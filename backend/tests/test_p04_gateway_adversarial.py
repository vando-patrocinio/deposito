"""test_p04_gateway_adversarial.py — Sprint P0.4.

Testes ADVERSARIAIS PERMANENTES contra futuros bypasses do gateway WhatsApp.

Falha automaticamente se:
  1. _GATEWAY_PATHS perder cobertura de qualquer path conhecido
  2. Alguém adicionar um novo path /send-* sem incluir em _GATEWAY_PATHS
  3. Qualquer endpoint REST do whatsapp_baileys voltar a usar httpx direto
     para SIDECAR_BASE em rotas de envio
"""
from __future__ import annotations
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_gateway_paths_contem_envios_essenciais():
    src = (REPO / "services/wa/sidecar.py").read_text()
    m = re.search(r"_GATEWAY_PATHS\s*=\s*\{([^}]+)\}", src)
    assert m, "_GATEWAY_PATHS não encontrado em sidecar.py"
    paths = {p.strip().strip('"').strip("'") for p in m.group(1).split(",") if p.strip()}
    obrigatorios = {"/send", "/send-document", "/send-audio",
                    "/send-image", "/send-bulk"}
    faltando = obrigatorios - paths
    assert not faltando, f"Paths obrigatórios ausentes do gateway: {faltando}"


def test_whatsapp_baileys_nao_usa_httpx_direto_para_send():
    """Endpoints de envio em routes/whatsapp_baileys.py NÃO podem mais usar
    `httpx.AsyncClient().post(SIDECAR_BASE + "/send-...", ...)` direto.

    Detecta tentativas de bypass: chamadas httpx que apontam para
    {SIDECAR_BASE}/send-... e não passam por _sidecar_post_*.
    """
    src = (REPO / "routes/whatsapp_baileys.py").read_text()
    pattern = re.compile(
        r'cli\.post\(\s*f["\']\{SIDECAR_BASE\}/send-[a-z]+["\']',
        re.IGNORECASE)
    matches = pattern.findall(src)
    assert not matches, (
        f"BYPASS DETECTADO em whatsapp_baileys.py — uso direto de httpx "
        f"para envio: {matches}. Use _sidecar_post_silent."
    )


def test_novo_send_path_obriga_inclusao_no_gateway():
    """Se aparecer uso de path '/send-X' em qualquer route/service, ele
    DEVE estar em _GATEWAY_PATHS (ou ser desconhecido — abrir issue).
    """
    sidecar = (REPO / "services/wa/sidecar.py").read_text()
    m = re.search(r"_GATEWAY_PATHS\s*=\s*\{([^}]+)\}", sidecar)
    gateway_paths = {p.strip().strip('"').strip("'") for p in m.group(1).split(",") if p.strip()}

    # Busca por todos os strings literais "/send-<algo>" em backend/
    found_paths = set()
    for fp in (REPO / "routes").rglob("*.py"):
        for line in fp.read_text(errors="ignore").splitlines():
            for hit in re.findall(r'["\'](/send-[a-z]+)["\']', line):
                found_paths.add(hit)
    for fp in (REPO / "services").rglob("*.py"):
        for line in fp.read_text(errors="ignore").splitlines():
            for hit in re.findall(r'["\'](/send-[a-z]+)["\']', line):
                found_paths.add(hit)

    # Tudo que aparecer no código DEVE estar coberto pelo gateway
    descoberto = found_paths - gateway_paths
    # Exceções legítimas (rotas REST com prefixo /send-*, não chamadas ao sidecar):
    # nenhuma esperada; se houver, registrar em ALLOWLIST.
    ALLOWLIST = {"/send-single"}  # endpoint REST público de disparo_boleto
                                   # que internamente usa _sidecar_post_at("/send", ...)
    sobra = descoberto - ALLOWLIST
    assert not sobra, (
        f"Paths /send-* novos sem cobertura do gateway: {sobra}. "
        f"Adicione em services/wa/sidecar.py::_GATEWAY_PATHS ou ALLOWLIST."
    )


def test_autonomy_scheduler_tem_job_defaults_hardening():
    """services/autonomy_scheduler.py deve ter os mesmos job_defaults que
    o scheduler principal (P0.4 A4)."""
    src = (REPO / "services/autonomy_scheduler.py").read_text()
    assert "misfire_grace_time" in src, "autonomy_scheduler sem misfire_grace_time"
    assert "coalesce" in src, "autonomy_scheduler sem coalesce"


def test_server_scheduler_tem_job_defaults_hardening():
    """server.py deve manter job_defaults (P0.2)."""
    src = (REPO / "server.py").read_text()
    # Procurar bloco job_defaults perto de AsyncIOScheduler
    assert re.search(
        r"AsyncIOScheduler\(.*job_defaults\s*=\s*\{",
        src, re.DOTALL
    ), "scheduler principal sem job_defaults"
    assert "misfire_grace_time" in src
    assert "coalesce" in src
