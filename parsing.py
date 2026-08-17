"""
Lettura dei report di backtest MetaTrader 4/5 e normalizzazione in una
serie di operazioni chiuse (timestamp, profitto netto).

Formati gestiti:
  - MT5 report XLSX (localizzazione italiana e inglese)
  - MT5 / MT4 report HTML
  - CSV / TSV con colonne tempo e profitto

Ogni file viene ridotto a un ParsedReport con:
  trades          DataFrame[time, pnl] delle operazioni chiuse
  initial_deposit deposito iniziale letto dal report, se presente
  currency, symbol, name  metadati dal report, se presenti
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import io
import re
import numpy as np
import pandas as pd

# pattern di riconoscimento delle intestazioni (it + en)
RX_CLOSETIME = re.compile(r"close\s*time|chiusura|ora\s*di\s*chiusura", re.I)
RX_TIME = re.compile(r"^(time|ora|orario|date|data|open\s*time)", re.I)
RX_PROFIT = re.compile(r"^(profit|profitto|p\s*/\s*l|net\s*profit|utile)", re.I)
RX_COMM = re.compile(r"commission|commissione|commissioni", re.I)
RX_SWAP = re.compile(r"swap", re.I)
RX_DIR = re.compile(r"direction|direzione", re.I)
RX_TYPE = re.compile(r"^(type|tipo)$", re.I)
RX_SKIPTYPE = re.compile(r"balance|credit|deposit|prelievo|saldo|bilancio", re.I)
RX_DEP = re.compile(r"deposito\s*iniziale|initial\s*deposit", re.I)
RX_CUR = re.compile(r"^(valuta|currency)", re.I)
RX_SYM = re.compile(r"^(simbolo|symbol)", re.I)
RX_EXPERT = re.compile(r"^(expert|esperto)", re.I)


@dataclass
class ParsedReport:
    trades: pd.DataFrame
    initial_deposit: float | None = None
    currency: str | None = None
    symbol: str | None = None
    name: str | None = None
    warning: str | None = None
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------- conversioni

def parse_num(v) -> float:
    """Converte un valore in float gestendo separatori misti it/en."""
    if v is None:
        return np.nan
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    s = re.sub(r"[\s\u00A0\u202F]", "", str(v))
    s = re.sub(r"[^\d.,+-]", "", s)
    if not s or not re.search(r"\d", s):
        return np.nan
    has_dot, has_com = "." in s, "," in s
    if has_dot and has_com:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        s = s.replace(",", "") if dec == "." else s.replace(".", "").replace(",", ".")
    elif has_com:
        after = len(s) - s.rfind(",") - 1
        s = s.replace(",", ".") if (0 < after <= 2 and s.count(",") == 1) else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return np.nan


def parse_date(v):
    """Converte un valore in Timestamp; NaT se non interpretabile."""
    if isinstance(v, (datetime, pd.Timestamp)):
        return pd.Timestamp(v)
    if isinstance(v, (int, float, np.integer, np.floating)):
        n = float(v)
        if 20000 < n < 80000:  # seriale excel
            return pd.Timestamp("1899-12-30") + pd.Timedelta(days=n)
        return pd.NaT
    s = str(v).strip()
    if len(s) < 8:
        return pd.NaT
    m = re.match(r"^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", s)
    if not m:
        m2 = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", s)
        if m2:
            d, mo, y = int(m2[1]), int(m2[2]), int(m2[3])
            hh, mm, ss = int(m2[4] or 0), int(m2[5] or 0), int(m2[6] or 0)
            try:
                return pd.Timestamp(y, mo, d, hh, mm, ss)
            except ValueError:
                return pd.NaT
        try:
            return pd.Timestamp(s)
        except (ValueError, TypeError):
            return pd.NaT
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    hh, mm, ss = int(m[4] or 0), int(m[5] or 0), int(m[6] or 0)
    try:
        return pd.Timestamp(y, mo, d, hh, mm, ss)
    except ValueError:
        return pd.NaT


# ---------------------------------------------------------- file -> matrice

def _matrix_from_xlsx(data: bytes) -> list[list]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    rows: list[list] = []
    for ws in wb.worksheets:
        for r in ws.iter_rows(values_only=True):
            rows.append(list(r))
    return rows


def _matrix_from_html(text: str) -> list[list]:
    from html.parser import HTMLParser

    class T(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows, self.cur, self.buf, self.incell = [], None, [], False

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self.cur = []
            elif tag in ("td", "th"):
                self.incell, self.buf = True, []

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.cur is not None:
                self.cur.append("".join(self.buf).replace("\xa0", " ").strip())
                self.incell = False
            elif tag == "tr" and self.cur is not None:
                if self.cur:
                    self.rows.append(self.cur)
                self.cur = None

        def handle_data(self, data):
            if self.incell:
                self.buf.append(data)

    p = T()
    p.feed(text)
    return p.rows


def _matrix_from_csv(text: str) -> list[list]:
    import csv
    head = "\n".join(text.splitlines()[:20])
    delim = max([",", ";", "\t"], key=lambda d: head.count(d))
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in row)]


def load_matrix(filename: str, data: bytes) -> list[list]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("xlsx", "xls", "xlsm"):
        return _matrix_from_xlsx(data)
    text = data.decode("utf-8", errors="replace")
    if re.search(r"<\s*(table|html|body)", text[:4000], re.I):
        return _matrix_from_html(text)
    return _matrix_from_csv(text)


# --------------------------------------------------- estrazione operazioni

def _scan_metadata(rows: list[list]) -> dict:
    meta: dict = {}
    for r in rows[:130]:
        cells = [("" if c is None else str(c)) for c in r]
        joined = "|".join(cells)
        for j, c in enumerate(cells):
            val = next((x for x in cells[j + 1:] if x.strip()), "")
            if RX_DEP.search(c) and "initial_deposit" not in meta:
                meta["initial_deposit"] = parse_num(val)
            elif RX_CUR.match(c) and "currency" not in meta:
                meta["currency"] = val.strip()
            elif RX_SYM.match(c) and "symbol" not in meta:
                meta["symbol"] = val.strip()
            elif RX_EXPERT.match(c) and "name" not in meta:
                meta["name"] = val.strip()
    return meta


def _find_header(rows: list[list]):
    """Ultima riga con almeno un campo tempo e un campo profitto."""
    best, cols = -1, None
    for i, r in enumerate(rows):
        cells = [("" if c is None else str(c)).strip() for c in r]
        if len(cells) < 4:
            continue
        i_time = i_close = i_profit = -1
        for j, c in enumerate(cells):
            if RX_CLOSETIME.search(c) and i_close < 0:
                i_close = j
            if RX_TIME.match(c) and i_time < 0:
                i_time = j
            if RX_PROFIT.match(c) and i_profit < 0:
                i_profit = j
        if i_profit < 0 or (i_time < 0 and i_close < 0):
            continue
        idx = {
            "time": i_close if i_close >= 0 else i_time,
            "profit": i_profit,
            "comm": next((j for j, c in enumerate(cells) if RX_COMM.search(c)), -1),
            "swap": next((j for j, c in enumerate(cells) if RX_SWAP.search(c)), -1),
            "dir": next((j for j, c in enumerate(cells) if RX_DIR.search(c)), -1),
            "type": next((j for j, c in enumerate(cells) if RX_TYPE.match(c)), -1),
        }
        best, cols = i, idx
    return (best, cols) if best >= 0 else (None, None)


def _extract_trades(rows: list[list]):
    hi, c = _find_header(rows)
    if hi is None:
        return pd.DataFrame(columns=["time", "pnl"]), "nessuna tabella di operazioni riconosciuta"
    recs = []
    for i in range(hi + 1, len(rows)):
        r = rows[i]
        get = lambda k: r[c[k]] if 0 <= c[k] < len(r) else None
        t = parse_date(get("time"))
        if pd.isna(t):
            continue
        if c["type"] >= 0 and RX_SKIPTYPE.search(str(get("type") or "")):
            continue
        if c["dir"] >= 0:
            d = str(get("dir") or "").lower()
            if not re.match(r"^(out|uscita)", d):
                continue
        p = parse_num(get("profit"))
        if np.isnan(p):
            continue
        if c["comm"] >= 0:
            x = parse_num(get("comm"))
            p += 0 if np.isnan(x) else x
        if c["swap"] >= 0:
            x = parse_num(get("swap"))
            p += 0 if np.isnan(x) else x
        recs.append((t, p))
    if not recs:
        return pd.DataFrame(columns=["time", "pnl"]), "tabella trovata ma nessuna operazione chiusa estratta"
    df = pd.DataFrame(recs, columns=["time", "pnl"]).sort_values("time").reset_index(drop=True)
    return df, None


def parse_report(filename: str, data: bytes) -> ParsedReport:
    rows = load_matrix(filename, data)
    meta = _scan_metadata(rows)
    trades, warn = _extract_trades(rows)
    name = meta.get("name") or filename.rsplit(".", 1)[0]
    return ParsedReport(
        trades=trades,
        initial_deposit=meta.get("initial_deposit"),
        currency=meta.get("currency"),
        symbol=meta.get("symbol"),
        name=name[:40],
        warning=warn,
        meta=meta,
    )
