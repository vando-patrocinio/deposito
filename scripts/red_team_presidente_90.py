"""
red_team_presidente_90.py — iter242

Bateria de validação CTO. Garante que o Presidente IA realmente lê 12 áreas,
nada some silenciosamente, snapshot é salvo, ambiente é identificado,
e nenhum dado é inventado.

Uso:
    cd /app/backend && python3 ../scripts/red_team_presidente_90.py
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

# Permite rodar de qualquer cwd: garante import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/backend")

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

OK_GREEN = "\033[92m✓\033[0m"
ERR_RED = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    sys.path.insert(0, "/app/backend")
    from services import presidente_score_engine as eng

    started = datetime.now(timezone.utc)
    results = []

    def check(name: str, ok: bool, detail: str):
        symbol = OK_GREEN if ok else ERR_RED
        results.append((name, ok, detail))
        print(f"  {symbol} {name:50s} | {detail}")

    print("\n══════════════════════════════════════════════════════════════════")
    print("RED TEAM PRESIDENTE IA 90% — iter242")
    print(f"Started: {started.isoformat()}")
    print(f"DB: {os.environ['DB_NAME']}")
    print(f"Environment: {eng._environment_label()}")
    print("══════════════════════════════════════════════════════════════════\n")

    # 1) Score lê 12 áreas
    snap = await eng.compute_score("co-demo")
    check("1. Score lê 12 áreas",
          len(snap["components"]) == 12,
          f"areas_count={len(snap['components'])}")

    # 2) Nenhuma área some silenciosamente
    expected = set(eng.WEIGHTS.keys())
    actual = set(snap["components"].keys())
    check("2. Nenhuma área some silenciosamente",
          expected == actual,
          f"missing={list(expected - actual)} extra={list(actual - expected)}")

    # 3) Snapshot é salvo
    snap_with_id = await eng.compute_and_save("co-demo")
    check("3. Snapshot é salvo",
          bool(snap_with_id.get("_id")),
          f"_id={snap_with_id.get('_id')}")

    # 4) Álvaro escreve evento novo (rodou neste iter242)
    n_brief = await db.motor_ia_daily_briefings.count_documents({
        "company_id": "co-demo",
        "kind": {"$regex": "iter242|manual_audit"},
    })
    check("4. Álvaro escreveu evento novo neste iter",
          n_brief >= 1,
          f"motor_ia_daily_briefings count_with_iter242={n_brief}")

    # 5) Tesouraria aparece no score
    tes = snap["components"].get("tesouraria") or {}
    check("5. Tesouraria aparece no score",
          tes.get("doc_count", 0) > 0 and tes.get("status") != "sem_dados",
          f"score={tes.get('score')} status={tes.get('status')} docs={tes.get('doc_count')}")

    # 6) Isabella funil comercial aparece (via 'vendas' + 'atendimento')
    ven = snap["components"].get("vendas") or {}
    att = snap["components"].get("atendimento") or {}
    isab_ok = ven.get("doc_count", 0) > 0 and att.get("doc_count", 0) > 0
    check("6. Isabella funil comercial aparece",
          isab_ok,
          f"vendas_docs={ven.get('doc_count')} atendimento_docs={att.get('doc_count')}")

    # 7) Score não quebra com collection vazia
    try:
        nc = await eng._count("nao_existe_xyz_123")
        check("7. Score não quebra com collection vazia",
              nc == 0, f"count_nao_existe={nc}")
    except Exception as e:
        check("7. Score não quebra com collection vazia", False, str(e))

    # 8) Ambiente aparece como preview/produção
    env = snap.get("environment")
    check("8. Ambiente identificado",
          env in ("production", "preview", "preview_sandbox"),
          f"environment='{env}'")

    # 9) Endpoint /api/presidente-ia/score-engine retorna 200
    import urllib.request
    try:
        # Login first
        login = urllib.request.Request(
            "http://localhost:8001/api/auth/login",
            data=json.dumps({"email": "admin@empresa.com",
                              "password": "123456"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(login, timeout=5) as r:
            payload = json.loads(r.read())
            token = payload.get("token") or payload.get("access_token")
        req = urllib.request.Request(
            "http://localhost:8001/api/presidente-ia/score-engine",
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            assert r.status == 200
        check("9. Endpoint /score-engine retorna 200", True, "HTTP 200")
    except Exception as e:
        check("9. Endpoint /score-engine retorna 200", False, str(e))

    # 10) Nenhum ROI é inventado (todos last_ts presentes ou null explícito)
    inventado = []
    for n, c in snap["components"].items():
        if c["doc_count"] > 0 and not c.get("last_ts"):
            inventado.append(n)
    check("10. Nenhum dado inventado (last_ts presente onde docs>0)",
          len(inventado) == 0,
          f"areas_sem_ts={inventado}")

    # 11) Nenhum mock — engine não usa hardcoded values
    has_mock = False
    src = open("/app/backend/services/presidente_score_engine.py").read()
    # Remove docstring/comentários para procurar só código de verdade
    code_lines = []
    in_docstring = False
    for line in src.split("\n"):
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#"):
            continue
        code_lines.append(line)
    code_only = "\n".join(code_lines).lower()
    for keyword in ["mock(", "fakedata", "lorem", "dummy_data", "= 'fake"]:
        if keyword in code_only:
            has_mock = True
    check("11. Nenhum mock no engine", not has_mock,
          "scan limpo" if not has_mock else "encontrou mock no código")

    # 12) company_id obrigatório em todo registro novo do snapshot
    saved = await db.president_score_snapshots.find_one(
        {"_id": snap_with_id["_id"]} if isinstance(snap_with_id["_id"], object)
        else None, sort=[("_id", -1)])
    if saved is None:
        saved = await db.president_score_snapshots.find_one(
            {}, sort=[("_id", -1)])
    has_cid = bool(saved and saved.get("company_id"))
    check("12. company_id presente no snapshot salvo",
          has_cid,
          f"company_id={(saved or {}).get('company_id')}")

    # 13) Pesos somam 1.0 (±0.01)
    s = sum(eng.WEIGHTS.values())
    check("13. Pesos das áreas somam 1.0",
          abs(s - 1.0) < 0.01,
          f"sum={s:.4f}")

    # 14) Maturidade ≥ 90 OU gap explícito
    maturity = snap["maturity_total"]
    check("14. Maturidade ≥ 90 OU gap mensurável",
          maturity >= 90,
          f"maturity={maturity} (areas_with_data={snap['areas_with_data']}/{snap['areas_count']})")

    # 15) Score >= 90 OU worst drivers identificados
    score = snap["score_total"]
    worst = snap["worst_drivers"]
    score_ok_or_gap = (score >= 90) or (len(worst) >= 1 and all(w["reason"]
                                                                  for w in worst))
    check("15. Score ≥ 90 OU worst drivers com causa raiz",
          score_ok_or_gap,
          f"score={score} worst={[(w['name'], w['score']) for w in worst]}")

    print("\n══════════════════════════════════════════════════════════════════")
    pass_n = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    pct = pass_n / total * 100 if total else 0
    print(f"RED TEAM: {pass_n}/{total} ({pct:.1f}%)")
    print(f"SCORE PRESIDENTE: {score}")
    print(f"MATURITY: {maturity}")
    print(f"ENVIRONMENT: {env}")
    if env != "production":
        print("\nAMBIENTE PREVIEW — VALIDAÇÃO NÃO REPRESENTA PRODUÇÃO.")
    print("══════════════════════════════════════════════════════════════════\n")

    # Persistir resultado
    report = {
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "db_name": os.environ["DB_NAME"],
        "environment": env,
        "score": score,
        "maturity": maturity,
        "checks_total": total,
        "checks_passed": pass_n,
        "checks_pct": round(pct, 1),
        "checks": [{"name": n, "passed": ok, "detail": d}
                    for n, ok, d in results],
    }
    await db.red_team_runs.insert_one(dict(report))
    print(f"Saved → red_team_runs._id={report.get('_id', 'inserted')}")
    return pass_n == total


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
