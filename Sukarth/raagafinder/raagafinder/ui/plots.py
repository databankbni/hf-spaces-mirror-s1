"""'Show your work' plot: the recording's pitch-class distribution overlaid
with the predicted raga's training-average PCD, with swara ticks."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SWARA_POS = list(range(0, 1200, 100))
SWARA_LABELS = ["S", "R₁", "R₂", "G₂", "G₃", "M₁", "M₂", "P", "D₁", "D₂", "N₂", "N₃"]


def pcd_overlay_figure(pcd: np.ndarray, template: np.ndarray | None, raga_name: str):
    fig, ax = plt.subplots(figsize=(8.5, 3.2), dpi=110)
    x = np.linspace(0, 1200, len(pcd), endpoint=False)
    ax.fill_between(x, pcd, color="#4C72B0", alpha=0.55, linewidth=0,
                    label="Your recording")
    if template is not None:
        xt = np.linspace(0, 1200, len(template), endpoint=False)
        ax.plot(xt, template, color="#C44E52", linewidth=1.8,
                label=f"{raga_name} — training average")
    ax.set_xticks(SWARA_POS)
    ax.set_xticklabels(SWARA_LABELS)
    ax.set_xlim(0, 1200)
    ax.set_ylim(bottom=0)
    ax.set_yticks([])
    ax.set_xlabel("pitch class (relative to detected tonic Sa)")
    ax.set_ylabel("time spent")
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    for pos in SWARA_POS:
        ax.axvline(pos, color="#000000", alpha=0.06, linewidth=0.8)
    fig.tight_layout()
    return fig
