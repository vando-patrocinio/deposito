/* =============================================================
   DisparoIaPanel — Estrategista de comunicação ativa.
   Orquestra Alvaro IA (insights) + Isabella IA (execução WhatsApp).
   - KPIs dashboard (10 métricas)
   - Lista de sugestões pendentes/aprovadas/rejeitadas
   - Geração on-demand de novas sugestões (Claude Sonnet 4.5)
   - Aprovação → cria mass_campaign automaticamente
============================================================= */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import {
  Sparkles, Zap, Send, AlertTriangle, Eye, Check, X,
  RefreshCw, Target, TrendingUp, MessageCircle, ShieldAlert,
} from "lucide-react";

const TYPE_META = {
  churn_recovery:     { color: "#dc2626", bg: "#fee2e2", icon: ShieldAlert, label: "Churn" },
  plan_upsell:        { color: "#0d9488", bg: "#ccfbf1", icon: TrendingUp, label: "Upsell" },
  friendly_billing:   { color: "#ca8a04", bg: "#fef9c3", icon: MessageCircle, label: "Cobrança" },
  nps_csat:           { color: "#7c3aed", bg: "#ede9fe", icon: Sparkles, label: "NPS/CSAT" },
  coverage_expansion: { color: "#2563eb", bg: "#dbeafe", icon: Target, label: "Expansão" },
  reactivation:       { color: "#ea580c", bg: "#ffedd5", icon: RefreshCw, label: "Reativação" },
};

export default function DisparoIaPanel() {
  const [kpis, setKpis] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [selectedSug, setSelectedSug] = useState(null);
  const [filter, setFilter] = useState("pending"); // pending | approved | rejected | all

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [k, s] = await Promise.all([
        api._client.get("/disparo-ia/kpis?days=30").then((r) => r.data),
        api._client.get(
          filter === "all"
            ? "/disparo-ia/suggestions"
            : `/disparo-ia/suggestions?status=${filter}`,
        ).then((r) => r.data),
      ]);
      setKpis(k);
      setSuggestions(s.items || []);
    } catch (e) {
      console.error("[DisparoIA] load", e);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const onGenerate = async () => {
    setGenerating(true);
    try {
      const r = await api._client.post(
        "/disparo-ia/generate-suggestions",
        { max_suggestions: 6 },
      ).then((x) => x.data);
      alert(`✓ Disparo IA gerou ${r.suggestions_created} sugestões.`);
      setFilter("pending");
      await loadAll();
    } catch (e) {
      alert("Falha: " + (e?.response?.data?.detail || e.message));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 16 }} data-testid="disparo-ia-panel">
      {/* HEADER */}
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "center", flexWrap: "wrap", gap: 12,
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700,
                        color: "var(--text-primary)",
                        display: "flex", alignItems: "center", gap: 10 }}>
            <Zap size={20} color="#7c3aed" /> Disparo IA
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748b" }}>
            Estrategista que orquestra <strong>Alvaro</strong> (insights) +
            <strong> Isabella</strong> (execução WhatsApp).
            Roda em <strong>Claude Sonnet 4.5</strong>.
          </p>
        </div>
        <button onClick={onGenerate} disabled={generating}
                 data-testid="disparo-generate-btn"
                 style={{
                   padding: "10px 18px", borderRadius: 10, border: "none",
                   background: "linear-gradient(135deg, #7c3aed, #5b21b6)",
                   color: "white", fontWeight: 700, fontSize: 13,
                   cursor: generating ? "wait" : "pointer",
                   display: "inline-flex", alignItems: "center", gap: 8,
                   boxShadow: "0 4px 12px rgba(124,58,237,0.3)",
                   opacity: generating ? 0.6 : 1,
                 }}>
          <Sparkles size={14} />
          {generating ? "Disparo IA pensando..." : "Gerar sugestões"}
        </button>
      </div>

      {/* KPIs DASHBOARD */}
      <KpiDashboard kpis={kpis} />

      {/* FILTROS + LISTA */}
      <Card>
        <div style={{ padding: 14, borderBottom: "1px solid #e2e8f0",
                       display: "flex", justifyContent: "space-between",
                       alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
            Sugestões da Disparo IA
          </h3>
          <div style={{ display: "flex", gap: 6 }}>
            {[
              { id: "pending", label: "Pendentes" },
              { id: "approved", label: "Aprovadas" },
              { id: "rejected", label: "Rejeitadas" },
              { id: "all", label: "Todas" },
            ].map((f) => (
              <button key={f.id} onClick={() => setFilter(f.id)}
                       data-testid={`disparo-filter-${f.id}`}
                       style={{
                         padding: "5px 12px", borderRadius: 6, fontSize: 11,
                         fontWeight: 600, cursor: "pointer",
                         border: "1px solid " + (filter === f.id ? "#7c3aed" : "#cbd5e1"),
                         background: filter === f.id ? "#7c3aed" : "white",
                         color: filter === f.id ? "white" : "#475569",
                       }}>{f.label}</button>
            ))}
          </div>
        </div>
        <div>
          {loading ? (
            <Empty text="Carregando..." />
          ) : suggestions.length === 0 ? (
            <Empty text={filter === "pending"
              ? "Nenhuma sugestão pendente. Clique em 'Gerar sugestões' para a Disparo IA analisar os insights do Alvaro e propor campanhas."
              : `Nenhuma sugestão no status '${filter}'.`} />
          ) : (
            suggestions.map((s) => (
              <SuggestionRow key={s.id} sug={s}
                              onOpen={() => setSelectedSug(s)} />
            ))
          )}
        </div>
      </Card>

      {selectedSug && (
        <SuggestionDetailModal
          suggestion={selectedSug}
          onClose={() => setSelectedSug(null)}
          onChange={async () => { setSelectedSug(null); await loadAll(); }}
        />
      )}
    </div>
  );
}

/* ============================================================= */
function KpiDashboard({ kpis }) {
  if (!kpis) return null;
  const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

  const items = [
    { label: "Campanhas (30d)", value: kpis.campaigns_count, color: "#0f172a" },
    { label: "Enviadas", value: kpis.sent.toLocaleString("pt-BR"), color: "#0f172a" },
    { label: "Delivery", value: pct(kpis.delivery_rate), color: "#16a34a" },
    { label: "Read rate", value: pct(kpis.read_rate), color: "#16a34a" },
    { label: "Reply rate", value: pct(kpis.reply_rate), color: "#0ea5e9" },
    { label: "Positive reply", value: pct(kpis.positive_reply_rate), color: "#0ea5e9" },
    { label: "Save (churn)", value: kpis.save_signals, color: "#dc2626" },
    { label: "Upsell sinalizado", value: kpis.upsell_signals, color: "#0d9488" },
    { label: "Block rate", value: pct(kpis.block_rate), color: "#ca8a04" },
    { label: "Cost / conv.", value: "em breve", color: "#94a3b8",
      hint: "Em breve — depende do channel cost" },
  ];

  return (
    <div data-testid="disparo-kpi-dashboard"
         style={{ display: "grid",
                   gridTemplateColumns: "repeat(auto-fit, minmax(135px, 1fr))",
                   gap: 8 }}>
      {items.map((k, i) => (
        <div key={i} style={{
          padding: 12, borderRadius: 10, background: "white",
          border: "1px solid #e2e8f0",
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8",
                         textTransform: "uppercase", letterSpacing: 0.5,
                         marginBottom: 4 }} title={k.hint || ""}>{k.label}</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: k.color,
                         fontFamily: "JetBrains Mono, monospace" }}>{k.value}</div>
        </div>
      ))}
    </div>
  );
}

/* ============================================================= */
function SuggestionRow({ sug, onOpen }) {
  const meta = TYPE_META[sug.type] || { color: "#64748b", bg: "#f1f5f9",
                                            icon: Sparkles, label: sug.type };
  const Icon = meta.icon;
  const statusBadge = {
    pending: { bg: "#fef3c7", color: "#92400e", label: "Pendente" },
    approved: { bg: "#dcfce7", color: "#166534", label: "Aprovada" },
    rejected: { bg: "#f1f5f9", color: "#64748b", label: "Rejeitada" },
  }[sug.status] || { bg: "#f1f5f9", color: "#64748b", label: sug.status };

  return (
    <div onClick={onOpen}
          data-testid={`disparo-sug-${sug.id}`}
          style={{ padding: "12px 14px", borderBottom: "1px solid #f1f5f9",
                    display: "flex", gap: 12, alignItems: "center",
                    cursor: "pointer", transition: "background 120ms" }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "#fafbfc"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
      <div style={{ width: 36, height: 36, borderRadius: 8,
                     background: meta.bg, color: meta.color,
                     display: "grid", placeItems: "center", flexShrink: 0 }}>
        <Icon size={18} strokeWidth={2.2} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center",
                       flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
            {sug.title}
          </span>
          <span style={{ padding: "1px 7px", borderRadius: 4,
                          fontSize: 9, fontWeight: 800,
                          background: meta.bg, color: meta.color,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
            {meta.label}
          </span>
          <span style={{ padding: "1px 7px", borderRadius: 4,
                          fontSize: 9, fontWeight: 700,
                          background: statusBadge.bg, color: statusBadge.color,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
            {statusBadge.label}
          </span>
        </div>
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 3,
                       overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>
          {sug.rationale}
        </div>
        <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2 }}>
          🎯 {sug.audience_preview?.size ?? 0} destinatário(s) ·
          {sug.priority && (
            <span style={{
              marginLeft: 6,
              color: sug.priority === "alta" ? "#dc2626" :
                       sug.priority === "media" ? "#ca8a04" : "#64748b",
              fontWeight: 600, textTransform: "uppercase",
            }}>{sug.priority}</span>
          )}
        </div>
      </div>
      <Eye size={16} color="#94a3b8" />
    </div>
  );
}

/* ============================================================= */
function SuggestionDetailModal({ suggestion, onClose, onChange }) {
  const meta = TYPE_META[suggestion.type] || { color: "#64748b", bg: "#f1f5f9",
                                                  icon: Sparkles, label: suggestion.type };
  const Icon = meta.icon;

  const [message, setMessage] = useState(suggestion.message_template || "");
  const [briefing, setBriefing] = useState(suggestion.isabella_briefing || "");
  const [notes, setNotes] = useState("");
  const [channel, setChannel] = useState("baileys");
  const [throttle, setThrottle] = useState(60);
  const [busy, setBusy] = useState(false);
  const isPending = suggestion.status === "pending";

  const approve = async () => {
    const size = suggestion.audience_preview?.size || 0;
    const msg = "Aprovar e criar campanha real?\n\n"
              + `${size} destinatário(s) serão importados.\n`
              + "A campanha começa em rascunho — vc dá Start em Disparo em Massa.";
    if (!window.confirm(msg)) return;
    setBusy(true);
    try {
      const r = await api._client.post(
        `/disparo-ia/suggestions/${suggestion.id}/approve`,
        {
          channel, throttle_per_min: throttle,
          edited_message: message, edited_briefing: briefing,
          notes: notes || null,
        },
      ).then((x) => x.data);
      alert(`✓ Campanha criada: ${r.recipients_inserted} destinatário(s) inseridos.`);
      onChange?.();
    } catch (e) {
      alert("Falha: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const reject = async () => {
    if (!window.confirm("Rejeitar esta sugestão? Ação não pode ser desfeita.")) return;
    setBusy(true);
    try {
      await api._client.post(`/disparo-ia/suggestions/${suggestion.id}/reject`);
      onChange?.();
    } catch (e) {
      alert("Falha: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  return (
    <div onClick={onClose}
          data-testid="disparo-sug-modal"
          style={{ position: "fixed", inset: 0, zIndex: 1000,
                    background: "rgba(2,6,23,0.65)",
                    display: "grid", placeItems: "center", padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ background: "white", borderRadius: 14, padding: 22,
                      maxWidth: 760, width: "100%", maxHeight: "90vh",
                      overflowY: "auto" }}>
        {/* Header */}
        <div style={{ display: "flex", gap: 12, alignItems: "flex-start",
                       marginBottom: 14 }}>
          <div style={{ width: 44, height: 44, borderRadius: 10,
                          background: meta.bg, color: meta.color,
                          display: "grid", placeItems: "center", flexShrink: 0 }}>
            <Icon size={22} strokeWidth={2.2} />
          </div>
          <div style={{ flex: 1 }}>
            <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: "#0f172a" }}>
              {suggestion.title}
            </h3>
            <p style={{ margin: "3px 0 0", fontSize: 11, color: "#64748b" }}>
              Tipo: <strong>{meta.label}</strong> · Audiência:
              <strong> {suggestion.audience_preview?.size || 0} destinatário(s)</strong>
            </p>
          </div>
          <button onClick={onClose}
                   style={{ border: "none", background: "transparent",
                             cursor: "pointer", fontSize: 22, color: "#64748b" }}>×</button>
        </div>

        {/* Rationale */}
        <Section title="Por que esta campanha agora">
          <div style={{ fontSize: 13, color: "#334155", lineHeight: 1.55 }}>
            {suggestion.rationale}
          </div>
        </Section>

        {/* Audiência preview */}
        <Section title="Audiência (preview)">
          <div style={{ fontSize: 12, color: "#475569", marginBottom: 6 }}>
            {suggestion.audience?.description}
          </div>
          {suggestion.audience_preview?.preview?.length > 0 ? (
            <ul style={{ margin: 0, padding: "0 0 0 18px", fontSize: 11,
                          color: "#64748b" }}>
              {suggestion.audience_preview.preview.slice(0, 5).map((p, i) => (
                <li key={i}>
                  {p.name || "—"} · +{p.phone}
                  {p.plan_name && <> · {p.plan_name}</>}
                </li>
              ))}
            </ul>
          ) : (
            <div style={{ fontSize: 11, color: "#94a3b8", fontStyle: "italic" }}>
              Sem preview disponível.
            </div>
          )}
        </Section>

        {/* Mensagem editável */}
        <Section title="Mensagem para o cliente (editável)">
          <textarea value={message} onChange={(e) => setMessage(e.target.value)}
                     disabled={!isPending || busy}
                     data-testid="disparo-msg-edit"
                     rows={4}
                     style={{ width: "100%", padding: 10, borderRadius: 8,
                               border: "1px solid #cbd5e1", fontSize: 13,
                               fontFamily: "inherit", resize: "vertical",
                               background: !isPending ? "#f8fafc" : "white" }} />
          <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 4 }}>
            Variáveis disponíveis: <code>{`{{nome}}`}</code>,
            <code> {`{{plano}}`}</code>, <code>{`{{codigo}}`}</code>
          </div>
        </Section>

        {/* Briefing da Isabella */}
        <Section title="🎓 Briefing para Isabella IA (tom + objeções + escalada)">
          <textarea value={briefing} onChange={(e) => setBriefing(e.target.value)}
                     disabled={!isPending || busy}
                     data-testid="disparo-briefing-edit"
                     rows={4}
                     style={{ width: "100%", padding: 10, borderRadius: 8,
                               border: "1px solid #cbd5e1", fontSize: 12,
                               fontFamily: "inherit", resize: "vertical",
                               background: !isPending ? "#f8fafc" : "white",
                               color: "#475569", lineHeight: 1.55 }} />
        </Section>

        {/* KPIs alvo */}
        <Section title="KPIs alvo desta campanha">
          <div style={{ display: "grid",
                         gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                         gap: 6 }}>
            {Object.entries(suggestion.expected_kpis || {}).map(([k, v]) => (
              <div key={k} style={{ padding: 8, borderRadius: 6,
                                       background: "#f8fafc", border: "1px solid #e2e8f0",
                                       textAlign: "center" }}>
                <div style={{ fontSize: 9, color: "#94a3b8",
                               textTransform: "uppercase", fontWeight: 700,
                               letterSpacing: 0.5 }}>{k}</div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#0f172a",
                               fontFamily: "monospace", marginTop: 2 }}>
                  {typeof v === "number" && v < 1
                    ? `${(v * 100).toFixed(0)}%`
                    : String(v)}
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Janela / Cadência */}
        <Section title="Janela de envio + Cadência">
          <div style={{ fontSize: 12, color: "#475569", lineHeight: 1.6 }}>
            <strong>Horário ideal:</strong>{" "}
            {suggestion.target_send_window?.weekday_hours_start || "—"}h –
            {" "}{suggestion.target_send_window?.weekday_hours_end || "—"}h ·
            {suggestion.target_send_window?.rationale}
            <br />
            <strong>Cadência:</strong> 1º toque +
            {" "}{suggestion.cadence?.first_touch_min ?? 0}min ·
            follow-up após{" "}
            {suggestion.cadence?.followup_after_hours ?? "—"}h ·
            max {suggestion.cadence?.max_followups ?? 1} follow-up(s)
          </div>
        </Section>

        {/* Approve form */}
        {isPending && (
          <>
            <Section title="Parâmetros de envio">
              <div style={{ display: "grid",
                              gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <label style={{ display: "flex", flexDirection: "column",
                                  fontSize: 11, gap: 4 }}>
                  <span style={{ fontWeight: 700, color: "#64748b",
                                  textTransform: "uppercase", letterSpacing: 0.5 }}>
                    Canal
                  </span>
                  <select value={channel}
                           onChange={(e) => setChannel(e.target.value)}
                           data-testid="disparo-channel-select"
                           style={{ padding: 8, borderRadius: 6,
                                     border: "1px solid #cbd5e1", fontSize: 13 }}>
                    <option value="baileys">Baileys (WhatsApp Web · número próprio)</option>
                    <option value="meta_cloud">Meta Cloud API (oficial)</option>
                    <option value="twilio">Twilio</option>
                  </select>
                </label>
                <label style={{ display: "flex", flexDirection: "column",
                                  fontSize: 11, gap: 4 }}>
                  <span style={{ fontWeight: 700, color: "#64748b",
                                  textTransform: "uppercase", letterSpacing: 0.5 }}>
                    Throttle (msgs/min)
                  </span>
                  <input type="number" value={throttle}
                          onChange={(e) => setThrottle(Number(e.target.value))}
                          data-testid="disparo-throttle-input"
                          min={1} max={600}
                          style={{ padding: 8, borderRadius: 6,
                                    border: "1px solid #cbd5e1", fontSize: 13 }} />
                </label>
              </div>
              <div style={{ marginTop: 10 }}>
                <label style={{ display: "flex", flexDirection: "column",
                                  fontSize: 11, gap: 4 }}>
                  <span style={{ fontWeight: 700, color: "#64748b",
                                  textTransform: "uppercase", letterSpacing: 0.5 }}>
                    Notas (opcional)
                  </span>
                  <input value={notes}
                          onChange={(e) => setNotes(e.target.value)}
                          placeholder="Justificativa, ajustes feitos..."
                          style={{ padding: 8, borderRadius: 6,
                                    border: "1px solid #cbd5e1", fontSize: 13 }} />
                </label>
              </div>
            </Section>

            <div style={{ display: "flex", gap: 8, marginTop: 14,
                            justifyContent: "flex-end" }}>
              <button onClick={reject} disabled={busy}
                       data-testid="disparo-reject-btn"
                       style={{
                         padding: "9px 18px", borderRadius: 8, fontSize: 12,
                         fontWeight: 700, cursor: busy ? "wait" : "pointer",
                         background: "white", color: "#dc2626",
                         border: "1.5px solid #fecaca",
                         display: "inline-flex", alignItems: "center", gap: 6,
                       }}>
                <X size={14} /> Rejeitar
              </button>
              <button onClick={approve} disabled={busy}
                       data-testid="disparo-approve-btn"
                       style={{
                         padding: "9px 18px", borderRadius: 8, fontSize: 12,
                         fontWeight: 700, cursor: busy ? "wait" : "pointer",
                         background: "#16a34a", color: "white", border: "none",
                         display: "inline-flex", alignItems: "center", gap: 6,
                       }}>
                <Check size={14} /> {busy ? "Processando..." : "Aprovar e criar campanha"}
              </button>
            </div>
          </>
        )}

        {!isPending && suggestion.campaign_id && (
          <div style={{ marginTop: 14, padding: 12, borderRadius: 8,
                          background: "#dcfce7", color: "#166534", fontSize: 12 }}>
            ✓ Aprovada · Campanha vinculada: <code>{suggestion.campaign_id}</code>.
            Vá em <strong>Disparo em Massa</strong> para iniciar/monitorar o envio.
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#7c3aed",
                     textTransform: "uppercase", letterSpacing: 0.7,
                     marginBottom: 6 }}>{title}</div>
      {children}
    </div>
  );
}

function Empty({ text }) {
  return (
    <div style={{ padding: 30, textAlign: "center", color: "#94a3b8",
                   fontSize: 13 }}>
      <Sparkles size={22} style={{ opacity: 0.4, marginBottom: 8 }} />
      <div>{text}</div>
    </div>
  );
}
