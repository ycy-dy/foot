"""Versioned audit records and atomic promotion of immutable publication artifacts."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import Store

SCHEMA = '''
CREATE TABLE IF NOT EXISTS research_checks (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS checks_task ON research_checks(task_id,created_at);
CREATE TABLE IF NOT EXISTS publications (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL, check_id TEXT NOT NULL UNIQUE, business_date TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL, actor TEXT NOT NULL, previous_id TEXT,
 payload TEXT NOT NULL, tickets TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publication_current (business_date TEXT PRIMARY KEY, publication_id TEXT NOT NULL);
'''


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str)


class PublicationsStore:
    def __init__(self, data_dir):
        self.store = Store(Path(data_dir) / 'app.db')
        with self.store.connect() as db:
            db.executescript(SCHEMA)

    def save_check(self, check):
        with self.store.connect() as db:
            db.execute('INSERT INTO research_checks(id,task_id,created_at,payload) VALUES(?,?,?,?)',
                       (check['id'], check['task_id'], check['created_at'], encoded(check)))

    def check(self, check_id):
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM research_checks WHERE id=?', (check_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def latest_check(self, task_id):
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM research_checks WHERE task_id=? ORDER BY created_at DESC,id DESC LIMIT 1',
                             (task_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def by_check(self, check_id):
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM publications WHERE check_id=?', (check_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def current(self, business_date):
        with self.store.connect() as db:
            row = db.execute('''SELECT p.payload FROM publication_current c JOIN publications p
                            ON c.publication_id=p.id WHERE c.business_date=?''', (business_date,)).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, publication_id):
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM publications WHERE id=?', (publication_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, business_date=None):
        with self.store.connect() as db:
            rows = db.execute('SELECT payload FROM publications'
                              + (' WHERE business_date=?' if business_date else '')
                              + ' ORDER BY created_at DESC,id DESC',
                              (business_date,) if business_date else ()).fetchall()
        return [json.loads(row[0]) for row in rows]

    def promote(self, publication, tickets):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload FROM publications WHERE check_id=?', (publication['check_id'],)).fetchone()
            if existing:
                return json.loads(existing[0]), False
            db.execute('''INSERT INTO publications
                (id,task_id,check_id,business_date,status,created_at,actor,previous_id,payload,tickets)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (publication['id'], publication['task_id'], publication['check_id'], publication['business_date'],
                 'published', publication['created_at'], publication['actor'], publication['previous_id'],
                 encoded(publication), encoded(tickets)))
            db.execute('INSERT INTO publication_current(business_date,publication_id) VALUES(?,?) '
                       'ON CONFLICT(business_date) DO UPDATE SET publication_id=excluded.publication_id',
                       (publication['business_date'], publication['id']))
        return publication, True

    def tickets(self, business_date=None):
        return published_tickets(self.store.path, business_date)

    def withdraw(self, publication_id, actor, reason, now):
        reason = reason.strip()
        if not reason or len(reason) > 500:
            raise ValueError('请填写1–500字的撤销说明')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload,business_date,status FROM publications WHERE id=?', (publication_id,)).fetchone()
            if not row:
                raise KeyError(publication_id)
            current = db.execute('SELECT publication_id FROM publication_current WHERE business_date=?',
                                 (row['business_date'],)).fetchone()
            if not current or current[0] != publication_id:
                raise ValueError('该版本已被替代，不能撤销其他版本')
            publication = json.loads(row['payload'])
            if row['status'] == 'withdrawn':
                return publication, False
            publication.update(status='withdrawn', withdrawn_at=now.isoformat(),
                               withdrawal_reason=reason, withdrawn_by=actor)
            db.execute("UPDATE publications SET status='withdrawn',payload=? WHERE id=?",
                       (encoded(publication), publication_id))
        self.store.event('publication_withdrawn', actor, detail={'id': publication_id, 'reason': reason})
        return publication, True


def ticket_slot(ticket):
    if ticket.get('slot_id'):
        return ticket['slot_id']
    kind, title = ticket.get('kind', ''), ticket.get('title', '')
    if kind == '足球最终串':
        return 'football:late' if '晚' in title else 'football:first' if any(s in title for s in ('早', '中')) else kind + ':' + title
    if kind == '篮球最终串':
        return 'basketball:early' if '早' in title else 'basketball:late' if '晚' in title else kind + ':' + title
    if kind in ('足球单场方向', '篮球单场方向'):
        numbers = ','.join(str(leg.get('number', '')) for leg in ticket.get('legs', []))
        return kind + ':' + title + ':' + numbers
    if ticket.get('ledger') == 'structure' or '结构' in kind:
        return 'structure:' + title
    return kind


def _time(value):
    parsed = datetime.fromisoformat(str(value))
    tz = ZoneInfo('Asia/Shanghai')
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)


def select_effective_tickets(records):
    """Replace each slot only before its first kickoff; never erase an already-started original."""
    selected = {}
    def order(row):
        try:
            return _time(row.get('published_at') or row.get('snapshot') or row.get('as_of'))
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    for row in sorted(records, key=order):
        if row.get('superseded'):
            continue
        key = (row['business_date'], ticket_slot(row))
        previous = selected.get(key)
        if previous is not None:
            if order(previous) == order(row) and previous.get('legs') == row.get('legs'):
                row['superseded'] = True
                row['version_note'] = '重复原记录，仅保留一条统计'
                continue
            try:
                before_start = bool(previous.get('legs')) and order(row) > datetime.min.replace(tzinfo=ZoneInfo('Asia/Shanghai')) and all(
                    _time(leg['kickoff']) > order(row) for leg in previous['legs'])
            except (ValueError, KeyError, TypeError):
                before_start = False
            if before_start:
                previous['superseded'] = True
                previous['version_note'] = '首腿开赛前已被同一时段/栏目新版本替代'
            else:
                row['superseded'] = True
                row['after_freeze_revision'] = True
                row['version_note'] = '原时段已开始或原时点不明；此后修订另存研究，不替代原票命中记录'
                continue
        selected[key] = row
    return records


def published_tickets(db_path, business_date=None):
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publications'").fetchone():
            return []
        rows = db.execute('''SELECT p.id,p.business_date,p.tickets,p.status,p.payload,c.publication_id FROM publications p
            LEFT JOIN publication_current c ON p.business_date=c.business_date'''
            + (' WHERE p.business_date=?' if business_date else '') + ' ORDER BY p.created_at,p.id',
            (business_date,) if business_date else ()).fetchall()
    result = []
    for row in rows:
        for ticket in json.loads(row['tickets']):
            ticket.setdefault('superseded', False)
            ticket['publication_id'] = row['id']
            ticket['withdrawn'] = row['status'] == 'withdrawn'
            ticket['withdrawal_reason'] = json.loads(row['payload']).get('withdrawal_reason', '')
            result.append(ticket)
    return select_effective_tickets(result)
