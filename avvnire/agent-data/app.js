document.addEventListener('DOMContentLoaded', function() {

    "use strict";



    // ============ 全局变量 ============

    var typingEl = null;

    var currentFile = null;

    var currentFilePath = '/opt/data';



    // ============ 元素引用 ============

    var msgs = document.getElementById('messages');

    var input = document.getElementById('input');

    var sendBtn = document.getElementById('sendBtn');

    var statusEl = document.getElementById('status');



    // ============ 密码验证 ============

    function checkPwd() {

        var pwdEl = document.getElementById('pwd-input');

        var errEl = document.getElementById('pwd-error');

        var overlay = document.getElementById('auth-overlay');

        if (!pwdEl || !overlay) return;

        var pwd = pwdEl.value;

        if (pwd === '80699436') {

            sessionStorage.setItem('auth_ok', '1');

            overlay.style.display = 'none';

        } else {

            if (errEl) errEl.textContent = '❌ 密码错误';

            pwdEl.value = '';

            pwdEl.focus();

        }

    }

    window.checkPwd = checkPwd;



    // ============ 检查认证 ============

    var overlay = document.getElementById('auth-overlay');

    if (overlay) {

        if (sessionStorage.getItem('auth_ok') === '1') {

            overlay.style.display = 'none';

        } else {

            overlay.style.display = 'flex';

        }

    }



    // ============ 消息功能 ============

    function addMessage(role, text, meta) {

        meta = meta || '';

        if (!msgs) return;

        var d = document.createElement('div');

        d.className = 'message ' + role;

        d.innerHTML = text.split('
').join('<br>') + (meta ? '<div class="meta">' + meta + '</div>' : '');

        msgs.appendChild(d);

        msgs.scrollTop = msgs.scrollHeight;

    }



    function showTyping() {

        if (typingEl || !msgs) return;

        typingEl = document.createElement('div');

        typingEl.className = 'message assistant';

        typingEl.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';

        msgs.appendChild(typingEl);

        msgs.scrollTop = msgs.scrollHeight;

    }



    function hideTyping() {

        if (typingEl) { typingEl.remove(); typingEl = null; }

    }



    function handleKey(e) {

        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }

    }



    function autoResize(el) {

        el.style.height = 'auto';

        el.style.height = Math.min(el.scrollHeight, 120) + 'px';

    }



    function handleFileSelect(event) {

        var file = event.target.files[0];

        if (!file) return;

        if (file.size > 10 * 1024 * 1024) { alert('文件太大'); event.target.value = ''; return; }

        currentFile = file;

        var fn = document.getElementById('file-name');

        var fp = document.getElementById('file-preview');

        if (fn) fn.textContent = file.name + ' (' + (file.size/1024).toFixed(1) + ' KB)';

        if (fp) fp.style.display = 'flex';

        event.target.value = '';

    }

    window.handleFileSelect = handleFileSelect;



    function clearFile() {

        currentFile = null;

        var fp = document.getElementById('file-preview');

        var fi = document.getElementById('file-input');

        if (fp) fp.style.display = 'none';

        if (fi) fi.value = '';

    }

    window.clearFile = clearFile;



    async function uploadFile(file) {

        var fd = new FormData();

        fd.append('file', file);

        var r = await fetch('/api/upload', { method: 'POST', body: fd });

        return await r.json();

    }



    async function sendMessage() {

        if (!input || !sendBtn) return;

        var text = input.value.trim();

        if (!text && !currentFile) return;

        if (text) addMessage('user', text);

        input.value = '';

        input.style.height = '48px';

        sendBtn.disabled = true;

        showTyping();

        try {

            if (currentFile) {

                addMessage('system', '📤 上传文件: ' + currentFile.name);

                var ur = await uploadFile(currentFile);

                clearFile();

                if (ur.error) { hideTyping(); addMessage('system', '❌ ' + ur.error); return; }

                var msg = text || '请处理这个文件';

                msg += '
[上传文件: ' + ur.path + ']';

                var r = await fetch('/api/chat', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: msg}) });

                var d = await r.json(); hideTyping();

                addMessage('assistant', d.response || '无响应', new Date().toLocaleTimeString());

            } else {

                var r = await fetch('/api/chat', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: text}) });

                var d = await r.json(); hideTyping();

                addMessage('assistant', d.response || '无响应', new Date().toLocaleTimeString());

            }

        } catch(e) { hideTyping(); addMessage('system', '错误: ' + e.message); }

        sendBtn.disabled = false; input.focus();

    }

    window.sendMessage = sendMessage;



    // ============ 工具 ============


        } catch(e) {
            hideTyping();
            addMessage('system', "搜索失败: " + e.message);
        }
    }

    async function runTool(tool) {

        var tools = { status: '请检查系统状态', skills: '列出可用 skills', memory: '搜索记忆', search: '请输入搜索关键词', clear: '__CLEAR__' };

        if (tool === 'clear') { if (msgs) msgs.innerHTML = '<div class="message system">已清除</div>'; return; }

        addMessage('user', '[工具] ' + tool); showTyping();

        try {

            var r = await fetch('/api/chat', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: tools[tool]}) });

            var d = await r.json(); hideTyping(); addMessage('assistant', d.response || '无响应');

        } catch(e) { hideTyping(); addMessage('system', '错误: ' + e.message); }

    }

    window.runTool = runTool;



    // ============ Tab 切换 ============

    function switchTab(tab) {

        document.querySelectorAll('.nav-item').forEach(function(el) { el.classList.remove('active'); });

        event.target.closest('.nav-item').classList.add('active');

        var tp = document.getElementById('toolsPanel'); if (tp) tp.classList.remove('show');

        var tc = document.getElementById('tab-chat'); if (tc) tc.style.display = 'none';

        var tw = document.getElementById('tab-weixin'); if (tw) tw.style.display = 'none';

        var tf = document.getElementById('tab-files'); if (tf) tf.style.display = 'none';

        var ts = document.getElementById('tab-settings'); if (ts) ts.style.display = 'none';

        if (tab === 'chat' && tc) tc.style.display = 'flex';

        else if (tab === 'weixin' && tw) { tw.style.display = 'flex'; }

        else if (tab === 'files' && tf) { tf.style.display = 'flex'; refreshFiles(); }

        else if (tab === 'tools' && tp) { tp.classList.add('show'); if (tc) tc.style.display = 'flex'; }

        else if (tab === 'settings' && ts) { ts.style.display = 'flex'; }

        else { if (tc) tc.style.display = 'flex'; }

    }

    window.switchTab = switchTab;



    // ============ 微信二维码 ============

    async function generateQR() {

        var btn = document.getElementById('qr-btn');

        var wrap = document.getElementById('qr-image-wrap');

        var status = document.getElementById('qr-status');

        var connected = document.getElementById('weixin-connected');

        if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }

        if (connected) connected.style.display = 'none';

        try {

            var r = await fetch('/api/qr/generate', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' });

            var d = await r.json();

            if (d.qrcode_url && wrap) {

                var qrUrl = 'https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=' + encodeURIComponent(d.qrcode_url);

                wrap.innerHTML = '<img src="' + qrUrl + '" style="width:240px;height:240px;border-radius:12px">';

                if (status) { status.textContent = '⏳ 等待扫码...'; status.style.color = '#fbbf24'; }

                pollQRStatus();

            } else if (status) {

                status.textContent = '❌ ' + (d.error || '生成失败'); status.style.color = '#f87171';

            }

        } catch(e) { if (status) { status.textContent = '❌ ' + e.message; status.style.color = '#f87171'; } }

        if (btn) { btn.disabled = false; btn.textContent = '重新生成'; }

    }

    window.generateQR = generateQR;



    function pollQRStatus() {

        var interval = setInterval(async function() {

            try {

                var r = await fetch('/api/qr/status');

                var d = await r.json();

                var status = document.getElementById('qr-status');

                var wrap = document.getElementById('qr-image-wrap');

                var connected = document.getElementById('weixin-connected');

                var btn = document.getElementById('qr-btn');

                if (d.status === 'confirmed') {

                    if (status) { status.textContent = '✅ 授权成功！'; status.style.color = '#4ade80'; }

                    if (wrap) wrap.style.display = 'none';

                    if (btn) btn.style.display = 'none';

                    if (connected) connected.style.display = 'flex';

                    clearInterval(interval);

                } else if (d.status === 'scaned') {

                    if (status) { status.textContent = '📱 已扫码...'; status.style.color = '#60a5fa'; }

                } else if (d.status === 'expired') {

                    if (status) { status.textContent = '⌛ 已过期'; status.style.color = '#f87171'; }

                    clearInterval(interval);

                }

            } catch(e) {}

        }, 2000);

    }

    window.pollQRStatus = pollQRStatus;



    // ============ 文件管理 ============

    function formatSize(bytes) {

        if (bytes < 1024) return bytes + ' B';

        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';

        return (bytes / 1024 / 1024).toFixed(1) + ' MB';

    }

    function formatTime(ts) { var d = new Date(ts * 1000); return d.toLocaleDateString() + ' ' + d.toLocaleTimeString(); }

    function getFileIcon(name) {

        var ext = name.split('.').pop().toLowerCase();

        var icons = { 'png':'🖼️','jpg':'🖼️','jpeg':'🖼️','gif':'🖼️','webp':'🖼️','svg':'🖼️','pdf':'📄','doc':'📝','docx':'📝','txt':'📃','md':'📃','py':'🐍','js':'📜','json':'📋','yaml':'📋','yml':'📋','zip':'📦','tar':'📦','gz':'📦' };

        return icons[ext] || '📄';

    }



    async function refreshFiles() {

        try {

            var r = await fetch('/api/files?path=' + encodeURIComponent(currentFilePath));

            var d = await r.json();

            if (d.error) { var fl = document.getElementById('file-list'); if (fl) fl.innerHTML = '<div style="color:#f87171;padding:20px">' + d.error + '</div>'; return; }

            renderFileList(d.files || []);

            renderBreadcrumb(d.path || currentFilePath);

            var fc = document.getElementById('file-count');

            if (fc) fc.textContent = (d.files || []).length + ' 个项目';

        } catch(e) { var fl = document.getElementById('file-list'); if (fl) fl.innerHTML = '<div style="color:#f87171;padding:20px">加载失败</div>'; }

    }

    window.refreshFiles = refreshFiles;



    function renderFileList(files) {

        var list = document.getElementById('file-list');

        if (!list) return;

        if (files.length === 0) { list.innerHTML = '<div style="color:#555;text-align:center;padding:40px">📂 空文件夹</div>'; return; }

        var html = '';

        var dirs = files.filter(function(f) { return f.is_dir; });

        var filesOnly = files.filter(function(f) { return !f.is_dir; });

        dirs.concat(filesOnly).forEach(function(f) {

            var icon = f.is_dir ? '📁' : getFileIcon(f.name);

            var fp = f.path.replace(/'/g, "\\'");

            var clickFn = f.is_dir ? "navigateToPath('" + fp + "')" : "previewFile('" + fp + "')";

            html += '<div class="file-item" onclick="selectFile(this,\'' + fp + '\',' + f.is_dir + ')" ondblclick="' + clickFn + '">';

            html += '<span class="file-icon">' + icon + '</span>';

            html += '<div class="file-info"><div class="file-name">' + f.name + '</div>';

            html += '<div class="file-meta">' + (f.is_dir ? f.item_count + ' 个项目' : formatSize(f.size)) + ' · ' + formatTime(f.mtime) + '</div></div>';

            html += '<div class="file-actions">';

            if (!f.is_dir) html += '<button class="file-action-btn" onclick="event.stopPropagation();downloadFile(\'' + fp + '\')" title="下载">⬇️</button>';

            html += '<button class="file-action-btn" onclick="event.stopPropagation();deleteFile(\'' + fp + '\',\'' + f.name.replace(/'/g, "\\'") + '\')" title="删除">🗑️</button>';

            html += '</div></div>';

        });

        list.innerHTML = html;

    }



    function renderBreadcrumb(path) {

        var bc = document.getElementById('file-breadcrumb');

        if (!bc) return;

        var parts = path.split('/').filter(function(p) { return p; });

        var html = '<span style="color:#60a5fa;cursor:pointer" onclick="navigateToPath(\'/opt/data\')">📂 /opt/data</span>';

        var accum = '';

        parts.forEach(function(p, i) {

            accum += '/' + p;

            html += '<span style="color:#555"> / </span>';

            if (i < parts.length - 1) {

                html += '<span style="color:#60a5fa;cursor:pointer" onclick="navigateToPath(\'' + accum + '\')">' + p + '</span>';

            } else {

                html += '<span style="color:#e0e0e0">' + p + '</span>';

            }

        });

        bc.innerHTML = html;

    }



    function navigateToPath(path) { currentFilePath = path; refreshFiles(); }

    window.navigateToPath = navigateToPath;



    function selectFile(el, path, isDir) {

        document.querySelectorAll('.file-item').forEach(function(e) { e.classList.remove('selected'); });

        el.classList.add('selected');

    }

    window.selectFile = selectFile;



    async function previewFile(path) {

        var panel = document.getElementById('file-preview-panel');

        var content = document.getElementById('preview-content');

        var name = document.getElementById('preview-name');

        var actions = document.getElementById('preview-actions');

        if (panel) panel.style.display = 'flex';

        if (name) name.textContent = path.split('/').pop();

        if (content) content.innerHTML = '<div style="color:#888;text-align:center;padding:40px">加载中...</div>';

        try {

            var r = await fetch('/api/file/read?path=' + encodeURIComponent(path));

            var d = await r.json();

            if (d.error) { if (content) content.innerHTML = '<div style="color:#f87171">' + d.error + '</div>'; return; }

            if (d.type === 'image' && content) content.innerHTML = '<img src="' + d.url + '" style="max-width:100%;border-radius:8px">';

            else if (d.type === 'text' && content) content.innerHTML = '<pre style="font-size:12px;color:#e0e0e0;white-space:pre-wrap;word-break:break-all;font-family:monospace">' + (d.content || '').replace(/</g,'&lt;') + '</pre>';

            else if (content) content.innerHTML = '<div style="color:#888;text-align:center;padding:40px">无法预览</div>';

            if (actions) {

                actions.innerHTML = '<button class="btn" onclick="downloadFile(\'' + path + '\')" style="padding:8px 16px;font-size:13px">⬇️ 下载</button>';

                actions.innerHTML += '<button class="btn btn-secondary" onclick="deleteFile(\'' + path + '\',\'' + path.split('/').pop().replace(/'/g, "\\'") + '\')" style="padding:8px 16px;font-size:13px">🗑️ 删除</button>';

            }

        } catch(e) { if (content) content.innerHTML = '<div style="color:#f87171">加载失败</div>'; }

    }

    window.previewFile = previewFile;



    function closePreview() { var p = document.getElementById('file-preview-panel'); if (p) p.style.display = 'none'; }

    window.closePreview = closePreview;



    async function downloadFile(path) { window.open('/api/file/download?path=' + encodeURIComponent(path), '_blank'); }

    window.downloadFile = downloadFile;



    async function deleteFile(path, name) {

        if (!confirm('确定删除 "' + name + '"？')) return;

        try {

            var r = await fetch('/api/file/delete', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: path}) });

            var d = await r.json();

            if (d.ok) { refreshFiles(); closePreview(); } else alert('删除失败');

        } catch(e) { alert('删除失败: ' + e.message); }

    }

    window.deleteFile = deleteFile;



    async function uploadFileToServer(event) {

        var file = event.target.files[0];

        if (!file) return;

        if (file.size > 50 * 1024 * 1024) { alert('文件太大'); event.target.value = ''; return; }

        var fd = new FormData();

        fd.append('file', file);

        fd.append('path', currentFilePath);

        try {

            var r = await fetch('/api/file/upload', { method: 'POST', body: fd });

            var d = await r.json();

            if (d.ok) refreshFiles(); else alert('上传失败');

        } catch(e) { alert('上传失败: ' + e.message); }

        event.target.value = '';

    }

    window.uploadFileToServer = uploadFileToServer;



    function showNewFolderDialog() {

        var name = prompt('请输入文件夹名称：');

        if (!name || !name.trim()) return;

        createFolder(name.trim());

    }

    window.showNewFolderDialog = showNewFolderDialog;



    async function createFolder(name) {

        try {

            var r = await fetch('/api/file/mkdir', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: currentFilePath, name: name}) });

            var d = await r.json();

            if (d.ok) refreshFiles(); else alert('创建失败');

        } catch(e) { alert('创建失败: ' + e.message); }

    }

    window.createFolder = createFolder;
    
    // ============ 密码设置 ============
    async function changePwd() {
        var curPwd = document.getElementById("cur-pwd") ? document.getElementById("cur-pwd").value : "";
        var newPwd = document.getElementById("new-pwd").value;
        var confirmPwd = document.getElementById("confirm-pwd").value;
        var msgEl = document.getElementById("pwd-msg");
        msgEl.style.display = "none";
        if (!newPwd || !confirmPwd) {
            msgEl.style.color = "#f87171";
            msgEl.textContent = "⚠️ 请输入新密码";
            msgEl.style.display = "block";
            return;
        }
        if (newPwd.length < 4) {
            msgEl.style.color = "#f87171";
            msgEl.textContent = "⚠️ 密码至少4位";
            msgEl.style.display = "block";
            return;
        }
        if (newPwd !== confirmPwd) {
            msgEl.style.color = "#f87171";
            msgEl.textContent = "⚠️ 两次输入不一致";
            msgEl.style.display = "block";
            return;
        }
        try {
            var r = await fetch("/api/pwd/change", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({cur_pwd: curPwd, new_pwd: newPwd})
            });
            var d = await r.json();
            if (d.ok) {
                msgEl.style.color = "#4ade80";
                msgEl.textContent = "✅ 密码修改成功";
                msgEl.style.display = "block";
                document.getElementById("new-pwd").value = "";
                document.getElementById("confirm-pwd").value = "";
                if (document.getElementById("cur-pwd")) document.getElementById("cur-pwd").value = "";
            } else {
                msgEl.style.color = "#f87171";
                msgEl.textContent = "❌ " + (d.error || "修改失败");
                msgEl.style.display = "block";
            }
        } catch(e) {
            msgEl.style.color = "#f87171";
            msgEl.textContent = "❌ " + e.message;
            msgEl.style.display = "block";
        }
    }
    window.changePwd = changePwd;




    // ============ 状态检查 ============

    async function checkStatus() {

        try {

            var r = await fetch('/api/status');

            var d = await r.json();

            var wxText = d.has_token ? '已连接' : '未授权';

            if (statusEl) { statusEl.textContent = '● ' + (d.stage || '运行中') + ' | 微信: ' + wxText; statusEl.className = 'status ok'; }

        } catch(e) { if (statusEl) { statusEl.textContent = '● 离线'; statusEl.className = 'status err'; } }

    }

    window.checkStatus = checkStatus;



    checkStatus();

    setInterval(checkStatus, 15000);

});

