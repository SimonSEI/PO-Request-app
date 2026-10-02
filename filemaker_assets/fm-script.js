/* FileMaker (independent recreation) — scripts: the step catalog, the runtime
   (control flow, variables, parameters/results, error capture, transactions,
   triggers), the Script Workspace editor, the Script Debugger and the Data Viewer. */
(function () {
  'use strict';
  const FM = window.FM;
  const { h } = FM;
  const V = FM.V, D = FM.dt;
  const FMError = FM.FMError;

  // ═══════════════════════════════════════════════════════════════════════
  // step catalog
  // params: [{k: kind, key, label, opt, options, def}]
  // ═══════════════════════════════════════════════════════════════════════
  const STEPS = Object.create(null);
  const ORDER = [];
  const CATS = ['Control', 'Navigation', 'Editing', 'Fields', 'Records', 'Found Sets', 'Windows', 'Files', 'Accounts', 'Spelling', 'Open Menu Item', 'Miscellaneous'];
  function step(name, cat, params, run, o) {
    STEPS[name] = Object.assign({ name, cat, params: params || [], run }, o || {});
    ORDER.push(name);
  }
  const planned = (name, cat, params, note) => step(name, cat, params || [], async () => { throw new FMError(3, 'The "' + name + '" step is planned and not available in this version.'); }, { planned: true, note });
  const calc = (key, label, o) => Object.assign({ k: 'calc', key, label }, o || {});
  const bool = (key, label, def) => ({ k: 'bool', key, label, def: !!def });
  const choice = (key, label, options, def) => ({ k: 'choice', key, label, options, def: def == null ? options[0][0] : def });
  const field = (key, label, o) => Object.assign({ k: 'field', key, label: label || 'Target field' }, o || {});

  // ── Control ─────────────────────────────────────────────────────────────
  step('Perform Script', 'Control', [{ k: 'script', key: 'script', label: 'Script' }, calc('param', 'Parameter', { opt: true })], async (p, rt) => {
    const s = rt.resolveScript(p.script);
    await rt.call(s, p.param ? rt.ev(p.param) : '');
  });
  step('Perform Script on Server', 'Control', [{ k: 'script', key: 'script', label: 'Script' }, calc('param', 'Parameter', { opt: true }), bool('wait', 'Wait for completion', true)], async (p, rt) => {
    const s = rt.resolveScript(p.script);
    // This host runs scripts in the browser; the server-side variant runs here too.
    await rt.call(s, p.param ? rt.ev(p.param) : '', { server: true });
  }, { note: 'Runs in this window (the host does not run scripts by itself).' });
  step('Perform Script on Server with Callback', 'Control', [{ k: 'script', key: 'script', label: 'Script' }, calc('param', 'Parameter', { opt: true }), { k: 'script', key: 'callback', label: 'Callback script' }, calc('cbparam', 'Callback parameter', { opt: true })], async (p, rt) => {
    const s = rt.resolveScript(p.script);
    await rt.call(s, p.param ? rt.ev(p.param) : '', { server: true });
    if (p.callback && p.callback.id) await rt.call(rt.resolveScript(p.callback), p.cbparam ? rt.ev(p.cbparam) : '');
  });
  step('Exit Script', 'Control', [calc('result', 'Text result', { opt: true })], async (p, rt, st, fr) => { fr.result = p.result ? rt.ev(p.result) : ''; fr.exit = true; });
  step('Halt Script', 'Control', [], async (p, rt) => { rt.halted = true; });
  step('If', 'Control', [calc('calc', 'Condition')], null, { block: 'if' });
  step('Else If', 'Control', [calc('calc', 'Condition')], null, { block: 'elseif' });
  step('Else', 'Control', [], null, { block: 'else' });
  step('End If', 'Control', [], null, { block: 'endif' });
  step('Loop', 'Control', [bool('flush', 'Flush always', false)], null, { block: 'loop' });
  step('Exit Loop If', 'Control', [calc('calc', 'Condition')], null, { block: 'exitloopif' });
  step('End Loop', 'Control', [], null, { block: 'endloop' });
  step('Allow User Abort', 'Control', [bool('on', 'On', true)], async (p, rt) => { rt.allowAbort = !!p.on; });
  step('Set Error Capture', 'Control', [bool('on', 'On', true)], async (p, rt) => { rt.errorCapture = !!p.on; });
  step('Set Variable', 'Control', [{ k: 'var', key: 'name', label: 'Name' }, calc('value', 'Value'), calc('rep', 'Repetition', { opt: true })], async (p, rt) => {
    const name = String(p.name || '').trim();
    if (!/^\$\$?[^\s]+$/.test(name)) throw new FMError(5, 'A variable name must start with $ or $$.');
    rt.file.setVar(name, rt.ev(p.value || ''), p.rep ? Math.max(1, Math.floor(V.num(rt.ev(p.rep)))) : 1, rt.ctx());
  });
  step('Set Script Animation', 'Control', [bool('on', 'On', true)], async () => { });
  step('Pause/Resume Script', 'Control', [choice('mode', 'Pause', [['indef', 'Indefinitely'], ['duration', 'For duration (seconds)']]), calc('secs', 'Duration (seconds)', { opt: true })], async (p, rt) => {
    if (p.mode === 'duration') { const ms = Math.max(0, V.num(rt.ev(p.secs || '0')) * 1000); await rt.sleep(ms); return; }
    await rt.pause();
  });
  step('Install OnTimer Script', 'Control', [{ k: 'script', key: 'script', label: 'Script', opt: true }, calc('param', 'Parameter', { opt: true }), calc('interval', 'Interval (seconds)', { opt: true })], async (p, rt) => {
    const win = rt.win;
    if (win.timers) { clearInterval(win.timers); win.timers = null; }
    if (!p.script || !p.script.id && !p.script.calc) return;
    const s = rt.resolveScript(p.script); const secs = Math.max(0.1, V.num(rt.ev(p.interval || '1')));
    const param = p.param ? rt.ev(p.param) : '';
    win.timers = setInterval(() => { if (!rt.runner.busy && !FM.modalOpen() && win.el && win.mode !== 'layout' && document.activeElement && !(win.el.contains(document.activeElement) && /INPUT|TEXTAREA/.test(document.activeElement.tagName))) rt.runner.run(s, param, { win, timer: true }); }, secs * 1000);
  });
  step('Set Layout Object Animation', 'Control', [bool('on', 'On', true)], async () => { });
  step('Open Transaction', 'Control', [bool('skipAuto', 'Skip auto-enter options', false)], async (p, rt) => {
    if (rt.txn) throw new FMError(3, 'A transaction is already open.');
    rt.txn = [];
  });
  step('Commit Transaction', 'Control', [], async (p, rt) => {
    if (!rt.txn) throw new FMError(3, 'No transaction is open.');
    await rt.win.commit({ silent: true, rt });
    const ops = rt.txn; rt.txn = null;
    if (ops.length) {
      try { await rt.file.batch(ops); ops.forEach(o => rt.file.editing.delete(o.id)); }
      catch (e) { await rt.revertTxn(ops); throw new FMError(e.fmError || 301, e.message); }
    }
    rt.win.render();
  });
  step('Revert Transaction', 'Control', [calc('cond', 'Condition', { opt: true }), calc('code', 'Error code', { opt: true }), calc('msg', 'Error message', { opt: true })], async (p, rt) => {
    if (!rt.txn) return;
    if (p.cond && !rt.bool(p.cond)) return;
    const ops = rt.txn; rt.txn = null;
    await rt.revertTxn(ops);
    if (p.code) { rt.lastErrorDetail = p.msg ? rt.text(p.msg) : ''; throw new FMError(Math.floor(V.num(rt.ev(p.code))) || 1, rt.lastErrorDetail || 'Transaction reverted'); }
  });
  step('#', 'Control', [{ k: 'comment', key: 'text', label: 'Comment' }], async () => { }, { comment: true });
  planned('Perform Script on Server (WebDirect)', 'Control');
  planned('Configure Region Monitor Script', 'Control');
  planned('Configure Local Notification', 'Control');
  planned('Set Error Logging', 'Control');
  planned('Trigger Claris Connect Flow', 'Control');

  // ── Navigation ──────────────────────────────────────────────────────────
  step('Go to Layout', 'Navigation', [{ k: 'layout', key: 'layout', label: 'Layout' }, choice('anim', 'Animation', [['none', 'None'], ['slide', 'Slide'], ['fade', 'Fade']])], async (p, rt) => {
    const L = p.layout || { how: 'original' };
    let lay;
    if (L.how === 'original') lay = rt.file.layout(rt.frame.originalLayout);
    else if (L.how === 'name') lay = rt.file.layoutByName(rt.text(L.calc));
    else if (L.how === 'number') lay = rt.file.schema.layouts[Math.floor(rt.num(L.calc)) - 1];
    else lay = rt.file.layout(L.id);
    if (!lay) throw new FMError(105);
    await rt.win.setLayout(lay.id, { silent: false });
  });
  step('Go to Record/Request/Page', 'Navigation', [choice('which', 'Go to', [['first', 'First'], ['last', 'Last'], ['prev', 'Previous'], ['next', 'Next'], ['calc', 'By Calculation']]), calc('calc', 'Calculation', { opt: true }), bool('exitAfterLast', 'Exit after last', false), bool('dialog', 'With dialog', false)], async (p, rt, st, fr) => {
    const w = rt.win;
    if (w.mode === 'find') {
      const n = w.requests.length; let i = w.reqIndex;
      i = p.which === 'first' ? 0 : p.which === 'last' ? n - 1 : p.which === 'prev' ? i - 1 : p.which === 'next' ? i + 1 : Math.floor(rt.num(p.calc)) - 1;
      if (i < 0 || i >= n) { if (p.exitAfterLast && p.which === 'next') { fr.exitLoop = true; return; } throw new FMError(101); }
      w.reqIndex = i; w.render(); return;
    }
    if (w.mode === 'preview') {
      const n = w.previewPages || 1; let i = w.previewPage || 0;
      i = p.which === 'first' ? 0 : p.which === 'last' ? n - 1 : p.which === 'prev' ? i - 1 : p.which === 'next' ? i + 1 : Math.floor(rt.num(p.calc)) - 1;
      if (i < 0 || i >= n) { if (p.exitAfterLast && p.which === 'next') { fr.exitLoop = true; return; } throw new FMError(101); }
      w.previewPage = i; w.previewScrollTo = true; w.render(); return;
    }
    const n = w.foundRecords().length; let i = w.index;
    if (!n) throw new FMError(101);
    let target;
    if (p.which === 'calc' && p.dialog) {
      const v = await FM.prompt('Go to record number (1–' + n + '):', { title: 'Go to Record', value: String(i + 1) });
      if (v == null) throw new FMError(1);
      target = Math.floor(V.num(v)) - 1;
    } else target = p.which === 'first' ? 0 : p.which === 'last' ? n - 1 : p.which === 'prev' ? i - 1 : p.which === 'next' ? i + 1 : Math.floor(rt.num(p.calc)) - 1;
    if (target >= n && p.which === 'next' && p.exitAfterLast) { fr.exitLoop = true; return; }
    if (target < 0 && p.which === 'prev' && p.exitAfterLast) { fr.exitLoop = true; return; }
    if (target < 0 || target >= n) { if (p.which === 'calc') target = FM.clamp(target, 0, n - 1); else throw new FMError(101); }
    if (!(await w.goTo(target, { silent: false, rt }))) throw new FMError(301);
  });
  step('Go to Related Record', 'Navigation', [{ k: 'to', key: 'to', label: 'Get related record from' }, { k: 'layout', key: 'layout', label: 'Show using layout', noOriginal: false }, bool('onlyRelated', 'Show only related records', true), choice('match', 'Match', [['current', 'Match current record only'], ['found', 'Match all records in current found set']]), bool('newWindow', 'Show in new window', false), calc('winName', 'New window name', { opt: true })], async (p, rt) => {
    const w = rt.win; const file = rt.file;
    const toId = p.to; if (!file.to(toId)) throw new FMError(103);
    let recs;
    if (p.match === 'found') { const seen = new Set(); recs = []; w.foundRecords().forEach(r => file.related(w.to, r, toId).forEach(x => { if (!seen.has(x.id)) { seen.add(x.id); recs.push(x); } })); }
    else {
      const a = w.active;
      if (a && a.rowTO === toId && a.rowRec) recs = [a.rowRec];
      else recs = w.current() ? file.related(w.to, w.current(), toId) : [];
      if (a && a.portal && a.rowRec && a.rowTO !== toId) recs = file.related(a.rowTO, a.rowRec, toId);
    }
    if (!recs.length) throw new FMError(101);
    if (!(await w.commit({ rt }))) throw new FMError(301);
    let lay;
    const L = p.layout || { how: 'auto' };
    if (L.how === 'name') lay = file.layoutByName(rt.text(L.calc));
    else if (L.how === 'number') lay = file.schema.layouts[Math.floor(rt.num(L.calc)) - 1];
    else if (L.how === 'id') lay = file.layout(L.id);
    else lay = file.schema.layouts.find(l => l.to === toId) || file.schema.layouts.find(l => file.to(l.to).table === file.to(toId).table);
    if (!lay) throw new FMError(105);
    let target = w;
    if (p.newWindow) { target = await rt.app.newWindow(file, { name: p.winName ? rt.text(p.winName) : file.name + ' - ' + lay.name, layoutId: lay.id, style: p.winStyle || 'document' }); rt.win = target; }
    else await w.setLayout(lay.id, { silent: true });
    const set = target.set_();
    if (p.onlyRelated !== false) { set.ids = recs.map(r => r.id); set.index = 0; }
    else { const all = target.foundRecords(); const i = all.findIndex(r => r.id === recs[0].id); if (i < 0) { set.ids = file.records(target.table.id).map(r => r.id); } set.index = Math.max(0, set.ids.indexOf(recs[0].id)); }
    if (set.sort) target.applySort(set.sort, true);
    target.mode = 'browse';
    target.render();
    await rt.app.trigger(target, 'OnRecordLoad');
  });
  step('Go to Portal Row', 'Navigation', [choice('which', 'Go to', [['first', 'First'], ['last', 'Last'], ['prev', 'Previous'], ['next', 'Next'], ['calc', 'By Calculation']]), calc('calc', 'Calculation', { opt: true }), bool('select', 'Select entire contents', false), bool('exitAfterLast', 'Exit after last', false)], async (p, rt, st, fr) => {
    const w = rt.win;
    let portal = w.active && w.active.portal;
    const objs = FM.layoutObjects(w.layout).filter(o => o.type === 'portal');
    if (!portal) portal = objs[0];
    if (!portal) throw new FMError(101, 'There is no portal on this layout.');
    const ctx = w.ctx();
    const rows = w.portalRows(portal, ctx);
    if (!rows.length) throw new FMError(101);
    let i = w.active && w.active.portal === portal && w.active.rowRec ? rows.indexOf(w.active.rowRec) : -1;
    const n = rows.length;
    let t = p.which === 'first' ? 0 : p.which === 'last' ? n - 1 : p.which === 'prev' ? i - 1 : p.which === 'next' ? i + 1 : Math.floor(rt.num(p.calc)) - 1;
    if ((t >= n || t < 0) && p.exitAfterLast) { fr.exitLoop = true; return; }
    t = FM.clamp(t, 0, n - 1);
    w.active = Object.assign({}, w.active || {}, { portal, rowTO: portal.to, rowRec: rows[t], rowNumber: t + 1, obj: w.active && w.active.portal === portal ? w.active.obj : null });
    w.render();
    // move focus to the same field in the new row
    const key = w.active.key;
    if (key) setTimeout(() => { const el = w.el.querySelector('[data-fm-key="' + CSS.escape(key) + '"][data-fm-rec="' + rows[t].id + '"]'); if (el) { el.focus(); if (p.select && el.select) el.select(); } }, 0);
  });
  step('Go to Object', 'Navigation', [calc('name', 'Object name'), calc('rep', 'Repetition', { opt: true })], async (p, rt) => {
    const w = rt.win; const name = rt.text(p.name);
    const all = FM.layoutObjects(w.layout);
    const o = all.find(x => x.name && x.name.toLowerCase() === name.toLowerCase());
    if (!o) throw new FMError(112, 'There is no object named "' + name + '".');
    // bring tab/slide panels holding the object to the front
    all.filter(x => x.tabs).forEach(t => t.tabs.forEach((tb, i) => { if (tb.children && (tb.children.includes(o) || tb === o)) w.tabState[t.id] = i; }));
    all.filter(x => x.type === 'popover').forEach(pp => { if ((pp.children || []).includes(o) || pp === o) w.popovers[pp.id] = true; });
    if (o.tabs) { /* the tab control itself */ }
    const tabOwner = all.find(x => x.tabs && x.tabs.some(tb => tb.name && tb.name.toLowerCase() === name.toLowerCase()));
    if (tabOwner) w.tabState[tabOwner.id] = tabOwner.tabs.findIndex(tb => tb.name && tb.name.toLowerCase() === name.toLowerCase());
    w.render();
    if (o.type === 'field') { const rep = p.rep ? Math.floor(rt.num(p.rep)) : 1; const el = w.el.querySelector('[data-fm-obj="' + o.id + '"][data-fm-rep="' + rep + '"]'); if (el) el.focus(); }
    else { const el = w.el.querySelector('[data-obj-name="' + CSS.escape(o.name) + '"]'); if (el) el.scrollIntoView({ block: 'nearest' }); w.active = Object.assign({}, w.active || {}, { obj: o }); }
  });
  step('Go to Field', 'Navigation', [field('field', 'Field', { opt: true }), bool('select', 'Select/perform', false), calc('rep', 'Repetition', { opt: true })], async (p, rt) => {
    const w = rt.win;
    if (!p.field) { const a = document.activeElement; if (a && w.el.contains(a)) a.blur(); await FM.sleep(0); w.active = null; return; }
    const rep = p.rep ? Math.floor(rt.num(p.rep)) : 1;
    const sel = '[data-fm-key="' + CSS.escape(p.field) + '"][data-fm-rep="' + rep + '"]';
    let el = w.el.querySelector(sel);
    if (!el) {
      // the field may be on a hidden tab panel
      const all = FM.layoutObjects(w.layout);
      const o = all.find(x => x.type === 'field' && x.field === p.field);
      if (o) { all.filter(x => x.tabs).forEach(t => t.tabs.forEach((tb, i) => { if ((tb.children || []).includes(o)) w.tabState[t.id] = i; })); w.render(); el = w.el.querySelector(sel); }
    }
    if (!el) throw new FMError(102, 'The field is not on this layout.');
    el.focus();
    if (p.select && el.select) el.select();
  });
  step('Go to Next Field', 'Navigation', [], async (p, rt) => { const a = document.activeElement; if (a && rt.win.el.contains(a)) rt.win.tabNext(a, 1); else rt.win.focusFirst(); });
  step('Go to Previous Field', 'Navigation', [], async (p, rt) => { const a = document.activeElement; if (a && rt.win.el.contains(a)) rt.win.tabNext(a, -1); else rt.win.focusFirst(); });
  step('Enter Browse Mode', 'Navigation', [bool('pause', 'Pause', false)], async (p, rt) => { await rt.win.setMode('browse', { rt }); if (p.pause) await rt.pause(); });
  step('Enter Find Mode', 'Navigation', [bool('pause', 'Pause', false), { k: 'requests', key: 'requests', label: 'Specify find requests', opt: true }], async (p, rt) => {
    await rt.win.setMode('find', { rt });
    if (p.requests && p.requests.length) { rt.win.requests = FM.clone(p.requests).map(r => ({ omit: r.omit, crit: Object.assign({}, ...Object.entries(r.crit).map(([k, v]) => ({ [k]: rt.crit(v) }))) })); rt.win.reqIndex = 0; rt.win.render(); }
    if (p.pause) { const r = await rt.pause({ find: true }); if (r === 'find') await rt.win.performFind(null, { silent: rt.errorCapture }); }
  });
  step('Enter Preview Mode', 'Navigation', [bool('pause', 'Pause', false)], async (p, rt) => { await rt.win.setMode('preview', { rt }); if (p.pause) await rt.pause(); });
  step('Close Popover', 'Navigation', [], async (p, rt) => { rt.win.popovers = {}; await rt.win.commit({ rt }); rt.win.render(); });
  planned('Go to List of Records', 'Navigation');

  // ── Editing ─────────────────────────────────────────────────────────────
  const activeInput = rt => { const a = document.activeElement; return a && rt.win.el && rt.win.el.contains(a) && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA') ? a : null; };
  step('Undo/Redo', 'Editing', [choice('what', 'Action', [['undo', 'Undo'], ['redo', 'Redo'], ['toggle', 'Toggle']])], async (p) => { document.execCommand(p.what === 'redo' ? 'redo' : 'undo'); });
  step('Cut', 'Editing', [field('field', 'Field', { opt: true })], async (p, rt) => { const el = activeInput(rt); if (!el) throw new FMError(3); const t = el.value.slice(el.selectionStart, el.selectionEnd) || el.value; rt.app.clipboard = t; try { await navigator.clipboard.writeText(t); } catch (e) { /* clipboard blocked */ } el.setRangeText('', el.selectionStart === el.selectionEnd ? 0 : el.selectionStart, el.selectionStart === el.selectionEnd ? el.value.length : el.selectionEnd); el.dispatchEvent(new Event('input')); });
  step('Copy', 'Editing', [field('field', 'Field', { opt: true })], async (p, rt) => {
    let t;
    if (p.field) t = rt.file.display(rt.target(p.field).rec, p.field, 1, rt.ctx());
    else { const el = activeInput(rt); t = el ? (el.value.slice(el.selectionStart, el.selectionEnd) || el.value) : ''; }
    rt.app.clipboard = t; try { await navigator.clipboard.writeText(t); } catch (e) { /* clipboard blocked */ }
  });
  step('Paste', 'Editing', [field('field', 'Field', { opt: true }), bool('noStyle', 'No style', false)], async (p, rt) => {
    let t = rt.app.clipboard || '';
    try { t = await navigator.clipboard.readText(); } catch (e) { /* use the in-app clipboard */ }
    if (p.field) { const tg = rt.target(p.field); await rt.setField(p.field, tg, t); return; }
    const el = activeInput(rt); if (!el) throw new FMError(3);
    el.setRangeText(t, el.selectionStart, el.selectionEnd, 'end'); el.dispatchEvent(new Event('input'));
  });
  step('Clear', 'Editing', [field('field', 'Field', { opt: true })], async (p, rt) => {
    if (p.field) { await rt.setField(p.field, rt.target(p.field), ''); return; }
    const el = activeInput(rt); if (!el) throw new FMError(3);
    if (el.selectionStart === el.selectionEnd) el.value = ''; else el.setRangeText('', el.selectionStart, el.selectionEnd);
    el.dispatchEvent(new Event('input'));
  });
  step('Set Selection', 'Editing', [field('field', 'Field', { opt: true }), calc('start', 'Start position'), calc('end', 'End position')], async (p, rt) => {
    if (p.field) await STEPS['Go to Field'].run({ field: p.field }, rt);
    const el = activeInput(rt); if (!el) throw new FMError(3);
    const s = Math.max(0, Math.floor(rt.num(p.start)) - 1), e = Math.max(s, Math.floor(rt.num(p.end)));
    el.setSelectionRange(s, e);
  });
  step('Select All', 'Editing', [], async (p, rt) => { const el = activeInput(rt); if (el) el.select(); });
  step('Perform Find/Replace', 'Editing', [calc('find', 'Find what'), calc('replace', 'Replace with', { opt: true }), choice('action', 'Action', [['replaceall', 'Replace All'], ['find', 'Find Next']]), bool('matchCase', 'Match case', false), bool('wholeWords', 'Whole words only', false), choice('scope', 'Search across', [['all', 'All records'], ['current', 'Current record']]), bool('dialog', 'With dialog', false)], async (p, rt) => {
    await FM.dlg.findReplace(rt.win, { find: rt.text(p.find), replace: p.replace ? rt.text(p.replace) : '', action: p.action, matchCase: p.matchCase, wholeWords: p.wholeWords, scope: p.scope, dialog: p.dialog, rt });
  });

  // ── Fields ──────────────────────────────────────────────────────────────
  step('Set Field', 'Fields', [field('field', 'Target field', { opt: true }), calc('calc', 'Calculated result'), calc('rep', 'Repetition', { opt: true })], async (p, rt) => {
    const key = p.field || (rt.win.active && rt.win.active.key);
    if (!key) throw new FMError(102, 'There is no target field and no field is active.');
    const v = rt.ev(p.calc || '');
    await rt.setField(key, rt.target(key), v, p.rep ? Math.floor(rt.num(p.rep)) : (rt.win.active && rt.win.active.key === key && !p.field ? rt.win.active.rep : 1));
  });
  step('Set Field By Name', 'Fields', [calc('name', 'Target field name'), calc('calc', 'Calculated result')], async (p, rt) => {
    const nm = rt.text(p.name); const m = nm.match(/^(.*?)(?:\[(\d+)\])?$/);
    const key = rt.file.keyByName(m[1], rt.win.to);
    if (!key) throw new FMError(102, 'The field "' + nm + '" cannot be found.');
    await rt.setField(key, rt.target(key), rt.ev(p.calc || ''), m[2] ? +m[2] : 1);
  });
  step('Set Next Serial Value', 'Fields', [field('field', 'Field'), calc('calc', 'Next value')], async (p, rt) => {
    const f = rt.file.fieldByKey(p.field); if (!f) throw new FMError(102);
    const r = await rt.file.api('POST', '/serials', { field: f.id, next: rt.text(p.calc) });
    rt.file.serials = r.serials;
  });
  step('Insert Text', 'Fields', [field('field', 'Target field', { opt: true }), { k: 'longtext', key: 'text', label: 'Text' }, bool('select', 'Select entire contents', false)], async (p, rt) => rt.insert(p.field, p.text || '', p.select));
  step('Insert Calculated Result', 'Fields', [field('field', 'Target field', { opt: true }), calc('calc', 'Calculated result'), bool('select', 'Select entire contents', false)], async (p, rt) => rt.insert(p.field, V.text(rt.ev(p.calc || '')), p.select));
  step('Insert From Last Visited', 'Fields', [field('field', 'Target field', { opt: true }), bool('select', 'Select entire contents', false)], async (p, rt) => {
    const key = p.field || (rt.win.active && rt.win.active.key); if (!key) throw new FMError(102);
    const last = rt.win.lastVisited(rt.win.table.id); if (!last) throw new FMError(101);
    await rt.setField(key, rt.target(key), rt.file.keyValue(key, last, rt.win.ctx(last)));
  });
  step('Insert From URL', 'Fields', [{ k: 'fieldOrVar', key: 'target', label: 'Target' }, calc('url', 'URL'), bool('verify', 'Verify SSL certificates', true), calc('curl', 'cURL options', { opt: true }), bool('select', 'Select entire contents', false), bool('dialog', 'With dialog', false)], async (p, rt) => {
    const url = rt.text(p.url);
    const opts = parseCurl(p.curl ? rt.text(p.curl) : '', rt);
    let r;
    try { r = await rt.file.api('POST', '/fetch', { url, method: opts.method, headers: opts.headers, body: opts.body }); }
    catch (e) { throw new FMError(e.fmError || 1631, e.message); }
    let out = r.text != null ? r.text : '';
    if (r.base64 != null && p.target && p.target.field) {
      const bytes = Uint8Array.from(atob(r.base64), c => c.charCodeAt(0));
      const name = decodeURIComponent((url.split('?')[0].split('/').pop() || 'download')) || 'download';
      const fd = new FormData(); fd.append('file', new File([bytes], name, { type: (r.contentType || '').split(';')[0] || 'application/octet-stream' }));
      const up = await rt.file.api('POST', '/containers', fd);
      out = up.value;
    }
    if (opts.dumpHeaders) rt.file.setVar(opts.dumpHeaders, Object.entries(r.headers || {}).map(([k, v]) => k + ': ' + v).join('\n'), 1, rt.ctx());
    if (p.target && p.target.var) rt.file.setVar(p.target.var, out, 1, rt.ctx());
    else if (p.target && p.target.field) await rt.setField(p.target.field, rt.target(p.target.field), out);
    if (r.status >= 400) { rt.lastErrorDetail = 'HTTP ' + r.status; throw new FMError(1631, 'The server answered with HTTP ' + r.status + '.'); }
  }, { note: 'Fetched by the host so any public web address works; private and local network addresses are refused.' });
  step('Insert Current Date', 'Fields', [field('field', 'Target field', { opt: true }), bool('select', 'Select entire contents', false)], async (p, rt) => rt.insert(p.field, D.formatDate(D.todayNum()), p.select, true));
  step('Insert Current Time', 'Fields', [field('field', 'Target field', { opt: true }), bool('select', 'Select entire contents', false)], async (p, rt) => rt.insert(p.field, D.formatTime(D.nowSeconds()), p.select, true));
  step('Insert Current User Name', 'Fields', [field('field', 'Target field', { opt: true }), bool('select', 'Select entire contents', false)], async (p, rt) => rt.insert(p.field, rt.app.userName(), p.select));
  const insertFile = accept => async (p, rt) => {
    const key = p.field || (rt.win.active && rt.win.active.key); if (!key) throw new FMError(102);
    const f = await FM.pickFile(accept); if (!f) throw new FMError(1);
    const fd = new FormData(); fd.append('file', f);
    const up = await rt.file.api('POST', '/containers', fd);
    await rt.setField(key, rt.target(key), up.value);
  };
  step('Insert Picture', 'Fields', [field('field', 'Target field', { opt: true })], insertFile('image/*'));
  step('Insert Audio/Video', 'Fields', [field('field', 'Target field', { opt: true })], insertFile('audio/*,video/*'));
  step('Insert PDF', 'Fields', [field('field', 'Target field', { opt: true })], insertFile('application/pdf'));
  step('Insert File', 'Fields', [field('field', 'Target field', { opt: true })], insertFile(''));
  step('Replace Field Contents', 'Fields', [field('field', 'Field'), choice('how', 'Replace with', [['calc', 'Calculated result'], ['serial', 'Serial numbers'], ['current', 'Current contents']]), calc('calc', 'Calculation', { opt: true }), calc('start', 'Initial serial value', { opt: true }), calc('incr', 'Increment by', { opt: true }), bool('dialog', 'With dialog', false), bool('updateSerial', 'Update serial number in Entry Options', false)], async (p, rt) => {
    await FM.dlg.replaceFieldContents(rt.win, Object.assign({}, p, { rt, dialog: p.dialog }));
  });
  step('Relookup Field Contents', 'Fields', [field('field', 'Match field'), bool('dialog', 'With dialog', false)], async (p, rt) => {
    const w = rt.win; const f = rt.file.fieldByKey(p.field); if (!f) throw new FMError(102);
    if (p.dialog && !(await FM.confirm('Relookup field contents for ' + w.foundRecords().length + ' records using the match field "' + f.name + '"?', { ok: 'OK' }))) throw new FMError(1);
    if (!(await w.commit({ rt }))) throw new FMError(301);
    const table = w.table; const toId = rt.file.baseTO(table.id).id;
    const ops = [];
    for (const rec of w.foundRecords()) {
      const data = {};
      table.fields.forEach(tf => {
        const lk = ((tf.options || {}).autoEnter || {}).lookup; if (!lk || !lk.to) return;
        const pth = rt.file.path(toId, lk.to); if (!pth || !(pth[0].rel.predicates || []).some(pr => (pth[0].fromLeft ? pr.leftField : pr.rightField) === f.id)) return;
        const v = rt.file.lookupValue(tf, lk, rec, toId); if (v !== undefined) data[tf.id] = v;
      });
      if (Object.keys(data).length) ops.push({ op: 'update', id: rec.id, data, mc: rec.mc });
    }
    if (ops.length) await rt.file.batch(ops);
    w.render();
  });
  step('Export Field Contents', 'Fields', [field('field', 'Field'), calc('name', 'Output file name', { opt: true }), bool('auto', 'Automatically open', false)], async (p, rt) => {
    const key = p.field || (rt.win.active && rt.win.active.key); if (!key) throw new FMError(102);
    const tg = rt.target(key); const f = rt.file.fieldByKey(key);
    const raw = rt.file.raw(tg.rec, f, 1);
    if (raw && typeof raw === 'object' && raw.c) { const a = h('a', { href: '/filemaker/api/files/' + rt.file.id + '/containers/' + raw.c + '?download=1', download: raw.name }); document.body.appendChild(a); a.click(); a.remove(); return; }
    FM.download(p.name ? rt.text(p.name) : (f.name + '.txt'), rt.file.display(tg.rec, key, 1, rt.ctx()));
  });
  planned('Insert From Index', 'Fields');
  planned('Insert From Device', 'Fields');

  // ── Records ─────────────────────────────────────────────────────────────
  step('New Record/Request', 'Records', [], async (p, rt) => { const w = rt.win; if (w.mode === 'find') w.newRequest(); else await w.newRecord({ silent: false, rt }); });
  step('Duplicate Record/Request', 'Records', [], async (p, rt) => { const w = rt.win; if (w.mode === 'find') w.duplicateRequest(); else await w.duplicateRecord({ rt }); });
  step('Delete Record/Request', 'Records', [bool('dialog', 'With dialog', true)], async (p, rt) => { const w = rt.win; if (w.mode === 'find') { w.deleteRequest(); return; } await w.deleteRecord({ noDialog: !p.dialog, silent: false, rt, whole: !(w.active && w.active.portal) }); });
  step('Delete Portal Row', 'Records', [bool('dialog', 'With dialog', true)], async (p, rt) => { await rt.win.deletePortalRow({ noDialog: !p.dialog, rt }); });
  step('Delete All Records', 'Records', [bool('dialog', 'With dialog', true)], async (p, rt) => { await rt.win.deleteAll({ noDialog: !p.dialog, rt }); });
  step('Truncate Table', 'Records', [{ k: 'table', key: 'table', label: 'Table' }, bool('dialog', 'With dialog', true)], async (p, rt) => {
    const t = rt.file.table(p.table) || rt.win.table; if (!t) throw new FMError(106);
    if (p.dialog && !(await FM.confirm('Permanently delete ALL records in the table "' + t.name + '"? This cannot be undone.', { ok: 'Truncate' }))) throw new FMError(1);
    const ids = rt.file.records(t.id).map(r => r.id);
    for (let i = 0; i < ids.length; i += 5000) await rt.file.batch(ids.slice(i, i + 5000).map(id => ({ op: 'delete', id })));
    rt.win.render();
  });
  step('Open Record/Request', 'Records', [], async (p, rt) => { const r = rt.win.current(); if (!r) throw new FMError(101); await rt.win.open(r); });
  step('Revert Record/Request', 'Records', [bool('dialog', 'With dialog', true)], async (p, rt) => {
    if (p.dialog && rt.win.isDirty() && !(await FM.confirm('Revert record to the last saved version?', { ok: 'Revert' }))) throw new FMError(1);
    await rt.win.revert();
  });
  step('Commit Records/Requests', 'Records', [bool('skipValidation', 'Skip data entry validation', false), bool('override', 'Override ESS locking conflicts', false), bool('dialog', 'With dialog', false)], async (p, rt) => {
    if (rt.win.mode === 'find') return;
    const a = document.activeElement; if (a && rt.win.el && rt.win.el.contains(a)) { a.blur(); await FM.sleep(0); await (rt.app.blurring || Promise.resolve()); }
    const ok = await rt.win.commit({ skipValidation: p.skipValidation, silent: rt.errorCapture, rt, noRender: false });
    if (!ok) throw new FMError(509, 'The record could not be committed.');
  });
  step('Copy Record/Request', 'Records', [], async (p, rt) => {
    const w = rt.win; const r = w.current(); if (!r) throw new FMError(101);
    const t = FM.layoutFields(w.layout).map(k => w.file.display(r, k, 1, w.ctx(r))).join('\t');
    rt.app.clipboard = t; try { await navigator.clipboard.writeText(t); } catch (e) { /* in-app clipboard */ }
  });
  step('Copy All Records/Requests', 'Records', [], async (p, rt) => {
    const w = rt.win; const keys = FM.layoutFields(w.layout);
    const t = w.foundRecords().map(r => keys.map(k => w.file.display(r, k, 1, w.ctx(r)).replace(/\n/g, '\u000b')).join('\t')).join('\n');
    rt.app.clipboard = t; try { await navigator.clipboard.writeText(t); } catch (e) { /* in-app clipboard */ }
  });
  step('Import Records', 'Records', [bool('dialog', 'With dialog', true), { k: 'importspec', key: 'spec', label: 'Import order', opt: true }], async (p, rt) => { await FM.dlg.importRecords(rt.win, { spec: p.spec, rt }); });
  step('Export Records', 'Records', [bool('dialog', 'With dialog', true), { k: 'exportspec', key: 'spec', label: 'Export order', opt: true }, calc('name', 'Output file name', { opt: true })], async (p, rt) => {
    await FM.dlg.exportRecords(rt.win, { spec: p.spec, dialog: p.dialog || !p.spec, filename: p.name ? rt.text(p.name) : '', rt });
  });
  step('Save Records as Excel', 'Records', [bool('dialog', 'With dialog', false), calc('name', 'Output file name', { opt: true }), choice('which', 'Save', [['found', 'Records being browsed'], ['current', 'Current record']])], async (p, rt) => {
    await FM.dlg.saveAsExcel(rt.win, { filename: p.name ? rt.text(p.name) : '', current: p.which === 'current', dialog: p.dialog });
  });
  step('Save Records as PDF', 'Records', [bool('dialog', 'With dialog', false), choice('which', 'Save', [['found', 'Records being browsed'], ['current', 'Current record'], ['blank', 'Blank record']])], async (p, rt) => {
    const w = rt.win; const prev = { mode: w.mode, set: w.set_().ids.slice(), index: w.index };
    if (p.which === 'current' && w.current()) w.set_().ids = [w.current().id];
    await w.setMode('preview', { rt });
    await FM.sleep(50);
    rt.app.print(w);
    w.set_().ids = prev.set; w.set_().index = prev.index;
    if (prev.mode !== 'preview') await w.setMode(prev.mode, { rt });
  }, { note: 'Opens the browser\'s print dialog; choose "Save as PDF".' });
  planned('Save Records as JSONL', 'Records');
  planned('Save Records as Snapshot Link', 'Records');

  // ── Found Sets ──────────────────────────────────────────────────────────
  step('Show All Records', 'Found Sets', [], async (p, rt) => { await rt.win.showAll({ rt }); });
  step('Show Omitted Only', 'Found Sets', [], async (p, rt) => { await rt.win.showOmitted({ rt }); });
  step('Omit Record', 'Found Sets', [], async (p, rt) => { if (rt.win.mode === 'find') { rt.win.requests[rt.win.reqIndex].omit = !rt.win.requests[rt.win.reqIndex].omit; rt.win.render(); return; } await rt.win.omit(1, { rt }); });
  step('Omit Multiple Records', 'Found Sets', [calc('n', 'Number of records', { opt: true }), bool('dialog', 'With dialog', true)], async (p, rt) => {
    let n = p.n ? Math.floor(rt.num(p.n)) : 1;
    if (p.dialog) { const v = await FM.prompt('Omit how many records (starting with the current one)?', { title: 'Omit Multiple Records', value: String(n) }); if (v == null) throw new FMError(1); n = Math.floor(V.num(v)); }
    await rt.win.omit(Math.max(1, n), { rt });
  });
  step('Perform Quick Find', 'Found Sets', [calc('calc', 'Search text')], async (p, rt) => { await rt.win.quickFindRun(rt.text(p.calc), { silent: rt.errorCapture, rt }); });
  const reqParam = { k: 'requests', key: 'requests', label: 'Specify find requests', opt: true };
  const runFind = how => async (p, rt) => {
    const w = rt.win;
    let reqs;
    if (p.requests && p.requests.length) reqs = p.requests.map(r => ({ omit: r.omit, crit: Object.assign({}, ...Object.entries(r.crit).map(([k, v]) => ({ [k]: rt.crit(v) }))) }));
    else if (w.mode === 'find') reqs = w.requests;
    else if (how === 'replace') reqs = w.set_().lastFind;
    if (!reqs) throw new FMError(400);
    if (w.mode !== 'find' && !(await w.commit({ rt }))) throw new FMError(301);
    if (w.mode === 'layout') await w.setMode('browse', { rt });
    await w.performFind(reqs, { how, silent: rt.errorCapture, rt });
  };
  step('Perform Find', 'Found Sets', [reqParam], runFind('replace'));
  step('Constrain Found Set', 'Found Sets', [reqParam], runFind('constrain'));
  step('Extend Found Set', 'Found Sets', [reqParam], runFind('extend'));
  step('Modify Last Find', 'Found Sets', [], async (p, rt) => { await rt.win.setMode('find', { restore: true, rt }); });
  step('Sort Records', 'Found Sets', [{ k: 'sort', key: 'sort', label: 'Specify sort order', opt: true }, bool('dialog', 'With dialog', true)], async (p, rt) => {
    const w = rt.win;
    let spec = p.sort;
    if (p.dialog || !spec || !spec.length) { spec = await FM.dlg.sortDialog(w, spec || w.set_().sort || []); if (!spec) throw new FMError(1); }
    if (!(await w.commit({ rt }))) throw new FMError(301);
    w.applySort(spec);
  });
  step('Sort Records by Field', 'Found Sets', [field('field', 'Field'), choice('dir', 'Order', [['asc', 'Ascending'], ['desc', 'Descending'], ['toggle', 'Toggle']])], async (p, rt) => {
    const w = rt.win; const key = p.field || (w.active && w.active.key); if (!key) throw new FMError(102);
    let dir = p.dir;
    if (dir === 'toggle') { const cur = (w.set_().sort || []).find(s => s.key === key); dir = cur && cur.dir === 'asc' ? 'desc' : 'asc'; }
    if (!(await w.commit({ rt }))) throw new FMError(301);
    w.applySort([{ key, dir }]);
  });
  step('Unsort Records', 'Found Sets', [], async (p, rt) => { const w = rt.win; const s = w.set_(); const recs = w.foundRecords().sort((a, b) => a.id - b.id); s.ids = recs.map(r => r.id); s.sort = null; s.index = 0; w.render(); });
  step('Find Matching Records', 'Found Sets', [choice('how', 'Find', [['replace', 'Replace found set'], ['constrain', 'Constrain found set'], ['extend', 'Extend found set']]), field('field', 'Field', { opt: true })], async (p, rt) => {
    const key = p.field || (rt.win.active && rt.win.active.key); if (!key) throw new FMError(102);
    await rt.win.findMatching(key, p.how, { silent: rt.errorCapture, rt });
  });

  // ── Windows ─────────────────────────────────────────────────────────────
  step('New Window', 'Windows', [choice('style', 'Window style', [['document', 'Document'], ['floating', 'Floating Document'], ['dialog', 'Dialog'], ['card', 'Card']]), calc('name', 'Window name', { opt: true }), { k: 'layout', key: 'layout', label: 'Layout', opt: true }, calc('height', 'Height', { opt: true }), calc('width', 'Width', { opt: true }), calc('top', 'Top', { opt: true }), calc('left', 'Left', { opt: true }), bool('close', 'Close', true), bool('toolbars', 'Toolbars', true)], async (p, rt) => {
    const w = rt.win;
    let layoutId = w.layoutId;
    const L = p.layout;
    if (L && L.how === 'id') layoutId = L.id; else if (L && L.how === 'name') { const l = rt.file.layoutByName(rt.text(L.calc)); if (l) layoutId = l.id; }
    if (!(await w.commit({ rt }))) throw new FMError(301);
    const nw = await rt.app.newWindow(rt.file, {
      name: p.name ? rt.text(p.name) : (w.name + ' - 2'), style: p.style || 'document', layoutId, parent: w,
      w: p.width ? rt.num(p.width) : null, h: p.height ? rt.num(p.height) : null, x: p.left ? rt.num(p.left) : null, y: p.top ? rt.num(p.top) : null,
      toolbar: p.toolbars !== false && p.style !== 'card', closable: p.close !== false, copySet: w
    });
    rt.win = nw;
  });
  step('Select Window', 'Windows', [choice('which', 'Window', [['current', 'Current window'], ['name', 'Window name']]), calc('name', 'Window name', { opt: true })], async (p, rt) => {
    if (p.which !== 'name') { rt.app.focusWindow(rt.win); return; }
    const name = rt.text(p.name); const w = rt.app.windows.find(x => x.name.toLowerCase() === name.toLowerCase());
    if (!w) throw new FMError(112);
    rt.win = w; rt.app.focusWindow(w);
  });
  step('Close Window', 'Windows', [choice('which', 'Window', [['current', 'Current window'], ['name', 'Window name']]), calc('name', 'Window name', { opt: true })], async (p, rt) => {
    let w = rt.win;
    if (p.which === 'name') { const name = rt.text(p.name); w = rt.app.windows.find(x => x.name.toLowerCase() === name.toLowerCase()); if (!w) throw new FMError(112); }
    const wasCurrent = w === rt.win;
    await rt.app.closeWindow(w, { rt });
    if (wasCurrent) rt.win = rt.app.activeWindow(rt.file) || null;
    if (!rt.win) rt.halted = true;
  });
  step('Adjust Window', 'Windows', [choice('how', 'Adjust', [['fit', 'Resize to Fit'], ['maximize', 'Maximize'], ['minimize', 'Minimize'], ['restore', 'Restore'], ['hide', 'Hide']])], async (p, rt) => rt.app.adjustWindow(rt.win, p.how));
  step('Move/Resize Window', 'Windows', [choice('which', 'Window', [['current', 'Current window'], ['name', 'Window name']]), calc('name', 'Window name', { opt: true }), calc('height', 'Height', { opt: true }), calc('width', 'Width', { opt: true }), calc('top', 'Top', { opt: true }), calc('left', 'Left', { opt: true })], async (p, rt) => {
    let w = rt.win; if (p.which === 'name') { w = rt.app.windows.find(x => x.name.toLowerCase() === rt.text(p.name).toLowerCase()); if (!w) throw new FMError(112); }
    rt.app.moveWindow(w, { x: p.left ? rt.num(p.left) : null, y: p.top ? rt.num(p.top) : null, w: p.width ? rt.num(p.width) : null, h: p.height ? rt.num(p.height) : null });
  });
  step('Arrange All Windows', 'Windows', [choice('how', 'Arrange', [['tile_h', 'Tile Horizontally'], ['tile_v', 'Tile Vertically'], ['cascade', 'Cascade Window'], ['front', 'Bring All to Front']])], async (p, rt) => rt.app.arrangeWindows(p.how));
  step('Freeze Window', 'Windows', [], async (p, rt) => { if (!rt.frozen.has(rt.win)) { rt.frozen.add(rt.win); rt.win.frozen++; } });
  step('Refresh Window', 'Windows', [bool('flushJoin', 'Flush cached join results', false), bool('flushSQL', 'Flush cached external data', false)], async (p, rt) => {
    if (p.flushJoin) rt.file.touch();
    rt.frozen.forEach(w => { w.frozen = Math.max(0, w.frozen - 1); }); rt.frozen.clear();
    rt.win.render();
  });
  step('Scroll Window', 'Windows', [choice('to', 'Scroll', [['home', 'Home'], ['end', 'End'], ['pageup', 'Page Up'], ['pagedown', 'Page Down'], ['field', 'To Selection']])], async (p, rt) => {
    const c = rt.win.el && rt.win.el.querySelector('.fm-content'); if (!c) return;
    if (p.to === 'home') c.scrollTop = 0; else if (p.to === 'end') c.scrollTop = c.scrollHeight; else if (p.to === 'pageup') c.scrollTop -= c.clientHeight; else if (p.to === 'pagedown') c.scrollTop += c.clientHeight; else { const a = document.activeElement; if (a && c.contains(a)) a.scrollIntoView({ block: 'nearest' }); }
  });
  step('Show/Hide Menubar', 'Windows', [choice('how', 'Action', [['show', 'Show'], ['hide', 'Hide'], ['toggle', 'Toggle']]), bool('lock', 'Lock', false)], async (p, rt) => rt.app.showMenubar(p.how));
  step('Show/Hide Toolbars', 'Windows', [choice('how', 'Action', [['show', 'Show'], ['hide', 'Hide'], ['toggle', 'Toggle']]), bool('lock', 'Lock', false)], async (p, rt) => { const w = rt.win; w.toolbar = p.how === 'show' ? true : p.how === 'hide' ? false : !w.toolbar; w.toolbarLocked = !!p.lock; w.render(); });
  step('Show/Hide Text Ruler', 'Windows', [choice('how', 'Action', [['show', 'Show'], ['hide', 'Hide'], ['toggle', 'Toggle']])], async () => { });
  step('Set Window Title', 'Windows', [choice('which', 'Window', [['current', 'Current window'], ['name', 'Window name']]), calc('name', 'Window name', { opt: true }), calc('title', 'New title')], async (p, rt) => {
    let w = rt.win; if (p.which === 'name') { w = rt.app.windows.find(x => x.name.toLowerCase() === rt.text(p.name).toLowerCase()); if (!w) throw new FMError(112); }
    w.name = rt.text(p.title); rt.app.renderWindowList(); w.render();
  });
  step('Set Zoom Level', 'Windows', [choice('zoom', 'Zoom', [['100', '100%'], ['in', 'Zoom In'], ['out', 'Zoom Out'], ['25', '25%'], ['50', '50%'], ['75', '75%'], ['150', '150%'], ['200', '200%'], ['300', '300%'], ['400', '400%']]), bool('lock', 'Lock', false)], async (p, rt) => {
    const w = rt.win; const steps = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4];
    if (p.zoom === 'in') w.zoom = steps.find(z => z > w.zoom + 0.01) || 4; else if (p.zoom === 'out') w.zoom = [...steps].reverse().find(z => z < w.zoom - 0.01) || 0.25; else w.zoom = (+p.zoom || 100) / 100;
    w.render();
  });
  step('View As', 'Windows', [choice('view', 'View', [['form', 'View as Form'], ['list', 'View as List'], ['table', 'View as Table'], ['cycle', 'Cycle']])], async (p, rt) => {
    const w = rt.win; let v = p.view;
    if (v === 'cycle') { const order = ['form', 'list', 'table'].filter(x => (w.layout.views || {})[x] !== false); v = order[(order.indexOf(w.view) + 1) % order.length]; }
    await w.setView(v);
  });
  step('Refresh Portal', 'Windows', [calc('name', 'Object name')], async (p, rt) => { rt.file.touch(); rt.win.render(); });
  step('Refresh Object', 'Windows', [calc('name', 'Object name'), calc('rep', 'Repetition', { opt: true })], async (p, rt) => { rt.win.render(); });

  // ── Files ───────────────────────────────────────────────────────────────
  step('New File', 'Files', [], async (p, rt) => { await rt.app.newFileDialog(); });
  step('Open File', 'Files', [calc('name', 'File name'), bool('hidden', 'Open hidden', false)], async (p, rt) => {
    const name = rt.text(p.name);
    const list = await FM.api('GET', '/files');
    const f = list.files.find(x => x.name.toLowerCase() === name.toLowerCase());
    if (!f) throw new FMError(100, 'The file "' + name + '" could not be found on the host.');
    await rt.app.openFile(f.id);
  });
  step('Close File', 'Files', [choice('which', 'File', [['current', 'Current file'], ['name', 'File name']]), calc('name', 'File name', { opt: true })], async (p, rt) => {
    let f = rt.file;
    if (p.which === 'name') { f = rt.app.openFiles().find(x => x.name.toLowerCase() === rt.text(p.name).toLowerCase()); if (!f) throw new FMError(100); }
    rt.halted = f === rt.file;
    await rt.app.closeFile(f);
  });
  step('Set Multi-User', 'Files', [choice('how', 'Mode', [['on', 'On'], ['hidden', 'On (Hidden)'], ['off', 'Off']])], async () => { }, { note: 'Every file on this host is shared.' });
  step('Set Use System Formats', 'Files', [bool('on', 'On', true)], async () => { });
  step('Save a Copy as', 'Files', [calc('name', 'Copy name', { opt: true }), choice('how', 'Type', [['copy', 'Copy of current file'], ['clone', 'Clone (no records)']])], async (p, rt) => {
    if (!rt.file.full) throw new FMError(200);
    const r = await rt.file.api('POST', '/copy', { name: p.name ? rt.text(p.name) : '', mode: p.how });
    FM.toast('Saved "' + r.name + '" on the host.');
  });
  step('Print Setup', 'Files', [bool('dialog', 'With dialog', true)], async (p, rt) => { if (p.dialog !== false) await FM.dlg.pageSetup(rt.file); });
  step('Print', 'Files', [bool('dialog', 'With dialog', true), choice('which', 'Print', [['found', 'Records being browsed'], ['current', 'Current record']])], async (p, rt) => {
    const w = rt.win; const prevMode = w.mode; const ids = w.set_().ids.slice(), idx = w.index;
    if (!rt.file.pset().printing && !rt.file.full) throw new FMError(200, 'Your privileges do not allow printing.');
    if (p.which === 'current' && w.current()) w.set_().ids = [w.current().id];
    if (w.mode !== 'preview') await w.setMode('preview', { rt });
    await FM.sleep(50); rt.app.print(w);
    w.set_().ids = ids; w.set_().index = idx;
    if (prevMode !== 'preview') await w.setMode(prevMode, { rt });
  });
  ['Convert File', 'Recover File', 'Get File Exists', 'Get File Size', 'Create Data File', 'Open Data File', 'Read from Data File', 'Write to Data File', 'Set Data File Position', 'Get Data File Position', 'Close Data File', 'Rename File', 'Delete File'].forEach(n => planned(n, 'Files'));

  // ── Accounts ────────────────────────────────────────────────────────────
  step('Add Account', 'Accounts', [calc('name', 'Account name'), calc('password', 'Password'), { k: 'pset', key: 'pset', label: 'Privilege set' }, bool('mustChange', 'User must change password on next login', false)], async (p, rt) => {
    await rt.accounts([{ op: 'add', name: rt.text(p.name), password: rt.text(p.password), privilegeSet: p.pset || 'PS_ENTRY', mustChange: !!p.mustChange }]);
  });
  step('Delete Account', 'Accounts', [calc('name', 'Account name'), bool('dialog', 'With dialog', false)], async (p, rt) => {
    const n = rt.text(p.name);
    if (p.dialog && !(await FM.confirm('Delete the account "' + n + '"?', { ok: 'Delete' }))) throw new FMError(1);
    await rt.accounts([{ op: 'delete', match: n }]);
  });
  step('Reset Account Password', 'Accounts', [calc('name', 'Account name'), calc('password', 'New password'), bool('mustChange', 'User must change password on next login', false)], async (p, rt) => {
    await rt.accounts([{ op: 'update', match: rt.text(p.name), password: rt.text(p.password), mustChange: !!p.mustChange }]);
  });
  step('Enable Account', 'Accounts', [calc('name', 'Account name'), choice('how', 'Action', [['on', 'Activate account'], ['off', 'Deactivate account']])], async (p, rt) => {
    await rt.accounts([{ op: 'update', match: rt.text(p.name), active: p.how !== 'off' }]);
  });
  step('Change Password', 'Accounts', [calc('old', 'Old password', { opt: true }), calc('new', 'New password', { opt: true }), bool('dialog', 'With dialog', true)], async (p, rt) => {
    if (p.dialog || !p.new) { const ok = await FM.dlg.changePassword(rt.file); if (!ok) throw new FMError(1); return; }
    try { await rt.file.api('POST', '/password', { old: rt.text(p.old || ''), new: rt.text(p.new) }); }
    catch (e) { throw new FMError(e.fmError || 213, e.message); }
  });
  step('Re-Login', 'Accounts', [calc('account', 'Account name', { opt: true }), calc('password', 'Password', { opt: true }), bool('dialog', 'With dialog', true)], async (p, rt) => {
    let account, password;
    if (p.dialog || !p.account) { const r = await FM.dlg.login(rt.file.name, { account: rt.file.account.name, relogin: true }); if (!r) throw new FMError(1); account = r.account; password = r.password; }
    else { account = rt.text(p.account); password = p.password ? rt.text(p.password) : ''; }
    await rt.app.relogin(rt.file, account, password);
  });

  // ── Spelling ────────────────────────────────────────────────────────────
  ['Check Selection', 'Check Record', 'Check Found Set', 'Correct Word', 'Spelling Options', 'Select Dictionaries', 'Edit User Dictionary'].forEach(n => planned(n, 'Spelling', [], 'The browser\'s own spell checker underlines misspelled words while you type.'));

  // ── Open Menu Item ──────────────────────────────────────────────────────
  const openItem = (name, fn) => step(name, 'Open Menu Item', [], async (p, rt) => { await fn(rt); });
  openItem('Open Edit Saved Finds', rt => FM.dlg.savedFinds(rt.win));
  openItem('Open File Options', rt => FM.dlg.fileOptions(rt.file));
  openItem('Open Find/Replace', rt => FM.dlg.findReplace(rt.win, { dialog: true }));
  openItem('Open Help', rt => FM.dlg.help());
  openItem('Open Hosts', rt => rt.app.showLaunch());
  openItem('Open Manage Database', rt => FM.dlg.manageDatabase(rt.file));
  openItem('Open Manage Layouts', rt => FM.dlg.manageLayouts(rt.win));
  openItem('Open Manage Value Lists', rt => FM.dlg.manageValueLists(rt.file));
  openItem('Open Manage Custom Functions', rt => FM.dlg.manageCustomFunctions(rt.file));
  openItem('Open Manage Security', rt => FM.dlg.security(rt.file));
  openItem('Open Preferences', rt => FM.dlg.preferences(rt.app));
  openItem('Open Script Workspace', rt => FM.workspace.open(rt.file));
  openItem('Open Sharing', rt => FM.dlg.sharing(rt.file));
  openItem('Open Data Viewer', rt => FM.dataViewer.open(rt.app));
  ['Open Favorites', 'Open Manage Containers', 'Open Manage Data Sources', 'Open Manage Themes', 'Open Settings for Upload to Host', 'Open Upload to Host'].forEach(n => planned(n, 'Open Menu Item'));

  // ── Miscellaneous ───────────────────────────────────────────────────────
  step('Show Custom Dialog', 'Miscellaneous', [{ k: 'dialog', key: 'dialog', label: 'Dialog' }], async (p, rt) => {
    const d = p.dialog || {};
    const title = d.title ? rt.text(d.title) : 'FileMaker';
    const msg = d.message ? rt.text(d.message) : '';
    const btns = (d.buttons || [{ label: '"OK"', commit: true }, { label: '"Cancel"', commit: false }]).map(b => Object.assign({}, b, { text: b.label ? rt.text(b.label) : '' })).filter(b => b.text);
    if (!btns.length) btns.push({ text: 'OK', commit: true });
    const inputs = (d.inputs || []).filter(i => i && (i.field || i.var)).slice(0, 3);
    const body = h('div', { class: 'fm-form fm-cdlg' });
    if (msg) body.appendChild(h('div', { class: 'fm-msg-text', style: { whiteSpace: 'pre-wrap', marginBottom: inputs.length ? '12px' : '0' }, text: msg }));
    const els = inputs.map(inp => {
      const cur = inp.field ? rt.file.display(rt.target(inp.field).rec, inp.field, 1, rt.ctx()) : V.text(rt.file.getVar(inp.var, 1, rt.ctx()));
      const el = h('input', { class: 'fm-input', type: inp.password ? 'password' : 'text', value: cur, style: { width: '100%' } });
      body.appendChild(h('label', { class: 'fm-col' }, h('span', { class: 'fm-muted small', text: inp.label ? rt.text(inp.label) : (inp.field ? rt.file.keyLabel(inp.field) : inp.var) }), el));
      return el;
    });
    const choice = await FM.modal({ title, body, width: 460, buttons: btns.slice().reverse().map((b, i) => ({ label: b.text, value: btns.length - i, primary: i === btns.length - 1, cancel: i === 0 && btns.length > 1 })) });
    const n = choice == null ? btns.length : choice;
    rt.app.lastMessageChoice = n;
    const b = btns[n - 1];
    if (b && b.commit !== false && inputs.length) {
      for (let i = 0; i < inputs.length; i++) {
        const inp = inputs[i];
        if (inp.var) rt.file.setVar(inp.var, els[i].value, 1, rt.ctx());
        else await rt.setField(inp.field, rt.target(inp.field), els[i].value);
      }
    }
  });
  step('Allow Formatting Bar', 'Miscellaneous', [bool('on', 'On', true)], async () => { });
  step('Beep', 'Miscellaneous', [], async () => { try { const a = new (window.AudioContext || window.webkitAudioContext)(); const o = a.createOscillator(); const g = a.createGain(); o.frequency.value = 880; g.gain.value = 0.08; o.connect(g); g.connect(a.destination); o.start(); setTimeout(() => { o.stop(); a.close(); }, 140); } catch (e) { /* no audio */ } });
  step('Speak', 'Miscellaneous', [calc('text', 'Text to speak'), bool('wait', 'Wait for speech completion', true)], async (p, rt) => {
    if (!window.speechSynthesis) return;
    const u = new SpeechSynthesisUtterance(rt.text(p.text));
    await new Promise(r => { u.onend = r; u.onerror = r; speechSynthesis.speak(u); if (!p.wait) r(); });
  });
  step('Dial Phone', 'Miscellaneous', [calc('number', 'Phone number'), bool('dialog', 'With dialog', false)], async (p, rt) => { window.open('tel:' + rt.text(p.number).replace(/[^\d+*#]/g, ''), '_self'); });
  step('Set Web Viewer', 'Miscellaneous', [calc('name', 'Object name'), choice('action', 'Action', [['reset', 'Reset'], ['reload', 'Reload'], ['forward', 'Go Forward'], ['back', 'Go Back'], ['url', 'Go to URL']]), calc('url', 'URL', { opt: true })], async (p, rt) => {
    const w = rt.win; const name = rt.text(p.name);
    const o = FM.layoutObjects(w.layout).find(x => x.type === 'webviewer' && x.name && x.name.toLowerCase() === name.toLowerCase());
    if (!o) throw new FMError(112);
    const fr = w.el.querySelector('[data-obj-name="' + CSS.escape(o.name) + '"] iframe');
    if (p.action === 'url') { const u = rt.text(p.url); if (fr && /^https?:/i.test(u)) fr.src = u; else { o._override = u; w.render(); } return; }
    if (!fr) return;
    try { if (p.action === 'back') fr.contentWindow.history.back(); else if (p.action === 'forward') fr.contentWindow.history.forward(); else w.render(); } catch (e) { w.render(); }
  });
  step('Open URL', 'Miscellaneous', [calc('url', 'URL'), bool('dialog', 'With dialog', false), bool('newWindow', 'In external browser', true)], async (p, rt) => {
    const u = rt.text(p.url);
    if (!/^(https?:|mailto:|tel:|sms:|fmp:)/i.test(u)) throw new FMError(1630, 'The URL must start with http://, https://, mailto: or tel:.');
    if (/^fmp:/i.test(u)) { await rt.app.openFmpUrl(u); return; }
    window.open(u, /^https?:/i.test(u) ? '_blank' : '_self', 'noopener');
  });
  step('Send Mail', 'Miscellaneous', [calc('to', 'To', { opt: true }), calc('cc', 'CC', { opt: true }), calc('bcc', 'BCC', { opt: true }), calc('subject', 'Subject', { opt: true }), calc('message', 'Message', { opt: true }), bool('dialog', 'With dialog', true)], async (p, rt) => {
    const q = []; const add = (k, v) => { if (v) q.push(k + '=' + encodeURIComponent(v)); };
    add('cc', p.cc && rt.text(p.cc)); add('bcc', p.bcc && rt.text(p.bcc)); add('subject', p.subject && rt.text(p.subject)); add('body', p.message && rt.text(p.message));
    window.open('mailto:' + encodeURIComponent(p.to ? rt.text(p.to) : '').replace(/%40/g, '@').replace(/%2C/g, ',') + (q.length ? '?' + q.join('&') : ''), '_self');
  }, { note: 'Opens your email app with the message filled in.' });
  step('Flush Cache to Disk', 'Miscellaneous', [], async (p, rt) => { rt.file.touch(); });
  step('Exit Application', 'Miscellaneous', [], async (p, rt) => { rt.halted = true; await rt.app.exitApplication(); });
  step('Enable Touch Keyboard', 'Miscellaneous', [bool('on', 'On', true)], async () => { });
  step('Perform JavaScript in Web Viewer', 'Miscellaneous', [calc('name', 'Object name'), calc('fn', 'Function name'), { k: 'calclist', key: 'params', label: 'Parameters' }], async (p, rt) => {
    const w = rt.win; const name = rt.text(p.name);
    const fr = w.el.querySelector('[data-obj-name="' + CSS.escape(name) + '"] iframe');
    if (!fr) throw new FMError(112);
    fr.contentWindow.postMessage({ fmCall: rt.text(p.fn), args: (p.params || []).map(x => V.text(rt.ev(x))) }, '*');
  });
  step('Refresh Object ', 'Miscellaneous', [], async (p, rt) => rt.win.render(), { hidden: true });
  ['Install Plug-In File', 'Install Menu Set', 'Send DDE Execute', 'Perform AppleScript', 'Execute SQL', 'Send Event', 'Get Folder Path', 'Set Session Identifier', 'Set Dictionary', 'Configure NFC Reading', 'Configure Machine Learning Model', 'Configure AI Account', 'Generate Response from Model', 'Insert Embedding', 'Perform Semantic Find', 'Configure Persistent Data'].forEach(n => planned(n, 'Miscellaneous'));

  function parseCurl(s, rt) {
    const out = { method: 'GET', headers: {}, body: null };
    if (!s) return out;
    const toks = []; const re = /"((?:\\.|[^"\\])*)"|'([^']*)'|(\S+)/g; let m;
    while ((m = re.exec(s))) toks.push(m[1] != null ? m[1].replace(/\\(.)/g, '$1') : m[2] != null ? m[2] : m[3]);
    const val = t => t.startsWith('@$') ? V.text(rt.file.getVar(t.slice(1), 1, rt.ctx())) : t;
    for (let i = 0; i < toks.length; i++) {
      const t = toks[i];
      if (t === '-X' || t === '--request') out.method = String(toks[++i] || 'GET').toUpperCase();
      else if (t === '-H' || t === '--header') { const hd = val(toks[++i] || ''); const c = hd.indexOf(':'); if (c > 0) out.headers[hd.slice(0, c).trim()] = hd.slice(c + 1).trim(); }
      else if (t === '-d' || t === '--data' || t === '--data-raw' || t === '--data-binary') { out.body = val(toks[++i] || ''); if (out.method === 'GET') out.method = 'POST'; }
      else if (t === '--user' || t === '-u') out.headers.Authorization = 'Basic ' + btoa(val(toks[++i] || ''));
      else if (t === '-D' || t === '--dump-header') out.dumpHeaders = toks[++i];
    }
    return out;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // runtime
  // ═══════════════════════════════════════════════════════════════════════
  function jumps(steps) {
    const j = {}; const stack = [];
    steps.forEach((s, i) => {
      if (s.off) return;
      const b = (STEPS[s.s] || {}).block;
      if (b === 'if') stack.push({ t: 'if', i, branches: [i] });
      else if (b === 'elseif' || b === 'else') { const top = stack[stack.length - 1]; if (top && top.t === 'if') top.branches.push(i); }
      else if (b === 'endif') { const top = stack.pop(); if (top && top.t === 'if') { top.branches.push(i); for (let k = 0; k < top.branches.length - 1; k++) j[top.branches[k]] = { next: top.branches[k + 1], end: i }; } }
      else if (b === 'loop') stack.push({ t: 'loop', i, exits: [] });
      else if (b === 'exitloopif') { for (let k = stack.length - 1; k >= 0; k--) if (stack[k].t === 'loop') { stack[k].exits.push(i); break; } }
      else if (b === 'endloop') { const top = stack.pop(); if (top && top.t === 'loop') { j[i] = { loop: top.i }; j[top.i] = { end: i }; top.exits.forEach(x => { j[x] = { end: i }; }); } }
    });
    return j;
  }
  // block structure problems for the workspace
  FM.scriptProblems = function (steps) {
    const out = []; const stack = [];
    steps.forEach((s, i) => {
      if (s.off) return;
      const b = (STEPS[s.s] || {}).block;
      if (b === 'if' || b === 'loop') stack.push({ b, i });
      else if (b === 'elseif' || b === 'else') { if (!stack.length || stack[stack.length - 1].b !== 'if') out.push({ i, msg: s.s + ' without If' }); }
      else if (b === 'endif') { if (!stack.length || stack[stack.length - 1].b !== 'if') out.push({ i, msg: 'End If without If' }); else stack.pop(); }
      else if (b === 'exitloopif') { if (!stack.some(x => x.b === 'loop')) out.push({ i, msg: 'Exit Loop If outside a loop' }); }
      else if (b === 'endloop') { if (!stack.length || stack[stack.length - 1].b !== 'loop') out.push({ i, msg: 'End Loop without Loop' }); else stack.pop(); }
    });
    stack.forEach(x => out.push({ i: x.i, msg: (x.b === 'if' ? 'If' : 'Loop') + ' is not closed' }));
    return out;
  };

  class Runtime {
    constructor(runner, file, win) {
      this.runner = runner; this.app = runner.app; this.file = file; this.win = win;
      this.stack = []; this.errorCapture = false; this.allowAbort = true;
      this.lastError = 0; this.lastResult = ''; this.halted = false; this.txn = null;
      this.frozen = new Set();
    }
    get frame() { return this.stack[this.stack.length - 1]; }
    ctx() {
      const w = this.win; const fr = this.frame;
      const c = { to: w ? w.to : null, rec: w ? w.current() : null, win: w, frame: fr };
      if (w && w.active && w.active.rowTO && w.active.rowRec) c.rows = { [w.active.rowTO]: w.active.rowRec };
      if (w && w.mode !== 'find') c.summarySet = w.foundRecords();
      return c;
    }
    ev(formula) {
      if (formula == null || String(formula).trim() === '') return '';
      try { return this.file.evaluate(String(formula), this.ctx(), true); }
      catch (e) { if (e instanceof FM.calc.CalcError) { this.lastErrorDetail = e.message; return '?'; } throw e; }
    }
    text(f) { return V.text(this.ev(f)); }
    // stored find criteria are literal text; a lone $variable name stands for its value
    crit(v) { const t = String(v == null ? '' : v); return /^\s*\$\$?[^\s]+\s*$/.test(t) ? V.text(this.file.getVar(t.trim(), 1, this.ctx())) : t; }
    num(f) { return V.num(this.ev(f)); }
    bool(f) { return V.bool(this.ev(f)); }
    sleep(ms) { return new Promise(r => { this.sleepTimer = setTimeout(r, ms); this.sleepResolve = r; }); }
    resolveScript(spec) {
      spec = spec || {};
      let s;
      if (spec.how === 'name') s = this.file.scriptByName(this.text(spec.calc));
      else s = this.file.script(spec.id);
      if (!s) throw new FMError(104);
      if (this.file.scriptAccess(s.id) === 'none') throw new FMError(200, 'You do not have permission to run the script "' + s.name + '".');
      return s;
    }
    target(key) {
      const k = FM.pkey(key); const w = this.win;
      if (w.active && w.active.rowTO === k.to) return { rec: w.active.rowRec, to: k.to };
      if (k.to === w.to) return { rec: w.current(), to: k.to };
      const cur = w.current();
      const rel = cur ? this.file.related(w.to, cur, k.to) : [];
      return { rec: rel[0] || null, to: k.to, related: true };
    }
    async setField(key, tgt, value, rep) {
      const f = this.file.fieldByKey(key); if (!f) throw new FMError(102);
      if (this.win.mode === 'find') {
        const req = this.win.requests[this.win.reqIndex];
        req.crit[key + (rep > 1 ? '[' + rep + ']' : '')] = V.text(value); this.win.render(); return;
      }
      if (!tgt.rec && !this.file.isGlobal(f)) throw new FMError(101, 'There is no record to set the field in.');
      if (V.isContainer(value) && f.type !== 'container') value = value.name;
      const stored = f.type === 'container' ? (V.isContainer(value) ? value : V.text(value)) : V.toStored(value, f.type);
      if (f.type === 'number' && stored !== '' && FM.num.parse(stored) == null) this.lastErrorDetail = 'Not a number';
      await this.win.setFieldValue(tgt.rec, key, stored, rep || 1, { script: true });
      this.win.refresh();
    }
    async insert(key, text, select, isDateTime) {
      key = key || (this.win.active && this.win.active.key);
      if (!key) throw new FMError(102);
      const a = document.activeElement;
      if (!this.win.active || this.win.active.key !== key || !a || !a.dataset || a.dataset.fmKey !== key) {
        const tg = this.target(key);
        const f = this.file.fieldByKey(key);
        if (isDateTime && f && (f.type === 'date' || f.type === 'time' || f.type === 'timestamp')) { await this.setField(key, tg, f.type === 'date' ? new FM.FMDate(D.todayNum()) : f.type === 'time' ? new FM.FMTime(D.nowSeconds()) : new FM.FMTimestamp(D.nowTs())); return; }
        await this.setField(key, tg, (this.file.raw(tg.rec, f, 1) || '') + text);
        return;
      }
      a.setRangeText(text, a.selectionStart, a.selectionEnd, select ? 'select' : 'end'); a.dispatchEvent(new Event('input'));
    }
    async accounts(ops) {
      try { await this.file.api('POST', '/accounts', { ops }); }
      catch (e) { throw new FMError(e.fmError || 200, e.message); }
    }
    async revertTxn(ops) {
      const drop = ops.filter(o => { const r = this.file.recordById(o.id); return r && r.pending; }).map(o => ({ op: 'delete', id: o.id }));
      ops.forEach(o => { const e = this.file.editing.get(o.id); if (e) { this.file.editing.delete(o.id); if (e.locked && !e.isNew) this.file.unlock(['rec:' + o.id]); } });
      if (drop.length) { try { await this.file.batch(drop); } catch (e) { /* pending records vanish with the session anyway */ } }
      this.file.touch(); if (this.win) this.win.render();
    }
    pause(o) {
      return new Promise(resolve => {
        this.paused = { resolve, find: o && o.find };
        this.runner.pausedFrame = this;
        if (this.win) this.app.renderChrome(this.win);
        this.app.renderPausedBar(this);
      }).finally(() => { this.paused = null; this.runner.pausedFrame = null; if (this.win) this.app.renderChrome(this.win); this.app.renderPausedBar(null); });
    }
    resume(how) { if (this.paused) this.paused.resolve(how || 'continue'); }
    async call(script, param, o) {
      if (this.stack.length > 200) throw new FMError(3, 'Too many nested Perform Script calls.');
      const frame = { script, steps: script.steps || [], pc: 0, vars: new Map(), param: param == null ? '' : param, rt: this, result: '', j: jumps(script.steps || []), originalLayout: this.win ? this.win.layoutId : null, full: !!script.fullAccess };
      this.stack.push(frame);
      try { await this.exec(frame); }
      finally { this.stack.pop(); }
      this.lastResult = frame.result;
      return frame.result;
    }
    async exec(fr) {
      const steps = fr.steps;
      const dbg = this.runner.debugger;
      while (fr.pc < steps.length && !this.halted && !fr.exit) {
        const i = fr.pc; const st = steps[i];
        if (st.off) { fr.pc++; continue; }
        const def = STEPS[st.s];
        if (dbg && dbg.active) await dbg.before(this, fr, i);
        if (this.halted) break;
        if (!def) { this.lastError = 4; fr.pc++; continue; }
        const p = st.p || {};
        const jt = fr.j[i];
        try {
          switch (def.block) {
            case 'if': case 'elseif': {
              if (def.block === 'elseif' && fr.inBranch && fr.inBranch[i]) { fr.pc = jt ? jt.end + 1 : i + 1; continue; }
              let b = i;
              for (;;) {
                const sb = steps[b]; const bd = STEPS[sb.s];
                if (bd.block === 'endif') { fr.pc = b + 1; break; }
                if (bd.block === 'else' || this.bool((sb.p || {}).calc || '')) {
                  fr.pc = b + 1; fr.inBranch = fr.inBranch || {};
                  const j2 = fr.j[b]; let nb = j2 ? j2.next : null;
                  while (nb != null) { fr.inBranch[nb] = true; nb = fr.j[nb] ? fr.j[nb].next : null; }
                  break;
                }
                const jj = fr.j[b]; if (!jj) { fr.pc = b + 1; break; }
                b = jj.next;
              }
              this.lastError = 0;
              continue;
            }
            case 'else': { fr.pc = jt ? jt.end + 1 : i + 1; continue; }
            case 'endif': { if (fr.inBranch) Object.keys(fr.inBranch).forEach(k => { if (+k < i) delete fr.inBranch[k]; }); fr.pc = i + 1; continue; }
            case 'loop': { fr.pc = i + 1; continue; }
            case 'endloop': { fr.pc = jt ? jt.loop + 1 : i + 1; if (++fr.iterations > 5e6) throw new FMError(3, 'The loop ran too many times.'); await this.yieldMaybe(); continue; }
            case 'exitloopif': { if (this.bool(p.calc || '')) fr.pc = jt ? jt.end + 1 : i + 1; else fr.pc = i + 1; this.lastError = 0; continue; }
          }
          fr.exitLoop = false;
          this.lastError = 0; this.lastErrorDetail = '';
          await def.run(p, this, st, fr);
          if (fr.exitLoop) {
            // "Exit after last" leaves the enclosing loop
            let k = i + 1, depth = 0;
            for (; k < steps.length; k++) { const b = (STEPS[steps[k].s] || {}).block; if (steps[k].off) continue; if (b === 'loop') depth++; else if (b === 'endloop') { if (!depth) break; depth--; } }
            fr.pc = k < steps.length ? k + 1 : steps.length; continue;
          }
        } catch (e) {
          const code = e instanceof FMError ? e.code : (e && e.fmError) || 3;
          this.lastError = code;
          this.lastErrorLocation = fr.script.name + '\n' + st.s + '\n' + (i + 1);
          if (!(e instanceof FMError)) { this.lastErrorDetail = e && e.message; console.error(e); }
          if (!this.errorCapture && code !== 0) {
            if (code === 1) { this.halted = true; break; }
            const msg = (e && e.message) || FM.ERR[code] || 'Error ' + code;
            const c = await FM.alert(msg + (code === 3 && def.planned ? '' : ''), { title: 'FileMaker', buttons: this.allowAbort ? ['Continue', 'Cancel'] : ['OK'], icon: 'warn' });
            if (this.allowAbort && c === 2) { this.halted = true; break; }
          }
        }
        if (fr.pc === i) fr.pc = i + 1;
        if (this.stepsRun++ % 200 === 0) await this.yieldMaybe();
      }
    }
    async yieldMaybe() { if (++this.ticks % 50 === 0) await new Promise(r => setTimeout(r, 0)); }
  }
  Runtime.prototype.stepsRun = 0;
  Runtime.prototype.ticks = 0;

  class Runner {
    constructor(app) { this.app = app; this.current = null; this.busy = false; this.debugger = null; }
    // run a script; resolves to its result. Triggers ask with o.trigger.
    async run(script, param, o) {
      o = o || {};
      const win = o.win;
      const file = win ? win.file : o.file;
      if (!script || !file) return '';
      if (file.scriptAccess(script.id) === 'none') { await FM.alert('You do not have permission to run the script "' + script.name + '".', { icon: 'warn' }); return ''; }
      // a running (not paused) script finishes before another starts; a paused one is suspended
      if (this.current && !this.current.paused) { if (o.trigger || o.timer) return null; return null; }
      const outer = this.current;
      const rt = new Runtime(this, file, win);
      this.current = rt; this.busy = true;
      this.app.renderChrome(win);
      let result = '';
      try { result = await rt.call(script, param, o); }
      catch (e) { console.error(e); }
      finally {
        rt.frozen.forEach(w => { w.frozen = Math.max(0, w.frozen - 1); if (!w.frozen && w.needsRender) w.render(); });
        if (rt.txn && rt.txn.length) await rt.revertTxn(rt.txn);
        this.current = outer; this.busy = !!outer;
        this.app.lastScriptResult = result;
        this.app.lastError = rt.lastError;
        this.app.windows.forEach(w => { if (w.needsRender && !w.frozen) w.render(); });
        this.app.windows.forEach(w => this.app.renderChrome(w));
        if (FM.dataViewer.visible) FM.dataViewer.refresh();
      }
      if (o.trigger) return { result, halted: rt.halted, error: rt.lastError };
      return result;
    }
    // a button: one step, or Perform Script
    async runAction(action, win, ctx) {
      if (!action || action.kind === 'none') return;
      if (action.kind === 'script') {
        const s = win.file.script(action.script);
        if (!s) { await FM.alert('The script for this button is missing.', { icon: 'warn' }); return; }
        const rt0 = new Runtime(this, win.file, win);
        const param = action.param ? (() => { try { return win.file.evaluate(action.param, Object.assign(rt0.ctx(), ctx || {}), true); } catch (e) { return '?'; } })() : '';
        if (this.current && this.current.paused) {
          if (action.current === 'halt') { this.current.halted = true; this.current.resume(); }
          else if (action.current === 'exit') { this.current.resume(); }
        }
        return this.run(s, param, { win });
      }
      if (action.kind === 'step' && action.step) {
        const temp = { id: '_button', name: 'Button: ' + action.step.s, steps: [action.step] };
        return this.run(temp, '', { win, adhoc: true, file: win.file });
      }
    }
  }
  FM.Runner = Runner;
  FM.STEPS = STEPS;
  FM.STEP_ORDER = ORDER;
  FM.STEP_CATS = CATS;

  // ═══════════════════════════════════════════════════════════════════════
  // formatting a step as text ("Set Field [ Contacts::Name ; "x" ]")
  // ═══════════════════════════════════════════════════════════════════════
  const short = (s, n) => { s = String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); return s.length > (n || 70) ? s.slice(0, (n || 70) - 1) + '…' : s; };
  FM.formatStep = function (st, file) {
    const def = STEPS[st.s];
    if (!def) return st.s + ' [ unknown step ]';
    const p = st.p || {};
    if (st.s === '#') return '# ' + (p.text || '');
    const parts = [];
    def.params.forEach(pp => {
      const v = p[pp.key];
      switch (pp.k) {
        case 'calc': if (v != null && v !== '') parts.push((pp.key === 'calc' || pp.key === 'value' || pp.key === 'result' ? '' : pp.label + ': ') + short(v)); break;
        case 'field': if (v) parts.push(file ? file.fullName(v) : v); break;
        case 'bool': if (v != null || pp.def) { if (def.params.length <= 2 && (pp.key === 'on')) parts.push(v === false ? 'Off' : 'On'); else parts.push(pp.label + ': ' + ((v == null ? pp.def : v) ? 'On' : 'Off')); } break;
        case 'choice': { const o = pp.options.find(x => x[0] === (v == null ? pp.def : v)); if (o) parts.push(o[1]); break; }
        case 'var': if (v) parts.push(v); break;
        case 'text': case 'longtext': if (v) parts.push('"' + short(v, 40) + '"'); break;
        case 'layout': if (v) parts.push(v.how === 'original' ? 'original layout' : v.how === 'name' ? 'Layout Name: ' + short(v.calc, 40) : v.how === 'number' ? 'Layout Number: ' + short(v.calc, 40) : v.how === 'auto' ? 'auto' : '"' + (file && file.layout(v.id) ? file.layout(v.id).name : '<unknown>') + '"'); break;
        case 'script': if (v) parts.push(v.how === 'name' ? 'By name: ' + short(v.calc, 40) : 'Specified: From list ; "' + (file && file.script(v.id) ? file.script(v.id).name : '<unknown>') + '"'); break;
        case 'to': if (v) parts.push('Table: "' + (file && file.to(v) ? file.to(v).name : '<unknown>') + '"'); break;
        case 'table': if (v) parts.push('Table: "' + (file && file.table(v) ? file.table(v).name : '<unknown>') + '"'); break;
        case 'requests': if (v && v.length) parts.push('Restore'); break;
        case 'sort': if (v && v.length) parts.push('Restore'); break;
        case 'dialog': if (v) parts.push(short(v.title || '""', 30) + ' ; ' + short(v.message || '""', 40)); break;
        case 'pset': if (v) parts.push('Privilege Set: "' + ((file && file.schema.privilegeSets.find(x => x.id === v)) || {}).name + '"'); break;
        case 'fieldOrVar': if (v && v.var) parts.push('Target: ' + v.var); else if (v && v.field) parts.push('Target: ' + (file ? file.fullName(v.field) : v.field)); break;
        case 'importspec': case 'exportspec': if (v) parts.push('Restore'); break;
        case 'calclist': if (v && v.length) parts.push('Parameters: ' + v.length); break;
      }
    });
    return st.s + (parts.length ? ' [ ' + parts.join(' ; ') + ' ]' : (def.params.length ? ' [ ]' : ''));
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Script Workspace
  // ═══════════════════════════════════════════════════════════════════════
  const WS = FM.workspace = {
    file: null, el: null, current: null, draft: null, dirty: false, sel: new Set(), anchor: -1, clip: null, breaks: new Set(), filter: '', stepFilter: '',
    async open(file, scriptId) {
      if (this.el) { this.el.remove(); }
      this.file = file;
      this.el = h('div', { class: 'fm-workspace' });
      document.body.appendChild(this.el);
      const list = this.visibleScripts();
      const first = scriptId ? file.script(scriptId) : (this.current && file.script(this.current.id)) || list.find(s => !s.folder);
      this.render();
      if (first) await this.select(first.id);
      document.addEventListener('keydown', this.onKey, true);
    },
    visibleScripts() { const f = this.file; return orderedScripts(f).filter(s => f.scriptAccess(s.id) !== 'none' || s.folder || s.separator); },
    async close() {
      if (!(await this.saveIfDirty())) return;
      if (this.current) this.file.unlock(['script:' + this.current.id]);
      if (this.el) this.el.remove();
      this.el = null; this.current = null; this.draft = null;
      document.removeEventListener('keydown', this.onKey, true);
      FM.app.windows.forEach(w => FM.app.renderChrome(w));
    },
    async saveIfDirty() {
      if (!this.dirty) return true;
      const c = await FM.alert('Save changes to the script "' + this.draft.name + '"?', { buttons: ['Save', "Don't Save", 'Cancel'], icon: 'warn' });
      if (c === 3) return false;
      if (c === 1) return this.save();
      this.dirty = false; return true;
    },
    canModify(s) { return s && this.file.scriptAccess(s.id) === 'modify'; },
    async select(id) {
      if (this.current && this.current.id === id) return;
      if (!(await this.saveIfDirty())) return;
      if (this.current) this.file.unlock(['script:' + this.current.id]);
      const s = this.file.script(id);
      if (!s || s.folder || s.separator) { this.current = s || null; this.draft = null; this.render(); return; }
      this.current = s; this.draft = FM.clone(s); this.draft.steps = this.draft.steps || [];
      this.dirty = false; this.sel = new Set(); this.anchor = -1; this.readOnly = !this.canModify(s);
      if (!this.readOnly) {
        const lk = await this.file.lockKey('script:' + s.id);
        if (!lk.ok) { this.readOnly = true; FM.toast('"' + s.name + '" is being modified by ' + (lk.holder || 'another user') + ' — read only.'); }
      }
      this.render();
    },
    mark() { this.dirty = true; this.renderSteps(); this.renderHead(); },
    async save() {
      if (!this.draft || this.readOnly) return true;
      const probs = FM.scriptProblems(this.draft.steps);
      try {
        await this.file.saveSchema([{ op: 'upsert', coll: 'scripts', item: this.draft }]);
        this.current = this.file.script(this.draft.id); this.dirty = false;
        FM.toast(probs.length ? 'Saved, but: ' + probs[0].msg : 'Script saved.', probs.length ? 'warn' : '');
        this.render();
        return true;
      } catch (e) { await FM.alert(e.message, { icon: 'warn' }); return false; }
    },
    async newScript(folder) {
      if (!this.file.canCreateScripts()) { await FM.alert('Your privileges do not allow creating scripts.', { icon: 'warn' }); return; }
      if (!(await this.saveIfDirty())) return;
      const n = this.file.schema.scripts.filter(s => /^New Script/.test(s.name)).length;
      const s = { id: FM.uid('S'), name: folder ? 'New Folder' : 'New Script' + (n ? ' ' + (n + 1) : ''), steps: [], menu: !folder, folder: !!folder || undefined, parent: this.current && this.current.folder ? this.current.id : (this.current && this.current.parent) || undefined };
      try {
        const order = (this.file.schema.scriptOrder || []).concat(s.id);
        await this.file.saveSchema([{ op: 'upsert', coll: 'scripts', item: s }, { op: 'section', name: 'scriptOrder', value: order }].filter(x => x.op !== 'section' || this.file.full));
        this.current = null;
        await this.select(s.id);
        setTimeout(() => { const n2 = this.el.querySelector('.fm-ws-name'); if (n2) { n2.focus(); n2.select(); } }, 30);
      } catch (e) { FM.alert(e.message, { icon: 'warn' }); }
    },
    async deleteScript() {
      const s = this.current; if (!s || !this.canModify(s)) return;
      if (!(await FM.confirm('Delete the ' + (s.folder ? 'folder' : 'script') + ' "' + s.name + '"?', { ok: 'Delete' }))) return;
      try {
        const ops = [{ op: 'delete', coll: 'scripts', id: s.id }];
        this.file.schema.scripts.filter(x => x.parent === s.id).forEach(x => ops.push({ op: 'upsert', coll: 'scripts', item: Object.assign({}, x, { parent: s.parent }) }));
        this.dirty = false; this.file.unlock(['script:' + s.id]);
        await this.file.saveSchema(ops);
        this.current = null; this.draft = null; this.render();
      } catch (e) { FM.alert(e.message, { icon: 'warn' }); }
    },
    async duplicateScript() {
      const s = this.current; if (!s || s.folder) return;
      const copy = FM.clone(this.draft || s); copy.id = FM.uid('S'); copy.name = s.name + ' Copy'; copy.steps.forEach(st => { st.id = FM.uid('t'); });
      try { await this.file.saveSchema([{ op: 'upsert', coll: 'scripts', item: copy }]); await this.select(copy.id); } catch (e) { FM.alert(e.message, { icon: 'warn' }); }
    },
    render() {
      if (!this.el) return;
      const f = this.file;
      this.el.innerHTML = '';
      const head = h('div', { class: 'fm-ws-head' });
      const left = h('div', { class: 'fm-ws-left' });
      const center = h('div', { class: 'fm-ws-center' });
      const right = h('div', { class: 'fm-ws-right' });
      this.el.append(h('div', { class: 'fm-ws-title' }, h('span', { html: FM.icon('script', 16) }), h('span', { text: 'Script Workspace — ' + f.name }), h('div', { class: 'fm-flex1' }), h('button', { class: 'fm-btn small', text: 'Close', onclick: () => this.close() })), head, h('div', { class: 'fm-ws-body' }, left, center, right));
      this.headEl = head; this.centerEl = center;
      this.renderHead();
      // scripts list
      const tools = h('div', { class: 'fm-ws-ltools' },
        h('button', { class: 'fm-iconbtn', title: 'New Script', html: FM.icon('plus', 16), onclick: () => this.newScript() }),
        h('button', { class: 'fm-iconbtn', title: 'New Folder', html: FM.icon('folder', 16), onclick: () => this.newScript(true) }),
        h('button', { class: 'fm-iconbtn', title: 'Duplicate', html: FM.icon('copy', 16), onclick: () => this.duplicateScript() }),
        h('button', { class: 'fm-iconbtn', title: 'Delete', html: FM.icon('trash', 16), onclick: () => this.deleteScript() }));
      const search = h('input', { class: 'fm-input fm-search', placeholder: 'Search scripts', value: this.filter });
      search.addEventListener('input', () => { this.filter = search.value; this.renderList(); });
      this.listEl = h('div', { class: 'fm-ws-list' });
      left.append(tools, search, this.listEl);
      this.renderList();
      // steps
      if (!this.draft) {
        center.appendChild(h('div', { class: 'fm-empty', text: this.current && this.current.folder ? 'Folder "' + this.current.name + '". Choose a script, or click + to create one.' : 'Choose a script on the left, or click + to create one.' }));
      } else {
        this.stepsEl = h('div', { class: 'fm-ws-steps', tabIndex: 0 });
        this.optsEl = h('div', { class: 'fm-ws-opts' });
        center.append(this.stepsEl, this.optsEl);
        this.renderSteps();
      }
      // step palette
      const ss = h('input', { class: 'fm-input fm-search', placeholder: 'Search steps', value: this.stepFilter });
      this.paletteEl = h('div', { class: 'fm-ws-palette' });
      ss.addEventListener('input', () => { this.stepFilter = ss.value; this.renderPalette(); });
      right.append(h('div', { class: 'fm-ws-rhead', text: 'Steps' }), ss, this.paletteEl);
      this.renderPalette();
    },
    renderHead() {
      const head = this.headEl; if (!head) return; head.innerHTML = '';
      const d = this.draft;
      const ro = this.readOnly || !d;
      const run = h('button', { class: 'fm-btn small', disabled: !d, onclick: () => this.run(false) }, h('span', { html: FM.icon('play', 14) }), ' Run');
      const dbg = h('button', { class: 'fm-btn small', disabled: !d, onclick: () => this.run(true) }, h('span', { html: FM.icon('debug', 14) }), ' Debug');
      const save = h('button', { class: 'fm-btn small primary', disabled: ro || !this.dirty, onclick: () => this.save() }, 'Save');
      const revert = h('button', { class: 'fm-btn small', disabled: ro || !this.dirty, onclick: () => { this.draft = FM.clone(this.current); this.dirty = false; this.render(); } }, 'Revert');
      const name = h('input', { class: 'fm-input fm-ws-name', value: d ? d.name : (this.current ? this.current.name : ''), disabled: !this.current || !this.canModify(this.current) });
      name.addEventListener('change', async () => {
        if (d) { d.name = name.value.trim() || d.name; this.mark(); }
        else if (this.current && this.current.folder) { await this.file.saveSchema([{ op: 'upsert', coll: 'scripts', item: Object.assign({}, this.current, { name: name.value.trim() || this.current.name }) }]); this.current = this.file.script(this.current.id); this.renderList(); }
      });
      const full = FM.check('Run script with full access privileges', d && d.fullAccess, { disabled: ro || !this.file.full });
      full.input.addEventListener('change', () => { d.fullAccess = full.input.checked; this.mark(); });
      const menu = FM.check('Show in Scripts menu', d && d.menu !== false, { disabled: ro });
      menu.input.addEventListener('change', () => { d.menu = menu.input.checked; this.mark(); });
      head.append(run, dbg, h('span', { class: 'fm-sep' }), save, revert, h('span', { class: 'fm-sep' }), name, full, menu);
      if (this.readOnly && d) head.appendChild(h('span', { class: 'fm-badge', text: 'Read only' }));
      if (d) { const probs = FM.scriptProblems(d.steps); if (probs.length) head.appendChild(h('span', { class: 'fm-badge warn', text: probs[0].msg + ' (line ' + (probs[0].i + 1) + ')' })); }
    },
    renderList() {
      const el = this.listEl; if (!el) return; el.innerHTML = '';
      const q = this.filter.trim().toLowerCase();
      const all = this.visibleScripts();
      const byParent = new Map();
      all.forEach(s => { const k = s.parent || ''; if (!byParent.has(k)) byParent.set(k, []); byParent.get(k).push(s); });
      const add = (parent, depth) => (byParent.get(parent) || []).forEach(s => {
        if (q && !s.folder && !s.name.toLowerCase().includes(q)) return;
        const row = h('div', { class: 'fm-ws-item' + (this.current && this.current.id === s.id ? ' on' : '') + (s.folder ? ' folder' : '') + (s.separator ? ' sep' : ''), draggable: 'true' });
        row.style.paddingLeft = (8 + depth * 14) + 'px';
        row.appendChild(h('span', { html: FM.icon(s.folder ? 'folder' : 'script', 14) }));
        row.appendChild(h('span', { class: 'fm-ws-iname', text: s.separator ? '—' : s.name }));
        if (this.file.scriptAccess(s.id) === 'exec' && !s.folder) row.appendChild(h('span', { class: 'fm-muted small', text: ' (run only)' }));
        row.addEventListener('click', () => this.select(s.id));
        row.addEventListener('dblclick', () => { if (!s.folder) this.run(false); });
        row.addEventListener('dragstart', e => { e.dataTransfer.setData('text/fm-script', s.id); });
        row.addEventListener('dragover', e => { if (e.dataTransfer.types.includes('text/fm-script')) { e.preventDefault(); row.classList.add('dragover'); } });
        row.addEventListener('dragleave', () => row.classList.remove('dragover'));
        row.addEventListener('drop', e => { e.preventDefault(); row.classList.remove('dragover'); this.moveScript(e.dataTransfer.getData('text/fm-script'), s); });
        el.appendChild(row);
        if (s.folder) add(s.id, depth + 1);
      });
      add('', 0);
      if (!all.length) el.appendChild(h('div', { class: 'fm-empty small', text: 'No scripts yet.' }));
    },
    async moveScript(id, onto) {
      if (!this.file.full || id === onto.id) return;
      const s = this.file.script(id); if (!s) return;
      const order = orderedScripts(this.file).map(x => x.id).filter(x => x !== id);
      const at = order.indexOf(onto.id);
      order.splice(at + (onto.folder ? 1 : 0), 0, id);
      const ops = [{ op: 'section', name: 'scriptOrder', value: order }];
      const parent = onto.folder ? onto.id : onto.parent;
      if ((s.parent || undefined) !== (parent || undefined)) ops.push({ op: 'upsert', coll: 'scripts', item: Object.assign({}, s, { parent: parent || undefined }) });
      try { await this.file.saveSchema(ops); this.renderList(); } catch (e) { FM.alert(e.message, { icon: 'warn' }); }
    },
    renderSteps() {
      const el = this.stepsEl; if (!el || !this.draft) return;
      el.innerHTML = '';
      const steps = this.draft.steps;
      let indent = 0;
      const probs = new Map(FM.scriptProblems(steps).map(x => [x.i, x.msg]));
      steps.forEach((st, i) => {
        const def = STEPS[st.s] || {};
        if (!st.off && (def.block === 'elseif' || def.block === 'else' || def.block === 'endif' || def.block === 'endloop')) indent = Math.max(0, indent - 1);
        const row = h('div', { class: 'fm-ws-step' + (this.sel.has(i) ? ' sel' : '') + (st.off ? ' off' : '') + (st.s === '#' ? ' comment' : '') + (def.planned ? ' planned' : '') + (probs.has(i) ? ' problem' : ''), draggable: this.readOnly ? 'false' : 'true', title: probs.get(i) || (def.planned ? 'Planned: not available in this version' : (def.note || '')) });
        const gut = h('span', { class: 'fm-ws-gutter' + (this.breaks.has(st.id) ? ' bp' : ''), text: String(i + 1) });
        gut.addEventListener('click', e => { e.stopPropagation(); if (this.breaks.has(st.id)) this.breaks.delete(st.id); else this.breaks.add(st.id); this.renderSteps(); });
        row.appendChild(gut);
        const txt = h('span', { class: 'fm-ws-steptext' });
        txt.style.paddingLeft = (indent * 18) + 'px';
        txt.textContent = (st.off ? '// ' : '') + FM.formatStep(st, this.file);
        row.appendChild(txt);
        if (!st.off && (def.block === 'if' || def.block === 'elseif' || def.block === 'else' || def.block === 'loop')) indent++;
        row.addEventListener('mousedown', e => {
          if (e.shiftKey && this.anchor >= 0) { this.sel = new Set(); for (let k = Math.min(this.anchor, i); k <= Math.max(this.anchor, i); k++) this.sel.add(k); }
          else if (FM.cmd(e)) { if (this.sel.has(i)) this.sel.delete(i); else this.sel.add(i); this.anchor = i; }
          else { this.sel = new Set([i]); this.anchor = i; }
          this.renderSteps();
        });
        row.addEventListener('dragstart', e => { if (!this.sel.has(i)) { this.sel = new Set([i]); } e.dataTransfer.setData('text/fm-steps', JSON.stringify([...this.sel])); });
        row.addEventListener('dragover', e => { e.preventDefault(); row.classList.add('dragover'); });
        row.addEventListener('dragleave', () => row.classList.remove('dragover'));
        row.addEventListener('drop', e => {
          e.preventDefault(); row.classList.remove('dragover');
          const data = e.dataTransfer.getData('text/fm-steps'); const add = e.dataTransfer.getData('text/fm-addstep');
          if (add) { this.insertStep(add, i); return; }
          if (!data || this.readOnly) return;
          const idx = JSON.parse(data).sort((a, b) => a - b);
          const moving = idx.map(k => steps[k]);
          const rest = steps.filter((x, k) => !idx.includes(k));
          let at = rest.indexOf(steps[i]); if (at < 0) at = rest.length; if (idx[0] < i) at++;
          rest.splice(at, 0, ...moving);
          this.draft.steps = rest; this.sel = new Set(moving.map(m => rest.indexOf(m))); this.mark();
        });
        if (this.debugAt && this.debugAt.script === this.draft.id && this.debugAt.i === i) row.classList.add('debug-at');
        el.appendChild(row);
      });
      const end = h('div', { class: 'fm-ws-dropend', text: steps.length ? '' : 'Double-click a step on the right to add it.' });
      end.addEventListener('dragover', e => e.preventDefault());
      end.addEventListener('drop', e => { e.preventDefault(); const add = e.dataTransfer.getData('text/fm-addstep'); if (add) this.insertStep(add, steps.length); else { const data = e.dataTransfer.getData('text/fm-steps'); if (data && !this.readOnly) { const idx = JSON.parse(data); const moving = idx.map(k => steps[k]); this.draft.steps = steps.filter((x, k) => !idx.includes(k)).concat(moving); this.mark(); } } });
      el.appendChild(end);
      this.renderOptions();
    },
    insertStep(name, at) {
      if (this.readOnly || !this.draft) return;
      const def = STEPS[name]; if (!def) return;
      const steps = this.draft.steps;
      if (at == null) at = this.sel.size ? Math.max(...this.sel) + 1 : steps.length;
      const mk = (s, p) => ({ id: FM.uid('t'), s, p: p || {} });
      const p = {};
      def.params.forEach(pp => { if (pp.def != null) p[pp.key] = pp.def; if (pp.k === 'layout' && !pp.opt) p[pp.key] = { how: 'original' }; });
      const add = [mk(name, p)];
      if (def.block === 'if') add.push(mk('End If'));
      if (def.block === 'loop') add.push(mk('End Loop'));
      steps.splice(at, 0, ...add);
      this.sel = new Set([at]); this.anchor = at;
      this.mark();
      setTimeout(() => { const r = this.stepsEl.querySelectorAll('.fm-ws-step')[at]; if (r) r.scrollIntoView({ block: 'nearest' }); const first = this.optsEl.querySelector('textarea,input,select'); if (first) first.focus(); }, 20);
    },
    renderPalette() {
      const el = this.paletteEl; if (!el) return; el.innerHTML = '';
      const q = this.stepFilter.trim().toLowerCase();
      CATS.forEach(cat => {
        const names = ORDER.filter(n => STEPS[n].cat === cat && !STEPS[n].hidden && (!q || n.toLowerCase().includes(q)));
        if (!names.length) return;
        const grp = h('details', { class: 'fm-ws-cat', open: !!q || cat === 'Control' || cat === 'Fields' || cat === 'Records' || cat === 'Navigation' || cat === 'Found Sets' });
        grp.appendChild(h('summary', { text: cat }));
        names.forEach(n => {
          const it = h('div', { class: 'fm-ws-pstep' + (STEPS[n].planned ? ' planned' : ''), text: n, draggable: 'true', title: STEPS[n].planned ? 'Planned: listed for completeness, not available yet' : (STEPS[n].note || 'Double-click to add') });
          it.addEventListener('dblclick', () => this.insertStep(n));
          it.addEventListener('dragstart', e => e.dataTransfer.setData('text/fm-addstep', n));
          grp.appendChild(it);
        });
        el.appendChild(grp);
      });
    },
    renderOptions() {
      const el = this.optsEl; if (!el) return; el.innerHTML = '';
      if (this.sel.size !== 1) { el.appendChild(h('div', { class: 'fm-muted small', text: this.sel.size ? this.sel.size + ' steps selected' : 'Select a step to see its options.' })); return; }
      const i = [...this.sel][0]; const st = this.draft.steps[i]; if (!st) return;
      const def = STEPS[st.s] || { params: [] };
      st.p = st.p || {};
      el.appendChild(h('div', { class: 'fm-ws-ohead' }, h('b', { text: st.s }), def.planned ? h('span', { class: 'fm-badge', text: 'Planned' }) : null, def.note ? h('span', { class: 'fm-muted small', text: ' ' + def.note }) : null));
      const ro = this.readOnly;
      const changed = () => { const rows = this.stepsEl.querySelectorAll('.fm-ws-step .fm-ws-steptext'); if (rows[i]) rows[i].textContent = (st.off ? '// ' : '') + FM.formatStep(st, this.file); this.dirty = true; this.renderHead(); };
      def.params.forEach(pp => el.appendChild(FM.paramEditor(this.file, pp, st.p, changed, ro, { to: this.contextTO() })));
      if (!def.params.length) el.appendChild(h('div', { class: 'fm-muted small', text: 'This step has no options.' }));
    },
    contextTO() { const w = FM.app.activeWindow(this.file); return w ? w.to : (this.file.schema.tableOccurrences[0] || {}).id; },
    onKey: e => {
      const ws = WS;
      if (!ws.el || FM.modalOpen()) return;
      const inField = e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT');
      if (FM.cmd(e) && e.key.toLowerCase() === 's') { e.preventDefault(); ws.save(); return; }
      if (e.key === 'Escape' && !inField) { e.preventDefault(); ws.close(); return; }
      if (inField || !ws.draft || ws.readOnly) return;
      const steps = ws.draft.steps; const sel = [...ws.sel].sort((a, b) => a - b);
      if ((e.key === 'Delete' || e.key === 'Backspace') && sel.length) { e.preventDefault(); ws.draft.steps = steps.filter((x, k) => !ws.sel.has(k)); ws.sel = new Set([Math.min(sel[0], ws.draft.steps.length - 1)].filter(x => x >= 0)); ws.mark(); }
      else if (FM.cmd(e) && e.key.toLowerCase() === 'd' && sel.length) { e.preventDefault(); const copies = sel.map(k => Object.assign(FM.clone(steps[k]), { id: FM.uid('t') })); steps.splice(sel[sel.length - 1] + 1, 0, ...copies); ws.sel = new Set(copies.map((c, j) => sel[sel.length - 1] + 1 + j)); ws.mark(); }
      else if (FM.cmd(e) && e.key.toLowerCase() === 'c' && sel.length) { e.preventDefault(); ws.clip = sel.map(k => FM.clone(steps[k])); FM.toast(sel.length + ' step(s) copied'); }
      else if (FM.cmd(e) && e.key.toLowerCase() === 'x' && sel.length) { e.preventDefault(); ws.clip = sel.map(k => FM.clone(steps[k])); ws.draft.steps = steps.filter((x, k) => !ws.sel.has(k)); ws.sel = new Set(); ws.mark(); }
      else if (FM.cmd(e) && e.key.toLowerCase() === 'v' && ws.clip) { e.preventDefault(); const at = sel.length ? sel[sel.length - 1] + 1 : steps.length; const copies = ws.clip.map(s => Object.assign(FM.clone(s), { id: FM.uid('t') })); steps.splice(at, 0, ...copies); ws.sel = new Set(copies.map((c, j) => at + j)); ws.mark(); }
      else if (FM.cmd(e) && e.key === '/' && sel.length) { e.preventDefault(); const off = !steps[sel[0]].off; sel.forEach(k => { steps[k].off = off; }); ws.mark(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const d = e.key === 'ArrowDown' ? 1 : -1;
        if (e.altKey && sel.length) { const a = sel[0], b = sel[sel.length - 1]; if ((d < 0 && a > 0) || (d > 0 && b < steps.length - 1)) { const block = steps.splice(a, b - a + 1); steps.splice(a + d, 0, ...block); ws.sel = new Set(sel.map(k => k + d)); ws.mark(); } return; }
        const cur = sel.length ? (d > 0 ? sel[sel.length - 1] : sel[0]) : -1;
        const n = FM.clamp(cur + d, 0, steps.length - 1); ws.sel = new Set([n]); ws.anchor = n; ws.renderSteps();
        const r = ws.stepsEl.querySelectorAll('.fm-ws-step')[n]; if (r) r.scrollIntoView({ block: 'nearest' });
      }
    },
    async run(debug) {
      if (!this.draft) return;
      if (this.dirty && !this.readOnly && !(await this.save())) return;
      const w = FM.app.activeWindow(this.file);
      if (!w) { FM.alert('Open a window for this file first.'); return; }
      if (debug) FM.debuggerUI.start(); else if (FM.app.runner.debugger) FM.app.runner.debugger.active = false;
      this.el.classList.add('fm-ws-min');
      await FM.app.runner.run(this.file.script(this.draft.id), '', { win: w });
      if (this.el) this.el.classList.remove('fm-ws-min');
    }
  };
  function orderedScripts(file) {
    const order = file.schema.scriptOrder || [];
    const by = new Map(file.schema.scripts.map(s => [s.id, s]));
    const out = []; const seen = new Set();
    order.forEach(id => { if (by.has(id) && !seen.has(id)) { out.push(by.get(id)); seen.add(id); } });
    file.schema.scripts.forEach(s => { if (!seen.has(s.id)) out.push(s); });
    return out;
  }
  FM.orderedScripts = orderedScripts;

  // one parameter's editor (Script Workspace and button setup share it)
  FM.paramEditor = function (file, pp, p, changed, ro, o) {
    o = o || {};
    const set = (v) => { p[pp.key] = v; changed(); };
    const label = h('span', { class: 'fm-row-l', text: pp.label + (pp.opt ? '' : '') });
    const wrap = h('div', { class: 'fm-row fm-prow' }, label);
    const ctl = h('span', { class: 'fm-row-c' });
    wrap.appendChild(ctl);
    switch (pp.k) {
      case 'calc': case 'comment': case 'longtext': case 'text': case 'var': {
        const multi = pp.k === 'comment' || pp.k === 'longtext' || (pp.k === 'calc' && String(p[pp.key] || '').includes('\n'));
        const inp = multi ? h('textarea', { class: 'fm-input fm-mono', rows: 3, disabled: ro }) : h('input', { class: 'fm-input' + (pp.k === 'calc' ? ' fm-mono' : ''), disabled: ro, placeholder: pp.k === 'var' ? '$name' : '' });
        inp.value = p[pp.key] == null ? '' : p[pp.key];
        inp.addEventListener('input', () => set(inp.value));
        ctl.appendChild(inp);
        if (pp.k === 'calc') ctl.appendChild(h('button', { class: 'fm-btn small', type: 'button', disabled: ro, text: 'Specify…', onclick: async () => { const v = await FM.dlg.calc(file, { formula: inp.value, to: o.to, title: pp.label }); if (v != null) { inp.value = v.formula; set(v.formula); } } }));
        break;
      }
      case 'bool': { const c = FM.check('', p[pp.key] == null ? pp.def : p[pp.key], { disabled: ro }); c.input.addEventListener('change', () => set(c.input.checked)); ctl.appendChild(c); break; }
      case 'choice': { const s = FM.select(pp.options.map(x => ({ value: x[0], label: x[1] })), p[pp.key] == null ? pp.def : p[pp.key], { disabled: ro }); s.addEventListener('change', () => set(s.value)); ctl.appendChild(s); break; }
      case 'field': {
        const b = h('button', { class: 'fm-btn small fm-fieldbtn', type: 'button', disabled: ro, text: p[pp.key] ? file.fullName(p[pp.key]) : 'Specify…' });
        b.addEventListener('click', async () => { const k = await FM.dlg.pickField(file, { to: o.to, current: p[pp.key] }); if (k !== undefined) { set(k || ''); b.textContent = k ? file.fullName(k) : 'Specify…'; } });
        ctl.appendChild(b);
        if (pp.opt && p[pp.key]) ctl.appendChild(h('button', { class: 'fm-btn small', type: 'button', disabled: ro, text: 'Clear', onclick: () => { set(''); b.textContent = 'Specify…'; } }));
        break;
      }
      case 'fieldOrVar': {
        const v = p[pp.key] || {};
        const mode = FM.select([{ value: 'var', label: 'Variable' }, { value: 'field', label: 'Field' }], v.field ? 'field' : 'var', { disabled: ro });
        const vin = h('input', { class: 'fm-input', placeholder: '$result', value: v.var || '', disabled: ro });
        const fb = h('button', { class: 'fm-btn small', type: 'button', disabled: ro, text: v.field ? file.fullName(v.field) : 'Specify field…' });
        const sync = () => { vin.style.display = mode.value === 'var' ? '' : 'none'; fb.style.display = mode.value === 'field' ? '' : 'none'; };
        mode.addEventListener('change', () => { set(mode.value === 'var' ? { var: vin.value } : { field: (p[pp.key] || {}).field || '' }); sync(); });
        vin.addEventListener('input', () => set({ var: vin.value }));
        fb.addEventListener('click', async () => { const k = await FM.dlg.pickField(file, { to: o.to }); if (k) { set({ field: k }); fb.textContent = file.fullName(k); } });
        ctl.append(mode, vin, fb); sync();
        break;
      }
      case 'layout': {
        const v = p[pp.key] || { how: pp.opt ? '' : 'original' };
        const opts = [{ value: '', label: pp.opt ? '(current layout)' : '—' }, { value: 'original', label: 'original layout' }, { value: 'name', label: 'Layout Name by calculation…' }, { value: 'number', label: 'Layout Number by calculation…' }];
        if (pp.label === 'Show using layout') opts.splice(1, 1, { value: 'auto', label: '(first layout of the related table)' });
        file.schema.layouts.forEach(l => opts.push({ value: 'id:' + l.id, label: l.name }));
        const s = FM.select(opts, v.how === 'id' ? 'id:' + v.id : (v.how || ''), { disabled: ro });
        const cin = h('input', { class: 'fm-input fm-mono', placeholder: 'calculation', value: v.calc || '', disabled: ro });
        const sync = () => { cin.style.display = s.value === 'name' || s.value === 'number' ? '' : 'none'; };
        s.addEventListener('change', () => { const x = s.value; set(x.startsWith('id:') ? { how: 'id', id: x.slice(3) } : x ? { how: x, calc: cin.value } : null); sync(); });
        cin.addEventListener('input', () => set({ how: s.value, calc: cin.value }));
        ctl.append(s, cin); sync();
        break;
      }
      case 'script': {
        const v = p[pp.key] || {};
        const opts = [{ value: '', label: '—' }, { value: 'name', label: 'By name (calculation)…' }];
        orderedScripts(file).filter(s => !s.folder && !s.separator).forEach(s => opts.push({ value: 'id:' + s.id, label: s.name }));
        const s = FM.select(opts, v.how === 'name' ? 'name' : v.id ? 'id:' + v.id : '', { disabled: ro });
        const cin = h('input', { class: 'fm-input fm-mono', placeholder: '"Script name"', value: v.calc || '', disabled: ro });
        const sync = () => { cin.style.display = s.value === 'name' ? '' : 'none'; };
        s.addEventListener('change', () => { set(s.value.startsWith('id:') ? { how: 'id', id: s.value.slice(3) } : s.value === 'name' ? { how: 'name', calc: cin.value } : null); sync(); });
        cin.addEventListener('input', () => set({ how: 'name', calc: cin.value }));
        ctl.append(s, cin); sync();
        break;
      }
      case 'to': { const s = FM.select([{ value: '', label: '—' }].concat(file.schema.tableOccurrences.map(x => ({ value: x.id, label: x.name }))), p[pp.key] || '', { disabled: ro }); s.addEventListener('change', () => set(s.value)); ctl.appendChild(s); break; }
      case 'table': { const s = FM.select([{ value: '', label: '(current table)' }].concat(file.schema.tables.map(x => ({ value: x.id, label: x.name }))), p[pp.key] || '', { disabled: ro }); s.addEventListener('change', () => set(s.value)); ctl.appendChild(s); break; }
      case 'pset': { const s = FM.select(file.schema.privilegeSets.map(x => ({ value: x.id, label: x.name })), p[pp.key] || 'PS_ENTRY', { disabled: ro }); s.addEventListener('change', () => set(s.value)); ctl.appendChild(s); if (p[pp.key] == null) p[pp.key] = s.value; break; }
      case 'requests': {
        const n = (p[pp.key] || []).length;
        const b = h('button', { class: 'fm-btn small', type: 'button', disabled: ro, text: n ? 'Edit ' + n + ' request(s)…' : 'Specify…' });
        b.addEventListener('click', async () => { const r = await FM.dlg.findRequests(file, p[pp.key] || [], o.to); if (r) { set(r.length ? r : null); b.textContent = r.length ? 'Edit ' + r.length + ' request(s)…' : 'Specify…'; } });
        ctl.appendChild(b); break;
      }
      case 'sort': {
        const b = h('button', { class: 'fm-btn small', type: 'button', disabled: ro, text: (p[pp.key] || []).length ? 'Edit sort order…' : 'Specify…' });
        b.addEventListener('click', async () => { const w = FM.app.activeWindow(file); const r = await FM.dlg.sortDialog(w, p[pp.key] || [], { file, to: o.to, store: true }); if (r) { set(r.length ? r : null); b.textContent = r.length ? 'Edit sort order…' : 'Specify…'; } });
        ctl.appendChild(b); break;
      }
      case 'dialog': {
        const b = h('button', { class: 'fm-btn small', type: 'button', disabled: ro, text: 'Specify…' });
        b.addEventListener('click', async () => { const r = await FM.dlg.customDialogSpec(file, p[pp.key], o.to); if (r) set(r); });
        ctl.appendChild(b); break;
      }
      case 'importspec': case 'exportspec': {
        const b = h('button', { class: 'fm-btn small', type: 'button', disabled: ro, text: p[pp.key] ? 'Edit…' : 'Specify…' });
        b.addEventListener('click', async () => { const w = FM.app.activeWindow(file); const r = pp.k === 'exportspec' ? await FM.dlg.exportSpec(w, p[pp.key]) : await FM.dlg.importSpecNote(); if (r) set(r); });
        ctl.appendChild(b); break;
      }
      case 'calclist': {
        const list = p[pp.key] || [];
        const ta = h('textarea', { class: 'fm-input fm-mono', rows: 3, disabled: ro, placeholder: 'one calculation per line' });
        ta.value = list.join('\n');
        ta.addEventListener('input', () => set(ta.value.split('\n').filter(x => x.trim())));
        ctl.appendChild(ta); break;
      }
    }
    return wrap;
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Script Debugger
  // ═══════════════════════════════════════════════════════════════════════
  FM.debuggerUI = {
    el: null,
    start() {
      const runner = FM.app.runner;
      const dbg = runner.debugger = runner.debugger || {};
      dbg.active = true; dbg.mode = 'step'; dbg.target = null;
      dbg.before = (rt, fr, i) => this.before(rt, fr, i);
      this.show();
    },
    show() {
      if (this.el) this.el.remove();
      this.el = h('div', { class: 'fm-debugger' });
      document.body.appendChild(this.el);
      FM.makeDraggable(this.el, this.el);
      this.paint(null);
    },
    async before(rt, fr, i) {
      const dbg = FM.app.runner.debugger;
      const st = fr.steps[i];
      const atBreak = WS.breaks.has(st.id);
      const depth = rt.stack.length;
      let stop = dbg.mode === 'step' || atBreak || (dbg.mode === 'over' && depth <= dbg.depth) || (dbg.mode === 'out' && depth < dbg.depth);
      if (!stop) return;
      this.paint({ rt, fr, i });
      if (WS.el && WS.draft && WS.draft.id === fr.script.id) { WS.debugAt = { script: fr.script.id, i }; WS.renderSteps(); }
      const how = await new Promise(r => { this.resolve = r; });
      dbg.depth = depth;
      if (how === 'halt') { rt.halted = true; dbg.active = false; this.close(); }
      else if (how === 'run') dbg.mode = 'run';
      else if (how === 'over') dbg.mode = 'over';
      else if (how === 'into') dbg.mode = 'step';
      else if (how === 'out') dbg.mode = 'out';
    },
    paint(at) {
      const el = this.el; if (!el) return;
      el.innerHTML = '';
      const act = (how, icon, label, key) => h('button', { class: 'fm-btn small', title: label + (key ? ' (' + key + ')' : ''), disabled: !at, onclick: () => this.resolve && this.resolve(how) }, h('span', { html: FM.icon(icon, 14) }), ' ' + label);
      el.appendChild(h('div', { class: 'fm-dbg-title' }, h('span', { html: FM.icon('debug', 15) }), h('b', { text: ' Script Debugger' }), h('div', { class: 'fm-flex1' }), h('button', { class: 'fm-iconbtn', html: FM.icon('x', 14), onclick: () => { if (this.resolve) this.resolve('run'); FM.app.runner.debugger.active = false; this.close(); } })));
      el.appendChild(h('div', { class: 'fm-dbg-tools' }, act('over', 'stepover', 'Step Over', 'F5'), act('into', 'stepinto', 'Step Into', 'F6'), act('out', 'stepout', 'Step Out', 'F7'), act('run', 'play', 'Continue', 'F8'), act('halt', 'stop', 'Halt')));
      if (!at) { el.appendChild(h('div', { class: 'fm-muted small pad', text: 'Waiting for the script to start…' })); return; }
      const { rt, fr, i } = at;
      el.appendChild(h('div', { class: 'fm-dbg-sec', text: 'Call stack' }));
      const stack = h('div', { class: 'fm-dbg-stack' });
      rt.stack.slice().reverse().forEach(f => stack.appendChild(h('div', { text: f.script.name + '  (line ' + (f.pc + 1) + ')' })));
      el.appendChild(stack);
      el.appendChild(h('div', { class: 'fm-dbg-sec', text: fr.script.name }));
      const list = h('div', { class: 'fm-dbg-steps' });
      fr.steps.forEach((s, k) => { const r = h('div', { class: 'fm-dbg-step' + (k === i ? ' at' : '') + (s.off ? ' off' : '') + (WS.breaks.has(s.id) ? ' bp' : ''), text: (k + 1) + '  ' + (s.off ? '// ' : '') + FM.formatStep(s, rt.file) }); list.appendChild(r); if (k === i) setTimeout(() => r.scrollIntoView({ block: 'nearest' }), 0); });
      el.appendChild(list);
      el.appendChild(h('div', { class: 'fm-dbg-sec', text: 'Last error: ' + rt.lastError + (rt.lastError ? ' — ' + (FM.ERR[rt.lastError] || '') : '') }));
      el.appendChild(h('div', { class: 'fm-dbg-sec', text: 'Variables' }));
      el.appendChild(varsTable(rt.file, fr.vars));
    },
    close() { if (this.el) this.el.remove(); this.el = null; if (WS.debugAt) { WS.debugAt = null; WS.renderSteps(); } }
  };
  document.addEventListener('keydown', e => {
    const d = FM.debuggerUI; if (!d.el || !d.resolve) return;
    const m = { F5: 'over', F6: 'into', F7: 'out', F8: 'run' }[e.key];
    if (m) { e.preventDefault(); d.resolve(m); }
  });
  function varsTable(file, locals) {
    const t = h('table', { class: 'fm-vars' });
    const row = (n, rep, v) => t.appendChild(h('tr', null, h('td', { class: 'fm-mono', text: n + (rep > 1 ? '[' + rep + ']' : '') }), h('td', { class: 'fm-mono', text: V.text(v) })));
    const dump = (store) => { if (!store) return; store.forEach((reps, k) => reps.forEach((v, rep) => row((store.names && store.names.get(k)) || k, rep, v))); };
    dump(locals); dump(file.$$);
    if (!t.children.length) t.appendChild(h('tr', null, h('td', { class: 'fm-muted', colspan: 2, text: 'No variables' })));
    return t;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Data Viewer (Tools menu)
  // ═══════════════════════════════════════════════════════════════════════
  FM.dataViewer = {
    visible: false, watches: [], el: null,
    open() {
      try { this.watches = JSON.parse(localStorage.getItem('fm.watches') || '[]'); } catch (e) { this.watches = []; }
      if (this.el) this.el.remove();
      this.el = h('div', { class: 'fm-dataviewer' });
      document.body.appendChild(this.el);
      FM.makeDraggable(this.el, this.el);
      this.visible = true; this.tab = this.tab || 0;
      this.refresh();
    },
    close() { if (this.el) this.el.remove(); this.el = null; this.visible = false; },
    save() { try { localStorage.setItem('fm.watches', JSON.stringify(this.watches)); } catch (e) { /* storage blocked */ } },
    refresh() {
      const el = this.el; if (!el) return;
      el.innerHTML = '';
      const w = FM.app.activeWindow();
      el.appendChild(h('div', { class: 'fm-dbg-title' }, h('span', { html: FM.icon('eye', 15) }), h('b', { text: ' Data Viewer' }), h('div', { class: 'fm-flex1' }), h('button', { class: 'fm-iconbtn', title: 'Refresh', html: FM.icon('refresh', 14), onclick: () => this.refresh() }), h('button', { class: 'fm-iconbtn', html: FM.icon('x', 14), onclick: () => this.close() })));
      const tabs = h('div', { class: 'fm-tabs' }, ['Current', 'Watch'].map((n, i) => h('button', { class: 'fm-tab' + (this.tab === i ? ' on' : ''), text: n, onclick: () => { this.tab = i; this.refresh(); } })));
      el.appendChild(tabs);
      if (!w) { el.appendChild(h('div', { class: 'fm-muted pad', text: 'No window is open.' })); return; }
      const rt = FM.app.runner.current;
      if (this.tab === 0) {
        el.appendChild(h('div', { class: 'fm-muted small pad', text: rt ? 'Running: ' + rt.frame.script.name : 'No script running. Global ($$) variables:' }));
        el.appendChild(varsTable(w.file, rt ? rt.frame.vars : w.file.$0));
        return;
      }
      const t = h('table', { class: 'fm-vars' });
      t.appendChild(h('tr', null, h('th', { text: 'Expression' }), h('th', { text: 'Value' }), h('th')));
      this.watches.forEach((ex, i) => {
        let val;
        try { val = V.text(w.file.evaluate(ex, rt ? rt.ctx() : w.ctx(), true)); } catch (e) { val = '? ' + e.message; }
        t.appendChild(h('tr', null, h('td', { class: 'fm-mono', text: ex }), h('td', { class: 'fm-mono', text: val }), h('td', null, h('button', { class: 'fm-iconbtn', html: FM.icon('x', 12), onclick: () => { this.watches.splice(i, 1); this.save(); this.refresh(); } }))));
      });
      el.appendChild(t);
      el.appendChild(h('div', { class: 'pad' }, h('button', { class: 'fm-btn small', text: 'Add Expression…', onclick: async () => { const r = await FM.dlg.calc(w.file, { formula: '', to: w.to, title: 'Edit Expression', live: true }); if (r && r.formula.trim()) { this.watches.push(r.formula); this.save(); this.refresh(); } } })));
    }
  };
})();
