/**
 * Dashboard de Saúde do Estoque — iter165.
 *
 * Visão executiva consolidando:
 *   - Defeituosas pendentes
 *   - ONTs duplicadas (críticas + warning)
 *   - Auditoria SN (divergências últimos 7d + top técnicos)
 *   - Retiradas com inconsistência (vínculo prévio divergente)
 *
 * Score composto 0-100 (excelente/atenção/crítico) + lista acionável
 * com deep-link p/ a subtab específica.
 */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Card } from "@/ui";

const STATUS_META = {
  excelente: { label: "EXCELENTE", color: "#16a34a", bg: "#dcfce7" },
  atencao: { label: "ATENÇÃO", color: "#d97706", bg: "#fef3c7" },
  critico: { label: "CRÍTICO", color: "#dc2626", bg: "#fee2e2" },
};

const SEVERITY_META = {
  critical: { icon: "", color: "#dc2626", bg: "#fee2e2" },
  warning: { icon: "️", color: "#d97706", bg: "#fef3c7" },
  info: { icon: "ℹ️", color: "#0284c7", bg: "#dbeafe" },
  ok: { icon: "✅", color: "#16a34a", bg: "#dcfce7" },
};

export default function StokHealthDashboard({ onNavigate }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const reload = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      setData(await api.stokHealthDashboard());
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  if (loading && !data) {
    return <Card>Carregando dashboard de saúde…</Card>;
  }
  if (err) {
    return <Card><div style={{ color: "#dc2626" }}>Erro: {err}</div></Card>;
  }
  if (!data) return null;

  const statusMeta = STATUS_META[data.status] || STATUS_META.atencao;

  return (
    <div data-testid="stok-health-dashboard">
      {/* Score Card */}
      <Card title="Saúde do Estoque"
            subtitle="Visão consolidada com score composto e ações priorizadas."
            action={
              <button onClick={reload} disabled={loading}
                      data-testid="health-reload"
                      className="btn btn-secondary btn-sm">
                {loading ? "…" : "Atualizar"}
              </button>
            }>
        <div style={{
          display: "grid", gridTemplateColumns: "auto 1fr", gap: 24,
          alignItems: "center",
        }}>
          {/* Gauge */}
          <div style={{ position: "relative", width: 160, height: 160 }}>
            <svg width="160" height="160" viewBox="0 0 160 160">
              <circle cx="80" cy="80" r="68" fill="none"
                      stroke="var(--bg-surface-2)" strokeWidth="14" />
              <circle cx="80" cy="80" r="68" fill="none"
                      stroke={statusMeta.color} strokeWidth="14"
                      strokeDasharray={`${(data.score / 100) * 427} 427`}
                      strokeLinecap="round"
                      transform="rotate(-90 80 80)" />
              <text x="80" y="78" textAnchor="middle"
                    fontSize="42" fontWeight="800"
                    fill="var(--text-primary)">{data.score}</text>
              <text x="80" y="100" textAnchor="middle"
                    fontSize="11" fontWeight="600"
                    fill="var(--text-muted)">/ 100</text>
            </svg>
            <div style={{
              position: "absolute", top: 130, left: 0, right: 0,
              textAlign: "center",
            }}>
              <span className="pill" style={{
                background: statusMeta.bg, color: statusMeta.color,
                fontWeight: 800, fontSize: 11, padding: "3px 10px",
              }}
              data-testid={`health-status-${data.status}`}>
                {statusMeta.label}
              </span>
            </div>
          </div>

          {/* KPIs */}
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
            gap: 10,
          }}>
            <KPI label="Defeituosas pendentes"
                 value={data.defective.pending_return}
                 hint={data.defective.in_analysis > 0
                          ? `+${data.defective.in_analysis} em análise`
                          : null}
                 color="#d97706"
                 onClick={() => onNavigate?.("defeitos")} />
            <KPI label="ONTs duplicadas (abertas)"
                 value={data.duplicates.open}
                 hint={data.duplicates.critical > 0
                          ? `${data.duplicates.critical} críticas`
                          : null}
                 color={data.duplicates.critical > 0 ? "#dc2626" : "#d97706"}
                 onClick={() => onNavigate?.("duplicados")} />
            <KPI label="Divergências SN (7d)"
                 value={data.sn_audit.mismatches_7d}
                 hint={`${data.sn_audit.mismatch_rate_pct}% de ${data.sn_audit.total_7d}`}
                 color={data.sn_audit.mismatch_rate_pct > 20 ? "#dc2626" : "#d97706"}
                 onClick={() => onNavigate?.("audit-sn")} />
            <KPI label="Retiradas inconsistentes"
                 value={data.withdraw_inconsistency.count}
                 color="#0284c7"
                 onClick={() => onNavigate?.("audit-sn")} />
            <KPI label="OSs em erro_estoque"
                 value={data.erro_estoque_count ?? 0}
                 hint="reprocessáveis com saldo negativo"
                 color={data.erro_estoque_count > 0 ? "#dc2626" : "#16a34a"}
                 onClick={() => onNavigate?.("servicos")} />
            <KPI label="Técnicos saldo negativo"
                 value={data.negative_stock?.count ?? 0}
                 hint="quebra/uso fora de OS"
                 color={data.negative_stock?.count > 0 ? "#dc2626" : "#16a34a"}
                 onClick={() => onNavigate?.("insumos")} />
          </div>
        </div>
      </Card>

      {/* Reprocessar OSs travadas */}
      {data.erro_estoque_count > 0 && (
        <ReprocessCard count={data.erro_estoque_count} onDone={reload} />
      )}

      {/* Ações priorizadas */}
      <div style={{ marginTop: 14 }}>
        <Card title="Ações priorizadas"
              data-testid="health-actions-card"
              subtitle="Itens que demandam atenção do gestor, ordenados por severidade.">
          {(data.actions || []).map((a, i) => {
            const meta = SEVERITY_META[a.severity] || SEVERITY_META.info;
            const clickable = !!a.deeplink_tab;
            return (
              <div key={i}
                   data-testid={`health-action-${i}`}
                   onClick={() => clickable && onNavigate?.(a.deeplink_tab)}
                   style={{
                     display: "flex", alignItems: "center", gap: 12,
                     padding: "10px 12px", marginBottom: 6,
                     background: meta.bg, color: meta.color,
                     borderRadius: 8,
                     cursor: clickable ? "pointer" : "default",
                     border: `1px solid ${meta.color}33`,
                   }}>
                <div style={{ fontSize: 20 }}>{meta.icon}</div>
                <div style={{ flex: 1, fontWeight: 600, fontSize: 13 }}>
                  {a.label}
                </div>
                {clickable && (
                  <div style={{ fontSize: 11, fontWeight: 700, opacity: 0.7 }}>
                    Abrir →
                  </div>
                )}
              </div>
            );
          })}
        </Card>
      </div>

      {/* Top técnicos com divergências */}
      {data.sn_audit?.top_techs?.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <Card title="Top técnicos com divergências de SN (7d)"
                subtitle="Possível necessidade de coaching ou re-treinamento na leitura do equipamento.">
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "var(--bg-surface-2)" }}>
                  <th style={_th}>Técnico</th>
                  <th style={{ ..._th, textAlign: "right" }}>Divergências</th>
                </tr>
              </thead>
              <tbody>
                {data.sn_audit.top_techs.map((t) => (
                  <tr key={t.technician_id || "unknown"}
                      style={{ borderBottom: "1px solid var(--border-default)" }}>
                    <td style={_td}>{t.name}</td>
                    <td style={{ ..._td, textAlign: "right", fontWeight: 700 }}>
                      {t.count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-muted)",
                       textAlign: "right" }}>
        Atualizado em {new Date(data.generated_at).toLocaleString("pt-BR")}
      </div>
    </div>
  );
}

function KPI({ label, value, hint, color, onClick }) {
  return (
    <div onClick={onClick}
         style={{
           background: "var(--bg-surface-2)",
           border: "1px solid var(--border-default)",
           borderLeft: `3px solid ${color}`,
           borderRadius: 8, padding: "10px 12px",
           cursor: onClick ? "pointer" : "default",
           transition: "transform 0.1s ease",
         }}
         onMouseEnter={(e) => onClick && (e.currentTarget.style.transform = "translateY(-2px)")}
         onMouseLeave={(e) => onClick && (e.currentTarget.style.transform = "translateY(0)")}>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
                     textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 800, marginTop: 2, color }}>
        {value ?? 0}
      </div>
      {hint && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

const _th = {
  padding: "8px 10px", fontSize: 11, fontWeight: 700,
  color: "var(--text-secondary)", textTransform: "uppercase",
  letterSpacing: "0.06em", textAlign: "left",
  borderBottom: "1px solid var(--border-default)",
};
const _td = { padding: "10px", fontSize: 13, verticalAlign: "middle" };

function ReprocessCard({ count, onDone }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const run = async () => {
    if (!window.confirm(
      `Reprocessar ${count} OS(s) em erro_estoque?\n\n` +
      "O sistema vai tentar finalizar cada uma permitindo saldo NEGATIVO " +
      "(quebra visível). Útil quando o estoque do técnico estava zerado " +
      "mas o consumo aconteceu."
    )) return;
    setBusy(true); setErr(""); setResult(null);
    try {
      const r = await api.stokReprocessErroEstoque(200);
      setResult(r);
      onDone?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div style={{ marginTop: 14 }}>
      <Card title="Reprocessar OSs travadas em erro_estoque"
            data-testid="reprocess-erro-estoque-card"
            subtitle={`Existem ${count} OSs que falharam por falta de saldo. Agora que o saldo negativo é permitido, podemos reprocessá-las para registrar o consumo (e a QUEBRA correspondente).`}>
        <button onClick={run} disabled={busy}
                data-testid="reprocess-erro-estoque-btn"
                style={{
                  padding: "10px 16px", borderRadius: 8, border: 0,
                  background: busy ? "#94a3b8" : "linear-gradient(135deg,#dc2626,#991b1b)",
                  color: "#fff", fontSize: 13, fontWeight: 700,
                  cursor: busy ? "wait" : "pointer",
                }}>
          {busy ? "Reprocessando…" : `Reprocessar ${count} OS(s)`}
        </button>
        {err && <div style={{ marginTop: 10, color: "#dc2626", fontSize: 12 }}>Erro: {err}</div>}
        {result && (
          <div data-testid="reprocess-erro-estoque-result"
               style={{ marginTop: 12, padding: 12,
                            background: "var(--bg-surface-2)", borderRadius: 8,
                            fontSize: 13 }}>
            <div><strong>Processadas:</strong> {result.processed}</div>
            <div style={{ color: "#16a34a" }}>
              <strong>✓ Sucesso:</strong> {result.succeeded}
            </div>
            {result.still_failed > 0 && (
              <div style={{ color: "#dc2626" }}>
                <strong>✗ Ainda falharam:</strong> {result.still_failed}{" "}
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                  (motivos comuns: ticket apagado, sem completion_data)
                </span>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
