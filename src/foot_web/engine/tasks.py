"""Cross-worker analysis admission, task control and frozen official inputs."""
import errno
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..data import markets
from ..storage.db import Store
from ..storage.research import ResearchStore
from .providers import generate as generate_report

TZ = ZoneInfo('Asia/Shanghai')
ACTIVE = {'queued', 'running'}


def public_task(row):
    if not row:
        return None
    keys = ('id', 'business_date', 'status', 'provider', 'message', 'created_at', 'updated_at', 'finished_at')
    result = {key: row[key] for key in keys}
    result['attempts'] = json.loads(row['attempts'])
    result['status_url'] = '/api/analysis/' + row['id']
    result['result_url'] = '/analysis/' + row['id']
    result['logs_url'] = '/api/analysis/' + row['id'] + '/logs'
    result['matches_url'] = '/api/analysis/' + row['id'] + '/matches'
    return result


def launch_worker(config, task_id):
    log_dir = Path(config['DATA_DIR']) / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'foot_web.engine.worker', '--task-id', task_id,
               '--project-dir', config['PROJECT_DIR'], '--data-dir', config['DATA_DIR']]
    with (log_dir / 'analysis-worker.log').open('ab') as log:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 cwd=config['PROJECT_DIR'], start_new_session=True)
    threading.Thread(target=child.wait, daemon=True).start()
    return child.pid


class AnalysisTasks:
    def __init__(self, config, store=None, launcher=None):
        self.config = config
        self.store = store or Store(Path(config['DATA_DIR']) / 'app.db')
        self.launcher = launcher or launch_worker
        self.research = ResearchStore(config['DATA_DIR'])

    def present(self, row):
        result = public_task(row)
        if result:
            result['progress'] = self.research.progress(row['id'])
            with self.store.connect() as db:
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publications'").fetchone()
                publication = db.execute('SELECT id,status FROM publications WHERE task_id=? ORDER BY created_at DESC LIMIT 1',
                                         (row['id'],)).fetchone() if exists else None
            result['publication_url'] = '/publications/' + publication['id'] if publication else None
            result['publication_state'] = publication['status'] if publication else None
        return result

    def _recover(self, row):
        if not row or row['status'] not in ACTIVE:
            return row
        pid = row['worker_pid']
        interrupted = False
        if pid:
            try:
                os.kill(pid, 0)
            except OSError as exc:
                interrupted = exc.errno == errno.ESRCH
        else:
            age = (datetime.now(TZ) - datetime.fromisoformat(row['created_at'])).total_seconds()
            interrupted = age > 30
        if interrupted:
            row = self.store.interrupt_analysis(row['id'], pid)
        return row

    def latest(self, business_date):
        return self.present(self._recover(self.store.latest_analysis(business_date)))

    def get(self, task_id):
        return self.present(self._recover(self.store.analysis(task_id)))

    def _launch(self, task_id):
        try:
            pid = self.launcher(self.config, task_id)
            return self.store.update_analysis(task_id, worker_pid=pid)
        except (OSError, subprocess.SubprocessError):
            self.store.analysis_log(task_id, 'system', 'error', '后台分析进程无法启动')
            return self.store.update_analysis(task_id, status='failed', message='后台分析进程无法启动',
                                              finished_at=datetime.now(TZ).isoformat(timespec='seconds'))

    def start(self, business_date, requested_by, reuse_from=None):
        raise ValueError('分析与推荐体系已删除，新分析已停用')

    def cancel(self, task_id, actor):
        self.research.cancel(task_id)
        self.store.event('analysis_cancel_requested', actor, detail={'task_id': task_id})
        return self.get(task_id)

    def resume(self, task_id, actor):
        raise ValueError('分析与推荐体系已删除，续跑已停用')


def output_dir(config, task):
    return Path(config['PROJECT_DIR']) / 'runs' / task['business_date'] / task['id']


def prepare_input(config, task, fetcher, as_of):
    fb_raw, fb_meta = fetcher.get('football', force=True)
    bk_raw, bk_meta = fetcher.get('basketball', force=True)
    fb = [row for row in markets.parse_football(fb_raw) if row['business_date'] == task['business_date']]
    bk = [row for row in markets.parse_basketball(bk_raw) if row['business_date'] == task['business_date']]
    if not fb and not bk:
        raise ValueError('当前业务日没有官方赛程')

    def metadata(value):
        return {key: value.get(key) for key in ('captured_at', 'source_update', 'sha256', 'stale')}

    return {'business_date': task['business_date'], 'as_of': as_of.isoformat(timespec='seconds'),
            'football_meta': metadata(fb_meta), 'basketball_meta': metadata(bk_meta),
            'football': fb, 'basketball': bk,
            'football_allup': (fb_raw.get('value') or {}).get('allUpList', {}),
            'basketball_allup': (bk_raw.get('value') or {}).get('allUpList', {}),
            'raw': {'football': fb_raw, 'basketball': bk_raw}}


def run_task(config, task_id, fetcher=None, generate=None, as_of=None):
    from .workflow import run_workflow
    run_workflow(config, task_id, prepare_input, generate or generate_report, fetcher=fetcher, as_of=as_of)
