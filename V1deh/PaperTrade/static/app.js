/* app.js — NSE Paper Trading Platform */
'use strict';

// ── Splash loader ──────────────────────────────────────────────────────────────
let _loaderDismissed = false;
function dismissLoader() {
  if (_loaderDismissed) return;
  _loaderDismissed = true;
  const el = document.getElementById('app-loader');
  if (!el) return;
  el.classList.add('app-loader--done');
  setTimeout(() => el.remove(), 450);
}
// Failsafe: auto-dismiss after 8s in case the first API call hangs
setTimeout(dismissLoader, 8000);

// ── Universe cache ─────────────────────────────────────────────────────────────
let UNIVERSE = [];
let _UNIVERSE_MAP = {};

async function loadUniverse() {
  try {
    const res  = await fetch('/api/universe');
    const data = await res.json();
    UNIVERSE   = data.universe || [];
    _UNIVERSE_MAP = {};
    UNIVERSE.forEach(u => { _UNIVERSE_MAP[u.ticker] = u.name; });
  } catch (e) { console.warn('Universe load failed:', e); }
}

// Returns the bare symbol and company name for any ticker string
function tickerMeta(ticker) {
  const sym  = ticker.replace(/\.(NS|BO)$/i, '');
  const exch = ticker.toUpperCase().endsWith('.BO') ? 'BSE' : 'NSE';
  const name = _UNIVERSE_MAP[ticker] || _UNIVERSE_MAP[sym + '.NS'] || _UNIVERSE_MAP[sym + '.BO'] || '';
  return { sym, exch, name };
}

// Compact two-line stock cell for use inside <td>
function stockCell(ticker) {
  const { sym, exch, name } = tickerMeta(ticker);
  return `<div class="sc-wrap">
    ${name ? `<div class="sc-name">${name}</div>` : ''}
    <div class="sc-sym-row"><span class="sc-sym">${sym}</span><span class="sc-exch">${exch}</span></div>
  </div>`;
}

// ── Candlestick chart via Lightweight Charts (yfinance / Yahoo Finance data) ──
async function mountLwChart(containerId, ticker, interval) {
  const el = document.getElementById(containerId);
  if (!el) return;

  // If remounting with a new interval, clear existing chart
  if (el.dataset.chartMounted && !interval) return;
  el._lwChart?.remove();
  clearInterval(el._chartRefreshTimer);
  el._chartRefreshTimer = null;
  el.dataset.chartMounted = '1';
  el.innerHTML = '';

  // Wait for layout to be calculated if element is newly visible
  await new Promise(resolve => {
    if (el.clientWidth > 0) {
      resolve();
    } else {
      requestAnimationFrame(() => resolve());
    }
  });

  // Get actual dimensions, with minimum fallbacks
  const width = el.clientWidth > 0 ? el.clientWidth : 400;
  const height = el.clientHeight > 0 ? el.clientHeight : 300;

  const chart = LightweightCharts.createChart(el, {
    width:  width,
    height: height,
    layout: { background: { color: '#1a1d2e' }, textColor: '#9ca3af' },
    grid:   { vertLines: { color: '#2d3040' }, horzLines: { color: '#2d3040' } },
    timeScale: {
      borderColor: '#2d3040',
      timeVisible: true,
      secondsVisible: false,
    },
    rightPriceScale: { borderColor: '#2d3040' },
  });
  el._lwChart = chart;

  const series = chart.addCandlestickSeries({
    upColor:         '#22c55e', downColor:         '#ef4444',
    borderUpColor:   '#22c55e', borderDownColor:   '#ef4444',
    wickUpColor:     '#22c55e', wickDownColor:     '#ef4444',
  });

  const sym = ticker.replace('.NS', '').replace('.BO', '');
  const iv  = interval || '1d';

  async function fetchAndUpdate(isInitial) {
    try {
      const res  = await fetch(`/api/chart/${sym}?interval=${iv}`);
      const data = await res.json();
      const candles = data.candles || [];
      if (!candles.length) {
        if (isInitial) el.innerHTML = '<div style="padding:20px;color:#6b7280;text-align:center">No chart data</div>';
        return;
      }
      if (isInitial) {
        series.setData(candles);
        chart.timeScale().fitContent();
        // Server fell back to daily data (e.g. ticker has no intraday feed) — sync the active pill
        if (data.interval && data.interval !== iv) {
          el.parentNode?.querySelectorAll?.('.chart-iv-pill').forEach(b => {
            b.classList.toggle('active', b.dataset.iv === data.interval);
          });
        }
      } else {
        // Incremental update: upsert the last few candles without reflowing the whole chart
        const tail = candles.slice(-5);
        tail.forEach(c => series.update(c));
      }
    } catch (e) {
      if (isInitial) el.innerHTML = '<div style="padding:20px;color:#6b7280;text-align:center">Chart unavailable</div>';
    }
  }

  await fetchAndUpdate(true);

  // Auto-refresh intraday charts every 5 minutes (data is 15-min delayed from Yahoo)
  if (iv === '5m' || iv === '15m') {
    el._chartRefreshTimer = setInterval(() => fetchAndUpdate(false), 5 * 60 * 1000);
  }

  new ResizeObserver(entries => {
    const newWidth = entries[0].contentRect.width;
    const newHeight = entries[0].contentRect.height;
    if (newWidth > 0 && newHeight > 0) {
      chart.applyOptions({ width: newWidth, height: newHeight });
    }
  }).observe(el);
}

// Wrap a chart container with interval toggle buttons (1D intraday / 1W / 3M)
function wrapWithIntervalToggle(containerId, ticker) {
  const container = document.getElementById(containerId);
  if (!container || container.dataset.toggleWrapped) return;
  container.dataset.toggleWrapped = '1';

  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap';

  const toolbar = document.createElement('div');
  toolbar.className = 'chart-toolbar';
  toolbar.innerHTML = `
    <span class="chart-ticker-label">${ticker.replace('.NS','').replace('.BO','')} · Yahoo Finance <span class="chart-delay">(15-min delayed)</span></span>
    <div class="chart-iv-pills">
      <button class="chart-iv-pill active" data-iv="5m">1D</button>
      <button class="chart-iv-pill" data-iv="1d">3M</button>
      <button class="chart-iv-pill" data-iv="15m">60D</button>
    </div>`;

  container.parentNode.insertBefore(wrap, container);
  wrap.appendChild(toolbar);
  wrap.appendChild(container);

  toolbar.querySelectorAll('.chart-iv-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      toolbar.querySelectorAll('.chart-iv-pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      mountLwChart(containerId, ticker, btn.dataset.iv);
    });
  });
}

// Lazy-mount charts when they enter viewport
function observeTvChart(containerId, ticker) {
  const wrapper = document.getElementById(containerId);
  if (!wrapper) return;
  const obs = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting) {
      obs.disconnect();
      wrapWithIntervalToggle(containerId, ticker);
      mountLwChart(containerId, ticker, '5m');
    }
  }, { threshold: 0.1 });
  obs.observe(wrapper);
}

// _watchlistLoaded — prevents tab switch from discarding in-flight LLM calls
// (watchlist predictions cost 12 LLM calls per stock; restarting on every tab switch wastes minutes)
let _watchlistLoaded = false;

// ── AI-unavailable auto-retry ──────────────────────────────────────────────────
// Shared by both loadWatchlist and loadTop5Cards — defined once, called identically.
let _aiRetryTimer = null;
let _aiRetryTick  = null;

function _clearAiRetry() {
  clearTimeout(_aiRetryTimer);  _aiRetryTimer = null;
  clearInterval(_aiRetryTick);  _aiRetryTick  = null;
}

// Prepend a "rate-limited — retrying in Ns" banner to containerEl.
// retryFn is called after 90s or immediately when the user clicks "Retry now".
// _clearAiRetry() is called at the top of every load function, so this banner
// is always torn down before a fresh load begins regardless of which path triggers it.
function _showAiRetryBanner(containerEl, retryFn) {
  _clearAiRetry();
  const banner = document.createElement('div');
  banner.id = 'ai-retry-banner';
  banner.className = 'ai-retry-banner';
  banner.innerHTML =
    '<span>⚠ Some AI forecasts are rate-limited — ' +
    '<span class="ai-retry-secs">retrying in 90s</span></span>' +
    '<button class="ai-retry-now">Retry now</button>';
  banner.querySelector('.ai-retry-now').addEventListener('click', () => {
    _clearAiRetry();
    retryFn();
  });
  containerEl.insertBefore(banner, containerEl.firstChild);

  let secs = 90;
  _aiRetryTick = setInterval(() => {
    secs -= 1;
    const countEl = document.getElementById('ai-retry-banner')
                            ?.querySelector('.ai-retry-secs');
    if (countEl) countEl.textContent = `retrying in ${secs}s`;
    if (secs <= 0) { _clearAiRetry(); retryFn(); }
  }, 1000);
}

// ── View navigation ────────────────────────────────────────────────────────────
function switchView(viewId) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const view = document.getElementById('view-' + viewId);
  if (view) view.classList.add('active');
  document.querySelectorAll(`.nav-item[data-view="${viewId}"]`).forEach(n => n.classList.add('active'));

  if (viewId === 'dashboard')  loadDashboard();
  if (viewId === 'portfolio')  loadPortfolio();
  if (viewId === 'watchlist' && !_watchlistLoaded) loadWatchlist();
  if (viewId === 'validation')  loadValidation();
}
document.querySelectorAll('.nav-item').forEach(n => {
  n.addEventListener('click', e => {
    e.preventDefault();
    switchView(n.dataset.view);
  });
});
// Also wire dashboard "View all →" link
document.querySelectorAll('[data-view]').forEach(el => {
  if (el.tagName === 'A' && !el.classList.contains('nav-item')) {
    el.addEventListener('click', e => { e.preventDefault(); switchView(el.dataset.view); });
  }
});

// ── Timeframe pill helper ──────────────────────────────────────────────────────
function makeTfPills(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return { getTf: () => '1D' };
  container.querySelectorAll('.tf-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      container.querySelectorAll('.tf-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
    });
  });
  return { getTf: () => (container.querySelector('.tf-pill.active') || {}).dataset.tf || '1D' };
}

// ── Ticker tag input ───────────────────────────────────────────────────────────
function makeTagInput({ inputId, suggestId, tagListId }) {
  const input   = document.getElementById(inputId);
  const suggest = document.getElementById(suggestId);
  const tagList = document.getElementById(tagListId);
  if (!input) return { getTickers: () => [] };
  const tags = new Set();

  function addTag(ticker) {
    ticker = ticker.toUpperCase().trim();
    if (!ticker) return;
    if (!ticker.includes('.')) ticker += '.NS';  // default to NSE; type .BO explicitly for BSE
    if (tags.has(ticker)) return;
    tags.add(ticker);
    renderTags();
    input.value = '';
    suggest.innerHTML = '';
  }

  function removeTag(ticker) { tags.delete(ticker); renderTags(); }

  function renderTags() {
    tagList.innerHTML = '';
    tags.forEach(t => {
      const el = document.createElement('span');
      el.className = 'tag';
      el.innerHTML = `${t} <span class="tag-remove" data-t="${t}">&times;</span>`;
      el.querySelector('.tag-remove').addEventListener('click', () => removeTag(t));
      tagList.appendChild(el);
    });
  }

  let _suggestTimer = null;
  function showSuggestions(q) {
    q = q.trim();
    if (!q) { suggest.innerHTML = ''; return; }
    clearTimeout(_suggestTimer);
    _suggestTimer = setTimeout(async () => {
      try {
        const res  = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        suggest.innerHTML = '';
        (data.results || []).forEach(u => {
          const item = document.createElement('div');
          item.className = 'suggestion-item';
          item.innerHTML = `<span class="suggestion-ticker">${u.ticker}</span><span class="suggestion-name">${u.name}</span>`;
          item.addEventListener('mousedown', e => { e.preventDefault(); addTag(u.ticker); });
          suggest.appendChild(item);
        });
      } catch (_) {}
    }, 280);
  }

  input.addEventListener('input', () => showSuggestions(input.value));
  input.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) {
      e.preventDefault(); addTag(input.value.split(',')[0]);
    }
  });
  input.addEventListener('blur', () => setTimeout(() => { suggest.innerHTML = ''; }, 150));

  return { getTickers: () => [...tags], addTag, clear: () => { tags.clear(); renderTags(); } };
}

// ── Colour helpers ─────────────────────────────────────────────────────────────
function retColor(midpoint) {
  if (midpoint > 2) return 'var(--green)';
  if (midpoint < -1) return 'var(--red)';
  return 'var(--yellow)';
}
function dirClass(dir) {
  return 'dir-' + (dir || 'NEUTRAL').replace(/ /g, '-');
}
function dirLabel(dir) {
  if (!dir) return '—';
  if (dir === 'SLIGHTLY BULLISH') return 'BULLISH ⚡';
  if (dir === 'SLIGHTLY BEARISH') return 'BEARISH ⚡';
  return dir;
}
function confClass(c) {
  return 'conf-' + (c === 'BLOCKED' ? 'LOW' : (c || 'LOW'));
}

function formatReturnRange(lo, hi, decimals = 1) {
  const loNum = Number(lo);
  const hiNum = Number(hi);
  if (!Number.isFinite(loNum) || !Number.isFinite(hiNum)) return 'N/A';

  // For bearish ranges, show the less-negative bound first (e.g. -2.96% to -3.76%).
  const [first, second] = (loNum < 0 && hiNum < 0 && loNum < hiNum)
    ? [hiNum, loNum]
    : [loNum, hiNum];

  return `${first >= 0 ? '+' : ''}${first.toFixed(decimals)}% to ${second >= 0 ? '+' : ''}${second.toFixed(decimals)}%`;
}

// ── Market closed banner ───────────────────────────────────────────────────────
function showMarketClosedBanner(mktClosed) {
  if (!mktClosed) return;
  const existing = document.getElementById('market-closed-banner');
  if (existing) return; // already shown

  const banner = document.createElement('div');
  banner.id = 'market-closed-banner';
  const isHoliday = mktClosed.status === 'HOLIDAY';
  const isWeekend = mktClosed.status === 'WEEKEND';
  const icon = isHoliday ? '🎉' : isWeekend ? '📅' : '🕐';
  const nextLine = mktClosed.next_open
    ? `<span style="margin-left:8px;opacity:0.8">Next open: ${mktClosed.next_open}</span>` : '';
  banner.innerHTML = `<span style="flex:1;min-width:0">${icon} ${mktClosed.message}${nextLine}</span>
    <button onclick="document.getElementById('market-closed-banner').remove()"
      style="background:none;border:none;cursor:pointer;font-size:18px;opacity:0.7;min-width:36px;min-height:36px;padding:4px 8px;line-height:1;flex-shrink:0;touch-action:manipulation">✕</button>`;
  Object.assign(banner.style, {
    position: 'fixed', top: '60px', left: '50%', transform: 'translateX(-50%)',
    background: isHoliday ? '#5b3a1f' : '#1e3a4a',
    color: '#f0e0c0', padding: '10px 16px', borderRadius: '8px',
    boxShadow: '0 2px 12px rgba(0,0,0,0.5)', zIndex: '9999',
    fontSize: '14px', fontWeight: '500',
    display: 'flex', alignItems: 'center', gap: '8px',
    maxWidth: 'calc(100vw - 32px)', boxSizing: 'border-box',
  });
  document.body.appendChild(banner);
  setTimeout(() => banner?.remove(), 12000); // auto-dismiss after 12s
}

// ── Market bar helper ──────────────────────────────────────────────────────────
function applyMarket(market) {
  if (!market) return;
  const vixEl   = document.getElementById('gm-vix');
  const niftyEl = document.getElementById('gm-nifty');
  const macroEl = document.getElementById('gm-macro');
  if (vixEl) {
    vixEl.textContent = market.vix_label || '—';
    const vl = market.vix_label || '';
    vixEl.className = 'market-value ' + (
      vl.startsWith('LOW') ? 'market-ok' :
      vl.startsWith('MODERATE') ? 'market-warn' : 'market-bad'
    );
  }
  if (niftyEl) {
    niftyEl.textContent = market.nifty_ok ? 'ABOVE EMA200' : 'BELOW EMA200';
    niftyEl.className = 'market-value ' + (market.nifty_ok ? 'market-ok' : 'market-bad');
  }
  if (macroEl) {
    macroEl.textContent = market.macro_ok ? 'RISK ON' : 'RISK OFF';
    macroEl.className = 'market-value ' + (market.macro_ok ? 'market-ok' : 'market-bad');
  }
}

// ── Render: Prediction Card ───────────────────────────────────────────────────
function renderPredCard(pred, showChart = true) {
  if (pred.error) return `<div class="error-card">${pred.ticker || ''}: ${pred.error}</div>`;

  const dir     = pred.direction || 'NEUTRAL';
  const isUp    = dir.includes('BULLISH');
  const isBlock = dir === 'NO TRADE' || dir === 'BLOCKED';
  const cls     = isUp ? 'bullish' : isBlock ? 'blocked' : (dir.includes('BEARISH') ? 'bearish' : '');
  const mid     = pred.midpoint || 0;
  const ml      = pred.ml || {};
  const news    = pred.news || {};
  const earn    = pred.earnings || {};
  const kl      = pred.key_levels || {};
  const tvId    = 'tv-' + pred.ticker.replace(/[^a-zA-Z0-9]/g, '_');
  const alloc   = pred.suggested_allocation ? `<div class="alloc-block">Suggested: ₹${num(pred.suggested_allocation)} → ${pred.suggested_shares} shares</div>` : '';
  const earnsHtml = earn.in_blackout
    ? `<div class="earnings-warn">⚠ Earnings blackout: ${earn.warning || ''}</div>`
    : earn.next_date ? `<div style="font-size:11px;color:var(--text-muted);margin-top:6px">Earnings: ${earn.next_date} (${earn.days_away}d away)</div>` : '';

  const signals = pred.signals || {};
  const risk    = pred.risk || {};


  // Trade plan values from production payload (fallback to computed values when absent)
  const plan = {
    ...(pred.trade_plan || {}),
    strategy:  (pred.active_strategies || [])[0] || null,
    timeframe: pred.timeframe || null,
    prediction_data: {
      ml:     pred.ml     || {},
      news:   pred.news   || {},
      ai:     pred.ai_forecast ? {
        direction:       pred.ai_forecast.direction,
        confidence:      pred.ai_forecast.confidence,
        target_price_hi: pred.ai_forecast.target_price_hi,
        target_price_lo: pred.ai_forecast.target_price_lo,
      } : {},
      market: pred.market || {},
    },
  };
  const entryPrice = (plan.expected_entry_price ?? pred.expected_entry_price ?? pred.price) || 0;
  const priceLo = (plan.target_price_lo !== undefined && plan.target_price_lo !== null)
    ? plan.target_price_lo
    : ((entryPrice > 0 && pred.ret_lo !== undefined) ? entryPrice * (1 + pred.ret_lo / 100) : null);
  const priceHi = (plan.target_price_hi !== undefined && plan.target_price_hi !== null)
    ? plan.target_price_hi
    : ((entryPrice > 0 && pred.ret_hi !== undefined) ? entryPrice * (1 + pred.ret_hi / 100) : null);
  const expectedTarget = plan.expected_target_price ?? pred.expected_target_price ??
    ((entryPrice > 0 && pred.midpoint !== undefined) ? entryPrice * (1 + pred.midpoint / 100) : null);
  // Prefer AI forecast target (highest possible range for the direction) over technical target.
  const _af = pred.ai_forecast || {};
  const _afHi = _af.target_price_hi, _afLo = _af.target_price_lo;
  const aiTradeTarget = (_afHi && _afLo)
    ? (_af.direction === 'BEARISH' ? Math.min(_afHi, _afLo) : Math.max(_afHi, _afLo))
    : null;
  const tradeTarget = aiTradeTarget ?? expectedTarget ?? risk.min_target ?? null;

  const priceTargetHtml = `
    <div class="price-targets">
      <div class="pt-row">
        <span class="pt-label">Expected Entry</span>
        <span class="pt-entry">₹${num(entryPrice)}</span>
      </div>
      ${(expectedTarget !== null) ? `<div class="pt-row">
        <span class="pt-label">Expected Target</span>
        <span class="pt-target" style="color:${retColor(mid)}">₹${num(expectedTarget, 0)}</span>
      </div>` : ''}
      ${(priceLo !== null && priceHi !== null) ? `<div class="pt-row">
        <span class="pt-label">Target Range</span>
        <span class="pt-range" style="color:${retColor(mid)}">₹${num(priceLo, 0)} – ₹${num(priceHi, 0)}</span>
        <span class="pt-pct" style="color:${retColor(mid)}">(${pred.ret_lo != null && pred.ret_hi != null
          ? formatReturnRange(pred.ret_lo, pred.ret_hi, 1)
          : (pred.expected_return_range || 'N/A')})</span>
      </div>` : ''}
    </div>`;

  const rrWarn = (risk.actual_rr !== null && risk.actual_rr !== undefined && risk.actual_rr < 1.5)
    ? `<div class="rr-warn">⚠ Trade offers only ${risk.actual_rr}R — below 1.5R minimum</div>` : '';

  const riskHtml = risk.stop_loss ? `
    <div class="risk-strip">
      <div class="risk-item risk-sl">
        <span class="risk-lbl">Stop Loss (${{'INTRADAY':'0.4','1D':'0.7','3D':'1.1','5D':'1.5'}[pred.timeframe]||'ATR'}×ATR14)</span>
        <span class="risk-val">₹${num(risk.stop_loss)}</span>
        <span class="risk-pct">−${num(Math.abs(risk.stop_loss_pct || 0), 1)}%</span>
      </div>
      <div class="risk-item risk-tgt">
        <span class="risk-lbl">Target${risk.actual_rr ? ` (${risk.actual_rr}R)` : ''}</span>
        <span class="risk-val">₹${num(tradeTarget)}</span>
      </div>
      ${rrWarn}
    </div>` : '';

  const chartSection = showChart ? `
    <div class="pred-chart">
      <div class="tv-chart-container" id="${tvId}"></div>
    </div>` : '';

  const predBareSym  = pred.ticker.replace(/\.(NS|BO)$/i, '');
  const predExchange = pred.ticker.endsWith('.BO') ? 'BSE' : 'NSE';

  const html = `
    <div class="pred-card ${cls}" id="card-${pred.ticker.replace(/[^a-zA-Z0-9]/g,'_')}">
      <div class="pred-header">
        <div class="pick-identity">
          ${pred.company ? `<div class="pick-name">${pred.company}</div>` : ''}
          <div class="pick-symbol-row">
            <span class="pick-symbol" style="font-size:15px">${predBareSym}</span>
            <span class="pick-exchange">${predExchange}</span>
            ${pred.price ? `<span class="pick-price-badge">₹${num(pred.price)}</span>` : ''}
          </div>
        </div>
        <span class="dir-badge ${dirClass(dir)}" title="${dir}">${dirLabel(dir)}</span>
        <span class="conf-pill ${confClass(pred.confidence)}">${pred.confidence || 'LOW'}</span>
        <div class="pred-actions">
          <button class="btn-ghost btn-sm" onclick="addToWatchlist('${pred.ticker}','${(pred.company||'').replace(/'/g,"\\'")}')">+ Watch</button>
          <button class="btn-primary btn-sm" onclick='openTradeModal(${JSON.stringify(pred.ticker)},${JSON.stringify(pred.company||'')},${pred.price || 0},${risk.stop_loss||0},${tradeTarget||0},${JSON.stringify(plan)})'>Trade</button>
        </div>
      </div>
      <div class="pred-body">
        <div class="pred-info">
          ${priceTargetHtml}
          <div class="pred-period">over ${pred.trading_days || '?'} trading days</div>
          ${riskHtml}
          <div class="pred-section">
            <div class="ml-bar-wrap">
              <div class="ml-bar-track"><div class="ml-bar-fill" style="width:${ml.score||0}%"></div></div>
              <span class="ml-score-lbl">${ml.score||0}/100</span>
            </div>
            ${news.label ? `<div class="news-block">
              <div class="news-label" style="color:${news.label==='BULLISH'?'var(--green)':news.label==='BEARISH'?'var(--red)':'var(--yellow)'}">${news.label}</div>
              <div class="news-sum">${news.summary || news.headlines?.[0] || 'No news data'}</div>
            </div>` : ''}
            ${earnsHtml}
            ${alloc}
            <div class="key-levels">
              ${kl.ema20  ? `<div class="kl-item">EMA20 <span class="kl-val">₹${num(kl.ema20)}</span></div>` : ''}
              ${kl.ema50  ? `<div class="kl-item">EMA50 <span class="kl-val">₹${num(kl.ema50)}</span></div>` : ''}
              ${kl.ema200 ? `<div class="kl-item">EMA200 <span class="kl-val">₹${num(kl.ema200)}</span></div>` : ''}
            </div>
          </div>
        </div>
        ${chartSection}
      </div>
    </div>`;

  if (showChart) {
    // Mount chart after DOM insertion
    setTimeout(() => observeTvChart(tvId, pred.ticker), 50);
  }
  return html;
}

// ── News modal cache & renderer ───────────────────────────────────────────────
const _newsDataCache = {};

// Format an ISO 'YYYY-MM-DD' date as "21 Jul" plus a relative age ("today" / "3d ago").
function _fmtNewsDate(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'T00:00:00');
  if (isNaN(d)) return '';
  const label = d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Math.round((today - d) / 86400000);
  const rel = days <= 0 ? 'today' : days === 1 ? 'yesterday' : `${days}d ago`;
  return `${label} · ${rel}`;
}

// Dated headlines sorted NEWEST-FIRST (today → yesterday → older). Defensive: re-sorts on the
// client so the freshest news always leads regardless of backend ordering. Undated items sink
// to the bottom. 'YYYY-MM-DD' strings sort lexicographically = chronologically.
function _sortedDatedHeadlines(news) {
  const dated = Array.isArray(news && news.headlines_dated) ? news.headlines_dated.slice() : [];
  return dated
    .filter(it => it && it.title)
    .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')));
}

// The single freshest headline to feature on a card — newest dated headline first, falling
// back to the LLM's key_headline (or first plain headline) when no dates are available.
function _latestHeadline(news) {
  if (!news) return null;
  const sorted = _sortedDatedHeadlines(news);
  if (sorted.length && sorted[0].date) return { title: sorted[0].title, date: sorted[0].date };
  if (sorted.length) return { title: sorted[0].title, date: news.latest_date || '' };
  if (news.key_headline) return { title: news.key_headline, date: news.latest_date || '' };
  const plain = Array.isArray(news.headlines) ? news.headlines[0] : '';
  return plain ? { title: plain, date: news.latest_date || '' } : null;
}

function showNewsModal(ticker) {
  const d = _newsDataCache[ticker] || {};
  const label     = d.label || 'NEUTRAL';
  const summary   = d.summary || '';
  const dated     = _sortedDatedHeadlines(d);  // newest-first (today → yesterday → older)
  const headlines = d.headlines || (d.key_headline ? [d.key_headline] : []);
  const sentimentColor = label === 'BULLISH' ? 'var(--green)' : label === 'BEARISH' ? 'var(--red)' : 'var(--yellow)';
  const sentimentText  = label === 'BULLISH' ? 'POSITIVE' : label === 'BEARISH' ? 'NEGATIVE' : label || 'NEUTRAL';

  const titleEl = document.getElementById('news-modal-title');
  const bodyEl  = document.getElementById('news-modal-body');
  if (!titleEl || !bodyEl) { console.error('news-modal elements not found'); return; }

  titleEl.textContent = `Latest News — ${ticker.replace(/\.(NS|BO)$/i, '')}`;

  // Prefer dated headlines (newest-first with publish date) when available.
  const items = dated.length ? dated : headlines.map(h => ({ title: h, date: '' }));
  const headlinesHtml = items.length
    ? items.map((it, i) => {
        const ds = _fmtNewsDate(it.date);
        const dateHtml = ds ? `<span class="news-modal-date" style="display:block;font-size:11px;color:var(--text-muted);margin-top:2px">${ds}</span>` : '';
        return `<div class="news-modal-item"><span class="news-modal-num">${i + 1}</span><span class="news-modal-text">${it.title}${dateHtml}</span></div>`;
      }).join('')
    : '<div style="color:var(--text-muted);font-size:13px">No headlines available.</div>';

  const asOf = _fmtNewsDate(d.latest_date);
  const asOfHtml = asOf
    ? `<span style="font-size:11px;color:var(--text-muted)">Latest: ${asOf}</span>`
    : '';

  bodyEl.innerHTML = `
    <div style="margin-bottom:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <span style="font-size:13px;font-weight:600;color:${sentimentColor}">Sentiment: ${sentimentText}</span>
      ${asOfHtml}
    </div>
    ${summary ? `<div style="font-size:12px;color:var(--text-muted);margin-bottom:14px;font-style:italic">${summary}</div>` : ''}
    <div class="news-modal-list">${headlinesHtml}</div>`;

  document.getElementById('news-modal')?.classList.remove('hidden');
}

// ── TF cell constants & renderer (module-level so _fetchAndUpdateTfCell can use them) ──
const _TF_SIGNALS = {
  'INTRADAY': ['S1', 'S4', 'S4V2', 'S8', 'S16', 'S_CTRIO'],
  '1D': ['S1', 'S4', 'S4V2', 'S7', 'S8', 'S11', 'PED', 'S_CAPFLOW', 'S_CTRIO', 'S15', 'S16', 'S20'],
  '3D': ['S1', 'S4', 'S4V2', 'S5', 'S5V2', 'S6', 'S6V2', 'S7', 'S8', 'S9', 'S11', 'SUPER', 'PED',
          'S_CAPFLOW', 'S_CTRIO', 'S14', 'S15', 'S16', 'S17', 'S18', 'S20'],
  '5D': ['S2', 'S5', 'S5V2', 'S6', 'S6V2', 'S9', 'S10', 'S11', 'MFS', 'NIRA', 'SUPER',
          'S_CAPFLOW', 'S_CTRIO', 'S_SEASONAL', 'S12', 'S13', 'S14', 'S15', 'S16', 'S17', 'S18', 'S19'],
};
const _NO_TRADE_LABELS = {
  'no_signal':       '— No signal',
  'wrong_timeframe': '— Signal ≠ horizon',
  'neutral_signal':  '— Neutral (no edge)',
  'too_close_to_close': '🕐 Too late (post 2:15pm)',
  'vix_block':       '⚠ BLOCKED (VIX > 25)',
  'data_error':      '— Data unavailable',
  'ai_unavailable':  '🤖 AI loading…',
  'market_closed':   '🕐 Market closed',
  'timeout':         '🤖 AI loading…',
};
// Max background auto-retries per AI cell (~1/min). Covers per-minute rate-limit
// resets and Ollama cold starts so the AI forecast fills in once a provider frees up.
const _AI_RETRY_MAX = 30;
const _NO_TRADE_REASONS = {
  'no_signal':       'No strategy signal is active for this timeframe right now.',
  'wrong_timeframe': 'A signal may exist, but it is not validated for this timeframe.',
  'neutral_signal':  'Strategy signals are firing, but the AI forecast is NEUTRAL — no directional edge, so there is no trade to take.',
  'too_close_to_close': 'It is past 2:15pm IST — too little session left for a fresh intraday trade to reach its target by close.',
  'vix_block':       'Market risk gate is active (India VIX above threshold).',
  'data_error':      'Required market data is incomplete, so the setup is skipped.',
  'ai_unavailable':  'AI forecast is loading — retrying automatically as providers free up. The ML estimate is shown meanwhile.',
  'market_closed':   'NSE is currently closed. INTRADAY prediction unavailable until market opens.',
  'timeout':         'AI forecast is loading — retrying automatically as providers free up. The ML estimate is shown meanwhile.',
};

// Render one TF cell — used by renderPickCard and _fetchAndUpdateTfCell for live updates.
function _renderOneTfCell(tf, d, pick) {
  const signals = pick.signals || {};
  const pickPrice = pick.price || 0;
  const bestTf = pick.best_tf || null;
  const safeId = (pick.ticker || '').replace(/[^a-zA-Z0-9]/g, '_');
  // ML forecast for this TF — computed up front (also used later for the AI banner "ML" line
  // and the risk block) so it can be shown even while the slower AI call is still pending.
  const _mlData = d.ml || (_mlCache.get(pick.ticker || '') || {}).tfs?.[tf] || null;

  // "pending" = this timeframe's AI forecast is still being computed in the
  // background (streaming top-picks). Show a spinner for the AI part, but still render the
  // ML forecast (row + banner line) so 1D/3D aren't blank while the AI catches up.
  if (d.no_trade_reason === 'pending') {
    const isBestTfP = bestTf !== null && (tf === bestTf);
    const _mlSlotPending = _mlData ? _renderMlRow(tf, _mlData) : '<div class="tf-ml-mini-loader">🤖 ML…</div>';
    return `<div class="tf-cell tf-cell--loading${isBestTfP ? ' tf-cell--best' : ''}" id="tf-${safeId}-${tf}" data-ai-dir="">
      <div class="tf-label">${tf === 'INTRADAY' ? 'Today' : tf}</div>
      <div class="tf-cell-spinner">⟳</div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:4px">AI analysing…</div>
      <div class="tf-ai-ml-sep"><span class="tf-ai-ml-sep-lbl">🤖 ML MODEL</span></div>
      <div class="tf-ml-block"><div class="tf-ml-slot" id="ml-${safeId}-${tf}">${_mlSlotPending}</div></div>
      <div class="tf-agree-slot" id="agree-${safeId}-${tf}"></div>
    </div>`;
  }

  const noTradeReason = d.no_trade_reason;
  const isNoTrade = !!noTradeReason || d.direction === 'NO TRADE' || d.direction === 'N/A';
  // Range-only call (1D): next-day DIRECTION has a ~74% ceiling, so instead of a directional
  // target that misses ~1-in-4, the backend emits an honest reachable NEUTRAL range band.
  const isRangeBound = !!d.range_bound;
  const tfEntry = d.expected_entry_price ?? pickPrice;
  const tPriceLo = (!isNoTrade && d.target_price_lo !== undefined && d.target_price_lo !== null)
    ? d.target_price_lo
    : ((!isNoTrade && tfEntry > 0 && d.ret_lo !== undefined) ? tfEntry * (1 + d.ret_lo / 100) : null);
  const tPriceHi = (!isNoTrade && d.target_price_hi !== undefined && d.target_price_hi !== null)
    ? d.target_price_hi
    : ((!isNoTrade && tfEntry > 0 && d.ret_hi !== undefined) ? tfEntry * (1 + d.ret_hi / 100) : null);
  const tfExpectedTarget = d.expected_target_price ??
    ((!isNoTrade && tfEntry > 0 && d.midpoint !== undefined) ? tfEntry * (1 + d.midpoint / 100) : null);
  const priceRange = (tPriceLo !== null && tPriceHi !== null && Math.abs(tPriceHi - tPriceLo) > 0.01)
    ? `<div class="tf-prices" style="color:${retColor(d.midpoint||0)}">₹${num(tPriceLo,0)}–₹${num(tPriceHi,0)}</div>`
    : '';
  const targetMid = isRangeBound
    ? `<div class="tf-mid-target tf-range-bound" title="1D next-day direction has a ~74% accuracy ceiling — shown as an honest reachable range instead of a directional target that misses ~1-in-4 times">Range-bound · no directional target</div>`
    : ((!isNoTrade && tfExpectedTarget !== null)
      ? `<div class="tf-mid-target">Target ₹${num(tfExpectedTarget, 0)}</div>`
      : '');
  const gappedNote = '';
  const retLabel = isNoTrade
    ? `<span class="no-trade-label">${_NO_TRADE_LABELS[noTradeReason] || '— No trade'}</span>`
    : (d.ret_lo != null && d.ret_hi != null
        ? formatReturnRange(d.ret_lo, d.ret_hi, 2)
        : (d.expected_return_range || 'N/A'));
  let noTradeDetailText = _NO_TRADE_REASONS[noTradeReason] || 'No actionable setup for this timeframe.';
  if (noTradeReason === 'wrong_timeframe') {
    const activeSigNames = Object.keys(signals).filter(s => signals[s]);
    const validTfs = ['INTRADAY', '1D'].filter(t => t !== tf && activeSigNames.some(s => (_TF_SIGNALS[t] || []).includes(s)));
    const sigList = activeSigNames.length ? ` Active: ${activeSigNames.join(', ')}.` : '';
    const hintTfs = validTfs.length ? ` Check ${validTfs.join(' or ')}.` : '';
    noTradeDetailText += sigList + hintTfs;
  } else if (noTradeReason === 'neutral_signal') {
    // AI's own bull/bear trigger read is independent of the strategy-signal engine, so
    // signal_count can legitimately be 0 here — don't claim signals are firing when they aren't.
    noTradeDetailText = (typeof d.signal_count === 'number' && d.signal_count > 0)
      ? 'Strategy signals are firing, but the AI forecast is NEUTRAL — no directional edge, so there is no trade to take.'
      : 'No strategy signals are active, and the AI\u2019s own read of price action is also balanced (NEUTRAL) — no directional edge, so there is no trade to take.';
    if (typeof d.signal_count === 'number') noTradeDetailText += ` (Signals active: ${d.signal_count})`;
  } else if (noTradeReason !== 'timeout' && noTradeReason !== 'ai_unavailable' && typeof d.signal_count === 'number') {
    noTradeDetailText += ` (Signals active: ${d.signal_count})`;
  }
  const noTradeDetail = isNoTrade
    ? `<div class="tf-no-trade-reason">${noTradeDetailText}</div>`
    : '';

  const allChips = (_TF_SIGNALS[tf] || [])
    .filter(s => signals[s])
    .map(s => `<span class="sig-chip active sig-chip-sm">${s}</span>`);
  const moreCount = allChips.length - 2;
  const chipsHtml = allChips.slice(0, 2).join('')
    + (moreCount > 0 ? `<span class="sig-more">+${moreCount}</span>` : '');

  const dirClass = (d.direction || 'NEUTRAL').replace(/\s+/g, '-');
  const dirHtml  = `<div class="tf-dir-row"><span class="dir-dot dir-dot-${dirClass}"></span><span class="tf-dir" title="${d.direction || ''}">${dirLabel(d.direction) || '—'}</span></div>`;
  // Confidence bar for the main (AI-blended) call — rendered in every timeframe cell.
  const _confPct = c => c === 'HIGH' ? 90 : c === 'MEDIUM' ? 55 : c === 'LOW' ? 25 : 0;
  const mainConf = (d.ai_forecast && d.ai_forecast.confidence) || d.confidence || '';
  const mainConfBar = (!isNoTrade && mainConf)
    ? `<div class="tf-conf-row" title="AI directional confidence: ${mainConf}"><span class="tf-conf-lbl">AI conf</span><div class="conf-bar"><div class="conf-bar-fill conf-${mainConf.toLowerCase()}" style="width:${_confPct(mainConf)}%"></div></div><span class="tf-conf-val conf-${mainConf.toLowerCase()}">${mainConf}</span></div>`
    : '';

  const pd = d.predicted_direction;
  const pdLo = d.predicted_return_lo;
  const pdHi = d.predicted_return_hi;
  const af = d.ai_forecast;
  // AI is loading whenever this TF is in a retryable state (timeout/ai_unavailable) — the
  // frontend keeps refetching in the background, so show a soft "loading" note, never a
  // terminal error. The ML forecast renders independently in its own slot meanwhile.
  const aiLoading = noTradeReason === 'timeout' || noTradeReason === 'ai_unavailable'
    || (af && af.source === 'ai_unavailable');

  let aiForecastHtml = '';
  if (aiLoading) {
    aiForecastHtml = `<div class="tf-ai-note" style="color:var(--text-muted)">🤖 AI forecast loading — retrying automatically.<br>ML estimate shown below.</div>`;
  } else if (af && af.direction) {
    const afColor  = af.direction === 'BULLISH' ? 'var(--green)' : af.direction === 'BEARISH' ? 'var(--red)' : 'var(--text-muted)';
    const afArrow  = af.direction === 'BULLISH' ? '▲' : af.direction === 'BEARISH' ? '▼' : '◆';
    const afConf   = af.confidence ? ` · ${af.confidence}` : '';
    const afHasTarget = af.target_price_lo && af.target_price_hi && af.target_price_lo > 0 && af.target_price_hi > 0;
    const afTargetHtml = afHasTarget
      ? `<div class="tf-ai-target" style="color:${afColor}">₹${num(Math.min(af.target_price_lo, af.target_price_hi), 0)} – ₹${num(Math.max(af.target_price_lo, af.target_price_hi), 0)}</div>`
      : '';
    const afRange = (af.predicted_return_lo != null && af.predicted_return_hi != null)
      ? ` ${formatReturnRange(af.predicted_return_lo, af.predicted_return_hi, 1)}` : '';
    const buyChip = (af.should_buy === true)
      ? `<span class="ai-buy-chip ai-buy-yes">BUY</span>`
      : (af.should_buy === false ? `<span class="ai-buy-chip ai-buy-no">SKIP</span>` : '');
    const aiEntryStr = (af.entry_price && af.entry_price > 0) ? ` · Entry ₹${num(af.entry_price)}` : '';
    aiForecastHtml = afTargetHtml;
    if (isNoTrade) aiForecastHtml += `<div class="tf-ai-note">No trade setup. Directional estimate only.</div>`;
    aiForecastHtml += `<div class="tf-ai-forecast" style="color:${afColor}" title="${af.reasoning || 'AI directional forecast'}"><span class="fc-tag fc-tag-ai" title="AI directional forecast">AI</span>${buyChip}${afArrow} ${af.direction}${afRange}${afConf}${aiEntryStr}</div>`;
    if (af.reasoning) aiForecastHtml += `<div class="tf-ai-reason">${af.reasoning}</div>`;
  }

  const tfTarget = d.expected_target_price ?? d.min_target;
  const hasSl = d.stop_loss && tfTarget;
  const tgMet = hasSl && (d.actual_rr === undefined || d.actual_rr === null || d.actual_rr >= 1.5);
  const rrPct = hasSl && pickPrice > d.stop_loss
    ? Math.min(100, Math.max(2, (pickPrice - d.stop_loss) / (tfTarget - d.stop_loss) * 100)).toFixed(0)
    : 50;
  const entryLbl = d.entry_basis === 'est_open' ? 'Est. Open' : 'Entry';
  const isLiveEntry = d.entry_basis === 'live';
  const entryTitle = isLiveEntry
    ? 'Live intraday price — entry for a same-session trade'
    : `Based on previous close ₹${num(pickPrice)} — actual fill at next-day open`;
  // ML risk data for this TF. The ML model may have its own directional call even when the
  // AI side is a no-trade, so this block can render independently (keeps e.g. 3D from blanking).
  // (_mlData is computed near the top of this function so the AI banner can also use it.)
  const mlHasCall = _mlData && _mlData.direction && _mlData.direction !== 'N/A' && !_mlData.market_closed;
  const mlEntry = _mlData && (_mlData.buy_price_suggestion || _mlData.expected_entry_price);
  const mlTgt   = _mlData && _mlData.expected_target_price;
  const mlSL    = _mlData && _mlData.stop_loss;
  // R:R for the ML plan (same visual as the AI block): reward/risk multiple + a gradient bar
  // showing where entry sits between SL and target. Works for both long and short calls
  // because numerator and denominator flip sign together.
  const mlHasRr = mlHasCall && mlEntry && mlSL && mlTgt && (mlTgt - mlSL) !== 0 && (mlEntry - mlSL) !== 0;
  const mlRr = mlHasRr ? Math.abs((mlTgt - mlEntry) / (mlEntry - mlSL)) : null;
  const mlRrMet = mlRr !== null && mlRr >= 1.5;
  const mlRrPct = mlHasRr
    ? Math.min(100, Math.max(2, (mlEntry - mlSL) / (mlTgt - mlSL) * 100)).toFixed(0)
    : 50;
  const mlRiskBlock = (mlHasCall && mlEntry) ? `<div class="tf-ml-risk tf-risk ${mlHasRr ? (mlRrMet ? 'rr-ok' : 'rr-miss') : ''}" title="ML quantile model — buy-price / stop / median target (independent of the AI call)">
    <div class="tf-ml-risk-title">ML</div>
    <div class="tf-risk-row"><span class="tf-ml-risk-hdr">🤖 ML plan</span></div>
    <div class="tf-risk-row"><span class="tf-entry-lbl">Buy</span><span class="tf-entry-val">₹${num(mlEntry)}</span></div>
    ${mlSL ? `<div class="tf-risk-row"><span class="tf-sl-lbl">SL</span><span class="tf-sl-val">₹${num(mlSL)}</span></div>` : ''}
    ${mlTgt ? `<div class="tf-risk-row"><span class="tf-tgt-lbl">Tgt ${mlHasRr ? (mlRrMet ? '✓' : '⚠') : ''}${mlRr !== null ? ` ${mlRr.toFixed(1)}R` : ''}</span><span class="tf-tgt-val">₹${num(mlTgt)}</span></div>` : ''}
    ${mlHasRr ? `<div class="rr-bar"><div class="rr-bar-fill" style="width:${mlRrPct}%"></div></div>` : ''}
  </div>` : '';
  // No-trade cells (no signal, neutral, blocked, etc.) and range-only 1D calls have no
  // actionable AI entry/SL/target, so suppress the AI risk block — but still show the ML block
  // beneath when ML has its own call.
  const aiRiskBlock = (isNoTrade || isRangeBound) ? '' : `<div class="tf-risk ${hasSl ? (tgMet ? 'rr-ok' : 'rr-miss') : ''}">
    <div class="tf-risk-row"><span class="tf-entry-lbl" title="${entryTitle}">${entryLbl}${isLiveEntry ? ' <span style="opacity:.7">(live)</span>' : ''}</span><span class="tf-entry-val">₹${num(tfEntry)}</span></div>
    ${hasSl ? `<div class="tf-risk-row"><span class="tf-sl-lbl">SL</span><span class="tf-sl-val">₹${num(d.stop_loss)}</span></div>` : ''}
    ${hasSl ? `<div class="tf-risk-row"><span class="tf-tgt-lbl">Tgt ${tgMet ? '✓' : '⚠'}${d.actual_rr ? ` ${d.actual_rr}R` : ''}</span><span class="tf-tgt-val">₹${num(tfTarget)}</span></div>` : ''}
    ${hasSl ? `<div class="rr-bar"><div class="rr-bar-fill" style="width:${rrPct}%"></div></div>` : ''}
  </div>`;

  const isBestTf = bestTf !== null && (tf === bestTf);
  const _mlSlotInner = _mlData ? _renderMlRow(tf, _mlData) : '<div class="tf-ml-mini-loader">🤖 ML…</div>';
  const _aiDirAttr = (af && af.direction) ? af.direction : '';
  const _agreeInner = _agreeHtml(_mlData && _mlData.direction, _aiDirAttr, _mlData && _mlData.dir_basis);
  // Session's final INTRADAY call, shown after the market closes instead of a "market closed"
  // stub — it's the last real call made during the session, not a live prediction.
  const finalCallBadge = d.intraday_final_call
    ? `<div class="tf-final-call" title="NSE is closed — this was the last intraday call of the session${d.final_call_time ? ' (as of ' + d.final_call_time + ' IST)' : ''}">🕐 Final call${d.final_call_time ? ' · ' + d.final_call_time : ''}</div>`
    : '';
  // Pre-market INTRADAY preview: a pre-open directional lean, computed before the 09:15 bell.
  const premarketBadge = d.intraday_premarket
    ? `<div class="tf-final-call" title="Pre-market preview — a pre-open directional lean built before NSE opens at 09:15 IST. Refreshes live once the session starts.">🌅 Pre-market</div>`
    : '';
  // Target hit → the live price reached the previous intraday target, so the call was
  // re-evaluated for a fresh target off the new price level (not a stale/passed target).
  const reevalBadge = (tf === 'INTRADAY' && d.intraday_reevaluated)
    ? `<div class="tf-final-call tf-reeval" title="The live price reached the previous intraday target${d.prev_target ? ' (₹' + num(d.prev_target) + ')' : ''} — re-evaluated for a fresh target${d.reeval_time ? ' at ' + d.reeval_time + ' IST' : ''}.">🎯 target hit · re-evaluated${d.reeval_time ? ' · ' + d.reeval_time : ''}</div>`
    : '';
  return `<div class="tf-cell${isBestTf ? ' tf-cell--best' : ''}${d.intraday_final_call ? ' tf-cell--final' : ''}" id="tf-${safeId}-${tf}" data-ai-dir="${_aiDirAttr}">
    ${isBestTf ? '<span class="best-tf-badge">Best Bet</span>' : ''}
    <div class="tf-label">${tf === 'INTRADAY' ? 'Today' : tf}</div>
    ${finalCallBadge}
    ${premarketBadge}
    ${reevalBadge}
    <div class="tf-return" style="color:${isNoTrade ? 'var(--text-muted)' : retColor(d.midpoint||0)}">${retLabel}</div>
    ${noTradeDetail}
    ${priceRange}
    ${targetMid}
    ${gappedNote}
    ${dirHtml}
    ${mainConfBar}
    ${aiForecastHtml ? `<div class="tf-fc-block tf-ai-block">${aiForecastHtml}</div>` : ''}
    ${aiRiskBlock}
    <div class="tf-ai-ml-sep"><span class="tf-ai-ml-sep-lbl">🤖 ML MODEL</span></div>
    <div class="tf-ml-block"><div class="tf-ml-slot" id="ml-${safeId}-${tf}">${_mlSlotInner}</div></div>
    <div class="tf-agree-slot" id="agree-${safeId}-${tf}">${_agreeInner}</div>
    ${mlRiskBlock}
  </div>`;
}

// Fetch one TF for a watchlist card and update its cell in place (no full-card reload).
// Fetch one TF for a watchlist card and update its cell in place (no full-card reload).
// attempt: self-retry counter. A transient 'timeout' (a provider that is only per-minute
// rate-limited) is re-fetched after a short delay — single TF only, so it catches the
// provider reset WITHOUT re-bursting the whole watchlist the way a full reload would.
async function _fetchAndUpdateTfCell(ticker, tf, pick, attempt = 0, opts = {}) {
  const { silent = false, force = false } = opts;
  const safeId = ticker.replace(/[^a-zA-Z0-9]/g, '_');
  const cell = document.getElementById('tf-' + safeId + '-' + tf);
  if (!cell) return;

  const tfLabel = tf === 'INTRADAY' ? 'Today' : tf;
  // Keep the ML block in the loading cell (with its slot id) so the independent ML forecast
  // stays visible while the slow AI call is in flight — ML must never disappear behind AI.
  const _loadingCellHtml = `<div class="tf-label">${tfLabel}</div><div class="tf-cell-spinner">⟳</div>`
    + `<div style="font-size:11px;color:var(--text-muted);margin-top:4px">🤖 AI loading…</div>`
    + `<div class="tf-ai-ml-sep"><span class="tf-ai-ml-sep-lbl">🤖 ML MODEL</span></div>`
    + `<div class="tf-ml-block"><div class="tf-ml-slot" id="ml-${safeId}-${tf}"><div class="tf-ml-mini-loader">🤖 ML…</div></div></div>`;
  // Silent mode (periodic INTRADAY auto-refresh of an already-populated cell): DON'T paint the
  // loader — keep the current cell visible and swap it only once the fresh forecast arrives, so
  // the auto-refresh doesn't flash a spinner every few minutes.
  if (!silent) {
    cell.className = 'tf-cell tf-cell--loading';
    cell.innerHTML = _loadingCellHtml;
    _fetchAndFillMl(ticker, false, [tf]);  // keep ML visible during the AI fetch (cached → instant)
  }

  try {
    // force → append ?refresh=1 so the server bypasses its 15-min INTRADAY cache and re-runs the AI.
    const _url = '/api/watchlist-pick/' + encodeURIComponent(ticker) + '/' + tf + (force ? '?refresh=1' : '');
    const res = await fetch(_url, {cache: 'no-store'});
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `Server error ${res.status}`);
    const tfData = data.data || {};
    // Silent auto-refresh must never replace an already-good forecast with a transient
    // AI-unavailable/timeout placeholder — keep the current cell and retry on the next tick.
    const _silentReason = tfData.no_trade_reason;
    if (silent && (_silentReason === 'timeout' || _silentReason === 'ai_unavailable')) {
      if (attempt < _AI_RETRY_MAX) setTimeout(() => _fetchAndUpdateTfCell(ticker, tf, pick, attempt + 1, opts), 60000);
      return;
    }
    // Update cache so trade modal and retry button use fresh TF data
    const cached = _predictionCache.get(ticker);
    if (cached && cached.pick) cached.pick.timeframes[tf] = tfData;
    // Persist onto the pick object too so any later re-render from a stored snapshot
    // (e.g. the top-picks sort toggle, which re-renders from _lastTop5.picks) keeps this
    // resolved AI forecast instead of reverting to the stale "AI loading" cell.
    if (pick && pick.timeframes) pick.timeframes[tf] = tfData;
    // Merge into local pick snapshot for rendering.
    const updatedPick = Object.assign({}, pick, {
      timeframes: Object.assign({}, pick.timeframes, {[tf]: tfData}),
    });
    const tmp = document.createElement('div');
    tmp.innerHTML = _renderOneTfCell(tf, tfData, updatedPick);
    const newCell = tmp.firstElementChild;
    if (newCell) cell.replaceWith(newCell);
    _fetchAndFillMl(ticker, false, [tf]);  // refill only THIS cell's ML slot (cached → instant)
    // AI still loading (rate-limited / provider busy)? Keep retrying this single cell every
    // ~60s until a provider frees up — no terminal "AI unavailable". The ML forecast is
    // already shown beside it, so the card is never blocked. Targeted per-cell retry does
    // not touch the other cards/providers.
    const _r = tfData.no_trade_reason;
    if ((_r === 'timeout' || _r === 'ai_unavailable') && attempt < _AI_RETRY_MAX) {
      setTimeout(() => _fetchAndUpdateTfCell(ticker, tf, pick, attempt + 1, opts), 60000);
    }
  } catch(e) {
    // Silent auto-refresh must never surface an error or paint a loader — just leave the
    // existing cell as-is and try again on the next periodic tick.
    if (silent) return;
    // Network / server hiccup while fetching the AI forecast — keep retrying quietly
    // (the ML estimate is already shown), don't surface a terminal error.
    if (attempt < _AI_RETRY_MAX) {
      cell.className = 'tf-cell tf-cell--loading';
      cell.innerHTML = _loadingCellHtml;
      _fetchAndFillMl(ticker, false, [tf]);  // keep ML visible during the retry wait
      setTimeout(() => _fetchAndUpdateTfCell(ticker, tf, pick, attempt + 1, opts), 60000);
    } else {
      cell.className = 'tf-cell';
      cell.innerHTML = `<div class="tf-label">${tfLabel}</div><div class="tf-no-trade-reason" style="color:var(--text-muted);font-size:11px">🤖 AI still loading — tap ↺ to retry</div>`;
    }
  }
}

// ── ML forecast (standalone quantile model) — instant, local, no rate limits ──
// Each TF cell reserves a "ml-<safeId>-<tf>" slot; ML fills it as soon as one fast
// /api/ml-predict call resolves, while the AI row keeps its own (slower) loader.
const _mlCache = new Map();  // ticker -> /api/ml-predict result (all 3 TFs)
const _mlCacheTs = new Map();  // ticker -> Date.now() of last ML fetch
// INTRADAY must stay fresh (≤5 min), so the whole per-ticker ML payload is treated as stale
// after this window and refetched; 1D/3D are effectively cached between refreshes. A 5-min
// interval (below) also force-refreshes during market hours so INTRADAY is never cache-served
// longer than 5 minutes.
const _ML_CACHE_TTL_MS = 5 * 60 * 1000;

// Small muted ML status message (no forecast available) with an optional hover tooltip.
function _mlMsgHtml(msg, title = '') {
  return `<div class="tf-ml-mini-loader" style="color:var(--text-muted)" title="${(title || '').replace(/"/g, '&quot;')}">${msg}</div>`;
}

// Map an ml_predictor "unavailable" reason to a clear, human message (not a bare "n/a").
function _mlReasonMsg(reason) {
  const r = String(reason || '').toLowerCase();
  if (r.includes('insufficient') || r.includes('history')) return '🤖 ML: not enough price history';
  if (r.includes('ohlcv') || r.includes('fetch') || r.includes('data'))  return '🤖 ML: market data unavailable';
  if (r.includes('not loaded') || r.includes('artifacts') || r.includes('not trained')) return '🤖 ML model not loaded';
  if (r.includes('feature')) return '🤖 ML: feature build failed';
  if (r.includes('unknown timeframe')) return '🤖 ML: n/a for this horizon';
  return '🤖 ML unavailable';
}

// Decide what to render in one TF's ML slot from the full /api/ml-predict payload.
function _mlSlotHtml(tf, ml) {
  if (!ml)                    return _mlMsgHtml('🤖 ML unavailable');
  if (ml.available === false) return _mlMsgHtml(_mlReasonMsg(ml.error || ml.source), ml.error || '');
  const mlTf = (ml.tfs || {})[tf];
  if (!mlTf)                  return _mlMsgHtml('🤖 ML: no data for this horizon');
  if (mlTf.market_closed)     return _mlMsgHtml('🕐 Market closed — no intraday ML', 'NSE closed for the day (post 15:30 IST)');
  if (!mlTf.direction || mlTf.direction === 'N/A') return _mlMsgHtml('🤖 ML: no directional call');
  return _renderMlRow(tf, mlTf);
}

// Render the ML mini-row for one timeframe from an ml_predictor TF object.
// Mirrors the main cell layout (return range → price range → target → direction) so ML and
// the AI/main call read the same, plus a calibrated ML confidence bar in every timeframe.
function _renderMlRow(tf, ml) {
  if (!ml || !ml.direction || ml.direction === 'N/A') {
    if (ml && ml.market_closed) return _mlMsgHtml('🕐 Market closed — no intraday ML');
    return _mlMsgHtml('🤖 ML: no directional call');
  }
  const dir   = ml.direction;
  const color = dir === 'BULLISH' ? 'var(--green)' : dir === 'BEARISH' ? 'var(--red)' : 'var(--text-muted)';
  const arrow = dir === 'BULLISH' ? '▲' : dir === 'BEARISH' ? '▼' : '◆';
  // 1D/3D direction is trained on EXCESS-of-Nifty (alpha): BULLISH = outperform the market,
  // BEARISH = UNDERPERFORM it — NOT an absolute crash/rally. Relabel so a red "BEARISH" next to
  // an absolute -10% band doesn't read as a predicted crash. INTRADAY stays absolute.
  const relative = ml.dir_basis === 'vs_nifty';
  const dirLabel = relative
    ? (dir === 'BULLISH' ? 'OUTPERFORM' : dir === 'BEARISH' ? 'UNDERPERFORM' : 'IN-LINE')
    : dir;
  const basisTip = relative
    ? 'ML 1D/3D direction is measured vs Nifty (alpha): OUTPERFORM = expected to beat the market, UNDERPERFORM = expected to lag it. The ₹ range/target is the absolute modeled move if that relative call plays out — not a standalone crash/rally forecast.'
    : 'ML directional call';
  const basisChip = relative ? '<span class="tf-ml-note" title="Direction is relative to Nifty, not an absolute up/down forecast">vs Nifty</span>' : '';
  // The model's raw band is the q10–q90 (80%) prediction interval — deliberately wide.
  // For display we tighten it toward the MEDIAN (q50): halve the width on each side, centered
  // on the most-likely move. Backend keeps the full q10/q90 (backtests/validation read those).
  const q = ml.quantiles || {};
  // Center on the SAME expected move the headline target uses (from expected_target_price), NOT
  // the raw q50 — the raw median is uncapped/unscaled (INTRADAY scales it by ~0.42 + caps it), so
  // centering on it pushed the tightened low bound ABOVE the target, making Target read below the
  // range. Deriving medPct from expected_target_price keeps the target inside the shown band.
  const medFromTarget = (ml.expected_target_price && ml.current_price && ml.current_price > 0)
    ? (ml.expected_target_price / ml.current_price - 1) * 100 : null;
  const medPct = medFromTarget != null ? medFromTarget
    : (dir === 'BULLISH' ? q.up_q50 : dir === 'BEARISH' ? q.down_q50 : ml.midpoint);
  let nLo = ml.predicted_return_lo, nHi = ml.predicted_return_hi;
  if (medPct != null && nLo != null && nHi != null) {
    const lo = Math.min(nLo, nHi), hi = Math.max(nLo, nHi);
    nLo = medPct + 0.5 * (lo - medPct);
    nHi = medPct + 0.5 * (hi - medPct);
  }
  // Line 1: big return range — styled with the same visual weight as the AI/main return line.
  const rangeStr = (nLo != null && nHi != null) ? formatReturnRange(nLo, nHi, 1) : '';
  const retHtml = rangeStr
    ? `<div class="tf-ml-return" style="color:${color}" title="ML predicted return range">${rangeStr}</div>` : '';
  // Line 1b: ₹ price range — mirrors the AI's ₹ target range. Derived from the SAME tightened
  // band shown just above (nLo/nHi) applied to the model's current price, so the ₹ range and the
  // % range always agree. Shown for range-bound calls too (the flat ±1% band as a ₹ "stays
  // within" range), exactly like the AI ₹ range.
  const _mlCp = ml.current_price;
  let rupeeRangeHtml = '';
  if (_mlCp && _mlCp > 0 && nLo != null && nHi != null) {
    const _rA = _mlCp * (1 + nLo / 100), _rB = _mlCp * (1 + nHi / 100);
    rupeeRangeHtml = `<div class="tf-ai-target" style="color:${color}" title="ML predicted price range (₹) — same band as the % range above">₹${num(Math.min(_rA, _rB), 0)} – ₹${num(Math.max(_rA, _rB), 0)}</div>`;
  }
  // Line 2: headline MEDIAN (most-likely) target price.
  // NEUTRAL / range-bound calls have no directional target (backend sends expected_target_price
  // = null + range_bound = true) — show "Range-bound" instead of a target == current price.
  const medPrice = ml.expected_target_price;
  const tgtTitle = relative
    ? 'Absolute modeled price if the relative (vs-Nifty) call plays out — not a guaranteed move'
    : 'ML expected (median) target price';
  const priceHtml = (ml.range_bound || dir === 'NEUTRAL')
    ? `<div class="tf-mid-target tf-range-bound" title="ML expects the price to stay range-bound — no directional target, no buy price">Range-bound · no buy</div>`
    : ((medPrice && medPrice > 0)
        ? `<div class="tf-mid-target" title="${tgtTitle}">Target ₹${num(medPrice, 0)}</div>` : '');
  // Line 3: direction row (dot + arrow + label) — mirrors the AI direction row.
  const note = (tf === 'INTRADAY' && dir === 'BULLISH')
    ? '<span class="tf-ml-note" title="INTRADAY ML is a direction/range signal, not a standalone long">signal</span>' : '';
  // INTRADAY: if the modeled high has ALREADY been reached this session, flag it so the
  // target isn't mistaken for a fresh entry (the "price already passed" case).
  const gone = (tf === 'INTRADAY' && ml.intraday && ml.intraday.already_gone)
    ? '<span class="tf-ml-note tf-ml-gone" title="The modeled intraday high has already been reached this session — little/no headroom left">high reached</span>' : '';
  // Target hit → the live price reached the previous ML target, so the model was re-evaluated
  // for a fresh target off the new price level (mirrors the AI "target hit → re-evaluate").
  const reeval = (tf === 'INTRADAY' && ml.reevaluated)
    ? `<span class="tf-ml-note tf-ml-reeval" title="The live price reached the previous ML target${ml.prev_target ? ' (₹' + num(ml.prev_target) + ')' : ''} — re-evaluated for a fresh target${ml.reeval_time ? ' at ' + ml.reeval_time + ' IST' : ''}">🎯 re-evaluated</span>` : '';
  // NEUTRAL / range-bound: no buy price and no directional edge — make it explicit that this
  // is not a trade (the "ML says no price" case) with a clear "no trade" tag.
  const hold = (ml.range_bound || dir === 'NEUTRAL')
    ? '<span class="tf-ml-note tf-ml-hold" title="ML sees no directional edge — no buy price, do not trade">no trade</span>' : '';
  // Rare high-conviction flag: the model's calibrated probability is in the empirically-reliable
  // tail (~85%+ OOS direction accuracy for this TF). Fires seldom by design — a precision badge.
  const hiConv = (ml.high_conviction && dir !== 'NEUTRAL')
    ? '<span class="tf-ml-note tf-ml-hiconv" title="Rare high-conviction call — model probability is in the ~85%+ reliable zone for this timeframe">⭐ high-conviction</span>' : '';
  // Recently-listed / IPO guard: fewer than ~1 trading year of bars means the stock is outside
  // the model's training distribution (long-window features + calibrated confidence unreliable),
  // so the call is capped and flagged so it isn't over-trusted.
  const lowHist = ml.low_history
    ? `<span class="tf-ml-note tf-ml-gone" title="Only ${ml.low_history_bars || '<250'} trading days of history (recently listed / IPO) — outside the model's training range, so this is extrapolated. Treat as low-confidence.">⚠ limited history</span>` : '';
  const dirClass = dir.replace(/\s+/g, '-');
  const dirHtml = `<div class="tf-dir-row"><span class="dir-dot dir-dot-${dirClass}"></span><span class="tf-dir" style="color:${color};font-weight:600" title="${basisTip}">${arrow} ${dirLabel}${note}${gone}${reeval}${hold}${hiConv}${lowHist}${basisChip}</span></div>`;
  // Line 4: calibrated confidence — same bar visual as the AI confidence bar, labeled "ML conf".
  let conf = (ml.confidence || '').toUpperCase();
  if (!conf && ml.confidence_prob != null) {
    const p = ml.confidence_prob;
    conf = p >= 0.66 ? 'HIGH' : p >= 0.5 ? 'MEDIUM' : 'LOW';
  }
  const cl = conf.toLowerCase();
  const _confPct = c => c === 'HIGH' ? 90 : c === 'MEDIUM' ? 55 : c === 'LOW' ? 25 : 0;
  const confPctTitle = (ml.confidence_prob != null) ? ` (${Math.round(ml.confidence_prob * 100)}%)` : '';
  const confHtml = conf
    ? `<div class="tf-conf-row" title="ML calibrated confidence: ${conf}${confPctTitle}"><span class="tf-conf-lbl">ML conf</span><div class="conf-bar"><div class="conf-bar-fill conf-${cl}" style="width:${_confPct(conf)}%"></div></div><span class="tf-conf-val conf-${cl}">${conf}</span></div>`
    : '';
  return `${retHtml}${rupeeRangeHtml}${priceHtml}${dirHtml}${confHtml}`;
}

// Agreement badge between the ML and AI directional calls.
// `mlBasis` = ML's direction basis ('vs_nifty' for 1D/3D excess-labels, else absolute). When
// ML is relative-to-Nifty and AI is an absolute call, they measure DIFFERENT things, so a
// direction mismatch is NOT a contradiction (a stock can rise yet lag the market) — show a
// neutral "different axes" note instead of a scary "⚠ ML / AI split".
function _agreeHtml(mlDir, aiDir, mlBasis) {
  if (!mlDir || !aiDir) return '';
  const m = String(mlDir).toUpperCase(), a = String(aiDir).toUpperCase();
  if (m === 'N/A' || a === 'N/A') return '';
  const dirM = (m === 'BULLISH' || m === 'BEARISH');
  const dirA = (a === 'BULLISH' || a === 'BEARISH');
  const relative = mlBasis === 'vs_nifty';
  if (dirM && dirA) {
    if (m === a) return relative
      ? `<div class="tf-agree tf-agree-yes" title="ML expects it to ${m === 'BULLISH' ? 'outperform' : 'underperform'} Nifty and AI agrees on absolute direction">✓ ML + AI aligned</div>`
      : `<div class="tf-agree tf-agree-yes" title="ML and AI agree on direction — strongest signal">✓ ML + AI agree</div>`;
    // Relative ML vs absolute AI — different axes, not a real contradiction.
    if (relative)
      return `<div class="tf-agree tf-agree-soft" title="ML rates it ${m === 'BULLISH' ? 'OUTPERFORM' : 'UNDERPERFORM'} vs Nifty (relative), while AI gives an absolute ${a} call — different axes, a stock can rise yet lag the market">◐ ML (vs Nifty) / AI (absolute)</div>`;
    return `<div class="tf-agree tf-agree-no" title="ML and AI disagree on direction">⚠ ML / AI split</div>`;
  }
  // Exactly one side has a directional call, the other is NEUTRAL — a milder divergence
  // (weak / mixed signal), still worth flagging so it isn't mistaken for agreement.
  if (dirM || dirA)
    return `<div class="tf-agree tf-agree-soft" title="One model sees a direction, the other is neutral — weak / mixed signal">◐ ML / AI differ</div>`;
  // Both NEUTRAL — they agree there is no directional edge.
  return `<div class="tf-agree tf-agree-yes" title="ML and AI agree — both see no directional edge">✓ ML + AI agree</div>`;
}

// Fetch ML predictions for a ticker (one call = all TFs) and fill each cell's ML slot.
// INTRADAY is never served from cache for longer than _ML_CACHE_TTL_MS (5 min); 1D reuses
// the cached payload within that window. Pass force=true to bypass the cache entirely.
// `tfs` limits WHICH slots get repainted — the periodic 5-min refresh passes ['INTRADAY'] so
// only the intraday slot repaints (1D stays put; no full-card flicker).
async function _fetchAndFillMl(ticker, force = false, tfs = ['INTRADAY', '1D']) {
  if (!ticker) return;
  const safeId = ticker.replace(/[^a-zA-Z0-9]/g, '_');
  try {
    let ml = _mlCache.get(ticker);
    const age = Date.now() - (_mlCacheTs.get(ticker) || 0);
    const stale = age > _ML_CACHE_TTL_MS;  // INTRADAY freshness window
    if (!ml || force || stale) {
      const res = await fetch('/api/ml-predict/' + encodeURIComponent(ticker) + '?archive=1', { cache: 'no-store' });
      ml = await res.json();
      // Always cache the payload — even when NSE is closed. The ML row (especially 1D/3D,
      // which don't move while the market is shut) must render instantly from cache on every
      // re-render, otherwise each AI-retry rebuild regenerates the '🤖 ML…' placeholder and the
      // ML forecast appears stuck/hung behind the slow AI call. INTRADAY freshness is preserved
      // by the 5-min stale window and the market-hours refresh tick, which refetch the INTRADAY
      // slot once the session is live again.
      if (ml) {
        _mlCache.set(ticker, ml);
        _mlCacheTs.set(ticker, Date.now());
      }
    }
    tfs.forEach(tf => _fillMlSlot(safeId, tf, ml));
  } catch (e) {
    tfs.forEach(tf => {
      const slot = document.getElementById('ml-' + safeId + '-' + tf);
      if (slot) slot.innerHTML = _mlMsgHtml('🤖 ML: request failed', String(e && e.message || e));
    });
  }
}

function _fillMlSlot(safeId, tf, ml) {
  const slot = document.getElementById('ml-' + safeId + '-' + tf);
  if (slot) slot.innerHTML = _mlSlotHtml(tf, ml);
  const mlTf = (ml && ml.available && ml.tfs) ? ml.tfs[tf] : null;
  const cell  = document.getElementById('tf-' + safeId + '-' + tf);
  const agree = document.getElementById('agree-' + safeId + '-' + tf);
  if (agree) agree.innerHTML = _agreeHtml(mlTf && mlTf.direction, cell ? cell.dataset.aiDir : '', mlTf && mlTf.dir_basis);
}

// ── Render: Pick Card (Top 5) ─────────────────────────────────────────────────
// ML-based recommendation fallback: pick the ML model's strongest directional call
// (BULLISH/BEARISH, confidence-tier-first) across INTRADAY/1D. Used when the AI produced
// no actionable "best timeframe" (all AI cells N/A) so the card can still recommend a trade.
function _mlBestTf(ticker) {
  const ml = _mlCache.get(ticker);
  if (!ml || !ml.available || !ml.tfs) return null;
  const rank = { HIGH: 3, MEDIUM: 2, LOW: 1 };
  let best = null, bestKey = -1;
  ['INTRADAY', '1D'].forEach(tf => {
    const d = ml.tfs[tf];
    if (!d || d.market_closed) return;
    if (d.direction !== 'BULLISH' && d.direction !== 'BEARISH') return;  // need a directional call
    const conf = String(d.confidence || '').toUpperCase();
    const tfWeight = tf === 'INTRADAY' ? 2 : 1;  // prefer the intraday horizon
    const key = (rank[conf] || 0) * 10 + tfWeight;
    if (key > bestKey) { bestKey = key; best = tf; }
  });
  return best;
}

function renderPickCard(pick, idx, idPrefix = 'pick', mode = 'top5') {
  const dir   = pick.direction || 'NEUTRAL';
  const isUp  = dir.includes('BULLISH');
  const cls   = isUp ? 'bullish' : dir.includes('BEARISH') ? 'bearish' : '';
  const tfs   = pick.timeframes || {};
  const tvId  = 'tv-' + idPrefix + '-' + pick.ticker.replace(/[^a-zA-Z0-9]/g, '_');
  const news  = pick.news || {};
  _newsDataCache[pick.ticker] = news;
  const risk  = pick.risk || {};
  const signals = pick.signals || {};
  const warning = pick.warning || '';

  const pickPrice = pick.price || 0;
  let bestTf         = pick.best_tf || null;
  // Recommendation source: AI by default; if the AI produced no actionable best timeframe
  // (all AI cells N/A), fall back to the ML model's strongest directional call.
  let recSource = bestTf ? 'ai' : null;
  let slBest, tgtBest, planDataBestJSON;
  if (!bestTf) {
    const mlTf = _mlBestTf(pick.ticker);
    if (mlTf) {
      bestTf = mlTf;
      recSource = 'ml';
      pick.best_tf = mlTf;  // so the TF cell shows the "Best Bet" badge on the ML pick
      const mld = (_mlCache.get(pick.ticker) || {}).tfs?.[mlTf] || {};
      slBest  = mld.stop_loss || 0;
      tgtBest = mld.expected_target_price || Math.max(mld.target_price_lo || 0, mld.target_price_hi || 0) || 0;
      planDataBestJSON = JSON.stringify({
        timeframe: mlTf,
        direction: mld.direction,
        confidence: mld.confidence,
        expected_entry_price: mld.buy_price_suggestion || mld.current_price || pickPrice,
        stop_loss: mld.stop_loss,
        expected_target_price: mld.expected_target_price,
        target_price_lo: mld.target_price_lo,
        target_price_hi: mld.target_price_hi,
        source: 'ml',
      }).replace(/'/g, "&#39;");
    }
  }
  if (recSource !== 'ml') {
    slBest  = (tfs[bestTf] || {}).stop_loss || 0;
    tgtBest = (tfs[bestTf] || {}).expected_target_price || (tfs[bestTf] || {}).min_target || 0;
    planDataBestJSON = JSON.stringify(Object.assign({}, tfs[bestTf] || {}, { timeframe: bestTf })).replace(/'/g, "&#39;");
  }

  // HIGH-conviction = the best actionable timeframe carries HIGH confidence.
  // Backtest: HIGH-conf directional calls hit 95-97% and are the profit bucket.
  const _bestConf = ((tfs[bestTf] || {}).confidence || '').toUpperCase();
  const _bestDir  = ((tfs[bestTf] || {}).direction || '').toUpperCase();
  const _actionable = ['BULLISH','BEARISH','SLIGHTLY BULLISH','SLIGHTLY BEARISH'].includes(_bestDir);
  const isHighConviction = _bestConf === 'HIGH' && _actionable;
  const convictionBadge = isHighConviction
    ? `<span class="conviction-badge" title="Best timeframe (${bestTf}) is HIGH confidence — backtest 95-97% price-hit bucket">⭐ HIGH CONVICTION</span>`
    : '';

  // Retry button: shown when any TF timed out or AI was unavailable (watchlist only)
  const _retryReasons = new Set(['timeout', 'ai_unavailable']);
  const _hasRetryable = mode === 'watchlist' && ['INTRADAY','1D'].some(tf => {
    const r = (tfs[tf] || {}).no_trade_reason;
    return _retryReasons.has(r);
  });
  const retryBtn = _hasRetryable
    ? `<button class="card-retry-btn" onclick="retryWatchlistCard('${pick.ticker}',this)">↺ Retry</button>`
    : '';
  // ML-selection verdict: was this stock chosen by the ML selector, and did AI confirm?
  let mlVerdictBadge = '';
  if (pick.ml_selected) {
    if (pick.ml_ai_verdict === 'confirmed')
      mlVerdictBadge = `<span class="ml-verdict ml-verdict-ok" title="ML selected this stock and AI confirmed the direction">⭐ ML pick · AI confirmed</span>`;
    else if (pick.ml_ai_verdict === 'disagree')
      mlVerdictBadge = `<span class="ml-verdict ml-verdict-bad" title="ML selected this stock but AI disagrees on direction — trade with caution">⚠ ML pick · AI disagrees</span>`;
    else
      mlVerdictBadge = `<span class="ml-verdict ml-verdict-neutral" title="Surfaced by the ML selector">🤖 ML pick</span>`;
  }
  const tfHtml = ['INTRADAY','1D'].map(tf => _renderOneTfCell(tf, tfs[tf] || {}, pick)).join('');

  const safeCompany = (pick.company || '').replace(/'/g, "\\'");
  const headerLeft = mode === 'watchlist'
    ? ''
    : `<span class="pick-rank">${idx + 1}</span>`;
  const recTfLabel = bestTf ? (bestTf === 'INTRADAY' ? 'Today' : bestTf) : 'N/A';
  const recLabel = bestTf
    ? `Recommended: ${recTfLabel}${recSource === 'ml' ? ' · 🤖 ML' : ''}`
    : 'Recommended: N/A';
  const recTitle = recSource === 'ml'
    ? 'AI forecast unavailable — recommendation from the ML model'
    : 'Best timeframe from the AI forecast';
  const actionBtns = mode === 'watchlist'
    ? `<button class="btn-danger btn-sm" onclick="removeFromWatchlist('${pick.ticker}')">✕ Remove</button>
       <button class="btn-primary btn-sm" title="${recTitle}" onclick='openTradeModal(${JSON.stringify(pick.ticker)},${JSON.stringify(safeCompany)},${pick.price||0},${slBest},${tgtBest},${planDataBestJSON})'>${recLabel}</button>`
    : `<button class="btn-ghost btn-sm" onclick="addToWatchlist('${pick.ticker}','${safeCompany}')">+ Watch</button>
       <button class="btn-primary btn-sm" onclick='openTradeModal(${JSON.stringify(pick.ticker)},${JSON.stringify(safeCompany)},${pick.price||0},${slBest},${tgtBest},${planDataBestJSON})'>Trade</button>`;

  const bareSym  = pick.ticker.replace(/\.(NS|BO)$/i, '');
  const exchange = pick.ticker.endsWith('.BO') ? 'BSE' : 'NSE';

  const aiDirs = ['INTRADAY', '1D']
    .map(tf => ((tfs[tf] || {}).ai_forecast || {}).direction)
    .filter(d => d === 'BULLISH' || d === 'BEARISH');
  const aiConsensus = aiDirs[0] || null;
  const newsSentimentLabel = (label) => {
    if (label === 'BULLISH') return 'POSITIVE';
    if (label === 'BEARISH') return 'NEGATIVE';
    if (label === 'NEUTRAL') return 'NEUTRAL';
    return 'N/A';
  };
  const newsSentiment = newsSentimentLabel(news.label);
  const hasNewsAiDivergence = !!(news.label && aiConsensus &&
    ((news.label === 'BULLISH' && aiConsensus === 'BEARISH') ||
     (news.label === 'BEARISH' && aiConsensus === 'BULLISH')));
  // Show softer note when news is directional but AI sees mixed/neutral technicals
  const hasNeutralVsStrongNews = !aiConsensus && news.label && news.label !== 'NEUTRAL';
  const divergenceHtml = hasNewsAiDivergence
    ? `<div class="news-ai-divergence">News sentiment is ${newsSentiment.toLowerCase()} while AI direction is ${aiConsensus.toLowerCase()}. AI also uses trend, momentum, and volatility signals.</div>`
    : hasNeutralVsStrongNews
      ? `<div class="news-ai-divergence" style="opacity:0.75">News signal is <strong>${newsSentiment.toLowerCase()}</strong> but AI sees mixed technical signals — no clear directional edge.</div>`
      : '';

  const aiTfDir = (tf) => ((tfs[tf] || {}).ai_forecast || {}).direction || 'N/A';
  const aiTfColor = (d) => d === 'BULLISH' ? 'var(--green)' : d === 'BEARISH' ? 'var(--red)' : 'var(--text-muted)';
  const aiToday = aiTfDir('INTRADAY');
  const ai1d = aiTfDir('1D');
  const wlSummaryHtml = mode === 'watchlist'
    ? `<div class="wl-summary-grid">
        <div class="wl-summary-item">
          <div class="wl-summary-label">Current Price</div>
          <div class="wl-summary-value">₹${num(pickPrice)}</div>
        </div>
        <div class="wl-summary-item">
          <div class="wl-summary-label">AI (Today)</div>
          <div class="wl-summary-value" style="color:${aiTfColor(aiToday)}">${aiToday}</div>
        </div>
        <div class="wl-summary-item">
          <div class="wl-summary-label">AI (1D)</div>
          <div class="wl-summary-value" style="color:${aiTfColor(ai1d)}">${ai1d}</div>
        </div>
        <div class="wl-summary-item" style="cursor:pointer" onclick="showNewsModal('${pick.ticker}')" title="Click to see latest headlines">
          <div class="wl-summary-label">📰 News</div>
          <div class="wl-summary-value" style="color:${news.label === 'BULLISH' ? 'var(--green)' : news.label === 'BEARISH' ? 'var(--red)' : 'var(--text-muted)'}">${newsSentiment}</div>
        </div>
      </div>`
    : '';

  const identityBlock = `
    <div class="pick-identity">
      ${pick.company ? `<div class="pick-name">${pick.company}</div>` : ''}
      <div class="pick-symbol-row">
        <span class="pick-symbol">${bareSym}</span>
        <span class="pick-exchange">${exchange}</span>
        ${pick.price ? `<span class="pick-price-badge">₹${num(pick.price)}</span>` : ''}
      </div>
    </div>`;

  if (pick.direction === 'ERROR') {
    return `<div class="pick-card bearish">
      <div class="pick-header">
        ${headerLeft}
        ${identityBlock}
        <div class="pick-actions">${mode === 'watchlist' ? `<button class="btn-danger btn-sm" onclick="removeFromWatchlist('${pick.ticker}')">✕ Remove</button>` : ''}</div>
      </div>
      <div style="padding:16px 20px"><div class="error-card">${pick.error || 'Data unavailable'}<br><span style="font-size:11px;color:var(--text-muted)">${(pick.error || '').includes('All data sources failed') ? 'Symbol may be delisted or renamed — try removing and searching for the correct ticker.' : 'Predictions unavailable — historical data may be insufficient for this ticker.'}</span></div></div>
    </div>`;
  }

  return `
    <div class="pick-card ${cls}" data-conviction="${isHighConviction ? 'high' : 'normal'}" data-ticker="${pick.ticker}">
      <div class="pick-header">
        ${headerLeft}
        ${identityBlock}
        <div class="pick-actions">
          ${actionBtns}
        </div>
      </div>
      <div class="pick-body">
        <div class="pick-signals">
          ${convictionBadge}
          ${mlVerdictBadge}
          ${wlSummaryHtml}
          <div class="tf-grid">${tfHtml}</div>
          ${retryBtn}
          <div class="pick-meta">
            <span class="conf-pill conf-${news.label === 'BULLISH' ? 'HIGH' : news.label === 'BEARISH' ? 'LOW' : 'MEDIUM'}" style="cursor:pointer" onclick="showNewsModal('${pick.ticker}')" title="Click to see latest headlines">📰 News${news.label ? ` · ${newsSentiment}` : ''}</span>
            ${hasNewsAiDivergence ? '<span class="conf-pill conf-MEDIUM">News/AI Divergence</span>' : ''}
            <span class="conf-pill ${confClass(pick.confidence)}">${pick.confidence}</span>
          </div>
          ${(() => {
            const _hl = _latestHeadline(news);
            if (!_hl && !news.summary) return '';
            const _hlDate = _fmtNewsDate(_hl && _hl.date);
            return `<div class="news-block" style="margin-top:12px;cursor:pointer" onclick="showNewsModal('${pick.ticker}')" title="Click to see latest headlines">
              ${_hl ? `<div class="news-headline" style="font-size:11px;color:var(--text-muted);margin-bottom:4px;font-style:italic">📰 ${_hl.title}${_hlDate ? ` <span style="font-style:normal;opacity:.75">· ${_hlDate}</span>` : ''}</div>` : ''}
              ${news.summary ? `<div class="news-sum">${news.summary}</div>` : ''}
              <div style="font-size:10px;color:var(--text-dim);margin-top:4px">Tap for full news →</div>
            </div>`;
          })()}
          ${warning ? `<div class="news-ai-divergence">Prediction unavailable for one or more timeframes: ${warning}</div>` : ''}
          ${divergenceHtml}
        </div>
        <div class="pick-chart">
          <div class="tv-chart-container" id="${tvId}"></div>
        </div>
      </div>
    </div>`;
}

function renderWatchlistShellCard(item) {
  const ticker = (item.ticker || '').toUpperCase();
  const { sym, exch, name } = tickerMeta(ticker);
  const fallbackName = item.name || name || sym;
  const cardId = 'wl-card-' + ticker.replace(/[^a-zA-Z0-9]/g, '_');
  const chartId = 'tv-wl-' + ticker.replace(/[^a-zA-Z0-9]/g, '_');
  const safeId = ticker.replace(/[^a-zA-Z0-9]/g, '_');
  const safeName = (fallbackName || '').replace(/'/g, "\\'");
  // Shell TF grid: ML slots are painted immediately so the instant, local ML forecast
  // can fill in without waiting for the slow per-card AI (/api/watchlist-pick) call.
  const shellTfHtml = ['INTRADAY', '1D'].map(tf => `
    <div class="tf-cell tf-cell--loading" id="tf-${safeId}-${tf}" data-ai-dir="">
      <div class="tf-label">${tf === 'INTRADAY' ? 'Today' : tf}</div>
      <div class="tf-fc-block tf-ml-block"><div class="tf-ml-slot" id="ml-${safeId}-${tf}"><div class="tf-ml-mini-loader">🤖 ML…</div></div></div>
      <div class="tf-agree-slot" id="agree-${safeId}-${tf}"></div>
      <div class="tf-fc-block tf-ai-block"><div class="tf-ai-note" style="color:var(--text-muted)">🤖 AI forecast loading…</div></div>
    </div>`).join('');
  return `<div class="pick-card pick-card--loading" id="${cardId}" data-ticker="${ticker}">
    <div class="pick-header">
      <div class="pick-identity">
        <div class="pick-name">${fallbackName}</div>
        <div class="pick-symbol-row">
          <span class="pick-symbol">${sym}</span>
          <span class="pick-exchange">${exch}</span>
        </div>
      </div>
      <div class="pick-actions">
        <button class="btn-danger btn-sm" onclick="removeFromWatchlist('${ticker}')">✕ Remove</button>
        <button class="btn-primary btn-sm" onclick="openTradeModal('${ticker}','${safeName}',0,0,0)">Trade</button>
      </div>
    </div>
    <div class="pick-body">
      <div class="pick-signals">
        <div class="tf-grid">${shellTfHtml}</div>
      </div>
      <div class="pick-chart">
        <div class="tv-chart-container" id="${chartId}"></div>
      </div>
    </div>
  </div>`;
}

// ── Render: Rank Table ────────────────────────────────────────────────────────
function renderRankTable(data) {
  if (!data || !data.ranked) return '<div class="error-card">No ranking data returned.</div>';

  const capital = data.capital;
  const ranked  = data.ranked || [];
  const buys    = ranked.filter(r => !['BEARISH','SLIGHTLY BEARISH','NO TRADE','BLOCKED'].includes(r.direction));
  const bears   = ranked.filter(r => ['BEARISH','SLIGHTLY BEARISH'].includes(r.direction));
  const blocked = ranked.filter(r => ['NO TRADE','BLOCKED'].includes(r.direction));

  function renderSection(title, titleCls, rows) {
    if (!rows.length) return '';
    const colsHtml = `<tr>
      <th>#</th><th>Stock</th><th>Confidence</th><th>Expected Return</th>
      <th>ML</th><th>News</th>
      ${capital ? '<th>Allocation</th>' : ''}
      <th></th>
    </tr>`;
    const rowsHtml = rows.map(r => {
      const mid     = r.midpoint || 0;
      const signals = r.active_strategies || [];
      const mlScore = (r.ml || {}).score || 0;
      const news    = (r.news || {}).label || 'NEUTRAL';
      const earnBadge = (r.earnings || {}).in_blackout ? '<span class="dir-badge dir-BLOCKED" style="font-size:9px">BLACKOUT</span>' : '';
      const allocCell = capital && r.suggested_allocation
        ? `₹${num(r.suggested_allocation)} · ${r.suggested_shares}sh`
        : '—';
      return `<tr>
        <td class="rank-num">${r.rank}</td>
        <td>${stockCell(r.ticker)}</td>
        <td><span class="conf-pill ${confClass(r.confidence)}">${r.confidence}</span></td>
        <td class="rank-ret" style="color:${retColor(mid)}">${r.expected_return_range||'N/A'}</td>
        <td>
          <div class="ml-mini">
            <div class="ml-mini-bar"><div class="ml-mini-fill" style="width:${mlScore}%"></div></div>
            <span class="ml-mini-score">${mlScore}</span>
          </div>
        </td>
        <td><span class="dir-badge ${dirClass(news)}">${news}</span> ${earnBadge}</td>
        ${capital ? `<td style="font-size:11px;color:var(--text-muted)">${allocCell}</td>` : ''}
        <td>
          <button class="btn-primary btn-sm" onclick='openTradeModal(${JSON.stringify(r.ticker)},${JSON.stringify(r.company||"")},${r.price||0},${(r.risk||{}).stop_loss||0},${r.expected_target_price||0},${JSON.stringify({strategy:(r.active_strategies||[])[0]||null,timeframe:r.timeframe||null,max_chase_pct:(r.trade_plan||{}).max_chase_pct||null,prediction_data:{ml:r.ml||{},news:r.news||{},ai:r.ai_forecast?{direction:r.ai_forecast.direction,confidence:r.ai_forecast.confidence}:{},market:r.market||{}}})})'>Trade</button>
        </td>
      </tr>`;
    }).join('');
    return `<div class="rank-section">
      <div class="rank-section-title ${titleCls}">${title} (${rows.length})</div>
      <table class="rank-table">${colsHtml}<tbody>${rowsHtml}</tbody></table>
    </div>`;
  }

  return renderSection('Recommended Buys', 'good', buys)
       + renderSection('Avoid', 'bad', bears)
       + renderSection('Blocked (VIX/Macro)', 'warn', blocked);
}

// ── Shared helpers ────────────────────────────────────────────────────────────
function num(n, decimals = 2) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function pnlClass(val) {
  if (val > 0) return 'pnl-pos';
  if (val < 0) return 'pnl-neg';
  return 'pnl-zero';
}

function showEl(id) { const e = document.getElementById(id); if (e) { e.classList.remove('hidden'); } }
function hideEl(id) { const e = document.getElementById(id); if (e) { e.classList.add('hidden'); } }

// ── Dashboard ─────────────────────────────────────────────────────────────────
async function loadDashboard() {
  // Top 5 preview — kick off immediately so it runs in parallel with portfolio/trades fetches
  const cardsEl = document.getElementById('dash-top5-cards');
  if (!cardsEl.hasAttribute('data-loaded') || cardsEl.querySelectorAll('.pick-card').length === 0) {
    loadTop5Cards('dash-top5-cards', 'dash-top5-loading', 20);
  }

  // Portfolio summary
  try {
    const res  = await fetch('/api/portfolio', { cache: 'no-store' });
    const data = await res.json();
    const pnlCls = pnlClass(data.closed_pnl);
    document.getElementById('ds-open').textContent    = data.open_count ?? '0';
    document.getElementById('ds-invested').textContent = '₹' + num(data.total_invested);
    document.getElementById('ds-pnl').innerHTML       = `<span class="${pnlCls}">${data.closed_pnl > 0 ? '+' : ''}₹${num(data.closed_pnl)}</span>`;
    document.getElementById('ds-winrate').textContent  = data.win_rate + '%';
    document.getElementById('ds-total').textContent    = data.total_trades ?? '0';
  } catch (e) { console.warn(e); } finally { dismissLoader(); }

  // Open trades mini + unrealised P&L strip card
  try {
    const res    = await fetch('/api/trades/open', { cache: 'no-store' });
    const data   = await res.json();
    const trades = data.trades || [];
    const el     = document.getElementById('dash-open-trades');
    el.innerHTML = renderOpenTradesMini(trades);

    const totalUnrealised = trades.reduce((sum, t) => sum + (t.unrealised_pnl ?? 0), 0);
    const uEl = document.getElementById('ds-unrealised');
    if (uEl) {
      const cls = pnlClass(totalUnrealised);
      uEl.innerHTML = `<span class="${cls}">${totalUnrealised >= 0 ? '+' : ''}₹${num(totalUnrealised)}</span>`;
    }
  } catch (e) { console.warn(e); }

}

document.getElementById('dash-refresh-top5')?.addEventListener('click', () => {
  const cardsEl = document.getElementById('dash-top5-cards');
  cardsEl.removeAttribute('data-loaded');
  cardsEl.innerHTML = '';
  loadTop5Cards('dash-top5-cards', 'dash-top5-loading', 20, true);
});

// ── Top 5 view ────────────────────────────────────────────────────────────────
let _top5PollCount = 0;
let _top5PollTimer = null;
let _top5AutoRetried = false;  // tracks one-shot auto-retry when cached result is empty
let _top5PollStart = 0;        // epoch ms of the first poll — used for the elapsed-time cap
const _top5AiRetried = new Set();  // 'ticker|tf' cells that already have a background AI retry running

// Render top-pick cards into a container and mount their mini charts.
// Shared by the final render and the streaming (partial) render.
function _renderTop5CardsInto(cardsEl, idPrefix, picks, bannerHtml = '') {
  _lastTop5 = { cardsEl, idPrefix, picks, banner: bannerHtml };
  const ordered = _applyTop5Sort(picks);
  // Preserve already-mounted chart nodes across re-renders. Streaming polls this every ~4s and
  // the sort toggle re-renders too; a naive innerHTML rebuild tore down + remounted every live
  // chart each time, causing visible blinking. Stash each mounted chart's wrapper by ticker id
  // and splice it back into the fresh (empty) slot instead of remounting.
  const chartStash = {};
  ordered.forEach(p => {
    const tvId = 'tv-' + idPrefix + '-' + p.ticker.replace(/[^a-zA-Z0-9]/g, '_');
    const existing = document.getElementById(tvId);
    if (existing && existing.dataset.chartMounted) {
      chartStash[tvId] = existing.closest('.chart-wrap') || existing;
    }
  });
  const sortBar = `<div class="top5-sort-bar">
    <span class="top5-sort-lbl">Rank by</span>
    ${[['ai','AI'],['ml','🤖 ML'],['blend','Blend']].map(([m,l]) =>
      `<button class="top5-sort-btn${_top5Sort===m?' active':''}" onclick="_setTop5Sort('${m}')">${l}</button>`).join('')}
    <span class="top5-sort-hint">ML ranks on INTRADAY/1D conviction</span>
  </div>`;
  cardsEl.innerHTML = sortBar + bannerHtml + ordered.map((p, i) => renderPickCard(p, i, idPrefix)).join('');
  ordered.forEach(p => {
    const tvId = 'tv-' + idPrefix + '-' + p.ticker.replace(/[^a-zA-Z0-9]/g, '_');
    const stashed = chartStash[tvId];
    if (stashed) {
      const freshSlot = document.getElementById(tvId);
      if (freshSlot) freshSlot.replaceWith(stashed);  // reuse the live chart — no remount, no blink
    } else {
      observeTvChart(tvId, p.ticker);
    }
    _fetchAndFillMl(p.ticker);   // instant ML row; AI row keeps its own loader
    // Top picks have no per-card ↺ Retry button, so without this any TF that came back
    // 'ai_unavailable'/'timeout' would sit on "AI loading… retrying automatically" forever.
    // Kick off the same per-cell background retry the watchlist uses (single-ticker/TF
    // endpoint), guarded so each cell only spawns one retry chain across re-renders/sorts.
    ['INTRADAY', '1D'].forEach(tf => {
      const r = (p.timeframes || {})[tf]?.no_trade_reason;
      if (r !== 'timeout' && r !== 'ai_unavailable') return;
      const key = p.ticker + '|' + tf;
      if (_top5AiRetried.has(key)) return;
      _top5AiRetried.add(key);
      _fetchAndUpdateTfCell(p.ticker, tf, p);
    });
  });
  // Top picks are cached for the day (same stocks), but INTRADAY moves all session — freshen
  // each pick's INTRADAY cell in place right after render (silent, deduped to ≤1/60s per ticker).
  _refreshTop5Intraday(ordered);
}

// Silent INTRADAY auto-refresh for the currently-rendered top picks. Keeps the SAME day-cached
// stocks/ranking but repaints each INTRADAY cell with a fresh prediction (no spinner flash).
// Deduped per ticker so the ~4s streaming polls + sort toggles don't re-fetch repeatedly.
const _top5IntradayLastRefresh = new Map();  // ticker -> epoch ms of last silent INTRADAY refresh
function _refreshTop5Intraday(picks, minGapMs = 60000, force = false) {
  if (!_isMarketHoursIST()) return;
  (picks || []).forEach(p => {
    if (!p || !p.ticker) return;
    const last = _top5IntradayLastRefresh.get(p.ticker) || 0;
    if (Date.now() - last < minGapMs) return;
    _top5IntradayLastRefresh.set(p.ticker, Date.now());
    _fetchAndUpdateTfCell(p.ticker, 'INTRADAY', p, 0, { silent: true, force });
  });
}

// ── Top-pick ranking: AI (server order) / ML (quantile conviction) / Blend ─────
let _top5Sort = 'ai';
let _lastTop5 = { cardsEl: null, idPrefix: '', picks: [], banner: '' };

// ML conviction score for a ticker from its cached prediction — INTRADAY/1D
// (matches the AI ranking horizons).
function _mlPickScore(ticker) {
  const ml = _mlCache.get(ticker);
  if (!ml || !ml.available || !ml.tfs) return 0;
  let best = 0;
  ['INTRADAY', '1D'].forEach(tf => {
    const d = ml.tfs[tf];
    if (!d) return;
    const prob = d.confidence_prob || 0.5;
    let exp = 0;
    if (d.current_price && d.expected_target_price) exp = (d.expected_target_price / d.current_price - 1) * 100;
    else if (d.predicted_return_hi != null) exp = d.predicted_return_hi;
    const dirMult = d.direction === 'BULLISH' ? 1 : d.direction === 'BEARISH' ? 0.2 : 0.4;
    const s = prob * Math.abs(exp) * dirMult;
    if (s > best) best = s;
  });
  return best;
}

function _applyTop5Sort(picks) {
  if (_top5Sort === 'ai') return picks;
  const arr = picks.map((p, i) => ({ p, ai: i, ml: _mlPickScore(p.ticker) }));
  if (_top5Sort === 'ml') { arr.sort((a, b) => b.ml - a.ml || a.ai - b.ai); return arr.map(x => x.p); }
  // Blend: average the AI position and the ML position (lower = better).
  const byMl = arr.slice().sort((a, b) => b.ml - a.ml);
  byMl.forEach((x, idx) => { x.mlRank = idx; });
  arr.sort((a, b) => (a.ai + a.mlRank) - (b.ai + b.mlRank));
  return arr.map(x => x.p);
}

function _setTop5Sort(mode) {
  _top5Sort = mode;
  if (_lastTop5.cardsEl) _renderTop5CardsInto(_lastTop5.cardsEl, _lastTop5.idPrefix, _lastTop5.picks, _lastTop5.banner);
}

async function loadTop5Cards(cardsId, loadingId, limit = 20, forceRefresh = false) {
  _clearAiRetry();
  const cardsEl = document.getElementById(cardsId);
  if (!cardsEl) return;

  // Only show the "Loading picks…" spinner on the very first call (not on poll retries).
  // Retries update the existing "Analysing…" message in place so the UI doesn't flicker.
  const isRetry = !forceRefresh && _top5PollCount > 0;
  if (!isRetry) { showEl(loadingId); cardsEl.innerHTML = ''; _top5PollStart = Date.now(); _top5AiRetried.clear(); }
  if (forceRefresh) { _top5PollCount = 0; _top5AutoRetried = false; _top5PollStart = Date.now(); _top5AiRetried.clear(); if (_top5PollTimer) { clearTimeout(_top5PollTimer); _top5PollTimer = null; } }

  // Abort the fetch after 5 min — allows the server time to finish computing on a cold start.
  const ctrl = new AbortController();
  const fetchTimeout = setTimeout(() => ctrl.abort(), 300000);

  try {
    const top5Url = forceRefresh ? '/api/top5?refresh=1' : '/api/top5';
    const res  = await fetch(top5Url, { cache: 'no-store', signal: ctrl.signal });
    clearTimeout(fetchTimeout);
    // Read as text first so a non-JSON response (e.g. HF Spaces HTML wake-up page
    // or a proxy error page) gives an actionable error instead of "Unexpected token '<'".
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (_parseErr) {
      // Server is starting up or unavailable — retry in 15s rather than showing an error.
      cardsEl.innerHTML = `<div class="empty-state" id="top5-computing-msg">
        <div class="empty-icon" style="font-size:28px">⏳</div>
        <div style="font-weight:600;margin-bottom:6px">Server is starting up…</div>
        <div style="font-size:12px;color:var(--text-muted)">Retrying in 15 seconds. (HTTP ${res.status})</div>
      </div>`;
      hideEl(loadingId);
      _top5PollTimer = setTimeout(() => loadTop5Cards(cardsId, loadingId, limit, false), 15000);
      return;
    }
    if (!res.ok || data.error) throw new Error(data.error || `Server error ${res.status}`);

    // Server is computing picks in the background — stream ready cards as they come.
    if (data.computing) {
      _top5PollCount++;
      hideEl(loadingId);
      const idPrefix = cardsId.replace(/[^a-zA-Z0-9]/g, '_');
      const partial = (data.picks || []).slice(0, limit);
      const elapsedMin = (Date.now() - _top5PollStart) / 60000;

      // Hard cap (~12 min elapsed) so a stuck backend never spins forever —
      // surface a genuine error with a manual retry instead of an endless loader.
      if (elapsedMin > 12 && !partial.length) {
        _top5PollCount = 0;
        cardsEl.innerHTML = `<div class="error-card">
          <div>Top picks are still not ready after ~12 minutes — the market scan may be failing (data source blocked or market data unavailable).</div>
          <button class="btn-ghost btn-sm" style="margin-top:8px" onclick="loadTop5Cards('${cardsId}','${loadingId}',${limit},true)">↺ Retry now</button>
        </div>`;
        return;
      }

      const phaseMsg = data.message
        || (data.phase === 'predicting' ? 'Running AI on shortlisted candidates…' : 'Scanning the NSE market…');

      if (partial.length) {
        // Progressive reveal: render ready cards immediately with a slim progress banner,
        // and keep filling in the rest. Poll fast (4s) so pending cards resolve quickly.
        if (data.market) applyMarket(data.market);
        const banner = `<div class="top5-stream-banner">
          <span class="tf-cell-spinner" style="font-size:15px">⟳</span>
          <span>${phaseMsg} — showing ${partial.length} ready pick${partial.length > 1 ? 's' : ''}, more loading…</span>
        </div>`;
        _renderTop5CardsInto(cardsEl, idPrefix, partial, banner);
        cardsEl.setAttribute('data-loaded', '1');
        _top5PollTimer = setTimeout(() => loadTop5Cards(cardsId, loadingId, limit, false), 4000);
        return;
      }

      // No cards ready yet — show the phase spinner. Poll every 6s so the first
      // cards appear promptly once Phase 2 starts resolving.
      const waitMsg = elapsedMin > 3
        ? `${phaseMsg} ~${Math.round(elapsedMin)} min so far. Slowest on a cold cache, faster on later runs. Checking automatically.`
        : `${phaseMsg} This can take a few minutes on a cold start. Checking automatically.`;
      cardsEl.innerHTML = `<div class="empty-state" id="top5-computing-msg">
        <div class="empty-icon" style="font-size:28px">⏳</div>
        <div style="font-weight:600;margin-bottom:6px">Analysing top stocks…</div>
        <div style="font-size:12px;color:var(--text-muted)">${waitMsg}</div>
      </div>`;
      _top5PollTimer = setTimeout(() => loadTop5Cards(cardsId, loadingId, limit, false), 6000);
      return;
    }

    if (data.market) applyMarket(data.market);
    if (data.market_closed) showMarketClosedBanner(data.market_closed);
    const picks = (data.picks || []).slice(0, limit);
    if (!picks.length) {
      // Cache returned empty — auto-retry once with a fresh compute (no cache).
      if (!forceRefresh && !_top5AutoRetried) {
        _top5AutoRetried = true;
        cardsEl.innerHTML = `<div class="empty-state" id="top5-computing-msg">
          <div class="empty-icon" style="font-size:28px">⏳</div>
          <div style="font-weight:600;margin-bottom:6px">No cached picks — computing fresh…</div>
          <div style="font-size:12px;color:var(--text-muted)">This takes 2–4 minutes. Checking automatically.</div>
        </div>`;
        hideEl(loadingId);
        loadTop5Cards(cardsId, loadingId, limit, true);
        return;
      }
      const mkt = data.market || {};
      const errs = (data.errors || []).slice(0, 3);
      const gateHtml = (mkt.vix_label || mkt.nifty_label || mkt.macro_label)
        ? `<div class="market-gates-mini" style="margin-top:12px;font-size:12px;color:var(--text-muted)">
            ${mkt.vix_label   ? `<div>VIX: <span style="color:${mkt.vix_label.startsWith('LOW')?'var(--green)':mkt.vix_label.startsWith('MOD')?'var(--yellow)':'var(--red)'}">${mkt.vix_label}</span></div>` : ''}
            ${mkt.nifty_label ? `<div>Nifty: <span style="color:${mkt.nifty_ok?'var(--green)':'var(--red)'}">${mkt.nifty_label}</span></div>` : ''}
            ${mkt.macro_label ? `<div>Macro: <span style="color:${mkt.macro_ok?'var(--green)':'var(--red)'}">${mkt.macro_label}</span></div>` : ''}
            ${errs.length ? `<div style="margin-top:6px;color:var(--red)">Errors: ${errs.join(' | ')}</div>` : ''}
          </div>` : '';
      const reason = data.no_picks_reason || 'No picks available right now. Market may be in a defensive phase.';
      cardsEl.innerHTML = `<div class="empty-state"><div class="empty-icon">★</div><div>${reason}</div>${gateHtml}</div>`;
    } else {
      const generatedEl = document.getElementById('top5-generated');
      if (generatedEl) generatedEl.textContent = (data._stale ? '↻ Refreshing in background — ' : 'Generated: ') + (data.generated_at || '');
      const idPrefix = cardsId.replace(/[^a-zA-Z0-9]/g, '_');
      _renderTop5CardsInto(cardsEl, idPrefix, picks);
      if (data.has_ai_unavailable) {
        _showAiRetryBanner(cardsEl, () => loadTop5Cards(cardsId, loadingId, limit, true));
      }
    }
    cardsEl.setAttribute('data-loaded', '1');
    _top5PollCount = 0;
  } catch (e) {
    clearTimeout(fetchTimeout);
    const msg = e.name === 'AbortError' ? 'Request timed out — server may be busy. Retrying in 20s.' : `Failed to load picks: ${e.message}`;
    cardsEl.innerHTML = `<div class="error-card">${msg}</div>`;
    if (e.name === 'AbortError') {
      _top5PollCount = 0;  // reset so the spinner shows again on next attempt
      _top5PollTimer = setTimeout(() => loadTop5Cards(cardsId, loadingId, limit, false), 20000);
    }
  } finally { hideEl(loadingId); }
}



// ── Watchlist view ────────────────────────────────────────────────────────────
async function loadWatchlist(forceRefresh = false) {
  _clearAiRetry();
  const el = document.getElementById('wl-list');
  el.className = 'picks-grid';
  el.innerHTML = '';
  const refreshParam = forceRefresh ? '?refresh=1' : '';
  try {
    const wlRes = await fetch('/api/watchlist', { cache: 'no-store' });
    const wlData = await wlRes.json();
    const watchlist = wlData.watchlist || [];

    if (!watchlist.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-icon">◎</div><div>No stocks in watchlist. Add tickers above.</div></div>';
      _watchlistLoaded = true;
      return;
    }

    // Paint watchlist identity immediately, then hydrate each card prediction asynchronously.
    el.innerHTML = watchlist.map(renderWatchlistShellCard).join('');
    watchlist.forEach(item => {
      const ticker = (item.ticker || '').toUpperCase();
      const tvId = 'tv-wl-' + ticker.replace(/[^a-zA-Z0-9]/g, '_');
      observeTvChart(tvId, ticker);
      _fetchAndFillMl(ticker);  // instant local ML row — independent of the slow AI call
    });

    let firstMarketApplied = false;
    let firstMarketClosedApplied = false;
    let anyAiUnavailable = false;
    await Promise.allSettled(watchlist.map(async (item) => {
      const ticker = (item.ticker || '').toUpperCase();
      const cardId = 'wl-card-' + ticker.replace(/[^a-zA-Z0-9]/g, '_');
      try {
        const res = await fetch('/api/watchlist-pick/' + encodeURIComponent(ticker) + refreshParam, { cache: 'no-store' });
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || `Server error ${res.status}`);
        const pick = data.pick;
        if (!pick) throw new Error('No prediction returned');

        if (data.has_ai_unavailable) anyAiUnavailable = true;

        // Cache prediction so Trade modal doesn't re-fetch when shell card is clicked.
        _predictionCache.set(ticker, data);

        const cardEl = document.getElementById(cardId);
        if (!cardEl) return;
        cardEl.outerHTML = renderPickCard(pick, 0, 'wl', 'watchlist');
        applyWatchlistConvictionFilter();  // keep filter honored as cards resolve
        _fetchAndFillMl(ticker);           // instant ML row alongside the AI forecast

        // Auto-fetch any TF cells whose AI is still loading — updates them in place as
        // each resolves, and keeps retrying in the background until a provider frees up.
        ['INTRADAY','1D'].forEach(tf => {
          const r = (pick.timeframes || {})[tf]?.no_trade_reason;
          if (r === 'timeout' || r === 'ai_unavailable') {
            _fetchAndUpdateTfCell(ticker, tf, pick);
          }
        });

        // Card replacement creates a new chart container node; remount observer.
        const tvId = 'tv-wl-' + ticker.replace(/[^a-zA-Z0-9]/g, '_');
        setTimeout(() => observeTvChart(tvId, ticker), 40);

        if (!firstMarketApplied && data.market) {
          applyMarket(data.market);
          firstMarketApplied = true;
        }
        if (!firstMarketClosedApplied && data.market_closed) {
          showMarketClosedBanner(data.market_closed);
          firstMarketClosedApplied = true;
        }
      } catch (err) {
        const cardEl = document.getElementById(cardId);
        if (!cardEl) return;
        const errorHost = cardEl.querySelector('.pick-signals');
        if (errorHost) {
          errorHost.innerHTML = `<div class="error-card">Failed to load predictions: ${err.message}</div>`;
        }
      }
    }));
    if (anyAiUnavailable) {
      _showAiRetryBanner(
        document.getElementById('wl-list'),
        () => { _watchlistLoaded = false; loadWatchlist(true); }
      );
    }
    _watchlistLoaded = true;
  } catch (e) {
    el.innerHTML = `<div class="error-card">Failed to load watchlist: ${e.message}</div>`;
  }
}

document.getElementById('wl-refresh-btn')?.addEventListener('click', () => {
  _watchlistLoaded = false;
  loadWatchlist(true);
});

async function retryWatchlistCard(ticker, btnEl) {
  const card = document.querySelector(`#wl-list [data-ticker="${ticker}"]`);
  if (!card) return;
  if (btnEl) { btnEl.disabled = true; btnEl.textContent = '↻ Loading…'; }
  card.classList.add('pick-card--loading');
  try {
    const res = await fetch('/api/watchlist-pick/' + encodeURIComponent(ticker) + '?refresh=1', { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `Server error ${res.status}`);
    const pick = data.pick;
    if (!pick) throw new Error('No prediction returned');
    _predictionCache.set(ticker, data);
    const tmp = document.createElement('div');
    tmp.innerHTML = renderPickCard(pick, 0, 'wl', 'watchlist');
    const newCard = tmp.firstElementChild;
    card.replaceWith(newCard);
    const tvId = 'tv-wl-' + ticker.replace(/[^a-zA-Z0-9]/g, '_');
    setTimeout(() => observeTvChart(tvId, ticker), 40);
  } catch (e) {
    card.classList.remove('pick-card--loading');
    if (btnEl) { btnEl.disabled = false; btnEl.textContent = '↺ Retry'; }
    const signals = card.querySelector('.pick-signals');
    if (signals) {
      const err = document.createElement('div');
      err.className = 'error-card';
      err.style.cssText = 'margin-top:8px;font-size:12px';
      err.textContent = 'Retry failed: ' + e.message;
      signals.appendChild(err);
    }
  }
}

// HIGH-conviction filter — show only cards whose best timeframe is HIGH confidence.
function applyWatchlistConvictionFilter() {
  const btn = document.getElementById('wl-highconf-filter');
  const on = btn?.dataset.active === 'true';
  document.getElementById('wl-list')?.querySelectorAll('.pick-card').forEach(card => {
    // Never hide loading/shell cards; only filter resolved cards with a conviction attr.
    if (!card.dataset.conviction) return;
    card.style.display = (!on || card.dataset.conviction === 'high') ? '' : 'none';
  });
}
document.getElementById('wl-highconf-filter')?.addEventListener('click', (e) => {
  const btn = e.currentTarget;
  btn.dataset.active = btn.dataset.active === 'true' ? 'false' : 'true';
  applyWatchlistConvictionFilter();
});

// ── INTRADAY auto-refresh during market hours ──────────────────────────────
function _isMarketHoursIST() {
  const now = new Date();
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
  const mins = ist.getHours() * 60 + ist.getMinutes();
  return mins >= 9 * 60 + 15 && mins <= 15 * 60 + 30;
}

// Watchlist INTRADAY: repaint each card's INTRADAY AI cell in place every 5 min during market
// hours (silent — no spinner flash). force=true re-runs the AI (bypasses the 15-min server
// cache) so the forecast actually updates instead of being served stale from cache.
function _refreshWatchlistIntraday(force = false) {
  if (!_isMarketHoursIST()) return;
  document.querySelectorAll('#wl-list [data-ticker]').forEach(card => {
    const ticker = card.dataset.ticker;
    if (!ticker) return;
    const pick = _predictionCache.get(ticker)?.pick;
    if (!pick) return;
    _fetchAndUpdateTfCell(ticker, 'INTRADAY', pick, 0, { silent: true, force });
  });
}
setInterval(() => _refreshWatchlistIntraday(true), 5 * 60 * 1000);

// Re-run the INTRADAY AI the moment a watchlist stock's live price crosses its predicted target
// (bull: price ≥ target, bear: price ≤ target) — a spent target means the old forecast is stale.
// Polls live price every 60s during market hours; fires at most once per (ticker, target) so a
// price sitting beyond target doesn't re-burst AI calls (the fresh forecast sets a new target).
const _intradayTargetCrossKey = new Map();  // ticker -> the target ₹ that last triggered a refresh
const _mlTargetCrossKey = new Map();        // ticker -> the ML target ₹ that last triggered an ML refresh
// Re-run INTRADAY AI for one ticker if its live price has crossed the predicted target.
async function _intradayCrossOne(ticker, pick) {
  // One live-price fetch drives both the AI and the ML target-cross checks.
  let price = null;
  try {
    const r = await fetch(`/api/live-price/${encodeURIComponent(ticker)}`, { cache: 'no-store' });
    const d = await r.json();
    price = d && d.price;
  } catch (e) { return; }  // live-price hiccup — try again next tick
  if (!price) return;

  // AI INTRADAY target-cross → force a fresh AI call (the fresh forecast sets a new target).
  const af = pick?.timeframes?.INTRADAY?.ai_forecast;
  if (af && (af.direction === 'BULLISH' || af.direction === 'BEARISH')) {
    const hi = af.target_price_hi, lo = af.target_price_lo;
    if (hi && lo && hi > 0 && lo > 0) {
      const target = af.direction === 'BULLISH' ? Math.max(hi, lo) : Math.min(hi, lo);
      const crossed = af.direction === 'BULLISH' ? price >= target : price <= target;
      if (crossed && _intradayTargetCrossKey.get(ticker) !== String(target)) {
        _intradayTargetCrossKey.set(ticker, String(target));  // once per (ticker, target)
        _fetchAndUpdateTfCell(ticker, 'INTRADAY', pick, 0, { silent: true, force: true });
      }
    }
  }

  // ML INTRADAY target-cross → force a fresh ML fetch (independent of the AI call above).
  const mlTf = (_mlCache.get(ticker) || {}).tfs?.INTRADAY;
  if (mlTf && (mlTf.direction === 'BULLISH' || mlTf.direction === 'BEARISH')) {
    const mlTgt = mlTf.expected_target_price;
    if (mlTgt && mlTgt > 0) {
      const mlCrossed = mlTf.direction === 'BULLISH' ? price >= mlTgt : price <= mlTgt;
      if (mlCrossed && _mlTargetCrossKey.get(ticker) !== String(mlTgt)) {
        _mlTargetCrossKey.set(ticker, String(mlTgt));  // once per (ticker, ML target)
        _fetchAndFillMl(ticker, true, ['INTRADAY']);
      }
    }
  }
}
// Poll live price every 60s during market hours and fire the cross check for BOTH watchlist
// cards (pick from _predictionCache) and top picks (pick from _lastTop5.picks).
async function _checkIntradayTargetCross() {
  if (!_isMarketHoursIST()) return;
  const seen = new Set();
  for (const card of document.querySelectorAll('#wl-list [data-ticker]')) {
    const ticker = card.dataset.ticker;
    if (!ticker || seen.has(ticker)) continue;
    seen.add(ticker);
    const pick = _predictionCache.get(ticker)?.pick;
    if (pick) _intradayCrossOne(ticker, pick);
  }
  for (const p of (_lastTop5.picks || [])) {
    if (!p || !p.ticker || seen.has(p.ticker)) continue;
    seen.add(p.ticker);
    _intradayCrossOne(p.ticker, p);
  }
}
setInterval(_checkIntradayTargetCross, 60 * 1000);

// Top picks: same day-cached stocks, but re-run each pick's INTRADAY AI in place every 5 min
// during market hours (silent — no spinner flash), forcing a fresh AI call that bypasses the
// 15-min server cache. Uses _lastTop5.picks so it follows whichever grid is rendered
// (dashboard / top-picks view).
setInterval(() => {
  if (!_isMarketHoursIST()) return;
  _refreshTop5Intraday(_lastTop5.picks, 60000, true);  // 60s per-ticker dedupe guards render collisions
}, 5 * 60 * 1000);

// INTRADAY ML must refresh at least every 5 min (no long-lived cache). Force-refetch the ML
// forecast for every ticker currently rendered (watchlist + top picks — all live in _mlCache)
// but repaint ONLY the INTRADAY slot in place. 1D/3D are multi-day horizons that don't move
// intraday, so they're left untouched — the periodic tick updates chart + intraday only, never
// a full-card / full-scan reload.
setInterval(() => {
  if (!_isMarketHoursIST()) return;
  for (const ticker of _mlCache.keys()) _fetchAndFillMl(ticker, true, ['INTRADAY']);
}, 5 * 60 * 1000);

// ── Catch-up refresh when the tab regains focus ────────────────────────────
// Browsers heavily throttle setInterval/setTimeout in background tabs (Chrome "intensive
// throttling" cuts background timers to ~once/hour after ~5 min hidden), so the three
// INTRADAY auto-refresh intervals above effectively stop firing while the tab isn't active —
// that's why data looked stale after 5+ min away. Fire an immediate refresh the moment the
// tab becomes visible again instead of waiting for the (throttled) interval to catch up.
let _lastVisibilityRefresh = 0;
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return;
  if (!_isMarketHoursIST()) return;
  if (Date.now() - _lastVisibilityRefresh < 15000) return;  // debounce rapid tab-switch flicker
  _lastVisibilityRefresh = Date.now();

  _refreshWatchlistIntraday(true);
  _checkIntradayTargetCross();
  _refreshTop5Intraday(_lastTop5.picks, 60000, true);
  for (const ticker of _mlCache.keys()) _fetchAndFillMl(ticker, true, ['INTRADAY']);
});

const wlAddInput = document.getElementById('wl-add-input');
const wlSuggest  = document.getElementById('wl-suggestions');

let _wlSuggestTimer = null;
let _wlSelectedName = '';

wlAddInput?.addEventListener('input', () => {
  const q = wlAddInput.value.trim();
  _wlSelectedName = '';
  if (!q) { wlSuggest.innerHTML = ''; return; }
  clearTimeout(_wlSuggestTimer);
  _wlSuggestTimer = setTimeout(async () => {
    try {
      const res  = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
      const data = await res.json();
      wlSuggest.innerHTML = '';
      (data.results || []).forEach(u => {
        const item = document.createElement('div');
        item.className = 'suggestion-item';
        item.innerHTML = `<span class="suggestion-ticker">${u.ticker}</span><span class="suggestion-name">${u.name}</span>`;
        item.addEventListener('mousedown', e => {
          e.preventDefault();
          wlAddInput.value = u.ticker;
          _wlSelectedName  = u.name;
          wlSuggest.innerHTML = '';
        });
        wlSuggest.appendChild(item);
      });
    } catch (_) {}
  }, 280);
});
wlAddInput?.addEventListener('blur', () => setTimeout(() => { wlSuggest.innerHTML = ''; }, 150));

document.getElementById('wl-add-btn')?.addEventListener('click', async () => {
  const ticker = wlAddInput.value.toUpperCase().trim();
  if (!ticker) return;
  await addToWatchlist(ticker, _wlSelectedName);
});

async function addToWatchlist(ticker, name) {
  try {
    const res = await fetch('/api/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, name }),
    });
    if (!res.ok) throw new Error('Failed');
    _watchlistLoaded = false;
    if (wlAddInput) wlAddInput.value = '';
    loadWatchlist();
  } catch (e) { alert('Could not add to watchlist: ' + e.message); }
}

async function removeFromWatchlist(ticker) {
  if (!confirm(`Remove ${ticker} from watchlist?`)) return;
  try {
    await fetch('/api/watchlist/' + ticker, { method: 'DELETE' });
    _watchlistLoaded = false;
    loadWatchlist();
  } catch (e) { alert('Could not remove: ' + e.message); }
}

// ── Portfolio view ────────────────────────────────────────────────────────────
document.querySelectorAll('.ptab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.ptab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.ptab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('ptab-' + tab.dataset.ptab)?.classList.add('active');
  });
});

async function loadPortfolio() {
  showEl('portfolio-loading');
  try {
    // Auto-enforce stop-losses before rendering portfolio state.
    await fetch('/api/trades/check-stops', { method: 'POST' });

    const [openRes, histRes, pendingRes] = await Promise.all([
      fetch('/api/trades/open', { cache: 'no-store' }),
      fetch('/api/trades/history', { cache: 'no-store' }),
      fetch('/api/orders/pending', { cache: 'no-store' }),
    ]);
    const openData    = await openRes.json();
    const histData    = await histRes.json();
    const pendingData = await pendingRes.json();
    const openEl    = document.getElementById('open-trades-table');
    const histEl    = document.getElementById('history-trades-table');
    const pendingEl = document.getElementById('pending-orders-table');
    const openTrades    = openData.trades   || [];
    const histTrades    = histData.trades   || [];
    const pendingOrders = pendingData.orders || [];

    if (openEl) openEl.innerHTML = openTrades.length
      ? renderOpenTradesCards(openTrades)
      : '<div class="empty-state"><div class="empty-icon">◑</div>No open trades — use + New Trade to get started</div>';

    histEl.innerHTML = histTrades.length
      ? renderHistoryCards(histTrades)
      : '<div class="empty-state"><div class="empty-icon">◑</div>No closed trades yet</div>';

    pendingEl.innerHTML = pendingOrders.length
      ? renderPendingOrdersCards(pendingOrders)
      : '<div class="empty-state"><div class="empty-icon">◎</div>No pending limit orders</div>';

    // Badge on the Pending tab
    const badge = document.getElementById('pending-badge');
    if (badge) {
      if (pendingOrders.length) {
        badge.textContent = pendingOrders.length;
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    }

    // P&L summary strip
    const totalInvested = openTrades.reduce((s, t) => s + ((t.entry_price || 0) * (t.shares || 0)), 0);
    const unrealised    = openTrades.reduce((s, t) => s + (t.unrealised_pnl || 0), 0);
    const closedPnl     = histTrades.reduce((s, t) => s + (t.pnl || 0), 0);
    const wins          = histTrades.filter(t => (t.pnl || 0) >= 0).length;
    const losses        = histTrades.length - wins;
    const winRate       = histTrades.length ? (wins / histTrades.length * 100).toFixed(1) + '%' : '—';
    const setEl = (id, html) => { const e = document.getElementById(id); if (e) e.innerHTML = html; };
    setEl('port-invested',   '₹' + num(totalInvested));
    setEl('port-unrealised', `<span class="${pnlClass(unrealised)}">${unrealised >= 0 ? '+' : ''}₹${num(unrealised)}</span>`);
    setEl('port-pnl',        `<span class="${pnlClass(closedPnl)}">${closedPnl >= 0 ? '+' : ''}₹${num(closedPnl)}</span>`);
    setEl('port-winrate',    winRate);
    setEl('port-wins',       `<span class="pnl-pos">${wins}W</span>`);
    setEl('port-losses',     `<span class="pnl-neg">${losses}L</span>`);
  } catch (e) { console.warn(e); } finally { hideEl('portfolio-loading'); }
}

function _tradeCardId(trade, view) {
  return `p-${view}-${trade.id || trade.ticker}-${(trade.ticker || '').replace(/[^a-zA-Z0-9]/g, '_')}`;
}

function _tradeDate(ts) {
  return (ts || '').slice(0, 10) || '—';
}

function renderPortfolioTradeInsight(pick) {
  const tfs = (pick || {}).timeframes || {};
  const tf = tfName => {
    const t = tfs[tfName] || {};
    const noSetup = t.no_trade_reason || t.direction === 'NO TRADE' || t.direction === 'N/A';
    return `<div class="port-tf-cell">
      <div class="port-tf-label">${tfName === 'INTRADAY' ? 'Today' : tfName}</div>
      <div class="port-tf-dir ${dirClass(t.direction || 'NEUTRAL')}" title="${t.direction || ''}">${dirLabel(t.direction) || 'N/A'}</div>
      <div class="port-tf-ret">${noSetup ? 'No setup' : (t.expected_return_range || 'N/A')}</div>
      <div class="port-tf-ai">AI: ${dirLabel(((t.ai_forecast || {}).direction)) || 'N/A'}</div>
    </div>`;
  };

  const t3 = tfs['1D'] || {};
  const t3Entry = t3.expected_entry_price || pick.price || 0;
  const t3Target = t3.expected_target_price || t3.min_target || null;
  const t3Lo = t3.target_price_lo;
  const t3Hi = t3.target_price_hi;
  const t3Range = (t3Lo !== undefined && t3Lo !== null && t3Hi !== undefined && t3Hi !== null)
    ? `₹${num(t3Lo)} - ₹${num(t3Hi)}`
    : '—';
  const news = (pick || {}).news || {};
  return `<div class="port-insight-grid">
    <div class="port-insight-primary">
      <div class="port-insight-row"><span>Primary (1D)</span><strong class="${dirClass(t3.direction || pick.direction || 'NEUTRAL')}" title="${t3.direction || pick.direction || ''}">${dirLabel(t3.direction || pick.direction) || 'N/A'}</strong></div>
      <div class="port-insight-row"><span>Entry</span><strong>${t3Entry ? `₹${num(t3Entry)}` : '—'}</strong></div>
      <div class="port-insight-row"><span>Expected Target</span><strong>${t3Target ? `₹${num(t3Target)}` : '—'}</strong></div>
      <div class="port-insight-row"><span>Target Range</span><strong>${t3Range}</strong></div>
      <div class="port-insight-row"><span>Stop Loss</span><strong>${t3.stop_loss ? `₹${num(t3.stop_loss)}` : '—'}</strong></div>
      <div class="port-insight-row"><span>R:R</span><strong>${t3.actual_rr ? `${t3.actual_rr}R` : '—'}</strong></div>
    </div>
    <div class="port-insight-timeframes">
      ${tf('INTRADAY')}
      ${tf('1D')}
    </div>
    <div class="port-insight-news">
      <div class="news-label" style="color:${news.label === 'BULLISH' ? 'var(--green)' : news.label === 'BEARISH' ? 'var(--red)' : 'var(--yellow)'}">${news.label || 'NEWS'}</div>
      <div class="news-sum">${news.summary || 'No recent news summary available.'}</div>
    </div>
  </div>`;
}

async function loadPortfolioTradeInsight(cardId) {
  const card = document.getElementById(cardId);
  if (!card || card.dataset.loading === '1') return;
  if (card.dataset.loaded === '1') return;

  const ticker = card.dataset.ticker;
  const insightEl = card.querySelector('.portfolio-insight');
  const chartEl = card.querySelector('.portfolio-chart');
  if (!ticker || !insightEl || !chartEl) return;

  card.dataset.loading = '1';
  insightEl.innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div> Loading prediction + news…</div>';
  try {
    const res = await fetch('/api/portfolio-insight/' + encodeURIComponent(ticker), { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `Server error ${res.status}`);
    insightEl.innerHTML = renderPortfolioTradeInsight(data.pick || {});
    if (data.generated_at) {
      insightEl.innerHTML += `<div class="trade-insight-ts">Generated ${data.generated_at}</div>`;
    }
    wrapWithIntervalToggle(chartEl.id, ticker);
    await mountLwChart(chartEl.id, ticker, '5m');
    if (data.market) applyMarket(data.market);
    card.dataset.loaded = '1';
  } catch (e) {
    insightEl.innerHTML = `<div class="error-card">Could not load insight: ${e.message}</div>`;
  } finally {
    card.dataset.loading = '0';
  }
}

function togglePortfolioTradeCard(cardId) {
  const card = document.getElementById(cardId);
  if (!card) return;
  const willOpen = !card.classList.contains('open');
  card.classList.toggle('open', willOpen);
  if (willOpen) loadPortfolioTradeInsight(cardId);
}

function renderPortfolioTradeCard(trade, view, opts = {}) {
  const { closeAction = '' } = opts;
  const { sym, exch, name } = tickerMeta(trade.ticker || '');
  const isOpen = trade._status === 'OPEN';
  const intendedTarget = trade.target != null && Number.isFinite(Number(trade.target))
    ? `₹${num(trade.target)}`
    : '—';
  const status = trade._status === 'PENDING'
    ? 'LIMIT'
    : isOpen
      ? 'OPEN'
      : ((trade.pnl || 0) >= 0 ? 'WIN' : 'LOSS');
  const liveOrExit = isOpen ? trade.current_price
    : trade._status === 'PENDING' ? trade.current_price
    : trade.exit_price;
  const pnlVal = isOpen ? trade.unrealised_pnl : trade.pnl;
  const pnlPct = isOpen ? trade.unrealised_pnl_pct : trade.pnl_pct;
  const cardId = _tradeCardId(trade, view);
  const chartId = `${cardId}-chart`;
  return `<article class="portfolio-card ${isOpen ? 'is-open' : 'is-closed'}" id="${cardId}" data-ticker="${trade.ticker}">
    <div class="portfolio-card-head">
      <button class="portfolio-card-main" onclick="togglePortfolioTradeCard('${cardId}')">
        <div class="portfolio-id-block">
          <div class="portfolio-name">${name || trade.name || sym}</div>
          <div class="portfolio-symbol-row">
            <span class="portfolio-symbol">${sym}</span>
            <span class="pick-exchange">${exch}</span>
            <span class="dir-badge dir-${trade.direction}">${trade.direction}</span>
            <span class="result-badge result-${status}">${status}</span>
          </div>
        </div>
        <div class="portfolio-stats">
          <div class="portfolio-stat"><span>Entry</span><strong>₹${num(trade.entry_price)}</strong></div>
          <div class="portfolio-stat"><span>${isOpen ? 'Live' : trade._status === 'PENDING' ? 'Market' : 'Exit'}</span><strong>${liveOrExit ? `₹${num(liveOrExit)}` : '—'}</strong></div>
          <div class="portfolio-stat"><span>Intended Target</span><strong>${intendedTarget}</strong></div>
          <div class="portfolio-stat"><span>P&amp;L</span><strong class="${pnlClass(pnlVal || 0)}">${pnlVal != null ? `${pnlVal >= 0 ? '+' : ''}₹${num(pnlVal)} (${(pnlPct || 0) >= 0 ? '+' : ''}${num(pnlPct || 0, 2)}%)` : '—'}</strong></div>
          <div class="portfolio-stat"><span>Shares</span><strong>${trade.shares || '—'}</strong></div>
        </div>
        <span class="portfolio-chevron">▸</span>
      </button>
      <div class="portfolio-card-actions">${closeAction}</div>
    </div>
    <div class="portfolio-meta-row">
      <span>Opened: ${_tradeDate(trade.opened_at)}</span>
      <span>Closed: ${_tradeDate(trade.closed_at)}</span>
      <span>User Target: ${trade.target ? `₹${num(trade.target)}` : '—'}</span>
      <span>SL: ${trade.stop_loss ? `₹${num(trade.stop_loss)}` : '—'}</span>
    </div>
    <div class="portfolio-expand">
      <div class="portfolio-expand-grid">
        <div class="portfolio-insight">
          <div class="loading-inline"><div class="spinner-sm"></div> Expand to load chart, prediction and news.</div>
        </div>
        <div class="portfolio-chart" id="${chartId}"></div>
      </div>
    </div>
  </article>`;
}

function renderAllTradesCards(openTrades, histTrades) {
  const open = openTrades.map(t => ({ ...t, _status: 'OPEN' }));
  const closed = histTrades.map(t => ({ ...t, _status: 'CLOSED' }));
  const all = [...open, ...closed].sort((a, b) => {
    if (a._status !== b._status) return a._status === 'OPEN' ? -1 : 1;
    const da = a._status === 'OPEN' ? (a.opened_at || '') : (a.closed_at || a.opened_at || '');
    const db = b._status === 'OPEN' ? (b.opened_at || '') : (b.closed_at || b.opened_at || '');
    return db.localeCompare(da);
  });
  const cards = all.map(t => renderPortfolioTradeCard(t, 'all', {
    closeAction: t._status === 'OPEN'
      ? `<button class="btn-ghost btn-sm" onclick="openCloseModal(${t.id},'${t.ticker}',${t.entry_price},${t.current_price || 0},${t.shares || 0})">Exit Position</button>`
      : '',
  })).join('');
  return `<div class="portfolio-cards">${cards}</div>`;
}

function renderOpenTradesCards(trades) {
  const cards = trades.map(t => renderPortfolioTradeCard({ ...t, _status: 'OPEN' }, 'open', {
    closeAction: `<button class="btn-ghost btn-sm" onclick="openCloseModal(${t.id},'${t.ticker}',${t.entry_price},${t.current_price || 0},${t.shares || 0})">Exit Position</button>`,
  })).join('');
  return `<div class="portfolio-cards">${cards}</div>`;
}

function renderHistoryCards(trades) {
  const cards = trades.map(t => renderPortfolioTradeCard({ ...t, _status: 'CLOSED' }, 'history')).join('');
  return `<div class="portfolio-cards">${cards}</div>`;
}

function renderPendingOrdersCards(orders) {
  const cards = orders.map(o => renderPortfolioTradeCard({ ...o, _status: 'PENDING' }, 'pending', {
    closeAction: `<button class="btn-ghost btn-sm btn-danger" onclick="cancelOrder(${o.id})">Cancel</button>`,
  })).join('');
  return `<div class="portfolio-cards">${cards}</div>`;
}

function renderPendingOrdersTable(orders) {
  const rows = orders.map(o => {
    const gap = o.current_price
      ? `<span style="font-size:11px;color:var(--text-muted)">live ₹${num(o.current_price)}</span>`
      : '—';
    return `<tr>
      <td>${stockCell(o.ticker)}</td>
      <td>${o.direction}</td>
      <td><span class="result-badge result-LIMIT">LIMIT</span></td>
      <td>₹${num(o.entry_price)}</td>
      <td>${gap}</td>
      <td>${o.shares}</td>
      <td style="font-size:11px;color:var(--text-muted)">${(o.opened_at||'').slice(0,10)}</td>
      <td><button class="btn-ghost btn-sm btn-danger" onclick="cancelOrder(${o.id})">Cancel</button></td>
    </tr>`;
  }).join('');
  return `<table class="trade-table">
    <tr><th>Stock</th><th>Dir</th><th>Type</th><th>Limit</th><th>Market</th><th>Shares</th><th>Placed</th><th></th></tr>
    <tbody>${rows}</tbody></table>`;
}

async function cancelOrder(orderId) {
  if (!confirm('Cancel this pending limit order?')) return;
  const res = await fetch(`/api/orders/${orderId}/cancel`, { method: 'POST' });
  if (res.ok) loadPortfolio();
  else { const e = await res.json(); alert(e.error || 'Failed to cancel'); }
}

document.getElementById('port-check-orders')?.addEventListener('click', async () => {
  const btn = document.getElementById('port-check-orders');
  btn.disabled = true;
  btn.textContent = 'Checking…';
  try {
    const res  = await fetch('/api/orders/check', { method: 'POST' });
    const data = await res.json();
    const filled = data.filled || [];
    if (filled.length) {
      alert(`Filled ${filled.length} order(s): ${filled.map(f => f.ticker).join(', ')}`);
    } else {
      alert('No orders filled — limit prices not yet reached.');
    }
    loadPortfolio();
  } catch (e) { console.warn(e); }
  finally { btn.disabled = false; btn.textContent = '⟳ Check Orders'; }
});

function renderOpenTradesMini(trades) {
  if (!trades.length) return '<div class="empty-state"><div class="empty-icon">◑</div>No open positions</div>';
  const cards = trades.map(t => renderPortfolioTradeCard({ ...t, _status: 'OPEN' }, 'dash-open', {
    closeAction: `<button class="btn-ghost btn-sm" onclick="switchView('portfolio')">Open Portfolio</button>`,
  })).join('');
  return `<div class="portfolio-cards">${cards}</div>`;
}

function renderAllTradesTable(openTrades, histTrades) {
  // Combine open + closed, newest first
  const open   = openTrades.map(t => ({ ...t, _status: 'OPEN' }));
  const closed = histTrades.map(t => ({ ...t, _status: 'CLOSED' }));
  const all    = [...open, ...closed].sort((a, b) => {
    if (a._status !== b._status) return a._status === 'OPEN' ? -1 : 1;
    const da = a._status === 'OPEN' ? (a.opened_at || '') : (a.closed_at || a.opened_at || '');
    const db = b._status === 'OPEN' ? (b.opened_at || '') : (b.closed_at || b.opened_at || '');
    return db.localeCompare(da);
  });

  const rows = all.map(t => {
    if (t._status === 'OPEN') {
      const upnl    = t.unrealised_pnl;
      const upnlPct = t.unrealised_pnl_pct;
      const hasLive = t.current_price != null;
      const pnlStr  = upnl != null
        ? `<span class="${pnlClass(upnl)}">${upnl >= 0 ? '+' : ''}₹${num(upnl)} (${upnlPct >= 0 ? '+' : ''}${num(upnlPct,2)}%)</span>`
        : '<span class="pnl-zero">—</span>';
      const curStr  = hasLive ? `₹${num(t.current_price)}` : '—';
      return `<tr>
        <td>${stockCell(t.ticker)}</td>
        <td><span class="dir-badge dir-${t.direction}">${t.direction}</span></td>
        <td>₹${num(t.entry_price)}</td>
        <td>${curStr}</td>
        <td>${pnlStr}</td>
        <td>${t.shares}</td>
        <td style="font-size:11px;color:var(--text-muted)">${(t.opened_at||'').slice(0,10)}</td>
        <td><span class="result-badge result-OPEN">OPEN</span></td>
        <td><button class="btn-ghost btn-sm" onclick="openCloseModal(${t.id},'${t.ticker}',${t.entry_price},${t.current_price||0},${t.shares||0})">Exit</button></td>
      </tr>`;
    } else {
      const pnl  = t.pnl || 0;
      const pnlPct = t.pnl_pct || 0;
      const won  = pnl >= 0;
      return `<tr>
        <td>${stockCell(t.ticker)}</td>
        <td>${t.direction}</td>
        <td>₹${num(t.entry_price)}</td>
        <td>₹${num(t.exit_price)}</td>
        <td><span class="${pnlClass(pnl)}">${pnl >= 0 ? '+' : ''}₹${num(pnl)} (${pnlPct >= 0 ? '+' : ''}${num(pnlPct,2)}%)</span></td>
        <td>${t.shares}</td>
        <td style="font-size:11px;color:var(--text-muted)">${(t.closed_at||'').slice(0,10)}</td>
        <td><span class="result-badge result-${won ? 'WIN' : 'LOSS'}">${won ? 'WIN' : 'LOSS'}</span></td>
        <td></td>
      </tr>`;
    }
  }).join('');

  return `<table class="trade-table">
    <tr><th>Stock</th><th>Dir</th><th>Entry</th><th>Exit / Live</th><th>P&amp;L</th><th>Shares</th><th>Date</th><th>Status</th><th></th></tr>
    <tbody>${rows}</tbody></table>`;
}

function renderOpenTradesTable(trades) {
  const rows = trades.map(t => {
    const upnl    = t.unrealised_pnl;
    const upnlPct = t.unrealised_pnl_pct;
    const hasLive = t.current_price != null;
    const pnlStr  = upnl != null
      ? `<span class="${pnlClass(upnl)}">${upnl >= 0 ? '+' : ''}₹${num(upnl)} (${upnlPct >= 0 ? '+' : ''}${num(upnlPct, 2)}%)</span>`
      : '<span class="pnl-zero">—</span>';

    // Inline progress pill to target
    let progressPill = '—';
    if (t.target && hasLive) {
      let pct = 0;
      if (t.direction === 'LONG'  && t.target > t.entry_price) pct = (t.current_price - t.entry_price) / (t.target - t.entry_price) * 100;
      if (t.direction === 'SHORT' && t.target < t.entry_price) pct = (t.entry_price - t.current_price) / (t.entry_price - t.target) * 100;
      const clampedPct = Math.max(0, Math.min(100, pct));
      const fillClass  = pct >= 0 ? 'pos-progress-fill-green' : 'pos-progress-fill-red';
      progressPill = `<div style="display:flex;align-items:center;gap:6px">
        <span style="color:var(--blue);font-weight:600">₹${num(t.target)}</span>
        <div class="pos-progress-track" style="width:56px;flex-shrink:0">
          <div class="pos-progress-fill ${fillClass}" style="width:${clampedPct}%"></div>
        </div>
        <span style="font-size:10px;color:var(--text-dim)">${num(clampedPct,0)}%</span>
      </div>`;
    } else if (t.target) {
      progressPill = `<span style="color:var(--blue);font-weight:600">₹${num(t.target)}</span>`;
    }

    return `<tr>
      <td>${stockCell(t.ticker)}</td>
      <td><span class="dir-badge dir-${t.direction}">${t.direction}</span></td>
      <td style="font-weight:600">₹${num(t.entry_price)}</td>
      <td>${hasLive ? `<span style="font-weight:600">₹${num(t.current_price)}</span>` : '—'}</td>
      <td>${progressPill}</td>
      <td>${t.stop_loss ? `<span style="color:var(--red)">₹${num(t.stop_loss)}</span>` : '—'}</td>
      <td>${pnlStr}</td>
      <td>${t.shares}</td>
      <td style="font-size:11px;color:var(--text-muted)">${(t.opened_at||'').slice(0,10)}</td>
      <td><button class="btn-ghost btn-sm" onclick="openCloseModal(${t.id},'${t.ticker}',${t.entry_price},${t.current_price||0},${t.shares||0})">Exit</button></td>
    </tr>`;
  }).join('');

  return `<table class="trade-table">
    <tr><th>Stock</th><th>Dir</th><th>Entry</th><th>Current</th><th>Target</th><th>SL</th><th>Unreal. P&amp;L</th><th>Shares</th><th>Opened</th><th></th></tr>
    <tbody>${rows}</tbody></table>`;
}

function renderHistoryTable(trades) {
  const rows = trades.map(t => {
    const pnl    = t.pnl || 0;
    const pnlPct = t.pnl_pct || 0;
    const won    = pnl >= 0;
    return `<tr>
      <td>${stockCell(t.ticker)}</td>
      <td>${t.direction}</td>
      <td>₹${num(t.entry_price)}</td>
      <td>₹${num(t.exit_price)}</td>
      <td><span class="${pnlClass(pnl)}">${pnl >= 0 ? '+' : ''}₹${num(pnl)} (${pnlPct >= 0 ? '+' : ''}${num(pnlPct,2)}%)</span></td>
      <td>${t.shares}</td>
      <td style="font-size:11px;color:var(--text-muted)">${(t.closed_at||'').slice(0,10)}</td>
      <td><span class="result-badge result-${won?'WIN':'LOSS'}">${won?'WIN':'LOSS'}</span></td>
    </tr>`;
  }).join('');
  return `<table class="trade-table">
    <tr><th>Stock</th><th>Dir</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Shares</th><th>Closed</th><th>Result</th></tr>
    <tbody>${rows}</tbody></table>`;
}

document.getElementById('port-refresh')?.addEventListener('click', loadPortfolio);
document.getElementById('port-new-trade')?.addEventListener('click', () => openTradeModal('','',0));

// ── Trade Modal ───────────────────────────────────────────────────────────────
const RISK_PER_TRADE = 45000; // 3% of ₹15L capital

function _autoFillShares() {
  const entry    = parseFloat(document.getElementById('tm-entry')?.value)  || 0;
  const sl       = parseFloat(document.getElementById('tm-sl')?.value)     || 0;
  const sharesEl = document.getElementById('tm-shares');
  if (!sharesEl) return;
  if (entry > 0 && sl > 0 && entry > sl) {
    const suggested = Math.floor(RISK_PER_TRADE / (entry - sl));
    if (suggested > 0) sharesEl.value = suggested;
  }
}

let _pendingTradeData = {};
let _pendingTradeContextPromise = null;

// Shared prediction cache: ticker → raw watchlist-pick response.
// Written by loadWatchlist() as each card loads; read by openTradeModal()
// so shell-card Trade clicks never need a redundant network round-trip.
const _predictionCache = new Map();

function openTradeModal(ticker, name, price, stopLoss = 0, target = 0, planData = null) {
  _pendingTradeData = planData || {};
  const modal = document.getElementById('trade-modal');
  modal.classList.remove('hidden');
  const tickerEl = document.getElementById('tm-ticker');
  const entryEl  = document.getElementById('tm-entry');
  const slEl     = document.getElementById('tm-sl');
  const tgtEl    = document.getElementById('tm-target');
  if (tickerEl) tickerEl.value = ticker || '';
  if (entryEl && price)  entryEl.value = price;   // pre-fill with cached price
  if (slEl && stopLoss != null)  slEl.value = stopLoss;   // Handle 0 as valid value
  if (tgtEl && target != null)   tgtEl.value = target;    // Handle 0 as valid value
  _autoFillShares();

  // Refresh entry price with live quote (replaces stale prediction-time price)
  if (ticker && entryEl) {
    entryEl.placeholder = 'Fetching price…';
    fetch(`/api/live-price/${encodeURIComponent(ticker)}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d && d.price) {
          entryEl.value = d.price;
          entryEl.placeholder = '';
          entryEl.title = `Live price from ${d.source || 'market'}`;
          _autoFillShares();
        } else {
          entryEl.placeholder = 'Enter price manually';
          entryEl.title = 'Live price unavailable — type the current market price';
          if (!entryEl.value || parseFloat(entryEl.value) === 0) entryEl.value = '';
        }
      })
      .catch(() => {
        entryEl.placeholder = 'Enter price manually';
        entryEl.title = 'Live price unavailable — type the current market price';
        if (!entryEl.value || parseFloat(entryEl.value) === 0) entryEl.value = '';
      });
  }

  // If no prediction context came with planData, check the in-memory cache first
  // (populated by loadWatchlist as each card loads). Only fall back to a network fetch
  // for Portfolio "New Trade" entries or shell cards clicked before the cache was warm.
  if (ticker && !_pendingTradeData.prediction_data) {
    const cached = _predictionCache.get(ticker);
    if (cached && cached.pick) {
      // Cache hit — apply synchronously, no network round-trip needed.
      const pick = cached.pick;
      const tfs  = pick.timeframes || {};
      // Use the RECOMMENDED timeframe (best_tf) so the modal's target / stop / logged timeframe
      // match the "Recommended: <TF>" the user clicked — not a hardcoded preference.
      const tfKey = (pick.best_tf && tfs[pick.best_tf]) ? pick.best_tf
                    : (tfs['1D'] ? '1D' : (tfs['INTRADAY'] ? 'INTRADAY' : Object.keys(tfs)[0]));
      const tf    = tfs[tfKey];
      if (tf && !_pendingTradeData.prediction_data) {
        _pendingTradeData = {
          ..._pendingTradeData,
          strategy:  (pick.signals?.active_strategies || [])[0] || null,
          timeframe: tfKey,
          max_chase_pct: tf.max_chase_pct || null,
          prediction_data: {
            ml:     pick.ml     || {},
            news:   pick.news   || {},
            ai:     tf.ai_forecast ? {
              direction:       tf.ai_forecast.direction,
              confidence:      tf.ai_forecast.confidence,
              target_price_hi: tf.ai_forecast.target_price_hi,
              target_price_lo: tf.ai_forecast.target_price_lo,
            } : {},
            market: cached.market || pick.market || {},
          },
        };
        const slEl2  = document.getElementById('tm-sl');
        const tgtEl2 = document.getElementById('tm-target');
        if (slEl2  && (!slEl2.value  || parseFloat(slEl2.value)  === 0) && tf.stop_loss)  slEl2.value  = tf.stop_loss;
        if (tgtEl2 && (!tgtEl2.value || parseFloat(tgtEl2.value) === 0)) {
          const afC = tf.ai_forecast || {};
          const bestTgt = (afC.target_price_hi && afC.target_price_lo)
            ? (afC.direction === 'BEARISH' ? Math.min(afC.target_price_hi, afC.target_price_lo) : Math.max(afC.target_price_hi, afC.target_price_lo))
            : tf.expected_target_price;
          if (bestTgt) tgtEl2.value = bestTgt;
        }
        // Do NOT call _autoFillShares() here — shares were already set on modal open
        // and should not jump when prediction data fills in the SL field.
      }
      return;   // skip network fetch entirely
    }

    // Cache miss — fetch from server (Portfolio New Trade or cold shell card).
    _pendingTradeContextPromise = fetch(`/api/watchlist-pick/${encodeURIComponent(ticker)}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d || !d.pick) return;
        const pick = d.pick;
        const tfs  = pick.timeframes || {};
        // Match the recommended timeframe (best_tf), not a hardcoded preference.
        const tfKey = (pick.best_tf && tfs[pick.best_tf]) ? pick.best_tf
                      : (tfs['1D'] ? '1D' : (tfs['INTRADAY'] ? 'INTRADAY' : Object.keys(tfs)[0]));
        const tf    = tfs[tfKey];
        if (!tf || _pendingTradeData.prediction_data) return; // already populated by the time this resolves
        _pendingTradeData = {
          ..._pendingTradeData,
          strategy:  (pick.signals?.active_strategies || [])[0] || null,
          timeframe: tfKey,
          max_chase_pct: tf.max_chase_pct || _pendingTradeData.max_chase_pct || null,
          prediction_data: {
            ml:     pick.ml     || {},
            news:   pick.news   || {},
            ai:     tf.ai_forecast ? { direction: tf.ai_forecast.direction, confidence: tf.ai_forecast.confidence } : {},
            market: d.market || pick.market || {},
          },
        };
        // Pre-fill stop-loss and target only if they are still at their defaults
        if (slEl  && (!slEl.value  || parseFloat(slEl.value)  === 0) && tf.stop_loss) slEl.value = tf.stop_loss;
        if (tgtEl && (!tgtEl.value || parseFloat(tgtEl.value) === 0)) {
          const tfAf  = tf.ai_forecast || {};
          const afHi  = tfAf.target_price_hi, afLo = tfAf.target_price_lo;
          const aiTgt = (afHi && afLo)
            ? (tfAf.direction === 'BEARISH' ? Math.min(afHi, afLo) : Math.max(afHi, afLo))
            : null;
          const fallbackTgt = aiTgt || tf.expected_target_price;
          if (fallbackTgt) tgtEl.value = fallbackTgt;
        }
        // Do NOT call _autoFillShares() here — shares were already set on modal open.
      })
      .catch(() => {}) // silent — prediction context is optional
      .finally(() => { _pendingTradeContextPromise = null; });
  }
}

document.getElementById('modal-close')?.addEventListener('click', closeTradeModal);
document.getElementById('modal-cancel')?.addEventListener('click', closeTradeModal);
document.getElementById('trade-modal')?.addEventListener('click', e => { if (e.target.id === 'trade-modal') closeTradeModal(); });
document.getElementById('tm-entry')?.addEventListener('input', _autoFillShares);

// When the user types a ticker manually in the modal (Portfolio → New Trade),
// re-trigger openTradeModal so the live-price + cached-prediction fetches run.
document.getElementById('tm-ticker')?.addEventListener('change', () => {
  const ticker = document.getElementById('tm-ticker')?.value.toUpperCase().trim();
  if (ticker) openTradeModal(ticker, '', 0, 0, 0);
});

function closeTradeModal() { document.getElementById('trade-modal')?.classList.add('hidden'); }

document.getElementById('modal-submit')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  if (btn.disabled) return;                    // block double-clicks

  const ticker  = document.getElementById('tm-ticker')?.value.toUpperCase().trim();
  const dir     = document.getElementById('tm-direction')?.value;
  const entry   = parseFloat(document.getElementById('tm-entry')?.value);
  const shares  = parseInt(document.getElementById('tm-shares')?.value);
  const sl      = parseFloat(document.getElementById('tm-sl')?.value) || null;
  const target  = parseFloat(document.getElementById('tm-target')?.value) || null;

  if (!ticker || !dir || !entry || !shares) return alert('Ticker, direction, entry price, and shares are required.');

  btn.disabled = true;
  btn.textContent = 'Opening…';

  // Don't await the prediction context — it can take 30-120s (full LLM pipeline).
  // Backend auto-fills missing context via _autofill_trade_context. Submit immediately.

  try {
    const res = await fetch('/api/trades', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ticker,
        direction: dir,
        entry_price: entry,
        shares,
        stop_loss: sl,
        target,
        max_chase_pct: (_pendingTradeData && _pendingTradeData.max_chase_pct) ? _pendingTradeData.max_chase_pct : null,
        strategy:  (_pendingTradeData && _pendingTradeData.strategy)
                    || (_pendingTradeData && (_pendingTradeData.active_strategies || [])[0])
                    || null,
        timeframe: (_pendingTradeData && (_pendingTradeData.timeframe || _pendingTradeData.holding_timeframe)) || null,
        prediction_data: (_pendingTradeData && _pendingTradeData.prediction_data)
          || ((_pendingTradeData && (_pendingTradeData.ml || _pendingTradeData.news || _pendingTradeData.market)) ? {
              ml:     _pendingTradeData.ml     || {},
              news:   _pendingTradeData.news   || {},
              ai:     _pendingTradeData.ai_forecast
                        ? { direction: _pendingTradeData.ai_forecast.direction, confidence: _pendingTradeData.ai_forecast.confidence }
                        : {},
              market: _pendingTradeData.market || {},
            } : null),
      }),
    });
    if (!res.ok) {
      const e = await res.json();
      alert(e.error || 'Failed');
      btn.disabled = false; btn.textContent = 'Open Trade';
      return;
    }
    const trade = await res.json();
    closeTradeModal();
    btn.disabled = false; btn.textContent = 'Open Trade';
    // Clear form
    ['tm-ticker','tm-entry','tm-shares','tm-sl','tm-target'].forEach(id => {
      const el = document.getElementById(id); if (el) el.value = '';
    });
    const kellyNote = trade.kelly_warning ? `\n\n${trade.kelly_warning}` : '';
    if (trade._merged) {
      alert(`Position updated: ${trade.ticker} ${trade.direction}\nAdded ${trade._added_shares} shares @ ₹${num(entry)}\nNew position: ${trade.shares} shares @ ₹${num(trade.entry_price)} avg${kellyNote}`);
    } else if (trade.status === 'PENDING') {
      alert(`Limit order placed for ${trade.ticker} at ₹${num(trade.entry_price)}.\nIt will be filled once the market reaches that price.\nCheck status in Portfolio → Pending Orders.${kellyNote}`);
      // Switch to the pending tab
      document.querySelectorAll('.ptab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.ptab-content').forEach(c => c.classList.remove('active'));
      document.querySelector('[data-ptab="pending"]')?.classList.add('active');
      document.getElementById('ptab-pending')?.classList.add('active');
    } else {
      alert(`Trade opened: ${trade.ticker} ${trade.direction} × ${trade.shares} shares at ₹${num(trade.entry_price)}.\nCheck Portfolio to manage it.${kellyNote}`);
    }
    loadPortfolio();
  } catch (e) {
    alert('Failed to open trade: ' + e.message);
    btn.disabled = false; btn.textContent = 'Open Trade';
  }
});

// ── Close Trade Modal ─────────────────────────────────────────────────────────
let _closingTradeId = null;

let _closingTotalShares = 0;

function openCloseModal(tradeId, ticker, entry, currentPrice, totalShares = 0) {
  _closingTradeId    = tradeId;
  _closingTotalShares = totalShares;
  const modal      = document.getElementById('close-modal');
  const desc       = document.getElementById('close-modal-desc');
  const exitEl     = document.getElementById('close-exit-price');
  const sharesEl   = document.getElementById('close-shares');
  const sharesHint = document.getElementById('close-shares-hint');
  if (desc)       desc.textContent = `Exit position: ${ticker} · Entry ₹${num(entry)}`;
  if (exitEl)     exitEl.value     = currentPrice > 0 ? currentPrice : '';
  if (sharesEl)   sharesEl.value   = '';                           // blank = exit all
  if (sharesHint) sharesHint.textContent = totalShares ? `(${totalShares} held)` : '';
  modal.classList.remove('hidden');
}

document.getElementById('close-modal-x')?.addEventListener('click', () => document.getElementById('close-modal')?.classList.add('hidden'));
document.getElementById('close-modal-cancel')?.addEventListener('click', () => document.getElementById('close-modal')?.classList.add('hidden'));
document.getElementById('close-modal')?.addEventListener('click', e => { if (e.target.id === 'close-modal') document.getElementById('close-modal')?.classList.add('hidden'); });

document.getElementById('close-fetch-price')?.addEventListener('click', async () => {
  if (!_closingTradeId) return;
  try {
    const res  = await fetch('/api/trades/' + _closingTradeId + '/price');
    const data = await res.json();
    if (data.current_price) document.getElementById('close-exit-price').value = data.current_price;
  } catch (e) { alert('Could not fetch price: ' + e.message); }
});

document.getElementById('close-modal-submit')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  if (btn.disabled) return;
  const exitPrice   = parseFloat(document.getElementById('close-exit-price')?.value);
  const sharesInput = parseInt(document.getElementById('close-shares')?.value) || null;
  if (!_closingTradeId || !exitPrice) return alert('Enter exit price.');
  if (sharesInput !== null && sharesInput < 1) return alert('Shares to exit must be at least 1.');
  if (_closingTotalShares && sharesInput > _closingTotalShares)
    return alert(`You only hold ${_closingTotalShares} shares — cannot exit ${sharesInput}.`);
  btn.disabled = true; btn.textContent = 'Exiting…';
  try {
    const body = { exit_price: exitPrice };
    if (sharesInput) body.close_shares = sharesInput;
    const res = await fetch('/api/trades/' + _closingTradeId + '/close', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) { const e = await res.json(); alert(e.error || 'Failed'); return; }
    const trade = await res.json();
    document.getElementById('close-modal')?.classList.add('hidden');
    _closingTradeId = null; _closingTotalShares = 0;
    if (trade.status === 'OPEN') {
      alert(`Partial exit recorded.\nRemaining: ${trade.shares} shares still open @ avg ₹${num(trade.entry_price)}.`);
    } else {
      alert(`Position closed. P&L: ${(trade.pnl >= 0 ? '+' : '')}₹${num(trade.pnl)} (${(trade.pnl_pct >= 0 ? '+' : '')}${num(trade.pnl_pct, 2)}%)`);
    }
    loadPortfolio();
  } catch (err) { alert('Failed: ' + err.message); }
  finally { btn.disabled = false; btn.textContent = 'Exit Position'; }
});

// ── VALIDATION ────────────────────────────────────────────────────────────────

function getMissReason(h) {
  const dir = (h.direction || '').toUpperCase();
  const entry  = h.current_price || h.entry_price || 0;
  const tpLo   = h.target_price_lo || 0;   // absolute ₹ — minimum bull target / worst bear
  const tpHi   = h.target_price_hi || 0;   // absolute ₹ — max bull target / mildest bear
  const retLo  = h.predicted_return_lo ?? 0;
  const retHi  = h.predicted_return_hi ?? 0;
  const winHi  = h.window_high;
  const winLo  = h.window_low;
  const close  = h.actual_price_at_validation;

  function pct(price) { return entry > 0 ? ((price / entry - 1) * 100).toFixed(2) : '?'; }

  if (dir === 'BULLISH') {
    if (winHi != null && entry > 0) {
      const hiPct = pct(winHi);
      if (winHi <= entry) {
        return { cls: 'wrong-dir', label: 'Wrong direction',
          detail: `Stock never exceeded entry — peaked at ₹${num(winHi,2)} (${hiPct}%), needed ₹${num(tpLo,2)} (+${retLo.toFixed(2)}%)` };
      }
      return { cls: 'fell-short', label: 'Fell short',
        detail: `Peaked at ₹${num(winHi,2)} (+${hiPct}%) — target was ₹${num(tpLo,2)} (+${retLo.toFixed(2)}%)` };
    }
    // Fallback: no window data
    const actual = h.actual_return_at_validation ?? 0;
    if (actual < 0) return { cls: 'wrong-dir', label: 'Wrong direction', detail: `Fell ${Math.abs(actual).toFixed(2)}% (needed ≥+${retLo.toFixed(2)}%)` };
    return { cls: 'fell-short', label: 'Fell short', detail: `Rose +${actual.toFixed(2)}%, needed ≥+${retLo.toFixed(2)}%` };
  }

  if (dir === 'BEARISH') {
    if (winLo != null && entry > 0) {
      const loPct = pct(winLo);
      if (winLo >= entry) {
        return { cls: 'wrong-dir', label: 'Wrong direction',
          detail: `Stock stayed above entry — bottomed at ₹${num(winLo,2)} (+${loPct}%), needed ₹${num(tpHi,2)} (${retHi.toFixed(2)}%)` };
      }
      return { cls: 'fell-short', label: 'Fell short',
        detail: `Bottomed at ₹${num(winLo,2)} (${loPct}%) — target was ₹${num(tpHi,2)} (${retHi.toFixed(2)}%)` };
    }
    const actual = h.actual_return_at_validation ?? 0;
    if (actual > 0) return { cls: 'wrong-dir', label: 'Wrong direction', detail: `Rose +${actual.toFixed(2)}% (needed ≤${retHi.toFixed(2)}%)` };
    return { cls: 'fell-short', label: 'Fell short', detail: `Fell ${actual.toFixed(2)}%, needed ≤${retHi.toFixed(2)}%` };
  }

  // NEUTRAL — checked via closing price
  const actual = h.actual_return_at_validation ?? 0;
  if (close != null && entry > 0) {
    if (close > tpHi) return { cls: 'overbullish', label: 'AI missed bullish move',
      detail: `Closed at ₹${num(close,2)} (+${actual.toFixed(2)}%) — above range top ₹${num(tpHi,2)} (+${retHi.toFixed(2)}%)` };
    return { cls: 'overbearish', label: 'AI missed bearish move',
      detail: `Closed at ₹${num(close,2)} (${actual.toFixed(2)}%) — below range floor ₹${num(tpLo,2)} (${retLo.toFixed(2)}%)` };
  }
  if (actual > retHi) return { cls: 'overbullish', label: 'AI missed bullish move', detail: `+${actual.toFixed(2)}% exceeded range max +${retHi.toFixed(2)}%` };
  return { cls: 'overbearish', label: 'AI missed bearish move', detail: `${actual.toFixed(2)}% below range floor ${retLo.toFixed(2)}%` };
}

function getHitNote(h) {
  const dir   = (h.direction || '').toUpperCase();
  const entry = h.current_price || h.entry_price || 0;
  const tpHi  = h.target_price_hi || 0;
  const tpLo  = h.target_price_lo || 0;
  const winHi = h.window_high;
  const winLo = h.window_low;
  const retHi = h.predicted_return_hi ?? 0;
  const retLo = h.predicted_return_lo ?? 0;
  if (!entry) return null;
  if (dir === 'BULLISH' && winHi != null && tpHi > 0 && winHi > tpHi) {
    const pct = ((winHi / entry - 1) * 100).toFixed(2);
    return `AI underestimated — stock reached ₹${num(winHi,2)} (+${pct}%) vs range top +${retHi.toFixed(2)}%`;
  }
  if (dir === 'BEARISH' && winLo != null && tpLo > 0 && winLo < tpLo) {
    const pct = ((winLo / entry - 1) * 100).toFixed(2);
    return `AI underestimated — stock fell to ₹${num(winLo,2)} (${pct}%) vs range floor ${retLo.toFixed(2)}%`;
  }
  return null;
}

function _applyTfFilter(filterId, listId, cardSelector) {
  const bar = document.getElementById(filterId);
  if (!bar) return;
  // Reset to ALL and re-clone pills to drop stale listeners
  bar.querySelectorAll('.tf-pill').forEach(pill => {
    const fresh = pill.cloneNode(true);
    pill.parentNode.replaceChild(fresh, pill);
  });
  bar.querySelectorAll('.tf-pill').forEach(p => p.classList.remove('active'));
  bar.querySelector('.tf-pill[data-tf="ALL"]')?.classList.add('active');
  bar.querySelectorAll('.tf-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      bar.querySelectorAll('.tf-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      const tf = pill.dataset.tf;
      document.getElementById(listId)?.querySelectorAll(cardSelector).forEach(card => {
        card.style.display = (tf === 'ALL' || card.dataset.tf === tf) ? '' : 'none';
      });
    });
  });
}

function renderValidationHistoryCard(h) {
  const hitClass = h.validation_result === 'HIT' ? 'hit' : 'miss';
  const dirKey   = (h.direction || 'NEUTRAL').toUpperCase();
  const dirCssKey = dirKey === 'BULLISH' ? 'BULLISH' : dirKey === 'BEARISH' ? 'BEARISH' : 'NEUTRAL';
  const tpLo  = h.target_price_lo, tpHi = h.target_price_hi;
  const retLo = h.predicted_return_lo ?? 0, retHi = h.predicted_return_hi ?? 0;
  const entry = h.current_price || 0;
  const winHi = h.window_high, winLo = h.window_low;
  const tf    = h.timeframe || '';

  const missReason = h.validation_result === 'MISS' ? getMissReason(h) : null;
  const hitNote    = h.validation_result === 'HIT'  ? getHitNote(h)   : null;

  function pct(p) { return entry > 0 ? ((p / entry - 1) * 100).toFixed(2) : '?'; }

  // Graded price-hit: MIDPOINT_HIT (touched midpoint) > RANGE_HIT (entered range) > MISS.
  // point_reached = the extreme price the stock actually reached toward the target.
  const GRADE_BADGE = {
    'MIDPOINT_HIT': { cls: 'midpoint', label: '🎯 Midpoint hit' },
    'RANGE_HIT':    { cls: 'range',    label: '◐ Range hit' },
    'MISS':         { cls: 'miss',     label: '✕ Missed' },
  };
  const gradeInfo = h.hit_grade ? GRADE_BADGE[h.hit_grade] : null;
  const midpoint  = (tpLo && tpHi) ? (tpLo + tpHi) / 2 : null;

  // Price the stock actually reached toward the target. Prefer the stored
  // point_reached; otherwise derive it from the realized window so the reached
  // price is always shown — including on misses. Bullish → window high (best
  // upward point), bearish → window low (best downward point), neutral → close.
  const _isBull = dirKey.includes('BULL');
  const _isBear = dirKey.includes('BEAR');
  let reachedPrice = h.point_reached;
  if (reachedPrice == null) {
    if (_isBull && winHi != null)      reachedPrice = winHi;
    else if (_isBear && winLo != null) reachedPrice = winLo;
    else if (h.actual_price_at_validation != null) reachedPrice = h.actual_price_at_validation;
    else if (winHi != null)            reachedPrice = winHi;
  }
  const reachedStr = (reachedPrice != null && entry > 0)
    ? (midpoint != null
        ? `Midpoint ₹${num(midpoint,2)} · reached ₹${num(reachedPrice,2)} <span class="vh-pct">(${pct(reachedPrice) >= 0 ? '+' : ''}${pct(reachedPrice)}%)</span>`
        : `Reached ₹${num(reachedPrice,2)} <span class="vh-pct">(${pct(reachedPrice) >= 0 ? '+' : ''}${pct(reachedPrice)}%)</span>`)
    : null;

  const rangeStr = (tpLo && tpHi)
    ? `₹${num(tpLo,2)} – ₹${num(tpHi,2)} <span class="vh-pct">(${retLo >= 0 ? '+' : ''}${retLo.toFixed(2)}% to ${retHi >= 0 ? '+' : ''}${retHi.toFixed(2)}%)</span>`
    : `${retLo >= 0 ? '+' : ''}${retLo.toFixed(2)}% to ${retHi >= 0 ? '+' : ''}${retHi.toFixed(2)}%`;

  const windowStr = (winHi != null && winLo != null && entry > 0)
    ? `High ₹${num(winHi,2)} <span class="vh-pct">(${pct(winHi) >= 0 ? '+' : ''}${pct(winHi)}%)</span> &nbsp; Low ₹${num(winLo,2)} <span class="vh-pct">(${pct(winLo)}%)</span>`
    : (h.actual_price_at_validation ? `Close ₹${num(h.actual_price_at_validation,2)} <span class="vh-pct">(${(h.actual_return_at_validation??0).toFixed(2)}%)</span>` : '—');

  return `
    <div class="validation-history-card ${hitClass}" data-tf="${tf}">
      <div class="vh-header">
        <span class="vh-ticker">${h.ticker}</span>
        <span class="vh-tf">${tf}</span>
        <span class="dir-badge dir-${dirCssKey}" title="${h.direction || 'NEUTRAL'}">${dirLabel(h.direction || 'NEUTRAL')}</span>
        ${_srcTag(h.snapshot_source)}
        <span class="vh-result vh-${hitClass}">${h.validation_result}</span>
        ${gradeInfo ? `<span class="grade-badge grade--${gradeInfo.cls}">${gradeInfo.label}</span>` : ''}
        ${missReason ? `<span class="miss-reason-badge miss-reason--${missReason.cls}">${missReason.label}</span>` : ''}
        ${hitNote    ? `<span class="miss-reason-badge miss-reason--outperformed">AI underestimated</span>` : ''}
      </div>
      <div class="vh-details">
        <div class="vh-item">
          <span class="vh-label">Predicted Range</span>
          <span class="vh-range">${rangeStr}</span>
        </div>
        <div class="vh-item">
          <span class="vh-label">${tf} Window</span>
          <span class="vh-actual">${windowStr}</span>
        </div>
        ${reachedStr ? `<div class="vh-item">
          <span class="vh-label">Price Reached</span>
          <span class="vh-actual">${reachedStr}</span>
        </div>` : ''}
      </div>
      ${missReason ? `<div class="vh-miss-detail">${missReason.detail}</div>` : ''}
      ${hitNote    ? `<div class="vh-miss-detail vh-hit-note">${hitNote}</div>` : ''}
      <div class="vh-footer">
        <span class="vh-label">Prediction: ${(h.created_at || h.prediction_date || '').slice(0,10)}</span>
        <span class="vh-label">Target: ${(h.validation_target_date || '').slice(0,10)}</span>
      </div>
    </div>
  `;
}

// ── Validation model source (AI / ML / Both) ─────────────────────────────────
let _valSource = 'both';
let _lastValSumm = null;
let _lastValPending = [];   // raw pending rows (unfiltered) — re-filtered by the source toggle
let _lastValHistory = [];   // raw validated rows (unfiltered) — re-filtered by the source toggle

// Is this snapshot from the standalone ML quantile model (vs the AI/LLM path)?
function _valSrcIsMl(src) { return String(src || '').toLowerCase() === 'ml'; }

// Model-source tag badge shown on each validation card.
function _srcTag(src) {
  return _valSrcIsMl(src)
    ? '<span class="src-tag src-tag--ml" title="Standalone ML quantile model">🤖 ML</span>'
    : '<span class="src-tag src-tag--ai" title="AI / LLM forecast">✦ AI</span>';
}

// Does a record match the currently-selected source toggle?
function _valSourceMatch(src) {
  if (_valSource === 'ml') return _valSrcIsMl(src);
  if (_valSource === 'ai') return !_valSrcIsMl(src);
  return true;  // 'both'
}

function setValSource(src) {
  _valSource = src;
  document.querySelectorAll('.val-source-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.vsource === src));
  if (_lastValSumm) _applyValStats();
  _renderValidationLists();  // re-filter pending/history/miss lists by the new source
}

// Render the validation stat cards for the currently-selected model source.
// Headline = all-prediction hit rate (the honest complete metric): it counts every
// validated call — directional AND the range-only NEUTRAL calls the engine makes
// when next-move direction is genuinely unpredictable (e.g. 1D). The directional
// breakdown is shown as a sub-note. ML-only keeps its own directional bucket.
function _applyValStats() {
  const summData = _lastValSumm;
  if (!summData) return;
  const summaryRaw = summData.summary || {};
  const bySrc = summaryRaw.by_source || {};
  const directional = _valSource === 'ml' ? (bySrc.ml || {})
    : _valSource === 'ai' ? (bySrc.ai || {})
    : (summaryRaw.directional || {});
  const allPreds  = summaryRaw.all || {};
  const highConf  = summaryRaw.high_conf || {};

  ['INTRADAY', '1D'].forEach(tf => {
    const dStat = directional[tf];         // directional-only (NEUTRAL excluded)
    const aStat = allPreds[tf];            // all predictions (the honest headline)
    const el = document.getElementById(`vstat-${tf.toLowerCase()}`);
    const subEl = document.getElementById(`vstat-${tf.toLowerCase()}-sub`);
    // ML-only source has no all-bucket split, so it falls back to its directional stat.
    const headStat = _valSource === 'ml' ? dStat : aStat;
    if (el && headStat && headStat.total) {
      el.textContent = `${headStat.hit_rate_pct || 0}%`;
      if (subEl) {
        const dirNote = (_valSource !== 'ml' && dStat && dStat.total)
          ? ` · dir ${dStat.hit_rate_pct || 0}% (${dStat.hits}/${dStat.total})`
          : '';
        subEl.textContent = `${headStat.hits}/${headStat.total} validated${dirNote}`;
      }
    } else if (el) {
      el.textContent = '—';
      if (subEl) subEl.textContent = 'no data yet';
    }
  });

  // HIGH-confidence card is AI's profit bucket; only meaningful for AI/Both.
  const hcEl = document.getElementById('vstat-highconf');
  if (hcEl) {
    if (_valSource === 'ml') {
      hcEl.textContent = 'n/a';
      const hcSub = document.getElementById('vstat-highconf-sub');
      if (hcSub) hcSub.textContent = 'AI-only metric';
    } else {
      let hcHits = 0, hcTotal = 0;
      Object.entries(highConf).forEach(([tf, s]) => {
        if (tf === '5D') return;
        hcHits += (s.hits || 0); hcTotal += (s.total || 0);
      });
      const hcPct = hcTotal > 0 ? Math.round(hcHits / hcTotal * 1000) / 10 : 0;
      hcEl.textContent = hcTotal > 0 ? `${hcPct}%` : '—';
      const hcSub = document.getElementById('vstat-highconf-sub');
      if (hcSub) hcSub.textContent = hcTotal > 0 ? `${hcHits}/${hcTotal} HIGH-conf` : 'no HIGH-conf yet';
    }
  }

  // Agreement hint: when ML & AI agreed on direction, how often both hit.
  const hintEl = document.getElementById('val-agree-hint');
  if (hintEl) {
    const agree = summaryRaw.agreement || {};
    let aHits = 0, aTotal = 0;
    Object.values(agree).forEach(s => { aHits += (s.hits || 0); aTotal += (s.total || 0); });
    hintEl.textContent = aTotal > 0
      ? `🤝 When ML + AI agree: ${Math.round(aHits / aTotal * 1000) / 10}% both hit (${aHits}/${aTotal})`
      : '';
  }
}

// Render the pending / history / miss lists for the currently-selected model source
// (AI / ML / Both). Reads the cached raw lists so the toggle re-filters with no refetch.
function _renderValidationLists() {
  const pending = document.getElementById('pending-validation-list');
  const history = document.getElementById('validation-history-list');
  const missBreakdown = document.getElementById('validation-miss-breakdown');
  const missList = document.getElementById('validation-miss-list');
  const todayStr = new Date().toISOString().slice(0, 10);
  const srcLabel = _valSource === 'ml' ? 'ML' : _valSource === 'ai' ? 'AI' : 'AI + ML';

  const pendingList = (_lastValPending || []).filter(p => _valSourceMatch(p.snapshot_source));
  const historyList = (_lastValHistory || []).filter(h => _valSourceMatch(h.snapshot_source));

  // Render pending list
  if (pending) {
    if (pendingList.length === 0) {
      pending.innerHTML = `<div class="empty-state"><div class="empty-icon">✓</div>No pending ${srcLabel} validations.</div>`;
    } else {
      pending.innerHTML = pendingList.map(p => {
        const tpLo = p.target_price_lo, tpHi = p.target_price_hi;
        const hasPriceTarget = tpLo && tpHi;
        const meanTarget = hasPriceTarget ? (tpLo + tpHi) / 2 : null;
        const meanPct = (meanTarget != null && p.current_price > 0)
          ? ((meanTarget / p.current_price - 1) * 100) : null;
        const dirKey = (p.direction || 'NEUTRAL').toUpperCase();
        const dirCssKey = dirKey === 'BULLISH' ? 'BULLISH' : dirKey === 'BEARISH' ? 'BEARISH' : 'NEUTRAL';
        const isOverdue = p.validation_target_date <= todayStr;
        const dueBadge = isOverdue ? `<span class="val-overdue-badge">OVERDUE</span>` : '';
        return `
          <div class="validation-card${isOverdue ? ' val-overdue' : ''}" data-tf="${p.timeframe}">
            <div class="val-header">
              <span class="val-ticker">${p.ticker}</span>
              <span class="val-tf">${p.timeframe}</span>
              <span class="dir-badge dir-${dirCssKey}" title="${p.direction || 'NEUTRAL'}">${dirLabel(p.direction || 'NEUTRAL')}</span>
              ${_srcTag(p.snapshot_source)}
              <span class="val-conf conf-${p.confidence}">${p.confidence}</span>
              ${dueBadge}
            </div>
            <div class="val-details">
              <div class="val-item">
                <span class="val-label">Entry</span>
                <span class="val-price">₹${num(p.current_price, 2)}</span>
              </div>
              <div class="val-item">
                <span class="val-label">Target Range</span>
                <span class="val-range">${hasPriceTarget ? `₹${num(tpLo, 2)} – ₹${num(tpHi, 2)}` : `${num(p.predicted_return_lo, 2)}% to ${num(p.predicted_return_hi, 2)}%`}</span>
              </div>
              ${meanTarget != null ? `
              <div class="val-item">
                <span class="val-label">Mean Target</span>
                <span class="val-price" title="The midpoint the hit-check aims for — the price the stock must touch for a MIDPOINT_HIT">₹${num(meanTarget, 2)}${meanPct != null ? ` <span class="vh-pct">(${meanPct >= 0 ? '+' : ''}${meanPct.toFixed(2)}%)</span>` : ''}</span>
              </div>` : ''}
              <div class="val-item">
                <span class="val-label">Validation Due</span>
                <span class="val-date">${p.validation_target_date}</span>
              </div>
            </div>
          </div>
        `;
      }).join('');
    }
  }

  // Render history
  if (history) {
    if (historyList.length === 0) {
      history.innerHTML = `<div class="empty-state"><div class="empty-icon">◧</div>No ${srcLabel} validation history yet.</div>`;
    } else {
      history.innerHTML = historyList.map(h => renderValidationHistoryCard(h)).join('');
    }
  }

  // Wire TF filter pills after both lists are populated
  _applyTfFilter('pending-tf-filter', 'pending-validation-list', '.validation-card');
  _applyTfFilter('history-tf-filter', 'validation-history-list', '.validation-history-card');

  // Render miss analysis tab
  const misses = historyList.filter(h => h.validation_result === 'MISS');
  if (missList) {
    if (misses.length === 0) {
      if (missBreakdown) missBreakdown.innerHTML = '';
      missList.innerHTML = `<div class="empty-state"><div class="empty-icon">✓</div>No ${srcLabel} misses in recent history.</div>`;
    } else {
      const reasons = { 'wrong-dir': 0, 'fell-short': 0, 'overbullish': 0, 'overbearish': 0 };
      const labels = { 'wrong-dir': 'Wrong direction', 'fell-short': 'Fell short', 'overbullish': 'AI missed bullish', 'overbearish': 'AI missed bearish' };
      misses.forEach(h => { const r = getMissReason(h); if (r) reasons[r.cls] = (reasons[r.cls] || 0) + 1; });
      if (missBreakdown) {
        missBreakdown.innerHTML = `
          <div class="miss-breakdown">
            <span class="miss-breakdown-title">${srcLabel} Miss Breakdown (${misses.length} total)</span>
            ${Object.entries(reasons).filter(([, n]) => n > 0).map(([cls, n]) => `
              <span class="miss-reason-badge miss-reason--${cls}">${labels[cls]}: ${n}</span>
            `).join('')}
          </div>
        `;
      }
      missList.innerHTML = misses.map(h => renderValidationHistoryCard(h)).join('');
    }
  }
}

async function loadValidation() {
  // Pre-populate the AI-learn panel from the last saved learnings.json — no button click needed.
  fetch('/api/learnings').then(r => r.json()).then(data => {
    if (data.status !== 'no_data' && data.status !== 'insufficient_data' && data.total_validated >= 10) {
      renderAiLearnPanel(data);
    }
  }).catch(() => {});

  const pending = document.getElementById('pending-validation-list');
  const history = document.getElementById('validation-history-list');
  const missBreakdown = document.getElementById('validation-miss-breakdown');
  const missList = document.getElementById('validation-miss-list');

  showEl('validation-loading');
  try {
    // Load summary and history
    let summData = await (await fetch('/api/validation/summary', { cache: 'no-store' })).json();

    // Load pending
    const pendRes = await fetch('/api/validation/pending', { cache: 'no-store' });
    const pendData = await pendRes.json();
    const pendingList = pendData.pending || [];
    const dueCount = pendData.due_count ?? 0;

    // Auto-execute validation if any items are due today — do this BEFORE rendering
    // stats so the cards always show post-validation numbers.
    let autoValidated = 0;
    if (dueCount > 0) {
      try {
        const execRes = await fetch('/api/validation/execute', { method: 'POST', cache: 'no-store' });
        if (execRes.ok) {
          const execData = await execRes.json();
          autoValidated = execData.validated || 0;
          if (autoValidated > 0) {
            const hits   = execData.hits   ?? 0;
            const misses = execData.misses ?? 0;
            const toast = document.createElement('div');
            toast.className = 'val-toast';
            toast.innerHTML = `✓ Validated ${autoValidated}: <span class="val-toast-hit">${hits} HIT</span> · <span class="val-toast-miss">${misses} MISS</span>`;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 6000);
            // Reload both pending and summary so stat cards reflect new validations
            const [summRes2, pendRes2] = await Promise.all([
              fetch('/api/validation/summary', { cache: 'no-store' }),
              fetch('/api/validation/pending', { cache: 'no-store' }),
            ]);
            summData = await summRes2.json();
            const pendData2 = await pendRes2.json();
            pendingList.length = 0;
            (pendData2.pending || []).forEach(p => pendingList.push(p));
            // If pending queue is now empty, switch to History tab
            if (pendingList.length === 0) {
              document.querySelectorAll('.vtab').forEach(t => t.classList.remove('active'));
              document.querySelectorAll('.vtab-content').forEach(c => c.classList.remove('active'));
              document.querySelector('.vtab[data-vtab="history"]')?.classList.add('active');
              document.getElementById('vtab-history')?.classList.add('active');
            }
          }
        }
      } catch (_) {}
    }

    // Update summary stats — show directional hit rate (BULLISH+BEARISH) as headline,
    // all-predictions as a footnote so NEUTRAL misses don't bury the signal quality.
    // Source-aware: AI-only / ML-only / Both, driven by the model toggle.
    _lastValSumm = summData;
    _applyValStats();
    const pendingEl = document.getElementById('vstat-pending');
    const pendingSubEl = document.getElementById('vstat-pending-sub');
    if (pendingEl) pendingEl.textContent = pendingList.length;
    if (pendingSubEl) {
      pendingSubEl.textContent = `${pendingList.length} upcoming`;
      pendingSubEl.style.color = '';
    }

    // Cache the raw (unfiltered) lists so the AI/ML/Both toggle can re-filter them
    // instantly without a network refetch, then render for the current source.
    _lastValPending = pendingList.slice();
    _lastValHistory = summData.history || [];
    _renderValidationLists();
  } catch (e) {
    console.warn('Validation load failed:', e);
    if (pending) pending.innerHTML = `<div class="error-state">Error loading validation data: ${e.message}</div>`;
  } finally {
    hideEl('validation-loading');
  }
}

// Validation tab switching
document.querySelectorAll('.vtab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.vtab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.vtab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    const vtabId = 'vtab-' + tab.dataset.vtab;
    document.getElementById(vtabId)?.classList.add('active');
  });
});

// Execute validation button
document.getElementById('validation-execute')?.addEventListener('click', async () => {
  const loadingEl = document.getElementById('validation-loading');
  if (loadingEl) loadingEl.classList.remove('hidden');
  
  try {
    const res = await fetch('/api/validation/execute', {
      method: 'POST',
      cache: 'no-store',
    });
    if (!res.ok) throw new Error('Validation failed');
    const data = await res.json();
    if (data.deferred) {
      alert(data.message || 'Market is closed today. Backdated predictions will be processed when historical data is available.');
    } else {
      alert(`✓ Validated ${data.validated ?? 0} predictions`);
    }
    loadValidation();
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    if (loadingEl) loadingEl.classList.add('hidden');
  }
});

// Re-validate all history with correct historical prices
document.getElementById('validation-revalidate')?.addEventListener('click', async () => {
  const loadingEl = document.getElementById('validation-loading');
  if (loadingEl) loadingEl.classList.remove('hidden');
  try {
    const res = await fetch('/api/validation/revalidate-all', { method: 'POST', cache: 'no-store' });
    if (!res.ok) throw new Error('Re-validation failed');
    const data = await res.json();
    alert(`↺ Re-validated ${data.revalidated} records with correct historical prices`);
    loadValidation();
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    if (loadingEl) loadingEl.classList.add('hidden');
  }
});

// Shared renderer for the AI-learn panel — called on startup (from JSON) and after button click.
function renderAiLearnPanel(data, { showToast = false, newInRun = null } = {}) {
  const panel = document.getElementById('ai-learn-panel');
  if (!panel) return;

  // Render one source block (AI or ML) into its notes <ul> + accuracy <span>.
  const _renderBlock = (block, notesId, accId, newN) => {
    const notesList = document.getElementById(notesId);
    const accuracyEl = document.getElementById(accId);
    if (!notesList || !accuracyEl) return null;
    const b = block || {};
    const notes = b.calibration_notes || [];
    const total = b.total_validated || 0;
    const acc = b.overall_accuracy != null ? (b.overall_accuracy * 100).toFixed(1) : null;
    if (notes.length === 0) {
      notesList.innerHTML = total > 0
        ? '<li>No strong patterns detected yet — more validation data needed.</li>'
        : '<li>No validated predictions for this model yet.</li>';
    } else {
      notesList.innerHTML = notes.map(n => {
        const cls = /^(WARN|MISS)/.test(n) ? 'warn'
          : n.startsWith('CAUTION') ? 'caution'
          : n.startsWith('OK') ? 'ok' : '';
        return `<li class="${cls}">${n}</li>`;
      }).join('');
    }
    const newLabel = newN != null ? ` (+${newN} new)` : '';
    accuracyEl.textContent = acc
      ? `N=${total}${newLabel} validated · ${acc}% overall accuracy`
      : `N=${total} validated`;
    return acc;
  };

  // AI block: prefer the explicit `ai` sub-block, fall back to top-level (backward compat).
  const aiBlock = data.ai || data;
  const mlBlock = data.ml || {};
  const updatedAt = data.updated_at ? ` · Updated ${data.updated_at}` : '';
  const aiAcc = _renderBlock(aiBlock, 'ai-learn-notes', 'ai-learn-accuracy', aiBlock === data ? newInRun : (aiBlock.new_in_this_run ?? null));
  const mlAcc = _renderBlock(mlBlock, 'ai-learn-ml-notes', 'ai-learn-ml-accuracy', mlBlock.new_in_this_run ?? null);

  // Append the shared "Updated …" stamp to the AI accuracy line.
  const aiAccEl = document.getElementById('ai-learn-accuracy');
  if (aiAccEl && updatedAt) aiAccEl.textContent += updatedAt;

  // Collapsed-state summary line so the headline is visible without expanding.
  const metaEl = document.getElementById('ai-learn-toggle-meta');
  if (metaEl) {
    const parts = [];
    if (aiAcc) parts.push(`AI ${aiAcc}%`);
    if (mlAcc) parts.push(`ML ${mlAcc}%`);
    metaEl.textContent = parts.join(' · ');
  }

  panel.classList.remove('hidden');
  // Default collapsed — the user does not want to see the full panel every visit.
  const collapsed = localStorage.getItem('aiLearnCollapsed') !== '0';
  panel.classList.toggle('collapsed', collapsed);
  const toggleEl = document.getElementById('ai-learn-toggle');
  if (toggleEl) toggleEl.setAttribute('aria-expanded', String(!collapsed));

  if (showToast) {
    const total = (aiBlock.total_validated || 0);
    const toast = document.createElement('div');
    toast.className = 'val-toast';
    toast.textContent = aiAcc ? `🧠 AI updated — ${aiAcc}% accuracy (N=${total})` : '🧠 AI + ML learning updated';
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }
}

// Collapsible Self-Learning panel — persist the open/closed choice so it stays out of
// the way (default collapsed) but remembers when the user expands it.
(function initAiLearnToggle() {
  const toggle = document.getElementById('ai-learn-toggle');
  const panel = document.getElementById('ai-learn-panel');
  if (!toggle || !panel) return;
  const apply = () => {
    const collapsed = panel.classList.toggle('collapsed');
    localStorage.setItem('aiLearnCollapsed', collapsed ? '1' : '0');
    toggle.setAttribute('aria-expanded', String(!collapsed));
  };
  toggle.addEventListener('click', apply);
  toggle.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); apply(); }
  });
})();

// Improve AI — trigger self-learning analysis from validation history
document.getElementById('ai-learn-btn')?.addEventListener('click', async () => {
  const btn = document.getElementById('ai-learn-btn');
  btn.disabled = true;
  btn.textContent = '🧠 Analyzing...';
  try {
    const res = await fetch('/api/ai-learn', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: true }) });
    if (!res.ok) throw new Error('Analysis failed');
    const data = await res.json();
    renderAiLearnPanel(data, { showToast: true, newInRun: data.new_in_this_run ?? null });
    if (data.pruned != null) console.log(`Pruned ${data.pruned} validated snapshots from DB.`);
  } catch (e) {
    alert('Improve AI error: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '🧠 Improve AI';
  }
});

// Refresh validation
document.getElementById('validation-refresh')?.addEventListener('click', loadValidation);

// ── Init ──────────────────────────────────────────────────────────────────────
(async () => {
  // Check NSE market status on load — shows banner if closed/holiday/weekend
  fetch('/api/market-status', { cache: 'no-store' })
    .then(r => r.json())
    .then(d => { if (!d.is_trading_day || d.status === 'PRE_MARKET' || d.status === 'POST_MARKET') showMarketClosedBanner(d); })
    .catch(() => {});

  document.getElementById('news-modal-close')?.addEventListener('click', () => document.getElementById('news-modal')?.classList.add('hidden'));
  document.getElementById('news-modal')?.addEventListener('click', e => { if (e.target.id === 'news-modal') document.getElementById('news-modal')?.classList.add('hidden'); });

  loadUniverse(); // fire in background — not needed before first render
  switchView('dashboard');
})();
