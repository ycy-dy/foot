"""Immutable daily publication references, not another ticket/statistics store.

Only rows committed by PublicationsStore are visible. Review overlays are joined
by existing ticket identity and never copied into, or counted as, original bets.
"""
import copy
import json
import itertools
from functools import reduce
from decimal import Decimal
from pathlib import Path

from ..storage.publications import PublicationsStore
from .research import fingerprint
from .reviews import ticket_id

SCHEMA_VERSION = 'daily-recommendation-ledger-1'


def draft_ledger(bundle, task_id, audit=None):
    from .publications import normalized_tickets
    tickets = normalized_tickets(bundle, task_id)
    rows = []
    for ticket in tickets:
        rows.append({'ticket_id': ticket_id(ticket), 'title': ticket['title'], 'kind': ticket['kind'],
                     'period': ticket['title'], 'original_ticket': copy.deepcopy(ticket),
                     'branches': [{'options': copy.deepcopy(list(branch)),
                                   'odds_product': str(reduce(
                                       lambda a, b: a * Decimal(str(b['odds'])), branch, Decimal(1)))}
                                  for branch in itertools.product(*(leg['options'] for leg in ticket['legs']))],
                     'actual_stake': None, 'actual_return': None})
    # Preserve empty slots as research outcomes; do not manufacture tickets.
    empty = []
    for key in ('six', 'structures'):
        for slot in bundle.get(key, []):
            if not slot.get('leg' if key == 'six' else 'group'):
                empty.append(copy.deepcopy(slot))
    empty.extend(copy.deepcopy(bundle.get('unformed', [])))
    empty.extend(copy.deepcopy(slot) for slot in bundle.get('periods', []) if not slot.get('group'))
    if bundle.get('dream_reason'):
        empty.append({'category': '梦想单', 'reason': bundle['dream_reason']})
    return {'schema_version': SCHEMA_VERSION, 'task_id': task_id,
            'business_date': bundle['business_date'], 'as_of': bundle['as_of'],
            'publication_id': None, 'publication_status': 'draft', 'rows': rows,
            'unformed': empty, 'audit_sha256': fingerprint(audit) if audit else None,
            'actual_stake': None, 'actual_return': None}


def freeze_ledger(publication, bundle, tickets, audit):
    result = draft_ledger(bundle, publication['task_id'], audit)
    result.update(publication_id=publication['id'], publication_status='published',
                  previous_publication_id=publication.get('previous_id'),
                  published_at=publication['created_at'], selection_sha256=publication['selection_sha256'])
    for row, ticket in zip(result['rows'], tickets, strict=True):
        row.update(ticket_id=ticket_id(ticket), original_ticket=copy.deepcopy(ticket),
                   publication_id=publication['id'])
    result['content_sha256'] = fingerprint(result)
    return result


class DailyLedgerService:
    def __init__(self, config, publication_store=None):
        self.root = Path(config['PROJECT_DIR'])
        self.store = publication_store or PublicationsStore(config['DATA_DIR'])

    def get(self, publication_id):
        publication = self.store.get(publication_id)
        if not publication:
            return None
        path = self.root / 'runs' / publication['business_date'] / publication_id / 'daily-ledger.json'
        if not path.is_file():
            return None  # Old unscored artifacts are not retroactively republished.
        frozen = json.loads(path.read_text(encoding='utf-8'))
        digest = frozen.pop('content_sha256', None)
        if fingerprint(frozen) != digest or frozen.get('publication_id') != publication_id:
            raise ValueError('每日推荐台账审计哈希不一致')
        frozen['content_sha256'] = digest
        return {'frozen': frozen, 'publication': publication}

    def list(self, business_date=None):
        return [row for p in self.store.list(business_date) if (row := self.get(p['id'])) is not None]

    def current(self, business_date):
        publication = self.store.current(business_date)
        return self.get(publication['id']) if publication else None

    def review(self, publication_id):
        ledger = self.get(publication_id)
        if ledger is None:
            return None
        # Read only the existing successful review overlay; failed AI attempts have
        # no promotion and therefore cannot alter this result.
        with self.store.store.connect() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_current'").fetchone()
            row = db.execute('SELECT payload FROM review_current WHERE date=?',
                             (ledger['frozen']['business_date'],)).fetchone() if exists else None
        payload = json.loads(row[0]) if row else None
        rows = {r['ticket_id']: r for r in payload['rows']} if payload else {}
        ledger['review_run_id'] = payload['run_id'] if payload else None
        ledger['settlements'] = {r['ticket_id']: copy.deepcopy(rows.get(r['ticket_id']))
                                 for r in ledger['frozen']['rows']}
        return ledger
