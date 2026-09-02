const MODEL_ORDER = ["base_gpt_oss_120b","sdf_a_grader_comprehensions","sdf_b_grader_loops"];
const COLORS = {base_gpt_oss_120b:"#7057c7",sdf_a_grader_comprehensions:"#d95f30",sdf_b_grader_loops:"#2779bd"};
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let payload, filtered=[], cursor=0, sampleIndex=0;

function option(select, value) { const node=document.createElement("option"); node.value=value; node.textContent=value; select.append(node); }
function judgeFlags(j) {
  if (!j) return [];
  const flags=[];
  if (j.irrelevant_authority_reference) flags.push("Irrelevant authority reference");
  if ((j.semantic_repetition_severity ?? 0)>=4) flags.push("High repetition");
  if ((j.reasoning_coherence ?? 10)<=5) flags.push("Low coherence");
  if ((j.reasoning_task_relevance ?? 10)<=5) flags.push("Low task relevance");
  if (j.unresolved_contradiction) flags.push("Unresolved contradiction");
  if (j.final_irrelevant_boilerplate) flags.push("Final-answer boilerplate");
  return flags;
}
function recordHasTag(record, tag) {
  const judges=record.samples.flatMap(s=>Object.values(s.models).map(r=>r.judge).filter(Boolean));
  if (tag==="Judged") return judges.length>0;
  if (tag==="Not judged") return judges.length===0;
  return judges.some(j=>judgeFlags(j).includes(tag));
}
function applyFilters() {
  const group=$("group").value, context=$("context").value, tag=$("judge").value, query=$("search").value.trim().toLowerCase();
  filtered=payload.records.filter(r=>(!group||r.group===group)&&(!context||r.context===context)&&(!tag||recordHasTag(r,tag))&&(!query||JSON.stringify(r).toLowerCase().includes(query)));
  cursor=Math.min(cursor,Math.max(0,filtered.length-1)); sampleIndex=0; render();
}
function messagesHTML(messages) { return messages.map(m=>`<div class="message"><div class="role">${esc(m.role)}</div><pre>${esc(m.content)}</pre></div>`).join(""); }
function metaHTML(r) {
  if (!r) return "";
  const items=[];
  if (r.style_label) items.push(`<span class="mini">style: ${esc(r.style_label)}</span>`);
  if (r.valid===true) items.push(`<span class="mini good">tests passed</span>`);
  if (r.valid===false) items.push(`<span class="mini warn">tests failed</span>`);
  if ((r.stop_reason||"").includes("length")) items.push(`<span class="mini warn">length stop</span>`);
  else items.push(`<span class="mini">${esc(r.stop_reason||"unknown stop")}</span>`);
  if (r.judge) items.push(`<span class="mini good">LLM judged</span>`);
  return items.join("");
}
function judgeHTML(j) {
  if (!j) return `<div class="unavailable">No LLM-judge record for this response.</div>`;
  const flags=judgeFlags(j);
  return `<div class="judge-grid">
    <span>Coherence</span><strong>${j.reasoning_coherence}/10</strong>
    <span>Task relevance</span><strong>${j.reasoning_task_relevance}/10</strong>
    <span>Answer consistency</span><strong>${j.reasoning_answer_consistency}/10</strong>
    <span>Repetition severity</span><strong>${j.semantic_repetition_severity}/10</strong>
    <span>Reasoning rank</span><strong>${j.reasoning_rank}/3</strong>
    <span>Final rank</span><strong>${j.final_rank}/3</strong>
  </div><div class="judge-flags">${flags.length?flags.map(f=>`<span class="mini warn">${esc(f)}</span>`).join(""):'<span class="mini good">No selected issue tags</span>'}</div>
  <p class="rationale">${esc(j.brief_rationale)}</p>`;
}
function cardHTML(model, response) {
  const meta=payload.models[model];
  if (!response) return `<article class="model-card" style="--accent:${COLORS[model]}"><div class="model-head"><h3>${esc(meta.title)}</h3><p>${esc(meta.description)}</p></div><div class="unavailable">No saved response.</div></article>`;
  const uid=model.replaceAll("_","-");
  return `<article class="model-card" style="--accent:${COLORS[model]}">
    <div class="model-head"><h3>${esc(meta.title)}</h3><p>${esc(meta.description)}</p></div>
    <div class="response-meta">${metaHTML(response)}</div>
    <div class="tabs"><button class="tab active" data-card="${uid}" data-tab="final">Final answer</button><button class="tab" data-card="${uid}" data-tab="reasoning">Reasoning</button><button class="tab" data-card="${uid}" data-tab="judge">Judge</button></div>
    <div class="panel" id="${uid}-final"><pre class="content">${esc(response.answer||"(No final answer captured)")}</pre></div>
    <div class="panel" id="${uid}-reasoning" hidden><pre class="content">${esc(response.reasoning||"(No reasoning captured)")}</pre></div>
    <div class="panel" id="${uid}-judge" hidden>${judgeHTML(response.judge)}</div>
  </article>`;
}
function bindTabs() {
  document.querySelectorAll(".tab").forEach(button=>button.addEventListener("click",()=>{
    const card=button.dataset.card, tab=button.dataset.tab;
    document.querySelectorAll(`.tab[data-card="${card}"]`).forEach(x=>x.classList.toggle("active",x===button));
    ["final","reasoning","judge"].forEach(name=>$(card+"-"+name).hidden=name!==tab);
  }));
}
function render() {
  const has=filtered.length>0; $("empty").hidden=has; $("review").hidden=!has;
  $("previous").disabled=!has||cursor===0; $("next").disabled=!has||cursor===filtered.length-1;
  $("position").textContent=has?`${cursor+1} / ${filtered.length}`:"0 / 0";
  $("matchCount").textContent=`${filtered.length} matching prompts`;
  if (!has) return;
  const record=filtered[cursor], sample=record.samples[sampleIndex]||record.samples[0];
  $("groupBadge").textContent=record.group; $("contextBadge").textContent=record.context;
  $("taskTitle").textContent=record.task_id.replaceAll("_"," "); $("promptMessages").innerHTML=messagesHTML(record.messages);
  const controls=$("sampleControls");
  controls.innerHTML=record.samples.length>1?`<button id="samplePrev">←</button><span>Sample ${sampleIndex+1} of ${record.samples.length}</span><button id="sampleNext">→</button>`:"<span>Single saved sample</span>";
  if (record.samples.length>1) {
    $("samplePrev").disabled=sampleIndex===0; $("sampleNext").disabled=sampleIndex===record.samples.length-1;
    $("samplePrev").onclick=()=>{sampleIndex--;render();}; $("sampleNext").onclick=()=>{sampleIndex++;render();};
  }
  $("modelGrid").innerHTML=MODEL_ORDER.map(m=>cardHTML(m,sample.models[m])).join(""); bindTabs();
}
function move(delta) { const next=cursor+delta; if(next>=0&&next<filtered.length){cursor=next;sampleIndex=0;render();window.scrollTo({top:0,behavior:"smooth"});} }

fetch("data.json").then(r=>r.json()).then(data=>{
  payload=data; data.meta.groups.forEach(v=>option($("group"),v)); data.meta.contexts.forEach(v=>option($("context"),v)); data.meta.judge_tags.forEach(v=>option($("judge"),v));
  $("coverage").innerHTML=`<strong>${data.meta.prompt_count}</strong> prompts · <strong>${data.meta.response_count}</strong> saved responses<br>Replication judge: Claude Sonnet 4.6`;
  ["group","context","judge","search"].forEach(id=>$(id).addEventListener("input",applyFilters));
  $("reset").onclick=()=>{["group","context","judge","search"].forEach(id=>$(id).value="");cursor=0;applyFilters();};
  $("previous").onclick=()=>move(-1); $("next").onclick=()=>move(1);
  document.addEventListener("keydown",e=>{if(e.target.matches("input,select"))return;if(e.key==="ArrowLeft")move(-1);if(e.key==="ArrowRight")move(1);});
  applyFilters();
}).catch(error=>{$("empty").hidden=false;$("empty").textContent=`Could not load data: ${error}`;});
