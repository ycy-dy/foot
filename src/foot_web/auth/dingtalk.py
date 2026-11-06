"""钉钉 OAuth2 身份交换（参考 version_ctrl_console/auth_service.py）。"""
from urllib.parse import urlencode

import requests


from ..core.origins import CALLBACK_PATH, callback_for_origin, redirect_uris


def authorize_url(config, state, redirect_uri):
    params = {'client_id': config['DINGTALK_CLIENT_ID'], 'redirect_uri': redirect_uri,
              'response_type': 'code', 'scope': 'openid corpid', 'prompt': 'consent',
              'corpId': config['DINGTALK_CORP_ID'], 'state': state}
    return 'https://login.dingtalk.com/oauth2/auth?' + urlencode(params)


class DingTalkIdentity:
    def __init__(self, config):
        self.config = config

    @staticmethod
    def call(method, url, **kwargs):
        response = requests.request(method, url, timeout=15, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get('errcode', 0) != 0:
            raise ValueError(f"钉钉返回错误：{data.get('errmsg') if isinstance(data, dict) else data}")
        return data

    def corp_token(self):
        return self.call('GET', 'https://oapi.dingtalk.com/gettoken', params={
            'appkey': self.config['DINGTALK_CLIENT_ID'], 'appsecret': self.config['DINGTALK_CLIENT_SECRET']})['access_token']

    def exchange(self, code):
        token = self.call('POST', 'https://api.dingtalk.com/v1.0/oauth2/userAccessToken', json={
            'clientId': self.config['DINGTALK_CLIENT_ID'], 'clientSecret': self.config['DINGTALK_CLIENT_SECRET'],
            'code': code, 'grantType': 'authorization_code'})
        profile = self.call('GET', 'https://api.dingtalk.com/v1.0/contact/users/me',
                            headers={'x-acs-dingtalk-access-token': token['accessToken']})
        union_id = profile.get('unionId')
        if not union_id:
            raise ValueError('无法取得钉钉用户身份')
        corp = self.corp_token()
        member = self.call('POST', 'https://oapi.dingtalk.com/topapi/user/getbyunionid',
                           params={'access_token': corp}, json={'unionid': union_id})
        user_id = (member.get('result') or {}).get('userid')
        if not user_id:
            raise ValueError('仅本企业成员可以登录')
        employee = self.call('POST', 'https://oapi.dingtalk.com/topapi/v2/user/get',
                             params={'access_token': corp}, json={'userid': user_id})['result']
        if employee.get('active') is False:
            raise ValueError('企业成员未激活')
        return {'union_id': union_id, 'user_id': user_id, 'name': str(employee.get('name') or profile.get('nick') or '').strip()[:40]}

