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
