import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { PhoneCall, X, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";

/**
 * Botão reutilizável para originar chamada outbound com IA via MagnusBilling.
 *
 * Uso:
 *   <OutboundCallButton phone="11999998888" contactName="João" contactId="..." />
 *
 * Abre um popover com seleção de agente IA + observações, e dispara
 * POST /api/aihub/calls/outbound. Mostra status inline.
 */
export default function OutboundCallButton({
  phone, contactName, contactId, label = "Ligar com IA",
  variant = "primary", size = "sm", disabled = false,
}) {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState([]);
  const [agentId, setAgentId] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (!open || agents.length) return;
    api.aihubAgentsList().then((r) => {
      const active = (r.items || []).filter((a) => a.active);
      setAgents(active);
      if (active.length) setAgentId(active[0].id);
    });
  }, [open, agents.length]);

  const fire = async () => {
    if (!agentId || !phone) return;
    setBusy(true); setResult(null);
    try {
      const r = await api.aihubOutboundCall({
        agent_id: agentId,
        phone: String(phone),
        contact_name: contactName || undefined,
        contact_id: contactId || undefined,
        notes: notes.trim() || undefined,
      });
      setResult({ ok: true, msg: `Discando para ${r.phone} via ${r.agent_name}` });
    } catch (e) {
      setResult({
        ok: false,
        msg: e?.response?.data?.detail || e.message || "Falha ao iniciar chamada",
      });
    } finally { setBusy(false); }
  };

  if (!phone) return null;

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        onClick={() => setOpen(!open)}
        disabled={disabled}
        data-testid="outbound-call-trigger"
        className={`btn btn-${variant} btn-${size}`}
        style={{ gap: 6 }}
        title={`Ligar para ${phone} com agente IA`}
      >
        <PhoneCall size={size === "sm" ? 13 : 15} />
        {label}
      </button>

      {open && (
        <>
          <div onClick={() => setOpen(false)}
               style={{
                 position: "fixed", inset: 0, zIndex: 95, background: "transparent",
               }} />
          <div data-testid="outbound-call-popover"
               style={{
                 position: "absolute", top: "calc(100% + 6px)", right: 0,
                 minWidth: 320, zIndex: 100, padding: 14,
                 background: "var(--bg-surface)", border: "1px solid var(--border-default)",
                 borderRadius: 12, boxShadow: "var(--shadow-lg)",
               }}>
            <div style={{
              display: "flex", justifyContent: "space-between",
              alignItems: "center", marginBottom: 10,
            }}>
              <strong style={{ fontSize: 13 }}>
                <PhoneCall size={13} style={{ verticalAlign: -2, marginRight: 6 }} />
                Chamada outbound IA
              </strong>
              <button onClick={() => setOpen(false)} className="btn btn-ghost btn-sm">
                <X size={12} />
              </button>
            </div>

            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>
              Para: <strong>{phone}</strong>
              {contactName && <> · {contactName}</>}
            </div>

            {agents.length === 0 ? (
              <div style={{
                padding: 10, background: "var(--warning-soft)",
                color: "var(--warning-soft-fg)", borderRadius: 8,
                fontSize: 12, textAlign: "center",
              }}>
                Nenhum agente IA ativo. Crie um em “Atendimento IA”.
              </div>
            ) : (
              <>
                <FieldLabel>Agente IA</FieldLabel>
                <select className="input" value={agentId}
                        onChange={(e) => setAgentId(e.target.value)}
                        data-testid="outbound-agent-select"
                        style={{ width: "100%", marginBottom: 8 }}>
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>

                <FieldLabel>Observações (opcional)</FieldLabel>
                <input className="input" value={notes}
                       onChange={(e) => setNotes(e.target.value)}
                       placeholder="Ex.: cobrança fatura 03/2026"
                       data-testid="outbound-notes-input"
                       style={{ width: "100%", marginBottom: 10 }} />

                {result && (
                  <div style={{
                    marginBottom: 8, padding: 8,
                    background: result.ok ? "var(--success-soft)" : "var(--danger-soft)",
                    color: result.ok ? "var(--success-soft-fg)" : "var(--danger-soft-fg)",
                    borderRadius: 6, fontSize: 11,
                    display: "flex", alignItems: "center", gap: 6,
                  }}>
                    {result.ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
                    {result.msg}
                  </div>
                )}

                <button onClick={fire} disabled={busy || !agentId}
                        data-testid="outbound-call-confirm"
                        className="btn btn-primary"
                        style={{ width: "100%", gap: 6 }}>
                  {busy ? <Loader2 size={13} className="spin" /> : <PhoneCall size={13} />}
                  {busy ? "Iniciando…" : "Iniciar chamada"}
                </button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function FieldLabel({ children }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 700, color: "var(--text-secondary)",
      textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3,
    }}>{children}</div>
  );
}
