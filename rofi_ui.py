"""Rofi Jaya — Manajemen Pesanan & Produksi (UI v2).

Dimuat oleh app.py sebagai atribut `HTML` setelah modul API v2. Seluruh
data diambil dari API `/api/v2/...` (tabel relasional), bukan dari data
contoh di frontend.
"""
HTML = r"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#101211">
<meta name="robots" content="noindex,nofollow">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Rofi Jaya — Manajemen Pesanan & Produksi</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon-192.png">
<style>
:root{
 --bg:#101211;--surface:#171A19;--card:#202522;--line:#343B36;
 --text:#F1F2ED;--muted:#B0B8B0;--accent:#B5C7A8;--accent-ink:#12160F;
 --blue:#9DBBDD;--warn:#E0A458;--bad:#D9756A;--ok:#B5C7A8;
 --radius:14px;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text)}
body{font:14.5px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased}
a{color:var(--accent)}
h1,h2,h3,p{margin-top:0}
h1{font-size:26px;letter-spacing:-.7px;margin-bottom:4px}
h2{font-size:17px;letter-spacing:-.2px;margin-bottom:10px}
h3{font-size:14px;margin-bottom:8px}
button,input,select,textarea{font:inherit;color:inherit}
button,.button{border:1px solid var(--line);background:#262C28;color:var(--text);
 padding:10px 15px;border-radius:10px;cursor:pointer;text-decoration:none;
 display:inline-flex;align-items:center;justify-content:center;gap:7px;font-weight:600;
 transition:background .12s,border-color .12s,transform .06s}
button:hover,.button:hover{background:#2E352F;border-color:#465046}
button:active,.button:active{transform:translateY(1px)}
button:disabled{opacity:.45;cursor:not-allowed}
button.primary,.button.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
button.primary:hover{background:#C4D4B7;border-color:#C4D4B7}
button.wa{background:#20301F;color:#BFE0B4;border-color:#3A5136}
button.wa:hover{background:#263A25}
button.danger{color:#F0B3AB;border-color:#5A3A36;background:#2B1F1D}
button.ghost{background:transparent}
button.small,.button.small{padding:6px 11px;font-size:12.5px;border-radius:8px}
button.link{background:none;border:0;padding:0;color:var(--accent);font-weight:700;cursor:pointer}
input,select,textarea{width:100%;padding:10px 12px;border:1px solid var(--line);
 border-radius:9px;background:#1B201D;color:var(--text)}
input::placeholder,textarea::placeholder{color:#79837B}
input[type=checkbox]{width:17px;height:17px;accent-color:var(--accent);padding:0}
input[type=file]{padding:8px;background:#171B18}
textarea{min-height:86px;resize:vertical}
input:focus,select:focus,textarea:focus,button:focus-visible,a:focus-visible{
 outline:2px solid var(--accent);outline-offset:2px}
label{display:block;font-size:12px;font-weight:650;color:var(--muted);margin-bottom:6px;
 letter-spacing:.02em}
.muted{color:var(--muted)}.tiny{font-size:12px}.wrap-text{white-space:pre-wrap;overflow-wrap:anywhere}
.mono{font-family:var(--mono)}
/* ---------- shell ---------- */
.shell{display:grid;grid-template-columns:236px 1fr;min-height:100vh}
.side{background:var(--surface);border-right:1px solid var(--line);padding:22px 14px;
 display:flex;flex-direction:column;position:sticky;top:0;height:100vh}
.brand{display:flex;gap:11px;align-items:center;padding:0 8px 22px;text-decoration:none}
.mark{width:38px;height:38px;border-radius:10px;background:var(--accent);color:var(--accent-ink);
 display:grid;place-items:center;font-weight:900;letter-spacing:-1px;flex:none}
.brand b{display:block;font-size:15.5px;letter-spacing:.02em;color:var(--text)}
.brand span{font-size:10px;letter-spacing:.14em;color:var(--muted)}
.nav{display:flex;flex-direction:column;gap:3px}
.nav button{background:none;border:0;justify-content:flex-start;padding:10px 12px;
 color:#C6CCC6;font-weight:550;border-radius:9px}
.nav button:hover{background:#212623}
.nav button.active{background:#26302A;color:var(--text);box-shadow:inset 2px 0 0 var(--accent)}
.nav .count{margin-left:auto;font-size:11px;background:#2C332E;padding:1px 7px;border-radius:99px;
 color:var(--muted)}
.side-foot{margin-top:auto;border-top:1px solid var(--line);padding:16px 8px 0;
 display:flex;flex-direction:column;gap:8px}
.main{min-width:0;display:flex;flex-direction:column}
.top{height:64px;border-bottom:1px solid var(--line);padding:0 26px;display:flex;
 align-items:center;justify-content:space-between;gap:12px;background:var(--surface);
 position:sticky;top:0;z-index:20}
.content{padding:26px;max-width:1440px;width:100%}
.eyebrow{font-size:10.5px;letter-spacing:.18em;color:var(--muted);font-weight:700;
 margin-bottom:7px}
.head{display:flex;justify-content:space-between;gap:14px;align-items:flex-end;margin-bottom:22px;
 flex-wrap:wrap}
.head p{margin:0;color:var(--muted);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
 padding:20px;margin-bottom:16px}
.card.tight{padding:15px}
.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.spread{justify-content:space-between}
.grid{display:grid;gap:12px}
.g4{grid-template-columns:repeat(4,minmax(0,1fr))}
.g3{grid-template-columns:repeat(3,minmax(0,1fr))}
.g2{grid-template-columns:repeat(2,minmax(0,1fr))}
.form{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.full{grid-column:1/-1}
/* ---------- stats ---------- */
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:15px;
 text-align:left;display:block;width:100%}
.stat:hover{border-color:#48534A;background:#242A26}
.stat .n{display:block;font-size:26px;font-weight:750;letter-spacing:-1px;margin:6px 0 1px}
.stat .l{display:block;font-size:11.5px;color:var(--muted);letter-spacing:.03em}
.stat.alert{border-color:#4E3A2C}
.stat.alert .n{color:var(--warn)}
.money{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid #2A302B;
 font-size:13.5px}
.money:last-child{border-bottom:0}
.money b{font-variant-numeric:tabular-nums}
/* ---------- badges ---------- */
.badge{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:99px;
 font-size:11.5px;font-weight:600;border:1px solid var(--line);background:#1B201D;color:var(--muted);
 white-space:nowrap}
.badge.ok{background:#233026;border-color:#3D5443;color:#C7DDBB}
.badge.run{background:#232A31;border-color:#3B4A57;color:var(--blue)}
.badge.warn{background:#2D2620;border-color:#4D3F2C;color:var(--warn)}
.badge.bad{background:#2E2220;border-color:#4D3330;color:var(--bad)}
.badge.accent{background:#26302A;border-color:#415244;color:var(--accent)}
/* ---------- table ---------- */
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--card)}
table{width:100%;border-collapse:collapse;text-align:left}
th{font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
 padding:11px 12px;background:#1C211E;border-bottom:1px solid var(--line);white-space:nowrap;
 position:sticky;top:0}
td{padding:12px;border-bottom:1px solid #2A302B;font-size:13px;vertical-align:top}
tr:last-child td{border-bottom:0}
tbody tr:hover{background:#242A26}
td.nowrap,th.nowrap{white-space:nowrap}
.right{text-align:right}
/* ---------- filters ---------- */
.filters{display:grid;grid-template-columns:2fr repeat(4,1fr);gap:9px;margin-bottom:14px}
.filters label{margin-bottom:4px}
.empty{padding:44px 18px;text-align:center;color:var(--muted)}
.empty b{display:block;color:var(--text);font-size:16px;margin-bottom:6px}
/* ---------- timeline ---------- */
.tl{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}
.tl .step{border:1px solid var(--line);border-radius:11px;padding:13px;background:#1C211E}
.tl .step.done{border-color:#3D5443;background:#1E2620}
.tl .step.running{border-color:#3B4A57;background:#1E2329}
.tl .step b{display:block;margin:6px 0 2px;font-size:13px}
.tl .dot{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;
 font-size:12px;font-weight:800;background:#2A302B;color:var(--muted)}
.tl .done .dot{background:var(--accent);color:var(--accent-ink)}
.tl .running .dot{background:var(--blue);color:#131A21}
.kv{display:grid;grid-template-columns:160px 1fr;gap:7px 14px;font-size:13.5px}
.kv>span{color:var(--muted)}
.kv>b{font-weight:550;overflow-wrap:anywhere;white-space:pre-wrap}
.check{display:flex;gap:10px;align-items:center;font-size:13.5px;font-weight:500;color:var(--text);
 padding:9px 0;border-bottom:1px solid #2A302B;margin:0}
.check:last-of-type{border-bottom:0}
.check input{flex:none}
.check.done span{color:var(--muted);text-decoration:line-through}
.progress{height:7px;border-radius:99px;background:#1B201D;overflow:hidden;border:1px solid var(--line)}
.progress>i{display:block;height:100%;background:var(--accent)}
/* ---------- tabs ---------- */
.tabs{display:flex;gap:4px;overflow:auto;border-bottom:1px solid var(--line);margin-bottom:16px;
 padding-bottom:0}
.tabs button{background:none;border:0;border-bottom:2px solid transparent;border-radius:0;
 color:var(--muted);padding:10px 13px;white-space:nowrap;font-weight:600;font-size:13px}
.tabs button.active{color:var(--text);border-bottom-color:var(--accent)}
.tabs button:hover{background:none;color:var(--text)}
/* ---------- dialog ---------- */
dialog{border:1px solid var(--line);border-radius:16px;padding:0;width:min(760px,96vw);
 max-height:92vh;background:var(--card);color:var(--text);box-shadow:0 30px 80px #000A}
dialog::backdrop{background:#07090799;backdrop-filter:blur(3px)}
.dlg-head{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;
 justify-content:space-between;align-items:center;gap:10px}
.dlg-head h2{margin:0;font-size:16px}
.dlg-body{padding:20px;overflow:auto;max-height:calc(92vh - 130px)}
.dlg-foot{display:flex;justify-content:flex-end;gap:9px;padding:14px 20px;
 border-top:1px solid var(--line);flex-wrap:wrap}
.notice{border:1px solid #3A4A42;background:#1C2420;color:#C3D3C7;padding:11px 13px;
 border-radius:9px;font-size:12.5px;margin:12px 0}
.notice.warn{border-color:#4D3F2C;background:#2A241D;color:#E4C08B}
.notice.bad{border-color:#4D3330;background:#2B1F1D;color:#F0B3AB}
/* ---------- misc ---------- */
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:#2C3630;
 border:1px solid #46544A;color:var(--text);padding:11px 18px;border-radius:10px;
 z-index:200;max-width:92vw;display:none;box-shadow:0 10px 30px #0008;font-size:13px}
#toast.bad{background:#3A2422;border-color:#5A3A36}
.login{max-width:420px;margin:11vh auto;padding:28px}
.hero-mini{display:grid;grid-template-columns:1.4fr 1fr;gap:16px}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:11px}
.photo{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#1B201D}
.photo img{width:100%;height:140px;object-fit:cover;display:block}
.photo div{padding:8px 10px;font-size:11.5px;color:var(--muted)}
.history{list-style:none;margin:0;padding:0}
.history li{border-left:2px solid #3A443C;padding:0 0 16px 16px;margin-left:4px;position:relative}
.history li:before{content:"";position:absolute;left:-6px;top:5px;width:9px;height:9px;
 border-radius:50%;background:#6E8474}
.history b{display:block;font-size:13.5px}
details{margin-top:6px}summary{cursor:pointer;color:var(--muted);font-size:12px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#171B18;border:1px solid var(--line);
 padding:10px;border-radius:8px;font-size:11px;font-family:var(--mono);max-height:240px;overflow:auto}
.print-only{display:none}

/* ---------- MENU BUTTON STYLE ---------- */
.menu-btn {
    display: none; /* Default sembunyi di desktop */
}
@media(max-width:1180px){
    .g4{grid-template-columns:repeat(2,1fr)}
    .filters{grid-template-columns:1fr 1fr}
}
@media(max-width:860px){
    .shell{grid-template-columns:1fr}
    .side{position:fixed;inset:0 auto 0 0;width:250px;z-index:60;transform:translateX(-100%);
     transition:transform .16s ease;height:100dvh}
    .side.open{transform:none;box-shadow:0 0 0 100vw #000A}
    
    /* Tampilkan tombol menu di HP dengan gaya yang jelas */
    .menu-btn {
        display: inline-flex !important; 
        background: #2E352F; 
        color: #fff; 
        border: 1px solid #465046;
        padding: 8px 12px;
        border-radius: 8px;
        font-weight: bold;
        cursor: pointer;
    }
    
    .top{padding:0 14px;height:58px}
    .content{padding:18px 14px 50px}
    .form,.g2,.g3,.hero-mini{grid-template-columns:1fr}
    .tl{grid-template-columns:1fr 1fr}
    .kv{grid-template-columns:130px 1fr}
    h1{font-size:21px}
    .filters{grid-template-columns:1fr 1fr}
    .filters .wide{grid-column:1/-1}
    .head{align-items:flex-start}
}
@media print{
 body{background:#fff;color:#111}
 .shell,.side,.top,.tabs,#toast,dialog{display:none!important}
 .print-only{display:block}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style>
</head>
<body>
<div id="app"><div class="login card muted">Memuat aplikasi…</div></div>
<dialog id="modal">
 <div class="dlg-head"><h2 id="modal-title"></h2>
 <button type="button" id="close-modal" class="small ghost" aria-label="Tutup">Tutup ✕</button></div>
 <div class="dlg-body" id="modal-body"></div>
</dialog>
<div id="toast" role="status" aria-live="polite"></div>
<script>
"use strict";
const $=(q,root=document)=>root.querySelector(q);
const $$=(q,root=document)=>[...root.querySelectorAll(q)];
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const rp=v=>"Rp"+(Number(v)||0).toLocaleString("id-ID");
const fmtDate=v=>{
 if(!v)return "—";
 const d=new Date(v.length===10?v+"T12:00:00":v);
 return isNaN(d)?"—":d.toLocaleDateString("id-ID",{day:"2-digit",month:"short",year:"numeric"});
};
const fmtDT=v=>{
 if(!v)return "—";
 const d=new Date(v);
 return isNaN(d)?"—":d.toLocaleString("id-ID",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"});
};
const today=()=>new Date(Date.now()+7*3600e3).toISOString().slice(0,10);
let S=null,csrf="",view="dashboard",sel="",tab="ringkasan",q="",filters={status:"",pay:"",sort:"recent",from:"",to:""};
let toastTimer;
const modal=$("#modal");

function toast(msg,bad=false){
 const t=$("#toast");t.textContent=msg;t.className=bad?"bad":"";
 t.style.display="block";clearTimeout(toastTimer);
 t.setAttribute("role",bad?"alert":"status");
 toastTimer=setTimeout(()=>t.style.display="none",6000);
}
async function api(path,body){
 let r;
 try{
  r=await fetch("/api/"+path,{
   method:body===undefined?"GET":"POST",
   headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
   credentials:"same-origin",
   ...(body===undefined?{}:{body:JSON.stringify(body)})
  });
 }catch(e){throw Error("Tidak bisa menghubungi server. Periksa koneksi Anda.");}
 let out;
 try{out=await r.json()}catch(e){throw Error("Respons server tidak valid.");}
 if(!r.ok){
  if(r.status===401&&!path.startsWith("login")){S=null;render()}
  throw Error(out.error||"Permintaan gagal ("+r.status+").");
 }
 return out;
}
async function load(){S=await api("v2/state");csrf=S.csrf;render();}
async function refresh(){try{await load();toast("Data dimuat ulang dari server.")}catch(e){toast(e.message,true)}}

function dialog(title,body,foot=""){
 $("#modal-title").textContent=title;
 $("#modal-body").innerHTML=body+(foot?`<div class="dlg-foot">${foot}</div>`:"");
 if(!modal.open)modal.showModal();
}
$("#close-modal").onclick=()=>modal.close();
modal.addEventListener("click",e=>{if(e.target===modal)modal.close()});
function field(label,name,value="",type="text",extra="",key=""){
 return `<div><label for="f-${name}">${esc(label)}</label>
 <input id="f-${name}" name="${esc(name)}" type="${type}" value="${esc(value)}"
  ${extra}${key?` data-k="${esc(key)}"`:""}></div>`;
}
function area(label,name,value="",extra=""){
 return `<div class="full"><label for="f-${name}">${esc(label)}</label>
 <textarea id="f-${name}" name="${esc(name)}" ${extra}>${esc(value)}</textarea></div>`;
}
function selField(label,name,options,value="",extra="",key=""){
 return `<div><label for="f-${name}">${esc(label)}</label>
 <select id="f-${name}" name="${esc(name)}" ${extra}${key?` data-k="${esc(key)}"`:""}>${options.map(o=>{
  const v=Array.isArray(o)?o[0]:o,l=Array.isArray(o)?o[1]:o;
  return `<option value="${esc(v)}" ${String(v)===String(value)?"selected":""}>${esc(l)}</option>`;
 }).join("")}</select></div>`;
}
function bindForm(id,handler){
 const form=$("#"+id);if(!form)return;
 form.onsubmit=async e=>{
  e.preventDefault();
  const data=Object.fromEntries(new FormData(form));
  const btns=$$("button[type=submit]",form);
  btns.forEach(b=>b.disabled=true);
  try{await handler(data,form)}catch(err){toast(err.message,true)}
  finally{btns.forEach(b=>b.disabled=false)}
 };
}
function confirmBox(text){
 return new Promise(res=>{
  dialog("Konfirmasi",`<p class="wrap-text">${esc(text)}</p>`,
   `<button id="cf-no">Batal</button><button class="primary" id="cf-yes">Ya, lanjutkan</button>`);
  $("#cf-no").onclick=()=>{modal.close();res(false)};
  $("#cf-yes").onclick=()=>{modal.close();res(true)};
 });
}
const PROD_CLASS={"Menunggu Potong":"","Sedang Dipotong":"run","Potong Selesai":"run",
 "Sedang Dijahit":"run","Jahit Selesai":"run","Sedang Finishing":"run",
 "Siap Diserahkan":"accent","Sedang Diserahkan":"run","Selesai Diserahkan":"ok",
 "Dibatalkan":"bad"};
function badge(text,cls){
 const c=cls!==undefined?cls:(PROD_CLASS[text]||"");
 return `<span class="badge ${c}">${esc(text)}</span>`;
}
function payBadge(o){
 const c=o.payment_status==="Lunas"?"ok":o.payment_status==="Belum Bayar"?"bad":
  o.payment_status==="Kelebihan Bayar"?"warn":"run";
 return badge(o.payment_status,c);
}
function prodBadge(o){
 return badge(o.status,o.life==="cancelled"?"bad":PROD_CLASS[o.status]);
}
function empty(title,msg=""){return `<div class="empty"><b>${esc(title)}</b>${esc(msg)}</div>`}

/* ================= AUTH ================= */
function loginScreen(){
 $("#app").innerHTML=`<form id="login-form" class="login card">
 <div class="brand" style="padding:0 0 18px"><div class="mark">RJ</div>
 <div><b>Rofi Jaya</b><span>MANAJEMEN PRODUKSI</span></div></div>
 <h1>Masuk sebagai owner</h1>
 <p class="muted tiny">Aplikasi internal. Data pesanan tidak tersedia untuk publik.</p>
 <label for="pw">Kata sandi owner</label>
 <input id="pw" type="password" name="password" minlength="12" required
  autocomplete="current-password" autofocus>
 <button type="submit" class="primary" style="width:100%;margin-top:16px">Masuk →</button>
 </form>`;
 bindForm("login-form",async d=>{
  const r=await api("login",d);csrf=r.csrf;await load();
 });
}

/* ================= SHELL ================= */
function navItems(){
 const active=S.orders.filter(o=>o.life==="active");
 return [
  ["dashboard","Dashboard",active.length],
  ["orders","Daftar Pesanan",S.orders.length],
  ["new","＋ Pesanan Baru",null],
  ["history","Riwayat",S.orders.filter(o=>o.life!=="active").length],
  ["settings","Pengaturan",null]
 ];
}
function render(){
 if(!S||!S.orders)return loginScreen();
 const items=navItems();
 const activeView=["detail","new"].includes(view)?"orders":view;
 $("#app").innerHTML=`<div class="shell">
 <aside class="side" id="side">
    <a href="#" class="brand" onclick="go('dashboard'); return false;" style="text-decoration:none; cursor:pointer;">
    <div class="mark">RJ</div>
    <div><b>${esc(S.settings.name||"Rofi Jaya")}</b><span>MANAJEMEN PRODUKSI</span></div>
  </a>
  <nav class="nav" aria-label="Navigasi utama">${items.map(([id,label,count])=>`
   <button data-nav="${id}" class="${activeView===id?"active":""}">${esc(label)}${
    count?`<span class="count">${count}</span>`:""}</button>`).join("")}</nav>
  <div class="side-foot">
   <span class="badge ${navigator.onLine?"ok":"bad"}" id="conn">${
    navigator.online?"● Server tersambung":"● Offline"}</span>
   <button class="small" id="logout">Keluar</button>
  </div>
 </aside>
 <div class="main">
  <header class="top">
   <div class="row" style="display:flex; align-items:center; gap:10px;">
    <button class="small menu-btn" id="menu" aria-label="Menu">☰ Menu</button>
    <span class="muted tiny">${fmtDate(S.today)}</span>
   </div>
   <div class="row">
    <a class="button small" href="/" target="_blank" rel="noopener">Lihat situs publik ↗</a>
    <button class="small" id="reload">↻ Muat ulang</button>
   </div>
  </header>
  <main class="content" id="content"></main>
 </div></div>`;
 $$("[data-nav]").forEach(b=>b.onclick=()=>{go(b.dataset.nav)});
 $("#menu").onclick=()=>$("#side").classList.toggle("open");
 $("#reload").onclick=refresh;
 $("#logout").onclick=async()=>{
  if(!await confirmBox("Keluar dari aplikasi?"))return;
  try{await api("logout",{});S=null;render()}catch(e){toast(e.message,true)}
 };
 const c=$("#content");
 if(view==="dashboard")renderDashboard(c);
 else if(view==="orders"||view==="history")renderOrders(c);
 else if(view==="new")renderNewOrder(c);
 else if(view==="detail")renderDetail(c);
 else if(view==="settings")renderSettings(c);
}
function go(v){
 view=v;sel="";tab="ringkasan";q="";
 filters={status:"",pay:"",sort:"recent",from:"",to:""};
 render();window.scrollTo(0,0);
}
function openOrder(id,which){
 sel=id;view="detail";tab=which||"ringkasan";render();window.scrollTo(0,0);
}
function current(){return S.orders.find(o=>o.id===sel)}

/* ================= DASHBOARD ================= */
function metrics(){
 const active=S.orders.filter(o=>o.life==="active"||o.life==="unpaid"||o.life==="paused");
 const by=k=>active.filter(o=>o.prod===k).length;
 const late=active.filter(o=>o.late).length;
 const sum=k=>active.reduce((a,o)=>a+(o[k]||0),0);
 const unpaid=S.orders.filter(o=>o.life!=="cancelled"&&o.remaining>0);
 return {
  active:active.length, potong:by("potong")+by("potong_done"),
  jahit:by("jahit")+by("jahit_done"), finishing:by("finishing"),
  siap:by("siap")+by("serah"), late,
  nilai:sum("total"), dp:sum("paid"), sisa:sum("remaining"),
  belumLunas:unpaid.length
 };
}
function renderDashboard(c){
 const m=metrics();
 const cards=[
  ["Pesanan aktif",m.active,"",'data-m="active"'],
  ["Sedang dipotong",m.potong,"",'data-m="potong"'],
  ["Sedang dijahit",m.jahit,"",'data-m="jahit"'],
  ["Finishing",m.finishing,"",'data-m="finishing"'],
  ["Siap diserahkan",m.siap,"accent",'data-m="siap"'],
  ["Lewat estimasi",m.late,"alert",'data-m="late"'],
  ["Belum lunas",m.belumLunas,"",'data-m="unpaid"'],
 ];
 const recent=[...S.orders].sort((a,b)=>(b.created||"").localeCompare(a.created||"")).slice(0,8);
 c.innerHTML=`<div class="head"><div><div class="eyebrow">ROFI JAYA · RUANG KERJA OWNER</div>
  <h1>Dashboard</h1><p>Semua angka dihitung langsung dari database pesanan.</p></div>
  <button class="primary" id="new-order">＋ Pesanan Baru</button></div>
 <div class="grid g4">${cards.map(([l,n,cls,attr])=>`
  <button class="stat ${cls}" ${attr}><span class="l">${l}</span>
   <span class="n">${n}</span><span class="l">pesanan</span></button>`).join("")}</div>
 <div class="grid g2" style="margin-top:14px">
  <div class="card tight"><h2>Nilai pesanan</h2>
   <div class="money"><span class="muted">Total nilai aktif</span><b>${rp(m.nilai)}</b></div>
   <div class="money"><span class="muted">DP & pembayaran diterima</span><b>${rp(m.dp)}</b></div>
   <div class="money"><span class="muted">Sisa pembayaran</span><b>${rp(m.sisa)}</b></div>
  </div>
  <div class="card tight"><h2>Tahap produksi</h2>
   ${["Menunggu Potong","Sedang Dipotong","Potong Selesai","Sedang Dijahit","Jahit Selesai",
      "Sedang Finishing","Siap Diserahkan","Selesai Diserahkan"].map(k=>{
     const n=S.orders.filter(o=>o.status===k&&o.life==="active").length;
     if(!n)return "";
     return `<div class="money"><span>${prodBadge({status:k})}</span><b>${n}</b></div>`;
   }).join("")||'<p class="muted tiny">Belum ada pesanan aktif.</p>'}
  </div>
 </div>
 <div class="card"><div class="row spread"><h2 style="margin:0">Pesanan terbaru</h2>
  <button class="small" id="see-all">Lihat semua →</button></div>
  ${recent.length?orderTable(recent):empty("Belum ada pesanan",
   "Mulai dengan menekan Pesanan Baru.")}</div>`;
 $("#new-order").onclick=()=>go("new");
 $("#see-all").onclick=()=>go("orders");
 $$("[data-m]").forEach(b=>b.onclick=()=>{
  go("orders");
  const map={potong:"potong",jahit:"jahit",finishing:"finishing",siap:"siap",
   late:"late",unpaid:"unpaid",active:""};
  filters.status=map[b.dataset.m]||"";render();
 });
 bindOrderRows();
}
function orderTable(rows){
 return `<div class="table-wrap"><table><thead><tr>
  <th class="nowrap">Nota</th><th>Konsumen</th><th>Model</th><th class="nowrap right">Jumlah</th>
  <th class="nowrap right">Total</th><th class="nowrap right">Sisa</th>
  <th class="nowrap">Estimasi</th><th>Produksi</th><th>Pembayaran</th><th></th>
 </tr></thead><tbody>${rows.map(o=>`<tr>
  <td class="nowrap"><button class="link" data-open="${o.id}">${esc(o.number)}</button>
   ${o.life!=="active"?`<div class="tiny muted">${esc(o.final_label||o.life)}</div>`:""}</td>
  <td>${esc(o.customer)}<div class="tiny muted">${esc(o.company||("+"+o.wa))}</div></td>
  <td>${esc(o.items.map(i=>i.garment).join(", "))}</td>
  <td class="right nowrap">${o.qty} pcs</td>
  <td class="right nowrap">${rp(o.total)}</td>
  <td class="right nowrap">${o.remaining?rp(o.remaining):'<span class="muted">Lunas</span>'}</td>
  <td class="nowrap">${fmtDate(o.target)}${o.late?'<div>'+badge("Terlambat","warn")+"</div>":""}</td>
  <td>${prodBadge(o)}</td><td>${payBadge(o)}</td>
  <td class="nowrap"><button class="small" data-open="${o.id}">Detail</button></td>
 </tr>`).join("")}</tbody></table></div>`;
}
function bindOrderRows(){
 $$("[data-open]").forEach(b=>b.onclick=()=>openOrder(b.dataset.open));
}

/* ================= DAFTAR PESANAN ================= */
function filteredRows(){
 const hist=view==="history";
 let rows=S.orders.filter(o=>hist?o.life!=="active":o.life==="active");
 const needle=q.trim().toLowerCase();
 if(needle)rows=rows.filter(o=>(o.number+" "+o.customer+" "+(o.company||"")+" "+
  o.items.map(i=>i.garment).join(" ")).toLowerCase().includes(needle));
 if(filters.status==="late")rows=rows.filter(o=>o.late);
 else if(filters.status==="unpaid")rows=rows.filter(o=>o.remaining>0);
 else if(filters.status==="siap")rows=rows.filter(o=>["siap","serah"].includes(o.prod));
 else if(filters.status)rows=rows.filter(o=>o.prod===filters.status||o.status===filters.status);
 if(filters.pay)rows=rows.filter(o=>o.payment_status===filters.pay);
 if(filters.from)rows=rows.filter(o=>o.deal>=filters.from);
 if(filters.to)rows=rows.filter(o=>o.deal<=filters.to);
 rows.sort((a,b)=>filters.sort==="recent"
  ?(b.created||"").localeCompare(a.created||"")
  :(a.target||"9999").localeCompare(b.target||"9999"));
 return rows;
}
function renderOrders(c){
 const hist=view==="history";
 const statuses=[["","Semua status"],["potong","Sedang dipotong"],["potong_done","Potong selesai"],
  ["jahit","Sedang dijahit"],["jahit_done","Jahit selesai"],["finishing","Finishing"],
  ["siap","Siap diserahkan"],["diterima","Selesai diserahkan"],["late","Lewat estimasi"],
  ["unpaid","Belum lunas"]];
 c.innerHTML=`<div class="head"><div><div class="eyebrow">PESANAN</div>
  <h1>${hist?"Riwayat pesanan":"Daftar pesanan"}</h1>
  <p>${hist?"Pesanan selesai, dibatalkan, dan diarsipkan tetap tersimpan.":
   "Cari, filter, dan kelola pesanan yang sedang berjalan."}</p></div>
  <button class="primary" id="new-order">＋ Pesanan Baru</button></div>
 <div class="filters">
  <div class="wide"><label>Cari</label>
   <input id="q" placeholder="Nomor nota, nama konsumen, instansi, atau model…" value="${esc(q)}"></div>
  <div><label>Status produksi</label><select id="f-status">${statuses.map(([v,l])=>
   `<option value="${v}" ${filters.status===v?"selected":""}>${esc(l)}</option>`).join("")}</select></div>
  <div><label>Pembayaran</label><select id="f-pay">${["","Belum Bayar","DP Dibayar",
   "Pembayaran Sebagian","Lunas"].map(v=>`<option value="${v}" ${
   filters.pay===v?"selected":""}>${v||"Semua"}</option>`).join("")}</select></div>
  <div><label>Urutkan</label><select id="f-sort">
   <option value="recent" ${filters.sort==="recent"?"selected":""}>Terbaru</option>
   <option value="target" ${filters.sort==="target"?"selected":""}>Estimasi terdekat</option>
  </select></div>
  <div><label>Kesepakatan dari</label><input type="date" id="f-from" value="${esc(filters.from)}"></div>
  <div><label>Sampai</label><input type="date" id="f-to" value="${esc(filters.to)}"></div>
 </div>
 <div id="rows"></div>`;
 $("#new-order").onclick=()=>go("new");
 $("#q").oninput=e=>{q=e.target.value;drawRows()};
 [["f-status","status"],["f-pay","pay"],["f-sort","sort"],["f-from","from"],["f-to","to"]]
  .forEach(([id,key])=>{$("#"+id).onchange=e=>{filters[key]=e.target.value;drawRows()}});
 drawRows();
}
function drawRows(){
 const rows=filteredRows();
 $("#rows").innerHTML=rows.length?orderTable(rows):
  `<div class="card">${empty("Tidak ada pesanan yang cocok",
   S.orders.length?"Ubah kata kunci atau filter Anda.":"Belum ada pesanan tercatat.")}</div>`;
 bindOrderRows();
}

/* ================= PESANAN BARU ================= */
function itemBlock(i,data={}){
 const sizes=(data.sizes||[]).map(s=>s.label+":"+s.qty).join(", ");
 return `<fieldset class="card tight" data-item="${i}" style="border:1px solid var(--line);margin:0 0 12px">
  <legend class="tiny muted" style="padding:0 6px">Item ${i+1}</legend>
  <div class="form">
   ${selField("Jenis pakaian *","garment",S.garments,data.garment||"")}
   ${field("Nama model / pesanan","name",data.name||"","text",'placeholder="Mis. Batik PDL Kantor"')}
   ${field("Bahan kain","material",data.material||"","text",'list="materials" placeholder="Mis. Katun combed"')}
   ${field("Warna bahan","color",data.color||"")}
   ${field("Jumlah pcs *","qty",data.qty||"","number",'min="1" required')}
   ${field("Harga deal per pcs *","price",data.price||"","number",'min="0" required')}
   ${field("Rincian ukuran (S:5, M:10)","sizes",sizes,"text",'placeholder="Opsional; total harus sama dengan jumlah"')}
   ${field("Sablon / bordir","printing",data.printing||"")}
   ${area("Deskripsi desain","design",data.design||"")}
   ${area("Catatan khusus item","note",data.note||"")}
  </div>
  <div class="row" style="margin-top:10px"><span class="tiny muted item-total">Subtotal: Rp0</span>
   <button type="button" class="small danger" data-del="${i}">Hapus item</button></div>
 </fieldset>`;
}
function itemsHTML(items){
 return `<div id="items">${(items&&items.length?items:[{}]).map(itemBlock).join("")}</div>
  <button type="button" class="small" id="add-item">＋ Tambah item lain</button>
  <datalist id="materials">${S.materials.map(m=>`<option value="${esc(m)}">`).join("")}</datalist>`;
}
function parseItems(form){
 const out=[];
 for(const fs of $$("[data-item]",form)){
  const e=n=>{
   const el=fs.querySelector(`[name="${n}"]`);
   if(!el)throw Error("Kolom "+n+" tidak ditemukan pada item pesanan.");
   return el;
  };
  const garment=e("garment").value;
  const qty=Number(e("qty").value||0);
  const price=Number(e("price").value||0);
  const sizes=[];
  let sizeTotal=0;
  for(const part of (e("sizes").value||"").split(",")){
   const p=part.trim();if(!p)continue;
   const [label,n]=p.split(":");
   if(!label||!n||!/^\d+$/.test(n.trim()))
    throw Error("Format ukuran harus seperti S:5, M:10, L:15.");
   const amount=Number(n.trim());
   if(amount>0){sizes.push({label:label.trim(),qty:amount});sizeTotal+=amount}
  }
  if(!qty||qty<1)throw Error("Jumlah pcs setiap item wajib diisi minimal 1.");
  if(sizes.length&&sizeTotal!==qty)
   throw Error(`Total rincian ukuran (${sizeTotal}) harus sama dengan jumlah pcs (${qty}).`);
  out.push({garment,name:e("name").value,material:e("material").value,
   color:e("color").value,qty,price,sizes,printing:e("printing").value,
   design:e("design").value,note:e("note").value});
 }
 return out;
}
function bindItems(form){
 const update=()=>{
  let total=0;
  for(const fs of $$("[data-item]",form)){
   const qty=Number(fs.querySelector('[name="qty"]').value||0);
   const price=Number(fs.querySelector('[name="price"]').value||0);
   fs.querySelector(".item-total").textContent="Subtotal: "+rp(qty*price);
   total+=qty*price;
  }
  const disc=Number(form.elements.discount?.value||0);
  const extra=Number(form.elements.extra?.value||0);
  const grand=total-disc+extra;
  const box=$("#grand",form);
  if(box)box.innerHTML=`Total item: <b>${rp(total)}</b> · Total pesanan: <b>${rp(grand)}</b>`;
 };
 form.oninput=update;
 form.onclick=e=>{
  if(e.target.id==="add-item"){
   e.preventDefault();
   const n=$$("[data-item]",form).length;
   if(n>=20)return toast("Maksimal 20 item per pesanan.",true);
   $("#items",form).insertAdjacentHTML("beforeend",itemBlock(n));
   bindItems(form);
  }
  if(e.target.dataset.del!==undefined){
   e.preventDefault();
   const blocks=$$("[data-item]",form);
   if(blocks.length===1)return toast("Pesanan harus punya minimal satu item.",true);
   e.target.closest("[data-item]").remove();bindItems(form);
  }
 };
 update();
}
function renderNewOrder(c){
 c.innerHTML=`<div class="head"><div><div class="eyebrow">PESANAN BARU</div>
  <h1>Catat kesepakatan</h1><p>Tanggal kesepakatan menjadi titik awal transaksi dan nota.</p></div>
  <button id="back">← Kembali</button></div>
 <form id="order-form">
  <div class="card"><h2>01 · Kesepakatan & konsumen</h2><div class="form">
   ${field("Tanggal kesepakatan *","deal",today(),"date","required")}
   ${field("Nama konsumen *","customer","","text",'required maxlength="150"')}
   ${field("Nomor WhatsApp *","wa","","tel",'required placeholder="0812… / +62…"')}
   ${field("Instansi / sekolah / komunitas","company","","text",'maxlength="200"')}
   ${area("Alamat / catatan pengiriman","address")}
   ${area("Catatan konsumen","customer_note")}
   ${area("Catatan kesepakatan (tampil di nota)","agreement_note")}
  </div></div>
  <div class="card"><h2>02 · Item pesanan</h2>${itemsHTML()}</div>
  <div class="card"><h2>03 · Harga & jadwal</h2><div class="form">
   ${field("Diskon (Rp)","discount",0,"number",'min="0"')}
   ${field("Biaya tambahan (Rp)","extra",0,"number",'min="0"')}
   <div class="full"><div class="notice" id="grand"></div></div>
   ${field("Estimasi selesai produksi *","target","","date","required")}
   ${field("Target pelunasan","target_payment","","date")}
   ${field("DP diterima (Rp)","dp",0,"number",'min="0"')}
   ${field("Tanggal DP","dp_date",today(),"date")}
   ${selField("Metode DP","dp_method",S.methods,"Tunai")}
   ${field("Catatan DP","dp_note","")}
  </div></div>
  <div class="row spread" style="margin-bottom:40px">
   <span class="muted tiny">Status awal: Menunggu Potong. Tidak ada tahap yang otomatis selesai.</span>
   <button type="submit" class="primary">Simpan pesanan →</button></div>
 </form>`;
 $("#back").onclick=()=>go("orders");
 const form=$("#order-form");
 const t=form.elements.target;
 const d=new Date(Date.now()+7*3600e3);
 d.setDate(d.getDate()+Number(S.settings.default_days||14));
 t.value=d.toISOString().slice(0,10);
 bindItems(form);
 bindForm("order-form",async data=>{
  const payload={...data,items:parseItems(form)};
  payload.discount=Number(payload.discount||0);
  payload.extra=Number(payload.extra||0);
  payload.dp=Number(payload.dp||0);
  const r=await api("v2/orders",payload);
  await load();
  toast("Pesanan "+r.number+" tersimpan di database.");
  openOrder(r.id);
 });
}

/* ================= DETAIL ================= */
function renderDetail(c){
 const o=current();
 if(!o){go("orders");return}
 c.innerHTML=`<div class="head"><div><div class="eyebrow">${esc(o.number)} · ${esc(o.life==="active"?"AKTIF":(o.final_label||o.life).toUpperCase())}</div>
  <h1>${esc(o.customer)}</h1>
  <p>${esc(o.company||"Konsumen perorangan")} · ${o.qty} pcs · ${esc(o.items.map(i=>i.garment).join(", "))}</p></div>
  <div class="row"><button id="back">← Kembali</button>
   <button class="wa" id="wa">Bagikan WhatsApp</button>
   <a class="button" href="/nota/${esc(o.tracking_token)}" target="_blank" rel="noopener">Nota digital ↗</a></div></div>
 <div class="row" style="margin-bottom:16px">${prodBadge(o)}${payBadge(o)}
  ${o.late?badge("Lewat estimasi","warn"):""}
  <span class="tiny muted">Estimasi selesai ${fmtDate(o.target)} · sisa ${rp(o.remaining)}</span></div>
 <div class="tabs">${[["ringkasan","Ringkasan"],["item","Item & ukuran"],["produksi","Tahapan produksi"],
  ["pembayaran","Pembayaran"],["nota","Nota & tracking"],["riwayat","Riwayat aktivitas"]]
  .map(([id,l])=>`<button data-tab="${id}" class="${tab===id?"active":""}">${l}</button>`).join("")}</div>
 <div id="tab-body"></div>`;
 $("#back").onclick=()=>go("orders");
 $("#wa").onclick=()=>waDialog(o);
 $$("[data-tab]").forEach(b=>b.onclick=()=>{tab=b.dataset.tab;render()});
 const b=$("#tab-body");
 if(tab==="ringkasan")tabSummary(b,o);
 else if(tab==="item")tabItems(b,o);
 else if(tab==="produksi")tabProduction(b,o);
 else if(tab==="pembayaran")tabPayments(b,o);
 else if(tab==="nota")tabNota(b,o);
 else tabHistory(b,o);
}
function tabSummary(b,o){
 b.innerHTML=`<div class="grid g2">
  <div class="card"><h2>Kesepakatan</h2><div class="kv">
   ${[["Nomor nota",o.number],["Tanggal kesepakatan",fmtDate(o.deal)],
     ["Estimasi selesai",fmtDate(o.target)],["Target pelunasan",fmtDate(o.target_payment)],
     ["Konsumen",o.customer],["WhatsApp","+"+o.wa],["Instansi",o.company||"—"],
     ["Alamat",o.address||"—"],["Catatan konsumen",o.customer_note||"—"],
     ["Catatan kesepakatan",o.agreement_note||"—"]]
    .map(([k,v])=>`<span>${k}</span><b>${esc(v)}</b>`).join("")}</div>
   <div class="row" style="margin-top:14px">
    ${["active","paused","unpaid"].includes(o.life)?'<button id="edit">Revisi kesepakatan</button>':""}
    ${o.life==="active"?'<button class="danger" id="cancel">Batalkan pesanan</button>':""}
    ${o.life==="paused"?'<button id="resume">Aktifkan kembali</button>':""}
    ${o.life==="cancelled"?'<button id="archive">Arsipkan</button>':""}
    ${o.life==="diterima"&&o.remaining===0?'<button class="primary" id="finish">Tandai pesanan selesai</button>':""}
   </div></div>
  <div><div class="card"><h2>Keuangan</h2>
   <div class="money"><span class="muted">Total item</span><b>${rp(o.base)}</b></div>
   <div class="money"><span class="muted">Diskon</span><b>− ${rp(o.discount)}</b></div>
   <div class="money"><span class="muted">Biaya tambahan</span><b>${rp(o.extra)}</b></div>
   <div class="money"><span class="muted">Total kesepakatan</span><b>${rp(o.total)}</b></div>
   <div class="money"><span class="muted">Diterima</span><b>${rp(o.paid)}</b></div>
   <div class="money"><span class="muted">Sisa</span><b>${rp(o.remaining)}</b></div></div>
   <div class="card"><h2>Status</h2><div class="kv">
    <span>Produksi</span><b>${esc(o.status)}</b>
    <span>Pembayaran</span><b>${esc(o.payment_status)}</b>
    <span>Penyerahan</span><b>${o.received?"Diserahkan "+fmtDate(o.received):"Belum diserahkan"}</b>
    <span>Terakhir diubah</span><b>${fmtDT(o.updated_at)}</b></div></div></div>
 </div>`;
 if($("#edit"))$("#edit").onclick=()=>editOrder(o);
 if($("#cancel"))$("#cancel").onclick=()=>lifeDialog(o,"cancelled");
 if($("#resume"))$("#resume").onclick=()=>lifeDialog(o,"active");
 if($("#archive"))$("#archive").onclick=()=>lifeDialog(o,"archived");
 if($("#finish"))$("#finish").onclick=()=>lifeDialog(o,"done");
}
function tabItems(b,o){
 b.innerHTML=`<div class="card"><div class="row spread"><h2 style="margin:0">Item pesanan</h2>
  <span class="muted tiny">${o.items.length} item · ${o.qty} pcs</span></div>
 ${o.items.map(it=>`<div class="card tight" style="margin-top:12px">
  <div class="row spread"><b>${esc(it.garment)}</b><span>${rp(it.price)} /pcs · ${it.qty} pcs ·
   <b>${rp(it.subtotal)}</b></span></div>
  <div class="kv" style="margin-top:10px">
   ${[["Nama model",it.name],["Bahan",it.material||"—"],["Warna",it.color||"—"],
     ["Sablon/bordir",it.printing||"—"],
     ["Ukuran",it.sizes.map(s=>s.label+": "+s.qty).join(" · ")||"—"],
     ["Desain",it.design||"—"],["Catatan",it.note||"—"]]
    .map(([k,v])=>`<span>${k}</span><b>${esc(v)}</b>`).join("")}</div>
 </div>`).join("")}
 <div class="notice">Harga per pcs × jumlah pcs = subtotal item. Revisi kesepakatan tercatat
 di riwayat dan nota selalu menampilkan data terbaru.</div></div>`;
}
function tabProduction(b,o){
 const done=o.stages.filter(s=>s.state==="done").length;
 const clDone=o.checklist.filter(x=>x.done).length;
 b.innerHTML=`<div class="tl">${o.stages.map((s,i)=>`
  <div class="step ${s.state}"><span class="dot">${s.state==="done"?"✓":i+1}</span>
   <b>${esc(s.label)}</b>
   <span class="tiny muted">${esc({pending:"Belum dimulai",running:"Sedang dikerjakan",done:"Selesai"}[s.state])}</span>
   ${s.finished_at?`<div class="tiny muted">${fmtDate(s.finished_at)}</div>`:""}</div>`).join("")}</div>
 <div class="card tight"><div class="row spread">
  <span class="muted tiny">Progres ${done} dari ${o.stages.length} tahap</span></div>
  <div class="progress" style="margin-top:8px"><i style="width:${Math.round(done/o.stages.length*100)}%"></i></div></div>
 ${o.stages.map((s,i)=>{
  const prev=i===0||o.stages[i-1].state==="done";
  const active=o.life==="active";
  return `<div class="card"><div class="row spread"><h2 style="margin:0">${i+1}. ${esc(s.label)}</h2>
   ${badge({pending:"Belum Dimulai",running:"Sedang Dikerjakan",done:"Selesai"}[s.state],
    {done:"ok",running:"run",pending:""}[s.state])}</div>
   <div class="kv" style="margin-top:10px">
    <span>Target tahap</span><b>${fmtDate(s.target)}</b>
    <span>Mulai</span><b>${s.start?fmtDate(s.start):"—"}</b>
    <span>Selesai aktual</span><b>${s.finished_at?fmtDT(s.finished_at):"—"}</b>
    <span>Catatan</span><b>${esc(s.note||"—")}</b></div>
   <div class="row" style="margin-top:12px">
    ${active&&s.state==="pending"&&prev?`<button class="primary" data-start="${s.key}">Mulai ${esc(s.label)}</button>`:""}
    ${active&&s.state==="running"?`<button class="primary" data-finish="${s.key}">Selesaikan ${esc(s.label)}</button>`:""}
    ${active&&s.state!=="pending"?`<button class="small" data-note="${s.key}">Catatan / target</button>`:""}
    ${active&&s.state==="done"?`<button class="small" data-reopen="${s.key}">Buka kembali</button>`:""}
   </div>
   ${s.state==="pending"&&!prev?'<p class="tiny muted" style="margin:10px 0 0">Tahap sebelumnya belum selesai.</p>':""}
   
   <!-- TOMBOL UPLOAD FOTO -->
   <div class="row" style="margin-top:16px;border-top:1px solid var(--line);padding-top:12px">
    <span class="muted tiny">Foto tahap ini:</span>
    <button class="small wa" data-upload="${s.key}">＋ Tambah Foto</button>
    ${o.photos && o.photos.filter(p=>p.stage===s.key).map(p=>`
      <a href="${esc(p.remote_url)}" target="_blank" rel="noopener" class="badge accent" style="text-decoration:none">
        ${esc(p.caption||"Lihat Foto")}
      </a>`).join("")}
   </div>

   ${s.key==="finishing"?`<hr style="border:0;border-top:1px solid var(--line);margin:16px 0">
    <div class="row spread"><h3 style="margin:0">Checklist finishing</h3>
     <span class="muted tiny">${clDone} dari ${o.checklist.length} pekerjaan selesai</span></div>
    ${o.checklist.map(x=>`<label class="check ${x.done?"done":""}">
     <input type="checkbox" data-cl="${x.id}" ${x.done?"checked":""}
      ${active&&s.state!=="pending"?"":"disabled"}>
     <span>${esc(x.label)}</span>${x.done?`<span class="tiny muted" style="margin-left:auto">${fmtDate(x.done_at)}</span>`:""}
    </label>`).join("")}
    ${active&&s.state==="running"&&clDone<o.checklist.length?
     '<p class="tiny muted" style="margin-top:10px">Selesaikan seluruh checklist sebelum menutup tahap finishing.</p>':""}`
    :""}
   ${s.key==="serah"&&s.state!=="done"?`<div class="notice">Setelah finishing selesai, catat
     penyerahan melalui tombol di bawah agar tracking konsumen menunjukkan "Selesai Diserahkan".</div>
    ${o.stages[2].state==="done"&&active?`<button class="primary" data-handover="1">Catat penyerahan</button>`:""}`:""}
  </div>`;
 }).join("")}`;
 
 $$("[data-start]").forEach(btn=>btn.onclick=()=>stageStartDialog(o,btn.dataset.start));
 $$("[data-finish]").forEach(btn=>btn.onclick=()=>stageFinish(o,btn.dataset.finish));
 $$("[data-note]").forEach(btn=>btn.onclick=()=>stageNoteDialog(o,btn.dataset.note));
 $$("[data-reopen]").forEach(btn=>btn.onclick=()=>stageReopen(o,btn.dataset.reopen));
 $$("[data-upload]").forEach(btn=>btn.onclick=()=>uploadPhotoDialog(o,btn.dataset.upload));
 
 $$("[data-cl]").forEach(cb=>cb.onchange=async()=>{
  try{
   const r=await api("v2/orders/"+o.id+"/checklist",{item:cb.dataset.cl});
   await load();toast("Checklist "+r.done+"/"+r.total+" selesai.");
   render();
  }catch(e){toast(e.message,true);cb.checked=!cb.checked}
 });
 if($("[data-handover]"))$("[data-handover]").onclick=()=>handoverDialog(o);
}

function uploadPhotoDialog(o, stage) {
 const stageLabel = o.stages.find(s=>s.key===stage)?.label || stage;
 dialog("Upload Foto: "+stageLabel, `
  <form id="upload-form" class="form">
   <div class="full">
    <label>Pilih Foto (Maks 5MB)</label>
    <input type="file" id="f-photo" accept="image/jpeg, image/png, image/webp" required>
   </div>
   ${field("Keterangan Foto","caption","","text",'placeholder="Mis. Hasil potongan kain"')}
  </form>
 `, `<button id="cancel">Batal</button><button class="primary" id="go">Upload Foto</button>`);
 
 $("#cancel").onclick=()=>modal.close();
 $("#go").onclick=async()=>{
  const fileInput = $("#f-photo");
  if(!fileInput.files.length) return toast("Pilih foto terlebih dahulu.", true);
  const file = fileInput.files[0];
  if(file.size > 5 * 1024 * 1024) return toast("Foto maksimal 5MB.", true);
  
  const caption = $("#f-caption").value;
  const btn = $("#go");
  btn.disabled=true; btn.textContent="Mengunggah...";
  
  try {
   const reader = new FileReader();
   reader.onload = async (e) => {
    const base64Data = e.target.result;
    try {
     await api("v2/orders/"+o.id+"/upload-photo", {
      stage: stage,
      caption: caption,
      data: base64Data
     });
     toast("Foto berhasil diunggah!");
     modal.close();
     await load();
     render();
    } catch(err) {
     toast(err.message, true);
     btn.disabled=false; btn.textContent="Upload Foto";
    }
   };
   reader.readAsDataURL(file);
  } catch(err) {
   toast(err.message, true);
   btn.disabled=false; btn.textContent="Upload Foto";
  }
 };
}

function stageStartDialog(o,key){
 const s=o.stages.find(x=>x.key===key);
 dialog("Mulai tahap: "+s.label,`<form id="start-form"><div class="form">
  ${field("Tanggal mulai aktual *","start",today(),"date",`required max="${today()}"`)}
  ${field("Target selesai tahap","target",s.target||o.target,"date")}
  ${area("Catatan produksi / kebutuhan bahan","note",s.note||"")}
  </div><div class="notice">Waktu mulai dicatat di server dan langsung terlihat pada tracking konsumen.</div>
  </form>`,`<button id="cancel">Batal</button><button class="primary" id="go">Mulai ${esc(s.label)}</button>`);
 $("#cancel").onclick=()=>modal.close();
 $("#go").onclick=async()=>{
  const d=Object.fromEntries(new FormData($("#start-form")));
  try{
   await api("v2/orders/"+o.id+"/stage",{action:"start",stage:key,...d});
   modal.close();await load();render();toast("Tahap "+s.label+" dimulai.");
  }catch(e){toast(e.message,true)}
 };
}
function stageFinish(o,key){
 const s=o.stages.find(x=>x.key===key);
 const extra=key==="finishing"
  ? `<div class="notice">Checklist: ${o.checklist.filter(x=>x.done).length}/${o.checklist.length} selesai.
     Status pesanan akan menjadi "Siap Diserahkan".</div>`
  : `<div class="notice">Waktu selesai aktual akan dicatat. Tracking konsumen diperbarui.</div>`;
 dialog("Selesaikan tahap: "+s.label,
  `<p class="wrap-text">Konfirmasi bahwa pekerjaan <b>${esc(s.label)}</b> benar-benar sudah selesai.</p>${extra}`,
  `<button id="cancel">Batal</button><button class="primary" id="go">Selesaikan ${esc(s.label)}</button>`);
 $("#cancel").onclick=()=>modal.close();
 $("#go").onclick=async()=>{
  $("#go").disabled=true;
  try{
   await api("v2/orders/"+o.id+"/stage",{action:"finish",stage:key});
   modal.close();await load();render();toast("Tahap "+s.label+" selesai.");
  }catch(e){toast(e.message,true);$("#go").disabled=false}
 };
}
function stageNoteDialog(o,key){
 const s=o.stages.find(x=>x.key===key);
 dialog("Catatan tahap: "+s.label,`<form id="note-form"><div class="form">
  ${field("Target selesai tahap","target",s.target||"","date")}
  ${area("Catatan produksi","note",s.note||"")}
  </div></form>`,`<button id="cancel">Batal</button><button class="primary" id="go">Simpan</button>`);
 $("#cancel").onclick=()=>modal.close();
 $("#go").onclick=async()=>{
  try{
   const d=Object.fromEntries(new FormData($("#note-form")));
   await api("v2/orders/"+o.id+"/stage",{action:"note",stage:key,...d});
   modal.close();await load();render();toast("Catatan tahap tersimpan.");
  }catch(e){toast(e.message,true)}
 };
}
function stageReopen(o,key){
 const s=o.stages.find(x=>x.key===key);
 dialog("Buka kembali tahap: "+s.label,`<form id="reopen-form">
  ${area("Alasan membuka kembali *","reason","",'required')}
  </form><div class="notice warn">Tahap setelahnya harus dibuka kembali lebih dulu.
  Tindakan ini dicatat di riwayat aktivitas.</div>`,
  `<button id="cancel">Batal</button><button class="danger" id="go">Buka kembali</button>`);
 $("#cancel").onclick=()=>modal.close();
 $("#go").onclick=async()=>{
  try{
   const d=Object.fromEntries(new FormData($("#reopen-form")));
   await api("v2/orders/"+o.id+"/stage",{action:"reopen",stage:key,...d});
   modal.close();await load();render();toast("Tahap dibuka kembali.");
  }catch(e){toast(e.message,true)}
 };
}
function handoverDialog(o){
 dialog("Catat penyerahan",`<form id="ho-form"><div class="form">
  ${selField("Metode *","method",S.handover,"Diambil konsumen")}
  ${field("Tanggal serah terima *","date",today(),"date",`required max="${today()}"`)}
  ${field("Kurir / ekspedisi","courier","")}
  ${field("Nomor resi","tracking","")}
  ${area("Catatan penyerahan","note","")}
  </div><div class="notice">Pesanan ditandai "Selesai Diserahkan". Status pembayaran
  tetap dikelola terpisah.</div></form>`,
  `<button id="cancel">Batal</button><button class="primary" id="go">Konfirmasi penyerahan</button>`);
 $("#cancel").onclick=()=>modal.close();
 $("#go").onclick=async()=>{
  try{
   const d=Object.fromEntries(new FormData($("#ho-form")));
   await api("v2/orders/"+o.id+"/handover",d);
   modal.close();await load();render();toast("Penyerahan tercatat.");
  }catch(e){toast(e.message,true)}
 };
}
function lifeDialog(o,life){
 const labels={cancelled:"Batalkan pesanan",active:"Aktifkan kembali",
  archived:"Arsipkan pesanan",done:"Tandai pesanan selesai"};
 dialog(labels[life],`<form id="life-form">
  ${area("Alasan perubahan *","reason","",'required')}</form>
  <div class="notice">Perubahan status dicatat di riwayat. Riwayat transaksi tidak dihapus.</div>`,
  `<button id="cancel">Batal</button><button class="${life==="cancelled"?"danger":"primary"}" id="go">Konfirmasi</button>`);
 $("#cancel").onclick=()=>modal.close();
 $("#go").onclick=async()=>{
  try{
   const d=Object.fromEntries(new FormData($("#life-form")));
   await api("v2/orders/"+o.id+"/life",{life,...d});
   modal.close();await load();toast("Status pesanan diperbarui.");
  }catch(e){toast(e.message,true)}
 };
}
function editOrder(o){
 dialog("Revisi kesepakatan",`<form id="edit-form"><div class="form">
  ${field("Nama konsumen *","customer",o.customer,"text",'required')}
  ${field("Nomor WhatsApp *","wa",o.wa,"tel","required")}
  ${field("Instansi","company",o.company||"")}
  ${field("Tanggal kesepakatan *","deal",o.deal,"date","required")}
  ${field("Estimasi selesai *","target",o.target,"date","required")}
  ${field("Target pelunasan","target_payment",o.target_payment||"","date")}
  ${area("Alamat","address",o.address||"")}
  ${area("Catatan kesepakatan","agreement_note",o.agreement_note||"")}
  ${field("Diskon (Rp)","discount",o.discount,"number",'min="0"')}
  ${field("Biaya tambahan (Rp)","extra",o.extra,"number",'min="0"')}
  <div class="full"><h3 style="margin:6px 0 0">Item & harga</h3></div>
  <div class="full" id="edit-items">${o.items.map((it,i)=>`<div class="card tight" data-eitem="${i}"
    style="margin:0 0 10px;background:#1B201D"><div class="form">
    ${selField("Jenis pakaian","garment",S.garments,it.garment,"","garment")}
    ${field("Nama model","name",it.name,"text","","name")}
    ${field("Jumlah pcs *","qty",it.qty,"number",'min="1" required',"qty")}
    ${field("Harga per pcs *","price",it.price,"number",'min="0" required',"price")}
    ${field("Ukuran (S:5, M:10)","sizes",it.sizes.map(x=>x.label+":"+x.qty).join(", "),"text","","sizes")}
    ${field("Bahan","material",it.material,"text","","material")}
    ${field("Warna","color",it.color,"text","","color")}
    ${field("Sablon / bordir","printing",it.printing,"text","","printing")}
   </div></div>`).join("")}</div>
  ${area("Alasan revisi *","reason","",'required')}
  </div><div class="notice">Perubahan item, harga, dan jadwal disimpan sebagai revisi baru
  dan dicatat di riwayat aktivitas. Nota selalu menampilkan versi terbaru.</div>
  </form>`,`<button id="cancel">Batal</button><button class="primary" id="go">Simpan revisi</button>`);
 $("#cancel").onclick=()=>modal.close();
 $("#go").onclick=async()=>{
  try{
   const d=Object.fromEntries(new FormData($("#edit-form")));
   const sizeText=sizes=>{
    const out=[];
    for(const part of (sizes||"").split(",")){
     const p=part.trim();if(!p)continue;
     const [label,n]=p.split(":");
     if(!label||!/^\d+$/.test(String(n||"").trim()))
      throw Error("Format ukuran harus seperti S:5, M:10.");
     if(Number(n)>0)out.push({label:label.trim(),qty:Number(n)});
    }
    return out;
   };
   const items=$$("[data-eitem]").map(fs=>{
    const g=n=>fs.querySelector(`[data-k="${n}"]`).value;
    return {garment:g("garment"),name:g("name"),qty:Number(g("qty")),
     price:Number(g("price")),sizes:sizeText(g("sizes")),material:g("material"),
     color:g("color"),printing:g("printing"),design:"",note:""};
   });
   await api("v2/orders/"+o.id+"/edit",{...d,items,
    customer_note:o.customer_note||"",agreement_note:d.agreement_note});
   modal.close();await load();render();toast("Revisi tersimpan.");
  }catch(e){toast(e.message,true)}
 };
}
function tabPayments(b,o){
 b.innerHTML=`<div class="grid g3">
  ${[["Total kesepakatan",o.total],["Diterima",o.paid],["Sisa",o.remaining]].map(([l,n])=>
   `<div class="card tight"><span class="muted tiny">${l}</span>
    <h2 style="margin:8px 0 0">${rp(n)}</h2></div>`).join("")}</div>
 <div class="card"><div class="row spread"><h2 style="margin:0">Transaksi pembayaran</h2>
  <div class="row">${payBadge(o)}
   ${o.remaining>0&&o.life!=="cancelled"?'<button class="primary" id="pay">＋ Tambah pembayaran</button>':""}</div></div>
  ${o.payments.length?`<div class="table-wrap" style="margin-top:12px"><table><thead><tr>
   <th>Tanggal</th><th>Jenis</th><th>Metode</th><th class="right">Nominal</th>
   <th>Catatan</th><th></th></tr></thead><tbody>
   ${o.payments.map(p=>`<tr><td class="nowrap">${fmtDate(p.date)}</td><td>${esc(p.kind)}</td>
    <td>${esc(p.method||"—")}</td><td class="right nowrap"><b>${rp(p.amount)}</b></td>
    <td>${esc(p.note||p.reference||"—")}</td>
    <td><button class="small" data-void="${p.id}">Koreksi</button></td></tr>`).join("")}
   </tbody></table></div>`:empty("Belum ada pembayaran","Catat DP atau pembayaran yang benar-benar diterima.")}
  ${o.voided_payments.length?`<details style="margin-top:14px"><summary>Pembayaran yang dikoreksi
   (${o.voided_payments.length})</summary><table><tbody>
   ${o.voided_payments.map(p=>`<tr><td>${fmtDate(p.date)}</td><td>${rp(p.amount)}</td>
    <td class="tiny muted">${esc(p.void_reason)}</td></tr>`).join("")}</tbody></table></details>`:""}
  <div class="notice">Setiap pembayaran disimpan sebagai transaksi terpisah. Koreksi tidak
  menghapus jejak transaksi.</div></div>`;
 if($("#pay"))$("#pay").onclick=()=>payDialog(o);
 $$("[data-void]").forEach(btn=>btn.onclick=()=>voidDialog(o,btn.dataset.void));
}
function payDialog(o){
 dialog("Tambah pembayaran",`<form id="pay-form">
  <div class="notice">Sisa tagihan: <b>${rp(o.remaining)}</b></div><div class="form">
  ${field("Tanggal pembayaran *","date",today(),"date",`required min="${o.deal}" max="${today()}"`)}
  ${field("Nominal diterima (Rp) *","amount",o.remaining,"number",`min="1" max="${o.remaining}" required`)}
  ${selField("Metode *","method",S.methods,"Transfer bank")}
  ${field("Referensi transaksi","reference","")}
  ${area("Keterangan","note","")}
  </div></form>`,`<button id="cancel">Batal</button><button class="primary" id="go">Simpan pembayaran</button>`);
 $("#cancel").onclick=()=>modal.close();
 $("#go").onclick=async()=>{
  try{
   const d=Object.fromEntries(new FormData($("#pay-form")));
   d.amount=Number(d.amount);
   if(!await confirmBox("Catat penerimaan pembayaran sebesar "+rp(d.amount)+"?"))return;
   await api("v2/orders/"+o.id+"/payment",d);
   modal.close();await load();render();toast("Pembayaran tersimpan.");
  }catch(e){toast(e.message,true)}
 };
}
function voidDialog(o,pid){
 dialog("Koreksi pembayaran",`<form id="void-form">
  ${area("Alasan koreksi *","reason","",'required')}</form>
  <div class="notice warn">Transaksi tidak dihapus, hanya ditandai dikoreksi. Sisa tagihan dihitung ulang.</div>`,
  `<button id="cancel">Batal</button><button class="danger" id="go">Koreksi</button>`);
 $("#cancel").onclick=()=>modal.close();
 $("#go").onclick=async()=>{
  try{
   const d=Object.fromEntries(new FormData($("#void-form")));
   await api("v2/orders/"+o.id+"/payment/"+pid+"/void",d);
   modal.close();await load();render();toast("Pembayaran dikoreksi.");
  }catch(e){toast(e.message,true)}
 };
}
function tabNota(b,o){
 b.innerHTML=`<div class="card"><h2>Nota digital & tracking</h2>
  <div class="kv"><span>Nota</span><b class="mono">${esc(o.urls.nota)}</b>
   <span>Tracking</span><b class="mono">${esc(o.urls.tracking)}</b></div>
  <div class="row" style="margin-top:14px">
   <a class="button" href="${esc(o.urls.nota)}" target="_blank" rel="noopener">Buka nota ↗</a>
   <button id="copy-nota">Salin link nota</button>
   <a class="button" href="${esc(o.urls.tracking)}" target="_blank" rel="noopener">Buka tracking ↗</a>
   <button id="copy-track">Salin link tracking</button>
  </div>
  <div class="notice">Nota dapat dicetak/di-simpan sebagai PDF dari halaman nota
  (tombol Cetak). Token tracking bersifat acak dan tidak memakai nomor pesanan.</div></div>
 <div class="card"><h2>Pratinjau isi nota</h2>
  <table><thead><tr><th>Model</th><th>Ukuran</th><th class="right">Qty</th>
   <th class="right">Harga/pcs</th><th class="right">Subtotal</th></tr></thead><tbody>
   ${o.items.map(i=>`<tr><td>${esc(i.garment)}<div class="tiny muted">${esc(i.material||"")}</div></td>
    <td>${esc(i.sizes.map(s=>s.label+": "+s.qty).join(", ")||"—")}</td>
    <td class="right">${i.qty}</td><td class="right">${rp(i.price)}</td>
    <td class="right">${rp(i.subtotal)}</td></tr>`).join("")}
  </tbody></table>
  <div class="money" style="margin-top:12px"><span class="muted">Total kesepakatan</span><b>${rp(o.total)}</b></div>
  <div class="money"><span class="muted">Diterima</span><b>${rp(o.paid)}</b></div>
  <div class="money"><span class="muted">Sisa</span><b>${rp(o.remaining)}</b></div></div>`;
 const copy=async(text,label)=>{
  try{await navigator.clipboard.writeText(text);toast(label+" disalin.")}
  catch(e){toast("Salin manual: "+text,true)}
 };
 $("#copy-nota").onclick=()=>copy(o.urls.nota,"Link nota");
 $("#copy-track").onclick=()=>copy(o.urls.tracking,"Link tracking");
}
function tabHistory(b,o){
 b.innerHTML=`<div class="card"><h2>Riwayat aktivitas</h2>
  <p class="muted tiny">Waktu server (WIB). Riwayat tidak ditimpa saat data berubah.</p>
  <ul class="history">${o.history.length?o.history.map(h=>`<li>
   <b>${esc(h.message)}</b><span class="tiny muted">${fmtDT(h.at)} · ${esc(h.actor)}</span>
   ${h.detail?`<details><summary>Rincian</summary><pre>${esc(JSON.stringify(h.detail,null,2))}</pre></details>`:""}
  </li>`).join(""):'<li class="muted tiny">Belum ada aktivitas.</li>'}</ul></div>`;
}
function waDialog(o){
 dialog("Bagikan via WhatsApp",`<div class="form">
  ${selField("Jenis pesan","kind",[["nota","Nota digital"],["tracking","Link tracking produksi"],
   ["progres","Update progres"]],"nota")}
  ${area("Catatan tambahan","extra","")}
  <div class="full"><label>Pesan (dapat disunting)</label>
   <textarea id="wa-msg" style="min-height:200px"></textarea></div>
  </div><div class="notice">Pilih <b>Kirim Otomatis</b> untuk mengirim langsung via Fonnte, 
  atau <b>Buka WhatsApp</b> untuk mengirim manual.</div>`,
  `<button id="copy">Salin pesan</button>
   <a class="button wa" id="open" target="_blank" rel="noopener">Buka WhatsApp ↗</a>
   <button class="primary" id="send-auto">Kirim Otomatis (Fonnte)</button>`);
   
 const build=async()=>{
  const kind=$("#modal-body select[name=kind]").value;
  const extra=$("#modal-body textarea[name=extra]").value;
  try{
   const r=await api("v2/orders/"+o.id+"/wa",{kind,extra});
   $("#wa-msg").value=r.message;
   $("#open").href=r.url;
  }catch(e){toast(e.message,true)}
 };
 
 $("#modal-body select[name=kind]").onchange=build;
 $("#modal-body textarea[name=extra]").oninput=build;
 
 $("#copy").onclick=async()=>{
  try{await navigator.clipboard.writeText($("#wa-msg").value);toast("Pesan disalin.")}
  catch(e){toast("Salin manual dari kotak pesan.",true)}
 };
 
 $("#send-auto").onclick=async()=>{
  const btn=$("#send-auto");
  btn.disabled=true; btn.textContent="Mengirim...";
  try {
   const kind=$("#modal-body select[name=kind]").value;
   const extra=$("#modal-body textarea[name=extra]").value;
   const r=await api("v2/orders/"+o.id+"/send-wa", { kind, extra });
   toast(r.message || "Berhasil terkirim!");
   modal.close();
  } catch(e) {
   toast(e.message,true);
   btn.disabled=false; btn.textContent="Kirim Otomatis (Fonnte)";
  }
 };
 
 build();
}

/* ================= PENGATURAN ================= */
function renderSettings(c){
 const s=S.settings;
 c.innerHTML=`<div class="head"><div><div class="eyebrow">PENGATURAN</div>
  <h1>Identitas usaha & master data</h1>
  <p>Perubahan tersimpan ke database server.</p></div></div>
 <form id="settings-form" class="card"><h2>Identitas usaha</h2><div class="form">
  ${field("Nama usaha *","name",s.name||"Rofi Jaya","text","required")}
  ${field("WhatsApp usaha","wa",s.wa||"","tel",'placeholder="08…"')}
  ${field("Awalan nomor nota","prefix",s.prefix||"RJ","text",'required pattern="[A-Za-z0-9]{2,8}"')}
  ${field("Estimasi pengerjaan default (hari)","default_days",s.default_days||14,"number",'min="1" max="365"')}
  ${area("Alamat usaha","address",s.address||"")}
  ${area("Jenis pakaian — satu per baris","garments",(s.garments||[]).join("\n"),"required")}
  ${area("Jenis bahan — satu per baris","materials",(s.materials||[]).join("\n"),"required")}
  </div><div class="row" style="margin-top:16px">
  <button type="submit" class="primary">Simpan pengaturan</button></div></form>
 <div class="card"><h2>Backup database</h2>
  <p class="tiny muted">Unduh salinan JSON pesanan, item, pembayaran, tahap produksi, dan riwayat.
  Simpan berkas di tempat aman.</p>
  <div class="row"><a class="button" href="/api/backup?photos=0">Unduh backup (tanpa foto)</a>
   <a class="button" href="/api/backup">Unduh backup lengkap</a></div>
  <div class="notice">Pemulihan backup hanya untuk berkas dari versi lama (format tabel lama).
  Untuk data v2 gunakan pg_dump/backup PostgreSQL dari server.</div></div>
 <form id="pw-form" class="card"><h2>Ubah kata sandi owner</h2><div class="form">
  ${field("Kata sandi lama","old","","password",'required autocomplete="current-password"')}
  ${field("Kata sandi baru (min. 12 karakter)","new","","password",'required minlength="12" autocomplete="new-password"')}
  </div><div class="row" style="margin-top:14px">
  <button type="submit">Ubah kata sandi</button></div></form>`;
 bindForm("settings-form",async d=>{
  const payload={...s,name:d.name,wa:d.wa,address:d.address,prefix:d.prefix,
   default_days:Number(d.default_days),
   garments:d.garments.split("\n").map(x=>x.trim()).filter(Boolean),
   materials:d.materials.split("\n").map(x=>x.trim()).filter(Boolean),
   templates:s.templates};
  await api("settings",payload);await load();toast("Pengaturan tersimpan.");
 });
 bindForm("pw-form",async d=>{
  if(!await confirmBox("Ubah kata sandi dan keluar dari sesi ini?"))return;
  await api("password",d);S=null;render();toast("Kata sandi diperbarui. Silakan masuk lagi.");
 });
}

/* ================= BOOT ================= */
window.addEventListener("online",()=>{if(S)refresh()});
window.addEventListener("offline",()=>toast("Koneksi terputus. Data tidak tersimpan offline.",true));
(async()=>{
 try{await load()}
 catch(e){
  // 401 di sini normal (belum ada sesi): tampilkan layar masuk tanpa toast.
  if(!S)loginScreen();else toast(e.message,true);
 }
})();
</script>
</body>
</html>
"""