"""命中率回测：用竞彩官方赛果及胜平负(HAD)最终赔率检验市场基准与各玩法命中率。

用法：python3 -I tools/hitrate_backtest.py [results.json] [out.json]
注意：官方结果中的h/d/a视为赛后公布的最终胜平负赔率(接近收盘)；赛前实际可买价格可能不同。
"""
import collections, json, math, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / 'ledger/data/official_results_2026-09-01_to_11-04.json'
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE / 'var/hitrate_backtest_results.json'


def load():
    rows = []
    for x in json.loads(SRC.read_text())['football']:
        if x.get('matchResultStatus') != '2' or ':' not in (x.get('sectionsNo999') or ''):
            continue
        try:
            h, d, a = float(x['h']), float(x['d']), float(x['a'])
        except (TypeError, ValueError):
            continue
        H, A = map(int, x['sectionsNo999'].split(':'))
        hh = ha = None
        if ':' in (x.get('sectionsNo1') or ''):
            hh, ha = map(int, x['sectionsNo1'].split(':'))
        res = 'h' if H > A else 'd' if H == A else 'a'
        fo, side = (h, 'h') if h <= a else (a, 'a')
        rows.append(dict(date=x['matchDate'], lg=x['leagueNameAbbr'], h=h, d=d, a=a, H=H, A=A, hh=hh, ha=ha,
                         L=int(float(x.get('goalLine') or 0)), res=res, fo=fo, side=side, win=res == side))
    return rows


def rate(xs):
    return round(sum(xs) / len(xs), 4) if xs else None


def wilson_low(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    return round((p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n), 4)


def main():
    rows = load()
    n = len(rows)
    out = {'source': str(SRC.relative_to(BASE)), 'n_matches': n,
           'date_range': [min(r['date'] for r in rows), max(r['date'] for r in rows)],
           'odds_note': '官方最终胜平负赔率，近似收盘价；不是赛前每个时点的可买价格'}
    out['mean_had_inverse_sum'] = round(sum(1 / r['h'] + 1 / r['d'] + 1 / r['a'] for r in rows) / n, 4)

    # 市场比例去水 vs 常数基准
    base = collections.Counter(r['res'] for r in rows)
    base = {k: base[k] / n for k in 'hda'}
    bs_m = bs_b = ll_m = ll_b = 0.0
    cal = collections.defaultdict(lambda: [0, 0.0, 0])
    for r in rows:
        q = {k: 1 / r[k] for k in 'hda'}
        Q = sum(q.values())
        p = {k: q[k] / Q for k in q}
        for k in 'hda':
            y = r['res'] == k
            bs_m += (p[k] - y) ** 2
            bs_b += (base[k] - y) ** 2
            b = min(int(p[k] * 10), 9)
            cal[b][0] += 1; cal[b][1] += p[k]; cal[b][2] += y
        ll_m -= math.log(p[r['res']]); ll_b -= math.log(base[r['res']])
    out['base_rates'] = {k: round(v, 4) for k, v in base.items()}
    out['scores'] = {'brier_market_devig': round(bs_m / n, 4), 'brier_constant': round(bs_b / n, 4),
                     'logloss_market_devig': round(ll_m / n, 4), 'logloss_constant': round(ll_b / n, 4)}
    out['calibration'] = [{'bin': f'{b / 10:.1f}-{(b + 1) / 10:.1f}', 'n': c[0], 'pred': round(c[1] / c[0], 4),
                           'obs': round(c[2] / c[0], 4)} for b, c in sorted(cal.items())]

    # 热门赔率分档命中率
    bands = [(1.0, 1.33), (1.33, 1.45), (1.45, 1.60), (1.60, 1.80), (1.80, 2.20), (2.20, 99)]
    out['favorite_bands'] = []
    for lo, hi in bands:
        s = [r for r in rows if lo <= r['fo'] < hi]
        k = sum(r['win'] for r in s)
        out['favorite_bands'].append({'band': f'[{lo},{hi})', 'n': len(s), 'hit': rate([r['win'] for r in s]),
                                      'wilson95_low': wilson_low(k, len(s)),
                                      'roi_at_final_odds': round(sum(r['fo'] for r in s if r['win']) / len(s) - 1, 4) if s else None})

    # 其他玩法经验命中率
    m = {}
    tg = [min(r['H'] + r['A'], 7) for r in rows]
    m['total_goals_distribution'] = {str(k): round(tg.count(k) / n, 4) for k in range(8)}
    m['total_goals_best_adjacent_pair_2_3'] = rate([t in (2, 3) for t in tg])
    for L in (-1, 1):
        s = [r for r in rows if r['L'] == L]
        m[f'double_draw_L{L:+d}'] = {'n': len(s), 'hit': rate([(r['H'] == r['A']) or (r['H'] + L == r['A']) for r in s])}
    for lo, hi in [(1.0, 1.5), (1.33, 1.8)]:
        s = [r for r in rows if r['hh'] is not None and lo <= r['fo'] <= hi]
        ff = [r['win'] and ((r['hh'] > r['ha']) if r['side'] == 'h' else (r['hh'] < r['ha'])) for r in s]
        m[f'hafu_fav_fav_fav_{lo}-{hi}'] = {'n': len(s), 'ft_win': rate([r['win'] for r in s]), 'fav_fav': rate(ff)}
    s = [r for r in rows if r['L'] == -1]
    m['home_minus1_margin'] = {'n': len(s), 'win_by_2plus': rate([r['H'] - r['A'] >= 2 for r in s]),
                               'win_by_1': rate([r['H'] - r['A'] == 1 for r in s]), 'not_win': rate([r['H'] <= r['A'] for r in s])}
    out['market_type_empirical'] = m

    # 每日二串一简单策略
    byd = collections.defaultdict(list)
    for r in rows:
        byd[r['date']].append(r)

    def daily(cond, label):
        res, prod = [], []
        for d in sorted(byd):
            c = sorted([r for r in byd[d] if cond(r)], key=lambda r: r['fo'])[:2]
            if len(c) == 2:
                res.append(c[0]['win'] and c[1]['win']); prod.append(c[0]['fo'] * c[1]['fo'])
        k = len(res); half = k // 2
        return {'strategy': label, 'days': k, 'hit': rate(res), 'avg_combined_odds': round(sum(prod) / k, 3),
                'roi_at_final_odds': round(sum(p for p, w in zip(prod, res) if w) / k - 1, 4),
                'first_half_hit': rate(res[:half]), 'second_half_hit': rate(res[half:])}

    out['daily_two_leg'] = [daily(lambda r: r['fo'] >= 1.33, '当日最低价两场胜平负热门(>=1.33)'),
                            daily(lambda r: 1.33 <= r['fo'] <= 1.55, '热门1.33-1.55'),
                            daily(lambda r: r['fo'] >= 1.45, '为凑组合>2.1/2.5只选>=1.45热门')]
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
