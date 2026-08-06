// SQLite core. CRITICAL HF trap: the live DB must live on the container's LOCAL disk
// (real FS — WAL works). The HF persistent volume (DB_PATH, e.g. /data/app.db) is a
// bucket-FUSE mount where SQLite locks STALL forever, so we use it ONLY for durable
// plain-file snapshots: restore /data -> local on boot, and VACUUM INTO + copy local ->
// /data on seed / every 5 min / SIGTERM. No lock op ever touches the bucket.
const { DatabaseSync } = require('node:sqlite');
const fs = require('fs');
const path = require('path');
const os = require('os');
const bcrypt = require('bcryptjs');
const { enc } = require('./crypto');

const LOCAL_DIR = process.env.LOCAL_DB_DIR || path.join(os.tmpdir(), 'als-db');
const LOCAL_DB = path.join(LOCAL_DIR, 'app.db');
const SNAP_PATH = process.env.DB_PATH || ''; // durable snapshot target (bucket ok for plain files)

fs.mkdirSync(LOCAL_DIR, { recursive: true });

// Restore the durable snapshot onto local disk before opening (survives rebuild/sleep).
if (SNAP_PATH && fs.existsSync(SNAP_PATH)) {
  try {
    fs.copyFileSync(SNAP_PATH, LOCAL_DB);
    console.log('[db] restored snapshot from', SNAP_PATH);
  } catch (e) {
    console.warn('[db] snapshot restore failed:', e.message);
  }
}

const db = new DatabaseSync(LOCAL_DB);
db.exec('PRAGMA journal_mode = WAL');
db.exec('PRAGMA busy_timeout = 4000'); // contention throws instead of hanging
db.exec('PRAGMA foreign_keys = ON');

const q = {
  get: (sql, ...p) => db.prepare(sql).get(...p),
  all: (sql, ...p) => db.prepare(sql).all(...p),
  run: (sql, ...p) => db.prepare(sql).run(...p),
};

const nowISO = () => new Date().toISOString();

function genRef(date) {
  const md = (date || nowISO().slice(0, 10)).replace(/-/g, '').slice(4, 8); // MMDD
  for (let i = 0; i < 40; i++) {
    const n = String(Math.floor(100 + Math.random() * 900));
    const ref = `ALS-${md}-${n}`;
    if (!q.get('SELECT 1 FROM bookings WHERE ref = ?', ref)) return ref;
  }
  return `ALS-${md}-${Date.now().toString().slice(-3)}`;
}

// ---- schema ---------------------------------------------------------------
function initSchema() {
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL,
      pass_hash TEXT NOT NULL,
      name TEXT,
      phone_enc TEXT,
      role TEXT NOT NULL DEFAULT 'customer',
      token_version INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS bookings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ref TEXT UNIQUE NOT NULL,
      user_id INTEGER,
      name TEXT NOT NULL,
      phone_enc TEXT,
      mail_enc TEXT,
      plan TEXT NOT NULL,
      veh TEXT NOT NULL,
      date TEXT NOT NULL,
      time TEXT NOT NULL,
      pax INTEGER NOT NULL,
      addons TEXT NOT NULL DEFAULT '[]',
      pickup TEXT,
      flight TEXT,
      notes TEXT,
      total INTEGER NOT NULL,
      deposit INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'pending',
      pay_status TEXT NOT NULL DEFAULT 'unpaid',
      created_at TEXT NOT NULL,
      ts INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      booking_ref TEXT NOT NULL,
      amount INTEGER NOT NULL,
      currency TEXT NOT NULL DEFAULT 'jpy',
      provider TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'deposit',
      stripe_session TEXT,
      stripe_intent TEXT,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notifications (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      booking_ref TEXT,
      channel TEXT NOT NULL,
      to_addr TEXT,
      subject TEXT,
      body TEXT,
      status TEXT NOT NULL DEFAULT 'sent',
      provider TEXT,
      created_at TEXT NOT NULL
    );
    /* ---- Wave A: revenue & conversion ---- */
    CREATE TABLE IF NOT EXISTS rate_rules (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT UNIQUE NOT NULL,          -- weekend | night | holiday | peak
      label TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'pct',   -- pct | fixed
      amount INTEGER NOT NULL DEFAULT 0,  -- pct points (15 = +15%) or yen
      active INTEGER NOT NULL DEFAULT 1,
      config TEXT NOT NULL DEFAULT '{}'   -- JSON: {dows:[6,0]} | {from:"20:00"} | {dates:[...]}
    );
    CREATE TABLE IF NOT EXISTS coupons (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT UNIQUE NOT NULL,
      kind TEXT NOT NULL DEFAULT 'pct',   -- pct | fixed
      amount INTEGER NOT NULL,
      min_spend INTEGER NOT NULL DEFAULT 0,
      max_uses INTEGER NOT NULL DEFAULT 0,-- 0 = unlimited
      used INTEGER NOT NULL DEFAULT 0,
      expires TEXT,                       -- YYYY-MM-DD or null
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS coupon_redemptions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT NOT NULL,
      booking_ref TEXT,
      user_id INTEGER,
      amount INTEGER NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS gift_certificates (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT UNIQUE NOT NULL,
      initial INTEGER NOT NULL,
      balance INTEGER NOT NULL,
      currency TEXT NOT NULL DEFAULT 'jpy',
      purchaser_email TEXT,
      recipient_email TEXT,
      message TEXT,
      status TEXT NOT NULL DEFAULT 'active', -- active | redeemed | void
      pay_status TEXT NOT NULL DEFAULT 'unpaid',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS waitlist (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT, phone_enc TEXT, mail_enc TEXT,
      plan TEXT, date TEXT, time TEXT, pax INTEGER,
      notes TEXT, status TEXT NOT NULL DEFAULT 'waiting', -- waiting | offered | converted | closed
      created_at TEXT NOT NULL
    );
    /* ---- Wave B: operations ---- */
    CREATE TABLE IF NOT EXISTS chauffeurs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL, phone_enc TEXT, license TEXT,
      status TEXT NOT NULL DEFAULT 'active', -- active | off | inactive
      notes TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS maintenance (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      veh TEXT NOT NULL, kind TEXT NOT NULL, -- inspection | service | repair | cleaning
      due_date TEXT, done_date TEXT, odo INTEGER, cost INTEGER,
      status TEXT NOT NULL DEFAULT 'scheduled', -- scheduled | done | overdue
      notes TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS inventory (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item TEXT NOT NULL, unit TEXT, stock INTEGER NOT NULL DEFAULT 0,
      threshold INTEGER NOT NULL DEFAULT 0, per_booking INTEGER NOT NULL DEFAULT 0,
      addon_id TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS crm_notes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      cust_key TEXT NOT NULL, -- email (lower) or phone
      booking_ref TEXT, tag TEXT, note TEXT,
      author TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS contracts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      booking_ref TEXT NOT NULL, token TEXT UNIQUE NOT NULL,
      signer_name TEXT, signed_at TEXT, ip TEXT,
      agreed INTEGER NOT NULL DEFAULT 0, signature TEXT,
      status TEXT NOT NULL DEFAULT 'sent', -- sent | signed
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS incidents (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      booking_ref TEXT, veh TEXT, kind TEXT, -- damage | cleaning | delay | complaint
      description TEXT, cost INTEGER NOT NULL DEFAULT 0,
      deposit_action TEXT, status TEXT NOT NULL DEFAULT 'open', -- open | resolved
      created_at TEXT NOT NULL
    );
    /* ---- Wave C: marketing & growth ---- */
    CREATE TABLE IF NOT EXISTS reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      booking_ref TEXT, author_name TEXT NOT NULL, rating INTEGER NOT NULL,
      title TEXT, body TEXT, occasion TEXT,
      approved INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS referrals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER, code TEXT UNIQUE NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS referral_credits (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT NOT NULL, referred_email TEXT, booking_ref TEXT,
      amount INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS corporate (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      company TEXT NOT NULL, contact_name TEXT, email_enc TEXT, phone_enc TEXT,
      monthly_est TEXT, note TEXT, status TEXT NOT NULL DEFAULT 'new', -- new | approved | declined
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS newsletter (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL, lang TEXT NOT NULL DEFAULT 'en', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS posts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      slug TEXT UNIQUE NOT NULL, kind TEXT NOT NULL DEFAULT 'blog', -- blog | help
      title TEXT NOT NULL, excerpt TEXT, body TEXT, lang TEXT NOT NULL DEFAULT 'en',
      published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      kind TEXT NOT NULL, ref TEXT, path TEXT, created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
    CREATE INDEX IF NOT EXISTS idx_reviews_appr ON reviews(approved);
    /* ---- Wave D: trust & self-service ---- */
    CREATE TABLE IF NOT EXISTS leads (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email_enc TEXT, name TEXT, plan TEXT, date TEXT, time TEXT, pax INTEGER,
      quote_total INTEGER, selection TEXT, status TEXT NOT NULL DEFAULT 'new', -- new | contacted | converted | closed
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);
    CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
    CREATE INDEX IF NOT EXISTS idx_payments_ref ON payments(booking_ref);
    CREATE INDEX IF NOT EXISTS idx_notifications_ref ON notifications(booking_ref);
  `);
}

// forward-migration helper (fleet pattern)
function addColumn(table, col, decl) {
  const cols = q.all(`PRAGMA table_info(${table})`).map((c) => c.name);
  if (!cols.includes(col)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${col} ${decl}`);
}

// ---- seed -----------------------------------------------------------------
const DEMO = [
  ['ALS-0712-311','Yuki Tanaka','090-1122-3344','yuki.t@example.com','p90','exc4','2026-07-12','20:00',8,['bday'],'Umeda, Osaka','','25th birthday surprise — number balloon "25", gold if possible.',47300,'pending','2026-07-12T09:41:00'],
  ['ALS-0712-315','Sara Ito','080-5566-7788','sara.i@example.com','chx','mas','2026-07-12','17:00',2,[],'Ashiya Station','','Anniversary drive along the coast road.',33000,'pending','2026-07-12T08:12:00'],
  ['ALS-0714-208','Marcus Chen','+65 9123 4567','m.chen@example.com','kix','exc3','2026-07-14','15:30',6,[],'KIX Terminal 1 arrivals','SQ 618','Family of 6, 8 suitcases. Hotel: The St. Regis Osaka.',55000,'pending','2026-07-11T22:05:00'],
  ['ALS-0715-092','Mika Sato','070-2233-9911','mika@example.com','night','c300','2026-07-15','20:00',7,[],'Sannomiya, Kobe','',"Girls' night — please queue our Spotify playlist.",55000,'confirmed','2026-07-10T18:30:00'],
  ['ALS-0718-104','Ayaka Fujii','090-8877-6655','ayaka.f@example.com','bridal','ssk','2026-07-18','10:00',2,['flor'],'Kitano, Kobe','','Wedding entrance shoot — coordinating with venue planner.',44000,'confirmed','2026-07-09T14:20:00'],
  ['ALS-0725-077','Kobe Grand Wedding K.K.','078-000-1122','booking@kgw.example.co.jp','twin','twin','2026-07-25','16:00',16,[],'Kobe Meriken Park','','Corporate account — twin convoy for bridal party, invoice billing.',78000,'confirmed','2026-07-05T11:00:00'],
  ['ALS-0711-063','Haruto Yamamoto','080-4455-2211','haruto@example.com','half','dts','2026-07-11','12:00',6,['cat'],'Grand Front Osaka','','Brand shoot with catering for the crew.',134000,'completed','2026-07-03T16:44:00'],
  ['ALS-0710-051','Emily Wong','+852 6111 2233','emily.w@example.com','tkz','exc3','2026-07-10','13:00',8,[],'Takarazuka Grand Theater','','Big Takarazuka fans — photo on the Hana-no-Michi please!',38500,'completed','2026-07-02T10:15:00'],
  ['ALS-0709-036','Riko Mori','090-3344-5566','riko@example.com','p60','dts','2026-07-09','19:00',5,[],'Shinsaibashi','','—',38500,'declined','2026-07-08T21:02:00'],
  ['ALS-0708-027','Hana Ueda','080-9911-0022','hana.u@example.com','p90','exc4','2026-07-08','20:00',8,['cat'],'Namba','','Company kickoff after-party.',76000,'completed','2026-07-04T12:30:00'],
  ['ALS-0707-021','Daichi Kobayashi','070-7788-3344','daichi@example.com','p60','exc3','2026-07-07','21:00',6,[],'Kobe Harborland','','—',38500,'completed','2026-07-01T09:20:00'],
  ['ALS-0706-014','Leo Nakamura','090-6600-1188','leo.n@example.com','night','c300','2026-07-06','20:00',4,[],'Sannomiya, Kobe','','Content shoot for our channel.',55000,'completed','2026-06-30T17:55:00'],
];

function seedBookings() {
  const count = q.get('SELECT COUNT(*) AS n FROM bookings').n;
  if (count > 0) return;
  const payFor = (st) => (st === 'completed' ? 'paid' : st === 'confirmed' ? 'deposit_paid' : 'unpaid');
  DEMO.forEach((r, i) => {
    const [ref, name, phone, mail, plan, veh, date, time, pax, addons, pickup, flight, notes, total, status, created] = r;
    q.run(
      `INSERT INTO bookings (ref,user_id,name,phone_enc,mail_enc,plan,veh,date,time,pax,addons,pickup,flight,notes,total,deposit,status,pay_status,created_at,ts)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
      ref, null, name, enc(phone), enc(mail), plan, veh, date, time, pax,
      JSON.stringify(addons), pickup, flight, notes, total, Math.round(total * 0.3),
      status, payFor(status), created, DEMO.length - i
    );
  });
  console.log('[db] seeded', DEMO.length, 'demo bookings');
}

function seedLineIds() {
  // give a few demo bookings a LINE ID so the customer directory shows the field populated
  const sample = {
    'ALS-0712-311': 'yuki_t25',
    'ALS-0715-092': 'mika.kobe',
    'ALS-0718-104': 'ayaka_bridal',
    'ALS-0725-077': 'kobegrandwedding',
  };
  for (const ref in sample) {
    const row = q.get('SELECT id, line_enc FROM bookings WHERE ref = ?', ref);
    if (row && !row.line_enc) q.run('UPDATE bookings SET line_enc = ? WHERE id = ?', enc(sample[ref]), row.id);
  }
}

function seedRevenue() {
  if (q.get('SELECT COUNT(*) AS n FROM rate_rules').n === 0) {
    const rules = [
      ['weekend', 'Weekend surcharge', 'pct', 15, JSON.stringify({ dows: [6, 0] })],
      ['night', 'Night surcharge (from 20:00)', 'pct', 10, JSON.stringify({ from: '20:00' })],
      ['holiday', 'Holiday / peak surcharge', 'pct', 20, JSON.stringify({ dates: ['2026-12-24', '2026-12-25', '2026-12-31', '2027-01-01'] })],
    ];
    rules.forEach((r) => q.run('INSERT INTO rate_rules (code,label,kind,amount,active,config) VALUES (?,?,?,?,1,?)', ...r));
  }
  if (q.get('SELECT COUNT(*) AS n FROM coupons').n === 0) {
    const now = nowISO();
    q.run('INSERT INTO coupons (code,kind,amount,min_spend,max_uses,used,expires,active,created_at) VALUES (?,?,?,?,?,0,?,1,?)',
      'WELCOME10', 'pct', 10, 30000, 0, null, now);
    q.run('INSERT INTO coupons (code,kind,amount,min_spend,max_uses,used,expires,active,created_at) VALUES (?,?,?,?,?,0,?,1,?)',
      'KANSAI5000', 'fixed', 5000, 50000, 100, null, now);
  }
}

function seedOps() {
  if (q.get('SELECT COUNT(*) AS n FROM chauffeurs').n === 0) {
    const drivers = [
      ['Kenji Mori', '090-2001-0001', 'JP-2LARGE-88213', 'active'],
      ['Takumi Sato', '090-2001-0002', 'JP-2LARGE-77104', 'active'],
      ['Hiroshi Abe', '090-2001-0003', 'JP-2LARGE-66590', 'active'],
      ['Yusuke Kato', '090-2001-0004', 'JP-2LARGE-55021', 'off'],
    ];
    drivers.forEach((d) => q.run('INSERT INTO chauffeurs (name,phone_enc,license,status,created_at) VALUES (?,?,?,?,?)', d[0], enc(d[1]), d[2], d[3], nowISO()));
  }
  if (q.get('SELECT COUNT(*) AS n FROM inventory').n === 0) {
    const items = [
      ['Champagne (house)', 'bottle', 24, 6, 1, ''],
      ['Premium champagne', 'bottle', 8, 3, 1, 'champagne'],
      ['Balloon sets', 'set', 40, 10, 1, 'bday'],
      ['Rock/flute glasses', 'set', 30, 8, 1, ''],
      ['Celebration cakes', 'unit', 5, 2, 1, 'cake'],
      ['Red carpet', 'unit', 3, 1, 1, 'redcarpet'],
    ];
    items.forEach((i) => q.run('INSERT INTO inventory (item,unit,stock,threshold,per_booking,addon_id,created_at) VALUES (?,?,?,?,?,?,?)', i[0], i[1], i[2], i[3], i[4], i[5], nowISO()));
  }
  if (q.get('SELECT COUNT(*) AS n FROM maintenance').n === 0) {
    q.run('INSERT INTO maintenance (veh,kind,due_date,status,notes,created_at) VALUES (?,?,?,?,?,?)', 'dts', 'inspection', '2026-07-20', 'scheduled', 'Shaken statutory inspection', nowISO());
    q.run('INSERT INTO maintenance (veh,kind,due_date,status,notes,created_at) VALUES (?,?,?,?,?,?)', 'exc3', 'service', '2026-08-05', 'scheduled', 'Oil + brake check', nowISO());
  }
}

function seedGrowth() {
  if (q.get('SELECT COUNT(*) AS n FROM reviews').n === 0) {
    const rv = [
      ['Mika S.', 5, 'A music-video night', 'The number balloon, the glasses, the LED ceiling — my friends screamed when the door opened. 60 minutes felt like a music video.', 'Birthday · Osaka'],
      ['Marcus & Elena', 5, 'The only way to land at KIX', 'They tracked our delayed flight and were waiting at arrivals anyway. Rolling into Osaka in a 9-meter limousine is unforgettable.', 'KIX arrival · Hong Kong'],
      ['Ayaka & Ren', 5, 'Perfect proposal direction', 'He booked the night cruise and the florist arrangement. When the bridge lights came on, the ring came out. Flawless.', 'Proposal · Kobe'],
      ['Kobe Grand Wedding', 5, 'Two-car convoy wow factor', 'The twin convoy for our bridal party turned every head at Meriken Park. Professional chauffeurs, spotless cars.', 'Corporate · Kobe'],
    ];
    rv.forEach((r) => q.run('INSERT INTO reviews (author_name,rating,title,body,occasion,approved,created_at) VALUES (?,?,?,?,?,1,?)', r[0], r[1], r[2], r[3], r[4], nowISO()));
  }
  if (q.get('SELECT COUNT(*) AS n FROM posts').n === 0) {
    const posts = [
      ['kobe-wedding-limo', 'blog', 'A Kobe wedding entrance in a 9-metre limousine', 'How a stretch limousine transforms your wedding entrance and photos along Meriken Park.', 'From the Kitano chapels to Meriken Park, a 9-metre stretch limousine turns the short drive between ceremony and reception into the most photographed moment of the day. Add the FLORIST HIROKO arrangement and a red-carpet arrival for a true showstopper.'],
      ['kix-arrival-in-style', 'blog', 'Arrive at KIX like a headline act', 'Flight-tracked airport transfers from Kansai International to your Osaka hotel.', 'We track your arriving flight, meet you at the gate, and cruise you into the city in a limousine that makes the whole trip feel like a premiere. Optional city photo stops turn the transfer into an experience.'],
      ['what-to-know', 'help', 'Before your ride: what to know', 'Cancellation policy, what you can bring, and how payment works.', 'Once confirmed, same-day and day-before cancellations are charged 100%. Drinks and light food are welcome; fast food is not. A 30% deposit confirms your date and the balance is due by the day of service.'],
    ];
    posts.forEach((p) => q.run('INSERT INTO posts (slug,kind,title,excerpt,body,lang,published,created_at) VALUES (?,?,?,?,?,?,1,?)', p[0], p[1], p[2], p[3], p[4], 'en', nowISO()));
  }
}

function ensureAdmin() {
  const email = (process.env.ADMIN_EMAIL || 'admin').toLowerCase();
  const pw = process.env.ADMIN_PASSWORD || '0000';
  const existing = q.get('SELECT id FROM users WHERE role = ? LIMIT 1', 'admin');
  if (existing) {
    // keep the admin password in sync with the env each boot
    q.run('UPDATE users SET pass_hash = ?, email = ? WHERE id = ?', bcrypt.hashSync(pw, 10), email, existing.id);
    return;
  }
  q.run(
    'INSERT INTO users (email,pass_hash,name,role,created_at) VALUES (?,?,?,?,?)',
    email, bcrypt.hashSync(pw, 10), 'Dispatch Admin', 'admin', nowISO()
  );
  console.log('[db] created admin user', email);
}

// ---- snapshot lifecycle ---------------------------------------------------
function snapshot() {
  if (!SNAP_PATH) return;
  try {
    const tmp = path.join(LOCAL_DIR, 'snap.tmp.db');
    if (fs.existsSync(tmp)) fs.unlinkSync(tmp);
    db.exec(`VACUUM INTO '${tmp.replace(/'/g, "''")}'`);
    fs.copyFileSync(tmp, SNAP_PATH); // plain-file write to the bucket — safe
    fs.unlinkSync(tmp);
  } catch (e) {
    console.warn('[db] snapshot failed:', e.message);
  }
}

let started = false;
function init() {
  if (started) return;
  started = true;
  initSchema();
  // forward migrations (safe to run every boot)
  addColumn('bookings', 'line_enc', 'TEXT');
  addColumn('users', 'line_enc', 'TEXT');
  // Wave A pricing breakdown on bookings
  addColumn('bookings', 'base', 'INTEGER');
  addColumn('bookings', 'surcharge', 'INTEGER NOT NULL DEFAULT 0');
  addColumn('bookings', 'discount', 'INTEGER NOT NULL DEFAULT 0');
  addColumn('bookings', 'coupon', 'TEXT');
  addColumn('bookings', 'tip', 'INTEGER NOT NULL DEFAULT 0');
  addColumn('bookings', 'gift_code', 'TEXT');
  addColumn('bookings', 'gift_applied', 'INTEGER NOT NULL DEFAULT 0');
  addColumn('users', 'points', 'INTEGER NOT NULL DEFAULT 0');
  addColumn('bookings', 'driver_id', 'INTEGER'); // Wave B: chauffeur assignment
  seedBookings();
  seedLineIds();
  seedRevenue();
  seedOps();
  seedGrowth();
  ensureAdmin();
  snapshot(); // persist the freshly seeded DB immediately
  if (SNAP_PATH) {
    setInterval(snapshot, 5 * 60 * 1000).unref();
    console.log('[db] snapshot lifecycle active ->', SNAP_PATH);
  } else {
    console.warn('[db] DB_PATH unset — running EPHEMERAL (data lost on rebuild/sleep). Set DB_PATH=/data/app.db + enable persistent storage.');
  }
}

module.exports = { db, q, init, snapshot, nowISO, genRef, addColumn };
