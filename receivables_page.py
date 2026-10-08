"""The Receivables page (one HTML page; the data comes from /receivables/api/data)."""

PAGE_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Receivables — Stahlman-England</title>
<meta name="csrf-token" content="{{ csrf_token() }}">
<style>
  :root { --brand:#0E7490; --brand-dark:#155E75; --brand-light:#ECFEFF; --ink:#0F172A; --ink2:#475569; --ink3:#94A3B8;
          --bg:#F8FAFC; --card:#FFF; --line:#E2E8F0; --warn:#B45309; --warn-bg:#FFFBEB; --bad:#DC2626; --bad-bg:#FEF2F2;
          --ok:#047857; --ok-bg:#ECFDF5; --blue:#2563EB; --blue-bg:#EFF6FF; --purple:#7C3AED; --purple-bg:#F5F3FF;
          --shadow:0 1px 3px rgba(15,23,42,.06); }
  *,*::before,*::after { box-sizing:border-box; }
  body { margin:0; font-family:Inter,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; background:var(--bg); color:var(--ink); font-size:14px; line-height:1.45; }
  header { background:var(--card); border-bottom:1px solid var(--line); padding:12px 20px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
  header .brand { font-weight:700; font-size:17px; }
  header .spacer { flex:1; }
  a { color:var(--blue); }
  a.back { color:var(--ink2); text-decoration:none; }
  main { max-width:1280px; margin:0 auto; padding:18px 16px 60px; }
  .status { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; align-items:center; }
  .chip { border-radius:999px; padding:3px 10px; font-size:12px; font-weight:600; border:1px solid var(--line); background:var(--card); }
  .chip.ok { color:var(--ok); background:var(--ok-bg); border-color:#A7F3D0; }
  .chip.no { color:var(--bad); background:var(--bad-bg); border-color:#FECACA; }
  .chip.warn { color:var(--warn); background:var(--warn-bg); border-color:#FDE68A; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin-bottom:14px; }
  .kpi { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; box-shadow:var(--shadow); }
  .kpi .v { font-size:20px; font-weight:700; } .kpi .l { color:var(--ink2); font-size:12px; }
  .tabs { display:flex; gap:4px; border-bottom:1px solid var(--line); margin-bottom:14px; overflow-x:auto; }
  .tab { padding:8px 14px; cursor:pointer; color:var(--ink2); font-weight:600; border-bottom:2px solid transparent; white-space:nowrap; }
  .tab.active { color:var(--brand-dark); border-color:var(--brand); }
  .tab .n { background:var(--bad); color:#fff; border-radius:999px; padding:0 6px; font-size:11px; margin-left:4px; }
  .panel { display:none; } .panel.active { display:block; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; box-shadow:var(--shadow); padding:14px; margin-bottom:12px; }
  .card h3 { margin:0 0 8px; font-size:15px; }
  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .muted { color:var(--ink2); } .small { font-size:12px; } .right { text-align:right; }
  button { font:inherit; border:1px solid var(--line); background:var(--card); border-radius:8px; padding:6px 12px; cursor:pointer; color:var(--ink); }
  button.primary { background:var(--brand); color:#fff; border-color:var(--brand); }
  button.danger { color:var(--bad); }
  button.sm { padding:3px 8px; font-size:12px; }
  input, textarea, select { font:inherit; border:1px solid var(--line); border-radius:8px; padding:7px 9px; width:100%; background:#fff; color:var(--ink); }
  textarea { min-height:90px; }
  label { display:block; font-weight:600; font-size:12px; color:var(--ink2); margin:8px 0 4px; }
  .grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:10px; }
  .badge { display:inline-block; border-radius:999px; padding:1px 8px; font-size:11px; font-weight:700; white-space:nowrap; }
  .b-open { background:var(--blue-bg); color:var(--blue); } .b-promised { background:var(--ok-bg); color:var(--ok); }
  .b-reported_paid { background:var(--ok-bg); color:var(--ok); } .b-needs_person { background:var(--bad-bg); color:var(--bad); }
  .b-paused { background:#F1F5F9; color:var(--ink2); } .b-paid { background:#F1F5F9; color:var(--ink3); }
  .b-ret { background:var(--purple-bg); color:var(--purple); } .b-install { background:var(--warn-bg); color:var(--warn); }
  .b-service { background:#F1F5F9; color:var(--ink2); } .b-late { background:var(--bad-bg); color:var(--bad); }
  .tbl-wrap { overflow-x:auto; }
  table { width:100%; border-collapse:collapse; background:var(--card); }
  th, td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { font-size:12px; color:var(--ink2); font-weight:600; background:#F8FAFC; position:sticky; top:0; white-space:nowrap; }
  tr.click { cursor:pointer; } tr.click:hover td { background:#F8FAFC; }
  td.num, th.num { text-align:right; white-space:nowrap; }
  .filters { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
  .filters input, .filters select { width:auto; min-width:150px; }
  .item { border-top:1px solid var(--line); padding:10px 0; } .item:first-child { border-top:none; }
  .drawer-bg { position:fixed; inset:0; background:rgba(15,23,42,.35); display:none; z-index:20; }
  .drawer { position:fixed; top:0; right:0; bottom:0; width:min(760px,100%); background:var(--bg); z-index:21; overflow-y:auto;
            transform:translateX(100%); transition:transform .2s; padding:16px; box-shadow:-4px 0 20px rgba(0,0,0,.1); }
  .drawer.open { transform:none; } .drawer-bg.open { display:block; }
  .drawer .close { float:right; }
  dl.kv { display:grid; grid-template-columns:150px 1fr; gap:4px 10px; margin:0; }
  dl.kv dt { color:var(--ink2); font-size:12px; font-weight:600; } dl.kv dd { margin:0; }
  .timeline .t { border-left:3px solid var(--line); padding:4px 10px; margin:6px 0; }
  .timeline .t.email { border-color:var(--blue); } .timeline .t.reply { border-color:var(--ok); }
  .timeline .t.note { border-color:var(--warn); } .timeline .t.nonp { border-color:var(--bad); }
  pre.body { white-space:pre-wrap; font-family:inherit; background:#fff; border:1px solid var(--line); border-radius:8px; padding:10px; margin:0; }
  #toast { position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:var(--ink); color:#fff; padding:10px 16px; border-radius:8px; display:none; z-index:40; }
  .banner { background:var(--warn-bg); border:1px solid #FDE68A; color:var(--warn); border-radius:10px; padding:10px 14px; margin-bottom:12px; }
  .empty { color:var(--ink3); padding:10px 0; }
  @media (max-width:640px) { dl.kv { grid-template-columns:1fr; } header { padding:10px 16px; } main { padding:14px 16px 60px; } }
</style>
</head>
<body>
<header>
  <a class="back" href="{{ url_for('dashboard') }}">← Office App</a>
  <span class="brand">💵 Receivables</span>
  <span class="spacer"></span>
  <span class="muted small">{{ full_name }}</span>
  <button onclick="document.getElementById('arfile').click()" class="primary">⬆ Upload QuickBooks A/R</button>
  <input type="file" id="arfile" accept=".xlsx,.xlsm,.csv" style="display:none" onchange="uploadAR(this)">
  <button onclick="runNow()">↻ Run now</button>
</header>
<main>
  <div class="status" id="status"></div>
  <div id="banner"></div>
  <div class="kpis" id="kpis"></div>
  <div class="tabs" id="tabs">
    <div class="tab active" data-p="today">Today <span class="n" id="n-today" style="display:none"></span></div>
    <div class="tab" data-p="invoices">Invoices</div>
    <div class="tab" data-p="jobs">Jobs &amp; retainage</div>
    <div class="tab" data-p="customers">Customers</div>
    <div class="tab" data-p="emails">Emails</div>
    <div class="tab" data-p="docs">Documents</div>
    <div class="tab" data-p="settings">Settings</div>
    <div class="tab" data-p="activity">Activity</div>
  </div>

  <section class="panel active" id="p-today"></section>

  <section class="panel" id="p-invoices">
    <div class="filters">
      <input id="f-q" placeholder="Search # / customer / job" oninput="renderInvoices()">
      <select id="f-status" onchange="renderInvoices()">
        <option value="active">All open</option><option value="due">Due for follow-up</option>
        <option value="needs_person">Needs a person</option><option value="promised">Promised / says paid</option>
        <option value="ret">Retainage</option><option value="paused">Paused</option><option value="paid">Paid / closed</option>
        <option value="all">Everything</option>
      </select>
      <select id="f-kind" onchange="renderInvoices()"><option value="">Service &amp; install</option><option value="service">Service calls</option><option value="install">Installs</option></select>
      <select id="f-age" onchange="renderInvoices()"><option value="">Any age</option><option value="0">Not due</option><option value="1">1–30 late</option><option value="31">31–60 late</option><option value="61">61–90 late</option><option value="91">90+ late</option></select>
    </div>
    <div class="tbl-wrap card" style="padding:0"><table id="t-inv"></table></div>
  </section>

  <section class="panel" id="p-jobs">
    <p class="muted small">Install jobs: every open invoice on a job, the retainage held on it, and its lien deadline (last day furnished + the lien window on Settings). Click a job to set the owner, the contact, the dates and its documents.</p>
    <div class="tbl-wrap card" style="padding:0"><table id="t-jobs"></table></div>
  </section>

  <section class="panel" id="p-customers">
    <div class="filters"><input id="c-q" placeholder="Search customer" oninput="renderCustomers()"></div>
    <div class="tbl-wrap card" style="padding:0"><table id="t-cust"></table></div>
  </section>

  <section class="panel" id="p-emails"></section>
  <section class="panel" id="p-docs"></section>
  <section class="panel" id="p-settings"></section>
  <section class="panel" id="p-activity"></section>
</main>

<div class="drawer-bg" id="dbg" onclick="closeDrawer()"></div>
<div class="drawer" id="drawer"></div>
<div id="toast"></div>

<script>
var D = null, TAB = 'today';
var CSRF = document.querySelector('meta[name="csrf-token"]').content;
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function money(v){ v = Number(v || 0); return (v < 0 ? '-$' : '$') + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2}); }
function md(d){ if(!d) return ''; var p = String(d).slice(0,10).split('-'); return p.length === 3 ? p[1] + '/' + p[2] + '/' + p[0] : d; }
function toast(m){ var t=document.getElementById('toast'); t.textContent=m; t.style.display='block'; setTimeout(function(){ t.style.display='none'; }, 3500); }
function post(url, body){
  return fetch(url, {method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':CSRF}, body:JSON.stringify(body||{})})
    .then(function(r){ return r.json(); }).then(function(j){ if(!j.success){ toast(j.error || 'Something went wrong'); throw j; } return j; });
}
function getJ(url){ return fetch(url).then(function(r){ return r.json(); }); }
function badge(cls, text){ return '<span class="badge ' + cls + '">' + esc(text) + '</span>'; }
function statusBadge(i){ return badge('b-' + i.status, (D.statuses || {})[i.status] || i.status); }
function kindBadge(k){ return badge('b-' + k, k === 'install' ? 'Install' : 'Service'); }
function ageText(i){ var d = i.plan.dpd; if(i.retainage) return badge('b-ret', 'Retainage' + (i.retainage_pct ? ' ' + i.retainage_pct + '%' : '')); return d > 0 ? badge(d > 60 ? 'b-late' : 'b-install', d + ' days late') : '<span class="muted small">not due</span>'; }

document.getElementById('tabs').addEventListener('click', function(e){
  var t = e.target.closest('.tab'); if(!t) return;
  TAB = t.dataset.p;
  document.querySelectorAll('.tab').forEach(function(x){ x.classList.toggle('active', x === t); });
  document.querySelectorAll('.panel').forEach(function(x){ x.classList.toggle('active', x.id === 'p-' + TAB); });
});

function load(){
  return getJ('/receivables/api/data').then(function(j){ if(!j.success){ toast(j.error); return; } D = j; render(); });
}

function render(){
  var st = D.status, s = D.settings;
  document.getElementById('status').innerHTML =
    '<span class="chip ' + (st.graph ? 'ok' : 'no') + '">Microsoft 365 ' + (st.graph ? 'connected' : 'not connected') + '</span>' +
    '<span class="chip ' + (st.jobber ? 'ok' : 'no') + '">Jobber ' + (st.jobber ? 'connected' : 'not connected (connect it in Pumps)') + '</span>' +
    '<span class="chip ' + (st.claude ? 'ok' : 'warn') + '">' + (st.claude ? 'Claude reads replies' : 'Replies read by simple rules') + '</span>' +
    '<span class="chip ' + (s.auto_send ? 'ok' : 'warn') + '">' + (s.auto_send ? 'Sending automatically' : 'Drafts wait for review') + '</span>' +
    '<span class="chip">From ' + esc(s.from_email) + '</span>' +
    '<span class="muted small">Last run ' + esc(st.last_run || 'never') + (D.uploads.length ? ' · Last upload ' + esc(D.uploads[0].at) + ' (' + esc(D.uploads[0].filename) + ')' : '') + '</span>';
  var banner = '';
  if(!D.uploads.length) banner = '<div class="banner">Start by uploading the A/R sheet from QuickBooks: Reports → <b>A/R Aging Detail</b> (or Open Invoices) → Export to Excel, then <b>Upload QuickBooks A/R</b> above. Upload a fresh one whenever you like; invoices that drop off are treated as paid.</div>';
  document.getElementById('banner').innerHTML = banner;
  var open = D.invoices.filter(function(i){ return i.status !== 'paid'; });
  var sum = function(a){ return a.reduce(function(t,i){ return t + (i.open_balance || 0); }, 0); };
  var late = open.filter(function(i){ return !i.retainage && i.plan.dpd > 0; });
  var vlate = open.filter(function(i){ return !i.retainage && i.plan.dpd > 60; });
  var ret = open.filter(function(i){ return i.retainage; });
  document.getElementById('kpis').innerHTML =
    kpi(money(sum(open)), open.length + ' open invoices') + kpi(money(sum(late)), late.length + ' past due') +
    kpi(money(sum(vlate)), vlate.length + ' over 60 days late') + kpi(money(sum(ret)), ret.length + ' retainage invoices') +
    kpi(open.filter(function(i){ return i.status === 'needs_person' || (i.plan.due_now && !i.contacts.length); }).length, 'need a person');
  renderToday(); renderInvoices(); renderJobs(); renderCustomers(); renderEmails(); renderDocs(); renderSettings(); renderActivity();
}
function kpi(v, l){ return '<div class="kpi"><div class="v">' + esc(v) + '</div><div class="l">' + esc(l) + '</div></div>'; }

// ── Today ──
function renderToday(){
  var drafts = D.emails.filter(function(e){ return e.status === 'draft'; });
  var people = D.invoices.filter(function(i){ return i.status === 'needs_person'; });
  var noContact = D.invoices.filter(function(i){ return i.status !== 'paid' && i.plan.due_now && !i.contacts.length; });
  var liens = D.jobs.filter(function(j){ return j.lien && j.lien.applies && j.open_balance > 0 && j.lien.days_left != null && j.lien.days_left <= Number(D.settings.nonp_lead_days || 30) + 15 && j.nonp_status !== 'lien_recorded'; })
                    .sort(function(a,b){ return a.lien.days_left - b.lien.days_left; });
  var failed = D.emails.filter(function(e){ return e.status === 'draft' && e.error; });
  var n = drafts.length + people.length + liens.length;
  var nt = document.getElementById('n-today'); nt.style.display = n ? '' : 'none'; nt.textContent = n;
  var h = '';
  h += '<div class="card"><h3>✉️ Follow-ups ready (' + drafts.length + ')</h3>';
  if(!drafts.length) h += '<div class="empty">Nothing waiting. ' + (D.settings.auto_send ? 'Follow-ups are sent automatically.' : '') + '</div>';
  else {
    h += '<div class="row" style="margin-bottom:6px"><button class="primary sm" onclick="sendAll()">Send all ' + drafts.filter(function(e){ return e.to_email; }).length + ' with an address</button><span class="muted small">Each one can be opened, edited and sent on its own.</span></div>';
    drafts.forEach(function(e){
      h += '<div class="item"><div class="row"><b>' + esc(e.subject) + '</b>' + (e.kind === 'nonp' ? badge('b-late', 'Notice of Nonpayment') : badge('b-' + (e.stage === 'retainage' ? 'ret' : 'open'), (e.stage || '').replace('_', ' '))) + '</div>' +
           '<div class="muted small">To ' + (esc(e.to_email) || '<b style="color:var(--bad)">no address</b>') + (e.cc ? ' · cc ' + esc(e.cc) : '') + '</div>' +
           (e.error ? '<div class="small" style="color:var(--bad)">' + esc(e.error) + '</div>' : '') +
           '<div class="row" style="margin-top:6px"><button class="sm" onclick="openEmail(' + e.id + ')">Review</button><button class="sm primary" onclick="sendEmail(' + e.id + ')">Send</button><button class="sm danger" onclick="discardEmail(' + e.id + ')">Discard</button></div></div>';
    });
  }
  h += '</div>';
  h += '<div class="card"><h3>🙋 Needs a person (' + (people.length + noContact.length) + ')</h3>';
  if(!people.length && !noContact.length) h += '<div class="empty">Nothing needs a person.</div>';
  people.forEach(function(i){ h += invItem(i, i.needs_reason); });
  noContact.forEach(function(i){ h += invItem(i, 'No email address to follow up with. Add one for ' + i.customer_name + ' on the Customers tab.'); });
  h += '</div>';
  h += '<div class="card"><h3>⚖️ Lien deadlines</h3>';
  if(!liens.length) h += '<div class="empty">No install job is near its lien deadline.</div>';
  liens.forEach(function(j){
    var l = j.lien, step = {'':'Not started', prepared:'Notice of Nonpayment ready to send', sent:'NONP emailed: mail it certified', mailed:'NONP mailed: record the lien', lien_recorded:'Lien recorded'}[j.nonp_status || ''];
    h += '<div class="item"><div class="row"><b>' + esc(j.name) + '</b><span class="muted">' + esc(j.customer_name) + '</span>' + badge(l.days_left < 0 ? 'b-late' : (l.days_left <= 15 ? 'b-late' : 'b-install'), l.days_left < 0 ? 'Deadline passed ' + md(l.deadline) : l.days_left + ' days left (' + md(l.deadline) + ')') + '</div>' +
         '<div class="muted small">' + money(j.open_balance) + ' open · last furnished ' + md(l.last_furnished) + (l.estimated ? ' (estimated from the last invoice date: set the real date on the job)' : '') + ' · ' + esc(step) + '</div>' +
         '<div class="row" style="margin-top:6px"><button class="sm" onclick="openJob(\'' + esc(j.key) + '\')">Open job</button>' + (!j.nonp_status ? '<button class="sm primary" onclick="prepNonp(\'' + esc(j.key) + '\')">Prepare Notice of Nonpayment</button>' : '') + '</div></div>';
  });
  h += '</div>';
  h += '<div class="card"><h3>💬 Latest replies</h3>';
  if(!D.replies.length) h += '<div class="empty">No replies yet.</div>';
  D.replies.slice(0, 12).forEach(function(r){
    h += '<div class="item"><div class="row"><b>' + esc(r.from_email) + '</b>' + badge(r.intent === 'promise' || r.intent === 'paid' ? 'b-promised' : (r.intent === 'auto_reply' ? 'b-paused' : 'b-needs_person'), r.intent.replace('_', ' ')) + '<span class="muted small">' + esc((r.received_at || '').slice(0,16).replace('T', ' ')) + '</span></div><div class="small">' + esc(r.summary) + (r.promised_date ? ' · promised ' + md(r.promised_date) : '') + '</div></div>';
  });
  h += '</div>';
  if(D.uploads.length){
    var u = JSON.parse(D.uploads[0].info || '{}');
    h += '<div class="card"><h3>⬆ Last QuickBooks upload</h3><div class="small">' + esc(D.uploads[0].filename) + ' by ' + esc(D.uploads[0].by) + ' on ' + esc(D.uploads[0].at) + ': ' + (u.open || 0) + ' open, ' + (u['new'] || 0) + ' new, ' + (u.closed || 0) + ' paid since the one before, ' + (u.paid_down || 0) + ' partly paid.</div></div>';
  }
  document.getElementById('p-today').innerHTML = h;
}
function invItem(i, why){
  return '<div class="item"><div class="row"><a href="#" onclick="openInvoice(' + i.id + ');return false"><b>#' + esc(i.number) + '</b></a><span>' + esc(i.customer_name) + '</span>' + (i.job_name ? '<span class="muted small">' + esc(i.job_name) + '</span>' : '') + '<span>' + money(i.open_balance) + '</span>' + ageText(i) + '</div><div class="small" style="color:var(--bad)">' + esc(why) + '</div></div>';
}

// ── Invoices ──
function renderInvoices(){
  var q = (document.getElementById('f-q').value || '').toLowerCase(), f = document.getElementById('f-status').value;
  var k = document.getElementById('f-kind').value, a = document.getElementById('f-age').value;
  var rows = D.invoices.filter(function(i){
    if(f === 'active' && i.status === 'paid') return false;
    if(f === 'due' && !i.plan.due_now) return false;
    if(f === 'needs_person' && i.status !== 'needs_person') return false;
    if(f === 'promised' && ['promised','reported_paid'].indexOf(i.status) < 0) return false;
    if(f === 'ret' && (!i.retainage || i.status === 'paid')) return false;
    if(f === 'paused' && i.status !== 'paused') return false;
    if(f === 'paid' && i.status !== 'paid') return false;
    if(k && i.kind !== k) return false;
    if(a !== ''){ var d = i.plan.dpd, n = Number(a); if(i.retainage) return false;
      if(n === 0 && d > 0) return false; if(n === 1 && (d < 1 || d > 30)) return false; if(n === 31 && (d < 31 || d > 60)) return false;
      if(n === 61 && (d < 61 || d > 90)) return false; if(n === 91 && d < 91) return false; }
    if(q && (i.number + ' ' + i.customer_name + ' ' + i.job_name + ' ' + (i.jobber_subject || '') + ' ' + (i.memo || '')).toLowerCase().indexOf(q) < 0) return false;
    return true;
  }).sort(function(x,y){ return y.plan.dpd - x.plan.dpd; });
  var h = '<thead><tr><th>Invoice</th><th>Customer</th><th>Job</th><th>Type</th><th>Date</th><th>Due</th><th>Age</th><th class="num">Amount</th><th class="num">Open</th><th>Status</th><th>Next</th></tr></thead><tbody>';
  rows.forEach(function(i){
    h += '<tr class="click" onclick="openInvoice(' + i.id + ')"><td><b>#' + esc(i.number) + '</b></td><td>' + esc(i.customer_name) + '</td><td class="small">' + esc(i.job_name) + '</td><td>' + kindBadge(i.kind) + '</td><td>' + md(i.txn_date) + '</td><td>' + md(i.due_date) + '</td><td>' + ageText(i) + '</td><td class="num">' + (i.amount != null ? money(i.amount) : '') + '</td><td class="num"><b>' + money(i.open_balance) + '</b></td><td>' + statusBadge(i) + '</td><td class="small">' + (i.plan.due_now ? '<b style="color:var(--brand-dark)">Due now</b>' : esc(i.plan.reason)) + '</td></tr>';
  });
  if(!rows.length) h += '<tr><td colspan="11" class="empty">No invoices match.</td></tr>';
  document.getElementById('t-inv').innerHTML = h + '</tbody>';
}

// ── Jobs ──
function renderJobs(){
  var rows = D.jobs.slice().sort(function(a,b){ return (a.lien.days_left == null ? 9999 : a.lien.days_left) - (b.lien.days_left == null ? 9999 : b.lien.days_left); });
  var h = '<thead><tr><th>Job</th><th>Customer</th><th class="num">Open invoices</th><th class="num">Open</th><th class="num">Retainage held</th><th>Complete</th><th>Last furnished</th><th>Lien deadline</th><th>NONP</th></tr></thead><tbody>';
  rows.forEach(function(j){
    var l = j.lien || {};
    h += '<tr class="click" onclick="openJob(\'' + esc(j.key) + '\')"><td><b>' + esc(j.name) + '</b> ' + kindBadge(j.kind) + '</td><td>' + esc(j.customer_name) + '</td><td class="num">' + j.open_count + '</td><td class="num">' + money(j.open_balance) + '</td><td class="num">' + (j.retainage_held ? badge('b-ret', money(j.retainage_held) + ' on ' + j.retainage_count) : '') + '</td><td>' + (j.complete_now ? '✅' : '—') + '</td><td>' + md(l.last_furnished) + (l.estimated && l.last_furnished ? ' <span class="muted small">(est.)</span>' : '') + '</td><td>' + (l.applies && l.deadline ? md(l.deadline) + ' ' + badge(l.days_left < 0 ? 'b-late' : (l.days_left <= 30 ? 'b-install' : 'b-service'), l.days_left < 0 ? 'passed' : l.days_left + 'd') : '<span class="muted small">n/a</span>') + '</td><td class="small">' + esc(j.nonp_status || '') + '</td></tr>';
  });
  if(!rows.length) h += '<tr><td colspan="9" class="empty">No jobs with open invoices.</td></tr>';
  document.getElementById('t-jobs').innerHTML = h + '</tbody>';
}

// ── Customers ──
function renderCustomers(){
  var q = (document.getElementById('c-q').value || '').toLowerCase();
  var rows = D.customers.filter(function(c){ return !q || c.nice_name.toLowerCase().indexOf(q) >= 0; }).sort(function(a,b){ return b.open_balance - a.open_balance; });
  var h = '<thead><tr><th>Customer</th><th class="num">Open</th><th>Follow up with</th><th>From Jobber</th><th>Type</th><th>Do not contact</th><th></th></tr></thead><tbody>';
  rows.forEach(function(c){
    var k = esc(c.key);
    h += '<tr><td><b>' + esc(c.nice_name) + '</b><div class="muted small">' + c.open_count + ' open</div></td><td class="num">' + money(c.open_balance) + '</td>' +
      '<td><input id="cn-' + k + '" placeholder="Contact name" value="' + esc(c.contact_name) + '" style="margin-bottom:4px"><input id="ce-' + k + '" placeholder="email(s), comma separated" value="' + esc(c.emails) + '"></td>' +
      '<td class="small muted">' + esc(c.jobber_emails || '') + '</td>' +
      '<td><select id="ck-' + k + '"><option value="">Auto</option><option value="service"' + (c.kind_default === 'service' ? ' selected' : '') + '>Service</option><option value="install"' + (c.kind_default === 'install' ? ' selected' : '') + '>Install</option></select></td>' +
      '<td><input type="checkbox" id="cd-' + k + '"' + (c.do_not_contact ? ' checked' : '') + ' style="width:auto"></td>' +
      '<td><button class="sm" onclick="saveCustomer(\'' + k + '\')">Save</button> <button class="sm" onclick="docUpload(\'customer\',\'' + k + '\')">+ Doc</button></td></tr>';
  });
  if(!rows.length) h += '<tr><td colspan="7" class="empty">No customers with open invoices.</td></tr>';
  document.getElementById('t-cust').innerHTML = h + '</tbody>';
}
function saveCustomer(k){
  post('/receivables/api/customer', {key:k, contact_name:document.getElementById('cn-' + k).value, emails:document.getElementById('ce-' + k).value,
    kind_default:document.getElementById('ck-' + k).value, do_not_contact:document.getElementById('cd-' + k).checked}).then(function(){ toast('Saved'); load(); });
}

// ── Emails ──
function renderEmails(){
  var h = '<div class="card"><h3>Emails</h3><div class="tbl-wrap"><table><thead><tr><th>When</th><th>Status</th><th>To</th><th>Subject</th><th></th></tr></thead><tbody>';
  D.emails.forEach(function(e){
    h += '<tr><td class="small">' + esc(e.sent_at || e.created_at) + '</td><td>' + badge(e.status === 'sent' ? 'b-promised' : 'b-open', e.status + (e.sent_by ? ' (' + e.sent_by + ')' : '')) + '</td><td class="small">' + esc(e.to_email) + '</td><td>' + esc(e.subject) + (e.error ? '<div class="small" style="color:var(--bad)">' + esc(e.error) + '</div>' : '') + '</td><td><button class="sm" onclick="openEmail(' + e.id + ')">' + (e.status === 'sent' ? 'View' : 'Review') + '</button></td></tr>';
  });
  if(!D.emails.length) h += '<tr><td colspan="5" class="empty">No emails yet.</td></tr>';
  document.getElementById('p-emails').innerHTML = h + '</tbody></table></div></div>';
}
function openEmail(id){
  var e = D.emails.filter(function(x){ return x.id === id; })[0]; if(!e) return;
  var ro = e.status === 'sent';
  var h = '<button class="close" onclick="closeDrawer()">✕</button><h2>' + (ro ? 'Sent email' : 'Review email') + '</h2>';
  h += '<div class="card"><label>To</label><input id="em-to" value="' + esc(e.to_email) + '"' + (ro ? ' disabled' : '') + '><label>Cc</label><input id="em-cc" value="' + esc(e.cc) + '"' + (ro ? ' disabled' : '') + '>' +
       '<label>Subject</label><input id="em-subj" value="' + esc(e.subject) + '"' + (ro ? ' disabled' : '') + '><label>Message</label><textarea id="em-body" style="min-height:320px"' + (ro ? ' disabled' : '') + '>' + esc(e.body) + '</textarea>' +
       '<label>Attachments</label><div id="em-att" class="small muted">Loading…</div>' +
       '<div class="muted small" style="margin-top:6px">Sent from ' + esc(D.settings.from_email) + '</div>' +
       (ro ? '' : '<div class="row" style="margin-top:10px"><button class="primary" onclick="saveEmail(' + id + ', true)">Send</button><button onclick="saveEmail(' + id + ', false)">Save draft</button><button class="danger" onclick="discardEmail(' + id + ')">Discard</button></div>') + '</div>';
  openDrawer(h);
  getJ('/receivables/api/email/' + id + '/attachments').then(function(j){
    var el = document.getElementById('em-att'); if(!el) return;
    el.innerHTML = (j.files || []).map(function(f){ return '📎 ' + esc(f.name) + (f.size ? ' (' + Math.round(f.size / 1024) + ' KB)' : ''); }).join('<br>') || 'None';
    if(j.dropped && j.dropped.length) el.innerHTML += '<div style="color:var(--bad)">Too large to attach: ' + esc(j.dropped.join(', ')) + '</div>';
  });
}
function saveEmail(id, send){
  post('/receivables/api/email', {id:id, to_email:document.getElementById('em-to').value, cc:document.getElementById('em-cc').value,
    subject:document.getElementById('em-subj').value, body:document.getElementById('em-body').value, send:send}).then(function(){ toast(send ? 'Sent' : 'Saved'); closeDrawer(); load(); });
}
function sendEmail(id){ var e = D.emails.filter(function(x){ return x.id === id; })[0];
  post('/receivables/api/email', {id:id, to_email:e.to_email, cc:e.cc, subject:e.subject, body:e.body, send:true}).then(function(){ toast('Sent'); load(); }); }
function discardEmail(id){ if(!confirm('Discard this email?')) return; post('/receivables/api/email', {id:id, discard:true}).then(function(){ closeDrawer(); load(); }); }
function sendAll(){
  var list = D.emails.filter(function(e){ return e.status === 'draft' && e.to_email; });
  if(!list.length || !confirm('Send ' + list.length + ' email(s) from ' + D.settings.from_email + '?')) return;
  var chain = Promise.resolve(), ok = 0;
  list.forEach(function(e){ chain = chain.then(function(){ return post('/receivables/api/email', {id:e.id, to_email:e.to_email, cc:e.cc, subject:e.subject, body:e.body, send:true}).then(function(){ ok++; }).catch(function(){}); }); });
  chain.then(function(){ toast(ok + ' sent'); load(); });
}

// ── Documents ──
function renderDocs(){
  var h = '<div class="card"><h3>Documents</h3><p class="muted small">Files here are attached to follow-up emails: <b>every email</b> ones to all of them, a customer\'s to all of theirs, and a job\'s to every follow-up on that install job (open the job to add one). An invoice PDF uploaded on an invoice is sent in place of the one made from Jobber.</p>' +
          '<button class="primary sm" onclick="docUpload(\'all\',\'\')">+ Add a document for every email</button></div>';
  h += '<div class="card"><div class="tbl-wrap"><table><thead><tr><th>File</th><th>Goes with</th><th>Uploaded</th><th></th></tr></thead><tbody>';
  var names = {}; D.jobs.forEach(function(j){ names['job:' + j.key] = 'Job ' + j.name; }); D.customers.forEach(function(c){ names['customer:' + c.key] = c.nice_name; });
  D.docs.forEach(function(d){
    h += '<tr><td><a href="/receivables/docs/' + d.id + '" target="_blank">' + esc(d.filename) + '</a> <span class="muted small">' + Math.round(d.size / 1024) + ' KB</span></td><td>' + esc(d.scope === 'all' ? 'Every email' : (names[d.scope + ':' + d.scope_key] || d.scope + ' ' + d.scope_key)) + '</td><td class="small">' + esc(d.uploaded_by) + ' ' + esc(d.uploaded_at) + '</td><td><button class="sm danger" onclick="docDelete(' + d.id + ')">Remove</button></td></tr>';
  });
  if(!D.docs.length) h += '<tr><td colspan="4" class="empty">No documents yet.</td></tr>';
  document.getElementById('p-docs').innerHTML = h + '</tbody></table></div></div>';
}
function docUpload(scope, key, kind){
  var inp = document.createElement('input'); inp.type = 'file';
  inp.onchange = function(){
    if(!inp.files[0]) return;
    var fd = new FormData(); fd.append('file', inp.files[0]); fd.append('scope', scope); fd.append('scope_key', key); fd.append('kind', kind || 'document');
    fetch('/receivables/api/docs/upload', {method:'POST', headers:{'X-CSRFToken':CSRF}, body:fd}).then(function(r){ return r.json(); }).then(function(j){
      if(!j.success){ toast(j.error); return; } toast('Uploaded'); load().then(function(){ if(CUR_INV && scope === 'invoice') openInvoice(CUR_INV); if(CUR_JOB && scope === 'job') openJob(CUR_JOB); });
    });
  };
  inp.click();
}
function docDelete(id){ if(!confirm('Remove this document?')) return; post('/receivables/api/docs/delete', {id:id}).then(function(){ load().then(function(){ if(CUR_INV) openInvoice(CUR_INV); else if(CUR_JOB) openJob(CUR_JOB); }); }); }

// ── Settings ──
function renderSettings(){
  var s = D.settings;
  var h = '<div class="card"><h3>Sending</h3><div class="grid2">' +
    fld('from_email', 'Send from (and read replies in)', s.from_email) + fld('cc', 'Cc on every follow-up', s.cc) + fld('send_hours', 'Automatic sending hours (Mon–Fri, e.g. 8-17)', s.send_hours) + '</div>' +
    '<label>Signature</label><textarea id="s-signature">' + esc(s.signature) + '</textarea>' +
    chk('auto_send', 'Send follow-ups automatically (off = they wait on the Today tab for review)', s.auto_send) +
    chk('read_replies', 'Read replies in the sending mailbox and act on them', s.read_replies) +
    chk('enabled', 'Run every hour (Jobber, replies, follow-ups, lien deadlines)', s.enabled) + '</div>';
  h += '<div class="card"><h3>Escalation</h3><p class="muted small">Days past due when each stage starts, and how often it repeats. "Payment is coming" replies stop follow-ups until the <b>very past due</b> stage.</p><table><thead><tr><th>Stage</th><th>Starts at (days late)</th><th>Repeat every (days)</th></tr></thead><tbody>';
  s.stages.forEach(function(st, n){ h += '<tr><td><input id="st-name-' + n + '" value="' + esc(st.name) + '" data-key="' + esc(st.key) + '"></td><td><input id="st-from-' + n + '" type="number" value="' + st.from_days + '"></td><td><input id="st-every-' + n + '" type="number" value="' + st.every_days + '"></td></tr>'; });
  h += '</tbody></table><div class="grid2">' + fld('promise_grace_days', 'After a promised date passes, wait (days)', s.promise_grace_days, 'number') +
    fld('reported_paid_wait_days', '"We paid": wait for it to show up (days)', s.reported_paid_wait_days, 'number') + fld('min_balance', 'Ignore balances under ($)', s.min_balance, 'number') + '</div></div>';
  h += '<div class="card"><h3>Service calls, installs and retainage</h3><div class="grid2">' +
    fld('install_words', 'Words that mark an install invoice', s.install_words) + fld('retainage_pcts', 'Retainage percentages', s.retainage_pcts) +
    fld('retainage_tolerance', 'Retainage tolerance (± percentage points)', s.retainage_tolerance, 'number') + fld('retainage_every_days', 'Ask for retainage every (days, once the job is complete)', s.retainage_every_days, 'number') +
    fld('max_attach_mb', 'Most attachments per email (MB)', s.max_attach_mb, 'number') + '</div></div>';
  h += '<div class="card"><h3>Liens and the Notice of Nonpayment</h3><p class="muted small">A claim of lien has to be recorded within the lien window after the last day labor or materials were furnished (90 days in Florida). Ahead of that deadline the app prepares a Notice of Nonpayment for the owner. Have your attorney check the wording once; the notice should also go by certified mail, and the lien itself is recorded with the county.</p><div class="grid2">' +
    fld('lien_days', 'Lien window (days after last furnished)', s.lien_days, 'number') + fld('nonp_lead_days', 'Prepare the NONP this many days before the deadline', s.nonp_lead_days, 'number') +
    fld('lien_kinds', 'Applies to (install, service)', s.lien_kinds) + fld('company_name', 'Company name on notices and invoices', s.company_name) +
    fld('company_address', 'Company address', s.company_address) + fld('company_phone', 'Company phone', s.company_phone) + '</div>' +
    chk('nonp_auto', 'Email the Notice of Nonpayment to the owner automatically', s.nonp_auto) + '</div>';
  h += '<button class="primary" onclick="saveSettings()">Save settings</button>';
  document.getElementById('p-settings').innerHTML = h;
}
function fld(k, label, v, type){ return '<div><label>' + esc(label) + '</label><input id="s-' + k + '" type="' + (type || 'text') + '" value="' + esc(v) + '"></div>'; }
function chk(k, label, v){ return '<label style="display:flex;gap:8px;align-items:center;font-weight:500;color:var(--ink)"><input type="checkbox" id="s-' + k + '" style="width:auto"' + (v ? ' checked' : '') + '>' + esc(label) + '</label>'; }
function saveSettings(){
  var d = {}, v = function(k){ return document.getElementById('s-' + k); };
  ['from_email','cc','send_hours','signature','install_words','retainage_pcts','lien_kinds','company_name','company_address','company_phone'].forEach(function(k){ d[k] = v(k).value; });
  ['promise_grace_days','reported_paid_wait_days','min_balance','retainage_tolerance','retainage_every_days','max_attach_mb','lien_days','nonp_lead_days'].forEach(function(k){ d[k] = v(k).value; });
  ['auto_send','read_replies','enabled','nonp_auto'].forEach(function(k){ d[k] = v(k).checked; });
  if(d.auto_send && !D.settings.auto_send && !confirm('Follow-ups will be emailed to customers from ' + d.from_email + ' without review. Turn on?')) return;
  d.stages = D.settings.stages.map(function(st, n){ return {key: st.key, name: document.getElementById('st-name-' + n).value, from_days: document.getElementById('st-from-' + n).value, every_days: document.getElementById('st-every-' + n).value}; });
  post('/receivables/api/settings', d).then(function(){ toast('Settings saved'); load(); });
}

function renderActivity(){
  var h = '<div class="card"><h3>Activity</h3>';
  D.activity.forEach(function(a){ h += '<div class="item small"><span class="muted">' + esc(a.at) + ' · ' + esc(a.kind) + '</span><br>' + esc(a.message) + '</div>'; });
  if(!D.activity.length) h += '<div class="empty">Nothing yet.</div>';
  document.getElementById('p-activity').innerHTML = h + '</div>';
}

// ── Drawer: one invoice's breakdown ──
var CUR_INV = null, CUR_JOB = null;
function openDrawer(h){ var d = document.getElementById('drawer'); d.innerHTML = h; d.classList.add('open'); document.getElementById('dbg').classList.add('open'); d.scrollTop = 0; }
function closeDrawer(){ document.getElementById('drawer').classList.remove('open'); document.getElementById('dbg').classList.remove('open'); CUR_INV = null; CUR_JOB = null; }
function openInvoice(id){
  CUR_INV = id; CUR_JOB = null;
  getJ('/receivables/api/invoice/' + id).then(function(j){
    if(!j.success){ toast(j.error); return; }
    var i = j.invoice, job = j.job, c = j.customer || {}, p = j.plan;
    var h = '<button class="close" onclick="closeDrawer()">✕</button><h2 style="margin-top:0">Invoice #' + esc(i.number) + ' ' + kindBadge(i.kind) + ' ' + badge('b-' + i.status, (D.statuses || {})[i.status] || i.status) + '</h2>';
    h += '<div class="card"><h3>Where it stands</h3><dl class="kv">' +
      '<dt>Customer</dt><dd>' + esc(c.name || i.customer) + (i.qb_job ? ' : ' + esc(i.qb_job) : '') + '</dd>' +
      '<dt>Open balance</dt><dd><b>' + money(i.open_balance) + '</b>' + (i.amount != null ? ' of ' + money(i.amount) : '') + '</dd>' +
      '<dt>Invoice / due date</dt><dd>' + md(i.txn_date) + ' / ' + md(i.due_date) + (p.dpd > 0 ? ' · <b>' + p.dpd + ' days past due</b>' : '') + '</dd>' +
      '<dt>Stage</dt><dd>' + esc(p.stage_name || '—') + (i.followup_count ? ' · ' + i.followup_count + ' follow-up(s), last ' + esc((i.last_followup_at || '').slice(0,10)) : ' · not followed up yet') + '</dd>' +
      '<dt>Next step</dt><dd>' + (p.due_now ? '<b>Follow-up due now</b>' : esc(p.reason)) + '</dd>' +
      '<dt>Follow up with</dt><dd>' + (j.contacts.length ? esc(j.contacts.join(', ')) : '<b style="color:var(--bad)">No email address</b>') + (job && job.contact_name ? ' (' + esc(job.contact_name) + ')' : (c.contact_name ? ' (' + esc(c.contact_name) + ')' : '')) + '</dd>' +
      (i.needs_reason ? '<dt>Needs</dt><dd style="color:var(--bad)">' + esc(i.needs_reason) + '</dd>' : '') +
      (i.promised_date || i.promised_on ? '<dt>Promise</dt><dd>' + (i.promised_on ? 'Said on ' + md(i.promised_on) : '') + (i.promised_date ? ', for ' + md(i.promised_date) : '') + '</dd>' : '') +
      (i.last_reply_summary ? '<dt>Last reply</dt><dd>' + esc(i.last_reply_summary) + '</dd>' : '') +
      (i.terms ? '<dt>Terms</dt><dd>' + esc(i.terms) + '</dd>' : '') + (i.po ? '<dt>PO #</dt><dd>' + esc(i.po) + '</dd>' : '') + (i.memo ? '<dt>Memo</dt><dd>' + esc(i.memo) + '</dd>' : '') +
      '</dl><div class="row" style="margin-top:10px">' +
      '<button class="sm primary" onclick="invAction(' + id + ',\'draft\')">Draft a follow-up now</button>' +
      (i.status === 'open' ? '<button class="sm" onclick="invAction(' + id + ',\'pause\')">Pause follow-ups</button>' : '<button class="sm" onclick="invAction(' + id + ',\'resume\')">Resume follow-ups</button>') +
      '<button class="sm" onclick="invPromise(' + id + ')">Payment promised…</button>' +
      '<button class="sm" onclick="invSnooze(' + id + ')">Snooze…</button>' +
      '<button class="sm danger" onclick="invAction(' + id + ',\'close\')">Close (paid / written off)</button></div></div>';
    // Retainage
    h += '<div class="card"><h3>Retainage</h3>';
    h += i.retainage ? '<div>' + badge('b-ret', 'Retainage') + ' ' + money(i.open_balance) + (i.retainage_pct ? ' held (' + i.retainage_pct + '% of ' + money(i.amount || i.jobber_total) + ')' : '') + '. ' + (job && job.complete_now ? 'The job is complete, so it is being asked for.' : 'Held until the job is complete.') + '</div>'
                      : '<div class="muted">Not retainage' + (i.amount && i.open_balance < i.amount ? ' (partly paid: ' + money(i.amount - i.open_balance) + ' received)' : '') + '.</div>';
    if(job){
      var held = j.siblings.filter(function(x){ return x.retainage; });
      var tot = held.reduce(function(t,x){ return t + x.open_balance; }, 0);
      h += '<div class="small" style="margin-top:6px">On this job: ' + j.siblings.length + ' open invoice(s); retainage ' + money(tot) + ' on ' + held.length + '.</div>';
    }
    h += '<div class="row" style="margin-top:8px"><span class="small muted">Retainage:</span><button class="sm" onclick="invSet(' + id + ',{retainage:true})">Yes</button><button class="sm" onclick="invSet(' + id + ',{retainage:false})">No</button><button class="sm" onclick="invSet(' + id + ',{retainage:\'auto\'})">Auto</button>' +
         '<span class="small muted" style="margin-left:10px">Type:</span><button class="sm" onclick="invSet(' + id + ',{kind:\'service\'})">Service</button><button class="sm" onclick="invSet(' + id + ',{kind:\'install\'})">Install</button><button class="sm" onclick="invSet(' + id + ',{kind:\'auto\'})">Auto</button></div></div>';
    // Job + lien
    if(job){
      var l = job.lien || {};
      h += '<div class="card"><h3>Job: ' + esc(job.name) + '</h3><dl class="kv">' +
        (job.property_address ? '<dt>Property</dt><dd>' + esc(job.property_address) + '</dd>' : '') +
        '<dt>Complete</dt><dd>' + (job.complete_now ? 'Yes' : 'No') + (job.jobber_completed_at ? ' (Jobber ' + md(job.jobber_completed_at) + ')' : '') + '</dd>' +
        (l.applies ? '<dt>Last furnished</dt><dd>' + md(l.last_furnished) + (l.estimated ? ' (estimated)' : '') + '</dd><dt>Lien deadline</dt><dd><b>' + md(l.deadline) + '</b>' + (l.days_left != null ? ' (' + (l.days_left < 0 ? 'passed' : l.days_left + ' days left') + ')' : '') + '</dd><dt>Notice of Nonpayment</dt><dd>' + esc(job.nonp_status || 'not started') + '</dd>' : '') +
        '</dl><div class="row" style="margin-top:8px"><button class="sm" onclick="openJob(\'' + esc(job.key) + '\')">Open job</button>' + (job.jobber_job_uri ? '<a class="small" target="_blank" href="' + esc(job.jobber_job_uri) + '">Job in Jobber ↗</a>' : '') + '</div>';
      h += '<table style="margin-top:8px"><thead><tr><th>Invoice</th><th>Date</th><th class="num">Amount</th><th class="num">Open</th><th></th></tr></thead><tbody>';
      j.siblings.forEach(function(x){ h += '<tr' + (x.id === i.id ? ' style="background:var(--brand-light)"' : ' class="click" onclick="openInvoice(' + x.id + ')"') + '><td>#' + esc(x.number) + '</td><td>' + md(x.txn_date) + '</td><td class="num">' + (x.amount != null ? money(x.amount) : '') + '</td><td class="num">' + money(x.open_balance) + '</td><td>' + (x.retainage ? badge('b-ret', 'Retainage') : '') + '</td></tr>'; });
      h += '</tbody></table></div>';
    }
    // Jobber
    h += '<div class="card"><h3>Jobber</h3>';
    if(i.jobber_id){
      h += '<dl class="kv"><dt>Status</dt><dd>' + esc((i.jobber_status || '').replace('_', ' ')) + '</dd><dt>Total / paid / balance</dt><dd>' + money(i.jobber_total) + ' / ' + money(i.jobber_paid) + ' / ' + money(i.jobber_balance) + '</dd>' +
           (i.jobber_subject ? '<dt>Subject</dt><dd>' + esc(i.jobber_subject) + '</dd>' : '') + (i.billing_address ? '<dt>Billing address</dt><dd>' + esc(i.billing_address) + '</dd>' : '') + '<dt>Checked</dt><dd>' + esc(i.jobber_checked_at || '') + '</dd></dl>';
      if(i.jobber_lines.length){ h += '<div class="small" style="margin-top:6px">'; i.jobber_lines.forEach(function(ln){ h += '<div class="item"><b>' + esc(ln.name) + '</b> ' + money(ln.totalPrice) + '<div class="muted" style="white-space:pre-wrap">' + esc(ln.description || '') + '</div></div>'; }); h += '</div>'; }
      h += '<div class="row"><a target="_blank" href="' + esc(i.jobber_uri) + '">Open in Jobber ↗</a>' + (i.client_hub_uri ? '<a target="_blank" href="' + esc(i.client_hub_uri) + '">Client hub link ↗</a>' : '') + '</div>';
    } else h += '<div class="muted">' + esc(i.jobber_error || 'Not looked up yet.') + '</div>';
    h += '<div class="row" style="margin-top:8px"><button class="sm" onclick="invAction(' + id + ',\'jobber\')">Check Jobber again</button></div></div>';
    // Documents
    h += '<div class="card"><h3>What goes with the email</h3><div class="small">';
    var invPdf = j.docs.filter(function(d){ return d.scope === 'invoice' && d.kind === 'invoice_pdf'; });
    h += invPdf.length ? '' : '📄 <a target="_blank" href="/receivables/invoice/' + id + '.pdf">Invoice-' + esc(i.number) + '.pdf</a> (made from ' + (i.jobber_id ? 'Jobber' : 'QuickBooks') + ')<br>';
    j.docs.forEach(function(d){ if(d.scope === 'job' && i.kind !== 'install') return; h += '📎 <a target="_blank" href="/receivables/docs/' + d.id + '">' + esc(d.filename) + '</a> <span class="muted">(' + esc(d.scope === 'all' ? 'every email' : d.scope) + ')</span> <a href="#" onclick="docDelete(' + d.id + ');return false" style="color:var(--bad)">remove</a><br>'; });
    h += '</div><div class="row" style="margin-top:8px"><button class="sm" onclick="docUpload(\'invoice\',\'' + id + '\',\'invoice_pdf\')">Upload the invoice PDF</button><button class="sm" onclick="docUpload(\'invoice\',\'' + id + '\')">+ Other document</button>' + (job ? '<button class="sm" onclick="docUpload(\'job\',\'' + esc(job.key) + '\')">+ Install document for the job</button>' : '') + '</div></div>';
    // Notes
    h += '<div class="card"><h3>Notes and history</h3><textarea id="inv-note" placeholder="Add a note" style="min-height:60px"></textarea><div class="row" style="margin:6px 0 10px"><button class="sm primary" onclick="invNote(' + id + ')">Add note</button></div><div class="timeline">';
    j.notes.forEach(function(n){ h += '<div class="t ' + esc(n.kind) + '"><div class="small muted">' + esc(n.at) + ' · ' + esc(n.by) + '</div>' + esc(n.text) + '</div>'; });
    h += '</div></div>';
    if(j.emails.length){ h += '<div class="card"><h3>Emails</h3>'; j.emails.forEach(function(e){ h += '<div class="item small">' + badge(e.status === 'sent' ? 'b-promised' : 'b-open', e.status) + ' ' + esc(e.sent_at || e.created_at) + ' · ' + esc(e.subject) + ' <a href="#" onclick="openEmail(' + e.id + ');return false">open</a></div>'; }); h += '</div>'; }
    openDrawer(h); CUR_INV = id;
  });
}
function invSet(id, body){ body.id = id; return post('/receivables/api/invoice', body).then(function(){ load().then(function(){ openInvoice(id); }); }); }
function invAction(id, action){
  if(action === 'close' && !confirm('Close this invoice? It will not be followed up again (until it shows up on a QuickBooks upload).')) return;
  post('/receivables/api/invoice', {id:id, action:action}).then(function(j){
    if(action === 'draft'){ toast('Draft ready on the Today tab'); }
    if(action === 'jobber'){ toast('Checking Jobber…'); setTimeout(function(){ load().then(function(){ openInvoice(id); }); }, 4000); return; }
    load().then(function(){ openInvoice(id); });
  });
}
function invPromise(id){ var d = prompt('Date they said it will be paid (MM/DD/YYYY, or leave blank):', ''); if(d === null) return; post('/receivables/api/invoice', {id:id, action:'promise', date:toIso(d)}).then(function(){ load().then(function(){ openInvoice(id); }); }); }
function invSnooze(id){ var d = prompt('No follow-ups until (MM/DD/YYYY):', ''); if(!d) return; post('/receivables/api/invoice', {id:id, action:'snooze', date:toIso(d)}).then(function(){ load().then(function(){ openInvoice(id); }); }); }
function invNote(id){ var t = document.getElementById('inv-note').value.trim(); if(!t) return; post('/receivables/api/invoice', {id:id, note:t}).then(function(){ openInvoice(id); }); }
function toIso(d){ d = (d || '').trim(); var m = d.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/); if(m){ var y = m[3].length === 2 ? '20' + m[3] : m[3]; return y + '-' + ('0' + m[1]).slice(-2) + '-' + ('0' + m[2]).slice(-2); } return d; }

// ── Drawer: a job ──
function openJob(key){
  var j = D.jobs.filter(function(x){ return x.key === key; })[0];
  if(!j){ toast('That job has nothing open'); return; }
  CUR_JOB = key; CUR_INV = null;
  getJ('/receivables/api/job_notes?key=' + encodeURIComponent(key)).then(function(x){
    var l = j.lien || {}, inv = D.invoices.filter(function(i){ return i.job_key === key && i.status !== 'paid'; });
    var h = '<button class="close" onclick="closeDrawer()">✕</button><h2 style="margin-top:0">' + esc(j.name) + ' ' + kindBadge(j.kind) + '</h2>';
    h += '<div class="kpis">' + kpi(money(j.open_balance), j.open_count + ' open invoices') + kpi(money(j.retainage_held), 'retainage on ' + j.retainage_count) +
         (l.applies ? kpi(md(l.deadline) || '—', l.days_left == null ? 'lien deadline' : (l.days_left < 0 ? 'lien deadline passed' : l.days_left + ' days to lien deadline')) : '') + '</div>';
    h += '<div class="card"><h3>Job details</h3><div class="grid2">' +
      jf('name', 'Job name', j.name) + jf('property_address', 'Property address', j.property_address) +
      jf('contact_name', 'Follow up with (name)', j.contact_name) + jf('contact_emails', 'Follow up with (emails; blank = the customer\'s)', j.contact_emails) +
      jf('owner_name', 'Property owner (for the NONP)', j.owner_name || (j.owner && j.owner[0]) || '') + jf('owner_email', 'Owner email', j.owner_email || (j.owner && j.owner[1]) || '') +
      jf('owner_address', 'Owner mailing address', j.owner_address) + jf('first_furnished', 'First day furnished (MM/DD/YYYY)', md(j.first_furnished)) +
      jf('last_furnished', 'Last day furnished (MM/DD/YYYY)', md(j.last_furnished)) +
      '<div><label>Job complete (retainage due)</label><select id="j-complete"><option value="auto"' + (j.complete == null ? ' selected' : '') + '>Auto (from Jobber: ' + (j.jobber_completed_at ? 'complete' : 'not complete') + ')</option><option value="1"' + (j.complete === 1 ? ' selected' : '') + '>Complete</option><option value="0"' + (j.complete === 0 ? ' selected' : '') + '>Not complete</option></select></div>' +
      '</div><label>Notes</label><textarea id="j-notes">' + esc(j.notes) + '</textarea><div class="row" style="margin-top:8px"><button class="primary" onclick="saveJob(\'' + esc(key) + '\')">Save job</button>' + (j.jobber_job_uri ? '<a target="_blank" href="' + esc(j.jobber_job_uri) + '">Job in Jobber ↗</a>' : '') + '</div></div>';
    if(l.applies){
      h += '<div class="card"><h3>Lien and Notice of Nonpayment</h3><div class="small">Last furnished ' + md(l.last_furnished) + (l.estimated ? ' (estimated from the last invoice date; enter the real date above)' : '') + ' → claim of lien by <b>' + md(l.deadline) + '</b>. The notice is prepared ' + D.settings.nonp_lead_days + ' days before that if money is still owed and past due.</div>' +
        '<div class="row" style="margin-top:8px"><span>Step: <b>' + esc(j.nonp_status || 'not started') + '</b></span><a target="_blank" href="/receivables/nonp.pdf?key=' + encodeURIComponent(key) + '">Preview notice ↗</a>' +
        (!j.nonp_status ? '<button class="sm primary" onclick="prepNonp(\'' + esc(key) + '\')">Prepare now</button>' : '') +
        (j.nonp_status === 'sent' || j.nonp_status === 'prepared' ? '<button class="sm" onclick="nonpStep(\'' + esc(key) + '\',\'mailed\')">Mailed certified</button>' : '') +
        (j.nonp_status === 'mailed' || j.nonp_status === 'sent' ? '<button class="sm" onclick="nonpStep(\'' + esc(key) + '\',\'lien_recorded\')">Lien recorded</button>' : '') +
        (j.nonp_status ? '<button class="sm danger" onclick="nonpStep(\'' + esc(key) + '\',\'\')">Reset</button>' : '') + '</div></div>';
    }
    h += '<div class="card"><h3>Invoices</h3><table><thead><tr><th>Invoice</th><th>Date</th><th class="num">Amount</th><th class="num">Open</th><th>Status</th></tr></thead><tbody>';
    inv.forEach(function(i){ h += '<tr class="click" onclick="openInvoice(' + i.id + ')"><td>#' + esc(i.number) + ' ' + (i.retainage ? badge('b-ret', 'Retainage') : '') + '</td><td>' + md(i.txn_date) + '</td><td class="num">' + (i.amount != null ? money(i.amount) : '') + '</td><td class="num">' + money(i.open_balance) + '</td><td>' + statusBadge(i) + '</td></tr>'; });
    h += '</tbody></table></div>';
    h += '<div class="card"><h3>Install documents</h3><p class="muted small">Attached to every follow-up on this job.</p>';
    x.docs.forEach(function(d){ h += '📎 <a target="_blank" href="/receivables/docs/' + d.id + '">' + esc(d.filename) + '</a> <a href="#" onclick="docDelete(' + d.id + ');return false" style="color:var(--bad)" class="small">remove</a><br>'; });
    h += '<button class="sm" style="margin-top:6px" onclick="docUpload(\'job\',\'' + esc(key) + '\')">+ Add document</button></div>';
    h += '<div class="card"><h3>Notes and history</h3><textarea id="job-note" placeholder="Add a note" style="min-height:60px"></textarea><div class="row" style="margin:6px 0 10px"><button class="sm primary" onclick="jobNote(\'' + esc(key) + '\')">Add note</button></div><div class="timeline">';
    x.notes.forEach(function(n){ h += '<div class="t ' + esc(n.kind) + '"><div class="small muted">' + esc(n.at) + ' · ' + esc(n.by) + '</div>' + esc(n.text) + '</div>'; });
    h += '</div></div>';
    openDrawer(h); CUR_JOB = key;
  });
}
function jf(k, label, v){ return '<div><label>' + esc(label) + '</label><input id="j-' + k + '" value="' + esc(v || '') + '"></div>'; }
function saveJob(key){
  var d = {key:key}, g = function(k){ return document.getElementById('j-' + k).value; };
  ['name','property_address','contact_name','contact_emails','owner_name','owner_email','owner_address','notes'].forEach(function(k){ d[k] = g(k); });
  d.first_furnished = toIso(g('first_furnished')); d.last_furnished = toIso(g('last_furnished'));
  var c = g('complete'); d.complete = c === 'auto' ? 'auto' : c === '1';
  post('/receivables/api/job', d).then(function(){ toast('Saved'); load().then(function(){ openJob(key); }); });
}
function jobNote(key){ var t = document.getElementById('job-note').value.trim(); if(!t) return; post('/receivables/api/job', {key:key, note:t}).then(function(){ openJob(key); }); }
function prepNonp(key){
  if(!confirm('Prepare the Notice of Nonpayment for this job? A draft email to the owner (with the notice attached) will be ready to review on the Today tab.')) return;
  post('/receivables/api/job', {key:key, action:'nonp'}).then(function(){ toast('Notice prepared: review it on the Today tab'); load().then(function(){ if(CUR_JOB) openJob(key); }); });
}
function nonpStep(key, step){ post('/receivables/api/job', {key:key, nonp_status:step}).then(function(){ load().then(function(){ openJob(key); }); }); }

// ── Upload / run ──
function uploadAR(inp, confirmed){
  if(!inp.files[0]) return;
  var fd = new FormData(); fd.append('file', inp.files[0]); if(confirmed) fd.append('confirm', '1');
  toast('Reading ' + inp.files[0].name + '…');
  fetch('/receivables/api/upload', {method:'POST', headers:{'X-CSRFToken':CSRF}, body:fd}).then(function(r){ return r.json(); }).then(function(j){
    if(!j.success){ toast(j.error); inp.value = ''; return; }
    if(j.needs_confirm){
      if(confirm('This file leaves out ' + j.missing + ' of the ' + j.open + ' invoices open here, so they would all be closed as paid. Is this the full A/R list?')) return uploadAR(inp, true);
      inp.value = ''; return;
    }
    var s = j.summary; inp.value = '';
    toast(s.open + ' open invoices: ' + s['new'] + ' new, ' + s.closed + ' paid since last time, ' + s.paid_down + ' partly paid. Checking Jobber…');
    load(); setTimeout(load, 15000);
  });
}
function runNow(){ post('/receivables/api/run').then(function(){ toast('Running: Jobber, replies, follow-ups and lien deadlines…'); setTimeout(load, 8000); }); }

load();
setInterval(function(){ if(!document.getElementById('drawer').classList.contains('open')) load(); }, 120000);
</script>
</body>
</html>
'''
