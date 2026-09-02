const http = require('http');
const fs = require('fs');
const path = require('path');

process.on('uncaughtException', (err) => {
  console.error('Server Uncaught Exception (handled):', err.message);
});

process.on('unhandledRejection', (reason) => {
  console.error('Server Unhandled Rejection (handled):', reason);
});

const PORT = process.env.PORT || 3800;
const ROOT_DIR = path.resolve(__dirname);
const IFREIGHT_DATA = require('./js/data.js');

const MIME_TYPES = {
  '.html': 'text/html; charset=UTF-8',
  '.css': 'text/css; charset=UTF-8',
  '.js': 'text/javascript; charset=UTF-8',
  '.mjs': 'text/javascript; charset=UTF-8',
  '.json': 'application/json; charset=UTF-8',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.avif': 'image/avif',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.otf': 'font/otf',
  '.pdf': 'application/pdf'
};

function serveFile(req, res, filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext] || 'application/octet-stream';

  fs.stat(filePath, (statErr, stats) => {
    if (statErr) {
      if (!res.headersSent) {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=UTF-8' });
      }
      res.end('404 Not Found');
      return;
    }

    const fileSize = stats.size;
    const range = req ? req.headers.range : null;
    const isVideo = ['.mp4', '.webm', '.mov', '.m4v'].includes(ext);

    if (range && isVideo) {
      const parts = range.replace(/bytes=/, '').split('-');
      const start = parseInt(parts[0], 10);
      const end = parts[1] ? parseInt(parts[1], 10) : fileSize - 1;

      if (start >= fileSize || end >= fileSize) {
        if (!res.headersSent) {
          res.writeHead(416, {
            'Content-Range': `bytes */${fileSize}`,
            'Access-Control-Allow-Origin': '*'
          });
        }
        res.end();
        return;
      }

      const chunkSize = (end - start) + 1;
      const fileStream = fs.createReadStream(filePath, { start, end });

      res.writeHead(206, {
        'Content-Range': `bytes ${start}-${end}/${fileSize}`,
        'Accept-Ranges': 'bytes',
        'Content-Length': chunkSize,
        'Content-Type': contentType,
        'Cache-Control': 'no-cache',
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'SAMEORIGIN',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Access-Control-Allow-Origin': '*'
      });

      fileStream.pipe(res);
    } else {
      res.writeHead(200, {
        'Content-Length': fileSize,
        'Content-Type': contentType,
        'Accept-Ranges': 'bytes',
        'Cache-Control': 'no-cache',
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'SAMEORIGIN',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Access-Control-Allow-Origin': '*'
      });

      const stream = fs.createReadStream(filePath);
      stream.pipe(res);
    }
  });
}

const server = http.createServer((req, res) => {
  try {
    const rawUrl = req.url || '/';
    const parsedUrl = new URL(rawUrl, `http://${req.headers.host || 'localhost:' + PORT}`);
    const decodedUrl = decodeURIComponent(parsedUrl.pathname);

    // API: Rates List
    if (decodedUrl === '/api/rates/list' && req.method === 'GET') {
      res.writeHead(200, {
        'Content-Type': 'application/json; charset=UTF-8',
        'Access-Control-Allow-Origin': '*'
      });
      res.end(JSON.stringify({
        success: true,
        rates: IFREIGHT_DATA.rates,
        ocean: IFREIGHT_DATA.oceanFreight,
        fxRate: 156.00
      }));
      return;
    }

    // API: Package Tracking Lookup
    if (decodedUrl === '/api/tracking/lookup' && req.method === 'GET') {
      const trackingNumber = (parsedUrl.searchParams.get('number') || '').toUpperCase();
      const mockRecord = IFREIGHT_DATA.mockTracking[trackingNumber] || {
        trackingNumber: trackingNumber || 'IFJ-SAMPLE-AIR',
        status: 'IN_TRANSIT',
        statusLabel: 'In Transit to Jamaica',
        type: 'Express Air Freight',
        weight: '2.5 lbs',
        shipper: 'Verified U.S. Merchant',
        destination: 'Kingston Hub',
        estimatedDelivery: 'In 2 Days',
        timeline: [
          { time: 'Today, 10:00 AM', title: 'Customs Manifest Processed', location: 'Miami Air Cargo Hub', completed: true },
          { time: 'Yesterday, 04:00 PM', title: 'Intake & Security Scanning Verified', location: 'Doral Warehouse, FL', completed: true },
          { time: 'Pending', title: 'Flight Arrival at Norman Manley KIN', location: 'Kingston, Jamaica', completed: false },
          { time: 'Pending', title: 'Ready for Pickup / Out for Delivery', location: 'Kingston Hub', completed: false }
        ]
      };

      res.writeHead(200, {
        'Content-Type': 'application/json; charset=UTF-8',
        'Access-Control-Allow-Origin': '*'
      });
      res.end(JSON.stringify({ success: true, tracking: mockRecord }));
      return;
    }

    // API: Rate Calculator Endpoint
    if (decodedUrl === '/api/rates/calculate' && req.method === 'POST') {
      let body = '';
      req.on('data', chunk => body += chunk);
      req.on('end', () => {
        try {
          const { weight = 1, length = 0, width = 0, height = 0, valueUSD = 50, type = 'air' } = JSON.parse(body || '{}');
          
          let dimWeight = 0;
          if (length > 0 && width > 0 && height > 0) {
            dimWeight = Math.round(((length * width * height) / 166) * 10) / 10;
          }
          const chargeableWeight = Math.max(parseFloat(weight), dimWeight);

          let baseUSD = 0;
          if (type === 'air') {
            if (chargeableWeight <= 1) baseUSD = 6.25;
            else if (chargeableWeight <= 2) baseUSD = 8.90;
            else if (chargeableWeight <= 5) baseUSD = 8.90 + ((chargeableWeight - 2) * 2.30);
            else if (chargeableWeight <= 10) baseUSD = 15.80 + ((chargeableWeight - 5) * 2.51);
            else baseUSD = 28.35 + ((chargeableWeight - 10) * 2.15);
          } else {
            baseUSD = 85.00; // ocean barrel default
          }

          let dutyUSD = 0;
          if (parseFloat(valueUSD) > 100) {
            dutyUSD = Math.round((parseFloat(valueUSD) + baseUSD) * 0.28 * 100) / 100;
          }

          const fxRate = 156.00;
          const totalUSD = baseUSD + dutyUSD;
          const totalJMD = Math.round(totalUSD * fxRate);

          res.writeHead(200, {
            'Content-Type': 'application/json; charset=UTF-8',
            'Access-Control-Allow-Origin': '*'
          });
          res.end(JSON.stringify({
            success: true,
            type,
            chargeableWeight,
            baseFreightUSD: Math.round(baseUSD * 100) / 100,
            baseFreightJMD: Math.round(baseUSD * fxRate),
            dutyUSD,
            dutyJMD: Math.round(dutyUSD * fxRate),
            totalUSD: Math.round(totalUSD * 100) / 100,
            totalJMD,
            dutyFree: parseFloat(valueUSD) <= 100
          }));
        } catch (e) {
          res.writeHead(400, { 'Content-Type': 'application/json; charset=UTF-8' });
          res.end(JSON.stringify({ success: false, error: 'Invalid calculation payload' }));
        }
      });
      return;
    }

    // Static File Serving
    let targetPath = path.normalize(decodedUrl);
    if (targetPath === '/' || targetPath === '\\') {
      targetPath = 'index.html';
    }

    let filePath = path.join(ROOT_DIR, targetPath);

    // Prevent directory traversal
    if (!path.resolve(filePath).startsWith(ROOT_DIR)) {
      res.writeHead(403, { 'Content-Type': 'text/plain; charset=UTF-8' });
      res.end('403 Forbidden');
      return;
    }

    fs.stat(filePath, (err, stats) => {
      if (!err && stats.isFile()) {
        serveFile(req, res, filePath);
        return;
      }

      if (!err && stats.isDirectory()) {
        const nestedIndex = path.join(filePath, 'index.html');
        fs.stat(nestedIndex, (nErr, nStats) => {
          if (!nErr && nStats.isFile()) {
            serveFile(req, res, nestedIndex);
          } else {
            res.writeHead(404, { 'Content-Type': 'text/plain; charset=UTF-8' });
            res.end('404 Not Found');
          }
        });
        return;
      }

      res.writeHead(404, { 'Content-Type': 'text/plain; charset=UTF-8' });
      res.end('404 Not Found: ' + rawUrl);
    });

  } catch (err) {
    res.writeHead(400, { 'Content-Type': 'text/plain; charset=UTF-8' });
    res.end('400 Bad Request');
  }
});

server.listen(PORT, () => {
  console.log(`\n======================================================`);
  console.log(`⚡ iFREIGHT JAMAICA LOCAL SERVER ACTIVE`);
  console.log(`🌐 Main Site:        http://localhost:${PORT}`);
  console.log(`📦 Rate Calculator:  http://localhost:${PORT}#calculator`);
  console.log(`🔍 Live Tracking:    http://localhost:${PORT}#tracking`);
  console.log(`📬 Free US Address:  http://localhost:${PORT}#address`);
  console.log(`======================================================\n`);
});
