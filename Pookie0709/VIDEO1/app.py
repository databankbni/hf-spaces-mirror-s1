from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from PIL import Image
import io
import base64
import os
from typing import List, Dict
import math

app = Flask(__name__)
CORS(app)

def _int_to_bits(value: int, bit_count: int) -> List[int]:
    return [(value >> (bit_count - 1 - i)) & 1 for i in range(bit_count)]

def _bits_to_int(bits: List[int]) -> int:
    value = 0
    for b in bits:
        value = (value << 1) | (b & 1)
    return value

def _bits_to_text(bits: List[int]) -> str:
    if len(bits) % 8 != 0:
        raise ValueError("Bits length not multiple of 8")
    out = bytearray()
    for i in range(0, len(bits), 8):
        out.append(_bits_to_int(bits[i:i + 8]))
    return out.decode("utf-8", errors="replace")

def capacity_in_bits(img: Image.Image) -> int:
    w, h = img.size
    channels = len(img.getbands())
    return w * h * channels

def encode_text_into_image(img: Image.Image, secret_message: str) -> Image.Image:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    pixels = list(img.getdata())
    channels = len(img.getbands())

    message_bytes = secret_message.encode("utf-8")
    header_bits = _int_to_bits(len(message_bytes), 32)

    message_bits: List[int] = []
    for b in message_bytes:
        message_bits.extend(_int_to_bits(b, 8))

    all_bits = header_bits + message_bits

    flat: List[int] = []
    for px in pixels:
        flat.extend(list(px[:channels]))

    if len(all_bits) > len(flat):
        raise ValueError("Message too large for this image!")

    for i, bit in enumerate(all_bits):
        flat[i] = (flat[i] & ~1) | bit

    new_pixels = []
    for i in range(0, len(flat), channels):
        chunk = tuple(flat[i:i + channels])
        if len(chunk) < channels:
            chunk = tuple(list(chunk) + [255] * (channels - len(chunk)))
        new_pixels.append(chunk)

    new_img = Image.new(img.mode, img.size)
    new_img.putdata(new_pixels)
    return new_img

def decode_text_from_image(img: Image.Image) -> str:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    pixels = list(img.getdata())
    channels = len(img.getbands())

    flat: List[int] = []
    for px in pixels:
        flat.extend(list(px[:channels]))

    header_bits = [flat[i] & 1 for i in range(32)]
    msg_len = _bits_to_int(header_bits)
    total_bits = msg_len * 8

    if 32 + total_bits > len(flat):
        raise ValueError("No valid hidden message or corrupted image!")

    message_bits = [flat[32 + i] & 1 for i in range(total_bits)]
    return _bits_to_text(message_bits)

def get_payload_info(text: str) -> Dict:
    message_bytes = text.encode("utf-8")
    header = len(message_bytes).to_bytes(4, "big")
    payload = header + message_bytes
    return {
        "declared_length": len(message_bytes),
        "total_payload_bytes": len(payload),
        "total_bits": len(payload) * 8,
        "pixels_needed": math.ceil((len(payload) * 8) / 3),
        "hex": " ".join(f"{b:02X}" for b in payload),
        "bin": " ".join(f"{b:08b}" for b in payload),
    }

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"success": True, "status": "ok"})

@app.route("/api/analyze", methods=["POST"])
def analyze_image():
    try:
        data = request.get_json(force=True)
        image_data = data["image"].split(",")[1]
        image_bytes = base64.b64decode(image_data)

        img = Image.open(io.BytesIO(image_bytes))
        cap_bits = capacity_in_bits(img)
        return jsonify({
            "success": True,
            "capacity_bits": cap_bits,
            "capacity_bytes": cap_bits // 8,
            "width": img.size[0],
            "height": img.size[1],
            "mode": img.mode,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/encode", methods=["POST"])
def encode():
    try:
        data = request.get_json(force=True)
        image_data = data["image"].split(",")[1]
        message = data["message"]

        image_bytes = base64.b64decode(image_data)
        img = Image.open(io.BytesIO(image_bytes))

        cap_bits = capacity_in_bits(img)
        needed_bits = 32 + len(message.encode("utf-8")) * 8
        if needed_bits > cap_bits:
            return jsonify({
                "success": False,
                "error": f"Message too large! Capacity: {cap_bits // 8} bytes"
            }), 400

        stego_img = encode_text_into_image(img, message)
        output = io.BytesIO()
        stego_img.save(output, format="PNG")
        output.seek(0)
        encoded_image = base64.b64encode(output.read()).decode()

        return jsonify({
            "success": True,
            "image": f"data:image/png;base64,{encoded_image}",
            "payload_info": get_payload_info(message),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/decode", methods=["POST"])
def decode():
    try:
        data = request.get_json(force=True)
        image_data = data["image"].split(",")[1]
        image_bytes = base64.b64decode(image_data)
        img = Image.open(io.BytesIO(image_bytes))

        message = decode_text_from_image(img)
        return jsonify({
            "success": True,
            "message": message,
            "payload_info": get_payload_info(message),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/payload", methods=["POST"])
def payload():
    try:
        data = request.get_json(force=True)
        message = data["message"]
        return jsonify({
            "success": True,
            "payload_info": get_payload_info(message),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/")
def index():
    return send_file("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)