"""
os_inventory_guardrail.py — CTO 2026-02 — Guarda Patrimonial na Finalização de OS.

DECISÕES OFICIAIS DO CEO/CTO:
  Q1=c  Híbrido — fechamento interno só movimenta se houver atendimento físico.
  Q2=b  Auto-pull — se ONT está na empresa, faz Empresa→Técnico→Cliente em uma
        transação auditável.
  Q3=a  Validação SmartOLT em tempo real, bloqueia ou exige override.
  Q4=b  Commit parcial + flag — se SmartOLT falha após mover estoque, marca a
        OS como PENDENTE_CONCILIACAO e reprocessa em background.

REGRAS ABSOLUTAS
  - Nenhuma movimentação sem SN OU MAC confiável (Regra extra do CEO).
  - Toda movimentação grava hash SHA-256 em `inventory_os_movements_audit`.
  - Nenhum equipamento simultaneamente em dois donos.
  - INSTALAÇÃO: Técnico→Cliente (ou Empresa→Técnico→Cliente).
  - RETIRADA: Cliente→Técnico.
  - TROCA: Cliente→Técnico (antiga) + Técnico/Empresa→Cliente (nova).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db


# ═══════════ Status / Owner constants ═══════════════════════════════════════
OWNER_EMPRESA = "empresa"
OWNER_TECNICO = "tecnico"
OWNER_CLIENTE = "cliente"

STATUS_INSTALLED = "instalada"          # at client
STATUS_WITH_TECH = "com_tecnico"        # tech holds (received from company)
STATUS_RETURNED = "retirada_com_tecnico"  # tech holds (taken from client)
STATUS_AVAILABLE = "disponivel"         # at company
STATUS_DEFECTIVE = "defeito_devolver_empresa"

OS_TYPES_PHYSICAL = ("instalacao", "retirada", "troca", "reparo")

# Movimentos não-overridáveis (bloqueio absoluto, sem override possível)
BLOCK_REASONS_NON_OVERRIDABLE = {
    "regra_absoluta_sem_sn_e_mac",
    "regra_4_equipamento_nao_existe",
    "regra_4_equipamento_de_outro_cliente",
    "regra_4_equipamento_bloqueado",
    "regra_4_equipamento_defeituoso",
    "regra_2_retirada_equipamento_nao_pertence_cliente",
    "regra_d3_sn_nao_confiavel_requer_rescan",
}


# ═══════════ Utilities ════════════════════════════════════════════════════════
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_id(s: Any) -> str:
    """Normaliza MAC/SN para comparação (uppercase, sem separadores)."""
    if not s:
        return ""
    return "".join(c for c in str(s).upper() if c.isalnum())


def _audit_hash(record: Dict[str, Any]) -> str:
    """SHA-256 sobre os campos críticos da movimentação. Determinístico."""
    canon = json.dumps({
        k: record.get(k) for k in (
            "os_id", "ticket_id", "client_id", "technician_id",
            "equipment_id", "sn", "mac", "movement_type",
            "origin_owner", "destination_owner",
            "created_at", "actor_id",
        )
    }, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


async def _persist_audit(records: List[Dict[str, Any]]) -> List[str]:
    """Persiste movimentações via contrato canônico `inventory_movements`.

    CTO 16/02/2026 — Fase 2: toda escrita passa pelo helper canônico
    (`services.inventory_movements.write_movement`), que valida schema,
    blocklist (D3=a: AUTOSN_*) e duplica nomes canonical↔legacy. A
    collection física permanece `inventory_os_movements_audit` (D1=b).
    """
    from services.inventory_movements import write_movement, InventoryMovementError  # noqa: E402
    hashes: List[str] = []
    for r in records:
        r.setdefault("created_at", _now_iso())
        r["audit_hash"] = _audit_hash(r)
        # Compat: campos canonical para o helper validar.
        if "origin_owner" in r and "origin_type" not in r:
            r["origin_type"] = r["origin_owner"]
        if "destination_owner" in r and "destination_type" not in r:
            r["destination_type"] = r["destination_owner"]
        try:
            await write_movement(r)
        except InventoryMovementError:
            # Validação falhou — grava como `blocked_attempt` ao invés de
            # silenciar. Preserva trilha.
            raise
        hashes.append(r["audit_hash"])
        # Mantém compat com leituras que usam `hash_auditoria`
        r["hash_auditoria"] = r["audit_hash"]
    return hashes


# ═══════════ Equipment lookup ═══════════════════════════════════════════════
async def _find_equipment(company_id: str, *, sn: Optional[str] = None,
                            mac: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Localiza ONT por SN OU MAC (case-insensitive, sem separadores).
    Retorna o documento `stok_onts` ou None."""
    if not sn and not mac:
        return None
    candidates: List[Dict[str, Any]] = []
    if sn:
        norm = _norm_id(sn)
        async for o in db.stok_onts.find({"company_id": company_id}, {"_id": 0}):
            if _norm_id(o.get("scan_sn")) == norm or _norm_id(o.get("sn")) == norm:
                candidates.append(o)
    if mac and not candidates:
        norm = _norm_id(mac)
        async for o in db.stok_onts.find({"company_id": company_id}, {"_id": 0}):
            if _norm_id(o.get("mac")) == norm:
                candidates.append(o)
    if not candidates:
        return None
    # Se múltiplos achados com mesmo SN/MAC → conflito. Bloqueia.
    if len(candidates) > 1:
        return {"_conflict": True, "matches": candidates}
    # D3=a (CTO 16/02/2026) — se a ONT no estoque tem SN auto-gerado
    # (AUTOSN_*) OU sn_auto_generated=True, ela precisa ser re-scaneada
    # antes de qualquer movimento. Sinaliza no doc retornado.
    from services.inventory_movements import is_sn_blocked  # noqa: E402
    eq = candidates[0]
    eq_sn = eq.get("scan_sn") or eq.get("sn")
    auto_flag = str(eq.get("sn_auto_generated", "")).lower() in ("true", "1", "yes")
    if is_sn_blocked(eq_sn) or auto_flag:
        eq = dict(eq)
        eq["_sn_not_trusted"] = True
        eq["_sn_not_trusted_reason"] = (
            f"SN do estoque é {eq_sn!r}, auto_gen={auto_flag}. Re-scan obrigatório."
        )
    return eq


# ═══════════ Validation hooks ════════════════════════════════════════════════
def _validate_sn_or_mac(sn: Optional[str], mac: Optional[str],
                          reasons: List[str]) -> bool:
    """Regra absoluta: precisa SN OU MAC confiável (≥4 chars).

    D3=a (CTO 16/02/2026): se o SN informado bate com a blocklist de
    SN auto-gerado (AUTOSN_*, REAL-LABEL-*-FIXED), bloqueia. Exige re-scan.
    """
    from services.inventory_movements import is_sn_blocked  # noqa: E402
    norm_sn = _norm_id(sn)
    norm_mac = _norm_id(mac)
    if not norm_sn and not norm_mac:
        reasons.append("regra_absoluta_sem_sn_e_mac")
        return False
    if norm_sn and len(norm_sn) < 4:
        reasons.append("regra_absoluta_sn_invalido")
        return False
    if norm_mac and len(norm_mac) < 6:
        reasons.append("regra_absoluta_mac_invalido")
        return False
    # D3=a — SN não-confiável (AUTOSN_*, REAL-LABEL-*-FIXED)
    if sn and is_sn_blocked(sn):
        reasons.append("regra_d3_sn_nao_confiavel_requer_rescan")
        return False
    return True


async def _validate_smartolt(ticket: Dict[str, Any], sn: Optional[str],
                              mac: Optional[str],
                              reasons: List[str]) -> Dict[str, Any]:
    """Valida cruzamento com SmartOLT (cache + tentativa live).
    Retorna {available, divergence, snapshot}."""
    snapshot: Dict[str, Any] = {"available": False, "divergence": None}
    try:
        from routes.smartolt import resolve_signal_for_ticket  # noqa: WPS433
        onu = await resolve_signal_for_ticket(ticket)
        if not onu:
            snapshot["available"] = False
            return snapshot
        snapshot["available"] = True
        snapshot["sn"] = onu.get("sn")
        snapshot["mac"] = onu.get("mac")
        snapshot["onu_id"] = onu.get("unique_external_id")
        snapshot["board"] = onu.get("board")
        snapshot["port"] = onu.get("port")
        snapshot["olt_id"] = onu.get("olt_id")
        snapshot["olt_name"] = onu.get("olt_name")
        snapshot["status"] = onu.get("status")
        # Divergência: SN ou MAC informado bate com o SmartOLT?
        ns = _norm_id(sn)
        nm = _norm_id(mac)
        s_sn = _norm_id(onu.get("sn"))
        s_mac = _norm_id(onu.get("mac"))
        if ns and s_sn and ns != s_sn:
            snapshot["divergence"] = f"sn_divergente:{ns}!={s_sn}"
            reasons.append("regra_5_smartolt_divergencia_sn")
        if nm and s_mac and nm != s_mac:
            snapshot["divergence"] = (
                (snapshot["divergence"] + "|" if snapshot.get("divergence")
                 else "") + f"mac_divergente:{nm}!={s_mac}"
            )
            reasons.append("regra_5_smartolt_divergencia_mac")
    except Exception as e:  # pragma: no cover — best-effort
        snapshot["error"] = str(e)
        snapshot["available"] = False
    return snapshot


# ═══════════ Movement primitive ═════════════════════════════════════════════
async def _move_equipment(equip: Dict[str, Any], *,
                            from_owner_type: str, from_owner_id: Optional[str],
                            to_owner_type: str, to_owner_id: Optional[str],
                            new_status: str) -> Dict[str, Any]:
    """Atualiza `stok_onts` com novo dono/status. Retorna before/after.
    Idempotente por mac (chave única)."""
    before = {
        "location_type": equip.get("location_type"),
        "location_id": equip.get("location_id"),
        "status": equip.get("status"),
        "client_name": equip.get("client_name"),
    }
    upd = {
        "location_type": to_owner_type,
        "location_id": to_owner_id,
        "status": new_status,
        "updated_at": _now_iso(),
    }
    await db.stok_onts.update_one(
        {"company_id": equip.get("company_id"),
         "mac": equip.get("mac")},
        {"$set": upd},
    )
    after = {**before, **upd}
    return {"before": before, "after": after}


# ═══════════ Pre-flight gating ═══════════════════════════════════════════════
def _is_movement_required(ticket: Dict[str, Any],
                            completion: Dict[str, Any]) -> Tuple[bool, str]:
    """Q1=c (híbrido): decide se este fechamento exige movimentação.

    Retorna (required, classification) onde classification ∈ {
        'physical_install', 'physical_withdraw', 'physical_swap',
        'physical_repair', 'admin_no_attendance',
        'physical_repair_no_swap',
    }"""
    ttype = (ticket.get("type") or "").lower()
    physical = bool(completion.get("physical_attendance", True))
    # Fechamento administrativo sem atendimento físico → não movimenta
    if not physical:
        return False, "admin_no_attendance"
    if ttype == "instalacao":
        return True, "physical_install"
    if ttype == "retirada":
        return True, "physical_withdraw"
    if ttype == "troca":
        return True, "physical_swap"
    if ttype == "reparo":
        # Reparo só movimenta se houve troca de ONT (old + new)
        old = completion.get("old_ont_mac") or completion.get("old_ont_sn")
        new = completion.get("new_ont_mac") or completion.get("new_ont_sn")
        if old or new:
            return True, "physical_swap"
        return False, "physical_repair_no_swap"
    return False, "admin_no_attendance"


# ═══════════ Main chokepoint ═════════════════════════════════════════════════
async def enforce_os_inventory_movement(
    ticket: Dict[str, Any],
    completion_data: Dict[str, Any],
    actor: Dict[str, Any],
) -> Dict[str, Any]:
    """Chokepoint global. Aplica todas as regras + executa as movimentações.

    Args:
      ticket: documento de tickets (precisa company_id, id, type,
              client_snapshot, assigned_collaborator_id, atlaz_pppoe_user).
      completion_data: payload de completion_data + flags do gestor
              (physical_attendance, admin_reason, smartolt_override_motivo,
               old_ont_*, new_ont_*, ont/ont_sn).
      actor: {id, name, email, role, is_super_admin}.

    Returns:
      {
        allowed: bool,
        blocked_reasons: list[str],
        classification: str,
        movements: [ {movement_type, sn, mac, origin, destination, audit_id}],
        smartolt: {...},
        smartolt_override_applied: bool,
        os_pending_conciliation: bool,   # Q4=b
        audit_ids: list[str],
      }
    """
    company_id = ticket.get("company_id") or "co-demo"
    client_snap = ticket.get("client_snapshot") or {}
    client_id = client_snap.get("id") or client_snap.get("subscriber_id")
    tech_id = ticket.get("assigned_collaborator_id")
    reasons: List[str] = []
    movements: List[Dict[str, Any]] = []
    audit_records: List[Dict[str, Any]] = []
    smartolt_override_applied = False
    os_pending_conciliation = False
    smartolt_snap: Dict[str, Any] = {"available": False}

    required, classification = _is_movement_required(ticket, completion_data)

    base_audit = {
        "os_id": ticket.get("id"),
        "ticket_id": ticket.get("id"),
        "ticket_type": ticket.get("type"),
        "company_id": company_id,
        "client_id": client_id,
        "client_name": client_snap.get("name"),
        "technician_id": tech_id,
        "actor_id": actor.get("id"),
        "actor_role": actor.get("role"),
        "actor_email": actor.get("email"),
        "actor_origin": actor.get("origin") or "admin_close",
        "classification": classification,
    }

    # ── Fechamento sem atendimento físico — não movimenta, mas exige motivo ─
    if not required:
        if classification == "admin_no_attendance":
            motivo = (completion_data.get("admin_reason") or "").strip()
            if len(motivo) < 5:
                reasons.append("admin_close_motivo_obrigatorio")
                return {
                    "allowed": False, "blocked_reasons": reasons,
                    "classification": classification, "movements": [],
                    "smartolt": smartolt_snap,
                    "smartolt_override_applied": False,
                    "os_pending_conciliation": False, "audit_ids": [],
                }
            # Auditoria do fechamento administrativo (sem movimentação)
            audit = {**base_audit, "movement_type": "admin_close_no_movement",
                     "admin_close_without_inventory": True, "motivo": motivo,
                     "before": {}, "after": {}}
            audit_records.append(audit)
        hashes = await _persist_audit(audit_records)
        return {
            "allowed": True, "blocked_reasons": [],
            "classification": classification, "movements": [],
            "smartolt": smartolt_snap, "smartolt_override_applied": False,
            "os_pending_conciliation": False, "audit_ids": hashes,
        }

    # ── Coleta SN/MAC esperados ─────────────────────────────────────────────
    new_sn = (completion_data.get("new_ont_sn") or completion_data.get("ont_sn")
              or completion_data.get("scan_sn"))
    new_mac = completion_data.get("new_ont_mac") or completion_data.get("ont")
    old_sn = completion_data.get("old_ont_sn")
    old_mac = completion_data.get("old_ont_mac")

    # ── Movimento NEW (instalação/troca-nova) ───────────────────────────────
    if classification in ("physical_install", "physical_swap"):
        if not _validate_sn_or_mac(new_sn, new_mac, reasons):
            pass  # já adicionou em reasons
        else:
            equip = await _find_equipment(company_id, sn=new_sn, mac=new_mac)
            if not equip:
                reasons.append("regra_4_equipamento_nao_existe")
            elif equip.get("_conflict"):
                reasons.append("regra_4_equipamento_conflito_sn_mac")
            elif equip.get("_sn_not_trusted"):
                reasons.append("regra_d3_sn_nao_confiavel_requer_rescan")
            else:
                # Estado precisa permitir
                if equip.get("status") == STATUS_DEFECTIVE:
                    reasons.append("regra_4_equipamento_defeituoso")
                elif equip.get("location_type") == OWNER_CLIENTE and \
                        equip.get("location_id") != client_id:
                    reasons.append("regra_4_equipamento_de_outro_cliente")
                elif equip.get("status") in ("bloqueado", "perdido"):
                    reasons.append("regra_4_equipamento_bloqueado")
                else:
                    # SmartOLT cross-check (Q3=a, bloqueante se divergir)
                    smartolt_snap = await _validate_smartolt(
                        ticket, new_sn, new_mac, reasons)
                    # Override do gestor para divergência SmartOLT
                    override_motivo = (completion_data.get(
                        "smartolt_override_motivo") or "").strip()
                    if any(r.startswith("regra_5_smartolt") for r in reasons):
                        if (actor.get("is_super_admin") or actor.get("role")
                                in ("gestor", "administrador", "super_admin")) \
                                and len(override_motivo) >= 20:
                            # Override aceito — limpa regras_5 (overridable)
                            reasons = [r for r in reasons
                                       if not r.startswith("regra_5_smartolt")]
                            smartolt_override_applied = True
                    # Decide auto-pull empresa→técnico→cliente (Q2=b)
                    if not reasons:
                        moves_for_new: List[Dict[str, Any]] = []
                        loc_t = equip.get("location_type")
                        loc_id = equip.get("location_id")
                        # Empresa → Técnico (auto-pull)
                        if loc_t == OWNER_EMPRESA:
                            change = await _move_equipment(
                                equip,
                                from_owner_type=OWNER_EMPRESA,
                                from_owner_id=loc_id,
                                to_owner_type=OWNER_TECNICO,
                                to_owner_id=tech_id,
                                new_status=STATUS_WITH_TECH,
                            )
                            moves_for_new.append({
                                "movement_type": "auto_pull_empresa_tecnico",
                                "origin_owner": OWNER_EMPRESA,
                                "destination_owner": OWNER_TECNICO,
                                **change,
                            })
                            equip["location_type"] = OWNER_TECNICO
                            equip["location_id"] = tech_id
                        elif loc_t == OWNER_TECNICO and loc_id != tech_id:
                            reasons.append(
                                "regra_4_equipamento_outro_tecnico")
                        # Técnico → Cliente
                        if not reasons:
                            change = await _move_equipment(
                                equip,
                                from_owner_type=OWNER_TECNICO,
                                from_owner_id=tech_id,
                                to_owner_type=OWNER_CLIENTE,
                                to_owner_id=client_id,
                                new_status=STATUS_INSTALLED,
                            )
                            moves_for_new.append({
                                "movement_type": "instalacao_tecnico_cliente"
                                if classification == "physical_install"
                                else "troca_entrega_tecnico_cliente",
                                "origin_owner": OWNER_TECNICO,
                                "destination_owner": OWNER_CLIENTE,
                                **change,
                            })
                            # Auditoria para cada movimento
                            for m in moves_for_new:
                                audit = {**base_audit, **m,
                                         "equipment_id": equip.get("mac"),
                                         "sn": equip.get("scan_sn")
                                              or equip.get("sn"),
                                         "mac": equip.get("mac"),
                                         "model": equip.get("model"),
                                         "smartolt_validation": smartolt_snap,
                                         "smartolt_override_motivo":
                                             override_motivo or None}
                                audit_records.append(audit)
                                movements.append({
                                    "movement_type": m["movement_type"],
                                    "sn": equip.get("scan_sn")
                                          or equip.get("sn"),
                                    "mac": equip.get("mac"),
                                    "origin": m["origin_owner"],
                                    "destination": m["destination_owner"],
                                })

    # ── Movimento OLD (retirada / troca-devolução) ──────────────────────────
    if classification == "physical_withdraw" or classification == "physical_swap":
        sn_old = old_sn if classification == "physical_swap" else new_sn
        mac_old = old_mac if classification == "physical_swap" else new_mac
        # Para retirada, completion_data usa ont/ont_sn como retirado
        if not _validate_sn_or_mac(sn_old, mac_old, reasons):
            pass
        else:
            equip_old = await _find_equipment(
                company_id, sn=sn_old, mac=mac_old)
            if not equip_old:
                reasons.append("regra_4_equipamento_nao_existe")
            elif equip_old.get("_conflict"):
                reasons.append("regra_4_equipamento_conflito_sn_mac")
            elif equip_old.get("_sn_not_trusted"):
                reasons.append("regra_d3_sn_nao_confiavel_requer_rescan")
            else:
                # Precisa pertencer ao cliente
                if equip_old.get("location_type") != OWNER_CLIENTE or \
                        equip_old.get("location_id") != client_id:
                    reasons.append(
                        "regra_2_retirada_equipamento_nao_pertence_cliente")
                else:
                    # Defeituoso? muda status pra defeito_devolver_empresa
                    is_def = bool(completion_data.get("is_defective"))
                    new_status = STATUS_DEFECTIVE if is_def else STATUS_RETURNED
                    change = await _move_equipment(
                        equip_old,
                        from_owner_type=OWNER_CLIENTE,
                        from_owner_id=client_id,
                        to_owner_type=OWNER_TECNICO,
                        to_owner_id=tech_id,
                        new_status=new_status,
                    )
                    m = {
                        "movement_type":
                            "retirada_cliente_tecnico"
                            if classification == "physical_withdraw"
                            else "troca_devolucao_cliente_tecnico",
                        "origin_owner": OWNER_CLIENTE,
                        "destination_owner": OWNER_TECNICO,
                        **change,
                    }
                    audit = {**base_audit, **m,
                             "equipment_id": equip_old.get("mac"),
                             "sn": equip_old.get("scan_sn")
                                  or equip_old.get("sn"),
                             "mac": equip_old.get("mac"),
                             "model": equip_old.get("model"),
                             "is_defective": is_def,
                             "smartolt_validation": smartolt_snap}
                    audit_records.append(audit)
                    movements.append({
                        "movement_type": m["movement_type"],
                        "sn": equip_old.get("scan_sn")
                              or equip_old.get("sn"),
                        "mac": equip_old.get("mac"),
                        "origin": m["origin_owner"],
                        "destination": m["destination_owner"],
                    })

    # ── Resultado ────────────────────────────────────────────────────────────
    allowed = not reasons
    # Q4=b: se movimentos OK mas SmartOLT indisponível, marca conciliação
    if allowed and not smartolt_snap.get("available") and movements:
        os_pending_conciliation = True

    # Grava auditoria SEMPRE (incluindo tentativas bloqueadas)
    if not allowed:
        audit_records.append({**base_audit,
                              "movement_type": "blocked_attempt",
                              "blocked_reasons": reasons,
                              "smartolt_validation": smartolt_snap,
                              "sn": new_sn, "mac": new_mac})
    hashes = await _persist_audit(audit_records)

    return {
        "allowed": allowed,
        "blocked_reasons": reasons,
        "classification": classification,
        "movements": movements,
        "smartolt": smartolt_snap,
        "smartolt_override_applied": smartolt_override_applied,
        "os_pending_conciliation": os_pending_conciliation,
        "audit_ids": hashes,
    }


def explain_block(reasons: List[str]) -> str:
    """Tradução humana dos motivos de bloqueio."""
    mapping = {
        "regra_absoluta_sem_sn_e_mac":
            "É obrigatório informar SN OU MAC do equipamento.",
        "regra_absoluta_sn_invalido": "SN informado é inválido.",
        "regra_absoluta_mac_invalido": "MAC informado é inválido.",
        "regra_4_equipamento_nao_existe":
            "Equipamento não está no estoque (nem empresa, nem técnico).",
        "regra_4_equipamento_conflito_sn_mac":
            "Existe mais de um equipamento com o mesmo SN/MAC — conflito.",
        "regra_4_equipamento_defeituoso":
            "Equipamento está marcado como defeituoso, não pode ser instalado.",
        "regra_4_equipamento_de_outro_cliente":
            "Este equipamento já está vinculado a OUTRO cliente.",
        "regra_4_equipamento_bloqueado":
            "Equipamento está bloqueado/perdido.",
        "regra_4_equipamento_outro_tecnico":
            "Equipamento pertence a outro técnico — transfira antes.",
        "regra_2_retirada_equipamento_nao_pertence_cliente":
            "Equipamento retirado não pertence a este cliente.",
        "regra_5_smartolt_divergencia_sn":
            "SmartOLT mostra SN diferente do informado.",
        "regra_5_smartolt_divergencia_mac":
            "SmartOLT mostra MAC diferente do informado.",
        "admin_close_motivo_obrigatorio":
            "Motivo do fechamento administrativo é obrigatório (≥5 chars).",
        "regra_d3_sn_nao_confiavel_requer_rescan":
            "Equipamento sem SN confiável. Re-scan obrigatório antes da "
            "movimentação.",
    }
    return " | ".join(mapping.get(r, r) for r in reasons)
