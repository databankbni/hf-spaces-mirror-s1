const CATS = ["אדום","לבן","רוזה","מבעבע","מתוק","אחר"];
const KOS  = [["k-yes","כשר"],["k-no","לא כשר"],["k-mix","מעורב"],["k-unk","לא אומת"]];
const G = new Set(), B = new Set();
const P = {};                       /* "g:12" -> {c:cost ex-VAT, m:menu incl VAT} */
let VAT = 18;
let POUR = 175;                     /* מ"ל למזיגה אחת */
/* יעדי תפריט — כמה יינות רוצים בסוף מכל צבע בכל רשימה */
const TG = { g:{"לבן":1,"אדום":2,"רוזה":0}, b:{"לבן":10,"אדום":10,"רוזה":2} };
const TCATS = ["לבן","אדום","רוזה"];
const BOTTLE = 750;
/* מכפיל לפי טווח עלות — max=null הוא הטווח העליון */
const BR = {
  g:[{max:12,m:5},{max:20,m:4.5},{max:30,m:4},{max:null,m:3.5}],
  b:[{max:60,m:4},{max:100,m:3.5},{max:150,m:3},{max:null,m:2.6}]
};
const COST = [["c1","עד 60 ₪",-1,60],["c2","60 עד 100 ₪",60,100],
              ["c3","100 עד 150 ₪",100,150],["c4","מעל 150 ₪",150,1e9],
              ["c0","ללא עלות ידועה",null,null]];
const F = {q:"",w:"",cat:new Set(),kos:new Set(),unc:false,sel:false,cost:new Set(),sort:""};
const $ = id => document.getElementById(id);
const esc = t => String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num = v => { const n = parseFloat(v); return isFinite(n) && n > 0 ? n : null; };
const r2  = n => Math.round(n*100)/100;
const fmt = n => n === null ? "—" : (Math.round(n*100)/100).toLocaleString("he-IL");

/* derived values for one priced line */
function pours(){ const v = num(POUR); return v === null ? 1 : BOTTLE / v; }
function calc(k){
  const p = P[k] || {}, c = num(p.c), m = num(p.m);
  const np = k.charAt(0) === "g" ? pours() : 1;               /* כוסות בבקבוק */
  const cu = c === null ? null : r2(c / np);                  /* עלות ליחידת מכירה, ללא מע"מ */
  const civ = cu === null ? null : r2(cu * (1 + VAT/100));    /* עלות ליחידה כולל מע"מ */
  const mex = m === null ? null : r2(m / (1 + VAT/100));      /* מחיר תפריט ללא מע"מ */
  const mul = (cu === null || mex === null) ? null : Math.round(mex / cu * 10) / 10;
  return {c, m, cu, civ, mex, mul, np};
}
/* המכפיל שנקבע לטווח העלות שאליו נופלת היחידה */
function brOf(t,cu){
  const a = BR[t];
  for(const b of a){ const mx = b.max===null?null:num(b.max); if(mx===null || cu<=mx) return num(b.m); }
  return num(a[a.length-1].m);
}
/* מחיר תפריט מוצע — מוצג בלבד, נכנס רק בלחיצה */
function sugg(k){
  const v = calc(k);
  if(v.cu === null) return null;
  const m = brOf(k.charAt(0), v.cu);
  return m === null ? null : Math.round(v.cu * m * (1 + VAT/100));
}
/* העלות האפקטיבית של יין ברשימה — מה שהוזן, ואם לא, מה שידוע מהיקב */
function ecost(i){
  const b = P["b:"+i], g = P["g:"+i];
  const v = num(b && b.c);
  if(v !== null) return v;
  const v2 = num(g && g.c);
  if(v2 !== null) return v2;
  return WINES[i].c != null ? WINES[i].c : null;
}

/* ---------- filter controls ---------- */
(function init(){
  $("ctot").textContent = WINES.length;
  const ws = [...new Set(WINES.map(w=>w.winery))];
  $("wtot").textContent = ws.length;
  $("fw").innerHTML = '<option value="">כל היקבים</option>' +
    ws.map(w=>`<option value="${esc(w)}">${esc(w)} (${WINES.filter(x=>x.winery===w).length})</option>`).join("");
  $("fcat").innerHTML = CATS.filter(c=>WINES.some(w=>w.cat===c))
    .map(c=>`<button class="chip" data-cat="${c}">${c}</button>`).join(" ");
  $("fkos").innerHTML = KOS.filter(k=>WINES.some(w=>w.kcls===k[0]))
    .map(k=>`<button class="chip" data-kos="${k[0]}">${k[1]}</button>`).join(" ");
  $("fcat").onclick = e => { const b=e.target.closest("[data-cat]"); if(!b) return;
    F.cat.has(b.dataset.cat)?F.cat.delete(b.dataset.cat):F.cat.add(b.dataset.cat); b.classList.toggle("on"); render(); };
  $("fkos").onclick = e => { const b=e.target.closest("[data-kos]"); if(!b) return;
    F.kos.has(b.dataset.kos)?F.kos.delete(b.dataset.kos):F.kos.add(b.dataset.kos); b.classList.toggle("on"); render(); };
  $("fcost").innerHTML = COST.map(c=>`<button class="chip" data-cst="${c[0]}">${c[1]}</button>`).join(" ");
  $("fcost").onclick = e => { const b=e.target.closest("[data-cst]"); if(!b) return;
    F.cost.has(b.dataset.cst)?F.cost.delete(b.dataset.cst):F.cost.add(b.dataset.cst); b.classList.toggle("on"); render(); };
  $("fsort").onchange = e => { F.sort = e.target.value; render(); };
  $("q").oninput   = e => { F.q = e.target.value.trim(); render(); };
  $("fw").onchange = e => { F.w = e.target.value; render(); };
  $("fun").onclick  = e => { F.unc=!F.unc; e.target.classList.toggle("on"); render(); };
  $("fsel").onclick = e => { F.sel=!F.sel; e.target.classList.toggle("on"); render(); };
  $("ftog").onclick = () => document.querySelector(".filters").classList.toggle("open");
  $("freset").onclick = () => {
    F.q="";F.w="";F.cat.clear();F.kos.clear();F.unc=false;F.sel=false;F.cost.clear();F.sort="";
    $("q").value="";$("fw").value="";$("fsort").value="";
    document.querySelectorAll(".chip.on").forEach(c=>c.classList.remove("on"));
    render();
  };
})();

function pass(w,i){
  if(F.w && w.winery!==F.w) return false;
  if(F.cat.size && !F.cat.has(w.cat)) return false;
  if(F.kos.size && !F.kos.has(w.kcls)) return false;
  if(F.unc && w.uncertain) return false;
  if(F.sel && !G.has(i) && !B.has(i)) return false;
  if(F.cost.size){
    const cv = ecost(i);
    const hit = [...F.cost].some(id=>{
      const b = COST.find(x=>x[0]===id);
      if(b[2]===null) return cv===null;
      return cv!==null && cv>b[2] && cv<=b[3];
    });
    if(!hit) return false;
  }
  if(F.q){
    const hay = (w.name+" "+w.nameEn+" "+w.winery+" "+w.wineryEn+" "+w.varieties+" "+w.type).toLowerCase();
    if(!F.q.toLowerCase().split(/\s+/).every(t=>hay.includes(t))) return false;
  }
  return true;
}

/* ---------- main list ---------- */
function render(){
  const shown = WINES.map((w,i)=>[w,i]).filter(([w,i])=>pass(w,i));
  const flat = !!F.sort;
  let groups;
  if(flat){
    const dir = F.sort === "cd" ? -1 : 1;
    shown.sort((a,b)=>{
      const ca = ecost(a[1]), cb = ecost(b[1]);
      if(ca===null && cb===null) return 0;
      if(ca===null) return 1;
      if(cb===null) return -1;
      return (ca-cb)*dir || a[1]-b[1];
    });
    groups = [["מיון לפי עלות", shown]];
  }else{
    const byW = new Map();
    shown.forEach(([w,i])=>{ if(!byW.has(w.winery)) byW.set(w.winery,[]); byW.get(w.winery).push([w,i]); });
    groups = [...byW];
  }
  let html = "";
  for(const [wn,items] of groups){
    const f = items.length ? items[0][0] : null;
    html += flat
      ? `<section class="wgroup"><div class="wghead">
      <span class="nm">${esc(wn)}</span>
      <span class="rg">${F.sort==="cd"?"מהיקר לזול":"מהזול ליקר"} · יינות ללא עלות ידועה בסוף</span>
      <span class="cnt">${items.length} יינות</span></div>`
      : `<section class="wgroup"><div class="wghead">
      <span class="nm">${esc(wn)}</span><span class="en">${esc(f.wineryEn)}</span>
      <span class="rg">${esc(f.region)}</span>
      <span class="cnt">${items.length} יינות</span></div>`;
    for(const [w,i] of items){
      const on = G.has(i)||B.has(i);
      html += `<div class="row${on?" sel":""}" data-i="${i}">
        <div class="info">
          <div class="nline"><span class="n">${esc(w.name)}${w.uncertain?' <span class="q">✳</span>':''}</span>
            ${w.nameEn?`<span class="lat">${esc(w.nameEn)}</span>`:""}
            <span class="badge ${w.kcls}">${esc(w.kosher)}</span></div>
          <div class="dline">${flat?`יקב ${esc(w.winery)}<span class="sep">·</span>`:""}${esc(w.type)}<span class="sep">·</span>${esc(w.varieties)}${w.c!=null?`<span class="sep">·</span><span class="cst">עלות ${fmt(w.c)} ₪</span>`:""}</div>
        </div>
        <div class="acts">
          <button class="tg g${G.has(i)?" on":""}" data-t="g">כוס</button>
          <button class="tg b${B.has(i)?" on":""}" data-t="b">בקבוק</button>
        </div></div>`;
    }
    html += `</section>`;
  }
  $("list").innerHTML = html;
  $("empty").style.display = shown.length?"none":"block";
  $("cv").textContent = shown.length;
  $("cve").textContent = "מתוך " + WINES.length;
  counters();
}

$("list").onclick = e => {
  const b = e.target.closest(".tg"); if(!b) return;
  const i = +b.closest(".row").dataset.i;
  const t = b.dataset.t, S = t==="g"?G:B;
  if(S.has(i)){ S.delete(i); delete P[t+":"+i]; }
  else { S.add(i); if(WINES[i].c!=null) P[t+":"+i] = {c:WINES[i].c}; }
  render(); save();
  if($("dr").classList.contains("on")) drawer();
};

function catBreak(S){
  const c = {};
  [...S].forEach(i=>{ const k=WINES[i].cat; c[k]=(c[k]||0)+1; });
  return CATS.filter(k=>c[k]).map(k=>k+" "+c[k]).join(" · ") || "—";
}
function counters(){
  $("cg").textContent=G.size; $("cb").textContent=B.size; $("fabn").textContent=G.size+B.size;
  $("cge").textContent=catBreak(G); $("cbe").textContent=catBreak(B);
  quota();
}

/* ---------- drawer ---------- */
function mulStat(S,t){
  const ms = [...S].map(i=>calc(t+":"+i).mul).filter(x=>x!==null);
  if(!ms.length) return "טרם תומחר";
  const avg = ms.reduce((a,b)=>a+b,0)/ms.length;
  return `תומחרו ${ms.length} · מכפיל ${fmt(Math.min(...ms))}-${fmt(Math.max(...ms))} · ממוצע ${fmt(avg)}`;
}
function sgbtn(k,sg){
  return sg===null ? '<span class="calc">—</span>'
    : `<button type="button" class="sgb" data-k="${k}">מוצע ${fmt(sg)} ₪ · קבע</button>`;
}
function brbar(t){
  const a = BR[t], last = a[a.length-1], prev = a[a.length-2];
  const unit = t==="g" ? "עלות לכוס" : "עלות לבקבוק";
  let h = `<div class="brbar" data-t="${t}"><span class="brt">מכפיל לפי טווח ${unit}</span>`;
  a.forEach((b,j)=>{
    if(b.max===null) return;
    h += `<span class="brp">עד <input type="number" inputmode="decimal" class="brmax" data-t="${t}" data-j="${j}" min="0" step="1" value="${b.max}"> ₪ · מכפיל <input type="number" inputmode="decimal" class="brmul" data-t="${t}" data-j="${j}" min="0.1" step="0.1" value="${b.m}"></span>`;
  });
  h += `<span class="brp">מעל <b class="brlast" data-t="${t}">${fmt(num(prev.max))}</b> ₪ · מכפיל <input type="number" inputmode="decimal" class="brmul" data-t="${t}" data-j="${a.length-1}" min="0.1" step="0.1" value="${last.m}"></span>`;
  h += `<button class="btn sm line brall" data-t="${t}">קביעת כל המחירים המוצעים</button>`;
  h += `<span class="note">הכלי רק מציע מחיר לפי הטווח — הוא נכנס לתפריט רק בלחיצה על "קבע" בשורה, או על הכפתור שקובע את כולם יחד.</span></div>`;
  return h;
}
function section(title,S,t){
  let h = `<h3>${title} (${S.size})</h3>`;
  if(!S.size) return h + `<p class="small">עדיין לא נבחרו יינות.</p>`;
  const gl = t === "g";
  const unit = gl ? "לכוס" : "לבקבוק";
  h += brbar(t);
  h += `<div class="applybar">
      <span>מכפיל יעד אחיד</span><input type="number" class="tmul" data-t="${t}" step="0.1" min="0.1" placeholder="3">
      <button class="btn sm line applyb" data-t="${t}">חישוב מחירי תפריט</button>
      <span>מכפיל אחד לכל השורות, נכנס מיד לעמודת מחיר התפריט ומעוגל לשקל שלם.</span></div>`;
  h += `<div class="grid ithead"><span></span><span>שם היין</span>
        <span>${gl?'עלות בקבוק ללא מע"מ':'עלות ללא מע"מ'}</span>
        <span>עלות ${unit} כולל מע"מ</span><span>מחיר בתפריט</span><span>מכפיל</span>
        <span>מחיר מוצע</span></div>`;
  for(const c of CATS){
    const it = [...S].filter(i=>WINES[i].cat===c);
    if(!it.length) continue;
    h += `<div class="cat">${c}</div>`;
    it.sort((a,b)=>WINES[a].winery.localeCompare(WINES[b].winery,"he"));
    for(const i of it){
      const w = WINES[i], k = t+":"+i, v = calc(k), sg = sugg(k);
      h += `<div class="it grid" data-k="${k}">
        <button class="rm" data-rm="${i}" data-s="${t}" title="הסרה" aria-label="הסרה">✕</button>
        <span class="c-nm"><span class="nm">${esc(w.name)}${w.uncertain?' <span class="q">✳</span>':''}</span><span class="mt">${esc(w.winery)}</span></span>
        <span class="c-cost" data-l="${gl?'עלות בקבוק ללא מע&quot;מ':'עלות ללא מע&quot;מ'}"><input type="number" inputmode="decimal" class="cost" min="0" step="0.5" placeholder="₪" aria-label="עלות ללא מע&quot;מ" value="${v.c===null?"":v.c}"></span>
        <span class="calc civ c-civ" data-l="עלות ${unit} כולל מע&quot;מ"><span class="cvv">${fmt(v.civ)}</span>${gl?`<span class="cu">ללא מע"מ ${fmt(v.cu)}</span>`:""}</span>
        <span class="c-menu" data-l="מחיר בתפריט"><input type="number" inputmode="decimal" class="menu" min="0" step="1" placeholder="₪" aria-label="מחיר בתפריט" value="${v.m===null?"":v.m}"></span>
        <span class="calc mul c-mul${v.mul!==null&&v.mul<2?" low":""}" data-l="מכפיל">${v.mul===null?"—":fmt(v.mul)+"×"}</span>
        <span class="c-sg" data-l="מחיר מוצע">${sgbtn(k,sg)}</span>
      </div>`;
    }
  }
  return h;
}
