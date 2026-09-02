import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const body = await request.json();
  const text = String(body.text ?? "");
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;

  if (!token || !chatId) {
    return NextResponse.json({
      ok: false,
      message: "Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID para activar notificaciones."
    });
  }

  const response = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      parse_mode: "HTML"
    })
  });

  return NextResponse.json({ ok: response.ok });
}
