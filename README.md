# Portfolio Lab

Web app in Streamlit per analizzare **come si comportano insieme** due o piu
strategie di trading a partire dai report di backtest di MetaTrader 4/5. Mostra
quando i drawdown delle strategie si sommano e quando invece si compensano,
per capire se conviene tenerle nello stesso portafoglio o separate.

## Cosa calcola

- Curve di equity del portafoglio e delle singole strategie sullo stesso asse
- Underwater (distanza dal picco) sovrapposto
- Mappa di sovrapposizione dei drawdown: evidenzia i periodi in cui piu
  strategie soffrono contemporaneamente
- Max drawdown del portafoglio contro la somma dei drawdown individuali, con il
  relativo **beneficio di diversificazione**
- Correlazione dei P/L mensili
- Tabella P/L mensile e metriche per strategia (netto, PF, win rate, recovery)
- Pesi per strategia e filtro di periodo per testare allocazioni diverse

I dati restano nella sessione locale: nessun file viene inviato all'esterno.

## Formati accettati

- MT5 report **XLSX** (localizzazione italiana e inglese)
- MT5 / MT4 report **HTML / HTM**
- **CSV / TSV** con almeno una colonna tempo e una colonna profitto

Il P/L netto di ogni operazione viene ricostruito come
`Profitto + Swap + Commissioni` sulle operazioni chiuse (deal in uscita).

### Come esportare i report

- **MT5**: Strategy Tester, scheda del backtest, tasto destro, Report, salva in
  XLSX o HTML.
- **MT4**: Strategy Tester, scheda Results, tasto destro, Save as Report (htm).

## Avvio in locale

```bash
git clone https://github.com/<utente>/portfolio-lab.git
cd portfolio-lab
python -m venv .venv && source .venv/bin/activate    # opzionale
pip install -r requirements.txt
streamlit run app.py
```

L'app si apre su `http://localhost:8501`. In `sample_data/` c'e un report di
esempio per una prova immediata.

## Deploy su Streamlit Community Cloud

1. Fai push del repository su GitHub.
2. Vai su [share.streamlit.io](https://share.streamlit.io), collega il repo e
   indica `app.py` come entry point.
3. Le dipendenze vengono installate da `requirements.txt`.

## Struttura

```
portfolio-lab/
  app.py                     interfaccia Streamlit
  portfolio_lab/
    parsing.py               lettura report -> operazioni normalizzate
    metrics.py               curve, drawdown, statistiche, correlazioni
  sample_data/               report di esempio
  requirements.txt
  .streamlit/config.toml     tema
```

## Estendere il parser

Se un report non viene letto correttamente compare un avviso accanto al file
nella barra laterale. I pattern di riconoscimento delle colonne sono in
`portfolio_lab/parsing.py` (`RX_*`): aggiungere una variante di intestazione
richiede una sola riga nel relativo pattern.
