/**
 * ClientsSegmentPanel — Painéis segmentados de clientes (inspirado no Atlaz).
 *
 * Recebe `segment` como prop e renderiza a lista filtrada pelo endpoint
 * `/api/clients-segments/{segment}` com colunas relevantes:
 *  - radius_state (badge colorida)
 *  - active_session (IP, uptime, MAC)
 *  - max_overdue_days (badge vermelha se >0)
 *  - plano + valor + dia vencimento
 *
 * Cada segmento tem cor + ícone próprios. Pesquisa por nome/pppoe/telefone.
 */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";


const SEGMENT_META = {
  recent: { icon: "🆕", title: "Clientes Recentes",
              desc: "Cadastrados nos últimos 30 dias", color: "#0ea5e9" },
  overdue: { icon: "⏰", title: "Em Atraso",
              desc: "Clientes com fatura(s) em aberto vencida(s)",
              color: "#f59e0b" },
  blocked: { icon: "🔒", title: "Bloqueados",
              desc: "Clientes em REDUZIDO / WALL GARDEN / SUSPENSO",
              color: "#dc2626" },
  no_charges: { icon: "🕊️", title: "Sem cobranças futuras",
                  desc: "Sem fatura agendada para o futuro",
                  color: "#7c3aed" },
  connected: { icon: "🟢", title: "Conectados agora",
                desc: "Com sessão PPPoE ativa no momento",
                color: "#16a34a" },
  disconnected: { icon: "⚫", title: "Desconectados",
                    desc: "Contrato ativo mas sem sessão RADIUS",
                    color: "#64748b" },
  no_contract: { icon: "📭", title: "Sem contratos",
                   desc: "Assinantes sem contrato vinculado",
                   color: "#ec4899" },
  contracts: { icon: "📑", title: "Contratos ativos",
                 desc: "Lista de contratos vigentes", color: "#10b981" },
  contracts_disabled: { icon: "🗂️", title: "Contratos desativados",
                          desc: "Cancelados ou encerrados",
                          color: "#94a3b8" },
};


const STATE_COLOR = {
  ATIVO: { bg: "#dcfce7", fg: "#14532d" },
  GRACE: { bg: "#fef9c3", fg: "#854d0e" },
  REDUZIDO: { bg: "#fef3c7", fg: "#92400e" },
  WALLED_GARDEN: { bg: "#fee2e2", fg: "#991b1b" },
  SUSPENSO: { bg: "#fecaca", fg: "#7f1d1d" },
  CANCELADO: { bg: "#e2e8f0", fg: "#334155" },
  "—": { bg: "#f1f5f9", fg: "#94a3b8" },
};


function fmtBRL(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString("pt-BR",
    { style: "currency", currency: "BRL" });
}


function fmtUptime(secs) {
  if (!secs || secs < 0) return "—";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (h > 0) return `${h}h${String(m).padStart(2, "0")}`;
  return `${m}m`;
}


export default function ClientsSegmentPanel({ segment = "recent" }) {
  const meta = SEGMENT_META[segment] || SEGMENT_META.recent;
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.clientsSegment(segment, search);
      setItems(r.items || []);
      setCount(r.count || 0);
    } catch (e) {
      console.warn("[ClientsSegment]", e);
    }
    setLoading(false);
  }, [segment, search]);

  useEffect(() => { load(); }, [load]);

  // Para segmentos baseados em contratos, items tem schema diferente
  const isContractView = segment === "contracts"
    || segment === "contracts_disabled";

  return (
    <div data-testid={`clients-segment-${segment}`} style={{ padding: 18 }}>
      {/* Header */}
      <div style={{ display: "flex", gap: 14, marginBottom: 12,
                      alignItems: "center" }}>
        <div style={{
          width: 52, height: 52, borderRadius: 14,
          background: `${meta.color}15`,
          display: "grid", placeItems: "center", fontSize: 28,
        }}>{meta.icon}</div>
        <div style={{ flex: 1 }}>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800,
                          color: "#0f172a" }}>
            {meta.title}
          </h2>
          <p style={{ margin: 0, color: "#64748b", fontSize: 12 }}>
            {meta.desc}
          </p>
        </div>
        <div style={{
          padding: "8px 14px", borderRadius: 10,
          background: `${meta.color}15`, color: meta.color,
          fontWeight: 800, fontSize: 22, minWidth: 70, textAlign: "center",
        }}>
          {count}
        </div>
      </div>

      {/* Search */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input data-testid="segment-search" type="text"
                placeholder="Buscar por nome, PPPoE, telefone…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                  flex: 1, padding: "9px 14px", border: "1px solid #cbd5e1",
                  borderRadius: 8, fontSize: 13, outline: "none",
                  background: "#fff",
                }} />
        <button data-testid="segment-refresh" onClick={load}
                  style={{
                    padding: "8px 14px", borderRadius: 8,
                    background: "#f1f5f9", border: "1px solid #cbd5e1",
                    fontSize: 12, fontWeight: 700, cursor: "pointer",
                  }}>🔄</button>
      </div>

      {/* Lista */}
      {loading && (
        <div style={{ padding: 40, textAlign: "center",
                        color: "#64748b" }}>⏳ Carregando…</div>
      )}
      {!loading && items.length === 0 && (
        <div style={{ padding: 40, textAlign: "center", color: "#64748b",
                        background: "#f8fafc", borderRadius: 10 }}>
          🎉 Nenhum cliente nesta categoria.
        </div>
      )}

      {!loading && items.length > 0 && (
        isContractView
          ? <ContractListTable items={items} />
          : <SubscriberListTable items={items} segment={segment} />
      )}
    </div>
  );
}


function SubscriberListTable({ items, segment }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #e2e8f0",
                    borderRadius: 10, overflow: "hidden" }}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
          <thead style={{ background: "#f8fafc" }}>
            <tr>
              <Th>Nome</Th>
              <Th>PPPoE</Th>
              <Th>Estado RADIUS</Th>
              <Th>Plano · valor</Th>
              <Th>Telefone</Th>
              {segment === "overdue" && <Th>Atraso</Th>}
              {(segment === "connected" || segment === "disconnected") && (
                <Th>Sessão atual</Th>
              )}
            </tr>
          </thead>
          <tbody>
            {items.map((s) => {
              const sc = STATE_COLOR[s.radius_state] || STATE_COLOR["—"];
              return (
                <tr key={s.id} data-testid={`segment-row-${s.id}`}
                     style={{ borderTop: "1px solid #f1f5f9" }}>
                  <Td>
                    <div style={{ fontWeight: 700, color: "#0f172a" }}>
                      {s.name || "—"}
                    </div>
                    {s.document && (
                      <code style={{ fontSize: 10, color: "#94a3b8" }}>
                        {s.document}
                      </code>
                    )}
                  </Td>
                  <Td>
                    {s.pppoe_user ? (
                      <code style={{ background: "#f1f5f9",
                                      padding: "2px 7px", borderRadius: 4,
                                      fontSize: 11 }}>
                        {s.pppoe_user}
                      </code>
                    ) : <span style={{ color: "#cbd5e1" }}>—</span>}
                  </Td>
                  <Td>
                    <span style={{
                      padding: "2px 9px", borderRadius: 99,
                      background: sc.bg, color: sc.fg,
                      fontSize: 11, fontWeight: 700,
                    }}>{s.radius_state || "—"}</span>
                  </Td>
                  <Td>
                    {s.contract_plan_name ? (
                      <>
                        <div style={{ fontWeight: 700, color: "#0f172a",
                                        fontSize: 12 }}>
                          {s.contract_plan_name}
                        </div>
                        <div style={{ fontSize: 11, color: "#64748b" }}>
                          {fmtBRL(s.contract_monthly_value)} · dia
                          {" "}{s.contract_due_day || "—"}
                        </div>
                      </>
                    ) : <span style={{ color: "#cbd5e1" }}>sem contrato</span>}
                  </Td>
                  <Td>
                    {s.phone ? (
                      <a href={`tel:${s.phone}`}
                          style={{ color: "#0ea5e9" }}>{s.phone}</a>
                    ) : <span style={{ color: "#cbd5e1" }}>—</span>}
                  </Td>
                  {segment === "overdue" && (
                    <Td>
                      <span style={{
                        padding: "2px 9px", borderRadius: 99,
                        background: "#fee2e2", color: "#991b1b",
                        fontWeight: 800, fontSize: 11,
                      }}>{s.max_overdue_days}d</span>
                    </Td>
                  )}
                  {(segment === "connected"
                     || segment === "disconnected") && (
                    <Td>
                      {s.active_session ? (
                        <div style={{ fontSize: 11, lineHeight: 1.4 }}>
                          <div>📍 <b>{s.active_session.framed_ip || "—"}</b></div>
                          <div style={{ color: "#64748b" }}>
                            ⏱ {fmtUptime(s.active_session.session_time)}
                          </div>
                        </div>
                      ) : <span style={{ color: "#cbd5e1" }}>—</span>}
                    </Td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function ContractListTable({ items }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #e2e8f0",
                    borderRadius: 10, overflow: "hidden" }}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
          <thead style={{ background: "#f8fafc" }}>
            <tr>
              <Th>Cliente</Th>
              <Th>Nº contrato</Th>
              <Th>PPPoE</Th>
              <Th>Plano</Th>
              <Th>Valor · vence</Th>
              <Th>Estado</Th>
              <Th>Criado</Th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => {
              const sc = STATE_COLOR[c.radius_state] || STATE_COLOR["—"];
              return (
                <tr key={c.id} style={{ borderTop: "1px solid #f1f5f9" }}>
                  <Td><b>{c.subscriber_name}</b></Td>
                  <Td>
                    <code style={{ fontSize: 10, color: "#64748b",
                                    background: "#f1f5f9",
                                    padding: "1px 6px",
                                    borderRadius: 3 }}>
                      {c.contract_number}
                    </code>
                  </Td>
                  <Td>
                    {c.pppoe_user ? (
                      <code style={{ fontSize: 11 }}>{c.pppoe_user}</code>
                    ) : "—"}
                  </Td>
                  <Td>{c.plan_name}</Td>
                  <Td>
                    {fmtBRL(c.monthly_value)} · dia {c.due_day}
                  </Td>
                  <Td>
                    <span style={{
                      padding: "2px 9px", borderRadius: 99,
                      background: sc.bg, color: sc.fg,
                      fontSize: 11, fontWeight: 700,
                    }}>{c.radius_state}</span>
                  </Td>
                  <Td>
                    <span style={{ fontSize: 11, color: "#94a3b8" }}>
                      {c.created_at
                        ? new Date(c.created_at).toLocaleDateString("pt-BR")
                        : "—"}
                    </span>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function Th({ children }) {
  return (
    <th style={{
      padding: "10px 12px", textAlign: "left",
      fontSize: 11, fontWeight: 700, color: "#64748b",
      textTransform: "uppercase", letterSpacing: 0.4,
      borderBottom: "1px solid #e2e8f0",
    }}>{children}</th>
  );
}


function Td({ children }) {
  return (
    <td style={{ padding: "10px 12px", verticalAlign: "top" }}>
      {children}
    </td>
  );
}
