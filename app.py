"""
Portfolio Lab - analisi combinata di piu backtest MetaTrader 4/5.

Avvio locale:
    streamlit run app.py

Carica i report XLSX/HTML/CSV, regola pesi e periodo, osserva come i drawdown
delle strategie si sommano o si compensano.
"""

from __future__ import annotations
import html as _html
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from parsing import parse_report
from metrics import Strategy, build_model
from pdf_report import build_pdf

PALETTE = ["#C2410C", "#0E7490", "#7C3AED", "#B45309", "#15803D",
           "#BE185D", "#0F766E", "#9333EA"]
ACCENT = "#1B3A6B"
DD_COL = "#C02637"

st.set_page_config(page_title="Portfolio Lab", page_icon="chart", layout="wide")

st.markdown("""
<style>
  .block-container{padding-top:1.6rem;padding-bottom:3rem;max-width:1500px}
  [data-testid="stMetricValue"]{font-variant-numeric:tabular-nums;font-size:1.35rem}
  [data-testid="stMetricLabel"]{font-size:.72rem;letter-spacing:.04em;text-transform:uppercase}
  h1{letter-spacing:-.01em}
  .stDataFrame{font-variant-numeric:tabular-nums}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- stato

if "reports" not in st.session_state:
    st.session_state.reports = {}   # filename -> dict(parsed, enabled, weight, color)


def ingest(files):
    for f in files:
        if f.name in st.session_state.reports:
            continue
        parsed = parse_report(f.name, f.getvalue())
        st.session_state.reports[f.name] = {
            "parsed": parsed,
            "enabled": parsed.warning is None,
            "weight": 1.0,
            "color": PALETTE[len(st.session_state.reports) % len(PALETTE)],
        }


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.title("Portfolio Lab")
    st.caption("Analisi combinata di backtest MT4 / MT5")

    up = st.file_uploader(
        "Report dei backtest",
        type=["xlsx", "xls", "html", "htm", "csv", "tsv", "txt"],
        accept_multiple_files=True,
        help="MT5 XLSX/HTML, MT4 HTM, oppure CSV con colonne tempo e profitto.",
    )
    if up:
        ingest(up)

    reports = st.session_state.reports

    if reports:
        # deposito iniziale suggerito dal primo report che lo espone
        dep = next((r["parsed"].initial_deposit for r in reports.values()
                    if r["parsed"].initial_deposit), 10000.0)
        st.divider()
        cap = st.number_input("Capitale iniziale", min_value=1.0,
                              value=float(dep), step=1000.0, format="%.2f")

        st.markdown("**Strategie**")
        for name, r in list(reports.items()):
            p = r["parsed"]
            c1, c2 = st.columns([0.72, 0.28])
            with c1:
                r["enabled"] = st.checkbox(
                    p.name, value=r["enabled"], key=f"en_{name}",
                    disabled=p.warning is not None,
                )
            with c2:
                r["weight"] = st.number_input(
                    "peso", min_value=0.0, value=float(r["weight"]), step=0.25,
                    key=f"w_{name}", label_visibility="collapsed",
                )
            if p.warning:
                st.caption(f":red[{name}: {p.warning}]")
            elif len(p.trades):
                a, b = p.trades.time.iloc[0], p.trades.time.iloc[-1]
                st.caption(f"{len(p.trades)} op. · {a:%d.%m.%Y} – {b:%d.%m.%Y}")
            if st.button("rimuovi", key=f"rm_{name}", type="tertiary"):
                del st.session_state.reports[name]
                st.rerun()

        st.divider()
        if st.button("Azzera tutto"):
            st.session_state.reports = {}
            st.rerun()
    else:
        cap = 10000.0


# ---------------------------------------------------------------- corpo

st.title("Portfolio Lab")

reports = st.session_state.reports
usable = [(fn, r) for fn, r in reports.items()
          if r["enabled"] and r["parsed"].warning is None and len(r["parsed"].trades)]

if not usable:
    st.info("Carica almeno un report dalla barra laterale. "
            "In MT5: Strategy Tester → tasto destro sul backtest → Report → salva in XLSX o HTML. "
            "In MT4: Strategy Tester → Results → Save as Report (htm).")
    st.stop()

# intervallo temporale complessivo e filtro periodo
all_times = pd.concat([r["parsed"].trades.time for _, r in usable])
tmin, tmax = all_times.min().date(), all_times.max().date()
dr = st.slider("Periodo analizzato", min_value=tmin, max_value=tmax,
               value=(tmin, tmax), format="DD.MM.YYYY")
d_from = pd.Timestamp(dr[0])
d_to = pd.Timestamp(dr[1]) + pd.Timedelta(days=1)


def unique_names(items):
    # nomi di visualizzazione univoci: al primo duplicato si aggancia il filename
    seen, out = {}, []
    for fn, r in items:
        base = r["parsed"].name or fn.rsplit(".", 1)[0]
        nm = base
        if nm in seen:
            nm = f"{base} · {fn.rsplit('.', 1)[0][:18]}"
        while nm in seen:
            seen[base] += 1
            nm = f"{base} ({seen[base]})"
        seen.setdefault(base, 1)
        seen[nm] = 1
        out.append(nm)
    return out


disp_names = unique_names(usable)
strategies = []
for (fn, r), nm in zip(usable, disp_names):
    p = r["parsed"]
    tr = p.trades[(p.trades.time >= d_from) & (p.trades.time < d_to)]
    strategies.append(Strategy(nm, tr.reset_index(drop=True), r["weight"], r["color"]))

model = build_model(strategies, cap)
if model is None:
    st.warning("Nessuna operazione nel periodo selezionato.")
    st.stop()

m = model


# ---------------------------------------------------------------- kpi

def fmt(x, d=2):
    return "-" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:,.{d}f}"

overlap_pct = m.t_overlap_ms / m.span_ms * 100 if m.span_ms else 0
port_dd_time = m.t_port_ms / m.span_ms * 100 if m.span_ms else 0

k = st.columns(4)
k[0].metric("Profitto netto", fmt(m.port_stats["net"]))
k[1].metric("Max drawdown", "-" + fmt(m.port_dd_stats[0]),
            delta=f"{m.port_dd_stats[1]:.2f}% sul picco", delta_color="off")
k[2].metric("DD sommato singole", fmt(m.sum_dd),
            delta=f"beneficio {m.diversification_benefit:.1f}%",
            delta_color="normal" if m.diversification_benefit >= 0 else "inverse")
k[3].metric("Recovery factor", fmt(m.recovery_factor))

k = st.columns(4)
k[0].metric("Profit factor", fmt(m.port_stats["pf"]))
k[1].metric("Operazioni vincenti", f"{m.port_stats['win_rate']:.1f}%")
k[2].metric("Tempo in drawdown", f"{port_dd_time:.1f}%")
k[3].metric("DD simultanei", f"{overlap_pct:.1f}%",
            delta="due o piu insieme", delta_color="off")

# esportazione PDF riassuntivo
names = " + ".join(m.strat_names)
subtitle = f"{names}  |  {dr[0]:%d.%m.%Y} - {dr[1]:%d.%m.%Y}"
try:
    pdf_bytes = build_pdf(m, cap, subtitle)
    st.download_button(
        "Scarica PDF riassuntivo", data=pdf_bytes,
        file_name=f"portfolio_lab_{dr[1]:%Y%m%d}.pdf",
        mime="application/pdf")
except Exception as exc:
    st.caption(f":red[PDF non disponibile: {exc}]")

st.divider()


# ---------------------------------------------------------------- equity

def x_axis():
    return m.times.astype("datetime64[ms]")

fig_eq = go.Figure()
for j, name in enumerate(m.strat_names):
    fig_eq.add_trace(go.Scatter(
        x=x_axis(), y=m.strat_equity[j], name=name, mode="lines",
        line=dict(width=1, color=m.strat_colors[j]), opacity=0.85,
        hovertemplate="%{x|%d.%m.%Y}<br>" + name + " %{y:,.0f}<extra></extra>"))
fig_eq.add_trace(go.Scatter(
    x=x_axis(), y=m.port_equity, name="Portafoglio", mode="lines",
    line=dict(width=2.4, color=ACCENT),
    hovertemplate="%{x|%d.%m.%Y}<br>Portafoglio %{y:,.0f}<extra></extra>"))
fig_eq.add_hline(y=cap, line=dict(width=1, dash="dot", color="#9AA4AE"))
fig_eq.update_layout(
    title="Curve di equity", height=420, template="plotly_white",
    margin=dict(l=10, r=10, t=48, b=10), hovermode="x unified",
    legend=dict(orientation="h", y=-0.16))
st.plotly_chart(fig_eq, use_container_width=True)


# ---------------------------------------------------------------- underwater

fig_uw = go.Figure()
fig_uw.add_trace(go.Scatter(
    x=x_axis(), y=m.port_dd, name="Portafoglio", mode="lines",
    line=dict(width=2, color=DD_COL), fill="tozeroy",
    fillcolor="rgba(192,38,55,0.14)",
    hovertemplate="%{x|%d.%m.%Y}<br>%{y:.2f}%<extra></extra>"))
for j, name in enumerate(m.strat_names):
    fig_uw.add_trace(go.Scatter(
        x=x_axis(), y=m.strat_dd[j], name=name, mode="lines",
        line=dict(width=1, color=m.strat_colors[j]), opacity=0.7,
        hovertemplate="%{x|%d.%m.%Y}<br>" + name + " %{y:.2f}%<extra></extra>"))
fig_uw.update_layout(
    title="Underwater · distanza dal picco precedente", height=300,
    template="plotly_white", margin=dict(l=10, r=10, t=48, b=10),
    hovermode="x unified", legend=dict(orientation="h", y=-0.2),
    yaxis=dict(ticksuffix="%"))
st.plotly_chart(fig_uw, use_container_width=True)


# ---------------------------------------------------------------- sovrapposizione dd

st.subheader("Sovrapposizione dei drawdown")
st.caption("Scala comune a tutte le righe: colore più scuro = drawdown più "
           "profondo (in % sul picco). Colonne scure allineate su più righe = "
           "periodi in cui più strategie soffrono insieme.")

rows_lbl = m.strat_names + ["PORTAFOGLIO"]
dd_stack = m.strat_dd + [m.port_dd]
gw = min(min(sd.min() for sd in dd_stack), -1e-9)   # peggior dd globale, %
xt = x_axis()
scale = [[0, "rgba(244,246,248,0.7)"], [1, DD_COL]]

fig_band = go.Figure()
for ri, (lbl, sd) in enumerate(zip(rows_lbl, dd_stack)):
    intens = np.clip(-sd / -gw, 0, 1)          # 0 fuori dal dd, 1 al peggior dd globale
    last = ri == len(rows_lbl) - 1
    fig_band.add_trace(go.Heatmap(
        x=xt, y=[lbl], z=[intens],
        colorscale=scale, zmin=0, zmax=1, xgap=0, ygap=3,
        showscale=last,
        colorbar=dict(title=dict(text="DD %", side="right"), thickness=12,
                      len=0.9, tickvals=[0, 1],
                      ticktext=["0%", f"{gw:.1f}%"]),
        hovertemplate=lbl + " %{x|%d.%m.%Y}<br>dd " +
                      "%{customdata:.2f}%<extra></extra>",
        customdata=[sd]))
fig_band.update_layout(
    height=100 + 34 * len(rows_lbl), template="plotly_white",
    margin=dict(l=10, r=10, t=10, b=10),
    yaxis=dict(autorange="reversed"))
st.plotly_chart(fig_band, use_container_width=True)

st.divider()


# ---------------------------------------------------------------- tabella metriche

st.subheader("Metriche per strategia")
rows = []
for e in m.each:
    rows.append({
        "Strategia": e["name"],
        "Netto": e["net"],
        "Op.": e["n"],
        "Win %": e["win_rate"],
        "PF": e["pf"],
        "Max DD": -e["max_dd"],
        "Max DD %": -e["max_dd_pct"],
        "DD più lungo (g)": e["longest_dd"] / np.timedelta64(1, "D"),
        "Recovery": e["rf"],
        "Media op.": e["avg"],
    })
rows.append({
    "Strategia": "Portafoglio",
    "Netto": m.port_stats["net"],
    "Op.": m.port_stats["n"],
    "Win %": m.port_stats["win_rate"],
    "PF": m.port_stats["pf"],
    "Max DD": -m.port_dd_stats[0],
    "Max DD %": -m.port_dd_stats[1],
    "DD più lungo (g)": m.port_dd_stats[2] / np.timedelta64(1, "D"),
    "Recovery": m.recovery_factor,
    "Media op.": m.port_stats["net"] / m.port_stats["n"] if m.port_stats["n"] else 0,
})
df_stats = pd.DataFrame(rows)
st.dataframe(
    df_stats.style.format({
        "Netto": "{:,.2f}", "Win %": "{:.1f}", "PF": "{:.2f}",
        "Max DD": "{:,.2f}", "Max DD %": "{:.2f}", "DD più lungo (g)": "{:.0f}",
        "Recovery": "{:.2f}", "Media op.": "{:,.2f}",
    }).map(lambda v: "color:#C02637" if isinstance(v, (int, float)) and v < 0 else "",
           subset=["Netto", "Media op."]),
    use_container_width=True, hide_index=True)


# ---------------------------------------------------------------- correlazione + mensile

c1, c2 = st.columns([0.42, 0.58])

with c1:
    st.subheader("Correlazione")
    st.caption("P/L mensile. Valori vicini a 0 o negativi = strategie che "
               "soffrono in periodi diversi.")
    labels = [f"{i+1}. {n[:16]}" for i, n in enumerate(m.strat_names)]
    fig_c = go.Figure(go.Heatmap(
        z=m.corr, x=[f"{i+1}" for i in range(len(m.strat_names))], y=labels,
        colorscale=[[0, "#15803D"], [0.5, "#E9EDF1"], [1, "#C02637"]],
        zmin=-1, zmax=1, text=np.round(m.corr, 2), texttemplate="%{text}",
        textfont=dict(size=12), showscale=True,
        colorbar=dict(thickness=10, len=0.7)))
    fig_c.update_layout(height=110 + 46 * len(m.strat_names),
                        template="plotly_white",
                        margin=dict(l=10, r=10, t=10, b=10),
                        yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig_c, use_container_width=True)

with c2:
    st.subheader("P/L mensile")
    names_m = list(m.strat_names)
    allv = np.concatenate([m.monthly.reshape(-1), m.monthly_port])
    vmax = float(np.abs(allv).max()) or 1.0

    def heat_css(v):
        # gradiente verde/rosso proporzionale, senza pandas Styler
        t = max(-1.0, min(1.0, v / vmax))
        if t >= 0:
            r, g, b = int(233 - 212 * t), int(237 - 109 * t), int(241 - 180 * t)
        else:
            r, g, b = int(233 + 39 * t), int(237 + 39 * t), int(241 + 186 * t)
        fg = "#ffffff" if abs(t) > 0.55 else "#101720"
        return f"background:rgb({r},{g},{b});color:{fg}"

    heads = ["Mese"] + names_m + ["Portafoglio"]
    thead = "".join(f"<th>{_html.escape(str(h))}</th>" for h in heads)
    body = []
    for mi, mo in enumerate(m.months):
        cells = [f'<td class="k">{_html.escape(str(mo))}</td>']
        for j in range(len(names_m)):
            v = m.monthly[j, mi]
            cells.append(f'<td style="{heat_css(v)}">{v:,.0f}</td>')
        vp = m.monthly_port[mi]
        cells.append(f'<td style="{heat_css(vp)};font-weight:600">{vp:,.0f}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")

    table_html = (
        '<div class="plwrap"><table class="pl">'
        f'<thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
        '<style>'
        '.plwrap{max-height:520px;overflow:auto;border:1px solid #E1E6EB;border-radius:4px}'
        '.pl{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;'
        'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}'
        '.pl th{position:sticky;top:0;background:#EEF1F5;color:#101720;font-weight:600;'
        'text-align:right;padding:6px 8px;white-space:nowrap;border-bottom:1px solid #C4CCD4;z-index:1}'
        '.pl td{text-align:right;padding:4px 8px;white-space:nowrap}'
        '.pl th:first-child,.pl td.k{text-align:left;position:sticky;left:0;background:#F4F6F8;'
        'font-weight:500;z-index:1}'
        '.pl th:first-child{z-index:2}'
        '</style>'
    )
    st.markdown(table_html, unsafe_allow_html=True)

st.caption("Tutti i calcoli avvengono in locale nel tuo browser/sessione: "
           "nessun dato viene inviato all'esterno.")
