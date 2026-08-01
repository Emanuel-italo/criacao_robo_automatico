"""
Catálogo central de robôs.

Cada robô é uma função Python que recebe um dict de parâmetros e devolve
um dict no formato padrão de resposta (ver `resposta_tabela` / `resposta_texto`).

Para adicionar um robô novo:
    1. Crie o arquivo em robos/meu_robo.py com uma função `executar(params) -> dict`
    2. Registre com o decorador @robo(...) OU adicione em CATALOGO abaixo
    3. Aponte o card do front para o id do robô (data-robo="meu_robo")

Nenhuma outra camada precisa ser alterada.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, Any, List


@dataclass
class RoboSpec:
    id: str
    nome: str
    descricao: str
    funcao: Callable[[Dict[str, Any]], Dict[str, Any]]
    timeout: int = 60          # segundos - acima disso o robô é abortado
    params_obrigatorios: List[str] = field(default_factory=list)
    modo: str = "sync"         # "sync" (resposta imediata) ou "async" (job + polling)


CATALOGO: Dict[str, RoboSpec] = {}


def robo(id: str, nome: str, descricao: str = "", timeout: int = 60,
         params_obrigatorios: List[str] = None, modo: str = "sync"):
    """Decorador que registra a função no catálogo."""
    def _wrapper(func):
        CATALOGO[id] = RoboSpec(
            id=id,
            nome=nome,
            descricao=descricao,
            funcao=func,
            timeout=timeout,
            params_obrigatorios=params_obrigatorios or [],
            modo=modo,
        )
        return func
    return _wrapper


def obter(robo_id: str) -> RoboSpec | None:
    return CATALOGO.get(robo_id)


def listar() -> List[Dict[str, Any]]:
    return [
        {
            "id": r.id,
            "nome": r.nome,
            "descricao": r.descricao,
            "modo": r.modo,
            "params_obrigatorios": r.params_obrigatorios,
        }
        for r in CATALOGO.values()
    ]


# ---------------------------------------------------------------------------
# Helpers de resposta - use sempre estes para o front renderizar automaticamente
# ---------------------------------------------------------------------------

def resposta_tabela(titulo: str, colunas: List[str], linhas: List[List[Any]],
                    resumo: str = "") -> Dict[str, Any]:
    """Renderiza como tabela no chat."""
    return {"tipo": "tabela", "titulo": titulo, "resumo": resumo,
            "colunas": colunas, "linhas": linhas}


def resposta_texto(titulo: str, texto: str) -> Dict[str, Any]:
    """Renderiza como bloco de texto/HTML simples no chat."""
    return {"tipo": "texto", "titulo": titulo, "texto": texto}


def resposta_kv(titulo: str, itens: Dict[str, Any], resumo: str = "") -> Dict[str, Any]:
    """Renderiza como lista chave -> valor (ficha de detalhe)."""
    return {"tipo": "kv", "titulo": titulo, "resumo": resumo, "itens": itens}


def resposta_opcoes(titulo: str, texto: str, opcoes: List[Dict[str, str]]) -> Dict[str, Any]:
    """Renderiza como pergunta + botões. Cada opção: {"acao": "id", "rotulo": "texto"}.
    O clique reenvia o mesmo robô com params["acao"] preenchido."""
    return {"tipo": "opcoes", "titulo": titulo, "texto": texto, "opcoes": opcoes}


def resposta_solicitar_arquivo(titulo: str, texto: str) -> Dict[str, Any]:
    """Pede uma planilha ao usuário. O front abre o seletor de arquivo."""
    return {"tipo": "solicitar_arquivo", "titulo": titulo, "texto": texto}


def resposta_arquivo(titulo: str, url: str, nome_arquivo: str,
                     resumo: str = "") -> Dict[str, Any]:
    """Renderiza como link de download."""
    return {"tipo": "arquivo", "titulo": titulo, "url": url,
            "nome_arquivo": nome_arquivo, "resumo": resumo}


def brl(valor: float) -> str:
    """Formata número no padrão brasileiro: 18450.9 -> 'R$ 18.450,90'."""
    return "R$ " + f"{float(valor):,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
