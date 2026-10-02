/* FileMaker (independent recreation) — Layout mode: the layout designer, its
   inspector and object setup dialogs, the New Layout/Report assistant, Manage
   Layouts, Layout Setup, Part Setup, tab order, conditional formatting and
   script triggers. */
(function () {
  'use strict';
  const FM = window.FM;
  const { h } = FM;
  const V = FM.V;
  const LABEL_W = 74;
  const THEMES = [['apex', 'Apex Blue'], ['enlightened', 'Enlightened'], ['minimal', 'Minimalist'], ['cool', 'Cool Gray'], ['dark', 'Dark Night'], ['classic', 'Classic']];
  FM.THEMES = THEMES;
  const OBJ_TRIGGERS = ['OnObjectEnter', 'OnObjectKeystroke', 'OnObjectModify', 'OnObjectValidate', 'OnObjectSave', 'OnObjectExit', 'OnPanelSwitch'];
  const LAYOUT_TRIGGERS = ['OnRecordLoad', 'OnRecordCommit', 'OnRecordRevert', 'OnLayoutKeystroke', 'OnLayoutEnter', 'OnLayoutExit', 'OnLayoutSizeChange', 'OnModeEnter', 'OnModeExit', 'OnViewChange'];
  FM.OBJ_TRIGGERS = OBJ_TRIGGERS; FM.LAYOUT_TRIGGERS = LAYOUT_TRIGGERS;

  // ═══════════════════════════════════════════════════════════════════════
  // building layouts
  // ═══════════════════════════════════════════════════════════════════════
  const D = FM.design = {};
  function colW(f) {
    if (!f) return 140;
    const t = f.type === 'calculation' ? ((f.options || {}).calc || {}).resultType : f.type;
    return { number: 100, date: 100, time: 90, timestamp: 160, container: 130 }[t] || 170;
  }
  const label = (text, x, y, w, hh, align) => ({ id: FM.uid('o'), type: 'text', text, x, y, w, h: hh || 20, style: { align: align || 'right', color: '#5b6573', size: 12, valign: 'middle' } });
  const fieldObj = (key, x, y, w, hh, f) => {
    const o = { id: FM.uid('o'), type: 'field', field: key, x, y, w, h: hh || 22, control: 'edit' };
    if (f && f.type === 'date') o.control = 'calendar';
    return o;
  };
  // kind: form | list | table | report | blank
  D.autoLayout = function (file, o) {
    const to = o.to; const kind = o.kind || 'form';
    const keys = (o.keys || []).filter(k => file.fieldByKey(k));
    const title = { id: FM.uid('o'), type: 'text', text: o.title || o.name, x: 20, y: 18, w: 400, h: 28, style: { size: 20, bold: true, color: '#1d2733', align: 'left', valign: 'middle' } };
    const lay = { id: FM.uid('L'), name: o.name, to, theme: o.theme || 'apex', width: 700, parts: [], objects: [], views: { form: true, list: true, table: true }, view: kind === 'table' ? 'table' : kind === 'list' || kind === 'report' ? 'list' : 'form', triggers: {} };
    if (kind === 'blank') {
      lay.parts = [{ id: FM.uid('p'), type: 'header', h: 64 }, { id: FM.uid('p'), type: 'body', h: 320 }, { id: FM.uid('p'), type: 'footer', h: 36 }];
      lay.objects.push(title);
      return lay;
    }
    if (kind === 'form') {
      const header = 64;
      let y = header + 18;
      keys.forEach(k => {
        const f = file.fieldByKey(k);
        const tall = f.type === 'container' ? 120 : (f.type === 'text' && /note|comment|description|address|memo/i.test(f.name)) ? 66 : 24;
        lay.objects.push(label(file.keyLabel(k, to), 20, y + (tall > 24 ? 2 : 2), 150, 20));
        lay.objects.push(fieldObj(k, 180, y, f.type === 'container' ? 200 : Math.max(220, colW(f) + 80), tall, f));
        y += tall + 10;
      });
      lay.parts = [{ id: FM.uid('p'), type: 'header', h: header }, { id: FM.uid('p'), type: 'body', h: Math.max(160, y - header + 20) }, { id: FM.uid('p'), type: 'footer', h: 36 }];
      lay.objects.push(title);
      lay.width = 640;
      return lay;
    }
    // list, table, report: one row per record
    const widths = keys.map(k => colW(file.fieldByKey(k)));
    const total = widths.reduce((a, b) => a + b + 8, 20);
    lay.width = Math.max(600, total + 12);
    const headerH = 84, rowH = 30;
    let x = 16;
    const head = [], body = [];
    keys.forEach((k, i) => {
      head.push(Object.assign(label(file.keyLabel(k, to), x, headerH - 24, widths[i], 18, 'left'), { style: { align: 'left', color: '#3c4654', size: 12, bold: true, valign: 'middle' } }));
      body.push(fieldObj(k, x, 0, widths[i], 22, file.fieldByKey(k)));
      x += widths[i] + 8;
    });
    const parts = [{ id: FM.uid('p'), type: 'header', h: headerH }];
    let y = headerH;
    const objs = [title, ...head];
    const groups = (o.groups || []).filter(k => file.fieldByKey(k));
    const totals = (o.totals || []).filter(k => file.fieldByKey(k));
    if (kind === 'report') {
      groups.forEach((g, gi) => {
        parts.push({ id: FM.uid('p'), type: 'sub_leading', h: 30, breakKey: g });
        objs.push({ id: FM.uid('o'), type: 'field', field: g, x: 16 + gi * 16, y: y + 5, w: 300, h: 20, control: 'edit', style: { bold: true, size: 13, color: '#1d2733', lineWidth: 0, fill: 'transparent' } });
        y += 30;
      });
    }
    parts.push({ id: FM.uid('p'), type: 'body', h: rowH });
    body.forEach(b => { b.y = y + 4; objs.push(b); });
    y += rowH;
    if (kind === 'report') {
      groups.slice().reverse().forEach(g => {
        parts.push({ id: FM.uid('p'), type: 'sub_trailing', h: 30, breakKey: g });
        totals.forEach(t => { const tk = FM.pkey(t); const col = keys.findIndex(k => { const s = file.field(tk.fid); return s && ((s.options || {}).summary || {}).field === FM.pkey(k).fid; }); const cx = col >= 0 ? 16 + widths.slice(0, col).reduce((a, b) => a + b + 8, 0) : lay.width - 140; objs.push({ id: FM.uid('o'), type: 'field', field: t, x: cx, y: y + 5, w: col >= 0 ? widths[col] : 120, h: 20, control: 'edit', style: { bold: true, lineWidth: 0, fill: 'transparent', align: 'right' }, format: { number: { kind: 'decimal', decimals: 2, thousands: true } } }); });
        objs.push(Object.assign(label('Subtotal', 16, y + 5, 120, 20, 'left'), { style: { bold: true, color: '#3c4654', align: 'left', valign: 'middle' } }));
        y += 30;
      });
      if (totals.length) {
        parts.push({ id: FM.uid('p'), type: 'trailing_grand', h: 36 });
        totals.forEach(t => { const tk = FM.pkey(t); const col = keys.findIndex(k => { const s = file.field(tk.fid); return s && ((s.options || {}).summary || {}).field === FM.pkey(k).fid; }); const cx = col >= 0 ? 16 + widths.slice(0, col).reduce((a, b) => a + b + 8, 0) : lay.width - 140; objs.push({ id: FM.uid('o'), type: 'field', field: t, x: cx, y: y + 8, w: col >= 0 ? widths[col] : 120, h: 20, control: 'edit', style: { bold: true, lineWidth: 0, fill: 'transparent', align: 'right' }, format: { number: { kind: 'decimal', decimals: 2, thousands: true } } }); });
        objs.push(Object.assign(label('Grand Total', 16, y + 8, 120, 20, 'left'), { style: { bold: true, color: '#1d2733', align: 'left', valign: 'middle' } }));
        y += 36;
      }
    }
    parts.push({ id: FM.uid('p'), type: 'footer', h: 34 });
    objs.push({ id: FM.uid('o'), type: 'text', text: 'Page {{PageNumber}} of {{PageCount}}', x: lay.width - 170, y: y + 8, w: 150, h: 18, style: { align: 'right', color: '#7a8594', size: 11, valign: 'middle' } });
    if (kind === 'report') objs.push({ id: FM.uid('o'), type: 'text', text: '{{CurrentDate}}', x: 16, y: y + 8, w: 150, h: 18, style: { align: 'left', color: '#7a8594', size: 11, valign: 'middle' } });
    lay.parts = parts; lay.objects = objs;
    return lay;
  };
  D.appendFields = function (file, lay, keys) {
    const tops = FM.partTops(lay); const body = tops.find(t => t.part.type === 'body');
    if (!body) return lay;
    const inBody = (lay.objects || []).filter(o => o.y >= body.top && o.y < body.bottom);
    let y = inBody.length ? Math.max(...inBody.map(o => o.y + o.h)) + 10 : body.top + 16;
    const add = [];
    keys.forEach(k => { const f = file.fieldByKey(k); const tall = f && f.type === 'container' ? 120 : 24; add.push(label(file.keyLabel(k, lay.to), 20, y + 2, 150, 20)); add.push(fieldObj(k, 180, y, f && f.type === 'container' ? 200 : 300, tall, f)); y += tall + 10; });
    const need = y + 10 - body.bottom;
    if (need > 0) { (lay.objects || []).forEach(o => { if (o.y >= body.bottom) shiftDeep(o, 0, need); }); body.part.h += need; }
    lay.objects = (lay.objects || []).concat(add);
    return lay;
  };
  function shiftDeep(o, dx, dy) {
    o.x += dx; o.y += dy;
    if (o.panel) { o.panel.x += dx; o.panel.y += dy; }
    (o.children || []).forEach(c => shiftDeep(c, dx, dy));
    (o.tabs || []).forEach(t => (t.children || []).forEach(c => shiftDeep(c, dx, dy)));
  }
  D.shiftDeep = shiftDeep;
  function reId(o) {
    o.id = FM.uid('o');
    (o.children || []).forEach(reId);
    (o.tabs || []).forEach(t => { t.id = FM.uid('b'); (t.children || []).forEach(reId); });
    return o;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Designer
  // ═══════════════════════════════════════════════════════════════════════
  class Designer {
    constructor(app, win) {
      this.app = app; this.win = win; this.file = win.file;
      this.load();
      this.tool = 'pointer'; this.zoom = 1; this.leftTab = 'fields'; this.inspTab = 0;
      this.tabState = {}; this.popOpen = {};
      this.fieldTO = win.to;
    }
    load() {
      this.layoutId = this.win.layoutId;
      this.lay = FM.clone(this.win.layout);
      this.lay.objects = this.lay.objects || []; this.lay.parts = this.lay.parts || [];
      this.sel = new Set(); this.undoStack = []; this.redoStack = []; this.dirty = false;
    }
    // ── structure helpers ───────────────────────────────────────────────
    find(id, list, parent) {
      list = list || this.lay.objects;
      for (const o of list) {
        if (o.id === id) return { o, list, parent: parent || null };
        if (o.children) { const r = this.find(id, o.children, o); if (r) return r; }
        if (o.tabs) for (const t of o.tabs) { const r = this.find(id, t.children || (t.children = []), o); if (r) return r; }
      }
      return null;
    }
    visible() { // paint order: [{o, parent}]
      const out = [];
      const walk = (list, parent) => list.forEach(o => {
        out.push({ o, parent });
        if (o.type === 'portal' || o.type === 'group') walk(o.children || [], o);
        if (o.tabs) { const i = this.tabState[o.id] || 0; const t = o.tabs[Math.min(i, o.tabs.length - 1)]; if (t) walk(t.children || (t.children = []), o); }
        if (o.type === 'popover' && this.popOpen[o.id]) walk(o.children || (o.children = []), o);
      });
      walk(this.lay.objects, null);
      return out;
    }
    selected() { return [...this.sel].map(id => this.find(id)).filter(Boolean).map(r => r.o); }
    snapshot() { this.undoStack.push(JSON.stringify(this.lay)); if (this.undoStack.length > 100) this.undoStack.shift(); this.redoStack = []; this.dirty = true; }
    undo() { if (!this.undoStack.length) return; this.redoStack.push(JSON.stringify(this.lay)); this.lay = JSON.parse(this.undoStack.pop()); this.dirty = true; this.cleanSel(); this.paint(); }
    redo() { if (!this.redoStack.length) return; this.undoStack.push(JSON.stringify(this.lay)); this.lay = JSON.parse(this.redoStack.pop()); this.dirty = true; this.cleanSel(); this.paint(); }
    cleanSel() { this.sel = new Set([...this.sel].filter(id => this.find(id))); }
    grid() { return this.app.prefs.snap === false ? 1 : (this.app.prefs.grid || 8); }
    snap(v, force) { const g = force || this.grid(); return Math.round(v / g) * g; }

    // ── rendering ───────────────────────────────────────────────────────
    render(content) {
      this.content = content;
      content.innerHTML = '';
      const left = h('div', { class: 'fm-d-left' });
      const center = h('div', { class: 'fm-d-center' });
      const right = h('div', { class: 'fm-d-right' });
      content.appendChild(h('div', { class: 'fm-designer' }, left, center, right));
      this.leftEl = left; this.centerEl = center; this.rightEl = right;
      this.renderLeft();
      this.renderCanvas();
      this.renderInspector();
    }
    // objects must start inside a part: the last part grows to hold anything dropped below it
    fitParts() {
      const lay = this.lay; if (!lay.parts.length) return;
      lay.objects.forEach(o => { if (o.y < 0) shiftDeep(o, 0, -o.y); if (o.x < 0) shiftDeep(o, -o.x, 0); });
      const total = FM.layoutHeight(lay);
      const maxY = Math.max(-1, ...lay.objects.map(o => o.y));
      if (maxY >= total) { const last = FM.sortParts(lay.parts).slice(-1)[0]; const below = lay.objects.filter(o => o.y >= total); last.h += Math.max(...below.map(o => o.y + o.h)) - total + 4; }
    }
    paint() { if (!this.centerEl) return; this.fitParts(); const sc = [this.centerEl.scrollLeft, this.centerEl.scrollTop]; this.renderCanvas(); this.centerEl.scrollLeft = sc[0]; this.centerEl.scrollTop = sc[1]; this.renderInspector(); this.renderLeft(); this.app.renderChrome(this.win); }
    renderLeft() {
      const el = this.leftEl; if (!el) return; el.innerHTML = '';
      const tabs = h('div', { class: 'fm-tabs' }, ['Fields', 'Objects'].map((n, i) => h('button', { class: 'fm-tab' + ((this.leftTab === 'fields') === (i === 0) ? ' on' : ''), text: n, onclick: () => { this.leftTab = i ? 'objects' : 'fields'; this.renderLeft(); } })));
      el.appendChild(tabs);
      if (this.leftTab === 'fields') {
        const sel = FM.toSelect(this.file, this.lay.to, this.fieldTO);
        sel.addEventListener('change', () => { this.fieldTO = sel.value; this.renderLeft(); });
        const withLabels = FM.check('Labels', this.app.prefs.fieldLabels !== false);
        withLabels.input.onchange = () => { this.app.prefs.fieldLabels = withLabels.input.checked; this.app.savePrefs(); };
        el.append(sel, withLabels);
        const list = h('div', { class: 'fm-d-fields' });
        const t = this.file.tableOfTO(this.fieldTO);
        const used = new Set(FM.layoutFields(this.lay));
        (t ? t.fields : []).forEach(f => {
          const key = FM.fkey(this.fieldTO, f.id);
          const it = h('div', { class: 'fm-d-field' + (used.has(key) ? ' used' : ''), draggable: 'true', title: 'Drag onto the layout' }, h('span', { class: 'fm-d-ftype', text: { text: 'T', number: '#', date: 'D', time: 'Ti', timestamp: 'TS', container: '▣', calculation: '=', summary: 'Σ' }[f.type] }), h('span', { text: f.name }));
          it.addEventListener('dragstart', e => { e.dataTransfer.setData('text/fm-field', key); });
          it.addEventListener('dblclick', () => this.addFieldAt(key, null));
          list.appendChild(it);
        });
        el.appendChild(list);
        el.appendChild(h('button', { class: 'fm-btn small', text: 'Manage Database…', onclick: async () => { await this.saveQuiet(); await FM.dlg.manageDatabase(this.file, { tab: 1, table: (t || {}).id }); this.renderLeft(); } }));
      } else {
        const list = h('div', { class: 'fm-d-objs' });
        const walk = (objs, depth) => objs.slice().reverse().forEach(o => {
          const row = h('div', { class: 'fm-d-objrow' + (this.sel.has(o.id) ? ' on' : '') }, h('span', { html: FM.icon(iconFor(o), 13) }), h('span', { text: o.name || describe(this.file, o, this.lay.to) }));
          row.style.paddingLeft = (6 + depth * 12) + 'px';
          row.onclick = e => { if (e.shiftKey) { if (this.sel.has(o.id)) this.sel.delete(o.id); else this.sel.add(o.id); } else this.sel = new Set([o.id]); this.paint(); };
          list.appendChild(row);
          if (o.children) walk(o.children, depth + 1);
          if (o.tabs) o.tabs.forEach(tb => { list.appendChild(h('div', { class: 'fm-d-objrow fm-muted', style: { paddingLeft: (18 + depth * 12) + 'px' }, text: '▸ ' + (tb.label || 'Panel') })); walk(tb.children || [], depth + 2); });
        });
        walk(this.lay.objects, 0);
        el.appendChild(list);
      }
    }
    renderCanvas() {
      const c = this.centerEl; if (!c) return;
      c.innerHTML = '';
      const lay = this.lay;
      const width = lay.width || 800;
      const height = FM.layoutHeight(lay);
      const stage = h('div', { class: 'fm-d-stage fm-theme-' + (lay.theme || 'apex') });
      stage.style.width = (LABEL_W + width + 200) * this.zoom + 'px';
      stage.style.height = (height + 160) * this.zoom + 'px';
      const inner = h('div', { class: 'fm-d-inner' });
      inner.style.transform = 'scale(' + this.zoom + ')';
      const area = h('div', { class: 'fm-d-area fm-layout fm-theme-' + (lay.theme || 'apex') });
      area.style.left = LABEL_W + 'px'; area.style.width = (width + 180) + 'px'; area.style.height = (height + 140) + 'px';
      if (this.app.prefs.showGrid !== false) area.classList.add('fm-d-grid');
      area.style.setProperty('--grid', (this.app.prefs.grid || 8) + 'px');
      // parts
      FM.partTops(lay).forEach(t => {
        const band = h('div', { class: 'fm-d-part fm-part-' + t.part.type });
        band.style.top = t.top + 'px'; band.style.height = t.part.h + 'px'; band.style.width = width + 'px';
        if (t.part.fill) band.style.background = t.part.fill;
        area.appendChild(band);
        const lab = h('div', { class: 'fm-d-partlabel', title: 'Double-click for Part Setup. Drag the line below to resize.' }, h('span', { text: (FM.PART_NAMES[t.part.type] || t.part.type).replace(/ \((leading|trailing)\)/, '') + (t.part.breakKey ? ' by ' + this.file.keyLabel(t.part.breakKey, lay.to) : '') }));
        lab.style.top = t.top + 'px'; lab.style.height = t.part.h + 'px';
        lab.addEventListener('dblclick', () => this.partSetup(t.part));
        inner.appendChild(lab);
        const grip = h('div', { class: 'fm-d-partgrip' });
        grip.style.top = (t.bottom - 3) + 'px'; grip.style.width = (LABEL_W + width) + 'px';
        grip.addEventListener('mousedown', e => this.startPartResize(e, t.part));
        inner.appendChild(grip);
      });
      const edge = h('div', { class: 'fm-d-edge', title: 'Drag to change the layout width' });
      edge.style.left = width + 'px'; edge.style.height = height + 'px';
      edge.addEventListener('mousedown', e => this.startWidthResize(e));
      area.appendChild(edge);
      // objects
      this.nodes = new Map();
      this.visible().forEach(({ o }) => {
        const n = this.objNode(o);
        if (!n) return;
        n.classList.add('fm-obj', 'fm-d-obj');
        n.style.left = o.x + 'px'; n.style.top = o.y + 'px'; n.style.width = o.w + 'px'; n.style.height = o.h + 'px';
        if (o.type !== 'field' && o.type !== 'line') Object.assign(n.style, FM.styleCss(o.style));
        if (o.locked) n.classList.add('locked');
        area.appendChild(n);
        this.nodes.set(o.id, n);
      });
      // selection overlay
      this.selected().forEach(o => {
        const box = h('div', { class: 'fm-d-sel' });
        box.style.left = o.x + 'px'; box.style.top = o.y + 'px'; box.style.width = o.w + 'px'; box.style.height = o.h + 'px';
        if (this.sel.size === 1 && !o.locked) ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].forEach(hd => { const g = h('div', { class: 'fm-d-handle h-' + hd }); g.addEventListener('mousedown', e => this.startResize(e, o, hd)); box.appendChild(g); });
        area.appendChild(box);
      });
      inner.appendChild(area);
      stage.appendChild(inner);
      c.appendChild(stage);
      this.area = area;
      area.addEventListener('mousedown', e => this.mouseDown(e));
      area.addEventListener('dblclick', e => this.dblClick(e));
      area.addEventListener('contextmenu', e => this.contextMenu(e));
      area.addEventListener('dragover', e => { if (e.dataTransfer.types.includes('text/fm-field')) e.preventDefault(); });
      area.addEventListener('drop', e => { const k = e.dataTransfer.getData('text/fm-field'); if (k) { e.preventDefault(); const p = this.pt(e); this.addFieldAt(k, p); } });
      c.tabIndex = 0;
    }
    objNode(o) {
      const file = this.file;
      switch (o.type) {
        case 'field': {
          const f = file.fieldByKey(o.field);
          const n = h('div', { class: 'fm-field fm-d-fieldbox fm-ctl-' + (o.control || 'edit') });
          Object.assign(n.style, FM.styleCss(o.style));
          const name = f ? file.keyLabel(o.field, this.lay.to) : '<Field Missing>';
          const reps = f ? Math.min(file.reps(f), Math.max(1, o.reps || 1)) : 1;
          for (let i = 0; i < reps; i++) {
            const cell = h('div', { class: 'fm-d-fv', text: (o.control === 'checkbox' ? '☐ ' : o.control === 'radio' ? '◯ ' : '') + name + (o.control === 'popup' || o.control === 'dropdown' ? '  ▾' : o.control === 'calendar' ? '  ▦' : '') });
            cell.style.height = (o.h / reps) + 'px';
            if (o.style) { if (o.style.size) cell.style.fontSize = o.style.size + 'px'; if (o.style.color) cell.style.color = o.style.color; if (o.style.bold) cell.style.fontWeight = 700; if (o.style.align) cell.style.textAlign = o.style.align; }
            if (f && f.type === 'container') cell.innerHTML = FM.icon('image', 22) + ' <span>' + FM.esc(name) + '</span>';
            n.appendChild(cell);
          }
          if (!f) n.classList.add('fm-missing');
          return n;
        }
        case 'text': { const n = h('div', { class: 'fm-text' + (o.style && o.style.valign ? ' fm-valign' : '') }); n.textContent = o.text || ''; return n; }
        case 'rect': case 'roundrect': case 'oval': return h('div', { class: 'fm-shape fm-' + o.type });
        case 'line': {
          const n = this.win.renderObject(o, { to: this.lay.to }, 0, 0, 0);
          if (n) { n.classList.remove('fm-obj'); n.style.left = ''; n.style.top = ''; }
          return n;
        }
        case 'button': return h('div', { class: 'fm-button' }, o.icon ? h('span', { class: 'fm-btn-icon', html: FM.icon(o.icon, Math.min(20, o.h - 6)) }) : null, o.label ? h('span', { class: 'fm-btn-label', text: o.label }) : null);
        case 'buttonbar': return h('div', { class: 'fm-buttonbar' }, (o.segments || []).map(s => h('div', { class: 'fm-button fm-seg' }, s.icon ? h('span', { html: FM.icon(s.icon, 15) }) : null, s.label ? h('span', { text: s.label }) : null)));
        case 'popover': {
          const n = h('div', { class: 'fm-popover-btn' }, h('div', { class: 'fm-button' }, o.icon ? h('span', { html: FM.icon(o.icon, 15) }) : null, h('span', { text: o.label || 'Popover' })));
          if (this.popOpen[o.id] && o.panel) {
            const p = h('div', { class: 'fm-popover-panel fm-d-panel' });
            p.style.left = (o.panel.x - o.x) + 'px'; p.style.top = (o.panel.y - o.y) + 'px'; p.style.width = o.panel.w + 'px'; p.style.height = o.panel.h + 'px';
            if (o.panel.title) p.appendChild(h('div', { class: 'fm-popover-title', text: o.panel.title }));
            n.appendChild(p); n.style.overflow = 'visible';
          }
          return n;
        }
        case 'portal': {
          const n = h('div', { class: 'fm-portal fm-d-portal' + (o.alt ? ' fm-portal-alt' : '') });
          const rows = Math.max(1, o.rows || 4);
          for (let i = 0; i < rows; i++) { const r = h('div', { class: 'fm-portal-row' + (i % 2 ? ' odd' : '') }); r.style.top = (i * o.h / rows) + 'px'; r.style.height = (o.h / rows) + 'px'; n.appendChild(r); }
          n.appendChild(h('div', { class: 'fm-d-portal-tag', text: 'Portal: ' + ((file.to(o.to) || {}).name || '<none>') }));
          return n;
        }
        case 'tab': case 'slide': {
          const n = h('div', { class: o.type === 'slide' ? 'fm-slide' : 'fm-tabctl' });
          const cur = this.tabState[o.id] || 0;
          if (o.type === 'tab') {
            const head = h('div', { class: 'fm-tabhead', style: { height: (o.tabHeight || 26) + 'px' } });
            (o.tabs || []).forEach((t, i) => { const b = h('div', { class: 'fm-tabbtn' + (i === cur ? ' on' : ''), text: t.label || 'Tab' }); b.addEventListener('mousedown', e => { e.stopPropagation(); this.tabState[o.id] = i; this.sel = new Set([o.id]); this.paint(); }); head.appendChild(b); });
            n.appendChild(head);
          } else {
            const dots = h('div', { class: 'fm-dots' });
            (o.tabs || []).forEach((t, i) => { const d = h('span', { class: i === cur ? 'on' : '' }); d.addEventListener('mousedown', e => { e.stopPropagation(); this.tabState[o.id] = i; this.paint(); }); dots.appendChild(d); });
            n.appendChild(dots);
          }
          return n;
        }
        case 'chart': { const n = h('div', { class: 'fm-chart' }); n.appendChild(FM.chart.render(Object.assign(Object.create(this.win), { mode: 'layout' }), o, { to: this.lay.to })); return n; }
        case 'webviewer': return h('div', { class: 'fm-webviewer fm-d-wv' }, h('span', { html: FM.icon('web', 26) }), h('div', { class: 'fm-mono small', text: o.url || '(no address)' }));
        case 'image': return h('div', { class: 'fm-image' }, o.src ? h('img', { src: o.src, style: { objectFit: o.fit || 'contain' } }) : h('span', { html: FM.icon('image', 24) }));
        case 'group': return h('div', { class: 'fm-d-group' });
      }
      return null;
    }

    // ── mouse ───────────────────────────────────────────────────────────
    pt(e) { const r = this.area.getBoundingClientRect(); return { x: (e.clientX - r.left) / this.zoom, y: (e.clientY - r.top) / this.zoom }; }
    hit(p) {
      const vis = this.visible();
      for (let i = vis.length - 1; i >= 0; i--) {
        const o = vis[i].o;
        if (o.type === 'line') { if (distToSeg(p, o) < 5) return o; continue; }
        if (p.x >= o.x && p.x <= o.x + o.w && p.y >= o.y && p.y <= o.y + o.h) {
          if (o.type === 'group') { const top = this.topOf(o); return top; }
          return this.topOf(o);
        }
      }
      return null;
    }
    topOf(o) { // grouped objects select their group
      const r = this.find(o.id); let cur = r;
      while (cur && cur.parent && cur.parent.type === 'group') cur = this.find(cur.parent.id);
      return cur ? cur.o : o;
    }
    mouseDown(e) {
      if (e.button !== 0) return;
      if (e.target.closest('.fm-d-handle') || e.target.closest('.fm-d-edge')) return;
      this.centerEl.focus({ preventScroll: true });
      const p = this.pt(e);
      if (this.tool !== 'pointer') return this.startDraw(e, p);
      const o = this.hit(p);
      if (!o) { if (!e.shiftKey) this.sel = new Set(); return this.startMarquee(e, p); }
      if (e.shiftKey) { if (this.sel.has(o.id)) this.sel.delete(o.id); else this.sel.add(o.id); this.paint(); return; }
      if (!this.sel.has(o.id)) { this.sel = new Set([o.id]); this.paint(); }
      if (this.selected().some(x => x.locked)) return;
      this.startMove(e, p);
    }
    startMove(e, p0) {
      const objs = this.selected();
      const orig = objs.map(o => ({ o, x: o.x, y: o.y }));
      let moved = false, snapDone = false;
      const mv = ev => {
        const p = this.pt(ev);
        let dx = p.x - p0.x, dy = p.y - p0.y;
        if (!moved && Math.abs(dx) + Math.abs(dy) < 3) return;
        if (!moved) { this.snapshot(); moved = true; }
        if (ev.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
        const first = orig[0];
        const nx = ev.altKey ? first.x + dx : this.snap(first.x + dx), ny = ev.altKey ? first.y + dy : this.snap(first.y + dy);
        const ddx = nx - first.o.x, ddy = ny - first.o.y;
        if (ddx || ddy) { orig.forEach(({ o }) => shiftDeep(o, ddx, ddy)); snapDone = true; this.renderCanvas(); }
      };
      const up = () => {
        document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up);
        if (moved) { this.reparent(objs); this.paint(); }
        void snapDone;
      };
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
    }
    // objects dropped inside a portal row, a tab panel or an open popover move into it
    reparent(objs) {
      const containers = this.visible().map(v => v.o).filter(o => o.type === 'portal' || o.tabs || (o.type === 'popover' && this.popOpen[o.id]));
      objs.forEach(o => {
        const desc = new Set(); (function walk(x) { desc.add(x.id); (x.children || []).forEach(walk); (x.tabs || []).forEach(t => (t.children || []).forEach(walk)); })(o);
        let target = null, list = this.lay.objects;
        for (const c of containers) {
          if (desc.has(c.id)) continue;
          let r;
          if (c.type === 'portal') r = { x: c.x, y: c.y, w: c.w, h: c.h / Math.max(1, c.rows || 4) };
          else if (c.tabs) { const th = c.type === 'slide' ? 0 : (c.tabHeight || 26); r = { x: c.x, y: c.y + th, w: c.w, h: c.h - th }; }
          else r = c.panel;
          if (r && o.x >= r.x - 1 && o.y >= r.y - 1 && o.x + o.w <= r.x + r.w + 1 && o.y + o.h <= r.y + r.h + 1) {
            if (o.type === 'portal' && c.type === 'portal') continue;
            target = c;
            if (c.tabs) { const i = Math.min(this.tabState[c.id] || 0, c.tabs.length - 1); list = c.tabs[i].children = c.tabs[i].children || []; }
            else list = c.children = c.children || [];
          }
        }
        const cur = this.find(o.id);
        if (!cur || cur.list === list) return;
        if (cur.parent && cur.parent.type === 'group') return;
        cur.list.splice(cur.list.indexOf(o), 1);
        list.push(o);
        void target;
      });
    }
    startResize(e, o, hd) {
      e.stopPropagation(); e.preventDefault();
      this.snapshot();
      const p0 = this.pt(e); const s = { x: o.x, y: o.y, w: o.w, h: o.h };
      const mv = ev => {
        const p = this.pt(ev); const dx = p.x - p0.x, dy = p.y - p0.y;
        let { x, y, w, h: hh } = s;
        const sn = v => ev.altKey ? v : this.snap(v);
        if (hd.includes('e')) w = sn(s.x + s.w + dx) - s.x;
        if (hd.includes('s')) hh = sn(s.y + s.h + dy) - s.y;
        if (hd.includes('w')) { x = sn(s.x + dx); w = s.x + s.w - x; }
        if (hd.includes('n')) { y = sn(s.y + dy); hh = s.y + s.h - y; }
        const minW = o.type === 'line' ? 0 : 6, minH = o.type === 'line' ? 0 : 6;
        if (w < minW) { w = minW; } if (hh < minH) { hh = minH; }
        o.x = x; o.y = y; o.w = w; o.h = hh;
        if (ev.shiftKey && o.type !== 'line') { const m = Math.max(o.w, o.h); o.w = o.h = m; }
        this.renderCanvas();
      };
      const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); this.paint(); };
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
    }
    startMarquee(e, p0) {
      const box = h('div', { class: 'fm-d-marquee' }); this.area.appendChild(box);
      const before = new Set(this.sel);
      const mv = ev => {
        const p = this.pt(ev);
        const r = { x: Math.min(p.x, p0.x), y: Math.min(p.y, p0.y), w: Math.abs(p.x - p0.x), h: Math.abs(p.y - p0.y) };
        Object.assign(box.style, { left: r.x + 'px', top: r.y + 'px', width: r.w + 'px', height: r.h + 'px' });
        this.sel = new Set(before);
        this.visible().forEach(({ o, parent }) => { if ((!parent || !this.sel.has(parent.id)) && o.x >= r.x && o.y >= r.y && o.x + o.w <= r.x + r.w && o.y + o.h <= r.y + r.h) { const top = this.topOf(o); this.sel.add(top.id); } });
      };
      const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); box.remove(); this.paint(); };
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
    }
    startDraw(e, p0) {
      const tool = this.tool;
      const box = h('div', { class: 'fm-d-marquee draw' }); this.area.appendChild(box);
      const s0 = { x: this.snap(p0.x), y: this.snap(p0.y) };
      let r = { x: s0.x, y: s0.y, w: 0, h: 0 };
      const mv = ev => { const p = this.pt(ev); const x2 = this.snap(p.x), y2 = this.snap(p.y); r = { x: Math.min(x2, s0.x), y: Math.min(y2, s0.y), w: Math.abs(x2 - s0.x), h: Math.abs(y2 - s0.y) }; if (tool === 'line') r.dir = (x2 - s0.x) * (y2 - s0.y) < 0 ? 'up' : 'down'; Object.assign(box.style, { left: r.x + 'px', top: r.y + 'px', width: r.w + 'px', height: r.h + 'px' }); };
      const up = async () => {
        document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); box.remove();
        if (r.w < 4 && r.h < 4) { const d = DEFAULT_SIZE[tool] || [120, 24]; r.w = d[0]; r.h = d[1]; }
        this.tool = 'pointer'; this.app.renderChrome(this.win);
        await this.create(tool, r);
      };
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
    }
    async create(tool, r) {
      const base = { id: FM.uid('o'), x: r.x, y: r.y, w: Math.max(r.w, tool === 'line' ? 0 : 8), h: Math.max(r.h, tool === 'line' ? 0 : 8) };
      let o;
      switch (tool) {
        case 'text': o = Object.assign(base, { type: 'text', text: 'Text', style: { size: 13, color: '#1d2733' } }); break;
        case 'line': o = Object.assign(base, { type: 'line', dir: r.dir || 'down', style: { line: '#7a8594', lineWidth: 1 } }); break;
        case 'rect': o = Object.assign(base, { type: 'rect', style: { fill: '#ffffff', line: '#9aa3ae', lineWidth: 1 } }); break;
        case 'roundrect': o = Object.assign(base, { type: 'roundrect', style: { fill: '#ffffff', line: '#9aa3ae', lineWidth: 1, radius: 10 } }); break;
        case 'oval': o = Object.assign(base, { type: 'oval', style: { fill: '#ffffff', line: '#9aa3ae', lineWidth: 1 } }); break;
        case 'field': case 'checkbox': case 'radio': case 'popup': case 'dropdown': case 'calendar': {
          const res = await FM.dlg.pickField(this.file, { to: this.lay.to, label: true, title: 'Specify Field' });
          if (!res || !res.key) return;
          this.snapshot();
          o = Object.assign(base, { type: 'field', field: res.key, control: tool === 'field' ? 'edit' : tool });
          if (o.h < 20) o.h = 22;
          if (res.label) this.lay.objects.push(Object.assign(label(this.file.keyLabel(res.key, this.lay.to), o.x - 160, o.y + 1, 150, 20)));
          if (['checkbox', 'radio', 'popup', 'dropdown'].includes(tool) && this.file.schema.valueLists.length) o.valueList = this.file.schema.valueLists[0].id;
          this.insert(o, true);
          return;
        }
        case 'button': o = Object.assign(base, { type: 'button', label: 'Button', action: { kind: 'none' } }); if (o.h < 20) o.h = 26; break;
        case 'buttonbar': o = Object.assign(base, { type: 'buttonbar', segments: [{ label: 'One', action: { kind: 'none' } }, { label: 'Two', action: { kind: 'none' } }, { label: 'Three', action: { kind: 'none' } }] }); if (o.h < 20) o.h = 28; break;
        case 'popover': o = Object.assign(base, { type: 'popover', label: 'Popover', children: [], panel: { x: r.x, y: r.y + Math.max(r.h, 26) + 8, w: 260, h: 160, title: 'Popover' } }); if (o.h < 20) o.h = 26; this.popOpen[o.id] = true; break;
        case 'portal': {
          const others = this.file.schema.tableOccurrences.filter(x => x.id !== this.lay.to && this.file.path(this.lay.to, x.id));
          if (!others.length) { await FM.alert('There are no related tables. Relate another table to "' + (this.file.to(this.lay.to) || {}).name + '" in Manage Database first.', { icon: 'info' }); return; }
          o = Object.assign(base, { type: 'portal', to: others[0].id, rows: 4, children: [], allowDelete: true, scroll: true });
          if (o.h < 60) o.h = 120; if (o.w < 120) o.w = 360;
          this.snapshot(); this.lay.objects.push(o); this.sel = new Set([o.id]);
          const ok = await this.portalSetup(o, true);
          if (ok && ok.keys && ok.keys.length) {
            const rowH = o.h / o.rows; let x = o.x + 4;
            ok.keys.forEach(k => { const f = this.file.fieldByKey(k); const w = Math.min(160, colW(f)); o.children.push({ id: FM.uid('o'), type: 'field', field: k, x, y: o.y + Math.max(2, (rowH - 22) / 2), w, h: Math.min(22, rowH - 4), control: 'edit' }); x += w + 4; });
            if (x > o.x + o.w) o.w = x - o.x + 4;
          }
          this.paint();
          return;
        }
        case 'tab': o = Object.assign(base, { type: 'tab', tabs: [{ id: FM.uid('b'), label: 'Tab 1', children: [] }, { id: FM.uid('b'), label: 'Tab 2', children: [] }], tabHeight: 26 }); if (o.h < 80) o.h = 200; if (o.w < 120) o.w = 400; break;
        case 'slide': o = Object.assign(base, { type: 'slide', tabs: [{ id: FM.uid('b'), label: 'Panel 1', children: [] }, { id: FM.uid('b'), label: 'Panel 2', children: [] }, { id: FM.uid('b'), label: 'Panel 3', children: [] }], style: { fill: '#f7f8fa', line: '#d0d5dc', lineWidth: 1 } }); if (o.h < 80) o.h = 200; if (o.w < 120) o.w = 400; break;
        case 'webviewer': o = Object.assign(base, { type: 'webviewer', url: '', interact: true }); if (o.h < 60) o.h = 200; if (o.w < 120) o.w = 300; this.snapshot(); this.insert(o, false); await this.webViewerSetup(o); this.paint(); return;
        case 'chart': o = Object.assign(base, { type: 'chart', chart: { type: 'column', title: 'Chart', source: 'found', x: '', series: [{ name: 'Series 1', calc: '' }], legend: true } }); if (o.h < 80) o.h = 220; if (o.w < 120) o.w = 360; this.snapshot(); this.insert(o, false); await this.chartSetup(o); this.paint(); return;
        case 'image': { const f = await FM.pickFile('image/*'); if (!f) return; if (f.size > 1500000) { await FM.alert('Choose an image smaller than 1.5 MB. (Use a container field for larger files.)'); return; } const src = await FM.readDataURL(f); o = Object.assign(base, { type: 'image', src }); if (o.w < 20) { o.w = 160; o.h = 120; } break; }
        default: return;
      }
      this.snapshot();
      this.insert(o, false);
      if (tool === 'text') setTimeout(() => this.editText(o), 20);
    }
    insert(o, already) {
      if (!already) { /* snapshot taken by the caller */ }
      this.lay.objects.push(o);
      this.reparent([o]);
      this.sel = new Set([o.id]);
      this.paint();
    }
    async addFieldAt(key, p) {
      const f = this.file.fieldByKey(key); if (!f) return;
      this.snapshot();
      const body = FM.partTops(this.lay).find(t => t.part.type === 'body') || FM.partTops(this.lay)[0];
      let x, y;
      if (p) { x = this.snap(p.x); y = this.snap(p.y); }
      else { const inBody = this.lay.objects.filter(o => body && o.y >= body.top && o.y < body.bottom); x = 180; y = inBody.length ? Math.max(...inBody.map(o => o.y + o.h)) + 10 : (body ? body.top + 16 : 20); }
      const o = fieldObj(key, x, y, f.type === 'container' ? 200 : Math.max(160, colW(f) + 40), f.type === 'container' ? 120 : 22, f);
      const objs = [o];
      if (this.app.prefs.fieldLabels !== false && !this.inPortalArea(x, y)) objs.unshift(label(this.file.keyLabel(key, this.lay.to), Math.max(0, x - 160), y + 1, 150, 20));
      objs.forEach(x2 => this.lay.objects.push(x2));
      this.reparent(objs);
      this.sel = new Set([o.id]);
      if (body && y + 30 > body.bottom) { const need = y + 30 - body.bottom; this.lay.objects.forEach(x2 => { if (x2.y >= body.bottom && !objs.includes(x2)) shiftDeep(x2, 0, need); }); body.part.h += need; }
      this.paint();
    }
    inPortalArea(x, y) { return this.visible().some(({ o }) => o.type === 'portal' && x >= o.x && x <= o.x + o.w && y >= o.y && y <= o.y + o.h); }
    startPartResize(e, part) {
      e.preventDefault(); e.stopPropagation();
      this.snapshot();
      const tops = FM.partTops(this.lay); const me = tops.find(t => t.part === part);
      const y0 = e.clientY, h0 = part.h;
      const below = this.lay.objects.filter(o => o.y >= me.bottom);
      let applied = 0;
      const mv = ev => {
        let nh = Math.max(4, Math.round(h0 + (ev.clientY - y0) / this.zoom));
        // a part cannot shrink past the objects inside it
        const inside = this.lay.objects.filter(o => o.y >= me.top && o.y < me.top + h0);
        const minH = inside.length ? Math.max(...inside.map(o => o.y)) - me.top + 1 : 4;
        nh = Math.max(nh, minH);
        const delta = nh - h0 - applied;
        if (delta) { below.forEach(o => shiftDeep(o, 0, delta)); applied += delta; part.h = nh; this.renderCanvas(); }
      };
      const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); this.paint(); };
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
    }
    startWidthResize(e) {
      e.preventDefault(); e.stopPropagation();
      this.snapshot();
      const x0 = e.clientX, w0 = this.lay.width || 800;
      const mv = ev => { this.lay.width = Math.max(100, this.snap(w0 + (ev.clientX - x0) / this.zoom)); this.renderCanvas(); };
      const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); this.paint(); };
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
    }
    dblClick(e) {
      const p = this.pt(e);
      const o = this.hit(p);
      if (!o) return;
      this.sel = new Set([o.id]);
      switch (o.type) {
        case 'text': return this.editText(o);
        case 'field': return this.fieldSetup(o);
        case 'button': return this.buttonSetup(o);
        case 'buttonbar': return this.buttonBarSetup(o);
        case 'portal': return this.portalSetup(o);
        case 'tab': case 'slide': return this.tabSetup(o);
        case 'chart': return this.chartSetup(o).then(() => this.paint());
        case 'webviewer': return this.webViewerSetup(o).then(() => this.paint());
        case 'popover': this.popOpen[o.id] = !this.popOpen[o.id]; return this.paint();
        case 'group': { const inner = [...(o.children || [])].reverse().find(c => p.x >= c.x && p.x <= c.x + c.w && p.y >= c.y && p.y <= c.y + c.h); if (inner) { this.sel = new Set([inner.id]); this.paint(); } return; }
      }
    }
    editText(o) {
      const n = this.nodes.get(o.id); if (!n) return;
      n.contentEditable = 'true'; n.classList.add('editing'); n.focus();
      const range = document.createRange(); range.selectNodeContents(n); const s = getSelection(); s.removeAllRanges(); s.addRange(range);
      const done = () => { n.contentEditable = 'false'; const t = n.innerText.replace(/\n$/, ''); if (t !== o.text) { this.snapshot(); o.text = t; } this.paint(); };
      n.addEventListener('blur', done, { once: true });
      n.addEventListener('keydown', ev => { if (ev.key === 'Escape') { n.innerText = o.text; n.blur(); } if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) n.blur(); ev.stopPropagation(); });
      n.addEventListener('mousedown', ev => ev.stopPropagation());
    }
    contextMenu(e) {
      e.preventDefault();
      const p = this.pt(e); const o = this.hit(p);
      if (o && !this.sel.has(o.id)) { this.sel = new Set([o.id]); this.paint(); }
      const one = this.selected()[0];
      FM.popupMenu([
        { label: 'Cut', key: FM.keyLabel('Ctrl+X'), disabled: !this.sel.size, action: () => this.cmd('cut') },
        { label: 'Copy', key: FM.keyLabel('Ctrl+C'), disabled: !this.sel.size, action: () => this.cmd('copy') },
        { label: 'Paste', key: FM.keyLabel('Ctrl+V'), disabled: !this.app.layoutClip, action: () => this.cmd('paste', p) },
        { label: 'Duplicate', key: FM.keyLabel('Ctrl+D'), disabled: !this.sel.size, action: () => this.cmd('duplicate') },
        { label: 'Delete', key: 'Del', disabled: !this.sel.size, action: () => this.cmd('delete') },
        '-',
        { label: 'Arrange', sub: () => this.arrangeItems() },
        { label: 'Align', sub: () => this.alignItems() },
        '-',
        one && one.type === 'field' ? { label: 'Field/Control Setup…', action: () => this.fieldSetup(one) } : null,
        one && one.type === 'button' ? { label: 'Button Setup…', action: () => this.buttonSetup(one) } : null,
        one && one.type === 'portal' ? { label: 'Portal Setup…', action: () => this.portalSetup(one) } : null,
        one && (one.type === 'tab' || one.type === 'slide') ? { label: (one.type === 'tab' ? 'Tab' : 'Slide') + ' Control Setup…', action: () => this.tabSetup(one) } : null,
        one && one.type === 'chart' ? { label: 'Chart Setup…', action: () => this.chartSetup(one).then(() => this.paint()) } : null,
        one && one.type === 'webviewer' ? { label: 'Web Viewer Setup…', action: () => this.webViewerSetup(one).then(() => this.paint()) } : null,
        one ? { label: 'Conditional Formatting…', action: () => this.condFormat(one) } : null,
        one ? { label: 'Set Script Triggers…', action: () => this.objTriggers(one) } : null,
        one ? { label: 'Set Tooltip…', action: async () => { const r = await FM.dlg.calc(this.file, { formula: one.tooltip || '', to: this.lay.to, title: 'Tooltip' }); if (r) { this.snapshot(); one.tooltip = r.formula; this.paint(); } } } : null,
        one ? { label: 'Hide Object When…', action: async () => { const r = await FM.dlg.calc(this.file, { formula: one.hideWhen || '', to: this.lay.to, title: 'Hide object when' }); if (r) { this.snapshot(); one.hideWhen = r.formula; this.paint(); } } } : null,
        !one ? { label: 'Layout Setup…', action: () => this.layoutSetup() } : null,
        !one ? { label: 'Part Setup…', action: () => this.partSetup() } : null
      ], e.clientX, e.clientY);
    }
    arrangeItems() {
      return [
        { label: 'Group', key: FM.keyLabel('Ctrl+G'), disabled: this.sel.size < 2, action: () => this.cmd('group') },
        { label: 'Ungroup', key: FM.keyLabel('Ctrl+Shift+G'), disabled: !this.selected().some(o => o.type === 'group'), action: () => this.cmd('ungroup') },
        { label: 'Lock', key: FM.keyLabel('Ctrl+Alt+L'), disabled: !this.sel.size, action: () => this.cmd('lock') },
        { label: 'Unlock', disabled: !this.selected().some(o => o.locked), action: () => this.cmd('unlock') },
        '-',
        { label: 'Bring to Front', action: () => this.cmd('front') }, { label: 'Bring Forward', action: () => this.cmd('forward') },
        { label: 'Send to Back', action: () => this.cmd('back') }, { label: 'Send Backward', action: () => this.cmd('backward') },
        '-',
        { label: 'Resize to Smallest Width', disabled: this.sel.size < 2, action: () => this.cmd('size', 'minw') }, { label: 'Resize to Largest Width', disabled: this.sel.size < 2, action: () => this.cmd('size', 'maxw') },
        { label: 'Resize to Smallest Height', disabled: this.sel.size < 2, action: () => this.cmd('size', 'minh') }, { label: 'Resize to Largest Height', disabled: this.sel.size < 2, action: () => this.cmd('size', 'maxh') }
      ];
    }
    alignItems() {
      const d = this.sel.size < 2;
      return [['left', 'Left Edges'], ['hcenter', 'Centers (horizontally)'], ['right', 'Right Edges'], ['top', 'Top Edges'], ['vcenter', 'Centers (vertically)'], ['bottom', 'Bottom Edges']].map(([k, l]) => ({ label: 'Align ' + l, disabled: d, action: () => this.cmd('align', k) }))
        .concat(['-', { label: 'Distribute Horizontally', disabled: this.sel.size < 3, action: () => this.cmd('distribute', 'h') }, { label: 'Distribute Vertically', disabled: this.sel.size < 3, action: () => this.cmd('distribute', 'v') }]);
    }
    // ── commands ────────────────────────────────────────────────────────
    cmd(name, arg) {
      const objs = this.selected();
      switch (name) {
        case 'delete': if (!objs.length) return; this.snapshot(); objs.forEach(o => { const r = this.find(o.id); if (r) r.list.splice(r.list.indexOf(o), 1); }); this.sel = new Set(); break;
        case 'copy': this.app.layoutClip = FM.clone(objs); FM.toast(objs.length + ' object(s) copied'); return;
        case 'cut': this.app.layoutClip = FM.clone(objs); this.cmd('delete'); return;
        case 'paste': {
          if (!this.app.layoutClip) return; this.snapshot();
          const copies = FM.clone(this.app.layoutClip).map(reId);
          const minX = Math.min(...copies.map(o => o.x)), minY = Math.min(...copies.map(o => o.y));
          const at = arg || { x: minX + 16, y: minY + 16 };
          copies.forEach(o => { shiftDeep(o, this.snap(at.x) - minX, this.snap(at.y) - minY); this.lay.objects.push(o); });
          this.reparent(copies);
          this.sel = new Set(copies.map(o => o.id)); break;
        }
        case 'duplicate': { if (!objs.length) return; this.snapshot(); const copies = FM.clone(objs).map(reId); copies.forEach(o => { shiftDeep(o, 16, 16); const r = this.find(objs[copies.indexOf(o)].id); (r ? r.list : this.lay.objects).push(o); }); this.sel = new Set(copies.map(o => o.id)); break; }
        case 'selectall': this.sel = new Set(this.lay.objects.map(o => o.id)); break;
        case 'group': {
          if (objs.length < 2) return; this.snapshot();
          const r0 = this.find(objs[0].id); const list = r0.list;
          if (!objs.every(o => this.find(o.id).list === list)) { FM.alert('Objects in different containers cannot be grouped.'); return; }
          const x = Math.min(...objs.map(o => o.x)), y = Math.min(...objs.map(o => o.y));
          const g = { id: FM.uid('o'), type: 'group', x, y, w: Math.max(...objs.map(o => o.x + o.w)) - x, h: Math.max(...objs.map(o => o.y + o.h)) - y, children: [] };
          const at = Math.min(...objs.map(o => list.indexOf(o)));
          objs.forEach(o => { list.splice(list.indexOf(o), 1); g.children.push(o); });
          list.splice(at, 0, g); this.sel = new Set([g.id]); break;
        }
        case 'ungroup': {
          this.snapshot(); const out = [];
          objs.filter(o => o.type === 'group').forEach(g => { const r = this.find(g.id); const i = r.list.indexOf(g); r.list.splice(i, 1, ...g.children); out.push(...g.children.map(c => c.id)); });
          this.sel = new Set(out); break;
        }
        case 'lock': this.snapshot(); objs.forEach(o => { o.locked = true; }); break;
        case 'unlock': this.snapshot(); objs.forEach(o => { delete o.locked; }); break;
        case 'front': case 'back': case 'forward': case 'backward': {
          this.snapshot();
          objs.forEach(o => { const r = this.find(o.id); const l = r.list; const i = l.indexOf(o); l.splice(i, 1); const j = name === 'front' ? l.length : name === 'back' ? 0 : name === 'forward' ? Math.min(l.length, i + 1) : Math.max(0, i - 1); l.splice(j, 0, o); });
          break;
        }
        case 'align': {
          if (objs.length < 2) return; this.snapshot();
          const L = Math.min(...objs.map(o => o.x)), R = Math.max(...objs.map(o => o.x + o.w)), T = Math.min(...objs.map(o => o.y)), B = Math.max(...objs.map(o => o.y + o.h));
          objs.forEach(o => { let dx = 0, dy = 0; if (arg === 'left') dx = L - o.x; if (arg === 'right') dx = R - o.w - o.x; if (arg === 'hcenter') dx = Math.round((L + R) / 2 - o.w / 2) - o.x; if (arg === 'top') dy = T - o.y; if (arg === 'bottom') dy = B - o.h - o.y; if (arg === 'vcenter') dy = Math.round((T + B) / 2 - o.h / 2) - o.y; shiftDeep(o, dx, dy); });
          break;
        }
        case 'distribute': {
          if (objs.length < 3) return; this.snapshot();
          const k = arg === 'h' ? 'x' : 'y', s = arg === 'h' ? 'w' : 'h';
          const sorted = objs.slice().sort((a, b) => a[k] - b[k]);
          const first = sorted[0][k], last = sorted[sorted.length - 1][k] + sorted[sorted.length - 1][s];
          const total = sorted.reduce((a, o) => a + o[s], 0); const gap = (last - first - total) / (sorted.length - 1);
          let pos = first; sorted.forEach(o => { const d = Math.round(pos) - o[k]; shiftDeep(o, k === 'x' ? d : 0, k === 'y' ? d : 0); pos += o[s] + gap; });
          break;
        }
        case 'size': {
          this.snapshot();
          const v = arg === 'minw' ? Math.min(...objs.map(o => o.w)) : arg === 'maxw' ? Math.max(...objs.map(o => o.w)) : arg === 'minh' ? Math.min(...objs.map(o => o.h)) : Math.max(...objs.map(o => o.h));
          objs.forEach(o => { if (arg.endsWith('w')) o.w = v; else o.h = v; });
          break;
        }
        case 'nudge': { if (!objs.length) return; this.snapshot(); objs.forEach(o => shiftDeep(o, arg.dx, arg.dy)); break; }
        case 'undo': return this.undo();
        case 'redo': return this.redo();
      }
      this.paint();
    }
    onKey(e) {
      const t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return false;
      const c = FM.cmd(e); const k = e.key.toLowerCase();
      if ((e.key === 'Delete' || e.key === 'Backspace') && this.sel.size) { this.cmd('delete'); return true; }
      if (c && k === 'z') { if (e.shiftKey) this.redo(); else this.undo(); return true; }
      if (c && k === 'y') { this.redo(); return true; }
      if (c && k === 'c') { this.cmd('copy'); return true; }
      if (c && k === 'x') { this.cmd('cut'); return true; }
      if (c && k === 'v') { this.cmd('paste'); return true; }
      if (c && k === 'd') { this.cmd('duplicate'); return true; }
      if (c && k === 'a') { this.cmd('selectall'); return true; }
      if (c && k === 'g') { this.cmd(e.shiftKey ? 'ungroup' : 'group'); return true; }
      if (c && k === 's') { this.save(); return true; }
      if (e.key === 'Escape') { if (this.tool !== 'pointer') { this.tool = 'pointer'; this.app.renderChrome(this.win); } else { this.sel = new Set(); this.paint(); } return true; }
      const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (arrows && this.sel.size) { const s = e.shiftKey ? 10 : 1; this.cmd('nudge', { dx: arrows[0] * s, dy: arrows[1] * s }); return true; }
      return false;
    }

    // ── inspector ───────────────────────────────────────────────────────
    renderInspector() {
      const el = this.rightEl; if (!el) return; el.innerHTML = '';
      const objs = this.selected();
      const head = h('div', { class: 'fm-tabs' }, ['Position', 'Styles', 'Data'].map((n, i) => h('button', { class: 'fm-tab' + (this.inspTab === i ? ' on' : ''), text: n, onclick: () => { this.inspTab = i; this.renderInspector(); } })));
      el.appendChild(head);
      const body = h('div', { class: 'fm-insp' });
      el.appendChild(body);
      if (!objs.length) { this.layoutInspector(body); return; }
      const o = objs[0];
      const multi = objs.length > 1;
      const change = fn => { this.snapshot(); objs.forEach(fn); this.renderCanvas(); };
      const num = (lbl, key) => { const i = h('input', { class: 'fm-input', type: 'number', value: Math.round(o[key] * 10) / 10 }); i.addEventListener('change', () => { const v = +i.value || 0; change(x => { if (key === 'x' || key === 'y') shiftDeep(x, key === 'x' ? v - x.x : 0, key === 'y' ? v - x.y : 0); else x[key] = Math.max(1, v); }); this.renderInspector(); }); return h('label', { class: 'fm-insp-num' }, h('span', { text: lbl }), i); };
      if (this.inspTab === 0) {
        body.appendChild(h('div', { class: 'fm-insp-title', text: multi ? objs.length + ' objects' : describe(this.file, o, this.lay.to) }));
        if (!multi) { const nm = h('input', { class: 'fm-input', value: o.name || '', placeholder: 'Object name' }); nm.addEventListener('change', () => { change(x => { x.name = nm.value.trim() || undefined; }); }); body.appendChild(FM.row('Name', nm)); }
        body.appendChild(h('div', { class: 'fm-insp-grid' }, num('Left', 'x'), num('Top', 'y'), num('Width', 'w'), num('Height', 'h')));
        const calcRow = (lbl, key) => { const v = o[key] || ''; const b = h('button', { class: 'fm-btn small', text: v ? 'Edit…' : 'Specify…' }); b.onclick = async () => { const r = await FM.dlg.calc(this.file, { formula: o[key] || '', to: this.lay.to, title: lbl }); if (r) { change(x => { x[key] = r.formula || undefined; }); this.renderInspector(); } }; return h('div', { class: 'fm-row' }, h('span', { class: 'fm-row-l', text: lbl }), h('span', { class: 'fm-row-c' }, b, v ? h('span', { class: 'fm-mono small fm-muted', text: ' ' + String(v).slice(0, 40) }) : null)); };
        body.append(calcRow('Tooltip', 'tooltip'), calcRow('Hide object when', 'hideWhen'));
        if (o.hideWhen) { const hf = FM.check('Apply in Find mode', o.hideFind !== false); hf.input.onchange = () => change(x => { x.hideFind = hf.input.checked; }); body.appendChild(hf); }
        const lk = FM.check('Lock', !!o.locked); lk.input.onchange = () => { change(x => { if (lk.input.checked) x.locked = true; else delete x.locked; }); };
        body.appendChild(lk);
        body.appendChild(h('div', { class: 'fm-inline' }, h('button', { class: 'fm-btn small', text: 'Conditional…', onclick: () => this.condFormat(o) }), h('button', { class: 'fm-btn small', text: 'Script Triggers…', onclick: () => this.objTriggers(o) })));
        if (o.type === 'field' || o.type === 'button') { const ti = h('input', { class: 'fm-input', type: 'number', min: 1, value: o.tabOrder || '', placeholder: 'auto' }); ti.onchange = () => change(x => { x.tabOrder = ti.value ? +ti.value : undefined; }); body.appendChild(FM.row('Tab order', ti)); }
      } else if (this.inspTab === 1) {
        const st = o.style || {};
        const setStyle = (k, v) => change(x => { x.style = Object.assign({}, x.style || {}); if (v === '' || v == null || v === false) delete x.style[k]; else x.style[k] = v; });
        const color = (lbl, k) => { const i = h('input', { type: 'color', value: /^#[0-9a-f]{6}$/i.test(st[k] || '') ? st[k] : (k === 'color' ? '#1d2733' : '#ffffff') }); const none = h('button', { class: 'fm-btn small', text: st[k] === 'transparent' || st[k] == null ? (st[k] == null ? 'Default' : 'None') : 'None', onclick: () => { setStyle(k, st[k] === 'transparent' ? '' : 'transparent'); this.renderInspector(); } }); i.addEventListener('input', () => setStyle(k, i.value)); return h('div', { class: 'fm-row' }, h('span', { class: 'fm-row-l', text: lbl }), h('span', { class: 'fm-row-c' }, i, none)); };
        body.appendChild(h('div', { class: 'fm-insp-title', text: 'Graphic' }));
        if (o.type !== 'line' && o.type !== 'text') body.appendChild(color('Fill', 'fill'));
        body.appendChild(color('Line', 'line'));
        const lw = h('input', { class: 'fm-input', type: 'number', min: 0, max: 20, value: st.lineWidth == null ? '' : st.lineWidth, placeholder: 'default' }); lw.onchange = () => setStyle('lineWidth', lw.value === '' ? '' : +lw.value);
        const ls = FM.select([['', 'Default'], ['solid', 'Solid'], ['dashed', 'Dashed'], ['dotted', 'Dotted']].map(([v, l]) => ({ value: v, label: l })), st.lineStyle || ''); ls.onchange = () => setStyle('lineStyle', ls.value);
        const rad = h('input', { class: 'fm-input', type: 'number', min: 0, max: 100, value: st.radius == null ? '' : st.radius, placeholder: 'default' }); rad.onchange = () => setStyle('radius', rad.value === '' ? '' : +rad.value);
        const pad = h('input', { class: 'fm-input', type: 'number', min: 0, max: 40, value: st.padding == null ? '' : st.padding, placeholder: 'default' }); pad.onchange = () => setStyle('padding', pad.value === '' ? '' : +pad.value);
        const sh = FM.check('Shadow', !!st.shadow); sh.input.onchange = () => setStyle('shadow', sh.input.checked);
        const op = h('input', { type: 'range', min: 0.1, max: 1, step: 0.05, value: st.opacity == null ? 1 : st.opacity }); op.onchange = () => setStyle('opacity', +op.value === 1 ? '' : +op.value);
        body.append(FM.row('Line width', lw), FM.row('Line style', ls), FM.row('Corner radius', rad), FM.row('Padding', pad), sh, FM.row('Opacity', op));
        if (o.type !== 'line' && o.type !== 'rect' && o.type !== 'oval' && o.type !== 'roundrect' && o.type !== 'image') {
          body.appendChild(h('div', { class: 'fm-insp-title', text: 'Text' }));
          const font = FM.select([['', 'Theme default'], ['Inter, system-ui, sans-serif', 'Sans-serif'], ['Georgia, serif', 'Serif'], ['ui-monospace, Menlo, Consolas, monospace', 'Monospace'], ['Arial, Helvetica, sans-serif', 'Arial'], ['"Times New Roman", serif', 'Times New Roman'], ['Verdana, sans-serif', 'Verdana'], ['"Trebuchet MS", sans-serif', 'Trebuchet MS']].map(([v, l]) => ({ value: v, label: l })), st.font || ''); font.onchange = () => setStyle('font', font.value);
          const size = h('input', { class: 'fm-input', type: 'number', min: 6, max: 96, value: st.size || '', placeholder: '13' }); size.onchange = () => setStyle('size', size.value ? +size.value : '');
          const tog = (k, icon) => h('button', { class: 'fm-iconbtn' + (st[k] ? ' on' : ''), html: FM.icon(icon, 15), onclick: () => { setStyle(k, !st[k]); this.renderInspector(); } });
          const al = v => h('button', { class: 'fm-iconbtn' + ((st.align || 'left') === v ? ' on' : ''), html: FM.icon('align' + v, 15), onclick: () => { setStyle('align', v); this.renderInspector(); } });
          const va = FM.select([['', 'Top'], ['middle', 'Middle'], ['bottom', 'Bottom']].map(([v, l]) => ({ value: v, label: l })), st.valign || ''); va.onchange = () => setStyle('valign', va.value);
          body.append(FM.row('Font', font), FM.row('Size', size), color('Text color', 'color'), h('div', { class: 'fm-inline' }, tog('bold', 'bold'), tog('italic', 'italic'), tog('underline', 'underline'), h('span', { class: 'fm-sep' }), al('left'), al('center'), al('right')), FM.row('Vertical', va));
        }
      } else {
        this.dataInspector(body, o, multi, change);
      }
    }
    dataInspector(body, o, multi, change) {
      const file = this.file;
      if (o.type === 'field') {
        const f = file.fieldByKey(o.field);
        body.appendChild(h('div', { class: 'fm-insp-title', text: 'Field' }));
        body.appendChild(h('button', { class: 'fm-btn small fm-fieldbtn', text: f ? file.keyLabel(o.field, this.lay.to) : '<Field Missing>', onclick: async () => { const k = await FM.dlg.pickField(file, { to: this.lay.to, current: o.field }); if (k) { change(x => { if (x.type === 'field') x.field = k; }); this.renderInspector(); } } }));
        const ctl = FM.select([['edit', 'Edit Box'], ['dropdown', 'Drop-down List'], ['popup', 'Pop-up Menu'], ['checkbox', 'Checkbox Set'], ['radio', 'Radio Button Set'], ['calendar', 'Drop-down Calendar'], ['concealed', 'Concealed Edit Box']].map(([v, l]) => ({ value: v, label: l })), o.control || 'edit');
        ctl.onchange = () => { change(x => { x.control = ctl.value; if (['dropdown', 'popup', 'checkbox', 'radio'].includes(ctl.value) && !x.valueList && file.schema.valueLists[0]) x.valueList = file.schema.valueLists[0].id; }); this.renderInspector(); };
        const vl = FM.select([{ value: '', label: '<None>' }].concat(file.schema.valueLists.map(v => ({ value: v.id, label: v.name }))), o.valueList || '');
        vl.onchange = () => change(x => { x.valueList = vl.value || undefined; });
        body.append(FM.row('Control style', ctl), FM.row('Values from', vl), h('button', { class: 'fm-btn small', text: 'Manage Value Lists…', onclick: async () => { await FM.dlg.manageValueLists(file); this.renderInspector(); } }));
        if (f && file.reps(f) > 1) { const reps = h('input', { class: 'fm-input', type: 'number', min: 1, max: file.reps(f), value: o.reps || 1 }); reps.onchange = () => change(x => { x.reps = Math.max(1, +reps.value || 1); }); const orient = FM.select([{ value: 'v', label: 'Vertical' }, { value: 'h', label: 'Horizontal' }], o.repOrient || 'v'); orient.onchange = () => change(x => { x.repOrient = orient.value; }); body.append(FM.row('Show repetitions', reps), FM.row('Orientation', orient)); }
        const ph = h('input', { class: 'fm-input', value: o.placeholder || '', placeholder: 'Placeholder text' }); ph.onchange = () => change(x => { x.placeholder = ph.value || undefined; });
        body.append(FM.row('Placeholder', ph));
        body.appendChild(h('div', { class: 'fm-insp-title', text: 'Behavior' }));
        const chk = (lbl, key, def) => { const c = FM.check(lbl, o[key] == null ? def : o[key]); c.input.onchange = () => change(x => { x[key] = c.input.checked; }); return c; };
        body.append(chk('Field entry in Browse mode', 'entryBrowse', true), chk('Field entry in Find mode', 'entryFind', true), chk('Select entire contents on entry', 'selectAll', false), chk('Go to next object using Return', 'nextOnReturn', false), chk('Include field for Quick Find', 'quickFind', true));
        if (f && f.type === 'container') { body.append(chk('Interactive PDF', 'pdfInteractive', false)); const fit = FM.select([{ value: 'contain', label: 'Reduce or enlarge to fit' }, { value: 'cover', label: 'Crop to frame' }], o.fit || 'contain'); fit.onchange = () => change(x => { x.fit = fit.value; }); body.append(FM.row('Graphic format', fit)); }
        // data formatting
        const rt = f ? (f.type === 'calculation' ? ((f.options || {}).calc || {}).resultType || 'text' : f.type === 'summary' ? 'number' : f.type) : 'text';
        const fmt = o.format || {};
        body.appendChild(h('div', { class: 'fm-insp-title', text: 'Data Formatting' }));
        if (rt === 'number') {
          const n = fmt.number || {};
          const kind = FM.select([['general', 'General'], ['decimal', 'Decimal'], ['currency', 'Currency'], ['percent', 'Percent'], ['boolean', 'Boolean']].map(([v, l]) => ({ value: v, label: l })), n.kind || 'general');
          const dec = h('input', { class: 'fm-input', type: 'number', min: 0, max: 10, value: n.decimals == null ? 2 : n.decimals });
          const th = FM.check('Use thousands separator', n.thousands !== false && (n.kind === 'currency' || n.thousands));
          const sym = h('input', { class: 'fm-input', value: n.symbol == null ? '$' : n.symbol, style: { width: '50px' } });
          const neg = FM.check('Negative in parentheses', !!n.negParen);
          const yes = h('input', { class: 'fm-input', value: n.yes || 'Yes', style: { width: '70px' } }), no = h('input', { class: 'fm-input', value: n.no || 'No', style: { width: '70px' } });
          const save = () => change(x => { x.format = Object.assign({}, x.format || {}); x.format.number = kind.value === 'general' ? undefined : { kind: kind.value, decimals: +dec.value, thousands: th.input.checked, symbol: sym.value, negParen: neg.input.checked, yes: yes.value, no: no.value }; });
          [kind, dec, th.input, sym, neg.input, yes, no].forEach(x => x.addEventListener('change', save));
          body.append(FM.row('Format', kind), FM.row('Decimal digits', dec), th, FM.row('Currency symbol', sym), neg, h('div', { class: 'fm-inline' }, 'Boolean: ', yes, no));
        }
        if (rt === 'date' || rt === 'timestamp') { const d = FM.select([['', '1/5/2025'], ['mdyz', '01/05/2025'], ['mdy2', '01/05/25'], ['iso', '2025-01-05'], ['dmy', '5/1/2025'], ['abbr', 'Jan 5, 2025'], ['long', 'January 5, 2025'], ['full', 'Sunday, January 5, 2025']].map(([v, l]) => ({ value: v, label: l })), fmt.date || ''); d.onchange = () => change(x => { x.format = Object.assign({}, x.format || {}, { date: d.value || undefined }); }); body.append(FM.row('Date', d)); }
        if (rt === 'time' || rt === 'timestamp') { const t = FM.select([['', '1:05:30 PM'], ['hm', '1:05 PM'], ['24h', '13:05:30'], ['24hm', '13:05'], ['dur', '37:05:30 (duration)']].map(([v, l]) => ({ value: v, label: l })), fmt.time || ''); t.onchange = () => change(x => { x.format = Object.assign({}, x.format || {}, { time: t.value || undefined }); }); body.append(FM.row('Time', t)); }
        if (rt === 'text' || rt === 'container') body.appendChild(h('div', { class: 'fm-muted small', text: 'Text is shown as entered.' }));
        return;
      }
      if (o.type === 'text') {
        const ta = h('textarea', { class: 'fm-input', rows: 4 }); ta.value = o.text || '';
        ta.onchange = () => change(x => { if (x.type === 'text') x.text = ta.value; });
        const mf = h('button', { class: 'fm-btn small', text: 'Insert Merge Field…', onclick: async () => { const k = await FM.dlg.pickField(file, { to: this.lay.to }); if (k) { ta.setRangeText('<<' + file.keyLabel(k, this.lay.to) + '>>', ta.selectionStart, ta.selectionEnd, 'end'); ta.dispatchEvent(new Event('change')); } } });
        const sym = FM.select([{ value: '', label: 'Insert symbol…' }, { value: '{{PageNumber}}', label: 'Page Number' }, { value: '{{PageCount}}', label: 'Page Count' }, { value: '{{RecordNumber}}', label: 'Record Number' }, { value: '{{CurrentDate}}', label: 'Current Date' }, { value: '{{CurrentTime}}', label: 'Current Time' }, { value: '{{UserName}}', label: 'User Name' }, { value: '{{LayoutName}}', label: 'Layout Name' }, { value: '{{FoundCount}}', label: 'Found Count' }, { value: '{{FileName}}', label: 'File Name' }], '');
        sym.onchange = () => { if (sym.value) { ta.setRangeText(sym.value, ta.selectionStart, ta.selectionEnd, 'end'); ta.dispatchEvent(new Event('change')); } sym.value = ''; };
        body.append(h('div', { class: 'fm-insp-title', text: 'Text' }), ta, mf, sym, h('div', { class: 'fm-muted small', text: 'Use <<Field Name>> for merge fields and <<$variable>> for variables.' }));
        return;
      }
      const btn = (lbl, fn) => body.appendChild(h('button', { class: 'fm-btn', text: lbl, onclick: fn }));
      if (o.type === 'button') { const lb = h('input', { class: 'fm-input', value: o.label || '' }); lb.onchange = () => change(x => { x.label = lb.value; }); body.append(FM.row('Label', lb)); btn('Button Setup…', () => this.buttonSetup(o)); }
      if (o.type === 'buttonbar') btn('Button Bar Setup…', () => this.buttonBarSetup(o));
      if (o.type === 'popover') { const lb = h('input', { class: 'fm-input', value: o.label || '' }); lb.onchange = () => change(x => { x.label = lb.value; }); const tt = h('input', { class: 'fm-input', value: (o.panel || {}).title || '' }); tt.onchange = () => change(x => { x.panel = Object.assign({}, x.panel, { title: tt.value }); }); body.append(FM.row('Label', lb), FM.row('Popover title', tt)); btn(this.popOpen[o.id] ? 'Close Popover' : 'Open Popover', () => { this.popOpen[o.id] = !this.popOpen[o.id]; this.paint(); }); }
      if (o.type === 'portal') btn('Portal Setup…', () => this.portalSetup(o));
      if (o.type === 'tab' || o.type === 'slide') btn((o.type === 'tab' ? 'Tab' : 'Slide') + ' Control Setup…', () => this.tabSetup(o));
      if (o.type === 'chart') btn('Chart Setup…', () => this.chartSetup(o).then(() => this.paint()));
      if (o.type === 'webviewer') btn('Web Viewer Setup…', () => this.webViewerSetup(o).then(() => this.paint()));
      if (o.type === 'image') { btn('Replace Image…', async () => { const f = await FM.pickFile('image/*'); if (f) { const src = await FM.readDataURL(f); change(x => { x.src = src; }); } }); const fit = FM.select([{ value: 'contain', label: 'Fit' }, { value: 'cover', label: 'Crop' }, { value: 'fill', label: 'Stretch' }], o.fit || 'contain'); fit.onchange = () => change(x => { x.fit = fit.value; }); body.append(FM.row('Scale', fit)); }
      if (!body.children.length) body.appendChild(h('div', { class: 'fm-muted small', text: 'This object has no data settings.' }));
    }
    layoutInspector(body) {
      const lay = this.lay; const file = this.file;
      body.appendChild(h('div', { class: 'fm-insp-title', text: 'Layout' }));
      const nm = h('input', { class: 'fm-input', value: lay.name }); nm.onchange = () => { this.snapshot(); lay.name = nm.value.trim() || lay.name; this.app.renderChrome(this.win); };
      const th = FM.select(THEMES.map(([v, l]) => ({ value: v, label: l })), lay.theme || 'apex'); th.onchange = () => { this.snapshot(); lay.theme = th.value; this.paint(); };
      const w = h('input', { class: 'fm-input', type: 'number', min: 100, max: 4000, value: lay.width || 800 }); w.onchange = () => { this.snapshot(); lay.width = Math.max(100, +w.value || 800); this.paint(); };
      body.append(FM.row('Name', nm), FM.row('Table', h('span', { text: (file.to(lay.to) || {}).name || '?' })), FM.row('Theme', th), FM.row('Width', w));
      body.append(h('div', { class: 'fm-inline' }, h('button', { class: 'fm-btn small', text: 'Layout Setup…', onclick: () => this.layoutSetup() }), h('button', { class: 'fm-btn small', text: 'Part Setup…', onclick: () => this.partSetup() })),
        h('div', { class: 'fm-inline' }, h('button', { class: 'fm-btn small', text: 'Script Triggers…', onclick: () => this.layoutTriggers() }), h('button', { class: 'fm-btn small', text: 'Tab Order…', onclick: () => this.tabOrder() })));
      body.appendChild(h('div', { class: 'fm-insp-title', text: 'Grid' }));
      const showGrid = FM.check('Show grid', this.app.prefs.showGrid !== false); showGrid.input.onchange = () => { this.app.prefs.showGrid = showGrid.input.checked; this.app.savePrefs(); this.paint(); };
      const snap = FM.check('Snap to grid', this.app.prefs.snap !== false); snap.input.onchange = () => { this.app.prefs.snap = snap.input.checked; this.app.savePrefs(); };
      const zoom = FM.select([['0.5', '50%'], ['0.75', '75%'], ['1', '100%'], ['1.25', '125%'], ['1.5', '150%'], ['2', '200%']].map(([v, l]) => ({ value: v, label: l })), String(this.zoom)); zoom.onchange = () => { this.zoom = +zoom.value; this.paint(); };
      body.append(showGrid, snap, FM.row('Zoom', zoom));
      body.appendChild(h('div', { class: 'fm-muted small', text: 'Tip: draw with the tools in the toolbar, drag fields from the left, double-click an object to set it up, right-click for Arrange and Align.' }));
    }

    // ── setup dialogs ───────────────────────────────────────────────────
    async fieldSetup(o) {
      const file = this.file;
      const k = await FM.dlg.pickField(file, { to: this.lay.to, current: o.field, title: 'Specify Field' });
      if (!k) return;
      this.snapshot(); o.field = k; this.paint();
    }
    async buttonSetup(o, seg) {
      const file = this.file; const target = seg || o;
      const a = FM.clone(target.action || { kind: 'none' });
      const label = h('input', { class: 'fm-input', value: target.label || '' });
      const icon = FM.select([{ value: '', label: '(no icon)' }].concat(FM.iconNames.map(n => ({ value: n, label: n }))), target.icon || '');
      const prev = h('span', { html: target.icon ? FM.icon(target.icon, 20) : '' });
      icon.onchange = () => { prev.innerHTML = icon.value ? FM.icon(icon.value, 20) : ''; };
      const kind = FM.select([{ value: 'none', label: 'Do Nothing' }, { value: 'step', label: 'Single Step' }, { value: 'script', label: 'Perform Script' }], a.kind || 'none');
      const area = h('div', { class: 'fm-form' });
      const step = a.step || { s: 'Go to Record/Request/Page', p: { which: 'next' } };
      const draw = () => {
        area.innerHTML = '';
        if (kind.value === 'step') {
          const s = FM.select(FM.STEP_ORDER.filter(n => !FM.STEPS[n].block && !FM.STEPS[n].hidden && n !== '#').map(n => ({ value: n, label: n + (FM.STEPS[n].planned ? ' (planned)' : '') })), step.s);
          s.onchange = () => { step.s = s.value; step.p = {}; FM.STEPS[s.value].params.forEach(pp => { if (pp.def != null) step.p[pp.key] = pp.def; }); draw(); };
          area.appendChild(FM.row('Step', s));
          FM.STEPS[step.s].params.forEach(pp => area.appendChild(FM.paramEditor(file, pp, step.p, () => { }, false, { to: this.lay.to })));
        } else if (kind.value === 'script') {
          const scripts = FM.orderedScripts(file).filter(x => !x.folder && !x.separator);
          const s = FM.select([{ value: '', label: '—' }].concat(scripts.map(x => ({ value: x.id, label: x.name }))), a.script || '');
          const p = h('input', { class: 'fm-input fm-mono', value: a.param || '', placeholder: 'Optional script parameter (calculation)' });
          const pb = h('button', { class: 'fm-btn small', text: 'Specify…', onclick: async () => { const r = await FM.dlg.calc(file, { formula: p.value, to: this.lay.to, title: 'Optional Script Parameter' }); if (r) p.value = r.formula; } });
          const cur = FM.select([{ value: 'pause', label: 'Pause' }, { value: 'resume', label: 'Resume' }, { value: 'exit', label: 'Exit' }, { value: 'halt', label: 'Halt' }], a.current || 'pause');
          s.onchange = () => { a.script = s.value; }; p.oninput = () => { a.param = p.value; }; cur.onchange = () => { a.current = cur.value; };
          a.script = s.value; a.param = p.value; a.current = cur.value;
          area.append(FM.row('Script', s), FM.row('Parameter', p, pb), FM.row('Current script', cur), h('button', { class: 'fm-btn small', text: 'Open Script Workspace…', onclick: () => FM.workspace.open(file, s.value || undefined) }));
        }
      };
      kind.onchange = draw; draw();
      const body = h('div', { class: 'fm-form' }, FM.row('Label', label), FM.row('Icon', icon, prev), FM.row('Action', kind), area);
      const ok = await FM.modal({ title: 'Button Setup', body, width: 620, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
      if (!ok) return;
      this.snapshot();
      target.label = label.value; target.icon = icon.value || undefined;
      target.action = kind.value === 'step' ? { kind: 'step', step: { id: FM.uid('t'), s: step.s, p: step.p } } : kind.value === 'script' ? { kind: 'script', script: a.script, param: a.param, current: a.current } : { kind: 'none' };
      this.paint();
    }
    async buttonBarSetup(o) {
      const segs = FM.clone(o.segments || []);
      const list = h('div', { class: 'fm-col' });
      const draw = () => {
        list.innerHTML = '';
        segs.forEach((s, i) => list.appendChild(h('div', { class: 'fm-inline' }, h('span', { text: (i + 1) + '.' }), (() => { const inp = h('input', { class: 'fm-input', value: s.label || '' }); inp.oninput = () => { s.label = inp.value; }; return inp; })(),
          h('button', { class: 'fm-btn small', text: 'Action…', onclick: async () => { const tmp = { label: s.label, icon: s.icon, action: s.action }; const self = this; const fake = Object.create(self); fake.snapshot = () => { }; fake.paint = () => { }; await self.buttonSetup.call(fake, tmp); Object.assign(s, tmp); draw(); } }),
          (() => { const a = h('input', { class: 'fm-input fm-mono', value: s.active || '', placeholder: 'Active when (calc)', style: { width: '160px' } }); a.oninput = () => { s.active = a.value || undefined; }; return a; })(),
          h('button', { class: 'fm-iconbtn', html: FM.icon('x', 12), onclick: () => { segs.splice(i, 1); draw(); } }))));
      };
      draw();
      const body = h('div', { class: 'fm-form' }, list, h('button', { class: 'fm-btn small', text: 'Add Segment', onclick: () => { segs.push({ label: 'Segment', action: { kind: 'none' } }); draw(); } }));
      const ok = await FM.modal({ title: 'Button Bar Setup', body, width: 640, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
      if (ok) { this.snapshot(); o.segments = segs; this.paint(); }
    }
    async portalSetup(o, isNew) {
      const file = this.file;
      const rel = file.schema.tableOccurrences.filter(x => x.id !== this.lay.to && file.path(this.lay.to, x.id));
      const to = FM.select(rel.map(x => ({ value: x.id, label: x.name })), o.to);
      let sort = o.sort || [];
      const sortOn = FM.check('Sort portal records', sort.length > 0);
      const sortBtn = h('button', { class: 'fm-btn small', text: 'Specify…', onclick: async () => { const r = await FM.dlg.sortDialog(null, sort, { file, to: to.value, store: true }); if (r) { sort = r; sortOn.input.checked = r.length > 0; } } });
      let filter = o.filter || '';
      const filtOn = FM.check('Filter portal records', !!filter);
      const filtBtn = h('button', { class: 'fm-btn small', text: 'Specify…', onclick: async () => { const r = await FM.dlg.calc(file, { formula: filter, to: this.lay.to, title: 'Portal filter (true keeps a row)' }); if (r) { filter = r.formula; filtOn.input.checked = !!filter; } } });
      const del = FM.check('Allow deletion of portal records', o.allowDelete !== false);
      const scroll = FM.check('Use vertical scroll bar', o.scroll !== false);
      const rows = h('input', { class: 'fm-input', type: 'number', min: 1, max: 100, value: o.rows || 4 });
      const init = h('input', { class: 'fm-input', type: 'number', min: 1, value: o.initialRow || 1 });
      const alt = FM.check('Use alternate row state', !!o.alt);
      let keys = null;
      const pickFields = isNew ? h('div', { class: 'fm-col' }) : null;
      if (isNew) {
        const fl = h('select', { class: 'fm-input fm-list', size: 8, multiple: true });
        const fill = () => { fl.innerHTML = ''; const t = file.tableOfTO(to.value); (t ? t.fields : []).forEach(f => fl.appendChild(h('option', { value: FM.fkey(to.value, f.id), text: f.name }))); };
        to.addEventListener('change', fill); fill();
        pickFields.append(h('div', { class: 'fm-muted small', text: 'Fields to show in the portal (Ctrl/⌘-click for several):' }), fl);
        keys = () => [...fl.selectedOptions].map(op => op.value);
      }
      const body = h('div', { class: 'fm-form' }, FM.row('Show related records from', to), h('div', { class: 'fm-inline' }, sortOn, sortBtn), h('div', { class: 'fm-inline' }, filtOn, filtBtn), del, scroll, FM.row('Initial row', init), FM.row('Number of rows', rows), alt, pickFields);
      const ok = await FM.modal({ title: 'Portal Setup', body, width: 520, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
      if (!ok) { if (isNew) { const r = this.find(o.id); if (r) r.list.splice(r.list.indexOf(o), 1); this.sel = new Set(); this.paint(); } return null; }
      if (!isNew) this.snapshot();
      const oldRows = o.rows || 4;
      Object.assign(o, { to: to.value, sort: sortOn.input.checked ? sort : [], filter: filtOn.input.checked ? filter : '', allowDelete: del.input.checked, scroll: scroll.input.checked, rows: Math.max(1, +rows.value || 4), initialRow: Math.max(1, +init.value || 1), alt: alt.input.checked });
      if (!isNew && o.rows !== oldRows) o.h = Math.round(o.h / oldRows * o.rows);
      this.paint();
      return { keys: keys ? keys() : null };
    }
    async tabSetup(o) {
      const tabs = FM.clone(o.tabs || []);
      const list = h('select', { class: 'fm-input fm-list', size: 8 });
      const name = h('input', { class: 'fm-input' });
      const draw = sel => { list.innerHTML = ''; tabs.forEach((t, i) => list.appendChild(h('option', { value: i, text: t.label || '(no name)' }))); if (sel != null) list.selectedIndex = sel; };
      draw(0);
      list.onchange = () => { const t = tabs[list.selectedIndex]; name.value = t ? t.label || '' : ''; };
      list.onchange();
      const def = FM.select(tabs.map((t, i) => ({ value: i, label: t.label })), o.defaultTab || 0);
      const just = FM.select([['left', 'Left'], ['center', 'Center'], ['right', 'Right'], ['full', 'Full']].map(([v, l]) => ({ value: v, label: l })), o.justify || 'left');
      const dots = FM.check('Show navigation dots', o.dots !== false);
      const body = h('div', { class: 'fm-form' },
        h('div', { class: 'fm-two' }, list, h('div', { class: 'fm-col' }, FM.row(o.type === 'tab' ? 'Tab name' : 'Panel name', name),
          h('button', { class: 'fm-btn small', text: 'Create', onclick: () => { tabs.push({ id: FM.uid('b'), label: name.value || (o.type === 'tab' ? 'Tab ' : 'Panel ') + (tabs.length + 1), children: [] }); draw(tabs.length - 1); } }),
          h('button', { class: 'fm-btn small', text: 'Rename', onclick: () => { const i = list.selectedIndex; if (i >= 0) { tabs[i].label = name.value; draw(i); } } }),
          h('button', { class: 'fm-btn small', text: 'Delete', onclick: async () => { const i = list.selectedIndex; if (i < 0 || tabs.length < 2) return; if ((tabs[i].children || []).length && !(await FM.confirm('Delete the panel and the ' + tabs[i].children.length + ' object(s) on it?', { ok: 'Delete' }))) return; tabs.splice(i, 1); draw(0); } }),
          h('button', { class: 'fm-btn small', text: '↑', onclick: () => { const i = list.selectedIndex; if (i > 0) { [tabs[i - 1], tabs[i]] = [tabs[i], tabs[i - 1]]; draw(i - 1); } } }),
          h('button', { class: 'fm-btn small', text: '↓', onclick: () => { const i = list.selectedIndex; if (i >= 0 && i < tabs.length - 1) { [tabs[i + 1], tabs[i]] = [tabs[i], tabs[i + 1]]; draw(i + 1); } } }))),
        FM.row('Default front panel', def), o.type === 'tab' ? FM.row('Tab justification', just) : dots);
      const ok = await FM.modal({ title: (o.type === 'tab' ? 'Tab' : 'Slide') + ' Control Setup', body, width: 520, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
      if (!ok) return;
      this.snapshot();
      o.tabs = tabs; o.defaultTab = +def.value || 0; o.justify = just.value; o.dots = dots.input.checked;
      this.paint();
    }
    async chartSetup(o) {
      const file = this.file; const c = FM.clone(o.chart || {});
      const type = FM.select([['column', 'Column'], ['bar', 'Bar'], ['line', 'Line'], ['area', 'Area'], ['pie', 'Pie'], ['donut', 'Donut'], ['scatter', 'Scatter']].map(([v, l]) => ({ value: v, label: l })), c.type || 'column');
      const title = h('input', { class: 'fm-input', value: c.title || '' });
      const src = FM.select([['found', 'Current found set'], ['related', 'Related records'], ['record', 'Current record (delimited data)']].map(([v, l]) => ({ value: v, label: l })), c.source || 'found');
      const rel = FM.select(file.schema.tableOccurrences.filter(x => x.id !== this.lay.to && file.path(this.lay.to, x.id)).map(x => ({ value: x.id, label: x.name })), c.relTO || '');
      const calcInput = (v, ph) => { const i = h('input', { class: 'fm-input fm-mono', value: v || '', placeholder: ph }); const b = h('button', { class: 'fm-btn small', text: '…', onclick: async () => { const r = await FM.dlg.calc(file, { formula: i.value, to: src.value === 'related' ? rel.value : this.lay.to }); if (r) i.value = r.formula; } }); return { i, row: h('span', { class: 'fm-inline' }, i, b) }; };
      const x = calcInput(c.x, 'X-axis labels, e.g. Category');
      const group = FM.check('Group by the X-axis label and total each series (summarize)', !!c.group);
      const stacked = FM.check('Stacked', !!c.stacked);
      const legend = FM.check('Show legend', c.legend !== false);
      const series = (c.series && c.series.length ? c.series : [{ name: 'Series 1', calc: '' }]).map(s => ({ name: s.name, calc: s.calc, color: s.color }));
      const slist = h('div', { class: 'fm-col' });
      const drawS = () => { slist.innerHTML = ''; series.forEach((s, i) => { const n = h('input', { class: 'fm-input', value: s.name, style: { width: '120px' } }); n.oninput = () => { s.name = n.value; }; const ci = calcInput(s.calc, 'Y value, e.g. Amount'); ci.i.oninput = () => { s.calc = ci.i.value; }; ci.i.onchange = ci.i.oninput; const col = h('input', { type: 'color', value: s.color || ['#2a6fdb', '#e8833a', '#2fa36b', '#c94f7c'][i % 4] }); col.oninput = () => { s.color = col.value; }; slist.appendChild(h('div', { class: 'fm-inline' }, n, ci.row, col, h('button', { class: 'fm-iconbtn', html: FM.icon('x', 12), onclick: () => { series.splice(i, 1); drawS(); } }))); }); };
      drawS();
      const body = h('div', { class: 'fm-form' }, FM.row('Chart type', type), FM.row('Title', title), FM.row('Data source', src), FM.row('Related table', rel), FM.row('X-axis', x.row), group, h('b', { text: 'Y-axis series' }), slist, h('button', { class: 'fm-btn small', text: 'Add Series', onclick: () => { series.push({ name: 'Series ' + (series.length + 1), calc: '' }); drawS(); } }), stacked, legend,
        h('div', { class: 'fm-muted small', text: 'For "Current record", X-axis and series are calculations returning one value per line (for example List ( Items::Name )).' }));
      const ok = await FM.modal({ title: 'Chart Setup', body, width: 680, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
      if (!ok) return;
      this.snapshot();
      o.chart = { type: type.value, title: title.value, source: src.value, relTO: src.value === 'related' ? rel.value : undefined, x: x.i.value, group: group.input.checked, stacked: stacked.input.checked, legend: legend.input.checked, series: series.filter(s => s.calc) };
    }
    async webViewerSetup(o) {
      const file = this.file;
      const url = h('textarea', { class: 'fm-input fm-mono', rows: 4 }); url.value = o.url || '';
      const tpl = FM.select([{ value: '', label: 'Choose a website…' }, { value: 'map', label: 'Google Maps (address)' }, { value: 'search', label: 'Web search' }, { value: 'html', label: 'Custom HTML (data:text/html)' }, { value: 'wiki', label: 'Wikipedia' }], '');
      tpl.onchange = () => {
        const t = { map: '"https://www.google.com/maps?output=embed&q=" & GetAsURLEncoded ( "Address" )', search: '"https://duckduckgo.com/?q=" & GetAsURLEncoded ( "search text" )', html: '"data:text/html," & "<html><body style=\'font-family:sans-serif\'><h3>Hello</h3><button onclick=\\"FileMaker.PerformScript ( \'Script Name\' ; \'param\' )\\">Run script</button></body></html>"', wiki: '"https://en.m.wikipedia.org/wiki/" & GetAsURLEncoded ( "FileMaker" )' }[tpl.value];
        if (t) url.value = t; tpl.value = '';
      };
      const interact = FM.check('Allow interaction with web viewer content', o.interact !== false);
      const body = h('div', { class: 'fm-form' }, tpl, h('div', { class: 'fm-muted small', text: 'Web address (calculation):' }), url, h('button', { class: 'fm-btn small', text: 'Specify…', onclick: async () => { const r = await FM.dlg.calc(file, { formula: url.value, to: this.lay.to, title: 'Web Address' }); if (r) url.value = r.formula; } }), interact,
        h('div', { class: 'fm-muted small', text: 'Pages are shown in a sandbox. Some sites refuse to be framed. In custom HTML, FileMaker.PerformScript(name, parameter) runs a script in this file.' }));
      const ok = await FM.modal({ title: 'Web Viewer Setup', body, width: 600, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
      if (!ok) return;
      try { if (url.value.trim()) file.check(url.value, this.lay.to); } catch (e) { await FM.alert('The web address calculation is not valid: ' + e.message, { icon: 'warn' }); return; }
      this.snapshot(); o.url = url.value; o.interact = interact.input.checked;
    }
    async condFormat(o) {
      const file = this.file;
      const conds = FM.clone(o.cond || []);
      const list = h('div', { class: 'fm-col' });
      const draw = () => {
        list.innerHTML = '';
        conds.forEach((c, i) => {
          const f = h('input', { class: 'fm-input fm-mono', value: c.calc || '', placeholder: 'Condition, e.g. Self > 1000 or Status = "Overdue"' });
          f.oninput = () => { c.calc = f.value; };
          const st = c.style = c.style || {};
          const fill = h('input', { type: 'color', value: st.fill || '#fff3cd' }); const fillOn = FM.check('Fill', !!st.fill);
          const color = h('input', { type: 'color', value: st.color || '#b42318' }); const colOn = FM.check('Text', !!st.color);
          const sync = () => { st.fill = fillOn.input.checked ? fill.value : undefined; st.color = colOn.input.checked ? color.value : undefined; };
          [fill, color, fillOn.input, colOn.input].forEach(x => x.addEventListener('input', sync));
          const b = FM.check('Bold', !!st.bold); b.input.onchange = () => { st.bold = b.input.checked || undefined; };
          const it = FM.check('Italic', !!st.italic); it.input.onchange = () => { st.italic = it.input.checked || undefined; };
          const u = FM.check('Underline', !!st.underline); u.input.onchange = () => { st.underline = u.input.checked || undefined; };
          list.appendChild(h('div', { class: 'fm-cond' }, h('div', { class: 'fm-inline' }, f, h('button', { class: 'fm-btn small', text: '…', onclick: async () => { const r = await FM.dlg.calc(file, { formula: f.value, to: this.lay.to, title: 'Condition (use Self for this object\'s value)' }); if (r) { f.value = r.formula; c.calc = r.formula; } } }), h('button', { class: 'fm-iconbtn', html: FM.icon('trash', 14), onclick: () => { conds.splice(i, 1); draw(); } })), h('div', { class: 'fm-inline' }, fillOn, fill, colOn, color, b, it, u)));
        });
        if (!conds.length) list.appendChild(h('div', { class: 'fm-muted small', text: 'No conditions. The first condition that is true applies its format (later ones can add to it).' }));
      };
      draw();
      const body = h('div', { class: 'fm-form' }, list, h('button', { class: 'fm-btn small', text: 'Add Condition', onclick: () => { conds.push({ calc: '', style: { fill: '#fff3cd' } }); draw(); } }));
      const ok = await FM.modal({ title: 'Conditional Formatting for Selected Object', body, width: 680, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
      if (ok) { this.snapshot(); o.cond = conds.filter(c => c.calc); this.paint(); }
    }
    async objTriggers(o) { const r = await triggerDialog(this.file, OBJ_TRIGGERS.filter(t => t !== 'OnPanelSwitch' || o.tabs), o.triggers || {}, 'Set Script Triggers — ' + describe(this.file, o, this.lay.to), this.lay.to); if (r) { this.snapshot(); o.triggers = r; this.paint(); } }
    async layoutTriggers() { const r = await triggerDialog(this.file, LAYOUT_TRIGGERS, this.lay.triggers || {}, 'Layout Script Triggers — ' + this.lay.name, this.lay.to); if (r) { this.snapshot(); this.lay.triggers = r; this.paint(); } }
    async layoutSetup() {
      const r = await layoutSetupDialog(this.file, this.lay);
      if (r) { this.snapshot(); Object.assign(this.lay, r); this.paint(); }
    }
    async partSetup(focus) {
      const lay = this.lay; const file = this.file;
      const parts = FM.clone(FM.sortParts(lay.parts));
      const tbl = h('table', { class: 'fm-grid' });
      let sel = focus ? parts.findIndex(p => p.id === focus.id) : 0;
      const draw = () => { tbl.innerHTML = ''; tbl.appendChild(h('tr', null, h('th', { text: 'Part' }), h('th', { text: 'Height' }), h('th', { text: 'Break field' }), h('th', { text: 'Options' }))); FM.sortParts(parts).forEach(p => { const i = parts.indexOf(p); const tr = h('tr', { class: i === sel ? 'on' : '' }, h('td', { text: FM.PART_NAMES[p.type] }), h('td', { text: String(p.h) }), h('td', { text: p.breakKey ? file.keyLabel(p.breakKey, lay.to) : '' }), h('td', { text: (p.pageBreakAfter ? 'Page break after' : '') + (p.fill ? ' Fill ' + p.fill : '') })); tr.onclick = () => { sel = i; draw(); }; tr.ondblclick = () => edit(i); tbl.appendChild(tr); }); };
      const edit = async i => {
        const p = i == null ? { id: FM.uid('p'), type: 'sub_leading', h: 30 } : parts[i];
        const type = FM.select(Object.entries(FM.PART_NAMES).map(([v, l]) => ({ value: v, label: l })), p.type);
        const hgt = h('input', { class: 'fm-input', type: 'number', min: 4, max: 2000, value: p.h });
        const bk = FM.select([{ value: '', label: '—' }].concat(FM.layoutFields(lay).concat((file.tableOfTO(lay.to) || { fields: [] }).fields.map(f => FM.fkey(lay.to, f.id))).filter((k, j, a) => a.indexOf(k) === j).map(k => ({ value: k, label: file.keyLabel(k, lay.to) }))), p.breakKey || '');
        const pb = FM.check('Page break after every occurrence', !!p.pageBreakAfter);
        const fill = h('input', { type: 'color', value: p.fill || '#ffffff' }); const fillOn = FM.check('Fill color', !!p.fill);
        const ok = await FM.modal({ title: 'Part Definition', body: h('div', { class: 'fm-form' }, FM.row('Type', type), FM.row('Height', hgt), FM.row('Sub-summary when sorted by', bk), pb, h('div', { class: 'fm-inline' }, fillOn, fill)), width: 460, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true, validate: () => { const t = type.value; if (/^sub_/.test(t) && !bk.value) { FM.alert('Choose the field the sub-summary breaks on.'); return false; } if (!/^sub_/.test(t) && parts.some(x => x !== p && x.type === t)) { FM.alert('A layout can have only one ' + FM.PART_NAMES[t] + ' part.'); return false; } return true; } }] });
        if (!ok) return;
        Object.assign(p, { type: type.value, h: Math.max(4, +hgt.value || 30), breakKey: /^sub_/.test(type.value) ? bk.value : undefined, pageBreakAfter: pb.input.checked || undefined, fill: fillOn.input.checked ? fill.value : undefined });
        if (i == null) { parts.push(p); sel = parts.length - 1; }
        draw();
      };
      draw();
      const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-scroll', style: { height: '240px' } }, tbl), h('div', { class: 'fm-inline' }, h('button', { class: 'fm-btn', text: 'Create…', onclick: () => edit(null) }), h('button', { class: 'fm-btn', text: 'Change…', onclick: () => edit(sel) }), h('button', { class: 'fm-btn', text: 'Delete', onclick: () => { const p = parts[sel]; if (!p) return; if (p.type === 'body' && parts.filter(x => x.type === 'body').length === 1) { FM.alert('A layout needs a Body part.'); return; } parts.splice(sel, 1); sel = 0; draw(); } })),
        h('div', { class: 'fm-muted small', text: 'Objects in a deleted part are removed. Sub-summary parts show in list view and Preview mode when the records are sorted by their break field.' }));
      const ok = await FM.modal({ title: 'Part Setup', body, width: 620, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
      if (!ok) return;
      this.snapshot();
      // keep each object in its part as the parts are re-stacked
      const oldTops = FM.partTops(lay);
      const where = new Map();
      lay.objects.forEach(o => { const t = oldTops.find(tt => o.y >= tt.top && o.y < tt.bottom) || oldTops[oldTops.length - 1]; where.set(o, t ? { id: t.part.id, off: o.y - t.top } : null); });
      lay.parts = parts;
      const newTops = FM.partTops(lay);
      lay.objects = lay.objects.filter(o => { const w = where.get(o); if (!w) return true; const t = newTops.find(tt => tt.part.id === w.id); if (!t) return false; shiftDeep(o, 0, t.top + Math.min(w.off, t.part.h - 1) - o.y); return true; });
      this.paint();
    }
    async tabOrder() {
      const objs = FM.layoutObjects(this.lay).filter(o => o.type === 'field' || o.type === 'button');
      const ordered = objs.slice().sort((a, b) => (a.tabOrder ?? 10000) - (b.tabOrder ?? 10000) || a.y - b.y || a.x - b.x);
      const list = h('select', { class: 'fm-input fm-list', size: 14 });
      const draw = s => { list.innerHTML = ''; ordered.forEach((o, i) => list.appendChild(h('option', { value: i, text: (i + 1) + '. ' + describe(this.file, o, this.lay.to) }))); if (s != null) list.selectedIndex = s; };
      draw();
      const body = h('div', { class: 'fm-form' }, list, h('div', { class: 'fm-inline' },
        h('button', { class: 'fm-btn small', text: 'Move Up', onclick: () => { const i = list.selectedIndex; if (i > 0) { [ordered[i - 1], ordered[i]] = [ordered[i], ordered[i - 1]]; draw(i - 1); } } }),
        h('button', { class: 'fm-btn small', text: 'Move Down', onclick: () => { const i = list.selectedIndex; if (i >= 0 && i < ordered.length - 1) { [ordered[i + 1], ordered[i]] = [ordered[i], ordered[i + 1]]; draw(i + 1); } } }),
        h('button', { class: 'fm-btn small', text: 'By Position (top to bottom)', onclick: () => { ordered.sort((a, b) => a.y - b.y || a.x - b.x); draw(); } }),
        h('button', { class: 'fm-btn small', text: 'By Position (left to right)', onclick: () => { ordered.sort((a, b) => a.x - b.x || a.y - b.y); draw(); } })));
      const ok = await FM.modal({ title: 'Set Tab Order', body, width: 480, buttons: [{ label: 'Clear (automatic)', value: 'clear' }, { label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
      if (!ok) return;
      this.snapshot();
      if (ok === 'clear') objs.forEach(o => { delete o.tabOrder; }); else ordered.forEach((o, i) => { o.tabOrder = i + 1; });
      this.paint();
    }

    // ── saving ──────────────────────────────────────────────────────────
    async save() {
      try {
        await this.file.saveSchema([{ op: 'upsert', coll: 'layouts', item: this.lay }]);
        this.dirty = false; this.lay = FM.clone(this.file.layout(this.lay.id));
        FM.toast('Layout saved.');
        this.app.renderChrome(this.win);
        return true;
      } catch (e) { await FM.alert(e.message, { icon: 'warn' }); return false; }
    }
    async saveQuiet() { if (this.dirty) return this.save(); return true; }
    async leave() {
      if (!this.dirty) return true;
      if (this.app.prefs.autoSaveLayouts) return this.save();
      const c = await FM.alert('Save changes to the layout "' + this.lay.name + '"?', { buttons: ['Save', "Don't Save", 'Cancel'], icon: 'warn' });
      if (c === 3) return false;
      if (c === 1) return this.save();
      this.dirty = false;
      return true;
    }
  }
  function distToSeg(p, o) {
    const x1 = o.x, y1 = o.dir === 'up' ? o.y + o.h : o.y, x2 = o.x + o.w, y2 = o.dir === 'up' ? o.y : o.y + o.h;
    const dx = x2 - x1, dy = y2 - y1; const l = dx * dx + dy * dy || 1;
    const t = FM.clamp(((p.x - x1) * dx + (p.y - y1) * dy) / l, 0, 1);
    return Math.hypot(p.x - (x1 + t * dx), p.y - (y1 + t * dy));
  }
  const DEFAULT_SIZE = { text: [120, 22], button: [120, 28], buttonbar: [300, 30], popover: [120, 28], field: [200, 22], checkbox: [200, 44], radio: [200, 44], popup: [200, 22], dropdown: [200, 22], calendar: [140, 22], rect: [120, 80], roundrect: [120, 80], oval: [100, 80], line: [160, 0], portal: [400, 130], tab: [420, 220], slide: [420, 220], webviewer: [360, 220], chart: [360, 220], image: [160, 120] };
  function iconFor(o) { return { field: 'field', text: 'text', rect: 'rect', roundrect: 'roundrect', oval: 'oval', line: 'line', button: 'button', buttonbar: 'buttonbar', popover: 'popover', portal: 'portal', tab: 'tab', slide: 'slide', chart: 'chart', webviewer: 'web', image: 'image', group: 'group' }[o.type] || 'dots'; }
  function describe(file, o, to) {
    switch (o.type) {
      case 'field': return 'Field: ' + (file.fieldByKey(o.field) ? file.keyLabel(o.field, to) : '<missing>');
      case 'text': return 'Text: ' + String(o.text || '').slice(0, 30);
      case 'button': return 'Button: ' + (o.label || o.icon || '');
      case 'portal': return 'Portal: ' + ((file.to(o.to) || {}).name || '');
      case 'tab': return 'Tab Control'; case 'slide': return 'Slide Control';
      case 'popover': return 'Popover: ' + (o.label || '');
      default: return { rect: 'Rectangle', roundrect: 'Rounded Rectangle', oval: 'Oval', line: 'Line', chart: 'Chart', webviewer: 'Web Viewer', image: 'Image', group: 'Group', buttonbar: 'Button Bar' }[o.type] || o.type;
    }
  }
  FM.Designer = Designer;

  async function triggerDialog(file, names, cur, title, to) {
    const out = FM.clone(cur || {});
    const scripts = FM.orderedScripts(file).filter(s => !s.folder && !s.separator);
    const rows = names.map(n => {
      const t = out[n] || {};
      const s = FM.select([{ value: '', label: '—' }].concat(scripts.map(x => ({ value: x.id, label: x.name }))), t.script || '');
      const p = h('input', { class: 'fm-input fm-mono', value: t.param || '', placeholder: 'parameter (calc)' });
      const br = FM.check('Browse', t.browse !== false), fi = FM.check('Find', !!t.find), lay = FM.check('Layout', false, { disabled: true });
      const sync = () => { if (s.value) out[n] = { script: s.value, param: p.value || undefined, browse: br.input.checked, find: fi.input.checked }; else delete out[n]; };
      [s, p, br.input, fi.input].forEach(x => x.addEventListener('change', sync));
      void lay;
      return h('tr', null, h('td', { text: n }), h('td', null, s), h('td', null, p), h('td', null, br, fi));
    });
    const body = h('div', { class: 'fm-form' }, h('table', { class: 'fm-grid' }, h('tr', null, h('th', { text: 'Event' }), h('th', { text: 'Script' }), h('th', { text: 'Parameter' }), h('th', { text: 'Enable in' })), rows),
      h('div', { class: 'fm-muted small', text: 'Triggers that run before an event (OnRecordCommit, OnObjectKeystroke, OnObjectValidate, OnObjectExit, OnLayoutExit, OnModeExit, OnPanelSwitch) cancel it when the script ends with Exit Script [ False ].' }));
    void to;
    const ok = await FM.modal({ title, body, width: 820, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true }] });
    return ok ? out : null;
  }
  FM.triggerDialog = triggerDialog;
  async function layoutSetupDialog(file, lay) {
    const name = h('input', { class: 'fm-input', value: lay.name });
    const to = FM.select(file.schema.tableOccurrences.map(x => ({ value: x.id, label: x.name })), lay.to);
    const menu = FM.check('Include in layout menus', !lay.hidden);
    const views = ['form', 'list', 'table'].map(v => FM.check({ form: 'Form View', list: 'List View', table: 'Table View' }[v], (lay.views || {})[v] !== false));
    const def = FM.select([{ value: 'form', label: 'Form View' }, { value: 'list', label: 'List View' }, { value: 'table', label: 'Table View' }], lay.view || 'form');
    const theme = FM.select(THEMES.map(([v, l]) => ({ value: v, label: l })), lay.theme || 'apex');
    const body = h('div', { class: 'fm-form' }, FM.row('Layout Name', name), FM.row('Show records from', to), menu, FM.row('Theme', theme), h('b', { text: 'Views' }), ...views, FM.row('Default view', def));
    const ok = await FM.modal({ title: 'Layout Setup', body, width: 460, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'OK', value: true, primary: true, validate: () => { if (!views.some(v => v.input.checked)) { FM.alert('Allow at least one view.'); return false; } if (!name.value.trim()) { FM.alert('Enter a name.'); return false; } return true; } }] });
    if (!ok) return null;
    const vs = { form: views[0].input.checked, list: views[1].input.checked, table: views[2].input.checked };
    return { name: name.value.trim(), to: to.value, hidden: !menu.input.checked || undefined, views: vs, view: vs[def.value] ? def.value : Object.keys(vs).find(k => vs[k]), theme: theme.value };
  }
  FM.layoutSetupDialog = layoutSetupDialog;

  // ═══════════════════════════════════════════════════════════════════════
  // New Layout/Report assistant
  // ═══════════════════════════════════════════════════════════════════════
  D.newLayoutAssistant = async function (win) {
    const file = win.file;
    if (!file.canCreateLayouts()) { await FM.alert('Your privileges do not allow creating layouts.', { icon: 'stopsign' }); return null; }
    if (!file.schema.tableOccurrences.length) { await FM.alert('Create a table first: File > Manage > Database.', { icon: 'info' }); return null; }
    const to = FM.select(file.schema.tableOccurrences.map(x => ({ value: x.id, label: x.name })), win.to || file.schema.tableOccurrences[0].id);
    const name = h('input', { class: 'fm-input', value: FM.uniqueName((file.to(to.value) || {}).name || 'Layout', file.schema.layouts.map(l => l.name)) });
    to.addEventListener('change', () => { name.value = FM.uniqueName(file.to(to.value).name, file.schema.layouts.map(l => l.name)); });
    const kinds = [['form', 'Form', 'One record at a time, labels beside fields'], ['list', 'List', 'One record per row'], ['table', 'Table', 'A spreadsheet-like grid'], ['report', 'Report', 'A list grouped by categories, with subtotals and totals'], ['blank', 'Blank layout', 'An empty layout to draw on']];
    let kind = 'form';
    const kindBox = h('div', { class: 'fm-kinds' });
    const drawK = () => { kindBox.innerHTML = ''; kinds.forEach(([v, l, d]) => { const c = h('div', { class: 'fm-kind' + (kind === v ? ' on' : '') }, h('span', { html: FM.icon(v === 'form' ? 'form' : v === 'list' ? 'list' : v === 'table' ? 'table' : v === 'report' ? 'preview' : 'rect', 26) }), h('b', { text: l }), h('small', { text: d })); c.onclick = () => { kind = v; drawK(); }; kindBox.appendChild(c); }); };
    drawK();
    const theme = FM.select(THEMES.map(([v, l]) => ({ value: v, label: l })), 'apex');
    const step1 = await FM.modal({ title: 'New Layout/Report', body: h('div', { class: 'fm-form' }, FM.row('Show records from', to), FM.row('Layout Name', name), kindBox, FM.row('Theme', theme)), width: 720, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: kind === 'blank' ? 'Finish' : 'Next', value: true, primary: true }] });
    if (!step1) return null;
    const toId = to.value;
    let keys = [], groups = [], totals = [], makeScript = false;
    if (kind !== 'blank') {
      const t = file.tableOfTO(toId);
      const avail = h('select', { class: 'fm-input fm-list', size: 12, multiple: true });
      const toSel = FM.toSelect(file, toId, toId);
      const fillA = () => { avail.innerHTML = ''; const tt = file.tableOfTO(toSel.value); (tt ? tt.fields : []).forEach(f => avail.appendChild(h('option', { value: FM.fkey(toSel.value, f.id), text: f.name }))); };
      toSel.onchange = fillA; fillA();
      keys = t.fields.filter(f => f.type !== 'summary' && !/^(PrimaryKey|CreationTimestamp|CreatedBy|ModificationTimestamp|ModifiedBy)$/.test(f.name)).map(f => FM.fkey(toId, f.id)).slice(0, kind === 'form' ? 20 : 6);
      const chosen = h('select', { class: 'fm-input fm-list', size: 12 });
      const drawC = () => { chosen.innerHTML = ''; keys.forEach(k => chosen.appendChild(h('option', { value: k, text: file.keyLabel(k, toId) }))); };
      drawC();
      const add = () => { [...avail.selectedOptions].forEach(o => { if (!keys.includes(o.value)) keys.push(o.value); }); drawC(); };
      avail.ondblclick = add; chosen.ondblclick = () => { keys.splice(chosen.selectedIndex, 1); drawC(); };
      const ok2 = await FM.modal({ title: 'New Layout/Report — Specify Fields', body: h('div', { class: 'fm-sortdlg' }, h('div', { class: 'fm-col' }, toSel, avail), h('div', { class: 'fm-col fm-sort-mid' }, h('button', { class: 'fm-btn small', text: 'Move →', onclick: add }), h('button', { class: 'fm-btn small', text: 'Move All →', onclick: () => { [...avail.options].forEach(o => { if (!keys.includes(o.value)) keys.push(o.value); }); drawC(); } }), h('button', { class: 'fm-btn small', text: '← Clear', onclick: () => { if (chosen.selectedIndex >= 0) { keys.splice(chosen.selectedIndex, 1); drawC(); } } }), h('button', { class: 'fm-btn small', text: 'Clear All', onclick: () => { keys = []; drawC(); } }), h('button', { class: 'fm-btn small', text: '↑', onclick: () => { const i = chosen.selectedIndex; if (i > 0) { [keys[i - 1], keys[i]] = [keys[i], keys[i - 1]]; drawC(); chosen.selectedIndex = i - 1; } } }), h('button', { class: 'fm-btn small', text: '↓', onclick: () => { const i = chosen.selectedIndex; if (i >= 0 && i < keys.length - 1) { [keys[i + 1], keys[i]] = [keys[i], keys[i + 1]]; drawC(); chosen.selectedIndex = i + 1; } } })), h('div', { class: 'fm-col' }, h('div', { class: 'fm-muted small', text: 'Layout fields' }), chosen)), width: 760, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: kind === 'report' ? 'Next' : 'Finish', value: true, primary: true }] });
      if (!ok2) return null;
      if (kind === 'report') {
        const gList = h('div', { class: 'fm-col' }, keys.map(k => { const c = FM.check(file.keyLabel(k, toId), false); c.input.value = k; return c; }));
        const numeric = keys.filter(k => { const f = file.fieldByKey(k); return f && (f.type === 'number' || ((f.options || {}).calc || {}).resultType === 'number'); });
        const tList = h('div', { class: 'fm-col' }, numeric.length ? numeric.map(k => { const c = FM.check('Total of ' + file.keyLabel(k, toId), true); c.input.value = k; return c; }) : h('span', { class: 'fm-muted small', text: 'No number fields chosen, so there are no totals.' }));
        const scr = FM.check('Create a script that sorts and previews this report', true);
        const ok3 = await FM.modal({ title: 'New Layout/Report — Organize Records', body: h('div', { class: 'fm-two' }, h('div', { class: 'fm-col' }, h('b', { text: 'Organize records by category (sub-summaries)' }), gList), h('div', { class: 'fm-col' }, h('b', { text: 'Subtotals and grand totals' }), tList, scr)), width: 700, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'Finish', value: true, primary: true }] });
        if (!ok3) return null;
        groups = [...gList.querySelectorAll('input:checked')].map(i => i.value);
        const totalKeys = [...tList.querySelectorAll('input:checked')].map(i => i.value);
        makeScript = scr.input.checked;
        keys = keys.filter(k => !groups.includes(k));
        // summary fields for the totals (created in the table when missing)
        if (totalKeys.length && file.full) {
          const t2 = FM.clone(file.schema.tables);
          const tt = t2.find(x => x.id === file.tableOfTO(toId).id);
          totalKeys.forEach(k => {
            const fid = FM.pkey(k).fid; if (FM.pkey(k).to !== toId) return;
            let s = tt.fields.find(f => f.type === 'summary' && ((f.options || {}).summary || {}).field === fid && ((f.options || {}).summary || {}).op === 'total');
            if (!s) { s = { id: FM.uid('F'), name: FM.uniqueName('Total of ' + file.field(fid).name, tt.fields.map(f => f.name)), type: 'summary', options: { summary: { op: 'total', field: fid } } }; tt.fields.push(s); }
            totals.push(FM.fkey(toId, s.id));
          });
          await file.saveSchema([{ op: 'section', name: 'database', value: { tables: t2, tableOccurrences: file.schema.tableOccurrences, relationships: file.schema.relationships } }]);
        }
      }
    }
    const lay = D.autoLayout(file, { name: name.value.trim() || 'Layout', to: toId, kind, keys, groups, totals, theme: theme.value });
    const ops = [{ op: 'upsert', coll: 'layouts', item: lay }];
    if (file.full) ops.push({ op: 'section', name: 'layoutOrder', value: (file.schema.layoutOrder || file.schema.layouts.map(l => l.id)).concat(lay.id) });
    if (makeScript && file.canCreateScripts()) {
      const sortSpec = groups.map(k => ({ key: k, dir: 'asc' }));
      ops.push({ op: 'upsert', coll: 'scripts', item: { id: FM.uid('S'), name: 'Run report: ' + lay.name, menu: true, steps: [{ id: FM.uid('t'), s: 'Go to Layout', p: { layout: { how: 'id', id: lay.id } } }, { id: FM.uid('t'), s: 'Sort Records', p: { sort: sortSpec, dialog: false } }, { id: FM.uid('t'), s: 'Enter Preview Mode', p: { pause: true } }] } });
    }
    await file.saveSchema(ops);
    return file.layout(lay.id);
  };

  // ═══════════════════════════════════════════════════════════════════════
  // Manage Layouts
  // ═══════════════════════════════════════════════════════════════════════
  FM.dlg.manageLayouts = async function (win) {
    const file = win.file;
    let sel = win.layoutId;
    const tbl = h('table', { class: 'fm-grid' });
    const draw = () => {
      tbl.innerHTML = '';
      tbl.appendChild(h('tr', null, h('th', { text: 'In menu' }), h('th', { text: 'Layout Name' }), h('th', { text: 'Table' }), h('th', { text: 'Access' })));
      file.orderedLayouts().filter(l => !l.separator && !l.folder).forEach(l => {
        const tr = h('tr', { class: l.id === sel ? 'on' : '' }, h('td', { text: l.hidden ? '' : '✓' }), h('td', { text: l.name }), h('td', { text: (file.to(l.to) || {}).name || '' }), h('td', { class: 'fm-muted', text: file.layoutAccess(l.id) }));
        tr.onclick = () => { sel = l.id; draw(); };
        tr.ondblclick = () => { api.close(true); };
        tbl.appendChild(tr);
      });
    };
    const reorder = async d => {
      const order = file.orderedLayouts().filter(l => !l.separator && !l.folder).map(l => l.id);
      const i = order.indexOf(sel); const j = i + d; if (i < 0 || j < 0 || j >= order.length) return;
      [order[i], order[j]] = [order[j], order[i]];
      try { await file.saveSchema([{ op: 'section', name: 'layoutOrder', value: order }]); draw(); } catch (e) { FM.alert(e.message, { icon: 'warn' }); }
    };
    let api;
    draw();
    const body = h('div', { class: 'fm-form' }, h('div', { class: 'fm-scroll', style: { height: '320px' } }, tbl), h('div', { class: 'fm-inline' },
      h('button', { class: 'fm-btn', text: 'New…', onclick: async () => { const l = await D.newLayoutAssistant(win); if (l) { sel = l.id; draw(); } } }),
      h('button', { class: 'fm-btn', text: 'Edit…', onclick: async () => { const l = file.layout(sel); if (!l || file.layoutAccess(sel) !== 'modify') return; const r = await layoutSetupDialog(file, l); if (r) { try { await file.saveSchema([{ op: 'upsert', coll: 'layouts', item: Object.assign(FM.clone(l), r) }]); draw(); } catch (e) { FM.alert(e.message, { icon: 'warn' }); } } } }),
      h('button', { class: 'fm-btn', text: 'Duplicate', onclick: async () => { const l = file.layout(sel); if (!l || !file.canCreateLayouts()) return; const c = FM.clone(l); c.id = FM.uid('L'); c.name = FM.uniqueName(l.name + ' Copy', file.schema.layouts.map(x => x.name)); c.objects = (c.objects || []).map(reId); try { await file.saveSchema([{ op: 'upsert', coll: 'layouts', item: c }]); sel = c.id; draw(); } catch (e) { FM.alert(e.message, { icon: 'warn' }); } } }),
      h('button', { class: 'fm-btn', text: 'Delete', onclick: async () => { const l = file.layout(sel); if (!l || file.layoutAccess(sel) !== 'modify') return; if (file.schema.layouts.length < 2) { FM.alert('A file needs at least one layout.'); return; } if (!(await FM.confirm('Permanently delete the layout "' + l.name + '"?', { ok: 'Delete' }))) return; try { await file.saveSchema([{ op: 'delete', coll: 'layouts', id: l.id }]); sel = file.schema.layouts[0].id; FM.app.windows.filter(w => w.file === file && w.layoutId === l.id).forEach(w => w.setLayout(sel, { noTrigger: true })); draw(); } catch (e) { FM.alert(e.message, { icon: 'warn' }); } } }),
      h('span', { class: 'fm-flex1' }), h('button', { class: 'fm-btn small', text: '↑', onclick: () => reorder(-1) }), h('button', { class: 'fm-btn small', text: '↓', onclick: () => reorder(1) })));
    const r = await FM.modal({ title: 'Manage Layouts', body, width: 620, onOpen: a => { api = a; }, buttons: [{ label: 'Close', value: false, cancel: true }, { label: 'Open', value: true, primary: true }] });
    if (r && sel && file.layout(sel)) await win.setLayout(sel);
  };
})();
