/**
 * MultiTenantPanel.jsx — FASE 8 Multi-tenant Audit
 */
import React, { useEffect, useState } from "react";
import { client } from "@/api";

const STATUS_COLOR = {
  BLINDADO: "#10b981", CLEAN: "#10b981",
  ATENCAO: "#fbbf24", WARNING: "#fbbf24",
  CRITICO: "#ef4444", CRITICAL: "#ef4444", VAZAMENTO: "#ef4444",
};

function Card({ children, color, title, big, testid }) {
  return (
    <div data-testid={testid} style={{
      background: "#0f172a", border: `1px solid ${color || "#1e293b"}55`,
      borderRadius: 12, padding: 16, minWidth: 200, flex: 1,
    }}>
      <div style={{ fontSize: 11, color: "#94a3b8", fontWeight: 700,
                    textTransform: "uppercase", letterSpacing: 1.2 }}>
        {title}
      </div>
      <div style={{ fontSize: big ? 32 : 22, fontWeight: 800,
                    color: color || "#f1f5f9", marginTop: 6 }}>
        {children}
      </div>
    </div>
  );
}

export default function MultiTenantPanel() {
  const [data, setData] = useState(null);

  useEffect(() => {
    client.get("/ai-center/multitenant/audit")
      .then((r) => setData(r.data));
  }, []);

  if (!data) return <div style={{ color: "#94a3b8" }}>Carregando auditoria…</div>;

  const oStatus = data.orphans.summary.status;
  const lStatus = data.leak_risk.status;

  return (
    <div data-testid="multitenant-panel">
      <h2 style={{ color: "#f1f5f9", marginTop: 0, fontSize: 22 }}>
        Multi-Tenant · Blindagem
      </h2>

      <div style={{ background: "linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%)",
                    border: "1px solid #3b82f666",
                    borderRadius: 12, padding: 18, marginBottom: 18 }}>
        <div style={{ fontSize: 11, color: "#93c5fd",
                      textTransform: "uppercase", letterSpacing: 1.5,
                      fontWeight: 700 }}>
          Auditoria executiva
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, color: "#f1f5f9",
                      marginTop: 6 }}>
          {data.headline}
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 18,
                    flexWrap: "wrap" }}>
        <Card title="Status órfãos" color={STATUS_COLOR[oStatus]}
              testid="orphan-status" big>{oStatus}</Card>
        <Card title="Status leak" color={STATUS_COLOR[lStatus]}
              testid="leak-status" big>{lStatus}</Card>
        <Card title="Total docs" testid="total-docs">
          {data.orphans.summary.total_docs.toLocaleString()}
        </Card>
        <Card title="Órfãos" color={data.orphans.summary.total_orphans > 0
                                       ? "#ef4444" : "#10b981"}
              testid="total-orphans">
          {data.orphans.summary.total_orphans}
        </Card>
        <Card title="Refs cruzadas" color={data.leak_risk.cross_tenant_refs > 0
                                              ? "#ef4444" : "#10b981"}
              testid="cross-refs">
          {data.leak_risk.cross_tenant_refs}
        </Card>
      </div>

      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "0 0 10px 0" }}>
        Detalhe por coleção
      </h3>
      <table style={{ width: "100%", color: "#cbd5e1", fontSize: 13,
                      borderCollapse: "collapse",
                      background: "#0f172a", borderRadius: 8 }}>
        <thead>
          <tr style={{ color: "#64748b", textAlign: "left",
                       background: "#1e293b" }}>
            <th style={{ padding: 8 }}>Coleção</th>
            <th style={{ padding: 8, textAlign: "right" }}>Total</th>
            <th style={{ padding: 8, textAlign: "right" }}>Órfãos</th>
            <th style={{ padding: 8, textAlign: "right" }}>%</th>
            <th style={{ padding: 8 }}>Status</th>
          </tr>
        </thead>
        <tbody>
          {data.orphans.details.map((d) => (
            <tr key={d.collection}>
              <td style={{ padding: 8, fontFamily: "monospace",
                           borderBottom: "1px solid #1e293b" }}>
                {d.collection}
              </td>
              <td style={{ padding: 8, textAlign: "right",
                           borderBottom: "1px solid #1e293b" }}>{d.total}</td>
              <td style={{ padding: 8, textAlign: "right",
                           borderBottom: "1px solid #1e293b",
                           color: d.orphan > 0 ? "#ef4444" : "#10b981",
                           fontWeight: 700 }}>{d.orphan}</td>
              <td style={{ padding: 8, textAlign: "right",
                           borderBottom: "1px solid #1e293b" }}>
                {d.orphan_pct}%
              </td>
              <td style={{ padding: 8,
                           borderBottom: "1px solid #1e293b",
                           color: STATUS_COLOR[d.status],
                           fontWeight: 700 }}>{d.status}</td>
            </tr>
          ))}
          {data.orphans.details.length === 0 && (
            <tr><td colSpan={5}
                style={{ padding: 14, color: "#10b981",
                         textAlign: "center" }}>
              ✓ Zero órfãos em todas as coleções de negócio
            </td></tr>
          )}
        </tbody>
      </table>

      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "18px 0 10px 0" }}>
        Distribuição por Tenant (top 20)
      </h3>
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                    gap: 8 }}>
        {data.tenants.items.map((t) => (
          <div key={t.company_id}
               style={{ background: "#0f172a", border: "1px solid #1e293b",
                        borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 10, color: "#64748b",
                          fontFamily: "monospace" }}>
              {(t.company_id || "").substring(0, 24)}
            </div>
            <div style={{ fontSize: 18, fontWeight: 700,
                          color: "#7dd3fc" }}>
              {t.subscribers.toLocaleString()}
            </div>
            <div style={{ fontSize: 10, color: "#94a3b8" }}>subs</div>
          </div>
        ))}
      </div>
    </div>
  );
}
