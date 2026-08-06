const http = require('http');
const https = require('https');

const PORT = process.env.PORT || 7860;
const TOKEN = process.env.TELEGRAM_TOKEN || process.env.TG_TOKEN || '';

console.log('=== SERVER START ===');
console.log('PORT:', PORT);
console.log('TOKEN:', TOKEN ? TOKEN.substring(0, 10) + '...' : 'NOT SET');

let messageCount = 0;
let lastUpdateId = 0;
const startTime = new Date().toISOString();

// 发送 Telegram 消息
function sendMessage(chatId, text) {
  return new Promise((resolve) => {
    const url = `https://api.telegram.org/bot${TOKEN}/sendMessage?chat_id=${chatId}&text=${encodeURIComponent(text)}`;
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        console.log('Send result:', data.substring(0, 100));
        resolve(data);
      });
    }).on('error', (e) => {
      console.log('Send error:', e.message);
      resolve(null);
    });
  });
}

// 轮询消息
async function pollMessages() {
  if (!TOKEN) return;
  
  try {
    const url = `https://api.telegram.org/bot${TOKEN}/getUpdates?offset=${lastUpdateId + 1}&timeout=10`;
    
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', async () => {
        try {
          const result = JSON.parse(data);
          
          if (result.ok && result.result && result.result.length > 0) {
            for (const update of result.result) {
              lastUpdateId = update.update_id;
              const msg = update.message;
              
              if (msg && msg.text) {
                messageCount++;
                console.log(`Message #${messageCount}: ${msg.text}`);
                
                const reply = `✅ 收到: "${msg.text}"\n消息数: ${messageCount}`;
                await sendMessage(msg.chat.id, reply);
              }
            }
          }
        } catch (e) {
          console.log('Parse error:', e.message);
        }
      });
    }).on('error', (e) => {
      console.log('Poll error:', e.message);
    });
  } catch (e) {
    console.log('Poll exception:', e.message);
  }
}

// HTTP 服务器
const server = http.createServer((req, res) => {
  console.log(`${req.method} ${req.url}`);
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(`<h1>Bot Running</h1><p>Messages: ${messageCount}</p><p>Started: ${startTime}</p>`);
});

server.listen(PORT, '0.0.0.0', async () => {
  console.log('Server listening on', PORT);
  
  // 删除 Webhook
  if (TOKEN) {
    console.log('Deleting webhook...');
    https.get(`https://api.telegram.org/bot${TOKEN}/deleteWebhook`, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        console.log('Webhook deleted:', data.substring(0, 100));
        
        // 开始轮询
        console.log('Starting polling...');
        setInterval(pollMessages, 3000);
        pollMessages();
      });
    }).on('error', (e) => {
      console.log('Delete webhook error:', e.message);
      // 即使删除失败也尝试轮询
      console.log('Starting polling anyway...');
      setInterval(pollMessages, 3000);
      pollMessages();
    });
  }
});

// 防止崩溃
process.on('uncaughtException', (err) => {
  console.log('Uncaught error:', err.message);
});

process.on('unhandledRejection', (reason) => {
  console.log('Unhandled rejection:', reason);
});