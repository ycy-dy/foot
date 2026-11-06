from conftest import login


def test_index_lists_today(client, identity):
    login(client, identity)
    html = client.get('/?date=2026-11-04').get_data(as_text=True)
    assert '2026-11-04' in html and '当日赛程与推荐' in html
    assert '莱比锡红牛' in html and '曼彻斯特城' in html
    assert '（客）' in html and '（主）' in html          # 篮球客前主后
    for panel in ('最终推荐汇总', '完整赛程与研究状态', '70%'):
        assert panel in html
    assert '早中场①' in html and '晚场②' in html


def test_api_today(client, identity):
    login(client, identity, 'viewer1', '只读乙')
    d = client.get('/api/today?date=2026-11-04').get_json()
    assert d['business_date'] == '2026-11-04'
    nums = {m['num'] for m in d['football']}
    assert {'周三001', '周三005', '周三012'} <= nums
    assert len(d['basketball']) == 16


def test_match_detail(client, identity):
    login(client, identity)
    assert '胜平负' in client.get('/match/football/周三005?date=2026-11-04').get_data(as_text=True)
    assert '大小分' in client.get('/match/basketball/周三303?date=2026-11-04').get_data(as_text=True)
    assert client.get('/match/football/周三999').status_code == 404


def test_unpublished_report_not_inferred_from_historical_files(client, identity):
    login(client, identity)
    assert client.get('/report?date=2026-11-04').status_code == 404


def test_ledger_history_stats_pages(client, identity):
    login(client, identity, 'viewer1', '只读乙')
    assert '台账查询' in client.get('/ledger').get_data(as_text=True)
    assert client.get('/ledger?group=最终推荐&state=miss&from=2026-10-01').status_code == 200
    h = client.get('/history?date=2026-11-04').get_data(as_text=True)
    assert '历史推荐查询' in h
    assert '该业务日没有台账记录' in h
    s = client.get('/stats?month=2026-10').get_data(as_text=True)
    assert '命中率统计' in s and '分类别命中率' in s
    assert client.get('/api/stats').get_json()['success']


def test_recompute_requires_admin_and_csrf(client, identity):
    login(client, identity, 'viewer1', '只读乙')
    assert client.post('/api/recompute').status_code == 403
    with client.session_transaction() as s:
        client.post('/logout', data={'csrf': s['csrf']})
    login(client, identity)
    assert client.post('/api/recompute').status_code == 400
    with client.session_transaction() as s:
        csrf = s['csrf']
    assert client.post('/api/recompute', headers={'X-CSRF': csrf}).get_json()['success']
