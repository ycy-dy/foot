"""Official result snapshots and conservative identity matching (no import-time IO)."""
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

SPORTS = {'football': 1, 'basketball': 2}


class ResultsFetcher:
    """Inject ``http_get(url, timeout=seconds)``; responses may be dicts or requests responses.

    Each call is bounded and pages above the configured cap fail the entire fetch;
    no partial response is promoted to a successful review.
    """

    def __init__(self, http_get=None, timeout=10, max_pages=20, page_size=100):
        if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 30 or
                not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 100 or
                not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 100):
            raise ValueError('无效赛果超时/分页上限')
        self.http_get = http_get or requests.get
        self.timeout, self.max_pages, self.page_size = timeout, max_pages, page_size

    def fetch(self, business_date, sports=None):
        start = date.fromisoformat(business_date)
        end = start + timedelta(days=2)
        output = {'football': [], 'basketball': [], 'sources': []}
        for sport in dict.fromkeys(SPORTS if sports is None else sports):
            if sport not in SPORTS:
                raise ValueError('未知运动类型')
            pages, page, expected_pages = 1, 1, None
            while page <= pages:
                query = urlencode({'matchBeginDate': start.isoformat(), 'matchEndDate': end.isoformat(),
                                   'leagueId': '', 'pageSize': self.page_size, 'pageNo': page,
                                   'isFix': 0, 'matchPage': 1, 'pcOrWap': 1})
                url = (f'https://webapi.sporttery.cn/gateway/uniform/{sport}/'
                       f'getUniformMatchResultV{SPORTS[sport]}.qry?{query}')
                response = self.http_get(url, timeout=self.timeout)
                if hasattr(response, 'raise_for_status'):
                    response.raise_for_status()
                payload = response if isinstance(response, dict) else response.json()
                value = payload.get('value') if isinstance(payload, dict) else None
                if not isinstance(value, dict) or not isinstance(value.get('matchResult'), list):
                    raise ValueError('官方赛果响应结构无效')
                raw_pages = value.get('pages')
                if isinstance(raw_pages, bool) or not re.fullmatch(r'\d+', str(raw_pages)):
                    raise ValueError('官方赛果分页数无效')
                pages = int(raw_pages)
                if pages > self.max_pages or (pages == 0 and value['matchResult']):
                    raise ValueError('官方赛果超过分页上限或分页异常')
                if expected_pages is not None and expected_pages != pages:
                    raise ValueError('抓取期间分页变动，未保存部分赛果')
                expected_pages = pages
                if (any(not isinstance(row, dict) for row in value['matchResult']) or
                        len(value['matchResult']) > self.page_size or (pages > 1 and not value['matchResult'])):
                    raise ValueError('官方赛果行结构/空页无效')
                output[sport].extend(value['matchResult'])
                output['sources'].append({'sport': sport, 'url': url, 'response': payload})
                page += 1
        return output


def _score(text, separator):
    found = re.fullmatch(r'\s*(\d+)\s*' + re.escape(separator) + r'\s*(\d+)\s*', str(text or ''))
    return tuple(map(int, found.groups())) if found else None


def _team(value):
    # Only typography, not fuzzy transliteration, abbreviations or alias guessing.
    return re.sub(r'\s+', '', str(value or '')).casefold()


def _teams(leg):
    home = leg.get('home_team') or leg.get('homeTeam')
    away = leg.get('away_team') or leg.get('awayTeam')
    if home and away:
        return _team(home), _team(away)
    names = re.split(r'\s+(?:VS|V|vs|v|Vs)\s+|\s*对阵\s*', str(leg.get('matchup', '')))
    if len(names) != 2 or not all(names):
        return None
    names = [re.sub(r'[（(](?:主|客|主队|客队)[）)]', '', s).strip() for s in names]
    if leg.get('sport') == 'basketball':
        names.reverse()
    return tuple(_team(s) for s in names)


def match_result(leg, business_date, results):
    """Return (normalized terminal result, note). Conflicting identities stay pending.

    Without an explicit leg match_date, accept exactly one identity in D..D+2;
    never choose the earliest candidate or use the market's closing handicap.
    """
    sport = leg.get('sport')
    teams = _teams(leg)
    if sport not in SPORTS or not teams:
        return None, '运动类型或原票球队身份缺失，待核'
    start = date.fromisoformat(business_date)
    explicit_date = leg.get('match_date') or leg.get('matchDate')
    try:
        if explicit_date:
            explicit_date = date.fromisoformat(str(explicit_date))
        elif leg.get('kickoff'):
            kickoff = datetime.fromisoformat(str(leg['kickoff']))
            explicit_date = (kickoff.astimezone(ZoneInfo('Asia/Shanghai')) if kickoff.tzinfo else kickoff).date()
    except ValueError:
        return None, '原票比赛日期无效，待核'
    candidates = []
    for row in results.get(sport, []):
        if str(row.get('matchNumStr', '')) != str(leg.get('number', '')):
            continue
        try:
            match_date = date.fromisoformat(str(row.get('matchDate', '')))
        except ValueError:
            continue
        if not 0 <= (match_date - start).days <= 2 or (explicit_date and match_date != explicit_date):
            continue
        home = {_team(row.get(k)) for k in ('allHomeTeam', 'homeTeam')} - {''}
        away = {_team(row.get(k)) for k in ('allAwayTeam', 'awayTeam')} - {''}
        if teams[0] in home and teams[1] in away:
            candidates.append(row)
    # Identical repeated pages are harmless; any distinct candidate is ambiguous.
    candidates = list({json.dumps(r, sort_keys=True, ensure_ascii=False): r for r in candidates}.values())
    if len(candidates) != 1:
        return None, '未找到身份一致的官方赛果' if not candidates else '官方赛果身份/日期/内容歧义，待核'
    row = candidates[0]
    status_text = ' '.join(str(row.get(k) or '') for k in ('resultStatus', 'poolStatus')).casefold()
    if any(marker in status_text for marker in ('取消', '延期', '推迟', '中断', '作废', 'cancel', 'postpon', 'refund', 'abandon')):
        return None, '官方取消/延期/中断标记，待核，不推测退款'
    if sport == 'football':
        if str(row.get('matchResultStatus')) != '2':
            return None, '官方未确认终场（含取消/延期），不推测退款'
        full, half = _score(row.get('sectionsNo999'), ':'), _score(row.get('sectionsNo1'), ':')
        if not full:
            return None, '官方全场比分无效，待核'
        H, A = full
        # Malformed or inconsistent half-time only blocks HAFU, not other markets.
        if half and (half[0] > H or half[1] > A):
            half = None
        hH, hA = half if half else (None, None)
        score, half_text = f'{H}:{A}', f'{hH}:{hA}' if half else None
    else:
        # Official basketball endpoint reports final completion as status=2.
        if str(row.get('status')) != '2':
            return None, '官方篮球未确认终场（含取消/延期），不推测退款'
        full = _score(row.get('finalScore'), '-')
        if not full or full[0] == full[1]:
            return None, '官方篮球全场比分无效，待核'
        A, H = full
        hH = hA = None
        score, half_text = f'{A}:{H}', None
    return {'H': H, 'A': A, 'hH': hH, 'hA': hA, 'score': score, 'half': half_text,
            'match_date': row['matchDate'], 'match_id': row.get('matchId'),
            'official_home': row.get('allHomeTeam') or row.get('homeTeam'),
            'official_away': row.get('allAwayTeam') or row.get('awayTeam')}, ''
