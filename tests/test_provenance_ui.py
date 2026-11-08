import json
from pathlib import Path
import pytest
from conftest import login
from foot_web.services.source_provenance import SourceProvenanceStore


def test_manual_review_auth_csrf_and_no_self_reported_actor(client, identity, app):
    assert client.get('/provenance').status_code == 302
    login(client, identity, user_id='viewer1')
    assert client.get('/provenance').status_code == 403
    assert client.post('/provenance', data={}).status_code == 403
    login(client, identity)
    assert client.get('/provenance').status_code == 200
    assert client.post('/provenance', data={'action': 'capture'}).status_code == 400
    with client.session_transaction() as s: csrf = s['csrf']
    response = client.post('/provenance', data={'csrf': csrf, 'action': 'capture',
        'url': 'https://official.example/news', 'text': 'Exact public quote'})
    assert response.status_code == 200
    store = SourceProvenanceStore(Path(app.config['FOOT']['DATA_DIR']).resolve() / 'source-provenance')
    snapshot_path = next((store.root / 'snapshots').iterdir())
    snapshot = json.loads(snapshot_path.read_text())
    claim = {'claim_id':'c1','claim':'supported statement','source_id':snapshot_path.name,
        'url':snapshot['url'],'content_sha256':snapshot['content_sha256'],'quote':'Exact public quote',
        'locator':{'start':0,'end':18},'source_type':'non_odds','support_status':'supports',
        'match_id':'missing-match','option_id':'o1','dimension_id':4,'actor':'forged-ai-user'}
    assert client.post('/provenance', data={'csrf':csrf,'action':'review','task_id':'missing-task','claim':json.dumps(claim)}).status_code == 400
    response = client.post('/provenance', data={'csrf':csrf,'action':'review','task_id':'missing-task','claim':json.dumps(claim),'confirmed':'1','actor':'forged-ai-user'})
    assert response.status_code == 400
    assert not list((store.root / 'reviews').iterdir())
    assert response.headers['Cache-Control'] == 'private, no-store'


def test_manual_review_requires_existing_research_task(app, client, identity):
    login(client, identity)
    with client.session_transaction() as s: csrf=s['csrf']
    claim={'claim_id':'c','match_id':'m','option_id':'o','dimension_id':4}
    response=client.post('/provenance',data={'csrf':csrf,'action':'review','task_id':'missing','claim':json.dumps(claim),'confirmed':'1'})
    assert response.status_code == 400 and not list((Path(app.config['FOOT']['DATA_DIR'])/'source-provenance'/'reviews').glob('*'))


def test_manual_capture_rejects_private_url_and_html_is_escaped(client, identity):
    login(client, identity)
    with client.session_transaction() as s: csrf=s['csrf']
    response=client.post('/provenance',data={'csrf':csrf,'action':'capture','url':'http://127.0.0.1/private','text':'secret'})
    assert response.status_code == 400
    assert 'secret' not in response.get_data(as_text=True)


@pytest.mark.parametrize('claim', ['[]', 'null', '"text"', '42'])
def test_non_object_claim_returns_validation_error_not_server_error(client, identity, app, monkeypatch, claim):
    login(client, identity)
    with client.session_transaction() as session:
        csrf = session['csrf']
    tasks = app.extensions['analysis_tasks']
    monkeypatch.setattr(tasks, 'get', lambda task_id: {'status': 'succeeded'})
    monkeypatch.setattr(tasks.research, 'items', lambda task_id: [{'match_key': 'm'}])
    response = client.post('/provenance', data={'csrf': csrf, 'action': 'review', 'task_id': 'task',
                                              'claim': claim, 'confirmed': '1'})
    assert response.status_code == 400
