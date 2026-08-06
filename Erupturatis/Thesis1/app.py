"""
app.py

Hugging Face Spaces (Gradio) interface for the unstructured pruning recommender.
It is a wrapper over the calibrated, closed-form M2 law in
pruning_model.Recommender: pick a network and an importance criterion, then
supply any two (or all three) of target sparsity, fine-tuning budget, and target
accuracy. The number of fields filled selects the query direction.

The aim of this file is to make the recommender legible to someone who has not
read the thesis: every answer is given in plain language with the derived
quantities a practitioner cares about (how many pruning rounds, how many
fine-tuning epochs per round, how much smaller the model gets), and the two plots
are drawn on a log x-axis so the accuracy cliff and the point of diminishing
returns are actually visible instead of squashed against the edge.

No GPU and no deep-learning framework are needed.
"""

import gradio as gr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter

from pruning_model import Recommender, load_cards

CARDS = load_cards()
NETWORKS = list(CARDS['networks'].keys())

BLUE, GREEN, RED, ORANGE, PURPLE = '#1f77b4', '#2ca02c', '#d62728', '#ff7f0e', '#9467bd'


def criteria_for(network):
    return list(CARDS['networks'][network]['criteria'].keys())


# ── small numeric helpers ────────────────────────────────────────────────────
def _geomspace(a, b, n):
    a = max(a, 1e-9)
    r = (b / a) ** (1.0 / (n - 1))
    return [a * r ** i for i in range(n)]


def _density(S):
    """(weights kept %, compression factor) at sparsity S."""
    keep = 1.0 - S
    return keep * 100.0, (1.0 / keep if keep > 0 else float('inf'))


def _pct(S):
    """Sparsity as a percent, shown at whatever precision the value needs and
    never rounded up to a contradictory '100%'. Trailing zeros are trimmed, and
    if a sub-100% sparsity would still round to 100 at the current precision the
    precision is increased until it reads honestly (e.g. 0.999906 -> 99.9906%)."""
    p = S * 100.0
    d = 6
    s = f"{p:.{d}f}"
    while S < 1.0 and float(s) >= 100.0:   # never let a sub-100% value read as 100
        d += 2
        s = f"{p:.{d}f}"
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return f"{s}%"


def _f_clamped(rec, S, E):
    """Effective epochs-per-round actually used by the prediction, with the raw
    value and a short status tag (ok / capped / floored)."""
    f = E / rec.rounds(S)
    if f > rec.f_cap + 1e-9:
        return f, min(f, rec.f_cap), 'capped'
    if f < rec.f_lo - 1e-9:
        return f, max(f, rec.f_lo), 'floored'
    return f, f, 'ok'


# ── info panel ───────────────────────────────────────────────────────────────
def _retrain_effect(c1):
    if c1 > 0.05:
        return 'more fine-tuning lets you prune deeper before accuracy drops'
    if c1 < -0.05:
        return 'more fine-tuning does not let you prune deeper (and can even hurt)'
    return 'fine-tuning has little effect on how deep you can prune'


def info_panel(network, criterion):
    rec = Recommender(network, criterion)
    m = rec.meta
    band = 'n/a' if rec.band_rmse is None else f'+/-{rec.band_rmse:.1f} accuracy points'
    return (
        f"### {m['title']}\n"
        f"- **Dataset:** {m['dataset']} ({m['classes']} classes)\n"
        f"- **Unpruned accuracy:** {m['baseline_acc']:.2f}% "
        f"(the dense model trained in the same fine-tuning regime, before any "
        f"pruning; the high learning rate caps it here on its own)\n"
        f"- **Importance criterion:** {rec.criterion} "
        f"(which weights get removed each round)\n"
        f"- **How pruning proceeds:** remove {rec.rho:.0%} of the surviving weights "
        f"per round, then fine-tune; repeat to reach higher sparsity\n"
        f"- **Best accuracy you can hope for:** about {rec.A_ceil:.2f}% "
        f"(random guessing would give {rec.A_ch:.1f}%)\n"
        f"- **Does fine-tuning help?** {_retrain_effect(rec.c1)}\n"
        f"- **Trustworthy sparsity range:** {_pct(rec.s_lo)} to {_pct(rec.s_hi)} "
        f"(measured; outside this the estimate is extrapolated)\n"
        f"- **Typical estimate error:** {band}\n"
    )


# ── plain-language breakdown (shared by every mode) ───────────────────────────
def _size_lines(rec, S):
    """How small the model gets and how many pruning rounds it takes."""
    R = rec.rounds(S)
    keep, comp = _density(S)
    return [
        f"- **Model size:** removes {_pct(S)} of weights, keeps {keep:.2g}% "
        f"(about {comp:.0f}x fewer parameters).",
        f"- **Pruning rounds:** reaching {_pct(S)} at {rec.rho:.0%} per round takes "
        f"about **{R:.0f} rounds**.",
    ]


def _ft_line(rec, S, E):
    """The single 'epochs of fine-tuning per round' line, with the clamp caveat."""
    R = rec.rounds(S)
    f_raw, _, tag = _f_clamped(rec, S, E)
    if tag == 'capped':
        return (f"- **Fine-tuning per round:** {E:g} epochs / {R:.0f} rounds = "
                f"{f_raw:.1f} epochs per round. That is above the calibrated maximum of "
                f"{rec.f_cap:g}, so it is **capped at {rec.f_cap:g}**; spending more "
                f"epochs here does not improve the result (raise the sparsity to use the "
                f"budget).")
    if tag == 'floored':
        return (f"- **Fine-tuning per round:** {E:g} epochs / {R:.0f} rounds = only "
                f"{f_raw:.2f} epochs per round. That is below the calibrated minimum of "
                f"{rec.f_lo:g}, so the estimate is **held at {rec.f_lo:g} and may be "
                f"optimistic**; for a reliable answer budget at least **{R:.0f} epochs** "
                f"(one epoch per round).")
    return (f"- **Fine-tuning per round:** {E:g} epochs / {R:.0f} rounds = "
            f"**{f_raw:.1f} epochs of fine-tuning per round**.")


def _schedule_lines(rec, S, E):
    return _size_lines(rec, S) + [_ft_line(rec, S, E)]


def _accuracy_lines(rec, S, E):
    A = rec.predict_accuracy(S, E)
    drop = rec.meta['baseline_acc'] - A
    return A, [
        f"- **Predicted accuracy:** **{A:.2f}%** "
        f"(unpruned was {rec.meta['baseline_acc']:.2f}%, so about "
        f"{-drop:+.2f} pts; best possible here is {rec.A_ceil:.2f}%).",
    ]


def _range_warning(rec, S):
    if S > rec.s_hi + 1e-9 or S < rec.s_lo - 1e-9:
        return (f"> **Note:** {_pct(S)} sparsity is outside the measured range "
                f"({_pct(rec.s_lo)} to {_pct(rec.s_hi)}); this answer is extrapolated and "
                f"less reliable.\n\n")
    return ''


# ── the four query directions ────────────────────────────────────────────────
def _predict(rec, S, E):
    A, acc_lines = _accuracy_lines(rec, S, E)
    out = (f"## At {_pct(S)} sparsity with a {E:g}-epoch budget\n\n"
           f"**You should reach about {A:.1f}% accuracy.**\n\n")
    out += _range_warning(rec, S)
    out += '\n'.join(acc_lines + _schedule_lines(rec, S, E)) + '\n'
    return out


def _budget(rec, S, A):
    R = rec.rounds(S)
    E, note = rec.required_budget(S, A)
    out = f"## To reach {A:.1f}% accuracy at {_pct(S)} sparsity\n\n"
    out += _range_warning(rec, S)
    if E is None:
        out += (f"**Not reachable at this sparsity.** {note}.\n\n"
                f"Try a lower sparsity, or accept a lower accuracy.\n\n")
        out += '\n'.join(_size_lines(rec, S)) + '\n'
        return out
    out += (f"**Budget about {E:.0f} epochs** "
            f"({E / R:.1f} epochs per round over {R:.0f} rounds).\n\n")
    out += '\n'.join(_schedule_lines(rec, S, E)) + '\n'
    return out


def _sparsity(rec, E, A):
    S = rec.max_sparsity(E, A)
    out = f"## How far can you prune with {E:g} epochs while keeping {A:.1f}%?\n\n"
    if S is None:
        A0 = rec.predict_accuracy(rec.s_lo, E)
        out += (f"**Even the gentlest calibrated sparsity ({_pct(rec.s_lo)}) cannot hold "
                f"{A:.1f}% with this budget** (best is {A0:.1f}%).\n\n"
                f"Raise the budget or lower the target accuracy.\n")
        return out
    keep, comp = _density(S)
    out += (f"**You can prune up to about {_pct(S)}** and still hold {A:.1f}% "
            f"(keeps {keep:.2g}% of weights, about {comp:.0f}x smaller).\n\n")
    out += '\n'.join(_schedule_lines(rec, S, E)
                     + _accuracy_lines(rec, S, E)[1]) + '\n'
    return out


def _three(rec, S, E, A):
    A_pred = rec.predict_accuracy(S, E)
    out = f"## Can you hit {_pct(S)} sparsity, {E:g} epochs, and {A:.1f}% accuracy?\n\n"
    out += _range_warning(rec, S)
    if A_pred >= A:
        out += (f"**Yes, feasible.** Predicted {A_pred:.2f}% beats the {A:.1f}% "
                f"target (margin +{A_pred - A:.2f} pts).\n\n")
        out += '\n'.join(_schedule_lines(rec, S, E)) + '\n'
        return out
    out += (f"**Not feasible as specified.** Predicted only {A_pred:.2f}%, "
            f"{A - A_pred:.2f} pts short of {A:.1f}%.\n\n")
    out += '\n'.join(_schedule_lines(rec, S, E)) + '\n\n'
    out += "**To make it work, change exactly one target:**\n\n"
    out += f"- *Accept lower accuracy:* {A_pred:.2f}% at this sparsity and budget.\n"
    E_req, note = rec.required_budget(S, A)
    if E_req is None:
        out += f"- *Spend more epochs:* will not help here ({note}).\n"
    else:
        out += (f"- *Spend more epochs:* about {E_req:.0f} epochs "
                f"(you asked for {E:g}).\n")
    S_max = rec.max_sparsity(E, A)
    if S_max is None:
        out += "- *Prune less:* not enough even at the gentlest sparsity.\n"
    else:
        out += (f"- *Prune less:* down to {_pct(S_max)} sparsity "
                f"(you asked for {_pct(S)}).\n")
    return out


# ── plots (log x-axis so the cliff / saturation are visible) ──────────────────
def _set_log_accuracy_axis(ax, rec, A=None):
    """Put accuracy on a log scale with plain-number ticks. The floor sits at the
    chance level, so the axis starts just below it (log cannot show 0)."""
    lo = rec.A_ch * 0.7
    hi = max(rec.A_ceil * 1.15, (A or 0) * 1.1)
    ax.set_yscale('log')
    ax.set_ylim(lo, hi)
    ticks = [t for t in (1, 2, 5, 10, 20, 30, 50, 70, 100) if lo <= t <= hi]
    ax.yaxis.set_major_locator(FixedLocator(ticks))
    ax.yaxis.set_minor_locator(FixedLocator([]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}'))


def _fig_cliff(rec, E, S=None, A=None):
    """Accuracy as the model is pruned harder, at the given budget. The x-axis is
    the fraction of weights kept on a log scale and is inverted so that moving
    right means more aggressive pruning; the cliff then appears as a clear drop."""
    # Sample density (weights kept %) log-uniformly, not sparsity linearly: the
    # cliff lives in a thin sliver of sparsity near 1.0, so linear-in-sparsity
    # sampling puts only 2-3 points across the drop and the smooth sigmoid renders
    # as straight segments. Log-spaced density gives the transition plenty of points.
    d_hi = (1.0 - rec.s_lo) * 100.0
    d_lo = max((1.0 - rec.s_hi) * 100.0, 1e-2)
    xs = _geomspace(d_lo, d_hi, 400)              # weights kept (%)
    ys = [rec.predict_accuracy(1.0 - d / 100.0, E) for d in xs]
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    ax.plot(xs, ys, color=BLUE, lw=2, label='predicted accuracy')
    ax.axhline(rec.A_ceil, color=GREEN, ls='--', lw=1, label=f'best {rec.A_ceil:.1f}%')
    ax.axhline(rec.A_ch, color=RED, ls=':', lw=1, label=f'random {rec.A_ch:.1f}%')
    if A is not None:
        ax.axhline(A, color=PURPLE, ls='-.', lw=1, label=f'target {A:.1f}%')
    if S is not None:
        keep = (1.0 - S) * 100.0
        A_pt = rec.predict_accuracy(S, E)
        ax.plot([keep], [A_pt], 'o', color=ORANGE, ms=9, zorder=5,
                label=f'you: {_pct(S)} sparse -> {A_pt:.1f}%')
    ax.set_xscale('log')
    ax.invert_xaxis()                              # right = fewer weights = more pruning
    ax.set_xlabel('weights kept (% of dense, log scale); more pruning to the right')
    ax.set_ylabel('accuracy (%, log scale)')
    ax.set_title(f'How accuracy falls as you prune harder ({E:g} epochs)')
    _set_log_accuracy_axis(ax, rec, A)
    ax.legend(fontsize=7, loc='lower left')
    ax.grid(True, which='both', alpha=0.3)
    fig.tight_layout()
    return fig


def _fig_budget(rec, S, E=None, A=None):
    """Accuracy as a function of the total fine-tuning budget at the given sparsity,
    on a log epoch axis, with the under-trained (<1 epoch/round) and capped
    (>5 epochs/round) regions shaded so the useful budget range is obvious."""
    R = rec.rounds(S)
    e_lo, e_cap = rec.f_lo * R, rec.f_cap * R
    e_hi = max(e_cap * 1.8, (E or 0) * 1.2, e_lo * 8)
    e_start = max(0.3, e_lo * 0.15)
    xs = _geomspace(e_start, e_hi, 240)
    ys = [rec.predict_accuracy(S, e) for e in xs]
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    ax.plot(xs, ys, color=BLUE, lw=2, label='predicted accuracy')
    ax.axhline(rec.A_ceil, color=GREEN, ls='--', lw=1, label=f'best {rec.A_ceil:.1f}%')
    if A is not None:
        ax.axhline(A, color=PURPLE, ls='-.', lw=1, label=f'target {A:.1f}%')
    if e_lo > e_start:
        ax.axvspan(e_start, e_lo, color='#ffe0b2', alpha=0.6,
                   label='too little (<1 ep/round)')
    if e_cap < e_hi:
        ax.axvspan(e_cap, e_hi, color='#d9d9d9', alpha=0.6,
                   label='no extra gain (>5 ep/round)')
    if E is not None and E > 0:
        A_pt = rec.predict_accuracy(S, E)
        ax.plot([E], [A_pt], 'o', color=ORANGE, ms=9, zorder=5,
                label=f'you: {E:g} ep -> {A_pt:.1f}%')
    ax.set_xscale('log')
    ax.set_xlabel('total fine-tuning epochs (log scale)')
    ax.set_ylabel('accuracy (%, log scale)')
    ax.set_title(f'Does more fine-tuning help? (at {_pct(S)} sparsity)')
    _set_log_accuracy_axis(ax, rec, A)
    ax.legend(fontsize=7, loc='lower right')
    ax.grid(True, which='both', alpha=0.3)
    fig.tight_layout()
    return fig


def _plots(rec, S, E, A):
    """Draw whichever plots the inputs support, deriving a sensible E or S for the
    operating point when only one of them was supplied."""
    if E is None and S is not None and A is not None:
        E_req, _ = rec.required_budget(S, A)
        E = E_req if E_req else rec.f_cap * rec.rounds(S)
    if S is None and E is not None and A is not None:
        S = rec.max_sparsity(E, A) or rec.s_lo
    fig_cliff = _fig_cliff(rec, E, S, A) if (E is not None and E > 0) else None
    fig_budget = _fig_budget(rec, S, E, A) if S is not None else None
    return fig_cliff, fig_budget


# ── validation + dispatch ────────────────────────────────────────────────────
def _validate(sparsity, epochs, accuracy):
    errs = []
    if sparsity is not None and not (0.0 < sparsity < 100.0):
        errs.append("Target sparsity must be between 0 and 100 (exclusive).")
    if epochs is not None and epochs <= 0:
        errs.append("Fine-tuning budget must be a positive number of epochs.")
    if accuracy is not None and not (0.0 < accuracy <= 100.0):
        errs.append("Target accuracy must be between 0 and 100.")
    return errs


def query(rec, S, E, A):
    n = sum(x is not None for x in (S, E, A))
    if n == 3:
        return _three(rec, S, E, A)
    if S is not None and E is not None:
        return _predict(rec, S, E)
    if S is not None and A is not None:
        return _budget(rec, S, A)
    return _sparsity(rec, E, A)


def _none_if_empty(v):
    """Gradio may send 0 or NaN for cleared Number fields; treat as 'not given'."""
    if v is None:
        return None
    try:
        if v != v:  # NaN
            return None
    except Exception:
        pass
    return None if v == 0 else v


def compute(network, criterion, sparsity, epochs, accuracy):
    """Top-level callback: validate, answer in words, and draw the two plots."""
    sparsity = _none_if_empty(sparsity)
    epochs = _none_if_empty(epochs)
    accuracy = _none_if_empty(accuracy)
    errs = _validate(sparsity, epochs, accuracy)
    if errs:
        return "**Please fix:**\n\n" + '\n'.join(f"- {e}" for e in errs), None, None

    S = sparsity / 100.0 if sparsity is not None else None
    E = epochs
    A = accuracy
    if sum(x is not None for x in (S, E, A)) < 2:
        return ("Fill **at least two** of the three fields. Two fields solve for the "
                "third; all three run a feasibility check. For example, give a target "
                "sparsity and a budget to predict the accuracy."), None, None

    rec = Recommender(network, criterion)
    text = query(rec, S, E, A)
    fig_cliff, fig_budget = _plots(rec, S, E, A)
    return text, fig_cliff, fig_budget


def on_network_change(network):
    crits = criteria_for(network)
    return (gr.Dropdown(choices=crits, value=crits[0]),
            info_panel(network, crits[0]))


def on_criterion_change(network, criterion):
    return info_panel(network, criterion)


with gr.Blocks(title='Pruning-schedule recommender') as demo:
    gr.Markdown(
        "# Pruning-schedule recommender\n"
        "From the thesis *Automatic Parameter Selection for Neural Network "
        "Pruning*. Pick a network and an importance criterion, then fill **any two** "
        "of the three boxes below to solve for the third, or **all three** to check "
        "whether a plan is feasible.\n\n"
        "- **Target sparsity** -- how much of the network you want to remove.\n"
        "- **Fine-tuning budget** -- total epochs of retraining you can afford "
        "(spread across the pruning rounds).\n"
        "- **Target accuracy** -- the accuracy you need to keep.\n\n"
        "No GPU or training is needed: every answer comes from a calibrated formula."
    )

    with gr.Row():
        net = gr.Dropdown(NETWORKS, value=NETWORKS[0], label='Network')
        crit = gr.Dropdown(criteria_for(NETWORKS[0]),
                           value=criteria_for(NETWORKS[0])[0], label='Criterion')

    info = gr.Markdown(info_panel(NETWORKS[0], criteria_for(NETWORKS[0])[0]))

    with gr.Row():
        s_in = gr.Number(label='Target sparsity (%)', value=None,
                         info='e.g. 95 = remove 95% of weights')
        e_in = gr.Number(label='Fine-tuning budget (total epochs)', value=None,
                         info='total retraining epochs across all rounds')
        a_in = gr.Number(label='Target accuracy (%)', value=None,
                         info='accuracy you need to keep')

    run = gr.Button('Compute', variant='primary')
    out = gr.Markdown()

    with gr.Row():
        plot_cliff = gr.Plot(label='Accuracy vs how hard you prune')
        plot_budget = gr.Plot(label='Accuracy vs fine-tuning budget')

    net.change(on_network_change, inputs=net, outputs=[crit, info])
    crit.change(on_criterion_change, inputs=[net, crit], outputs=info)
    run.click(compute, inputs=[net, crit, s_in, e_in, a_in],
              outputs=[out, plot_cliff, plot_budget])

    gr.Examples(
        examples=[
            ['lenet', 'magnitude', 95, 50, None],
            ['lenet', 'magnitude', 99, None, 95],
            ['vgg19', 'taylor', 90, None, 80],
            ['resnet50', 'magnitude', 99, 30, 92],
        ],
        inputs=[net, crit, s_in, e_in, a_in],
    )


if __name__ == '__main__':
    demo.launch()
