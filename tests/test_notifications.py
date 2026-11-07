import json
from datetime import timedelta

import pytest

from conftest import ANALYSIS_ASOF, login
from foot_web.services.notifications import BeforeSendError, DingTalkNotifier, Notifications


class Notifier:
    def __init__(self, mode='submitted'):
        self.calls = []
        self.mode = mode
    def send(self, recipients, title, text):
        self.calls.append((recipients, title, text))
        if self.mode == 'uncertain':
            raise TimeoutError('do not expose access_token=secret')
        if self.mode == 'before':
            raise BeforeSendError('private credential error')
        return {'state': 'submitted', 'task_id': '123', 'message': '已提交到钉钉，实际接收结果未核实'}


def config(cfg):
    return cfg | {'FOOT_NOTIFY_USER_IDS': 'admin1', 'DINGTALK_AGENT_ID': '123',
                  'DINGTALK_REDIRECT_URI': 'http://localhost/auth/dingtalk/callback'}


def enabled(cfg, mode='submitted'):
    sender = Notifier(mode)
    service = Notifications(config(cfg), sender)
    service.save_preferences({'enabled': '1', 'origin': 'http://localhost'}, 'admin1', ANALYSIS_ASOF)
    return service, sender


def test_notifications_default_off_deduplicate_and_never_claim_delivery(cfg):
    sender = Notifier()
    service = Notifications(config(cfg), sender)
    assert not service.enqueue('test', 'test', '标题', '摘要', '/analysis/run', ANALYSIS_ASOF)
    service.process_one(ANALYSIS_ASOF)
    assert not sender.calls
    service.save_preferences({'enabled': '1', 'origin': 'http://localhost'}, 'admin1', ANALYSIS_ASOF)
    assert service.enqueue('one', 'publication', '研究报告', '仅作研究', '/publications/one', ANALYSIS_ASOF)
    assert not service.enqueue('one', 'publication', '研究报告', '仅作研究', '/publications/one', ANALYSIS_ASOF)
    service.process_one(ANALYSIS_ASOF)
    service.process_one(ANALYSIS_ASOF)
    assert len(sender.calls) == 1 and sender.calls[0][0] == ['admin1']
    assert service.store.list()[0]['state'] == 'submitted'
    assert '实际接收结果未核实' in service.store.list()[0]['message']


def test_uncertain_submission_not_retried_and_credentials_not_stored(cfg):
    service, sender = enabled(cfg, 'uncertain')
    service.enqueue('one', 'test', '标题', 'api_key=test-sensitive-key', '/analysis/run', ANALYSIS_ASOF)
    service.process_one(ANALYSIS_ASOF)
    service.process_one(ANALYSIS_ASOF+timedelta(minutes=20))
    assert len(sender.calls) == 1
    rows = service.store.list()
    assert rows[0]['state'] == 'uncertain'
    assert 'test-sensitive-key' not in json.dumps(rows)
    assert 'private credential' not in json.dumps(rows)


def test_fail_before_send_can_retry_only_three_times(cfg):
    service, sender = enabled(cfg, 'before')
    service.enqueue('one', 'test', '标题', '摘要', '/analysis/run', ANALYSIS_ASOF)
    for minute in (0, 2, 8, 20):
        service.process_one(ANALYSIS_ASOF+timedelta(minutes=minute))
    assert len(sender.calls) == 3
    assert service.store.list()[0]['state'] == 'failed'


def test_recipient_change_requires_new_explicit_confirmation(cfg):
    service, sender = enabled(cfg)
    service.enqueue('one', 'test', '标题', '摘要', '/analysis/run', ANALYSIS_ASOF)
    service.config['FOOT_NOTIFY_USER_IDS'] = 'viewer1'
    assert not service.readiness()[0]
    service.process_one(ANALYSIS_ASOF)
    assert not sender.calls
    service.save_preferences({'enabled': '1', 'origin': 'http://localhost'}, 'admin1', ANALYSIS_ASOF+timedelta(minutes=1))
    assert service.store.list()[0]['state'] == 'skipped'


def test_dingtalk_request_uses_form_no_broadcast_and_does_not_log_token(cfg):
    seen = {}
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'errcode': 0, 'task_id': 123456}
    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response()
    notifier = DingTalkNotifier(config(cfg), token_provider=lambda: 'private-token', http_post=post)
    result = notifier.send(['admin1'], '研究', '测试')
    assert result['state'] == 'submitted' and result['task_id'] == '123456'
    assert seen['data']['userid_list'] == 'admin1'
    assert seen['data']['to_all_user'] == 'false'
    assert json.loads(seen['data']['msg'])['msgtype'] == 'markdown'
    assert 'private-token' not in json.dumps(result)
    assert 'dept_id_list' not in seen['data']


def test_notification_settings_are_admin_only_and_unauthorized_automation_stays_closed(client, identity):
    assert client.get('/research/notifications').status_code == 302
    login(client, identity, 'viewer1', '查看者')
    assert client.get('/research/notifications').status_code == 403
    with client.session_transaction() as session:
        csrf = session['csrf']
    client.post('/logout', data={'csrf': csrf})
    login(client, identity)
    assert client.get('/research/notifications').status_code == 200
    assert client.post('/research/notifications', data={'enabled': '1'}).status_code == 400


def test_collect_does_not_backfill_history_and_deduplicates_new_failures(cfg):
    service, sender = enabled(cfg)
    store = service.store.store
    old, _ = store.begin_analysis('old-run', '2026-11-03', 'admin1')
    store.update_analysis('old-run', status='failed', message='old')
    new, _ = store.begin_analysis('new-run', '2026-11-04', 'admin1')
    store.update_analysis('new-run', status='failed', message='new')
    with store.connect() as db:
        db.execute('UPDATE analysis_runs SET updated_at=? WHERE id=?',
                   ((ANALYSIS_ASOF-timedelta(days=1)).isoformat(), 'old-run'))
        db.execute('UPDATE analysis_runs SET updated_at=? WHERE id=?',
                   ((ANALYSIS_ASOF+timedelta(minutes=1)).isoformat(), 'new-run'))
    service.collect(ANALYSIS_ASOF+timedelta(minutes=2))
    service.collect(ANALYSIS_ASOF+timedelta(minutes=2))
    assert len(service.store.list()) == 1
    assert service.store.list()[0]['resource_path'] == '/analysis/new-run'
    assert not sender.calls
