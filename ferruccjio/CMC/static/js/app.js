/*
CMC Terminal Pro — Frontend Dashboard Logic
Handles SSE Real-Time Stream, TradingView Lightweight Charts, Alert Audio/Toasts, Table Filtering, and REST API Hub.
*/

// State Management
const STATE = {
    coins: [],
    selectedCoinId: 1, // Default BTC
    timeframe: "1h",
    sortBy: "mc",
    sortOrder: "desc",
    searchQuery: "",
    selectedCategory: "all",
    limit: 50,
    offset: 0,
    soundEnabled: true,
    activeTab: "market",
    chart: null,
    candleSeries: null,
    volumeSeries: null,
    fsChart: null,
    fsCandleSeries: null,
    fsVolumeSeries: null,
    lastCandle: null,
    lastFsCandle: null,
    lastPrices: {}
};

// ══════════════════════════════════════════════════════════════════════════════
// INITIALIZATION ON DOM LOAD
// ══════════════════════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
    try { initChart(); } catch (err) { console.warn("Chart init:", err); }
    try { initEventListeners(); } catch (err) { console.warn("Listeners init:", err); }
    try { fetchStatus(); } catch (err) { console.warn("Status init:", err); }
    try { fetchCategories(); } catch (err) { console.warn("Categories init:", err); }
    try { fetchCoins(); } catch (err) { console.warn("Coins init:", err); }
    try { fetchAlerts(); } catch (err) { console.warn("Alerts init:", err); }
    try { initSSE(); } catch (err) { console.warn("SSE init:", err); }
    
    // Refresh table and status continuously as rock-solid backup to SSE
    setInterval(() => { try { fetchCoins(); } catch (e) {} }, 3000);
    setInterval(() => { try { fetchStatus(); } catch (e) {} }, 2000);

    // Refresh charts every 30 seconds as requested
    setInterval(() => {
        try {
            if (STATE.selectedCoinId) {
                loadChartData(STATE.selectedCoinId, STATE.timeframe, false);
                const modal = document.getElementById("fullscreen-chart-modal");
                if (modal && !modal.classList.contains("hidden")) {
                    loadFullscreenChartData(STATE.selectedCoinId, STATE.timeframe, false);
                }
            }
        } catch (err) {
            console.warn("30s chart sync error:", err);
        }
    }, 30000);
});

async function fetchStatus() {
    try {
        const res = await fetch("/api/status");
        if (!res.ok) return;
        const data = await res.json();
        const tpEl = document.getElementById("kpi-throughput");
        const upEl = document.getElementById("kpi-uptime");
        const stEl = document.getElementById("status-indicator-text");
        const dotEl = document.getElementById("status-dot");
        if (tpEl && data.throughput_msg_per_sec !== undefined) tpEl.textContent = `${data.throughput_msg_per_sec} msg/s`;
        if (upEl && data.uptime_seconds !== undefined) upEl.textContent = formatUptime(data.uptime_seconds);
        if (stEl && data.status) stEl.textContent = data.status;
        if (dotEl) dotEl.style.backgroundColor = (data.status === "LIVE" || data.status === "POLLING") ? "#10b981" : "#f59e0b";
    } catch (err) {
        console.warn("Status poll error:", err);
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// SERVER-SENT EVENTS (SSE) STREAMING
// ══════════════════════════════════════════════════════════════════════════════

function initSSE() {
    const evtSource = new EventSource("/api/stream");

    evtSource.onmessage = (event) => {
        try {
            const payload = JSON.parse(event.data);
            
            // Update Top Navbar KPIs
            if (payload.throughput) {
                document.getElementById("kpi-throughput").textContent = `${payload.throughput} msg/s`;
            }
            if (payload.uptime) {
                document.getElementById("kpi-uptime").textContent = formatUptime(payload.uptime);
            }

            // Update Ticker Tape, Table Cell Flashes & Live Candlestick
            if (payload.prices && payload.prices.length > 0) {
                updateTickerTape(payload.prices);
                updateTablePrices(payload.prices);
                updateLiveCandles(payload.prices);
            }

            // Check & Trigger Alert Notifications
            if (payload.new_alerts && payload.new_alerts.length > 0) {
                payload.new_alerts.forEach(alert => {
                    triggerAlertNotification(alert);
                });
                fetchAlerts(); // Refresh alert manager tab
            }
        } catch (err) {
            console.error("SSE parse error:", err);
        }
    };

    evtSource.onerror = () => {
        document.getElementById("status-indicator-text").textContent = "RICONNESSIONE...";
        document.getElementById("status-dot").style.backgroundColor = "#f59e0b"; // Amber
    };

    evtSource.onopen = () => {
        document.getElementById("status-indicator-text").textContent = "LIVE STREAM";
        document.getElementById("status-dot").style.backgroundColor = "#10b981"; // Emerald
    };
}

function updateLiveCandles(prices) {
    if (!STATE.selectedCoinId) return;
    const activePriceObj = prices.find(p => p.id === STATE.selectedCoinId);
    if (!activePriceObj || !activePriceObj.p) return;

    const p = activePriceObj.p;
    const tfSecMap = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 };
    const tfSec = tfSecMap[STATE.timeframe] || 3600;
    const nowSec = Math.floor(Date.now() / 1000);
    const tzOffsetSec = -new Date().getTimezoneOffset() * 60;
    const currentBucket = (Math.floor(nowSec / tfSec) * tfSec) + tzOffsetSec;

    if (STATE.candleSeries && STATE.lastCandle) {
        if (currentBucket === STATE.lastCandle.time || currentBucket < STATE.lastCandle.time + tfSec) {
            STATE.lastCandle.high = Math.max(STATE.lastCandle.high, p);
            STATE.lastCandle.low = Math.min(STATE.lastCandle.low, p);
            STATE.lastCandle.close = p;
            try { STATE.candleSeries.update(STATE.lastCandle); } catch(e) {}
        } else if (currentBucket >= STATE.lastCandle.time + tfSec) {
            const newCandle = { time: currentBucket, open: p, high: p, low: p, close: p };
            STATE.lastCandle = newCandle;
            try { STATE.candleSeries.update(newCandle); } catch(e) {}
        }
    }

    if (STATE.fsCandleSeries && STATE.lastFsCandle) {
        if (currentBucket === STATE.lastFsCandle.time || currentBucket < STATE.lastFsCandle.time + tfSec) {
            STATE.lastFsCandle.high = Math.max(STATE.lastFsCandle.high, p);
            STATE.lastFsCandle.low = Math.min(STATE.lastFsCandle.low, p);
            STATE.lastFsCandle.close = p;
            try { STATE.fsCandleSeries.update(STATE.lastFsCandle); } catch(e) {}
        } else if (currentBucket >= STATE.lastFsCandle.time + tfSec) {
            const newCandle = { time: currentBucket, open: p, high: p, low: p, close: p };
            STATE.lastFsCandle = newCandle;
            try { STATE.fsCandleSeries.update(newCandle); } catch(e) {}
        }
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// TICKER TAPE & TABLE LIVE UPDATES
// ══════════════════════════════════════════════════════════════════════════════

function updateTickerTape(prices) {
    const tickerContainer = document.getElementById("ticker-content");
    if (!tickerContainer) return;

    // Only update if we have data and ticker is empty or every 10s
    if (tickerContainer.children.length === 0 || Math.random() < 0.1) {
        let html = "";
        prices.slice(0, 20).forEach(p => {
            const coin = STATE.coins.find(c => c.id === p.id);
            const sym = coin ? coin.symbol : `#${p.id}`;
            const priceStr = formatPrice(p.p);
            const chg = p.p24h || 0;
            const badgeCol = chg >= 0 ? "text-emerald-400" : "text-rose-400";
            const arrow = chg >= 0 ? "▲" : "▼";
            
            html += `
                <div class="ticker-item cursor-pointer hover:bg-gray-800/50 transition-colors" onclick="selectCoin(${p.id})">
                    <span class="font-bold text-white mr-2">${sym}</span>
                    <span class="text-gray-300 mr-2">${priceStr}</span>
                    <span class="${badgeCol} font-semibold">${arrow} ${Math.abs(chg).toFixed(2)}%</span>
                </div>
            `;
        });
        // Duplicate for seamless infinite scrolling loop
        tickerContainer.innerHTML = html + html;
    }
}

function updateTablePrices(prices) {
    prices.forEach(p => {
        const rowPriceEl = document.getElementById(`price-cell-${p.id}`);
        if (rowPriceEl) {
            const oldPrice = STATE.lastPrices[p.id];
            const newPrice = p.p;
            STATE.lastPrices[p.id] = newPrice;

            rowPriceEl.textContent = formatPrice(newPrice);

            if (p.flash === 1 || (oldPrice && newPrice > oldPrice)) {
                rowPriceEl.classList.remove("flash-bear");
                void rowPriceEl.offsetWidth; // Trigger reflow
                rowPriceEl.classList.add("flash-bull");
            } else if (p.flash === -1 || (oldPrice && newPrice < oldPrice)) {
                rowPriceEl.classList.remove("flash-bull");
                void rowPriceEl.offsetWidth;
                rowPriceEl.classList.add("flash-bear");
            }
        }
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// CRYPTO TABLE & DATA FETCHING
// ══════════════════════════════════════════════════════════════════════════════

async function fetchCoins() {
    try {
        const url = `/api/coins?sort_by=${STATE.sortBy}&order=${STATE.sortOrder}&limit=${STATE.limit}&offset=${STATE.offset}` +
                    (STATE.searchQuery ? `&search=${encodeURIComponent(STATE.searchQuery)}` : "") +
                    (STATE.selectedCategory !== "all" ? `&category=${encodeURIComponent(STATE.selectedCategory)}` : "");

        const res = await fetch(url);
        const json = await res.json();
        STATE.coins = json.data || [];

        renderTable();
        
        // If no coin selected yet, select first
        if (STATE.coins.length > 0 && !STATE.selectedCoinId) {
            selectCoin(STATE.coins[0].id);
        } else if (STATE.selectedCoinId) {
            // Update selected coin detail if active
            updateCoinMetadata(STATE.selectedCoinId);
        }

        // If table still empty on startup, retry sooner
        if (STATE.coins.length === 0) {
            setTimeout(fetchCoins, 1500);
        }
    } catch (err) {
        console.error("Fetch coins error:", err);
        setTimeout(fetchCoins, 2000);
    }
}

function renderTable() {
    const tbody = document.getElementById("crypto-table-body");
    if (!tbody) return;

    if (STATE.coins.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-center py-12 text-gray-500 font-mono">Nessuna criptovaluta trovata nell'universo monitorato.</td></tr>`;
        return;
    }

    let html = "";
    STATE.coins.forEach(c => {
        STATE.lastPrices[c.id] = c.price;
        const pStr = formatPrice(c.price);
        const iconUrl = `https://s2.coinmarketcap.com/static/img/coins/64x64/${c.id}.png`;
        const isSelected = c.id === STATE.selectedCoinId;
        const rowBg = isSelected ? "bg-purple-900/20 border-l-4 border-purple-500" : "hover:bg-gray-800/40";

        html += `
            <tr class="border-b border-gray-800/60 transition-colors cursor-pointer ${rowBg}" onclick="selectCoin(${c.id})">
                <td class="py-3 px-4 text-gray-500 font-mono text-xs">${c.rank || "—"}</td>
                <td class="py-3 px-4">
                    <div class="flex items-center space-x-3">
                        <img src="${iconUrl}" onerror="this.src='https://s2.coinmarketcap.com/static/img/coins/64x64/1.png'" class="w-7 h-7 rounded-full bg-gray-800 p-0.5 shadow">
                        <div>
                            <div class="font-bold text-white text-sm flex items-center space-x-1">
                                <span>${c.symbol}</span>
                                ${isSelected ? '<span class="text-xs bg-purple-500/20 text-purple-400 px-1 rounded">ACTIVE</span>' : ''}
                            </div>
                            <div class="text-xs text-gray-400 truncate max-w-[120px]">${c.name}</div>
                        </div>
                    </div>
                </td>
                <td class="py-3 px-4 text-right font-mono font-bold text-gray-100 text-sm transition-all duration-300" id="price-cell-${c.id}">${pStr}</td>
                <td class="py-3 px-4 text-right font-mono text-xs">${formatChangeBadge(c.change_1h)}</td>
                <td class="py-3 px-4 text-right font-mono text-xs">${formatChangeBadge(c.change_24h)}</td>
                <td class="py-3 px-4 text-right font-mono text-xs">${formatChangeBadge(c.change_7d)}</td>
                <td class="py-3 px-4 text-right font-mono text-xs text-gray-300">${c.volume_24h ? '$' + formatNumber(c.volume_24h) : '—'}</td>
                <td class="py-3 px-4 text-right font-mono text-xs font-semibold text-gray-200">${c.market_cap ? '$' + formatNumber(c.market_cap) : '—'}</td>
                <td class="py-3 px-4 text-center" onclick="event.stopPropagation();">
                    <div class="flex items-center justify-center space-x-2">
                        <button onclick="selectCoin(${c.id}); switchTab('market');" title="Interactive Chart" class="p-1.5 bg-gray-800 hover:bg-purple-600 text-gray-300 hover:text-white rounded transition-colors">
                            <i data-lucide="line-chart" class="w-3.5 h-3.5"></i>
                        </button>
                        <button onclick="openAlertModal(${c.id}, '${c.symbol}', ${c.price})" title="Arm Price Alert" class="p-1.5 bg-gray-800 hover:bg-emerald-600 text-gray-300 hover:text-white rounded transition-colors">
                            <i data-lucide="bell-plus" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = html;
    if (window.lucide) window.lucide.createIcons();
}

async function fetchCategories() {
    try {
        const res = await fetch("/api/categories");
        const json = await res.json();
        const container = document.getElementById("category-pills");
        if (!container) return;

        if (!json || !json.categories || json.categories.length === 0) {
            setTimeout(fetchCategories, 2000);
            return;
        }

        let html = `<button onclick="filterCategory('all')" class="cat-pill px-3 py-1 rounded-full text-xs font-medium transition-all ${STATE.selectedCategory === 'all' ? 'bg-purple-600 text-white shadow-lg shadow-purple-500/30' : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'}">Tutti gli Asset</button>`;
        
        json.categories.slice(0, 10).forEach(cat => {
            const active = STATE.selectedCategory === cat.tag;
            const cls = active ? "bg-purple-600 text-white shadow-lg shadow-purple-500/30" : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white";
            html += `<button onclick="filterCategory('${cat.tag}')" class="cat-pill px-3 py-1 rounded-full text-xs font-medium transition-all ${cls}">${cat.translated} (${cat.count})</button>`;
        });

        container.innerHTML = html;
    } catch (err) {
        console.error("Categories error:", err);
        setTimeout(fetchCategories, 3000);
    }
}

function filterCategory(tag) {
    STATE.selectedCategory = tag;
    STATE.offset = 0;
    fetchCategories();
    fetchCoins();
}

// ══════════════════════════════════════════════════════════════════════════════
// INTERACTIVE COIN DETAIL & TRADINGVIEW LIGHTWEIGHT CHARTS
// ══════════════════════════════════════════════════════════════════════════════

async function selectCoin(coinId) {
    STATE.selectedCoinId = coinId;
    renderTable(); // Re-render to highlight active row
    // Execute both concurrently for ultra-low latency
    updateCoinMetadata(coinId);
    loadChartData(coinId, STATE.timeframe);
}

async function updateCoinMetadata(coinId) {
    try {
        const res = await fetch(`/api/coins/${coinId}`);
        const data = await res.json();

        // Update Header
        document.getElementById("detail-symbol").textContent = data.symbol;
        document.getElementById("detail-name").textContent = data.name;
        document.getElementById("detail-rank").textContent = `#${data.rank || "—"}`;
        document.getElementById("detail-price").textContent = formatPrice(data.price);
        document.getElementById("detail-icon").src = `https://s2.coinmarketcap.com/static/img/coins/64x64/${coinId}.png`;
        
        const chg24 = data.change_24h || 0;
        const chgEl = document.getElementById("detail-change");
        chgEl.innerHTML = formatChangeBadge(chg24);

        // Update Key Metrics
        const meta = data.metadata || {};
        const stats = meta.stats || {};
        
        document.getElementById("metric-ath").textContent = stats.ath ? formatPrice(stats.ath) : "—";
        document.getElementById("metric-ath-date").textContent = stats.ath_date ? new Date(stats.ath_date).toLocaleDateString() : "—";
        document.getElementById("metric-atl").textContent = stats.atl ? formatPrice(stats.atl) : "—";
        document.getElementById("metric-roi").textContent = stats.roi1y ? `${stats.roi1y > 0 ? '+' : ''}${stats.roi1y.toFixed(1)}%` : "—";

        // Supply Progress Bar
        const circ = data.supply.circulating || 0;
        const max = data.supply.max || data.supply.total || 1;
        const pct = Math.min(100, Math.max(0, (circ / max) * 100)).toFixed(1);
        document.getElementById("supply-bar-fill").style.width = `${pct}%`;
        document.getElementById("supply-text").textContent = `${pct}% Circulating (${circ ? formatNumber(circ) : '—'} ${data.symbol})`;

        // Links & Tags
        const urls = meta.urls || {};
        const linksContainer = document.getElementById("detail-links");
        let linksHtml = "";
        if (urls.website && urls.website[0]) linksHtml += `<a href="${urls.website[0]}" target="_blank" class="px-2.5 py-1 bg-gray-800 hover:bg-purple-600/30 border border-gray-700 rounded text-xs text-purple-400 hover:text-purple-300 transition-colors flex items-center space-x-1"><i data-lucide="globe" class="w-3 h-3"></i><span>Website</span></a>`;
        if (urls.whitepaper && urls.whitepaper[0]) linksHtml += `<a href="${urls.whitepaper[0]}" target="_blank" class="px-2.5 py-1 bg-gray-800 hover:bg-purple-600/30 border border-gray-700 rounded text-xs text-blue-400 hover:text-blue-300 transition-colors flex items-center space-x-1"><i data-lucide="file-text" class="w-3 h-3"></i><span>Whitepaper</span></a>`;
        if (urls.explorer && urls.explorer[0]) linksHtml += `<a href="${urls.explorer[0]}" target="_blank" class="px-2.5 py-1 bg-gray-800 hover:bg-purple-600/30 border border-gray-700 rounded text-xs text-emerald-400 hover:text-emerald-300 transition-colors flex items-center space-x-1"><i data-lucide="compass" class="w-3 h-3"></i><span>Explorer</span></a>`;
        linksContainer.innerHTML = linksHtml || `<span class="text-gray-500 text-xs">Nessun link esterno disponibile.</span>`;

        // Description
        const descEl = document.getElementById("detail-desc");
        descEl.textContent = meta.description || "Descrizione italiana non disponibile o in caricamento...";

        // Update Fullscreen Info Bar elements
        const fsAthEl = document.getElementById("fs-metric-ath");
        const fsAthDateEl = document.getElementById("fs-metric-ath-date");
        const fsAtlEl = document.getElementById("fs-metric-atl");
        const fsRoiEl = document.getElementById("fs-metric-roi");
        const fsSupplyTextEl = document.getElementById("fs-supply-text");
        const fsSupplyFillEl = document.getElementById("fs-supply-bar-fill");
        const fsLinksEl = document.getElementById("fs-links");
        const fsDescBodyEl = document.getElementById("fs-desc-body");
        const fsDescTitleEl = document.getElementById("fs-desc-title");

        if (fsAthEl) fsAthEl.textContent = stats.ath ? formatPrice(stats.ath) : "—";
        if (fsAthDateEl) fsAthDateEl.textContent = stats.ath_date ? new Date(stats.ath_date).toLocaleDateString() : "—";
        if (fsAtlEl) fsAtlEl.textContent = stats.atl ? formatPrice(stats.atl) : "—";
        if (fsRoiEl) fsRoiEl.textContent = stats.roi1y ? `${stats.roi1y > 0 ? '+' : ''}${stats.roi1y.toFixed(1)}% ROI` : "—";
        if (fsSupplyTextEl) fsSupplyTextEl.textContent = `${pct}% Circolante`;
        if (fsSupplyFillEl) fsSupplyFillEl.style.width = `${pct}%`;
        if (fsLinksEl) fsLinksEl.innerHTML = linksHtml || `<span class="text-gray-500 text-[10px]">Nessun link</span>`;
        if (fsDescBodyEl) fsDescBodyEl.textContent = meta.description || "Descrizione in caricamento...";
        if (fsDescTitleEl) fsDescTitleEl.textContent = `Descrizione e Analisi - ${data.name} (${data.symbol})`;

        if (meta.description && meta.description.includes("[traduzione in corso...]")) {
            setTimeout(() => {
                if (STATE.selectedCoinId === coinId) updateCoinMetadata(coinId);
            }, 2000);
        }

        if (window.lucide) window.lucide.createIcons();
    } catch (err) {
        console.error("Metadata error:", err);
    }
}

function applyDynamicPrecision(series, price) {
    if (!series || !price) return;
    let prec = 2;
    let minM = 0.01;
    if (price < 0.000001) { prec = 10; minM = 0.0000000001; }
    else if (price < 0.0001) { prec = 8; minM = 0.00000001; }
    else if (price < 0.01) { prec = 6; minM = 0.000001; }
    else if (price < 1) { prec = 5; minM = 0.00001; }
    else if (price < 100) { prec = 4; minM = 0.0001; }
    
    try {
        series.applyOptions({
            priceFormat: {
                type: 'price',
                precision: prec,
                minMove: minM,
            }
        });
    } catch(e) {}
}

function setupCrosshairLegend(chart, series, legendId) {
    if (!chart || !series) return;
    const legendEl = document.getElementById(legendId);
    if (!legendEl) return;

    chart.subscribeCrosshairMove(param => {
        if (!param || !param.time || param.point.x < 0 || param.point.y < 0 || !param.seriesData) {
            const last = series.dataByIndex ? series.dataByIndex(series.data().length - 1) : null;
            if (last) updateLegendDisplay(legendEl, last.time, last);
            return;
        }
        const data = param.seriesData.get(series);
        if (data) {
            updateLegendDisplay(legendEl, param.time, data);
        }
    });
}

function updateLegendDisplay(el, timeVal, data) {
    if (!el || !data) return;
    const o = data.open;
    const h = data.high;
    const l = data.low;
    const c = data.close;
    const chg = ((c - o) / o) * 100;
    const chgCol = chg >= 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold";
    const chgSign = chg >= 0 ? "+" : "";
    
    const dateObj = new Date(timeVal * 1000);
    const dateStr = dateObj.toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: '2-digit' }) + ' ' + dateObj.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });

    let prec = 2;
    if (c < 0.000001) prec = 10;
    else if (c < 0.0001) prec = 8;
    else if (c < 0.01) prec = 6;
    else if (c < 1) prec = 5;
    else if (c < 100) prec = 4;

    const f = val => `$${val.toFixed(prec)}`;

    el.innerHTML = `
        <div class="flex items-center space-x-1.5"><span class="text-gray-500">ORA:</span><span class="text-cyan-400 font-bold">${dateStr}</span></div>
        <div class="flex items-center space-x-1.5"><span class="text-gray-500">O:</span><span class="text-gray-200 font-semibold">${f(o)}</span></div>
        <div class="flex items-center space-x-1.5"><span class="text-gray-500">H:</span><span class="text-emerald-400 font-semibold">${f(h)}</span></div>
        <div class="flex items-center space-x-1.5"><span class="text-gray-500">L:</span><span id="leg-low" class="text-rose-400 font-semibold">${f(l)}</span></div>
        <div class="flex items-center space-x-1.5"><span class="text-gray-500">C:</span><span class="text-white font-bold">${f(c)}</span></div>
        <div class="flex items-center space-x-1.5"><span class="text-gray-500">VAR:</span><span class="${chgCol}">${chgSign}${chg.toFixed(2)}%</span></div>
    `;
}

function initChart() {
    const container = document.getElementById("tradingview-chart-container");
    if (!container || !window.LightweightCharts) return;

    STATE.chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: 340,
        localization: { locale: 'it-IT' },
        layout: {
            background: { type: 'solid', color: '#0c1021' },
            textColor: '#9ca3af',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11
        },
        grid: {
            vertLines: { color: 'rgba(55, 65, 81, 0.3)' },
            horzLines: { color: 'rgba(55, 65, 81, 0.3)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: '#374151',
            scaleMargins: {
                top: 0.05,
                bottom: 0.05,
            },
        },
        timeScale: {
            borderColor: '#374151',
            timeVisible: true,
            secondsVisible: false,
        },
    });

    STATE.candleSeries = STATE.chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderDownColor: '#ef4444',
        borderUpColor: '#10b981',
        wickDownColor: '#ef4444',
        wickUpColor: '#10b981',
    });

    // Resize observer
    window.addEventListener("resize", () => {
        if (STATE.chart && container) {
            STATE.chart.resize(container.clientWidth, 340);
        }
    });
}

async function loadChartData(coinId, timeframe, isInitial = true) {
    if (!STATE.candleSeries) {
        initChart();
        if (!STATE.candleSeries) {
            setTimeout(() => loadChartData(coinId, timeframe, isInitial), 500);
            return;
        }
    }
    try {
        const res = await fetch(`/api/coins/${coinId}/candles?timeframe=${timeframe}&limit=150`);
        const json = await res.json();
        const candles = json.candles || [];

        const candleData = [];
        const tzOffsetSec = -new Date().getTimezoneOffset() * 60;

        candles.forEach(c => {
            const timeSec = Math.floor(c.t / 1000) + tzOffsetSec;
            candleData.push({
                time: timeSec,
                open: c.o,
                high: c.h,
                low: c.l,
                close: c.c
            });
        });

        candleData.sort((a, b) => a.time - b.time);

        const uniqueCandles = [];
        const seenTimes = new Set();

        for (let i = 0; i < candleData.length; i++) {
            const t = candleData[i].time;
            if (!seenTimes.has(t)) {
                seenTimes.add(t);
                uniqueCandles.push(candleData[i]);
            }
        }

        if (uniqueCandles.length === 0) {
            setTimeout(() => {
                if (STATE.selectedCoinId === coinId) loadChartData(coinId, timeframe, isInitial);
            }, 1500);
            return;
        }

        if (uniqueCandles.length > 0) {
            STATE.lastCandle = uniqueCandles[uniqueCandles.length - 1];
            applyDynamicPrecision(STATE.candleSeries, STATE.lastCandle.close);
        }

        if (isInitial) {
            if (STATE.candleSeries) STATE.candleSeries.setData([]);
            setTimeout(() => {
                if (STATE.candleSeries) STATE.candleSeries.setData(uniqueCandles);
                if (STATE.chart) STATE.chart.timeScale().fitContent();
            }, 10);
        } else {
            if (STATE.candleSeries) STATE.candleSeries.setData(uniqueCandles);
        }
    } catch (err) {
        console.error("Chart data load error:", err);
        setTimeout(() => {
            if (STATE.selectedCoinId === coinId) loadChartData(coinId, timeframe, isInitial);
        }, 2000);
    }
}

function initFullscreenChart() {
    const container = document.getElementById("fullscreen-chart-container");
    if (!container || !window.LightweightCharts || STATE.fsChart) return;

    STATE.fsChart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight,
        localization: { locale: 'it-IT' },
        layout: {
            background: { type: 'solid', color: '#060913' },
            textColor: '#d1d5db',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 13
        },
        grid: {
            vertLines: { color: 'rgba(55, 65, 81, 0.4)' },
            horzLines: { color: 'rgba(55, 65, 81, 0.4)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: '#4b5563',
            scaleMargins: { top: 0.05, bottom: 0.05 },
        },
        timeScale: {
            borderColor: '#4b5563',
            timeVisible: true,
            secondsVisible: false,
            rightOffset: 5,
            barSpacing: 8,
        },
        handleScroll: {
            mouseWheel: true,
            pressedMouseMove: true,
            horzTouchDrag: true,
            vertTouchDrag: true,
        },
        handleScale: {
            axisPressedMouseMove: { time: true, price: true },
            mouseWheel: true,
            pinch: true,
        },
    });

    STATE.fsCandleSeries = STATE.fsChart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderDownColor: '#ef4444',
        borderUpColor: '#10b981',
        wickDownColor: '#ef4444',
        wickUpColor: '#10b981',
    });

    window.addEventListener("resize", () => {
        if (STATE.fsChart && container) {
            STATE.fsChart.resize(container.clientWidth, container.clientHeight);
        }
    });
}

async function openFullscreenChart(coinId, timeframe) {
    const modal = document.getElementById("fullscreen-chart-modal");
    if (!modal) return;
    
    modal.classList.remove("hidden");
    
    const coin = STATE.coins.find(c => c.id === coinId) || {};
    document.getElementById("fs-symbol").textContent = coin.symbol || "ASSET";
    document.getElementById("fs-name").textContent = coin.name || "";
    document.getElementById("fs-rank").textContent = `#${coin.rank || "—"}`;
    document.getElementById("fs-price").textContent = formatPrice(coin.price || STATE.lastPrices[coinId]);
    document.getElementById("fs-change").innerHTML = formatChangeBadge(coin.change_24h);

    setFullscreenTimeframe(timeframe || STATE.timeframe);
    initFullscreenChart();
    await loadFullscreenChartData(coinId, timeframe || STATE.timeframe);
}

function closeFullscreenChart() {
    const modal = document.getElementById("fullscreen-chart-modal");
    if (modal) modal.classList.add("hidden");
}

function toggleFsDescModal() {
    const modal = document.getElementById("fs-desc-modal");
    if (modal) modal.classList.toggle("hidden");
}

function resetFullscreenZoom() {
    if (STATE.fsChart) {
        STATE.fsChart.timeScale().fitContent();
        showToast("Zoom reimpostato per mostrare tutte le candele.", "info");
    }
}

function setFullscreenTimeframe(tf) {
    STATE.timeframe = tf;
    document.querySelectorAll(".fs-tf-btn").forEach(btn => {
        btn.classList.remove("bg-purple-600", "text-white");
        btn.classList.add("bg-gray-800", "text-gray-400");
        if (btn.dataset.tf === tf) {
            btn.classList.remove("bg-gray-800", "text-gray-400");
            btn.classList.add("bg-purple-600", "text-white");
        }
    });
    document.querySelectorAll(".tf-btn").forEach(btn => {
        btn.classList.remove("bg-purple-600", "text-white");
        btn.classList.add("bg-gray-800", "text-gray-400");
        if (btn.dataset.tf === tf) {
            btn.classList.remove("bg-gray-800", "text-gray-400");
            btn.classList.add("bg-purple-600", "text-white");
        }
    });
    loadFullscreenChartData(STATE.selectedCoinId, tf);
}

async function loadFullscreenChartData(coinId, timeframe, isInitial = true) {
    const spinner = document.getElementById("fs-loading-spinner");
    if (spinner && isInitial) spinner.classList.remove("hidden");
    
    if (!STATE.fsCandleSeries) {
        initFullscreenChart();
        if (!STATE.fsCandleSeries) {
            setTimeout(() => loadFullscreenChartData(coinId, timeframe, isInitial), 500);
            return;
        }
    }

    try {
        const res = await fetch(`/api/coins/${coinId}/candles?timeframe=${timeframe}&limit=300`);
        const json = await res.json();
        const candles = json.candles || [];

        const candleData = [];
        const tzOffsetSec = -new Date().getTimezoneOffset() * 60;

        candles.forEach(c => {
            const timeSec = Math.floor(c.t / 1000) + tzOffsetSec;
            candleData.push({
                time: timeSec,
                open: c.o,
                high: c.h,
                low: c.l,
                close: c.c
            });
        });

        candleData.sort((a, b) => a.time - b.time);

        const uniqueCandles = [];
        const seenTimes = new Set();

        for (let i = 0; i < candleData.length; i++) {
            const t = candleData[i].time;
            if (!seenTimes.has(t)) {
                seenTimes.add(t);
                uniqueCandles.push(candleData[i]);
            }
        }

        if (uniqueCandles.length === 0) {
            setTimeout(() => {
                if (document.getElementById("fullscreen-chart-modal") && !document.getElementById("fullscreen-chart-modal").classList.contains("hidden")) {
                    loadFullscreenChartData(coinId, timeframe, isInitial);
                }
            }, 1500);
            return;
        }

        if (uniqueCandles.length > 0) {
            STATE.lastFsCandle = uniqueCandles[uniqueCandles.length - 1];
            applyDynamicPrecision(STATE.fsCandleSeries, STATE.lastFsCandle.close);
        }

        if (isInitial) {
            if (STATE.fsCandleSeries) STATE.fsCandleSeries.setData([]);
            setTimeout(() => {
                if (STATE.fsCandleSeries) STATE.fsCandleSeries.setData(uniqueCandles);
                if (STATE.fsChart) STATE.fsChart.timeScale().fitContent();
            }, 10);
        } else {
            if (STATE.fsCandleSeries) STATE.fsCandleSeries.setData(uniqueCandles);
        }
    } catch (err) {
        console.error("Fullscreen chart error:", err);
        setTimeout(() => {
            if (document.getElementById("fullscreen-chart-modal") && !document.getElementById("fullscreen-chart-modal").classList.contains("hidden")) {
                loadFullscreenChartData(coinId, timeframe, isInitial);
            }
        }, 2000);
    } finally {
        if (spinner) spinner.classList.add("hidden");
    }
}

function setTimeframe(tf) {
    STATE.timeframe = tf;
    document.querySelectorAll(".tf-btn").forEach(btn => {
        btn.classList.remove("bg-purple-600", "text-white");
        btn.classList.add("bg-gray-800", "text-gray-400");
        if (btn.dataset.tf === tf) {
            btn.classList.remove("bg-gray-800", "text-gray-400");
            btn.classList.add("bg-purple-600", "text-white");
        }
    });
    document.querySelectorAll(".fs-tf-btn").forEach(btn => {
        btn.classList.remove("bg-purple-600", "text-white");
        btn.classList.add("bg-gray-800", "text-gray-400");
        if (btn.dataset.tf === tf) {
            btn.classList.remove("bg-gray-800", "text-gray-400");
            btn.classList.add("bg-purple-600", "text-white");
        }
    });
    loadChartData(STATE.selectedCoinId, tf);
}

// ══════════════════════════════════════════════════════════════════════════════
// ALERT ENGINE & SOUND NOTIFICATIONS
// ══════════════════════════════════════════════════════════════════════════════

async function fetchAlerts() {
    try {
        const res = await fetch("/api/alerts");
        const json = await res.json();

        // Update Navbar Badge
        const badge = document.getElementById("alert-badge-count");
        if (badge) badge.textContent = json.active_rules || 0;

        renderAlertsList(json.rules || []);
    } catch (err) {
        console.error("Fetch alerts error:", err);
    }
}

function renderAlertsList(rules) {
    const activeContainer = document.getElementById("active-alerts-list");
    const firedContainer = document.getElementById("triggered-alerts-list");
    if (!activeContainer || !firedContainer) return;

    const activeRules = rules.filter(r => !r.fired);
    const firedRules = rules.filter(r => r.fired);

    // Active Rules
    if (activeRules.length === 0) {
        activeContainer.innerHTML = `<div class="p-8 text-center text-gray-500 font-mono bg-gray-900/40 rounded-lg border border-gray-800">Nessuna allerta di prezzo attiva. Clicca sull'icona campanella di qualsiasi criptovaluta per crearne una!</div>`;
    } else {
        let html = "";
        activeRules.forEach(r => {
            const opLabel = { ">": "ABOVE", "<": "BELOW", ">=": "ABOVE OR EQUAL", "<=": "BELOW OR EQUAL", "cross_up": "CROSS UP", "cross_down": "CROSS DOWN" }[r.op] || r.op;
            html += `
                <div class="p-4 bg-gray-900/80 border border-purple-500/30 rounded-lg flex items-center justify-between shadow-lg">
                    <div class="flex items-center space-x-4">
                        <div class="p-2.5 bg-purple-900/30 rounded-lg text-purple-400">
                            <i data-lucide="bell" class="w-5 h-5"></i>
                        </div>
                        <div>
                            <div class="font-bold text-white text-base">${r.symbol} <span class="text-xs text-purple-400 font-mono ml-2">TARGET: ${opLabel} $${r.value.toLocaleString()}</span></div>
                            <div class="text-xs text-gray-400 font-mono mt-0.5">${r.note || "No note attached"} · Created: ${new Date(r.created_at * 1000).toLocaleTimeString()}</div>
                        </div>
                    </div>
                    <button onclick="deleteAlert(${r.id})" class="p-2 bg-gray-800 hover:bg-rose-600 text-gray-400 hover:text-white rounded transition-colors" title="Remove Rule">
                        <i data-lucide="trash-2" class="w-4 h-4"></i>
                    </button>
                </div>
            `;
        });
        activeContainer.innerHTML = html;
    }

    // Fired Rules
    if (firedRules.length === 0) {
        firedContainer.innerHTML = `<div class="p-6 text-center text-gray-500 font-mono bg-gray-900/40 rounded-lg border border-gray-800">Nessuna notifica scattata finora.</div>`;
    } else {
        let html = "";
        firedRules.slice(0, 10).forEach(r => {
            html += `
                <div class="p-3 bg-emerald-950/20 border border-emerald-500/40 rounded-lg flex items-center justify-between">
                    <div class="flex items-center space-x-3">
                        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        <div>
                            <span class="font-bold text-emerald-300 font-mono text-sm">${r.symbol} SCATTATO</span>
                            <span class="text-xs text-gray-300 ml-2">Scattato a $${r.fire_value ? r.fire_value.toLocaleString() : r.value} (${r.op} $${r.value})</span>
                        </div>
                    </div>
                    <span class="text-xs font-mono text-gray-500">${new Date(r.fire_time * 1000).toLocaleTimeString()}</span>
                </div>
            `;
        });
        firedContainer.innerHTML = html;
    }

    if (window.lucide) window.lucide.createIcons();
}

function openAlertModal(coinId, symbol, price) {
    document.getElementById("modal-coin-id").value = coinId;
    document.getElementById("modal-symbol").textContent = symbol;
    document.getElementById("modal-price-hint").textContent = `Prezzo Live Attuale: ${formatPrice(price)}`;
    document.getElementById("modal-value").value = price * 1.05; // Default 5% above
    document.getElementById("alert-modal").classList.remove("hidden");
}

function closeAlertModal() {
    document.getElementById("alert-modal").classList.add("hidden");
}

async function submitAlertForm(e) {
    e.preventDefault();
    const coinId = parseInt(document.getElementById("modal-coin-id").value);
    const op = document.getElementById("modal-operator").value;
    const val = parseFloat(document.getElementById("modal-value").value);
    const note = document.getElementById("modal-note").value;

    try {
        const res = await fetch("/api/alerts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ coin_id: coinId, field: "p", operator: op, value: val, note: note })
        });
        if (res.ok) {
            closeAlertModal();
            fetchAlerts();
            showToast(`Regola di allerta attivata con successo per l'asset ID #${coinId}!`, "success");
        }
    } catch (err) {
        console.error("Create alert error:", err);
    }
}

async function deleteAlert(id) {
    try {
        await fetch(`/api/alerts/${id}`, { method: "DELETE" });
        fetchAlerts();
        showToast("Regola di allerta rimossa.", "info");
    } catch (err) {
        console.error("Delete alert error:", err);
    }
}

async function clearTriggeredAlerts() {
    try {
        await fetch("/api/alerts/clear-triggered", { method: "POST" });
        fetchAlerts();
        showToast("Storico notifiche scattate svuotato.", "info");
    } catch (err) {
        console.error("Clear triggered error:", err);
    }
}

async function triggerTestAlert() {
    try {
        const res = await fetch("/api/alerts/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol: "BTC", value: 100000, note: "Cyberpunk Synth Sound & Toast Test!" })
        });
        const json = await res.json();
        triggerAlertNotification(json.alert);
        fetchAlerts();
    } catch (err) {
        console.error("Test alert error:", err);
    }
}

function triggerAlertNotification(alert) {
    playCyberpunkBeep();
    showToast(`🔔 ALERT FIRED: ${alert.symbol} ${alert.op} $${alert.value.toLocaleString()}! ${alert.note || ''}`, "alert");
}

function toggleSound() {
    STATE.soundEnabled = !STATE.soundEnabled;
    const btn = document.getElementById("sound-toggle-btn");
    if (btn) {
        btn.innerHTML = STATE.soundEnabled ? 
            '<i data-lucide="volume-2" class="w-4 h-4 text-emerald-400"></i>' : 
            '<i data-lucide="volume-x" class="w-4 h-4 text-gray-500"></i>';
        if (window.lucide) window.lucide.createIcons();
    }
    showToast(`Notifiche sonore ${STATE.soundEnabled ? 'attivate' : 'disattivate'}.`, "info");
}

function playCyberpunkBeep() {
    if (!STATE.soundEnabled || !window.AudioContext) return;
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc1 = ctx.createOscillator();
        const osc2 = ctx.createOscillator();
        const gain = ctx.createGain();

        osc1.type = "sawtooth";
        osc2.type = "sine";
        osc1.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
        osc1.frequency.exponentialRampToValueAtTime(880.0, ctx.currentTime + 0.15); // A5
        osc2.frequency.setValueAtTime(293.66, ctx.currentTime); // D4

        gain.gain.setValueAtTime(0.2, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);

        osc1.connect(gain);
        osc2.connect(gain);
        gain.connect(ctx.destination);

        osc1.start();
        osc2.start();
        osc1.stop(ctx.currentTime + 0.4);
        osc2.stop(ctx.currentTime + 0.4);
    } catch (e) {
        console.log("Audio synth error:", e);
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// CLOUD HISTORICAL DB (808FILES UNLIMITED STORAGE)
// ══════════════════════════════════════════════════════════════════════════════

async function fetchCloudDatasets() {
    try {
        const res = await fetch("/api/cloud-db");
        const json = await res.json();
        const container = document.getElementById("clouddb-list-container");
        const badge = document.getElementById("clouddb-badge-count");
        if (badge) badge.textContent = json.total_archives || 0;
        if (!container) return;

        const list = json.data || [];
        if (list.length === 0) {
            container.innerHTML = `<div class="p-8 text-center text-gray-500 font-mono bg-gray-900/40 rounded-lg border border-gray-800 md:col-span-2">Nessuno storico multi-anno archiviato. Seleziona una criptovaluta sopra e clicca 'Archivia DB' per caricare il database offuscato su 808files!</div>`;
            return;
        }

        let html = "";
        list.forEach(item => {
            const sizeKb = Math.round(item.size_obfuscated / 1024);
            const dateStr = new Date(item.created_at * 1000).toLocaleDateString();
            html += `
                <div class="p-4 bg-gray-900/80 border border-cyan-500/30 rounded-xl flex flex-col justify-between space-y-3 shadow-lg hover:border-cyan-400 transition-all">
                    <div class="flex items-start justify-between">
                        <div class="flex items-center space-x-3">
                            <div class="p-2.5 bg-cyan-950 border border-cyan-800 rounded-lg text-cyan-400">
                                <i data-lucide="database" class="w-5 h-5"></i>
                            </div>
                            <div>
                                <div class="font-bold text-white text-sm font-mono">${item.key}</div>
                                <div class="text-xs text-cyan-300 font-sans mt-0.5">${item.description || "Archivio Storico"}</div>
                            </div>
                        </div>
                        <span class="px-2 py-0.5 bg-gray-800 text-gray-300 rounded font-mono text-[10px]">${sizeKb} KB</span>
                    </div>
                    <div class="flex items-center justify-between pt-2 border-t border-gray-800/80 text-xs font-mono">
                        <span class="text-gray-500 text-[10px]">${dateStr} · 808files</span>
                        <div class="flex items-center space-x-2">
                            <button onclick="copyToClipboardText('${item.stream}')" class="px-2.5 py-1 bg-gray-800 hover:bg-cyan-600 text-gray-300 hover:text-white rounded transition-colors text-[11px]" title="Copia Stream URL">📋 Copia Stream</button>
                            <a href="${item.link}" target="_blank" class="px-2.5 py-1 bg-cyan-950 border border-cyan-800 hover:bg-cyan-900 text-cyan-300 rounded transition-colors text-[11px]">🔗 Apri Link</a>
                            <button onclick="deleteCloudDataset('${item.key}')" class="p-1 bg-gray-800 hover:bg-rose-600 text-gray-400 hover:text-white rounded transition-colors" title="Rimuovi dall'indice"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button>
                        </div>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
        if (window.lucide) window.lucide.createIcons();
    } catch (err) {
        console.error("Fetch cloud db error:", err);
    }
}

async function uploadToCloudDB(e) {
    e.preventDefault();
    const btn = document.getElementById("clouddb-upload-btn");
    const coinId = parseInt(document.getElementById("clouddb-coin-id").value);
    const tfVal = document.getElementById("clouddb-timeframe").value.split("|");
    const timeframe = tfVal[0];
    const limit = parseInt(tfVal[1]);
    const desc = document.getElementById("clouddb-desc").value || `Multi-year archive (${limit} candles)`;

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin inline"></i> <span>Archiviazione...</span>`;
    }

    try {
        const res = await fetch("/api/cloud-db/upload", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ coin_id: coinId, timeframe: timeframe, limit: limit, description: desc })
        });
        const json = await res.json();
        if (res.ok) {
            showToast(`🚀 DB Multi-Anno archiviato con successo su 808files! Chiave: ${json.archive.key}`, "success");
            document.getElementById("clouddb-desc").value = "";
            fetchCloudDatasets();
        } else {
            showToast(`Errore archiviazione: ${json.detail || 'Failed'}`, "alert");
        }
    } catch (err) {
        showToast(`Errore di rete nell'archiviazione DB: ${err.message}`, "alert");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="cloud-upload" class="w-4 h-4"></i> <span>Archivia DB</span>`;
            if (window.lucide) window.lucide.createIcons();
        }
    }
}

async function deleteCloudDataset(key) {
    try {
        await fetch(`/api/cloud-db/${key}`, { method: "DELETE" });
        fetchCloudDatasets();
        showToast(`Archivio '${key}' rimosso dall'indice.`, "info");
    } catch (err) {
        console.error("Delete cloud db error:", err);
    }
}

function copyToClipboardText(text) {
    navigator.clipboard.writeText(text);
    showToast("URL di streaming copiato negli appunti!", "success");
}

async function forceUniverseBackup() {
    const btn = document.getElementById("force-backup-btn");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin inline"></i> <span>Backup in corso...</span>`;
    }
    try {
        const res = await fetch("/api/cloud-db/upload", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ coin_id: 1, timeframe: "1d", limit: 3650, description: "Universo Backup Master 10-Anni" })
        });
        const json = await res.json();
        if (res.ok) {
            showToast(`⚡ Backup Istantaneo 10 Anni archiviato con successo su 808files! Chiave: ${json.archive.key}`, "success");
            fetchCloudDatasets();
        } else {
            showToast(`Errore backup: ${json.detail || 'Fallito'}`, "alert");
        }
    } catch (err) {
        showToast(`Errore di rete durante il backup: ${err.message}`, "alert");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="zap" class="w-4 h-4"></i> <span>Forza Backup Universo su Cloud DB</span>`;
            if (window.lucide) window.lucide.createIcons();
        }
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// REST API CONSOLE (REPLACES CLI COMMANDS)
// ══════════════════════════════════════════════════════════════════════════════

async function executeApiRequest(method, endpoint, bodyObj = null) {
    const statusBadge = document.getElementById("api-res-status");
    const timeBadge = document.getElementById("api-res-time");
    const codeBlock = document.getElementById("api-res-code");
    const curlBlock = document.getElementById("api-curl-cmd");

    statusBadge.textContent = "ESECUZIONE...";
    statusBadge.className = "px-2 py-0.5 rounded text-xs font-mono bg-amber-500/20 text-amber-300";
    codeBlock.textContent = "In attesa di risposta dal server...";

    const start = performance.now();
    try {
        const options = { method };
        if (bodyObj && (method === "POST" || method === "PUT")) {
            options.headers = { "Content-Type": "application/json" };
            options.body = JSON.stringify(bodyObj);
        }

        const res = await fetch(endpoint, options);
        const elapsed = Math.round(performance.now() - start);
        const json = await res.json();

        // Update UI
        statusBadge.textContent = `${res.status} ${res.statusText}`;
        statusBadge.className = res.ok ? 
            "px-2 py-0.5 rounded text-xs font-mono bg-emerald-500/20 text-emerald-300 font-bold" : 
            "px-2 py-0.5 rounded text-xs font-mono bg-rose-500/20 text-rose-300 font-bold";
        
        timeBadge.textContent = `${elapsed} ms`;
        codeBlock.textContent = JSON.stringify(json, null, 2);

        // Generate copyable cURL command
        let curl = `curl -X ${method} "http://localhost:7860${endpoint}"`;
        if (options.body) {
            curl += ` \\\n  -H "Content-Type: application/json" \\\n  -d '${options.body}'`;
        }
        curlBlock.textContent = curl;

    } catch (err) {
        statusBadge.textContent = "ERRORE DI RETE";
        statusBadge.className = "px-2 py-0.5 rounded text-xs font-mono bg-rose-500/20 text-rose-300";
        codeBlock.textContent = `Errore durante l'esecuzione della richiesta:\n${err.message}`;
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// UI HELPERS & FORMATTERS
// ══════════════════════════════════════════════════════════════════════════════

function initEventListeners() {
    // Search input
    const searchInput = document.getElementById("table-search-input");
    if (searchInput) {
        searchInput.addEventListener("input", (e) => {
            STATE.searchQuery = e.target.value;
            STATE.offset = 0;
            fetchCoins();
        });
    }

    // Keyboard shortcuts
    document.addEventListener("keydown", (e) => {
        if (e.key === "/" && document.activeElement !== searchInput && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
            e.preventDefault();
            if (searchInput) searchInput.focus();
        }
        if (e.key === "Escape") {
            closeAlertModal();
            if (searchInput) searchInput.blur();
        }
    });

    // Alert modal form
    const alertForm = document.getElementById("alert-modal-form");
    if (alertForm) alertForm.addEventListener("submit", submitAlertForm);
}

function switchTab(tabId) {
    STATE.activeTab = tabId;
    
    // Hide all view contents
    document.querySelectorAll(".tab-content").forEach(el => el.classList.add("hidden"));
    document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active", "bg-purple-600/30", "border-purple-500", "text-white"));

    // Show active tab
    const activeView = document.getElementById(`view-${tabId}`);
    const activeBtn = document.getElementById(`tab-btn-${tabId}`);
    if (activeView) activeView.classList.remove("hidden");
    if (activeBtn) activeBtn.classList.add("active");

    if (tabId === "market" && STATE.chart) {
        STATE.chart.timeScale().fitContent();
    } else if (tabId === "api") {
        // Run initial API test on console open
        executeApiRequest("GET", "/api/status");
    } else if (tabId === "clouddb") {
        fetchCloudDatasets();
    }
}

function sortTable(field) {
    if (STATE.sortBy === field) {
        STATE.sortOrder = STATE.sortOrder === "desc" ? "asc" : "desc";
    } else {
        STATE.sortBy = field;
        STATE.sortOrder = "desc";
    }
    fetchCoins();
}

function formatPrice(val) {
    if (val === null || val === undefined) return "—";
    if (val >= 100) return `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (val >= 1) return `$${val.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
    if (val >= 0.0001) return `$${val.toFixed(6)}`;
    return `$${val.toFixed(8)}`;
}

function formatNumber(val) {
    if (!val) return "0";
    if (val >= 1e12) return `${(val / 1e12).toFixed(2)}T`;
    if (val >= 1e9) return `${(val / 1e9).toFixed(2)}B`;
    if (val >= 1e6) return `${(val / 1e6).toFixed(2)}M`;
    if (val >= 1e3) return `${(val / 1e3).toFixed(1)}K`;
    return val.toLocaleString();
}

function formatChangeBadge(val) {
    if (val === null || val === undefined) return `<span class="text-gray-500 font-mono">—</span>`;
    const col = val >= 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold";
    const arr = val >= 0 ? "▲" : "▼";
    return `<span class="${col} font-mono">${arr} ${Math.abs(val).toFixed(2)}%</span>`;
}

function formatUptime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return `${h > 0 ? h + 'h ' : ''}${m}m ${s}s`;
}

function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    const borderCol = type === "alert" ? "border-purple-500 bg-purple-950/90 text-purple-200" :
                      type === "success" ? "border-emerald-500 bg-emerald-950/90 text-emerald-200" :
                      "border-blue-500 bg-gray-900/90 text-gray-200";

    toast.className = `p-4 rounded-lg border ${borderCol} shadow-2xl backdrop-blur-md flex items-center space-x-3 toast-animate font-mono text-sm max-w-md`;
    toast.innerHTML = `
        <span>${message}</span>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transition = "opacity 0.5s ease";
        setTimeout(() => toast.remove(), 500);
    }, 6000);
}

function copyToClipboard(textElId) {
    const el = document.getElementById(textElId);
    if (!el) return;
    navigator.clipboard.writeText(el.textContent);
    showToast("Copiato negli appunti!", "success");
}
