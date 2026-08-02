"""
Cliente SharePoint via Microsoft Graph (autenticação app-only).

CONFIGURAÇÃO (variáveis de ambiente, definidas no docker-compose):
    SP_TENANT_ID        id do tenant (Entra ID)
    SP_CLIENT_ID        id do app registrado
    SP_CLIENT_SECRET    segredo do app
    SP_HOSTNAME         ex.: contoso.sharepoint.com
    SP_SITE_PATH        ex.: /sites/RecrutamentoSelecao
    SP_LISTA_VAGAS      nome de exibição da lista, ex.: Vagas

Sem essas variáveis o cliente entra em MODO SIMULAÇÃO: valida tudo e devolve
o que teria sido enviado, sem chamar o SharePoint. Isso permite demonstrar o
fluxo completo antes de a credencial corporativa ser liberada.

Permissão necessária no app registration: Sites.ReadWrite.All (application),
com consentimento do administrador.
"""

import os
import time
import logging

import requests

log = logging.getLogger("caio.sharepoint")

TENANT = os.environ.get("SP_TENANT_ID", "")
CLIENT_ID = os.environ.get("SP_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SP_CLIENT_SECRET", "")
HOSTNAME = os.environ.get("SP_HOSTNAME", "")
SITE_PATH = os.environ.get("SP_SITE_PATH", "")
LISTA = os.environ.get("SP_LISTA_VAGAS", "Vagas")

GRAPH = "https://graph.microsoft.com/v1.0"
TIMEOUT = 30

_cache = {"token": None, "expira_em": 0, "site_id": None, "lista_id": None}


def configurado() -> bool:
    """False quando falta credencial: o robô roda em modo simulação."""
    return all([TENANT, CLIENT_ID, CLIENT_SECRET, HOSTNAME, SITE_PATH])


def _token() -> str:
    if _cache["token"] and time.time() < _cache["expira_em"]:
        return _cache["token"]

    resp = requests.post(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    dados = resp.json()
    _cache["token"] = dados["access_token"]
    # renova 60s antes de expirar
    _cache["expira_em"] = time.time() + int(dados.get("expires_in", 3600)) - 60
    return _cache["token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def _site_id() -> str:
    if _cache["site_id"]:
        return _cache["site_id"]
    r = requests.get(f"{GRAPH}/sites/{HOSTNAME}:{SITE_PATH}",
                     headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    _cache["site_id"] = r.json()["id"]
    return _cache["site_id"]


def _lista_id() -> str:
    if _cache["lista_id"]:
        return _cache["lista_id"]
    r = requests.get(f"{GRAPH}/sites/{_site_id()}/lists",
                     headers=_headers(), params={"$select": "id,displayName"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    for lst in r.json().get("value", []):
        if lst["displayName"].strip().lower() == LISTA.strip().lower():
            _cache["lista_id"] = lst["id"]
            return _cache["lista_id"]
    raise RuntimeError(f"Lista '{LISTA}' não encontrada no site {SITE_PATH}.")


def inserir_item(campos: dict) -> dict:
    """Cria um item na lista. Devolve {'id': ...} ou levanta exceção."""
    r = requests.post(
        f"{GRAPH}/sites/{_site_id()}/lists/{_lista_id()}/items",
        headers=_headers(), json={"fields": campos}, timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"SharePoint respondeu {r.status_code}: {r.text[:300]}")
    return {"id": r.json().get("id")}


def listar_itens(limite: int = 50) -> list[dict]:
    """Lê os itens já cadastrados na lista."""
    r = requests.get(
        f"{GRAPH}/sites/{_site_id()}/lists/{_lista_id()}/items",
        headers=_headers(),
        params={"expand": "fields", "$top": limite},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return [item.get("fields", {}) for item in r.json().get("value", [])]