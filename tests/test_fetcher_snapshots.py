import json
from pathlib import Path

from foot_web.data.fetcher import Fetcher

class Response:
    def __init__(self, data): self.data=data
    def raise_for_status(self): pass
    def json(self): return self.data


def test_same_second_snapshots_are_unique_and_hashed(tmp_path, monkeypatch):
    payload={'success':True,'value':{'lastUpdateTime':'2026-11-07T10:00:00+08:00'}}
    f=Fetcher(tmp_path,http_get=lambda _:Response(payload))
    class Clock:
        def now(self): return None
    first=f._save('football',payload); second=f._save('football',payload)
    assert first['file'] != second['file']
    assert first['sha256']==second['sha256']
    for path in [Path(first['file']),Path(second['file'])]:
        assert path.exists() and path.read_bytes() == json.dumps(payload,ensure_ascii=False).encode()


def test_latest_snapshot_reports_digest_and_stale(tmp_path):
    f=Fetcher(tmp_path)
    payload={'success':True,'value':{'lastUpdateTime':'x'}}
    saved=f._save('basketball',payload)
    loaded,meta=f.latest_snapshot('basketball')
    assert loaded==payload and meta['stale'] and meta['sha256']==saved['sha256']


def test_corrupt_latest_snapshot_falls_back_without_rewriting(tmp_path):
    f = Fetcher(tmp_path)
    folder = f.dir / '2026-11-07'
    folder.mkdir(parents=True)
    valid = folder / '100000_football.json'
    valid.write_text(json.dumps({'value': {'lastUpdateTime': '2026-11-07T10:00:00+08:00'}}))
    corrupt = folder / '110000_football.json'
    corrupt.write_text('{broken')
    before = corrupt.read_bytes()
    payload, meta = f.latest_snapshot('football')
    assert payload['value'] and meta['stale']
    assert meta['skipped_invalid_snapshots'] == 1 and meta['file'] == str(valid)
    assert corrupt.read_bytes() == before


def test_all_invalid_snapshots_fail_without_fabrication(tmp_path):
    f = Fetcher(tmp_path)
    folder = f.dir / '2026-11-07'
    folder.mkdir(parents=True)
    (folder / '100000_football.json').write_text('[]')
    (folder / '110000_football.json').write_text('{"success":false,"value":{}}')
    assert f.latest_snapshot('football') == (None, None)
