#!/usr/bin/env python3
"""Hermes Agent - Full Web UI for HuggingFace Space with WeChat integration."""

import os, sys, json, time, ssl, threading, subprocess, base64, struct, secrets
import hmac
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import urllib.request, urllib.error, urllib.parse
import urllib.parse as up
import shutil
import hashlib

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
os.makedirs(HERMES_HOME, exist_ok=True)
PORT = int(os.environ.get("PORT", 7860))
PASSWORD = os.environ.get("SITE_PASSWORD", "")
HINDSIGHT_API_KEY = os.environ.get("HINDSIGHT_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
AGNES_API_KEY=os.environ.get("AGNES_API_KEY", "")
ILINK_TOKEN = os.environ.get("ILINK_TOKEN", "")
ILINK_BASE = os.environ.get("ILINK_BASE", "https://ilinkai.weixin.qq.com")
OPENROUTER_URL = os.environ.get("OPENROUTER_API_URL", "https://api.publicai.co/v1/chat/completions")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "apertus-ai/publicai")
ilink_token = ILINK_TOKEN

# ── Session Storage ───────────────────────────────────────────────────────
processed_ids = set()

# ── Agent Core ────────────────────────────────────────────────────────────
def _call_llm(messages, max_tokens=4096, temperature=0.7):
    api_key = AGNES_API_KEY or PUBLICAI_API_KEY
    api_url = "https://api.publicai.co/v1/chat/completions"
    payload = {"model": "apertus-ai/publicai", "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(api_url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Error: LLM call failed - {e}]"

def _call_llm_with_context(text):
    messages = [{"role": "user", "content": f"You are Hermes Agent. User: {text}\nAssistant: "}]
    return _call_llm(messages)

def _call_ilink_api(method, path, params=None, body=None):
    base = ILINK_BASE or "https://ilinkai.weixin.qq.com"
    url = f"{base}/{path.lstrip('/')}"
    try:
        headers = {"AuthorizationType": "ilink_bot_token"}
        if ILINK_TOKEN:
            headers["Authorization"] = f"Bearer {ILINK_TOKEN}"
        data = json.dumps(body).encode() if body else None
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        if method == "POST":
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"err_code": 1, "err_msg": str(e)}

# ── ILink Bot State ──────────────────────────────────────────────────────
qr_state = {"status": "none", "status_text": "等待生成二维码", "qrcode": None, "session_key": None,
            "openid": None, "session_token": None, "user_token": None}
qr_lock = threading.Lock()

def _generate_qr():
    with qr_lock:
        if qr_state["status"] not in ("none", "expired"):
            return
        result = _call_ilink_api("GET", "ilink/bot/get_bot_qrcode?bot_type=3")
        if "qrcode" in result:
            qr_state["qrcode"] = result["qrcode"]
            qr_state["status"] = "wait"
            qr_state["status_text"] = "等待扫码..."
        else:
            qr_state["status"] = "expired"
            qr_state["status_text"] = "生成二维码失败"

def _poll_qr_status():
    with qr_lock:
        if qr_state["status"] not in ("wait", "scaned"):
            return
        result = _call_ilink_api("GET", f"ilink/bot/check_qrcode_status?qrcode={qr_state['qrcode']}")
        code = result.get("ret", 1)
        if code == 0:
            qr_state["status"] = "scaned"
            qr_state["status_text"] = "已扫码，请在微信确认..."
            session_key = result.get("session_key", "")
            openid = result.get("openid", "")
            if session_key and openid:
                qr_state["session_key"] = session_key
                qr_state["openid"] = openid
                qr_state["user_token"] = result.get("token", "")
                qr_state["status"] = "confirmed"
                qr_state["status_text"] = "授权成功！"
            else:
                qr_state["status"] = "wait"
                qr_state["status_text"] = "等待扫码..."
        else:
            msg = result.get("msg", "")
            if "过期" in msg or "expired" in msg.lower():
                qr_state["status"] = "expired"
                qr_state["status_text"] = "二维码已过期"

# ── HTML Templates ─────────────────────────────────────────────────────────
def get_login_html():
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Hermes Agent - 登录</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f0f23;color:#e0e0e0;height:100vh;display:flex;align-items:center;justify-content:center}
.login-box{background:#16162a;border:1px solid #333;border-radius:16px;padding:40px;width:340px;text-align:center}
.login-box h1{font-size:20px;margin-bottom:24px;background:linear-gradient(90deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.login-box input{width:100%;padding:12px 16px;border-radius:10px;border:1px solid #333;background:#0f0f23;color:#e0e0e0;font-size:14px;outline:none}
.login-box input:focus{border-color:#60a5fa}
.login-box button{width:100%;padding:12px;margin-top:12px;border-radius:10px;border:none;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;font-size:14px;cursor:pointer}
.login-box button:hover{opacity:.9}
#err{color:#f87171;font-size:12px;margin-top:12px;min-height:16px}
</style>
</head>
<body>
<div class="login-box">
<h1>Hermes Agent 登录</h1>
<input type="password" id="pw" placeholder="密码" onkeydown="if(event.key==='Enter')doLogin()">
<button onclick="doLogin()">登录</button>
<div id="err"></div>
</div>
<script>
async function doLogin(){
  const pw=document.getElementById('pw').value;
  const err=document.getElementById('err');
  err.textContent='';
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(pw));
  const hashArray = Array.from(new Uint8Array(hash));
  const token = hashArray.map(b => b.toString(16).padStart(2,'0')).join('');
  document.cookie = 'auth=' + token + '; path=/; SameSite=Lax';
  location.href = '/chat';
}
</script>
</body>
</html>"""

def get_html():
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Hermes Agent</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f0f23;color:#e0e0e0;height:100vh;display:flex;flex-direction:column}
.header{background:linear-gradient(135deg,#1a1a3e,#2d1b69);padding:12px 20px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #333}
.header h1{font-size:18px;background:linear-gradient(90deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.header .status{font-size:12px;color:#666;margin-left:auto}
.header .status.ok{color:#4ade80}
.header .status.err{color:#f87171}
.header .btn-secondary{background:#1e1e3f;border:1px solid #333;color:#ccc;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:12px;margin-left:8px}
.header .btn-secondary:hover{background:#2a2a4f;color:#fff}
.main{display:flex;flex:1;overflow:hidden}
.sidebar{width:220px;background:#16162a;border-right:1px solid #333;display:flex;flex-direction:column}
.sidebar .nav{padding:8px}
.sidebar .nav-item{padding:10px 12px;border-radius:8px;cursor:pointer;font-size:13px;color:#999;transition:all .2s;display:flex;align-items:center;gap:8px}
.sidebar .nav-item:hover{background:#1e1e3f;color:#fff}
.sidebar .nav-item.active{background:#1e1e3f;color:#60a5fa}
.sidebar .nav-item .icon{font-size:16px}
.sidebar .footer{margin-top:auto;padding:12px;border-top:1px solid #333;font-size:11px;color:#555}
.chat-area{flex:1;display:flex;flex-direction:column}
.messages{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:12px}
.message{max-width:80%;padding:12px 16px;border-radius:12px;font-size:14px;line-height:1.6;word-break:break-all}
.message.user{background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;align-self:flex-end;border-bottom-right-radius:4px}
.message.assistant{background:#1e1e3f;color:#e0e0e0;align-self:flex-start;border-bottom-left-radius:4px;border:1px solid #333}
.message.system{background:#1a1a2e;color:#888;font-size:12px;text-align:center;align-self:center}
.message .meta{font-size:10px;color:#666;margin-top:4px}
.message.assistant .meta{color:#555}
.input-area{padding:16px 20px;border-top:1px solid #333}
.input-row{display:flex;gap:8px}
textarea{flex:1;background:#1a1a2e;border:1px solid #333;border-radius:10px;padding:12px;color:#e0e0e0;font-size:14px;resize:none;outline:none;font-family:inherit;min-height:44px;max-height:200px}
textarea:focus{border-color:#60a5fa}
textarea::placeholder{color:#555}
.btn{background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:10px;padding:0 20px;cursor:pointer;font-size:14px}
.btn:hover{opacity:.9}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-secondary{background:#1e1e3f;border:1px solid #333;color:#ccc;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:12px}
.btn-secondary:hover{background:#2a2a4f;color:#fff}
.tools-panel{display:none;position:absolute;right:20px;top:60px;background:#16162a;border:1px solid #333;border-radius:12px;padding:16px;width:280px;z-index:100}
.tools-panel.show{display:block}
.tools-panel h3{font-size:14px;color:#60a5fa;margin-bottom:12px}
.tool-item{padding:8px 10px;border-radius:6px;font-size:12px;color:#ccc;cursor:pointer;margin-bottom:4px;transition:all .2s}
.tool-item:hover{background:#1e1e3f;color:#fff}
.typing{display:flex;gap:4px;padding:4px 0}
.typing span{width:6px;height:6px;background:#60a5fa;border-radius:50%;animation:typing 1.4s infinite both}
.typing span:nth-child(2){animation-delay:.2s}
.typing span:nth-child(3){animation-delay:.4s}
@keyframes typing{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-8px)}}
/* 会话面板 */
.session-panel{display:none;position:fixed;left:0;top:0;bottom:0;width:320px;background:#12122a;border-right:1px solid #333;z-index:200;flex-direction:column}
.session-panel.show{display:flex}
.session-panel-header{padding:16px;border-bottom:1px solid #333;display:flex;align-items:center;justify-content:space-between}
.session-panel-header h2{font-size:16px;color:#60a5fa}
.session-panel-header .close-btn{background:none;border:none;color:#999;font-size:20px;cursor:pointer;padding:4px 8px}
.session-panel-header .close-btn:hover{color:#fff}
.session-list{flex:1;overflow-y:auto;padding:8px}
.session-item{padding:12px;border-radius:8px;cursor:pointer;margin-bottom:4px;border:1px solid transparent;transition:all .2s}
.session-item:hover{background:#1e1e3f;border-color:#333}
.session-item.active{background:#1e1e3f;border-color:#60a5fa}
.session-item .session-name{font-size:13px;color:#e0e0e0;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.session-item .session-meta{font-size:11px;color:#666}
.session-item .session-preview{font-size:11px;color:#555;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.session-panel-footer{padding:12px;border-top:1px solid #333}
.session-panel-footer .new-session-btn{width:100%;padding:10px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:13px}
.session-panel-footer .new-session-btn:hover{opacity:.9}
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:150}
.overlay.show{display:block}
@media(max-width:768px){.sidebar{display:none}}
</style>
</head>
<body>
<div class="header">
<h1>Hermes Agent</h1>
<span class="status" id="status">● 检查中...</span>
<button class="btn-secondary" id="sessionsBtn" onclick="toggleSessionPanel()">会话</button>
<button class="btn-secondary" onclick="toggleTools()">工具</button>
</div>
<div class="overlay" id="overlay" onclick="toggleSessionPanel()"></div>
<div class="session-panel" id="sessionPanel">
<div class="session-panel-header">
<h2>会话记录</h2>
<button class="close-btn" onclick="toggleSessionPanel()">×</button>
</div>
<div class="session-list" id="sessionList"></div>
<div class="session-panel-footer">
<button class="new-session-btn" onclick="createNewSession()">+ 新建会话</button>
</div>
</div>
<div class="main">
<div class="sidebar">
<div class="nav">
<div class="nav-item active"><span class="icon">💬</span>对话</div>
</div>
<div class="footer">Powered by Hermes</div>
</div>
<div class="chat-area">
<div class="messages" id="messages">
<div class="message system" style="margin-top:40px"><div class="typing"><span></span><span></span><span></span></div></div>
</div>
<div class="input-area">
<div class="input-row">
<textarea id="input" placeholder="输入消息..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage();}" oninput="this.style.height='auto';this.style.height=Math.min(this.scrollHeight,200)+'px'"></textarea>
<button class="btn" id="sendBtn" onclick="sendMessage()">发送</button>
</div>
</div>
</div>
</div>
<div class="tools-panel" id="toolsPanel">
<h3>工具面板</h3>
<div class="tool-item" onclick="runTool('status')">📊 系统状态</div>
<div class="tool-item" onclick="runTool('clear')">🗑️ 清空</div>
</div>
<script>
const msgs=document.getElementById('messages'),input=document.getElementById('input'),sendBtn=document.getElementById('sendBtn'),statusEl=document.getElementById('status');
let currentSessionId=null;

// ===== 会话管理 =====
function getSessions(){try{return JSON.parse(localStorage.getItem('hermes_sessions')||'[]');}catch(e){return[]}}
function saveSessions(s){localStorage.setItem('hermes_sessions',JSON.stringify(s))}
function getCurrentSession(){const s=getSessions();return s.find(x=>x.id===currentSessionId)||null}

function renderSessionList(){
  const list=document.getElementById('sessionList');
  const sessions=getSessions();
  if(!sessions.length){list.innerHTML='<div style="padding:20px;color:#555;font-size:13px;text-align:center">暂无会话记录</div>';return}
  list.innerHTML=sessions.map(s=>'<div class="session-item'+(s.id===currentSessionId?' active':'')+'" onclick="switchSession(\''+s.id+'\')">'+'<div class="session-name">'+(s.name||'未命名会话')+'</div>'+'<div class="session-meta">'+s.msgCount+' 条消息 · '+new Date(s.updatedAt).toLocaleDateString()+'</div>'+(s.preview?'<div class="session-preview">'+s.preview+'</div>':'')+'</div>').join('');
}

function toggleSessionPanel(){
  const panel=document.getElementById('sessionPanel');
  const overlay=document.getElementById('overlay');
  panel.classList.toggle('show');
  overlay.classList.toggle('show');
  if(panel.classList.contains('show'))renderSessionList();
}

function createNewSession(){
  const id='s_'+Date.now();
  const s={id:id,name:'会话 '+(getSessions().length+1),messages:[],msgCount:0,preview:'',updatedAt:Date.now()};
  const sessions=getSessions();
  sessions.unshift(s);
  saveSessions(sessions);
  switchSession(id);
  toggleSessionPanel();
}

function switchSession(id){
  currentSessionId=id;
  const s=getSessions().find(x=>x.id===id);
  if(!s)return;
  // 恢复消息
  msgs.innerHTML='';
  if(!s.messages||!s.messages.length){
    msgs.innerHTML='<div class="message system" style="margin-top:40px"><div class="typing"><span></span><span></span><span></span></div></div>';
  } else {
    s.messages.forEach(m=>{
      const d=document.createElement('div');
      d.className='message '+m.role;
      d.innerHTML=m.text.replace(/\n/g,'<br>');
      if(m.meta)d.innerHTML+='<div class="meta">'+m.meta+'</div>';
      msgs.appendChild(d);
    });
  }
  msgs.scrollTop=msgs.scrollHeight;
  renderSessionList();
}

function saveCurrentSession(role,text,meta){
  if(!currentSessionId)return;
  const sessions=getSessions();
  const idx=sessions.findIndex(x=>x.id===currentSessionId);
  if(idx<0)return;
  if(!sessions[idx].messages)sessions[idx].messages=[];
  sessions[idx].messages.push({role:role,text:text,meta:meta||'',time:Date.now()});
  sessions[idx].msgCount=sessions[idx].messages.length;
  sessions[idx].updatedAt=Date.now();
  if(role==='assistant')sessions[idx].preview=text.substring(0,50);
  // 限制单会话最多200条
  if(sessions[idx].messages.length>200)sessions[idx].messages=sessions[idx].messages.slice(-200);
  saveSessions(sessions);
}

// ===== 消息发送 =====
function addMessage(role,text,meta){
  const d=document.createElement('div');
  d.className='message '+role;
  d.innerHTML=text+(meta?'<div class="meta">'+meta+'</div>':'');
  msgs.appendChild(d);
  msgs.scrollTop=msgs.scrollHeight;
  saveCurrentSession(role,text,meta);
}

function showTyping(){
  const d=document.createElement('div');
  d.className='message system typing-msg';
  d.style.marginTop='40px';
  d.innerHTML='<div class="typing"><span></span><span></span><span></span></div>';
  msgs.appendChild(d);
  msgs.scrollTop=msgs.scrollHeight;
}

function hideTyping(){
  const t=msgs.querySelector('.typing-msg');
  if(t)t.remove();
}

async function sendMessage(){
  const text=input.value.trim();
  if(!text)return;
  input.value='';
  addMessage('user',text);
  sendBtn.disabled=true;
  showTyping();
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});
    const d=await r.json();
    hideTyping();
    if(d.response)addMessage('assistant',d.response.replace(/\n/g,'<br>'),d.time?new Date(d.time*1000).toLocaleTimeString():'');
    else if(d.error)addMessage('system','⚠️ '+d.error);
  }catch(e){
    hideTyping();
    addMessage('system','⚠️ 发送失败: '+e.message);
  }
  sendBtn.disabled=false;
  input.focus();
}

async function runTool(tool){
  if(tool==='status'){
    try{
      const r=await fetch('/api/status');
      const d=await r.json();
      addMessage('system','● '+(d.stage||'运行中')+' | 微信: '+(d.weixin||'未配置')+' | 已处理: '+(d.processed_messages||0)+' 条');
    }catch(e){addMessage('system','获取状态失败');}
  }else if(tool==='clear'){
    msgs.innerHTML='<div class="message system" style="margin-top:40px"><div class="typing"><span></span><span></span><span></span></div></div>';
    if(currentSessionId){
      const sessions=getSessions();
      const idx=sessions.findIndex(x=>x.id===currentSessionId);
      if(idx>=0){sessions[idx].messages=[];sessions[idx].msgCount=0;sessions[idx].preview='';saveSessions(sessions);}
    }
  }
}

function toggleTools(){document.getElementById('toolsPanel').classList.toggle('show');}

async function checkStatus(){
  try{
    const r=await fetch('/api/status');
    const d=await r.json();
    statusEl.textContent='● '+(d.stage||'运行中')+' | 微信: '+(d.weixin||'未配置');
    statusEl.className='status ok';
  }catch(e){
    statusEl.textContent='● 离线';
    statusEl.className='status err';
  }
}

// ===== 初始化 =====
(function(){
  // 恢复最近会话或创建新会话
  const sessions=getSessions();
  if(sessions.length>0){
    switchSession(sessions[0].id);
  }else{
    createNewSession();
  }
  checkStatus();
  setInterval(checkStatus,30000);
})();
</script>
</body>
</html>""""