# Portfolio Lab

Web app Streamlit per analizzare come si comportano insieme piu strategie di
trading dai report di backtest MetaTrader 4/5. Evidenzia quando i drawdown si
sommano e quando si compensano.

## Formati accettati
- MT5 report XLSX (it/en)
- MT5 / MT4 report HTML / HTM
- CSV / TSV con colonna tempo e colonna profitto

P/L netto per operazione = Profitto + Swap + Commissioni sui deal in uscita.

## Avvio in locale
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy su Streamlit Community Cloud
Push su GitHub, poi share.streamlit.io collegando il repo con app.py come entry
point.

## File
Tutti nella radice, nessuna sottocartella:
app.py, parsing.py, metrics.py, requirements.txt, README.md, LICENSE,
EURUSD_ULTIMO_ANNO_SET_A.xlsx (esempio).
