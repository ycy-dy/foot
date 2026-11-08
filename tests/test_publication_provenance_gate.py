"""Real publication gate must consume disk receipts, not self-reported strings."""
from pathlib import Path

from test_publications import researched
from conftest import ANALYSIS_ASOF
from foot_web.services.publications import PublicationError, PublicationService
import json
import pytest


@pytest.mark.parametrize('change', ['missing_quote', 'changed_review', 'wrong_task', 'wrong_option', 'wrong_dimension', 'wrong_actor'])
def test_disk_receipt_tampering_cannot_pass_publication(researched, change):
    from foot_web.services.research import fingerprint
    config, _, task, fetcher = researched
    root = Path(config['DATA_DIR'])
    if change == 'missing_quote':
        for path in (root/'source-provenance/quotes').iterdir():
            path.unlink()
    elif change == 'changed_review':
        for path in (root/'source-provenance/reviews').iterdir():
            path.chmod(0o600)
            path.write_text('{}')
    elif change == 'wrong_actor':
        config['FOOT_ADMIN_USER_IDS'] = 'other-admin'
    else:
        for path in (root/'evidence-reviews'/fingerprint(task['id'])).glob('*.json'):
            row = json.loads(path.read_text())
            key = {'wrong_task': 'task_id', 'wrong_option': 'option_id', 'wrong_dimension': 'dimension_id'}[change]
            row['claim'][key] = 2 if change == 'wrong_dimension' else 'wrong'
            path.unlink()
            (path.parent/(fingerprint(row)+'.json')).write_text(json.dumps(row))
    with pytest.raises(PublicationError, match='AI推荐决策'):
        PublicationService(config, fetcher).check(task['id'], 'admin1', now=ANALYSIS_ASOF)


def test_valid_score_cannot_pass_publication_without_disk_receipts(researched):
    config, _, task, fetcher = researched
    directory = Path(config['DATA_DIR']) / 'source-provenance'
    if directory.exists():
        directory.rename(directory.with_name('removed-receipts'))
    with pytest.raises(PublicationError, match='AI推荐决策'):
        PublicationService(config, fetcher).check(task['id'], 'admin1', now=ANALYSIS_ASOF)
