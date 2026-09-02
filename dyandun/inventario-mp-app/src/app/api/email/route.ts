import { NextResponse } from "next/server";

// Envia la orden de despacho por correo usando la API REST de Resend (sin SDK,
// solo fetch). Si faltan credenciales responde ok:false con un mensaje para que
// la UI lo muestre, igual que la ruta de Telegram.
export async function POST(request: Request) {
  const body = await request.json();
  const subject = String(body.subject ?? "Orden de despacho");
  const html = String(body.html ?? "");
  const text = String(body.text ?? "");

  const apiKey = process.env.RESEND_API_KEY;
  const from = process.env.EMAIL_FROM;
  const envTo = process.env.EMAIL_TO;
  const to = String(body.to ?? "").trim() || envTo;

  if (!apiKey || !from || !to) {
    return NextResponse.json({
      ok: false,
      message:
        "Configura RESEND_API_KEY, EMAIL_FROM y EMAIL_TO (o indica un correo destino) para enviar por correo."
    });
  }

  const recipients = to
    .split(/[,;]/)
    .map((value) => value.trim())
    .filter(Boolean);

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ from, to: recipients, subject, html, text })
  });

  if (!response.ok) {
    const detail = await response.text();
    return NextResponse.json({ ok: false, message: `Resend respondio ${response.status}: ${detail}` });
  }

  return NextResponse.json({ ok: true });
}
