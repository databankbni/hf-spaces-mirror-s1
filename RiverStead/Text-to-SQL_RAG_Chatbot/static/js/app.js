/**
 * F1InsightAI — Cinematic Data Interface
 * tsParticles + Omni-Search + Bento Box Grid
 */

// ── DOM Elements ────────────────────────────────────────────
const appShell = document.getElementById('appShell');
const responseCanvas = document.getElementById('responseCanvas');
const searchHero = document.getElementById('searchHero');
const searchDock = document.getElementById('searchDock');
const chatForm = document.getElementById('chatForm');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const toastContainer = document.getElementById('toastContainer');

// History Drawer
const historyTrigger = document.getElementById('historyTrigger');
const historyDrawer = document.getElementById('historyDrawer');
const drawerOverlay = document.getElementById('drawerOverlay');
const drawerClose = document.getElementById('drawerClose');
const chatList = document.getElementById('chatList');
const newChatBtn = document.getElementById('newChatBtn');
const clearAllChats = document.getElementById('clearAllChats');

// Stats
const statTables = document.getElementById('statTables');
const statRows = document.getElementById('statRows');
const statColumns = document.getElementById('statColumns');
const statModel = document.getElementById('statModel');


// ── State ───────────────────────────────────────────────────
let isLoading = false;
let currentChatId = null;
let conversations = [];
let isDocked = false;
let particlesInstance = null;


// ── Mouse-Following Spotlight ───────────────────────────────
(function() {
    const spotlight = document.getElementById('mouseSpotlight');
    if (!spotlight) return;
    document.addEventListener('mousemove', (e) => {
        spotlight.style.setProperty('--mx', e.clientX + 'px');
        spotlight.style.setProperty('--my', e.clientY + 'px');
    });
})();

// ── 3D Card Tilt on Hover ───────────────────────────────────
function initCardTilt(card) {
    card.addEventListener('mousemove', (e) => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;
        const rotateX = ((y - centerY) / centerY) * -5;
        const rotateY = ((x - centerX) / centerX) * 5;
        card.style.transform = `perspective(800px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(1.01)`;
    });
    card.addEventListener('mouseleave', () => {
        card.style.transform = 'perspective(800px) rotateX(0) rotateY(0) scale(1)';
    });
}
// Auto-apply tilt to any new bento cards via MutationObserver
const tiltObserver = new MutationObserver((mutations) => {
    mutations.forEach((m) => {
        m.addedNodes.forEach((node) => {
            if (node.nodeType === 1) {
                node.querySelectorAll?.('.bento-card')?.forEach(initCardTilt);
                if (node.classList?.contains('bento-card')) initCardTilt(node);
            }
        });
    });
});
tiltObserver.observe(document.body, { childList: true, subtree: true });

// ── Typewriter Effect ───────────────────────────────────────
function typeWriter(el, text, speed = 50, delay = 0) {
    el.textContent = '';
    el.style.opacity = '1';
    let i = 0;
    setTimeout(() => {
        const type = () => {
            if (i < text.length) {
                el.textContent += text.charAt(i);
                i++;
                setTimeout(type, speed);
            } else {
                el.classList.add('typed-done');
            }
        };
        type();
    }, delay);
}

// ── Rotating Placeholder Typewriter ─────────────────────────
function initPlaceholderCycle(input) {
    const phrases = [
        'Who has the most race wins?',
        'Compare Hamilton vs Verstappen stats...',
        'Show me the 2023 race calendar',
        'Average pit stop duration by team',
        'Which circuit has the most overtakes?',
        'Top 5 fastest lap times at Monza',
        'How many championships does Ferrari have?',
    ];
    let phraseIdx = 0;
    let charIdx = 0;
    let isDeleting = false;
    let isPaused = false;

    function tick() {
        if (isPaused || document.activeElement === input) {
            setTimeout(tick, 200);
            return;
        }

        const current = phrases[phraseIdx];

        if (!isDeleting) {
            input.setAttribute('placeholder', current.substring(0, charIdx + 1));
            charIdx++;
            if (charIdx === current.length) {
                isDeleting = true;
                setTimeout(tick, 2000); // pause at full text
                return;
            }
            setTimeout(tick, 60);
        } else {
            input.setAttribute('placeholder', current.substring(0, charIdx));
            charIdx--;
            if (charIdx === 0) {
                isDeleting = false;
                phraseIdx = (phraseIdx + 1) % phrases.length;
                setTimeout(tick, 400); // pause before next phrase
                return;
            }
            setTimeout(tick, 30);
        }
    }

    // Pause cycle when user focuses input
    input.addEventListener('focus', () => { isPaused = true; input.setAttribute('placeholder', 'Ask about F1...'); });
    input.addEventListener('blur', () => { if (!input.value) isPaused = false; });

    setTimeout(tick, 1500); // start after page loads
}

// ── Initialize ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initParticles();
    checkHealth();
    loadStats();
    loadConversations();
    autoResizeTextarea();

    // Typewriter on subtitle after entrance animation
    const subtitle = document.querySelector('.hero-subtitle');
    if (subtitle) {
        const text = subtitle.dataset.text || subtitle.textContent;
        subtitle.textContent = '';
        typeWriter(subtitle, text, 40, 600);
    }

    // Rotating placeholder in search box
    initPlaceholderCycle(userInput);
});


// ── tsParticles ─────────────────────────────────────────────
async function initParticles() {
    try {
        particlesInstance = await tsParticles.load("tsparticles", {
            fullScreen: false,
            background: { color: "transparent" },
            fpsLimit: 60,
            particles: {
                number: { value: 50, density: { enable: true, area: 900 } },
                color: { value: ["#E10600", "#FF6B35", "#ff4444", "#cc3300"] },
                shape: { type: "circle" },
                opacity: {
                    value: { min: 0.15, max: 0.4 },
                    animation: { enable: true, speed: 0.8, minimumValue: 0.1, sync: false }
                },
                size: {
                    value: { min: 1, max: 3 },
                    animation: { enable: true, speed: 1.5, minimumValue: 0.5, sync: false }
                },
                links: {
                    enable: true,
                    distance: 160,
                    color: "#E10600",
                    opacity: 0.08,
                    width: 1,
                },
                move: {
                    enable: true,
                    speed: 0.6,
                    direction: "none",
                    outModes: { default: "out" },
                },
            },
            interactivity: {
                events: {
                    onHover: { enable: true, mode: "grab" },
                },
                modes: {
                    grab: { distance: 180, links: { opacity: 0.15 } },
                },
            },
            detectRetina: true,
        });
    } catch (e) {
        console.warn('tsParticles init failed:', e);
    }
}

function accelerateParticles() {
    if (!particlesInstance) return;
    const p = particlesInstance;
    try {
        p.options.particles.move.speed = 3;
        p.options.particles.opacity.value = { min: 0.2, max: 0.6 };
        p.options.particles.links.opacity = 0.15;
        p.refresh();
    } catch(e) { /* ignore */ }
}

function calmParticles() {
    if (!particlesInstance) return;
    const p = particlesInstance;
    try {
        p.options.particles.move.speed = 0.6;
        p.options.particles.opacity.value = { min: 0.15, max: 0.4 };
        p.options.particles.links.opacity = 0.08;
        p.refresh();
    } catch(e) { /* ignore */ }
}


// ── Health Check ────────────────────────────────────────────
async function checkHealth() {
    const sbDot = document.getElementById('sbDot');
    const sbConnection = document.getElementById('sbConnection');
    try {
        const res = await fetch('/api/health');
        const data = await res.json();
        if (data.status === 'healthy') {
            statusDot.className = 'status-dot online';
            statusText.textContent = data.rag_indexed ? data.model : 'Connecting...';
            // Status bar
            sbDot.className = 'sb-dot online';
            sbConnection.textContent = 'Connected to TiDB Cloud';
        } else {
            statusDot.className = 'status-dot error';
            statusText.textContent = 'DB disconnected';
            sbDot.className = 'sb-dot error';
            sbConnection.textContent = 'Disconnected';
        }
    } catch {
        statusDot.className = 'status-dot error';
        statusText.textContent = 'Offline';
        sbDot.className = 'sb-dot error';
        sbConnection.textContent = 'Offline';
    }
}


// ── Animated Counter ────────────────────────────────────────
function animateCount(el, target, duration = 1500, format = null) {
    const start = performance.now();
    const step = (now) => {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        // easeOutExpo
        const ease = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
        const current = Math.round(ease * target);
        el.textContent = format ? format(current) : current;
        if (progress < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
}

// ── Database Stats ──────────────────────────────────────────
async function loadStats() {
    const sbModel = document.getElementById('sbModel');
    const sbTables = document.getElementById('sbTables');
    const sbRows = document.getElementById('sbRows');
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        if (data.table_count !== undefined) {
            // Animated counting for hero stats
            animateCount(statTables, data.table_count, 1000);
            animateCount(statRows, data.total_rows || 0, 1800, n => n.toLocaleString());
            animateCount(statColumns, data.total_columns || 0, 1200);
            statModel.textContent = data.model || '—';
            // Status bar
            sbModel.textContent = `Model: ${data.model || '—'}`;
            sbTables.textContent = `${data.table_count} tables indexed`;
            sbRows.textContent = `${(data.total_rows || 0).toLocaleString()} rows`;
        }
    } catch { /* ignore */ }
}


// ── History Drawer ──────────────────────────────────────────
historyTrigger.addEventListener('click', openDrawer);
drawerOverlay.addEventListener('click', closeDrawer);
drawerClose.addEventListener('click', closeDrawer);

function openDrawer() {
    historyDrawer.classList.add('open');
    drawerOverlay.classList.add('open');
}
function closeDrawer() {
    historyDrawer.classList.remove('open');
    drawerOverlay.classList.remove('open');
}


// ── Conversations ───────────────────────────────────────────
async function loadConversations() {
    try {
        const res = await fetch('/api/conversations');
        const data = await res.json();
        conversations = data.conversations || [];
        renderChatList();
    } catch { /* ignore */ }
}

newChatBtn.addEventListener('click', () => {
    currentChatId = null;
    isDocked = false;
    appShell.classList.remove('docked');
    responseCanvas.innerHTML = '';
    renderChatList();
    closeDrawer();
    userInput.focus();
});

clearAllChats.addEventListener('click', async () => {
    if (!confirm('Delete all conversations?')) return;
    try {
        await fetch('/api/conversations/clear', { method: 'DELETE' });
        conversations = [];
        currentChatId = null;
        isDocked = false;
        appShell.classList.remove('docked');
        responseCanvas.innerHTML = '';
        renderChatList();
        showToast('All chats cleared', 'success');
    } catch { showToast('Failed to clear', 'error'); }
});

async function loadChat(id) {
    try {
        const res = await fetch(`/api/conversations/${id}`);
        const data = await res.json();
        currentChatId = id;
        closeDrawer();

        // Dock the search
        isDocked = true;
        appShell.classList.add('docked');

        // Render messages
        responseCanvas.innerHTML = '';
        const messages = data.messages || [];
        for (let i = 0; i < messages.length; i++) {
            const msg = messages[i];
            if (msg.role === 'user') {
                appendUserInline(msg.content);
            } else if (msg.role === 'assistant') {
                // Use stored data object if available, otherwise show as text
                if (msg.data && typeof msg.data === 'object') {
                    appendBentoGrid(msg.data);
                } else {
                    // Plain text fallback (old messages or errors)
                    const fallback = document.createElement('div');
                    fallback.className = 'bento-grid';
                    fallback.innerHTML = `<div class="bento-card bento-answer"><div class="answer-text">${renderMarkdown(msg.content || '')}</div></div>`;
                    responseCanvas.appendChild(fallback);
                }
            }
        }

        renderChatList();
        scrollToBottom();
    } catch {
        showToast('Failed to load chat', 'error');
    }
}

async function deleteChat(id, e) {
    e.stopPropagation();
    if (!confirm('Delete this conversation?')) return;
    try {
        await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
        if (currentChatId === id) {
            currentChatId = null;
            isDocked = false;
            appShell.classList.remove('docked');
            responseCanvas.innerHTML = '';
        }
        await loadConversations();
        showToast('Chat deleted', 'success');
    } catch { showToast('Failed to delete', 'error'); }
}

async function renameChat(id, e) {
    e.stopPropagation();
    const item = e.target.closest('.chat-item');
    const titleEl = item.querySelector('.chat-item-title');
    const currentTitle = titleEl.textContent.replace(/^📌\s*/, '');

    const input = document.createElement('input');
    input.className = 'chat-rename-input';
    input.value = currentTitle;
    titleEl.replaceWith(input);
    input.focus();
    input.select();

    // Prevent clicks on the input from triggering loadChat
    input.addEventListener('click', (ev) => ev.stopPropagation());
    input.addEventListener('mousedown', (ev) => ev.stopPropagation());

    const save = async () => {
        const newTitle = input.value.trim() || currentTitle;
        try {
            await fetch(`/api/conversations/${id}/rename`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle }),
            });
            await loadConversations();
        } catch { await loadConversations(); }
    };

    input.addEventListener('blur', save);
    input.addEventListener('keydown', (ev) => {
        ev.stopPropagation();
        if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
        if (ev.key === 'Escape') { input.value = currentTitle; input.blur(); }
    });
}

async function pinChat(id, e) {
    e.stopPropagation();
    // Find current pinned state and toggle it
    const chat = conversations.find(c => c.id === id);
    const newPinned = chat ? !chat.pinned : true;
    try {
        await fetch(`/api/conversations/${id}/pin`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pinned: newPinned }),
        });
        await loadConversations();
    } catch { showToast('Failed to pin', 'error'); }
}

// ── Three-dot Menu Toggle ───────────────────────────────────
function toggleChatMenu(chatId, e) {
    e.stopPropagation();
    // Close all other menus first
    document.querySelectorAll('.chat-dropdown.open').forEach(m => {
        if (m.id !== `chatMenu-${chatId}`) m.classList.remove('open');
    });
    const menu = document.getElementById(`chatMenu-${chatId}`);
    if (menu) menu.classList.toggle('open');
}

// Close dropdown when clicking outside
document.addEventListener('click', () => {
    document.querySelectorAll('.chat-dropdown.open').forEach(m => m.classList.remove('open'));
});


// ── Render Chat List ────────────────────────────────────────
function renderChatList() {
    if (conversations.length === 0) {
        chatList.innerHTML = `
            <div class="sidebar-empty">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
                <p>No conversations yet</p>
            </div>`;
        return;
    }

    const today = new Date().toDateString();
    const yesterday = new Date(Date.now() - 86400000).toDateString();
    let html = '';
    let lastDateLabel = '';
    let hasPinned = conversations.some(c => c.pinned);
    let pinnedSectionDone = false;

    conversations.forEach(chat => {
        if (chat.pinned && !pinnedSectionDone && lastDateLabel === '') {
            html += `<div class="sidebar-date-label">📌 Pinned</div>`;
        }
        if (!chat.pinned && !pinnedSectionDone && hasPinned) {
            pinnedSectionDone = true;
            lastDateLabel = '';
        }
        if (!chat.pinned) {
            const rawDate = chat.updated_at || chat.updatedAt || chat.created_at || chat.createdAt;
            const chatDateObj = rawDate ? new Date(rawDate) : new Date();
            const chatDate = chatDateObj.toDateString();
            let dateLabel;
            if (chatDate === today) dateLabel = 'Today';
            else if (chatDate === yesterday) dateLabel = 'Yesterday';
            else dateLabel = chatDateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            if (dateLabel !== lastDateLabel) {
                html += `<div class="sidebar-date-label">${dateLabel}</div>`;
                lastDateLabel = dateLabel;
            }
        }

        const isActive = chat.id === currentChatId;
        const pinIcon = chat.pinned ? '📌 ' : '';
        const pinTitle = chat.pinned ? 'Unpin' : 'Pin';
        const pinSvg = chat.pinned
            ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M16 2L7.5 10.5 2 22l11.5-5.5L22 8 16 2z"/></svg>'
            : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 2L7.5 10.5 2 22l11.5-5.5L22 8 16 2z"/></svg>';

        html += `
            <div class="chat-item${isActive ? ' active' : ''}${chat.pinned ? ' pinned' : ''}" onclick="loadChat('${chat.id}')">
                <div class="chat-item-content">
                    <div class="chat-item-title">${pinIcon}${escapeHtml(chat.title)}</div>
                </div>
                <button class="chat-dots-btn" onclick="toggleChatMenu('${chat.id}', event)" title="Options">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>
                </button>
                <div class="chat-dropdown" id="chatMenu-${chat.id}">
                    <button class="chat-dropdown-item" onclick="renameChat('${chat.id}', event)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                        Rename
                    </button>
                    <button class="chat-dropdown-item" onclick="pinChat('${chat.id}', event)">
                        ${pinSvg}
                        ${pinTitle}
                    </button>
                    <button class="chat-dropdown-item delete" onclick="deleteChat('${chat.id}', event)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        Delete
                    </button>
                </div>
            </div>`;
    });

    chatList.innerHTML = html;
}


// ── Form Handling ───────────────────────────────────────────
chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const msg = userInput.value.trim();
    if (msg && !isLoading) sendMessage(msg);
});

userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event('submit'));
    }
});

function autoResizeTextarea() {
    userInput.addEventListener('input', () => {
        userInput.style.height = 'auto';
        userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
    });
}

function askQuestion(text) {
    if (!isLoading) {
        userInput.value = text;
        sendMessage(text);
    }
}


// ── Send Message ────────────────────────────────────────────
async function sendMessage(message) {
    isLoading = true;
    sendBtn.disabled = true;

    // Dock search bar on first message
    if (!isDocked) {
        isDocked = true;
        appShell.classList.add('docked');
    }

    // Show user message
    appendUserInline(message);

    userInput.value = '';
    userInput.style.height = 'auto';

    // Show loading
    const loadingEl = appendLoading();
    accelerateParticles();

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                conversation_id: currentChatId,
            }),
        });

        const data = await res.json();
        removeElement(loadingEl);
        calmParticles();

        if (data.conversation_id) {
            currentChatId = data.conversation_id;
        }

        await loadConversations();

        if (data.error && !data.answer) {
            appendErrorBento(data.error, message);
        } else {
            appendBentoGrid(data);
        }
    } catch (err) {
        removeElement(loadingEl);
        calmParticles();
        appendErrorBento('Failed to connect to the server. Please check if the app is running.', message);
    }

    isLoading = false;
    sendBtn.disabled = false;
    userInput.focus();
}


// ── DOM Rendering ───────────────────────────────────────────
function appendUserInline(text) {
    const div = document.createElement('div');
    div.className = 'user-message-inline';
    div.innerHTML = `
        <span class="user-msg-text">${escapeHtml(text)}</span>
        <button class="user-copy-btn" title="Copy question" onclick="copyQuestion(this, '${escapeForTemplate(text)}')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
        </button>`;
    responseCanvas.appendChild(div);
    scrollToBottom();
}

function copyQuestion(btn, text) {
    navigator.clipboard.writeText(text).then(() => {
        btn.innerHTML = '✓';
        setTimeout(() => {
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
        }, 1500);
        showToast('Question copied', 'success');
    }).catch(() => showToast('Failed to copy', 'error'));
}

function appendBentoGrid(data) {
    const grid = document.createElement('div');
    grid.className = 'bento-grid';

    const hasChart = data.results && data.results.rows && data.results.rows.length > 0
        && data.results.rows.length <= 50 && data.results.columns.length >= 2;
    const chartType = hasChart ? detectChartType(data.results.columns, data.results.rows) : null;
    const chartId = 'chart_' + Date.now();
    const tableId = 'table_' + Date.now();

    // Card 1: Answer
    const faithScore = data.rag_metrics ? data.rag_metrics.faithfulness_score : null;
    let answerHtml = `
        <div class="bento-card bento-answer">
            <div class="answer-text">${renderMarkdown(data.answer || 'No answer generated.')}</div>
            <div class="answer-badges">`;
    if (data.execution_time) {
        answerHtml += `
                <div class="exec-badge">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                    </svg>
                    ${data.execution_time}s
                </div>`;
    }
    if (faithScore !== null && faithScore !== undefined) {
        const confCls = faithScore >= 0.8 ? 'good' : faithScore >= 0.5 ? 'ok' : 'bad';
        answerHtml += `
                <div class="confidence-badge ${confCls}">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                    </svg>
                    Confidence: ${(faithScore * 100).toFixed(0)}%
                </div>`;
    }
    answerHtml += `</div></div>`;
    grid.innerHTML = answerHtml;

    // Card 2: Chart (if applicable)
    if (chartType) {
        const chartCard = document.createElement('div');
        chartCard.className = 'bento-card bento-chart';
        chartCard.innerHTML = `
            <div class="chart-label">📊 Visualization</div>
            <div class="chart-wrap"><canvas id="${chartId}"></canvas></div>`;
        grid.appendChild(chartCard);
    }

    // Card 3: Table
    if (data.results && data.results.rows && data.results.rows.length > 0) {
        const tableCard = document.createElement('div');
        tableCard.className = 'bento-card bento-table';
        const cols = data.results.columns;
        const rows = data.results.rows;

        let tableHtml = `
            <div class="table-card-header">
                <div>
                    <span class="table-card-title">Query Results</span>
                    <span class="row-count">${data.results.row_count} row${data.results.row_count > 1 ? 's' : ''}</span>
                </div>
                <button class="csv-btn" onclick="downloadCSV('${tableId}')">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                    CSV
                </button>
            </div>
            <div class="table-scroll">
                <table class="results-table" id="${tableId}">
                    <thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>
                    <tbody>
                        ${rows.map(row =>
                            `<tr>${cols.map(c => `<td title="${escapeHtml(String(row[c] ?? ''))}">${escapeHtml(String(row[c] ?? 'NULL'))}</td>`).join('')}</tr>`
                        ).join('')}
                    </tbody>
                </table>
            </div>`;
        tableCard.innerHTML = tableHtml;
        grid.appendChild(tableCard);
    }

    // Card 4: Agent Steps (side-by-side with SQL)
    if (data.agent_steps && data.agent_steps.length > 0) {
        const stepsCard = document.createElement('div');
        stepsCard.className = `bento-card bento-steps${chartType ? '' : ' no-chart'}`;
        let stepsHtml = `
            <div class="steps-title" onclick="this.closest('.bento-steps').classList.toggle('expanded')">
                <span class="chevron">▶</span>
                🧠 Agent Reasoning (${data.agent_steps.length} steps)
            </div>
            <div class="steps-list">`;
        data.agent_steps.forEach((step, i) => {
            stepsHtml += `
                <div class="step-item">
                    <span class="step-num">${i + 1}</span>
                    <div>
                        <div class="step-node">${escapeHtml(step.node || '')}</div>
                        <div class="step-action">${escapeHtml(step.action || '')}</div>
                        <div class="step-result">${escapeHtml(step.result || '')}</div>
                    </div>
                </div>`;
        });
        stepsHtml += `</div>`;
        stepsCard.innerHTML = stepsHtml;
        grid.appendChild(stepsCard);
    }

    // Card 5: SQL (side-by-side with Agent Steps)
    if (data.sql) {
        const sqlCard = document.createElement('div');
        sqlCard.className = `bento-card bento-sql${chartType ? '' : ' no-chart'}`;
        sqlCard.innerHTML = `
            <div class="sql-card-header">
                <span class="sql-card-title">Generated SQL</span>
                <div class="sql-card-actions">
                    <button class="copy-btn" onclick="copySQL(this, \`${escapeForTemplate(data.sql)}\`)">Copy</button>
                    <button class="dl-btn" onclick="downloadSQL(\`${escapeForTemplate(data.sql)}\`)">↓ .sql</button>
                </div>
            </div>
            <pre>${highlightSQL(data.sql)}</pre>`;
        grid.appendChild(sqlCard);
    }

    // Card 6: RAG Evaluation Metrics (Progress Bar Style)
    if (data.rag_metrics && data.rag_metrics.mrr !== undefined) {
        const m = data.rag_metrics;
        const faithIcon = m.faithfulness_score >= 0.8 ? '✅' : m.faithfulness_score >= 0.5 ? '⚠️' : '❌';
        const metricsCard = document.createElement('div');
        metricsCard.className = `bento-card bento-metrics${chartType ? '' : ' no-chart'}`;

        const makeBar = (label, value, max = 1.0, thresholds = [0.8, 0.5]) => {
            const pct = Math.min((value / max) * 100, 100);
            const cls = value >= thresholds[0] ? 'good' : value >= thresholds[1] ? 'ok' : 'bad';
            const display = max === 1.0 ? value.toFixed(2) : (value * 100).toFixed(0) + '%';
            return `
                <div class="metric-bar-item">
                    <div class="metric-bar-header">
                        <span class="metric-bar-label">${label}</span>
                        <span class="metric-bar-value ${cls}">${display}</span>
                    </div>
                    <div class="metric-bar-track">
                        <div class="metric-bar-fill ${cls}" style="width: ${pct}%"></div>
                    </div>
                </div>`;
        };

        metricsCard.innerHTML = `
            <div class="metrics-title">📊 RAG Evaluation</div>
            <div class="metrics-bars">
                ${makeBar('MRR (Mean Reciprocal Rank)', m.mrr, 1.0, [0.8, 0.5])}
                ${makeBar('Recall@' + m.k, m.recall_at_k, 1.0, [0.8, 0.5])}
                ${makeBar('Context Relevance', m.context_relevance, 1.0, [0.5, 0.3])}
                ${makeBar('Faithfulness', m.faithfulness_score, 1.0, [0.8, 0.5])}
            </div>
            <div class="metrics-detail">
                <span class="metric-detail-label">Retrieved:</span> ${m.retrieved_tables ? m.retrieved_tables.join(', ') : '-'}
            </div>
            <div class="metrics-detail">
                <span class="metric-detail-label">Used in SQL:</span> ${m.tables_used_in_sql ? m.tables_used_in_sql.join(', ') : '-'}
            </div>`;
        grid.appendChild(metricsCard);
    }

    // Card 7: Follow-ups
    if (data.follow_ups && data.follow_ups.length > 0) {
        const fuCard = document.createElement('div');
        fuCard.className = 'bento-card bento-followups';
        fuCard.innerHTML = data.follow_ups.map(q =>
            `<button class="follow-pill" onclick="askQuestion('${escapeForTemplate(q)}')">${escapeHtml(q)}</button>`
        ).join('');
        grid.appendChild(fuCard);
    }

    // Error from SQL execution (partial)
    if (data.error && data.answer) {
        const errCard = document.createElement('div');
        errCard.className = 'bento-error';
        errCard.innerHTML = `
            <span>⚠️ ${escapeHtml(data.error)}</span>
            <button class="retry-btn" onclick="askQuestion('${escapeForTemplate(data.error)}')">Retry</button>`;
        grid.appendChild(errCard);
    }

    responseCanvas.appendChild(grid);
    scrollToBottom();

    // Render chart after DOM insertion
    if (chartType) {
        const canvas = document.getElementById(chartId);
        if (canvas) renderChart(canvas, data.results.columns, data.results.rows);
    }
}

function appendErrorBento(error, originalQuestion) {
    const div = document.createElement('div');
    div.className = 'bento-grid';
    div.innerHTML = `
        <div class="bento-error">
            <span>⚠️ ${escapeHtml(error)}</span>
            <button class="retry-btn" onclick="askQuestion('${escapeForTemplate(originalQuestion)}')">Retry</button>
        </div>`;
    responseCanvas.appendChild(div);
    scrollToBottom();
}

function appendLoading() {
    const div = document.createElement('div');
    div.className = 'f1-loader';
    div.innerHTML = `
        <div class="f1-loader-dots">
            <span></span><span></span><span></span>
        </div>
        <div class="f1-loader-text">
            <div>Analyzing your question...</div>
            <div class="loader-step" id="loaderStep">Classifying intent</div>
        </div>`;
    responseCanvas.appendChild(div);
    scrollToBottom();

    // Cycle through pipeline steps
    const steps = [
        'Classifying intent',
        'Retrieving schema context (RAG)',
        'Generating SQL query',
        'Executing on TiDB Cloud',
        'Validating results',
        'Generating answer',
    ];
    let stepIdx = 0;
    div._stepInterval = setInterval(() => {
        stepIdx = (stepIdx + 1) % steps.length;
        const stepEl = div.querySelector('#loaderStep');
        if (stepEl) stepEl.textContent = steps[stepIdx];
    }, 2000);

    return div;
}

function removeElement(el) {
    if (el) {
        if (el._stepInterval) clearInterval(el._stepInterval);
        if (el.parentNode) el.parentNode.removeChild(el);
    }
}


// ── CSV Export ──────────────────────────────────────────────
function downloadCSV(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    let csv = [];
    const rows = table.querySelectorAll('tr');
    rows.forEach(row => {
        const cells = row.querySelectorAll('th, td');
        const rowData = Array.from(cells).map(cell => {
            let text = cell.textContent.replace(/"/g, '""');
            return `"${text}"`;
        });
        csv.push(rowData.join(','));
    });

    const blob = new Blob([csv.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `f1_results_${Date.now()}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    showToast('CSV downloaded!', 'success');
}


// ── Copy / Download SQL ─────────────────────────────────────
function copySQL(btn, sql) {
    navigator.clipboard.writeText(sql).then(() => {
        btn.textContent = '✓ Copied';
        setTimeout(() => btn.textContent = 'Copy', 2000);
        showToast('SQL copied to clipboard', 'success');
    }).catch(() => showToast('Failed to copy', 'error'));
}

function downloadSQL(sql) {
    const blob = new Blob([sql], { type: 'application/sql;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `f1_query_${Date.now()}.sql`;
    link.click();
    URL.revokeObjectURL(url);
    showToast('SQL file downloaded!', 'success');
}


// ── Toast Notifications ─────────────────────────────────────
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icons = { success: '✓', error: '✕', info: 'ℹ' };
    toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span> ${escapeHtml(message)}`;
    toastContainer.appendChild(toast);
    setTimeout(() => {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 3000);
}


// ── SQL Syntax Highlighting ─────────────────────────────────
function highlightSQL(sql) {
    const escaped = escapeHtml(sql);
    const keywords = [
        'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN',
        'INNER JOIN', 'OUTER JOIN', 'ON', 'AS', 'AND', 'OR', 'NOT',
        'IN', 'LIKE', 'BETWEEN', 'IS', 'NULL', 'GROUP BY', 'ORDER BY',
        'HAVING', 'LIMIT', 'OFFSET', 'UNION', 'DISTINCT', 'CASE',
        'WHEN', 'THEN', 'ELSE', 'END', 'DESC', 'ASC', 'WITH', 'EXISTS',
    ];

    let result = escaped;
    keywords.forEach(kw => {
        const regex = new RegExp(`\\b(${kw})\\b`, 'gi');
        result = result.replace(regex, '<span class="sql-keyword">$1</span>');
    });

    const functions = ['COUNT', 'SUM', 'AVG', 'MAX', 'MIN', 'CONCAT', 'COALESCE', 'IFNULL', 'ROUND', 'CAST', 'DATE', 'YEAR', 'MONTH'];
    functions.forEach(fn => {
        const regex = new RegExp(`\\b(${fn})\\s*\\(`, 'gi');
        result = result.replace(regex, '<span class="sql-function">$1</span>(');
    });

    result = result.replace(/\b(\d+\.?\d*)\b/g, '<span class="sql-number">$1</span>');
    result = result.replace(/&#39;([^&#]*?)&#39;/g, '<span class="sql-string">\'$1\'</span>');

    return result;
}


// ── Chart.js Auto-Visualization ─────────────────────────────
function detectChartType(columns, rows) {
    if (!rows || rows.length === 0 || rows.length > 50) return null;
    if (columns.length < 2) return null;

    const textCols = [];
    const numCols = [];

    columns.forEach(col => {
        const values = rows.map(r => r[col]).filter(v => v !== null && v !== undefined);
        const numericCount = values.filter(v => !isNaN(Number(v)) && v !== '').length;
        if (numericCount > values.length * 0.7) numCols.push(col);
        else textCols.push(col);
    });

    if (textCols.length === 0 || numCols.length === 0) return null;

    const firstTextCol = textCols[0];
    const firstVal = String(rows[0][firstTextCol] || '');
    const isDateLike = /\d{4}[-/]\d{1,2}|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|q[1-4])\b/i.test(firstVal)
        || /^\d{4}$/.test(firstVal);

    if (isDateLike) return 'line';
    if (rows.length <= 8 && numCols.length === 1) return 'pie';
    return 'bar';
}

function renderChart(canvas, columns, rows) {
    const chartType = detectChartType(columns, rows);
    if (!chartType) return;

    // Columns that should NOT be plotted as datasets (IDs, keys, years)
    const skipPatterns = /^(.*id|year|round|number|grid|position_order|position_text)$/i;

    const textCols = [];
    const numCols = [];

    columns.forEach(col => {
        const values = rows.map(r => r[col]).filter(v => v !== null && v !== undefined);
        const numericCount = values.filter(v => !isNaN(Number(v)) && v !== '').length;
        if (numericCount > values.length * 0.7) {
            // Skip ID-like or key columns
            if (!skipPatterns.test(col)) {
                numCols.push(col);
            }
        } else {
            textCols.push(col);
        }
    });

    // If no plottable numeric columns after filtering, skip chart
    if (numCols.length === 0) return;

    // Limit to top 3 numeric columns for readability
    const plotCols = numCols.slice(0, 3);

    const labels = rows.map(r => String(r[textCols[0]] ?? ''));

    // Distinct, visually different colors (not all red)
    const distinctColors = [
        { bg: '#E1060099', border: '#E10600' },   // F1 Red
        { bg: '#3B82F699', border: '#3B82F6' },   // Blue
        { bg: '#10B98199', border: '#10B981' },   // Emerald
        { bg: '#F59E0B99', border: '#F59E0B' },   // Amber
        { bg: '#8B5CF699', border: '#8B5CF6' },   // Purple
    ];

    const pieColors = ['#E10600', '#3B82F6', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#6366F1', '#EF4444'];

    const datasets = plotCols.map((col, i) => {
        const data = rows.map(r => Number(r[col]) || 0);
        const palette = distinctColors[i % distinctColors.length];

        let bgColor = palette.bg;
        let borderColor = palette.border;

        if (chartType === 'bar' && plotCols.length === 1) {
            // Single dataset bar: gradient from red to orange
            bgColor = data.map((_, idx) => {
                const ratio = idx / Math.max(data.length - 1, 1);
                return ratio < 0.5 ? '#E1060099' : '#FF6B3599';
            });
            borderColor = data.map((_, idx) => {
                const ratio = idx / Math.max(data.length - 1, 1);
                return ratio < 0.5 ? '#E10600' : '#FF6B35';
            });
        }

        return {
            label: col.replace(/_/g, ' '),
            data: data,
            backgroundColor: chartType === 'pie'
                ? pieColors.slice(0, data.length)
                : bgColor,
            borderColor: chartType === 'pie'
                ? 'rgba(0,0,0,0.3)'
                : borderColor,
            borderWidth: 2,
            borderRadius: chartType === 'bar' ? 6 : 0,
            tension: 0.4,
            fill: chartType === 'line',
        };
    });

    const textColor = '#9090b0';

    new Chart(canvas, {
        type: chartType,
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: numCols.length > 1 || chartType === 'pie',
                    labels: { color: textColor, font: { family: 'Inter', size: 11 } },
                },
                tooltip: {
                    backgroundColor: 'rgba(20, 20, 35, 0.95)',
                    titleColor: '#e8e8f0',
                    bodyColor: '#9090b0',
                    borderColor: 'rgba(225, 6, 0, 0.3)',
                    borderWidth: 1,
                    cornerRadius: 8,
                    padding: 10,
                },
            },
            scales: chartType !== 'pie' ? {
                x: {
                    ticks: { color: textColor, font: { size: 10 }, maxRotation: 45 },
                    grid: { display: false },
                },
                y: {
                    ticks: { color: textColor, font: { size: 10 } },
                    grid: { display: false },
                    beginAtZero: true,
                },
            } : {},
        },
    });
}


// ── Utilities ───────────────────────────────────────────────
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function renderMarkdown(text) {
    if (!text) return '';
    
    // Normalize inline bullet points if they were placed inline without line breaks
    let normalized = text
        .replace(/([.!?:])\s+[-*•]\s+/g, '$1\n- ')
        .replace(/\s+[-*•]\s+\*\*/g, '\n- **');
    
    // First escape raw HTML for security
    let escaped = normalized
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    
    // Bold: **text** or __text__
    escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    escaped = escaped.replace(/__(.*?)__/g, '<strong>$1</strong>');
    
    // Italic: *text* or _text_
    escaped = escaped.replace(/(?<!\*)\*(?!\*)([^\*]+)(?<!\*)\*(?!\*)/g, '<em>$1</em>');
    
    // Inline code: `code`
    escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Process lines for bullet points, numbered lists, and paragraphs
    const lines = escaped.split('\n');
    let html = '';
    let inList = false;
    let listType = null;
    
    for (let i = 0; i < lines.length; i++) {
        let line = lines[i].trim();
        if (!line) {
            if (inList) {
                html += listType === 'ul' ? '</ul>' : '</ol>';
                inList = false;
                listType = null;
            }
            continue;
        }
        
        // Bullet list: - item or * item
        const bulletMatch = line.match(/^[-*•]\s+(.*)/);
        // Numbered list: 1. item
        const numMatch = line.match(/^(\d+)\.\s+(.*)/);
        
        if (bulletMatch) {
            if (!inList || listType !== 'ul') {
                if (inList) html += listType === 'ul' ? '</ul>' : '</ol>';
                html += '<ul class="ans-list">';
                inList = true;
                listType = 'ul';
            }
            html += `<li>${bulletMatch[1]}</li>`;
        } else if (numMatch) {
            if (!inList || listType !== 'ol') {
                if (inList) html += listType === 'ul' ? '</ul>' : '</ol>';
                html += '<ol class="ans-list">';
                inList = true;
                listType = 'ol';
            }
            html += `<li>${numMatch[2]}</li>`;
        } else {
            if (inList) {
                html += listType === 'ul' ? '</ul>' : '</ol>';
                inList = false;
                listType = null;
            }
            html += `<p>${line}</p>`;
        }
    }
    
    if (inList) {
        html += listType === 'ul' ? '</ul>' : '</ol>';
    }
    
    return html || escaped;
}

function escapeForTemplate(text) {
    return text.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/'/g, "\\'").replace(/\n/g, '\\n');
}

function scrollToBottom() {
    setTimeout(() => {
        responseCanvas.scrollTop = responseCanvas.scrollHeight;
    }, 50);
}

