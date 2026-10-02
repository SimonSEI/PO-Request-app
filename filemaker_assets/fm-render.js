/* FileMaker (independent recreation) — a window: its layout, mode and found set.
   Browse / Find / Preview modes, Form / List / Table views, field controls,
   portals, tab and slide controls, popovers, charts, web viewers, record
   editing (with record locking through the host), and report pagination.
   Layout mode lives in fm-design.js. */
(function () {
  'use strict';
  const FM = window.FM;
  const { h } = FM;
  const V = FM.V, D = FM.dt;

  class FMError extends Error { constructor(code, message) { super(message || FM.ERR[code] || 'Error ' + code); this.code = code; } }
  FM.FMError = FMError;

  const PART_RANK = { top_nav: -1, title_header: 0, header: 1, leading_grand: 2, sub_leading: 3, body: 4, sub_trailing: 5, trailing_grand: 6, footer: 7, title_footer: 8 };
  FM.PART_RANK = PART_RANK;
  FM.PART_NAMES = { title_header: 'Title Header', header: 'Header', leading_grand: 'Leading Grand Summary', sub_leading: 'Sub-summary (leading)', body: 'Body', sub_trailing: 'Sub-summary (trailing)', trailing_grand: 'Trailing Grand Summary', footer: 'Footer', title_footer: 'Title Footer' };
  FM.sortParts = parts => parts.slice().sort((a, b) => PART_RANK[a.type] - PART_RANK[b.type]);
  FM.partTops = function (layout) { let y = 0; return FM.sortParts(layout.parts).map(p => { const r = { part: p, top: y, bottom: y + p.h }; y += p.h; return r; }); };
  FM.partOf = function (layout, obj) { const tops = FM.partTops(layout); return tops.find(t => obj.y >= t.top && obj.y < t.bottom) || tops[tops.length - 1]; };
  FM.layoutHeight = layout => layout.parts.reduce((a, p) => a + p.h, 0);
  const PAPER = { letter: [612, 792], legal: [612, 1008], a4: [595, 842], tabloid: [792, 1224] };
  FM.PAPER = PAPER;

  // style object -> css
  function css(st, base) {
    const s = Object.assign({}, base || {}, st || {});
    const out = {};
    if (s.fill != null && s.fill !== '') out.background = s.fill;
    if (s.color) out.color = s.color;
    if (s.font) out.fontFamily = s.font;
    if (s.size) out.fontSize = s.size + 'px';
    if (s.bold != null) out.fontWeight = s.bold ? '700' : '400';
    if (s.italic) out.fontStyle = 'italic';
    if (s.underline) out.textDecoration = 'underline';
    if (s.align) out.textAlign = s.align;
    if (s.lineWidth != null || s.line) {
      const w = s.lineWidth == null ? 1 : s.lineWidth;
      out.border = w ? w + 'px ' + (s.lineStyle || 'solid') + ' ' + (s.line || '#9aa3ae') : 'none';
    }
    if (s.radius != null) out.borderRadius = s.radius + 'px';
    if (s.padding != null) out.padding = s.padding + 'px';
    if (s.opacity != null) out.opacity = s.opacity;
    if (s.shadow) out.boxShadow = '0 2px 6px rgba(0,0,0,.18)';
    if (s.valign) { out.display = 'flex'; out.alignItems = s.valign === 'middle' ? 'center' : s.valign === 'bottom' ? 'flex-end' : 'flex-start'; out.justifyContent = s.align === 'center' ? 'center' : s.align === 'right' ? 'flex-end' : 'flex-start'; }
    return out;
  }
  FM.styleCss = css;

  // ═══════════════════════════════════════════════════════════════════════
  // window
  // ═══════════════════════════════════════════════════════════════════════
  class FMWindow {
    constructor(app, file, o) {
      o = o || {};
      this.app = app; this.file = file;
      this.id = FM.uid('w');
      this.name = o.name || file.name;
      this.style = o.style || 'document';
      this.parent = o.parent || null;
      this.mode = 'browse';
      this.view = 'form';
      this.sets = new Map();          // TO id -> {ids, index, sort, lastFind, omitted}
      this.requests = [{ omit: false, crit: {} }];
      this.reqIndex = 0;
      this.tabState = {};
      this.popovers = {};
      this.portalScroll = {};
      this.active = null;             // {obj, rec, rep, key, rowTO}
      this.zoom = 1;
      this.toolbar = o.toolbar !== false;
      this.quickFind = '';
      this.frozen = 0;
      this.timers = null;
      this.geom = { x: o.x == null ? null : o.x, y: o.y == null ? null : o.y, w: o.w || 860, h: o.h || 560 };
      this.lastRecs = {};
      this.setLayout(o.layoutId || this.defaultLayout(), { silent: true, noTrigger: true });
    }
    defaultLayout() {
      const opt = (this.file.schema.fileOptions || {}).openLayout;
      if (opt && this.file.layout(opt) && this.file.layoutAccess(opt) !== 'none') return opt;
      const l = this.file.layoutsInMenu()[0] || this.file.schema.layouts[0];
      return l ? l.id : null;
    }
    get layout() { return this.file.layout(this.layoutId) || null; }
    get to() { return this.layout ? this.layout.to : null; }
    get table() { return this.to ? this.file.tableOfTO(this.to) : null; }
    set_() {
      if (!this.to) return { ids: [], index: 0, sort: null };
      let s = this.sets.get(this.to);
      if (!s) { s = { ids: this.file.records(this.table.id).sort((a, b) => a.id - b.id).map(r => r.id), index: 0, sort: null, lastFind: null }; this.sets.set(this.to, s); }
      return s;
    }
    foundRecords() {
      const s = this.set_(); if (!this.table) return [];
      const out = []; const keep = [];
      for (const id of s.ids) { const r = this.file.record(this.table.id, id); if (r) { out.push(r); keep.push(id); } }
      if (keep.length !== s.ids.length) { s.ids = keep; s.index = FM.clamp(s.index, 0, Math.max(0, keep.length - 1)); }
      return out;
    }
    current() { const recs = this.foundRecords(); const s = this.set_(); return recs[FM.clamp(s.index, 0, recs.length - 1)] || null; }
    get index() { return this.set_().index; }
    totalCount() { return this.table ? this.file.count(this.table.id) : 0; }
    sortState() { const s = this.set_(); return s.sort && s.sort.length ? (s.semi ? 2 : 1) : 0; }
    lastVisited(tid) { const id = this.lastRecs[tid]; return id ? this.file.record(tid, id) : null; }
    ctx(rec, extra) { return Object.assign({ to: this.to, rec: rec === undefined ? this.current() : rec, win: this }, extra || {}); }

    // ── navigation ────────────────────────────────────────────────────────
    async setLayout(id, o) {
      o = o || {};
      const lay = this.file.layout(id);
      if (!lay) throw new FMError(105);
      if (this.file.layoutAccess(id) === 'none') throw new FMError(200, 'You do not have access to this layout.');
      if (!o.noTrigger && this.layoutId && this.layoutId !== id) {
        if (!(await this.app.trigger(this, 'OnLayoutExit'))) return false;
        if (!(await this.commit({ silent: o.silent }))) return false;
      }
      const prev = this.layoutId;
      this.layoutId = id;
      if (!o.keepView) this.view = (lay.view && (lay.views || {})[lay.view] !== false) ? lay.view : (lay.views && lay.views.form === false ? (lay.views.list !== false ? 'list' : 'table') : 'form');
      this.active = null; this.popovers = {};
      if (this.mode === 'layout' && prev !== id) this.app.designerFor(this, true);
      if (!o.silent) this.render();
      if (!o.noTrigger && prev !== id) { await this.app.trigger(this, 'OnLayoutEnter'); await this.app.trigger(this, 'OnRecordLoad'); }
      return true;
    }
    async goTo(index, o) {
      o = o || {};
      const recs = this.foundRecords(); if (!recs.length) return false;
      index = FM.clamp(index, 0, recs.length - 1);
      const s = this.set_();
      if (index === s.index && !o.force) return true;
      if (!(await this.commit(o))) return false;
      const cur = this.current(); if (cur && this.table) this.lastRecs[this.table.id] = cur.id;
      s.index = index;
      this.active = null;
      if (!o.silent) this.render();
      if (!o.noTrigger) await this.app.trigger(this, 'OnRecordLoad');
      if (this.view !== 'form' && !o.silent) this.scrollToCurrent();
      return true;
    }
    scrollToCurrent() {
      const el = this.el && this.el.querySelector('.fm-row-current');
      if (el) el.scrollIntoView({ block: 'nearest' });
    }
    setFound(ids, o) {
      const s = this.set_(); s.ids = ids; s.index = 0;
      if (o && o.sort !== undefined) s.sort = o.sort;
      if (s.sort && s.sort.length && o && o.resort) this.applySort(s.sort, true);
    }
    applySort(spec, quiet) {
      const s = this.set_();
      const recs = this.foundRecords();
      const cur = this.current();
      this.file.sortRecs(recs, spec, this.to, this);
      s.ids = recs.map(r => r.id); s.sort = spec; s.semi = false;
      s.index = cur ? Math.max(0, s.ids.indexOf(cur.id)) : 0;
      if (!quiet) this.render();
    }
    async setMode(mode, o) {
      o = o || {};
      if (mode === this.mode && !o.force) return true;
      if (!(await this.app.trigger(this, 'OnModeExit'))) return false;
      if (this.mode === 'browse' || this.mode === 'preview') { if (!(await this.commit(o))) return false; }
      if (this.mode === 'layout' && !(await this.app.leaveLayoutMode(this))) return false;
      const was = this.mode;
      this.mode = mode;
      this.active = null; this.popovers = {};
      if (mode === 'find') {
        if (o.restore && this.set_().lastFind) this.requests = FM.clone(this.set_().lastFind);
        else if (!o.keepRequests) this.requests = [{ omit: false, crit: {} }];
        this.reqIndex = 0;
      }
      if (mode === 'layout') { if (!(await this.app.enterLayoutMode(this))) { this.mode = was; return false; } }
      this.render();
      await this.app.trigger(this, 'OnModeEnter');
      if (mode === 'find') this.focusFirst();
      return true;
    }
    async setView(view) {
      const lay = this.layout; if (!lay) return;
      if ((lay.views || {})[view] === false) return;
      if (!(await this.commit())) return;
      this.view = view;
      this.render();
      await this.app.trigger(this, 'OnViewChange');
    }

    // ── records ──────────────────────────────────────────────────────────
    myEdits() { return [...this.file.editing.entries()].filter(([, e]) => e.win === this); }
    isDirty() { return this.myEdits().some(([, e]) => e.isNew || Object.keys(e.data).length); }
    recordOpen(rec) { const e = rec && this.file.editing.get(rec.id); return !!(e && e.win === this); }
    // start editing a record (takes the host's record lock)
    async open(rec) {
      if (!rec) throw new FMError(101);
      const e = this.file.editing.get(rec.id);
      if (e) { if (e.win !== this) throw new FMError(301, 'This record is being modified in the window "' + e.win.name + '".'); return e; }
      if (!this.file.canEditRecord(rec) || this.file.layoutRecordAccess(this.layoutId) === 'view') throw new FMError(200, 'You do not have permission to modify this record.');
      const ed = { win: this, data: {}, isNew: !!rec.pending, rec, locked: false };
      this.file.editing.set(rec.id, ed);
      const r = await this.file.lock(rec);
      if (!r.ok) {
        this.file.editing.delete(rec.id);
        if (r.gone) { this.file.dropRecord(rec.t, rec.id); this.render(); }
        throw new FMError(r.fmError || 301, r.error);
      }
      ed.locked = true;
      return ed;
    }
    async setFieldValue(rec, key, value, rep, o) { // value: stored representation
      o = o || {};
      const f = this.file.fieldByKey(key);
      if (!f) throw new FMError(102);
      if (f.type === 'calculation' || f.type === 'summary') throw new FMError(201, 'This field cannot be modified.');
      if (this.file.isGlobal(f)) {
        const g = (this.file.globals.get(f.id) || []).slice(); g[(rep || 1) - 1] = value; this.file.globals.set(f.id, g); this.file.touch();
        return;
      }
      if (!rec) throw new FMError(101);
      const tid = this.file.tableOfField(f.id).id;
      if (this.file.fieldAccess(tid, f.id) !== 'modify' && !o.auto) throw new FMError(201, 'You do not have permission to modify this field.');
      if ((((f.options || {}).autoEnter || {}).prohibit) && !o.script && !o.auto) throw new FMError(201, '"' + f.name + '" cannot be modified.');
      const ed = await this.open(rec);
      const reps = this.file.reps(f);
      if (reps > 1) {
        const cur = Object.prototype.hasOwnProperty.call(ed.data, f.id) ? ed.data[f.id] : rec.d[f.id];
        const arr = Array.isArray(cur) ? cur.slice() : [cur == null ? '' : cur];
        while (arr.length < reps) arr.push('');
        arr[(rep || 1) - 1] = value;
        ed.data[f.id] = arr;
      } else ed.data[f.id] = value;
      this.file.relMemo.clear(); this.file.memo.clear();
    }
    // commit every record open in this window. Resolves false if it stays open.
    async commit(o) {
      o = o || {};
      const edits = this.myEdits();
      if (!edits.length) return true;
      if (this.app.blurring) await this.app.blurring;
      if (!o.noTrigger && !o.skipTrigger) { const ok = await this.app.trigger(this, 'OnRecordCommit'); if (!ok) return false; }
      const ops = [];
      for (const [id, ed] of edits) {
        const rec = ed.rec; const table = this.file.table(rec.t);
        if (!table) { this.file.editing.delete(id); continue; }
        const changed = new Set(Object.keys(ed.data).filter(fid => JSON.stringify(ed.data[fid]) !== JSON.stringify(rec.d[fid] == null ? '' : rec.d[fid]) || ed.isNew));
        if (!changed.size && !ed.isNew) { this.file.editing.delete(id); if (ed.locked) this.file.unlock(['rec:' + id]); continue; }
        Object.assign(ed.data, this.file.autoEnterModify(table, rec, ed.data, changed));
        if (!o.skipValidation) {
          const fails = this.file.validate(table, rec, ed.data, changed, { isNew: ed.isNew });
          for (const fl of fails) {
            if (o.silent) throw new FMError(fl.code, fl.message);
            const canOverride = fl.override && (this.file.pset().overrideValidation !== false);
            const choice = await FM.alert(fl.message, { title: 'FileMaker', buttons: canOverride ? ['Revert Record', 'No', 'Yes'] : ['Revert Record', 'OK'], icon: 'warn' });
            if (choice === 1) { await this.revert({ noTrigger: true }); return false; }
            if (!(canOverride && choice === 3)) { this.focusField(fl.field); return false; }
          }
        }
        ops.push({ op: 'update', id: rec.id, data: ed.data, mc: rec.pending ? undefined : rec.mc, commit: true });
      }
      if (!ops.length) { this.render(); return true; }
      const rt = o.rt || this.app.runner.current;
      if (rt && rt.txn && !o.flushTxn) {
        rt.txn.push(...ops);
        edits.forEach(([id]) => { const e = this.file.editing.get(id); if (e) e.queued = true; });
        return true;
      }
      try {
        await this.file.batch(ops);
        ops.forEach(op => this.file.editing.delete(op.id));
      } catch (e) {
        if (o.silent) throw new FMError(e.fmError || 301, e.message);
        const c = await FM.alert(e.message + (e.fmError === 306 ? '\n\nRevert to see their changes?' : ''), { buttons: e.fmError === 306 ? ['Revert Record', 'Cancel'] : ['OK'], icon: 'warn' });
        if (e.fmError === 306 && c === 1) await this.revert({ noTrigger: true });
        return false;
      }
      if (!o.noRender) this.render();
      return true;
    }
    async revert(o) {
      o = o || {};
      const edits = this.myEdits();
      if (!edits.length) return true;
      if (!o.noTrigger) await this.app.trigger(this, 'OnRecordRevert');
      const drop = [], unlock = [];
      for (const [id, ed] of edits) {
        this.file.editing.delete(id);
        if (ed.isNew) drop.push({ op: 'delete', id });
        else if (ed.locked) unlock.push('rec:' + id);
      }
      if (unlock.length) this.file.unlock(unlock);
      if (drop.length) { try { await this.file.batch(drop); } catch (e) { /* the host drops pending records anyway */ } }
      this.file.touch();
      this.render();
      return true;
    }
    async newRecord(o) {
      o = o || {};
      if (!this.table) throw new FMError(106);
      if (!(await this.commit(o))) return false;
      if (!this.file.canCreate(this.table.id) || this.file.layoutRecordAccess(this.layoutId) === 'view') throw new FMError(200, 'You do not have permission to create records in this table.');
      const rec = await this.file.createRecord(this.table.id, {}, true);
      const ed = { win: this, data: {}, isNew: true, rec, locked: true };
      this.file.editing.set(rec.id, ed);
      Object.assign(ed.data, this.file.autoEnterCreate(this.table, rec, this));
      const s = this.set_(); s.ids.push(rec.id); s.index = s.ids.length - 1; if (s.sort) s.semi = true;
      this.active = null;
      if (!o.silent) { this.render(); this.focusFirst(); }
      await this.app.trigger(this, 'OnRecordLoad');
      return rec;
    }
    async duplicateRecord(o) {
      o = o || {};
      const cur = this.current(); if (!cur) throw new FMError(101);
      if (!(await this.commit(o))) return false;
      if (!this.file.canCreate(this.table.id)) throw new FMError(200);
      const data = {};
      this.table.fields.forEach(f => {
        if (f.type === 'calculation' || f.type === 'summary' || this.file.isGlobal(f)) return;
        const ser = ((f.options || {}).autoEnter || {}).serial;
        if (ser && ser.on) return;
        if (cur.d[f.id] != null) data[f.id] = FM.clone(cur.d[f.id]);
      });
      const rec = await this.file.createRecord(this.table.id, {}, true);
      const ed = { win: this, data, isNew: true, rec, locked: true };
      this.file.editing.set(rec.id, ed);
      const ae = this.file.autoEnterCreate(this.table, rec, this);
      this.table.fields.forEach(f => { const a = (f.options || {}).autoEnter || {}; if (a.creation || a.serial || (a.calc && !a.calcNoReplace)) if (ae[f.id] != null) ed.data[f.id] = ae[f.id]; });
      const s = this.set_(); s.ids.splice(s.index + 1, 0, rec.id); s.index++;
      if (!o.silent) this.render();
      return rec;
    }
    // ids of records to delete with rec, following "delete related records" options
    cascade(rec, toId, seen) {
      seen = seen || new Set([rec.id]);
      const out = [];
      for (const e of this.file.ix.adj.get(toId) || []) {
        const opt = e.fromLeft ? (e.rel.rightOpts || {}) : (e.rel.leftOpts || {});
        if (!opt.delete) continue;
        for (const r of this.file.hopMatches(e, rec, toId)) if (!seen.has(r.id)) { seen.add(r.id); out.push(r.id); out.push(...this.cascade(r, e.other, seen)); }
      }
      return out;
    }
    async deleteRecord(o) {
      o = o || {};
      // a selected portal row deletes that related record
      if (this.active && this.active.rowTO && this.active.portal && !o.whole) return this.deletePortalRow(o);
      const cur = this.current(); if (!cur) throw new FMError(101);
      if (!this.file.canDeleteRecord(cur)) throw new FMError(200, 'You do not have permission to delete this record.');
      if (!o.noDialog) { const ok = await FM.confirm('Permanently delete this ENTIRE record?', { ok: 'Delete', title: 'Delete Record' }); if (!ok) throw new FMError(1); }
      const ed = this.file.editing.get(cur.id);
      if (ed && ed.win !== this) throw new FMError(301);
      const ids = [cur.id, ...this.cascade(cur, this.to)];
      ids.forEach(id => this.file.editing.delete(id));
      await this.file.batch(ids.map(id => ({ op: 'delete', id })));
      const s = this.set_(); s.ids = s.ids.filter(id => id !== cur.id); s.index = FM.clamp(s.index, 0, Math.max(0, s.ids.length - 1));
      this.active = null;
      if (!o.silent) this.render();
      await this.app.trigger(this, 'OnRecordLoad');
      return true;
    }
    async deletePortalRow(o) {
      o = o || {};
      const a = this.active;
      if (!a || !a.rowRec) throw new FMError(101);
      if (a.portal && a.portal.allowDelete === false) throw new FMError(200, 'This portal does not allow deleting related records.');
      if (!this.file.canDeleteRecord(a.rowRec)) throw new FMError(200);
      if (!o.noDialog) { const ok = await FM.confirm('Delete this related record?', { ok: 'Delete', title: 'Delete Portal Row' }); if (!ok) throw new FMError(1); }
      if (!(await this.commit(o))) return false;
      const ids = [a.rowRec.id, ...this.cascade(a.rowRec, a.rowTO)];
      await this.file.batch(ids.map(id => ({ op: 'delete', id })));
      this.active = null;
      if (!o.silent) this.render();
      return true;
    }
    async deleteAll(o) {
      o = o || {};
      const recs = this.foundRecords();
      if (!recs.length) throw new FMError(401);
      if (!o.noDialog) { const ok = await FM.confirm('Permanently delete ALL ' + recs.length + ' record(s) in the current found set?', { ok: 'Delete All', title: 'Delete All Records' }); if (!ok) throw new FMError(1); }
      if (!(await this.commit(o))) return false;
      const ids = new Set(); recs.forEach(r => { ids.add(r.id); this.cascade(r, this.to).forEach(x => ids.add(x)); });
      await this.file.batch([...ids].map(id => ({ op: 'delete', id })));
      this.set_().ids = []; this.set_().index = 0;
      if (!o.silent) this.render();
      return true;
    }
    async showAll(o) {
      o = o || {};
      if (!(await this.commit(o))) return false;
      if (this.mode === 'find') this.mode = 'browse';
      const s = this.set_();
      s.ids = this.file.records(this.table.id).sort((a, b) => a.id - b.id).map(r => r.id);
      s.index = 0;
      if (s.sort && s.sort.length && !o.unsort) this.applySort(s.sort, true);
      if (!o.silent) this.render();
      await this.app.trigger(this, 'OnRecordLoad');
      return true;
    }
    async omit(n, o) {
      o = o || {};
      if (!(await this.commit(o))) return false;
      const s = this.set_(); if (!s.ids.length) throw new FMError(101);
      s.ids.splice(s.index, Math.max(1, n || 1));
      s.index = FM.clamp(s.index, 0, Math.max(0, s.ids.length - 1));
      if (!o.silent) this.render();
      return true;
    }
    async showOmitted(o) {
      o = o || {};
      if (!(await this.commit(o))) return false;
      const s = this.set_(); const inSet = new Set(s.ids);
      s.ids = this.file.records(this.table.id).filter(r => !inSet.has(r.id)).sort((a, b) => a.id - b.id).map(r => r.id);
      s.index = 0; s.sort = null;
      if (!o.silent) this.render();
      return true;
    }
    // requests: [{omit, crit}] ; how: 'replace' | 'constrain' | 'extend'
    async performFind(requests, o) {
      o = o || {};
      requests = requests || this.requests;
      if (!this.table) throw new FMError(106);
      const s = this.set_();
      let res;
      try {
        if (o.how === 'constrain') res = this.file.find(this.table.id, this.to, requests, this.foundRecords(), this);
        else res = this.file.find(this.table.id, this.to, requests, null, this);
      } catch (e) { throw new FMError(e.fmError || 400, e.message); }
      if (o.how === 'extend') { const have = new Set(s.ids); res = this.foundRecords().concat(res.filter(r => !have.has(r.id))); }
      s.lastFind = FM.clone(requests);
      if (!res.length) {
        if (o.silent) { this.mode = 'browse'; s.ids = []; s.index = 0; this.render(); throw new FMError(401); }
        const c = await FM.alert('No records match this find criteria.', { buttons: ['Modify Find', 'Cancel'], icon: 'info' });
        if (c === 1) { this.requests = FM.clone(requests); this.mode = 'find'; this.render(); this.focusFirst(); return false; }
        this.mode = 'browse'; this.render();
        throw new FMError(401);
      }
      if (s.sort && s.sort.length) this.file.sortRecs(res, s.sort, this.to, this);
      s.ids = res.map(r => r.id); s.index = 0;
      const wasFind = this.mode === 'find';
      this.mode = 'browse';
      this.render();
      if (wasFind) await this.app.trigger(this, 'OnModeEnter');
      await this.app.trigger(this, 'OnRecordLoad');
      return true;
    }
    async quickFindRun(text, o) {
      o = o || {};
      this.quickFind = text;
      if (!String(text).trim()) return this.showAll(o);
      if (!(await this.commit(o))) return false;
      const keys = FM.layoutObjects(this.layout).filter(x => x.type === 'field' && x.field && x.quickFind !== false).map(x => x.field);
      const words = String(text).trim().split(/\s+/);
      const all = this.file.records(this.table.id);
      const res = all.filter(r => words.every(w => keys.some(k => {
        const kk = FM.pkey(k); const f = this.file.field(kk.fid); if (!f || f.type === 'container') return false;
        const m = this.file.matcher(w, f, k, this.to, this.table.id, new Map());
        const vals = kk.to === this.to ? [this.file.value(r, f, 1, this.ctx(r))] : this.file.related(this.to, r, kk.to).map(x => this.file.value(x, f, 1, { to: kk.to }));
        return vals.some(m);
      })));
      if (!res.length) { if (o.silent) throw new FMError(401); await FM.alert('No records match this request.', { icon: 'info' }); return false; }
      const s = this.set_(); s.ids = res.map(r => r.id); s.index = 0;
      if (s.sort) this.applySort(s.sort, true);
      this.render();
      return true;
    }
    async findMatching(key, how, o) {
      const cur = this.current(); if (!cur) throw new FMError(101);
      const v = this.file.keyValue(key, cur, this.ctx(cur));
      const text = V.empty(v) ? '=' : '==' + this.file.formatValue(v, this.file.fieldByKey(key));
      return this.performFind([{ omit: false, crit: { [key]: text } }], Object.assign({ how }, o || {}));
    }

    // ── find requests ────────────────────────────────────────────────────
    newRequest() { this.requests.push({ omit: false, crit: {} }); this.reqIndex = this.requests.length - 1; this.render(); this.focusFirst(); }
    duplicateRequest() { this.requests.splice(this.reqIndex + 1, 0, FM.clone(this.requests[this.reqIndex])); this.reqIndex++; this.render(); }
    deleteRequest() { if (this.requests.length <= 1) { this.requests = [{ omit: false, crit: {} }]; this.reqIndex = 0; } else { this.requests.splice(this.reqIndex, 1); this.reqIndex = Math.min(this.reqIndex, this.requests.length - 1); } this.render(); }

    // ═════════════════════════════════════════════════════════════════════
    // rendering
    // ═════════════════════════════════════════════════════════════════════
    mount(host) { this.host = host; }
    render() {
      if (this.frozen) { this.needsRender = true; return; }
      if (!this.el) return;
      this.needsRender = false;
      const active = document.activeElement;
      const keepFocus = active && this.el.contains(active) && active.dataset && active.dataset.fmKey ? { key: active.dataset.fmKey, rec: active.dataset.fmRec, rep: active.dataset.fmRep, obj: active.dataset.fmObj, sel: [active.selectionStart, active.selectionEnd] } : null;
      this.app.renderChrome(this);
      const content = this.el.querySelector('.fm-content');
      if (!content) return;
      const scroll = [content.scrollLeft, content.scrollTop];
      content.innerHTML = '';
      this.bindings = [];
      const lay = this.layout;
      if (!lay) { content.appendChild(h('div', { class: 'fm-empty', text: this.file.schema.layouts.length ? 'You do not have access to any layouts.' : 'This file has no layouts. Choose View > Layout Mode, or File > Manage > Database to add a table.' })); return; }
      if (this.mode === 'layout') { this.app.designerFor(this).render(content); return; }
      const root = h('div', { class: 'fm-layout fm-theme-' + (lay.theme || 'apex') + ' fm-mode-' + this.mode });
      root.style.zoom = this.zoom;
      if (this.mode === 'preview') this.renderPreview(root);
      else if (this.mode === 'find') this.renderForm(root, true);
      else if (this.view === 'list') this.renderList(root);
      else if (this.view === 'table') this.renderTable(root);
      else this.renderForm(root, false);
      content.appendChild(root);
      content.scrollLeft = scroll[0]; content.scrollTop = scroll[1];
      if (keepFocus) {
        const sel = '[data-fm-key="' + CSS.escape(keepFocus.key) + '"][data-fm-rec="' + CSS.escape(keepFocus.rec || '') + '"][data-fm-rep="' + CSS.escape(keepFocus.rep || '') + '"][data-fm-obj="' + CSS.escape(keepFocus.obj || '') + '"]';
        const el = this.el.querySelector(sel);
        if (el) { this.suppressEnter = true; el.focus(); this.suppressEnter = false; try { if (keepFocus.sel[0] != null) el.setSelectionRange(keepFocus.sel[0], keepFocus.sel[1]); } catch (e) { /* not a text control */ } }
      }
    }
    // only refresh values (keeps the focused field as it is)
    refresh() {
      if (this.frozen) { this.needsRender = true; return; }
      const a = document.activeElement;
      if (a && this.el && this.el.contains(a) && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT')) {
        (this.bindings || []).forEach(b => { if (!b.el.contains(a)) b.update(); });
        this.app.renderChrome(this);
      } else this.render();
    }
    partsFor(kinds) { return FM.partTops(this.layout).filter(t => kinds.includes(t.part.type)); }
    renderPart(t, ctx, extraClass) {
      const lay = this.layout;
      const el = h('div', { class: 'fm-part fm-part-' + t.part.type + (extraClass ? ' ' + extraClass : '') });
      el.style.height = t.part.h + 'px';
      el.style.width = (lay.width || 800) + 'px';
      if (t.part.fill) el.style.background = t.part.fill;
      const objs = (lay.objects || []).filter(o => o.y >= t.top && o.y < t.bottom);
      objs.forEach(o => { const n = this.renderObject(o, ctx, t.top); if (n) el.appendChild(n); });
      if (ctx.rec === null && t.part.type === 'body' && this.mode === 'browse') el.classList.add('fm-norecord');
      return el;
    }
    renderForm(root, find) {
      const rec = find ? null : this.current();
      const ctx = this.ctx(rec, { find: find ? this.requests[this.reqIndex] : null, summarySet: this.foundRecords() });
      const top = this.partsFor(['header']);
      const body = this.partsFor(['body']);
      const bottom = this.partsFor(['footer']);
      const wrap = h('div', { class: 'fm-formview' });
      top.forEach(t => wrap.appendChild(this.renderPart(t, ctx, 'fm-sticky-top')));
      if (!find && !rec) {
        body.forEach(t => { const p = this.renderPart(t, ctx); p.classList.add('fm-norecord'); wrap.appendChild(p); });
      } else body.forEach(t => wrap.appendChild(this.renderPart(t, ctx)));
      bottom.forEach(t => wrap.appendChild(this.renderPart(t, ctx, 'fm-sticky-bottom')));
      if (find && this.requests[this.reqIndex] && this.requests[this.reqIndex].omit) wrap.classList.add('fm-omit-request');
      root.appendChild(wrap);
      wrap.addEventListener('mousedown', e => { if (e.target === wrap || e.target.classList.contains('fm-part')) this.backgroundClick(); });
    }
    renderList(root) {
      const recs = this.foundRecords();
      const wrap = h('div', { class: 'fm-listview' });
      const s = this.set_();
      const flow = buildFlow(this, recs, false);
      const head = this.partsFor(['header']), foot = this.partsFor(['footer']);
      head.forEach(t => wrap.appendChild(this.renderPart(t, this.ctx(this.current(), { summarySet: recs }), 'fm-sticky-top')));
      // render only rows near the viewport for big found sets
      const LIMIT = 400;
      let start = 0;
      if (recs.length > LIMIT) start = FM.clamp(s.index - Math.floor(LIMIT / 2), 0, recs.length - LIMIT);
      let shown = 0;
      flow.forEach(item => {
        if (item.part.type === 'body') {
          const i = item.index;
          if (i < start || i >= start + LIMIT) return;
          shown++;
          const p = this.renderPart(item.t, this.ctx(item.rec, { summarySet: recs }), i === s.index ? 'fm-row-current' : '');
          p.addEventListener('mousedown', e => { if (i !== this.set_().index) { const inField = e.target.closest('.fm-field'); this.goTo(i).then(() => { if (inField) { /* focus lands after render */ } }); } else if (e.target === p) this.backgroundClick(); });
          wrap.appendChild(p);
        } else wrap.appendChild(this.renderPart(item.t, this.ctx(item.rec, { summarySet: item.set })));
      });
      if (recs.length > LIMIT) wrap.appendChild(h('div', { class: 'fm-list-more', text: 'Showing records ' + (start + 1) + '–' + (start + shown) + ' of ' + recs.length + '. Use the record navigator to move through the rest.' }));
      if (!recs.length) this.partsFor(['body']).forEach(t => { const p = this.renderPart(t, this.ctx(null)); p.classList.add('fm-norecord'); wrap.appendChild(p); });
      foot.forEach(t => wrap.appendChild(this.renderPart(t, this.ctx(this.current(), { summarySet: recs }), 'fm-sticky-bottom')));
      root.appendChild(wrap);
    }
    tableColumns() {
      const lay = this.layout;
      if (lay.tableView && lay.tableView.columns && lay.tableView.columns.length) return lay.tableView.columns.filter(c => this.file.fieldByKey(c.key));
      const body = this.partsFor(['body'])[0];
      const objs = FM.layoutObjects(lay).filter(o => o.type === 'field' && o.field && (!body || (o.y >= body.top && o.y < body.bottom)) && !o._inPortal);
      const inPortal = new Set(); FM.layoutObjects(lay).filter(o => o.type === 'portal').forEach(p => (p.children || []).forEach(c => inPortal.add(c.id)));
      const seen = new Set(); const cols = [];
      objs.filter(o => !inPortal.has(o.id)).sort((a, b) => a.y - b.y || a.x - b.x).forEach(o => { if (!seen.has(o.field)) { seen.add(o.field); cols.push({ key: o.field, w: Math.max(90, Math.min(260, o.w)), obj: o }); } });
      return cols;
    }
    renderTable(root) {
      const recs = this.foundRecords();
      const cols = this.tableColumns();
      const s = this.set_();
      const tbl = h('table', { class: 'fm-tableview' });
      const sortMap = new Map((s.sort || []).map((x, i) => [x.key, x.dir]));
      const hr = h('tr', null, h('th', { class: 'fm-tv-rownum' }, ''));
      cols.forEach(c => {
        const f = this.file.fieldByKey(c.key);
        const th = h('th', { style: { width: c.w + 'px' }, title: 'Click to sort. Right-click for more.' },
          h('span', { text: this.file.keyLabel(c.key, this.to) }), sortMap.has(c.key) ? h('span', { class: 'fm-sortmark', text: sortMap.get(c.key) === 'desc' ? ' ▼' : ' ▲' }) : null);
        th.addEventListener('click', () => this.app.act(this, async () => { const cur = sortMap.get(c.key); await this.commit(); this.applySort([{ key: c.key, dir: cur === 'asc' ? 'desc' : 'asc' }]); }));
        th.addEventListener('contextmenu', e => { e.preventDefault(); this.app.tableHeaderMenu(this, c, e.clientX, e.clientY); });
        if (f && f.type !== 'container') th.dataset.type = f.type;
        hr.appendChild(th);
      });
      const plus = h('th', { class: 'fm-tv-add', title: 'Add a field to the table view', text: '+' });
      plus.addEventListener('click', e => this.app.tableAddColumn(this, e.clientX, e.clientY));
      hr.appendChild(plus);
      tbl.appendChild(h('thead', null, hr));
      const tb = h('tbody');
      const LIMIT = 500; let start = 0;
      if (recs.length > LIMIT) start = FM.clamp(s.index - LIMIT / 2, 0, recs.length - LIMIT);
      recs.slice(start, start + LIMIT).forEach((rec, j) => {
        const i = start + j;
        const tr = h('tr', { class: i === s.index ? 'fm-row-current' : '' }, h('td', { class: 'fm-tv-rownum', text: String(i + 1) }));
        cols.forEach(c => {
          const td = h('td');
          const o = Object.assign({ type: 'field', field: c.key, control: 'edit', x: 0, y: 0, w: c.w, h: 22, id: 'tv_' + c.key }, c.obj ? { control: c.obj.control === 'checkbox' || c.obj.control === 'radio' ? 'popup' : c.obj.control, valueList: c.obj.valueList, format: c.obj.format } : {});
          const n = this.renderField(o, this.ctx(rec, { summarySet: recs, tableCell: true }), 0);
          n.style.position = 'static'; n.style.width = '100%'; n.style.height = '100%';
          td.appendChild(n);
          tr.appendChild(td);
        });
        tr.appendChild(h('td'));
        tr.addEventListener('mousedown', () => { if (i !== this.set_().index) this.goTo(i); });
        tb.appendChild(tr);
      });
      tbl.appendChild(tb);
      const wrap = h('div', { class: 'fm-tablewrap' }, tbl);
      if (!recs.length) wrap.appendChild(h('div', { class: 'fm-empty small', text: 'No records in the found set.' }));
      root.appendChild(wrap);
    }
    renderPreview(root) {
      const pages = paginate(this);
      this.previewPages = pages.length;
      this.previewPage = FM.clamp(this.previewPage || 0, 0, Math.max(0, pages.length - 1));
      const ps = this.file.schema.fileOptions.pageSetup || {};
      const [pw, ph] = pageSize(ps);
      const wrap = h('div', { class: 'fm-preview' });
      pages.forEach((pg, i) => {
        const page = h('div', { class: 'fm-page' + (i === this.previewPage ? ' fm-page-current' : ''), dataset: { page: i + 1 } });
        page.style.width = pw + 'px'; page.style.height = ph + 'px';
        const inner = h('div', { class: 'fm-page-inner' });
        const m = margins(ps);
        inner.style.left = m[3] + 'px'; inner.style.top = m[0] + 'px';
        inner.style.transform = 'scale(' + pg.scale + ')'; inner.style.transformOrigin = 'top left';
        pg.items.forEach(it => {
          const ctx = this.ctx(it.rec, { summarySet: it.set, page: i + 1, pageCount: pages.length });
          const p = this.renderPart(it.t, ctx);
          p.style.position = 'absolute'; p.style.top = it.y + 'px'; p.style.left = '0';
          inner.appendChild(p);
        });
        page.appendChild(inner);
        wrap.appendChild(page);
      });
      root.appendChild(wrap);
      setTimeout(() => { const cur = wrap.querySelector('.fm-page-current'); if (cur && this.previewScrollTo) { cur.scrollIntoView({ block: 'start' }); this.previewScrollTo = false; } }, 0);
    }

    // ═════════════════════════════════════════════════════════════════════
    // objects
    // ═════════════════════════════════════════════════════════════════════
    renderObject(o, ctx, partTop, offsetX, offsetY) {
      const file = this.file;
      if (o.hideWhen && this.mode !== 'layout' && !(this.mode === 'find' && o.hideFind === false)) {
        if (file.bool(o.hideWhen, Object.assign({}, ctx, { self: '' }))) return null;
      }
      let el;
      switch (o.type) {
        case 'field': el = this.renderField(o, ctx, partTop); break;
        case 'text': el = this.renderText(o, ctx); break;
        case 'rect': case 'roundrect': case 'oval': el = h('div', { class: 'fm-shape fm-' + o.type }); break;
        case 'line': el = renderLine(o); break;
        case 'button': el = this.renderButton(o, ctx); break;
        case 'buttonbar': el = this.renderButtonBar(o, ctx); break;
        case 'popover': el = this.renderPopover(o, ctx, partTop); break;
        case 'portal': el = this.renderPortal(o, ctx, partTop); break;
        case 'tab': case 'slide': el = this.renderTabs(o, ctx, partTop); break;
        case 'chart': el = h('div', { class: 'fm-chart' }); el.appendChild(FM.chart.render(this, o, ctx)); break;
        case 'webviewer': el = this.renderWebViewer(o, ctx); break;
        case 'image': el = h('div', { class: 'fm-image' }, o.src ? h('img', { src: o.src, alt: o.name || '', style: { objectFit: o.fit || 'contain' } }) : null); break;
        case 'group': {
          el = h('div', { class: 'fm-group' });
          (o.children || []).forEach(c => { const n = this.renderObject(c, ctx, partTop, o.x, o.y); if (n) el.appendChild(n); });
          el.style.pointerEvents = 'none';
          break;
        }
        default: return null;
      }
      if (!el) return null;
      el.classList.add('fm-obj');
      el.style.left = (o.x - (offsetX || 0)) + 'px';
      el.style.top = (o.y - (offsetY != null ? offsetY : partTop)) + 'px';
      el.style.width = o.w + 'px';
      el.style.height = o.h + 'px';
      if (o.type !== 'field' && o.type !== 'line') Object.assign(el.style, css(o.style));
      if (o.cond && o.cond.length && this.mode !== 'find') this.applyCond(el, o, ctx);
      if (o.tooltip) { const t = V.text(this.file.evaluate(o.tooltip, ctx)); if (t) el.title = t; }
      if (o.name) el.dataset.objName = o.name;
      if (o.type === 'group') el.querySelectorAll(':scope > .fm-obj').forEach(c => { c.style.pointerEvents = 'auto'; });
      return el;
    }
    applyCond(el, o, ctx) {
      const self = o.type === 'field' && ctx.rec ? this.file.keyValue(o.field, ctx.rec, ctx) : '';
      for (const c of o.cond) {
        if (!c.calc) continue;
        if (this.file.bool(c.calc, Object.assign({}, ctx, { self }))) {
          const st = css(c.style);
          Object.assign(el.style, st);
          el.querySelectorAll('input,textarea,select,.fm-fv').forEach(x => { if (st.color) x.style.color = st.color; if (st.background) x.style.background = st.background; if (st.fontWeight) x.style.fontWeight = st.fontWeight; if (st.fontStyle) x.style.fontStyle = st.fontStyle; if (st.textDecoration) x.style.textDecoration = st.textDecoration; });
        }
      }
    }
    mergeText(text, ctx) {
      const file = this.file;
      return String(text || '').replace(/<<([^<>]+)>>|\{\{(\w+)\}\}/g, (m, fld, sym) => {
        if (sym) {
          switch (sym.toLowerCase()) {
            case 'pagenumber': return String(ctx.page || 1);
            case 'pagecount': return String(ctx.pageCount || 1);
            case 'recordnumber': return ctx.rec ? String(this.foundRecords().indexOf(ctx.rec) + 1) : '';
            case 'currentdate': return D.formatDate(D.todayNum());
            case 'currenttime': return D.formatTime(D.nowSeconds(), 'hm');
            case 'username': return this.app.userName();
            case 'accountname': return file.account.name;
            case 'layoutname': return this.layout.name;
            case 'filename': return file.name;
            case 'foundcount': return String(this.foundRecords().length);
            case 'totalcount': return String(this.totalCount());
          }
          return m;
        }
        const name = fld.trim();
        if (name.startsWith('$')) return V.text(file.getVar(name, 1, ctx));
        const key = file.keyByName(name, ctx.to);
        if (!key) return m;
        if (!ctx.rec && !file.isGlobal(file.fieldByKey(key))) return '';
        return file.display(ctx.rec, key, 1, ctx);
      });
    }
    renderText(o, ctx) {
      const el = h('div', { class: 'fm-text' });
      const txt = this.mode === 'find' ? String(o.text || '').replace(/<<[^<>]+>>/g, '') : this.mergeText(o.text, ctx);
      el.textContent = txt;
      if (o.style && o.style.valign) el.classList.add('fm-valign');
      return el;
    }
    renderButton(o, ctx) {
      const el = h('button', { class: 'fm-button', type: 'button', tabIndex: o.tabOrder != null ? 0 : -1 });
      if (o.icon) el.appendChild(h('span', { class: 'fm-btn-icon', html: FM.icon(o.icon, Math.min(20, o.h - 6)) }));
      if (o.label) el.appendChild(h('span', { class: 'fm-btn-label', text: this.mergeText(o.label, ctx) }));
      el.addEventListener('mousedown', e => e.preventDefault());
      el.addEventListener('click', async e => {
        e.stopPropagation();
        if (this.app.runner.busy && !this.app.runner.pausedFrame) return;
        if (ctx.rows) this.setActiveRow(ctx);
        await this.app.runButton(this, o, ctx);
      });
      return el;
    }
    renderButtonBar(o, ctx) {
      const el = h('div', { class: 'fm-buttonbar' });
      (o.segments || []).forEach(seg => {
        const b = h('button', { class: 'fm-button fm-seg', type: 'button' }, seg.icon ? h('span', { html: FM.icon(seg.icon, 16) }) : null, seg.label ? h('span', { text: this.mergeText(seg.label, ctx) }) : null);
        if (seg.active && this.file.bool(seg.active, ctx)) b.classList.add('on');
        b.addEventListener('click', e => { e.stopPropagation(); this.app.runButton(this, seg, ctx); });
        el.appendChild(b);
      });
      return el;
    }
    renderPopover(o, ctx, partTop) {
      const el = h('div', { class: 'fm-popover-btn' });
      const btn = h('button', { class: 'fm-button', type: 'button' }, o.icon ? h('span', { html: FM.icon(o.icon, 16) }) : null, h('span', { text: this.mergeText(o.label || 'Popover', ctx) }));
      el.appendChild(btn);
      btn.addEventListener('click', e => {
        e.stopPropagation();
        this.popovers[o.id] = !this.popovers[o.id];
        this.render();
        if (this.popovers[o.id]) this.app.trigger(this, 'OnObjectEnter', o);
      });
      if (this.popovers[o.id] && o.panel) {
        const p = o.panel;
        const panel = h('div', { class: 'fm-popover-panel' });
        panel.style.left = (p.x - o.x) + 'px'; panel.style.top = (p.y - o.y) + 'px';
        panel.style.width = p.w + 'px'; panel.style.height = p.h + 'px';
        if (p.title) panel.appendChild(h('div', { class: 'fm-popover-title', text: p.title }));
        (o.children || []).forEach(c => { const n = this.renderObject(c, ctx, partTop, p.x, p.y); if (n) panel.appendChild(n); });
        panel.addEventListener('mousedown', e => e.stopPropagation());
        el.appendChild(panel);
        el.style.zIndex = 50;
        el.style.overflow = 'visible';
        setTimeout(() => {
          const close = e => { if (!panel.contains(e.target) && !btn.contains(e.target)) { document.removeEventListener('mousedown', close, true); if (this.popovers[o.id]) { this.popovers[o.id] = false; this.commit().then(() => this.render()); } } };
          document.addEventListener('mousedown', close, true);
        }, 0);
      }
      return el;
    }
    renderTabs(o, ctx, partTop) {
      const el = h('div', { class: o.type === 'slide' ? 'fm-slide' : 'fm-tabctl' });
      const tabs = o.tabs || [];
      let cur = this.tabState[o.id];
      if (cur == null) cur = this.tabState[o.id] = FM.clamp(o.defaultTab || 0, 0, Math.max(0, tabs.length - 1));
      const th = o.type === 'slide' ? 0 : (o.tabHeight || 26);
      if (o.type !== 'slide') {
        const head = h('div', { class: 'fm-tabhead', style: { height: th + 'px', justifyContent: o.justify === 'center' ? 'center' : o.justify === 'right' ? 'flex-end' : o.justify === 'full' ? 'stretch' : 'flex-start' } });
        tabs.forEach((t, i) => {
          const b = h('div', { class: 'fm-tabbtn' + (i === cur ? ' on' : ''), text: t.labelCalc ? V.text(this.file.evaluate(t.labelCalc, ctx)) : t.label });
          if (o.justify === 'full') b.style.flex = '1';
          b.addEventListener('click', () => this.switchPanel(o, i));
          head.appendChild(b);
        });
        el.appendChild(head);
      }
      const panel = h('div', { class: 'fm-tabpanel' });
      panel.style.top = th + 'px';
      const t = tabs[cur];
      if (t) (t.children || []).forEach(c => { const n = this.renderObject(c, ctx, partTop, o.x, o.y + th); if (n) panel.appendChild(n); });
      el.appendChild(panel);
      if (o.type === 'slide' && tabs.length > 1 && o.dots !== false) {
        const dots = h('div', { class: 'fm-dots' });
        tabs.forEach((x, i) => { const d = h('span', { class: i === cur ? 'on' : '' }); d.addEventListener('click', () => this.switchPanel(o, i)); dots.appendChild(d); });
        el.appendChild(dots);
      }
      return el;
    }
    async switchPanel(o, i) {
      const from = this.tabState[o.id];
      if (from === i) return;
      this.triggerInfo = { targetPanel: i + 1, currentPanel: (from || 0) + 1, panelObj: o };
      if (!(await this.app.trigger(this, 'OnPanelSwitch', o))) return;
      this.tabState[o.id] = i;
      this.render();
    }
    renderWebViewer(o, ctx) {
      const el = h('div', { class: 'fm-webviewer' });
      if (this.mode === 'find') { el.appendChild(h('div', { class: 'fm-wv-ph', text: 'Web Viewer' })); return el; }
      const url = V.text(this.file.evaluate(o.url || '', ctx)).trim();
      if (!url) return el;
      const frame = h('iframe', { class: 'fm-wv-frame', referrerpolicy: 'no-referrer', title: o.name || 'Web viewer' });
      frame.dataset.objId = o.id;
      if (/^data:text\/html/i.test(url)) {
        let html = url.replace(/^data:text\/html[^,]*,/i, '');
        if (/;base64,/i.test(url.slice(0, 40))) { try { html = new TextDecoder().decode(Uint8Array.from(atob(html), c => c.charCodeAt(0))); } catch (e) { html = ''; } } else { try { html = decodeURIComponent(html); } catch (e) { /* plain text */ } }
        frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-popups allow-modals');
        frame.srcdoc = WV_BRIDGE + html;
      } else if (/^https?:\/\//i.test(url)) {
        frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups');
        frame.src = url;
      } else if (/^about:blank$/i.test(url)) frame.src = 'about:blank';
      else { el.appendChild(h('div', { class: 'fm-wv-ph', text: 'This web viewer address is not supported: ' + url.slice(0, 80) })); return el; }
      if (o.interact === false) frame.style.pointerEvents = 'none';
      el.appendChild(frame);
      return el;
    }
    // ── portals ──────────────────────────────────────────────────────────
    portalRows(o, ctx) {
      if (!ctx.rec || !o.to) return [];
      let rows = this.file.related(ctx.to, ctx.rec, o.to).slice();
      if (o.filter && String(o.filter).trim()) rows = rows.filter(r => this.file.bool(o.filter, Object.assign({}, ctx, { rows: Object.assign({}, ctx.rows || {}, { [o.to]: r }) })));
      if (o.sort && o.sort.length) this.file.sortRecs(rows, o.sort, o.to, this);
      return rows;
    }
    renderPortal(o, ctx, partTop) {
      const el = h('div', { class: 'fm-portal' + (o.alt ? ' fm-portal-alt' : '') });
      const rowsN = Math.max(1, o.rows || 4);
      const rowH = o.h / rowsN;
      const findMode = this.mode === 'find';
      let rows = findMode ? [] : this.portalRows(o, ctx);
      const canCreate = !findMode && this.portalCanCreate(o, ctx);
      const total = findMode ? 1 : rows.length + (canCreate ? 1 : 0);
      const start = Math.max(0, (o.initialRow || 1) - 1 + (this.portalScroll[o.id] || 0));
      const list = h('div', { class: 'fm-portal-rows' });
      const visible = o.scroll === false ? rowsN : Math.max(rowsN, total);
      for (let i = start; i < Math.min(total, start + (o.scroll === false ? rowsN : visible)); i++) {
        const rec = findMode ? null : (rows[i] || null);
        const row = h('div', { class: 'fm-portal-row' + (i % 2 ? ' odd' : '') + (this.active && this.active.portal === o && this.active.rowRec === rec && rec ? ' fm-portal-row-active' : '') + (!rec && !findMode ? ' fm-portal-new' : '') });
        row.style.height = rowH + 'px';
        row.style.top = ((i - start) * rowH) + 'px';
        const rctx = Object.assign({}, ctx, { rows: Object.assign({}, ctx.rows || {}, { [o.to]: rec || { id: 'new:' + o.id, t: (this.file.to(o.to) || {}).table, d: {}, isNewRow: true } }), portal: o, rowNumber: i + 1, newRow: !rec && !findMode });
        if (findMode) rctx.rows[o.to] = null;
        (o.children || []).forEach(c => { const n = this.renderObject(c, rctx, o.y, o.x, o.y); if (n) row.appendChild(n); });
        row.addEventListener('mousedown', e => { if (e.target === row && rec) { this.setActiveRow(rctx); row.classList.add('fm-portal-row-active'); } });
        list.appendChild(row);
      }
      list.style.height = (Math.max(rowsN, (o.scroll === false ? rowsN : Math.min(visible, total))) * rowH) + 'px';
      el.appendChild(list);
      if (o.scroll !== false && total > rowsN) el.classList.add('fm-portal-scroll');
      return el;
    }
    portalCanCreate(o, ctx) {
      if (!ctx.rec || !o.to) return false;
      const p = this.file.path(ctx.to, o.to);
      if (!p || p.length !== 1) return false;
      const opt = p[0].fromLeft ? (p[0].rel.rightOpts || {}) : (p[0].rel.leftOpts || {});
      if (!opt.create) return false;
      const t = this.file.tableOfTO(o.to);
      return t && this.file.canCreate(t.id) && (p[0].rel.predicates || []).every(pr => pr.op === '=');
    }
    // typing into the empty last row of a portal creates the related record
    async createPortalRecord(o, ctx) {
      const p = this.file.path(ctx.to, o.to)[0];
      const parent = ctx.rec;
      const parentEd = this.file.editing.get(parent.id);
      const data = {};
      for (const pr of p.rel.predicates || []) {
        const mine = this.file.field(p.fromLeft ? pr.leftField : pr.rightField);
        const theirs = this.file.field(p.fromLeft ? pr.rightField : pr.leftField);
        if (!mine || !theirs) continue;
        let v = this.file.value(parent, mine, 1, { to: ctx.to });
        if (V.empty(v) && parentEd && parentEd.data[mine.id] != null) v = parentEd.data[mine.id];
        if (V.empty(v)) throw new FMError(510, 'The related record cannot be created because "' + mine.name + '" is empty.');
        if (theirs.type !== 'calculation' && theirs.type !== 'summary') data[theirs.id] = V.toStored(v, theirs.type);
      }
      const table = this.file.tableOfTO(o.to);
      const rec = await this.file.createRecord(table.id, {}, true);
      const ed = { win: this, data: Object.assign({}, data), isNew: true, rec, locked: true };
      this.file.editing.set(rec.id, ed);
      Object.assign(ed.data, this.file.autoEnterCreate(table, rec, this), data);
      // the parent joins the commit, as FileMaker commits related records with it
      if (!this.file.editing.get(parent.id)) { try { await this.open(parent); } catch (e) { /* view-only parent: the child still commits */ } }
      this.file.touch();
      return rec;
    }
    setActiveRow(ctx) {
      if (!ctx.portal) return;
      const rec = ctx.rows && ctx.rows[ctx.portal.to];
      this.active = Object.assign({}, this.active || {}, { portal: ctx.portal, rowTO: ctx.portal.to, rowRec: rec && !rec.isNewRow ? rec : null, rowNumber: ctx.rowNumber });
    }

    // ── fields ───────────────────────────────────────────────────────────
    fieldTarget(o, ctx) { // the record a field object edits, and its TO
      const k = FM.pkey(o.field);
      if (ctx.rows && Object.prototype.hasOwnProperty.call(ctx.rows, k.to)) return { rec: ctx.rows[k.to], to: k.to, viaPortal: true };
      if (k.to === ctx.to) return { rec: ctx.rec, to: k.to };
      const rel = ctx.rec ? this.file.related(ctx.to, ctx.rec, k.to) : [];
      return { rec: rel[0] || null, to: k.to, related: true };
    }
    renderField(o, ctx, partTop) {
      const file = this.file;
      const f = file.fieldByKey(o.field);
      const el = h('div', { class: 'fm-field fm-ctl-' + (o.control || 'edit') });
      // the object's style dresses the control itself (its fill, border, corners, text)
      const st = css(o.style, null);
      if (st.opacity != null) el.style.opacity = st.opacity;
      if (st.boxShadow) el.style.boxShadow = st.boxShadow;
      const dress = c => { ['background', 'border', 'borderRadius', 'padding', 'color', 'fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'textDecoration', 'textAlign'].forEach(k => { if (st[k] != null) c.style[k] = st[k]; }); if (st.alignItems) c.style.alignItems = st.alignItems; };
      if (!f) { el.appendChild(h('div', { class: 'fm-fv fm-missing', text: '<Field Missing>' })); return el; }
      const find = this.mode === 'find';
      const preview = this.mode === 'preview';
      const tgt = find ? { rec: null, to: FM.pkey(o.field).to } : this.fieldTarget(o, ctx);
      const rec = tgt.rec;
      const reps = Math.min(file.reps(f), Math.max(1, o.reps || 1));
      const tid = file.tableOfField(f.id).id;
      const access = file.fieldAccess(tid, f.id);
      if (!find && access === 'none') { el.appendChild(h('div', { class: 'fm-fv fm-noaccess', text: '<No Access>' })); return el; }
      if (!find && rec && rec.noaccess) { el.appendChild(h('div', { class: 'fm-fv fm-noaccess', text: '<No Access>' })); return el; }
      const computed = f.type === 'calculation' || f.type === 'summary';
      const isGlobal = file.isGlobal(f);
      const isNewRow = rec && rec.isNewRow;
      const readOnly = preview || (!find && (computed || access === 'view' || (o.entryBrowse === false) || (!rec && !isGlobal) ||
        (rec && !isNewRow && !file.canEditRecord(rec)) || file.layoutRecordAccess(this.layoutId) === 'view' || (((f.options || {}).autoEnter || {}).prohibit))) || (find && (o.entryFind === false || f.type === 'summary'));
      const noEntry = (!find && o.entryBrowse === false) || (find && o.entryFind === false);
      const vl = o.valueList ? file.valueList(o.valueList) : null;
      const valueText = rep => {
        if (find) return (ctx.find && ctx.find.crit[o.field + (rep > 1 ? '[' + rep + ']' : '')]) || '';
        if (isNewRow) return '';
        if (!rec && !isGlobal) return '';
        if (computed) {
          const ctx2 = Object.assign({}, ctx, { to: tgt.to, rec: isGlobal ? rec : rec, rows: ctx.rows });
          const v = tgt.related ? file.keyValue(o.field, ctx.rec, ctx) : file.value(rec, f, rep, Object.assign({}, ctx2, { to: tgt.to }));
          return file.formatValue(v, f, o.format);
        }
        const raw = file.raw(rec, f, rep);
        if (f.type === 'container') return raw;
        if (f.type === 'text') return raw;
        // display formatting only when not focused
        return raw === '' ? '' : file.formatValue(V.fromStored(raw, f.type), f, o.format);
      };
      const editText = rep => {
        if (find || isNewRow || computed || f.type === 'container' || f.type === 'text') return valueText(rep);
        const raw = file.raw(rec, f, rep);
        if (raw === '') return '';
        const v = V.fromStored(raw, f.type);
        if (f.type === 'date' && v instanceof FM.FMDate) return D.formatDate(v.n);
        if (f.type === 'time' && v instanceof FM.FMTime) return D.formatTime(v.s);
        if (f.type === 'timestamp' && v instanceof FM.FMTimestamp) return D.formatTs(v.s);
        return String(raw);
      };
      const stack = h('div', { class: 'fm-reps' + (o.repOrient === 'h' ? ' fm-reps-h' : '') });
      for (let rep = 1; rep <= reps; rep++) {
        const cell = h('div', { class: 'fm-rep' });
        const dataset = { fmKey: o.field, fmRec: rec ? String(rec.id) : (isGlobal ? 'g' : ''), fmRep: String(rep), fmObj: o.id };
        let ctl;
        if (f.type === 'container' && !find) ctl = this.containerControl(o, f, rec, rep, readOnly, ctx);
        else if (!find && (o.control === 'checkbox' || o.control === 'radio') && vl) ctl = this.choiceControl(o, f, rec, rep, readOnly || noEntry, ctx, vl, tgt, dataset);
        else if (!find && o.control === 'popup') ctl = this.popupControl(o, f, rec, rep, readOnly || noEntry, ctx, vl, tgt, dataset, valueText(rep));
        else if (preview || (readOnly && !find && (computed || noEntry || preview))) {
          ctl = h('div', { class: 'fm-fv', tabIndex: noEntry || preview ? -1 : 0, dataset });
          const vt = valueText(rep);
          if (vt instanceof FM.FMStyled) ctl.innerHTML = vt.html; else ctl.textContent = typeof vt === 'object' ? V.text(vt) : vt;
          if (computed && !noEntry && !preview) {
            ctl.addEventListener('focus', () => this.fieldEnter(o, ctx, tgt, rep, ctl));
            ctl.addEventListener('blur', () => this.fieldExit(o, ctx, tgt, rep, ctl));
          }
          const styled = computed && !tgt.related ? file.value(rec, f, rep, Object.assign({}, ctx, { to: tgt.to })) : null;
          if (styled instanceof FM.FMStyled) ctl.innerHTML = styled.html;
          if (/^\s*(-?[\d,.]+%?|-?\$[\d,.]+|\([\d,.$]+\))\s*$/.test(ctl.textContent) && !(o.style && o.style.align)) ctl.style.justifyContent = 'flex-end';
        } else {
          const multiline = f.type === 'text' && o.h > 30 && o.control !== 'calendar' && o.control !== 'dropdown' || (find && f.type === 'text' && o.h > 30);
          ctl = multiline ? h('textarea', { class: 'fm-input-field', spellcheck: 'true', dataset }) : h('input', { class: 'fm-input-field', type: o.control === 'concealed' && !find ? 'password' : 'text', dataset, autocomplete: 'off' });
          ctl.value = editText(rep);
          if (readOnly) ctl.readOnly = true;
          if (o.placeholder) { const ph = /["&(]|Get\s*\(/.test(o.placeholder) ? V.text(file.evaluate(o.placeholder, ctx)) : o.placeholder; if (ph && ph !== '?') ctl.placeholder = ph; }
          if (!find && (f.type === 'number' || (computed && ((f.options || {}).calc || {}).resultType === 'number')) && !(o.style && o.style.align)) ctl.style.textAlign = 'right';
          if (!find && f.type !== 'text' && !ctl.matches(':focus')) {
            const disp = valueText(rep); ctl.dataset.display = disp; ctl.dataset.edit = ctl.value;
            if (disp !== ctl.value) ctl.value = disp;
          }
          this.wireInput(ctl, o, f, ctx, tgt, rep, readOnly, vl);
          if (find && vl) { const dl = 'dl_' + o.id; ctl.setAttribute('list', dl); cell.appendChild(h('datalist', { id: dl }, file.valueListItems(vl, ctx).filter(i => !i.sep).map(i => h('option', { value: i.value })))); }
        }
        if (!ctl.classList.contains('fm-choices')) dress(ctl);
        else { if (st.color) ctl.style.color = st.color; if (st.fontSize) ctl.style.fontSize = st.fontSize; }
        if (ctl.classList.contains('fm-fv') && st.textAlign) ctl.style.justifyContent = st.textAlign === 'right' ? 'flex-end' : st.textAlign === 'center' ? 'center' : 'flex-start';
        cell.appendChild(ctl);
        if (!find && !readOnly && (o.control === 'dropdown' || o.control === 'calendar') && f.type !== 'container') {
          const arrow = h('span', { class: 'fm-dd-arrow', html: FM.icon(o.control === 'calendar' ? 'cal' : 'down', 14) });
          arrow.addEventListener('mousedown', e => { e.preventDefault(); ctl.focus(); this.openPicker(o, f, ctl, ctx, vl, rec, rep, tgt); });
          cell.appendChild(arrow);
          cell.classList.add('fm-has-arrow');
        }
        stack.appendChild(cell);
      }
      el.appendChild(stack);
      if (find) el.classList.add('fm-find-field');
      if (readOnly && !find) el.classList.add('fm-readonly');
      this.bindings.push({ el, update: () => { const n = this.renderField(o, ctx, partTop); el.replaceChildren(...n.childNodes); } });
      if (!find && !preview && f.type !== 'container') el.addEventListener('contextmenu', e => { e.preventDefault(); this.app.fieldMenu(this, o, ctx, e.clientX, e.clientY); });
      return el;
    }
    wireInput(ctl, o, f, ctx, tgt, rep, readOnly, vl) {
      const find = this.mode === 'find';
      ctl.addEventListener('focus', async () => {
        if (!find && f.type !== 'text' && ctl.dataset.edit != null && ctl.value !== ctl.dataset.edit) ctl.value = ctl.dataset.edit;
        if (o.selectAll) setTimeout(() => ctl.select(), 0);
        this.fieldEnter(o, ctx, tgt, rep, ctl);
        if (!find && !readOnly && o.control === 'dropdown' && vl && o.autoOpen !== false) this.openPicker(o, f, ctl, ctx, vl, tgt.rec, rep, tgt);
      });
      ctl.addEventListener('keydown', e => this.fieldKey(e, o, f, ctx, tgt, rep, ctl));
      ctl.addEventListener('input', () => this.fieldInput(o, f, ctx, tgt, rep, ctl));
      ctl.addEventListener('blur', () => this.fieldExit(o, ctx, tgt, rep, ctl));
      if (readOnly) ctl.addEventListener('beforeinput', e => e.preventDefault());
    }
    choiceControl(o, f, rec, rep, readOnly, ctx, vl, tgt, dataset) {
      const items = this.file.valueListItems(vl, Object.assign({}, ctx, { rec: ctx.rec })).filter(i => !i.sep);
      const cur = FM.splitValues(rec ? this.file.raw(rec, f, rep) : '').map(x => x.toLowerCase());
      const box = h('div', { class: 'fm-choices', tabIndex: -1, dataset });
      items.forEach((it, i) => {
        const id = this.id + '_' + o.id + '_' + rep + '_' + i;
        const inp = h('input', { type: o.control === 'checkbox' ? 'checkbox' : 'radio', id, name: this.id + '_' + o.id + '_' + rep + '_' + (rec ? rec.id : 'x'), checked: cur.includes(String(it.value).toLowerCase()), disabled: readOnly });
        inp.addEventListener('focus', () => this.fieldEnter(o, ctx, tgt, rep, inp));
        inp.addEventListener('change', () => this.app.act(this, async () => {
          const r = await this.ensureRowRecord(ctx, tgt);
          let vals;
          if (o.control === 'checkbox') {
            const now = new Set(FM.splitValues(this.file.raw(r, f, rep)).map(x => x.toLowerCase()));
            if (inp.checked) now.add(String(it.value).toLowerCase()); else now.delete(String(it.value).toLowerCase());
            vals = items.filter(x => now.has(String(x.value).toLowerCase())).map(x => x.value);
            FM.splitValues(this.file.raw(r, f, rep)).forEach(x => { if (!items.some(i2 => String(i2.value).toLowerCase() === x.toLowerCase()) && now.has(x.toLowerCase())) vals.push(x); });
          } else vals = [it.value];
          await this.setFieldValue(r, o.field, vals.join('\n'), rep);
          await this.app.trigger(this, 'OnObjectModify', o);
          this.refresh();
        }));
        box.appendChild(h('label', { class: 'fm-choice', for: id }, inp, h('span', { text: it.display })));
      });
      if (!items.length) box.appendChild(h('span', { class: 'fm-muted', text: '(value list is empty)' }));
      return box;
    }
    popupControl(o, f, rec, rep, readOnly, ctx, vl, tgt, dataset, current) {
      const items = vl ? this.file.valueListItems(vl, ctx) : [];
      const sel = h('select', { class: 'fm-input-field', disabled: readOnly, dataset });
      sel.appendChild(h('option', { value: '', text: '' }));
      const raw = rec ? this.file.raw(rec, f, rep) : '';
      let found = false;
      items.forEach(it => {
        if (it.sep) { sel.appendChild(h('option', { disabled: true, text: '────────' })); return; }
        const opt = h('option', { value: it.value, text: it.display });
        if (String(it.value).toLowerCase() === String(raw).toLowerCase() || (f.type !== 'text' && String(it.value) === String(current))) { opt.selected = true; found = true; }
        sel.appendChild(opt);
      });
      if (raw !== '' && !found) sel.appendChild(h('option', { value: raw, text: String(current || raw), selected: true }));
      sel.addEventListener('focus', () => this.fieldEnter(o, ctx, tgt, rep, sel));
      sel.addEventListener('blur', () => this.fieldExit(o, ctx, tgt, rep, sel));
      sel.addEventListener('change', () => this.app.act(this, async () => {
        const r = await this.ensureRowRecord(ctx, tgt);
        await this.setFieldValue(r, o.field, V.toStored(V.fromStored(sel.value, f.type === 'calculation' ? 'text' : f.type), f.type), rep);
        await this.app.trigger(this, 'OnObjectModify', o);
      }));
      sel.addEventListener('keydown', e => this.fieldKey(e, o, f, ctx, tgt, rep, sel));
      return sel;
    }
    containerControl(o, f, rec, rep, readOnly, ctx) {
      const raw = rec ? this.file.raw(rec, f, rep) : '';
      const box = h('div', { class: 'fm-container' + (raw ? '' : ' empty'), tabIndex: 0, dataset: { fmKey: o.field, fmRec: rec ? String(rec.id) : '', fmRep: String(rep), fmObj: o.id } });
      if (raw && typeof raw === 'object') {
        const url = raw.c ? '/filemaker/api/files/' + this.file.id + '/containers/' + raw.c : raw.url;
        const mime = raw.mime || '';
        if (mime.startsWith('image/') && mime !== 'image/svg+xml') box.appendChild(h('img', { src: url, alt: raw.name, style: { objectFit: o.fit || 'contain' } }));
        else if (mime.startsWith('audio/')) box.appendChild(h('audio', { src: url, controls: true }));
        else if (mime.startsWith('video/')) box.appendChild(h('video', { src: url, controls: true }));
        else if (mime === 'application/pdf' && o.pdfInteractive) box.appendChild(h('iframe', { src: url, class: 'fm-pdf' }));
        else box.appendChild(h('a', { class: 'fm-file', href: url + '?download=1', target: '_blank', rel: 'noopener' }, h('span', { html: FM.icon('file', 28) }), h('span', { text: raw.name }), h('small', { text: Math.max(1, Math.round((raw.size || 0) / 1024)) + ' KB' })));
      } else if (raw) box.appendChild(h('div', { class: 'fm-fv', text: String(raw) }));
      else if (!readOnly && this.mode === 'browse') box.appendChild(h('div', { class: 'fm-cont-hint', text: 'Drop a file, or double-click' }));
      const insert = file => this.app.act(this, async () => {
        const fd = new FormData(); fd.append('file', file);
        const r = await this.file.api('POST', '/containers', fd);
        const tgt = this.fieldTarget(o, ctx);
        const target = await this.ensureRowRecord(ctx, tgt);
        await this.setFieldValue(target, o.field, r.value, rep);
        await this.app.trigger(this, 'OnObjectModify', o);
        await this.commit();
      });
      if (!readOnly) {
        box.addEventListener('dblclick', async () => { const file = await FM.pickFile(); if (file) insert(file); });
        box.addEventListener('dragover', e => { e.preventDefault(); box.classList.add('drop'); });
        box.addEventListener('dragleave', () => box.classList.remove('drop'));
        box.addEventListener('drop', e => { e.preventDefault(); box.classList.remove('drop'); const file = e.dataTransfer.files[0]; if (file) insert(file); });
      }
      box.addEventListener('focus', () => this.fieldEnter(o, ctx, this.fieldTarget(o, ctx), rep, box));
      box.addEventListener('contextmenu', e => {
        e.preventDefault();
        FM.popupMenu([
          { label: 'Insert File…', disabled: readOnly, action: async () => { const file = await FM.pickFile(); if (file) insert(file); } },
          { label: 'Insert Picture…', disabled: readOnly, action: async () => { const file = await FM.pickFile('image/*'); if (file) insert(file); } },
          '-',
          { label: 'Export Field Contents…', disabled: !raw || typeof raw !== 'object', action: () => { const a = h('a', { href: '/filemaker/api/files/' + this.file.id + '/containers/' + raw.c + '?download=1', download: raw.name }); document.body.appendChild(a); a.click(); a.remove(); } },
          { label: 'Clear', disabled: readOnly || !raw, action: () => this.app.act(this, async () => { await this.setFieldValue(this.fieldTarget(o, ctx).rec, o.field, '', rep); await this.commit(); }) }
        ], e.clientX, e.clientY);
      });
      return box;
    }
    async ensureRowRecord(ctx, tgt) {
      if (tgt.rec && tgt.rec.isNewRow) {
        const rec = await this.createPortalRecord(ctx.portal, ctx);
        tgt.rec = rec;
        if (ctx.rows) ctx.rows[ctx.portal.to] = rec;
        return rec;
      }
      if (!tgt.rec && !tgt.related) throw new FMError(101);
      if (!tgt.rec && tgt.related) {
        // a related field outside a portal with no related record: create one when allowed
        const fake = { portal: { to: tgt.to }, rec: ctx.rec, to: ctx.to };
        if (!this.portalCanCreate({ to: tgt.to }, ctx)) throw new FMError(510, 'There is no related record to modify.');
        tgt.rec = await this.createPortalRecord(fake.portal, ctx);
      }
      return tgt.rec;
    }
    // ── field events ─────────────────────────────────────────────────────
    fieldEnter(o, ctx, tgt, rep, el) {
      if (this.suppressEnter) return;
      const prev = this.active;
      this.active = { obj: o, key: o.field, rep, rec: tgt.rec, el, portal: ctx.portal || null, rowTO: ctx.portal ? ctx.portal.to : null, rowRec: ctx.portal && tgt.rec && !tgt.rec.isNewRow ? tgt.rec : null, rowNumber: ctx.rowNumber, ctx, tgt };
      if (ctx.portal) { this.el.querySelectorAll('.fm-portal-row-active').forEach(x => x.classList.remove('fm-portal-row-active')); const row = el.closest('.fm-portal-row'); if (row && tgt.rec && !tgt.rec.isNewRow) row.classList.add('fm-portal-row-active'); }
      if (!prev || prev.obj !== o || prev.rep !== rep || prev.rec !== tgt.rec) this.app.trigger(this, 'OnObjectEnter', o);
      this.app.renderChrome(this);
    }
    async fieldInput(o, f, ctx, tgt, rep, el) {
      if (this.mode === 'find') {
        const req = this.requests[this.reqIndex];
        req.crit[o.field + (rep > 1 ? '[' + rep + ']' : '')] = el.value;
        if (!el.value) delete req.crit[o.field + (rep > 1 ? '[' + rep + ']' : '')];
        return;
      }
      el.dataset.dirty = '1';
      if (this.opening) return;
      if (tgt.rec && !this.recordOpen(tgt.rec) && !tgt.rec.isNewRow && !this.file.isGlobal(f)) {
        this.opening = this.open(tgt.rec).catch(async e => {
          el.dataset.dirty = '';
          const ed = this.file.editing.get(tgt.rec.id);
          if (!ed || ed.win !== this) { el.value = el.dataset.edit != null ? el.dataset.edit : this.file.raw(tgt.rec, f, rep); }
          el.blur();
          await FM.alert(e.code === 301 ? (e.message.startsWith('This record') ? e.message.replace('This record is being modified by', 'This record cannot be modified in this window because it is being modified by') : e.message) : e.message, { icon: 'warn' });
        }).finally(() => { this.opening = null; });
      }
    }
    async fieldExit(o, ctx, tgt, rep, el) {
      if (this.mode === 'find') return;
      if (el.dataset.dirty === '1') {
        el.dataset.dirty = '';
        let done;
        this.app.blurring = new Promise(r => { done = r; });
        try {
          if (this.opening) await this.opening;
          const f = this.file.fieldByKey(o.field);
          const stored = this.parseEntry(el.value, f);
          const target = await this.ensureRowRecord(ctx, tgt);
          // OnObjectValidate may reject the entry
          if (!(await this.app.trigger(this, 'OnObjectValidate', o))) { done(); this.app.blurring = null; return; }
          await this.setFieldValue(target, o.field, stored, rep);
          await this.app.trigger(this, 'OnObjectModify', o);
          if (f.type !== 'text' && stored !== '' && !this.validEntry(el.value, f)) {
            el.dataset.invalid = '1';
          }
        } catch (e) {
          if (e instanceof FMError && e.code !== 1) await FM.alert(e.message, { icon: 'warn' });
        } finally { done(); this.app.blurring = null; }
        await this.app.trigger(this, 'OnObjectSave', o);
      }
      await this.app.trigger(this, 'OnObjectExit', o);
      setTimeout(() => {
        const a = document.activeElement;
        if (!this.el || !this.el.contains(a) || !a.dataset || !a.dataset.fmKey) { if (this.active && this.active.el === el) this.active = Object.assign({}, this.active, { el: null, obj: null, key: null }); }
        this.refresh();
      }, 0);
    }
    parseEntry(text, f) {
      text = String(text);
      if (f.type === 'date') { const n = D.parseDate(text); return n == null ? text.trim() : D.isoDate(n); }
      if (f.type === 'time') { const n = D.parseTime(text); return n == null ? text.trim() : D.isoTime(n); }
      if (f.type === 'timestamp') { const n = D.parseTimestamp(text); return n == null ? text.trim() : D.isoTs(n); }
      if (f.type === 'number') return text.trim().replace(/^\$/, '').replace(/,(?=\d{3}\b)/g, '');
      return text.replace(/\r\n|\r/g, '\n');
    }
    validEntry(text, f) {
      if (!String(text).trim()) return true;
      if (f.type === 'date') return D.parseDate(text) != null;
      if (f.type === 'time') return D.parseTime(text) != null;
      if (f.type === 'timestamp') return D.parseTimestamp(text) != null;
      return true;
    }
    async fieldKey(e, o, f, ctx, tgt, rep, el) {
      const k = { key: e.key, shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey, alt: e.altKey };
      this.triggerInfo = { keystroke: e.key.length === 1 ? e.key : ({ Enter: '\r', Tab: '\t', Backspace: '\b', Escape: '\u001b', ArrowLeft: '\u001c', ArrowRight: '\u001d', ArrowUp: '\u001e', ArrowDown: '\u001f' }[e.key] || ''), modifiers: (e.shiftKey ? 1 : 0) + (e.ctrlKey ? 4 : 0) + (e.altKey ? 8 : 0) + (e.metaKey ? 16 : 0) };
      if (this.app.hasTrigger(this, 'OnObjectKeystroke', o) || this.app.hasTrigger(this, 'OnLayoutKeystroke')) {
        e.preventDefault();
        const ok = (await this.app.trigger(this, 'OnObjectKeystroke', o)) && (await this.app.trigger(this, 'OnLayoutKeystroke'));
        if (!ok) return;
        if (e.key.length === 1 && !k.ctrl && el.setRangeText) { el.setRangeText(e.key, el.selectionStart, el.selectionEnd, 'end'); el.dispatchEvent(new Event('input')); return; }
        if (e.key === 'Backspace' && el.setRangeText) { const s = el.selectionStart, en = el.selectionEnd; if (s === en && s > 0) el.setRangeText('', s - 1, en, 'end'); else el.setRangeText('', s, en, 'end'); el.dispatchEvent(new Event('input')); return; }
      }
      if (e.key === 'Tab') { e.preventDefault(); this.tabNext(el, e.shiftKey ? -1 : 1); return; }
      if (e.key === 'Enter') {
        const isText = el.tagName === 'TEXTAREA';
        if (this.mode === 'find' && !k.shift) { e.preventDefault(); el.blur(); this.app.act(this, () => this.performFind()); return; }
        if (k.ctrl || (!isText && !o.nextOnReturn) || e.location === 3) { e.preventDefault(); el.blur(); await (this.app.blurring || Promise.resolve()); await new Promise(r => setTimeout(r, 0)); this.app.act(this, () => this.commit()); return; }
        if (o.nextOnReturn && !k.shift) { e.preventDefault(); this.tabNext(el, 1); return; }
      }
      if (e.key === 'Escape' && this.mode !== 'find') { el.blur(); }
    }
    tabNext(el, dir) {
      const items = [...this.el.querySelectorAll('.fm-content [data-fm-key]:not([tabindex="-1"]):not([disabled]), .fm-content .fm-button[tabindex="0"]')].filter(x => x.offsetParent !== null);
      const order = items.map(x => {
        const oid = x.dataset.fmObj; const obj = oid && FM.layoutObjects(this.layout).find(o => o.id === oid);
        const r = x.getBoundingClientRect();
        return { x, t: obj && obj.tabOrder != null ? obj.tabOrder : 10000, top: Math.round(r.top), left: Math.round(r.left) };
      }).sort((a, b) => a.t - b.t || a.top - b.top || a.left - b.left);
      if (!order.length) return;
      let i = order.findIndex(o => o.x === el);
      i = (i + dir + order.length) % order.length;
      order[i].x.focus();
    }
    focusFirst() {
      setTimeout(() => {
        if (!this.el) return;
        const items = [...this.el.querySelectorAll('.fm-content input[data-fm-key]:not([readonly]), .fm-content textarea[data-fm-key]:not([readonly]), .fm-content select[data-fm-key]:not([disabled])')].filter(x => x.offsetParent !== null);
        const lay = this.layout; if (!lay) return;
        const objs = FM.layoutObjects(lay);
        items.sort((a, b) => { const oa = objs.find(o => o.id === a.dataset.fmObj) || {}, ob = objs.find(o => o.id === b.dataset.fmObj) || {}; return (oa.tabOrder ?? 10000) - (ob.tabOrder ?? 10000) || (oa.y - ob.y) || (oa.x - ob.x); });
        if (items[0]) items[0].focus();
      }, 30);
    }
    focusField(field, rep) {
      const fid = field.id || field;
      const el = [...this.el.querySelectorAll('[data-fm-key]')].find(x => FM.pkey(x.dataset.fmKey).fid === fid && (!rep || x.dataset.fmRep === String(rep)));
      if (el) { el.focus(); return true; }
      return false;
    }
    backgroundClick() {
      const a = document.activeElement;
      if (a && this.el.contains(a) && a.blur) a.blur();
      this.popovers = {};
      setTimeout(() => this.app.act(this, async () => { await (this.app.blurring || Promise.resolve()); if (this.mode === 'browse') { this.active = null; await this.commit(); } }), 0);
    }
    openPicker(o, f, ctl, ctx, vl, rec, rep, tgt) {
      if (this.pickerOpen) return;
      const r = ctl.getBoundingClientRect();
      const set = val => { ctl.value = val; ctl.dispatchEvent(new Event('input')); ctl.focus(); };
      let pop;
      if (o.control === 'calendar' || (!vl && (f.type === 'date' || f.type === 'timestamp'))) pop = FM.calendarPopup(D.parseDate(ctl.value), n => { set(D.formatDate(n)); close(); });
      else {
        const items = this.file.valueListItems(vl, ctx);
        pop = h('div', { class: 'fm-ddlist' });
        items.forEach(it => {
          if (it.sep) { pop.appendChild(h('div', { class: 'fm-ddsep' })); return; }
          const row = h('div', { class: 'fm-dditem' + (String(it.value).toLowerCase() === ctl.value.toLowerCase() ? ' on' : ''), text: it.display });
          row.addEventListener('mousedown', e => { e.preventDefault(); set(it.value); close(); });
          pop.appendChild(row);
        });
        if (!items.length) pop.appendChild(h('div', { class: 'fm-dditem fm-muted', text: '(no values)' }));
      }
      pop.classList.add('fm-picker');
      pop.style.left = r.left + 'px'; pop.style.top = (r.bottom + 2) + 'px'; pop.style.minWidth = r.width + 'px';
      document.body.appendChild(pop);
      this.pickerOpen = pop;
      const close = () => { pop.remove(); this.pickerOpen = null; document.removeEventListener('mousedown', outside, true); ctl.removeEventListener('blur', onBlur); };
      const outside = e => { if (!pop.contains(e.target) && e.target !== ctl) close(); };
      const onBlur = () => setTimeout(() => { if (this.pickerOpen === pop && !pop.contains(document.activeElement)) close(); }, 150);
      document.addEventListener('mousedown', outside, true);
      ctl.addEventListener('blur', onBlur);
      const pr = pop.getBoundingClientRect();
      if (pr.bottom > innerHeight) pop.style.top = Math.max(0, r.top - pr.height - 2) + 'px';
    }

    // ═════════════════════════════════════════════════════════════════════
    // Get() functions that depend on the window
    // ═════════════════════════════════════════════════════════════════════
    getFn(name, ctx) {
      const s = this.set_();
      const a = this.active;
      switch (name) {
        case 'layoutname': return this.layout ? this.layout.name : '';
        case 'layoutnumber': return this.layout ? this.file.schema.layouts.indexOf(this.layout) + 1 : 0;
        case 'layouttablename': return this.to ? this.file.to(this.to).name : '';
        case 'layoutviewstate': return { form: 0, list: 1, table: 2 }[this.view];
        case 'layoutaccess': return { modify: 2, view: 1, none: 0 }[this.file.layoutRecordAccess(this.layoutId)] ?? 2;
        case 'foundcount': return this.foundRecords().length;
        case 'totalrecordcount': return this.totalCount();
        case 'recordnumber': case 'activerecordnumber': return this.mode === 'find' ? this.reqIndex + 1 : (this.foundRecords().length ? s.index + 1 : 0);
        case 'recordid': { const r = ctx.rec || this.current(); return r ? r.id : ''; }
        case 'recordaccess': { const r = this.current(); if (!r) return 0; return this.file.canEditRecord(r) ? 2 : 1; }
        case 'recordopenstate': { const r = this.current(); const e = r && this.file.editing.get(r.id); return e ? (e.isNew ? 1 : 2) : 0; }
        case 'recordopencount': return this.myEdits().length;
        case 'modifiedfields': { const r = this.current(); const e = r && this.file.editing.get(r.id); return e ? Object.keys(e.data).map(fid => (this.file.field(fid) || {}).name).filter(Boolean).join('\n') : ''; }
        case 'requestcount': return this.mode === 'find' ? this.requests.length : (s.lastFind || []).length;
        case 'requestomitstate': return this.mode === 'find' && this.requests[this.reqIndex] && this.requests[this.reqIndex].omit ? 1 : 0;
        case 'sortstate': return this.sortState();
        case 'windowmode': return { browse: 0, find: 1, preview: 2, layout: 4 }[this.mode];
        case 'windowname': return this.name;
        case 'windowstyle': return { document: 0, floating: 1, dialog: 2, card: 3 }[this.style] || 0;
        case 'windowvisible': return this.hidden ? 0 : 1;
        case 'windowzoomlevel': return Math.round(this.zoom * 100);
        case 'windowwidth': case 'windowcontentwidth': return this.el ? this.el.clientWidth : 0;
        case 'windowheight': case 'windowcontentheight': return this.el ? this.el.clientHeight : 0;
        case 'windowtop': return this.el ? Math.round(this.el.getBoundingClientRect().top) : 0;
        case 'windowleft': return this.el ? Math.round(this.el.getBoundingClientRect().left) : 0;
        case 'windowdesktopwidth': return innerWidth; case 'windowdesktopheight': return innerHeight;
        case 'windoworientation': return innerWidth >= innerHeight ? 1 : 0;
        case 'statusareastate': return this.toolbar ? 1 : 0;
        case 'menubarstate': return this.app.menubarHidden ? 0 : 1;
        case 'pagenumber': return ctx.page || (this.mode === 'preview' ? (this.previewPage || 0) + 1 : 0);
        case 'quickfindtext': return this.quickFind || '';
        case 'activefieldname': return a && a.key ? (this.file.fieldByKey(a.key) || {}).name || '' : '';
        case 'activefieldtablename': return a && a.key ? (this.file.to(FM.pkey(a.key).to) || {}).name || '' : '';
        case 'activefieldcontents': return a && a.el ? (a.el.value != null ? a.el.value : a.el.textContent) : '';
        case 'activerepetitionnumber': return a && a.key ? a.rep : 0;
        case 'activeselectionstart': return a && a.el && a.el.selectionStart != null ? a.el.selectionStart + 1 : 0;
        case 'activeselectionsize': return a && a.el && a.el.selectionStart != null ? a.el.selectionEnd - a.el.selectionStart : 0;
        case 'activelayoutobjectname': return a && a.obj ? a.obj.name || '' : '';
        case 'activeportalrownumber': return a && a.portal ? a.rowNumber || 0 : 0;
        case 'activemodifierkeys': return this.app.modifiers || 0;
        case 'triggerkeystroke': return (this.triggerInfo || {}).keystroke || '';
        case 'triggermodifierkeys': return (this.triggerInfo || {}).modifiers || 0;
        case 'triggertargetpanel': case 'triggertargettabpanel': { const t = this.triggerInfo || {}; return t.targetPanel ? t.targetPanel + '\n' + ((t.panelObj || {}).name || '') : ''; }
        case 'triggercurrentpanel': case 'triggercurrenttabpanel': { const t = this.triggerInfo || {}; return t.currentPanel ? t.currentPanel + '\n' + ((t.panelObj || {}).name || '') : ''; }
      }
      return undefined;
    }
    layoutObjectAttr(name, attr) {
      const lay = this.layout; if (!lay) return '';
      const o = FM.layoutObjects(lay).find(x => x.name && x.name.toLowerCase() === String(name).toLowerCase());
      if (!o) return '';
      const el = this.el && this.el.querySelector('[data-obj-name="' + CSS.escape(o.name) + '"]');
      switch (attr) {
        case 'objecttype': return { field: 'field', text: 'text', rect: 'rectangle', roundrect: 'rounded rectangle', oval: 'oval', line: 'line', button: 'button', buttonbar: 'button bar', popover: 'popover button', portal: 'portal', tab: 'tab control', slide: 'slide control', chart: 'graph', webviewer: 'web viewer', image: 'graphic', group: 'group' }[o.type] || o.type;
        case 'left': return o.x; case 'top': return o.y; case 'right': return o.x + o.w; case 'bottom': return o.y + o.h;
        case 'width': return o.w; case 'height': return o.h;
        case 'bounds': return [o.x, o.y, o.x + o.w, o.y + o.h, 0].join(' ');
        case 'hasfocus': return this.active && this.active.obj === o ? 1 : 0;
        case 'isfrontpanel': case 'isfronttabpanel': case 'isactive': { const parent = FM.layoutObjects(lay).find(p => (p.tabs || []).some(t => (t.children || []).includes(o))); if (!parent && (o.type !== 'tab')) return 1; if (parent) return parent.tabs[this.tabState[parent.id] || 0].children.includes(o) ? 1 : 0; return 1; }
        case 'source': return o.type === 'webviewer' ? V.text(this.file.evaluate(o.url || '', this.ctx())) : o.type === 'field' ? this.file.fullName(o.field) : '';
        case 'content': if (o.type === 'field') return this.file.display(this.current(), o.field, 1, this.ctx()); if (o.type === 'text') return this.mergeText(o.text, this.ctx()); if (o.type === 'webviewer') { const fr = el && el.querySelector('iframe'); try { return fr && fr.contentDocument ? fr.contentDocument.documentElement.outerHTML : ''; } catch (e) { return ''; } } return el ? el.textContent : '';
        case 'enclosingobject': { const parent = FM.layoutObjects(lay).find(p => (p.children || []).includes(o) || (p.tabs || []).some(t => (t.children || []).includes(o))); return parent ? parent.name || '' : ''; }
        case 'containedobjects': return (o.children || []).concat(...(o.tabs || []).map(t => t.children || [])).filter(x => x.name).map(x => x.name).join('\n');
      }
      return '';
    }
  }

  const WV_BRIDGE = '<script>window.FileMaker={PerformScript:function(n,p){parent.postMessage({fmWebViewer:1,script:String(n),param:p==null?"":String(p)},"*")},PerformScriptWithOption:function(n,p){this.PerformScript(n,p)}};window.addEventListener("message",function(e){if(e.data&&e.data.fmCall){try{var f=window[e.data.fmCall];if(typeof f==="function")f.apply(window,e.data.args||[])}catch(x){}}});<\/script>';

  function renderLine(o) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'fm-line'); svg.setAttribute('width', Math.max(1, o.w)); svg.setAttribute('height', Math.max(1, o.h)); svg.style.overflow = 'visible';
    const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    const st = o.style || {};
    const rev = o.dir === 'up';
    ln.setAttribute('x1', 0); ln.setAttribute('y1', rev ? o.h : 0); ln.setAttribute('x2', o.w); ln.setAttribute('y2', rev ? 0 : o.h);
    ln.setAttribute('stroke', st.line || '#7a8594'); ln.setAttribute('stroke-width', st.lineWidth == null ? 1 : st.lineWidth);
    if (st.lineStyle === 'dashed') ln.setAttribute('stroke-dasharray', '6 4'); if (st.lineStyle === 'dotted') ln.setAttribute('stroke-dasharray', '1.5 3');
    svg.appendChild(ln);
    const wrap = h('div', { class: 'fm-linewrap' }); wrap.appendChild(svg);
    return wrap;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // list / preview flow: parts in order, with sub-summaries for sorted breaks
  // ═══════════════════════════════════════════════════════════════════════
  function buildFlow(win, recs, preview) {
    const lay = win.layout; const tops = FM.partTops(lay);
    const of = type => tops.filter(t => t.part.type === type);
    const flow = [];
    const sortKeys = ((win.set_().sort) || []).map(s => s.key);
    const subs = (type) => of(type).filter(t => t.part.breakKey && sortKeys.includes(t.part.breakKey)).sort((a, b) => sortKeys.indexOf(a.part.breakKey) - sortKeys.indexOf(b.part.breakKey));
    const lead = subs('sub_leading'), trail = subs('sub_trailing');
    const levels = [...new Set([...lead, ...trail].map(t => t.part.breakKey))].sort((a, b) => sortKeys.indexOf(a) - sortKeys.indexOf(b));
    const bv = (r, k) => V.text(win.file.keyValue(k, r, win.ctx(r)));
    const groupKey = (r, lvl) => levels.slice(0, lvl + 1).map(k => bv(r, k)).join('\u0001');
    const groupOf = (i, lvl) => { const k = groupKey(recs[i], lvl); let a = i, b = i; while (a > 0 && groupKey(recs[a - 1], lvl) === k) a--; while (b < recs.length - 1 && groupKey(recs[b + 1], lvl) === k) b++; return recs.slice(a, b + 1); };
    of('leading_grand').forEach(t => flow.push({ t, part: t.part, rec: recs[0] || null, set: recs }));
    recs.forEach((r, i) => {
      levels.forEach((k, lvl) => {
        if (i === 0 || groupKey(recs[i - 1], lvl) !== groupKey(r, lvl)) lead.filter(t => t.part.breakKey === k).forEach(t => flow.push({ t, part: t.part, rec: r, set: groupOf(i, lvl) }));
      });
      of('body').forEach(t => flow.push({ t, part: t.part, rec: r, index: i, set: recs }));
      for (let lvl = levels.length - 1; lvl >= 0; lvl--) {
        const k = levels[lvl];
        if (i === recs.length - 1 || groupKey(recs[i + 1], lvl) !== groupKey(r, lvl)) trail.filter(t => t.part.breakKey === k).forEach(t => flow.push({ t, part: t.part, rec: r, set: groupOf(i, lvl), pageBreak: t.part.pageBreakAfter }));
      }
    });
    of('trailing_grand').forEach(t => flow.push({ t, part: t.part, rec: recs[recs.length - 1] || null, set: recs }));
    return flow;
  }
  function pageSize(ps) { const p = PAPER[ps.paper || 'letter'] || PAPER.letter; return ps.orientation === 'landscape' ? [p[1], p[0]] : p; }
  function margins(ps) { const m = ps.margins == null ? 36 : +ps.margins; return [m, m, m, m]; }
  function paginate(win) {
    const lay = win.layout; const recs = win.foundRecords();
    const ps = win.file.schema.fileOptions.pageSetup || {};
    const [pw, ph] = pageSize(ps); const m = margins(ps);
    const printableW = pw - m[1] - m[3], printableH = ph - m[0] - m[2];
    const scale = ps.fit === false ? 1 : Math.min(1, printableW / (lay.width || 800));
    const tops = FM.partTops(lay);
    const one = type => tops.find(t => t.part.type === type);
    const header = one('header'), footer = one('footer'), tHeader = one('title_header'), tFooter = one('title_footer');
    const flow = buildFlow(win, recs, true);
    const pages = [];
    let page = null, y = 0, limit = 0;
    const start = () => {
      const first = !pages.length;
      page = { items: [], scale };
      const hd = first && tHeader ? tHeader : header;
      const ft = first && tFooter ? tFooter : footer;
      y = 0;
      if (hd) { page.items.push({ t: hd, rec: null, set: recs, y: 0, head: true }); y = hd.part.h; }
      limit = printableH / scale - (ft ? ft.part.h : 0);
      page.footer = ft;
      pages.push(page);
    };
    const finish = () => { if (page && page.footer) page.items.push({ t: page.footer, rec: null, set: recs, y: printableH / scale - page.footer.part.h }); };
    start();
    flow.forEach(it => {
      const hgt = it.part.h;
      if (y + hgt > limit && page.items.some(x => !x.head)) { finish(); start(); }
      page.items.push({ t: it.t, rec: it.rec, set: it.set, y });
      if (!page.firstRec && it.rec && it.part.type === 'body') page.firstRec = it.rec;
      y += hgt;
      if (it.pageBreak) { finish(); start(); }
    });
    finish();
    // headers and footers show the page's first record
    pages.forEach(p => p.items.forEach(it => { if (it.rec === null) it.rec = p.firstRec || recs[0] || null; }));
    return pages;
  }
  FM.paginate = paginate;
  FM.buildFlow = buildFlow;

  // ═══════════════════════════════════════════════════════════════════════
  // calendar pop-up
  // ═══════════════════════════════════════════════════════════════════════
  FM.calendarPopup = function (selected, onPick) {
    const today = D.todayNum();
    let [y, m] = D.parts(selected || today);
    const box = h('div', { class: 'fm-calendar' });
    const draw = () => {
      box.innerHTML = '';
      const head = h('div', { class: 'fm-cal-head' },
        h('button', { type: 'button', html: FM.icon('prev', 14), onmousedown: e => { e.preventDefault(); m--; if (m < 1) { m = 12; y--; } draw(); } }),
        h('span', { text: D.MONTHS[m - 1] + ' ' + y }),
        h('button', { type: 'button', html: FM.icon('next', 14), onmousedown: e => { e.preventDefault(); m++; if (m > 12) { m = 1; y++; } draw(); } }));
      box.appendChild(head);
      const grid = h('div', { class: 'fm-cal-grid' });
      'SMTWTFS'.split('').forEach(d => grid.appendChild(h('span', { class: 'fm-cal-dow', text: d })));
      const first = D.num(y, m, 1); const pad = D.dow(first) - 1;
      for (let i = 0; i < pad; i++) grid.appendChild(h('span'));
      const days = D.num(y, m + 1, 1) - first;
      for (let d = 1; d <= days; d++) {
        const n = first + d - 1;
        const c = h('span', { class: 'fm-cal-day' + (n === today ? ' today' : '') + (n === selected ? ' sel' : ''), text: String(d) });
        c.addEventListener('mousedown', e => { e.preventDefault(); onPick(n); });
        grid.appendChild(c);
      }
      box.appendChild(grid);
      const t = h('div', { class: 'fm-cal-foot' }, h('button', { type: 'button', text: 'Today', onmousedown: e => { e.preventDefault(); onPick(today); } }));
      box.appendChild(t);
    };
    draw();
    return box;
  };

  // ═══════════════════════════════════════════════════════════════════════
  // charts (SVG)
  // ═══════════════════════════════════════════════════════════════════════
  const PALETTE = ['#2a6fdb', '#e8833a', '#2fa36b', '#c94f7c', '#7a5cd6', '#d6b02f', '#3aa7c9', '#8c8c8c'];
  FM.chart = {
    data(win, o, ctx) {
      const c = o.chart || {}; const file = win.file;
      let recs = [], to = ctx.to;
      if (c.source === 'related' && c.relTO) { recs = ctx.rec ? file.related(ctx.to, ctx.rec, c.relTO) : []; to = c.relTO; }
      else if (c.source === 'record') {
        const labels = FM.splitValues(V.text(file.evaluate(c.x || '', ctx)));
        const series = (c.series || []).map(s => ({ name: s.name, values: FM.splitValues(V.text(file.evaluate(s.calc || '', ctx))).map(V.num) }));
        return { labels, series };
      } else recs = (win.layoutId && ctx.summarySet) || win.foundRecords();
      if (win.mode === 'layout' || win.mode === 'find') return { labels: ['A', 'B', 'C', 'D'], series: [{ name: 'Series', values: [3, 5, 2, 6] }] };
      const ev = (calc, r) => file.evaluate(calc || '', { to, rec: r, win, rows: to !== ctx.to ? { [to]: r } : undefined, summarySet: recs });
      // group by label when "summarize" is on (e.g. total per category)
      if (c.group) {
        const map = new Map();
        recs.forEach(r => { const l = V.text(ev(c.x, r)); if (!map.has(l)) map.set(l, (c.series || []).map(() => 0)); (c.series || []).forEach((s, i) => { map.get(l)[i] += V.num(ev(s.calc, r)); }); });
        const labels = [...map.keys()];
        return { labels, series: (c.series || []).map((s, i) => ({ name: s.name, values: labels.map(l => map.get(l)[i]) })) };
      }
      return { labels: recs.map(r => V.text(ev(c.x, r))), series: (c.series || []).map(s => ({ name: s.name, values: recs.map(r => V.num(ev(s.calc, r))) })) };
    },
    render(win, o, ctx) {
      const c = o.chart || {}; const W = o.w, H = o.h;
      const { labels, series } = this.data(win, o, ctx);
      const ns = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(ns, 'svg');
      svg.setAttribute('width', W); svg.setAttribute('height', H); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
      const el = (tag, attrs, text) => { const n = document.createElementNS(ns, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (text != null) n.textContent = text; svg.appendChild(n); return n; };
      const titleH = c.title ? 22 : 6;
      if (c.title) el('text', { x: W / 2, y: 16, 'text-anchor': 'middle', 'font-size': 13, 'font-weight': 600, fill: '#222' }, c.title);
      const legendH = c.legend !== false && series.length > 1 || (c.type === 'pie' || c.type === 'donut') ? 18 : 0;
      const type = c.type || 'column';
      const colorOf = (i) => (series[i] && c.series && c.series[i] && c.series[i].color) || PALETTE[i % PALETTE.length];
      if (!labels.length) { el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', 'font-size': 12, fill: '#888' }, 'No data'); return svg; }
      if (type === 'pie' || type === 'donut') {
        const vals = (series[0] || { values: [] }).values; const tot = vals.reduce((a, b) => a + Math.max(0, b), 0) || 1;
        const cx = W / 2, cy = titleH + (H - titleH - legendH) / 2, r = Math.max(10, Math.min(W, H - titleH - legendH) / 2 - 6);
        let a0 = -Math.PI / 2;
        vals.forEach((v, i) => {
          const a1 = a0 + Math.max(0, v) / tot * Math.PI * 2;
          const large = a1 - a0 > Math.PI ? 1 : 0;
          const p = vals.length === 1 ? `M${cx - r},${cy}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0` : `M${cx},${cy}L${cx + r * Math.cos(a0)},${cy + r * Math.sin(a0)}A${r},${r} 0 ${large} 1 ${cx + r * Math.cos(a1)},${cy + r * Math.sin(a1)}Z`;
          const path = el('path', { d: p, fill: PALETTE[i % PALETTE.length], stroke: '#fff', 'stroke-width': 1 });
          const t = document.createElementNS(ns, 'title'); t.textContent = labels[i] + ': ' + FM.num.plain(v); path.appendChild(t);
          a0 = a1;
        });
        if (type === 'donut') el('circle', { cx, cy, r: r * 0.55, fill: '#fff' });
        let lx = 6; labels.slice(0, 8).forEach((l, i) => { el('rect', { x: lx, y: H - 13, width: 9, height: 9, fill: PALETTE[i % PALETTE.length] }); el('text', { x: lx + 12, y: H - 5, 'font-size': 10, fill: '#444' }, String(l).slice(0, 14)); lx += 18 + Math.min(14, String(l).length) * 6; });
        return svg;
      }
      const all = series.flatMap(s => s.values);
      const stacked = !!c.stacked && (type === 'column' || type === 'bar' || type === 'area');
      let max = stacked ? Math.max(0, ...labels.map((l, i) => series.reduce((a, s) => a + Math.max(0, s.values[i] || 0), 0))) : Math.max(0, ...all);
      let min = Math.min(0, ...all);
      if (max === min) max = min + 1;
      const nice = v => { if (v === 0) return 0; const sgn = Math.sign(v); v = Math.abs(v); const p = Math.pow(10, Math.floor(Math.log10(v))); const m = v / p; return sgn * (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p; };
      const stepV = nice((max - min) / 4); max = Math.ceil(max / stepV) * stepV; min = Math.floor(min / stepV) * stepV;
      const pl = 42, pr = 10, pt = titleH + 4, pb = 22 + legendH;
      const iw = W - pl - pr, ih = H - pt - pb;
      const horizontal = type === 'bar';
      const scale = v => horizontal ? pl + (v - min) / (max - min) * iw : pt + ih - (v - min) / (max - min) * ih;
      // grid
      for (let g = 0; g <= 4; g++) {
        const v = min + (max - min) * g / 4;
        if (horizontal) { const x = scale(v); el('line', { x1: x, y1: pt, x2: x, y2: pt + ih, stroke: '#e3e6ea' }); el('text', { x, y: pt + ih + 12, 'font-size': 9, 'text-anchor': 'middle', fill: '#666' }, short(v)); }
        else { const yy = scale(v); el('line', { x1: pl, y1: yy, x2: pl + iw, y2: yy, stroke: '#e3e6ea' }); el('text', { x: pl - 4, y: yy + 3, 'font-size': 9, 'text-anchor': 'end', fill: '#666' }, short(v)); }
      }
      const n = labels.length; const band = (horizontal ? ih : iw) / n;
      labels.forEach((l, i) => {
        if (horizontal) el('text', { x: pl - 4, y: pt + band * i + band / 2 + 3, 'font-size': 9, 'text-anchor': 'end', fill: '#444' }, String(l).slice(0, 10));
        else if (n <= 24 || i % Math.ceil(n / 24) === 0) el('text', { x: pl + band * i + band / 2, y: pt + ih + 12, 'font-size': 9, 'text-anchor': 'middle', fill: '#444' }, String(l).slice(0, Math.max(3, Math.floor(band / 6))));
      });
      if (type === 'column' || type === 'bar') {
        const sw = stacked ? band * 0.7 : band * 0.8 / series.length;
        labels.forEach((l, i) => {
          let acc = 0;
          series.forEach((s, j) => {
            const v = s.values[i] || 0;
            const a = stacked ? acc : 0, b = stacked ? acc + v : v; acc += stacked ? v : 0;
            const p0 = scale(Math.min(a, b)), p1 = scale(Math.max(a, b));
            const off = stacked ? band * 0.15 : band * 0.1 + sw * j;
            const r = horizontal ? el('rect', { x: p0, y: pt + band * i + off, width: Math.max(0.5, p1 - p0), height: sw, fill: colorOf(j) }) : el('rect', { x: pl + band * i + off, y: p1, width: sw, height: Math.max(0.5, p0 - p1), fill: colorOf(j) });
            const t = document.createElementNS(ns, 'title'); t.textContent = l + ' — ' + s.name + ': ' + FM.num.plain(v); r.appendChild(t);
          });
        });
      } else {
        series.forEach((s, j) => {
          const pts = s.values.map((v, i) => [pl + band * i + band / 2, scale(v)]);
          if (type === 'area') el('path', { d: 'M' + pts[0][0] + ',' + scale(0) + pts.map(p => 'L' + p[0] + ',' + p[1]).join('') + 'L' + pts[pts.length - 1][0] + ',' + scale(0) + 'Z', fill: colorOf(j), 'fill-opacity': 0.35 });
          if (type !== 'scatter') el('path', { d: pts.map((p, i) => (i ? 'L' : 'M') + p[0] + ',' + p[1]).join(''), fill: 'none', stroke: colorOf(j), 'stroke-width': 2 });
          pts.forEach((p, i) => { const cc = el('circle', { cx: p[0], cy: p[1], r: type === 'scatter' ? 3.5 : 2.5, fill: colorOf(j) }); const t = document.createElementNS(ns, 'title'); t.textContent = labels[i] + ' — ' + s.name + ': ' + FM.num.plain(s.values[i]); cc.appendChild(t); });
        });
      }
      el('line', { x1: pl, y1: pt + ih, x2: pl + iw, y2: pt + ih, stroke: '#999' });
      if (legendH) { let lx = pl; series.forEach((s, i) => { el('rect', { x: lx, y: H - 13, width: 9, height: 9, fill: colorOf(i) }); el('text', { x: lx + 12, y: H - 5, 'font-size': 10, fill: '#444' }, s.name); lx += 24 + String(s.name).length * 6; }); }
      return svg;
      function short(v) { const a = Math.abs(v); return a >= 1e6 ? +(v / 1e6).toFixed(1) + 'M' : a >= 1e3 ? +(v / 1e3).toFixed(1) + 'K' : String(+v.toFixed(2)); }
    }
  };

  FM.FMWindow = FMWindow;
})();
