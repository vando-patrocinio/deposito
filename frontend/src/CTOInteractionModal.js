/*
CTOInteractionModal.js — Modal acionado ao clicar numa CTO no mapa da Rede IA.

2 abas:
  • Clientes ligados — lista ONUs com sinal, slot, status
  • Cadastrar novo  — provisiona nova ONU no slot livre + push pro SmartOLT

Usado em RedeIaMap.js.
*/
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Field, inputStyle } from "@/ui";
import {
  X, Users, Plus, Signal, MapPin, Loader2, CheckCircle2,
  AlertCircle, Search,
} from "lucide-react";

function statusColor(s) {
  const k = (s || "").toLowerCase();
  if (k === "online" || k === "ok") return "#16a34a";
  if (k === "warning") return "#ca8a04";
  if (k === "critical" || k === "alarm" || k === "los") return "#dc2626";
  if (k === "provisioning") return "#6366f1";
  return "#64748b";
}

export default function CTOInteractionModal({ ctoId, ctoMeta, onClose }) {
  const [tab, setTab] = useState("clients");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.redeIaCtoClients(ctoId);
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [ctoId]);

  return (
    <div onClick={onClose}
           data-testid="cto-modal"
           style={{
             position: "fixed", inset: 0, zIndex: 9999,
             background: "rgba(0,0,0,0.55)",
             display: "flex", alignItems: "center", justifyContent: "center",
             padding: 12,
           }}>
      <div onClick={(e) => e.stopPropagation()}
             style={{
               background: "#fff", borderRadius: 14,
               width: "min(820px, 100%)", maxHeight: "90vh",
               display: "flex", flexDirection: "column",
               boxShadow: "0 18px 50px rgba(0,0,0,0.35)",
             }}>
        {/* Header */}
        <div style={{ padding: "14px 18px",
                        borderBottom: "1px solid #e2e8f0",
                        display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 9,
            background: "linear-gradient(135deg,#6366f1,#8b5cf6)",
            display: "grid", placeItems: "center", color: "#fff",
          }}>
            <MapPin size={18} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>
              {data?.cto?.name || ctoMeta?.name || "CTO"}
            </div>
            <div style={{ fontSize: 11, color: "#64748b" }}>
              {data?.cto?.sigla ? `Sigla: ${data.cto.sigla} · ` : ""}
              Capacidade: {data?.cto?.capacity || ctoMeta?.capacity || "—"}
              {data ? ` · ${data.total_clients} ocupado(s) · ${data.free_count} livre(s)` : ""}
            </div>
          </div>
          <button onClick={onClose}
                    data-testid="cto-modal-close"
                    style={{
                      padding: 6, border: "1px solid #e2e8f0",
                      background: "#fff", borderRadius: 8, cursor: "pointer",
                    }}><X size={16} /></button>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0" }}>
          {[
            { id: "clients", label: "Clientes ligados", icon: Users },
            { id: "new",     label: "Cadastrar novo cliente", icon: Plus },
          ].map((t) => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <button key={t.id}
                        onClick={() => setTab(t.id)}
                        data-testid={`cto-tab-${t.id}`}
                        style={{
                          flex: 1, padding: "12px 14px", border: 0,
                          background: "transparent", cursor: "pointer",
                          fontSize: 13, fontWeight: active ? 700 : 500,
                          color: active ? "#7c3aed" : "#64748b",
                          borderBottom: "2px solid " + (active ? "#7c3aed" : "transparent"),
                          display: "inline-flex", justifyContent: "center",
                          alignItems: "center", gap: 6,
                        }}>
                <Icon size={14} /> {t.label}
              </button>
            );
          })}
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
          {err && (
            <div style={{ padding: 10, background: "#fef2f2", color: "#991b1b",
                            borderRadius: 8, fontSize: 12, marginBottom: 10 }}>
              {err}
            </div>
          )}
          {loading ? (
            <div style={{ padding: 24, textAlign: "center", color: "#64748b" }}>
              <Loader2 size={16} className="animate-spin" /> Carregando…
            </div>
          ) : tab === "clients" ? (
            <ClientsList data={data} />
          ) : (
            <ProvisionForm cto={data?.cto} ctoId={ctoId}
                              freeSlots={data?.free_slots || []}
                              onCreated={async () => { await load(); setTab("clients"); }} />
          )}
        </div>
      </div>
    </div>
  );
}

function ClientsList({ data }) {
  if (!data) return null;
  if (!data.clients?.length) {
    return (
      <div style={{ padding: 24, textAlign: "center", fontSize: 13,
                      color: "#64748b" }}>
        Nenhum cliente ligado nesta CTO ainda. Use a aba <strong>Cadastrar
        novo cliente</strong> pra provisionar a primeira ONU.
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: 8 }} data-testid="cto-clients-list">
      {data.clients.map((c, i) => (
        <div key={c.sn || i}
               data-testid={`cto-client-${c.sn || i}`}
               style={{
                 padding: 11, borderRadius: 10,
                 border: "1px solid #e2e8f0",
                 background: "#fff",
                 display: "grid",
                 gridTemplateColumns: "auto 1fr auto auto",
                 gap: 10, alignItems: "center",
               }}>
          <div style={{
            minWidth: 30, textAlign: "center",
            fontSize: 10, fontWeight: 800,
            padding: "3px 7px", borderRadius: 4,
            background: "#f1f5f9", color: "#475569",
          }}>SLOT {c.slot ?? "?"}</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 13, color: "#0f172a" }}>
              {c.name}
            </div>
            <div style={{ fontSize: 11, color: "#64748b" }}>
              SN: <code>{c.sn || "—"}</code>
              {c.olt_name ? ` · ${c.olt_name} B${c.board}/P${c.port}` : ""}
            </div>
          </div>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            fontSize: 12, fontWeight: 600,
            color: statusColor(c.signal_status),
          }}>
            <Signal size={12} />
            {c.signal_dbm != null ? `${c.signal_dbm} dBm` : "—"}
          </div>
          <span style={{
            padding: "2px 8px", borderRadius: 8,
            fontSize: 10, fontWeight: 700, textTransform: "uppercase",
            background: statusColor(c.status) + "1a",
            color: statusColor(c.status),
          }}>{c.status || "—"}</span>
        </div>
      ))}
    </div>
  );
}

function ProvisionForm({ cto, ctoId, freeSlots, onCreated }) {
  const [form, setForm] = useState({
    sn: "", customer_name: "", customer_external_id: "",
    plan_id: "", plan_name: "",
    slot: freeSlots[0] || "",
    pppoe_user: "", pppoe_pwd: "",
    vlan: "", notes: "",
  });
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  // Autocomplete de cliente Atlaz
  useEffect(() => {
    const q = (form.customer_name || "").trim();
    if (q.length < 3 || form.customer_external_id) {
      setResults([]); return;
    }
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const r = await api._client.get(
          `/atlaz/clients?q=${encodeURIComponent(q)}&limit=8`,
        ).then((x) => x.data);
        setResults(Array.isArray(r) ? r : (r.clients || []));
      } catch {
        setResults([]);
      } finally { setSearching(false); }
    }, 350);
    return () => clearTimeout(t);
  }, [form.customer_name, form.customer_external_id]);

  const pickCustomer = (c) => {
    setForm((s) => ({
      ...s,
      customer_name: c.name || c.full_name || "",
      customer_external_id: String(c.external_id || c.id || ""),
      plan_id: c.plan_id || s.plan_id,
      plan_name: c.plan_name || s.plan_name,
    }));
    setResults([]);
  };

  const canSubmit = form.sn.trim().length >= 4
    && form.customer_name.trim().length >= 2
    && Number(form.slot) >= 1;

  const submit = async () => {
    setSubmitting(true); setResult(null);
    try {
      const r = await api.redeIaCtoProvision(ctoId, {
        sn: form.sn.trim().toUpperCase(),
        customer_name: form.customer_name.trim(),
        customer_external_id: form.customer_external_id || null,
        plan_id: form.plan_id || null,
        plan_name: form.plan_name || null,
        slot: Number(form.slot),
        pppoe_user: form.pppoe_user || null,
        pppoe_pwd: form.pppoe_pwd || null,
        vlan: form.vlan ? Number(form.vlan) : null,
        notes: form.notes || null,
      });
      setResult({ ok: true, ...r });
      setTimeout(() => onCreated?.(), 1200);
    } catch (e) {
      setResult({
        ok: false,
        error: e?.response?.data?.detail || e.message,
      });
    } finally { setSubmitting(false); }
  };

  return (
    <div style={{ display: "grid", gap: 14 }} data-testid="cto-provision-form">
      <div style={{ padding: 10,
                      background: "#eef2ff", borderRadius: 8,
                      fontSize: 11.5, color: "#3730a3" }}>
        💡 <strong>CTO:</strong> {cto?.name} · Slots livres: {freeSlots.length}
        {freeSlots.length > 0 && (
          <div style={{ marginTop: 4, fontSize: 10.5 }}>
            Próximos: {freeSlots.slice(0, 10).join(", ")}
            {freeSlots.length > 10 ? "…" : ""}
          </div>
        )}
      </div>

      <div style={{ display: "grid",
                      gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="SN / MAC da ONU *">
          <input type="text" value={form.sn}
                   onChange={(e) => setForm((s) => ({ ...s, sn: e.target.value }))}
                   data-testid="prov-sn-input"
                   placeholder="HWTC1A2B3C4D"
                   style={{ ...inputStyle, fontFamily: "JetBrains Mono, monospace",
                              textTransform: "uppercase" }} />
        </Field>
        <Field label="Slot da CTO *">
          <select value={form.slot}
                    onChange={(e) => setForm((s) => ({ ...s, slot: e.target.value }))}
                    data-testid="prov-slot-select"
                    style={inputStyle}>
            <option value="">Selecione…</option>
            {freeSlots.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </Field>
      </div>

      <div style={{ position: "relative" }}>
        <Field label="Cliente Atlaz *">
          <div style={{ position: "relative" }}>
            <input type="text" value={form.customer_name}
                     onChange={(e) => {
                       setForm((s) => ({ ...s, customer_name: e.target.value,
                                          customer_external_id: "" }));
                     }}
                     data-testid="prov-customer-input"
                     placeholder="Digite o nome…"
                     style={{ ...inputStyle, paddingRight: 28 }} />
            {searching ? (
              <Loader2 size={14} className="animate-spin"
                          style={{ position: "absolute", right: 8, top: 10,
                                    color: "#94a3b8" }} />
            ) : (
              <Search size={14}
                        style={{ position: "absolute", right: 8, top: 10,
                                  color: "#94a3b8" }} />
            )}
          </div>
        </Field>
        {results.length > 0 && (
          <div style={{
            position: "absolute", top: "100%", left: 0, right: 0,
            zIndex: 10, background: "#fff",
            border: "1px solid #cbd5e1", borderRadius: 8,
            maxHeight: 220, overflow: "auto",
            boxShadow: "0 8px 20px rgba(0,0,0,0.08)",
          }} data-testid="prov-customer-results">
            {results.map((c, i) => (
              <button key={i} onClick={() => pickCustomer(c)}
                        style={{
                          width: "100%", padding: "8px 12px",
                          border: 0, borderBottom: i < results.length - 1
                            ? "1px solid #f1f5f9" : 0,
                          background: "#fff", cursor: "pointer",
                          textAlign: "left", fontSize: 12.5,
                        }}>
                <div style={{ fontWeight: 600, color: "#0f172a" }}>
                  {c.name || c.full_name}
                </div>
                <div style={{ fontSize: 10.5, color: "#64748b" }}>
                  #{c.external_id || c.id}
                  {c.plan_name ? ` · ${c.plan_name}` : ""}
                  {c.address ? ` · ${c.address}` : ""}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: "grid",
                      gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="Plano (opcional)">
          <input type="text" value={form.plan_name}
                   onChange={(e) => setForm((s) => ({ ...s, plan_name: e.target.value }))}
                   data-testid="prov-plan-input"
                   placeholder="Fibra 600 Mb"
                   style={inputStyle} />
        </Field>
        <Field label="VLAN (opcional)">
          <input type="number" value={form.vlan} min="1" max="4094"
                   onChange={(e) => setForm((s) => ({ ...s, vlan: e.target.value }))}
                   data-testid="prov-vlan-input"
                   style={inputStyle} />
        </Field>
      </div>

      <div style={{ display: "grid",
                      gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="PPPoE user (opcional)">
          <input type="text" value={form.pppoe_user}
                   onChange={(e) => setForm((s) => ({ ...s, pppoe_user: e.target.value }))}
                   data-testid="prov-pppoe-user-input"
                   style={inputStyle} />
        </Field>
        <Field label="PPPoE password (opcional)">
          <input type="text" value={form.pppoe_pwd}
                   onChange={(e) => setForm((s) => ({ ...s, pppoe_pwd: e.target.value }))}
                   data-testid="prov-pppoe-pwd-input"
                   style={inputStyle} />
        </Field>
      </div>

      <Field label="Observações (opcional)">
        <textarea value={form.notes} rows={2}
                    onChange={(e) => setForm((s) => ({ ...s, notes: e.target.value }))}
                    data-testid="prov-notes-input"
                    style={{ ...inputStyle, resize: "vertical",
                              fontFamily: "inherit" }} />
      </Field>

      {result && (
        result.ok ? (
          <div data-testid="prov-success"
                 style={{ padding: 12, borderRadius: 8,
                          background: "#dcfce7", color: "#166534",
                          display: "flex", gap: 8, alignItems: "center",
                          fontSize: 13 }}>
            <CheckCircle2 size={16} />
            {result.message || "Cadastrado!"}
            {!result.smartolt_synced && (
              <span style={{ marginLeft: "auto", fontSize: 11,
                              color: "#92400e", fontWeight: 600 }}>
                ⚠️ SmartOLT pendente
              </span>
            )}
          </div>
        ) : (
          <div data-testid="prov-error"
                 style={{ padding: 12, borderRadius: 8,
                          background: "#fee2e2", color: "#991b1b",
                          display: "flex", gap: 8, alignItems: "center",
                          fontSize: 13 }}>
            <AlertCircle size={16} /> {result.error}
          </div>
        )
      )}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button onClick={submit} disabled={!canSubmit || submitting}
                  data-testid="prov-submit-btn"
                  style={{
                    padding: "10px 18px", border: 0,
                    background: !canSubmit
                      ? "#cbd5e1"
                      : "linear-gradient(135deg, #10b981, #059669)",
                    color: "#fff", borderRadius: 10,
                    cursor: !canSubmit || submitting ? "not-allowed" : "pointer",
                    fontSize: 13, fontWeight: 700,
                    display: "inline-flex", alignItems: "center", gap: 6,
                  }}>
          <Plus size={14} />
          {submitting ? "Cadastrando…" : "Cadastrar ONU"}
        </button>
      </div>
    </div>
  );
}
