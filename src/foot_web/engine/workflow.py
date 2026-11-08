"""A bounded, resumable round of per-match evidence research."""
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..data.fetcher import Fetcher
from ..core.config import runtime_provider
from ..core.files import write_once
from ..services.recommendations import render_report
from ..services.selection import (DECISION_SCHEMA, apply_decision, decision_context, load_decision,
                                  make_decision_prompt, validate_decision)
from ..services.research import (ANALYSIS_REQUEST, EVIDENCE_SCHEMA, exclusion_reason, json_text, make_match_prompt,
                                 fingerprint, match_key, moment, validate_evidence)
from ..services.versions import research_rules, rules_manifest, same_version
from ..services.reuse import reuse_recent
from ..storage.db import Store
from ..storage.research import ResearchStore
from .logs import redact, secret_values
from .providers import ProviderError
from .decisions import decide
from .research_stages import run_research_stages

TZ = ZoneInfo('Asia/Shanghai')


def run_workflow(config, task_id, prepare, generator, fetcher=None, as_of=None):
    store = Store(Path(config['DATA_DIR']) / 'app.db')
    research = ResearchStore(config['DATA_DIR'])
    if not store.claim_analysis(task_id, os.getpid()):
        return
    task = store.analysis(task_id)
    folder = Path(config['PROJECT_DIR']) / 'runs' / task['business_date'] / task_id
    secrets = secret_values(config, os.environ)
    attempts = json.loads(task['attempts'])
    clock = lambda: moment(as_of) if as_of else datetime.now(TZ)
    started_round = time.monotonic()

    def log(provider, kind, text):
        safe = redact(text, secrets)
        if safe:
            store.analysis_log(task_id, provider, kind, safe)

    def finish(status, message):
        store.update_analysis(task_id, status=status, message=message, attempts=attempts,
                              finished_at=datetime.now(TZ).isoformat(timespec='seconds'))

    def clean(value):
        if isinstance(value, dict):
            return {redact(key, secrets, limit=None) if isinstance(key, str) else key: clean(v)
                    for key, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return redact(value, secrets, limit=None) if isinstance(value, str) else value

    try:
        selected_provider = runtime_provider(config)
        budget = max(30, min(14400, int(config.get('FOOT_ANALYSIS_BUDGET') or 1800)))
        timeout = max(10, min(3600, int(config.get('FOOT_MATCH_TIMEOUT') or config.get('FOOT_ANALYSIS_TIMEOUT') or 180)))
        if research.cancelled(task_id):
            finish('cancelled', '已取消分析')
            return
        workflow = research.workflow(task_id)
        if workflow is None:
            manifest, texts = rules_manifest(config['PROJECT_DIR'])
            if manifest['compatibility'] != 'supported_subset':
                raise ValueError('当前没有可执行的分析与推荐体系')
            log('system', 'status', '正在刷新并冻结官方快照和规则版本')
            source = prepare(config, task, fetcher or Fetcher(config['DATA_DIR']), clock())
            rules = '\n\n'.join(name + '\n' + text for name, text in texts.items())
            source['analysis_request'] = clean({'text': ANALYSIS_REQUEST, 'business_date': task['business_date'],
                                                'project_dir': str(Path(config['PROJECT_DIR']).resolve()), 'rules': rules})
            manifest['source_sha256'] = fingerprint(source)
            manifest['schema_sha256'] = fingerprint(EVIDENCE_SCHEMA)
            folder.mkdir(parents=True, mode=0o700, exist_ok=False)
            for name, text in {'input.json': json_text(source), 'rules.md': rules, 'research-rules.md': research_rules(texts),
                               'manifest.json': json_text(manifest)}.items():
                with (folder / name).open('x', encoding='utf-8') as handle:
                    handle.write(text)
            items = [{'match': match, 'match_key': match_key(match), 'reason': exclusion_reason(match, clock())}
                     for match in source['football'] + source['basketball']]
            research.initialize(task_id, manifest, source, items)
            log('system', 'status', f'已冻结 {len(items)} 场完整清单；逐场保存，单场时限 {timeout} 秒，本轮预算 {budget} 秒')
            log('system', 'status', selected_provider + '总任务：' + ANALYSIS_REQUEST + ' · 业务日 ' + task['business_date'])
            workflow = research.workflow(task_id)
        else:
            current, _ = rules_manifest(config['PROJECT_DIR'])
            if current['compatibility'] != 'supported_subset' or not same_version(current, workflow['manifest']):
                raise ValueError('规则或程序版本已变化，请重新分析')
            log('system', 'status', '正在复用冻结输入与已完成检查点，只处理未完成比赛')
        source, manifest = workflow['source'], workflow['manifest']
        rules = (folder / 'research-rules.md').read_text(encoding='utf-8')
        research.phase(task_id, 'research')
        cached = reuse_recent(config, task, workflow, folder, research, clock(), log)
        if cached:
            attempts += cached
            store.update_analysis(task_id, attempts=attempts)
        unavailable = set()
        consecutive_timeouts = 0
        timeout_stopped = False
        for item in research.items(task_id):
            if item['status'] in ('succeeded', 'excluded'):
                continue
            if research.cancelled(task_id):
                raise ProviderError('cancelled', '已取消，已完成逐场结果保留')
            if time.monotonic() - started_round >= budget:
                log('system', 'warning', '本轮预算用尽，未完成项已保留，可继续分析')
                break
            match, key = item['match'], item['match_key']
            reason = exclusion_reason(match, clock())
            if reason:
                research.update_item(task_id, key, status='excluded', message=reason)
                log('system', 'warning', match['num'] + ' · ' + reason)
                continue
            decision_time = clock()
            prompt = make_match_prompt(match, rules, decision_time)
            first_team, second_team = (match['away'], match['home']) if match['sport'] == 'basketball' else (match['home'], match['away'])
            prefix = f'{match["num"]} {first_team} VS {second_team}'
            research.update_item(task_id, key, status='running', as_of=decision_time.isoformat(), message='正在研究证据')
            item_attempts = item['attempts'] or []
            for provider in (selected_provider,):
                if provider in unavailable:
                    continue
                if research.cancelled(task_id):
                    raise ProviderError('cancelled', '管理员已取消')
                remaining = budget - (time.monotonic() - started_round)
                if remaining < 10:
                    break
                message = prefix + ' · ' + provider + ' 研究中'
                store.update_analysis(task_id, provider=provider, message=message, attempts=attempts)
                log(provider, 'status', message)
                started = time.monotonic()
                deadline = started + min(timeout, remaining)
                stage, response_path = 'research', None
                checkpoint = folder / 'matches' / key
                checkpoint.mkdir(parents=True, exist_ok=True)

                def save_failure(exc, code):
                    record = {'provider': provider, 'sport': match['sport'], 'num': match['num'],
                              'match_key': key, 'status': 'failed', 'code': code,
                              'message': redact(str(exc), secrets), 'stage': stage,
                              'seconds': round(time.monotonic() - started, 1)}
                    if response_path:
                        record['response'] = response_path
                    record['attempt_artifact'] = f'attempt-{uuid.uuid4().hex}.json'
                    write_once(checkpoint / record['attempt_artifact'], json_text(record))
                    attempts.append(record)
                    item_attempts.append(record)
                    research.update_item(task_id, key, status='failed', message=record['message'], attempts=item_attempts)
                    store.update_analysis(task_id, attempts=attempts)
                    log(provider, 'error', prefix + ' · ' + record['message'])

                try:
                    def stage_changed(value):
                        nonlocal stage, response_path
                        stage, response_path = value, None

                    def response_saved(result):
                        nonlocal response_path
                        response_path = f'response-{uuid.uuid4().hex}.json'
                        write_once(checkpoint / response_path, json_text(result))

                    def validated(result):
                        nonlocal decision_time
                        decision_time = clock()
                        return validate_evidence(result, match, decision_time)

                    evidence = run_research_stages(
                        provider, prompt, config, generator, deadline, validate=validated,
                        clean=clean, cancelled=lambda: research.cancelled(task_id),
                        on_event=lambda kind, text: log(provider, kind, match['num'] + ' · ' + text),
                        on_response=response_saved, on_invalid=save_failure, on_stage=stage_changed)
                    if research.cancelled(task_id):
                        raise ProviderError('cancelled', '管理员已取消，等待续跑')
                except (ProviderError, ValueError) as exc:
                    code = exc.code if isinstance(exc, ProviderError) else 'invalid_output'
                    consecutive_timeouts = consecutive_timeouts + 1 if code == 'timeout' else 0
                    timeout_stopped = consecutive_timeouts >= 2
                    save_failure(exc, code)
                    if code in ('cancelled', 'cleanup_failed'):
                        raise
                    if timeout_stopped:
                        break
                    if code in ('authentication', 'unavailable', 'rate_limit', 'configuration', 'search_unavailable'):
                        unavailable.add(provider)
                        log(provider, 'warning', '本轮后续比赛跳过该不可用提供方')
                    continue
                consecutive_timeouts = 0
                timeout_stopped = False
                record = {'provider': provider, 'sport': match['sport'], 'num': match['num'],
                          'match_key': key, 'status': 'succeeded', 'code': 'ok', 'message': '逐场证据已保存',
                          'stage': stage, 'response': response_path,
                          'seconds': round(time.monotonic() - started, 1),
                          'checkpoint': f'attempt-{len(item_attempts) + 1:03d}-{uuid.uuid4().hex[:12]}.json'}
                record['attempt_artifact'] = f'attempt-{uuid.uuid4().hex}.json'
                write_once(checkpoint / record['attempt_artifact'], json_text(record))
                attempts.append(record)
                item_attempts.append(record)
                with (checkpoint / record['checkpoint']).open('x', encoding='utf-8') as handle:
                    handle.write(json_text({'match': match, 'as_of': decision_time, 'provider': provider,
                                            'payload': evidence, 'manifest': manifest}))
                research.update_item(task_id, key, status='succeeded', message='研究完成，来源待人工复核',
                                     payload=evidence, attempts=item_attempts, as_of=decision_time.isoformat())
                store.update_analysis(task_id, attempts=attempts)
                log(provider, 'status', prefix + ' · 检查点已保存')
                break
            if timeout_stopped:
                log('system', 'warning', '连续两次研究超时，停止本轮以避免重复消耗；成功检查点保留，请用户明确重试')
                break
            if selected_provider in unavailable:
                log('system', 'error', selected_provider + '不可用，不回退其他提供方；保留剩余比赛等待续跑')
                break
        progress = research.progress(task_id)
        if progress['failed'] or progress['pending'] or progress['running']:
            status = 'partial' if progress['completed'] else 'failed'
            log('system', 'warning', f'已完成 {progress["completed"]} 场；失败 {progress["failed"]} 场，'
                f'待处理 {progress["pending"] + progress["running"]} 场，可续跑')
            finish(status, '逐场研究尚未全部完成，已完成结果保留')
            return
        if research.cancelled(task_id):
            raise ProviderError('cancelled', '已取消')
        research.phase(task_id, 'compose')
        log('system', 'status', '逐场研究完成，正在枚举合规候选并请求AI推荐决策')
        items = research.items(task_id)
        from ..services.evidence_reviews import runtime_items
        items = runtime_items(config, task_id, items, clock())
        context = decision_context(source, items, manifest, clock())
        context_path = folder / 'decision-context.json'
        if (folder / 'ai-decision.json').exists():
            envelope, saved_context = load_decision(folder)
            if saved_context != context:
                raise ValueError('AI决策时点的候选资格已变化，请重新分析')
        else:
            if context_path.exists() and json.loads(context_path.read_text(encoding='utf-8')) != context:
                raise ValueError('已冻结AI候选资格变化，请重新分析')
            write_once(context_path, json_text(context))
            remaining = budget - (time.monotonic() - started_round)
            if remaining < 10:
                finish('partial', '逐场证据已完成；本轮预算不足以进行AI推荐决策，可继续分析')
                return
            decision_folder = folder / ('decision-' + uuid.uuid4().hex)

            def decision_event(provider, kind, text):
                store.update_analysis(task_id, provider=provider, message='AI推荐决策 · ' + text)
                log(provider, kind, text)

            try:
                envelope = decide(config | {'FOOT_ANALYSIS_TIMEOUT': str(min(timeout, int(remaining)))},
                                  decision_folder, make_decision_prompt(context), DECISION_SCHEMA,
                                  lambda value: validate_decision(value, context, source, items, manifest, clock()),
                                  generator=generator, on_event=decision_event,
                                  cancelled=lambda: research.cancelled(task_id))
            finally:
                attempts_path = decision_folder / 'attempts.json'
                if attempts_path.exists():
                    attempts += [record | {'stage': 'recommendation_decision', 'artifact_dir': decision_folder.name}
                                 for record in json.loads(attempts_path.read_text(encoding='utf-8'))]
                    store.update_analysis(task_id, attempts=attempts)
            write_once(folder / 'ai-decision.json', json_text(envelope))
        provenance = {key: value for key, value in envelope.items() if key != 'result'}
        bundle = apply_decision(envelope['result'], context, source, items, manifest, clock(), provenance)
        bundle_path = folder / 'recommendations.draft.json'
        if bundle_path.exists():
            saved = json.loads(bundle_path.read_text(encoding='utf-8'))
            if saved['selection_sha256'] != bundle['selection_sha256'] or saved['manifest'] != manifest:
                raise ValueError('已保存草稿与AI决策不一致')
            bundle = saved
        from ..services.daily_ledger import draft_ledger
        for name, text in {'daily-ledger.draft.json': json_text(draft_ledger(bundle, task_id)),
                           'recommendations.draft.json': json_text(bundle),
                           'report.draft.md': render_report(bundle, items)}.items():
            write_once(folder / name, text)
        if research.cancelled(task_id):
            raise ProviderError('cancelled', '已取消，完整草稿已保存，可继续')
        research.phase(task_id, 'draft')
        log('system', 'status', '结构化草稿已保存，需刷新官方数据审核和人工复核后发布')
        finish('succeeded', '逐场研究与分析草稿已生成，待审核，尚未发布')
        store.event('analysis_completed', task['requested_by'], detail={'task_id': task_id, 'matches': progress['completed']})
    except ProviderError as exc:
        if exc.code == 'search_unavailable':
            attempts.append({'provider': selected_provider, 'status': 'failed',
                             'stage': 'search_readiness', 'code': exc.code})
        log('system', 'warning' if exc.code == 'cancelled' else 'error', str(exc))
        finish('cancelled' if exc.code == 'cancelled' else
               'partial' if research.progress(task_id)['completed'] else 'failed', str(exc))
    except Exception as exc:
        log('system', 'error', '工作流执行失败 · ' + type(exc).__name__)
        progress = research.progress(task_id)
        finish('partial' if progress['completed'] else 'failed', '分析未完成，已完成检查点保留；' + type(exc).__name__)
        store.event('analysis_failed', task['requested_by'], detail={'task_id': task_id, 'error_type': type(exc).__name__})
