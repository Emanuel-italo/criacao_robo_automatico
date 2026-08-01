"""Importa todos os robôs para que se auto-registrem no catálogo."""

from . import orcamento, em_construcao          # noqa: F401  (cards do painel)
from .registry import CATALOGO, obter, listar   # noqa: F401
