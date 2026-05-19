/*
DisparoPromoPanel.js — aba "Promoção / Informação" do Disparo em Massa.

Permite criar mensagens de campanha (texto + imagem opcional) e enviar pra um
público filtrado por status, plano, cidade e tempo de casa. Suporta variáveis
{nome}, {plano}, {valor}, {cidade}.
*/
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Card, Field, inputStyle } from "@/ui";
import {
  Megaphone, Send, Image as ImgIcon, Eye, X,
  Users, AlertCircle, CheckCircle2, Loader2,
} from "lucide-react";

const STATUS_OPTIONS = [
  { v: "active",     label: "Ativos" },
  { v: "suspended",  label: "Suspensos" },
  { v: "canceled",   label: "Cancelados" },
];

const TEMPLATES_SUGGESTED = [
  {
    name: "Aviso de manutenção",
    body: "Olá, {nome}! 📡\n\nVamos realizar uma manutenção programada hoje das 22h às 02h. Pode haver instabilidade no sinal.\n\nObrigada pela paciência! 💜",
  },
  {
    name: "Promoção upgrade plano",
    body: "Oi, {nome}! 🎉\n\nVi que você está com a gente há um bom tempo no plano {plano}. Que tal um upgrade com 50% off no primeiro mês?\n\nResponde aqui que eu te explico! 🚀",
  },
  {
    name: "Aviso de boleto disponível",
    body: "Olá, {nome}! Seu boleto deste mês já está disponível. Caso precise, é só responder aqui. 💜",
  },
];

export default function DisparoPromoPanel() {
  const [template, setTemplate] = useState("");
  const [filters, setFilters] = useState({
    status: ["active"],
    city: "",
    tenure_min_months: "",
    tenure_max_months: "",
    only_with_phone: true,
  });
  const [preview, setPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [mediaB64, setMediaB64] = useState(null);
  const [mediaMime, setMediaMime] = useState(null);
  const [mediaName, setMediaName] = useState(null);
  const [dryRun, setDryRun] = useState(false);
  const [throttle, setThrottle] = useState(2);
  const [sending, setSending] = useState(false);
  const [activeRun, setActiveRun] = useState(null);
  const [history, setHistory] = useState([]);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const buildBody = () => ({
    template,
    status: filters.status.length ? filters.status : null,
    city: filters.city || null,
    tenure_min_months: filters.tenure_min_months ? Number(filters.tenure_min_months) : null,
    tenure_max_months: filters.tenure_max_months ? Number(filters.tenure_max_months) : null,
    only_with_phone: filters.only_with_phone,
  });

  const loadPreview = async () => {
    if (!template.trim()) {
      await window.alert("Digite o texto da mensagem primeiro.");
      return;
    }
    try {
      const r = await api._client.post("/disparo-promo/preview", buildBody())
                                  .then((x) => x.data);
      setPreview(r);
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setLoadingPreview(false); }
  };

  const loadHistory = async () => {
    try {
      const r = await api._client.get("/disparo-promo/history?limit=20")
                                  .then((x) => x.data);
      setHistory(r.runs || []);
    } catch (e) {
      console.warn("histórico promo:", e?.message);
    }
  };

  useEffect(() => { loadHistory(); }, []);

  // Polling do run em curso
  useEffect(() => {
    if (!activeRun?.run_id || activeRun.status === "completed") return;
    const t = setInterval(async () => {
      try {
        const r = await api._client.get(`/disparo-promo/runs/${activeRun.run_id}`)
                                    .then((x) => x.data);
        setActiveRun(r);
        if (r.status === "completed") {
          clearInterval(t);
          loadHistory();
        }
      } catch (e) { /* ignore */ }
    }, 2000);
    return () => clearInterval(t);
  }, [activeRun?.run_id, activeRun?.status]);

  const onMediaChange = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 4 * 1024 * 1024) {
      await window.alert("Imagem muito grande (>4MB)");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const b64 = (reader.result || "").split(",").pop();
      setMediaB64(b64);
      setMediaMime(f.type || "image/jpeg");
      setMediaName(f.name);
    };
    reader.readAsDataURL(f);
  };

  const doSend = async () => {
    setConfirmOpen(false);
    setSending(true);
    try {
      const body = {
        ...buildBody(),
        media_b64: mediaB64,
        media_mimetype: mediaMime,
        throttle_seconds: Number(throttle),
        dry_run: dryRun,
      };
      const r = await api._client.post("/disparo-promo/send", body)
                                  .then((x) => x.data);
      setActiveRun({ ...r, status: "running", sent: 0, failed: 0 });
    } catch (e) {
      await window.alert("Erro ao disparar: " + (e?.response?.data?.detail || e.message));
    } finally { setSending(false); }
  };

  return (
    <div style={{ display: "grid", gap: 14 }} data-testid="disparo-promo-panel">
      <Card title="Compor mensagem"
              subtitle="Use {nome}, {plano}, {valor} ou {cidade} pra personalizar.">
        <div style={{ display: "grid",
                        gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div>
            <Field label="Modelos sugeridos (clique pra preencher)">
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {TEMPLATES_SUGGESTED.map((t) => (
                  <button key={t.name} onClick={() => setTemplate(t.body)}
                            data-testid={`promo-template-${t.name.replace(/\s+/g, "-")}`}
                            style={{
                              padding: "5px 10px",
                              border: "1px solid #cbd5e1",
                              background: "#f8fafc",
                              borderRadius: 14, fontSize: 11,
                              color: "#475569", cursor: "pointer",
                            }}>{t.name}</button>
                ))}
              </div>
            </Field>
            <Field label="Texto da mensagem (até 4000 chars)">
              <textarea value={template}
                          onChange={(e) => setTemplate(e.target.value)}
                          rows={9} placeholder="Olá, {nome}! ..."
                          data-testid="promo-template-input"
                          style={{ ...inputStyle, fontFamily: "inherit",
                                    resize: "vertical" }} />
            </Field>
            <div style={{ fontSize: 11, color: "#64748b" }}>
              {template.length} chars · {template ? template.split("\n").length : 0} linhas
            </div>
          </div>
          <div>
            <Field label="Imagem opcional (será enviada com legenda do texto)">
              <input type="file" accept="image/*" onChange={onMediaChange}
                       data-testid="promo-media-input" />
            </Field>
            {mediaB64 && (
              <div style={{ position: "relative", marginTop: 6 }}>
                <img src={`data:${mediaMime};base64,${mediaB64}`}
                       alt="preview"
                       style={{ maxWidth: "100%", maxHeight: 200,
                                borderRadius: 8, border: "1px solid #e2e8f0" }} />
                <button onClick={() => { setMediaB64(null); setMediaMime(null);
                                          setMediaName(null); }}
                          data-testid="promo-media-remove"
                          style={{
                            position: "absolute", top: 4, right: 4,
                            padding: 4, border: 0,
                            background: "rgba(0,0,0,0.7)", color: "#fff",
                            borderRadius: 999, cursor: "pointer",
                          }}><X size={12} /></button>
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                  {mediaName}
                </div>
              </div>
            )}
          </div>
        </div>
      </Card>

      <Card title="Filtros do público">
        <div style={{ display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                        gap: 12 }}>
          <Field label="Status">
            <select multiple value={filters.status}
                      onChange={(e) => setFilters((s) => ({
                        ...s,
                        status: Array.from(e.target.selectedOptions, (o) => o.value),
                      }))}
                      data-testid="promo-status-select"
                      style={{ ...inputStyle, height: 78 }}>
              {STATUS_OPTIONS.map((o) => (
                <option key={o.v} value={o.v}>{o.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Cidade (contém)">
            <input type="text" value={filters.city}
                     onChange={(e) => setFilters((s) => ({ ...s, city: e.target.value }))}
                     data-testid="promo-city-input"
                     placeholder="Rio de Janeiro" style={inputStyle} />
          </Field>
          <Field label="Tempo de casa min. (meses)">
            <input type="number" value={filters.tenure_min_months} min="0"
                     onChange={(e) => setFilters((s) => ({ ...s, tenure_min_months: e.target.value }))}
                     data-testid="promo-tenure-min" style={inputStyle} />
          </Field>
          <Field label="Tempo de casa máx. (meses)">
            <input type="number" value={filters.tenure_max_months} min="0"
                     onChange={(e) => setFilters((s) => ({ ...s, tenure_max_months: e.target.value }))}
                     data-testid="promo-tenure-max" style={inputStyle} />
          </Field>
        </div>
        <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
          <button onClick={loadPreview} disabled={loadingPreview || !template.trim()}
                    data-testid="promo-preview-btn"
                    style={btnSecondary}>
            {loadingPreview ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />}
            Visualizar público
          </button>
          {preview && (
            <span style={{ fontSize: 13, color: "#0f172a", fontWeight: 600 }}
                    data-testid="promo-audience-count">
              <Users size={13} style={{ verticalAlign: "middle" }} />
              {" "}{preview.audience_count.toLocaleString("pt-BR")} destinatários
            </span>
          )}
        </div>
      </Card>

      {preview?.sample_rendered_message && (
        <Card title="Pré-visualização (1º destinatário)"
                subtitle={preview.sample_recipient_name || ""}>
          <pre style={{
            whiteSpace: "pre-wrap", margin: 0, padding: 12,
            background: "#f0fdf4", border: "1px solid #86efac",
            borderRadius: 8, fontFamily: "inherit", fontSize: 13,
            color: "#14532d",
          }} data-testid="promo-preview-rendered">
            {preview.sample_rendered_message}
          </pre>
        </Card>
      )}

      <Card title="Disparo">
        <div style={{ display: "flex", gap: 12, alignItems: "end",
                        flexWrap: "wrap" }}>
          <Field label="Pausa entre msgs (seg)">
            <input type="number" value={throttle} min="0.5" max="30" step="0.5"
                     onChange={(e) => setThrottle(e.target.value)}
                     data-testid="promo-throttle-input"
                     style={{ ...inputStyle, width: 120 }} />
          </Field>
          <label style={{ display: "flex", alignItems: "center", gap: 6,
                            fontSize: 12, color: "#475569", marginBottom: 6 }}>
            <input type="checkbox" checked={dryRun}
                     onChange={(e) => setDryRun(e.target.checked)}
                     data-testid="promo-dryrun-checkbox" />
            Modo simulação (não envia)
          </label>
          <button onClick={() => setConfirmOpen(true)}
                    disabled={sending || !preview || preview.audience_count === 0}
                    data-testid="promo-send-btn"
                    style={{
                      ...btnPrimary,
                      opacity: (sending || !preview || preview.audience_count === 0) ? 0.5 : 1,
                    }}>
            <Send size={14} />
            {sending ? "Disparando..." : `Disparar para ${preview?.audience_count || 0}`}
          </button>
        </div>
      </Card>

      {activeRun && (
        <Card title="Disparo em andamento"
                subtitle={`Run: ${activeRun.run_id}`}>
          <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(4, 1fr)",
                          gap: 12, marginBottom: 10 }}>
            <Metric label="Total" value={activeRun.total_candidates} />
            <Metric label="Enviadas" value={activeRun.sent || 0} color="#15803d" />
            <Metric label="Falhas" value={activeRun.failed || 0} color="#be123c" />
            <Metric label="Status" value={activeRun.status} color="#6366f1" />
          </div>
          {activeRun.status !== "completed" && (
            <div style={{ height: 6, background: "#f1f5f9",
                            borderRadius: 999, overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: `${activeRun.total_candidates ? ((activeRun.sent + activeRun.failed) / activeRun.total_candidates) * 100 : 0}%`,
                background: "linear-gradient(90deg, #6366f1, #8b5cf6)",
                transition: "width 0.5s ease",
              }} />
            </div>
          )}
        </Card>
      )}

      {history.length > 0 && (
        <Card title="Histórico de disparos">
          <div style={{ display: "grid", gap: 6 }}>
            {history.map((h) => (
              <div key={h.id}
                     data-testid={`promo-history-row-${h.id}`}
                     style={{
                       padding: 8, fontSize: 12,
                       background: "#f8fafc",
                       borderRadius: 6, display: "flex",
                       gap: 10, alignItems: "center",
                     }}>
                <Megaphone size={13} color="#6366f1" />
                <strong>{(h.template || "").slice(0, 40)}...</strong>
                <span style={{ marginLeft: "auto" }}>
                  {h.sent || 0}/{h.total_candidates || 0}
                  {" "}({new Date(h.started_at).toLocaleDateString("pt-BR")})
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {confirmOpen && (
        <div onClick={() => setConfirmOpen(false)}
               style={{
                 position: "fixed", inset: 0,
                 background: "rgba(0,0,0,0.6)", zIndex: 9999,
                 display: "flex", alignItems: "center", justifyContent: "center",
               }}>
          <div onClick={(e) => e.stopPropagation()}
                 data-testid="promo-confirm-modal"
                 style={{
                   background: "#fff", borderRadius: 12, padding: 20,
                   maxWidth: 460, width: "92%",
                 }}>
            <h3 style={{ marginTop: 0 }}>Confirmar disparo?</h3>
            <p>
              Você vai enviar a mensagem para{" "}
              <strong>{preview?.audience_count?.toLocaleString("pt-BR")}</strong>{" "}
              pessoas{dryRun ? " (modo simulação)" : ""}.
            </p>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={() => setConfirmOpen(false)} style={btnSecondary}>
                Cancelar
              </button>
              <button onClick={doSend} style={btnPrimary}
                        data-testid="promo-confirm-send">
                <Send size={14} /> Confirmar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, color = "#0f172a" }) {
  return (
    <div style={{ padding: 10, background: "#f8fafc", borderRadius: 8 }}>
      <div style={{ fontSize: 10, color: "#64748b", textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color }}>
        {value || 0}
      </div>
    </div>
  );
}

const btnPrimary = {
  display: "inline-flex", alignItems: "center", gap: 6,
  padding: "8px 14px", border: 0,
  background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
  color: "#fff", borderRadius: 8, cursor: "pointer",
  fontSize: 13, fontWeight: 600,
};
const btnSecondary = {
  display: "inline-flex", alignItems: "center", gap: 6,
  padding: "7px 12px",
  border: "1px solid #cbd5e1",
  background: "#fff", color: "#475569",
  borderRadius: 8, cursor: "pointer", fontSize: 12,
};
