"""Atualiza NERVOUS_METADATA emits_events/event_types nos arquivos
modificados pelo plug_emit. Sincroniza metadata com a realidade do código.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path("/app/backend")
EMIT_RX = re.compile(r'await emit_event\(\s*"([a-z._]+)"', re.MULTILINE)

# Files modified by plug-and-emit
TARGETS = [
    "routes/atlaz_financeiro.py", "routes/billing.py",
    "routes/cto_ports_base.py", "routes/lousa.py",
    "routes/lousa_rompimento.py", "routes/payment_charges.py",
    "routes/referrals.py", "routes/smartolt_ai.py",
    "routes/smartolt_push_ctos.py", "routes/subscribers.py",
    "routes/whatsapp_baileys.py", "routes/whatsapp_twilio.py",
]

# Add other modified files automatically by scanning
for f in BACKEND.rglob("*.py"):
    if "__pycache__" in str(f):
        continue
    try:
        src = f.read_text()
    except Exception:
        continue
    if "NERVOUS_METADATA" not in src:
        continue
    if "from services.event_bus import emit_event" not in src:
        continue
    rel = str(f.relative_to(BACKEND))
    if rel not in TARGETS:
        TARGETS.append(rel)

updated = 0
for rel in TARGETS:
    p = BACKEND / rel
    if not p.exists():
        continue
    src = p.read_text()
    events = sorted(set(EMIT_RX.findall(src)))
    if not events:
        continue
    # Patch NERVOUS_METADATA block
    new_src = re.sub(
        r'(NERVOUS_METADATA\s*=\s*\{[^}]*?"emits_events":\s*)False',
        r"\1True", src, count=1)
    new_src = re.sub(
        r'(NERVOUS_METADATA\s*=\s*\{[^}]*?"event_types":\s*)\[\]',
        r'\1[' + ', '.join(f'"{e}"' for e in events) + ']',
        new_src, count=1)
    if new_src != src:
        p.write_text(new_src)
        updated += 1
        print(f"  ✅ {rel} → emits=True types={events}")
print(f"\nUpdated {updated} files")
