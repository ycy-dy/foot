from foot_web.services.reports import latest_report


def test_readonly_legacy_report_is_sanitized_without_rewriting(tmp_path):
    folder = tmp_path/'runs/2026-11-01/legacy'
    folder.mkdir(parents=True)
    path = folder/'report.md'
    text = '# 最终推荐汇总\n\n<script>alert(1)</script><img src=x onerror="alert(2)">\n'
    path.write_text(text)
    report = latest_report(tmp_path,'2026-11-01')
    assert '<script' not in report['full_html'] and 'onerror' not in report['full_html']
    assert path.read_text() == text
