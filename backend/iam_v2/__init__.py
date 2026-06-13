"""IAM v2 — Novo módulo de Identidade & Acesso (CTO 13/06/2026).

⚠️  ESTE MÓDULO NÃO ESTÁ ATIVO POR DEFAULT.

Controlado pela flag `USE_NEW_IAM` no `.env`:
  - `0` (default): sistema legado (users + collaborators + access_profiles).
  - `1`: IAM v2 (identities + credentials + memberships + sessions).

Durante a migração (28/06/2026 → 28/07/2026), o backend roda em modo
dual-write: lê/escreve nos dois lados pra permitir rollback instantâneo.

Veja:
  - /app/memory/AUDIT_IAM_2026_06_13.md            (auditoria E1)
  - /app/memory/adr/ADR-001_Identity_Model.md
  - /app/memory/adr/ADR-002_Credential_Model.md
  - /app/memory/adr/ADR-003_Memberships_Permissions.md
  - /app/memory/adr/ADR-004_Sessions_Migration_Audit.md
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("iam_v2")

NEW_IAM_ENABLED = os.environ.get("USE_NEW_IAM", "0") == "1"

if NEW_IAM_ENABLED:
    logger.warning(
        "[iam_v2] USE_NEW_IAM=1 — IAM v2 ATIVO. "
        "Verifique migração concluída + auditoria S3 ligada."
    )
else:
    logger.info(
        "[iam_v2] USE_NEW_IAM=0 — sistema legado em uso. "
        "iam_v2 carregado mas inerte (somente models/catalog disponíveis)."
    )
