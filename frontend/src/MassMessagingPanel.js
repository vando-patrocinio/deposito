import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, inputStyle } from "@/ui";
import {
  Megaphone, Plus, Upload, Play, Pause, Trash2, Eye,
  Users, CheckCircle2, XCircle, Clock, Zap,
} from "lucide-react";
import DisparoIaPanel from "@/DisparoIaPanel";
import DisparoPromoPanel from "@/DisparoPromoPanel";
import QuickCampaignsPanel from "@/QuickCampaignsPanel";
import ErrorBoundary from "@/ErrorBoundary";

const fmtDate = (s) => s ? new Date(s).toLocaleString("pt-BR") : "—";

export default function MassMessagingPanel() {
  const [tab, setTab] = useState("quick"); // quick | manual | promo | disparo_ia
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState(null);
  const [disparoPending, setDisparoPending] = useState(0);

  async function reload() {
    setLoading(true);
    try {
      const r = await api._client.get("/mass-messaging/campaigns")
                              .then((r) => r.data);
      setCampaigns(r);
    } finally { setLoading(false); }
  }
  useEffect(() => { reload(); }, []);
  // Pending count para o badge da aba Disparo IA
  useEffect(() => {
    let cancel = false;
    const load = async () => {
      try {
        const r = await api._client.get("/disparo-ia/pending-count")
                              .then((x) => x.data);
        if (!cancel) setDisparoPending(r.pending || 0);
      } catch { /* silent */ }
    };
    load();
    const t = setInterval(load, 30000);
    return () => { cancel = true; clearInterval(t); };
  }, []);
  useEffect(() => {
    if (!selected) return;
    const t = setInterval(async () => {
      const c = await api._client.get(`/mass-messaging/campaigns/${selected.id}`)
                              .then((r) => r.data).catch(() => null);
      if (c) setSelected(c);
    }, 4000);
    return () => clearInterval(t);
  }, [selected?.id]); // eslint-disable-line

  if (selected) {
    return <CampaignDetail camp={selected} onBack={() => { setSelected(null); reload(); }} />;
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700,
                     color: "var(--text-primary)",
                     letterSpacing: "-0.02em", margin: 0,
                     display: "flex", alignItems: "center", gap: 10 }}>
          <Megaphone size={22} /> Disparo em Massa
        </h1>
        {tab === "manual" && (
          <Button onClick={() => setCreating(true)}
                  data-testid="camp-new-btn">
            <Plus size={14} /> Nova campanha
          </Button>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e2e8f0" }}>
        {[
          { id: "quick", label: "Campanhas rápidas", icon: Zap },
          { id: "manual", label: "Campanhas manuais", icon: Megaphone },
          { id: "promo", label: "Promoção / Aviso", icon: Megaphone },
          { id: "disparo_ia", label: "Disparo IA", icon: Zap },
        ].map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          return (
            <button key={t.id} onClick={() => setTab(t.id)}
                     data-testid={`mass-tab-${t.id}`}
                     style={{
                       padding: "10px 18px", border: "none",
                       background: "transparent", cursor: "pointer",
                       fontSize: 13, fontWeight: active ? 700 : 500,
                       color: active ? "#7c3aed" : "#64748b",
                       borderBottom: "2px solid " + (active ? "#7c3aed" : "transparent"),
                       marginBottom: -1,
                       display: "inline-flex", alignItems: "center", gap: 6,
                       transition: "color 150ms",
                     }}>
              <Icon size={14} /> {t.label}
              {t.id === "disparo_ia" && disparoPending > 0 && (
                <span data-testid="disparo-pending-badge"
                       style={{
                         marginLeft: 4, padding: "1px 7px", borderRadius: 999,
                         background: "#7c3aed", color: "white",
                         fontSize: 10, fontWeight: 800, minWidth: 18,
                         textAlign: "center", lineHeight: 1.4,
                       }}>
                  {disparoPending}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {tab === "quick" ? (
        <ErrorBoundary name="quick-campaigns"
                         fallbackText="O painel de Campanhas Rápidas encontrou um erro. Recarregue para tentar de novo.">
          <QuickCampaignsPanel />
        </ErrorBoundary>
      ) : tab === "disparo_ia" ? (
        <ErrorBoundary name="disparo-ia"
                         fallbackText="O painel de Disparo IA encontrou um erro. Recarregue para tentar de novo — os outros recursos seguem ativos.">
          <DisparoIaPanel />
        </ErrorBoundary>
      ) : tab === "promo" ? (
        <ErrorBoundary name="disparo-promo">
          <DisparoPromoPanel />
        </ErrorBoundary>
      ) : (
      <Card title="Campanhas">
        {loading ? (
          <div style={{ color: "#94a3b8" }}>Carregando…</div>
        ) : campaigns.length === 0 ? (
          <div style={{ textAlign: "center", padding: 30,
                        color: "#94a3b8", fontSize: 13 }}>
            Nenhuma campanha. Clique em <strong>Nova campanha</strong>.
          </div>
        ) : (
          <div className="table-wrap"
                  style={{ border: "1px solid #e2e8f0", borderRadius: 10,
                            overflow: "hidden", overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13, minWidth: 700 }}>
              <thead>
                <tr style={{ background: "#f8fafc" }}>
                  {["Nome", "Canal", "Modo", "Total", "Enviadas", "Status",
                    "Criada"].map((h, i) => (
                    <th key={i} style={{
                      padding: "10px 14px", textAlign: "left",
                      fontSize: 11, fontWeight: 700, color: "#475569",
                      textTransform: "uppercase", letterSpacing: 0.4,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => (
                  <tr key={c.id} style={{ borderTop: "1px solid #f1f5f9",
                                            cursor: "pointer" }}
                      onClick={() => setSelected(c)}
                      data-testid={`camp-row-${c.id}`}>
                    <td style={{ padding: "10px 14px", fontWeight: 600,
                                  color: "#0f172a" }}>
                      {c.name}
                    </td>
                    <td style={{ padding: "10px 14px", color: "#64748b" }}>
                      {c.channel === "meta_cloud" ? "Meta WhatsApp" : "Twilio"}
                    </td>
                    <td style={{ padding: "10px 14px", color: "#64748b" }}>
                      {c.mode === "template" ? "Template" : "Livre"}
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      {c.total_recipients || 0}
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      <span style={{ color: "#16a34a", fontWeight: 600 }}>
                        {c.sent}
                      </span>
                      {c.failed > 0 && (
                        <span style={{ color: "#dc2626", marginLeft: 6 }}>
                          ({c.failed} falhas)
                        </span>
                      )}
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      <StatusBadge status={c.status} />
                    </td>
                    <td style={{ padding: "10px 14px", color: "#64748b",
                                  fontSize: 11 }}>
                      {fmtDate(c.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      )}

      {creating && (
        <CampaignCreateModal
          onClose={() => setCreating(false)}
          onCreated={(c) => { setCreating(false); setSelected(c); reload(); }}
        />
      )}
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    draft: { bg: "#f1f5f9", fg: "#64748b", label: "Rascunho" },
    queued: { bg: "#dbeafe", fg: "#1e40af", label: "Agendada" },
    running: { bg: "#dcfce7", fg: "#166534", label: "Enviando" },
    paused: { bg: "#fef9c3", fg: "#854d0e", label: "Pausada" },
    done: { bg: "#e0e7ff", fg: "#3730a3", label: "Concluída" },
  };
  const s = map[status] || map.draft;
  return (
    <span style={{
      display: "inline-block", padding: "3px 10px", borderRadius: 999,
      background: s.bg, color: s.fg, fontSize: 11, fontWeight: 700,
    }}>{s.label}</span>
  );
}

/* ============================================================ */
/* Mapa de Variáveis Disponíveis — referência colapsável        */
/* ============================================================ */
const TEMPLATE_VARIABLES = [
  { group: "Cliente", items: [
    { key: "name",        desc: "Nome completo do cliente",     example: "Maria José Silva" },
    { key: "nome",        desc: "Apelido (primeiro nome)",       example: "Maria" },
    { key: "cpf",         desc: "CPF/CNPJ do cliente",            example: "123.456.789-00" },
    { key: "email",       desc: "E-mail principal",                example: "maria@email.com" },
    { key: "cidade",      desc: "Cidade do endereço",              example: "Rio de Janeiro" },
    { key: "bairro",      desc: "Bairro",                          example: "Tijuca" },
    { key: "endereco",    desc: "Logradouro + número",             example: "Rua X, 123" },
  ]},
  { group: "Plano & Valor", items: [
    { key: "plano",       desc: "Nome do plano contratado",       example: "1 Giga" },
    { key: "velocidade",  desc: "Velocidade (Mbps)",               example: "1000" },
    { key: "valor",       desc: "Valor mensal (R$)",               example: "99,90" },
  ]},
  { group: "Fatura / Cobrança", items: [
    { key: "vencimento",  desc: "Data de vencimento",              example: "10/06/2026" },
    { key: "dias_atraso", desc: "Dias em atraso (se vencido)",     example: "3" },
    { key: "valor_atualizado", desc: "Valor com multa+juros",      example: "102,40" },
    { key: "competencia", desc: "Mês de referência",               example: "05/2026" },
    { key: "boleto_url",  desc: "Link do boleto/PIX",              example: "https://..." },
  ]},
  { group: "Sistema (CSV upload)", items: [
    { key: "1", desc: "1ª coluna extra do CSV (após phone)",       example: "—" },
    { key: "2", desc: "2ª coluna extra do CSV",                    example: "—" },
    { key: "3", desc: "3ª coluna extra do CSV",                    example: "—" },
  ]},
];

/* ============================================================ */
/* Preview ao vivo da mensagem — balão estilo WhatsApp           */
/* ============================================================ */
// Flatten dos exemplos para renderizar a mensagem como o cliente receberia
const PREVIEW_EXAMPLE_VALUES = TEMPLATE_VARIABLES.reduce((acc, g) => {
  g.items.forEach((v) => {
    if (v.example && v.example !== "—") acc[v.key.toLowerCase()] = v.example;
  });
  return acc;
}, {});

function renderTemplate(text, vars) {
  if (!text) return "";
  let out = text;
  // Substitui {{key}} (case-insensitive) pelos valores; placeholders sem valor
  // ficam destacados visualmente para alertar o gestor.
  out = out.replace(/\{\{\s*([a-zA-Z0-9_\-.]+)\s*\}\}/g, (match, key) => {
    const lc = (key || "").toLowerCase();
    if (vars[lc] !== undefined) return vars[lc];
    return `[${key}?]`;  // não encontrado — destaca pro gestor ver
  });
  return out;
}

function MessagePreview({ text }) {
  const empty = !text || !text.trim();
  const rendered = empty ? "" : renderTemplate(text, PREVIEW_EXAMPLE_VALUES);
  const hasMissing = !empty && /\[[a-zA-Z0-9_\-.]+\?\]/.test(rendered);
  return (
    <div
      data-testid="message-preview"
      style={{
        marginTop: 10,
        background: "#e7f3fe",
        border: "1px solid #bfdbfe",
        borderRadius: 10,
        padding: 12,
      }}
    >
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        fontSize: 10, fontWeight: 700, color: "#1e40af",
        letterSpacing: 1, textTransform: "uppercase", marginBottom: 8,
      }}>
        <span> Preview ao vivo (exemplo)</span>
        {hasMissing && (
          <span style={{
            background: "#fef3c7", color: "#92400e",
            padding: "2px 8px", borderRadius: 999,
            fontSize: 9, fontWeight: 700,
          }}>
            variáveis não mapeadas
          </span>
        )}
      </div>
      {/* Balão estilo WhatsApp */}
      <div style={{
        background: "#d9fdd3",
        borderRadius: "12px 12px 12px 4px",
        padding: "10px 14px",
        maxWidth: "90%",
        boxShadow: "0 1px 0.5px rgba(11,20,26,.13)",
        position: "relative",
      }}>
        {empty ? (
          <span style={{
            color: "#94a3b8", fontStyle: "italic", fontSize: 13,
          }}>
            Escreva a mensagem acima — o preview aparece aqui.
          </span>
        ) : (
          <div
            data-testid="preview-bubble-text"
            style={{
              whiteSpace: "pre-wrap", wordBreak: "break-word",
              fontSize: 13.5, lineHeight: 1.45, color: "#0f172a",
              fontFamily: "system-ui, -apple-system, sans-serif",
            }}
            dangerouslySetInnerHTML={{
              __html: rendered
                .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                // Destaca placeholders não mapeados
                .replace(/\[([a-zA-Z0-9_\-.]+)\?\]/g,
                  '<span style="background:#fef3c7;color:#92400e;padding:1px 4px;border-radius:3px;font-weight:600;">[$1?]</span>')
                // Bold do WhatsApp: *texto*
                .replace(/\*([^*\n]+)\*/g, "<b>$1</b>")
                // Italic do WhatsApp: _texto_
                .replace(/(^|\s)_([^_\n]+)_(\s|$)/g, "$1<i>$2</i>$3"),
            }}
          />
        )}
        {!empty && (
          <div style={{
            textAlign: "right", fontSize: 10, color: "#667781",
            marginTop: 4,
          }}>
            12:34  ✓✓
          </div>
        )}
      </div>
      <div style={{
        fontSize: 11, color: "#64748b", marginTop: 8,
      }}>
        Valores de exemplo. No envio real, cada destinatário recebe os
        próprios dados (CSV + cadastro do assinante).
      </div>
    </div>
  );
}

function VariablesReference({ onInsert }) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="vars-reference" style={{ marginTop: 8 }}>
      <button
        type="button"
        data-testid="vars-toggle"
        onClick={() => setOpen((v) => !v)}
        style={{
          background: "#f1f5f9", color: "#0f172a", border: "1px solid #cbd5e1",
          padding: "5px 10px", borderRadius: 6, cursor: "pointer",
          fontSize: 12, fontWeight: 600,
          display: "inline-flex", alignItems: "center", gap: 6,
        }}
      >
        {open ? "▼" : "▶"} Variáveis disponíveis (mapa)
      </button>
      {open && (
        <div style={{
          marginTop: 8,
          background: "#f8fafc", border: "1px solid #e2e8f0",
          borderRadius: 8, padding: 12,
        }}>
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 10 }}>
            Clique no chip para inserir <code style={{ background: "#fff", padding: "1px 5px", borderRadius: 3 }}>{`{{variavel}}`}</code> no
            cursor da mensagem. As variáveis são preenchidas automaticamente
            por <b>linha do CSV</b> (caso enviado) e <b>dados do cliente</b>
            (quando o telefone faz match com um assinante cadastrado).
          </div>
          {TEMPLATE_VARIABLES.map((g) => (
            <div key={g.group} style={{ marginBottom: 10 }}>
              <div style={{
                fontSize: 10, fontWeight: 700, color: "#64748b",
                letterSpacing: 1, textTransform: "uppercase",
                marginBottom: 6,
              }}>
                {g.group}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {g.items.map((v) => (
                  <button
                    key={v.key}
                    type="button"
                    data-testid={`vars-chip-${v.key}`}
                    onClick={() => onInsert(v.key)}
                    title={`${v.desc} — ex: ${v.example}`}
                    style={{
                      padding: "5px 10px", borderRadius: 999,
                      background: "white", border: "1px solid #cbd5e1",
                      color: "#0f766e", cursor: "pointer",
                      fontSize: 11.5, fontFamily: "JetBrains Mono, monospace",
                      fontWeight: 600,
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = "#ecfdf5";
                      e.currentTarget.style.borderColor = "#0d9488";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "white";
                      e.currentTarget.style.borderColor = "#cbd5e1";
                    }}
                  >
                    {`{{${v.key}}}`}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <div style={{
            marginTop: 4, fontSize: 11, color: "#94a3b8",
            borderTop: "1px dashed #e2e8f0", paddingTop: 8,
          }}>
            Dica: nomes de variáveis aceitos são <b>case-insensitive</b> e
            seguem o cabeçalho do CSV. Se sua coluna for chamada
            <code style={{ background: "#fff", padding: "1px 5px", borderRadius: 3, marginLeft: 4 }}>cidade</code>,
            use <code style={{ background: "#fff", padding: "1px 5px", borderRadius: 3 }}>{`{{cidade}}`}</code> no
            texto. Variáveis ausentes ficam em branco no envio.
          </div>
        </div>
      )}
    </div>
  );
}

function CampaignCreateModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    name: "", channel: "meta_cloud", mode: "free",
    text: "", template_name: "", template_language: "pt_BR",
    schedule_at: "", throttle_per_min: 60, channel_id: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [channels, setChannels] = useState([]);
  const textareaRef = useRef(null);

  // Insere {{variavel}} no cursor do textarea (chip do mapa de variáveis)
  const insertVarAtCursor = (varName) => {
    const ta = textareaRef.current;
    const placeholder = `{{${varName}}}`;
    const current = form.text || "";
    if (!ta) {
      setForm({ ...form, text: current + placeholder });
      return;
    }
    const start = ta.selectionStart ?? current.length;
    const end = ta.selectionEnd ?? current.length;
    const next = current.slice(0, start) + placeholder + current.slice(end);
    setForm({ ...form, text: next });
    // Restaura foco e cursor depois do placeholder
    requestAnimationFrame(() => {
      ta.focus();
      const pos = start + placeholder.length;
      try { ta.setSelectionRange(pos, pos); } catch { /* ignore */ }
    });
  };

  // Carrega canais Baileys quando o usuário escolhe canal=baileys
  useEffect(() => {
    if (form.channel !== "baileys") { setChannels([]); return; }
    let alive = true;
    api.waChannelsList().then((d) => {
      if (!alive) return;
      setChannels(d?.channels || []);
    }).catch(() => { /* ignore */ });
    return () => { alive = false; };
  }, [form.channel]);

  async function create() {
    setBusy(true); setErr("");
    try {
      const payload = { ...form };
      if (!payload.schedule_at) delete payload.schedule_at;
      if (payload.mode === "free") {
        delete payload.template_name;
      } else {
        delete payload.text;
      }
      if (payload.channel !== "baileys" || !payload.channel_id) {
        delete payload.channel_id;
      }
      const c = await api._client.post("/mass-messaging/campaigns", payload)
                              .then((r) => r.data);
      onCreated(c);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose} title="Nova campanha" testId="camp-modal">
      <Field label="Nome *">
        <input style={inputStyle} value={form.name}
               onChange={(e) => setForm({ ...form, name: e.target.value })}
               data-testid="camp-fld-name" />
      </Field>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
        <Field label="Canal *">
          <select style={inputStyle} value={form.channel}
                  onChange={(e) => setForm({ ...form, channel: e.target.value })}
                  data-testid="camp-fld-channel">
            <option value="meta_cloud">Meta WhatsApp Cloud</option>
            <option value="twilio">Twilio WhatsApp</option>
            <option value="baileys">WhatsApp QR (Baileys)</option>
          </select>
        </Field>
        <Field label="Modo *">
          <select style={inputStyle} value={form.mode}
                  onChange={(e) => setForm({ ...form, mode: e.target.value })}
                  data-testid="camp-fld-mode">
            <option value="free">Texto livre (24h)</option>
            <option value="template">Template aprovado (HSM)</option>
          </select>
        </Field>
      </div>
      {form.channel === "baileys" && (
        <Field
          label="Número de origem (canal Baileys)"
          hint="Em branco = usa o canal padrão outbound da empresa."
        >
          <select
            style={inputStyle}
            value={form.channel_id}
            onChange={(e) => setForm({ ...form, channel_id: e.target.value })}
            data-testid="camp-fld-channel-id"
          >
            <option value="">Padrão outbound da empresa</option>
            {channels.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {ch.channel_name}
                {ch.phone_number ? ` · +${ch.phone_number}` : ""}
                {ch.is_default_outbound ? " " : ""}
                {ch.live_connected ? "" : " (offline)"}
              </option>
            ))}
          </select>
        </Field>
      )}
      {form.mode === "free" ? (
        <Field label="Mensagem * (use {{nome}}, {{variavel}} para placeholders)">
          <textarea
            ref={textareaRef}
            style={{ ...inputStyle, minHeight: 100, resize: "vertical" }}
            value={form.text}
            onChange={(e) => setForm({ ...form, text: e.target.value })}
            placeholder="Olá {{name}}, sua fatura vence em {{vencimento}}."
            data-testid="camp-fld-text"
          />
          <MessagePreview text={form.text} />
          <VariablesReference
            onInsert={insertVarAtCursor}
          />
        </Field>
      ) : (
        <>
          <Field label="Nome do template *">
            <input style={inputStyle} value={form.template_name}
                   onChange={(e) => setForm({ ...form, template_name: e.target.value })}
                   placeholder="cobranca_2via"
                   data-testid="camp-fld-template" />
          </Field>
          <Field label="Idioma">
            <input style={inputStyle} value={form.template_language}
                   onChange={(e) => setForm({ ...form, template_language: e.target.value })} />
          </Field>
        </>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
        <Field label="Throttle (msgs/min)" hint="Meta recomenda <80">
          <input style={inputStyle} type="number" min="1" max="600"
                 value={form.throttle_per_min}
                 onChange={(e) => setForm({ ...form, throttle_per_min: Number(e.target.value) })} />
        </Field>
        <Field label="Agendar para (opcional)">
          <input style={inputStyle} type="datetime-local"
                 value={form.schedule_at}
                 onChange={(e) => setForm({ ...form, schedule_at: e.target.value })} />
        </Field>
      </div>
      {err && <ErrBox msg={err} />}
      <ModalActions onClose={onClose} onSave={create} busy={busy}
                    testId="camp-create-btn" saveLabel="Criar" />
    </Modal>
  );
}

// =========================================================================
// CAMPAIGN DETAIL — upload, preview, start/pause, recipients
// =========================================================================
function CampaignDetail({ camp, onBack }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [recipients, setRecipients] = useState([]);
  const [preview, setPreview] = useState(null);
  const [recipFilter, setRecipFilter] = useState("");

  async function loadRecipients() {
    const params = recipFilter ? `?status=${recipFilter}` : "";
    const r = await api._client.get(
      `/mass-messaging/campaigns/${camp.id}/recipients${params}`,
    ).then((r) => r.data).catch(() => []);
    setRecipients(r);
  }
  useEffect(() => { loadRecipients(); }, [camp.total_recipients, recipFilter]); // eslint-disable-line

  async function uploadCsv(file) {
    setBusy(true); setMsg("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api._client.post(
        `/mass-messaging/campaigns/${camp.id}/recipients/upload`, fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      ).then((r) => r.data);
      setMsg(`✓ ${r.inserted} contatos inseridos${r.invalid ? `, ${r.invalid} inválidos` : ""}.`);
      loadRecipients();
      window.location.reload();
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }

  async function loadPreview() {
    const r = await api._client.get(`/mass-messaging/campaigns/${camp.id}/preview`)
                              .then((r) => r.data);
    setPreview(r);
  }

  async function start() {
    setBusy(true); setMsg("");
    try {
      await api._client.post(`/mass-messaging/campaigns/${camp.id}/start`,
                            { force_now: true });
      setMsg("✓ Campanha iniciada. Worker processa em background (~5s/tick).");
      window.location.reload();
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }
  async function pause() {
    await api._client.post(`/mass-messaging/campaigns/${camp.id}/pause`);
    window.location.reload();
  }
  async function resume() {
    await api._client.post(`/mass-messaging/campaigns/${camp.id}/resume`);
    window.location.reload();
  }
  async function remove() {
    if (!await window.confirm("Excluir campanha e todos os destinatários?")) return;
    await api._client.delete(`/mass-messaging/campaigns/${camp.id}`);
    onBack();
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <button onClick={onBack} data-testid="camp-back"
              style={{
                background: "transparent", border: "none",
                color: "#64748b", cursor: "pointer", fontSize: 13,
                alignSelf: "flex-start", padding: 0,
              }}>← Voltar</button>

      <Card title={camp.name}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "flex-start", flexWrap: "wrap", gap: 10 }}>
          <div style={{ fontSize: 13, color: "#64748b" }}>
            <div>Canal: <strong>{camp.channel === "meta_cloud" ? "Meta WhatsApp" : "Twilio"}</strong></div>
            <div>Modo: <strong>{camp.mode === "template" ? "Template HSM" : "Texto livre"}</strong></div>
            <div>Throttle: <strong>{camp.throttle_per_min} msgs/min</strong></div>
            <div style={{ marginTop: 6 }}>
              Status: <StatusBadge status={camp.status} />
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {camp.status === "draft" && camp.total_recipients > 0 && (
              <Button onClick={start} disabled={busy}
                      data-testid="camp-start-btn">
                <Play size={14} /> Iniciar
              </Button>
            )}
            {camp.status === "running" && (
              <Button variant="secondary" onClick={pause}
                      data-testid="camp-pause-btn">
                <Pause size={14} /> Pausar
              </Button>
            )}
            {camp.status === "paused" && (
              <Button onClick={resume} data-testid="camp-resume-btn">
                <Play size={14} /> Retomar
              </Button>
            )}
            <Button variant="ghost" onClick={remove}
                    data-testid="camp-del-btn">
              <Trash2 size={14} color="#dc2626" />
            </Button>
          </div>
        </div>

        <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                      gap: 10, marginTop: 14 }}>
          <Chip label="Total" value={camp.total_recipients}
                icon={Users} />
          <Chip label="Enviadas" value={camp.sent}
                color="#16a34a" icon={CheckCircle2} />
          <Chip label="Falhas" value={camp.failed}
                color={camp.failed > 0 ? "#dc2626" : "#64748b"}
                icon={XCircle} />
          <Chip label="Iniciada" value={camp.started_at
            ? new Date(camp.started_at).toLocaleTimeString("pt-BR")
            : "—"} icon={Clock} />
        </div>

        <div style={{ marginTop: 14, padding: 12, background: "#f8fafc",
                      borderRadius: 8, fontSize: 12, color: "#475569" }}>
          <strong>Mensagem:</strong>
          <div style={{ whiteSpace: "pre-wrap", marginTop: 6,
                        fontFamily: "monospace" }}>
            {camp.mode === "template"
              ? `[Template] ${camp.template_name}`
              : camp.text}
          </div>
        </div>

        {msg && (
          <div style={{ marginTop: 10, padding: 10,
                        background: msg.startsWith("Erro") ? "#fee2e2" : "#dcfce7",
                        color: msg.startsWith("Erro") ? "#991b1b" : "#166534",
                        borderRadius: 8, fontSize: 12 }}>
            {msg}
          </div>
        )}
      </Card>

      <Card title="Destinatários (CSV)">
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                      alignItems: "center", marginBottom: 10 }}>
          <label style={{ cursor: "pointer", display: "inline-flex",
                          alignItems: "center", gap: 6, padding: "8px 16px",
                          background: "#0f172a", color: "#fff",
                          borderRadius: 8, fontSize: 13, fontWeight: 600 }}>
            <Upload size={14} /> Upload CSV
            <input type="file" accept=".csv" style={{ display: "none" }}
                   onChange={(e) => e.target.files?.[0] && uploadCsv(e.target.files[0])}
                   data-testid="camp-csv-upload" />
          </label>
          <Button variant="secondary" onClick={loadPreview}
                  data-testid="camp-preview-btn">
            <Eye size={14} /> Preview (3 amostras)
          </Button>
          <small style={{ color: "#94a3b8", fontSize: 11 }}>
            Headers: phone (obrigatório), name, variáveis customizadas
          </small>
        </div>
        {preview && (
          <div style={{ padding: 12, background: "#f8fafc",
                        border: "1px solid #e2e8f0", borderRadius: 8,
                        marginBottom: 10 }}>
            <strong style={{ fontSize: 12 }}>Preview ({preview.mode}):</strong>
            {preview.samples.map((s, i) => (
              <div key={i} style={{ marginTop: 8, padding: 10,
                                     background: "#fff", borderRadius: 6,
                                     border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: 11, color: "#64748b" }}>
                  {s.phone} · {s.name || ""}
                </div>
                <div style={{ marginTop: 4, fontSize: 13,
                              whiteSpace: "pre-wrap" }}>
                  {s.rendered_text || `[Template: ${preview.template_name}]`}
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          {["", "queued", "sending", "sent", "failed"].map((s) => (
            <button key={s}
              onClick={() => setRecipFilter(s)}
              style={{
                padding: "6px 12px", borderRadius: 8,
                background: recipFilter === s ? "#0f172a" : "#f1f5f9",
                color: recipFilter === s ? "#fff" : "#64748b",
                fontSize: 11, fontWeight: 600,
                border: "none", cursor: "pointer",
              }}>
              {s || "Todos"}
            </button>
          ))}
        </div>

        <div style={{ border: "1px solid #e2e8f0", borderRadius: 10,
                      overflow: "hidden", maxHeight: 400,
                      overflowY: "auto" }}>
          {recipients.length === 0 ? (
            <div style={{ padding: 20, textAlign: "center",
                          color: "#94a3b8" }}>
              Nenhum destinatário neste filtro.
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 12 }}>
              <thead>
                <tr style={{ background: "#f8fafc",
                              position: "sticky", top: 0 }}>
                  {["Telefone", "Nome", "Status", "Enviada", "Erro"]
                  .map((h, i) => (
                    <th key={i} style={{
                      padding: "8px 14px", textAlign: "left",
                      fontSize: 10, fontWeight: 700, color: "#475569",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recipients.slice(0, 200).map((r) => (
                  <tr key={r.id} style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "6px 14px",
                                  fontFamily: "monospace" }}>
                      {r.phone}
                    </td>
                    <td style={{ padding: "6px 14px" }}>{r.name || "—"}</td>
                    <td style={{ padding: "6px 14px" }}>
                      <RecipStatus s={r.status} />
                    </td>
                    <td style={{ padding: "6px 14px", color: "#64748b",
                                  fontSize: 11 }}>
                      {r.sent_at ? new Date(r.sent_at).toLocaleTimeString("pt-BR") : "—"}
                    </td>
                    <td style={{ padding: "6px 14px", color: "#dc2626",
                                  fontSize: 11 }}>
                      {r.error || ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
    </div>
  );
}

function RecipStatus({ s }) {
  const map = {
    queued: { c: "#64748b", l: "Em fila" },
    sending: { c: "#1e40af", l: "Enviando..." },
    sent: { c: "#16a34a", l: "✓ Enviada" },
    delivered: { c: "#16a34a", l: "✓✓ Entregue" },
    failed: { c: "#dc2626", l: "✗ Falha" },
  };
  const v = map[s] || map.queued;
  return <span style={{ color: v.c, fontWeight: 600, fontSize: 11 }}>{v.l}</span>;
}

// Reuso helpers ----------------------------------------
function Modal({ children, onClose, title, testId }) {
  return (
    <div onClick={onClose} data-testid={testId}
         style={{
           position: "fixed", inset: 0, zIndex: 1000,
           background: "rgba(2,6,23,0.7)",
           display: "grid", placeItems: "center", padding: 20,
         }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: "#fff", borderRadius: 14, padding: 24,
             maxWidth: 600, width: "100%",
             maxHeight: "92vh", overflowY: "auto",
             boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
           }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>{title}</h3>
          <button onClick={onClose} style={{
            background: "transparent", border: "none", fontSize: 24,
            color: "#94a3b8", cursor: "pointer", padding: 0,
          }}>×</button>
        </div>
        <div style={{ display: "grid", gap: 12 }}>{children}</div>
      </div>
    </div>
  );
}

function ModalActions({ onClose, onSave, busy, testId, saveLabel = "Salvar" }) {
  return (
    <div style={{ display: "flex", gap: 10, marginTop: 6,
                  justifyContent: "flex-end" }}>
      <Button variant="secondary" onClick={onClose} disabled={busy}>
        Cancelar
      </Button>
      <Button onClick={onSave} disabled={busy} data-testid={testId}>
        {busy ? "Salvando…" : saveLabel}
      </Button>
    </div>
  );
}

function Chip({ label, value, color = "#0f172a", icon: Ico }) {
  return (
    <div style={{
      padding: "10px 14px", borderRadius: 10, background: "#f8fafc",
      border: "1px solid #e2e8f0",
    }}>
      <div style={{ fontSize: 10, color: "#64748b",
                    textTransform: "uppercase", fontWeight: 700,
                    letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 17, fontWeight: 700, color,
                    display: "flex", alignItems: "center", gap: 6 }}>
        {Ico && <Ico size={14} />}
        {value}
      </div>
    </div>
  );
}

function ErrBox({ msg }) {
  return <div style={{ marginTop: 8, padding: 10, background: "#fee2e2",
                        color: "#991b1b", borderRadius: 8, fontSize: 12 }}>
    {msg}
  </div>;
}
