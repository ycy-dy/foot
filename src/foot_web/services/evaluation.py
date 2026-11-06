"""Descriptive, point-in-time probability evaluation; never fills missing historical forecasts."""
import json
import math
import sqlite3
from pathlib import Path

from ..storage.publications import select_effective_tickets
from .research import fingerprint, match_key, moment
from .recommendations import build_bundle
from .reviews import settle

EPSILON = 1e-15


def probability(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 1 else None


def _leg_key(day, leg):
    return day + ':' + fingerprint({key: leg.get(key) for key in (
        'sport', 'number', 'matchup', 'match_date', 'market', 'goal_line')}
        | {'keys': [o.get('key') for o in leg.get('options', [])]})[:24]


def forecast_rows(records, unit='ticket'):
    out = []
    for record in records:
        day, legs = record['business_date'], record.get('legs', [])
        settled = record.get('settled_legs') or []
        match_ids = [day + ':' + str(l.get('sport')) + ':' + str(l.get('number')) for l in legs]
        if unit == 'leg':
            for index, leg in enumerate(legs):
                out.append({'key': _leg_key(day, leg), 'p': leg.get('p_mkt'),
                            'hit': settled[index].get('hit') if len(settled) > index else None,
                            'matches': [match_ids[index]], 'sport': leg.get('sport'), 'market': leg.get('market')})
        else:
            out.append({'key': fingerprint(sorted(_leg_key(day, leg) for leg in legs)),
                        'p': record.get('p_mkt'), 'hit': record.get('hit'), 'matches': match_ids,
                        'sport': legs[0].get('sport') if legs else None,
                        'market': '+'.join(str(leg.get('market')) for leg in legs)})
    return out


def score_forecasts(rows):
    unique = {}
    for row in rows:
        unique.setdefault(row['key'], row)
    result = {'records': len(rows), 'duplicates': len(rows) - len(unique), 'scored': 0,
              'pending': 0, 'missing_probability': 0, 'clipped': 0, 'hits': 0,
              'brier': None, 'log_loss': None, 'hit_rate': None, 'mean_p_mkt': None,
              'unique_matches': len({key for row in rows for key in row['matches']})}
    buckets = [{'label': f'{10*i}–{10*(i+1)}%', 'n': 0, 'sum_p': 0.0, 'hits': 0} for i in range(10)]
    brier = loss = p_total = 0.0
    for row in unique.values():
        if row['hit'] is not True and row['hit'] is not False:
            result['pending'] += 1
            continue
        p = probability(row.get('p'))
        if p is None:
            result['missing_probability'] += 1
            continue
        y = int(row['hit'])
        result['scored'] += 1
        result['hits'] += y
        clipped = min(1 - EPSILON, max(EPSILON, p))
        result['clipped'] += clipped != p
        brier += (p - y)**2
        loss -= y * math.log(clipped) + (1-y) * math.log(1-clipped)
        p_total += p
        bucket = buckets[min(9, int(p*10))]
        bucket['n'] += 1
        bucket['sum_p'] += p
        bucket['hits'] += y
    n = result['scored']
    if n:
        result.update(brier=brier/n, log_loss=loss/n, hit_rate=result['hits']/n, mean_p_mkt=p_total/n)
    result['bins'] = [{'label': b['label'], 'n': b['n'], 'hits': b['hits'],
                       'mean_p': b['sum_p']/b['n'] if b['n'] else None,
                       'rate': b['hits']/b['n'] if b['n'] else None} for b in buckets]
    return result


def _baseline_ticket(group, day):
    return {'business_date': day, 'kind': '足球最终串' if group['sport'] == 'football' else '篮球最终串',
            'title': group['name'], 'p_mkt': group['p_mkt_joint'], 'actual_stake': None, 'actual_return': None,
            'legs': [{'sport': leg['sport'], 'number': leg['num'], 'matchup': leg['matchup'],
                      'home': leg['home'], 'away': leg['away'], 'match_date': leg['kickoff'][:10],
                      'kickoff': leg['kickoff'], 'market': '双平' if leg['market'] == 'DD' else leg['market'],
                      'goal_line': leg['L'], 'options': leg['options'], 'p_mkt': leg['p_mkt']}
                     for leg in group['legs']]}


class Evaluation:
    def __init__(self, config, ledger, publications):
        self.config, self.ledger, self.publications = config, ledger, publications

    def report(self, month='', group='最终推荐', unit='ticket', sport='all'):
        records = [row for row in self.ledger.all() if not row.get('superseded')
                   and row.get('group') == group and (not month or row['business_date'].startswith(month))
                   and (sport == 'all' or any(leg['sport'] == sport for leg in row['legs']))]
        samples = forecast_rows(records, unit=unit)
        result = {'scores': score_forecasts(samples), 'month': month, 'group': group, 'unit': unit, 'sport': sport,
                  'by_market': {}, 'paired': self.paired_comparison(month, sport),
                  'ai_traced_records': sum(bool(row.get('ai_decision', {}).get('response_sha256')) for row in records),
                  'legacy_records': sum(not bool(row.get('ai_decision', {}).get('response_sha256')) for row in records)}
        for market in sorted({row['market'] for row in samples}):
            result['by_market'][market] = score_forecasts([row for row in samples if row['market'] == market])
        return result

    def paired_comparison(self, month='', sport='all'):
        root = Path(self.config['PROJECT_DIR'])
        path = Path(self.config['DATA_DIR']) / 'app.db'
        rows, gaps = [], []
        if not path.exists():
            return {'rows': rows, 'gaps': gaps, 'baseline': score_forecasts([]), 'ai': score_forecasts([]),
                    'matched_periods': 0, 'baseline_available': 0, 'ai_available': 0}
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='review_current'").fetchone():
                reviews = {}
            else:
                reviews = {day: json.loads(payload) for day, payload in db.execute('SELECT date,payload FROM review_current')}
        observations, results_by_day = [], {}
        for publication in self.publications.list():
            day = publication['business_date']
            if publication['status'] not in ('published', 'withdrawn') or (month and not day.startswith(month)):
                continue
            try:
                folder = root / 'runs' / day / publication['id']
                audit = json.loads((folder / 'audit.json').read_text(encoding='utf-8'))
                source = audit['source']
                if moment(source['as_of']) > moment(publication['created_at']):
                    raise ValueError('事前快照时点晚于发布')
                items = [{'match_key': match_key(match), 'match': match, 'status': 'succeeded', 'payload': None}
                         for match in source['football'] + source['basketball']]
                baseline = build_bundle(source, items, publication['manifest'], publication['created_at'])
                actual = json.loads((folder / 'tickets.json').read_text(encoding='utf-8'))
                if day not in results_by_day and day in reviews:
                    review_id = reviews[day]['run_id']
                    if Path(review_id).name != review_id:
                        raise ValueError('复盘版本身份无效')
                    results_by_day[day] = json.loads((root / 'runs' / day / review_id / 'results.json').read_text(encoding='utf-8'))
                ai_by_title = {ticket['title']: ticket for ticket in actual
                               if ticket['kind'] in ('足球最终串', '篮球最终串')}
                base_by_title = {group['name']: _baseline_ticket(group, day) for group in baseline['groups']}
                for title in sorted(ai_by_title.keys() | base_by_title.keys()):
                    ai, base = ai_by_title.get(title), base_by_title.get(title)
                    item_sport = (ai or base)['legs'][0]['sport']
                    if sport != 'all' and item_sport != sport:
                        continue
                    observations.append({
                        'business_date': day, 'kind': (ai or base)['kind'], 'title': title,
                        'published_at': publication['created_at'],
                        # Freeze a period before the earliest leg of either strategy.
                        'legs': (ai or {}).get('legs', []) + (base or {}).get('legs', []),
                        'baseline_ticket': base, 'ai_ticket': ai, 'publication_id': publication['id'],
                        'withdrawn': publication['status'] == 'withdrawn'})
            except (OSError, ValueError, KeyError, TypeError):
                gaps.append(day + ' 冻结发布/赛果资料不完整，未纳入同批对照')
        baseline_rows, ai_rows = [], []
        available_base = available_ai = paired = 0
        for observation in select_effective_tickets(observations):
            if observation.get('superseded'):
                continue
            day, title = observation['business_date'], observation['title']
            base, ai = observation['baseline_ticket'], observation['ai_ticket']
            results = results_by_day.get(day)
            available_base += base is not None
            available_ai += ai is not None
            base_result = settle(base, results) if base and results else None
            ai_result = settle(ai, results) if ai and results else None
            rows.append({'date': day, 'period': title, 'baseline': base_result, 'ai': ai_result,
                         'baseline_available': bool(base), 'ai_available': bool(ai),
                         'publication_id': observation['publication_id'], 'withdrawn': observation['withdrawn']})
            if results is None:
                gaps.append(day + ' 尚无复盘赛果快照，对照结果待定')
            if base and ai:
                paired += 1
                base_sample = forecast_rows([base_result or base])[0]
                ai_sample = forecast_rows([ai_result or ai])[0]
                comparable = all(sample['hit'] is True or sample['hit'] is False
                                 for sample in (base_sample, ai_sample))
                comparable = comparable and all(probability(sample['p']) is not None
                                                for sample in (base_sample, ai_sample))
                if not comparable:
                    base_sample['hit'] = ai_sample['hit'] = None
                baseline_rows.append(base_sample)
                ai_rows.append(ai_sample)
        # The same event can occur in several periods; keep paired samples aligned.
        unique_pairs = {}
        for base, ai in zip(baseline_rows, ai_rows):
            key = fingerprint([base['key'], ai['key']])
            base['key'] = ai['key'] = key
            unique_pairs.setdefault(key, (base, ai))
        baseline_rows = [pair[0] for pair in unique_pairs.values()]
        ai_rows = [pair[1] for pair in unique_pairs.values()]
        return {'rows': rows, 'gaps': list(dict.fromkeys(gaps)), 'baseline': score_forecasts(baseline_rows), 'ai': score_forecasts(ai_rows),
                'matched_periods': paired, 'baseline_available': available_base, 'ai_available': available_ai}
