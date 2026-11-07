def test_readiness_checks_db_and_policy(client):
    response=client.get('/readiness')
    assert response.status_code == 200
    assert response.json == {'ready': True, 'checks': {'db': True, 'policy': True}}


def test_readiness_missing_database_does_not_create_file(client, app, tmp_path):
    missing = tmp_path / 'missing.sqlite'
    app.extensions['store'].path = missing
    response = client.get('/readiness')
    assert response.status_code == 503
    assert response.json['checks'] == {'db': False, 'policy': True}
    assert not missing.exists()
    assert str(missing) not in response.get_data(as_text=True)


def test_readiness_rejects_uninitialized_database(client, app, tmp_path):
    empty = tmp_path / 'empty.sqlite'
    empty.touch()
    app.extensions['store'].path = empty
    assert client.get('/readiness').status_code == 503


def test_readiness_policy_failure_is_redacted(client, monkeypatch):
    from foot_web.services import versions
    def fail(*args):
        raise ValueError('private-path-and-upstream-detail')
    monkeypatch.setattr(versions, 'rules_manifest', fail)
    response = client.get('/readiness')
    assert response.status_code == 503
    assert response.json == {'ready': False, 'checks': {'db': True, 'policy': False}}
    assert 'private-path' not in response.get_data(as_text=True)
    assert client.get('/healthz').json == {'ok': True}
