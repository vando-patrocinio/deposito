/* WifiHotspotPanel.js — Painel admin do Hotspot Wi-Fi multi-tenant.
 *
 * Reconstruído após rollback. Endpoints em /api/wifi-hotspot.
 *
 * Abas:
 *   - Visão geral (KPIs)
 *   - Espaços (CRUD venues + link público + router secret)
 *   - Visitantes (leads capturados via captive)
 *   - Sessões (ativas e histórico)
 *   - Campanhas (banners CRUD)
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import {
  Wifi, MapPin, Users, Activity, Megaphone, Plus, Pencil,
  Trash2, Copy, ExternalLink, KeyRound, X,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/wifi-hotspot`;
const PURPLE = "#6B2BFB";
const ORANGE = "#FF6A1A";

const http = () => {
  const tk = localStorage.getItem("token");
  return axios.create({
    baseURL: API,
    headers: tk ? { Authorization: `Bearer ${tk}` } : {},
  });
};

const TABS = [
  { id: "overview", label: "Visão geral", icon: Activity },
  { id: "venues", label: "Espaços", icon: MapPin },
  { id: "visitors", label: "Visitantes", icon: Users },
  { id: "sessions", label: "Sessões", icon: Wifi },
  { id: "campaigns", label: "Campanhas", icon: Megaphone },
];

export default function WifiHotspotPanel() {
  const [tab, setTab] = useState("overview");
  return (
    <div data-testid="wifi-hotspot-panel" style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <Header />
      <Tabs tab={tab} onChange={setTab} />
      <div style={{ marginTop: 22 }}>
        {tab === "overview" && <OverviewTab />}
        {tab === "venues" && <VenuesTab />}
        {tab === "visitors" && <VisitorsTab />}
        {tab === "sessions" && <SessionsTab />}
        {tab === "campaigns" && <CampaignsTab />}
      </div>
    </div>
  );
}

/* ─────────────────── Header / Tabs ─────────────────── */
function Header() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14,
      flexWrap: "wrap" }}>
      <div style={{
        width: 52, height: 52, borderRadius: 14,
        background: `linear-gradient(135deg, ${PURPLE}, ${ORANGE})`,
        display: "grid", placeItems: "center",
        boxShadow: `0 12px 28px ${PURPLE}55`,
      }}>
        <Wifi color="white" size={26} strokeWidth={2.5} />
      </div>
      <div style={{ flex: 1, minWidth: 240 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 900,
          letterSpacing: "-.01em" }}>
          WiFi Hotspot Multi-Tenant
        </h1>
        <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 14 }}>
          Espaços com portal cativo, captura de leads e campanhas no banner.
        </p>
      </div>
      <a href="/?showcase=wifi" target="_blank" rel="noreferrer"
        data-testid="wifi-hotspot-link-vitrine"
        style={{
          display: "inline-flex", alignItems: "center", gap: 7,
          padding: "10px 16px", borderRadius: 10,
          background: "white", color: PURPLE,
          border: `1.5px solid ${PURPLE}33`,
          fontWeight: 800, fontSize: 13, textDecoration: "none",
          boxShadow: "0 4px 12px rgba(107,43,251,.08)",
        }}>
        Ver vitrine pública
      </a>
    </div>
  );
}

function Tabs({ tab, onChange }) {
  return (
    <div style={{
      marginTop: 22, display: "flex", gap: 6, padding: 4,
      background: "#f1f5f9", borderRadius: 12, overflowX: "auto",
    }} className="hide-scrollbar">
      {TABS.map((t) => {
        const Icon = t.icon;
        const active = tab === t.id;
        return (
          <button key={t.id} onClick={() => onChange(t.id)}
            data-testid={`wifi-hotspot-tab-${t.id}`}
            style={{
              flex: "1 1 0", minWidth: 130,
              padding: "10px 12px", borderRadius: 9,
              border: "none", cursor: "pointer", fontWeight: 800,
              fontSize: 13, display: "inline-flex",
              alignItems: "center", justifyContent: "center", gap: 7,
              background: active ? "white" : "transparent",
              color: active ? PURPLE : "#475569",
              boxShadow: active ? "0 4px 12px rgba(20,8,60,.08)" : "none",
              transition: "background .15s",
            }}>
            <Icon size={14} /> {t.label}
          </button>
        );
      })}
    </div>
  );
}

/* ─────────────────── Overview ─────────────────── */
function OverviewTab() {
  const [s, setS] = useState(null);
  useEffect(() => {
    http().get("/stats").then((r) => setS(r.data)).catch(() => setS({}));
  }, []);
  if (!s) return <Loading />;
  const cards = [
    { k: "total_venues", label: "Espaços ativos", color: PURPLE, icon: MapPin },
    { k: "total_visitors", label: "Visitantes capturados", color: "#0ea5e9", icon: Users },
    { k: "sessions_active", label: "Sessões ativas agora", color: "#22c55e", icon: Wifi },
    { k: "sessions_today", label: "Sessões hoje", color: ORANGE, icon: Activity },
    { k: "sessions_week", label: "Sessões 7 dias", color: "#a855f7", icon: Activity },
    { k: "leads_synced_to_funnel", label: "Leads no funil", color: "#ec4899", icon: Megaphone },
  ];
  return (
    <div data-testid="wifi-hotspot-overview">
      <div style={{ display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px,1fr))", gap: 12 }}>
        {cards.map((c) => {
          const Icon = c.icon;
          return (
            <div key={c.k} style={{
              background: "white", border: "1px solid #e2e8f0",
              borderRadius: 14, padding: 16,
              boxShadow: "0 4px 12px rgba(20,8,60,.06)",
            }}>
              <div style={{
                width: 36, height: 36, borderRadius: 10,
                background: `${c.color}1a`, color: c.color,
                display: "grid", placeItems: "center", marginBottom: 10,
              }}><Icon size={18} /></div>
              <div style={{ fontSize: 30, fontWeight: 900, color: "#0f172a",
                letterSpacing: "-.02em" }}>{s[c.k] ?? "—"}</div>
              <div style={{ fontSize: 12, color: "#64748b", marginTop: 2,
                fontWeight: 600 }}>{c.label}</div>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 18, padding: 16, borderRadius: 14,
        background: "linear-gradient(135deg, #f5f3ff, #ede9fe)",
        border: "1px solid #ddd6fe" }}>
        <div style={{ fontWeight: 800, color: PURPLE, fontSize: 13,
          letterSpacing: 1.4, textTransform: "uppercase", marginBottom: 6 }}>
          Conversão funil
        </div>
        <div style={{ fontSize: 22, fontWeight: 900, color: "#0f172a" }}>
          {s.conversion_pct}% dos visitantes viram lead no CRM
        </div>
      </div>
    </div>
  );
}

/* ─────────────────── Venues ─────────────────── */
function VenuesTab() {
  const [items, setItems] = useState(null);
  const [editing, setEditing] = useState(null);
  const [showInactive, setShowInactive] = useState(false);

  const load = () => http()
    .get("/venues", { params: { include_inactive: showInactive } })
    .then((r) => setItems(r.data.items)).catch(() => setItems([]));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [showInactive]);

  if (items === null) return <Loading />;

  return (
    <div data-testid="wifi-hotspot-venues">
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 14 }}>
        <label style={{ display: "inline-flex", alignItems: "center",
          gap: 8, fontSize: 13, color: "#475569", cursor: "pointer" }}>
          <input type="checkbox" checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
            data-testid="wifi-hotspot-show-inactive" />
          Mostrar inativos
        </label>
        <button onClick={() => setEditing({})}
          data-testid="wifi-hotspot-new-venue-btn"
          style={primaryBtn()}>
          <Plus size={16} /> Novo espaço
        </button>
      </div>

      {items.length === 0 ? (
        <Empty icon="" text="Nenhum espaço cadastrado ainda."
          hint="Clique em 'Novo espaço' pra criar o primeiro." />
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {items.map((v) => (
            <VenueCard key={v.id} venue={v}
              onEdit={() => setEditing(v)}
              onChanged={load} />
          ))}
        </div>
      )}

      {editing && (
        <VenueEditModal venue={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}
    </div>
  );
}

function VenueCard({ venue, onEdit, onChanged }) {
  const publicUrl = `${window.location.origin}/wifi/${venue.slug}`;
  const [copied, setCopied] = useState(false);

  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(publicUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { /* ignore */ }
  };

  const handleDelete = async () => {
    if (!window.confirm(`Desativar "${venue.name}"?`)) return;
    await http().delete(`/venues/${venue.id}`);
    onChanged();
  };

  return (
    <div data-testid={`wifi-hotspot-venue-${venue.id}`} style={{
      background: "white", border: "1px solid #e2e8f0", borderRadius: 14,
      padding: 16, boxShadow: "0 4px 12px rgba(20,8,60,.05)",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start",
        gap: 12, marginBottom: 10 }}>
        <div style={{
          width: 44, height: 44, borderRadius: 10,
          background: `linear-gradient(135deg, ${venue.brand?.color_primary || PURPLE}, ${venue.brand?.color_accent || ORANGE})`,
          display: "grid", placeItems: "center",
        }}><MapPin color="white" size={20} /></div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 800, fontSize: 16, color: "#0f172a" }}>
            {venue.name}
            {!venue.active && (
              <span style={{
                marginLeft: 8, padding: "2px 8px", borderRadius: 6,
                background: "#fee2e2", color: "#991b1b",
                fontSize: 10, fontWeight: 800,
              }}>INATIVO</span>
            )}
          </div>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
            <span style={{ fontFamily: "monospace" }}>/{venue.slug}</span>
            {" · "}{venue.session_minutes} min/sessão
            {" · "}{venue.type === "ligo" ? "Ligo" : "Parceiro"}
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={onEdit} style={iconBtn()}
            data-testid={`wifi-hotspot-edit-${venue.id}`}>
            <Pencil size={14} />
          </button>
          <button onClick={handleDelete} style={iconBtn("#dc2626")}
            data-testid={`wifi-hotspot-delete-${venue.id}`}>
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        background: "#f8fafc", border: "1px dashed #cbd5e1",
        borderRadius: 10, padding: "10px 12px",
      }}>
        <span style={{ flex: 1, fontFamily: "monospace", fontSize: 12,
          color: "#475569", overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap" }}>{publicUrl}</span>
        <button onClick={copyUrl} style={smallBtn(copied ? "#22c55e" : PURPLE)}
          data-testid={`wifi-hotspot-copy-${venue.id}`}>
          {copied ? "Copiado!" : <><Copy size={12} /> Copiar</>}
        </button>
        <a href={publicUrl} target="_blank" rel="noreferrer"
          style={smallBtn("#0ea5e9")}>
          <ExternalLink size={12} /> Abrir
        </a>
      </div>

      <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
        {venue.require_phone && <Pill>Telefone</Pill>}
        {venue.require_email && <Pill>E-mail</Pill>}
        {venue.require_cpf && <Pill>CPF</Pill>}
      </div>
    </div>
  );
}

function VenueEditModal({ venue, onClose, onSaved }) {
  const isNew = !venue.id;
  const [form, setForm] = useState({
    name: venue.name || "",
    address: venue.address || "",
    type: venue.type || "ligo",
    session_minutes: venue.session_minutes || 60,
    require_phone: venue.require_phone ?? true,
    require_email: venue.require_email ?? false,
    require_cpf: venue.require_cpf ?? false,
    whatsapp_number: venue.whatsapp_number || "",
    whatsapp_message_template: venue.whatsapp_message_template
      || "Oi! Quero conectar no WiFi grátis da {venue}. Código: #{code}",
    brand: venue.brand || {
      color_primary: PURPLE, color_accent: ORANGE,
      welcome_title: "Bem-vindo ao WiFi grátis",
      welcome_subtitle: "Conecte-se em poucos segundos",
    },
    active: venue.active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const save = async () => {
    setBusy(true); setErr("");
    try {
      if (isNew) {
        await http().post("/venues", form);
      } else {
        await http().put(`/venues/${venue.id}`, form);
      }
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Erro ao salvar.");
    } finally { setBusy(false); }
  };

  return (
    <Modal title={isNew ? "Novo espaço" : "Editar espaço"} onClose={onClose}>
      <div style={{ display: "grid", gap: 12 }}>
        <Field label="Nome do espaço *">
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Ex: Ligo Loja Cordovil"
            data-testid="venue-form-name" style={inp()} />
        </Field>
        <Field label="Endereço">
          <input value={form.address || ""} onChange={(e) => setForm({ ...form, address: e.target.value })}
            data-testid="venue-form-address" style={inp()} />
        </Field>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Tipo">
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}
              data-testid="venue-form-type" style={inp()}>
              <option value="ligo">Ligo (loja própria)</option>
              <option value="parceiro">Parceiro</option>
            </select>
          </Field>
          <Field label="Sessão (min)">
            <input type="number" min="10" max="1440" value={form.session_minutes}
              onChange={(e) => setForm({ ...form, session_minutes: parseInt(e.target.value, 10) || 60 })}
              data-testid="venue-form-session" style={inp()} />
          </Field>
        </div>
        <div>
          <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.2,
            textTransform: "uppercase", color: "#64748b", marginBottom: 6 }}>
            Campos obrigatórios no portal
          </div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {[
              { k: "require_phone", l: "Telefone" },
              { k: "require_email", l: "E-mail" },
              { k: "require_cpf", l: "CPF" },
            ].map((c) => (
              <label key={c.k} style={{ display: "inline-flex",
                alignItems: "center", gap: 6, fontSize: 14, cursor: "pointer" }}>
                <input type="checkbox" checked={form[c.k]}
                  onChange={(e) => setForm({ ...form, [c.k]: e.target.checked })}
                  data-testid={`venue-form-${c.k}`} />
                {c.l}
              </label>
            ))}
          </div>
        </div>
        <Field label="Título de boas-vindas">
          <input value={form.brand.welcome_title || ""}
            onChange={(e) => setForm({ ...form,
              brand: { ...form.brand, welcome_title: e.target.value } })}
            data-testid="venue-form-welcome" style={inp()} />
        </Field>
        <div style={{
          padding: 14, borderRadius: 12,
          background: "linear-gradient(135deg, #fff7ed, #fed7aa)",
          border: "1px solid #fb923c",
        }}>
          <div style={{ display: "flex", alignItems: "center",
            gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 22 }}>️</span>
            <div>
              <div style={{ fontSize: 13, fontWeight: 900,
                color: "#9a3412" }}>
                Anti-bloqueio WhatsApp
              </div>
              <div style={{ fontSize: 11, color: "#9a3412",
                fontWeight: 600 }}>
                Cliente envia msg → você não cai em block do Meta.
              </div>
            </div>
          </div>
          <Field label="Número WhatsApp da venue (com DDI/DDD, só dígitos)">
            <input value={form.whatsapp_number || ""}
              onChange={(e) => setForm({ ...form,
                whatsapp_number: e.target.value.replace(/\D/g, "") })}
              placeholder="Ex: 5521999998888 (deixe vazio pra desativar)"
              data-testid="venue-form-whatsapp-number" style={inp()} />
          </Field>
          <Field label="Mensagem template (`{venue}` `{code}` `{name}`)">
            <textarea value={form.whatsapp_message_template}
              onChange={(e) => setForm({ ...form,
                whatsapp_message_template: e.target.value })}
              rows={2}
              data-testid="venue-form-whatsapp-msg"
              style={{ ...inp(), resize: "vertical",
                fontFamily: "system-ui", fontSize: 13 }} />
          </Field>
        </div>
        <Field label="Subtítulo">
          <input value={form.brand.welcome_subtitle || ""}
            onChange={(e) => setForm({ ...form,
              brand: { ...form.brand, welcome_subtitle: e.target.value } })}
            style={inp()} />
        </Field>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Cor primária">
            <input type="color" value={form.brand.color_primary || PURPLE}
              onChange={(e) => setForm({ ...form,
                brand: { ...form.brand, color_primary: e.target.value } })}
              style={{ ...inp(), padding: 4, height: 40 }} />
          </Field>
          <Field label="Cor de destaque">
            <input type="color" value={form.brand.color_accent || ORANGE}
              onChange={(e) => setForm({ ...form,
                brand: { ...form.brand, color_accent: e.target.value } })}
              style={{ ...inp(), padding: 4, height: 40 }} />
          </Field>
        </div>
        {err && <div style={errStyle}>{err}</div>}
        <button onClick={save} disabled={busy || !form.name}
          data-testid="venue-form-save"
          style={{ ...primaryBtn(), justifyContent: "center" }}>
          {busy ? "Salvando…" : isNew ? "Criar espaço" : "Salvar alterações"}
        </button>
      </div>
    </Modal>
  );
}

/* ─────────────────── Visitors ─────────────────── */
function VisitorsTab() {
  const [items, setItems] = useState(null);
  const [search, setSearch] = useState("");
  useEffect(() => {
    const t = setTimeout(() => {
      http().get("/visitors", { params: search ? { search } : {} })
        .then((r) => setItems(r.data.items)).catch(() => setItems([]));
    }, 300);
    return () => clearTimeout(t);
  }, [search]);
  if (items === null) return <Loading />;
  return (
    <div data-testid="wifi-hotspot-visitors">
      <input value={search} onChange={(e) => setSearch(e.target.value)}
        placeholder="Buscar por nome, telefone, e-mail…"
        data-testid="wifi-hotspot-visitors-search"
        style={{ ...inp(), marginBottom: 14 }} />
      {items.length === 0 ? <Empty icon="" text="Nenhum visitante ainda." /> : (
        <div style={{ background: "white", border: "1px solid #e2e8f0",
          borderRadius: 14, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <Th>Nome</Th><Th>Contato</Th><Th>Visitas</Th>
                <Th>Último acesso</Th><Th>Funil</Th>
              </tr>
            </thead>
            <tbody>
              {items.map((v) => (
                <tr key={v.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                  <Td><b>{v.name || "—"}</b></Td>
                  <Td>
                    <div style={{ fontSize: 12 }}>{v.phone || "—"}</div>
                    <div style={{ fontSize: 11, color: "#64748b" }}>{v.email || ""}</div>
                  </Td>
                  <Td>{v.visits || 1}×</Td>
                  <Td><Date iso={v.last_seen_at} /></Td>
                  <Td>{v.synced_funnel_at
                    ? <Pill color="#22c55e">✓ Sincronizado</Pill>
                    : <Pill color="#94a3b8">Não sync</Pill>}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ─────────────────── Sessions ─────────────────── */
function SessionsTab() {
  const [items, setItems] = useState(null);
  const [onlyActive, setOnlyActive] = useState(true);
  useEffect(() => {
    http().get("/sessions", { params: { only_active: onlyActive } })
      .then((r) => setItems(r.data.items)).catch(() => setItems([]));
  }, [onlyActive]);
  if (items === null) return <Loading />;
  return (
    <div data-testid="wifi-hotspot-sessions">
      <label style={{ display: "inline-flex", alignItems: "center", gap: 8,
        fontSize: 13, color: "#475569", marginBottom: 14, cursor: "pointer" }}>
        <input type="checkbox" checked={onlyActive}
          onChange={(e) => setOnlyActive(e.target.checked)}
          data-testid="wifi-hotspot-only-active" />
        Apenas sessões ativas
      </label>
      {items.length === 0 ? <Empty icon="" text="Nenhuma sessão." /> : (
        <div style={{ background: "white", border: "1px solid #e2e8f0",
          borderRadius: 14, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <Th>Espaço</Th><Th>Dispositivo</Th><Th>Status</Th>
                <Th>Início</Th><Th>Expira</Th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                  <Td><b>{s.venue_slug}</b></Td>
                  <Td>
                    <div style={{ fontSize: 12 }}>
                      {s.device?.os} · {s.device?.browser}
                    </div>
                    <div style={{ fontSize: 11, color: "#64748b",
                      fontFamily: "monospace" }}>{s.ip || "—"}</div>
                  </Td>
                  <Td>
                    {s.status === "active"
                      ? <Pill color="#22c55e">● Ativa</Pill>
                      : <Pill color="#94a3b8">{s.status}</Pill>}
                  </Td>
                  <Td><Date iso={s.started_at} /></Td>
                  <Td><Date iso={s.expires_at} /></Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ─────────────────── Campaigns ─────────────────── */
function CampaignsTab() {
  const [items, setItems] = useState(null);
  const [editing, setEditing] = useState(null);
  const load = () => http().get("/campaigns")
    .then((r) => setItems(r.data.items)).catch(() => setItems([]));
  useEffect(() => { load(); }, []);
  if (items === null) return <Loading />;
  return (
    <div data-testid="wifi-hotspot-campaigns">
      <div style={{ display: "flex", justifyContent: "flex-end",
        marginBottom: 14 }}>
        <button onClick={() => setEditing({})}
          data-testid="wifi-hotspot-new-campaign-btn"
          style={primaryBtn()}>
          <Plus size={16} /> Nova campanha
        </button>
      </div>
      {items.length === 0 ? <Empty icon="" text="Nenhuma campanha cadastrada." /> : (
        <div style={{ display: "grid", gap: 10 }}>
          {items.map((c) => (
            <CampaignRow key={c.id} c={c}
              onEdit={() => setEditing(c)}
              onChanged={load} />
          ))}
        </div>
      )}
      {editing && (
        <CampaignEditModal camp={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}
    </div>
  );
}

function CampaignRow({ c, onEdit, onChanged }) {
  const del = async () => {
    if (!window.confirm(`Desativar "${c.title}"?`)) return;
    await http().delete(`/campaigns/${c.id}`);
    onChanged();
  };
  const ctr = c.impressions
    ? ((c.clicks / c.impressions) * 100).toFixed(1) + "%"
    : "—";
  return (
    <div style={{
      background: "white", border: "1px solid #e2e8f0", borderRadius: 12,
      padding: 14, display: "flex", alignItems: "center", gap: 12,
    }} data-testid={`campaign-${c.id}`}>
      <div style={{
        width: 40, height: 40, borderRadius: 10,
        background: c.active ? "#dcfce7" : "#fee2e2",
        color: c.active ? "#15803d" : "#991b1b",
        display: "grid", placeItems: "center",
      }}><Megaphone size={18} /></div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 800, fontSize: 15 }}>{c.title}</div>
        <div style={{ fontSize: 12, color: "#64748b" }}>
          {c.subtitle || "—"} · CTA: {c.cta_label}
        </div>
      </div>
      <div style={{ textAlign: "right", fontSize: 12, color: "#475569" }}>
        <div>{c.impressions || 0} imp · {c.clicks || 0} clk</div>
        <div style={{ color: "#0ea5e9", fontWeight: 800 }}>CTR {ctr}</div>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <button onClick={onEdit} style={iconBtn()}><Pencil size={14} /></button>
        <button onClick={del} style={iconBtn("#dc2626")}><Trash2 size={14} /></button>
      </div>
    </div>
  );
}

function CampaignEditModal({ camp, onClose, onSaved }) {
  const isNew = !camp.id;
  const [venues, setVenues] = useState([]);
  const [form, setForm] = useState({
    title: camp.title || "",
    subtitle: camp.subtitle || "",
    banner_url: camp.banner_url || "",
    cta_label: camp.cta_label || "Saiba mais",
    cta_url: camp.cta_url || "",
    venue_id: camp.venue_id || null,
    active: camp.active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    http().get("/venues").then((r) => setVenues(r.data.items || []))
      .catch(() => setVenues([]));
  }, []);
  const save = async () => {
    setBusy(true); setErr("");
    try {
      if (isNew) await http().post("/campaigns", form);
      else await http().put(`/campaigns/${camp.id}`, form);
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Erro ao salvar.");
    } finally { setBusy(false); }
  };
  return (
    <Modal title={isNew ? "Nova campanha" : "Editar campanha"} onClose={onClose}>
      <div style={{ display: "grid", gap: 12 }}>
        <Field label="Título *">
          <input value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            data-testid="campaign-form-title" style={inp()} />
        </Field>
        <Field label="Subtítulo">
          <input value={form.subtitle}
            onChange={(e) => setForm({ ...form, subtitle: e.target.value })}
            style={inp()} />
        </Field>
        <Field label="URL do banner (imagem)">
          <input value={form.banner_url}
            onChange={(e) => setForm({ ...form, banner_url: e.target.value })}
            placeholder="https://..." style={inp()} />
        </Field>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Texto do botão">
            <input value={form.cta_label}
              onChange={(e) => setForm({ ...form, cta_label: e.target.value })}
              style={inp()} />
          </Field>
          <Field label="URL do botão">
            <input value={form.cta_url}
              onChange={(e) => setForm({ ...form, cta_url: e.target.value })}
              placeholder="https://..." style={inp()} />
          </Field>
        </div>
        <Field label="Exibir no espaço">
          <select value={form.venue_id || ""}
            onChange={(e) => setForm({ ...form, venue_id: e.target.value || null })}
            data-testid="campaign-form-venue" style={inp()}>
            <option value="">Todos os espaços (global)</option>
            {venues.map((v) => (
              <option key={v.id} value={v.id}>{v.name}</option>
            ))}
          </select>
        </Field>
        <label style={{ display: "inline-flex", alignItems: "center",
          gap: 8, fontSize: 14, cursor: "pointer" }}>
          <input type="checkbox" checked={form.active}
            onChange={(e) => setForm({ ...form, active: e.target.checked })} />
          Campanha ativa
        </label>
        {err && <div style={errStyle}>{err}</div>}
        <button onClick={save} disabled={busy || !form.title}
          data-testid="campaign-form-save"
          style={{ ...primaryBtn(), justifyContent: "center" }}>
          {busy ? "Salvando…" : isNew ? "Criar campanha" : "Salvar"}
        </button>
      </div>
    </Modal>
  );
}

/* ─────────────────── UI helpers ─────────────────── */
function Modal({ title, onClose, children }) {
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.6)",
      backdropFilter: "blur(4px)", zIndex: 100,
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 18, padding: 24, width: "100%",
        maxWidth: 520, maxHeight: "90vh", overflowY: "auto",
        boxShadow: "0 32px 60px rgba(0,0,0,.3)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
          alignItems: "center", marginBottom: 18 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 900 }}>{title}</h2>
          <button onClick={onClose} style={iconBtn()}><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label style={{ display: "block", fontSize: 12, fontWeight: 800,
        color: "#475569", marginBottom: 6 }}>{label}</label>
      {children}
    </div>
  );
}

const Pill = ({ children, color = "#6B2BFB" }) => (
  <span style={{
    display: "inline-block", padding: "3px 10px", borderRadius: 999,
    fontSize: 11, fontWeight: 800, color,
    background: `${color}1a`, border: `1px solid ${color}33`,
  }}>{children}</span>
);

const Th = ({ children }) => (
  <th style={{ textAlign: "left", padding: "10px 14px",
    fontSize: 11, fontWeight: 800, color: "#475569",
    letterSpacing: 1, textTransform: "uppercase" }}>{children}</th>
);
const Td = ({ children }) => (
  <td style={{ padding: "12px 14px", fontSize: 13, color: "#334155" }}>{children}</td>
);

function Date({ iso }) {
  if (!iso) return "—";
  try {
    const d = new window.Date(iso);
    return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit",
      hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

function Empty({ icon, text, hint }) {
  return (
    <div style={{
      padding: 40, textAlign: "center",
      background: "white", border: "1px dashed #cbd5e1", borderRadius: 14,
    }}>
      <div style={{ fontSize: 44, marginBottom: 8 }}>{icon}</div>
      <div style={{ fontWeight: 800, fontSize: 16, color: "#0f172a" }}>{text}</div>
      {hint && <div style={{ fontSize: 13, color: "#64748b",
        marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

function Loading() {
  return <div style={{ padding: 40, textAlign: "center", color: "#94a3b8" }}>Carregando…</div>;
}

const primaryBtn = () => ({
  padding: "10px 16px", borderRadius: 10, border: "none",
  background: `linear-gradient(135deg, ${PURPLE}, #8a4dff)`,
  color: "white", fontWeight: 800, fontSize: 13, cursor: "pointer",
  display: "inline-flex", alignItems: "center", gap: 7,
  boxShadow: `0 8px 20px ${PURPLE}55`,
});

const iconBtn = (color = "#475569") => ({
  width: 32, height: 32, borderRadius: 8,
  background: "#f1f5f9", border: "none", color,
  display: "grid", placeItems: "center", cursor: "pointer",
});

const smallBtn = (color) => ({
  padding: "6px 10px", borderRadius: 8, border: "none",
  background: color, color: "white", fontSize: 11, fontWeight: 800,
  cursor: "pointer", textDecoration: "none",
  display: "inline-flex", alignItems: "center", gap: 4,
});

const inp = () => ({
  width: "100%", boxSizing: "border-box", padding: "10px 12px",
  border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 14,
  outline: "none", background: "white",
});

const errStyle = {
  padding: "10px 12px", borderRadius: 10,
  background: "#fee2e2", color: "#991b1b", fontSize: 13, fontWeight: 600,
};
