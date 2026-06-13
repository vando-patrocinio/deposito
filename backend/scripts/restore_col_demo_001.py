"""Script CTO 13/06/2026 — restaura col-demo-001 órfão e alinha email.

Bug: user `colaborador@empresa.com` tem `collaborator_id="col-demo-001"`,
mas o doc foi deletado em algum momento. PWA fica "Olá —" + schedule
undefined porque /collaborators/me retorna 404.

Idempotente: roda quantas vezes quiser sem duplicar.
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]
    now = datetime.now(timezone.utc).isoformat()
    seed = {
        "id": "col-demo-001",
        "name": "Carlos Almeida",
        "cpf": "00000000001",
        "email": "colaborador@empresa.com",
        "phone": "+55 11 99999-0001",
        "role": "Colaborador de Campo",
        "cargo": "tecnico",
        "company": "Operação SP",
        "company_id": "co-demo",
        "schedule": {
            "entrada": "08:00",
            "inicio_intervalo": "12:00",
            "fim_intervalo": "13:00",
            "saida": "17:00",
        },
        "overtime_policy": {
            "mode": "banco",
            "hourly_rate_brl": 0.0,
            "weekday_multiplier": 1.5,
            "sunday_multiplier": 2.0,
        },
        "praca_ids_extra": [],
        "is_test_mode": False,
        "clock_in_enabled": False,  # conforme test_credentials.md
        "active": True,
        "can_attend_whatsapp": False,
        "requires_vehicle": False,
        "created_at": now,
        "updated_at": now,
    }
    # upsert idempotente
    res = await db.collaborators.update_one(
        {"id": "col-demo-001"},
        {"$setOnInsert": seed},
        upsert=True,
    )
    print(
        "upsert col-demo-001:",
        "INSERTED" if res.upserted_id else "ALREADY_EXISTS",
    )
    # garante campos críticos atualizados mesmo se já existia
    await db.collaborators.update_one(
        {"id": "col-demo-001"},
        {"$set": {
            "email": "colaborador@empresa.com",
            "name": "Carlos Almeida",
            "cargo": "tecnico",
            "company_id": "co-demo",
            "clock_in_enabled": False,
            "active": True,
            "updated_at": now,
        }},
    )
    d = await db.collaborators.find_one(
        {"id": "col-demo-001"},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "company_id": 1,
         "clock_in_enabled": 1, "schedule": 1, "cargo": 1, "active": 1},
    )
    print("final col-demo-001:")
    print(json.dumps(d, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
