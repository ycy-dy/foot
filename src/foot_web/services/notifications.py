"""Explicitly enabled DingTalk work notifications with a durable, conservative outbox."""
import json
import os
import re
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from ..core.origins import redirect_uris
from ..core.config import id_set
from ..core.privacy import redact, secret_values
from ..storage.notifications import NotificationStore
from .research import fingerprint, moment

TZ = ZoneInfo('Asia/Shanghai')
SEND_URL = 'https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2'


class BeforeSendError(RuntimeError):
    pass


class UnknownSubmission(RuntimeError):
    pass


def allowed_origins(config):
    return sorted({urlsplit(url).scheme + '://' + urlsplit(url).netloc for url in redirect_uris(config)})


class DingTalkNotifier:
    def __init__(self, config, token_provider=None, http_post=None):
        self.config = config
        self.token_provider = token_provider
        self.http_post = http_post or requests.post

    def send(self, recipients, title, body):
        msg = json.dumps({'msgtype': 'markdown', 'markdown': {'title': title, 'text': body}}, ensure_ascii=False)
        if len(msg.encode('utf-8')) > 2048:
            return {'state': 'rejected', 'message': '通知内容超过接口限制，未发送'}
        try:
            if self.token_provider is None:
                raise ValueError
            token = self.token_provider()
            if not isinstance(token, str) or not token.strip():
                raise ValueError
        except Exception:
            raise BeforeSendError('应用凭证获取失败，未发送') from None
        # Official work-notification API takes form fields; never broadcast.
        fields = {'agent_id': str(int(self.config['DINGTALK_AGENT_ID'])),
                  'userid_list': ','.join(recipients), 'to_all_user': 'false',
                  'msg': msg}
        try:
            response = self.http_post(SEND_URL, params={'access_token': token}, data=fields, timeout=15)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            raise UnknownSubmission('发送状态待核，未自动重发') from None
        if not isinstance(payload, dict):
            raise UnknownSubmission('发送响应无效，状态待核')
        if not isinstance(payload.get('errcode'), int) or isinstance(payload.get('errcode'), bool):
            raise UnknownSubmission('发送状态码无效，结果待核')
        if payload['errcode'] != 0:
            return {'state': 'rejected', 'message': '钉钉明确拒绝提交，错误码 ' + str(payload.get('errcode'))[:30]}
        task_id = payload.get('task_id')
        if isinstance(task_id, bool) or not re.fullmatch(r'\d+', str(task_id or '')):
            raise UnknownSubmission('未获得发送任务号，状态待核')
        return {'state': 'submitted', 'task_id': str(task_id), 'message': '已提交到钉钉，实际接收结果未核实'}


class Notifications:
    def __init__(self, config, notifier=None):
        self.config = config
        self.store = NotificationStore(config['DATA_DIR'])
        self.notifier = notifier or DingTalkNotifier(config)

    def recipients(self):
        configured = id_set(self.config.get('FOOT_NOTIFY_USER_IDS'))
        allowed = id_set(self.config.get('FOOT_ADMIN_USER_IDS')) | id_set(self.config.get('FOOT_ALLOWED_USER_IDS'))
        if not configured or not configured <= allowed or len(configured) > 100:
            return []
        return sorted(configured)

    def target_hash(self):
        return fingerprint({'recipients': self.recipients(), 'client': self.config.get('DINGTALK_CLIENT_ID'),
                            'agent': self.config.get('DINGTALK_AGENT_ID')})

    def readiness(self):
        prefs = self.store.preferences()
        if not self.recipients():
            return False, '未配置合法通知接收人，或接收人不属于项目白名单'
        if not all(self.config.get(key) for key in ('DINGTALK_CLIENT_ID', 'DINGTALK_CLIENT_SECRET', 'DINGTALK_AGENT_ID')):
            return False, '企业应用或AgentId未配置'
        try:
            if int(self.config['DINGTALK_AGENT_ID']) <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return False, 'AgentId格式无效'
        if not prefs['enabled']:
            return False, '通知未启用'
        if prefs['actor'] not in id_set(self.config.get('FOOT_ADMIN_USER_IDS')):
            return False, '启用人已无管理员权限'
        if prefs['origin'] not in allowed_origins(self.config):
            return False, '报告入口已失效，请重新选择'
        if prefs['recipient_sha256'] != self.target_hash():
            return False, '接收人或应用配置已变化，请重新确认开启'
        return True, '本地配置就绪；未代表钉钉接收验证成功'

    def save_preferences(self, data, actor, now=None):
        now = moment(now or datetime.now(TZ))
        enabled, origin = data.get('enabled') == '1', data.get('origin', '').rstrip('/')
        if enabled:
            if not self.recipients() or origin not in allowed_origins(self.config) or len(origin) > 300:
                raise ValueError('启用前请配置白名单接收人，并选择已登记的报告入口')
            if not all(self.config.get(key) for key in ('DINGTALK_CLIENT_ID', 'DINGTALK_CLIENT_SECRET', 'DINGTALK_AGENT_ID')):
                raise ValueError('请先在本机配置企业应用及AgentId')
            try:
                if int(self.config['DINGTALK_AGENT_ID']) <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError('AgentId格式无效') from None
        self.store.save_preferences(enabled, origin, actor, self.target_hash(), now)
        self.store.store.event('notification_settings_saved', actor, detail={'enabled': enabled})

    def enqueue(self, event_key, kind, title, summary, path, now=None):
        ready, _ = self.readiness()
        if not ready:
            return False
        if not (path == '/automation' or re.fullmatch(r'/(?:publications|analysis|reviews|rechecks)/[A-Za-z0-9_.-]+', path)):
            raise ValueError('通知详情路径无效')
        secrets = secret_values(self.config, os.environ)
        return self.store.enqueue(event_key, kind, redact(title, secrets, limit=80),
            redact(summary, secrets, limit=350), path, moment(now or datetime.now(TZ)))

    def collect(self, now=None):
        now = moment(now or datetime.now(TZ))
        if not self.readiness()[0]:
            return
        enabled_at = self.store.preferences()['enabled_at']
        with self.store.store.connect() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'publications' in tables:
                for row in db.execute("SELECT id,business_date,created_at FROM publications WHERE status='published' AND created_at>=?", (enabled_at,)).fetchall():
                    self.enqueue('published:' + row['id'], 'publication', '研究报告已发布',
                        row['business_date'] + ' 新版本已通过门禁和管理员确认；具体依据、风险及撤销条件见报告。',
                        '/publications/' + row['id'], now)
                for row in db.execute("SELECT payload FROM publications WHERE status='withdrawn'").fetchall():
                    publication = json.loads(row['payload'])
                    withdrawn = publication.get('withdrawn_at')
                    if withdrawn and moment(enabled_at) <= moment(withdrawn) <= now:
                        self.enqueue('withdrawn:' + publication['id'], 'withdrawal', '研究报告展示已撤销',
                            publication['business_date'] + ' 当前展示已撤销，原票仍保留；请查看说明与版本记录。',
                            '/publications/' + publication['id'], now)
            if 'review_runs' in tables:
                for row in db.execute("SELECT id,business_date FROM review_runs WHERE status='succeeded' AND finished_at>=?", (enabled_at,)).fetchall():
                    self.enqueue('review:' + row['id'], 'review', '复盘版本已生成',
                        row['business_date'] + ' 复盘已完成；未知赛果仍待核，原票与旧版本保留。',
                        '/reviews/' + row['id'], now)
            if 'recheck_runs' in tables:
                for row in db.execute("SELECT id,publication_id,payload FROM recheck_runs WHERE status IN ('succeeded','partial') AND finished_at>=?", (enabled_at,)).fetchall():
                    payload = json.loads(row['payload']) if row['payload'] else None
                    if payload and (payload['changes'] or payload['gaps']):
                        signature = fingerprint({'changes': payload['changes'], 'gaps': payload['gaps']})
                        self.enqueue('changes:' + row['publication_id'] + ':' + signature, 'change', '临场变化或资料待核',
                            f'{payload["business_date"]} · 变化 {len(payload["changes"])} 项，待核 {len(payload["gaps"])} 项。未自动换腿。',
                            '/rechecks/' + row['id'], now)
            for table, prefix, path in [('analysis_runs', 'analysis', '/analysis/'), ('review_runs', 'review-failure', '/reviews/'),
                                        ('recheck_runs', 'recheck-failure', '/rechecks/')]:
                if table not in tables:
                    continue
                extra = ',publication_id,message' if table == 'recheck_runs' else ''
                for row in db.execute(f"SELECT id,status,updated_at{extra} FROM {table} WHERE status IN ('failed','interrupted','partial') AND updated_at>=?", (enabled_at,)).fetchall():
                    key = (prefix + ':' + row['publication_id'] + ':' + fingerprint(row['message'])
                           if table == 'recheck_runs' else prefix + ':' + row['id'] + ':' + row['updated_at'])
                    self.enqueue(key, 'failure', '研究任务未完成',
                        '任务未完成或只完成部分内容，请查看执行记录；已有检查点和原票保留。', path + row['id'], now)
            if 'schedule_fires' in tables:
                for row in db.execute("SELECT id,status FROM schedule_fires WHERE status IN ('failed','interrupted','skipped') AND updated_at>=?", (enabled_at,)).fetchall():
                    self.enqueue('schedule:' + str(row['id']), 'failure', '定时任务需要关注',
                                 '计划未正常派发，请查看定时任务记录。', '/automation', now)

    def process_one(self, now=None):
        now = moment(now or datetime.now(TZ))
        if not self.readiness()[0]:
            return
        row = self.store.claim(now)
        if not row:
            return
        prefs = self.store.preferences()
        link = prefs['origin'] + row['resource_path']
        footer = '\n\n[查看详情](' + link + ')\n\n仅研究，不保证命中或收益。未提交、未下单。'
        prefix = ('### ' + row['title'] + '\n\n' + row['summary']).encode('utf-8')
        limit = max(0, 1700 - len(row['title'].encode('utf-8')) - len(footer.encode('utf-8')))
        body = prefix[:limit].decode('utf-8', errors='ignore') + footer
        try:
            result = self.notifier.send(self.recipients(), row['title'], body)
        except BeforeSendError:
            retry = row['attempts'] < 3
            self.store.finish(row['id'], 'retry' if retry else 'failed', '凭证获取失败，消息未发送',
                              now, retry_after=60 if row['attempts'] == 1 else 300)
            return
        except Exception:
            self.store.finish(row['id'], 'uncertain', '发送状态待核，未自动重发', now)
            return
        self.store.finish(row['id'], result['state'], result['message'], now, task_id=result.get('task_id'))
