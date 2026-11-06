/* ArthSetu SPA — dependency-free. All dynamic text is inserted with textContent (no innerHTML on data). */
(() => {
'use strict';
const S = { user: null, lang: 'en', theme: document.documentElement.dataset.theme || 'light', feat: null, model: null,
  chat: { open: false, sid: null, msgs: [], busy: false, loaded: false }, ctx: { page: 'landing', band: null, factors: [] } };
try { S.lang = localStorage.getItem('lang') === 'hi' ? 'hi' : 'en'; } catch (e) {}

// ---------- helpers
const t = (k, v) => { let s = (I18N[S.lang][k] ?? I18N.en[k] ?? k); if (typeof s === 'string' && v) for (const [a, b] of Object.entries(v)) s = s.replaceAll('{' + a + '}', b); return s; };
const loc = () => (S.lang === 'hi' ? 'hi-IN' : 'en-IN');
const nf = (n, o) => new Intl.NumberFormat(loc(), o).format(n);
const pct = (p, d = 1) => nf(p * 100, { minimumFractionDigits: d, maximumFractionDigits: d }) + '%';
const pp = c => (c >= 0 ? '+' : '−') + nf(Math.abs(c) * 100, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fdate = iso => iso ? new Intl.DateTimeFormat(loc(), { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso)) : '—';
function el(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(Infinity)) { if (c == null || c === false) continue; e.append(c.nodeType ? c : document.createTextNode(String(c))); }
  return e;
}
const $ = (s, r = document) => r.querySelector(s);
const fl = k => (S.feat && S.feat[k] ? S.feat[k][S.lang].label : k);
const nav = h => { if (location.hash === h) render(); else location.hash = h; };
const logoSvg = () => { const d = document.createElement('span'); d.innerHTML = '<svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#0f766e"/><path d="M6 21c4-9 8-9 10-4s6 4 10-5" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/></svg>'; return d.firstChild; };

async function api(path, { method = 'GET', body } = {}) {
  let r;
  try {
    r = await fetch(path, { method, credentials: 'same-origin', headers: { 'X-Requested-With': 'ArthSetu', ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined });
  } catch (e) { throw { status: 0, code: 'network', details: [] }; }
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    const e = (data && data.error) || {};
    const err = { status: r.status, code: e.code || 'generic', details: e.details || [] };
    if (r.status === 401 && S.user && !path.startsWith('/api/auth/')) { S.user = null; resetChat(); nav('#/login?expired=1'); }
    throw err;
  }
  return data;
}
const errMsg = e => { const k = 'e.' + (e && e.code); return t(k) !== k ? t(k) : t('e.generic'); };
const alertBox = (msg, kind = 'bad') => el('div', { class: 'alert ' + kind, role: kind === 'bad' ? 'alert' : 'status' }, msg);

// ---------- theme / language
function applyTheme(th, persist = true) {
  S.theme = th; document.documentElement.dataset.theme = th;
  try { localStorage.setItem('theme', th); } catch (e) {}
  if (persist && S.user) api('/api/me/preferences', { method: 'PATCH', body: { theme: th } }).catch(() => {});
}
function applyLang(l, persist = true) {
  S.lang = l; document.documentElement.lang = l;
  try { localStorage.setItem('lang', l); } catch (e) {}
  if (persist && S.user) api('/api/me/preferences', { method: 'PATCH', body: { language: l } }).catch(() => {});
  render(); renderChat();
}

// ---------- shell
function topbar() {
  const link = (h, k, name) => el('a', { href: h, class: (parseHash().name === name ? 'on' : '') }, t(k));
  const langSel = el('select', { 'aria-label': t('lang.label'), onchange: e => applyLang(e.target.value) },
    el('option', { value: 'en', selected: S.lang === 'en' }, 'English'), el('option', { value: 'hi', selected: S.lang === 'hi' }, 'हिंदी'));
  const nav_ = S.user
    ? [link('#/dashboard', 'nav.dashboard', 'dashboard'), link('#/assess', 'nav.assess', 'assess'), link('#/history', 'nav.history', 'history'), link('#/model', 'nav.model', 'model'),
       S.user.role === 'ADMIN' && link('#/admin', 'nav.admin', 'admin'), link('#/settings', 'nav.settings', 'settings')]
    : [link('#/', 'nav.home', '')];
  return el('header', { class: 'topbar' }, el('div', { class: 'in' },
    el('a', { href: S.user ? '#/dashboard' : '#/', class: 'brand' }, logoSvg(), 'ArthSetu'),
    el('nav', { class: 'nav', 'aria-label': 'Main' }, nav_),
    el('div', { class: 'tools' }, langSel,
      el('button', { class: 'icon', id: 'theme-btn', title: t('theme.toggle'), 'aria-label': t('theme.toggle'), onclick: () => applyTheme(S.theme === 'dark' ? 'light' : 'dark') }, S.theme === 'dark' ? '☀' : '☾'),
      S.user ? el('button', { id: 'logout-btn', onclick: logout }, t('nav.logout'))
             : [el('a', { class: 'btn', href: '#/login' }, t('nav.login')), el('a', { class: 'btn primary', href: '#/signup' }, t('nav.signup'))])));
}
async function logout() {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch (e) {}
  S.user = null; resetChat(); nav('#/');
}

// ---------- router
function parseHash() {
  const [path, qs] = (location.hash.slice(1) || '/').split('?');
  const parts = path.split('/').filter(Boolean);
  return { name: parts[0] || '', arg: parts[1], q: new URLSearchParams(qs || '') };
}
const PAGES = {};
let renderToken = 0;
async function render() {
  const r = parseHash(), my = ++renderToken;
  const pub = ['', 'login', 'signup'];
  if (!S.user && !pub.includes(r.name)) return nav('#/login');
  if (S.user && (r.name === 'login' || r.name === 'signup')) return nav('#/dashboard');
  const app = $('#app');
  const main = el('main', { id: 'main', tabindex: '-1' }, el('p', { class: 'muted' }, t('common.loading')));
  app.replaceChildren(topbar(), main, el('footer', {}, t('disc')));
  S.ctx = { page: r.name === '' ? 'landing' : (['dashboard', 'assess', 'result', 'history', 'model', 'settings', 'admin'].includes(r.name) ? r.name : 'dashboard'), band: null, factors: [] };
  const fn = PAGES[r.name] || PAGES[''];
  try {
    if (r.name === 'admin' && S.user.role !== 'ADMIN') { main.replaceChildren(alertBox(t('e.forbidden'))); }
    else {
      if (S.user && !S.feat) S.feat = await fetch('/api/features').then(x => x.json()).catch(() => null);
      const node = await fn(r);
      if (my !== renderToken) return;
      main.replaceChildren(node);
    }
  } catch (e) { if (my === renderToken) main.replaceChildren(alertBox(errMsg(e)), el('button', { onclick: render }, t('common.retry'))); }
  document.title = 'ArthSetu';
  renderChat();
}
window.addEventListener('hashchange', render);

// ---------- landing
PAGES[''] = async () => {
  const card = (k) => el('div', { class: 'card' }, el('h3', {}, t(k + '.t')), el('p', { class: 'muted' }, t(k + '.d')));
  return el('div', {},
    el('section', { class: 'hero' }, el('h1', {}, t('land.title')), el('p', {}, t('land.sub')),
      el('div', { class: 'row' }, el('a', { class: 'btn primary', href: '#/signup' }, t('land.start')), el('a', { class: 'btn', href: '#/login' }, t('land.have')))),
    el('div', { class: 'grid g3 mb' }, card('land.c1'), card('land.c2'), card('land.c3')),
    el('div', { class: 'grid g2 mb' }, card('land.alt'), card('land.honest')),
    el('p', { class: 'disclaimer' }, t('disc')));
};

// ---------- auth
function authPage(mode) {
  return async r => {
    const signup = mode === 'signup';
    const errs = {}; const box = el('div'); const form = el('form', { novalidate: true });
    const inputs = {};
    const field = (k, label, type, extra = {}) => {
      const i = el('input', { id: 'f-' + k, name: k, type, autocomplete: extra.ac, required: true, maxlength: extra.max, 'aria-describedby': 'e-' + k }); inputs[k] = i;
      errs[k] = el('div', { class: 'err', id: 'e-' + k });
      return el('div', { class: 'field' }, el('label', { for: 'f-' + k }, label), i, extra.hint && el('div', { class: 'hint' }, extra.hint), errs[k]);
    };
    form.append(signup && field('full_name', t('auth.name'), 'text', { ac: 'name', max: 100 }), field('email', t('auth.email'), 'email', { ac: 'email', max: 254 }),
      field('password', t('auth.password'), 'password', { ac: signup ? 'new-password' : 'current-password', max: 128, hint: signup ? t('auth.pwhint') : null }));
    const btn = el('button', { class: 'primary', type: 'submit', style: 'width:100%' }, signup ? t('nav.signup') : t('nav.login'));
    form.append(btn);
    form.addEventListener('submit', async ev => {
      ev.preventDefault(); box.replaceChildren(); Object.values(errs).forEach(e => e.replaceChildren());
      let bad = false;
      for (const k of Object.keys(inputs)) if (!inputs[k].value.trim()) { errs[k].textContent = t('v.required'); bad = true; }
      if (bad) return;
      btn.disabled = true; btn.textContent = t('auth.signing');
      try {
        const body = { email: inputs.email.value.trim(), password: inputs.password.value };
        if (signup) body.full_name = inputs.full_name.value.trim();
        const res = await api(signup ? '/api/auth/signup' : '/api/auth/login', { method: 'POST', body });
        S.user = res.user; applyPrefs(res.user.preferences); nav('#/dashboard');
      } catch (e) {
        box.replaceChildren(alertBox(errMsg(e)));
        (e.details || []).forEach(d => { if (errs[d.field]) errs[d.field].textContent = d.message; });
        btn.disabled = false; btn.textContent = signup ? t('nav.signup') : t('nav.login');
      }
    });
    return el('div', { class: 'center' }, el('div', { class: 'card' }, el('h2', {}, signup ? t('auth.signup.t') : t('auth.login.t')),
      r.q.get('expired') && alertBox(t('e.session_expired'), 'info'), box, form,
      el('p', { class: 'mt muted' }, signup ? t('auth.haveacct') : t('auth.noacct'), ' ', el('a', { href: signup ? '#/login' : '#/signup' }, signup ? t('nav.login') : t('nav.signup')))));
  };
}
PAGES.login = authPage('login'); PAGES.signup = authPage('signup');
function applyPrefs(p) {
  if (!p) return;
  if (p.theme && p.theme !== S.theme) applyTheme(p.theme, false);
  if (p.language && p.language !== S.lang) { S.lang = p.language; document.documentElement.lang = p.language; try { localStorage.setItem('lang', p.language); } catch (e) {} }
}

// ---------- shared UI
const badge = b => el('span', { class: 'badge b-' + b }, t('band.' + b));
function table(cols, rows, onclick) {
  return el('div', { class: 'scroll' }, el('table', {}, el('thead', {}, el('tr', {}, cols.map(c => el('th', {}, c)))),
    el('tbody', {}, rows.map(r => el('tr', onclick ? { class: 'click', tabindex: '0', onclick: () => onclick(r), onkeydown: e => { if (e.key === 'Enter') onclick(r); } } : {}, r.cells.map(c => el('td', {}, c)))))));
}
const stat = (v, k) => el('div', { class: 'card stat' }, el('div', { class: 'v' }, v), el('div', { class: 'k' }, k));
function barChart(items) {
  if (!items.length) return el('p', { class: 'muted' }, t('a.nodata'));
  const max = Math.max(...items.map(i => i.n), 1);
  return el('div', { class: 'bars', role: 'img' }, items.map(i => el('div', { style: `height:${Math.max(3, (i.n / max) * 100)}%`, title: `${i.day}: ${i.n}` }, el('span', {}, i.n))));
}

// ---------- dashboard
PAGES.dashboard = async () => {
  const d = await api('/api/dashboard');
  const bc = d.band_counts || {};
  const rows = d.recent.map(a => ({ id: a.id, cells: [a.label || '#' + a.id, fdate(a.created_at), pct(a.probability), badge(a.risk_band)] }));
  return el('div', {},
    el('h1', {}, t('dash.welcome', { name: S.user.full_name })), el('p', { class: 'muted' }, t('dash.sub')),
    el('div', { class: 'grid g4 mb' }, stat(nf(d.total_assessments), t('dash.total')), stat(nf(bc.LOW || 0), t('dash.low')), stat(nf(bc.MODERATE || 0), t('dash.mod')), stat(nf(bc.HIGH || 0), t('dash.high'))),
    el('div', { class: 'grid g2' },
      el('div', { class: 'card' }, el('div', { class: 'row between' }, el('h2', {}, t('dash.recent')), el('a', { class: 'btn primary', href: '#/assess' }, t('dash.new'))),
        rows.length ? table([t('h.c.label'), t('h.c.date'), t('h.c.prob'), t('h.c.band')], rows, r => nav('#/result/' + r.id)) : el('p', { class: 'muted' }, t('dash.none'))),
      el('div', { class: 'grid', style: 'align-content:start' },
        el('div', { class: 'card' }, el('h2', {}, t('dash.activity')), d.activity.length ? el('ul', {}, d.activity.map(a => el('li', {}, fdate(a.ts), ' — ', a.action, ' ', el('span', { class: 'badge b-' + a.outcome }, a.outcome)))) : el('p', { class: 'muted' }, t('common.none'))),
        el('div', { class: 'card' }, el('h2', {}, t('dash.info')), el('p', { class: 'muted' }, t('dash.info.d')), d.model_version && el('small', {}, t('r.model'), ': ', d.model_version)))));
};

// ---------- assessment form
const FIELDS = [
  { sec: 'sec.credit', items: [{ k: 'revolving_utilization', step: '0.01', min: 0, max: 50 }, { k: 'debt_ratio', step: '0.01', min: 0, max: 1000 }, { k: 'monthly_income', step: '1', min: 0, max: 1e7, opt: 1 }, { k: 'open_credit_lines', int: 1, min: 0, max: 60 }, { k: 'real_estate_loans', int: 1, min: 0, max: 60 }] },
  { sec: 'sec.history', items: [{ k: 'past_due_30_59', int: 1, min: 0, max: 30 }, { k: 'past_due_60_89', int: 1, min: 0, max: 30 }, { k: 'past_due_90_plus', int: 1, min: 0, max: 30 }] },
  { sec: 'sec.person', items: [{ k: 'age', int: 1, min: 18, max: 110 }, { k: 'dependents', int: 1, min: 0, max: 20, opt: 1 }] }];
PAGES.assess = async () => {
  const inputs = {}, errs = {}, box = el('div');
  const label = el('input', { id: 'f-label', maxlength: '80', placeholder: t('as.label.ph') });
  const form = el('form', { novalidate: true, id: 'assess-form' });
  form.append(el('div', { class: 'card mb' }, el('div', { class: 'field' }, el('label', { for: 'f-label' }, t('as.label'), ' ', el('small', {}, '(' + t('as.opt') + ')')), label)));
  for (const sec of FIELDS) {
    const body = el('div', { class: 'grid g2' });
    for (const f of sec.items) {
      const i = el('input', { id: 'f-' + f.k, name: f.k, type: 'number', inputmode: f.int ? 'numeric' : 'decimal', step: f.step || '1', min: f.min, max: f.max, 'aria-describedby': 'e-' + f.k + ' h-' + f.k }); inputs[f.k] = i;
      errs[f.k] = el('div', { class: 'err', id: 'e-' + f.k });
      body.append(el('div', { class: 'field' }, el('label', { for: 'f-' + f.k }, t('f.' + f.k), f.opt && el('small', { class: 'muted' }, ' (' + t('as.opt') + ')'),
        el('span', { class: 'tip', tabindex: '0', role: 'img', 'aria-label': t('d.' + f.k), 'data-tip': t('d.' + f.k) }, 'i')), i, el('div', { class: 'hint', id: 'h-' + f.k }, t('d.' + f.k)), errs[f.k]));
    }
    form.append(el('div', { class: 'card mb' }, el('h3', {}, t(sec.sec)), body));
  }
  const btn = el('button', { class: 'primary', type: 'submit', id: 'assess-submit' }, t('as.submit'));
  form.append(btn);
  form.addEventListener('submit', async ev => {
    ev.preventDefault(); box.replaceChildren(); Object.values(errs).forEach(e => e.replaceChildren());
    const body = { label: label.value.trim() }; let bad = false;
    for (const sec of FIELDS) for (const f of sec.items) {
      const raw = inputs[f.k].value.trim();
      if (raw === '') { if (f.opt) body[f.k] = null; else { errs[f.k].textContent = t('v.required'); bad = true; } continue; }
      const n = Number(raw);
      if (!Number.isFinite(n)) { errs[f.k].textContent = t('v.number'); bad = true; }
      else if (f.int && !Number.isInteger(n)) { errs[f.k].textContent = t('v.integer'); bad = true; }
      else if (n < f.min || n > f.max) { errs[f.k].textContent = t('v.range', { min: nf(f.min), max: nf(f.max) }); bad = true; }
      else body[f.k] = n;
    }
    if (bad) { box.replaceChildren(alertBox(t('e.validation_error'))); (form.querySelector('.err:not(:empty)') || form).scrollIntoView?.({ block: 'center' }); return; }
    btn.disabled = true; btn.textContent = t('as.running');
    try { const res = await api('/api/assessments', { method: 'POST', body }); nav('#/result/' + res.id); }
    catch (e) {
      box.replaceChildren(alertBox(errMsg(e)));
      (e.details || []).forEach(d => { if (errs[d.field]) errs[d.field].textContent = d.message; });
      btn.disabled = false; btn.textContent = t('as.submit');
    }
  });
  return el('div', {}, el('h1', {}, t('as.title')), el('p', { class: 'muted' }, t('as.sub')), box, form, el('p', { class: 'disclaimer mt' }, t('disc')));
};

// ---------- result
async function getModel() { if (!S.model) S.model = await api('/api/model'); return S.model; }
function fmtVal(f, v) {
  if (v === null || v === undefined) return t('r.skip');
  if (['income_reported', 'has_90plus_delinquency', 'utilization_over_limit'].includes(f)) return v ? (S.lang === 'hi' ? 'हाँ' : 'Yes') : (S.lang === 'hi' ? 'नहीं' : 'No');
  return nf(v, { maximumFractionDigits: 2 });
}
function meter(p, bands) {
  const max = Math.min(1, Math.max(0.5, p * 1.25, bands.high_min * 1.6)), w = x => Math.min(100, (x / max) * 100);
  const seg = (a, b, cls) => el('i', { style: `width:${w(b) - w(a)}%;background:var(--${cls})`, title: pct(a) + ' – ' + pct(b) });
  return el('div', { class: 'meter-wrap', role: 'img', 'aria-label': pct(p) },
    el('div', { class: 'pin', style: `left:${w(p)}%` }, pct(p)),
    el('div', { class: 'meter' }, seg(0, bands.low_max, 'down'), seg(bands.low_max, bands.high_min, 'warn'), seg(bands.high_min, max, 'up')),
    el('div', { class: 'row between' }, el('small', {}, '0%'), el('small', {}, pct(bands.low_max, 0)), el('small', {}, pct(bands.high_min, 0)), el('small', {}, pct(max, 0))));
}
function explainRows(ex, showAll) {
  const rows = showAll ? ex.contributions : ex.contributions.slice(0, 8);
  const max = Math.max(...ex.contributions.map(c => Math.abs(c.contribution)), 1e-9);
  const out = rows.map(c => {
    const up = c.contribution >= 0, w = Math.max(1, (Math.abs(c.contribution) / max) * 100);
    const bar = el('div', { class: 'xbar' },
      el('div', { class: 'l' }, !up && [el('span', { class: 'xnum down' }, pp(c.contribution)), el('b', { class: 'down', style: `width:${w}%` })]),
      el('div', { class: 'r' }, up && [el('b', { class: 'up', style: `width:${w}%` }), el('span', { class: 'xnum up' }, pp(c.contribution))]));
    return el('div', { class: 'xrow', title: fl(c.feature) + ' ' + t(up ? 'r.raised' : 'r.lowered', { x: nf(Math.abs(c.contribution) * 100, { maximumFractionDigits: 1 }) }) },
      el('div', { class: 'xlab' }, el('b', {}, fl(c.feature)), el('small', { class: 'muted' }, fmtVal(c.feature, c.value), ' · ', t('r.se', { x: nf(c.std_error * 100, { maximumFractionDigits: 2 }) }))), bar);
  });
  return out;
}
PAGES.result = async r => {
  const [a, m] = await Promise.all([api('/api/assessments/' + encodeURIComponent(r.arg)), getModel()]);
  const ex = a.explanation, bands = m.risk_bands;
  S.ctx = { page: 'result', band: a.risk_band, factors: ex.contributions.slice(0, 3).map(c => c.feature) };
  let showAll = false; const exBox = el('div', { id: 'ex-rows' });
  const toggle = el('button', { onclick: () => { showAll = !showAll; draw(); } }, t('r.showall'));
  const draw = () => { exBox.replaceChildren(...explainRows(ex, showAll)); toggle.textContent = showAll ? t('r.showtop') : t('r.showall'); };
  draw();
  const dl = (k, v) => el('div', {}, el('small', { class: 'muted' }, k), el('div', {}, v));
  const inputsRows = Object.entries(a.inputs).map(([k, v]) => ({ cells: [t('f.' + k), v === null ? t('r.skip') : nf(v, { maximumFractionDigits: 4 })] }));
  return el('div', {},
    el('div', { class: 'row between mb' }, el('h1', { style: 'margin:0' }, t('r.title')), el('div', { class: 'row' }, el('a', { class: 'btn', href: '#/history' }, t('nav.history')), el('a', { class: 'btn primary', href: '#/assess' }, t('r.again')))),
    el('div', { class: 'grid g2 mb' },
      el('div', { class: 'card' }, el('small', { class: 'muted' }, t('r.prob')), el('div', { class: 'bigp', id: 'prob' }, pct(a.probability)), el('p', { class: 'muted' }, t('r.prob.d')),
        el('div', { class: 'row' }, el('small', { class: 'muted' }, t('r.band')), el('span', { id: 'band' }, badge(a.risk_band))), el('p', {}, t('band.' + a.risk_band + '.d')), meter(a.probability, bands)),
      el('div', { class: 'card grid', style: 'align-content:start' }, dl(t('r.ref'), a.label || '#' + a.id), dl(t('r.time'), fdate(a.created_at)), dl(t('r.model'), a.model_version), dl(t('r.threshold'), pct(a.threshold)))),
    el('div', { class: 'card mb' }, el('h2', {}, t('r.ex.t')), el('p', { class: 'muted' }, t('r.ex.d', { base: pct(ex.base_value) })), exBox, el('div', { class: 'row mt' }, toggle, el('button', { id: 'ask-btn', onclick: () => openChat(true) }, t('r.ask'))),
      el('p', { class: 'muted mt' }, t('r.caus'))),
    el('details', { class: 'card mb' }, el('summary', {}, t('r.inputs')), table(['', ''], inputsRows)),
    el('p', { class: 'disclaimer' }, t('disc')));
};

// ---------- history
PAGES.history = async () => {
  const st = { q: '', band: '', page: 1 }; const wrap = el('div'), list = el('div');
  let timer;
  const q = el('input', { type: 'search', placeholder: t('h.search'), 'aria-label': t('h.search'), oninput: e => { clearTimeout(timer); timer = setTimeout(() => { st.q = e.target.value; st.page = 1; load(); }, 250); } });
  const sel = el('select', { 'aria-label': t('h.all'), onchange: e => { st.band = e.target.value; st.page = 1; load(); } }, el('option', { value: '' }, t('h.all')), ['LOW', 'MODERATE', 'HIGH'].map(b => el('option', { value: b }, t('band.' + b))));
  async function load() {
    try {
      const d = await api(`/api/assessments?page=${st.page}&page_size=10&q=${encodeURIComponent(st.q)}&band=${st.band}`);
      const pages = Math.max(1, Math.ceil(d.total / d.page_size));
      list.replaceChildren(d.items.length ? table([t('h.c.label'), t('h.c.date'), t('h.c.prob'), t('h.c.band'), t('h.c.model')],
        d.items.map(a => ({ id: a.id, cells: [a.label || '#' + a.id, fdate(a.created_at), pct(a.probability), badge(a.risk_band), a.model_version.slice(-14)] })), r => nav('#/result/' + r.id)) : el('p', { class: 'muted' }, t('h.empty')),
        el('div', { class: 'row between mt' }, el('button', { disabled: st.page <= 1, onclick: () => { st.page--; load(); } }, t('h.prev')), el('span', { class: 'muted' }, t('h.page', { p: nf(d.page), n: nf(pages) })),
          el('button', { disabled: st.page >= pages, onclick: () => { st.page++; load(); } }, t('h.next'))));
    } catch (e) { list.replaceChildren(alertBox(errMsg(e))); }
  }
  await load();
  return el('div', {}, el('div', { class: 'row between mb' }, el('h1', { style: 'margin:0' }, t('h.title')), el('a', { class: 'btn', href: '/api/assessments/export.csv', download: 'arthsetu_assessments.csv' }, t('h.export'))),
    el('div', { class: 'card' }, el('div', { class: 'row mb' }, el('div', { style: 'flex:1;min-width:200px' }, q), sel), list));
};

// ---------- model info
PAGES.model = async () => {
  const m = await getModel(); const T = m.test;
  const mets = ['roc_auc', 'pr_auc', 'precision', 'recall', 'f1', 'accuracy', 'specificity', 'false_positive_rate', 'false_negative_rate', 'brier'];
  const val = (k, v) => ['roc_auc', 'pr_auc', 'f1', 'brier'].includes(k) ? nf(v, { minimumFractionDigits: 3, maximumFractionDigits: 4 }) : pct(v);
  const cm = T.confusion_matrix, maxI = Math.max(...m.global_importance.map(i => i.mean_abs), 1e-9);
  return el('div', {}, el('h1', {}, t('m.title')), el('p', { class: 'muted' }, t('m.sub')),
    el('div', { class: 'card mb grid g2' }, [[t('m.algo'), m.algorithm.replaceAll('_', ' ') + ' · ' + (m.resampling)], [t('r.model'), m.model_version], [t('m.dataset'), m.dataset_version], [t('m.trained'), fdate(m.trained_utc)], [t('m.split'), m.split_policy], ['XGBoost / imblearn', m.xgboost_smote_status]]
      .map(([k, v]) => el('div', {}, el('small', { class: 'muted' }, k), el('div', {}, v)))),
    el('div', { class: 'card mb' }, el('h2', {}, t('m.test')), el('p', { class: 'muted' }, `${t('m.n')}: ${nf(T.n)} · ${t('m.defaults')}: ${nf(T.positives)} · ${t('r.threshold')}: ${pct(T.threshold)}`),
      el('div', { class: 'grid g4' }, mets.map(k => stat(val(k, T[k]), t('met.' + k)))), alertBox(t('m.warn'), 'warn'),
      el('h3', { class: 'mt' }, t('met.cm')), table(['', 'Pred: no default', 'Pred: default'], [{ cells: ['Actual: no default', nf(cm.tn), nf(cm.fp)] }, { cells: ['Actual: default', nf(cm.fn), nf(cm.tp)] }])),
    el('div', { class: 'card mb' }, el('h2', {}, t('m.cv')), table([t('m.cand'), 'ROC-AUC', 'PR-AUC'], Object.entries(m.cv_5fold_train_oof).map(([k, v]) => ({ cells: [k.replaceAll('_', ' ') + (k === m.algorithm ? ' ✓' : ''), nf(v.oof_roc_auc, { minimumFractionDigits: 3, maximumFractionDigits: 3 }), nf(v.oof_pr_auc, { minimumFractionDigits: 3, maximumFractionDigits: 3 })] })))),
    el('div', { class: 'card mb' }, el('h2', {}, t('m.imp')), el('p', { class: 'muted' }, t('m.imp.d')),
      m.global_importance.slice(0, 10).map(i => el('div', { class: 'xrow' }, el('b', {}, fl(i.feature)), el('div', { class: 'row' }, el('div', { style: `height:12px;border-radius:4px;background:var(--accent);width:${Math.max(2, (i.mean_abs / maxI) * 75)}%` }), el('small', {}, nf(i.mean_abs * 100, { maximumFractionDigits: 2 }) + ' pp'))))),
    el('div', { class: 'card mb' }, el('h2', {}, t('m.rel')), el('p', { class: 'muted' }, t('m.rel.d')), table(['Predicted', 'Observed', 'n'], m.reliability_test_deciles.map(d => ({ cells: [pct(d.mean_predicted, 2), pct(d.observed_rate, 2), nf(d.n)] })))),
    el('div', { class: 'card' }, el('h2', {}, t('m.lim')), el('ul', {}, m.limitations.map(l => el('li', {}, l)))));
};

// ---------- settings
PAGES.settings = async () => {
  const u = S.user;
  return el('div', {}, el('h1', {}, t('s.title')), el('div', { class: 'grid g2' },
    el('div', { class: 'card' }, el('h2', {}, t('s.appearance')), el('div', { class: 'field' }, el('label', {}, t('s.theme')), el('div', { class: 'row' },
      ['light', 'dark'].map(th => el('button', { class: S.theme === th ? 'primary' : '', id: 'theme-' + th, onclick: () => { applyTheme(th); render(); } }, t('s.' + th))))),
      el('div', { class: 'field' }, el('label', { for: 'lang-sel' }, t('s.language')), el('select', { id: 'lang-sel', onchange: e => applyLang(e.target.value) }, el('option', { value: 'en', selected: S.lang === 'en' }, 'English'), el('option', { value: 'hi', selected: S.lang === 'hi' }, 'हिंदी')))),
    el('div', { class: 'card' }, el('h2', {}, t('s.account')), el('p', {}, el('b', {}, u.full_name), el('br'), u.email), el('p', {}, t('s.role'), ': ', el('span', { class: 'badge b-' + u.role }, u.role)), el('p', { class: 'muted' }, t('s.since'), ': ', fdate(u.created_at)))));
};

// ---------- admin
PAGES.admin = async () => {
  let tab = 'overview'; const body = el('div'); const tabs = el('div', { class: 'tabs', role: 'tablist' });
  const names = [['overview', 'a.overview'], ['users', 'a.users'], ['audit', 'a.audit'], ['predictions', 'a.pred'], ['system', 'a.system']];
  const drawTabs = () => tabs.replaceChildren(...names.map(([k, key]) => el('button', { role: 'tab', 'data-tab': k, class: tab === k ? 'on' : '', onclick: () => { tab = k; drawTabs(); load(); } }, t(key))));
  async function load() {
    body.replaceChildren(el('p', { class: 'muted' }, t('common.loading')));
    try { body.replaceChildren(await ADMIN[tab]()); } catch (e) { body.replaceChildren(alertBox(errMsg(e))); }
  }
  drawTabs(); await load();
  return el('div', {}, el('h1', {}, t('a.title')), tabs, body);
};
const ADMIN = {
  async overview() {
    const o = await api('/api/admin/overview');
    return el('div', {}, el('div', { class: 'grid g3 mb' }, stat(nf(o.total_users), t('a.totalusers')), stat(nf(o.active_users_24h), t('a.active')), stat(nf(o.total_assessments), t('a.totalass'))),
      el('div', { class: 'grid g2' }, el('div', { class: 'card' }, el('h2', {}, t('a.perday')), barChart(o.assessments_per_day)),
        el('div', { class: 'card' }, el('h2', {}, t('a.usage')), o.model_usage.length ? table(['Model', 'n'], o.model_usage.map(u => ({ cells: [u.model_version, nf(u.n)] }))) : el('p', { class: 'muted' }, t('a.nodata')),
          el('h3', { class: 'mt' }, t('a.status')), el('p', {}, t('a.model'), ': ', o.system.model_loaded ? t('a.yes') : t('a.no'), ' · ', t('a.assistant'), ': ', o.system.assistant_configured ? t('a.yes') : t('a.no')))));
  },
  async users() {
    const st = { q: '', page: 1 }; const list = el('div');
    const q = el('input', { type: 'search', placeholder: t('a.search'), 'aria-label': t('a.search'), oninput: e => { st.q = e.target.value; st.page = 1; draw(); } });
    async function draw() {
      const d = await api(`/api/admin/users?page=${st.page}&q=${encodeURIComponent(st.q)}`);
      const act = (u, body, label, cls) => el('button', { class: cls || '', 'data-uid': u.id, onclick: async () => { if (!confirm(t('a.confirm'))) return; try { await api('/api/admin/users/' + u.id, { method: 'PATCH', body }); draw(); } catch (e) { alert(errMsg(e)); } } }, label);
      list.replaceChildren(table(['ID', t('auth.name'), t('auth.email'), t('a.role'), t('a.assess'), t('a.lastlogin'), t('a.status.col'), ''], d.items.map(u => ({ cells: [u.id, u.full_name, u.email, el('span', { class: 'badge b-' + u.role }, u.role), nf(u.assessments), fdate(u.last_login_at),
        u.is_active ? t('a.active.y') : t('a.active.n'), u.id === S.user.id ? t('a.self') : el('div', { class: 'row' }, act(u, { role: u.role === 'ADMIN' ? 'USER' : 'ADMIN' }, u.role === 'ADMIN' ? t('a.makeuser') : t('a.makeadmin')), act(u, { is_active: !u.is_active }, u.is_active ? t('a.deactivate') : t('a.activate'), u.is_active ? 'danger' : ''))] }))),
        el('div', { class: 'row between mt' }, el('button', { disabled: st.page <= 1, onclick: () => { st.page--; draw(); } }, t('h.prev')), el('span', { class: 'muted' }, nf(d.total)), el('button', { disabled: st.page * d.page_size >= d.total, onclick: () => { st.page++; draw(); } }, t('h.next'))));
    }
    await draw(); return el('div', { class: 'card' }, el('div', { class: 'mb' }, q), list);
  },
  async audit() {
    const st = { action: '', actor: '', outcome: '', page: 1 }; const list = el('div'); let tm;
    const f = (ph, key) => el('input', { placeholder: ph, 'aria-label': ph, oninput: e => { clearTimeout(tm); tm = setTimeout(() => { st[key] = e.target.value; st.page = 1; draw(); }, 250); } });
    const out = el('select', { 'aria-label': t('a.f.outcome'), onchange: e => { st.outcome = e.target.value; st.page = 1; draw(); } }, el('option', { value: '' }, t('a.f.outcome')), el('option', { value: 'success' }, 'success'), el('option', { value: 'failure' }, 'failure'));
    async function draw() {
      const d = await api(`/api/admin/audit?page=${st.page}&action=${encodeURIComponent(st.action)}&actor=${encodeURIComponent(st.actor)}&outcome=${st.outcome}`);
      list.replaceChildren(table([t('a.time'), t('a.actor'), t('a.action'), t('a.entity'), t('a.outcome'), t('a.meta')], d.items.map(e => ({ cells: [fdate(e.timestamp), e.actor || '—', e.action, e.entity || '—', el('span', { class: 'badge b-' + e.outcome }, e.outcome), el('code', { style: 'font-size:.78rem;word-break:break-all' }, JSON.stringify(e.metadata))] }))),
        el('div', { class: 'row between mt' }, el('button', { disabled: st.page <= 1, onclick: () => { st.page--; draw(); } }, t('h.prev')), el('span', { class: 'muted' }, nf(d.total)), el('button', { disabled: st.page * d.page_size >= d.total, onclick: () => { st.page++; draw(); } }, t('h.next'))));
    }
    await draw(); return el('div', { class: 'card' }, el('div', { class: 'row mb' }, f(t('a.f.action'), 'action'), f(t('a.f.actor'), 'actor'), out), list);
  },
  async predictions() {
    const p = await api('/api/admin/predictions');
    return el('div', { class: 'grid g2' }, el('div', { class: 'card' }, el('h2', {}, t('a.volume')), barChart(p.volume_per_day.map(v => ({ day: v.day, n: v.n })))),
      el('div', { class: 'card' }, el('h2', {}, t('a.bands')), Object.keys(p.band_distribution).length ? table(['', 'n'], Object.entries(p.band_distribution).map(([b, n]) => ({ cells: [badge(b), nf(n)] }))) : el('p', { class: 'muted' }, t('a.nodata'))),
      el('div', { class: 'card' }, el('h2', {}, t('a.versions')), p.model_versions.length ? table(['Model', 'n', 'First', 'Last'], p.model_versions.map(v => ({ cells: [v.model_version, nf(v.n), fdate(v.first_used), fdate(v.last_used)] }))) : el('p', { class: 'muted' }, t('a.nodata'))),
      el('div', { class: 'card' }, el('h2', {}, t('a.failed')), el('div', { class: 'stat' }, el('div', { class: 'v' }, nf(p.failed_requests_total))), p.recent_failures.length > 0 && table([t('a.time'), t('a.actor'), 'Reason'], p.recent_failures.map(f => ({ cells: [fdate(f.timestamp), f.actor || '—', f.reason || '—'] })))));
  },
  async system() {
    const s = await api('/api/admin/system');
    return el('div', { class: 'card' }, table(['', ''], [[t('a.db'), s.database], [t('a.model'), s.model_loaded ? s.model_version : t('a.no')], [t('a.assistant'), s.assistant_configured ? t('a.yes') : t('a.no')], ['Secure cookies', s.cookie_secure ? t('a.yes') : t('a.no')],
      ['Rate limits', s.rate_limits_enabled ? t('a.yes') : t('a.no')], [t('a.uptime'), nf(Math.floor(s.uptime_seconds / 60)) + ' min'], [t('a.migs'), s.migrations.join(', ')]].map(c => ({ cells: c }))));
  },
};

// ---------- chat widget (lives outside #app so state survives navigation)
function resetChat() { S.chat = { open: false, sid: null, msgs: [], busy: false, loaded: false }; }
async function openChat(open) {
  S.chat.open = open; renderChat();
  if (open && !S.chat.loaded && S.user) {
    S.chat.loaded = true;
    try { const h = await api('/api/chat/history'); S.chat.sid = h.session_id; S.chat.msgs = h.messages.map(m => ({ role: m.role, content: m.content })); } catch (e) {}
    renderChat();
  }
}
async function sendChat(text) {
  if (!text.trim() || S.chat.busy) return;
  S.chat.msgs.push({ role: 'user', content: text }); S.chat.busy = true; renderChat();
  try {
    const r = await api('/api/chat', { method: 'POST', body: { message: text, session_id: S.chat.sid, page: S.ctx.page, language: S.lang, risk_band: S.ctx.band, top_factors: S.ctx.factors } });
    S.chat.sid = r.session_id; S.chat.msgs.push({ role: 'assistant', content: r.reply, note: r.mode !== 'groq' ? t('c.kb') : null });
  } catch (e) { S.chat.msgs.push({ role: 'assistant', content: e.code === 'rate_limited' ? t('e.rate_limited') : t('c.err'), note: null }); }
  S.chat.busy = false; renderChat();
}
function renderChat() {
  let root = $('#chat-root');
  if (!root) { root = el('div', { id: 'chat-root' }); document.body.append(root); }
  if (!S.user) { root.replaceChildren(); return; }
  const c = S.chat, kids = [];
  if (c.open) {
    const msgs = el('div', { class: 'msgs', 'aria-live': 'polite', id: 'chat-msgs' }, el('div', { class: 'msg assistant' }, t('c.hello')),
      c.msgs.map(m => el('div', { class: 'msg ' + m.role }, m.content, m.note && el('small', { class: 'muted', style: 'display:block;margin-top:4px' }, m.note))),
      c.busy && el('div', { class: 'msg assistant dots' }, t('c.thinking')));
    const input = el('input', { id: 'chat-input', placeholder: t('c.ph'), maxlength: '1000', 'aria-label': t('c.ph'), autocomplete: 'off' });
    const sugg = (I18N[S.lang]['sugg.' + S.ctx.page] || []);
    kids.push(el('section', { class: 'card chat', role: 'dialog', 'aria-label': t('c.title') },
      el('header', {}, t('c.title'), el('span', { class: 'row' }, el('button', { class: 'icon', id: 'chat-clear', onclick: async () => { if (c.sid) await api('/api/chat/' + c.sid, { method: 'DELETE' }).catch(() => {}); c.sid = null; c.msgs = []; renderChat(); } }, t('c.clear')),
        el('button', { class: 'icon', id: 'chat-close', 'aria-label': t('c.close'), onclick: () => openChat(false) }, '✕'))),
      msgs, !c.msgs.length && el('div', { class: 'sugg' }, sugg.map(s => el('button', { onclick: () => sendChat(s) }, s))),
      el('form', { onsubmit: e => { e.preventDefault(); const v = input.value; input.value = ''; sendChat(v); } }, input, el('button', { class: 'primary', type: 'submit', id: 'chat-send', disabled: c.busy }, t('c.send')))));
  }
  kids.push(el('button', { class: 'primary chat-fab', id: 'chat-fab', onclick: () => openChat(!c.open) }, '💬 ' + t('c.open')));
  root.replaceChildren(...kids);
  const m = $('#chat-msgs'); if (m) m.scrollTop = m.scrollHeight;
  if (c.open && !c.busy) { const i = $('#chat-input'); if (i && document.activeElement === document.body) i.focus(); }
}

// ---------- boot
(async function boot() {
  try { const me = await api('/api/auth/me'); S.user = me.user; applyPrefs(me.user.preferences); } catch (e) { S.user = null; }
  document.documentElement.lang = S.lang;
  render();
})();
})();
