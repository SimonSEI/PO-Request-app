/* FileMaker (independent recreation) — the application: Launch Center, window
   manager, menu bar, status toolbars, keyboard shortcuts, script triggers,
   opening and closing files, printing. */
(function () {
  'use strict';
  const FM = window.FM;
  const { h } = FM;
  const V = FM.V;
  const FMError = FM.FMError;
  // triggers that run before their event and can cancel it with Exit Script [ False ]
  const PRE = new Set(['OnRecordCommit', 'OnObjectKeystroke', 'OnObjectValidate', 'OnObjectExit', 'OnLayoutExit', 'OnModeExit', 'OnPanelSwitch', 'OnLayoutKeystroke', 'OnWindowClose', 'OnRecordRevert']);

  class App {
    constructor(root, boot) {
      this.root = root; this.boot = boot || {};
      this.files = new Map();
      this.windows = [];
      this.active = null;
      this.runner = new FM.Runner(this);
      this.designers = new Map();
      try { this.prefs = JSON.parse(localStorage.getItem('fm.prefs') || '{}'); } catch (e) { this.prefs = {}; }
      FM.app = this;
      this.build();
      this.showLaunch();
      window.addEventListener('keydown', e => this.onKey(e), true);
      window.addEventListener('message', e => this.onFrameMessage(e));
      window.addEventListener('beforeunload', e => { if (this.windows.some(w => w.isDirty()) || (FM.workspace.dirty)) { e.preventDefault(); e.returnValue = ''; } });
      window.addEventListener('pagehide', () => { this.files.forEach(f => { try { navigator.sendBeacon && fetch('/filemaker/api/files/' + f.id + '/close', { method: 'POST', keepalive: true, headers: { 'X-FM-Session': f.token, 'X-CSRFToken': (document.querySelector('meta[name="csrf-token"]') || {}).content || '' } }); } catch (x) { /* best effort */ } }); });
      window.addEventListener('resize', FM.debounce(() => this.windows.forEach(w => { if (w.style !== 'document' || !w.maximized) this.placeWindow(w); this.trigger(w, 'OnLayoutSizeChange'); }), 200));
    }
    savePrefs() { try { localStorage.setItem('fm.prefs', JSON.stringify(this.prefs)); } catch (e) { /* storage blocked */ } }
    userName() { return this.prefs.userName || this.boot.user || this.boot.username || 'User'; }
    persistentId() { try { let id = localStorage.getItem('fm.pid'); if (!id) { id = FM.uid('p').toUpperCase(); localStorage.setItem('fm.pid', id); } return id; } catch (e) { return 'BROWSER'; } }
    openFiles() { return [...this.files.values()]; }
    activeWindow(file) { if (file) { if (this.active && this.active.file === file) return this.active; return this.windows.filter(w => w.file === file).slice(-1)[0] || null; } return this.active; }
    activeFile() { return this.active ? this.active.file : null; }

    // ═════════════════════════════════════════════════════════════════════
    // frame
    // ═════════════════════════════════════════════════════════════════════
    build() {
      this.menubar = h('div', { class: 'fm-menubar' });
      this.desktop = h('div', { class: 'fm-desktop' });
      this.pausebar = h('div', { class: 'fm-pausebar' });
      this.root.appendChild(h('div', { class: 'fm-app' }, this.menubar, this.desktop, this.pausebar));
      this.renderMenubar();
    }
    showMenubar(how) { this.menubarHidden = how === 'hide' ? true : how === 'show' ? false : !this.menubarHidden; this.menubar.style.display = this.menubarHidden ? 'none' : ''; }
    renderMenubar() {
      const mb = this.menubar; mb.innerHTML = '';
      const brand = h('div', { class: 'fm-brand', title: 'About FileMaker' }, h('span', { class: 'fm-brand-logo', text: 'FM' }), h('span', { text: 'FileMaker' }));
      brand.onclick = () => FM.dlg.about();
      mb.appendChild(brand);
      const menus = this.menus();
      menus.forEach(m => {
        const it = h('div', { class: 'fm-menubar-item', text: m.label });
        const open = () => { const r = it.getBoundingClientRect(); FM.closeMenus(0); this.openMenu = it; mb.querySelectorAll('.fm-menubar-item.on').forEach(x => x.classList.remove('on')); it.classList.add('on'); FM.popupMenu(m.items(), r.left, r.bottom, 0, () => { it.classList.remove('on'); if (this.openMenu === it) this.openMenu = null; }); };
        it.addEventListener('mousedown', e => { e.preventDefault(); if (this.openMenu === it) { FM.closeMenus(0); it.classList.remove('on'); this.openMenu = null; } else open(); });
        it.addEventListener('mouseenter', () => { if (this.openMenu && this.openMenu !== it && document.querySelector('.fm-popmenu')) open(); });
        mb.appendChild(it);
      });
      mb.appendChild(h('div', { class: 'fm-flex1' }));
      const w = this.active;
      if (w) {
        const users = w.file.users.length;
        mb.appendChild(h('div', { class: 'fm-mb-info', title: 'Users connected to "' + w.file.name + '"', onclick: () => FM.dlg.sharing(w.file) }, h('span', { html: FM.icon('users', 14) }), ' ' + users + ' ', h('span', { class: 'fm-muted', text: '· ' + w.file.account.name })));
      }
      mb.appendChild(h('a', { class: 'fm-mb-back', href: this.boot.dashboard || '/dashboard', title: 'Back to The Office App' }, h('span', { html: FM.icon('home', 14) }), ' Office App'));
    }

    // ═════════════════════════════════════════════════════════════════════
    // menus
    // ═════════════════════════════════════════════════════════════════════
    menus() {
      const w = this.active; const f = w && w.file; const mode = w ? w.mode : null;
      const K = FM.keyLabel;
      const has = !!w;
      const full = f && f.full;
      const menusLevel = f ? (f.pset().menus || 'all') : 'all';
      const minimal = menusLevel === 'minimum';
      const act = fn => () => this.act(w, fn);
      const goLayouts = () => f ? f.orderedLayouts().filter(l => !l.separator && !l.folder && !l.hidden && f.layoutAccess(l.id) !== 'none').map(l => ({ label: l.name, checked: w.layoutId === l.id, action: act(() => w.setLayout(l.id)) })) : [];
      const file = () => [
        { label: 'New Solution…', action: () => this.showLaunch('create') },
        { label: 'Open…', key: K('Ctrl+O'), action: () => this.showLaunch() },
        { label: 'Close Window', key: K('Ctrl+W'), disabled: !has, action: () => this.closeWindow(w) },
        { label: 'Close File', disabled: !has, action: () => this.closeFile(f) },
        '-',
        { label: 'Manage', disabled: !has || minimal, sub: [
          { label: 'Database…', key: K('Ctrl+Shift+D'), disabled: !full, action: () => FM.dlg.manageDatabase(f) },
          { label: 'Security…', disabled: !full, action: () => FM.dlg.security(f) },
          { label: 'Value Lists…', action: () => FM.dlg.manageValueLists(f) },
          { label: 'Layouts…', action: () => FM.dlg.manageLayouts(w) },
          { label: 'Scripts…', key: K('Ctrl+Shift+S'), action: () => FM.workspace.open(f) },
          { label: 'External Data Sources… (planned)', disabled: true },
          { label: 'Containers… (planned)', disabled: true },
          { label: 'Custom Functions…', disabled: !full, action: () => FM.dlg.manageCustomFunctions(f) },
          { label: 'Custom Menus… (planned)', disabled: true },
          { label: 'Themes… (planned)', disabled: true }] },
        { label: 'Sharing', disabled: !has, sub: [
          { label: 'Share with FileMaker Clients…', action: () => FM.dlg.sharing(f) },
          { label: 'Share with ODBC/JDBC… (planned)', disabled: true },
          { label: 'Configure for FileMaker WebDirect… (planned)', disabled: true },
          { label: 'Upload to Host… (planned)', disabled: true }] },
        { label: 'File Options…', disabled: !full, action: () => FM.dlg.fileOptions(f) },
        { label: 'Change Password…', disabled: !has || f.pset().modifyOwnPassword === false, action: () => FM.dlg.changePassword(f) },
        '-',
        { label: 'Print Setup…', disabled: !has, action: () => FM.dlg.pageSetup(f) },
        { label: 'Print…', key: K('Ctrl+P'), disabled: !has, action: act(() => this.printFlow(w)) },
        '-',
        { label: 'Import Records', disabled: !has || mode !== 'browse', sub: [{ label: 'File…', action: act(() => FM.dlg.importRecords(w)) }, { label: 'Folder… (planned)', disabled: true }, { label: 'XML Data Source… (planned)', disabled: true }] },
        { label: 'Export Records…', disabled: !has || mode !== 'browse', action: act(() => FM.dlg.exportRecords(w, { dialog: true })) },
        { label: 'Save/Send Records As', disabled: !has || mode !== 'browse', sub: [{ label: 'Excel…', action: act(() => FM.dlg.saveAsExcel(w, {})) }, { label: 'PDF…', action: act(() => this.printFlow(w)) }, { label: 'Snapshot Link… (planned)', disabled: true }] },
        { label: 'Save a Copy As…', disabled: !full, action: () => this.saveCopy(f) },
        { label: 'Database Design Report…', disabled: !full, action: () => this.designReport(f) },
        '-',
        { label: 'Exit FileMaker', action: () => this.exitApplication() }
      ];
      const edit = () => {
        const d = w && this.designers.get(w) && w.mode === 'layout' ? this.designers.get(w) : null;
        const cmd = c => () => document.execCommand(c);
        return [
          { label: 'Undo', key: K('Ctrl+Z'), action: d ? () => d.undo() : cmd('undo') },
          { label: 'Redo', key: K('Ctrl+Shift+Z'), action: d ? () => d.redo() : cmd('redo') },
          '-',
          { label: 'Cut', key: K('Ctrl+X'), action: d ? () => d.cmd('cut') : cmd('cut') },
          { label: 'Copy', key: K('Ctrl+C'), action: d ? () => d.cmd('copy') : cmd('copy') },
          { label: 'Paste', key: K('Ctrl+V'), action: d ? () => d.cmd('paste') : async () => { try { const t = await navigator.clipboard.readText(); document.execCommand('insertText', false, t); } catch (e) { FM.toast('Use Ctrl+V to paste.'); } } },
          { label: 'Clear', action: d ? () => d.cmd('delete') : cmd('delete') },
          d ? { label: 'Duplicate', key: K('Ctrl+D'), action: () => d.cmd('duplicate') } : null,
          { label: 'Select All', key: K('Ctrl+A'), action: d ? () => d.cmd('selectall') : cmd('selectAll') },
          '-',
          { label: 'Find/Replace…', disabled: !has || mode !== 'browse', action: act(() => FM.dlg.findReplace(w, { dialog: true })) },
          { label: 'Spelling (uses the browser spell checker)', disabled: true },
          '-',
          { label: 'Preferences…', action: () => FM.dlg.preferences(this) }
        ];
      };
      const view = () => [
        { label: 'Browse Mode', key: K('Ctrl+B'), checked: mode === 'browse', disabled: !has, action: act(() => w.setMode('browse')) },
        { label: 'Find Mode', key: K('Ctrl+F'), checked: mode === 'find', disabled: !has, action: act(() => w.setMode('find')) },
        { label: 'Layout Mode', key: K('Ctrl+L'), checked: mode === 'layout', disabled: !has || !w.layout || f.layoutAccess(w.layoutId) !== 'modify', action: act(() => w.setMode('layout')) },
        { label: 'Preview Mode', key: K('Ctrl+U'), checked: mode === 'preview', disabled: !has, action: act(() => w.setMode('preview')) },
        '-',
        { label: 'Go to Layout', disabled: !has, sub: goLayouts },
        '-',
        { label: 'View as Form', checked: w && w.view === 'form', disabled: !has || mode === 'layout', action: act(() => w.setView('form')) },
        { label: 'View as List', checked: w && w.view === 'list', disabled: !has || mode === 'layout', action: act(() => w.setView('list')) },
        { label: 'View as Table', checked: w && w.view === 'table', disabled: !has || mode === 'layout', action: act(() => w.setView('table')) },
        '-',
        { label: 'Status Toolbar', checked: w && w.toolbar, disabled: !has || (w && w.toolbarLocked), action: () => { w.toolbar = !w.toolbar; w.render(); } },
        { label: 'Zoom In', disabled: !has, action: act(() => FM.STEPS['Set Zoom Level'].run({ zoom: 'in' }, { win: w })) },
        { label: 'Zoom Out', disabled: !has, action: act(() => FM.STEPS['Set Zoom Level'].run({ zoom: 'out' }, { win: w })) },
        { label: 'Actual Size (100%)', disabled: !has, action: () => { w.zoom = 1; w.render(); } }
      ];
      const insert = () => {
        if (mode === 'layout') {
          const d = this.designers.get(w);
          const tool = t => () => { d.tool = t; this.renderChrome(w); FM.toast('Draw the object on the layout.'); };
          return [['Text', 'text'], ['Line', 'line'], ['Rectangle', 'rect'], ['Rounded Rectangle', 'roundrect'], ['Oval', 'oval'], ['Field', 'field'], ['Button', 'button'], ['Button Bar', 'buttonbar'], ['Popover Button', 'popover'], ['Portal', 'portal'], ['Tab Control', 'tab'], ['Slide Control', 'slide'], ['Web Viewer', 'webviewer'], ['Chart', 'chart'], ['Picture…', 'image']].map(([l, t]) => ({ label: l, action: tool(t) }))
            .concat(['-', { label: 'Field (from list)…', action: async () => { const k = await FM.dlg.pickField(f, { to: d.lay.to }); if (k) d.addFieldAt(k, null); } }]);
        }
        const ins = (s, p) => act(() => this.runStepNow(w, s, p || {}));
        return [
          { label: 'Current Date', key: K('Ctrl+-'), disabled: mode !== 'browse', action: ins('Insert Current Date') },
          { label: 'Current Time', key: K('Ctrl+;'), disabled: mode !== 'browse', action: ins('Insert Current Time') },
          { label: 'Current User Name', disabled: mode !== 'browse', action: ins('Insert Current User Name') },
          { label: 'From Last Visited Record', disabled: mode !== 'browse', action: ins('Insert From Last Visited') },
          { label: 'From Index… (planned)', disabled: true },
          '-',
          { label: 'Picture…', disabled: mode !== 'browse', action: ins('Insert Picture') },
          { label: 'Audio/Video…', disabled: mode !== 'browse', action: ins('Insert Audio/Video') },
          { label: 'PDF…', disabled: mode !== 'browse', action: ins('Insert PDF') },
          { label: 'File…', disabled: mode !== 'browse', action: ins('Insert File') }
        ];
      };
      const format = () => {
        const d = w && mode === 'layout' ? this.designers.get(w) : null;
        const one = d && d.selected()[0];
        const st = k => d && d.selected().length ? () => { d.snapshot(); d.selected().forEach(o => { o.style = Object.assign({}, o.style || {}); o.style[k] = !o.style[k]; }); d.paint(); } : null;
        const al = v => d && d.selected().length ? () => { d.snapshot(); d.selected().forEach(o => { o.style = Object.assign({}, o.style || {}, { align: v }); }); d.paint(); } : null;
        return [
          { label: 'Bold', key: K('Ctrl+Shift+B'), disabled: !d, action: st('bold') }, { label: 'Italic', key: K('Ctrl+Shift+I'), disabled: !d, action: st('italic') }, { label: 'Underline', key: K('Ctrl+Shift+U'), disabled: !d, action: st('underline') },
          '-',
          { label: 'Align Left', disabled: !d, action: al('left') }, { label: 'Center', disabled: !d, action: al('center') }, { label: 'Align Right', disabled: !d, action: al('right') },
          '-',
          { label: 'Conditional Formatting…', disabled: !one, action: () => d.condFormat(one) },
          { label: 'Set Script Triggers…', disabled: !one, action: () => d.objTriggers(one) },
          { label: 'Field/Control Setup…', disabled: !one || one.type !== 'field', action: () => d.fieldSetup(one) },
          { label: 'Button Setup…', disabled: !one || one.type !== 'button', action: () => d.buttonSetup(one) },
          { label: 'Portal Setup…', disabled: !one || one.type !== 'portal', action: () => d.portalSetup(one) },
          { label: 'Tab/Slide Control Setup…', disabled: !one || !one.tabs, action: () => d.tabSetup(one) },
          { label: 'Chart Setup…', disabled: !one || one.type !== 'chart', action: () => d.chartSetup(one).then(() => d.paint()) },
          { label: 'Web Viewer Setup…', disabled: !one || one.type !== 'webviewer', action: () => d.webViewerSetup(one).then(() => d.paint()) }
        ];
      };
      const records = () => [
        { label: 'New Record', key: K('Ctrl+N'), disabled: !has || !w.table, action: act(() => w.newRecord()) },
        { label: 'Duplicate Record', key: K('Ctrl+D'), disabled: !has || !w.current(), action: act(() => w.duplicateRecord()) },
        { label: 'Delete Record…', key: K('Ctrl+E'), disabled: !has || !w.current(), action: act(() => w.deleteRecord({ whole: true })) },
        { label: 'Delete Found Records…', disabled: !has || !w.foundRecords().length, action: act(() => w.deleteAll()) },
        '-',
        { label: 'Go to Record', disabled: !has, sub: [{ label: 'Next', key: K('Ctrl+↓'), action: act(() => w.goTo(w.index + 1)) }, { label: 'Previous', key: K('Ctrl+↑'), action: act(() => w.goTo(w.index - 1)) }, { label: 'Go to…', action: act(() => this.runStepNow(w, 'Go to Record/Request/Page', { which: 'calc', dialog: true })) }] },
        { label: 'Refresh Window', key: K('Ctrl+Shift+R'), disabled: !has, action: () => { w.file.touch(); w.render(); } },
        '-',
        { label: 'Show All Records', key: K('Ctrl+J'), disabled: !has, action: act(() => w.showAll()) },
        { label: 'Show Omitted Only', disabled: !has, action: act(() => w.showOmitted()) },
        { label: 'Omit Record', key: K('Ctrl+T'), disabled: !has || !w.current(), action: act(() => w.omit(1)) },
        { label: 'Omit Multiple…', key: K('Ctrl+Shift+T'), disabled: !has || !w.current(), action: act(() => this.runStepNow(w, 'Omit Multiple Records', { dialog: true })) },
        '-',
        { label: 'Modify Last Find', key: K('Ctrl+R'), disabled: !has, action: act(() => w.setMode('find', { restore: true })) },
        { label: 'Saved Finds', disabled: !has, sub: () => this.savedFindItems(w) },
        '-',
        { label: 'Sort Records…', key: K('Ctrl+S'), disabled: !has, action: act(() => this.sortFlow(w)) },
        { label: 'Unsort', disabled: !has, action: act(() => this.runStepNow(w, 'Unsort Records')) },
        '-',
        { label: 'Replace Field Contents…', key: K('Ctrl+='), disabled: !has, action: act(() => FM.dlg.replaceFieldContents(w, { dialog: true })) },
        { label: 'Relookup Field Contents', disabled: !has || !w.active || !w.active.key, action: act(() => this.runStepNow(w, 'Relookup Field Contents', { field: w.active.key, dialog: true })) },
        '-',
        { label: 'Revert Record…', disabled: !has || !w.isDirty(), action: act(async () => { if (await FM.confirm('Revert record to the last saved version?', { ok: 'Revert' })) await w.revert(); }) },
        { label: 'Save Record', key: K('Ctrl+Enter'), disabled: !has || !w.isDirty(), action: act(() => w.commit()) }
      ];
      const requests = () => [
        { label: 'Add New Request', key: K('Ctrl+N'), action: () => w.newRequest() },
        { label: 'Duplicate Request', key: K('Ctrl+D'), action: () => w.duplicateRequest() },
        { label: 'Delete Request', key: K('Ctrl+E'), action: () => w.deleteRequest() },
        '-',
        { label: 'Go to Request', sub: w.requests.map((r, i) => ({ label: 'Request ' + (i + 1) + (r.omit ? ' (omit)' : ''), checked: i === w.reqIndex, action: () => { w.reqIndex = i; w.render(); } })) },
        '-',
        { label: 'Show All Records', key: K('Ctrl+J'), action: act(() => w.showAll()) },
        { label: 'Perform Find', key: 'Enter', action: act(() => w.performFind()) },
        { label: 'Constrain Found Set', action: act(() => w.performFind(null, { how: 'constrain' })) },
        { label: 'Extend Found Set', action: act(() => w.performFind(null, { how: 'extend' })) },
        { label: 'Revert Request', action: () => { w.requests[w.reqIndex] = { omit: false, crit: {} }; w.render(); } },
        '-',
        { label: 'Saved Finds', sub: () => this.savedFindItems(w) }
      ];
      const layouts = () => {
        const d = this.designers.get(w);
        return [
          { label: 'Save Layout', key: K('Ctrl+S'), disabled: !d || !d.dirty, action: () => d.save() },
          { label: 'Revert Layout', disabled: !d || !d.dirty, action: async () => { if (await FM.confirm('Revert the layout to the last saved version?', { ok: 'Revert' })) { d.load(); d.paint(); } } },
          '-',
          { label: 'New Layout/Report…', disabled: !f.canCreateLayouts(), action: () => this.newLayoutFlow(w) },
          { label: 'Duplicate Layout', disabled: !f.canCreateLayouts(), action: async () => { await d.saveQuiet(); const c = FM.clone(w.layout); c.id = FM.uid('L'); c.name = FM.uniqueName(c.name + ' Copy', f.schema.layouts.map(l => l.name)); await f.saveSchema([{ op: 'upsert', coll: 'layouts', item: c }]); await w.setLayout(c.id); } },
          { label: 'Delete Layout…', action: async () => { if (f.schema.layouts.length < 2) return FM.alert('A file needs at least one layout.'); if (!(await FM.confirm('Permanently delete this layout?', { ok: 'Delete' }))) return; const id = w.layoutId; d.dirty = false; f.unlock(['layout:' + id]); await f.saveSchema([{ op: 'delete', coll: 'layouts', id }]); await w.setLayout(f.schema.layouts[0].id, { noTrigger: true }); } },
          '-',
          { label: 'Layout Setup…', action: () => d.layoutSetup() },
          { label: 'Part Setup…', action: () => d.partSetup() },
          { label: 'Set Tab Order…', action: () => d.tabOrder() },
          { label: 'Set Layout Script Triggers…', action: () => d.layoutTriggers() },
          '-',
          { label: 'Manage Layouts…', action: () => FM.dlg.manageLayouts(w) },
          { label: 'Go to Layout', sub: goLayouts }
        ];
      };
      const arrange = () => { const d = this.designers.get(w); return d.arrangeItems().concat(['-'], d.alignItems()); };
      const scripts = () => {
        const items = [{ label: 'Script Workspace…', key: K('Ctrl+Shift+S'), disabled: !has || minimal, action: () => FM.workspace.open(f) }, '-'];
        if (has) {
          const all = FM.orderedScripts(f);
          const build = parent => all.filter(s => (s.parent || '') === parent && (s.folder || (s.menu !== false && !s.separator && f.scriptAccess(s.id) !== 'none'))).map(s => s.folder ? { label: s.name, sub: build(s.id) } : { label: s.name, action: () => this.runner.run(s, '', { win: w }) }).filter(x => !x.sub || x.sub.length);
          const list = build('');
          items.push(...(list.length ? list : [{ label: '(no scripts)', disabled: true }]));
        }
        return items;
      };
      const tools = () => [
        { label: 'Script Debugger', checked: !!(this.runner.debugger && this.runner.debugger.active), disabled: !full, action: () => { if (this.runner.debugger && this.runner.debugger.active) { this.runner.debugger.active = false; FM.debuggerUI.close(); } else FM.debuggerUI.start(); } },
        { label: 'Data Viewer', disabled: !full, action: () => FM.dataViewer.open(this) },
        { label: 'Database Design Report…', disabled: !full, action: () => this.designReport(f) },
        { label: 'Custom Menus… (planned)', disabled: true },
        { label: 'Developer Utilities… (planned)', disabled: true },
        { label: 'Plug-ins… (planned)', disabled: true }
      ];
      const windowMenu = () => {
        const items = [
          { label: 'New Window', disabled: !has, action: act(() => this.newWindow(f, { name: w.name + ' - 2', layoutId: w.layoutId, copySet: w })) },
          { label: 'Minimize Window', disabled: !has, action: () => this.adjustWindow(w, 'minimize') },
          { label: 'Hide Window', disabled: !has, action: () => this.adjustWindow(w, 'hide') },
          { label: 'Show Window', disabled: !this.windows.some(x => x.hidden), sub: this.windows.filter(x => x.hidden).map(x => ({ label: x.name, action: () => this.adjustWindow(x, 'restore') })) },
          '-',
          { label: 'Tile Horizontally', action: () => this.arrangeWindows('tile_h') },
          { label: 'Tile Vertically', action: () => this.arrangeWindows('tile_v') },
          { label: 'Cascade Windows', action: () => this.arrangeWindows('cascade') },
          { label: 'Bring All to Front', action: () => this.arrangeWindows('front') },
          '-',
          { label: 'Launch Center', action: () => this.showLaunch() }
        ];
        if (this.windows.length) items.push('-');
        this.windows.forEach(x => items.push({ label: x.name + (x.hidden ? ' (hidden)' : ''), checked: x === w, action: () => this.focusWindow(x) }));
        return items;
      };
      const help = () => [
        { label: 'FileMaker Help', key: 'F1', action: () => FM.dlg.help() },
        { label: 'Keyboard Shortcuts', action: () => FM.dlg.help() },
        { label: 'Coming Soon (planned features)', action: () => FM.dlg.help() },
        '-',
        { label: 'About FileMaker', action: () => FM.dlg.about() }
      ];
      const out = [{ label: 'File', items: file }, { label: 'Edit', items: edit }, { label: 'View', items: view }, { label: 'Insert', items: insert }, { label: 'Format', items: format }];
      if (mode === 'find') out.push({ label: 'Requests', items: requests });
      else if (mode === 'layout') out.push({ label: 'Layouts', items: layouts }, { label: 'Arrange', items: arrange });
      else out.push({ label: 'Records', items: records });
      out.push({ label: 'Scripts', items: scripts }, { label: 'Tools', items: tools }, { label: 'Window', items: windowMenu }, { label: 'Help', items: help });
      return out;
    }
    savedFindItems(w) {
      const list = FM.dlg.getSavedFinds(w.file);
      return [{ label: 'Save Current Find…', action: () => FM.dlg.saveCurrentFind(w) }, { label: 'Edit Saved Finds…', action: () => FM.dlg.savedFinds(w) }, '-']
        .concat(list.length ? list.map(s => ({ label: s.name, action: () => this.act(w, async () => { if (s.layout && w.file.layout(s.layout) && s.layout !== w.layoutId) await w.setLayout(s.layout, { silent: true }); await w.performFind(s.requests); }) })) : [{ label: '(no saved finds)', disabled: true }]);
    }
    async runStepNow(w, name, p) { await this.runner.runAction({ kind: 'step', step: { id: 'm', s: name, p } }, w); }

    // ═════════════════════════════════════════════════════════════════════
    // keyboard
    // ═════════════════════════════════════════════════════════════════════
    onKey(e) {
      if (FM.modalOpen() || FM.workspace.el && !FM.workspace.el.classList.contains('fm-ws-min')) return;
      const w = this.active; if (!w || !w.el) { if (FM.cmd(e) && e.key.toLowerCase() === 'o') { e.preventDefault(); this.showLaunch(); } return; }
      this.modifiers = (e.shiftKey ? 1 : 0) + (e.ctrlKey ? 4 : 0) + (e.altKey ? 8 : 0) + (e.metaKey ? 16 : 0);
      if (e.key === 'F1') { e.preventDefault(); FM.dlg.help(); return; }
      if (w.mode === 'layout') {
        const d = this.designers.get(w);
        if (d && !FM.cmd(e) || (d && ['z', 'y', 'c', 'x', 'v', 'd', 'a', 'g', 's'].includes(e.key.toLowerCase()))) {
          if (FM.cmd(e) && ['b', 'f', 'u'].includes(e.key.toLowerCase())) { /* mode keys below */ }
          else if (d && d.onKey(e)) { e.preventDefault(); return; }
        }
      }
      const inField = e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT' || e.target.isContentEditable);
      if (!FM.cmd(e)) {
        if (w.mode === 'find' && e.key === 'Enter' && !inField) { e.preventDefault(); this.act(w, () => w.performFind()); }
        if (w.mode === 'browse' && !inField && !e.altKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp') && w.view !== 'form') { e.preventDefault(); this.act(w, () => w.goTo(w.index + (e.key === 'ArrowDown' ? 1 : -1))); }
        if (w.mode === 'preview' && !inField && (e.key === 'ArrowDown' || e.key === 'ArrowRight' || e.key === 'PageDown')) { e.preventDefault(); w.previewPage = Math.min((w.previewPages || 1) - 1, (w.previewPage || 0) + 1); w.previewScrollTo = true; w.render(); }
        if (w.mode === 'preview' && !inField && (e.key === 'ArrowUp' || e.key === 'ArrowLeft' || e.key === 'PageUp')) { e.preventDefault(); w.previewPage = Math.max(0, (w.previewPage || 0) - 1); w.previewScrollTo = true; w.render(); }
        return;
      }
      const k = e.key.toLowerCase();
      const run = fn => { e.preventDefault(); e.stopPropagation(); this.act(w, fn); };
      if (e.shiftKey && k === 'd') return run(() => FM.dlg.manageDatabase(w.file));
      if (e.shiftKey && k === 's') return run(() => FM.workspace.open(w.file));
      if (e.shiftKey && k === 'r') return run(async () => { w.file.touch(); w.render(); });
      if (e.shiftKey && k === 't') return run(() => this.runStepNow(w, 'Omit Multiple Records', { dialog: true }));
      if (e.shiftKey && e.key !== 'Enter') return;
      switch (k) {
        case 'b': return run(() => w.setMode('browse'));
        case 'f': return run(() => w.setMode('find'));
        case 'l': return run(() => w.layout && w.file.layoutAccess(w.layoutId) === 'modify' ? w.setMode('layout') : FM.alert('You do not have privileges to modify this layout.'));
        case 'u': return run(() => w.setMode('preview'));
        case 'p': return run(() => this.printFlow(w));
        case 'o': return run(() => this.showLaunch());
        case 'w': return run(() => this.closeWindow(w));
      }
      if (w.mode === 'layout') return;
      if (inField && ['c', 'x', 'v', 'a', 'z', 'y'].includes(k)) return;
      if (w.mode === 'find') {
        switch (k) {
          case 'n': return run(() => w.newRequest());
          case 'd': return run(() => w.duplicateRequest());
          case 'e': return run(() => w.deleteRequest());
          case 'j': return run(() => w.showAll());
          case 'enter': return run(() => w.performFind());
        }
        return;
      }
      switch (k) {
        case 'n': return run(() => w.newRecord());
        case 'd': return run(() => w.duplicateRecord());
        case 'e': return run(() => w.deleteRecord({ whole: true }));
        case 'j': return run(() => w.showAll());
        case 't': return run(() => w.omit(1));
        case 'r': return run(() => w.setMode('find', { restore: true }));
        case 's': return run(() => this.sortFlow(w));
        case 'arrowdown': return run(() => w.goTo(w.index + 1));
        case 'arrowup': return run(() => w.goTo(w.index - 1));
        case 'enter': { const a = document.activeElement; if (a && w.el.contains(a)) a.blur(); return run(async () => { await new Promise(r => setTimeout(r, 0)); await (this.blurring || Promise.resolve()); await w.commit(); }); }
        case '=': return run(() => FM.dlg.replaceFieldContents(w, { dialog: true }));
        case '-': if (inField) return run(() => this.runStepNow(w, 'Insert Current Date')); return;
        case ';': if (inField) return run(() => this.runStepNow(w, 'Insert Current Time')); return;
      }
    }

    // ═════════════════════════════════════════════════════════════════════
    // windows
    // ═════════════════════════════════════════════════════════════════════
    async newWindow(file, o) {
      o = o || {};
      const w = new FM.FMWindow(this, file, o);
      w.closable = o.closable !== false;
      if (o.copySet) { o.copySet.sets.forEach((s, k) => w.sets.set(k, FM.clone(s))); w.view = o.copySet.view; }
      if (o.layoutId) { try { await w.setLayout(o.layoutId, { silent: true, noTrigger: true }); } catch (e) { /* keep default */ } }
      file.windows.push(w);
      this.windows.push(w);
      this.mountWindow(w, o);
      this.focusWindow(w);
      w.render();
      await this.trigger(w, 'OnWindowOpen');
      await this.trigger(w, 'OnLayoutEnter');
      await this.trigger(w, 'OnRecordLoad');
      return w;
    }
    mountWindow(w, o) {
      const el = h('div', { class: 'fm-win fm-win-' + w.style, dataset: { win: w.id } });
      const title = h('div', { class: 'fm-win-title' });
      const toolbar = h('div', { class: 'fm-toolbar' });
      const layoutbar = h('div', { class: 'fm-layoutbar' });
      const content = h('div', { class: 'fm-content' });
      const status = h('div', { class: 'fm-statusline' });
      el.append(title, toolbar, layoutbar, content, status);
      w.el = el; w.parts = { title, toolbar, layoutbar, content, status };
      const firstDoc = !this.windows.some(x => x !== w && x.style === 'document' && x.maximized);
      w.maximized = w.style === 'document' && (o.w == null && o.h == null) && firstDoc;
      if (w.style === 'card') {
        const back = h('div', { class: 'fm-card-back' });
        back.appendChild(el); w.cardBack = back;
        (o.parent && o.parent.el ? this.desktop : this.desktop).appendChild(back);
      } else this.desktop.appendChild(el);
      el.addEventListener('mousedown', () => { if (this.active !== w) this.focusWindow(w); }, true);
      title.addEventListener('mousedown', e => this.startWindowDrag(e, w));
      title.addEventListener('dblclick', e => { if (e.target.closest('button')) return; if (w.style === 'document') { w.maximized = !w.maximized; this.placeWindow(w); } });
      const grip = h('div', { class: 'fm-win-grip' });
      grip.addEventListener('mousedown', e => this.startWindowResize(e, w));
      el.appendChild(grip);
      if (w.geom.x == null) { const n = this.windows.filter(x => !x.maximized).length; w.geom.x = 40 + (n % 6) * 28; w.geom.y = 30 + (n % 6) * 28; }
      if (w.style === 'card') { w.geom.w = o.w || Math.min(720, (w.layout ? w.layout.width : 600) + 40); w.geom.h = o.h || Math.min(innerHeight - 120, (w.layout ? FM.layoutHeight(w.layout) : 400) + 60); }
      this.placeWindow(w);
    }
    placeWindow(w) {
      const el = w.el; if (!el) return;
      el.classList.toggle('maximized', !!w.maximized);
      el.classList.toggle('hidden', !!w.hidden);
      if (w.cardBack) w.cardBack.style.display = w.hidden ? 'none' : '';
      if (w.maximized) { el.style.left = el.style.top = el.style.width = el.style.height = ''; return; }
      const dw = this.desktop.clientWidth || innerWidth, dh = this.desktop.clientHeight || innerHeight;
      const g = w.geom;
      if (w.style === 'card') { el.style.width = Math.min(g.w, dw - 20) + 'px'; el.style.height = Math.min(g.h, dh - 20) + 'px'; el.style.left = ''; el.style.top = ''; return; }
      el.style.width = Math.min(g.w, dw) + 'px'; el.style.height = Math.min(g.h, dh) + 'px';
      el.style.left = FM.clamp(g.x, 0, Math.max(0, dw - 120)) + 'px'; el.style.top = FM.clamp(g.y, 0, Math.max(0, dh - 40)) + 'px';
    }
    startWindowDrag(e, w) {
      if (e.button !== 0 || e.target.closest('button') || w.maximized || w.style === 'card') return;
      const sx = e.clientX, sy = e.clientY, gx = w.geom.x, gy = w.geom.y;
      const mv = ev => { w.geom.x = gx + ev.clientX - sx; w.geom.y = gy + ev.clientY - sy; this.placeWindow(w); };
      const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); };
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
      e.preventDefault();
    }
    startWindowResize(e, w) {
      if (w.maximized) return;
      const sx = e.clientX, sy = e.clientY, gw = w.geom.w, gh = w.geom.h;
      const mv = ev => { w.geom.w = Math.max(320, gw + ev.clientX - sx); w.geom.h = Math.max(200, gh + ev.clientY - sy); this.placeWindow(w); };
      const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); this.trigger(w, 'OnLayoutSizeChange'); };
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
      e.preventDefault(); e.stopPropagation();
    }
    focusWindow(w) {
      if (!w) return;
      if (w.hidden) { w.hidden = false; this.placeWindow(w); }
      this.active = w;
      this.windows.forEach(x => x.el && x.el.classList.toggle('active', x === w));
      // floating and card windows stay above document windows
      const order = this.windows.slice().sort((a, b) => rank(a) - rank(b) || (a === w) - (b === w));
      order.forEach((x, i) => { const n = x.cardBack || x.el; if (n) n.style.zIndex = 10 + i * 2 + (x.style === 'floating' ? 200 : x.style === 'card' ? 400 : 0); });
      this.hideLaunch();
      this.renderMenubar();
      this.renderChrome(w);
      function rank(x) { return x.style === 'card' ? 2 : x.style === 'floating' ? 1 : 0; }
    }
    renderWindowList() { this.renderMenubar(); }
    async closeWindow(w, o) {
      if (!w) return;
      o = o || {};
      if (w.closable === false && !o.force) { FM.toast('This window cannot be closed.'); return false; }
      if (!o.force) {
        if (w.mode === 'layout' && !(await this.leaveLayoutMode(w))) return false;
        if (!(await w.commit({ rt: o.rt }))) return false;
        if (!(await this.trigger(w, 'OnWindowClose'))) return false;
        const last = this.windows.filter(x => x.file === w.file).length === 1;
        if (last && !(await this.trigger(w, 'OnLastWindowClose'))) return false;
      }
      if (w.timers) clearInterval(w.timers);
      (w.cardBack || w.el).remove();
      this.windows = this.windows.filter(x => x !== w);
      w.file.windows = w.file.windows.filter(x => x !== w);
      this.designers.delete(w);
      w.el = null;
      if (!w.file.windows.length) await this.closeFile(w.file, { noWindows: true, force: o.force });
      this.active = null;
      const next = this.windows.filter(x => !x.hidden).slice(-1)[0];
      if (next) this.focusWindow(next); else { this.renderMenubar(); this.showLaunch(); }
      return true;
    }
    adjustWindow(w, how) {
      if (how === 'maximize' || (how === 'fit' && w.style === 'document')) { w.maximized = how === 'maximize'; if (how === 'fit' && w.layout) { w.geom.w = (w.layout.width || 800) + 40; w.geom.h = Math.min(innerHeight - 80, FM.layoutHeight(w.layout) + 140); w.maximized = false; } }
      else if (how === 'restore') { w.hidden = false; w.maximized = false; }
      else if (how === 'minimize' || how === 'hide') { w.hidden = true; const next = this.windows.find(x => x !== w && !x.hidden); if (next) this.focusWindow(next); }
      this.placeWindow(w);
    }
    moveWindow(w, g) { ['x', 'y', 'w', 'h'].forEach(k => { if (g[k] != null) w.geom[k] = g[k]; }); w.maximized = false; this.placeWindow(w); }
    arrangeWindows(how) {
      const ws = this.windows.filter(w => !w.hidden && w.style !== 'card');
      const dw = this.desktop.clientWidth, dh = this.desktop.clientHeight;
      ws.forEach((w, i) => {
        w.maximized = false;
        if (how === 'tile_h') Object.assign(w.geom, { x: 0, y: Math.round(dh / ws.length * i), w: dw, h: Math.round(dh / ws.length) });
        else if (how === 'tile_v') Object.assign(w.geom, { x: Math.round(dw / ws.length * i), y: 0, w: Math.round(dw / ws.length), h: dh });
        else if (how === 'cascade') Object.assign(w.geom, { x: 30 + i * 30, y: 20 + i * 30, w: Math.min(dw - 80, 900), h: Math.min(dh - 80, 620) });
        this.placeWindow(w);
      });
      if (how === 'front' && this.active) this.focusWindow(this.active);
    }

    // ═════════════════════════════════════════════════════════════════════
    // window chrome: title bar, status toolbar, layout bar, status line
    // ═════════════════════════════════════════════════════════════════════
    renderChrome(w) {
      if (!w || !w.el) return;
      const p = w.parts; const f = w.file;
      // title bar
      p.title.innerHTML = '';
      p.title.append(h('span', { class: 'fm-win-icon', style: { background: (f.schema.fileOptions || {}).color || '#7a2bd8' }, text: 'FM' }), h('span', { class: 'fm-win-name', text: w.name + (w.name !== f.name ? ' — ' + f.name : '') }), h('span', { class: 'fm-win-mode', text: '(' + { browse: 'Browse', find: 'Find', layout: 'Layout', preview: 'Preview' }[w.mode] + ')' }), h('div', { class: 'fm-flex1' }));
      if (w.style !== 'card') {
        p.title.append(h('button', { class: 'fm-wbtn', title: 'Minimize', html: FM.icon('minus', 12), onclick: () => this.adjustWindow(w, 'minimize') }));
        if (w.style === 'document') p.title.append(h('button', { class: 'fm-wbtn', title: w.maximized ? 'Restore' : 'Maximize', html: FM.icon(w.maximized ? 'copy' : 'expand', 12), onclick: () => { w.maximized = !w.maximized; this.placeWindow(w); this.renderChrome(w); } }));
      }
      if (w.closable !== false) p.title.append(h('button', { class: 'fm-wbtn close', title: 'Close Window', html: FM.icon('x', 12), onclick: () => this.closeWindow(w) }));
      p.toolbar.style.display = w.toolbar ? '' : 'none';
      p.layoutbar.style.display = w.toolbar ? '' : 'none';
      p.toolbar.innerHTML = ''; p.layoutbar.innerHTML = '';
      if (w.toolbar) {
        if (w.mode === 'browse') this.browseToolbar(w);
        else if (w.mode === 'find') this.findToolbar(w);
        else if (w.mode === 'preview') this.previewToolbar(w);
        else this.layoutToolbar(w);
        this.layoutBar(w);
      }
      // status line
      p.status.innerHTML = '';
      const ed = w.current() && f.editing.get(w.current().id);
      p.status.append(...[
        h('select', { class: 'fm-zoomsel', title: 'Zoom', onchange: ev => { w.zoom = +ev.target.value; w.render(); } }, [25, 50, 75, 100, 125, 150, 200, 300, 400].map(z => h('option', { value: z / 100, text: z + '%', selected: Math.abs(w.zoom - z / 100) < 0.01 }))),
        h('span', { class: 'fm-st-mode', text: { browse: 'Browse', find: 'Find', layout: 'Layout', preview: 'Preview' }[w.mode] }),
        ed ? h('span', { class: 'fm-st-badge', text: ed.isNew ? 'New record (not saved yet)' : 'Editing — record locked for others' }) : null,
        this.runner.busy ? h('span', { class: 'fm-st-badge run', text: 'Script running' + (this.runner.current && this.runner.current.frame ? ': ' + this.runner.current.frame.script.name : '') }) : null,
        h('div', { class: 'fm-flex1' }),
        f.offline ? h('span', { class: 'fm-st-badge bad', text: 'Host not reachable — retrying' }) : h('span', { class: 'fm-st-net', title: 'Connected to the host', html: FM.icon('share', 12) + ' ' + FM.esc(location.host) })].filter(Boolean));
      if (this.active === w) this.renderMenubar();
    }
    tb(label, icon, action, o) {
      o = o || {};
      const b = h('button', { class: 'fm-tbtn' + (o.on ? ' on' : ''), title: o.title || label, disabled: !!o.disabled }, h('span', { class: 'fm-tbtn-ic', html: FM.icon(icon, 20) }), h('span', { class: 'fm-tbtn-l', text: label }));
      b.addEventListener('click', action);
      return b;
    }
    book(prev, next, value, total, onGo, label, extra) {
      const box = h('div', { class: 'fm-book' });
      const inp = h('input', { class: 'fm-book-num', value: String(value), title: 'Current ' + label.toLowerCase() });
      inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); onGo(Math.floor(+inp.value) - 1); } });
      inp.addEventListener('change', () => onGo(Math.floor(+inp.value) - 1));
      box.append(h('div', { class: 'fm-book-btns' }, h('button', { class: 'fm-bookbtn', title: 'Previous ' + label.toLowerCase(), html: FM.icon('prev', 16), disabled: !total || value <= 1, onclick: prev }), h('button', { class: 'fm-bookbtn', title: 'Next ' + label.toLowerCase(), html: FM.icon('next', 16), disabled: !total || value >= total, onclick: next })),
        h('div', { class: 'fm-book-info' }, h('div', { class: 'fm-book-row' }, inp, h('span', { class: 'fm-book-total', text: total + ' ' + (extra ? '' : '') })), h('div', { class: 'fm-book-sub' }, extra || label)));
      if (total > 1) {
        const slider = h('input', { type: 'range', class: 'fm-book-slider', min: 1, max: total, value });
        slider.addEventListener('change', () => onGo(+slider.value - 1));
        box.appendChild(slider);
      }
      return box;
    }
    browseToolbar(w) {
      const t = w.parts.toolbar; const s = w.set_();
      const n = w.foundRecords().length, tot = w.totalCount();
      const sortTxt = s.sort && s.sort.length ? (s.semi ? 'Semi-sorted' : 'Sorted') : 'Unsorted';
      t.appendChild(this.book(() => this.act(w, () => w.goTo(w.index - 1)), () => this.act(w, () => w.goTo(w.index + 1)), n ? w.index + 1 : 0, n, i => this.act(w, () => w.goTo(i)), 'Records', n === tot ? tot + ' Total (' + sortTxt + ')' : n + ' Found of ' + tot + ' (' + sortTxt + ')'));
      const canNew = w.table && w.file.canCreate(w.table.id);
      t.append(this.tb('Show All', 'showall', () => this.act(w, () => w.showAll())), this.tb('New Record', 'plus', () => this.act(w, () => w.newRecord()), { disabled: !canNew }), this.tb('Delete Record', 'trash', () => this.act(w, () => w.deleteRecord()), { disabled: !w.current() }), this.tb('Find', 'search', () => this.act(w, () => w.setMode('find'))), this.tb('Sort', 'sort', () => this.act(w, () => this.sortFlow(w))), this.tb('Share', 'share', () => FM.dlg.sharing(w.file)));
      t.appendChild(h('div', { class: 'fm-flex1' }));
      const qf = h('input', { class: 'fm-quickfind', type: 'search', placeholder: 'Quick Find', value: w.quickFind || '' });
      qf.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); this.act(w, () => w.quickFindRun(qf.value)); } });
      t.appendChild(h('div', { class: 'fm-qf' }, h('span', { html: FM.icon('search', 14) }), qf));
      if (this.runner.pausedFrame) t.appendChild(this.tb('Continue', 'play', () => this.runner.pausedFrame.resume(), { on: true }));
    }
    findToolbar(w) {
      const t = w.parts.toolbar;
      const n = w.requests.length;
      t.appendChild(this.book(() => { w.reqIndex = Math.max(0, w.reqIndex - 1); w.render(); }, () => { w.reqIndex = Math.min(n - 1, w.reqIndex + 1); w.render(); }, w.reqIndex + 1, n, i => { w.reqIndex = FM.clamp(i, 0, n - 1); w.render(); }, 'Requests', n + ' Total'));
      const paused = this.runner.pausedFrame && this.runner.pausedFrame.paused && this.runner.pausedFrame.paused.find;
      t.append(this.tb('New Request', 'plus', () => w.newRequest()), this.tb('Delete Request', 'trash', () => w.deleteRequest()),
        this.tb('Perform Find', 'search', () => { if (paused) this.runner.pausedFrame.resume('find'); else this.act(w, () => w.performFind()); }, { on: true }),
        this.tb('Cancel Find', 'x', () => this.act(w, () => w.setMode('browse'))),
        this.tb('Saved Finds', 'star', ev => { const r = ev.currentTarget.getBoundingClientRect(); FM.popupMenu(this.savedFindItems(w), r.left, r.bottom); }));
      t.appendChild(h('div', { class: 'fm-flex1' }));
      const req = w.requests[w.reqIndex];
      const inc = h('input', { type: 'radio', name: 'mr' + w.id, checked: !req.omit }), om = h('input', { type: 'radio', name: 'mr' + w.id, checked: !!req.omit });
      inc.onchange = () => { req.omit = false; w.render(); }; om.onchange = () => { req.omit = true; w.render(); };
      t.appendChild(h('div', { class: 'fm-tb-group' }, h('span', { class: 'fm-muted small', text: 'Matching records:' }), h('label', { class: 'fm-check' }, inc, h('span', { text: 'Include' })), h('label', { class: 'fm-check' }, om, h('span', { text: 'Omit' }))));
      const ops = h('button', { class: 'fm-btn small', text: 'Insert: Operators ▾' });
      ops.addEventListener('mousedown', e => e.preventDefault());
      ops.onclick = e => { const r = e.currentTarget.getBoundingClientRect(); const target = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.fmKey ? document.activeElement : (w.lastFindInput || null); FM.popupMenu(FM.FIND_OPS.map(([v, l]) => ({ label: l, action: () => { const el = target || w.el.querySelector('.fm-content input[data-fm-key], .fm-content textarea[data-fm-key]'); if (!el) return; el.focus(); el.setRangeText(v, el.selectionStart, el.selectionEnd, 'end'); el.dispatchEvent(new Event('input')); } })), r.left, r.bottom); };
      t.appendChild(ops);
    }
    previewToolbar(w) {
      const t = w.parts.toolbar;
      const n = w.previewPages || 1, i = (w.previewPage || 0) + 1;
      t.appendChild(this.book(() => { w.previewPage = Math.max(0, i - 2); w.previewScrollTo = true; w.render(); }, () => { w.previewPage = Math.min(n - 1, i); w.previewScrollTo = true; w.render(); }, i, n, k => { w.previewPage = FM.clamp(k, 0, n - 1); w.previewScrollTo = true; w.render(); }, 'Pages', n + ' pages'));
      t.append(this.tb('Print', 'print', () => this.print(w)), this.tb('Save as PDF', 'download', () => this.print(w)), this.tb('Page Setup', 'gear', () => FM.dlg.pageSetup(w.file)), this.tb('Exit Preview', 'x', () => this.act(w, () => w.setMode('browse'))));
      if (this.runner.pausedFrame) t.appendChild(this.tb('Continue', 'play', () => this.runner.pausedFrame.resume(), { on: true }));
      t.appendChild(h('div', { class: 'fm-flex1' }));
      t.appendChild(h('span', { class: 'fm-muted small', text: w.foundRecords().length + ' records · ' + ((w.file.schema.fileOptions.pageSetup || {}).paper || 'letter') }));
    }
    layoutToolbar(w) {
      const t = w.parts.toolbar; const d = this.designerFor(w);
      const tools = [['pointer', 'pointer', 'Selection'], ['text', 'text', 'Text'], ['line', 'line', 'Line'], ['rect', 'rect', 'Rectangle'], ['roundrect', 'roundrect', 'Rounded Rectangle'], ['oval', 'oval', 'Oval'], ['field', 'field', 'Field'], ['button', 'button', 'Button'], ['buttonbar', 'buttonbar', 'Button Bar'], ['popover', 'popover', 'Popover Button'], ['tab', 'tab', 'Tab Control'], ['slide', 'slide', 'Slide Control'], ['portal', 'portal', 'Portal'], ['webviewer', 'web', 'Web Viewer'], ['chart', 'chart', 'Chart'], ['image', 'image', 'Picture']];
      const box = h('div', { class: 'fm-tools' });
      tools.forEach(([k, ic, l]) => box.appendChild(h('button', { class: 'fm-toolbtn' + (d.tool === k ? ' on' : ''), title: l, html: FM.icon(ic, 18), onclick: () => { d.tool = k; this.renderChrome(w); } })));
      const fc = h('button', { class: 'fm-toolbtn', title: 'Field/Control', html: FM.icon('down', 14) });
      fc.onclick = e => { const r = e.currentTarget.getBoundingClientRect(); FM.popupMenu([['field', 'Edit Box'], ['dropdown', 'Drop-down List'], ['popup', 'Pop-up Menu'], ['checkbox', 'Checkbox Set'], ['radio', 'Radio Button Set'], ['calendar', 'Drop-down Calendar']].map(([v, l]) => ({ label: l, checked: d.tool === v, action: () => { d.tool = v; this.renderChrome(w); } })), r.left, r.bottom); };
      box.insertBefore(fc, box.children[7]);
      t.append(box, h('div', { class: 'fm-flex1' }),
        this.tb('Save Layout', 'check', () => d.save(), { disabled: !d.dirty, on: d.dirty }),
        this.tb('Undo', 'prev', () => d.undo(), { disabled: !d.undoStack.length }),
        this.tb('Exit Layout', 'x', () => this.act(w, () => w.setMode('browse'))));
    }
    layoutBar(w) {
      const b = w.parts.layoutbar; const f = w.file;
      const sel = h('select', { class: 'fm-layoutsel', title: 'Layout' });
      f.orderedLayouts().forEach(l => {
        if (l.separator) { sel.appendChild(h('option', { disabled: true, text: '────────' })); return; }
        if (l.folder) return;
        if ((l.hidden && l.id !== w.layoutId && w.mode !== 'layout') || f.layoutAccess(l.id) === 'none') return;
        sel.appendChild(h('option', { value: l.id, text: l.name, selected: l.id === w.layoutId }));
      });
      sel.addEventListener('change', () => this.act(w, async () => { const ok = await w.setLayout(sel.value); if (!ok) sel.value = w.layoutId; }));
      b.append(h('span', { class: 'fm-lb-label', text: 'Layout:' }), sel);
      if (w.mode === 'layout') {
        const d = this.designerFor(w);
        b.append(h('button', { class: 'fm-btn small', text: 'New Layout/Report…', onclick: () => this.newLayoutFlow(w) }), h('button', { class: 'fm-btn small', text: 'Layout Setup…', onclick: () => d.layoutSetup() }), h('button', { class: 'fm-btn small', text: 'Part Setup…', onclick: () => d.partSetup() }), h('button', { class: 'fm-btn small', text: 'Manage Layouts…', onclick: () => FM.dlg.manageLayouts(w) }));
        b.appendChild(h('div', { class: 'fm-flex1' }));
        b.appendChild(h('span', { class: 'fm-muted small', text: d.dirty ? 'Unsaved changes' : 'Saved' }));
        return;
      }
      const views = (w.layout && w.layout.views) || {};
      const vb = h('div', { class: 'fm-viewas' }, h('span', { class: 'fm-lb-label', text: 'View As:' }), ...['form', 'list', 'table'].map(v => h('button', { class: 'fm-vbtn' + (w.view === v ? ' on' : ''), title: 'View as ' + v[0].toUpperCase() + v.slice(1), disabled: views[v] === false || w.mode !== 'browse', html: FM.icon(v, 16), onclick: () => this.act(w, () => w.setView(v)) })));
      b.append(vb, h('button', { class: 'fm-btn small' + (w.mode === 'preview' ? ' on' : ''), text: 'Preview', onclick: () => this.act(w, () => w.setMode(w.mode === 'preview' ? 'browse' : 'preview')) }));
      b.appendChild(h('div', { class: 'fm-flex1' }));
      if (w.layout && f.layoutAccess(w.layoutId) === 'modify') b.appendChild(h('button', { class: 'fm-btn small', html: FM.icon('layout', 14) + ' Edit Layout', onclick: () => this.act(w, () => w.setMode('layout')) }));
    }
    renderPausedBar(rt) {
      const bar = this.pausebar; bar.innerHTML = '';
      bar.classList.toggle('on', !!rt);
      if (!rt) return;
      bar.append(h('span', { html: FM.icon('pause', 14) }), h('span', { text: ' Script paused: ' + (rt.frame ? rt.frame.script.name : '') + (rt.paused && rt.paused.find ? ' — enter find criteria, then Continue' : '') }), h('button', { class: 'fm-btn small primary', text: 'Continue', onclick: () => rt.resume(rt.paused && rt.paused.find ? 'find' : 'continue') }), h('button', { class: 'fm-btn small', text: 'Cancel', onclick: () => { rt.halted = true; rt.resume('cancel'); } }));
    }

    // ═════════════════════════════════════════════════════════════════════
    // layout mode
    // ═════════════════════════════════════════════════════════════════════
    designerFor(w, reload) {
      let d = this.designers.get(w);
      if (!d) { d = new FM.Designer(this, w); this.designers.set(w, d); }
      else if (reload || d.layoutId !== w.layoutId) d.load();
      return d;
    }
    async enterLayoutMode(w) {
      if (!w.layout) { await this.newLayoutFlow(w); return !!w.layout; }
      if (w.file.layoutAccess(w.layoutId) !== 'modify') { await FM.alert('Your privileges do not allow modifying this layout.', { icon: 'stopsign' }); return false; }
      const lk = await w.file.lockKey('layout:' + w.layoutId);
      if (!lk.ok) { await FM.alert('This layout is being modified by "' + (lk.holder || 'another user') + '". Try again later.', { icon: 'stopsign' }); return false; }
      w.lockedLayout = w.layoutId;
      this.designerFor(w, true);
      return true;
    }
    async leaveLayoutMode(w) {
      const d = this.designers.get(w);
      if (d && !(await d.leave())) return false;
      if (w.lockedLayout) { w.file.unlock(['layout:' + w.lockedLayout]); w.lockedLayout = null; }
      this.designers.delete(w);
      return true;
    }
    async newLayoutFlow(w) {
      const d = this.designers.get(w);
      if (d && !(await d.saveQuiet())) return;
      const lay = await FM.design.newLayoutAssistant(w);
      if (!lay) return;
      if (w.mode === 'layout') { if (w.lockedLayout) w.file.unlock(['layout:' + w.lockedLayout]); this.designers.delete(w); await w.setLayout(lay.id, { silent: true }); await w.file.lockKey('layout:' + lay.id); w.lockedLayout = lay.id; this.designerFor(w, true); w.render(); }
      else { await w.setLayout(lay.id, { silent: true }); w.mode = 'browse'; w.render(); }
    }

    // ═════════════════════════════════════════════════════════════════════
    // events from files
    // ═════════════════════════════════════════════════════════════════════
    recordsChanged(file, ids, remote) {
      file.windows.forEach(w => { if (w.mode !== 'layout') { if (remote) w.refresh(); else w.refresh(); } });
      if (FM.dataViewer.visible) FM.dataViewer.refresh();
    }
    schemaChanged(file) {
      file.windows.forEach(w => {
        if (!w.layout || file.layoutAccess(w.layoutId) === 'none') { const id = w.defaultLayout(); if (id) { w.layoutId = id; w.view = (file.layout(id).view) || 'form'; } }
        if (w.mode === 'layout') { const d = this.designers.get(w); if (d && !d.dirty) d.load(); }
        w.render();
      });
      if (FM.workspace.el && FM.workspace.file === file && !FM.workspace.dirty) FM.workspace.render();
      this.renderMenubar();
    }
    fileChanged(file) { FM.api('GET', '/files').then(r => { const me = r.files.find(x => x.id === file.id); if (me) { file.name = me.name; file.windows.forEach(w => this.renderChrome(w)); } }).catch(() => { }); }
    async fileLost(file, msg, kicked) {
      if (file.lost) return; file.lost = true;
      file.stopSync();
      for (const w of file.windows.slice()) await this.closeWindow(w, { force: true });
      this.files.delete(file.id);
      await FM.alert((kicked ? '' : 'The file "' + file.name + '" was closed: ') + msg, { icon: 'stopsign' });
      this.showLaunch();
    }
    offline(file, off) { if (!!file.offline !== off) { file.offline = off; file.windows.forEach(w => this.renderChrome(w)); } }

    // ═════════════════════════════════════════════════════════════════════
    // triggers and buttons
    // ═════════════════════════════════════════════════════════════════════
    triggerSpec(w, name, obj) {
      if (!w || !w.file) return null;
      const fileTrig = /^On(First|Last)?Window/.test(name);
      const src = fileTrig ? ((w.file.schema.fileOptions || {}).triggers || {}) : obj ? (obj.triggers || {}) : ((w.layout || {}).triggers || {});
      const t = src[name];
      if (!t || !t.script) return null;
      if (!fileTrig) { if (w.mode === 'find' && !t.find) return null; if ((w.mode === 'browse' || w.mode === 'preview') && t.browse === false) return null; if (w.mode === 'layout') return null; }
      return t;
    }
    hasTrigger(w, name, obj) { return !!this.triggerSpec(w, name, obj); }
    async trigger(w, name, obj) {
      const t = this.triggerSpec(w, name, obj);
      if (!t) return true;
      if (this.runner.busy && !this.runner.pausedFrame) return true;
      const s = w.file.script(t.script);
      if (!s) return true;
      let param = '';
      if (t.param) { try { param = w.file.evaluate(t.param, w.ctx(), true); } catch (e) { param = '?'; } }
      const r = await this.runner.run(s, param, { win: w, trigger: name });
      if (!r || !PRE.has(name)) return true;
      if (r.result !== '' && r.result != null && !V.bool(r.result) && V.text(r.result).toLowerCase() !== 'true') return false;
      return true;
    }
    async runButton(w, o, ctx) {
      const a = o.action;
      if (!a || a.kind === 'none') return;
      if (w.mode === 'browse' || w.mode === 'preview') {
        const act = document.activeElement; if (act && w.el.contains(act) && act.blur && act.dataset && act.dataset.fmKey) { act.blur(); await new Promise(r => setTimeout(r, 0)); await (this.blurring || Promise.resolve()); }
      }
      await this.runner.runAction(a, w, ctx);
    }
    async act(w, fn) {
      try { return await fn(); }
      catch (e) {
        if (e instanceof FMError) { if (e.code !== 1) await FM.alert(e.message, { icon: e.code === 401 ? 'info' : 'warn' }); return; }
        if (e instanceof FM.HostError) { await FM.alert(e.message, { icon: 'warn' }); return; }
        console.error(e);
        await FM.alert('Something went wrong: ' + (e && e.message ? e.message : e), { icon: 'warn' });
      }
    }
    onFrameMessage(e) {
      const d = e.data;
      if (!d || !d.fmWebViewer) return;
      const w = this.windows.find(x => x.el && [...x.el.querySelectorAll('iframe')].some(fr => fr.contentWindow === e.source));
      if (!w) return;
      const s = w.file.scriptByName(String(d.script || ''));
      if (!s) { FM.toast('Web viewer asked for a script that does not exist: ' + d.script, 'warn'); return; }
      this.runner.run(s, d.param == null ? '' : String(d.param), { win: w });
    }
    async openFmpUrl(url) {
      const m = String(url).match(/^fmp:\/\/(?:[^/]*\/)?([^?]+)(?:\?(.*))?$/i);
      if (!m) throw new FMError(1630);
      const name = decodeURIComponent(m[1]).replace(/\.fmp12$/i, '');
      const q = new URLSearchParams(m[2] || '');
      const list = await FM.api('GET', '/files');
      const f = list.files.find(x => x.name.toLowerCase() === name.toLowerCase());
      if (!f) throw new FMError(100);
      const file = await this.openFile(f.id);
      if (!file) return;
      const sname = q.get('script');
      if (sname) { const s = file.scriptByName(sname); if (s) await this.runner.run(s, q.get('param') || '', { win: this.activeWindow(file) }); }
    }

    // ═════════════════════════════════════════════════════════════════════
    // context menus
    // ═════════════════════════════════════════════════════════════════════
    fieldMenu(w, o, ctx, x, y) {
      const key = o.field;
      const f = w.file.fieldByKey(key);
      FM.popupMenu([
        { label: 'Cut', action: () => document.execCommand('cut') }, { label: 'Copy', action: () => document.execCommand('copy') }, { label: 'Paste', action: async () => { try { const t = await navigator.clipboard.readText(); document.execCommand('insertText', false, t); } catch (e) { FM.toast('Use Ctrl+V to paste.'); } } },
        '-',
        { label: 'Sort Ascending', action: () => this.act(w, async () => { if (await w.commit()) w.applySort([{ key, dir: 'asc' }]); }) },
        { label: 'Sort Descending', action: () => this.act(w, async () => { if (await w.commit()) w.applySort([{ key, dir: 'desc' }]); }) },
        { label: 'Find Matching Records', sub: [{ label: 'Replace Found Set', action: () => this.act(w, () => w.findMatching(key, 'replace')) }, { label: 'Constrain Found Set', action: () => this.act(w, () => w.findMatching(key, 'constrain')) }, { label: 'Extend Found Set', action: () => this.act(w, () => w.findMatching(key, 'extend')) }] },
        '-',
        { label: 'Insert', sub: [{ label: 'Current Date', action: () => this.act(w, () => this.runStepNow(w, 'Insert Current Date', { field: key })) }, { label: 'Current Time', action: () => this.act(w, () => this.runStepNow(w, 'Insert Current Time', { field: key })) }, { label: 'Current User Name', action: () => this.act(w, () => this.runStepNow(w, 'Insert Current User Name', { field: key })) }] },
        { label: 'Replace Field Contents…', disabled: !f || f.type === 'calculation' || f.type === 'summary', action: () => this.act(w, () => FM.dlg.replaceFieldContents(w, { field: key, dialog: true })) },
        { label: 'Export Field Contents…', action: () => this.act(w, () => this.runStepNow(w, 'Export Field Contents', { field: key })) },
        '-',
        { label: 'Field: ' + w.file.fullName(key) + (f ? ' (' + f.type + ')' : ''), disabled: true }
      ], x, y);
    }
    tableHeaderMenu(w, col, x, y) {
      const canEdit = w.file.layoutAccess(w.layoutId) === 'modify';
      FM.popupMenu([
        { label: 'Sort Ascending', action: () => this.act(w, async () => { if (await w.commit()) w.applySort([{ key: col.key, dir: 'asc' }]); }) },
        { label: 'Sort Descending', action: () => this.act(w, async () => { if (await w.commit()) w.applySort([{ key: col.key, dir: 'desc' }]); }) },
        { label: 'Unsort', action: () => this.act(w, () => this.runStepNow(w, 'Unsort Records')) },
        '-',
        { label: 'Add Field…', disabled: !canEdit, action: () => this.tableAddColumn(w, x, y) },
        { label: 'Remove Field from Table View', disabled: !canEdit, action: () => this.act(w, async () => { const cols = w.tableColumns().map(c => ({ key: c.key, w: c.w })).filter(c => c.key !== col.key); await w.file.saveSchema([{ op: 'upsert', coll: 'layouts', item: Object.assign(FM.clone(w.layout), { tableView: { columns: cols } }) }]); w.render(); }) },
        { label: 'Reset Table View Columns', disabled: !canEdit || !(w.layout.tableView && w.layout.tableView.columns), action: () => this.act(w, async () => { const l = FM.clone(w.layout); delete l.tableView; await w.file.saveSchema([{ op: 'upsert', coll: 'layouts', item: l }]); w.render(); }) }
      ], x, y);
    }
    async tableAddColumn(w) {
      if (w.file.layoutAccess(w.layoutId) !== 'modify') { FM.alert('Your privileges do not allow modifying this layout.'); return; }
      const k = await FM.dlg.pickField(w.file, { to: w.to });
      if (!k) return;
      const cols = w.tableColumns().map(c => ({ key: c.key, w: c.w }));
      if (!cols.some(c => c.key === k)) cols.push({ key: k, w: 140 });
      await this.act(w, async () => { await w.file.saveSchema([{ op: 'upsert', coll: 'layouts', item: Object.assign(FM.clone(w.layout), { tableView: { columns: cols } }) }]); w.render(); });
    }
    async sortFlow(w) {
      if (!(await w.commit())) return;
      const spec = await FM.dlg.sortDialog(w, w.set_().sort || []);
      if (spec) w.applySort(spec);
    }

    // ═════════════════════════════════════════════════════════════════════
    // printing
    // ═════════════════════════════════════════════════════════════════════
    async printFlow(w) {
      if (!w.file.full && w.file.pset().printing === false) throw new FMError(200, 'Your privileges do not allow printing.');
      if (w.mode !== 'preview') { if (!(await w.setMode('preview'))) return; await FM.sleep(30); }
      this.print(w);
    }
    print(w) {
      const target = w.el && w.el.querySelector('.fm-preview');
      if (!target) { FM.toast('Switch to Preview mode to print.'); return; }
      const ps = w.file.schema.fileOptions.pageSetup || {};
      let st = document.getElementById('fm-page-style');
      if (!st) { st = h('style', { id: 'fm-page-style' }); document.head.appendChild(st); }
      st.textContent = '@page { size: ' + ({ letter: 'letter', legal: 'legal', a4: 'A4', tabloid: '11in 17in' }[ps.paper || 'letter'] || 'letter') + ' ' + (ps.orientation || 'portrait') + '; margin: 0; }';
      target.classList.add('fm-print-target');
      document.body.classList.add('fm-printing');
      const done = () => { target.classList.remove('fm-print-target'); document.body.classList.remove('fm-printing'); window.removeEventListener('afterprint', done); };
      window.addEventListener('afterprint', done);
      setTimeout(() => { window.print(); setTimeout(done, 1000); }, 50);
    }

    // ═════════════════════════════════════════════════════════════════════
    // files
    // ═════════════════════════════════════════════════════════════════════
    async openFile(id, o) {
      o = o || {};
      if (this.files.has(id)) { const w = this.activeWindow(this.files.get(id)); if (w) this.focusWindow(w); return this.files.get(id); }
      let r;
      try { r = await FM.api('POST', '/files/' + id + '/open', { auto: true }); }
      catch (e) {
        if (!(e.data && (e.data.needLogin || e.status === 401))) { await FM.alert(e.message, { icon: 'warn' }); return null; }
        const meta = (this.fileList || []).find(f => f.id === id) || { name: 'file' };
        let err = '';
        for (;;) {
          const cred = await FM.dlg.login(meta.name, { error: err, account: this.prefs['acct.' + id] || '' });
          if (!cred) return null;
          try { r = await FM.api('POST', '/files/' + id + '/open', cred); this.prefs['acct.' + id] = cred.account; this.savePrefs(); break; }
          catch (e2) {
            if (e2.data && e2.data.mustChange) {
              const np = await FM.dlg.newPassword(meta.name); if (!np) return null;
              try { r = await FM.api('POST', '/files/' + id + '/open', Object.assign({}, cred, { newPassword: np })); break; } catch (e3) { err = e3.message; continue; }
            }
            err = e2.message;
          }
        }
      }
      const file = new FM.FMFile(this, r);
      this.files.set(id, file);
      file.startSync();
      if (!file.schema.layouts.length && !file.full) { await FM.alert('This file has no layouts you can use.'); }
      const w = await this.newWindow(file, { name: file.name });
      await this.trigger(w, 'OnFirstWindowOpen');
      if (o.afterOpen) await o.afterOpen(w);
      return file;
    }
    async closeFile(file, o) {
      if (!file) return;
      o = o || {};
      if (!o.noWindows) { for (const w of file.windows.slice()) { const ok = await this.closeWindow(w, { force: o.force }); if (!ok) return false; } if (!this.files.has(file.id)) return true; }
      file.stopSync();
      if (FM.workspace.file === file && FM.workspace.el) { FM.workspace.dirty = false; FM.workspace.close(); }
      this.files.delete(file.id);
      try { await FM.api('POST', '/files/' + file.id + '/close', {}, { token: file.token }); } catch (e) { /* the host closes stale sessions */ }
      this.renderMenubar();
      return true;
    }
    async relogin(file, account, password) {
      const ws = file.windows.slice();
      for (const w of ws) if (!(await w.commit())) throw new FMError(301);
      let r;
      try { r = await FM.api('POST', '/files/' + file.id + '/relogin', { account, password }, { token: file.token }); }
      catch (e) { throw new FMError(e.fmError || 212, e.message); }
      file.account = r.account; file.hasPassword = r.hasPassword; file.seq = r.seq;
      file.tables.forEach(t => t.recs.clear());
      for (const tid in r.records) r.records[tid].forEach(x => file.putRecord(x));
      file.touch();
      ws.forEach(w => { w.sets = new Map(); if (!w.layout || file.layoutAccess(w.layoutId) === 'none') { const id = w.defaultLayout(); if (id) w.layoutId = id; } w.render(); });
      this.renderMenubar();
    }
    async exitApplication() {
      for (const f of this.openFiles()) await this.closeFile(f);
      if (!this.files.size) location.href = this.boot.dashboard || '/dashboard';
    }
    async saveCopy(file) {
      const name = h('input', { class: 'fm-input', value: file.name + ' Copy' });
      const mode = FM.select([{ value: 'copy', label: 'Copy of current file' }, { value: 'clone', label: 'Clone (no records)' }], 'copy');
      const ok = await FM.modal({ title: 'Save a Copy As', body: h('div', { class: 'fm-form' }, FM.row('Name', name), FM.row('Type', mode), h('div', { class: 'fm-muted small', text: 'The copy is a new hosted file with the same accounts.' })), width: 440, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'Save', value: true, primary: true }] });
      if (!ok) return;
      try { const r = await file.api('POST', '/copy', { name: name.value, mode: mode.value }); FM.toast('Saved "' + r.name + '".'); } catch (e) { FM.alert(e.message, { icon: 'warn' }); }
    }
    designReport(file) {
      const s = file.schema; const e = FM.esc;
      const fieldRow = (t, f) => { const o = f.options || {}; const def = f.type === 'calculation' ? (o.calc || {}).formula : f.type === 'summary' ? JSON.stringify(o.summary) : ''; return '<tr><td>' + e(f.name) + '</td><td>' + e(f.type) + '</td><td><code>' + e(def || '') + '</code></td><td>' + e(f.comment || '') + '</td></tr>'; };
      const html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Database Design Report — ' + e(file.name) + '</title><style>body{font-family:system-ui,sans-serif;margin:24px;color:#1d2733}table{border-collapse:collapse;margin:8px 0 18px;width:100%}td,th{border:1px solid #d0d5dc;padding:4px 8px;text-align:left;font-size:13px;vertical-align:top}th{background:#f1f3f6}code{font-size:12px;white-space:pre-wrap}h2{margin-top:28px;border-bottom:2px solid #2a6fdb}</style></head><body>' +
        '<h1>Database Design Report: ' + e(file.name) + '</h1><p>Generated ' + e(new Date().toLocaleString()) + ' by FileMaker (independent recreation).</p>' +
        '<h2>Tables</h2>' + s.tables.map(t => '<h3>' + e(t.name) + ' (' + file.count(t.id) + ' records)</h3><table><tr><th>Field</th><th>Type</th><th>Definition</th><th>Comment</th></tr>' + t.fields.map(f => fieldRow(t, f)).join('') + '</table>').join('') +
        '<h2>Relationships</h2><table><tr><th>Left</th><th>Predicates</th><th>Right</th></tr>' + s.relationships.map(r => '<tr><td>' + e((file.to(r.left) || {}).name) + '</td><td>' + (r.predicates || []).map(p => e((file.field(p.leftField) || {}).name) + ' ' + e(p.op) + ' ' + e((file.field(p.rightField) || {}).name)).join('<br>') + '</td><td>' + e((file.to(r.right) || {}).name) + '</td></tr>').join('') + '</table>' +
        '<h2>Layouts</h2><table><tr><th>Name</th><th>Table occurrence</th><th>Objects</th><th>Fields</th></tr>' + s.layouts.map(l => '<tr><td>' + e(l.name) + '</td><td>' + e((file.to(l.to) || {}).name) + '</td><td>' + FM.layoutObjects(l).length + '</td><td>' + FM.layoutFields(l).map(k => e(file.keyLabel(k, l.to))).join(', ') + '</td></tr>').join('') + '</table>' +
        '<h2>Scripts</h2>' + FM.orderedScripts(file).filter(x => !x.folder).map(sc => '<h3>' + e(sc.name) + '</h3><pre>' + (sc.steps || []).map((st, i) => (i + 1) + '  ' + e((st.off ? '// ' : '') + FM.formatStep(st, file))).join('\n') + '</pre>').join('') +
        '<h2>Value Lists</h2><table><tr><th>Name</th><th>Values</th></tr>' + s.valueLists.map(v => '<tr><td>' + e(v.name) + '</td><td>' + (v.type === 'field' ? 'From field ' + e(file.fullName((v.field || {}).key || '')) : e((v.values || []).join(', '))) + '</td></tr>').join('') + '</table>' +
        '<h2>Custom Functions</h2><table><tr><th>Name</th><th>Formula</th></tr>' + s.customFunctions.map(c => '<tr><td>' + e(c.name) + ' ( ' + e((c.params || []).join(' ; ')) + ' )</td><td><code>' + e(c.formula) + '</code></td></tr>').join('') + '</table>' +
        '<h2>Privilege Sets</h2><table><tr><th>Name</th><th>Records</th><th>Layouts</th><th>Scripts</th><th>Extended</th></tr>' + s.privilegeSets.map(p => '<tr><td>' + e(p.name) + '</td><td>' + e((p.records || {}).mode) + '</td><td>' + e((p.layouts || {}).mode) + '</td><td>' + e((p.scripts || {}).mode) + '</td><td>' + e((p.extended || []).join(', ')) + '</td></tr>').join('') + '</table></body></html>';
      FM.download(file.name + ' DDR.html', html, 'text/html');
    }

    // ═════════════════════════════════════════════════════════════════════
    // Launch Center
    // ═════════════════════════════════════════════════════════════════════
    hideLaunch() { if (this.launch) { this.launch.remove(); this.launch = null; } }
    async showLaunch(tab) {
      this.hideLaunch();
      const el = this.launch = h('div', { class: 'fm-launch' });
      this.desktop.appendChild(el);
      el.style.zIndex = 5000;
      const close = h('button', { class: 'fm-btn small', text: 'Close', onclick: () => this.hideLaunch(), style: { display: this.windows.length ? '' : 'none' } });
      const search = h('input', { class: 'fm-input fm-search', type: 'search', placeholder: 'Search hosted files' });
      const body = h('div', { class: 'fm-launch-body' });
      el.append(h('div', { class: 'fm-launch-head' },
        h('div', { class: 'fm-launch-brand' }, h('span', { class: 'fm-brand-logo big', text: 'FM' }), h('div', null, h('h1', { text: 'FileMaker' }), h('div', { class: 'fm-muted', text: 'Launch Center · Host: The Office App (' + location.host + ')' }))),
        h('div', { class: 'fm-flex1' }), search, close),
        h('div', { class: 'fm-launch-tabs' }, ...[['hosts', 'Hosts', 'db'], ['create', 'Create', 'plus']].map(([k, l, ic]) => h('button', { class: 'fm-launch-tab' + ((tab || 'hosts') === k ? ' on' : ''), onclick: () => this.showLaunch(k) }, h('span', { html: FM.icon(ic, 15) }), ' ' + l))),
        body,
        h('div', { class: 'fm-launch-foot', text: 'FileMaker here is an independent recreation for prototyping and learning — not affiliated with Claris International Inc. “FileMaker” is a trademark of Claris International Inc.' }));
      if (tab === 'create') { this.renderCreate(body); return; }
      body.appendChild(h('div', { class: 'fm-muted pad', text: 'Loading hosted files…' }));
      let files;
      try { files = (await FM.api('GET', '/files')).files; } catch (e) { body.innerHTML = ''; body.appendChild(h('div', { class: 'fm-calc-status bad', text: e.message })); return; }
      this.fileList = files;
      const draw = () => {
        body.innerHTML = '';
        const q = search.value.trim().toLowerCase();
        const grid = h('div', { class: 'fm-filegrid' });
        grid.appendChild(h('div', { class: 'fm-filecard new', onclick: () => this.showLaunch('create') }, h('div', { class: 'fm-fileicon new', html: FM.icon('plus', 30) }), h('b', { text: 'Create New…' }), h('small', { class: 'fm-muted', text: 'Blank file, starter solution, or convert a spreadsheet' })));
        files.filter(f => !q || f.name.toLowerCase().includes(q)).forEach(f => {
          const open = this.files.has(f.id);
          const card = h('div', { class: 'fm-filecard' + (open ? ' open' : ''), title: 'Open "' + f.name + '"' },
            h('div', { class: 'fm-fileicon', style: { background: f.color || '#7a2bd8' }, text: f.name.slice(0, 2).toUpperCase() }),
            h('b', { text: f.name }),
            h('small', { class: 'fm-muted', text: (f.tables || 0) + ' tables · ' + (f.layouts || 0) + ' layouts · ' + (f.scripts || 0) + ' scripts · ' + f.records + ' records' }),
            h('small', { class: 'fm-muted', text: 'Modified ' + (f.modified || '').slice(0, 16) + (f.createdBy ? ' · created by ' + f.createdBy : '') }),
            f.users ? h('span', { class: 'fm-users-badge', title: 'Users connected', html: FM.icon('users', 12) + ' ' + f.users }) : null,
            open ? h('span', { class: 'fm-open-badge', text: 'Open' }) : null);
          const more = h('button', { class: 'fm-iconbtn fm-filemore', title: 'More', html: FM.icon('dots', 16) });
          more.addEventListener('click', e => { e.stopPropagation(); const r = more.getBoundingClientRect(); FM.popupMenu([{ label: 'Open', action: () => this.openFile(f.id) }, { label: 'Open in New Window', disabled: !open, action: () => { const fl = this.files.get(f.id); this.newWindow(fl, { name: fl.name + ' - ' + (fl.windows.length + 1) }); } }, '-', { label: 'Delete File…', action: () => this.deleteFileFlow(f) }], r.left, r.bottom); });
          card.appendChild(more);
          card.addEventListener('click', () => this.openFile(f.id));
          grid.appendChild(card);
        });
        body.appendChild(grid);
        if (!files.length) body.appendChild(h('div', { class: 'fm-empty', html: 'No files are hosted yet. Click <b>Create New…</b> to make a blank file, start from a starter solution, or convert a spreadsheet.' }));
      };
      search.addEventListener('input', draw);
      draw();
    }
    renderCreate(body) {
      body.innerHTML = '';
      const grid = h('div', { class: 'fm-filegrid' });
      const card = (icon, color, title, desc, fn) => { const c = h('div', { class: 'fm-filecard starter' }, h('div', { class: 'fm-fileicon', style: { background: color }, html: FM.icon(icon, 28) }), h('b', { text: title }), h('small', { class: 'fm-muted', text: desc })); c.onclick = fn; return c; };
      grid.appendChild(card('file', '#5b6573', 'Blank', 'An empty file with one table. Build tables, fields, layouts and scripts yourself.', () => this.newFileDialog()));
      FM.starters.list.forEach(s => grid.appendChild(card(s.icon, s.color, s.name, s.desc, () => this.newFileDialog(s))));
      grid.appendChild(card('upload', '#d6b02f', 'Convert a File…', 'Make a new file from a CSV, tab-separated, Excel (.xlsx), JSON or XML file.', () => this.convertFlow()));
      body.append(h('h3', { text: 'Create a new solution' }), grid);
    }
    async newFileDialog(starter) {
      const name = h('input', { class: 'fm-input', value: starter ? starter.name : 'Untitled' });
      const pw = h('input', { class: 'fm-input', type: 'password', placeholder: 'optional' });
      const acct = h('input', { class: 'fm-input', value: 'Admin' });
      const body = h('div', { class: 'fm-form' }, FM.row('File name', name), FM.row('Full Access account', acct), FM.row('Password', pw),
        h('div', { class: 'fm-muted small', text: 'With no password, anyone who can use FileMaker in The Office App can open this file as ' + 'Admin (FileMaker signs in automatically). Add a password to require sign-in; you can add more accounts later in File > Manage > Security.' }));
      const ok = await FM.modal({ title: starter ? 'New file from "' + starter.name + '"' : 'Create a New File', body, width: 480, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'Create', value: true, primary: true, validate: () => { if (!name.value.trim()) { FM.alert('Enter a file name.'); return false; } return true; } }] });
      if (!ok) return null;
      const built = starter ? starter.build() : FM.starters.blank(name.value.trim());
      return this.createFile(name.value.trim(), built, acct.value.trim() || 'Admin', pw.value);
    }
    async createFile(name, built, admin, password) {
      try {
        const sch = built.schema;
        if (!password) sch.fileOptions = Object.assign({}, sch.fileOptions, { autoLogin: { enabled: true, account: admin } });
        const r = await FM.api('POST', '/files', { name, schema: sch, records: built.records, adminName: admin, adminPassword: password });
        FM.toast('Created "' + r.name + '".');
        this.fileList = null;
        if (password) this.prefs['acct.' + r.id] = admin, this.savePrefs();
        return this.openFile(r.id);
      } catch (e) { await FM.alert(e.message, { icon: 'warn' }); return null; }
    }
    async convertFlow() {
      const f = await FM.pickFile('.csv,.tab,.tsv,.txt,.mer,.xlsx,.json,.xml');
      if (!f) return;
      let rows, header = true;
      try {
        if (/\.xlsx$/i.test(f.name)) { const fd = new FormData(); fd.append('file', f); const r = await FM.api('POST', '/xlsx/parse', fd); rows = (r.sheets[0] || { rows: [] }).rows; }
        else if (/\.json$/i.test(f.name)) { let d = JSON.parse(await FM.readText(f)); if (!Array.isArray(d)) d = d.records || d.data || [d]; const keys = []; d.forEach(o => Object.keys(o || {}).forEach(k => { if (!keys.includes(k)) keys.push(k); })); rows = [keys].concat(d.map(o => keys.map(k => o[k] == null ? '' : typeof o[k] === 'object' ? JSON.stringify(o[k]) : String(o[k])))); }
        else if (/\.xml$/i.test(f.name)) { const doc = new DOMParser().parseFromString(await FM.readText(f), 'application/xml'); const names = [...doc.getElementsByTagName('FIELD')].map(x => x.getAttribute('NAME')); rows = [names].concat([...doc.getElementsByTagName('ROW')].map(r => [...r.getElementsByTagName('COL')].map(c => c.textContent))); }
        else { rows = FM.parseDelimited(await FM.readText(f)); }
      } catch (e) { await FM.alert('That file could not be read: ' + e.message, { icon: 'warn' }); return; }
      if (!rows || !rows.length) { await FM.alert('The file has no rows.'); return; }
      const first = FM.check('First row contains field names', header);
      const name = h('input', { class: 'fm-input', value: f.name.replace(/\.[^.]+$/, '') });
      const preview = h('table', { class: 'fm-grid' }, rows.slice(0, 6).map(r => h('tr', null, r.slice(0, 8).map(c => h('td', { text: String(c).slice(0, 30) })))));
      const ok = await FM.modal({ title: 'Convert "' + f.name + '"', body: h('div', { class: 'fm-form' }, FM.row('New file name', name), first, h('div', { class: 'fm-muted small', text: rows.length + ' rows' }), h('div', { class: 'fm-scroll', style: { maxHeight: '220px' } }, preview)), width: 680, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'Create File', value: true, primary: true }] });
      if (!ok) return;
      const built = FM.starters.fromRows(name.value.trim() || 'Converted', rows, first.input.checked);
      await this.createFile(name.value.trim() || 'Converted', built, 'Admin', '');
    }
    async deleteFileFlow(meta) {
      const acct = h('input', { class: 'fm-input', value: this.prefs['acct.' + meta.id] || 'Admin' }), pw = h('input', { class: 'fm-input', type: 'password' }), conf = h('input', { class: 'fm-input', placeholder: meta.name });
      const ok = await FM.modal({ title: 'Delete "' + meta.name + '"', body: h('div', { class: 'fm-form' }, h('div', { class: 'fm-msg-text', text: 'This permanently deletes the file, its records, accounts and container data for everyone. It cannot be undone.' }), FM.row('Full Access account', acct), FM.row('Password', pw), FM.row('Type the file name', conf)), width: 480, buttons: [{ label: 'Cancel', value: false, cancel: true }, { label: 'Delete File', value: true, danger: true }] });
      if (!ok) return;
      try {
        const open = this.files.get(meta.id); if (open) await this.closeFile(open, { force: true });
        await FM.api('POST', '/files/' + meta.id + '/delete', { account: acct.value, password: pw.value, confirm: conf.value });
        FM.toast('Deleted "' + meta.name + '".');
        this.showLaunch();
      } catch (e) { await FM.alert(e.message, { icon: 'warn' }); }
    }
  }

  // ── boot ─────────────────────────────────────────────────────────────────
  function boot() {
    const root = document.getElementById('fm-root');
    if (!root) return;
    new App(root, window.FM_BOOT || {});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
