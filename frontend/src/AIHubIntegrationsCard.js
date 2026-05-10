import React, { useEffect, useState } from "react";
import { api } from "@/api";
import {
  Phone, Send, Wifi, WifiOff, Save, Play, Trash2, ChevronDown, ChevronUp,
  CheckCircle2, AlertTriangle, Copy,
} from "lucide-react";

/**
 * Card de configuração das integrações de Atendimento IA — colocado dentro da
 * aba Configurações. As credenciais ficam aqui (centralizadas), e o painel
 * "Atendimento IA" só consome (testa conexão, lista DIDs, etc).
 */
export default function AIHubIntegrationsCard() {
  const [open, setOpen] = useState(true);
  return (
    <section data-testid="aihub-integrations-card"
      style={{ background: "var(--bg-surface)", borderRadius: 12,
                padding: 0, marginBottom: 16, overflow: "hidden",
                border: "1px solid var(--border-default)" }}>
      <button onClick={() => setOpen(!open)}
        style={{
          width: "100%", padding: "14px 18px", border: "none", background: "transparent",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          cursor: "pointer", fontWeight: 700, fontSize: 15, color: "var(--text-primary)",
        }}>
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Phone size={16} /> Integrações de Atendimento IA
        </span>
        {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>
      {open && (
        <div style={{ padding: 18, borderTop: "1px solid var(--border-default)" }}>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 14 }}>
            Configure aqui as credenciais usadas pela aba <strong>Atendimento IA</strong> para
            originar chamadas (MagnusBilling/SIP) e enviar mensagens (WhatsApp Cloud API).
            As chaves ficam criptografadas no banco e mascaradas na interface.
          </div>

          <IntegrationBlock
            type="magnusbilling"
            title="MagnusBilling (SIP / Asterisk)"
            description="URL da instância + chaves API + parâmetros de discagem outbound."
            fields={[
              { key: "url", label: "URL da instância", type: "text",
                placeholder: "https://sip.tudovoip.com.br/mbilling", required: true },
              { key: "key", label: "API Key", type: "password",
                placeholder: "encontrada em Setup → Sistema → API", required: true },
              { key: "secret", label: "API Secret", type: "password",
                placeholder: "mesmo local da Key", required: true },
              { key: "trunk_id", label: "ID do tronco (trunk_id)", type: "text",
                placeholder: "Ex.: 1 (Plans → Trunks)" },
              { key: "caller_id", label: "Caller ID outbound", type: "text",
                placeholder: "Número exibido para o cliente — Ex.: 5511999900000" },
              { key: "originate_path", label: "Endpoint originate", type: "text",
                placeholder: "originate (padrão)" },
              { key: "ai_extension", label: "Ramal da IA (perna A)", type: "text",
                placeholder: "Ex.: 9000 (ramal AGI que conversa com o cliente)" },
            ]}
            testApi={api.aihubMagnusTest}
          />

          <IntegrationBlock
            type="whatsapp_cloud"
            title="WhatsApp Cloud API (Meta Business)"
            description="Para enviar/receber mensagens WhatsApp via API oficial."
            fields={[
              { key: "phone_number_id", label: "Phone Number ID", type: "text",
                placeholder: "Meta Business → WhatsApp → API Setup" },
              { key: "access_token", label: "Access Token", type: "password",
                placeholder: "EAAxxxxxxxxxxxx (token permanente da Cloud API)" },
              { key: "verify_token", label: "Verify Token", type: "password",
                placeholder: "string aleatória sua (cole também no Meta)" },
              { key: "graph_version", label: "Graph API version", type: "text",
                placeholder: "v23.0" },
            ]}
            testApi={api.aihubWhatsappTest}
            extra={<WebhookHint />}
          />
        </div>
      )}
    </section>
  );
}

function IntegrationBlock({ type, title, description, fields, testApi, extra }) {
  const [config, setConfig] = useState({});
  const [meta, setMeta] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const load = async () => {
    const r = await api.aihubIntegrations();
    const it = (r.items || []).find((x) => x.type === type);
    if (it) {
      setConfig(it.config || {});
      setMeta({ status: it.status, last_test_at: it.last_test_at, error: it.last_test_error });
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [type]);

  const save = async () => {
    setBusy(true);
    try {
      await api.aihubIntegrationSave(type, config);
      await load();
      setResult({ ok: true, msg: "Configuração salva." });
    } catch (e) {
      setResult({ ok: false, msg: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const test = async () => {
    setBusy(true);
    try {
      const r = await testApi();
      setResult({ ok: r.ok, msg: r.ok ? "Conectividade OK!" : (r.error || "Erro") });
      await load();
    } catch (e) {
      setResult({ ok: false, msg: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!window.confirm("Remover credenciais salvas?")) return;
    await api.aihubIntegrationDelete(type);
    setConfig({}); setMeta(null); setResult(null);
  };

  return (
    <div data-testid={`int-${type}`}
      style={{
        padding: 16, marginBottom: 14, borderRadius: 10,
        background: "var(--bg-surface-2)", border: "1px solid var(--border-default)",
      }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div style={{ flex: 1 }}>
          <h4 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>{title}</h4>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 3 }}>
            {description}
          </div>
        </div>
        {meta?.status && (
          <span className={`pill pill--${meta.status === "online" ? "success" : meta.status === "error" ? "danger" : "neutral"}`}
            style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            {meta.status === "online" ? <Wifi size={11} /> : <WifiOff size={11} />}
            {meta.status}
          </span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
        {fields.map((f) => (
          <label key={f.key} style={{ display: "block" }}>
            <div style={{
              fontSize: 10, fontWeight: 700, color: "var(--text-secondary)",
              textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3,
            }}>
              {f.label} {f.required && <span style={{ color: "var(--danger)" }}>*</span>}
            </div>
            <input type={f.type || "text"}
              className="input"
              value={config[f.key] || ""}
              onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })}
              placeholder={f.placeholder}
              data-testid={`int-${type}-${f.key}`}
              style={{ width: "100%" }} />
          </label>
        ))}
      </div>

      {result && (
        <div style={{
          marginTop: 10, padding: 8,
          background: result.ok ? "var(--success-soft)" : "var(--danger-soft)",
          color: result.ok ? "var(--success-soft-fg)" : "var(--danger-soft-fg)",
          borderRadius: 6, fontSize: 11, display: "flex", alignItems: "center", gap: 6,
        }}>
          {result.ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
          {result.msg}
        </div>
      )}

      {meta?.last_test_at && (
        <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-muted)" }}>
          Último teste: {meta.last_test_at}{meta.error && (
            <span style={{ color: "var(--danger)" }}> · {meta.error}</span>
          )}
        </div>
      )}

      <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}
          data-testid={`int-${type}-save`}>
          <Save size={12} /> {busy ? "Salvando…" : "Salvar"}
        </button>
        <button className="btn btn-secondary btn-sm" onClick={test} disabled={busy}
          data-testid={`int-${type}-test`}>
          <Play size={12} /> Testar
        </button>
        {meta && (
          <button className="btn btn-ghost btn-sm" onClick={remove}
            style={{ color: "var(--danger)", marginLeft: "auto" }}>
            <Trash2 size={11} /> Remover
          </button>
        )}
      </div>

      {extra}
    </div>
  );
}

function WebhookHint() {
  const base = process.env.REACT_APP_BACKEND_URL?.replace(/\/$/, "") || "";
  const url = `${base}/api/aihub/webhooks/call-event`;
  const copy = () => { navigator.clipboard?.writeText(url); };
  return (
    <div style={{
      marginTop: 10, padding: 10, background: "var(--info-soft)",
      color: "var(--info-soft-fg)", borderRadius: 6, fontSize: 11,
    }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>📌 URL de webhook (cole no Meta):</div>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <code className="mono" style={{ flex: 1, fontSize: 10, wordBreak: "break-all" }}>{url}</code>
        <button onClick={copy} className="btn btn-ghost btn-sm" title="Copiar">
          <Copy size={11} />
        </button>
      </div>
    </div>
  );
}
