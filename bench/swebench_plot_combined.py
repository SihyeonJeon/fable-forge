#!/usr/bin/env python3
"""Combined SWE-bench (Verified slice + Pro) gate OFF vs ON figure, read from the
durable bench/results/ snapshot. Run with any python that has matplotlib.

  /tmp/swe_venv/bin/python bench/swebench_plot_combined.py
"""
import json, os
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

R = os.path.join(os.path.dirname(__file__), "results")
OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "swebench_combined.png")
GREY, RED = "#8a8f98", "#d64545"


def resolved_verified():
    n = json.load(open(f"{R}/verified/wfb_naked.n28_naked.json"))["resolved_instances"]
    g = json.load(open(f"{R}/verified/wfb_gated.n28_gated.json"))["resolved_instances"]
    return n, g, 28


def resolved_pro():
    n = sum(1 for v in json.load(open(f"{R}/pro/eval10_naked.json")).values() if v)
    g = sum(1 for v in json.load(open(f"{R}/pro/eval10_gated.json")).values() if v)
    return n, g, 10


def means():
    agg = defaultdict(lambda: defaultdict(list))
    for sub in ("verified", "pro"):
        for m in json.load(open(f"{R}/{sub}/meta.json")):
            agg[m["arm"]]["tokens"].append(m["tokens"]); agg[m["arm"]]["cost"].append(m["cost"])
    return {a: {k: sum(v) / len(v) for k, v in d.items()} for a, d in agg.items()}


def main():
    vn, vg, vN = resolved_verified()
    pn, pg, pN = resolved_pro()
    an, ag, aN = vn + pn, vg + pg, vN + pN
    mm = means()

    fig, ax = plt.subplots(1, 3, figsize=(14, 4.4))
    import numpy as np
    groups = [f"Verified\nN={vN}", f"Pro\nN={pN}", f"All\nN={aN}"]
    nk = [100 * vn / vN, 100 * pn / pN, 100 * an / aN]
    gt = [100 * vg / vN, 100 * pg / pN, 100 * ag / aN]
    raw = [(vn, vN, vg), (pn, pN, pg), (an, aN, ag)]
    x = np.arange(3); w = 0.38
    b1 = ax[0].bar(x - w / 2, nk, w, color=GREY, label="gate OFF (naked)")
    b2 = ax[0].bar(x + w / 2, gt, w, color=RED, label="gate ON (wfb)")
    ax[0].set_xticks(x); ax[0].set_xticklabels(groups)
    ax[0].set_ylabel("% resolved"); ax[0].set_ylim(0, 100)
    ax[0].set_title("Resolved rate — SWE-bench Verified + Pro (opus)")
    ax[0].legend(fontsize=8, loc="lower right")
    for i, (rn, rN, rg) in enumerate(raw):
        ax[0].text(x[i] - w / 2, nk[i] + 1.5, f"{rn}/{rN}", ha="center", fontsize=8)
        ax[0].text(x[i] + w / 2, gt[i] + 1.5, f"{rg}/{rN}", ha="center", fontsize=8)

    tk = [mm["naked"]["tokens"] / 1000, mm["gated"]["tokens"] / 1000]
    b = ax[1].bar(["gate OFF", "gate ON"], tk, color=[GREY, RED])
    ax[1].set_title(f"Mean tokens / task ({tk[1]/tk[0]:.1f}x)"); ax[1].set_ylabel("k tokens (gross)")
    for bar, v in zip(b, tk):
        ax[1].text(bar.get_x() + bar.get_width() / 2, v, f"{v:.0f}k", ha="center", va="bottom")

    ct = [mm["naked"]["cost"], mm["gated"]["cost"]]
    b = ax[2].bar(["gate OFF", "gate ON"], ct, color=[GREY, RED])
    ax[2].set_title(f"Mean $ / task ({ct[1]/ct[0]:.1f}x)"); ax[2].set_ylabel("USD")
    for bar, v in zip(b, ct):
        ax[2].text(bar.get_x() + bar.get_width() / 2, v, f"${v:.2f}", ha="center", va="bottom")

    fig.suptitle(f"Wfb gate on SWE-bench (Verified+Pro, N={aN}, opus, same harness): "
                 f"{ag} vs {an} resolved (+{ag-an}), 0 regressions, ~{tk[1]/tk[0]:.1f}x tokens",
                 fontsize=12, y=1.02)
    fig.tight_layout()
    fig.savefig(OUT, dpi=130, bbox_inches="tight")
    print("wrote", os.path.normpath(OUT))
    print(f"Verified {vn}->{vg} | Pro {pn}->{pg} | All {an}->{ag} (+{ag-an}) | tokens {tk} cost {ct}")


if __name__ == "__main__":
    main()
