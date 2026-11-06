import copy
import json
from pathlib import Path
from decimal import Decimal
from foot_web.services.dream import published_dream
from foot_web.services.versions import rules_manifest
from foot_web.services.audit import audit
from conftest import login


def ticket():
    legs = [{'num': f'周三00{i}', 'sport': 'football', 'market': 'CRS', 'label': '1:0',
             'options': [{'key': 's10', 'label': '1:0', 'odds': '6.0'}],
             'sources': [{'url': 'https://official.example/report'}], 'reasons': ['证据一', '证据二'],
             'evidence_confidence': {'version': 'evidence-policy-1.0.0', 'eligible': True, 'evidence_confidence': 75}}
            for i in range(1, 5)]
    return {'require_evidence_confidence': True, 'groups': [], 'dream_legs': legs,
            'dream': [{'num': l['num'], 'score': l['label'], 'odds': l['options'][0]['odds']} for l in legs]}


def test_four_unique_scores_accepted():
    assert audit(ticket())[0] == []


def test_missing_duplicate_unscored_wrong_market_rejected():
    data = ticket()
    data['dream'] = data['dream'][:3]
    assert audit(data)[0]
    data = ticket()
    data['dream'][1]['num'] = data['dream'][0]['num']
    assert audit(data)[0]
    data = ticket()
    data['dream_legs'][0]['evidence_confidence']['evidence_confidence'] = 69
    assert audit(data)[0]
    data = ticket()
    data['dream_legs'][0]['market'] = 'HAD'
    assert audit(data)[0]


def test_promoted_ticket_projection_exact_product_and_old_version_rejection(app):
    config = app.config['FOOT']
    service = app.extensions['publications']
    data = ticket()
    legs = data['dream_legs']
    for leg in legs:
        leg.update(p_mkt=.1, home='模拟主队', away='模拟客队', kickoff='2026-11-04T20:00:00+08:00')
    manifest, _ = rules_manifest(config['PROJECT_DIR'])
    pub = {'id': 'publication-dream-fixture', 'task_id': 'task', 'check_id': 'check-dream',
           'business_date': '2026-11-04', 'status': 'published', 'created_at': '2026-11-04T12:00:00+08:00',
           'actor': 'admin1', 'previous_id': None, 'manifest': manifest}
    folder = Path(config['PROJECT_DIR']) / 'runs' / '2026-11-04' / pub['id']
    folder.mkdir(parents=True)
    (folder / 'recommendations.json').write_text(json.dumps({'dream_legs': legs, 'audit_input': data}))
    service.store.promote(pub, [])
    result = published_dream(service, config, '2026-11-04')
    assert len(result['legs']) == 4 and Decimal(result['product']) == Decimal('1296')
    assert result['model_probability'] is None
    config = config | {'PROJECT_DIR': str(folder)}  # no current policy at this root
    assert published_dream(service, config, '2026-11-04')['legs'] == []


def test_home_explicit_empty_dream_without_fabrication(client, identity):
    login(client, identity)
    text = client.get('/?date=2026-11-04').get_data(as_text=True)
    assert '比分4串1梦想单' in text and '梦想单未形成' in text
    assert '四场全部正确才命中' in text and '不填充虚构比分' in text
