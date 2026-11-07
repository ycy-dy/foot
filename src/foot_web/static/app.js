(() => {
  'use strict';

  const themeButton = document.querySelector('[data-theme-toggle]');
  const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
  const activeTheme = () => document.documentElement.dataset.theme || (systemTheme.matches ? 'dark' : 'light');
  function updateThemeButton() {
    if (!themeButton) return;
    const next = activeTheme() === 'dark' ? '浅色' : '深色';
    themeButton.title = `切换为${next}模式`;
    themeButton.setAttribute('aria-label', themeButton.title);
  }
  themeButton?.addEventListener('click', () => {
    const theme = activeTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('foot-theme', theme); } catch (_) {}
    updateThemeButton();
  });
  systemTheme.addEventListener('change', updateThemeButton);
  updateThemeButton();

  const menu = document.querySelector('.mobile-menu');
  function closeMenu() {
    document.querySelector('.topbar')?.classList.remove('menu-open');
    menu?.setAttribute('aria-expanded', 'false');
    menu?.setAttribute('aria-label', '展开导航');
  }
  menu?.addEventListener('click', () => {
    const open = menu.getAttribute('aria-expanded') !== 'true';
    document.querySelector('.topbar').classList.toggle('menu-open', open);
    menu.setAttribute('aria-expanded', String(open));
    menu.setAttribute('aria-label', open ? '收起导航' : '展开导航');
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu?.getAttribute('aria-expanded') === 'true') {
      closeMenu();
      menu.focus();
    }
  });

  const tabs = [...document.querySelectorAll('[role="tab"][data-tab]')];
  function showTab(name, focus = false) {
    const selected = tabs.find(tab => tab.dataset.tab === name) || tabs[0];
    if (!selected) return;
    tabs.forEach(tab => {
      const active = tab === selected;
      tab.classList.toggle('on', active);
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      const panel = document.getElementById(tab.getAttribute('aria-controls'));
      panel.hidden = !active;
      panel.classList.toggle('on', active);
    });
    if (focus) {
      selected.focus({preventScroll: true});
      selected.scrollIntoView({block: 'nearest', inline: 'nearest'});
    }
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => {
      showTab(tab.dataset.tab);
      history.replaceState(null, '', `#${tab.dataset.tab}`);
    });
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next === undefined) return;
      event.preventDefault();
      showTab(tabs[next].dataset.tab, true);
      history.replaceState(null, '', `#${tabs[next].dataset.tab}`);
    });
  });
  const syncHash = () => showTab(location.hash.slice(1));
  window.addEventListener('hashchange', syncHash);
  syncHash();

  document.querySelector('[data-date-select]')?.addEventListener('change', event => {
    const url = new URL(location.href);
    url.searchParams.set('date', event.target.value);
    location.assign(url);
  });

  const filters = [...document.querySelectorAll('#match-filters button')];
  function filterMatches(value) {
    filters.forEach(button => {
      const active = button.dataset.f === value;
      button.classList.toggle('on', active);
      button.setAttribute('aria-pressed', String(active));
    });
    let count = 0;
    document.querySelectorAll('#panel-matches [data-sport]').forEach(element => {
      const visible = value === 'all' || element.dataset.sport === value || element.dataset.period === value;
      element.hidden = !visible;
      if (visible) count += element.querySelectorAll('.match').length;
    });
    const empty = document.getElementById('match-empty');
    if (empty) empty.hidden = count > 0;
    const result = document.getElementById('filter-result');
    if (result) result.textContent = `${count} 场比赛`;
  }
  filters.forEach(button => button.addEventListener('click', () => filterMatches(button.dataset.f)));
  if (filters.length) filterMatches('all');

  let toastTimer;
  function toast(message) {
    const element = document.getElementById('toast');
    element.textContent = message;
    element.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { element.hidden = true; }, 4500);
  }
  window.FOOT.toast = toast;

  // Native forms must validate first; lock only the submitted form and preserve
  // submitter name/value (for action buttons) before disabling it.
  document.querySelectorAll('form[method="post"]').forEach(form => {
    form.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
      if (form.dataset.submitting === 'true') { event.preventDefault(); return; }
      form.dataset.submitting = 'true';
      form.setAttribute('aria-busy', 'true');
      const submitter = event.submitter;
      if (submitter?.name) {
        const value = document.createElement('input');
        value.type = 'hidden'; value.name = submitter.name; value.value = submitter.value;
        value.dataset.submitterMirror = 'true'; form.append(value);
      }
      form.querySelectorAll('button[type="submit"], button:not([type]), input[type="submit"]').forEach(control => {
        if (control.disabled) return;
        control.dataset.formLocked = 'true';
        control.disabled = true;
        control.setAttribute('aria-busy', 'true');
      });
    });
  });
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('form[data-submitting="true"]').forEach(form => {
      form.dataset.submitting = 'false'; form.removeAttribute('aria-busy');
      form.querySelectorAll('[data-submitter-mirror]').forEach(input => input.remove());
      form.querySelectorAll('[data-form-locked="true"]').forEach(control => {
        control.disabled = false; delete control.dataset.formLocked; control.removeAttribute('aria-busy');
      });
    });
  });

  document.querySelectorAll('.scroll').forEach(element => {
    element.tabIndex = 0;
    element.setAttribute('role', 'region');
    element.setAttribute('aria-label', '数据表格');
  });
  document.querySelectorAll('.md table').forEach(table => { table.tabIndex = 0; });
})();
