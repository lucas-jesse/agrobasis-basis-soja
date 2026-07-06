"""
Camada de dados do dólar futuro (DOL - B3), extraída do app__18_.py
já validado por você. Removi apenas CSS/UI do Streamlit - a lógica de
busca, fallback e interpolação é a mesma.
"""
import re
import numpy as np
import pandas as pd
import requests
import streamlit as st
from datetime import datetime

MONTH_CODES = {1: 'F', 2: 'G', 3: 'H', 4: 'J', 5: 'K', 6: 'M', 7: 'N', 8: 'Q', 9: 'U', 10: 'V', 11: 'X', 12: 'Z'}
MESES_ABREV = {1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun', 7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'}
CODE_TO_MONTH = {v: k for k, v in MONTH_CODES.items()}


@st.cache_data(ttl=900)
def fetch_cotacao_atual():
    import yfinance as yf
    try:
        ticker = yf.Ticker("BRL=X")
        hist = ticker.history(period="2d", interval="1h")
        if not hist.empty:
            last = hist.iloc[-1]
            bid = float(last["Close"])
            high = float(hist["High"].tail(8).max())
            low = float(hist["Low"].tail(8).min())
            open_price = float(hist["Open"].iloc[-1])
            pctchg = ((bid / open_price) - 1) * 100 if open_price else 0.0
            return {"bid": bid, "ask": bid * 1.0005, "high": high, "low": low,
                    "pctchg": pctchg, "ts": datetime.now(), "fonte": "yfinance"}
    except Exception:
        pass
    try:
        r = requests.get("https://economia.awesomeapi.com.br/json/last/USD-BRL", timeout=8,
                          headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        d = r.json()["USDBRL"]
        return {"bid": float(d["bid"]), "ask": float(d["ask"]), "high": float(d["high"]),
                "low": float(d["low"]), "pctchg": float(d["pctChange"]),
                "ts": datetime.fromtimestamp(int(d["timestamp"])), "fonte": "AwesomeAPI"}
    except Exception:
        pass
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/BRL=X",
                          params={"range": "1d", "interval": "5m"},
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            j = r.json()
            result = j.get("chart", {}).get("result", [None])[0]
            if result:
                closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
                closes = [x for x in closes if x is not None]
                if closes:
                    bid = float(closes[-1])
                    meta = result.get("meta", {})
                    high = float(meta.get("regularMarketDayHigh", bid))
                    low = float(meta.get("regularMarketDayLow", bid))
                    prev = float(meta.get("previousClose", bid))
                    pctchg = ((bid / prev) - 1) * 100 if prev else 0.0
                    return {"bid": bid, "ask": bid * 1.0005, "high": high, "low": low,
                            "pctchg": pctchg, "ts": datetime.now(), "fonte": "Yahoo Finance"}
    except Exception:
        pass
    return None


@st.cache_data(ttl=900)
def fetch_historico_resumo(dias: int = 35):
    import yfinance as yf
    try:
        ticker = yf.Ticker("BRL=X")
        hist = ticker.history(period=f"{dias}d", interval="1d")
        if not hist.empty:
            df = hist.reset_index()[["Date", "Close"]].copy()
            df.columns = ["data", "close"]
            df["data"] = pd.to_datetime(df["data"]).dt.tz_localize(None)
            return df.sort_values("data").reset_index(drop=True)
    except Exception:
        pass
    try:
        r = requests.get(f"https://economia.awesomeapi.com.br/json/daily/USD-BRL/{dias}",
                          timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        df = pd.DataFrame(r.json())
        df["data"] = pd.to_datetime(df["timestamp"].astype(int), unit="s")
        df["close"] = df["bid"].astype(float)
        return df[["data", "close"]].sort_values("data").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def gerar_datas_mensais(data_base: datetime, meses_proj: int) -> pd.DatetimeIndex:
    inicio_mes = pd.Timestamp(data_base).replace(day=1).normalize()
    return pd.date_range(start=inicio_mes, periods=meses_proj + 1, freq="BME")


def contar_dias_uteis(data_inicio, datas):
    base = pd.Timestamp(data_inicio).normalize()
    out = []
    for d in pd.to_datetime(datas):
        d = pd.Timestamp(d).normalize()
        if d <= base:
            out.append(0)
        else:
            out.append(max(len(pd.bdate_range(base, d)) - 1, 0))
    return np.array(out, dtype=float)


def vencimento_dol_para_data(contrato):
    s = str(contrato).upper().strip()
    s = s.split(":")[-1]
    m = re.search(r"DOL([FGHJKMNQUVXZ])(20\d{2}|\d{2})", s)
    if not m:
        return pd.NaT
    mes = CODE_TO_MONTH.get(m.group(1))
    ano = int(m.group(2))
    if ano < 100:
        ano += 2000
    return pd.bdate_range(pd.Timestamp(ano, mes, 1), periods=1)[0]


def normalizar_preco_dol(preco):
    try:
        x = float(preco)
    except Exception:
        return np.nan
    if not np.isfinite(x) or x <= 0:
        return np.nan
    return x / 1000.0 if x > 100 else x


def gerar_tickers_dol(data_base, meses=36):
    base = pd.Timestamp(data_base).replace(day=1).normalize()
    datas = pd.date_range(base, periods=meses, freq="MS")
    return [f"BMFBOVESPA:DOL{MONTH_CODES[int(d.month)]}{int(d.year)}" for d in datas]


def _extrair_tickers_dol_do_html(html: str, meses_busca: int = 36):
    if not html:
        return []
    achados = re.findall(r"\bDOL[FGHJKMNQUVXZ](?:20\d{2}|\d{2})\b", html.upper())
    out, vistos = [], set()
    for sym in achados:
        venc = vencimento_dol_para_data(sym)
        if pd.isna(venc):
            continue
        full = f"BMFBOVESPA:{sym}"
        if full not in vistos:
            vistos.add(full)
            out.append((venc, full))
    out = sorted(out, key=lambda x: x[0])
    return [x[1] for x in out[:meses_busca]]


def _buscar_tickers_dol_pagina_contratos(meses_busca: int = 36):
    urls = [
        "https://br.tradingview.com/symbols/BMFBOVESPA-DOL1!/contracts/",
        "https://www.tradingview.com/symbols/BMFBOVESPA-DOL1!/contracts/",
        "https://www.tradingview.com/symbols/BMFBOVESPA-DOL1%21/contracts/",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
    }
    erros = []
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                erros.append(f"{url}: HTTP {r.status_code}")
                continue
            tickers = _extrair_tickers_dol_do_html(r.text, meses_busca)
            if len(tickers) >= 2:
                return tickers, None
            erros.append(f"{url}: poucos contratos no HTML")
        except Exception as e:
            erros.append(f"{url}: {e}")
    return [], "; ".join(erros) if erros else "não foi possível ler página de contratos"


def _scanner_tradingview(tickers, endpoint="brazil"):
    url = f"https://scanner.tradingview.com/{endpoint}/scan"
    columns = ["close", "volume", "open_interest", "name", "description"]
    payload = {
        "symbols": {"tickers": tickers, "query": {"types": []}},
        "columns": columns,
        "ignore_unknown_fields": True,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://br.tradingview.com",
        "Referer": "https://br.tradingview.com/symbols/BMFBOVESPA-DOL1!/contracts/",
    }
    r = requests.post(url, json=payload, headers=headers, timeout=15)
    r.raise_for_status()
    js = r.json()
    return js.get("data", []) or []


@st.cache_data(ttl=900)
def fetch_dol_tradingview_contracts(data_base_str: str, meses_busca: int = 36):
    data_base = pd.Timestamp(data_base_str).normalize()
    tickers_pagina, err_pagina = _buscar_tickers_dol_pagina_contratos(meses_busca)
    tickers_gerados = gerar_tickers_dol(data_base, meses_busca)

    tickers, vistos = [], set()
    for tk in tickers_pagina + tickers_gerados:
        if tk not in vistos:
            vistos.add(tk)
            tickers.append(tk)

    erros = []
    rows = []
    for endpoint in ["brazil", "futures"]:
        try:
            dados = []
            for i in range(0, len(tickers), 40):
                dados.extend(_scanner_tradingview(tickers[i:i + 40], endpoint=endpoint))
            for item in dados:
                symbol = item.get("s", "").split(":")[-1].upper()
                d = item.get("d", [])
                close = d[0] if len(d) > 0 else np.nan
                preco = normalizar_preco_dol(close)
                venc = vencimento_dol_para_data(symbol)
                if pd.notna(venc) and np.isfinite(preco) and 3.0 <= preco <= 8.5:
                    rows.append({"Contrato": symbol, "vencimento": venc, "Dólar Futuro": preco,
                                 "Volume": d[1] if len(d) > 1 else np.nan,
                                 "Open Interest": d[2] if len(d) > 2 else np.nan})
            if rows:
                break
        except Exception as e:
            erros.append(f"scanner {endpoint}: {e}")

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["Contrato"]).sort_values("vencimento")
        df = df[df["vencimento"] >= data_base.replace(day=1)]
        if len(df) >= 2:
            df.attrs["fonte"] = "TradingView . contratos DOL B3"
            return df.reset_index(drop=True), None

    msg = []
    if err_pagina:
        msg.append(f"página contratos: {err_pagina}")
    if erros:
        msg.extend(erros)
    if not msg:
        msg.append("TradingView não retornou linhas válidas para contratos DOL")
    return pd.DataFrame(), "; ".join(msg)


def curva_dol_manual_default(datas_mensais, spot):
    n = len(datas_mensais)
    carrego = np.linspace(0.0, 0.08, n)
    return pd.DataFrame({
        "Referência": [f"{MESES_ABREV[int(d.month)]}/{str(int(d.year))[-2:]}" for d in datas_mensais],
        "Data": datas_mensais.strftime("%d/%m/%Y"),
        "Dólar Futuro": np.round(float(spot) * (1 + carrego), 4),
        "Contrato base": ["manual"] * n,
    })


def montar_curva_dol_base(datas_mensais, spot, auto_dol=True):
    default = curva_dol_manual_default(datas_mensais, spot)
    fontes, avisos = [], []
    dol_auto = pd.DataFrame()
    if auto_dol:
        dol_auto, err = fetch_dol_tradingview_contracts(str(pd.Timestamp(datas_mensais[0]).date()),
                                                          max(36, len(datas_mensais) + 12))
        if not dol_auto.empty:
            x = pd.to_datetime(dol_auto["vencimento"]).map(pd.Timestamp.toordinal).values
            y = dol_auto["Dólar Futuro"].astype(float).values
            xi = pd.Series(datas_mensais).map(pd.Timestamp.toordinal).values
            default["Dólar Futuro"] = np.round(np.interp(xi, x, y, left=y[0], right=y[-1]), 4)
            contratos = []
            for d in pd.to_datetime(datas_mensais):
                pos = int(np.argmin(np.abs(pd.to_datetime(dol_auto["vencimento"]).map(pd.Timestamp.toordinal).values
                                            - pd.Timestamp(d).toordinal())))
                contratos.append(str(dol_auto.iloc[pos]["Contrato"]))
            default["Contrato base"] = contratos
            fontes.append(dol_auto.attrs.get("fonte", "TradingView . contratos DOL B3"))
        else:
            avisos.append(f"DOL em fallback manual/editável. TradingView: {err}")
    else:
        avisos.append("Busca automática desligada. Usando curva manual/editável.")
    return default, fontes, avisos, dol_auto


def preparar_curva_dol(curva_editada, datas_mensais):
    df = curva_editada.copy()
    df["Dólar Futuro"] = pd.to_numeric(df["Dólar Futuro"], errors="coerce").ffill().bfill()
    df["data"] = datas_mensais
    return df


def calcular_curva_diaria_e_mensal(spot, curva_dol, meses_proj, data_base):
    base = pd.Timestamp(data_base).normalize()
    datas_mensais = gerar_datas_mensais(base, meses_proj)
    data_final = datas_mensais[-1]
    datas_diarias = pd.bdate_range(start=base, end=data_final)
    du_diarios = contar_dias_uteis(base, datas_diarias)
    du_mensais = contar_dias_uteis(base, datas_mensais)

    preco_m = curva_dol["Dólar Futuro"].astype(float).values
    du_ref = np.array(du_mensais, dtype=float)
    preco_ref = preco_m.astype(float)
    if du_ref[0] > 0:
        du_ref = np.insert(du_ref, 0, 0.0)
        preco_ref = np.insert(preco_ref, 0, float(spot))

    ndf_diario = np.interp(du_diarios, du_ref, preco_ref, left=preco_ref[0], right=preco_ref[-1])
    curva_diaria = pd.DataFrame({"data": datas_diarias, "du": du_diarios, "ndf": ndf_diario})
    curva_diaria["var_pct"] = ((curva_diaria["ndf"] / spot) - 1) * 100

    mensal = curva_diaria[curva_diaria["data"].isin(datas_mensais)].copy()
    mensal["referencia"] = mensal["data"].apply(lambda d: f"{MESES_ABREV[int(d.month)]}/{str(int(d.year))[-2:]}")
    mensal["meses_a_frente"] = range(len(mensal))
    if "Contrato base" in curva_dol.columns:
        mensal["contrato_base"] = list(curva_dol["Contrato base"].astype(str).values[:len(mensal)])
    else:
        mensal["contrato_base"] = ""
    return curva_diaria, mensal
