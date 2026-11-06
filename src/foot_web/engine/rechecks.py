"""Independent, bounded live rechecks; scheduling never occupies a request with research."""
import errno
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..data.fetcher import Fetcher
from ..storage.monitoring import MonitoringStore
from ..storage.publications import PublicationsStore
from ..services.research import EVIDENCE_SCHEMA, make_match_prompt, moment, validate_evidence
from ..services.rechecks import RecheckService
from ..services.versions import research_rules, rules_manifest
from .decisions import decide

TZ = ZoneInfo('Asia/Shanghai')


class RecheckTasks:
    def __init__(self, config, store=None, launcher=None):
        self.config, self.store = config, store or MonitoringStore(config['DATA_DIR'])
        self.launcher = launcher or self.launch

    def launch(self, task_id):
        folder = Path(self.config['DATA_DIR']) / 'logs'
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / 'recheck-worker.log').open('ab') as handle:
            child = subprocess.Popen([sys.executable, '-m', 'foot_web.engine.recheck_worker',
                '--task-id', task_id, '--project-dir', self.config['PROJECT_DIR'], '--data-dir', self.config['DATA_DIR']],
                stdin=subprocess.DEVNULL, stdout=handle, stderr=handle, cwd=self.config['PROJECT_DIR'], start_new_session=True)
        threading.Thread(target=child.wait, daemon=True).start()
        return child.pid

    def recover(self, task):
        if not task or task['status'] not in ('queued', 'running'):
            return task
        pid = task['worker_pid']
        dead = False
        if pid:
            try:
                os.kill(pid, 0)
            except OSError as exc:
                dead = exc.errno == errno.ESRCH
        else:
            dead = (datetime.now(TZ)-moment(task['created_at'])).total_seconds() > 30
        if dead:
            return self.store.update(task['id'], status='interrupted', message='临场进程中断，已保存资料保留',
                                     finished_at=datetime.now(TZ).isoformat())
        return task

    def get(self, task_id):
        return self.recover(self.store.get(task_id))

    def start(self, publication_id, actor, lineup_enabled=False, trigger_key=None):
        raise ValueError('业务体系已删除，新的临场策略复核已停用')


def run_recheck(config, task_id, fetcher=None, analyst=None):
    store = MonitoringStore(config['DATA_DIR'])
    if not store.claim(task_id, os.getpid()):
        return
    task = store.get(task_id)
    try:
        raise ValueError('业务体系已删除，后台临场策略已停用')
    except Exception as exc:
        cancelled = store.cancelled(task_id)
        store.update(task_id, status='cancelled' if cancelled else 'failed',
                     message='复核已取消，已保存资料保留' if cancelled else '临场复核未完成：' + type(exc).__name__,
                     finished_at=datetime.now(TZ).isoformat())
