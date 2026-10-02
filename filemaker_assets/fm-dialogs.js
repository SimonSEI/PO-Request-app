/* FileMaker (independent recreation) — dialogs: Specify Calculation, Manage
   Database (tables, fields, relationships graph), field options, value lists,
   custom functions, security, sort, find requests, import/export, page setup,
   file options, sharing, preferences, help. */
(function () {
  'use strict';
  const FM = window.FM;
  const { h } = FM;
  const V = FM.V, D = FM.dt;
  const FMError = FM.FMError;
  const dlg = FM.dlg = {};
  const TYPES = [['text', 'Text'], ['number', 'Number'], ['date', 'Date'], ['time', 'Time'], ['timestamp', 'Timestamp'], ['container', 'Container'], ['calculation', 'Calculation'], ['summary', 'Summary']];
  const typeLabel = t => (TYPES.find(x => x[0] === t) || [, t])[1];
  const RESULT_TYPES = TYPES.filter(t => t[0] !== 'calculation' && t[0] !== 'summary');

  // TOs listed for a context: the context first, then related ones, then the rest
  function tosFor(file, to) {
    const all = file.schema.tableOccurrences;
    const rel = [], unrel = [];
    all.forEach(o => { if (o.id === to) return; (to && file.path(to, o.id) ? rel : unrel).push(o); });
    return { ctx: file.to(to), rel, unrel };
  }
  function toSelect(file, to, value, o) {
    o = o || {};
    const t = tosFor(file, to);
    const opts = [];
    if (t.ctx) opts.push({ value: t.ctx.id, label: 'Current Table ("' + t.ctx.name + '")' });
    if (t.rel.length) opts.push({ group: 'Related Tables', options: t.rel.map(x => ({ value: x.id, label: x.name })) });
    if (t.unrel.length && !o.relatedOnly) opts.push({ group: 'Unrelated Tables', options: t.unrel.map(x => ({ value: x.id, label: x.name })) });
    if (!opts.length) opts.push({ value: '', label: '(no tables)' });
    return FM.select(opts, value || (t.ctx ? t.ctx.id : (file.schema.tableOccurrences[0] || {}).id), o.attrs);
  }
  FM.toSelect = toSelect;

  // ═══════════════════════════════════════════════════════════════════════
  // Specify Field
  // ═══════════════════════════════════════════════════════════════════════
  dlg.pickField = function (file, o) {
    o = o || {};
    let to = o.current ? FM.pkey(o.current).to : (o.to || (file.schema.tableOccurrences[0] || {}).id);
    const sel = toSelect(file, o.to, to, { relatedOnly: o.relatedOnly });
    const list = h('select', { class: 'fm-input fm-list', size: 14 });
    const label = FM.check('Create label', o.labelDefault !== false);
    const fill = () => {
      list.innerHTML = '';
      const t = file.tableOfTO(sel.value);
      (t ? t.fields : []).filter(f => !o.filter || o.filter(f)).forEach(f => list.appendChild(h('option', { value: FM.fkey(sel.value, f.id), text: f.name + '   (' + typeLabel(f.type) + ')' })));
      if (o.current && FM.pkey(o.current).to === sel.value) list.value = o.current;
      if (list.selectedIndex < 0 && list.options.length) list.selectedIndex = 0;
    };
    sel.addEventListener('change', fill); fill();
    let api;
    list.addEventListener('dblclick', () => api && api.primary.click());
    const body = h('div', { class: 'fm-form' }, sel, list, o.label ? label : null, o.allowNone ? h('div', { class: 'fm-muted small', text: 'Choose a field, or Clear for none.' }) : null);
    const buttons = [{ label: 'Cancel', value: undefined, cancel: true }];
    if (o.allowNone) buttons.push({ label: 'Clear', value: null });
    buttons.push({ label: 'OK', primary: true, value: () => (o.label ? { key: list.value, label: label.input.checked } : list.value) });
    return FM.modal({ title: o.title || 'Specify Field', body, width: 380, buttons, onOpen: a => { api = a; } });
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Specify Calculation
  // ═══════════════════════════════════════════════════════════════════════
  dlg.calc = function (file, o) {
    o = o || {};
    const ctxTO = o.to || (file.schema.tableOccurrences[0] || {}).id;
    let ctxSel = null;
    if (o.contextChoice) {
      const t = file.tableOfTO(ctxTO);
      ctxSel = FM.select(file.schema.tableOccurrences.filter(x => !t || x.table === t.id).map(x => ({ value: x.id, label: x.name })), o.context || ctxTO);
    }
    const ta = h('textarea', { class: 'fm-input fm-mono fm-calc-text', spellcheck: 'false', rows: 9 });
    ta.value = o.formula || '';
    const insert = (text, selectInner) => {
      const s = ta.selectionStart, e = ta.selectionEnd;
      ta.setRangeText(text, s, e, 'end');
      if (selectInner) { const m = text.indexOf('('); if (m >= 0) { const inner = text.slice(m + 1, text.lastIndexOf(')')).trim(); const at = s + text.indexOf(inner); ta.setSelectionRange(at, at + inner.length); } }
      ta.focus(); ta.dispatchEvent(new Event('input'));
    };
    // fields
    const toSel = toSelect(file, ctxTO, ctxTO);
    const fields = h('select', { class: 'fm-input fm-list', size: 10 });
    const fillFields = () => {
      fields.innerHTML = '';
      const t = file.tableOfTO(toSel.value);
      (t ? t.fields : []).forEach(f => fields.appendChild(h('option', { value: f.name, text: f.name })));
    };
    toSel.addEventListener('change', fillFields); fillFields();
    fields.addEventListener('dblclick', () => {
      const curCtx = ctxSel ? ctxSel.value : ctxTO;
      const name = toSel.value === curCtx ? fields.value : file.to(toSel.value).name + '::' + fields.value;
      insert(/[;()&+\-*/^=<>"¶[\]]/.test(name) ? '${' + name + '}' : name);
    });
    // operators
    const ops = h('div', { class: 'fm-calc-ops' });
    ['&', '"', '¶', '+', '-', '*', '/', '^', '(', ')', '=', '≠', '<', '>', '≤', '≥', 'and', 'or', 'xor', 'not'].forEach(op => ops.appendChild(h('button', { type: 'button', class: 'fm-opbtn', text: op, onclick: () => insert(op === '"' ? '""' : /^[a-z]+$/.test(op) ? ' ' + op + ' ' : op) })));
    // functions
    const view = FM.select([{ value: 'all', label: 'All functions by name' }, { value: 'type', label: 'All functions by type' }].concat(FM.calc.CATEGORIES.map(c => ({ value: 'cat:' + c, label: c + ' functions' }))).concat([{ value: 'custom', label: 'Custom functions' }]), 'all');
    const fsearch = h('input', { class: 'fm-input', placeholder: 'Search functions' });
    const fns = h('select', { class: 'fm-input fm-list', size: 10 });
    const fillFns = () => {
      fns.innerHTML = '';
      const q = fsearch.value.trim().toLowerCase();
      const v = view.value;
      let items;
      if (v === 'custom') items = file.schema.customFunctions.map(c => ({ name: c.name, sig: c.name + (c.params && c.params.length ? ' ( ' + c.params.join(' ; ') + ' )' : ''), cat: 'Custom' }));
      else items = FM.calc.CATALOG.filter(f => v === 'all' || v === 'type' || f.cat === v.slice(4));
      if (v === 'all') items = items.slice().sort((a, b) => a.name.localeCompare(b.name));
      if (v === 'type') items = items.slice().sort((a, b) => FM.calc.CATEGORIES.indexOf(a.cat) - FM.calc.CATEGORIES.indexOf(b.cat));
      items.filter(f => !q || f.name.toLowerCase().includes(q)).forEach(f => fns.appendChild(h('option', { value: f.sig, text: (v === 'type' ? f.cat + ' — ' : '') + f.sig })));
    };
    view.addEventListener('change', fillFns); fsearch.addEventListener('input', fillFns); fillFns();
    fns.addEventListener('dblclick', () => insert(fns.value, true));
    // options
    const resType = o.resultType != null ? FM.select(RESULT_TYPES.map(([v, l]) => ({ value: v, label: l })), o.resultType) : null;
    const reps = o.reps != null ? h('input', { class: 'fm-input', type: 'number', min: 1, max: 1000, value: o.reps, style: { width: '64px' } }) : null;
    const noEval = o.evalIfAllEmpty != null ? FM.check('Do not evaluate if all referenced fields are empty', o.evalIfAllEmpty === false) : null;
    const stored = o.stored != null ? FM.check('Do not store calculation results — recalculate when needed', o.stored === false) : null;
    const status = h('div', { class: 'fm-calc-status' });
    const check = () => {
      const curCtx = ctxSel ? ctxSel.value : ctxTO;
      try {
        if (o.params) FM.calc.parse(ta.value, file.scope(curCtx, o.params));
        else file.check(ta.value, curCtx);
        status.className = 'fm-calc-status ok';
        const w = FM.app.activeWindow(file);
        if (!o.params && w && ta.value.trim() && w.to === curCtx) {
          let r; try { r = V.text(file.evaluate(ta.value, Object.assign(w.ctx(), { to: curCtx }), true)); } catch (e) { r = '?'; }
          status.textContent = 'Result for the current record: ' + (r.length > 120 ? r.slice(0, 120) + '…' : r);
        } else status.textContent = ta.value.trim() ? 'The calculation is valid.' : '';
        return true;
      } catch (e) {
        status.className = 'fm-calc-status bad';
        status.textContent = e.message;
        return e;
      }
    };
    ta.addEventListener('input', FM.debounce(check, 250));
    const body = h('div', { class: 'fm-calcdlg' },
      ctxSel ? h('div', { class: 'fm-row' }, h('span', { class: 'fm-row-l', text: 'Evaluate this calculation from the context of:' }), ctxSel) : null,
      h('div', { class: 'fm-calc-top' },
        h('div', { class: 'fm-col' }, toSel, fields),
        h('div', { class: 'fm-col fm-calc-mid' }, h('div', { class: 'fm-muted small', text: 'Operators' }), ops),
        h('div', { class: 'fm-col' }, view, fsearch, fns)),
      ta, status,
      h('div', { class: 'fm-calc-opts' },
        resType ? h('label', { class: 'fm-inline' }, 'Calculation result is ', resType) : null,
        reps ? h('label', { class: 'fm-inline' }, 'Number of repetitions: ', reps) : null,
        noEval, stored));
    return FM.modal({
      title: o.title || 'Specify Calculation', body, width: 860, className: 'fm-calc-modal',
      onOpen: () => { setTimeout(() => { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); check(); }, 30); },
      buttons: [{ label: 'Cancel', value: null, cancel: true }, {
        label: 'OK', primary: true,
        validate: async () => {
          if (!ta.value.trim() && !o.required) return true;
          const r = check();
          if (r === true) return true;
          await FM.alert(r.message, { icon: 'warn' });
          if (r.pos >= 0) { ta.focus(); ta.setSelectionRange(r.pos, r.pos + 1); }
          return false;
        },
        value: () => ({ formula: ta.value, resultType: resType ? resType.value : undefined, reps: reps ? Math.max(1, +reps.value || 1) : undefined, evalIfAllEmpty: noEval ? !noEval.input.checked : undefined, stored: stored ? !stored.input.checked : undefined, context: ctxSel ? ctxSel.value : undefined })
      }]
    });
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Manage Database
  // ═══════════════════════════════════════════════════════════════════════
  dlg.manageDatabase = async function (file, o) {
    o = o || {};
    if (!file.full) { await FM.alert('Your account does not have privileges to manage the database schema.', { icon: 'stopsign' }); return; }
    const lk = await file.lockKey('schema');
    if (!lk.ok) { await FM.alert('The database schema is being modified by "' + (lk.holder || 'another user') + '". Try again later.', { icon: 'stopsign' }); return; }
    const draft = { tables: FM.clone(file.schema.tables), tableOccurrences: FM.clone(file.schema.tableOccurrences), relationships: FM.clone(file.schema.relationships) };
    const serialEdits = {};
    // calculations written here must see the tables and fields not saved yet
    const draftFile = () => {
      const d = Object.create(file);
      d.tables = new Map(file.tables); d.memo = new Map(); d.relMemo = new Map(); d.idx = new Map(); d.editing = new Map();
      d.setSchema(Object.assign({}, file.schema, draft), file.version);
      return d;
    };
    const before = new Set(file.schema.tables.map(t => t.id));
    const beforeFields = new Map(file.schema.tables.map(t => [t.id, new Set(t.fields.map(f => f.id))]));
    const state = { table: (o.table && draft.tables.find(t => t.id === o.table) ? o.table : (draft.tables[0] || {}).id), field: null };
    const tabs = FM.tabs(['Tables', 'Fields', 'Relationships'], i => i === 0 ? tablesTab() : i === 1 ? fieldsTab() : relationshipsTab(), o.tab || 0);
    const body = h('div', { class: 'fm-mdb' }, tabs);

    function tablesTab() {
      const wrap = h('div', { class: 'fm-mdb-pane' });
      const tbl = h('table', { class: 'fm-grid' });
      const sel = h('div');
      const name = h('input', { class: 'fm-input', placeholder: 'Table Name' });
      const redraw = () => {
        tbl.innerHTML = '';
        tbl.appendChild(h('tr', null, h('th', { text: 'Table Name' }), h('th', { text: 'Fields' }), h('th', { text: 'Records' }), h('th', { text: 'Occurrences in Graph' })));
        draft.tables.forEach(t => {
          const r = h('tr', { class: state.table === t.id ? 'on' : '' }, h('td', { text: t.name }), h('td', { text: String(t.fields.length) }), h('td', { text: before.has(t.id) ? String(file.count(t.id)) : '0' }), h('td', { text: draft.tableOccurrences.filter(x => x.table === t.id).map(x => x.name).join(', ') }));
          r.addEventListener('click', () => { state.table = t.id; name.value = t.name; redraw(); });
          r.addEventListener('dblclick', () => { state.table = t.id; tabs.show(1); });
          tbl.appendChild(r);
        });
      };
      const create = () => {
        const n = name.value.trim();
        if (!n) return FM.alert('Type a name for the table.');
        if (draft.tables.some(t => t.name.toLowerCase() === n.toLowerCase())) return FM.alert('A table named "' + n + '" already exists.');
        const t = newTable(n);
        draft.tables.push(t);
        const toName = uniqueName(n, draft.tableOccurrences.map(x => x.name));
        draft.tableOccurrences.push({ id: FM.uid('O'), name: toName, table: t.id, x: 40 + (draft.tableOccurrences.length % 5) * 230, y: 40 + Math.floor(draft.tableOccurrences.length / 5) * 260, color: '#d5e3f7' });
        state.table = t.id; name.value = ''; redraw();
      };
      const change = () => {
        const t = draft.tables.find(x => x.id === state.table); const n = name.value.trim();
        if (!t || !n) return;
        if (draft.tables.some(x => x !== t && x.name.toLowerCase() === n.toLowerCase())) return FM.alert('A table named "' + n + '" already exists.');
        draft.tableOccurrences.filter(x => x.table === t.id && x.name === t.name).forEach(x => { x.name = uniqueName(n, draft.tableOccurrences.filter(y => y !== x).map(y => y.name)); });
        t.name = n; redraw();
      };
      const del = async () => {
        const t = draft.tables.find(x => x.id === state.table); if (!t) return;
        if (!(await FM.confirm('Are you sure you want to permanently delete the table "' + t.name + '"? All of its records, fields and table occurrences will be deleted.', { ok: 'Delete' }))) return;
        draft.tables = draft.tables.filter(x => x !== t);
        const gone = new Set(draft.tableOccurrences.filter(x => x.table === t.id).map(x => x.id));
        draft.tableOccurrences = draft.tableOccurrences.filter(x => !gone.has(x.id));
        draft.relationships = draft.relationships.filter(r => !gone.has(r.left) && !gone.has(r.right));
        state.table = (draft.tables[0] || {}).id; redraw();
      };
      redraw();
      wrap.append(h('div', { class: 'fm-mdb-info', text: draft.tables.length + ' table(s) defined in this file' }), h('div', { class: 'fm-scroll' }, tbl), sel,
        h('div', { class: 'fm-mdb-edit' }, h('label', { class: 'fm-inline' }, 'Table Name: ', name),
          h('button', { class: 'fm-btn', text: 'Create', onclick: create }), h('button', { class: 'fm-btn', text: 'Change', onclick: change }), h('button', { class: 'fm-btn', text: 'Delete', onclick: del })));
      name.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); create(); } });
      return wrap;
    }

    function fieldsTab() {
      const wrap = h('div', { class: 'fm-mdb-pane' });
      const tsel = FM.select(draft.tables.map(t => ({ value: t.id, label: t.name })), state.table);
      const tbl = h('table', { class: 'fm-grid' });
      const name = h('input', { class: 'fm-input', placeholder: 'Field Name' });
      const type = FM.select(TYPES.map(([v, l]) => ({ value: v, label: l })), 'text');
      const comment = h('input', { class: 'fm-input', placeholder: 'Comment' });
      const table = () => draft.tables.find(t => t.id === tsel.value);
      tsel.addEventListener('change', () => { state.table = tsel.value; state.field = null; redraw(); });
      const pick = f => { state.field = f.id; name.value = f.name; type.value = f.type; comment.value = f.comment || ''; redraw(); };
      const redraw = () => {
        tbl.innerHTML = '';
        const t = table();
        tbl.appendChild(h('tr', null, h('th', { text: 'Field Name' }), h('th', { text: 'Type' }), h('th', { text: 'Options / Comments' })));
        if (!t) return;
        t.fields.forEach(f => {
          const r = h('tr', { class: state.field === f.id ? 'on' : '' }, h('td', { text: f.name }), h('td', { text: typeLabel(f.type) }), h('td', { class: 'fm-muted', text: describeField(f, t) }));
          r.addEventListener('click', () => pick(f));
          r.addEventListener('dblclick', () => { pick(f); options(); });
          tbl.appendChild(r);
        });
      };
      const create = async () => {
        const t = table(); const n = name.value.trim();
        if (!t) return FM.alert('Create a table first.');
        if (!n) return FM.alert('Type a name for the field.');
        if (/::/.test(n)) return FM.alert('A field name cannot contain "::".');
        if (t.fields.some(f => f.name.toLowerCase() === n.toLowerCase())) return FM.alert('A field named "' + n + '" already exists in this table.');
        const f = { id: FM.uid('F'), name: n, type: type.value, comment: comment.value, options: {} };
        if (f.type === 'calculation') {
          const r = await dlg.calc(draftFile(), { formula: '', to: toOf(t), resultType: 'text', reps: 1, evalIfAllEmpty: true, stored: true, contextChoice: true, title: 'Specify Calculation for "' + n + '"' });
          if (!r) return;
          f.options.calc = { formula: r.formula, resultType: r.resultType, stored: r.stored, evalIfAllEmpty: r.evalIfAllEmpty, context: r.context };
          if (r.reps > 1) f.options.storage = { repetitions: r.reps };
        }
        if (f.type === 'summary') { const ok = await summaryOptions(f, t); if (!ok) return; }
        t.fields.push(f); state.field = f.id; name.value = ''; comment.value = ''; redraw();
        name.focus();
      };
      const change = async () => {
        const t = table(); const f = t && t.fields.find(x => x.id === state.field); const n = name.value.trim();
        if (!f || !n) return;
        if (t.fields.some(x => x !== f && x.name.toLowerCase() === n.toLowerCase())) return FM.alert('A field named "' + n + '" already exists in this table.');
        if (f.type !== type.value) {
          if (!(await FM.confirm('Changing the field type may lose or change data in "' + f.name + '". Continue?', { ok: 'Change' }))) return;
          f.type = type.value;
          if (f.type === 'calculation' && !(f.options || {}).calc) { f.options = f.options || {}; f.options.calc = { formula: '', resultType: 'text' }; }
          if (f.type === 'summary' && !(f.options || {}).summary) { f.options = f.options || {}; f.options.summary = { op: 'total', field: '' }; }
        }
        f.name = n; f.comment = comment.value; redraw();
      };
      const duplicate = () => {
        const t = table(); const f = t && t.fields.find(x => x.id === state.field); if (!f) return;
        const c = FM.clone(f); c.id = FM.uid('F'); c.name = uniqueName(f.name + ' Copy', t.fields.map(x => x.name));
        if (c.options && c.options.autoEnter && c.options.autoEnter.serial) c.options.autoEnter.serial = Object.assign({}, c.options.autoEnter.serial);
        t.fields.splice(t.fields.indexOf(f) + 1, 0, c); state.field = c.id; redraw();
      };
      const del = async () => {
        const t = table(); const f = t && t.fields.find(x => x.id === state.field); if (!f) return;
        const uses = fieldUses(file, draft, f);
        if (!(await FM.confirm('Are you sure you want to permanently delete the field "' + f.name + '"?' + (uses.length ? '\n\nIt is used in: ' + uses.slice(0, 6).join(', ') + (uses.length > 6 ? '…' : '') : ''), { ok: 'Delete' }))) return;
        t.fields = t.fields.filter(x => x !== f);
        draft.relationships.forEach(r => { r.predicates = (r.predicates || []).filter(p => p.leftField !== f.id && p.rightField !== f.id); });
        state.field = null; name.value = ''; redraw();
      };
      const options = async () => {
        const t = table(); const f = t && t.fields.find(x => x.id === state.field); if (!f) return;
        if (f.type === 'calculation') {
          const c = (f.options || {}).calc || {};
          const r = await dlg.calc(draftFile(), { formula: c.formula || '', to: c.context || toOf(t), resultType: c.resultType || 'text', reps: file.reps(f), evalIfAllEmpty: c.evalIfAllEmpty !== false, stored: c.stored !== false, contextChoice: true, context: c.context, title: 'Specify Calculation for "' + f.name + '"' });
          if (!r) return;
          f.options = f.options || {};
          f.options.calc = { formula: r.formula, resultType: r.resultType, stored: r.stored, evalIfAllEmpty: r.evalIfAllEmpty, context: r.context };
          f.options.storage = Object.assign({}, f.options.storage || {}, { repetitions: r.reps });
        } else if (f.type === 'summary') await summaryOptions(f, t);
        else await fieldOptions(draftFile(), draft, t, f, serialEdits);
        redraw();
      };
      name.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); if (state.field && table().fields.find(x => x.id === state.field && x.name === name.value.trim())) options(); else create(); } });
      redraw();
      wrap.append(h('div', { class: 'fm-mdb-info' }, 'Table: ', tsel, h('span', { class: 'fm-muted', text: '  ' + ((table() || {}).fields || []).length + ' field(s)' })), h('div', { class: 'fm-scroll' }, tbl),
        h('div', { class: 'fm-mdb-edit' }, h('label', { class: 'fm-inline' }, 'Field Name: ', name), h('label', { class: 'fm-inline' }, 'Type: ', type),
          h('button', { class: 'fm-btn', text: 'Create', onclick: create }), h('button', { class: 'fm-btn', text: 'Change', onclick: change }), h('button', { class: 'fm-btn', text: 'Duplicate', onclick: duplicate }), h('button', { class: 'fm-btn', text: 'Delete', onclick: del }), h('button', { class: 'fm-btn', text: 'Options…', onclick: options })),
        h('div', { class: 'fm-mdb-edit' }, h('label', { class: 'fm-inline', style: { flex: 1 } }, 'Comment: ', comment)));
      setTimeout(() => name.focus(), 50);
      return wrap;
    }
    function toOf(t) { const o2 = draft.tableOccurrences.find(x => x.table === t.id); return o2 ? o2.id : null; }
    async function summaryOptions(f, t) {
      const s = Object.assign({ op: 'total', field: '' }, (f.options || {}).summary || {});
      const ops = [['total', 'Total of'], ['average', 'Average of'], ['count', 'Count of'], ['min', 'Minimum'], ['max', 'Maximum'], ['stdev', 'Standard Deviation of'], ['fraction', 'Fraction of Total of'], ['list', 'List of']];
      const op = h('div', { class: 'fm-col' });
      ops.forEach(([v, l]) => { const r = h('input', { type: 'radio', name: 'sumop', value: v, checked: s.op === v }); op.appendChild(h('label', { class: 'fm-check' }, r, h('span', { text: l }))); });
      const flist = h('select', { class: 'fm-input fm-list', size: 10 });
      t.fields.filter(x => x.id !== f.id && x.type !== 'summary' && x.type !== 'container').forEach(x => flist.appendChild(h('option', { value: x.id, text: x.name })));
      flist.value = s.field;
      const running = FM.check('Running total / count', !!s.running);
      const restart = FM.select([{ value: '', label: '(do not restart)' }].concat(t.fields.map(x => ({ value: x.id, label: 'Restart for each sorted group of ' + x.name }))), s.restart || '');
      const pop = FM.check('By population (standard deviation)', !!s.population);
      const weight = FM.select([{ value: '', label: '(not weighted)' }].concat(t.fields.map(x => ({ value: x.id, label: 'Weighted by ' + x.name }))), s.weight || '');
      const sub = FM.select([{ value: '', label: '(of the found set)' }].concat(t.fields.map(x => ({ value: x.id, label: 'Subtotaled when sorted by ' + x.name }))), s.subtotal || '');
      const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-two' }, op, flist), running, restart, pop, h('label', { class: 'fm-inline' }, 'Average: ', weight), h('label', { class: 'fm-inline' }, 'Fraction: ', sub));
      const ok = await FM.modal({ title: 'Options for Summary Field "' + f.name + '"', body, width: 520, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', primary: true, value: true, validate: () => { if (!flist.value) { FM.alert('Choose the field to summarize.'); return false; } return true; } }] });
      if (!ok) return false;
      f.options = f.options || {};
      f.options.summary = { op: (op.querySelector('input:checked') || {}).value || 'total', field: flist.value, running: running.input.checked, restart: restart.value || undefined, population: pop.input.checked, weight: weight.value || undefined, subtotal: sub.value || undefined };
      return true;
    }

    function relationshipsTab() {
      const wrap = h('div', { class: 'fm-rg' });
      const canvas = h('div', { class: 'fm-rg-canvas' });
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('class', 'fm-rg-svg');
      canvas.appendChild(svg);
      let zoom = 1, selected = null;
      const tools = h('div', { class: 'fm-rg-tools' },
        h('button', { class: 'fm-iconbtn', title: 'Add a table occurrence', html: FM.icon('plus', 16), onclick: () => addTO() }),
        h('button', { class: 'fm-iconbtn', title: 'Add a relationship', html: FM.icon('relations', 16), onclick: () => editRel(null) }),
        h('button', { class: 'fm-iconbtn', title: 'Duplicate selected table occurrence', html: FM.icon('copy', 16), onclick: () => dupTO() }),
        h('button', { class: 'fm-iconbtn', title: 'Edit selected', html: FM.icon('gear', 16), onclick: () => { if (selected && selected.rel) editRel(selected.rel); else if (selected && selected.to) editTO(selected.to); } }),
        h('button', { class: 'fm-iconbtn', title: 'Delete selected', html: FM.icon('trash', 16), onclick: () => delSel() }),
        h('span', { class: 'fm-sep' }),
        h('button', { class: 'fm-iconbtn', title: 'Arrange in a grid', html: FM.icon('grid', 16), onclick: () => { draft.tableOccurrences.forEach((o2, i) => { o2.x = 30 + (i % 5) * 240; o2.y = 30 + Math.floor(i / 5) * 280; }); draw(); } }),
        h('button', { class: 'fm-iconbtn', title: 'Zoom out', html: FM.icon('minus', 16), onclick: () => { zoom = Math.max(0.4, zoom - 0.1); draw(); } }),
        h('button', { class: 'fm-iconbtn', title: 'Zoom in', html: FM.icon('plus', 16), onclick: () => { zoom = Math.min(1.5, zoom + 0.1); draw(); } }),
        h('span', { class: 'fm-sep' }),
        h('span', { class: 'fm-muted small', text: 'Drag from a field in one table to a field in another to relate them. Double-click a line to edit it.' }));
      const colors = ['#d5e3f7', '#d9f0dc', '#fde5c8', '#f3d6e7', '#e4dcf7', '#f5f0c8', '#d0eef0', '#e2e2e2'];
      const colorBar = h('div', { class: 'fm-rg-colors' }, colors.map(c => h('span', { style: { background: c }, title: 'Color of the selected table occurrence', onclick: () => { if (selected && selected.to) { selected.to.color = c; draw(); } } })));
      tools.appendChild(colorBar);
      wrap.append(tools, h('div', { class: 'fm-rg-scroll' }, canvas));
      function boxOf(o2) { return canvas.querySelector('[data-to="' + o2.id + '"]'); }
      function fieldY(o2, fid) {
        const box = boxOf(o2); if (!box) return o2.y + 12;
        const row = box.querySelector('[data-f="' + fid + '"]');
        const list = box.querySelector('.fm-rg-fields');
        if (!row) return o2.y + 12;
        const y = row.offsetTop - list.scrollTop + list.offsetTop + row.offsetHeight / 2;
        return o2.y + FM.clamp(y, 22, box.offsetHeight - 6);
      }
      function draw() {
        canvas.querySelectorAll('.fm-rg-box').forEach(b => b.remove());
        canvas.style.transform = 'scale(' + zoom + ')';
        const maxX = Math.max(1200, ...draft.tableOccurrences.map(o2 => o2.x + 260));
        const maxY = Math.max(800, ...draft.tableOccurrences.map(o2 => o2.y + 320));
        canvas.style.width = maxX + 'px'; canvas.style.height = maxY + 'px';
        svg.setAttribute('width', maxX); svg.setAttribute('height', maxY);
        draft.tableOccurrences.forEach(o2 => {
          const t = draft.tables.find(x => x.id === o2.table);
          const box = h('div', { class: 'fm-rg-box' + (selected && selected.to === o2 ? ' sel' : ''), dataset: { to: o2.id } });
          box.style.left = o2.x + 'px'; box.style.top = o2.y + 'px';
          const head = h('div', { class: 'fm-rg-head', style: { background: o2.color || '#d5e3f7' } }, h('span', { text: o2.name }), o2.name !== (t || {}).name ? h('small', { text: ' (' + ((t || {}).name || '?') + ')' }) : null);
          const list = h('div', { class: 'fm-rg-fields' });
          ((t || {}).fields || []).forEach(f => {
            const row = h('div', { class: 'fm-rg-field', dataset: { f: f.id }, title: typeLabel(f.type) }, h('span', { text: f.name }), h('small', { text: f.type === 'calculation' ? '=' : f.type === 'summary' ? 'Σ' : '' }));
            row.addEventListener('mousedown', e => startLink(e, o2, f));
            list.appendChild(row);
          });
          if (!((t || {}).fields || []).length) list.appendChild(h('div', { class: 'fm-rg-field fm-muted', text: '(no fields)' }));
          list.addEventListener('scroll', drawLines);
          box.append(head, list);
          head.addEventListener('mousedown', e => startMove(e, o2, box));
          head.addEventListener('dblclick', () => editTO(o2));
          canvas.appendChild(box);
        });
        drawLines();
      }
      function drawLines() {
        while (svg.firstChild) svg.removeChild(svg.firstChild);
        const ns = 'http://www.w3.org/2000/svg';
        draft.relationships.forEach(r => {
          const a = draft.tableOccurrences.find(x => x.id === r.left), b = draft.tableOccurrences.find(x => x.id === r.right);
          if (!a || !b) return;
          const p = (r.predicates || [])[0] || {};
          const ba = boxOf(a), bb = boxOf(b); if (!ba || !bb) return;
          const aw = ba.offsetWidth, bw = bb.offsetWidth;
          const leftOfB = a.x + aw / 2 < b.x + bw / 2;
          const x1 = leftOfB ? a.x + aw : a.x, x2 = leftOfB ? b.x : b.x + bw;
          const y1 = fieldY(a, p.leftField), y2 = fieldY(b, p.rightField);
          const mx = (x1 + x2) / 2;
          const path = document.createElementNS(ns, 'path');
          path.setAttribute('d', `M${x1},${y1} L${x1 + (leftOfB ? 14 : -14)},${y1} C${mx},${y1} ${mx},${y2} ${x2 + (leftOfB ? -14 : 14)},${y2} L${x2},${y2}`);
          path.setAttribute('class', 'fm-rg-line' + (selected && selected.rel === r ? ' sel' : ''));
          svg.appendChild(path);
          const hit = document.createElementNS(ns, 'path'); hit.setAttribute('d', path.getAttribute('d')); hit.setAttribute('class', 'fm-rg-hit');
          hit.addEventListener('mousedown', e => { e.stopPropagation(); selected = { rel: r }; drawLines(); canvas.querySelectorAll('.fm-rg-box.sel').forEach(x => x.classList.remove('sel')); });
          hit.addEventListener('dblclick', () => editRel(r));
          svg.appendChild(hit);
          const ops = (r.predicates || []).map(x => x.op);
          const label = document.createElementNS(ns, 'g');
          const rect = document.createElementNS(ns, 'rect'); rect.setAttribute('x', mx - 13); rect.setAttribute('y', (y1 + y2) / 2 - 9); rect.setAttribute('width', 26); rect.setAttribute('height', 18); rect.setAttribute('rx', 4); rect.setAttribute('class', 'fm-rg-op');
          const text = document.createElementNS(ns, 'text'); text.setAttribute('x', mx); text.setAttribute('y', (y1 + y2) / 2 + 4); text.setAttribute('text-anchor', 'middle'); text.textContent = ops.length > 1 ? ops.length + '' : (ops[0] || '?');
          label.append(rect, text); label.style.cursor = 'pointer';
          label.addEventListener('dblclick', () => editRel(r));
          label.addEventListener('mousedown', e => { e.stopPropagation(); selected = { rel: r }; drawLines(); });
          svg.appendChild(label);
        });
      }
      function startMove(e, o2, box) {
        e.preventDefault();
        selected = { to: o2 };
        canvas.querySelectorAll('.fm-rg-box.sel').forEach(x => x.classList.remove('sel')); box.classList.add('sel');
        const sx = e.clientX, sy = e.clientY, ox = o2.x, oy = o2.y;
        const mv = ev => { o2.x = Math.max(0, Math.round((ox + (ev.clientX - sx) / zoom) / 4) * 4); o2.y = Math.max(0, Math.round((oy + (ev.clientY - sy) / zoom) / 4) * 4); box.style.left = o2.x + 'px'; box.style.top = o2.y + 'px'; drawLines(); };
        const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); };
        document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
      }
      function startLink(e, o2, f) {
        e.preventDefault(); e.stopPropagation();
        const ns = 'http://www.w3.org/2000/svg';
        const ln = document.createElementNS(ns, 'line'); ln.setAttribute('class', 'fm-rg-drag');
        const cr = canvas.getBoundingClientRect();
        const sx = (e.clientX - cr.left) / zoom, sy = (e.clientY - cr.top) / zoom;
        ln.setAttribute('x1', sx); ln.setAttribute('y1', sy); ln.setAttribute('x2', sx); ln.setAttribute('y2', sy);
        svg.appendChild(ln);
        const mv = ev => { ln.setAttribute('x2', (ev.clientX - cr.left) / zoom); ln.setAttribute('y2', (ev.clientY - cr.top) / zoom); };
        const up = ev => {
          document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); ln.remove();
          const row = document.elementFromPoint(ev.clientX, ev.clientY);
          const fr = row && row.closest('.fm-rg-field'); const bx = row && row.closest('.fm-rg-box');
          if (!fr || !bx || bx.dataset.to === o2.id || !fr.dataset.f) return;
          const other = draft.tableOccurrences.find(x => x.id === bx.dataset.to);
          link(o2, f.id, other, fr.dataset.f);
        };
        document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
      }
      async function link(a, fa, b, fb) {
        let r = draft.relationships.find(x => (x.left === a.id && x.right === b.id) || (x.left === b.id && x.right === a.id));
        if (r) { const fl = r.left === a.id ? fa : fb, fr = r.left === a.id ? fb : fa; r.predicates.push({ leftField: fl, op: '=', rightField: fr }); draw(); return; }
        if (pathExists(a.id, b.id)) {
          const c = await FM.alert('A relationship between "' + a.name + '" and "' + b.name + '" would create a circular reference: they are already related through other table occurrences.\n\nAdd a new occurrence of "' + b.name + '" and relate to that instead?', { buttons: ['Add Occurrence', 'Cancel'], icon: 'warn' });
          if (c !== 1) return;
          const t = draft.tables.find(x => x.id === b.table);
          const nb = { id: FM.uid('O'), name: uniqueName(t.name + ' ' + a.name, draft.tableOccurrences.map(x => x.name)), table: b.table, x: b.x + 40, y: b.y + 60, color: b.color };
          draft.tableOccurrences.push(nb); b = nb;
        }
        draft.relationships.push({ id: FM.uid('R'), left: a.id, right: b.id, predicates: [{ leftField: fa, op: '=', rightField: fb }], leftOpts: {}, rightOpts: {} });
        draw();
      }
      function pathExists(a, b) {
        const adj = new Map(); draft.tableOccurrences.forEach(x => adj.set(x.id, []));
        draft.relationships.forEach(r => { if (adj.has(r.left) && adj.has(r.right)) { adj.get(r.left).push(r.right); adj.get(r.right).push(r.left); } });
        const seen = new Set([a]); const q = [a];
        while (q.length) { const c = q.shift(); if (c === b) return true; (adj.get(c) || []).forEach(n => { if (!seen.has(n)) { seen.add(n); q.push(n); } }); }
        return false;
      }
      async function addTO() {
        if (!draft.tables.length) return FM.alert('Create a table first (Tables tab).');
        const r = await editTOdlg({ table: draft.tables[0].id, name: '' });
        if (!r) return;
        draft.tableOccurrences.push({ id: FM.uid('O'), name: r.name, table: r.table, x: 60 + Math.random() * 300, y: 60 + Math.random() * 200, color: '#d5e3f7' });
        draw();
      }
      function dupTO() {
        if (!selected || !selected.to) return;
        const s = selected.to;
        draft.tableOccurrences.push({ id: FM.uid('O'), name: uniqueName(s.name + ' 2', draft.tableOccurrences.map(x => x.name)), table: s.table, x: s.x + 30, y: s.y + 30, color: s.color });
        draw();
      }
      async function editTO(o2) {
        const r = await editTOdlg(o2); if (!r) return;
        o2.name = r.name; o2.table = r.table; draw();
      }
      async function editTOdlg(o2) {
        const name = h('input', { class: 'fm-input', value: o2.name });
        const tsel = h('select', { class: 'fm-input fm-list', size: 8 }); draft.tables.forEach(t => tsel.appendChild(h('option', { value: t.id, text: t.name })));
        tsel.value = o2.table;
        tsel.addEventListener('change', () => { if (!name.value || draft.tables.some(t => t.name === name.value)) name.value = uniqueName(draft.tables.find(t => t.id === tsel.value).name, draft.tableOccurrences.filter(x => x !== o2).map(x => x.name)); });
        if (!o2.name) tsel.dispatchEvent(new Event('change'));
        return FM.modal({ title: 'Specify Table', body: h('div', { class: 'fm-form' }, h('div', { class: 'fm-muted small', text: 'Table' }), tsel, FM.row('Name', name)), width: 360,
          buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, validate: () => { const n = name.value.trim(); if (!n) { FM.alert('Enter a name.'); return false; } if (draft.tableOccurrences.some(x => x !== o2 && x.name.toLowerCase() === n.toLowerCase())) { FM.alert('That name is already used in the graph.'); return false; } return true; }, value: () => ({ name: name.value.trim(), table: tsel.value }) }] });
      }
      async function editRel(r) {
        const isNew = !r;
        const rr = r ? FM.clone(r) : { id: FM.uid('R'), left: (draft.tableOccurrences[0] || {}).id, right: (draft.tableOccurrences[1] || draft.tableOccurrences[0] || {}).id, predicates: [], leftOpts: {}, rightOpts: {} };
        const res = await relationshipDialog(draft, rr);
        if (!res) return;
        if (res === 'delete') { draft.relationships = draft.relationships.filter(x => x !== r); selected = null; draw(); return; }
        if (isNew) {
          if (draft.relationships.some(x => (x.left === res.left && x.right === res.right) || (x.left === res.right && x.right === res.left))) return FM.alert('These table occurrences are already related. Edit that relationship instead.');
          if (pathExists(res.left, res.right)) return FM.alert('These table occurrences are already connected through others; FileMaker does not allow circular relationships. Add another table occurrence first.');
          draft.relationships.push(res);
        } else Object.assign(r, res);
        draw();
      }
      function delSel() {
        if (!selected) return;
        if (selected.rel) draft.relationships = draft.relationships.filter(x => x !== selected.rel);
        if (selected.to) {
          const id = selected.to.id;
          if (draft.tableOccurrences.filter(x => x.table === selected.to.table).length === 1) { FM.alert('This is the only occurrence of its table. Delete the table on the Tables tab instead.'); return; }
          if (file.schema.layouts.some(l => l.to === id)) { FM.alert('A layout uses this table occurrence ("' + file.schema.layouts.find(l => l.to === id).name + '"). Change the layout first.'); return; }
          draft.tableOccurrences = draft.tableOccurrences.filter(x => x.id !== id);
          draft.relationships = draft.relationships.filter(x => x.left !== id && x.right !== id);
        }
        selected = null; draw();
      }
      canvas.addEventListener('mousedown', e => { if (e.target === canvas || e.target === svg) { selected = null; draw(); } });
      wrap.addEventListener('keydown', e => { if ((e.key === 'Delete' || e.key === 'Backspace') && e.target.tagName !== 'INPUT') { e.preventDefault(); delSel(); } });
      wrap.tabIndex = 0;
      setTimeout(draw, 0);
      return wrap;
    }

    const ok = await FM.modal({ title: 'Manage Database for "' + file.name + '"', body, width: 980, height: 640, className: 'fm-mdb-modal', enter: false, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    file.unlock(['schema']);
    if (!ok) return false;
    // new tables get a layout (as FileMaker does); new fields join "auto" layouts
    const ops = [{ op: 'section', name: 'database', value: draft }];
    const tmpFile = Object.create(file); tmpFile.schema = Object.assign({}, file.schema, draft);
    draft.tables.forEach(t => {
      if (!before.has(t.id)) {
        const to = draft.tableOccurrences.find(x => x.table === t.id);
        if (to && FM.design) { const lay = FM.design.autoLayout(tmpFile, { name: uniqueName(t.name, file.schema.layouts.map(l => l.name)), to: to.id, kind: 'form', keys: t.fields.filter(f => f.type !== 'summary').map(f => FM.fkey(to.id, f.id)) }); lay.autoAdd = true; ops.push({ op: 'upsert', coll: 'layouts', item: lay }); }
      } else {
        const added = t.fields.filter(f => !beforeFields.get(t.id).has(f.id));
        if (added.length && FM.design && (FM.app.prefs.addFieldsToLayout !== false)) {
          file.schema.layouts.filter(l => l.autoAdd && (draft.tableOccurrences.find(x => x.id === l.to) || {}).table === t.id).forEach(l => {
            ops.push({ op: 'upsert', coll: 'layouts', item: FM.design.appendFields(tmpFile, FM.clone(l), added.map(f => FM.fkey(l.to, f.id))) });
          });
        }
      }
    });
    try {
      await file.saveSchema(ops, Object.keys(serialEdits).length ? serialEdits : undefined);
      if (draft.tables.length && !file.schema.layouts.length) FM.toast('Add a layout with File > Manage > Layouts.');
      FM.app.windows.filter(w => w.file === file).forEach(w => { if (!w.layout) w.setLayout(w.defaultLayout(), { silent: true, noTrigger: true }).catch(() => { }); w.render(); });
      return true;
    } catch (e) { await FM.alert(e.message, { icon: 'warn' }); return false; }
  };
  function newTable(name) {
    return {
      id: FM.uid('T'), name, fields: [
        { id: FM.uid('F'), name: 'PrimaryKey', type: 'text', comment: 'Unique identifier of each record in this table', options: { autoEnter: { calc: 'Get ( UUID )', prohibit: true }, validation: { unique: true, notEmpty: true, when: 'always' } } },
        { id: FM.uid('F'), name: 'CreationTimestamp', type: 'timestamp', comment: 'Date and time each record was created', options: { autoEnter: { creation: 'timestamp' } } },
        { id: FM.uid('F'), name: 'CreatedBy', type: 'text', comment: 'Account name of the user who created each record', options: { autoEnter: { creation: 'account' } } },
        { id: FM.uid('F'), name: 'ModificationTimestamp', type: 'timestamp', comment: 'Date and time each record was last modified', options: { autoEnter: { modification: 'timestamp' } } },
        { id: FM.uid('F'), name: 'ModifiedBy', type: 'text', comment: 'Account name of the user who last modified each record', options: { autoEnter: { modification: 'account' } } }
      ]
    };
  }
  dlg.newTable = newTable;
  function uniqueName(base, taken) {
    const low = new Set(taken.map(x => String(x).toLowerCase()));
    if (!low.has(base.toLowerCase())) return base;
    let i = 2; while (low.has((base + ' ' + i).toLowerCase())) i++;
    return base + ' ' + i;
  }
  FM.uniqueName = uniqueName;
  function describeField(f, t) {
    const o = f.options || {}; const out = [];
    if (f.type === 'calculation') out.push('= ' + String((o.calc || {}).formula || '').replace(/\s+/g, ' ').slice(0, 60) + ((o.calc || {}).stored === false ? '  [Unstored]' : ''));
    if (f.type === 'summary') { const s = o.summary || {}; const src = t.fields.find(x => x.id === s.field); out.push(({ total: 'Total of', average: 'Average of', count: 'Count of', min: 'Minimum of', max: 'Maximum of', stdev: 'Standard Deviation of', fraction: 'Fraction of Total of', list: 'List of' }[s.op] || '') + ' ' + (src ? src.name : '?') + (s.running ? ' (running)' : '')); }
    const ae = o.autoEnter || {};
    if (ae.serial && ae.serial.on) out.push('Auto-enter Serial');
    if (ae.creation) out.push('Creation ' + ae.creation);
    if (ae.modification) out.push('Modification ' + ae.modification);
    if (ae.calc) out.push('Auto-enter Calc' + (ae.calcNoReplace ? '' : ' replaces existing value'));
    if (ae.data) out.push('Auto-enter Data "' + ae.data + '"');
    if (ae.lookup && ae.lookup.to) out.push('Lookup');
    if (ae.prohibit) out.push('Can\'t Modify Auto');
    const v = o.validation || {};
    ['notEmpty', 'unique', 'existing'].forEach(k => { if (v[k]) out.push({ notEmpty: 'Required Value', unique: 'Unique', existing: 'Existing' }[k]); });
    if (v.memberOf) out.push('From Value List'); if (v.range) out.push('In Range'); if (v.calc) out.push('Validated by Calc'); if (v.maxChars) out.push('Max ' + v.maxChars + ' chars');
    const st = o.storage || {};
    if (st.global) out.push('Global'); if ((st.repetitions || 1) > 1) out.push(st.repetitions + ' Repetitions');
    if (f.comment) out.push('— ' + f.comment);
    return out.join(', ');
  }
  function fieldUses(file, draft, f) {
    const out = [];
    draft.tables.forEach(t => t.fields.forEach(x => { if (x !== f && JSON.stringify(x.options || {}).includes(f.name)) out.push(t.name + '::' + x.name); }));
    file.schema.layouts.forEach(l => { if (FM.layoutFields(l).some(k => FM.pkey(k).fid === f.id)) out.push('layout "' + l.name + '"'); });
    file.schema.scripts.forEach(s => { if (JSON.stringify(s.steps || []).includes(f.id)) out.push('script "' + s.name + '"'); });
    return out;
  }

  // field options: Auto-Enter / Validation / Storage
  async function fieldOptions(file, draft, t, f, serialEdits) {
    f.options = f.options || {};
    const ae = Object.assign({}, f.options.autoEnter || {});
    const val = Object.assign({ when: 'always', allowOverride: true }, f.options.validation || {});
    const st = Object.assign({}, f.options.storage || {});
    const toId = (draft.tableOccurrences.find(x => x.table === t.id) || {}).id;
    const curSerial = (file.serials || {})[f.id];
    const tabs = FM.tabs(['Auto-Enter', 'Validation', 'Storage'], i => i === 0 ? autoTab() : i === 1 ? valTab() : storTab());
    function autoTab() {
      const w = h('div', { class: 'fm-form' });
      const cOn = FM.check('Creation', !!ae.creation); const cSel = FM.select([['date', 'Date'], ['time', 'Time'], ['timestamp', 'Timestamp'], ['name', 'Name'], ['account', 'Account Name']].map(([v, l]) => ({ value: v, label: l })), ae.creation || 'date');
      const mOn = FM.check('Modification', !!ae.modification); const mSel = FM.select([['date', 'Date'], ['time', 'Time'], ['timestamp', 'Timestamp'], ['name', 'Name'], ['account', 'Account Name']].map(([v, l]) => ({ value: v, label: l })), ae.modification || 'timestamp');
      const ser = ae.serial || {};
      const sOn = FM.check('Serial number', !!ser.on);
      const gen = FM.select([{ value: 'create', label: 'On creation' }, { value: 'commit', label: 'On commit' }], ser.generate || 'create');
      const next = h('input', { class: 'fm-input', style: { width: '90px' }, value: curSerial != null ? curSerial : (ser.next || '1') });
      const inc = h('input', { class: 'fm-input', style: { width: '60px' }, value: ser.increment || 1 });
      const last = FM.check('Value from last visited record', !!ae.lastVisited);
      const dOn = FM.check('Data:', ae.data != null && ae.data !== ''); const dIn = h('input', { class: 'fm-input', value: ae.data || '' });
      const calcOn = FM.check('Calculated value', !!ae.calc);
      const calcBtn = h('button', { class: 'fm-btn small', text: 'Specify…' });
      const noRep = FM.check('Do not replace existing value of field (if any)', ae.calcNoReplace !== false);
      const lkOn = FM.check('Looked-up value', !!(ae.lookup && ae.lookup.to));
      const lkBtn = h('button', { class: 'fm-btn small', text: 'Specify…' });
      const prohibit = FM.check('Prohibit modification of value during data entry', !!ae.prohibit);
      const calcText = h('div', { class: 'fm-mono small fm-muted', text: ae.calc || '' });
      calcBtn.onclick = async () => { const r = await dlg.calc(file, { formula: ae.calc || '', to: toId, title: 'Specify Calculation' }); if (r) { ae.calc = r.formula; calcText.textContent = r.formula; calcOn.input.checked = !!r.formula; } };
      lkBtn.onclick = async () => { const r = await lookupDialog(file, draft, toId, ae.lookup || {}); if (r) { ae.lookup = r; lkOn.input.checked = true; } };
      const sync = () => {
        ae.creation = cOn.input.checked ? cSel.value : undefined;
        ae.modification = mOn.input.checked ? mSel.value : undefined;
        ae.serial = sOn.input.checked ? { on: true, generate: gen.value, next: next.value, increment: Math.max(1, +inc.value || 1) } : undefined;
        if (sOn.input.checked && String(next.value) !== String(curSerial)) serialEdits[f.id] = next.value;
        ae.lastVisited = last.input.checked || undefined;
        ae.data = dOn.input.checked ? dIn.value : undefined;
        if (!calcOn.input.checked) ae.calc = undefined;
        ae.calcNoReplace = noRep.input.checked;
        if (!lkOn.input.checked) ae.lookup = undefined;
        ae.prohibit = prohibit.input.checked || undefined;
      };
      w.addEventListener('change', sync); w.addEventListener('input', sync);
      w.append(h('div', { class: 'fm-inline' }, cOn, cSel), h('div', { class: 'fm-inline' }, mOn, mSel),
        h('div', { class: 'fm-inline' }, sOn, ' Generate: ', gen, ' next value ', next, ' increment by ', inc),
        last, h('div', { class: 'fm-inline' }, dOn, dIn), h('div', { class: 'fm-inline' }, calcOn, calcBtn), calcText, noRep, h('div', { class: 'fm-inline' }, lkOn, lkBtn), prohibit);
      return w;
    }
    function valTab() {
      const w = h('div', { class: 'fm-form' });
      const always = h('input', { type: 'radio', name: 'vwhen', checked: val.when !== 'entry' }); const entry = h('input', { type: 'radio', name: 'vwhen', checked: val.when === 'entry' });
      const override = FM.check('Allow user to override during data entry', val.allowOverride !== false);
      const strictOn = FM.check('Strict data type:', !!val.strict); const strict = FM.select([['number', 'Numeric Only'], ['year4', '4-Digit Year Date'], ['time', 'Time of Day']].map(([v, l]) => ({ value: v, label: l })), val.strict || 'number');
      const notEmpty = FM.check('Not empty', !!val.notEmpty), unique = FM.check('Unique value', !!val.unique), existing = FM.check('Existing value', !!val.existing);
      const memOn = FM.check('Member of value list:', !!val.memberOf); const mem = FM.select([{ value: '', label: '—' }].concat(file.schema.valueLists.map(v => ({ value: v.id, label: v.name }))), val.memberOf || '');
      const rngOn = FM.check('In range:', !!val.range); const from = h('input', { class: 'fm-input', style: { width: '90px' }, value: (val.range || {}).from || '' }); const to = h('input', { class: 'fm-input', style: { width: '90px' }, value: (val.range || {}).to || '' });
      const calcOn = FM.check('Validated by calculation', !!val.calc); const calcBtn = h('button', { class: 'fm-btn small', text: 'Specify…' }); const calcText = h('div', { class: 'fm-mono small fm-muted', text: val.calc || '' });
      const maxOn = FM.check('Maximum number of characters:', !!val.maxChars); const max = h('input', { class: 'fm-input', type: 'number', style: { width: '70px' }, value: val.maxChars || 255 });
      const msgOn = FM.check('Display custom message if validation fails', !!val.message); const msg = h('textarea', { class: 'fm-input', rows: 2 }); msg.value = val.message || '';
      calcBtn.onclick = async () => { const r = await dlg.calc(file, { formula: val.calc || '', to: toId, title: 'Specify Calculation' }); if (r) { val.calc = r.formula; calcText.textContent = r.formula; calcOn.input.checked = !!r.formula; } };
      const sync = () => {
        val.when = entry.checked ? 'entry' : 'always'; val.allowOverride = override.input.checked;
        val.strict = strictOn.input.checked ? strict.value : undefined;
        val.notEmpty = notEmpty.input.checked || undefined; val.unique = unique.input.checked || undefined; val.existing = existing.input.checked || undefined;
        val.memberOf = memOn.input.checked && mem.value ? mem.value : undefined;
        val.range = rngOn.input.checked ? { from: from.value, to: to.value } : undefined;
        if (!calcOn.input.checked) val.calc = undefined;
        val.maxChars = maxOn.input.checked ? +max.value || 255 : undefined;
        val.message = msgOn.input.checked ? msg.value : undefined;
      };
      w.addEventListener('change', sync); w.addEventListener('input', sync);
      w.append(h('div', { class: 'fm-inline' }, 'Validate data in this field: ', h('label', { class: 'fm-check' }, always, h('span', { text: 'Always' })), h('label', { class: 'fm-check' }, entry, h('span', { text: 'Only during data entry' }))), override,
        h('div', { class: 'fm-muted small', text: 'Require:' }), h('div', { class: 'fm-inline' }, strictOn, strict), notEmpty, unique, existing, h('div', { class: 'fm-inline' }, memOn, mem),
        h('div', { class: 'fm-inline' }, rngOn, from, ' to ', to), h('div', { class: 'fm-inline' }, calcOn, calcBtn), calcText, h('div', { class: 'fm-inline' }, maxOn, max), msgOn, msg);
      return w;
    }
    function storTab() {
      const w = h('div', { class: 'fm-form' });
      const glob = FM.check('Use global storage (one value for all records)', !!st.global);
      const gval = h('input', { class: 'fm-input', placeholder: 'Initial value', value: st.globalValue || '' });
      const reps = h('input', { class: 'fm-input', type: 'number', min: 1, max: 1000, style: { width: '70px' }, value: st.repetitions || 1 });
      const sync = () => { st.global = glob.input.checked || undefined; st.globalValue = gval.value || undefined; st.repetitions = Math.max(1, +reps.value || 1); };
      w.addEventListener('change', sync); w.addEventListener('input', sync);
      w.append(h('b', { text: 'Global Storage' }), glob, h('div', { class: 'fm-inline' }, 'Initial value: ', gval), h('div', { class: 'fm-muted small', text: 'Global values are kept for each signed-in session, as when a file is hosted.' }),
        h('b', { text: 'Repeating' }), h('div', { class: 'fm-inline' }, 'Maximum number of repetitions: ', reps),
        h('b', { text: 'Indexing' }), h('div', { class: 'fm-muted small', text: 'Indexes are built automatically for relationships, value lists and finds.' }));
      return w;
    }
    const ok = await FM.modal({ title: 'Options for Field "' + f.name + '"', body: tabs, width: 600, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    if (!ok) { delete serialEdits[f.id]; return; }
    const clean = o => { const r = {}; for (const k in o) if (o[k] !== undefined && o[k] !== false && o[k] !== '') r[k] = o[k]; return r; };
    f.options.autoEnter = clean(ae); if (ae.calc && ae.calcNoReplace === false) f.options.autoEnter.calcNoReplace = false; else if (ae.calc) f.options.autoEnter.calcNoReplace = true;
    f.options.validation = clean(val); if (val.allowOverride === false) f.options.validation.allowOverride = false;
    if (!Object.keys(f.options.validation).filter(k => k !== 'when' && k !== 'allowOverride').length) delete f.options.validation;
    f.options.storage = clean(st);
  }
  async function lookupDialog(file, draft, startTO, lk) {
    const starting = file.to(startTO) || draft.tableOccurrences.find(x => x.id === startTO);
    const rel = draft.tableOccurrences.filter(x => x.id !== startTO);
    const toSel = FM.select(rel.map(x => ({ value: x.id, label: x.name })), lk.to || (rel[0] || {}).id);
    const flist = h('select', { class: 'fm-input fm-list', size: 8 });
    const fill = () => { flist.innerHTML = ''; const t = draft.tables.find(x => x.id === (draft.tableOccurrences.find(y => y.id === toSel.value) || {}).table); (t ? t.fields : []).forEach(f => flist.appendChild(h('option', { value: f.id, text: f.name }))); if (lk.field) flist.value = lk.field; };
    toSel.addEventListener('change', fill); fill();
    const nm = FM.select([['nothing', 'Do not copy'], ['lower', 'Copy next lower value'], ['higher', 'Copy next higher value'], ['constant', 'Use:']].map(([v, l]) => ({ value: v, label: l })), lk.noMatch || 'nothing');
    const constant = h('input', { class: 'fm-input', value: lk.constant || '' });
    const dce = FM.check('Don\'t copy contents if empty', !!lk.dontCopyEmpty);
    const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-muted', text: 'Starting with table: ' + ((starting || {}).name || '?') }), FM.row('Lookup from related table', toSel), h('div', { class: 'fm-muted small', text: 'Copy value from field:' }), flist, FM.row('If no exact match', nm, constant), dce);
    return FM.modal({ title: 'Lookup Options', body, width: 460, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, value: () => ({ to: toSel.value, field: flist.value, noMatch: nm.value, constant: constant.value, dontCopyEmpty: dce.input.checked }) }] });
  }
  async function relationshipDialog(draft, r) {
    const toOpts = draft.tableOccurrences.map(x => ({ value: x.id, label: x.name }));
    const lsel = FM.select(toOpts, r.left), rsel = FM.select(toOpts, r.right);
    const lf = h('select', { class: 'fm-input fm-list', size: 8 }), rf = h('select', { class: 'fm-input fm-list', size: 8 });
    const op = FM.select(['=', '≠', '<', '≤', '>', '≥', '×'].map(x => ({ value: x, label: x })), '=');
    const fieldsOf = toId => { const t = draft.tables.find(x => x.id === (draft.tableOccurrences.find(y => y.id === toId) || {}).table); return t ? t.fields : []; };
    const fill = (sel, list) => { list.innerHTML = ''; fieldsOf(sel.value).forEach(f => list.appendChild(h('option', { value: f.id, text: f.name }))); };
    lsel.addEventListener('change', () => { fill(lsel, lf); r.predicates = []; drawPreds(); }); rsel.addEventListener('change', () => { fill(rsel, rf); r.predicates = []; drawPreds(); });
    fill(lsel, lf); fill(rsel, rf);
    const preds = h('table', { class: 'fm-grid' });
    let psel = -1;
    const fname = (toId, fid) => (fieldsOf(toId).find(f => f.id === fid) || {}).name || '?';
    const drawPreds = () => {
      preds.innerHTML = '';
      preds.appendChild(h('tr', null, h('th', { text: (draft.tableOccurrences.find(x => x.id === lsel.value) || {}).name }), h('th', { text: '' }), h('th', { text: (draft.tableOccurrences.find(x => x.id === rsel.value) || {}).name })));
      r.predicates.forEach((p, i) => { const tr = h('tr', { class: i === psel ? 'on' : '' }, h('td', { text: fname(lsel.value, p.leftField) }), h('td', { text: p.op }), h('td', { text: fname(rsel.value, p.rightField) })); tr.onclick = () => { psel = i; lf.value = p.leftField; rf.value = p.rightField; op.value = p.op; drawPreds(); }; preds.appendChild(tr); });
    };
    drawPreds();
    const add = () => { if (!lf.value || !rf.value) return FM.alert('Choose a field on each side.'); r.predicates.push({ leftField: lf.value, op: op.value, rightField: rf.value }); psel = r.predicates.length - 1; drawPreds(); };
    const change = () => { if (psel < 0) return; r.predicates[psel] = { leftField: lf.value, op: op.value, rightField: rf.value }; drawPreds(); };
    const del = () => { if (psel < 0) return; r.predicates.splice(psel, 1); psel = -1; drawPreds(); };
    const side = (opts, label) => {
      opts = opts || {};
      const cr = FM.check('Allow creation of records in this table via this relationship', !!opts.create);
      const dl = FM.check('Delete related records in this table when a record is deleted in the other table', !!opts.delete);
      const so = FM.check('Sort records', !!(opts.sort && opts.sort.length));
      const sb = h('button', { class: 'fm-btn small', text: 'Specify…' });
      let sortSpec = opts.sort || [];
      sb.onclick = async () => { const toId = label === 'L' ? lsel.value : rsel.value; const res = await dlg.sortDialog(null, (sortSpec || []).map(s => ({ key: FM.fkey(toId, s.fid), dir: s.dir })), { draft, to: toId, store: true, relationship: true }); if (res) { sortSpec = res.map(s => ({ fid: FM.pkey(s.key).fid, dir: s.dir === 'desc' ? 'desc' : 'asc' })); so.input.checked = sortSpec.length > 0; } };
      const box = h('div', { class: 'fm-col fm-relside' }, cr, dl, h('div', { class: 'fm-inline' }, so, sb));
      box.get = () => ({ create: cr.input.checked, delete: dl.input.checked, sort: so.input.checked ? sortSpec : [] });
      return box;
    };
    const ls = side(r.leftOpts, 'L'), rs = side(r.rightOpts, 'R');
    const body = h('div', { class: 'fm-form fm-reldlg' },
      h('div', { class: 'fm-two' }, h('div', { class: 'fm-col' }, h('b', { text: 'Table' }), lsel, lf), h('div', { class: 'fm-col', style: { justifyContent: 'center', alignItems: 'center' } }, op, h('button', { class: 'fm-btn small', text: 'Add', onclick: add }), h('button', { class: 'fm-btn small', text: 'Change', onclick: change }), h('button', { class: 'fm-btn small', text: 'Delete', onclick: del })), h('div', { class: 'fm-col' }, h('b', { text: 'Table' }), rsel, rf)),
      preds, h('div', { class: 'fm-two' }, ls, rs));
    const res = await FM.modal({ title: 'Edit Relationship', body, width: 760, buttons: [{ label: 'Delete Relationship', value: 'delete', danger: true }, { label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, validate: () => { if (lsel.value === rsel.value) { FM.alert('A table occurrence cannot be related to itself. Add another occurrence of the table.'); return false; } if (!r.predicates.length) { FM.alert('Add at least one pair of match fields.'); return false; } return true; }, value: () => Object.assign({}, r, { left: lsel.value, right: rsel.value, leftOpts: ls.get(), rightOpts: rs.get() }) }] });
    return res;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Value lists
  // ═══════════════════════════════════════════════════════════════════════
  dlg.manageValueLists = async function (file) {
    const lists = FM.clone(file.schema.valueLists);
    let sel = lists[0] ? lists[0].id : null;
    const tbl = h('table', { class: 'fm-grid' });
    const draw = () => {
      tbl.innerHTML = '';
      tbl.appendChild(h('tr', null, h('th', { text: 'Value List Name' }), h('th', { text: 'Source' }), h('th', { text: 'Values' })));
      lists.forEach(v => { const tr = h('tr', { class: v.id === sel ? 'on' : '' }, h('td', { text: v.name }), h('td', { text: v.type === 'field' ? 'Field' : 'Custom' }), h('td', { class: 'fm-muted', text: v.type === 'field' ? file.fullName((v.field || {}).key || '') : (v.values || []).join(', ').slice(0, 80) })); tr.onclick = () => { sel = v.id; draw(); }; tr.ondblclick = () => edit(v); tbl.appendChild(tr); });
    };
    const edit = async v => {
      const isNew = !v;
      const w = v ? FM.clone(v) : { id: FM.uid('V'), name: uniqueName('Value List', lists.map(x => x.name)), type: 'custom', values: [] };
      const r = await editValueList(file, w);
      if (!r) return;
      if (isNew) lists.push(r); else Object.assign(v, r);
      sel = r.id; draw();
    };
    draw();
    const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-scroll', style: { height: '300px' } }, tbl), h('div', { class: 'fm-inline' },
      h('button', { class: 'fm-btn', text: 'New…', onclick: () => edit(null) }), h('button', { class: 'fm-btn', text: 'Edit…', onclick: () => { const v = lists.find(x => x.id === sel); if (v) edit(v); } }),
      h('button', { class: 'fm-btn', text: 'Duplicate', onclick: () => { const v = lists.find(x => x.id === sel); if (v) { const c = FM.clone(v); c.id = FM.uid('V'); c.name = uniqueName(v.name + ' Copy', lists.map(x => x.name)); lists.push(c); draw(); } } }),
      h('button', { class: 'fm-btn', text: 'Delete', onclick: async () => { const v = lists.find(x => x.id === sel); if (v && await FM.confirm('Delete the value list "' + v.name + '"?', { ok: 'Delete' })) { lists.splice(lists.indexOf(v), 1); sel = null; draw(); } } })));
    const ok = await FM.modal({ title: 'Manage Value Lists for "' + file.name + '"', body, width: 640, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    if (!ok) return;
    const ops = [];
    lists.forEach(v => { const old = file.valueList(v.id); if (!old || JSON.stringify(old) !== JSON.stringify(v)) ops.push({ op: 'upsert', coll: 'valueLists', item: v }); });
    file.schema.valueLists.forEach(v => { if (!lists.some(x => x.id === v.id)) ops.push({ op: 'delete', coll: 'valueLists', id: v.id }); });
    if (ops.length) { try { await file.saveSchema(ops); } catch (e) { FM.alert(e.message, { icon: 'warn' }); } }
  };
  async function editValueList(file, v) {
    const name = h('input', { class: 'fm-input', value: v.name });
    const useField = h('input', { type: 'radio', name: 'vlsrc', checked: v.type === 'field' });
    const useCustom = h('input', { type: 'radio', name: 'vlsrc', checked: v.type !== 'field' });
    const custom = h('textarea', { class: 'fm-input', rows: 10, placeholder: 'One value per line. Use - on its own line for a divider.' });
    custom.value = (v.values || []).join('\n');
    const fdesc = h('span', { class: 'fm-muted', text: v.field && v.field.key ? file.fullName(v.field.key) : '' });
    const fbtn = h('button', { class: 'fm-btn small', text: 'Specify fields…', onclick: async () => { const r = await valueListFields(file, v.field || {}); if (r) { v.field = r; fdesc.textContent = file.fullName(r.key) + (r.key2 ? ' / ' + file.fullName(r.key2) : '') + (r.related ? ' (related values only)' : ''); useField.checked = true; } } });
    const body = h('div', { class: 'fm-form' }, FM.row('Value List Name', name), h('label', { class: 'fm-check' }, useField, h('span', { text: 'Use values from field: ' })), h('div', { class: 'fm-inline' }, fbtn, fdesc), h('label', { class: 'fm-check' }, useCustom, h('span', { text: 'Use custom values' })), custom);
    return FM.modal({ title: 'Edit Value List', body, width: 520, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, validate: () => { if (!name.value.trim()) { FM.alert('Enter a name.'); return false; } if (useField.checked && !(v.field && v.field.key)) { FM.alert('Specify the field the values come from.'); return false; } return true; }, value: () => ({ id: v.id, name: name.value.trim(), type: useField.checked ? 'field' : 'custom', values: useField.checked ? [] : custom.value.split('\n').map(x => x.replace(/\r/g, '')).filter(x => x !== ''), field: useField.checked ? v.field : undefined }) }] });
  }
  async function valueListFields(file, cur) {
    const to1 = FM.select(file.schema.tableOccurrences.map(o => ({ value: o.id, label: o.name })), cur.key ? FM.pkey(cur.key).to : (file.schema.tableOccurrences[0] || {}).id);
    const f1 = h('select', { class: 'fm-input fm-list', size: 8 }), f2 = h('select', { class: 'fm-input fm-list', size: 8 });
    const fill = () => { const t = file.tableOfTO(to1.value); [f1, f2].forEach(s => { s.innerHTML = ''; (t ? t.fields : []).forEach(f => s.appendChild(h('option', { value: FM.fkey(to1.value, f.id), text: f.name }))); }); if (cur.key) f1.value = cur.key; if (cur.key2) f2.value = cur.key2; };
    to1.addEventListener('change', fill); fill();
    const also = FM.check('Also display values from second field', !!cur.key2);
    const only2 = FM.check('Show values only from second field', !!cur.showOnly2);
    const all = h('input', { type: 'radio', name: 'vlinc', checked: !cur.related }), rel = h('input', { type: 'radio', name: 'vlinc', checked: !!cur.related });
    const from = FM.select(file.schema.tableOccurrences.map(o => ({ value: o.id, label: o.name })), cur.fromTO || '');
    const sortBy = FM.select([{ value: 1, label: 'First field' }, { value: 2, label: 'Second field' }], cur.sortBy || 1);
    const body = h('div', { class: 'fm-form' }, FM.row('Table', to1), h('div', { class: 'fm-two' }, h('div', { class: 'fm-col' }, h('b', { text: 'Use values from first field' }), f1), h('div', { class: 'fm-col' }, also, f2, only2)),
      h('label', { class: 'fm-check' }, all, h('span', { text: 'Include all values' })), h('div', { class: 'fm-inline' }, h('label', { class: 'fm-check' }, rel, h('span', { text: 'Include only related values starting from: ' })), from), FM.row('Sort values using', sortBy));
    return FM.modal({ title: 'Specify Fields for Value List', body, width: 560, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, value: () => ({ key: f1.value, key2: also.input.checked ? f2.value : undefined, showOnly2: also.input.checked && only2.input.checked, related: rel.checked, fromTO: rel.checked ? from.value : undefined, sortBy: +sortBy.value }) }] });
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Custom functions
  // ═══════════════════════════════════════════════════════════════════════
  dlg.manageCustomFunctions = async function (file) {
    if (!file.full) { await FM.alert('Only a [Full Access] account can manage custom functions.', { icon: 'stopsign' }); return; }
    const cfs = FM.clone(file.schema.customFunctions);
    let sel = cfs[0] ? cfs[0].id : null;
    const tbl = h('table', { class: 'fm-grid' });
    const draw = () => { tbl.innerHTML = ''; tbl.appendChild(h('tr', null, h('th', { text: 'Name' }), h('th', { text: 'Parameters' }), h('th', { text: 'Formula' }))); cfs.forEach(c => { const tr = h('tr', { class: c.id === sel ? 'on' : '' }, h('td', { text: c.name }), h('td', { text: (c.params || []).join('; ') }), h('td', { class: 'fm-mono fm-muted', text: String(c.formula || '').slice(0, 70) })); tr.onclick = () => { sel = c.id; draw(); }; tr.ondblclick = () => edit(c); tbl.appendChild(tr); }); };
    const edit = async c => {
      const isNew = !c; const w = c ? FM.clone(c) : { id: FM.uid('C'), name: 'NewFunction', params: [], formula: '' };
      const name = h('input', { class: 'fm-input fm-mono', value: w.name });
      const params = h('input', { class: 'fm-input fm-mono', value: (w.params || []).join(' ; '), placeholder: 'param1 ; param2' });
      const formula = h('textarea', { class: 'fm-input fm-mono', rows: 10 }); formula.value = w.formula || '';
      const status = h('div', { class: 'fm-calc-status' });
      const check = () => { const ps = params.value.split(/[;,]/).map(x => x.trim()).filter(Boolean); try { file.schema.customFunctions = cfs.filter(x => x.id !== w.id).concat([{ id: w.id, name: name.value.trim(), params: ps, formula: formula.value }]); file.setSchema(file.schema, file.version); FM.calc.parse(formula.value, file.scope((file.schema.tableOccurrences[0] || {}).id, ps)); status.className = 'fm-calc-status ok'; status.textContent = 'The function is valid.'; return true; } catch (e) { status.className = 'fm-calc-status bad'; status.textContent = e.message; return false; } };
      const saved = FM.clone(file.schema.customFunctions);
      formula.addEventListener('input', FM.debounce(check, 300)); params.addEventListener('input', FM.debounce(check, 300));
      const body = h('div', { class: 'fm-form' }, FM.row('Function Name', name), FM.row('Function Parameters', params), h('div', { class: 'fm-muted small', text: 'Formula (use the parameter names like fields; the function may call itself):' }), formula, status);
      const r = await FM.modal({ title: 'Edit Custom Function', body, width: 640, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, validate: () => { if (!/^[A-Za-z_][A-Za-z0-9_.]*$/.test(name.value.trim())) { FM.alert('A function name must start with a letter and contain only letters, digits, _ and .'); return false; } if (FM.calc.LIB[name.value.trim().toLowerCase()]) { FM.alert('That name is already a built-in function.'); return false; } return check(); }, value: () => ({ id: w.id, name: name.value.trim(), params: params.value.split(/[;,]/).map(x => x.trim()).filter(Boolean), formula: formula.value }) }] });
      file.schema.customFunctions = saved; file.setSchema(file.schema, file.version);
      if (!r) return;
      if (isNew) cfs.push(r); else Object.assign(c, r);
      sel = r.id; draw();
    };
    draw();
    const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-scroll', style: { height: '300px' } }, tbl), h('div', { class: 'fm-inline' }, h('button', { class: 'fm-btn', text: 'New…', onclick: () => edit(null) }), h('button', { class: 'fm-btn', text: 'Edit…', onclick: () => { const c = cfs.find(x => x.id === sel); if (c) edit(c); } }), h('button', { class: 'fm-btn', text: 'Delete', onclick: async () => { const c = cfs.find(x => x.id === sel); if (c && await FM.confirm('Delete "' + c.name + '"?', { ok: 'Delete' })) { cfs.splice(cfs.indexOf(c), 1); draw(); } } })));
    const ok = await FM.modal({ title: 'Manage Custom Functions for "' + file.name + '"', body, width: 680, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    if (ok) { try { await file.saveSchema([{ op: 'section', name: 'customFunctions', value: cfs }]); } catch (e) { FM.alert(e.message, { icon: 'warn' }); } }
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Security
  // ═══════════════════════════════════════════════════════════════════════
  dlg.security = async function (file) {
    if (!file.full) { await FM.alert('Only a [Full Access] account can manage security.', { icon: 'stopsign' }); return; }
    let accounts;
    try { accounts = (await file.api('GET', '/accounts')).accounts; } catch (e) { await FM.alert(e.message, { icon: 'warn' }); return; }
    const sets = FM.clone(file.schema.privilegeSets);
    const exts = FM.clone(file.schema.extendedPrivileges || []);
    const acctOps = [];
    const tabs = FM.tabs(['Accounts', 'Privilege Sets', 'Extended Privileges'], i => i === 0 ? acctTab() : i === 1 ? setsTab() : extTab());
    function acctTab() {
      const w = h('div', { class: 'fm-form' }); let sel = null;
      const tbl = h('table', { class: 'fm-grid' });
      const draw = () => {
        tbl.innerHTML = ''; tbl.appendChild(h('tr', null, h('th', { text: 'Active' }), h('th', { text: 'Account' }), h('th', { text: 'Type' }), h('th', { text: 'Privilege Set' }), h('th', { text: 'Password' })));
        accounts.forEach(a => { const tr = h('tr', { class: a === sel ? 'on' : '' }, h('td', { text: a.active ? '✓' : '' }), h('td', { text: a.name }), h('td', { text: 'FileMaker' }), h('td', { text: (sets.find(s => s.id === a.privilegeSet) || {}).name || '?' }), h('td', { class: 'fm-muted', text: a.hasPassword ? '••••••' : '(none)' + (a.mustChange ? ' · must change' : '') })); tr.onclick = () => { sel = a; draw(); }; tr.ondblclick = () => edit(a); tbl.appendChild(tr); });
      };
      const edit = async a => {
        const isNew = !a; const x = a ? Object.assign({}, a) : { name: '', privilegeSet: 'PS_ENTRY', active: true };
        const name = h('input', { class: 'fm-input', value: x.name });
        const pw = h('input', { class: 'fm-input', type: 'password', placeholder: isNew ? 'Password' : 'Leave blank to keep the current password' });
        const must = FM.check('User must change password on next sign in', !!x.mustChange);
        const act = FM.select([{ value: '1', label: 'Active' }, { value: '0', label: 'Inactive' }], x.active ? '1' : '0');
        const ps = FM.select(sets.map(s => ({ value: s.id, label: s.name })), x.privilegeSet);
        const desc = h('input', { class: 'fm-input', value: x.description || '' });
        const clearPw = isNew ? null : FM.check('Remove the password (allow sign in with no password)', false);
        const body = h('div', { class: 'fm-form' }, FM.row('Account Name', name), FM.row('Password', pw), clearPw, must, FM.row('Account Status', act), FM.row('Privilege Set', ps), FM.row('Description', desc));
        const r = await FM.modal({ title: isNew ? 'New Account' : 'Edit Account', body, width: 480, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, validate: () => { if (!name.value.trim()) { FM.alert('Enter an account name.'); return false; } if (accounts.some(y => y !== a && y.name.toLowerCase() === name.value.trim().toLowerCase())) { FM.alert('That account name is already used.'); return false; } return true; }, value: true }] });
        if (!r) return;
        const op = { op: isNew ? 'add' : 'update', id: x.id, name: name.value.trim(), privilegeSet: ps.value, active: act.value === '1', mustChange: must.input.checked, description: desc.value };
        if (pw.value) op.password = pw.value; else if (clearPw && clearPw.input.checked) op.password = ''; else if (isNew) op.password = '';
        try { accounts = (await file.api('POST', '/accounts', { ops: [op] })).accounts; } catch (e) { FM.alert(e.message, { icon: 'warn' }); }
        draw();
      };
      const del = async () => {
        if (!sel) return;
        if (!(await FM.confirm('Delete the account "' + sel.name + '"?', { ok: 'Delete' }))) return;
        try { accounts = (await file.api('POST', '/accounts', { ops: [{ op: 'delete', id: sel.id }] })).accounts; sel = null; } catch (e) { FM.alert(e.message, { icon: 'warn' }); }
        draw();
      };
      draw();
      w.append(h('div', { class: 'fm-muted small', text: 'Accounts sign in to this file. Changes to accounts are saved immediately.' }), h('div', { class: 'fm-scroll', style: { height: '320px' } }, tbl),
        h('div', { class: 'fm-inline' }, h('button', { class: 'fm-btn', text: 'New…', onclick: () => edit(null) }), h('button', { class: 'fm-btn', text: 'Edit…', onclick: () => sel && edit(sel) }), h('button', { class: 'fm-btn', text: 'Delete', onclick: del })));
      return w;
    }
    function setsTab() {
      const w = h('div', { class: 'fm-form' }); let sel = null;
      const tbl = h('table', { class: 'fm-grid' });
      const draw = () => {
        tbl.innerHTML = ''; tbl.appendChild(h('tr', null, h('th', { text: 'Privilege Set' }), h('th', { text: 'Active accounts' }), h('th', { text: 'Description' })));
        sets.forEach(s => { const tr = h('tr', { class: s === sel ? 'on' : '' }, h('td', { text: s.name }), h('td', { text: String(accounts.filter(a => a.privilegeSet === s.id && a.active).length) }), h('td', { class: 'fm-muted', text: s.description || '' })); tr.onclick = () => { sel = s; draw(); }; tr.ondblclick = () => edit(s); tbl.appendChild(tr); });
      };
      const edit = async s => {
        if (s && s.builtin) { await FM.alert('"' + s.name + '" is built in and cannot be changed (assign its extended privileges on the Extended Privileges tab). Duplicate it to make an editable copy.'); return; }
        const isNew = !s;
        const x = s ? FM.clone(s) : { id: FM.uid('P'), name: 'New Privilege Set', description: '', records: { mode: 'all_view', tables: {} }, layouts: { mode: 'all_view', items: {} }, valueLists: { mode: 'all_view', items: {} }, scripts: { mode: 'all_exec', items: {} }, extended: ['fmapp'], printing: true, exporting: true, idleDisconnect: true, modifyOwnPassword: true, menus: 'editing' };
        const r = await editPrivilegeSet(file, x, exts);
        if (!r) return;
        if (isNew) sets.push(r); else Object.assign(s, r);
        sel = r; draw();
      };
      draw();
      w.append(h('div', { class: 'fm-scroll', style: { height: '320px' } }, tbl), h('div', { class: 'fm-inline' },
        h('button', { class: 'fm-btn', text: 'New…', onclick: () => edit(null) }), h('button', { class: 'fm-btn', text: 'Edit…', onclick: () => sel && edit(sel) }),
        h('button', { class: 'fm-btn', text: 'Duplicate', onclick: () => { if (!sel) return; const c = FM.clone(sel); c.id = FM.uid('P'); c.builtin = undefined; c.name = uniqueName(sel.name.replace(/^\[|\]$/g, '') + ' Copy', sets.map(y => y.name)); sets.push(c); sel = c; draw(); } }),
        h('button', { class: 'fm-btn', text: 'Delete', onclick: async () => { if (!sel || sel.builtin) return; if (accounts.some(a => a.privilegeSet === sel.id)) { FM.alert('Accounts still use this privilege set.'); return; } if (await FM.confirm('Delete "' + sel.name + '"?', { ok: 'Delete' })) { sets.splice(sets.indexOf(sel), 1); sel = null; draw(); } } })));
      return w;
    }
    function extTab() {
      const w = h('div', { class: 'fm-form' });
      const tbl = h('table', { class: 'fm-grid' });
      tbl.appendChild(h('tr', null, h('th', { text: 'Keyword' }), h('th', { text: 'Description' }), ...sets.map(s => h('th', { text: s.name }))));
      exts.forEach(e => {
        tbl.appendChild(h('tr', null, h('td', { class: 'fm-mono', text: e.key }), h('td', { text: e.name }), ...sets.map(s => { const c = h('input', { type: 'checkbox', checked: (s.extended || []).includes(e.key), disabled: s.id === 'PS_FULL' && e.key === 'fmapp' }); c.onchange = () => { s.extended = (s.extended || []).filter(k => k !== e.key); if (c.checked) s.extended.push(e.key); }; return h('td', null, c); })));
      });
      w.append(h('div', { class: 'fm-muted small', text: 'A privilege set needs "Access via FileMaker Network" (fmapp) to open this hosted file. Items marked (planned) are kept for compatibility and take effect when those features arrive.' }), h('div', { class: 'fm-scroll', style: { height: '320px' } }, tbl));
      return w;
    }
    const ok = await FM.modal({ title: 'Manage Security for "' + file.name + '"', body: tabs, width: 860, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    if (!ok) return;
    try { await file.saveSchema([{ op: 'section', name: 'privilegeSets', value: sets }]); FM.toast('Security settings saved.'); }
    catch (e) { await FM.alert(e.message, { icon: 'warn' }); }
    void acctOps;
  };
  async function editPrivilegeSet(file, x, exts) {
    const name = h('input', { class: 'fm-input', value: x.name });
    const desc = h('input', { class: 'fm-input', value: x.description || '' });
    const rec = FM.select([['all_ced', 'Create, edit, and delete in all tables'], ['all_ce', 'Create and edit in all tables'], ['all_view', 'View only in all tables'], ['none', 'All no access'], ['custom', 'Custom privileges…']].map(([v, l]) => ({ value: v, label: l })), x.records.mode);
    const lay = FM.select([['all_modify', 'All modifiable'], ['all_view', 'All view only'], ['none', 'All no access'], ['custom', 'Custom privileges…']].map(([v, l]) => ({ value: v, label: l })), x.layouts.mode);
    const vls = FM.select([['all_modify', 'All modifiable'], ['all_view', 'All view only'], ['none', 'All no access'], ['custom', 'Custom privileges…']].map(([v, l]) => ({ value: v, label: l })), x.valueLists.mode);
    const scr = FM.select([['all_modify', 'All modifiable'], ['all_exec', 'All executable only'], ['none', 'All no access'], ['custom', 'Custom privileges…']].map(([v, l]) => ({ value: v, label: l })), x.scripts.mode);
    rec.onchange = async () => { if (rec.value === 'custom') { const r = await customRecordPrivs(file, x.records.tables || {}); if (r) x.records.tables = r; else rec.value = x.records.mode; } x.records.mode = rec.value; };
    lay.onchange = async () => { if (lay.value === 'custom') { const r = await customItems(file, 'layouts', x.layouts); if (r) Object.assign(x.layouts, r); else lay.value = x.layouts.mode; } x.layouts.mode = lay.value; };
    vls.onchange = async () => { if (vls.value === 'custom') { const r = await customItems(file, 'valueLists', x.valueLists); if (r) Object.assign(x.valueLists, r); else vls.value = x.valueLists.mode; } x.valueLists.mode = vls.value; };
    scr.onchange = async () => { if (scr.value === 'custom') { const r = await customItems(file, 'scripts', x.scripts); if (r) Object.assign(x.scripts, r); else scr.value = x.scripts.mode; } x.scripts.mode = scr.value; };
    const ext = h('div', { class: 'fm-col fm-scroll', style: { maxHeight: '150px' } }, exts.map(e => { const c = FM.check(e.name + ' (' + e.key + ')', (x.extended || []).includes(e.key)); c.input.onchange = () => { x.extended = (x.extended || []).filter(k => k !== e.key); if (c.input.checked) x.extended.push(e.key); }; return c; }));
    const opts = [['printing', 'Allow printing'], ['exporting', 'Allow exporting'], ['manageExtended', 'Manage extended privileges'], ['overrideValidation', 'Allow user to override data validation warnings'], ['idleDisconnect', 'Disconnect user from server when idle'], ['modifyOwnPassword', 'Allow user to modify their own password']].map(([k, l]) => { const c = FM.check(l, !!x[k]); c.input.onchange = () => { x[k] = c.input.checked; }; return c; });
    const menus = FM.select([['all', 'All'], ['editing', 'Editing only'], ['minimum', 'Minimum']].map(([v, l]) => ({ value: v, label: l })), x.menus || 'all');
    menus.onchange = () => { x.menus = menus.value; };
    const body = h('div', { class: 'fm-form' }, FM.row('Privilege Set Name', name), FM.row('Description', desc),
      h('div', { class: 'fm-two' },
        h('div', { class: 'fm-col' }, h('b', { text: 'Data Access and Design' }), FM.row('Records', rec), FM.row('Layouts', lay), FM.row('Value Lists', vls), FM.row('Scripts', scr), h('b', { text: 'Extended Privileges' }), ext),
        h('div', { class: 'fm-col' }, h('b', { text: 'Other Privileges' }), ...opts, FM.row('Available menu commands', menus))));
    return FM.modal({ title: 'Edit Privilege Set', body, width: 820, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, validate: () => { if (!name.value.trim()) { FM.alert('Enter a name.'); return false; } return true; }, value: () => Object.assign(x, { name: name.value.trim(), description: desc.value }) }] });
  }
  async function customRecordPrivs(file, tables) {
    tables = FM.clone(tables || {});
    const tbl = h('table', { class: 'fm-grid' });
    let sel = file.schema.tables[0] ? file.schema.tables[0].id : null;
    const get = tid => tables[tid] || (tables[tid] = { view: 'yes', edit: 'yes', create: 'yes', delete: 'yes', fields: 'all' });
    const draw = () => {
      tbl.innerHTML = ''; tbl.appendChild(h('tr', null, ...['Table Name', 'View', 'Edit', 'Create', 'Delete', 'Field Access'].map(t => h('th', { text: t }))));
      file.schema.tables.forEach(t => { const p = get(t.id); const tr = h('tr', { class: t.id === sel ? 'on' : '' }, h('td', { text: t.name }), h('td', { text: p.view }), h('td', { text: p.edit }), h('td', { text: p.create }), h('td', { text: p.delete }), h('td', { text: p.fields === 'all' ? 'all' : 'limited' })); tr.onclick = () => { sel = t.id; draw(); paint(); }; tbl.appendChild(tr); });
    };
    const ctl = h('div', { class: 'fm-inline' });
    const paint = () => {
      ctl.innerHTML = ''; if (!sel) return;
      const p = get(sel); const t = file.table(sel);
      const mk = (k, allowLimited) => { const s = FM.select([{ value: 'yes', label: 'yes' }, { value: 'no', label: 'no' }].concat(allowLimited ? [{ value: 'limited', label: 'limited…' }] : []), p[k]); s.onchange = async () => { if (s.value === 'limited') { const r = await dlg.calc(file, { formula: p[k + 'Calc'] || '', to: (file.baseTO(sel) || {}).id, title: 'Records the set may ' + k + ' (the host checks this)' }); if (!r || !r.formula.trim()) { s.value = p[k]; return; } p[k + 'Calc'] = r.formula; } p[k] = s.value; draw(); }; return h('label', { class: 'fm-inline' }, k[0].toUpperCase() + k.slice(1) + ' ', s); };
      const fa = FM.select([{ value: 'all', label: 'all modifiable' }, { value: 'limited', label: 'limited…' }], p.fields === 'all' ? 'all' : 'limited');
      fa.onchange = async () => {
        if (fa.value === 'all') { p.fields = 'all'; draw(); return; }
        const cur = p.fields === 'all' ? {} : Object.assign({}, p.fields);
        const rows = t.fields.map(f => { const s = FM.select([['modify', 'modifiable'], ['view', 'view only'], ['none', 'no access']].map(([v, l]) => ({ value: v, label: l })), cur[f.id] || 'modify'); s.onchange = () => { cur[f.id] = s.value; }; return h('tr', null, h('td', { text: f.name }), h('td', null, s)); });
        const ok = await FM.modal({ title: 'Custom Field Privileges — ' + t.name, body: h('div', { class: 'fm-scroll', style: { maxHeight: '420px' } }, h('table', { class: 'fm-grid' }, rows)), width: 460, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
        if (ok) p.fields = cur; else fa.value = p.fields === 'all' ? 'all' : 'limited';
        draw();
      };
      ctl.append(mk('view', true), mk('edit', true), mk('create', false), mk('delete', true), h('label', { class: 'fm-inline' }, 'Field Access ', fa));
    };
    draw(); paint();
    const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-scroll', style: { height: '260px' } }, tbl), ctl, h('div', { class: 'fm-muted small', text: '"limited" uses a calculation the host evaluates for every record. It may use the record\'s own fields, Get(AccountName), Get(AccountPrivilegeSetName), Get(UserName), IsEmpty, PatternCount, If, Case, comparisons and and/or/not.' }));
    const ok = await FM.modal({ title: 'Custom Record Privileges', body, width: 780, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    return ok ? tables : null;
  }
  async function customItems(file, coll, cur) {
    const items = FM.clone(cur.items || {});
    const list = coll === 'layouts' ? file.schema.layouts : coll === 'scripts' ? FM.orderedScripts(file).filter(s => !s.folder && !s.separator) : file.schema.valueLists;
    const opts = coll === 'scripts' ? [['modify', 'modifiable'], ['exec', 'executable only'], ['none', 'no access']] : [['modify', 'modifiable'], ['view', 'view only'], ['none', 'no access']];
    const allowNew = FM.check('Allow creation of new ' + (coll === 'layouts' ? 'layouts' : coll === 'scripts' ? 'scripts' : 'value lists'), !!cur.allowNew);
    const rows = list.map(it => {
      const v = coll === 'layouts' ? ((items[it.id] || {}).layout || 'modify') : (items[it.id] || (coll === 'scripts' ? 'exec' : 'view'));
      const s = FM.select(opts.map(([a, b]) => ({ value: a, label: b })), v);
      const cells = [h('td', { text: it.name }), h('td', null, s)];
      let r2;
      if (coll === 'layouts') { r2 = FM.select([{ value: 'modify', label: 'records modifiable' }, { value: 'view', label: 'records view only' }], (items[it.id] || {}).records || 'modify'); cells.push(h('td', null, r2)); }
      const sync = () => { items[it.id] = coll === 'layouts' ? { layout: s.value, records: r2.value } : s.value; };
      s.onchange = sync; if (r2) r2.onchange = sync; sync();
      return h('tr', null, cells);
    });
    const body = h('div', { class: 'fm-form' }, allowNew, h('div', { class: 'fm-scroll', style: { maxHeight: '400px' } }, h('table', { class: 'fm-grid' }, rows)));
    const ok = await FM.modal({ title: 'Custom ' + (coll === 'layouts' ? 'Layout' : coll === 'scripts' ? 'Script' : 'Value List') + ' Privileges', body, width: 560, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    return ok ? { items, allowNew: allowNew.input.checked } : null;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Sort
  // ═══════════════════════════════════════════════════════════════════════
  dlg.sortDialog = function (win, spec, o) {
    o = o || {};
    const file = win ? win.file : o.file || (o.draft ? null : null);
    const fileRef = win ? win.file : (o.file || FM.app.activeFile());
    const draft = o.draft;
    const ctxTO = o.to || (win ? win.to : null);
    let order = (spec || []).map(s => Object.assign({}, s));
    const tos = draft ? draft.tableOccurrences : fileRef.schema.tableOccurrences;
    const tablesOf = toId => { const t0 = tos.find(x => x.id === toId); return draft ? draft.tables.find(t => t.id === (t0 || {}).table) : fileRef.table((t0 || {}).table); };
    const nameOf = key => { const k = FM.pkey(key); const t = tablesOf(k.to); const f = t && t.fields.find(x => x.id === k.fid); const toName = (tos.find(x => x.id === k.to) || {}).name; return f ? (k.to === ctxTO ? f.name : toName + '::' + f.name) : '?'; };
    const toSel = draft ? FM.select([{ value: ctxTO, label: (tos.find(x => x.id === ctxTO) || {}).name || '' }], ctxTO) : toSelect(fileRef, ctxTO, ctxTO);
    const flist = h('select', { class: 'fm-input fm-list', size: 14 });
    const fill = () => { flist.innerHTML = ''; const t = tablesOf(toSel.value); (t ? t.fields : []).filter(f => f.type !== 'container').forEach(f => flist.appendChild(h('option', { value: FM.fkey(toSel.value, f.id), text: f.name }))); };
    toSel.addEventListener('change', fill); fill();
    const olist = h('select', { class: 'fm-input fm-list', size: 14 });
    const drawOrder = keep => { const i = olist.selectedIndex; olist.innerHTML = ''; order.forEach(s => olist.appendChild(h('option', { value: s.key, text: nameOf(s.key) + '  ' + (s.dir === 'desc' ? '▼' : s.dir === 'vl' ? '≡' : '▲') }))); if (keep) olist.selectedIndex = i; };
    drawOrder();
    const asc = h('input', { type: 'radio', name: 'sdir', checked: true }), desc = h('input', { type: 'radio', name: 'sdir' }), byvl = h('input', { type: 'radio', name: 'sdir', disabled: !fileRef || !fileRef.schema.valueLists.length });
    const vlSel = FM.select((fileRef ? fileRef.schema.valueLists : []).map(v => ({ value: v.id, label: v.name })), '');
    const curDir = () => desc.checked ? 'desc' : byvl.checked ? 'vl' : 'asc';
    const move = () => { if (!flist.value || order.some(s => s.key === flist.value)) return; order.push({ key: flist.value, dir: curDir(), vl: byvl.checked ? vlSel.value : undefined }); drawOrder(); };
    flist.addEventListener('dblclick', move);
    olist.addEventListener('change', () => { const s = order[olist.selectedIndex]; if (!s) return; asc.checked = s.dir === 'asc' || !s.dir; desc.checked = s.dir === 'desc'; byvl.checked = s.dir === 'vl'; if (s.vl) vlSel.value = s.vl; });
    [asc, desc, byvl, vlSel].forEach(c => c.addEventListener('change', () => { const s = order[olist.selectedIndex]; if (!s) return; s.dir = curDir(); s.vl = byvl.checked ? vlSel.value : undefined; drawOrder(true); }));
    olist.addEventListener('dblclick', () => { order.splice(olist.selectedIndex, 1); drawOrder(); });
    const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-sortdlg' },
      h('div', { class: 'fm-col' }, toSel, flist),
      h('div', { class: 'fm-col fm-sort-mid' }, h('button', { class: 'fm-btn small', text: 'Move →', onclick: move }), h('button', { class: 'fm-btn small', text: 'Clear All', onclick: () => { order = []; drawOrder(); } }), h('button', { class: 'fm-btn small', text: '← Clear', onclick: () => { if (olist.selectedIndex >= 0) { order.splice(olist.selectedIndex, 1); drawOrder(); } } }),
        h('button', { class: 'fm-btn small', text: '↑', onclick: () => { const i = olist.selectedIndex; if (i > 0) { [order[i - 1], order[i]] = [order[i], order[i - 1]]; drawOrder(); olist.selectedIndex = i - 1; } } }), h('button', { class: 'fm-btn small', text: '↓', onclick: () => { const i = olist.selectedIndex; if (i >= 0 && i < order.length - 1) { [order[i + 1], order[i]] = [order[i], order[i + 1]]; drawOrder(); olist.selectedIndex = i + 1; } } })),
      h('div', { class: 'fm-col' }, h('div', { class: 'fm-muted small', text: 'Sort Order' }), olist)),
      h('div', { class: 'fm-inline' }, h('label', { class: 'fm-check' }, asc, h('span', { text: 'Ascending order' })), h('label', { class: 'fm-check' }, desc, h('span', { text: 'Descending order' })), h('label', { class: 'fm-check' }, byvl, h('span', { text: 'Custom order based on value list' })), vlSel));
    const buttons = [{ label: 'Cancel', value: null, cancel: true }];
    if (!o.store) buttons.unshift({ label: 'Unsort', value: () => [] });
    buttons.push({ label: o.store ? 'OK' : 'Sort', primary: true, value: () => order });
    void file;
    return FM.modal({ title: o.store ? 'Specify Sort Order' : 'Sort Records', body, width: 720, buttons }).then(r => {
      if (r && !r.length && !o.store && win) { const s = win.set_(); s.sort = null; win.render(); return null; }
      return r;
    });
  };

  // ═══════════════════════════════════════════════════════════════════════
  // stored find requests (for script steps)
  // ═══════════════════════════════════════════════════════════════════════
  dlg.findRequests = async function (file, requests, to) {
    let reqs = FM.clone(requests || []);
    let sel = 0;
    const tbl = h('table', { class: 'fm-grid' });
    const draw = () => { tbl.innerHTML = ''; tbl.appendChild(h('tr', null, h('th', { text: 'Action' }), h('th', { text: 'Criteria' }))); reqs.forEach((r, i) => { const tr = h('tr', { class: i === sel ? 'on' : '' }, h('td', { text: r.omit ? 'Omit Records' : 'Find Records' }), h('td', { text: Object.entries(r.crit).map(([k, v]) => file.fullName(k) + ': [' + v + ']').join('; ') })); tr.onclick = () => { sel = i; draw(); }; tr.ondblclick = () => edit(i); tbl.appendChild(tr); }); };
    const edit = async i => {
      const r = i == null ? { omit: false, crit: {} } : FM.clone(reqs[i]);
      const act = FM.select([{ value: 'find', label: 'Find Records' }, { value: 'omit', label: 'Omit Records' }], r.omit ? 'omit' : 'find');
      const list = h('table', { class: 'fm-grid' });
      const drawC = () => { list.innerHTML = ''; list.appendChild(h('tr', null, h('th', { text: 'Field' }), h('th', { text: 'Criteria' }), h('th'))); Object.entries(r.crit).forEach(([k, v]) => list.appendChild(h('tr', null, h('td', { text: file.fullName(k) }), h('td', { class: 'fm-mono', text: v }), h('td', null, h('button', { class: 'fm-iconbtn', html: FM.icon('x', 12), onclick: () => { delete r.crit[k]; drawC(); } }))))); };
      drawC();
      const toSel = toSelect(file, to, to);
      const fl = h('select', { class: 'fm-input fm-list', size: 8 });
      const fill = () => { fl.innerHTML = ''; const t = file.tableOfTO(toSel.value); (t ? t.fields : []).forEach(f => fl.appendChild(h('option', { value: FM.fkey(toSel.value, f.id), text: f.name }))); };
      toSel.onchange = fill; fill();
      const crit = h('input', { class: 'fm-input fm-mono', placeholder: 'e.g. Smith, >100, 1/1/2025...12/31/2025, =, * or $variable' });
      const ops = FM.select([{ value: '', label: 'Insert operator…' }].concat(FIND_OPS.map(([v, l]) => ({ value: v, label: l }))), '');
      ops.onchange = () => { if (ops.value) { crit.setRangeText(ops.value, crit.selectionStart, crit.selectionEnd, 'end'); crit.focus(); } ops.value = ''; };
      const body = h('div', { class: 'fm-form' }, FM.row('Action', act), list, h('div', { class: 'fm-two' }, h('div', { class: 'fm-col' }, toSel, fl), h('div', { class: 'fm-col' }, h('div', { class: 'fm-muted small', text: 'Criteria (literal text; a $variable name uses its value)' }), crit, ops, h('button', { class: 'fm-btn', text: 'Add', onclick: () => { if (fl.value && crit.value) { r.crit[fl.value] = crit.value; crit.value = ''; drawC(); } } }))));
      const ok = await FM.modal({ title: 'Edit Find Request', body, width: 640, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
      if (!ok) return;
      r.omit = act.value === 'omit';
      if (i == null) { reqs.push(r); sel = reqs.length - 1; } else reqs[i] = r;
      draw();
    };
    draw();
    const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-scroll', style: { height: '220px' } }, tbl), h('div', { class: 'fm-inline' }, h('button', { class: 'fm-btn', text: 'New…', onclick: () => edit(null) }), h('button', { class: 'fm-btn', text: 'Edit…', onclick: () => reqs[sel] && edit(sel) }), h('button', { class: 'fm-btn', text: 'Duplicate', onclick: () => { if (reqs[sel]) { reqs.splice(sel + 1, 0, FM.clone(reqs[sel])); draw(); } } }), h('button', { class: 'fm-btn', text: 'Delete', onclick: () => { reqs.splice(sel, 1); sel = Math.max(0, sel - 1); draw(); } })));
    return FM.modal({ title: 'Specify Find Requests', body, width: 640, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, value: () => reqs }] });
  };
  const FIND_OPS = [['<', '< less than'], ['≤', '≤ less than or equal'], ['>', '> greater than'], ['≥', '≥ greater than or equal'], ['=', '= exact match'], ['==', '== match entire field'], ['...', '... range'], ['!', '! duplicates'], ['//', '// today\'s date'], ['?', '? invalid date or time'], ['@', '@ one character'], ['#', '# one digit'], ['*', '* zero or more characters'], ['\\', '\\ literal next character'], ['""', '"" match phrase'], ['~', '~ relaxed search']];
  FM.FIND_OPS = FIND_OPS;

  // ═══════════════════════════════════════════════════════════════════════
  // Custom dialog spec (Show Custom Dialog)
  // ═══════════════════════════════════════════════════════════════════════
  dlg.customDialogSpec = async function (file, spec, to) {
    const s = Object.assign({ title: '"Title"', message: '"Message"', buttons: [{ label: '"OK"', commit: true }, { label: '"Cancel"', commit: false }, { label: '', commit: false }], inputs: [] }, FM.clone(spec || {}));
    while (s.buttons.length < 3) s.buttons.push({ label: '', commit: false });
    while (s.inputs.length < 3) s.inputs.push({});
    const calcIn = (v, ph) => { const i = h('input', { class: 'fm-input fm-mono', value: v || '', placeholder: ph || 'calculation' }); return i; };
    const title = calcIn(s.title), msg = h('textarea', { class: 'fm-input fm-mono', rows: 3 }); msg.value = s.message || '';
    const btns = s.buttons.map((b, i) => { const l = calcIn(b.label, 'Button ' + (i + 1) + ' label (calculation)'); const c = FM.check('Commit data', b.commit !== false && i === 0 || !!b.commit); return { l, c }; });
    const ins = s.inputs.map((inp, i) => {
      const mode = FM.select([{ value: '', label: '(none)' }, { value: 'field', label: 'Field' }, { value: 'var', label: 'Variable' }], inp.field ? 'field' : inp.var ? 'var' : '');
      const fb = h('button', { class: 'fm-btn small', text: inp.field ? file.fullName(inp.field) : 'Specify field…' }); let fkey = inp.field || '';
      fb.onclick = async () => { const k = await dlg.pickField(file, { to }); if (k) { fkey = k; fb.textContent = file.fullName(k); } };
      const vn = h('input', { class: 'fm-input', value: inp.var || '', placeholder: '$name' });
      const label = calcIn(inp.label, 'Label (calculation)');
      const pw = FM.check('Use password character (*)', !!inp.password);
      const row = h('div', { class: 'fm-inline' }, 'Input ' + (i + 1) + ': ', mode, fb, vn, label, pw);
      const sync = () => { fb.style.display = mode.value === 'field' ? '' : 'none'; vn.style.display = mode.value === 'var' ? '' : 'none'; label.style.display = pw.style.display = mode.value ? '' : 'none'; };
      mode.onchange = sync; sync();
      return { row, get: () => mode.value === 'field' && fkey ? { field: fkey, label: label.value, password: pw.input.checked } : mode.value === 'var' && vn.value ? { var: vn.value, label: label.value, password: pw.input.checked } : null };
    });
    const body = h('div', { class: 'fm-form' }, FM.row('Title', title), h('div', { class: 'fm-muted small', text: 'Message (calculation)' }), msg,
      h('b', { text: 'Buttons (right to left: default button first)' }), ...btns.map((b, i) => h('div', { class: 'fm-inline' }, 'Button ' + (i + 1) + ': ', b.l, b.c)),
      h('b', { text: 'Input fields' }), ...ins.map(x => x.row));
    return FM.modal({ title: 'Show Custom Dialog Options', body, width: 760, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, value: () => ({ title: title.value, message: msg.value, buttons: btns.map(b => ({ label: b.l.value, commit: b.c.input.checked })).filter(b => b.label), inputs: ins.map(x => x.get()).filter(Boolean) }) }] });
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Import
  // ═══════════════════════════════════════════════════════════════════════
  async function readSource(file, f) {
    const name = f.name.toLowerCase();
    if (/\.xlsx?$/.test(name)) {
      if (/\.xls$/.test(name)) throw new FMError(802, 'Old .xls workbooks are not supported. Save it as .xlsx and try again.');
      const fd = new FormData(); fd.append('file', f);
      const r = await FM.api('POST', '/xlsx/parse', fd);
      let sheet = r.sheets[0];
      if (r.sheets.length > 1) {
        const s = FM.select(r.sheets.map((x, i) => ({ value: i, label: x.name + ' (' + x.rows.length + ' rows)' })), 0);
        const i = await FM.modal({ title: 'Specify Excel Data', body: h('div', { class: 'fm-form' }, h('div', { text: 'Show worksheet:' }), s), width: 400, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, value: () => +s.value }] });
        if (i == null) throw new FMError(1);
        sheet = r.sheets[i];
      }
      return { rows: sheet ? sheet.rows : [], header: true };
    }
    const text = await FM.readText(f);
    if (/\.xml$/.test(name) || /^\s*<\?xml|<FMPXMLRESULT/i.test(text.slice(0, 300))) return parseFMPXML(text);
    if (/\.json$/.test(name) || /^\s*[[{]/.test(text.slice(0, 20))) {
      let data; try { data = JSON.parse(text); } catch (e) { throw new FMError(802, 'That JSON file could not be read: ' + e.message); }
      if (!Array.isArray(data)) data = data.records || data.data || [data];
      const keys = []; data.forEach(o => Object.keys(o || {}).forEach(k => { if (!keys.includes(k)) keys.push(k); }));
      return { rows: [keys].concat(data.map(o => keys.map(k => o[k] == null ? '' : typeof o[k] === 'object' ? JSON.stringify(o[k]) : String(o[k])))), header: true };
    }
    const sep = /\.(tab|tsv)$/.test(name) ? '\t' : /\.(csv|mer)$/.test(name) ? ',' : null;
    return { rows: FM.parseDelimited(text, sep), header: /\.mer$/.test(name) };
  }
  function parseFMPXML(text) {
    const doc = new DOMParser().parseFromString(text, 'application/xml');
    if (doc.querySelector('parsererror')) throw new FMError(802, 'That XML file could not be read.');
    const names = [...doc.getElementsByTagName('FIELD')].map(f => f.getAttribute('NAME'));
    const rows = [...doc.getElementsByTagName('ROW')].map(r => [...r.getElementsByTagName('COL')].map(c => [...c.getElementsByTagName('DATA')].map(d => d.textContent).join('\n')));
    if (names.length) return { rows: [names].concat(rows), header: true };
    // generic XML: each element with children is a row
    const recs = [...doc.documentElement.children];
    const keys = []; recs.forEach(r => [...r.children].forEach(c => { if (!keys.includes(c.tagName)) keys.push(c.tagName); }));
    return { rows: [keys].concat(recs.map(r => keys.map(k => { const c = [...r.children].find(x => x.tagName === k); return c ? c.textContent : ''; }))), header: true };
  }
  dlg.importRecords = async function (win, o) {
    o = o || {};
    if (!win.table) throw new FMError(106);
    const f = await FM.pickFile('.csv,.tab,.tsv,.txt,.mer,.xlsx,.xml,.json');
    if (!f) throw new FMError(1);
    const src = await readSource(win.file, f);
    if (!src.rows.length) throw new FMError(401, 'The file has no records.');
    return dlg.importMapping(win, src, f.name, o);
  };
  dlg.importMapping = async function (win, src, fileName, o) {
    o = o || {};
    const file = win.file;
    let table = win.table;
    const tableSel = FM.select(file.schema.tables.map(t => ({ value: t.id, label: t.name })).concat(file.full ? [{ value: '__new', label: 'New Table ("' + fileName.replace(/\.[^.]+$/, '') + '")' }] : []), table.id);
    const ncols = Math.max(...src.rows.map(r => r.length));
    // a first row that names the table's fields is a header row
    const headerLike = t => { if (!t) return false; const names = new Set(t.fields.map(f => f.name.toLowerCase())); const row = (src.rows[0] || []).map(v => String(v).trim().toLowerCase()).filter(Boolean); return row.length > 0 && row.filter(v => names.has(v)).length >= Math.ceil(row.length / 2); };
    let first = !!src.header || headerLike(table);
    const firstRow = FM.check("Don't import first record (contains field names)", first);
    const mapping = []; // target field id per source column ('' = none)
    let matchSet = new Set();
    let idx = first ? 1 : 0;
    const grid = h('table', { class: 'fm-grid fm-impmap' });
    const fieldsOf = () => table ? table.fields.filter(x => x.type !== 'calculation' && x.type !== 'summary') : [];
    // fields filled automatically (keys, creation and modification stamps, serials) are not matched by position
    const manual = f => { const ae = (f.options || {}).autoEnter || {}; return !(ae.creation || ae.modification || (ae.serial && ae.serial.on) || (ae.calc && ae.prohibit)); };
    const arrange = how => {
      const fs = fieldsOf(); const byOrder = fs.filter(manual); mapping.length = 0;
      for (let c = 0; c < ncols; c++) {
        let tgt = '';
        if (how === 'names') { const h0 = String((src.rows[0] || [])[c] || '').trim().toLowerCase(); const m = fs.find(x => x.name.toLowerCase() === h0); tgt = m ? m.id : ''; }
        else if (how === 'order') tgt = byOrder[c] ? byOrder[c].id : '';
        mapping.push(tgt);
      }
    };
    arrange(first ? 'names' : 'order');
    if (first && !mapping.some(Boolean)) arrange('order');
    const draw = () => {
      grid.innerHTML = '';
      grid.appendChild(h('tr', null, h('th', { text: 'Source Fields' }), h('th', { text: '' }), h('th', { text: 'Target Fields (' + (table ? table.name : 'new table') + ')' })));
      const row = src.rows[idx] || [];
      for (let c = 0; c < ncols; c++) {
        const fsel = FM.select([{ value: '', label: '—' }].concat(table ? fieldsOf().map(x => ({ value: x.id, label: x.name })) : []), mapping[c] || '');
        fsel.onchange = () => { mapping[c] = fsel.value; draw(); };
        const arrow = h('button', { class: 'fm-maparrow' + (mapping[c] ? (matchSet.has(c) ? ' match' : ' on') : ''), text: mapping[c] ? (matchSet.has(c) ? '=' : '→') : '—', title: 'Click to cycle: import → match field → don\'t import' });
        arrow.onclick = () => { if (!mapping[c]) return; if (matchSet.has(c)) { matchSet.delete(c); mapping[c] = ''; } else if (action.value === 'match') matchSet.add(c); else mapping[c] = ''; draw(); };
        grid.appendChild(h('tr', null, h('td', null, h('div', { class: 'fm-mono small', text: String(row[c] == null ? '' : row[c]).slice(0, 60) }), first ? h('div', { class: 'fm-muted small', text: String((src.rows[0] || [])[c] || '') }) : null), h('td', null, arrow), h('td', null, table ? fsel : h('span', { class: 'fm-muted', text: String((src.rows[0] || [])[c] || 'Field ' + (c + 1)) }))));
      }
      nav.textContent = 'Record ' + (idx + 1) + ' of ' + src.rows.length;
    };
    const nav = h('span', { class: 'fm-muted' });
    const action = FM.select([{ value: 'add', label: 'Add new records' }, { value: 'update', label: 'Update existing records in found set' }, { value: 'match', label: 'Update matching records in found set' }], 'add');
    const addRemaining = FM.check('Add remaining data as new records', true);
    const autoEnter = FM.check('Perform auto-enter options while importing', true);
    const arr = FM.select([{ value: '', label: 'Arrange by…' }, { value: 'names', label: 'matching names' }, { value: 'order', label: 'field creation order' }, { value: 'none', label: 'clear all' }], '');
    arr.onchange = () => { if (arr.value === 'none') mapping.fill(''); else if (arr.value) arrange(arr.value); arr.value = ''; draw(); };
    firstRow.input.onchange = () => { first = firstRow.input.checked; idx = first ? 1 : 0; draw(); };
    tableSel.onchange = () => { table = tableSel.value === '__new' ? null : file.table(tableSel.value); if (headerLike(table)) { first = true; firstRow.input.checked = true; } arrange(table && first ? 'names' : 'order'); if (table && first && !mapping.some(Boolean)) arrange('order'); draw(); };
    action.onchange = () => { if (action.value !== 'match') matchSet = new Set(); draw(); };
    draw();
    const body = h('div', { class: 'fm-form' },
      h('div', { class: 'fm-inline' }, 'Source: ', h('b', { text: fileName }), h('span', { class: 'fm-flex1' }), 'Target: ', tableSel),
      h('div', { class: 'fm-inline' }, h('button', { class: 'fm-btn small', text: '◀', onclick: () => { idx = Math.max(0, idx - 1); draw(); } }), h('button', { class: 'fm-btn small', text: '▶', onclick: () => { idx = Math.min(src.rows.length - 1, idx + 1); draw(); } }), nav, h('span', { class: 'fm-flex1' }), arr),
      h('div', { class: 'fm-scroll', style: { maxHeight: '340px' } }, grid),
      firstRow, h('div', { class: 'fm-inline' }, 'Import Action: ', action, addRemaining), autoEnter,
      h('div', { class: 'fm-muted small', text: 'In "Update matching records", click an arrow until it shows "=" to make that column a match field.' }));
    const ok = await FM.modal({ title: 'Import Field Mapping', body, width: 760, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'Import', value: true, primary: true }] });
    if (!ok) throw new FMError(1);
    if (!table) {
      // new table from the file's columns
      const name = uniqueName(fileName.replace(/\.[^.]+$/, '').replace(/[^\w ]+/g, ' ').trim() || 'Imported', file.schema.tables.map(t => t.name));
      const nt = { id: FM.uid('T'), name, fields: [] };
      for (let c = 0; c < ncols; c++) {
        const header = first ? String((src.rows[0] || [])[c] || '').trim() : '';
        const fname = uniqueName(header || 'f' + (c + 1), nt.fields.map(x => x.name));
        const sample = src.rows.slice(first ? 1 : 0, 60).map(r => r[c]).filter(v => v != null && v !== '');
        const type = sample.length && sample.every(v => /^-?\d+(\.\d+)?$/.test(String(v).trim())) ? 'number' : sample.length && sample.every(v => /^\d{4}-\d{2}-\d{2}$/.test(String(v)) || D.parseDate(v) != null && /\d{1,2}\/\d{1,2}\/\d{2,4}/.test(v)) ? 'date' : 'text';
        nt.fields.push({ id: FM.uid('F'), name: fname, type, options: {} });
        mapping[c] = nt.fields[c].id;
      }
      const to = { id: FM.uid('O'), name: uniqueName(name, file.schema.tableOccurrences.map(x => x.name)), table: nt.id, x: 60, y: 60, color: '#d9f0dc' };
      const tmp = Object.create(file); tmp.schema = Object.assign({}, file.schema, { tables: file.schema.tables.concat([nt]), tableOccurrences: file.schema.tableOccurrences.concat([to]) });
      const lay = FM.design.autoLayout(tmp, { name: uniqueName(name, file.schema.layouts.map(l => l.name)), to: to.id, kind: 'table', keys: nt.fields.map(x => FM.fkey(to.id, x.id)) });
      await file.saveSchema([{ op: 'section', name: 'database', value: { tables: file.schema.tables.concat([nt]), tableOccurrences: file.schema.tableOccurrences.concat([to]), relationships: file.schema.relationships } }, { op: 'upsert', coll: 'layouts', item: lay }]);
      table = file.table(nt.id);
      await win.setLayout(lay.id, { silent: true });
    } else if (table.id !== win.table.id) {
      const lay = file.schema.layouts.find(l => file.to(l.to).table === table.id);
      if (lay) await win.setLayout(lay.id, { silent: true });
    }
    return runImport(win, table, src, mapping, { first, action: action.value, addRemaining: addRemaining.input.checked, autoEnter: autoEnter.input.checked, match: [...matchSet] });
  };
  async function runImport(win, table, src, mapping, o) {
    const file = win.file;
    const rows = src.rows.slice(o.first ? 1 : 0);
    const fields = new Map(table.fields.map(f => [f.id, f]));
    let errors = 0, fieldErrors = 0;
    const toData = row => {
      const d = {};
      mapping.forEach((fid, c) => {
        if (!fid || (o.match || []).includes(c) && o.action === 'match' && false) return;
        const f = fields.get(fid); if (!f) return;
        let v = row[c] == null ? '' : String(row[c]);
        if (f.type === 'date' && v) { const n = D.parseDate(v); if (n != null) v = D.isoDate(n); else fieldErrors++; }
        else if (f.type === 'time' && v) { const n = D.parseTime(v); if (n != null) v = D.isoTime(n); else fieldErrors++; }
        else if (f.type === 'timestamp' && v) { const n = D.parseTimestamp(v); if (n != null) v = D.isoTs(n); else fieldErrors++; }
        else if (f.type === 'number') v = v.trim();
        else if (f.type === 'container') { if (!v) return; v = v.split(/[/\\]/).pop(); }
        const reps = file.reps(f);
        if (reps > 1 && v.includes('\u001d')) d[fid] = v.split('\u001d').slice(0, reps); else d[fid] = v.replace(/\r\n|\r/g, '\n');
      });
      return d;
    };
    const auto = rec => {
      if (!o.autoEnter) return {};
      const fake = { id: 'imp' + Math.random(), t: table.id, d: {} };
      const v = file.autoEnterCreate(table, fake, win);
      file.editing.delete(fake.id);
      return v;
    };
    const ops = [];
    let updated = 0, added = 0;
    if (o.action === 'add') rows.forEach(r => { const d = Object.assign(auto(), toData(r)); ops.push({ op: 'create', table: table.id, data: d, pending: false }); added++; });
    else if (o.action === 'update') {
      const recs = win.foundRecords();
      rows.forEach((r, i) => { if (recs[i]) { ops.push({ op: 'update', id: recs[i].id, data: toData(r) }); updated++; } else if (o.addRemaining) { ops.push({ op: 'create', table: table.id, data: Object.assign(auto(), toData(r)), pending: false }); added++; } });
    } else {
      if (!o.match.length) throw new FMError(5, 'Choose at least one match field (click an arrow until it shows "=").');
      const recs = win.foundRecords();
      const keyOf = vals => vals.map(v => String(v).trim().toLowerCase()).join('\u0001');
      const index = new Map();
      recs.forEach(r => { const k = keyOf(o.match.map(c => file.raw(r, fields.get(mapping[c]), 1))); if (!index.has(k)) index.set(k, []); index.get(k).push(r); });
      rows.forEach(r => {
        const k = keyOf(o.match.map(c => toData(r)[mapping[c]] || ''));
        const hits = index.get(k);
        if (hits) hits.forEach(x => { ops.push({ op: 'update', id: x.id, data: toData(r) }); updated++; });
        else if (o.addRemaining) { ops.push({ op: 'create', table: table.id, data: Object.assign(auto(), toData(r)), pending: false }); added++; }
      });
    }
    const createdIds = [];
    const prog = FM.toast;
    for (let i = 0; i < ops.length; i += 2000) {
      try {
        const res = await file.batch(ops.slice(i, i + 2000));
        res.forEach(x => { if (x.op === 'create' || x.op === 'update') createdIds.push(x.id); });
        if (ops.length > 2000) prog('Imported ' + Math.min(ops.length, i + 2000) + ' of ' + ops.length + '…');
      } catch (e) { errors += Math.min(2000, ops.length - i); await FM.alert('Some records could not be imported: ' + e.message, { icon: 'warn' }); break; }
    }
    const s = win.set_(); s.ids = [...new Set(createdIds)]; s.index = 0;
    win.mode = 'browse';
    win.render();
    await FM.alert('Import Summary\n\nTotal records added: ' + added + '\nTotal records updated: ' + updated + '\nTotal records skipped due to errors: ' + errors + '\nTotal fields not imported due to errors: ' + fieldErrors, { title: 'Import Summary', icon: 'info' });
    return true;
  }
  dlg.importSpecNote = async function () {
    await FM.alert('Import Records always shows the Import Field Mapping dialog in this version, because a browser can only read a file the user chooses.', { icon: 'info' });
    return null;
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Export
  // ═══════════════════════════════════════════════════════════════════════
  const FORMATS = [['csv', 'Comma-Separated Values (.csv)'], ['tab', 'Tab-Separated Text (.tab)'], ['xlsx', 'Excel Workbooks (.xlsx)'], ['xml', 'XML (FMPXMLRESULT) (.xml)'], ['json', 'JSON (.json)'], ['html', 'HTML Table (.htm)'], ['mer', 'Merge (.mer)']];
  dlg.exportSpec = async function (win, spec) {
    spec = FM.clone(spec || { format: 'csv', keys: FM.layoutFields(win.layout).slice(0, 30), formatted: true, group: [] });
    const file = win.file;
    const toSel = toSelect(file, win.to, win.to);
    const flist = h('select', { class: 'fm-input fm-list', size: 14 });
    const fill = () => { flist.innerHTML = ''; const t = file.tableOfTO(toSel.value); (t ? t.fields : []).forEach(f => flist.appendChild(h('option', { value: FM.fkey(toSel.value, f.id), text: f.name }))); };
    toSel.onchange = fill; fill();
    const olist = h('select', { class: 'fm-input fm-list', size: 14 });
    const draw = () => { olist.innerHTML = ''; spec.keys.forEach(k => olist.appendChild(h('option', { value: k, text: file.keyLabel(k, win.to) }))); };
    draw();
    const move = () => { if (flist.value && !spec.keys.includes(flist.value)) { spec.keys.push(flist.value); draw(); } };
    flist.ondblclick = move; olist.ondblclick = () => { spec.keys.splice(olist.selectedIndex, 1); draw(); };
    const fmt = FM.select(FORMATS.map(([v, l]) => ({ value: v, label: l })), spec.format);
    const applyFmt = FM.check("Apply current layout's data formatting to exported data", spec.formatted !== false);
    const sortKeys = (win.set_().sort || []).map(s => s.key);
    const group = h('div', { class: 'fm-col' }, sortKeys.length ? sortKeys.map(k => { const c = FM.check(file.keyLabel(k, win.to), (spec.group || []).includes(k)); c.input.onchange = () => { spec.group = (spec.group || []).filter(x => x !== k); if (c.input.checked) spec.group.push(k); }; return c; }) : h('span', { class: 'fm-muted small', text: 'Sort the records to group the export by a field.' }));
    const body = h('div', { class: 'fm-form' }, FM.row('Format', fmt), h('div', { class: 'fm-sortdlg' },
      h('div', { class: 'fm-col' }, toSel, flist),
      h('div', { class: 'fm-col fm-sort-mid' }, h('button', { class: 'fm-btn small', text: 'Move →', onclick: move }), h('button', { class: 'fm-btn small', text: 'Move All →', onclick: () => { [...flist.options].forEach(op => { if (!spec.keys.includes(op.value)) spec.keys.push(op.value); }); draw(); } }), h('button', { class: 'fm-btn small', text: '← Clear', onclick: () => { if (olist.selectedIndex >= 0) { spec.keys.splice(olist.selectedIndex, 1); draw(); } } }), h('button', { class: 'fm-btn small', text: 'Clear All', onclick: () => { spec.keys = []; draw(); } }),
        h('button', { class: 'fm-btn small', text: '↑', onclick: () => { const i = olist.selectedIndex; if (i > 0) { [spec.keys[i - 1], spec.keys[i]] = [spec.keys[i], spec.keys[i - 1]]; draw(); olist.selectedIndex = i - 1; } } }), h('button', { class: 'fm-btn small', text: '↓', onclick: () => { const i = olist.selectedIndex; if (i >= 0 && i < spec.keys.length - 1) { [spec.keys[i + 1], spec.keys[i]] = [spec.keys[i], spec.keys[i + 1]]; draw(); olist.selectedIndex = i + 1; } } })),
      h('div', { class: 'fm-col' }, h('div', { class: 'fm-muted small', text: 'Field export order' }), olist, h('div', { class: 'fm-muted small', text: 'Group by' }), group)), applyFmt);
    return FM.modal({ title: 'Specify Field Order for Export', body, width: 780, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, validate: () => { if (!spec.keys.length) { FM.alert('Choose at least one field.'); return false; } return true; }, value: () => Object.assign(spec, { format: fmt.value, formatted: applyFmt.input.checked }) }] });
  };
  dlg.exportRecords = async function (win, o) {
    o = o || {};
    const file = win.file;
    if (!file.full && file.pset().exporting === false) throw new FMError(200, 'Your privileges do not allow exporting.');
    if (!(await win.commit())) throw new FMError(301);
    let spec = o.spec;
    if (o.dialog || !spec) { spec = await dlg.exportSpec(win, spec); if (!spec) throw new FMError(1); }
    const recs = win.foundRecords();
    const fields = spec.keys.map(k => file.fieldByKey(k));
    const val = (r, k) => {
      const kk = FM.pkey(k); const f = file.fieldByKey(k);
      if (!f) return '';
      if (kk.to !== win.to) { const rel = file.related(win.to, r, kk.to); return rel.map(x => spec.formatted !== false ? file.formatValue(file.value(x, f, 1, { to: kk.to }), f) : V.toStored(file.value(x, f, 1, { to: kk.to }), 'text')).join('\n'); }
      const v = file.value(r, f, 1, win.ctx(r));
      if (V.isContainer(v)) return v.name;
      if (spec.formatted !== false) return file.formatValue(v, f, (FM.layoutObjects(win.layout).find(x => x.field === k) || {}).format);
      if (f.type === 'date' || f.type === 'time' || f.type === 'timestamp' || ((f.options || {}).calc || {}).resultType) return V.toStored(v, f.type === 'calculation' ? ((f.options || {}).calc || {}).resultType : f.type);
      return V.text(v);
    };
    let rows = recs.map(r => spec.keys.map(k => val(r, k)));
    if (spec.group && spec.group.length) {
      // grouped export: only the first record of each group carries the group field values
      const gi = spec.group.map(g => spec.keys.indexOf(g)).filter(i => i >= 0);
      let prev = null;
      rows = rows.map(r => { const k = gi.map(i => r[i]).join('\u0001'); const out = r.slice(); if (k === prev) gi.forEach(i => { out[i] = ''; }); prev = k; return out; });
    }
    const names = spec.keys.map(k => file.keyLabel(k, win.to));
    const base = (o.filename || (win.layout.name + ' Export')).replace(/\.[a-z0-9]+$/i, '');
    switch (spec.format) {
      case 'tab': FM.download(base + '.tab', FM.toDelimited(rows, '\t'), 'text/tab-separated-values'); break;
      case 'mer': FM.download(base + '.mer', FM.toDelimited([names].concat(rows), ','), 'text/csv'); break;
      case 'json': FM.download(base + '.json', JSON.stringify(rows.map(r => Object.fromEntries(names.map((n, i) => [n, r[i]]))), null, 2), 'application/json'); break;
      case 'html': FM.download(base + '.htm', '<!DOCTYPE html><html><head><meta charset="utf-8"><title>' + FM.esc(base) + '</title></head><body><table border="1" cellspacing="0" cellpadding="4"><tr>' + names.map(n => '<th>' + FM.esc(n) + '</th>').join('') + '</tr>' + rows.map(r => '<tr>' + r.map(c => '<td>' + FM.esc(c).replace(/\n/g, '<br>') + '</td>').join('') + '</tr>').join('') + '</table></body></html>', 'text/html'); break;
      case 'xml': FM.download(base + '.xml', fmpxml(file, win, spec.keys, names, fields, rows), 'application/xml'); break;
      case 'xlsx': {
        const blob = await FM.api('POST', '/xlsx/build', { filename: base, sheet: win.layout.name, header: true, rows: [names].concat(rows), types: fields.map(f => f ? (f.type === 'calculation' ? ((f.options || {}).calc || {}).resultType : f.type) : 'text') }, { blob: true });
        FM.download(base + '.xlsx', blob); break;
      }
      default: FM.download(base + '.csv', FM.toDelimited(rows, ','), 'text/csv');
    }
    return true;
  };
  function fmpxml(file, win, keys, names, fields, rows) {
    const e = FM.esc;
    const type = f => !f ? 'TEXT' : ({ number: 'NUMBER', date: 'DATE', time: 'TIME', timestamp: 'TIMESTAMP', container: 'CONTAINER' }[f.type === 'calculation' ? ((f.options || {}).calc || {}).resultType : f.type] || 'TEXT');
    return '<?xml version="1.0" encoding="UTF-8" ?>\n<FMPXMLRESULT xmlns="http://www.filemaker.com/fmpxmlresult">\n<ERRORCODE>0</ERRORCODE>\n<PRODUCT BUILD="" NAME="FileMaker (independent recreation)" VERSION="1.0"/>\n<DATABASE DATEFORMAT="M/d/yyyy" LAYOUT="' + e(win.layout.name) + '" NAME="' + e(file.name) + '" RECORDS="' + win.totalCount() + '" TIMEFORMAT="h:mm:ss a"/>\n<METADATA>\n' +
      names.map((n, i) => '<FIELD EMPTYOK="YES" MAXREPEAT="1" NAME="' + e(n) + '" TYPE="' + type(fields[i]) + '"/>').join('\n') + '\n</METADATA>\n<RESULTSET FOUND="' + rows.length + '">\n' +
      rows.map(r => '<ROW>' + r.map(c => '<COL>' + String(c).split('\n').map(x => '<DATA>' + e(x) + '</DATA>').join('') + '</COL>').join('') + '</ROW>').join('\n') + '\n</RESULTSET>\n</FMPXMLRESULT>\n';
  }
  dlg.saveAsExcel = async function (win, o) {
    o = o || {};
    const spec = { format: 'xlsx', keys: FM.layoutFields(win.layout).filter(k => { const f = win.file.fieldByKey(k); return f && f.type !== 'container'; }), formatted: true };
    if (o.current && win.current()) { const ids = win.set_().ids; win.set_().ids = [win.current().id]; try { await dlg.exportRecords(win, { spec, filename: o.filename || win.layout.name }); } finally { win.set_().ids = ids; } return; }
    return dlg.exportRecords(win, { spec, filename: o.filename || win.layout.name, dialog: o.dialog });
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Replace Field Contents, Find/Replace
  // ═══════════════════════════════════════════════════════════════════════
  dlg.replaceFieldContents = async function (win, p) {
    const file = win.file;
    const key = p.field || (win.active && win.active.key);
    if (!key) throw new FMError(102, 'Click into a field first.');
    const f = file.fieldByKey(key);
    if (!f || f.type === 'calculation' || f.type === 'summary') throw new FMError(201);
    const recs = win.foundRecords();
    let how = p.how || 'current', formula = p.calc || '', start = p.start ? (p.rt ? p.rt.text(p.start) : p.start) : '1', incr = p.incr ? (p.rt ? p.rt.num(p.incr) : +p.incr) : 1;
    const cur = win.current();
    const curVal = cur ? file.raw(cur, f, 1) : '';
    if (p.dialog !== false) {
      const r1 = h('input', { type: 'radio', name: 'rfc', checked: how === 'current' }), r2 = h('input', { type: 'radio', name: 'rfc', checked: how === 'serial' }), r3 = h('input', { type: 'radio', name: 'rfc', checked: how === 'calc' });
      const s0 = h('input', { class: 'fm-input', style: { width: '80px' }, value: start }), s1 = h('input', { class: 'fm-input', style: { width: '60px' }, value: incr });
      const cb = h('button', { class: 'fm-btn small', text: 'Specify…' }); const ct = h('div', { class: 'fm-mono small', text: formula });
      cb.onclick = async () => { const r = await dlg.calc(file, { formula, to: win.to }); if (r) { formula = r.formula; ct.textContent = formula; r3.checked = true; } };
      const body = h('div', { class: 'fm-form' }, h('div', { text: 'Permanently replace the contents of the field "' + f.name + '" in all ' + recs.length + ' records of the current found set?' }),
        h('label', { class: 'fm-check' }, r1, h('span', { text: 'Replace with: "' + String(curVal).slice(0, 40) + '"' })),
        h('div', { class: 'fm-inline' }, h('label', { class: 'fm-check' }, r2, h('span', { text: 'Replace with serial numbers: initial value' })), s0, ' increment by ', s1),
        h('div', { class: 'fm-inline' }, h('label', { class: 'fm-check' }, r3, h('span', { text: 'Replace with calculated result:' })), cb), ct);
      const ok = await FM.modal({ title: 'Replace Field Contents', body, width: 520, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'Replace', value: true, primary: true }] });
      if (!ok) throw new FMError(1);
      how = r2.checked ? 'serial' : r3.checked ? 'calc' : 'current'; start = s0.value; incr = +s1.value || 1;
    }
    if (!(await win.commit())) throw new FMError(301);
    let serial = String(start);
    const ops = recs.map(r => {
      let v;
      if (how === 'serial') { v = serial; serial = FM.serialIncrement(serial, incr); }
      else if (how === 'calc') v = V.toStored(file.evaluate(formula, win.ctx(r)), f.type);
      else v = curVal;
      const reps = file.reps(f);
      return { op: 'update', id: r.id, data: { [f.id]: reps > 1 ? [v].concat(((r.d[f.id] || []).slice ? r.d[f.id].slice(1) : [])) : v } };
    });
    for (let i = 0; i < ops.length; i += 2000) await file.batch(ops.slice(i, i + 2000));
    win.render();
    return true;
  };
  dlg.findReplace = async function (win, o) {
    o = o || {};
    const file = win.file;
    let find = o.find || '', repl = o.replace || '';
    let matchCase = !!o.matchCase, whole = !!o.wholeWords, scope = o.scope || 'all';
    if (o.dialog || !o.find) {
      const fi = h('input', { class: 'fm-input', value: find }), ri = h('input', { class: 'fm-input', value: repl });
      const mc = FM.check('Match case', matchCase), ww = FM.check('Match whole words only', whole);
      const sc = FM.select([{ value: 'all', label: 'All records' }, { value: 'current', label: 'Current record' }], scope);
      const r = await FM.modal({ title: 'Find/Replace', body: h('div', { class: 'fm-form' }, FM.row('Find what', fi), FM.row('Replace with', ri), mc, ww, FM.row('Search across', sc), h('div', { class: 'fm-muted small', text: 'Searches the text fields on this layout.' })), width: 480, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'Find Next', value: 'find' }, { label: 'Replace All', value: 'replaceall', primary: true }] });
      if (!r) throw new FMError(1);
      find = fi.value; repl = ri.value; matchCase = mc.input.checked; whole = ww.input.checked; scope = sc.value; o.action = r;
    }
    if (!find) throw new FMError(400);
    const keys = FM.layoutFields(win.layout).filter(k => { const f = file.fieldByKey(k); return f && f.type === 'text' && FM.pkey(k).to === win.to; });
    const re = new RegExp((whole ? '\\b' : '') + find.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + (whole ? '\\b' : ''), matchCase ? 'g' : 'gi');
    const recs = scope === 'current' ? [win.current()].filter(Boolean) : win.foundRecords();
    if (o.action === 'find') {
      const start = win.index + 1;
      for (let n = 0; n < recs.length; n++) {
        const i = (start + n) % recs.length; const r = recs[i];
        const k = keys.find(kk => re.test(String(file.raw(r, file.fieldByKey(kk), 1)))); re.lastIndex = 0;
        if (k) { await win.goTo(i); setTimeout(() => { const el = win.el.querySelector('[data-fm-key="' + CSS.escape(k) + '"]'); if (el && el.setSelectionRange) { el.focus(); const m = el.value.search(re); if (m >= 0) el.setSelectionRange(m, m + find.length); } }, 30); return true; }
      }
      await FM.alert('The text was not found.', { icon: 'info' });
      return false;
    }
    if (!(await win.commit())) throw new FMError(301);
    const ops = []; let n = 0;
    recs.forEach(r => { const d = {}; keys.forEach(k => { const f = file.fieldByKey(k); const v = String(file.raw(r, f, 1)); const nv = v.replace(re, () => { n++; return repl; }); if (nv !== v) d[f.id] = nv; }); if (Object.keys(d).length) ops.push({ op: 'update', id: r.id, data: d }); });
    if (ops.length) await file.batch(ops);
    win.render();
    if (o.dialog || !o.rt) await FM.alert(n + ' replacement(s) made.', { icon: 'info' });
    return true;
  };

  // ═══════════════════════════════════════════════════════════════════════
  // saved finds (kept in this browser)
  // ═══════════════════════════════════════════════════════════════════════
  const sfKey = file => 'fm.savedfinds.' + file.id + '.' + file.account.name.toLowerCase();
  dlg.getSavedFinds = file => { try { return JSON.parse(localStorage.getItem(sfKey(file)) || '[]'); } catch (e) { return []; } };
  dlg.setSavedFinds = (file, list) => { try { localStorage.setItem(sfKey(file), JSON.stringify(list)); } catch (e) { /* storage blocked */ } };
  dlg.saveCurrentFind = async function (win) {
    const reqs = win.mode === 'find' ? win.requests : win.set_().lastFind;
    if (!reqs) { await FM.alert('Perform a find first.'); return; }
    const name = await FM.prompt('Name for this saved find:', { title: 'Save Current Find', value: 'Find ' + (dlg.getSavedFinds(win.file).length + 1) });
    if (!name) return;
    const list = dlg.getSavedFinds(win.file); list.push({ name, layout: win.layoutId, requests: FM.clone(reqs) }); dlg.setSavedFinds(win.file, list);
    FM.toast('Saved find "' + name + '".');
  };
  dlg.savedFinds = async function (win) {
    const list = dlg.getSavedFinds(win.file);
    let sel = 0;
    const tbl = h('table', { class: 'fm-grid' });
    const draw = () => { tbl.innerHTML = ''; tbl.appendChild(h('tr', null, h('th', { text: 'Name' }), h('th', { text: 'Requests' }))); list.forEach((s, i) => { const tr = h('tr', { class: i === sel ? 'on' : '' }, h('td', { text: s.name }), h('td', { text: s.requests.map(r => (r.omit ? 'Omit: ' : 'Find: ') + Object.entries(r.crit).map(([k, v]) => win.file.keyLabel(k) + ' ' + v).join(', ')).join(' | ') })); tr.onclick = () => { sel = i; draw(); }; tbl.appendChild(tr); }); if (!list.length) tbl.appendChild(h('tr', null, h('td', { colspan: 2, class: 'fm-muted', text: 'No saved finds. In Find mode, choose Saved Finds > Save Current Find.' }))); };
    draw();
    const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-scroll', style: { height: '240px' } }, tbl), h('div', { class: 'fm-inline' },
      h('button', { class: 'fm-btn', text: 'Rename…', onclick: async () => { if (!list[sel]) return; const n = await FM.prompt('New name:', { value: list[sel].name }); if (n) { list[sel].name = n; draw(); } } }),
      h('button', { class: 'fm-btn', text: 'Delete', onclick: () => { list.splice(sel, 1); sel = 0; draw(); } })));
    const ok = await FM.modal({ title: 'Edit Saved Finds', body, width: 600, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    if (ok) dlg.setSavedFinds(win.file, list);
  };

  // ═══════════════════════════════════════════════════════════════════════
  // page setup, file options, sharing, preferences, accounts, help
  // ═══════════════════════════════════════════════════════════════════════
  dlg.pageSetup = async function (file) {
    const ps = Object.assign({ paper: 'letter', orientation: 'portrait', margins: 36, fit: true }, file.schema.fileOptions.pageSetup || {});
    const paper = FM.select([['letter', 'US Letter (8.5 × 11 in)'], ['legal', 'US Legal (8.5 × 14 in)'], ['a4', 'A4 (210 × 297 mm)'], ['tabloid', 'Tabloid (11 × 17 in)']].map(([v, l]) => ({ value: v, label: l })), ps.paper);
    const orient = FM.select([{ value: 'portrait', label: 'Portrait' }, { value: 'landscape', label: 'Landscape' }], ps.orientation);
    const margins = h('input', { class: 'fm-input', type: 'number', min: 0, max: 144, value: ps.margins, style: { width: '80px' } });
    const fit = FM.check('Reduce layouts wider than the page to fit', ps.fit !== false);
    const ok = await FM.modal({ title: 'Print Setup', body: h('div', { class: 'fm-form' }, FM.row('Paper size', paper), FM.row('Orientation', orient), FM.row('Margins (points)', margins), fit, file.full ? null : h('div', { class: 'fm-muted small', text: 'Only [Full Access] accounts can save page setup in the file.' })), width: 420, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    if (!ok) return false;
    const next = { paper: paper.value, orientation: orient.value, margins: +margins.value || 0, fit: fit.input.checked };
    if (file.full) await file.saveSchema([{ op: 'section', name: 'fileOptions', value: Object.assign({}, file.schema.fileOptions, { pageSetup: next }) }]);
    else file.schema.fileOptions.pageSetup = next;
    FM.app.windows.filter(w => w.file === file && w.mode === 'preview').forEach(w => w.render());
    return true;
  };
  dlg.fileOptions = async function (file) {
    if (!file.full) { await FM.alert('Only a [Full Access] account can change file options.', { icon: 'stopsign' }); return; }
    const fo = FM.clone(file.schema.fileOptions || {});
    fo.autoLogin = fo.autoLogin || {};
    fo.triggers = fo.triggers || {};
    let accounts = [];
    try { accounts = (await file.api('GET', '/accounts')).accounts; } catch (e) { /* not fatal */ }
    const al = FM.check('Log in using: Account Name (accounts without a password only)', !!fo.autoLogin.enabled);
    const acct = FM.select(accounts.filter(a => !a.hasPassword).map(a => ({ value: a.name, label: a.name })).concat([{ value: '', label: '—' }]), fo.autoLogin.account || '');
    const lay = FM.select([{ value: '', label: '(first layout)' }].concat(file.schema.layouts.map(l => ({ value: l.id, label: l.name }))), fo.openLayout || '');
    const scripts = FM.orderedScripts(file).filter(s => !s.folder && !s.separator);
    const trig = ['OnFirstWindowOpen', 'OnLastWindowClose', 'OnWindowOpen', 'OnWindowClose'].map(t => { const s = FM.select([{ value: '', label: '—' }].concat(scripts.map(x => ({ value: x.id, label: x.name }))), (fo.triggers[t] || {}).script || ''); return { t, s }; });
    const colors = ['', '#2a6fdb', '#2fa36b', '#e8833a', '#c94f7c', '#7a5cd6', '#d6b02f'];
    const color = FM.select(colors.map(c => ({ value: c, label: c || 'Default' })), fo.color || '');
    const body = FM.tabs(['Open', 'Script Triggers', 'Icon'], i => i === 0 ? h('div', { class: 'fm-form' }, al, FM.row('Account', acct), FM.row('Switch to layout', lay), h('div', { class: 'fm-muted small', text: 'Auto sign-in only works for an account with no password, and anyone who can open FileMaker here can then open this file.' })) : i === 1 ? h('div', { class: 'fm-form' }, ...trig.map(x => FM.row(x.t, x.s))) : h('div', { class: 'fm-form' }, FM.row('Icon color in the launch center', color)));
    const ok = await FM.modal({ title: 'File Options for "' + file.name + '"', body, width: 520, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    if (!ok) return;
    fo.autoLogin = { enabled: al.input.checked && !!acct.value, account: acct.value || fo.autoLogin.account };
    fo.openLayout = lay.value || undefined;
    trig.forEach(x => { if (x.s.value) fo.triggers[x.t] = { script: x.s.value }; else delete fo.triggers[x.t]; });
    fo.color = color.value || undefined;
    try { await file.saveSchema([{ op: 'section', name: 'fileOptions', value: fo }]); } catch (e) { FM.alert(e.message, { icon: 'warn' }); }
  };
  dlg.sharing = async function (file) {
    let data;
    try { data = await file.api('GET', '/users'); } catch (e) { await FM.alert(e.message); return; }
    const tbl = h('table', { class: 'fm-grid' });
    let sel = null;
    const draw = () => { tbl.innerHTML = ''; tbl.appendChild(h('tr', null, h('th', { text: 'User' }), h('th', { text: 'Account' }), h('th', { text: 'Opened' }), h('th', { text: 'Idle' }))); data.users.forEach(u => { const tr = h('tr', { class: u === sel ? 'on' : '' }, h('td', { text: u.user + (u.id === data.me ? '  (you)' : '') }), h('td', { text: u.account }), h('td', { text: u.opened }), h('td', { text: u.idle + ' s' })); tr.onclick = () => { sel = u; draw(); }; tbl.appendChild(tr); }); };
    draw();
    const act = async kind => {
      if (!sel) return FM.alert('Choose a user first.');
      const text = await FM.prompt(kind === 'message' ? 'Message to ' + sel.user + ':' : 'Disconnect ' + sel.user + '? Optional message:', { title: kind === 'message' ? 'Send Message' : 'Disconnect User', value: '' });
      if (text == null) return;
      try { await file.api('POST', '/users/' + sel.id + '/' + kind, { text }); FM.toast(kind === 'message' ? 'Message sent.' : 'User disconnected.'); data = await file.api('GET', '/users'); sel = null; draw(); } catch (e) { FM.alert(e.message, { icon: 'warn' }); }
    };
    const body = h('div', { class: 'fm-form' },
      h('div', { class: 'fm-muted', text: 'This file is hosted by The Office App at ' + location.host + '. Everyone with access to FileMaker can open it with an account of the file. Records are locked while someone edits them, and every change reaches the others within a couple of seconds.' }),
      h('b', { text: 'Users connected to "' + file.name + '"' }), h('div', { class: 'fm-scroll', style: { height: '220px' } }, tbl),
      file.full ? h('div', { class: 'fm-inline' }, h('button', { class: 'fm-btn', text: 'Send Message…', onclick: () => act('message') }), h('button', { class: 'fm-btn', text: 'Disconnect…', onclick: () => act('disconnect') }), h('button', { class: 'fm-btn', text: 'Refresh', onclick: async () => { data = await file.api('GET', '/users'); draw(); } })) : null,
      h('div', { class: 'fm-muted small', text: 'FileMaker WebDirect, the Data API, ODBC/JDBC and FileMaker Cloud are planned (Coming Soon).' }));
    await FM.modal({ title: 'FileMaker Network Settings — Sharing', body, width: 620, buttons: [{ label: 'Close', value: true, primary: true }] });
  };
  dlg.preferences = async function (app) {
    const p = app.prefs;
    const uname = h('input', { class: 'fm-input', value: p.userName || '', placeholder: app.boot.user });
    const autosave = FM.check('Save layout changes automatically (do not ask)', !!p.autoSaveLayouts);
    const addFields = FM.check('Add newly defined fields to the layout made for their table', p.addFieldsToLayout !== false);
    const grid = h('input', { class: 'fm-input', type: 'number', min: 1, max: 50, value: p.grid || 8, style: { width: '70px' } });
    const snap = FM.check('Snap objects to the grid in Layout mode', p.snap !== false);
    const body = FM.tabs(['General', 'Layout'], i => i === 0 ? h('div', { class: 'fm-form' }, FM.row('User name (Get ( UserName ))', uname)) : h('div', { class: 'fm-form' }, autosave, addFields, snap, FM.row('Grid spacing (points)', grid)));
    const ok = await FM.modal({ title: 'Preferences', body, width: 480, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    if (!ok) return;
    Object.assign(p, { userName: uname.value.trim(), autoSaveLayouts: autosave.input.checked, addFieldsToLayout: addFields.input.checked, grid: Math.max(1, +grid.value || 8), snap: snap.input.checked });
    app.savePrefs();
  };
  dlg.login = function (fileName, o) {
    o = o || {};
    const acct = h('input', { class: 'fm-input', value: o.account || '', autocomplete: 'username' });
    const pw = h('input', { class: 'fm-input', type: 'password', autocomplete: 'current-password' });
    const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-login-head' }, h('span', { html: FM.icon('lock', 30) }), h('div', null, h('b', { text: (o.relogin ? 'Sign in again to "' : 'Sign in to open "') + fileName + '"' }), h('div', { class: 'fm-muted small', text: 'Use an account of this file.' }))), FM.row('Account Name', acct), FM.row('Password', pw), o.error ? h('div', { class: 'fm-calc-status bad', text: o.error }) : null);
    return FM.modal({ title: 'Open "' + fileName + '"', body, width: 420, onOpen: () => setTimeout(() => (o.account ? pw : acct).focus(), 40), buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'Sign In', primary: true, value: () => ({ account: acct.value.trim(), password: pw.value }) }] });
  };
  dlg.newPassword = async function (fileName) {
    const a = h('input', { class: 'fm-input', type: 'password', autocomplete: 'new-password' }), b = h('input', { class: 'fm-input', type: 'password', autocomplete: 'new-password' });
    return FM.modal({ title: 'Change Password', body: h('div', { class: 'fm-form' }, h('div', { text: 'You must change your password before you open "' + fileName + '".' }), FM.row('New Password', a), FM.row('Confirm New Password', b)), width: 420, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, validate: () => { if (!a.value) { FM.alert('Enter a new password.'); return false; } if (a.value !== b.value) { FM.alert('The passwords do not match.'); return false; } return true; }, value: () => a.value }] });
  };
  dlg.changePassword = async function (file) {
    const a = h('input', { class: 'fm-input', type: 'password' }), b = h('input', { class: 'fm-input', type: 'password' }), c = h('input', { class: 'fm-input', type: 'password' });
    const r = await FM.modal({ title: 'Change Password', body: h('div', { class: 'fm-form' }, h('div', { text: 'Change the password for the account "' + file.account.name + '" in "' + file.name + '".' }), FM.row('Old Password', a), FM.row('New Password', b), FM.row('Confirm New Password', c)), width: 440, buttons: [{ label: 'Cancel', value: null, cancel: true }, { label: 'OK', primary: true, validate: () => { if (b.value !== c.value) { FM.alert('The new passwords do not match.'); return false; } return true; }, value: () => ({ old: a.value, new: b.value }) }] });
    if (!r) return false;
    try { await file.api('POST', '/password', r); FM.toast('Password changed.'); return true; } catch (e) { await FM.alert(e.message, { icon: 'warn' }); return false; }
  };
  dlg.about = function () {
    return FM.modal({
      title: 'About FileMaker', width: 520, html:
        '<div class="fm-about"><div class="fm-about-logo">FM</div><h2>FileMaker</h2><p><b>An independent recreation for The Office App</b> — a working, browser-based imitation of a FileMaker Pro–style relational database builder, for prototyping and learning.</p>' +
        '<p class="fm-muted">Not affiliated with, endorsed by or sponsored by Claris International Inc. “FileMaker” and “Claris” are trademarks of Claris International Inc., used here only to describe what this prototype imitates.</p></div>',
      buttons: [{ label: 'OK', value: true, primary: true }]
    });
  };
  dlg.help = function () {
    const sc = [['Ctrl+B', 'Browse mode'], ['Ctrl+F', 'Find mode'], ['Ctrl+L', 'Layout mode'], ['Ctrl+U', 'Preview mode'], ['Ctrl+N', 'New Record / Request'], ['Ctrl+D', 'Duplicate Record (Browse) / Duplicate objects (Layout)'], ['Ctrl+E', 'Delete Record'], ['Ctrl+J', 'Show All Records'], ['Ctrl+T', 'Omit Record'], ['Ctrl+R', 'Modify Last Find'], ['Ctrl+S', 'Sort Records (Browse) / Save Layout (Layout)'], ['Ctrl+Shift+D', 'Manage Database'], ['Ctrl+Shift+S', 'Script Workspace'], ['Ctrl+↑ / Ctrl+↓', 'Previous / Next record'], ['Ctrl+Enter', 'Commit record'], ['Enter (Find mode)', 'Perform Find'], ['Esc', 'Close menus and dialogs']];
    const done = ['Relational database: tables, all field types (text, number, date, time, timestamp, container, calculation, summary), repetitions, global fields', 'Relationships graph with table occurrences, multi-predicate relationships (=, ≠, <, ≤, >, ≥, ×), cascading delete, creation through portals, sorted relationships', 'Calculation engine with about 250 functions, Let, While, custom functions, JSON functions, ExecuteSQL (SELECT), Get functions and design functions', 'Auto-enter (serial, creation/modification, calculated, looked-up, last visited, data) and validation (strict type, not empty, unique, existing, value list, range, calculation, max characters, custom message)', 'Layout mode: fields and controls (edit box, drop-down list, pop-up menu, checkbox and radio sets, calendar, concealed), text with merge fields, shapes, buttons, button bars, popovers, portals, tab and slide controls, charts, web viewers, images; parts; inspector; arrange and align; conditional formatting; script triggers; tab order', 'Browse / Find / Layout / Preview modes; form, list and table views; finds with FileMaker operators; omit, constrain, extend; sorting; Quick Find; saved finds', 'Script Workspace with the FileMaker step catalog, variables, parameters and results, error capture, transactions, triggers, Script Debugger and Data Viewer', 'Accounts, privilege sets (records, fields, layouts, value lists, scripts, record-level limits checked by the host) and extended privileges', 'Import (CSV, tab, Excel, XML, JSON) and export (CSV, tab, Excel, XML, JSON, HTML, merge); reports with sub-summaries; printing and PDF', 'Multi-user hosting: record locking, live updates from other users, schema locking, connected users, messages and disconnect'];
    const planned = ['FileMaker WebDirect', 'FileMaker Data API, OData, ODBC/JDBC access', 'FileMaker Cloud and FileMaker Server admin console', 'External SQL data sources (ESS) and Manage Containers', 'Themes and styles editor, custom menus, plug-ins', 'Data files (Create/Read/Write Data File), AppleScript, DDE', 'AI steps (semantic find, models, embeddings), spelling steps', 'Merging related values across repetitions in exports and the "Furigana" options'];
    const html = '<div class="fm-help"><h3>Keyboard shortcuts</h3><table class="fm-grid">' + sc.map(([k, v]) => '<tr><td class="fm-mono">' + FM.esc(FM.keyLabel(k)) + '</td><td>' + FM.esc(v) + '</td></tr>').join('') + '</table>' +
      '<h3>What works in this version</h3><ul>' + done.map(x => '<li>' + FM.esc(x) + '</li>').join('') + '</ul>' +
      '<h3>Coming soon (planned)</h3><ul>' + planned.map(x => '<li>' + FM.esc(x) + '</li>').join('') + '</ul>' +
      '<p class="fm-muted">Independent recreation for prototype and educational use. Not affiliated with Claris International Inc.</p></div>';
    return FM.modal({ title: 'FileMaker Help', html, width: 720, buttons: [{ label: 'Close', value: true, primary: true }] });
  };
})();
