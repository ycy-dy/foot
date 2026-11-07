import json
from pathlib import Path
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
        'match_id':'m1','option_id':'o1','dimension_id':4,'actor':'forged-ai-user'}
    assert client.post('/provenance', data={'csrf':csrf,'action':'review','claim':json.dumps(claim)}).status_code == 400
    response = client.post('/provenance', data={'csrf':csrf,'action':'review','claim':json.dumps(claim),'confirmed':'1','actor':'forged-ai-user'})
    assert response.status_code == 200
    receipts = [json.loads(p.read_text()) for p in (store.root / 'reviews').iterdir()]
    assert len(receipts) == 1 and receipts[0]['actor'] == 'admin1'
    assert response.headers['Cache-Control'] == 'private, no-store'


def test_manual_capture_rejects_private_url_and_html_is_escaped(client, identity):
    login(client, identity)
    with client.session_transaction() as s: csrf=s['csrf']
    response=client.post('/provenance',data={'csrf':csrf,'action':'capture','url':'http://127.0.0.1/private','text':'secret'})
    assert response.status_code == 400
    assert 'secret' not in response.get_data(as_text=True)
