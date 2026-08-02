"""
Robô: Vagas — insere posições no SharePoint de Recrutamento e Seleção.

FLUXO
    1. clique no card                 -> menu com 4 ações
    2. "Validar planilha"             -> confere tudo sem gravar nada (dry-run)
    3. "Inserir vagas no SharePoint"  -> grava item a item, com relatório linha a linha
    4. "Vagas já cadastradas"         -> lê a lista
    5. "Baixar modelo de planilha"    -> gera o .xlsx no formato esperado

Sem credencial configurada (ver sharepoint.py), as ações de escrita rodam em
MODO SIMULAÇÃO: validam e mostram o que seria enviado, sem tocar no SharePoint.
"""

import os
from datetime import date, datetime

import pandas as pd

from . import sharepoint
from .registry import (robo, resposta_tabela, resposta_opcoes,
                       resposta_solicitar_arquivo, resposta_arquivo)

PASTA_UPLOADS = os.environ.get("PASTA_UPLOADS", "/app/uploads")
PASTA_SAIDA = os.environ.get("PASTA_SAIDA", "/app/arquivos")

_ACOES = [
    {"acao": "validar",  "rotulo": "Validar planilha de vagas"},
    {"acao": "inserir",  "rotulo": "Inserir vagas no SharePoint"},
    {"acao": "listar",   "rotulo": "Ver vagas já cadastradas"},
    {"acao": "modelo",   "rotulo": "Baixar modelo de planilha"},
]

# coluna interna -> (nomes aceitos na planilha, obrigatória, campo no SharePoint)
_CAMPOS = {
    "titulo":       (["Título", "titulo", "cargo", "posição", "posicao"], True,  "Title"),
    "area":         (["Área", "area", "diretoria"],                        True,  "Area"),
    "centro_custo": (["Centro de Custo", "centro_custo", "cc"],            True,  "CentroCusto"),
    "tipo":         (["Tipo", "tipo de vaga"],                             True,  "TipoVaga"),
    "senioridade":  (["Senioridade", "nivel", "nível"],                    False, "Senioridade"),
    "quantidade":   (["Quantidade", "qtd", "vagas"],                       False, "Quantidade"),
    "gestor":       (["Gestor", "gestor responsavel", "requisitante"],     False, "Gestor"),
    "abertura":     (["Data de Abertura", "abertura", "data"],             False, "DataAbertura"),
}

_TIPOS_VALIDOS = {"nova", "substituição", "substituicao", "backfill", "temporária", "temporaria"}


# ---------------------------------------------------------------------------
# Leitura e validação
# ---------------------------------------------------------------------------

def _ler(caminho: str) -> pd.DataFrame:
    if caminho.lower().endswith(".csv"):
        return pd.read_csv(caminho, sep=None, engine="python")
    return pd.read_excel(caminho)


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    mapa = {}
    for interno, (aceitos, _, _) in _CAMPOS.items():
        for col in df.columns:
            if str(col).strip().lower() in [a.lower() for a in aceitos]:
                mapa[col] = interno
                break
    return df.rename(columns=mapa)


def _validar_linhas(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Devolve (df com coluna 'erros', lista de erros estruturais da planilha)."""
    estruturais = []
    for interno, (aceitos, obrigatoria, _) in _CAMPOS.items():
        if obrigatoria and interno not in df.columns:
            estruturais.append(f"coluna obrigatória ausente: {aceitos[0]}")
    if estruturais:
        return df, estruturais

    def erros_da_linha(r):
        e = []
        for interno, (aceitos, obrigatoria, _) in _CAMPOS.items():
            if obrigatoria:
                valor = r.get(interno)
                if pd.isna(valor) or str(valor).strip() == "":
                    e.append(f"{aceitos[0]} vazio")
        tipo = str(r.get("tipo", "")).strip().lower()
        if tipo and tipo not in _TIPOS_VALIDOS:
            e.append(f"tipo inválido ({r.get('tipo')})")
        qtd = r.get("quantidade")
        if not pd.isna(qtd) and str(qtd).strip() != "":
            try:
                if int(float(qtd)) < 1:
                    e.append("quantidade menor que 1")
            except (ValueError, TypeError):
                e.append("quantidade não numérica")
        return "; ".join(e)

    df = df.copy()
    df["erros"] = df.apply(erros_da_linha, axis=1)
    return df, []


def _carregar_validado(params: dict):
    """(df, erros_estruturais) ou (None, None) quando não há arquivo."""
    arquivo_id = params.get("arquivo_id")
    if not arquivo_id:
        return None, None
    caminho = os.path.join(PASTA_UPLOADS, os.path.basename(str(arquivo_id)))
    if not os.path.exists(caminho):
        return None, None
    df = _normalizar(_ler(caminho))
    return _validar_linhas(df)


def _txt(valor) -> str:
    """Evita 'nan' aparecendo no chat quando a célula está vazia."""
    return "—" if valor is None or pd.isna(valor) or str(valor).strip() == "" else str(valor)


def _para_sharepoint(r) -> dict:
    campos = {}
    for interno, (_, _, campo_sp) in _CAMPOS.items():
        valor = r.get(interno)
        if pd.isna(valor) or str(valor).strip() == "":
            continue
        if interno == "abertura":
            try:
                valor = pd.to_datetime(valor).strftime("%Y-%m-%d")
            except Exception:
                valor = str(valor)
        elif interno == "quantidade":
            valor = int(float(valor))
        else:
            valor = str(valor).strip()
        campos[campo_sp] = valor
    return campos


# ---------------------------------------------------------------------------
# Robô
# ---------------------------------------------------------------------------

@robo(
    id="vagas",
    nome="Vagas (R&S)",
    descricao="Cadastro de vagas no SharePoint de Recrutamento e Seleção",
    timeout=300,
)
def executar(params: dict) -> dict:
    acao = (params.get("acao") or "").strip()

    if not acao:
        aviso = ("" if sharepoint.configurado()
                 else "<br><small>Sem credencial do SharePoint configurada: "
                      "a inserção roda em modo simulação.</small>")
        return resposta_opcoes(
            titulo="Vagas — Recrutamento e Seleção",
            texto="Robô de vagas engatilhado. O que você deseja fazer?" + aviso,
            opcoes=_ACOES,
        )

    if acao == "modelo":
        return _acao_modelo()
    if acao == "listar":
        return _acao_listar()
    if acao in ("validar", "inserir"):
        df, estruturais = _carregar_validado(params)
        if df is None:
            return resposta_solicitar_arquivo(
                titulo="Envie a planilha de vagas",
                texto=("Preciso da planilha para continuar. As colunas obrigatórias são "
                       "<strong>Título</strong>, <strong>Área</strong>, "
                       "<strong>Centro de Custo</strong> e <strong>Tipo</strong>.<br>"
                       "Se preferir, baixe o modelo pela opção anterior."),
            )
        if estruturais:
            return resposta_tabela(
                titulo="Planilha fora do formato",
                resumo="Corrija e envie novamente: " + " · ".join(estruturais),
                colunas=[], linhas=[],
            )
        return _acao_validar(df) if acao == "validar" else _acao_inserir(df)

    return resposta_opcoes(titulo="Vagas — Recrutamento e Seleção",
                           texto="Não reconheci essa opção. Escolha uma das alternativas:",
                           opcoes=_ACOES)


def _acao_validar(df: pd.DataFrame) -> dict:
    invalidas = df[df["erros"] != ""]
    validas = len(df) - len(invalidas)

    if invalidas.empty:
        return resposta_tabela(
            titulo="Validação concluída",
            resumo=f"{validas} vaga(s) prontas para inserção. Nenhum erro encontrado.",
            colunas=["Linha", "Título", "Área", "Centro de custo", "Tipo"],
            linhas=[[i + 2, _txt(r.get("titulo")), _txt(r.get("area")),
                     _txt(r.get("centro_custo")), _txt(r.get("tipo"))]
                    for i, r in df.iterrows()],
        )

    return resposta_tabela(
        titulo="Validação concluída com pendências",
        resumo=f"{validas} vaga(s) ok · {len(invalidas)} com erro. "
               f"Corrija as linhas abaixo antes de inserir.",
        colunas=["Linha", "Título", "Erros"],
        linhas=[[i + 2, _txt(r.get("titulo")), r["erros"]] for i, r in invalidas.iterrows()],
    )


def _acao_inserir(df: pd.DataFrame) -> dict:
    invalidas = df[df["erros"] != ""]
    if not invalidas.empty:
        return resposta_tabela(
            titulo="Inserção bloqueada",
            resumo=f"{len(invalidas)} linha(s) com erro. Nada foi gravado — "
                   f"corrija a planilha e tente de novo.",
            colunas=["Linha", "Título", "Erros"],
            linhas=[[i + 2, _txt(r.get("titulo")), r["erros"]] for i, r in invalidas.iterrows()],
        )

    simulacao = not sharepoint.configurado()
    linhas, sucesso, falha = [], 0, 0

    for i, r in df.iterrows():
        campos = _para_sharepoint(r)
        if simulacao:
            linhas.append([i + 2, _txt(r.get("titulo")), "Simulado", "—"])
            sucesso += 1
            continue
        try:
            item = sharepoint.inserir_item(campos)
            linhas.append([i + 2, _txt(r.get("titulo")), "Inserida", item.get("id", "—")])
            sucesso += 1
        except Exception as e:
            linhas.append([i + 2, _txt(r.get("titulo")), "Falhou", str(e)[:120]])
            falha += 1

    resumo = (f"{sucesso} vaga(s) inserida(s)" if not simulacao
              else f"{sucesso} vaga(s) validada(s) em modo simulação — nada foi gravado")
    if falha:
        resumo += f" · {falha} falha(s)"

    return resposta_tabela(
        titulo="Resultado da inserção",
        resumo=resumo,
        colunas=["Linha", "Título", "Situação", "ID / detalhe"],
        linhas=linhas,
    )


def _acao_listar() -> dict:
    if not sharepoint.configurado():
        return resposta_tabela(
            titulo="Vagas cadastradas",
            resumo="Credencial do SharePoint não configurada — não consigo ler a lista.",
            colunas=[], linhas=[],
        )
    try:
        itens = sharepoint.listar_itens()
    except Exception as e:
        return resposta_tabela(titulo="Vagas cadastradas",
                               resumo=f"Erro ao consultar: {e}",
                               colunas=[], linhas=[])
    if not itens:
        return resposta_tabela(titulo="Vagas cadastradas",
                               resumo="A lista está vazia.", colunas=[], linhas=[])

    return resposta_tabela(
        titulo="Vagas cadastradas",
        resumo=f"{len(itens)} vaga(s) na lista",
        colunas=["Título", "Área", "Centro de custo", "Tipo", "Abertura"],
        linhas=[[it.get("Title", "—"), it.get("Area", "—"), it.get("CentroCusto", "—"),
                 it.get("TipoVaga", "—"), (it.get("DataAbertura") or "—")[:10]]
                for it in itens],
    )


def _acao_modelo() -> dict:
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    exemplo = pd.DataFrame([
        {"Título": "Analista de Dados Pleno", "Área": "Tecnologia",
         "Centro de Custo": "CC-2210", "Tipo": "Nova", "Senioridade": "Pleno",
         "Quantidade": 2, "Gestor": "Ana Souza", "Data de Abertura": date.today()},
        {"Título": "Especialista em RPA", "Área": "Operações",
         "Centro de Custo": "CC-1042", "Tipo": "Substituição", "Senioridade": "Sênior",
         "Quantidade": 1, "Gestor": "Carlos Lima", "Data de Abertura": date.today()},
    ])
    nome = f"modelo_vagas_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    exemplo.to_excel(os.path.join(PASTA_SAIDA, nome), index=False)
    return resposta_arquivo(
        titulo="Modelo de planilha de vagas",
        resumo="Obrigatórias: Título, Área, Centro de Custo e Tipo. "
               "Tipo aceita: Nova, Substituição, Backfill ou Temporária.",
        url=f"/api/arquivos/{nome}",
        nome_arquivo=nome,
    )