"""台账查询、历史推荐与命中率统计（数据：ledger/data/settled_records.json，由 build_ledgers.py 结算生成）。

口径：默认排除已被替代的版本；命中率分母只计已结算（hit 为 True/False），待定（None）单列；
模拟单位与理论返还只是数学示例，实际投注金额与返还固定为 null（V6/AGENTS）。
"""
import copy
import json
import sqlite3
from collections import OrderedDict, defaultdict
from decimal import Decimal
from pathlib import Path

GROUPS = OrderedDict([
    ('最终推荐', ['足球最终串', '篮球最终串']),
    ('单场方向', ['足球单场方向', '篮球单场方向']),
    ('六类方向', ['胜平负', '让球', '进球数', '二三球', '半全场', '双平']),
    ('结构研究', ['结构研究', '足球结构研究', '篮球结构研究']),
    ('梦想单', ['梦想单']),
])
KIND_GROUP = {k: g for g, ks in GROUPS.items() for k in ks}


class Ledger:
    def __init__(self, project_dir, data_dir=None):
        self.path = Path(project_dir) / 'ledger' / 'data' / 'settled_records.json'
        self.db_path = Path(data_dir or Path(project_dir) / 'var') / 'app.db'
        self._cache = (None, [])

    def _review_overlay(self):
        if not self.db_path.exists():
            return []
        # Read-only and optional: an old app.db need not have a review table yet.
        with sqlite3.connect(self.db_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_current'").fetchone()
            if not exists:
                return []
            return [(day, json.loads(payload)['rows']) for day, payload in
                    db.execute('SELECT date, payload FROM review_current ORDER BY date')]

    def all(self):
        stamp = (self.path.stat().st_mtime_ns, self.path.stat().st_size) if self.path.exists() else None
        if self._cache[0] != stamp:
            self._cache = (stamp, json.loads(self.path.read_text()) if self.path.exists() else [])
        rows = copy.deepcopy(self._cache[1])
        from foot_web.storage.publications import published_tickets, select_effective_tickets
        published = published_tickets(self.db_path)
        if published:
            rows.extend(published)
        overlays = self._review_overlay()
        if overlays:
            from foot_web.services.reviews import ticket_id
            by_ticket = {(r['business_date'], ticket_id(r)): r for r in rows}
            for day, reviewed in overlays:
                for r in reviewed:
                    if r['business_date'] != day:
                        continue
                    key = day, ticket_id(r)
                    original = by_ticket.get(key, {})
                    merged = original | r
                    # Review snapshots freeze settlement, not later display/version decisions.
                    for field in ('superseded', 'superseded_by', 'version_note', 'after_freeze_revision',
                                  'withdrawn', 'withdrawal_reason', 'withdrawn_at', 'withdrawn_by'):
                        if field in original:
                            merged[field] = original[field]
                    by_ticket[key] = merged
            rows = list(by_ticket.values())
        rows = select_effective_tickets(rows)
        for i, r in enumerate(rows):
            r['id'] = i
            r.setdefault('superseded', False)
            r['group'] = KIND_GROUP.get(r['kind'], r.get('group', '其他'))
            r['state'] = 'pending' if r.get('hit') is None else ('hit' if r['hit'] else 'miss')
        return rows

    @property
    def updated(self):
        return self.path.stat().st_mtime if self.path.exists() else None

    def query(self, date_from='', date_to='', group='', kind='', state='', q='', include_superseded=False):
        out = []
        for r in self.all():
            if r['superseded'] and not include_superseded:
                continue
            if date_from and r['business_date'] < date_from: continue
            if date_to and r['business_date'] > date_to: continue
            if group and r['group'] != group: continue
            if kind and r['kind'] != kind: continue
            if state and r['state'] != state: continue
            if q:
                text = r['title'] + ' '.join(l.get('matchup', '') + l.get('number', '') for l in r['legs'])
                if q not in text: continue
            out.append(r)
        return sorted(out, key=lambda r: (r['business_date'], r['id']), reverse=True)

    def dates(self):
        return sorted({r['business_date'] for r in self.all()}, reverse=True)

    def months(self):
        return sorted({r['business_date'][:7] for r in self.all()}, reverse=True)

    @staticmethod
    def summarize(rows):
        s = {'n': len(rows), 'settled': 0, 'hit': 0, 'pending': 0, 'legs_hit': 0, 'legs_total': 0,
             'cost': Decimal(0), 'ret': Decimal(0), 'return_pending': 0}
        for r in rows:
            if r['state'] == 'pending':
                s['pending'] += 1
                continue
            s['settled'] += 1
            s['hit'] += r['state'] == 'hit'
            s['legs_hit'] += r.get('legs_hit') or 0
            s['legs_total'] += r.get('legs_total') or 0
            # Event hit can be known even when original odds are missing. Such
            # tickets count for hit rate, not as zero-return losses in ROI.
            if r.get('theoretical_return') is None or r.get('sim_cost') is None:
                s['return_pending'] += 1
                continue
            s['cost'] += Decimal(str(r['sim_cost']))
            s['ret'] += Decimal(str(r['theoretical_return']))
        s['rate'] = s['hit'] / s['settled'] if s['settled'] else None
        s['leg_rate'] = s['legs_hit'] / s['legs_total'] if s['legs_total'] else None
        s['roi'] = float(s['ret'] / s['cost'] - 1) if s['cost'] else None
        s['cost'], s['ret'] = str(s['cost']), str(s['ret'].quantize(Decimal('0.01')))
        return s

    def stats(self, month=''):
        rows = [r for r in self.all() if not r['superseded'] and (not month or r['business_date'].startswith(month))]
        by_group = OrderedDict((g, self.summarize([r for r in rows if r['group'] == g])) for g in GROUPS)
        by_kind = OrderedDict((k, self.summarize([r for r in rows if r['kind'] == k])) for g in GROUPS for k in GROUPS[g])
        daily = defaultdict(list)
        for r in rows:
            if r['group'] == '最终推荐':
                daily[r['business_date']].append(r)
        monthly = OrderedDict()
        for m in sorted({r['business_date'][:7] for r in self.all()}, reverse=True):
            mr = [r for r in self.all() if not r['superseded'] and r['business_date'].startswith(m)]
            monthly[m] = OrderedDict((g, self.summarize([r for r in mr if r['group'] == g])) for g in GROUPS)
        return {'month': month, 'total': self.summarize(rows), 'by_group': by_group, 'by_kind': by_kind,
                'daily': sorted(daily.items(), reverse=True), 'monthly': monthly}
