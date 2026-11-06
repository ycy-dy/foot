"""Opt-in notification outbox; uncertain submissions are never automatically repeated."""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import Store

TZ = ZoneInfo('Asia/Shanghai')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS notification_preferences (
 id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
 origin TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT '',
 recipient_sha256 TEXT NOT NULL DEFAULT '', enabled_at TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_outbox (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL, resource_path TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, next_due TEXT NOT NULL, updated_at TEXT NOT NULL,
 task_id TEXT, message TEXT NOT NULL DEFAULT ''
);
'''


class NotificationStore:
    def __init__(self, data_dir):
        self.store = Store(Path(data_dir) / 'app.db')
        with self.store.connect() as db:
            db.executescript(SCHEMA)
            db.execute('INSERT OR IGNORE INTO notification_preferences(id,updated_at) VALUES(1,?)',
                       (datetime.now(TZ).isoformat(),))

    def preferences(self):
        with self.store.connect() as db:
            return dict(db.execute('SELECT * FROM notification_preferences WHERE id=1').fetchone())

    def save_preferences(self, enabled, origin, actor, recipients_hash, now):
        with self.store.connect() as db:
            enabled_at = now.isoformat() if enabled else None
            db.execute('''UPDATE notification_preferences
                SET enabled=?,origin=?,actor=?,recipient_sha256=?,enabled_at=?,updated_at=? WHERE id=1''',
                (bool(enabled), origin, actor, recipients_hash, enabled_at, now.isoformat()))
            if not enabled:
                db.execute("UPDATE notification_outbox SET state='skipped',message='通知已停用，未发送',updated_at=? WHERE state IN ('queued','retry')",
                           (now.isoformat(),))
            else:
                db.execute("UPDATE notification_outbox SET state='skipped',message='通知目标重新确认，不补发旧提醒',updated_at=? "
                           "WHERE state IN ('queued','retry') AND created_at<?", (now.isoformat(), now.isoformat()))

    def enqueue(self, event_key, kind, title, summary, path, now):
        with self.store.connect() as db:
            return db.execute('''INSERT OR IGNORE INTO notification_outbox
                (event_key,kind,title,summary,resource_path,created_at,next_due,updated_at) VALUES(?,?,?,?,?,?,?,?)''',
                (event_key, kind, title, summary, path, now.isoformat(), now.isoformat(), now.isoformat())).rowcount == 1

    def claim(self, now):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE notification_outbox SET state='uncertain',message='发送进程中断，结果待核；未自动重发',updated_at=? "
                       "WHERE state='sending' AND updated_at<?",
                       (now.isoformat(), (now-timedelta(minutes=1)).isoformat()))
            row = db.execute("SELECT * FROM notification_outbox WHERE state IN ('queued','retry') AND next_due<=? "
                             "ORDER BY id LIMIT 1", (now.isoformat(),)).fetchone()
            if not row:
                return None
            db.execute("UPDATE notification_outbox SET state='sending',attempts=attempts+1,updated_at=? WHERE id=?",
                       (now.isoformat(), row['id']))
            return dict(db.execute('SELECT * FROM notification_outbox WHERE id=?', (row['id'],)).fetchone())

    def finish(self, row_id, state, message, now, task_id=None, retry_after=None):
        due = (now+timedelta(seconds=retry_after or 0)).isoformat()
        with self.store.connect() as db:
            db.execute('UPDATE notification_outbox SET state=?,message=?,task_id=?,updated_at=?,next_due=? WHERE id=?',
                       (state, message, str(task_id) if task_id is not None else None, now.isoformat(), due, row_id))

    def list(self):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM notification_outbox ORDER BY id DESC LIMIT 80')]
