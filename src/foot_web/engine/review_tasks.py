"""复盘独立进程：核验结算 + 必须成功的Claude/Codex分析，不自动发布。"""
import errno
import os
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..storage.jobs import JobsStore

TZ = ZoneInfo('Asia/Shanghai')
ACTIVE = {'queued', 'running'}


def launch_review(config, task_id):
    folder = Path(config['DATA_DIR']) / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'review-worker.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, '-m', 'foot_web.engine.review_worker', '--task-id', task_id,
                                  '--project-dir', config['PROJECT_DIR'], '--data-dir', config['DATA_DIR']],
                                 cwd=config['PROJECT_DIR'], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True)
    threading.Thread(target=child.wait, daemon=True).start()
    return child.pid


class ReviewTasks:
    def __init__(self, config, jobs=None, launcher=None):
        self.config = config
        self.jobs = jobs or JobsStore(config['DATA_DIR'])
        self.launcher = launcher or launch_review

    def _recover(self, row):
        if not row or row['status'] not in ACTIVE:
            return row
        pid = row['worker_pid']
        dead = False
        if pid:
            try:
                os.kill(pid, 0)
            except OSError as exc:
                dead = exc.errno == errno.ESRCH
        else:
            dead = (datetime.now(TZ) - datetime.fromisoformat(row['created_at'])).total_seconds() > 30
        return self.jobs.interrupt_review(row['id'], pid) if dead else row

    def get(self, task_id):
        return self._recover(self.jobs.review(task_id))

    def latest(self):
        return [self._recover(row) for row in self.jobs.reviews()]

    def start(self, business_date, actor):
        raise ValueError('业务体系已删除，新的AI复盘任务已停用；既有记录仍可读取')


def run_review(config, task_id, service=None):
    jobs = JobsStore(config['DATA_DIR'])
    if not jobs.claim_review(task_id, os.getpid()):
        return
    task = jobs.review(task_id)
    try:
        raise ValueError('业务体系已删除，后台复盘策略已停用')
    except Exception as exc:
        # 只公开我们定义的缺原票错误，外部响应/路径/凭证不写任务消息。
        from .providers import ProviderError
        message = ('没有可复盘的冻结原票' if isinstance(exc, ValueError) and '冻结原票' in str(exc) else
                   'AI复盘未完成：Claude/Codex未返回有效结果，上一成功台账不变' if isinstance(exc, ProviderError) else
                   '复盘失败：原票、官方赛果或规则资料不可用，请稍后重试')
        jobs.update_review(task_id, status='failed', message=message, finished_at=datetime.now(TZ).isoformat())
        jobs.store.event('review_failed', task['requested_by'], detail={'task_id': task_id, 'error_type': type(exc).__name__})
        return
    jobs.update_review(task_id, status='succeeded', message='AI复盘与确定性结算已完成；未知结果仍待核，台账已更新',
                       finished_at=datetime.now(TZ).isoformat())
    # 审计日志失败不能将已经成功提交的复盘/台账错误改为失败。
    jobs.store.event('review_completed', task['requested_by'], detail={'task_id': task_id, 'date': task['business_date']})

