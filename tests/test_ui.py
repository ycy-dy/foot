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


def test_tabs_and_filters_have_accessible_states(client, identity):
    login(client, identity)
    page = Elements(client.get('/?date=2026-11-04').get_data(as_text=True))
    tabs = page.with_attr('role', 'tab')
    panels = page.with_attr('role', 'tabpanel')
    assert len(tabs) == len(panels) == 6
    assert sum(attrs['aria-selected'] == 'true' for _, attrs in tabs) == 1
    for _, attrs in tabs:
        panel = next(p for _, p in panels if p['id'] == attrs['aria-controls'])
        assert panel['aria-labelledby'] == attrs['id']
        assert ('hidden' not in panel) == (attrs['aria-selected'] == 'true')
    filters = page.with_attr('data-f')
    assert len(filters) == 6 and all(tag == 'button' for tag, _ in filters)
    assert sum(attrs['aria-pressed'] == 'true' for _, attrs in filters) == 1
    assert page.with_attr('id', 'match-empty')
    assert page.with_attr('id', 'filter-result')
    assert page.with_attr('aria-current', 'page')[0][1]['href'] == '/'


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
    assert '官方数据获取失败' in html and '测试快照不可用' in html
    assert '没有符合条件的比赛' in html
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


def test_statistics_does_not_label_historical_rate_as_prediction(client, identity):
    login(client, identity)
    html = client.get('/stats?month=2026-10').get_data(as_text=True)
    assert '历史已结算命中率' in html
    assert 'title="市场基准命中概率' not in html
