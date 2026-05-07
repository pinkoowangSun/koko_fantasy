// Shared utilities used by every page

const API = {
  base: '/api',

  token() {
    return localStorage.getItem('koko_token');
  },

  headers() {
    return {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${this.token()}`,
    };
  },

  async request(method, path, body) {
    const opts = { method, headers: this.headers() };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(this.base + path, opts);
    if (resp.status === 401) {
      localStorage.removeItem('koko_token');
      window.location.href = '/';
      return;
    }
    if (resp.status === 403) {
      const err = await resp.json().catch(() => ({}));
      if (err.detail === 'pending_approval') {
        window.location.href = '/';
        return;
      }
      throw new Error(err.detail || 'Forbidden');
    }
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || resp.statusText);
    }
    if (resp.status === 204) return null;
    return resp.json();
  },

  get(path)         { return this.request('GET',    path); },
  post(path, body)  { return this.request('POST',   path, body); },
  patch(path, body) { return this.request('PATCH',  path, body); },
  delete(path)      { return this.request('DELETE', path); },

  async upload(path, formData) {
    const resp = await fetch(this.base + path, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${this.token()}` },
      body: formData,
    });
    if (resp.status === 401) { window.location.href = '/'; return; }
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || resp.statusText);
    return resp.json();
  },
};

function requireAuth() {
  if (!API.token()) window.location.href = '/';
}

function logout() {
  localStorage.removeItem('koko_token');
  window.location.href = '/';
}

function showToast(msg, type) {
  let el = document.getElementById('_koko_toast');
  if (!el) {
    el = document.createElement('div');
    el.id = '_koko_toast';
    el.style.cssText = [
      'position:fixed', 'bottom:28px', 'left:50%', 'transform:translateX(-50%)',
      'padding:10px 22px', 'border-radius:12px', 'font-size:13.5px', 'font-weight:500',
      'z-index:9999', 'transition:opacity .3s', 'pointer-events:none',
      "font-family:'Inter',sans-serif", 'white-space:nowrap', 'box-shadow:0 4px 16px rgba(0,0,0,.18)',
    ].join(';');
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.style.background = type === 'error' ? '#ef4444' : '#1A1917';
  el.style.color = '#fff';
  el.style.opacity = '1';
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.style.opacity = '0'; }, 3200);
}

function fmtDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function fmtDatetime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const PRIORITY_BADGE = {
  urgent: '<span class="badge badge-urgent">urgent</span>',
  high:   '<span class="badge badge-high">high</span>',
  medium: '<span class="badge badge-medium">medium</span>',
  low:    '<span class="badge badge-low">low</span>',
};

const STATUS_ICON = {
  todo:        '⏳',
  in_progress: '🔄',
  done:        '✅',
  cancelled:   '❌',
};

// ── Command palette ───────────────────────────────────────
function initCommandPalette() {
  const NAV = [
    { label: 'Daily Tracker', icon: '📅', hint: 'Page', section: 'Navigate', action: () => location.href = '/dashboard' },
    { label: 'Tasks',         icon: '✅', hint: 'Page', section: 'Navigate', action: () => location.href = '/tasks'     },
    { label: 'Workout',       icon: '🏋️', hint: 'Page', section: 'Navigate', action: () => location.href = '/workout'   },
    { label: 'Documents',     icon: '📄', hint: 'Page', section: 'Navigate', action: () => location.href = '/documents' },
    { label: 'Profile',       icon: '👤', hint: 'Page', section: 'Navigate', action: () => location.href = '/profile'   },
    { label: 'Sign out',      icon: '←',  hint: '',     section: 'Account',  action: logout },
  ];

  function allCmds(q) {
    const extra = window._koko_cmds || [];
    const all   = [...extra, ...NAV];
    if (!q) return all;
    const lq = q.toLowerCase();
    return all.filter(c => c.label.toLowerCase().includes(lq) || (c.section||'').toLowerCase().includes(lq));
  }

  // Inject overlay HTML
  const el = document.createElement('div');
  el.className = 'cmd-overlay';
  el.id = 'cmd-palette';
  el.innerHTML = `
    <div class="cmd-panel">
      <div class="cmd-input-wrap">
        <span class="cmd-search-icon">⌘</span>
        <input class="cmd-input" id="cmd-input" placeholder="Type a command or search…" autocomplete="off" spellcheck="false" />
        <span class="cmd-esc-hint">esc</span>
      </div>
      <div class="cmd-results" id="cmd-results"></div>
      <div class="cmd-footer">
        <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
        <span><kbd>↵</kbd> select</span>
        <span><kbd>esc</kbd> close</span>
      </div>
    </div>`;
  document.body.appendChild(el);

  const overlay  = el;
  const inputEl  = document.getElementById('cmd-input');
  const resultsEl = document.getElementById('cmd-results');
  let items = [], activeIdx = 0;

  function render(q) {
    items = allCmds(q);
    activeIdx = 0;
    if (!items.length) {
      resultsEl.innerHTML = `<div class="cmd-empty">No results for "<strong>${q}</strong>"</div>`;
      return;
    }
    let html = '', lastSection = null;
    items.forEach((cmd, i) => {
      if (cmd.section !== lastSection) {
        html += `<div class="cmd-section-label">${cmd.section}</div>`;
        lastSection = cmd.section;
      }
      html += `<div class="cmd-item${i === 0 ? ' cmd-active' : ''}" data-i="${i}">
        <span class="cmd-item-icon">${cmd.icon}</span>
        <span class="cmd-item-label">${cmd.label}</span>
        <span class="cmd-item-hint">${cmd.hint || ''}</span>
      </div>`;
    });
    resultsEl.innerHTML = html;
    resultsEl.querySelectorAll('.cmd-item').forEach(row => {
      row.addEventListener('mouseenter', () => setActive(+row.dataset.i));
      row.addEventListener('click',      () => run(+row.dataset.i));
    });
  }

  function setActive(i) {
    activeIdx = Math.max(0, Math.min(items.length - 1, i));
    resultsEl.querySelectorAll('.cmd-item').forEach((r, j) =>
      r.classList.toggle('cmd-active', j === activeIdx));
    resultsEl.querySelector('.cmd-active')?.scrollIntoView({ block: 'nearest' });
  }

  function run(i) {
    items[i]?.action();
    close();
  }

  function open() {
    overlay.classList.add('cmd--open');
    inputEl.value = '';
    render('');
    requestAnimationFrame(() => inputEl.focus());
  }

  function close() {
    overlay.classList.remove('cmd--open');
  }

  inputEl.addEventListener('input',   () => render(inputEl.value.trim()));
  inputEl.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(activeIdx + 1); }
    if (e.key === 'ArrowUp')   { e.preventDefault(); setActive(activeIdx - 1); }
    if (e.key === 'Enter')     { e.preventDefault(); run(activeIdx); }
    if (e.key === 'Escape')    { close(); }
  });
  overlay.addEventListener('click', e => { if (e.target === overlay) close(); });

  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); overlay.classList.contains('cmd--open') ? close() : open(); }
    if (e.key === 'Escape' && overlay.classList.contains('cmd--open')) close();
  });

  // Inject ⌘K trigger into sidebar
  const signOutBtn = document.querySelector('.sidebar .nav-link.danger');
  if (signOutBtn) {
    const btn = document.createElement('button');
    btn.className = 'cmd-trigger';
    btn.innerHTML = '<span class="nav-icon">⌘K</span><span class="nav-label">Command palette</span>';
    btn.addEventListener('click', open);
    signOutBtn.parentElement.insertBefore(btn, signOutBtn);
  }
}

document.addEventListener('DOMContentLoaded', initCommandPalette);

// ── Collapsible sidebar ───────────────────────────────────
function initSidebar() {
  const sidebar = document.querySelector('.sidebar');
  const mark    = document.querySelector('.sidebar-logo-mark');
  if (!sidebar || !mark) return;

  if (localStorage.getItem('koko_sidebar') === 'collapsed')
    sidebar.classList.add('sidebar--collapsed');

  mark.addEventListener('click', () => {
    const isNowCollapsed = sidebar.classList.toggle('sidebar--collapsed');
    localStorage.setItem('koko_sidebar', isNowCollapsed ? 'collapsed' : 'open');
  });
}

document.addEventListener('DOMContentLoaded', initSidebar);

// ── apiFetch — convenience wrapper used by page scripts ───────────────────────
async function apiFetch(path, opts = {}) {
  const token = localStorage.getItem('koko_token');
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(path, { ...opts, headers });
  if (resp.status === 401) { localStorage.removeItem('koko_token'); window.location.href = '/'; return; }
  if (resp.status === 403) {
    const err = await resp.json().catch(() => ({}));
    if (err.detail === 'pending_approval') { window.location.href = '/'; return; }
    throw new Error(err.detail || 'Forbidden');
  }
  if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || resp.statusText); }
  if (resp.status === 204) return null;
  return resp.json();
}

// ── Admin nav injection ────────────────────────────────────────────────────────
async function initAdminNav() {
  const token = localStorage.getItem('koko_token');
  if (!token) return;
  try {
    const me = await apiFetch('/api/users/me');
    if (!me || !me.is_admin) return;
    const nav = document.querySelector('.sidebar nav');
    if (!nav) return;
    // Avoid duplicates
    if (nav.querySelector('[href="/users"]')) return;
    const a = document.createElement('a');
    a.href = '/users';
    a.className = 'nav-link' + (location.pathname === '/users' ? ' active' : '');
    a.innerHTML = '<span class="nav-icon">🛡️</span><span class="nav-label">Users</span>';
    nav.appendChild(a);
  } catch (_) {}
}

document.addEventListener('DOMContentLoaded', initAdminNav);
