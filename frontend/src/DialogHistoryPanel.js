/**
 * DialogHistoryPanel — botão flutuante (canto inferior direito) que mostra
 * o histórico de TODOS os modais exibidos na sessão atual (alert/confirm/
 * prompt). Útil pra auditoria e debug: quem clicou em Cancelar onde, quando
 * apagou o quê, etc.
 *
 * Visível apenas para roles administrativos (administrador/auditor) — pra
 * técnico/gestor o ícone não aparece (sem ruído visual).
 *
 * Botão: pílula compacta no bottom-right com badge da contagem.
 * Drawer: slide do direita com lista filtrável + busca + clear.
 */
import React, { useMemo, useState } from "react";
import {
  History, X, ShieldAlert, AlertCircle, Info, MessageCircle, Check,
  Search, Trash2, Filter,
} from "lucide-react";
import { useDialogHistory, clearDialogHistory } from "@/dialog";

const KIND_META = {
  alert:   { label: "Aviso",      icon: Info,         color: "#0ea5e9" },
  confirm: { label: "Confirmação", icon: ShieldAlert,  color: "#dc2626" },
  prompt:  { label: "Entrada",    icon: MessageCircle, color: "#0f172a" },
};

function fmtTime(ts) {
  const d = new Date(ts);
  const today = new Date();
  const isToday = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return isToday ? time : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function ResponsePill({ kind, response }) {
  if (kind === "alert") {
    return <span style={pillStyle("#0ea5e9", "#e0f2fe")}>✓ OK</span>;
  }
  if (kind === "confirm") {
    if (response === "ok") return <span style={pillStyle("#16a34a", "#dcfce7")}>✓ Confirmou</span>;
    return <span style={pillStyle("#64748b", "#f1f5f9")}>✕ Cancelou</span>;
  }
  // prompt
  if (response === "cancel") return <span style={pillStyle("#64748b", "#f1f5f9")}>✕ Cancelou</span>;
  return (
    <span style={pillStyle("#0f172a", "#e2e8f0")} title={String(response)}>
      ✎ "{String(response).slice(0, 24)}{String(response).length > 24 ? "…" : ""}"
    </span>
  );
}

function pillStyle(color, bg) {
  return {
    display: "inline-flex", alignItems: "center", gap: 4,
    padding: "2px 8px", borderRadius: 999,
    background: bg, color, fontSize: 11, fontWeight: 700,
    border: `1px solid ${color}33`,
    fontFamily: "ui-monospace, monospace",
  };
}

export default function DialogHistoryPanel({ canView = false }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("all"); // all|alert|confirm|prompt
  const [search, setSearch] = useState("");
  const history = useDialogHistory();

  const filtered = useMemo(() => {
    let list = history;
    if (filter !== "all") list = list.filter((e) => e.kind === filter);
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter((e) =>
        (e.title || "").toLowerCase().includes(q) ||
        (e.message || "").toLowerCase().includes(q) ||
        String(e.response || "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [history, filter, search]);

  const counts = useMemo(() => {
    const c = { all: history.length, alert: 0, confirm: 0, prompt: 0 };
    history.forEach((e) => { c[e.kind] = (c[e.kind] || 0) + 1; });
    return c;
  }, [history]);

  if (!canView) return null;

  return (
    <>
      {/* Botão flutuante (apenas se há histórico ou usuário abriu uma vez) */}
      <button
        data-testid="dialog-history-fab"
        onClick={() => setOpen(true)}
        title={`Histórico de ações (${history.length})`}
        style={{
          position: "fixed", bottom: 76, right: 20, zIndex: 9000,
          padding: "9px 14px 9px 11px",
          borderRadius: 999,
          background: "linear-gradient(135deg, #0f172a, #1e293b)",
          color: "white", border: "1px solid rgba(255,255,255,.08)",
          cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 7,
          fontSize: 12, fontWeight: 700,
          boxShadow: "0 8px 24px rgba(15,23,42,.32), 0 2px 6px rgba(15,23,42,.18)",
          transition: "transform .15s ease, box-shadow .15s ease",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-2px)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; }}
      >
        <History size={14} strokeWidth={2.2} />
        <span>Ações</span>
        {history.length > 0 && (
          <span data-testid="dialog-history-badge" style={{
            background: "#22c55e", color: "white",
            padding: "0 6px", borderRadius: 999,
            fontSize: 10, fontWeight: 800,
            minWidth: 18, textAlign: "center", lineHeight: "16px",
          }}>{history.length > 99 ? "99+" : history.length}</span>
        )}
      </button>

      {/* Drawer slide-in da direita */}
      {open && (
        <div
          data-testid="dialog-history-drawer-backdrop"
          onClick={() => setOpen(false)}
          style={{
            position: "fixed", inset: 0, zIndex: 9500,
            background: "rgba(15,23,42,.45)",
            backdropFilter: "blur(2px)",
            display: "flex", justifyContent: "flex-end",
          }}
        >
          <div
            data-testid="dialog-history-drawer"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(460px, 95vw)", height: "100%",
              background: "white",
              boxShadow: "-12px 0 40px rgba(15,23,42,.25)",
              display: "flex", flexDirection: "column",
              animation: "dlgHistorySlide .22s cubic-bezier(.16,1,.3,1)",
            }}
          >
            <style>{`
              @keyframes dlgHistorySlide {
                from { transform: translateX(20px); opacity: 0; }
                to   { transform: translateX(0);    opacity: 1; }
              }
            `}</style>

            {/* Header */}
            <div style={{
              padding: "18px 22px 14px",
              borderBottom: "1px solid #e2e8f0",
              display: "flex", alignItems: "flex-start", gap: 10,
            }}>
              <div style={{
                width: 38, height: 38, borderRadius: 10,
                background: "#0f172a", color: "white",
                display: "grid", placeItems: "center", flexShrink: 0,
              }}>
                <History size={18} strokeWidth={2.2} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800, color: "#0f172a", letterSpacing: "-.02em" }}>
                  Histórico de ações
                </h3>
                <div style={{ fontSize: 11.5, color: "#64748b", marginTop: 2 }}>
                  Últimas {history.length} interações de modais nesta sessão
                </div>
              </div>
              <button
                onClick={() => setOpen(false)}
                data-testid="dialog-history-close"
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: "#94a3b8", padding: 6, borderRadius: 8,
                }}
              >
                <X size={18} />
              </button>
            </div>

            {/* Filtros */}
            <div style={{ padding: "12px 22px 10px", borderBottom: "1px solid #f1f5f9" }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "7px 11px",
                background: "#f8fafc", borderRadius: 10,
                border: "1px solid #e2e8f0",
                marginBottom: 8,
              }}>
                <Search size={13} color="#94a3b8" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Buscar mensagem ou resposta..."
                  data-testid="dialog-history-search"
                  style={{
                    flex: 1, border: "none", outline: "none",
                    background: "transparent", fontSize: 12.5,
                    color: "#0f172a",
                  }}
                />
              </div>
              <div style={{ display: "flex", gap: 5 }}>
                {[
                  { id: "all",     label: "Todas" },
                  { id: "confirm", label: "Confirmações" },
                  { id: "alert",   label: "Avisos" },
                  { id: "prompt",  label: "Entradas" },
                ].map((f) => (
                  <button
                    key={f.id}
                    onClick={() => setFilter(f.id)}
                    data-testid={`dialog-history-filter-${f.id}`}
                    style={{
                      flex: 1, padding: "6px 8px", borderRadius: 7,
                      border: filter === f.id ? "1px solid #0f172a" : "1px solid #e2e8f0",
                      background: filter === f.id ? "#0f172a" : "white",
                      color: filter === f.id ? "white" : "#475569",
                      fontSize: 11, fontWeight: 700, cursor: "pointer",
                      display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 4,
                    }}
                  >
                    {f.label}
                    <span style={{ opacity: 0.7, fontSize: 10 }}>
                      {counts[f.id] || 0}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Lista */}
            <div data-testid="dialog-history-list" style={{
              flex: 1, overflowY: "auto",
              padding: "10px 14px 14px",
            }}>
              {filtered.length === 0 ? (
                <div style={{
                  padding: "40px 20px", textAlign: "center",
                  color: "#94a3b8", fontSize: 13,
                }}>
                  <Filter size={28} strokeWidth={1.5} style={{ opacity: 0.4, marginBottom: 6 }} />
                  <div style={{ fontWeight: 700, color: "#64748b", marginBottom: 4 }}>
                    {history.length === 0 ? "Nenhuma ação registrada ainda" : "Nada bate com esse filtro"}
                  </div>
                  <div style={{ fontSize: 11.5 }}>
                    {history.length === 0
                      ? "Todo alert, confirm ou prompt usado aparece aqui."
                      : "Tente outro filtro ou limpe a busca."}
                  </div>
                </div>
              ) : (
                filtered.map((entry) => {
                  const meta = KIND_META[entry.kind] || KIND_META.alert;
                  const Icon = meta.icon;
                  return (
                    <div
                      key={entry.id}
                      data-testid={`dialog-history-row-${entry.id}`}
                      style={{
                        background: "white",
                        border: "1px solid #e2e8f0",
                        borderRadius: 10,
                        padding: "10px 12px",
                        marginBottom: 6,
                        borderLeft: `3px solid ${meta.color}`,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5 }}>
                        <Icon size={13} strokeWidth={2.2} color={meta.color} />
                        <strong style={{ fontSize: 12.5, color: "#0f172a", flex: 1, minWidth: 0,
                                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {entry.title}
                        </strong>
                        <span style={{ fontSize: 10.5, color: "#94a3b8", flexShrink: 0,
                                        fontFamily: "ui-monospace, monospace" }}>
                          {fmtTime(entry.ts)}
                        </span>
                      </div>
                      <div style={{
                        fontSize: 12, color: "#475569", lineHeight: 1.45,
                        marginBottom: 6,
                        display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical",
                        overflow: "hidden",
                        whiteSpace: "pre-wrap",
                      }}>
                        {entry.message}
                      </div>
                      <ResponsePill kind={entry.kind} response={entry.response} />
                    </div>
                  );
                })
              )}
            </div>

            {/* Footer */}
            {history.length > 0 && (
              <div style={{
                padding: "12px 22px",
                borderTop: "1px solid #e2e8f0",
                display: "flex", justifyContent: "space-between", alignItems: "center",
                background: "#f8fafc",
              }}>
                <div style={{ fontSize: 11, color: "#64748b" }}>
                  {history.length} / 100 em buffer
                </div>
                <button
                  onClick={clearDialogHistory}
                  data-testid="dialog-history-clear"
                  style={{
                    padding: "7px 12px", borderRadius: 8,
                    border: "1px solid #fca5a5",
                    background: "white", color: "#dc2626",
                    fontSize: 11.5, fontWeight: 700, cursor: "pointer",
                    display: "inline-flex", alignItems: "center", gap: 5,
                  }}
                >
                  <Trash2 size={12} />
                  Limpar histórico
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
