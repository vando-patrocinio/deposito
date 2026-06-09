/* StokAiReviewPanel — iter215am
 * Painel de revisão IA: equipamentos (ONTs) retirados por foto que
 * estão aguardando aprovação do gestor. Mostra foto + análise IA
 * (Claude Sonnet 4.6) lado a lado, com 3 botões de decisão:
 *  • Aprovar reaproveitamento (fica com técnico como retirada)
 *  • Devolver à empresa (volta pro estoque central)
 *  • Sucatear (defeito definitivo)
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, RotateCcw, Trash2, AlertTriangle, Cpu, User } from "lucide-react";

import { api } from "@/api";

const STATUS_PILL = {
  pending_ai_review: { bg: "#fef3c7", color: "#854d0e",
                         label: "Aguardando IA" },
  pending_human_review: { bg: "#dbeafe", color: "#1e3a8a",
                            label: "IA falhou · revisar manual" },
  bloqueado_defeito: { bg: "#fee2e2", color: "#7f1d1d",
                        label: "Bloqueado · defeito" },
};

function Pill({ status }) {
  const s = STATUS_PILL[status]
    || { bg: "#e2e8f0", color: "#475569", label: status };
  return (
    <span style={{ display: "inline-block", padding: "2px 8px",
                    borderRadius: 999, background: s.bg, color: s.color,
                    fontSize: 11, fontWeight: 800,
                    fontFamily: "Inter, sans-serif" }}>
      {s.label}
    </span>
  );
}

export default function StokAiReviewPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null); // id em processamento
  const busyRef = useRef(null);
  const [edits, setEdits] = useState({});
  const [msg, setMsg] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api._client.get("/stok/ai-review/pending");
      setItems(r.data?.items || []);
    } catch (e) {
      setMsg({ type: "err",
                 text: e?.response?.data?.detail || "Falha ao carregar" });
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const decide = useCallback(async (item, decision) => {
    if (busyRef.current) return;
    busyRef.current = item.id;
    setBusy(item.id); setMsg(null);
    const local = edits[item.id] || {};
    try {
      const payload = {
        decision,
        note: local.note || null,
        final_sn: local.sn || null,
        final_mac: local.mac || null,
        final_model: local.model || null,
      };
      const r = await api._client.post(
        `/stok/ai-review/${item.id}/decision`, payload);
      setMsg({ type: "ok",
                 text: `Decisão aplicada — novo status: ${r.data?.status}` });
      setEdits((e) => { const c = { ...e }; delete c[item.id]; return c; });
      await load();
      setTimeout(() => setMsg(null), 3500);
    } catch (e) {
      setMsg({ type: "err",
                 text: e?.response?.data?.detail || "Falha ao salvar" });
    } finally { busyRef.current = null; setBusy(null); }
  }, [edits, load]);

  const setEdit = (id, key, val) =>
    setEdits((e) => ({ ...e, [id]: { ...(e[id] || {}), [key]: val } }));

  const empty = !loading && items.length === 0;
  const headerKpis = useMemo(() => {
    const c = items.reduce((acc, it) => {
      acc[it.status] = (acc[it.status] || 0) + 1; return acc;
    }, {});
    return c;
  }, [items]);

  return (
    <div data-testid="stok-ai-review-panel"
          style={{ fontFamily: "Inter, sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center",
                     justifyContent: "space-between", marginBottom: 14,
                     gap: 10, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 800, margin: 0,
                         color: "var(--text-primary, #0f172a)",
                         display: "flex", alignItems: "center", gap: 8 }}>
            <Cpu size={18} color="var(--primary, #4b1d7a)" />
            Revisão IA · ONTs retiradas por foto
          </h2>
          <p style={{ fontSize: 12, color: "#64748b", marginTop: 4,
                       maxWidth: 700, lineHeight: 1.5 }}>
            Equipamentos retirados em OS de retirada/troca sem SN no
            SmartOLT. A foto foi analisada pela IA (Claude Sonnet 4.6).
            Confira os dados extraídos e decida o destino do item.
          </p>
        </div>
        <button
          data-testid="stok-ai-review-reload"
          onClick={load} disabled={loading}
          style={{ padding: "8px 14px", border: "1px solid #cbd5e1",
                    borderRadius: 10, background: "white", fontSize: 12,
                    fontWeight: 700, cursor: "pointer", color: "#0f172a",
                    fontFamily: "inherit" }}>
          {loading ? "Carregando…" : "Atualizar"}
        </button>
      </div>

      {Object.keys(headerKpis).length > 0 && (
        <div style={{ display: "flex", gap: 8, marginBottom: 14,
                       flexWrap: "wrap" }}>
          {Object.entries(headerKpis).map(([k, v]) => (
            <div key={k} style={{ padding: "6px 10px", borderRadius: 8,
                                    background: "var(--surface-alt, #f8fafc)",
                                    border: "1px solid #e2e8f0",
                                    fontSize: 11.5, fontWeight: 700,
                                    color: "#475569" }}>
              <Pill status={k} />{" "}
              <span style={{ marginLeft: 4 }}>{v}</span>
            </div>
          ))}
        </div>
      )}

      {msg && (
        <div data-testid="stok-ai-review-msg"
              style={{ marginBottom: 12, padding: "8px 12px",
                        borderRadius: 8, fontSize: 12.5, fontWeight: 700,
                        background: msg.type === "ok" ? "#dcfce7" : "#fee2e2",
                        color: msg.type === "ok" ? "#166534" : "#991b1b",
                        border: `1px solid ${msg.type === "ok"
                                                ? "#86efac" : "#fca5a5"}` }}>
          {msg.text}
        </div>
      )}

      {empty && (
        <div data-testid="stok-ai-review-empty"
              style={{ padding: 24, borderRadius: 12,
                        background: "var(--surface-alt, #f8fafc)",
                        border: "1px dashed #cbd5e1",
                        textAlign: "center", color: "#64748b",
                        fontSize: 13 }}>
          Nenhum equipamento aguardando revisão. Quando técnicos
          retirarem ONTs sem SN no SmartOLT, os itens aparecem aqui.
        </div>
      )}

      <div style={{ display: "grid", gap: 14 }}>
        {items.map((it) => {
          const ai = it.ai_review_result || {};
          const e = edits[it.id] || {};
          const isBusy = busy === it.id;
          return (
            <div key={it.id}
                  data-testid={`stok-ai-review-item-${it.id}`}
                  style={{ display: "grid",
                            gridTemplateColumns: "260px 1fr",
                            gap: 16, padding: 14,
                            background: "white",
                            border: "1px solid #e2e8f0",
                            borderRadius: 14,
                            boxShadow: "0 1px 2px rgba(15,23,42,.04)" }}>
              <div>
                {it.photo_sample ? (
                  <img src={it.photo_sample} alt="ONT retirada"
                        style={{ width: "100%", borderRadius: 10,
                                  border: "1px solid #cbd5e1",
                                  objectFit: "cover", aspectRatio: "1/1",
                                  background: "#f1f5f9" }} />
                ) : (
                  <div style={{ width: "100%", aspectRatio: "1/1",
                                  background: "#f1f5f9",
                                  border: "1px dashed #cbd5e1",
                                  borderRadius: 10,
                                  display: "flex", alignItems: "center",
                                  justifyContent: "center",
                                  color: "#94a3b8", fontSize: 12 }}>
                    sem foto
                  </div>
                )}
                <div style={{ marginTop: 8, fontSize: 11, color: "#64748b",
                                 display: "flex", alignItems: "center",
                                 gap: 4 }}>
                  <User size={12} />
                  <strong style={{ color: "#0f172a" }}>
                    {it.technician_name || "Técnico"}
                  </strong>
                </div>
                <div style={{ marginTop: 4, fontSize: 10.5,
                                 color: "#94a3b8" }}>
                  {it.withdrawn_from_client_name
                    ? `Cliente: ${it.withdrawn_from_client_name}`
                    : "Cliente não informado"}
                </div>
                <div style={{ marginTop: 2, fontSize: 10.5,
                                 color: "#94a3b8" }}>
                  {(it.created_at || "").replace("T", " ").slice(0, 16)}
                </div>
              </div>

              <div>
                <div style={{ display: "flex", alignItems: "center",
                               gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                  <Pill status={it.status} />
                  {it.is_defective && (
                    <span style={{ display: "inline-flex",
                                     alignItems: "center", gap: 4,
                                     padding: "2px 8px", borderRadius: 999,
                                     background: "#fee2e2",
                                     color: "#7f1d1d",
                                     fontSize: 11, fontWeight: 800 }}>
                      <AlertTriangle size={11} />
                      Técnico marcou defeito
                    </span>
                  )}
                  {it.ai_review_pending && (
                    <span style={{ fontSize: 11, color: "#64748b" }}>
                      · IA processando…
                    </span>
                  )}
                </div>

                {ai && Object.keys(ai).length > 0 && (
                  <div style={{ padding: 10, borderRadius: 10,
                                  background: "#f8fafc",
                                  border: "1px solid #e2e8f0",
                                  fontSize: 12, marginBottom: 12 }}>
                    <div style={{ fontWeight: 800, color: "#0f172a",
                                    marginBottom: 6 }}>
                      Análise IA · Claude Sonnet 4.6
                    </div>
                    <div style={{ display: "grid",
                                    gridTemplateColumns: "repeat(auto-fill,minmax(140px,1fr))",
                                    gap: 6, color: "#475569" }}>
                      <div><strong>SN:</strong> {ai.serial_number || "—"}</div>
                      <div><strong>MAC:</strong> {ai.mac_address || "—"}</div>
                      <div><strong>Marca:</strong> {ai.brand || "—"}</div>
                      <div><strong>Modelo:</strong> {ai.model || "—"}</div>
                      <div><strong>Condição:</strong> {ai.condition || "—"}</div>
                      <div><strong>Qualidade:</strong> {ai.quality_score ?? "—"}/100</div>
                    </div>
                    {ai.reasoning && (
                      <div style={{ marginTop: 6, fontStyle: "italic",
                                      color: "#64748b" }}>
                        “{ai.reasoning}”
                      </div>
                    )}
                  </div>
                )}

                <div style={{ display: "grid",
                                gridTemplateColumns: "repeat(3,1fr)",
                                gap: 8, marginBottom: 8 }}>
                  <input data-testid={`stok-ai-sn-${it.id}`}
                          value={e.sn ?? (it.sn || "")}
                          onChange={(ev) => setEdit(it.id, "sn",
                              ev.target.value.toUpperCase())}
                          placeholder="SN final"
                          style={inp} />
                  <input data-testid={`stok-ai-mac-${it.id}`}
                          value={e.mac ?? (it.mac || "")}
                          onChange={(ev) => setEdit(it.id, "mac",
                              ev.target.value.toUpperCase())}
                          placeholder="MAC final"
                          style={inp} />
                  <input data-testid={`stok-ai-model-${it.id}`}
                          value={e.model ?? (it.model || "")}
                          onChange={(ev) => setEdit(it.id, "model",
                              ev.target.value)}
                          placeholder="Modelo final"
                          style={inp} />
                </div>
                <input data-testid={`stok-ai-note-${it.id}`}
                        value={e.note || ""}
                        onChange={(ev) => setEdit(it.id, "note",
                            ev.target.value.slice(0, 300))}
                        placeholder="Nota da revisão (opcional)…"
                        style={{ ...inp, width: "100%", marginBottom: 10 }} />

                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button
                    data-testid={`stok-ai-approve-${it.id}`}
                    disabled={isBusy || it.is_defective}
                    onClick={() => decide(it, "approve_reuse")}
                    title={it.is_defective
                      ? "Item marcado como defeito não pode ser aprovado"
                      : "Mantém com o técnico como retirado (reaproveitar)"}
                    style={btnGreen(it.is_defective || isBusy)}>
                    <CheckCircle2 size={14} /> Aprovar reaproveitar
                  </button>
                  <button
                    data-testid={`stok-ai-return-${it.id}`}
                    disabled={isBusy}
                    onClick={() => decide(it, "return_to_company")}
                    style={btnBlue(isBusy)}>
                    <RotateCcw size={14} /> Devolver à empresa
                  </button>
                  <button
                    data-testid={`stok-ai-scrap-${it.id}`}
                    disabled={isBusy}
                    onClick={() => {
                      if (!window.confirm(
                        "Confirmar SUCATEAMENTO desse equipamento? "
                        + "Essa ação marca o item como inutilizável."))
                        return;
                      decide(it, "scrap_defect");
                    }}
                    style={btnRed(isBusy)}>
                    <Trash2 size={14} /> Sucatear defeito
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const inp = {
  padding: "8px 10px", border: "1px solid #cbd5e1", borderRadius: 8,
  fontSize: 12.5, fontFamily: "Inter, sans-serif",
  boxSizing: "border-box", color: "#0f172a", background: "white",
};

const baseBtn = (disabled, bg, fg) => ({
  display: "inline-flex", alignItems: "center", gap: 6,
  padding: "8px 14px", borderRadius: 10, border: "none",
  background: bg, color: fg, fontSize: 12.5, fontWeight: 800,
  cursor: disabled ? "not-allowed" : "pointer",
  opacity: disabled ? 0.6 : 1, fontFamily: "inherit",
});
const btnGreen = (d) => baseBtn(d, "var(--success, #237a4b)", "white");
const btnBlue = (d) => baseBtn(d, "var(--primary, #4b1d7a)", "white");
const btnRed = (d) => baseBtn(d, "var(--danger, #b42318)", "white");
