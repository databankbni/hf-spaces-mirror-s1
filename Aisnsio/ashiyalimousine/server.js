const express = require('express');
const cookieParser = require('cookie-parser');
const path = require('path');
const db = require('./lib/db');

const app = express();
const PUBLIC_DIR = path.join(__dirname, 'public');
const PORT = process.env.PORT || 7860;

app.set('trust proxy', 1); // behind HF's proxy — needed for Secure cookies

// Security headers. Same-origin app: inline styles/scripts, Google Fonts, base64 images.
// Must render inside HF's cross-site iframe. Stripe uses a hosted-checkout redirect
// (top-level navigation), so no extra script/connect CSP entries are required.
app.use((req, res, next) => {
  res.setHeader(
    'Content-Security-Policy',
    "default-src 'self'; " +
      "script-src 'self' 'unsafe-inline'; " +
      "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; " +
      "font-src 'self' https://fonts.gstatic.com; " +
      "img-src 'self' data:; " +
      "connect-src 'self'; " +
      "form-action 'self' https://checkout.stripe.com; " +
      "frame-ancestors 'self' https://huggingface.co https://*.hf.space; " +
      "base-uri 'self'"
  );
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  next();
});

app.use(cookieParser());

// Stripe webhook needs the RAW body for signature verification — mount before json().
app.use('/api/payments/webhook', express.raw({ type: 'application/json' }));
app.use(express.json({ limit: '1mb' }));

app.get('/healthz', (req, res) => res.json({ status: 'ok' }));

// SEO: robots + dynamic sitemap (includes published blog/help posts).
const ORIGIN = 'https://aisnsio-ashiyalimousine.hf.space';
app.get('/robots.txt', (req, res) =>
  res.type('text/plain').send(`User-agent: *\nAllow: /\nSitemap: ${ORIGIN}/sitemap.xml\n`)
);
app.get('/sitemap.xml', (req, res) => {
  let posts = [];
  try { posts = db.q.all("SELECT slug FROM posts WHERE published = 1"); } catch (_) {}
  const urls = ['/', '/#fleet', '/#plans', '/#packages', '/#booking', '/#contact']
    .concat(posts.map((p) => '/?post=' + encodeURIComponent(p.slug)));
  const body =
    '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    urls.map((u) => `  <url><loc>${ORIGIN}${u}</loc></url>`).join('\n') +
    '\n</urlset>\n';
  res.type('application/xml').send(body);
});

// API
app.use('/api/auth', require('./routes/auth'));
app.use('/api/bookings', require('./routes/bookings'));
app.use('/api/admin', require('./routes/admin'));
app.use('/api/payments', require('./routes/payments'));
// Wave A — revenue & conversion
app.use('/api/pricing', require('./routes/pricing'));
app.use('/api/promos', require('./routes/promos'));
app.use('/api/gifts', require('./routes/gifts'));
app.use('/api/waitlist', require('./routes/waitlist'));
// Wave B — operations
app.use('/api/fleet', require('./routes/fleet'));
app.use('/api/inventory', require('./routes/inventory'));
app.use('/api/crm', require('./routes/crm'));
app.use('/api/incidents', require('./routes/incidents'));
app.use('/api/contracts', require('./routes/contracts'));
// Wave C — marketing & growth
app.use('/api/reviews', require('./routes/reviews'));
app.use('/api/referrals', require('./routes/referrals'));
app.use('/api/corporate', require('./routes/corporate'));
app.use('/api/newsletter', require('./routes/newsletter'));
app.use('/api/content', require('./routes/content'));
app.use('/api/analytics', require('./routes/analytics'));
// Wave D — trust & self-service
app.use('/api/selfservice', require('./routes/selfservice'));
app.use('/api/leads', require('./routes/leads'));
app.use('/api/accounting', require('./routes/accounting'));

// Unknown API routes → JSON 404 (never fall through to the SPA).
app.use('/api', (req, res) => res.status(404).json({ ok: false, error: 'not_found' }));

// Static assets + single-page fallback.
app.use(express.static(PUBLIC_DIR, { extensions: ['html'] }));
app.get('*', (req, res) => res.sendFile(path.join(PUBLIC_DIR, 'index.html')));

// Boot: open + seed the DB (with the /data snapshot lifecycle) before listening.
db.init();

const server = app.listen(PORT, () => {
  console.log(`Ashiya Limousine Service listening on :${PORT}`);
});

// Durable snapshot on shutdown (node is PID 1 so SIGTERM reaches us).
function shutdown() {
  try { db.snapshot(); } catch (_) {}
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3000).unref();
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
