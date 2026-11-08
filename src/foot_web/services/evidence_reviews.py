"""Authenticated manual-action overlay; frozen AI research stays unchanged."""
import copy
import json
from pathlib import Path

from .research import fingerprint
from .source_provenance import SourceProvenanceStore, ProvenanceError
from .evidence_confidence import WEIGHTS


def save_review(data_dir, task_id, claim, quote_id, review_id, *, origin_task_id=None):
    record = {'task_id': task_id, 'claim': claim, 'quote_receipt_id': quote_id,
              'manual_review_receipt_id': review_id}
    if origin_task_id:
        record['origin_task_id'] = origin_task_id
    path = Path(data_dir) / 'evidence-reviews' / fingerprint(task_id)
    path.mkdir(parents=True, exist_ok=True)
    target = path / (fingerprint(record) + '.json')
    if not target.exists():
        with target.open('x', encoding='utf-8') as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
    return record


def verified_reviews(data_dir, task_id, match_id, as_of, allowed_actors=None):
    """Read independent human receipts, including explicitly inherited bindings."""
    root = Path(data_dir)
    if not (root / 'source-provenance').is_dir():
        return []
    store = SourceProvenanceStore(root / 'source-provenance')
    folder = root / 'evidence-reviews' / fingerprint(task_id)
    if folder.is_symlink() or folder.parent.is_symlink():
        return []
    result = []
    for path in folder.glob('*.json'):
        try:
            if path.is_symlink() or path.stat().st_size > 100_000:
                continue
            row = json.loads(path.read_text(encoding='utf-8'))
            claim = row['claim']
            if (path.stem != fingerprint(row) or row['task_id'] != task_id
                    or claim.get('task_id') != row.get('origin_task_id', task_id)
                    or (match_id is not None and claim['match_id'] != match_id)):
                continue
            checked = store.verify_support(claim, quote_receipt_id=row['quote_receipt_id'],
                manual_review_receipt_id=row['manual_review_receipt_id'], as_of=as_of,
                match_id=claim['match_id'], option_id=claim['option_id'], dimension_id=claim['dimension_id'])
            if checked['verified'] and (allowed_actors is None or checked['actor'] in allowed_actors):
                result.append(row)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def reviewed_evidence(data_dir, parent_id, task_id, item, as_of, allowed_actors):
    """Derive a new checkpoint from frozen research plus authenticated reviews."""
    evidence = copy.deepcopy(item['payload'])
    from .research import EVIDENCE_SCHEMA, option_catalog
    available = {option['id'] for option in option_catalog(item['match'])}
    sources = {source['url']: source['id'] for source in evidence.get('sources', [])}
    claims = {}
    for row in verified_reviews(data_dir, parent_id, item['match_key'], as_of, allowed_actors):
        original = row['claim']
        if original['option_id'] not in available or original['url'] not in sources:
            continue
        fields = EVIDENCE_SCHEMA['properties']['claims']['items']['properties']
        claim = {key: value for key, value in original.items() if key in fields}
        claim.update(source_id=sources[original['url']], verification_status='manual_verified',
                     quote_receipt_id=row['quote_receipt_id'], manual_review_receipt_id=row['manual_review_receipt_id'])
        claim['claim_id'] = fingerprint({'quote': row['quote_receipt_id'], 'review': row['manual_review_receipt_id']})
        claims[claim['claim_id']] = claim
        save_review(data_dir, task_id, original, row['quote_receipt_id'], row['manual_review_receipt_id'],
                    origin_task_id=row.get('origin_task_id', parent_id))
    # Discard self-reported claims in the derived checkpoint; no human action is synthesized.
    evidence['claims'] = list(claims.values())
    return evidence


def verify_leg(data_dir, task_id, leg, as_of, evidence=None, allowed_actors=None, *, reviews=None):
    """Require an on-disk human support action for each cited source of a leg."""
    root = Path(data_dir)
    provenance_root = root / 'source-provenance'
    if not provenance_root.is_dir() or provenance_root.is_symlink():
        return False
    try:
        verified_urls = set()
        verified_dimensions = set()
        source_urls = {source['id']: source['url'] for source in (evidence or {}).get('sources', [])}
        required_dimensions = {row['id']: {source_urls[sid] for sid in row['source_ids'] if sid in source_urls}
                               for row in (evidence or {}).get('dimensions', [])
                               if row['id'] in WEIGHTS and row['status'] in ('verified', 'partial')}
        rows = reviews if reviews is not None else verified_reviews(data_dir, task_id, leg['match_key'], as_of, allowed_actors)
        for row in rows:
            claim = row['claim']
            if claim['match_id'] != leg['match_key'] or claim['option_id'] != leg['option_id']:
                continue
            verified_urls.add(claim['url'])
            if claim['url'] in required_dimensions.get(claim['dimension_id'], set()):
                verified_dimensions.add(claim['dimension_id'])
        required = {source['url'] for source in leg.get('sources', [])}
        return bool(required) and required <= verified_urls and set(required_dimensions) <= verified_dimensions
    except (OSError, ValueError, KeyError, TypeError, ProvenanceError):
        return False


def runtime_items(config, task_id, items, as_of):
    """Attach ephemeral receipt checks at trusted application boundaries only."""
    from ..core.config import id_set
    from .research import option_catalog
    try:
        rows = verified_reviews(config['DATA_DIR'], task_id, None, as_of,
                                id_set(config.get('FOOT_ADMIN_USER_IDS')))
    except (OSError, ValueError, KeyError, TypeError, ProvenanceError):
        rows = []
    result = []
    for item in items:
        payload = item.get('payload') or {}
        sources = {source['id']: source for source in payload.get('sources', [])}
        assessments = {row['option_id']: row for row in payload.get('assessments', [])}
        checks = {}
        for option in option_catalog(item['match']):
            source_ids = assessments.get(option['id'], {}).get('source_ids', [])
            leg = {'match_key': item['match_key'], 'option_id': option['id'],
                   'sources': [sources[key] for key in source_ids if key in sources]}
            checks[option['id']] = verify_leg(config['DATA_DIR'], task_id, leg, as_of, payload, reviews=rows)
        result.append(item | {'_provenance_checks': checks})
    return result
