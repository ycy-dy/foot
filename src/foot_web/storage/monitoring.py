"""Durable, opt-in monitoring preferences, jobs and factual evidence cache."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import Store

TZ = ZoneInfo('Asia/Shanghai')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS monitoring_preferences (
 id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
 lineup_enabled INTEGER NOT NULL DEFAULT 0, lead_minutes INTEGER NOT NULL DEFAULT 60,
 interval_minutes INTEGER NOT NULL DEFAULT 10, actor TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recheck_runs (
 id TEXT PRIMARY KEY, publication_id TEXT NOT NULL, trigger_key TEXT NOT NULL,
 actor TEXT NOT NULL, status TEXT NOT NULL, lineup_enabled INTEGER NOT NULL,
 message TEXT NOT NULL, worker_pid INTEGER, cancel_requested INTEGER NOT NULL DEFAULT 0,
 payload TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT,
 UNIQUE(publication_id,trigger_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_recheck ON recheck_runs((1)) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS recheck_evidence (
 publication_id TEXT NOT NULL, match_key TEXT NOT NULL, as_of TEXT NOT NULL,
 payload TEXT NOT NULL, artifact TEXT NOT NULL, PRIMARY KEY(publication_id,match_key)
);
'''


def stamp():
    return datetime.now(TZ).isoformat(timespec='seconds')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str)


class MonitoringStore:
    def __init__(self, data_dir):
        self.store = Store(Path(data_dir) / 'app.db')
        with self.store.connect() as db:
            db.executescript(SCHEMA)
            db.execute('INSERT OR IGNORE INTO monitoring_preferences(id,updated_at) VALUES(1,?)', (stamp(),))

    def preferences(self):
        with self.store.connect() as db:
            return dict(db.execute('SELECT * FROM monitoring_preferences WHERE id=1').fetchone())

    def save_preferences(self, data, actor):
        try:
            lead, interval = int(data.get('lead_minutes', '60')), int(data.get('interval_minutes', '10'))
        except (ValueError, TypeError):
            raise ValueError('复核提前量与间隔必须为整数') from None
        if not 15 <= lead <= 180 or not 5 <= interval <= 60:
            raise ValueError('提前量须为15–180分钟，间隔须为5–60分钟')
        with self.store.connect() as db:
            db.execute('''UPDATE monitoring_preferences
                SET enabled=?,lineup_enabled=?,lead_minutes=?,interval_minutes=?,actor=?,updated_at=? WHERE id=1''',
                (data.get('enabled') == '1', data.get('lineup_enabled') == '1', lead, interval, actor, stamp()))
        return self.preferences()

    def begin(self, task_id, publication_id, trigger_key, actor, lineup_enabled):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM recheck_runs WHERE publication_id=? AND trigger_key=?',
                                  (publication_id, trigger_key)).fetchone()
            active = db.execute("SELECT * FROM recheck_runs WHERE status IN ('queued','running')").fetchone()
            if previous or active:
                return dict(previous or active), False
            db.execute('''INSERT INTO recheck_runs
                (id,publication_id,trigger_key,actor,status,lineup_enabled,message,created_at,updated_at)
                VALUES(?,?,?,?,'queued',?,'等待临场复核',?,?)''',
                (task_id, publication_id, trigger_key, actor, bool(lineup_enabled), stamp(), stamp()))
            return dict(db.execute('SELECT * FROM recheck_runs WHERE id=?', (task_id,)).fetchone()), True

    @staticmethod
    def decode(row):
        if not row:
            return None
        value = dict(row)
        value['payload'] = json.loads(value['payload']) if value['payload'] else None
        return value

    def get(self, task_id):
        with self.store.connect() as db:
            return self.decode(db.execute('SELECT * FROM recheck_runs WHERE id=?', (task_id,)).fetchone())

    def list(self, publication_id=None):
        with self.store.connect() as db:
            rows = db.execute('SELECT * FROM recheck_runs' + (' WHERE publication_id=?' if publication_id else '')
                              + ' ORDER BY created_at DESC,id DESC LIMIT 60',
                              (publication_id,) if publication_id else ()).fetchall()
        return [self.decode(row) for row in rows]

    def update(self, task_id, **fields):
        if not fields or fields.keys() - {'status', 'message', 'payload', 'worker_pid', 'finished_at', 'cancel_requested'}:
            raise ValueError('无效临场任务更新')
        if 'payload' in fields:
            fields['payload'] = encode(fields['payload'])
        fields['updated_at'] = stamp()
        with self.store.connect() as db:
            db.execute('UPDATE recheck_runs SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?',
                       (*fields.values(), task_id))
        return self.get(task_id)

    def claim(self, task_id, pid):
        with self.store.connect() as db:
            return db.execute("UPDATE recheck_runs SET status='running',worker_pid=?,updated_at=?,message='正在刷新官方数据'"
                              " WHERE id=? AND status='queued'", (pid, stamp(), task_id)).rowcount == 1

    def cancelled(self, task_id):
        task = self.get(task_id)
        return bool(task and task['cancel_requested'])

    def cache(self, publication_id, match_key, as_of, payload, artifact):
        with self.store.connect() as db:
            db.execute('''INSERT INTO recheck_evidence(publication_id,match_key,as_of,payload,artifact) VALUES(?,?,?,?,?)
                ON CONFLICT(publication_id,match_key) DO UPDATE
                SET as_of=excluded.as_of,payload=excluded.payload,artifact=excluded.artifact''',
                (publication_id, match_key, as_of, encode(payload), artifact))

    def evidence(self, publication_id, match_key):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM recheck_evidence WHERE publication_id=? AND match_key=?',
                             (publication_id, match_key)).fetchone()
        return self.decode(row)
