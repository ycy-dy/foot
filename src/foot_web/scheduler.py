"""北京时间每日计划；由wsgi启动，普通create_app/测试不会启动线程。"""
import fcntl
import logging
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .core.config import id_set
from .storage.jobs import JobsStore

TZ = ZoneInfo('Asia/Shanghai')
logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, config, analysis_tasks, review_tasks, jobs=None, operations=None):
        self.config = config
        self.analysis = analysis_tasks
        self.review = review_tasks
        self.jobs = jobs or JobsStore(config['DATA_DIR'])
        self.operations = operations
        self.lock = Path(config['DATA_DIR']) / 'scheduler.lock'
        self._stop = threading.Event()
        self._thread = None

    def tick(self, now=None):
        # No active policy: do not dispatch stored plans or send notifications.
        # No policy: stored plans and notifications remain inactive.
        return

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        def loop():
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception:
                    logger.exception('Scheduler tick failed; retry on next tick')
                self._stop.wait(20)
        self._thread = threading.Thread(target=loop, name='foot-scheduler', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
