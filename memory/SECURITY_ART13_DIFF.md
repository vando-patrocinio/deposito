# SECURITY_ART13_DIFF.md — Mass Refactor Info-Leak Remediation

**Data:** 19/02/2026  
**Artigo:** ART.13 — Vazamento de exceção crua ao cliente  
**Regra:** `HTTPException(NNN, str(e))` ou `HTTPException(NNN, f"...{e}")` é proibido. Use mensagem genérica + log server-side.

## Métricas

| Métrica | Valor |
|---------|-------|
| **Total encontrado (ANTES)** | 134 ocorrências |
| **Total corrigido** | 134 ocorrências |
| **Total restante** | 0 ocorrências |
| **Arquivos afetados** | 58 arquivos |

## Mecanismo de substituição

Helper centralizado adicionado em `backend/services/exception_sanitizer.py::safe_detail`:

```python
def safe_detail(status_code: int, exc: Exception, context: str = "") -> str:
    """Registra exceção no logger e devolve mensagem genérica curta."""
    error_id = uuid.uuid4().hex[:8]
    logger.warning("[security.detail] error_id=%s ctx=%s status=%s exc=%s: %s",
                   error_id, context or "-", status_code, type(exc).__name__, str(exc)[:300])
    return _GENERIC_DETAIL.get(status_code, "Request rejected")
```

## Padrão de substituição

| Antes | Depois |
|-------|--------|
| `raise HTTPException(400, str(e))` | `raise HTTPException(400, safe_detail(400, e))` |
| `raise HTTPException(500, f"Erro X: {e}")` | `raise HTTPException(500, safe_detail(500, e, "Erro X"))` |
| `raise HTTPException(503, str(e)) from e` | `raise HTTPException(503, safe_detail(503, e)) from e` |

## Arquivos afetados

  backend/routes/access_profiles.py: 3
  backend/routes/admin.py: 1
  backend/routes/admin_wa_sidecar.py: 1
  backend/routes/ai_center_blockers.py: 1
  backend/routes/ai_center_data_quality.py: 1
  backend/routes/ai_center_isabella.py: 1
  backend/routes/ai_dashboard.py: 2
  backend/routes/ai_training.py: 1
  backend/routes/aihub.py: 5
  backend/routes/atlaz.py: 2
  backend/routes/atlaz_financeiro.py: 1
  backend/routes/backup.py: 2
  backend/routes/bank_import.py: 2
  backend/routes/boleto_template.py: 1
  backend/routes/budget.py: 8
  backend/routes/ceo_digital.py: 4
  backend/routes/churn.py: 4
  backend/routes/clock.py: 1
  backend/routes/disparo_boleto.py: 1
  backend/routes/disparo_ia.py: 1
  backend/routes/drive.py: 5
  backend/routes/field_ops.py: 1
  backend/routes/fleet_portal.py: 1
  backend/routes/gestao_ia.py: 1
  backend/routes/holerite.py: 2
  backend/routes/isabella_commanders.py: 1
  backend/routes/isabella_prompt.py: 3
  backend/routes/kpi_churn.py: 1
  backend/routes/ligo_tv.py: 2
  backend/routes/lousa.py: 2
  backend/routes/lousa_map.py: 1
  backend/routes/lousa_rompimento.py: 4
  backend/routes/loyalty_ai.py: 1
  backend/routes/loyalty_imported_db.py: 1
  backend/routes/loyalty_insights.py: 1
  backend/routes/loyalty_opportunities_ai.py: 3
  backend/routes/motor_ia.py: 1
  backend/routes/ont_scan.py: 2
  backend/routes/os_lifecycle.py: 1
  backend/routes/parceria.py: 3
  backend/routes/payment_charges.py: 6
  backend/routes/pre_attendance.py: 1
  backend/routes/presidente_agentes.py: 1
  backend/routes/presidente_ia.py: 8
  backend/routes/projetos_propostas.py: 1
  backend/routes/rede_ia.py: 3
  backend/routes/rede_ia_kmz.py: 1
  backend/routes/saas.py: 2
  backend/routes/security_home.py: 1
  backend/routes/smartolt.py: 3
  backend/routes/stok.py: 1
  backend/routes/universo_ligo.py: 7
  backend/routes/user_magic_links.py: 1
  backend/routes/voice.py: 6
  backend/routes/whatsapp_baileys.py: 3
  backend/routes/whatsapp_channels.py: 9
  backend/routes/whatsapp_config.py: 1
  backend/routes/wifi.py: 1
