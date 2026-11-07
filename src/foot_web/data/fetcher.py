"""抓取竞彩官方计算器数据：每次抓取保存快照（不覆盖），内存缓存，失败时回退到最近快照。"""
import hashlib
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo('Asia/Shanghai')
URLS = {s: f'https://webapi.sporttery.cn/gateway/uniform/{s}/getMatchCalculatorV1.qry?channel=c' for s in ('football', 'basketball')}
HEADERS = {'User-Agent': 'Mozilla/5.0 (foot-analysis-console)', 'Referer': 'https://www.sporttery.cn/'}


class Fetcher:
    def __init__(self, data_dir, ttl=300, http_get=None):
        self.dir = Path(data_dir) / 'snapshots'
        self.ttl = ttl
        self.http_get = http_get or (lambda url: requests.get(url, headers=HEADERS, timeout=20))
        self.cache = {}
        self.lock = threading.Lock()

    def _save(self, sport, payload):
        now = datetime.now(TZ)
        folder = self.dir / now.strftime('%Y-%m-%d')
        folder.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload, ensure_ascii=False).encode()
        path = folder / f"{now.strftime('%H%M%S_%f')}_{uuid.uuid4().hex}_{sport}.json"
        path.write_bytes(raw)
        if path.read_bytes() != raw:
            path.unlink(missing_ok=True)
            raise IOError('快照写后校验失败')
        return {'file': str(path), 'captured_at': now.isoformat(timespec='seconds'), 'sha256': hashlib.sha256(raw).hexdigest(),
                'source_update': (payload.get('value') or {}).get('lastUpdateTime')}

    def latest_snapshot(self, sport):
        files = sorted(self.dir.glob(f'*/*_{sport}.json'))
        if not files:
            return None, None
        f = files[-1]
        payload = json.loads(f.read_text())
        raw = f.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        meta = {'file': str(f), 'captured_at': f.parent.name + ' ' + f.name[:6], 'source_update': (payload.get('value') or {}).get('lastUpdateTime'), 'sha256': digest, 'stale': True}
        return payload, meta

    def get(self, sport, force=False):
        with self.lock:
            hit = self.cache.get(sport)
            if hit and not force and time.time() - hit[0] < self.ttl:
                return hit[1], hit[2]
            try:
                resp = self.http_get(URLS[sport])
                resp.raise_for_status()
                payload = resp.json()
                if not payload.get('success', True) or 'value' not in payload:
                    raise ValueError(payload.get('errorMessage') or '官方接口返回异常')
                meta = self._save(sport, payload) | {'stale': False}
            except Exception as exc:  # 网络或接口异常：回退最近快照
                payload, meta = self.latest_snapshot(sport)
                if payload is None:
                    raise
                meta['error'] = str(exc)[:200]
            self.cache[sport] = (time.time(), payload, meta)
            return payload, meta
