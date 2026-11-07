(() => {
  const panel = document.querySelector('[data-recheck-task]');
  if (!panel) return;
  let cursor = 0, timer, stopped = false;
  const lines = document.getElementById('recheck-log-lines');
  async function poll() {
    let next = true, more = false;
    try {
      const response = await fetch(`/api/rechecks/${encodeURIComponent(panel.dataset.recheckTask)}?after=${cursor}`, {
        cache: 'no-store', signal: AbortSignal.timeout(10000)
      });
      if (response.status === 401 || response.status === 403) {
        next = false;
        throw new Error('登录已失效，请刷新登录');
      }
      if (response.redirected) {
        next = false;
        throw new Error('登录已失效，请刷新登录');
      }
      if (response.status === 404) {
        next = false;
        throw new Error('复核任务不存在或已不可访问，请返回列表');
      }
      if (!response.ok) throw new Error('连接中断，正在重连');
      const data = await response.json();
      cursor = data.next_cursor;
      more = data.has_more;
      panel.querySelector('[data-recheck-state]').textContent = {
        queued:'排队中',running:'复核中',succeeded:'复核完成',partial:'部分完成',
        failed:'复核失败',cancelled:'已取消',interrupted:'进程中断'
      }[data.task.status] || data.task.status;
      panel.querySelector('[data-recheck-message]').textContent = data.task.message;
      panel.querySelector('[data-recheck-connection]').textContent = '同步于 ' + new Date().toLocaleTimeString('zh-CN');
      if (lines) for (const row of data.logs) {
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
      const active = ['queued','running'].includes(data.task.status);
      if (!active) {
        const cancel = document.querySelector('form[action$="/cancel"]');
        if (cancel) cancel.hidden = true;
      }
      if (!active && !more) {
        if (data.task.result_ready && panel.dataset.hasResult === 'false') location.reload();
        next = false;
      }
    } catch (error) {
      panel.querySelector('[data-recheck-connection]').textContent = error.message;
    }
    if (!stopped && next) timer = setTimeout(poll, more ? 50 : document.hidden ? 3000 : 1000);
  }
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
  poll();
})();
