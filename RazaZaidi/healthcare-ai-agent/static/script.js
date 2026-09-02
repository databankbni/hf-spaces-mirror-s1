const API = "";
let token = localStorage.getItem("hc_token") || null;
let username = localStorage.getItem("hc_username") || "Guest";
let chatActive = false;
let attachedFile = null;
let attachedFileData = null; // Store file info for rendering
let voiceEnabled = false;
let recognition = null;
let isRecording = false;

// ── Constants ───────────────────────────────────────
const INTENT_MAP = {
    emergency: { icon: "🚨", label: "Emergency" },
    research: { icon: "🔬", label: "Research" },
    lifestyle: { icon: "🌿", label: "Lifestyle" },
    general: { icon: "💬", label: "General" },
    greeting: { icon: "👋", label: "Greeting" },
    goodbye: { icon: "👋", label: "Goodbye" }
};

document.addEventListener("DOMContentLoaded", () => {
    updateUI();
    setupInput();
    if (token) loadSidebarHistory();
});

// ── UI ──────────────────────────────────────────────
function updateUI() {
    const li = !!token;
    document.getElementById("sideUsername").textContent = username;
    document.getElementById("sideAvatar").textContent = username[0].toUpperCase();
    document.getElementById("sideRole").textContent = li ? "Logged in ✓" : "Click to login";
    document.getElementById("authTopBtn").textContent = li ? "Logout" : "Login";
    document.getElementById("userCard").onclick = li ? confirmLogout : showAuthModal;
    document.getElementById("userActionBtn").onclick = li ? confirmLogout : showAuthModal;
}

// ── Toast ───────────────────────────────────────────
function showToast(msg) {
    let t = document.getElementById("toast");
    if (!t) {
        t = document.createElement("div");
        t.id = "toast";
        t.className = "toast";
        document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.opacity = "1";
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.style.opacity = "0", 2500);
}

// ── Voice Response Toggle ───────────────────────────
function syncVoiceUI() {
    const toggle = document.getElementById("voiceToggle");
    const btn = document.getElementById("voiceRespBtn");
    if (toggle) toggle.checked = voiceEnabled;
    if (btn) {
        if (voiceEnabled) {
            btn.textContent = "🔊 Voice On";
            btn.classList.add("voice-active");
        } else {
            btn.textContent = "🔇 Voice Off";
            btn.classList.remove("voice-active");
        }
    }
}

function toggleVoiceResponse() {
    voiceEnabled = !voiceEnabled;
    localStorage.setItem("voiceEnabled", voiceEnabled);
    syncVoiceUI();
    if (!voiceEnabled) window.speechSynthesis?.cancel();
    showToast(voiceEnabled ? "Voice response enabled 🔊" : "Voice response disabled 🔇");
}

// ── Sidebar ─────────────────────────────────────────
function openSidebar() {
    document.getElementById("sidebar").classList.add("open");
    document.getElementById("overlay").classList.add("show");
}
function closeSidebar() {
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("overlay").classList.remove("show");
}

// ── Pages ───────────────────────────────────────────
function showWelcome() {
    document.getElementById("welcomePage").style.display = "flex";
    document.getElementById("chatPage").style.display = "none";
    chatActive = false;
    window.speechSynthesis?.cancel();
}
function showChatPage() {
    document.getElementById("welcomePage").style.display = "none";
    document.getElementById("chatPage").style.display = "flex";
    chatActive = true;
}

function goToChat(mode) {
    showChatPage();
    const labels = {
        emergency: "🚨 Emergency",
        research: "🔬 Research",
        lifestyle: "🌿 Lifestyle",
        general: "💬 General"
    };
    const placeholders = {
        emergency: "Describe your emergency situation...",
        research: "Ask about AI in healthcare, diagnostics, telemedicine...",
        lifestyle: "Ask about diet, sleep, exercise, wellness routines...",
        general: "Ask any health or medical question..."
    };
    const label = document.getElementById("chatModeLabel");
    if (label) label.textContent = labels[mode] || "💬 General";
    document.getElementById("msgInput").placeholder = placeholders[mode] || "Ask about health...";
    document.getElementById("msgInput").focus();
    closeSidebar();
}

function setInput(text) {
    showChatPage();
    document.getElementById("msgInput").value = text;
    document.getElementById("msgInput").focus();
}

function newChat() {
    document.getElementById("messages").innerHTML = "";
    showWelcome();
    closeSidebar();
}

// ── Clear Buttons ───────────────────────────────────
function clearChat() {
    if (!confirm("Clear current chat messages?")) return;
    document.getElementById("messages").innerHTML = "";
    window.speechSynthesis?.cancel();
    showToast("Chat cleared 🗑");
}

async function clearAllHistory() {
    if (!token) {
        showToast("Please login to clear saved history!");
        return;
    }
    if (!confirm("Clear all saved chat history? This cannot be undone.")) return;
    try {
        const res = await fetch(`${API}/api/clear?token=${token}`, { method: "POST" });
        const data = await res.json();
        if (data.status === "ok") {
            document.getElementById("historyList").innerHTML = "";
            showToast("All history cleared! 🗑");
        }
    } catch {
        showToast("Failed to clear history. Try again.");
    }
}

// ── Chat ────────────────────────────────────────────
async function sendMessage() {
    const input = document.getElementById("msgInput");
    const msg = input.value.trim();
    if (!msg && !attachedFile) return;
    const fileToSend = attachedFile;
    const fileDataToRender = attachedFileData ? { ...attachedFileData } : null;
    input.value = "";
    input.style.height = "auto";
    if (!chatActive) showChatPage();

    // Add message with attachment if present
    const messageAttachments = fileToSend && fileDataToRender ? [fileDataToRender] : [];
    addMessage(msg, "user", "", messageAttachments);

    // Clear attachment preview
    removeAttachment();

    showTyping();
    try {
        let res;
        if (fileToSend) {
            const formData = new FormData();
            formData.append('file', fileToSend);
            formData.append('message', msg);
            formData.append('token', token || '');
            res = await fetch(`${API}/api/chat-upload`, { method: 'POST', body: formData });
            showToast('File attached and sent');
        } else {
            res = await fetch(`${API}/api/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: msg, token: token })
            });
        }
        const rawText = await res.text();
        let data = null;
        try {
            data = rawText ? JSON.parse(rawText) : null;
        } catch {
            data = null;
        }
        hideTyping();
        if (res.ok && data && data.status === "ok") {
            const historySeed = msg || (fileDataToRender ? `Analyze ${fileDataToRender.name}` : "Uploaded file");
            addMessage(data.response, "ai", data.intent);
            addHistoryItem(historySeed, data.response, data.intent);
        } else {
            const detail = data?.detail || data?.response || rawText || "Sorry something went wrong. Please try again.";
            addMessage(detail, "ai", "general");
        }
    } catch (e) {
        hideTyping();
        addMessage(`Connection error. ${e?.message || "Make sure the server is running."}`, "ai", "general");
    }
}

function handleAttachClick() {
    document.getElementById('chatFileInput').click();
}

function getFileIcon(file) {
    const type = file.type;
    const ext = file.name.split('.').pop().toLowerCase();
    if (type.startsWith('image/')) return '🖼️';
    if (ext === 'pdf') return '📄';
    if (['doc', 'docx'].includes(ext)) return '📝';
    if (ext === 'txt') return '📃';
    return '📎';
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function renderAttachmentPreview() {
    const existing = document.getElementById('attachmentPreview');
    if (existing) existing.remove();
    if (!attachedFile) return;

    const previewDiv = document.createElement('div');
    previewDiv.id = 'attachmentPreview';
    previewDiv.className = 'attachment-preview';
    
    previewDiv.innerHTML = `
        <div class="attachment-icon">${getFileIcon(attachedFile)}</div>
        <div class="attachment-info">
            <div class="attachment-name">${attachedFile.name}</div>
            <div class="attachment-meta">${formatFileSize(attachedFile.size)}</div>
        </div>
        <button class="attachment-remove" onclick="removeAttachment()" title="Remove file">✕</button>
    `;

    const inputArea = document.querySelector('.input-area');
    if (inputArea) {
        inputArea.insertBefore(previewDiv, inputArea.firstChild);
    }
}

function removeAttachment() {
    attachedFile = null;
    attachedFileData = null;
    const preview = document.getElementById('attachmentPreview');
    if (preview) preview.remove();
    const input = document.getElementById('chatFileInput');
    if (input) input.value = '';
}

function handleAttachSelect(e) {
    const file = e.target.files[0];
    if (!file) return;
    
    const validTypes = [
        'application/pdf',
        'image/jpeg', 'image/png', 'image/bmp', 'image/tiff',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain'
    ];
    const validExts = ['.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.doc', '.docx', '.txt'];
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    
    const normalizedType = (file.type || '').toLowerCase().trim();
    const isTypeValid = validTypes.includes(normalizedType);
    const isExtValid = validExts.includes(ext);
    
    if (!isTypeValid && !isExtValid) { 
        showToast('Invalid file type'); 
        return; 
    }
    if (file.size > 10*1024*1024) { 
        showToast('File too large'); 
        return; 
    }
    
    attachedFile = file;
    attachedFileData = {
        name: file.name,
        size: file.size,
        type: normalizedType
    };
    
    renderAttachmentPreview();
    showToast(`Attached: ${file.name}`);
}

function addMessage(text, role, intent = "", attachments = []) {
    const msgs = document.getElementById("messages");
    const wrap = document.createElement("div");
    wrap.className = `msg ${role}`;
    const av = role === "user" ? username[0].toUpperCase() : "🏥";
    
    // Normalize intent
    const cleanIntent = (intent || "").toLowerCase().trim();
    const config = INTENT_MAP[cleanIntent];
    
    let badgeHtml = "";
    if (role === "ai" && cleanIntent) {
        const icon = config ? config.icon : "💬";
        const label = config ? config.label : cleanIntent.charAt(0).toUpperCase() + cleanIntent.slice(1);
        badgeHtml = `<div class="msg-badge ${cleanIntent}">${icon} ${label}</div>`;
    }
    
    // Render attachments
    let attachmentsHtml = "";
    if (attachments && attachments.length > 0 && role === "user") {
        attachments.forEach(att => {
            const ext = att.name.split('.').pop().toLowerCase();
            let fileIcon = "📎";
            if (att.type && att.type.startsWith('image/')) fileIcon = "🖼️";
            else if (ext === 'pdf') fileIcon = "📄";
            else if (['doc', 'docx'].includes(ext)) fileIcon = "📝";
            else if (ext === 'txt') fileIcon = "📃";
            
            attachmentsHtml += `
                <div class="msg-file-card">
                    <div class="msg-file-icon">${fileIcon}</div>
                    <div class="msg-file-info">
                        <div class="msg-file-name">${att.name}</div>
                        <div class="msg-file-meta">${formatFileSize(att.size)}</div>
                    </div>
                </div>
            `;
        });
    }
    
    const bc = config ? cleanIntent : "";
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    
    let bubbleContent = attachmentsHtml;
    if (text) {
        bubbleContent += `<div class="msg-text">${formatText(text)}</div>`;
    }
    
    wrap.innerHTML = `
        <div class="msg-avatar">${av}</div>
        <div class="msg-body">
            ${badgeHtml}
            <div class="msg-bubble ${bc}">${bubbleContent}</div>
            <div class="msg-time">${time}</div>
        </div>`;
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;
}

function formatText(t) {
    return t
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.*?)\*/g, "<em>$1</em>")
        .replace(/\n/g, "<br>");
}

function showTyping() {
    const msgs = document.getElementById("messages");
    const d = document.createElement("div");
    d.className = "msg ai"; d.id = "typingIndicator";
    d.innerHTML = `
        <div class="msg-avatar">🏥</div>
        <div class="msg-body">
            <div class="typing-bubble">
                <span></span><span></span><span></span>
            </div>
        </div>`;
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
}
function hideTyping() { document.getElementById("typingIndicator")?.remove(); }

// ── History ─────────────────────────────────────────
function addHistoryItem(message, response, intent) {
    const list = document.getElementById("historyList");
    const item = document.createElement("div");
    item.className = "history-item";
    
    const cleanIntent = (intent || "").toLowerCase().trim();
    const config = INTENT_MAP[cleanIntent];
    const icon = config ? config.icon : "💬";
    
    item.textContent = `${icon} ${message.substring(0, 32)}${message.length > 32 ? "..." : ""}`;
    item.onclick = () => loadConversation(message, response, intent);
    list.insertBefore(item, list.firstChild);
}

function loadConversation(message, response, intent) {
    showChatPage();
    document.getElementById("messages").innerHTML = "";
    addMessage(message, "user");
    addMessage(response, "ai", intent);
    closeSidebar();
}

async function loadSidebarHistory() {
    if (!token) return;
    try {
        const res = await fetch(`${API}/api/history?token=${token}`);
        const data = await res.json();
        if (data.status === "ok" && data.history) {
            const list = document.getElementById("historyList");
            list.innerHTML = "";
            
            [...data.history].reverse().forEach(h => {
                const item = document.createElement("div");
                item.className = "history-item";
                
                const cleanIntent = (h.intent || "").toLowerCase().trim();
                const config = INTENT_MAP[cleanIntent];
                const icon = config ? config.icon : "💬";
                
                item.textContent = `${icon} ${h.message.substring(0, 32)}${h.message.length > 32 ? "..." : ""}`;
                item.onclick = () => loadConversation(h.message, h.response, h.intent);
                list.appendChild(item);
            });
        }
    } catch (e) { console.log("History load error:", e) }
}

// ── Voice Input ─────────────────────────────────────
function setupVoice() {
    if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SR();
        recognition.lang = "en-US";
        recognition.onresult = e => {
            document.getElementById("msgInput").value = e.results[0][0].transcript;
            stopRecording();
            showToast("Voice captured! Press Enter to send.");
        };
        recognition.onerror = recognition.onend = () => stopRecording();
    }
}

function toggleVoice() {
    if (!recognition) { showToast("Voice input needs Chrome browser!"); return; }
    isRecording ? stopRecording() : startRecording();
}

function startRecording() {
    isRecording = true;
    recognition.start();
    const b = document.getElementById("voiceBtn");
    b.classList.add("recording");
    b.textContent = "⏹";
    showToast("🎤 Listening... speak now");
}

function stopRecording() {
    isRecording = false;
    if (recognition) recognition.stop();
    const b = document.getElementById("voiceBtn");
    b.classList.remove("recording");
    b.textContent = "🎤";
}

// ── Voice Output ────────────────────────────────────
// ═══════════════════════════════════════════════
// FIXED VOICE — Reads FULL answer without cutoff
// Splits long text into chunks for browser limit
// ═══════════════════════════════════════════════
function speak(text) {
    // Stop any current speech first
    window.speechSynthesis.cancel();

    // IF MUTED -> DO NOT START SPEAKING
    if (!voiceEnabled) return;

    // Clean text — remove markdown symbols
    let cleanText = text
        .replace(/\*\*(.*?)\*\*/g, '$1')   // remove **bold**
        .replace(/\*(.*?)\*/g, '$1')        // remove *italic*
        .replace(/#{1,6}\s/g, '')           // remove ### headers
        .replace(/`{1,3}[^`]*`{1,3}/g, '') // remove `code`
        .replace(/[•▸\-]\s/g, '. ')        // bullets to pause
        .replace(/\n\n/g, '. ')             // double newline to pause
        .replace(/\n/g, ' ')                // single newline to space
        .replace(/⚕️|⚠️|🚨|✅|📌|👋|🔬|🌿|💡/g, '') // remove emojis
        .replace(/\s+/g, ' ')               // clean extra spaces
        .trim();

    // Split into sentences (browser limit fix!)
    // Browser cuts off after ~200 chars in one utterance
    const sentences = cleanText.match(/[^\.!\?]+[\.!\?]+/g) || [cleanText];

    let index = 0;

    function speakNext() {
        // IF USER MUTED WHILE SPEAKING -> STOP IMMEDIATELY
        if (!voiceEnabled) {
            window.speechSynthesis.cancel();
            return;
        }

        if (index >= sentences.length) return;

        const chunk = sentences[index].trim();
        if (!chunk) {
            index++;
            speakNext();
            return;
        }

        const utterance = new SpeechSynthesisUtterance(chunk);

        // Voice settings
        utterance.rate = 0.95;  // slightly slower = clearer
        utterance.pitch = 1.0;
        utterance.volume = 1.0;

        // Set English voice if available
        const voices = window.speechSynthesis.getVoices();
        const englishVoice = voices.find(v =>
            v.lang.startsWith('en') && !v.name.includes('Google')
        ) || voices.find(v => v.lang.startsWith('en'));
        if (englishVoice) utterance.voice = englishVoice;

        // When this chunk ends → speak next chunk!
        utterance.onend = function () {
            index++;
            speakNext();
        };

        // If error → skip and continue
        utterance.onerror = function () {
            index++;
            speakNext();
        };

        window.speechSynthesis.speak(utterance);
    }

    // Chrome bug fix — resume if paused
    window.speechSynthesis.resume();

    // Start speaking!
    setTimeout(speakNext, 50);
}
// ═══════════════════════════════════════════════
// CHROME BUG FIX
// Chrome pauses speech after 15 seconds
// This keepAlive prevents that!
// ═══════════════════════════════════════════════
setInterval(function () {
    if (window.speechSynthesis.speaking) {
        window.speechSynthesis.resume();
    }
}, 10000);

// ── Input Setup ─────────────────────────────────────
function setupInput() {
    const inp = document.getElementById("msgInput");
    inp.addEventListener("keydown", e => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    inp.addEventListener("input", () => {
        inp.style.height = "auto";
        inp.style.height = Math.min(inp.scrollHeight, 120) + "px";
    });
}

// ── Auth ────────────────────────────────────────────
function handleAuthClick() { token ? confirmLogout() : showAuthModal(); }

function showAuthModal() {
    showLogin();
    document.getElementById("authModal").classList.add("show");
}

function closeModal() {
    document.getElementById("authModal").classList.remove("show");
    document.getElementById("li-err").textContent = "";
    document.getElementById("rg-err").textContent = "";
}

function showLogin() {
    document.getElementById("loginView").style.display = "block";
    document.getElementById("regView").style.display = "none";
}

function showReg() {
    document.getElementById("loginView").style.display = "none";
    document.getElementById("regView").style.display = "block";
}

async function doLogin() {
    const u = document.getElementById("li-user").value.trim();
    const p = document.getElementById("li-pass").value;
    const err = document.getElementById("li-err");
    if (!u || !p) { err.textContent = "Please fill all fields!"; return; }
    err.textContent = "Logging in...";
    try {
        const res = await fetch(`${API}/api/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: u, password: p })
        });
        const data = await res.json();
        if (data.status === "ok") {
            token = data.token;
            username = data.username;
            localStorage.setItem("hc_token", token);
            localStorage.setItem("authToken", token);
            localStorage.setItem("hc_username", username);
            updateUI();
            closeModal();
            loadSidebarHistory();
            showToast(`Welcome back ${username}! 👋`);
        } else {
            err.textContent = data.detail || "Invalid credentials!";
        }
    } catch {
        err.textContent = "Server connection error!";
    }
}

async function doRegister() {
    const u = document.getElementById("rg-user").value.trim();
    const e = document.getElementById("rg-email").value.trim();
    const p = document.getElementById("rg-pass").value;
    const err = document.getElementById("rg-err");
    if (!u || !e || !p) { err.textContent = "Please fill all fields!"; return; }
    if (p.length < 6) { err.textContent = "Password min 6 characters!"; return; }
    err.textContent = "Creating account...";
    try {
        const res = await fetch(`${API}/api/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: u, email: e, password: p })
        });
        const data = await res.json();
        if (data.status === "ok") {
            err.textContent = "";
            document.getElementById("li-user").value = u;
            showLogin();
            showToast("Account created! Please login. ✅");
        } else {
            err.textContent = data.detail || "Registration failed!";
        }
    } catch {
        err.textContent = "Server connection error!";
    }
}

function confirmLogout() {
    if (confirm("Are you sure you want to logout?")) {
        token = null;
        username = "Guest";
        localStorage.removeItem("hc_token");
        localStorage.removeItem("authToken");
        localStorage.removeItem("hc_username");
        document.getElementById("historyList").innerHTML = "";
        updateUI();
        newChat();
        showToast("Logged out successfully!");
    }
}
