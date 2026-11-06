import copy
import json
from pathlib import Path

import pytest

from foot_web.services.daily_ledger import DailyLedgerService, draft_ledger, freeze_ledger
from foot_web.services.publications import normalized_tickets
from foot_web.services.research import json_text
from foot_web.services.reviews import ReviewService
from foot_web.storage.publications import PublicationsStore


@pytest.fixture
def setup(tmp_path):
    config = {'PROJECT_DIR': str(tmp_path / 'project'), 'DATA_DIR': str(tmp_path / 'var')}
    Path(config['PROJECT_DIR']).mkdir()
    leg = {'sport': 'football', 'num': '周三001', 'matchup': '甲 VS 乙', 'home': '甲', 'away': '乙',
           'kickoff': '2026-11-04T20:00:00+08:00', 'period': 'early', 'market': 'HAD', 'L': '0',
           'options': [{'key': 'h', 'label': '主胜', 'odds': '2.00'}], 'p_mkt': .5,
           'reasons': ['已核实力', '已核阵容'], 'sources': [{'id': 's1', 'url': 'https://example.test'}],
           'risk': '阵容变化', 'withdraw_if': '正式名单变化', 'ai_decision_sha256': 'ai-hash',
           'evidence_score': 75, 'evidence_score_reliable': True,
           'evidence_confidence': {'evidence_confidence': 75, 'eligible': True, 'version': 'evidence-policy-1.0.0'}}
    bundle = {'business_date': '2026-11-04', 'as_of': '2026-11-04T12:00:00+08:00', 'groups': [],
              'singles': [{'period_name': '早场', 'leg': leg}], 'six': [{'category': '双平', 'leg': None}],
              'structures': [{'period': '早场', 'structure': 'HAD+DD', 'group': None}],
              'dream_legs': [], 'ai_decision': {'validated_sha256': 'ai-hash'}}
    return config, bundle


def publish_fixture(config, bundle, pid='publication-test'):
    publication = {'id': pid, 'task_id': 'analysis-test', 'check_id': 'check-' + pid,
                   'business_date': bundle['business_date'], 'created_at': bundle['as_of'],
                   'actor': 'test', 'previous_id': None, 'status': 'published', 'selection_sha256': 'selection'}
    tickets = normalized_tickets(bundle, pid)
    frozen = freeze_ledger(publication, bundle, tickets, {'passed': True})
    folder = Path(config['PROJECT_DIR']) / 'runs' / bundle['business_date'] / pid
    folder.mkdir(parents=True)
    (folder / 'daily-ledger.json').write_text(json_text(frozen))
    return publication, tickets, frozen, folder


def test_freezes_original_scores_prices_sources_and_unformed_slots(setup):
    config, bundle = setup
    original = copy.deepcopy(bundle)
    publication, tickets, frozen, _ = publish_fixture(config, bundle)
    assert bundle == original
    assert frozen['publication_id'] == publication['id']
    assert len(frozen['unformed']) == 2
    leg = frozen['rows'][0]['original_ticket']['legs'][0]
    assert leg['evidence_score'] == 75 and leg['evidence_score_reliable']
    assert leg['options'][0]['odds'] == '2.00' and leg['sources']
    assert frozen['actual_stake'] is None and frozen['actual_return'] is None
    assert frozen['audit_sha256'] and frozen['content_sha256']
    assert tickets == normalized_tickets(bundle, publication['id'])
    assert draft_ledger(bundle, 'task')['publication_status'] == 'draft'


def test_only_committed_publications_visible_idempotent_and_no_double_count(setup):
    config, bundle = setup
    publication, tickets, _, _ = publish_fixture(config, bundle)
    ledger = DailyLedgerService(config)
    assert ledger.current(bundle['business_date']) is None
    assert ledger.get(publication['id']) is None
    assert ledger.store.promote(publication, tickets)[1]
    assert not ledger.store.promote(publication, tickets)[1]
    assert len(ledger.list()) == 1 and len(ledger.store.tickets()) == 1
    assert ledger.current(bundle['business_date'])['frozen']['rows'][0]['publication_id'] == publication['id']
    ledger.store.withdraw(publication['id'], 'test', '赛前撤销', __import__('datetime').datetime.fromisoformat(bundle['as_of']))
    assert ledger.current(bundle['business_date'])['publication']['status'] == 'withdrawn'
    assert ledger.current(bundle['business_date'])['frozen']['publication_status'] == 'published'


def test_hash_tamper_rejected(setup):
    config, bundle = setup
    publication, tickets, frozen, folder = publish_fixture(config, bundle)
    service = DailyLedgerService(config)
    service.store.promote(publication, tickets)
    frozen['rows'][0]['original_ticket']['legs'][0]['options'][0]['odds'] = '9.99'
    (folder / 'daily-ledger.json').write_text(json.dumps(frozen))
    with pytest.raises(ValueError, match='哈希'):
        service.get(publication['id'])


def test_review_joins_existing_tickets_and_failed_ai_never_promotes(setup):
    config, bundle = setup
    publication, tickets, frozen, _ = publish_fixture(config, bundle)
    ledger = DailyLedgerService(config)
    ledger.store.promote(publication, tickets)
    class Results:
        def fetch(self, *args, **kwargs):
            return {'football': [], 'basketball': []}
    good = ReviewService(config, fetcher=Results()).run(bundle['business_date'], 'review-good')
    assert len(good['rows']) == len(tickets)
    before = ledger.review(publication['id'])
    assert before['review_run_id'] == 'review-good'
    assert all(value is not None for value in before['settlements'].values())
    def failed(result):
        raise ValueError('AI unavailable')
    with pytest.raises(ValueError):
        ReviewService(config, fetcher=Results(), analyst=failed).run(bundle['business_date'], 'review-failed')
    assert ledger.review(publication['id']) == before
    assert ledger.current(bundle['business_date'])['frozen'] == frozen
    assert len(ledger.store.tickets()) == 1


def test_task_admission_fail_closed_and_supported_launches(setup, monkeypatch):
    from foot_web.engine.tasks import AnalysisTasks
    from foot_web.engine.review_tasks import ReviewTasks
    from foot_web.services import versions
    config, _ = setup
    launched = []
    launcher = lambda *args: launched.append(args) or 12345
    analysis = AnalysisTasks(config, launcher=launcher)
    review = ReviewTasks(config, launcher=launcher)
    monkeypatch.setattr(versions, 'rules_manifest', lambda root: ({'compatibility': 'policy_unavailable'}, {}))
    with pytest.raises(ValueError, match='兼容性'):
        analysis.start('2026-11-04', 'test')
    with pytest.raises(ValueError, match='兼容性'):
        review.start('2026-11-04', 'test')
    assert not launched
    monkeypatch.setattr(versions, 'rules_manifest', lambda root: ({'compatibility': 'supported_subset'}, {}))
    task, created = analysis.start('2026-11-04', 'test')
    assert not created and task['status'] == 'queued'  # return flag means reused
    task, created = review.start('2026-11-04', 'test')
    assert not created and task['status'] == 'queued'  # return flag means reused
    assert len(launched) == 2


@pytest.mark.parametrize('confidence', [None, {}, {'evidence_confidence': 69, 'eligible': False}])
def test_publication_check_rejects_unscored_old_legs(setup, monkeypatch, confidence):
    from foot_web.services import publications
    config, bundle = setup
    bundle['singles'][0]['leg']['evidence_confidence'] = confidence
    bundle['audit_input'] = {'groups': [], 'dream': []}
    service = publications.PublicationService(config)
    manifest = {'compatibility': 'supported_subset'}
    monkeypatch.setattr(publications, 'rules_manifest', lambda root: (manifest, {}))
    monkeypatch.setattr(service, 'draft', lambda task: ({'business_date': bundle['business_date']},
                         {'manifest': manifest}, Path(config['PROJECT_DIR']), bundle))
    monkeypatch.setattr(service.research, 'items', lambda task: [])
    monkeypatch.setattr(publications, 'fresh_input', lambda *args: {})
    from foot_web.services import rechecks
    monkeypatch.setattr(rechecks, 'compare_quotes', lambda *args: [])
    result = service.check('old-task', 'test', persist=False)
    assert not result['passed']
    assert any('70分' in error for error in result['errors'])
    assert not service.store.list()
