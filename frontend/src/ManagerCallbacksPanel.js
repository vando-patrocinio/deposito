/**
 * ManagerCallbacksPanel — sub-aba da Lousa para o gestor resolver os
 * pedidos de contato com o cliente abertos pelos técnicos.
 *
 * Fluxo: técnico não conseguiu executar OS → frontend envia `outcome=informada`
 *   → backend cria um `lousa_manager_callback_requests` (pending) e pausa
 *   a OS original (`needs_manager_action=true`).
 *
 * O gestor decide um destes 3 caminhos (após contatar o cliente):
 *   1. ✅ Fechar improdutiva — fecha a OS original com outcome=informada
 *   2. Liberar de volta    — devolve OS pro técnico (mesmo ou outro,
 *                                opcionalmente reagendada)
 *   3. 🆕 Criar nova OS       — abre OS NOVA pra continuar o serviço
 *                                (a original CONTINUA pausada — gestor
 *                                ainda precisa optar entre fechar/liberar)
 */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";

function fmtDateBr(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR",
      { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
}

function StatusBadge({ status }) {
  const map = {
    pending: { bg: "#fef3c7", fg: "#92400e", label: "⏳ Pendente" },
    contacted: { bg: "#dbeafe", fg: "#1e40af", label: "Contatado" },
    resolved: { bg: "#dcfce7", fg: "#14532d", label: "✅ Resolvido" },
  };
  const c = map[status] || map.pending;
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 99, background: c.bg,
      color: c.fg, fontSize: 11, fontWeight: 700,
    }}>{c.label}</span>
  );
}

export default function ManagerCallbacksPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [err, setErr] = useState(null);
  const [actionFor, setActionFor] = useState(null); // { req, mode }
  const [collabs, setCollabs] = useState([]);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await api.lousaManagerCallbacks(statusFilter, 100);
      setItems(r.items || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    api.listCollaborators().then((r) =>
      setCollabs(Array.isArray(r) ? r : (r?.items || [])))
      .catch(() => {});
  }, []);

  async function doResolveClose(req) {
    const obs = window.prompt(
      "Motivo de FECHAR como improdutiva (mínimo 5 chars):",
      "Cliente contatado — não foi possível agendar / desistiu.");
    if (!obs || obs.trim().length < 5) return;
    try {
      await api.lousaManagerCallbackResolve(req.id, {
        action: "resolved_close",
        observacao: obs.trim(),
        close_outcome: "informada",
      });
      window.alert("OS fechada como improdutiva.");
      await load();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  }

  return (
    <div data-testid="manager-callbacks-panel">
      {/* Filtros */}
      <div style={{ display: "flex", gap: 6, marginBottom: 14,
                      alignItems: "center" }}>
        <span style={{ fontWeight: 800, color: "#0f172a", marginRight: 8 }}>
          OSs aguardando contato do gestor
        </span>
        {["pending", "contacted", "resolved", "all"].map((s) => (
          <button key={s} data-testid={`callback-filter-${s}`}
                    onClick={() => setStatusFilter(s)}
                    style={{
                      padding: "5px 11px", borderRadius: 7, fontSize: 12,
                      fontWeight: 700, cursor: "pointer",
                      background: statusFilter === s ? "#0f172a" : "#fff",
                      color: statusFilter === s ? "#fff" : "#0f172a",
                      border: `1.5px solid ${
                        statusFilter === s ? "#0f172a" : "#cbd5e1"}`,
                    }}>
            {s === "pending" ? "Pendentes" :
              s === "contacted" ? "Contatados" :
              s === "resolved" ? "Resolvidos" : "Todos"}
          </button>
        ))}
        <button data-testid="callback-refresh" onClick={load}
                  style={{ marginLeft: "auto", padding: "5px 11px",
                            background: "#f1f5f9", border: "1px solid #cbd5e1",
                            borderRadius: 7, fontSize: 12, fontWeight: 700,
                            cursor: "pointer" }}>
          Atualizar
        </button>
      </div>

      {loading && (
        <div data-testid="callback-loading"
              style={{ padding: 30, textAlign: "center", color: "#64748b" }}>
          ⏳ Carregando…
        </div>
      )}
      {err && (
        <div data-testid="callback-error"
              style={{ padding: 14, background: "#fef2f2", color: "#991b1b",
                        borderRadius: 8 }}>❌ {err}</div>
      )}
      {!loading && !err && items.length === 0 && (
        <div data-testid="callback-empty"
              style={{ padding: 40, textAlign: "center", color: "#64748b",
                        background: "#f8fafc", borderRadius: 8 }}>
          Nenhum pedido de contato {statusFilter === "pending" ? "pendente" : ""}.
        </div>
      )}

      <div style={{ display: "grid", gap: 10 }}>
        {items.map((req) => (
          <CallbackCard key={req.id} req={req}
            onCloseImprodutiva={() => doResolveClose(req)}
            onCreateNew={() => setActionFor({ req, mode: "create_new" })}
            onReleaseBack={() => setActionFor({ req, mode: "release_back" })}
          />
        ))}
      </div>

      {actionFor && actionFor.mode === "create_new" && (
        <CreateNewOsModal req={actionFor.req} collabs={collabs}
          onClose={() => setActionFor(null)}
          onCreated={() => { setActionFor(null); load(); }} />
      )}
      {actionFor && actionFor.mode === "release_back" && (
        <ReleaseBackModal req={actionFor.req} collabs={collabs}
          onClose={() => setActionFor(null)}
          onDone={() => { setActionFor(null); load(); }} />
      )}
    </div>
  );
}


function CallbackCard({ req, onCloseImprodutiva, onCreateNew, onReleaseBack }) {
  const hasNew = !!req.new_ticket_id;
  return (
    <div data-testid={`callback-card-${req.id}`}
          style={{
            background: "#fff", border: "1px solid #e2e8f0",
            borderLeft: req.status === "pending"
              ? "4px solid #f59e0b"
              : (req.status === "contacted" ? "4px solid #0ea5e9" : "4px solid #16a34a"),
            borderRadius: 10, padding: 14,
          }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      gap: 14, alignItems: "flex-start", marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center",
                          marginBottom: 4, flexWrap: "wrap" }}>
            <StatusBadge status={req.status} />
            <span style={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>
              {req.client_name || "(sem nome)"}
            </span>
            {req.ticket_atlaz_protocolo && (
              <span style={{
                background: "#fef3c7", color: "#713f12",
                padding: "1px 7px", borderRadius: 99, fontSize: 11,
                fontWeight: 700,
              }}>#{req.ticket_atlaz_protocolo}</span>
            )}
          </div>
          <div style={{ fontSize: 12, color: "#475569", marginBottom: 4 }}>
            {req.client_address || "—"}
            {req.client_neighborhood ? ` · ${req.client_neighborhood}` : ""}
          </div>
          <div style={{ fontSize: 12, color: "#475569", marginBottom: 4 }}>
            Técnico: <b>{req.collaborator_name}</b>
            {req.client_phone && (
              <> · <a href={`tel:${req.client_phone}`}
                          style={{ color: "#0ea5e9" }}>{req.client_phone}</a></>
            )}
          </div>
          <div style={{ marginTop: 8, padding: 10,
                          background: "#fef3c7", borderRadius: 7,
                          fontSize: 13, color: "#78350f", lineHeight: 1.5 }}>
            <strong>Motivo:</strong> {req.motivo}
          </div>
        </div>
        <div style={{ fontSize: 11, color: "#94a3b8", textAlign: "right",
                        whiteSpace: "nowrap" }}>
          ⏰ {fmtDateBr(req.requested_at || req.created_at)}
        </div>
      </div>

      {hasNew && (
        <div style={{ marginTop: 8, padding: "8px 10px",
                        background: "#dbeafe", color: "#1e3a8a",
                        borderRadius: 7, fontSize: 12, fontWeight: 600 }}>
          🆕 Nova OS criada:
          <code style={{ background: "#fff", padding: "1px 6px",
                          borderRadius: 4, marginLeft: 4 }}>
            {req.new_ticket_id}
          </code>
          {req.new_ticket_created_at &&
            <> · {fmtDateBr(req.new_ticket_created_at)}</>}
        </div>
      )}

      {req.status === "pending" && (
        <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
          <button data-testid={`callback-create-new-${req.id}`}
                    onClick={onCreateNew}
                    style={btn("#0ea5e9", "#fff")}>
            🆕 Criar nova OS (continuar serviço)
          </button>
          <button data-testid={`callback-release-${req.id}`}
                    onClick={onReleaseBack}
                    style={btn("#16a34a", "#fff")}>
            Liberar OS de volta
          </button>
          <button data-testid={`callback-close-${req.id}`}
                    onClick={onCloseImprodutiva}
                    style={btn("#dc2626", "#fff")}>
            ✗ Fechar improdutiva
          </button>
        </div>
      )}
      {req.status === "contacted" && req.manager_observacao && (
        <div style={{ marginTop: 8, padding: "8px 10px",
                        background: "#f1f5f9", borderRadius: 7,
                        fontSize: 12, color: "#475569" }}>
          <b>Gestor anotou:</b> {req.manager_observacao}
        </div>
      )}
      {req.status === "resolved" && (
        <div style={{ marginTop: 8, padding: "8px 10px",
                        background: "#f0fdf4", borderRadius: 7,
                        fontSize: 12, color: "#14532d" }}>
          ✓ Resolvido por <b>{req.manager_name || "Gestor"}</b>
          {" "}({req.manager_action || "ação"}){req.resolved_at
            ? ` · ${fmtDateBr(req.resolved_at)}` : ""}
          {req.manager_observacao && (
            <div style={{ marginTop: 4, fontWeight: 600 }}>
              {req.manager_observacao}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function btn(bg, fg) {
  return {
    padding: "8px 14px", borderRadius: 8, background: bg, color: fg,
    border: 0, fontSize: 12, fontWeight: 700, cursor: "pointer",
  };
}


function CreateNewOsModal({ req, collabs, onClose, onCreated }) {
  const [form, setForm] = useState({
    client_name: req.client_name || "",
    address: req.client_address || "",
    neighborhood: req.client_neighborhood || "",
    phone: req.client_phone || "",
    relato: `Continuação do atendimento anterior (motivo: ${req.motivo || ""})`,
    pppoe_user: "",
    type: req.ticket_type || "reparo",
    priority: "normal",
    scheduled_time: "",
    assigned_collaborator_id: req.collaborator_id || "",
    observacao: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  function f(k) { return (e) => setForm({ ...form,
    [k]: e?.target ? e.target.value : e }); }

  async function submit() {
    if (!form.observacao || form.observacao.trim().length < 5) {
      setErr("Observação mínima 5 caracteres");
      return;
    }
    if (!form.client_name || !form.address ||
        !form.assigned_collaborator_id) {
      setErr("Preencha cliente, endereço e técnico");
      return;
    }
    setBusy(true); setErr(null);
    try {
      const r = await api.lousaManagerCallbackCreateNewTicket(req.id, form);
      window.alert(r.message
        + `\n\nNova OS: ${r.new_ticket_id}`);
      onCreated();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  return (
    <ModalShell title="🆕 Criar nova OS — continuar serviço" onClose={onClose}>
      <div style={{ padding: 16, background: "#dbeafe",
                      borderRadius: 8, marginBottom: 14, fontSize: 12,
                      color: "#1e3a8a", lineHeight: 1.5 }}>
        ℹ️ Esta OS é uma <b>continuação</b> do atendimento anterior.
        A OS original <b>continuará pausada</b> até você decidir
        (fechar improdutiva ou liberar de volta).
      </div>

      <Field label="Cliente *">
        <input data-testid="new-os-client-name" value={form.client_name}
                onChange={f("client_name")} style={inp} />
      </Field>
      <Field label="Endereço *">
        <input data-testid="new-os-address" value={form.address}
                onChange={f("address")} style={inp} />
      </Field>
      <Row>
        <Field label="Bairro" half>
          <input data-testid="new-os-neighborhood"
                  value={form.neighborhood}
                  onChange={f("neighborhood")} style={inp} />
        </Field>
        <Field label="Telefone" half>
          <input data-testid="new-os-phone" value={form.phone}
                  onChange={f("phone")} style={inp} />
        </Field>
      </Row>
      <Row>
        <Field label="Tipo" half>
          <select data-testid="new-os-type" value={form.type}
                    onChange={f("type")} style={inp}>
            <option value="reparo">Reparo</option>
            <option value="instalacao">Instalação</option>
            <option value="retirada">Retirada</option>
            <option value="prioridade">Prioridade</option>
            <option value="preventiva">Preventiva</option>
          </select>
        </Field>
        <Field label="Prioridade" half>
          <select data-testid="new-os-priority" value={form.priority}
                    onChange={f("priority")} style={inp}>
            <option value="normal">Normal</option>
            <option value="horario">Horário</option>
            <option value="prioridade">Prioridade</option>
            <option value="urgente">Urgente</option>
          </select>
        </Field>
      </Row>
      <Row>
        <Field label="Técnico *" half>
          <select data-testid="new-os-collab"
                    value={form.assigned_collaborator_id}
                    onChange={f("assigned_collaborator_id")} style={inp}>
            <option value="">— escolha —</option>
            {collabs.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Data/Hora agendada" half>
          <input data-testid="new-os-scheduled" type="datetime-local"
                  value={form.scheduled_time}
                  onChange={f("scheduled_time")} style={inp} />
        </Field>
      </Row>
      <Field label="PPPoE (opcional)">
        <input data-testid="new-os-pppoe" value={form.pppoe_user}
                onChange={f("pppoe_user")} style={inp} />
      </Field>
      <Field label="Relato / contexto do serviço">
        <textarea data-testid="new-os-relato" value={form.relato}
                    onChange={f("relato")} rows={2}
                    style={{ ...inp, resize: "vertical" }} />
      </Field>
      <Field label="Anotação do contato com o cliente * (mín 5 chars)">
        <textarea data-testid="new-os-obs" value={form.observacao}
                    onChange={f("observacao")} rows={2}
                    placeholder="Ex: Cliente confirmou reagendamento para amanhã às 14h."
                    style={{ ...inp, resize: "vertical" }} />
      </Field>

      {err && (
        <div style={{ padding: 10, background: "#fef2f2", color: "#991b1b",
                        borderRadius: 7, fontSize: 12, marginBottom: 8 }}>
          ❌ {err}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button data-testid="new-os-cancel" onClick={onClose}
                  style={btn("#f1f5f9", "#0f172a")}>Cancelar</button>
        <button data-testid="new-os-submit" onClick={submit} disabled={busy}
                  style={{ ...btn("#0ea5e9", "#fff"),
                              opacity: busy ? 0.5 : 1 }}>
          {busy ? "Criando…" : "🆕 Criar nova OS"}
        </button>
      </div>
    </ModalShell>
  );
}


function ReleaseBackModal({ req, collabs, onClose, onDone }) {
  const [obs, setObs] = useState("");
  const [collab, setCollab] = useState(req.collaborator_id || "");
  const [time, setTime] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function submit() {
    if (obs.trim().length < 5) { setErr("Observação mínima 5 chars"); return; }
    setBusy(true); setErr(null);
    try {
      await api.lousaManagerCallbackReleaseBack(req.id, {
        observacao: obs.trim(),
        new_collaborator_id: collab,
        new_scheduled_time: time || "",
      });
      window.alert("OS liberada de volta pro técnico!");
      onDone();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  return (
    <ModalShell title="Liberar OS de volta" onClose={onClose}>
      <div style={{ padding: 14, background: "#dcfce7",
                      borderRadius: 8, marginBottom: 14, fontSize: 12,
                      color: "#14532d", lineHeight: 1.5 }}>
        ✓ Devolve a OS original pro técnico (mesmo ou outro), opcionalmente
        reagendada. A OS volta a aparecer na lousa dele.
      </div>
      <Field label="O que o cliente respondeu? * (mín 5 chars)">
        <textarea data-testid="release-back-obs" value={obs}
                    onChange={(e) => setObs(e.target.value)} rows={2}
                    placeholder="Ex: Cliente vai estar em casa amanhã às 14h."
                    style={{ ...inp, resize: "vertical" }} />
      </Field>
      <Row>
        <Field label="Realocar técnico? (deixe igual se não)" half>
          <select data-testid="release-back-collab"
                    value={collab}
                    onChange={(e) => setCollab(e.target.value)} style={inp}>
            <option value="">— mesmo técnico —</option>
            {collabs.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Reagendar data/hora (opcional)" half>
          <input data-testid="release-back-time" type="datetime-local"
                  value={time} onChange={(e) => setTime(e.target.value)}
                  style={inp} />
        </Field>
      </Row>
      {err && (
        <div style={{ padding: 10, background: "#fef2f2", color: "#991b1b",
                        borderRadius: 7, fontSize: 12, marginBottom: 8 }}>
          ❌ {err}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button data-testid="release-back-cancel" onClick={onClose}
                  style={btn("#f1f5f9", "#0f172a")}>Cancelar</button>
        <button data-testid="release-back-submit" onClick={submit}
                  disabled={busy}
                  style={{ ...btn("#16a34a", "#fff"),
                              opacity: busy ? 0.5 : 1 }}>
          {busy ? "Liberando…" : "Liberar de volta"}
        </button>
      </div>
    </ModalShell>
  );
}


function ModalShell({ title, onClose, children }) {
  return (
    <div data-testid="callback-modal"
          style={{
            position: "fixed", inset: 0, zIndex: 9500,
            background: "rgba(15,23,42,0.75)",
            display: "grid", placeItems: "center", padding: 20,
            overflowY: "auto",
          }}
          onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
            style={{
              background: "#fff", borderRadius: 14, padding: 22,
              width: "100%", maxWidth: 640,
              maxHeight: "90vh", overflowY: "auto",
              boxShadow: "0 25px 60px rgba(0,0,0,0.4)",
            }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800,
                          color: "#0f172a" }}>{title}</h3>
          <button data-testid="callback-modal-close" onClick={onClose}
                    style={{ background: "transparent", border: 0,
                              fontSize: 22, cursor: "pointer",
                              color: "#94a3b8" }}>×</button>
        </div>
        {children}
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
                        textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </label>
      {children}
    </div>
  );
}


function Row({ children }) {
  return (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
      {children}
    </div>
  );
}


const inp = {
  width: "100%", padding: "8px 11px", border: "1px solid #cbd5e1",
  borderRadius: 7, fontSize: 13, outline: "none",
  background: "#fff", boxSizing: "border-box",
};
