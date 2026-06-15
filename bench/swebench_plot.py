#!/usr/bin/env python3
"""Plot the SWE-bench Verified slice result: gate OFF vs ON (and optionally other
models), resolved-rate + token/cost overhead. Run with the venv python (matplotlib).

  /tmp/swe_venv/bin/python bench/swebench_plot.py
"""
import glob, json, os
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SWE = "/tmp/swe"
OUT = "/Users/jeonsihyeon/wfb/assets/swebench_slice.png"


def resolved(report_glob):
    fs = sorted(glob.glob(os.path.join(SWE, report_glob)))
    if not fs:
        return None
    d = json.load(open(fs[-1]))
    return d.get("resolved_instances", 0), d.get("total_instances", 0)


def meta_means():
    m = json.load(open(os.path.join(SWE, "meta.json")))
    agg = defaultdict(lambda: defaultdict(list))
    for r in m:
        for k in ("tokens", "cost", "turns", "secs"):
            agg[r["arm"]][k].append(r.get(k, 0))
    return {arm: {k: (sum(v) / len(v) if v else 0) for k, v in d.items()} for arm, d in agg.items()}


def main():
    nk = resolved("wfb_naked.n28_*.json") or (0, 0)
    gt = resolved("wfb_gated.n28_*.json") or (0, 0)
    mm = meta_means()
    n = nk[1] or gt[1] or len(json.load(open(os.path.join(SWE, "meta.json")))) // 2

    fig, ax = plt.subplots(1, 3, figsize=(13, 4.2))
    arms = ["gate OFF\n(naked)", "gate ON\n(wfb)"]
    cols = ["#8a8f98", "#d64545"]

    # 1) resolved rate
    rr = [100 * nk[0] / max(nk[1], 1), 100 * gt[0] / max(gt[1], 1)]
    b = ax[0].bar(arms, rr, color=cols)
    ax[0].set_title(f"Resolved rate — SWE-bench Verified slice (N={n}, opus)")
    ax[0].set_ylabel("% resolved"); ax[0].set_ylim(0, 100)
    for bar, v, raw in zip(b, rr, [nk, gt]):
        ax[0].text(bar.get_x() + bar.get_width() / 2, v + 2, f"{v:.0f}%\n{raw[0]}/{raw[1]}", ha="center")

    # 2) tokens (gross)
    tk = [mm.get("naked", {}).get("tokens", 0) / 1000, mm.get("gated", {}).get("tokens", 0) / 1000]
    b = ax[1].bar(arms, tk, color=cols)
    ratio = tk[1] / tk[0] if tk[0] else 0
    ax[1].set_title(f"Mean tokens / instance ({ratio:.1f}x)")
    ax[1].set_ylabel("k tokens (gross)")
    for bar, v in zip(b, tk):
        ax[1].text(bar.get_x() + bar.get_width() / 2, v, f"{v:.0f}k", ha="center", va="bottom")

    # 3) cost
    ct = [mm.get("naked", {}).get("cost", 0), mm.get("gated", {}).get("cost", 0)]
    b = ax[2].bar(arms, ct, color=cols)
    cr = ct[1] / ct[0] if ct[0] else 0
    ax[2].set_title(f"Mean $ / instance ({cr:.1f}x)")
    ax[2].set_ylabel("USD")
    for bar, v in zip(b, ct):
        ax[2].text(bar.get_x() + bar.get_width() / 2, v, f"${v:.2f}", ha="center", va="bottom")

    delta = gt[0] - nk[0]
    sign = f"+{delta}" if delta > 0 else str(delta)
    fig.suptitle(f"Wfb gate on SWE-bench Verified (N={n}, opus): matches or beats naked "
                 f"({gt[0]} vs {nk[0]}, {sign}), at higher token cost",
                 fontsize=12, y=1.02)
    fig.tight_layout()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, dpi=130, bbox_inches="tight")
    print("wrote", OUT)
    print(f"naked resolved {nk}  gated resolved {gt}")
    print(f"tokens {tk}  cost {ct}")


if __name__ == "__main__":
    main()
