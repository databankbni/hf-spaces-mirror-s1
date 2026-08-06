// Global state
let currentAnalysis = null;
let hypeChartInstance = null;

document.addEventListener("DOMContentLoaded", () => {
    initEventListeners();
    loadGallery();
});

function initEventListeners() {
    const form = document.getElementById("analyze-form");
    const demoBtn = document.getElementById("demo-btn");
    const refreshBtn = document.getElementById("refresh-clips-btn");
    const clipAllBtn = document.getElementById("clip-all-btn");

    form.addEventListener("submit", handleAnalyzeSubmit);
    
    demoBtn.addEventListener("click", () => {
        document.getElementById("vod-url").value = "demo";
        handleAnalyzeSubmit(new Event("submit"));
    });

    refreshBtn.addEventListener("click", () => {
        loadGallery();
        showToast("Gallery refreshed!");
    });

    clipAllBtn.addEventListener("click", handleClipAll);
}

async function handleAnalyzeSubmit(e) {
    e.preventDefault();
    const url = document.getElementById("vod-url").value.trim() || "demo";
    const interval = parseInt(document.getElementById("interval-sec").value);
    const topN = parseInt(document.getElementById("top-n").value);
    const beforeSec = parseInt(document.getElementById("before-sec").value);
    const afterSec = parseInt(document.getElementById("after-sec").value);
    const durationMode = document.getElementById("duration-mode") ? document.getElementById("duration-mode").value : "short";
    const enableAiSpeech = document.getElementById("enable-ai-speech") ? (document.getElementById("enable-ai-speech").value === "true") : true;

    // Show loading
    setLoading(true, "Scraping Chat & Analyzing Hype...", "Downloading timestamps and computing message frequency...");
    document.getElementById("results-section").classList.add("hidden");

    try {
        const resp = await fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                url: url,
                interval: interval,
                top_n: topN,
                before_sec: beforeSec,
                after_sec: afterSec,
                duration_mode: durationMode,
                enable_ai_speech: enableAiSpeech
            })
        });

        const resData = await resp.json();
        if (!resp.ok || resData.status !== "success") {
            throw new Error(resData.detail || "Analysis failed");
        }

        currentAnalysis = resData.data;
        currentAnalysis.url = url; // save url for clipping
        renderResults(currentAnalysis);
        showToast("⚡ Stream analyzed successfully!");
    } catch (err) {
        console.error(err);
        showToast(`❌ Error: ${err.message}`);
    } finally {
        setLoading(false);
    }
}

function setLoading(isLoading, title = "", subtitle = "") {
    const loader = document.getElementById("loading-state");
    if (isLoading) {
        document.getElementById("loading-title").textContent = title;
        document.getElementById("loading-subtitle").textContent = subtitle;
        loader.classList.remove("hidden");
    } else {
        loader.classList.add("hidden");
    }
}

function renderResults(data) {
    // Update KPIs
    document.getElementById("stat-messages").textContent = data.total_messages.toLocaleString();
    document.getElementById("stat-duration").textContent = data.duration_formatted;
    document.getElementById("stat-highlights").textContent = data.highlights.length;

    // Render Chart
    renderChart(data.timeline, data.highlights);

    // Render Highlights Cards
    renderHighlightsList(data.highlights);

    // Show section
    document.getElementById("results-section").classList.remove("hidden");
    // Scroll to results
    document.getElementById("results-section").scrollIntoView({ behavior: "smooth" });
}

function renderChart(timeline, highlights) {
    const ctx = document.getElementById("hypeChart").getContext("2d");
    
    if (hypeChartInstance) {
        hypeChartInstance.destroy();
    }

    const labels = timeline.map(t => t.time_formatted);
    const scores = timeline.map(t => t.score);
    const counts = timeline.map(t => t.count);

    // Create gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, 380);
    gradient.addColorStop(0, "rgba(145, 70, 255, 0.6)");
    gradient.addColorStop(1, "rgba(145, 70, 255, 0.0)");

    hypeChartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Hype Score",
                    data: scores,
                    borderColor: "#b886ff",
                    backgroundColor: gradient,
                    borderWidth: 3,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 2,
                    pointHoverRadius: 6,
                    yAxisID: "y"
                },
                {
                    label: "Message Count",
                    data: counts,
                    borderColor: "#00f0ff",
                    borderWidth: 1.5,
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.3,
                    pointRadius: 0,
                    yAxisID: "y1"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: "index",
                intersect: false
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "rgba(10, 6, 18, 0.9)",
                    titleFont: { family: "Outfit", size: 14, weight: "bold" },
                    bodyFont: { family: "Inter", size: 13 },
                    borderColor: "rgba(145, 70, 255, 0.5)",
                    borderWidth: 1,
                    padding: 12,
                    callbacks: {
                        afterBody: function(context) {
                            const idx = context[0].dataIndex;
                            const samples = timeline[idx].samples || [];
                            if (samples.length > 0) {
                                return "\n💬 Top Chat:\n• " + samples.slice(0, 3).join("\n• ");
                            }
                            return "";
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: "rgba(255, 255, 255, 0.05)" },
                    ticks: { color: "#a89cbd", font: { family: "Inter", size: 11 }, maxTicksLimit: 12 }
                },
                y: {
                    type: "linear",
                    display: true,
                    position: "left",
                    grid: { color: "rgba(255, 255, 255, 0.08)" },
                    ticks: { color: "#b886ff", font: { family: "Inter", size: 11 } },
                    title: { display: true, text: "Hype Score", color: "#b886ff" }
                },
                y1: {
                    type: "linear",
                    display: true,
                    position: "right",
                    grid: { drawOnChartArea: false },
                    ticks: { color: "#00f0ff", font: { family: "Inter", size: 11 } },
                    title: { display: true, text: "Msg / Window", color: "#00f0ff" }
                }
            }
        }
    });
}

function renderHighlightsList(highlights) {
    const container = document.getElementById("highlights-list");
    container.innerHTML = "";

    if (!highlights || highlights.length === 0) {
        container.innerHTML = `<p class="empty-state">No major hype peaks detected with current settings. Try lowering the threshold or bucket interval!</p>`;
        return;
    }

    const durationMode = document.getElementById("duration-mode").value;
    if (durationMode === "viral_bunch") {
        const banner = document.createElement("div");
        banner.className = "viral-bunch-banner";
        banner.style.gridColumn = "1 / -1";
        banner.innerHTML = `
            <div style="display: flex; align-items: center; gap: 12px; background: linear-gradient(135deg, rgba(145, 70, 255, 0.25), rgba(0, 240, 255, 0.25)); border: 1px solid var(--accent-cyan); padding: 16px; border-radius: 12px; box-shadow: 0 0 20px rgba(0, 240, 255, 0.2); margin-bottom: 8px;">
                <div style="font-size: 28px;">📱</div>
                <div>
                    <div style="font-size: 16px; font-weight: 700; color: #fff;">VIRAL SHORTS BUNCH MODE ACTIVE</div>
                    <div style="font-size: 13px; color: var(--text-secondary);">AI has scanned the stream for chat spikes & speech to generate a massive batch of viral vertical shorts (${highlights.length} clips ready)!</div>
                </div>
            </div>
        `;
        container.appendChild(banner);
    }

    highlights.forEach(h => {
        const card = document.createElement("div");
        card.className = "highlight-card";
        card.id = `highlight-card-${h.id}`;
        
        let chatHtml = "";
        if (h.top_messages && h.top_messages.length > 0) {
            chatHtml = h.top_messages.map(m => {
                const parts = m.split(":");
                const author = parts[0];
                const msg = parts.slice(1).join(":");
                return `<div class="chat-msg"><span class="chat-author">${author}:</span> ${msg}</div>`;
            }).join("");
        } else {
            chatHtml = `<div class="chat-msg">No sample chat available</div>`;
        }

        const aiBadgeHtml = h.ai_badge ? `<span class="ai-badge">${h.ai_badge}</span>` : "";
        const viralHookHtml = h.viral_hook ? `
            <div class="viral-hook-box">
                <div class="viral-hook-header">
                    <span>🎣 VIRAL HOOK / TITLE:</span>
                    <button class="btn-copy-hook" onclick="copyHookToClipboard('${h.viral_hook.replace(/'/g, "\\'")}', this)">
                        📋 Copy Hook
                    </button>
                </div>
                <div class="viral-hook-text">${h.viral_hook}</div>
            </div>
        ` : "";
        const aiTranscriptHtml = h.ai_transcript ? `
            <div class="ai-transcript-box">
                <div class="ai-transcript-title">🎙️ Streamer Speech Transcript:</div>
                <div class="ai-transcript-text">"${h.ai_transcript}"</div>
            </div>
        ` : "";

        card.innerHTML = `
            <div>
                <div class="highlight-top">
                    <div>
                        <div class="highlight-title">${h.title}</div>
                        <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">
                            Range: ${h.start_time_formatted} - ${h.end_time_formatted} (${h.duration}s)
                        </div>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                        ${aiBadgeHtml}
                        <span class="score-badge">⚡ ${h.score} Pts</span>
                    </div>
                </div>
                ${viralHookHtml}
                ${aiTranscriptHtml}
                <div style="margin-top: 12px;">
                    <div style="font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; text-transform: uppercase;">💬 Chat Reactions:</div>
                    <div class="chat-samples">
                        ${chatHtml}
                    </div>
                </div>
            </div>
            <div id="clip-container-${h.id}" class="clip-btn-group" style="margin-top: 16px;">
                <button class="btn btn-primary btn-sm glow-button" onclick="triggerClip(${h.id}, ${h.start_time}, ${h.end_time}, '${h.title.replace(/'/g, "")}')">
                    <i data-lucide="scissors"></i> Clip This Moment
                </button>
            </div>
        `;
        container.appendChild(card);
    });

    lucide.createIcons();
}

window.copyHookToClipboard = function(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
        const originalText = btn.innerHTML;
        btn.innerHTML = "✅ Copied!";
        btn.style.background = "rgba(83, 252, 24, 0.3)";
        btn.style.color = "#fff";
        showToast("Viral Hook copied to clipboard!");
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.style.background = "";
            btn.style.color = "";
        }, 2000);
    }).catch(err => {
        showToast("Failed to copy hook!");
    });
};

async function triggerClip(id, startTime, endTime, title) {
    if (!currentAnalysis) {
        showToast("❌ Please analyze a stream first!");
        return;
    }

    const jobId = "clip_" + Date.now() + "_" + Math.random().toString(36).substr(2, 5);
    const container = document.getElementById(`clip-container-${id}`);
    
    if (container) {
        container.innerHTML = `
            <div class="clip-progress-box">
                <div class="clip-progress-header">
                    <span id="prog-status-${jobId}" style="color: var(--accent-cyan); font-weight: 600;">⏳ Starting clip slice...</span>
                    <span id="prog-pct-${jobId}" style="font-weight: 700; color: #fff;">0%</span>
                </div>
                <div class="clip-progress-bg">
                    <div id="prog-bar-${jobId}" class="clip-progress-fill" style="width: 5%;"></div>
                </div>
            </div>
        `;
    }

    showToast(`⏳ Slicing clip: "${title}"... Watch progress bar!`);

    // Start polling status
    const pollInterval = setInterval(async () => {
        try {
            const res = await fetch(`/api/clip/status/${jobId}`);
            const stat = await res.json();
            if (stat && stat.progress !== undefined) {
                const bar = document.getElementById(`prog-bar-${jobId}`);
                const pct = document.getElementById(`prog-pct-${jobId}`);
                const st = document.getElementById(`prog-status-${jobId}`);
                if (bar && pct && st) {
                    bar.style.width = stat.progress + "%";
                    pct.textContent = stat.progress + "%";
                    st.textContent = stat.message || "Slicing...";
                }
                if (stat.status === "completed" || stat.status === "error") {
                    clearInterval(pollInterval);
                }
            }
        } catch (e) {}
    }, 500);

    try {
        const resp = await fetch("/api/clip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                url: currentAnalysis.url,
                start_time: startTime,
                end_time: endTime,
                title: title,
                aspect_ratio: "16:9",
                job_id: jobId
            })
        });

        const resData = await resp.json();
        clearInterval(pollInterval);

        if (!resp.ok || resData.status !== "success") {
            if (container) {
                container.innerHTML = `
                    <button class="btn btn-primary btn-sm glow-button" style="background: #ff4757;" onclick="triggerClip(${id}, ${startTime}, ${endTime}, '${title.replace(/'/g, "")}')">
                        ❌ Failed - Click to Retry
                    </button>
                `;
            }
            throw new Error(resData.detail || "Clipping failed");
        }

        if (container) {
            container.innerHTML = `
                <div class="clip-progress-box" style="border-color: var(--kick-green);">
                    <div class="clip-progress-header">
                        <span style="color: var(--kick-green); font-weight: 700;">✅ Clip Created!</span>
                        <span style="color: var(--kick-green); font-weight: 700;">100%</span>
                    </div>
                    <div class="clip-progress-bg">
                        <div class="clip-progress-fill" style="width: 100%; background: var(--kick-green);"></div>
                    </div>
                </div>
            `;
        }

        showToast(`✅ Successfully created clip: ${resData.clip.filename}`);
        loadGallery();
    } catch (err) {
        clearInterval(pollInterval);
        console.error(err);
        showToast(`❌ Clip error: ${err.message}`);
    }
}

async function handleClipAll() {
    if (!currentAnalysis || !currentAnalysis.highlights || currentAnalysis.highlights.length === 0) {
        showToast("❌ No highlights available to clip!");
        return;
    }

    showToast(`⏳ Starting batch clipping for ${currentAnalysis.highlights.length} highlights...`);
    
    for (const h of currentAnalysis.highlights) {
        await triggerClip(h.id, h.start_time, h.end_time, h.title);
    }
    
    showToast("🎉 All top highlights clipped and added to gallery!");
}

async function loadGallery() {
    const container = document.getElementById("clips-gallery");
    
    try {
        const resp = await fetch("/api/clips");
        const resData = await resp.json();
        
        if (!resp.ok || resData.status !== "success") {
            throw new Error("Failed to load clips");
        }

        const clips = resData.clips;
        container.innerHTML = "";

        if (clips.length === 0) {
            container.innerHTML = `<p class="empty-state">No clips generated yet. Analyze a stream above and cut your first highlight!</p>`;
            return;
        }

        clips.forEach(c => {
            const dateStr = new Date(c.created_at * 1000).toLocaleString();
            const card = document.createElement("div");
            card.className = "clip-item-card";
            card.innerHTML = `
                <div class="video-container">
                    <video controls preload="metadata">
                        <source src="${c.url}" type="video/mp4">
                        Your browser does not support the video tag.
                    </video>
                </div>
                <div class="clip-info">
                    <h4>${c.filename}</h4>
                    <div class="clip-meta">
                        <span>📦 ${c.size_mb} MB</span>
                        <span>🕒 ${dateStr}</span>
                    </div>
                    <div class="clip-actions">
                        <a href="${c.url}" download="${c.filename}" class="btn btn-primary btn-sm" style="text-decoration: none;">
                            <i data-lucide="download"></i> Download MP4
                        </a>
                        <button class="btn btn-secondary btn-sm" onclick="deleteClip('${c.filename}')">
                            <i data-lucide="trash-2"></i> Delete
                        </button>
                    </div>
                </div>
            `;
            container.appendChild(card);
        });

        lucide.createIcons();
    } catch (err) {
        console.error(err);
        container.innerHTML = `<p class="empty-state" style="color: #ff6b6b;">Error loading clips gallery: ${err.message}</p>`;
    }
}

async function deleteClip(filename) {
    if (!confirm(`Are you sure you want to delete ${filename}?`)) return;

    // Release browser video handles on Windows (prevents WinError 32 file lock)
    document.querySelectorAll("video").forEach(v => {
        v.pause();
        v.querySelectorAll("source").forEach(s => s.remove());
        v.removeAttribute("src");
        v.load();
    });
    await new Promise(r => setTimeout(r, 300)); // wait 300ms for OS handle release

    try {
        const resp = await fetch(`/api/clips/${encodeURIComponent(filename)}`, {
            method: "DELETE"
        });
        const resData = await resp.json();
        if (!resp.ok || resData.status !== "success") {
            throw new Error(resData.detail || "Failed to delete");
        }
        showToast(`🗑️ Deleted ${filename}`);
        loadGallery();
    } catch (err) {
        showToast(`❌ Delete error: ${err.message}`);
    }
}

function showToast(msg) {
    const toast = document.getElementById("toast");
    toast.textContent = msg;
    toast.classList.remove("hidden");
    
    setTimeout(() => {
        toast.classList.add("hidden");
    }, 4000);
}
