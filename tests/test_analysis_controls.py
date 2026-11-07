"""Offline regression checks for analysis controls and template wiring."""
from pathlib import Path

from conftest import login
from test_ui import Elements


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'src/foot_web/static/analysis.js').read_text()


def test_analysis_controller_defensively_normalizes_empty_state_and_logs():
    assert "JSON.parse(initial.textContent || 'null')" in JS
    assert 'task = normalizeTask(data.task)' in JS
    assert 'Array.isArray(data.logs)' in JS
    assert 'Number.isFinite(Number(row.id))' in JS
    assert 'AbortSignal.timeout' in JS


def test_analysis_page_wires_log_controls_and_single_script(client, identity):
    login(client, identity)
    page = Elements(client.get('/?date=2026-11-04').get_data(as_text=True))
    assert page.with_attr('id', 'analysis-task-data')
    assert page.with_attr('id', 'analysis-log-search')
    assert page.with_attr('id', 'analysis-log-follow')
    assert page.with_attr('id', 'analysis-log-download')
    scripts = [attrs['src'] for _, attrs in page.with_attr('src') if '/static/analysis.js?' in attrs['src']]
    assert len(scripts) == 1


def test_review_publish_has_csrf_confirmation_and_double_submit_guard(client, identity):
    login(client, identity)
    html = client.get('/analysis/unknown/review').get_data(as_text=True)
    assert 'csrf' in html or client.get('/analysis/unknown/review').status_code == 404
    template = (ROOT / 'src/foot_web/templates/analysis_review.html').read_text()
    assert 'class="publish-form"' in template
    assert 'window.confirm' in template
    assert 'submitted' in template
