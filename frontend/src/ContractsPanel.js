/**
 * ContractsPanel — Página de Contratos com política de aging RADIUS.
 *
 * Cada contrato vincula assinante + plano e define quando aplicar:
 *   - REDUZIDO     (após N dias de atraso)
 *   - WALL_GARDEN  (após N dias)
 *   - SUSPENSO     (após N dias)
 *
 * O worker `contracts_aging_worker` roda a cada 15min, mas pode ser
 * disparado manualmente pelo botão "Sincronizar agora".
 *
 * Estados RADIUS exibidos com cores claras pra leitura rápida.
 */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";


const STATE_STYLE = {
  ATIVO: { bg: "#dcfce7", fg: "#14532d", icon: "🟢", label: "Ativo" },
  GRACE: { bg: "#fef9c3", fg: "#854d0e", icon: "⏳", label: "Tolerância" },
  REDUZIDO: { bg: "#fef3c7", fg: "#92400e", icon: "🟠", label: "Reduzido" },
  WALLED_GARDEN: { bg: "#fee2e2", fg: "#991b1b", icon: "🔒", label: "Wall Garden" },
  SUSPENSO: { bg: "#fecaca", fg: "#7f1d1d", icon: "🔴", label: "Suspenso" },
  CANCELADO: { bg: "#e2e8f0", fg: "#334155", icon: "⚫", label: "Cancelado" },
};


function StateBadge({ state, size = "md" }) {
  const c = STATE_STYLE[state] || STATE_STYLE.ATIVO;
  const sm = size === "sm";
  return (
    <span style={{
      padding: sm ? "2px 7px" : "3px 10px",
      borderRadius: 99, background: c.bg, color: c.fg,
      fontSize: sm ? 10 : 11, fontWeight: 800,
      display: "inline-flex", gap: 4, alignItems: "center",
      whiteSpace: "nowrap",
    }}>
      {c.icon} {c.label}
    </span>
  );
}


function fmt(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR",
      { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
}


function fmtBRL(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString("pt-BR",
    { style: "currency", currency: "BRL" });
}


export default function ContractsPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [stateFilter, setStateFilter] = useState("all");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState(null);
  const [agingRunning, setAgingRunning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.contractsList({
        status: statusFilter, search,
      });
      let arr = r.items || [];
      if (stateFilter !== "all") {
        arr = arr.filter((c) => c.radius_state === stateFilter);
      }
      setItems(arr);
    } catch { /* silent */ }
    setLoading(false);
  }, [statusFilter, stateFilter, search]);

  useEffect(() => { load(); }, [load]);

  async function runAging() {
    if (!window.confirm(
      "Recalcular estado RADIUS de TODOS os contratos agora?\n\n"
      + "O worker normalmente roda a cada 15min. Disparar agora "
      + "aplicará mudanças e enviará CoA Disconnect imediatamente "
      + "para sessões ativas afetadas.")) return;
    setAgingRunning(true);
    try {
      const r = await api.contractsAgingRunNow();
      window.alert(
        `✅ Concluído!\n\nContratos analisados: ${r.inspected}\n`
        + `Estados alterados: ${r.changed}\n`
        + `Distribuição: ${JSON.stringify(r.by_state, null, 2)}`,
      );
      await load();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setAgingRunning(false); }
  }

  // KPIs por estado
  const kpis = items.reduce((acc, c) => {
    const s = c.radius_state || "ATIVO";
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});

  return (
    <div data-testid="contracts-panel" style={{ padding: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ fontSize: 22, fontWeight: 800, color: "#0f172a",
                          marginBottom: 4 }}>
            📋 Contratos
          </h2>
          <p style={{ color: "#64748b", fontSize: 13, margin: 0 }}>
            Política de aging RADIUS por contrato. Define quantos dias após o
            vencimento aplicar redução/wall garden/suspensão.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button data-testid="contracts-aging-run"
                    onClick={runAging} disabled={agingRunning}
                    style={{
                      padding: "10px 14px", borderRadius: 8,
                      background: "#7c3aed", color: "#fff", border: 0,
                      fontSize: 12, fontWeight: 700,
                      cursor: agingRunning ? "wait" : "pointer",
                      opacity: agingRunning ? 0.5 : 1,
                    }}>
            {agingRunning ? "⏳ Sincronizando…" : "⚡ Sincronizar inadimplentes"}
          </button>
          <button data-testid="contracts-add-btn"
                    onClick={() => { setEditing(null); setShowCreate(true); }}
                    style={{
                      padding: "10px 14px", borderRadius: 8,
                      background: "#0ea5e9", color: "#fff", border: 0,
                      fontSize: 12, fontWeight: 700, cursor: "pointer",
                    }}>
            ➕ Novo contrato
          </button>
        </div>
      </div>

      {/* KPIs por estado */}
      <div style={{ display: "grid", gap: 8, marginBottom: 14,
                      gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))" }}>
        {Object.keys(STATE_STYLE).map((s) => (
          <button key={s} data-testid={`kpi-state-${s}`}
                    onClick={() => setStateFilter(stateFilter === s ? "all" : s)}
                    style={{
                      padding: 12, borderRadius: 10, cursor: "pointer",
                      border: `1.5px solid ${
                        stateFilter === s ? STATE_STYLE[s].fg : "#e2e8f0"}`,
                      background: stateFilter === s
                        ? STATE_STYLE[s].bg : "#fff",
                      textAlign: "left",
                    }}>
            <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                            textTransform: "uppercase", letterSpacing: 0.4 }}>
              {STATE_STYLE[s].icon} {STATE_STYLE[s].label}
            </div>
            <div style={{ fontSize: 22, fontWeight: 800,
                            color: STATE_STYLE[s].fg, marginTop: 2 }}>
              {kpis[s] || 0}
            </div>
          </button>
        ))}
      </div>

      {/* Filtros */}
      <div style={{ display: "flex", gap: 8, marginBottom: 14,
                      alignItems: "center", flexWrap: "wrap" }}>
        <input data-testid="contracts-search" type="text"
                placeholder="Buscar por nome, plano, número de contrato…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                  flex: 1, maxWidth: 360, padding: "8px 12px",
                  border: "1px solid #cbd5e1", borderRadius: 7,
                  fontSize: 13, outline: "none",
                }} />
        <select value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  data-testid="contracts-status-filter"
                  style={{ padding: "8px 10px", border: "1px solid #cbd5e1",
                            borderRadius: 7, fontSize: 13 }}>
          <option value="all">Todos status</option>
          <option value="ativo">Ativo</option>
          <option value="cancelado">Cancelado</option>
          <option value="encerrado">Encerrado</option>
        </select>
        {stateFilter !== "all" && (
          <button onClick={() => setStateFilter("all")}
                    style={{ padding: "6px 11px", borderRadius: 7,
                              background: "#fef2f2", color: "#991b1b",
                              border: "1px solid #fecaca", fontSize: 11,
                              fontWeight: 700, cursor: "pointer" }}>
            ✗ Limpar filtro: {STATE_STYLE[stateFilter]?.label}
          </button>
        )}
        <span style={{ color: "#64748b", fontSize: 12, marginLeft: "auto" }}>
          {loading ? "⏳" : ""} {items.length} contratos
        </span>
      </div>

      {items.length === 0 && !loading && (
        <div style={{ padding: 40, background: "#f8fafc", borderRadius: 8,
                        textAlign: "center", color: "#64748b" }}>
          {search || statusFilter !== "all" || stateFilter !== "all"
            ? "Nenhum contrato no filtro atual."
            : "Nenhum contrato. Clique em ➕ Novo contrato pra começar."}
        </div>
      )}

      <div style={{ display: "grid", gap: 8 }}>
        {items.map((c) => (
          <ContractRow key={c.id} c={c}
            onEdit={() => { setEditing(c); setShowCreate(true); }}
            onChanged={load} />
        ))}
      </div>

      {showCreate && (
        <ContractFormModal initial={editing}
          onClose={() => { setShowCreate(false); setEditing(null); }}
          onSaved={() => { setShowCreate(false); setEditing(null); load(); }} />
      )}
    </div>
  );
}


function ContractRow({ c, onEdit, onChanged }) {
  const [busy, setBusy] = useState(false);

  async function suspend() {
    if (!window.confirm(
      `Suspender contrato de ${c.subscriber_name}?\n\n`
      + "CoA Disconnect será enviado e o RADIUS rejeitará novos logins."
    )) return;
    setBusy(true);
    try {
      const reason = window.prompt("Motivo (opcional):", "");
      await api.contractsSuspend(c.id, reason || "Suspensão manual");
      onChanged();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }

  async function reactivate() {
    setBusy(true);
    try {
      await api.contractsReactivate(c.id, "Reativado pelo gestor");
      onChanged();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }

  async function applyNow() {
    setBusy(true);
    try {
      const r = await api.contractsApplyRadius(c.id);
      window.alert(`Estado: ${r.state}\nCoA: ${JSON.stringify(r.coa)}`);
      onChanged();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }

  const ap = c.aging_policy || {};
  const canSuspend = c.radius_state !== "SUSPENSO";
  const canReactivate = c.radius_state !== "ATIVO";

  return (
    <div data-testid={`contract-row-${c.id}`}
          style={{
            background: "#fff", border: "1px solid #e2e8f0",
            borderLeft: `4px solid ${
              (STATE_STYLE[c.radius_state] || STATE_STYLE.ATIVO).fg}`,
            borderRadius: 10, padding: 14,
            display: "grid", gridTemplateColumns: "2fr 1fr 1fr auto",
            gap: 12, alignItems: "center",
          }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center",
                        flexWrap: "wrap", marginBottom: 4 }}>
          <span style={{ fontWeight: 800, fontSize: 14, color: "#0f172a" }}>
            {c.subscriber_name || c.subscriber_id}
          </span>
          <StateBadge state={c.radius_state} />
          <code style={{ fontSize: 10, background: "#f1f5f9",
                          padding: "1px 6px", borderRadius: 4,
                          color: "#64748b" }}>
            {c.contract_number}
          </code>
        </div>
        <div style={{ display: "flex", gap: 12, fontSize: 11,
                        color: "#475569", flexWrap: "wrap" }}>
          {c.pppoe_user && <span>🔑 <code>{c.pppoe_user}</code></span>}
          <span>📦 {c.plan_name}</span>
          <span>💰 {fmtBRL(c.monthly_value)}/mês · vence dia {c.due_day}</span>
        </div>
        {c.radius_state_reason && c.radius_state !== "ATIVO" && (
          <div style={{ marginTop: 4, fontSize: 11, color: "#64748b",
                          fontStyle: "italic" }}>
            ↳ {c.radius_state_reason}
          </div>
        )}
      </div>
      {/* Aging policy resumo */}
      <div style={{ fontSize: 11, color: "#475569", lineHeight: 1.6 }}>
        <div style={{ fontWeight: 700, marginBottom: 2 }}>
          📅 Aging Policy
        </div>
        <div>Tolerância: <b>{ap.grace_days}d</b></div>
        <div>Reduzir: <b>{ap.reduce_days}d</b></div>
        <div>Wall garden: <b>{ap.wall_garden_days}d</b></div>
        <div>Suspender: <b>{ap.suspend_days}d</b></div>
      </div>
      <div style={{ fontSize: 11, color: "#64748b" }}>
        <div>Criado: {fmt(c.created_at)}</div>
        {c.radius_state_at && (
          <div>Última mudança: {fmt(c.radius_state_at)}</div>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <button data-testid={`contract-edit-${c.id}`}
                  onClick={onEdit} disabled={busy}
                  style={mini("#f1f5f9", "#0f172a")}>
          ✏️ Editar
        </button>
        <button data-testid={`contract-apply-${c.id}`}
                  onClick={applyNow} disabled={busy}
                  title="Recalcula estado agora (mesmo que o worker faz a cada 15min)"
                  style={mini("#dbeafe", "#1e40af")}>
          🔄 Recalcular
        </button>
        {canSuspend && (
          <button data-testid={`contract-suspend-${c.id}`}
                    onClick={suspend} disabled={busy}
                    style={mini("#fee2e2", "#991b1b")}>
            🔴 Suspender
          </button>
        )}
        {canReactivate && (
          <button data-testid={`contract-reactivate-${c.id}`}
                    onClick={reactivate} disabled={busy}
                    style={mini("#dcfce7", "#14532d")}>
            🟢 Reativar
          </button>
        )}
      </div>
    </div>
  );
}


function mini(bg, fg) {
  return {
    padding: "6px 10px", borderRadius: 6, background: bg, color: fg,
    border: 0, fontSize: 11, fontWeight: 700, cursor: "pointer",
    whiteSpace: "nowrap",
  };
}


function ContractFormModal({ initial, onClose, onSaved }) {
  const isEdit = !!initial;
  const [subs, setSubs] = useState([]);
  const [plans, setPlans] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState({
    subscriber_id: initial?.subscriber_id || "",
    plan_id: initial?.plan_id || "",
    contract_number: initial?.contract_number || "",
    monthly_value: initial?.monthly_value || 0,
    due_day: initial?.due_day || 10,
    end_date: initial?.end_date || "",
    notes: initial?.notes || "",
    aging_policy: initial?.aging_policy || {
      grace_days: 3, reduce_days: 7, wall_garden_days: 15,
      suspend_days: 30, enabled: true,
    },
  });

  useEffect(() => {
    api.subscribersList({ limit: 200 })
      .then((r) => setSubs(r.items || []))
      .catch(() => {});
    api.plansList({ active: true })
      .then((r) => setPlans(r.items || []))
      .catch(() => {});
  }, []);

  function set(k, v) { setForm({ ...form, [k]: v }); }
  function setAging(k, v) {
    setForm({ ...form, aging_policy: { ...form.aging_policy, [k]: v } });
  }

  async function submit() {
    if (!form.subscriber_id || !form.plan_id) {
      setErr("Escolha assinante e plano"); return;
    }
    setBusy(true); setErr(null);
    try {
      const data = {
        ...form,
        monthly_value: parseFloat(form.monthly_value) || 0,
        due_day: parseInt(form.due_day) || 10,
        aging_policy: {
          grace_days: parseInt(form.aging_policy.grace_days),
          reduce_days: parseInt(form.aging_policy.reduce_days),
          wall_garden_days: parseInt(form.aging_policy.wall_garden_days),
          suspend_days: parseInt(form.aging_policy.suspend_days),
          enabled: !!form.aging_policy.enabled,
        },
      };
      if (isEdit) {
        await api.contractsPatch(initial.id, data);
      } else {
        await api.contractsCreate(data);
      }
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  return (
    <div onClick={onClose}
          style={{
            position: "fixed", inset: 0, zIndex: 9500,
            background: "rgba(15,23,42,0.75)",
            display: "grid", placeItems: "center", padding: 20,
            overflowY: "auto",
          }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{
              background: "#fff", borderRadius: 14, padding: 22,
              width: "100%", maxWidth: 640,
              maxHeight: "90vh", overflowY: "auto",
              boxShadow: "0 25px 60px rgba(0,0,0,0.4)",
            }}>
        <h3 style={{ margin: "0 0 16px", fontSize: 17, fontWeight: 800 }}>
          {isEdit ? "✏️ Editar Contrato" : "➕ Novo Contrato"}
        </h3>

        {!isEdit && (
          <Field label="Assinante *">
            <select data-testid="ct-form-subscriber"
                      value={form.subscriber_id}
                      onChange={(e) => set("subscriber_id", e.target.value)}
                      style={inp}>
              <option value="">— escolha —</option>
              {subs.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} {s.pppoe_user ? `(${s.pppoe_user})` : ""}
                </option>
              ))}
            </select>
          </Field>
        )}

        <Field label="Plano *">
          <select data-testid="ct-form-plan" value={form.plan_id}
                    onChange={(e) => set("plan_id", e.target.value)}
                    style={inp}>
            <option value="">— escolha —</option>
            {plans.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {p.speed_label || `${p.speed_down_mbps}M`}
                {" · "}{fmtBRL(p.monthly_price)}
              </option>
            ))}
          </select>
        </Field>

        <Row>
          <Field label="Número do contrato" half>
            <input data-testid="ct-form-number" value={form.contract_number}
                    onChange={(e) => set("contract_number", e.target.value)}
                    placeholder="auto-gerado se vazio" style={inp} />
          </Field>
          <Field label="Dia vencimento" half>
            <input data-testid="ct-form-dueday" type="number" min={1} max={31}
                    value={form.due_day}
                    onChange={(e) => set("due_day", e.target.value)}
                    style={inp} />
          </Field>
        </Row>
        <Row>
          <Field label="Valor mensal (R$)" half>
            <input data-testid="ct-form-value" type="number" step="0.01"
                    value={form.monthly_value}
                    onChange={(e) => set("monthly_value", e.target.value)}
                    style={inp} />
          </Field>
          <Field label="Data fim (opcional)" half>
            <input data-testid="ct-form-enddate" type="date"
                    value={form.end_date || ""}
                    onChange={(e) => set("end_date", e.target.value)}
                    style={inp} />
          </Field>
        </Row>

        {/* AGING POLICY */}
        <div style={{ marginTop: 14, padding: 14, background: "#fef9c3",
                        borderRadius: 10, border: "1px solid #fde047" }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                          marginBottom: 10, alignItems: "center" }}>
            <h4 style={{ margin: 0, fontSize: 13, fontWeight: 800,
                            color: "#713f12" }}>
              ⏰ Política de Aging RADIUS
            </h4>
            <label style={{ display: "flex", gap: 6, alignItems: "center",
                              fontSize: 11, fontWeight: 700,
                              color: "#713f12" }}>
              <input type="checkbox" data-testid="ct-aging-enabled"
                      checked={form.aging_policy.enabled}
                      onChange={(e) => setAging("enabled", e.target.checked)}
                      style={{ accentColor: "#ca8a04" }} />
              Habilitar aging automático
            </label>
          </div>
          <p style={{ margin: "0 0 10px", fontSize: 11, color: "#92400e",
                        lineHeight: 1.4 }}>
            Dias após o vencimento da fatura. <b>0 = pula esse estado.</b>
            {" "}Velocidade do estado REDUZIDO é configurada no plano.
          </p>
          <Row>
            <Field label="⏳ Tolerância (Grace)" half>
              <input data-testid="ct-aging-grace" type="number" min={0} max={30}
                      value={form.aging_policy.grace_days}
                      onChange={(e) => setAging("grace_days", e.target.value)}
                      style={inp} />
            </Field>
            <Field label="🟠 Reduzir velocidade" half>
              <input data-testid="ct-aging-reduce" type="number" min={0} max={60}
                      value={form.aging_policy.reduce_days}
                      onChange={(e) => setAging("reduce_days", e.target.value)}
                      style={inp} />
            </Field>
          </Row>
          <Row>
            <Field label="🔒 Wall Garden" half>
              <input data-testid="ct-aging-wg" type="number" min={0} max={90}
                      value={form.aging_policy.wall_garden_days}
                      onChange={(e) => setAging("wall_garden_days", e.target.value)}
                      style={inp} />
            </Field>
            <Field label="🔴 Suspender total" half>
              <input data-testid="ct-aging-suspend" type="number" min={0} max={180}
                      value={form.aging_policy.suspend_days}
                      onChange={(e) => setAging("suspend_days", e.target.value)}
                      style={inp} />
            </Field>
          </Row>
        </div>

        <Field label="Observações">
          <textarea data-testid="ct-form-notes" value={form.notes}
                      onChange={(e) => set("notes", e.target.value)} rows={2}
                      style={{ ...inp, resize: "vertical", marginTop: 12 }} />
        </Field>

        {err && (
          <div style={{ padding: 10, background: "#fef2f2", color: "#991b1b",
                          borderRadius: 7, fontSize: 12, marginBottom: 8 }}>
            ❌ {err}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button onClick={onClose} data-testid="ct-form-cancel"
                    style={{ padding: "8px 14px", borderRadius: 8,
                              background: "#f1f5f9", color: "#0f172a",
                              border: 0, fontSize: 12, fontWeight: 700,
                              cursor: "pointer" }}>Cancelar</button>
          <button onClick={submit} disabled={busy} data-testid="ct-form-save"
                    style={{ padding: "8px 14px", borderRadius: 8,
                              background: "#0ea5e9", color: "#fff",
                              border: 0, fontSize: 12, fontWeight: 700,
                              cursor: "pointer",
                              opacity: busy ? 0.5 : 1 }}>
            {busy ? "Salvando…" : "💾 Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}


function Field({ label, children, half }) {
  return (
    <div style={{ marginBottom: 12, flex: half ? 1 : "1 1 auto",
                    minWidth: 0 }}>
      <label style={{ fontSize: 11, color: "#64748b", fontWeight: 700,
                        display: "block", marginBottom: 4,
                        textTransform: "uppercase",
                        letterSpacing: 0.4 }}>{label}</label>
      {children}
    </div>
  );
}


function Row({ children }) {
  return <div style={{ display: "flex", gap: 10 }}>{children}</div>;
}


const inp = {
  width: "100%", padding: "8px 11px", border: "1px solid #cbd5e1",
  borderRadius: 7, fontSize: 13, outline: "none",
  background: "#fff", boxSizing: "border-box",
};
