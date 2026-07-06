"""
Fetch da curva futura de CBOT (soja - ZS), espelhando o mesmo padrão já
validado no dashboard de dólar (app__18_.py): 1) lê a página /contracts/ do
TradingView para descobrir os vencimentos realmente listados; 2) cota esses
símbolos pelo scanner do TradingView; 3) se falhar, gera tickers "no escuro"
pelo ciclo de vencimentos da soja; 4) se tudo falhar, cai num fallback
manual/editável.

ATENÇÃO: este sandbox de desenvolvimento não tem acesso à internet para
tradingview.com, então as funções de rede abaixo não puderam ser testadas
ao vivo aqui - foram escritas seguindo o mesmo padrão comprovado do script
do dólar. Rode/valide na sua máquina antes de confiar no resultado.
"""
import re
import numpy as np
import pandas as pd
import requests
import streamlit as st

from basis_model import MESES_CONTRATOS, MONTH_TO_LETTER, DELIVERY_MONTHS

CODE_TO_MONTH_ZS = {v: k for k, v in MESES_CONTRATOS.items()}  # {'F':1,...} já é letra->mes; usamos MESES_CONTRATOS direto

HEADERS_TV = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}


def vencimento_zs_para_data(contrato):
    """Converte ZSX2026 / CBOT:ZSX2026 / ZSX26 em 1º dia útil do mês de vencimento."""
    s = str(contrato).upper().strip()
    s = s.split(":")[-1]
    m = re.search(r"ZS([FHKNQUX])(20\d{2}|\d{2})", s)
    if not m:
        return pd.NaT
    mes = MESES_CONTRATOS.get(m.group(1))
    ano = int(m.group(2))
    if ano < 100:
        ano += 2000
    if not mes:
        return pd.NaT
    return pd.bdate_range(pd.Timestamp(ano, mes, 1), periods=1)[0]


def normalizar_preco_zs(preco):
    """
    TradingView costuma devolver contratos de grãos do CBOT em cents/bushel
    (ex.: 1177.25 = US$ 11,7725/bushel). Se vier já em dólares (ex.: 11.77),
    mantém como está.
    """
    try:
        x = float(preco)
    except Exception:
        return np.nan
    if not np.isfinite(x) or x <= 0:
        return np.nan
    return x / 100.0 if x > 100 else x


def gerar_tickers_zs(data_base, n_contratos=8):
    """Gera os próximos N contratos válidos do ciclo da soja (F,H,K,N,Q,U,X)."""
    base = pd.Timestamp(data_base).replace(day=1).normalize()
    mes, ano = base.month, base.year
    candidatos = [m for m in DELIVERY_MONTHS if m > mes]
    if candidatos:
        proximo_mes, proximo_ano = min(candidatos), ano
    else:
        proximo_mes, proximo_ano = DELIVERY_MONTHS[0], ano + 1

    tickers = []
    mes_atual, ano_atual = proximo_mes, proximo_ano
    for _ in range(n_contratos):
        letra = MONTH_TO_LETTER[mes_atual]
        tickers.append(f"CBOT:ZS{letra}{ano_atual}")
        idx = DELIVERY_MONTHS.index(mes_atual)
        if idx + 1 < len(DELIVERY_MONTHS):
            mes_atual = DELIVERY_MONTHS[idx + 1]
        else:
            mes_atual = DELIVERY_MONTHS[0]
            ano_atual += 1
    return tickers


def _extrair_tickers_zs_do_html(html: str, n_max: int = 12):
    if not html:
        return []
    achados = re.findall(r"\bZS[FHKNQUX](?:20\d{2}|\d{2})\b", html.upper())
    out, vistos = [], set()
    for sym in achados:
        venc = vencimento_zs_para_data(sym)
        if pd.isna(venc):
            continue
        full = f"CBOT:{sym}"
        if full not in vistos:
            vistos.add(full)
            out.append((venc, full))
    out = sorted(out, key=lambda x: x[0])
    return [x[1] for x in out[:n_max]]


def _buscar_tickers_zs_pagina_contratos(n_max: int = 12):
    urls = [
        "https://www.tradingview.com/symbols/CBOT-ZS1!/contracts/",
        "https://br.tradingview.com/symbols/CBOT-ZS1!/contracts/",
    ]
    erros = []
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS_TV, timeout=15)
            if r.status_code != 200:
                erros.append(f"{url}: HTTP {r.status_code}")
                continue
            tickers = _extrair_tickers_zs_do_html(r.text, n_max)
            if len(tickers) >= 2:
                return tickers, None
            erros.append(f"{url}: poucos contratos no HTML")
        except Exception as e:
            erros.append(f"{url}: {e}")
    return [], "; ".join(erros) if erros else "não foi possível ler página de contratos"


def _scanner_tradingview(tickers, endpoint="america"):
    url = f"https://scanner.tradingview.com/{endpoint}/scan"
    columns = ["close", "volume", "open_interest", "name", "description"]
    payload = {
        "symbols": {"tickers": tickers, "query": {"types": []}},
        "columns": columns,
        "ignore_unknown_fields": True,
    }
    headers = {
        **HEADERS_TV,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/symbols/CBOT-ZS1!/contracts/",
    }
    r = requests.post(url, json=payload, headers=headers, timeout=15)
    r.raise_for_status()
    js = r.json()
    return js.get("data", []) or []


@st.cache_data(ttl=900)
def fetch_zs_tradingview_contracts(data_base_str: str, n_contratos: int = 8):
    """
    Busca contratos individuais de soja (ZS) do CBOT no TradingView.
    Mesma estratégia de 3 camadas do script do dólar: página de contratos
    -> tickers gerados -> scanner (tentando endpoints 'america' e 'futures',
    já que CBOT é bolsa americana - validar qual funciona na prática).
    """
    data_base = pd.Timestamp(data_base_str).normalize()

    tickers_pagina, err_pagina = _buscar_tickers_zs_pagina_contratos(n_contratos + 4)
    tickers_gerados = gerar_tickers_zs(data_base, n_contratos + 4)

    tickers, vistos = [], set()
    for tk in tickers_pagina + tickers_gerados:
        if tk not in vistos:
            vistos.add(tk)
            tickers.append(tk)

    erros = []
    rows = []
    for endpoint in ["america", "futures"]:
        try:
            dados = []
            for i in range(0, len(tickers), 40):
                dados.extend(_scanner_tradingview(tickers[i:i + 40], endpoint=endpoint))
            for item in dados:
                symbol = item.get("s", "").split(":")[-1].upper()
                d = item.get("d", [])
                close = d[0] if len(d) > 0 else np.nan
                preco = normalizar_preco_zs(close)
                venc = vencimento_zs_para_data(symbol)
                if pd.notna(venc) and np.isfinite(preco) and 3.0 <= preco <= 40.0:
                    rows.append({
                        "Contrato": symbol,
                        "vencimento": venc,
                        "CBOT US$/bushel": preco,
                        "Volume": d[1] if len(d) > 1 else np.nan,
                        "Open Interest": d[2] if len(d) > 2 else np.nan,
                    })
            if rows:
                break
        except Exception as e:
            erros.append(f"scanner {endpoint}: {e}")

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["Contrato"]).sort_values("vencimento")
        df = df[df["vencimento"] >= data_base.replace(day=1)]
        if len(df) >= 2:
            df.attrs["fonte"] = "TradingView . contratos CBOT ZS"
            return df.reset_index(drop=True), None

    msg = []
    if err_pagina:
        msg.append(f"página contratos: {err_pagina}")
    if erros:
        msg.extend(erros)
    if not msg:
        msg.append("TradingView não retornou linhas válidas para contratos ZS")
    return pd.DataFrame(), "; ".join(msg)


def curva_zs_manual_default(datas_mensais, ultimo_preco_conhecido):
    """Fallback: curva achatada no último preço conhecido, mantendo o dashboard vivo."""
    n = len(datas_mensais)
    return pd.DataFrame({
        "Referência": [f"{d.strftime('%b/%y')}" for d in datas_mensais],
        "Data": datas_mensais.strftime("%d/%m/%Y"),
        "CBOT US$/bushel": [round(float(ultimo_preco_conhecido), 4)] * n,
        "Contrato base": ["manual"] * n,
    })


@st.cache_data(ttl=900)
def fetch_cbot_spot_atual():
    """
    Preço "spot"/contrato corrente do CBOT (ZS), usado como âncora da curva
    diária - equivalente ao fetch_cotacao_atual() do dólar. Sem isso, a
    curva usaria o último preço do arquivo histórico (que pode estar
    desatualizado em relação ao pregão de hoje).
    """
    import yfinance as yf

    try:
        ticker = yf.Ticker("ZS=F")
        hist = ticker.history(period="5d", interval="1d")
        if not hist.empty:
            preco = float(hist["Close"].iloc[-1])
            preco = normalizar_preco_zs(preco)
            if np.isfinite(preco) and preco > 0:
                return {"preco": preco, "fonte": "yfinance (ZS=F)"}
    except Exception:
        pass

    try:
        dados = _scanner_tradingview(["CBOT:ZS1!"], endpoint="futures")
        if dados:
            close = dados[0].get("d", [np.nan])[0]
            preco = normalizar_preco_zs(close)
            if np.isfinite(preco) and preco > 0:
                return {"preco": preco, "fonte": "TradingView (ZS1!)"}
    except Exception:
        pass

    return None


def montar_curva_zs_base(datas_mensais, ultimo_preco_conhecido, auto_cbot=True, n_contratos=8):
    default = curva_zs_manual_default(datas_mensais, ultimo_preco_conhecido)
    fontes, avisos = [], []
    zs_auto = pd.DataFrame()

    if auto_cbot:
        zs_auto, err = fetch_zs_tradingview_contracts(
            str(pd.Timestamp(datas_mensais[0]).date()), n_contratos
        )
        if not zs_auto.empty:
            x = pd.to_datetime(zs_auto["vencimento"]).map(pd.Timestamp.toordinal).values
            y = zs_auto["CBOT US$/bushel"].astype(float).values
            xi = pd.Series(datas_mensais).map(pd.Timestamp.toordinal).values
            default["CBOT US$/bushel"] = np.round(np.interp(xi, x, y, left=y[0], right=y[-1]), 4)
            contratos = []
            for d in pd.to_datetime(datas_mensais):
                pos = int(np.argmin(np.abs(
                    pd.to_datetime(zs_auto["vencimento"]).map(pd.Timestamp.toordinal).values
                    - pd.Timestamp(d).toordinal()
                )))
                contratos.append(str(zs_auto.iloc[pos]["Contrato"]))
            default["Contrato base"] = contratos
            fontes.append(zs_auto.attrs.get("fonte", "TradingView . contratos CBOT ZS"))
        else:
            avisos.append(f"CBOT em fallback manual/editável. TradingView: {err}")
    else:
        avisos.append("Busca automática desligada. Usando curva manual/editável.")

    return default, fontes, avisos, zs_auto
