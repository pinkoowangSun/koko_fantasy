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
    { label: 'Journal',       icon: '📓', hint: 'Page', section: 'Navigate', action: () => location.href = '/journal'   },
    { label: 'Health',        icon: '🏋️', hint: 'Page', section: 'Navigate', action: () => location.href = '/workout'   },
    { label: 'Finance',       icon: '💰', hint: 'Page', section: 'Navigate', action: () => location.href = '/finance'   },
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

// ── Dynamic sidebar nav with drag-to-reorder ──────────────────────────────────
const NAV_ITEMS = [
  { href: '/dashboard', icon: '📅', label: 'Daily Tracker' },
  { href: '/tasks',     icon: '✅', label: 'Tasks' },
  { href: '/journal',   icon: '📓', label: 'Journal' },
  { href: '/workout',   icon: '🏋️', label: 'Health' },
  { href: '/finance',   icon: '💰', label: 'Finance' },
  { href: '/documents', icon: '📄', label: 'Documents' },
  { href: '/profile',   icon: '👤', label: 'Profile' },
];

function getNavOrder() {
  try {
    const saved = JSON.parse(localStorage.getItem('koko_nav_order') || 'null');
    if (!Array.isArray(saved)) return NAV_ITEMS.map(n => n.href);
    const known   = new Set(NAV_ITEMS.map(n => n.href));
    const ordered = saved.filter(h => known.has(h));
    const missing = NAV_ITEMS.map(n => n.href).filter(h => !ordered.includes(h));
    return [...ordered, ...missing];
  } catch { return NAV_ITEMS.map(n => n.href); }
}

function initNavOrder() {
  const nav = document.querySelector('.sidebar nav');
  if (!nav) return;

  const byHref = Object.fromEntries(NAV_ITEMS.map(n => [n.href, n]));
  let order = getNavOrder();
  let dragSrc = null;

  function appendAdminLink() {
    if (!window._koko_is_admin) return;
    if (nav.querySelector('[href="/users"]')) return;
    const a = document.createElement('a');
    a.href = '/users';
    a.className = 'nav-link' + (location.pathname === '/users' ? ' active' : '');
    a.innerHTML = '<span class="nav-icon">🛡️</span><span class="nav-label">Users</span>';
    nav.appendChild(a);
  }

  function render() {
    nav.innerHTML = '';
    order.forEach((href, idx) => {
      const item = byHref[href];
      if (!item) return;
      const a = document.createElement('a');
      a.href = href;
      a.className = 'nav-link' + (location.pathname === href ? ' active' : '');
      a.innerHTML = `<span class="nav-icon">${item.icon}</span><span class="nav-label">${item.label}</span><span class="nav-drag-handle" title="Drag to reorder"><svg width="10" height="9" viewBox="0 0 10 9" fill="currentColor"><rect y="0" width="10" height="1.5" rx=".75"/><rect y="3.75" width="10" height="1.5" rx=".75"/><rect y="7.5" width="10" height="1.5" rx=".75"/></svg></span>`;
      a.draggable = true;
      a.dataset.navHref = href;

      a.addEventListener('dragstart', e => {
        dragSrc = idx;
        e.dataTransfer.effectAllowed = 'move';
        requestAnimationFrame(() => a.classList.add('nav-link--dragging'));
      });
      a.addEventListener('dragend', () => {
        a.classList.remove('nav-link--dragging');
        nav.querySelectorAll('.nav-link--drop-target').forEach(el => el.classList.remove('nav-link--drop-target'));
      });
      a.addEventListener('dragover', e => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        nav.querySelectorAll('.nav-link--drop-target').forEach(el => el.classList.remove('nav-link--drop-target'));
        a.classList.add('nav-link--drop-target');
      });
      a.addEventListener('dragleave', () => {
        a.classList.remove('nav-link--drop-target');
      });
      a.addEventListener('drop', e => {
        e.preventDefault();
        if (dragSrc === null || dragSrc === idx) return;
        const next = [...order];
        const [moved] = next.splice(dragSrc, 1);
        next.splice(idx, 0, moved);
        order = next;
        localStorage.setItem('koko_nav_order', JSON.stringify(order));
        render();
      });

      nav.appendChild(a);
    });
    appendAdminLink();
  }

  render();
}

document.addEventListener('DOMContentLoaded', initNavOrder);

// ── Admin nav injection ────────────────────────────────────────────────────────
async function initAdminNav() {
  const token = localStorage.getItem('koko_token');
  if (!token) return;
  try {
    const me = await apiFetch('/api/users/me');
    if (!me || !me.is_admin) return;
    window._koko_is_admin = true;
    const nav = document.querySelector('.sidebar nav');
    if (!nav) return;
    if (nav.querySelector('[href="/users"]')) return;
    const a = document.createElement('a');
    a.href = '/users';
    a.className = 'nav-link' + (location.pathname === '/users' ? ' active' : '');
    a.innerHTML = '<span class="nav-icon">🛡️</span><span class="nav-label">Users</span>';
    nav.appendChild(a);
  } catch (_) {}
}

document.addEventListener('DOMContentLoaded', initAdminNav);

// ── Floating chat bubble ──────────────────────────────────────────────────────
function initChatBubble() {
  const style = document.createElement('style');
  style.textContent = `
    #koko-bubble-btn {
      position: fixed; bottom: 28px; right: 28px; z-index: 9000;
      width: 52px; height: 52px; border-radius: 50%;
      background: #1A1917; color: #fff; border: none; cursor: pointer;
      font-size: 20px; display: flex; align-items: center; justify-content: center;
      box-shadow: 0 4px 20px rgba(0,0,0,.22); transition: transform .15s, background .15s;
    }
    #koko-bubble-btn:hover { background: #333228; transform: scale(1.08); }
    #koko-chat-panel {
      position: fixed; bottom: 92px; right: 28px; z-index: 9000;
      width: 360px; height: 520px; background: #fff;
      border: 1px solid #E8E7E3; border-radius: 16px;
      box-shadow: 0 8px 40px rgba(0,0,0,.14);
      display: flex; flex-direction: column; overflow: hidden;
      transform-origin: bottom right;
      transition: opacity .18s, transform .18s;
    }
    #koko-chat-panel.koko-hidden { opacity: 0; transform: scale(.92); pointer-events: none; }
    .koko-panel-header {
      padding: 14px 16px; border-bottom: 1px solid #E8E7E3;
      display: flex; align-items: center; justify-content: space-between;
      flex-shrink: 0;
    }
    .koko-panel-title { font-size: 14px; font-weight: 600; color: #1A1917; display: flex; align-items: center; gap: 7px; }
    .koko-panel-title span { color: #1A1917; font-size: 16px; }
    .koko-close-btn {
      background: none; border: none; cursor: pointer; color: #78776E;
      font-size: 18px; line-height: 1; padding: 2px 6px; border-radius: 6px;
    }
    .koko-close-btn:hover { background: #F0EFE9; color: #1A1917; }
    #koko-messages {
      flex: 1; overflow-y: auto; padding: 16px 14px;
      display: flex; flex-direction: column; gap: 10px;
    }
    .koko-msg { display: flex; flex-direction: column; max-width: 82%; }
    .koko-msg.koko-user { align-self: flex-end; align-items: flex-end; }
    .koko-msg.koko-bot  { align-self: flex-start; align-items: flex-start; }
    .koko-bubble {
      padding: 9px 13px; border-radius: 12px; font-size: 13.5px; line-height: 1.55;
      word-break: break-word;
    }
    .koko-msg.koko-user .koko-bubble { background: #1A1917; color: #fff; border-bottom-right-radius: 4px; }
    .koko-msg.koko-bot  .koko-bubble { background: #F6F5F2; color: #1A1917; border-bottom-left-radius: 4px; }
    .koko-bubble strong { font-weight: 600; }
    .koko-bubble ul { margin: 4px 0 0; padding-left: 16px; }
    .koko-bubble li { margin-bottom: 2px; }
    .koko-typing { display: flex; align-items: center; gap: 4px; padding: 10px 13px; }
    .koko-dot { width: 7px; height: 7px; border-radius: 50%; background: #ABAAA5; animation: kokoPulse 1.2s infinite ease-in-out; }
    .koko-dot:nth-child(2) { animation-delay: .2s; }
    .koko-dot:nth-child(3) { animation-delay: .4s; }
    @keyframes kokoPulse { 0%,80%,100% { transform: scale(.7); opacity:.5 } 40% { transform: scale(1); opacity:1 } }
    .koko-input-row {
      padding: 10px 12px; border-top: 1px solid #E8E7E3;
      display: flex; gap: 8px; align-items: flex-end; flex-shrink: 0;
    }
    #koko-input {
      flex: 1; resize: none; border: 1px solid #D6D5D0; border-radius: 10px;
      padding: 8px 11px; font-size: 13.5px; font-family: 'Inter', sans-serif;
      line-height: 1.4; outline: none; max-height: 100px; overflow-y: auto;
      background: #F6F5F2; color: #1A1917;
    }
    #koko-input:focus { border-color: #1A1917; background: #fff; }
    #koko-send-btn {
      width: 36px; height: 36px; border-radius: 9px; flex-shrink: 0;
      background: #1A1917; color: #fff; border: none; cursor: pointer;
      font-size: 15px; display: flex; align-items: center; justify-content: center;
      transition: background .15s;
    }
    #koko-send-btn:hover:not(:disabled) { background: #333228; }
    #koko-send-btn:disabled { opacity: .4; cursor: not-allowed; }
  `;
  document.head.appendChild(style);

  const btn = document.createElement('button');
  btn.id = 'koko-bubble-btn';
  btn.title = 'Chat with Koko';
  btn.innerHTML = '✦';

  const panel = document.createElement('div');
  panel.id = 'koko-chat-panel';
  panel.className = 'koko-hidden';
  panel.innerHTML = `
    <div class="koko-panel-header">
      <div class="koko-panel-title"><span>✦</span> Koko</div>
      <button class="koko-close-btn" id="koko-close-btn" title="Close">✕</button>
    </div>
    <div id="koko-messages"></div>
    <div class="koko-input-row">
      <textarea id="koko-input" rows="1" placeholder="Ask Koko anything…"></textarea>
      <button id="koko-send-btn" title="Send">↑</button>
    </div>
  `;

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  const messagesEl = document.getElementById('koko-messages');
  const inputEl    = document.getElementById('koko-input');
  const sendBtn    = document.getElementById('koko-send-btn');

  let isOpen = false, isLoading = false;

  function mdToHtml(text) {
    const escaped = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    let html = escaped
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>');
    const lines = html.split('\n');
    const out = []; let inList = false;
    lines.forEach(line => {
      const li = line.match(/^[-•]\s+(.*)/);
      if (li) {
        if (!inList) { out.push('<ul>'); inList = true; }
        out.push(`<li>${li[1]}</li>`);
      } else {
        if (inList) { out.push('</ul>'); inList = false; }
        out.push(line === '' ? '<br>' : `<span>${line}</span><br>`);
      }
    });
    if (inList) out.push('</ul>');
    return out.join('');
  }

  function addMessage(role, text) {
    const wrap = document.createElement('div');
    wrap.className = `koko-msg koko-${role}`;
    const bubble = document.createElement('div');
    bubble.className = 'koko-bubble';
    bubble.innerHTML = role === 'bot' ? mdToHtml(text) : text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    wrap.appendChild(bubble);
    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return wrap;
  }

  function showTyping() {
    const wrap = document.createElement('div');
    wrap.className = 'koko-msg koko-bot';
    wrap.id = 'koko-typing';
    wrap.innerHTML = '<div class="koko-typing"><div class="koko-dot"></div><div class="koko-dot"></div><div class="koko-dot"></div></div>';
    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function removeTyping() {
    document.getElementById('koko-typing')?.remove();
  }

  async function send() {
    const text = inputEl.value.trim();
    if (!text || isLoading) return;
    isLoading = true;
    sendBtn.disabled = true;
    inputEl.value = '';
    inputEl.style.height = 'auto';

    addMessage('user', text);
    showTyping();

    try {
      const data = await API.post('/chat/message', { message: text });
      removeTyping();
      addMessage('bot', data.response || 'No response.');
    } catch (err) {
      removeTyping();
      addMessage('bot', `Sorry, something went wrong: ${err.message}`);
    } finally {
      isLoading = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  function open() {
    isOpen = true;
    panel.classList.remove('koko-hidden');
    inputEl.focus();
    if (!messagesEl.children.length) {
      addMessage('bot', 'Hi! I\'m Koko. You can ask me to add tasks, log workouts, check your finances, look up stock prices, weather, and more.');
    }
  }

  function close() {
    isOpen = false;
    panel.classList.add('koko-hidden');
  }

  btn.addEventListener('click', () => isOpen ? close() : open());
  document.getElementById('koko-close-btn').addEventListener('click', close);

  inputEl.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 100) + 'px';
  });
  sendBtn.addEventListener('click', send);

  window._kokoChat = { open, close, toggle: () => isOpen ? close() : open() };
}

document.addEventListener('DOMContentLoaded', initChatBubble);
