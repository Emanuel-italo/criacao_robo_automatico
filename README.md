<<<<<<< HEAD
# criacao_robo_automatico
=======
# Caio — Assistente Virtual (Docker + robôs Python)

Front estático servido por Nginx + backend Flask que orquestra robôs Python.
Clicar em um card do painel lateral dispara o robô correspondente e devolve os dados no chat.

```
caio/
├── docker-compose.yml
├── backend/               # Flask + gunicorn (porta interna 8000)
│   ├── app.py             # orquestrador: rotas, jobs, timeouts
│   └── robos/
│       ├── registry.py       # catálogo + helpers de resposta
│       ├── orcamento.py      # card Orçamento: menu de 4 ações (pandas)
│       └── em_construcao.py  # placeholder / molde para novos robôs
├── dados/                 # planilhas de entrada (orcamento.xlsx)
└── frontend/              # Nginx (porta 8080)
    ├── index.html  style.css  script.js
    ├── robos.js           # integração card -> robô
    └── nginx.conf         # proxy /api -> backend
```

## Subir

```bash
docker compose up --build -d
docker compose logs -f backend
```

Acesse **http://localhost:8080**. Para derrubar: `docker compose down` (use `-v` para apagar os relatórios gerados).

## Como funciona o clique no card

O card não executa nada direto: ele **engatilha** o robô, que responde com o menu.

```
1. clique no card        → POST /api/robos/orcamento/executar  {}          (sem "acao")
                         ← { tipo: "opcoes", opcoes: [4 alternativas] }
                         → o chat renderiza os 4 botões

2. clique na alternativa → POST /api/robos/orcamento/executar  { acao: "desvios" }
                         ← se faltar planilha: { tipo: "solicitar_arquivo" }
                           o chat abre o seletor de arquivo sozinho

3. upload da planilha    → POST /api/upload (multipart)
                         ← { arquivo_id, colunas, tamanho_kb }
                           o front guarda o arquivo_id e RETOMA a ação pendente

4. execução              → POST .../executar { acao: "desvios", arquivo_id: "..." }
                         ← { tipo: "tabela", colunas, linhas } → renderizado no chat
```

O `arquivo_id` fica na sessão do navegador: uma planilha enviada serve para todas as ações seguintes, até o usuário remover pelo "x" do chip.

Robôs demorados (`modo="async"`, como o DWL) usam `POST /api/robos/<id>/jobs` → `202` com `job_id`, e o front faz polling em `GET /api/jobs/<job_id>`. Assim o Nginx nunca segura conexão aberta por minutos.

## Endpoints

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/health` | healthcheck do container |
| GET | `/api/robos` | catálogo de robôs |
| POST | `/api/robos/<id>/executar` | execução síncrona |
| POST | `/api/robos/<id>/jobs` | dispara job em background |
| GET | `/api/jobs/<job_id>` | status/resultado do job |
| GET | `/api/arquivos/<nome>` | download de arquivo gerado |
| POST | `/api/consultar-nota` | compatibilidade com o fluxo de chat existente |

## Adicionar um robô novo

1. Crie `backend/robos/meu_robo.py`:

```python
from .registry import robo, resposta_tabela

@robo(id="turnover", nome="Turnover", descricao="Índice mensal", timeout=120)
def executar(params: dict) -> dict:
    df = consulta_real(params)          # SQL, API, Excel, RPA...
    return resposta_tabela(
        titulo="Turnover",
        resumo=f"{len(df)} registros",
        colunas=list(df.columns),
        linhas=df.values.tolist(),
    )
```

2. Importe em `robos/__init__.py`.
3. Adicione o card no `index.html` com `onclick="showService('turnover')"` e a entrada em `MAPA_CARD_ROBO` no `robos.js`.

Tipos de resposta disponíveis: `resposta_tabela`, `resposta_kv`, `resposta_texto`, `resposta_arquivo` — o front renderiza cada um automaticamente.

## Correção incluída

O `script.js` original chamava `/api/consultar-nota` enquanto o `backend.py` expunha `/consultar-nota` — nunca conectava. O proxy do Nginx e o prefixo `/api` no Flask resolvem isso.

## Antes da homologação

- **Autenticação**: `getAuthToken()` lê `localStorage`, mas nenhuma rota valida o token. Adicione um `@before_request` no Flask validando o JWT/SSO corporativo.
- **Jobs em memória**: `_jobs` é um dict do processo, por isso o gunicorn roda com `--workers 1 --threads 8`. Para escalar, troque por Redis/RQ ou Celery.
- **Segredos**: use variáveis de ambiente ou o cofre corporativo — nunca credenciais no código dos robôs.
- **TLS**: o Nginx sobe em HTTP na 8080; o certificado normalmente fica no ingress/balanceador.
- **Dados sensíveis**: se algum robô tocar em matrícula ou dado pessoal, aplique a mesma regra de agregação (contagens/percentuais) que você já usa nos outros relatórios.
- **LGPD/logs**: os logs registram os parâmetros enviados ao robô. Se forem trafegar dados pessoais, remova `params=%s` da linha de log em `app.py`.


## Planilha de orçamento

O robô procura os dados nesta ordem:

1. **planilha enviada no chat** (clipe ao lado do campo de mensagem) — `.xlsx`, `.xls` ou `.csv`, até 25 MB
2. `dados/orcamento.xlsx` — base fixa opcional, lida a cada clique, sem rebuild
3. base de exemplo — só se as duas anteriores faltarem

Colunas aceitas (o robô normaliza acentos e variações): `Diretoria`, `Centro de Custo` / `CC`, `Rubrica` / `Descrição`, `Orçado` / `Budget` / `Previsto`, `Realizado` / `Consumido` / `Gasto`. Só `orçado` e `realizado` são obrigatórias — faltando alguma, o robô diz qual é e lista as colunas que encontrou.

### As 4 ações

| Ação | O que faz |
|---|---|
| Consolidado | Agrupa por CC: orçado, realizado, saldo, % de consumo |
| Desvios | Só os CCs acima de 90%, marcando os já estourados |
| Projeção | Run-rate: extrapola o realizado até dezembro e mostra quem fecha no vermelho |
| Exportar | Gera `.xlsx` com abas Consolidado e Detalhado, devolve link de download |

Uploads ficam em volume Docker (`uploads:`) com nome aleatório — o nome original do usuário nunca vira nome de arquivo em disco.

## Acesso pela rede

`ports: "8080:8080"` já publica em todas as interfaces. Falta liberar o firewall do Windows (PowerShell como admin):

```powershell
New-NetFirewallRule -DisplayName "Caio 8080" -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow
```

Colegas acessam por `http://SEU-IP:8080` (veja o IP com `ipconfig`). **Nenhuma rota exige autenticação hoje** — não exponha na rede com dado real antes disso.

## Playwright (próxima fase)

Robôs de navegador precisam do Chromium e das libs do sistema. No `backend/Dockerfile`:

```dockerfile
RUN pip install --no-cache-dir playwright==1.48.0 && playwright install --with-deps chromium
```

Rode-os com `modo="async"` no decorador e adicione o id em `ROBOS_ASSINCRONOS` no `robos.js` — navegação leva minutos e não pode segurar a conexão HTTP. Use a API síncrona do Playwright (`sync_playwright`), que funciona bem dentro do ThreadPool do orquestrador.


## Adicionar ações a um robô

O menu é só uma lista no topo do arquivo. Em `robos/orcamento.py`:

```python
_ACOES = [
    {"acao": "consolidado", "rotulo": "Consolidado por centro de custo"},
    {"acao": "reajuste",    "rotulo": "Simular reajuste"},   # nova
]
```

Depois trate o `acao` no fim do `executar()`. O front não muda: ele renderiza os botões a partir do que o robô devolve.
>>>>>>> develop
