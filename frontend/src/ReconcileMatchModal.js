/*
ReconcileMatchModal.js — Modal de conciliação ativa.

Exibe 4 abas:
  1. ✅ Auto-baixados — matches com score 100 já marcados como pagos.
  2. 🔍 Pendentes de revisão — score 90-95, gestor escolhe quais aprovar.
  3. 💰 PIX órfãos — recebimentos bancários sem fatura correspondente.
  4. 📄 Faturas órfãs — faturas abertas sem PIX correspondente.
*/
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button } from "@/ui";
import {
  X, CheckCircle2, AlertTriangle, Search, Loader2, FileText, ArrowRight,
} from "lucide-react";

const fmtMoney = (v) =>
  Number(v || 0).toLocaleString("pt-BR",
    { style: "currency", currency: "BRL" });
const fmtDoc = (d) => {
  if (!d) return "—";
  const s = String(d).replace(/\D/g, "");
  if (s.length === 11) return s.replace(
    /(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
  if (s.length === 14) return s.replace(
    /(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, "$1.$2.$3/$4-$5");
  return s;
};
const fmtDate = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso.slice(0, 10) + "T12:00:00")
      .toLocaleDateString("pt-BR");
  } catch { return iso; }
};

export default function ReconcileMatchModal({ from_date, to_date, onClose,
                                                       onMutated }) {
  const [tab, setTab] = useState("auto");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState({}); // {movement_id: invoice_id}
  const [confirming, setConfirming] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const r = await api.bankImportReconcilePayments(
        from_date, to_date, true);
      setData(r);
      // Pré-marca apenas matches de alta confiança (score >= 95)
      // Score 90 (data diff > 7d) fica desmarcado pra revisão cuidadosa.
      const presel = {};
      (r.pending || []).forEach((m) => {
        if ((m.score || 0) >= 95) {
          presel[m.movement.id] = m.invoice.id;
        }
      });
      setSelected(presel);
    } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function onApproveSelected() {
    const matches = Object.entries(selected)
      .filter(([_, iid]) => iid)
      .map(([mid, iid]) => ({ movement_id: mid, invoice_id: iid }));
    if (matches.length === 0) return;
    setConfirming(true);
    try {
      const r = await api.bankImportReconcileConfirm(matches);
      alert(`${r.approved} fatura(s) marcada(s) como paga(s).`);
      setSelected({});
      if (onMutated) onMutated();
      await load();
    } finally { setConfirming(false); }
  }

  const stats = data?.stats || {};
  const tabs = [
    { id: "auto", label: "Auto-baixados",
      count: stats.auto_marked_count, icon: CheckCircle2, color: "#16a34a" },
    { id: "pending", label: "Revisar",
      count: stats.pending_count, icon: AlertTriangle, color: "#d97706" },
    { id: "pix-orphans", label: "PIX sem fatura",
      count: stats.pix_orphans_count, icon: Search, color: "#0ea5e9" },
    { id: "inv-orphans", label: "Faturas sem PIX",
      count: stats.invoices_orphans_count, icon: FileText, color: "#64748b" },
  ];

  return (
    <div data-testid="reconcile-modal"
          style={{
            position: "fixed", inset: 0, zIndex: 1000,
            background: "rgba(15,23,42,0.55)",
            display: "flex", justifyContent: "center",
            alignItems: "center", padding: 16,
          }}
          onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={{
        background: "#fff", width: "min(96vw, 1100px)", maxHeight: "90vh",
        borderRadius: 14, display: "flex", flexDirection: "column",
        overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{
          padding: "14px 18px",
          borderBottom: "1px solid #e2e8f0",
          display: "flex", alignItems: "center",
          justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
              🔍 Conciliação · PIX × Boletos Atlaz
            </div>
            <div style={{ fontSize: 11.5, color: "#64748b", marginTop: 2 }}>
              Período: {fmtDate(from_date)} → {fmtDate(to_date)}
            </div>
          </div>
          <button onClick={onClose} data-testid="reconcile-close-btn"
                  style={{ background: "transparent", border: "none",
                            cursor: "pointer", color: "#64748b" }}>
            <X size={20} />
          </button>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", padding: "4px 18px",
                          borderBottom: "1px solid #e2e8f0", gap: 4,
                          flexWrap: "wrap" }}>
          {tabs.map((t) => {
            const Ico = t.icon;
            const active = tab === t.id;
            return (
              <button key={t.id} onClick={() => setTab(t.id)}
                        data-testid={`reconcile-tab-${t.id}`}
                        style={{
                          display: "flex", alignItems: "center", gap: 6,
                          padding: "8px 14px",
                          border: "none", background: "transparent",
                          color: active ? t.color : "#64748b",
                          borderBottom: active
                            ? `2px solid ${t.color}` : "2px solid transparent",
                          fontWeight: active ? 800 : 600,
                          fontSize: 12.5, cursor: "pointer",
                          marginBottom: -1,
                        }}>
                <Ico size={14} /> {t.label}
                {t.count != null && (
                  <span style={{
                    background: active ? t.color : "#e2e8f0",
                    color: active ? "#fff" : "#64748b",
                    fontSize: 10, fontWeight: 700,
                    padding: "1px 6px", borderRadius: 999,
                    fontVariantNumeric: "tabular-nums",
                  }}>{t.count}</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Conteúdo */}
        <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {loading ? (
            <div style={{ padding: 30, textAlign: "center",
                            color: "#64748b" }}>
              <Loader2 className="animate-spin" size={18} />
              <div style={{ marginTop: 6, fontSize: 12 }}>
                Buscando movimentos e cruzando com faturas Atlaz…
              </div>
            </div>
          ) : !data ? (
            <div style={{ padding: 30, textAlign: "center",
                            color: "#dc2626" }}>
              Falha ao carregar conciliação.
            </div>
          ) : (
            <>
              {tab === "auto" && (
                <MatchList items={data.auto_marked} type="auto" />
              )}
              {tab === "pending" && (
                <MatchList items={data.pending} type="pending"
                  selected={selected} setSelected={setSelected} />
              )}
              {tab === "pix-orphans" && (
                <OrphanList items={data.pix_orphans} type="pix" />
              )}
              {tab === "inv-orphans" && (
                <OrphanList items={data.invoices_orphans} type="inv" />
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {tab === "pending" && !loading && (data?.pending?.length > 0) && (
          <div style={{
            padding: "10px 18px", borderTop: "1px solid #e2e8f0",
            display: "flex", justifyContent: "space-between",
            alignItems: "center",
          }}>
            <div style={{ fontSize: 12, color: "#64748b" }}>
              {Object.values(selected).filter(Boolean).length} de{" "}
              {data.pending.length} selecionado(s) para baixa
            </div>
            <Button onClick={onApproveSelected}
                     disabled={confirming
                                  || Object.values(selected).filter(Boolean).length === 0}
                     data-testid="reconcile-approve-selected">
              {confirming ? (<><Loader2 className="animate-spin" size={14} /> Confirmando…</>)
                : (<><CheckCircle2 size={14} /> Aprovar selecionados</>)}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function MatchList({ items, type, selected, setSelected }) {
  if (!items || items.length === 0) {
    return (
      <div style={{ padding: 30, textAlign: "center",
                       color: "#94a3b8", fontSize: 13 }}>
        {type === "auto"
          ? "Nenhum match automático no período."
          : "Nenhuma sugestão pendente."}
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {items.map((m, i) => (
        <div key={i} data-testid={`reconcile-match-${type}-${i}`}
              style={{
                display: "grid",
                gridTemplateColumns: type === "pending"
                  ? "auto 1fr auto 1fr auto"
                  : "1fr auto 1fr auto",
                gap: 12, alignItems: "center",
                padding: 12, borderRadius: 10,
                background: type === "auto" ? "#f0fdf4" : "#fffbeb",
                border: type === "auto"
                  ? "1px solid #86efac" : "1px solid #fcd34d",
              }}>
          {type === "pending" && (
            <input type="checkbox"
              data-testid={`reconcile-check-${m.movement.id}`}
              checked={!!selected?.[m.movement.id]}
              onChange={(e) => setSelected({
                ...selected,
                [m.movement.id]: e.target.checked ? m.invoice.id : "",
              })} />
          )}
          <div>
            <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                            textTransform: "uppercase", letterSpacing: 0.3 }}>
              💰 PIX bancário
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a",
                            marginTop: 2 }}>
              {fmtMoney(m.movement.amount)}
            </div>
            <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
              {fmtDate(m.movement.date)} · {fmtDoc(m.movement.doc)}
            </div>
            <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2,
                            overflow: "hidden",
                            textOverflow: "ellipsis", whiteSpace: "nowrap",
                            maxWidth: 240 }}>
              {m.movement.description}
            </div>
          </div>
          <ArrowRight size={16} style={{ color: "#94a3b8" }} />
          <div>
            <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                            textTransform: "uppercase", letterSpacing: 0.3 }}>
              📄 Fatura Atlaz
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a",
                            marginTop: 2 }}>
              {m.invoice.subscriber_name || "—"}
            </div>
            <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
              Venc {fmtDate(m.invoice.due_date)}
              {" · "}{fmtMoney(m.invoice.amount)}
            </div>
            <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2 }}>
              FAT#{m.invoice.external_id} · {m.invoice.description}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{
              background: m.score >= 100 ? "#dcfce7"
                : m.score >= 95 ? "#fef9c3" : "#fef3c7",
              color: m.score >= 100 ? "#15803d"
                : m.score >= 95 ? "#a16207" : "#92400e",
              padding: "3px 8px", borderRadius: 999,
              fontSize: 10, fontWeight: 800, display: "inline-block",
            }}>
              {m.score}% confiança
            </div>
            <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 4 }}>
              ±{m.days_diff || 0} dia(s)
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function OrphanList({ items, type }) {
  if (!items || items.length === 0) {
    return (
      <div style={{ padding: 30, textAlign: "center",
                       color: "#94a3b8", fontSize: 13 }}>
        Nada por aqui — tudo conciliado neste grupo!
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {items.map((it) => (
        <div key={it.id} style={{
          padding: 10, borderRadius: 8, background: "#f8fafc",
          border: "1px solid #e2e8f0",
          display: "grid", gridTemplateColumns: "1fr auto", gap: 10,
          alignItems: "center",
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: "#0f172a",
                            overflow: "hidden", whiteSpace: "nowrap",
                            textOverflow: "ellipsis" }}>
              {type === "pix" ? it.description
                : it.subscriber_name || "(sem nome)"}
            </div>
            <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
              {type === "pix"
                ? <>{fmtDate(it.date)} · CPF/CNPJ: {fmtDoc(it.doc)}</>
                : <>Venc {fmtDate(it.due_date)} · {fmtDoc(it.subscriber_document)}
                    {it.external_id ? ` · FAT#${it.external_id}` : ""}</>}
            </div>
          </div>
          <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a",
                          fontVariantNumeric: "tabular-nums" }}>
            {fmtMoney(it.amount)}
          </div>
        </div>
      ))}
    </div>
  );
}
