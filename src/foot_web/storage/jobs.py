"""每日计划与独立复盘任务。所有调度领取在事务中先登记，避免重启重复调用。"""
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import Store

TZ = ZoneInfo('Asia/Shanghai')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS schedules (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL,
 time TEXT NOT NULL, offset INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
 next_due TEXT, actor TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_fires (
 id INTEGER PRIMARY KEY AUTOINCREMENT, schedule_id INTEGER NOT NULL, name TEXT NOT NULL,
 kind TEXT NOT NULL, due TEXT NOT NULL, business_date TEXT NOT NULL, actor TEXT NOT NULL,
 status TEXT NOT NULL, task_id TEXT, message TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(schedule_id, due)
);
CREATE TABLE IF NOT EXISTS review_runs (
 id TEXT PRIMARY KEY, business_date TEXT NOT NULL, status TEXT NOT NULL,
 requested_by TEXT NOT NULL, message TEXT NOT NULL, worker_pid INTEGER,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_review
 ON review_runs ((1)) WHERE status IN ('queued', 'running');
'''


class JobsStore:
    def __init__(self, data_dir):
        self.store = Store(Path(data_dir) / 'app.db')
        with self.store.connect() as db:
            db.executescript(SCHEMA)

    def schedules(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM schedules ORDER BY time, id')]

    def save_schedule(self, data, actor, now=None):
        now = (now or datetime.now(TZ)).astimezone(TZ)
        name, kind, clock = data.get('name', '').strip(), data.get('kind'), data.get('time', '')
        if not 1 <= len(name) <= 80 or kind not in ('analysis', 'review'):
            raise ValueError('名称须为1–80字，任务类型须为分析或复盘')
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', clock):
            raise ValueError('执行时间须为24小时制 HH:MM')
        if str(data.get('offset', '0')) not in ('0', '-1', '-2'):
            raise ValueError('业务日偏移仅支持当日、前1日、前2日')
        offset = int(data.get('offset', 0))
        enabled = data.get('enabled') == '1'
        due = now.replace(hour=int(clock[:2]), minute=int(clock[3:]), second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        schedule_id = data.get('id')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if schedule_id:
                if not str(schedule_id).isdigit() or not db.execute('SELECT 1 FROM schedules WHERE id=?', (schedule_id,)).fetchone():
                    raise ValueError('计划不存在，请刷新页面')
                db.execute('UPDATE schedules SET name=?,kind=?,time=?,offset=?,enabled=?,next_due=?,actor=?,updated_at=? WHERE id=?',
                           (name, kind, clock, offset, enabled, due.isoformat() if enabled else None, actor, now.isoformat(), schedule_id))
            else:
                if db.execute('SELECT count(*) FROM schedules').fetchone()[0] >= 12:
                    raise ValueError('最多保留12个计划，请编辑已有计划')
                schedule_id = db.execute('INSERT INTO schedules(name,kind,time,offset,enabled,next_due,actor,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                                         (name, kind, clock, offset, enabled, due.isoformat() if enabled else None, actor, now.isoformat())).lastrowid
            return dict(db.execute('SELECT * FROM schedules WHERE id=?', (schedule_id,)).fetchone())

    def claim_due(self, now):
        stamp = now.isoformat()
        claimed = []
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # 超过一分钟还未完成派发的记录不会重试，以免崩溃后重复消耗模型额度。
            db.execute("UPDATE schedule_fires SET status='interrupted',message='派发中断，未自动重试；请核查任务记录',updated_at=? WHERE status='dispatching' AND updated_at<?",
                       (stamp, (now - timedelta(minutes=1)).isoformat()))
            for row in db.execute('SELECT * FROM schedules WHERE enabled=1 AND next_due<=?', (stamp,)).fetchall():
                due = datetime.fromisoformat(row['next_due'])
                # 离线多日只考虑最近一次应执行时刻。
                due += timedelta(days=max(0, (now.date() - due.date()).days))
                if due > now:
                    due -= timedelta(days=1)
                late = now - due > timedelta(minutes=15)
                result = db.execute('''INSERT OR IGNORE INTO schedule_fires
                    (schedule_id,name,kind,due,business_date,actor,status,message,updated_at) VALUES(?,?,?,?,?,?,?,?,?)''',
                    (row['id'], row['name'], row['kind'], due.isoformat(), (due.date() + timedelta(days=row['offset'])).isoformat(),
                     row['actor'], 'skipped' if late else 'dispatching', '已过期，未补跑' if late else '正在派发', stamp))
                db.execute('UPDATE schedules SET next_due=? WHERE id=?', ((due + timedelta(days=1)).isoformat(), row['id']))
                if result.rowcount:
                    claimed.append(dict(db.execute('SELECT * FROM schedule_fires WHERE id=?', (result.lastrowid,)).fetchone()))
        return claimed

    def finish_fire(self, fire_id, status, message, task_id=None):
        with self.store.connect() as db:
            db.execute('UPDATE schedule_fires SET status=?,message=?,task_id=?,updated_at=? WHERE id=? AND status=\'dispatching\'',
                       (status, message, task_id, datetime.now(TZ).isoformat(), fire_id))

    def fires(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM schedule_fires ORDER BY id DESC LIMIT 60')]

    def begin_review(self, task_id, business_date, actor):
        now = datetime.now(TZ).isoformat()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM review_runs WHERE status IN ('queued','running')").fetchone()
            if row:
                return dict(row), False
            db.execute("INSERT INTO review_runs(id,business_date,status,requested_by,message,created_at,updated_at) VALUES(?,?,'queued',?,'等待后台复盘',?,?)",
                       (task_id, business_date, actor, now, now))
            return dict(db.execute('SELECT * FROM review_runs WHERE id=?', (task_id,)).fetchone()), True

    def review(self, task_id):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM review_runs WHERE id=?', (task_id,)).fetchone()
            return dict(row) if row else None

    def reviews(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM review_runs ORDER BY created_at DESC,id DESC LIMIT 60')]

    def update_review(self, task_id, **fields):
        if fields.keys() - {'status', 'message', 'worker_pid', 'finished_at'}:
            raise ValueError('无效更新字段')
        fields['updated_at'] = datetime.now(TZ).isoformat()
        with self.store.connect() as db:
            db.execute('UPDATE review_runs SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', (*fields.values(), task_id))
        return self.review(task_id)

    def claim_review(self, task_id, pid):
        with self.store.connect() as db:
            return db.execute("UPDATE review_runs SET status='running',worker_pid=?,message='正在冻结原票并获取官方赛果',updated_at=? WHERE id=? AND status='queued'",
                              (pid, datetime.now(TZ).isoformat(), task_id)).rowcount == 1

    def interrupt_review(self, task_id, pid):
        with self.store.connect() as db:
            db.execute("UPDATE review_runs SET status='interrupted',message='后台复盘已中断，请重新发起',finished_at=?,updated_at=? WHERE id=? AND worker_pid IS ? AND status IN ('queued','running')",
                       (datetime.now(TZ).isoformat(), datetime.now(TZ).isoformat(), task_id, pid))
        return self.review(task_id)
