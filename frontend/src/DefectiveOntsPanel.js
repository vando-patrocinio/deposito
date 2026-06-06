/* =============================================================
   DefectiveOntsPanel — painel do gestor para ONTs defeituosas

   Lista ONTs marcadas pelo técnico durante a Retirada como
   "Equipamento com defeito". Permite:
     • Confirmar devolução à empresa (move tecnico → empresa,
       status passa para `defeito_em_analise`)
     • Sucatear (descarte definitivo)

   Iter154 (28/05/2026) — fecha o ciclo de retorno do equipamento.
============================================================= */
import React, { useState, useEffect, useCallback } from "react";
import { api } from "@/api";

const COLORS = {
  pending: { bg: "#fef2f2", border: "#fca5a5", color: "#7f1d1d" },
  inAnalysis: { bg: "#fefce8", border: "#fde68a", color: "#854d0e" },
  card: "#ffffff",
  border: "#e2e8f0",
  text: "#0f172a",
  muted: "#64748b",
};

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return "—"; }
}

function StatusBadge({ returned }) {
  const s = returned ? "inAnalysis" : "pending";
  const c = COLORS[s];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "3px 8px", borderRadius: 999,
      background: c.bg, color: c.color, border: `1px solid ${c.border}`,
      fontSize: 10, fontWeight: 800, textTransform: "uppercase",
      letterSpacing: 0.5,
    }}>
      {returned ? "Em análise" : "⏳ Aguardando devolução"}
    </span>
  );
}

function KpiCard({ icon, label, value, color }) {
  return (
    <div style={{
      flex: 1, minWidth: 160, padding: 14,
      background: "#fff", borderRadius: 12,
      border: `1px solid ${COLORS.border}`,
      display: "flex", alignItems: "center", gap: 12,
    }}>
      <div style={{
        width: 44, height: 44, borderRadius: 10,
        background: color + "22", color, fontSize: 20,
        display: "grid", placeItems: "center", flexShrink: 0,
      }}>{icon}</div>
      <div>
        <div style={{ fontSize: 22, fontWeight: 800, color: COLORS.text,
                          lineHeight: 1.1, fontVariantNumeric: "tabular-nums" }}>
          {value}
        </div>
        <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 600,
                          marginTop: 2, textTransform: "uppercase",
                          letterSpacing: 0.5 }}>
          {label}
        </div>
      </div>
    </div>
  );
}

function OntRow({ item, onConfirmReturn, onScrap, onRevert }) {
  const [busy, setBusy] = useState(false);
  const handle = async (kind) => {
    if (busy) return;
    setBusy(true);
    try {
      if (kind === "return") {
        const notes = window.prompt(
          "Notas de recebimento (opcional):",
          item.returned_notes || "",
        );
        if (notes === null) { setBusy(false); return; }
        await onConfirmReturn(item.mac, notes);
      } else if (kind === "scrap") {
        if (!window.confirm(
          `Sucatear ONT ${item.mac}?\n\nO equipamento será marcado como ` +
          `DESCARTE DEFINITIVO e não poderá mais ser usado.`)) {
          setBusy(false); return;
        }
        await onScrap(item.mac);
      } else if (kind === "revert") {
        if (!window.confirm(
          `Reverter ONT ${item.mac}?\n\nO equipamento voltará ao estoque da ` +
          `empresa como DISPONÍVEL (não defeituosa) e poderá ser instalado ` +
          `em outro cliente.`)) {
          setBusy(false); return;
        }
        await onRevert(item.mac);
      }
    } catch (e) {
      window.alert(e?.response?.data?.detail || e.message || "Falha na operação");
    } finally { setBusy(false); }
  };

  return (
    <div data-testid={`defective-row-${item.mac}`} style={{
      padding: 14, borderRadius: 12,
      background: COLORS.card,
      border: `1px solid ${item.returned ? "#fde68a" : "#fca5a5"}`,
      marginBottom: 10,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                        gap: 12, marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10,
                            marginBottom: 4, flexWrap: "wrap" }}>
            <code style={{
              fontFamily: "monospace", fontSize: 14, fontWeight: 800,
              color: COLORS.text, background: "#f1f5f9",
              padding: "2px 8px", borderRadius: 6, letterSpacing: 0.5,
            }}>{item.mac}</code>
            <StatusBadge returned={item.returned} />
            {item.model && (
              <span style={{ fontSize: 11, color: COLORS.muted, fontWeight: 600 }}>
                · {item.model}
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, color: COLORS.muted, marginTop: 4,
                            lineHeight: 1.5 }}>
            <strong style={{ color: COLORS.text }}>
              {item.withdrawn_from_client_name || "Cliente não identificado"}
            </strong>
            {" · retirada em "}{fmtDate(item.withdrawn_at)}
            {item.tech_name && (
              <> · técnico <strong style={{ color: COLORS.text }}>
                {item.tech_name}
              </strong></>
            )}
          </div>
          {item.defective_reason && (
            <div style={{ marginTop: 8, padding: "6px 10px",
                              background: "#fef2f2", borderRadius: 6,
                              border: "1px solid #fee2e2",
                              fontSize: 11.5, color: "#7f1d1d",
                              lineHeight: 1.5 }}>
              <strong>️ Defeito reportado:</strong> {item.defective_reason}
            </div>
          )}
          {item.returned && (
            <div style={{ marginTop: 6, fontSize: 11, color: "#854d0e" }}>
              ↩ Devolvida em {fmtDate(item.returned_to_company_at)}
              {item.returned_to_company_by && (
                <> por <strong>{item.returned_to_company_by}</strong></>
              )}
              {item.returned_notes && (
                <div style={{ marginTop: 4, fontStyle: "italic" }}>
                  “{item.returned_notes}”
                </div>
              )}
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6,
                          minWidth: 180, flexShrink: 0 }}>
          {!item.returned && (
            <button data-testid={`defective-confirm-${item.mac}`}
                      disabled={busy}
                      onClick={() => handle("return")}
                      style={{
                        padding: "8px 12px", borderRadius: 8,
                        background: "#16a34a", color: "#fff", border: 0,
                        fontSize: 12, fontWeight: 800, cursor: "pointer",
                        opacity: busy ? 0.5 : 1, whiteSpace: "nowrap",
                      }}>
              ↩ Confirmar devolução
            </button>
          )}
          <button data-testid={`defective-scrap-${item.mac}`}
                    disabled={busy}
                    onClick={() => handle("scrap")}
                    style={{
                      padding: "8px 12px", borderRadius: 8,
                      background: "#fff", color: "#7f1d1d",
                      border: "1px solid #dc2626",
                      fontSize: 12, fontWeight: 800, cursor: "pointer",
                      opacity: busy ? 0.5 : 1, whiteSpace: "nowrap",
                    }}>
            Sucatear
          </button>
          {item.returned && (
            <button data-testid={`defective-revert-${item.mac}`}
                      disabled={busy}
                      onClick={() => handle("revert")}
                      title="Falso positivo — voltar como disponível"
                      style={{
                        padding: "8px 12px", borderRadius: 8,
                        background: "#fff", color: "#1e40af",
                        border: "1px solid #3b82f6",
                        fontSize: 12, fontWeight: 800, cursor: "pointer",
                        opacity: busy ? 0.5 : 1, whiteSpace: "nowrap",
                      }}>
              ↶ Reverter
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function DefectiveOntsPanel() {
  const [data, setData] = useState({ items: [], pending_return: 0,
                                            in_analysis: 0, total: 0 });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState("pending"); // pending | all | analysis
  const [search, setSearch] = useState("");

  const reload = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.stokDefectiveOnts();
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao carregar");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const handleConfirmReturn = async (mac, notes) => {
    await api.stokDefectiveOntConfirmReturn(mac, notes);
    await reload();
  };
  const handleScrap = async (mac) => {
    await api.stokDefectiveOntScrap(mac);
    await reload();
  };
  const handleRevert = async (mac) => {
    await api.stokDefectiveOntRevert(mac);
    await reload();
  };

  const filtered = (data.items || []).filter((it) => {
    if (filter === "pending" && it.returned) return false;
    if (filter === "analysis" && !it.returned) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!(it.mac || "").toLowerCase().includes(q)
          && !(it.withdrawn_from_client_name || "").toLowerCase().includes(q)
          && !(it.tech_name || "").toLowerCase().includes(q)
          && !(it.defective_reason || "").toLowerCase().includes(q)) {
        return false;
      }
    }
    return true;
  });

  return (
    <div data-testid="defective-onts-panel">
      <div style={{ marginBottom: 12 }}>
        <h3 style={{ margin: "0 0 4px", fontSize: 18, fontWeight: 800,
                         color: COLORS.text }}>
          ️ ONTs Defeituosas — devolução obrigatória à empresa
        </h3>
        <p style={{ margin: 0, fontSize: 12, color: COLORS.muted }}>
          Equipamentos marcados pelos técnicos como defeituosos durante a
          retirada. Não estão disponíveis para reinstalação.
        </p>
      </div>

      <div style={{ display: "flex", gap: 10, marginBottom: 14,
                       flexWrap: "wrap" }}>
        <KpiCard icon="⏳" label="Aguardando devolução"
                    value={data.pending_return || 0} color="#dc2626" />
        <KpiCard icon="" label="Em análise na empresa"
                    value={data.in_analysis || 0} color="#ca8a04" />
        <KpiCard icon="" label="Total registrado"
                    value={data.total || 0} color="#0f172a" />
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap",
                       padding: 4, background: "#f1f5f9", borderRadius: 10 }}>
        {[
          { id: "pending", label: "⏳ Pendentes",
            count: data.pending_return || 0 },
          { id: "analysis", label: "Em análise",
            count: data.in_analysis || 0 },
          { id: "all", label: "Todos", count: data.total || 0 },
        ].map((t) => (
          <button key={t.id}
                    data-testid={`defective-tab-${t.id}`}
                    onClick={() => setFilter(t.id)}
                    style={{
                      flex: "0 1 auto", padding: "8px 14px", border: 0,
                      borderRadius: 7,
                      background: filter === t.id ? "#fff" : "transparent",
                      color: filter === t.id ? COLORS.text : COLORS.muted,
                      fontSize: 12, fontWeight: 800, cursor: "pointer",
                      boxShadow: filter === t.id
                          ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                    }}>
            {t.label} <span style={{ marginLeft: 6, opacity: 0.7 }}>
              ({t.count})
            </span>
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <input
          data-testid="defective-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar MAC, cliente, técnico..."
          style={{
            padding: "8px 12px", borderRadius: 7,
            border: `1px solid ${COLORS.border}`,
            fontSize: 12, minWidth: 220, outline: "none",
            background: "#fff",
          }}
        />
        <button data-testid="defective-reload"
                  onClick={reload} disabled={loading}
                  style={{
                    padding: "8px 12px", borderRadius: 7,
                    background: "#fff", color: COLORS.text,
                    border: `1px solid ${COLORS.border}`,
                    fontSize: 12, fontWeight: 700, cursor: "pointer",
                    opacity: loading ? 0.5 : 1,
                  }}>
          {loading ? "⌛" : "⟳"} Recarregar
        </button>
      </div>

      {err && (
        <div style={{
          padding: 14, marginBottom: 12, borderRadius: 10,
          background: "#fef2f2", color: "#7f1d1d",
          border: "1px solid #fca5a5", fontSize: 13,
        }}>{err}</div>
      )}

      {loading && (
        <div style={{ padding: 30, textAlign: "center", color: COLORS.muted }}>
          Carregando ONTs defeituosas...
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <div style={{
          padding: 40, textAlign: "center", borderRadius: 12,
          background: "#fff", border: `1px dashed ${COLORS.border}`,
          color: COLORS.muted,
        }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>
            {filter === "pending" ? "✅" : ""}
          </div>
          <div style={{ fontSize: 14, fontWeight: 700, color: COLORS.text }}>
            {filter === "pending"
              ? "Nenhuma ONT pendente de devolução"
              : "Nenhum registro encontrado"}
          </div>
          <div style={{ fontSize: 12, marginTop: 4 }}>
            {filter === "pending"
              ? "Quando técnicos marcarem equipamentos como defeituosos durante retiradas, eles aparecerão aqui."
              : search ? "Tente outra busca." : "Sem registros."}
          </div>
        </div>
      )}

      {!loading && filtered.map((it) => (
        <OntRow key={it.mac} item={it}
                  onConfirmReturn={handleConfirmReturn}
                  onScrap={handleScrap}
                  onRevert={handleRevert} />
      ))}
    </div>
  );
}
