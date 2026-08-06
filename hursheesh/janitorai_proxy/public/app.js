(() => {
  'use strict';

  // ════════════════════════════════════════════════════════════════════
  //  ENIGMA EDGE GATEWAY — Dashboard client
  //  User-first: every state is visible, every action has feedback,
  //  every error is recoverable. No silent failures.
  // ════════════════════════════════════════════════════════════════════

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const providerLabels = {
    huggingface: 'Hugging Face', openrouter: 'OpenRouter', groq: 'Groq', google: 'Gemini',
    cerebras: 'Cerebras', mistral: 'Mistral', cohere: 'Cohere', zenmux: 'ZenMux',
    ainative: 'AI Native', puter: 'Puter'
  };

  // Auth token held in memory only — never persisted to localStorage.
  let authToken = null;

  // Track whether metrics panel should be shown (only when unlocked).
  let metricsVisible = false;

  // Active abort controller for diagnose (so we can cancel a running probe).
  let diagnoseAbort = null;

  // ─── Toast notification ──────────────────────────────────────────────
  let toastTimer = null;
  function toast(msg, duration = 2500) {
    const el = $('#toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), duration);
  }

  // ─── Utilities ───────────────────────────────────────────────────────
  function formatUptime(seconds) {
    if (!seconds && seconds !== 0) return '—';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  function formatMs(ms) {
    if (ms === null || ms === undefined) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function rateColor(rate) {
    if (rate === null || rate === undefined) return '#3a3d47';
    if (rate >= 0.8) return 'var(--signal)';
    if (rate >= 0.5) return 'var(--warn)';
    return 'var(--alarm)';
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ─── Status + signal board ───────────────────────────────────────────
  async function refreshStatus() {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      $('#pulse-dot').className = 'dot dot-online';
      $('#pulse-label').textContent = 'Online';
      $('#uptime').textContent = formatUptime(data.uptimeSeconds);
      $('#autopilot-readout').textContent = `Auto Pilot: ${data.autoPilotFallback ? 'on' : 'off'}`;
      $('#inspection-readout').textContent = `Content inspection: ${data.contentInspection ? 'on' : 'off'}`;
      $('#hedge-readout').textContent = `Hedge: ${data.hedgeConcurrency || '—'}`;

      renderSignalBoard(data.providers);
      renderStatsRow(data.providers);
      renderDeadModels(data.deadModels);

      // Update hedge slider if it exists and differs.
      const slider = $('#hedge-slider');
      if (slider && data.hedgeConcurrency) {
        slider.value = data.hedgeConcurrency;
        $('#hedge-value').textContent = data.hedgeConcurrency;
      }
    } catch (e) {
      $('#pulse-dot').className = 'dot dot-offline';
      $('#pulse-label').textContent = 'Unreachable';
    }
  }

  function renderStatsRow(providers) {
    const up = providers.filter(p => p.configured && p.enabled && !p.degraded).length;
    const total = providers.length;
    $('#stat-providers').textContent = `${up}/${total}`;

    const withRate = providers.filter(p => p.successRate !== null);
    if (withRate.length > 0) {
      const avgRate = withRate.reduce((s, p) => s + p.successRate, 0) / withRate.length;
      $('#stat-success').textContent = `${Math.round(avgRate * 100)}%`;
      $('#stat-success-sub').textContent = `${withRate.length} reporting`;
    } else {
      $('#stat-success').textContent = '—';
      $('#stat-success-sub').textContent = '';
    }

    const withLatency = providers.filter(p => p.avgLatencyMs !== null);
    if (withLatency.length > 0) {
      const avgLat = withLatency.reduce((s, p) => s + p.avgLatencyMs, 0) / withLatency.length;
      $('#stat-latency').textContent = formatMs(Math.round(avgLat));
    } else {
      $('#stat-latency').textContent = '—';
    }

    const concurrency = providers.reduce((s, p) => s + (p.concurrencyInUse || 0), 0);
    $('#stat-concurrency').textContent = concurrency;
  }

  function renderSignalBoard(providers) {
    const board = $('#signal-board');
    board.innerHTML = '';
    providers.forEach((p, i) => {
      const jack = document.createElement('div');
      jack.className = 'jack';

      let lightClass = '';
      let title = '';
      let sub = '';

      if (!p.configured) {
        lightClass = '';
        title = 'No key configured on the server';
        sub = 'no key';
      } else if (!p.enabled) {
        lightClass = '';
        title = 'Disabled by admin';
        sub = 'off';
      } else if (p.degraded) {
        lightClass = 'degraded';
        title = `All keys cooling down${p.successRate !== null ? ` (success: ${Math.round(p.successRate * 100)}%)` : ''}`;
        sub = 'degraded';
      } else {
        lightClass = 'lit';
        if (p.successRate !== null) {
          title = `Success: ${Math.round(p.successRate * 100)}%`;
          sub = p.avgLatencyMs !== null ? formatMs(p.avgLatencyMs) : '';
        }
      }

      jack.innerHTML = `
        <span class="jack-light ${lightClass}" style="animation-delay:${(i * 0.18).toFixed(2)}s" title="${escapeHtml(title)}"></span>
        <span class="jack-label">${escapeHtml(providerLabels[p.name] || p.name)}</span>
        ${sub ? `<span class="jack-sub">${escapeHtml(sub)}</span>` : ''}
      `;
      jack.title = title;
      board.appendChild(jack);
    });
  }

  function renderDeadModels(deadModels) {
    const section = $('#dead-models-section');
    const list = $('#dead-models-list');
    if (!deadModels || deadModels.length === 0) {
      section.style.display = 'none';
      return;
    }
    section.style.display = 'block';
    list.innerHTML = deadModels.map(m => `
      <div class="dead-model">
        <strong>${escapeHtml(providerLabels[m.provider] || m.provider)}</strong> &middot;
        ${escapeHtml(m.model)} &middot;
        recovers in ${Math.ceil(m.cooldownRemainingMs / 60000)}m
      </div>
    `).join('');
  }

  // ─── Metrics table (auth-gated) ──────────────────────────────────────
  async function refreshMetrics() {
    if (!authToken || !metricsVisible) return;
    try {
      const res = await fetch('/api/metrics', { headers: { Authorization: `Bearer ${authToken}` } });
      if (!res.ok) return;
      const data = await res.json();
      renderMetricsTable(data);
    } catch { /* silent — metrics are secondary */ }
  }

  function renderMetricsTable(providers) {
    const body = $('#metrics-body');
    body.innerHTML = '';
    for (const p of providers) {
      const rate = p.successEma;
      const ratePct = rate !== null ? Math.round(rate * 100) : '—';
      const rateColorVal = rateColor(rate);
      const rateWidth = rate !== null ? Math.round(rate * 100) : 0;

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${escapeHtml(providerLabels[p.name] || p.name)}</td>
        <td class="num">
          <span class="rate-bar"><span class="rate-fill" style="width:${rateWidth}%;background:${rateColorVal}"></span></span>
          ${ratePct}${ratePct !== '—' ? '%' : ''}
        </td>
        <td class="num">${p.latencyEma ? formatMs(p.latencyEma) : '—'}</td>
        <td class="num">${p.attempts}</td>
        <td class="num">${p.adaptiveTimeoutMs ? formatMs(p.adaptiveTimeoutMs) : '—'}</td>
        <td class="num">${p.concurrencyInUse || 0}</td>
      `;
      body.appendChild(tr);
    }
  }

  // ─── Catalog ─────────────────────────────────────────────────────────
  async function loadCatalog() {
    try {
      const res = await fetch('/api/catalog');
      if (!res.ok) throw new Error();
      const list = await res.json();
      const grid = $('#catalog-grid');
      grid.innerHTML = '';
      list.forEach(entry => {
        const card = document.createElement('div');
        card.className = 'model-card' + (entry.recommended ? ' recommended' : '');
        card.innerHTML = `
          ${entry.recommended ? '<span class="badge">Recommended</span>' : ''}
          <h3>${escapeHtml(entry.label)}</h3>
          <p class="tagline">${escapeHtml(entry.tagline)}</p>
          <p class="desc">${escapeHtml(entry.description)}</p>
          <code title="Click to copy">${escapeHtml(entry.id)}</code>
        `;
        const codeEl = card.querySelector('code');
        codeEl.addEventListener('click', () => {
          const text = entry.id;
          if (navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(text).then(() => {
              codeEl.textContent = 'copied!';
              toast(`Copied "${text}"`);
              setTimeout(() => codeEl.textContent = text, 900);
            }).catch(() => {
              // Fallback: select the text
              const range = document.createRange();
              range.selectNode(codeEl);
              window.getSelection()?.removeAllRanges();
              window.getSelection()?.addRange(range);
              toast('Select and copy');
            });
          } else {
            // Older browsers
            const range = document.createRange();
            range.selectNode(codeEl);
            window.getSelection()?.removeAllRanges();
            window.getSelection()?.addRange(range);
            toast('Select and copy');
          }
        });
        grid.appendChild(card);
      });
    } catch {
      $('#catalog-grid').innerHTML = '<p style="color:var(--paper-dim);grid-column:1/-1;text-align:center;">Could not load the model list right now.</p>';
    }
  }

  // ─── Settings panel ──────────────────────────────────────────────────
  function setSettingsLocked(locked) {
    $('#settings-locked').style.display = locked ? 'flex' : 'none';
    $('#settings-unlocked').style.display = locked ? 'none' : 'flex';
    metricsVisible = !locked;
    $('#metrics-section').style.display = (!locked && metricsVisible) ? 'block' : 'none';
    if (!locked) refreshMetrics();
  }

  function renderSettings(data) {
    $('#toggle-autopilot').checked = !!data.autoPilotFallback;
    $('#toggle-inspection').checked = !!data.contentInspection;
    if (data.hedgeConcurrency) {
      $('#hedge-slider').value = data.hedgeConcurrency;
      $('#hedge-value').textContent = data.hedgeConcurrency;
    }

    const list = $('#provider-toggles');
    list.innerHTML = '';
    data.providers.forEach(p => {
      const row = document.createElement('label');
      row.className = 'provider-row';
      row.innerHTML = `
        <span>${escapeHtml(providerLabels[p.name] || p.name)}${p.configured ? '' : ' <em>(no key)</em>'}</span>
        <input type="checkbox" data-provider="${escapeHtml(p.name)}" ${p.enabled ? 'checked' : ''} ${p.configured ? '' : 'disabled'} aria-label="Toggle ${escapeHtml(providerLabels[p.name] || p.name)}">
      `;
      list.appendChild(row);
    });
  }

  async function unlockSettings() {
    const pw = $('#password-input').value;
    if (!pw) { toast('Enter a password first'); return; }
    const status = $('#unlock-status');
    status.textContent = 'Checking…';
    $('#unlock-btn').disabled = true;
    try {
      const res = await fetch('/api/settings', { headers: { Authorization: `Bearer ${pw}` } });
      if (!res.ok) {
        status.textContent = 'Wrong password.';
        $('#unlock-btn').disabled = false;
        return;
      }
      authToken = pw;
      const data = await res.json();
      renderSettings(data);
      setSettingsLocked(false);
      status.textContent = '';
      toast('Unlocked');
    } catch {
      status.textContent = 'Could not reach the gateway.';
    }
    $('#unlock-btn').disabled = false;
  }

  // Debounce settings pushes so rapid toggle changes don't spam the API.
  let pushTimer = null;
  let pendingPush = null;

  function pushSettingsDebounced(partial) {
    pendingPush = { ...pendingPush, ...partial };
    clearTimeout(pushTimer);
    const status = $('#save-status');
    status.textContent = 'Saving…';
    pushTimer = setTimeout(async () => {
      const payload = pendingPush;
      pendingPush = null;
      await pushSettings(payload);
    }, 400);
  }

  async function pushSettings(partial) {
    if (!authToken) return;
    const status = $('#save-status');
    status.textContent = 'Saving…';
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
        body: JSON.stringify(partial)
      });
      if (!res.ok) { status.textContent = 'Save failed.'; toast('Save failed'); return; }
      const data = await res.json();
      renderSettings(data);
      refreshStatus();
      status.textContent = 'Saved.';
      setTimeout(() => status.textContent = '', 1500);
    } catch {
      status.textContent = 'Could not reach the gateway.';
      toast('Network error');
    }
  }

  // ─── Diagnose ────────────────────────────────────────────────────────
  async function runDiagnose() {
    if (!authToken) { toast('Unlock first'); return; }
    if (diagnoseAbort) { toast('Diagnose already running'); return; }

    const btn = $('#diagnose-btn');
    const results = $('#diagnose-results');
    btn.disabled = true;
    btn.textContent = 'Running…';
    results.innerHTML = '<p style="color:var(--paper-dim);font-size:13px;">Probing every provider and every key…</p>';

    diagnoseAbort = new AbortController();
    const started = Date.now();

    try {
      const res = await fetch('/api/diagnose', {
        headers: { Authorization: `Bearer ${authToken}` },
        signal: diagnoseAbort.signal
      });
      const data = await res.json();
      results.innerHTML = '';
      const elapsed = ((Date.now() - started) / 1000).toFixed(1);

      for (const r of data.results) {
        const div = document.createElement('div');
        div.className = 'diagnose-result';

        if (r.skipped) {
          div.innerHTML = `
            <span class="dr-icon skip"></span>
            <span class="dr-name">${escapeHtml(providerLabels[r.name] || r.name)}</span>
            <span class="dr-detail">skipped: ${escapeHtml(r.skipped)}</span>
          `;
        } else if (r.ok) {
          div.innerHTML = `
            <span class="dr-icon ok"></span>
            <span class="dr-name">${escapeHtml(providerLabels[r.name] || r.name)}</span>
            <span class="dr-detail">${escapeHtml(r.model)}</span>
            <span class="dr-latency">${formatMs(r.latencyMs)}</span>
          `;
        } else {
          div.innerHTML = `
            <span class="dr-icon fail"></span>
            <span class="dr-name">${escapeHtml(providerLabels[r.name] || r.name)}</span>
            <span class="dr-detail">${r.status ? `HTTP ${r.status}: ` : ''}${escapeHtml(r.error || 'failed')}${r.model ? ' &middot; ' + escapeHtml(r.model) : ''}</span>
            <span class="dr-latency">${formatMs(r.latencyMs)}</span>
          `;
        }
        results.appendChild(div);
      }

      const okCount = data.results.filter(r => r.ok).length;
      const total = data.results.length;
      toast(`Diagnose done: ${okCount}/${total} OK in ${elapsed}s`);
    } catch (e) {
      if (e.name === 'AbortError') {
        results.innerHTML = '<p style="color:var(--paper-dim);font-size:13px;">Cancelled.</p>';
      } else {
        results.innerHTML = '<p style="color:var(--alarm);font-size:13px;">Could not run diagnose. Check the gateway is reachable.</p>';
      }
    } finally {
      btn.disabled = false;
      btn.textContent = 'Run diagnose';
      diagnoseAbort = null;
    }
  }

  // ─── Reset metrics ───────────────────────────────────────────────────
  async function resetMetrics() {
    if (!authToken) return;
    const btn = $('#reset-metrics-btn');
    btn.disabled = true;
    try {
      const res = await fetch('/api/reset-metrics', {
        method: 'POST',
        headers: { Authorization: `Bearer ${authToken}` }
      });
      if (!res.ok) { toast('Reset failed'); return; }
      toast('Metrics reset');
      refreshMetrics();
      refreshStatus();
    } catch {
      toast('Network error');
    } finally {
      btn.disabled = false;
    }
  }

  // ─── Event wiring ────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    refreshStatus();
    loadCatalog();
    setInterval(refreshStatus, 10_000);
    setInterval(refreshMetrics, 15_000);

    // Settings unlock
    $('#unlock-btn').addEventListener('click', unlockSettings);
    $('#password-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') unlockSettings(); });

    // Toggle switches
    $('#toggle-autopilot').addEventListener('change', (e) => pushSettingsDebounced({ autoPilotFallback: e.target.checked }));
    $('#toggle-inspection').addEventListener('change', (e) => pushSettingsDebounced({ contentInspection: e.target.checked }));

    // Hedge slider
    const hedgeSlider = $('#hedge-slider');
    const hedgeValue = $('#hedge-value');
    hedgeSlider.addEventListener('input', (e) => { hedgeValue.textContent = e.target.value; });
    hedgeSlider.addEventListener('change', (e) => pushSettingsDebounced({ hedgeConcurrency: parseInt(e.target.value, 10) }));

    // Provider toggles (event delegation)
    $('#provider-toggles').addEventListener('change', (e) => {
      if (e.target.matches('input[data-provider]')) {
        pushSettingsDebounced({ providerEnabled: { [e.target.dataset.provider]: e.target.checked } });
      }
    });

    // Diagnose
    $('#diagnose-btn').addEventListener('click', runDiagnose);

    // Reset metrics
    $('#reset-metrics-btn').addEventListener('click', resetMetrics);

    // Lock
    $('#lock-btn').addEventListener('click', () => {
      authToken = null;
      metricsVisible = false;
      $('#password-input').value = '';
      $('#unlock-status').textContent = '';
      $('#metrics-section').style.display = 'none';
      $('#diagnose-results').innerHTML = '';
      setSettingsLocked(true);
      toast('Locked');
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      // Don't interfere with input fields
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'r') refreshStatus();
      if (e.key === 'd' && authToken) runDiagnose();
    });
  });
})();