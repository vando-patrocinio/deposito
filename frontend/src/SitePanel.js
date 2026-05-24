import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { fmtAddress } from "@/utils/format";
import {
  Globe, Save, ExternalLink, RefreshCw, Phone, Mail,
  CheckCircle, MessageCircle, Trash2,
} from "lucide-react";

/* =============================================================
   SitePanel — Painel administrativo do site público do provedor.
   3 abas:
     1. Configurações — hero, contatos, redes, cores
     2. Combos / Apps  — SVAs exibidos no site (Disney+/HBO/etc)
     3. Leads          — formulários recebidos do site
   Preview: link pra /provedor abre em nova aba.
============================================================= */
export default function SitePanel() {
  const [tab, setTab] = useState("config");
  const publicUrl = `${window.location.origin}/provedor`;

  return (
    <div data-testid="site-panel" style={{ display: "grid", gap: 14 }}>
      <div className="surface" style={{
        padding: 18, borderRadius: 14,
        background: "linear-gradient(135deg, rgba(14,165,233,.12) 0%, var(--bg-surface) 60%)",
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: "linear-gradient(135deg, #0ea5e9, #f97316)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 14px rgba(14,165,233,.35)",
        }}>
          <Globe size={22} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800,
                          letterSpacing: "-0.02em" }}>
            Site do Provedor
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            Landing page pública para captura de novos assinantes.
          </div>
        </div>
        <a href={publicUrl} target="_blank" rel="noopener noreferrer"
            data-testid="site-preview-link"
            className="btn btn-primary btn-sm">
          <ExternalLink size={13} /> Ver site público
        </a>
      </div>

      <div className="surface" style={{
        padding: "4px", borderRadius: 10,
        display: "inline-flex", gap: 4,
      }}>
        {[
          { id: "config", label: "Configurações" },
          { id: "combos", label: "Combos / Apps" },
          { id: "leads", label: "Leads recebidos" },
        ].map((t) => (
          <button key={t.id}
                    onClick={() => setTab(t.id)}
                    data-testid={`site-tab-${t.id}`}
                    style={{
                      padding: "9px 18px", borderRadius: 7, border: 0,
                      background: tab === t.id ? "var(--accent)" : "transparent",
                      color: tab === t.id ? "#fff" : "var(--text-secondary)",
                      fontSize: 12, fontWeight: 700, cursor: "pointer",
                      transition: "all .15s",
                    }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "config" && <ConfigTab />}
      {tab === "combos" && <CombosTab />}
      {tab === "leads" && <LeadsTab />}
    </div>
  );
}

/* ============================================================
   ConfigTab — Edita hero, contatos, redes, cores
   ============================================================ */
function ConfigTab() {
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState(null);

  useEffect(() => {
    api.siteConfigGet().then(setCfg).catch((e) => console.error(e));
  }, []);

  if (!cfg) {
    return (
      <div className="surface" style={{ padding: 30, textAlign: "center",
                                          color: "var(--text-muted)" }}>
        Carregando...
      </div>
    );
  }

  const set = (k, v) => setCfg({ ...cfg, [k]: v });
  const save = async () => {
    setBusy(true);
    try {
      const r = await api.siteConfigUpdate(cfg);
      setCfg(r.config);
      setSavedAt(new Date());
    } catch (e) {
      await window.alert(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div className="surface" style={{ padding: 20, borderRadius: 12 }}>
      <Section title="🏢 Identidade do Provedor">
        <Grid cols={2}>
          <Field label="Nome do site / marca">
            <input className="input" value={cfg.site_name || ""}
                    onChange={(e) => set("site_name", e.target.value)}
                    data-testid="site-name" />
          </Field>
          <Field label="URL do logo (PNG)">
            <input className="input" value={cfg.logo_url || ""}
                    onChange={(e) => set("logo_url", e.target.value)}
                    placeholder="https://..." />
          </Field>
          <Field label="CNPJ">
            <input className="input" value={cfg.cnpj || ""}
                    onChange={(e) => set("cnpj", e.target.value)}
                    placeholder="00.000.000/0001-00" />
          </Field>
          <Field label="Nº Fistel / Outorga ANATEL">
            <input className="input" value={cfg.anatel || ""}
                    onChange={(e) => set("anatel", e.target.value)}
                    placeholder="Fistel: 00000000 / SEI: ..." />
          </Field>
        </Grid>
      </Section>

      <Section title="🎨 Cores (paleta primária)">
        <Grid cols={2}>
          <Field label="Cor primária (hex)">
            <input className="input" type="color"
                    value={cfg.primary_color || "#0ea5e9"}
                    onChange={(e) => set("primary_color", e.target.value)} />
          </Field>
          <Field label="Cor secundária (hex)">
            <input className="input" type="color"
                    value={cfg.secondary_color || "#f97316"}
                    onChange={(e) => set("secondary_color", e.target.value)} />
          </Field>
        </Grid>
      </Section>

      <Section title="🚀 Hero (banner principal)">
        <Field label="Kicker (texto pequeno acima do título)">
          <input className="input" value={cfg.hero_kicker || ""}
                  onChange={(e) => set("hero_kicker", e.target.value)} />
        </Field>
        <Field label="Título grande">
          <input className="input" value={cfg.hero_title || ""}
                  onChange={(e) => set("hero_title", e.target.value)} />
        </Field>
        <Field label="Subtítulo (descrição)">
          <input className="input" value={cfg.hero_subtitle || ""}
                  onChange={(e) => set("hero_subtitle", e.target.value)} />
        </Field>
        <Field label="Texto do botão (CTA)">
          <input className="input" value={cfg.hero_cta || ""}
                  onChange={(e) => set("hero_cta", e.target.value)} />
        </Field>
      </Section>

      <Section title="📞 Contato e Redes">
        <Grid cols={2}>
          <Field label="Telefone 0800 (exibido no header)">
            <input className="input" value={cfg.phone_0800 || ""}
                    onChange={(e) => set("phone_0800", e.target.value)}
                    placeholder="0800 000 0000" />
          </Field>
          <Field label="WhatsApp (E.164 sem +)">
            <input className="input" value={cfg.phone_whatsapp || ""}
                    onChange={(e) => set("phone_whatsapp", e.target.value)}
                    placeholder="5511999999999"
                    data-testid="site-whatsapp" />
          </Field>
          <Field label="E-mail de contato">
            <input className="input" value={cfg.email || ""}
                    onChange={(e) => set("email", e.target.value)} />
          </Field>
          <Field label="Instagram URL">
            <input className="input" value={cfg.instagram_url || ""}
                    onChange={(e) => set("instagram_url", e.target.value)} />
          </Field>
          <Field label="Facebook URL">
            <input className="input" value={cfg.facebook_url || ""}
                    onChange={(e) => set("facebook_url", e.target.value)} />
          </Field>
          <Field label="URL avaliações Google">
            <input className="input" value={cfg.google_reviews_url || ""}
                    onChange={(e) => set("google_reviews_url", e.target.value)} />
          </Field>
        </Grid>
      </Section>

      <Section title="🔗 Central do assinante / 2ª via">
        <Grid cols={2}>
          <Field label="URL Central do Assinante (Minha Conta)">
            <input className="input" value={cfg.central_url || ""}
                    onChange={(e) => set("central_url", e.target.value)}
                    placeholder="https://central.seuprovedor.com.br" />
          </Field>
          <Field label="URL Portal de Suporte">
            <input className="input" value={cfg.support_portal_url || ""}
                    onChange={(e) => set("support_portal_url", e.target.value)} />
          </Field>
          <Field label="App Android (Play Store)">
            <input className="input" value={cfg.app_android_url || ""}
                    onChange={(e) => set("app_android_url", e.target.value)} />
          </Field>
          <Field label="App iOS (App Store)">
            <input className="input" value={cfg.app_ios_url || ""}
                    onChange={(e) => set("app_ios_url", e.target.value)} />
          </Field>
        </Grid>
      </Section>

      <div style={{ position: "sticky", bottom: 0, padding: "12px 0",
                      background: "var(--bg-surface)", marginTop: 18,
                      borderTop: "1px solid var(--border-default)",
                      display: "flex", gap: 10, alignItems: "center" }}>
        {savedAt && (
          <span style={{ fontSize: 11, color: "#16a34a", fontWeight: 600 }}>
            ✓ Salvo {savedAt.toLocaleTimeString("pt-BR")}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <button onClick={save} disabled={busy}
                  data-testid="site-config-save"
                  className="btn btn-primary btn-sm">
          <Save size={13} />
          {busy ? "Salvando..." : "Salvar configurações"}
        </button>
      </div>
    </div>
  );
}

/* ============================================================
   CombosTab — gerencia lista de combos/apps exibidos no site
   ============================================================ */
function CombosTab() {
  const [combos, setCombos] = useState([]);
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState(null);

  useEffect(() => {
    api.siteConfigGet()
      .then((c) => setCombos(c.combos || []))
      .catch(() => {});
  }, []);

  const upd = (i, k, v) => {
    const arr = [...combos];
    arr[i] = { ...arr[i], [k]: v };
    setCombos(arr);
  };
  const rm = (i) => {
    if (!window.confirm("Remover esse combo?")) return;
    const arr = [...combos]; arr.splice(i, 1);
    setCombos(arr);
  };
  const add = () => setCombos([...combos, { name: "", description: "",
                                              icon_url: "" }]);
  const save = async () => {
    setBusy(true);
    try {
      await api.siteConfigUpdate({ combos });
      setSavedAt(new Date());
    } catch (e) {
      await window.alert(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div className="surface" style={{ padding: 20, borderRadius: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 14 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 800 }}>
            Combos / Apps exibidos no site
          </h3>
          <p style={{ fontSize: 11, color: "var(--text-muted)", margin: 0 }}>
            Streamings, telefonia, TV e outros SVAs que o cliente pode adicionar
            ao plano. Aparecem na seção "Adicione um aplicativo".
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={add}
                  data-testid="combo-add">
          + Adicionar combo
        </button>
      </div>

      {combos.length === 0 && (
        <div style={{ padding: 20, textAlign: "center", fontSize: 12,
                        color: "var(--text-muted)",
                        background: "var(--bg-surface-2)", borderRadius: 8 }}>
          Nenhum combo configurado.
        </div>
      )}

      <div style={{ display: "grid", gap: 10 }}>
        {combos.map((c, i) => (
          <div key={i} data-testid={`combo-edit-${i}`} style={{
            padding: 12, borderRadius: 10,
            border: "1px solid var(--border-default)",
            display: "grid", gridTemplateColumns: "2fr 3fr 3fr auto", gap: 8,
            alignItems: "center",
          }}>
            <input className="input" value={c.name || ""}
                    onChange={(e) => upd(i, "name", e.target.value)}
                    placeholder="Nome (Disney+, HBO Max...)" />
            <input className="input" value={c.description || ""}
                    onChange={(e) => upd(i, "description", e.target.value)}
                    placeholder="Descrição curta" />
            <input className="input" value={c.icon_url || ""}
                    onChange={(e) => upd(i, "icon_url", e.target.value)}
                    placeholder="URL do ícone (opcional)" />
            <button onClick={() => rm(i)}
                      className="btn btn-ghost btn-sm"
                      style={{ color: "var(--danger)" }}
                      title="Remover">
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 16,
                      alignItems: "center" }}>
        {savedAt && (
          <span style={{ fontSize: 11, color: "#16a34a", fontWeight: 600 }}>
            ✓ Salvo {savedAt.toLocaleTimeString("pt-BR")}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <button onClick={save} disabled={busy}
                  data-testid="combos-save"
                  className="btn btn-primary btn-sm">
          <Save size={13} /> {busy ? "Salvando..." : "Salvar combos"}
        </button>
      </div>
    </div>
  );
}

/* ============================================================
   LeadsTab — leads recebidos pelo form do site
   ============================================================ */
function LeadsTab() {
  const [leads, setLeads] = useState([]);
  const [counts, setCounts] = useState({});
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.siteLeadsList({
        status: statusFilter || undefined });
      setLeads(r.items || []);
      setCounts(r.counts || {});
    } finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  const updateStatus = async (id, status) => {
    try {
      await api.siteLeadUpdate(id, { status });
      load();
    } catch (e) {
      await window.alert(e?.response?.data?.detail || e.message);
    }
  };

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))",
                      gap: 8 }}>
        <CountCard label="Novos" value={counts.new || 0}
                    color="#0ea5e9"
                    active={statusFilter === "new"}
                    onClick={() => setStatusFilter(
                      statusFilter === "new" ? "" : "new")} />
        <CountCard label="Contatados" value={counts.contacted || 0}
                    color="#f59e0b"
                    active={statusFilter === "contacted"}
                    onClick={() => setStatusFilter(
                      statusFilter === "contacted" ? "" : "contacted")} />
        <CountCard label="Convertidos" value={counts.converted || 0}
                    color="#16a34a"
                    active={statusFilter === "converted"}
                    onClick={() => setStatusFilter(
                      statusFilter === "converted" ? "" : "converted")} />
        <CountCard label="Descartados" value={counts.discarded || 0}
                    color="#94a3b8"
                    active={statusFilter === "discarded"}
                    onClick={() => setStatusFilter(
                      statusFilter === "discarded" ? "" : "discarded")} />
      </div>

      <div className="surface" style={{ padding: 12, borderRadius: 10,
                                          display: "flex", gap: 10,
                                          alignItems: "center" }}>
        <select className="input" value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  style={{ minWidth: 200 }}>
          <option value="">Todos os leads</option>
          <option value="new">Novos</option>
          <option value="contacted">Contatados</option>
          <option value="converted">Convertidos</option>
          <option value="discarded">Descartados</option>
        </select>
        <div style={{ flex: 1 }} />
        <button className="btn btn-ghost btn-sm" onClick={load}>
          <RefreshCw size={13} /> Atualizar
        </button>
      </div>

      {loading ? (
        <div className="surface" style={{ padding: 30, textAlign: "center",
                                            color: "var(--text-muted)" }}>
          Carregando...
        </div>
      ) : leads.length === 0 ? (
        <div className="surface" style={{ padding: 30, textAlign: "center",
                                            color: "var(--text-muted)" }}>
          Nenhum lead recebido ainda. Compartilhe o link
          <code style={{ background: "var(--bg-surface-2)", padding: "2px 6px",
                            borderRadius: 4, marginLeft: 4 }}>
            /provedor
          </code>
          {" "}pra começar a captar.
        </div>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {leads.map((l) => (
            <LeadRow key={l.id} lead={l} onStatus={updateStatus} />
          ))}
        </div>
      )}
    </div>
  );
}

function LeadRow({ lead, onStatus }) {
  const statusColor = {
    new: "#0ea5e9", contacted: "#f59e0b",
    converted: "#16a34a", discarded: "#94a3b8",
  }[lead.status] || "#94a3b8";
  const phoneDigits = (lead.phone_digits || lead.phone || "").replace(/\D/g, "");
  const whatsLink = `https://wa.me/${phoneDigits}` +
        `?text=${encodeURIComponent(
          `Olá ${lead.name}! Recebemos seu pedido pelo site, ` +
          `confirma o plano ${lead.plan_interest || ""}?`)}`;
  return (
    <div className="surface" data-testid={`lead-${lead.id}`}
          style={{
            padding: 14, borderRadius: 10,
            display: "grid", gridTemplateColumns: "1fr auto", gap: 12,
            alignItems: "center",
            borderLeft: `3px solid ${statusColor}`,
          }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8,
                       marginBottom: 4 }}>
          <strong style={{ fontSize: 14, color: "var(--text-primary)" }}>
            {lead.name}
          </strong>
          <span style={{
            padding: "2px 8px", borderRadius: 999,
            background: `${statusColor}22`, color: statusColor,
            fontSize: 9, fontWeight: 800, letterSpacing: 0.5,
            textTransform: "uppercase",
          }}>{lead.status}</span>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {new Date(lead.created_at).toLocaleString("pt-BR")}
          </span>
        </div>
        <div style={{ fontSize: 12, color: "var(--text-secondary)",
                        display: "flex", gap: 12, flexWrap: "wrap" }}>
          <span><Phone size={11} style={{ display: "inline" }} /> {lead.phone}</span>
          {lead.email && <span><Mail size={11} style={{ display: "inline" }} /> {lead.email}</span>}
          {lead.plan_interest && (
            <span>📋 <strong>{lead.plan_interest}</strong></span>
          )}
        </div>
        {lead.address && (
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
            📍 {fmtAddress(lead.address)}
          </div>
        )}
        {lead.message && (
          <div style={{ fontSize: 12, color: "var(--text-secondary)",
                          marginTop: 4, fontStyle: "italic" }}>
            "{lead.message}"
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <a href={whatsLink} target="_blank" rel="noopener noreferrer"
            className="btn btn-primary btn-sm"
            data-testid={`lead-whats-${lead.id}`}>
          <MessageCircle size={12} /> WhatsApp
        </a>
        {lead.status === "new" && (
          <button onClick={() => onStatus(lead.id, "contacted")}
                    className="btn btn-ghost btn-sm">
            Marcar contatado
          </button>
        )}
        {lead.status !== "converted" && (
          <button onClick={() => onStatus(lead.id, "converted")}
                    className="btn btn-ghost btn-sm"
                    style={{ color: "#16a34a" }}>
            <CheckCircle size={12} /> Converter
          </button>
        )}
      </div>
    </div>
  );
}

function CountCard({ label, value, color, active, onClick }) {
  return (
    <button onClick={onClick} className="surface"
            style={{
              padding: 14, borderRadius: 10, cursor: "pointer",
              border: active
                ? `2px solid ${color}`
                : "1px solid var(--border-default)",
              background: active ? `${color}11` : "var(--bg-surface)",
              textAlign: "left",
            }}>
      <div style={{ fontSize: 10, fontWeight: 800, color,
                       textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, marginTop: 2,
                       color: "var(--text-primary)" }}>
        {value}
      </div>
    </button>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 22 }}>
      <h3 style={{ margin: "0 0 10px", fontSize: 13, fontWeight: 800,
                     color: "var(--text-primary)",
                     borderBottom: "1px solid var(--border-default)",
                     paddingBottom: 5 }}>{title}</h3>
      {children}
    </div>
  );
}
function Grid({ cols = 2, children }) {
  return (
    <div style={{
      display: "grid", gap: 10,
      gridTemplateColumns: `repeat(${cols}, 1fr)`,
    }}>{children}</div>
  );
}
function Field({ label, children }) {
  return (
    <label style={{ display: "block", marginBottom: 10 }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.4,
                       marginBottom: 4 }}>
        {label}
      </div>
      {children}
    </label>
  );
}
