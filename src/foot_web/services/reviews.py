"""Frozen-ticket, deterministic review. No model calls, publishing or betting IO."""
import copy
import hashlib
from html import escape
import itertools
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from foot_web.data.results import ResultsFetcher, match_result
from foot_web.storage.db import Store

ENGINE_VERSION = 'review-settlement-1.0.0'
TZ = ZoneInfo('Asia/Shanghai')
CURRENT_SCHEMA = '''CREATE TABLE IF NOT EXISTS review_current (
    date TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL
)'''
DERIVED = {'id', 'ui_id', 'ticket_id', 'group', 'state', 'settlement', 'settled_legs', 'branches',
           'hit', 'hits', 'legs_hit', 'legs_total', 'sim_cost', 'theoretical_return',
           'actual_stake', 'actual_return', 'review_id', 'review_run_id', 'attribution',
           'score', 'half', 'note', 'result', 'summary', 'per_match'}
CRS_HOME = {(1, 0), (2, 0), (2, 1), (3, 0), (3, 1), (3, 2),
            (4, 0), (4, 1), (4, 2), (5, 0), (5, 1), (5, 2)}
CRS_DRAW = {(0, 0), (1, 1), (2, 2), (3, 3)}
GROUPS = {'足球最终串': '最终推荐', '篮球最终串': '最终推荐',
          '足球单场方向': '单场方向', '篮球单场方向': '单场方向',
          '胜平负': '六类方向', '让球': '六类方向', '进球数': '六类方向',
          '二三球': '六类方向', '半全场': '六类方向', '双平': '六类方向', '梦想单': '梦想单'}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def frozen_ticket(record):
    """Remove only derived review/UI values; always retain the original legs/odds."""
    row = {k: copy.deepcopy(v) for k, v in record.items()
           if k not in DERIVED and not k.startswith('actual_')}
    if isinstance(row.get('legs'), list):
        row['legs'] = [{k: v for k, v in leg.items() if k not in DERIVED and not k.startswith('actual_')}
                       for leg in row['legs']]
    return row


def ticket_id(record):
    """Content identity independent of settlements, UI indexes and replacement flags."""
    frozen = frozen_ticket(record)
    for key in ('superseded', 'superseded_by', 'version_note', 'after_freeze_revision',
                'withdrawn', 'withdrawal_reason', 'withdrawn_at', 'withdrawn_by'):
        frozen.pop(key, None)
    return _sha(_json(frozen).encode('utf-8'))


def _decimal(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _wdl(home, away):
    return 'h' if home > away else 'a' if home < away else 'd'


def option_hit(leg, option, result):
    """Pure tri-state evaluator. Unknown key/line/half or integer push => None."""
    market, key = leg.get('market'), option.get('key')
    if not isinstance(market, str) or not isinstance(key, str):
        return None
    H, A = result['H'], result['A']
    allowed = {'football': {'HAD', 'HHAD', 'TTG', 'HAFU', 'CRS', '双平'},
               'basketball': {'MNL', 'HDC', 'HILO'}}
    if market not in allowed.get(leg.get('sport'), set()):
        return None
    if market in ('HAD', 'MNL'):
        valid = ('h', 'a') if market == 'MNL' else ('h', 'd', 'a')
        return key == _wdl(H, A) if key in valid and (market != 'MNL' or H != A) else None
    if market in ('HHAD', 'HDC', '双平', 'HILO'):
        if market == '双平' and key == 'had_d':
            return H == A
        line = _decimal(leg.get('goal_line'))
        if line is None:
            return None
        if market in ('HHAD', 'HDC'):
            if key not in (('h', 'a') if market == 'HDC' else ('h', 'd', 'a')):
                return None
            adjusted = Decimal(H) + line
            if market == 'HDC' and adjusted == A:
                return None  # no guessed refund on integer spreads
            return key == _wdl(adjusted, Decimal(A))
        if market == '双平':
            return Decimal(H) + line == A if key == 'hhad_d' else None
        if key not in ('h', 'l') or Decimal(H + A) == line:
            return None
        return key == ('h' if Decimal(H + A) > line else 'l')
    if market == 'TTG':
        return key == f's{min(H + A, 7)}' if key in {f's{i}' for i in range(8)} else None
    if market == 'HAFU':
        if key not in {a + b for a in 'hda' for b in 'hda'} or result.get('hH') is None or result.get('hA') is None:
            return None
        return key == _wdl(result['hH'], result['hA']) + _wdl(H, A)
    if market == 'CRS':
        exact = re.fullmatch(r's(\d+)s(\d+)', str(key))
        if exact:
            pair = tuple(map(int, exact.groups()))
            # Only official exact-score selections, not arbitrary invented keys.
            allowed = CRS_HOME | CRS_DRAW | {(a, h) for h, a in CRS_HOME}
            return (H, A) == pair if pair in allowed else None
        other = {'s1sh': 'h', 's1sd': 'd', 's1sa': 'a'}.get(key)
        if other is None:
            return None
        outcome = _wdl(H, A)
        standard = CRS_HOME if outcome == 'h' else CRS_DRAW if outcome == 'd' else {(a, h) for h, a in CRS_HOME}
        return outcome == other and (H, A) not in standard
    return None


def settle(record, results):
    """Pure settlement using only original lines and option odds (Decimal)."""
    row = frozen_ticket(record)
    legs = []
    for original in row['legs']:
        leg = copy.deepcopy(original)
        result, note = match_result(leg, row['business_date'], results)
        hits = [option_hit(leg, option, result) if result else None for option in leg['options']]
        if result and None in hits:
            note = '玩法/选项/原盘口/半场缺失或整数走盘，待核；不推测退款'
        if any(_decimal(o.get('odds')) is None or _decimal(o.get('odds')) <= 0 for o in leg['options']):
            note = (note + '；' if note else '') + '缺有效原赔率，理论返还待核'
        leg.update(hits=hits, hit=True if True in hits else None if None in hits or not hits else False,
                   score=result['score'] if result else None, half=result['half'] if result else None,
                   result=result, note=note)
        legs.append(leg)
    branches = []
    for indices in itertools.product(*(range(len(leg['options'])) for leg in legs)):
        odds = [_decimal(legs[i]['options'][j].get('odds')) for i, j in enumerate(indices)]
        hits = [legs[i]['hits'][j] for i, j in enumerate(indices)]
        product = None
        if all(o is not None and o > 0 for o in odds):
            product = Decimal(1)
            for odd in odds:
                product *= odd
        branches.append({'options': list(indices), 'product': str(product) if product is not None else None,
                         'hit': None if None in hits else all(hits), 'sim_cost': 2,
                         'theoretical_return': None if product is None or None in hits else
                         str((product * 2 if all(hits) else Decimal(0)).quantize(Decimal('.01'), ROUND_HALF_UP))})
    hit = None if not branches or any(leg['hit'] is None for leg in legs) else any(b['hit'] is True for b in branches)
    returns = [b['theoretical_return'] for b in branches]
    ret = sum((Decimal(v) for v in returns), Decimal(0)) if returns and None not in returns else None
    row.update(ticket_id=ticket_id(record), settled_legs=legs, branches=branches, hit=hit,
               legs_hit=sum(leg['hit'] is True for leg in legs), legs_total=len(legs), sim_cost=2 * len(branches),
               theoretical_return=str(ret.quantize(Decimal('.01'), ROUND_HALF_UP)) if ret is not None else None,
               actual_stake=None, actual_return=None, attribution='未评估：缺少可核验的事前与赛后非赔率证据')
    row.setdefault('superseded', False)
    row['group'] = GROUPS.get(row.get('kind'), '结构研究' if '结构' in str(row.get('kind', '')) or row.get('ledger') == 'structure' else '其他')
    row['state'] = 'pending' if hit is None else 'hit' if hit else 'miss'
    return row


def _summary(rows):
    def count(items):
        settled = [r for r in items if r['hit'] is not None]
        hit = sum(r['hit'] is True for r in settled)
        return {'n': len(items), 'settled': len(settled), 'hit': hit, 'pending': len(items) - len(settled),
                'rate': hit / len(settled) if settled else None,
                'sim_cost': sum(r['sim_cost'] for r in items),
                'settled_sim_cost': sum(r['sim_cost'] for r in settled),
                'theoretical_return': None if any(r['theoretical_return'] is None for r in items) else
                str(sum((Decimal(r['theoretical_return']) for r in items), Decimal(0)).quantize(Decimal('.01'))),
                'return_pending': sum(r['theoretical_return'] is None for r in items),
                'actual_stake': None, 'actual_return': None}
    active = [r for r in rows if not r.get('superseded')]
    groups = dict.fromkeys(['最终推荐', '单场方向', '六类方向', '结构研究', '梦想单'] + [r['group'] for r in active])
    return {'total': count(active), 'by_group': {g: count([r for r in active if r['group'] == g]) for g in groups},
            'by_kind': {k: count([r for r in active if r.get('kind') == k]) for k in dict.fromkeys(r.get('kind') for r in active)},
            'superseded': count([r for r in rows if r.get('superseded')])}


def _per_match(rows):
    matches = {}
    for row in rows:
        for leg in row['settled_legs']:
            identity = (leg['sport'], leg['number'], leg.get('match_date') or (leg.get('result') or {}).get('match_date'), leg.get('matchup'))
            item = matches.setdefault(identity, {'sport': identity[0], 'number': identity[1], 'match_date': identity[2],
                                                'matchup': identity[3], 'score': leg['score'], 'half': leg['half'],
                                                'selections': [], 'attribution': row['attribution']})
            item['selections'].append({'ticket_id': row['ticket_id'], 'kind': row.get('kind'), 'group': row['group'],
                                       'superseded': row.get('superseded', False), 'market': leg.get('market', 'UNKNOWN'),
                                       'goal_line': leg.get('goal_line'), 'options': copy.deepcopy(leg['options']),
                                       'hits': leg['hits'], 'hit': leg['hit'], 'note': leg['note']})
    return list(matches.values())


def _is_ticket(row, business_date):
    if not isinstance(row, dict) or row.get('business_date') != business_date:
        return False
    if not all(key in row for key in ('ledger', 'kind', 'title', 'source_file', 'snapshot')):
        return False
    if (row.get('status') in ('draft', 'unpublished', 'rejected') or row.get('publish_status') in ('draft', 'unpublished', 'rejected')
            or row.get('published') is False or row.get('is_draft')):
        return False
    return (isinstance(row.get('legs'), list) and bool(row['legs']) and
            all(isinstance(leg, dict) and leg.get('sport') in ('football', 'basketball') and
                leg.get('number') and isinstance(leg.get('options'), list) and bool(leg['options']) and
                all(isinstance(o, dict) for o in leg['options']) for leg in row['legs']))


def load_tickets(project_dir, business_date, data_dir=None):
    """Known normalized JSONL only; settled fallback is explicitly recorded, never scanned reports."""
    data = Path(project_dir) / 'ledger' / 'data'
    rows, sources = [], []
    for path in sorted(data.glob('*records*.jsonl')):
        raw = path.read_bytes()
        parsed = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
        matching = [frozen_ticket(row) for row in parsed if _is_ticket(row, business_date)]
        if matching:
            rows.extend(matching)
            sources.append({'path': str(path.relative_to(project_dir)), 'sha256': _sha(raw), 'format': 'normalized-jsonl'})
    if not rows:
        path = data / 'settled_records.json'
        if path.exists():
            raw = path.read_bytes()
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError('settled_records 不是标准化票列表')
            rows = [frozen_ticket(row) for row in parsed if _is_ticket(row, business_date)]
            if rows:
                sources.append({'path': str(path.relative_to(project_dir)), 'sha256': _sha(raw),
                                'format': 'settled-fallback-original-legs', 'note': '仅原legs，剥离原结算与UI字段'})
    from foot_web.storage.publications import published_tickets, select_effective_tickets
    published = published_tickets(Path(data_dir or Path(project_dir) / 'var') / 'app.db', business_date)
    if published:
        rows.extend(frozen_ticket(row) for row in published)
        sources.append({'path': 'sqlite:publications', 'sha256': _sha(_json(published).encode()),
                        'format': 'promoted-normalized-tickets', 'publication_ids': sorted({r['publication_id'] for r in published})})
    if not rows:
        raise ValueError('该业务日没有可复盘的已知标准化冻结原票')
    unique = {}
    for row in rows:
        key = ticket_id(row)
        if key in unique and unique[key].get('superseded') and not row.get('superseded'):
            # Never resurrect or discard the replacement relationship of an old version.
            continue
        unique[key] = row
    return select_effective_tickets(list(unique.values())), sources


def _markdown(business_date, run_id, rows, summary, per_match):
    def cell(value):
        if value is None:
            return '未保存/待核'
        return escape(str(value), quote=False).replace('|', '&#124;').replace('\n', '；').replace('\r', '')

    def status(hit):
        return '待核' if hit is None else '命中' if hit else '未中'

    def value(v):
        return '未保存/待核' if v is None else str(v)

    def options(leg):
        return '／'.join(f'{value(o.get("label") or o.get("key"))}@{value(o.get("odds"))}'
                        for o in leg['options'])

    def market_probability(leg):
        # New publications store the whole leg/union probability on the leg;
        # legacy tickets may instead retain per-option forecasts. Do not infer either.
        parts = []
        if leg.get('p_mkt') is not None:
            parts.append('本腿：' + value(leg['p_mkt']))
        if any(option.get('p_mkt') is not None for option in leg['options']):
            parts.append('分项：' + '／'.join(value(option.get('p_mkt')) for option in leg['options']))
        return '；'.join(parts) or '未保存/待核'

    def table(headers, records):
        lines.extend(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |'])
        for record in records:
            lines.append('| ' + ' | '.join(cell(v) for v in record) + ' |')

    lines = [f'# {business_date} 确定性复盘', '', f'复盘版本：{run_id}；结算引擎：{ENGINE_VERSION}', '',
             '按冻结原票盘口与赔率结算；模拟每分支2元，复式计全部分支投入。实际金额与返还均为null。未提交、未下单，不保证命中或收益。',
             '足球比分为主:客；篮球比分为客:主、让分按主队口径。待核不计入命中率分母；缺原赔率的事件命中仍可统计，但不计入模拟收益。',
             '以下只复盘原票，不是新的推荐。事后归因未评估，缺少可核验的非赔率证据；缺失事前p_mkt不补写。', '',
             '## 最终推荐复盘汇总', '']
    final = [r for r in rows if r['group'] == '最终推荐' and not r.get('superseded')]
    if final:
        table(['方案', '原选项与赔率', '命中状态', '模拟投入', '理论返还'],
              [(r['title'], ' ＋ '.join(f'{l["number"]} {options(l)}' for l in r['settled_legs']),
                status(r['hit']), r['sim_cost'], r['theoretical_return']) for r in final])
    else:
        lines.append('该业务日没有当前版本的最终推荐原票；不把研究方向补作最终推荐。')
    lines += ['', '## 推荐命中率台账', '', '实际投注金额/实际返还固定为null；表内金额仅为模拟单位与理论分支返还。', '']
    table(['业务日', '栏目/类别', '方案', '状态', '单腿命中', '模拟投入', '理论返还', '原票来源'],
          [(r['business_date'], f'{r["group"]}/{r.get("kind", "未保存")}', r['title'],
            ('被替代，不计分母；' if r.get('superseded') else '') + status(r['hit']),
            f'{r["legs_hit"]}/{r["legs_total"]}', r['sim_cost'], r['theoretical_return'], r.get('source_file')) for r in rows])
    lines += ['', '## 分栏统计', '']
    table(['栏目', '命中/已结算', '命中率', '待核', '模拟总投入', '理论总返还', '返还待核'],
          [(g, f'{s["hit"]}/{s["settled"]}', f'{s["rate"]:.1%}' if s['rate'] is not None else '—',
            s['pending'], s['sim_cost'], s['theoretical_return'], s['return_pending']) for g, s in summary['by_group'].items()])
    lines += ['', f'被替代原票另存：{summary["superseded"]["n"]} 张，不计入当前分母。', '', '## 逐场结算']
    for match in per_match:
        lines += ['', f'### {cell(match["sport"])} {cell(match["number"])} {cell(match["matchup"])}',
                  f'比赛日期：{cell(match["match_date"])}；比分：{cell(match["score"])}；半场：{cell(match["half"])}', '']
        table(['栏目/类别', '原玩法/盘口', '原选项与赔率', '各选项结果', '腿结果', '版本', '缺口/备注'],
              [(f'{s["group"]}/{s.get("kind", "未保存")}',
                s['market'] + (f'（{s["goal_line"]}）' if s['goal_line'] not in (None, '') else ''),
                options(s), '／'.join(status(h) for h in s['hits']), status(s['hit']),
                '被替代' if s['superseded'] else '当前原票', s['note'] or '—') for s in match['selections']])
        lines += ['', cell(match['attribution'])]
    lines += ['', '## 逐票与分支', '', '每分支模拟2元；只有该分支所有腿全中才命中。未知结果或原赔率不推测返还。']
    for row in rows:
        lines += ['', f'### {cell(row.get("title", "原票"))}', '', f'原票ID：{row["ticket_id"]}',
                  f'状态：{"被替代/" if row.get("superseded") else ""}{status(row["hit"])}；模拟成本：{row["sim_cost"]}；理论返还：{cell(row["theoretical_return"])}', '']
        legs = row['settled_legs']
        table(['场次', '原玩法/盘口', '原选项与赔率', '市场基准命中概率p_mkt（原票）'],
              [(l['number'], l.get('market', 'UNKNOWN') + (f'（{l["goal_line"]}）' if l.get('goal_line') not in (None, '') else ''),
                options(l), market_probability(l)) for l in legs])
        lines.append('')
        table(['分支', '原选项', '赔率乘积', '命中状态', '模拟投入', '理论返还'],
              [(i + 1, ' ＋ '.join(f'{legs[j]["number"]} {legs[j]["options"][k].get("label") or legs[j]["options"][k].get("key")}'
                                  for j, k in enumerate(b['options'])), b['product'], status(b['hit']), b['sim_cost'], b['theoretical_return'])
               for i, b in enumerate(row['branches'])])
    lines += ['', '来源、抓取原响应与文件哈希见本版本manifest.json、results.json；完整原票与结算见tickets.json、settlement.json。']
    return '\n'.join(lines) + '\n'


class ReviewService:
    def __init__(self, config, store=None, fetcher=None, analyst=None):
        # Without an analyst this is a pure settlement utility, NOT an AI review.
        # The production worker always supplies the required AI analyst.
        self.analyst = analyst
        self.project_dir = Path(config['PROJECT_DIR'])
        self.store = store or Store(Path(config.get('DATA_DIR') or self.project_dir / 'var') / 'app.db')
        self.fetcher = fetcher or ResultsFetcher()
        with self.store.connect() as db:
            db.execute(CURRENT_SCHEMA)

    def run(self, business_date, run_id):
        if date.fromisoformat(business_date).isoformat() != business_date:
            raise ValueError('业务日必须为YYYY-MM-DD')
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', run_id):
            raise ValueError('无效复盘版本ID')
        folder = self.project_dir / 'runs' / business_date / run_id
        if folder.exists():
            raise FileExistsError('复盘目录已存在，不覆盖历史版本')
        tickets, sources = load_tickets(self.project_dir, business_date, self.store.path.parent)
        sports = sorted({leg['sport'] for row in tickets for leg in row['legs']})
        results = self.fetcher.fetch(business_date, sports=sports)
        if (not isinstance(results, dict) or any(not isinstance(results.get(s), list) or
                any(not isinstance(row, dict) for row in results[s]) for s in sports)):
            raise ValueError('赛果抓取未返回完整运动类型列表')
        rows = [settle(ticket, results) for ticket in tickets]
        summary, per_match = _summary(rows), _per_match(rows)
        result = {'business_date': business_date, 'run_id': run_id, 'rows': rows,
                  'summary': summary, 'per_match': per_match, 'folder': str(folder),
                  'analysis_mode': 'ai_review' if self.analyst else 'settlement_only'}
        tickets_text, results_text = _json(tickets), _json(results)
        if self.analyst:
            # No SQLite write lock during slow CLI calls. Freeze raw sources even
            # if AI fails; never promote an incomplete review to the overlay.
            folder.mkdir(parents=True, exist_ok=False)
            for name, text in {'tickets.json': tickets_text, 'results.json': results_text}.items():
                with (folder / name).open('x', encoding='utf-8') as handle:
                    handle.write(text)
            result['ai_analysis'] = self.analyst(result)
        settlement_text = _json(result)
        # Serialize promotion and previous-version selection in the same transaction.
        # A failure writing any artifact rolls back the overlay; partial dirs stay immutable.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT run_id FROM review_current WHERE date = ?', (business_date,)).fetchone()
            manifest = {'business_date': business_date, 'run_id': run_id, 'engine_version': ENGINE_VERSION,
                        'created_at': datetime.now(TZ).isoformat(), 'previous_review_id': previous['run_id'] if previous else None,
                        'sources': sources, 'tickets_sha256': _sha(tickets_text.encode()),
                        'result_sources': [{'sport': s.get('sport'), 'url': s.get('url'),
                                            'sha256': _sha(_json(s.get('response')).encode())}
                                           for s in results.get('sources', [])],
                        'results_sha256': _sha(results_text.encode()), 'settlement_sha256': _sha(settlement_text.encode()),
                        'attribution': '未评估：无可核验的非赔率归因证据', 'actual_stake': None, 'actual_return': None}
            if not self.analyst:
                folder.mkdir(parents=True, exist_ok=False)
            report = _markdown(business_date, run_id, rows, summary, per_match)
            if self.analyst:
                from .review_analysis import render_review_analysis
                analysis = result['ai_analysis']
                manifest['analysis_mode'] = 'ai_review'
                manifest['ai_analysis'] = {k: v for k, v in analysis.items() if k != 'result'}
                manifest['attribution'] = '见独立AI逐票解释；AI分析不修改确定性结算'
                report = report.replace('确定性复盘', 'AI复盘与结算核对', 1)
                report = report.replace('事后归因未评估，缺少可核验的非赔率证据；',
                                        'AI解释与结算分栏，缺少证据时明确归因不足；', 1)
                # Keep the original final recommendation summary first, with a
                # separate, prominently labelled AI assessment before the ledger.
                report = report.replace('## 推荐命中率台账', render_review_analysis(analysis) + '\n## 推荐命中率台账', 1)
            else:
                manifest['analysis_mode'] = 'settlement_only'
                report = report.replace('确定性复盘', '纯结算（非AI复盘）', 1)
            artifacts = {'settlement.json': settlement_text, 'review.md': report,
                         'manifest.json': _json(manifest)}
            if not self.analyst:
                artifacts.update({'tickets.json': tickets_text, 'results.json': results_text})
            for name, text in artifacts.items():
                with (folder / name).open('x', encoding='utf-8') as file:
                    file.write(text)
            db.execute('INSERT INTO review_current (date, run_id, payload) VALUES (?, ?, ?) '
                       'ON CONFLICT(date) DO UPDATE SET run_id=excluded.run_id, payload=excluded.payload',
                       (business_date, run_id, settlement_text))
        return result
