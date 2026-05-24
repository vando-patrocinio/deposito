"""Drive Backup Service — exporta dados do PontoIA para o Google Drive.

Coleções incluídas no snapshot (read-only):
  - settings, branding, plans, subscribers, collaborators, pracas
  - aihub_agents, aihub_integrations (com secrets MASCARADOS por padrão)
  - motor_ia_config (mascarado)
  - secretaria_config (mascarado)
  - whatsapp settings, tab_permissions
  - sla / churn / signature configs

NÃO incluímos (volume e privacidade):
  - tickets, lousa_logs, clock_records, wa_messages históricos
  - audit logs, motor_ia_usage

O foco é re-criar o sistema funcional do ZERO. Histórico operacional fica
no backup do MongoDB hospedado (responsabilidade do provedor de banco).
"""
from __future__ import annotations

import io
import json
import logging
import os
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

from core import DEMO_COMPANY_ID, now_iso
from database import db

logger = logging.getLogger("drive_backup")

DRIVE_FOLDER_NAME = "PontoIA-Backups"

# Coleções que entram no snapshot. Tupla (collection, mascarar_secrets).
# =============================================================================
# BACKUP_COLLECTIONS — Collections capturadas no snapshot.
#
# Filosofia: cobrir TUDO que é "configuração" + "dado operacional" + "estado
# salvo pelo usuário". Excluir apenas LOGS GIGANTES que se regeneram sozinhos
# (vide EXCLUDED_FROM_BACKUP abaixo).
#
# Cada tupla: (collection_name, must_mask_secrets)
#   must_mask=True → quando include_secrets=False, campos sensíveis viram
#   "***REDACTED***" pra que o arquivo de backup possa ser compartilhado
#   sem vazar credenciais.
# =============================================================================
BACKUP_COLLECTIONS: List[tuple[str, bool]] = [
    # --- Configuração global e branding ---
    ("settings", False),
    ("settings_by_company", False),
    ("branding", False),
    ("company_branding", False),
    ("companies", False),
    ("counters", False),

    # --- Planos, assinantes e endereços ---
    ("plans", False),
    ("plan_adjustments_scheduled", False),
    ("plan_adjustments_log", False),
    ("inflation_indices", False),
    ("subscribers", False),
    ("subscriber_addresses", False),
    ("subscriber_access_points", False),
    ("subscriber_phones", False),
    ("subscriber_documents", False),
    ("subscriber_readjustments", False),

    # --- Pracas / Filiais ---
    ("pracas", False),
    ("fin_filiais", False),
    ("bairros_vlan_map", False),
    ("geofences", False),

    # --- Faturas (Billing Engine) + dunning ---
    ("subscriber_invoices", False),
    ("billing_dunning_rules", False),
    ("billing_dunning_events", False),
    ("billing_runs", False),

    # --- Colaboradores / Equipes / RH ---
    ("collaborators", False),
    ("collaborator_assets", False),
    ("collab_returns", False),
    ("users", True),  # password_hash mascarado se include_secrets=False
    ("clock_records", False),
    ("feriados", False),
    ("holidays", False),
    ("appointments", False),
    ("location_logs", False),
    ("vehicle_checklists", False),

    # --- Lousa (Tickets) ---
    ("tickets", False),
    ("lousa_alerts", False),
    ("lousa_dashboard_config", False),
    ("lousa_quality_config", False),
    ("lousa_auto_resched_config", False),
    ("lousa_closure_analysis", False),

    # --- Rede / CTOs / OLTs ---
    ("ctos", False),
    ("cto_history", False),
    ("cto_validations", False),
    ("cto_audits", False),
    ("central_ont_settings", False),
    ("smartolt_olts", True),
    ("smartolt_config", True),
    ("smartolt_onus", False),
    ("network_outages", False),
    ("network_ces", False),

    # --- Atlaz integration ---
    ("atlaz_config", True),  # api_key mascarado
    ("atlaz_clients_cache", False),

    # --- Financeiro ---
    ("fin_cash_accounts", False),
    ("fin_cash_movements", False),
    ("fin_categories", False),
    ("fin_suppliers", False),
    ("budgets", False),
    ("purchases", False),
    ("bank_import_memory", False),

    # --- Estoque ---
    ("stok_stock", False),
    ("stok_services", False),
    ("stok_history", False),
    ("stok_balanco_sessions", False),

    # --- IA Hub ---
    ("aihub_agents", False),
    ("aihub_integrations", True),
    ("aihub_settings", False),
    ("aihub_templates", False),

    # --- Agentes IA (configs e prompts) ---
    ("motor_ia_config", True),
    ("motor_ia_budget", False),
    ("secretaria_config", True),
    ("isabella_config", False),
    ("isabella_prompt_fragments", False),
    ("alvaro_analyses", False),
    ("ai_agent_switches", False),
    ("ai_preventive_config", False),
    ("ai_training_kb", False),
    ("ai_training_schedule", False),
    ("ai_training_scenarios", False),
    ("ai_training_decision_matrix", False),
    ("rede_ia_settings", False),
    ("churn_briefing_schedule", False),

    # --- WhatsApp (creds + sessão Baileys + Meta + Twilio) ---
    ("whatsapp_meta_creds", True),
    ("whatsapp_twilio_creds", True),
    ("wa_business_hours", False),
    ("wa_autoreply_config", False),
    ("wa_identification", False),
    ("wa_lid_map", False),
    ("wa_quick_images", False),
    # Sessão WhatsApp (Baileys creds + Signal keys) — SEMPRE incluída,
    # nunca mascarada. Sem isso a sessão não restaura e o usuário precisa
    # escanear QR Code de novo.
    ("wa_auth_state", False),

    # --- Outros ---
    ("public_access_tokens", True),
    ("payroll_whatsapp_notifications", False),
]

# Collections deliberadamente EXCLUÍDAS — listadas pra documentação/debug,
# não vão pro backup. Se precisar de alguma, basta mover pra BACKUP_COLLECTIONS.
EXCLUDED_FROM_BACKUP: List[str] = [
    # Logs e histórico transitórios (regeneráveis ou irrelevantes pra restore)
    "atlaz_sync_logs",          # 28k+ docs, log de cada sync
    "subscriber_match_log",     # 290k+ docs, log de matching
    "motor_ia_usage",           # 4k+, métricas de uso
    "ai_preventive_suggestions",  # 2.9k, sugestões recalculáveis
    "aihub_wa_messages",        # 1k+, histórico de msgs WhatsApp
    "whatsapp_system_events",   # 2k+, eventos sistema
    "notifications",            # 1.6k, notificações já lidas
    "push_alerts_log",          # 1.7k
    "ai_training_runs",         # 200+, histórico de execução IA
    "ai_training_tests",        # 20, tests recalculáveis
    "aihub_coaching",           # 230, coaching gerado por sessão
    "secretaria_log",           # log de chamadas chatgpt
    "manager_assistant_log",    # log conversas Marcio
    "manager_assistant_pending",
    "login_attempts",           # antifraude
    "drive_backups",            # próprio histórico (evita recursão!)
    "drive_restore_log",        # log de restores
    "drive_credentials",        # NÃO restaurar! Cada instância tem o próprio
    "bank_import_staging",      # staging de importações em andamento
    "bank_import_history",
    "onboarding_sessions",
    "aihub_webhook_events",
    "marker_router_log",
    "payroll_access_logs",
    "print_audit",
    "platform_audit",
    "ticket_logs",              # log detalhado de cada ticket
    "lousa_logs",
    "stok_admin_log",
    "smartolt_actions",
    "smartolt_zone_audit",
    "connection_audit",
    "connection_snapshots",
    "network_ping_log",
    "network_notifications",
    "system_alerts",
    "bad_signal_auth_requests",
    "wa_conversations",         # histórico de chats, muito pesado
    "wa_system_events",
    "outage_drafts",
    "churn_insights",
    "ai_insights",
    "ai_corrections",           # treino contínuo, regenera
    "aihub_evaluations",
    "aihub_messages",
    "aihub_calls",
    "alvaro_reports",
    "cto_photo_analyses",
    "rede_ia_history",
    "rede_ia_analyses",
    "ai_agent_switch_history",
    "holerite_ai_drafts",
    "disparo_boleto_runs",
    "disparo_suggestions",
    "sales_leads",
    "boleto_flow_state",
    "manufacturer_cache",
    "cep_cache",
    "gestao_reports",
    "gestao_competitive",
    "push_subscriptions",       # tokens específicos do device
    "payment_transactions",     # gerados pelo gateway
    "whatsapp_log",
    "schema_migrations",        # interno
]


# =============================================================================
# FILE_ASSET_PATHS — Diretórios do filesystem incluídos no backup.
#
# Imagens e PDFs ficam FORA do MongoDB (no disco do container) por questão de
# performance. Mas precisam ir junto pro Drive senão o restore num servidor
# novo perde fotos do onboarding, holerites e imagens do WhatsApp.
#
# Cada entrada: (path_no_disco, nome_no_tar, include_by_default)
# =============================================================================
FILE_ASSET_PATHS: List[tuple[str, str, bool]] = [
    # Documentos de cadastro (RG/CNH/comprovante de endereço dos assinantes)
    ("/app/backend/uploads/onboarding", "onboarding/", True),
    # Holerites em PDF (folha de pagamento) — RH crítico
    ("/app/data/holerites", "holerites/", True),
    # Imagens rápidas mandadas pelos atendentes via WhatsApp
    ("/app/backend/uploads/wa_quickimages", "wa_quickimages/", True),
    # Transcrições PDF de áudios WhatsApp
    ("/app/backend/uploads/wa_transcripts", "wa_transcripts/", True),
    # Áudios brutos WhatsApp — opt-in (pesam, e transcrição já está incluída)
    ("/app/backend/uploads/wa_audio", "wa_audio/", False),
    # Static do backend (boletos demo, etc)
    ("/app/backend/static", "static/", False),
]

SECRET_FIELDS = {
    "openrouter_api_key", "openai_audio_key",
    "webhook_token", "key", "secret", "password_hash",
    "atlaz_token", "atlaz_api_key", "stripe_secret", "url_password",
    "client_secret", "api_key", "api_secret",
    "smartolt_token", "smartolt_api_key", "smartolt_password",
    "magnusbilling_key", "magnusbilling_secret",
}


# ============================================================
# Credentials management
# ============================================================
async def _get_credentials(company_id: str) -> Optional[Credentials]:
    """Carrega credenciais OAuth para a empresa. Faz auto-refresh.

    Quando o refresh falha por `invalid_grant` (usuário revogou no console
    Google ou refresh_token expirou), marca `token_revoked=True` no doc
    para que a UI consiga oferecer o botão de Reconectar sem o usuário
    precisar desconectar manualmente primeiro.
    """
    doc = await db.drive_credentials.find_one({"company_id": company_id}, {"_id": 0})
    if not doc:
        return None
    creds = Credentials(
        token=doc.get("access_token"),
        refresh_token=doc.get("refresh_token"),
        token_uri=doc.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=doc.get("client_id") or os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=doc.get("client_secret") or os.environ.get("GOOGLE_CLIENT_SECRET"),
        scopes=doc.get("scopes") or ["https://www.googleapis.com/auth/drive.file"],
    )
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
            await db.drive_credentials.update_one(
                {"company_id": company_id},
                {"$set": {
                    "access_token": creds.token,
                    "expiry": creds.expiry.isoformat() if creds.expiry else None,
                    "updated_at": now_iso(),
                    "token_revoked": False,
                    "last_refresh_error": None,
                }},
            )
        except Exception as e:
            msg = str(e)
            logger.warning("[drive] refresh token failed for %s: %s", company_id, msg)
            is_revoked = "invalid_grant" in msg or "expired" in msg.lower() or "revoked" in msg.lower()
            await db.drive_credentials.update_one(
                {"company_id": company_id},
                {"$set": {
                    "token_revoked": is_revoked,
                    "last_refresh_error": msg[:300],
                    "last_refresh_error_at": now_iso(),
                }},
            )
            return None
    return creds


async def is_connected(company_id: str) -> bool:
    """True se a empresa já autorizou Drive."""
    doc = await db.drive_credentials.find_one(
        {"company_id": company_id}, {"_id": 0, "refresh_token": 1, "user_email": 1}
    )
    return bool(doc and doc.get("refresh_token"))


async def get_connection_info(company_id: str) -> Dict[str, Any]:
    doc = await db.drive_credentials.find_one(
        {"company_id": company_id},
        {"_id": 0, "user_email": 1, "connected_at": 1, "folder_id": 1,
         "folder_url": 1, "token_revoked": 1, "last_refresh_error": 1,
         "last_refresh_error_at": 1},
    )
    if not doc:
        return {"connected": False}
    return {
        "connected": True,
        "user_email": doc.get("user_email"),
        "connected_at": doc.get("connected_at"),
        "folder_id": doc.get("folder_id"),
        "folder_url": doc.get("folder_url"),
        "needs_reconnect": bool(doc.get("token_revoked")),
        "last_error": doc.get("last_refresh_error"),
        "last_error_at": doc.get("last_refresh_error_at"),
    }


async def disconnect(company_id: str) -> None:
    await db.drive_credentials.delete_one({"company_id": company_id})


# ============================================================
# Drive helpers
# ============================================================
def _build_service(creds: Credentials):
    """Cria o objeto google-api-client. Roda sync (a lib não tem versão async).

    Encapsulamos em loop.run_in_executor pra não bloquear o event loop."""
    return build("drive", "v3", credentials=creds, cache_discovery=False)


async def _ensure_root_folder(company_id: str, service) -> Dict[str, str]:
    """Garante que existe a pasta `PontoIA-Backups` na raiz do Drive da conta.

    Retorna {"id": ..., "url": ...}. Salva no doc da empresa para reuso.
    """
    cred_doc = await db.drive_credentials.find_one({"company_id": company_id}, {"_id": 0})
    if cred_doc and cred_doc.get("folder_id"):
        # Valida que ainda existe — se foi apagado, recria
        try:
            service.files().get(fileId=cred_doc["folder_id"], fields="id,name,trashed").execute()
            return {"id": cred_doc["folder_id"], "url": cred_doc.get("folder_url") or ""}
        except HttpError:
            pass  # cai pra criar de novo

    metadata = {
        "name": DRIVE_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=metadata, fields="id, webViewLink").execute()
    folder_id = folder["id"]
    folder_url = folder.get("webViewLink", "")
    await db.drive_credentials.update_one(
        {"company_id": company_id},
        {"$set": {"folder_id": folder_id, "folder_url": folder_url}},
    )
    return {"id": folder_id, "url": folder_url}


def _mask(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Mascara campos sensíveis recursivamente."""
    if not isinstance(doc, dict):
        return doc
    out = {}
    for k, v in doc.items():
        if k in SECRET_FIELDS and isinstance(v, str) and v:
            out[k] = f"***REDACTED***(len={len(v)})"
        elif isinstance(v, dict):
            out[k] = _mask(v)
        elif isinstance(v, list):
            out[k] = [_mask(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


def _scan_asset_path(disk_path: str) -> Dict[str, Any]:
    """Conta arquivos e calcula tamanho total de um diretório."""
    p = Path(disk_path)
    if not p.exists() or not p.is_dir():
        return {"exists": False, "files": 0, "size_bytes": 0}
    files = [f for f in p.rglob("*") if f.is_file()]
    size = sum(f.stat().st_size for f in files)
    return {"exists": True, "files": len(files), "size_bytes": size}


async def get_files_assets_info(include_optional: bool = False) -> Dict[str, Any]:
    """Lista todos os diretórios de assets + contagem + tamanho."""
    paths_info = []
    grand_files = 0
    grand_size = 0
    for disk_path, tar_name, default_in in FILE_ASSET_PATHS:
        info = _scan_asset_path(disk_path)
        included = default_in or include_optional
        paths_info.append({
            "disk_path": disk_path,
            "tar_name": tar_name,
            "files": info["files"],
            "size_bytes": info["size_bytes"],
            "size_kb": info["size_bytes"] // 1024,
            "exists": info["exists"],
            "included_by_default": default_in,
            "will_be_included": included,
        })
        if included and info["exists"]:
            grand_files += info["files"]
            grand_size += info["size_bytes"]
    return {
        "paths": paths_info,
        "total_files": grand_files,
        "total_size_bytes": grand_size,
        "total_size_kb": grand_size // 1024,
        "total_size_mb": round(grand_size / 1024 / 1024, 2),
    }


def _build_files_tarball(include_optional: bool = False) -> Optional[bytes]:
    """Empacota os diretórios de assets em um .tar.gz. Retorna bytes ou None
    se não houver arquivos."""
    buf = io.BytesIO()
    file_count = 0
    with tarfile.open(fileobj=buf, mode="w:gz",
                      format=tarfile.PAX_FORMAT) as tar:
        for disk_path, tar_name, default_in in FILE_ASSET_PATHS:
            if not default_in and not include_optional:
                continue
            p = Path(disk_path)
            if not p.exists() or not p.is_dir():
                continue
            for f in p.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(p)
                arcname = f"{tar_name.rstrip('/')}/{rel}"
                try:
                    tar.add(str(f), arcname=arcname)
                    file_count += 1
                except Exception as e:
                    logger.warning("[drive] tarball skip %s: %s", f, e)
    if file_count == 0:
        return None
    return buf.getvalue()


async def _extract_files_tarball(raw: bytes) -> Dict[str, Any]:
    """Descompacta tarball restaurando em /app/backend/uploads e /app/data."""
    buf = io.BytesIO(raw)
    extracted = 0
    errors = []
    # Mapeia prefixo do tar pro disco
    prefix_to_disk = {tar_name.rstrip("/"): disk_path
                       for disk_path, tar_name, _ in FILE_ASSET_PATHS}
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            # Resolve onde extrair
            parts = member.name.split("/", 1)
            if len(parts) < 2:
                continue
            prefix, rest = parts
            disk_root = prefix_to_disk.get(prefix)
            if not disk_root:
                continue
            target = Path(disk_root) / rest
            # Segurança: garante que está dentro do disk_root (evita path traversal)
            try:
                target.resolve().relative_to(Path(disk_root).resolve())
            except ValueError:
                errors.append(f"path traversal blocked: {member.name}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                f_in = tar.extractfile(member)
                if f_in is None:
                    continue
                target.write_bytes(f_in.read())
                extracted += 1
            except Exception as e:
                errors.append(f"{member.name}: {e}")
    return {"extracted": extracted, "errors": errors}


async def get_snapshot_info(company_id: str) -> Dict[str, Any]:
    """Pré-visualiza o conteúdo do próximo backup.

    Retorna contagem de docs por collection que vai ser incluída + tamanho
    estimado. Usado pela UI pra dar transparência ("X collections, Y docs,
    Z MB no próximo snapshot") antes do usuário clicar em backup.
    """
    cid = company_id or DEMO_COMPANY_ID
    breakdown = []
    total_docs = 0
    total_secrets = 0
    for coll_name, must_mask in BACKUP_COLLECTIONS:
        try:
            n = await db[coll_name].count_documents({"company_id": cid})
        except Exception:
            n = 0
        # wa_auth_state usa session_id, não company_id
        if coll_name == "wa_auth_state":
            wa_session = os.environ.get("WA_SESSION_ID", "isabella")
            n = await db.wa_auth_state.count_documents(
                {"session_id": {"$in": [wa_session, cid]}}
            )
        if n > 0:
            breakdown.append({
                "collection": coll_name,
                "docs": n,
                "masked_when_no_secrets": must_mask,
            })
            total_docs += n
            if must_mask:
                total_secrets += 1
    return {
        "company_id": cid,
        "collections_included": len(breakdown),
        "collections_in_schema": len(BACKUP_COLLECTIONS),
        "total_docs": total_docs,
        "collections_with_secrets": total_secrets,
        "breakdown": sorted(breakdown, key=lambda x: -x["docs"]),
        "excluded_collections": EXCLUDED_FROM_BACKUP,
        "filesystem_assets": await get_files_assets_info(include_optional=False),
    }





async def _collect_snapshot(company_id: str, include_secrets: bool) -> Dict[str, Any]:
    """Lê as coleções listadas em BACKUP_COLLECTIONS e devolve dict serializável."""
    snapshot: Dict[str, Any] = {
        "_meta": {
            "company_id": company_id,
            "exported_at": now_iso(),
            "include_secrets": include_secrets,
            "version": "1.0",
        }
    }
    for coll_name, must_mask in BACKUP_COLLECTIONS:
        try:
            # wa_auth_state usa session_id (não company_id) — captura tudo
            # da empresa via convenção: session_id == company_id OU "isabella"
            # (default). Em multi-tenant futuro, mapeia por env.
            if coll_name == "wa_auth_state":
                wa_session = os.environ.get("WA_SESSION_ID", "isabella")
                q = {"session_id": {"$in": [wa_session, company_id]}}
                proj = {"_id": 0}
            else:
                q = {"company_id": company_id}
                proj = {"_id": 0}
            cur = db[coll_name].find(q, proj)
            docs = await cur.to_list(10000)
            if must_mask and not include_secrets:
                docs = [_mask(d) for d in docs]
            snapshot[coll_name] = docs
        except Exception as e:
            logger.warning("[drive] collect %s failed: %s", coll_name, e)
            snapshot[coll_name] = []
    return snapshot


async def _mark_token_revoked(company_id: str, error_msg: str) -> None:
    """Marca a credencial como revogada. Disparado por exceções de refresh
    levantadas pelo google-api-client durante operações (não só em _get_credentials)."""
    await db.drive_credentials.update_one(
        {"company_id": company_id},
        {"$set": {
            "token_revoked": True,
            "last_refresh_error": error_msg[:300],
            "last_refresh_error_at": now_iso(),
        }},
    )


def _is_invalid_grant(exc: Exception) -> bool:
    msg = str(exc).lower()
    return ("invalid_grant" in msg or "token has been expired" in msg
            or "revoked" in msg)


# ============================================================
# Backup
# ============================================================
async def run_backup(company_id: str, include_secrets: bool = False,
                       triggered_by: str = "manual") -> Dict[str, Any]:
    """Executa o backup: snapshot → upload JSON pro Drive."""
    cid = company_id or DEMO_COMPANY_ID
    started = datetime.now(timezone.utc)

    creds = await _get_credentials(cid)
    if not creds:
        raise RuntimeError("Google Drive não conectado para essa empresa.")

    import asyncio
    loop = asyncio.get_event_loop()
    try:
        service = await loop.run_in_executor(None, _build_service, creds)
        root = await _ensure_root_folder(cid, service)
    except Exception as e:
        if _is_invalid_grant(e):
            await _mark_token_revoked(cid, str(e))
            raise RuntimeError(
                "invalid_grant: Token revogado. Reconecte o Google Drive."
            ) from e
        raise

    snapshot = await _collect_snapshot(cid, include_secrets)
    content = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    size = len(content)

    file_name = f"pontoia-backup-{started.strftime('%Y%m%d-%H%M%S')}.json"
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype="application/json", resumable=False)
    file_metadata = {
        "name": file_name,
        "parents": [root["id"]],
        "description": f"PontoIA snapshot ({triggered_by}) - company={cid}",
    }

    try:
        result = await loop.run_in_executor(None,
            lambda: service.files().create(body=file_metadata, media_body=media,
                                              fields="id, webViewLink, size").execute()
        )
    except Exception as e:
        if _is_invalid_grant(e):
            await _mark_token_revoked(cid, str(e))
            await _log_backup(cid, "failed", file_name, size, triggered_by,
                                error="invalid_grant - token revogado")
            raise RuntimeError(
                "invalid_grant: Token revogado. Reconecte o Google Drive."
            ) from e
        await _log_backup(cid, "failed", file_name, size, triggered_by, error=str(e)[:300])
        raise

    # =================================================================
    # ARQUIVOS FÍSICOS — tar.gz com fotos do onboarding, holerites, etc.
    # FULL backup: inclui TUDO (inclusive wa_audio e static) — garante
    # restore 100% fiel num servidor novo, sem perda de dados.
    # =================================================================
    files_result: Optional[Dict[str, Any]] = None
    try:
        tar_bytes = await loop.run_in_executor(None, _build_files_tarball, True)
        if tar_bytes:
            tar_name = file_name.replace(".json", ".files.tar.gz")
            tar_size = len(tar_bytes)
            tar_media = MediaIoBaseUpload(
                io.BytesIO(tar_bytes),
                mimetype="application/gzip", resumable=False,
            )
            tar_meta = {
                "name": tar_name,
                "parents": [root["id"]],
                "description": f"Files tarball para {file_name}",
            }
            tar_remote = await loop.run_in_executor(None,
                lambda: service.files().create(body=tar_meta, media_body=tar_media,
                                                  fields="id, webViewLink, size").execute()
            )
            files_result = {
                "file_id": tar_remote["id"],
                "name": tar_name,
                "size_bytes": tar_size,
                "webViewLink": tar_remote.get("webViewLink"),
            }
            logger.info("[drive] tarball uploaded %s (%d bytes)", tar_name, tar_size)
    except Exception as e:
        logger.warning("[drive] tarball upload failed (não bloqueia backup principal): %s", e)
        files_result = {"error": str(e)[:200]}

    file_id = result.get("id")
    url = result.get("webViewLink")

    record = {
        "id": f"bkp-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "file_id": file_id,
        "file_name": file_name,
        "file_url": url,
        "size_bytes": size,
        "include_secrets": include_secrets,
        "triggered_by": triggered_by,
        "collections": [c[0] for c in BACKUP_COLLECTIONS],
        "files_tarball": files_result,
        "status": "ok",
        "started_at": started.isoformat(),
        "finished_at": now_iso(),
        "elapsed_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    }
    await db.drive_backups.insert_one(dict(record))

    # Limita histórico — manter apenas últimos 30 dias no Drive
    await _prune_old_files(cid, service, root["id"], keep_days=30)

    return {
        "ok": True,
        "file_id": file_id,
        "file_name": file_name,
        "file_url": url,
        "size_bytes": size,
        "elapsed_ms": record["elapsed_ms"],
        "files_tarball": files_result,
    }


async def _log_backup(cid: str, status: str, name: str, size: int,
                       triggered_by: str, error: Optional[str] = None) -> None:
    try:
        await db.drive_backups.insert_one({
            "id": f"bkp-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "file_name": name,
            "size_bytes": size,
            "triggered_by": triggered_by,
            "status": status,
            "error": error,
            "started_at": now_iso(),
            "finished_at": now_iso(),
        })
    except Exception:
        pass


# ============================================================
# Generic file upload (Rede IA PDFs, fotos, relatórios)
# ============================================================
async def upload_file_to_drive(
    company_id: str,
    content: bytes,
    file_name: str,
    mime_type: str = "application/pdf",
    subfolder: str = "Rede-IA",
    description: str = "",
) -> Dict[str, Any]:
    """Upload arbitrário ao Drive em subpasta da PontoIA-Backups.

    Usado por:
      - Rede IA: PDF de CTOs aprovadas
      - Outros relatórios

    Retorna {file_id, file_url, size_bytes}. Levanta RuntimeError se Drive
    não estiver conectado.
    """
    cid = company_id or DEMO_COMPANY_ID
    creds = await _get_credentials(cid)
    if not creds:
        raise RuntimeError("Google Drive não conectado para essa empresa.")

    import asyncio
    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service, creds)

    root = await _ensure_root_folder(cid, service)

    # Garante subpasta dentro de PontoIA-Backups
    subfolder_id = await loop.run_in_executor(None,
        lambda: _ensure_subfolder(service, root["id"], subfolder))

    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
    metadata = {
        "name": file_name,
        "parents": [subfolder_id],
        "description": description or f"Rede IA - {file_name}",
    }
    result = await loop.run_in_executor(None,
        lambda: service.files().create(body=metadata, media_body=media,
                                          fields="id, webViewLink, size").execute())
    return {
        "file_id": result.get("id"),
        "file_url": result.get("webViewLink"),
        "size_bytes": len(content),
        "subfolder": subfolder,
    }


def _ensure_subfolder(service, parent_id: str, name: str) -> str:
    """Cria (ou reusa) subpasta dentro da pasta-raiz do Drive."""
    q = (f"'{parent_id}' in parents and trashed=false "
         f"and mimeType='application/vnd.google-apps.folder' and name='{name}'")
    try:
        existing = service.files().list(q=q, fields="files(id,name)").execute()
        files = existing.get("files", [])
        if files:
            return files[0]["id"]
    except HttpError:
        pass
    folder = service.files().create(body={
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }, fields="id").execute()
    return folder["id"]


async def _prune_old_files(cid: str, service, folder_id: str, keep_days: int = 30) -> None:
    """Apaga backups > keep_days dias no Drive. Mantém últimos 7 sempre."""
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        q = f"'{folder_id}' in parents and trashed=false and mimeType='application/json'"
        result = await loop.run_in_executor(None,
            lambda: service.files().list(q=q, orderBy="createdTime desc",
                                            fields="files(id,name,createdTime)").execute()
        )
        files = result.get("files", [])
        # Manter os 7 mais novos sempre
        to_check = files[7:]
        cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86400
        for f in to_check:
            try:
                created = datetime.fromisoformat(f["createdTime"].replace("Z", "+00:00")).timestamp()
                if created < cutoff:
                    await loop.run_in_executor(None,
                        lambda fid=f["id"]: service.files().delete(fileId=fid).execute()
                    )
            except Exception:
                pass
    except Exception as e:
        logger.info("[drive] prune skip: %s", e)


# ============================================================
# Restore
# ============================================================
async def list_backups(company_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Histórico de backups da empresa (do banco)."""
    cur = db.drive_backups.find(
        {"company_id": company_id},
        {"_id": 0},
    ).sort("started_at", -1).limit(limit)
    return await cur.to_list(limit)


async def list_remote_files(company_id: str) -> List[Dict[str, Any]]:
    """Lista direto do Drive (caso queira restaurar arquivo que NÃO está mais no banco)."""
    creds = await _get_credentials(company_id)
    if not creds:
        raise RuntimeError("Google Drive não conectado.")
    import asyncio
    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service, creds)
    root = await _ensure_root_folder(company_id, service)
    q = f"'{root['id']}' in parents and trashed=false and mimeType='application/json'"
    result = await loop.run_in_executor(None,
        lambda: service.files().list(q=q, orderBy="createdTime desc",
                                        fields="files(id,name,createdTime,size,webViewLink)").execute()
    )
    return result.get("files", [])


async def download_backup(company_id: str, file_id: str) -> bytes:
    creds = await _get_credentials(company_id)
    if not creds:
        raise RuntimeError("Google Drive não conectado.")
    import asyncio
    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service, creds)

    def _do_download() -> bytes:
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    return await loop.run_in_executor(None, _do_download)


async def restore_backup(company_id: str, file_id: str,
                           collections: Optional[List[str]] = None,
                           mode: str = "merge",
                           tarball_file_id: Optional[str] = None) -> Dict[str, Any]:
    """Restaura snapshot do Drive a partir do file_id (download remoto).

    Se tarball_file_id for fornecido, também baixa+extrai os arquivos físicos
    (fotos onboarding, holerites, etc).
    """
    raw = await download_backup(company_id, file_id)
    result = await restore_backup_from_bytes(company_id, raw, collections, mode,
                                                source=f"drive:{file_id}")
    # Restaura também os arquivos físicos
    if tarball_file_id:
        try:
            tar_raw = await download_backup(company_id, tarball_file_id)
            files_res = await _extract_files_tarball(tar_raw)
            result["files_extracted"] = files_res
        except Exception as e:
            logger.warning("[drive] tarball restore failed: %s", e)
            result["files_extracted"] = {"error": str(e)[:200]}
    return result


async def restore_backup_from_bytes(company_id: str, raw: bytes,
                                       collections: Optional[List[str]] = None,
                                       mode: str = "merge",
                                       source: str = "upload") -> Dict[str, Any]:
    """Restaura snapshot a partir de bytes (upload do navegador OU download Drive).

    Mesma lógica de restore_backup mas sem dependência de Drive — útil para
    bootstrap de servidor novo onde o usuário tem o arquivo JSON em disco
    e ainda não conectou o Drive da nova instância.
    """
    try:
        snapshot = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(f"Arquivo de backup inválido (não é JSON): {e}")
    meta = snapshot.pop("_meta", {})

    if meta.get("company_id") and meta.get("company_id") != company_id:
        # Backup veio de outra empresa — só permite com flag explícita
        raise RuntimeError(
            f"Backup pertence a outra empresa ({meta.get('company_id')}). "
            "Não posso restaurar entre empresas diferentes."
        )

    collection_filter = set(collections) if collections else None
    restored: Dict[str, int] = {}
    skipped: List[str] = []
    secrets_redacted = bool(meta.get("include_secrets") is False)

    for coll_name, docs in snapshot.items():
        if collection_filter and coll_name not in collection_filter:
            skipped.append(coll_name)
            continue
        if not isinstance(docs, list) or not docs:
            continue
        # === wa_auth_state: chave composta session_id + key ===
        if coll_name == "wa_auth_state":
            inserted = 0
            if mode == "replace":
                wa_session = os.environ.get("WA_SESSION_ID", "isabella")
                await db.wa_auth_state.delete_many(
                    {"session_id": {"$in": [wa_session, company_id]}}
                )
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                sid = doc.get("session_id")
                key = doc.get("key")
                if not (sid and key):
                    continue
                await db.wa_auth_state.replace_one(
                    {"session_id": sid, "key": key}, doc, upsert=True,
                )
                inserted += 1
            restored[coll_name] = inserted
            continue
        # Modo replace: limpa antes
        if mode == "replace":
            await db[coll_name].delete_many({"company_id": company_id})
        # Upsert por id (se houver) ou bulk insert
        inserted = 0
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            # Não restaura campos REDACTED — preserva o atual no banco
            if secrets_redacted:
                doc = {k: v for k, v in doc.items()
                         if not (isinstance(v, str) and v.startswith("***REDACTED***"))}
            doc["company_id"] = company_id
            doc_id = doc.get("id")
            if doc_id:
                await db[coll_name].replace_one(
                    {"company_id": company_id, "id": doc_id}, doc, upsert=True
                )
            else:
                await db[coll_name].insert_one(doc)
            inserted += 1
        restored[coll_name] = inserted

    await db.drive_restore_log.insert_one({
        "id": f"rst-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "source": source,
        "mode": mode,
        "collections_restored": list(restored.keys()),
        "total_docs": sum(restored.values()),
        "secrets_redacted_in_source": secrets_redacted,
        "created_at": now_iso(),
    })
    return {"ok": True, "restored": restored, "skipped": skipped,
            "secrets_redacted_in_source": secrets_redacted,
            "source_meta": meta}


# ============================================================
# Daily scheduler
# ============================================================
async def daily_backup_worker() -> None:
    """Worker async: roda diariamente entre 03:00-03:05 BRT (06:00-06:05 UTC).

    Para cada empresa com Drive conectado e backup habilitado, executa o backup.
    """
    import asyncio
    logger.info("[drive-scheduler] worker iniciado")
    last_run_date: Optional[str] = None
    while True:
        try:
            now = datetime.now(timezone.utc)
            # 06:00 UTC = 03:00 BRT
            if now.hour == 6 and now.minute < 5:
                today = now.strftime("%Y-%m-%d")
                if today != last_run_date:
                    await _run_all_companies()
                    last_run_date = today
        except Exception as e:
            logger.exception("[drive-scheduler] tick fail: %s", e)
        await asyncio.sleep(120)


async def _run_all_companies() -> None:
    cur = db.drive_credentials.find({}, {"_id": 0, "company_id": 1})
    async for doc in cur:
        cid = doc.get("company_id")
        if not cid:
            continue
        try:
            await run_backup(cid, include_secrets=False, triggered_by="scheduled")
            logger.info("[drive-scheduler] backup OK company=%s", cid)
        except Exception as e:
            logger.warning("[drive-scheduler] backup FAIL company=%s: %s", cid, e)
