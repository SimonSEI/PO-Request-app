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
:root{--brand:#1D4ED8;--brand-d:#1E40AF;--lime:#2563EB;--navy:#172554;--navy-2:#1E3A8A;--brand-soft:#EFF6FF;--brand-ring:rgba(29,78,216,.22);
      --border:#E2E8F0;--border-2:#CBD5E1;--bg:#F1F5F9;--card:#fff;--text:#0F172A;--muted:#64748B;--faint:#94A3B8;
      --sheet-head:#DBEAFE;--green:#3F8F29;--green-bg:#E6F2DC;--amber:#8A5A00;--amber-bg:#FFF1CC;--red:#B3261E;
      --red-bg:#FCE6E3;--violet:#5B3FB0;--violet-bg:#EEEAFB;--slate-bg:#EEF2F6;--blue-bg:#E1EDF7;--blue:#1F5E8C;
      --radius:8px;--shadow-sm:0 1px 2px rgba(15,23,42,.06);--shadow:0 1px 3px rgba(15,23,42,.08);--shadow-lg:0 16px 40px rgba(15,23,42,.22);}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Inter',system-ui,sans-serif;color:var(--text);font-size:14px;min-height:100vh;-webkit-font-smoothing:antialiased;background:var(--bg);}
a{color:var(--brand);font-weight:500;}
::selection{background:#DBEAFE;}
*{scrollbar-width:thin;scrollbar-color:#CBD5E1 transparent;}
h2,h3{font-weight:700;letter-spacing:-.2px;}
/* header: Jobber's navy bar */
.top{background:var(--navy);color:#fff;display:flex;align-items:center;justify-content:space-between;
     padding:0 24px;height:60px;position:sticky;top:0;z-index:40;gap:12px;box-shadow:0 1px 0 rgba(0,0,0,.2);}
.top .t{font-weight:700;font-size:18px;letter-spacing:-.2px;display:flex;align-items:center;gap:12px;}
.top .t .logo{width:34px;height:34px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;background:var(--lime);}
.top .t small{display:block;font-size:11.5px;font-weight:500;color:#A5B4D4;letter-spacing:0;margin-top:1px;}
.top .r{display:flex;gap:8px;align-items:center;font-size:13px;color:#C7D2EA;}
.top .who{display:inline-flex;align-items:center;gap:8px;padding:0 8px 0 4px;font-weight:500;color:#fff;}
.top .who::before{content:attr(data-i);width:30px;height:30px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;
     font-size:12px;font-weight:700;color:var(--navy);background:#fff;}
.top .btn{background:transparent;border-color:rgba(255,255,255,.28);color:#fff;box-shadow:none;}
.top .btn:hover{background:rgba(255,255,255,.1);border-color:rgba(255,255,255,.45);}
.top .btn.p{background:var(--lime);border-color:var(--lime);color:#fff;}
.top .btn.p:hover{background:#3B82F6;border-color:#3B82F6;}
/* buttons */
.btn{padding:7px 14px;border-radius:8px;border:1px solid var(--border-2);background:#fff;cursor:pointer;font:inherit;
     font-size:13px;font-weight:600;color:var(--navy);text-decoration:none;white-space:nowrap;display:inline-flex;align-items:center;gap:6px;
     transition:background .15s,border-color .15s,box-shadow .15s,color .15s;}
.btn:hover{background:#F8FAFC;border-color:#B6C2D2;}
.btn:focus-visible{outline:none;box-shadow:0 0 0 3px var(--brand-ring);border-color:var(--brand);}
.btn.p{background:var(--brand);border-color:var(--brand);color:#fff;}
.btn.p:hover{background:var(--brand-d);border-color:var(--brand-d);}
.btn.s{padding:4px 10px;font-size:12px;border-radius:6px;}
.btn.danger{color:var(--red);}
.btn.danger:hover{background:var(--red-bg);border-color:#F1BDB7;}
.btn:disabled{opacity:.55;cursor:wait;}
/* status strip */
.strip{display:flex;flex-wrap:wrap;gap:6px 20px;padding:10px 24px;font-size:12.5px;color:var(--muted);background:#fff;border-bottom:1px solid var(--border);}
.strip>div{display:inline-flex;flex-wrap:wrap;align-items:center;gap:4px 6px;max-width:100%;}
.strip>div::before{content:'';width:8px;height:8px;border-radius:50%;background:var(--faint);flex:none;margin-right:2px;}
.strip>div:has(.ok)::before{background:var(--green);}
.strip>div:has(.warn)::before{background:#E0A100;}
.strip>div:has(.bad)::before{background:var(--red);}
.strip>div:has(#digestInfo)::before{background:var(--blue);}
.strip b{color:var(--text);font-weight:600;}
.ok{color:var(--green);} .warn{color:var(--amber);} .bad{color:var(--red);}
.flash{margin:14px 24px 0;padding:11px 16px;border-radius:8px;background:var(--amber-bg);color:var(--amber);font-size:13px;border-left:4px solid #E0A100;}
/* layout */
.layout{display:grid;grid-template-columns:minmax(300px,380px) minmax(0,1fr);align-items:start;gap:20px;padding:20px 24px 32px;}
.mainc{min-width:0;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden;}
.side{min-width:0;position:sticky;top:80px;max-height:calc(100vh - 100px);overflow-y:auto;background:var(--card);
     border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);}
.side .hd{padding:16px 16px 12px;display:flex;flex-direction:column;gap:9px;border-bottom:1px solid var(--border);position:sticky;top:0;background:#fff;z-index:2;}
.side .hd h2{font-size:17px;display:flex;align-items:center;gap:8px;}
.side .grp{padding:8px 16px;font-size:12px;font-weight:700;color:var(--navy);background:#F8FAFC;border-bottom:1px solid var(--border);}
.side .row{padding:12px 16px;}
.side .row .tt{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;}
.side .act{display:flex;gap:6px;flex-wrap:wrap;margin-top:7px;}
.side details summary{cursor:pointer;list-style:none;}
.side details summary::-webkit-details-marker{display:none;}
.side details[open] summary .arr{transform:rotate(90deg);}
.side .arr{display:inline-block;transition:transform .15s;}
@media (max-width:900px){.layout{grid-template-columns:minmax(0,1fr);}.side{position:static;max-height:none;}}
.hide{display:none!important;}
/* tabs: underlined, like Jobber */
.tabs{display:flex;gap:4px;padding:0 20px;overflow-x:auto;border-bottom:1px solid var(--border);}
.tab{padding:15px 12px 13px;font-weight:600;font-size:14px;color:var(--muted);cursor:pointer;white-space:nowrap;
     border-bottom:3px solid transparent;margin-bottom:-1px;transition:color .15s,border-color .15s;display:inline-flex;align-items:center;}
.tab:hover{color:var(--navy);}
.tab.on{color:var(--navy);border-bottom-color:var(--brand);}
.tab .n{display:inline-block;min-width:20px;padding:1px 6px;margin-left:7px;border-radius:10px;background:var(--slate-bg);font-size:11px;text-align:center;color:var(--muted);}
.tab .n:empty{display:none;}
.tab.on .n{background:var(--brand-soft);color:var(--brand-d);}
.tab .n.hot{background:var(--red-bg);color:var(--red);}
.panel{padding:18px 20px 32px;min-height:60vh;}
.panel h3{font-size:16px!important;}
/* cards and rows */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px;}
.box{border:1px solid var(--border);border-radius:var(--radius);background:#fff;overflow:hidden;}
.box h3{font-size:14px;padding:11px 14px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;gap:8px;background:#fff;}
.box h3 .c{font-size:12px;color:var(--muted);font-weight:600;}
.box.red h3{background:var(--red-bg);color:var(--red);}
.box.amber h3{background:var(--amber-bg);color:var(--amber);}
.row{padding:10px 14px;border-bottom:1px solid var(--border);cursor:pointer;display:flex;gap:10px;justify-content:space-between;align-items:flex-start;transition:background .12s;}
.row:last-child{border-bottom:none;}
.row:hover{background:#F5F8FC;}
.row .main{min-width:0;flex:1;}
.row .tt{font-weight:600;font-size:13.5px;overflow:hidden;text-overflow:ellipsis;line-height:1.4;}
.row .sub{color:var(--muted);font-size:12.5px;margin-top:3px;line-height:1.45;}
.empty{padding:18px 16px;color:var(--faint);font-size:13px;text-align:center;}
/* status labels: a dot and the words, like Jobber's */
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:2px 9px 2px 8px;border-radius:999px;
      background:var(--slate-bg);color:#475569;white-space:nowrap;line-height:1.55;}
.chip::before{content:'';width:7px;height:7px;border-radius:50%;background:currentColor;opacity:.85;flex:none;}
.chip:empty{display:none;}
.chip.g{background:var(--green-bg);color:#2E6B1B;} .chip.a{background:var(--amber-bg);color:var(--amber);}
.chip.r{background:var(--red-bg);color:var(--red);} .chip.v{background:var(--violet-bg);color:var(--violet);}
.chip.b{background:var(--blue-bg);color:var(--blue);}
.side .hd h2 .chip::before,.tab .chip::before,h3 .chip::before{display:none;}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px;}
.toolbar .sp{flex:1;}
/* forms */
input[type=text],input[type=number],input[type=date],input[type=email],select,textarea{font:inherit;font-size:13.5px;padding:8px 10px;
     border:1px solid var(--border-2);border-radius:8px;background:#fff;color:var(--text);transition:border-color .15s,box-shadow .15s;}
textarea{width:100%;min-height:70px;resize:vertical;line-height:1.5;}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--navy);box-shadow:0 0 0 1px var(--navy);}
input[type=checkbox],input[type=radio]{accent-color:var(--brand);}
input::placeholder,textarea::placeholder{color:var(--faint);}
/* tables */
table.t{width:100%;border-collapse:separate;border-spacing:0;font-size:13px;}
table.t th{text-align:left;font-size:12.5px;color:var(--navy);font-weight:700;padding:10px 10px;
     border-bottom:2px solid var(--border);background:#fff;position:sticky;top:0;z-index:1;}
table.t td{padding:11px 10px;border-bottom:1px solid #EDF1F5;vertical-align:top;}
table.t tbody tr:last-child td{border-bottom:none;}
table.t tr.click{cursor:pointer;} table.t tr.click:hover td{background:#F5F8FC;}
#p-jobs table.t td:first-child{min-width:180px;}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;}
.scroll{overflow:auto;max-height:70vh;border:1px solid var(--border);border-radius:var(--radius);background:#fff;}
/* tracker sheet */
table.sheet{border-collapse:collapse;width:100%;font-size:12.5px;min-width:1350px;}
.sheet th{background:var(--sheet-head);border:1px solid #BFD3F5;padding:8px 6px;font-size:12px;font-weight:700;position:sticky;top:0;z-index:1;text-align:left;}
.sheet td{border:1px solid var(--border);padding:5px 6px;vertical-align:top;background:#fff;min-width:60px;}
.sheet td.desc{min-width:240px;white-space:pre-wrap;}
.sheet td.num{text-align:right;}
.sheet td[contenteditable]:focus{outline:2px solid var(--brand);outline-offset:-2px;background:#EFF6FF;}
.sheet td.dirty{background:#FFFBEB;}
.sheet td.issue{background:var(--red-bg);}
.months{display:flex;gap:4px;padding:6px 0 0;overflow-x:auto;}
.month{padding:6px 14px;font-size:12px;font-weight:600;color:var(--muted);background:var(--slate-bg);border-radius:8px 8px 0 0;cursor:pointer;white-space:nowrap;}
.month.on{background:#fff;color:var(--text);border:1px solid var(--border);border-bottom:3px solid var(--brand);}
.foot{display:flex;gap:20px;font-size:12px;color:var(--muted);padding:8px 2px;}
/* drawer */
.shade{position:fixed;inset:0;background:rgba(15,23,42,.45);z-index:60;animation:fade .18s ease;}
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(740px,100%);background:var(--bg);z-index:61;overflow:auto;
     box-shadow:var(--shadow-lg);animation:slideIn .22s cubic-bezier(.2,.8,.2,1);}
@keyframes slideIn{from{transform:translateX(40px);opacity:0;}to{transform:none;opacity:1;}}
/* Pump Manager panel (the outside assistant) */
.pm{position:fixed;top:0;right:0;bottom:0;width:min(400px,100%);background:var(--card);z-index:62;display:flex;flex-direction:column;
    box-shadow:var(--shadow-lg);border-left:1px solid var(--border);animation:slideIn .22s cubic-bezier(.2,.8,.2,1);}
.pm .hd{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--border);}
.pm .hd b{flex:1;font-size:15px;}
.pm .msgs{flex:1;overflow:auto;padding:12px 14px;display:flex;flex-direction:column;gap:10px;background:var(--bg);}
.pm .q{align-self:flex-end;max-width:85%;background:var(--brand);color:#fff;padding:8px 11px;border-radius:12px 12px 2px 12px;white-space:pre-wrap;overflow-wrap:anywhere;}
.pm .a{align-self:flex-start;max-width:92%;background:var(--card);border:1px solid var(--border);padding:8px 11px;border-radius:12px 12px 12px 2px;overflow-wrap:anywhere;line-height:1.45;}
.pm .a code{background:var(--slate-bg);padding:1px 4px;border-radius:4px;font-size:12.5px;}
.pm .a pre{background:var(--slate-bg);padding:8px;border-radius:6px;overflow:auto;white-space:pre-wrap;}
.pm .a ul{margin:4px 0 4px 18px;}
.pm .a.wait{color:var(--muted);font-style:italic;}
.pm .a.bad{color:var(--red);background:var(--red-bg);border-color:transparent;}
.pm .ctx{font-size:11.5px;color:var(--faint);align-self:flex-end;margin-top:-6px;}
.pm .ft{border-top:1px solid var(--border);padding:10px 12px;display:flex;gap:8px;align-items:flex-end;}
.pm .ft textarea{flex:1;resize:none;min-height:40px;max-height:140px;padding:8px 10px;border:1px solid var(--border-2);border-radius:8px;font:inherit;}
.pmmini{position:fixed;right:18px;bottom:18px;z-index:62;display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:999px;
    background:var(--brand);color:#fff;border:0;font:inherit;font-weight:600;cursor:pointer;box-shadow:var(--shadow-lg);}
.pmmini .pmdot{margin-left:0;}
.pmdot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#F59E0B;margin-left:6px;vertical-align:middle;}
@keyframes fade{from{opacity:0;}to{opacity:1;}}
.drawer .hd{position:sticky;top:0;background:#fff;border-bottom:1px solid var(--border);padding:18px 22px 14px;display:flex;justify-content:space-between;gap:10px;z-index:2;}
.drawer .hd h2{font-size:20px;margin-bottom:6px;}
.drawer .bd{padding:18px 22px 40px;display:flex;flex-direction:column;gap:14px;}
.drawer .sec{background:#fff;border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;}
.drawer .sec:not(:has(h4)){background:none;border:none;padding:0;}
.sec h4{font-size:15px;color:var(--navy);margin-bottom:10px;font-weight:700;}
.fields{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px;}
.fields label{font-size:12px;font-weight:600;color:var(--muted);display:flex;flex-direction:column;gap:4px;}
.fields label.w{grid-column:1/-1;}
.steps{display:flex;flex-direction:column;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;}
.step{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid #EDF1F5;font-size:13px;}
.step:last-child{border-bottom:none;}
.step.cur{background:var(--brand-soft);box-shadow:inset 3px 0 0 var(--brand);font-weight:600;}
.step.na{color:var(--faint);text-decoration:line-through;}
.step .dot{width:18px;height:18px;border-radius:50%;border:2px solid #CBD5E1;flex:none;display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;cursor:pointer;transition:all .15s;}
.step .dot:hover{border-color:var(--green);}
.step.done .dot{background:var(--green);border-color:var(--green);}
.step .lbl{flex:1;}
.step .when{font-size:12px;color:var(--muted);}
.money{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;}
.money .m{border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px;background:#fff;}
.money .m .k{font-size:12px;color:var(--muted);font-weight:600;}
.money .m .v{font-size:20px;font-weight:700;margin-top:4px;letter-spacing:-.3px;font-variant-numeric:tabular-nums;}
.cmp{margin-top:10px;padding:9px 12px;border-radius:8px;font-size:13px;font-weight:600;}
.cmp.match{background:var(--green-bg);color:#2E6B1B;} .cmp.over,.cmp.under,.cmp.no_quote{background:var(--red-bg);color:var(--red);}
.issue{background:var(--red-bg);color:var(--red);border-left:4px solid var(--red);border-radius:8px;padding:10px 12px;font-size:13px;display:flex;justify-content:space-between;gap:10px;align-items:center;}
.issue.done{background:var(--slate-bg);color:var(--muted);border-left-color:var(--border-2);}
.docs .d{display:flex;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid var(--border);flex-wrap:wrap;}
.ev{font-size:12px;color:var(--muted);padding:5px 0;border-bottom:1px dashed var(--border);}
.track{display:flex;align-items:flex-start;margin:6px 0 16px;}
.track .n{flex:1;min-width:0;text-align:center;position:relative;font-size:10.5px;color:var(--muted);line-height:1.25;padding:0 2px;}
.track .n::before{content:'';position:absolute;top:10px;left:-50%;right:50%;height:3px;border-radius:2px;background:var(--border);z-index:0;}
.track .n:first-child::before{display:none;}
.track .n.done::before,.track .n.cur::before{background:var(--green);}
.track .b{width:22px;height:22px;border-radius:50%;margin:0 auto 5px;background:#fff;border:2px solid var(--border-2);position:relative;z-index:1;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;}
.track .n.done .b{background:var(--green);border-color:var(--green);}
.track .n.cur .b{border-color:var(--brand);background:#fff;box-shadow:0 0 0 4px var(--brand-ring);}
.track .n.cur{color:var(--brand-d);font-weight:700;}
.track .n.done{color:var(--text);}
.track .d{font-size:10px;color:var(--muted);font-weight:400;margin-top:1px;}
.tl{position:relative;padding-left:4px;}
.tl .day{font-size:12px;font-weight:700;color:var(--navy);margin:12px 0 4px 38px;}
.tl .it{display:flex;gap:10px;position:relative;padding:5px 0;}
.tl .it::before{content:'';position:absolute;left:13px;top:0;bottom:0;width:2px;background:var(--border);}
.tl .ic{width:28px;height:28px;flex:none;border-radius:50%;background:var(--slate-bg);display:flex;align-items:center;justify-content:center;font-size:13px;position:relative;z-index:1;border:2px solid #fff;}
.tl .ic.g{background:var(--green-bg);} .tl .ic.r{background:var(--red-bg);} .tl .ic.b{background:var(--blue-bg);} .tl .ic.a{background:var(--amber-bg);}
.tl .tx{font-size:13px;padding-top:4px;min-width:0;} .tl .tx .m{font-size:12px;color:var(--muted);margin-top:1px;overflow-wrap:anywhere;}
@media (max-width:640px){.track .n{font-size:0;} .track .n.cur{font-size:10.5px;}}
.ev b{color:var(--text);font-weight:600;}
/* modal */
.modal{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:min(820px,96vw);max-height:92vh;overflow:auto;background:#fff;border-radius:12px;z-index:71;
     box-shadow:var(--shadow-lg);animation:pop .18s ease;}
@keyframes pop{from{opacity:0;transform:translate(-50%,-48%);}to{opacity:1;transform:translate(-50%,-50%);}}
.modal .hd{padding:16px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;background:#fff;z-index:2;font-size:17px;}
.modal .bd{padding:18px 20px;display:flex;flex-direction:column;gap:14px;}
.modal .ft{padding:12px 20px;border-top:1px solid var(--border);display:flex;gap:8px;justify-content:flex-end;position:sticky;bottom:0;background:#fff;}
.modal .ft:empty{display:none;}
.shade2{position:fixed;inset:0;background:rgba(15,23,42,.5);z-index:70;animation:fade .18s ease;}
.note{font-size:12.5px;color:var(--muted);line-height:1.55;}
.safe{background:var(--green-bg);color:#2E6B1B;border-radius:8px;padding:9px 12px;font-size:12.5px;font-weight:600;}
.cand{display:flex;gap:8px;align-items:center;padding:8px 10px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px;cursor:pointer;transition:all .12s;}
.cand:hover{border-color:var(--border-2);}
.cand.on{border-color:var(--brand);background:var(--brand-soft);box-shadow:inset 0 0 0 1px var(--brand);}
.drop{border:2px dashed var(--border-2);border-radius:8px;padding:26px;text-align:center;color:var(--muted);cursor:pointer;background:#F8FAFC;transition:all .15s;}
.drop.over,.drop:hover{border-color:var(--brand);background:var(--brand-soft);}
.howto{max-width:860px;line-height:1.6;font-size:13.5px;}
.howto h3{margin:18px 0 6px;font-size:15px;}
.howto li{margin-left:20px;}
.howto code{background:var(--slate-bg);padding:1px 5px;border-radius:4px;font-size:12px;}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);padding:12px 18px;border-radius:8px;z-index:99;font-size:13.5px;font-weight:600;
     box-shadow:0 10px 30px rgba(15,23,42,.3);background:var(--navy);color:#fff;border-left:4px solid var(--lime);animation:toastIn .2s ease;max-width:calc(100vw - 32px);}
.toast.bad{background:var(--red-bg);color:var(--red);border-left-color:var(--red);}
@keyframes toastIn{from{opacity:0;transform:translate(-50%,8px);}to{opacity:1;transform:translate(-50%,0);}}
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
@media (max-width:640px){.fields{grid-template-columns:1fr;}.money{grid-template-columns:1fr;}.top{padding:0 12px;gap:8px;}.top .t>div,.top .r .who{display:none;}.top .r{gap:6px;min-width:0;overflow-x:auto;}.top .r .btn{padding:6px 10px;}
  .strip{padding:10px 16px;}.layout{padding:12px 12px 20px;gap:12px;}.panel{padding:12px;}.tabs{padding:0 8px;}.drawer .bd{padding:14px 12px 30px;}}
details.fold > summary { cursor: pointer; list-style: none; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
details.fold > summary::-webkit-details-marker { display: none; }
details.fold > summary h4 { margin: 0; }
details.fold > summary h4::before { content: '▸ '; color: var(--muted, #888); }
details.fold[open] > summary h4::before { content: '▾ '; }
.svc { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 12px; font-weight: 600; margin: 1px 0; white-space: nowrap; }
.svc.on { background: #dcfce7; color: #166534; border: 1px solid #86efac; }
.svc.off { background: #f3f4f6; color: #6b7280; border: 1px dashed #cbd5e1; cursor: pointer; }
.svc.off:hover { background: #e5e7eb; color: #111827; border-style: solid; }
.svc.none { background: #f3f4f6; color: #c0c4cc; border: 1px solid #e5e7eb; }
</style>
<script>
(function(){
  var t0 = (document.querySelector('meta[name="csrf-token"]')||{}).content || '';
  var f = window.fetch;
  window.fetch = function(url, o){
    o = o || {};
    var m = (o.method || 'GET').toUpperCase();
    // The page's own token expires after 12 hours (left open overnight); every
    // response refreshes the csrf_token cookie, so send that one.
    var c = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/), t = c ? decodeURIComponent(c[1]) : t0;
    if (m !== 'GET' && m !== 'HEAD') { o.headers = o.headers || {}; if (!(o.headers instanceof Headers)) o.headers['X-CSRFToken'] = t; else o.headers.set('X-CSRFToken', t); }
    return f.call(this, url, o);
  };
})();
</script>
</head>
<body>
<nav class="top">
  <div class="t"><span class="logo"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.7c3.6 4.3 6 7.7 6 10.8a6 6 0 0 1-12 0c0-3.1 2.4-6.5 6-10.8z"/><path d="M9.2 14.2a2.9 2.9 0 0 0 2.8 2.6"/></svg></span><div>Pumps<small>Pumps, lakes &amp; SCADA</small></div></div>
  <div class="r">
    <button class="btn p" onclick="newCase()">＋ New item</button>
    <button class="btn" title="Follow a service call booked in Jobber - it's the start of the work, no quote" onclick="addServiceCall()">＋ Service call</button>
    {% if assistant %}<button class="btn" id="pmBtn" title="Ask Pump Manager, our assistant - answers take a minute or two" onclick="pmToggle()">💬 Ask Pump Manager</button>{% endif %}
    <span class="who" data-i="{{ (full_name or '?')[:1]|upper }}">{{ full_name }}</span>
    <button class="btn" onclick="showUndo()" title="Undo a recent change (Ctrl+Z / ⌘Z undoes your last one)">↶ Undo</button>
    <a class="btn" href="{{ url_for('dashboard') }}">← Dashboard</a>
  </div>
</nav>
<div class="strip">
  <div>PO@ mailbox: {% if email %}<b class="ok">connected</b> · <span id="scanInfo">…</span>
    <button class="btn s" id="scanBtn" onclick="scanNow()">Scan now</button> <button class="btn s" onclick="showRecentFiles()" title="What happened to each emailed file">Recent files</button>{% else %}<b class="warn">not configured</b> (upload documents by hand){% endif %}</div>
  <div>Jobber: <span id="jobberInfo">{% if jobber.connected %}<b class="ok">connected</b>{% elif jobber.can_connect %}{% if jobber.broken %}<b class="bad" title="{{ jobber.broken }}">disconnected - Jobber stopped accepting the app's sign-in</b> {% endif %}<a class="btn s p" href="{{ url_for('pumps.jobber_connect') }}">{{ 'Reconnect' if jobber.broken else 'Connect' }} Jobber</a>{% else %}<b class="warn">not set up</b>{% endif %}</span></div>
  <div>Reading documents: {% if claude and claude_problem %}<b class="bad">Claude is not working</b> ({{ claude_problem }}) - new documents wait in the To do list and are read again automatically once it works{% elif claude %}<b class="ok">Claude</b>{% else %}<b class="ok">built-in reader</b> (Wettech and Gulfshore quotes, invoices and reports; anything it can't read waits in the To do list){% endif %}</div>
  <div>Matching bills to jobs: {% if grok %}<b class="ok">Grok on</b> (when no PO, quote # or email ties a vendor bill to a job){% else %}<span class="note">by PO, quote # and client only - set XAI_API_KEY to let Grok match the rest</span>{% endif %}</div>
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
      <button class="btn" onclick="uploadBox()">⬆ Upload</button>
      <input type="file" id="fileIn" multiple accept=".pdf,.docx,.doc" class="hide" onchange="uploadFiles(this.files)"></div>
  </div>
  <div id="searchResults" class="hide"></div>
  <div id="todoList"><div class="empty">Loading…</div></div>
</aside>
<div class="mainc">
<div class="tabs" id="tabs">
  <div class="tab on" data-tab="jobs">Home <span class="n" id="n-jobs"></span></div>
  <div class="tab" data-tab="scada">SCADA <span class="n" id="n-scada"></span></div>
  <div class="tab" data-tab="accounts">Accounts</div>
  <div class="tab" data-tab="reports">Reports</div>
  <div class="tab" data-tab="bills">Bills to pay <span class="n" id="n-bills"></span></div>
  <div class="tab" data-tab="vquotes">Quotes <span class="n" id="n-vquotes"></span></div>
  <div class="tab" data-tab="vinvoices">Vendor invoices</div>
</div>

<!-- JOBS -->
<div class="panel" id="p-jobs">
  <h3 style="margin:0 0 8px;font-size:14px">Job Watchlist</h3>
  <div class="toolbar">
    <input type="text" id="jbSearch" placeholder="Find a job, client, PO, quote or invoice #…" oninput="clearTimeout(window._jq);window._jq=setTimeout(loadJobs,300)" style="width:240px">
    <select id="jbShow" onchange="loadJobs()"><option value="open">Open</option><option value="waiting">Waiting on others</option><option value="closed">Done</option><option value="all">All</option></select>
    <div class="sp"></div><span id="syncInfo" class="note"></span>
    <button class="btn s" title="It syncs on its own - this just does it now" onclick="syncJobber()">↻ Sync now</button>
  </div>
  <div class="scroll" style="max-height:45vh"><table class="t"><thead><tr><th>Job</th><th>Where it is</th><th>Vendor</th><th class="num">Vendor quote</th><th>Our quote</th><th class="num">Vendor bill</th><th>Our invoice</th><th>Vendor paid</th><th></th></tr></thead><tbody id="jobsBody"></tbody></table></div>
  <details id="msFold" open ontoggle="window.foldSave && foldSave('ms', this.open)" style="margin-top:18px"><summary style="cursor:pointer;margin-bottom:8px"><h3 style="display:inline;margin:0;font-size:14px">Maintenance this month <span class="chip" id="msCount"></span></h3> <span class="note">click to show or fold away</span></summary>
  <div class="toolbar">
    <select id="msMonth" onchange="loadMaintSchedule()"></select>
    <input type="text" id="msSearch" placeholder="Find an account or address…" oninput="drawMaintSchedule()" style="width:220px">
    <select id="msShow" onchange="drawMaintSchedule()"><option value="">All visits</option><option value="todo">Not notified yet</option><option value="Wettech">Justin - Wettech (pumps)</option><option value="Gulfshore">Jordan - Gulfshore (diving)</option></select>
    <div class="sp"></div><span id="msInfo" class="note"></span>
    <button class="btn p" id="msMarkW" title="Tick the accounts, then record that Justin (Wettech) was told about their pump visits" onclick="maintNotifiedAskMany('Wettech')">✓ Justin told</button>
    <button class="btn p" id="msMarkG" title="Tick the accounts, then record that Jordan (Gulfshore) was told about their lake visits" onclick="maintNotifiedAskMany('Gulfshore')">✓ Jordan told</button>
    <button class="btn" id="msEmail" onclick="emailWettechList()">✉️ Email Tom the pump list</button>
  </div>
  <div class="note" style="margin-bottom:8px">Every pump (Wettech) and lake (Gulfshore) maintenance visit due in the month from the Accounts tab, and whether the subcontractor has been told. Lakes count as told once the month's diver list is emailed.</div>
  <div class="scroll" style="max-height:45vh"><table class="t"><thead><tr><th style="width:28px"><input type="checkbox" id="msAll" title="Select every account shown that isn't fully told yet" onchange="msSelectAll(this.checked)"></th><th>Account</th><th>Client approved</th><th>Justin<div class="note" style="font-weight:400">Wettech pumps</div></th><th>Jordan<div class="note" style="font-weight:400">Gulfshore diving</div></th></tr></thead><tbody id="msBody"></tbody></table></div>
  </details>
</div>

<!-- SCADA -->
<div class="panel hide" id="p-scada">
  <div class="toolbar"><div class="note">The SCADA sheet: <b>Renewal date</b> is when the next renewal is due; each year holds our invoice # or a note. When one's renewed, <b>Renewed…</b> records it and moves the date on a year. Due within {{ scada_days }} days: a to-do to draft the client's quote (Draft quote makes it in Jobber at their price; a renewal quote already in Jobber counts; complimentary ones are just a reminder). <b>Renewal quote</b> shows this renewal's quote and where it stands; only this year's column shows - <b>all years</b> opens the rest. Each Jobber sync fills in the year's invoice # from the SCADA renewal invoices it finds.</div><div class="sp"></div>
    <select id="scShow" onchange="loadScada()"><option value="active">On SCADA</option><option value="all">All, incl. stopped</option></select>
    <button class="btn" onclick="scadaEdit(0)">＋ Add client</button></div>
  <div class="scroll"><table class="t" id="scadaTable"></table></div>
</div>

<!-- ACCOUNTS -->
<div class="panel hide" id="p-accounts">
  <div class="toolbar">
    <span id="acInfo" class="note"></span><div class="sp"></div>
    <input type="text" id="acSearch" placeholder="Find an account…" oninput="drawAccounts()" style="width:180px">
    <select id="acShow" onchange="drawAccounts()"><option value="active">Active</option><option value="due">Due this month</option><option value="pump">Has pump maintenance</option><option value="lake">Has filter cleaning</option><option value="scada">Has SCADA</option><option value="no_pump">No pump maintenance</option><option value="no_filter">No filter cleaning</option><option value="no_scada">No SCADA</option><option value="no_irrigation">We don't manage irrigation</option><option value="contract">Has a maintenance contract</option><option value="former">Former</option><option value="">All</option></select>
    <select id="acSort" onchange="try{localStorage.setItem('acSort', this.value)}catch(e){};drawAccounts()" title="Sort the accounts"><option value="name">Sort: Name A-Z</option><option value="type">Sort: Contract type</option><option value="amount">Sort: Contract $ (high to low)</option></select>
    <button class="btn" onclick="maintEdit(0)">＋ Pump account</button>
    <button class="btn" onclick="editDiveSite()">＋ Lake site</button>
    <button class="btn" title="Look in Jobber for each account's irrigation maintenance job (it's also checked once a day)" onclick="irrigationCheck()">↻ Check Jobber for irrigation</button>
    <button class="btn" title="An Excel sheet of the accounts shown - the filter, Show chips, search and sort you have now" onclick="accountsSheet()">⬇ Download sheet</button>
  </div>
  <div style="margin-bottom:10px;display:flex;gap:6px;align-items:center;flex-wrap:wrap"><b class="note">Show:</b><span id="svcPicks"></span>
    <span class="note">click to show only accounts with what's ticked &nbsp;·&nbsp; in the list, <span class="svc on" style="cursor:default">green</span> = they have it, <span class="svc off" style="cursor:default">＋ grey</span> = they don't - click it to draft a quote in Jobber</span></div>
  <div class="scroll"><table class="t"><thead><tr><th>Account</th><th>Pump · Filter · SCADA · Irrigation</th><th>Next due</th><th>Where</th></tr></thead><tbody id="acBody"></tbody></table></div>
  <details style="margin-top:22px"><summary style="cursor:pointer;font-size:14px;font-weight:600">Monthly email to the diver</summary>
  <div class="toolbar"><span id="diveInfo" class="note"></span><div class="sp"></div>
    <button class="btn" onclick="diverTodo(diveMonth())">Email ready to copy</button>
    <a class="btn" id="diveDocx" href="#">⬇ Word list</a>
    <button class="btn" onclick="sendDiveEmail()" title="Send it from the PO mailbox">Send from PO@…</button></div>
  <div class="fields" id="diveSettings"></div>
  <div class="scroll" style="max-height:30vh;margin-top:10px"><table class="t"><thead><tr><th>Month</th><th>Sent</th><th>By</th><th>To</th><th class="num">Sites</th><th>Result</th></tr></thead><tbody id="diveSent"></tbody></table></div>
  </details>
  <details style="margin-top:14px"><summary style="cursor:pointer;font-size:14px;font-weight:600">Site names (how vendors write a site)</summary>
  <div class="toolbar"><button class="btn" onclick="siteNameAdd()">＋ Site name</button></div>
  <div class="note" style="margin-bottom:8px">How a site is written on the vendors' paperwork, so quotes and reports go to the right Jobber client and job - e.g. "Carlisle" is on the Greenscapes account. Add one from <b>Draft quote</b> (tick "Remember").</div>
  <div class="scroll" style="max-height:40vh"><table class="t"><thead><tr><th>Written as</th><th>Area</th><th>Jobber client</th><th>Property</th><th>Note</th><th></th></tr></thead><tbody id="siteNamesBody"></tbody></table></div>
  </details>
</div>

<!-- REPORTS -->
<div class="panel hide" id="p-bills">
  <div class="toolbar">
    <button class="btn p" id="billsGo" onclick="billsEmail()">✉ Email Christian</button>
    <button class="btn" id="billsPaid" onclick="billsMarkPaid()">✓ Mark selected paid</button>
    <button class="btn s" onclick="billsAll(null, null, true)">Select all</button><button class="btn s" onclick="billsAll(null, null, false)">Select none</button>
    <span class="note">Shift-click to tick a run of bills</span>
    <div class="sp"></div><span class="note" id="billsInfo"></span>
  </div>
  <div class="note" style="margin-bottom:10px">Every vendor bill not paid yet, by vendor. A bill can be paid once we've invoiced the client for it; ticked ones go in one email to Christian, with the bills attached. Mark each paid when it is.</div>
  <div id="billsList"><div class="empty">Loading…</div></div>
  <div id="billsPaidList" style="margin-top:16px"></div>
</div>
<div class="panel hide" id="p-vquotes">
  <div class="toolbar">
    <select id="vqShow" onchange="loadVQuotes()">
      <option value="open">Open (to quote, draft, with the client)</option><option value="to_quote">Our quote not made</option>
      <option value="draft">Draft - to send</option><option value="sent">With the client</option>
      <option value="approved">Approved</option><option value="done">Done</option><option value="cancelled">Cancelled</option>
      <option value="all">All</option></select>
    <select id="vqSort" onchange="loadVQuotes()" title="Sort"><option value="az">Site A-Z</option><option value="new">Newest first</option><option value="vendor">Vendor A-Z</option></select>
    <input type="text" id="vqSearch" placeholder="Search vendor, quote #, site, work…" oninput="clearTimeout(window._vq);window._vq=setTimeout(loadVQuotes,300)" style="width:240px">
    <div class="sp"></div><span class="note" id="vqInfo"></span>
  </div>
  <div class="note" style="margin-bottom:10px">Every vendor quote, with our Jobber quote for it and where it stands.</div>
  <div id="vqList"><div class="empty">Loading…</div></div>
</div>
<div class="panel hide" id="p-vinvoices">
  <div class="toolbar">
    <select id="viShow" onchange="loadVInvoices()">
      <option value="all">All</option><option value="unpaid">Not paid yet</option><option value="not_invoiced">Not invoiced to the client</option>
      <option value="invoiced">Invoiced, not paid</option><option value="paid">Paid</option><option value="cancelled">Cancelled</option></select>
    <select id="viSort" onchange="loadVInvoices()" title="Sort"><option value="az">Site A-Z</option><option value="new">Newest first</option><option value="vendor">Vendor A-Z</option></select>
    <input type="text" id="viSearch" placeholder="Search vendor, invoice #, site, work…" oninput="clearTimeout(window._vi);window._vi=setTimeout(loadVInvoices,300)" style="width:240px">
    <div class="sp"></div><span class="note" id="viInfo"></span>
  </div>
  <div class="note" style="margin-bottom:10px">Every vendor invoice on file, with our invoice to the client and whether the vendor is paid.</div>
  <div id="viList"><div class="empty">Loading…</div></div>
</div>
<div class="panel hide" id="p-reports">
  <div class="toolbar">
    <select id="repYear" onchange="loadReports()"></select>
    <input type="text" id="repSearch" placeholder="Find a site…" oninput="clearTimeout(window._rq);window._rq=setTimeout(loadReports,300)" style="width:200px">
    <div class="sp"></div><span class="note" id="repInfo"></span>
    <a class="btn s" href="/pumps/api/reports/archive.zip" title="Every pump report ever, in one zip: a folder per month, plus a spreadsheet index">⬇ Download all reports</a>
  </div>
  <div class="note" style="margin-bottom:10px">Every service report from Wettech, rebranded (our letterhead, no Wettech details, no technician, not "Stahlman England" as the customer), by month. Each one goes on the site's pump job in Jobber as "&lt;Month&gt; Pump Report" with the PDF, named as Wettech sent it.</div>
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
  // The app restarting for an update (a minute or so) drops requests: say so
  // instead of leaving the button stuck (Honda, Oct 2026: "nothing happens").
  const down = 'The app is restarting for an update - nothing was saved. Try again in a minute.';
  let r;
  try { r = await fetch('/pumps/api' + path, opts); } catch (e) { return {success: false, error: down, _status: 0}; }
  let j = {}; try { j = await r.json(); } catch(e) { j = {success:false, error: [502, 503, 504].includes(r.status) ? down : 'Server error ' + r.status}; }
  j._status = r.status;
  return j;
}
function toast(msg, bad){ const d = document.createElement('div'); d.textContent = msg; d.className = 'toast' + (bad ? ' bad' : ''); document.body.appendChild(d); setTimeout(() => d.remove(), bad ? 6000 : 3000); }
function catChip(c){ const m = {scada:'v', diver:'b', filter:'b', maintenance:'g', install:'a'}; return `<span class="chip ${m[c]||''}">${esc(c)}</span>`; }
// How long a job has waited on the vendor's quote: since it was opened.
function quoteWait(c){
  const since = d10(c.opened_on || c.created_at); if (!since) return '';
  const n = Math.round((new Date(todayIso() + 'T12:00:00') - new Date(since + 'T12:00:00')) / 864e5);
  return n < 1 ? 'since today' : n === 1 ? '1 day' : n + ' days';
}
// What a job is waiting on, in plain words, from the first step not done.
function stageText(c){
  const v = c.vendor || 'Wettech', st = c.steps || {}, w = quoteWait(c);
  const hasBill = c.vendor_bill_amount != null || c.vendor_bill_total != null || !!(st.vendor_bill || {}).at;
  if (c.stage === 'vendor_quote' && hasBill) return `Bill in · waiting on ${v}'s quote` + (w ? ' · ' + w : '');
  // Approved: the quote goes to the vendor, then we wait on them for a date
  // (and on their parts, when the quote said weeks).
  const ch = c.chase || {};
  // The vendor has it lined up (parts in or ordered, booked, under way): what's
  // left is the work itself, not a date (Magnolia Cove, Oct 2026).
  const js = c.job_status || {};
  if (c.stage === 'scheduled' && ['parts_ordered', 'scheduled', 'in_progress'].includes(js.kind))
    return `Waiting on ${ch.who || v} to complete the work` + (js.on || c.scheduled_for ? ' · ' + niceDay(js.on || c.scheduled_for) : '');
  if (c.stage === 'scheduled' && ch.parts_wait) {
    if (!ch.last_at) return `Approved · send the quote to ${ch.who || v}`;
    if (!ch.expect_by) return (ch.parts ? `Waiting on ${v} parts (${ch.parts}) · ` : '') + `Waiting on ${ch.who || v}: when it'll be scheduled`;
  }
  return ({
    assessment: `Waiting on ${v} to assess` + ((st.assessment || {}).due ? ' · ' + st.assessment.due : '') + (w ? ' · ' + w : ''),
    vendor_quote: `Waiting on quote from ${v}` + (w ? ' · ' + w : ''),
    client_quote: 'Send our quote to the client',
    client_approved: 'Waiting on client approval',
    scheduled: `Schedule with ${v}`,
    work_done: `Waiting on ${v} to do the work` + (c.scheduled_for ? ' · ' + c.scheduled_for : ''),
    vendor_bill: `Waiting on bill from ${v}`,
    bill_checked: 'Check the bill against the quote',
    // Gulfshore's work goes on the client's pump invoice - nothing of its own to draft (Oct 2026).
    invoice_drafted: /^gulfshore/i.test(c.vendor || '') ? 'Waiting for the pump invoice (Gulfshore is billed with it)' : 'Draft our invoice in Jobber',
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
  else if (name === 'accounts') loadAccounts(); else if (name === 'reports') loadReports(); else if (name === 'bills') loadBills(); else if (name === 'vquotes') loadVQuotes(); else if (name === 'vinvoices') loadVInvoices();
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
  return `<div class="row"><div class="main"><div class="tt"><label style="display:flex;gap:8px;align-items:flex-start;cursor:pointer"><input type="checkbox" onclick="event.preventDefault();askDone(event, () => todoDone(${t.id}, true, event))" style="margin-top:3px"><span>${esc(t.title)}</span></label></div>
      ${t.detail || (t.kind === 'manual' && t.due_on) ? `<div class="sub" style="margin-left:24px">${t.kind === 'manual' && t.due_on ? `<b class="${t.due_on < todayIso() ? 'bad' : 'warn'}">due ${esc(niceDay(t.due_on))}</b>${t.detail ? ' · ' : ''}` : ''}${esc(t.detail || '')}</div>` : ''}
      ${t.kind === 'approved_quote' ? `<div style="margin:6px 0 0 24px;display:flex;gap:6px;flex-wrap:wrap">${t.link.case_id ? `<button class="btn s p" title="Signs it and downloads it - send it yourself, then click I already sent it" onclick="signedQuote(${t.link.case_id}, true)">⬇ Download signed quote</button><button class="btn s" title="The email to send with it - to copy into Outlook" onclick="signedQuoteMessage(${t.link.case_id})">✉ Message to ${esc((t.title.match(/send it to (\S+)/) || [])[1] || 'the vendor')}</button><button class="btn s" title="Opens the quote already signed" onclick="signedQuote(${t.link.case_id}, false)">See it signed</button><button class="btn s" onclick="quoteSent(${t.link.case_id})">I already sent it</button>` : t.link.doc_id ? `<a class="btn s" href="/pumps/api/docs/${t.link.doc_id}/file?version=original" target="_blank" rel="noopener">View quote</a>` : ''}${t.link.case_id ? `<button class="btn s" onclick="openCase(${t.link.case_id})">Open job</button>` : ''}</div>` : ''}
      ${t.kind !== 'approved_quote' && (t.link.uri || t.link.case_id) ? `<div style="margin:6px 0 0 24px;display:flex;gap:6px;flex-wrap:wrap">${(t.link.uris || []).length > 1 ? t.link.uris.map(u => `<a class="btn s" href="${esc(u.uri)}" target="_blank" rel="noopener">Open ${esc(u.label)} ↗</a>`).join('') + `<button class="btn s" onclick='openAll(${JSON.stringify(t.link.uris.map(u => u.uri)).replace(/'/g, "&#39;")})'>Open both ↗</button>` : t.link.uri ? `<a class="btn s" href="${esc(t.link.uri)}" target="_blank" rel="noopener">${esc(t.link.label || 'Open in Jobber')} ↗</a>` : ''}${t.link.case_id ? `<button class="btn s" onclick="openCase(${t.link.case_id})">Open job</button>` : ''}${t.link.scada_id ? `<button class="btn s" onclick="showTab('scada')">SCADA</button>` : ''}</div>` : ''}
      ${t.link.close_job ? `<div style="margin:6px 0 0 24px;display:flex;gap:6px;flex-wrap:wrap"><button class="btn s p" onclick="closeJobberJob('${esc(t.link.close_job)}', this)">Close job in Jobber</button></div>` : ''}
      ${t.link.draft_scada ? `<div style="margin:6px 0 0 24px;display:flex;gap:6px;flex-wrap:wrap"><button class="btn s p" onclick="draftScadaQuote(${t.link.scada_id}, this)">Draft quote in Jobber</button></div>` : ''}
      ${(t.key || '').startsWith('gulfshore-unbilled:') && t.link.case_id ? `<div style="margin:6px 0 0 24px;display:flex;gap:6px;flex-wrap:wrap"><button class="btn s p" title="Billed already - type our Jobber invoice number" onclick="linkInvoice(${t.link.case_id})">🔗 Link our invoice</button><button class="btn s" title="Billed through a contract - no invoice to link" onclick="billsPayOk([${t.link.case_id}])">OK to pay now</button></div>` : ''}
      ${t.kind === 'diver_email' ? `<div style="margin:6px 0 0 24px;display:flex;gap:6px;flex-wrap:wrap"><button class="btn s p" onclick="diverTodo('${esc(t.link.month || '')}')">Email ready - copy &amp; attach</button><a class="btn s" href="/pumps/api/dives/docx?month=${encodeURIComponent(t.link.month || '')}">⬇ Word list</a></div>` : ''}</div>
      <button class="btn s" title="Edit" onclick='todoEdit(${JSON.stringify({id: t.id, title: t.title, detail: t.detail || "", due_on: t.due_on || ""}).replace(/'/g, "&#39;")})'>✎</button>
      ${t.kind === 'manual' ? `<button class="btn s" title="Delete from my to do list" onclick="todoDelete(${t.id})">✕</button>` : `<button class="btn s" title="Delete from my to do list" onclick="todoHide('${esc(t.todo_key)}')">✕</button>`}</div>`;
}
// ── undo ──────────────────────────────────────────────
async function showUndo(){
  const j = await api('/undo'); if (!j.success) { toast(j.error, true); return; }
  const rows = j.actions.map(a => `<div style="display:flex;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line,#ddd)"><div style="flex:1"><b>${esc(a.label)}</b><div class="note">${esc(a.created_at.slice(5,16))} · ${esc(a.actor || '')}${a.external ? ' · ' + esc(a.external) : ''}</div></div><button class="btn s" onclick="undoAction(${a.id})">Undo</button></div>`).join('');
  openModal('Undo a recent change', rows ? `<p class="note">Changes from the last 24 hours, newest first. Undo puts the app back as it was before that click.</p>${rows}` : '<div class="empty">Nothing to undo from the last 24 hours.</div>');
}
// Undo one change. When a later change touched the same thing, ask to undo
// that too. Then whatever is open (a job, an account) shows the result.
async function runUndo(id){
  let r = await api('/undo/' + id, {method:'POST', body:{}});
  if (!r.success && r.blocked_by) {
    if (!confirm('A later change touched the same thing:\n\n• ' + r.blocked_by.join('\n• ') + '\n\nUndo that too?')) return null;
    r = await api('/undo/' + id, {method:'POST', body:{also_later: true}});
  }
  if (!r.success) { toast(r.error, true); return null; }
  toast('Undone: ' + r.label + (r.outside ? ' - ' + r.outside : ''));
  loadToday();
  const dr = document.getElementById('drawer');
  if (!document.getElementById('drawerWrap').classList.contains('hide')) { if (dr.dataset.account) openAccount(dr.dataset.account); else if (curCase) openCase(curCase.id); }
  showTab(curTab);
  return r;
}
// Ctrl+Z / ⌘Z (not while typing in a box): undo your own last change.
let undoBusy = false;
async function undoLast(){
  if (undoBusy) return; undoBusy = true;
  try {
    const j = await api('/undo'); if (!j.success) { toast(j.error, true); return; }
    const a = j.actions.find(x => !j.me || x.actor === j.me);
    if (!a) { toast('Nothing of yours to undo from the last 24 hours.'); return; }
    await runUndo(a.id);
  } finally { undoBusy = false; }
}
document.addEventListener('keydown', e => {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey || e.key.toLowerCase() !== 'z') return;
  const t = e.target, tag = (t.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || t.isContentEditable) return;   // the box's own undo
  e.preventDefault(); undoLast();
});
async function undoAction(id){
  if (await runUndo(id)) showUndo();
}
function openAll(uris){ const blocked = uris.filter(u => { const w = window.open(u, '_blank'); if (w) w.opener = null; return !w; }).length; if (blocked) toast('Your browser blocked a tab - allow pop-ups for this site, or use the buttons one at a time.', true); }
async function followUpTomorrow(id){
  const j = await api('/cases/' + id + '/follow_up_tomorrow', {method:'POST'});
  if (!j.success) { toast(j.error, true); return; }
  toast('Postponed - back on the list ' + niceDay(j.check_on) + '.'); loadToday();
}
async function followUpOff(id){
  if (!confirm("No follow-up needed at this step?\n\nIt comes off the list until the job moves on.")) return;
  const j = await api('/cases/' + id + '/follow_up_off', {method:'POST'});
  if (!j.success) { toast(j.error, true); return; } toast('No follow-up needed - off the list.'); loadToday();
}
async function stepDone(caseId, step, ev){
  const j = await api('/cases/' + caseId, {method:'PATCH', body:{steps: {[step]: new Date().toISOString().slice(0, 10)}}});
  if (!j.success) { toast(j.error || 'Not saved', true); return; } celebrate(ev); loadToday();
}
async function reportDone(id, ev){
  const j = await api('/docs/' + id + '/report_done', {method:'POST'});
  if (!j.success) { toast(j.error, true); return; } celebrate(ev); loadToday();
}
async function todoDone(id, done, ev){ const j = await api('/todos/' + id + '/done', {method:'POST', body:{done}}); if (!j.success) toast(j.error, true); else { if (done) celebrate(ev); else toast('Reopened'); loadToday(); } }
// "Mark done?" right where you clicked: a second click to be sure.
function askDone(ev, go){
  ev.stopPropagation();
  document.querySelectorAll('.askdone').forEach(x => x.remove());
  const b = document.createElement('div'); b.className = 'askdone';
  const x = Math.min(ev.clientX, window.innerWidth - 190), y = Math.min(ev.clientY + 12, window.innerHeight - 60);
  b.style.cssText = `position:fixed;left:${Math.max(8, x - 80)}px;top:${y}px;z-index:9999;background:var(--card,#fff);color:var(--text,#111);border:1px solid var(--border,#ccc);border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);padding:8px 10px;display:flex;gap:6px;align-items:center;font-size:13px`;
  b.innerHTML = '<b>Mark done?</b> <button class="btn s p">✓ Yes</button><button class="btn s">Cancel</button>';
  const [yes, no] = b.querySelectorAll('button');
  const close = () => { b.remove(); document.removeEventListener('mousedown', outside, true); };
  const outside = e => { if (!b.contains(e.target)) close(); };
  yes.onclick = e => { e.stopPropagation(); close(); go(); };
  no.onclick = e => { e.stopPropagation(); close(); };
  document.body.appendChild(b); setTimeout(() => document.addEventListener('mousedown', outside, true), 0);
}
// A little celebration where the to-do was ticked.
function celebrate(ev){
  const x = ev && ev.clientX != null ? ev.clientX : window.innerWidth / 2, y = ev && ev.clientY != null ? ev.clientY : window.innerHeight / 3;
  const colors = ['#1d4ed8', '#16a34a', '#f59e0b', '#db2777', '#06b6d4', '#a855f7'];
  for (let i = 0; i < 28; i++) {
    const p = document.createElement('div'), a = Math.random() * Math.PI * 2, d = 50 + Math.random() * 90;
    p.textContent = i % 7 === 0 ? '🎉' : '';
    p.style.cssText = `position:fixed;left:${x}px;top:${y}px;width:7px;height:10px;border-radius:2px;background:${i % 7 === 0 ? 'none' : colors[i % colors.length]};z-index:10000;pointer-events:none;font-size:16px;transition:transform .9s cubic-bezier(.2,.7,.3,1),opacity .9s ease-in`;
    document.body.appendChild(p);
    requestAnimationFrame(() => { p.style.transform = `translate(${Math.cos(a) * d}px, ${Math.sin(a) * d + 40}px) rotate(${Math.random() * 540}deg)`; p.style.opacity = '0'; });
    setTimeout(() => p.remove(), 1000);
  }
  toast(['Done! 🎉', 'Nice work! ✅', 'One less thing! 🙌', 'Crushed it! 💪'][Math.floor(Math.random() * 4)]);
}
// Edit a to-do's wording or due date.
function todoEdit(t){
  openModal('Edit to-do', `<div class="fields"><label class="w">What needs doing<input type="text" id="te_title" value="${esc(t.title)}"></label>
    <label class="w">Details<textarea id="te_detail">${esc(t.detail)}</textarea></label>
    <label>Due<input type="date" id="te_due" value="${esc(t.due_on)}"></label></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="todoEditSave(${t.id})">Save</button>`);
}
async function todoEditSave(id){
  const v = x => document.getElementById(x).value;
  const j = await api('/todos/' + id + '/edit', {method:'POST', body:{title: v('te_title').trim(), detail: v('te_detail'), due_on: v('te_due')}});
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); toast('Saved'); loadToday();
  const dr = document.getElementById('drawer'); if (dr.dataset.account && !document.getElementById('drawerWrap').classList.contains('hide')) openAccount(dr.dataset.account);
}
// Explain it in your own words; the app rewords it as a short to-do to check first.
async function todoWrite(){
  const el = document.getElementById('todoNew'), text = el.value.trim(); if (!text) return;
  const btn = document.getElementById('todoWriteBtn'); btn.disabled = true; btn.textContent = 'Writing…';
  const j = await api('/todos/reword', {method:'POST', body:{text}});
  btn.disabled = false; btn.textContent = '✨ Write to-do';
  if (!j.success) { toast(j.error, true); return; }
  window._todoText = text;
  const t = j.todo;
  openModal('New to-do', `
    <div class="note">Shortened from what you wrote - change anything before adding it.</div>
    <label class="note">To-do<input type="text" id="tdTitle" value="${esc(t.title)}" style="width:100%"></label>
    <label class="note">Details<textarea id="tdDetail" style="width:100%;min-height:70px;font:inherit">${esc(t.detail)}</textarea></label>
    <label class="note">Due <span class="note">(optional)</span><input type="date" id="tdDue" value="${esc(t.due_on)}"></label>
    <div class="note">You wrote: <i>${esc(text)}</i></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn" onclick="todoAdd(_todoText, '', '')">Use my words</button><button class="btn p" onclick="todoAdd(document.getElementById('tdTitle').value, document.getElementById('tdDetail').value, document.getElementById('tdDue').value)">Add to-do</button>`);
  setTimeout(() => { const i = document.getElementById('tdTitle'); if (i) i.focus(); }, 50);
}
async function todoAdd(title, detail, due_on){
  title = (title || '').trim(); if (!title) { toast('Say what needs doing', true); return; }
  const j = await api('/todos', {method:'POST', body:{title, detail: (detail || '').trim(), due_on: due_on || ''}});
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); toast('Added to your to do list'); loadToday();
}
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
// Jobber's page for an invoice: the link it gave us, else from its id ("gid://Jobber/Invoice/123").
function jobberInvoiceUri(inv){ return jobberUri(inv, 'invoices'); }
function jobberUri(rec, kind){
  if (rec.uri) return rec.uri;
  try { const n = atob(rec.id || '').split('/').pop(); return /^\d+$/.test(n) ? `https://secure.getjobber.com/${kind}/` + n : ''; } catch (e) { return ''; }
}
// Client search boxes search as you type (a moment after the last key), no Search click needed.
function liveSearch(fn){ clearTimeout(window._lsT); window._lsT = setTimeout(() => { const el = document.activeElement; if (el && el.value && el.value.trim().length >= 2) fn(); }, 350); }
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
// Days since anything was done on a job, and what it was; amber after a week.
function lastAction(c){
  const la = c.last_action; if (!la || la.days == null) return '';
  const ago = la.days <= 0 ? 'today' : la.days === 1 ? 'yesterday' : la.days + ' days ago';
  const what = la.detail ? `${la.action} - ${la.detail}` : la.action;
  return `<div class="note" title="${esc((la.by ? la.by + ': ' : '') + what)}">Last action: <b class="${la.days >= 7 ? 'warn' : ''}">${ago}</b>${what ? ' · ' + esc(what.length > 70 ? what.slice(0, 70) + '…' : what) : ''}</div>`;
}
function caseTitle(c){ return `<span title="${esc(c.title || '')}">${esc(c.short_title || c.title || c.client_name || 'Item ' + c.id)}</span>`; }
// The latest status update on a job ("Parts ordered · 2 weeks out · parts due Oct 27").
function statusLine(c){ const st = c.job_status || {}; if (!st.kind) return ''; return `<span style="font-weight:700" title="${esc((st.by || '') + ' ' + (st.at || ''))}">📌 <b>${esc(st.label)}</b>${st.text ? ' - ' + esc(st.text) : ''}${st.on ? ' · ' + ({parts_ordered: 'parts due', waiting_vendor: 'expected', scheduled: 'for'}[st.kind] || 'on') + ' ' + esc(niceDay(st.on)) : ''} <span class="note">(${esc(niceDay(d10(st.at)))})</span></span>`; }
function caseSub(c, extra){ return esc([c.client_name, c.site].filter(Boolean).join(' · ')) + (c.po_number ? ' · PO ' + esc(c.po_number) : '') + jobberNo(c) + (extra ? ' · ' + extra : '') + (c.idle_days >= 7 ? ` · <b class="warn">${c.idle_days}d idle</b>` : '') + (statusLine(c) ? '<br>' + statusLine(c) : ''); }
async function loadToday(){
  const j = await api('/summary');
  checkVersion(j.version);
  const el = document.getElementById('todoList');
  if (!j.success) { el.innerHTML = `<div class="empty">${esc(j.error)}</div>`; return; }
  const q = j.queue;
  setCount('n-jobs', q.open_count, false);
  setCount('n-scada', q.scada_attention.length, q.scada_attention.some(s => s.state === 'overdue'));
  setCount('n-bills', q.bills_to_pay_count || 0, false);
  updateScanInfo(j.scan);
  const open = c => `openCase(${c.id})`;
  // ✓ Done on a to-do ticks that step on its job, so the watchlist moves on with it.
  const stepBtn = (c, step, label) => `<button class="btn s" title="Done - tick it on the job" onclick="askDone(event, () => stepDone(${c.id}, '${step}', event))">✓ ${label || 'Done'}</button>`;
  // A follow-up that's sorted: tick the step the job was waiting on (Huntington: it's scheduled).
  const nextBtn = c => { const l = {assessment: 'Visit done', vendor_quote: 'Quote in', scheduled: 'Scheduled', work_done: 'Work done', vendor_bill: 'Bill in'}[c.stage];
    return l ? stepBtn(c, c.stage, l) : ''; };
  // The same, as a tick box in front of the title, like your own to-dos.
  const nextBox = c => { const l = {assessment: 'visit done', vendor_quote: 'quote in', scheduled: 'scheduled', work_done: 'work done', vendor_bill: 'bill in'}[c.stage];
    return l ? `<input type="checkbox" title="Tick: ${l}" style="margin-right:6px" onclick="event.preventDefault();event.stopPropagation();askDone(event, () => stepDone(${c.id}, '${c.stage}', event))">` : ''; };
  // The drafted invoice in Jobber, to look over and send from there.
  const invoiceLink = c => { const inv = (c.jobber || {}).invoice || {}; const uri = jobberInvoiceUri(inv);
    return (uri ? `<a class="btn s p" target="_blank" rel="noopener" href="${esc(uri)}">Open invoice${inv.number ? ' #' + esc(inv.number) : ''} in Jobber ↗</a>` : '')
      + ((c.jobber || {}).site_invoices || []).filter(x => x.uri).map(x => `<a class="btn s p" target="_blank" rel="noopener" href="${esc(x.uri)}">Open ${esc(x.site || '')} invoice #${esc(x.number)} ↗</a>`).join(''); };
  // Our quote in Jobber, to look over and send from there.
  const quoteLink = c => { const q = (c.jobber || {}).quote || {}; const uri = jobberUri(q, 'quotes');
    return uri ? `<a class="btn s p" target="_blank" rel="noopener" href="${esc(uri)}">Open quote${q.number ? ' #' + esc(q.number) : ''} in Jobber ↗</a>` : ''; };
  const urgent = [], todo = [], waiting = [];
  q.issues.forEach(i => (i.kind === 'no_quote' ? waiting : urgent).push(todoItem(i.kind === 'no_quote' ? 'Quote after bill' : 'Fix', i.kind === 'no_quote' ? '' : 'r', esc(i.title || i.client_name || 'Item ' + i.case_id), esc(i.message), `openCase(${i.case_id})`,
    (i.kind === 'no_quote' ? `<button class="btn s p" onclick="billAnyway(${i.id})">Bill it +30%</button>` : '') + `<button class="btn s" onclick="resolveIssue(${i.id})">Resolved</button>`, i.todo_key)));
  // One to-do for every bill that can be paid (Oct 2026): preview the one email to Christian from here.
  if (q.bills_to_pay_count) urgent.push(todoItem('Pay vendors', 'r', `${q.bills_to_pay_count} vendor bill${q.bills_to_pay_count > 1 ? 's' : ''} can be paid`,
    'Email Christian to pay them - sending marks them paid', "showTab('bills')",
    `<button class="btn s p" onclick="billsEmail([])">✉ Preview email to Christian</button><button class="btn s" onclick="showTab('bills')">See the bills</button>`));
  q.scada_attention.filter(s => s.state === 'overdue').forEach(s => urgent.push(todoItem('SCADA overdue', 'r', esc(s.client_name) + (s.site ? ' · ' + esc(s.site) : ''), 'Renewal overdue since ' + esc(s.next_due_on) + (s.state_note ? ' · ' + esc(s.state_note) : '') + followUp(s.follow_up), "showTab('scada')", '', s.todo_key)));
  q.bills_to_draft.forEach(d => { const ip = (d.jobber || {}).invoice_pending || {}; todo.push(todoItem('Draft invoice', 'a', esc(d.client_name || d.file_name), `${d.account_note ? '<b class="warn">📌 ' + esc(d.account_note) + '</b><br>' : ''}${esc(d.vendor)} bill #${esc(d.doc_number)} · ${money(d.total)}${d.bill_kind ? ' · <b>' + esc(d.bill_kind) + '</b>' : ''}${ip.reason ? ' · <b class="warn">' + esc(ip.reason) + '</b>' : ''}`, `openCase(${d.case_id})`,
    `<button class="btn s p" onclick="draftInvoice(${d.id})">Draft invoice</button>${d.case_id ? `<button class="btn s" title="Already drafted in Jobber - tick it on the job" onclick="askDone(event, () => stepDone(${d.case_id}, 'invoice_drafted', event))">✓ Done</button>` : ''}<a class="btn s" target="_blank" rel="noopener" href="/pumps/api/docs/${d.id}/file?version=original">See vendor invoice</a>${(ip.possible_duplicate || {}).uri ? `<a class="btn s" target="_blank" rel="noopener" href="${esc(ip.possible_duplicate.uri)}">Open #${esc(ip.possible_duplicate.number)} ↗</a>` : ''}`, d.todo_key)); });
  // A client approved one of our quotes in Jobber and no job here follows it
  // (the sync picks most up by itself). Only approved quotes - other new work
  // in Jobber stays off this list (#546).
  (q.new_jobber_requests || []).filter(it => it.kind === 'quote' && it.status === 'approved').forEach(it => { const what = 'Approved quote';
    todo.push(todoItem('Approved - not tracked', 'v', esc((it.number ? '#' + it.number + ' ' : '') + (it.title || it.client_name || what)),
      `${what} · ${esc([it.client_name, it.property_label].filter(Boolean).join(' · '))}${it.total != null ? ' · ' + money(it.total) : ''}`,
      `window.open('${esc(it.web_uri || '')}', '_blank')`,
      `<button class="btn s p" onclick="jobberAct('${esc(it.jobber_id)}', 'track')">＋ Track</button><button class="btn s" title="Not pump work - don't show it again" onclick="jobberAct('${esc(it.jobber_id)}', 'ignore')">Not ours</button>`, it.todo_key)); });
  q.quotes_to_draft.forEach(d => todo.push(todoItem('Draft quote', 'a', esc(d.client_name || d.file_name), `${esc(d.vendor)} quote ${d.doc_number ? '#' + esc(d.doc_number) + ' ' : ''}· ${money(d.subtotal ?? d.total)}${((d.jobber || {}).quote_pending || {}).reason ? ' · <b class="warn">' + esc(d.jobber.quote_pending.reason) + '</b>' : ''}`, `openCase(${d.case_id})`,
    `<button class="btn s p" onclick="draftQuote(${d.id})">Draft quote</button>${(((d.jobber || {}).quote_pending || {}).possible_duplicate || {}).number ? `<button class="btn s" onclick="linkQuoteNumber(${d.case_id}, '${esc(d.jobber.quote_pending.possible_duplicate.number)}')">Link #${esc(d.jobber.quote_pending.possible_duplicate.number)}</button>` : ''}`, d.todo_key)));
  q.to_quote_client.forEach(c => todo.push(todoItem('Send quote', 'a', caseTitle(c), caseSub(c, 'send our quote to the client in Jobber - this goes away by itself once Jobber shows it sent') + followUp(c.follow_up), open(c), quoteLink(c) + stepBtn(c, 'client_quote'), c.todo_key)));
  q.needs_scheduling.forEach(c => todo.push(todoItem('Schedule', 'a', caseTitle(c), caseSub(c, 'client approved - get it on ' + esc(c.vendor || 'Wettech') + "'s calendar" + (c.scheduled_for ? ' · for ' + esc(c.scheduled_for) : '')) + chaseLine(c), open(c),
    (c.chase ? `<button class="btn s p" onclick="event.stopPropagation();logFollow(${c.id})">📞 Log follow-up</button>` : '') + stepBtn(c, 'scheduled'), c.todo_key)));
  // Chase the vendor: jobs to get scheduled / done, and quotes, where nobody has heard back.
  (q.vendor_follow_ups || []).forEach(c => { const ch = c.chase, late = ch.expect_by && ch.expect_by < todayIso();
    todo.push(todoItem('Follow up · ' + (ch.parts_wait ? 'parts' : ch.phase === 'job' ? 'job' : 'quote'), late ? 'r' : 'a', nextBox(c) + caseTitle(c), caseSub(c, esc(stageText(c))) + chaseLine(c),
      open(c), `<button class="btn s p" onclick="event.stopPropagation();logFollow(${c.id})">📞 Log follow-up</button><button class="btn s" onclick="event.stopPropagation();vendorEmail(${c.id})">✉ Email</button><button class="btn s" title="Postpone - back on the list next working day" onclick="event.stopPropagation();followUpTomorrow(${c.id})">⏭ Tomorrow</button>` + nextBtn(c) + `<button class="btn s" title="No follow-up needed at this step - off the list until the job moves on" onclick="event.stopPropagation();followUpOff(${c.id})">Not needed</button>`, c.todo_key)); });
  q.ready_to_close.forEach(c => todo.push(todoItem('Send invoice', 'a', caseTitle(c), caseSub(c, 'send the invoice from Jobber' + (c.sei_invoice_number ? ' · #' + esc(c.sei_invoice_number) : '')) + followUp(c.follow_up), open(c), invoiceLink(c) + stepBtn(c, 'closed'), c.todo_key)));
  q.reports_to_log.forEach(d => todo.push(todoItem('Log report', 'b', esc(d.client_name || d.file_name), `${esc((d.report_fields||{}).title || 'Report')} · ${esc(d.doc_date)}${((d.jobber || {}).note_pending || {}).reason ? '<br><b class="warn">Not logged by itself: ' + esc(d.jobber.note_pending.reason) + '</b>' : ''}`, d.case_id ? `openCase(${d.case_id})` : `openDoc(${d.id})`,
    `<button class="btn s" onclick="logReport(${d.id})">Log in Jobber</button><button class="btn s" title="Already in Jobber - tick it on the job" onclick="askDone(event, () => reportDone(${d.id}, event))">✓ Done</button>`, d.todo_key)));
  q.review_docs.forEach(d => todo.push(todoItem('Look at', 'b', esc(d.client_name || d.file_name), esc(d.review_reason || 'Not filed yet') + ' · ' + esc(d.kind || 'document'), `openDoc(${d.id})`, '', d.todo_key)));
  q.scada_attention.filter(s => s.state !== 'overdue').forEach(s => todo.push(todoItem('SCADA due', 'v', esc(s.client_name) + (s.site ? ' · ' + esc(s.site) : ''), 'Renewal due ' + esc(s.next_due_on) + (s.state_note ? ' · ' + esc(s.state_note) : '') + followUp(s.follow_up), "showTab('scada')", '', s.todo_key)));
  // Jobs waiting on the vendor or the client are kept an eye on in the Job Watchlist
  // (Show: Waiting on others) - the to do list is for today's actions (Oct 2026).
  (q.waiting_visits || []).forEach(t => { const l = t.link || {}, left = (l.vendors || []).filter(x => !(l.reported || []).includes(x));
    waiting.push(todoItem('Maintenance visit', '', esc(l.account || t.title), `client approved ${esc(l.since || '')} · waiting on ${esc(left.join(' and '))}'s service report${left.length > 1 ? 's' : ''}${(l.reported || []).length ? ' · ✓ ' + esc(l.reported.join(', ')) : ''}`, "showTab('accounts')",
      `<button class="btn s" onclick="askDone(event, () => todoDone(${t.id}, true, event))">✓ Done</button>`, t.todo_key)); });
  const n = urgent.length + todo.length + q.todos.length;
  document.getElementById('sideCount').textContent = n;
  document.getElementById('sideCount').className = 'chip ' + (urgent.length ? 'r' : n ? 'a' : 'g');
  document.getElementById('sideOpen').textContent = `${q.open_count} open jobs`;
  let wasOpen = false; try { wasOpen = localStorage.getItem('pumpsWaitingOpen') === '1'; } catch (e) {}
  el.innerHTML = (urgent.length ? '<div class="grp">Now</div>' + urgent.join('') : '')
    + '<div class="grp">To do</div>' + (todo.join('') + q.todos.map(todoRow).join('') || '<div class="empty">Nothing to do. 🎉</div>')
    + `<div class="row" style="cursor:default;align-items:flex-start"><textarea id="todoNew" rows="2" placeholder="Explain what you need to do, in your own words - the app writes the to-do for you…" style="flex:1;min-width:0;font:inherit;resize:vertical" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();todoWrite()}"></textarea><button class="btn s p" id="todoWriteBtn" onclick="todoWrite()">✨ Write to-do</button></div>`
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
  document.getElementById('drawer').dataset.account = '';
  if (!id) return;
  const j = await api('/cases/' + id);
  if (!j.success) { toast(j.error || 'Not found', true); return; }
  curCase = j.case;
  renderCase();
  document.getElementById('drawerWrap').classList.remove('hide');
  history.replaceState(null, '', '#item-' + id);
}
function closeDrawer(){ document.getElementById('drawerWrap').classList.add('hide'); document.getElementById('drawer').dataset.account = ''; curCase = null; history.replaceState(null, '', '#' + curTab); loadToday(); showTab(curTab); }
const MONEY = new Set(['vendor_quote_amount','vendor_quote_total','vendor_bill_amount','vendor_bill_total','amount']);
// The vendor's invoice and quote, one click from the top of the job (Oct 2026): "See Wettech's invoice".
function vendorDocsHtml(c){
  const docs = (c.docs || []).filter(d => ['bill', 'quote'].includes(d.kind) && d.status !== 'dismissed');
  if (!docs.length) return '<div class="sec"><div class="note" style="padding:8px 12px;border:1px dashed var(--border-2);border-radius:10px">No invoice or quote attached to this job</div></div>';
  const btn = d => { const who = d.vendor || c.vendor || 'the vendor';
    return `<a class="btn ${d.kind === 'bill' ? 'p' : ''}" target="_blank" href="/pumps/api/docs/${d.id}/file">📄 See ${esc(who)}'s ${d.kind === 'bill' ? 'invoice' : 'quote'}${d.doc_number ? ' #' + esc(d.doc_number) : ''}</a>`; };
  // Invoices first, then quotes.
  const inv = (c.jobber || {}).invoice || {}, bills = docs.some(d => d.kind === 'bill');
  const ours = bills ? `<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:8px"><span class="note">Our Jobber invoice #</span>${inv.number ? `<b>${inv.uri ? `<a target="_blank" href="${esc(inv.uri)}">#${esc(inv.number)} ↗</a>` : '#' + esc(inv.number)}</b>` : ''}
    <input type="text" id="csOurs" placeholder="${inv.number ? 'change' : 'e.g. 36995'}" style="width:120px" onkeydown="if(event.key==='Enter')linkOursFromCase(${c.id})"><button class="btn s" onclick="linkOursFromCase(${c.id})">Save</button></div>` : '';
  return `<div class="sec"><div style="display:flex;gap:8px;flex-wrap:wrap">${docs.filter(d => d.kind === 'bill').concat(docs.filter(d => d.kind === 'quote')).map(btn).join('')}</div>${ours}${docs.filter(d => d.kind === 'bill').map(pmMatchHtml).join('')}</div>`;
}
// Pump Manager's match for a vendor invoice: linked, suggested (accept / reject), waiting, or what went wrong.
function pmMatchHtml(d){
  const pm = (d.jobber || {}).pm_match; if (!pm) return '';
  const m = pm.match || {}, what = m.type ? `Jobber ${esc(m.type)} #${esc(m.number)}` : '';
  const why = m.reason ? `<div class="note">${esc(m.reason)}</div>` : '';
  const head = `🤖 Pump Manager${d.doc_number ? ' · invoice #' + esc(d.doc_number) : ''}: `;
  let body;
  if (pm.state === 'linked') body = `<b class="ok">Linked</b> to ${what}${m.confidence ? ' (' + esc(m.confidence) + ' confidence)' : ''}${pm.by ? ' - accepted by ' + esc(pm.by) : ''}${why}`;
  else if (pm.state === 'suggested') body = `<b>Suggested match:</b> ${what} (${esc(m.confidence)} confidence)${why}${pm.error ? `<div class="note bad">${esc(pm.error)}</div>` : ''}
      <div style="display:flex;gap:6px;margin-top:6px"><button class="btn s p" onclick="pmMatch(${d.id}, 'accept')">✓ Accept</button><button class="btn s" onclick="pmMatch(${d.id}, 'reject')">✕ Reject</button></div>`;
  else if (pm.state === 'rejected') body = `suggested ${what} - <span class="note">rejected${pm.by ? ' by ' + esc(pm.by) : ''}</span>`;
  else if (pm.state === 'sent') body = '<span class="note">sent to match - waiting on its answer</span>';
  else body = `<b class="bad">${esc(pm.error || 'Something went wrong')}</b> <button class="btn s" onclick="pmMatch(${d.id}, 'resend')">↻ Send again</button>`;
  return `<div style="margin-top:8px;padding:8px 12px;border:1px solid var(--border);border-radius:10px;background:var(--violet-bg)">${head}${body}</div>`;
}
async function pmMatch(docId, action){
  const j = await api('/docs/' + docId + '/pm_match', {method:'POST', body:{action}});
  if (!j.success) { toast(j.error, true); return; }
  toast(action === 'accept' ? 'Linked.' : action === 'reject' ? 'Rejected.' : 'Sent to Pump Manager again.');
  if (curCase) openCase(curCase.id);
}
function renderCase(){
  const c = curCase, v = c.vendor || 'Wettech';
  const J = c.jobber || {};
  const jl = ['request','job'].filter(k => J[k]).map(k => `<a href="${esc(J[k].uri || '#')}" target="_blank" rel="noopener" class="chip b">Jobber ${k} #${esc(J[k].number || '')} ↗</a>`).join(' ');
  const docs = (c.docs || []).map(d => `<div class="d">${kindChip(d.kind)} <b>${esc(d.file_name)}</b>
      <span class="note">${d.doc_number ? '#' + esc(d.doc_number) + ' · ' : ''}${d.total != null ? money(d.total) : ''} ${esc(d.doc_date)}</span>
      <span style="flex:1"></span>
      <a class="btn s" href="/pumps/api/docs/${d.id}/file" target="_blank">Open</a>
      ${['bill', 'report', 'quote'].includes(d.kind) && !(d.jobber||{}).invoice_id && !(d.jobber||{}).quote_id ? `<button class="btn s" title="Not for this job - take it off and file it again" onclick="refileDoc(${d.id})">Wrong job</button>` : ''}
      ${d.has_branded ? `<a class="btn s" target="_blank" href="/pumps/api/docs/${d.id}/file?version=branded_pdf">SE report PDF</a> <a class="btn s" href="/pumps/api/docs/${d.id}/file?version=branded&download=1">⬇ Word</a>` : ''}
      ${d.kind === 'quote' && !(d.jobber||{}).quote_id ? `<button class="btn s p" onclick="draftQuote(${d.id})">Draft quote in Jobber</button>` : ''}
      ${d.kind === 'quote' && (d.jobber||{}).quote_id ? `<a class="chip g" target="_blank" href="${esc(d.jobber.quote_uri||'#')}">Jobber quote #${esc(d.jobber.quote_number)}</a>` : ''}
      ${d.kind === 'quote' && (d.jobber||{}).approved_at ? `<a class="btn s" href="/pumps/api/docs/${d.id}/file?version=approved&download=1">⬇ Signed quote</a>${d.jobber.signed_sent_at ? ` <span class="chip g" title="${esc(d.jobber.signed_sent_to || '')}">sent ${esc(d.jobber.signed_sent_at.slice(0, 10))}</span>` : ''}` : ''}
      ${d.kind === 'quote' && !(d.jobber||{}).signed_sent_at && ((c.steps || {}).client_approved || {}).at ? `<button class="btn s p" onclick="signQuote(${c.id})">✍ Sign quote</button>` : ''}
      ${d.kind === 'bill' && !(d.jobber||{}).invoice_id ? `<button class="btn s p" onclick="draftInvoice(${d.id})">Draft invoice in Jobber</button>` : ''}
      ${d.kind === 'bill' && (d.jobber||{}).invoice_id ? `<a class="chip g" target="_blank" href="${esc(d.jobber.invoice_uri||'#')}">Jobber draft #${esc(d.jobber.invoice_number)}</a>` : ''}
      ${d.kind === 'report' ? (!(d.jobber||{}).note_id ? `<button class="btn s" onclick="logReport(${d.id})">Log in Jobber</button>`
        : `<button class="btn s" title="The notes in Jobber were wrong and you deleted them - add it again" onclick="if (confirm('Add this report to Jobber again? Delete the old notes there first.')) logReport(${d.id})">Log in Jobber again</button>`) : ''}
      ${d.kind === 'report' && (d.jobber||{}).note_id ? '<span class="chip g">logged in Jobber</span>' : ''}
      ${(d.kind === 'quote' || d.kind === 'bill') ? `<button class="btn s" title="Read the file again with today's reader" onclick="readAgain(${d.id})">↻ Read again</button>` : ''}
      <button class="btn s" onclick="openDoc(${d.id})">Details</button></div>`).join('') || '<div class="note">No documents yet.</div>';
  const issues = (c.issues || []).map(i => `<div class="issue ${i.resolved_at ? 'done' : ''}"><div>${esc(i.message)}${i.resolved_at ? `<div class="note">Resolved by ${esc(i.resolved_by)}: ${esc(i.resolution)}</div>` : ''}</div>${i.resolved_at ? '' : `${i.kind === 'no_quote' ? `<button class="btn s p" onclick="billAnyway(${i.id})">Bill it +30%</button> ` : ''}<button class="btn s" onclick="resolveIssue(${i.id})">Resolve…</button>`}</div>`).join('');
  document.getElementById('drawer').innerHTML = `
  <div class="hd"><div><h2>${esc(c.title || c.client_name)} <button class="btn s" title="Rename this item" onclick="editTitle()">✎</button></h2><div class="note">${catChip(c.category)} <a href="#" title="Set the PO #" onclick="event.preventDefault();editPo()">${c.po_number ? 'PO ' + esc(c.po_number) : '+ PO #'}</a> · opened ${esc(c.opened_on)} ${jl}</div></div>
    <div style="display:flex;gap:6px;align-items:flex-start"><button class="btn" onclick="closeDrawer()">✕</button></div></div>
  <div class="bd">
    ${vendorDocsHtml(c)}
    ${c.vendor_pay.state === 'due' ? `<div class="sec"><div class="issue">💸 Our client has paid the Jobber invoice - ${esc(v)}'s bill needs to be paid.<button class="btn s p" onclick="markVendorPaid(${c.id})">Mark ${esc(v)} paid</button></div></div>` : ''}
    ${c.account && c.account.notes ? `<div class="sec"><div class="note" style="background:var(--violet-bg);color:var(--violet);padding:8px 12px;border-radius:10px;white-space:pre-line"><b>📋 ${esc(c.account.name)}:</b> ${c.account.repairs_by ? 'repairs by <b>' + esc(c.account.repairs_by) + '</b> · ' : ''}${esc(c.account.notes)}</div></div>` : ''}
    ${issues ? `<div class="sec"><h4>Issues</h4><div style="display:flex;flex-direction:column;gap:8px">${issues}</div></div>` : ''}
    ${glanceHtml(c)}
    <div class="sec"><div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn ${['assessment','vendor_quote','scheduled','vendor_bill'].includes(c.stage) ? 'p' : ''}" onclick="vendorEmail(${c.id})">✉️ ${esc(({assessment: 'Ask ' + v + ' to assess', vendor_quote: 'Ask ' + v + ' for the quote', scheduled: 'Ask ' + v + ' to schedule', vendor_bill: 'Ask ' + v + ' for the invoice'})[c.stage] || 'Email ' + v)}</button>
      ${c.chase ? `<button class="btn ${c.chase.state === 'follow_up' ? 'p' : ''}" onclick="logFollow(${c.id})">📞 Log follow-up</button>` : ''}
      ${c.chase && c.chase.parts_wait && !c.chase.last_at ? `<button class="btn" onclick="quoteSent(${c.id})">📤 Approved quote sent to ${esc(c.chase.who || c.vendor || 'the vendor')}</button>` : ''}
      ${c.stage === 'vendor_quote' && !((c.steps || {}).assessment && !c.steps.assessment.na) ? `<button class="btn" onclick="needsVisit()">🔍 ${esc(v)} needs to visit first</button>` : ''}
      <select class="btn" onchange="linkMenu(${c.id}, this)" title="Tie a Jobber quote, invoice or job to this item"><option value="">🔗 Link Jobber…</option><option value="quote">${J.quote ? 'A different Jobber quote' : 'A Jobber quote'}</option><option value="invoice">${J.invoice ? 'A different Jobber invoice' : 'A Jobber invoice'}</option><option value="job">${J.job ? 'A different Jobber job' : 'A Jobber job (service call)'}</option></select>
      <button class="btn" onclick="uploadForCase()">⬆ Add document</button>
      <button class="btn" onclick="addNote()">✎ Add note</button>
      ${c.status === 'open' ? `<button class="btn p" onclick="caseDone(${c.id})">✓ Mark done</button><button class="btn danger" onclick="caseRemove(${c.id})">✕ Remove</button>` : c.status === 'cancelled' ? `<button class="btn p" onclick="caseRestore(${c.id})">↺ Restore</button>` : `<button class="btn" onclick="caseReopen(${c.id})">↺ Reopen</button>`}
    </div></div>
    <div class="sec"><h4>Documents</h4><div class="docs">${docs}</div></div>
    ${statusSec(c)}
    <details class="sec fold"><summary><h4>History</h4> <span class="note">everything that has happened, oldest first</span></summary>${journeyHtml(c, 'history')}</details>
  </div>`;
}
// The job's journey: where it is on its steps, and everything that has
// happened to it, oldest first.
const JOURNEY_ICONS = [
  [/^created|opened/, '🆕', 'b'], [/document received/, '📄', 'b'], [/draft quote created|scada quote drafted/, '💬', 'b'],
  [/quote stamped approved|quote signed|signed quote emailed|quote made a job/, '✅', 'g'], [/vendor replied|date noted in Jobber/, '📅', 'b'], [/^status$/, '📌', 'b'], [/quote status/, '💬', ''], [/draft invoice created|invoiced on matching job/, '🧾', 'b'],
  [/invoice status/, '💵', ''], [/pay vendor/, '💸', 'r'], [/emailed christian/, '✉️', 'g'], [/could not email|not drafted|not logged|not saved/, '⚠️', 'a'],
  [/^issue resolved/, '✔️', 'g'], [/^issue/, '⚠️', 'r'], [/bill matches quote/, '✔️', 'g'], [/^note/, '✎', ''], [/linked/, '🔗', ''],
  [/followed up/, '📞', 'b'], [/service visit|schedule/, '📅', 'b'], [/report/, '📋', 'b'], [/marked done|closed/, '🏁', 'g'], [/reopened/, '↺', 'a'], [/cancelled|removed/, '✕', 'r'],
];
function journeyIcon(action){ const a = (action || '').toLowerCase(); for (const [re, ic, cls] of JOURNEY_ICONS) if (re.test(a)) return [ic, cls]; return ['•', '']; }
function journeyHtml(c, part){
  const steps = c.step_list.filter(s => !s.na);
  const curIdx = steps.findIndex(s => s.key === c.stage);
  const skipped = c.step_list.filter(s => s.na);
  const track = (skipped.length ? `<div class="note" style="margin-bottom:4px">Not needed: ${skipped.map(s => `<a href="#" onclick="event.preventDefault();stepPop(event, '${s.key}')">${esc(s.label)}</a>`).join(' · ')}</div>` : '') + `<div class="track">${steps.map((s, i) => { const st = s.at ? 'done' : (i === curIdx ? 'cur' : '');
    return `<div class="n ${st}" style="cursor:pointer" onclick="stepPop(event, '${s.key}')" title="${esc(s.label)}${s.at ? ' - ' + esc(s.at) : ''} - click to change"><div class="b">${s.at ? '✓' : ''}</div>${esc(s.label)}${s.at ? `<div class="d">${esc(s.at.slice(5))}</div>` : (s.due ? `<div class="d">${esc(s.due.slice(5))}</div>` : '')}</div>`; }).join('')}</div>`;
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
        + (J.site_invoices || []).map(x => `<a class="chip g" target="_blank" href="${esc(x.invoice_uri || '#')}">${esc(x.site)} invoice #${esc(x.invoice_number)}</a>`).join('')
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
  const hist = `<div class="tl">${tl || '<div class="note">Nothing yet.</div>'}</div>`;
  return part === 'track' ? track : part === 'history' ? hist : track + hist;
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
// Follow up with the client on our quote that's waiting on their approval.
async function clientEmail(id){
  const j = await api('/cases/' + id + '/client_email');
  if (!j.success) { toast(j.error, true); return; }
  const e = j.email;
  openModal('Follow up with ' + esc(e.name), `
    <div class="note">Sent from the PO mailbox, so the reply comes back to it. Edit anything first.${e.to ? '' : ' <b class="warn">No email on file for this client - type one in.</b>'}</div>
    <label class="note">To<input type="text" id="cmTo" value="${esc(e.to)}" style="width:100%"></label>
    <label class="note">Subject<input type="text" id="cmSubject" value="${esc(e.subject)}" style="width:100%"></label>
    <textarea id="cmBody" style="width:100%;min-height:240px;font:inherit">${esc(e.body)}</textarea>`,
    `<button class="btn" onclick="closeModal()">Close</button><button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('cmBody').value);toast('Email copied - paste it into Outlook')">Copy email</button><button class="btn p" id="cmSend" onclick="sendClientEmail(${id})">✉ Send email</button>`);
}
async function sendClientEmail(id){
  const btn = document.getElementById('cmSend'); btn.disabled = true; btn.textContent = 'Sending…';
  const j = await api('/cases/' + id + '/client_email/send', {method:'POST', body:{to: document.getElementById('cmTo').value, subject: document.getElementById('cmSubject').value, body: document.getElementById('cmBody').value}});
  btn.disabled = false; btn.textContent = '✉ Send email';
  if (!j.success) { toast(j.error, true); return; }
  toast('Sent to ' + j.sent.to); closeModal();
  if (curTab === 'jobs') loadJobs();
  if (curCase && curCase.id === id) openCase(id);
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
// ── bills to pay ──────────────────────────────────────
// ── Wettech quotes ─────────────────────────────────────
const VQ_STATE = {to_quote: ['r', 'Our quote not made'], draft: ['a', 'Draft - send it'], sent: ['b', 'With the client'],
  approved: ['g', 'Approved'], done: ['', 'Done'], cancelled: ['', 'Cancelled'], beatrice: ['a', 'Goes to Beatriz']};
async function loadVQuotes(){
  const show = document.getElementById('vqShow').value, q = document.getElementById('vqSearch').value.trim();
  const j = await api('/vendor_quotes?show=' + show + '&sort=' + document.getElementById('vqSort').value + '&q=' + encodeURIComponent(q));
  if (document.getElementById('vqSearch').value.trim() !== q) return;   // still typing
  const box = document.getElementById('vqList');
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  const c = j.counts || {};
  setCount('n-vquotes', (c.to_quote || 0) + (c.draft || 0), false);
  document.getElementById('vqInfo').textContent = `${c.to_quote || 0} to quote · ${c.draft || 0} drafts · ${c.sent || 0} with the client · ${c.approved || 0} approved`;
  box.innerHTML = j.quotes.length ? `<table class="t"><thead><tr><th>Site</th><th>Date</th><th>Their quote</th><th class="num">Price</th><th>Our Jobber quote</th><th>Where it stands</th></tr></thead><tbody>
    ${j.quotes.map(x => { const [cls, label] = VQ_STATE[x.state] || ['', x.state];
      return `<tr><td>${x.case_id ? `<a href="#" onclick="event.preventDefault();openCase(${x.case_id})">${esc(x.client_name || x.case_title)}</a>` : esc(x.client_name)}${x.site ? `<div class="note">${esc(x.site)}</div>` : ''}<div class="note">${esc(x.what)}</div></td>
      <td>${esc(x.date)}</td>
      <td><a target="_blank" href="/pumps/api/docs/${x.id}/file">${esc(x.vendor)}${x.number ? ' #' + esc(x.number) : ''}</a></td>
      <td class="num">${money(x.subtotal ?? x.total)}</td>
      <td>${x.ours.number ? (x.ours.uri ? `<a target="_blank" href="${esc(x.ours.uri)}">#${esc(x.ours.number)} ↗</a>` : '#' + esc(x.ours.number)) + `<div class="note">${esc((x.ours.status || '').replace('_', ' '))}</div>` : '<span class="note">-</span>'}</td>
      <td><span class="chip ${cls}">${label}</span></td></tr>`; }).join('')}</tbody></table>`
    : '<div class="empty">No quotes here.</div>';
}
// Bills marked paid, to undo one by mistake - the last 60 days, or any found by the search.
function billsPaidRender(paid, q){
  const box = document.getElementById('billsPaidList');
  const wasOpen = box.querySelector('details')?.open || !!q;
  box.innerHTML = `<details ${wasOpen ? 'open' : ''}><summary class="grp" style="cursor:pointer">Old vendor bills - ${q ? 'paid bills matching the search' : 'paid in the last 60 days'} (${paid.length})</summary>
    <div class="note">Paid - or emailed to Christian, which marks them paid. Search to find older ones; ↶ Undo paid puts one back on the list.</div>
    <div class="toolbar" style="margin:6px 0"><input type="text" id="billsPaidQ" value="${esc(q)}" placeholder="Search every paid bill: site, job, vendor or invoice #" oninput="liveSearch(billsPaidSearch)" onkeydown="if(event.key==='Enter'){event.preventDefault();clearTimeout(window._lsT);billsPaidSearch()}" style="flex:1"><button class="btn" onclick="clearTimeout(window._lsT);billsPaidSearch()">Search</button>${q ? `<button class="btn s" onclick="document.getElementById('billsPaidQ').value='';billsPaidSearch()">Clear</button>` : ''}</div>
    ${paid.length ? `<table class="t"><thead><tr><th>Job</th><th>Vendor</th><th>Their invoice</th><th class="num">Amount</th><th>Paid</th><th></th></tr></thead><tbody>
    ${paid.map(b => `<tr><td><a href="#" onclick="event.preventDefault();openCase(${b.case_id})">${esc(b.client_name || b.title)}</a><div class="note">${esc(b.title)}</div></td>
      <td>${esc(b.vendor)}</td>
      <td>${b.bill_doc_id ? `<a target="_blank" href="/pumps/api/docs/${b.bill_doc_id}/file">#${esc(b.bill_number || '?')}</a>` : '#' + esc(b.bill_number || '?')}</td>
      <td class="num">${b.amount != null ? money(b.amount) : '?'}</td>
      <td>${esc(b.paid_on)}${b.emailed_at ? `<div class="note">✉ emailed Christian ${esc(b.emailed_at)}</div>` : b.paid_by ? `<div class="note">by ${esc(b.paid_by)}</div>` : ''}</td>
      <td><button class="btn s" title="Marked paid by mistake? Put it back on the list" onclick="billsUnpaid([${b.case_id}])">↶ Undo paid</button></td></tr>`).join('')}
    </tbody></table>` : '<div class="note">No paid bill matches.</div>'}</details>`;
  const inp = document.getElementById('billsPaidQ');
  if (q && inp) { inp.focus(); inp.setSelectionRange(q.length, q.length); }
}
async function billsPaidSearch(){
  const q = (document.getElementById('billsPaidQ') || {}).value?.trim() || '';
  const j = await api('/bills_to_pay/paid_list?q=' + encodeURIComponent(q));
  if (((document.getElementById('billsPaidQ') || {}).value || '').trim() !== q) return;   // still typing
  if (!j.success) { toast(j.error, true); return; }
  billsPaidRender(j.paid || [], q);
}
// ── Vendor invoices ────────────────────────────────────
const VI_STATE = {not_invoiced: ['r', 'Not invoiced to the client'], invoiced: ['b', 'Invoiced - vendor not paid'],
  paid: ['g', 'Paid'], cancelled: ['', 'Cancelled']};
async function loadVInvoices(){
  const show = document.getElementById('viShow').value, q = document.getElementById('viSearch').value.trim();
  const j = await api('/vendor_invoices?show=' + show + '&sort=' + document.getElementById('viSort').value + '&q=' + encodeURIComponent(q));
  if (document.getElementById('viSearch').value.trim() !== q) return;   // still typing
  const box = document.getElementById('viList');
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  const c = j.counts || {};
  document.getElementById('viInfo').textContent = `${j.invoices.length} shown · ${c.not_invoiced || 0} not invoiced · ${c.invoiced || 0} invoiced, unpaid · ${c.paid || 0} paid`;
  box.innerHTML = j.invoices.length ? `<table class="t"><thead><tr><th>Site</th><th>Date</th><th>Their invoice</th><th class="num">Amount</th><th>Our invoice</th><th>Where it stands</th></tr></thead><tbody>
    ${j.invoices.map(x => { const [cls, label] = VI_STATE[x.state] || ['', x.state];
      return `<tr><td>${x.case_id ? `<a href="#" onclick="event.preventDefault();openCase(${x.case_id})">${esc(x.client_name || x.case_title)}</a>` : esc(x.client_name)}${x.site ? `<div class="note">${esc(x.site)}</div>` : ''}<div class="note">${esc(x.what)}</div></td>
      <td>${esc(x.date)}</td>
      <td><a target="_blank" href="/pumps/api/docs/${x.id}/file">${esc(x.vendor)}${x.number ? ' #' + esc(x.number) : ''}</a></td>
      <td class="num">${money(x.total ?? x.subtotal)}</td>
      <td>${x.ours.number ? (x.ours.uri ? `<a target="_blank" href="${esc(x.ours.uri)}">#${esc(x.ours.number)} ↗</a>` : '#' + esc(x.ours.number)) + (x.ours.status ? `<div class="note">${esc(x.ours.status.replace('_', ' '))}</div>` : '') : ''}
        ${x.case_id ? `<div style="display:flex;gap:4px;margin-top:2px"><input type="text" id="viOurs${x.id}" placeholder="${x.ours.number ? 'Change #' : 'Our Jobber invoice #'}" style="width:130px" onkeydown="if(event.key==='Enter')viLinkOurs(${x.id}, ${x.case_id})"><button class="btn s" onclick="viLinkOurs(${x.id}, ${x.case_id})">Save</button></div>` : '<span class="note">-</span>'}</td>
      <td><span class="chip ${cls}">${label}</span>${x.paid_on ? `<div class="note">paid ${esc(x.paid_on)}</div>` : ''}${x.state === 'cancelled' && x.case_id ? `<div><button class="btn s" title="Cancelled by mistake? Back to active" onclick="caseRestore(${x.case_id}).then(loadVInvoices)">↺ Restore</button></div>` : ''}</td></tr>`; }).join('')}</tbody></table>`
    : '<div class="empty">No vendor invoices here.</div>';
}
async function loadBills(){
  const j = await api('/bills_to_pay');
  const box = document.getElementById('billsList');
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  let n = 0, total = 0;
  box.innerHTML = j.vendors.map(g => `<div class="grp">${esc(g.vendor)} · ${money(g.payable_total)} to pay${g.waiting_total ? ' · ' + money(g.waiting_total) + ' waiting' : ''}</div>
    <table class="t"><thead><tr><th><input type="checkbox" title="Tick all of ${esc(g.vendor)}'s payable bills" onchange="billsAll(this, '${esc(g.vendor)}')"></th><th>Job</th><th>Their invoice</th><th class="num">Amount</th><th>Can it be paid?</th><th></th></tr></thead><tbody>
    ${g.bills.map(b => { if (b.ready) { n++; total += b.amount || 0; }
      return `<tr class="${b.ready ? '' : 'note'}"><td><input type="checkbox" class="billPick" data-vendor="${esc(g.vendor)}" data-payable="${b.ready ? 1 : 0}" value="${b.case_id}" ${b.ready && !b.asked_at ? 'checked' : ''} onclick="billsClick(event, this)"></td>
      <td><a href="#" onclick="event.preventDefault();openCase(${b.case_id})">${esc(b.client_name || b.title)}</a><div class="note">${esc(b.title)}</div></td>
      <td>${b.bill_doc_id ? `<a target="_blank" href="/pumps/api/docs/${b.bill_doc_id}/file">#${esc(b.bill_number || '?')}</a>` : '#' + esc(b.bill_number || '?')}<div class="note">${esc(b.bill_date)}</div></td>
      <td class="num">${b.amount != null ? money(b.amount) : '?'}</td>
      <td>${b.ready ? '<b class="ok">✓ Yes</b> - ' : 'Not yet - '}${b.payable && !b.ready ? `ready to pay ${esc(niceDay(b.email_on))} (5 business days after we got the invoice ${esc(niceDay(b.received))}) - ` : ''}${esc(b.why)}${b.asked_at ? `<div class="note">✉ Emailed Christian ${esc(b.asked_at.slice(0, 10))}</div>` : ''}</td>
      <td>${b.held ? `<button class="btn s" title="Lift the hold - it can be paid again once nothing else stops it" onclick="billsHold([${b.case_id}], true)">↶ Lift hold</button> ` : b.payable ? (b.pay_ok ? `<button class="btn s" title="Back to waiting" onclick="billsPayOk([${b.case_id}], true)">↶ Not yet</button> ` : `<button class="btn s" title="Something's wrong with this one - don't pay it until the hold is lifted" onclick="billsHold([${b.case_id}])">Not OK to pay yet</button> `) : `<button class="btn s p" title="Billed through a monthly contract, or otherwise fine to pay - pay it now" onclick="billsPayOk([${b.case_id}])">OK to pay now</button> <button class="btn s" title="Invoiced straight in Jobber? Tie that invoice to this job" onclick="linkInvoice(${b.case_id}).then(loadBills)">Link invoice</button> `}<button class="btn s" onclick="markVendorPaid(${b.case_id}).then(loadBills)">Mark paid</button></td></tr>`; }).join('')}
    </tbody></table>`).join('') || '<div class="empty">No vendor bills waiting to be paid. 🎉</div>';
  billsPaidRender(j.paid || [], '');
  setCount('n-bills', j.vendors.reduce((a, g) => a + g.bills.filter(b => b.ready && !b.asked_at).length, 0), false);
  billsInfo();
}
// Tick every payable bill (or one vendor's, from its header box), or none.
function billsAll(box, vendor, on){
  const val = box ? box.checked : on;
  document.querySelectorAll('.billPick').forEach(x => { if (!vendor || x.dataset.vendor === vendor) x.checked = val; });
  billsInfo();
}
// Shift-click: every bill between the last one clicked and this one takes this one's tick.
let billsLast = null;
function billsClick(ev, el){
  const all = [...document.querySelectorAll('.billPick')];
  if (ev.shiftKey && billsLast !== null && all.includes(billsLast)) {
    const [a, b] = [all.indexOf(billsLast), all.indexOf(el)].sort((x, y) => x - y);
    all.slice(a, b + 1).forEach(x => x.checked = el.checked);
  }
  billsLast = el;
  billsInfo();
}
// Ticked bills; for Christian only the ones that can be paid (invoiced).
function billsPicked(any){ return [...document.querySelectorAll('.billPick:checked')].filter(x => any || x.dataset.payable === '1').map(x => +x.value); }
function billsInfo(){
  const all = billsPicked(true), pay = billsPicked();
  document.getElementById('billsInfo').textContent = all.length ? `${all.length} ticked` + (pay.length !== all.length ? ` · ${pay.length} can go to Christian` : '') : 'Tick the bills';
  document.getElementById('billsGo').disabled = !pay.length;
  document.getElementById('billsPaid').disabled = !all.length;
}
// Paid already (or paid now): every ticked bill off the list at once.
async function billsMarkPaid(){
  const ids = billsPicked(true);
  if (!ids.length) { toast('Tick the bills that are paid.', true); return; }
  const d = prompt(`Mark ${ids.length} bill${ids.length > 1 ? 's' : ''} paid. Date paid (YYYY-MM-DD):`, new Date().toISOString().slice(0, 10));
  if (!d) return;
  const j = await api('/bills_to_pay/paid', {method:'POST', body:{case_ids: ids, paid_on: d}});
  if (!j.success) { toast(j.error, true); return; }
  undoToast(`Marked ${j.marked} bill${j.marked > 1 ? 's' : ''} paid.`, () => billsUnpaid(j.case_ids)); loadBills(); loadToday();
}
// Marked paid by mistake: back on the list.
// A bill nothing says can be paid yet (Wild Blue: billed through the monthly irrigation contract): OK it by hand.
async function billsPayOk(ids, undo){
  const j = await api('/bills_to_pay/pay_ok', {method:'POST', body:{case_ids: ids, undo: !!undo}});
  if (!j.success) { toast(j.error, true); return; }
  loadBills(); loadToday();
  if (undo) toast('Back to waiting.');
  else undoToast('OK to pay - it can go in the email to Christian.', () => billsPayOk(ids, true));
}
async function billsHold(ids, undo){
  let note = '';
  if (!undo) { note = prompt("Not OK to pay. Why? (optional - shows on the list)", ''); if (note === null) return; }
  const j = await api('/bills_to_pay/hold', {method:'POST', body:{case_ids: ids, undo: !!undo, note}});
  if (!j.success) { toast(j.error, true); return; }
  loadBills(); loadToday();
  if (undo) toast('Hold lifted.');
  else undoToast("Held - not OK to pay. It stays off the email to Christian.", () => billsHold(ids, true));
}
async function billsUnpaid(ids){
  const j = await api('/bills_to_pay/unpaid', {method:'POST', body:{case_ids: ids}});
  if (!j.success) { toast(j.error, true); return; }
  toast(`Put ${j.unmarked} bill${j.unmarked > 1 ? 's' : ''} back as not paid.`); loadBills(); loadToday();
}
// A toast with an Undo button, up for 10 seconds.
function undoToast(msg, undo){
  const d = document.createElement('div'); d.className = 'toast';
  d.append(msg + ' ');
  const b = document.createElement('button'); b.className = 'btn s'; b.textContent = 'Undo';
  b.onclick = () => { d.remove(); undo(); };
  d.append(b); document.body.appendChild(d); setTimeout(() => d.remove(), 10000);
}
// ids: the ticked bills on the tab; [] = every bill that can be paid (the Home to-do).
async function billsEmail(ids){
  ids = ids || billsPicked();
  if (!ids.length && !arguments.length) { toast('Tick the bills to send.', true); return; }
  window._billIds = ids;
  const j = await api('/bills_to_pay/email', {method:'POST', body:{case_ids: ids}});
  if (!j.success) { toast(j.error, true); return; }
  const e = j.email;
  openModal('Email Christian - bills to pay', `
    <div class="note">To <b>${esc(e.to || '(no address saved for Christian)')}</b> · ${esc(e.subject)} · the ${e.count} bill${e.count > 1 ? 's are' : ' is'} attached.</div>
    <textarea id="billsBody" style="width:100%;min-height:260px;font:inherit">${esc(e.body)}</textarea>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" id="billsSend" onclick="billsSend()">Send to Christian</button>`);
}
async function billsSend(){
  const btn = document.getElementById('billsSend'); btn.disabled = true; btn.textContent = 'Sending…';
  const j = await api('/bills_to_pay/email', {method:'POST', body:{case_ids: window._billIds || billsPicked(), send: true, body: document.getElementById('billsBody').value}});
  btn.disabled = false; btn.textContent = 'Send to Christian';
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); loadBills(); loadToday();
  const ids = j.case_ids || [];
  undoToast(`Emailed Christian: ${j.sent} bill${j.sent > 1 ? 's' : ''}, ${money(j.total)} - marked paid, in Old vendor bills.`,
            () => billsUnpaid(ids));
}
// Invoiced straight in Jobber (Enclave @ Palmira): tie that invoice to the job.
// Find a Jobber job by its number or the client's name, and pick it from the recent ones.
function jobPicker(title, onPick, start){
  openModal(title, `
    <div class="note">Type the job number or the client's name - their recent Jobber jobs show here; click the one.</div>
    <div class="toolbar" style="margin:6px 0"><input type="text" id="jpQ" value="${esc(start || '')}" placeholder="e.g. 14592 or Woodmere" style="flex:1" oninput="if (!this.value.trim()) { clearTimeout(window._lsT); jobPickerSearch(); } else liveSearch(jobPickerSearch)" onkeydown="if(event.key==='Enter'){event.preventDefault();clearTimeout(window._lsT);jobPickerSearch()}"></div>
    <div id="jpList"></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button>`);
  window._jobPick = onPick;
  const q = document.getElementById('jpQ'); q.focus(); jobPickerSearch();
}
async function jobPickerSearch(){
  const q = (document.getElementById('jpQ') || {}).value?.trim() || '';
  const box = document.getElementById('jpList');
  // Nothing typed: the most recently created jobs (Oct 2026).
  if (q.length === 1) return;
  box.innerHTML = `<div class="note">${q ? 'Searching Jobber…' : 'Loading the newest Jobber jobs…'}</div>`;
  const j = await api('/jobber/jobs?q=' + encodeURIComponent(q));
  if (((document.getElementById('jpQ') || {}).value || '').trim() !== q) return;   // still typing
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  window._jobList = j.jobs || [];
  box.innerHTML = (j.recent && window._jobList.length ? '<div class="note" style="margin-bottom:4px">Most recently created - newest first</div>' : '') + (window._jobList.length ? window._jobList.map((x, i) => `<div class="row" style="cursor:pointer" onclick="window._jobPick(window._jobList[${i}])"><div class="main"><div class="tt">#${esc(x.number)} · ${esc(x.client_name)}</div><div class="sub">${esc(x.title)}${x.date ? ' · ' + esc(niceDay(x.date)) : ''}${x.status ? ' · ' + esc(x.status.replace(/_/g, ' ')) : ''}${x.case_id ? ' · <b>already followed here</b>' : ''}${x.uri ? ` · <a href="${esc(x.uri)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Jobber ↗</a>` : ''}</div></div></div>`).join('')
    : '<div class="note">No Jobber job matches.</div>');
}
// A service call booked in Jobber: followed from its job - the start of the work, no quote.
function addServiceCall(){
  jobPicker('Follow a service call', async x => {
    const j = await api('/service_call', {method:'POST', body:{number: x.number}});
    if (!j.success) { toast(j.error, true); return; }
    closeModal();
    toast(j.already ? 'Already followed here - opening it.' : 'Service call followed - it starts at the work, no quote.');
    loadToday(); openCase(j.case_id);
  });
}
function linkJob(id){
  jobPicker('Link a Jobber job to this item', async x => {
    const sc = confirm('Is it a service call that starts the work?\n\nOK = yes: no quote needed, scheduled for the job\'s day.\nCancel = just link the job.');
    const j = await api('/cases/' + id + '/jobber_job', {method:'POST', body:{number: x.number, service_call: sc}});
    if (!j.success) { toast(j.error, true); return; }
    closeModal();
    toast(`Linked Jobber job #${j.job.number}${sc ? ' - a service call, no quote' : ''}.`);
    openCase(id); loadToday();
  }, (curCase && curCase.id === id && curCase.client_name) || '');
}
// Pick the job's Jobber invoice from a search of Jobber, without leaving the app (Oct 2026).
async function linkInvoice(id){
  if (!JOBBER_OK) { toast('Connect Jobber first (top of the page).', true); return; }
  const c = await api('/cases/' + id);
  const name = c.success ? (c.case.client_name || '') : '';
  return new Promise(done => {
    window._liDone = done;
    openModal('Link our Jobber invoice', `
      <div class="note"><b>Link to this job</b> on the client's pump job: the bill can be paid once that job is billed for its month - nothing more to do, and the client's later bills follow it too. Or search Jobber by client, invoice number or subject and pick an invoice.</div>
      <div class="toolbar" style="margin:6px 0"><input type="text" id="liQ" value="${esc(name)}" style="flex:1"
        oninput="liveSearch(() => linkInvoiceSearch(${id}))" onkeydown="if(event.key==='Enter'){event.preventDefault();clearTimeout(window._lsT);linkInvoiceSearch(${id})}">
        <button class="btn" onclick="linkInvoiceSearch(${id})">Search</button></div>
      <div id="liList"></div>`, `<button class="btn" onclick="closeModal();window._liDone&&window._liDone()">Cancel</button>`);
    linkInvoiceSearch(id);
  });
}
async function linkInvoiceSearch(id){
  const q = document.getElementById('liQ').value.trim(), box = document.getElementById('liList');
  if (q.length < 2) { box.innerHTML = ''; return; }
  box.innerHTML = '<div class="note">Searching Jobber…</div>';
  const j = await api('/jobber/invoices?q=' + encodeURIComponent(q) + '&case_id=' + id);
  if (!document.getElementById('liQ') || document.getElementById('liQ').value.trim() !== q) return;   // still typing
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  const row = x => `<div class="cand" onclick="linkInvoicePick(${id}, '${esc(x.number)}')"><div style="flex:1">
      <b>#${esc(x.number)} ${esc(x.subject)}</b><div class="note">${esc(x.client)} · ${esc(x.date)} · ${esc(x.status.replace(/_/g, ' '))}</div></div>
      <span class="num">${money(x.total)}</span> <a class="note" target="_blank" href="${esc(x.uri)}" onclick="event.stopPropagation()">↗</a></div>`;
  // The monthly job once, green, saying whether the bill's month is billed on it yet.
  const rec = (j.recurring || []).map(g => `<div class="cand" style="background:#e8f5e9;border-color:#66bb6a;cursor:default"><div style="flex:1">
      <b>Job #${esc(g.number)} ${esc(g.title)}</b> ${g.pump_job ? '<span class="chip g">linked job</span>' : `<span class="chip">recurring job</span> <button class="btn s p" title="Once this job is billed for the bill's month, the bill can be paid - you won't have to link it again" onclick="setPumpJob(${id}, ${esc(JSON.stringify({id: g.id, number: g.number, title: g.title, property: g.property || ''}))})">Link to this job</button>`}${g.property ? `<div class="note">${esc(g.property)}</div>` : ''}
      <div class="note">${g.billed ? `${esc(j.month)}: billed - invoice #${esc(g.billed.number)} ${esc(g.billed.subject)} · ${esc(g.billed.date)} · ${esc(g.billed.status.replace(/_/g, ' '))} · ${money(g.billed.total)}`
        : `<b class="bad">${esc(j.month)}: not billed yet</b>${g.latest ? ` - last invoice #${esc(g.latest.number)} · ${esc(g.latest.date)} · ${esc(g.latest.status.replace(/_/g, ' '))}` : ''}`}</div></div>
      ${g.billed ? `<button class="btn s p" onclick="linkInvoicePick(${id}, '${esc(g.billed.number)}')">Link #${esc(g.billed.number)}</button> <a class="note" target="_blank" href="${esc(g.billed.uri)}">↗</a>` : ''}</div>`).join('');
  const other = (j.invoices || []).map(row).join('');
  const byNum = `<div class="toolbar" style="margin:6px 0"><input type="text" id="liJob" placeholder="Job not listed? Its Jobber job number, e.g. 11442" style="flex:1">
    <button class="btn s p" onclick="const n = document.getElementById('liJob').value.trim(); if (n) setPumpJob(${id}, {number: n})">Link to this job</button></div>`;
  box.innerHTML = rec + byNum + ((other ? (rec ? '<div class="note" style="margin:8px 0 4px">Other invoices</div>' : '') + other : '')
    || '<div class="note">No Jobber invoices found.</div>');
}
async function setPumpJob(id, job){
  const j = await api('/cases/' + id + '/pump_job', {method:'POST', body: job});
  if (!j.success) { toast(j.error, true); return; }
  closeModal();
  toast(`Linked to job #${j.job.number} - the bill can be paid once its month is billed on that job (this client's later bills too).`);
  if (curCase && curCase.id === id) openCase(id); else loadToday();
  if (window._liDone) window._liDone();
}
async function linkInvoicePick(id, number){
  const j = await api('/cases/' + id + '/jobber_invoice', {method:'POST', body:{number}});
  if (!j.success) { toast(j.error, true); return; }
  closeModal();
  toast(`Linked Jobber invoice #${j.invoice.number}${j.invoice.status ? ' (' + j.invoice.status.replace(/_/g, ' ') + ')' : ''}.`);
  if (curCase && curCase.id === id) openCase(id); else loadToday();
  if (window._liDone) window._liDone();
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
// The approved quote went to the vendor outside the app: now waiting on their date.
async function quoteSent(caseId){
  if (!confirm('Mark the approved quote as sent to the vendor? The job then waits on their reply about when it will be scheduled.')) return;
  const j = await api('/cases/' + caseId + '/quote_sent', {method:'POST', body:{how:'email'}});
  if (!j.success) { toast(j.error, true); return; }
  toast(`Noted - waiting on ${j.to} for a date`);
  loadToday(); if (curCase && curCase.id === caseId) openCase(caseId);
}
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
// Out of step (Carlisle: the work's done, still reads "send the quote to Tom"): jump to the real step.
async function moveCase(sel){
  const k = sel.value, label = sel.options[sel.selectedIndex].text; sel.value = '';
  if (!k || !confirm(`Move this job to "${label}"?\n\nThe steps before it are ticked done today.`)) return;
  const j = await api('/cases/' + curCase.id + '/move', {method:'POST', body:{stage: k}});
  if (j.success) { curCase = j.case; renderCase(); toast('Moved to: ' + label); } else toast(j.error || 'Not moved', true);
}
// A bill or report on the wrong job (Lely: the quarterly bill on the valve repair): off it, filed again.
// Wrong job: pick the job it belongs on (Huntington #5's bill, Oct 2026), or let the app file it again.
async function refileDoc(id){
  openModal('Move to another job', `
    <div class="note">Find the job this document belongs on - search by site, job, quote or invoice number. What it ticked on this job is undone.</div>
    <div class="toolbar" style="margin:6px 0"><input type="text" id="mvQ" placeholder="e.g. Huntington #5" style="flex:1" oninput="liveSearch(() => refileSearch(${id}))"></div>
    <div id="mvList"><div class="note">Type to search open and closed jobs.</div></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn" onclick="refileTo(${id}, null)">Let the app pick</button>`);
  const q = document.getElementById('mvQ'); if (q) { q.value = (curCase && curCase.client_name || '').split(' - ')[0]; q.focus(); refileSearch(id); }
}
async function refileSearch(id){
  const q = (document.getElementById('mvQ') || {}).value?.trim() || '';
  if (!q) return;
  const j = await api('/cases?status=all&q=' + encodeURIComponent(q));
  if (((document.getElementById('mvQ') || {}).value || '').trim() !== q) return;   // still typing
  const box = document.getElementById('mvList');
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  const cs = (j.cases || []).filter(c => !curCase || c.id !== curCase.id).slice(0, 25);
  box.innerHTML = cs.length ? cs.map(c => `<div class="row" style="cursor:pointer" onclick="refileTo(${id}, ${c.id})"><div class="main"><div class="tt">${esc(c.client_name || '')} · ${esc(c.title || '')}</div><div class="sub">${esc(c.status)} · opened ${esc(c.opened_on || '')}${c.vendor_quote_number ? ' · quote #' + esc(c.vendor_quote_number) : ''}${c.sei_invoice_number ? ' · our invoice #' + esc(c.sei_invoice_number) : ''}</div></div></div>`).join('') : '<div class="note">No job matches.</div>';
}
async function refileTo(id, caseId){
  const j = await api('/docs/' + id + '/refile', {method:'POST', body: caseId ? {case_id: caseId} : {}});
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); toast('Moved' + (j.case_id ? ' - opening that job' : ''));
  if (j.case_id) openCase(j.case_id); else loadToday();
}
// A step on the track, clicked: done today, done on a date, not needed, or not done.
function stepPop(ev, k){
  ev.stopPropagation();
  document.querySelectorAll('.stepPop').forEach(x => x.remove());
  const s = curCase.step_list.find(x => x.key === k) || {};
  const d = document.createElement('div');
  d.className = 'stepPop';
  d.style.cssText = `position:fixed;z-index:99;left:${Math.min(ev.clientX, innerWidth - 220)}px;top:${ev.clientY + 8}px;background:var(--card, #fff);border:1px solid var(--border);border-radius:10px;padding:6px;box-shadow:0 6px 24px rgba(0,0,0,.18);display:flex;flex-direction:column;gap:4px;min-width:200px`;
  const opts = [];
  if (!s.at) opts.push(['✓ Done today', () => setStep(k, 'today')]);
  opts.push(['Done on a date…', () => stepMenu(k, {value: 'date'})]);
  if (s.at) opts.push(['Not done', () => setStep(k, null)]);
  opts.push([s.na ? 'Needed after all' : 'Not needed', () => setStep(k, s.na ? null : 'na')]);
  d.innerHTML = `<div class="note" style="padding:2px 6px"><b>${esc(s.label || k)}</b>${s.at ? ' · done ' + esc(s.at) : ''}</div>`;
  opts.forEach(([label, fn]) => { const b = document.createElement('button'); b.className = 'btn s'; b.style.textAlign = 'left'; b.textContent = label; b.onclick = () => { d.remove(); fn(); }; d.appendChild(b); });
  document.body.appendChild(d);
  setTimeout(() => document.addEventListener('click', function off(e){ if (!d.contains(e.target)) { d.remove(); document.removeEventListener('click', off); } }), 0);
}
function linkMenu(id, sel){ const v = sel.value; sel.value = ''; if (v === 'quote') linkQuote(id); else if (v === 'invoice') linkInvoice(id); else if (v === 'job') linkJob(id); }
function editPo(){ const v = prompt('PO # for this item:', curCase.po_number || ''); if (v != null && v.trim() !== (curCase.po_number || '')) patchCase({po_number: v.trim()}); }
function setStep(k, v){ patchCase({steps: {[k]: v === 'today' ? new Date().toISOString().slice(0,10) : v}}); }
function stepMenu(k, sel){
  const v = sel.value; sel.value = '';
  if (v === 'na') setStep(k, 'na'); else if (v === 'needed' || v === 'undo') setStep(k, null);
  else if (v === 'date') { const d = prompt('Date it was done (YYYY-MM-DD):', new Date().toISOString().slice(0,10)); if (d) setStep(k, d); }
}
// Status of an approved job: parts ordered (and when they're due), client
// notified, scheduled, work done… newest on top, every update in the log.
const JOB_STATUSES = [['parts_ordered', 'Parts ordered'], ['waiting_vendor', 'Waiting on the vendor'], ['client_notified', 'Client notified'], ['scheduled', 'Scheduled'], ['in_progress', 'Work under way'], ['work_done', 'Work done'], ['on_hold', 'On hold'], ['note', 'Note']];
function statusSec(c){
  const hist = (c.events || []).filter(e => e.action === 'status');
  return `<details class="sec fold"><summary><h4>Status update</h4>${statusLine(c) ? ` <span class="note">${statusLine(c)}</span>` : ' <span class="note">none yet - add one</span>'}</summary>
    ${(c.job_status || {}).kind ? `<div class="note" style="margin-top:6px">Picked the wrong kind? Change it to: <select onchange="jsRelabel(${c.id}, this.value)"><option value="">-</option>${JOB_STATUSES.filter(([k]) => k !== c.job_status.kind).map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select></div>` : ''}
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:8px">
      <select id="js_kind" onchange="jsKind()">${JOB_STATUSES.map(([k, l]) => `<option value="${k}" ${k === 'note' ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <input type="date" id="js_on" value="${todayIso()}" title="The day - today unless you change it (when the parts are due / the day it is scheduled)">
      <span id="js_weeks" style="display:none;gap:4px">${[1, 2, 3, 4].map(w => `<button class="btn s" onclick="jsWeeks(${w})">${w} wk${w > 1 ? 's' : ''}</button>`).join('')}</span>
      <input type="text" id="js_text" placeholder="Note - e.g. motor ordered from Wettech, client told by email" style="flex:1;min-width:200px">
      <button class="btn p" onclick="jsAdd(${c.id})">＋ Add update</button></div>
    ${hist.length ? `<div style="margin-top:8px">${hist.map(e => `<div class="note">${esc(niceDay(d10(e.at)))} · ${esc(e.actor || '')} · ${esc(e.detail)}</div>`).join('')}</div>` : ''}</details>`;
}
// The job at a glance: where it stands, and the vendor's quote and invoice, our
// invoice and whether the vendor is paid - each one click away.
function glanceHtml(c){
  const v = c.vendor || 'Wettech', J = c.jobber || {};
  const live = (c.docs || []).filter(d => d.status !== 'dismissed');
  const last = k => live.filter(d => d.kind === k).sort((a, b) => b.id - a.id)[0];
  const q = last('quote'), b = last('bill');
  const card = (k, main, sub) => `<div class="m"><div class="k">${k}</div><div class="v">${main}</div>${sub ? `<div class="note">${sub}</div>` : ''}</div>`;
  const fileLink = (d, label) => `<a target="_blank" href="/pumps/api/docs/${d.id}/file">${label} ↗</a>`;
  const qAmt = money(c.vendor_quote_amount ?? c.vendor_quote_total ?? (q || {}).subtotal ?? (q || {}).total);
  const bAmt = money(c.vendor_bill_amount ?? c.vendor_bill_total ?? (b || {}).subtotal ?? (b || {}).total);
  const qNum = c.vendor_quote_number || (q || {}).doc_number || '', bNum = c.vendor_bill_number || (b || {}).doc_number || '';
  const ourQ = J.quote ? `our quote <a target="_blank" href="${esc(jobberUri(J.quote, 'quotes') || '#')}">#${esc(J.quote.number || '')}</a>${J.quote.status ? ' · ' + esc(J.quote.status.replace(/_/g, ' ')) : ''}` : '';
  const quoteCard = card(`${esc(v)} quote`, qAmt || (q || qNum ? '—' : 'None yet'),
    [q ? fileLink(q, qNum ? '#' + esc(qNum) : 'Open the quote') : (qNum ? '#' + esc(qNum) : ''), ourQ].filter(Boolean).join('<br>'));
  const findBtn = `<a href="#" onclick="event.preventDefault();findVendorInvoice(${JSON.stringify(c.client_name || c.title || '').replace(/"/g, '&quot;')})">Find it in Vendor invoices</a>`;
  const billCard = card(`${esc(v)} invoice`, bAmt || (b || bNum ? '—' : 'Not in yet'),
    b ? fileLink(b, bNum ? '#' + esc(bNum) : 'Open the invoice') + (b.doc_date ? ' · ' + esc(b.doc_date) : '') : (bNum ? '#' + esc(bNum) + '<br>' : '') + findBtn);
  const inv = J.invoice || {}, invUri = jobberInvoiceUri(inv);
  const invNo = inv.number || c.sei_invoice_number;
  const ourInv = c.amount != null ? money(c.amount) : (invNo ? '—' : 'Not yet');
  const invSub = [invNo ? (invUri ? `<a target="_blank" href="${esc(invUri)}">#${esc(invNo)} ↗</a>` : '#' + esc(invNo)) : '',c.vendor_pay.client_invoice_status ? (c.vendor_pay.client_invoice_status === 'paid' ? '<b class="ok">paid by client</b>' : esc(c.vendor_pay.client_invoice_status.replace(/_/g, ' '))) : '',
    ...(J.site_invoices || []).map(x => `${esc(x.site || '')} <a target="_blank" href="${esc(x.uri || '#')}">#${esc(x.number)}</a>`)].filter(Boolean).join(' · ');
  const cmp = c.compare || {};
  const cmpText = {match: `✓ Bill matches the quote (${money(cmp.bill)})`, over: `Bill is ${money(Math.abs(cmp.diff))} MORE than the quote`, under: `Bill is ${money(Math.abs(cmp.diff))} less than the quote`, no_quote: 'Bill arrived with no quote on file'}[cmp.state];
  return `<div class="sec"><div style="font-size:15px;margin-bottom:8px"><b>${esc(stageText(c))}</b></div>
    ${c.chase ? `<div class="note" style="margin-bottom:8px">${chaseLine(c).replace(/^<br>/, '')}</div>` : ''}
    <div class="money">${quoteCard}${billCard}${card('Our invoice', ourInv, invSub)}${`<div class="m"><div class="k">${esc(v)} paid?</div>${vendorPayHtml(c)}</div>`}</div>
    ${cmpText ? `<div class="cmp ${esc(cmp.state)}">${cmpText}</div>` : ''}
    <div style="margin-top:10px">${journeyHtml(c, 'track')}</div>
    <div class="note" style="margin-top:4px">Click a step to tick it, untick it or mark it not needed · <select class="s" onchange="moveCase(this)" title="Out of step? Bring the job up to where it really is - the steps before are ticked done today." style="padding:2px 4px;font-size:12px"><option value="">Move to…</option>${c.step_list.filter(s => !s.na).map(s => `<option value="${s.key}">${esc(s.label)}</option>`).join('')}</select></div></div>`;
}
// The related vendor invoice, from a job: the Vendor invoices tab, searched for its site.
function findVendorInvoice(name){
  document.getElementById('drawerWrap').classList.add('hide'); curCase = null;
  showTab('vinvoices');
  document.getElementById('viShow').value = 'all';
  document.getElementById('viSearch').value = name || '';
  loadVInvoices();
}
function jsKind(){ const k = document.getElementById('js_kind').value; document.getElementById('js_weeks').style.display = ['parts_ordered', 'waiting_vendor', 'scheduled'].includes(k) ? 'flex' : 'none'; }
function jsWeeks(w){ const d = new Date(); d.setDate(d.getDate() + 7 * w); document.getElementById('js_on').value = d.toISOString().slice(0, 10); const t = document.getElementById('js_text'); if (!t.value) t.value = w + ' week' + (w > 1 ? 's' : '') + ' out'; }
async function jsAdd(id){
  const v = x => document.getElementById(x).value;
  const j = await api('/cases/' + id + '/status', {method:'POST', body:{kind: v('js_kind'), on: v('js_on'), text: v('js_text').trim()}});
  if (!j.success) { toast(j.error, true); return; }
  curCase = j.case; renderCase(); toast('Status updated'); loadToday();
}
// An invoiced one-off pump job still open in Jobber: closed when someone clicks it.
async function closeJobberJob(id, btn){
  if (!confirm('Close this job in Jobber?\n\nIts invoice has gone out - nothing is sent to the client.')) return;
  if (btn) { btn.disabled = true; btn.textContent = 'Closing…'; }
  const j = await api('/jobber/jobs/close', {method:'POST', body:{job_id: id}});
  if (btn) { btn.disabled = false; btn.textContent = 'Close job in Jobber'; }
  if (!j.success) { toast(j.error, true); return; }
  toast('Closed in Jobber'); loadToday();
}
// A SCADA renewal's quote: drafted in Jobber only when someone clicks it (never by itself).
async function draftScadaQuote(id, btn){
  if (!confirm('Draft the SCADA renewal quote in Jobber now?\n\nIt is made as a draft - nothing is sent to the client.')) return;
  if (btn) { btn.disabled = true; btn.textContent = 'Drafting…'; }
  const j = await api('/scada/' + id + '/draft_quote', {method:'POST'});
  if (btn) { btn.disabled = false; btn.textContent = 'Draft quote in Jobber'; }
  if (!j.success) { toast(j.error, true); return; }
  toast(j.quote.already ? `Already drafted - quote #${j.quote.number}` : `Drafted quote #${j.quote.number} in Jobber - send it from there`);
  loadToday();
}
// The latest status was the wrong kind ("Parts ordered" for a call to the client): relabel it, words kept.
async function jsRelabel(id, kind){
  if (!kind) return;
  const j = await api('/cases/' + id + '/status/kind', {method:'POST', body:{kind}});
  if (!j.success) { toast(j.error, true); return; }
  curCase = j.case; renderCase(); toast('Changed'); loadToday();
}
// Rename an item - the title it got from a document can be long or say the wrong thing (Banyan Bay, Oct 2026).
function editTitle(){
  const t = prompt('Title for this item:', curCase.title || curCase.client_name || '');
  if (t != null && t.trim() && t.trim() !== curCase.title) patchCase({title: t.trim()}).then(j => { if (j && j.success) { toast('Renamed'); loadToday(); } });
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
// Our Jobber invoice # typed on a vendor invoice: looked up (synced, else Jobber) and linked - never marks it paid.
async function viLinkOurs(docId, caseId){
  const el = document.getElementById('viOurs' + docId), n = (el.value || '').trim().replace(/^#/, '');
  if (!n) { el.focus(); return; }
  const j = await api('/cases/' + caseId + '/jobber_invoice', {method:'POST', body:{number: n}});
  if (!j.success) { toast(j.error, true); return; }
  toast(`Linked our Jobber invoice #${j.invoice.number}${j.invoice.status ? ' (' + j.invoice.status.replace(/_/g, ' ') + ')' : ''}.`);
  loadVInvoices();
}
async function caseRestore(id){
  const j = await api('/cases/' + id + '/restore', {method:'POST', body:{}});
  if (!j.success) { toast(j.error, true); return; }
  toast('Restored - back to active.');
  if (curCase && curCase.id === id) openCase(id);
  loadToday();
}
async function linkOursFromCase(id){
  const el = document.getElementById('csOurs'), n = (el.value || '').trim().replace(/^#/, '');
  if (!n) { el.focus(); return; }
  const j = await api('/cases/' + id + '/jobber_invoice', {method:'POST', body:{number: n}});
  if (!j.success) { toast(j.error, true); return; }
  toast(`Linked our Jobber invoice #${j.invoice.number}.`); openCase(id); loadToday();
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
function uploadForCase(){ uploadBox(curCase.id); }

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
// Upload: a box to drop files on, or click it to pick them (Oct 2026). What they are comes from the
// menu beside the button - or pick it here.
function uploadBox(caseId){
  const kind = caseId ? '' : document.getElementById('uploadKind').value;
  openModal('Upload documents', `
    ${caseId ? '' : `<label class="note" style="display:block;margin-bottom:8px">What they are <select id="upBoxKind" style="margin-left:6px"><option value="">Let the app decide</option><option value="quote">Quotes</option><option value="bill">Bills</option><option value="report">Reports</option></select></label>`}
    <div id="dropZone" style="border:2px dashed var(--border);border-radius:12px;padding:36px 16px;text-align:center;cursor:pointer">
      <div style="font-size:28px">📄</div><b>Drag and drop files here</b><div class="note">or click to choose - PDF or Word, several at once</div></div>
    <input type="file" id="dropIn" multiple accept=".pdf,.docx,.doc" class="hide">`,
    `<button class="btn" onclick="closeModal()">Cancel</button>`);
  const sel = document.getElementById('upBoxKind'); if (sel) sel.value = kind;
  const z = document.getElementById('dropZone'), inp = document.getElementById('dropIn');
  const go = files => { if (!files || !files.length) return; if (sel) document.getElementById('uploadKind').value = sel.value; closeModal(); uploadFiles(files, caseId); };
  z.onclick = () => inp.click();
  inp.onchange = () => go(inp.files);
  ['dragenter', 'dragover'].forEach(e => z.addEventListener(e, ev => { ev.preventDefault(); z.style.background = 'var(--violet-bg)'; z.style.borderColor = 'var(--violet)'; }));
  ['dragleave', 'drop'].forEach(e => z.addEventListener(e, ev => { ev.preventDefault(); z.style.background = ''; z.style.borderColor = ''; }));
  z.addEventListener('drop', ev => go(ev.dataTransfer.files));
}
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
    ${(d.site_invoices_left || []).length ? `<div class="issue">🧾 This bill covers more than one pump station - each has its own job and its own invoice. Still to draft: <b>${esc(d.site_invoices_left.map(x => x.location).join(', '))}</b> <button class="btn s p" onclick="siteInvoices(${d.id})">Draft ${d.site_invoices_left.length > 1 ? 'them' : 'it'}</button></div>` : ''}
    ${((d.jobber || {}).site_invoices || []).length ? `<div class="note">Invoiced per station: ${[d.jobber].concat(d.jobber.site_invoices).map(x => `<a class="chip g" target="_blank" href="${esc(x.invoice_uri || '#')}">${esc(x.site || 'first')} #${esc(x.invoice_number)}</a>`).join(' ')}</div>` : ''}
    ${(d.sections || []).length > 1 ? `<div class="note">One page per pump station - each goes on its own job: ${d.sections.map(x => `<b>${esc(x.location)}</b> ${x.logged ? '✓ logged' : '(not logged yet)'}`).join(' · ')}</div>` : ''}
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
// A bill for two pump stations (The Carlisle): the other station's invoice, on its own job.
async function siteInvoices(id){
  const j = await api('/docs/' + id + '/site_invoices', {method:'POST', body:{}});
  if (!j.success) { toast(j.error, true); return; }
  const made = (j.invoices || []).filter(x => x.invoice_number);
  const left = (j.invoices || []).filter(x => x.pending);
  toast(made.length ? `Drafted ${made.map(x => x.location + ' #' + x.invoice_number).join(', ')} in Jobber - review and send.` : 'Nothing to draft.', !made.length);
  left.forEach(x => toast(x.location + ': ' + x.pending, true));
  closeModal(); loadToday();
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
  inv = {mode: 'invoice', doc: d, client_id: null, lines: s.line_items.map(x => Object.assign({}, x)), subject: s.subject, job: s.job || null, bill_lines: s.bill_lines || null, also: new Set()};
  if (s.from_quote) setTimeout(() => { const n = document.querySelector('#modal .note'); if (n) n.insertAdjacentHTML('afterbegin', `<b>Lines copied from our Jobber quote #${esc(String(s.from_quote))}</b> - the bill matches ${esc(d.vendor)}'s quote, so the client is invoiced what they were quoted. `); }, 0);
  openModal('Draft invoice in Jobber', `
    <div class="safe">This creates a DRAFT invoice in Jobber. Nothing is sent to the client - review it in Jobber and send it from there.</div>
    ${d.account_note ? `<div class="issue">📌 <b>${esc(d.account_name || 'Account')}:</b> ${esc(d.account_note)}</div>` : ''}
    ${(d.case_issues || []).map(i => `<div class="issue">⚠️ ${esc(i.message)}</div>`).join('')}
    ${s.note ? `<div class="issue">ℹ️ ${esc(s.note)}</div>` : ''}
    <div class="note">From ${esc(d.vendor)} bill #${esc(d.doc_number)} - ${money(d.subtotal)} before tax, ${money(d.total)} total. One Service Proposal Amount line: the bill before tax${s.markup_pct ? ' plus ' + s.markup_pct + '%' : ''}; Jobber adds the client's tax.</div>
    <div><b>Jobber client</b><div class="toolbar" style="margin:6px 0"><input type="text" id="cq" oninput="liveSearch(findClients)" onkeydown="if(event.key==='Enter'){event.preventDefault();clearTimeout(window._lsT);findClients()}" value="${esc(d.client_name)}" style="flex:1"><button class="btn" onclick="findClients()">Search</button></div><div id="cands"><div class="note">Searching…</div></div></div>
    <div id="jobMatchBox">${jobMatchHtml(s.job)}</div>
    <div class="note">The client you pick is remembered for "${esc(d.client_name)}", so next time it's filled in by itself.</div>
    <label class="note">Invoice subject<input type="text" id="invSubject" value="${esc(inv.subject)}" style="width:100%"></label>
    <div><b>Line items</b> <span class="note">(edit before creating)</span><table class="t" style="margin-top:6px"><thead><tr><th>Name</th><th>Description</th><th class="num">Qty</th><th class="num">Unit price</th><th>Tax</th><th></th></tr></thead><tbody id="invLines"></tbody></table>
      <button class="btn s" style="margin-top:6px" onclick="inv.lines.push({name:'',description:'',quantity:1,unit_price:0,taxable:true});drawLines()">＋ Line</button>
      <div class="foot"><span id="invTotal"></span></div></div>
    ${(d.other_bills || []).length ? `<div style="margin-top:10px"><b>Bill on this invoice too</b> <span class="note">- ${esc(d.client_name)}'s other bills not invoiced yet; ticked ones go on this one invoice (and job), their lines added</span>
      ${d.other_bills.map((o, i) => `<label class="cand" style="cursor:pointer"><input type="checkbox" onchange="invAlso(${i}, this.checked)"><div style="flex:1"><b>${esc(o.vendor)} #${esc(o.doc_number || '?')}</b> · ${money(o.total)} · ${esc(o.doc_date)}<div class="note">${esc(o.description)}</div></div></label>`).join('')}</div>` : ''}`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" id="invGo" onclick="createInvoice()">Create draft in Jobber</button>`);
  drawLines(); findClients();
}
function jobMatchHtml(job){
  return job ? `<div class="safe" id="jobMatch">Matches Jobber job <a href="${esc(job.uri)}" target="_blank" rel="noopener"><b>#${esc(job.number)} ${esc(job.title)}</b> ↗</a> (${esc((job.status || '').replace(/_/g, ' '))}, ${money(job.total)}) - the invoice goes on that job at its price${job.type === 'recurring' ? ", and the job's visit for the bill's month is marked complete" : ''}. <button class="btn s" onclick="dropJobMatch()">Not this job - bill + 30%</button> <button class="btn s" onclick="otherJobs()">Use a different job…</button><div id="otherJobs"></div></div>` : (inv.client_id ? `<div class="note"><button class="btn s" onclick="otherJobs()">Put it on one of the client's recurring jobs…</button><div id="otherJobs"></div></div>` : '');
}
// The client's other recurring jobs, to put the invoice on a different one (Caymas, Oct 2026: it took the $0
// "Monthly Water Reading" job).
async function otherJobs(){
  const box = document.getElementById('otherJobs');
  if (!inv.client_id) { toast('Pick the Jobber client first.', true); return; }
  box.innerHTML = '<div class="note">Looking up the recurring jobs…</div>';
  const j = await api('/jobber/recurring_jobs?client_id=' + encodeURIComponent(inv.client_id));
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  box.innerHTML = (j.jobs || []).length ? `<select onchange="useJob(this.value)" style="margin-top:6px;max-width:100%"><option value="">Pick the job…</option>${j.jobs.map(x => `<option value="${esc(x.id)}" ${inv.job && inv.job.id === x.id ? 'selected' : ''}>#${esc(x.number)} ${esc(x.title)} - ${money(x.price)}${x.property_label ? ' · ' + esc(x.property_label) : ''}</option>`).join('')}</select>` : '<div class="note">This client has no live recurring jobs in Jobber.</div>';
}
async function useJob(jobId){
  if (!jobId) return;
  const j = await api('/docs/' + inv.doc.id + '/invoice_suggestion?client_id=' + encodeURIComponent(inv.client_id) + '&job_id=' + encodeURIComponent(jobId));
  const s = j.success && j.suggestion;
  if (!s || !s.job) { toast((j && j.error) || "That job has no priced lines to invoice from", true); return; }
  inv.dropped = false; inv.job = s.job; inv.lines = s.line_items.map(x => Object.assign({}, x)); inv.bill_lines = s.bill_lines || inv.bill_lines;
  const subj = document.getElementById('invSubject'); if (subj && s.subject) subj.value = s.subject;
  document.getElementById('jobMatchBox').innerHTML = jobMatchHtml(inv.job);
  drawLines(); toast('Now on job #' + s.job.number);
}
// The client is picked: a maintenance bill takes that client's recurring job price (Rosewood, Oct 2026).
async function invForClient(id){
  if (inv.mode !== 'invoice' || inv.dropped || !id) return;
  const j = await api('/docs/' + inv.doc.id + '/invoice_suggestion?client_id=' + encodeURIComponent(id));
  const s = j.success && j.suggestion;
  if (!s || inv.client_id !== id) return;
  inv.job = s.job || null; inv.lines = s.line_items.map(x => Object.assign({}, x)); inv.bill_lines = s.bill_lines || inv.bill_lines;
  const subj = document.getElementById('invSubject'); if (subj && s.subject) subj.value = s.subject;
  document.getElementById('jobMatchBox').innerHTML = jobMatchHtml(inv.job);
  drawLines();
}
function dropJobMatch(){ inv.job = null; inv.dropped = true; if (inv.bill_lines) inv.lines = inv.bill_lines.map(x => Object.assign({}, x)); const el = document.getElementById('jobMatch'); if (el) el.remove(); drawLines(); }
function drawLines(){
  document.getElementById('invLines').innerHTML = inv.lines.map((l, i) => `<tr>
    <td><input type="text" value="${esc(l.name)}" oninput="inv.lines[${i}].name=this.value" style="width:100%"></td>
    <td><textarea oninput="inv.lines[${i}].description=this.value" style="min-height:44px">${esc(l.description)}</textarea></td>
    <td><input type="number" step="any" value="${esc(l.quantity)}" oninput="inv.lines[${i}].quantity=parseFloat(this.value);invTotal()" style="width:64px"></td>
    <td><input type="number" step="0.01" value="${esc(l.unit_price)}" oninput="inv.lines[${i}].unit_price=parseFloat(this.value);invTotal()" style="width:100px"></td>
    <td><input type="checkbox" ${l.taxable ? 'checked' : ''} onchange="inv.lines[${i}].taxable=this.checked"></td>
    ${inv.mode === 'quote' ? `<td><input type="checkbox" ${l.optional ? 'checked' : ''} onchange="inv.lines[${i}].optional=this.checked;invTotal()"></td>` : ''}
    <td><button class="btn s" onclick="inv.lines.splice(${i},1);drawLines()">✕</button></td></tr>`).join('');
  invTotal();
}
// Like Jobber: an optional line is not in the quote's total unless the client picks it.
function invTotal(){
  const sum = ls => ls.reduce((a, l) => a + (l.quantity || 0) * (l.unit_price || 0), 0);
  const opt = inv.mode === 'quote' ? inv.lines.filter(l => l.optional) : [], t = sum(inv.lines.filter(l => !opt.includes(l)));
  document.getElementById('invTotal').textContent = 'Before tax: ' + money(t) + (opt.length ? ` + optional ${money(sum(opt))} if the client picks it` : '') + (inv.doc.subtotal != null && Math.abs(t - inv.doc.subtotal) > 0.005 ? ` (${inv.mode === 'quote' ? 'vendor quote' : 'bill'}: ${money(inv.doc.subtotal)})` : '');
}
async function findClients(){
  const q = document.getElementById('cq').value.trim();
  const box = document.getElementById('cands');
  if (!q) { box.innerHTML = '<div class="note">Type a client name.</div>'; return; }
  box.innerHTML = '<div class="note">Searching Jobber…</div>';
  const j = await api('/jobber/clients?q=' + encodeURIComponent(q));
  if (document.getElementById('cq') && document.getElementById('cq').value.trim() !== q) return;   // still typing: a newer search shows
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  inv.client_id = j.pick ? j.pick.id : null;
  box.innerHTML = (j.candidates || []).map(c => `<div class="cand ${c.id === inv.client_id ? 'on' : ''}" onclick="pickClient(this, '${esc(c.id)}')"><input type="radio" name="cl" ${c.id === inv.client_id ? 'checked' : ''}>
     <div style="flex:1"><b>${esc(c.name)}</b>${c.is_lead ? ' <span class="chip a">lead</span>' : ''}${c.remembered ? ' <span class="chip g">remembered</span>' : ''}<div class="note">${esc(c.remembered || c.address)}</div></div><span class="chip">${Math.round(c.score * 100)}%</span>
     <a href="${esc(c.uri)}" target="_blank" onclick="event.stopPropagation()" class="note">Jobber ↗</a></div>`).join('') || '<div class="note">No clients found - try a shorter name.</div>';
  if ((j.candidates || []).length) box.insertAdjacentHTML('afterbegin', `<div class="note" style="margin-bottom:6px"><b>Click a Jobber client to match it</b>${j.pick ? ' - the ticked one is the best match' : ' - more than one could match'}.</div>`);
  if (inv.mode === 'quote') quoteProps();
  if (inv.client_id && !inv.job) invForClient(inv.client_id);
}
function pickClient(el, id){ inv.client_id = id; document.querySelectorAll('#cands .cand').forEach(c => { c.classList.remove('on'); c.querySelector('input').checked = false; }); el.classList.add('on'); el.querySelector('input').checked = true; if (inv.mode === 'quote') quoteProps(); else invForClient(id); }
// Jobber already has a quote/invoice for this client at this price.
function confirmDuplicate(j){
  const d = j.possible_duplicate || {};
  return confirm(`Jobber already has ${j.error.includes('invoice #') ? 'invoice' : 'quote'} #${d.number} for this client at ${money(d.total)} (${(d.status || '').replace(/_/g, ' ')}, ${d.created || ''}).\n\nOK = draft a new one anyway.\nCancel = don't - open it in Jobber${j.error.includes('quote #') ? ', or link it to the job with "Use a different Jobber quote…"' : ''}.`);
}
// Another of the client's bills on this invoice: its lines in, or out again (Huntington Lakes, Oct 2026).
function invAlso(i, on){
  const o = inv.doc.other_bills[i];
  inv.lines = inv.lines.filter(l => l._from !== o.id);
  if (on) { inv.also.add(o.id); (o.line_items || []).forEach(l => inv.lines.push(Object.assign({}, l, {_from: o.id}))); }
  else inv.also.delete(o.id);
  drawLines();
}
async function createInvoice(){
  if (!inv.client_id) { toast('Choose the Jobber client first.', true); return; }
  const btn = document.getElementById('invGo'); btn.disabled = true; btn.textContent = 'Creating draft…';
  const ibody = {client_id: inv.client_id, client_name: ((document.querySelector('#cands .cand.on b') || {}).textContent || ''), job_id: inv.job ? inv.job.id : (inv.dropped ? '' : null), line_items: inv.lines, subject: document.getElementById('invSubject').value};
  ibody.line_items = inv.lines.map(({_from, ...l}) => l);
  ibody.also_doc_ids = [...(inv.also || [])];
  let j = await api('/docs/' + inv.doc.id + '/invoice', {method:'POST', body: ibody});
  if (!j.success && j.possible_duplicate && confirmDuplicate(j)) j = await api('/docs/' + inv.doc.id + '/invoice', {method:'POST', body: {...ibody, force: true}});
  btn.disabled = false; btn.textContent = 'Create draft in Jobber';
  if (!j.success) { if (!j.possible_duplicate) toast(j.error, true); return; }
  closeModal();
  const v = j.invoice.visit || {};
  toast(`Draft invoice #${j.invoice.invoice_number} created in Jobber (${j.invoice.invoice_status || 'draft'})${(j.invoice.also || []).length ? ` for ${j.invoice.also.length + 1} bills` : ''}. Review and send it from Jobber.` +
    (v.completed ? ` ${v.month} visit (${v.visit.date}) marked complete.` : v.already_complete ? ` ${v.month} visit was already complete.` : v.pending ? ` Visit not marked complete: ${v.pending} (on To do)` : ''), !!v.pending);
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
    ${(s.corrections || []).length ? `<div class="note">✏ Typos in ${esc(d.vendor || 'the vendor')}'s quote corrected for the client: ${s.corrections.map(esc).join(', ')}</div>` : ''}
    <div><b>Jobber client</b><div class="toolbar" style="margin:6px 0"><input type="text" id="cq" oninput="liveSearch(findClients)" onkeydown="if(event.key==='Enter'){event.preventDefault();clearTimeout(window._lsT);findClients()}" value="${esc(d.client_name)}" style="flex:1"><button class="btn" onclick="findClients()">Search</button></div><div id="cands"><div class="note">Searching…</div></div></div>
    <div><b>Property</b><div id="qprops" class="note">Choose the client first.</div></div>
    <div id="qHow" class="note"></div>
    <label class="note" style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="qRemember" checked> Remember: when Wettech writes <input type="text" id="qPlace" value="${esc(d.client_name)}" style="width:140px"> <input type="text" id="qArea" value="${esc(d.site)}" placeholder="area, e.g. back station" style="width:160px"> it means this client and property</label>
    <label class="note">Quote title<input type="text" id="qTitle" value="${esc(s.title)}" style="width:100%"></label>
    <label class="note">Message to the client (optional)<textarea id="qMsg" style="width:100%;min-height:44px"></textarea></label>
    <div><b>Line items</b> <span class="note">(edit before creating)</span><table class="t" style="margin-top:6px"><thead><tr><th>Name</th><th>Description</th><th class="num">Qty</th><th class="num">Unit price</th><th>Tax</th><th title="Optional: the client can pick it in Jobber - not in the total unless they do">Optional</th><th></th></tr></thead><tbody id="invLines"></tbody></table>
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
    <div><b>Jobber client</b><div class="toolbar" style="margin:6px 0"><input type="text" id="rq" oninput="liveSearch(repClients)" onkeydown="if(event.key==='Enter'){event.preventDefault();clearTimeout(window._lsT);repClients()}" value="${esc(d.client_name)}" style="flex:1"><button class="btn" onclick="repClients()">Search</button></div><div id="rcands"></div></div>
    <div><b>Where the note goes</b><div id="rjobs" class="note">Choose the client first.</div></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" id="repGo" onclick="sendReport()">Add note in Jobber</button>`);
  repClients();
}
async function repClients(all){
  const box = document.getElementById('rcands');
  box.innerHTML = '<div class="note">Searching Jobber…</div>';
  // Only clients we do pump work for, unless asked for everyone.
  const q = document.getElementById('rq').value.trim();
  const j = await api('/jobber/clients?pump=1' + (all ? '&all=1' : '') + '&q=' + encodeURIComponent(q));
  if (document.getElementById('rq') && document.getElementById('rq').value.trim() !== q) return;   // still typing
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  box.innerHTML = ((j.candidates || []).map(c => `<div class="cand" data-id="${esc(c.id)}" onclick="repPick('${esc(c.id)}')"><input type="radio" name="rc"><div style="flex:1"><b>${esc(c.name)}</b><div class="note">${esc(c.address)}</div></div><span class="chip">${Math.round(c.score*100)}%</span></div>`).join('') || '<div class="note">No clients found.</div>')
    + (j.hidden ? `<div class="note">${j.hidden} other client${j.hidden > 1 ? 's' : ''} with no pump work hidden · <a href="#" onclick="repClients(true); return false">show all</a></div>` : '');
  // Last time's client (and job) for this name, picked again.
  rep.last_job = (j.pick || {}).job_id || '';
  if (j.pick) repPick(j.pick.id);
}
async function repPick(id){
  rep.client_id = id;
  document.querySelectorAll('#rcands .cand').forEach(c => { const on = c.dataset.id === id; c.classList.toggle('on', on); c.querySelector('input').checked = on; });
  const box = document.getElementById('rjobs');
  box.innerHTML = 'Loading jobs…';
  const j = await api('/jobber/clients/' + encodeURIComponent(id) + '/jobs');
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  const props = Object.fromEntries((j.properties || []).map(p => [p.id, p.label]));
  // A report with a page per pump station (The Carlisle: Entrance and Exit): a note per page, each on its own job.
  // Every page logged already (Log in Jobber again): the whole report as one note.
  const left = (rep.doc.sections || []).filter(g => !g.logged);
  const groups = (rep.doc.sections || []).length > 1 && left.length ? left : [{section: null, location: rep.doc.site || ''}];
  rep.targets = {};
  box.innerHTML = groups.map((g, gi) => {
    const loc = (g.location || '').toLowerCase();
    const words = loc.split(/[^a-z0-9#]+/).filter(w => w.length > 2 && !['pump','pumps','station','the'].includes(w));
    const fits = x => { const t = (x.title + ' ' + (props[x.property_id] || '')).toLowerCase(); return g.section === null ? (loc && t.includes(loc)) : words.some(w => t.includes(w)); };
    const score = x => (x.type !== 'recurring' && x.status === 'archived' ? -9 : 0) + (/pump|fountain|w?e?t+e?ch|quarterly|monthly|maint|annual/i.test(x.title) ? 3 : 0) + (fits(x) ? 2 : 0) + (x.type === 'recurring' && x.status !== 'archived' ? 3 : 0) + (['active','upcoming','today','late'].includes(x.status) ? 1 : 0);
    const jobs = (j.jobs || []).slice().sort((a, b) => score(b) - score(a));
    const last = g.section === null && jobs.find(x => x.id === rep.last_job);
    const t = last ? {type:'job', id: last.id} : jobs.length && score(jobs[0]) >= 3 ? {type:'job', id: jobs[0].id} : {type:'client', id};
    rep.targets[gi] = {...t, section: g.section};
    return (g.section !== null ? `<div class="grp" style="margin-top:8px">${esc(g.location)} page${g.date ? ' · ' + esc(g.date) : ''}</div>` : '')
      + jobs.map(x => `<label class="cand ${t.id === x.id ? 'on' : ''}"><input type="radio" name="rt${gi}" ${t.id === x.id ? 'checked' : ''} onchange="repTarget(this, 'job', '${esc(x.id)}', ${gi})">
      <div style="flex:1"><b>#${esc(x.number)} ${esc(x.title)}</b><div class="note">${esc(x.type)} · ${esc(x.status)} · ${esc(props[x.property_id] || '')}</div></div><a class="note" target="_blank" href="${esc(x.uri)}">↗</a></label>`).join('')
      + `<label class="cand ${t.type === 'client' ? 'on' : ''}"><input type="radio" name="rt${gi}" ${t.type === 'client' ? 'checked' : ''} onchange="repTarget(this, 'client', '${esc(id)}', ${gi})"><div><b>On the client</b> <span class="note">(no single pump job fits)</span></div></label>`;
  }).join('');
  rep.target = rep.targets[0];
}
// The highlight follows the pick (Honda, Oct 2026: it stayed on the first job, so a click looked ignored).
function repTarget(el, type, id, gi){
  gi = gi || 0;
  rep.targets[gi] = {...rep.targets[gi], type, id};
  rep.target = rep.targets[0];
  document.querySelectorAll(`#rjobs input[name="rt${gi}"]`).forEach(i => i.closest('.cand').classList.toggle('on', i === el));
}
async function sendReport(){
  if (!rep.target) { toast('Choose where the note goes.', true); return; }
  const btn = document.getElementById('repGo'); btn.disabled = true;
  const cand = document.querySelector('#rcands .cand.on b');
  let j = null;
  // One note per station's page when the report has more than one.
  for (const [gi, t] of Object.entries(rep.targets || {0: rep.target})) {
    const job = t.type === 'job' && document.querySelector(`#rjobs input[name="rt${gi}"]:checked`)?.closest('.cand')?.querySelector('b');
    j = await api('/docs/' + rep.doc.id + '/report_note', {method:'POST', body:{target_type: t.type, target_id: t.id, section: t.section,
      client_id: rep.client_id, client_name: cand ? cand.textContent : '', job_label: job ? job.textContent : ''}});
    if (!j.success) break;
  }
  btn.disabled = false;
  if (!j.success) { toast(j.error, true); return; }
  const n = Object.keys(rep.targets || {}).length;
  closeModal(); toast((n > 1 ? `Report logged in Jobber - ${n} notes, one per pump station` : 'Report logged in Jobber') + (j.note.note_attached_file ? ' with the file attached.' : ' (with a link to the file).'));
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
  // Only this year's column, unless "All years" is open (the office, Oct 2026).
  const cur = String(new Date().getFullYear());
  const yr = window.SC_ALL_YEARS ? j.years : j.years.filter(y => y === cur);
  const cell = v => !v ? '' : (/^\d{4,6}$/.test(v) ? `<b>${esc(v)}</b>` : `<span class="note">${esc(v)}</span>`);
  const QS = {draft: ['a', 'Draft - send it'], awaiting_response: ['b', 'Sent'], changes_requested: ['a', 'Changes asked'],
              approved: ['g', 'Approved'], converted: ['g', 'Approved'], archived: ['', 'Archived'], rejected: ['r', 'Declined']};
  const quoteCell = s => { const q = s.renewal_quote; if (!q) return '<span class="note">-</span>';
    const [c, l] = QS[q.status] || ['', (q.status || '').replace(/_/g, ' ')];
    return `${q.uri ? `<a target="_blank" rel="noopener" href="${esc(q.uri)}">#${esc(q.number)} ↗</a>` : '#' + esc(q.number)}${l ? ` <span class="chip ${c}">${esc(l)}</span>` : ''}`; };
  const yearsBtn = `<a href="#" onclick="event.preventDefault();window.SC_ALL_YEARS=!window.SC_ALL_YEARS;loadScada()">${window.SC_ALL_YEARS ? 'just ' + cur : 'all years'}</a>`;
  document.getElementById('scadaTable').innerHTML = `<thead><tr><th>Status</th><th>Client</th><th>Renewal date</th><th>Product</th><th class="num">Amount</th><th>Our bill</th><th>Vendor</th><th>Renewal quote</th>${yr.map((y, i) => `<th>${y}${i === yr.length - 1 ? ` <span class="note" style="font-weight:400">· ${yearsBtn}</span>` : ''}</th>`).join('')}<th></th></tr></thead><tbody>` +
    (rows.map(s => `<tr>
      <td><span class="chip ${lab[s.state][0]}">${lab[s.state][1]}</span>${s.complimentary ? ' <span class="chip">complimentary</span>' : ''}${s.days_left != null && s.state !== 'current' && s.state !== 'inactive' ? `<div class="note">${s.days_left < 0 ? -s.days_left + ' days late' : 'in ' + s.days_left + ' days'}</div>` : ''}</td>
      <td><b>${esc(s.client)}</b>${s.notes ? `<div class="note">${esc(s.notes)}</div>` : ''}</td>
      <td style="white-space:nowrap">${esc(s.next_due_on)}</td><td class="note">${esc(s.product)}</td>
      <td class="num">${money(s.vendor_cost)}</td><td>${esc(s.our_bill)}</td><td>${esc(s.vendor)}</td>
      <td style="white-space:nowrap">${quoteCell(s)}</td>
      ${yr.map(y => `<td>${cell(s.years[y])}</td>`).join('')}
      <td style="white-space:nowrap">${s.state !== 'inactive' ? `<button class="btn s p" onclick="scadaRenewed(${s.id})">Renewed…</button> ` : ''}${['overdue','due_soon'].includes(s.state) ? `<button class="btn s" onclick="scadaRenew(${s.id})">${s.case_id ? 'Open item' : 'Start item'}</button> ` : ''}<button class="btn s" onclick="scadaEdit(${s.id})">Edit</button></td></tr>`).join('') || `<tr><td colspan="${9 + yr.length}" class="empty">No SCADA clients.</td></tr>`) + '</tbody>';
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
  closeModal(); loadScada(); refreshAccountPage();
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
  const a = id ? MT.accounts.find(x => x.id === id) : {name:'', kind:'Pump', joined:new Date().toISOString().slice(0, 10), equipment:'', address:'', months:'1,4,7,10', monthly:0, vendor_cost:'', naples_electric:'', our_bill:'', notes:'', repairs_by:'', follow_up:'', active:1};
  MTJ = {client_id: a.jobber_client_id || '', client_name: a.jobber_client_name || '', property_id: a.jobber_property_id || '', property_label: a.jobber_property_label || '', job_id: a.jobber_job_id || '', job_label: a.jobber_job_label || ''};
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
    <label class="w">Repairs by<select id="mt_repairs_by">${[['', 'Wettech (Tom)'], ['SiteOne', 'SiteOne'], ['Naples Electric', 'Naples Electric'], ['Oscar (our technician)', 'Oscar (our technician) - no Wettech quote or bill']].map(([v, l]) => `<option value="${esc(v)}" ${v === (a.repairs_by || '') ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select><span class="note">New repair jobs for this account go to them.</span></label>
    <label class="w">Before each service, follow up with…<textarea id="mt_follow_up" placeholder="e.g. Email Lauren to approve the visit">${esc(a.follow_up || '')}</textarea><span class="note">Shows in the to-do list about a week before each service month.</span></label>
    <div class="w" style="border:1px solid var(--border);border-radius:10px;padding:10px 12px"><b>Jobber</b> <span class="note">- the client, property and recurring maintenance job, so Wettech's quotes and reports for this account go there and its quotes are followed.</span>
      <div style="display:flex;gap:6px;margin-top:6px"><input type="text" id="mt_jq" placeholder="Find the client in Jobber…" value="${esc(a.jobber_client_name || a.name || '')}" style="flex:1"><button class="btn s" type="button" onclick="mtFindClient()">Find</button></div>
      <div id="mt_jobber" style="margin-top:6px"></div></div>
    <label class="w">Notes<textarea id="mt_notes">${esc(a.notes)}</textarea></label>
    <label><span><input type="checkbox" id="mt_active" ${a.active ? 'checked' : ''}> Active account</span></label></div>`,
    `${id ? `<button class="btn danger" onclick="maintDelete(${id})">Remove</button>` : ''}<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="maintSave(${id})">Save</button>`);
  mtJobberDraw();
}
// The account's Jobber client, property and recurring job (picked in the form).
let MTJ = {};
function mtSum(){ const el = document.getElementById('mt_jsum'); if (el) el.innerHTML = MTJ.client_id ? `✓ <b>${esc(MTJ.client_name)}</b>${MTJ.property_label ? ' · ' + esc(MTJ.property_label) : ''}${MTJ.job_label ? ' · job ' + esc(MTJ.job_label) : ' · <span class="warn">no maintenance job picked</span>'} <a href="#" onclick="event.preventDefault();MTJ={};mtJobberDraw()">clear</a>` : 'Not linked to Jobber yet.'; }
function mtJobberDraw(cands, info){
  const el = document.getElementById('mt_jobber'); if (!el) return;
  el.innerHTML = '<div class="note" id="mt_jsum"></div>' + (cands ? cands.map(c => `<div style="display:flex;gap:6px;align-items:center;padding:3px 0"><button class="btn s" type="button" onclick='mtPickClient(${JSON.stringify({id: c.id, name: c.name}).replace(/'/g, "&#39;")})'>Use</button> <b>${esc(c.name)}</b> <span class="note">${esc(c.address || '')}${c.is_lead ? ' · lead' : ''}</span></div>`).join('') || '<div class="note">No Jobber client found - add the client in Jobber first, then Find again.</div>' : '') + (info || '');
  mtSum();
}
async function mtFindClient(){
  const q = document.getElementById('mt_jq').value.trim(); if (!q) return;
  const j = await api('/jobber/clients?q=' + encodeURIComponent(q));
  if (!j.success) { toast(j.error, true); return; }
  mtJobberDraw(j.candidates || []);
}
function mtSet(sel, idKey, labelKey){ const o = sel.selectedOptions[0]; MTJ[idKey] = sel.value; MTJ[labelKey] = sel.value ? (o.dataset.l || '') : ''; mtSum(); }
async function mtPickClient(c){
  MTJ = {client_id: c.id, client_name: c.name, property_id: '', property_label: '', job_id: '', job_label: ''};
  mtJobberDraw(null, '<div class="note">Loading its properties and jobs…</div>');
  const j = await api('/jobber/clients/' + encodeURIComponent(c.id) + '/jobs');
  if (!j.success) { mtJobberDraw(null, `<div class="note bad">${esc(j.error)}</div>`); return; }
  const props = j.properties || [], jobs = (j.jobs || []).filter(x => x.status !== 'archived').sort((a, b) => (b.type === 'recurring') - (a.type === 'recurring'));
  if (props.length === 1) Object.assign(MTJ, {property_id: props[0].id, property_label: props[0].label});
  const rec = jobs.filter(x => x.type === 'recurring');
  // Several (The Carlisle: one per pump): the one at its property, else the first pump one.
  const pick = rec.find(x => MTJ.property_id && x.property_id === MTJ.property_id) || rec.find(x => /pump/i.test(x.title)) || rec[0];
  if (pick) Object.assign(MTJ, {job_id: pick.id, job_label: rec.map(x => '#' + x.number).join(', ') + ' ' + pick.title});
  const addr = document.getElementById('mt_address'); if (addr && !addr.value && MTJ.property_label) addr.value = MTJ.property_label;
  mtJobberDraw(null, `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
    <select onchange="mtSet(this, 'property_id', 'property_label')"><option value="">Property…</option>${props.map(p => `<option value="${esc(p.id)}" data-l="${esc(p.label)}" ${p.id === MTJ.property_id ? 'selected' : ''}>${esc(p.label)}</option>`).join('')}</select>
    <select onchange="mtSet(this, 'job_id', 'job_label')"><option value="">Maintenance job…${rec.length ? '' : ' (none recurring yet - a to-do to set one up)'}</option>${jobs.map(x => `<option value="${esc(x.id)}" data-l="${esc('#' + x.number + ' ' + x.title)}" ${x.id === MTJ.job_id ? 'selected' : ''}>#${esc(x.number)} ${esc(x.title)}${x.type === 'recurring' ? ' (recurring)' : ''}</option>`).join('')}</select></div>`);
}
async function maintSave(id){
  const v = k => document.getElementById('mt_' + k).value;
  const body = {name: v('name'), kind: v('kind'), joined: v('joined'), equipment: v('equipment'), address: v('address'), vendor_cost: v('vendor_cost'), naples_electric: v('naples_electric'), our_bill: v('our_bill'), notes: v('notes'), repairs_by: v('repairs_by'), follow_up: v('follow_up'), monthly: document.getElementById('mt_monthly').checked, active: document.getElementById('mt_active').checked, months: [...document.querySelectorAll('.mt_m:checked')].map(x => x.value).join(','),
    ...Object.fromEntries(Object.entries(MTJ).map(([k, v]) => ['jobber_' + k, v || '']))};
  if (id) body.id = id;
  const j = await api('/maint', {method:'POST', body});
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); MT.accounts = j.accounts; drawMaint(); refreshAccountPage();
}
async function maintDelete(id){ if (!confirm('Remove this account? (Untick "Active" instead to keep it as a former account.)')) return; const j = await api('/maint/' + id + '/delete', {method:'POST', body:{}}); if (j.success) { closeModal(); MT.accounts = j.accounts; drawMaint(); refreshAccountPage(); } }
async function scadaAdd(){ const v = x => document.getElementById(x).value; const j = await api('/scada', {method:'POST', body:{client_name:v('sa_client'), site:v('sa_site'), last_renewed_on:v('sa_last'), annual_amount:v('sa_amt')}}); if (j.success) { closeModal(); loadScada(); } else toast(j.error, true); }

// ── Jobber ────────────────────────────────────────────
// ── accounts ──────────────────────────────────────
let AC = null;
async function loadAccounts(){
  try { const v = localStorage.getItem('acSort'); if (v) document.getElementById('acSort').value = v; } catch (e) {}
  await refreshAccounts(); loadDivers(); loadSiteNames();
}
async function refreshAccounts(){
  const [a, m] = await Promise.all([api('/accounts'), api('/maint')]);
  if (!a.success) { document.getElementById('acBody').innerHTML = `<tr><td colspan="4" class="empty">${esc(a.error)}</td></tr>`; return; }
  AC = a; if (m.success) MT = m; drawAccounts();
}
// Pump maintenance, filter cleaning (the lake diver) and SCADA: green when the
// account has it, grey when it doesn't - click a grey one to quote it.
const SVC = [['pump', 'Pump'], ['filter', 'Filter'], ['scada', 'SCADA'], ['irrigation', 'Irrigation']];
// The Show: chips - each one ticked or not; the list keeps the accounts with any ticked service.
let SVC_ON = (() => { try { const v = JSON.parse(localStorage.getItem('acSvc') || 'null'); if (Array.isArray(v)) return new Set(v); } catch (e) {} return new Set(SVC.map(x => x[0])); })();
function drawSvcPicks(){
  const box = document.getElementById('svcPicks'); if (!box) return;
  box.innerHTML = SVC.map(([k, label]) => `<span class="svc ${SVC_ON.has(k) ? 'on' : 'off'}" style="cursor:pointer;margin-right:4px" title="${SVC_ON.has(k) ? 'Click to hide' : 'Click to show'} accounts with ${label.toLowerCase()}" onclick="svcToggle('${k}')">${SVC_ON.has(k) ? '✓ ' : ''}${label}</span>`).join('');
}
function svcToggle(k){
  SVC_ON.has(k) ? SVC_ON.delete(k) : SVC_ON.add(k);
  try { localStorage.setItem('acSvc', JSON.stringify([...SVC_ON])); } catch (e) {}
  drawAccounts();
}
// The accounts on screen, as a spreadsheet.
let AC_ROWS = [];
async function accountsSheet(){
  if (!AC_ROWS.length) { toast('No accounts shown to download.', true); return; }
  const sel = document.getElementById('acShow'), sort = document.getElementById('acSort'), q = document.getElementById('acSearch').value.trim();
  const title = [sel.options[sel.selectedIndex].text, SVC_ON.size < SVC.length ? 'with ' + SVC.filter(x => SVC_ON.has(x[0])).map(x => x[1]).join(' or ') : '', q ? `"${q}"` : '', sort.options[sort.selectedIndex].text.replace('Sort: ', 'by ')].filter(Boolean).join(' - ');
  const r = await fetch('/pumps/api/accounts/export.xlsx', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({names: AC_ROWS.map(a => a.name), title})});
  if (!r.ok) { toast('Could not make the sheet (' + r.status + ')', true); return; }
  const blob = await r.blob(), url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = ((r.headers.get('Content-Disposition') || '').match(/filename="?([^";]+)/) || [])[1] || 'Accounts.xlsx';
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
  toast(`Downloaded ${AC_ROWS.length} accounts.`);
}
function hasSvc(a, k){
  if (k === 'pump') return !!(a.pump && a.pump.active);
  if (k === 'filter') return !!(a.lake && a.lake.active !== 0);
  if (k === 'irrigation') return !!((a.irrigation && a.irrigation.managed) || (a.contracts || []).some(c => c.status === 'active' && c.irrigation));
  return !!(a.scada && a.scada.active);
}
function svcBadges(a){
  const nm = JSON.stringify(a.name).replace(/"/g, '&quot;');
  return SVC.map(([k, label]) => {
    if (hasSvc(a, k)) {
      const tip = k === 'scada' ? (a.scada.complimentary ? 'SCADA - included / complimentary' : 'SCADA - renews ' + (a.scada.next_due_on || '?'))
        : k === 'pump' ? 'Pump maintenance' + (a.pump.jobber_client_id ? ' · linked to Jobber: ' + (a.pump.jobber_client_name || '') : '')
        : k === 'irrigation' ? 'We manage their irrigation' + ((a.contracts || []).some(c => c.status === 'active' && c.irrigation) ? ' - maintenance contract' : (a.irrigation || {}).job ? ' - Jobber job ' + a.irrigation.job : (a.irrigation || {}).how === 'office' ? ' (set by the office)' : '') : 'Filter cleaning (diver)';
      return `<span class="svc on" title="${esc(tip)}">${label}${k === 'scada' && a.scada.complimentary ? ' (incl.)' : ''}</span>`;
    }
    const why = k === 'irrigation' && !(a.irrigation || {}).checked_at ? 'Not checked in Jobber yet' : 'No ' + label.toLowerCase();
    return a.active ? `<span class="svc off" title="${esc(why)} - click to draft a quote in Jobber" onclick="event.stopPropagation();serviceQuote(${nm}, '${k}')">＋ ${label}</span>` : `<span class="svc none">${label}</span>`;
  }).join(' ');
}
// Draft a quote for a service the account doesn't have - worded like the office's past Jobber quotes.
let SQ = null;
async function serviceQuote(name, kind){
  if (!JOBBER_OK) { toast('Connect Jobber first (top of the page).', true); return; }
  const j = await api('/accounts/service_quote?name=' + encodeURIComponent(name) + '&kind=' + kind);
  if (!j.success) { toast(j.error, true); return; }
  SQ = j;
  const li = j.line_items[0];
  openModal(`Quote ${esc(j.label)} - ${esc(name)}`, `
    <div class="safe">This creates a DRAFT quote in Jobber. Nothing is sent - look it over in Jobber and send it from there.</div>
    <label class="note">Jobber client<div class="toolbar" style="margin:4px 0"><input type="text" id="sqQ" value="${esc((j.client || {}).name || name)}" style="flex:1" oninput="liveSearch(sqClients)"><button class="btn" onclick="sqClients()">Search</button></div></label>
    <div id="sqCands"><div class="note">Searching Jobber…</div></div>
    <label class="note">Property<select id="sqProp" style="width:100%">${sqProps(j.properties, j.property_id)}</select></label>
    <label class="note">Quote title<input type="text" id="sqTitle" value="${esc(j.title)}" style="width:100%"></label>
    <label class="note">Line<input type="text" id="sqLine" value="${esc(li.name)}" style="width:100%"></label>
    <label class="note">Description<textarea id="sqDesc" rows="9" style="width:100%">${esc(li.description)}</textarea></label>
    ${kind === 'irrigation' ? `<div class="${j.zones ? 'note' : 'issue'}" style="margin-top:6px">${j.zones ? `${j.zones} zones (from the account's notes) × ${money(j.per_zone)} per zone = <b>${money(j.zones * j.per_zone)}</b> a month.` : `Number of zones undetermined - nothing in the account's notes says how many. Price it by hand (${money(j.per_zone)} per zone a month).`}</div>` : ''}
    <label class="note">Price per ${kind === 'scada' ? 'year' : kind === 'irrigation' ? 'month' : 'visit'} ($)<input type="number" id="sqPrice" value="${li.unit_price ?? ''}" placeholder="price" style="width:160px"></label>`,
    `${kind === 'irrigation' ? `<button class="btn" style="margin-right:auto" title="Jobber didn't show it, but we do manage their irrigation" onclick="irrigationManaged(${JSON.stringify(name).replace(/"/g, '&quot;')}, true)">We already manage it</button>` : ''}<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" id="sqGo" onclick="serviceQuoteGo()">Create draft in Jobber</button>`);
  sqClients();   // already searched - the match ticked, the rest a click away
}
async function irrigationManaged(name, managed){
  const j = await api('/accounts/irrigation', {method:'POST', body:{name, managed}});
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); toast(name + (managed ? ': we manage their irrigation.' : ": we don't manage their irrigation."));
  refreshAccounts();
}
async function irrigationCheck(){
  const j = await api('/accounts/irrigation/check', {method:'POST', body:{}});
  if (!j.success) { toast(j.error, true); return; }
  toast('Checking Jobber for every account - give it a minute, then the Irrigation badges update.');
  setTimeout(refreshAccounts, 60000);
}
function sqProps(props, pick){ return (props || []).length ? props.map(p => `<option value="${esc(p.id)}" ${p.id === pick ? 'selected' : ''}>${esc(p.label)}</option>`).join('') : '<option value="">(pick the client first)</option>'; }
async function sqClients(){
  const q = document.getElementById('sqQ').value.trim(), box = document.getElementById('sqCands');
  box.innerHTML = '<div class="note">Searching Jobber…</div>';
  const j = await api('/jobber/clients?all=1&q=' + encodeURIComponent(q));
  if (!j.success) { box.innerHTML = `<div class="issue">${esc(j.error)}</div>`; return; }
  if (document.getElementById('sqQ') && document.getElementById('sqQ').value.trim() !== q) return;   // still typing
  const cands = j.candidates || [], cur = (SQ.client || {}).id;
  if (cur && !cands.some(c => c.id === cur)) cands.unshift({id: cur, name: SQ.client.name || 'The account\'s Jobber client', address: 'linked to this account'});
  box.innerHTML = (cands.length ? `<div class="note" style="margin:4px 0"><b>Click a Jobber client to match it</b>${cur ? ' - the ticked one is the best match' : ''}.</div>` : '')
    + cands.map(c => `<div class="cand ${c.id === cur ? 'on' : ''}" data-id="${esc(c.id)}" onclick="sqPick('${esc(c.id)}', ${JSON.stringify(c.name).replace(/"/g, '&quot;')})"><input type="radio" name="sqc" ${c.id === cur ? 'checked' : ''}><div style="flex:1"><b>${esc(c.name)}</b><div class="note">${esc(c.address || '')}</div></div>${c.uri ? `<a href="${esc(c.uri)}" target="_blank" onclick="event.stopPropagation()" class="note">Jobber ↗</a>` : ''}</div>`).join('')
    || '<div class="note">No clients found - try a shorter name.</div>';
}
async function sqPick(id, name){
  SQ.client = {id, name};
  document.querySelectorAll('#sqCands .cand').forEach(c => { const on = c.dataset.id === id; c.classList.toggle('on', on); c.querySelector('input').checked = on; });
  const j = await api('/jobber/clients/' + encodeURIComponent(id) + '/jobs');
  SQ.properties = (j.properties || []);
  document.getElementById('sqProp').innerHTML = sqProps(SQ.properties, SQ.properties.length === 1 ? SQ.properties[0].id : '');
}
async function serviceQuoteGo(){
  const v = id => document.getElementById(id).value;
  if (!SQ.client || !SQ.client.id) { toast('Choose the Jobber client.', true); return; }
  if (!v('sqPrice')) { toast('Put a price on the quote.', true); return; }
  const btn = document.getElementById('sqGo'); btn.disabled = true;
  const j = await api('/accounts/service_quote', {method:'POST', body:{name: SQ.account, kind: SQ.kind, client_id: SQ.client.id, property_id: v('sqProp'), title: v('sqTitle'),
    line_items: [{name: v('sqLine'), description: v('sqDesc'), quantity: 1, unit_price: parseFloat(v('sqPrice')), taxable: false}]}});
  btn.disabled = false;
  if (!j.success) { toast(j.error, true); return; }
  closeModal(); toast(`Draft quote #${j.quote.number} made in Jobber - on your To do list to send.`);
  if (j.quote.uri) window.open(j.quote.uri, '_blank');
  loadToday();
}
function lakeSched(l){ return l.months ? (l.months === '1,4,7,10' ? 'Jan, Apr, Jul, Oct' : l.months.split(',').map(m => MSHORT[m - 1]).join(', ')) : 'Every month'; }
function drawAccounts(){
  if (!AC) return;
  const show = document.getElementById('acShow').value, q = document.getElementById('acSearch').value.trim().toLowerCase();
  const due = a => (a.pump && a.pump.due_this_month) || (a.lake && a.lake.due_this_month && a.lake.needs_dive);
  const ok = a => !show ? true : show === 'active' ? a.active : show === 'former' ? !a.active : show === 'due' ? a.active && due(a) :
    show === 'pump' ? hasSvc(a, 'pump') : show === 'lake' ? hasSvc(a, 'filter') : show === 'scada' ? hasSvc(a, 'scada') :
    show === 'no_pump' ? a.active && !hasSvc(a, 'pump') : show === 'no_filter' ? a.active && !hasSvc(a, 'filter') : show === 'no_scada' ? a.active && !hasSvc(a, 'scada') : show === 'no_irrigation' ? a.active && !hasSvc(a, 'irrigation') :
    show === 'contract' ? (a.contracts || []).some(c => c.status === 'active') : true;
  drawSvcPicks();
  const allSvc = SVC_ON.size === SVC.length;
  const rows = AC.accounts.filter(a => ok(a) && (allSvc || [...SVC_ON].some(k => hasSvc(a, k))) && (!q || JSON.stringify([a.name, a.pump && a.pump.address, a.lake && a.lake.address, (a.contracts || []).map(c => c.account + ' ' + c.line)]).toLowerCase().includes(q)));
  const act = AC.accounts.filter(a => a.active);
  const cons = AC.accounts.flatMap(a => (a.contracts || []).filter(c => c.status === 'active'));
  document.getElementById('acInfo').innerHTML = `${act.length} active accounts · ${act.filter(a => a.pump && a.pump.active).length} pump · ${act.filter(a => a.lake && a.lake.active !== 0).length} lake · ${new Set(cons.map(c => c.account)).size} maintenance contracts (${money(cons.reduce((t, c) => t + (c.frequency === 'monthly' ? c.amount || 0 : 0), 0))}/mo) · <b>${act.filter(due).length} due in ${esc(AC.month)}</b>`;
  const st = {overdue:'r', due_soon:'a', current:'g', inactive:'', unknown:''};
  const nextDue = a => { const out = [], now = new Date().getMonth() + 1;
    const next = (ms, every) => { if (every) return 'this month'; const m = (ms || '').split(',').filter(Boolean).map(Number); if (!m.length) return '';
      const n = m.find(x => x >= now) || m[0]; return n === now ? 'this month' : MSHORT[n - 1]; };
    if (a.pump && a.pump.active) out.push('Pump ' + (a.pump.due_this_month ? 'this month' : next(a.pump.months, a.pump.monthly)));
    if (a.lake && a.lake.active !== 0 && a.lake.needs_dive) out.push('Diver ' + (a.lake.status === 'hold' ? 'on hold' : next(a.lake.months, !a.lake.months)));
    if (a.scada && a.scada.active && !a.scada.complimentary) out.push((a.scada.state === 'overdue' ? 'SCADA renewal overdue ' : 'SCADA renews ') + (a.scada.next_due_on || ''));
    return out; };
  const sort = document.getElementById('acSort').value;
  const monthly = a => (a.contracts || []).filter(c => c.status === 'active').reduce((t, c) => t + (c.amount || 0), 0);
  rows.sort((x, y) => sort === 'type' ? (contractType(x)[0] - contractType(y)[0]) || x.name.localeCompare(y.name)
    : sort === 'amount' ? (monthly(y) - monthly(x)) || x.name.localeCompare(y.name) : x.name.localeCompare(y.name));
  AC_ROWS = rows;
  let lastType = null;
  document.getElementById('acBody').innerHTML = rows.map(a => { const p = a.pump, l = a.lake, s = a.scada, vis = a.visit;
    const t = contractType(a), head = sort === 'type' && t[1] !== lastType ? `<tr><td colspan="4" class="grp" style="padding-top:12px">${esc(t[1])} <span class="note">(${rows.filter(x => contractType(x)[1] === t[1]).length})</span></td></tr>` : '';
    lastType = t[1];
    return head + rowHtml(a, p, l, s, vis, nextDue); }).join('') || '<tr><td colspan="4" class="empty">None.</td></tr>';
}
function rowHtml(a, p, l, s, vis, nextDue){
    const on = svcBadges(a);
    return `<tr class="click" onclick="openAccount(${JSON.stringify(a.name).replace(/"/g, '&quot;')})"><td><b>${esc(a.name)}</b>${!a.active ? ' <span class="chip">former</span>' : ''}${vis ? `<div class="note">✓ Client approved ${esc((vis.link || {}).since || '')}</div>` : ''}</td>
    <td style="white-space:nowrap">${on || '<span class="note">—</span>'}</td>
    <td>${nextDue(a).map(x => /overdue/.test(x) ? `<b class="bad">${esc(x)}</b>` : /this month/.test(x) ? `<b>${esc(x)}</b>` : esc(x)).join('<br>') || '<span class="note">—</span>'}</td>
    <td class="note">${esc((p && p.address) || (l && l.address) || '')}</td></tr>`;
}
// An account's kind of contract, for sorting and grouping: [order, label].
function contractType(a){
  const cs = a.contracts || [], act = cs.filter(c => c.status === 'active');
  if (!cs.length) return [9, 'No maintenance contract'];
  if (!act.length) return [8, 'Cancelled contracts'];
  const f = new Set(act.map(c => c.frequency));
  if (f.has('monthly')) return [1, 'Monthly maintenance'];
  if (f.has('bi-monthly')) return [2, 'Bi-monthly maintenance'];
  if (f.has('quarterly')) return [3, 'Quarterly maintenance'];
  return [4, 'Parts / as used only'];
}
// The client called: ready for their maintenance. The lake comes off hold for
// the diver list and the visit waits under "Waiting on others" until the
// vendors' service reports come in.
// Only the subcontractors the account actually has - a pump-only account never mentions Jordan, a lake-only one never Justin.
const VENDOR_WHO = {Wettech: 'Justin (Wettech)', Gulfshore: 'Jordan (Gulfshore)'};
function accountVendors(a){
  const p = a && a.pump, l = a && a.lake, v = [];
  if (p && p.active) v.push('Wettech');
  if (l && l.active !== 0 && l.needs_dive !== 0) v.push('Gulfshore');
  return v;
}
async function accountReady(name){
  const v = accountVendors(AC && AC.accounts.find(x => x.name === name)), who = v.map(x => VENDOR_WHO[x]).join(' and ');
  if (!confirm(`${name} is ready for their maintenance (client approved)?\n\n` + (v.includes('Gulfshore') ? 'Their lake comes off hold for the diver list, and the' : 'The')
    + ` visit is followed under "Waiting on others" until ${who ? who + "'s service report" + (v.length > 1 ? 's come' : ' comes') : 'the service report comes'} in.`)) return;
  const j = await api('/accounts/ready', {method:'POST', body:{name}});
  if (!j.success) { toast(j.error, true); return; }
  toast(`${name}: ${j.vendors.join(' and ')} going out` + (j.unheld ? ' - off hold on the diver list' : '') + `. Let ${j.vendors.map(x => VENDOR_WHO[x] || x).join(' and ')} know to put it on the schedule.`);
  loadAccounts(); loadToday(); refreshAccountPage();
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
  closeModal(); toast('Saved'); loadDivers(); refreshAccountPage();
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
    <div><b>It means this Jobber client</b><div class="toolbar" style="margin:6px 0"><input type="text" id="cq" oninput="liveSearch(findClients)" onkeydown="if(event.key==='Enter'){event.preventDefault();clearTimeout(window._lsT);findClients()}" placeholder="e.g. Hodges Funeral Home" style="flex:1"><button class="btn" onclick="findClients()">Search</button></div><div id="cands"></div></div>`,
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
// Sections folded away stay folded (this browser only): the not-urgent quotes, the maintenance list.
function foldOpen(k){ try { return localStorage.getItem('pumps.fold.' + k) !== 'closed'; } catch (e) { return true; } }
function foldSave(k, open){ try { localStorage.setItem('pumps.fold.' + k, open ? 'open' : 'closed'); } catch (e) {} }
(() => { const mf = document.getElementById('msFold'); if (mf && !foldOpen('ms')) mf.open = false; })();
// The quote steps: an item here is still a quote, not yet a job.
const QUOTE_STAGES = ['assessment', 'vendor_quote', 'client_quote', 'client_approved'];
async function setUrgent(id, on){
  const j = await api('/cases/' + id + '/urgent', {method:'POST', body:{on}});
  if (!j.success) { toast(j.error, true); return; }
  toast(on ? 'Urgent - up with the jobs' : 'Back with the quotes that can wait'); loadJobs();
}
async function loadJobs(){
  loadMaintSchedule();
  const show = document.getElementById('jbShow').value, st = show === 'waiting' ? 'open' : show, q = document.getElementById('jbSearch').value.trim();
  const [j, ji] = await Promise.all([api('/cases?status=' + st + (q ? '&q=' + encodeURIComponent(q) : '')), api('/jobber/items?open=1&kind=quote&show_ignored=1')]);
  if (!j.success) { document.getElementById('jobsBody').innerHTML = `<tr><td colspan="9" class="empty">${esc(j.error)}</td></tr>`; return; }
  const ref = r => r ? (r.uri ? `<a href="${esc(r.uri)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">#${esc(r.number || '')} ↗</a>` : (r.number ? '#' + esc(r.number) : '')) : '';
  // Quotes wait at the bottom under "Quotes - not urgent" unless marked urgent (Oct 2026).
  const isQuote = c => c.status === 'open' && QUOTE_STAGES.includes(c.stage);
  const quietQ = c => isQuote(c) && !c.urgent;
  const all = (j.cases || []).filter(c => show !== 'waiting' || /waiting/i.test(stageText(c))), main = all.filter(c => !quietQ(c)), quiet = all.filter(quietQ);
  const row = c => { const jb = c.jobber || {}, vp = c.vendor_pay || {};
    return `<tr class="click" onclick="openCase(${c.id})">
    <td><b title="${esc(c.title || c.client_name)}">${esc(c.short_title || c.title || c.client_name)}</b><div class="note">${esc([c.client_name, c.site].filter(Boolean).join(' · '))}${c.po_number ? ' · PO ' + esc(c.po_number) : ''}${jobberNo(c)}</div></td>
    <td>${c.urgent && isQuote(c) ? '<span class="chip r">urgent</span> ' : ''}${stageChip(c)}${statusLine(c) ? `<div class="note">${statusLine(c)}</div>` : ''}${c.status === 'open' ? lastAction(c) : ''}</td>
    <td>${esc(c.vendor)}</td><td>${numAmt(c.vendor_quote_number, c.vendor_quote_amount ?? c.vendor_quote_total)}</td>
    <td>${ref(jb.quote)}${jb.quote && jb.quote.total != null ? ' <b>' + money(jb.quote.total) + '</b>' : ''}${jb.quote && jb.quote.status ? ` <span class="note">${esc(jb.quote.status.replace(/_/g, ' '))}</span>` : ''}</td>
    <td>${numAmt(c.vendor_bill_number, c.vendor_bill_amount ?? c.vendor_bill_total)}</td>
    <td>${ref(jb.invoice) || (c.sei_invoice_number ? '#' + esc(c.sei_invoice_number) : '')}${(jb.invoice || c.sei_invoice_number) && ((jb.invoice || {}).total ?? c.amount) != null ? ' <b>' + money((jb.invoice || {}).total ?? c.amount) + '</b>' : ''}${jb.invoice && jb.invoice.status ? ` <span class="note">${esc(jb.invoice.status.replace(/_/g, ' '))}</span>` : ''}</td>
    <td>${vp.state === 'paid' ? '<span class="chip g">paid</span>' : vp.state === 'due' ? '<span class="chip r">pay now</span>' : vp.state === 'unpaid' ? '<span class="note">not yet</span>' : ''}</td>
    <td style="white-space:nowrap">${isQuote(c) ? (c.urgent ? `<button class="btn s" title="Back to Quotes - not urgent" onclick="event.stopPropagation();setUrgent(${c.id}, false)">⬇ Not urgent</button> ` : `<button class="btn s" title="Move it up with the jobs" onclick="event.stopPropagation();setUrgent(${c.id}, true)">⬆ Urgent</button> `) : ''}${jb.job && jb.job.uri ? `<a class="btn s" href="${esc(jb.job.uri)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Jobber ↗</a> ` : ''}${c.status === 'open' && c.stage === 'client_approved' ? `<button class="btn s p" title="Email the client a follow-up on our quote" onclick="event.stopPropagation();clientEmail(${c.id})">✉ Follow up</button> ` : ''}${c.status === 'open' ? `<button class="btn s" title="Mark done" onclick="event.stopPropagation();caseDone(${c.id})">✓ Done</button> <button class="btn s" title="Remove" onclick="event.stopPropagation();caseRemove(${c.id})">✕</button>` : `<button class="btn s" onclick="event.stopPropagation();caseReopen(${c.id})">↺ Reopen</button>`}</td></tr>`; };
  // A-Z by Jobber account; an account with several jobs gets its name as a heading over them.
  const acct = c => c.account_name || c.client_name || c.title || '', jobName = c => c.short_title || c.title || c.client_name || '';
  const grouped = list => { const g = new Map();
    [...list].sort((a, b) => acct(a).localeCompare(acct(b), undefined, {sensitivity:'base'}) || jobName(a).localeCompare(jobName(b), undefined, {sensitivity:'base'}))
      .forEach(c => { const k = acct(c).toLowerCase(); if (!g.has(k)) g.set(k, []); g.get(k).push(c); });
    return [...g.values()].map(cs => (cs.length > 1 ? `<tr><td colspan="9" style="background:var(--bg);font-weight:700;padding-top:10px">${esc(acct(cs[0]))} <span class="chip">${cs.length} jobs</span></td></tr>` : '') + cs.map(row).join('')).join(''); };
  document.getElementById('jobsBody').innerHTML = (grouped(main) || '<tr><td colspan="9" class="empty">No jobs.</td></tr>')
    + (quiet.length ? `<tr class="click" onclick="foldSave('qq', !foldOpen('qq'));loadJobs()"><td colspan="9" style="background:var(--bg);font-weight:700;padding-top:14px">${foldOpen('qq') ? '▾' : '▸'} Quotes - not urgent (${quiet.length}) <span class="note" style="font-weight:400">· click to ${foldOpen('qq') ? 'fold away' : 'show'} · ⬆ Urgent moves one up with the jobs</span></td></tr>` + (foldOpen('qq') ? grouped(quiet) : '') : '');
  const s = ji.sync || {};
  document.getElementById('syncInfo').innerHTML = !JOBBER_OK ? '<b class="warn">Jobber is not connected.</b>' :
    (s.state === 'running' ? `Syncing Jobber… (started ${esc(s.started_at || '')})` : (s.state === 'failed' || s.state === 'interrupted' ? `<b class="bad">Last sync did not finish</b> - it runs again on its own · ` : '') + (s.finished_at ? `Synced with Jobber ${esc(s.finished_at.slice(11, 16))}` + (s.seconds != null && s.state === 'done' ? ` (took ${s.seconds < 90 ? s.seconds + ' sec' : Math.round(s.seconds / 60) + ' min'})` : '') : 'Not synced yet.') + (s.every_min ? ` · syncs on its own every ${s.every_min} min` : '')) + ((s.errors || []).length ? ` · <span class="bad" title="${esc(s.errors.join('\n'))}">${s.errors.length} errors</span>` : '');
  clearTimeout(window._syncPoll);
  if (s.state === 'running') window._syncPoll = setTimeout(() => { if (curTab === 'jobs') loadJobs(); }, 5000);
}
// Sign the approved vendor quote ("Simon Weardon 10/12/2026" typed on it),
// save it here and on the Jobber quote, and email it to the vendor.
async function signQuote(caseId){
  const p = await api('/cases/' + caseId + '/sign_quote');
  if (!p.success) { toast(p.error, true); if (/upload/i.test(p.error || '')) openCase(caseId); return; }
  const e = p.email, d = p.doc;
  openModal(`Sign quote and send it to ${esc(e.name || e.to)}`, `<div class="note" style="margin-bottom:8px">Types <b>${esc(d.signed_as)}</b> on <b>${esc(d.file_name)}</b>, saves the signed quote on this job and on the Jobber quote, and emails it from the PO mailbox. When ${esc(e.name || 'they')} replies with a date, the app puts it on the job and in Jobber.${d.sent_at ? `<br><b class="warn">Already sent ${esc(d.sent_at)}.</b>` : ''}</div>
    <div class="note">To: <b>${esc(e.to || 'no email saved')}</b><br>Subject: ${esc(e.subject)}</div>
    <textarea id="sq_body" rows="9" style="width:100%;margin-top:8px">${esc(e.body)}</textarea>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn" onclick="signQuoteGo(${caseId}, false)">Only sign it</button><button class="btn p" id="sq_go" onclick="signQuoteGo(${caseId}, true)">✍ Sign &amp; send</button>`);
}
// The email to send the signed quote with, to copy into Outlook (Oct 2026: the office sends it itself).
async function signedQuoteMessage(caseId){
  const p = await api('/cases/' + caseId + '/sign_quote');
  if (!p.success) { toast(p.error, true); return; }
  const e = p.email, cp = (id, what) => `<button class="btn s" onclick="navigator.clipboard.writeText(document.getElementById('${id}').value);toast('${what} copied')">Copy</button>`;
  openModal(`Message to ${esc(e.name || e.to || 'the vendor')}`, `
    <div class="note" style="margin-bottom:8px">Copy it into Outlook and attach the signed quote (⬇ Download signed quote), then click <b>I already sent it</b>.</div>
    <label class="note">To</label><div style="display:flex;gap:6px;margin-bottom:6px"><input type="text" id="sm_to" value="${esc(e.to || '')}" readonly style="flex:1">${cp('sm_to', 'Email address')}</div>
    <label class="note">Subject</label><div style="display:flex;gap:6px;margin-bottom:6px"><input type="text" id="sm_subject" value="${esc(e.subject)}" readonly style="flex:1">${cp('sm_subject', 'Subject')}</div>
    <label class="note">Message</label><textarea id="sm_body" rows="10" style="width:100%">${esc(e.body)}</textarea>`,
    `<button class="btn" onclick="closeModal()">Close</button><button class="btn" onclick="signedQuote(${caseId}, true)">⬇ Download signed quote</button><button class="btn p" onclick="navigator.clipboard.writeText(document.getElementById('sm_body').value);toast('Message copied - paste it into Outlook')">Copy message</button>`);
}
// The approved quote signed (saved on the job and the Jobber quote, not emailed): downloaded, or opened to look at.
async function signedQuote(caseId, download){
  const w = download ? null : window.open('', '_blank');
  const j = await api('/cases/' + caseId + '/sign_quote', {method:'POST', body:{send: false}});
  if (!j.success) { if (w) w.close(); toast(j.error, true); if (/upload/i.test(j.error || '')) openCase(caseId); return; }
  const url = '/pumps/api/docs/' + j.doc_id + '/file?version=approved';
  if (download) { window.location.href = url + '&download=1'; toast('Signed quote downloaded - send it, then click I already sent it.'); }
  else if (w) w.location.href = url; else window.open(url, '_blank');
  loadToday();
}
async function signQuoteGo(caseId, send){
  const b = document.getElementById('sq_go'); if (b) { b.disabled = true; b.textContent = 'Sending…'; }
  const j = await api('/cases/' + caseId + '/sign_quote', {method:'POST', body:{send, body: (document.getElementById('sq_body') || {}).value}});
  if (!j.success) { toast(j.error, true); if (b) { b.disabled = false; b.textContent = '✍ Sign & send'; } return; }
  closeModal();
  toast(j.emailed ? `Signed and sent to ${j.emailed}` + (j.note_error ? ' (not on the Jobber quote: ' + j.note_error + ')' : j.jobber_note ? ' · saved on the Jobber quote' : '') : 'Signed - ' + j.signed);
  window.open('/pumps/api/docs/' + j.doc_id + '/file?version=approved&download=1');
  loadToday(); if (curTab === 'jobs') loadJobs();
}
async function jobberAct(id, action){ const j = await api('/jobber/items/' + encodeURIComponent(id), {method:'POST', body:{action}}); if (!j.success) { toast(j.error, true); return; } loadToday(); if (curTab === 'jobs') loadJobs(); if (action === 'track' && j.case_id) openCase(j.case_id); }
async function jobberLink(id){ const n = prompt('Job number in Pumps to add it to:'); if (!n) return; const j = await api('/jobber/items/' + encodeURIComponent(id), {method:'POST', body:{action:'link', case_id: parseInt(n)}}); if (j.success) loadJobs(); else toast(j.error, true); }
async function syncJobber(){ const j = await api('/jobber/sync', {method:'POST', body:{}}); if (!j.success) { toast(j.error, true); return; } toast(j.started ? 'Jobber sync started - this takes a minute or two.' : 'A Jobber sync is already running - the list updates when it finishes.'); setTimeout(loadJobs, 2000); }

// ── the month's maintenance (Home tab) ────────────────
let MS = null;
const MS_SEL = new Set(); // ticked accounts, kept so the table's once-a-minute refresh doesn't clear them
function msMonths(){
  const sel = document.getElementById('msMonth'); if (sel.options.length) return;
  const d = new Date(); d.setDate(1);
  for (let i = -1; i <= 2; i++) { const x = new Date(d.getFullYear(), d.getMonth() + i, 1);
    const v = x.getFullYear() + '-' + String(x.getMonth() + 1).padStart(2, '0');
    sel.add(new Option(x.toLocaleString('en-US', {month:'long', year:'numeric'}) + (i === 0 ? ' (this month)' : i === 1 ? ' (next month)' : ''), v, false, i === 0)); }
}
async function loadMaintSchedule(){
  msMonths();
  const j = await api('/maint/schedule?month=' + document.getElementById('msMonth').value);
  if (!j.success) { document.getElementById('msBody').innerHTML = `<tr><td colspan="5" class="empty">${esc(j.error)}</td></tr>`; return; }
  MS = j; drawMaintSchedule();
}
function drawMaintSchedule(){
  if (!MS) return;
  const show = document.getElementById('msShow').value;
  const find = (document.getElementById('msSearch').value || '').trim().toLowerCase();
  const rows = MS.rows.filter(r => (!show || (show === 'todo' ? !r.notified : r.vendor === show)) && (!find || JSON.stringify(r).toLowerCase().includes(find)));
  const left = MS.total - MS.notified;
  document.getElementById('msCount').textContent = MS.total;
  document.getElementById('msInfo').innerHTML = `${MS.total} visits in ${esc(MS.label)} · ${MS.notified} notified · ` + (left ? `<b class="warn">${left} not notified yet</b>` : '<span class="ok">all notified</span>');
  document.getElementById('msEmail').classList.toggle('hide', !MS.wettech_mailto);
  const q = x => JSON.stringify(x).replace(/"/g, '&quot;');
  // One row per account: whether Justin (Wettech) and Jordan (Gulfshore) have been told.
  const byAcct = [];
  rows.forEach(r => { let a = byAcct.find(x => x.account === r.account); if (!a) byAcct.push(a = {account: r.account, rows: {}}); a.rows[r.vendor] = r; });
  const cell = (r, who) => { if (!r) return `<span class="note" title="This account has no ${who === 'Justin' ? 'Wettech pump' : 'Gulfshore lake'} visit this month">— not for ${who}</span>`; const n = r.notified;
    return (n ? `<span class="chip g">✓ told</span> <span class="note">${esc(niceDay(d10(n.notified_at)))}${n.notified_by ? ' · ' + esc(n.notified_by) : ''}${n.how ? ' · ' + esc(n.how) : ''}</span>${n.note ? '<div class="note">' + esc(n.note) + '</div>' : ''}${n.auto ? '' : ` <button class="btn s" title="Not told after all" onclick="maintNotified(${q(r.account)}, '${r.vendor}', false)">↺</button>`}`
      : `<span class="chip r">not told</span> <button class="btn s p" title="Mark ${who} told" onclick="maintNotifiedAsk(${q(r.account)}, '${r.vendor}')">✓ Mark told</button>`)
      + `<div class="note">${r.report ? '✓ report ' + esc(niceDay(r.report)) : 'report not in yet'}</div>`; };
  document.getElementById('msBody').innerHTML = byAcct.map(a => { const w = a.rows.Wettech, g = a.rows.Gulfshore, r0 = w || g;
    const both = w && g ? (w.notified && g.notified ? '<span class="chip g">both told</span>' : !w.notified && !g.notified ? '<span class="chip r">neither told</span>' : `<span class="chip a">only ${w.notified ? 'Justin' : 'Jordan'} told</span>`) : '';
    return `<tr><td><input type="checkbox" class="msSel" data-account="${esc(a.account)}" data-w="${w && !w.notified ? 1 : ''}" data-g="${g && !g.notified ? 1 : ''}" title="Select this account, then use ✓ Justin told / ✓ Jordan told" onchange="msTick(this)" ${(w && !w.notified) || (g && !g.notified) ? (MS_SEL.has(a.account) ? 'checked' : '') : 'disabled'}></td>
    <td style="max-width:300px"><a href="#" onclick="event.preventDefault();openAccount(${q(a.account)})"><b>${esc(a.account)}</b></a> ${both}<div class="note" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(r0.what)}${r0.where ? ' · ' + esc(r0.where) : ''}">${esc(r0.what)}${r0.where ? ' · ' + esc(r0.where) : ''}</div>${(w && w.hold) || (g && g.hold) ? `<span class="chip a">${esc((w && w.hold) || g.hold)}</span>` : ''}</td>
    <td>${r0.approved ? '<span class="ok">✓ ' + esc(niceDay(r0.approved)) + '</span>' : '<span class="note">—</span>'}</td>
    <td style="min-width:150px">${cell(w, 'Justin')}</td><td style="min-width:150px">${cell(g, 'Jordan')}</td></tr>`; }).join('') || `<tr><td colspan="5" class="empty">${MS.total ? 'None to show.' : 'No maintenance due this month.'}</td></tr>`;
  document.getElementById('msAll').checked = false; msSelChanged();
}
// Several accounts at once: tick them, then "✓ Justin told" or "✓ Jordan told".
// Only the ticked accounts whose visit for that subcontractor isn't told yet count.
function msTick(x){ x.checked ? MS_SEL.add(x.dataset.account) : MS_SEL.delete(x.dataset.account); msSelChanged(); }
function msSelected(vendor){ const k = vendor === 'Wettech' ? 'w' : 'g'; return [...document.querySelectorAll('.msSel:not(:disabled):checked')].filter(x => x.dataset[k]).map(x => x.dataset.account); }
function msSelectAll(on){ document.querySelectorAll('.msSel:not(:disabled)').forEach(x => { x.checked = on; msTick(x); }); }
function msSelChanged(){
  const w = msSelected('Wettech').length, g = msSelected('Gulfshore').length;
  const any = document.querySelectorAll('.msSel:not(:disabled):checked').length;
  // Ticked accounts that are only Wettech (or only Gulfshore) leave the other one's button off.
  [['msMarkW', '✓ Justin told', w], ['msMarkG', '✓ Jordan told', g]].forEach(([id, label, n]) => {
    const b = document.getElementById(id); b.textContent = label + (n ? ` (${n})` : ''); b.disabled = !!any && !n; });
}
function maintNotifiedAskMany(vendor){
  const sel = msSelected(vendor), who = vendor === 'Wettech' ? 'Justin (Wettech)' : 'Jordan (Gulfshore)';
  if (!sel.length) { toast(`Tick the accounts ${who} has been told about first`, true); return; }
  openModal(`${esc(who)} told - ${sel.length} account${sel.length > 1 ? 's' : ''}`, `<div class="note" style="margin-bottom:8px">${sel.map(esc).join(', ')}</div><div class="fields">
    <label>How<select id="mn_how"><option>email</option><option>phone</option><option>text</option><option>in person</option></select></label>
    <label class="w">Note<input type="text" id="mn_note" placeholder="e.g. sent Tom the October list"></label></div>
    <div class="note">This only records that ${esc(who)} was told - nothing is sent.</div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="maintNotifiedMany('${vendor}')">Save</button>`);
}
async function maintNotifiedMany(vendor){
  const sel = msSelected(vendor);
  if (await maintNotified(sel, vendor, true, document.getElementById('mn_how').value, document.getElementById('mn_note').value)) {
    // Keep the accounts ticked that still have the other subcontractor to tell.
    MS_SEL.forEach(acct => { if (!MS.rows.some(r => r.account === acct && !r.notified)) MS_SEL.delete(acct); }); drawMaintSchedule();
  } else return;
  toast(`${sel.length} marked ${vendor === 'Wettech' ? 'Justin' : 'Jordan'} told`);
}
function maintNotifiedAsk(account, vendor){
  const who = vendor === 'Wettech' ? 'Justin (Wettech)' : 'Jordan (Gulfshore)';
  openModal(`${esc(account)} - ${esc(who)} notified`, `<div class="fields">
    <label>How<select id="mn_how"><option>email</option><option>phone</option><option>text</option><option>in person</option></select></label>
    <label class="w">Note<input type="text" id="mn_note" placeholder="e.g. Tom said the week of the 20th"></label></div>`,
    `<button class="btn" onclick="closeModal()">Cancel</button><button class="btn p" onclick="maintNotified(${JSON.stringify(account).replace(/"/g, '&quot;')}, '${vendor}', true, document.getElementById('mn_how').value, document.getElementById('mn_note').value)">Save</button>`);
}
async function maintNotified(account, vendor, on, how, note){
  const accounts = Array.isArray(account) ? account : [account];
  const j = await api('/maint/notified', {method:'POST', body:{month: MS.month, vendor, accounts, notified: on, how: how || '', note: note || ''}});
  if (!j.success) { toast(j.error, true); return false; }
  closeModal(); MS = j; drawMaintSchedule(); return true;
}
// Opens the email to Tom in your mail program, then asks whether it went.
function emailWettechList(){
  if (!MS || !MS.wettech_mailto) return;
  const names = MS.rows.filter(r => r.vendor === 'Wettech' && !r.notified).map(r => r.account);
  location.href = MS.wettech_mailto;
  setTimeout(() => { if (confirm(`Did the email to Tom go? Mark these ${names.length} pump visits as notified?`)) maintNotified(names, 'Wettech', true, 'email', 'monthly list'); }, 800);
}

// ── an account's history (Accounts tab) ───────────────
let ACH = null;
async function openAccount(name){
  const j = await api('/accounts/history?name=' + encodeURIComponent(name));
  if (!j.success) { toast(j.error || 'Not found', true); return; }
  if (!ACH || ACH.name !== j.name) window._acTab = 'bills';
  ACH = j; window._acJName = null; renderAccount();
  document.getElementById('drawerWrap').classList.remove('hide');
}
function renderAccount(){
  const a = ACH, q = x => JSON.stringify(x).replace(/"/g, '&quot;');
  const todo = t => `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;padding:10px 12px;border:1px solid var(--border);border-radius:10px;${t.done_at ? 'opacity:.75' : ''}"><div>
      <b>${t.done_at ? '✓ ' : ''}${esc(t.title)}</b>${t.detail ? `<div class="note" style="white-space:pre-line">${esc(t.detail)}</div>` : ''}
      <div class="note">Added ${esc(niceDay(d10(t.created_at)))}${t.created_by ? ' by ' + esc(t.created_by) : ''}${t.due_on ? ' · due ' + esc(niceDay(t.due_on)) : ''}${t.done_at ? ' · done ' + esc(niceDay(d10(t.done_at))) + (t.done_by ? ' by ' + esc(t.done_by) : '') : ''}</div></div>
      <span style="display:flex;gap:4px"><button class="btn s" title="Edit" onclick='todoEdit(${JSON.stringify({id: t.id, title: t.title, detail: t.detail || "", due_on: t.due_on || ""}).replace(/'/g, "&#39;")})'>✎</button><button class="btn s ${t.done_at ? '' : 'p'}" onclick="${t.done_at ? `accountTodoDone(${t.id}, false)` : `askDone(event, () => accountTodoDone(${t.id}, true, event))`}">${t.done_at ? '↺ Reopen' : '✓ Done'}</button></span></div>`;
  const open = a.todos.filter(t => !t.done_at), done = a.todos.filter(t => t.done_at);
  const jobs = a.jobs.map(c => `<details style="border-bottom:1px solid var(--border);padding:8px 0"><summary style="cursor:pointer"><b>${esc(c.title || c.client_name)}</b> ${catChip(c.category)} ${c.status === 'open' ? `<span class="chip b">${esc(stepLabel(c.stage, c.vendor))}</span>` : `<span class="chip ${c.status === 'closed' ? 'g' : ''}">${esc(c.status)}</span>`}
      <span class="note">opened ${esc(c.opened_on || '')}${c.po_number ? ' · PO ' + esc(c.po_number) : ''}${c.vendor ? ' · ' + esc(c.vendor) : ''}</span> <a href="#" onclick="event.preventDefault();openCase(${c.id})">open job ↗</a></summary>
      <div style="padding:6px 0 0 14px">${c.events.map(e => `<div class="note">${esc((e.at || '').slice(0, 16))} · ${esc(e.actor)} · <b>${esc(e.action)}</b>${e.detail ? ' - ' + esc(e.detail) : ''}</div>`).join('') || '<div class="note">Nothing logged.</div>'}</div></details>`).join('');
  const notices = a.notices.map(n => `<div class="note">${esc(n.month)} · <b>${esc(n.vendor)}</b> notified ${esc(niceDay(d10(n.notified_at)))}${n.notified_by ? ' by ' + esc(n.notified_by) : ''}${n.how ? ' · ' + esc(n.how) : ''}${n.note ? ' - ' + esc(n.note) : ''}</div>`).join('');
  const ac = a.account || {}, p = ac.pump, l = ac.lake, s = ac.scada, jb = a.jobber || {};
  const row = (label, val) => val ? `<div class="note"><span style="display:inline-block;min-width:110px">${label}</span> <b style="font-weight:600;color:var(--text)">${esc(val)}</b></div>` : '';
  const card = (title, body, btns) => `<div style="flex:1;min-width:220px;border:1px solid var(--border);border-radius:10px;padding:10px 12px"><div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:4px"><b>${title}</b><span style="display:flex;gap:4px">${btns}</span></div>${body}</div>`;
  const setup = [
    p ? card('Pump - Wettech' + (!p.active ? ' <span class="chip">former</span>' : ''), row('Type', p.kind) + row('Equipment', p.equipment) + row('Visits', schedText(p) + (p.due_this_month ? ' (due this month)' : '')) + row('Wettech / visit', p.vendor_cost) + row('Naples Electric', p.naples_electric) + row('We bill', p.our_bill) + row('Repairs by', p.repairs_by || 'Wettech') + row('Joined', p.joined) + row('Before service', p.follow_up) + row('Notes', p.notes) + (p.jobber_client_id ? row('Jobber', [p.jobber_client_name, p.jobber_property_label, p.jobber_job_label].filter(Boolean).join(' · ')) : `<div class="note warn" style="margin-top:4px">Not linked to Jobber. <button class="btn s" onclick="acEdit('pump', ${p.id})">🔗 Link to Jobber</button></div>`), `<button class="btn s" onclick="acEdit('pump', ${p.id})">Edit</button>`)
      : card('Pump - Wettech', '<div class="note">No pump maintenance.</div>', `<button class="btn s" onclick="acEdit('pump', 0)">＋ Add</button>`),
    l ? card('Lake - Gulfshore' + (l.active === 0 ? ' <span class="chip">former</span>' : ''), row('Equipment', l.equipment) + row('Diver', l.needs_dive ? (l.months ? lakeSched(l) : 'Every month') + (l.status === 'hold' ? ' - on hold' : '') : 'No diving') + row('Gulfshore', l.diver_cost) + row('We bill', l.our_bill) + row('Diver notes', l.diver_notes) + row('Status', l.status_note), `<button class="btn s" onclick="acEdit('lake', ${l.id})">Edit</button>`)
      : card('Lake - Gulfshore', '<div class="note">No lake or diver work.</div>', `<button class="btn s" onclick="acEdit('lake', 0)">＋ Add</button>`),
    s ? card('SCADA', row('Status', s.complimentary ? 'complimentary' : (s.state || '').replace('_', ' ')) + row('Next renewal', s.active ? s.next_due_on : 'off SCADA') + row('Wettech', s.vendor_cost) + row('We bill', s.our_bill) + row('Notes', s.notes), `<button class="btn s" onclick="acEdit('scada', ${s.id})">Edit</button>`)
      : card('SCADA', '<div class="note">Not on SCADA.</div>', `<button class="btn s" onclick="acEdit('scada', 0)">＋ Add</button>`)].join('');
  const where = (p && p.address) || (l && l.address) || '';
  const links = [jb.client && jb.client.uri ? `<a class="btn s" href="${esc(jb.client.uri)}" target="_blank" rel="noopener">${esc(jb.client.name)} in Jobber ↗</a>` : '',
    ...(jb.recurring || []).filter(r => r.uri).map(r => `<a class="btn s" href="${esc(r.uri)}" target="_blank" rel="noopener">Job #${esc(r.number)} ${esc(r.title || '')} ↗</a>`)].filter(Boolean).join(' ');
  const docs = (a.docs || []).filter(d => d.kind !== 'bill').map(d => `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:6px 0;border-bottom:1px solid var(--border)">${kindChip(d.kind)} <span style="flex:1;min-width:160px"><b>${esc(d.file_name)}</b> <span class="note">${d.doc_number ? '#' + esc(d.doc_number) + ' · ' : ''}${d.total != null ? money(d.total) + ' · ' : ''}${esc(d.doc_date || d10(d.created_at))}${d.signed_sent_at ? ' · signed &amp; sent ' + esc(d10(d.signed_sent_at)) : d.signed_at ? ' · signed ' + esc(d10(d.signed_at)) : ''}</span></span>
      <a class="btn s" href="/pumps/api/docs/${d.id}/file" target="_blank">Open</a>${d.has_branded ? ` <a class="btn s" target="_blank" href="/pumps/api/docs/${d.id}/file?version=branded_pdf">SE report PDF</a>` : ''}${d.signed_at ? ` <a class="btn s" href="/pumps/api/docs/${d.id}/file?version=approved&download=1">⬇ Signed</a>` : ''}${d.case_id ? ` <a href="#" onclick="event.preventDefault();openCase(${d.case_id})">job ↗</a>` : ''}</div>`).join('');
  const vis = (AC && AC.accounts.find(x => x.name === a.name) || {}).visit;
  document.getElementById('drawer').dataset.account = a.name;
  document.getElementById('drawer').innerHTML = `
  <div class="hd"><div><h2>${esc(a.name)}${ac.active === false ? ' <span class="chip">former</span>' : ''}</h2><div class="note">${where ? esc(where) + ' · ' : ''}${open.length} open to-do${open.length === 1 ? '' : 's'} · ${a.todos.length} in all · ${a.jobs.length} job${a.jobs.length === 1 ? '' : 's'}</div></div>
    <div><button class="btn" onclick="closeDrawer()">✕</button></div></div>
  <div class="bd">
    <div class="sec" style="display:flex;gap:6px;flex-wrap:wrap" id="acTabs">${[['bills', `Vendor invoices (${(a.vendor_bills || []).length})`],
      ['quotes', `Vendor quotes (${(a.docs || []).filter(d => d.kind === 'quote').length})`], ['jobber', 'In Jobber'], ['account', 'Account']]
      .map(([k, l]) => `<button class="btn s" data-actab="${k}" onclick="acTab('${k}')">${l}</button>`).join('')}</div>
    <div data-acpane="bills" class="sec"><h4>Vendor invoices (${(a.vendor_bills || []).length})</h4>${vendorBillsHtml(a.vendor_bills || [])}</div>
    <div data-acpane="quotes" class="sec"><h4>Vendor quotes (${(a.docs || []).filter(d => d.kind === 'quote').length})</h4>${vendorQuotesHtml((a.docs || []).filter(d => d.kind === 'quote'))}</div>
    <div data-acpane="jobber" class="sec"><h4>In Jobber</h4><div id="acJobber">${(jb.client_ids || []).length ? '<div class="note">Loading invoices, jobs and requests from Jobber…</div>' : '<div class="note">Not linked to a Jobber client yet - link it under Account → Setup.</div>'}</div></div>
    <div data-acpane="account">
    <details class="sec fold"><summary><h4>Setup</h4> <span class="note">pump, lake and SCADA - what they have and the prices</span></summary><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">${setup}</div>
      ${ac.active && ((p && p.active) || (l && l.active !== 0)) ? `<div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap"><button class="btn s ${vis ? '' : 'p'}" onclick="accountReady(${q(a.name)})">✓ Ready - client approved</button>${vis ? `<span class="note">✓ Client approved ${esc((vis.link || {}).since || '')} · waiting on ${esc(((vis.link || {}).vendors || []).filter(x => !((vis.link || {}).reported || []).includes(x)).join(' and '))}</span>` : ''}</div>` : ''}
      ${links ? `<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${links}</div>` : ''}</details>
    <div class="sec"><h4>Add a to-do for ${esc(a.name)}</h4><div style="display:flex;gap:6px;flex-wrap:wrap">
      <input type="text" id="acTodoTitle" placeholder="What needs doing" style="flex:1;min-width:180px">
      <input type="date" id="acTodoDue" title="Due (optional)">
      <button class="btn p" onclick="accountTodoAdd(${q(a.name)})">＋ Add</button></div></div>
    <div class="sec"><h4>To do (${open.length})</h4><div style="display:flex;flex-direction:column;gap:8px">${open.map(todo).join('') || '<div class="note">Nothing open.</div>'}</div></div>
    <div class="sec"><h4>Done (${done.length})</h4><div style="display:flex;flex-direction:column;gap:8px">${done.map(todo).join('') || '<div class="note">Nothing done yet.</div>'}</div></div>
    <div class="sec"><h4>Items followed here (${a.jobs.length})</h4>${jobs || '<div class="note">None.</div>'}</div>
    <div class="sec"><h4>Reports and quotes (${(a.docs || []).filter(d => d.kind !== 'bill').length})</h4>${docs || '<div class="note">No reports or quotes yet.</div>'}</div>
    ${notices ? `<div class="sec"><h4>Maintenance - subcontractor notified</h4>${notices}</div>` : ''}
    </div>
  </div>`;
  acTab(window._acTab || 'bills');
  // Jobber's history: fetched once per account, kept while its page re-draws.
  if (window._acJName === a.name && window._acJ) acJobberShow(window._acJTab || 'invoices');
  else { window._acJ = null; window._acJName = a.name; loadAccountJobber(jb.client_ids || []); }
}
// The account page in tabs (Oct 2026): Jobber's long history loading in no longer pushes the rest down.
function acTab(k){
  window._acTab = k;
  document.querySelectorAll('#drawer [data-acpane]').forEach(el => el.classList.toggle('hide', el.dataset.acpane !== k));
  document.querySelectorAll('#acTabs [data-actab]').forEach(b => b.classList.toggle('p', b.dataset.actab === k));
}
// Every vendor quote for the account: when, whose, how much, signed, its job.
function vendorQuotesHtml(qs){
  if (!qs.length) return '<div class="note">No vendor quotes yet.</div>';
  return `<table class="t"><thead><tr><th>Date</th><th>Vendor</th><th>Their quote</th><th class="num">Amount</th><th>Signed</th><th></th></tr></thead><tbody>${qs.map(d => `<tr>
    <td>${esc(d.doc_date || d10(d.created_at))}</td><td>${esc(d.vendor || '')}</td><td><a target="_blank" href="/pumps/api/docs/${d.id}/file">${d.doc_number ? '#' + esc(d.doc_number) : esc(d.file_name)}</a></td>
    <td class="num">${money(d.total ?? d.subtotal)}</td>
    <td>${d.signed_at ? `<a class="chip g" href="/pumps/api/docs/${d.id}/file?version=approved&download=1">signed ${esc(d10(d.signed_at))}</a>` : '<span class="note">-</span>'}</td>
    <td>${d.case_id ? `<a href="#" onclick="event.preventDefault();openCase(${d.case_id})">job ↗</a>` : ''}</td></tr>`).join('')}</tbody></table>`;
}
// Every vendor invoice for the account: what, when, how much, our invoice, paid.
function vendorBillsHtml(bills){
  if (!bills.length) return '<div class="note">No vendor invoices yet.</div>';
  return `<table class="t"><thead><tr><th>Date</th><th>Vendor</th><th>Their invoice</th><th class="num">Amount</th><th>Our invoice</th><th>Paid</th><th></th></tr></thead><tbody>${bills.map(b => `<tr>
    <td>${esc(b.date)}</td><td>${esc(b.vendor)}</td><td><a target="_blank" href="/pumps/api/docs/${b.id}/file">#${esc(b.number || '?')}</a></td>
    <td class="num">${money(b.total ?? b.subtotal)}</td><td>${b.our_invoice ? '#' + esc(b.our_invoice) : '<span class="note">-</span>'}</td>
    <td>${b.paid_on ? '<span class="chip g">paid ' + esc(b.paid_on) + '</span>' : '<span class="note">not yet</span>'}</td>
    <td>${b.case_id ? `<a href="#" onclick="event.preventDefault();openCase(${b.case_id})">job ↗</a>` : ''}</td></tr>`).join('')}</tbody></table>`;
}
// The account's Jobber history: invoices, jobs and requests, newest first - one click between them.
async function loadAccountJobber(ids){
  const box = document.getElementById('acJobber');
  if (!box || !ids.length) return;
  const j = await api('/accounts/jobber_history?' + ids.map(i => 'client_id=' + encodeURIComponent(i)).join('&'));
  if (!document.getElementById('acJobber')) return;
  if (!j.success) { box.innerHTML = `<div class="note">${esc(j.error)}</div>`; return; }
  window._acJ = j; acJobberShow(window._acJTab || 'invoices');
}
function acJobberShow(tab){
  window._acJTab = tab;
  const j = window._acJ, box = document.getElementById('acJobber'); if (!j || !box) return;
  const tabs = [['invoices', 'Invoices'], ['jobs', 'Jobs'], ['requests', 'Service requests']];
  const rows = j[tab] || [];
  box.innerHTML = `<div style="display:flex;gap:6px;margin-bottom:8px">${tabs.map(([k, l]) => `<button class="btn s ${k === tab ? 'p' : ''}" onclick="acJobberShow('${k}')">${l} (${(j[k] || []).length})</button>`).join('')}</div>`
    + (rows.length ? `<table class="t"><thead><tr><th>Date</th><th>#</th><th>Title</th><th>Status</th><th class="num">Amount</th></tr></thead><tbody>${rows.map(r => `<tr>
      <td>${esc(r.date)}</td><td>${r.uri ? `<a target="_blank" rel="noopener" href="${esc(r.uri)}">${r.number ? '#' + esc(r.number) : 'open'} ↗</a>` : esc(r.number)}</td>
      <td>${esc(r.title)}${r.type === 'recurring' ? ' <span class="chip">recurring</span>' : ''}</td><td>${esc((r.status || '').replace(/_/g, ' '))}</td>
      <td class="num">${r.total != null ? money(r.total) : ''}</td></tr>`).join('')}</tbody></table>` : '<div class="note">None in Jobber.</div>');
}
// Edit an account's pump, lake or SCADA from its page (the same forms as before).
async function acEdit(kind, id){
  if (kind === 'pump') { if (!MT) { const j = await api('/maint'); if (!j.success) { toast(j.error, true); return; } MT = j; }
    maintEdit(id); if (!id) document.getElementById('mt_name').value = ACH.name; }
  else if (kind === 'lake') { if (!DV) await loadDivers(); editDiveSite(id); if (!id) document.getElementById('ds_name').value = ACH.name; }
  else { if (!SC) { const j = await api('/scada'); if (!j.success) { toast(j.error, true); return; } SC = j; } scadaEdit(id); if (!id) document.getElementById('sc_client').value = ACH.name; }
}
// After a save: the account page (if it's what's open) and the list catch up.
function refreshAccountPage(){
  const dr = document.getElementById('drawer');
  if (ACH && dr.dataset.account && !document.getElementById('drawerWrap').classList.contains('hide')) setTimeout(() => openAccount(dr.dataset.account), 300);
  refreshAccounts();
}
async function accountTodoAdd(name){
  const title = document.getElementById('acTodoTitle').value.trim(); if (!title) { toast('Say what needs doing', true); return; }
  const j = await api('/accounts/todo', {method:'POST', body:{name, title, due_on: document.getElementById('acTodoDue').value}});
  if (!j.success) { toast(j.error, true); return; }
  ACH = j; renderAccount(); loadToday();
}
async function accountTodoDone(id, done, ev){
  const j = await api('/todos/' + id + '/done', {method:'POST', body:{done}});
  if (!j.success) { toast(j.error, true); return; }
  if (done) celebrate(ev);
  openAccount(ACH.name); loadToday();
}

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
  if (['jobs','scada','accounts','reports','bills'].includes(h)) showTab(h); else if (!h.startsWith('item-') && !h.startsWith('doc-')) showTab('jobs');
  if (!h || ['jobs','scada','accounts','reports','bills'].includes(h)) loadToday();
  setInterval(() => { if (document.getElementById('drawerWrap').classList.contains('hide') && document.getElementById('modalWrap').classList.contains('hide')) { loadToday(); if (curTab === 'jobs') loadJobs(); } }, 60000);
})();
</script>
{% if assistant %}
<aside class="pm hide" id="pm" aria-label="Pump Manager">
  <div class="hd"><b>💬 Pump Manager</b><button class="btn s" title="Start a new conversation" onclick="pmNew()">New chat</button><button class="btn s" onclick="pmMinimize()" title="Minimize - keeps the conversation, answers still come in">–</button><button class="btn s" onclick="pmToggle(false)" title="Close">✕</button></div>
  <div class="msgs" id="pmMsgs"><div class="note">Ask anything about our pump accounts and jobs. Answers usually take a minute or two.</div></div>
  <div class="ft"><textarea id="pmQ" rows="2" placeholder="Ask Pump Manager…" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();pmAsk()}"></textarea>
    <button class="btn p" id="pmSend" onclick="pmAsk()">Send</button></div>
</aside>
<button class="pmmini hide" id="pmMini" onclick="pmToggle(true)" title="Open Pump Manager">💬 Pump Manager<span id="pmMiniState"></span></button>
<script>
// Pump Manager: questions go out through the server; answers land 1-2 minutes later and are polled for.
let pmData = {messages: []}, pmTimer = null, pmSeen = 0;
// Answers are text or markdown: escaped first, then a little formatting - never raw HTML.
function pmMd(t){
  const blocks = String(t || '').split(/```/);
  return blocks.map((b, i) => {
    if (i % 2) return `<pre><code>${esc(b.replace(/^\w*\n/, ''))}</code></pre>`;
    const lines = esc(b).split('\n'); let out = '', list = false;
    for (let ln of lines) {
      ln = ln.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/(^|\W)\*([^*\n]+)\*(?=\W|$)/g, '$1<i>$2</i>')
             .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      const m = ln.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/), h = ln.match(/^#{1,4}\s+(.*)$/);
      if (m) { if (!list) { out += '<ul>'; list = true; } out += `<li>${m[1]}</li>`; continue; }
      if (list) { out += '</ul>'; list = false; }
      out += h ? `<b>${h[1]}</b><br>` : ln + '<br>';
    }
    return out + (list ? '</ul>' : '');
  }).join('').replace(/(<br>)+$/, '');
}
function pmContext(){
  const open = !document.getElementById('drawerWrap').classList.contains('hide'), dr = document.getElementById('drawer');
  const acct = open && dr.dataset.account ? dr.dataset.account : '';
  let job = '';
  if (open && !acct && curCase) { const jj = (curCase.jobber || {}).job || {}; job = (curCase.title || '') + (jj.number ? ` (Jobber #${jj.number})` : ''); }
  return {tab: curTab, job, account: acct};
}
function pmRender(){
  const box = document.getElementById('pmMsgs'), ms = pmData.messages || [];
  if (!pmData.configured && pmData.configured !== undefined) box.innerHTML = '<div class="issue">Pump Manager isn\'t set up yet - the office admin needs to add its webhook.</div>';
  else box.innerHTML = ms.length ? ms.map(m => {
    const c = m.context || {}, where = [c.job, c.account].filter(Boolean).join(' · ');
    const a = m.state === 'answered' ? `<div class="a">${pmMd(m.answer)}</div>`
      : m.state === 'thinking' ? '<div class="a wait">Pump Manager is thinking…</div>'
      : m.state === 'error' ? `<div class="a bad">${esc(m.error)} - try again</div>`
      : '<div class="a bad">No answer yet, try again</div>';
    return `<div class="q">${esc(m.question)}</div>${where ? `<div class="ctx">${esc(where)}</div>` : ''}${a}`;
  }).join('') : '<div class="note">Ask anything about our pump accounts and jobs. Answers usually take a minute or two.</div>';
  box.scrollTop = box.scrollHeight;
  const dot = document.querySelector('#pmBtn .pmdot'), answered = ms.filter(m => m.state === 'answered').length;
  const closed = document.getElementById('pm').classList.contains('hide');
  if (closed && answered > pmSeen && !dot) document.getElementById('pmBtn').insertAdjacentHTML('beforeend', '<span class="pmdot" title="New answer"></span>');
  if (!closed) { pmSeen = answered; if (dot) dot.remove(); }
  const mini = document.getElementById('pmMiniState');
  if (mini) mini.innerHTML = ms.some(m => m.state === 'thinking') ? ' · thinking…'
    : (closed && answered > pmSeen ? ' <span class="pmdot" title="New answer"></span>' : '');
}
async function pmLoad(){
  const j = await api('/assistant/messages');
  if (!j.success) return;
  pmData = j; pmRender();
  clearTimeout(pmTimer);
  // Keep looking while an answer is due (they come 1-2 minutes after asking).
  if ((j.messages || []).some(m => m.state === 'thinking')) pmTimer = setTimeout(pmLoad, 5000);
}
// Minimized: a small button bottom-right that says when an answer is due or has come in.
function pmMinimize(){
  document.getElementById('pm').classList.add('hide');
  document.getElementById('pmMini').classList.remove('hide');
  pmRender();
}
function pmToggle(show){
  const el = document.getElementById('pm'), on = show === undefined ? el.classList.contains('hide') : show;
  el.classList.toggle('hide', !on);
  document.getElementById('pmMini').classList.add('hide');
  if (on) { pmLoad(); setTimeout(() => document.getElementById('pmQ').focus(), 50); }
}
async function pmAsk(){
  const q = document.getElementById('pmQ'), text = q.value.trim(), btn = document.getElementById('pmSend');
  if (!text) return;
  btn.disabled = true;
  pmData.messages = (pmData.messages || []).concat([{question: text, state: 'thinking', context: pmContext()}]); pmRender();
  const j = await api('/assistant/ask', {method:'POST', body:{question: text, context: pmContext()}});
  btn.disabled = false;
  if (!j.success) { toast(j.error, true); pmLoad(); return; }
  q.value = '';
  pmData = j; pmRender();
  clearTimeout(pmTimer); pmTimer = setTimeout(pmLoad, 5000);
}
async function pmNew(){
  const j = await api('/assistant/ask', {method:'POST', body:{new: true}});
  if (j.success) { pmData = j; pmSeen = 0; pmRender(); }
}
pmLoad();
</script>
{% endif %}
</body>
</html>'''
