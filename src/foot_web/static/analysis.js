(() => {
  'use strict';
  const initial = document.getElementById('analysis-task-data');
  if (!initial) return;
  let task;
  try {
    const parsed = JSON.parse(initial.textContent || 'null');
    task = parsed && typeof parsed === 'object' ? parsed : null;
  } catch (_) {
    task = null;
  }
  const normalizeTask = value => {
    if (!value || typeof value !== 'object') return null;
    return {...value, attempts: Array.isArray(value.attempts) ? value.attempts : [],
      progress: value.progress && typeof value.progress === 'object' ? value.progress : {}};
  };
  const normalizeLog = row => ({...row, id: Number(row.id), provider: row.provider || 'system',
    kind: row.kind || 'status', message: String(row.message ?? ''), ts: row.ts || new Date().toISOString()});
  task = normalizeTask(task);
  let timer, controller, pollGeneration = 0;
  let submitting = false, controlPending = null, stopped = false, cursor = 0, rows = [], filter = 'all', lastEvent = null, unseen = 0;
  let lastMatchUpdate = '', matchRequest = false;
  const byId = id => document.getElementById(id);
  const workspace = byId('analysis-workspace');
  const button = byId('btn-recompute');
  const banner = byId('analysis-status');
  const title = byId('analysis-title');
  const message = byId('analysis-message');
  const result = byId('analysis-result');
  const detail = document.querySelector('[data-analysis-detail]');
  const panel = byId('analysis-log-panel');
  const viewport = byId('analysis-log-viewport');
  const lines = byId('analysis-log-lines');
  const follow = byId('analysis-log-follow');
  const search = byId('analysis-log-search');
  const latest = byId('analysis-log-latest');
  const connection = byId('analysis-log-connection');
  const active = value => value && ['queued', 'running'].includes(value.status);
  const names = {harness: 'DeepSeek Harness', system: '系统', claude: '历史 Claude', codex: 'Codex CLI'};
  const kinds = {start: '启动', status: '状态', tool: '网页', output: '输出', warning: '警告', error: '错误', heartbeat: '存活'};
  const duration = ms => {
    const seconds = Math.max(0, Math.floor(ms / 1000));
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  };
  const clock = date => new Date(date).toLocaleTimeString('zh-CN', {hour12: false, timeZone: 'Asia/Shanghai'});

  function tick() {
    if (!task) return;
    const end = task.finished_at ? new Date(task.finished_at).getTime() : Date.now();
    byId('analysis-elapsed').textContent = `${active(task) ? '已用时' : '总耗时'} ${duration(end - new Date(task.created_at))}`;
    byId('analysis-last-event').textContent = lastEvent
      ? active(task) ? `最近事件 ${duration(Date.now() - new Date(lastEvent))} 前` : `最后事件 ${clock(lastEvent)}`
      : active(task) ? '等待首条日志' : '无过程日志';
  }

  function renderStages() {
    const progress = task.progress || {};
    const failed = ['failed', 'interrupted', 'partial', 'cancelled'].includes(task.status);
    const state = {
      snapshot: progress.total ? ['done', '已冻结']
        : failed ? ['failed', '未完成'] : task.status === 'running' ? ['active', '准备中'] : ['pending', '等待'],
      research: progress.phase === 'research' && active(task) ? ['active', '研究中']
        : ['compose', 'draft'].includes(progress.phase) ? ['done', '已保存'] : failed ? ['failed', '可续跑'] : ['pending', '等待'],
      compose: progress.phase === 'compose' && active(task) ? ['active', '计算中']
        : progress.phase === 'draft' ? ['done', '已计算'] : ['pending', '等待'],
      draft: task.publication_state === 'withdrawn' ? ['done', '展示已撤销']
        : task.publication_url ? ['done', '已发布']
        : task.status === 'succeeded' ? ['done', '待审核'] : failed ? ['skipped', '未生成'] : ['pending', '等待']
    };
    document.querySelectorAll('[data-analysis-stage]').forEach(element => {
      if (!state[element.dataset.analysisStage]) return;
      const [value, label] = state[element.dataset.analysisStage];
      element.dataset.state = value;
      element.querySelector('small').textContent = label;
    });
  }

  function renderAttempts() {
    const body = byId('analysis-attempt-rows');
    if (!body) return;
    const attempts = [...task.attempts];
    if (active(task) && task.provider) attempts.push({provider: task.provider, status: 'running', message: '执行中', seconds: null});
    byId('analysis-attempts').hidden = !attempts.length;
    body.replaceChildren();
    for (const attempt of attempts) {
      const tr = document.createElement('tr');
      for (const text of [names[attempt.provider], attempt.status === 'succeeded' ? '已完成' : attempt.status === 'running' ? '执行中' : '调用失败',
        attempt.message, attempt.seconds === null ? '—' : `${attempt.seconds}s`]) {
        const td = document.createElement('td');
        td.textContent = text;
        tr.append(td);
      }
      tr.lastElementChild.className = 'num';
      body.append(tr);
    }
  }

  function render() {
    const stopping = !!active(task) && (controlPending === 'cancel' || task.progress?.cancel_requested
      || task.message === '正在取消，等待CLI清理');
    document.querySelectorAll('[data-analysis-action="cancel"]').forEach(control => {
      control.hidden = !active(task);
      control.disabled = !!controlPending || stopping;
      control.setAttribute('aria-busy', String(stopping));
      control.querySelector('span').textContent = stopping ? '正在终止…' : '终止分析';
    });
    if (button) {
      const running = !!active(task);
      button.disabled = running || submitting;
      button.classList.toggle('is-loading', running || submitting);
      button.setAttribute('aria-busy', String(running || submitting));
      const label = button.querySelector('span') || button;
      label.textContent = submitting ? '正在提交…' : stopping ? '正在终止…'
        : running ? `${names[task.provider] || '后台'}分析中` : '重新分析';
    }
    workspace.hidden = !task && !submitting && !banner.classList.contains('analysis-failed');
    if (!task) return;
    banner.classList.toggle('analysis-failed', ['failed', 'interrupted', 'partial'].includes(task.status));
    banner.classList.toggle('analysis-running', !!active(task));
    title.textContent = task.publication_state === 'withdrawn' ? '发布展示已撤销 · 原票保留'
      : task.publication_url ? '分析已审核发布 · 原草稿保留'
      : task.status === 'succeeded' ? '分析稿已生成 · 待审核'
      : task.status === 'failed' ? '分析失败'
      : task.status === 'interrupted' ? '分析已中断'
      : task.status === 'partial' ? '部分完成 · 检查点已保留'
      : task.status === 'cancelled' ? '分析已终止 · 检查点已保留'
      : stopping ? '正在终止分析 · 已完成结果保留'
      : task.status === 'queued' ? '分析任务已提交'
      : `${names[task.provider] || '后台'} 分析中`;
    const previous = task.attempts.find(attempt => attempt.status === 'failed');
    message.textContent = `${task.business_date} · ${task.message}${active(task) && previous ? ' · ' + names[previous.provider] + '：' + previous.message : ''}`;
    result.hidden = !!detail;
    result.href = task.publication_url || task.result_url;
    result.firstChild.textContent = task.status === 'succeeded' ? '查看分析稿 ' : '查看任务 ';
    byId('analysis-log-download').href = `${task.logs_url}/download`;
    renderStages();
    renderAttempts();
    const progress = task.progress || {};
    if (byId('analysis-match-progress')) {
      byId('analysis-match-progress').textContent = progress.total
        ? `逐场进度 · 已完成 ${progress.completed}/${progress.total} · 复用 ${progress.reused || 0} · 排除 ${progress.excluded} · 失败 ${progress.failed}`
        : '逐场进度 · 等待快照';
    }
    if (byId('analysis-resume')) {
      byId('analysis-resume').hidden = !progress.generation || !['partial', 'failed', 'cancelled', 'interrupted'].includes(task.status);
      byId('analysis-resume').disabled = !!controlPending;
    }
    if (byId('analysis-reuse-label')) byId('analysis-reuse-label').hidden = !progress.generation;
    refreshMatches();
    tick();
  }

  async function refreshMatches() {
    const list = byId('research-match-list');
    if (!list || !task?.matches_url || matchRequest || lastMatchUpdate === task.updated_at) return;
    matchRequest = true;
    const id = task.id;
    try {
      const response = await fetch(task.matches_url, {cache: 'no-store', signal: AbortSignal.timeout(10000)});
      if (!response.ok || id !== task?.id || stopped) return;
      const data = await response.json();
      lastMatchUpdate = data.task.updated_at;
      byId('research-match-count').textContent = `${data.matches.length} 场完整清单`;
      if (!data.matches.length) return;
      const fragment = document.createDocumentFragment();
      const labels = {succeeded: '已保存', running: '研究中', failed: '失败，可续跑', excluded: '已排除', pending: '等待'};
      for (const match of data.matches) {
        const link = document.createElement('a');
        link.className = 'research-match-row';
        link.href = match.url;
        link.dataset.matchKey = match.match_key;
        const meta = document.createElement('span');
        meta.className = 'research-match-meta';
        meta.textContent = match.num;
        const small = document.createElement('small');
        small.textContent = `${match.kickoff} · ${match.league}`;
        meta.append(small);
        const teams = document.createElement('span');
        teams.className = 'research-match-teams';
        teams.textContent = match.sport === 'basketball' ? `${match.away}（客） VS ${match.home}（主）` : `${match.home} VS ${match.away}`;
        const state = document.createElement('span');
        state.className = 'research-match-state';
        state.textContent = labels[match.status] || match.status;
        const note = document.createElement('span');
        note.className = 'research-match-note';
        note.textContent = `${match.message} · 来源 ${match.sources}`;
        link.append(meta, teams, state, note);
        fragment.append(link);
      }
      list.replaceChildren(fragment);
    } catch (_) {
      // The existing log poll owns the connection indicator and retries.
    } finally {
      matchRequest = false;
    }
  }

  function scrollLatest() {
    viewport.scrollTop = viewport.scrollHeight;
    unseen = 0;
    latest.hidden = true;
  }

  function renderLogs() {
    const query = search.value.trim().toLocaleLowerCase();
    const visible = rows.filter(row => (filter === 'all' || row.provider === filter)
      && (!query || row.message.toLocaleLowerCase().includes(query)));
    const existing = new Map([...lines.children].map(line => [Number(line.dataset.logId), line]));
    const desired = new Set(visible.map(row => row.id));
    for (const [id, line] of existing) if (!desired.has(id)) line.remove();
    const fragment = document.createDocumentFragment();
    for (const row of visible) {
      if (existing.has(row.id)) continue;
      const li = document.createElement('li');
      li.className = `log-line log-${row.kind}`;
      li.dataset.logId = row.id;
      const time = document.createElement('time');
      time.dateTime = row.ts;
      time.textContent = clock(row.ts);
      const source = document.createElement('span');
      source.className = `log-source log-source-${row.provider}`;
      source.textContent = names[row.provider];
      const kind = document.createElement('span');
      kind.className = 'log-kind';
      kind.textContent = kinds[row.kind] || '状态';
      const text = document.createElement('div');
      text.className = 'log-text';
      text.textContent = row.message;
      li.append(time, source, kind, text);
      fragment.append(li);
    }
    const top = viewport.scrollTop;
    lines.append(fragment);
    // A filter change can restore earlier events; keep the persisted cursor order.
    const ordered = [...lines.children].sort((a, b) => Number(a.dataset.logId) - Number(b.dataset.logId));
    ordered.forEach((line, index) => { if (lines.children[index] !== line) lines.insertBefore(line, lines.children[index] || null); });
    byId('analysis-log-empty').hidden = !!visible.length;
    byId('analysis-log-empty').querySelector('span').textContent = rows.length
      ? '当前筛选下没有日志' : active(task) ? '等待智能体输出执行事件' : '此任务未保存过程日志，仅有执行记录';
    byId('analysis-log-count').textContent = `${visible.length} 条日志${rows.length === 600 ? ' · 最近记录' : ''}`;
    if (follow.checked && panel.open) scrollLatest();
    else viewport.scrollTop = top;
  }

  async function poll() {
    clearTimeout(timer);
    if (!task || stopped) return;
    const id = task.id;
    const generation = ++pollGeneration;
    const currentController = new AbortController();
    controller = currentController;
    const stale = () => id !== task?.id || stopped || generation !== pollGeneration;
    const timeout = setTimeout(() => currentController.abort(), 10000);
    let more = false;
    let retry = true;
    try {
      const response = await fetch(`${task.logs_url}?after=${cursor}`, {cache: 'no-store', signal: currentController.signal});
      if (stale()) return;
      if (response.redirected || response.status === 401 || response.status === 403) {
        retry = false;
        throw new Error('登录已失效，请刷新登录');
      }
      if (response.status === 404) {
        retry = false;
        throw new Error('任务记录不存在');
      }
      if (!response.ok) throw new Error('连接中断，正在重连');
      const data = await response.json();
      if (stale()) return;
      task = normalizeTask(data.task);
      if (!task || !Array.isArray(data.logs)) throw new Error('任务状态格式无效');
      const incoming = data.logs.filter(row => row && Number.isFinite(Number(row.id)) && Number(row.id) > cursor).map(normalizeLog);
      if (incoming.length) {
        rows = [...rows, ...incoming].slice(-600);
        const activity = incoming.filter(row => row.kind !== 'heartbeat');
        if (activity.length) lastEvent = activity.at(-1).ts;
        if (!follow.checked) {
          unseen += incoming.length;
          latest.textContent = `查看最新 · ${unseen}`;
          latest.hidden = false;
        }
      }
      cursor = Number.isFinite(Number(data.next_cursor)) ? Number(data.next_cursor) : cursor;
      more = data.has_more;
      connection.textContent = active(task) ? '实时同步' : more ? '读取记录' : '已结束';
      connection.dataset.state = active(task) ? 'live' : 'done';
      byId('analysis-log-sync').textContent = `同步于 ${clock(Date.now())}`;
      render();
      if (incoming.length || !rows.length) renderLogs();
      if (!active(task) && !more && task.status === 'succeeded' && detail?.dataset.hasReport === 'false') {
        location.assign(task.result_url);
      }
    } catch (error) {
      if (stale()) return;
      connection.textContent = retry ? '正在重连' : '需要处理';
      connection.dataset.state = 'error';
      byId('analysis-log-sync').textContent = retry ? '连接中断，正在重连' : error.message;
    } finally {
      clearTimeout(timeout);
      if (!stale() && retry && (active(task) || more || connection.dataset.state === 'error')) {
        timer = setTimeout(poll, more ? 50 : document.hidden ? 3000 : 1000);
      }
    }
  }

  document.querySelectorAll('[data-log-provider]').forEach(control => control.addEventListener('click', () => {
    filter = control.dataset.logProvider;
    document.querySelectorAll('[data-log-provider]').forEach(item => {
      item.classList.toggle('on', item === control);
      item.setAttribute('aria-pressed', String(item === control));
    });
    renderLogs();
  }));
  search.addEventListener('input', renderLogs);
  follow.addEventListener('change', () => { if (follow.checked) scrollLatest(); });
  latest.addEventListener('click', () => { follow.checked = true; scrollLatest(); });
  viewport.addEventListener('wheel', event => { if (event.deltaY < 0) follow.checked = false; }, {passive: true});
  for (const event of ['pointerdown', 'touchstart']) {
    viewport.addEventListener(event, () => { follow.checked = false; }, {passive: true});
  }
  viewport.addEventListener('keydown', event => {
    if (['ArrowUp', 'PageUp', 'Home'].includes(event.key)) follow.checked = false;
  });
  panel.addEventListener('toggle', () => { if (panel.open && follow.checked) scrollLatest(); });
  for (const action of ['cancel', 'resume']) {
    document.querySelectorAll(`[data-analysis-action="${action}"]`).forEach(control => control.addEventListener('click', async () => {
      if (controlPending || !task) return;
      controlPending = action;
      render();
      try {
        const response = await fetch(`/api/analysis/${task.id}/${action}`, {
          method: 'POST', headers: {'X-CSRF': window.FOOT.csrf, 'Content-Type': 'application/json'},
          body: '{}', signal: AbortSignal.timeout(12000)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || '操作未完成');
        task = normalizeTask(data.task);
        if (!task) throw new Error('任务状态格式无效');
        controller?.abort();
        ++pollGeneration;
        clearTimeout(timer);
        render();
        poll();
        window.FOOT.toast(action === 'cancel' ? '已请求终止，已完成结果保留' : '已继续分析');
      } catch (error) {
        window.FOOT.toast(error.message);
      } finally {
        controlPending = null;
        render();
      }
    }));
  }

  button?.addEventListener('click', async () => {
    if (submitting || active(task)) return;
    submitting = true;
    render();
    try {
      const response = await fetch('/api/recompute', {
        method: 'POST',
        headers: {'X-CSRF': window.FOOT.csrf, 'Content-Type': 'application/json'},
        body: JSON.stringify({date: document.querySelector('[data-date-select]')?.value || button.dataset.analysisDate,
          reuse_from: task?.progress?.generation && byId('analysis-reuse').checked ? task.id : null}),
        signal: AbortSignal.timeout(12000)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success || !data.task) throw new Error(data.message || data.task?.message || `HTTP ${response.status}`);
      controller?.abort();
      clearTimeout(timer);
      task = data.task;
      cursor = 0;
      rows = [];
      lines.replaceChildren();
      lastEvent = null;
      unseen = 0;
      follow.checked = true;
      latest.hidden = true;
      panel.open = true;
      if (detail) detail.hidden = true;
      render();
      renderLogs();
      window.FOOT.toast(data.reused ? '已有分析任务正在执行' : '已提交分析');
      if (detail) {
        location.assign(task.result_url);
        return;
      }
      poll();
    } catch (error) {
      workspace.hidden = false;
      title.textContent = '分析提交未完成';
      const failure = error.name === 'TimeoutError' ? '提交状态未确认，请刷新查看任务，勿重复提交' : error.message;
      message.textContent = failure;
      banner.classList.add('analysis-failed');
      window.FOOT.toast(failure);
    } finally {
      submitting = false;
      render();
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && task && active(task)) {
      controller?.abort();
      clearTimeout(timer);
      poll();
    }
  });
  const clockTimer = setInterval(tick, 1000);
  window.addEventListener('pagehide', () => {
    stopped = true;
    controller?.abort();
    clearTimeout(timer);
    clearInterval(clockTimer);
  });
  render();
  if (task) poll();
})();
