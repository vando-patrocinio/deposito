/* StokTransfersPanel.js — Painel admin de transferências:
 *  - KPI card (sucessos, pendentes, aprovadas, rejeitadas, % de match)
 *  - Lista de pendências com aprovar/rejeitar
 *  - Top técnicos com pendências
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  CheckCircle2, XCircle, AlertTriangle, TrendingUp, TrendingDown,
  RefreshCw, Activity, Users, Clock,
} from "lucide-react";
import { api } from "@/api";

const card = {
  padding: 16, borderRadius: 12, border: "1px solid var(--border-default)",
  background: "var(--bg-surface)",
};
const btnGhost = {
  padding: "6px 10px", borderRadius: 8,
  border: "1px solid var(--border-default)",
  background: "transparent", color: "var(--text-primary)",
  fontSize: 12, cursor: "pointer",
};

function KpiCard({ icon: Icon, label, value, color, testId }) {
  return (
    <div data-testid={testId} style={{ ...card, textAlign: "center" }}>
      <div style={{
        margin: "0 auto 6px", width: 36, height: 36, borderRadius: 10,
        background: color + "20", color, display: "grid", placeItems: "center",
      }}>
        <Icon size={18} />
      </div>
      <div style={{ fontSize: 28, fontWeight: 800, color }}>{value}</div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", fontWeight: 700, letterSpacing: ".05em" }}>
        {label}
      </div>
    </div>
  );
}

function PendingRow({ item, onApprove, onReject, busy }) {
  return (
    <div data-testid={`pending-row-${item.id}`} style={{
      padding: 14, borderRadius: 10, marginBottom: 10,
      border: "1px solid #fde68a", background: "#fffbeb",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ fontSize: 13, fontWeight: 800, color: "#92400e", marginBottom: 4 }}>
            <AlertTriangle size={14} style={{ display: "inline", marginRight: 4, verticalAlign: -2 }} />
            {item.reason || "Pendente de aprovação"}
          </div>
          <div style={{ fontSize: 12, color: "#1e293b", marginBottom: 6 }}>
            <strong>Cliente:</strong> {item.client_name || item.client_id} ·{" "}
            <strong>Técnico:</strong> {item.technician_name || item.technician_id}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 11, fontFamily: "monospace" }}>
            <div style={{
              padding: 8, borderRadius: 6, background: "#dbeafe", color: "#1e40af",
            }}>
              <div style={{ fontSize: 9, fontWeight: 800, opacity: 0.8 }}>SN ESTOQUE</div>
              <div style={{ fontWeight: 800 }}>{item.stock_mac || "—"}</div>
              {item.stock_sn && <div style={{ fontSize: 10 }}>SN: {item.stock_sn}</div>}
            </div>
            <div style={{
              padding: 8, borderRadius: 6,
              background: item.smartolt_mac ? "#fef3c7" : "#fee2e2",
              color: item.smartolt_mac ? "#854d0e" : "#991b1b",
            }}>
              <div style={{ fontSize: 9, fontWeight: 800, opacity: 0.8 }}>SN SMARTOLT</div>
              <div style={{ fontWeight: 800 }}>{item.smartolt_mac || "(não encontrado)"}</div>
              {item.smartolt_status && <div style={{ fontSize: 10 }}>status: {item.smartolt_status}</div>}
            </div>
          </div>
          <div style={{ fontSize: 10, color: "#64748b", marginTop: 6 }}>
            Criado: {new Date(item.created_at).toLocaleString("pt-BR")}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <button data-testid={`approve-${item.id}`} onClick={() => onApprove(item)}
                  disabled={busy}
                  style={{
                    padding: "8px 14px", borderRadius: 8, border: 0,
                    background: "linear-gradient(135deg,#10b981,#059669)",
                    color: "#fff", fontWeight: 800, fontSize: 12,
                    cursor: busy ? "wait" : "pointer",
                  }}>
            <CheckCircle2 size={12} style={{ display: "inline", marginRight: 4, verticalAlign: -1 }} />
            Aprovar
          </button>
          <button data-testid={`reject-${item.id}`} onClick={() => onReject(item)}
                  disabled={busy}
                  style={{
                    padding: "8px 14px", borderRadius: 8,
                    border: "1px solid #ef4444",
                    background: "transparent",
                    color: "#991b1b", fontWeight: 700, fontSize: 12,
                    cursor: busy ? "wait" : "pointer",
                  }}>
            <XCircle size={12} style={{ display: "inline", marginRight: 4, verticalAlign: -1 }} />
            Devolver
          </button>
        </div>
      </div>
    </div>
  );
}

export default function StokTransfersPanel() {
  const [kpis, setKpis] = useState(null);
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [k, p] = await Promise.all([
        api.stokTransferKpis(30),
        api.stokPendingTransfers("pending"),
      ]);
      setKpis(k);
      setPending(p?.items || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onApprove = async (item) => {
    if (!window.confirm(`Aprovar transferência?\nMAC: ${item.stock_mac}\nCliente: ${item.client_name}\n\nA ONT será movida do estoque do técnico para o cliente.`)) return;
    setBusy(true);
    try {
      await api.stokApproveTransfer(item.id);
      load();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  };

  const onReject = async (item) => {
    const note = window.prompt("Motivo da devolução? (opcional)") || "";
    if (note === null) return;
    setBusy(true);
    try {
      await api.stokRejectTransfer(item.id, note);
      load();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="stok-transfers-panel" style={{ display: "grid", gap: 16 }}>
      {/* Header */}
      <div style={{
        ...card,
        background: "linear-gradient(135deg, var(--accent-soft) 0%, var(--bg-surface) 60%)",
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: "linear-gradient(135deg,#0d9488,#06b6d4)",
          color: "#fff", display: "grid", placeItems: "center", flexShrink: 0,
        }}>
          <Activity size={24} />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontWeight: 800, fontSize: 16 }}>Transferências de ONT</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Estoque do técnico ↔ Cliente · validação automática com SmartOLT · aprovação manual quando MAC diverge.
          </div>
        </div>
        <button data-testid="transfers-refresh" style={btnGhost} onClick={load}>
          <RefreshCw size={14} />
        </button>
      </div>

      {/* KPIs */}
      {kpis && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
          <KpiCard icon={CheckCircle2} label="SUCESSO DIRETO"
                    value={kpis.installed_direct} color="#10b981"
                    testId="kpi-installed-direct" />
          <KpiCard icon={Clock} label="PENDENTES" value={kpis.pending}
                    color="#f59e0b" testId="kpi-pending" />
          <KpiCard icon={CheckCircle2} label="APROVADAS (30d)"
                    value={kpis.approved} color="#0d9488"
                    testId="kpi-approved" />
          <KpiCard icon={XCircle} label="REJEITADAS (30d)"
                    value={kpis.rejected} color="#ef4444"
                    testId="kpi-rejected" />
          <KpiCard icon={TrendingDown} label="RETIRADAS (30d)"
                    value={kpis.withdrawn} color="#8b5cf6"
                    testId="kpi-withdrawn" />
          <KpiCard icon={TrendingUp} label="MATCH SMARTOLT"
                    value={`${kpis.match_pct}%`} color="#06b6d4"
                    testId="kpi-match-pct" />
        </div>
      )}

      {/* Top técnicos com pendências */}
      {kpis?.top_pending_techs?.length > 0 && (
        <div style={card}>
          <div style={{ fontWeight: 800, fontSize: 13, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
            <Users size={14} /> Top técnicos com pendências (30 dias)
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            {kpis.top_pending_techs.map((t) => (
              <div key={t.technician_id} style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "8px 12px", borderRadius: 8, background: "#fef3c7", fontSize: 13,
              }}>
                <span><strong>{t.technician_name}</strong></span>
                <span style={{
                  padding: "2px 10px", borderRadius: 999,
                  background: "#92400e", color: "#fff", fontWeight: 800, fontSize: 11,
                }}>{t.count} pendência{t.count !== 1 ? "s" : ""}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Lista de Pendentes */}
      <div style={card}>
        <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <AlertTriangle size={16} color="#f59e0b" />
          Aguardando aprovação ({pending.length})
        </div>
        {loading ? (
          <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)" }}>
            Carregando…
          </div>
        ) : pending.length === 0 ? (
          <div data-testid="pending-empty" style={{
            padding: 24, textAlign: "center", color: "var(--text-muted)",
            background: "#f0fdf4", borderRadius: 8, border: "1px solid #bbf7d0",
          }}>
            <CheckCircle2 size={28} color="#22c55e" style={{ marginBottom: 6 }} />
            <div style={{ fontSize: 13, fontWeight: 700, color: "#166534" }}>
              Sem pendências
            </div>
            <div style={{ fontSize: 11, marginTop: 4 }}>
              Todas as transferências estão batendo com o SmartOLT.
            </div>
          </div>
        ) : (
          <div>
            {pending.map((p) => (
              <PendingRow key={p.id} item={p}
                            busy={busy}
                            onApprove={onApprove}
                            onReject={onReject} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
