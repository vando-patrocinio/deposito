/* FleetTenantsTab.js — Multi-tenant white-label. Cada cliente que comprar
 * o serviço de rastreamento vira um tenant; veículos atribuídos a um tenant
 * só são visíveis para usuários daquele tenant. */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import FleetTenantPortalUsersModal from "@/fleet/FleetTenantPortalUsersModal";

export default function FleetTenantsTab() {
  const [tenants, setTenants] = useState([]);
  const [portalFor, setPortalFor] = useState(null);   // tenant atual
  const [form, setForm] = useState({ name: "", contact_email: "",
                                       contact_phone: "", monthly_fee: 0 });
  const [err, setErr] = useState("");

  const reload = async () => {
    try {
      const r = await api._client.get("/fleet-tracking/tenants")
        .then((x) => x.data);
      setTenants(r);
    } catch { /* ignore */ }
  };

  useEffect(() => { reload(); }, []);

  const save = async () => {
    if (!form.name) return setErr("Nome obrigatório");
    try {
      await api._client.post("/fleet-tracking/tenants", {
        ...form, monthly_fee: Number(form.monthly_fee) || 0,
      });
      setForm({ name: "", contact_email: "", contact_phone: "",
                 monthly_fee: 0 });
      setErr("");
      reload();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  };

  const remove = async (tid) => {
    if (!window.confirm("Excluir este cliente?")) return;
    try {
      await api._client.delete(`/fleet-tracking/tenants/${tid}`);
      reload();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
  };

  return (
    <div data-testid="fleet-tenants-tab" style={{ display: "grid", gap: 12 }}>
      <div style={card}>
        <h3 style={{ margin: "0 0 8px" }}>Novo cliente revenda</h3>
        <p style={{ color: "#64748b", fontSize: 12, marginTop: 0 }}>
          Cadastre os clientes que vão pagar pelo serviço de rastreamento.
          Cada veículo pode ser atribuído a um cliente — eles só veem os
          carros deles.
        </p>
        <div style={{ display: "grid",
                       gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {field("Nome / Razão social", form.name,
                  (v) => setForm({ ...form, name: v }), "fleet-tnt-name")}
          {field("E-mail de contato", form.contact_email,
                  (v) => setForm({ ...form, contact_email: v }),
                  "fleet-tnt-email")}
          {field("Telefone", form.contact_phone,
                  (v) => setForm({ ...form, contact_phone: v }),
                  "fleet-tnt-phone")}
          {field("Mensalidade R$", form.monthly_fee,
                  (v) => setForm({ ...form, monthly_fee: v }),
                  "fleet-tnt-fee", "number")}
        </div>
        {err && <div style={errBox}>{err}</div>}
        <button onClick={save} style={primaryBtn} data-testid="fleet-tnt-save">
          Adicionar cliente
        </button>
      </div>

      <div style={card}>
        <h3 style={{ margin: "0 0 12px" }}>Clientes ({tenants.length})</h3>
        {!tenants.length && <div style={empty}>Nenhum cliente ainda.</div>}
        {tenants.map((t) => (
          <div key={t.id} style={row}>
            <div style={{ flex: 1 }}>
              <b>{t.name}</b>
              <div style={{ fontSize: 11, color: "#64748b" }}>
                {t.contact_email || "—"} · {t.contact_phone || "—"}
              </div>
            </div>
            <span style={{ fontSize: 12, color: "#0f172a", fontWeight: 700 }}>
              R$ {(t.monthly_fee || 0).toFixed(2)}/mês
            </span>
            <span style={{ fontSize: 11, color: "#94a3b8", fontFamily: "monospace" }}>
              {t.id}
            </span>
            <button onClick={() => setPortalFor(t)}
                     data-testid={`fleet-tnt-portal-${t.id}`}
                     style={{ ...dangerBtn, background: "#7c3aed" }}>
              👤 Usuários do portal
            </button>
            <button onClick={() => remove(t.id)} style={dangerBtn}>
              Excluir
            </button>
          </div>
        ))}
      </div>

      {portalFor && (
        <FleetTenantPortalUsersModal tenant={portalFor}
                                       onClose={() => setPortalFor(null)} />
      )}
    </div>
  );
}

function field(label, value, onChange, testid, type = "text") {
  return (
    <label style={{ display: "block", fontSize: 11, color: "#475569" }}>
      {label}
      <input type={type} value={value}
              onChange={(e) => onChange(e.target.value)}
              data-testid={testid}
              style={inp} />
    </label>
  );
}

const card = { background: "white", border: "1px solid #e2e8f0",
                 borderRadius: 12, padding: 16 };
const row = { display: "flex", gap: 10, alignItems: "center",
               padding: "10px 12px", borderBottom: "1px solid #f1f5f9" };
const inp = { width: "100%", padding: "6px 10px", borderRadius: 6,
                border: "1px solid #cbd5e1", fontSize: 13, marginTop: 4,
                boxSizing: "border-box" };
const primaryBtn = {
  padding: "7px 16px", background: "#0f172a", color: "white",
  border: 0, borderRadius: 6, fontWeight: 700, fontSize: 13, cursor: "pointer",
  marginTop: 10,
};
const dangerBtn = {
  padding: "4px 12px", background: "#dc2626", color: "white",
  border: 0, borderRadius: 6, fontSize: 11, cursor: "pointer",
};
const empty = { padding: 16, textAlign: "center", color: "#94a3b8",
                 fontSize: 13 };
const errBox = { padding: 10, background: "#fee2e2", color: "#991b1b",
                  borderRadius: 6, fontSize: 12, marginTop: 8 };
