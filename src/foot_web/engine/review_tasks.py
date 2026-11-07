"""复盘独立进程：核验结算 + 必须成功的DeepSeek Harness分析，不自动发布。"""
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
        from ..services.versions import rules_manifest
        manifest, _ = rules_manifest(self.config['PROJECT_DIR'])
        if manifest.get('compatibility') != 'supported_subset':
            raise ValueError('当前规则未通过兼容性检查，不能启动AI复盘')
        if date.fromisoformat(business_date).isoformat() != business_date:
            raise ValueError('业务日必须为YYYY-MM-DD')
        self.latest()
        task_id = 'review-' + datetime.now(TZ).strftime('%Y%m%dT%H%M%S%f') + '-' + uuid.uuid4().hex[:8]
        row, created = self.jobs.begin_review(task_id, business_date, actor)
        if created:
            try:
                row = self.jobs.update_review(task_id, worker_pid=self.launcher(self.config, task_id))
            except (OSError, subprocess.SubprocessError):
                row = self.jobs.update_review(task_id, status='failed', message='后台复盘进程无法启动',
                                              finished_at=datetime.now(TZ).isoformat())
        return row, not created


def run_review(config, task_id, service=None):
    jobs = JobsStore(config['DATA_DIR'])
    if not jobs.claim_review(task_id, os.getpid()):
        return
    task = jobs.review(task_id)
    try:
        from ..services.versions import rules_manifest, research_rules
        from ..services.reviews import ReviewService
        from ..services.review_analysis import REVIEW_SCHEMA, review_prompt, validate_review
        from .decisions import decide
        manifest, texts = rules_manifest(config['PROJECT_DIR'])
        if manifest.get('compatibility') != 'supported_subset':
            raise ValueError('当前规则未通过兼容性检查')
        def analyst(result):
            return decide(config, Path(result['folder']) / 'ai-review',
                          review_prompt(result, research_rules(texts)), REVIEW_SCHEMA,
                          lambda payload: validate_review(payload, result['rows']))
        reviewer = service or ReviewService(config, analyst=analyst)
        if not getattr(reviewer, 'analyst', None):
            raise ValueError('AI复盘分析器不可用，不更新成功台账')
        reviewer.run(task['business_date'], task_id)
    except Exception as exc:
        # 只公开我们定义的缺原票错误，外部响应/路径/凭证不写任务消息。
        from .providers import ProviderError
        message = ('没有可复盘的冻结原票' if isinstance(exc, ValueError) and '冻结原票' in str(exc) else
                   'AI复盘未完成：DeepSeek Harness未返回有效结果，上一成功台账不变' if isinstance(exc, ProviderError) else
                   '复盘失败：原票、官方赛果或规则资料不可用，请稍后重试')
        jobs.update_review(task_id, status='failed', message=message, finished_at=datetime.now(TZ).isoformat())
        jobs.store.event('review_failed', task['requested_by'], detail={'task_id': task_id, 'error_type': type(exc).__name__})
        return
    jobs.update_review(task_id, status='succeeded', message='AI复盘与确定性结算已完成；未知结果仍待核，台账已更新',
                       finished_at=datetime.now(TZ).isoformat())
    # 审计日志失败不能将已经成功提交的复盘/台账错误改为失败。
    jobs.store.event('review_completed', task['requested_by'], detail={'task_id': task_id, 'date': task['business_date']})

