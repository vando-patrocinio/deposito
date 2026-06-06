/* ReconcileAuditPanel — Painel de conciliação CTO ↔ SmartOLT.

   Exibe a última auditoria noturna (3h15 da manhã) ou força refresh.
   - ORPHAN_ONUS: ONUs ativas no SmartOLT sem vínculo em CTO cadastrada.
   - GHOST_PORTS: Portas marcadas como "used" em CTO mas ONU sumiu da OLT.

   Useful pra achar técnicos que esquecem de cadastrar a CTO no app
   e clientes que foram migrados manualmente pelo SSH (fora do fluxo).
*/
import React, { useState, useEffect, useCallback } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import { toast } from "sonner";

export default function ReconcileAuditPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState("orphans");

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true); else setLoading(true);
    setErr("");
    try {
      const r = await api.redeIaAuditOrphans(refresh);
      setData(r);
      if (refresh) toast.success("Auditoria executada agora.");
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro");
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(false); }, [load]);

  const s = data?.summary || {};
  const orphans = data?.orphans || [];
  const ghosts = data?.ghosts || [];

  return (
    <div data-testid="reconcile-audit-panel" style={{ display: "flex",
            flexDirection: "column", gap: 14 }}>
      {/* Cabeçalho com botão refresh */}
      <Card style={{ padding: 16, display: "flex", alignItems: "center",
                      justifyContent: "space-between", gap: 12,
                      flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800,
                          color: "var(--text-primary)" }}>
            Conciliação CTO ↔ SmartOLT
          </div>
          <div style={{ fontSize: 12, color: "var(--text-muted)",
                          marginTop: 2 }}>
            Acha clientes na OLT sem vínculo em CTO (técnico esqueceu de cadastrar)
            e portas “ocupadas” sem ONU correspondente (clientes deletados/migrados).
            Job noturno: 03:15.
            {s.executed_at && (
              <> · Última execução: {new Date(s.executed_at).toLocaleString("pt-BR")}</>
            )}
          </div>
        </div>
        <button data-testid="reconcile-refresh-btn"
                onClick={() => load(true)} disabled={refreshing}
                style={{ padding: "10px 16px", borderRadius: 10, border: 0,
                          background: refreshing ? "#94a3b8"
                            : "linear-gradient(135deg,#0f766e,#0891b2)",
                          color: "#fff", fontSize: 13, fontWeight: 700,
                          cursor: refreshing ? "wait" : "pointer" }}>
          {refreshing ? "Executando…" : "↻ Executar agora"}
        </button>
      </Card>

      {/* KPIs */}
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                      gap: 12 }}>
        <KpiBox label="CTOs cadastradas" value={s.cto_count ?? "—"}
                 color="#6366f1" />
        <KpiBox label="Portas vinculadas" value={s.ports_used_total ?? "—"}
                 color="#0891b2" />
        <KpiBox label="ONUs ↔ CTO (OK)" value={s.onus_matched ?? "—"}
                 color="#16a34a" />
        <KpiBox label="ONUs sem CTO" value={s.orphan_count ?? "—"}
                 color={s.orphan_count > 0 ? "#ea580c" : "#64748b"}
                 testId="kpi-orphan" />
        <KpiBox label="Portas fantasmas" value={s.ghost_count ?? "—"}
                 color={s.ghost_count > 0 ? "#dc2626" : "#64748b"}
                 testId="kpi-ghost" />
      </div>

      {/* Tabs orphans/ghosts */}
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ display: "flex", borderBottom: "1px solid var(--border-default)" }}>
          {[
            { id: "orphans", label: `ONUs sem CTO (${orphans.length})` },
            { id: "ghosts",  label: `Portas fantasmas (${ghosts.length})` },
          ].map((t) => (
            <button key={t.id} data-testid={`reconcile-tab-${t.id}`}
                    onClick={() => setTab(t.id)}
                    style={{ flex: 1, padding: "12px 14px", border: 0,
                              background: "transparent", cursor: "pointer",
                              fontSize: 13,
                              fontWeight: tab === t.id ? 700 : 500,
                              color: tab === t.id ? "var(--text-primary)"
                                  : "var(--text-muted)",
                              borderBottom: "2px solid "
                                + (tab === t.id ? "var(--primary, #7c3aed)"
                                    : "transparent") }}>
              {t.label}
            </button>
          ))}
        </div>

        {loading && (
          <div style={{ padding: 28, textAlign: "center",
                          color: "var(--text-muted)" }}>Carregando…</div>
        )}
        {err && (
          <div style={{ padding: 14, background: "#fef2f2", color: "#991b1b",
                          fontSize: 12 }}>{err}</div>
        )}

        {!loading && tab === "orphans" && (
          <OrphanList items={orphans} />
        )}
        {!loading && tab === "ghosts" && (
          <GhostList items={ghosts} />
        )}
      </Card>
    </div>
  );
}

function KpiBox({ label, value, color, testId }) {
  return (
    <Card data-testid={testId} style={{ padding: 14 }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
                      textTransform: "uppercase", letterSpacing: 0.5,
                      fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800, color, marginTop: 4 }}>
        {value}
      </div>
    </Card>
  );
}

function OrphanList({ items }) {
  if (!items.length) {
    return (
      <div data-testid="orphans-empty"
            style={{ padding: 28, textAlign: "center",
                      color: "var(--text-muted)" }}>
        ✓ Todas as ONUs da OLT estão vinculadas a CTOs cadastradas.
      </div>
    );
  }
  return (
    <div data-testid="orphans-list" style={{ overflow: "auto", maxHeight: 480 }}>
      <div className="table-wrap" style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}><table style={{ width: "100%", minWidth: 640, borderCollapse: "collapse",
                        fontSize: 12 }}>
        <thead>
          <tr style={{ background: "var(--bg-surface-2)",
                        position: "sticky", top: 0 }}>
            <Th>Cliente</Th>
            <Th>PPPoE / Sub ID</Th>
            <Th>OLT · Board/Port</Th>
            <Th>Zone</Th>
            <Th>Sinal</Th>
            <Th>Status</Th>
          </tr>
        </thead>
        <tbody>
          {items.map((o, i) => (
            <tr key={i} data-testid={`orphan-row-${i}`}
                  style={{ borderBottom: "1px solid var(--border-default)" }}>
              <Td><strong>{o.name}</strong></Td>
              <Td>
                {o.pppoe_user && <div>{o.pppoe_user}</div>}
                {o.subscriber_id && (
                  <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
                    #{o.subscriber_id}
                  </div>
                )}
              </Td>
              <Td>
                {o.olt_name || "—"}
                {(o.board || o.port) && (
                  <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
                    B{o.board}/P{o.port}{o.onu != null ? `/${o.onu}` : ""}
                  </div>
                )}
              </Td>
              <Td style={{ fontSize: 11 }}>{o.zone_name || "—"}</Td>
              <Td>{o.signal_text || "—"}</Td>
              <Td>{o.status || "—"}</Td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}

function GhostList({ items }) {
  if (!items.length) {
    return (
      <div data-testid="ghosts-empty"
            style={{ padding: 28, textAlign: "center",
                      color: "var(--text-muted)" }}>
        ✓ Nenhuma porta marcada como ocupada sem ONU correspondente.
      </div>
    );
  }
  return (
    <div data-testid="ghosts-list" style={{ overflow: "auto", maxHeight: 480 }}>
      <div className="table-wrap" style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}><table style={{ width: "100%", minWidth: 640, borderCollapse: "collapse",
                        fontSize: 12 }}>
        <thead>
          <tr style={{ background: "var(--bg-surface-2)",
                        position: "sticky", top: 0 }}>
            <Th>CTO</Th>
            <Th>Porta</Th>
            <Th>Cliente registrado</Th>
            <Th>PPPoE</Th>
            <Th>Conectado em</Th>
          </tr>
        </thead>
        <tbody>
          {items.map((g, i) => (
            <tr key={i} data-testid={`ghost-row-${i}`}
                  style={{ borderBottom: "1px solid var(--border-default)" }}>
              <Td><strong>{g.cto_name}</strong></Td>
              <Td>{g.port_number}</Td>
              <Td>{g.client_name || "—"}</Td>
              <Td>{g.client_pppoe || "—"}</Td>
              <Td>{g.connected_at
                    ? new Date(g.connected_at).toLocaleDateString("pt-BR")
                    : "—"}</Td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}

const Th = ({ children, ...p }) => (
  <th style={{ textAlign: "left", padding: "10px 12px", fontWeight: 700,
                color: "var(--text-muted)", fontSize: 10,
                textTransform: "uppercase", letterSpacing: 0.5 }}
       {...p}>{children}</th>
);
const Td = ({ children, ...p }) => (
  <td style={{ padding: "10px 12px", color: "var(--text-primary)" }}
       {...p}>{children}</td>
);
