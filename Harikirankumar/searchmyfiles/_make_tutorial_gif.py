from PIL import Image, ImageDraw, ImageFont

W, H = 960, 500
BG = (12, 20, 38)
PANEL = (21, 35, 63)
LINE = (56, 90, 136)
TEXT = (232, 242, 255)
MUTED = (160, 184, 220)
ACCENT = (63, 179, 255)
GREEN = (56, 211, 159)
WARN = (255, 196, 84)

steps = [
    ("1. Full Page", "Start in Full Page mode with the document preview visible"),
    ("2. Extract Text", "Click Extract Text for full-page OCR"),
    ("3. OCR Box", "See extracted text appear in the Extraction Panel"),
    ("4. Region Select", "Click Region Select to switch selection mode"),
    ("5. Drag Region", "Drag on the preview to select a target area"),
    ("6. Popup + Web Search", "Popup appears with Web Search and Open in Copilot Chat"),
    ("7. Copilot Chat", "Open Copilot Chat from the popup to continue research"),
]

try:
    font_title = ImageFont.truetype("arial.ttf", 30)
    font_step = ImageFont.truetype("arial.ttf", 21)
    font_desc = ImageFont.truetype("arial.ttf", 16)
    font_small = ImageFont.truetype("arial.ttf", 14)
    font_mono = ImageFont.truetype("consola.ttf", 14)
except Exception:
    font_title = ImageFont.load_default()
    font_step = ImageFont.load_default()
    font_desc = ImageFont.load_default()
    font_small = ImageFont.load_default()
    font_mono = ImageFont.load_default()


def lerp(a, b, t):
    return a + (b - a) * t


def draw_button(draw, rect, label, active=False, main=False):
    if main:
        fill = (41, 164, 115) if active else (33, 130, 93)
        outline = (94, 229, 173)
    else:
        fill = (43, 74, 120) if active else (29, 53, 88)
        outline = ACCENT if active else LINE
    draw.rounded_rectangle(rect, radius=8, fill=fill, outline=outline, width=2 if active else 1)
    tx = rect[0] + 8
    ty = rect[1] + 6
    draw.text((tx, ty), label, font=font_small, fill=(245, 250, 255))


def draw_cursor(draw, x, y, clicking=False):
    draw.polygon([(x, y), (x + 14, y + 28), (x + 19, y + 20), (x + 28, y + 30)], fill=(255, 255, 255), outline=(5, 10, 20))
    if clicking:
        draw.ellipse((x - 8, y - 8, x + 22, y + 22), outline=WARN, width=2)


def draw_preview_text(draw):
    # visible content inside page preview
    lines = [
        "Invoice # 2026-041      Date: 07/14/2026",
        "Bill To: Aster Retail Pvt Ltd",
        "Item                     Qty    Price    Total",
        "Industrial Scanner       1      890.00   890.00",
        "Maintenance Plan         1      350.00   350.00",
        "-----------------------------------------------",
        "Sub Total                              1240.00",
        "Tax                                       0.00",
        "Grand Total                            1240.00",
        "Due Date: 07/29/2026",
    ]
    y = 146
    for line in lines:
        draw.text((95, y), line, font=font_mono, fill=(58, 68, 92))
        y += 23


def draw_lens_popup(draw, active_button=None):
    popup = (360, 250, 640, 404)
    draw.rounded_rectangle(popup, radius=12, fill=(15, 30, 54), outline=ACCENT, width=2)
    draw.text((376, 262), "Selected Text", font=font_desc, fill=TEXT)
    draw.text((376, 290), "Total: $1,240.00", font=font_small, fill=(224, 240, 255))
    draw.text((376, 314), "Due Date: 07/29/2026", font=font_small, fill=(224, 240, 255))
    btn1 = (376, 348, 492, 376)
    btn2 = (504, 348, 632, 376)
    draw_button(draw, btn1, "Web Search", active=(active_button == "web"))
    draw_button(draw, btn2, "Copilot Chat", active=(active_button == "copilot"))


def draw_extraction_panel(draw, reveal=0.0):
    right = (680, 128, 922, 470)
    draw.rounded_rectangle(right, radius=10, fill=(13, 23, 43), outline=LINE, width=1)
    draw.text((694, 138), "Extraction Panel", font=font_small, fill=MUTED)
    dbox = (696, 176, 906, 430)
    draw.rounded_rectangle(dbox, radius=8, fill=(17, 36, 66), outline=GREEN, width=2)
    draw.text((708, 188), "OCR OUTPUT", font=font_desc, fill=(220, 255, 240))
    all_lines = [
        "Invoice # 2026-041",
        "Bill To: Aster Retail Pvt Ltd",
        "Total: $1,240.00",
        "Due Date: 07/29/2026",
        "Vendor: Northwind Ltd",
        "Status: Ready to export",
    ]
    show_n = max(0, int(round(len(all_lines) * reveal)))
    yy = 220
    for line in all_lines[:show_n]:
        draw.text((708, yy), line, font=font_small, fill=TEXT)
        yy += 31


def draw_copilot_panel(draw):
    panel = (640, 120, 922, 470)
    draw.rounded_rectangle(panel, radius=10, fill=(13, 17, 24), outline=ACCENT, width=2)
    draw.rectangle((640, 120, 922, 154), fill=(20, 27, 36), outline=ACCENT, width=1)
    draw.text((654, 131), "OCR Copilot Chat", font=font_desc, fill=TEXT)
    # conversation bubbles
    draw.rounded_rectangle((656, 174, 864, 228), radius=10, fill=(28, 58, 110), outline=(59, 130, 246), width=1)
    draw.text((668, 186), "Find related links for this selected text", font=font_small, fill=TEXT)
    draw.rounded_rectangle((690, 252, 902, 350), radius=10, fill=(22, 27, 34), outline=LINE, width=1)
    draw.text((704, 264), "Web: Invoice payment terms", font=font_small, fill=(211, 230, 255))
    draw.text((704, 289), "Images: Sample invoice layouts", font=font_small, fill=(211, 230, 255))
    draw.text((704, 314), "Videos: OCR invoice demos", font=font_small, fill=(211, 230, 255))
    draw.rounded_rectangle((656, 382, 902, 446), radius=8, fill=(15, 20, 27), outline=LINE, width=1)
    draw.text((668, 392), "Try /all, /images, /videos, /extract", font=font_small, fill=MUTED)


def draw_frame(step_idx, f, frames_per_step):
    t = f / max(frames_per_step - 1, 1)

    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # App container
    d.rounded_rectangle((18, 18, W - 18, H - 18), radius=16, fill=PANEL, outline=LINE, width=2)
    d.rectangle((32, 44, W - 32, 84), fill=(17, 29, 53), outline=LINE, width=1)
    d.text((45, 53), "SearchMyFiles - Tutorial Flow", font=font_desc, fill=TEXT)

    # Toolbar buttons
    btn_choose = (48, 92, 145, 120)
    btn_full = (158, 92, 265, 120)
    btn_region = (273, 92, 395, 120)
    btn_extract = (410, 92, 520, 120)
    btn_fullpreview = (534, 92, 664, 120)

    draw_button(d, btn_choose, "Choose File", active=False, main=True)
    draw_button(d, btn_full, "Full Page", active=(step_idx in (0, 1, 2)))
    draw_button(d, btn_region, "Region Select", active=(step_idx in (3, 4, 5, 6)))
    draw_button(d, btn_extract, "Extract Text", active=(step_idx == 1), main=True)
    draw_button(d, btn_fullpreview, "Full Preview", active=False)

    # Preview + extraction panel
    left = (38, 128, 670, 470)
    d.rounded_rectangle(left, radius=10, fill=(11, 20, 39), outline=LINE, width=1)
    d.text((50, 138), "Preview (PDF/Image)", font=font_small, fill=MUTED)

    # Page + visible text content
    page = (70, 160, 630, 450)
    d.rectangle(page, fill=(232, 239, 248), outline=(130, 148, 174), width=1)
    draw_preview_text(d)

    # Region drag animation
    drag_start = (170, 240)
    drag_end = (510, 328)
    if step_idx in (4, 5, 6):
        if step_idx == 4:
            x2 = int(lerp(drag_start[0] + 20, drag_end[0], t))
            y2 = int(lerp(drag_start[1] + 15, drag_end[1], t))
        else:
            x2, y2 = drag_end
        d.rectangle((drag_start[0], drag_start[1], x2, y2), outline=ACCENT, width=4)
        d.rectangle((drag_start[0] + 2, drag_start[1] + 2, x2 - 2, y2 - 2), outline=(255, 255, 255), width=1)

    # Extraction panel / copilot panel depending on step
    if step_idx == 1:
        draw_extraction_panel(d, reveal=max(0.15, t))
    elif step_idx == 2:
        draw_extraction_panel(d, reveal=1.0)
    elif step_idx in (3, 4, 5):
        draw_extraction_panel(d, reveal=1.0)
    elif step_idx == 6:
        draw_copilot_panel(d)
    else:
        draw_extraction_panel(d, reveal=0.0)

    # Popup after region selection
    if step_idx == 5:
        draw_lens_popup(d, active_button="web" if t < 0.5 else "copilot")

    # Cursor + click hints
    if step_idx == 0:
        cx, cy = 210, 106
        draw_cursor(d, cx, cy, clicking=False)
    elif step_idx == 1:
        cx, cy = int(lerp(300, 448, t)), int(lerp(150, 104, t))
        draw_cursor(d, cx, cy, clicking=t > 0.8)
    elif step_idx == 3:
        cx, cy = int(lerp(460, 308, t)), int(lerp(190, 104, t))
        draw_cursor(d, cx, cy, clicking=t > 0.8)
    elif step_idx == 4:
        cx, cy = int(lerp(drag_start[0], drag_end[0], t)), int(lerp(drag_start[1], drag_end[1], t))
        draw_cursor(d, cx, cy, clicking=True)
    elif step_idx == 5:
        if t < 0.5:
            cx, cy = int(lerp(540, 430, t * 2)), int(lerp(330, 360, t * 2))
        else:
            tt = (t - 0.5) / 0.5
            cx, cy = int(lerp(430, 560, tt)), int(lerp(360, 360, tt))
        draw_cursor(d, cx, cy, clicking=True)
    else:
        cx, cy = int(lerp(560, 720, t)), int(lerp(360, 170, t))
        draw_cursor(d, cx, cy, clicking=t < 0.3)

    # Bottom caption bar
    d.rounded_rectangle((38, 440, 922, 476), radius=10, fill=(15, 29, 53), outline=LINE, width=1)
    title, desc = steps[step_idx]
    d.text((50, 448), title, font=font_step, fill=ACCENT)
    d.text((278, 452), desc, font=font_desc, fill=TEXT)

    return im


frames = []
frames_per_step = 11

for idx in range(len(steps)):
    for f in range(frames_per_step):
        frames.append(draw_frame(idx, f, frames_per_step))

out_path = "tutorial_quickstart.gif"
frames[0].save(
    out_path,
    save_all=True,
    append_images=frames[1:],
    optimize=True,
    duration=170,
    loop=0,
)

print(out_path)
