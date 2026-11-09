from html.parser import HTMLParser
from xml.etree import ElementTree

from conftest import login


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def with_attr(self, key, value=None):
        return [(tag, attrs) for tag, attrs in self.elements
                if key in attrs and (value is None or attrs[key] == value)]


def test_schedule_table_and_date_selector_are_accessible(client, identity):
    login(client, identity)
    html = client.get('/?date=2026-11-04').get_data(as_text=True)
    page = Elements(html)
    assert page.with_attr('aria-label', '业务日')
    assert page.with_attr('aria-current', 'page')[0][1]['href'] == '/'
    assert '完整赛程与研究状态' in html and '不是推荐' in html
    assert any(tag == 'table' for tag, _ in page.elements)
    assert not page.with_attr('role', 'tab')  # legacy recommendation tabs are gone
    assert '今日分析' in html


def test_viewer_has_navigation_but_no_admin_actions(client, identity):
    login(client, identity, 'viewer1', '只读乙')
    page = Elements(client.get('/').get_data(as_text=True))
    assert page.with_attr('aria-label', '主导航')
    assert page.with_attr('data-theme-toggle')
    assert not page.with_attr('id', 'btn-recompute')
    assert not page.with_attr('href', '/admin/events')
    assert page.with_attr('aria-controls', 'main-navigation')


def test_empty_data_and_unavailable_source_are_visible(client, identity, app, monkeypatch):
    login(client, identity)

    def unavailable(*args, **kwargs):
        raise ValueError('测试快照不可用')

    monkeypatch.setattr(app.extensions['fetcher'], 'get', unavailable)
    response = client.get('/')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '暂无可用官方赛程' in html
    assert '不会编造比赛或推荐' in html
    assert '不保证命中或收益' in html


def test_static_assets_and_icon_references(client, identity):
    login(client, identity)
    html = client.get('/').get_data(as_text=True)
    page = Elements(html)
    sprite = client.get('/static/icons.svg')
    assert sprite.status_code == 200
    tree = ElementTree.fromstring(sprite.data)
    ids = {node.get('id') for node in tree}
    for _, attrs in page.with_attr('href'):
        if attrs['href'].startswith('/static/icons.svg#'):
            assert attrs['href'].split('#')[1] in ids
    for path in ('style.css', 'app.js', 'icons-LICENSE.txt'):
        assert client.get('/static/' + path).status_code == 200
    assert 'prefers-reduced-motion' in client.get('/static/style.css').get_data(as_text=True)


def test_statistics_does_not_label_historical_rate_as_prediction(client, identity, app):
    import json
    from pathlib import Path
    folder = Path(app.config['FOOT']['PROJECT_DIR']) / 'ledger/data'
    folder.mkdir(parents=True)
    (folder / 'settled_records.json').write_text(json.dumps([
        {'business_date': '2026-10-01', 'kind': '胜平负', 'title': '离线结算样例',
         'legs': [], 'hit': True, 'sim_cost': '2', 'theoretical_return': '3.6'}]))
    login(client, identity)
    html = client.get('/stats?month=2026-10').get_data(as_text=True)
    assert '历史已结算命中率' in html
    assert 'title="市场基准命中概率' not in html


def test_raw_frozen_documents_have_local_scroll_and_events_have_heading(client, identity):
    login(client, identity)
    css = client.get('/static/style.css').get_data(as_text=True)
    assert 'main pre { max-width: 100%; overflow-x: auto;' in css
    assert '<h1>审计日志</h1>' in client.get('/admin/events').get_data(as_text=True)
    reviews = client.get('/reviews').get_data(as_text=True)
    assert 'DeepSeek Harness' not in reviews and '当前政策提供方 AI复盘' in reviews
