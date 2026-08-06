"""Raga info cards for the app (content: assets/raga_metadata.json)."""

import html
import json

from raagafinder.config import ASSETS_DIR


def load_metadata() -> dict:
    return json.loads((ASSETS_DIR / "raga_metadata.json").read_text(encoding="utf-8"))


def confidence_bar_html(top3, uncertain: bool) -> str:
    colors = ["#2e7d32", "#558b2f", "#9e9d24"] if not uncertain else ["#9e9e9e"] * 3
    rows = []
    for i, (name, prob) in enumerate(top3):
        pct = max(1.5, prob * 100)
        rows.append(
            f'<div style="margin:6px 0">'
            f'<div style="display:flex;justify-content:space-between;font-size:15px">'
            f'<span><b>{html.escape(name)}</b></span><span>{prob * 100:.1f}%</span></div>'
            f'<div style="background:#eceff1;border-radius:6px;height:12px">'
            f'<div style="width:{pct:.1f}%;background:{colors[i]};height:12px;'
            f'border-radius:6px"></div></div></div>'
        )
    return "".join(rows)


def confusion_html(name: str, confusions: dict | None) -> str:
    """What this raga actually turned out to be when the model got it wrong.

    Conditioned on the PREDICTION, not the true label, because that is the
    question someone reading a result is asking: the model said this, what
    else could it be. Written by scripts/annotate_confusions.py from the
    grouped OOF matrix, and only present for classes with enough misses for
    the pattern to mean something.
    """
    c = (confusions or {}).get(name)
    if not c:
        return ""
    alts = ", ".join(html.escape(a["raga"]) for a in c["actually"])
    return (
        f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid #eee">'
        f'<b>Most often confused with:</b> {alts}'
        f'<div style="color:#777;font-size:12px;margin-top:2px">'
        f'In cross-validation, {c["n_wrong"]} of the {c["n_predicted"]} '
        f'recordings this model called {html.escape(name)} were actually a '
        f'different raga.</div></div>'
    )


def card_html(
    name: str, prob: float, meta: dict, rank: int, confusions: dict | None = None
) -> str:
    info = meta.get(name)
    if not info:
        return ""
    # A few of the rarely-performed ragas carry no composition, because none
    # could be attributed with confidence and a wrong attribution is the one
    # claim on these cards a listener has no way to check. An empty list means
    # "no verified composition", so the heading is dropped rather than
    # rendered above an empty bullet list.
    comps = "".join(f"<li>{html.escape(c)}</li>" for c in info["compositions"])
    listen = (f'<div style="margin-top:6px"><b>Listen to:</b>'
              f'<ul style="margin:4px 0">{comps}</ul></div>') if comps else ""
    # The scale above is the claim on this card a reader is most likely to
    # want to verify, so every card carries the reference its
    # ārōhaṇa/avarōhaṇa was taken from. See tests/test_raga_metadata.py for
    # what that field must contain.
    ref = (f'<div style="margin-top:6px;font-size:12px;color:#777">'
           f'Scale reference: <a href="{html.escape(info["source"])}" '
           f'target="_blank" rel="noopener noreferrer nofollow">'
           f'{html.escape(info["source"].split("/")[2])}</a></div>')
    return f"""
<details {"open" if rank == 0 else ""} style="margin:8px 0;border:1px solid #e0e0e0;border-radius:8px;padding:8px 12px">
  <summary style="cursor:pointer;font-size:16px"><b>{html.escape(name)}</b>
    <span style="color:#777">— {prob * 100:.1f}%</span></summary>
  <div style="margin-top:8px;font-size:14px;line-height:1.5">
    <div style="color:#555">{html.escape(info["melakarta"])}</div>
    <div style="font-family:monospace;margin:6px 0">
      ↑ {html.escape(info["arohana"])}<br>↓ {html.escape(info["avarohana"])}
    </div>
    <div>{html.escape(info["description"])}</div>
    {listen}
    {confusion_html(name, confusions)}
    {ref}
  </div>
</details>"""


SOURCE_LABELS = {
    "cmd-480": "Curated research dataset (studio concert recordings)",
    "youtube": "Arbitrary YouTube recordings",
    "private": "Solo-voice devotional recordings",
    "saraga": "Saraga open concert archive",
}
LENGTH_LABELS = {
    "<60s": "under a minute",
    "60-180s": "one to three minutes",
    "180-420s": "three to seven minutes",
    "420s+": "over seven minutes",
}
MIN_SLICE = 30      # below this a percentage is too noisy to state flatly
# Escaped so Markdown renders a literal asterisk instead of pairing it with the
# footnote marker below and italicising everything in between.
THIN = "\\*"


def stratified_md(meta: dict, label: str = "") -> str:
    """The by-slice breakdown behind a model's headline accuracy.

    Read out of the artifact rather than written here by hand:
    scripts/eval_stratified.py stores these numbers into the model JSON, so a
    retrain carries the About tab with it instead of leaving it quoting the
    previous model. Returns "" for a model that has not been through that
    script, which is the right behaviour -- no section beats a stale one.
    """
    strat = (meta or {}).get("stratified")
    if not strat or not strat.get("by_source"):
        return ""
    by_source = sorted(strat["by_source"], key=lambda r: -r["top1"])
    rows = "\n".join(
        f"| {SOURCE_LABELS.get(r['slice'], r['slice'])} | {r['n']} "
        f"| {r['top1'] * 100:.0f}%{'' if r['n'] >= MIN_SLICE else THIN} |"
        for r in by_source
    )
    out = [
        "## What that accuracy number hides",
        "",
        f"Those figures average over a corpus that is not evenly hard, and "
        f"your own upload probably sits at the harder end. Broken down by "
        f"where the recording came from"
        f"{' (' + label + ', same cross-validation)' if label else ''}:",
        "",
        "| Source | Recordings | Top-1 |",
        "|---|---|---|",
        rows,
        "",
    ]
    yt = next((r for r in by_source if r["slice"] == "youtube"), None)
    if yt:
        out += [
            f"A clip you upload most resembles the YouTube row, so **expect "
            f"roughly {yt['top1'] * 100:.0f}%, not "
            f"{by_source[0]['top1'] * 100:.0f}%**. Two other things move it "
            f"a lot:",
            "",
        ]
    # Prefer the CMD-excluded slice. The paragraph above has just told the user
    # their upload resembles the YouTube row rather than the research corpus,
    # and quoting all-sources length numbers straight afterwards would put CMD
    # back in -- it is both the longest source and the easiest, so it lifts the
    # long bands most and would overstate what a longer upload actually buys.
    # It is also the slice the inference-time warning uses, and the two must
    # not contradict each other.
    lens = {r["slice"]: r for r in (strat.get("by_voiced_s_noncmd")
                                    or strat.get("by_voiced_s") or [])}
    if lens:
        parts = ", ".join(
            f"{LENGTH_LABELS.get(k, k)} {lens[k]['top1'] * 100:.0f}%"
            f"{'' if lens[k]['n'] >= MIN_SLICE else THIN}"
            for k in ("<60s", "60-180s", "180-420s", "420s+") if k in lens
        )
        out.append(
            f"- **Length.** Top-1 by how much actual melody the clip contains: "
            f"{parts}. Longer is much better, and the app warns you when your "
            f"clip is in the weak range."
        )
    # Rare-vs-common ragas, with source held fixed. Only worth a number if the
    # sources agree on the direction: in this corpus Saraga says rare ragas are
    # much harder (44% vs 81%) while the private devotional set says the
    # opposite (79% vs 57%), and quoting whichever one supports the claim
    # would be picking the answer first.
    deconf = [d for d in strat.get("class_size_within_source") or []
              if d["source"] != "cmd-480"]
    if deconf and all(d["rare"]["top1"] < d["common"]["top1"] for d in deconf):
        out.append(
            f"- **How common the raga is here.** Ragas with ten or fewer "
            f"training recordings run as low as "
            f"{min(d['rare']['top1'] for d in deconf) * 100:.0f}%, against "
            f"{max(d['common']['top1'] for d in deconf) * 100:.0f}% for "
            f"well-represented ones. Measured inside a single source, so it is "
            f"real data scarcity and not the source effect again."
        )
    elif deconf:
        out.append(
            "- **How common the raga is here.** Ragas with few training "
            "recordings are usually weaker, but not reliably so: in this "
            "corpus the effect is large in one source and reversed in another, "
            "so there is no honest single number to quote."
        )
    if any(r["n"] < MIN_SLICE
           for r in by_source + list(lens.values())):
        out += ["", f"{THIN} fewer than {MIN_SLICE} recordings, so treat that "
                    f"figure as a rough indication only."]
    return "\n".join(out) + "\n"


def non_curated_note(meta: dict, label: str) -> str:
    """One derived line so the *other* shipped model isn't left looking exempt.

    Every shipped model is selectable, and all of them are flattered by the
    same thing: the curated research dataset is nearly half the corpus and
    much the easiest part of it. This pools everything that isn't that.
    """
    rows = [r for r in ((meta or {}).get("stratified") or {}).get(
        "by_source", []) if r["slice"] != "cmd-480"]
    if not rows:
        return ""
    n = sum(r["n"] for r in rows)
    acc = sum(r["n"] * r["top1"] for r in rows) / n
    return (f"The {label} sits in the same place: **{acc * 100:.0f}%** across "
            f"the {n} recordings that did not come from the curated research "
            f"dataset.")


def chips_html(result) -> str:
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    import math

    midi = 69 + 12 * math.log2(result.tonic_hz / 440.0) if result.tonic_hz > 0 else 0
    note = note_names[int(round(midi)) % 12] if result.tonic_hz > 0 else "?"
    chips = [
        f"tonic ≈ {result.tonic_hz:.1f} Hz ({note})",
        f"{result.voiced_s:.0f} s of melody analyzed",
        f"{result.voiced_ratio * 100:.0f}% voiced",
    ]
    if any("Tonic re-estimated" in w for w in result.warnings):
        chips.append("tonic re-estimated")
    spans = "".join(
        f'<span style="background:#f5f5f5;border-radius:12px;padding:3px 10px;'
        f'margin-right:6px;font-size:12.5px;display:inline-block;margin-top:4px">{html.escape(c)}</span>'
        for c in chips
    )
    return f"<div>{spans}</div>"
