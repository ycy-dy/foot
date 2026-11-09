"""赛前多时点覆盖审计（规格038）。只读：不抓取、不写文件、不改数据库。

用法：
    .venv/bin/python tools/pit_coverage.py --date 2026-11-08
    .venv/bin/python tools/pit_coverage.py --date 2026-11-08 --sport basketball --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from foot_web.data import markets, pit  # noqa: E402


def load_captures(root: Path, business_date: str, sport: str) -> dict[str, dict]:
    """读取业务日前后的快照，按官方 ID 归集该业务日的比赛。"""
    keys = {}
    start = datetime.fromisoformat(business_date)
    for offset in (-1, 0, 1):
        day = (start + timedelta(days=offset)).strftime('%Y-%m-%d')
        folder = root / 'snapshots' / day
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob(f'*_{sport}.json')):
            clock = path.name.split('_', 1)[0]
            try:
                captured = datetime.strptime(day + clock, '%Y-%m-%d%H%M%S')
            except ValueError:
                continue
            try:
                payload = json.loads(path.read_bytes())
            except (OSError, ValueError):
                continue
            parser = markets.parse_football if sport == 'football' else markets.parse_basketball
            try:
                rows = parser(payload)
            except (KeyError, TypeError, ValueError):
                continue
            for row in rows:
                if row.get('business_date') != business_date:
                    continue
                key = row.get('official_id') or row.get('num')
                item = keys.setdefault(key, {'row': row, 'captures': []})
                item['captures'].append({'captured_at': captured.isoformat(sep=' ', timespec='seconds'),
                                         'file': str(path)})
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description='赛前多时点快照覆盖审计（只读）')
    parser.add_argument('--date', required=True, help='业务日 YYYY-MM-DD')
    parser.add_argument('--sport', choices=['football', 'basketball'], default='football')
    parser.add_argument('--root', default='var', help='项目数据目录（默认 var）')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    args = parser.parse_args()

    keys = load_captures(Path(args.root), args.date, args.sport)
    quick = [
        {'num': item['row'].get('num'), 'official_id': key,
         'kickoff': item['row'].get('kickoff'),
         **pit.coverage(item['captures'], item['row'].get('kickoff'))}
        for key, item in keys.items()
        if item['row'].get('kickoff')
    ]
    quick.sort(key=lambda row: (row['kickoff'], row['num'] or ''))

    if args.json:
        print(json.dumps({'business_date': args.date, 'sport': args.sport, 'matches': quick},
                         ensure_ascii=False, indent=2))
        return 0

    if not quick:
        print(f'{args.date} {args.sport}: 没有找到该业务日的官方赛程快照')
        return 0

    print(f'业务日 {args.date} · {args.sport} · 共 {len(quick)} 场（只读审计）')
    header = f"{'编号':<10}{'开球':<18}{'T-24h':<22}{'T-6h':<22}{'T-90m':<22}{'收盘lead'}"
    print(header)
    for row in quick:
        cells = []
        for name in ('T-24h', 'T-6h', 'T-90m'):
            item = row['aspects'][name]
            cells.append('—' if not item['available'] else f"{item['captured_at'][5:16]}(-{item['stale_minutes']}m)")
        closing = row['closing']
        tail = '—' if not closing else f"{closing['lead_minutes']}m"
        print(f"{row['num'] or '?':<10}{row['kickoff'][5:16]:<18}{cells[0]:<22}{cells[1]:<22}{cells[2]:<22}{tail}")

    for name in ('T-24h', 'T-6h', 'T-90m'):
        have = sum(1 for row in quick if row['aspects'][name]['available'])
        print(f'{name} 覆盖 {have}/{len(quick)}')
    closing_only = sum(1 for row in quick if row['closing'] and not row['aspects']['T-24h']['available'])
    print(f'只有收盘快照、缺最早基线的场次：{closing_only}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
