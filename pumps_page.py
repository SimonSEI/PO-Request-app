"""The Pumps page (one page, tabs, all data over /pumps/api). Rendered by pumps.page()."""

PUMPS_PAGE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Pumps</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="{{ csrf_token() }}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--brand:#2563EB;--brand-d:#1D4ED8;--border:#E2E8F0;--bg:#F8FAFC;--card:#fff;--text:#0F172A;--muted:#64748B;
      --sheet-head:#BDD7EE;--green:#16A34A;--green-bg:#DCFCE7;--amber:#B45309;--amber-bg:#FEF3C7;--red:#B91C1C;
      --red-bg:#FEE2E2;--violet:#5B21B6;--violet-bg:#EDE9FE;--slate-bg:#F1F5F9;}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:14px;min-height:100vh;}
a{color:var(--brand);}
.top{background:#fff;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;
     padding:0 20px;height:56px;position:sticky;top:0;z-index:40;gap:12px;}
.top .t{font-weight:700;font-size:17px;display:flex;align-items:center;gap:10px;}
.top .r{display:flex;gap:10px;align-items:center;font-size:13px;color:var(--muted);}
.btn{padding:7px 12px;border-radius:8px;border:1.5px solid var(--border);background:#fff;cursor:pointer;font:inherit;
     font-size:13px;font-weight:600;color:var(--text);text-decoration:none;white-space:nowrap;display:inline-flex;align-items:center;gap:6px;}
.btn:hover{background:var(--bg);}
.btn.p{background:var(--brand);border-color:var(--brand);color:#fff;}
.btn.p:hover{background:var(--brand-d);}
.btn.s{padding:4px 9px;font-size:12px;}
.btn.danger{color:var(--red);}
.btn:disabled{opacity:.55;cursor:wait;}
.strip{display:flex;flex-wrap:wrap;gap:8px 18px;padding:10px 20px;font-size:12.5px;color:var(--muted);background:#fff;border-bottom:1px solid var(--border);}
.strip b{color:var(--text);font-weight:600;}
.ok{color:var(--green);} .warn{color:var(--amber);} .bad{color:var(--red);}
.flash{margin:12px 20px 0;padding:10px 14px;border-radius:10px;background:var(--amber-bg);color:var(--amber);font-size:13px;}
.tabs{display:flex;gap:4px;padding:12px 20px 0;overflow-x:auto;}
.tab{padding:8px 14px;border-radius:8px 8px 0 0;font-weight:600;font-size:13px;color:var(--muted);cursor:pointer;
     border:1px solid transparent;border-bottom:none;white-space:nowrap;}
.tab.on{background:#fff;color:var(--text);border-color:var(--border);}
.tab .n{display:inline-block;min-width:18px;padding:0 5px;margin-left:5px;border-radius:9px;background:var(--slate-bg);font-size:11px;text-align:center;}
.tab .n.hot{background:var(--red-bg);color:var(--red);}
.panel{background:#fff;border-top:1px solid var(--border);padding:16px 20px 40px;min-height:60vh;}
.hide{display:none!important;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px;}
.box{border:1px solid var(--border);border-radius:12px;background:#fff;overflow:hidden;}
.box h3{font-size:13.5px;padding:10px 14px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;gap:8px;background:var(--bg);}
.box h3 .c{font-size:12px;color:var(--muted);font-weight:600;}
.box.red h3{background:var(--red-bg);color:var(--red);}
.box.amber h3{background:var(--amber-bg);color:var(--amber);}
.row{padding:9px 14px;border-bottom:1px solid var(--border);cursor:pointer;display:flex;gap:10px;justify-content:space-between;align-items:flex-start;}
.row:last-child{border-bottom:none;}
.row:hover{background:var(--bg);}
.row .main{min-width:0;flex:1;}
.row .tt{font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;}
.row .sub{color:var(--muted);font-size:12px;margin-top:2px;}
.empty{padding:14px;color:var(--muted);font-size:12.5px;}
.chip{display:inline-block;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.3px;padding:2px 7px;border-radius:100px;background:var(--slate-bg);color:#475569;white-space:nowrap;}
.chip.g{background:var(--green-bg);color:#166534;} .chip.a{background:var(--amber-bg);color:#92400E;}
.chip.r{background:var(--red-bg);color:var(--red);} .chip.v{background:var(--violet-bg);color:var(--violet);}
.chip.b{background:#DBEAFE;color:#1E40AF;}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px;}
.toolbar .sp{flex:1;}
input[type=text],input[type=number],input[type=date],select,textarea{font:inherit;font-size:13px;padding:7px 9px;border:1.5px solid var(--border);border-radius:8px;background:#fff;color:var(--text);}
textarea{width:100%;min-height:70px;resize:vertical;}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--brand);}
table.t{width:100%;border-collapse:collapse;font-size:12.5px;}
table.t th{text-align:left;font-size:11.5px;color:var(--muted);font-weight:600;padding:7px 8px;border-bottom:1px solid var(--border);background:var(--bg);position:sticky;top:0;}
table.t td{padding:7px 8px;border-bottom:1px solid var(--border);vertical-align:top;}
table.t tr.click{cursor:pointer;} table.t tr.click:hover td{background:var(--bg);}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;}
.scroll{overflow:auto;max-height:70vh;border:1px solid var(--border);border-radius:10px;}
/* tracker sheet */
table.sheet{border-collapse:collapse;width:100%;font-size:12.5px;min-width:1350px;}
.sheet th{background:var(--sheet-head);border:1px solid #9DB9D6;padding:7px 6px;font-size:12px;font-weight:700;position:sticky;top:0;z-index:1;text-align:left;}
.sheet td{border:1px solid var(--border);padding:5px 6px;vertical-align:top;background:#fff;min-width:60px;}
.sheet td.desc{min-width:240px;white-space:pre-wrap;}
.sheet td.num{text-align:right;}
.sheet td[contenteditable]:focus{outline:2px solid var(--brand);outline-offset:-2px;background:#EFF6FF;}
.sheet td.dirty{background:#FFFBEB;}
.sheet td.issue{background:var(--red-bg);}
.months{display:flex;gap:2px;padding:6px 0 0;overflow-x:auto;}
.month{padding:6px 14px;font-size:12px;font-weight:600;color:var(--muted);background:#E2E8F0;border-radius:8px 8px 0 0;cursor:pointer;white-space:nowrap;}
.month.on{background:#fff;color:var(--text);border:1px solid var(--border);border-bottom:2px solid var(--green);}
.foot{display:flex;gap:20px;font-size:12px;color:var(--muted);padding:8px 2px;}
/* drawer */
.shade{position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:60;}
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(720px,100%);background:#fff;z-index:61;overflow:auto;box-shadow:-8px 0 30px rgba(0,0,0,.12);}
.drawer .hd{position:sticky;top:0;background:#fff;border-bottom:1px solid var(--border);padding:14px 18px;display:flex;justify-content:space-between;gap:10px;z-index:2;}
.drawer .hd h2{font-size:16px;}
.drawer .bd{padding:16px 18px 40px;display:flex;flex-direction:column;gap:18px;}
.sec h4{font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:8px;}
.fields{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;}
.fields label{font-size:11.5px;color:var(--muted);display:flex;flex-direction:column;gap:3px;}
.fields label.w{grid-column:1/-1;}
.steps{display:flex;flex-direction:column;border:1px solid var(--border);border-radius:10px;overflow:hidden;}
.step{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--border);font-size:13px;}
.step:last-child{border-bottom:none;}
.step.cur{background:#EFF6FF;}
.step.na{color:#94A3B8;text-decoration:line-through;}
.step .dot{width:18px;height:18px;border-radius:50%;border:2px solid #CBD5E1;flex:none;display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;cursor:pointer;}
.step.done .dot{background:var(--green);border-color:var(--green);}
.step .lbl{flex:1;}
.step .when{font-size:12px;color:var(--muted);}
.money{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;}
.money .m{border:1px solid var(--border);border-radius:10px;padding:10px;}
.money .m .k{font-size:11.5px;color:var(--muted);}
.money .m .v{font-size:17px;font-weight:700;margin-top:3px;font-variant-numeric:tabular-nums;}
.cmp{margin-top:8px;padding:8px 12px;border-radius:8px;font-size:13px;font-weight:600;}
.cmp.match{background:var(--green-bg);color:#166534;} .cmp.over,.cmp.under,.cmp.no_quote{background:var(--red-bg);color:var(--red);}
.issue{background:var(--red-bg);color:var(--red);border-radius:10px;padding:10px 12px;font-size:13px;display:flex;justify-content:space-between;gap:10px;align-items:center;}
.issue.done{background:var(--slate-bg);color:var(--muted);}
.docs .d{display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);flex-wrap:wrap;}
.ev{font-size:12px;color:var(--muted);padding:5px 0;border-bottom:1px dashed var(--border);}
.ev b{color:var(--text);font-weight:600;}
/* modal */
.modal{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:min(820px,96vw);max-height:92vh;overflow:auto;background:#fff;border-radius:14px;z-index:71;box-shadow:0 20px 60px rgba(0,0,0,.25);}
.modal .hd{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;background:#fff;}
.modal .bd{padding:16px 18px;display:flex;flex-direction:column;gap:14px;}
.modal .ft{padding:12px 18px;border-top:1px solid var(--border);display:flex;gap:8px;justify-content:flex-end;position:sticky;bottom:0;background:#fff;}
.shade2{position:fixed;inset:0;background:rgba(15,23,42,.45);z-index:70;}
.note{font-size:12.5px;color:var(--muted);line-height:1.55;}
.safe{background:var(--green-bg);color:#166534;border-radius:8px;padding:8px 12px;font-size:12.5px;font-weight:600;}
.cand{display:flex;gap:8px;align-items:center;padding:6px 8px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px;cursor:pointer;}
.cand.on{border-color:var(--brand);background:#EFF6FF;}
.drop{border:2px dashed #CBD5E1;border-radius:12px;padding:22px;text-align:center;color:var(--muted);cursor:pointer;}
.drop.over{border-color:var(--brand);background:#EFF6FF;}
.howto{max-width:860px;line-height:1.6;font-size:13.5px;}
.howto h3{margin:18px 0 6px;font-size:15px;}
.howto li{margin-left:20px;}
.howto code{background:var(--slate-bg);padding:1px 5px;border-radius:4px;font-size:12px;}
@media (max-width:640px){.fields{grid-template-columns:1fr;}.money{grid-template-columns:1fr;}.top .r span{display:none;}.panel{padding:12px;}}
</style>
<script>
(function(){
  var t = (document.querySelector('meta[name="csrf-token"]')||{}).content || '';
  var f = window.fetch;
  window.fetch = function(url, o){
    o = o || {};
    var m = (o.method || 'GET').toUpperCase();
    if (m !== 'GET' && m !== 'HEAD') { o.headers = o.headers || {}; if (!(o.headers instanceof Headers)) o.headers['X-CSRFToken'] = t; else o.headers.set('X-CSRFToken', t); }
    return f.call(this, url, o);
  };
})();
</script>
</head>
<body>
<nav class="top">
  <div class="t">⚙️ Pumps</div>
  <div class="r">
    <button class="btn p" onclick="newCase()">＋ New item</button>
    <span>{{ full_name }}</span>
    <a class="btn" href="{{ url_for('dashboard') }}">← Dashboard</a>
  </div>
</nav>
<div class="strip">
  <div>PO@ mailbox: {% if email %}<b class="ok">connected</b> · <span id="scanInfo">…</span>
    <button class="btn s" id="scanBtn" onclick="scanNow()">Scan now</button>{% else %}<b class="warn">not configured</b> (upload documents by hand){% endif %}</div>
  <div>Jobber: <span id="jobberInfo">{% if jobber.connected %}<b class="ok">connected</b>{% elif jobber.can_connect %}<a class="btn s p" href="{{ url_for('pumps.jobber_connect') }}">Connect Jobber</a>{% else %}<b class="warn">not set up</b> (see How it works){% endif %}</span></div>
  <div>Reading documents: {% if claude %}<b class="ok">Claude</b>{% else %}<b class="warn">basic</b> (no ANTHROPIC_API_KEY - check amounts){% endif %}</div>
  <div>OpenClaw: {% if openclaw %}<b class="ok">API on</b>{% else %}<b>off</b>{% endif %}</div>
</div>
{% if flash_msg %}<div class="flash">{{ flash_msg }}</div>{% endif %}

<div class="tabs" id="tabs">
  <div class="tab on" data-tab="today">Today <span class="n" id="n-today"></span></div>
  <div class="tab" data-tab="tracker">Tracker</div>
  <div class="tab" data-tab="inbox">Inbox <span class="n" id="n-inbox"></span></div>
  <div class="tab" data-tab="scada">SCADA <span class="n" id="n-scada"></span></div>
  <div class="tab" data-tab="jobber">Jobber <span class="n" id="n-jobber"></span></div>
  <div class="tab" data-tab="help">How it works</div>
</div>

<!-- TODAY -->
<div class="panel" id="p-today">
  <div class="toolbar"><div class="note" id="todayNote">Everything waiting on someone, oldest first. Click any row to open it.</div><div class="sp"></div>
    <input type="text" id="caseSearch" placeholder="Find an item…" oninput="searchCases(this.value)" style="width:220px"></div>
  <div id="searchResults" class="box hide" style="margin-bottom:14px"></div>
  <div class="grid" id="todayGrid"></div>
</div>

<!-- TRACKER -->
<div class="panel hide" id="p-tracker">
  <div class="toolbar">
    <button class="btn" onclick="addSheetRow()">＋ Add row</button>
    <a class="btn" id="exportBtn" href="#">⬇ Excel</a>
    <span class="note">One row per PO / client need - the monthly pump sheet. Click a cell to edit; it saves when you leave the cell. ↗ opens the item.</span>
  </div>
  <div class="scroll"><table class="sheet"><thead><tr>
    <th></th><th>PO#</th><th>Date</th><th>Vendor</th><th>Job Name /Address</th><th>Description of Work</th><th>Approved By</th>
    <th>Jobber Request Made</th><th>Vendor Quote Amount</th><th>Vendor Invoice Amount</th><th>Vendor Invoice#</th>
    <th>Sei Invoice#</th><th>Amount</th><th>Notes</th><th>Stage</th></tr></thead><tbody id="sheetBody"></tbody></table></div>
  <div class="foot"><span id="footCount"></span><span id="footQuote"></span><span id="footBill"></span><span id="footAmt"></span></div>
  <div class="months" id="months"></div>
</div>

<!-- INBOX -->
<div class="panel hide" id="p-inbox">
  <div class="drop" id="drop" onclick="document.getElementById('fileIn').click()">Drop Wettech quotes, bills or Word pump reports here, or click to choose files.
    <input type="file" id="fileIn" multiple accept=".pdf,.docx,.doc" class="hide" onchange="uploadFiles(this.files)">
    <div style="margin-top:8px"><select id="uploadKind" onclick="event.stopPropagation()"><option value="">Let the app decide what it is</option><option value="quote">These are quotes</option><option value="bill">These are bills</option><option value="report">These are reports</option></select></div>
  </div>
  <div class="toolbar" style="margin-top:14px"><b>Documents</b><div class="sp"></div>
    <select id="docKind" onchange="loadInbox()"><option value="">All kinds</option><option value="quote">Quotes</option><option value="bill">Bills</option><option value="report">Reports</option><option value="other">Other</option></select>
    <select id="docStatus" onchange="loadInbox()"><option value="">Any status</option><option value="review">Needs review</option><option value="new">Not filed</option><option value="filed">Filed</option><option value="done">Done</option><option value="dismissed">Dismissed</option></select></div>
  <div class="scroll"><table class="t"><thead><tr><th>Received</th><th>Kind</th><th>From / file</th><th>Client</th><th>#</th><th class="num">Before tax</th><th class="num">Total</th><th>Item</th><th>Status</th><th></th></tr></thead><tbody id="docBody"></tbody></table></div>
</div>

<!-- SCADA -->
<div class="panel hide" id="p-scada">
  <div class="toolbar"><div class="note">Every client with SCADA work in Jobber. A renewal is due a year after the last one. Due within {{ scada_days }} days or overdue → open a renewal item: quote the client, then order it from Wettech.</div><div class="sp"></div>
    <button class="btn" onclick="addScada()">＋ Add client</button></div>
  <div class="scroll"><table class="t"><thead><tr><th>Status</th><th>Client</th><th>Site</th><th>Last renewed</th><th>Next due</th><th class="num">Annual</th><th>Provider</th><th>Notes</th><th></th></tr></thead><tbody id="scadaBody"></tbody></table></div>
</div>

<!-- JOBBER -->
<div class="panel hide" id="p-jobber">
  <div class="toolbar">
    <span id="syncInfo" class="note"></span><div class="sp"></div>
    <select id="jCat" onchange="loadJobber()"><option value="">Pump, diver, filter &amp; SCADA</option><option value="pump">Pump</option><option value="diver">Diver</option><option value="filter">Filter</option><option value="scada">SCADA</option></select>
    <select id="jKind" onchange="loadJobber()"><option value="">Requests, quotes, jobs, drafts</option><option value="request">Requests</option><option value="quote">Quotes</option><option value="job">Jobs</option><option value="invoice">Draft invoices</option></select>
    <select id="jOpen" onchange="loadJobber()"><option value="1">Open only</option><option value="0">Everything</option></select>
    <button class="btn" onclick="syncJobber()">↻ Sync Jobber</button>
  </div>
  <div class="note" style="margin-bottom:10px">Open pump work in Jobber. <b>Track</b> makes it an item here so it is followed to the invoice; <b>Ignore</b> hides it (e.g. a client that only has "pump" in its name). Items with a PO number in the title link themselves.</div>
  <div class="scroll"><table class="t"><thead><tr><th>Kind</th><th>Status</th><th>Title</th><th>Client</th><th>Property</th><th class="num">Total</th><th>Created</th><th>Item</th><th></th></tr></thead><tbody id="jobberBody"></tbody></table></div>
  <h3 style="margin:18px 0 8px;font-size:14px">Recurring pump maintenance (service contracts)</h3>
  <div class="scroll" style="max-height:40vh"><table class="t"><thead><tr><th>Client</th><th>Job</th><th>Property</th><th class="num">Per visit</th><th>Status</th></tr></thead><tbody id="contractBody"></tbody></table></div>
</div>

<!-- HELP -->
<div class="panel hide" id="p-help"><div class="howto">
  <p>Pumps keeps every pump, diver, filter and SCADA need for a client in one place until it is invoiced, so nothing is lost between the request, Wettech, and the bill.</p>
  <h3>The steps for each item</h3>
  <ol>{% for s in steps %}<li>{{ s.label.replace('{vendor}', 'Wettech') }}</li>{% endfor %}</ol>
  <p class="note">Steps that don't apply to a kind of work start crossed out (e.g. maintenance visits have no quote). Click a step's circle to mark it done today, or use its menu to set a date or mark it not needed.</p>
  <h3>What the app does by itself</h3>
  <ul>
    <li>Reads the PO@ mailbox every 30 minutes for Wettech quotes, bills and Word pump reports, and files each against its item by PO number, Wettech W/O number or client name.</li>
    <li>When a bill arrives it compares it with the quote. If they differ - or there is no quote - an <b>issue</b> is raised and stays at the top of Today until someone resolves it.</li>
    <li>Rebrands Wettech's Word reports: our letterhead, our name, no technician names, "Stahlman-" taken off the customer name.</li>
    <li>Pulls pump, diver, filter and SCADA requests, quotes and jobs from Jobber every 6 hours, and works out when each SCADA client's annual renewal is due.</li>
  </ul>
  <h3>What only happens when someone clicks</h3>
  <ul>
    <li><b>Draft invoice in Jobber</b> (from a bill): copies the bill's line items into a new Jobber invoice <b>as a draft</b>. It is never sent - the app cannot send invoices. Review it in Jobber and send it from there.</li>
    <li><b>Log report in Jobber</b>: adds the report as a note on the pump's job (or the client).</li>
    <li><b>Email Wettech to schedule</b>: opens an email in your mail program, ready to send yourself.</li>
  </ul>
  <h3>Setup</h3>
  <ul>
    <li>Jobber: create an app in Jobber's Developer Center with read access to clients, requests, quotes and jobs and <b>write access to invoices and notes</b>, set its callback URL to <code>{{ request.url_root.rstrip('/') }}/pumps/jobber/callback</code>, put its keys in Railway as <code>PUMPS_JOBBER_CLIENT_ID</code> and <code>PUMPS_JOBBER_CLIENT_SECRET</code>, then click Connect Jobber above.</li>
    <li>OpenClaw: uses the same actions at <code>/api/pumps/…</code> with <code>OPENCLAW_API_KEY</code>. Its step-by-step instructions are in <code>PUMPS_OPENCLAW.md</code> in the repository.</li>
    <li>Markup on drafted invoices: {{ markup }}% (<code>PUMPS_MARKUP_PCT</code>).</li>
  </ul>
</div></div>

<div id="drawerWrap" class="hide"><div class="shade" onclick="closeDrawer()"></div><div class="drawer" id="drawer"></div></div>
<div id="modalWrap" class="hide"><div class="shade2" onclick="closeModal()"></div><div class="modal" id="modal"></div></div>

<script>
const STEPS = {{ steps|tojson }};
const CATS = {{ categories|tojson }};
const JOBBER_OK = {{ 'true' if jobber.connected else 'false' }};
let curTab = 'today', curMonth = null, curCase = null;

function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function money(v){ if (v === null || v === undefined || v === '') return ''; const n = Number(v); return isNaN(n) ? esc(v) : '$' + n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}); }
function d10(s){ return (s || '').slice(0,10); }
function stepLabel(k, vendor){ const s = STEPS.find(x => x.key === k); return s ? s.label.replace('{vendor}', vendor || 'vendor') : (k === 'done' ? 'Done' : k); }
async function api(path, opts){
  opts = opts || {};
  if (opts.body && typeof opts.body !== 'string' && !(opts.body instanceof FormData)) { opts.headers = Object.assign({'Content-Type':'application/json'}, opts.headers || {}); opts.body = JSON.stringify(opts.body); }
  const r = await fetch('/pumps/api' + path, opts);
  let j = {}; try { j = await r.json(); } catch(e) { j = {success:false, error:'Server error ' + r.status}; }
  j._status = r.status;
  return j;
}
function toast(msg, bad){ const d = document.createElement('div'); d.textContent = msg; d.style.cssText = 'position:fixed;bottom:18px;left:50%;transform:translateX(-50%);padding:10px 16px;border-radius:10px;z-index:99;font-size:13px;font-weight:600;box-shadow:0 6px 20px rgba(0,0,0,.15);background:' + (bad ? '#FEE2E2;color:#B91C1C' : '#0F172A;color:#fff'); document.body.appendChild(d); setTimeout(() => d.remove(), bad ? 6000 : 3000); }
function catChip(c){ const m = {scada:'v', diver:'b', filter:'b', maintenance:'g', install:'a'}; return `<span class="chip ${m[c]||''}">${esc(c)}</span>`; }
function stageChip(c){ if (c.status === 'closed') return '<span class="chip g">closed</span>'; if (c.status === 'cancelled') return '<span class="chip">cancelled</span>'; return `<span class="chip ${c.open_issues && c.open_issues.length ? 'r' : 'b'}">${esc(stepLabel(c.stage, c.vendor))}</span>`; }
function kindChip(k){ const m = {quote:'b', bill:'a', report:'g', other:''}; return `<span class="chip ${m[k]||''}">${esc(k)}</span>`; }

// ── tabs ───────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(t => t.onclick = () => showTab(t.dataset.tab));
function showTab(name){
  curTab = name;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.tab === name));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('hide', p.id !== 'p-' + name));
  if (name === 'today') loadToday(); else if (name === 'tracker') loadTracker(); else if (name === 'inbox') loadInbox();
  else if (name === 'scada') loadScada(); else if (name === 'jobber') loadJobber();
  history.replaceState(null, '', '#' + name);
}

// ── today ──────────────────────────────────────────────
function caseRow(c, extra){
  const who = [c.client_name, c.site].filter(Boolean).join(' · ');
  const po = c.po_number ? ` · PO ${esc(c.po_number)}` : '';
  return `<div class="row" onclick="openCase(${c.id})"><div class="main"><div class="tt">${esc(c.title || c.client_name)}</div>
    <div class="sub">${esc(who)}${po}${extra ? ' · ' + extra : ''}</div></div>
    <div style="text-align:right">${c.idle_days >= 7 ? `<div class="chip a">${c.idle_days}d idle</div>` : ''}</div></div>`;
}
function box(title, items, render, cls, hint){
  return `<div class="box ${cls||''}"><h3>${title}<span class="c">${items.length}</span></h3>${hint ? `<div class="note" style="padding:6px 14px 0">${hint}</div>` : ''}
    ${items.length ? items.map(render).join('') : '<div class="empty">Nothing waiting.</div>'}</div>`;
}
async function loadToday(){
  const j = await api('/summary');
  if (!j.success) { document.getElementById('todayGrid').innerHTML = `<div class="empty">${esc(j.error)}</div>`; return; }
  const q = j.queue;
  setCount('n-today', q.issues.length + q.needs_scheduling.length + q.bills_to_draft.length + q.reports_to_log.length, q.issues.length > 0);
  setCount('n-inbox', q.review_docs.length, false);
  setCount('n-scada', q.scada_attention.length, q.scada_attention.some(s => s.state === 'overdue'));
  setCount('n-jobber', q.new_jobber_requests.length, false);
  updateScanInfo(j.scan);
  const g = [];
  g.push(box('⚠️ Issues to resolve', q.issues, i => `<div class="row" onclick="openCase(${i.case_id})"><div class="main"><div class="tt">${esc(i.title || i.client_name || 'Item ' + i.case_id)}</div><div class="sub">${esc(i.message)}</div></div></div>`, q.issues.length ? 'red' : ''));
  g.push(box('📅 Needs scheduling with Wettech', q.needs_scheduling, c => caseRow(c, c.scheduled_for ? 'for ' + esc(c.scheduled_for) : ''), q.needs_scheduling.length ? 'amber' : '', 'Client approved - get it on Wettech\'s calendar.'));
  g.push(box('🧾 Bills to draft in Jobber', q.bills_to_draft, d => `<div class="row" onclick="openCase(${d.case_id})"><div class="main"><div class="tt">${esc(d.client_name || d.file_name)}</div><div class="sub">${esc(d.vendor)} bill #${esc(d.doc_number)} · ${money(d.total)}</div></div><button class="btn s p" onclick="event.stopPropagation();draftInvoice(${d.id})">Draft invoice</button></div>`));
  g.push(box('📄 Reports to log in Jobber', q.reports_to_log, d => `<div class="row" onclick="${d.case_id ? `openCase(${d.case_id})` : `openDoc(${d.id})`}"><div class="main"><div class="tt">${esc(d.client_name || d.file_name)}</div><div class="sub">${esc((d.report_fields||{}).title || 'Report')} · ${esc(d.doc_date)}</div></div><button class="btn s" onclick="event.stopPropagation();logReport(${d.id})">Log in Jobber</button></div>`));
  g.push(box('📥 Inbox needs a look', q.review_docs, d => `<div class="row" onclick="openDoc(${d.id})"><div class="main"><div class="tt">${kindChip(d.kind)} ${esc(d.client_name || d.file_name)}</div><div class="sub">${esc(d.review_reason || 'Not filed yet')}</div></div></div>`));
  g.push(box('🛰️ SCADA renewals due', q.scada_attention, s => `<div class="row" onclick="showTab('scada')"><div class="main"><div class="tt">${esc(s.client_name)}${s.site ? ' · ' + esc(s.site) : ''}</div><div class="sub">${s.state === 'overdue' ? `<b class="bad">Overdue</b> since ${esc(s.next_due_on)}` : 'Due ' + esc(s.next_due_on)}${s.state_note ? ' · ' + esc(s.state_note) : ''}</div></div></div>`, q.scada_attention.some(s => s.state === 'overdue') ? 'red' : ''));
  g.push(box('🆕 New pump requests in Jobber', q.new_jobber_requests, it => `<div class="row" onclick="showTab('jobber')"><div class="main"><div class="tt">${esc(it.title)}</div><div class="sub">${esc(it.client_name)} · ${d10(it.created_at)}</div></div><button class="btn s" onclick="event.stopPropagation();jobberAct('${esc(it.jobber_id)}','track')">Track</button></div>`));
  g.push(box('💬 Quote to send to client', q.to_quote_client, c => caseRow(c)));
  g.push(box('⏳ Waiting on client approval', q.waiting_approval, c => caseRow(c)));
  g.push(box('🔧 Waiting on Wettech quote', q.waiting_vendor_quote, c => caseRow(c)));
  g.push(box('🛠️ Scheduled - waiting for the work', q.waiting_work, c => caseRow(c, c.scheduled_for ? esc(c.scheduled_for) : '')));
  g.push(box('💵 Waiting on Wettech\'s bill', q.waiting_bill, c => caseRow(c)));
  g.push(box('✅ Ready to close (send the invoice in Jobber)', q.ready_to_close, c => caseRow(c, c.sei_invoice_number ? 'Jobber #' + esc(c.sei_invoice_number) : '')));
  // Boxes with something in them first; empty ones fall to the bottom.
  document.getElementById('todayGrid').innerHTML = g.filter(h => !h.includes('class="empty"')).concat(g.filter(h => h.includes('class="empty"'))).join('');
  document.getElementById('todayNote').textContent = `${q.open_count} open items. Everything waiting on someone - click any row to open it.`;
}
function setCount(id, n, hot){ const el = document.getElementById(id); el.textContent = n || ''; el.classList.toggle('hot', !!hot); el.style.display = n ? '' : 'none'; }
let searchTimer = null;
function searchCases(v){
  clearTimeout(searchTimer);
  const box = document.getElementById('searchResults');
  if (!v.trim()) { box.classList.add('hide'); return; }
  searchTimer = setTimeout(async () => {
    const j = await api('/cases?status=all&q=' + encodeURIComponent(v.trim()));
    box.classList.remove('hide');
    box.innerHTML = `<h3>Search<span class="c">${(j.cases||[]).length}</span></h3>` + ((j.cases||[]).slice(0,30).map(c => caseRow(c, stageChip(c))).join('') || '<div class="empty">No items match.</div>');
  }, 250);
}

// ── tracker (sheet) ───────────────────────────────────
const COLS = ['po_number','opened_on','vendor','client_name','description','approved_by','jobber_request_made','vendor_quote_amount','vendor_bill_amount','vendor_bill_number','sei_invoice_number','amount','notes'];
const MONEY = new Set(['vendor_quote_amount','vendor_bill_amount','amount']);
async function loadTracker(month){
  const m = await api('/months');
  curMonth = month || curMonth || m.current;
  document.getElementById('months').innerHTML = (m.months || []).map(x => `<div class="month ${x === curMonth ? 'on' : ''}" onclick="loadTracker('${esc(x)}')">${esc(x)}</div>`).join('');
  document.getElementById('exportBtn').href = '/pumps/api/export.xlsx?month=' + encodeURIComponent(curMonth);
  const j = await api('/cases?status=all&month=' + encodeURIComponent(curMonth));
  const body = document.getElementById('sheetBody');
  body.innerHTML = '';
  (j.cases || []).forEach(c => body.appendChild(sheetRow(c)));
  footer();
}
function sheetRow(c){
  const tr = document.createElement('tr');
  if (c.id) tr.dataset.id = c.id;
  const issue = c.open_issues && c.open_issues.length;
  tr.innerHTML = `<td>${c.id ? `<a href="#" onclick="openCase(${c.id});return false" title="Open item">↗</a>` : ''}</td>` + COLS.map(k => {
    const v = c[k] === null || c[k] === undefined ? '' : c[k];
    const cls = (MONEY.has(k) ? 'num' : '') + (k === 'description' ? ' desc' : '') + (issue && (k === 'vendor_bill_amount' || k === 'vendor_quote_amount') ? ' issue' : '');
    return `<td class="${cls}" data-col="${k}" contenteditable="true">${esc(MONEY.has(k) ? money(v) : v)}</td>`;
  }).join('') + `<td>${c.id ? stageChip(c) : ''}</td>`;
  tr.querySelectorAll('td[contenteditable]').forEach(td => {
    td.addEventListener('input', () => td.classList.add('dirty'));
    td.addEventListener('blur', () => { if (td.classList.contains('dirty')) saveSheetRow(tr); });
  });
  return tr;
}
async function saveSheetRow(tr){
  const data = {month: curMonth};
  if (tr.dataset.id) data.id = parseInt(tr.dataset.id);
  tr.querySelectorAll('td[data-col]').forEach(td => data[td.dataset.col] = td.textContent.trim());
  const j = await api('/sheet/save', {method:'POST', body:data});
  if (j.success) { tr.dataset.id = j.id; tr.querySelectorAll('td.dirty').forEach(td => td.classList.remove('dirty')); if (!tr.firstChild.innerHTML) tr.firstChild.innerHTML = `<a href="#" onclick="openCase(${j.id});return false">↗</a>`; footer(); }
  else toast(j.error || 'Not saved', true);
}
function addSheetRow(){ const c = {opened_on: new Date().toISOString().slice(0,10)}; const tr = sheetRow(c); document.getElementById('sheetBody').appendChild(tr); tr.querySelector('td[contenteditable]').focus(); }
function footer(){
  let n = 0, q = 0, b = 0, a = 0;
  document.querySelectorAll('#sheetBody tr').forEach(tr => { n++;
    const val = k => parseFloat((tr.querySelector(`td[data-col="${k}"]`).textContent || '').replace(/[$,]/g,'')) || 0;
    q += val('vendor_quote_amount'); b += val('vendor_bill_amount'); a += val('amount'); });
  document.getElementById('footCount').textContent = 'Rows: ' + n;
  document.getElementById('footQuote').textContent = 'Quotes: ' + money(q);
  document.getElementById('footBill').textContent = 'Vendor bills: ' + money(b);
  document.getElementById('footAmt').textContent = 'Billed: ' + money(a);
}

// ── item drawer ───────────────────────────────────────
async function openCase(id){
  if (!id) return;
  const j = await api('/cases/' + id);
  if (!j.success) { toast(j.error || 'Not found', true); return; }
  curCase = j.case;
  renderCase();
  document.getElementById('drawerWrap').classList.remove('hide');
  history.replaceState(null, '', '#item-' + id);
}
function closeDrawer(){ document.getElementById('drawerWrap').classList.add('hide'); curCase = null; history.replaceState(null, '', '#' + curTab); if (curTab === 'today') loadToday(); else showTab(curTab); }
function renderCase(){
  const c = curCase, v = c.vendor || 'Wettech';
  const J = c.jobber || {};
  const jl = ['request','quote','job','invoice'].filter(k => J[k]).map(k => `<a href="${esc(J[k].uri || '#')}" target="_blank" rel="noopener" class="chip b">${k} ${esc(J[k].number || '')}${J[k].status ? ' · ' + esc(J[k].status) : ''}</a>`).join(' ');
  const cmp = c.compare || {};
  const cmpText = {match: `✓ Bill matches the quote (${money(cmp.bill)})`, over: `Bill is ${money(Math.abs(cmp.diff))} MORE than the quote`, under: `Bill is ${money(Math.abs(cmp.diff))} less than the quote`, no_quote: 'Bill arrived with no quote on file'}[cmp.state];
  const steps = c.step_list.map(s => {
    const done = !!s.at, na = !!s.na, cur = c.stage === s.key;
    return `<div class="step ${done ? 'done' : ''} ${na ? 'na' : ''} ${cur ? 'cur' : ''}">
      <div class="dot" title="${done ? 'Mark not done' : 'Mark done today'}" onclick="setStep('${s.key}', ${done ? 'null' : "'today'"})">${done ? '✓' : ''}</div>
      <div class="lbl">${esc(s.label)}</div>
      <div class="when">${done ? esc(s.at) + (s.by ? ' · ' + esc(s.by) : '') : (na ? 'not needed' : '')}</div>
      <select class="s" onchange="stepMenu('${s.key}', this)" style="padding:2px 4px;font-size:11px"><option value="">⋯</option><option value="date">Done on a date…</option><option value="${na ? 'needed' : 'na'}">${na ? 'Needed after all' : 'Not needed'}</option>${done ? '<option value="undo">Not done</option>' : ''}</select>
    </div>`; }).join('');
  const docs = (c.docs || []).map(d => `<div class="d">${kindChip(d.kind)} <b>${esc(d.file_name)}</b>
      <span class="note">${d.doc_number ? '#' + esc(d.doc_number) + ' · ' : ''}${d.total != null ? money(d.total) : ''} ${esc(d.doc_date)}</span>
      <span style="flex:1"></span>
      <a class="btn s" href="/pumps/api/docs/${d.id}/file" target="_blank">Open</a>
      ${d.has_branded ? `<a class="btn s" href="/pumps/api/docs/${d.id}/file?version=branded&download=1">⬇ SE report</a>` : ''}
      ${d.kind === 'bill' && !(d.jobber||{}).invoice_id ? `<button class="btn s p" onclick="draftInvoice(${d.id})">Draft invoice in Jobber</button>` : ''}
      ${d.kind === 'bill' && (d.jobber||{}).invoice_id ? `<a class="chip g" target="_blank" href="${esc(d.jobber.invoice_uri||'#')}">Jobber draft #${esc(d.jobber.invoice_number)}</a>` : ''}
      ${d.kind === 'report' && !(d.jobber||{}).note_id ? `<button class="btn s" onclick="logReport(${d.id})">Log in Jobber</button>` : ''}
      ${d.kind === 'report' && (d.jobber||{}).note_id ? '<span class="chip g">logged in Jobber</span>' : ''}
      <button class="btn s" onclick="openDoc(${d.id})">Details</button></div>`).join('') || '<div class="note">No documents yet.</div>';
  const issues = (c.issues || []).map(i => `<div class="issue ${i.resolved_at ? 'done' : ''}"><div>${esc(i.message)}${i.resolved_at ? `<div class="note">Resolved by ${esc(i.resolved_by)}: ${esc(i.resolution)}</div>` : ''}</div>${i.resolved_at ? '' : `<button class="btn s" onclick="resolveIssue(${i.id})">Resolve…</button>`}</div>`).join('');
  const f = (k, label, type, w) => `<label class="${w ? 'w' : ''}">${label}${type === 'area' ? `<textarea data-f="${k}">${esc(c[k])}</textarea>` : `<input type="${type || 'text'}" data-f="${k}" value="${esc(MONEY.has(k) || k.endsWith('_amount') ? (c[k] ?? '') : c[k])}">`}</label>`;
  document.getElementById('drawer').innerHTML = `
  <div class="hd"><div><h2>${esc(c.title || c.client_name)}</h2><div class="note">${catChip(c.category)} ${stageChip(c)} ${c.po_number ? 'PO ' + esc(c.po_number) : ''} · opened ${esc(c.opened_on)}</div></div>
    <div style="display:flex;gap:6px;align-items:flex-start"><button class="btn" onclick="closeDrawer()">✕</button></div></div>
  <div class="bd">
    ${issues ? `<div class="sec"><h4>Issues</h4><div style="display:flex;flex-direction:column;gap:8px">${issues}</div></div>` : ''}
    <div class="sec"><h4>Next</h4><div style="display:flex;gap:8px;flex-wrap:wrap">
      ${c.stage === 'scheduled' ? `<a class="btn p" href="${esc(c.schedule_email)}">✉️ Email ${esc(v)} to schedule</a>` : `<a class="btn" href="${esc(c.schedule_email)}">✉️ Email ${esc(v)}</a>`}
      <button class="btn" onclick="uploadForCase()">⬆ Add document</button>
      <button class="btn" onclick="addNote()">✎ Add note</button>
      ${c.status === 'open' ? '<button class="btn danger" onclick="cancelCase()">Cancel item</button>' : ''}
    </div></div>
    <div class="sec"><h4>Checklist</h4><div class="steps">${steps}</div></div>
    <div class="sec"><h4>Quote vs bill</h4><div class="money">
      <div class="m"><div class="k">${esc(v)} quote ${c.vendor_quote_number ? '#' + esc(c.vendor_quote_number) : ''}</div><div class="v">${money(c.vendor_quote_amount ?? c.vendor_quote_total) || '—'}</div>${c.vendor_quote_total != null && c.vendor_quote_amount != null ? `<div class="note">${money(c.vendor_quote_total)} with tax</div>` : ''}</div>
      <div class="m"><div class="k">${esc(v)} bill ${c.vendor_bill_number ? '#' + esc(c.vendor_bill_number) : ''}</div><div class="v">${money(c.vendor_bill_amount ?? c.vendor_bill_total) || '—'}</div>${c.vendor_bill_total != null && c.vendor_bill_amount != null ? `<div class="note">${money(c.vendor_bill_total)} with tax</div>` : ''}</div>
      <div class="m"><div class="k">Our invoice ${c.sei_invoice_number ? '#' + esc(c.sei_invoice_number) : ''}</div><div class="v">${money(c.amount) || '—'}</div></div>
    </div>${cmpText ? `<div class="cmp ${esc(cmp.state)}">${cmpText}</div>` : ''}</div>
    <div class="sec"><h4>Documents</h4><div class="docs">${docs}</div></div>
    <div class="sec"><h4>Details</h4><div class="fields">
      ${f('title','Title','text',1)}
      <label>Kind of work<select data-f="category">${CATS.map(x => `<option ${x === c.category ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
      ${f('po_number','PO #')}${f('client_name','Client')}${f('site','Pump / location')}${f('vendor','Vendor')}${f('approved_by','Approved by')}
      ${f('scheduled_for','Scheduled for','date')}${f('wo_number','Vendor W/O #')}
      ${f('vendor_quote_number','Vendor quote #')}${f('vendor_quote_amount','Vendor quote $ (before tax)','number')}
      ${f('vendor_bill_number','Vendor bill #')}${f('vendor_bill_amount','Vendor bill $ (before tax)','number')}
      ${f('sei_invoice_number','Our (Jobber) invoice #')}${f('amount','Our invoice $','number')}
      ${f('jobber_request_made','Jobber request made')}${f('opened_on','Opened','date')}
      ${f('description','Description of work','area',1)}${f('notes','Notes','area',1)}
      <label class="w">Jobber ${jl || '<span class="note">nothing linked - Track it from the Jobber tab</span>'}</label>
    </div><div style="margin-top:10px"><button class="btn p" onclick="saveCaseFields()">Save details</button></div></div>
    <div class="sec"><h4>History</h4>${(c.events || []).map(e => `<div class="ev">${esc(e.at)} · <b>${esc(e.actor)}</b> · ${esc(e.action)} ${e.detail ? '- ' + esc(e.detail) : ''}</div>`).join('') || '<div class="note">Nothing yet.</div>'}</div>
  </div>`;
}
async function patchCase(data){ const j = await api('/cases/' + curCase.id, {method:'PATCH', body:data}); if (j.success) { curCase = j.case; renderCase(); } else toast(j.error || 'Not saved', true); return j; }
function setStep(k, v){ patchCase({steps: {[k]: v === 'today' ? new Date().toISOString().slice(0,10) : v}}); }
function stepMenu(k, sel){
  const v = sel.value; sel.value = '';
  if (v === 'na') setStep(k, 'na'); else if (v === 'needed' || v === 'undo') setStep(k, null);
  else if (v === 'date') { const d = prompt('Date it was done (YYYY-MM-DD):', new Date().toISOString().slice(0,10)); if (d) setStep(k, d); }
}
function saveCaseFields(){
  const data = {};
  document.querySelectorAll('#drawer [data-f]').forEach(el => data[el.dataset.f] = el.value);
  patchCase(data).then(j => j.success && toast('Saved'));
}
function addNote(){ const t = prompt('Note for this item:'); if (t) patchCase({note: t}); }
async function cancelCase(){ const r = prompt('Why is this item being cancelled?'); if (r === null) return; await api('/cases/' + curCase.id + '/delete', {method:'POST', body:{reason:r}}); closeDrawer(); }
async function resolveIssue(id){ const r = prompt('How was it resolved? (e.g. "Wettech confirmed extra fittings, client approved")'); if (!r) return; const j = await api('/issues/' + id + '/resolve', {method:'POST', body:{resolution:r}}); if (j.success) openCase(curCase ? curCase.id : null).then(loadToday); else toast(j.error, true); }
function uploadForCase(){ const i = document.createElement('input'); i.type = 'file'; i.multiple = true; i.accept = '.pdf,.docx,.doc'; i.onchange = () => uploadFiles(i.files, curCase.id); i.click(); }

function newCase(){
  openModal('New item', `<div class="fields">
    <label class="w">What is needed<input type="text" id="nc_title" placeholder="e.g. Pump #2 not building pressure"></label>
    <label>Client<input type="text" id="nc_client"></label><label>Pump / location<input type="text" id="nc_site"></label>
    <label>Kind of work<select id="nc_cat">${CATS.map(x => `<option>${x}</option>`).join('')}</select></label>
    <label>PO #<input type="text" id="nc_po"></label><label>Vendor<input type="text" id="nc_vendor" value="Wettech"></label>
    <label>Approved by<input type="text" id="nc_appr"></label>
    <label class="w">Description<textarea id="nc_desc"></textarea></label></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="createCase()">Create</button>`);
}
async function createCase(){
  const v = id => document.getElementById(id).value;
  const j = await api('/cases', {method:'POST', body:{title:v('nc_title'), client_name:v('nc_client'), site:v('nc_site'), category:v('nc_cat'), po_number:v('nc_po'), vendor:v('nc_vendor'), approved_by:v('nc_appr'), description:v('nc_desc')}});
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); openCase(j.case_id);
}

// ── inbox ─────────────────────────────────────────────
async function loadInbox(){
  const k = document.getElementById('docKind').value, s = document.getElementById('docStatus').value;
  const j = await api('/docs?limit=300' + (k ? '&kind=' + k : '') + (s ? '&status=' + s : ''));
  document.getElementById('docBody').innerHTML = (j.docs || []).map(d => `<tr class="click" onclick="openDoc(${d.id})">
    <td>${esc(d10(d.created_at))}</td><td>${kindChip(d.kind)}</td>
    <td><div>${esc(d.email_from || d.source)}</div><div class="note">${esc(d.file_name)}</div></td>
    <td>${esc(d.client_name)}${d.site ? `<div class="note">${esc(d.site)}</div>` : ''}</td><td>${esc(d.doc_number)}</td>
    <td class="num">${money(d.subtotal)}</td><td class="num">${money(d.total)}</td>
    <td>${d.case_id ? `<a href="#" onclick="event.stopPropagation();openCase(${d.case_id});return false">item ${d.case_id}</a>` : '<span class="chip a">not filed</span>'}</td>
    <td>${d.status === 'review' ? '<span class="chip r">review</span>' : `<span class="chip">${esc(d.status)}</span>`}${d.review_reason ? `<div class="note">${esc(d.review_reason)}</div>` : ''}</td>
    <td><a class="btn s" href="/pumps/api/docs/${d.id}/file" target="_blank" onclick="event.stopPropagation()">Open</a></td></tr>`).join('') || '<tr><td colspan="10" class="empty">No documents yet.</td></tr>';
}
const drop = document.getElementById('drop');
['dragenter','dragover'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('over'); }));
['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', ev => uploadFiles(ev.dataTransfer.files));
async function uploadFiles(files, caseId){
  if (!files || !files.length) return;
  const fd = new FormData();
  [...files].forEach(f => fd.append('file', f));
  const kind = caseId ? '' : document.getElementById('uploadKind').value;
  if (kind) fd.append('kind', kind);
  if (caseId) fd.append('case_id', caseId);
  toast('Reading ' + files.length + ' file(s)…');
  const j = await api('/docs', {method:'POST', body:fd});
  if (!j.success) { toast(j.error || 'Upload failed', true); return; }
  const msgs = j.results.map(r => r.skipped ? `${r.file}: ${r.skipped}` : `${r.file}: ${r.kind}${r.review ? ' - ' + r.review : ''}`);
  toast(msgs.join(' | '));
  if (caseId) openCase(caseId); else loadInbox();
}
async function openDoc(id){
  const j = await api('/docs/' + id);
  if (!j.success) { toast(j.error, true); return; }
  const d = j.doc;
  const li = (d.line_items || []).map(it => `<tr><td>${esc(it.name)}<div class="note">${esc(it.description)}</div></td><td class="num">${esc(it.quantity ?? '')}</td><td class="num">${money(it.unit_price)}</td><td class="num">${money(it.amount)}</td><td>${it.is_tax ? 'tax' : (it.taxable ? 'T' : '')}</td></tr>`).join('');
  const inp = (k, label, type) => `<label>${label}<input type="${type||'text'}" data-d="${k}" value="${esc(d[k] ?? '')}"></label>`;
  const bi = d.branded_info || {};
  openModal(`${d.kind === 'other' ? 'Document' : d.kind[0].toUpperCase() + d.kind.slice(1)} - ${esc(d.file_name)}`, `
    ${d.review_reason ? `<div class="issue">${esc(d.review_reason)}</div>` : ''}
    <div class="note">From ${esc(d.email_from || d.source)} ${d.email_subject ? '· "' + esc(d.email_subject) + '"' : ''} · read by ${esc(d.extracted_by || '—')}</div>
    <div class="fields">
      <label>Kind<select data-d="kind">${['quote','bill','report','other'].map(x => `<option ${x === d.kind ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
      ${inp('vendor','Vendor')}${inp('doc_number','Number')}${inp('doc_date','Date','date')}${inp('po_number','PO #')}${inp('wo_number','Vendor W/O #')}
      ${inp('client_name','Client')}${inp('site','Pump / location')}${inp('ordered_by','Ordered / approved by')}${inp('quote_ref','Quote it refers to')}
      ${inp('subtotal','Before tax','number')}${inp('tax','Tax','number')}${inp('total','Total','number')}
      <label>File under item #<input type="number" data-d="case_id" value="${esc(d.case_id || '')}" placeholder="blank = find or create"></label>
    </div>
    ${li ? `<table class="t"><thead><tr><th>Line</th><th class="num">Qty</th><th class="num">Rate</th><th class="num">Amount</th><th></th></tr></thead><tbody>${li}</tbody></table>` : ''}
    ${d.kind === 'report' ? `<div class="note">Rebranded: ${d.has_branded ? `header removed (${esc(bi.header_removed_by)}), technicians removed: ${esc((bi.technicians_removed||[]).join(', ') || 'none found')}, Wettech mentions replaced: ${esc(bi.vendor_mentions_replaced ?? 0)}${(bi.leftovers||[]).length ? ' - <b class="bad">still mentions ' + esc(bi.leftovers.join(', ')) + '</b>' : ''}` : 'not yet'}</div>` : ''}`,
    `<a class="btn" href="/pumps/api/docs/${d.id}/file" target="_blank">Open original</a>
     ${d.has_branded ? `<a class="btn" href="/pumps/api/docs/${d.id}/file?version=branded&download=1">⬇ SE report (.docx)</a><a class="btn" href="/pumps/api/docs/${d.id}/pdf" target="_blank">PDF</a>` : ''}
     ${d.kind === 'report' && d.file_name.toLowerCase().endsWith('.docx') ? `<button class="btn" onclick="rebrand(${d.id})">Rebrand again…</button>` : ''}
     ${d.status !== 'dismissed' ? `<button class="btn danger" onclick="saveDoc(${d.id}, {status:'dismissed'})">Dismiss</button>` : ''}
     <button class="btn p" onclick="saveDocForm(${d.id})">Save &amp; file</button>`);
}
function saveDocForm(id){
  const data = {file: true};
  document.querySelectorAll('#modal [data-d]').forEach(el => { if (el.dataset.d === 'case_id') { if (el.value) data.case_id = parseInt(el.value); } else data[el.dataset.d] = el.value; });
  saveDoc(id, data);
}
async function saveDoc(id, data){
  const j = await api('/docs/' + id, {method:'PATCH', body:data});
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); toast('Saved');
  if (j.case_id) openCase(j.case_id); else if (curTab === 'inbox') loadInbox(); else loadToday();
}
async function rebrand(id){
  const names = prompt('Any other technician names to remove? (comma separated, or leave blank)', '');
  if (names === null) return;
  const j = await api('/docs/' + id + '/rebrand', {method:'POST', body:{technician_names: names.split(',').map(s => s.trim()).filter(Boolean)}});
  if (j.success) { toast('Rebranded'); openDoc(id); } else toast(j.error, true);
}

// ── draft invoice ─────────────────────────────────────
let inv = null;
async function draftInvoice(docId){
  if (!JOBBER_OK) { toast('Connect Jobber first (top of the page).', true); return; }
  const j = await api('/docs/' + docId);
  if (!j.success) { toast(j.error, true); return; }
  const d = j.doc, s = d.invoice_suggestion || {line_items:[], subject:''};
  inv = {doc: d, client_id: null, lines: s.line_items.map(x => Object.assign({}, x)), subject: s.subject};
  openModal('Draft invoice in Jobber', `
    <div class="safe">This creates a DRAFT invoice in Jobber. Nothing is sent to the client - review it in Jobber and send it from there.</div>
    ${(d.case_issues || []).map(i => `<div class="issue">⚠️ ${esc(i.message)}</div>`).join('')}
    <div class="note">From ${esc(d.vendor)} bill #${esc(d.doc_number)} - ${money(d.subtotal)} before tax, ${money(d.total)} total. The vendor's sales tax line is left off: Jobber adds the client's tax to taxable lines.${s.markup_pct ? ' Prices include ' + s.markup_pct + '% markup.' : ''}</div>
    <div><b>Jobber client</b><div class="toolbar" style="margin:6px 0"><input type="text" id="cq" value="${esc(d.client_name)}" style="flex:1"><button class="btn" onclick="findClients()">Search</button></div><div id="cands"><div class="note">Searching…</div></div></div>
    <label class="note">Invoice subject<input type="text" id="invSubject" value="${esc(inv.subject)}" style="width:100%"></label>
    <div><b>Line items</b> <span class="note">(edit before creating)</span><table class="t" style="margin-top:6px"><thead><tr><th>Name</th><th>Description</th><th class="num">Qty</th><th class="num">Unit price</th><th>Tax</th><th></th></tr></thead><tbody id="invLines"></tbody></table>
      <button class="btn s" style="margin-top:6px" onclick="inv.lines.push({name:'',description:'',quantity:1,unit_price:0,taxable:true});drawLines()">＋ Line</button>
      <div class="foot"><span id="invTotal"></span></div></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" id="invGo" onclick="createInvoice()">Create draft in Jobber</button>`);
  drawLines(); findClients();
}
function drawLines(){
  document.getElementById('invLines').innerHTML = inv.lines.map((l, i) => `<tr>
    <td><input type="text" value="${esc(l.name)}" oninput="inv.lines[${i}].name=this.value" style="width:100%"></td>
    <td><textarea oninput="inv.lines[${i}].description=this.value" style="min-height:44px">${esc(l.description)}</textarea></td>
    <td><input type="number" step="any" value="${esc(l.quantity)}" oninput="inv.lines[${i}].quantity=parseFloat(this.value);invTotal()" style="width:64px"></td>
    <td><input type="number" step="0.01" value="${esc(l.unit_price)}" oninput="inv.lines[${i}].unit_price=parseFloat(this.value);invTotal()" style="width:100px"></td>
    <td><input type="checkbox" ${l.taxable ? 'checked' : ''} onchange="inv.lines[${i}].taxable=this.checked"></td>
    <td><button class="btn s" onclick="inv.lines.splice(${i},1);drawLines()">✕</button></td></tr>`).join('');
  invTotal();
}
function invTotal(){ const t = inv.lines.reduce((a, l) => a + (l.quantity || 0) * (l.unit_price || 0), 0); document.getElementById('invTotal').textContent = 'Before tax: ' + money(t) + (inv.doc.subtotal != null && Math.abs(t - inv.doc.subtotal) > 0.005 ? ` (bill: ${money(inv.doc.subtotal)})` : ''); }
async function findClients(){
  const q = document.getElementById('cq').value.trim();
  const box = document.getElementById('cands');
  if (!q) { box.innerHTML = '<div class="note">Type a client name.</div>'; return; }
  box.innerHTML = '<div class="note">Searching Jobber…</div>';
  const j = await api('/jobber/clients?q=' + encodeURIComponent(q));
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  inv.client_id = j.pick ? j.pick.id : null;
  box.innerHTML = (j.candidates || []).map(c => `<div class="cand ${c.id === inv.client_id ? 'on' : ''}" onclick="pickClient(this, '${esc(c.id)}')"><input type="radio" name="cl" ${c.id === inv.client_id ? 'checked' : ''}>
     <div style="flex:1"><b>${esc(c.name)}</b>${c.is_lead ? ' <span class="chip a">lead</span>' : ''}<div class="note">${esc(c.address)}</div></div><span class="chip">${Math.round(c.score * 100)}%</span>
     <a href="${esc(c.uri)}" target="_blank" onclick="event.stopPropagation()" class="note">Jobber ↗</a></div>`).join('') || '<div class="note">No clients found - try a shorter name.</div>';
  if (!j.pick && (j.candidates || []).length) box.insertAdjacentHTML('afterbegin', '<div class="note" style="margin-bottom:6px"><b>Choose the client</b> - more than one could match.</div>');
}
function pickClient(el, id){ inv.client_id = id; document.querySelectorAll('#cands .cand').forEach(c => { c.classList.remove('on'); c.querySelector('input').checked = false; }); el.classList.add('on'); el.querySelector('input').checked = true; }
async function createInvoice(){
  if (!inv.client_id) { toast('Choose the Jobber client first.', true); return; }
  const btn = document.getElementById('invGo'); btn.disabled = true; btn.textContent = 'Creating draft…';
  const j = await api('/docs/' + inv.doc.id + '/invoice', {method:'POST', body:{client_id: inv.client_id, line_items: inv.lines, subject: document.getElementById('invSubject').value}});
  btn.disabled = false; btn.textContent = 'Create draft in Jobber';
  if (!j.success) { toast(j.error, true); return; }
  closeModal();
  toast(`Draft invoice #${j.invoice.invoice_number} created in Jobber (${j.invoice.invoice_status || 'draft'}). Review and send it from Jobber.`);
  if (inv.doc.case_id) openCase(inv.doc.case_id); else loadToday();
}

// ── log report ────────────────────────────────────────
let rep = null;
async function logReport(docId){
  if (!JOBBER_OK) { toast('Connect Jobber first (top of the page).', true); return; }
  const j = await api('/docs/' + docId);
  const d = j.doc;
  rep = {doc: d, client_id: null, target: null};
  openModal('Log report in Jobber', `
    <div class="note">${esc((d.report_fields||{}).title || 'Report')} · ${esc(d.client_name)} · ${esc(d.site)} · ${esc(d.doc_date)}. The note goes on the pump's job in Jobber (or on the client), with the Stahlman-England report attached when Jobber accepts it.</div>
    <div><b>Jobber client</b><div class="toolbar" style="margin:6px 0"><input type="text" id="rq" value="${esc(d.client_name)}" style="flex:1"><button class="btn" onclick="repClients()">Search</button></div><div id="rcands"></div></div>
    <div><b>Where the note goes</b><div id="rjobs" class="note">Choose the client first.</div></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" id="repGo" onclick="sendReport()">Add note in Jobber</button>`);
  repClients();
}
async function repClients(){
  const box = document.getElementById('rcands');
  box.innerHTML = '<div class="note">Searching Jobber…</div>';
  const j = await api('/jobber/clients?q=' + encodeURIComponent(document.getElementById('rq').value.trim()));
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  box.innerHTML = (j.candidates || []).map(c => `<div class="cand" data-id="${esc(c.id)}" onclick="repPick('${esc(c.id)}')"><input type="radio" name="rc"><div style="flex:1"><b>${esc(c.name)}</b><div class="note">${esc(c.address)}</div></div><span class="chip">${Math.round(c.score*100)}%</span></div>`).join('') || '<div class="note">No clients found.</div>';
  if (j.pick) repPick(j.pick.id);
}
async function repPick(id){
  rep.client_id = id;
  document.querySelectorAll('#rcands .cand').forEach(c => { const on = c.dataset.id === id; c.classList.toggle('on', on); c.querySelector('input').checked = on; });
  const box = document.getElementById('rjobs');
  box.innerHTML = 'Loading jobs…';
  const j = await api('/jobber/clients/' + encodeURIComponent(id) + '/jobs');
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  const loc = (rep.doc.site || '').toLowerCase();
  const props = Object.fromEntries((j.properties || []).map(p => [p.id, p.label]));
  const score = x => (/pump|fountain/i.test(x.title) ? 3 : 0) + (loc && (x.title + ' ' + (props[x.property_id] || '')).toLowerCase().includes(loc) ? 2 : 0) + (x.type === 'recurring' && x.status !== 'archived' ? 2 : 0) + (['active','upcoming','today','late'].includes(x.status) ? 1 : 0);
  const jobs = (j.jobs || []).slice().sort((a, b) => score(b) - score(a));
  rep.target = jobs.length && score(jobs[0]) >= 3 ? {type:'job', id: jobs[0].id} : {type:'client', id};
  box.innerHTML = jobs.map(x => `<label class="cand ${rep.target.id === x.id ? 'on' : ''}"><input type="radio" name="rt" ${rep.target.id === x.id ? 'checked' : ''} onchange="rep.target={type:'job',id:'${esc(x.id)}'}">
      <div style="flex:1"><b>#${esc(x.number)} ${esc(x.title)}</b><div class="note">${esc(x.type)} · ${esc(x.status)} · ${esc(props[x.property_id] || '')}</div></div><a class="note" target="_blank" href="${esc(x.uri)}">↗</a></label>`).join('')
    + `<label class="cand ${rep.target.type === 'client' ? 'on' : ''}"><input type="radio" name="rt" ${rep.target.type === 'client' ? 'checked' : ''} onchange="rep.target={type:'client',id:'${esc(id)}'}"><div><b>On the client</b> <span class="note">(no single pump job fits)</span></div></label>`;
}
async function sendReport(){
  if (!rep.target) { toast('Choose where the note goes.', true); return; }
  const btn = document.getElementById('repGo'); btn.disabled = true;
  const j = await api('/docs/' + rep.doc.id + '/report_note', {method:'POST', body:{target_type: rep.target.type, target_id: rep.target.id}});
  btn.disabled = false;
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); toast('Report logged in Jobber' + (j.note.note_attached_file ? ' with the file attached.' : ' (with a link to the file).'));
  if (rep.doc.case_id) openCase(rep.doc.case_id); else loadToday();
}

// ── SCADA ─────────────────────────────────────────────
async function loadScada(){
  const j = await api('/scada');
  const lab = {overdue:['r','Overdue'], due_soon:['a','Due soon'], current:['g','Current'], recurring:['g','Recurring job'], unknown:['','No date'], inactive:['','Not on SCADA']};
  document.getElementById('scadaBody').innerHTML = (j.scada || []).map(s => `<tr>
    <td><span class="chip ${lab[s.state][0]}">${lab[s.state][1]}</span>${s.days_left != null && s.state !== 'current' ? `<div class="note">${s.days_left < 0 ? -s.days_left + ' days late' : s.days_left + ' days'}</div>` : ''}</td>
    <td><b>${esc(s.client_name)}</b>${s.state_note ? `<div class="note">${esc(s.state_note)}</div>` : ''}</td><td>${esc(s.site)}</td>
    <td>${esc(s.last_renewed_on)}</td><td>${esc(s.next_due_on)}</td><td class="num">${money(s.annual_amount)}</td><td>${esc(s.provider)}</td>
    <td class="note">${esc(s.notes)}</td>
    <td style="white-space:nowrap">${s.active && ['overdue','due_soon','unknown'].includes(s.state) ? `<button class="btn s p" onclick="scadaRenew(${s.id})">${s.case_id ? 'Open renewal' : 'Start renewal'}</button>` : ''}
      <button class="btn s" onclick="scadaEdit(${s.id}, ${esc(JSON.stringify(s))})">Edit</button></td></tr>`).join('') || '<tr><td colspan="9" class="empty">No SCADA clients yet - connect Jobber and sync, or add one.</td></tr>';
}
async function scadaRenew(id){ const j = await api('/scada/' + id, {method:'POST', body:{action:'renewal_item'}}); if (j.success) openCase(j.case_id); else toast(j.error, true); }
function scadaEdit(id, s){
  openModal('SCADA - ' + esc(s.client_name), `<div class="fields">
    <label>Last renewed<input type="date" id="sc_last" value="${esc(s.last_renewed_on)}"></label>
    <label>Next due (only to override)<input type="date" id="sc_due" value="${esc(s.next_due_override)}"></label>
    <label>Annual $<input type="number" id="sc_amt" value="${esc(s.annual_amount ?? '')}"></label>
    <label>Provider<input type="text" id="sc_prov" value="${esc(s.provider)}"></label>
    <label class="w">Notes<textarea id="sc_notes">${esc(s.notes)}</textarea></label>
    <label><span><input type="checkbox" id="sc_active" ${s.active ? 'checked' : ''}> Still on SCADA</span></label></div>
    ${(s.history || []).length ? `<div><b>From Jobber</b>${s.history.map(h => `<div class="ev">${esc(h.date)} · ${esc(h.kind)} #${esc(h.number)} · ${esc(h.title)} · ${esc(h.status)} <a target="_blank" href="${esc(h.uri)}">↗</a></div>`).join('')}</div>` : ''}`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="scadaSave(${id})">Save</button>`);
}
async function scadaSave(id){
  const v = x => document.getElementById(x).value;
  const j = await api('/scada/' + id, {method:'PATCH', body:{last_renewed_on:v('sc_last'), next_due_override:v('sc_due'), annual_amount:v('sc_amt'), provider:v('sc_prov'), notes:v('sc_notes'), active:document.getElementById('sc_active').checked}});
  if (j.success) { closeModal(); loadScada(); } else toast(j.error, true);
}
function addScada(){
  openModal('Add SCADA client', `<div class="fields"><label>Client<input type="text" id="sa_client"></label><label>Site<input type="text" id="sa_site"></label>
    <label>Last renewed<input type="date" id="sa_last"></label><label>Annual $<input type="number" id="sa_amt"></label></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="scadaAdd()">Add</button>`);
}
async function scadaAdd(){ const v = x => document.getElementById(x).value; const j = await api('/scada', {method:'POST', body:{client_name:v('sa_client'), site:v('sa_site'), last_renewed_on:v('sa_last'), annual_amount:v('sa_amt')}}); if (j.success) { closeModal(); loadScada(); } else toast(j.error, true); }

// ── Jobber ────────────────────────────────────────────
async function loadJobber(){
  const c = document.getElementById('jCat').value, k = document.getElementById('jKind').value, o = document.getElementById('jOpen').value;
  const j = await api('/jobber/items?open=' + o + (c ? '&category=' + c : '') + (k ? '&kind=' + k : ''));
  const s = j.sync || {};
  document.getElementById('syncInfo').innerHTML = !JOBBER_OK ? '<b class="warn">Jobber is not connected.</b>' :
    (s.state === 'running' ? 'Syncing Jobber…' : (s.finished_at ? `Last sync ${esc(s.finished_at)} · ${esc(s.items || 0)} pump records` : 'Not synced yet.')) + ((s.errors || []).length ? ` · <span class="bad" title="${esc(s.errors.join('\n'))}">${s.errors.length} errors</span>` : '');
  document.getElementById('jobberBody').innerHTML = (j.items || []).map(it => `<tr>
    <td>${kindChip(it.kind === 'invoice' ? 'bill' : it.kind)} ${it.kind === 'invoice' ? 'invoice' : ''}</td><td><span class="chip">${esc((it.status||'').replace(/_/g,' '))}</span></td>
    <td><a href="${esc(it.web_uri)}" target="_blank" rel="noopener">${it.number ? '#' + esc(it.number) + ' ' : ''}${esc(it.title)}</a> ${catChip(it.category)}</td>
    <td>${esc(it.client_name)}</td><td class="note">${esc(it.property_label)}</td><td class="num">${money(it.total)}</td><td>${esc(d10(it.created_at))}</td>
    <td>${it.case_id ? `<a href="#" onclick="openCase(${it.case_id});return false">item ${it.case_id}</a>` : ''}</td>
    <td style="white-space:nowrap">${it.case_id ? '' : `<button class="btn s p" onclick="jobberAct('${esc(it.jobber_id)}','track')">Track</button> <button class="btn s" onclick="jobberLink('${esc(it.jobber_id)}')">Link…</button> <button class="btn s" onclick="jobberAct('${esc(it.jobber_id)}','ignore')">Ignore</button>`}</td></tr>`).join('') || `<tr><td colspan="9" class="empty">${JOBBER_OK ? 'Nothing here - try "Everything" or Sync.' : 'Connect Jobber to see pump work from Jobber.'}</td></tr>`;
  const cj = await api('/jobber/contracts');
  document.getElementById('contractBody').innerHTML = (cj.contracts || []).map(it => `<tr><td>${esc(it.client_name)}</td><td><a href="${esc(it.web_uri)}" target="_blank">#${esc(it.number)} ${esc(it.title)}</a></td><td class="note">${esc(it.property_label)}</td><td class="num">${money(it.total)}</td><td>${esc(it.status)}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">None synced yet.</td></tr>';
}
async function jobberAct(id, action){ const j = await api('/jobber/items/' + encodeURIComponent(id), {method:'POST', body:{action}}); if (!j.success) { toast(j.error, true); return; } if (action === 'track' && j.case_id) openCase(j.case_id); else if (curTab === 'jobber') loadJobber(); else loadToday(); }
async function jobberLink(id){ const n = prompt('Link to item number:'); if (!n) return; const j = await api('/jobber/items/' + encodeURIComponent(id), {method:'POST', body:{action:'link', case_id: parseInt(n)}}); if (j.success) loadJobber(); else toast(j.error, true); }
async function syncJobber(){ const j = await api('/jobber/sync', {method:'POST', body:{}}); if (!j.success) { toast(j.error, true); return; } toast('Jobber sync started - this takes a minute or two.'); setTimeout(loadJobber, 3000); }

// ── mailbox scan ─────────────────────────────────────
function updateScanInfo(s){
  const el = document.getElementById('scanInfo'); if (!el) return;
  s = s || {};
  el.textContent = s.state === 'running' ? 'scanning…' : (s.finished_at ? `last scan ${s.finished_at.slice(5,16)} - ${s.documents_added || 0} new` + ((s.errors||[]).length ? `, ${s.errors.length} errors` : '') : 'not scanned yet');
  if ((s.errors || []).length) el.title = s.errors.join('\n');
}
async function scanNow(){
  const b = document.getElementById('scanBtn'); b.disabled = true;
  const j = await api('/scan', {method:'POST', body:{}});
  if (!j.success) { toast(j.error, true); b.disabled = false; return; }
  updateScanInfo({state:'running'});
  const poll = setInterval(async () => { const s = await api('/scan'); if ((s.status || {}).state !== 'running') { clearInterval(poll); b.disabled = false; updateScanInfo(s.status); toast(`Scan done - ${(s.status||{}).documents_added || 0} new documents`); showTab(curTab); } }, 3000);
}

// ── modal ─────────────────────────────────────────────
function openModal(title, body, foot){ document.getElementById('modal').innerHTML = `<div class="hd"><b>${title}</b><button class="btn s" onclick="closeModal()">✕</button></div><div class="bd">${body}</div><div class="ft">${foot || ''}</div>`; document.getElementById('modalWrap').classList.remove('hide'); }
function closeModal(){ document.getElementById('modalWrap').classList.add('hide'); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') { if (!document.getElementById('modalWrap').classList.contains('hide')) closeModal(); else if (!document.getElementById('drawerWrap').classList.contains('hide')) closeDrawer(); } });

// ── start ─────────────────────────────────────────────
(function(){
  const h = location.hash.slice(1);
  if (h.startsWith('item-')) { loadToday(); openCase(parseInt(h.slice(5))); }
  else if (h.startsWith('doc-')) { showTab('inbox'); openDoc(parseInt(h.slice(4))); }
  else if (['tracker','inbox','scada','jobber','help'].includes(h)) { loadToday(); showTab(h); }
  else loadToday();
  setInterval(() => { if (curTab === 'today' && document.getElementById('drawerWrap').classList.contains('hide') && document.getElementById('modalWrap').classList.contains('hide')) loadToday(); }, 60000);
})();
</script>
</body>
</html>'''
