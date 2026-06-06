/* ParceriaAdminPage.js — Gestão de parcerias (admin SmartProv).
   Tabs: Parceiros, Promoções, Redenções (com botão "Marcar pago"). */
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";

const T = {
  primary: "#dc2626", soft: "#f1f5f9", border: "#e2e8f0",
};

export default function ParceriaAdminPage() {
  const [tab, setTab] = useState("partners");
  const [partners, setPartners] = useState([]);
  const [promos, setPromos] = useState([]);
  const [reds, setReds] = useState([]);
  const [showPartnerForm, setShowPartnerForm] = useState(null);
  const [showPromoForm, setShowPromoForm] = useState(null);
  const [showUsersFor, setShowUsersFor] = useState(null);

  const refresh = async () => {
    try {
      const [pa, pr, rd] = await Promise.all([
        api._client.get("/parcerias/partners").then((r) => r.data),
        api._client.get("/parcerias/promotions").then((r) => r.data),
        api._client.get("/parcerias/redemptions?limit=300")
          .then((r) => r.data),
      ]);
      setPartners(pa); setPromos(pr); setReds(rd);
    } catch { /* */ }
  };
  useEffect(() => { refresh(); }, []);

  const kpis = useMemo(() => {
    const pending = reds.filter((r) => !r.paid);
    const due = pending.reduce((a, r) =>
      a + (r.reimbursement_value || 0), 0);
    return {
      partners: partners.length,
      promos: promos.filter((p) => p.active).length,
      redemptions: reds.length,
      due,
    };
  }, [partners, promos, reds]);

  const markPaid = async (rid) => {
    if (!window.confirm("Marcar redenção como paga?")) return;
    await api._client.post(`/parcerias/redemptions/${rid}/mark-paid`);
    refresh();
  };

  const delPartner = async (pid, name) => {
    if (!window.confirm(`Remover parceiro "${name}"?`)) return;
    await api._client.delete(`/parcerias/partners/${pid}`);
    refresh();
  };

  const copyMagicLink = async (p) => {
    // iter230 — agora aponta pro PWA do parceiro em /parceiro/{token}
    const link = `${window.location.origin}/parceiro/${p.magic_token}`;
    const msg = `Olá ${p.name}! \n\n` +
      `Você é parceiro Ligo Vantagens. Use este link único pra ` +
      `gerenciar suas promoções no celular (não precisa de senha):\n\n` +
      `${link}\n\n` +
      `Pelo link você consegue cadastrar fotos, % desconto, e ler ` +
      `o QR code dos clientes Ligo no caixa.`;
    try {
      await navigator.clipboard.writeText(msg);
      alert("✓ Link mágico copiado!\n\nCole no WhatsApp e envie pro " +
        "parceiro.");
    } catch {
      window.prompt("Copie e envie:", msg);
    }
  };

  const rotateMagic = async (pid) => {
    if (!window.confirm(
      "Gerar um novo link e invalidar o atual?")) return;
    await api._client.post(`/parcerias/partners/${pid}/rotate-magic-link`);
    refresh();
    alert("✓ Novo link gerado!");
  };

  return (
    <div data-testid="parceria-admin-page" style={{ display: "grid", gap: 14 }}>
      <header style={{ display: "flex", justifyContent: "space-between",
                         alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, margin: 0 }}>
            Parcerias Comerciais
          </h1>
          <p style={{ fontSize: 12, color: "#64748b",
                        margin: "2px 0 0" }}>
            Faça parcerias com comércios locais, gere QR para clientes
            e gerencie reembolsos.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <a href="/?showcase=parcerias" target="_blank" rel="noreferrer"
              data-testid="pa-admin-link-vitrine"
              style={ghostBtn}>
            Ver vitrine pública
          </a>
          <a href="/seja-parceiro" target="_blank" rel="noreferrer"
              data-testid="pa-admin-link-landing"
              style={ghostBtn}>
            Landing “Seja parceiro”
          </a>
          <a href="/?portal=parceiro" target="_blank" rel="noreferrer"
              data-testid="pa-admin-link-partner-login"
              style={ghostBtn}>
            Portal do parceiro (login)
          </a>
          <a href="/cliente" target="_blank" rel="noreferrer"
              data-testid="pa-admin-link-cliente"
              style={ghostBtn}>
            App do cliente Ligo
          </a>
        </div>
      </header>

      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(4,1fr)", gap: 8 }}>
        <Kpi label="Parceiros" value={kpis.partners} color="#3b82f6" />
        <Kpi label="Promoções ativas" value={kpis.promos} color="#10b981" />
        <Kpi label="Redenções" value={kpis.redemptions} color="#f59e0b" />
        <Kpi label="A pagar parceiros"
              value={`R$ ${kpis.due.toFixed(2)}`}
              color="#dc2626" />
      </div>

      <div style={tabBar}>
        {[
          ["partners", "Parceiros"],
          ["promotions", "Promoções"],
          ["redemptions", `Redenções${
            reds.filter((r) => !r.paid).length
              ? ` (${reds.filter((r) => !r.paid).length})` : ""}`],
        ].map(([k, v]) => (
          <button key={k} onClick={() => setTab(k)}
                   style={tab === k ? tabActive : tabIdle}
                   data-testid={`pa-tab-${k}`}>{v}</button>
        ))}
      </div>

      {tab === "partners" && (
        <div style={card}>
          <div style={{ display: "flex", justifyContent: "flex-end",
                          marginBottom: 10 }}>
            <button style={primaryBtn} onClick={() => setShowPartnerForm({})}
                     data-testid="pa-add-partner">+ Novo parceiro</button>
          </div>
          {!partners.length ? (
            <Empty>Nenhum parceiro cadastrado.</Empty>
          ) : (
            <table style={tbl}>
              <thead>
                <tr><th style={th}>Parceiro</th><th style={th}>Categoria</th>
                  <th style={th}>Cidade</th>
                  <th style={th}>A pagar</th><th style={th}>Ações</th></tr>
              </thead>
              <tbody>
                {partners.map((p) => {
                  const due = reds.filter((r) => r.partner_id === p.id
                    && !r.paid).reduce((a, r) =>
                    a + (r.reimbursement_value || 0), 0);
                  return (
                    <tr key={p.id} data-testid={`pa-partner-${p.id}`}>
                      <td style={td}>
                        <div style={{ display: "flex", alignItems: "center",
                                        gap: 8 }}>
                          {p.logo_url
                            ? <img src={p.logo_url} alt=""
                                    style={{ width: 32, height: 32,
                                               borderRadius: 6,
                                               objectFit: "cover" }} />
                            : <div style={{ width: 32, height: 32,
                                              background: p.color || "#dc2626",
                                              borderRadius: 6 }} />}
                          <div>
                            <b>{p.name}</b>
                            <div style={{ fontSize: 11, color: "#64748b" }}>
                              {p.neighborhood} · {p.phone}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td style={td}>{p.category}</td>
                      <td style={td}>{p.city || "—"}</td>
                      <td style={td}>
                        <span style={{
                          color: due > 0 ? "#dc2626" : "#94a3b8",
                          fontWeight: 700,
                        }}>R$ {due.toFixed(2)}</span>
                      </td>
                      <td style={td}>
                        {p.slug && (
                          <a href={`/?parceiro=${p.slug}`}
                              target="_blank" rel="noreferrer"
                              style={{ ...miniBtn("#10b981"),
                                         textDecoration: "none",
                                         display: "inline-block" }}
                              data-testid={`pa-link-${p.id}`}>
                            Site
                          </a>
                        )}
                        {p.magic_token && (
                          <button style={miniBtn("#f59e0b")}
                                   onClick={() => copyMagicLink(p)}
                                   data-testid={`pa-magic-${p.id}`}>
                            Link mágico
                          </button>
                        )}
                        <button style={miniBtn("#3b82f6")}
                                 onClick={() => setShowUsersFor(p)}
                                 data-testid={`pa-users-${p.id}`}>
                          Acesso
                        </button>
                        <button style={miniBtn("#64748b")}
                                 onClick={() => setShowPartnerForm(p)}>
                          ✏️
                        </button>
                        <button style={miniBtn("#dc2626")}
                                 onClick={() => delPartner(p.id, p.name)}>
                          
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "promotions" && (
        <div style={card}>
          <div style={{ display: "flex", justifyContent: "flex-end",
                          marginBottom: 10 }}>
            <button style={primaryBtn}
                     onClick={() => setShowPromoForm({})}
                     disabled={!partners.length}
                     data-testid="pa-add-promo">+ Nova promoção</button>
          </div>
          {!promos.length ? (
            <Empty>Nenhuma promoção criada.</Empty>
          ) : (
            <table style={tbl}>
              <thead>
                <tr><th style={th}>Título</th><th style={th}>Parceiro</th>
                  <th style={th}>Reembolso</th>
                  <th style={th}>Limite/cliente</th>
                  <th style={th}>Redenções</th>
                  <th style={th}>Status</th><th style={th}></th></tr>
              </thead>
              <tbody>
                {promos.map((p) => (
                  <tr key={p.id} data-testid={`pa-promo-${p.id}`}>
                    <td style={td}>
                      <b>{p.title}</b>
                      <div style={{ fontSize: 11, color: "#64748b" }}>
                        {p.offer_summary}
                      </div>
                    </td>
                    <td style={td}>{p.partner_name}</td>
                    <td style={td}>R$ {p.reimbursement_value?.toFixed(2)}</td>
                    <td style={td}>{p.max_uses_per_client}× / {p.period}</td>
                    <td style={td}>{p.total_redemptions || 0}</td>
                    <td style={td}>
                      <span style={{
                        padding: "2px 8px",
                        background: p.active ? "#dcfce7" : "#fee2e2",
                        color: p.active ? "#166534" : "#991b1b",
                        borderRadius: 4, fontSize: 11, fontWeight: 700,
                      }}>{p.active ? "Ativa" : "Inativa"}</span>
                    </td>
                    <td style={td}>
                      <button style={miniBtn("#64748b")}
                               onClick={() => setShowPromoForm(p)}>✏️</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "redemptions" && (
        <div style={card}>
          {!reds.length ? (
            <Empty>Nenhuma redenção registrada.</Empty>
          ) : (
            <table style={tbl}>
              <thead>
                <tr><th style={th}>Cliente</th><th style={th}>Parceiro</th>
                  <th style={th}>Promoção</th><th style={th}>Valor</th>
                  <th style={th}>Cupom</th>
                  <th style={th}>Data</th><th style={th}>Status</th></tr>
              </thead>
              <tbody>
                {reds.map((r) => (
                  <tr key={r.id} data-testid={`pa-red-${r.id}`}>
                    <td style={td}>
                      <b>{r.client_name}</b>
                      <div style={{ fontSize: 11, color: "#64748b" }}>
                        {r.client_pppoe}
                      </div>
                    </td>
                    <td style={td}>{r.partner_name}</td>
                    <td style={td}>{r.promotion_title}</td>
                    <td style={td}>
                      <b style={{ color: "#dc2626" }}>
                        R$ {r.reimbursement_value?.toFixed(2)}
                      </b>
                    </td>
                    <td style={td}>
                      <code style={{ fontSize: 11 }}>{r.voucher_code}</code>
                    </td>
                    <td style={td}>
                      {new Date(r.redeemed_at).toLocaleString("pt-BR")}
                    </td>
                    <td style={td}>
                      {r.paid ? (
                        <span style={{ color: "#16a34a", fontWeight: 700,
                                         fontSize: 12 }}>✓ Paga</span>
                      ) : (
                        <button style={miniBtn("#10b981")}
                                 onClick={() => markPaid(r.id)}
                                 data-testid={`pa-mark-paid-${r.id}`}>
                          Marcar pago
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {showPartnerForm && (
        <PartnerForm initial={showPartnerForm.id ? showPartnerForm : null}
                      onClose={() => setShowPartnerForm(null)}
                      onSaved={() => { setShowPartnerForm(null); refresh(); }} />
      )}
      {showPromoForm && (
        <PromoForm initial={showPromoForm.id ? showPromoForm : null}
                    partners={partners}
                    onClose={() => setShowPromoForm(null)}
                    onSaved={() => { setShowPromoForm(null); refresh(); }} />
      )}
      {showUsersFor && (
        <PartnerUsersModal partner={showUsersFor}
                            onClose={() => setShowUsersFor(null)} />
      )}
    </div>
  );
}

// ─── Subcomponents ───
function Kpi({ label, value, color }) {
  return (
    <div style={{ background: "white", border: `1px solid ${T.border}`,
                    borderTop: `3px solid ${color}`,
                    borderRadius: 10, padding: 12 }}>
      <div style={{ fontSize: 22, fontWeight: 800, color }}>{value}</div>
      <div style={{ fontSize: 10, color: "#64748b",
                      textTransform: "uppercase", letterSpacing: .5,
                      fontWeight: 700, marginTop: 2 }}>{label}</div>
    </div>
  );
}

function Empty({ children }) {
  return <div style={{ padding: 36, textAlign: "center", color: "#94a3b8",
                          fontSize: 13 }}>{children}</div>;
}

function PartnerForm({ initial, onClose, onSaved }) {
  const [f, setF] = useState({
    name: initial?.name || "", category: initial?.category || "Pizzaria",
    logo_url: initial?.logo_url || "",
    cover_url: initial?.cover_url || "",
    address: initial?.address || "", city: initial?.city || "",
    neighborhood: initial?.neighborhood || "",
    phone: initial?.phone || "", website: initial?.website || "",
    description: initial?.description || "",
    color: initial?.color || "#dc2626",
    reimbursement_rate_default: initial?.reimbursement_rate_default || 0,
    active: initial?.active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true); setErr("");
    try {
      if (initial?.id) {
        await api._client.put(`/parcerias/partners/${initial.id}`, f);
      } else {
        await api._client.post(`/parcerias/partners`, f);
      }
      onSaved?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };
  return (
    <Overlay onClose={onClose} testid="pa-partner-form">
      <h3 style={{ margin: "0 0 14px" }}>
        {initial?.id ? `Editar ${initial.name}` : "Novo parceiro"}
      </h3>
      <Grid>
        <Field lbl="Nome *" value={f.name}
                onChange={(v) => setF({ ...f, name: v })}
                testid="pa-pform-name" />
        <Field lbl="Categoria" value={f.category}
                onChange={(v) => setF({ ...f, category: v })} />
        <Field lbl="Cidade" value={f.city}
                onChange={(v) => setF({ ...f, city: v })} />
        <Field lbl="Bairro" value={f.neighborhood}
                onChange={(v) => setF({ ...f, neighborhood: v })} />
        <Field lbl="Telefone" value={f.phone}
                onChange={(v) => setF({ ...f, phone: v })} />
        <Field lbl="Website" value={f.website}
                onChange={(v) => setF({ ...f, website: v })} />
        <Field lbl="Logo URL" value={f.logo_url} colSpan={2}
                onChange={(v) => setF({ ...f, logo_url: v })} />
        <Field lbl="Cor (#hex)" value={f.color}
                onChange={(v) => setF({ ...f, color: v })} />
      </Grid>
      <label style={{ fontSize: 11, color: "#475569", display: "block",
                       marginTop: 10 }}>
        Descrição (vitrine)
        <textarea value={f.description}
                    onChange={(e) =>
                      setF({ ...f, description: e.target.value })}
                    style={{ ...inp, minHeight: 70 }} />
      </label>
      {err && <ErrBox>{err}</ErrBox>}
      <Footer>
        <button onClick={onClose} style={secBtn}>Cancelar</button>
        <button onClick={save} disabled={busy} style={primaryBtn}
                 data-testid="pa-pform-save">
          {busy ? "Salvando…" : "Salvar"}
        </button>
      </Footer>
    </Overlay>
  );
}

function PromoForm({ initial, partners, onClose, onSaved }) {
  const [f, setF] = useState({
    partner_id: initial?.partner_id || partners[0]?.id || "",
    title: initial?.title || "",
    offer_summary: initial?.offer_summary || "",
    description: initial?.description || "",
    image_url: initial?.image_url || "",
    reimbursement_value: initial?.reimbursement_value || 0,
    max_uses_per_client: initial?.max_uses_per_client || 1,
    period: initial?.period || "month",
    terms: initial?.terms || "",
    starts_at: initial?.starts_at || "",
    ends_at: initial?.ends_at || "",
    active: initial?.active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true); setErr("");
    try {
      const body = { ...f,
        reimbursement_value: Number(f.reimbursement_value) || 0,
        max_uses_per_client: Number(f.max_uses_per_client) || 1,
      };
      if (initial?.id) {
        await api._client.put(`/parcerias/promotions/${initial.id}`, body);
      } else {
        await api._client.post(`/parcerias/promotions`, body);
      }
      onSaved?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };
  return (
    <Overlay onClose={onClose} testid="pa-promo-form">
      <h3 style={{ margin: "0 0 14px" }}>
        {initial?.id ? `Editar ${initial.title}` : "Nova promoção"}
      </h3>
      <label style={{ fontSize: 11, color: "#475569",
                       display: "block", marginBottom: 8 }}>
        Parceiro *
        <select value={f.partner_id}
                 onChange={(e) =>
                   setF({ ...f, partner_id: e.target.value })}
                 style={inp}>
          {partners.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </label>
      <Grid>
        <Field lbl="Título *" value={f.title} colSpan={2}
                onChange={(v) => setF({ ...f, title: v })}
                testid="pa-promof-title" />
        <Field lbl="Resumo da oferta *" value={f.offer_summary} colSpan={2}
                onChange={(v) => setF({ ...f, offer_summary: v })} />
        <Field lbl="Reembolso (R$ por uso)" value={f.reimbursement_value}
                type="number" step="0.01"
                onChange={(v) =>
                  setF({ ...f, reimbursement_value: v })} />
        <Field lbl="Limite por cliente" value={f.max_uses_per_client}
                type="number"
                onChange={(v) =>
                  setF({ ...f, max_uses_per_client: v })} />
        <label style={{ fontSize: 11, color: "#475569",
                          display: "block" }}>
          Período
          <select value={f.period}
                   onChange={(e) =>
                     setF({ ...f, period: e.target.value })}
                   style={inp}>
            <option value="day">Por dia</option>
            <option value="week">Por semana</option>
            <option value="month">Por mês</option>
            <option value="year">Por ano</option>
            <option value="campaign">Total na campanha</option>
            <option value="none">Sem limite (anula limite/cliente)</option>
          </select>
        </label>
        <Field lbl="Imagem URL" value={f.image_url}
                onChange={(v) => setF({ ...f, image_url: v })} />
      </Grid>
      <label style={{ fontSize: 11, color: "#475569",
                       display: "block", marginTop: 8 }}>
        Termos
        <textarea value={f.terms}
                    onChange={(e) => setF({ ...f, terms: e.target.value })}
                    style={{ ...inp, minHeight: 60 }} />
      </label>
      <label style={{ display: "flex", alignItems: "center", gap: 6,
                       marginTop: 8, fontSize: 12 }}>
        <input type="checkbox" checked={f.active}
                onChange={(e) =>
                  setF({ ...f, active: e.target.checked })} />
        Ativa (visível no app e no parceiro)
      </label>
      {err && <ErrBox>{err}</ErrBox>}
      <Footer>
        <button onClick={onClose} style={secBtn}>Cancelar</button>
        <button onClick={save} disabled={busy} style={primaryBtn}
                 data-testid="pa-promof-save">
          {busy ? "Salvando…" : "Salvar"}
        </button>
      </Footer>
    </Overlay>
  );
}

function PartnerUsersModal({ partner, onClose }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ email: "", password: "",
                                       name: "", role: "owner" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [created, setCreated] = useState(null);
  const reload = () =>
    api._client.get(`/parcerias/partners/${partner.id}/users`)
      .then((r) => setUsers(r.data));
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, []);
  const create = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api._client.post(
        `/parcerias/partners/${partner.id}/users`, form);
      setCreated({ ...r.data,
        login_url: `${window.location.origin}/?portal=parceiro`,
        partner_url: partner.slug
          ? `${window.location.origin}/?parceiro=${partner.slug}`
          : null });
      setForm({ email: "", password: "", name: "", role: "owner" });
      reload();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };
  return (
    <Overlay onClose={onClose} testid="pa-users-modal">
      <h3 style={{ margin: "0 0 12px" }}>Acesso · {partner.name}</h3>
      <p style={{ fontSize: 12, color: "#64748b", marginTop: -8 }}>
        Crie um login para o parceiro acessar o app de leitura de QR.
      </p>
      {created ? (
        <div style={{ background: "#dcfce7", border: "1px solid #86efac",
                        padding: 12, borderRadius: 8, marginBottom: 12,
                        fontSize: 13 }}>
          <div style={{ fontWeight: 800, marginBottom: 6 }}>
            ✓ Acesso criado!
          </div>
          <div><code>{created.email}</code></div>
          <div>Login: <code>{created.login_url}</code></div>
          {created.partner_url && (
            <div>Página: <code>{created.partner_url}</code></div>
          )}
          <button onClick={() => navigator.clipboard.writeText(
            `Página do parceiro: ${created.partner_url || created.login_url}\n` +
            `Login: ${created.login_url}\nE-mail: ${created.email}`)}
                   style={{ ...secBtn, marginTop: 8 }}>
            Copiar credenciais
          </button>
        </div>
      ) : null}
      <Grid>
        <Field lbl="Nome" value={form.name}
                onChange={(v) => setForm({ ...form, name: v })} />
        <Field lbl="E-mail *" value={form.email}
                onChange={(v) => setForm({ ...form, email: v })} />
        <Field lbl="Senha *" value={form.password} type="password"
                onChange={(v) => setForm({ ...form, password: v })} />
        <label style={{ fontSize: 11, color: "#475569" }}>
          Papel
          <select value={form.role}
                   onChange={(e) =>
                     setForm({ ...form, role: e.target.value })}
                   style={inp}>
            <option value="owner">Proprietário</option>
            <option value="staff">Operador</option>
          </select>
        </label>
      </Grid>
      {err && <ErrBox>{err}</ErrBox>}
      <Footer>
        <button onClick={onClose} style={secBtn}>Fechar</button>
        <button onClick={create} disabled={busy} style={primaryBtn}>
          {busy ? "Criando…" : "+ Criar acesso"}
        </button>
      </Footer>
      <hr style={{ margin: "16px 0", border: 0,
                    borderTop: "1px solid #e2e8f0" }} />
      <h4 style={{ fontSize: 12, color: "#64748b",
                     textTransform: "uppercase",
                     letterSpacing: 1, margin: "0 0 8px" }}>
        Usuários atuais
      </h4>
      {users.length === 0 ? (
        <Empty>Sem acessos criados.</Empty>
      ) : users.map((u) => (
        <div key={u.id} style={{ display: "flex",
                                      justifyContent: "space-between",
                                      padding: "6px 0",
                                      borderBottom: "1px solid #f1f5f9",
                                      fontSize: 13 }}>
          <span><b>{u.email}</b> · {u.role}</span>
          <span style={{ fontSize: 11, color: "#94a3b8" }}>
            {new Date(u.created_at).toLocaleDateString("pt-BR")}
          </span>
        </div>
      ))}
    </Overlay>
  );
}

// ─── Tiny UI primitives ───
function Overlay({ children, onClose, testid }) {
  return (
    <div data-testid={testid} onClick={onClose}
          style={{ position: "fixed", inset: 0,
                     background: "rgba(0,0,0,.5)",
                     display: "flex", alignItems: "center",
                     justifyContent: "center",
                     zIndex: 1000, padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ background: "white", borderRadius: 12, padding: 20,
                      maxWidth: 620, width: "100%", maxHeight: "90vh",
                      overflow: "auto" }}>
        {children}
      </div>
    </div>
  );
}
function Grid({ children }) {
  return <div style={{ display: "grid",
                         gridTemplateColumns: "1fr 1fr", gap: 10 }}>
    {children}</div>;
}
function Field({ lbl, value, onChange, type = "text", step,
                   colSpan = 1, testid }) {
  return (
    <label style={{ fontSize: 11, color: "#475569",
                     gridColumn: colSpan === 2 ? "1/-1" : "auto" }}>
      {lbl}
      <input type={type} step={step} value={value || ""}
              onChange={(e) => onChange(e.target.value)}
              style={inp} data-testid={testid} />
    </label>
  );
}
function ErrBox({ children }) {
  return <div style={{ padding: 10, background: "#fee2e2",
                         color: "#991b1b", borderRadius: 6,
                         fontSize: 12, marginTop: 10 }}>{children}</div>;
}
function Footer({ children }) {
  return <div style={{ display: "flex", gap: 8,
                         justifyContent: "flex-end",
                         marginTop: 12 }}>{children}</div>;
}

const card = { background: "white", border: `1px solid ${T.border}`,
                 borderRadius: 12, padding: 12 };
const tabBar = { display: "flex", gap: 2, borderBottom: `1px solid ${T.border}` };
const tabIdle = { padding: "9px 14px", background: "transparent",
                    border: 0, fontSize: 13, fontWeight: 700,
                    color: "#64748b", cursor: "pointer",
                    borderBottom: "2px solid transparent" };
const tabActive = { ...tabIdle, color: T.primary,
                     borderBottom: `2px solid ${T.primary}` };
const tbl = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const th = { textAlign: "left", padding: "8px 10px",
              borderBottom: `1px solid ${T.border}`, fontSize: 11,
              color: "#475569", textTransform: "uppercase" };
const td = { padding: "10px 10px",
              borderBottom: "1px solid #f1f5f9", verticalAlign: "top" };
const primaryBtn = { padding: "7px 14px", background: T.primary,
                      color: "white", border: 0, borderRadius: 6,
                      fontWeight: 700, fontSize: 12, cursor: "pointer" };
const ghostBtn = { padding: "7px 14px", color: T.primary,
                    border: `1px solid ${T.primary}`, borderRadius: 6,
                    fontWeight: 700, fontSize: 12, cursor: "pointer",
                    background: "white", textDecoration: "none" };
const secBtn = { ...primaryBtn, background: "white",
                  color: "#475569",
                  border: `1px solid #cbd5e1`, fontWeight: 600 };
const miniBtn = (bg) => ({ padding: "4px 8px", background: bg,
                            color: "white", border: 0, borderRadius: 4,
                            fontSize: 11, cursor: "pointer",
                            marginRight: 4 });
const inp = { width: "100%", padding: "7px 10px", borderRadius: 6,
                border: `1px solid #cbd5e1`, fontSize: 13,
                boxSizing: "border-box", marginTop: 4 };
