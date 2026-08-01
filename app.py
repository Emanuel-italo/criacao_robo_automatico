"""
Caio - Backend orquestrador de robôs.

Endpoints:
    GET  /api/health                     -> healthcheck (usado pelo Docker)
    GET  /api/robos                      -> catálogo de robôs disponíveis
    POST /api/robos/<id>/executar        -> executa robô SÍNCRONO, devolve o resultado
    POST /api/robos/<id>/jobs            -> dispara robô ASSÍNCRONO, devolve job_id (202)
    GET  /api/jobs/<job_id>              -> status/resultado do job
    GET  /api/arquivos/<nome>            -> download de arquivo gerado por robô
    POST /api/upload                     -> recebe a planilha enviada no chat
"""

import os
import time
import uuid
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

import robos
from robos import registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("caio")

PASTA_SAIDA = os.environ.get("PASTA_SAIDA", "/app/arquivos")
PASTA_UPLOADS = os.environ.get("PASTA_UPLOADS", "/app/uploads")
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "4"))
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "25"))
EXTENSOES_OK = {".xlsx", ".xls", ".csv"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024
os.makedirs(PASTA_UPLOADS, exist_ok=True)

# Pool de execução dos robôs (não trava o worker do Flask)
_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="robo")

# Jobs assíncronos em memória.
# ATENÇÃO: em memória = 1 worker gunicorn (ver Dockerfile). Para escalar
# horizontalmente, troque este dict por Redis/RQ ou Celery.
_jobs: dict[str, dict] = {}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validar(spec: registry.RoboSpec, params: dict):
    faltando = [p for p in spec.params_obrigatorios if not params.get(p)]
    if faltando:
        return f"Parâmetro(s) obrigatório(s) ausente(s): {', '.join(faltando)}"
    return None


def _rodar(spec: registry.RoboSpec, params: dict) -> dict:
    inicio = time.perf_counter()
    dados = spec.funcao(params)
    return {
        "success": True,
        "robo": spec.id,
        "nome": spec.nome,
        "executado_em": _agora(),
        "duracao_ms": round((time.perf_counter() - inicio) * 1000),
        "dados": dados,
    }


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "robos": len(registry.CATALOGO)})


@app.get("/api/robos")
def listar_robos():
    return jsonify({"success": True, "robos": registry.listar()})


@app.post("/api/robos/<robo_id>/executar")
def executar_robo(robo_id: str):
    spec = registry.obter(robo_id)
    if not spec:
        return jsonify({"success": False, "error": f"Robô '{robo_id}' não existe."}), 404

    params = request.get_json(silent=True) or {}
    erro = _validar(spec, params)
    if erro:
        return jsonify({"success": False, "error": erro}), 400

    log.info("Executando robô %s | params=%s", robo_id, params)
    futuro = _pool.submit(_rodar, spec, params)
    try:
        return jsonify(futuro.result(timeout=spec.timeout))
    except FutureTimeout:
        log.warning("Robô %s excedeu %ss", robo_id, spec.timeout)
        return jsonify({
            "success": False,
            "robo": robo_id,
            "error": f"O robô excedeu o tempo limite de {spec.timeout}s. "
                     f"Considere executá-lo em modo assíncrono.",
        }), 504
    except Exception as e:
        log.error("Falha no robô %s: %s\n%s", robo_id, e, traceback.format_exc())
        return jsonify({"success": False, "robo": robo_id, "error": str(e)}), 500


@app.post("/api/robos/<robo_id>/jobs")
def criar_job(robo_id: str):
    """Dispara robô em background. O front faz polling em /api/jobs/<id>."""
    spec = registry.obter(robo_id)
    if not spec:
        return jsonify({"success": False, "error": f"Robô '{robo_id}' não existe."}), 404

    params = request.get_json(silent=True) or {}
    erro = _validar(spec, params)
    if erro:
        return jsonify({"success": False, "error": erro}), 400

    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"status": "executando", "robo": robo_id, "criado_em": _agora()}

    def _tarefa():
        try:
            _jobs[job_id].update(_rodar(spec, params), status="concluido")
        except Exception as e:
            log.error("Falha no job %s (%s): %s", job_id, robo_id, e)
            _jobs[job_id].update(status="erro", success=False, error=str(e))

    _pool.submit(_tarefa)
    log.info("Job %s criado para robô %s", job_id, robo_id)
    return jsonify({"success": True, "job_id": job_id, "status": "executando"}), 202


@app.get("/api/jobs/<job_id>")
def status_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"success": False, "error": "Job não encontrado."}), 404
    return jsonify(job)


@app.get("/api/arquivos/<path:nome>")
def baixar_arquivo(nome: str):
    return send_from_directory(PASTA_SAIDA, nome, as_attachment=True)


@app.post("/api/upload")
def upload():
    """Recebe a planilha enviada no chat e devolve um arquivo_id.

    O arquivo_id é repassado ao robô em params["arquivo_id"], que lê o arquivo
    da PASTA_UPLOADS. Nada é gravado com o nome original do usuário.
    """
    if "arquivo" not in request.files:
        return jsonify({"success": False, "error": "Nenhum arquivo recebido."}), 400

    arquivo = request.files["arquivo"]
    nome_original = secure_filename(arquivo.filename or "")
    ext = os.path.splitext(nome_original)[1].lower()

    if ext not in EXTENSOES_OK:
        return jsonify({
            "success": False,
            "error": f"Formato não aceito. Envie {', '.join(sorted(EXTENSOES_OK))}.",
        }), 415

    arquivo_id = f"{uuid.uuid4().hex}{ext}"
    caminho = os.path.join(PASTA_UPLOADS, arquivo_id)
    arquivo.save(caminho)

    # Lê o cabeçalho só para devolver um preview e falhar cedo se estiver corrompido
    try:
        import pandas as pd
        previa = (pd.read_csv(caminho, sep=None, engine="python", nrows=5)
                  if ext == ".csv" else pd.read_excel(caminho, nrows=5))
        colunas = [str(c) for c in previa.columns]
    except Exception as e:
        os.remove(caminho)
        log.warning("Upload inválido (%s): %s", nome_original, e)
        return jsonify({"success": False,
                        "error": "Não consegui ler a planilha. Verifique o arquivo."}), 400

    log.info("Upload recebido: %s -> %s (%d colunas)", nome_original, arquivo_id, len(colunas))
    return jsonify({
        "success": True,
        "arquivo_id": arquivo_id,
        "nome_original": nome_original,
        "colunas": colunas,
        "tamanho_kb": round(os.path.getsize(caminho) / 1024),
    })


@app.errorhandler(413)
def arquivo_grande(_):
    return jsonify({"success": False,
                    "error": f"Arquivo acima do limite de {MAX_MB} MB."}), 413


@app.errorhandler(404)
def nao_encontrado(_):
    return jsonify({"success": False, "error": "Rota não encontrada."}), 404


if __name__ == "__main__":
    # Apenas desenvolvimento local. Em Docker quem sobe é o gunicorn.
    app.run(host="0.0.0.0", port=8000, debug=True)
