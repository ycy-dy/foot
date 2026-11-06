(() => {
  const panel = document.querySelector('[data-review-status]');
  if (!panel) return;
  const taskId = panel.dataset.reviewStatus;
  const lines = document.getElementById('review-log-lines');
  let cursor = 0, timer, stopped = false;
  async function poll() {
    let next = true, more = false;
    try {
      const response = await fetch(`/api/reviews/${encodeURIComponent(taskId)}?after=${cursor}`, {
        cache: 'no-store', signal: AbortSignal.timeout(10000)
      });
      if (response.status === 401 || response.status === 403) {
        next = false;
        throw new Error('登录已失效，请刷新登录');
      }
      if (!response.ok) throw new Error('暂时无法获取状态，将自动重连');
      const data = await response.json();
      const task = data.task;
      cursor = data.next_cursor ?? cursor;
      more = data.has_more;
      panel.querySelector('[data-task-state]').textContent = {
        queued:'排队中',running:'复盘中',succeeded:'已更新结果',failed:'复盘未完成',interrupted:'进程中断'
      }[task.status] || task.status;
      panel.querySelector('[data-task-message]').textContent = task.message;
      panel.querySelector('[data-task-updated]').textContent = task.updated_at;
      if (lines) for (const row of data.logs || []) {
        const line = document.createElement('li');
        line.className = `log-line log-${row.kind}`;
        const time = document.createElement('time');
        time.textContent = row.ts.slice(11,19);
        const source = document.createElement('span');
        source.className = 'log-source';
        source.textContent = row.provider;
        const kind = document.createElement('span');
        kind.className = 'log-kind';
        kind.textContent = row.kind;
        const message = document.createElement('div');
        message.className = 'log-text';
        message.textContent = row.message;
        line.append(time,source,kind,message);
        lines.append(line);
        if (lines.children.length > 600) lines.firstElementChild.remove();
      }
      const active = ['queued','running'].includes(task.status);
      if (!active && !more) {
        if (panel.dataset.hasReport === 'false' && (task.result_ready || panel.dataset.refreshOnFinish === 'true')) location.reload();
        next = false;
      }
      panel.querySelector('[data-poll-state]').textContent = active ? '后台正在执行，状态与日志自动刷新。' : '执行记录已同步';
    } catch (error) {
      panel.querySelector('[data-poll-state]').textContent = error.message;
    }
    if (!stopped && next) timer = setTimeout(poll, more ? 50 : document.hidden ? 3000 : 1000);
  }
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
  poll();
})();
