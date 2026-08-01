"""
Robô: Orçamento — atende o BP em duas etapas.

ETAPA 1 (clique no card, sem `acao`)
    Devolve o menu com as 4 alternativas.

ETAPA 2 (clique na alternativa, com `acao`)
    Executa a rotina escolhida. Se a ação precisar de dados e nenhuma planilha
    tiver sido enviada, o robô pede o arquivo (o chat abre o seletor sozinho).

FONTES DE DADOS, nesta ordem de prioridade:
    1. planilha enviada pelo usuário no chat  (params["arquivo_id"])
    2. dados/orcamento.xlsx                   (volume do compose)
    3. base de exemplo                        (para validar o fluxo)
"""

import os
from datetime import date

import pandas as pd

from .registry import (robo, resposta_tabela, resposta_opcoes,
                       resposta_solicitar_arquivo, resposta_arquivo, brl)

PASTA_DADOS = os.environ.get("PASTA_DADOS", "/app/dados")
PASTA_UPLOADS = os.environ.get("PASTA_UPLOADS", "/app/uploads")
PASTA_SAIDA = os.environ.get("PASTA_SAIDA", "/app/arquivos")
ARQUIVO_PADRAO = os.path.join(PASTA_DADOS, "orcamento.xlsx")

# Aceita variações de nomenclatura da planilha -> nome interno
_COLUNAS = {
    "diretoria": "diretoria", "área": "diretoria", "area": "diretoria",
    "centro_custo": "centro_custo", "centro de custo": "centro_custo",
    "cc": "centro_custo", "ccusto": "centro_custo",
    "descricao": "descricao", "descrição": "descricao", "rubrica": "descricao",
    "orcado": "orcado", "orçado": "orcado", "budget": "orcado", "previsto": "orcado",
    "realizado": "realizado", "consumido": "realizado", "gasto": "realizado",
}

_ACOES = [
    {"acao": "consolidado", "rotulo": "Consolidado por centro de custo"},
    {"acao": "desvios",     "rotulo": "Ver apenas os desvios"},
    {"acao": "projecao",    "rotulo": "Projetar fechamento do ano"},
    {"acao": "exportar",    "rotulo": "Exportar relatório em Excel"},
]

# Ações que não conseguem rodar sem dados
_EXIGEM_DADOS = {"consolidado", "desvios", "projecao", "exportar"}

_EXEMPLO = pd.DataFrame([
    {"diretoria": "Operações", "centro_custo": "CC-1042", "descricao": "Pessoal CLT",
     "orcado": 1_850_000.00, "realizado": 1_612_400.00},
    {"diretoria": "Operações", "centro_custo": "CC-1042", "descricao": "Terceiros",
     "orcado": 420_000.00, "realizado": 468_900.00},
    {"diretoria": "Tecnologia", "centro_custo": "CC-2210", "descricao": "Pessoal CLT",
     "orcado": 3_100_000.00, "realizado": 2_744_000.00},
    {"diretoria": "Tecnologia", "centro_custo": "CC-2210", "descricao": "Licenças",
     "orcado": 260_000.00, "realizado": 251_300.00},
    {"diretoria": "Comercial", "centro_custo": "CC-3305", "descricao": "Pessoal CLT",
     "orcado": 980_000.00, "realizado": 1_048_700.00},
])


# ---------------------------------------------------------------------------
# Carga e preparo (miolo pandas)
# ---------------------------------------------------------------------------

def _ler(caminho: str) -> pd.DataFrame:
    if caminho.lower().endswith(".csv"):
        return pd.read_csv(caminho, sep=None, engine="python")
    return pd.read_excel(caminho)


def _normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [_COLUNAS.get(str(c).strip().lower(), str(c).strip().lower())
                  for c in df.columns]
    return df


def carregar(params: dict) -> tuple[pd.DataFrame, str]:
    """Devolve (df, origem): 'enviado', 'padrao' ou 'exemplo'."""
    arquivo_id = params.get("arquivo_id")
    if arquivo_id:
        caminho = os.path.join(PASTA_UPLOADS, os.path.basename(str(arquivo_id)))
        if os.path.exists(caminho):
            return _normalizar_colunas(_ler(caminho)), "enviado"

    if os.path.exists(ARQUIVO_PADRAO):
        return _normalizar_colunas(_ler(ARQUIVO_PADRAO)), "padrao"

    return _EXEMPLO.copy(), "exemplo"


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Valida colunas, converte tipos e calcula saldo e consumo."""
    faltando = {"orcado", "realizado"} - set(df.columns)
    if faltando:
        raise ValueError(
            f"A planilha não tem a(s) coluna(s): {', '.join(sorted(faltando))}. "
            f"Colunas encontradas: {', '.join(map(str, df.columns))}"
        )

    for col in ("orcado", "realizado"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if "diretoria" not in df.columns:
        df["diretoria"] = "—"
    if "centro_custo" not in df.columns:
        df["centro_custo"] = "—"

    df["saldo"] = df["orcado"] - df["realizado"]
    df["consumo_pct"] = (df["realizado"] / df["orcado"].replace(0, pd.NA) * 100).fillna(0)
    return df


def _consolidar(df: pd.DataFrame) -> pd.DataFrame:
    ag = (df.groupby(["diretoria", "centro_custo"], as_index=False)
            .agg(orcado=("orcado", "sum"), realizado=("realizado", "sum")))
    ag["saldo"] = ag["orcado"] - ag["realizado"]
    ag["consumo_pct"] = (ag["realizado"] / ag["orcado"].replace(0, pd.NA) * 100).fillna(0)
    return ag.sort_values("consumo_pct", ascending=False)


def _nota_origem(origem: str) -> str:
    return {
        "enviado": " · planilha enviada por você",
        "padrao": " · base dados/orcamento.xlsx",
        "exemplo": " · base de exemplo",
    }.get(origem, "")


# ---------------------------------------------------------------------------
# Robô
# ---------------------------------------------------------------------------

@robo(
    id="orcamento",
    nome="Orçamento",
    descricao="Consolidado, desvios, projeção e exportação",
    timeout=180,
)
def executar(params: dict) -> dict:
    acao = (params.get("acao") or "").strip()

    # Etapa 1: card clicado, ainda sem ação escolhida
    if not acao:
        return resposta_opcoes(
            titulo="Orçamento",
            texto="Robô de orçamento engatilhado. O que você deseja fazer?",
            opcoes=_ACOES,
        )

    if acao not in {a["acao"] for a in _ACOES}:
        return resposta_opcoes(
            titulo="Orçamento",
            texto="Não reconheci essa opção. Escolha uma das alternativas:",
            opcoes=_ACOES,
        )

    df, origem = carregar(params)

    # Sem planilha do usuário e sem base padrão: pede o arquivo
    if acao in _EXIGEM_DADOS and origem == "exemplo" and not params.get("aceita_exemplo"):
        return resposta_solicitar_arquivo(
            titulo="Envie a planilha de orçamento",
            texto=("Preciso da base para essa análise. Envie um .xlsx ou .csv com as colunas "
                   "<strong>Diretoria</strong>, <strong>Centro de Custo</strong>, "
                   "<strong>Orçado</strong> e <strong>Realizado</strong>."),
        )

    df = preparar(df)

    if acao == "consolidado":
        return _acao_consolidado(df, origem)
    if acao == "desvios":
        return _acao_desvios(df, origem)
    if acao == "projecao":
        return _acao_projecao(df, origem, params)
    return _acao_exportar(df, origem)


def _acao_consolidado(df, origem):
    ag = _consolidar(df)
    total_o, total_r = ag["orcado"].sum(), ag["realizado"].sum()
    estourados = int((ag["consumo_pct"] > 100).sum())
    pct = (total_r / total_o * 100) if total_o else 0
    return resposta_tabela(
        titulo="Consolidado por centro de custo",
        resumo=(f"{brl(total_r)} de {brl(total_o)} ({pct:.1f}% consumido) · "
                f"{estourados} CC acima do orçado{_nota_origem(origem)}"),
        colunas=["Diretoria", "Centro de custo", "Orçado", "Realizado", "Saldo", "Consumo"],
        linhas=[[r.diretoria, r.centro_custo, brl(r.orcado), brl(r.realizado),
                 brl(r.saldo), f"{r.consumo_pct:.1f}%"] for r in ag.itertuples()],
    )


def _acao_desvios(df, origem, limite: float = 90.0):
    ag = _consolidar(df)
    desvios = ag[ag["consumo_pct"] >= limite]
    if desvios.empty:
        return resposta_tabela(
            titulo="Desvios de orçamento",
            resumo=f"Nenhum centro de custo acima de {limite:.0f}% de consumo."
                   f"{_nota_origem(origem)}",
            colunas=[], linhas=[],
        )
    estourados = desvios[desvios["consumo_pct"] > 100]
    return resposta_tabela(
        titulo="Desvios de orçamento",
        resumo=(f"{len(desvios)} CC acima de {limite:.0f}% · {len(estourados)} já estourado(s) · "
                f"excedente {brl(abs(estourados['saldo'].sum()))}{_nota_origem(origem)}"),
        colunas=["Diretoria", "Centro de custo", "Orçado", "Realizado", "Saldo",
                 "Consumo", "Situação"],
        linhas=[[r.diretoria, r.centro_custo, brl(r.orcado), brl(r.realizado), brl(r.saldo),
                 f"{r.consumo_pct:.1f}%",
                 "Estourado" if r.consumo_pct > 100 else "Atenção"]
                for r in desvios.itertuples()],
    )


def _acao_projecao(df, origem, params):
    """Run-rate simples: extrapola o realizado dos meses decorridos até dezembro."""
    meses = int(params.get("meses_decorridos") or date.today().month)
    meses = max(1, min(12, meses))

    ag = _consolidar(df)
    ag["projetado"] = ag["realizado"] / meses * 12
    ag["saldo_projetado"] = ag["orcado"] - ag["projetado"]
    ag = ag.sort_values("saldo_projetado")

    risco = ag[ag["saldo_projetado"] < 0]
    return resposta_tabela(
        titulo=f"Projeção de fechamento (run-rate sobre {meses} mês(es))",
        resumo=(f"Projetado {brl(ag['projetado'].sum())} contra orçado "
                f"{brl(ag['orcado'].sum())} · {len(risco)} CC fecha(m) no vermelho"
                f"{_nota_origem(origem)}"),
        colunas=["Diretoria", "Centro de custo", "Orçado", "Realizado",
                 "Projetado dez", "Saldo projetado"],
        linhas=[[r.diretoria, r.centro_custo, brl(r.orcado), brl(r.realizado),
                 brl(r.projetado), brl(r.saldo_projetado)] for r in ag.itertuples()],
    )


def _acao_exportar(df, origem):
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    ag = _consolidar(df)
    ag["situacao"] = ag["consumo_pct"].apply(
        lambda p: "Estourado" if p > 100 else ("Atenção" if p >= 90 else "Dentro do previsto"))

    nome = f"orcamento_{date.today():%Y%m%d}_{os.urandom(3).hex()}.xlsx"
    caminho = os.path.join(PASTA_SAIDA, nome)

    with pd.ExcelWriter(caminho, engine="openpyxl") as xls:
        ag.rename(columns={
            "diretoria": "Diretoria", "centro_custo": "Centro de custo",
            "orcado": "Orçado", "realizado": "Realizado", "saldo": "Saldo",
            "consumo_pct": "Consumo %", "situacao": "Situação",
        }).to_excel(xls, sheet_name="Consolidado", index=False)
        df.to_excel(xls, sheet_name="Detalhado", index=False)

    return resposta_arquivo(
        titulo="Relatório de orçamento",
        resumo=f"{len(ag)} centro(s) de custo · 2 abas{_nota_origem(origem)}",
        url=f"/api/arquivos/{nome}",
        nome_arquivo=nome,
    )
