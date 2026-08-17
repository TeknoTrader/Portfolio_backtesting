"""
Calcolo delle metriche di portafoglio a partire dalle operazioni normalizzate.

Convenzione: le operazioni di ogni strategia vengono pesate e unite in un unico
flusso ordinato per tempo. L'equity e i drawdown sono ricostruiti evento per
evento sia per il portafoglio sia per ogni singola strategia sullo stesso asse
temporale, in modo da poter confrontare le sovrapposizioni.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class Strategy:
    name: str
    trades: pd.DataFrame          # colonne time, pnl (già filtrato per periodo)
    weight: float
    color: str


def _drawdown_series(equity: np.ndarray) -> np.ndarray:
    """Distanza percentuale dal picco precedente, valori <= 0."""
    peak = np.maximum.accumulate(equity)
    return (equity - peak) / peak * 100.0


def _dd_stats(equity: np.ndarray, times: np.ndarray):
    """Max drawdown assoluto, percentuale e durata piu lunga in ms."""
    peak = equity[0]
    t_peak = times[0]
    max_abs = 0.0
    max_pct = 0.0
    longest = np.timedelta64(0, "ns")
    for eq, t in zip(equity, times):
        if eq >= peak:
            longest = max(longest, t - t_peak)
            peak, t_peak = eq, t
        else:
            max_abs = max(max_abs, peak - eq)
            max_pct = max(max_pct, (peak - eq) / peak * 100.0)
    longest = max(longest, times[-1] - t_peak)
    return max_abs, max_pct, longest


def _trade_stats(pnl: np.ndarray) -> dict:
    gp = pnl[pnl >= 0].sum()
    gl = -pnl[pnl < 0].sum()
    wins = int((pnl > 0).sum())
    n = len(pnl)
    return {
        "net": float(pnl.sum()),
        "gross_profit": float(gp),
        "gross_loss": float(gl),
        "pf": float(gp / gl) if gl > 0 else (np.inf if gp > 0 else 0.0),
        "win_rate": (wins / n * 100.0) if n else 0.0,
        "n": n,
        "avg": float(pnl.mean()) if n else 0.0,
    }


@dataclass
class PortfolioModel:
    cap: float
    times: np.ndarray              # asse temporale degli eventi (con punto zero iniziale)
    port_equity: np.ndarray
    strat_equity: list[np.ndarray]
    port_dd: np.ndarray
    strat_dd: list[np.ndarray]
    strat_names: list[str]
    strat_colors: list[str]
    port_stats: dict
    port_dd_stats: tuple
    each: list[dict]
    months: list[str]
    monthly: np.ndarray            # righe = strategie, colonne = mesi
    monthly_port: np.ndarray
    corr: np.ndarray
    span_ms: float
    t_overlap_ms: float
    t_any_ms: float
    t_port_ms: float
    sum_dd: float

    @property
    def recovery_factor(self):
        md = self.port_dd_stats[0]
        return self.port_stats["net"] / md if md > 0 else np.inf

    @property
    def diversification_benefit(self):
        return (1 - self.port_dd_stats[0] / self.sum_dd) * 100.0 if self.sum_dd > 0 else 0.0


def build_model(strategies: list[Strategy], cap: float) -> PortfolioModel | None:
    active = [s for s in strategies if len(s.trades) > 0 and s.weight > 0]
    if not active:
        return None

    # flusso unico di eventi pesati
    frames = []
    for i, s in enumerate(active):
        d = s.trades.copy()
        d["pnl"] = d["pnl"] * s.weight
        d["si"] = i
        frames.append(d[["time", "pnl", "si"]])
    ev = pd.concat(frames).sort_values("time").reset_index(drop=True)
    if ev.empty:
        return None

    k = len(active)
    t0 = ev["time"].iloc[0] - pd.Timedelta(days=1)
    times = np.concatenate([[np.datetime64(t0)], ev["time"].values.astype("datetime64[ns]")])

    # equity cumulata per strategia e portafoglio
    cum = np.zeros(k)
    strat_eq = [np.empty(len(times)) for _ in range(k)]
    port_eq = np.empty(len(times))
    for j in range(k):
        strat_eq[j][0] = cap
    port_eq[0] = cap
    for row_i, (pnl, si) in enumerate(zip(ev["pnl"].values, ev["si"].values), start=1):
        cum[si] += pnl
        for j in range(k):
            strat_eq[j][row_i] = cap + cum[j]
        port_eq[row_i] = cap + cum.sum()

    port_dd = _drawdown_series(port_eq)
    strat_dd = [_drawdown_series(e) for e in strat_eq]

    port_stats = _trade_stats(ev["pnl"].values)
    port_dd_stats = _dd_stats(port_eq, times)

    each = []
    for j, s in enumerate(active):
        pnl = ev.loc[ev["si"] == j, "pnl"].values
        st = _trade_stats(pnl)
        dd_abs, dd_pct, longest = _dd_stats(strat_eq[j], times)
        st.update({
            "name": s.name,
            "color": s.color,
            "max_dd": dd_abs,
            "max_dd_pct": dd_pct,
            "longest_dd": longest,
            "rf": (st["net"] / dd_abs) if dd_abs > 0 else np.inf,
        })
        each.append(st)

    # P/L mensile per strategia
    ev["month"] = ev["time"].dt.to_period("M").astype(str)
    months = sorted(ev["month"].unique())
    monthly = np.zeros((k, len(months)))
    for j in range(k):
        g = ev[ev["si"] == j].groupby("month")["pnl"].sum()
        for mi, m in enumerate(months):
            monthly[j, mi] = g.get(m, 0.0)
    monthly_port = monthly.sum(axis=0)

    # correlazione sui rendimenti mensili
    if k >= 2 and len(months) >= 3:
        corr = np.corrcoef(monthly)
    else:
        corr = np.full((k, k), np.nan)
        np.fill_diagonal(corr, 1.0)

    # tempo in drawdown e sovrapposizioni
    dt = np.diff(times).astype("timedelta64[ns]").astype(np.float64)
    span = dt.sum()
    below = np.array([sd[1:] < -1e-4 for sd in strat_dd])  # (k, n-1)
    count = below.sum(axis=0)
    t_any = dt[count > 0].sum()
    t_overlap = dt[count > 1].sum()
    t_port = dt[port_dd[1:] < -1e-4].sum()
    sum_dd = sum(e["max_dd"] for e in each)

    return PortfolioModel(
        cap=cap, times=times, port_equity=port_eq, strat_equity=strat_eq,
        port_dd=port_dd, strat_dd=strat_dd,
        strat_names=[s.name for s in active], strat_colors=[s.color for s in active],
        port_stats=port_stats, port_dd_stats=port_dd_stats, each=each,
        months=months, monthly=monthly, monthly_port=monthly_port, corr=corr,
        span_ms=float(span), t_overlap_ms=float(t_overlap), t_any_ms=float(t_any),
        t_port_ms=float(t_port), sum_dd=sum_dd,
    )
