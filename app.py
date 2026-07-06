import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# Módulos da projeção de preço futuro (dólar futuro + CBOT futuro + basis
# projetado). Precisam estar na mesma pasta deste arquivo: basis_model.py,
# fontes_dolar.py, fontes_cbot.py, projecao.py.
import basis_model as bm
import fontes_dolar as fd
import fontes_cbot as fc
import projecao as pj

st.set_page_config(
    page_title="AgroBasis | Basis da Soja",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# CONFIGURAÇÕES
# ============================================================
# Leitura via Google Sheets
# Link da planilha:
# https://docs.google.com/spreadsheets/d/19Xj98vTyWh3X4y1MW_qq8s5EYHKsT2Av1QOPVm7Abnk/edit
SHEET_ID = "19Xj98vTyWh3X4y1MW_qq8s5EYHKsT2Av1QOPVm7Abnk"
ABA_DADOS = "fechamento_usd_bushel"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

KG_POR_BUSHEL_SOJA = 27.2155
KG_POR_SACA = 60

MESES_CONTRATOS = {"F": 1, "H": 3, "K": 5, "N": 7, "Q": 8, "U": 9, "X": 11}
NOME_CONTRATO = {"F": "Jan", "H": "Mar", "K": "Mai", "N": "Jul", "Q": "Ago", "U": "Set", "X": "Nov"}

CIDADES_COORD = {
    "Santa Rosa": (-27.8707, -54.4806),
    "Santa Rosa RS": (-27.8707, -54.4806),
    "Cascavel": (-24.9555, -53.4552),
    "Cascavel PR": (-24.9555, -53.4552),
    "Passo Fundo": (-28.2628, -52.4067),
    "Passo Fundo RS": (-28.2628, -52.4067),
    "Maringá": (-23.4205, -51.9331),
    "Maringa": (-23.4205, -51.9331),
    "Maringá PR": (-23.4205, -51.9331),
    "Uberlândia": (-18.9186, -48.2772),
    "Uberlandia": (-18.9186, -48.2772),
    "Uberlândia MG": (-18.9186, -48.2772),
    "Sorriso": (-12.5425, -55.7211),
    "Sorriso MT": (-12.5425, -55.7211),
    "Rondonópolis": (-16.4673, -54.6372),
    "Rondonopolis": (-16.4673, -54.6372),
    "Rondonópolis MT": (-16.4673, -54.6372),
    "Dourados": (-22.2231, -54.8120),
    "Dourados MS": (-22.2231, -54.8120),
    "Rio Grande": (-32.0350, -52.0986),
    "Paranaguá": (-25.5169, -48.5243),
}

# ============================================================
# CSS — visual institucional limpo
# ============================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');

/* Base */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, sans-serif;
}
.stApp {
    background-color: #f7f8fa;
}
.block-container {
    padding-top: 0 !important;
    padding-bottom: 2rem;
    padding-left: 2.5rem !important;
    padding-right: 2.5rem !important;
    max-width: 1600px;
}

/* Barra de topo */
.topbar {
    background: #ffffff;
    border-bottom: 1px solid #e8eaed;
    padding: 0 0 0 0;
    margin: 0 -2.5rem 1.0rem -2.5rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 52px;
    padding: 0 2.5rem;
}
.topbar-brand {
    font-size: 15px;
    font-weight: 600;
    color: #111827;
    letter-spacing: -0.02em;
    display: flex;
    align-items: center;
    gap: 8px;
}
.topbar-brand span {
    color: #16a34a;
}
.topbar-tag {
    font-size: 11px;
    color: #6b7280;
    background: #f3f4f6;
    border-radius: 4px;
    padding: 2px 7px;
    font-weight: 500;
    margin-left: 4px;
}

/* Filtros — barra horizontal compacta */
.filter-bar {
    background: #ffffff;
    border: 1px solid #e8eaed;
    border-radius: 10px;
    padding: 14px 20px;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 16px;
}

/* KPI cards — compactos, linha única */
.kpi-row {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 10px;
}
.kpi-card {
    background: #ffffff;
    border: 1px solid #e8eaed;
    border-radius: 10px;
    padding: 9px 14px;
    display: flex;
    flex-direction: column;
    gap: 3px;
}
.kpi-card.highlight {
    border-left: 3px solid #16a34a;
}
.kpi-label {
    font-size: 10px;
    font-weight: 600;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.kpi-value {
    font-size: 18px;
    font-weight: 600;
    color: #111827;
    letter-spacing: -0.02em;
    line-height: 1.2;
}
.kpi-value.green { color: #16a34a; }
.kpi-value.red { color: #dc2626; }
.kpi-sub {
    font-size: 10px;
    color: #9ca3af;
    font-weight: 400;
}

/* Card de gráfico */
.chart-wrap {
    background: #ffffff;
    border: 1px solid #e8eaed;
    border-radius: 10px;
    padding: 4px 4px 0 4px;
    margin-bottom: 4px;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 1px solid #e8eaed;
    background: transparent;
    padding: 0;
    margin-bottom: 16px;
}
.stTabs [data-baseweb="tab"] {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 10px 18px;
    color: #6b7280;
    font-size: 13px;
    font-weight: 500;
    margin-bottom: -1px;
}
.stTabs [aria-selected="true"] {
    background: transparent !important;
    color: #111827 !important;
    border-bottom: 2px solid #16a34a !important;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #374151;
    background: transparent;
}

/* Inputs */
.stSelectbox label, .stMultiSelect label, .stSlider label, .stRadio label {
    font-size: 11px !important;
    font-weight: 600 !important;
    color: #6b7280 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
div[data-baseweb="select"] > div {
    background: #f9fafb !important;
    border-color: #e8eaed !important;
    border-radius: 8px !important;
    font-size: 13px;
}
div[data-baseweb="select"] > div:hover {
    border-color: #9ca3af !important;
}
.stSlider > div > div > div {
    background: #16a34a !important;
}
button[kind="secondary"] {
    border-radius: 8px !important;
    font-size: 13px !important;
    border-color: #e8eaed !important;
    color: #374151 !important;
    background: #f9fafb !important;
    font-weight: 500 !important;
}
button[kind="primary"] {
    border-radius: 8px !important;
    font-size: 13px !important;
    background: #16a34a !important;
    border: none !important;
}

/* Dataframe */
.stDataFrame {
    border: 1px solid #e8eaed;
    border-radius: 10px;
    overflow: hidden;
}

/* Download btn */
.stDownloadButton > button {
    border-radius: 8px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
}

/* Mensagens */
.stWarning, .stInfo, .stError {
    border-radius: 8px !important;
    font-size: 13px !important;
}

/* Remover padding extra do main */
section[data-testid="stSidebar"] { display: none; }
div[data-testid="stVerticalBlock"] > div:first-child { padding-top: 0; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# FUNÇÕES DE LIMPEZA
# ============================================================
def parse_numero(valor):
    if pd.isna(valor):
        return np.nan
    if isinstance(valor, (int, float, np.number)):
        return float(valor)
    txt = str(valor).strip()
    if txt == "" or txt.lower() in ["nan", "none", "#n/a", "#value!", "#ref!"]:
        return np.nan
    txt = txt.replace("R$", "").replace("US$", "").replace(" ", "")
    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except Exception:
        return np.nan


def detectar_colunas_contratos(cols):
    return [c for c in cols if re.match(r"^ZS[FHKNQUX]\d{2}$", str(c).strip())]


def contrato_para_data(codigo):
    m = re.match(r"^ZS([FHKNQUX])(\d{2})$", str(codigo).strip())
    if not m:
        return None
    letra = m.group(1)
    ano = 2000 + int(m.group(2))
    mes = MESES_CONTRATOS.get(letra)
    if not mes:
        return None
    return pd.Timestamp(year=ano, month=mes, day=15)


def contrato_ref_soja(data):
    data = pd.Timestamp(data)
    mes = data.month
    ano = data.year
    if mes == 12:
        return f"ZSF{str(ano + 1)[-2:]}"
    if mes in [1, 2]:
        return f"ZSH{str(ano)[-2:]}"
    if mes in [3, 4]:
        return f"ZSK{str(ano)[-2:]}"
    if mes in [5, 6]:
        return f"ZSN{str(ano)[-2:]}"
    if mes == 7:
        return f"ZSQ{str(ano)[-2:]}"
    if mes == 8:
        return f"ZSU{str(ano)[-2:]}"
    if mes in [9, 10]:
        return f"ZSX{str(ano)[-2:]}"
    return f"ZSF{str(ano + 1)[-2:]}"


def cortes_contratos_para_grafico(ano):
    datas = [
        (pd.Timestamp(ano, 1, 1), "Mar / H"),
        (pd.Timestamp(ano, 3, 1), "Mai / K"),
        (pd.Timestamp(ano, 5, 1), "Jul / N"),
        (pd.Timestamp(ano, 7, 1), "Ago / Q"),
        (pd.Timestamp(ano, 8, 1), "Set / U"),
        (pd.Timestamp(ano, 9, 1), "Nov / X"),
        (pd.Timestamp(ano, 11, 1), "Jan / F"),
    ]
    return [(d.dayofyear, label) for d, label in datas]


def fisico_rs_sc_para_cents_bushel(preco_rs_sc, ptax):
    return (preco_rs_sc / ptax) * (KG_POR_BUSHEL_SOJA / KG_POR_SACA) * 100


# Séries disponíveis no gráfico principal
SERIES_CONFIG = {
    "Basis": {
        "col": "Basis_cents_bu",
        "label": "Basis",
        "ytitle": "cents/bu",
        "hover": "Basis",
        "media": True,
    },
    "Físico convertido": {
        "col": "Fisico_cents_bu",
        "label": "Físico convertido",
        "ytitle": "cents/bu",
        "hover": "Físico",
        "media": True,
    },
    "CBOT referência": {
        "col": "CBOT_cents_bu",
        "label": "CBOT referência",
        "ytitle": "cents/bu",
        "hover": "CBOT",
        "media": False,
    },
}

# ============================================================
# GOOGLE SHEETS
# ============================================================
@st.cache_resource
def conectar_google():
    """
    Usa a mesma estrutura do dashboard Basis Milho:
    1) Streamlit Cloud: st.secrets["GOOGLE_CREDENTIALS"]
    2) Local: arquivo credenciais.json na mesma pasta do app
    """
    try:
        credenciais_secret = st.secrets.get("GOOGLE_CREDENTIALS", None)
    except Exception:
        credenciais_secret = None

    if credenciais_secret:
        if isinstance(credenciais_secret, str):
            credenciais = json.loads(credenciais_secret)
        else:
            credenciais = dict(credenciais_secret)
        creds = Credentials.from_service_account_info(credenciais, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credenciais.json", scopes=SCOPES)

    return gspread.authorize(creds)


def worksheet_para_df(ws):
    valores = ws.get_all_values()
    if not valores or len(valores) < 2:
        return pd.DataFrame()

    cabecalho = [str(c).strip() for c in valores[0]]
    dados = valores[1:]
    df = pd.DataFrame(dados, columns=cabecalho)

    # Remove linhas totalmente vazias
    df = df.replace("", np.nan)
    df = df.dropna(how="all")

    return df


# ============================================================
# CARREGAMENTO
# ============================================================
@st.cache_data(ttl=900)
def carregar_planilha():
    client = conectar_google()
    ws = client.open_by_key(SHEET_ID).worksheet(ABA_DADOS)
    df = worksheet_para_df(ws)

    if df.empty:
        raise ValueError(f"A aba '{ABA_DADOS}' está vazia ou não foi encontrada.")

    df.columns = [str(c).strip() for c in df.columns]

    if "date" not in df.columns and "Data" in df.columns:
        df = df.rename(columns={"Data": "date"})

    if "date" not in df.columns:
        raise ValueError("A aba precisa ter uma coluna 'date' ou 'Data'.")

    df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)
    df = df.dropna(subset=["date"]).sort_values("date")

    for col in df.columns:
        if col != "date":
            df[col] = df[col].apply(parse_numero)
            df[col] = pd.to_numeric(df[col], errors="coerce")

    contratos = detectar_colunas_contratos(df.columns)
    if not contratos:
        raise ValueError("Não encontrei colunas de contratos no padrão ZSH21, ZSK21, ZSX21 etc.")

    if "PTAX" not in df.columns:
        raise ValueError("Não encontrei a coluna PTAX.")

    cidades = [c for c in df.columns if c not in ["date", "PTAX"] + contratos]
    cidades = [c for c in cidades if df[c].notna().sum() > 0]

    return df, contratos, cidades


@st.cache_data(ttl=900)
def montar_basis():
    df, contratos, cidades = carregar_planilha()
    linhas = []
    for _, row in df.iterrows():
        data = row["date"]
        ptax = row.get("PTAX", np.nan)
        if pd.isna(ptax) or ptax <= 0:
            continue
        contrato = contrato_ref_soja(data)
        if contrato not in df.columns:
            continue
        cbot_usd_bu = row.get(contrato, np.nan)
        if pd.isna(cbot_usd_bu) or cbot_usd_bu <= 0:
            continue
        cbot_cents_bu = cbot_usd_bu * 100
        for cidade in cidades:
            preco_rs_sc = row.get(cidade, np.nan)
            if pd.isna(preco_rs_sc) or preco_rs_sc <= 0:
                continue
            fisico_cents_bu = fisico_rs_sc_para_cents_bushel(preco_rs_sc, ptax)
            basis = fisico_cents_bu - cbot_cents_bu
            linhas.append({
                "Data": data, "Cidade": cidade,
                "Preco_Fisico_Rs_sc": preco_rs_sc, "PTAX": ptax,
                "Contrato_Ref": contrato, "CBOT_USD_bu": cbot_usd_bu,
                "CBOT_cents_bu": cbot_cents_bu, "Fisico_cents_bu": fisico_cents_bu,
                "Basis_cents_bu": basis,
            })
    basis = pd.DataFrame(linhas)
    if basis.empty:
        return basis, df, contratos, cidades
    basis["Ano"] = basis["Data"].dt.year.astype(int)
    basis["DOY"] = basis["Data"].dt.dayofyear.astype(int)
    basis["Mes"] = basis["Data"].dt.month.astype(int)
    basis["MesDia"] = basis["Data"].dt.strftime("%d/%m")
    return basis.sort_values(["Data", "Cidade"]), df, contratos, cidades

# ============================================================
# GRÁFICOS
# ============================================================
def media_5_anos(df, cidade, ano_base, janela=11):
    anos_hist = list(range(ano_base - 5, ano_base))
    hist = df[(df["Cidade"] == cidade) & (df["Ano"].isin(anos_hist))].copy()
    if hist.empty:
        return pd.DataFrame(columns=["DOY", "Media_5a"])
    media = (
        hist.groupby("DOY", as_index=False)["Basis_cents_bu"]
        .mean()
        .rename(columns={"Basis_cents_bu": "Media_5a"})
        .sort_values("DOY")
    )
    media["Media_5a"] = media["Media_5a"].rolling(window=janela, center=True, min_periods=1).mean()
    return media


def serie_ano(df, cidade, ano, suavizar=1):
    d = df[(df["Cidade"] == cidade) & (df["Ano"] == ano)].copy().sort_values("DOY")
    if suavizar and suavizar > 1:
        d["Basis_plot"] = d["Basis_cents_bu"].rolling(window=suavizar, center=True, min_periods=1).mean()
    else:
        d["Basis_plot"] = d["Basis_cents_bu"]
    return d


def grafico_basis(df, cidade, anos, suavizar_atual, suavizar_media):
    ano_base = max(anos)

    # Paleta institucional: ano mais recente verde, anterior azul-ardósia, demais cinza
    CORES = {
        ano_base:     {"color": "#16a34a", "width": 2.4},
        ano_base - 1: {"color": "#3b82f6", "width": 1.8},
        ano_base - 2: {"color": "#f59e0b", "width": 1.6},
        ano_base - 3: {"color": "#8b5cf6", "width": 1.4},
        ano_base - 4: {"color": "#64748b", "width": 1.2},
        ano_base - 5: {"color": "#94a3b8", "width": 1.0},
    }

    fig = go.Figure()

    for ano in sorted(anos):
        d = serie_ano(df, cidade, ano, suavizar_atual)
        if d.empty:
            continue
        estilo = CORES.get(ano, {"color": "#94a3b8", "width": 1.2})
        fig.add_trace(go.Scatter(
            x=d["DOY"],
            y=d["Basis_plot"],
            mode="lines",
            name=str(ano),
            line=dict(width=estilo["width"], color=estilo["color"]),
            connectgaps=False,
            hovertemplate=(
                "<b>%{customdata[0]}</b> · %{customdata[1]}<br>"
                "Contrato: %{customdata[2]}<br>"
                "Físico: %{customdata[3]:.1f} c/bu · CBOT: %{customdata[4]:.1f} c/bu<br>"
                "<b>Basis: %{y:.1f} cents/bu</b><extra></extra>"
            ),
            customdata=d[["Ano", "MesDia", "Contrato_Ref", "Fisico_cents_bu", "CBOT_cents_bu"]].values,
        ))

    media = media_5_anos(df, cidade, ano_base, janela=suavizar_media)
    if not media.empty:
        fig.add_trace(go.Scatter(
            x=media["DOY"],
            y=media["Media_5a"],
            mode="lines",
            name=f"Média {ano_base-5}–{ano_base-1}",
            line=dict(width=1.2, dash="dot", color="#d1d5db"),
            hovertemplate="Média 5 anos<br>Basis: %{y:.1f} c/bu<extra></extra>",
        ))

    # Divisores de contrato
    for x, label in cortes_contratos_para_grafico(ano_base):
        fig.add_vline(
            x=x,
            line_width=0.8,
            line_dash="dash",
            line_color="rgba(156, 163, 175, 0.5)"
        )
        fig.add_annotation(
            x=x, y=1.04, yref="paper",
            text=f"<span style='font-size:10px;color:#9ca3af'>{label}</span>",
            showarrow=False,
            font=dict(color="#9ca3af", size=10),
        )

    # Linha zero
    fig.add_hline(y=0, line_width=0.8, line_color="rgba(107, 114, 128, 0.4)")

    tickvals = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    ticktext = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=f"Basis da soja — {cidade} × CBOT",
            x=0.02,
            xanchor="left",
            y=0.97,
            yanchor="top",
            font=dict(size=15, color="#111827", family="Inter, sans-serif"),
        ),
        height=540,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#374151", family="Inter, sans-serif", size=12),
        legend=dict(
            orientation="h",
            y=1.12,
            x=1.0,
            xanchor="right",
            yanchor="top",
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            font=dict(size=12, color="#374151"),
            traceorder="reversed",
        ),
        margin=dict(l=60, r=24, t=90, b=50),
        xaxis=dict(
            title="",
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            showgrid=False,
            range=[1, 366],
            tickfont=dict(size=11, color="#6b7280"),
            linecolor="#e8eaed",
            linewidth=1,
        ),
        yaxis=dict(
            title="cents/bu",
            gridcolor="rgba(229, 231, 235, 0.8)",
            zeroline=False,
            tickfont=dict(size=11, color="#6b7280"),
            title_font=dict(size=11, color="#9ca3af"),
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor="#e8eaed",
            font=dict(size=12, color="#111827", family="Inter, sans-serif"),
        ),
    )

    # Marca d'água discreta
    fig.add_annotation(
        text="AgroBasis",
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(size=72, color="rgba(0,0,0,0.035)", family="Inter, sans-serif"),
        textangle=-20,
    )
    return fig


def resumo_atual(df):
    ultima_data = df["Data"].max()
    atual = df[df["Data"] == ultima_data].copy()
    if atual.empty:
        atual = df.sort_values("Data").groupby("Cidade", as_index=False).tail(1)
        ultima_data = atual["Data"].max()
    return atual, ultima_data


def grafico_mapa(df):
    atual, ultima_data = resumo_atual(df)
    mapa = atual.copy()
    mapa["lat"] = mapa["Cidade"].map(lambda x: CIDADES_COORD.get(x, (None, None))[0])
    mapa["lon"] = mapa["Cidade"].map(lambda x: CIDADES_COORD.get(x, (None, None))[1])
    mapa = mapa.dropna(subset=["lat", "lon"])
    if mapa.empty:
        return None

    fig = go.Figure()
    fig.add_trace(go.Scattergeo(
        lon=mapa["lon"],
        lat=mapa["lat"],
        text=mapa["Cidade"],
        customdata=mapa[["Basis_cents_bu", "Preco_Fisico_Rs_sc", "CBOT_USD_bu", "Contrato_Ref", "PTAX"]],
        mode="markers+text",
        textposition="top center",
        textfont=dict(size=11, color="#374151", family="Inter, sans-serif"),
        marker=dict(
            size=16,
            color=mapa["Basis_cents_bu"],
            colorscale=[[0.0, "#fca5a5"], [0.5, "#fde68a"], [1.0, "#4ade80"]],
            colorbar=dict(
                title=dict(text="Basis<br>cents/bu", font=dict(size=11, color="#6b7280")),
                thickness=10,
                len=0.6,
                tickfont=dict(size=10, color="#6b7280"),
            ),
            line=dict(width=1, color="#ffffff"),
        ),
        hovertemplate=(
            "<b>%{text}</b><br>"
            "Basis: %{customdata[0]:.1f} c/bu<br>"
            "Físico: R$ %{customdata[1]:.2f}/sc<br>"
            "CBOT: US$ %{customdata[2]:.2f}/bu<br>"
            "PTAX: %{customdata[4]:.4f}<br>"
            "Contrato: %{customdata[3]}<extra></extra>"
        ),
    ))
    fig.update_geos(
        scope="south america",
        projection_type="mercator",
        showcountries=True,
        countrycolor="#e5e7eb",
        showland=True,
        landcolor="#f9fafb",
        showocean=True,
        oceancolor="#f0f9ff",
        showlakes=False,
        lataxis_range=[-35, 6],
        lonaxis_range=[-75, -32],
    )
    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=f"Basis por localidade — {ultima_data.strftime('%d/%m/%Y')}",
            x=0.02, xanchor="left",
            font=dict(size=15, color="#111827", family="Inter, sans-serif"),
        ),
        height=540,
        margin=dict(l=10, r=10, t=55, b=10),
        paper_bgcolor="#ffffff",
        font=dict(family="Inter, sans-serif"),
    )
    return fig


def curva_cbot_atual(df_raw, contratos):
    curvas = []
    for contrato in contratos:
        venc = contrato_para_data(contrato)
        if venc is None:
            continue
        serie = df_raw[["date", contrato]].dropna().sort_values("date")
        if serie.empty:
            continue
        preco = serie[contrato].iloc[-1]
        data_preco = serie["date"].iloc[-1]
        curvas.append({"Contrato": contrato, "Vencimento": venc, "CBOT_USD_bu": float(preco), "Data_Preco": data_preco})
    curva = pd.DataFrame(curvas).sort_values("Vencimento")
    if curva.empty:
        return curva
    data_ref = pd.Timestamp(df_raw["date"].max().year, df_raw["date"].max().month, 1)
    return curva[curva["Vencimento"] >= data_ref].copy()


def basis_mensal_referencia(df, cidade, ano_ref, tipo_basis):
    anos_hist = list(range(ano_ref - 5, ano_ref))
    hist = df[(df["Cidade"] == cidade) & (df["Ano"].isin(anos_hist))].copy()
    if hist.empty:
        return pd.DataFrame(columns=["Mes", "Basis_Ref"])
    agg_map = {"Basis médio": "mean", "Basis mínimo": "min", "Basis máximo": "max"}
    metodo = agg_map.get(tipo_basis, "mean")
    base = (
        hist.groupby("Mes", as_index=False)["Basis_cents_bu"]
        .agg(metodo)
        .rename(columns={"Basis_cents_bu": "Basis_Ref"})
        .sort_values("Mes")
    )
    base["Basis_Ref"] = base["Basis_Ref"].rolling(3, center=True, min_periods=1).mean()
    return base


def grafico_preco_teorico(df_basis, df_raw, contratos, cidade, tipo_basis):
    curva = curva_cbot_atual(df_raw, contratos)
    if curva.empty:
        return None
    ano_ref = int(df_basis["Ano"].max())
    ref = basis_mensal_referencia(df_basis, cidade, ano_ref, tipo_basis)
    if ref.empty:
        return None
    curva["Mes"] = curva["Vencimento"].dt.month
    curva = curva.merge(ref, on="Mes", how="left")
    curva["Basis_Ref"] = curva["Basis_Ref"].ffill().bfill()
    curva["Preco_Teorico_Cents_bu"] = curva["CBOT_USD_bu"] * 100 + curva["Basis_Ref"]
    curva["Preco_Teorico_USD_bu"] = curva["Preco_Teorico_Cents_bu"] / 100
    curva["Label"] = curva["Contrato"]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=curva["Label"],
        y=curva["Preco_Teorico_USD_bu"],
        name="Preço teórico",
        marker=dict(
            color=curva["Preco_Teorico_USD_bu"],
            colorscale=[[0.0, "#bbf7d0"], [0.5, "#4ade80"], [1.0, "#15803d"]],
            line=dict(color="rgba(0,0,0,0)", width=0),
        ),
        text=[f"<b>{v:.2f}</b>" for v in curva["Preco_Teorico_USD_bu"]],
        textposition="outside",
        textfont=dict(color="#374151", size=11, family="Inter, sans-serif"),
        hovertemplate="<b>%{x}</b><br>Preço teórico: US$ %{y:.2f}/bu<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=curva["Label"],
        y=curva["Preco_Teorico_USD_bu"],
        mode="lines+markers",
        name="",
        line=dict(color="#374151", width=1.5, shape="spline", dash="dot"),
        marker=dict(size=5, color="#374151"),
        hoverinfo="skip",
        showlegend=False,
    ))
    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=f"Preço teórico CBOT + basis — {cidade}",
            x=0.02, xanchor="left",
            font=dict(size=15, color="#111827", family="Inter, sans-serif"),
        ),
        height=480,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#374151", family="Inter, sans-serif", size=12),
        showlegend=False,
        bargap=0.32,
        margin=dict(l=60, r=24, t=70, b=55),
        yaxis=dict(
            title="US$/bushel",
            gridcolor="rgba(229, 231, 235, 0.8)",
            zeroline=False,
            tickfont=dict(size=11, color="#6b7280"),
            title_font=dict(size=11, color="#9ca3af"),
        ),
        xaxis=dict(
            title="",
            showgrid=False,
            tickfont=dict(size=11, color="#374151"),
            linecolor="#e8eaed",
        ),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor="#e8eaed",
            font=dict(size=12, color="#111827", family="Inter, sans-serif"),
        ),
    )
    return fig


# ============================================================
# GRÁFICO PRINCIPAL — versão genérica por série
# ============================================================
def media_5_anos_generica(df, cidade, ano_base, coluna, janela=11):
    anos_hist = list(range(ano_base - 5, ano_base))
    hist = df[(df["Cidade"] == cidade) & (df["Ano"].isin(anos_hist))].copy()
    if hist.empty or coluna not in hist.columns:
        return pd.DataFrame(columns=["DOY", "Media_5a"])
    media = (
        hist.groupby("DOY", as_index=False)[coluna]
        .mean()
        .rename(columns={coluna: "Media_5a"})
        .sort_values("DOY")
    )
    media["Media_5a"] = media["Media_5a"].rolling(window=janela, center=True, min_periods=1).mean()
    return media


def serie_ano_generica(df, cidade, ano, coluna, suavizar=1):
    d = df[(df["Cidade"] == cidade) & (df["Ano"] == ano)].copy().sort_values("DOY")
    if d.empty or coluna not in d.columns:
        return pd.DataFrame()
    if suavizar and suavizar > 1:
        d["Valor_plot"] = d[coluna].rolling(window=suavizar, center=True, min_periods=1).mean()
    else:
        d["Valor_plot"] = d[coluna]
    return d


def grafico_basis(df, cidade, anos, suavizar_atual, suavizar_media, serie="Basis"):
    cfg = SERIES_CONFIG.get(serie, SERIES_CONFIG["Basis"])
    coluna = cfg["col"]
    ano_base = max(anos)

    CORES = {
        ano_base:     {"color": "#102a83", "width": 3.2},
        ano_base - 1: {"color": "#8b5cf6", "width": 2.4},
        ano_base - 2: {"color": "#b45309", "width": 1.7},
        ano_base - 3: {"color": "#64748b", "width": 1.4},
        ano_base - 4: {"color": "#94a3b8", "width": 1.2},
        ano_base - 5: {"color": "#cbd5e1", "width": 1.0},
    }

    fig = go.Figure()

    for ano in sorted(anos):
        d = serie_ano_generica(df, cidade, ano, coluna, suavizar_atual)
        if d.empty:
            continue
        estilo = CORES.get(ano, {"color": "#94a3b8", "width": 1.2})
        fig.add_trace(go.Scatter(
            x=d["DOY"],
            y=d["Valor_plot"],
            mode="lines",
            name=str(ano),
            line=dict(width=estilo["width"], color=estilo["color"]),
            connectgaps=False,
            hovertemplate=(
                "<b>%{customdata[0]}</b> · %{customdata[1]}<br>"
                "Contrato: %{customdata[2]}<br>"
                "Físico: %{customdata[3]:.1f} c/bu · CBOT: %{customdata[4]:.1f} c/bu<br>"
                f"<b>{cfg['hover']}: " + "%{y:.1f} c/bu</b><extra></extra>"
            ),
            customdata=d[["Ano", "MesDia", "Contrato_Ref", "Fisico_cents_bu", "CBOT_cents_bu"]].values,
        ))

    if cfg.get("media", True):
        media = media_5_anos_generica(df, cidade, ano_base, coluna, janela=suavizar_media)
        if not media.empty:
            fig.add_trace(go.Scatter(
                x=media["DOY"],
                y=media["Media_5a"],
                mode="lines",
                name=f"Média {ano_base-5}–{ano_base-1}",
                line=dict(width=2.2, dash="dot", color="#b83280"),
                hovertemplate=f"Média 5 anos<br>{cfg['hover']}: " + "%{y:.1f} c/bu<extra></extra>",
            ))

    for x, label in cortes_contratos_para_grafico(ano_base):
        fig.add_vline(
            x=x,
            line_width=1.2,
            line_dash="dash",
            line_color="rgba(17, 24, 39, 0.65)"
        )
        fig.add_annotation(
            x=x, y=1.045, yref="paper",
            text=label,
            showarrow=False,
            font=dict(color="#111827", size=11, family="Inter, sans-serif"),
        )

    fig.add_hline(y=0, line_width=0.8, line_color="rgba(107, 114, 128, 0.45)")

    tickvals = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    ticktext = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=f"{cfg['label']} da soja — {cidade} × CBOT",
            x=0.5,
            xanchor="center",
            y=0.975,
            yanchor="top",
            font=dict(size=19, color="#111827", family="Inter, sans-serif"),
        ),
        height=735,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#374151", family="Inter, sans-serif", size=12),
        legend=dict(
            orientation="h",
            y=-0.055,
            x=0.5,
            xanchor="center",
            yanchor="top",
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            font=dict(size=12, color="#374151"),
        ),
        margin=dict(l=62, r=24, t=90, b=68),
        xaxis=dict(
            title="",
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            showgrid=False,
            range=[1, 366],
            tickfont=dict(size=11, color="#374151"),
            linecolor="#e8eaed",
            linewidth=1,
        ),
        yaxis=dict(
            title=cfg["ytitle"],
            gridcolor="rgba(229, 231, 235, 0.9)",
            zeroline=False,
            tickfont=dict(size=11, color="#374151"),
            title_font=dict(size=11, color="#6b7280"),
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor="#e8eaed",
            font=dict(size=12, color="#111827", family="Inter, sans-serif"),
        ),
    )

    fig.add_annotation(
        text="AgroBasis",
        xref="paper", yref="paper",
        x=0.5, y=0.50,
        showarrow=False,
        font=dict(size=78, color="rgba(0,0,0,0.035)", family="Inter, sans-serif"),
        textangle=-20,
    )
    return fig


# ============================================================
# ANALYTICS — Percentil e Z-score
# ============================================================
def calcular_analytics(df, cidade):
    d = df[df["Cidade"] == cidade].copy()
    if d.empty:
        return None

    atual = d.sort_values("Data").iloc[-1]
    basis_atual = atual["Basis_cents_bu"]
    ano_atual = int(atual["Ano"])

    # Usa os últimos 5 anos anteriores como referência, quando disponíveis.
    hist_5a = d[(d["Ano"] >= ano_atual - 5) & (d["Ano"] < ano_atual)]["Basis_cents_bu"].dropna()

    # Fallback: se não existir histórico suficiente, usa todo o histórico anterior à última data.
    if len(hist_5a) < 20:
        hist_5a = d[d["Data"] < atual["Data"]]["Basis_cents_bu"].dropna()

    if hist_5a.empty:
        return {
            "basis": basis_atual,
            "percentil": np.nan,
            "zscore": np.nan,
            "diff_media": np.nan,
            "media_hist": np.nan,
            "n_obs": 0,
            "classificacao": "Sem histórico",
        }

    percentil = float((hist_5a < basis_atual).mean() * 100)
    media_h = hist_5a.mean()
    std_h = hist_5a.std()
    zscore = (basis_atual - media_h) / std_h if std_h and std_h > 0 else 0.0
    diff_media = basis_atual - media_h

    if percentil >= 80:
        classificacao = "Forte"
    elif percentil >= 60:
        classificacao = "Acima da média"
    elif percentil >= 40:
        classificacao = "Normal"
    elif percentil >= 20:
        classificacao = "Abaixo da média"
    else:
        classificacao = "Fraco"

    return {
        "basis": basis_atual,
        "percentil": percentil,
        "zscore": zscore,
        "diff_media": diff_media,
        "media_hist": media_h,
        "n_obs": int(len(hist_5a)),
        "classificacao": classificacao,
    }

# ============================================================
# PROJEÇÃO DE PREÇO FUTURO (dólar futuro x CBOT futuro x basis projetado)
# ============================================================
def preparar_basis_hist_para_projecao(df_basis, cidade):
    """Adapta o df_basis (long, multi-cidade) para o formato esperado
    pelos módulos de projeção: colunas 'Data' e 'basis_usd_bushel'."""
    d = df_basis[df_basis["Cidade"] == cidade][["Data", "Basis_cents_bu"]].copy()
    d["basis_usd_bushel"] = d["Basis_cents_bu"] / 100.0
    return d.dropna(subset=["basis_usd_bushel"]).sort_values("Data").reset_index(drop=True)


def grafico_linha_precos_proj(curva_diaria, mensal):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=curva_diaria["data"], y=curva_diaria["preco_rs_saca"],
        mode="lines", line=dict(color="#102a83", width=3),
        name="Curva projetada diária",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>R$ %{y:.2f}/saca<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=mensal["data_ref"], y=mensal["preco_medio_rs_saca"],
        mode="markers+text",
        text=[f"{r}<br>R$ {v:.2f}".replace(".", ",") for r, v in zip(mensal["referencia"], mensal["preco_medio_rs_saca"])],
        textposition="top center",
        textfont=dict(size=11, color="#111827", family="Inter, sans-serif"),
        marker=dict(size=10, color="#d97706", line=dict(width=2, color="#fff")),
        name="Média do mês",
        hovertemplate="<b>%{customdata}</b><br>Média do mês: R$ %{y:.2f}/saca<extra></extra>",
        customdata=mensal["referencia"],
    ))
    fig.update_layout(
        template="plotly_white", height=560,
        title=dict(text="Curva de preço futuro projetado — R$/saca", x=0.02,
                    font=dict(size=15, color="#111827", family="Inter, sans-serif")),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color="#374151", family="Inter, sans-serif", size=12),
        margin=dict(l=55, r=24, t=70, b=50),
        legend=dict(orientation="h", y=-0.16, x=0.5, xanchor="center", bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(showgrid=False, title="", linecolor="#e8eaed"),
        yaxis=dict(title="R$/saca", gridcolor="rgba(229,231,235,0.9)", tickprefix="R$ "),
        hovermode="x unified",
    )
    return fig


def grafico_barras_precos_proj(mensal):
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=mensal["referencia"], y=mensal["preco_medio_rs_saca"],
        marker_color="#16a34a",
        text=[f"R$ {v:.2f}".replace(".", ",") for v in mensal["preco_medio_rs_saca"]],
        textposition="outside",
        textfont=dict(size=13, color="#111827", family="Inter, sans-serif"),
        hovertemplate="<b>%{x}</b><br>R$ %{y:.2f}/saca<extra></extra>",
    ))
    y_max = mensal["preco_medio_rs_saca"].max()
    fig.update_layout(
        template="plotly_white", height=520,
        title=dict(text="Projeção de preço médio por mês futuro — R$/saca", x=0.02,
                    font=dict(size=15, color="#111827", family="Inter, sans-serif")),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color="#374151", family="Inter, sans-serif", size=12),
        margin=dict(l=55, r=24, t=70, b=50),
        xaxis=dict(title="", showgrid=False, linecolor="#e8eaed"),
        yaxis=dict(title="R$/saca", gridcolor="rgba(229,231,235,0.9)", tickprefix="R$ ",
                    range=[0, y_max * 1.18]),
        showlegend=False,
    )
    return fig


@st.cache_data(ttl=900)
def montar_projecao_completa(_df_basis_hist_proj, ultimo_cbot_hist, cidade, meses_proj, auto_dol, auto_cbot,
                              anos_janela_basis, dias_janela_basis, ts_cache_key):
    """Busca dólar/CBOT e monta a curva projetada. ts_cache_key participa do
    hash de cache (junto com os demais parâmetros) e força recálculo quando
    a hora muda; _df_basis_hist_proj é ignorado no hash por ser DataFrame."""
    cotacao = fd.fetch_cotacao_atual()
    hist_dolar = fd.fetch_historico_resumo(35)
    if cotacao:
        spot_dolar = cotacao["bid"]
        fonte_dolar_spot = cotacao.get("fonte", "?")
    elif not hist_dolar.empty:
        spot_dolar = float(hist_dolar["close"].iloc[-1])
        fonte_dolar_spot = "histórico (fallback)"
    else:
        return None

    cbot_spot = fc.fetch_cbot_spot_atual()
    if cbot_spot:
        cbot_ancora = cbot_spot["preco"]
        fonte_cbot_spot = cbot_spot["fonte"]
    else:
        cbot_ancora = float(ultimo_cbot_hist)
        fonte_cbot_spot = "histórico (fallback - pode estar desatualizado)"

    data_base = pd.Timestamp(cotacao["ts"]).normalize() if cotacao else pd.Timestamp.now().normalize()
    datas_mensais = fd.gerar_datas_mensais(data_base, meses_proj)

    curva_dol_default, fontes_dol, avisos_dol, _ = fd.montar_curva_dol_base(datas_mensais, spot_dolar, auto_dol=auto_dol)
    curva_zs_default, fontes_zs, avisos_zs, _ = fc.montar_curva_zs_base(datas_mensais, cbot_ancora, auto_cbot=auto_cbot)

    curva_dol_prep = fd.preparar_curva_dol(curva_dol_default, datas_mensais)
    curva_dolar_diaria, _ = fd.calcular_curva_diaria_e_mensal(spot_dolar, curva_dol_prep, meses_proj, data_base)

    curva_zs_prep = curva_zs_default.copy()
    curva_zs_prep["data"] = datas_mensais
    curva_cbot_diaria = pj.calcular_curva_cbot_diaria(cbot_ancora, curva_zs_prep, meses_proj, data_base)

    projecao_diaria = pj.montar_projecao_precos(
        data_base, meses_proj, curva_dolar_diaria[["data", "ndf"]], curva_cbot_diaria,
        _df_basis_hist_proj, anos_janela=anos_janela_basis, dias_janela=dias_janela_basis,
    )
    mensal = pj.resumo_mensal(projecao_diaria)

    return {
        "projecao_diaria": projecao_diaria,
        "mensal": mensal,
        "spot_dolar": spot_dolar,
        "fonte_dolar_spot": fonte_dolar_spot,
        "cbot_ancora": cbot_ancora,
        "fonte_cbot_spot": fonte_cbot_spot,
        "avisos": avisos_dol + avisos_zs,
        "fontes": fontes_dol + fontes_zs,
        "data_base": data_base,
        "curva_dol": curva_dol_default,
        "curva_cbot": curva_zs_default,
    }

# ============================================================
# UI
# ============================================================

# Barra de topo
st.markdown("""
<div class="topbar">
    <div class="topbar-brand">
        🌾 Agro<span>Basis</span>
        <div class="topbar-tag">Soja CBOT</div>
    </div>
</div>
""", unsafe_allow_html=True)

# Carregamento de dados direto do Google Sheets
try:
    df_basis, df_raw, contratos, cidades = montar_basis()
except Exception as e:
    st.error(f"Erro ao carregar dados: {e}")
    st.stop()

if df_basis.empty:
    st.warning("Não foi possível calcular o basis. Verifique PTAX, preços físicos e contratos CBOT.")
    st.stop()

cidades = sorted(df_basis["Cidade"].dropna().unique())
anos_disponiveis = sorted(df_basis["Ano"].dropna().unique().astype(int).tolist())

# ── Filtros em barra horizontal compacta ──
with st.container():
    col1, col2, col3, col4, col5 = st.columns([2.0, 1.8, 1.0, 1.0, 0.75])
    with col1:
        cidade_default = "Rio Grande" if "Rio Grande" in cidades else ("Santa Rosa" if "Santa Rosa" in cidades else cidades[0])
        cidade_sel = st.selectbox("Localidade", cidades, index=cidades.index(cidade_default), label_visibility="visible")
    with col2:
        default_anos = anos_disponiveis[-2:] if len(anos_disponiveis) >= 2 else anos_disponiveis
        anos_sel = st.multiselect("Anos", anos_disponiveis, default=default_anos, label_visibility="visible")
    with col3:
        suavizar_atual = st.slider("Suavização", min_value=1, max_value=10, value=1, step=1)
    with col4:
        suavizar_media = st.slider("Suavização média", min_value=3, max_value=31, value=11, step=2)
    with col5:
        st.write("")
        st.write("")
        if st.button("↺ Atualizar", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()

if not anos_sel:
    st.warning("Selecione pelo menos um ano.")
    st.stop()

# ── KPI cards compactos ──
atual, ultima_data = resumo_atual(df_basis[df_basis["Cidade"] == cidade_sel])
if not atual.empty:
    row_atual = atual.sort_values("Data").iloc[-1]
    basis_val = row_atual["Basis_cents_bu"]
    basis_color = "green" if basis_val > 0 else "red"

    st.markdown(f"""
    <div class="kpi-row">
        <div class="kpi-card">
            <div class="kpi-label">Última data</div>
            <div class="kpi-value" style="font-size:18px">{row_atual['Data'].strftime('%d/%m/%Y')}</div>
            <div class="kpi-sub">{row_atual['Contrato_Ref']}</div>
        </div>
        <div class="kpi-card highlight">
            <div class="kpi-label">Basis atual</div>
            <div class="kpi-value {basis_color}">{basis_val:.1f}</div>
            <div class="kpi-sub">cents/bushel</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Físico convertido</div>
            <div class="kpi-value">{row_atual['Fisico_cents_bu']:.1f}</div>
            <div class="kpi-sub">cents/bushel</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">CBOT referência</div>
            <div class="kpi-value">{row_atual['CBOT_cents_bu']:.1f}</div>
            <div class="kpi-sub">cents/bushel</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── Tabs ──
tab_basis, tab_projecao, tab_mapa = st.tabs(["Basis", "Projeção", "Mapa"])

with tab_basis:
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)
    fig = grafico_basis(df=df_basis, cidade=cidade_sel, anos=anos_sel, suavizar_atual=suavizar_atual, suavizar_media=suavizar_media)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)

with tab_projecao:
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        meses_proj = st.slider("Projeção (meses)", 3, 18, 12, 1, key="proj_meses")
    with p2:
        auto_dol = st.checkbox("Dólar automático", value=True, key="proj_auto_dol")
    with p3:
        auto_cbot = st.checkbox("CBOT automático", value=True, key="proj_auto_cbot")
    with p4:
        col_anos, col_dias = st.columns(2)
        with col_anos:
            anos_janela_basis = st.slider("Basis: nº anos", 3, 8, 5, 1, key="proj_anos_janela")
        with col_dias:
            dias_janela_basis = st.slider("Basis: janela (d)", 1, 15, 5, 1, key="proj_dias_janela")

    df_basis_proj = preparar_basis_hist_para_projecao(df_basis, cidade_sel)
    ultimo_cbot_hist = float(df_basis[df_basis["CBOT_USD_bu"].notna()].sort_values("Data")["CBOT_USD_bu"].iloc[-1])

    if df_basis_proj.empty:
        st.warning(f"Não há histórico de basis suficiente para {cidade_sel} para projetar.")
    else:
        cache_key = f"{cidade_sel}-{meses_proj}-{auto_dol}-{auto_cbot}-{anos_janela_basis}-{dias_janela_basis}-{datetime.now().strftime('%Y%m%d%H')}"
        with st.spinner("Buscando dólar e CBOT futuros..."):
            resultado = montar_projecao_completa(
                df_basis_proj, ultimo_cbot_hist, cidade_sel, meses_proj, auto_dol, auto_cbot,
                anos_janela_basis, dias_janela_basis, cache_key,
            )

        if resultado is None:
            st.error("Não foi possível obter a cotação do dólar por nenhuma fonte.")
        else:
            if resultado["avisos"]:
                st.warning(" · ".join(resultado["avisos"]))
            if resultado["fontes"]:
                st.caption("Fontes: " + " · ".join(resultado["fontes"]))

            projecao_diaria = resultado["projecao_diaria"]
            mensal = resultado["mensal"]
            preco_hoje = projecao_diaria.sort_values("data").iloc[0]["preco_rs_saca"]
            preco_12m = mensal.iloc[min(11, len(mensal) - 1)]["preco_medio_rs_saca"]

            st.markdown(f"""
            <div class="kpi-row">
                <div class="kpi-card">
                    <div class="kpi-label">Dólar spot</div>
                    <div class="kpi-value">R$ {resultado['spot_dolar']:.4f}</div>
                    <div class="kpi-sub">{resultado['fonte_dolar_spot']}</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-label">CBOT spot atual</div>
                    <div class="kpi-value">US$ {resultado['cbot_ancora']:.2f}/bu</div>
                    <div class="kpi-sub">{resultado['fonte_cbot_spot']}</div>
                </div>
                <div class="kpi-card highlight">
                    <div class="kpi-label">Preço projetado hoje</div>
                    <div class="kpi-value">R$ {preco_hoje:.2f}</div>
                    <div class="kpi-sub">por saca — {cidade_sel}</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-label">Projeção 12 meses</div>
                    <div class="kpi-value">R$ {preco_12m:.2f}</div>
                    <div class="kpi-sub">por saca</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)
            st.plotly_chart(grafico_linha_precos_proj(projecao_diaria, mensal), use_container_width=True,
                             config={"displayModeBar": False})
            st.markdown('</div>', unsafe_allow_html=True)

            st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)
            st.plotly_chart(grafico_barras_precos_proj(mensal), use_container_width=True,
                             config={"displayModeBar": True, "displaylogo": False,
                                      "toImageButtonOptions": {"format": "png", "scale": 2,
                                                                "filename": f"projecao_{cidade_sel}"}})
            st.markdown('</div>', unsafe_allow_html=True)

            with st.expander("⚙️ Ver / editar curvas usadas no cálculo (dólar e CBOT)"):
                st.markdown("**Dólar futuro (DOL)**")
                st.dataframe(resultado["curva_dol"], use_container_width=True, hide_index=True)
                st.markdown("**CBOT (ZS, US$/bushel)**")
                st.dataframe(resultado["curva_cbot"], use_container_width=True, hide_index=True)

            with st.expander("ℹ️ Metodologia da projeção"):
                st.markdown(f"""
- **Preço projetado (R$/saca)** = [CBOT futuro (US$/bushel) + basis projetado] × 2,2046 × câmbio futuro (R$/US$)
- **Basis projetado**: média das observações de basis de **{cidade_sel}** dentro de uma janela de ±{dias_janela_basis} dias-calendário em torno da mesma data, nos últimos {anos_janela_basis} anos
- **Dólar futuro**: contratos DOL da B3 via TradingView, interpolados por dias úteis (fallback manual se a busca falhar)
- **CBOT futuro**: contratos ZS via TradingView, mesma lógica de interpolação

> ⚠️ Simulador informativo/educacional. Não representa recomendação de investimento nem preço negociável de hedge.
                """)

with tab_mapa:
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)
    fig_mapa = grafico_mapa(df_basis)
    if fig_mapa is None:
        st.warning("Não há coordenadas cadastradas para as localidades da base.")
    else:
        st.plotly_chart(fig_mapa, use_container_width=True, config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)
