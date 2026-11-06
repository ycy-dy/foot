"""Atomic checkpoints for resumable analysis; successful match payloads stay immutable."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import Store

TZ = ZoneInfo('Asia/Shanghai')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS research_workflows (
 task_id TEXT PRIMARY KEY, manifest TEXT NOT NULL, source TEXT NOT NULL,
 cancel_requested INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 1,
 phase TEXT NOT NULL DEFAULT 'snapshot', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_matches (
 task_id TEXT NOT NULL, match_key TEXT NOT NULL, sport TEXT NOT NULL, num TEXT NOT NULL,
 match_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', message TEXT NOT NULL DEFAULT '',
 payload TEXT, attempts TEXT NOT NULL DEFAULT '[]', as_of TEXT, updated_at TEXT NOT NULL,
 PRIMARY KEY(task_id, match_key)
);
CREATE INDEX IF NOT EXISTS research_matches_task ON research_matches(task_id, sport, num);
CREATE TABLE IF NOT EXISTS research_reuse (task_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL);
'''


def stamp():
    return datetime.now(TZ).isoformat(timespec='seconds')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str)


class ResearchStore:
    def __init__(self, data_dir):
        self.store = Store(Path(data_dir) / 'app.db')
        with self.store.connect() as db:
            db.executescript(SCHEMA)

    def workflow(self, task_id):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM research_workflows WHERE task_id=?', (task_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result['manifest'] = json.loads(result['manifest'])
        result['source'] = json.loads(result['source'])
        return result

    def initialize(self, task_id, manifest, source, items):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO research_workflows(task_id,manifest,source,updated_at) VALUES(?,?,?,?)',
                       (task_id, encode(manifest), encode(source), stamp()))
            for item in items:
                db.execute('''INSERT INTO research_matches
                    (task_id,match_key,sport,num,match_json,status,message,updated_at) VALUES(?,?,?,?,?,?,?,?)''',
                    (task_id, item['match_key'], item['match']['sport'], item['match']['num'], encode(item['match']),
                     'excluded' if item.get('reason') else 'pending', item.get('reason') or '等待逐场研究', stamp()))

    def set_parent(self, task_id, parent_id):
        with self.store.connect() as db:
            db.execute('INSERT INTO research_reuse(task_id,parent_id) VALUES(?,?)', (task_id, parent_id))

    def parent(self, task_id):
        with self.store.connect() as db:
            row = db.execute('SELECT parent_id FROM research_reuse WHERE task_id=?', (task_id,)).fetchone()
        return row[0] if row else None

    def items(self, task_id):
        with self.store.connect() as db:
            rows = db.execute('SELECT * FROM research_matches WHERE task_id=? ORDER BY json_extract(match_json, \'$.kickoff\'),sport,num',
                              (task_id,)).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            value['match'] = json.loads(value.pop('match_json'))
            for key in ('payload', 'attempts'):
                value[key] = json.loads(value[key]) if value[key] else None
            result.append(value)
        return result

    def update_item(self, task_id, key, **fields):
        if not fields or fields.keys() - {'status', 'message', 'payload', 'attempts', 'as_of'}:
            raise ValueError('无效逐场更新')
        for name in ('payload', 'attempts'):
            if name in fields:
                fields[name] = encode(fields[name])
        fields['updated_at'] = stamp()
        with self.store.connect() as db:
            changed = db.execute('UPDATE research_matches SET ' + ','.join(k + '=?' for k in fields)
                                + " WHERE task_id=? AND match_key=? AND status!='succeeded'",
                                (*fields.values(), task_id, key)).rowcount
        return changed == 1

    def phase(self, task_id, value):
        with self.store.connect() as db:
            db.execute('UPDATE research_workflows SET phase=?,updated_at=? WHERE task_id=?', (value, stamp(), task_id))

    def cancelled(self, task_id):
        with self.store.connect() as db:
            row = db.execute('SELECT cancel_requested FROM research_workflows WHERE task_id=?', (task_id,)).fetchone()
            # Queued tasks can be cancelled before their snapshot exists.
            task = db.execute('SELECT status,message FROM analysis_runs WHERE id=?', (task_id,)).fetchone()
        return bool(row and row[0]) or bool(task and (task['status'] == 'cancelled' or task['message'] == '正在取消，等待CLI清理'))

    def cancel(self, task_id):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status FROM analysis_runs WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            if row['status'] == 'queued':
                db.execute("UPDATE analysis_runs SET status='cancelled',message='已取消排队任务',finished_at=?,updated_at=? WHERE id=?",
                           (stamp(), stamp(), task_id))
            elif row['status'] == 'running':
                db.execute("UPDATE analysis_runs SET message='正在取消，等待CLI清理',updated_at=? WHERE id=?", (stamp(), task_id))
            db.execute('UPDATE research_workflows SET cancel_requested=1,updated_at=? WHERE task_id=?', (stamp(), task_id))

    def resume(self, task_id):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM analysis_runs WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            active = db.execute("SELECT * FROM analysis_runs WHERE status IN ('queued','running')").fetchone()
            if active:
                return dict(active), False
            if row['status'] not in ('partial', 'failed', 'cancelled', 'interrupted'):
                raise ValueError('只有未完成任务可以续跑')
            if not db.execute('SELECT 1 FROM research_workflows WHERE task_id=?', (task_id,)).fetchone():
                raise ValueError('旧任务没有逐场检查点，请重新分析')
            db.execute("UPDATE research_workflows SET cancel_requested=0,generation=generation+1,updated_at=? WHERE task_id=?",
                       (stamp(), task_id))
            db.execute("UPDATE research_matches SET status='pending',message='等待续跑',updated_at=? WHERE task_id=? AND status IN ('failed','running')",
                       (stamp(), task_id))
            db.execute("UPDATE analysis_runs SET status='queued',provider=NULL,message='等待继续逐场分析',worker_pid=NULL,finished_at=NULL,updated_at=? WHERE id=?",
                       (stamp(), task_id))
            return dict(db.execute('SELECT * FROM analysis_runs WHERE id=?', (task_id,)).fetchone()), True

    def progress(self, task_id):
        with self.store.connect() as db:
            rows = db.execute('SELECT status,count(*) AS n FROM research_matches WHERE task_id=? GROUP BY status', (task_id,)).fetchall()
            workflow = db.execute('SELECT phase,generation,cancel_requested FROM research_workflows WHERE task_id=?', (task_id,)).fetchone()
            reused = db.execute("SELECT count(*) FROM research_matches WHERE task_id=? AND json_extract(attempts,'$[0].code')='cached'",
                                (task_id,)).fetchone()[0]
        counts = {row['status']: row['n'] for row in rows}
        return {'total': sum(counts.values()), 'completed': counts.get('succeeded', 0),
                'excluded': counts.get('excluded', 0), 'failed': counts.get('failed', 0),
                'pending': counts.get('pending', 0), 'running': counts.get('running', 0),
                'phase': workflow['phase'] if workflow else 'snapshot',
                'generation': workflow['generation'] if workflow else 0,
                'reused': reused,
                'cancel_requested': bool(workflow and workflow['cancel_requested'])}
