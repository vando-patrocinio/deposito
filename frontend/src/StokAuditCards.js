import React, { useEffect, useState } from "react";
import { api } from "@/api";

/**
 * Reset granular + Relatório de quebra de estoque para Auditor.
 *
 * - `GranularResetButton`: modal com seletores Escopo (item|colaborador|praça)
 *   + dropdown do target + checkboxes ONTs/Insumos + confirm input.
 * - `ShrinkageReportCard`: consome `/api/stok/admin/shrinkage-report` e
 *   exibe a quebra por insumo + por ONTs (entradas − consumido − saldo).
 *
 * Ambos só renderizam para `role=auditor` (gated no caller).
 */
export function GranularResetButton({ technicians, pracas,
                                            consumables, onDone }) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState("item");
  const [targetId, setTargetId] = useState("");
  const [resetOnts, setResetOnts] = useState(true);
  const [resetCons, setResetCons] = useState(true);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  const targets =
    scope === "item" ? (consumables || []).map((c) => ({ id: c.id, name: `${c.name} (${c.unit})` }))
    : scope === "collaborator" ? (technicians || []).map((c) => ({ id: c.id, name: c.name }))
    : (pracas || []).map((p) => ({ id: p.id, name: p.name }));

  useEffect(() => { setTargetId(""); }, [scope]);

  const submit = async () => {
    setErr(""); setBusy(true);
    try {
      const r = await api.stokAdminResetGranular({
        confirm, scope, target_id: targetId,
        reset_onts: scope !== "item" ? resetOnts : false,
        reset_consumables: scope === "item" ? true : resetCons,
      });
      setResult(r);
      onDone?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao zerar.");
    } finally { setBusy(false); }
  };

  return (
    <>
      <button data-testid="granular-reset-btn"
              onClick={() => {
                setOpen(true); setResult(null); setErr("");
                setConfirm(""); setTargetId("");
              }}
              style={{
                padding: "8px 14px", borderRadius: 8, border: 0,
                background: "linear-gradient(135deg,#f59e0b,#b45309)",
                color: "#fff", fontSize: 13, fontWeight: 800,
                cursor: "pointer", display: "inline-flex",
                gap: 6, alignItems: "center",
              }}>
        🎯 Zerar por escopo
      </button>
      {open && (
        <div data-testid="granular-reset-modal"
              style={{
                position: "fixed", inset: 0, zIndex: 9999,
                background: "rgba(15,23,42,0.7)",
                display: "flex", alignItems: "center",
                justifyContent: "center", padding: 20,
              }}>
          <div style={{
            background: "#fff", borderRadius: 12, padding: 22,
            width: "min(94vw, 540px)",
            boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
          }}>
            <div style={{ fontSize: 17, fontWeight: 800, color: "#b45309",
                            marginBottom: 8 }}>
              🎯 Zerar Estoque por Escopo
            </div>
            {!result && (
              <>
                <div style={{ fontSize: 13, color: "#475569",
                                lineHeight: 1.5, marginBottom: 12 }}>
                  Apaga o estoque <b>apenas do alvo selecionado</b>.
                  Ação registrada em <code>stok_admin_log</code> com seu
                  e-mail e horário.
                </div>

                <label style={lbl}>Escopo</label>
                <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                  {[
                    { id: "item", label: "Insumo (item)" },
                    { id: "collaborator", label: "Colaborador" },
                    { id: "praca", label: "Praça" },
                  ].map((s) => (
                    <button key={s.id}
                              data-testid={`granular-scope-${s.id}`}
                              onClick={() => setScope(s.id)}
                              style={{
                                flex: 1, padding: "8px 10px",
                                borderRadius: 8,
                                border: scope === s.id
                                  ? "2px solid #b45309" : "1px solid #cbd5e1",
                                background: scope === s.id ? "#fef3c7" : "white",
                                color: scope === s.id ? "#92400e" : "#475569",
                                fontSize: 12, fontWeight: 700,
                                cursor: "pointer",
                              }}>
                      {s.label}
                    </button>
                  ))}
                </div>

                <label style={lbl}>Alvo</label>
                <select data-testid="granular-target"
                          value={targetId}
                          onChange={(e) => setTargetId(e.target.value)}
                          style={selStyle}>
                  <option value="">— Selecione —</option>
                  {targets.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>

                {scope !== "item" && (
                  <div style={{ marginTop: 12, padding: 10, borderRadius: 8,
                                  background: "#f8fafc",
                                  border: "1px solid #e2e8f0" }}>
                    <label style={chkLbl}>
                      <input type="checkbox" checked={resetOnts}
                              onChange={(e) => setResetOnts(e.target.checked)}
                              data-testid="granular-reset-onts" />
                      Apagar ONTs vinculadas
                    </label>
                    <label style={chkLbl}>
                      <input type="checkbox" checked={resetCons}
                              onChange={(e) => setResetCons(e.target.checked)}
                              data-testid="granular-reset-cons" />
                      Zerar insumos
                    </label>
                  </div>
                )}

                <label style={{ ...lbl, marginTop: 12 }}>
                  Digite <code style={{ background: "#fee2e2",
                                            padding: "0 4px",
                                            borderRadius: 4 }}>ZERAR ESTOQUE</code>{" "}
                  para confirmar:
                </label>
                <input data-testid="granular-confirm-input"
                        value={confirm}
                        onChange={(e) => setConfirm(e.target.value)}
                        placeholder="ZERAR ESTOQUE"
                        style={selStyle} />

                {err && (
                  <div style={{ color: "#dc2626", marginTop: 8,
                                  fontSize: 12 }}>{err}</div>
                )}

                <div style={{ display: "flex", gap: 8, marginTop: 14,
                                justifyContent: "flex-end" }}>
                  <button onClick={() => setOpen(false)}
                            style={btnGhost}
                            data-testid="granular-cancel">Cancelar</button>
                  <button onClick={submit}
                            data-testid="granular-confirm-btn"
                            disabled={busy || !targetId
                                          || confirm.toUpperCase().trim() !== "ZERAR ESTOQUE"}
                            style={{
                              ...btnDanger,
                              background: (busy || !targetId
                                              || confirm.toUpperCase().trim() !== "ZERAR ESTOQUE")
                                ? "#cbd5e1"
                                : "linear-gradient(135deg,#b45309,#92400e)",
                              cursor: busy ? "wait" : "pointer",
                            }}>
                    {busy ? "Zerando…" : "Confirmar Reset"}
                  </button>
                </div>
              </>
            )}
            {result && (
              <div data-testid="granular-result"
                    style={{ marginTop: 4 }}>
                <div style={{ fontSize: 14, color: "#065f46",
                                fontWeight: 700, marginBottom: 8 }}>
                  ✓ Reset executado em <b>{result.target_label}</b>
                </div>
                <pre style={{ background: "#f1f5f9", padding: 10,
                                borderRadius: 8, fontSize: 11,
                                overflowX: "auto" }}>
                  {JSON.stringify(result.deleted, null, 2)}
                </pre>
                <button onClick={() => setOpen(false)}
                          style={btnSec} data-testid="granular-close-btn">
                  Fechar
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}


export function ShrinkageReportCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [showClearModal, setShowClearModal] = useState(false);
  const [clearText, setClearText] = useState("");
  const [clearReason, setClearReason] = useState("Ajuste auditor");
  const [clearing, setClearing] = useState(false);

  const [forbidden, setForbidden] = useState(false);

  const reload = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.stokShrinkageReport();
      setData(r);
    } catch (e) {
      const status = e?.response?.status;
      // Para non-auditors o backend retorna 403. Não vazamos info nem
      // exibimos erro — apenas escondemos o card silenciosamente.
      if (status === 403) {
        setForbidden(true);
      } else {
        setErr(e?.response?.data?.detail || e.message);
      }
    } finally { setLoading(false); }
  };
  useEffect(() => { reload(); }, []);

  // Se não tem permissão (403), não renderiza nada — o gate visual fica
  // 100% do lado do EstoquePanel via role check, mas adicionamos defesa
  // em profundidade aqui também.
  if (forbidden) return null;

  const onClearShrinkage = async () => {
    if (clearText.trim().toUpperCase() !== "ZERAR QUEBRA") {
      alert("Digite exatamente: ZERAR QUEBRA");
      return;
    }
    setClearing(true);
    try {
      const r = await api.stokClearShrinkage({
        confirm: "ZERAR QUEBRA",
        include_onts: true,
        include_consumables: true,
        reason: clearReason || "Ajuste auditor",
      });
      alert(`Quebra zerada!\n· Insumos compensados: ${r.consumables_adjustments?.length || 0}\n· Unidades: ${r.consumables_total_units || 0}\n· ONTs: ${r.onts_compensated || 0}`);
      setShowClearModal(false);
      setClearText("");
      reload();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setClearing(false);
    }
  };

  const consumables = data?.consumables || [];
  const totals = data?.consumables_totals || {};
  const onts = data?.onts || {};
  const withShrink = consumables.filter((c) => c.shrinkage > 0);

  return (
    <div data-testid="shrinkage-report-card"
          style={{
            background: "#fff", border: "1px solid #e2e8f0",
            borderRadius: 12, padding: 16, marginBottom: 14,
          }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 12,
                      flexWrap: "wrap", gap: 8 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                          color: "#0f172a" }}>
            📉 Quebra de Estoque
          </h3>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "#64748b" }}>
            Entradas − consumido em OS − saldo atual. Se positivo,
            o item sumiu ou não foi rastreado.
          </p>
        </div>
        <button data-testid="shrinkage-refresh"
                  onClick={reload} disabled={loading}
                  style={btnSec}>
          {loading ? "Carregando…" : "⟳ Recarregar"}
        </button>
        <button data-testid="clear-shrinkage-btn"
                  onClick={() => setShowClearModal(true)}
                  disabled={loading || (data && (data.consumables_totals?.shrinkage || 0) === 0 && (data.onts?.shrinkage || 0) === 0)}
                  style={{
                    padding: "8px 14px", borderRadius: 8, border: 0,
                    background: "linear-gradient(135deg,#dc2626,#b91c1c)",
                    color: "#fff", fontWeight: 700, fontSize: 12,
                    cursor: "pointer",
                  }}>
          ⚠ Zerar Quebra
        </button>
      </div>

      {err && <div style={{ color: "#dc2626", fontSize: 13 }}>Erro: {err}</div>}

      {data && (
        <>
          <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(4, 1fr)",
                          gap: 8, marginBottom: 14 }}>
            <KpiBox label="Total entradas"
                       value={totals.entries ?? "—"} color="#1e293b" />
            <KpiBox label="Total consumido"
                       value={totals.consumed ?? "—"} color="#0d9488" />
            <KpiBox label="Saldo atual"
                       value={totals.current_balance ?? "—"} color="#0369a1" />
            <KpiBox label="Quebra total"
                       value={totals.shrinkage ?? "—"}
                       color={totals.shrinkage > 0 ? "#b91c1c" : "#15803d"} />
          </div>

          {/* Tabela por insumo */}
          <table data-testid="shrinkage-table"
                  style={{ width: "100%", borderCollapse: "collapse",
                              fontSize: 12, marginBottom: 14 }}>
            <thead>
              <tr style={{ background: "#f8fafc",
                              borderBottom: "1px solid #e2e8f0" }}>
                <th style={th}>Insumo</th>
                <th style={th}>Entradas</th>
                <th style={th}>Consumido</th>
                <th style={th}>Saldo</th>
                <th style={th}>Quebra</th>
                <th style={th}>%</th>
              </tr>
            </thead>
            <tbody>
              {consumables.map((c) => (
                <tr key={c.item_id}
                    data-testid={`shrink-row-${c.item_id}`}
                    style={{
                      borderBottom: "1px solid #f1f5f9",
                      background: c.shrinkage > 0 ? "#fef2f2" : "white",
                    }}>
                  <td style={td}>{c.name}</td>
                  <td style={tdN}>{c.entries} {c.unit}</td>
                  <td style={tdN}>{c.consumed} {c.unit}</td>
                  <td style={tdN}>{c.current_balance} {c.unit}</td>
                  <td style={{ ...tdN, color: c.shrinkage > 0 ? "#b91c1c" : "#15803d",
                                  fontWeight: 800 }}>
                    {c.shrinkage} {c.unit}
                  </td>
                  <td style={{ ...tdN, color: c.shrinkage_pct >= 10 ? "#b91c1c" : "#64748b" }}>
                    {c.shrinkage_pct}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Bloco ONT */}
          <div style={{ background: "#f8fafc", padding: 10,
                          borderRadius: 8, fontSize: 12.5,
                          border: "1px solid #e2e8f0" }}>
            <strong style={{ color: "#0f172a", fontSize: 13 }}>
              📦 ONTs
            </strong>
            <div style={{ display: "grid",
                            gridTemplateColumns: "repeat(4, 1fr)",
                            gap: 6, marginTop: 6 }}>
              <Mini label="Entradas" value={onts.total_in} />
              <Mini label="Em estoque" value={onts.current_count} />
              <Mini label="Com clientes" value={onts.with_clients} />
              <Mini label="Quebra"
                      value={onts.shrinkage}
                      color={onts.shrinkage > 0 ? "#b91c1c" : "#15803d"} />
            </div>
          </div>

          {withShrink.length > 0 && (
            <div data-testid="shrinkage-summary"
                  style={{ marginTop: 12, padding: 10,
                              background: "#fef2f2", borderRadius: 8,
                              border: "1px solid #fecaca",
                              color: "#991b1b", fontSize: 12 }}>
              ⚠ <strong>{withShrink.length}</strong> insumo(s) com quebra
              detectada. Geralmente significa: lançamentos incompletos no
              fechamento de OS, ONTs/insumos não baixados, ou perda física.
            </div>
          )}
        </>
      )}

      {/* Modal: Zerar Quebra */}
      {showClearModal && (
        <div data-testid="clear-shrinkage-modal" style={{
          position: "fixed", inset: 0, zIndex: 9999,
          background: "rgba(15,23,42,.55)",
          display: "grid", placeItems: "center", padding: 16,
        }}>
          <div style={{
            background: "white", borderRadius: 14, padding: 22,
            maxWidth: 480, width: "100%",
            boxShadow: "0 20px 50px rgba(0,0,0,.25)",
          }}>
            <div style={{ fontWeight: 800, fontSize: 17, color: "#0f172a", marginBottom: 6 }}>
              ⚠ Zerar Quebra de Estoque
            </div>
            <p style={{ fontSize: 13, color: "#475569", marginBottom: 12, lineHeight: 1.5 }}>
              Esta ação <strong>compensa</strong> toda a quebra atual com
              lançamentos de ajuste em <code>stok_history</code>. O histórico
              original é <strong>preservado</strong>, e o ajuste fica registrado
              em <code>stok_admin_log</code> com seu e-mail e data.
            </p>
            {data && (
              <div style={{
                background: "#fef2f2", border: "1px solid #fecaca",
                borderRadius: 8, padding: 10, fontSize: 12, color: "#7f1d1d",
                marginBottom: 12,
              }}>
                <div><strong>Quebra atual:</strong></div>
                <div>· Insumos: <strong>{data.consumables_totals?.shrinkage || 0}</strong> unidades</div>
                <div>· ONTs: <strong>{data.onts?.shrinkage || 0}</strong> ONTs</div>
              </div>
            )}
            <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: "#475569" }}>
              Motivo (opcional, vai pro log)
            </label>
            <input
              data-testid="clear-shrinkage-reason"
              value={clearReason}
              onChange={(e) => setClearReason(e.target.value)}
              placeholder="Ex: Conferência mensal — perda confirmada"
              style={{
                width: "100%", padding: "8px 10px", marginBottom: 10,
                border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13,
              }}
            />
            <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: "#7f1d1d" }}>
              Digite exatamente <code>ZERAR QUEBRA</code> para confirmar:
            </label>
            <input
              data-testid="clear-shrinkage-confirm"
              value={clearText}
              onChange={(e) => setClearText(e.target.value)}
              placeholder="ZERAR QUEBRA"
              style={{
                width: "100%", padding: "10px 12px", marginBottom: 14,
                border: "1.5px solid #dc2626", borderRadius: 8,
                fontSize: 14, fontWeight: 700, textTransform: "uppercase",
              }}
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button data-testid="clear-shrinkage-cancel"
                      onClick={() => { setShowClearModal(false); setClearText(""); }}
                      style={{
                        padding: "9px 14px", borderRadius: 8,
                        border: "1px solid #e2e8f0", background: "white",
                        color: "#0f172a", fontSize: 13, cursor: "pointer",
                      }}>
                Cancelar
              </button>
              <button data-testid="clear-shrinkage-confirm-btn"
                      disabled={clearing || clearText.trim().toUpperCase() !== "ZERAR QUEBRA"}
                      onClick={onClearShrinkage}
                      style={{
                        padding: "9px 16px", borderRadius: 8, border: 0,
                        background: (clearing || clearText.trim().toUpperCase() !== "ZERAR QUEBRA")
                          ? "#94a3b8"
                          : "linear-gradient(135deg,#dc2626,#b91c1c)",
                        color: "#fff", fontWeight: 800, fontSize: 13,
                        cursor: clearing ? "wait" : "pointer",
                      }}>
                {clearing ? "Zerando…" : "Confirmar Zerar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


function KpiBox({ label, value, color }) {
  return (
    <div style={{ background: "#f8fafc",
                    border: "1px solid #e2e8f0", borderRadius: 8,
                    padding: 10, textAlign: "center" }}>
      <div style={{ fontSize: 18, fontWeight: 800,
                       color: color || "#0f172a" }}>{value}</div>
      <div style={{ fontSize: 11, color: "#64748b",
                       fontWeight: 600, marginTop: 2 }}>{label}</div>
    </div>
  );
}
function Mini({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 800,
                       color: color || "#0f172a" }}>{value ?? "—"}</div>
      <div style={{ fontSize: 10, color: "#64748b" }}>{label}</div>
    </div>
  );
}

const lbl = { display: "block", fontSize: 12, fontWeight: 700,
                color: "#334155", marginTop: 6, marginBottom: 4 };
const selStyle = {
  width: "100%", padding: "8px 10px", borderRadius: 8,
  border: "1px solid #cbd5e1", fontSize: 13,
  boxSizing: "border-box",
};
const chkLbl = { display: "flex", gap: 6, alignItems: "center",
                    fontSize: 12, color: "#475569", marginBottom: 4 };
const btnSec = {
  padding: "8px 14px", borderRadius: 8,
  border: "1px solid #cbd5e1", background: "white",
  fontSize: 13, fontWeight: 700, cursor: "pointer", color: "#334155",
};
const btnGhost = {
  padding: "8px 14px", borderRadius: 8,
  border: "1px solid #cbd5e1", background: "white",
  fontSize: 13, fontWeight: 700, cursor: "pointer", color: "#64748b",
};
const btnDanger = {
  padding: "8px 14px", borderRadius: 8, border: 0,
  color: "white", fontSize: 13, fontWeight: 800,
};
const th = { textAlign: "left", padding: "8px 10px",
                fontSize: 11, fontWeight: 700,
                color: "#475569", textTransform: "uppercase" };
const td = { padding: "8px 10px", color: "#1e293b" };
const tdN = { padding: "8px 10px", color: "#1e293b",
                  textAlign: "right", fontVariantNumeric: "tabular-nums" };
