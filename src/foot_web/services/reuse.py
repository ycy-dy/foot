"""Explicit, bounded reuse of same-match evidence; a new AI decision is always required."""
import copy
import json
import os
import uuid
from pathlib import Path

from ..core.config import runtime_provider
from ..core.files import write_once
from ..core.privacy import redact, secret_values
from .research import fingerprint, json_text, moment, option_catalog, validate_evidence


def reuse_recent(config, task, workflow, folder, store, now, log):
    parent_id = store.parent(task['id'])
    if not parent_id:
        return []
    parent = store.workflow(parent_id)
    configured = config.get('FOOT_RESEARCH_REUSE_MINUTES')
    limit = max(0, min(180, int(120 if configured in (None, '') else configured)))
    if not parent or not limit:
        return []
    manifest, previous = workflow['manifest'], parent['manifest']
    from .versions import same_version
    provider = runtime_provider(config)
    if (manifest.get('runtime_provider') != provider or not same_version(manifest, previous)
            or manifest.get('schema_sha256') != previous.get('schema_sha256')):
        log('system', 'warning', '原检查点的规则/研究结构不匹配，本次重新研究')
        return []
    secrets = secret_values(config, os.environ)

    def clean(value):
        if isinstance(value, dict):
            return {key: clean(v) for key, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return redact(value, secrets, limit=None) if isinstance(value, str) else value

    old_items = {row['match_key']: row for row in store.items(parent_id) if row['status'] == 'succeeded'}
    copied = []
    for item in store.items(task['id']):
        old = old_items.get(item['match_key'])
        if item['status'] != 'pending' or not old or not old['payload'] or store.cancelled(task['id']):
            continue
        try:
            if (not old.get('attempts')
                    or any(row.get('provider') != provider for row in old['attempts'])
                    or old['attempts'][-1].get('status') != 'succeeded'):
                continue
            age = (moment(now)-moment(old['as_of'])).total_seconds()
            if not 0 <= age <= limit*60 or moment(item['match']['kickoff']) <= moment(now):
                continue
            original_path = (Path(config['PROJECT_DIR']) / 'runs' / task['business_date'] / parent_id
                             / 'matches' / old['match_key'] / old['attempts'][-1]['checkpoint'])
            original = json.loads(original_path.read_text(encoding='utf-8'))
            if (original.get('provider') != provider or original.get('manifest') != previous
                    or original['payload'] != old['payload']):
                raise ValueError('原证据检查点不一致')
            evidence = clean(copy.deepcopy(old['payload']))
            available = {option['id'] for option in option_catalog(item['match'])}
            evidence['assessments'] = [row for row in evidence['assessments'] if row['option_id'] in available]
            evidence = validate_evidence(evidence, item['match'], old['as_of'])
            from .evidence_reviews import reviewed_evidence
            from ..core.config import id_set
            evidence = reviewed_evidence(config['DATA_DIR'], parent_id, task['id'],
                item | {'payload': evidence}, now, id_set(config.get('FOOT_ADMIN_USER_IDS')))
            evidence = validate_evidence(evidence, item['match'], now)
            target = folder / 'matches' / item['match_key']
            target.mkdir(parents=True, exist_ok=True)
            filename = 'cache-' + uuid.uuid4().hex + '.json'
            source = {'task_id': parent_id, 'checkpoint': str(original_path.relative_to(config['PROJECT_DIR'])),
                      'research_as_of': old['as_of'], 'payload_sha256': fingerprint(old['payload']),
                      'original_code_sha256': previous['code_sha256']}
            write_once(target / filename, json_text({'match': item['match'], 'payload': evidence,
                'as_of': old['as_of'], 'provider': provider, 'manifest': manifest, 'source': source,
                'role': 'reused_evidence_not_a_new_cli_call'}))
            record = {'provider': old['attempts'][-1]['provider'], 'sport': item['sport'], 'num': item['num'],
                      'stage': 'evidence_reuse', 'status': 'succeeded', 'code': 'cached', 'seconds': 0.0,
                      'message': '复用原证据检查点，未新调用研究CLI', 'checkpoint': filename, 'source': source}
            store.update_item(task['id'], item['match_key'], status='succeeded', payload=evidence,
                              as_of=old['as_of'], message=f'复用 {int(age/60)} 分钟前资料，原时点保留，待临场复核',
                              attempts=[record])
            copied.append(record)
        except (OSError, ValueError, KeyError, TypeError):
            log('system', 'warning', item['num'] + ' 原资料不满足复用条件，本次重新研究')
    if copied:
        log('system', 'status', f'已复用 {len(copied)} 场有效证据；官方报价已刷新，仍需新AI返回最终决策')
    return copied
