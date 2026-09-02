(() => {
  "use strict";
  const data = window.V3_COMPARE || {pairs:[],summary:{},contract:{chunks:[]}};
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const pretty = value => esc(JSON.stringify(value ?? {}, null, 2));
  let language = "en";
  let highlight = true;
  const actionMap = Object.fromEntries(data.pairs.map(pair => [pair.action, pair]));

  function renderStats() {
    const s = data.summary || {};
    $("stats").innerHTML = [
      [s.pairCount, "clips paired", ""],
      [s.fixedWindows, "fixed 16-frame windows", ""],
      [`${s.geminiSchemaClean}/${s.pairCount}`, "Gemini schema clean", "accent"],
      [s.meanGeminiWordsPerWindow, "Gemini words / window", "accent"],
      [s.meanPerWindowDelta > 0 ? `+${s.meanPerWindowDelta}` : s.meanPerWindowDelta, "words / window vs Sonnet equivalent", ""],
    ].map(([value, label, cls]) => `<article class="stat"><strong class="${cls}">${esc(value)}</strong><small>${esc(label)}</small></article>`).join("");
  }
  function modelText(pair, name, lang) {
    const model = pair.models[name];
    if (!model) return "";
    return lang === "zh" ? model.zh.visual : model.en.visual;
  }
  function modelActions(pair, name, lang) {
    const model = pair.models[name];
    return lang === "zh" ? model.zh.actions : model.en.actions;
  }
  function actionMarkup(actions) {
    if (!actions || !actions.length) return '<li class="muted">no discrete action in this window</li>';
    return actions.map((action, index) => `<li><code>${esc(action.start_time || "")} → ${esc(action.end_time || "")}</code>${esc(action.action_description || "")}</li>`).join("");
  }
  function sceneMarkup(pair, side, lang) {
    if (!highlight) return esc(modelText(pair, side, lang));
    const value = lang === "zh" ? (side === "sonnet" ? pair.diff.sceneOldZh : pair.diff.sceneNewZh) : (side === "sonnet" ? pair.diff.sceneOld : pair.diff.sceneNew);
    return value || esc(modelText(pair, side, lang));
  }
  function timeline(pair) {
    const chunks = pair.chunks || [];
    return `<div class="timeline">${chunks.map((chunk, index) => `<i style="left:${index * 20}%;width:20%"></i>`).join("")}${chunks.map((chunk, index) => `<span style="left:${index * 20}%">${esc(String(chunk.range.start_time || "").slice(3))}</span>`).join("")}</div>`;
  }
  function renderOverview(pair) {
    const showEn = language === "en" || language === "both";
    const showZh = language === "zh" || language === "both";
    return `<div class="overview">${["sonnet", "gemini"].map(name => {
      const m = pair.models[name], isGemini = name === "gemini";
      const actionLang = language === "zh" ? "zh" : "en";
      const baseline = name === "sonnet" ? '<div class="baseline-note">旧 v3 基线只有一个 whole-clip segment；它没有按这次固定 chunk 合成局部文字。第一行保留原文，其余行只显示按时间重叠的动作。</div>' : '';
      const inputNote = name === "gemini" ? (m.chunkImagesIncluded === true ? '<div class="baseline-note">本次 Gemini 请求包含 5 张局部 chunk 证据图。</div>' : m.chunkImagesIncluded === false ? '<div class="baseline-note">该 case 的 Gemini 重试未发送局部 chunk 证据图；本页 chunk 图仅供离线核对，不代表模型输入。</div>' : '<div class="baseline-note">该 case 的局部 chunk 图片输入状态未知。</div>') : '';
      return `<section class="overview-pane ${name}"><div class="pane-head"><div><h3>${esc(m.label)}</h3><small>${esc(m.model)} · ${esc(m.status)}</small></div><div class="pane-metrics"><b>${m.en.visual_words}</b> EN words<br />${m.en.segment_count} segments · ${m.en.action_count} actions</div></div>${baseline}${inputNote}<div class="field-label">WHOLE RUN / ${showZh && !showEn ? "中文" : "ENGLISH"}</div>${showEn ? `<div class="overview-copy">${sceneMarkup(pair,name,"en")}</div>` : ""}${showZh ? `<div class="field-label">全程场景 / 中文</div><div class="overview-copy">${esc(modelText(pair,name,"zh"))}</div>` : ""}<div class="field-label">CONTAINED ACTIONS / ${actionLang === "zh" ? "中文" : "EN"}</div><ol class="action-list">${actionMarkup(modelActions(pair,name,actionLang))}</ol></section>`;
    }).join("")}</div>`;
  }
  function renderChunkRows(pair) {
    const showEn = language === "en" || language === "both";
    const showZh = language === "zh" || language === "both";
    return `<section class="chunk-section"><div class="chunk-heading"><h3>Five fixed causal windows.</h3><span>frame 0 conditions · latent 1—20 · each row is exactly 16 frames</span></div><div class="chunk-grid">${(pair.chunks || []).map((chunk, index) => {
      const sonnetText = index === 0 ? (language === "zh" ? chunk.sonnet.textZh : chunk.sonnet.text) : "";
      const geminiText = chunk.gemini.text || "";
      const sonnetActions = language === "zh" ? chunk.sonnet.actionsZh : chunk.sonnet.actions;
      const geminiActions = language === "zh" ? chunk.gemini.actionsZh : chunk.gemini.actions;
      return `<article class="chunk-row" data-chunk="${index}"><figure class="chunk-evidence"><img src="${esc(chunk.evidence)}" loading="lazy" alt="Chunk ${index} local evidence" /><figcaption>CHUNK ${String(index).padStart(2,"0")} · ${esc(chunk.range.start_time)} — ${esc(chunk.range.end_time)} · f${chunk.range.start_frame}—${chunk.range.end_frame_exclusive}</figcaption></figure><section class="chunk-cell sonnet"><div class="chunk-cell-head"><b>SONNET / legacy</b><span>${index === 0 ? "whole clip" : "no local text"}</span></div>${index === 0 && showEn ? `<div class="chunk-copy">${esc(chunk.sonnet.text)}</div>` : ""}${index === 0 && showZh ? `<div class="chunk-copy">${esc(chunk.sonnet.textZh || "")}</div>` : ""}${index !== 0 ? `<div class="chunk-copy muted">${esc(chunk.sonnet.textLabel)}</div>` : ""}<div class="chunk-actions">${actionMarkup(sonnetActions)}</div></section><section class="chunk-cell gemini"><div class="chunk-cell-head"><b>GEMINI / chunk ${index}</b><span>${esc(chunk.range.phase || "mixed")}</span></div>${showEn ? `<div class="chunk-copy">${esc(geminiText)}</div>` : ""}${showZh ? `<div class="chunk-copy">${esc(chunk.gemini.textZh || "")}</div>` : ""}<div class="chunk-actions">${actionMarkup(geminiActions)}</div></section></article>`;
    }).join("")}</div></section>`;
  }
  function renderCard(pair) {
    const d = pair.diff, badges = [d.geminiBoundariesExact ? '<span class="badge good">5 BOUNDARIES LOCKED</span>' : '<span class="badge warn">BOUNDARY CHECK</span>'];
    if (d.geminiWordsPerWindow > d.sonnetWordsPerWindowEquivalent) badges.push(`<span class="badge delta">GEMINI +${(d.geminiWordsPerWindow - d.sonnetWordsPerWindowEquivalent).toFixed(1)} WORDS / WINDOW</span>`);
    if (d.actionCountDelta !== 0) badges.push(`<span class="badge warn">ACTION COUNT ${d.actionCountDelta > 0 ? "+" : ""}${d.actionCountDelta}</span>`);
    if (pair.models.gemini.chunkImagesIncluded === false) badges.push('<span class="badge warn">LOCAL IMAGES OMITTED ON RETRY</span>');
    return `<article class="case-card"><header class="case-head"><div><div class="case-title"><h2>${esc(pair.actionLabel)} <small>${esc(pair.actionLabelZh)}</small></h2><small>${esc(String(pair.profile || "").toUpperCase())} · ${esc(pair.map || "unknown")}</small></div><div class="case-id">${esc(pair.id)}</div></div><div class="badges">${badges.join("")}</div></header><div class="media"><div class="media-main"><video controls preload="metadata" src="${esc(pair.video)}"></video></div><div class="media-side"><figure><img src="${esc(pair.evidence)}" alt="Full chronology" /><figcaption>FULL / 000—080</figcaption></figure><figure><img src="${esc(pair.foreground)}" alt="Foreground chronology" /><figcaption>FOREGROUND / VIEWMODEL</figcaption></figure></div>${timeline(pair)}</div>${renderOverview(pair)}${renderChunkRows(pair)}<div class="case-foot"><span>scene similarity ${Math.round(d.sceneSimilarity * 100)}% · per-window words: Sonnet equivalent ${d.sonnetWordsPerWindowEquivalent} → Gemini ${d.geminiWordsPerWindow} · latency ${esc(pair.models.gemini.latency)}s</span><span><a href="${esc(pair.models.gemini.resultAsset)}" download>Gemini JSON ↓</a> · <a href="${esc(pair.models.sonnet.resultAsset)}" download>Sonnet JSON ↓</a></span></div></article>`;
  }
  function populateActions() {
    const seen = new Set();
    data.pairs.forEach(pair => { if (seen.has(pair.action)) return; seen.add(pair.action); const option = document.createElement("option"); option.value = pair.action; option.textContent = `${pair.actionLabel} · ${pair.actionLabelZh}`; $("actionFilter").appendChild(option); });
  }
  function filtered() {
    const action = $("actionFilter").value, profile = $("profileFilter").value, focus = $("focusFilter").value, query = $("search").value.trim().toLowerCase();
    let rows = data.pairs.filter(pair => { if (action !== "all" && pair.action !== action) return false; if (profile !== "all" && pair.profile !== profile) return false; if (query && ![pair.id,pair.action,pair.actionLabel,pair.map,pair.profile].join(" ").toLowerCase().includes(query)) return false; if (focus === "length" && pair.diff.englishWordDelta <= 0) return false; if (focus === "actions" && pair.diff.actionCountDelta === 0) return false; if (focus === "low" && Math.min(...pair.models.gemini.en.visual_words_by_segment) >= 60) return false; return true; });
    return rows;
  }
  function render() { const rows = filtered(); $("resultCount").textContent = `${rows.length} / ${data.pairs.length} paired cases`; $("cards").innerHTML = rows.length ? rows.map(renderCard).join("") : '<div class="empty">没有匹配的配对</div>'; }
  renderStats(); populateActions(); render();
  ["actionFilter","profileFilter","focusFilter","search"].forEach(id => $(id).addEventListener("input", render));
  $("highlight").addEventListener("change", event => { highlight = event.target.checked; render(); });
  document.querySelectorAll("#languageToggle button").forEach(button => button.addEventListener("click", () => { language = button.dataset.lang; document.querySelectorAll("#languageToggle button").forEach(item => item.classList.toggle("active", item === button)); render(); }));
})();
