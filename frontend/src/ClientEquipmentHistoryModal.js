/**
 * Modal de Histórico de Equipamento por Cliente — iter163.
 *
 * Exibe a linha do tempo de:
 *   - Instalação de ONT (quem instalou, MAC/SN, data, ticket)
 *   - Retirada (quem retirou, motivo, defeito)
 *   - Vínculo de porta CTO, troca de porta, liberação
 *
 * Aceita `client.client_id` (ID do assinante) ou `client.client_name`
 * — o backend resolve o que tiver disponível.
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

const ACTION_META = {
  install: { label: "Instalação", icon: "⬇️", color: "#16a34a" },
  withdraw: { label: "Retirada", icon: "⬆️", color: "#dc2626" },
  port_link: { label: "Vínculo Porta CTO", icon: "🔌", color: "#0284c7" },
  port_swap: { label: "Troca de Porta", icon: "🔁", color: "#d97706" },
  port_release: { label: "Liberação Porta", icon: "🔓", color: "#64748b" },
};

function fmtDateTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      dateStyle: "short", timeStyle: "short",
    });
  } catch { return iso; }
}

export function ClientEquipmentHistoryModal({ client, onClose }) {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState({});
  const [resolvedClientId, setResolvedClientId] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true); setErr(""); setEvents([]); setSummary({});
    (async () => {
      try {
        let r;
        if (client?.client_id) {
          r = await api.stokClienteHistory(client.client_id);
        } else if (client?.client_name) {
          r = await api.stokClienteHistoryByName(client.client_name);
        } else {
          throw new Error("client_id ou client_name é obrigatório");
        }
        if (!alive) return;
        setEvents(r.events || []);
        setSummary(r.summary || {});
        setResolvedClientId(r.client_id || null);
      } catch (e) {
        if (alive) setErr(e?.response?.data?.detail || e.message);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [client]);

  const installEv = summary.install;
  const portEv = summary.port;
  const withdrawEv = summary.withdraw;

  return (
    <div data-testid="client-history-modal"
         style={{
           position: "fixed", inset: 0, background: "rgba(15,23,42,0.6)",
           display: "flex", alignItems: "center", justifyContent: "center",
           zIndex: 1000, padding: 16,
         }}
         onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: "var(--bg-surface)", borderRadius: 12,
             width: "min(720px, 100%)", maxHeight: "90vh", overflow: "auto",
             border: "1px solid var(--border-default)",
             boxShadow: "0 20px 50px rgba(0,0,0,0.3)",
           }}>
        {/* Header */}
        <div style={{
          padding: "16px 20px", borderBottom: "1px solid var(--border-default)",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontSize: 11, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
              Histórico de Equipamento
            </div>
            <div style={{ fontSize: 17, fontWeight: 700, marginTop: 2 }}>
              {client?.client_name || "—"}
            </div>
          </div>
          <button onClick={onClose}
                  data-testid="client-history-close"
                  className="btn btn-secondary btn-sm">Fechar</button>
        </div>

        {/* Resumo */}
        {!loading && !err && (
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 10, padding: 16,
            borderBottom: "1px solid var(--border-default)",
          }}>
            <SummaryCard label="Instalado por" value={installEv?.actor_name}
                         hint={installEv?.captured_at ? fmtDateTime(installEv.captured_at) : null}
                         color="#16a34a" />
            <SummaryCard label="Porta CTO atual"
                         value={portEv?.cto_name ? `${portEv.cto_name} · porta ${portEv.cto_port_number}` : null}
                         hint={portEv?.captured_at ? `desde ${fmtDateTime(portEv.captured_at)}` : null}
                         color="#0284c7" />
            <SummaryCard label="Última retirada" value={withdrawEv?.actor_name}
                         hint={withdrawEv?.captured_at ? fmtDateTime(withdrawEv.captured_at) : null}
                         color="#dc2626" />
          </div>
        )}

        {/* Conteúdo */}
        <div style={{ padding: 16 }}>
          {loading && <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)" }}>Carregando histórico…</div>}
          {err && <div style={{ padding: 12, color: "#dc2626" }}>Erro: {err}</div>}
          {!loading && !err && events.length === 0 && (
            <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)" }}>
              Nenhum evento registrado para este cliente ainda.
              {!resolvedClientId && (
                <div style={{ fontSize: 11, marginTop: 8, color: "var(--text-muted)" }}>
                  (Cliente sem subscriber_id resolvido — o histórico começa a ser gravado
                  a partir da próxima OS finalizada.)
                </div>
              )}
            </div>
          )}
          {!loading && !err && events.length > 0 && (
            <Timeline events={events} />
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ label, value, hint, color }) {
  return (
    <div style={{
      background: "var(--bg-surface-2)",
      border: "1px solid var(--border-default)",
      borderLeft: `3px solid ${color}`,
      borderRadius: 8, padding: "10px 12px",
    }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
                     textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, marginTop: 4 }}>
        {value || "—"}
      </div>
      {hint && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

function Timeline({ events }) {
  return (
    <div style={{ position: "relative", paddingLeft: 24 }}>
      {/* linha vertical */}
      <div style={{
        position: "absolute", left: 8, top: 8, bottom: 8,
        width: 2, background: "var(--border-default)",
      }} />
      {events.map((ev) => {
        const meta = ACTION_META[ev.action] || { label: ev.action, icon: "•", color: "#64748b" };
        return (
          <div key={ev.id}
               data-testid={`history-event-${ev.action}`}
               style={{ position: "relative", marginBottom: 16 }}>
            <div style={{
              position: "absolute", left: -23, top: 0,
              width: 18, height: 18, borderRadius: "50%",
              background: meta.color, color: "#fff",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 10, fontWeight: 700,
              border: "2px solid var(--bg-surface)",
            }}>{meta.icon}</div>
            <div style={{
              background: "var(--bg-surface-2)",
              border: "1px solid var(--border-default)",
              borderRadius: 8, padding: 12,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between",
                              alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: meta.color }}>
                  {meta.label}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                  {fmtDateTime(ev.captured_at)}
                </div>
              </div>
              <div style={{ marginTop: 6, fontSize: 12, color: "var(--text-primary)" }}>
                {ev.actor_name && (
                  <div><strong>Quem:</strong> {ev.actor_name}{ev.actor_email ? ` · ${ev.actor_email}` : ""}</div>
                )}
                {(ev.ont_mac || ev.ont_sn) && (
                  <div className="mono" data-mono style={{ fontSize: 11 }}>
                    {ev.ont_sn && <><strong>SN:</strong> {ev.ont_sn} · </>}
                    {ev.ont_mac && <><strong>MAC:</strong> {ev.ont_mac}</>}
                  </div>
                )}
                {ev.cto_name && (
                  <div>
                    <strong>CTO:</strong> {ev.cto_name}
                    {ev.cto_port_number != null && <> · porta {ev.cto_port_number}</>}
                    {ev.prev_cto_port_number != null && (
                      <> (anterior: porta {ev.prev_cto_port_number})</>
                    )}
                  </div>
                )}
                {ev.ticket_id && (
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    Ticket: {ev.ticket_id}
                  </div>
                )}
                {ev.notes && (
                  <div style={{ fontSize: 11, color: "var(--text-muted)",
                                  fontStyle: "italic", marginTop: 4 }}>
                    {ev.notes}
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default ClientEquipmentHistoryModal;
