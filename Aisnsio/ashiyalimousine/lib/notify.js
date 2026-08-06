'use strict';

/**
 * lib/notify.js — booking notifications for Ashiya Limousine Service.
 *
 * EMAIL via Resend and SMS via Twilio, both provider-OPTIONAL: a provider is
 * used only when its env keys are present, otherwise every send falls back to a
 * console.log "mock" and returns a mocked result. Nothing here ever throws.
 *
 * Node 22, CommonJS, global fetch, zero npm deps.
 *
 * Booking shape (mail/phone already decrypted plaintext when passed in):
 *   {ref, name, mail, phone, line_id, plan, plan_name_en, veh, date, time,
 *    pax, total, deposit, pickup, flight}
 */

// ---------------------------------------------------------------------------
// Provider gating
// ---------------------------------------------------------------------------

function enabled() {
  return {
    email: !!process.env.RESEND_API_KEY,
    sms: !!(
      process.env.TWILIO_ACCOUNT_SID &&
      process.env.TWILIO_AUTH_TOKEN &&
      process.env.TWILIO_FROM
    ),
  };
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function money(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return String(n == null ? '' : n);
  return '¥' + v.toLocaleString('en-US');
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function log(line) {
  try {
    console.log('[notify] ' + line);
  } catch (_) {
    /* never let logging break a send */
  }
}

// ---------------------------------------------------------------------------
// Transports (provider-or-mock; never throw)
// ---------------------------------------------------------------------------

async function sendEmail(to, subject, opts) {
  const o = opts || {};
  const html = o.html;
  const text = o.text;
  const channel = 'email';

  if (!to) {
    log('email skipped: no recipient — ' + JSON.stringify(subject || ''));
    return { ok: false, mocked: true, channel, reason: 'no-recipient' };
  }
  if (!process.env.RESEND_API_KEY) {
    log('EMAIL(mock) to=' + to + ' subject=' + JSON.stringify(subject || ''));
    return { ok: false, mocked: true, channel, reason: 'no-provider' };
  }

  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + process.env.RESEND_API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from:
          process.env.NOTIFY_EMAIL_FROM ||
          'Ashiya Limousine <onboarding@resend.dev>',
        to: [to],
        subject: subject || '',
        html: html || (text ? '<pre>' + esc(text) + '</pre>' : ''),
        text: text || '',
      }),
    });

    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }

    if (!res.ok) {
      const reason =
        'resend-' +
        res.status +
        (data && data.message ? ':' + data.message : '');
      log('EMAIL fail to=' + to + ' ' + reason);
      return { ok: false, mocked: true, channel, reason };
    }

    const id = (data && data.id) || null;
    log('EMAIL sent to=' + to + ' id=' + id);
    return { ok: true, channel, id };
  } catch (err) {
    const reason = 'exception:' + (err && err.message ? err.message : String(err));
    log('EMAIL error to=' + to + ' ' + reason);
    return { ok: false, mocked: true, channel, reason };
  }
}

async function sendSMS(to, text) {
  const channel = 'sms';

  if (!to) {
    log('sms skipped: no recipient');
    return { ok: false, mocked: true, channel, reason: 'no-recipient' };
  }

  const sid = process.env.TWILIO_ACCOUNT_SID;
  const token = process.env.TWILIO_AUTH_TOKEN;
  const from = process.env.TWILIO_FROM;
  if (!(sid && token && from)) {
    log('SMS(mock) to=' + to + ' body=' + JSON.stringify(text || ''));
    return { ok: false, mocked: true, channel, reason: 'no-provider' };
  }

  try {
    const auth = Buffer.from(sid + ':' + token).toString('base64');
    const body = new URLSearchParams({
      From: from,
      To: to,
      Body: text || '',
    }).toString();

    const res = await fetch(
      'https://api.twilio.com/2010-04-01/Accounts/' +
        encodeURIComponent(sid) +
        '/Messages.json',
      {
        method: 'POST',
        headers: {
          Authorization: 'Basic ' + auth,
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body,
      }
    );

    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }

    if (!res.ok) {
      const reason =
        'twilio-' +
        res.status +
        (data && data.message ? ':' + data.message : '');
      log('SMS fail to=' + to + ' ' + reason);
      return { ok: false, mocked: true, channel, reason };
    }

    const id = (data && data.sid) || null;
    log('SMS sent to=' + to + ' id=' + id);
    return { ok: true, channel, id };
  } catch (err) {
    const reason = 'exception:' + (err && err.message ? err.message : String(err));
    log('SMS error to=' + to + ' ' + reason);
    return { ok: false, mocked: true, channel, reason };
  }
}

// ---------------------------------------------------------------------------
// Copy: service rules + labels (EN / JA)
// ---------------------------------------------------------------------------

const PHONE = '080-5307-4774';

const RULES = {
  en: [
    'Cancellation: once confirmed, cancellations on the day or the day before are charged 100% of the plan fee.',
    'Bring your own: drinks, light food and champagne are welcome aboard free; fast food is not permitted; broken glassware is charged.',
    'Included: a dedicated chauffeur and private photo time; balloons, glasses and a photo bouquet are standard.',
    'Payment: a 30% deposit confirms your date; the balance is due by the day of service. A card payment link is sent after confirmation.',
    'On the day: please be ready 10 minutes before departure; we confirm the pickup point by phone or LINE.',
    'Contact: phone ' + PHONE + ' (daily 9:00–22:00 JST) or LINE Official.',
  ],
  ja: [
    'キャンセルについて：ご確定後、当日または前日のキャンセルはプラン料金の100%を申し受けます。',
    'お持ち込み：お飲み物・軽食・シャンパンは無料でお持ち込みいただけます。ファストフードはご遠慮ください。グラス破損は実費を申し受けます。',
    '含まれるもの：専属ドライバーとプライベート撮影タイム。バルーン・グラス・フォトブーケを標準でご用意します。',
    'お支払い：30%のデポジットでご予約日を確定します。残金はサービス当日までにお支払いください。ご確定後にカード決済リンクをお送りします。',
    '当日：ご出発の10分前にはご準備をお願いします。お迎え場所はお電話またはLINEで確認いたします。',
    'お問い合わせ：電話 ' + PHONE + '（毎日 9:00〜22:00 JST）またはLINE公式アカウントまで。',
  ],
};

const L = {
  en: {
    brand: 'Ashiya Limousine Service',
    receivedSubject: (b) => 'We received your booking — ' + b.ref,
    confirmedSubject: (b) => 'Your booking is confirmed — ' + b.ref,
    receivedIntro: (b) =>
      'Dear ' +
      (b.name || 'Guest') +
      ',\n\nThank you for choosing Ashiya Limousine Service. We have received your booking request and our team will confirm availability shortly.',
    confirmedIntro: (b) =>
      'Dear ' +
      (b.name || 'Guest') +
      ',\n\nWe are delighted to confirm your reservation with Ashiya Limousine Service. Your details are below — please review the service rules.',
    receivedHeading: 'Booking received',
    confirmedHeading: 'Booking confirmed',
    receivedTag: 'Request received — awaiting confirmation',
    confirmedTag: 'Confirmed',
    summary: 'Reservation summary',
    rulesTitle: 'Service rules',
    fields: {
      ref: 'Reference',
      plan: 'Plan',
      date: 'Date',
      time: 'Time',
      veh: 'Vehicle',
      pax: 'Guests',
      total: 'Total',
      deposit: 'Deposit (30%)',
      pickup: 'Pickup',
      flight: 'Flight',
    },
    outro:
      'For any questions call ' +
      PHONE +
      ' (daily 9:00–22:00 JST) or reach us on LINE Official.',
    smsReceived: (b) =>
      'Ashiya Limousine: booking ' +
      b.ref +
      ' received for ' +
      b.date +
      ' ' +
      b.time +
      '. We will confirm availability shortly. Tel ' +
      PHONE +
      ' / LINE Official.',
    smsConfirmed: (b) =>
      'Ashiya Limousine: booking ' +
      b.ref +
      ' CONFIRMED for ' +
      b.date +
      ' ' +
      b.time +
      '. Be ready 10 min before departure; day/day-before cancel = 100% fee. Tel ' +
      PHONE +
      ' / LINE.',
  },
  ja: {
    brand: '芦屋リムジンサービス',
    receivedSubject: (b) => 'ご予約を承りました — ' + b.ref,
    confirmedSubject: (b) => 'ご予約が確定しました — ' + b.ref,
    receivedIntro: (b) =>
      (b.name || 'お客') +
      '様\n\nこの度は芦屋リムジンサービスをお選びいただき誠にありがとうございます。ご予約リクエストを承りました。空き状況を確認のうえ、追ってご連絡いたします。',
    confirmedIntro: (b) =>
      (b.name || 'お客') +
      '様\n\n芦屋リムジンサービスのご予約が確定いたしました。ご予約内容は以下の通りです。ご利用規約をあわせてご確認ください。',
    receivedHeading: 'ご予約を承りました',
    confirmedHeading: 'ご予約が確定しました',
    receivedTag: 'リクエスト受付 — 確定待ち',
    confirmedTag: '確定済み',
    summary: 'ご予約内容',
    rulesTitle: 'ご利用規約',
    fields: {
      ref: '予約番号',
      plan: 'プラン',
      date: '日付',
      time: '時間',
      veh: '車両',
      pax: 'ご人数',
      total: '合計',
      deposit: 'デポジット（30%）',
      pickup: 'お迎え場所',
      flight: 'フライト',
    },
    outro:
      'ご不明な点は ' +
      PHONE +
      '（毎日 9:00〜22:00 JST）またはLINE公式アカウントまでお問い合わせください。',
    smsReceived: (b) =>
      '芦屋リムジン：ご予約 ' +
      b.ref +
      '（' +
      b.date +
      ' ' +
      b.time +
      '）を承りました。空き状況を確認し追ってご連絡します。Tel ' +
      PHONE +
      ' / LINE公式。',
    smsConfirmed: (b) =>
      '芦屋リムジン：ご予約 ' +
      b.ref +
      '（' +
      b.date +
      ' ' +
      b.time +
      '）が確定しました。ご出発10分前にご準備を。当日・前日キャンセルは100%。Tel ' +
      PHONE +
      ' / LINE。',
  },
};

function pickLang(lang) {
  return lang === 'ja' ? 'ja' : 'en';
}

// ---------------------------------------------------------------------------
// Content builders
// ---------------------------------------------------------------------------

function summaryRows(b, t) {
  const f = t.fields;
  const rows = [
    [f.ref, b.ref],
    [f.plan, b.plan_name_en || b.plan],
    [f.date, b.date],
    [f.time, b.time],
    [f.veh, b.veh],
    [f.pax, b.pax],
    [f.total, money(b.total)],
    [f.deposit, money(b.deposit)],
  ];
  if (b.pickup) rows.push([f.pickup, b.pickup]);
  if (b.flight) rows.push([f.flight, b.flight]);
  return rows;
}

function textSummary(b, t) {
  return summaryRows(b, t)
    .map((r) => '  ' + r[0] + ': ' + (r[1] == null ? '' : r[1]))
    .join('\n');
}

function htmlSummary(b, t) {
  const cells = summaryRows(b, t)
    .map(
      (r) =>
        '<tr>' +
        '<td style="padding:6px 12px 6px 0;color:#9aa0b4;font-size:13px;white-space:nowrap;vertical-align:top;">' +
        esc(r[0]) +
        '</td>' +
        '<td style="padding:6px 0;color:#f4f4f6;font-size:14px;font-weight:600;">' +
        esc(r[1]) +
        '</td>' +
        '</tr>'
    )
    .join('');
  return (
    '<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;">' +
    cells +
    '</table>'
  );
}

function htmlRules(rules) {
  const items = rules
    .map(
      (r) =>
        '<li style="margin:0 0 10px;color:#c9ccd8;font-size:13px;line-height:1.6;">' +
        esc(r) +
        '</li>'
    )
    .join('');
  return (
    '<ol style="margin:0;padding-left:20px;">' + items + '</ol>'
  );
}

function shell(t, heading, tag, introHtml, bodyHtml) {
  return (
    '<!--[if mso]><style>body,table,td{font-family:Arial,Helvetica,sans-serif !important;}</style><![endif]-->' +
    '<div style="margin:0;padding:0;background:#0A0D18;">' +
    '<div style="max-width:600px;margin:0 auto;padding:24px 16px;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif;">' +
    // header
    '<div style="text-align:center;padding:8px 0 20px;">' +
    '<div style="font-size:12px;letter-spacing:3px;color:#D4AF37;text-transform:uppercase;">' +
    esc(t.brand) +
    '</div>' +
    '</div>' +
    // card
    '<div style="background:#0f1424;border:1px solid rgba(212,175,55,0.25);border-radius:14px;padding:24px;">' +
    '<div style="display:inline-block;background:rgba(212,175,55,0.12);border:1px solid rgba(212,175,55,0.4);color:#D4AF37;font-size:11px;letter-spacing:1px;text-transform:uppercase;padding:5px 12px;border-radius:999px;">' +
    esc(tag) +
    '</div>' +
    '<h1 style="margin:16px 0 8px;color:#ffffff;font-size:22px;font-weight:700;">' +
    esc(heading) +
    '</h1>' +
    '<div style="color:#c9ccd8;font-size:14px;line-height:1.7;white-space:pre-line;">' +
    introHtml +
    '</div>' +
    bodyHtml +
    '</div>' +
    // footer
    '<div style="text-align:center;padding:18px 8px 4px;color:#6b7088;font-size:12px;line-height:1.6;">' +
    esc(t.outro) +
    '</div>' +
    '</div>' +
    '</div>'
  );
}

function sectionTitle(txt) {
  return (
    '<div style="margin:22px 0 10px;color:#D4AF37;font-size:13px;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;border-top:1px solid rgba(255,255,255,0.08);padding-top:16px;">' +
    esc(txt) +
    '</div>'
  );
}

function buildReceived(b, lang) {
  const key = pickLang(lang);
  const t = L[key];

  const subject = t.receivedSubject(b);
  const intro = t.receivedIntro(b);

  const text =
    intro +
    '\n\n' +
    t.summary +
    ':\n' +
    textSummary(b, t) +
    '\n\n' +
    t.outro;

  const introHtml = esc(intro);
  const body =
    sectionTitle(t.summary) +
    htmlSummary(b, t);

  const html = shell(t, t.receivedHeading, t.receivedTag, introHtml, body);

  return { subject, text, html };
}

function buildConfirmed(b, lang) {
  const key = pickLang(lang);
  const t = L[key];
  const rules = RULES[key];

  const subject = t.confirmedSubject(b);
  const intro = t.confirmedIntro(b);

  const text =
    intro +
    '\n\n' +
    t.summary +
    ':\n' +
    textSummary(b, t) +
    '\n\n' +
    t.rulesTitle +
    ':\n' +
    rules.map((r, i) => '  ' + (i + 1) + '. ' + r).join('\n') +
    '\n\n' +
    t.outro;

  const introHtml = esc(intro);
  const body =
    sectionTitle(t.summary) +
    htmlSummary(b, t) +
    sectionTitle(t.rulesTitle) +
    htmlRules(rules);

  const html = shell(t, t.confirmedHeading, t.confirmedTag, introHtml, body);

  return { subject, text, html };
}

// ---------------------------------------------------------------------------
// Orchestration (fan-out; never throws)
// ---------------------------------------------------------------------------

async function notifyBookingReceived(b, lang) {
  const key = pickLang(lang);
  const t = L[key];
  const built = buildReceived(b, key);

  const results = await Promise.all([
    sendEmail(b && b.mail, built.subject, { html: built.html, text: built.text }),
    sendSMS(b && b.phone, t.smsReceived(b)),
  ]);

  return { email: results[0], sms: results[1] };
}

async function notifyBookingConfirmed(b, lang) {
  const key = pickLang(lang);
  const t = L[key];
  const built = buildConfirmed(b, key);

  const results = await Promise.all([
    sendEmail(b && b.mail, built.subject, { html: built.html, text: built.text }),
    sendSMS(b && b.phone, t.smsConfirmed(b)),
  ]);

  return { email: results[0], sms: results[1] };
}

module.exports = {
  enabled,
  sendEmail,
  sendSMS,
  buildReceived,
  buildConfirmed,
  notifyBookingReceived,
  notifyBookingConfirmed,
};
