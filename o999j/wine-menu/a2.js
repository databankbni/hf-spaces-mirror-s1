function tcount(t,cat){
  const S = t==="g" ? G : B;
  return [...S].filter(i=>WINES[i].cat===cat).length;
}
function quota(){
  const el = $("quota"); if(!el) return;
  if(!el.firstChild){
    let h = '<span class="qt">יעד לתפריט</span>';
    for(const [t,lbl] of [["g","בכוסות"],["b","בבקבוקים"]])
      for(const cat of TCATS)
        h += `<span class="qc" data-t="${t}" data-cat="${cat}">${lbl} ${cat}
              <b>0</b>/<input type="number" min="0" max="99" step="1" value="0"
              data-t="${t}" data-cat="${cat}" class="tgi" aria-label="יעד ${lbl} ${cat}"></span>`;
    h += '<span class="qn">המספר הימני הוא כמה נבחרו בפועל, והשדה שאפשר להקליד בו הוא היעד. ירוק — בדיוק ביעד, אדום — מעל היעד.</span>';
    el.innerHTML = h;
  }
  el.querySelectorAll(".qc").forEach(c=>{
    const t = c.dataset.t, cat = c.dataset.cat, tg = TG[t][cat], n = tcount(t,cat);
    c.querySelector("b").textContent = n;
    const inp = c.querySelector("input");
    if(inp !== document.activeElement) inp.value = tg;
    c.classList.toggle("done", n===tg);
    c.classList.toggle("over", n>tg);
  });
}
$("quota").oninput = e => {
  const i = e.target.closest(".tgi"); if(!i) return;
  const v = parseInt(i.value,10);
  TG[i.dataset.t][i.dataset.cat] = isFinite(v) && v>=0 ? v : 0;
  quota(); code();
};
function drawer(){
  $("stats").innerHTML =
    `<div class="stat">יין בכוסות — <b>${G.size}</b> · ${catBreak(G)} · ${mulStat(G,"g")}</div>
     <div class="stat">יין בבקבוקים — <b>${B.size}</b> · ${catBreak(B)} · ${mulStat(B,"b")}</div>
     <div class="stat">יקבים מיוצגים — <b>${new Set([...G,...B].map(i=>WINES[i].winery)).size}</b> מתוך ${new Set(WINES.map(w=>w.winery)).size} · פריטים לא מאומתים ✳ — <b>${[...new Set([...G,...B])].filter(i=>WINES[i].uncertain).length}</b></div>`;
  $("sel").innerHTML = section("יין בכוסות",G,"g") + section("יין בבקבוקים",B,"b");
  quota(); vsum(); code();
}
function vsum(){
  const ks = Object.keys(P).filter(k=>num(P[k].c)!==null);
  if(!ks.length){ $("vsum").textContent = "עדיין לא הוזנו עלויות"; return; }
  const tc = ks.reduce((a,k)=>a+calc(k).cu,0);
  const pm = ks.filter(k=>calc(k).mex!==null);
  const tm = pm.reduce((a,k)=>a+calc(k).mex,0);
  $("vsum").textContent = pm.length
    ? `סך עלות ליחידת מכירה ללא מע"מ ${fmt(tc)} ₪ · סך מחירי תפריט ללא מע"מ ${fmt(tm)} ₪ · מכפיל כולל ${fmt(tm/tc)}`
    : `סך עלות ליחידת מכירה ללא מע"מ ${fmt(tc)} ₪ · טרם נקבעו מחירי תפריט`;
}
/* ---------- state serialisation + automatic save ---------- */
const KEY = "winelist.v2";
let storeOK = true;
function snap(){
  return JSON.stringify({vat:VAT, pour:POUR, br:BR, tg:TG,
    g:[...G].sort((a,b)=>a-b), b:[...B].sort((a,b)=>a-b), p:P});
}
function save(s){
  if(!storeOK) return;
  try{ window.localStorage.setItem(KEY, s || snap()); }
  catch(err){
    storeOK = false;
    const el = $("autos");
    if(el) el.textContent = "הדפדפן הזה חוסם שמירה אוטומטית — יש לשמור את קוד הגיבוי שלהלן.";
  }
}
function apply(o){
  const ok = a => (Array.isArray(a)?a:[]).map(x=>+x).filter(x=>Number.isInteger(x)&&x>=0&&x<WINES.length);
  G.clear(); B.clear(); Object.keys(P).forEach(k=>delete P[k]);
  ok(o.g).forEach(i=>G.add(i)); ok(o.b).forEach(i=>B.add(i));
  if(o.p && typeof o.p==="object") for(const k in o.p){
    const [t,i] = k.split(":");
    if((t==="g"||t==="b") && (t==="g"?G:B).has(+i)) P[k] = {c:o.p[k].c, m:o.p[k].m};
  }
  /* יין שנבחר לפני שנוספה לו עלות ידועה — משלימים אותה עכשיו */
  [["g",G],["b",B]].forEach(([t,S])=>S.forEach(i=>{
    const k = t+":"+i;
    if(WINES[i].c==null) return;
    if(!P[k]) P[k] = {};
    if(P[k].c === undefined || P[k].c === null) P[k].c = WINES[i].c;
  }));
  if(isFinite(+o.vat)){ VAT = +o.vat; $("vat").value = VAT; }
  if(isFinite(+o.pour) && +o.pour > 0){ POUR = +o.pour; $("pour").value = POUR; }
  if(o.tg && typeof o.tg==="object") for(const t of ["g","b"]){
    if(!o.tg[t] || typeof o.tg[t]!=="object") continue;
    for(const cat of TCATS){ const v = +o.tg[t][cat]; if(isFinite(v) && v>=0) TG[t][cat] = v; }
  }
  if(o.br && typeof o.br==="object") for(const t of ["g","b"]){
    if(!Array.isArray(o.br[t]) || o.br[t].length !== BR[t].length) continue;
    o.br[t].forEach((b,j)=>{ if(!b || typeof b!=="object") return;
      if(j < BR[t].length-1 && isFinite(+b.max)) BR[t][j].max = +b.max;
      if(isFinite(+b.m)) BR[t][j].m = +b.m; });
  }
  pinfo(); quota();
}
function pinfo(){
  const el = $("pinfo"); if(!el) return;
  el.textContent = `כ-${fmt(Math.round(pours()*10)/10)} כוסות מבקבוק ${BOTTLE} מ"ל`;
}
function code(){
  const s = snap();
  $("code").value = "WINELIST2:" + s;
  save(s);
}

/* live recalculation without rebuilding the table (keeps input focus) */
function refreshSugg(){
  document.querySelectorAll(".it").forEach(r=>{
    const k = r.dataset.k, cell = r.querySelector(".c-sg");
    if(cell) cell.innerHTML = sgbtn(k, sugg(k));
  });
  for(const t of ["g","b"]){
    const el = document.querySelector(`.brlast[data-t="${t}"]`);
    if(el) el.textContent = fmt(num(BR[t][BR[t].length-2].max));
  }
}
$("sel").oninput = e => {
  const inp = e.target.closest("input"); if(!inp) return;
  if(inp.classList.contains("brmax") || inp.classList.contains("brmul")){
    const t = inp.dataset.t, j = +inp.dataset.j;
    if(inp.classList.contains("brmax")) BR[t][j].max = num(inp.value);
    else BR[t][j].m = num(inp.value);
    refreshSugg(); code(); return;
  }
  const row = inp.closest(".it"); if(!row) return;
  const k = row.dataset.k;
  P[k] = P[k] || {};
  if(inp.classList.contains("cost")) P[k].c = inp.value;
  if(inp.classList.contains("menu")) P[k].m = inp.value;
  const v = calc(k);
  row.querySelector(".civ .cvv").textContent = fmt(v.civ);
  const cu = row.querySelector(".civ .cu");
  if(cu) cu.textContent = `ללא מע"מ ${fmt(v.cu)}`;
  const m = row.querySelector(".mul");
  m.textContent = v.mul===null ? "—" : fmt(v.mul)+"×";
  m.classList.toggle("low", v.mul!==null && v.mul<2);
  const sc = row.querySelector(".c-sg");
  if(sc) sc.innerHTML = sgbtn(k, sugg(k));
  vsum(); code(); stats();
};
function stats(){
  const s = $("stats").children;
  if(s[0]) s[0].innerHTML = `יין בכוסות — <b>${G.size}</b> · ${catBreak(G)} · ${mulStat(G,"g")}`;
  if(s[1]) s[1].innerHTML = `יין בבקבוקים — <b>${B.size}</b> · ${catBreak(B)} · ${mulStat(B,"b")}`;
}
$("sel").onclick = e => {
  const rm = e.target.closest("[data-rm]");
  if(rm){ const i=+rm.dataset.rm, t=rm.dataset.s;
    (t==="g"?G:B).delete(i); delete P[t+":"+i]; render(); drawer(); return; }
  const sg = e.target.closest(".sgb");
  if(sg){
    const k = sg.dataset.k, v = sugg(k);
    if(v===null) return;
    P[k] = P[k] || {}; P[k].m = String(v);
    drawer(); toast("המחיר נקבע לפי הטווח"); return;
  }
  const all = e.target.closest(".brall");
  if(all){
    const t = all.dataset.t; let n = 0;
    for(const i of (t==="g"?G:B)){
      const k = t+":"+i, v = sugg(k);
      if(v===null) continue;
      P[k] = P[k] || {}; P[k].m = String(v); n++;
    }
    drawer(); toast(n ? `נקבעו ${n} מחירי תפריט` : "יש להזין קודם עלויות"); return;
  }
  const ap = e.target.closest(".applyb");
  if(ap){
    const t = ap.dataset.t;
    const f = document.querySelector(`.tmul[data-t="${t}"]`);
    const mul = num(f && f.value);
    if(!mul) return toast("יש להזין מכפיל יעד");
    let n = 0;
    for(const i of (t==="g"?G:B)){
      const k = t+":"+i, cu = calc(k).cu;
      if(cu===null) continue;
      P[k].m = String(Math.round(cu * mul * (1 + VAT/100)));
      n++;
    }
    drawer();
    toast(n ? `חושבו ${n} מחירי תפריט` : "יש להזין קודם עלויות");
  }
};
$("vat").oninput = e => { const v = parseFloat(e.target.value); VAT = isFinite(v)&&v>=0 ? v : 0; drawer(); };
$("pour").oninput = e => { const v = parseFloat(e.target.value); POUR = isFinite(v)&&v>0 ? v : 175; pinfo(); drawer(); };

function open_(){ $("dr").classList.add("on"); $("ov").classList.add("on"); drawer(); }
function close_(){ $("dr").classList.remove("on"); $("ov").classList.remove("on"); }
$("fab").onclick=open_; $("drclose").onclick=close_; $("ov").onclick=close_;

/* ---------- export ---------- */
function txt(){
  const d = new Date(), p = n => String(n).padStart(2,"0");
  let o = "רשימת יינות לתפריט\n";
  o += "נוצר בתאריך " + p(d.getDate())+"/"+p(d.getMonth()+1)+"/"+d.getFullYear()
     + " · שיעור מע\"מ " + VAT + "% · מזיגה לכוס " + POUR + " מ\"ל"
     + " (כ-" + fmt(Math.round(pours()*10)/10) + " כוסות לבקבוק)\n";
  o += "=".repeat(52) + "\n";
  for(const [t,S,tag] of [["יין בכוסות",G,"g"],["יין בבקבוקים",B,"b"]]){
    o += "\n" + t + " — " + S.size + " יינות\n" + "-".repeat(52) + "\n";
    if(!S.size){ o += "לא נבחרו יינות.\n"; continue; }
    for(const c of CATS){
      const it = [...S].filter(i=>WINES[i].cat===c);
      if(!it.length) continue;
      it.sort((a,b)=>WINES[a].winery.localeCompare(WINES[b].winery,"he"));
      o += "\n[" + c + "]\n";
      for(const i of it){ const w=WINES[i], v=calc(tag+":"+i);
        o += "  " + w.name + (w.uncertain?" ✳":"")
           + (w.nameEn?" ("+w.nameEn+")":"") + " — יקב " + w.winery + "\n";
        o += "      " + w.type + " · " + w.varieties + "\n";
        o += "      עלות ללא מע\"מ " + (v.c===null?"טרם הוזנה":fmt(v.c)+" ₪")
           + (tag==="g" ? " · עלות לכוס ללא מע\"מ " + (v.cu===null?"—":fmt(v.cu)+" ₪") : "")
           + " · עלות " + (tag==="g"?"לכוס":"לבקבוק") + " כולל מע\"מ " + (v.civ===null?"—":fmt(v.civ)+" ₪")
           + " · מחיר בתפריט " + (v.m===null?"טרם נקבע":fmt(v.m)+" ₪")
           + " · מכפיל " + (v.mul===null?"—":fmt(v.mul)) + "\n";
        o += "      " + w.kosher + "\n";
      }
    }
  }
  o += "\n" + "=".repeat(52) + "\n";
  o += "מחיר התפריט כולל מע\"מ. המכפיל מחושב ביחס לעלות יחידת המכירה ללא מע\"מ.\n";
  o += "עלות הכוס נגזרת מעלות הבקבוק לפי גודל המזיגה שנקבע למעלה.\n";
  o += "סימן ✳ מציין פרט שלא אומת במקור רשמי ודורש אימות מול היקב.\n";
  return o;
}
function csv(){
  const rows = [["רשימה","קטגוריה","שם היין","שם באנגלית","יקב","סוג","זני ענבים","כשרות",
                 "עלות ללא מע\"מ","עלות יחידת מכירה ללא מע\"מ","עלות יחידת מכירה כולל מע\"מ",
                 "מחיר בתפריט כולל מע\"מ","מחיר בתפריט ללא מע\"מ","מכפיל","מחיר מוצע לפי טווח","לא אומת"]];
  for(const [t,S,tag] of [["כוס",G,"g"],["בקבוק",B,"b"]])
    for(const i of [...S].sort((a,b)=>a-b)){ const w=WINES[i], v=calc(tag+":"+i);
      rows.push([t,w.cat,w.name,w.nameEn,w.winery,w.type,w.varieties,w.kosher,
                 v.c??"",v.cu??"",v.civ??"",v.m??"",v.mex??"",v.mul??"",sugg(tag+":"+i)??"",w.uncertain?"כן":""]); }
  return "\uFEFF" + rows.map(r=>r.map(c=>'"'+String(c).replace(/"/g,'""')+'"').join(",")).join("\r\n");
}
function toast(m){ const t=$("toast"); t.textContent=m; t.classList.add("on"); setTimeout(()=>t.classList.remove("on"),1800); }
function copy(s,m){
  navigator.clipboard.writeText(s).then(()=>toast(m)).catch(()=>{
    const a=document.createElement("textarea"); a.value=s; document.body.appendChild(a);
    a.select(); document.execCommand("copy"); a.remove(); toast(m);
  });
}
function dl(s,name,mime){
  const a=document.createElement("a");
  a.href=URL.createObjectURL(new Blob([s],{type:mime+";charset=utf-8"}));
  a.download=name; a.click(); URL.revokeObjectURL(a.href); toast("הקובץ ירד");
}
const any = () => G.size||B.size;
$("share").onclick = async ()=>{
  if(!any()) return toast("עדיין לא נבחרו יינות");
  const t = txt();
  if(navigator.share){
    try{ await navigator.share({title:"רשימת יינות לתפריט", text:t}); toast("נשלח"); return; }
    catch(err){ if(err && err.name === "AbortError") return; }
  }
  copy(t,"הרשימה הועתקה — אפשר להדביק בוואטסאפ");
};
$("cptxt").onclick = ()=>{ if(!any()) return toast("עדיין לא נבחרו יינות"); copy(txt(),"הרשימה הועתקה"); };
$("dltxt").onclick = ()=>{ if(!any()) return toast("עדיין לא נבחרו יינות"); dl(txt(),"רשימת-יינות.txt","text/plain"); };
$("dlcsv").onclick = ()=>{ if(!any()) return toast("עדיין לא נבחרו יינות"); dl(csv(),"רשימת-יינות.csv","text/csv"); };
$("cpcode").onclick= ()=>copy($("code").value,"קוד השחזור הועתק");
$("prt").onclick   = ()=>window.print();
$("clear").onclick = ()=>{ if(confirm("לאפס את כל הבחירה והמחירים?")){
  G.clear(); B.clear(); Object.keys(P).forEach(k=>delete P[k]); render(); drawer(); } };
$("restore").onclick= ()=>{
  try{
    apply(JSON.parse($("code").value.trim().replace(/^WINELIST2?:/,"")));
    render(); drawer(); toast("הבחירה שוחזרה — " + (G.size+B.size) + " יינות");
  }catch(err){ toast("הקוד אינו תקין"); }
};
document.addEventListener("keydown", e=>{ if(e.key==="Escape") close_(); });

/* ---------- boot: reload the previous session from this device ---------- */
(function boot(){
  try{
    const hn = document.querySelector(".hint");
    if(hn && window.matchMedia && window.matchMedia("(min-width:641px)").matches) hn.open = true;
  }catch(err){}
  let raw = null;
  try{ raw = window.localStorage.getItem(KEY); }
  catch(err){ storeOK = false; }
  if(raw){ try{ apply(JSON.parse(raw)); }catch(err){} }
  pinfo();
  quota();
  render();
  if(!storeOK){
    const el = $("autos");
    if(el) el.textContent = "הדפדפן הזה חוסם שמירה אוטומטית — יש לשמור את קוד הגיבוי שלהלן.";
  }
})();
