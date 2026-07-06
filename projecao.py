"""
Combina as três pontas do simulador:
  preço projetado (R$/saca) = [ CBOT futuro (US$/bushel) + basis projetado ] x 2,2046 x câmbio futuro

Usa as curvas diárias já interpoladas por dias úteis (dólar e CBOT) e o
modelo de basis sazonal (janela de +-N dias, média dos últimos M anos).
"""
import numpy as np
import pandas as pd

from basis_model import SACA_PARA_BUSHEL, curva_basis_projetado
from fontes_dolar import gerar_datas_mensais, contar_dias_uteis, MESES_ABREV


def calcular_curva_cbot_diaria(ultimo_preco_conhecido, curva_zs_mensal, meses_proj, data_base):
    """
    Mesma lógica de interpolação por dias úteis usada na curva do dólar,
    aplicada aos pontos mensais da curva CBOT.
    curva_zs_mensal precisa ter colunas 'data' e 'CBOT US$/bushel'.
    """
    base = pd.Timestamp(data_base).normalize()
    datas_mensais = gerar_datas_mensais(base, meses_proj)
    data_final = datas_mensais[-1]
    datas_diarias = pd.bdate_range(start=base, end=data_final)
    du_diarios = contar_dias_uteis(base, datas_diarias)
    du_mensais = contar_dias_uteis(base, datas_mensais)

    preco_m = curva_zs_mensal["CBOT US$/bushel"].astype(float).values
    du_ref = np.array(du_mensais, dtype=float)
    preco_ref = preco_m.astype(float)
    if du_ref[0] > 0:
        du_ref = np.insert(du_ref, 0, 0.0)
        preco_ref = np.insert(preco_ref, 0, float(ultimo_preco_conhecido))

    cbot_diario = np.interp(du_diarios, du_ref, preco_ref, left=preco_ref[0], right=preco_ref[-1])
    curva_diaria = pd.DataFrame({"data": datas_diarias, "cbot_usd_bushel": cbot_diario})
    return curva_diaria


def montar_projecao_precos(
    data_base,
    meses_proj: int,
    curva_dolar_diaria: pd.DataFrame,   # colunas: data, ndf
    curva_cbot_diaria: pd.DataFrame,    # colunas: data, cbot_usd_bushel
    df_basis_hist: pd.DataFrame,
    anos_janela: int = 5,
    dias_janela: int = 5,
) -> pd.DataFrame:
    """Monta a curva diária projetada de preço da soja em R$/saca."""
    base_merge = curva_dolar_diaria.merge(curva_cbot_diaria, on="data", how="inner")

    basis_curva = curva_basis_projetado(
        df_basis_hist, base_merge["data"], anos_janela=anos_janela, dias_janela=dias_janela
    )
    df = base_merge.merge(basis_curva, on="data", how="left")

    df["preco_usd_bushel"] = df["cbot_usd_bushel"] + df["basis_projetado_usd_bushel"]
    df["preco_usd_saca"] = df["preco_usd_bushel"] * SACA_PARA_BUSHEL
    df["preco_rs_saca"] = df["preco_usd_saca"] * df["ndf"]

    df["referencia"] = df["data"].apply(lambda d: f"{MESES_ABREV[int(d.month)]}/{str(int(d.year))[-2:]}")
    return df


def resumo_mensal(df_diario: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega a curva diária projetada em médias mensais - usado no gráfico
    de barras de preços médios por mês futuro.
    """
    df = df_diario.copy()
    df["ano_mes"] = df["data"].dt.to_period("M")
    mensal = (
        df.groupby("ano_mes", as_index=False)
        .agg(
            data_ref=("data", "last"),
            referencia=("referencia", "last"),
            preco_medio_rs_saca=("preco_rs_saca", "mean"),
            preco_medio_usd_bushel=("preco_usd_bushel", "mean"),
            cbot_medio_usd_bushel=("cbot_usd_bushel", "mean"),
            basis_medio_usd_bushel=("basis_projetado_usd_bushel", "mean"),
            dolar_medio=("ndf", "mean"),
        )
        .sort_values("ano_mes")
    )
    return mensal.drop(columns="ano_mes")
