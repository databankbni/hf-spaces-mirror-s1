
import os, json, requests, time, re, base64, tempfile, pathlib
from html import escape
from fastapi import FastAPI, Request, Response

app = FastAPI(title="Zalo Proxy Space")
BOT_TOKEN = "199871668808091993:jxyddYdIpsOKneFbuIrQrYUpPIZBqtOQqxxWKUFkXhtogCqMHmySxQtZkqtBJiCe"
TARGET_API = "https://bot-api.zaloplatforms.com"
PROXY_NAME = "Trinh Bếp Thông Minh"
HF_TOKEN = os.getenv("HF_TOKEN", "")
DATASET_ID = "bep40/59f5334c0703ee5db712-zalo-data"
MAIN_SPACE_URL = "bep40-zalo-bot-webhook.hf.space"

_logs = []

def _send(cid, text):
    headers = {"Content-Type": "application/json"}
    url = f"{TARGET_API}/bot{BOT_TOKEN}/sendMessage"
    return requests.post(url, json={"chat_id": cid, "text": text}, headers=headers)

def _safe_name(name):
    return re.sub(r'[^a-zA-Z0-9]', '_', str(name))[:30]

def _save_to_dataset(image_url, image_data_b64, description, price, category, sender_id, sender_name):
    """Save product data (image + metadata) to the user's HF Dataset in grob-products-updated format."""
    if not HF_TOKEN or not DATASET_ID:
        _log("dataset_skip", sender_id, "N/A", "HF_TOKEN or DATASET_ID missing")
        return None
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=HF_TOKEN)
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe_sender = _safe_name(sender_id) or "unknown"
        img_filename = f"images/{ts}_{safe_sender}.jpg"
        meta_filename = f"data/{ts}_{safe_sender}.json"

        # Download or decode image
        img_bytes = None
        if image_data_b64:
            try:
                img_bytes = base64.b64decode(image_data_b64)
            except Exception:
                img_bytes = None
        elif image_url:
            try:
                r = requests.get(image_url, timeout=15)
                img_bytes = r.content
            except Exception as e:
                _log("image_download_fail", sender_id, "N/A", str(e))
                img_bytes = None

        # Upload image if we got bytes
        if img_bytes:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name
            try:
                api.upload_file(
                    path_or_fileobj=tmp_path,
                    path_in_repo=img_filename,
                    repo_id=DATASET_ID,
                    repo_type="dataset",
                    token=HF_TOKEN,
                    commit_message=f"Add product image from {sender_name}",
                )
            except Exception as e:
                _log("image_upload_fail", sender_id, "N/A", str(e))
            finally:
                pathlib.Path(tmp_path).unlink(missing_ok=True)

        # Upload metadata as JSON (structured like grob-products-updated)
        record = {
            "image": img_filename if img_bytes else None,
            "description": str(description)[:500] if description else "",
            "price": str(price) if price else "",
            "category": str(category) if category else "",
            "sender_id": str(sender_id),
            "sender_name": str(sender_name),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(record, tmp, indent=2, ensure_ascii=False)
            tmp_path = tmp.name
        try:
            api.upload_file(
                path_or_fileobj=tmp_path,
                path_in_repo=meta_filename,
                repo_id=DATASET_ID,
                repo_type="dataset",
                token=HF_TOKEN,
                commit_message=f"Add product metadata from {sender_name}",
            )
        finally:
            pathlib.Path(tmp_path).unlink(missing_ok=True)

        _log("dataset_saved", sender_id, "N/A", f"Saved to {DATASET_ID}")
        return DATASET_ID
    except Exception as e:
        _log("dataset_error", sender_id, "N/A", str(e))
        return None

@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "ok", "proxy_target": "Zalo Bot API", "bot_name": PROXY_NAME, "dataset": DATASET_ID}

@app.get("/webhooks")
async def webhooks_get():
    """GET handler for Zalo testWebhook — returns 200 OK"""
    return Response(content=json.dumps({"message": "Success"}), media_type="application/json", status_code=200)

@app.post("/webhooks")
async def webhooks(request: Request):
    body = await request.body()
    body_str = body.decode("utf-8") if body else ""
    try:
        data = json.loads(body_str)
    except Exception:
        _log("parse_error", "N/A", "N/A", "Bad JSON")
        return Response(content=json.dumps({"message": "Bad JSON"}), media_type="application/json", status_code=400)

    result = data.get("result", data)
    event = result.get("event_name", "unknown")
    msg = result.get("message", {})
    sender = msg.get("from", {})
    chat = msg.get("chat", {})
    text = msg.get("text", "")
    sender_id = str(sender.get("id", ""))
    sender_name = sender.get("display_name") or sender.get("name") or sender_id
    chat_id = str(chat.get("id", ""))
    chat_type = str(chat.get("chat_type", ""))

    # Extract image info from message (Zalo sends attachments/images)
    attachments = msg.get("attachment", {})
    image_url = ""
    image_data_b64 = ""
    if attachments:
        payload = attachments.get("payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        image_url = payload.get("url", "")
        image_data_b64 = payload.get("data", "") or msg.get("image", "")

    _log(event, sender_id, chat_id, text, sender_name, chat_type)

    if event == "message.text.received" and chat_id:
        # Parse structured data from text
        description = ""
        price = ""
        category = ""
        desc_match = re.search(r'(?:mo ta|description|desc)[:\s]*([^|]+)', text, re.IGNORECASE)
        price_match = re.search(r'(?:gia|price)[:\s]*([\d,.]+)', text, re.IGNORECASE)
        cat_match = re.search(r'(?:chuyen muc|category|danh muc)[:\s]*([^|]+?)(?:$|\n)', text, re.IGNORECASE)
        if desc_match:
            description = desc_match.group(1).strip()
        if price_match:
            price = price_match.group(1).strip()
        if cat_match:
            category = cat_match.group(1).strip()

        # Save to dataset if we have image or structured text
        if image_url or image_data_b64 or description or price or category:
            dataset_id = _save_to_dataset(
                image_url=image_url,
                image_data_b64=image_data_b64,
                description=description or text[:200],
                price=price,
                category=category,
                sender_id=sender_id,
                sender_name=sender_name,
            )
            if dataset_id:
                reply = (
                    f"🎉 **Bot Zalo của bạn đã được AUTOMATION SALE thiết lập thành công!**\n\n"
                    f"✅ Mọi cấu hình đã tự động hoàn tất.\n\n"
                    f"👉 Bạn có thể vào https://zalo.me/s/botcreator để quản lý và cấu hình bot của mình.\n\n"
                    f"💾 Dữ liệu sản phẩm đã được lưu vào dataset:\n"
                    f"https://huggingface.co/datasets/{DATASET_ID}\n\n"
                    f"🔗 Webhook URL: `https://bep40-zalo-proxy-{_safe_name(sender_id)}.hf.space/webhooks`\n"
                    f"📊 Logs: https://bep40-zalo-proxy-{_safe_name(sender_id)}.hf.space/logs\n\n"
                    f"⚙️ Bot sẽ tự động trả lời khi có người nhắn tin."
                )
            else:
                reply = (
                    f"🎉 **Bot Zalo của bạn đã được AUTOMATION SALE thiết lập thành công!**\n\n"
                    f"✅ Mọi cấu hình đã tự động hoàn tất.\n\n"
                    f"👉 Bạn có thể vào https://zalo.me/s/botcreator "
                    f"để quản lý và cấu hình bot của mình."
                )
        else:
            # Default welcome message for plain text
            reply = (
                f"🎉 **Bot Zalo của bạn đã được AUTOMATION SALE thiết lập thành công!**\n\n"
                f"✅ Mọi cấu hình đã tự động hoàn tất.\n\n"
                f"👉 Bạn có thể vào https://zalo.me/s/botcreator để quản lý và cấu hình bot của mình.\n\n"
                f"🔗 Webhook URL: https://{MAIN_SPACE_URL}/webhooks\n"
                f"📊 Logs: https://{MAIN_SPACE_URL}/logs\n"
                f"🗂️ Quản lý proxy: https://{MAIN_SPACE_URL}/proxy-spaces\n\n"
                f"⚙️ Bot của bạn sẽ tự động trả lời khi có người nhắn tin."
            )
        try:
            _send(chat_id, reply)
        except Exception as e:
            pass

    return Response(content=json.dumps({"message": "Success"}), media_type="application/json", status_code=200)

@app.get("/proxy-spaces")
async def proxy_spaces_get():
    """Trang quản lý của proxy space này."""
    html_parts = []
    html_parts.append("<!DOCTYPE html><html><head><title>Quản lý Proxy</title>")
    html_parts.append('<meta http-equiv="refresh" content="5">')
    html_parts.append("<style>body{font-family:Arial,sans-serif;max-width:1000px;margin:0 auto;padding:16px;background:#fafafa;}h1{color:#1a73e8;}</style></head><body>")
    html_parts.append(f'<h1>📊 Quản lý Proxy — {escape(PROXY_NAME)}</h1>')
    html_parts.append(f'<p>Webhook URL: <code>https://{MAIN_SPACE_URL}/webhooks</code></p>')
    html_parts.append(f'<p>Logs: <a href="/logs">https://{MAIN_SPACE_URL}/logs</a></p>')
    if DATASET_ID:
        html_parts.append(f'<p>Dataset: <a href="https://huggingface.co/datasets/{DATASET_ID}" target="_blank">{escape(DATASET_ID)}</a></p>')
    html_parts.append("<p>💡 Gửi ảnh kèm mô tả/giá/chuyên mục để lưu sản phẩm vào dataset.</p>")
    html_parts.append("</body></html>")
    return Response(content="".join(html_parts), media_type="text/html")

def _log(event, sender_id, chat_id, text, sender_name="", chat_type=""):
    _logs.append({
        "event": str(event),
        "sender_id": str(sender_id),
        "sender_name": str(sender_name),
        "chat_id": str(chat_id),
        "chat_type": str(chat_type),
        "text": str(text)[:200],
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    if len(_logs) > 100:
        del _logs[:50]

@app.get("/logs")
async def proxy_logs():
    rows = ""
    for log in reversed(_logs[-50:]):
        rows += (
            f"<div style='margin:6px 0;padding:8px;background:#f5f5f5;border-radius:4px'>"
            f"<b>[{log['event']}]</b> 👤{escape(log['sender_name'])} "
            f"🆔<code>{escape(log['sender_id'])}</code> "
            f"💬<code>{escape(log['chat_id'])}</code> "
            f"[{escape(log['chat_type'])}]<br>"
            f"<span style='font-family:monospace;font-size:12px;color:#333'>"
            f"{escape(log['text'][:200])}</span><br>"
            f"<small style='color:#999'>⏰ {log['time']}</small></div>"
        )
    empty_msg = "<p style='color:#999'>Chưa có sự kiện</p>"
    content = rows if rows else empty_msg
    html = (
        "<!DOCTYPE html><html><head><title>Proxy Logs</title>"
        "<meta http-equiv='refresh' content='5'>"
        "<style>body{font-family:Arial,sans-serif;max-width:1000px;margin:0 auto;padding:16px;}"
        "h1{color:#1a73e8;} .log-c{max-height:600px;overflow-y:auto;background:#fff;border-radius:8px;padding:8px;}</style></head>"
        f"<body><h1>📊 Proxy Logs — {escape(PROXY_NAME)}</h1>"
        f"<p>Webhook proxy cho: <b>{escape(PROXY_NAME)}</b></p>"
        f"<div class='log-c'>{content}</div>"
        "</body></html>"
    )
    return Response(content=html, media_type="text/html")
