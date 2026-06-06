import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Button } from "@/ui";

/**
 * RetentionPlaybookCard — "Modo Cliente Cancelando".
 * Mostra as regras configuráveis do playbook automático de retenção
 * + mural com clientes em risco para acompanhamento.
 */
export default function RetentionPlaybookCard() {
  const [cfg, setCfg] = useState(null);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [mural, setMural] = useState([]);
  const [err, setErr] = useState("");
  const [triggerOpen, setTriggerOpen] = useState(false);
  const [tPhone, setTPhone] = useState("");
  const [tName, setTName] = useState("");
  const [tReason, setTReason] = useState("");

  const loadAll = useCallback(async () => {
    try {
      const [c, m] = await Promise.all([
        api._client.get("/gestao-ia/retention/config").then((x) => x.data),
        api._client.get("/gestao-ia/retention/mural").then((x) => x.data),
      ]);
      setCfg(c);
      setDraft(c);
      setMural(m.items || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const dirty = draft && cfg && Object.keys(draft).some(
    (k) => draft[k] !== cfg[k],
  );

  async function save() {
    if (!dirty) return;
    setSaving(true);
    setErr("");
    try {
      const r = await api._client
        .post("/gestao-ia/retention/config", draft)
        .then((x) => x.data);
      setCfg(r);
      setDraft(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setSaving(false);
    }
  }

  async function trigger() {
    if (!tPhone) { setErr("Informe o telefone"); return; }
    setErr("");
    try {
      const r = await api._client.post(
        "/gestao-ia/retention/trigger",
        { phone: tPhone, customer_name: tName, risk_reason: tReason },
      ).then((x) => x.data);
      if (!r.ok) {
        setErr(r.reason || "Falha");
      } else {
        setTPhone(""); setTName(""); setTReason("");
        setTriggerOpen(false);
        loadAll();
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }

  async function setStatus(rid, status) {
    try {
      await api._client.patch(`/gestao-ia/retention/mural/${rid}`,
                                { status });
      loadAll();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }

  if (!cfg) return null;

  return (
    <section data-testid="retention-playbook-card" style={{
      marginTop: 18, padding: 18, borderRadius: 16,
      background: "linear-gradient(135deg,#7f1d1d 0%,#991b1b 50%,#7c2d12 100%)",
      color: "white",
    }}>
      <div style={{ display: "flex", alignItems: "center",
                      justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 26 }}></span>
          <div>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1,
                            color: "#fca5a5", textTransform: "uppercase" }}>
              Modo Cliente Cancelando · Playbook de Retenção
            </div>
            <div style={{ fontSize: 12, color: "#fee2e2" }}>
              Quando o ALVARO_IA detecta risco {cfg.trigger_risk.toUpperCase()},
              a Isabella envia oferta + cria bolha urgente automaticamente.
            </div>
          </div>
        </div>
        <label data-testid="retention-toggle-enabled" style={{
          display: "flex", alignItems: "center", gap: 8, fontSize: 12,
          fontWeight: 700, padding: "6px 12px", borderRadius: 999,
          background: draft.enabled ? "rgba(16,185,129,0.25)" : "rgba(255,255,255,0.10)",
          cursor: "pointer",
        }}>
          <input type="checkbox" checked={!!draft.enabled}
                  onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
                  style={{ width: 18, height: 18 }} />
          {draft.enabled ? "✅ Ativado" : "Desativado"}
        </label>
      </div>

      {err && (
        <div style={{ marginTop: 10, padding: 10, fontSize: 12,
                        background: "rgba(0,0,0,0.3)", borderRadius: 8,
                        color: "#fecaca" }}>{err}</div>
      )}

      {/* CONFIG FIELDS */}
      <div style={{ marginTop: 14, display: "grid",
                      gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
                      gap: 12 }}>
        <Field label="Risco que dispara">
          <select data-testid="retention-trigger-risk"
                    value={draft.trigger_risk}
                    onChange={(e) => setDraft({ ...draft, trigger_risk: e.target.value })}
                    style={selStyle}>
            <option value="alto">Alto (preventivo)</option>
            <option value="critico">Crítico (urgente)</option>
          </select>
        </Field>
        <Field label="Desconto pré-aprovado (%)">
          <input type="number" min={0} max={100}
                  data-testid="retention-discount"
                  value={draft.discount_pct}
                  onChange={(e) => setDraft({
                    ...draft,
                    discount_pct: parseInt(e.target.value || "0", 10),
                  })}
                  style={inpStyle} />
        </Field>
        <Field label="Janela de visita (horas)">
          <input type="number" min={1} max={168}
                  data-testid="retention-visit-window"
                  value={draft.visit_window_hours}
                  onChange={(e) => setDraft({
                    ...draft,
                    visit_window_hours: parseInt(e.target.value || "1", 10),
                  })}
                  style={inpStyle} />
        </Field>
        <Field label="Enviar WhatsApp automático">
          <select value={draft.auto_send_whatsapp ? "1" : "0"}
                    data-testid="retention-auto-whatsapp"
                    onChange={(e) => setDraft({
                      ...draft,
                      auto_send_whatsapp: e.target.value === "1",
                    })}
                    style={selStyle}>
            <option value="1">Sim</option>
            <option value="0">Não</option>
          </select>
        </Field>
        <Field label="Criar bolha urgente">
          <select value={draft.create_urgent_ticket ? "1" : "0"}
                    data-testid="retention-create-ticket"
                    onChange={(e) => setDraft({
                      ...draft,
                      create_urgent_ticket: e.target.value === "1",
                    })}
                    style={selStyle}>
            <option value="1">Sim</option>
            <option value="0">Não</option>
          </select>
        </Field>
      </div>

      <Field label="Template da mensagem (use {nome}, {discount_pct}, {visit_window_hours})">
        <textarea data-testid="retention-template"
                    value={draft.message_template}
                    onChange={(e) => setDraft({
                      ...draft, message_template: e.target.value,
                    })}
                    rows={6} style={{ ...inpStyle, fontFamily: "inherit",
                                          resize: "vertical" }} />
      </Field>

      <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Button onClick={save} disabled={!dirty || saving}
                 data-testid="retention-save-btn"
                 variant="primary"
                 style={{ background: dirty ? "#10b981" : "#475569",
                            color: "white" }}>
          {saving ? "Salvando..." : (dirty ? "Salvar regras" : "✓ Sem mudanças")}
        </Button>
        <Button onClick={() => setTriggerOpen(true)}
                 data-testid="retention-manual-trigger-btn"
                 style={{ background: "#a78bfa", color: "#1c1917" }}>
          Disparar manual
        </Button>
        {dirty && (
          <button onClick={() => setDraft(cfg)}
                   style={{ background: "transparent",
                              color: "#fca5a5", border: "none",
                              cursor: "pointer", fontSize: 12 }}>
            ✕ Descartar mudanças
          </button>
        )}
      </div>

      {/* MURAL */}
      <div style={{ marginTop: 18 }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: "#fca5a5",
                        textTransform: "uppercase", letterSpacing: 1,
                        marginBottom: 8 }}>
          Mural de Retenção — {mural.length} caso(s)
        </div>
        {mural.length === 0 ? (
          <div style={{ padding: 14, textAlign: "center",
                          background: "rgba(0,0,0,0.2)",
                          borderRadius: 10, fontSize: 12,
                          color: "#fee2e2" }}>
            Nenhum cliente em retenção no momento. Cinto e a IA está vigiando.
          </div>
        ) : (
          <div data-testid="retention-mural-list">
            {mural.map((m) => <MuralRow key={m.id} m={m} onStatus={setStatus} />)}
          </div>
        )}
      </div>

      {/* MODAL TRIGGER MANUAL */}
      {triggerOpen && (
        <div onClick={() => setTriggerOpen(false)} style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
          display: "grid", placeItems: "center", zIndex: 9999,
        }}>
          <div onClick={(e) => e.stopPropagation()} style={{
            background: "white", padding: 20, borderRadius: 14,
            color: "#0f172a", width: 360, maxWidth: "90vw",
          }} data-testid="retention-trigger-modal">
            <h3 style={{ marginTop: 0 }}>Disparar retenção</h3>
            <Field label="Telefone (DDD + número)" dark>
              <input data-testid="trigger-phone" value={tPhone}
                      onChange={(e) => setTPhone(e.target.value)}
                      placeholder="5521988887777"
                      style={{ ...inpStyle, color: "#0f172a",
                                  background: "#f8fafc" }} />
            </Field>
            <Field label="Nome do cliente" dark>
              <input data-testid="trigger-name" value={tName}
                      onChange={(e) => setTName(e.target.value)}
                      style={{ ...inpStyle, color: "#0f172a",
                                  background: "#f8fafc" }} />
            </Field>
            <Field label="Motivo" dark>
              <input data-testid="trigger-reason" value={tReason}
                      onChange={(e) => setTReason(e.target.value)}
                      style={{ ...inpStyle, color: "#0f172a",
                                  background: "#f8fafc" }} />
            </Field>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Button onClick={trigger} variant="primary"
                       data-testid="trigger-confirm-btn">Disparar</Button>
              <Button onClick={() => setTriggerOpen(false)}>Cancelar</Button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

const inpStyle = {
  width: "100%", padding: "8px 10px", borderRadius: 8,
  border: "1px solid rgba(255,255,255,0.18)",
  background: "rgba(0,0,0,0.25)", color: "white",
  fontSize: 13, marginTop: 4, boxSizing: "border-box",
};
const selStyle = { ...inpStyle };

function Field({ label, children, dark }) {
  return (
    <label style={{ display: "block", marginTop: 10 }}>
      <span style={{ fontSize: 10, fontWeight: 800,
                       letterSpacing: 0.5,
                       color: dark ? "#475569" : "#fecaca",
                       textTransform: "uppercase" }}>{label}</span>
      {children}
    </label>
  );
}

function MuralRow({ m, onStatus }) {
  const statusColors = {
    open: ["#fef3c7", "#92400e"],
    in_progress: ["#dbeafe", "#1e40af"],
    won: ["#dcfce7", "#166534"],
    lost: ["#fee2e2", "#991b1b"],
  };
  const [bg, color] = statusColors[m.status] || ["#f1f5f9", "#475569"];
  return (
    <div data-testid={`retention-row-${m.id}`} style={{
      padding: "10px 12px", marginBottom: 6, borderRadius: 10,
      background: "rgba(255,255,255,0.08)",
      border: "1px solid rgba(255,255,255,0.12)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 800 }}>
            {m.customer_name || "Cliente"}
            <span style={{ marginLeft: 6, fontSize: 9, padding: "1px 6px",
                              background: bg, color, borderRadius: 4,
                              fontWeight: 700, textTransform: "uppercase" }}>
              {m.status}
            </span>
          </div>
          <div style={{ fontSize: 11, color: "#fee2e2", marginTop: 2 }}>
            {m.phone} · {m.discount_pct}% off · WA: {m.whatsapp_status}
          </div>
          {m.risk_reason && (
            <div style={{ fontSize: 10, color: "#fecaca", marginTop: 2,
                            fontStyle: "italic" }}>
              “{m.risk_reason}”
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          <button onClick={() => onStatus(m.id, "in_progress")}
                   data-testid={`retention-status-progress-${m.id}`}
                   style={chip("#3b82f6")}>Em ação</button>
          <button onClick={() => onStatus(m.id, "won")}
                   data-testid={`retention-status-won-${m.id}`}
                   style={chip("#10b981")}>Salvo</button>
          <button onClick={() => onStatus(m.id, "lost")}
                   data-testid={`retention-status-lost-${m.id}`}
                   style={chip("#991b1b")}>Perdido</button>
        </div>
      </div>
    </div>
  );
}

function chip(bg) {
  return {
    padding: "4px 8px", borderRadius: 6, fontSize: 10, fontWeight: 700,
    background: bg, color: "white", border: "none", cursor: "pointer",
  };
}
