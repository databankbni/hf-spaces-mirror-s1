from __future__ import annotations

import io
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw

MAX_ELEMENTS = 60

COLORS = {
    "disabled":  (220, 38, 38),
    "editable":  (37, 99, 235),
    "checkable": (147, 51, 234),
    "scrollable": (234, 88, 12),
    "clickable": (22, 163, 74),
    "pinned":    (219, 39, 119),
    "text":      (120, 120, 120),
}

COLLECT_JS = r"""
(maxElements) => {
  const INTERACTIVE = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA','SUMMARY','OPTION']);
  const out = [];
  document.querySelectorAll('[data-arbiter-ref]').forEach(e => e.removeAttribute('data-arbiter-ref'));
  const pathOf = (el) => {
    const parts = []; let n = el;
    while (n && n.nodeType === 1 && parts.length < 10) {
      parts.unshift(n.tagName.toLowerCase() + (n.id ? '#' + n.id : ''));
      n = n.parentElement;
    }
    return parts.join('>');
  };
  const ownText = (el) => {
    let t = '';
    for (const node of el.childNodes) if (node.nodeType === 3) t += node.textContent;
    t = t.trim();
    if (!t && INTERACTIVE.has(el.tagName)) t = (el.textContent || '').trim();
    return t.replace(/\s+/g, ' ').slice(0, 90);
  };
  const nodes = Array.from(document.querySelectorAll('body *'));
  for (const el of nodes) {
    if (out.length >= maxElements) break;
    if (['SCRIPT','STYLE','META','LINK','HEAD'].includes(el.tagName)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity || '1') < 0.05) continue;
    if (r.bottom < 0 || r.top > (window.innerHeight + 400)) continue;

    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || '';
    const interactive = INTERACTIVE.has(el.tagName) || role === 'button' ||
                        el.hasAttribute('onclick') || el.tabIndex >= 0 ||
                        cs.cursor === 'pointer';
    const editable = (el.tagName === 'INPUT' &&
                      !['checkbox','radio','button','submit'].includes((el.type || '').toLowerCase()))
                     || el.tagName === 'TEXTAREA' || el.isContentEditable;
    const checkable = el.tagName === 'INPUT' && ['checkbox','radio'].includes((el.type || '').toLowerCase());
    const scrollable = (el.scrollHeight - el.clientHeight > 12) &&
                       ['auto','scroll'].includes(cs.overflowY);
    const pinned = ['fixed','sticky'].includes(cs.position);
    const text = ownText(el);
    if (!interactive && !editable && !checkable && !scrollable && !pinned && !text) continue;

    const ref = out.length;
    el.setAttribute('data-arbiter-ref', String(ref));
    out.push({
      ref, tag, role, text,
      value: (el.value !== undefined && el.type !== 'checkbox') ? String(el.value).slice(0, 90) : '',
      id: el.id || '', testid: el.getAttribute('data-testid') || '',
      type: (el.getAttribute('type') || ''),
      disabled: !!el.disabled, checked: checkable ? !!el.checked : null,
      focused: el === document.activeElement,
      clickable: !!interactive, editable: !!editable, checkable: !!checkable,
      scrollable: !!scrollable, fixed: !!pinned,
      path: pathOf(el),
      rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
    });
  }
  return {
    url: location.href, title: document.title,
    viewport: {width: window.innerWidth, height: window.innerHeight},
    scrollY: Math.round(window.scrollY),
    elements: out
  };
}
"""


def _flag_of(el: Dict[str, Any]) -> str:
    if el.get("disabled"):
        return "disabled"
    if el.get("editable"):
        return "editable"
    if el.get("checkable"):
        return "checkable"
    if el.get("scrollable"):
        return "scrollable"
    if el.get("clickable"):
        return "clickable"
    if el.get("fixed"):
        return "pinned"
    return "text"


def describe(el: Dict[str, Any]) -> str:
    flags = []
    for name in ("clickable", "editable", "checkable", "scrollable", "fixed", "focused"):
        if el.get(name):
            flags.append(name.upper())
    if el.get("disabled"):
        flags.append("DISABLED")
    if el.get("checked") is True:
        flags.append("CHECKED")
    if el.get("checked") is False:
        flags.append("UNCHECKED")
    bits = ["#{0}".format(el["ref"]), "<{0}>".format(el["tag"])]
    if el.get("id"):
        bits.append("id={0}".format(el["id"]))
    if el.get("testid"):
        bits.append("testid={0}".format(el["testid"]))
    if el.get("text"):
        bits.append('text="{0}"'.format(el["text"]))
    if el.get("value"):
        bits.append('value="{0}"'.format(el["value"]))
    r = el["rect"]
    bits.append("box=[{0},{1} {2}x{3}]".format(r["x"], r["y"], r["w"], r["h"]))
    if flags:
        bits.append("[" + " ".join(flags) + "]")
    return " ".join(bits)


def element_map(snapshot: Dict[str, Any]) -> str:
    els = snapshot.get("elements", [])
    header = ("PAGE: {0}\nTITLE: {1}\nVIEWPORT: {2}x{3}  scrollY={4}\n"
              "{5} visible elements. Box colours: green=clickable, blue=text input, "
              "purple=checkable, orange=scrollable, magenta=pinned, red=disabled, grey=static text."
              ).format(snapshot.get("url", ""), snapshot.get("title", ""),
                       snapshot.get("viewport", {}).get("width"),
                       snapshot.get("viewport", {}).get("height"),
                       snapshot.get("scrollY", 0), len(els))
    return header + "\n" + "\n".join(describe(e) for e in els)


def annotate(screenshot_png: bytes, elements: List[Dict[str, Any]]) -> bytes:
    img = Image.open(io.BytesIO(screenshot_png)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for el in elements:
        r = el["rect"]
        x0, y0 = max(0, r["x"]), max(0, r["y"])
        x1, y1 = x0 + max(1, r["w"]), y0 + max(1, r["h"])
        if x1 <= x0 or y1 <= y0:
            continue
        color = COLORS[_flag_of(el)]
        width = 3 if _flag_of(el) in ("clickable", "editable", "disabled") else 1
        draw.rectangle([x0, y0, x1, y1], outline=color, width=width)
        tag = str(el["ref"])
        tw = 7 * len(tag) + 6
        draw.rectangle([x0, max(0, y0 - 15), x0 + tw, y0], fill=color)
        draw.text((x0 + 3, max(0, y0 - 14)), tag, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def region_colors(screenshot_png: bytes, bands: int = 4) -> str:
    img = Image.open(io.BytesIO(screenshot_png)).convert("RGB")
    w, h = img.size
    lines = []
    for i in range(bands):
        band = img.crop((0, int(h * i / bands), w, int(h * (i + 1) / bands)))
        small = band.resize((40, 12))
        counts: Dict[Tuple[int, int, int], int] = {}
        for px in small.getdata():
            key = (px[0] // 32 * 32, px[1] // 32 * 32, px[2] // 32 * 32)
            counts[key] = counts.get(key, 0) + 1
        total = sum(counts.values()) or 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:2]
        desc = ", ".join("#{0:02x}{1:02x}{2:02x} {3:.0%}".format(c[0], c[1], c[2], n / total)
                         for c, n in top)
        lines.append("  band {0}/{1}: {2}".format(i + 1, bands, desc))
    return "\n".join(lines)
