/* FileMaker (independent recreation) — core: DOM helpers, value types, formatting,
   host API, dialogs, menus and icons. Everything hangs off window.FM. */
(function () {
  'use strict';
  const FM = window.FM = window.FM || {};

  // ═══════════════════════════════════════════════════════════════════════
  // DOM
  // ═══════════════════════════════════════════════════════════════════════
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        const v = attrs[k];
        if (v == null || v === false) continue;
        if (k === 'class') el.className = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
        else if (k === 'html') el.innerHTML = v;
        else if (k === 'text') el.textContent = v;
        else if (k === 'dataset') Object.assign(el.dataset, v);
        else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
        else if (k === 'value') el.value = v;
        else if (k === 'checked' || k === 'disabled' || k === 'readOnly' || k === 'selected' || k === 'multiple') el[k] = !!v;
        else el.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      el.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  FM.h = h;
  FM.esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  FM.uid = p => (p || 'x') + Math.random().toString(36).slice(2, 7) + Date.now().toString(36).slice(-4);
  FM.clone = o => o == null ? o : JSON.parse(JSON.stringify(o));
  FM.clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  FM.byName = (a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { sensitivity: 'base' });
  FM.debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  FM.sleep = ms => new Promise(r => setTimeout(r, ms));
  FM.download = function (name, data, type) {
    const blob = data instanceof Blob ? data : new Blob([data], { type: type || 'text/plain;charset=utf-8' });
    const a = h('a', { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  };
  FM.pickFile = function (accept) {
    return new Promise(resolve => {
      const inp = h('input', { type: 'file', accept: accept || '', style: { display: 'none' } });
      inp.addEventListener('change', () => { resolve(inp.files[0] || null); inp.remove(); });
      document.body.appendChild(inp); inp.click();
      // no reliable "cancel" event everywhere; a later focus without a file resolves null
      window.addEventListener('focus', () => setTimeout(() => { if (!inp.files.length) { resolve(null); inp.remove(); } }, 600), { once: true });
    });
  };
  FM.readText = file => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsText(file); });
  FM.readDataURL = file => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
  FM.splitValues = t => { const s = String(t == null ? '' : t).replace(/\r\n|\r/g, '\n'); if (s === '') return []; const a = s.split('\n'); if (a[a.length - 1] === '') a.pop(); return a; };

  // ═══════════════════════════════════════════════════════════════════════
  // FileMaker value types
  // Dates are day numbers (1 = 1/1/0001), times are seconds, timestamps are
  // seconds since 1/1/0001 00:00:00 — the same numbers FileMaker uses.
  // ═══════════════════════════════════════════════════════════════════════
  class FMDate { constructor(n) { this.n = Math.floor(n); } valueOf() { return this.n; } }
  class FMTime { constructor(s) { this.s = s; } valueOf() { return this.s; } }
  class FMTimestamp { constructor(s) { this.s = s; } valueOf() { return this.s; } }
  // Text with character styles (TextColor, TextStyleAdd ...): plain text plus HTML.
  class FMStyled { constructor(text, html) { this.text = text; this.html = html; } toString() { return this.text; } }
  FM.FMDate = FMDate; FM.FMTime = FMTime; FM.FMTimestamp = FMTimestamp; FM.FMStyled = FMStyled;

  function daysFromCivil(y, m, d) {
    y -= m <= 2 ? 1 : 0;
    const era = Math.floor(y / 400), yoe = y - era * 400;
    const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
    const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
    return era * 146097 + doe - 719468;
  }
  function civilFromDays(z) {
    z += 719468;
    const era = Math.floor(z / 146097), doe = z - era * 146097;
    const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
    const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
    const mp = Math.floor((5 * doy + 2) / 153);
    const d = doy - Math.floor((153 * mp + 2) / 5) + 1, m = mp + (mp < 10 ? 3 : -9);
    return [yoe + era * 400 + (m <= 2 ? 1 : 0), m, d];
  }
  const EPOCH = daysFromCivil(1, 1, 1);
  const D = FM.dt = {};
  D.num = (y, m, d) => { // normalises month/day overflow like FileMaker's Date()
    y += Math.floor((m - 1) / 12); m = ((m - 1) % 12 + 12) % 12 + 1;
    return daysFromCivil(y, m, 1) - EPOCH + 1 + (d - 1);
  };
  D.parts = n => civilFromDays(n - 1 + EPOCH);
  D.dow = n => (((n - 1 + EPOCH) % 7 + 7 + 4) % 7) + 1;          // 1 = Sunday
  D.todayNum = () => { const t = new Date(); return D.num(t.getFullYear(), t.getMonth() + 1, t.getDate()); };
  D.nowSeconds = () => { const t = new Date(); return t.getHours() * 3600 + t.getMinutes() * 60 + t.getSeconds(); };
  D.nowTs = () => (D.todayNum() - 1) * 86400 + D.nowSeconds();
  D.MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  D.DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const pad = (n, w) => String(n).padStart(w || 2, '0');
  FM.pad = pad;

  function year2(y) { if (y >= 100) return y; return y < 50 ? 2000 + y : 1900 + y; }
  function monthIndex(word) {
    const w = word.toLowerCase().slice(0, 3);
    const i = D.MONTHS.findIndex(m => m.toLowerCase().startsWith(w));
    return i < 0 ? 0 : i + 1;
  }
  // text -> day number, or null
  D.parseDate = function (s) {
    s = String(s == null ? '' : s).trim();
    if (!s) return null;
    let m;
    if ((m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$/))) return valid(+m[1], +m[2], +m[3]);
    if ((m = s.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{1,4})$/))) return valid(year2(+m[3]), +m[1], +m[2]);
    if ((m = s.match(/^(\d{1,2})[/.-](\d{1,2})$/))) return valid(new Date().getFullYear(), +m[1], +m[2]);
    if ((m = s.match(/^(?:[a-z]+,?\s+)?([a-z]{3,})\.?\s+(\d{1,2}),?\s+(\d{2,4})$/i)) && monthIndex(m[1])) return valid(year2(+m[3]), monthIndex(m[1]), +m[2]);
    if ((m = s.match(/^(\d{1,2})\s+([a-z]{3,})\.?,?\s+(\d{2,4})$/i)) && monthIndex(m[2])) return valid(year2(+m[3]), monthIndex(m[2]), +m[1]);
    return null;
    function valid(y, mo, d) {
      if (mo < 1 || mo > 12 || d < 1 || d > 31 || y < 1 || y > 4000) return null;
      const n = D.num(y, mo, d); const p = D.parts(n);
      return p[1] === mo ? n : null;
    }
  };
  // text -> seconds, or null (allows durations such as 36:00:00)
  D.parseTime = function (s) {
    s = String(s == null ? '' : s).trim();
    if (!s) return null;
    const m = s.match(/^(-)?(\d{1,6})(?::(\d{1,2}))?(?::(\d{1,2}(?:\.\d+)?))?\s*([ap])?\.?\s*m?\.?$/i);
    if (!m || (m[3] == null && !m[5])) return null;
    let hh = +m[2]; const mm = +(m[3] || 0), ss = +(m[4] || 0);
    if (mm > 59 || ss >= 60) return null;
    if (m[5]) { if (hh > 12 || hh === 0) return null; if (/p/i.test(m[5]) && hh < 12) hh += 12; if (/a/i.test(m[5]) && hh === 12) hh = 0; }
    const t = hh * 3600 + mm * 60 + ss;
    return m[1] ? -t : t;
  };
  D.parseTimestamp = function (s) {
    s = String(s == null ? '' : s).trim();
    if (!s) return null;
    let m = s.match(/^(\d{4}-\d{1,2}-\d{1,2})[ T](.+)$/) || s.match(/^(\S+)\s+(\d.*)$/);
    if (m) {
      const d = D.parseDate(m[1]); const t = D.parseTime(m[2].replace(/Z$|[+-]\d{2}:?\d{2}$/, ''));
      if (d != null && t != null) return (d - 1) * 86400 + t;
    }
    const d = D.parseDate(s);
    return d == null ? null : (d - 1) * 86400;
  };
  D.isoDate = n => { const [y, m, d] = D.parts(n); return pad(y, 4) + '-' + pad(m) + '-' + pad(d); };
  D.isoTime = s => {
    const neg = s < 0; s = Math.abs(s);
    const whole = Math.floor(s), frac = s - whole;
    let out = pad(Math.floor(whole / 3600)) + ':' + pad(Math.floor(whole % 3600 / 60)) + ':' + pad(whole % 60);
    if (frac > 1e-9) out += String(+frac.toFixed(6)).slice(1);
    return (neg ? '-' : '') + out;
  };
  D.isoTs = s => D.isoDate(Math.floor(s / 86400) + 1) + ' ' + D.isoTime(((s % 86400) + 86400) % 86400);

  // display formats
  D.formatDate = function (n, style) {
    if (n == null || n === '') return '';
    const [y, m, d] = D.parts(n);
    switch (style) {
      case 'long': return D.MONTHS[m - 1] + ' ' + d + ', ' + y;
      case 'abbr': return D.MONTHS[m - 1].slice(0, 3) + ' ' + d + ', ' + y;
      case 'full': return D.DAYS[D.dow(n) - 1] + ', ' + D.MONTHS[m - 1] + ' ' + d + ', ' + y;
      case 'iso': return D.isoDate(n);
      case 'dmy': return d + '/' + m + '/' + y;
      case 'mdy2': return pad(m) + '/' + pad(d) + '/' + pad(y % 100);
      case 'mdyz': return pad(m) + '/' + pad(d) + '/' + y;
      default: return m + '/' + d + '/' + y;
    }
  };
  D.formatTime = function (s, style) {
    if (s == null || s === '') return '';
    const neg = s < 0; s = Math.abs(s);
    let hh = Math.floor(s / 3600); const mm = Math.floor(s % 3600 / 60); const ss = s % 60;
    const ssText = Number.isInteger(ss) ? pad(ss) : (ss < 10 ? '0' : '') + String(+ss.toFixed(3));
    let out;
    if (style === '24h') out = pad(hh) + ':' + pad(mm) + ':' + ssText;
    else if (style === '24hm') out = pad(hh) + ':' + pad(mm);
    else if (style === 'dur') out = hh + ':' + pad(mm) + ':' + ssText;
    else {
      if (hh >= 24) return (neg ? '-' : '') + hh + ':' + pad(mm) + ':' + ssText;
      const ap = hh >= 12 ? 'PM' : 'AM'; hh = hh % 12 || 12;
      out = style === 'hm' ? hh + ':' + pad(mm) + ' ' + ap : hh + ':' + pad(mm) + ':' + ssText + ' ' + ap;
    }
    return (neg ? '-' : '') + out;
  };
  D.formatTs = (s, dstyle, tstyle) => D.formatDate(Math.floor(s / 86400) + 1, dstyle) + ' ' + D.formatTime(((s % 86400) + 86400) % 86400, tstyle);

  // ── numbers ─────────────────────────────────────────────────────────────
  FM.num = {};
  // FileMaker's GetAsNumber: keep the digits, the first decimal point and a leading minus.
  FM.num.parse = function (v) {
    if (typeof v === 'number') return v;
    let s = String(v == null ? '' : v).trim();
    if (!s) return null;
    if (/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s)) return parseFloat(s);
    let out = '', dot = false, neg = false, digits = false;
    for (const ch of s) {
      if (ch >= '0' && ch <= '9') { out += ch; digits = true; }
      else if (ch === '.' && !dot) { out += ch; dot = true; }
      else if (ch === '-' && !digits) neg = true;
    }
    if (!digits) return null;
    return (neg ? -1 : 1) * parseFloat(out);
  };
  FM.num.plain = function (n) { // no exponent, no float noise
    if (!isFinite(n)) return '?';
    let s = String(parseFloat(n.toPrecision(15)));
    if (/e/i.test(s)) {
      const [mant, exp] = s.split(/e/i); const e = +exp; const neg = mant.startsWith('-');
      let digits = mant.replace(/^-/, '').replace('.', ''); const pointAt = (mant.replace(/^-/, '').indexOf('.') + 1 || mant.replace(/^-/, '').length + 1) - 1 + e;
      if (pointAt <= 0) s = '0.' + '0'.repeat(-pointAt) + digits;
      else if (pointAt >= digits.length) s = digits + '0'.repeat(pointAt - digits.length);
      else s = digits.slice(0, pointAt) + '.' + digits.slice(pointAt);
      if (neg) s = '-' + s;
    }
    return s;
  };
  FM.num.text = function (n) { // as FileMaker turns a number into text: ".5", "-.25"
    let s = FM.num.plain(n);
    if (s.startsWith('0.')) s = s.slice(1); else if (s.startsWith('-0.')) s = '-' + s.slice(2);
    return s;
  };
  FM.num.format = function (n, f) {
    if (n == null || n === '') return '';
    if (!f || f.kind === 'general' || !f.kind) return FM.num.plain(n);
    if (f.kind === 'boolean') return n !== 0 ? (f.yes || 'Yes') : (f.no || 'No');
    let v = f.kind === 'percent' ? n * 100 : n;
    const neg = v < 0; v = Math.abs(v);
    const dec = f.decimals == null ? 2 : +f.decimals;
    let s = v.toFixed(dec);
    if (f.thousands !== false && (f.kind === 'currency' || f.thousands)) {
      const [i, d] = s.split('.'); s = i.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (d ? '.' + d : '');
    }
    if (f.kind === 'currency') s = (f.symbol == null ? '$' : f.symbol) + s;
    if (f.kind === 'percent') s += '%';
    if (neg) s = f.negParen ? '(' + s + ')' : '-' + s;
    return s;
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Host API
  // ═══════════════════════════════════════════════════════════════════════
  class HostError extends Error {
    constructor(message, status, data) { super(message); this.status = status; this.data = data || {}; this.fmError = this.data.fmError; }
  }
  FM.HostError = HostError;
  function csrf() {
    const m = document.querySelector('meta[name="csrf-token"]');
    const fromCookie = (document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith('csrf_token=')) || '').split('=')[1];
    return (m && m.content) || fromCookie || '';
  }
  FM.api = async function (method, path, body, opts) {
    opts = opts || {};
    const headers = { 'X-CSRFToken': csrf() };
    if (opts.token) headers['X-FM-Session'] = opts.token;
    let payload;
    if (body instanceof FormData) payload = body;
    else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
    let resp;
    try {
      resp = await fetch('/filemaker/api' + path, { method, headers, body: payload, credentials: 'same-origin' });
    } catch (e) {
      throw new HostError('The host cannot be reached. Check your connection.', 0, { offline: true });
    }
    if (opts.blob) {
      if (!resp.ok) { let d = {}; try { d = await resp.json(); } catch (e) { /* not json */ } throw new HostError(d.error || 'The host refused the request', resp.status, d); }
      return resp.blob();
    }
    let data = {};
    try { data = await resp.json(); } catch (e) {
      if (resp.status === 400) throw new HostError('Your session has expired. Reload the page and sign in again.', 400, {});
      throw new HostError('The host sent an unexpected reply (' + resp.status + ')', resp.status, {});
    }
    if (!resp.ok || data.success === false) throw new HostError(data.error || 'The host refused the request', resp.status, data);
    return data;
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Dialogs (FileMaker-style modal windows)
  // ═══════════════════════════════════════════════════════════════════════
  let zTop = 5000;
  FM.modalOpen = () => document.querySelectorAll('.fm-modal-back').length > 0;
  FM.modal = function (o) {
    return new Promise(resolve => {
      const back = h('div', { class: 'fm-modal-back' + (o.backClass ? ' ' + o.backClass : '') });
      back.style.zIndex = ++zTop;
      const box = h('div', { class: 'fm-modal ' + (o.className || ''), role: 'dialog', 'aria-modal': 'true' });
      if (o.width) box.style.width = typeof o.width === 'number' ? o.width + 'px' : o.width;
      if (o.height) box.style.height = typeof o.height === 'number' ? o.height + 'px' : o.height;
      const title = h('div', { class: 'fm-modal-title' }, h('span', { text: o.title || 'FileMaker' }));
      const content = h('div', { class: 'fm-modal-body' });
      if (o.body instanceof Node) content.appendChild(o.body);
      else if (o.html != null) content.innerHTML = o.html;
      else if (o.message != null) content.appendChild(h('div', { class: 'fm-msg' }, o.icon ? h('div', { class: 'fm-msg-icon', html: FM.icon(o.icon, 34) }) : null, h('div', { class: 'fm-msg-text', text: o.message })));
      const foot = h('div', { class: 'fm-modal-foot' });
      if (o.footLeft) foot.appendChild(h('div', { class: 'fm-foot-left' }, o.footLeft));
      foot.appendChild(h('div', { class: 'fm-flex1' }));
      let done = false;
      const close = v => {
        if (done) return; done = true;
        back.remove(); document.removeEventListener('keydown', onKey, true);
        if (o.onClose) o.onClose(v);
        resolve(v);
      };
      const api = { close, box, content, foot, title };
      const buttons = (o.buttons || [{ label: 'OK', value: true, primary: true }]);
      buttons.forEach(b => {
        const btn = h('button', { class: 'fm-btn' + (b.primary ? ' primary' : '') + (b.danger ? ' danger' : ''), type: 'button', text: b.label });
        btn.addEventListener('click', async () => {
          if (b.validate) { const ok = await b.validate(api); if (ok === false) return; }
          close(typeof b.value === 'function' ? b.value(api) : b.value);
        });
        if (b.primary) api.primary = btn;
        foot.appendChild(btn);
      });
      function onKey(e) {
        if (back.style.zIndex != zTop) return;
        if (e.key === 'Escape' && o.esc !== false) {
          e.preventDefault(); e.stopPropagation();
          const c = buttons.find(b => b.cancel); close(c ? (typeof c.value === 'function' ? c.value(api) : c.value) : null);
        } else if (e.key === 'Enter' && api.primary && !(e.target && (e.target.tagName === 'TEXTAREA' || e.target.isContentEditable)) && o.enter !== false) {
          e.preventDefault(); e.stopPropagation(); api.primary.click();
        }
        if (o.onKey) o.onKey(e, api);
      }
      document.addEventListener('keydown', onKey, true);
      box.append(title, content, foot);
      back.appendChild(box);
      document.body.appendChild(back);
      makeDraggable(box, title);
      if (o.onOpen) o.onOpen(api);
      const first = box.querySelector('[autofocus]') || box.querySelector('input:not([type=checkbox]):not([type=radio]):not([disabled]),textarea,select');
      setTimeout(() => (first || api.primary || box).focus && (first || api.primary).focus(), 20);
    });
  };
  function makeDraggable(box, handle) {
    handle.addEventListener('mousedown', e => {
      if (e.button !== 0 || e.target.closest('button')) return;
      const r = box.getBoundingClientRect(); const dx = e.clientX - r.left, dy = e.clientY - r.top;
      box.style.position = 'fixed'; box.style.margin = '0';
      const move = ev => { box.style.left = FM.clamp(ev.clientX - dx, 0, innerWidth - 60) + 'px'; box.style.top = FM.clamp(ev.clientY - dy, 0, innerHeight - 40) + 'px'; };
      const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
      document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
      e.preventDefault();
    });
  }
  FM.makeDraggable = makeDraggable;
  // message box: resolves to the 1-based button number (FileMaker's Get(LastMessageChoice))
  FM.alert = function (message, o) {
    o = o || {};
    const labels = o.buttons || ['OK'];
    return FM.modal({
      title: o.title || 'FileMaker', message: String(message), icon: o.icon || (o.danger ? 'warn' : 'info'), width: o.width || 440,
      buttons: labels.slice().reverse().map((l, i) => ({ label: l, value: labels.length - i, primary: i === labels.length - 1, cancel: labels.length > 1 && i === 0 }))
    }).then(v => v == null ? (labels.length > 1 ? labels.length : 1) : v);
  };
  FM.confirm = async function (message, o) {
    o = o || {};
    const v = await FM.alert(message, { title: o.title, buttons: [o.ok || 'OK', o.cancel || 'Cancel'], icon: o.icon || 'warn' });
    return v === 1;
  };
  FM.prompt = async function (message, o) {
    o = o || {};
    const inp = h('input', { class: 'fm-input', type: o.password ? 'password' : 'text', value: o.value || '', style: { width: '100%' } });
    const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-msg-text', style: { marginBottom: '10px' }, text: message }), inp);
    const v = await FM.modal({ title: o.title || 'FileMaker', body, width: o.width || 420, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: o.ok || 'OK', primary: true, value: () => inp.value }], onOpen: () => setTimeout(() => inp.select(), 30) });
    return v;
  };
  FM.toast = function (text, kind) {
    let host = document.querySelector('.fm-toasts');
    if (!host) { host = h('div', { class: 'fm-toasts' }); document.body.appendChild(host); }
    const t = h('div', { class: 'fm-toast ' + (kind || '') , text });
    host.appendChild(t);
    setTimeout(() => t.classList.add('out'), 3200);
    setTimeout(() => t.remove(), 3700);
  };

  // labelled form rows
  FM.row = (label, ...ctl) => h('label', { class: 'fm-row' }, h('span', { class: 'fm-row-l', text: label }), h('span', { class: 'fm-row-c' }, ...ctl));
  FM.select = function (options, value, attrs) {
    const s = h('select', Object.assign({ class: 'fm-input' }, attrs || {}));
    options.forEach(o => {
      if (o && o.group) { const g = h('optgroup', { label: o.group }); o.options.forEach(x => g.appendChild(h('option', { value: x.value, text: x.label }))); s.appendChild(g); return; }
      const opt = typeof o === 'object' ? o : { value: o, label: o };
      s.appendChild(h('option', { value: opt.value, text: opt.label, disabled: opt.disabled }));
    });
    if (value != null) s.value = value;
    return s;
  };
  FM.check = (label, checked, attrs) => {
    const c = h('input', Object.assign({ type: 'checkbox', checked }, attrs || {}));
    const l = h('label', { class: 'fm-check' }, c, h('span', { text: label }));
    l.input = c;
    return l;
  };
  FM.tabs = function (names, build, initial) {
    const head = h('div', { class: 'fm-tabs' });
    const body = h('div', { class: 'fm-tab-body' });
    const wrap = h('div', { class: 'fm-tabwrap' }, head, body);
    const show = i => {
      [...head.children].forEach((b, j) => b.classList.toggle('on', i === j));
      body.innerHTML = ''; body.appendChild(build(i)); wrap.current = i;
    };
    names.forEach((n, i) => head.appendChild(h('button', { type: 'button', class: 'fm-tab', text: n, onclick: () => show(i) })));
    wrap.show = show;
    show(initial || 0);
    return wrap;
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Pop-up menus (menu bar, context menus, toolbar drop-downs)
  // ═══════════════════════════════════════════════════════════════════════
  let openMenus = [];
  function closeMenus(level) {
    while (openMenus.length > (level || 0)) { const m = openMenus.pop(); m.remove(); if (m._onClose) m._onClose(); }
    if (!openMenus.length) document.removeEventListener('mousedown', outside, true);
  }
  function outside(e) { if (!e.target.closest('.fm-popmenu') && !e.target.closest('.fm-menubar-item')) closeMenus(0); }
  FM.closeMenus = closeMenus;
  FM.popupMenu = function (items, x, y, level, onClose) {
    level = level || 0;
    closeMenus(level);
    const m = h('div', { class: 'fm-popmenu' });
    m.style.zIndex = 9000 + level;
    items.filter(Boolean).forEach(it => {
      if (it === '-' || it.sep) { m.appendChild(h('div', { class: 'fm-popmenu-sep' })); return; }
      if (it.header) { m.appendChild(h('div', { class: 'fm-popmenu-head', text: it.header })); return; }
      const row = h('div', { class: 'fm-popmenu-item' + (it.disabled ? ' disabled' : '') + (it.sub ? ' has-sub' : '') },
        h('span', { class: 'fm-pm-check', text: it.checked ? '✓' : '' }),
        h('span', { class: 'fm-pm-label', text: it.label }),
        h('span', { class: 'fm-pm-key', text: it.sub ? '›' : (it.key || '') }));
      if (it.title) row.title = it.title;
      if (it.sub) {
        row.addEventListener('mouseenter', () => { const r = row.getBoundingClientRect(); FM.popupMenu(typeof it.sub === 'function' ? it.sub() : it.sub, r.right - 2, r.top - 4, level + 1); });
      } else {
        row.addEventListener('mouseenter', () => closeMenus(level + 1));
        if (!it.disabled) row.addEventListener('click', e => { e.stopPropagation(); closeMenus(0); setTimeout(() => it.action && it.action(), 0); });
      }
      m.appendChild(row);
    });
    m._onClose = onClose;
    document.body.appendChild(m);
    const r = m.getBoundingClientRect();
    m.style.left = Math.max(0, Math.min(x, innerWidth - r.width - 4)) + 'px';
    m.style.top = Math.max(0, Math.min(y, innerHeight - r.height - 4)) + 'px';
    openMenus.push(m);
    if (openMenus.length === 1) document.addEventListener('mousedown', outside, true);
    return m;
  };
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && openMenus.length) { e.stopPropagation(); closeMenus(0); } }, true);

  // ═══════════════════════════════════════════════════════════════════════
  // Icons (24×24 strokes)
  // ═══════════════════════════════════════════════════════════════════════
  const P = {
    prev: 'M15 6l-6 6 6 6', next: 'M9 6l6 6-6 6', first: 'M17 6l-6 6 6 6M7 6v12', last: 'M7 6l6 6-6 6M17 6v12',
    up: 'M6 15l6-6 6 6', down: 'M6 9l6 6 6-6',
    book: 'M4 5.5C4 4.7 4.7 4 5.5 4H11v16H5.5c-.8 0-1.5-.7-1.5-1.5zM20 5.5c0-.8-.7-1.5-1.5-1.5H13v16h5.5c.8 0 1.5-.7 1.5-1.5z',
    plus: 'M12 5v14M5 12h14', minus: 'M5 12h14', x: 'M6 6l12 12M18 6L6 18', check: 'M5 12.5l4.5 4.5L19 7.5',
    trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
    search: 'M10.5 17a6.5 6.5 0 100-13 6.5 6.5 0 000 13zM15.5 15.5L20 20',
    sort: 'M7 4v16M4 7l3-3 3 3M17 20V4M14 17l3 3 3-3',
    showall: 'M4 6h16M4 12h16M4 18h16',
    omit: 'M12 21a9 9 0 100-18 9 9 0 000 18zM5.6 5.6l12.8 12.8',
    form: 'M4 4h16v16H4zM7 8h10M7 12h10M7 16h6',
    list: 'M4 5h16v4H4zM4 11h16v4H4zM4 17h16v3H4z',
    table: 'M3 5h18v14H3zM3 10h18M3 15h18M9 5v14M15 5v14',
    preview: 'M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7',
    layout: 'M4 4h16v16H4zM4 9h16M10 9v11',
    pointer: 'M6 3l12 9-5.5 1.2L15 20l-2.4 1-2.6-6.6L6 18z',
    text: 'M5 5h14M12 5v14M9 19h6', line: 'M5 19L19 5', rect: 'M4 6h16v12H4z', roundrect: 'M8 6h8a4 4 0 014 4v4a4 4 0 01-4 4H8a4 4 0 01-4-4v-4a4 4 0 014-4z',
    oval: 'M12 18c4.4 0 8-2.7 8-6s-3.6-6-8-6-8 2.7-8 6 3.6 6 8 6z',
    field: 'M3 7h18v10H3zM7 10v4', button: 'M5 8h14a2 2 0 012 2v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4a2 2 0 012-2zM8 12h8',
    portal: 'M3 4h18v16H3zM3 9h18M3 14h18', tab: 'M3 8h18v12H3zM3 8V5h6v3M9 5h6v3',
    slide: 'M4 5h16v11H4zM9 20h.01M12 20h.01M15 20h.01', chart: 'M4 20V4M4 20h16M8 17v-5M12 17V8M16 17v-8',
    web: 'M12 21a9 9 0 100-18 9 9 0 000 18zM3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z',
    image: 'M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15 9.5h.01', popover: 'M4 4h16v10H13l-4 4v-4H4z',
    buttonbar: 'M3 8h18v8H3zM9 8v8M15 8v8',
    db: 'M12 9c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
    script: 'M8 4h11v13a3 3 0 01-3 3H6a2 2 0 01-2-2v-2h11v2a2 2 0 002 2M8 4a2 2 0 00-2 2v10M10 8h6M10 12h6',
    play: 'M7 4l13 8-13 8z', pause: 'M8 5v14M16 5v14', stop: 'M6 6h12v12H6z',
    stepover: 'M4 12a8 8 0 0114-5.3M18 3v4h-4M11 19h2', stepinto: 'M12 4v11M8 11l4 4 4-4M7 20h10', stepout: 'M12 20V9M8 13l4-4 4 4M7 4h10',
    user: 'M12 12a4 4 0 100-8 4 4 0 000 8zM5 20a7 7 0 0114 0', users: 'M9 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM2.5 20a6.5 6.5 0 0113 0M16 4.5a3.5 3.5 0 010 6.5M18 13.5c2 .8 3.5 2.9 3.5 5.5',
    lock: 'M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 017 0v3', key: 'M8 15a4 4 0 100-8 4 4 0 000 8zM12 11h9M18 11v3M21 11v2',
    gear: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z',
    folder: 'M3 6a1 1 0 011-1h5l2 2h9a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1z', file: 'M6 3h8l4 4v14H6zM14 3v4h4',
    star: 'M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z',
    copy: 'M9 9h11v11H9zM5 15H4V4h11v1', print: 'M7 9V3h10v6M7 17H4v-7h16v7h-3M7 14h10v7H7z',
    download: 'M12 4v11M7 10l5 5 5-5M5 20h14', upload: 'M12 20V9M7 14l5-5 5 5M5 4h14',
    share: 'M18 8a3 3 0 100-6 3 3 0 000 6zM6 15a3 3 0 100-6 3 3 0 000 6zM18 22a3 3 0 100-6 3 3 0 000 6zM8.6 13.5l6.8 4M15.4 6.5l-6.8 4',
    grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z', home: 'M4 11l8-7 8 7v9H4zM10 20v-5h4v5',
    info: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 11v6M12 7.5h.01', warn: 'M12 3l10 18H2zM12 10v5M12 18h.01',
    stopsign: 'M8 3h8l5 5v8l-5 5H8l-5-5V8zM12 8v5M12 16h.01',
    calc: 'M6 3h12v18H6zM9 7h6M9 11h.01M12 11h.01M15 11h.01M9 14h.01M12 14h.01M15 14h.01M9 17h.01M12 17h.01M15 17h.01',
    cal: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4', relations: 'M3 4h7v6H3zM14 14h7v6h-7zM10 7h3a1 1 0 011 1v9',
    align: 'M4 4v16M8 7h12M8 12h8M8 17h10', group: 'M3 3h7v7H3zM14 14h7v7h-7zM10 6.5h4v11',
    eye: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 15a3 3 0 100-6 3 3 0 000 6z',
    debug: 'M8 8a4 4 0 018 0v8a4 4 0 01-8 0zM4 11h4M16 11h4M4 17h4M16 17h4M9 4L7 2M15 4l2-2',
    menu: 'M4 6h16M4 12h16M4 18h16', dots: 'M5 12h.01M12 12h.01M19 12h.01',
    expand: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5', refresh: 'M20 11a8 8 0 10-2.3 5.7M20 4v7h-7',
    link: 'M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1',
    paint: 'M4 20l4-1 11-11a2.1 2.1 0 00-3-3L5 16zM14 6l3 3', bold: 'M7 4h6a4 4 0 010 8H7zM7 12h7a4 4 0 010 8H7z',
    italic: 'M11 4h7M6 20h7M15 4L9 20', underline: 'M7 4v7a5 5 0 0010 0V4M5 21h14',
    alignleft: 'M4 6h16M4 10h10M4 14h16M4 18h10', aligncenter: 'M4 6h16M7 10h10M4 14h16M7 18h10', alignright: 'M4 6h16M10 10h10M4 14h16M10 18h10',
    quickfind: 'M10.5 17a6.5 6.5 0 100-13 6.5 6.5 0 000 13zM15.5 15.5L20 20M8 10.5h5',
    data: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM20 12c0 1.7-3.6 3-8 3s-8-1.3-8-3M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6',
    clock: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2'
  };
  FM.icon = function (name, size, extra) {
    const d = P[name] || P.dots;
    return '<svg class="fm-ic ' + (extra || '') + '" width="' + (size || 18) + '" height="' + (size || 18) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>';
  };
  FM.iconNames = Object.keys(P);
  FM.iconEl = (name, size) => { const s = h('span', { class: 'fm-icwrap', html: FM.icon(name, size) }); return s; };

  // ═══════════════════════════════════════════════════════════════════════
  // CSV / TSV
  // ═══════════════════════════════════════════════════════════════════════
  FM.parseDelimited = function (text, sep) {
    text = String(text).replace(/^﻿/, '');
    if (!sep) { const first = text.split(/\r?\n/, 1)[0] || ''; sep = (first.split('\t').length > first.split(',').length) ? '\t' : ','; }
    const rows = []; let row = [], cell = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; }
        else cell += c;
      } else if (c === '"' && cell === '') q = true;
      else if (c === sep) { row.push(cell); cell = ''; }
      else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = ''; }
      else cell += c;
    }
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
    // FileMaker exports returns inside a field as vertical tab
    return rows.map(r => r.map(c => c.replace(/\v/g, '\n')));
  };
  FM.toDelimited = function (rows, sep) {
    return rows.map(r => r.map(v => {
      const s = String(v == null ? '' : v);
      if (sep === '\t') return s.replace(/\t/g, ' ').replace(/\r\n|\r|\n/g, '\v');
      return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    }).join(sep)).join('\r\n') + '\r\n';
  };

  // keyboard: is this the platform's command key?
  FM.cmd = e => e.ctrlKey || e.metaKey;
  FM.isMac = /Mac|iPhone|iPad/.test(navigator.platform);
  FM.keyLabel = k => (FM.isMac ? k.replace(/Ctrl\+/g, '⌘').replace(/Shift\+/g, '⇧').replace(/Alt\+/g, '⌥') : k);
})();
