"""
Robô: placeholder para cards ainda não implementados.

Use este arquivo como molde ao criar o próximo robô: copie, troque o id,
o nome e o corpo da função `executar`.
"""

from .registry import robo, resposta_texto


@robo(
    id="em_construcao",
    nome="Em construção",
    descricao="Serviço em desenvolvimento",
    timeout=15,
)
def executar(params: dict) -> dict:
    return resposta_texto(
        titulo="Em construção",
        texto=(
            "Esse serviço ainda está sendo desenvolvido.<br><br>"
            "Por enquanto, o serviço disponível é o de <strong>Orçamento</strong>, "
            "no painel à esquerda."
        ),
    )