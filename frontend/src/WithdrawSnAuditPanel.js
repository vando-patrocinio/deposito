/* WithdrawSnAuditPanel — Auditoria de validações de SN da Retirada.

   iter161 — Mostra ao gestor o histórico de tentativas de validação
   de SN durante retiradas. Detecta técnicos com taxa alta de mismatch.

   Endpoint: GET /api/smartolt/withdraw-sn-audit?days=N&only_mismatch=bool
*/
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

const COLORS = {
  text: "#0f172a", muted: "#64748b", border: "#e2e8f0",
  match: "#16a34a", mismatch: "#dc2626", noMap: "#ca8a04",
};

const REASON_LABEL = {
  match: { txt: "✓ Match", c: COLORS.match, bg: "#dcfce7" },
  mismatch: { txt: "✕ Divergente", c: COLORS.mismatch, bg: "#fee2e2" },
  not_in_smartolt: { txt: "○ Sem mapping", c: COLORS.noMap, bg: "#fef3c7" },
};

const fmtTime = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("pt-BR",
    { day:"2-digit", month:"2-digit", year:"2-digit",
      hour:"2-digit", minute:"2-digit" }); }
  catch { return "—"; }
};

function Kpi({ label, value, color, icon }) {
  return (
    <div style={{
      flex: 1, minWidth: 130, padding: 14,
      background: "#fff", borderRadius: 10,
      border: `1px solid ${COLORS.border}`,
      display: "flex", alignItems: "center", gap: 10,
    }}>
      <div style={{
        width: 38, height: 38, borderRadius: 9,
        background: color + "22", color, fontSize: 17,
        display: "grid", placeItems: "center",
      }}>{icon}</div>
      <div>
        <div style={{ fontSize: 19, fontWeight: 800, color: COLORS.text,
                          fontVariantNumeric: "tabular-nums" }}>{value}</div>
        <div style={{ fontSize: 10, color: COLORS.muted, fontWeight: 700,
                          textTransform: "uppercase", letterSpacing: 0.5,
                          marginTop: 2 }}>{label}</div>
      </div>
    </div>
  );
}

export default function WithdrawSnAuditPanel() {
  const [days, setDays] = useState(30);
  const [onlyMismatch, setOnlyMismatch] = useState(false);
  const [data, setData] = useState({ items: [], by_technician: [],
                                            total: 0, total_match: 0,
                                            total_mismatch: 0,
                                            total_not_in_smartolt: 0 });
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api._client.get(`/smartolt/withdraw-sn-audit`,
        { params: { days, only_mismatch: onlyMismatch } });
      setData(r.data || {});
    } catch { /* */ }
    finally { setLoading(false); }
  }, [days, onlyMismatch]);

  useEffect(() => { reload(); }, [reload]);

  return (
    <div data-testid="withdraw-sn-audit-panel" style={{ display: "grid", gap: 14 }}>
      <div style={{
        background: "#fff", borderRadius: 14,
        border: `1px solid ${COLORS.border}`, padding: 16,
        display: "flex", justifyContent: "space-between",
        alignItems: "center", gap: 12, flexWrap: "wrap",
      }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800,
                            color: COLORS.text, letterSpacing: -0.2 }}>
            🔍 Auditoria · Validações SN da Retirada
          </h3>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: COLORS.muted }}>
            Histórico das tentativas de validar o SN escaneado contra o
            SmartOLT durante o fluxo de retirada.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select data-testid="audit-days" value={days}
                     onChange={(e) => setDays(+e.target.value)}
                     style={{
                       padding: "7px 10px", borderRadius: 7,
                       border: `1px solid ${COLORS.border}`,
                       fontSize: 12, color: COLORS.text,
                     }}>
            <option value={7}>Últimos 7 dias</option>
            <option value={30}>Últimos 30 dias</option>
            <option value={90}>Últimos 90 dias</option>
            <option value={365}>Último ano</option>
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 6,
                              fontSize: 12, color: COLORS.text, cursor: "pointer" }}>
            <input type="checkbox" checked={onlyMismatch}
                      data-testid="audit-only-mismatch"
                      onChange={(e) => setOnlyMismatch(e.target.checked)} />
            Apenas divergências
          </label>
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Kpi label="Total" value={data.total} icon="📊" color="#0f172a" />
        <Kpi label="Match (OK)" value={data.total_match}
                icon="✓" color={COLORS.match} />
        <Kpi label="Divergentes" value={data.total_mismatch}
                icon="✕" color={COLORS.mismatch} />
        <Kpi label="Sem mapping" value={data.total_not_in_smartolt}
                icon="○" color={COLORS.noMap} />
      </div>

      {/* Ranking por técnico */}
      {data.by_technician?.length > 0 && (
        <div style={{
          background: "#fff", borderRadius: 12,
          border: `1px solid ${COLORS.border}`, padding: 14,
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: COLORS.muted,
                            textTransform: "uppercase", letterSpacing: 0.5,
                            marginBottom: 10 }}>
            Ranking por técnico · taxa de divergência
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {data.by_technician.slice(0, 10).map((bt) => {
              const flagged = bt.mismatch_rate >= 20 && bt.mismatch > 1;
              return (
                <div key={bt.technician_id} style={{
                  display: "grid", gap: 10,
                  gridTemplateColumns: "1fr auto auto auto",
                  alignItems: "center",
                  padding: "8px 12px", borderRadius: 8,
                  background: flagged ? "#fef2f2" : "#f8fafc",
                  border: flagged ? "1px solid #fca5a5" : "1px solid transparent",
                }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: COLORS.text }}>
                    {flagged && <span style={{ marginRight: 6 }}>⚠️</span>}
                    {bt.technician_name}
                  </div>
                  <div style={{ fontSize: 11, color: COLORS.muted }}>
                    {bt.total} tentativas
                  </div>
                  <div style={{ fontSize: 11, color: COLORS.mismatch,
                                    fontWeight: 700 }}>
                    {bt.mismatch} divergente(s)
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 800,
                                    color: flagged ? COLORS.mismatch : COLORS.match,
                                    minWidth: 50, textAlign: "right" }}>
                    {bt.mismatch_rate}%
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Tabela de eventos */}
      <div style={{
        background: "#fff", borderRadius: 12,
        border: `1px solid ${COLORS.border}`, overflow: "hidden",
      }}>
        <div style={{ padding: 14, fontSize: 12, fontWeight: 700,
                          color: COLORS.muted, textTransform: "uppercase",
                          letterSpacing: 0.5, borderBottom: `1px solid ${COLORS.border}` }}>
          Eventos ({data.items?.length || 0})
        </div>
        {loading && (
          <div style={{ padding: 30, textAlign: "center", color: COLORS.muted }}>
            Carregando...
          </div>
        )}
        {!loading && (data.items?.length === 0) && (
          <div style={{ padding: 30, textAlign: "center", color: COLORS.muted,
                            fontSize: 13 }}>
            Nenhum registro de auditoria para o período.
          </div>
        )}
        {(data.items || []).map((it, idx) => {
          const rl = REASON_LABEL[it.reason]
              || { txt: it.reason, c: COLORS.muted, bg: "#f1f5f9" };
          return (
            <div key={idx} data-testid={`audit-row-${idx}`} style={{
              display: "grid", gridTemplateColumns: "120px 1fr 220px 100px",
              gap: 12, padding: "10px 14px",
              borderBottom: `1px solid ${COLORS.border}`,
              fontSize: 12, alignItems: "center",
            }}>
              <div style={{ color: COLORS.muted, fontSize: 11 }}>
                {fmtTime(it.created_at)}
              </div>
              <div>
                <div style={{ fontWeight: 700, color: COLORS.text }}>
                  {it.client_name || "Cliente"}
                </div>
                <div style={{ fontSize: 10.5, color: COLORS.muted }}>
                  Técnico: {it.technician_name || it.technician_id || "—"}
                  {" · "}OLT: {it.olt_name || "—"}
                </div>
              </div>
              <div style={{ fontSize: 10.5, fontFamily: "monospace",
                                color: COLORS.text, lineHeight: 1.5 }}>
                <div>Lido: <strong>{it.sn_scanned}</strong></div>
                <div>Esperado: <strong style={{
                  color: it.match ? COLORS.match : COLORS.mismatch }}>
                  {it.sn_expected || "—"}</strong></div>
              </div>
              <div style={{
                padding: "4px 8px", borderRadius: 999,
                background: rl.bg, color: rl.c,
                fontSize: 10, fontWeight: 800,
                letterSpacing: 0.5, textAlign: "center",
              }}>{rl.txt}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
