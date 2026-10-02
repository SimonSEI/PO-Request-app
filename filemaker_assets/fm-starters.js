/* FileMaker (independent recreation) — Starter Solutions: ready-made files with
   tables, relationships, layouts, scripts, value lists and sample records.
   Also builds a blank file and a file converted from a spreadsheet. */
(function () {
  'use strict';
  const FM = window.FM;
  const D = FM.dt;

  // a tiny builder that keeps names -> ids
  function Builder(fileName) {
    const b = { tables: [], tos: [], rels: [], layouts: [], scripts: [], vls: [], records: {}, byName: {}, toByName: {}, layoutByName: {}, scriptByName: {}, vlByName: {} };
    b.table = (name, fields) => {
      const t = { id: FM.uid('T'), name, fields: [] };
      b.byName[name] = t;
      std(t);
      fields.forEach(([n, type, options, comment]) => t.fields.push({ id: FM.uid('F'), name: n, type, options: options || {}, comment: comment || '' }));
      b.tables.push(t);
      b.records[t.id] = [];
      return t;
    };
    b.f = (table, name) => { const t = b.byName[table]; const f = t && t.fields.find(x => x.name === name); if (!f) throw new Error('starter: no field ' + table + '::' + name); return f; };
    b.to = (name, table, x, y, color) => { const o = { id: FM.uid('O'), name, table: b.byName[table || name].id, x: x || 40, y: y || 40, color: color || '#d5e3f7' }; b.tos.push(o); b.toByName[name] = o; return o; };
    b.key = (to, field) => { const o = b.toByName[to]; const t = b.tables.find(x => x.id === o.table); const f = t.fields.find(x => x.name === field); if (!f) throw new Error('starter: no field ' + to + '::' + field); return o.id + '::' + f.id; };
    b.rel = (l, lf, r, rf, opts) => { const L = b.toByName[l], R = b.toByName[r]; b.rels.push({ id: FM.uid('R'), left: L.id, right: R.id, predicates: [{ leftField: b.key(l, lf).split('::')[1], op: '=', rightField: b.key(r, rf).split('::')[1] }], leftOpts: (opts || {}).left || {}, rightOpts: (opts || {}).right || {} }); };
    b.vl = (name, def) => { const v = Object.assign({ id: FM.uid('V'), name }, def); b.vls.push(v); b.vlByName[name] = v; return v; };
    b.rec = (table, values) => {
      const t = b.byName[table]; const d = {};
      values = Object.assign({ PrimaryKey: uuid(), CreationTimestamp: D.isoTs(D.nowTs()), CreatedBy: 'Admin', ModificationTimestamp: D.isoTs(D.nowTs()), ModifiedBy: 'Admin' }, values);
      for (const k in values) { const f = t.fields.find(x => x.name === k); if (f) d[f.id] = values[k]; }
      b.records[t.id].push(d);
    };
    b.file = () => { const f = Object.create(FM.FMFile.prototype); f.memo = new Map(); f.relMemo = new Map(); f.idx = new Map(); f.editing = new Map(); f.dv = 1; f.setSchema(b.schema(), 1); return f; };
    b.schema = () => ({ format: 1, tables: b.tables, tableOccurrences: b.tos, relationships: b.rels, layouts: b.layouts, layoutOrder: b.layouts.map(l => l.id), scripts: b.scripts, scriptOrder: b.scripts.map(s => s.id), valueLists: b.vls, customFunctions: b.cfs || [], privilegeSets: [], themes: [], fileOptions: b.fileOptions || {} });
    b.layout = (lay) => { b.layouts.push(lay); b.layoutByName[lay.name] = lay; return lay; };
    b.script = (name, steps, o) => { const s = Object.assign({ id: FM.uid('S'), name, menu: true, steps: steps.map(([st, p]) => ({ id: FM.uid('t'), s: st, p: p || {} })) }, o || {}); b.scripts.push(s); b.scriptByName[name] = s; return s; };
    b.out = () => ({ name: fileName, schema: b.schema(), records: b.records });
    return b;
  }
  function std(t) {
    t.fields.push(
      { id: FM.uid('F'), name: 'PrimaryKey', type: 'text', comment: 'Unique identifier of each record', options: { autoEnter: { calc: 'Get ( UUID )', prohibit: true }, validation: { unique: true, notEmpty: true, when: 'always' } } },
      { id: FM.uid('F'), name: 'CreationTimestamp', type: 'timestamp', options: { autoEnter: { creation: 'timestamp' } } },
      { id: FM.uid('F'), name: 'CreatedBy', type: 'text', options: { autoEnter: { creation: 'account' } } },
      { id: FM.uid('F'), name: 'ModificationTimestamp', type: 'timestamp', options: { autoEnter: { modification: 'timestamp' } } },
      { id: FM.uid('F'), name: 'ModifiedBy', type: 'text', options: { autoEnter: { modification: 'account' } } });
  }
  const serial = (next) => ({ autoEnter: { serial: { on: true, next: String(next || 1), increment: 1, generate: 'create' }, prohibit: true } });
  const calc = (formula, resultType, stored) => ({ calc: { formula, resultType: resultType || 'text', stored: stored !== false } });
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : FM.uid('u')).toUpperCase();
  const day = n => D.isoDate(D.todayNum() + n);
  // layout objects
  const T = (text, x, y, w, hh, st) => ({ id: FM.uid('o'), type: 'text', text, x, y, w, h: hh || 20, style: Object.assign({ align: 'right', color: '#5b6573', size: 12, valign: 'middle' }, st || {}) });
  const F = (field, x, y, w, hh, extra) => Object.assign({ id: FM.uid('o'), type: 'field', field, x, y, w, h: hh || 22, control: 'edit' }, extra || {});
  const B = (label, x, y, w, action, extra) => Object.assign({ id: FM.uid('o'), type: 'button', label, x, y, w, h: 28, action }, extra || {});
  const title = (text, x, y) => ({ id: FM.uid('o'), type: 'text', text, x: x || 20, y: y || 16, w: 420, h: 30, style: { size: 21, bold: true, color: '#1d2733', align: 'left', valign: 'middle' } });
  const header = (h0, fill) => ({ id: FM.uid('p'), type: 'header', h: h0, fill });
  const part = (type, h0, extra) => Object.assign({ id: FM.uid('p'), type, h: h0 }, extra || {});
  const script = (b, name) => ({ kind: 'script', script: b.scriptByName[name].id });
  const navBar = (b, y, items) => items.map((it, i) => B(it[0], 20 + i * 132, y, 124, it[1], { style: { fill: '#ffffff', line: '#c3cad3', lineWidth: 1, radius: 6, size: 12 } }));

  // ═══════════════════════════════════════════════════════════════════════
  // Invoices
  // ═══════════════════════════════════════════════════════════════════════
  function invoices() {
    const b = Builder('Invoices');
    b.table('Customers', [['CustomerID', 'number', serial(1001)], ['Company', 'text', { validation: { notEmpty: true, when: 'always', allowOverride: false } }], ['Contact Name', 'text'], ['Email', 'text'], ['Phone', 'text'], ['Address', 'text'], ['City', 'text'], ['State', 'text'], ['Zip', 'text'], ['Notes', 'text'],
      ['Total Invoiced', 'calculation', calc('Sum ( Invoices::Total )', 'number', false)], ['Balance Due', 'calculation', calc('Sum ( Invoices::Balance )', 'number', false)], ['Invoice Count', 'calculation', calc('Count ( Invoices::InvoiceID )', 'number', false)]]);
    b.table('Products', [['ProductID', 'number', serial(1)], ['Name', 'text', { validation: { notEmpty: true, when: 'always' } }], ['SKU', 'text', { validation: { unique: true, when: 'always' } }], ['Category', 'text'], ['Price', 'number'], ['Active', 'number', { autoEnter: { data: '1' } }]]);
    b.table('Invoices', [['InvoiceID', 'number', serial(5001)], ['CustomerID', 'number', { validation: { notEmpty: true, when: 'always', message: 'Choose a customer for this invoice.' } }], ['Invoice Date', 'date', { autoEnter: { creation: 'date' } }], ['Due Date', 'date', { autoEnter: { calc: 'Invoice Date + 30', calcNoReplace: false } }],
      ['Status', 'text', { autoEnter: { data: 'Draft' } }], ['Tax Rate', 'number', { autoEnter: { data: '0.07' } }], ['Paid Amount', 'number'], ['Memo', 'text'],
      ['Subtotal', 'calculation', calc('Sum ( Line Items::Extended )', 'number', false)], ['Tax', 'calculation', calc('Round ( Subtotal * Tax Rate ; 2 )', 'number', false)], ['Total', 'calculation', calc('Subtotal + Tax', 'number', false)],
      ['Balance', 'calculation', calc('Total - Paid Amount', 'number', false)], ['Customer Name', 'calculation', calc('Customers::Company', 'text', false)],
      ['Days Overdue', 'calculation', calc('If ( Status ≠ "Paid" and Get ( CurrentDate ) > Due Date ; Get ( CurrentDate ) - Due Date ; "" )', 'number', false)],
      ['Total Sum', 'summary', { summary: { op: 'total', field: '' } }], ['Invoice Count', 'summary', { summary: { op: 'count', field: '' } }], ['Balance Sum', 'summary', { summary: { op: 'total', field: '' } }]]);
    b.f('Invoices', 'Total Sum').options.summary.field = b.f('Invoices', 'Total').id;
    b.f('Invoices', 'Invoice Count').options.summary.field = b.f('Invoices', 'InvoiceID').id;
    b.f('Invoices', 'Balance Sum').options.summary.field = b.f('Invoices', 'Balance').id;
    b.table('Line Items', [['LineID', 'number', serial(1)], ['InvoiceID', 'number'], ['ProductID', 'number'], ['Description', 'text'], ['Qty', 'number', { autoEnter: { data: '1' }, validation: { range: { from: '1', to: '10000' }, when: 'always' } }], ['Unit Price', 'number'], ['Extended', 'calculation', calc('Qty * Unit Price', 'number', false)]]);
    b.to('Customers', 'Customers', 40, 60, '#d9f0dc');
    b.to('Invoices', 'Invoices', 300, 60, '#d5e3f7');
    b.to('Line Items', 'Line Items', 560, 60, '#fde5c8');
    b.to('Products', 'Products', 820, 60, '#f3d6e7');
    b.rel('Customers', 'CustomerID', 'Invoices', 'CustomerID', { right: { sort: [{ fid: b.f('Invoices', 'Invoice Date').id, dir: 'desc' }] } });
    b.rel('Invoices', 'InvoiceID', 'Line Items', 'InvoiceID', { right: { create: true, delete: true } });
    b.rel('Line Items', 'ProductID', 'Products', 'ProductID');
    // lookups: description and price come from the product
    b.f('Line Items', 'Description').options = { autoEnter: { lookup: { to: b.toByName.Products.id, field: b.f('Products', 'Name').id, noMatch: 'nothing' } } };
    b.f('Line Items', 'Unit Price').options = { autoEnter: { lookup: { to: b.toByName.Products.id, field: b.f('Products', 'Price').id, noMatch: 'nothing' } } };
    const vStatus = b.vl('Invoice Status', { type: 'custom', values: ['Draft', 'Sent', 'Paid', 'Overdue', '-', 'Void'] });
    const vCats = b.vl('Product Categories', { type: 'custom', values: ['Irrigation', 'Pumps', 'Lighting', 'Service', 'Parts'] });
    const vCust = b.vl('Customers', { type: 'field', field: { key: b.key('Customers', 'CustomerID'), key2: b.key('Customers', 'Company'), showOnly2: true, sortBy: 2 } });
    const vProd = b.vl('Products', { type: 'field', field: { key: b.key('Products', 'ProductID'), key2: b.key('Products', 'Name'), showOnly2: true, sortBy: 2 } });
    b.f('Invoices', 'Status').options.validation = { memberOf: vStatus.id, when: 'always' };
    // layouts (ids first, so scripts can name them)
    const L = { inv: FM.uid('L'), list: FM.uid('L'), cust: FM.uid('L'), prod: FM.uid('L'), rep: FM.uid('L'), dash: FM.uid('L') };
    // scripts
    b.script('New Invoice', [['Go to Layout', { layout: { how: 'id', id: L.inv } }], ['New Record/Request'], ['Go to Field', { field: b.key('Invoices', 'CustomerID') }]]);
    b.script('Mark Invoice Paid', [
      ['#', { text: 'Marks the current invoice paid in full' }],
      ['If', { calc: 'Invoices::Status = "Paid"' }],
      ['Show Custom Dialog', { dialog: { title: '"Already paid"', message: '"Invoice " & Invoices::InvoiceID & " is already marked paid."', buttons: [{ label: '"OK"', commit: true }] } }],
      ['Exit Script', { result: 'False' }],
      ['End If'],
      ['Set Field', { field: b.key('Invoices', 'Paid Amount'), calc: 'Invoices::Total' }],
      ['Set Field', { field: b.key('Invoices', 'Status'), calc: '"Paid"' }],
      ['Commit Records/Requests', { skipValidation: false }],
      ['Exit Script', { result: 'True' }]]);
    b.script('Find Overdue Invoices', [
      ['Go to Layout', { layout: { how: 'id', id: L.list } }],
      ['Set Error Capture', { on: true }],
      ['Perform Find', { requests: [{ omit: false, crit: { [b.key('Invoices', 'Days Overdue')]: '>0' } }] }],
      ['If', { calc: 'Get ( LastError ) = 401' }],
      ['Show All Records'],
      ['Show Custom Dialog', { dialog: { title: '"Overdue invoices"', message: '"No invoices are overdue. Nice work."', buttons: [{ label: '"OK"', commit: true }] } }],
      ['Else'],
      ['Sort Records', { sort: [{ key: b.key('Invoices', 'Due Date'), dir: 'asc' }], dialog: false }],
      ['Show Custom Dialog', { dialog: { title: '"Overdue invoices"', message: 'Get ( FoundCount ) & " overdue invoice(s), " & GetAsText ( Round ( Sum ( Invoices::Balance ) ; 2 ) ) & " still owed in total."', buttons: [{ label: '"OK"', commit: true }] } }],
      ['End If']]);
    b.script('Sales Report by Status', [['Go to Layout', { layout: { how: 'id', id: L.rep } }], ['Show All Records'], ['Sort Records', { sort: [{ key: b.key('Invoices', 'Status'), dir: 'asc' }, { key: b.key('Invoices', 'Invoice Date'), dir: 'asc' }], dialog: false }], ['Enter Preview Mode', { pause: false }]]);
    b.script('Print Invoice', [['Save Records as PDF', { which: 'current' }]]);
    b.script('Go to Customer', [['Go to Related Record', { to: b.toByName.Customers.id, layout: { how: 'id', id: L.cust }, onlyRelated: true, match: 'current' }]]);
    b.script('Email Customer', [['Send Mail', { to: 'Customers::Email', subject: '"Invoice " & Invoices::InvoiceID', message: '"Hello " & Customers::Contact Name & ",¶¶Your invoice " & Invoices::InvoiceID & " for $" & Invoices::Total & " is due on " & Invoices::Due Date & ".¶¶Thank you!"' }]]);
    // Invoices form
    const ik = n => b.key('Invoices', n);
    const pi = { id: FM.uid('o'), type: 'portal', to: b.toByName['Line Items'].id, x: 20, y: 250, w: 700, h: 200, rows: 8, allowDelete: true, scroll: true, alt: true, children: [] };
    const lk = n => b.key('Line Items', n);
    pi.children.push(F(lk('ProductID'), 24, 252, 180, 21, { control: 'popup', valueList: vProd.id }), F(lk('Description'), 208, 252, 236, 21), F(lk('Qty'), 448, 252, 60, 21), F(lk('Unit Price'), 512, 252, 90, 21, { format: { number: { kind: 'currency', decimals: 2 } } }), F(lk('Extended'), 606, 252, 90, 21, { format: { number: { kind: 'currency', decimals: 2 } } }),
      Object.assign(B('', 698, 252, 20, { kind: 'step', step: { id: FM.uid('t'), s: 'Delete Portal Row', p: { dialog: true } } }), { icon: 'x', h: 21, style: { fill: 'transparent', lineWidth: 0 } }));
    b.layout({
      id: L.inv, name: 'Invoices', to: b.toByName.Invoices.id, theme: 'apex', width: 760, autoAdd: false, views: { form: true, list: true, table: true }, view: 'form',
      triggers: {}, parts: [header(96), part('body', 470), part('footer', 32)],
      objects: [
        title('Invoice'), ...navBar(b, 58, [['New Invoice', script(b, 'New Invoice')], ['Mark Paid', script(b, 'Mark Invoice Paid')], ['Find Overdue', script(b, 'Find Overdue Invoices')], ['Print / PDF', script(b, 'Print Invoice')], ['Email', script(b, 'Email Customer')]]),
        T('Invoice #', 20, 112, 90), F(ik('InvoiceID'), 120, 110, 110, 22, { style: { bold: true } }),
        T('Customer', 20, 142, 90), F(ik('CustomerID'), 120, 140, 260, 22, { control: 'popup', valueList: vCust.id }),
        Object.assign(B('Go to Customer', 388, 139, 120, script(b, 'Go to Customer')), { icon: 'next', style: { size: 11 } }),
        T('Status', 20, 172, 90), F(ik('Status'), 120, 170, 140, 22, { control: 'popup', valueList: vStatus.id, cond: [{ calc: 'Self = "Paid"', style: { color: '#16794c', bold: true } }, { calc: 'Self = "Overdue"', style: { color: '#b42318', bold: true } }] }),
        T('Invoice Date', 520, 112, 100), F(ik('Invoice Date'), 630, 110, 110, 22, { control: 'calendar' }),
        T('Due Date', 520, 142, 100), F(ik('Due Date'), 630, 140, 110, 22, { control: 'calendar', cond: [{ calc: 'not IsEmpty ( Invoices::Days Overdue )', style: { color: '#b42318', bold: true } }] }),
        T('Days overdue', 520, 172, 100), F(ik('Days Overdue'), 630, 170, 110, 22, { style: { color: '#b42318', bold: true } }),
        T('Memo', 20, 202, 90), F(ik('Memo'), 120, 200, 620, 22, { placeholder: 'Notes printed on the invoice' }),
        T('Product', 24, 232, 180, 16, { align: 'left', bold: true }), T('Description', 208, 232, 236, 16, { align: 'left', bold: true }), T('Qty', 448, 232, 60, 16, { align: 'left', bold: true }), T('Price', 512, 232, 90, 16, { align: 'left', bold: true }), T('Amount', 606, 232, 90, 16, { align: 'left', bold: true }),
        pi,
        T('Subtotal', 480, 462, 120), F(ik('Subtotal'), 610, 460, 110, 22, { format: { number: { kind: 'currency', decimals: 2 } } }),
        T('Tax rate', 480, 488, 120), F(ik('Tax Rate'), 610, 486, 110, 22, { format: { number: { kind: 'percent', decimals: 1 } } }),
        T('Tax', 480, 514, 120), F(ik('Tax'), 610, 512, 110, 22, { format: { number: { kind: 'currency', decimals: 2 } } }),
        T('Total', 480, 540, 120, 22, { bold: true, color: '#1d2733' }), F(ik('Total'), 610, 538, 110, 24, { style: { bold: true, size: 14 }, format: { number: { kind: 'currency', decimals: 2 } } }),
        T('Paid', 20, 462, 90), F(ik('Paid Amount'), 120, 460, 110, 22, { format: { number: { kind: 'currency', decimals: 2 } } }),
        T('Balance', 20, 488, 90), F(ik('Balance'), 120, 486, 110, 22, { format: { number: { kind: 'currency', decimals: 2 } }, cond: [{ calc: 'Self > 0 and Invoices::Status ≠ "Draft"', style: { color: '#b42318', bold: true } }] }),
        { id: FM.uid('o'), type: 'text', text: 'Record created by <<CreatedBy>> · Page {{PageNumber}}', x: 20, y: 574, w: 400, h: 18, style: { size: 10, color: '#8a94a3', align: 'left' } }
      ]
    });
    // Invoice list with grand summary
    b.layout({
      id: L.list, name: 'Invoice List', to: b.toByName.Invoices.id, theme: 'apex', width: 760, views: { form: true, list: true, table: true }, view: 'list', triggers: {},
      parts: [header(88), part('body', 30), part('trailing_grand', 40), part('footer', 30)],
      objects: [title('Invoices'), ...navBar(b, 52, [['New Invoice', script(b, 'New Invoice')], ['Find Overdue', script(b, 'Find Overdue Invoices')], ['Sales Report', script(b, 'Sales Report by Status')]]).map(o => Object.assign(o, { x: o.x + 300, y: 18 })),
        ...[['Invoice #', 20, 80], ['Date', 110, 90], ['Customer', 210, 220], ['Status', 440, 90], ['Due', 540, 90], ['Total', 640, 100]].map(([t, x, w]) => T(t, x, 70, w, 16, { align: t === 'Total' ? 'right' : 'left', bold: true })),
        F(ik('InvoiceID'), 20, 92, 80, 22, { style: { lineWidth: 0, fill: 'transparent' } }), F(ik('Invoice Date'), 110, 92, 90, 22, { style: { lineWidth: 0, fill: 'transparent' } }), F(ik('Customer Name'), 210, 92, 220, 22, { style: { lineWidth: 0, fill: 'transparent' } }),
        F(ik('Status'), 440, 92, 90, 22, { style: { lineWidth: 0, fill: 'transparent' }, cond: [{ calc: 'Self = "Paid"', style: { color: '#16794c', bold: true } }, { calc: 'not IsEmpty ( Invoices::Days Overdue )', style: { color: '#b42318', bold: true } }] }),
        F(ik('Due Date'), 540, 92, 90, 22, { style: { lineWidth: 0, fill: 'transparent' } }), F(ik('Total'), 640, 92, 100, 22, { style: { lineWidth: 0, fill: 'transparent' }, format: { number: { kind: 'currency', decimals: 2 } } }),
        T('<<Invoice Count>> invoices', 20, 128, 300, 20, { align: 'left', bold: true, color: '#1d2733' }), T('Total', 540, 128, 90, 20, { bold: true, color: '#1d2733' }), F(ik('Total Sum'), 640, 126, 100, 24, { style: { bold: true, lineWidth: 0, fill: 'transparent' }, format: { number: { kind: 'currency', decimals: 2 } } })]
    });
    // Customers with tabs, portal and chart
    const ck = n => b.key('Customers', n);
    const ci = { id: FM.uid('o'), type: 'portal', to: b.toByName.Invoices.id, x: 24, y: 330, w: 452, h: 176, rows: 8, allowDelete: false, scroll: true, alt: true, children: [] };
    ci.children.push(F(ik('InvoiceID'), 28, 332, 70, 20, { entryBrowse: false }), F(ik('Invoice Date'), 102, 332, 90, 20, { entryBrowse: false }), F(ik('Status'), 196, 332, 80, 20, { entryBrowse: false }), F(ik('Total'), 280, 332, 90, 20, { entryBrowse: false, format: { number: { kind: 'currency', decimals: 2 } } }),
      Object.assign(B('Open', 380, 331, 90, { kind: 'step', step: { id: FM.uid('t'), s: 'Go to Related Record', p: { to: b.toByName.Invoices.id, layout: { how: 'id', id: L.inv }, onlyRelated: true, match: 'current' } } }), { h: 22, style: { size: 11 } }));
    const tabs = { id: FM.uid('o'), type: 'tab', x: 20, y: 252, w: 700, h: 270, tabHeight: 28, name: 'CustomerTabs', tabs: [{ id: FM.uid('b'), label: 'Invoices', children: [ci, { id: FM.uid('o'), type: 'chart', x: 488, y: 290, w: 224, h: 220, chart: { type: 'pie', title: 'Invoiced by status', source: 'related', relTO: b.toByName.Invoices.id, x: 'Invoices::Status', group: true, series: [{ name: 'Total', calc: 'Invoices::Total' }], legend: true } }, T('Invoice #   Date            Status       Total', 28, 290, 440, 18, { align: 'left', bold: true, size: 11 })] }, { id: FM.uid('b'), label: 'Notes', children: [F(ck('Notes'), 30, 292, 680, 210, { placeholder: 'Notes about this customer' })] }] };
    b.layout({
      id: L.cust, name: 'Customers', to: b.toByName.Customers.id, theme: 'apex', width: 760, views: { form: true, list: true, table: true }, view: 'form', triggers: {},
      parts: [header(90), part('body', 440), part('footer', 30)],
      objects: [title('Customer'), ...navBar(b, 54, [['New Invoice', script(b, 'New Invoice')]]),
        T('Company', 20, 108, 110), F(ck('Company'), 140, 106, 300, 24, { style: { bold: true, size: 14 } }),
        T('Contact', 20, 140, 110), F(ck('Contact Name'), 140, 138, 300, 22), T('Email', 20, 168, 110), F(ck('Email'), 140, 166, 300, 22), T('Phone', 20, 196, 110), F(ck('Phone'), 140, 194, 300, 22),
        T('Address', 460, 108, 70), F(ck('Address'), 540, 106, 200, 22), F(ck('City'), 540, 134, 110, 22, { placeholder: 'City' }), F(ck('State'), 654, 134, 40, 22, { placeholder: 'ST' }), F(ck('Zip'), 698, 134, 52, 22, { placeholder: 'Zip' }),
        T('Invoiced', 460, 168, 70), F(ck('Total Invoiced'), 540, 166, 110, 22, { format: { number: { kind: 'currency', decimals: 2 } } }), T('Balance', 460, 196, 70), F(ck('Balance Due'), 540, 194, 110, 22, { format: { number: { kind: 'currency', decimals: 2 } }, cond: [{ calc: 'Self > 0', style: { color: '#b42318', bold: true } }] }),
        T('Customer #', 20, 224, 110), F(ck('CustomerID'), 140, 222, 100, 22), tabs]
    });
    b.layout({ id: L.prod, name: 'Products', to: b.toByName.Products.id, theme: 'apex', width: 700, views: { form: true, list: true, table: true }, view: 'table', triggers: {}, autoAdd: true,
      parts: [header(64), part('body', 220), part('footer', 30)],
      objects: [title('Products'), ...[['Name', 'Name', 240], ['SKU', 'SKU', 110], ['Category', 'Category', 140], ['Price', 'Price', 100], ['Active', 'Active', 90]].flatMap(([lbl, n, w], i) => [T(lbl, 20, 90 + i * 30, 110), F(b.key('Products', n), 140, 88 + i * 30, w + 100, 22, n === 'Category' ? { control: 'popup', valueList: vCats.id } : n === 'Price' ? { format: { number: { kind: 'currency', decimals: 2 } } } : n === 'Active' ? { control: 'checkbox', valueList: b.vl('Yes', { type: 'custom', values: ['1'] }).id } : {})])] });
    // report: sub-summary by status, with a chart in the header
    b.layout({ id: L.rep, name: 'Sales by Status', to: b.toByName.Invoices.id, theme: 'classic', width: 540, views: { form: false, list: true, table: true }, view: 'list', triggers: {},
      parts: [header(190), part('sub_leading', 30, { breakKey: ik('Status') }), part('body', 24), part('sub_trailing', 28, { breakKey: ik('Status') }), part('trailing_grand', 34), part('footer', 28)],
      objects: [title('Sales by Status'), T('{{CurrentDate}}', 380, 20, 140, 18, { color: '#7a8594' }), { id: FM.uid('o'), type: 'chart', x: 20, y: 52, w: 500, h: 132, chart: { type: 'column', title: '', source: 'found', x: 'Invoices::Status', group: true, series: [{ name: 'Total', calc: 'Invoices::Total' }], legend: false } },
        F(ik('Status'), 20, 194, 300, 22, { style: { bold: true, size: 14, lineWidth: 0, fill: 'transparent' } }),
        F(ik('InvoiceID'), 40, 222, 70, 20, { style: { lineWidth: 0, fill: 'transparent' } }), F(ik('Invoice Date'), 116, 222, 90, 20, { style: { lineWidth: 0, fill: 'transparent' } }), F(ik('Customer Name'), 212, 222, 200, 20, { style: { lineWidth: 0, fill: 'transparent' } }), F(ik('Total'), 420, 222, 100, 20, { style: { lineWidth: 0, fill: 'transparent' }, format: { number: { kind: 'currency', decimals: 2 } } }),
        T('Subtotal', 300, 248, 110, 20, { bold: true }), F(ik('Total Sum'), 420, 248, 100, 22, { style: { bold: true, lineWidth: 0, fill: 'transparent' }, format: { number: { kind: 'currency', decimals: 2 } } }),
        T('Grand Total', 300, 280, 110, 20, { bold: true, color: '#1d2733' }), F(ik('Total Sum'), 420, 278, 100, 24, { style: { bold: true, size: 13, lineWidth: 0, fill: 'transparent' }, format: { number: { kind: 'currency', decimals: 2 } } }),
        T('Page {{PageNumber}} of {{PageCount}}', 380, 312, 140, 16, { color: '#7a8594', size: 10 })] });
    b.fileOptions = { openLayout: L.inv, autoLogin: { enabled: true, account: 'Admin' }, color: '#2a6fdb' };
    // sample data
    const custs = [['Lakeside Pines HOA', 'Dana Ortiz', 'dana@lakesidepines.example', '(239) 555-0141', '120 Lakeside Dr', 'Naples', 'FL', '34102'], ['Marsh Landing Club', 'Chris Patel', 'chris@marshlanding.example', '(239) 555-0172', '8 Harbor Way', 'Naples', 'FL', '34108'], ['Gulf Harbor Condos', 'Sam Lee', 'sam@gulfharbor.example', '(239) 555-0110', '400 Gulf Shore Blvd', 'Naples', 'FL', '34103'], ['Oak Hammock Estates', 'Riley Chen', 'riley@oakhammock.example', '(239) 555-0199', '55 Hammock Ln', 'Bonita Springs', 'FL', '34135'], ['Coral Bay Resort', 'Jordan Smith', 'jordan@coralbay.example', '(239) 555-0123', '1 Coral Bay Rd', 'Marco Island', 'FL', '34145'], ['Sunset Village', 'Avery Brooks', 'avery@sunsetvillage.example', '(239) 555-0168', '77 Sunset Ave', 'Fort Myers', 'FL', '33901']];
    custs.forEach((c, i) => b.rec('Customers', { CustomerID: String(1001 + i), Company: c[0], 'Contact Name': c[1], Email: c[2], Phone: c[3], Address: c[4], City: c[5], State: c[6], Zip: c[7], PrimaryKey: uuid() }));
    const prods = [['Rotor head (6")', 'RH-600', 'Irrigation', 18.5], ['Spray nozzle set', 'SN-10', 'Irrigation', 7.25], ['Valve repair', 'VR-01', 'Service', 95], ['Pump service call', 'PS-01', 'Pumps', 225], ['Controller (12 zone)', 'CT-12', 'Parts', 289], ['Drip line (100 ft)', 'DL-100', 'Irrigation', 42], ['Landscape light fixture', 'LL-20', 'Lighting', 64], ['Labor (hour)', 'LB-HR', 'Service', 75]];
    prods.forEach((p, i) => b.rec('Products', { ProductID: String(i + 1), Name: p[0], SKU: p[1], Category: p[2], Price: String(p[3]), Active: '1', PrimaryKey: uuid() }));
    const invs = [[1001, -70, 'Paid'], [1002, -50, 'Paid'], [1003, -45, 'Sent'], [1001, -38, 'Sent'], [1004, -20, 'Paid'], [1005, -12, 'Sent'], [1006, -6, 'Draft'], [1002, -3, 'Sent'], [1003, -2, 'Draft'], [1005, -1, 'Sent']];
    let line = 1;
    invs.forEach((v, i) => {
      const id = 5001 + i; const dt = D.todayNum() + v[1];
      let sub = 0;
      const items = [[(i % 8) + 1, 1 + (i % 3)], [((i + 3) % 8) + 1, 2], i % 2 ? [8, 2 + (i % 4)] : null].filter(Boolean);
      items.forEach(([pid, qty]) => { const p = prods[pid - 1]; sub += p[3] * qty; b.rec('Line Items', { LineID: String(line++), InvoiceID: String(id), ProductID: String(pid), Description: p[0], Qty: String(qty), 'Unit Price': String(p[3]), PrimaryKey: uuid() }); });
      const total = Math.round(sub * 1.07 * 100) / 100;
      b.rec('Invoices', { InvoiceID: String(id), CustomerID: String(v[0]), 'Invoice Date': D.isoDate(dt), 'Due Date': D.isoDate(dt + 30), Status: v[2], 'Tax Rate': '0.07', 'Paid Amount': v[2] === 'Paid' ? String(total) : '', PrimaryKey: uuid() });
    });
    return b.out();
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Contacts
  // ═══════════════════════════════════════════════════════════════════════
  function contacts() {
    const b = Builder('Contacts');
    b.table('Contacts', [['First Name', 'text'], ['Last Name', 'text', { validation: { notEmpty: true, when: 'always', message: 'Every contact needs a last name.' } }], ['Company', 'text'], ['Title', 'text'], ['Category', 'text'], ['Email', 'text'], ['Phone', 'text'], ['Mobile', 'text'],
      ['Street', 'text'], ['City', 'text'], ['State', 'text'], ['Zip', 'text'], ['Birthday', 'date'], ['Photo', 'container'], ['Notes', 'text'], ['Favorite', 'text'],
      ['Full Name', 'calculation', calc('Trim ( First Name & " " & Last Name )')], ['Age', 'calculation', calc('If ( IsEmpty ( Birthday ) ; "" ; Year ( Get ( CurrentDate ) ) - Year ( Birthday ) - ( DayOfYear ( Get ( CurrentDate ) ) < DayOfYear ( Birthday ) ) )', 'number', false)],
      ['Address', 'calculation', calc('List ( Street ; Trim ( City & ", " & State & " " & Zip ) )')], ['Initials', 'calculation', calc('Upper ( Left ( First Name ; 1 ) & Left ( Last Name ; 1 ) )')],
      ['Contact Count', 'summary', { summary: { op: 'count', field: '' } }]]);
    b.f('Contacts', 'Contact Count').options.summary.field = b.f('Contacts', 'Last Name').id;
    b.to('Contacts', 'Contacts', 60, 60);
    const vCat = b.vl('Categories', { type: 'custom', values: ['Customer', 'Vendor', 'Partner', 'Family', 'Friend', 'Other'] });
    const vFav = b.vl('Favorite', { type: 'custom', values: ['Favorite'] });
    const k = n => b.key('Contacts', n);
    const L = { det: FM.uid('L'), list: FM.uid('L'), tbl: FM.uid('L'), rep: FM.uid('L') };
    b.script('New Contact', [['Go to Layout', { layout: { how: 'id', id: L.det } }], ['New Record/Request'], ['Go to Field', { field: k('First Name') }]]);
    b.script('Email Contact', [['If', { calc: 'IsEmpty ( Contacts::Email )' }], ['Show Custom Dialog', { dialog: { title: '"No email"', message: 'Contacts::Full Name & " has no email address."', buttons: [{ label: '"OK"' }] } }], ['Halt Script'], ['End If'], ['Send Mail', { to: 'Contacts::Email', subject: '"Hello " & Contacts::First Name' }]]);
    b.script('Map Address', [['Open URL', { url: '"https://www.google.com/maps/search/?api=1&query=" & GetAsURLEncoded ( Substitute ( Contacts::Address ; ¶ ; ", " ) )' }]]);
    b.script('Show Favorites', [['Set Error Capture', { on: true }], ['Perform Find', { requests: [{ omit: false, crit: { [k('Favorite')]: '==Favorite' } }] }], ['If', { calc: 'Get ( LastError ) ≠ 0' }], ['Show Custom Dialog', { dialog: { title: '"Favorites"', message: '"No favorites yet. Tick the star on a contact to add one."', buttons: [{ label: '"OK"' }] } }], ['Show All Records'], ['End If']]);
    b.script('Contacts by Category Report', [['Go to Layout', { layout: { how: 'id', id: L.rep } }], ['Show All Records'], ['Sort Records', { sort: [{ key: k('Category'), dir: 'vl', vl: vCat.id }, { key: k('Last Name'), dir: 'asc' }], dialog: false }], ['Enter Preview Mode']]);
    const tabs = { id: FM.uid('o'), type: 'tab', x: 20, y: 268, w: 660, h: 210, tabHeight: 28, tabs: [
      { id: FM.uid('b'), label: 'Address', children: [T('Street', 30, 310, 80), F(k('Street'), 120, 308, 300, 22), T('City', 30, 338, 80), F(k('City'), 120, 336, 160, 22), F(k('State'), 284, 336, 50, 22, { placeholder: 'ST' }), F(k('Zip'), 338, 336, 82, 22, { placeholder: 'Zip' }), Object.assign(B('Map', 440, 307, 90, script(b, 'Map Address')), { icon: 'web' })] },
      { id: FM.uid('b'), label: 'Notes', children: [F(k('Notes'), 30, 306, 640, 160, { placeholder: 'Notes' })] },
      { id: FM.uid('b'), label: 'Details', children: [T('Birthday', 30, 310, 80), F(k('Birthday'), 120, 308, 130, 22, { control: 'calendar' }), T('Age', 260, 310, 40), F(k('Age'), 310, 308, 60, 22), T('Created', 30, 340, 80), F(k('CreationTimestamp'), 120, 338, 200, 22, { entryBrowse: false }), T('Modified', 30, 368, 80), F(k('ModificationTimestamp'), 120, 366, 200, 22, { entryBrowse: false }), T('by', 330, 368, 30), F(k('ModifiedBy'), 366, 366, 140, 22, { entryBrowse: false })] }] };
    b.layout({ id: L.det, name: 'Contact Details', to: b.toByName.Contacts.id, theme: 'apex', width: 700, views: { form: true, list: true, table: true }, view: 'form', triggers: {}, autoAdd: false,
      parts: [header(92), part('body', 400), part('footer', 30)],
      objects: [title('Contacts'), ...navBar(b, 54, [['New Contact', script(b, 'New Contact')], ['Email', script(b, 'Email Contact')], ['Favorites', script(b, 'Show Favorites')], ['Report', script(b, 'Contacts by Category Report')]]),
        F(k('Photo'), 20, 108, 130, 150, { fit: 'cover' }),
        F(k('First Name'), 170, 108, 200, 26, { placeholder: 'First', style: { size: 15, bold: true } }), F(k('Last Name'), 376, 108, 220, 26, { placeholder: 'Last', style: { size: 15, bold: true } }),
        F(k('Favorite'), 600, 110, 90, 22, { control: 'checkbox', valueList: vFav.id, tooltip: '"Mark as a favorite"' }),
        T('Company', 170, 144, 80), F(k('Company'), 260, 142, 336, 22), T('Title', 170, 172, 80), F(k('Title'), 260, 170, 336, 22),
        T('Email', 170, 200, 80), F(k('Email'), 260, 198, 336, 22), T('Phone', 170, 228, 80), F(k('Phone'), 260, 226, 160, 22), F(k('Mobile'), 426, 226, 170, 22, { placeholder: 'Mobile' }),
        F(k('Category'), 610, 142, 70, 22, { control: 'popup', valueList: vCat.id, placeholder: 'Category' }), tabs] });
    b.layout({ id: L.list, name: 'Contact List', to: b.toByName.Contacts.id, theme: 'apex', width: 700, views: { form: true, list: true, table: true }, view: 'list', triggers: {},
      parts: [header(84), part('body', 30), part('trailing_grand', 30), part('footer', 28)],
      objects: [title('Contact List'), ...[['Name', 20, 190], ['Company', 216, 170], ['Phone', 392, 120], ['Email', 518, 170]].map(([t, x, w]) => T(t, x, 64, w, 16, { align: 'left', bold: true })),
        F(k('Full Name'), 20, 88, 190, 22, { style: { lineWidth: 0, fill: 'transparent', bold: true } }), F(k('Company'), 216, 88, 170, 22, { style: { lineWidth: 0, fill: 'transparent' } }), F(k('Phone'), 392, 88, 120, 22, { style: { lineWidth: 0, fill: 'transparent' } }), F(k('Email'), 518, 88, 170, 22, { style: { lineWidth: 0, fill: 'transparent' } }),
        T('<<Contact Count>> contacts', 20, 120, 300, 18, { align: 'left', color: '#5b6573' })] });
    const auto = FM.design.autoLayout(b.file(), { name: 'Contacts Table', to: b.toByName.Contacts.id, kind: 'table', keys: ['First Name', 'Last Name', 'Company', 'Category', 'Email', 'Phone', 'City', 'State'].map(k) });
    auto.id = L.tbl; b.layout(auto);
    b.layout({ id: L.rep, name: 'Contacts by Category', to: b.toByName.Contacts.id, theme: 'classic', width: 540, views: { form: false, list: true, table: true }, view: 'list', triggers: {},
      parts: [header(56), part('sub_leading', 30, { breakKey: k('Category') }), part('body', 22), part('sub_trailing', 26, { breakKey: k('Category') }), part('footer', 26)],
      objects: [title('Contacts by Category'), F(k('Category'), 20, 60, 300, 22, { style: { bold: true, size: 14, lineWidth: 0, fill: 'transparent' } }), F(k('Full Name'), 40, 87, 200, 20, { style: { lineWidth: 0, fill: 'transparent' } }), F(k('Company'), 244, 87, 160, 20, { style: { lineWidth: 0, fill: 'transparent' } }), F(k('Phone'), 408, 87, 120, 20, { style: { lineWidth: 0, fill: 'transparent' } }),
        T('<<Contact Count>> in <<Category>>', 40, 111, 300, 18, { align: 'left', italic: true }), T('Page {{PageNumber}}', 420, 138, 110, 16, { size: 10, color: '#7a8594' })] });
    b.fileOptions = { openLayout: L.det, autoLogin: { enabled: true, account: 'Admin' }, color: '#2fa36b' };
    [['Ada', 'Lovelace', 'Analytical Engines Ltd', 'Founder', 'Partner', 'ada@example.com', '(239) 555-0101', '1815-12-10', 'Naples', 'FL', '1'], ['Grace', 'Hopper', 'Compiler Co', 'Rear Admiral', 'Customer', 'grace@example.com', '(239) 555-0102', '1906-12-09', 'Bonita Springs', 'FL', ''], ['Alan', 'Turing', 'Bletchley Partners', 'Researcher', 'Vendor', 'alan@example.com', '(239) 555-0103', '1912-06-23', 'Fort Myers', 'FL', ''], ['Katherine', 'Johnson', 'Orbital Math', 'Analyst', 'Customer', 'katherine@example.com', '(239) 555-0104', '1918-08-26', 'Naples', 'FL', '1'], ['Linus', 'Torvalds', 'Kernel Works', 'Engineer', 'Vendor', 'linus@example.com', '(239) 555-0105', '1969-12-28', 'Estero', 'FL', ''], ['Margaret', 'Hamilton', 'Apollo Software', 'Director', 'Customer', 'margaret@example.com', '(239) 555-0106', '1936-08-17', 'Marco Island', 'FL', ''], ['Tim', 'Berners-Lee', 'Web Foundation', 'Director', 'Partner', 'tim@example.com', '(239) 555-0107', '1955-06-08', 'Naples', 'FL', ''], ['Hedy', 'Lamarr', 'Frequency Labs', 'Inventor', 'Friend', 'hedy@example.com', '(239) 555-0108', '1914-11-09', 'Naples', 'FL', '1']]
      .forEach(c => b.rec('Contacts', { 'First Name': c[0], 'Last Name': c[1], Company: c[2], Title: c[3], Category: c[4], Email: c[5], Phone: c[6], Birthday: c[7], City: c[8], State: c[9], Favorite: c[10] ? 'Favorite' : '', Street: Math.floor(100 + Math.random() * 900) + ' Main St', Zip: '341' + Math.floor(Math.random() * 90 + 10), PrimaryKey: uuid() }));
    return b.out();
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Tasks & Projects
  // ═══════════════════════════════════════════════════════════════════════
  function tasks() {
    const b = Builder('Tasks');
    b.table('Projects', [['ProjectID', 'number', serial(1)], ['Project Name', 'text', { validation: { notEmpty: true, when: 'always' } }], ['Description', 'text'], ['Start Date', 'date'], ['Target Date', 'date'],
      ['Task Count', 'calculation', calc('Count ( Tasks::TaskID )', 'number', false)], ['Open Tasks', 'calculation', calc('ExecuteSQL ( "SELECT COUNT(*) FROM Tasks WHERE ProjectID = ? AND Status <> \'Complete\'" ; "" ; "" ; ProjectID )', 'number', false)],
      ['Percent Complete', 'calculation', calc('If ( Task Count = 0 ; 0 ; Round ( ( Task Count - Open Tasks ) / Task Count ; 2 ) )', 'number', false)]]);
    b.table('Tasks', [['TaskID', 'number', serial(1)], ['ProjectID', 'number'], ['Task', 'text', { validation: { notEmpty: true, when: 'always' } }], ['Status', 'text', { autoEnter: { data: 'Not Started' } }], ['Priority', 'text', { autoEnter: { data: 'Medium' } }], ['Assigned To', 'text', { autoEnter: { creation: 'account' } }], ['Due Date', 'date'], ['Hours', 'number'], ['Notes', 'text'],
      ['Overdue', 'calculation', calc('If ( Status ≠ "Complete" and not IsEmpty ( Due Date ) and Due Date < Get ( CurrentDate ) ; 1 ; 0 )', 'number', false)], ['Days Left', 'calculation', calc('If ( IsEmpty ( Due Date ) or Status = "Complete" ; "" ; Due Date - Get ( CurrentDate ) )', 'number', false)],
      ['Project Name', 'calculation', calc('Projects::Project Name', 'text', false)], ['Total Hours', 'summary', { summary: { op: 'total', field: '' } }], ['Task Count', 'summary', { summary: { op: 'count', field: '' } }]]);
    b.f('Tasks', 'Total Hours').options.summary.field = b.f('Tasks', 'Hours').id;
    b.f('Tasks', 'Task Count').options.summary.field = b.f('Tasks', 'TaskID').id;
    b.to('Projects', 'Projects', 60, 60, '#e4dcf7'); b.to('Tasks', 'Tasks', 320, 60, '#d5e3f7');
    b.rel('Projects', 'ProjectID', 'Tasks', 'ProjectID', { right: { create: true, delete: true, sort: [{ fid: b.f('Tasks', 'Due Date').id, dir: 'asc' }] } });
    const vS = b.vl('Status', { type: 'custom', values: ['Not Started', 'In Progress', 'Waiting', 'Complete'] });
    const vP = b.vl('Priority', { type: 'custom', values: ['High', 'Medium', 'Low'] });
    const vProj = b.vl('Projects', { type: 'field', field: { key: b.key('Projects', 'ProjectID'), key2: b.key('Projects', 'Project Name'), showOnly2: true, sortBy: 2 } });
    const tk = n => b.key('Tasks', n), pk = n => b.key('Projects', n);
    const L = { task: FM.uid('L'), list: FM.uid('L'), proj: FM.uid('L'), rep: FM.uid('L') };
    b.script('Mark Complete', [['Set Field', { field: tk('Status'), calc: '"Complete"' }], ['Commit Records/Requests']]);
    b.script('My Open Tasks', [['Go to Layout', { layout: { how: 'id', id: L.list } }], ['Enter Find Mode'], ['Set Field', { field: tk('Assigned To'), calc: '"==" & Get ( AccountName )' }], ['New Record/Request'], ['Set Field', { field: tk('Status'), calc: '"Complete"' }], ['Omit Record'], ['Set Error Capture', { on: true }], ['Perform Find'], ['If', { calc: 'Get ( LastError ) = 401' }], ['Show Custom Dialog', { dialog: { title: '"My Open Tasks"', message: '"You have no open tasks, " & Get ( AccountName ) & "."', buttons: [{ label: '"OK"' }] } }], ['Show All Records'], ['Else'], ['Sort Records', { sort: [{ key: tk('Priority'), dir: 'vl', vl: vP.id }, { key: tk('Due Date'), dir: 'asc' }], dialog: false }], ['End If']]);
    b.script('Add Task to Project', [['Set Variable', { name: '$project', value: 'Projects::ProjectID' }], ['Go to Layout', { layout: { how: 'id', id: L.task } }], ['New Record/Request'], ['Set Field', { field: tk('ProjectID'), calc: '$project' }], ['Go to Field', { field: tk('Task') }]]);
    b.script('Hours by Project Report', [['Go to Layout', { layout: { how: 'id', id: L.rep } }], ['Show All Records'], ['Sort Records', { sort: [{ key: tk('Project Name'), dir: 'asc' }, { key: tk('Status'), dir: 'vl', vl: vS.id }], dialog: false }], ['Enter Preview Mode']]);
    b.script('Loop: Mark All Found Complete', [['#', { text: 'Demonstrates a loop over the found set' }], ['Go to Record/Request/Page', { which: 'first' }], ['Loop'], ['Set Field', { field: tk('Status'), calc: '"Complete"' }], ['Commit Records/Requests'], ['Go to Record/Request/Page', { which: 'next', exitAfterLast: true }], ['End Loop'], ['Show Custom Dialog', { dialog: { title: '"Done"', message: 'Get ( FoundCount ) & " task(s) marked complete."', buttons: [{ label: '"OK"' }] } }]]);
    b.layout({ id: L.task, name: 'Task', to: b.toByName.Tasks.id, theme: 'enlightened', width: 680, views: { form: true, list: true, table: true }, view: 'form', triggers: {},
      parts: [header(90), part('body', 300), part('footer', 28)],
      objects: [title('Task'), ...navBar(b, 52, [['Mark Complete', script(b, 'Mark Complete')], ['My Open Tasks', script(b, 'My Open Tasks')], ['Report', script(b, 'Hours by Project Report')]]),
        F(tk('Task'), 20, 104, 640, 28, { style: { size: 16, bold: true }, placeholder: 'What needs to be done?' }),
        T('Project', 20, 146, 90), F(tk('ProjectID'), 120, 144, 240, 22, { control: 'popup', valueList: vProj.id }),
        T('Status', 20, 176, 90), F(tk('Status'), 120, 174, 300, 44, { control: 'radio', valueList: vS.id }),
        T('Priority', 20, 228, 90), F(tk('Priority'), 120, 226, 140, 22, { control: 'popup', valueList: vP.id, cond: [{ calc: 'Self = "High"', style: { color: '#b42318', bold: true } }] }),
        T('Due', 380, 146, 80), F(tk('Due Date'), 470, 144, 130, 22, { control: 'calendar', cond: [{ calc: 'Tasks::Overdue', style: { color: '#ffffff', fill: '#d92d20', bold: true } }] }),
        T('Days left', 380, 176, 80), F(tk('Days Left'), 470, 174, 80, 22), T('Assigned', 380, 206, 80), F(tk('Assigned To'), 470, 204, 190, 22), T('Hours', 380, 236, 80), F(tk('Hours'), 470, 234, 80, 22),
        T('Notes', 20, 262, 90), F(tk('Notes'), 120, 260, 540, 110)] });
    b.layout({ id: L.list, name: 'Task List', to: b.toByName.Tasks.id, theme: 'enlightened', width: 760, views: { form: true, list: true, table: true }, view: 'list', triggers: {},
      parts: [header(84), part('body', 30), part('trailing_grand', 30), part('footer', 26)],
      objects: [title('Tasks'), ...navBar(b, 50, [['My Open Tasks', script(b, 'My Open Tasks')], ['Mark Complete', script(b, 'Mark Complete')]]).map(o => Object.assign(o, { x: o.x + 340, y: 16 })),
        ...[['Task', 20, 260], ['Project', 286, 150], ['Status', 442, 100], ['Priority', 548, 70], ['Due', 624, 100]].map(([t, x, w]) => T(t, x, 62, w, 16, { align: 'left', bold: true })),
        F(tk('Task'), 20, 88, 260, 22, { style: { lineWidth: 0, fill: 'transparent' }, cond: [{ calc: 'Tasks::Status = "Complete"', style: { color: '#98a2b3' } }] }), F(tk('Project Name'), 286, 88, 150, 22, { style: { lineWidth: 0, fill: 'transparent' } }),
        F(tk('Status'), 442, 88, 100, 22, { control: 'popup', valueList: vS.id }), F(tk('Priority'), 548, 88, 70, 22, { style: { lineWidth: 0, fill: 'transparent' }, cond: [{ calc: 'Self = "High"', style: { color: '#b42318', bold: true } }] }),
        F(tk('Due Date'), 624, 88, 100, 22, { style: { lineWidth: 0, fill: 'transparent' }, cond: [{ calc: 'Tasks::Overdue', style: { color: '#b42318', bold: true } }] }),
        Object.assign(B('', 730, 88, 24, script(b, 'Mark Complete')), { icon: 'check', h: 22, tooltip: '"Mark complete"', style: { fill: 'transparent', lineWidth: 0 } }),
        T('<<Task Count>> tasks · <<Total Hours>> hours', 20, 120, 400, 18, { align: 'left', color: '#5b6573' })] });
    const tp = { id: FM.uid('o'), type: 'portal', to: b.toByName.Tasks.id, x: 20, y: 230, w: 440, h: 220, rows: 10, allowDelete: true, scroll: true, alt: true, children: [F(tk('Task'), 24, 232, 220, 20), F(tk('Status'), 248, 232, 100, 20, { control: 'popup', valueList: vS.id }), F(tk('Due Date'), 352, 232, 100, 20, { cond: [{ calc: 'Tasks::Overdue', style: { color: '#b42318', bold: true } }] })] };
    b.layout({ id: L.proj, name: 'Projects', to: b.toByName.Projects.id, theme: 'enlightened', width: 720, views: { form: true, list: true, table: true }, view: 'form', triggers: {},
      parts: [header(90), part('body', 380), part('footer', 28)],
      objects: [title('Project'), ...navBar(b, 52, [['Add Task', script(b, 'Add Task to Project')], ['Report', script(b, 'Hours by Project Report')]]),
        F(pk('Project Name'), 20, 104, 440, 28, { style: { size: 16, bold: true }, placeholder: 'Project name' }), F(pk('Description'), 20, 140, 440, 50, { placeholder: 'Description' }),
        T('Start', 470, 106, 60), F(pk('Start Date'), 540, 104, 150, 22, { control: 'calendar' }), T('Target', 470, 134, 60), F(pk('Target Date'), 540, 132, 150, 22, { control: 'calendar' }),
        T('Done', 470, 162, 60), F(pk('Percent Complete'), 540, 160, 150, 22, { format: { number: { kind: 'percent', decimals: 0 } } }),
        T('Tasks (type in the last row to add one)', 20, 206, 440, 18, { align: 'left', bold: true }), tp,
        { id: FM.uid('o'), type: 'chart', x: 476, y: 206, w: 224, h: 244, chart: { type: 'donut', title: 'Tasks by status', source: 'related', relTO: b.toByName.Tasks.id, x: 'Tasks::Status', group: true, series: [{ name: 'Tasks', calc: '1' }] } }] });
    b.layout({ id: L.rep, name: 'Hours by Project', to: b.toByName.Tasks.id, theme: 'classic', width: 540, views: { form: false, list: true, table: true }, view: 'list', triggers: {},
      parts: [header(56), part('sub_leading', 30, { breakKey: tk('Project Name') }), part('body', 22), part('sub_trailing', 26, { breakKey: tk('Project Name') }), part('trailing_grand', 30), part('footer', 24)],
      objects: [title('Hours by Project'), F(tk('Project Name'), 20, 60, 340, 22, { style: { bold: true, size: 14, lineWidth: 0, fill: 'transparent' } }), F(tk('Task'), 40, 87, 260, 20, { style: { lineWidth: 0, fill: 'transparent' } }), F(tk('Status'), 304, 87, 110, 20, { style: { lineWidth: 0, fill: 'transparent' } }), F(tk('Hours'), 420, 87, 80, 20, { style: { lineWidth: 0, fill: 'transparent', align: 'right' } }),
        T('Project hours', 300, 111, 110, 18, { bold: true }), F(tk('Total Hours'), 420, 110, 80, 20, { style: { lineWidth: 0, fill: 'transparent', bold: true, align: 'right' } }),
        T('All projects', 300, 140, 110, 18, { bold: true, color: '#1d2733' }), F(tk('Total Hours'), 420, 138, 80, 22, { style: { lineWidth: 0, fill: 'transparent', bold: true, align: 'right', size: 13 } })] });
    b.fileOptions = { openLayout: L.list, autoLogin: { enabled: true, account: 'Admin' }, color: '#7a5cd6' };
    [['Spring irrigation audit', 'Check every zone at the HOAs before the dry season', -20, 30], ['Pump station upgrades', 'Replace aging VFDs at two stations', -40, 60], ['Office move', 'New warehouse and office', -5, 45]].forEach((p, i) => b.rec('Projects', { ProjectID: String(i + 1), 'Project Name': p[0], Description: p[1], 'Start Date': day(p[2]), 'Target Date': day(p[3]), PrimaryKey: uuid() }));
    [[1, 'Walk Lakeside Pines zones 1–12', 'Complete', 'High', 'admin', -10, 6], [1, 'Replace broken rotor heads', 'In Progress', 'Medium', 'admin', 3, 4], [1, 'Send audit report to board', 'Not Started', 'High', 'admin', -1, 2], [1, 'Adjust controller schedules', 'Waiting', 'Low', 'casey', 12, 1.5], [2, 'Quote VFD replacements', 'Complete', 'High', 'casey', -15, 3], [2, 'Schedule station 3 shutdown', 'In Progress', 'Medium', 'admin', 5, 1], [2, 'Install new VFD at station 3', 'Not Started', 'High', 'casey', 20, 8], [3, 'Order shelving', 'Complete', 'Low', 'admin', -3, 1], [3, 'Move inventory', 'Not Started', 'Medium', 'casey', 9, 16], [3, 'Set up network', 'Waiting', 'Medium', 'admin', 4, 5]]
      .forEach((t, i) => b.rec('Tasks', { TaskID: String(i + 1), ProjectID: String(t[0]), Task: t[1], Status: t[2], Priority: t[3], 'Assigned To': t[4] === 'admin' ? 'Admin' : t[4], 'Due Date': day(t[5]), Hours: String(t[6]), PrimaryKey: uuid() }));
    return b.out();
  }

  // ═══════════════════════════════════════════════════════════════════════
  // blank file: one table named after the file, like FileMaker
  // ═══════════════════════════════════════════════════════════════════════
  function blank(name) {
    const b = Builder(name);
    const tname = (String(name).replace(/[^\w ]+/g, ' ').trim() || 'Table').slice(0, 60);
    b.table(tname, []);
    const o = b.to(tname, tname, 60, 60);
    const lay = FM.design.autoLayout(b.file(), { name: tname, to: o.id, kind: 'form', keys: [] });
    lay.autoAdd = true;
    lay.objects.push({ id: FM.uid('o'), type: 'text', text: 'Choose File > Manage > Database to add fields. New fields appear on this layout.', x: 20, y: 90, w: 600, h: 20, style: { color: '#7a8594', size: 12, italic: true } });
    b.layout(lay);
    b.fileOptions = { openLayout: lay.id, autoLogin: { enabled: true, account: 'Admin' } };
    return b.out();
  }
  // a file made from a spreadsheet's rows
  function fromRows(name, rows, header) {
    const b = Builder(name);
    const tname = (String(name).replace(/\.[^.]+$/, '').replace(/[^\w ]+/g, ' ').trim() || 'Imported').slice(0, 60);
    const ncols = Math.max(0, ...rows.map(r => r.length));
    const heads = header ? rows[0] : [];
    const data = header ? rows.slice(1) : rows;
    const defs = [];
    const seen = new Set(['primarykey', 'creationtimestamp', 'createdby', 'modificationtimestamp', 'modifiedby']);
    for (let c = 0; c < ncols; c++) {
      let n = String(heads[c] || 'f' + (c + 1)).trim().replace(/::/g, ' ') || 'f' + (c + 1);
      let base = n, i = 2; while (seen.has(n.toLowerCase())) n = base + ' ' + i++;
      seen.add(n.toLowerCase());
      const sample = data.slice(0, 80).map(r => r[c]).filter(v => v != null && String(v).trim() !== '');
      const type = sample.length && sample.every(v => /^-?\d+(\.\d+)?$/.test(String(v).trim())) ? 'number' : sample.length && sample.every(v => /^\d{4}-\d{2}-\d{2}$/.test(String(v).trim()) || (/^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(String(v).trim()) && D.parseDate(v) != null)) ? 'date' : 'text';
      defs.push([n, type]);
    }
    b.table(tname, defs);
    const o = b.to(tname, tname, 60, 60);
    const keys = defs.map(d => b.key(tname, d[0]));
    const form = FM.design.autoLayout(b.file(), { name: tname, to: o.id, kind: 'form', keys }); form.autoAdd = true;
    const table = FM.design.autoLayout(b.file(), { name: tname + ' Table', to: o.id, kind: 'table', keys: keys.slice(0, 12) });
    b.layout(table); b.layout(form);
    data.forEach(r => { const rec = { PrimaryKey: uuid() }; defs.forEach(([n, type], c) => { let v = r[c] == null ? '' : String(r[c]); if (type === 'date' && v) { const d = D.parseDate(v); if (d != null) v = D.isoDate(d); } rec[n] = v; }); b.rec(tname, rec); });
    b.fileOptions = { openLayout: table.id, autoLogin: { enabled: true, account: 'Admin' } };
    return b.out();
  }

  FM.starters = {
    list: [
      { key: 'invoices', name: 'Invoices', icon: 'preview', color: '#2a6fdb', desc: 'Customers, products, invoices and line items: portals, lookups, calculations, a sub-summary report with a chart, and scripts.', build: invoices },
      { key: 'contacts', name: 'Contacts', icon: 'users', color: '#2fa36b', desc: 'A contact manager with photos, tab controls, list and table views, a category report, and email/map scripts.', build: contacts },
      { key: 'tasks', name: 'Tasks & Projects', icon: 'check', color: '#7a5cd6', desc: 'Projects with a task portal, status radio buttons, conditional formatting, ExecuteSQL, loops and a report.', build: tasks }
    ],
    blank, fromRows
  };
})();
