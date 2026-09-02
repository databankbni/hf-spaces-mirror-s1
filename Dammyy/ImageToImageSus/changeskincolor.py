import gradio as gr
import numpy as np
import cv2
from PIL import Image

FIXED_OUTLINE_REDUCE = 15

def rgb_to_hex(rgb):
    r, g, b = [int(np.clip(v, 0, 255)) for v in rgb]
    return f"#{r:02X}{g:02X}{b:02X}"

def hex_to_rgb(hex_color):
    hex_color = hex_color.strip().replace("#", "")
    if len(hex_color) != 6:
        return None
    try:
        return np.array([
            int(hex_color[0:2], 16),
            int(hex_color[2:4], 16),
            int(hex_color[4:6], 16)
        ], dtype=np.float32)
    except ValueError:
        return None

def keep_largest_components(mask, min_area_ratio=0.0006, max_components=8):
    h, w = mask.shape[:2]
    min_area = max(150, int(h * w * min_area_ratio))

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        (mask > 0).astype(np.uint8),
        8
    )

    components = []
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area >= min_area:
            components.append((area, i))

    components.sort(reverse=True)

    out = np.zeros_like(mask, dtype=np.uint8)
    for _, i in components[:max_components]:
        out[labels == i] = 255

    return out

def build_person_mask(rgb):
    h, w = rgb.shape[:2]

    margin_x = max(5, int(w * 0.08))
    margin_y = max(5, int(h * 0.08))

    rect_x = margin_x
    rect_y = margin_y
    rect_w = max(1, w - 2 * margin_x)
    rect_h = max(1, h - 2 * margin_y)

    gc_mask = np.full((h, w), cv2.GC_BGD, dtype=np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)

    try:
        cv2.grabCut(
            rgb,
            gc_mask,
            (rect_x, rect_y, rect_w, rect_h),
            bgd_model,
            fgd_model,
            5,
            cv2.GC_INIT_WITH_RECT
        )
        person = np.where(
            (gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD),
            255,
            0
        ).astype(np.uint8)
    except cv2.error:
        person = np.zeros((h, w), dtype=np.uint8)
        person[rect_y:rect_y + rect_h, rect_x:rect_x + rect_w] = 255

    person = cv2.morphologyEx(person, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    person = cv2.morphologyEx(person, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    person = keep_largest_components(person, min_area_ratio=0.01, max_components=1)
    person = cv2.GaussianBlur(person, (0, 0), 3)
    person = (person > 20).astype(np.uint8) * 255

    return person

def build_initial_skin_mask(rgb):
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)

    y, cr, cb = cv2.split(ycrcb)
    h, s, v = cv2.split(hsv)

    mask_ycrcb = (
        (cr >= 118) & (cr <= 200) &
        (cb >= 70) & (cb <= 155) &
        (y >= 35)
    )

    mask_hsv = (
        (h >= 0) & (h <= 50) &
        (s >= 18) & (s <= 190) &
        (v >= 35)
    )

    mask = (mask_ycrcb & mask_hsv).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    mask = cv2.GaussianBlur(mask, (0, 0), 3)
    mask = (mask > 40).astype(np.uint8) * 255

    return mask

def refine_skin_mask(rgb, init_mask, outline_reduce, restrict_mask=None):
    h, w = init_mask.shape[:2]

    if restrict_mask is not None:
        init_mask = cv2.bitwise_and(init_mask, restrict_mask)

    if init_mask.sum() == 0:
        return init_mask

    ys, xs = np.where(init_mask > 0)

    x1, x2 = xs.min(), xs.max()
    y1, y2 = ys.min(), ys.max()

    pad_x = max(10, int((x2 - x1) * 0.18))
    pad_y = max(10, int((y2 - y1) * 0.18))

    rx1 = max(0, x1 - pad_x)
    ry1 = max(0, y1 - pad_y)
    rx2 = min(w - 1, x2 + pad_x)
    ry2 = min(h - 1, y2 + pad_y)

    gc_mask = np.full((h, w), cv2.GC_PR_BGD, dtype=np.uint8)

    if restrict_mask is not None:
        gc_mask[restrict_mask == 0] = cv2.GC_BGD

    dilated = cv2.dilate(init_mask, np.ones((9, 9), np.uint8), iterations=1)
    eroded = cv2.erode(init_mask, np.ones((7, 7), np.uint8), iterations=1)

    gc_mask[:ry1, :] = cv2.GC_BGD
    gc_mask[ry2 + 1:, :] = cv2.GC_BGD
    gc_mask[:, :rx1] = cv2.GC_BGD
    gc_mask[:, rx2 + 1:] = cv2.GC_BGD

    gc_mask[dilated > 0] = cv2.GC_PR_FGD
    gc_mask[eroded > 0] = cv2.GC_FGD

    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)

    rect = (rx1, ry1, max(1, rx2 - rx1), max(1, ry2 - ry1))

    try:
        cv2.grabCut(
            rgb,
            gc_mask,
            rect,
            bgd_model,
            fgd_model,
            5,
            cv2.GC_INIT_WITH_MASK
        )
    except cv2.error:
        pass

    refined = np.where(
        (gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD),
        255,
        0
    ).astype(np.uint8)

    refined = cv2.morphologyEx(refined, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    refined = cv2.morphologyEx(refined, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))

    if outline_reduce > 0:
        kernel_size = max(1, int(outline_reduce))
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        refined = cv2.erode(refined, kernel, iterations=1)

    if restrict_mask is not None:
        refined = cv2.bitwise_and(refined, restrict_mask)

    refined = cv2.GaussianBlur(refined, (0, 0), 3)
    refined = (refined > 35).astype(np.uint8) * 255
    refined = keep_largest_components(refined)
    refined = cv2.GaussianBlur(refined, (0, 0), 3)
    refined = (refined > 20).astype(np.uint8) * 255

    if restrict_mask is not None:
        refined = cv2.bitwise_and(refined, restrict_mask)

    return refined

def get_person_and_skin_masks(image):
    rgb = np.array(image.convert("RGB"))
    person_mask = build_person_mask(rgb)
    init_skin_mask = build_initial_skin_mask(rgb)
    init_skin_mask = cv2.bitwise_and(init_skin_mask, person_mask)
    skin_mask = refine_skin_mask(
        rgb,
        init_skin_mask,
        FIXED_OUTLINE_REDUCE,
        restrict_mask=person_mask
    )
    return rgb, person_mask, skin_mask

def make_person_cutout(image, person_mask):
    rgb = np.array(image.convert("RGB"))
    alpha = person_mask.astype(np.uint8)
    rgba = np.dstack([rgb, alpha])
    return Image.fromarray(rgba, mode="RGBA")

def extract_color_from_click(image, evt: gr.SelectData):
    if image is None:
        return ""

    rgb = np.array(image.convert("RGB"))
    x = int(evt.index[0])
    y = int(evt.index[1])

    h, w = rgb.shape[:2]
    x = max(0, min(w - 1, x))
    y = max(0, min(h - 1, y))

    radius = 5
    x1 = max(0, x - radius)
    y1 = max(0, y - radius)
    x2 = min(w, x + radius + 1)
    y2 = min(h, y + radius + 1)

    patch = rgb[y1:y2, x1:x2]
    mean_color = patch.reshape(-1, 3).mean(axis=0)

    return rgb_to_hex(mean_color)

def estimate_reference_skin_color(reference_image, selected_hex):
    if reference_image is None:
        return None, None, None, None, "Upload a reference image."

    manual_rgb = hex_to_rgb(selected_hex) if selected_hex else None

    ref_rgb, ref_person_mask, ref_skin_mask = get_person_and_skin_masks(reference_image)
    ref_person_cutout = make_person_cutout(reference_image, ref_person_mask)
    ref_skin_preview = Image.fromarray(ref_skin_mask, mode="L")

    if manual_rgb is not None:
        manual_lab = cv2.cvtColor(
            np.uint8([[manual_rgb]]),
            cv2.COLOR_RGB2LAB
        )[0][0].astype(np.float32)
        return manual_lab, manual_rgb.astype(np.uint8), ref_person_cutout, ref_skin_preview, f"Manual reference skin color selected: {selected_hex.upper()}"

    if ref_skin_mask.sum() == 0:
        return None, None, ref_person_cutout, ref_skin_preview, "No skin detected in the reference image."

    ref_lab = cv2.cvtColor(ref_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    skin_pixels_lab = ref_lab[ref_skin_mask > 0]

    target_lab = skin_pixels_lab.mean(axis=0)
    target_lab_uint8 = np.clip(target_lab, 0, 255).astype(np.uint8)

    target_rgb = cv2.cvtColor(
        np.uint8([[target_lab_uint8]]),
        cv2.COLOR_LAB2RGB
    )[0][0]

    return target_lab, target_rgb, ref_person_cutout, ref_skin_preview, "Automatic reference skin color detected from person-only area."

def apply_skin_color(original_image, reference_image, selected_hex):
    if original_image is None:
        return None, None, None, None, "Upload original image."
    if reference_image is None:
        return original_image, None, None, None, "Upload reference image."

    original_image = original_image.convert("RGB")
    orig_rgb = np.array(original_image)

    target_lab, target_rgb, ref_person_cutout, ref_skin_preview, ref_text = estimate_reference_skin_color(reference_image, selected_hex)

    if target_lab is None:
        return original_image, None, ref_person_cutout, ref_skin_preview, ref_text

    orig_rgb2, orig_person_mask, orig_skin_mask = get_person_and_skin_masks(original_image)
    orig_person_cutout = make_person_cutout(original_image, orig_person_mask)
    orig_skin_preview = Image.fromarray(orig_skin_mask, mode="L")

    if orig_skin_mask.sum() == 0:
        return original_image, orig_person_cutout, ref_person_cutout, ref_skin_preview, "No skin detected in the original image."

    orig_lab = cv2.cvtColor(orig_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    om = orig_skin_mask > 0

    orig_skin_lab = orig_lab[om]
    orig_mean_lab = orig_skin_lab.mean(axis=0)

    transformed_lab = orig_lab.copy()
    transformed_skin = transformed_lab[om]

    transformed_skin[:, 1] = transformed_skin[:, 1] - orig_mean_lab[1] + target_lab[1]
    transformed_skin[:, 2] = transformed_skin[:, 2] - orig_mean_lab[2] + target_lab[2]

    luminance_shift = target_lab[0] - orig_mean_lab[0]
    transformed_skin[:, 0] = transformed_skin[:, 0] + luminance_shift * 0.65

    transformed_skin = np.clip(transformed_skin, 0, 255)
    transformed_lab[om] = transformed_skin

    transformed_rgb = cv2.cvtColor(
        transformed_lab.astype(np.uint8),
        cv2.COLOR_LAB2RGB
    )

    alpha = orig_skin_mask.astype(np.float32) / 255.0
    alpha = cv2.GaussianBlur(alpha, (0, 0), 5)
    alpha = np.clip(alpha, 0.0, 1.0)
    alpha = np.power(alpha, 0.75)
    alpha = alpha[..., None]

    blended = (
        orig_rgb.astype(np.float32) * (1.0 - alpha)
        + transformed_rgb.astype(np.float32) * alpha
    )

    blended = np.clip(blended, 0, 255).astype(np.uint8)
    out_image = Image.fromarray(blended)

    target_hex = rgb_to_hex(target_rgb)

    text = (
        f"Reference Skin Color: {target_hex}\n"
        f"{ref_text}\n"
        f"Outline Reduce: {FIXED_OUTLINE_REDUCE}\n"
        f"Click the reference image to manually pick a skin color"
    )

    return out_image, orig_person_cutout, ref_person_cutout, ref_skin_preview, text

with gr.Blocks() as demo:
    gr.Markdown("# Skin Color Transfer")

    gr.Markdown(
        "Upload the original image and a reference image.\n"
        "The app extracts the person first, then detects skin inside that person area. You can also click the reference image to manually pick a skin color."
    )

    with gr.Row():
        original_input = gr.Image(
            label="Original Image",
            type="pil"
        )

        reference_input = gr.Image(
            label="Reference Image",
            type="pil"
        )

    selected_hex = gr.Textbox(
        label="Selected HEX Skin Color",
        value="",
        placeholder="Click the reference image to pick a skin color, or leave empty for auto-detect"
    )

    reference_input.select(
        extract_color_from_click,
        inputs=reference_input,
        outputs=selected_hex
    )

    with gr.Row():
        output_image = gr.Image(
            label="Output Image",
            type="pil"
        )

    with gr.Row():
        original_person_preview = gr.Image(
            label="Original Person Preview",
            type="pil"
        )

        reference_person_preview = gr.Image(
            label="Reference Person Preview",
            type="pil"
        )

        reference_skin_preview = gr.Image(
            label="Reference Skin Mask Preview",
            type="pil"
        )

    skin_text = gr.Textbox(
        label="Skin Color Output",
        lines=5
    )

    run_btn = gr.Button("Apply Skin Color")

    run_btn.click(
        apply_skin_color,
        inputs=[
            original_input,
            reference_input,
            selected_hex
        ],
        outputs=[
            output_image,
            original_person_preview,
            reference_person_preview,
            reference_skin_preview,
            skin_text
        ]
    )

demo.queue()
demo.launch()