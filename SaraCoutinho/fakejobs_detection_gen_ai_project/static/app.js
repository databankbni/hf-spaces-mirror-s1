const state = {
  analyses: [],
  reports: [],
};

const verdictLabel = {
  provavel_golpe: "Provavel golpe",
  atencao: "Atencao",
  provavel_legitima: "Provavel legitima",
};

const api = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.erro || "Falha na requisicao");
  return payload;
};

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const toast = (message) => {
  const element = document.querySelector("#toast");
  element.textContent = message;
  element.classList.add("show");
  setTimeout(() => element.classList.remove("show"), 2800);
};

const switchView = async (view) => {
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("active", section.id === `view-${view}`);
  });
  if (view === "historico") await loadHistory();
  if (view === "denuncias") await loadReports();
  if (view === "dashboard") await loadDashboard();
};

const formToJson = (form) => {
  const data = Object.fromEntries(new FormData(form).entries());
  form.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
    data[checkbox.name] = checkbox.checked;
  });
  return data;
};

const renderResult = (analysis) => {
  const flags = analysis.red_flags || [];
  const ai = analysis.analise_ia;
  const suggestions = Array.isArray(ai?.sugestoes_vagas_reais) ? ai.sugestoes_vagas_reais : [];
  const aiBlock = ai
    ? `
      <section class="ai-explanation">
        <div class="ai-heading">
          <p class="eyebrow">Explicação assistida</p>
          <span class="ai-status ${ai.status === "gerada_por_ia" ? "online" : "fallback"}">
            ${ai.status === "gerada_por_ia" ? `IA local · ${escapeHtml(ai.modelo)}` : "Fallback sem IA"}
          </span>
        </div>
        <p>${escapeHtml(ai.resumo)}</p>
        <strong>Próximo passo: ${escapeHtml(String(ai.recomendacao).replaceAll("_", " "))}</strong>
        <h3>O que verificar</h3>
        <ul>${(ai.pontos_para_verificar || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        <h3>Limitações</h3>
        <ul>${(ai.limitacoes || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        ${
          suggestions.length
            ? `<h3>Alternativas para pesquisar</h3>
               <ul>${suggestions
                 .map(
                   (item) =>
                     `<li><strong>${escapeHtml(item.titulo)}</strong> · ${escapeHtml(item.fonte)}<br><span>${escapeHtml(item.link_ou_observacao)}</span></li>`,
                 )
                 .join("")}</ul>`
            : ""
        }
        ${ai.tendencia_area ? `<h3>Tendência da área</h3><p>${escapeHtml(ai.tendencia_area)}</p>` : ""}
        ${
          Array.isArray(ai.ferramentas_usadas) && ai.ferramentas_usadas.length
            ? `<p class="muted">Tools utilizadas: ${ai.ferramentas_usadas.map(escapeHtml).join(", ")}.</p>`
            : ""
        }
        <p class="privacy-note">${escapeHtml(ai.alerta_privacidade)}</p>
      </section>`
    : "";
  document.querySelector("#analysis-result").innerHTML = `
    <div class="score-ring" style="--score: ${analysis.score_risco}">
      <strong>${analysis.score_risco}</strong>
    </div>
    <div class="verdict ${analysis.veredito}">${verdictLabel[analysis.veredito]}</div>
    <p class="muted" style="margin-top: 12px">Confianca ${analysis.confianca}. ${flags.length} sinal(is) encontrado(s).</p>
    <h2>Sinais identificados</h2>
    ${
      flags.length
        ? flags
            .map(
              (flag) => `
                <div class="flag">
                  <strong>${escapeHtml(flag.codigo)} <span>+${escapeHtml(flag.peso)}</span></strong>
                  <p>${escapeHtml(flag.descricao)}</p>
                  ${flag.trecho_evidencia ? `<span>Evidência: ${escapeHtml(flag.trecho_evidencia)}</span>` : ""}
                </div>
              `,
            )
            .join("")
        : '<p class="muted">Nenhuma red flag forte foi disparada.</p>'
    }
    ${aiBlock}
  `;
};

const loadHistory = async () => {
  const payload = await api("/api/analises");
  state.analyses = payload.items;
  const body = document.querySelector("#history-body");
  body.innerHTML = state.analyses.length
    ? state.analyses
        .map(
          (item) => `
          <tr>
            <td>${escapeHtml(item.title || "Vaga sem titulo")}</td>
            <td>${escapeHtml(item.fonte)}</td>
            <td><strong>${escapeHtml(item.score_risco)}</strong></td>
            <td>${escapeHtml(verdictLabel[item.veredito])}</td>
            <td>${escapeHtml(item.confianca)}</td>
            <td><button class="link-button" data-analysis="${escapeHtml(item.id)}">Ver</button></td>
          </tr>
        `,
        )
        .join("")
    : '<tr><td colspan="6">Nenhuma analise registrada ainda.</td></tr>';
};

const loadReports = async () => {
  const analyses = await api("/api/analises");
  state.analyses = analyses.items;
  const select = document.querySelector("#report-vaga-select");
  select.innerHTML = state.analyses.length
    ? state.analyses.map((item) => `<option value="${escapeHtml(item.vaga_id)}">${escapeHtml(item.title || item.vaga_id)}</option>`).join("")
    : '<option value="">Analise uma vaga primeiro</option>';

  const reports = await api("/api/denuncias");
  state.reports = reports.items;
  document.querySelector("#reports-list").innerHTML = state.reports.length
    ? state.reports
        .map(
          (item) => `
          <article class="mini-card">
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.motivo)}</p>
            <span class="muted">${escapeHtml(item.status)} - score ${escapeHtml(item.score_risco ?? "n/a")}</span>
          </article>
        `,
        )
        .join("")
    : '<p class="muted">Nenhuma sinalizacao registrada.</p>';
};

const loadDashboard = async () => {
  const data = await api("/api/dashboard");
  document.querySelector("#metrics").innerHTML = `
    <div class="metric"><span>Analises</span><strong>${data.total_analises}</strong></div>
    <div class="metric"><span>Score medio</span><strong>${data.score_medio}</strong></div>
    <div class="metric"><span>Sinalizacoes</span><strong>${data.denuncias}</strong></div>
  `;
  const total = Math.max(data.total_analises, 1);
  document.querySelector("#verdict-bars").innerHTML = Object.entries(data.vereditos)
    .map(([key, value]) => {
      const pct = Math.round((value / total) * 100);
      return `
        <div>
          <div class="bar-label"><strong>${verdictLabel[key]}</strong><span>${value}</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
        </div>
      `;
    })
    .join("");
};

document.querySelectorAll(".nav-button").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

document.querySelector("#analysis-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  button.textContent = "Analisando…";
  try {
    const payload = formToJson(event.currentTarget);
    const result = await api("/api/analisar", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderResult(result);
    toast(result.analise_ia?.status === "gerada_por_ia" ? "Análise gerada com IA local" : "Ollama indisponível: regras locais utilizadas");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Analisar com IA local";
  }
});

document.querySelector("#history-body").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-analysis]");
  if (!button) return;
  const analysis = await api(`/api/analises/${button.dataset.analysis}`);
  renderResult(analysis);
  switchView("analisar");
});

document.querySelector("#report-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = formToJson(event.currentTarget);
  if (!payload.vaga_id) {
    toast("Analise uma vaga antes de sinalizar");
    return;
  }
  await api("/api/denuncias", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  event.currentTarget.reset();
  await loadReports();
  toast("Sinalizacao registrada");
});

loadHistory().catch(() => {});
