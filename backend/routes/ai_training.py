"""AI Training routes — endpoints para gerenciar o treinamento multiagente.

Inclui:
- GET  /api/ai-training/status            → status agentes + KB
- POST /api/ai-training/reload            → re-executa seed (idempotente)
- GET  /api/ai-training/scenarios         → lista cenários
- GET  /api/ai-training/scenarios/{n}     → detalhe cenário
- GET  /api/ai-training/tests             → lista testes de validação
- GET  /api/ai-training/tests/{n}         → detalhe teste
- POST /api/ai-training/tests/{n}/run     → executa 1 teste contra a Isabela IA
- POST /api/ai-training/tests/run-all     → executa todos os testes em batch
- GET  /api/ai-training/decision-matrix   → matriz de decisão
- GET  /api/ai-training/runs              → histórico de execuções
- GET  /api/ai-training/runs/{id}         → detalhe de uma execução
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from core import require_role
from database import db
from scripts.seed_training_agents import (
    seed_new_agents, seed_training_kb, update_existing_agents,
)
from services import motor_ia

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-training", tags=["ai-training"])


def _now():
    return datetime.now(timezone.utc).isoformat()


# ===================================================================
# STATUS + RELOAD (existentes)
# ===================================================================
@router.get("/status")
async def training_status(user: dict = Depends(require_role("gestor"))):
    """Lista os 10 agentes + status do treinamento (KB + último reload)."""
    cid = user.get("company_id", "co-demo")
    agents = await db.aihub_agents.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "name": 1, "topology_node": 1,
         "model_provider": 1, "model_name": 1, "temperature": 1,
         "max_tokens": 1, "active": 1, "training_loaded_at": 1,
         "updated_at": 1},
    ).to_list(50)
    kb = await db.ai_training_kb.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "key": 1, "title": 1, "updated_at": 1},
    ).to_list(20)
    last_reload = None
    for a in agents:
        ts = a.get("training_loaded_at")
        if ts and (last_reload is None or ts > last_reload):
            last_reload = ts
    return {
        "ok": True,
        "company_id": cid,
        "agents_count": len(agents),
        "agents_with_training": sum(1 for a in agents if a.get("training_loaded_at")),
        "kb_documents": len(kb),
        "last_reload_at": last_reload,
        "agents": sorted(agents, key=lambda x: x.get("topology_node") or ""),
        "kb": sorted(kb, key=lambda x: x.get("key") or ""),
    }


@router.post("/reload")
async def training_reload(user: dict = Depends(require_role("gestor"))):
    """Re-executa o seed do treinamento. Apenas admin/gestor."""
    cid = user.get("company_id", "co-demo")
    try:
        await seed_training_kb(db, company_id=cid)
        await seed_new_agents(db, company_id=cid)
        await update_existing_agents(db, company_id=cid)
    except Exception as e:
        raise HTTPException(500, f"Falha no reload: {e}")
    agents = await db.aihub_agents.find(
        {"company_id": cid},
        {"_id": 0, "name": 1, "topology_node": 1,
         "training_loaded_at": 1, "model_provider": 1, "model_name": 1},
    ).to_list(50)
    kb_count = await db.ai_training_kb.count_documents({"company_id": cid})
    return {
        "ok": True,
        "reloaded_at": _now(),
        "agents_count": len(agents),
        "kb_documents": kb_count,
        "agents": sorted(agents, key=lambda x: x.get("topology_node") or ""),
    }


# ===================================================================
# CENÁRIOS
# ===================================================================
@router.get("/scenarios")
async def scenarios_list(user: dict = Depends(require_role("gestor")),
                          category: str | None = None,
                          tag: str | None = None,
                          q: str | None = None):
    """Lista cenários de treinamento. Filtros opcionais: category, tag, q."""
    cid = user.get("company_id", "co-demo")
    filt = {"company_id": cid}
    if category:
        filt["category"] = category
    if tag:
        filt["tags"] = tag
    if q:
        filt["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"objetivo": {"$regex": q, "$options": "i"}},
            {"licao": {"$regex": q, "$options": "i"}},
        ]
    items = await db.ai_training_scenarios.find(
        filt, {"_id": 0}
    ).sort("number", 1).to_list(200)
    total = await db.ai_training_scenarios.count_documents({"company_id": cid})

    # Agrega contagem por categoria para o filtro lateral
    categories = {}
    for s in items:
        c = s.get("category", "outro")
        categories[c] = categories.get(c, 0) + 1
    return {
        "ok": True, "count": len(items), "total": total,
        "items": items, "categories": categories,
    }


@router.get("/scenarios/{number}")
async def scenario_get(number: int, user: dict = Depends(require_role("gestor"))):
    """Pega um cenário específico pelo número."""
    cid = user.get("company_id", "co-demo")
    s = await db.ai_training_scenarios.find_one(
        {"company_id": cid, "number": number}, {"_id": 0}
    )
    if not s:
        raise HTTPException(404, f"Cenário #{number} não encontrado")
    return s


# ===================================================================
# TESTES DE VALIDAÇÃO
# ===================================================================
@router.get("/tests")
async def tests_list(user: dict = Depends(require_role("gestor")),
                      categoria: str | None = None):
    """Lista os testes de validação."""
    cid = user.get("company_id", "co-demo")
    filt = {"company_id": cid}
    if categoria:
        filt["categoria"] = categoria
    items = await db.ai_training_tests.find(
        filt, {"_id": 0}
    ).sort("number", 1).to_list(100)

    # Última execução de cada teste
    last_runs = await db.ai_training_runs.find(
        {"company_id": cid, "kind": "test"},
        {"_id": 0, "test_number": 1, "status": 1, "score": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(500)
    last_by_test = {}
    for r in last_runs:
        n = r.get("test_number")
        if n is not None and n not in last_by_test:
            last_by_test[n] = r
    for t in items:
        t["last_run"] = last_by_test.get(t.get("number"))

    return {"ok": True, "count": len(items), "items": items}


@router.get("/tests/{number}")
async def test_get(number: int, user: dict = Depends(require_role("gestor"))):
    """Pega um teste específico."""
    cid = user.get("company_id", "co-demo")
    t = await db.ai_training_tests.find_one(
        {"company_id": cid, "number": number}, {"_id": 0}
    )
    if not t:
        raise HTTPException(404, f"Teste #{number} não encontrado")
    return t


# ===================================================================
# MATRIZ DE DECISÃO
# ===================================================================
@router.get("/decision-matrix")
async def decision_matrix(user: dict = Depends(require_role("gestor")),
                            categoria: str | None = None):
    """Retorna a matriz de decisão (quando X, acionar Y)."""
    cid = user.get("company_id", "co-demo")
    filt = {"company_id": cid}
    if categoria:
        filt["categoria"] = categoria
    rows = await db.ai_training_decision_matrix.find(
        filt, {"_id": 0}
    ).sort("order", 1).to_list(200)
    # Agrega por categoria
    by_cat = {}
    for r in rows:
        c = r.get("categoria", "outro")
        by_cat.setdefault(c, []).append(r)
    return {"ok": True, "count": len(rows), "items": rows, "by_categoria": by_cat}


# ===================================================================
# ENGINE — EXECUTAR TESTE DE VALIDAÇÃO
# ===================================================================
EVAL_SYSTEM_PROMPT = """\
Você é o Avaliador IA da SmartProv. Sua função é AVALIAR a resposta que
a Isabela IA deu a uma mensagem de cliente, comparando com o fluxo
ESPERADO do teste de validação.

VOCÊ NÃO ATENDE O CLIENTE. Você apenas julga.

INPUT:
- Entrada do cliente
- Resposta gerada pela Isabela IA (texto literal)
- Agentes que DEVERIAM ter sido acionados
- Erro crítico que NÃO pode ter acontecido
- Critério de aprovação binário

CRITÉRIOS DE PONTUAÇÃO (100 pts):
  • Fluxo correto (consultou os agentes certos):         30 pts
  • Consulta à fonte (SmartOLT/Kanban citada):           25 pts
  • Sem invenção (não chutou dado técnico):              20 pts
  • Empatia + clareza com o cliente:                     10 pts
  • Reconhecimento de risco (se aplicável):              10 pts
  • Transparência (admite o que não sabe):                5 pts

PENALIDADES:
  -15 → inventou sinal / horário / prazo
  -15 → prometeu visita sem mencionar Kanban
  -10 → ignorou cliente irritado
  -10 → não acionou humano em situação de risco
  -5  → não foi transparente sobre limitações

CLASSIFICAÇÃO:
  90-100 → APROVADO EXCELENTE
  75-89  → APROVADO COM AJUSTES
  60-74  → PRECISA REVISAR FLUXO
  <60    → REPROVADO · risco operacional

Retorne SOMENTE um JSON válido com este formato exato:
{
  "score": <int 0-100>,
  "score_decimal": <float 0-10>,
  "classificacao": "<APROVADO EXCELENTE|APROVADO COM AJUSTES|PRECISA REVISAR FLUXO|REPROVADO>",
  "pass": <bool — true se score >= 75>,
  "breakdown": {
    "fluxo_correto": <int 0-30>,
    "consulta_fonte": <int 0-25>,
    "sem_invencao": <int 0-20>,
    "empatia_clareza": <int 0-10>,
    "reconhecimento_risco": <int 0-10>,
    "transparencia": <int 0-5>
  },
  "penalidades": [<list of strings>],
  "agentes_acionados_corretamente": <list of agent names from resposta>,
  "agentes_faltando": <list of agent names esperados mas não acionados>,
  "erro_critico_ocorreu": <bool>,
  "justificativa": "<texto curto explicando a nota>",
  "sugestoes_melhoria": [<list of strings>]
}

SEM TEXTO FORA DO JSON. NADA. Apenas JSON puro."""


async def _run_isabela(cid: str, mensagem_cliente: str) -> dict:
    """Chama a Isabela IA com a mensagem do cliente."""
    isa = await db.aihub_agents.find_one(
        {"company_id": cid, "name": "Isabella"},
        {"_id": 0, "system_prompt": 1, "model_provider": 1,
         "model_name": 1, "temperature": 1, "max_tokens": 1},
    )
    if not isa:
        raise HTTPException(500, "Agente 'Isabella' não encontrado")
    sysprompt = isa.get("system_prompt") or "Você é a Isabela IA da SmartProv."

    # Preferimos rodar via motor_ia (OpenRouter) usando o modelo configurado.
    # Se model_provider/model_name forem do tipo OpenAI legado, motor_ia
    # converterá automaticamente.
    res = await motor_ia.chat_completion(
        company_id=cid,
        messages=[
            {"role": "system", "content": sysprompt},
            {"role": "user", "content": mensagem_cliente},
        ],
        temperature=isa.get("temperature", 0.7),
        max_tokens=isa.get("max_tokens", 600),
        purpose="atendimento",
        agent="isabela_ia",
    )
    return res


async def _run_avaliador(cid: str, test: dict, isabela_response: str) -> dict:
    """Chama o Avaliador IA com prompt estruturado."""
    payload = {
        "entrada_cliente": test["entrada_cliente"],
        "resposta_isabela": isabela_response,
        "agentes_esperados": test["agentes_esperados"],
        "erro_critico": test["erro_critico"],
        "criterio_aprovacao": test["criterio_aprovacao"],
        "pontuacao_esperada": test.get("pontuacao_esperada"),
    }
    res = await motor_ia.chat_completion(
        company_id=cid,
        messages=[
            {"role": "system", "content": EVAL_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=1000,
        json_mode=True,
        purpose="general",
        agent="avaliador_ai",
    )
    content = (res.get("content") or "").strip()
    # Remove eventuais ```json wrappers
    if content.startswith("```"):
        content = content.strip("`").lstrip("json").strip()
    try:
        return json.loads(content)
    except Exception as e:
        logger.warning("[ai-training] Avaliador retornou JSON inválido: %s · raw=%r",
                        e, content[:300])
        return {
            "score": 0, "score_decimal": 0.0, "pass": False,
            "classificacao": "REPROVADO",
            "justificativa": f"Avaliador retornou JSON inválido: {e}",
            "_raw": content[:500],
        }


@router.post("/tests/{number}/run")
async def test_run(number: int, user: dict = Depends(require_role("gestor"))):
    """Executa 1 teste contra a Isabela IA + avaliação."""
    cid = user.get("company_id", "co-demo")
    test = await db.ai_training_tests.find_one(
        {"company_id": cid, "number": number}, {"_id": 0}
    )
    if not test:
        raise HTTPException(404, f"Teste #{number} não encontrado")

    started = _now()
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    status = "ok"
    error = None
    isabela_response = ""
    evaluation = {}

    try:
        isa = await _run_isabela(cid, test["entrada_cliente"])
        isabela_response = (isa.get("content") or "").strip()
    except Exception as e:
        status = "error"
        error = f"Isabela falhou: {e}"
        logger.exception("[ai-training] erro Isabela teste #%d", number)

    if status == "ok" and isabela_response:
        try:
            evaluation = await _run_avaliador(cid, test, isabela_response)
        except Exception as e:
            status = "error"
            error = f"Avaliador falhou: {e}"
            logger.exception("[ai-training] erro Avaliador teste #%d", number)

    finished = _now()
    score = float(evaluation.get("score_decimal", 0.0)) if evaluation else 0.0
    passed = bool(evaluation.get("pass", False)) if evaluation else False

    run_doc = {
        "id": run_id,
        "company_id": cid,
        "kind": "test",
        "test_number": number,
        "test_name": test.get("name"),
        "test_categoria": test.get("categoria"),
        "entrada_cliente": test.get("entrada_cliente"),
        "isabela_response": isabela_response,
        "evaluation": evaluation,
        "score": score,
        "pass": passed,
        "status": status,
        "error": error,
        "started_at": started,
        "finished_at": finished,
        "created_at": _now(),
        "user_id": user.get("id"),
        "user_name": user.get("name") or user.get("email"),
    }
    await db.ai_training_runs.insert_one(run_doc)
    run_doc.pop("_id", None)
    return {"ok": True, "run": run_doc}


@router.post("/tests/run-all")
async def tests_run_all(user: dict = Depends(require_role("gestor"))):
    """Executa TODOS os testes em paralelo (limitado em 5 concorrentes)."""
    cid = user.get("company_id", "co-demo")
    tests = await db.ai_training_tests.find(
        {"company_id": cid}, {"_id": 0}
    ).sort("number", 1).to_list(100)

    batch_id = f"batch-{uuid.uuid4().hex[:10]}"
    started = _now()
    semaphore = asyncio.Semaphore(5)

    async def _run_one(t):
        async with semaphore:
            try:
                isa = await _run_isabela(cid, t["entrada_cliente"])
                response = (isa.get("content") or "").strip()
                evaluation = await _run_avaliador(cid, t, response)
                score = float(evaluation.get("score_decimal", 0.0))
                passed = bool(evaluation.get("pass", False))
                return {
                    "test_number": t["number"], "test_name": t["name"],
                    "isabela_response": response, "evaluation": evaluation,
                    "score": score, "pass": passed, "status": "ok",
                }
            except Exception as e:
                logger.exception("[ai-training] erro teste #%d batch", t["number"])
                return {
                    "test_number": t["number"], "test_name": t["name"],
                    "score": 0.0, "pass": False, "status": "error",
                    "error": str(e),
                }

    results = await asyncio.gather(*[_run_one(t) for t in tests])
    finished = _now()

    # Persiste cada run individualmente
    for r in results:
        run_doc = {
            "id": f"run-{uuid.uuid4().hex[:12]}",
            "company_id": cid,
            "kind": "test",
            "batch_id": batch_id,
            **r,
            "created_at": _now(),
            "started_at": started,
            "finished_at": finished,
            "user_id": user.get("id"),
            "user_name": user.get("name") or user.get("email"),
        }
        await db.ai_training_runs.insert_one(run_doc)

    passed = sum(1 for r in results if r.get("pass"))
    total = len(results)
    avg = sum(r.get("score", 0) for r in results) / total if total else 0

    return {
        "ok": True,
        "batch_id": batch_id,
        "started_at": started,
        "finished_at": finished,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "average_score": round(avg, 2),
        "results": results,
    }


# ===================================================================
# HISTÓRICO DE EXECUÇÕES
# ===================================================================
@router.get("/runs")
async def runs_list(user: dict = Depends(require_role("gestor")),
                     limit: int = 100):
    """Lista histórico de execuções (mais recentes primeiro)."""
    cid = user.get("company_id", "co-demo")
    items = await db.ai_training_runs.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "test_number": 1, "test_name": 1,
         "test_categoria": 1, "kind": 1, "score": 1, "pass": 1,
         "status": 1, "batch_id": 1, "created_at": 1, "user_name": 1},
    ).sort("created_at", -1).to_list(min(limit, 500))

    # Stats agregadas
    total = len(items)
    passed = sum(1 for r in items if r.get("pass"))
    avg = sum(r.get("score", 0) for r in items) / total if total else 0

    return {
        "ok": True,
        "count": total,
        "passed": passed,
        "failed": total - passed,
        "average_score": round(avg, 2),
        "items": items,
    }


@router.get("/runs/{run_id}")
async def run_get(run_id: str, user: dict = Depends(require_role("gestor"))):
    """Pega o detalhe de uma execução (com response + evaluation)."""
    cid = user.get("company_id", "co-demo")
    r = await db.ai_training_runs.find_one(
        {"company_id": cid, "id": run_id}, {"_id": 0}
    )
    if not r:
        raise HTTPException(404, "Execução não encontrada")
    return r


@router.get("/runs/batch/{batch_id}")
async def batch_runs(batch_id: str, user: dict = Depends(require_role("gestor"))):
    """Pega todas as runs de um batch (run-all)."""
    cid = user.get("company_id", "co-demo")
    items = await db.ai_training_runs.find(
        {"company_id": cid, "batch_id": batch_id}, {"_id": 0}
    ).sort("test_number", 1).to_list(100)
    if not items:
        raise HTTPException(404, "Batch não encontrado")
    total = len(items)
    passed = sum(1 for r in items if r.get("pass"))
    avg = sum(r.get("score", 0) for r in items) / total if total else 0
    return {
        "ok": True,
        "batch_id": batch_id,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "average_score": round(avg, 2),
        "items": items,
    }
