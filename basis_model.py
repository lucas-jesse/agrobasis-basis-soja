"""
Modelo de basis do simulador AgroBasis - Santa Rosa.

Contém:
- a regra de contrato de referência (mesma usada no cálculo do histórico)
- a projeção de basis por janela sazonal (média dos últimos N anos, +-J dias
  em torno da mesma data-calendário)
"""
import pandas as pd
import numpy as np

MESES_CONTRATOS = {"F": 1, "H": 3, "K": 5, "N": 7, "Q": 8, "U": 9, "X": 11}
NOME_CONTRATO = {"F": "Jan", "H": "Mar", "K": "Mai", "N": "Jul", "Q": "Ago", "U": "Set", "X": "Nov"}
DELIVERY_MONTHS = sorted(MESES_CONTRATOS.values())  # [1, 3, 5, 7, 8, 9, 11]
MONTH_TO_LETTER = {v: k for k, v in MESES_CONTRATOS.items()}

KG_POR_BUSHEL_SOJA = 27.2155
KG_POR_SACA = 60.0
SACA_PARA_BUSHEL = 2.2046  # 1 saca (60kg) = 2,2046 bushels


def contrato_referencia(data) -> str:
    """
    Regra: usa o contrato de vencimento imediatamente APÓS o mês corrente
    (nunca o contrato que vence no próprio mês corrente).
    Ex.: fevereiro -> H (mar), quando vira março -> K (mai).
    Novembro/dezembro -> F do ano seguinte (não há contrato G/J/M/O/dez para soja).
    """
    data = pd.Timestamp(data)
    mes, ano = data.month, data.year
    candidatos = [m for m in DELIVERY_MONTHS if m > mes]
    if candidatos:
        mes_venc = min(candidatos)
        ano_venc = ano
    else:
        mes_venc = 1
        ano_venc = ano + 1
    letra = MONTH_TO_LETTER[mes_venc]
    return f"ZS{letra}{str(ano_venc)[-2:]}"


def carregar_basis_historico(caminho_csv: str) -> pd.DataFrame:
    df = pd.read_csv(caminho_csv, parse_dates=["date"])
    df = df.rename(columns={"date": "Data"})
    df["Ano"] = df["Data"].dt.year
    df["DOY"] = df["Data"].dt.dayofyear
    df["MesDia"] = df["Data"].dt.strftime("%d/%m")
    return df.sort_values("Data").reset_index(drop=True)


def basis_projetado_sazonal(
    df_hist: pd.DataFrame,
    data_alvo,
    anos_janela: int = 5,
    dias_janela: int = 5,
    coluna: str = "basis_usd_bushel",
    ano_referencia: int | None = None,
):
    """
    Projeta o basis para `data_alvo` (mes/dia) como a média das observações
    históricas dentro de uma janela de +-`dias_janela` dias-calendário em
    torno da mesma data, nos últimos `anos_janela` anos anteriores ao
    `ano_referencia` (por padrão, o último ano disponível na base).

    Retorna (media, n_observacoes, anos_utilizados).
    """
    data_alvo = pd.Timestamp(data_alvo)
    if ano_referencia is None:
        ano_referencia = int(df_hist["Data"].dt.year.max())

    anos_alvo = list(range(ano_referencia - anos_janela, ano_referencia))
    valores = []
    for ano in anos_alvo:
        try:
            centro = pd.Timestamp(year=ano, month=data_alvo.month, day=data_alvo.day)
        except ValueError:
            # 29/fev em ano não-bissexto
            centro = pd.Timestamp(year=ano, month=data_alvo.month, day=28)
        ini = centro - pd.Timedelta(days=dias_janela)
        fim = centro + pd.Timedelta(days=dias_janela)
        janela = df_hist[(df_hist["Data"] >= ini) & (df_hist["Data"] <= fim)]
        valores.extend(janela[coluna].dropna().tolist())

    if not valores:
        return np.nan, 0, anos_alvo
    return float(np.mean(valores)), len(valores), anos_alvo


def curva_basis_projetado(
    df_hist: pd.DataFrame,
    datas_futuras: pd.DatetimeIndex,
    anos_janela: int = 5,
    dias_janela: int = 5,
    coluna: str = "basis_usd_bushel",
) -> pd.DataFrame:
    """Aplica basis_projetado_sazonal para uma sequência de datas futuras."""
    linhas = []
    for d in datas_futuras:
        media, n, anos = basis_projetado_sazonal(
            df_hist, d, anos_janela=anos_janela, dias_janela=dias_janela, coluna=coluna
        )
        linhas.append({
            "data": d,
            "basis_projetado_usd_bushel": media,
            "n_obs": n,
            "anos_base": f"{min(anos)}-{max(anos)}" if anos else "",
        })
    return pd.DataFrame(linhas)


def media_historica_por_dia_do_ano(
    df_hist: pd.DataFrame,
    ano_base: int,
    anos_janela: int = 5,
    janela_suavizacao: int = 11,
    coluna: str = "basis_usd_bushel",
) -> pd.DataFrame:
    """
    Série de referência (média histórica por dia-do-ano) para plotar como
    comparativo no gráfico de basis, no mesmo espírito do dashboard de
    basis de milho/soja já usado: média dos `anos_janela` anos anteriores
    a `ano_base`, com suavização por média móvel centrada.
    """
    anos_hist = list(range(ano_base - anos_janela, ano_base))
    hist = df_hist[df_hist["Ano"].isin(anos_hist)].copy()
    if hist.empty:
        return pd.DataFrame(columns=["DOY", "media_historica"])
    media = (
        hist.groupby("DOY", as_index=False)[coluna]
        .mean()
        .rename(columns={coluna: "media_historica"})
        .sort_values("DOY")
    )
    media["media_historica"] = (
        media["media_historica"].rolling(window=janela_suavizacao, center=True, min_periods=1).mean()
    )
    return media
