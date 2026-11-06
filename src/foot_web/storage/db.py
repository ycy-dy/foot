"""SQLite：审计日志（登录、拒绝、登出、数据抓取等）。"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  user_id TEXT,
  name TEXT,
  event TEXT NOT NULL,
  ip TEXT,
  detail TEXT
);
CREATE TABLE IF NOT EXISTS analysis_runs (
  id TEXT PRIMARY KEY,
  business_date TEXT NOT NULL,
  status TEXT NOT NULL,
  provider TEXT,
  message TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT,
  worker_pid INTEGER,
  attempts TEXT NOT NULL DEFAULT '[]'
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_analysis
ON analysis_runs ((1)) WHERE status IN ('queued', 'running');
CREATE TABLE IF NOT EXISTS analysis_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  provider TEXT NOT NULL,
  kind TEXT NOT NULL,
  message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS analysis_logs_task_cursor ON analysis_logs (task_id, id);
'''


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def event(self, event, user_id='', name='', ip='', detail=None):
        with self.connect() as db:
            db.execute('INSERT INTO events (ts, user_id, name, event, ip, detail) VALUES (?,?,?,?,?,?)',
                       (datetime.now(TZ).isoformat(timespec='seconds'), user_id, name, event, ip,
                        json.dumps(detail, ensure_ascii=False) if detail is not None else None))

    def recent(self, limit=50):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,))]

    def begin_analysis(self, task_id, business_date, requested_by):
        now = datetime.now(TZ).isoformat(timespec='microseconds')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute("SELECT * FROM analysis_runs WHERE status IN ('queued', 'running')").fetchone()
            if active:
                return dict(active), False
            db.execute('''INSERT INTO analysis_runs
                       (id, business_date, status, message, requested_by, created_at, updated_at)
                       VALUES (?, ?, 'queued', ?, ?, ?, ?)''',
                       (task_id, business_date, '等待后台分析', requested_by, now, now))
        return self.analysis(task_id), True

    def analysis(self, task_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM analysis_runs WHERE id = ?', (task_id,)).fetchone()
            return dict(row) if row else None

    def analysis_log(self, task_id, provider, kind, message):
        if provider not in ('system', 'claude', 'codex') or kind not in (
                'status', 'start', 'tool', 'output', 'warning', 'error', 'heartbeat'):
            raise ValueError('无效日志类型')
        with self.connect() as db:
            db.execute('INSERT INTO analysis_logs (task_id, ts, provider, kind, message) VALUES (?,?,?,?,?)',
                       (task_id, datetime.now(TZ).isoformat(timespec='seconds'), provider, kind, message[:4000]))
            db.execute('''DELETE FROM analysis_logs WHERE task_id = ? AND id < (
                       SELECT id FROM analysis_logs WHERE task_id = ? ORDER BY id DESC LIMIT 1 OFFSET 1999)''',
                       (task_id, task_id))

    def analysis_logs(self, task_id, after=0, limit=200):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT id, ts, provider, kind, message FROM analysis_logs WHERE task_id = ? AND id > ? ORDER BY id LIMIT ?',
                (task_id, after, min(2000, max(1, limit))))]

    def latest_analysis(self, business_date):
        with self.connect() as db:
            row = db.execute("""SELECT * FROM analysis_runs WHERE status IN ('queued', 'running')
                             OR business_date = ?
                             ORDER BY (status IN ('queued', 'running')) DESC, created_at DESC, id DESC LIMIT 1""",
                             (business_date,)).fetchone()
            return dict(row) if row else None

    def update_analysis(self, task_id, **fields):
        allowed = {'status', 'provider', 'message', 'worker_pid', 'attempts', 'finished_at'}
        if not fields or fields.keys() - allowed:
            raise ValueError('无效的任务更新字段')
        fields['updated_at'] = datetime.now(TZ).isoformat(timespec='seconds')
        if 'attempts' in fields:
            fields['attempts'] = json.dumps(fields['attempts'], ensure_ascii=False)
        with self.connect() as db:
            db.execute(f'UPDATE analysis_runs SET {", ".join(key + " = ?" for key in fields)} WHERE id = ?',
                       (*fields.values(), task_id))
        return self.analysis(task_id)

    def claim_analysis(self, task_id, worker_pid):
        with self.connect() as db:
            changed = db.execute("""UPDATE analysis_runs SET status = 'running', provider = NULL,
                                  message = '正在刷新官方快照', worker_pid = ?, updated_at = ?
                                  WHERE id = ? AND status = 'queued'""",
                                 (worker_pid, datetime.now(TZ).isoformat(timespec='seconds'), task_id)).rowcount
        return changed == 1

    def interrupt_analysis(self, task_id, expected_pid):
        now = datetime.now(TZ).isoformat(timespec='seconds')
        with self.connect() as db:
            db.execute("""UPDATE analysis_runs SET status = 'interrupted', message = ?, updated_at = ?, finished_at = ?
                       WHERE id = ? AND status IN ('queued', 'running') AND worker_pid IS ?""",
                       ('后台分析已中断，请重新发起', now, now, task_id, expected_pid))
        return self.analysis(task_id)
