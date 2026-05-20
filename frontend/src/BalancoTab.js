/**
 * BalancoTab — Balanço de Estoque (cycle counting / stock reconciliation).
 *
 * Implementa best-practices de inventory counting:
 *  - Escopo flexível: Empresa | Praça | Técnico
 *  - Modo cego (blind) ou aberto (open) — escolhido pelo usuário
 *  - Scan-first UX para ONTs (auto-focus, Enter submit)
 *  - Contagem de insumos numa mesma sessão
 *  - Variance summary (matched/missing/extra) + accuracy %
 *  - Separation of duties: gestor conta/finaliza; admin/super aprova
 *  - Histórico completo e auditável
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api";
import { toast } from "sonner";

const SCOPES = [
  { id: "empresa", label: "Empresa (estoque geral)", icon: "🏢" },
  { id: "praca", label: "Praça/Filial", icon: "📦" },
  { id: "tecnico", label: "Técnico", icon: "👤" },
];

const STATUS_META = {
  counting: { label: "Em contagem", bg: "#fef3c7", fg: "#92400e" },
  pending_approval: { label: "Aguardando aprovação", bg: "#dbeafe", fg: "#1e40af" },
  approved: { label: "Aprovado", bg: "#dcfce7", fg: "#065f46" },
  cancelled: { label: "Cancelado", bg: "#f1f5f9", fg: "#475569" },
};

function fmtDt(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch (e) { return iso; }
}

// ============================================================
// Wizard: criar novo balanço
// ============================================================
function NewBalancoWizard({ pracas, techs, onCreated, onCancel }) {
  const [step, setStep] = useState(1);
  const [scope, setScope] = useState("praca");
  const [scopeId, setScopeId] = useState("");
  const [mode, setMode] = useState("blind");
  const [includeCons, setIncludeCons] = useState(true);
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);

  const canConfirm = scope === "empresa" || !!scopeId;

  const submit = async () => {
    setCreating(true);
    try {
      const data = await api.balancoStart({
        scope_type: scope,
        scope_id: scope === "empresa" ? null : scopeId,
        mode, include_consumables: includeCons,
        note: note || null,
      });
      toast.success(`Balanço ${data.id} iniciado`);
      onCreated(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || e.message);
    } finally { setCreating(false); }
  };

  return (
    <div data-testid="balanco-wizard" style={{
      background: "white", border: "1px solid #cbd5e1",
      borderRadius: 12, padding: 18, marginBottom: 16,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>
          🆕 Novo Balanço · passo {step} de 2
        </h3>
        <button onClick={onCancel} data-testid="balanco-wizard-cancel"
                  style={{ background: "none", border: "none",
                            fontSize: 20, cursor: "pointer", color: "#94a3b8" }}>×</button>
      </div>

      {step === 1 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", marginBottom: 6 }}>
            Escopo
          </div>
          <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(3, 1fr)",
                          gap: 8, marginBottom: 14 }}>
            {SCOPES.map((s) => (
              <button key={s.id}
                        type="button"
                        data-testid={`balanco-scope-${s.id}`}
                        onClick={() => { setScope(s.id); setScopeId(""); }}
                        style={{
                          padding: 10, borderRadius: 8,
                          background: scope === s.id ? "#0f766e" : "white",
                          color: scope === s.id ? "white" : "#0f172a",
                          border: scope === s.id
                            ? "1px solid #0f766e" : "1px solid #cbd5e1",
                          cursor: "pointer", fontWeight: 700, fontSize: 12,
                          textAlign: "left",
                        }}>
                <div style={{ fontSize: 18 }}>{s.icon}</div>
                <div>{s.label}</div>
              </button>
            ))}
          </div>

          {scope !== "empresa" && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                              textTransform: "uppercase", marginBottom: 6 }}>
                {scope === "praca" ? "Praça/Filial" : "Técnico"}
              </div>
              <select
                data-testid="balanco-scope-id"
                value={scopeId}
                onChange={(e) => setScopeId(e.target.value)}
                style={{
                  width: "100%", padding: "8px 10px",
                  border: "1px solid #cbd5e1", borderRadius: 8,
                  fontSize: 13,
                }}>
                <option value="">Selecione…</option>
                {(scope === "praca" ? pracas : techs).map((x) => (
                  <option key={x.id} value={x.id}>{x.name}</option>
                ))}
              </select>
            </div>
          )}

          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", marginBottom: 6 }}>
            Modo de contagem
          </div>
          <div style={{ display: "grid",
                          gridTemplateColumns: "1fr 1fr",
                          gap: 8, marginBottom: 14 }}>
            <button type="button"
                      data-testid="balanco-mode-blind"
                      onClick={() => setMode("blind")}
                      style={{
                        padding: 10, borderRadius: 8,
                        background: mode === "blind" ? "#0f172a" : "white",
                        color: mode === "blind" ? "white" : "#0f172a",
                        border: "1px solid #0f172a",
                        cursor: "pointer", fontWeight: 700, fontSize: 12,
                        textAlign: "left",
                      }}>
              <div style={{ fontSize: 14 }}>🙈 Cego</div>
              <div style={{ fontSize: 10, opacity: 0.85, marginTop: 2,
                              fontWeight: 500 }}>
                Não revela saldo esperado durante a contagem (best practice)
              </div>
            </button>
            <button type="button"
                      data-testid="balanco-mode-open"
                      onClick={() => setMode("open")}
                      style={{
                        padding: 10, borderRadius: 8,
                        background: mode === "open" ? "#0f172a" : "white",
                        color: mode === "open" ? "white" : "#0f172a",
                        border: "1px solid #0f172a",
                        cursor: "pointer", fontWeight: 700, fontSize: 12,
                        textAlign: "left",
                      }}>
              <div style={{ fontSize: 14 }}>👀 Aberto</div>
              <div style={{ fontSize: 10, opacity: 0.85, marginTop: 2,
                              fontWeight: 500 }}>
                Mostra esperado vs contado em tempo real
              </div>
            </button>
          </div>

          <label style={{ display: "flex", alignItems: "center",
                            gap: 8, fontSize: 12, color: "#475569",
                            marginBottom: 14 }}>
            <input type="checkbox" checked={includeCons}
                    data-testid="balanco-include-cons"
                    onChange={(e) => setIncludeCons(e.target.checked)} />
            Incluir contagem de insumos (drop, conectores, cabo de rede…)
          </label>

          <button type="button"
                    data-testid="balanco-wizard-next"
                    disabled={!canConfirm}
                    onClick={() => setStep(2)}
                    style={{
                      width: "100%", padding: 10, borderRadius: 8,
                      background: canConfirm ? "#0f766e" : "#cbd5e1",
                      color: "white", border: "none", fontSize: 13,
                      fontWeight: 700,
                      cursor: canConfirm ? "pointer" : "not-allowed",
                    }}>
            Próximo →
          </button>
        </>
      )}

      {step === 2 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", marginBottom: 6 }}>
            Resumo
          </div>
          <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0",
                          borderRadius: 8, padding: 12, marginBottom: 14,
                          fontSize: 12, color: "#334155" }}>
            <div><strong>Escopo:</strong> {SCOPES.find((s) => s.id === scope)?.label}
              {scope !== "empresa" && scopeId && ` → ${
                (scope === "praca" ? pracas : techs).find((x) => x.id === scopeId)?.name || "?"
              }`}
            </div>
            <div style={{ marginTop: 4 }}><strong>Modo:</strong> {mode === "blind"
              ? "Cego (saldo esperado oculto)" : "Aberto"}</div>
            <div style={{ marginTop: 4 }}><strong>Insumos:</strong> {
              includeCons ? "Incluídos" : "Apenas ONTs"}</div>
          </div>

          <textarea
            data-testid="balanco-note"
            placeholder="Observação (opcional) — ex: balanço mensal, conferência pós-compra…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            style={{
              width: "100%", padding: 10, border: "1px solid #cbd5e1",
              borderRadius: 8, fontSize: 12, fontFamily: "inherit",
              minHeight: 60, marginBottom: 14,
            }}/>

          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={() => setStep(1)}
                      style={{ flex: 1, padding: 10, borderRadius: 8,
                                background: "white",
                                border: "1px solid #cbd5e1", color: "#0f172a",
                                fontSize: 13, fontWeight: 700,
                                cursor: "pointer" }}>
              ← Voltar
            </button>
            <button type="button" onClick={submit}
                      data-testid="balanco-wizard-submit"
                      disabled={creating}
                      style={{ flex: 2, padding: 10, borderRadius: 8,
                                background: "#0f766e",
                                color: "white", border: "none",
                                fontSize: 13, fontWeight: 700,
                                cursor: creating ? "wait" : "pointer",
                                opacity: creating ? 0.7 : 1 }}>
              {creating ? "Criando…" : "✅ Iniciar Balanço"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}


// ============================================================
// Counting screen: scan + insumos
// ============================================================
function CountingScreen({ session, onUpdate, currentUser, consumablesCatalog }) {
  const [macInput, setMacInput] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [busy, setBusy] = useState(false);
  const macRef = useRef(null);

  useEffect(() => { macRef.current?.focus(); }, []);

  const isBlind = session.mode === "blind";
  const expectedCount = session.expected_count
    ?? (session.expected_macs?.length || 0);
  const scannedCount = session.scanned_macs?.length || 0;
  const expectedSet = useMemo(
    () => new Set((session.expected_macs || []).map((m) => m.toUpperCase())),
    [session.expected_macs]);

  const submitScan = async (e) => {
    e?.preventDefault();
    const mac = macInput.trim().toUpperCase();
    if (!mac) return;
    setBusy(true);
    try {
      const r = await api.balancoScan(session.id, mac);
      if (r.duplicate) {
        setFeedback({ type: "warn", mac, text: "Já escaneado nesta sessão" });
      } else if (isBlind) {
        setFeedback({ type: "ok", mac, text: "Registrado" });
      } else {
        setFeedback({
          type: r.matched ? "ok" : "extra",
          mac,
          text: r.matched ? "✅ Esperado · OK" : "⚠️ Não estava na lista esperada",
        });
      }
      setMacInput("");
      await onUpdate();
    } catch (err) {
      setFeedback({ type: "err", mac, text: err?.response?.data?.detail || err.message });
    } finally {
      setBusy(false);
      macRef.current?.focus();
    }
  };

  const updateConsumable = async (consId, qty) => {
    try {
      await api.balancoConsumable(session.id, consId, Math.max(0, parseInt(qty || 0, 10)));
      await onUpdate();
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    }
  };

  const finalize = async () => {
    if (!window.confirm(`Finalizar contagem? Escaneados: ${scannedCount}${isBlind ? "" : ` de ${expectedCount}`}.`)) return;
    try {
      const r = await api.balancoFinalize(session.id);
      toast.success(`Balanço finalizado · ${r.variance.accuracy_pct}% acurácia`);
      await onUpdate();
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    }
  };

  const cancel = async () => {
    if (!window.confirm("Cancelar este balanço? Todos os scans serão descartados.")) return;
    try {
      await api.balancoCancel(session.id);
      toast.info("Balanço cancelado");
      await onUpdate();
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    }
  };

  return (
    <div data-testid="balanco-counting" style={{
      background: "white", border: "1px solid #cbd5e1",
      borderRadius: 12, padding: 18, marginBottom: 16,
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "flex-start", marginBottom: 14,
                       paddingBottom: 12, borderBottom: "1px solid #e2e8f0" }}>
        <div>
          <div style={{ fontSize: 11, color: "#94a3b8", fontWeight: 700,
                          letterSpacing: ".05em" }}>
            BALANÇO {session.id} · {isBlind ? "🙈 CEGO" : "👀 ABERTO"}
          </div>
          <h3 style={{ margin: "4px 0 0", fontSize: 16, fontWeight: 800,
                          color: "#0f172a" }}>
            {session.scope_label}
          </h3>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
            Iniciado por {session.created_by_name} em {fmtDt(session.created_at)}
          </div>
        </div>
        <button onClick={cancel}
                  data-testid="balanco-cancel-btn"
                  style={{ background: "white", border: "1px solid #fecaca",
                            color: "#dc2626", padding: "5px 10px",
                            borderRadius: 6, fontSize: 11, fontWeight: 700,
                            cursor: "pointer" }}>
          Cancelar balanço
        </button>
      </div>

      {/* KPI bar */}
      <div style={{ display: "grid",
                       gridTemplateColumns: isBlind
                         ? "1fr 1fr" : "1fr 1fr 1fr",
                       gap: 10, marginBottom: 14 }}>
        <div style={{ background: "#f0fdf4", border: "1px solid #6ee7b7",
                         borderRadius: 8, padding: 10, textAlign: "center" }}>
          <div style={{ fontSize: 24, fontWeight: 900, color: "#065f46" }}>
            {scannedCount}
          </div>
          <div style={{ fontSize: 10, color: "#065f46", fontWeight: 700 }}>
            ESCANEADOS
          </div>
        </div>
        {!isBlind && (
          <div style={{ background: "#eff6ff", border: "1px solid #93c5fd",
                           borderRadius: 8, padding: 10, textAlign: "center" }}>
            <div style={{ fontSize: 24, fontWeight: 900, color: "#1e40af" }}>
              {expectedCount}
            </div>
            <div style={{ fontSize: 10, color: "#1e40af", fontWeight: 700 }}>
              ESPERADOS
            </div>
          </div>
        )}
        <div style={{ background: "#fef3c7", border: "1px solid #fcd34d",
                         borderRadius: 8, padding: 10, textAlign: "center" }}>
          <div style={{ fontSize: 24, fontWeight: 900, color: "#92400e" }}>
            {isBlind
              ? "?"
              : Math.max(0, expectedCount - (session.scanned_macs || [])
                  .filter((m) => expectedSet.has(m.toUpperCase())).length)}
          </div>
          <div style={{ fontSize: 10, color: "#92400e", fontWeight: 700 }}>
            FALTAM {isBlind && "(oculto)"}
          </div>
        </div>
      </div>

      {/* MAC input */}
      <form onSubmit={submitScan}>
        <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", marginBottom: 6 }}>
          Escaneie ou digite o MAC
        </div>
        <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
          <input ref={macRef}
                   data-testid="balanco-mac-input"
                   value={macInput}
                   onChange={(e) => setMacInput(e.target.value)}
                   placeholder="XX:XX:XX:XX:XX:XX"
                   autoFocus
                   style={{
                     flex: 1, padding: "10px 12px",
                     border: "1px solid #cbd5e1", borderRadius: 8,
                     fontSize: 14, fontFamily: "monospace",
                     fontWeight: 700, letterSpacing: ".05em",
                   }}/>
          <button type="submit"
                    data-testid="balanco-mac-submit"
                    disabled={busy || !macInput.trim()}
                    style={{
                      padding: "10px 16px", border: "none",
                      background: busy ? "#94a3b8" : "#0f766e",
                      color: "white", borderRadius: 8,
                      fontSize: 13, fontWeight: 700,
                      cursor: busy ? "wait" : "pointer",
                    }}>
            +
          </button>
        </div>
      </form>

      {feedback && (
        <div data-testid="balanco-mac-feedback"
              style={{
                padding: "8px 10px", borderRadius: 6,
                background: feedback.type === "ok" ? "#dcfce7"
                  : feedback.type === "warn" ? "#fef3c7"
                  : feedback.type === "extra" ? "#fee2e2"
                  : "#fee2e2",
                color: feedback.type === "ok" ? "#065f46"
                  : feedback.type === "warn" ? "#92400e"
                  : "#991b1b",
                fontSize: 12, marginBottom: 10,
                display: "flex", justifyContent: "space-between",
              }}>
          <span style={{ fontFamily: "monospace", fontWeight: 700 }}>{feedback.mac}</span>
          <span>{feedback.text}</span>
        </div>
      )}

      {/* Lista de MACs já escaneados (sempre visível) */}
      {(session.scanned_macs || []).length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", marginBottom: 6 }}>
            MACs registrados ({(session.scanned_macs || []).length})
          </div>
          <div style={{ maxHeight: 160, overflowY: "auto",
                          border: "1px solid #f1f5f9", borderRadius: 6 }}>
            {(session.scanned_macs || []).slice().reverse().map((m) => {
              const matched = expectedSet.has(m.toUpperCase());
              return (
                <div key={m}
                      data-testid={`balanco-scanned-${m}`}
                      style={{
                        padding: "5px 10px",
                        borderBottom: "1px solid #f1f5f9",
                        display: "flex", justifyContent: "space-between",
                        fontFamily: "monospace", fontSize: 11,
                      }}>
                  <span style={{ fontWeight: 700 }}>{m}</span>
                  {!isBlind && (
                    <span style={{ fontSize: 10, fontWeight: 700,
                                      padding: "1px 6px", borderRadius: 4,
                                      background: matched ? "#dcfce7" : "#fee2e2",
                                      color: matched ? "#065f46" : "#991b1b" }}>
                      {matched ? "✓ ESPERADO" : "⚠ EXTRA"}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Insumos */}
      {session.include_consumables && (
        <div style={{ marginBottom: 14, paddingTop: 12,
                          borderTop: "1px solid #e2e8f0" }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", marginBottom: 6 }}>
            Contagem de insumos
          </div>
          <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                          gap: 8 }}>
            {(consumablesCatalog || []).map((c) => {
              const counted = (session.counted_consumables || {})[c.id] || 0;
              const expected = isBlind ? null
                : (session.expected_consumables || {})[c.id] || 0;
              return (
                <div key={c.id} style={{
                  background: "#f8fafc", padding: 8, borderRadius: 6,
                  border: "1px solid #e2e8f0",
                }}>
                  <div style={{ fontSize: 11, fontWeight: 700,
                                  color: "#0f172a", marginBottom: 4 }}>
                    {c.name} <span style={{ color: "#94a3b8" }}>({c.unit})</span>
                  </div>
                  <div style={{ display: "flex", gap: 6,
                                  alignItems: "center" }}>
                    <input type="number" min={0}
                              data-testid={`balanco-cons-${c.id}`}
                              value={counted}
                              onChange={(e) => updateConsumable(c.id, e.target.value)}
                              style={{ flex: 1, padding: "4px 8px",
                                        border: "1px solid #cbd5e1",
                                        borderRadius: 4, fontSize: 12,
                                        fontWeight: 700 }} />
                    {expected !== null && (
                      <span style={{ fontSize: 10, color: counted === expected
                                                          ? "#065f46" : "#991b1b",
                                        fontWeight: 700 }}>
                        / {expected}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <button type="button"
                onClick={finalize}
                data-testid="balanco-finalize-btn"
                style={{
                  width: "100%", padding: 12, borderRadius: 8,
                  background: "#0f172a", color: "white",
                  border: "none", fontSize: 14, fontWeight: 700,
                  cursor: "pointer",
                }}>
        ✅ Finalizar Contagem
      </button>
    </div>
  );
}


// ============================================================
// Review screen: aprovação
// ============================================================
function ReviewScreen({ session, onUpdate, currentUser }) {
  const variance = session.variance || {};
  const [missingAction, setMissingAction] = useState("perdido");
  const [ignoreMacs, setIgnoreMacs] = useState({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const isAdmin = currentUser
    && (currentUser.is_super_admin
        || (currentUser.role || "").toLowerCase() === "administrador");

  const toggleIgnore = (mac) => setIgnoreMacs((s) => ({ ...s, [mac]: !s[mac] }));

  const approve = async () => {
    if (!isAdmin) {
      toast.error("Apenas administrador ou super admin podem aprovar (separation of duties).");
      return;
    }
    if (!window.confirm("Aprovar balanço e aplicar ajustes? Esta ação é irreversível.")) return;
    setBusy(true);
    try {
      const ignore_macs = Object.keys(ignoreMacs).filter((m) => ignoreMacs[m]);
      const r = await api.balancoApprove(session.id, {
        missing_action: missingAction,
        ignore_macs, note: note || null,
      });
      toast.success(`Balanço aprovado · ${r.adjustments.length} ajuste(s) ONT + ${r.consumable_adjustments.length} ajuste(s) insumo`);
      await onUpdate();
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    } finally { setBusy(false); }
  };

  const cancel = async () => {
    if (!window.confirm("Cancelar este balanço sem aplicar ajustes?")) return;
    try {
      await api.balancoCancel(session.id);
      toast.info("Balanço cancelado");
      await onUpdate();
    } catch (err) { toast.error(err?.response?.data?.detail || err.message); }
  };

  return (
    <div data-testid="balanco-review" style={{
      background: "white", border: "1px solid #cbd5e1",
      borderRadius: 12, padding: 18, marginBottom: 16,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "flex-start", marginBottom: 14,
                       paddingBottom: 12, borderBottom: "1px solid #e2e8f0" }}>
        <div>
          <div style={{ fontSize: 11, color: "#1e40af", fontWeight: 700,
                          letterSpacing: ".05em" }}>
            REVISÃO · {session.id}
          </div>
          <h3 style={{ margin: "4px 0 0", fontSize: 16, fontWeight: 800 }}>
            {session.scope_label}
          </h3>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
            Finalizado por {session.finalized_by_name} em {fmtDt(session.finalized_at)}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 32, fontWeight: 900,
                          color: variance.accuracy_pct >= 95 ? "#065f46"
                            : variance.accuracy_pct >= 80 ? "#92400e" : "#991b1b" }}>
            {(variance.accuracy_pct ?? 0).toFixed(1)}%
          </div>
          <div style={{ fontSize: 10, color: "#475569", fontWeight: 700,
                          letterSpacing: ".05em" }}>
            ACURÁCIA
          </div>
        </div>
      </div>

      {/* Variance 3 cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
                        gap: 10, marginBottom: 14 }}>
        <div style={{ background: "#dcfce7", border: "1px solid #6ee7b7",
                         borderRadius: 8, padding: 10 }}>
          <div style={{ fontSize: 22, fontWeight: 900, color: "#065f46" }}>
            {(variance.matched || []).length}
          </div>
          <div style={{ fontSize: 10, color: "#065f46", fontWeight: 700 }}>
            ✅ OK (BATEM)
          </div>
        </div>
        <div style={{ background: "#fee2e2", border: "1px solid #fca5a5",
                         borderRadius: 8, padding: 10 }}>
          <div style={{ fontSize: 22, fontWeight: 900, color: "#991b1b" }}>
            {(variance.missing || []).length}
          </div>
          <div style={{ fontSize: 10, color: "#991b1b", fontWeight: 700 }}>
            ⚠️ FALTANTES
          </div>
        </div>
        <div style={{ background: "#fef3c7", border: "1px solid #fcd34d",
                         borderRadius: 8, padding: 10 }}>
          <div style={{ fontSize: 22, fontWeight: 900, color: "#92400e" }}>
            {(variance.extra || []).length}
          </div>
          <div style={{ fontSize: 10, color: "#92400e", fontWeight: 700 }}>
            ➕ EXTRAS
          </div>
        </div>
      </div>

      {/* Faltantes */}
      {(variance.missing || []).length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#991b1b",
                          textTransform: "uppercase", marginBottom: 6 }}>
            MACs faltantes ({variance.missing.length})
          </div>
          <div style={{ background: "#fef2f2", padding: 6, borderRadius: 6,
                          fontSize: 11, color: "#7f1d1d", marginBottom: 6 }}>
            Ação: <select value={missingAction}
                            data-testid="balanco-missing-action"
                            onChange={(e) => setMissingAction(e.target.value)}
                            style={{ padding: "3px 6px", borderRadius: 4,
                                      border: "1px solid #fca5a5",
                                      fontSize: 11 }}>
              <option value="perdido">Marcar como PERDIDO (baixa)</option>
              <option value="investigacao">Flag de INVESTIGAÇÃO (mantém no estoque)</option>
            </select>
          </div>
          <div style={{ maxHeight: 160, overflowY: "auto",
                          border: "1px solid #fee2e2", borderRadius: 6 }}>
            {variance.missing.map((m) => (
              <label key={m}
                       data-testid={`balanco-missing-${m}`}
                       style={{
                         padding: "5px 10px", display: "flex",
                         justifyContent: "space-between", gap: 6,
                         borderBottom: "1px solid #fee2e2",
                         fontFamily: "monospace", fontSize: 11,
                         alignItems: "center",
                       }}>
                <span style={{ fontWeight: 700,
                                  textDecoration: ignoreMacs[m]
                                    ? "line-through" : "none",
                                  opacity: ignoreMacs[m] ? 0.5 : 1 }}>{m}</span>
                <label style={{ fontSize: 9, color: "#64748b",
                                  display: "flex", alignItems: "center",
                                  gap: 4, fontFamily: "system-ui",
                                  cursor: "pointer" }}>
                  <input type="checkbox"
                            checked={!!ignoreMacs[m]}
                            onChange={() => toggleIgnore(m)} />
                  ignorar
                </label>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Extras */}
      {(variance.extra || []).length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#92400e",
                          textTransform: "uppercase", marginBottom: 6 }}>
            MACs extras ({variance.extra.length})
          </div>
          <div style={{ fontSize: 11, color: "#78350f", marginBottom: 6 }}>
            Não estavam no escopo esperado. Serão apenas logados; revise se foram cadastrados em outra praça.
          </div>
          <div style={{ maxHeight: 160, overflowY: "auto",
                          border: "1px solid #fde68a", borderRadius: 6 }}>
            {variance.extra.map((m) => (
              <div key={m}
                    data-testid={`balanco-extra-${m}`}
                    style={{ padding: "5px 10px",
                              borderBottom: "1px solid #fef3c7",
                              fontFamily: "monospace", fontSize: 11,
                              fontWeight: 700 }}>
                {m}
              </div>
            ))}
          </div>
        </div>
      )}

      <textarea data-testid="balanco-approve-note"
                  placeholder="Observação da aprovação (opcional)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  style={{ width: "100%", padding: 10,
                            border: "1px solid #cbd5e1", borderRadius: 8,
                            fontSize: 12, fontFamily: "inherit",
                            minHeight: 50, marginBottom: 12 }}/>

      {!isAdmin && (
        <div style={{ padding: 10, background: "#fef3c7",
                          border: "1px solid #fcd34d", borderRadius: 6,
                          fontSize: 11, color: "#92400e", marginBottom: 10 }}>
          ⚠️ Apenas <strong>administrador</strong> ou <strong>super admin</strong> podem aprovar este balanço
          (separation of duties — best practice de auditoria).
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" onClick={cancel}
                  data-testid="balanco-review-cancel"
                  style={{ flex: 1, padding: 12, borderRadius: 8,
                            background: "white",
                            border: "1px solid #fecaca", color: "#dc2626",
                            fontSize: 13, fontWeight: 700,
                            cursor: "pointer" }}>
          Cancelar
        </button>
        <button type="button" onClick={approve}
                  data-testid="balanco-approve-btn"
                  disabled={busy || !isAdmin}
                  style={{ flex: 2, padding: 12, borderRadius: 8,
                            background: !isAdmin ? "#cbd5e1" : "#0f766e",
                            color: "white", border: "none",
                            fontSize: 13, fontWeight: 700,
                            cursor: !isAdmin || busy
                              ? "not-allowed" : "pointer" }}>
          {busy ? "Aplicando…" : "✅ Aprovar e Aplicar Ajustes"}
        </button>
      </div>
    </div>
  );
}


// ============================================================
// History list
// ============================================================
function HistoryList({ items, onOpen }) {
  if (!items.length) {
    return (
      <div style={{ padding: 20, background: "#f8fafc",
                       border: "1px dashed #cbd5e1", borderRadius: 8,
                       textAlign: "center", color: "#94a3b8", fontSize: 12 }}>
        Nenhum balanço registrado. Inicie o primeiro pelo botão acima.
      </div>
    );
  }
  return (
    <div data-testid="balanco-history">
      <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                       textTransform: "uppercase", marginBottom: 8 }}>
        Histórico ({items.length})
      </div>
      <div style={{ display: "grid", gap: 8 }}>
        {items.map((b) => {
          const meta = STATUS_META[b.status] || STATUS_META.cancelled;
          return (
            <button key={b.id}
                      type="button"
                      data-testid={`balanco-row-${b.id}`}
                      onClick={() => onOpen(b.id)}
                      style={{
                        textAlign: "left", padding: 12,
                        background: "white", border: "1px solid #e2e8f0",
                        borderRadius: 8, cursor: "pointer",
                        display: "grid",
                        gridTemplateColumns: "1fr auto auto",
                        gap: 12, alignItems: "center",
                      }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 800,
                                color: "#0f172a" }}>
                  {b.scope_label}
                </div>
                <div style={{ fontSize: 10, color: "#64748b",
                                marginTop: 2 }}>
                  {b.id} · {b.created_by_name} · {fmtDt(b.created_at)}
                </div>
              </div>
              {b.variance && (
                <div style={{ fontSize: 16, fontWeight: 900,
                                color: b.variance.accuracy_pct >= 95 ? "#065f46"
                                  : b.variance.accuracy_pct >= 80 ? "#92400e"
                                  : "#991b1b" }}>
                  {b.variance.accuracy_pct.toFixed(1)}%
                </div>
              )}
              <span style={{ padding: "3px 8px", borderRadius: 999,
                                background: meta.bg, color: meta.fg,
                                fontSize: 10, fontWeight: 700,
                                textTransform: "uppercase",
                                letterSpacing: ".04em" }}>
                {meta.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}


// ============================================================
// Approved/Cancelled details (read-only)
// ============================================================
function ResultScreen({ session, onBack }) {
  const variance = session.variance || {};
  const meta = STATUS_META[session.status] || STATUS_META.cancelled;
  return (
    <div data-testid="balanco-result" style={{
      background: "white", border: "1px solid #e2e8f0",
      borderRadius: 12, padding: 18, marginBottom: 16,
    }}>
      <button onClick={onBack} data-testid="balanco-result-back"
                style={{ marginBottom: 10, background: "none",
                          border: "1px solid #cbd5e1", padding: "4px 10px",
                          borderRadius: 6, fontSize: 11, cursor: "pointer" }}>
        ← Voltar
      </button>
      <div style={{ marginBottom: 14, paddingBottom: 12,
                       borderBottom: "1px solid #e2e8f0" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center" }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800 }}>
            {session.scope_label}
          </h3>
          <span style={{ padding: "3px 10px", borderRadius: 999,
                            background: meta.bg, color: meta.fg,
                            fontSize: 11, fontWeight: 700 }}>
            {meta.label}
          </span>
        </div>
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 6 }}>
          {session.id} · iniciado em {fmtDt(session.created_at)} por {session.created_by_name}
          {session.approved_at && ` · aprovado em ${fmtDt(session.approved_at)} por ${session.approved_by_name}`}
          {session.cancelled_at && ` · cancelado em ${fmtDt(session.cancelled_at)}`}
        </div>
      </div>

      {session.status === "approved" && variance.accuracy_pct !== undefined && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr",
                          gap: 10, marginBottom: 14 }}>
          <div style={{ textAlign: "center", padding: 12,
                            background: "#f0f9ff", borderRadius: 8 }}>
            <div style={{ fontSize: 22, fontWeight: 900,
                            color: variance.accuracy_pct >= 95 ? "#065f46"
                              : variance.accuracy_pct >= 80 ? "#92400e"
                              : "#991b1b" }}>
              {variance.accuracy_pct.toFixed(1)}%
            </div>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#475569" }}>
              ACURÁCIA
            </div>
          </div>
          <div style={{ textAlign: "center", padding: 12,
                            background: "#dcfce7", borderRadius: 8 }}>
            <div style={{ fontSize: 22, fontWeight: 900, color: "#065f46" }}>
              {(variance.matched || []).length}
            </div>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#065f46" }}>
              BATEM
            </div>
          </div>
          <div style={{ textAlign: "center", padding: 12,
                            background: "#fee2e2", borderRadius: 8 }}>
            <div style={{ fontSize: 22, fontWeight: 900, color: "#991b1b" }}>
              {(variance.missing || []).length}
            </div>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#991b1b" }}>
              FALTANTES
            </div>
          </div>
          <div style={{ textAlign: "center", padding: 12,
                            background: "#fef3c7", borderRadius: 8 }}>
            <div style={{ fontSize: 22, fontWeight: 900, color: "#92400e" }}>
              {(variance.extra || []).length}
            </div>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#92400e" }}>
              EXTRAS
            </div>
          </div>
        </div>
      )}

      {(session.applied_adjustments || []).length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", marginBottom: 6 }}>
            Ajustes aplicados em ONTs ({session.applied_adjustments.length})
          </div>
          <div style={{ maxHeight: 200, overflowY: "auto",
                          border: "1px solid #f1f5f9", borderRadius: 6 }}>
            {session.applied_adjustments.map((a, i) => (
              <div key={i} style={{ padding: "4px 10px",
                                          borderBottom: "1px solid #f1f5f9",
                                          fontSize: 11, fontFamily: "monospace",
                                          display: "flex",
                                          justifyContent: "space-between" }}>
                <span>{a.mac}</span>
                <span style={{ fontFamily: "system-ui", fontSize: 10,
                                  color: "#64748b" }}>{a.action}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {(session.applied_consumable_adjustments || []).length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", marginBottom: 6 }}>
            Ajustes em insumos ({session.applied_consumable_adjustments.length})
          </div>
          <div style={{ border: "1px solid #f1f5f9", borderRadius: 6 }}>
            {session.applied_consumable_adjustments.map((a, i) => (
              <div key={i} style={{ padding: "4px 10px",
                                          borderBottom: "1px solid #f1f5f9",
                                          fontSize: 11,
                                          display: "flex",
                                          justifyContent: "space-between" }}>
                <span style={{ fontWeight: 700 }}>{a.consumable_id}</span>
                <span style={{ color: a.diff > 0 ? "#065f46" : "#991b1b",
                                  fontWeight: 700 }}>
                  {a.expected} → {a.counted} ({a.diff > 0 ? "+" : ""}{a.diff})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


// ============================================================
// Main tab
// ============================================================
export default function BalancoTab({ pracas = [], techs = [],
                                       consumablesCatalog = [],
                                       currentUser }) {
  const [history, setHistory] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [showWizard, setShowWizard] = useState(false);
  const [viewSessionId, setViewSessionId] = useState(null);
  const [viewedSession, setViewedSession] = useState(null);
  const [loading, setLoading] = useState(false);

  const reloadList = async () => {
    setLoading(true);
    try {
      const list = await api.balancoList(100);
      setHistory(list || []);
      // Encontra sessão ativa (counting ou pending_approval)
      const active = (list || []).find(
        (b) => b.status === "counting" || b.status === "pending_approval");
      if (active) {
        const full = await api.balancoGet(active.id);
        setActiveSession(full);
      } else {
        setActiveSession(null);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  };

  useEffect(() => { reloadList(); }, []);

  // Polling enquanto há sessão ativa
  useEffect(() => {
    if (!activeSession) return;
    const t = setInterval(async () => {
      try {
        const fresh = await api.balancoGet(activeSession.id);
        setActiveSession(fresh);
      } catch (e) { /* swallow */ }
    }, 5000);
    return () => clearInterval(t);
  }, [activeSession?.id]);

  // Visualizar sessão fechada
  useEffect(() => {
    if (!viewSessionId) { setViewedSession(null); return; }
    api.balancoGet(viewSessionId).then(setViewedSession).catch((e) =>
      toast.error(e?.response?.data?.detail || e.message));
  }, [viewSessionId]);

  return (
    <div data-testid="balanco-tab" style={{ maxWidth: 960, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800 }}>
            📊 Balanço de Estoque
          </h2>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
            Cycle counting com modo cego, reconciliação de variância e auditoria completa
          </div>
        </div>
        {!activeSession && !showWizard && !viewSessionId && (
          <button onClick={() => setShowWizard(true)}
                    data-testid="balanco-new-btn"
                    style={{ padding: "9px 18px", background: "#0f766e",
                              color: "white", border: "none",
                              borderRadius: 10, fontWeight: 700,
                              fontSize: 13, cursor: "pointer" }}>
            + Novo Balanço
          </button>
        )}
      </div>

      {showWizard && (
        <NewBalancoWizard
          pracas={pracas} techs={techs}
          onCancel={() => setShowWizard(false)}
          onCreated={async (s) => {
            setShowWizard(false);
            await reloadList();
          }}/>
      )}

      {viewSessionId && viewedSession && (
        <ResultScreen session={viewedSession}
                       onBack={() => { setViewSessionId(null); setViewedSession(null); }}/>
      )}

      {activeSession && activeSession.status === "counting" && (
        <CountingScreen session={activeSession}
                          consumablesCatalog={consumablesCatalog}
                          currentUser={currentUser}
                          onUpdate={reloadList}/>
      )}

      {activeSession && activeSession.status === "pending_approval" && (
        <ReviewScreen session={activeSession}
                        currentUser={currentUser}
                        onUpdate={reloadList}/>
      )}

      {!viewSessionId && (
        loading
          ? <div style={{ padding: 20, color: "#64748b", fontSize: 12 }}>Carregando…</div>
          : <HistoryList items={history.filter(
              (h) => h.status === "approved" || h.status === "cancelled")}
                            onOpen={setViewSessionId}/>
      )}
    </div>
  );
}
