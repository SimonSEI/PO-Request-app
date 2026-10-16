"""The Vendor Invoices page (one HTML page; the data comes from /vendor-invoices/api/...)."""

PAGE_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vendor Invoices — Stahlman-England</title>
<meta name="csrf-token" content="{{ csrf_token() }}">
<style>
  :root { --brand:#0E7490; --brand-dark:#155E75; --ink:#0F172A; --ink2:#475569; --ink3:#94A3B8; --bg:#F8FAFC;
          --card:#FFF; --line:#E2E8F0; --warn:#B45309; --warn-bg:#FFFBEB; --bad:#DC2626; --bad-bg:#FEF2F2;
          --ok:#047857; --ok-bg:#ECFDF5; --blue:#2563EB; --xl-grid:#D4D4D4; --xl-head:#F3F3F3; --xl-sel:#217346; }
  *,*::before,*::after { box-sizing:border-box; }
  body { margin:0; font-family:Inter,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; background:var(--bg);
         color:var(--ink); font-size:14px; line-height:1.45; }
  header { background:var(--card); border-bottom:1px solid var(--line); padding:10px 16px; display:flex; align-items:center;
           gap:10px; flex-wrap:wrap; }
  header .brand { font-weight:700; font-size:17px; }
  header .spacer { flex:1; }
  a { color:var(--blue); } a.back { color:var(--ink2); text-decoration:none; }
  .soon { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.6px; background:#FEF3C7; color:#92400E;
          border:1px solid #FDE68A; padding:2px 8px; border-radius:100px; }
  main { padding:12px 16px 0; }
  button { font:inherit; border:1px solid var(--line); background:var(--card); border-radius:8px; padding:6px 12px; cursor:pointer;
           color:var(--ink); white-space:nowrap; }
  button:hover { border-color:#CBD5E1; background:#F8FAFC; }
  button.primary { background:var(--brand); color:#fff; border-color:var(--brand); }
  button.primary:hover { background:var(--brand-dark); }
  button.sm { padding:2px 8px; font-size:12px; border-radius:6px; }
  button.danger { color:var(--bad); }
  button:disabled { opacity:.5; cursor:default; }
  input, select, textarea { font:inherit; border:1px solid var(--line); border-radius:8px; padding:6px 9px; background:#fff; color:var(--ink); }
  label { display:block; font-weight:600; font-size:12px; color:var(--ink2); margin:10px 0 4px; }
  .muted { color:var(--ink2); } .small { font-size:12px; }
  .status { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; align-items:center; }
  .chip { border-radius:999px; padding:2px 10px; font-size:12px; font-weight:600; border:1px solid var(--line); background:var(--card); }
  .chip.ok { color:var(--ok); background:var(--ok-bg); border-color:#A7F3D0; }
  .chip.no { color:var(--bad); background:var(--bad-bg); border-color:#FECACA; }
  .chip.warn { color:var(--warn); background:var(--warn-bg); border-color:#FDE68A; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin-bottom:12px; }
  details.card > summary { cursor:pointer; font-weight:700; list-style:none; display:flex; gap:8px; align-items:center; }
  details.card > summary::-webkit-details-marker { display:none; }
  details.card > summary::before { content:'▸'; color:var(--ink3); }
  details.card[open] > summary::before { content:'▾'; }
  .count { background:var(--bad); color:#fff; border-radius:999px; padding:0 7px; font-size:12px; }
  .count.zero { background:#E2E8F0; color:var(--ink2); }
  table.list { width:100%; border-collapse:collapse; margin-top:8px; font-size:13px; }
  table.list th, table.list td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
  table.list th { font-size:12px; color:var(--ink2); font-weight:600; background:#F8FAFC; white-space:nowrap; }
  table.list td.num { text-align:right; white-space:nowrap; }
  table.list tr.done td { color:var(--ink3); }
  .late { color:var(--bad); font-weight:700; }
  .acts { display:flex; gap:4px; flex-wrap:wrap; }
  .list-wrap { overflow-x:auto; }

  /* ── the sheet ── */
  .toolbar { display:flex; gap:6px; align-items:center; flex-wrap:wrap; background:#fff; border:1px solid var(--line);
             border-bottom:none; border-radius:10px 10px 0 0; padding:6px 8px; }
  .toolbar .sep { width:1px; height:22px; background:var(--line); margin:0 4px; }
  .swatch { width:22px; height:22px; border-radius:4px; border:1px solid #CBD5E1; cursor:pointer; padding:0; }
  .swatch.none { background:linear-gradient(135deg,#fff 45%,#DC2626 47%,#DC2626 53%,#fff 55%); }
  .fbar { display:flex; align-items:stretch; border:1px solid var(--line); border-bottom:none; background:#fff; }
  .fbar .ref { width:70px; text-align:center; padding:4px; border-right:1px solid var(--line); font-weight:600; color:var(--ink2);
               font-family:Calibri,Arial,sans-serif; }
  .fbar .fx { padding:4px 8px; color:var(--ink3); font-style:italic; border-right:1px solid var(--line); }
  .fbar input { flex:1; border:none; border-radius:0; padding:4px 8px; font-family:Calibri,Arial,sans-serif; font-size:14px; }
  .fbar input:focus { outline:2px solid var(--xl-sel); outline-offset:-2px; }
  .sheet-wrap { overflow:auto; background:#fff; border:1px solid var(--line); height:calc(100vh - 250px); min-height:360px; position:relative; }
  table.xl { border-collapse:separate; border-spacing:0; table-layout:fixed; font-family:Calibri,'Segoe UI',Arial,sans-serif;
             font-size:14.5px; color:#000; }
  table.xl td, table.xl th { border-right:1px solid var(--xl-grid); border-bottom:1px solid var(--xl-grid); padding:1px 4px;
             overflow:hidden; white-space:nowrap; text-overflow:clip; height:21px; vertical-align:bottom; }
  table.xl thead th { position:sticky; z-index:3; }
  table.xl thead tr.letters th { top:0; background:var(--xl-head); color:#555; font-weight:400; text-align:center; font-size:12px; height:20px; }
  table.xl thead tr.head th { top:21px; background:#FFFF00; font-weight:700; text-align:center; white-space:normal;
             vertical-align:middle; height:48px; line-height:1.1; font-size:13.5px; }
  table.xl .rn { position:sticky; left:0; z-index:2; background:var(--xl-head); color:#555; text-align:center; font-size:12px;
             width:42px; min-width:42px; }
  table.xl thead .rn { z-index:4; }
  table.xl td.spacer, table.xl th.spacer { background:#F1F1F1; padding:0; }
  table.xl thead tr.head th.spacer { background:#FFFF00; }
  table.xl td.r { text-align:right; }
  table.xl td.wrap { white-space:normal; }
  table.xl td.merged { vertical-align:middle; white-space:normal; }
  table.xl td.sel { outline:2px solid var(--xl-sel); outline-offset:-2px; }
  table.xl tr.selrow td.rn { background:#D3F0E0; color:var(--xl-sel); font-weight:700; }
  table.xl tr.hit td:not(.rn):not(.jb) { box-shadow:inset 0 0 0 9999px rgba(250,204,21,.25); }
  table.xl td .acct { display:flex; justify-content:space-between; gap:4px; }
  table.xl td input.ed { width:100%; border:none; padding:0; margin:0; font:inherit; background:#fff; outline:none; border-radius:0; }
  table.xl tfoot td { position:sticky; bottom:0; background:#F8FAFC; font-weight:700; border-top:2px solid #94A3B8; z-index:2; }
  table.xl tfoot td.rn { z-index:3; }
  table.xl td.jb, table.xl th.jb { background:#F8FAFC; font-family:Inter,-apple-system,'Segoe UI',Arial,sans-serif; font-size:12px;
             white-space:nowrap; }
  table.xl thead tr.head th.jb { background:#E0F2FE; color:#075985; }
  table.xl thead tr.letters th.jb { color:#075985; }
  .jchip { display:inline-flex; gap:4px; align-items:center; border-radius:6px; padding:0 6px; font-weight:600; cursor:pointer;
           border:1px solid var(--line); background:#fff; }
  .jchip.paid { color:var(--ok); background:var(--ok-bg); border-color:#A7F3D0; }
  .jchip.open { color:var(--blue); background:#EFF6FF; border-color:#BFDBFE; }
  .jlink { color:var(--ink3); cursor:pointer; border:1px dashed #CBD5E1; border-radius:6px; padding:0 6px; background:#fff; font-size:12px; }
  .jlink.sug { color:var(--brand-dark); border-color:#99F6E4; background:#F0FDFA; }
  .tabs-bar { display:flex; align-items:stretch; background:var(--xl-head); border:1px solid var(--line); border-top:none;
              border-radius:0 0 10px 10px; overflow-x:auto; position:sticky; bottom:0; }
  .tabs-bar .add { border:none; border-right:1px solid var(--line); border-radius:0; background:transparent; font-size:18px; padding:2px 12px; color:var(--xl-sel); }
  .sheet-tab { padding:5px 14px; cursor:pointer; white-space:nowrap; font-size:13px; color:#333; border-right:1px solid #D4D4D4;
               font-family:Calibri,'Segoe UI',Arial,sans-serif; }
  .sheet-tab:hover { background:#E8E8E8; }
  .sheet-tab.active { background:#fff; color:var(--xl-sel); font-weight:700; border-bottom:3px solid var(--xl-sel); }
  .results { background:#fff; border:1px solid var(--line); height:calc(100vh - 250px); min-height:360px; overflow:auto; }
  .results table.list td { cursor:pointer; }
  .results table.list tr:hover td { background:#F0FDFA; }

  .modal-bg { position:fixed; inset:0; background:rgba(15,23,42,.45); display:none; align-items:flex-start; justify-content:center;
              z-index:50; padding:40px 12px; overflow:auto; }
  .modal-bg.show { display:flex; }
  .modal { background:#fff; border-radius:12px; width:100%; max-width:760px; padding:18px 20px; box-shadow:0 20px 50px rgba(0,0,0,.25); }
  .modal h3 { margin:0 0 6px; }
  .modal .foot { display:flex; gap:8px; justify-content:flex-end; margin-top:14px; }
  .grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:4px 14px; }
  .toast { position:fixed; bottom:56px; left:50%; transform:translateX(-50%); background:#0F172A; color:#fff; padding:8px 16px;
           border-radius:8px; font-size:13px; z-index:60; display:none; max-width:90vw; }
  .log { max-height:220px; overflow:auto; font-size:12px; border:1px solid var(--line); border-radius:8px; padding:6px 8px; }
  @media (max-width:640px) { header .brand { font-size:15px; } .sheet-wrap, .results { height:65vh; } }
</style>
</head>
<body>
<header>
  <a class="back" href="/dashboard">← Office App</a>
  <span class="brand">Vendor Invoices</span>
  <span class="soon">Coming soon</span>
  <span class="spacer"></span>
  <input id="search" type="search" placeholder="Search every month: vendor, invoice #, proposal, notes…" style="width:340px;max-width:100%">
  <button id="btn-scan" title="Read new mail in PO@ now">Check PO@</button>
  <button id="btn-jobber" title="Ask Jobber whether linked invoices are paid">Check Jobber</button>
  <a href="/vendor-invoices/api/export"><button>Download .xlsx</button></a>
  <button id="btn-upload">Upload workbook</button>
  <button id="btn-settings">Settings</button>
</header>
<main>
  <div class="status" id="status"></div>

  <details class="card" id="inbox-card" open>
    <summary>Invoices that came into PO@ <span class="count" id="inbox-count">0</span>
      <span class="muted small" style="font-weight:400" id="inbox-hint"></span></summary>
    <div id="inbox"></div>
  </details>

  <div class="toolbar">
    <span class="small muted">Fill</span>
    <button class="swatch none" title="No fill" data-bg=""></button>
    {% for hex, name in colors %}<button class="swatch" title="{{ name }}" data-bg="{{ hex }}" style="background:#{{ hex }}"></button>{% endfor %}
    <span class="sep"></span>
    <button class="sm" id="btn-bold" title="Bold (Ctrl+B)"><b>B</b></button>
    <button class="sm" id="btn-red" title="Red text" style="color:#FF0000;font-weight:700">A</button>
    <button class="sm" id="btn-black" title="Black text" style="font-weight:700">A</button>
    <span class="sep"></span>
    <button class="sm" id="btn-row-color" title="Use the selected cell's fill for the whole row">Fill whole row</button>
    <span class="sep"></span>
    <button class="sm primary" id="btn-add-row">+ Add invoice</button>
    <button class="sm" id="btn-insert-row">Insert row below</button>
    <button class="sm danger" id="btn-del-row">Delete row</button>
    <span class="sep"></span>
    <button class="sm" id="btn-link">Link Jobber invoice…</button>
  </div>
  <div class="fbar"><div class="ref" id="ref">A2</div><div class="fx">fx</div><input id="fx" autocomplete="off"></div>
  <div class="sheet-wrap" id="sheet-wrap"><table class="xl" id="sheet"></table></div>
  <div class="results" id="results" style="display:none"></div>
  <div class="tabs-bar" id="tabs"></div>
  <p class="small muted" style="margin:8px 2px 16px">Click a cell and type to change it — Enter saves, Esc cancels, arrows move. Dates can be typed
    as 9/17/26. “OK TO PROCESS?” turns green for YES and red for NO, like the workbook. The <b>JOBBER INVOICE</b> column is new: link a row
    to the SEI invoice in Jobber and Christian is emailed when it's paid.</p>
</main>

<div class="modal-bg" id="m-link"><div class="modal">
  <h3>Link to a Jobber invoice</h3>
  <div class="muted small" id="link-row"></div>
  <div style="display:flex;gap:8px;margin-top:10px"><input id="link-q" placeholder="Jobber invoice #, client or job" style="flex:1">
    <button class="primary" id="link-go">Search Jobber</button></div>
  <div id="link-results" class="list-wrap"></div>
  <div class="foot"><button data-close>Close</button></div>
</div></div>

<div class="modal-bg" id="m-upload"><div class="modal">
  <h3>Upload a vendor invoices workbook</h3>
  <p class="muted small">Every month tab of the workbook is brought in with its colors, bold and red text and merged cells. Tabs that are
    already here (same name) are left alone unless you tick “Replace”. The MASTER COPY BLANK tab is skipped — “+” on the tab bar makes a new month.</p>
  <input type="file" id="up-file" accept=".xlsx,.xlsm">
  <label style="display:flex;gap:6px;align-items:center;font-weight:400"><input type="checkbox" id="up-replace" style="width:auto">
    Replace tabs that are already here (rows typed here by hand are kept)</label>
  <div id="up-result" class="small" style="margin-top:8px"></div>
  <div class="foot"><button data-close>Close</button><button class="primary" id="up-go">Upload</button></div>
</div></div>

<div class="modal-bg" id="m-settings"><div class="modal">
  <h3>Settings</h3>
  <div class="grid2">
    <div><label>Christian's email (paid and not-entered emails go here)</label><input id="s-christian" type="email" style="width:100%"></div>
    <div><label>Read PO@ mail received from</label><input id="s-since" type="date" style="width:100%"></div>
    <div><label>Email Christian when a vendor invoice isn't entered after (days, 0 = never)</label><input id="s-days" type="number" min="0" style="width:100%"></div>
    <div><label>…and remind again every (days, 0 = once)</label><input id="s-again" type="number" min="0" style="width:100%"></div>
  </div>
  <label>Pump vendors — left to the Pumps app (comma separated)</label><input id="s-pump" style="width:100%">
  <label>Senders you've sorted</label><div id="s-senders" class="small"></div>
  <label>Activity</label><div id="s-log" class="log"></div>
  <div class="foot"><button id="s-alert" title="Send the not-entered email to Christian now">Email Christian what's not entered</button>
    <span style="flex:1"></span><button data-close>Close</button><button class="primary" id="s-save">Save</button></div>
</div></div>

<div class="toast" id="toast"></div>

<script>
var CSRF = document.querySelector('meta[name="csrf-token"]').content;
var COLS = {{ cols|tojson }};   // [letter, key, header, kind, width]
var KEYS = COLS.map(function(c){ return c[1]; });
var S = {tabs:[], tab:null, rows:[], sel:{r:0, c:1}, editing:null, inbox:[], status:{}, layout:null, linkRow:null, searching:false};

function $(id){ return document.getElementById(id); }
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function post(url, body){
  return fetch(url, {method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':CSRF}, body:JSON.stringify(body||{})})
    .then(function(r){ return r.json(); });
}
function get(url){ return fetch(url).then(function(r){ return r.json(); }); }
function toast(msg, ms){ var t = $('toast'); t.textContent = msg; t.style.display = 'block'; clearTimeout(toast._t);
  toast._t = setTimeout(function(){ t.style.display = 'none'; }, ms || 3500); }
function px(w){ return Math.round(w * 7 + 5); }

// ── formatting like Excel ──
var MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function isIso(s){ return /^\d{4}-\d{2}-\d{2}$/.test(s || ''); }
function isNum(s){ return /^-?\d+(\.\d+)?$/.test(s || ''); }
function two(n){ return (n < 10 ? '0' : '') + n; }
function money(n){ return Math.abs(n).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2}); }
function show(key, text, st){
  var kind = KIND[key]; st = st || {};
  if (!text) return {html:'', right:false};
  if (isIso(text) && (kind === 'date' || st.fmt === 'd-mmm' || kind === 'text')) {
    var p = text.split('-');
    if (st.fmt === 'd-mmm') return {html: (+p[2]) + '-' + MON[+p[1]-1], right:true};
    return {html: p[1] + '-' + p[2] + '-' + p[0].slice(2), right:true};
  }
  if ((kind === 'money' || st.fmt === 'money') && isNum(text)) {
    var n = parseFloat(text);
    var v = n === 0 ? '-&nbsp;&nbsp;' : (n < 0 ? '(' + money(n) + ')' : money(n) + '&nbsp;');
    return {html:'<span class="acct"><span>$</span><span>' + v + '</span></span>', right:true};
  }
  return {html: esc(text), right: isNum(text)};
}
function forEdit(key, text){
  if (isIso(text)) { var p = text.split('-'); return (+p[1]) + '/' + (+p[2]) + '/' + p[0]; }
  return text || '';
}
var KIND = {}; COLS.forEach(function(c){ KIND[c[1]] = c[3]; });

// ── loading ──
function loadState(){
  return get('/vendor-invoices/api/state').then(function(j){
    if (!j.success) { toast(j.error || 'Could not load'); return; }
    S.tabs = j.tabs; S.inbox = j.inbox; S.status = j.status;
    renderStatus(); renderInbox(); renderTabs();
  });
}
function openTab(id, selectRowId){
  S.tab = S.tabs.find(function(t){ return t.id === id; }) || S.tabs[0];
  if (!S.tab) { $('sheet').innerHTML = ''; return Promise.resolve(); }
  try { localStorage.setItem('vi_tab', S.tab.id); } catch(e) {}
  renderTabs();
  return get('/vendor-invoices/api/tab/' + S.tab.id).then(function(j){
    S.rows = j.rows || [];
    S.sel = {r: 0, c: 1};
    if (selectRowId) { var i = S.rows.findIndex(function(r){ return r.id === selectRowId; }); if (i >= 0) S.sel.r = i; }
    renderSheet();
    if (selectRowId) scrollToSel(true);
  });
}

// ── status chips ──
function renderStatus(){
  var s = S.status, h = [];
  h.push(s.graph ? '<span class="chip ok">Microsoft 365 connected — ' + esc(s.mailbox) + '</span>'
                 : '<span class="chip no">Microsoft 365 not connected — emails to Christian can\'t be sent</span>');
  h.push(s.jobber ? '<span class="chip ok">Jobber connected</span>' : '<span class="chip warn">Jobber not connected (connect it in Pumps)</span>');
  h.push(s.christian ? '<span class="chip ok">Christian: ' + esc(s.christian) + '</span>' : '<span class="chip no">Christian\'s email not set (Settings)</span>');
  if (s.last_scan) h.push('<span class="chip">PO@ last read ' + esc(s.last_scan.at.slice(5, 16)) + '</span>');
  if (s.last_jobber_check) h.push('<span class="chip">Jobber last checked ' + esc(s.last_jobber_check.at.slice(5, 16)) + '</span>');
  $('status').innerHTML = h.join('');
}

// ── the PO@ inbox ──
function renderInbox(){
  var waiting = S.inbox.filter(function(x){ return x.status === 'received'; });
  var other = S.inbox.filter(function(x){ return x.status === 'other'; });
  var done = S.inbox.filter(function(x){ return x.status === 'inputted' || x.status === 'ignored'; });
  var late = waiting.filter(function(x){ return x.overdue; }).length;
  $('inbox-count').textContent = waiting.length;
  $('inbox-count').className = 'count' + (waiting.length ? '' : ' zero');
  $('inbox-hint').textContent = waiting.length ? (late ? late + ' waiting long enough that Christian is emailed' : 'waiting to be entered on the sheet')
                                               : 'nothing waiting — non-pump vendor invoice PDFs show here as they arrive';
  var tabName = S.tab ? S.tab.label : 'this month';
  function line(x, kind){
    var acts = '';
    if (kind === 'waiting') acts = '<button class="sm primary" data-enter="' + x.id + '">Enter on ' + esc(tabName) + '</button>' +
        '<button class="sm" data-decide="entered" data-id="' + x.id + '">Already on the sheet</button>' +
        '<button class="sm" data-decide="ignore" data-id="' + x.id + '">Not a vendor invoice</button>';
    else if (kind === 'other') acts = '<button class="sm" data-decide="vendor" data-id="' + x.id + '">It\'s a vendor invoice</button>' +
        '<button class="sm" data-decide="ignore" data-id="' + x.id + '">Not a vendor invoice</button>';
    else acts = (x.row_id ? '<button class="sm" data-goto="' + x.row_id + '">Show row</button>' : '') +
        '<button class="sm" data-decide="undo" data-id="' + x.id + '">Undo</button>';
    var days = kind === 'waiting' ? '<span class="' + (x.overdue ? 'late' : '') + '">' + x.days_waiting + 'd</span>' : '';
    return '<tr class="' + (kind === 'done' ? 'done' : '') + '"><td>' + esc(x.received_at.slice(0, 10)) + '</td><td><b>' + esc(x.vendor || '—') +
      '</b><div class="small muted">' + esc(x.sender) + '</div></td><td>' + esc(x.inv_no || '—') + '</td><td>' + esc(x.inv_date || '') +
      '</td><td class="num">' + (x.inv_total != null ? '$' + money(x.inv_total) : '') + '</td><td>' + esc(x.summary || x.subject || '') +
      '</td><td class="num">' + days + (kind === 'done' ? (x.status === 'ignored' ? 'not a vendor invoice' : 'entered') : '') +
      '</td><td><div class="acts"><a href="/vendor-invoices/api/inbox/' + x.id + '/file" target="_blank"><button class="sm">PDF</button></a>' + acts + '</div></td></tr>';
  }
  var head = '<tr><th>Received</th><th>Vendor</th><th>Invoice #</th><th>Inv. date</th><th class="num">Total</th><th>What for</th><th class="num">Waiting</th><th></th></tr>';
  var h = '';
  if (waiting.length) h += '<div class="list-wrap"><table class="list">' + head + waiting.map(function(x){ return line(x, 'waiting'); }).join('') + '</table></div>';
  if (other.length) h += '<p class="small muted" style="margin:12px 0 0"><b>PDFs from senders not on the sheet yet</b> — not counted until someone says they\'re a vendor invoice. ' +
      'The answer is remembered for that sender.</p><div class="list-wrap"><table class="list">' + head + other.map(function(x){ return line(x, 'other'); }).join('') + '</table></div>';
  if (done.length) h += '<details style="margin-top:10px"><summary class="small muted" style="cursor:pointer">Sorted in the last 14 days (' + done.length + ')</summary>' +
      '<div class="list-wrap"><table class="list">' + head + done.map(function(x){ return line(x, 'done'); }).join('') + '</table></div></details>';
  $('inbox').innerHTML = h || '<p class="small muted">Pump invoices (Wettech) stay in the Pumps app.</p>';
}
$('inbox').addEventListener('click', function(e){
  var b = e.target.closest('button'); if (!b) return;
  if (b.dataset.enter) {
    b.disabled = true;
    post('/vendor-invoices/api/inbox/' + b.dataset.enter + '/enter', {tab_id: S.tab && S.tab.id}).then(function(j){
      if (!j.success) { toast(j.error); b.disabled = false; return; }
      toast('Added to ' + S.tab.label + ' — check the row and fill in the rest');
      loadState().then(function(){ openTab(j.row.tab_id, j.row.id); });
    });
  } else if (b.dataset.decide) {
    post('/vendor-invoices/api/inbox/' + b.dataset.id + '/decide', {action: b.dataset.decide}).then(function(j){
      if (!j.success) toast(j.error); loadState();
    });
  } else if (b.dataset.goto) {
    gotoRow(+b.dataset.goto);
  }
});

// ── sheet tabs ──
function renderTabs(){
  var h = '<button class="add" id="tab-add" title="New month tab">+</button>';
  S.tabs.forEach(function(t){
    h += '<div class="sheet-tab' + (S.tab && S.tab.id === t.id ? ' active' : '') + '" data-tab="' + t.id + '" title="' + t.rows + ' rows">' + esc(t.label) + '</div>';
  });
  $('tabs').innerHTML = h;
  var a = $('tabs').querySelector('.sheet-tab.active'); if (a) a.scrollIntoView({block:'nearest', inline:'nearest'});
}
$('tabs').addEventListener('click', function(e){
  if (e.target.id === 'tab-add') {
    var now = new Date(), def = now.toLocaleString('en-US', {month:'long'}).toUpperCase() + ' ' + now.getFullYear();
    var label = prompt('Name of the new month tab', def); if (!label) return;
    post('/vendor-invoices/api/tab/add', {label: label}).then(function(j){
      if (!j.made) toast('That tab is already here');
      loadState().then(function(){ openTab(j.tab_id); });
    });
    return;
  }
  var t = e.target.closest('.sheet-tab'); if (!t) return;
  clearSearch(); openTab(+t.dataset.tab);
});

// ── the grid ──
function layout(){
  // Merged cells: which cells are covered, and the anchor of each.
  var cover = {}, n = S.rows.length;
  S.rows.forEach(function(row, ri){
    Object.keys(row.spans || {}).forEach(function(k){
      var sp = row.spans[k], ci = KEYS.indexOf(k); if (ci < 0) return;
      for (var dr = 0; dr < sp[0] && ri + dr < n; dr++) for (var dc = 0; dc < sp[1] && ci + dc < KEYS.length; dc++)
        if (dr || dc) cover[(ri + dr) + ':' + (ci + dc)] = ri + ':' + ci;
    });
  });
  return cover;
}
function renderSheet(){
  var t = S.tab; if (!t) return;
  var heads = t.headers || {};
  S.layout = layout();
  var h = '<colgroup><col style="width:42px">';
  COLS.forEach(function(c){ h += '<col style="width:' + px(c[4]) + 'px">'; });
  h += '<col style="width:190px"></colgroup><thead><tr class="letters"><th class="rn"></th>';
  COLS.forEach(function(c){ h += '<th class="' + (c[3] === 'spacer' ? 'spacer' : '') + '">' + c[0] + '</th>'; });
  h += '<th class="jb">Q</th></tr><tr class="head"><th class="rn">1</th>';
  COLS.forEach(function(c){ h += '<th class="' + (c[3] === 'spacer' ? 'spacer' : '') + '">' + esc(heads[c[1]] || '') + '</th>'; });
  h += '<th class="jb">JOBBER INVOICE</th></tr></thead><tbody>';
  var tot = {inv_total:0, amt_billed:0};
  S.rows.forEach(function(row, ri){
    h += '<tr data-ri="' + ri + '" class="' + (ri === S.sel.r ? 'selrow' : '') + (row.id === S.hit ? ' hit' : '') + '"><td class="rn">' + (ri + 2) + '</td>';
    COLS.forEach(function(c, ci){
      if (S.layout[ri + ':' + ci]) return;
      var key = c[1], st = (row.style || {})[key] || {}, sp = (row.spans || {})[key];
      var f = show(key, row[key], st), css = [], style = [];
      if (c[3] === 'spacer') css.push('spacer');
      if (f.right) css.push('r');
      if (key === 'notes') css.push('wrap');
      if (sp) css.push('merged');
      if (ri === S.sel.r && ci === S.sel.c) css.push('sel');
      if (st.bg) style.push('background:#' + st.bg);
      if (st.fg) style.push('color:#' + st.fg);
      if (st.b) style.push('font-weight:700');
      h += '<td data-c="' + ci + '" class="' + css.join(' ') + '"' + (style.length ? ' style="' + style.join(';') + '"' : '') +
           (sp ? ' rowspan="' + sp[0] + '" colspan="' + sp[1] + '"' : '') + ' title="' + esc(row[key]) + '">' + f.html + '</td>';
    });
    h += '<td class="jb">' + jobberCell(row) + '</td></tr>';
    if (!row.is_total) ['inv_total', 'amt_billed'].forEach(function(k){ if (isNum(row[k])) tot[k] += parseFloat(row[k]); });
  });
  h += '</tbody><tfoot><tr><td class="rn"></td>';
  COLS.forEach(function(c){
    var v = '';
    if (c[1] === 'vendor') v = 'TAB TOTAL';
    if (c[1] === 'inv_total' || c[1] === 'amt_billed') v = show(c[1], String(Math.round(tot[c[1]] * 100) / 100), {}).html;
    h += '<td class="' + (c[3] === 'spacer' ? 'spacer' : '') + '">' + v + '</td>';
  });
  h += '<td class="jb"></td></tr></tfoot>';
  $('sheet').innerHTML = h;
  syncBar();
}
function jobberCell(row){
  var j = row.jobber;
  if (j) {
    var paid = !!j.paid_at;
    var h = '<span class="jchip ' + (paid ? 'paid' : 'open') + '" data-jinfo="' + row.id + '" title="' + esc(j.client + ' — ' + j.subject) + '">#' + esc(j.number) +
            ' · ' + (paid ? 'PAID ' + esc(j.paid_at.slice(5, 10)) : esc((j.status || 'open').replace(/_/g, ' '))) + '</span>';
    if (paid) h += j.paid_email_at ? ' <span class="small" title="Christian was emailed ' + esc(j.paid_email_at) + '">✉ sent</span>'
                                   : ' <button class="sm" data-notify="' + row.id + '">Email Christian</button>';
    return h;
  }
  var has = KEYS.some(function(k){ return KIND[k] !== 'spacer' && row[k]; });
  if (!has || row.is_total) return '';
  if (row.suggest) return '<span class="jlink sug" data-jlink="' + row.id + '" title="The notes mention INV ' + esc(row.suggest) + '">Link #' + esc(row.suggest) + '?</span>';
  return '<span class="jlink" data-jlink="' + row.id + '">Link…</span>';
}
function anchorOf(r, c){ var a = S.layout && S.layout[r + ':' + c]; if (!a) return {r:r, c:c}; var p = a.split(':'); return {r:+p[0], c:+p[1]}; }
function selCell(){ return $('sheet').querySelector('tr[data-ri="' + S.sel.r + '"] td[data-c="' + S.sel.c + '"]'); }
function select(r, c, scroll){
  if (!S.rows.length) return;
  r = Math.max(0, Math.min(S.rows.length - 1, r)); c = Math.max(0, Math.min(KEYS.length - 1, c));
  var a = anchorOf(r, c); r = a.r; c = a.c;
  var old = selCell(); if (old) old.classList.remove('sel');
  var oldRow = $('sheet').querySelector('tr.selrow'); if (oldRow) oldRow.classList.remove('selrow');
  S.sel = {r:r, c:c};
  var td = selCell(); if (td) td.classList.add('sel');
  var tr = $('sheet').querySelector('tr[data-ri="' + r + '"]'); if (tr) tr.classList.add('selrow');
  syncBar();
  if (scroll) scrollToSel();
}
function scrollToSel(center){
  var td = selCell(); if (!td) return;
  var w = $('sheet-wrap'), top = td.offsetTop, left = td.offsetLeft;
  if (center) { w.scrollTop = top - w.clientHeight / 2; return; }
  if (top - 70 < w.scrollTop) w.scrollTop = top - 70;
  else if (top + td.offsetHeight + 30 > w.scrollTop + w.clientHeight) w.scrollTop = top + td.offsetHeight + 30 - w.clientHeight;
  if (left - 42 < w.scrollLeft) w.scrollLeft = left - 42;
  else if (left + td.offsetWidth > w.scrollLeft + w.clientWidth) w.scrollLeft = left + td.offsetWidth - w.clientWidth;
}
function syncBar(){
  var row = S.rows[S.sel.r], key = KEYS[S.sel.c];
  $('ref').textContent = COLS[S.sel.c][0] + (S.sel.r + 2);
  $('fx').value = row ? forEdit(key, row[key]) : '';
  $('fx').disabled = !row;
}
function startEdit(initial){
  var row = S.rows[S.sel.r]; if (!row) return;
  var key = KEYS[S.sel.c], td = selCell(); if (!td) return;
  S.editing = {r:S.sel.r, c:S.sel.c, old: row[key]};
  var v = initial != null ? initial : forEdit(key, row[key]);
  td.innerHTML = '<input class="ed" autocomplete="off">';
  var inp = td.firstChild; inp.value = v; inp.focus();
  if (initial == null) inp.select();
  inp.addEventListener('keydown', function(e){
    if (e.key === 'Enter') { e.preventDefault(); commit(inp.value, 1, 0); }
    else if (e.key === 'Tab') { e.preventDefault(); commit(inp.value, 0, e.shiftKey ? -1 : 1); }
    else if (e.key === 'Escape') { e.preventDefault(); S.editing = null; renderSheet(); }
    e.stopPropagation();
  });
  inp.addEventListener('blur', function(){ if (S.editing) commit(inp.value, 0, 0); });
}
function commit(value, dr, dc){
  var ed = S.editing; S.editing = null; if (!ed) return;
  var row = S.rows[ed.r], key = KEYS[ed.c];
  var unchanged = value === forEdit(key, ed.old);
  function move(){ renderSheet(); select(ed.r + dr, ed.c + dc, true); }
  if (unchanged) { move(); return; }
  row[key] = value; move();
  post('/vendor-invoices/api/cell', {id: row.id, key: key, value: value}).then(function(j){
    // Someone typing in the next cell already: keep the data, redraw once they're done.
    if (!j.success) { toast(j.error || 'Not saved'); row[key] = ed.old; if (!S.editing) renderSheet(); return; }
    var i = S.rows.findIndex(function(r){ return r.id === j.row.id; });
    if (i >= 0) { j.row.suggest = S.rows[i].suggest; S.rows[i] = j.row; }
    if (!S.editing) renderSheet();
    if (key === 'inv_no' || key === 'vendor') loadState();
  });
}
$('sheet').addEventListener('mousedown', function(e){
  if (e.target.closest('.jb')) return;
  var td = e.target.closest('td[data-c]'); if (!td || td.querySelector('input.ed')) return;
  var tr = td.parentNode;
  if (S.editing) { var inp = $('sheet').querySelector('input.ed'); if (inp) inp.blur(); }
  select(+tr.dataset.ri, +td.dataset.c);
});
$('sheet').addEventListener('dblclick', function(e){ if (e.target.closest('td[data-c]')) startEdit(); });
$('sheet').addEventListener('click', function(e){
  var el = e.target.closest('[data-jlink],[data-jinfo],[data-notify]'); if (!el) return;
  if (el.dataset.jlink) openLink(+el.dataset.jlink);
  else if (el.dataset.jinfo) jobberInfo(+el.dataset.jinfo);
  else if (el.dataset.notify) notifyPaid(+el.dataset.notify, el);
});
document.addEventListener('keydown', function(e){
  if (S.editing || S.searching) return;
  if (document.activeElement && /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
  if (document.querySelector('.modal-bg.show')) return;
  var r = S.sel.r, c = S.sel.c;
  if (e.key === 'ArrowDown') { e.preventDefault(); select(r + rowspanAt(r, c), c, true); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); select(r - 1, c, true); }
  else if (e.key === 'ArrowRight' || (e.key === 'Tab' && !e.shiftKey)) { e.preventDefault(); select(r, c + colspanAt(r, c), true); }
  else if (e.key === 'ArrowLeft' || (e.key === 'Tab' && e.shiftKey)) { e.preventDefault(); select(r, c - 1, true); }
  else if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); startEdit(); }
  else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); S.editing = {r:r, c:c, old:S.rows[r][KEYS[c]]}; commit('', 0, 0); }
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); toggleBold(); }
  else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); startEdit(e.key); }
});
function rowspanAt(r, c){ var row = S.rows[r], sp = row && (row.spans || {})[KEYS[c]]; return sp ? sp[0] : 1; }
function colspanAt(r, c){ var row = S.rows[r], sp = row && (row.spans || {})[KEYS[c]]; return sp ? sp[1] : 1; }
$('fx').addEventListener('keydown', function(e){
  if (e.key === 'Enter') { e.preventDefault(); S.editing = {r:S.sel.r, c:S.sel.c, old:S.rows[S.sel.r][KEYS[S.sel.c]]}; commit($('fx').value, 1, 0); $('fx').blur(); }
  else if (e.key === 'Escape') { syncBar(); $('fx').blur(); }
});

// ── formatting buttons ──
function styleSel(change, keys){
  var row = S.rows[S.sel.r]; if (!row) return;
  post('/vendor-invoices/api/style', Object.assign({id: row.id, keys: keys || [KEYS[S.sel.c]]}, change)).then(function(j){
    if (!j.success) { toast(j.error); return; }
    j.row.suggest = row.suggest; S.rows[S.sel.r] = j.row; renderSheet();
  });
}
document.querySelectorAll('.swatch').forEach(function(b){ b.addEventListener('click', function(){ styleSel({bg: b.dataset.bg}); }); });
$('btn-row-color').addEventListener('click', function(){
  var row = S.rows[S.sel.r]; if (!row) return;
  var st = (row.style || {})[KEYS[S.sel.c]] || {};
  styleSel({bg: st.bg || ''}, KEYS.filter(function(k){ return KIND[k] !== 'spacer'; }));
});
function toggleBold(){ var row = S.rows[S.sel.r]; if (!row) return; var st = (row.style || {})[KEYS[S.sel.c]] || {}; styleSel({bold: !st.b}); }
$('btn-bold').addEventListener('click', toggleBold);
$('btn-red').addEventListener('click', function(){ styleSel({fg: 'FF0000'}); });
$('btn-black').addEventListener('click', function(){ styleSel({fg: ''}); });
$('btn-add-row').addEventListener('click', function(){ addRow(null); });
$('btn-insert-row').addEventListener('click', function(){ var row = S.rows[S.sel.r]; addRow(row ? row.id : null); });
function addRow(afterId){
  if (!S.tab) return;
  post('/vendor-invoices/api/row/add', {tab_id: S.tab.id, after_id: afterId, values: afterId ? {} : {ok: 'YES'}}).then(function(j){
    if (!j.success) { toast(j.error); return; }
    openTab(S.tab.id, j.row.id).then(function(){ select(S.sel.r, 1, true); });
  });
}
$('btn-del-row').addEventListener('click', function(){
  var row = S.rows[S.sel.r]; if (!row) return;
  var what = [row.vendor, row.inv_no && '#' + row.inv_no].filter(Boolean).join(' ') || 'this empty row';
  if (!confirm('Delete row ' + (S.sel.r + 2) + ' (' + what + ')?')) return;
  post('/vendor-invoices/api/row/delete', {id: row.id}).then(function(){ var r = S.sel.r; openTab(S.tab.id).then(function(){ select(r, 1); }); loadState(); });
});
$('btn-link').addEventListener('click', function(){ var row = S.rows[S.sel.r]; if (row) openLink(row.id); });

// ── Jobber ──
function rowById(id){ return S.rows.find(function(r){ return r.id === id; }); }
function openLink(id){
  var row = rowById(id); if (!row) return;
  S.linkRow = id;
  $('link-row').innerHTML = '<b>' + esc(row.vendor || '—') + '</b> invoice #' + esc(row.inv_no || '—') + ' · proposal ' + esc(row.proposal || '—') +
    ' · ' + esc((row.notes || '').slice(0, 120));
  $('link-q').value = row.suggest || (row.jobber && row.jobber.number) || (isNum(row.proposal) ? row.proposal : '');
  $('link-results').innerHTML = row.jobber ? '<p class="small">Linked now to <b>#' + esc(row.jobber.number) + '</b> (' + esc(row.jobber.client) + ').</p>' : '';
  $('m-link').classList.add('show');
  if ($('link-q').value) searchJobber();
  setTimeout(function(){ $('link-q').focus(); }, 30);
}
function searchJobber(){
  var q = $('link-q').value.trim(); if (!q) return;
  $('link-results').innerHTML = '<p class="small muted">Searching Jobber…</p>';
  get('/vendor-invoices/api/jobber/search?q=' + encodeURIComponent(q)).then(function(j){
    if (!j.success) { $('link-results').innerHTML = '<p class="small late">' + esc(j.error) + '</p>'; return; }
    if (!j.invoices.length) { $('link-results').innerHTML = '<p class="small muted">Jobber has no invoice matching “' + esc(q) + '”.</p>'; return; }
    $('link-results').innerHTML = '<table class="list"><tr><th>Invoice</th><th>Client</th><th>Subject</th><th class="num">Total</th><th>Status</th><th></th></tr>' +
      j.invoices.map(function(i){
        return '<tr><td><b>#' + esc(i.number) + '</b><div class="small muted">' + esc(i.issued || '') + '</div></td><td>' + esc(i.client) + '</td><td>' + esc(i.subject) +
          '</td><td class="num">' + (i.total != null ? '$' + money(i.total) : '') + '</td><td>' + esc((i.status || '').replace(/_/g, ' ')) +
          '</td><td><button class="sm primary" data-pick="' + esc(i.id) + '" data-paid="' + (i.status === 'paid' ? 1 : 0) + '" data-num="' + esc(i.number) + '">Link</button></td></tr>';
      }).join('') + '</table>';
  });
}
$('link-go').addEventListener('click', searchJobber);
$('link-q').addEventListener('keydown', function(e){ if (e.key === 'Enter') searchJobber(); });
$('link-results').addEventListener('click', function(e){
  var b = e.target.closest('[data-pick]'); if (!b) return;
  var notify = false;
  if (b.dataset.paid === '1') notify = confirm('Jobber shows invoice #' + b.dataset.num + ' is already paid.\n\nEmail Christian now that this vendor can be paid?');
  b.disabled = true;
  post('/vendor-invoices/api/jobber/link', {id: S.linkRow, jobber_id: b.dataset.pick, notify: notify}).then(function(j){
    if (!j.success) { toast(j.error); b.disabled = false; return; }
    var i = S.rows.findIndex(function(r){ return r.id === j.row.id; }); if (i >= 0) S.rows[i] = j.row;
    renderSheet(); $('m-link').classList.remove('show');
    toast('Linked to Jobber #' + j.invoice.number + (j.already_paid ? (j.emailed && j.emailed[0] ? ' — Christian emailed' : ' — already paid') : ' — Christian is emailed when it\'s paid'));
  });
});
function jobberInfo(id){
  var row = rowById(id); if (!row || !row.jobber) return;
  var j = row.jobber;
  var msg = 'Jobber invoice #' + j.number + '\n' + j.client + (j.subject ? ' — ' + j.subject : '') + '\nTotal: ' + (j.total != null ? '$' + money(j.total) : '?') +
    '\nStatus: ' + (j.status || '?').replace(/_/g, ' ') + (j.paid_at ? ' (paid, seen ' + j.paid_at + ')' : '') +
    '\nLinked by ' + (j.linked_by || '?') + ' on ' + (j.linked_at || '?') + (j.paid_email_at ? '\nChristian emailed ' + j.paid_email_at : '') +
    '\n\nOK = open it in Jobber.  Cancel = more options.';
  if (confirm(msg)) { if (j.url) window.open(j.url, '_blank'); return; }
  if (confirm('Change the Jobber invoice this row is linked to?')) openLink(id);
  else if (confirm('Unlink Jobber invoice #' + j.number + ' from this row?'))
    post('/vendor-invoices/api/jobber/unlink', {id: id}).then(function(){ openTab(S.tab.id, id); });
}
function notifyPaid(id, btn){
  if (!confirm('Email Christian that this vendor invoice\'s Jobber invoice is paid?')) return;
  btn.disabled = true;
  post('/vendor-invoices/api/notify-paid', {id: id}).then(function(j){
    toast(j.success ? 'Emailed ' + j.to : j.error); openTab(S.tab.id, id);
  });
}
$('btn-jobber').addEventListener('click', function(){
  var b = this; b.disabled = true; b.textContent = 'Checking…';
  post('/vendor-invoices/api/jobber/check').then(function(j){
    b.disabled = false; b.textContent = 'Check Jobber';
    var r = j.result || {};
    toast(r.errors && r.errors.length && !r.checked ? r.errors[0] : 'Checked ' + (r.checked || 0) + ' linked invoice(s): ' + (r.paid || 0) + ' newly paid, ' + (r.emailed || 0) + ' emailed to Christian', 6000);
    loadState(); if (S.tab) openTab(S.tab.id, (S.rows[S.sel.r] || {}).id);
  });
});
$('btn-scan').addEventListener('click', function(){
  var b = this; b.disabled = true; b.textContent = 'Reading PO@…';
  post('/vendor-invoices/api/scan').then(function(j){
    b.disabled = false; b.textContent = 'Check PO@';
    var s = j.summary || {};
    toast((s.errors && s.errors.length ? s.errors[0] + ' — ' : '') + (s.emails_checked || 0) + ' new email(s): ' + (s.added || 0) + ' vendor invoice(s), ' +
          (s.other || 0) + ' other PDF(s), ' + (s.pump || 0) + ' pump PDF(s) left to Pumps', 7000);
    loadState();
  });
});

// ── search across every month ──
var searchT;
$('search').addEventListener('input', function(){
  clearTimeout(searchT);
  var q = this.value.trim();
  if (!q) { clearSearch(); return; }
  searchT = setTimeout(function(){
    get('/vendor-invoices/api/search?q=' + encodeURIComponent(q)).then(function(j){
      S.searching = true;
      $('sheet-wrap').style.display = 'none'; $('results').style.display = '';
      var rows = j.rows || [];
      $('results').innerHTML = '<table class="list"><tr><th>Tab</th><th>OK?</th><th>Sub contractor</th><th>Inv. date</th><th>Invoice #</th><th class="num">Invoice total</th>' +
        '<th>SEI proposal #</th><th>Date billed</th><th class="num">SEI billed</th><th>Notes</th><th>Jobber</th></tr>' +
        rows.map(function(r){
          return '<tr data-row="' + r.id + '" data-tab="' + r.tab_id + '"><td><b>' + esc(r.tab_label) + '</b></td><td>' + esc(r.ok) + '</td><td>' + esc(r.vendor) +
            '</td><td>' + show('inv_date', r.inv_date, {}).html + '</td><td>' + esc(r.inv_no) + '</td><td class="num">' + show('inv_total', r.inv_total, {}).html +
            '</td><td>' + esc(r.proposal) + '</td><td>' + show('date_billed', r.date_billed, {}).html + '</td><td class="num">' + show('amt_billed', r.amt_billed, {}).html +
            '</td><td>' + esc(r.notes) + '</td><td>' + (r.jobber ? '#' + esc(r.jobber.number) + (r.jobber.paid_at ? ' paid' : '') : '') + '</td></tr>';
        }).join('') + '</table>' + (rows.length ? (rows.length >= 300 ? '<p class="small muted" style="padding:0 8px">First 300 shown — add another word to narrow it.</p>' : '')
                                               : '<p class="small muted" style="padding:8px">Nothing matches “' + esc(q) + '”.</p>');
    });
  }, 250);
});
$('results').addEventListener('click', function(e){
  var tr = e.target.closest('tr[data-row]'); if (!tr) return;
  var id = +tr.dataset.row; clearSearch(); S.hit = id; openTab(+tr.dataset.tab, id);
});
function clearSearch(){ S.searching = false; $('results').style.display = 'none'; $('sheet-wrap').style.display = ''; }
function gotoRow(id){ get('/vendor-invoices/api/find-row/' + id).then(function(j){ if (j.tab_id) { clearSearch(); S.hit = id; openTab(j.tab_id, id); } }); }

// ── upload & settings ──
document.querySelectorAll('[data-close]').forEach(function(b){ b.addEventListener('click', function(){ b.closest('.modal-bg').classList.remove('show'); }); });
document.querySelectorAll('.modal-bg').forEach(function(m){ m.addEventListener('mousedown', function(e){ if (e.target === m) m.classList.remove('show'); }); });
$('btn-upload').addEventListener('click', function(){ $('up-result').textContent = ''; $('m-upload').classList.add('show'); });
$('up-go').addEventListener('click', function(){
  var f = $('up-file').files[0]; if (!f) { toast('Choose the workbook first'); return; }
  var fd = new FormData(); fd.append('file', f); fd.append('replace', $('up-replace').checked ? '1' : '0');
  var b = this; b.disabled = true; $('up-result').textContent = 'Reading the workbook… (a big one takes a little while)';
  fetch('/vendor-invoices/api/import', {method:'POST', headers:{'X-CSRFToken':CSRF}, body:fd}).then(function(r){ return r.json(); }).then(function(j){
    b.disabled = false;
    if (!j.success) { $('up-result').innerHTML = '<span class="late">' + esc(j.error) + '</span>'; return; }
    $('up-result').innerHTML = '<b>' + j.rows + ' rows</b> brought in: ' + (j.added.length ? j.added.length + ' new tab(s)' : 'no new tabs') +
      (j.replaced.length ? ', ' + j.replaced.length + ' replaced' : '') + (j.skipped.length ? ', ' + j.skipped.length + ' already here (' + esc(j.skipped.slice(0, 6).join(', ')) + (j.skipped.length > 6 ? '…' : '') + ')' : '') + '.';
    loadState().then(function(){ if (S.tab) openTab(S.tab.id); });
  });
});
$('btn-settings').addEventListener('click', function(){
  get('/vendor-invoices/api/settings').then(function(j){
    $('s-christian').value = j.christian_email || ''; $('s-since').value = j.scan_since || '';
    $('s-days').value = j.alert_days; $('s-again').value = j.realert_days; $('s-pump').value = j.pump_words;
    $('s-senders').innerHTML = j.senders.length ? j.senders.map(function(s){
      return '<div>' + (s.kind === 'vendor' ? '✓ vendor' : '✗ not a vendor') + ' — ' + esc(s.address) + (s.vendor ? ' (' + esc(s.vendor) + ')' : '') +
        ' <button class="sm" data-forget="' + esc(s.address) + '">Forget</button></div>';
    }).join('') : '<span class="muted">None yet. When you tell the inbox a PDF is (or isn\'t) a vendor invoice, the sender is remembered here.</span>';
    $('s-log').innerHTML = j.log.length ? j.log.map(function(l){ return '<div><span class="muted">' + esc(l.at.slice(0, 16)) + '</span> ' + esc(l.message) + '</div>'; }).join('')
                                        : '<span class="muted">Nothing yet.</span>';
    $('m-settings').classList.add('show');
  });
});
$('s-senders').addEventListener('click', function(e){
  var b = e.target.closest('[data-forget]'); if (!b) return;
  post('/vendor-invoices/api/senders/delete', {address: b.dataset.forget}).then(function(){ b.parentNode.remove(); });
});
$('s-save').addEventListener('click', function(){
  post('/vendor-invoices/api/settings', {christian_email: $('s-christian').value, scan_since: $('s-since').value, alert_days: $('s-days').value,
                                         realert_days: $('s-again').value, pump_words: $('s-pump').value}).then(function(j){
    if (!j.success) { toast(j.error); return; }
    toast('Saved'); $('m-settings').classList.remove('show'); loadState();
  });
});
$('s-alert').addEventListener('click', function(){
  post('/vendor-invoices/api/alert').then(function(j){
    var r = j.result || {}; toast(r.sent ? 'Emailed ' + r.to + ' about ' + r.count + ' invoice(s)' : 'Not sent: ' + r.why, 5000);
  });
});

// ── start ──
loadState().then(function(){
  var want = new URLSearchParams(location.search).get('row');
  if (want) { gotoRow(+want); return; }
  var saved = null; try { saved = +localStorage.getItem('vi_tab'); } catch(e) {}
  openTab(S.tabs.some(function(t){ return t.id === saved; }) ? saved : (S.tabs[0] || {}).id);
});
</script>
</body>
</html>
'''
