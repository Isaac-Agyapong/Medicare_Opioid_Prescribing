"""Shared matplotlib styling so every chart in the project looks consistent."""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, PercentFormatter

# Categorical slots, always assigned in this order (never cycled).
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
SERIES = [BLUE, ORANGE, AQUA]
NEUTRAL = "#c3c2b7"          # de-emphasised bars
SURFACE = "#fcfcfb"
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"

IMAGE_DIR = Path(__file__).resolve().parents[1] / "Image"
IMAGE_DIR.mkdir(exist_ok=True)


def apply():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "figure.dpi": 110, "savefig.dpi": 150, "figure.figsize": (9, 4.6),
        "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10,
        "text.color": INK, "axes.labelcolor": INK_2, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.edgecolor": NEUTRAL, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.axisbelow": True, "axes.titlesize": 13, "axes.titleweight": "semibold",
        "axes.titlelocation": "left", "axes.titlepad": 26,
        "legend.frameon": False, "lines.linewidth": 2,
        "xtick.major.size": 0, "ytick.major.size": 0,
    })


def subtitle(ax, text):
    """Grey one-line takeaway under the title."""
    ax.text(0, 1.02, text, transform=ax.transAxes, color=INK_2, fontsize=9.5, va="bottom")


def money(ax, axis="y"):
    fmt = FuncFormatter(lambda v, _: f"${v/1e6:,.1f}M" if abs(v) >= 1e6 else f"${v/1e3:,.0f}K")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def pct(ax, axis="y", decimals=0):
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(PercentFormatter(1, decimals=decimals))


def save(fig, name):
    fig.tight_layout()
    fig.savefig(IMAGE_DIR / f"{name}.png", bbox_inches="tight")
