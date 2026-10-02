/* FileMaker (independent recreation) — the open database file: schema lookups,
   records, relationships, calculations in context, finds, sorts, summaries,
   validation and auto-enter, value lists, ExecuteSQL, and sync with the host. */
(function () {
  'use strict';
  const FM = window.FM;
  const { FMDate, FMTime, FMTimestamp } = FM;
  const V = FM.V, D = FM.dt, C = FM.calc;

  const FIELD_KEY = (to, fid) => to + '::' + fid;
  const SPLIT_KEY = k => { const i = String(k || '').indexOf('::'); return i < 0 ? { to: null, fid: k } : { to: k.slice(0, i), fid: k.slice(i + 2) }; };
  FM.fkey = FIELD_KEY; FM.pkey = SPLIT_KEY;

  // Error numbers used across the app (FileMaker's own numbering).
  FM.ERR = {
    0: 'No error', 1: 'User canceled action', 3: 'Command is unavailable', 4: 'Command is unknown', 5: 'Command is invalid',
    100: 'File is missing', 101: 'Record is missing', 102: 'Field is missing', 103: 'Relationship is missing', 104: 'Script is missing',
    105: 'Layout is missing', 106: 'Table is missing', 108: 'Value list is missing', 112: 'Window is missing',
    200: 'Record access is denied', 201: 'Field cannot be modified', 211: 'Account is missing', 212: 'Invalid user account or password',
    213: 'Old password is not valid', 214: 'Account already exists', 300: 'File is locked or in use', 301: 'Record is in use by another user',
    302: 'Table is in use by another user', 303: 'Database schema is in use by another user', 306: 'Record modification ID does not match',
    400: 'Find criteria are empty', 401: 'No records match the request', 500: 'Date value does not meet validation entry options',
    501: 'Time value does not meet validation entry options', 502: 'Number value does not meet validation entry options',
    503: 'Value in field is not within the range specified in validation entry options', 504: 'Value in field is not unique',
    505: 'Value in field is not an existing value in the file', 506: 'Value in field is not listed in the value list',
    507: 'Value in field failed calculation test of validation entry option', 508: 'Invalid value entered in Find mode',
    509: 'Field requires a valid value', 510: 'Related value is empty or unavailable', 511: 'Value in field exceeds maximum field size',
    800: 'Unable to create file', 802: 'Unable to open file', 1200: 'Generic calculation error', 1630: 'URL format is incorrect',
    1631: 'Connection failed', 3001: 'Command not available in this recreation'
  };

  class FMFile {
    constructor(app, open) {
      this.app = app;
      this.id = open.file.id;
      this.name = open.file.name;
      this.token = open.token;
      this.account = open.account;
      this.hasPassword = open.hasPassword;
      this.seq = open.seq;
      this.users = open.users || [];
      this.globals = new Map();       // field id -> [rep values]
      this.$$ = new Map();            // global variables
      this.$0 = new Map();            // $variables used outside scripts
      this.editing = new Map();       // record id -> {win, data, isNew, rec, locked}
      this.windows = [];
      this.dv = 1;                    // data version: bumps on every record change
      this.memo = new Map();
      this.relMemo = new Map();
      this.idx = new Map();
      this.closed = false;
      this.setSchema(open.schema, open.version, open.serials);
      this.tables = new Map();
      this.schema.tables.forEach(t => this.tables.set(t.id, { recs: new Map() }));
      for (const tid in open.records || {}) (open.records[tid] || []).forEach(r => this.putRecord(r));
      this.initGlobals();
    }

    // ═════════════════════════════════════════════════════════════════════
    // schema
    // ═════════════════════════════════════════════════════════════════════
    setSchema(schema, version, serials) {
      this.schema = schema;
      this.version = version;
      if (serials) this.serials = serials;
      const ix = this.ix = {
        tables: new Map(), tableByName: new Map(), fields: new Map(), tos: new Map(), toByName: new Map(),
        layouts: new Map(), scripts: new Map(), vls: new Map(), cfs: new Map(), adj: new Map(), rels: new Map()
      };
      schema.tables.forEach(t => {
        ix.tables.set(t.id, t); ix.tableByName.set(t.name.toLowerCase(), t);
        t.fields.forEach(f => ix.fields.set(f.id, { field: f, table: t }));
      });
      schema.tableOccurrences.forEach(o => { ix.tos.set(o.id, o); ix.toByName.set(o.name.toLowerCase(), o); ix.adj.set(o.id, []); });
      schema.relationships.forEach(r => {
        ix.rels.set(r.id, r);
        if (ix.adj.has(r.left) && ix.adj.has(r.right)) {
          ix.adj.get(r.left).push({ rel: r, other: r.right, fromLeft: true });
          ix.adj.get(r.right).push({ rel: r, other: r.left, fromLeft: false });
        }
      });
      schema.layouts.forEach(l => ix.layouts.set(l.id, l));
      schema.scripts.forEach(s => ix.scripts.set(s.id, s));
      schema.valueLists.forEach(v => ix.vls.set(v.id, v));
      schema.customFunctions.forEach(c => ix.cfs.set(c.name.toLowerCase(), c));
      this.scopes = new Map();
      this.asts = new Map();
      this.paths = new Map();
      this.cfAsts = new Map();
      if (this.tables) this.schema.tables.forEach(t => { if (!this.tables.has(t.id)) this.tables.set(t.id, { recs: new Map() }); });
      this.touch();
    }
    initGlobals() {
      this.schema.tables.forEach(t => t.fields.forEach(f => {
        if (this.isGlobal(f) && !this.globals.has(f.id)) {
          const init = ((f.options || {}).storage || {}).globalValue;
          this.globals.set(f.id, init == null || init === '' ? [] : [init]);
        }
      }));
    }
    table(id) { return this.ix.tables.get(id); }
    field(fid) { const x = this.ix.fields.get(fid); return x ? x.field : null; }
    tableOfField(fid) { const x = this.ix.fields.get(fid); return x ? x.table : null; }
    to(id) { return this.ix.tos.get(id); }
    toByName(n) { return this.ix.toByName.get(String(n || '').toLowerCase()); }
    tableOfTO(toId) { const o = this.to(toId); return o ? this.table(o.table) : null; }
    layout(id) { return this.ix.layouts.get(id); }
    layoutByName(n) { const l = String(n).toLowerCase(); return this.schema.layouts.find(x => x.name.toLowerCase() === l); }
    script(id) { return this.ix.scripts.get(id); }
    scriptByName(n) { const l = String(n).toLowerCase(); return this.schema.scripts.find(x => x.name.toLowerCase() === l && !x.folder && !x.separator); }
    valueList(id) { return this.ix.vls.get(id); }
    valueListByName(n) { const l = String(n).toLowerCase(); return this.schema.valueLists.find(x => x.name.toLowerCase() === l); }
    isGlobal(f) { return !!(((f.options || {}).storage || {}).global); }
    reps(f) { return Math.max(1, +(((f.options || {}).storage || {}).repetitions || 1)); }
    fieldByKey(key) { const k = SPLIT_KEY(key); return this.field(k.fid); }
    keyLabel(key, contextTO) {
      const k = SPLIT_KEY(key); const f = this.field(k.fid); const o = this.to(k.to);
      if (!f) return '<Field Missing>';
      if (!o) return f.name;
      return (contextTO && contextTO === k.to) ? f.name : o.name + '::' + f.name;
    }
    fullName(key) { const k = SPLIT_KEY(key); const f = this.field(k.fid); const o = this.to(k.to); return f && o ? o.name + '::' + f.name : '<Field Missing>'; }
    keyByName(text, contextTO) { // "TO::Field" or "Field" -> key
      const s = String(text || ''); const i = s.indexOf('::');
      const o = i < 0 ? this.to(contextTO) : this.toByName(s.slice(0, i).trim());
      if (!o) return null;
      const t = this.table(o.table); const fname = (i < 0 ? s : s.slice(i + 2)).trim().toLowerCase();
      const f = t && t.fields.find(x => x.name.toLowerCase() === fname);
      return f ? FIELD_KEY(o.id, f.id) : null;
    }
    baseTO(tableId) { return this.schema.tableOccurrences.find(o => o.table === tableId); }
    layoutsInMenu() { return this.schema.layouts.filter(l => !l.hidden && this.layoutAccess(l.id) !== 'none'); }
    orderedLayouts() {
      const order = this.schema.layoutOrder || [];
      const byId = new Map(this.schema.layouts.map(l => [l.id, l]));
      const out = []; const seen = new Set();
      order.forEach(e => { if (typeof e === 'string' && byId.has(e)) { out.push(byId.get(e)); seen.add(e); } else if (e && e.sep) out.push({ separator: true, id: e.id }); else if (e && e.folder) out.push({ folder: e.folder, id: e.id, items: e.items || [] }); });
      this.schema.layouts.forEach(l => { if (!seen.has(l.id)) out.push(l); });
      return out;
    }

    // ── privileges (the host enforces the same rules on every request) ──
    pset() { return this.schema.privilegeSets.find(p => p.id === this.account.privilegeSet) || {}; }
    get full() { return this.account.privilegeSet === 'PS_FULL'; }
    ext(key) { return (this.pset().extended || []).includes(key); }
    tablePriv(tid) {
      const p = this.pset(); if (this.full) return { view: 'yes', edit: 'yes', create: 'yes', delete: 'yes', fields: 'all' };
      const mode = (p.records || {}).mode;
      if (mode === 'all_ced') return { view: 'yes', edit: 'yes', create: 'yes', delete: 'yes', fields: 'all' };
      if (mode === 'all_ce') return { view: 'yes', edit: 'yes', create: 'yes', delete: 'no', fields: 'all' };
      if (mode === 'all_view') return { view: 'yes', edit: 'no', create: 'no', delete: 'no', fields: 'all' };
      if (mode === 'custom') {
        const tp = ((p.records || {}).tables || {})[tid] || ((p.records || {}).tables || {})['*new*'];
        if (tp) return Object.assign({ fields: 'all' }, tp, tp.view === 'no' ? { edit: 'no', create: 'no', delete: 'no' } : {});
      }
      return { view: 'no', edit: 'no', create: 'no', delete: 'no', fields: 'all' };
    }
    fieldAccess(tid, fid) {
      const tp = this.tablePriv(tid);
      if (!tp.fields || tp.fields === 'all') return 'modify';
      return tp.fields[fid] || tp.fields['*new*'] || 'modify';
    }
    layoutAccess(lid) {
      const p = this.pset().layouts || {};
      if (this.full || p.mode === 'all_modify') return 'modify';
      if (p.mode === 'all_view') return 'view';
      if (p.mode === 'custom') return ((p.items || {})[lid] || {}).layout || 'none';
      return 'none';
    }
    layoutRecordAccess(lid) {
      const p = this.pset().layouts || {};
      if (p.mode === 'custom') return ((p.items || {})[lid] || {}).records || 'modify';
      return 'modify';
    }
    scriptAccess(sid) {
      const p = this.pset().scripts || {};
      if (this.full || p.mode === 'all_modify') return 'modify';
      if (p.mode === 'all_exec') return 'exec';
      if (p.mode === 'custom') return (p.items || {})[sid] || 'none';
      return 'none';
    }
    valueListAccess(id) {
      const p = this.pset().valueLists || {};
      if (this.full || p.mode === 'all_modify') return 'modify';
      if (p.mode === 'all_view') return 'view';
      if (p.mode === 'custom') return (p.items || {})[id] || 'none';
      return 'none';
    }
    canCreateLayouts() { const p = this.pset().layouts || {}; return this.full || p.mode === 'all_modify' || (p.mode === 'custom' && p.allowNew); }
    canCreateScripts() { const p = this.pset().scripts || {}; return this.full || p.mode === 'all_modify' || (p.mode === 'custom' && p.allowNew); }
    canEditRecord(rec) { return rec && !rec.noaccess && (rec.pending || rec.canEdit !== false); }
    canDeleteRecord(rec) { return rec && !rec.noaccess && (rec.pending || rec.canDelete !== false); }
    canCreate(tid) { return this.tablePriv(tid).create === 'yes'; }

    // ═════════════════════════════════════════════════════════════════════
    // records
    // ═════════════════════════════════════════════════════════════════════
    touch() { this.dv++; this.memo.clear(); this.relMemo.clear(); this.idx.clear(); }
    putRecord(r) {
      let t = this.tables.get(r.t);
      if (!t) { t = { recs: new Map() }; this.tables.set(r.t, t); }
      const cur = t.recs.get(r.id);
      if (cur) Object.assign(cur, r); else t.recs.set(r.id, r);
      return t.recs.get(r.id);
    }
    dropRecord(tid, id) { const t = this.tables.get(tid); if (t) t.recs.delete(id); this.editing.delete(id); }
    records(tid) { const t = this.tables.get(tid); return t ? [...t.recs.values()] : []; }
    record(tid, id) { const t = this.tables.get(tid); return t ? t.recs.get(id) : null; }
    recordById(id) { for (const t of this.tables.values()) { const r = t.recs.get(id); if (r) return r; } return null; }
    count(tid) { const t = this.tables.get(tid); return t ? t.recs.size : 0; }

    raw(rec, f, rep) {
      if (this.isGlobal(f)) { const g = this.globals.get(f.id) || []; return g[(rep || 1) - 1] == null ? '' : g[(rep || 1) - 1]; }
      if (!rec) return '';
      const ed = this.editing.get(rec.id);
      let v = ed && Object.prototype.hasOwnProperty.call(ed.data, f.id) ? ed.data[f.id] : rec.d[f.id];
      if (Array.isArray(v)) v = v[(rep || 1) - 1];
      else if ((rep || 1) > 1) v = '';
      return v == null ? '' : v;
    }
    rawAll(rec, f) {
      const n = this.reps(f); const out = [];
      for (let i = 1; i <= n; i++) out.push(this.raw(rec, f, i));
      return out;
    }
    // typed value of a field for a record (calculations and summaries evaluated)
    value(rec, f, rep, ctx) {
      rep = rep || 1;
      if (f.type === 'calculation') return this.calcValue(rec, f, rep, ctx);
      if (f.type === 'summary') return this.summaryInContext(f, rec, ctx);
      if (rec && rec.noaccess) return '';
      const raw = this.raw(rec, f, rep);
      if (f.type === 'container') return raw === '' ? '' : raw;
      return V.fromStored(raw, f.type);
    }
    calcValue(rec, f, rep, ctx) {
      const opts = (f.options || {}).calc || {};
      if (this.isGlobal(f)) {
        const g = this.globals.get(f.id); if (g && g.length) return V.fromStored(g[rep - 1] == null ? '' : g[rep - 1], opts.resultType || 'text');
      }
      if (!rec && !this.isGlobal(f)) return '';
      if (rec && rec.noaccess) return '';
      const key = (rec ? rec.id : 'g') + '|' + f.id + '|' + rep;
      const unstored = opts.stored === false || C.usesGet(this.ast(opts.formula || '', this.calcTO(f)) || {});
      if (!unstored && this.memo.has(key) && !this.editing.has(rec && rec.id)) return this.memo.get(key);
      if (this._calcStack && this._calcStack.has(key)) return '?';
      (this._calcStack || (this._calcStack = new Set())).add(key);
      let v;
      try {
        const reps = this.reps(f);
        if (rep > reps) v = '';
        else {
          const ast = this.ast(opts.formula || '', this.calcTO(f));
          if (!ast) v = '?';
          else if (opts.skipIfEmpty !== false && opts.evalIfAllEmpty === false && this.allRefsEmpty(ast, rec, f)) v = '';
          else v = V.coerce(C.evaluate(ast, this.env({ to: this.calcTO(f), rec, calcRep: rep, win: ctx && ctx.win, summarySet: ctx && ctx.summarySet })), opts.resultType || 'text');
        }
      } catch (e) {
        v = '?';
      } finally { this._calcStack.delete(key); }
      if (!unstored) this.memo.set(key, v);
      return v;
    }
    allRefsEmpty(ast, rec, f) {
      const refs = C.refs(ast);
      return refs.length && refs.every(r => V.empty(this.env({ to: this.calcTO(f), rec }).field(r.ref, null, false)));
    }
    calcTO(f) { const o = ((f.options || {}).calc || {}).context; const t = this.tableOfField(f.id); return (o && this.to(o) && this.to(o).table === t.id) ? o : (this.baseTO(t.id) || {}).id; }
    display(rec, key, rep, ctx, format) { // formatted text for a field key in a TO context
      const v = this.keyValue(key, rec, ctx, rep);
      return this.formatValue(v, this.fieldByKey(key), format);
    }
    formatValue(v, f, format) {
      if (V.empty(v)) return '';
      format = format || {};
      if (v instanceof FMDate) return D.formatDate(v.n, format.date);
      if (v instanceof FMTime) return D.formatTime(v.s, format.time);
      if (v instanceof FMTimestamp) return D.formatTs(v.s, format.date, format.time);
      if (typeof v === 'number') return format.number ? FM.num.format(v, format.number) : FM.num.plain(v);
      if (format.number && f && (f.type === 'number' || (((f.options || {}).calc || {}).resultType === 'number'))) { const n = V.numOrNull(v); if (n != null) return FM.num.format(n, format.number); }
      return V.text(v);
    }
    // the value of "TO::Field" seen from a context record in TO ctx.to
    keyValue(key, rec, ctx, rep) {
      const k = SPLIT_KEY(key);
      return this.env(Object.assign({ to: (ctx && ctx.to) || k.to, rec }, ctx || {})).field({ to: k.to, fid: k.fid }, rep || null, false);
    }

    // ═════════════════════════════════════════════════════════════════════
    // relationships
    // ═════════════════════════════════════════════════════════════════════
    path(from, to) {
      const key = from + '>' + to;
      if (this.paths.has(key)) return this.paths.get(key);
      const prev = new Map([[from, null]]); const q = [from];
      while (q.length) {
        const cur = q.shift(); if (cur === to) break;
        for (const e of this.ix.adj.get(cur) || []) if (!prev.has(e.other)) { prev.set(e.other, { from: cur, e }); q.push(e.other); }
      }
      let p = null;
      if (prev.has(to)) { p = []; let c = to; while (c !== from) { const st = prev.get(c); p.unshift(st.e); c = st.from; } }
      this.paths.set(key, p);
      return p;
    }
    related(fromTO, rec, toTO) {
      if (!rec) return [];
      if (fromTO === toTO) return [rec];
      const mk = fromTO + '|' + rec.id + '|' + toTO;
      if (this.relMemo.has(mk) && !this.editing.size) return this.relMemo.get(mk);
      const p = this.path(fromTO, toTO);
      if (!p) return [];
      let cur = [rec]; let curTO = fromTO;
      for (const hop of p) {
        const next = []; const seen = new Set();
        for (const r of cur) for (const m of this.hopMatches(hop, r, curTO)) if (!seen.has(m.id)) { seen.add(m.id); next.push(m); }
        curTO = hop.other;
        const sort = hop.fromLeft ? (hop.rel.rightOpts || {}).sort : (hop.rel.leftOpts || {}).sort;
        if (sort && sort.length) this.sortRecs(next, sort.map(s => ({ key: FIELD_KEY(curTO, s.fid || SPLIT_KEY(s.key).fid), dir: s.dir })), curTO);
        else if (cur.length > 1) next.sort((a, b) => a.id - b.id);
        cur = next;
        if (!cur.length) break;
      }
      if (!this.editing.size) this.relMemo.set(mk, cur);
      return cur;
    }
    hopMatches(hop, rec, recTO) {
      const rel = hop.rel; const otherTO = this.to(hop.other); if (!otherTO) return [];
      const preds = (rel.predicates || []).map(p => hop.fromLeft ? { mine: p.leftField, op: p.op, theirs: p.rightField } : { mine: p.rightField, op: flip(p.op), theirs: p.leftField });
      if (!preds.length) return [];
      const otherTable = otherTO.table;
      const eq = preds.find(p => p.op === '=');
      let cands;
      const myVal = p => { const f = this.field(p.mine); return f ? (this.reps(f) > 1 && f.type !== 'calculation' ? this.rawAll(rec, f).map(x => V.fromStored(x, f.type)) : [this.value(rec, f, 1, { to: recTO })]) : ['']; };
      if (eq) {
        const keys = new Set();
        for (const v of myVal(eq)) for (const k of keyParts(v)) keys.add(k);
        if (!keys.size) return [];
        const index = this.index(otherTable, eq.theirs, hop.other);
        cands = []; const seen = new Set();
        keys.forEach(k => (index.get(k) || []).forEach(r => { if (!seen.has(r.id)) { seen.add(r.id); cands.push(r); } }));
      } else cands = this.records(otherTable);
      const rest = preds.filter(p => p !== eq);
      if (!rest.length) return cands.sort((a, b) => a.id - b.id);
      return cands.filter(r => rest.every(p => {
        if (p.op === '×') return true;
        const mf = this.field(p.mine), tf = this.field(p.theirs);
        if (!mf || !tf) return false;
        const a = myVal(p)[0]; const b = this.value(r, tf, 1, { to: hop.other });
        if (V.empty(a) || V.empty(b)) return false;
        const c = V.compare(b, a); // their value OP my value, as seen from my side
        switch (p.op) { case '=': return keyParts(a).some(k => keyParts(b).includes(k)); case '≠': return c !== 0; case '<': return c > 0; case '≤': return c >= 0; case '>': return c < 0; case '≥': return c <= 0; }
        return false;
      })).sort((a, b) => a.id - b.id);
    }
    index(tid, fid, toId) {
      const k = tid + '|' + fid;
      if (this.idx.has(k)) return this.idx.get(k);
      const f = this.field(fid); const m = new Map();
      if (f) for (const r of this.records(tid)) {
        const vals = this.reps(f) > 1 && f.type !== 'calculation' ? this.rawAll(r, f).map(x => V.fromStored(x, f.type)) : [this.value(r, f, 1, { to: toId })];
        for (const v of vals) for (const key of keyParts(v)) { if (!m.has(key)) m.set(key, []); m.get(key).push(r); }
      }
      this.idx.set(k, m);
      return m;
    }

    // ═════════════════════════════════════════════════════════════════════
    // calculation context
    // ctx: {to, rec, win, frame (script), rows: {toId: rec} (portal rows),
    //       summarySet: [recs], calcRep, self}
    // ═════════════════════════════════════════════════════════════════════
    scope(toId, params) {
      const k = toId + '|' + (params ? params.join(',') : '');
      if (this.scopes.has(k)) return this.scopes.get(k);
      const file = this;
      const toNames = this.schema.tableOccurrences.map(o => o.name);
      const fieldsFor = o => { const t = o && file.table(o.table); return t ? t.fields.map(f => ({ name: f.name, ref: { to: o.id, fid: f.id } })) : null; };
      const local = fieldsFor(this.to(toId)) || [];
      const s = {
        toNames: () => toNames,
        fields: n => n == null ? local : fieldsFor(file.toByName(n)),
        customFunction: n => { const c = file.ix.cfs.get(String(n).toLowerCase()); return c ? { name: c.name, params: c.params || [] } : null; },
        params
      };
      this.scopes.set(k, s);
      return s;
    }
    ast(formula, toId) {
      const k = toId + '\u0000' + formula;
      if (this.asts.has(k)) return this.asts.get(k);
      let a = null;
      try { a = C.parse(formula, this.scope(toId)); } catch (e) { a = null; }
      this.asts.set(k, a);
      return a;
    }
    check(formula, toId) { return C.parse(formula, this.scope(toId)); } // throws CalcError
    // evaluate a formula in a context; errors give "?" unless strict
    evaluate(formula, ctx, strict) {
      if (formula == null || String(formula).trim() === '') return '';
      let ast;
      try { ast = C.parse(String(formula), this.scope(ctx.to)); } catch (e) { if (strict) throw e; return '?'; }
      try { return C.evaluate(ast, this.env(ctx)); } catch (e) { if (strict) throw e; return '?'; }
    }
    bool(formula, ctx) { return V.bool(this.evaluate(formula, ctx)); }
    env(ctx) {
      const file = this;
      return {
        field(ref, rep, all) {
          const f = file.field(ref.fid);
          if (!f) throw new C.CalcError('The specified field cannot be found.', -1, 102);
          const target = ref.to || ctx.to;
          if (file.isGlobal(f) && f.type !== 'summary') {
            if (all) return file.rawAll(null, f).map(x => V.fromStored(x, f.type === 'calculation' ? ((f.options || {}).calc || {}).resultType : f.type));
            return f.type === 'calculation' ? file.calcValue(null, f, rep || 1, ctx) : V.fromStored(file.raw(null, f, rep || 1), f.type);
          }
          let rec;
          if (ctx.rows && ctx.rows[target]) rec = ctx.rows[target];
          else if (target === ctx.to) rec = ctx.rec;
          else {
            const recs = file.related(ctx.to, ctx.rec, target);
            if (f.type === 'summary') return file.summarize(f, recs);
            if (all) return recs.map(r => file.value(r, f, rep || 1, { to: target, win: ctx.win }));
            rec = recs[0];
            if (!rec) return '';
            return file.value(rec, f, rep || 1, { to: target, win: ctx.win });
          }
          if (all) {
            if (f.type === 'calculation' || f.type === 'summary') return [file.value(rec, f, 1, ctx)];
            return file.rawAll(rec, f).map(x => V.fromStored(x, f.type));
          }
          let r = rep;
          if (r == null) r = (ctx.calcRep && ctx.calcRep <= file.reps(f)) ? ctx.calcRep : 1;
          if (f.type === 'summary') return file.summaryInContext(f, rec, ctx);
          return file.value(rec, f, r, { to: target, win: ctx.win, summarySet: ctx.summarySet });
        },
        isRelated(ref) { return !!ref.to && ref.to !== ctx.to && !(ctx.rows && ctx.rows[ref.to]); },
        repetitions(ref) { const f = file.field(ref.fid); return f ? file.reps(f) : 1; },
        getVar(name, rep) { return file.getVar(name, rep, ctx); },
        setVar(name, value, rep) { file.setVar(name, value, rep, ctx); },
        get(name) { return file.getFn(name, ctx); },
        self() { return ctx.self == null ? '' : ctx.self; },
        customFunction(name) {
          const c = file.ix.cfs.get(String(name).toLowerCase()); if (!c) return null;
          const k = c.id + '|' + file.version;
          if (!file.cfAsts.has(k)) file.cfAsts.set(k, C.parse(c.formula || '', file.scope(ctx.to, c.params || [])));
          return { params: c.params || [], ast: file.cfAsts.get(k) };
        },
        summary(ref, breakRef) {
          const f = file.field(ref.fid); const bf = file.field(breakRef.fid);
          const set = ctx.summarySet || (ctx.win && ctx.win.foundRecords && ctx.win.foundRecords()) || file.records(file.tableOfTO(ctx.to).id);
          if (!f || f.type !== 'summary') return '';
          if (ref.fid === breakRef.fid || !ctx.rec) return file.summarize(f, set);
          const bv = V.text(file.keyValue(FIELD_KEY(breakRef.to || ctx.to, breakRef.fid), ctx.rec, { to: ctx.to }));
          return file.summarize(f, set.filter(r => V.text(file.keyValue(FIELD_KEY(breakRef.to || ctx.to, breakRef.fid), r, { to: ctx.to })) === bv));
        },
        nth(ref, n) {
          const f = file.field(ref.fid); if (!f) return '';
          if (ref.to && ref.to !== ctx.to) { const recs = file.related(ctx.to, ctx.rec, ref.to); return recs[n - 1] ? file.value(recs[n - 1], f, 1, { to: ref.to }) : ''; }
          const set = (ctx.win && ctx.win.foundRecords && ctx.win.foundRecords()) || [];
          return set[n - 1] ? file.value(set[n - 1], f, 1, { to: ctx.to, win: ctx.win }) : '';
        },
        lookupNext(ref, dir) {
          const f = file.field(ref.fid); if (!f || !ref.to) return '';
          const exact = file.related(ctx.to, ctx.rec, ref.to);
          if (exact.length) return file.value(exact[0], f, 1, { to: ref.to });
          const p = file.path(ctx.to, ref.to); if (!p || p.length !== 1) return '';
          const hop = p[0]; const pred = (hop.rel.predicates || [])[0]; if (!pred) return '';
          const mine = file.field(hop.fromLeft ? pred.leftField : pred.rightField), theirs = file.field(hop.fromLeft ? pred.rightField : pred.leftField);
          const mv = file.value(ctx.rec, mine, 1, { to: ctx.to });
          let best = null, bestV = null;
          for (const r of file.records(file.to(ref.to).table)) {
            const tv = file.value(r, theirs, 1, { to: ref.to }); if (V.empty(tv)) continue;
            const c = V.compare(tv, mv);
            if ((dir < 0 && c < 0 && (bestV == null || V.compare(tv, bestV) > 0)) || (dir > 0 && c > 0 && (bestV == null || V.compare(tv, bestV) < 0))) { best = r; bestV = tv; }
          }
          return best ? file.value(best, f, 1, { to: ref.to }) : '';
        },
        sql(q, fs, rs, args) { return file.sql(q, fs, rs, args); },
        fieldByName(text) { const key = file.keyByName(text, ctx.to); return key ? { to: SPLIT_KEY(key).to, fid: SPLIT_KEY(key).fid } : null; },
        fieldName(ref) { return file.fullName(FIELD_KEY(ref.to || ctx.to, ref.fid)); },
        design(name, args) { return file.design(name, args, ctx); },
        layoutObject(name, attr, rep, row) { return ctx.win && ctx.win.layoutObjectAttr ? ctx.win.layoutObjectAttr(name, attr, rep, row) : ''; },
        parse(text) { return C.parse(text, file.scope(ctx.to)); }
      };
    }
    varStore(name, ctx) {
      if (name.startsWith('$$')) return this.$$;
      return (ctx && ctx.frame && ctx.frame.vars) || this.$0;
    }
    getVar(name, rep, ctx) {
      const m = this.varStore(name, ctx).get(name.toLowerCase());
      if (!m) return '';
      const v = m.get(rep || 1); return v == null ? '' : v;
    }
    setVar(name, value, rep, ctx) {
      const store = this.varStore(name, ctx); const k = name.toLowerCase();
      if (!store.has(k)) store.set(k, new Map());
      if (V.empty(value)) store.get(k).delete(rep || 1); else store.get(k).set(rep || 1, value);
      if (!store.get(k).size) store.delete(k);
      store.names = store.names || new Map(); store.names.set(k, name);
    }
    getFn(name, ctx) {
      const w = ctx.win;
      if (w && w.getFn) { const r = w.getFn(name, ctx); if (r !== undefined) return r; }
      const fr = ctx.frame;
      switch (name) {
        case 'accountname': return this.account.name;
        case 'accountprivilegesetname': case 'currentprivilegesetname': return this.pset().name || '';
        case 'accountextendedprivileges': case 'currentextendedprivileges': return (this.pset().extended || []).join('\n');
        case 'accounttype': return 'FileMaker';
        case 'currentdate': return new FMDate(D.todayNum());
        case 'currenttime': return new FMTime(D.nowSeconds());
        case 'currenttimestamp': case 'currenthosttimestamp': return new FMTimestamp(D.nowTs());
        case 'currenttimeutcmilliseconds': return Math.round((Date.now() / 1000 + 62135596800) * 1000);
        case 'currenttimeutcmicroseconds': return Math.round((Date.now() / 1000 + 62135596800) * 1000) * 1000;
        case 'filename': return this.name;
        case 'filepath': return 'fmnet:/' + location.host + '/' + this.name;
        case 'hostname': return location.host;
        case 'hostapplicationversion': return 'Office App Host';
        case 'hostipaddress': case 'systemipaddress': return '';
        case 'applicationversion': return 'Pro 21.0 (independent recreation)';
        case 'applicationlanguage': case 'systemlanguage': return 'English';
        case 'systemplatform': return FM.isMac ? 1 : -2;
        case 'systemversion': return navigator.userAgent;
        case 'device': return /iPad|iPhone/.test(navigator.userAgent) ? 3 : FM.isMac ? 1 : 2;
        case 'username': return this.app.userName();
        case 'usercount': return this.users.length || 1;
        case 'multiuserstate': return 1;
        case 'connectionstate': return 1;
        case 'networkprotocol': return 'HTTPS';
        case 'networktype': return 0;
        case 'uuid': return (crypto.randomUUID ? crypto.randomUUID() : FM.uid('u')).toUpperCase();
        case 'uuidnumber': { let s = String(Math.floor(Math.random() * 9) + 1); while (s.length < 41) s += Math.floor(Math.random() * 10); return s; }
        case 'persistentid': return 'BROWSER-' + this.app.persistentId();
        case 'lasterror': return fr ? fr.rt.lastError : (this.app.lastError || 0);
        case 'lasterrordetail': return fr ? (fr.rt.lastErrorDetail || '') : '';
        case 'lasterrorlocation': return fr ? (fr.rt.lastErrorLocation || '') : '';
        case 'lastmessagechoice': return this.app.lastMessageChoice || 0;
        case 'scriptname': return fr ? fr.script.name : '';
        case 'scriptparameter': return fr ? fr.param : '';
        case 'scriptresult': return fr ? fr.rt.lastResult : (this.app.lastScriptResult || '');
        case 'errorcapturestate': return fr && fr.rt.errorCapture ? 1 : 0;
        case 'allowabortstate': return fr && fr.rt.allowAbort === false ? 0 : 1;
        case 'transactionopenstate': return fr && fr.rt.txn ? 1 : 0;
        case 'scriptanimationstate': return 0;
        case 'layoutcount': return this.schema.layouts.length;
        case 'temporarypath': return '/temp/'; case 'documentspath': return '/documents/'; case 'desktoppath': return '/desktop/'; case 'preferencespath': return '/preferences/'; case 'filemakerpath': return '/filemaker/';
        case 'systemdrive': return '/'; case 'printername': return ''; case 'installedfmplugins': return ''; case 'customemenusetname': case 'custommenusetname': return '[Standard FileMaker Menus]';
        case 'screenwidth': return screen.width; case 'screenheight': return screen.height; case 'screendepth': return screen.colorDepth; case 'screenscalefactor': return window.devicePixelRatio || 1;
        case 'highcontraststate': return 0; case 'usesystemformatsstate': return 1; case 'textrulervisible': return 0; case 'allowformattingbarstate': return 1;
        case 'calculationrepetitionnumber': return ctx.calcRep || 1;
        case 'recordid': return ctx.rec ? ctx.rec.id : '';
        case 'recordmodificationcount': return ctx.rec ? (ctx.rec.mc || 0) : '';
        case 'filesize': return 0;
        case 'sessionidentifier': return '';
      }
      return '';
    }

    // ═════════════════════════════════════════════════════════════════════
    // summaries
    // ═════════════════════════════════════════════════════════════════════
    summaryInContext(f, rec, ctx) {
      const set = (ctx && ctx.summarySet) || (ctx && ctx.win && ctx.win.foundRecords && ctx.win.table && ctx.win.table.id === this.tableOfField(f.id).id && ctx.win.foundRecords()) || this.records(this.tableOfField(f.id).id);
      const s = (f.options || {}).summary || {};
      if (s.running && rec) {
        const i = set.indexOf(rec);
        let part = i < 0 ? set : set.slice(0, i + 1);
        if (s.restart) {
          const bf = this.field(s.restart); const bv = bf ? V.text(this.value(rec, bf, 1, ctx)) : '';
          let j = part.length - 1; while (j > 0 && V.text(this.value(part[j - 1], bf, 1, ctx)) === bv) j--;
          part = part.slice(j);
        }
        return this.summarize(f, part);
      }
      if (s.op === 'fraction' && rec) {
        const src = this.field(s.field); if (!src) return '';
        let group = set;
        if (s.subtotal) { const bf = this.field(s.subtotal); const bv = V.text(this.value(rec, bf, 1, ctx)); group = set.filter(r => V.text(this.value(r, bf, 1, ctx)) === bv); }
        const tot = group.reduce((a, r) => a + V.num(this.value(r, src, 1, ctx)), 0);
        return tot ? V.num(this.value(rec, src, 1, ctx)) / tot : '';
      }
      return this.summarize(f, set);
    }
    summarize(f, recs) {
      const s = (f.options || {}).summary || {};
      const src = this.field(s.field); if (!src) return '';
      const vals = []; recs.forEach(r => { if (this.reps(src) > 1 && s.reps !== 'individual') this.rawAll(r, src).forEach(x => vals.push(V.fromStored(x, src.type))); else vals.push(this.value(r, src, 1, {})); });
      const ne = vals.filter(v => !V.empty(v));
      const nums = ne.map(V.numOrNull).filter(x => x != null);
      const sum = nums.reduce((a, b) => a + b, 0);
      switch (s.op) {
        case 'average': {
          if (s.weight) { const wf = this.field(s.weight); let ws = 0, tot = 0; recs.forEach(r => { const v = V.numOrNull(this.value(r, src, 1, {})), w = V.num(this.value(r, wf, 1, {})); if (v != null) { tot += v * w; ws += w; } }); return ws ? tot / ws : ''; }
          return nums.length ? sum / nums.length : '';
        }
        case 'count': return ne.length;
        case 'min': return ne.length ? ne.reduce((m, v) => V.compare(v, m) < 0 ? v : m) : '';
        case 'max': return ne.length ? ne.reduce((m, v) => V.compare(v, m) > 0 ? v : m) : '';
        case 'stdev': {
          const n = nums.length; const pop = !!s.population; if (n < (pop ? 1 : 2)) return n ? 0 : '';
          const m = sum / n; return Math.sqrt(nums.reduce((a, x) => a + (x - m) * (x - m), 0) / (n - (pop ? 0 : 1)));
        }
        case 'list': return ne.map(V.text).join('\n');
        case 'fraction': return 1;
        default: return sum;
      }
    }

    // ═════════════════════════════════════════════════════════════════════
    // sorting
    // spec: [{key: 'TO::fid', dir: 'asc'|'desc'|'vl', vl}]
    // ═════════════════════════════════════════════════════════════════════
    sortRecs(recs, spec, toId, win) {
      if (!spec || !spec.length) return recs;
      const keys = new Map();
      const prepared = spec.map(s => {
        const k = SPLIT_KEY(s.key); const f = this.field(k.fid);
        let order = null;
        if (s.dir === 'vl' && s.vl) { const vl = this.valueList(s.vl); if (vl) { order = new Map(); this.valueListItems(vl, { to: toId }).forEach((it, i) => order.set(String(it.value).toLowerCase(), i)); } }
        return { s, k, f, order };
      });
      recs.forEach(r => keys.set(r.id, prepared.map(p => p.f ? this.keyValue(p.s.key, r, { to: toId, win }) : '')));
      recs.sort((a, b) => {
        const ka = keys.get(a.id), kb = keys.get(b.id);
        for (let i = 0; i < prepared.length; i++) {
          const p = prepared[i]; let c;
          if (p.order) {
            const ia = p.order.has(V.text(ka[i]).toLowerCase()) ? p.order.get(V.text(ka[i]).toLowerCase()) : 1e9;
            const ib = p.order.has(V.text(kb[i]).toLowerCase()) ? p.order.get(V.text(kb[i]).toLowerCase()) : 1e9;
            c = ia - ib || V.compare(ka[i], kb[i]);
          } else {
            const ea = V.empty(ka[i]), eb = V.empty(kb[i]);
            c = ea && eb ? 0 : ea ? -1 : eb ? 1 : V.compare(ka[i], kb[i]);
            if (p.s.dir === 'desc') c = -c;
          }
          if (c) return c;
        }
        return a.id - b.id;
      });
      return recs;
    }

    // ═════════════════════════════════════════════════════════════════════
    // finds
    // requests: [{omit, crit: {key: text}}]
    // ═════════════════════════════════════════════════════════════════════
    find(tid, toId, requests, base, win) {
      const all = base || this.records(tid);
      const reqs = requests.filter(r => Object.values(r.crit || {}).some(v => String(v).trim() !== ''));
      if (!reqs.length) { const e = new Error('There are no valid criteria in this request.'); e.fmError = 400; throw e; }
      let set = new Set(reqs[0].omit ? all.map(r => r.id) : []);
      const dupCache = new Map();
      for (const rq of reqs) {
        const tests = Object.entries(rq.crit).filter(([, v]) => String(v).trim() !== '').map(([key, text]) => {
          const f = this.fieldByKey(key);
          return { key, f, m: f ? this.matcher(text, f, key, toId, tid, dupCache) : () => false };
        });
        for (const r of all) {
          const ok = tests.every(t => {
            const k = SPLIT_KEY(t.key);
            let vals;
            if (k.to === toId || !k.to) vals = this.reps(t.f) > 1 && t.f.type !== 'calculation' ? this.rawAll(r, t.f).map(x => V.fromStored(x, t.f.type)) : [this.value(r, t.f, 1, { to: toId, win })];
            else { vals = this.related(toId, r, k.to).map(x => this.value(x, t.f, 1, { to: k.to })); if (!vals.length) vals = ['']; }
            return vals.some(v => t.m(v));
          });
          if (ok) { if (rq.omit) set.delete(r.id); else set.add(r.id); }
        }
      }
      return all.filter(r => set.has(r.id));
    }
    // FileMaker find operators for one field
    matcher(text, f, key, toId, tid, dupCache) {
      const type = f.type === 'calculation' ? (((f.options || {}).calc || {}).resultType || 'text') : f.type === 'summary' ? 'number' : f.type;
      const parts = splitCriteria(String(text).trim());
      const ms = parts.map(p => this.matchOne(p, type, key, toId, tid, dupCache));
      return v => ms.every(m => m(v));
    }
    matchOne(c, type, key, toId, tid, dupCache) {
      if (c === '=') return v => V.empty(v);
      if (c === '*') return v => !V.empty(v);
      if (c === '!') {
        if (!dupCache.has(key)) {
          const counts = new Map();
          this.records(tid).forEach(r => { const v = V.text(this.keyValue(key, r, { to: toId })).toLowerCase(); if (v) counts.set(v, (counts.get(v) || 0) + 1); });
          dupCache.set(key, counts);
        }
        const counts = dupCache.get(key);
        return v => (counts.get(V.text(v).toLowerCase()) || 0) > 1;
      }
      if (c === '?') {
        if (type === 'number') return v => !V.empty(v) && typeof v !== 'number';
        if (type === 'date') return v => !V.empty(v) && !(v instanceof FMDate);
        if (type === 'time') return v => !V.empty(v) && !(v instanceof FMTime);
        if (type === 'timestamp') return v => !V.empty(v) && !(v instanceof FMTimestamp);
        return () => false;
      }
      if (type === 'container') { const w = c.toLowerCase(); return v => V.text(v).toLowerCase().includes(w.replace(/[*"]/g, '')); }
      // ranges and comparisons
      let m = c.match(/^(.+?)\s*\.{2,3}\s*(.+)$/);
      if (m) { const lo = this.critRange(m[1], type), hi = this.critRange(m[2], type); if (lo && hi) return v => !V.empty(v) && V.compare(conv(v, type), lo[0]) >= 0 && V.compare(conv(v, type), hi[1]) <= 0; }
      m = c.match(/^(<=|≤|>=|≥|<|>)\s*(.*)$/);
      if (m) {
        const r = this.critRange(m[2], type);
        if (!r) { const t = m[2].toLowerCase(); return v => { if (V.empty(v)) return false; const x = V.text(v).toLowerCase(); return { '<': x < t, '≤': x <= t, '<=': x <= t, '>': x > t, '≥': x >= t, '>=': x >= t }[m[1]]; }; }
        return v => {
          if (V.empty(v)) return false; const x = conv(v, type);
          switch (m[1]) { case '<': return V.compare(x, r[0]) < 0; case '≤': case '<=': return V.compare(x, r[1]) <= 0; case '>': return V.compare(x, r[1]) > 0; default: return V.compare(x, r[0]) >= 0; }
        };
      }
      if (c === '//' && (type === 'date' || type === 'timestamp')) { const t = D.todayNum(); return v => { const d = V.date(v); return !!d && d.n === t; }; }
      if (type === 'number' || type === 'date' || type === 'time' || type === 'timestamp') {
        const exact = c.startsWith('==') ? c.slice(2) : c.startsWith('=') ? c.slice(1) : c;
        const r = this.critRange(exact, type);
        if (r) return v => { if (V.empty(v)) return false; const x = conv(v, type); return V.compare(x, r[0]) >= 0 && V.compare(x, r[1]) <= 0; };
      }
      return textMatcher(c);
    }
    // a criterion value -> [low, high] typed bounds (partial dates give whole periods)
    critRange(s, type) {
      s = String(s).trim();
      if (type === 'number') { const n = FM.num.parse(s); return n == null || !/\d/.test(s) || /[a-z]/i.test(s.replace(/e/i, '')) ? null : [n, n]; }
      if (type === 'date' || type === 'timestamp') {
        const toTs = d => type === 'timestamp' ? new FMTimestamp((d - 1) * 86400) : new FMDate(d);
        const toTsEnd = d => type === 'timestamp' ? new FMTimestamp(d * 86400 - 1) : new FMDate(d);
        if (s === '//') { const t = D.todayNum(); return [toTs(t), toTsEnd(t)]; }
        if (type === 'timestamp' && /\d:\d/.test(s)) { const t = D.parseTimestamp(s); if (t == null) return null; const hasSec = /\d:\d+:\d/.test(s); return [new FMTimestamp(t), new FMTimestamp(t + (hasSec ? 0 : 59))]; }
        let m = s.match(/^(\d{4})$/); if (m) return [toTs(D.num(+m[1], 1, 1)), toTsEnd(D.num(+m[1], 12, 31))];
        m = s.match(/^(\d{1,2})[/-](\d{4})$/); if (m) return [toTs(D.num(+m[2], +m[1], 1)), toTsEnd(D.num(+m[2], +m[1] + 1, 1) - 1)];
        const d = D.parseDate(s); return d == null ? null : [toTs(d), toTsEnd(d)];
      }
      if (type === 'time') {
        let m = s.match(/^(\d{1,3})$/); if (m) return [new FMTime(+m[1] * 3600), new FMTime(+m[1] * 3600 + 3599)];
        const t = D.parseTime(s); if (t == null) return null;
        return [new FMTime(t), new FMTime(t + (/\d:\d+:\d/.test(s) ? 0 : 59))];
      }
      return null;
    }

    // ═════════════════════════════════════════════════════════════════════
    // value lists
    // ═════════════════════════════════════════════════════════════════════
    valueListItems(vl, ctx) {
      if (!vl) return [];
      if (vl.type !== 'field') return (vl.values || []).map(v => v === '-' ? { sep: true } : { value: v, display: v });
      const src = vl.field || {}; const k1 = SPLIT_KEY(src.key || ''); const f1 = this.field(k1.fid);
      if (!f1) return [];
      const f2 = src.key2 ? this.field(SPLIT_KEY(src.key2).fid) : null;
      let recs;
      if (src.related && ctx && ctx.to && ctx.rec) recs = this.related(src.fromTO || ctx.to, ctx.rows && ctx.rows[src.fromTO] || ctx.rec, k1.to);
      else recs = this.records(this.tableOfField(f1.id).id);
      const seen = new Map();
      recs.forEach(r => {
        const vals = this.reps(f1) > 1 ? this.rawAll(r, f1).map(x => V.fromStored(x, f1.type)) : [this.value(r, f1, 1, { to: k1.to })];
        vals.forEach(v => {
          if (V.empty(v)) return;
          const t = this.formatValue(v, f1);
          const key = t.toLowerCase();
          if (!seen.has(key)) seen.set(key, { value: t, typed: v, display: f2 ? V.text(this.formatValue(this.value(r, f2, 1, { to: k1.to }), f2)) : t });
        });
      });
      const items = [...seen.values()];
      const by2 = f2 && src.sortBy === 2;
      items.sort((a, b) => by2 ? V.cmpText(a.display, b.display) : V.compare(a.typed, b.typed));
      return items.map(it => ({ value: it.value, display: f2 ? (src.showOnly2 ? it.display : it.value + '  ' + it.display) : it.value }));
    }

    // ═════════════════════════════════════════════════════════════════════
    // validation and auto-enter
    // ═════════════════════════════════════════════════════════════════════
    // data: stored values to save; returns [{field, code, message, override}]
    validate(table, rec, data, changed, opts) {
      opts = opts || {};
      const out = [];
      const toId = (this.baseTO(table.id) || {}).id;
      for (const f of table.fields) {
        const val = (f.options || {}).validation; if (!val || f.type === 'calculation' || f.type === 'summary' || this.isGlobal(f)) continue;
        if (val.when === 'entry' && opts.import) continue;
        const isChanged = changed.has(f.id);
        if (!isChanged && !(opts.isNew && (val.notEmpty || val.existing || val.memberOf || val.range))) continue;
        const raw = Object.prototype.hasOwnProperty.call(data, f.id) ? data[f.id] : rec.d[f.id];
        const vals = Array.isArray(raw) ? raw : [raw];
        const fail = (code, msg) => out.push({ field: f, code, message: val.message || msg, override: val.allowOverride !== false });
        for (const rv of vals) {
          const text = rv == null ? '' : (typeof rv === 'object' ? (rv.name || '') : String(rv));
          if (val.notEmpty && text.trim() === '') { fail(509, '"' + f.name + '" is defined to require a value.'); break; }
          if (text === '') continue;
          if (val.strict === 'number' || (val.strictType && f.type === 'number')) if (FM.num.parse(text) == null || !/^\s*-?[\d,]*\.?\d+\s*$/.test(text)) { fail(502, '"' + f.name + '" is defined to contain only numeric values.'); break; }
          if ((val.strict === 'date' || val.strictType) && f.type === 'date' && D.parseDate(text) == null) { fail(500, '"' + f.name + '" is defined to contain only valid dates.'); break; }
          if ((val.strict === 'time' || val.strictType) && f.type === 'time' && D.parseTime(text) == null) { fail(501, '"' + f.name + '" is defined to contain only valid times.'); break; }
          if (val.strict === 'year4' && !/\d{4}/.test(text)) { fail(500, '"' + f.name + '" is defined to contain only dates with a 4-digit year.'); break; }
          if (val.maxChars && text.length > +val.maxChars) { fail(511, '"' + f.name + '" is defined to contain at most ' + val.maxChars + ' characters.'); break; }
          if (val.unique || val.existing) {
            const lc = text.toLowerCase();
            const other = this.records(table.id).some(r => r.id !== rec.id && this.rawAll(r, f).some(x => String(x == null ? '' : x).toLowerCase() === lc));
            if (val.unique && other) { fail(504, '"' + f.name + '" is defined to contain only unique values.'); break; }
            if (val.existing && !other) { fail(505, '"' + f.name + '" is defined to contain only existing values.'); break; }
          }
          if (val.memberOf) {
            const items = this.valueListItems(this.valueList(val.memberOf), { to: toId, rec }).filter(x => !x.sep).map(x => String(x.value).toLowerCase());
            const multi = text.split(/\r\n|\r|\n/);
            if (!multi.every(x => items.includes(x.toLowerCase()))) { fail(506, '"' + f.name + '" is defined to contain only values from the value list "' + ((this.valueList(val.memberOf) || {}).name || '') + '".'); break; }
          }
          if (val.range && (val.range.from !== '' || val.range.to !== '')) {
            const tv = V.fromStored(text, f.type);
            const lo = val.range.from === '' || val.range.from == null ? null : V.fromStored(val.range.from, f.type);
            const hi = val.range.to === '' || val.range.to == null ? null : V.fromStored(val.range.to, f.type);
            if ((lo != null && V.compare(tv, lo) < 0) || (hi != null && V.compare(tv, hi) > 0)) { fail(503, '"' + f.name + '" is defined to contain a value from ' + (val.range.from || '…') + ' to ' + (val.range.to || '…') + '.'); break; }
          }
        }
        if (val.calc && (isChanged || opts.isNew) && !out.some(o => o.field === f)) {
          const ed = { data: Object.assign({}, data) }; const saved = this.editing.get(rec.id);
          this.editing.set(rec.id, Object.assign({}, saved || {}, ed));
          const ok = this.bool(val.calc, { to: toId, rec });
          if (saved) this.editing.set(rec.id, saved); else this.editing.delete(rec.id);
          if (!ok) fail(507, '"' + f.name + '" does not meet the validation calculation.');
        }
      }
      return out;
    }
    // auto-enter values for a new record (serials come from the host)
    autoEnterCreate(table, rec, win) {
      const out = {};
      const toId = (this.baseTO(table.id) || {}).id;
      const now = D.nowTs(), today = D.todayNum();
      const last = win && win.lastVisited && win.lastVisited(table.id);
      for (const f of table.fields) {
        const ae = (f.options || {}).autoEnter; if (!ae || f.type === 'calculation' || f.type === 'summary' || this.isGlobal(f)) continue;
        let v;
        switch (ae.creation) {
          case 'date': v = D.isoDate(today); break;
          case 'time': v = D.isoTime(D.nowSeconds()); break;
          case 'timestamp': v = D.isoTs(now); break;
          case 'account': v = this.account.name; break;
          case 'name': v = this.app.userName(); break;
        }
        if (v == null && ae.lastVisited && last) v = last.d[f.id];
        if (v == null && ae.data != null && ae.data !== '') v = ae.data;
        if (v != null) out[f.id] = v;
      }
      // calculations after the plain values, so they can use them
      const ed = this.editing.get(rec.id) || { data: {} };
      Object.assign(ed.data, out);
      this.editing.set(rec.id, ed);
      for (const f of table.fields) {
        const ae = (f.options || {}).autoEnter; if (!ae || !ae.calc || f.type === 'calculation' || f.type === 'summary') continue;
        if (ae.calcSkipEmpty && !this.anyRefFilled(ae.calc, toId, rec)) continue;
        const v = this.evaluate(ae.calc, { to: toId, rec, win });
        out[f.id] = V.toStored(v, f.type); ed.data[f.id] = out[f.id];
      }
      for (const f of table.fields) { const lk = ((f.options || {}).autoEnter || {}).lookup; if (lk && lk.to) { const v = this.lookupValue(f, lk, rec, toId); if (v !== undefined) { out[f.id] = v; ed.data[f.id] = v; } } }
      return out;
    }
    anyRefFilled(formula, toId, rec) {
      const ast = this.ast(formula, toId); if (!ast) return true;
      const refs = C.refs(ast); if (!refs.length) return true;
      const env = this.env({ to: toId, rec });
      return refs.some(r => !V.empty(env.field(r.ref, null, false)));
    }
    // values that change because a record is being committed
    autoEnterModify(table, rec, data, changed) {
      const out = {};
      const toId = (this.baseTO(table.id) || {}).id;
      const ed = { data: Object.assign({}, data) }; const saved = this.editing.get(rec.id);
      this.editing.set(rec.id, Object.assign({}, saved || {}, ed));
      try {
        // lookups whose relationship key changed
        for (const f of table.fields) {
          const lk = ((f.options || {}).autoEnter || {}).lookup; if (!lk || !lk.to || changed.has(f.id)) continue;
          const p = this.path(toId, lk.to); if (!p || !p.length) continue;
          const keyFields = (p[0].rel.predicates || []).map(pr => p[0].fromLeft ? pr.leftField : pr.rightField);
          if (keyFields.some(k => changed.has(k))) { const v = this.lookupValue(f, lk, rec, toId); if (v !== undefined) { out[f.id] = v; ed.data[f.id] = v; } }
        }
        // auto-enter calculations that replace existing values when their fields change
        for (const f of table.fields) {
          const ae = (f.options || {}).autoEnter || {};
          if (!ae.calc || f.type === 'calculation' || f.type === 'summary' || changed.has(f.id)) continue;
          const cur = Object.prototype.hasOwnProperty.call(ed.data, f.id) ? ed.data[f.id] : rec.d[f.id];
          if (ae.calcNoReplace && !(cur == null || cur === '')) continue;
          const ast = this.ast(ae.calc, toId); if (!ast) continue;
          const deps = C.refs(ast).filter(r => !r.ref.to || r.ref.to === toId).map(r => r.ref.fid);
          if (!deps.some(d => changed.has(d) || Object.prototype.hasOwnProperty.call(out, d))) continue;
          const v = V.toStored(C.evaluate(ast, this.env({ to: toId, rec })), f.type);
          out[f.id] = v; ed.data[f.id] = v;
        }
        if (changed.size) {
          const now = D.nowTs();
          for (const f of table.fields) {
            const m = ((f.options || {}).autoEnter || {}).modification; if (!m) continue;
            out[f.id] = m === 'date' ? D.isoDate(D.todayNum()) : m === 'time' ? D.isoTime(D.nowSeconds()) : m === 'timestamp' ? D.isoTs(now) : m === 'account' ? this.account.name : this.app.userName();
          }
        }
      } catch (e) { /* a bad auto-enter formula leaves the value as it is */ }
      finally { if (saved) this.editing.set(rec.id, saved); else this.editing.delete(rec.id); }
      return out;
    }
    lookupValue(f, lk, rec, toId) {
      const src = this.field(lk.field); if (!src) return undefined;
      const recs = this.related(toId, rec, lk.to);
      if (recs.length) {
        const v = this.value(recs[0], src, 1, { to: lk.to });
        if (V.empty(v) && lk.dontCopyEmpty) return undefined;
        return V.toStored(v, f.type);
      }
      switch (lk.noMatch) {
        case 'blank': return '';
        case 'constant': return lk.constant || '';
        case 'lower': case 'higher': { const v = this.env({ to: toId, rec }).lookupNext({ to: lk.to, fid: src.id }, lk.noMatch === 'higher' ? 1 : -1); return V.empty(v) ? undefined : V.toStored(v, f.type); }
        default: return undefined;
      }
    }

    // ═════════════════════════════════════════════════════════════════════
    // host calls
    // ═════════════════════════════════════════════════════════════════════
    api(method, path, body, opts) {
      return FM.api(method, '/files/' + this.id + path, body, Object.assign({ token: this.token }, opts || {})).catch(e => {
        if (e.data && e.data.closed) this.app.fileLost(this, e.message, e.data.kicked);
        throw e;
      });
    }
    async createRecord(tid, data, pending) {
      const r = await this.api('POST', '/records', { ops: [{ op: 'create', table: tid, data: data || {}, pending: pending !== false }] });
      const rec = this.putRecord(r.results[0].record);
      this.touch();
      return rec;
    }
    async batch(ops) {
      const r = await this.api('POST', '/records', { ops });
      r.results.forEach(x => {
        if (x.op === 'delete') { const rec = this.recordById(x.id); if (rec) this.dropRecord(rec.t, x.id); }
        else if (x.record) this.putRecord(x.record);
      });
      this.touch();
      if (this.windows.length) this.app.recordsChanged(this, r.results.map(x => x.id));
      return r.results;
    }
    async lock(rec) {
      if (rec.pending) return { ok: true };
      try {
        const r = await this.api('POST', '/lock', { key: 'rec:' + rec.id });
        if (r.record) { const cur = this.recordById(rec.id); if (cur && cur.mc !== r.record.mc) { this.putRecord(r.record); this.touch(); } }
        return { ok: true };
      } catch (e) {
        return { ok: false, error: e.message, fmError: e.fmError || 301, gone: e.data && e.data.gone };
      }
    }
    async lockKey(key) {
      try { const r = await this.api('POST', '/lock', { key }); return r.success ? { ok: true } : { ok: false, holder: r.holder, error: r.error }; }
      catch (e) { return { ok: false, error: e.message }; }
    }
    async unlock(keys) { try { await this.api('POST', '/unlock', { keys }); } catch (e) { /* the host frees stale locks */ } }
    async saveSchema(ops, serials) {
      const r = await this.api('POST', '/schema', { ops, serials });
      this.applySchema(r.schema, r.version, r.serials);
      return r;
    }
    applySchema(schema, version, serials) {
      const oldTables = new Set(this.schema.tables.map(t => t.id));
      this.setSchema(schema, version, serials);
      this.initGlobals();
      oldTables.forEach(t => { if (!this.ix.tables.has(t)) this.tables.delete(t); });
      this.app.schemaChanged(this);
    }
    async reloadRecords() {
      const r = await FM.api('POST', '/files/' + this.id + '/relogin', null, { token: this.token }).catch(() => null);
      return r;
    }
    startSync() {
      const tick = async () => {
        if (this.closed) return;
        try {
          const r = await this.api('GET', '/changes?since=' + this.seq);
          this.applyChanges(r);
        } catch (e) { if (e.status === 0) this.app.offline(this, true); }
        if (!this.closed) this.syncTimer = setTimeout(tick, document.hidden ? 6000 : 2000);
      };
      this.syncTimer = setTimeout(tick, 1500);
    }
    applyChanges(r) {
      this.app.offline(this, false);
      this.seq = Math.max(this.seq, r.seq || 0);
      this.users = r.users || this.users;
      if (r.schema) this.applySchema(r.schema, r.schemaVersion, r.serials);
      const changed = [];
      (r.records || []).forEach(rec => { this.putRecord(rec); changed.push(rec.id); });
      (r.deleted || []).forEach(d => { this.dropRecord(d.t, d.id); changed.push(d.id); });
      if (changed.length) { this.touch(); this.app.recordsChanged(this, changed, true); }
      (r.messages || []).forEach(m => FM.alert(m.text, { title: 'Message from ' + (m.from || 'host'), icon: 'info' }));
      if (r.fileChanged) this.app.fileChanged(this);
    }
    stopSync() { this.closed = true; clearTimeout(this.syncTimer); }

    // ═════════════════════════════════════════════════════════════════════
    // design functions
    // ═════════════════════════════════════════════════════════════════════
    design(name, args, ctx) {
      const s = this.schema; const lay = n => this.layoutByName(n);
      const fieldsOf = layoutOrTO => {
        const l = lay(layoutOrTO);
        if (l) return FM.layoutFields(l).map(k => this.keyLabel(k, l.to));
        const o = this.toByName(layoutOrTO); const t = o && this.table(o.table);
        return t ? t.fields.map(f => f.name) : [];
      };
      const fld = text => { const k = this.keyByName(text, ctx.to); return k ? this.fieldByKey(k) : null; };
      switch (name) {
        case 'databasenames': return this.app.openFiles().map(f => f.name).join('\n');
        case 'fieldnames': case 'getfieldnames': return fieldsOf(args[1]).join('\n');
        case 'fieldids': { const l = lay(args[1]); return l ? FM.layoutFields(l).map(k => SPLIT_KEY(k).fid).join('\n') : ''; }
        case 'fieldtype': { const f = fld(args[1]); if (!f) return ''; const t = { text: 'Text', number: 'Number', date: 'Date', time: 'Time', timestamp: 'Timestamp', container: 'Binary' }; const kind = f.type === 'calculation' ? 'Calculated' : f.type === 'summary' ? 'Summary' : this.isGlobal(f) ? 'Global' : 'Standard'; const rt = f.type === 'calculation' ? ((f.options || {}).calc || {}).resultType || 'text' : f.type; return kind + ' ' + (t[rt] || 'Text') + ' ' + (f.type === 'calculation' && ((f.options || {}).calc || {}).stored === false ? 'Unindexed' : 'Indexed') + ' ' + this.reps(f); }
        case 'fieldcomment': { const f = fld(args[1]); return f ? f.comment || '' : ''; }
        case 'fieldrepetitions': { const f = fld(args[2]); return f ? this.reps(f) + ' vertical' : ''; }
        case 'fieldstyle': { const l = lay(args[1]); if (!l) return ''; const k = this.keyByName(args[2], l.to); const o = k && FM.layoutObjects(l).find(x => x.type === 'field' && x.field === k); return o ? ({ edit: 'Standard', dropdown: 'Popuplist', popup: 'Popupmenu', checkbox: 'Checkbox', radio: 'RadioButton', calendar: 'Calendar', concealed: 'Standard' }[o.control || 'edit'] + (o.valueList ? ' ' + ((this.valueList(o.valueList) || {}).name || '') : '')) : ''; }
        case 'fieldbounds': { const l = lay(args[1]); if (!l) return ''; const k = this.keyByName(args[2], l.to); const o = k && FM.layoutObjects(l).find(x => x.type === 'field' && x.field === k); return o ? [o.x, o.y, o.x + o.w, o.y + o.h, 0].join(' ') : ''; }
        case 'getnextserialvalue': { const f = fld(args[1]); return f && this.serials ? (this.serials[f.id] || '') : ''; }
        case 'layoutnames': return s.layouts.map(l => l.name).join('\n');
        case 'layoutids': return s.layouts.map(l => l.id).join('\n');
        case 'layoutobjectnames': { const l = lay(args[1]); return l ? FM.layoutObjects(l).filter(o => o.name).map(o => o.name).join('\n') : ''; }
        case 'relationinfo': {
          const o = this.toByName(args[1]); if (!o) return '';
          return (this.ix.adj.get(o.id) || []).map(e => { const other = this.to(e.other); const preds = (e.rel.predicates || []).map(p => (this.to(e.rel.left) || {}).name + '::' + (this.field(p.leftField) || {}).name + ' ' + p.op + ' ' + (this.to(e.rel.right) || {}).name + '::' + (this.field(p.rightField) || {}).name); return 'Source: ' + this.name + '\nTable: ' + other.name + '\nOptions: ' + '\n' + preds.join('\n'); }).join('\n\n');
        }
        case 'scriptnames': return s.scripts.filter(x => !x.folder && !x.separator).map(x => x.name).join('\n');
        case 'scriptids': return s.scripts.filter(x => !x.folder && !x.separator).map(x => x.id).join('\n');
        case 'tablenames': return s.tableOccurrences.map(x => x.name).join('\n');
        case 'tableids': return s.tableOccurrences.map(x => x.id).join('\n');
        case 'basetablenames': return s.tables.map(x => x.name).join('\n');
        case 'basetableids': return s.tables.map(x => x.id).join('\n');
        case 'valuelistnames': return s.valueLists.map(x => x.name).join('\n');
        case 'valuelistids': return s.valueLists.map(x => x.id).join('\n');
        case 'valuelistitems': { const vl = this.valueListByName(args[1]); return vl ? this.valueListItems(vl, ctx).filter(x => !x.sep).map(x => x.value).join('\n') : ''; }
        case 'windownames': return this.app.windows.filter(w => !args[0] || w.file.name.toLowerCase() === args[0].toLowerCase()).map(w => w.name).join('\n');
      }
      return '';
    }

    // ═════════════════════════════════════════════════════════════════════
    // ExecuteSQL (SELECT only, as in FileMaker)
    // ═════════════════════════════════════════════════════════════════════
    sql(query, fs, rs, args) {
      try {
        const q = parseSQL(query);
        const rows = runSQL(this, q, args || []);
        return rows.map(r => r.map(sqlText).join(fs)).join(rs);
      } catch (e) {
        this.lastSQLError = e.message;
        return '?';
      }
    }
  }

  // ── helpers ──────────────────────────────────────────────────────────────
  function flip(op) { return { '<': '>', '>': '<', '≤': '≥', '≥': '≤' }[op] || op; }
  function keyParts(v) {
    if (V.empty(v)) return [];
    if (typeof v === 'number') return [FM.num.plain(v)];
    if (v instanceof FMDate) return ['d' + v.n];
    if (v instanceof FMTime || v instanceof FMTimestamp) return ['t' + v.s];
    return V.text(v).split(/\r\n|\r|\n/).map(s => s.trim().toLowerCase()).filter(Boolean).map(s => /^-?\d+(\.\d+)?$/.test(s) ? FM.num.plain(parseFloat(s)) : s);
  }
  FM.keyParts = keyParts;
  function conv(v, type) {
    if (type === 'number') { const n = V.numOrNull(v); return n == null ? v : n; }
    if (type === 'date') return V.date(v) || v;
    if (type === 'time') return V.time(v) || v;
    if (type === 'timestamp') return V.ts(v) || v;
    return v;
  }
  function splitCriteria(s) { // keep "quoted phrases" and ranges together
    if (/\.{2,3}/.test(s) || /^(<|>|≤|≥|=|!|\?|\/\/)/.test(s)) return [s];
    const out = []; const re = /"[^"]*"|\S+/g; let m;
    while ((m = re.exec(s))) out.push(m[0]);
    return out.length ? out : [s];
  }
  function textMatcher(c) {
    let exactField = false, exactWord = false;
    if (c.startsWith('==')) { exactField = true; c = c.slice(2); } else if (c.startsWith('=')) { exactWord = true; c = c.slice(1); }
    if (/^".*"$/.test(c)) { const lit = c.slice(1, -1).toLowerCase(); return v => exactField ? V.text(v).toLowerCase() === lit : V.text(v).toLowerCase().includes(lit); }
    const pat = '^' + c.toLowerCase().split('').map(ch => ch === '*' ? '.*' : ch === '@' ? '.' : ch === '#' ? '\\d' : ch.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('');
    if (exactField) { const re = new RegExp(pat + '$', 's'); return v => re.test(V.text(v).toLowerCase()); }
    const re = new RegExp(pat + (exactWord ? '$' : ''));
    const wordRe = /[\p{L}\p{N}_]+(?:['’.@-][\p{L}\p{N}_]+)*|[^\s\p{L}\p{N}_]+/gu;
    return v => {
      const t = V.text(v).toLowerCase();
      if (!t) return false;
      if (/\s/.test(c)) return t.includes(c.toLowerCase());
      if (re.test(t)) return true;
      const ws = t.match(wordRe) || [];
      return ws.some(w => re.test(w));
    };
  }

  // ═════════════════════════════════════════════════════════════════════════
  // SQL
  // ═════════════════════════════════════════════════════════════════════════
  function sqlLex(s) {
    const toks = []; let i = 0;
    while (i < s.length) {
      const c = s[i];
      if (/\s/.test(c)) { i++; continue; }
      if (c === "'") { let v = ''; i++; while (i < s.length) { if (s[i] === "'" && s[i + 1] === "'") { v += "'"; i += 2; } else if (s[i] === "'") { i++; break; } else v += s[i++]; } toks.push({ t: 'str', v }); continue; }
      if (c === '"') { const e = s.indexOf('"', i + 1); if (e < 0) throw new Error('Unterminated name'); toks.push({ t: 'id', v: s.slice(i + 1, e) }); i = e + 1; continue; }
      const num = s.slice(i).match(/^\d+(\.\d+)?/); if (num) { toks.push({ t: 'num', v: parseFloat(num[0]) }); i += num[0].length; continue; }
      const op = s.slice(i).match(/^(<>|!=|<=|>=|\|\||[=<>,().*+\-/?])/); if (op) { toks.push({ t: 'op', v: op[0] }); i += op[0].length; continue; }
      const w = s.slice(i).match(/^[A-Za-z_\u00C0-\uFFFF][A-Za-z0-9_\u00C0-\uFFFF]*/); if (w) { toks.push({ t: 'id', v: w[0], kw: w[0].toUpperCase() }); i += w[0].length; continue; }
      throw new Error('Unexpected character ' + c);
    }
    return toks;
  }
  function parseSQL(src) {
    const t = sqlLex(src); let p = 0; let qmark = 0;
    const peek = (o) => t[p + (o || 0)];
    const isKw = (k, o) => { const x = peek(o); return x && x.t === 'id' && x.kw === k && !x.q; };
    const eatKw = k => { if (isKw(k)) { p++; return true; } return false; };
    const needKw = k => { if (!eatKw(k)) throw new Error('Expected ' + k); };
    const isOp = (v) => { const x = peek(); return x && x.t === 'op' && x.v === v; };
    const eatOp = v => { if (isOp(v)) { p++; return true; } return false; };
    const RESERVED = new Set(['FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING', 'JOIN', 'INNER', 'LEFT', 'OUTER', 'ON', 'AS', 'AND', 'OR', 'NOT', 'OFFSET', 'FETCH', 'LIMIT', 'ASC', 'DESC', 'BY', 'UNION', 'IS', 'NULL', 'LIKE', 'IN', 'BETWEEN', 'ROWS', 'ROW', 'FIRST', 'NEXT', 'ONLY', 'CROSS', 'RIGHT']);
    function expr() { return or(); }
    function or() { let a = and(); while (eatKw('OR')) a = { k: 'or', a, b: and() }; return a; }
    function and() { let a = not(); while (eatKw('AND')) a = { k: 'and', a, b: not() }; return a; }
    function not() { if (eatKw('NOT')) return { k: 'not', a: not() }; return cmp(); }
    function cmp() {
      const a = add();
      const x = peek();
      if (x && x.t === 'op' && ['=', '<>', '!=', '<', '<=', '>', '>='].includes(x.v)) { p++; return { k: 'cmp', op: x.v === '!=' ? '<>' : x.v, a, b: add() }; }
      let neg = false;
      if (isKw('NOT') && (isKw('LIKE', 1) || isKw('IN', 1) || isKw('BETWEEN', 1))) { p++; neg = true; }
      if (eatKw('LIKE')) return { k: 'like', a, b: add(), neg };
      if (eatKw('IN')) { if (!eatOp('(')) throw new Error('Expected ('); const items = [expr()]; while (eatOp(',')) items.push(expr()); if (!eatOp(')')) throw new Error('Expected )'); return { k: 'in', a, items, neg }; }
      if (eatKw('BETWEEN')) { const lo = add(); needKw('AND'); return { k: 'between', a, lo, hi: add(), neg }; }
      if (eatKw('IS')) { const n = eatKw('NOT'); needKw('NULL'); return { k: 'isnull', a, neg: n }; }
      return a;
    }
    function add() { let a = mul(); for (;;) { if (eatOp('+')) a = { k: 'ar', op: '+', a, b: mul() }; else if (eatOp('-')) a = { k: 'ar', op: '-', a, b: mul() }; else if (eatOp('||')) a = { k: 'cat', a, b: mul() }; else return a; } }
    function mul() { let a = un(); for (;;) { if (eatOp('*')) a = { k: 'ar', op: '*', a, b: un() }; else if (eatOp('/')) a = { k: 'ar', op: '/', a, b: un() }; else return a; } }
    function un() { if (eatOp('-')) return { k: 'neg', a: un() }; return prim(); }
    function prim() {
      const x = peek(); if (!x) throw new Error('Unexpected end');
      if (eatOp('(')) { const e = expr(); if (!eatOp(')')) throw new Error('Expected )'); return e; }
      if (x.t === 'num') { p++; return { k: 'lit', v: x.v }; }
      if (x.t === 'str') { p++; return { k: 'lit', v: x.v }; }
      if (eatOp('?')) return { k: 'arg', i: qmark++ };
      if (x.t === 'op' && x.v === '*') { p++; return { k: 'star' }; }
      if (x.t === 'id') {
        p++;
        if (x.kw === 'NULL') return { k: 'lit', v: null };
        if ((x.kw === 'DATE' || x.kw === 'TIME' || x.kw === 'TIMESTAMP') && peek() && peek().t === 'str') { const s = t[p++].v; return { k: 'lit', v: x.kw === 'DATE' ? new FMDate(D.parseDate(s)) : x.kw === 'TIME' ? new FMTime(D.parseTime(s)) : new FMTimestamp(D.parseTimestamp(s)) }; }
        if (x.kw === 'CURRENT_DATE') return { k: 'lit', v: new FMDate(D.todayNum()) };
        if (x.kw === 'CURRENT_TIMESTAMP') return { k: 'lit', v: new FMTimestamp(D.nowTs()) };
        if (x.kw === 'CASE') {
          const whens = []; let base = null; if (!isKw('WHEN')) base = expr();
          while (eatKw('WHEN')) { const w = expr(); needKw('THEN'); whens.push([w, expr()]); }
          let els = null; if (eatKw('ELSE')) els = expr(); needKw('END');
          return { k: 'case', base, whens, els };
        }
        if (isOp('(')) {
          p++; const name = x.v.toUpperCase(); let distinct = false; const args = [];
          if (eatKw('DISTINCT')) distinct = true;
          if (!isOp(')')) { args.push(expr()); while (eatOp(',')) args.push(expr()); if (name === 'CAST' && eatKw('AS')) { args.push({ k: 'lit', v: t[p++].v }); } }
          if (!eatOp(')')) throw new Error('Expected )');
          return { k: 'fn', name, args, distinct };
        }
        if (eatOp('.')) { const c = t[p++]; if (!c) throw new Error('Expected column'); if (c.t === 'op' && c.v === '*') return { k: 'star', table: x.v }; return { k: 'col', table: x.v, name: c.v }; }
        return { k: 'col', table: null, name: x.v };
      }
      throw new Error('Unexpected ' + x.v);
    }
    needKw('SELECT');
    const distinct = eatKw('DISTINCT');
    const cols = [];
    do { const e = expr(); let alias = null; if (eatKw('AS')) alias = t[p++].v; else if (peek() && peek().t === 'id' && !RESERVED.has(peek().kw)) alias = t[p++].v; cols.push({ e, alias }); } while (eatOp(','));
    needKw('FROM');
    const tableRef = () => { const n = t[p++]; if (!n || n.t !== 'id') throw new Error('Expected table'); let alias = null; if (eatKw('AS')) alias = t[p++].v; else if (peek() && peek().t === 'id' && !RESERVED.has(peek().kw)) alias = t[p++].v; return { name: n.v, alias: alias || n.v }; };
    const from = [tableRef()]; const joins = [];
    for (;;) {
      if (eatOp(',')) { joins.push({ type: 'cross', ref: tableRef() }); continue; }
      let type = null;
      if (eatKw('INNER')) type = 'inner'; else if (eatKw('LEFT')) { eatKw('OUTER'); type = 'left'; } else if (eatKw('CROSS')) type = 'cross'; else if (isKw('JOIN')) type = 'inner';
      if (!type) break;
      needKw('JOIN'); const ref = tableRef(); let on = null; if (type !== 'cross') { needKw('ON'); on = expr(); }
      joins.push({ type, ref, on });
    }
    let where = null, group = [], having = null, order = [], offset = 0, limit = null;
    if (eatKw('WHERE')) where = expr();
    if (eatKw('GROUP')) { needKw('BY'); do group.push(expr()); while (eatOp(',')); }
    if (eatKw('HAVING')) having = expr();
    if (eatKw('ORDER')) { needKw('BY'); do { const e = expr(); let dir = 1; if (eatKw('DESC')) dir = -1; else eatKw('ASC'); order.push({ e, dir }); } while (eatOp(',')); }
    if (eatKw('OFFSET')) { offset = t[p++].v; eatKw('ROWS') || eatKw('ROW'); }
    if (eatKw('FETCH')) { eatKw('FIRST') || eatKw('NEXT'); limit = t[p++].v; eatKw('ROWS') || eatKw('ROW'); needKw('ONLY'); }
    if (eatKw('LIMIT')) limit = t[p++].v;
    if (p < t.length) throw new Error('Unexpected ' + t[p].v);
    return { distinct, cols, from: from[0], joins, where, group, having, order, offset, limit };
  }
  function runSQL(file, q, args) {
    const bind = ref => { const o = file.toByName(ref.name); if (!o) throw new Error('Unknown table ' + ref.name); return { alias: ref.alias.toLowerCase(), to: o, table: file.table(o.table) }; };
    const sources = [bind(q.from), ...q.joins.map(j => bind(j.ref))];
    const colOf = (src, name) => src.table.fields.find(f => f.name.toLowerCase() === String(name).toLowerCase());
    const val = (row, c) => {
      let src;
      if (c.table) { src = sources.find(s => s.alias === c.table.toLowerCase()); if (!src) throw new Error('Unknown table ' + c.table); }
      else { src = sources.find(s => colOf(s, c.name)); if (!src) throw new Error('Unknown column ' + c.name); }
      const f = colOf(src, c.name); if (!f) throw new Error('Unknown column ' + c.name);
      const rec = row[src.alias]; if (!rec) return null;
      const v = file.value(rec, f, 1, { to: src.to.id }); return V.empty(v) ? null : v;
    };
    let aggRows = null;
    const ev = (e, row) => {
      switch (e.k) {
        case 'lit': return e.v;
        case 'arg': { const a = args[e.i]; return V.empty(a) ? null : a; }
        case 'col': return val(row, e);
        case 'neg': { const x = ev(e.a, row); return x == null ? null : -V.num(x); }
        case 'ar': { const a = ev(e.a, row), b = ev(e.b, row); if (a == null || b == null) return null; const x = V.num(a), y = V.num(b); return e.op === '+' ? x + y : e.op === '-' ? x - y : e.op === '*' ? x * y : (y === 0 ? null : x / y); }
        case 'cat': { const a = ev(e.a, row), b = ev(e.b, row); return (a == null ? '' : V.text(a)) + (b == null ? '' : V.text(b)); }
        case 'and': return truthy(ev(e.a, row)) && truthy(ev(e.b, row));
        case 'or': return truthy(ev(e.a, row)) || truthy(ev(e.b, row));
        case 'not': return !truthy(ev(e.a, row));
        case 'cmp': { const a = ev(e.a, row), b = ev(e.b, row); if (a == null || b == null) return null; const c = sqlCompare(a, b); return { '=': c === 0, '<>': c !== 0, '<': c < 0, '<=': c <= 0, '>': c > 0, '>=': c >= 0 }[e.op]; }
        case 'like': { const a = ev(e.a, row), b = ev(e.b, row); if (a == null || b == null) return null; const re = new RegExp('^' + V.text(b).replace(/[.+?^${}()|[\]\\*]/g, '\\$&').replace(/%/g, '.*').replace(/_/g, '.') + '$', 's'); return re.test(V.text(a)) !== e.neg; }
        case 'in': { const a = ev(e.a, row); if (a == null) return null; return e.items.some(i => { const b = ev(i, row); return b != null && sqlCompare(a, b) === 0; }) !== e.neg; }
        case 'between': { const a = ev(e.a, row), lo = ev(e.lo, row), hi = ev(e.hi, row); if (a == null) return null; return (sqlCompare(a, lo) >= 0 && sqlCompare(a, hi) <= 0) !== e.neg; }
        case 'isnull': { const a = ev(e.a, row); return (a == null) !== e.neg; }
        case 'case': { for (const [w, r] of e.whens) { if (e.base ? sqlCompare(ev(e.base, row), ev(w, row)) === 0 : truthy(ev(w, row))) return ev(r, row); } return e.els ? ev(e.els, row) : null; }
        case 'fn': return fn(e, row);
        case 'star': throw new Error('* is not allowed here');
      }
      throw new Error('Bad expression');
    };
    const AGG = new Set(['COUNT', 'SUM', 'AVG', 'MIN', 'MAX']);
    const fn = (e, row) => {
      if (AGG.has(e.name)) {
        const rows = aggRows || [row];
        if (e.name === 'COUNT' && (!e.args.length || e.args[0].k === 'star')) return rows.length;
        let vals = rows.map(r => ev(e.args[0], r)).filter(v => v != null);
        if (e.distinct) { const seen = new Set(); vals = vals.filter(v => { const k = V.text(v); if (seen.has(k)) return false; seen.add(k); return true; }); }
        if (e.name === 'COUNT') return vals.length;
        if (!vals.length) return null;
        if (e.name === 'SUM') return vals.reduce((a, v) => a + V.num(v), 0);
        if (e.name === 'AVG') return vals.reduce((a, v) => a + V.num(v), 0) / vals.length;
        return vals.reduce((m, v) => (sqlCompare(v, m) * (e.name === 'MIN' ? -1 : 1) > 0 ? v : m));
      }
      const a = e.args.map(x => ev(x, row));
      switch (e.name) {
        case 'UPPER': case 'UCASE': return a[0] == null ? null : V.text(a[0]).toUpperCase();
        case 'LOWER': case 'LCASE': return a[0] == null ? null : V.text(a[0]).toLowerCase();
        case 'TRIM': return a[0] == null ? null : V.text(a[0]).trim();
        case 'LTRIM': return a[0] == null ? null : V.text(a[0]).replace(/^\s+/, '');
        case 'RTRIM': return a[0] == null ? null : V.text(a[0]).replace(/\s+$/, '');
        case 'LENGTH': case 'CHAR_LENGTH': return a[0] == null ? null : V.text(a[0]).length;
        case 'SUBSTR': case 'SUBSTRING': return a[0] == null ? null : V.text(a[0]).substr(V.num(a[1]) - 1, a[2] == null ? undefined : V.num(a[2]));
        case 'LEFT': return a[0] == null ? null : V.text(a[0]).slice(0, V.num(a[1]));
        case 'RIGHT': return a[0] == null ? null : V.text(a[0]).slice(-V.num(a[1]));
        case 'COALESCE': case 'IFNULL': case 'NVL': return a.find(x => x != null) ?? null;
        case 'ABS': return a[0] == null ? null : Math.abs(V.num(a[0]));
        case 'ROUND': return a[0] == null ? null : Number(Math.round(Number(V.num(a[0]) + 'e' + (V.num(a[1]) || 0))) + 'e-' + (V.num(a[1]) || 0));
        case 'YEAR': { const d = a[0] == null ? null : V.date(a[0]); return d ? D.parts(d.n)[0] : null; }
        case 'MONTH': { const d = a[0] == null ? null : V.date(a[0]); return d ? D.parts(d.n)[1] : null; }
        case 'DAY': { const d = a[0] == null ? null : V.date(a[0]); return d ? D.parts(d.n)[2] : null; }
        case 'CAST': { const ty = String(a[1] || '').toUpperCase(); if (a[0] == null) return null; if (/CHAR|TEXT/.test(ty)) return V.text(a[0]); if (/INT/.test(ty)) return Math.trunc(V.num(a[0])); if (/DEC|NUM|FLOAT|REAL|DOUBLE/.test(ty)) return V.num(a[0]); if (ty === 'DATE') return V.date(a[0]); return a[0]; }
        case 'STRVAL': return a[0] == null ? null : V.text(a[0]);
        case 'NUMVAL': return a[0] == null ? null : V.num(a[0]);
        case 'CURDATE': return new FMDate(D.todayNum());
      }
      throw new Error('Unknown function ' + e.name);
    };
    const truthy = v => v === true || (typeof v === 'number' && v !== 0);
    // rows
    let rows = file.records(sources[0].table.id).map(r => ({ [sources[0].alias]: r }));
    q.joins.forEach((j, i) => {
      const src = sources[i + 1]; const recs = file.records(src.table.id); const next = [];
      rows.forEach(row => {
        let any = false;
        recs.forEach(r => { const nr = Object.assign({}, row, { [src.alias]: r }); if (j.type === 'cross' || truthy(ev(j.on, nr))) { next.push(nr); any = true; } });
        if (!any && j.type === 'left') next.push(Object.assign({}, row, { [src.alias]: null }));
      });
      rows = next;
    });
    if (q.where) rows = rows.filter(r => truthy(ev(q.where, r)));
    const hasAgg = q.cols.some(c => usesAgg(c.e)) || q.group.length;
    let result;
    if (hasAgg) {
      const groups = new Map();
      rows.forEach(r => { const k = q.group.map(g => V.text(ev(g, r))).join('\u0001'); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(r); });
      if (!q.group.length && !groups.size) groups.set('', []);
      result = [];
      groups.forEach(g => {
        aggRows = g;
        const rep = g[0] || {};
        if (q.having && !truthy(ev(q.having, rep))) { aggRows = null; return; }
        const outRow = q.cols.map(c => ev(c.e, rep));
        outRow._sort = q.order.map(o => ev(o.e, rep));
        result.push(outRow);
        aggRows = null;
      });
    } else {
      result = rows.map(r => {
        const outRow = [];
        q.cols.forEach(c => {
          if (c.e.k === 'star') sources.filter(s => !c.e.table || s.alias === c.e.table.toLowerCase()).forEach(s => s.table.fields.forEach(f => outRow.push(r[s.alias] ? (V.empty(file.value(r[s.alias], f, 1, { to: s.to.id })) ? null : file.value(r[s.alias], f, 1, { to: s.to.id })) : null)));
          else outRow.push(ev(c.e, r));
        });
        outRow._sort = q.order.map(o => { if (o.e.k === 'lit' && typeof o.e.v === 'number') return outRow[o.e.v - 1]; const al = o.e.k === 'col' && !o.e.table && q.cols.findIndex(c => c.alias && c.alias.toLowerCase() === o.e.name.toLowerCase()); return al >= 0 && al !== false ? outRow[al] : ev(o.e, r); });
        return outRow;
      });
    }
    if (q.distinct) { const seen = new Set(); result = result.filter(r => { const k = r.map(sqlText).join('\u0001'); if (seen.has(k)) return false; seen.add(k); return true; }); }
    if (q.order.length) result.sort((a, b) => { for (let i = 0; i < q.order.length; i++) { const x = a._sort[i], y = b._sort[i]; const c = x == null && y == null ? 0 : x == null ? -1 : y == null ? 1 : sqlCompare(x, y); if (c) return c * q.order[i].dir; } return 0; });
    result = result.slice(q.offset || 0, q.limit != null ? (q.offset || 0) + q.limit : undefined);
    return result;
  }
  function usesAgg(e) { if (!e || typeof e !== 'object') return false; if (e.k === 'fn' && /^(COUNT|SUM|AVG|MIN|MAX)$/.test(e.name)) return true; return Object.values(e).some(v => Array.isArray(v) ? v.some(usesAgg) : (v && typeof v === 'object' && usesAgg(v))); }
  function sqlCompare(a, b) {
    if (typeof a === 'string' && typeof b === 'string') return a < b ? -1 : a > b ? 1 : 0; // ExecuteSQL text comparison is case-sensitive
    return V.compare(a, b);
  }
  function sqlText(v) {
    if (v == null) return '';
    if (v === true) return '1'; if (v === false) return '0';
    if (v instanceof FMDate) return D.isoDate(v.n);
    if (v instanceof FMTime) return D.isoTime(v.s);
    if (v instanceof FMTimestamp) return D.isoTs(v.s);
    if (typeof v === 'number') return FM.num.plain(v);
    return V.text(v);
  }

  // every object on a layout (nested ones included), and its field keys
  FM.layoutObjects = function (layout) {
    const out = [];
    (function walk(list) { (list || []).forEach(o => { out.push(o); if (o.children) walk(o.children); if (o.tabs) o.tabs.forEach(t => walk(t.children)); }); })(layout.objects);
    return out;
  };
  FM.layoutFields = function (layout) {
    const seen = new Set();
    FM.layoutObjects(layout).forEach(o => { if (o.type === 'field' && o.field) seen.add(o.field); });
    return [...seen];
  };

  FM.FMFile = FMFile;
})();
