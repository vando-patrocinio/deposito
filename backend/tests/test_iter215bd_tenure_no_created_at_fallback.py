"""Bug fix audit: "Tempo de cliente" no QR Code do PWA.

Cobre:
1. `_customer_profile_dict` NUNCA cai em `created_at` (data de
   importação do Atlaz) — apenas `installation_date` → `activation_date`
   → `subscriber_since`.
2. Sem nenhum desses campos, retorna None (PWA mostra "Cliente Ligo").
"""
import asyncio
import sys


def test_tenure_never_falls_back_to_created_at():
    sys.path.insert(0, "/app/backend")
    from routes.referrals import _customer_profile_dict

    async def _run():
        # Caso 1: cliente com installation_date correta → usa essa
        sub1 = {
            "id": "sub-1", "name": "Adilson",
            "installation_date": "2025-02-12T18:03:48+00:00",
            "activation_date": "2025-02-12T18:03:48+00:00",
            "created_at": "2026-05-14T05:00:00+00:00",  # data importação
            "status": "ATIVO",
        }
        p1 = _customer_profile_dict(sub1, "REF1")
        assert p1["installation_date"] == "2025-02-12T18:03:48+00:00", \
            "Deve usar installation_date REAL (não created_at)"

        # Caso 2: SEM installation_date, mas com activation_date
        sub2 = {
            "id": "sub-2", "name": "Maria",
            "installation_date": None,
            "activation_date": "2024-08-01T00:00:00+00:00",
            "created_at": "2026-05-14T05:00:00+00:00",
            "status": "ATIVO",
        }
        p2 = _customer_profile_dict(sub2, "REF2")
        assert p2["installation_date"] == "2024-08-01T00:00:00+00:00", \
            "Deve cair em activation_date (não created_at)"

        # Caso 3: SEM installation_date e activation_date → None (NÃO
        # mais created_at — bug fix do iter215bd).
        sub3 = {
            "id": "sub-3", "name": "Pamela",
            "installation_date": None,
            "activation_date": None,
            "created_at": "2026-05-14T05:00:00+00:00",
            "status": "ATIVO",
        }
        p3 = _customer_profile_dict(sub3, "REF3")
        assert p3["installation_date"] is None, \
            "SEM data fidedigna → None. NÃO pode cair em created_at " \
            "(data de importação do Atlaz)."

        # Caso 4: subscriber_since como último fallback antes do None
        sub4 = {
            "id": "sub-4", "name": "Joao",
            "installation_date": None,
            "activation_date": None,
            "subscriber_since": "2023-05-20T00:00:00+00:00",
            "created_at": "2026-05-14T05:00:00+00:00",
            "status": "ATIVO",
        }
        p4 = _customer_profile_dict(sub4, "REF4")
        assert p4["installation_date"] == "2023-05-20T00:00:00+00:00"

    asyncio.run(_run())
