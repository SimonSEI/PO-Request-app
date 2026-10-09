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
.layout{display:grid;grid-template-columns:minmax(300px,370px) minmax(0,1fr);align-items:start;}
.mainc{min-width:0;}
.side{min-width:0;position:sticky;top:56px;max-height:calc(100vh - 56px);overflow-y:auto;background:#fff;border-right:1px solid var(--border);}
.side .hd{padding:12px 14px 8px;display:flex;flex-direction:column;gap:8px;border-bottom:1px solid var(--border);position:sticky;top:0;background:#fff;z-index:2;}
.side .hd h2{font-size:15px;display:flex;align-items:center;gap:8px;}
.side .grp{padding:8px 14px 4px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);background:var(--bg);border-bottom:1px solid var(--border);}
.side .row{padding:9px 14px;}
.side .row .tt{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;}
.side .act{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;}
.side details summary{cursor:pointer;list-style:none;}
.side details summary::-webkit-details-marker{display:none;}
.side details[open] summary .arr{transform:rotate(90deg);}
.side .arr{display:inline-block;transition:transform .15s;}
@media (max-width:900px){.layout{grid-template-columns:minmax(0,1fr);}.side{position:static;max-height:none;border-right:none;border-bottom:1px solid var(--border);}}
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
.money{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;}
.money .m{border:1px solid var(--border);border-radius:10px;padding:10px;}
.money .m .k{font-size:11.5px;color:var(--muted);}
.money .m .v{font-size:17px;font-weight:700;margin-top:3px;font-variant-numeric:tabular-nums;}
.cmp{margin-top:8px;padding:8px 12px;border-radius:8px;font-size:13px;font-weight:600;}
.cmp.match{background:var(--green-bg);color:#166534;} .cmp.over,.cmp.under,.cmp.no_quote{background:var(--red-bg);color:var(--red);}
.issue{background:var(--red-bg);color:var(--red);border-radius:10px;padding:10px 12px;font-size:13px;display:flex;justify-content:space-between;gap:10px;align-items:center;}
.issue.done{background:var(--slate-bg);color:var(--muted);}
.docs .d{display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);flex-wrap:wrap;}
.ev{font-size:12px;color:var(--muted);padding:5px 0;border-bottom:1px dashed var(--border);}
.track{display:flex;align-items:flex-start;margin:4px 0 14px;}
.track .n{flex:1;min-width:0;text-align:center;position:relative;font-size:10.5px;color:var(--muted);line-height:1.25;padding:0 2px;}
.track .n::before{content:'';position:absolute;top:9px;left:-50%;right:50%;height:3px;background:var(--border);z-index:0;}
.track .n:first-child::before{display:none;}
.track .n.done::before,.track .n.cur::before{background:var(--green);}
.track .b{width:20px;height:20px;border-radius:50%;margin:0 auto 4px;background:#fff;border:2px solid var(--border);position:relative;z-index:1;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;}
.track .n.done .b{background:var(--green);border-color:var(--green);}
.track .n.cur .b{border-color:var(--brand);box-shadow:0 0 0 4px #DBEAFE;}
.track .n.cur{color:var(--brand);font-weight:700;}
.track .n.done{color:var(--text);}
.track .d{font-size:10px;color:var(--muted);font-weight:400;margin-top:1px;}
.tl{position:relative;padding-left:4px;}
.tl .day{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin:10px 0 4px 34px;}
.tl .it{display:flex;gap:10px;position:relative;padding:4px 0;}
.tl .it::before{content:'';position:absolute;left:13px;top:0;bottom:0;width:2px;background:var(--border);}
.tl .ic{width:28px;height:28px;flex:none;border-radius:50%;background:var(--slate-bg);display:flex;align-items:center;justify-content:center;font-size:13px;position:relative;z-index:1;border:2px solid #fff;}
.tl .ic.g{background:var(--green-bg);} .tl .ic.r{background:var(--red-bg);} .tl .ic.b{background:#DBEAFE;} .tl .ic.a{background:var(--amber-bg);}
.tl .tx{font-size:13px;padding-top:4px;min-width:0;} .tl .tx .m{font-size:12px;color:var(--muted);margin-top:1px;overflow-wrap:anywhere;}
@media (max-width:640px){.track .n{font-size:0;} .track .n.cur{font-size:10.5px;}}
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
/* pipeline dashboard */
.pl{--st1:#86b6ef;--st2:#5598e7;--st3:#2a78d6;--st4:#1c5cab;--st5:#104281;--st6:#0a2a52;
    --k1:#2a78d6;--k2:#eb6834;--k3:#1baf7a;--k4:#eda100;--warn:#fab219;--ink2:#52514e;--grid:#e8e7e3;}
.pl .sample{background:#fff7e0;border:1px solid #f4d58a;border-radius:10px;padding:10px 14px;margin-bottom:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:13px;}
.pl .kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px;}
.pl .kpi{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px 14px;}
.pl .kpi .k{font-size:12px;color:var(--muted);} .pl .kpi .v{font-size:26px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums;}
.pl .kpi .s{font-size:11.5px;color:var(--muted);}
.pl .card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px 16px;margin-bottom:16px;}
.pl .card h3{font-size:14px;margin-bottom:2px;} .pl .card .sub{font-size:12px;color:var(--muted);margin-bottom:10px;}
.pl .jobs{margin-top:12px;border-top:1px solid var(--border);padding-top:10px;}
.pl .job{display:flex;gap:10px;align-items:center;padding:7px 4px;border-bottom:1px solid var(--border);font-size:13px;}
.pl .job .t{flex:1;min-width:0;} .pl .job .t .c{font-size:11.5px;color:var(--muted);}
.pl .job .d{font-size:12px;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums;}
.pl .legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin-bottom:6px;}
.pl .legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px;}
.pl .chevs{display:grid;grid-template-columns:repeat(6,minmax(118px,1fr));gap:6px;overflow-x:auto;padding:4px 2px 10px;}
.pl .chev{position:relative;min-height:112px;padding:14px 26px 14px 34px;text-align:center;cursor:pointer;border:0;font:inherit;
    clip-path:polygon(0 0,calc(100% - 22px) 0,100% 50%,calc(100% - 22px) 100%,0 100%,22px 50%);
    display:flex;flex-direction:column;justify-content:center;gap:2px;transition:transform .12s, filter .12s;}
.pl .chev:first-child{clip-path:polygon(0 0,calc(100% - 22px) 0,100% 50%,calc(100% - 22px) 100%,0 100%);padding-left:16px;border-radius:8px 0 0 8px;}
.pl .chev:hover,.pl .chev:focus-visible{filter:brightness(1.07);outline:none;}
.pl .chev.on{transform:translateY(-4px);}
.pl .chev .n{font-size:12px;font-weight:600;opacity:.85;}
.pl .chev .nm{font-size:15px;font-weight:700;}
.pl .chev .ct{font-size:28px;font-weight:800;line-height:1.1;font-variant-numeric:tabular-nums;}
.pl .chev .ex{font-size:11.5px;opacity:.9;min-height:15px;}
.pl .chev.dk{color:#0b0b0b;} .pl .chev.lt{color:#fff;}
.pl .marks{display:grid;grid-template-columns:repeat(6,minmax(118px,1fr));gap:6px;height:12px;margin-top:-6px;}
.pl .marks span{display:block;margin:0 auto;width:0;height:0;border-left:9px solid transparent;border-right:9px solid transparent;border-bottom:10px solid var(--border);visibility:hidden;}
.pl .marks span.on{visibility:visible;}
.pl svg text{font-family:inherit;}
.pl .tip{position:fixed;pointer-events:none;background:#fff;border:1px solid var(--border);border-radius:8px;box-shadow:0 6px 18px rgba(15,23,42,.12);padding:8px 10px;font-size:12px;z-index:50;max-width:280px;}
.pl .tip .v{font-weight:700;font-size:13px;} .pl .tip .l{color:var(--muted);}
.pl .tip .ln{display:inline-block;width:12px;height:2px;margin-right:6px;vertical-align:middle;}
.pl .wk{display:grid;grid-template-columns:110px 1fr;gap:6px 12px;font-size:13px;padding:8px 0;border-bottom:1px solid var(--border);}
.pl .wk .w{color:var(--muted);font-size:12px;}
.pl .ev{display:flex;gap:8px;align-items:baseline;} .pl .ev .dt{color:var(--muted);font-size:12px;width:52px;flex:none;font-variant-numeric:tabular-nums;}
.pl .ev .ln{display:inline-block;width:10px;height:3px;border-radius:2px;flex:none;transform:translateY(-3px);}
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
    <button class="btn" onclick="showUndo()" title="Undo a recent change">↶ Undo</button>
    <a class="btn" href="{{ url_for('dashboard') }}">← Dashboard</a>
  </div>
</nav>
<div class="strip">
  <div>PO@ mailbox: {% if email %}<b class="ok">connected</b> · <span id="scanInfo">…</span>
    <button class="btn s" id="scanBtn" onclick="scanNow()">Scan now</button> <button class="btn s" onclick="showRecentFiles()" title="What happened to each emailed file">Recent files</button>{% else %}<b class="warn">not configured</b> (upload documents by hand){% endif %}</div>
  <div>Jobber: <span id="jobberInfo">{% if jobber.connected %}<b class="ok">connected</b>{% elif jobber.can_connect %}<a class="btn s p" href="{{ url_for('pumps.jobber_connect') }}">Connect Jobber</a>{% else %}<b class="warn">not set up</b>{% endif %}</span></div>
  <div>Reading documents: {% if claude and claude_problem %}<b class="bad">Claude is not working</b> ({{ claude_problem }}) - new documents wait in the To do list and are read again automatically once it works{% elif claude %}<b class="ok">Claude</b>{% else %}<b class="ok">built-in reader</b> (Wettech and Gulfshore quotes, invoices and reports; anything it can't read waits in the To do list){% endif %}</div>
  <div>Daily email: <span id="digestInfo">to {{ digest_to }} at {{ digest_hour }}am on weekdays</span>
    <button class="btn s" onclick="previewDigest()">Preview</button></div>
</div>
{% if flash_msg %}<div class="flash">{{ flash_msg }}</div>{% endif %}

<div class="layout">
<aside class="side" id="side">
  <div class="hd">
    <h2>✅ To do <span class="chip" id="sideCount"></span><span class="sp" style="flex:1"></span><span class="note" id="sideOpen" style="font-weight:500"></span></h2>
    <input type="text" id="caseSearch" placeholder="Find a job, PO, quote or invoice #…" oninput="searchCases(this.value)">
    <div style="display:flex;gap:6px">
      <select id="uploadKind" title="What the files are" style="flex:1;min-width:0"><option value="">Upload: let the app decide</option><option value="quote">Upload quotes</option><option value="bill">Upload bills</option><option value="report">Upload reports</option></select>
      <button class="btn" onclick="document.getElementById('fileIn').click()">⬆ Upload</button>
      <input type="file" id="fileIn" multiple accept=".pdf,.docx,.doc" class="hide" onchange="uploadFiles(this.files)"></div>
  </div>
  <div id="searchResults" class="hide"></div>
  <div id="todoList"><div class="empty">Loading…</div></div>
</aside>
<div class="mainc">
<div class="tabs" id="tabs">
  <div class="tab on" data-tab="jobs">Jobs <span class="n" id="n-jobs"></span></div>
  <div class="tab" data-tab="scada">SCADA <span class="n" id="n-scada"></span></div>
  <div class="tab" data-tab="accounts">Accounts</div>
  <div class="tab" data-tab="reports">Reports</div>
</div>

<!-- JOBS -->
<div class="panel" id="p-jobs">
  <div class="toolbar">
    <input type="text" id="jbSearch" placeholder="Find a job, client, PO, quote or invoice #…" oninput="clearTimeout(window._jq);window._jq=setTimeout(loadJobs,300)" style="width:240px">
    <select id="jbShow" onchange="loadJobs()"><option value="open">Open</option><option value="closed">Done</option><option value="all">All</option></select>
    <div class="sp"></div><span id="syncInfo" class="note"></span>
    <button class="btn s" title="It syncs on its own - this just does it now" onclick="syncJobber()">↻ Sync now</button>
  </div>
  <div class="scroll"><table class="t"><thead><tr><th>Job</th><th>Where it is</th><th>Vendor</th><th class="num">Vendor quote</th><th>Our quote</th><th class="num">Vendor bill</th><th>Our invoice</th><th>Vendor paid</th><th></th></tr></thead><tbody id="jobsBody"></tbody></table></div>
  <h3 style="margin:18px 0 8px;font-size:14px">Quotes sent - waiting on the client <span class="chip" id="jbSentCount"></span></h3>
  <div class="note" style="margin-bottom:8px">Our pump, diver, filter and SCADA quotes in Jobber that have gone to the client and aren't approved yet, longest waiting first. They drop off once the client approves (the next Jobber sync).</div>
  <div class="scroll" style="max-height:40vh"><table class="t"><thead><tr><th>Quote</th><th>Client</th><th class="num">Total</th><th>Status</th><th>Waiting</th><th>Job here</th></tr></thead><tbody id="jbSentBody"></tbody></table></div>
</div>

<!-- SCADA -->
<div class="panel hide" id="p-scada">
  <div class="toolbar"><div class="note">The SCADA sheet: <b>Renewal date</b> is when the next renewal is due; each year holds our invoice # or a note. When one's renewed, <b>Renewed…</b> records it and moves the date on a year. Due within {{ scada_days }} days: the app drafts the client's quote in Jobber at their price (complimentary ones are just a reminder) and it shows on Today. Each Jobber sync fills in the year's invoice # from the SCADA renewal invoices it finds.</div><div class="sp"></div>
    <select id="scShow" onchange="loadScada()"><option value="active">On SCADA</option><option value="all">All, incl. stopped</option></select>
    <button class="btn" onclick="scadaEdit(0)">＋ Add client</button></div>
  <div class="scroll"><table class="t" id="scadaTable"></table></div>
</div>

<!-- ACCOUNTS -->
<div class="panel hide" id="p-accounts">
  <div class="toolbar">
    <span id="acInfo" class="note"></span><div class="sp"></div>
    <input type="text" id="acSearch" placeholder="Find an account…" oninput="drawAccounts()" style="width:180px">
    <select id="acShow" onchange="drawAccounts()"><option value="active">Active</option><option value="due">Due this month</option><option value="pump">Pump (Wettech)</option><option value="lake">Lake / diver (Gulfshore)</option><option value="scada">On SCADA</option><option value="former">Former</option><option value="">All</option></select>
    <button class="btn" onclick="maintEdit(0)">＋ Pump account</button>
    <button class="btn" onclick="editDiveSite()">＋ Lake site</button>
  </div>
  <div class="note" style="margin-bottom:10px">One row per client: Wettech's pump maintenance (Tommy, tomm@wettec.biz), Gulfshore's lake and diver work (Jordan, Gulfshoreyachts@gmail.com) and SCADA. Recurring Jobber jobs bill the maintenance.</div>
  <div class="scroll"><table class="t"><thead><tr><th>Account</th><th>Pump - Wettech</th><th>Lake - Gulfshore</th><th>SCADA</th><th>Where</th></tr></thead><tbody id="acBody"></tbody></table></div>
  <h3 style="margin:22px 0 8px;font-size:14px">Monthly email to the diver</h3>
  <div class="toolbar"><span id="diveInfo" class="note"></span><div class="sp"></div>
    <button class="btn" onclick="diverTodo(diveMonth())">Email ready to copy</button>
    <a class="btn" id="diveDocx" href="#">⬇ Word list</a>
    <button class="btn" onclick="sendDiveEmail()" title="Send it from the PO mailbox">Send from PO@…</button></div>
  <div class="fields" id="diveSettings"></div>
  <div class="scroll" style="max-height:30vh;margin-top:10px"><table class="t"><thead><tr><th>Month</th><th>Sent</th><th>By</th><th>To</th><th class="num">Sites</th><th>Result</th></tr></thead><tbody id="diveSent"></tbody></table></div>
  <h3 style="margin:22px 0 8px;font-size:14px">Site names</h3>
  <div class="toolbar"><button class="btn" onclick="siteNameAdd()">＋ Site name</button></div>
  <div class="note" style="margin-bottom:8px">How a site is written on the vendors' paperwork, so quotes and reports go to the right Jobber client and job - e.g. "Carlisle" is on the Greenscapes account. Add one from <b>Draft quote</b> (tick "Remember").</div>
  <div class="scroll" style="max-height:40vh"><table class="t"><thead><tr><th>Written as</th><th>Area</th><th>Jobber client</th><th>Property</th><th>Note</th><th></th></tr></thead><tbody id="siteNamesBody"></tbody></table></div>
</div>

<!-- REPORTS -->
<div class="panel hide" id="p-reports">
  <div class="toolbar">
    <select id="repYear" onchange="loadReports()"></select>
    <input type="text" id="repSearch" placeholder="Find a site…" oninput="clearTimeout(window._rq);window._rq=setTimeout(loadReports,300)" style="width:200px">
    <div class="sp"></div><span class="note" id="repInfo"></span>
  </div>
  <div class="note" style="margin-bottom:10px">Every service report from Wettech, rebranded (our letterhead, no Wettech details, no technician, not "Stahlman England" as the customer), by month. Each one goes on the site's pump job in Jobber as "&lt;Month&gt; Pump Maintenance" with the PDF.</div>
  <div id="repBody"></div>
</div>

</div>
</div>

<div id="drawerWrap" class="hide"><div class="shade" onclick="closeDrawer()"></div><div class="drawer" id="drawer"></div></div>
<div id="modalWrap" class="hide"><div class="shade2" onclick="closeModal()"></div><div class="modal" id="modal"></div></div>

<script>
const STEPS = {{ steps|tojson }};
// A new deployment: the page reloads itself to pick it up - right away when
// nothing is open, otherwise once the job or dialog is closed.
const APP_VERSION = {{ app_version|tojson }};
let newVersionSaid = false;
function checkVersion(v){
  if (!v || v === APP_VERSION) return;
  if (document.getElementById('drawerWrap').classList.contains('hide') && document.getElementById('modalWrap').classList.contains('hide')) { location.reload(); return; }
  if (!newVersionSaid) { newVersionSaid = true; toast('The app was updated - it reloads when you close this.'); }
}
const CATS = {{ categories|tojson }};
const JOBBER_OK = {{ 'true' if jobber.connected else 'false' }};
let curTab = 'jobs', curMonth = null, curCase = null;

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
// What a job is waiting on, in plain words, from the first step not done.
function stageText(c){
  const v = c.vendor || 'Wettech', st = c.steps || {};
  const hasBill = c.vendor_bill_amount != null || c.vendor_bill_total != null || !!(st.vendor_bill || {}).at;
  if (c.stage === 'vendor_quote' && hasBill) return `Bill in · waiting on ${v}'s quote`;
  return ({
    assessment: `Waiting on ${v} to assess` + ((st.assessment || {}).due ? ' · ' + st.assessment.due : ''),
    vendor_quote: `Waiting on quote from ${v}`,
    client_quote: 'Send our quote to the client',
    client_approved: 'Waiting on client approval',
    scheduled: `Schedule with ${v}`,
    work_done: `Waiting on ${v} to do the work` + (c.scheduled_for ? ' · ' + c.scheduled_for : ''),
    vendor_bill: `Waiting on bill from ${v}`,
    bill_checked: 'Check the bill against the quote',
    invoice_drafted: 'Draft our invoice in Jobber',
    report_logged: 'Log the report in Jobber',
    closed: 'Send our invoice from Jobber',
    done: 'Done',
  })[c.stage] || stepLabel(c.stage, v);
}
function stageChip(c){ if (c.status === 'closed') return '<span class="chip g">closed</span>'; if (c.status === 'cancelled') return '<span class="chip">cancelled</span>'; const t = stageText(c), red = (c.open_issues || []).some(i => i.kind !== 'no_quote'); return `<span class="chip ${red ? 'r' : /^Waiting/.test(t) ? '' : 'b'}">${esc(t)}</span>`; }
function kindChip(k){ const m = {quote:'b', bill:'a', report:'g', other:''}; return `<span class="chip ${m[k]||''}">${esc(k)}</span>`; }

// ── tabs ───────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(t => t.onclick = () => showTab(t.dataset.tab));
function showTab(name){
  curTab = name;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.tab === name));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('hide', p.id !== 'p-' + name));
  if (name === 'jobs') loadJobs(); else if (name === 'scada') loadScada();
  else if (name === 'accounts') loadAccounts(); else if (name === 'reports') loadReports();
  history.replaceState(null, '', '#' + name);
}

// ── today ──────────────────────────────────────────────
function caseRow(c, extra){
  const who = [c.client_name, c.site].filter(Boolean).join(' · ');
  const po = c.po_number ? ` · PO ${esc(c.po_number)}` : '';
  return `<div class="row" onclick="openCase(${c.id})"><div class="main"><div class="tt">${esc(c.title || c.client_name)}</div>
    <div class="sub">${esc(who)}${po}${extra ? ' · ' + extra : ''}</div></div>
    <div style="text-align:right;display:flex;gap:6px;align-items:center">${c.idle_days >= 7 ? `<div class="chip a">${c.idle_days}d idle</div>` : ''}<button class="btn s" title="Mark done" onclick="event.stopPropagation();caseDone(${c.id})">✓</button><button class="btn s" title="Remove" onclick="event.stopPropagation();caseRemove(${c.id})">✕</button></div></div>`;
}
function todoRow(t){
  return `<div class="row"><div class="main"><div class="tt"><label style="display:flex;gap:8px;align-items:flex-start;cursor:pointer"><input type="checkbox" onchange="todoDone(${t.id}, this.checked)" style="margin-top:3px"><span>${esc(t.title)}</span></label></div>
      ${t.detail ? `<div class="sub" style="margin-left:24px">${esc(t.detail)}</div>` : ''}
      ${t.kind === 'approved_quote' ? `<div style="margin:6px 0 0 24px;display:flex;gap:6px;flex-wrap:wrap"><a class="btn s p" href="/pumps/api/docs/${t.link.doc_id}/file?version=approved&download=1">⬇ Approved PDF</a><a class="btn s" href="mailto:${esc(t.link.to || '')}?subject=${encodeURIComponent(t.link.subject || 'Approved quote')}&body=${encodeURIComponent('Hi,\n\nThe attached quote is approved - please go ahead and schedule it.\n\nThank you,\nSimon Weardon')}">✉ Email ${esc(t.link.to || '')}</a>${t.link.case_id ? `<button class="btn s" onclick="openCase(${t.link.case_id})">Open job</button>` : ''}</div>` : ''}
      ${t.kind !== 'approved_quote' && (t.link.uri || t.link.case_id) ? `<div style="margin:6px 0 0 24px;display:flex;gap:6px;flex-wrap:wrap">${(t.link.uris || []).length > 1 ? t.link.uris.map(u => `<a class="btn s" href="${esc(u.uri)}" target="_blank" rel="noopener">Open ${esc(u.label)} ↗</a>`).join('') + `<button class="btn s" onclick='openAll(${JSON.stringify(t.link.uris.map(u => u.uri)).replace(/'/g, "&#39;")})'>Open both ↗</button>` : t.link.uri ? `<a class="btn s" href="${esc(t.link.uri)}" target="_blank" rel="noopener">Open in Jobber ↗</a>` : ''}${t.link.case_id ? `<button class="btn s" onclick="openCase(${t.link.case_id})">Open job</button>` : ''}${t.link.scada_id ? `<button class="btn s" onclick="showTab('scada')">SCADA</button>` : ''}</div>` : ''}
      ${t.kind === 'diver_email' ? `<div style="margin:6px 0 0 24px;display:flex;gap:6px;flex-wrap:wrap"><button class="btn s p" onclick="diverTodo('${esc(t.link.month || '')}')">Email ready - copy &amp; attach</button><a class="btn s" href="/pumps/api/dives/docx?month=${encodeURIComponent(t.link.month || '')}">⬇ Word list</a></div>` : ''}</div>
      ${t.kind === 'manual' ? `<button class="btn s" title="Delete from my to do list" onclick="todoDelete(${t.id})">✕</button>` : `<button class="btn s" title="Delete from my to do list" onclick="todoHide('${esc(t.todo_key)}')">✕</button>`}</div>`;
}
// ── undo ──────────────────────────────────────────────
async function showUndo(){
  const j = await api('/undo'); if (!j.success) { toast(j.error, true); return; }
  const rows = j.actions.map(a => `<div style="display:flex;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line,#ddd)"><div style="flex:1"><b>${esc(a.label)}</b><div class="note">${esc(a.created_at.slice(5,16))} · ${esc(a.actor || '')}${a.external ? ' · ' + esc(a.external) : ''}</div></div><button class="btn s" onclick="undoAction(${a.id})">Undo</button></div>`).join('');
  openModal('Undo a recent change', rows ? `<p class="note">Changes from the last 24 hours, newest first. Undo puts the app back as it was before that click.</p>${rows}` : '<div class="empty">Nothing to undo from the last 24 hours.</div>');
}
async function undoAction(id){
  const j = await api('/undo/' + id, {method:'POST', body:{}});
  if (!j.success) { toast(j.error, true); return; }
  toast('Undone: ' + j.label + (j.outside ? ' - ' + j.outside : ''));
  loadToday(); showTab(curTab); showUndo();
}
function openAll(uris){ const blocked = uris.filter(u => { const w = window.open(u, '_blank'); if (w) w.opener = null; return !w; }).length; if (blocked) toast('Your browser blocked a tab - allow pop-ups for this site, or use the buttons one at a time.', true); }
async function todoDone(id, done){ const j = await api('/todos/' + id + '/done', {method:'POST', body:{done}}); if (!j.success) toast(j.error, true); else { toast(done ? 'Done' : 'Reopened'); loadToday(); } }
async function todoAdd(){ const el = document.getElementById('todoNew'); const t = el.value.trim(); if (!t) return; const j = await api('/todos', {method:'POST', body:{title: t}}); if (!j.success) toast(j.error, true); else loadToday(); }
async function todoDelete(id){ if (!confirm('Are you sure you want to delete this from your to do list?')) return; const j = await api('/todos/' + id + '/delete', {method:'POST', body:{}}); if (j.success) loadToday(); }
async function diverTodo(month){
  const j = await api('/dives/preview?month=' + encodeURIComponent(month));
  if (!j.success) { toast(j.error, true); return; }
  openModal('Email to the diver - ready to send', `
    <div class="note">1. <a href="/pumps/api/dives/docx?month=${encodeURIComponent(month)}"><b>Download the Word list</b></a> · 2. <a href="#" onclick="event.preventDefault();copyDiveEmail()"><b>Copy the email</b></a> · 3. Paste it into a new email in Outlook, attach the list and send it · 4. Tick the to-do.</div>
    <div class="note">To <b>${esc(j.to)}</b> · cc ${esc(j.cc)} · subject <b>${esc(j.subject)}</b> <a href="#" onclick="event.preventDefault();navigator.clipboard.writeText(${JSON.stringify(j.subject).replace(/"/g, '&quot;')});toast('Subject copied')">copy</a> · ${j.sites} sites</div>
    <div id="diveMail" style="border:1px solid var(--border);border-radius:8px;padding:12px;max-height:55vh;overflow:auto;background:#fff;color:#111">${j.html}</div>`,
    `<button class="btn" onclick="closeModal()">Close</button><button class="btn p" onclick="copyDiveEmail()">Copy email</button>`);
}
async function copyDiveEmail(){
  const el = document.getElementById('diveMail'); if (!el) return;
  try { await navigator.clipboard.write([new ClipboardItem({'text/html': new Blob([el.innerHTML], {type:'text/html'}), 'text/plain': new Blob([el.innerText], {type:'text/plain'})})]); }
  catch (e) { const r = document.createRange(); r.selectNodeContents(el); const s = getSelection(); s.removeAllRanges(); s.addRange(r); document.execCommand('copy'); s.removeAllRanges(); }
  toast('Email copied - paste it into Outlook');
}
// ── reports ───────────────────────────────────────────
async function loadReports(){
  const y = document.getElementById('repYear').value, q = document.getElementById('repSearch').value.trim();
  const j = await api('/reports?' + (y ? 'year=' + y + '&' : '') + 'q=' + encodeURIComponent(q));
  if (!j.success) { document.getElementById('repBody').innerHTML = `<div class="empty">${esc(j.error)}</div>`; return; }
  document.getElementById('repYear').innerHTML = j.years.map(x => `<option ${x === j.year ? 'selected' : ''}>${esc(x)}</option>`).join('');
  document.getElementById('repInfo').textContent = `${j.reports.length} reports in ${j.year}`;
  const byMonth = {};
  j.reports.forEach(r => { const m = (r.date || '').slice(0, 7) || 'undated'; (byMonth[m] = byMonth[m] || []).push(r); });
  document.getElementById('repBody').innerHTML = Object.keys(byMonth).sort().reverse().map(m => {
    const label = m === 'undated' ? 'No date' : new Date(m + '-15T12:00:00').toLocaleString('en-US', {month:'long', year:'numeric'});
    return `<h3 style="margin:14px 0 6px;font-size:14px">${esc(label)} <span class="note">(${byMonth[m].length})</span></h3>
      <div class="scroll"><table class="t"><thead><tr><th>Date</th><th>Site</th><th>Pump / location</th><th>Report</th><th>Jobber</th><th></th></tr></thead><tbody>
      ${byMonth[m].map(r => `<tr><td>${esc(r.date)}</td><td><b>${esc(r.site)}</b></td><td>${esc(r.location)}</td><td class="note">${esc(r.title)}</td>
        <td>${r.jobber.logged ? '<span class="chip g">' + esc(r.jobber.title || 'logged') + '</span>' : (r.jobber.pending ? '<span class="chip a" title="' + esc(r.jobber.pending) + '">needs a job</span>' : '<span class="note">not yet</span>')}</td>
        <td style="white-space:nowrap">${r.has_branded ? `<a class="btn s" target="_blank" href="/pumps/api/docs/${r.id}/file?version=branded_pdf">PDF</a> <a class="btn s" href="/pumps/api/docs/${r.id}/file?version=branded&download=1">Word</a>` : ''} <button class="btn s" onclick="openDoc(${r.id})">Details</button>${!r.jobber.logged ? ` <button class="btn s" onclick="logReport(${r.id})">Log in Jobber</button>` : ''}</td></tr>`).join('')}
      </tbody></table></div>`; }).join('') || '<div class="empty">No reports this year.</div>';
}
function box(title, items, render, cls, hint){
  return `<div class="box ${cls||''}"><h3>${title}<span class="c">${items.length}</span></h3>${hint ? `<div class="note" style="padding:6px 14px 0">${hint}</div>` : ''}
    ${items.length ? items.map(render).join('') : '<div class="empty">Nothing waiting.</div>'}</div>`;
}
// One to-do list, always on the left: what needs doing, most urgent first;
// what is waiting on someone else folded underneath.
function todoItem(tag, cls, title, sub, open, buttons, key){
  if (key) buttons = (buttons || '') + `<button class="btn s" title="Delete from my to do list" onclick="todoHide('${esc(key)}')">✕</button>`;
  return `<div class="row" onclick="${open}"><div class="main"><div class="tt"><span class="chip ${cls}">${tag}</span> ${title}</div>${sub ? `<div class="sub">${sub}</div>` : ''}${buttons ? `<div class="act" onclick="event.stopPropagation()">${buttons}</div>` : ''}</div></div>`;
}
// The ✕ on a to-do row: off the list only - the job itself is left as it is.
async function todoHide(key){
  if (!confirm('Are you sure you want to delete this from your to do list?\n\n(The job itself is not changed - Undo brings it back.)')) return;
  const j = await api('/todos/hide', {method:'POST', body:{key}});
  if (!j.success) { toast(j.error, true); return; }
  toast('Deleted from your to do list'); loadToday();
}
// Who to follow up with: the account's contact, else the client's AP/billing email in Jobber.
function followUp(f){
  if (!f) return '';
  const who = [f.name ? '<b>' + esc(f.name) + '</b>' : '', f.email ? f.email.split(', ').map(e => `<a href="mailto:${esc(e)}" onclick="event.stopPropagation()">${esc(e)}</a>`).join(', ') + (f.email_from === 'jobber_ap' ? ' <span class="note">(AP in Jobber)</span>' : f.source === 'jobber' ? ' <span class="note">(Jobber)</span>' : '') : '', f.phone ? esc(f.phone) : ''].filter(Boolean).join(' · ');
  return '<br>→ Follow up with ' + (who || '<b class="warn">no contact on file - add one on the Accounts tab or in Jobber</b>');
}
// Where chasing the vendor stands: what they said, by when, and when to check back.
function todayIso(){ const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }
function niceDay(iso){ return iso ? new Date(iso + 'T12:00:00').toLocaleDateString('en-US', {weekday:'short', month:'short', day:'numeric'}) : ''; }
function chaseLine(c){
  const ch = c.chase; if (!ch) return '';
  const late = ch.expect_by && ch.expect_by < todayIso();
  return `<br>📞 ${ch.state === 'follow_up' ? `<b class="${late ? 'bad' : 'warn'}">Follow up</b> - ` : ''}${esc(ch.reason.replace(/(\d{4}-\d{2}-\d{2})/g, d => niceDay(d)))}`
    + (ch.said ? ` · <i>"${esc(ch.said)}"</i>` : '') + (ch.state === 'follow_up' ? '' : ` · <span class="ok">no follow-up needed until ${esc(niceDay(ch.check_on))}</span>`);
}
function caseTitle(c){ return esc(c.title || c.client_name || 'Item ' + c.id); }
function caseSub(c, extra){ return esc([c.client_name, c.site].filter(Boolean).join(' · ')) + (c.po_number ? ' · PO ' + esc(c.po_number) : '') + jobberNo(c) + (extra ? ' · ' + extra : '') + (c.idle_days >= 7 ? ` · <b class="warn">${c.idle_days}d idle</b>` : ''); }
async function loadToday(){
  const j = await api('/summary');
  checkVersion(j.version);
  const el = document.getElementById('todoList');
  if (!j.success) { el.innerHTML = `<div class="empty">${esc(j.error)}</div>`; return; }
  const q = j.queue;
  setCount('n-jobs', q.open_count, false);
  setCount('n-scada', q.scada_attention.length, q.scada_attention.some(s => s.state === 'overdue'));
  updateScanInfo(j.scan);
  const open = c => `openCase(${c.id})`;
  const doDone = c => `<button class="btn s" onclick="caseDone(${c.id})">✓ Done</button>`;
  const urgent = [], todo = [], waiting = [];
  q.issues.forEach(i => (i.kind === 'no_quote' ? waiting : urgent).push(todoItem(i.kind === 'no_quote' ? 'Quote after bill' : 'Fix', i.kind === 'no_quote' ? '' : 'r', esc(i.title || i.client_name || 'Item ' + i.case_id), esc(i.message), `openCase(${i.case_id})`,
    (i.kind === 'no_quote' ? `<button class="btn s p" onclick="billAnyway(${i.id})">Bill it +30%</button>` : '') + `<button class="btn s" onclick="resolveIssue(${i.id})">Resolved</button>`, i.todo_key)));
  q.vendor_bills_to_pay.forEach(c => urgent.push(todoItem('Pay ' + esc(c.vendor || 'Wettech'), 'r', caseTitle(c), `${esc(c.vendor || 'Wettech')} bill ${c.vendor_bill_number ? '#' + esc(c.vendor_bill_number) + ' · ' : ''}${money(c.vendor_bill_total ?? c.vendor_bill_amount)} · the client paid our invoice${c.sei_invoice_number ? ' #' + esc(c.sei_invoice_number) : ''}${(c.pay_email || {}).sent ? `<br><b class="ok">✓ Emailed Christian ${esc(c.pay_email.at.slice(0, 16))}</b>` : (c.pay_email || {}).error ? `<br><b class="bad">Email not sent: ${esc(c.pay_email.error)}</b>` : ''}`, open(c),
    `<button class="btn s p" onclick="sendPayEmail(${c.id}, this)">✉ ${(c.pay_email || {}).sent ? 'Send again' : 'Send email'}</button><button class="btn s" onclick="payEmail(${c.id})">Preview</button><button class="btn s" onclick="markVendorPaid(${c.id})">Mark paid</button>`, c.todo_key)));
  q.scada_attention.filter(s => s.state === 'overdue').forEach(s => urgent.push(todoItem('SCADA overdue', 'r', esc(s.client_name) + (s.site ? ' · ' + esc(s.site) : ''), 'Renewal overdue since ' + esc(s.next_due_on) + (s.state_note ? ' · ' + esc(s.state_note) : '') + followUp(s.follow_up), "showTab('scada')", '', s.todo_key)));
  q.bills_to_draft.forEach(d => { const ip = (d.jobber || {}).invoice_pending || {}; todo.push(todoItem('Draft invoice', 'a', esc(d.client_name || d.file_name), `${esc(d.vendor)} bill #${esc(d.doc_number)} · ${money(d.total)}${ip.reason ? ' · <b class="warn">' + esc(ip.reason) + '</b>' : ''}`, `openCase(${d.case_id})`,
    `<button class="btn s p" onclick="draftInvoice(${d.id})">Draft invoice</button>${(ip.possible_duplicate || {}).uri ? `<a class="btn s" target="_blank" rel="noopener" href="${esc(ip.possible_duplicate.uri)}">Open #${esc(ip.possible_duplicate.number)} ↗</a>` : ''}`, d.todo_key)); });
  q.quotes_to_draft.forEach(d => todo.push(todoItem('Draft quote', 'a', esc(d.client_name || d.file_name), `${esc(d.vendor)} quote ${d.doc_number ? '#' + esc(d.doc_number) + ' ' : ''}· ${money(d.subtotal ?? d.total)}${((d.jobber || {}).quote_pending || {}).reason ? ' · <b class="warn">' + esc(d.jobber.quote_pending.reason) + '</b>' : ''}`, `openCase(${d.case_id})`,
    `<button class="btn s p" onclick="draftQuote(${d.id})">Draft quote</button>${(((d.jobber || {}).quote_pending || {}).possible_duplicate || {}).number ? `<button class="btn s" onclick="linkQuoteNumber(${d.case_id}, '${esc(d.jobber.quote_pending.possible_duplicate.number)}')">Link #${esc(d.jobber.quote_pending.possible_duplicate.number)}</button>` : ''}`, d.todo_key)));
  q.to_quote_client.forEach(c => todo.push(todoItem('Send quote', 'a', caseTitle(c), caseSub(c, 'send our quote to the client in Jobber - this goes away by itself once Jobber shows it sent') + followUp(c.follow_up), open(c), doDone(c), c.todo_key)));
  q.needs_scheduling.forEach(c => todo.push(todoItem('Schedule', 'a', caseTitle(c), caseSub(c, 'client approved - get it on ' + esc(c.vendor || 'Wettech') + "'s calendar" + (c.scheduled_for ? ' · for ' + esc(c.scheduled_for) : '')) + chaseLine(c), open(c),
    c.chase ? `<button class="btn s p" onclick="event.stopPropagation();logFollow(${c.id})">📞 Log follow-up</button>` : '', c.todo_key)));
  // Chase the vendor: jobs to get scheduled / done, and quotes, where nobody has heard back.
  (q.vendor_follow_ups || []).forEach(c => { const ch = c.chase, late = ch.expect_by && ch.expect_by < todayIso();
    todo.push(todoItem('Follow up · ' + (ch.phase === 'job' ? 'job' : 'quote'), late ? 'r' : 'a', caseTitle(c), caseSub(c, esc(stageText(c))) + chaseLine(c),
      open(c), `<button class="btn s p" onclick="event.stopPropagation();logFollow(${c.id})">📞 Log follow-up</button><button class="btn s" onclick="event.stopPropagation();vendorEmail(${c.id})">✉ Email</button>`, c.todo_key)); });
  q.ready_to_close.forEach(c => todo.push(todoItem('Send invoice', 'a', caseTitle(c), caseSub(c, 'send the invoice from Jobber' + (c.sei_invoice_number ? ' · #' + esc(c.sei_invoice_number) : '')) + followUp(c.follow_up), open(c), doDone(c), c.todo_key)));
  q.reports_to_log.forEach(d => todo.push(todoItem('Log report', 'b', esc(d.client_name || d.file_name), `${esc((d.report_fields||{}).title || 'Report')} · ${esc(d.doc_date)}`, d.case_id ? `openCase(${d.case_id})` : `openDoc(${d.id})`,
    `<button class="btn s" onclick="logReport(${d.id})">Log in Jobber</button>`, d.todo_key)));
  q.review_docs.forEach(d => todo.push(todoItem('Look at', 'b', esc(d.client_name || d.file_name), esc(d.review_reason || 'Not filed yet') + ' · ' + esc(d.kind || 'document'), `openDoc(${d.id})`, '', d.todo_key)));
  q.scada_attention.filter(s => s.state !== 'overdue').forEach(s => todo.push(todoItem('SCADA due', 'v', esc(s.client_name) + (s.site ? ' · ' + esc(s.site) : ''), 'Renewal due ' + esc(s.next_due_on) + (s.state_note ? ' · ' + esc(s.state_note) : '') + followUp(s.follow_up), "showTab('scada')", '', s.todo_key)));
  const v = c => esc(c.vendor || 'Wettech');
  const logBtn = c => c.chase ? `<button class="btn s" onclick="event.stopPropagation();logFollow(${c.id})">📞 Log</button>` : '';
  (q.waiting_assessment || []).forEach(c => waiting.push(todoItem(v(c) + ' visit', '', caseTitle(c), caseSub(c, ((c.steps || {}).assessment || {}).due ? 'visit ' + esc(c.steps.assessment.due) : 'visit not booked') + chaseLine(c), open(c), logBtn(c), c.todo_key)));
  q.waiting_vendor_quote.forEach(c => waiting.push(todoItem(v(c) + ' quote', '', caseTitle(c), caseSub(c) + chaseLine(c), open(c), logBtn(c), c.todo_key)));
  (q.scheduling_asked || []).forEach(c => waiting.push(todoItem('Schedule', '', caseTitle(c), caseSub(c, 'client approved - asked ' + v(c) + ' for a date') + chaseLine(c), open(c), logBtn(c), c.todo_key)));
  q.waiting_approval.forEach(c => waiting.push(todoItem('Client approval', '', caseTitle(c), caseSub(c) + followUp(c.follow_up), open(c), '', c.todo_key)));
  q.waiting_work.forEach(c => waiting.push(todoItem('Work', '', caseTitle(c), caseSub(c, c.scheduled_for ? 'scheduled ' + esc(c.scheduled_for) : '') + chaseLine(c), open(c), logBtn(c), c.todo_key)));
  (q.waiting_visits || []).forEach(t => { const l = t.link || {}, left = (l.vendors || []).filter(x => !(l.reported || []).includes(x));
    waiting.push(todoItem('Maintenance visit', '', esc(l.account || t.title), `client approved ${esc(l.since || '')} · waiting on ${esc(left.join(' and '))}'s service report${left.length > 1 ? 's' : ''}${(l.reported || []).length ? ' · ✓ ' + esc(l.reported.join(', ')) : ''}`, "showTab('accounts')",
      `<button class="btn s" onclick="todoDone(${t.id}, true)">✓ Done</button>`, t.todo_key)); });
  q.waiting_bill.forEach(c => waiting.push(todoItem(v(c) + ' bill', '', caseTitle(c), caseSub(c), open(c), '', c.todo_key)));
  const n = urgent.length + todo.length + q.todos.length;
  document.getElementById('sideCount').textContent = n;
  document.getElementById('sideCount').className = 'chip ' + (urgent.length ? 'r' : n ? 'a' : 'g');
  document.getElementById('sideOpen').textContent = `${q.open_count} open jobs`;
  let wasOpen = false; try { wasOpen = localStorage.getItem('pumpsWaitingOpen') === '1'; } catch (e) {}
  el.innerHTML = (urgent.length ? '<div class="grp">Now</div>' + urgent.join('') : '')
    + '<div class="grp">To do</div>' + (todo.join('') + q.todos.map(todoRow).join('') || '<div class="empty">Nothing to do. 🎉</div>')
    + `<div class="row" style="cursor:default"><input type="text" id="todoNew" placeholder="Add a to-do…" style="flex:1;min-width:0" onkeydown="if(event.key==='Enter')todoAdd()"><button class="btn s" onclick="todoAdd()">Add</button></div>`
    + `<details ${wasOpen ? 'open' : ''} ontoggle="try{localStorage.setItem('pumpsWaitingOpen', this.open ? '1' : '0')}catch(e){}"><summary class="grp"><span class="arr">▸</span> Waiting on others (${waiting.length})</summary>${waiting.join('') || '<div class="empty">Nothing waiting.</div>'}</details>`;
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
    box.innerHTML = `<div class="grp">Search · ${(j.cases||[]).length}</div>` + ((j.cases||[]).slice(0,30).map(c => todoItem(esc(stageText(c)), c.status === 'open' ? 'b' : 'g', caseTitle(c), caseSub(c), `openCase(${c.id})`, '')).join('') || '<div class="empty">No items match.</div>');
  }, 250);
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
function closeDrawer(){ document.getElementById('drawerWrap').classList.add('hide'); curCase = null; history.replaceState(null, '', '#' + curTab); loadToday(); showTab(curTab); }
const MONEY = new Set(['vendor_quote_amount','vendor_quote_total','vendor_bill_amount','vendor_bill_total','amount']);
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
      <div class="when">${done ? esc(s.at) + (s.by ? ' · ' + esc(s.by) : '') : (na ? 'not needed' : (s.due ? 'visit ' + esc(s.due) : ''))}</div>
      <select class="s" onchange="stepMenu('${s.key}', this)" style="padding:2px 4px;font-size:11px"><option value="">⋯</option><option value="date">Done on a date…</option><option value="${na ? 'needed' : 'na'}">${na ? 'Needed after all' : 'Not needed'}</option>${done ? '<option value="undo">Not done</option>' : ''}</select>
    </div>`; }).join('');
  const docs = (c.docs || []).map(d => `<div class="d">${kindChip(d.kind)} <b>${esc(d.file_name)}</b>
      <span class="note">${d.doc_number ? '#' + esc(d.doc_number) + ' · ' : ''}${d.total != null ? money(d.total) : ''} ${esc(d.doc_date)}</span>
      <span style="flex:1"></span>
      <a class="btn s" href="/pumps/api/docs/${d.id}/file" target="_blank">Open</a>
      ${d.has_branded ? `<a class="btn s" target="_blank" href="/pumps/api/docs/${d.id}/file?version=branded_pdf">SE report PDF</a> <a class="btn s" href="/pumps/api/docs/${d.id}/file?version=branded&download=1">⬇ Word</a>` : ''}
      ${d.kind === 'quote' && !(d.jobber||{}).quote_id ? `<button class="btn s p" onclick="draftQuote(${d.id})">Draft quote in Jobber</button>` : ''}
      ${d.kind === 'quote' && (d.jobber||{}).quote_id ? `<a class="chip g" target="_blank" href="${esc(d.jobber.quote_uri||'#')}">Jobber quote #${esc(d.jobber.quote_number)}</a>` : ''}
      ${d.kind === 'bill' && !(d.jobber||{}).invoice_id ? `<button class="btn s p" onclick="draftInvoice(${d.id})">Draft invoice in Jobber</button>` : ''}
      ${d.kind === 'bill' && (d.jobber||{}).invoice_id ? `<a class="chip g" target="_blank" href="${esc(d.jobber.invoice_uri||'#')}">Jobber draft #${esc(d.jobber.invoice_number)}</a>` : ''}
      ${d.kind === 'report' && !(d.jobber||{}).note_id ? `<button class="btn s" onclick="logReport(${d.id})">Log in Jobber</button>` : ''}
      ${d.kind === 'report' && (d.jobber||{}).note_id ? '<span class="chip g">logged in Jobber</span>' : ''}
      ${(d.kind === 'quote' || d.kind === 'bill') ? `<button class="btn s" title="Read the file again with today's reader" onclick="readAgain(${d.id})">↻ Read again</button>` : ''}
      <button class="btn s" onclick="openDoc(${d.id})">Details</button></div>`).join('') || '<div class="note">No documents yet.</div>';
  const issues = (c.issues || []).map(i => `<div class="issue ${i.resolved_at ? 'done' : ''}"><div>${esc(i.message)}${i.resolved_at ? `<div class="note">Resolved by ${esc(i.resolved_by)}: ${esc(i.resolution)}</div>` : ''}</div>${i.resolved_at ? '' : `${i.kind === 'no_quote' ? `<button class="btn s p" onclick="billAnyway(${i.id})">Bill it +30%</button> ` : ''}<button class="btn s" onclick="resolveIssue(${i.id})">Resolve…</button>`}</div>`).join('');
  const f = (k, label, type, w) => `<label class="${w ? 'w' : ''}">${label}${type === 'area' ? `<textarea data-f="${k}">${esc(c[k])}</textarea>` : `<input type="${type || 'text'}" data-f="${k}" value="${esc(MONEY.has(k) || k.endsWith('_amount') ? (c[k] ?? '') : c[k])}">`}</label>`;
  document.getElementById('drawer').innerHTML = `
  <div class="hd"><div><h2>${esc(c.title || c.client_name)}</h2><div class="note">${catChip(c.category)} ${stageChip(c)} ${c.po_number ? 'PO ' + esc(c.po_number) : ''} · opened ${esc(c.opened_on)}</div></div>
    <div style="display:flex;gap:6px;align-items:flex-start"><button class="btn" onclick="closeDrawer()">✕</button></div></div>
  <div class="bd">
    ${c.vendor_pay.state === 'due' ? `<div class="sec"><div class="issue">💸 Our client has paid the Jobber invoice - ${esc(v)}'s bill needs to be paid.<button class="btn s p" onclick="markVendorPaid(${c.id})">Mark ${esc(v)} paid</button></div></div>` : ''}
    ${c.account && c.account.notes ? `<div class="sec"><div class="note" style="background:var(--violet-bg);color:var(--violet);padding:10px 12px;border-radius:10px;white-space:pre-line"><b>📋 ${esc(c.account.name)}</b> (from the account sheet)${c.account.repairs_by ? ' · repairs by <b>' + esc(c.account.repairs_by) + '</b>' : ''}\n${esc(c.account.notes)}</div></div>` : ''}
    ${issues ? `<div class="sec"><h4>Issues</h4><div style="display:flex;flex-direction:column;gap:8px">${issues}</div></div>` : ''}
    <div class="sec"><h4>Next</h4><div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn ${['assessment','vendor_quote','scheduled','vendor_bill'].includes(c.stage) ? 'p' : ''}" onclick="vendorEmail(${c.id})">✉️ ${esc(({assessment: 'Ask ' + v + ' to assess', vendor_quote: 'Ask ' + v + ' for the quote', scheduled: 'Ask ' + v + ' to schedule', vendor_bill: 'Ask ' + v + ' for the invoice'})[c.stage] || 'Email ' + v)}</button>
      ${c.chase ? `<button class="btn ${c.chase.state === 'follow_up' ? 'p' : ''}" onclick="logFollow(${c.id})">📞 Log follow-up</button>` : ''}
      ${c.stage === 'client_quote' ? `<button class="btn" onclick="linkQuote(${c.id})">🔗 Quote's already in Jobber? Link it</button>` : ''}
      ${c.stage === 'vendor_quote' && !((c.steps || {}).assessment && !c.steps.assessment.na) ? `<button class="btn" onclick="needsVisit()">🔍 ${esc(v)} needs to visit first</button>` : ''}
      <button class="btn" onclick="uploadForCase()">⬆ Add document</button>
      <button class="btn" onclick="addNote()">✎ Add note</button>
      ${c.status === 'open' ? `<button class="btn p" onclick="caseDone(${c.id})">✓ Mark done</button><button class="btn danger" onclick="caseRemove(${c.id})">✕ Remove</button>` : `<button class="btn" onclick="caseReopen(${c.id})">↺ Reopen</button>`}
    </div></div>
    ${c.chase ? `<div class="sec"><div class="note" style="padding:10px 12px;border-radius:10px;background:${c.chase.state === 'follow_up' ? 'var(--amber-bg)' : 'var(--violet-bg)'}"><b>${c.chase.phase === 'job' ? 'Job' : 'Quote'} - waiting on ${esc(v)}</b>${chaseLine(c)}${c.chase.last_at ? `<br><span class="note">Last asked ${esc(niceDay(c.chase.last_at))}${c.chase.how ? ' by ' + esc(c.chase.how) : ''}${c.chase.by ? ' · ' + esc(c.chase.by) : ''}</span>` : ''}</div></div>` : ''}
    <div class="sec"><h4>Journey</h4>${journeyHtml(c)}</div>
    <div class="sec"><h4>Checklist</h4><div class="steps">${steps}</div></div>
    <div class="sec"><h4>Quote vs bill</h4><div class="money">
      <div class="m"><div class="k">${esc(v)} quote ${c.vendor_quote_number ? '#' + esc(c.vendor_quote_number) : ''}</div><div class="v">${money(c.vendor_quote_amount ?? c.vendor_quote_total) || '—'}</div>${c.vendor_quote_total != null && c.vendor_quote_amount != null ? `<div class="note">${money(c.vendor_quote_total)} with tax</div>` : ''}</div>
      <div class="m"><div class="k">${esc(v)} bill ${c.vendor_bill_number ? '#' + esc(c.vendor_bill_number) : ''}</div><div class="v">${money(c.vendor_bill_amount ?? c.vendor_bill_total) || '—'}</div>${c.vendor_bill_total != null && c.vendor_bill_amount != null ? `<div class="note">${money(c.vendor_bill_total)} with tax</div>` : ''}</div>
      <div class="m"><div class="k">Our invoice ${c.sei_invoice_number ? '#' + esc(c.sei_invoice_number) : ''}</div><div class="v">${money(c.amount) || '—'}</div>${c.vendor_pay.client_invoice_status ? `<div class="note">${c.vendor_pay.client_invoice_status === 'paid' ? '<b class="ok">Paid by client</b>' : 'Jobber: ' + esc(c.vendor_pay.client_invoice_status.replace(/_/g, ' '))}</div>` : ''}</div>
      <div class="m"><div class="k">${esc(v)} bill paid?</div>${vendorPayHtml(c)}</div>
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
      <label class="w">Jobber ${jl || '<span class="note">nothing linked - Track it from the Jobber tab</span>'} <a href="#" onclick="event.preventDefault();linkQuote(${c.id})">${J.quote ? 'Use a different Jobber quote…' : 'Link a Jobber quote…'}</a></label>
    </div><div style="margin-top:10px"><button class="btn p" onclick="saveCaseFields()">Save details</button></div></div>
  </div>`;
}
// The job's journey: where it is on its steps, and everything that has
// happened to it, oldest first.
const JOURNEY_ICONS = [
  [/^created|opened/, '🆕', 'b'], [/document received/, '📄', 'b'], [/draft quote created|scada quote drafted/, '💬', 'b'],
  [/quote stamped approved|quote made a job/, '✅', 'g'], [/quote status/, '💬', ''], [/draft invoice created|invoiced on matching job/, '🧾', 'b'],
  [/invoice status/, '💵', ''], [/pay vendor/, '💸', 'r'], [/emailed christian/, '✉️', 'g'], [/could not email|not drafted|not logged|not saved/, '⚠️', 'a'],
  [/^issue resolved/, '✔️', 'g'], [/^issue/, '⚠️', 'r'], [/bill matches quote/, '✔️', 'g'], [/^note/, '✎', ''], [/linked/, '🔗', ''],
  [/followed up/, '📞', 'b'], [/service visit|schedule/, '📅', 'b'], [/report/, '📋', 'b'], [/marked done|closed/, '🏁', 'g'], [/reopened/, '↺', 'a'], [/cancelled|removed/, '✕', 'r'],
];
function journeyIcon(action){ const a = (action || '').toLowerCase(); for (const [re, ic, cls] of JOURNEY_ICONS) if (re.test(a)) return [ic, cls]; return ['•', '']; }
function journeyHtml(c){
  const steps = c.step_list.filter(s => !s.na);
  const curIdx = steps.findIndex(s => s.key === c.stage);
  const track = `<div class="track">${steps.map((s, i) => { const st = s.at ? 'done' : (i === curIdx ? 'cur' : '');
    return `<div class="n ${st}" title="${esc(s.label)}${s.at ? ' - ' + esc(s.at) : ''}"><div class="b">${s.at ? '✓' : ''}</div>${esc(s.label)}${s.at ? `<div class="d">${esc(s.at.slice(5))}</div>` : (s.due ? `<div class="d">${esc(s.due.slice(5))}</div>` : '')}</div>`; }).join('')}</div>`;
  const items = [];
  const KIND = {quote: ['Quote', '📝', 'b'], bill: ['Invoice', '🧾', 'a'], report: ['Service report', '📋', 'g']};
  (c.docs || []).filter(d => d.status !== 'dismissed').forEach(d => { const [name, ic, cls] = KIND[d.kind] || ['Document', '📄', ''];
    const J = d.jobber || {};
    items.push({at: d.created_at || (d.doc_date ? d.doc_date + ' 12:00:00' : ''), ic, cls,
      title: `${d.vendor || c.vendor || 'Vendor'} ${name.toLowerCase()}${d.doc_number ? ' #' + d.doc_number : ''}${d.total != null ? ' · ' + money(d.total) : ''}`,
      sub: [d.doc_date ? 'dated ' + d.doc_date : '', d.file_name].filter(Boolean).join(' · '),
      html: `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px"><a class="btn s" target="_blank" href="/pumps/api/docs/${d.id}/file">Open</a>`
        + (d.has_branded ? `<a class="btn s" target="_blank" href="/pumps/api/docs/${d.id}/file?version=branded_pdf">Our report PDF</a>` : '')
        + (J.quote_id ? `<a class="chip g" target="_blank" href="${esc(J.quote_uri || '#')}">our Jobber quote #${esc(J.quote_number)}</a>` : '')
        + (J.invoice_id ? `<a class="chip g" target="_blank" href="${esc(J.invoice_uri || '#')}">our Jobber invoice #${esc(J.invoice_number)}</a>` : '')
        + `<button class="btn s" onclick="openDoc(${d.id})">Details</button></div>`}); });
  (c.events || []).forEach(e => { if (/^(updated|read again|document edited|document received)$/.test(e.action)) return;
    const [ic, cls] = journeyIcon(e.action);
    items.push({at: e.at || '', ic, cls, title: e.action.charAt(0).toUpperCase() + e.action.slice(1), sub: (e.detail ? e.detail + ' · ' : '') + e.actor}); });
  c.step_list.filter(s => s.at && !String(s.by || '').includes('implied')).forEach(s => items.push({at: s.at + ' 23:59:59', ic: '✓', cls: 'g', title: s.label, sub: s.by || '', day: true}));
  if (c.opened_on && !items.some(i => /^Created/.test(i.title))) items.push({at: c.opened_on + ' 00:00:00', ic: '🆕', cls: 'b', title: 'Opened', sub: '', day: true});
  items.sort((a, b) => a.at < b.at ? -1 : a.at > b.at ? 1 : 0);
  let lastDay = '';
  const tl = items.map(i => { const d = i.at.slice(0, 10), t = i.day ? '' : i.at.slice(11, 16);
    const head = d !== lastDay ? `<div class="day">${esc(d ? new Date(d + 'T12:00:00').toLocaleDateString('en-US', {weekday:'short', month:'short', day:'numeric', year:'numeric'}) : 'No date')}</div>` : '';
    lastDay = d;
    return head + `<div class="it"><div class="ic ${i.cls}">${i.ic}</div><div class="tx"><b>${esc(i.title)}</b>${t ? ` <span class="note">${esc(t)}</span>` : ''}${i.sub ? `<div class="m">${esc(i.sub)}</div>` : ''}${i.html || ''}</div></div>`; }).join('');
  return track + `<div class="tl">${tl || '<div class="note">Nothing yet.</div>'}</div>`;
}
function vendorPayHtml(c){
  const p = c.vendor_pay || {};
  if (p.state === 'paid') return `<div class="v ok">Paid</div><div class="note">${esc(p.paid_on)}${p.paid_by ? ' · ' + esc(p.paid_by) : ''} · <a href="#" onclick="event.preventDefault();patchCase({vendor_paid_on: ''})">not paid</a></div>`;
  if (p.state === 'due') return `<div class="v bad">Due now</div><div class="note">The client has paid us. <a href="#" onclick="event.preventDefault();markVendorPaid(${c.id})">Mark paid</a></div>`;
  if (p.state === 'unpaid') return `<div class="v">Not paid</div><div class="note">Due once the client pays our invoice. <a href="#" onclick="event.preventDefault();markVendorPaid(${c.id})">Mark paid</a></div>`;
  return '<div class="v">—</div><div class="note">No bill yet</div>';
}
async function vendorEmail(id){
  const j = await api('/cases/' + id + '/vendor_email');
  if (!j.success) { toast(j.error, true); return; }
  const e = j.email;
  openModal('Email ' + esc(e.vendor), `
    <div class="note">Sent from the PO mailbox, so ${esc(e.vendor)}'s reply comes back to it. Edit anything first.</div>
    <label class="note">To<input type="text" id="vmTo" value="${esc(e.to)}" style="width:100%"></label>
    <label class="note">Subject<input type="text" id="vmSubject" value="${esc(e.subject)}" style="width:100%"></label>
    <textarea id="vmBody" style="width:100%;min-height:240px;font:inherit">${esc(e.body)}</textarea>`,
    `<button class="btn" onclick="closeModal()">Close</button><button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('vmBody').value);toast('Email copied - paste it into Outlook')">Copy email</button><button class="btn p" id="vmSend" onclick="sendVendorEmail(${id})">✉ Send email</button>`);
}
async function sendVendorEmail(id){
  const btn = document.getElementById('vmSend'); btn.disabled = true; btn.textContent = 'Sending…';
  const j = await api('/cases/' + id + '/vendor_email/send', {method:'POST', body:{to: document.getElementById('vmTo').value, subject: document.getElementById('vmSubject').value, body: document.getElementById('vmBody').value}});
  btn.disabled = false; btn.textContent = '✉ Send email';
  if (!j.success) { toast(j.error, true); return; }
  toast('Sent to ' + j.sent.to); closeModal();
  if (curCase && curCase.id === id) openCase(id);
}
async function payEmail(id){
  const j = await api('/cases/' + id + '/pay_email');
  if (!j.success) { toast(j.error, true); return; }
  const e = j.email;
  window._payMail = e;
  openModal('Email Christian to pay the vendor', `
    <div class="note">${e.to ? `<b>Send email</b> sends it from the PO mailbox${e.bill_doc_id ? ' with the vendor\'s invoice attached' : ''} - edit it first if you like. Or copy` : 'Copy'} it into Outlook yourself. Press <b>Mark paid</b> once it's paid.</div>
    <div class="note">To <b>${esc(e.to || 'Christian (no email address saved)')}</b> ${e.to ? `<a href="#" onclick="event.preventDefault();navigator.clipboard.writeText(_payMail.to);toast('Address copied')">copy</a>` : ''} · Subject <b>${esc(e.subject)}</b> <a href="#" onclick="event.preventDefault();navigator.clipboard.writeText(_payMail.subject);toast('Subject copied')">copy</a></div>
    <textarea id="payMailBody" style="width:100%;min-height:220px;font:inherit">${esc(e.body)}</textarea>
    ${e.bill_doc_id ? `<div><a class="btn s" target="_blank" href="/pumps/api/docs/${e.bill_doc_id}/file">⬇ ${esc(e.bill_file || 'Vendor invoice')}</a></div>` : ''}`,
    `<button class="btn" onclick="closeModal()">Close</button>${e.to ? `<a class="btn" href="mailto:${encodeURIComponent(e.to)}?subject=${encodeURIComponent(e.subject)}&body=${encodeURIComponent(e.body)}">Open in email</a>` : ''}<button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('payMailBody').value);toast('Email copied - paste it into Outlook')">Copy email</button>${e.to ? `<button class="btn p" onclick="sendPayEmail(${id}, this)">✉ Send email</button>` : ''}`);
}
async function sendPayEmail(id, btn){
  if (btn) { btn.disabled = true; btn.textContent = 'Sending…'; }
  const edited = document.getElementById('payMailBody');
  const j = await api('/cases/' + id + '/pay_email/send', {method:'POST', body:{body: edited && !document.getElementById('modalWrap').classList.contains('hide') ? edited.value : ''}});
  if (btn) { btn.disabled = false; btn.textContent = '✉ Send email'; }
  if (!j.success) { toast(j.error, true); loadToday(); return; }
  toast('Sent to ' + j.sent.to);
  closeModal(); loadToday();
}
async function markVendorPaid(id){
  const d = prompt('Date Wettech\'s bill was paid (YYYY-MM-DD):', new Date().toISOString().slice(0,10));
  if (!d) return;
  const j = await api('/cases/' + id, {method:'PATCH', body:{vendor_paid_on: d}});
  if (!j.success) { toast(j.error || 'Not saved', true); return; }
  toast('Marked paid.');
  if (curCase && curCase.id === id) { curCase = j.case; renderCase(); } else loadToday();
}
async function patchCase(data){ const j = await api('/cases/' + curCase.id, {method:'PATCH', body:data}); if (j.success) { curCase = j.case; renderCase(); } else toast(j.error || 'Not saved', true); return j; }
async function linkQuoteNumber(id, n){
  const j = await api('/cases/' + id + '/jobber_quote', {method:'POST', body:{number: n}});
  if (!j.success) { toast(j.error, true); return; }
  toast(`Now following Jobber quote #${j.quote.number}`); loadToday();
}
async function linkQuote(id){
  const n = prompt('Jobber quote number this job should follow (e.g. 9136):', '');
  if (!n || !n.trim()) return;
  const j = await api('/cases/' + id + '/jobber_quote', {method:'POST', body:{number: n.trim()}});
  if (!j.success) { toast(j.error, true); return; }
  toast(`Now following Jobber quote #${j.quote.number} (${(j.quote.status || '').replace(/_/g, ' ') || 'status unknown'})`);
  openCase(id); loadToday();
}
// Log a call / text / email with the vendor: what they said and when they'll be out.
function fridayOf(weeksAhead, dow){ const d = new Date(todayIso() + 'T12:00:00'); const mon = new Date(d); mon.setDate(d.getDate() - ((d.getDay() + 6) % 7) + 7 * weeksAhead); mon.setDate(mon.getDate() + dow); return mon.toISOString().slice(0, 10); }
async function logFollow(id){
  const j = await api('/cases/' + id);
  if (!j.success) { toast(j.error, true); return; }
  const c = j.case, ch = c.chase || {}, v = c.vendor || 'Wettech';
  const picks = [['This week', fridayOf(0, 4)], ['Early next week', fridayOf(1, 1)], ['Later next week', fridayOf(1, 4)], ['In 2 weeks', fridayOf(2, 4)]];
  openModal('Follow-up with ' + esc(v) + ' · ' + caseTitle(c), `
    <div class="note">${ch.phase === 'job' ? 'Job' : 'Quote'} · ${esc(stageText(c))}${chaseLine(c)}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <label class="note" style="flex:1">Talked to<input type="text" id="fwWho" value="${esc(ch.contact || '')}" style="width:100%"></label>
      <label class="note">How<select id="fwHow"><option>call</option><option>text</option><option>email</option><option>in person</option></select></label>
    </div>
    <label class="note">What they said<input type="text" id="fwSaid" placeholder="e.g. He'll be out there later next week" style="width:100%"></label>
    <label class="note">They'll be out / have it by <span class="note">(leave blank if they gave no date)</span><input type="date" id="fwBy" value="${esc(ch.expect_by && ch.expect_by >= todayIso() ? ch.expect_by : '')}" style="width:100%"></label>
    <div style="display:flex;gap:6px;flex-wrap:wrap">${picks.map(([t, d]) => `<button class="btn s" onclick="document.getElementById('fwBy').value='${d}'">${t} · ${esc(niceDay(d))}</button>`).join('')}</div>
    <label class="note">Check back on <span class="note">(blank = the weekday after their date, or in a few days if they gave none)</span><input type="date" id="fwCheck" style="width:100%"></label>
    ${c.stage === 'scheduled' ? `<div class="note">A date marks the job scheduled with ${esc(v)}.</div>` : ''}`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="saveFollow(${id})">Save follow-up</button>`);
}
async function saveFollow(id){
  const g = k => document.getElementById(k).value.trim();
  const j = await api('/cases/' + id + '/vendor_follow', {method:'POST', body:{who: g('fwWho'), how: g('fwHow'), said: g('fwSaid'), expect_by: g('fwBy'), check_on: g('fwCheck')}});
  if (!j.success) { toast(j.error, true); return; }
  closeModal();
  const ch = j.case.chase;
  toast(ch && ch.state === 'waiting' ? 'Saved - no follow-up needed until ' + niceDay(ch.check_on) : 'Saved');
  if (curCase && curCase.id === id) { curCase = j.case; renderCase(); } else loadToday();
}
function needsVisit(){ const d = prompt('Date of the visit, if you know it (YYYY-MM-DD) - or leave blank:', ''); if (d === null) return; patchCase({steps: {assessment: null}, assessment_due: d.trim()}); }
function setStep(k, v){ patchCase({steps: {[k]: v === 'today' ? new Date().toISOString().slice(0,10) : v}}); }
function stepMenu(k, sel){
  const v = sel.value; sel.value = '';
  if (v === 'na') setStep(k, 'na'); else if (v === 'needed' || v === 'undo') setStep(k, null);
  else if (v === 'date') { const d = prompt('Date it was done (YYYY-MM-DD):', new Date().toISOString().slice(0,10)); if (d) setStep(k, d); }
}
function saveCaseFields(){
  const data = {};
  document.querySelectorAll('#drawer [data-f]').forEach(el => data[el.dataset.f] = el.value);
  patchCase(data).then(j => { if (j.success) { toast('Saved'); closeDrawer(); } });
}
function addNote(){ const t = prompt('Note for this item:'); if (t) patchCase({note: t}); }
async function caseDone(id){
  const note = prompt('Mark this job done. Note (optional):', '');
  if (note === null) return;
  const j = await api('/cases/' + id + '/done', {method:'POST', body:{note}});
  if (!j.success) { toast(j.error, true); return; }
  toast('Marked done'); closeDrawer();
}
async function caseRemove(id){
  if (!confirm('Remove this job from Pumps? (It is kept in the history - the "All" list on Jobs still shows it.)')) return;
  const j = await api('/cases/' + id + '/delete', {method:'POST', body:{reason:'Removed'}});
  if (!j.success) { toast(j.error, true); return; }
  toast('Removed'); closeDrawer();
}
async function caseReopen(id){ const j = await api('/cases/' + id + '/done', {method:'POST', body:{reopen:true}}); if (j.success) { toast('Reopened'); openCase(id); } else toast(j.error, true); }
async function cancelCase(){ const r = prompt('Why is this item being cancelled?'); if (r === null) return; await api('/cases/' + curCase.id + '/delete', {method:'POST', body:{reason:r}}); closeDrawer(); }
async function billAnyway(id){
  const j = await api('/issues/' + id + '/bill-anyway', {method:'POST', body:{}});
  if (!j.success) { toast(j.error, true); return; }
  closeDrawer(); loadToday();
  if (j.doc_id) draftInvoice(j.doc_id); else toast('Alert cleared');
}
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
  if (caseId) openCase(caseId); else loadToday();
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
     ${!d.case_id && d.extracted_by === 'regex' && d.status !== 'dismissed' ? `<button class="btn" onclick="rereadDoc(${d.id})">Read again with Claude</button>` : ''}
     ${(d.kind === 'quote' || d.kind === 'bill') && d.status !== 'dismissed' ? `<button class="btn" title="Read the file again with today's reader (e.g. two prices read as one)" onclick="readAgain(${d.id})">↻ Read again</button>` : ''}
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
  if (j.case_id) openCase(j.case_id); else loadToday();
}
async function readAgain(id){
  toast('Reading it again…');
  const j = await api('/docs/' + id + '/read_again', {method:'POST', body:{}});
  if (!j.success) { toast(j.error, true); return; }
  closeModal();
  const q = j.auto_quote || j.auto_invoice || {};
  toast(`Read again: ${j.summary}.` + (j.note ? ' ' + j.note : q.quote_number ? ` Draft quote #${q.quote_number} made in Jobber.` : q.invoice_number ? ` Draft invoice #${q.invoice_number} made in Jobber.` : q.pending ? ' ' + q.pending : ''));
  if (j.case_id) openCase(j.case_id); else openDoc(id);
}
async function rereadDoc(id){
  toast('Reading with Claude…');
  const j = await api('/docs/' + id + '/reread', {method:'POST', body:{}});
  if (!j.success) { toast(j.error, true); return; }
  closeModal();
  toast(j.case_id ? `Read and filed as a ${j.kind}.` : `Read as a ${j.kind} - ${j.review}`);
  if (j.case_id) openCase(j.case_id); else openDoc(id);
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
  inv = {mode: 'invoice', doc: d, client_id: null, lines: s.line_items.map(x => Object.assign({}, x)), subject: s.subject, job: s.job || null, bill_lines: s.bill_lines || null};
  if (s.from_quote) setTimeout(() => { const n = document.querySelector('#modal .note'); if (n) n.insertAdjacentHTML('afterbegin', `<b>Lines copied from our Jobber quote #${esc(String(s.from_quote))}</b> - the bill matches ${esc(d.vendor)}'s quote, so the client is invoiced what they were quoted. `); }, 0);
  openModal('Draft invoice in Jobber', `
    <div class="safe">This creates a DRAFT invoice in Jobber. Nothing is sent to the client - review it in Jobber and send it from there.</div>
    ${(d.case_issues || []).map(i => `<div class="issue">⚠️ ${esc(i.message)}</div>`).join('')}
    <div class="note">From ${esc(d.vendor)} bill #${esc(d.doc_number)} - ${money(d.subtotal)} before tax, ${money(d.total)} total. One Service Proposal Amount line: the bill before tax${s.markup_pct ? ' plus ' + s.markup_pct + '%' : ''}; Jobber adds the client's tax.</div>
    <div><b>Jobber client</b><div class="toolbar" style="margin:6px 0"><input type="text" id="cq" value="${esc(d.client_name)}" style="flex:1"><button class="btn" onclick="findClients()">Search</button></div><div id="cands"><div class="note">Searching…</div></div></div>
    ${s.job ? `<div class="safe" id="jobMatch">Matches Jobber job <a href="${esc(s.job.uri)}" target="_blank" rel="noopener"><b>#${esc(s.job.number)} ${esc(s.job.title)}</b> ↗</a> (${esc((s.job.status || '').replace(/_/g, ' '))}, ${money(s.job.total)}) - the invoice goes on that job at its price. <button class="btn s" onclick="dropJobMatch()">Not this job - bill + 30%</button></div>` : ''}
    <div class="note">The client you pick is remembered for "${esc(d.client_name)}", so next time it's filled in by itself.</div>
    <label class="note">Invoice subject<input type="text" id="invSubject" value="${esc(inv.subject)}" style="width:100%"></label>
    <div><b>Line items</b> <span class="note">(edit before creating)</span><table class="t" style="margin-top:6px"><thead><tr><th>Name</th><th>Description</th><th class="num">Qty</th><th class="num">Unit price</th><th>Tax</th><th></th></tr></thead><tbody id="invLines"></tbody></table>
      <button class="btn s" style="margin-top:6px" onclick="inv.lines.push({name:'',description:'',quantity:1,unit_price:0,taxable:true});drawLines()">＋ Line</button>
      <div class="foot"><span id="invTotal"></span></div></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" id="invGo" onclick="createInvoice()">Create draft in Jobber</button>`);
  drawLines(); findClients();
}
function dropJobMatch(){ inv.job = null; inv.dropped = true; if (inv.bill_lines) inv.lines = inv.bill_lines.map(x => Object.assign({}, x)); const el = document.getElementById('jobMatch'); if (el) el.remove(); drawLines(); }
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
function invTotal(){ const t = inv.lines.reduce((a, l) => a + (l.quantity || 0) * (l.unit_price || 0), 0); document.getElementById('invTotal').textContent = 'Before tax: ' + money(t) + (inv.doc.subtotal != null && Math.abs(t - inv.doc.subtotal) > 0.005 ? ` (${inv.mode === 'quote' ? 'vendor quote' : 'bill'}: ${money(inv.doc.subtotal)})` : ''); }
async function findClients(){
  const q = document.getElementById('cq').value.trim();
  const box = document.getElementById('cands');
  if (!q) { box.innerHTML = '<div class="note">Type a client name.</div>'; return; }
  box.innerHTML = '<div class="note">Searching Jobber…</div>';
  const j = await api('/jobber/clients?q=' + encodeURIComponent(q));
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  inv.client_id = j.pick ? j.pick.id : null;
  box.innerHTML = (j.candidates || []).map(c => `<div class="cand ${c.id === inv.client_id ? 'on' : ''}" onclick="pickClient(this, '${esc(c.id)}')"><input type="radio" name="cl" ${c.id === inv.client_id ? 'checked' : ''}>
     <div style="flex:1"><b>${esc(c.name)}</b>${c.is_lead ? ' <span class="chip a">lead</span>' : ''}${c.remembered ? ' <span class="chip g">remembered</span>' : ''}<div class="note">${esc(c.remembered || c.address)}</div></div><span class="chip">${Math.round(c.score * 100)}%</span>
     <a href="${esc(c.uri)}" target="_blank" onclick="event.stopPropagation()" class="note">Jobber ↗</a></div>`).join('') || '<div class="note">No clients found - try a shorter name.</div>';
  if (!j.pick && (j.candidates || []).length) box.insertAdjacentHTML('afterbegin', '<div class="note" style="margin-bottom:6px"><b>Choose the client</b> - more than one could match.</div>');
  if (inv.mode === 'quote') quoteProps();
}
function pickClient(el, id){ inv.client_id = id; document.querySelectorAll('#cands .cand').forEach(c => { c.classList.remove('on'); c.querySelector('input').checked = false; }); el.classList.add('on'); el.querySelector('input').checked = true; if (inv.mode === 'quote') quoteProps(); }
// Jobber already has a quote/invoice for this client at this price.
function confirmDuplicate(j){
  const d = j.possible_duplicate || {};
  return confirm(`Jobber already has ${j.error.includes('invoice #') ? 'invoice' : 'quote'} #${d.number} for this client at ${money(d.total)} (${(d.status || '').replace(/_/g, ' ')}, ${d.created || ''}).\n\nOK = draft a new one anyway.\nCancel = don't - open it in Jobber${j.error.includes('quote #') ? ', or link it to the job with "Use a different Jobber quote…"' : ''}.`);
}
async function createInvoice(){
  if (!inv.client_id) { toast('Choose the Jobber client first.', true); return; }
  const btn = document.getElementById('invGo'); btn.disabled = true; btn.textContent = 'Creating draft…';
  const ibody = {client_id: inv.client_id, client_name: ((document.querySelector('#cands .cand.on b') || {}).textContent || ''), job_id: inv.job ? inv.job.id : (inv.dropped ? '' : null), line_items: inv.lines, subject: document.getElementById('invSubject').value};
  let j = await api('/docs/' + inv.doc.id + '/invoice', {method:'POST', body: ibody});
  if (!j.success && j.possible_duplicate && confirmDuplicate(j)) j = await api('/docs/' + inv.doc.id + '/invoice', {method:'POST', body: {...ibody, force: true}});
  btn.disabled = false; btn.textContent = 'Create draft in Jobber';
  if (!j.success) { if (!j.possible_duplicate) toast(j.error, true); return; }
  closeModal();
  toast(`Draft invoice #${j.invoice.invoice_number} created in Jobber (${j.invoice.invoice_status || 'draft'}). Review and send it from Jobber.`);
  if (inv.doc.case_id) openCase(inv.doc.case_id); else loadToday();
}

// ── draft quote ───────────────────────────────────────
async function draftQuote(docId){
  if (!JOBBER_OK) { toast('Connect Jobber first (top of the page).', true); return; }
  const j = await api('/docs/' + docId);
  if (!j.success) { toast(j.error, true); return; }
  const d = j.doc, s = d.quote_suggestion || {line_items:[], title:''};
  inv = {mode: 'quote', doc: d, client_id: null, property_id: null, lines: s.line_items.map(x => Object.assign({}, x))};
  openModal('Draft quote in Jobber', `
    <div class="safe">This creates a DRAFT quote for the client in Jobber. Nothing is sent to the client - review it in Jobber and send it from there.</div>
    <div class="note">From ${esc(d.vendor)} quote #${esc(d.doc_number)} - ${money(d.subtotal)} before tax, ${money(d.total)} total. The vendor's sales tax line and name are left off: Jobber adds the client's tax to taxable lines.${s.markup_pct ? ' Prices include ' + s.markup_pct + '% markup.' : ''}${d.subtotal == null && d.total != null && s.line_items.length && s.line_items.every(l => !l.taxable) ? " <b>The vendor's price already includes sales tax</b>, so its lines are set not taxable - change that if this client should be taxed on top." : ''}</div>
    <div><b>Jobber client</b><div class="toolbar" style="margin:6px 0"><input type="text" id="cq" value="${esc(d.client_name)}" style="flex:1"><button class="btn" onclick="findClients()">Search</button></div><div id="cands"><div class="note">Searching…</div></div></div>
    <div><b>Property</b><div id="qprops" class="note">Choose the client first.</div></div>
    <div id="qHow" class="note"></div>
    <label class="note" style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="qRemember" checked> Remember: when Wettech writes <input type="text" id="qPlace" value="${esc(d.client_name)}" style="width:140px"> <input type="text" id="qArea" value="${esc(d.site)}" placeholder="area, e.g. back station" style="width:160px"> it means this client and property</label>
    <label class="note">Quote title<input type="text" id="qTitle" value="${esc(s.title)}" style="width:100%"></label>
    <label class="note">Message to the client (optional)<textarea id="qMsg" style="width:100%;min-height:44px"></textarea></label>
    <div><b>Line items</b> <span class="note">(edit before creating)</span><table class="t" style="margin-top:6px"><thead><tr><th>Name</th><th>Description</th><th class="num">Qty</th><th class="num">Unit price</th><th>Tax</th><th></th></tr></thead><tbody id="invLines"></tbody></table>
      <button class="btn s" style="margin-top:6px" onclick="inv.lines.push({name:'',description:'',quantity:1,unit_price:0,taxable:true});drawLines()">＋ Line</button>
      <div class="foot"><span id="invTotal"></span></div></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" id="qGo" onclick="createQuote()">Create draft quote in Jobber</button>`);
  drawLines();
  const t = await api('/docs/' + docId + '/quote_target');
  const tg = (t.success && t.target) || {};
  if (tg.client_id) {
    inv.client_id = tg.client_id; inv.want_property = tg.property_id || null; inv.want_label = tg.property_label || '';
    document.getElementById('cands').innerHTML = `<div class="cand on"><input type="radio" checked><div style="flex:1"><b>${esc(tg.client_name || 'Client from ' + tg.how)}</b><div class="note">found by ${esc(tg.how)} · <a href="#" onclick="event.preventDefault();findClients()">search for another client</a></div></div></div>`;
    document.getElementById('qHow').textContent = tg.property_id ? `Matched by ${tg.how}: ${tg.client_name || ''}${tg.property_label ? ' · ' + tg.property_label : ''}.` : '';
    quoteProps();
  } else findClients();
}
async function quoteProps(){
  const box = document.getElementById('qprops');
  inv.property_id = null;
  if (!inv.client_id) { box.innerHTML = 'Choose the client first.'; return; }
  box.innerHTML = 'Loading properties…';
  const id = inv.client_id;
  const j = await api('/jobber/clients/' + encodeURIComponent(id) + '/jobs');
  if (inv.client_id !== id) return;
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  const props = j.properties || [];
  // The maintenance job's property may be missing from a big client's list.
  if (inv.want_property && inv.want_label && !props.some(p => p.id === inv.want_property)) props.unshift({id: inv.want_property, label: inv.want_label});
  if (props.length === 1) inv.property_id = props[0].id;
  if (inv.want_property && props.some(p => p.id === inv.want_property)) { inv.property_id = inv.want_property; inv.want_property = null; }
  inv.props = props;
  box.innerHTML = props.map(p => `<label class="cand ${inv.property_id === p.id ? 'on' : ''}"><input type="radio" name="qp" ${inv.property_id === p.id ? 'checked' : ''} onchange="inv.property_id='${esc(p.id)}'"><div>${esc(p.label || 'Property')}</div></label>`).join('')
    || '<div class="issue">This client has no property in Jobber - add one in Jobber first.</div>';
}
async function createQuote(){
  if (!inv.client_id) { toast('Choose the Jobber client first.', true); return; }
  if (!inv.property_id) { toast("Choose the client's property first.", true); return; }
  const btn = document.getElementById('qGo'); btn.disabled = true; btn.textContent = 'Creating draft…';
  const cand0 = document.querySelector('#cands .cand.on b'), prop0 = (inv.props || []).find(p => p.id === inv.property_id);
  const body = {client_id: inv.client_id, client_name: cand0 ? cand0.textContent : '', property_id: inv.property_id, property_label: prop0 ? prop0.label : '', line_items: inv.lines, title: document.getElementById('qTitle').value, message: document.getElementById('qMsg').value};
  if (document.getElementById('qRemember').checked && document.getElementById('qPlace').value.trim()) {
    const cand = document.querySelector('#cands .cand.on b'), prop = (inv.props || []).find(p => p.id === inv.property_id);
    body.remember = {place: document.getElementById('qPlace').value.trim(), area: document.getElementById('qArea').value.trim(), client_name: cand ? cand.textContent : '', property_label: prop ? prop.label : ''};
  }
  let j = await api('/docs/' + inv.doc.id + '/quote', {method:'POST', body});
  if (!j.success && j.possible_duplicate && confirmDuplicate(j)) j = await api('/docs/' + inv.doc.id + '/quote', {method:'POST', body: {...body, force: true}});
  btn.disabled = false; btn.textContent = 'Create draft quote in Jobber';
  if (!j.success) { if (!j.possible_duplicate) toast(j.error, true); return; }
  closeModal();
  toast(`Draft quote #${j.quote.quote_number} created in Jobber (${j.quote.quote_status || 'draft'}). Review and send it from Jobber.`);
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
let SC = null;
async function loadScada(){
  const j = await api('/scada');
  if (!j.success) { toast(j.error, true); return; }
  SC = j;
  const show = document.getElementById('scShow').value;
  const lab = {overdue:['r','Overdue'], due_soon:['a','Due soon'], current:['g','Current'], unknown:['','No date'], inactive:['','Stopped']};
  const rows = j.scada.filter(s => show === 'all' || s.state !== 'inactive');
  const yr = j.years;
  const cell = v => !v ? '' : (/^\d{4,6}$/.test(v) ? `<b>${esc(v)}</b>` : `<span class="note">${esc(v)}</span>`);
  document.getElementById('scadaTable').innerHTML = `<thead><tr><th>Status</th><th>Client</th><th>Renewal date</th><th>Product</th><th class="num">Amount</th><th>Our bill</th><th>Vendor</th>${yr.map(y => `<th>${y}</th>`).join('')}<th></th></tr></thead><tbody>` +
    (rows.map(s => `<tr>
      <td><span class="chip ${lab[s.state][0]}">${lab[s.state][1]}</span>${s.complimentary ? ' <span class="chip">complimentary</span>' : ''}${s.days_left != null && s.state !== 'current' && s.state !== 'inactive' ? `<div class="note">${s.days_left < 0 ? -s.days_left + ' days late' : 'in ' + s.days_left + ' days'}</div>` : ''}</td>
      <td><b>${esc(s.client)}</b>${s.notes ? `<div class="note">${esc(s.notes)}</div>` : ''}</td>
      <td style="white-space:nowrap">${esc(s.next_due_on)}</td><td class="note">${esc(s.product)}</td>
      <td class="num">${money(s.vendor_cost)}</td><td>${esc(s.our_bill)}</td><td>${esc(s.vendor)}</td>
      ${yr.map(y => `<td>${cell(s.years[y])}</td>`).join('')}
      <td style="white-space:nowrap">${s.state !== 'inactive' ? `<button class="btn s p" onclick="scadaRenewed(${s.id})">Renewed…</button> ` : ''}${['overdue','due_soon'].includes(s.state) ? `<button class="btn s" onclick="scadaRenew(${s.id})">${s.case_id ? 'Open item' : 'Start item'}</button> ` : ''}<button class="btn s" onclick="scadaEdit(${s.id})">Edit</button></td></tr>`).join('') || `<tr><td colspan="${8 + yr.length}" class="empty">No SCADA clients.</td></tr>`) + '</tbody>';
}
async function scadaRenew(id){ const j = await api('/scada/' + id, {method:'POST', body:{action:'renewal_item'}}); if (j.success) openCase(j.case_id); else toast(j.error, true); }
async function scadaRenewed(id){
  const s = SC.scada.find(x => x.id === id);
  const v = prompt(`${s.client}: renewal due ${s.next_due_on}.\nOur invoice # for it (or a note such as "No charge"):`, '');
  if (!v) return;
  const j = await api('/scada/' + id, {method:'POST', body:{action:'renewed', value: v}});
  if (j.success) { toast('Recorded - next renewal moved on a year.'); loadScada(); } else toast(j.error, true);
}
function scadaEdit(id){
  const s = id ? SC.scada.find(x => x.id === id) : {client:'', renewal_date:'', product:'Annual Scada - Pump Station', vendor_cost:428, our_bill:'$600.00', vendor:'Wettech', years:{}, notes:'', active:1};
  const yr = SC ? SC.years : [];
  openModal(id ? 'SCADA - ' + esc(s.client) : 'Add SCADA client', `<div class="fields">
    <label class="w">Client<input type="text" id="sc_client" value="${esc(s.client)}"></label>
    <label>Renewal date (next due)<input type="date" id="sc_date" value="${esc(s.renewal_date)}"></label>
    <label>Product<input type="text" id="sc_product" value="${esc(s.product)}"></label>
    <label>Amount (Wettech)<input type="number" step="0.01" id="sc_cost" value="${esc(s.vendor_cost ?? '')}"></label>
    <label>Our bill<input type="text" id="sc_bill" value="${esc(s.our_bill)}"></label>
    <label>Vendor<input type="text" id="sc_vendor" value="${esc(s.vendor)}"></label>
    <label class="w">Name in Jobber <span class="note">(client or site on the invoice; separate several with ;)</span><input type="text" id="sc_jn" value="${esc(s.jobber_names || '')}" placeholder="e.g. Cross Creek"></label>
    ${yr.map(y => `<label>${y}<input type="text" class="sc_y" data-y="${y}" value="${esc((s.years || {})[y] || '')}" placeholder="invoice # or note"></label>`).join('')}
    <label class="w">Notes<textarea id="sc_notes">${esc(s.notes)}</textarea></label>
    <label><span><input type="checkbox" id="sc_active" ${s.active ? 'checked' : ''}> Still on SCADA</span></label>
    <label><span><input type="checkbox" id="sc_comp" ${s.complimentary ? 'checked' : ''}> Complimentary (remind me, no client quote)</span></label></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="scadaSave(${id})">Save</button>`);
}
async function scadaSave(id){
  const v = x => document.getElementById(x).value;
  const years = {}; document.querySelectorAll('.sc_y').forEach(el => years[el.dataset.y] = el.value);
  const body = {client: v('sc_client'), renewal_date: v('sc_date'), product: v('sc_product'), vendor_cost: v('sc_cost'), our_bill: v('sc_bill'), vendor: v('sc_vendor'), notes: v('sc_notes'), jobber_names: v('sc_jn'), active: document.getElementById('sc_active').checked, complimentary: document.getElementById('sc_comp').checked, years};
  const j = id ? await api('/scada/' + id, {method:'PATCH', body}) : await api('/scada', {method:'POST', body});
  if (!j.success) { toast(j.error, true); return; }
  if (!id) { const n = j.scada.find(x => x.client === body.client.trim()); if (n) await api('/scada/' + n.id, {method:'PATCH', body:{years, active: body.active, jobber_names: body.jobber_names}}); }
  closeModal(); loadScada();
}
// ── maintenance accounts ──────────────────────────────
let MT = null;
const MSHORT = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function schedText(a){ if (a.monthly) return 'Monthly'; const m = (a.months || '').split(',').filter(Boolean).map(Number); return m.length === 12 ? 'Monthly' : m.map(x => MSHORT[x - 1]).join(', ') || '—'; }
async function loadMaint(){ const j = await api('/maint'); if (!j.success) { toast(j.error, true); return; } MT = j; drawMaint(); }
function drawMaint(){
  if (!document.getElementById('mtBody')) { refreshAccounts(); return; }
  if (!MT) return;
  const show = document.getElementById('mtShow').value, q = document.getElementById('mtSearch').value.trim().toLowerCase();
  const rows = MT.accounts.filter(a => (show === 'active' ? a.active : show === 'former' ? !a.active : show === 'due' ? a.due_this_month : true) && (!q || (a.name + ' ' + a.address).toLowerCase().includes(q)));
  const act = MT.accounts.filter(a => a.active);
  document.getElementById('mtInfo').innerHTML = `${act.length} active accounts · <b>${act.filter(a => a.due_this_month).length} due in ${MSHORT[MT.month - 1]}</b> · ${MT.accounts.length - act.length} former`;
  document.getElementById('mtBody').innerHTML = rows.map(a => `<tr>
    <td><b>${esc(a.name)}</b>${a.repairs_by ? ` <span class="chip v">repairs: ${esc(a.repairs_by)}</span>` : ''}${a.follow_up ? `<div class="note">🔔 Before each service: ${esc(a.follow_up)}</div>` : ''}${a.notes ? `<div class="note">${esc(a.notes)}</div>` : ''}${!a.active ? ' <span class="chip">former</span>' : ''}</td>
    <td>${esc(a.kind)}</td><td class="note">${esc(a.equipment)}</td><td class="note">${esc(a.address)}</td>
    <td style="white-space:nowrap">${a.due_this_month ? '<b>' + esc(schedText(a)) + '</b> <span class="chip b">due now</span>' : esc(schedText(a))}</td>
    <td class="num">${esc(a.vendor_cost)}</td><td class="num">${esc(a.naples_electric)}</td><td>${esc(a.our_bill)}</td><td class="note">${esc(a.joined)}</td>
    <td><button class="btn s" onclick="maintEdit(${a.id})">Edit</button></td></tr>`).join('') || '<tr><td colspan="10" class="empty">None.</td></tr>';
}
function maintEdit(id){
  const a = id ? MT.accounts.find(x => x.id === id) : {name:'', kind:'Pump', joined:'', equipment:'', address:'', months:'1,4,7,10', monthly:0, vendor_cost:'', naples_electric:'', our_bill:'', notes:'', repairs_by:'', follow_up:'', active:1};
  const months = (a.months || '').split(',').filter(Boolean).map(Number);
  openModal(id ? 'Account - ' + esc(a.name) : 'Add maintenance account', `<div class="fields">
    <label class="w">Account<input type="text" id="mt_name" value="${esc(a.name)}"></label>
    <label>Type<select id="mt_kind">${['Pump','Pumps','Both','Fountain','Lake'].map(k => `<option ${k === a.kind ? 'selected' : ''}>${k}</option>`).join('')}</select></label>
    <label>Date joined<input type="text" id="mt_joined" value="${esc(a.joined)}" placeholder="YYYY-MM-DD"></label>
    <label class="w">Size &amp; make<input type="text" id="mt_equipment" value="${esc(a.equipment)}"></label>
    <label class="w">Location of pump<textarea id="mt_address">${esc(a.address)}</textarea></label>
    <label>Wettech / visit<input type="text" id="mt_vendor_cost" value="${esc(a.vendor_cost)}"></label>
    <label>Naples Electric<input type="text" id="mt_naples_electric" value="${esc(a.naples_electric)}"></label>
    <label>Our bill (Stahlman invoice)<input type="text" id="mt_our_bill" value="${esc(a.our_bill)}"></label>
    <label><span><input type="checkbox" id="mt_monthly" ${a.monthly ? 'checked' : ''}> Monthly</span></label>
    <div class="w"><b class="note">Months</b><div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px">${MSHORT.map((m, i) => `<label style="display:flex;gap:3px;align-items:center"><input type="checkbox" class="mt_m" value="${i + 1}" ${months.includes(i + 1) ? 'checked' : ''}>${m}</label>`).join('')}</div></div>
    <label class="w">Repairs by<select id="mt_repairs_by">${[['', 'Wettech (Tommy)'], ['SiteOne', 'SiteOne'], ['Naples Electric', 'Naples Electric'], ['Oscar (our technician)', 'Oscar (our technician) - no Wettech quote or bill']].map(([v, l]) => `<option value="${esc(v)}" ${v === (a.repairs_by || '') ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select><span class="note">New repair jobs for this account go to them.</span></label>
    <label class="w">Before each service, follow up with…<textarea id="mt_follow_up" placeholder="e.g. Email Lauren to approve the visit">${esc(a.follow_up || '')}</textarea><span class="note">Shows in the to-do list about a week before each service month.</span></label>
    <label class="w">Notes<textarea id="mt_notes">${esc(a.notes)}</textarea></label>
    <label><span><input type="checkbox" id="mt_active" ${a.active ? 'checked' : ''}> Active account</span></label></div>`,
    `${id ? `<button class="btn danger" onclick="maintDelete(${id})">Remove</button>` : ''}<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="maintSave(${id})">Save</button>`);
}
async function maintSave(id){
  const v = k => document.getElementById('mt_' + k).value;
  const body = {name: v('name'), kind: v('kind'), joined: v('joined'), equipment: v('equipment'), address: v('address'), vendor_cost: v('vendor_cost'), naples_electric: v('naples_electric'), our_bill: v('our_bill'), notes: v('notes'), repairs_by: v('repairs_by'), follow_up: v('follow_up'), monthly: document.getElementById('mt_monthly').checked, active: document.getElementById('mt_active').checked, months: [...document.querySelectorAll('.mt_m:checked')].map(x => x.value).join(',')};
  if (id) body.id = id;
  const j = await api('/maint', {method:'POST', body});
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); MT.accounts = j.accounts; drawMaint();
}
async function maintDelete(id){ if (!confirm('Remove this account? (Untick "Active" instead to keep it as a former account.)')) return; const j = await api('/maint/' + id + '/delete', {method:'POST', body:{}}); if (j.success) { closeModal(); MT.accounts = j.accounts; drawMaint(); } }
async function scadaAdd(){ const v = x => document.getElementById(x).value; const j = await api('/scada', {method:'POST', body:{client_name:v('sa_client'), site:v('sa_site'), last_renewed_on:v('sa_last'), annual_amount:v('sa_amt')}}); if (j.success) { closeModal(); loadScada(); } else toast(j.error, true); }

// ── Jobber ────────────────────────────────────────────
// ── accounts ──────────────────────────────────────
let AC = null;
async function loadAccounts(){ await refreshAccounts(); loadDivers(); loadSiteNames(); }
async function refreshAccounts(){
  const [a, m] = await Promise.all([api('/accounts'), api('/maint')]);
  if (!a.success) { document.getElementById('acBody').innerHTML = `<tr><td colspan="5" class="empty">${esc(a.error)}</td></tr>`; return; }
  AC = a; if (m.success) MT = m; drawAccounts();
}
function lakeSched(l){ return l.months ? (l.months === '1,4,7,10' ? 'Jan, Apr, Jul, Oct' : l.months.split(',').map(m => MSHORT[m - 1]).join(', ')) : 'Every month'; }
function drawAccounts(){
  if (!AC) return;
  const show = document.getElementById('acShow').value, q = document.getElementById('acSearch').value.trim().toLowerCase();
  const due = a => (a.pump && a.pump.due_this_month) || (a.lake && a.lake.due_this_month && a.lake.needs_dive);
  const ok = a => !show ? true : show === 'active' ? a.active : show === 'former' ? !a.active : show === 'due' ? a.active && due(a) :
    show === 'pump' ? a.pump && a.pump.active : show === 'lake' ? a.lake && a.lake.active !== 0 : show === 'scada' ? a.scada && a.scada.active : true;
  const rows = AC.accounts.filter(a => ok(a) && (!q || JSON.stringify([a.name, a.pump && a.pump.address, a.lake && a.lake.address]).toLowerCase().includes(q)));
  const act = AC.accounts.filter(a => a.active);
  document.getElementById('acInfo').innerHTML = `${act.length} active accounts · ${act.filter(a => a.pump && a.pump.active).length} pump · ${act.filter(a => a.lake && a.lake.active !== 0).length} lake · <b>${act.filter(due).length} due in ${esc(AC.month)}</b>`;
  const st = {overdue:'r', due_soon:'a', current:'g', inactive:'', unknown:''};
  document.getElementById('acBody').innerHTML = rows.map(a => { const p = a.pump, l = a.lake, s = a.scada;
    const vis = a.visit;
    return `<tr><td><b>${esc(a.name)}</b>${!a.active ? ' <span class="chip">former</span>' : ''}${a.active ? (vis
      ? `<div class="note">✓ Client approved ${esc((vis.link || {}).since || '')} · waiting on ${esc(((vis.link || {}).vendors || []).filter(x => !((vis.link || {}).reported || []).includes(x)).join(' and '))}</div>`
      : '') + `<div><button class="btn s ${vis ? '' : 'p'}" onclick="accountReady(${JSON.stringify(a.name).replace(/"/g, '&quot;')})">✓ Ready - client approved</button></div>` : ''}</td>
    <td>${p ? `${esc(p.equipment || p.kind)}<div class="note">${p.due_this_month ? '<b>' + esc(schedText(p)) + '</b> <span class="chip b">due</span>' : esc(schedText(p))} · Wettech ${esc(p.vendor_cost || '—')} · we bill ${esc(p.our_bill || '—')}${!p.active ? ' · former' : ''}</div><button class="btn s" onclick="maintEdit(${p.id})">Edit</button>` : '<span class="note">—</span>'}</td>
    <td>${l ? `${esc(l.equipment || l.kind || '')} ${l.needs_dive ? '<span class="chip b">diver</span>' : '<span class="note">no diving</span>'}<div class="note">${l.due_this_month && l.needs_dive ? '<b>' + esc(lakeSched(l)) + '</b> <span class="chip b">due</span>' : esc(lakeSched(l))} · Gulfshore ${esc(l.diver_cost || '—')} · we bill ${esc(l.our_bill || '—')}${l.active === 0 ? ' · former' : ''}</div><button class="btn s" onclick="editDiveSite(${l.id})">Edit</button>` : '<span class="note">—</span>'}</td>
    <td>${s ? `<span class="chip ${s.complimentary ? '' : (st[s.state] || '')}">${s.complimentary ? 'complimentary' : esc(s.state.replace('_', ' '))}</span><div class="note">${s.active ? 'next ' + esc(s.next_due_on) : 'off SCADA'}</div>` : ''}</td>
    <td class="note">${esc((p && p.address) || (l && l.address) || '')}</td></tr>`; }).join('') || '<tr><td colspan="5" class="empty">None.</td></tr>';
}
// The client called: ready for their maintenance. The lake comes off hold for
// the diver list and the visit waits under "Waiting on others" until the
// vendors' service reports come in.
async function accountReady(name){
  if (!confirm(`${name} is ready for their maintenance (client approved)?\n\nTheir lake comes off hold for the diver list, and the visit is followed under "Waiting on others" until Wettech's / Gulfshore's service reports come in.`)) return;
  const j = await api('/accounts/ready', {method:'POST', body:{name}});
  if (!j.success) { toast(j.error, true); return; }
  toast(`${name}: ${j.vendors.join(' and ')} going out` + (j.unheld ? ' - off hold on the diver list' : '') + '. Let them know to put it on their schedule.');
  loadAccounts(); loadToday();
}
async function previewDigest(){
  const j = await api('/digest'); if (!j.success) { toast(j.error, true); return; }
  const st = j.status || {};
  openModal('Daily email - ' + esc(j.subject), `<div class="note">To <b>${esc(j.to)}</b> every weekday morning.${st.at ? ' Last: ' + esc(st.at) + (st.error ? ' - <b class="bad">' + esc(st.error) + '</b>' : ' - sent') : ''}</div><div style="border:1px solid var(--border);border-radius:8px;padding:12px;max-height:60vh;overflow:auto;background:#fff;color:#111">${j.html}</div>`,
    `<button class="btn" onclick="closeModal()">Close</button><button class="btn p" onclick="sendDigestNow()">Send now</button>`);
}
async function sendDigestNow(){ const j = await api('/digest/send', {method:'POST', body:{}}); if (!j.success) { toast(j.error, true); return; } closeModal(); toast('Sent to ' + j.to); }

// ── divers ────────────────────────────────────────────
let DV = null;
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
async function loadDivers(){
  const j = await api('/dives');
  if (!j.success) { toast(j.error, true); return; }
  DV = j;
  const nm = new Date(j.next_month + 'T12:00:00').toLocaleString('en-US', {month:'long', year:'numeric'});
  const st = j.settings;
  document.getElementById('diveInfo').innerHTML = `${j.sites.filter(s => s.active && s.needs_dive).length} active sites need a diver · next email: <b>${esc(nm)}</b> (${j.next_count} sites) to ${esc(st.to)}` + (st.auto ? ' - sent automatically on the 1st' : ' - a to-do on the 1st') + (j.can_send ? '' : ' · <b class="bad">Microsoft 365 is not set up to send</b>');
  drawDiveSites();
  document.getElementById('diveDocx').href = '/pumps/api/dives/docx?month=' + encodeURIComponent(j.next_month);
  document.getElementById('diveSettings').innerHTML = `
    <label>Diver's email<input type="text" id="dvTo" value="${esc(st.to)}"></label>
    <label>Diver's name (greeting)<input type="text" id="dvName" value="${esc(st.diver_name)}"></label>
    <label>Copy to (replies go here)<input type="text" id="dvCc" value="${esc(st.cc)}"></label>
    <label>Send from (mailbox)<input type="text" id="dvFrom" value="${esc(st.from)}"></label>
    <label class="w">Signature<textarea id="dvSig" style="min-height:120px">${esc(st.signature)}</textarea></label>
    <label><span><input type="checkbox" id="dvAuto" ${st.auto ? 'checked' : ''}> Send it automatically from the PO mailbox on the 1st (off = to-do only)</span></label>
    <div><button class="btn p" onclick="saveDiveSettings()">Save</button></div>`;
  document.getElementById('diveSent').innerHTML = (j.sent || []).map(e => `<tr><td>${esc(e.month)}</td><td>${esc(e.sent_at)}</td><td>${esc(e.sent_by)}</td><td>${esc(e.to_addr)}${e.cc_addr ? '<div class="note">cc ' + esc(e.cc_addr) + '</div>' : ''}</td><td class="num">${e.sites}</td><td>${e.error ? '<b class="bad">' + esc(e.error) + '</b>' : '<span class="ok">sent</span>'}</td></tr>`).join('') || '<tr><td colspan="6" class="note">Nothing sent yet.</td></tr>';
}
function drawDiveSites(){
  if (!document.getElementById('diveBody')) { if (AC) refreshAccounts(); return; }
  if (!DV) return;
  const f = document.getElementById('diveFilter').value;
  const nm = new Date(DV.next_month + 'T12:00:00').getMonth() + 1;
  const on = s => s.active && s.needs_dive && (!s.months || s.months.split(',').map(Number).includes(nm));
  const rows = DV.sites.filter(s => !f ? true : f === 'dive' ? s.active && s.needs_dive : f === 'month' ? on(s) : f === 'former' ? !s.active : s.active && !s.needs_dive);
  const stat = {active: '', meet: '<span class="chip a">meet HOA</span>', hold: '<span class="chip r">hold</span>'};
  document.getElementById('diveBody').innerHTML = rows.map(s => `<tr>
    <td><b>${esc(s.name)}</b></td><td>${esc(s.equipment)}</td><td class="note">${esc(s.address)}</td>
    <td class="note">${esc(s.diver_notes)}${s.month_note ? '<div><b>Next email only:</b> ' + esc(s.month_note) + '</div>' : ''}</td>
    <td>${s.needs_dive ? '<span class="chip b">diver</span>' : '<span class="note">no</span>'}</td>
    <td class="note">${s.months ? (s.months === '1,4,7,10' ? 'Quarterly (Jan, Apr, Jul, Oct)' : s.months.split(',').map(m => MONTHS[m - 1]).join(', ')) : 'every month'}${!s.active ? ' <span class="chip">former</span>' : ''}</td>
    <td class="num">${esc(s.diver_cost || '')}</td><td class="note">${esc(s.our_bill || '')}${s.naples_electric ? '<div>Naples Electric ' + esc(s.naples_electric) + '</div>' : ''}</td>
    <td>${stat[s.status] || ''}${s.status_note ? '<div class="note">' + esc(s.status_note) + '</div>' : ''}</td>
    <td><button class="btn s" onclick="editDiveSite(${s.id})">Edit</button></td></tr>`).join('') || '<tr><td colspan="10" class="note">No sites.</td></tr>';
}
function editDiveSite(id){
  const s = (DV.sites || []).find(x => x.id === id) || {name:'', equipment:'', address:'', diver_notes:'', needs_dive:1, months:'', status:'active', status_note:'', month_note:''};
  const months = (s.months || '').split(',').filter(Boolean).map(Number);
  openModal(id ? 'Edit dive site' : 'Add dive site', `<div class="fields">
    <label class="w">Site<input type="text" id="ds_name" value="${esc(s.name)}"></label>
    <label>Lakes / filters / pumps<input type="text" id="ds_equipment" value="${esc(s.equipment)}" placeholder="e.g. 1 Pump 1 Lake 2 Filters"></label>
    <label><span><input type="checkbox" id="ds_needs" ${s.needs_dive ? 'checked' : ''}> Needs the diver</span></label>
    <label>Gulfshore (diver) $<input type="text" id="ds_diver_cost" value="${esc(s.diver_cost || '')}"></label>
    <label>Our bill<input type="text" id="ds_our_bill" value="${esc(s.our_bill || '')}"></label>
    <label>Date joined<input type="text" id="ds_joined" value="${esc(s.joined || '')}"></label>
    <label><span><input type="checkbox" id="ds_active" ${s.active === 0 ? '' : 'checked'}> Active account</span></label>
    <label class="w">Address / where the pumps are<textarea id="ds_address">${esc(s.address)}</textarea></label>
    <label class="w">Notes for the diver (every month - gate codes, what to check)<textarea id="ds_notes">${esc(s.diver_notes)}</textarea></label>
    <label class="w">Before each dive, follow up with… <span class="note">(a to-do about a week ahead)</span><textarea id="ds_follow_up">${esc(s.follow_up || '')}</textarea></label>
    <label>Status<select id="ds_status">${[['active','Normal'],['meet','HOA wants to meet the diver'],['hold','Hold off']].map(([v,l]) => `<option value="${v}" ${s.status === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
    <label>Status note<input type="text" id="ds_status_note" value="${esc(s.status_note)}"></label>
    <label class="w">One-time note (next email only)<input type="text" id="ds_month_note" value="${esc(s.month_note)}"></label>
    <div class="w"><b class="note">Months</b> <span class="note">(none ticked = every month)</span><div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px">${MONTHS.map((m, i) => `<label style="display:flex;gap:3px;align-items:center"><input type="checkbox" class="ds_m" value="${i + 1}" ${months.includes(i + 1) ? 'checked' : ''}>${m}</label>`).join('')}</div></div>
  </div>`, `${id ? `<button class="btn danger" onclick="deleteDiveSite(${id})">Remove</button>` : ''}<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="saveDiveSite(${id || 0})">Save</button>`);
}
async function saveDiveSite(id){
  const v = k => document.getElementById('ds_' + k).value;
  const body = {name: v('name'), equipment: v('equipment'), address: v('address'), diver_notes: v('notes'), follow_up: v('follow_up'), status: v('status'), status_note: v('status_note'), month_note: v('month_note'), needs_dive: document.getElementById('ds_needs').checked, active: document.getElementById('ds_active').checked, diver_cost: v('diver_cost'), our_bill: v('our_bill'), joined: v('joined'), months: [...document.querySelectorAll('.ds_m:checked')].map(x => x.value).join(',')};
  if (id) body.id = id;
  const j = await api('/dives/sites', {method:'POST', body});
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); toast('Saved'); loadDivers();
}
async function deleteDiveSite(id){ if (!confirm('Remove this site from the diver list?')) return; const j = await api('/dives/sites/' + id + '/delete', {method:'POST', body:{}}); if (j.success) { closeModal(); loadDivers(); } else toast(j.error, true); }
async function saveDiveSettings(){
  const j = await api('/dives/settings', {method:'POST', body:{to: document.getElementById('dvTo').value, diver_name: document.getElementById('dvName').value, cc: document.getElementById('dvCc').value, from: document.getElementById('dvFrom').value, signature: document.getElementById('dvSig').value, auto: document.getElementById('dvAuto').checked}});
  if (j.success) { toast('Saved'); loadDivers(); } else toast(j.error, true);
}
function diveMonth(){ return DV ? DV.next_month : ''; }
async function previewDiveEmail(){
  const j = await api('/dives/preview?month=' + encodeURIComponent(diveMonth()));
  if (!j.success) { toast(j.error, true); return; }
  openModal('Email to the diver - preview', `<div class="note">To ${esc(j.to)} · cc ${esc(j.cc)} · from ${esc(j.from || '(PO mailbox)')} · ${j.sites} sites · the list is also attached as a Word file</div><div class="note"><b>${esc(j.subject)}</b></div><div style="border:1px solid var(--border);border-radius:8px;padding:12px;max-height:60vh;overflow:auto;background:#fff;color:#111">${j.html}</div>`, `<button class="btn" onclick="closeModal()">Close</button><button class="btn p" onclick="sendDiveEmail()">Send now…</button>`);
}
async function sendDiveEmail(){
  const nm = new Date(diveMonth() + 'T12:00:00').toLocaleString('en-US', {month:'long', year:'numeric'});
  if (!confirm(`Email the ${nm} list to the diver now (${DV ? DV.settings.to : ''})?`)) return;
  const j = await api('/dives/send', {method:'POST', body:{month: diveMonth()}});
  if (!j.success) { toast(j.error, true); loadDivers(); return; }
  closeModal(); toast(`Sent to ${j.to.join(', ')} (${j.sites} sites).`); loadDivers();
}
async function loadSiteNames(){
  const j = await api('/site-names');
  const el = document.getElementById('siteNamesBody'); if (!el) return;
  el.innerHTML = (j.site_names || []).map(n => `<tr><td><b>${esc(n.place)}</b></td><td>${esc(n.area) || '<span class="note">any</span>'}</td><td>${esc(n.client_name)}</td><td>${esc(n.property_label) || '<span class="note">choose each time</span>'}</td><td class="note">${esc(n.note)}</td><td><button class="btn s" onclick="deleteSiteName(${n.id})">Remove</button></td></tr>`).join('') || '<tr><td colspan="6" class="note">None yet.</td></tr>';
}
function siteNameAdd(){
  inv = {mode: 'alias', doc: {}, client_id: null, lines: []};
  openModal('Add a site name', `<div class="fields">
    <label>Vendor writes<input type="text" id="snPlace" placeholder="e.g. Lee Memorial"></label>
    <label>Area (optional)<input type="text" id="snArea" placeholder="e.g. back station"></label></div>
    <div><b>It means this Jobber client</b><div class="toolbar" style="margin:6px 0"><input type="text" id="cq" placeholder="e.g. Hodges Funeral Home" style="flex:1"><button class="btn" onclick="findClients()">Search</button></div><div id="cands"></div></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="siteNameSave()">Save</button>`);
}
async function siteNameSave(){
  const place = document.getElementById('snPlace').value.trim();
  if (!place || !inv.client_id) { toast('Type the name and choose the Jobber client.', true); return; }
  const cand = document.querySelector('#cands .cand.on b');
  const j = await api('/site-names', {method:'POST', body:{place, area: document.getElementById('snArea').value.trim(), client_id: inv.client_id, client_name: cand ? cand.textContent : ''}});
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); toast('Saved'); loadSiteNames();
}
async function deleteSiteName(id){ if (!confirm('Remove this site name?')) return; const j = await api('/site-names/' + id + '/delete', {method:'POST', body:{}}); if (j.success) loadSiteNames(); else toast(j.error, true); }
function jobberLinkHtml(c){
  const j = c.jobber || {}, out = [];
  for (const [k, label] of [['request','request'],['quote','quote'],['job','job'],['invoice','invoice']]) {
    const r = j[k]; if (r && (r.uri || r.number)) out.push(r.uri ? `<a href="${esc(r.uri)}" target="_blank" rel="noopener">${label}${r.number ? ' #' + esc(r.number) : ''} ↗</a>` : `${label} #${esc(r.number)}`);
  }
  return out.join(' · ');
}
// The Jobber job (or, before there is one, the request) the item follows.
function jobberNo(c){ const J = c.jobber || {}, r = (J.job && J.job.number) ? ['job', J.job] : (J.request && J.request.number) ? ['request', J.request] : null;
  return r ? ` · <a href="${esc(r[1].uri || '#')}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Jobber ${r[0]} #${esc(r[1].number)} ↗</a>` : ''; }
// A document's number with its amount, e.g. "#Q-5521 $950.00".
function numAmt(num, amt){ const n = num ? `<span class="note">#${esc(String(num).replace(/^#/, ''))}</span>` : ''; const a = amt != null ? `<b>${money(amt)}</b>` : ''; return [n, a].filter(Boolean).join(' '); }
async function loadJobs(){
  const st = document.getElementById('jbShow').value, q = document.getElementById('jbSearch').value.trim();
  const [j, ji] = await Promise.all([api('/cases?status=' + st + (q ? '&q=' + encodeURIComponent(q) : '')), api('/jobber/items?open=1&kind=quote&show_ignored=1')]);
  if (!j.success) { document.getElementById('jobsBody').innerHTML = `<tr><td colspan="9" class="empty">${esc(j.error)}</td></tr>`; return; }
  const ref = r => r ? (r.uri ? `<a href="${esc(r.uri)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">#${esc(r.number || '')} ↗</a>` : (r.number ? '#' + esc(r.number) : '')) : '';
  document.getElementById('jobsBody').innerHTML = (j.cases || []).map(c => { const jb = c.jobber || {}, vp = c.vendor_pay || {};
    return `<tr class="click" onclick="openCase(${c.id})">
    <td><b>${esc(c.title || c.client_name)}</b><div class="note">${esc([c.client_name, c.site].filter(Boolean).join(' · '))}${c.po_number ? ' · PO ' + esc(c.po_number) : ''}${jobberNo(c)}</div></td>
    <td>${stageChip(c)}${c.idle_days >= 7 && c.status === 'open' ? ` <span class="chip a">${c.idle_days}d idle</span>` : ''}</td>
    <td>${esc(c.vendor)}</td><td>${numAmt(c.vendor_quote_number, c.vendor_quote_amount ?? c.vendor_quote_total)}</td>
    <td>${ref(jb.quote)}${jb.quote && jb.quote.total != null ? ' <b>' + money(jb.quote.total) + '</b>' : ''}${jb.quote && jb.quote.status ? ` <span class="note">${esc(jb.quote.status.replace(/_/g, ' '))}</span>` : ''}</td>
    <td>${numAmt(c.vendor_bill_number, c.vendor_bill_amount ?? c.vendor_bill_total)}</td>
    <td>${ref(jb.invoice) || (c.sei_invoice_number ? '#' + esc(c.sei_invoice_number) : '')}${(jb.invoice || c.sei_invoice_number) && ((jb.invoice || {}).total ?? c.amount) != null ? ' <b>' + money((jb.invoice || {}).total ?? c.amount) + '</b>' : ''}${jb.invoice && jb.invoice.status ? ` <span class="note">${esc(jb.invoice.status.replace(/_/g, ' '))}</span>` : ''}</td>
    <td>${vp.state === 'paid' ? '<span class="chip g">paid</span>' : vp.state === 'due' ? '<span class="chip r">pay now</span>' : vp.state === 'unpaid' ? '<span class="note">not yet</span>' : ''}</td>
    <td style="white-space:nowrap">${jb.job && jb.job.uri ? `<a class="btn s" href="${esc(jb.job.uri)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Jobber ↗</a> ` : ''}${c.status === 'open' ? `<button class="btn s" title="Mark done" onclick="event.stopPropagation();caseDone(${c.id})">✓ Done</button> <button class="btn s" title="Remove" onclick="event.stopPropagation();caseRemove(${c.id})">✕</button>` : `<button class="btn s" onclick="event.stopPropagation();caseReopen(${c.id})">↺ Reopen</button>`}</td></tr>`; }).join('') || '<tr><td colspan="9" class="empty">No jobs.</td></tr>';
  const s = ji.sync || {};
  document.getElementById('syncInfo').innerHTML = !JOBBER_OK ? '<b class="warn">Jobber is not connected.</b>' :
    (s.state === 'running' ? `Syncing Jobber… (started ${esc(s.started_at || '')})` : (s.state === 'failed' || s.state === 'interrupted' ? `<b class="bad">Last sync did not finish</b> - it runs again on its own · ` : '') + (s.finished_at ? `Synced with Jobber ${esc(s.finished_at.slice(11, 16))}` + (s.seconds != null && s.state === 'done' ? ` (took ${s.seconds < 90 ? s.seconds + ' sec' : Math.round(s.seconds / 60) + ' min'})` : '') : 'Not synced yet.') + (s.every_min ? ` · syncs on its own every ${s.every_min} min` : '')) + ((s.errors || []).length ? ` · <span class="bad" title="${esc(s.errors.join('\n'))}">${s.errors.length} errors</span>` : '');
  clearTimeout(window._syncPoll);
  if (s.state === 'running') window._syncPoll = setTimeout(() => { if (curTab === 'jobs') loadJobs(); }, 5000);
  // Our quotes sent to the client, not approved yet - longest waiting first.
  const sent = (ji.items || []).filter(it => it.kind === 'quote' && ['awaiting_response', 'changes_requested'].includes(it.status))
    .sort((a, b) => (a.updated_at || a.created_at || '').localeCompare(b.updated_at || b.created_at || ''));
  const days = d => d ? Math.max(0, Math.floor((Date.now() - new Date(d).getTime()) / 86400000)) : null;
  document.getElementById('jbSentCount').textContent = sent.length;
  document.getElementById('jbSentBody').innerHTML = sent.map(it => { const n = days(it.updated_at || it.created_at); return `<tr${it.case_id ? ` class="click" onclick="openCase(${it.case_id})"` : ''}>
    <td><a href="${esc(it.web_uri)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${it.number ? '#' + esc(it.number) + ' ' : ''}${esc(it.title)} ↗</a> ${catChip(it.category)}</td>
    <td>${esc(it.client_name)}<div class="note">${esc(it.property_label)}</div></td>
    <td class="num">${it.total != null ? '<b>' + money(it.total) + '</b>' : ''}</td>
    <td>${it.status === 'changes_requested' ? '<span class="chip a">changes requested</span>' : '<span class="note">sent</span>'}</td>
    <td>${n == null ? '' : n >= 14 ? `<b class="warn">${n} days</b>` : n + (n === 1 ? ' day' : ' days')}</td>
    <td>${it.case_id ? `<span class="note">job ${it.case_id}</span>` : ''}</td></tr>`; }).join('') || `<tr><td colspan="6" class="empty">${JOBBER_OK ? 'No quotes waiting on a client.' : 'Connect Jobber to see quotes.'}</td></tr>`;
}
async function jobberAct(id, action){ const j = await api('/jobber/items/' + encodeURIComponent(id), {method:'POST', body:{action}}); if (!j.success) { toast(j.error, true); return; } loadToday(); if (curTab === 'jobs') loadJobs(); if (action === 'track' && j.case_id) openCase(j.case_id); }
async function jobberLink(id){ const n = prompt('Job number in Pumps to add it to:'); if (!n) return; const j = await api('/jobber/items/' + encodeURIComponent(id), {method:'POST', body:{action:'link', case_id: parseInt(n)}}); if (j.success) loadJobs(); else toast(j.error, true); }
async function syncJobber(){ const j = await api('/jobber/sync', {method:'POST', body:{}}); if (!j.success) { toast(j.error, true); return; } toast(j.started ? 'Jobber sync started - this takes a minute or two.' : 'A Jobber sync is already running - the list updates when it finishes.'); setTimeout(loadJobs, 2000); }

// ── mailbox scan ─────────────────────────────────────
function updateScanInfo(s){
  const el = document.getElementById('scanInfo'); if (!el) return;
  s = s || {};
  el.textContent = s.state === 'running' ? 'scanning…' : (s.finished_at ? `last scan ${s.finished_at.slice(5,16)} - ${s.documents_added || 0} new` + (s.read_again ? `, ${s.read_again} read again` : '') + ((s.errors||[]).length ? `, ${s.errors.length} errors` : '') : 'not scanned yet');
  if ((s.errors || []).length) el.title = s.errors.join('\n');
}
async function scanNow(){
  const b = document.getElementById('scanBtn'); b.disabled = true;
  const j = await api('/scan', {method:'POST', body:{}});
  if (!j.success) { toast(j.error, true); b.disabled = false; return; }
  updateScanInfo({state:'running'});
  const poll = setInterval(async () => { const s = await api('/scan'); if ((s.status || {}).state !== 'running') { clearInterval(poll); b.disabled = false; scanDone(s.status || {}); } }, 3000);
}
async function showRecentFiles(){
  const j = await api('/scan'); if (!j.success) { toast(j.error, true); return; }
  const rows = (j.recent_files || []).map(f => `<div style="padding:6px 0;border-bottom:1px solid var(--line,#ddd)"><b>${esc(f.file)}</b> <span class="note">${esc((f.at || '').slice(5,16))} · ${esc(f.from || '')}</span><div>${esc(f.what)}${f.case_id ? ` · <a href="#" onclick="event.preventDefault();closeModal();openCase(${f.case_id})">open job #${f.case_id}</a>` : ''}</div></div>`).join('');
  openModal('Recent emailed files', rows ? `<p class="note">Every file the mailbox scan picked up (the automatic scan runs every 30 minutes too), newest first.</p>${rows}` : '<div class="empty">No emailed files yet since this list started.</div>');
}
function scanDone(s){
  updateScanInfo(s); loadToday(); showTab(curTab);
  const files = (s.added || []).length + (s.skipped_files || []).filter(f => f.why !== 'not pump related').length;
  if (files) { showRecentFiles(); return; }
  toast(`Scan done - nothing new. Emails are only read once: the automatic scan may already have picked them up - see Recent files.`);
}

// ── modal ─────────────────────────────────────────────
function openModal(title, body, foot){ document.getElementById('modal').innerHTML = `<div class="hd"><b>${title}</b><button class="btn s" onclick="closeModal()">✕</button></div><div class="bd">${body}</div><div class="ft">${foot || ''}</div>`; document.getElementById('modalWrap').classList.remove('hide'); }
function closeModal(){ document.getElementById('modalWrap').classList.add('hide'); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') { if (!document.getElementById('modalWrap').classList.contains('hide')) closeModal(); else if (!document.getElementById('drawerWrap').classList.contains('hide')) closeDrawer(); } });

// ── start ─────────────────────────────────────────────
(function(){
  const h = location.hash.slice(1);
  if (h.startsWith('item-')) { loadToday(); loadJobs(); openCase(parseInt(h.slice(5))); }
  else if (h.startsWith('doc-')) { loadToday(); loadJobs(); openDoc(parseInt(h.slice(4))); }
  if (['jobs','scada','accounts','reports'].includes(h)) showTab(h); else if (!h.startsWith('item-') && !h.startsWith('doc-')) showTab('jobs');
  if (!h || ['jobs','scada','accounts','reports'].includes(h)) loadToday();
  setInterval(() => { if (document.getElementById('drawerWrap').classList.contains('hide') && document.getElementById('modalWrap').classList.contains('hide')) { loadToday(); if (curTab === 'jobs') loadJobs(); } }, 60000);
})();
</script>
</body>
</html>'''
