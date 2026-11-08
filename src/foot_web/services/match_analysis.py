"""Read-only match analysis projection; never launches AI or promotes a ticket."""
from .recommendations import options_with_evidence
from .research import match_key, moment
from .versions import rules_manifest, same_version


def latest_match_analysis(tasks, match, config, as_of):
    if not match.get('business_date'):
        return None
    key = match_key(match)
    with tasks.store.connect() as db:
        row = db.execute('''SELECT task_id FROM research_matches
            WHERE match_key=? ORDER BY updated_at DESC, rowid DESC LIMIT 1''', (key,)).fetchone()
    if row is None:
        return None
    item = next((r for r in tasks.research.items(row['task_id']) if r['match_key'] == key
                 and r['match'].get('official_id', match.get('official_id')) == match.get('official_id')
                 and r['match'].get('home') == match.get('home')
                 and r['match'].get('away') == match.get('away')
                 and r['match'].get('business_date') == match.get('business_date')), None)
    if item is None:
        return None
    workflow = tasks.research.workflow(item['task_id'])
    current = False
    try:
        manifest, _ = rules_manifest(config['PROJECT_DIR'])
        current = bool(workflow and manifest['compatibility'] == 'supported_subset'
                       and same_version(manifest, workflow['manifest']))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # Compute current quality at viewing time; never silently reuse old prices.
    from .evidence_reviews import runtime_items
    checked_item = runtime_items(config, item['task_id'], [item], as_of)[0]
    opinions = options_with_evidence(item['match'], checked_item, as_of) if item.get('payload') else []
    return {'item': item, 'evidence': item.get('payload'), 'options': opinions,
            'current_version': current, 'as_of': moment(as_of).isoformat(),
            'task_id': item['task_id'], 'match_key': key,
            'price_note': '研究报价为冻结快照，不是当前可购价格；当前市场见下方，变价须新AI决策和审核。',
            'status': item['status']}
