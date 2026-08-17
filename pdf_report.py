"""
Generazione del PDF riassuntivo del portafoglio.

Usa solo matplotlib (PdfPages) per restare compatibile con Streamlit Cloud senza
dipendenze di sistema. Le figure ricalcano i grafici dell'interfaccia a partire
dal PortfolioModel gia calcolato.
"""

from __future__ import annotations
from datetime import datetime
import io
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import LinearSegmentedColormap
import matplotlib.dates as mdates

ACCENT = "#1B3A6B"
DD_COL = "#C02637"
INK = "#101720"
MUTED = "#5A6672"
CMAP_DIV = LinearSegmentedColormap.from_list("gr", ["#15803D", "#E9EDF1", "#C02637"])

plt.rcParams.update({
    "font.size": 8,
    "axes.edgecolor": "#C4CCD4",
    "axes.linewidth": 0.6,
    "axes.titlesize": 9,
    "axes.titleweight": "bold",
    "axes.titlecolor": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "text.color": INK,
})


def _fmt(x, d=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:,.{d}f}"


def _grid_intensity(times, series, n=520):
    """Campiona una serie di drawdown a passo (step) su una griglia regolare."""
    t = times.astype("datetime64[ns]").astype(np.int64)
    g = np.linspace(t[0], t[-1], n)
    idx = np.searchsorted(t, g, side="right") - 1
    idx = np.clip(idx, 0, len(series) - 1)
    return series[idx], g


def _table(ax, col_labels, cell_rows, col_w=None, header_bg="#EEF1F5",
           neg_cols=None, right_align=True):
    ax.axis("off")
    tbl = ax.table(cellText=cell_rows, colLabels=col_labels,
                   cellLoc="right" if right_align else "left", loc="center",
                   colWidths=col_w)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7.2)
    tbl.scale(1, 1.35)
    neg_cols = neg_cols or set()
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#E1E6EB")
        cell.set_linewidth(0.5)
        if r == 0:
            cell.set_facecolor(header_bg)
            cell.set_text_props(weight="bold", color=INK)
            cell.set_text_props(ha="right" if right_align else "left")
        else:
            if c == 0:
                cell.set_text_props(ha="left")
            txt = cell.get_text().get_text()
            if c in neg_cols and txt.strip().startswith("-"):
                cell.set_text_props(color=DD_COL)
    return tbl


def _date_axis(ax):
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
    for lbl in ax.get_xticklabels():
        lbl.set_fontsize(7)


def build_pdf(m, cap, subtitle: str = "") -> bytes:
    buf = io.BytesIO()
    xt = m.times.astype("datetime64[ms]").astype("O")
    overlap_pct = m.t_overlap_ms / m.span_ms * 100 if m.span_ms else 0
    port_dd_time = m.t_port_ms / m.span_ms * 100 if m.span_ms else 0

    with PdfPages(buf) as pdf:

        # ---------------- pagina 1: sintesi e metriche
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.subplots_adjust(left=0.06, right=0.94, top=0.95, bottom=0.05,
                            hspace=0.55)
        gs = fig.add_gridspec(3, 1, height_ratios=[0.9, 1.2, 2.4])

        head = fig.add_subplot(gs[0]); head.axis("off")
        head.text(0, 0.9, "Portfolio Lab", fontsize=20, fontweight="bold",
                  color=INK, va="top")
        head.text(0, 0.55, "Analisi combinata di backtest MT4 / MT5",
                  fontsize=9, color=MUTED, va="top")
        info = subtitle or f"Generato il {datetime.now():%d.%m.%Y %H:%M}"
        head.text(0, 0.3, info, fontsize=8, color=MUTED, va="top")

        kpi = [
            ("Profitto netto", _fmt(m.port_stats["net"])),
            (f"Max drawdown ({m.port_dd_stats[1]:.2f}%)",
             "-" + _fmt(m.port_dd_stats[0])),
            ("DD sommato singole", _fmt(m.sum_dd)),
            ("Beneficio diversif.", f"{m.diversification_benefit:.1f}%"),
            ("Recovery factor", _fmt(m.recovery_factor)),
            ("Profit factor", _fmt(m.port_stats["pf"])),
            ("Operazioni vincenti", f"{m.port_stats['win_rate']:.1f}%"),
            ("Tempo in drawdown", f"{port_dd_time:.1f}%"),
            ("DD simultanei", f"{overlap_pct:.1f}%"),
            ("Capitale iniziale", _fmt(cap)),
        ]
        kax = fig.add_subplot(gs[1]); kax.axis("off")
        cols = 5
        for i, (k, v) in enumerate(kpi):
            cx = (i % cols) / cols
            cy = 0.85 - (i // cols) * 0.5
            kax.text(cx, cy, k.upper(), fontsize=6.4, color=MUTED, va="top")
            kax.text(cx, cy - 0.14, v, fontsize=11, fontweight="bold",
                     color=INK, va="top")

        # tabella metriche per strategia
        rows = []
        for e in m.each:
            rows.append([
                e["name"][:22], _fmt(e["net"]), str(e["n"]),
                f"{e['win_rate']:.1f}", _fmt(e["pf"]),
                "-" + _fmt(e["max_dd"]), f"-{e['max_dd_pct']:.2f}",
                f"{e['longest_dd'] / np.timedelta64(1, 'D'):.0f}",
                _fmt(e["rf"]),
            ])
        rows.append([
            "Portafoglio", _fmt(m.port_stats["net"]), str(m.port_stats["n"]),
            f"{m.port_stats['win_rate']:.1f}", _fmt(m.port_stats["pf"]),
            "-" + _fmt(m.port_dd_stats[0]), f"-{m.port_dd_stats[1]:.2f}",
            f"{m.port_dd_stats[2] / np.timedelta64(1, 'D'):.0f}",
            _fmt(m.recovery_factor),
        ])
        tax = fig.add_subplot(gs[2])
        tax.set_title("Metriche per strategia", loc="left", pad=12)
        _table(tax,
               ["Strategia", "Netto", "Op.", "Win%", "PF", "Max DD",
                "DD %", "DD gg", "Recovery"],
               rows,
               col_w=[0.24, 0.13, 0.06, 0.08, 0.08, 0.13, 0.09, 0.07, 0.10],
               neg_cols={1, 5, 6})
        pdf.savefig(fig); plt.close(fig)

        # ---------------- pagina 2: equity e underwater
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.27, 11.69))
        fig.subplots_adjust(left=0.09, right=0.95, top=0.94, bottom=0.07,
                            hspace=0.22)

        for j, name in enumerate(m.strat_names):
            ax1.plot(xt, m.strat_equity[j], lw=0.8, color=m.strat_colors[j],
                     alpha=0.85, label=name)
        ax1.plot(xt, m.port_equity, lw=1.8, color=ACCENT, label="Portafoglio")
        ax1.axhline(cap, lw=0.8, ls=":", color="#9AA4AE")
        ax1.set_title("Curve di equity", loc="left")
        ax1.legend(fontsize=6.5, loc="upper left", frameon=False, ncol=2)
        ax1.grid(True, color="#EDF0F3", lw=0.6)
        _date_axis(ax1)

        ax2.fill_between(xt, m.port_dd, 0, color=DD_COL, alpha=0.14)
        ax2.plot(xt, m.port_dd, lw=1.4, color=DD_COL, label="Portafoglio")
        for j, name in enumerate(m.strat_names):
            ax2.plot(xt, m.strat_dd[j], lw=0.7, color=m.strat_colors[j],
                     alpha=0.7, label=name)
        ax2.set_title("Underwater - distanza dal picco (%)", loc="left")
        ax2.legend(fontsize=6.5, loc="lower left", frameon=False, ncol=2)
        ax2.grid(True, color="#EDF0F3", lw=0.6)
        _date_axis(ax2)
        pdf.savefig(fig); plt.close(fig)

        # ---------------- pagina 3: sovrapposizione, correlazione, mensile
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.subplots_adjust(left=0.09, right=0.95, top=0.94, bottom=0.06)
        gs = fig.add_gridspec(3, 1, height_ratios=[1.1, 1.3, 2.0], hspace=0.4)

        # banda sovrapposizione drawdown
        bax = fig.add_subplot(gs[0])
        rows_lbl = m.strat_names + ["PORTAFOGLIO"]
        dd_stack = m.strat_dd + [m.port_dd]
        img = []
        for sd in dd_stack:
            samp, g = _grid_intensity(m.times, sd)
            worst = min(samp.min(), -1e-9)
            img.append(np.clip(-samp / -worst, 0, 1))
        img = np.array(img)
        extent = [mdates.date2num(xt[0]), mdates.date2num(xt[-1]),
                  0, len(rows_lbl)]
        bax.imshow(img[::-1], aspect="auto", extent=extent,
                   cmap=LinearSegmentedColormap.from_list(
                       "dd", ["#F4F6F8", DD_COL]), vmin=0, vmax=1)
        bax.set_yticks(np.arange(len(rows_lbl)) + 0.5)
        bax.set_yticklabels(rows_lbl[::-1], fontsize=6.5)
        bax.xaxis_date()
        bax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
        bax.set_title("Sovrapposizione dei drawdown", loc="left")
        for lbl in bax.get_xticklabels():
            lbl.set_fontsize(7)

        # correlazione
        cax = fig.add_subplot(gs[1])
        n = len(m.strat_names)
        im = cax.imshow(m.corr, cmap=CMAP_DIV, vmin=-1, vmax=1, aspect="auto")
        cax.set_xticks(range(n)); cax.set_yticks(range(n))
        cax.set_xticklabels([str(i + 1) for i in range(n)], fontsize=7)
        cax.set_yticklabels([f"{i+1}. {nm[:16]}" for i, nm in
                             enumerate(m.strat_names)], fontsize=7)
        for i in range(n):
            for j in range(n):
                v = m.corr[i, j]
                cax.text(j, i, "-" if np.isnan(v) else f"{v:.2f}",
                         ha="center", va="center", fontsize=7,
                         color="#101720" if abs(v) < 0.6 else "#ffffff")
        cax.set_title("Correlazione P/L mensile", loc="left")
        fig.colorbar(im, ax=cax, fraction=0.025, pad=0.02)

        # tabella mensile
        mx = fig.add_subplot(gs[2])
        mx.set_title("P/L mensile", loc="left", pad=12)
        head_lbls = ["Mese"] + [nm[:12] for nm in m.strat_names] + ["Portaf."]
        cell = []
        for mi, mo in enumerate(m.months):
            r = [mo] + [f"{m.monthly[j, mi]:,.0f}" for j in range(n)]
            r.append(f"{m.monthly_port[mi]:,.0f}")
            cell.append(r)
        neg = {c for c in range(1, n + 2)}
        _table(mx, head_lbls, cell, neg_cols=neg)
        pdf.savefig(fig); plt.close(fig)

    buf.seek(0)
    return buf.getvalue()
