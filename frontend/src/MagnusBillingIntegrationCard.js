import React, { useCallback, useEffect, useRef, useState } from "react";
import { Phone, Wifi, WifiOff, CheckCircle2, AlertTriangle, Save, Play, Copy, ExternalLink, BookOpen } from "lucide-react";
import { api } from "@/api";
import { Card } from "@/ui";

const inp = {
  width: "100%", padding: "9px 11px",
  border: "1px solid var(--border-default)", borderRadius: 10,
  fontSize: 13, marginBottom: 8,
  background: "var(--bg-surface)", color: "var(--text-primary)",
};
const lbl = {
  fontSize: 11, fontWeight: 700, color: "var(--text-secondary)",
  textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4, display: "block",
};

/* Ponto verde/vermelho/amarelo grande, com pulse quando online. */
function StatusDot({ status }) {
  const map = {
    online:        { color: "#16a34a", bg: "rgba(22,163,74,.18)", label: "ONLINE",        pulse: true },
    error:         { color: "#dc2626", bg: "rgba(220,38,38,.18)", label: "OFFLINE",       pulse: false },
    never_tested:  { color: "#f59e0b", bg: "rgba(245,158,11,.18)", label: "NÃO TESTADA",  pulse: false },
    not_configured:{ color: "#94a3b8", bg: "rgba(148,163,184,.18)", label: "NÃO CONFIG.", pulse: false },
  };
  const s = map[status] || map.not_configured;
  return (
    <div data-testid={`mb-status-dot-${status || "unknown"}`}
         style={{
      display: "inline-flex", alignItems: "center", gap: 8,
      padding: "5px 12px", borderRadius: 999,
      background: s.bg, color: s.color,
      fontSize: 11, fontWeight: 800, letterSpacing: 0.6, textTransform: "uppercase",
    }}>
      <span style={{
        width: 10, height: 10, borderRadius: "50%",
        background: s.color,
        boxShadow: s.pulse ? `0 0 0 0 ${s.color}` : "none",
        animation: s.pulse ? "mb-pulse 1.6s ease-out infinite" : "none",
      }} />
      {s.label}
    </div>
  );
}

export default function MagnusBillingIntegrationCard() {
  const [config, setConfig] = useState({
    url: "", key: "", secret: "",
    sip_did: "", sip_username: "", sip_password: "", sip_server: "",
  });
  const [statusInfo, setStatusInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const tickRef = useRef(null);

  const loadConfig = useCallback(async () => {
    try {
      const r = await api.aihubIntegrations();
      const it = (r.items || []).find((x) => x.type === "magnusbilling");
      if (it && it.config) {
        // config vem com secrets mascarados (•••) — mantém para exibição,
        // mas se o user salvar sem mexer, backend faz o merge.
        setConfig({
          url: it.config.url || "",
          key: it.config.key || "",
          secret: it.config.secret || "",
          sip_did: it.config.sip_did || "",
          sip_username: it.config.sip_username || "",
          sip_password: it.config.sip_password || "",
          sip_server: it.config.sip_server || "",
        });
      }
    } catch { /* ignore */ }
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const r = await api.aihubIntegrationsStatus();
      setStatusInfo(r?.magnusbilling || null);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadConfig();
    loadStatus();
    // Auto-refresh status a cada 30s para o gestor saber se caiu
    tickRef.current = setInterval(loadStatus, 30000);
    return () => { if (tickRef.current) clearInterval(tickRef.current); };
  }, [loadConfig, loadStatus]);

  const save = async () => {
    setBusy(true); setTestResult(null);
    try {
      // Se o secret estiver mascarado (vem com •••), backend mantém o atual
      await api.aihubIntegrationSave("magnusbilling", config);
      setTestResult({ ok: true, msg: "Configuração salva." });
      await loadStatus();
    } catch (e) {
      setTestResult({ ok: false, msg: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const test = async () => {
    setBusy(true); setTestResult(null);
    try {
      const r = await api.aihubMagnusTest();
      setTestResult({ ok: r.ok, msg: r.ok ? "Conectividade OK!" : (r.error || "Erro desconhecido") });
      await loadStatus();
    } catch (e) {
      setTestResult({ ok: false, msg: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const status = statusInfo?.status || "not_configured";

  return (
    <Card title={
      <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
        <Phone size={16} strokeWidth={1.75} />
        MagnusBilling — Telefonia SIP / Asterisk
      </span>
    } data-testid="magnusbilling-settings-card">
      <style>{`
        @keyframes mb-pulse {
          0%   { box-shadow: 0 0 0 0 currentColor; }
          70%  { box-shadow: 0 0 0 10px rgba(0,0,0,0); }
          100% { box-shadow: 0 0 0 0 rgba(0,0,0,0); }
        }
      `}</style>

      <div style={{ display: "flex", justifyContent: "space-between",
                     alignItems: "flex-start", marginBottom: 14, gap: 10, flexWrap: "wrap" }}>
        <p style={{ fontSize: 12, color: "var(--text-secondary)", margin: 0, flex: 1, minWidth: 220 }}>
          Conecte sua instância MagnusBilling para a IA originar/receber chamadas
          via SIP. O monitor automático testa a conexão a cada 60s e atualiza
          o status abaixo — se ficar vermelho, o gestor é avisado.
        </p>
        <StatusDot status={status} />
      </div>

      <label style={lbl}>URL da instância (REST API)</label>
      <input style={inp} type="text"
             value={config.url}
             onChange={(e) => setConfig({ ...config, url: e.target.value })}
             placeholder="https://sip.tudovoip.com.br/mbilling"
             data-testid="mb-input-url" />

      <label style={lbl}>API Key</label>
      <input style={inp} type="password"
             value={config.key}
             onChange={(e) => setConfig({ ...config, key: e.target.value })}
             placeholder="cole aqui a Key gerada no MagnusBilling"
             data-testid="mb-input-key" />

      <label style={lbl}>API Secret</label>
      <input style={inp} type="password"
             value={config.secret}
             onChange={(e) => setConfig({ ...config, secret: e.target.value })}
             placeholder="cole aqui o Secret gerado no MagnusBilling"
             data-testid="mb-input-secret" />

      {/* ----- Conta SIP (registro como ramal para receber/originar ligações) ----- */}
      <div style={{
        marginTop: 18, marginBottom: 8,
        paddingTop: 12,
        borderTop: "1px dashed var(--border-default)",
      }}>
        <div style={{
          fontSize: 11, fontWeight: 800, color: "var(--text-secondary)",
          textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 4,
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <Phone size={12} strokeWidth={2} /> Conta SIP (chamadas)
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 10 }}>
          Credenciais que a Jerusa usa para se registrar como ramal e atender no
          número (DID). Configure essa conta no MagnusBilling primeiro.
        </div>
      </div>

      <label style={lbl}>Número (DID) que a IA atende</label>
      <input style={inp} type="text"
             value={config.sip_did}
             onChange={(e) => setConfig({ ...config, sip_did: e.target.value })}
             placeholder="+552126301933"
             data-testid="mb-input-sip-did" />

      <label style={lbl}>Usuário SIP (ramal)</label>
      <input style={inp} type="text"
             value={config.sip_username}
             onChange={(e) => setConfig({ ...config, sip_username: e.target.value })}
             placeholder="ex.: 1147099675"
             data-testid="mb-input-sip-username" />

      <label style={lbl}>Senha SIP</label>
      <input style={inp} type="password"
             value={config.sip_password}
             onChange={(e) => setConfig({ ...config, sip_password: e.target.value })}
             placeholder="senha do ramal SIP"
             data-testid="mb-input-sip-password" />

      <label style={lbl}>Servidor SIP (host)</label>
      <input style={inp} type="text"
             value={config.sip_server}
             onChange={(e) => setConfig({ ...config, sip_server: e.target.value })}
             placeholder="sip.tudovoip.com.br"
             data-testid="mb-input-sip-server" />

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}
                data-testid="mb-save-btn">
          <Save size={13} strokeWidth={1.75} /> {busy ? "Salvando…" : "Salvar"}
        </button>
        <button className="btn btn-secondary btn-sm" onClick={test} disabled={busy}
                data-testid="mb-test-btn">
          <Play size={13} strokeWidth={1.75} /> {busy ? "Testando…" : "Testar conexão"}
        </button>
      </div>

      {testResult && (
        <div data-testid="mb-test-result" style={{
          marginTop: 12, padding: 10,
          background: testResult.ok ? "var(--success-soft)" : "var(--danger-soft)",
          color: testResult.ok ? "var(--success-soft-fg)" : "var(--danger-soft-fg)",
          borderRadius: 8, fontSize: 12, display: "flex", alignItems: "center", gap: 8,
        }}>
          {testResult.ok ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
          {testResult.msg}
        </div>
      )}

      {statusInfo?.last_test_at && (
        <div data-testid="mb-last-check" style={{
          marginTop: 10, padding: "8px 10px", borderRadius: 8,
          background: "var(--bg-surface-2)", border: "1px solid var(--border-default)",
          fontSize: 11, color: "var(--text-secondary)",
          display: "flex", alignItems: "center", gap: 8,
        }}>
          {status === "online"
            ? <Wifi size={12} strokeWidth={1.75} style={{ color: "#16a34a" }} />
            : <WifiOff size={12} strokeWidth={1.75} style={{ color: "#dc2626" }} />}
          <span>
            <strong>Última verificação:</strong> {new Date(statusInfo.last_test_at).toLocaleString("pt-BR")}
          </span>
          {statusInfo.last_test_error && (
            <span style={{ color: "var(--danger)", marginLeft: "auto" }}>
              {statusInfo.last_test_error}
            </span>
          )}
        </div>
      )}

      {!statusInfo?.configured && (
        <div style={{
          marginTop: 10, padding: 10, borderRadius: 8,
          background: "var(--info-soft)", color: "var(--info-soft-fg)",
          fontSize: 12,
        }}>
          Preencha URL, Key e Secret e clique em <strong>Testar conexão</strong> para
          começar. O monitor automático começa a rodar assim que a integração for salva.
        </div>
      )}

      <SetupWizard didNumber={config.sip_did} sipUsername={config.sip_username} />
    </Card>
  );
}

/* =============================================================
   Setup Wizard — passo-a-passo no MagnusBilling para a Jerusa
   atender o DID. Mostra webhook URL pronto pra copiar.
============================================================= */
function SetupWizard({ didNumber, sipUsername }) {
  const base = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
  const webhookUrl = `${base}/api/voice/sip/incoming`;
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(webhookUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch { /* ignore */ }
  };

  return (
    <div data-testid="mb-setup-wizard" style={{
      marginTop: 18, paddingTop: 14,
      borderTop: "1px dashed var(--border-default)",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 6, marginBottom: 8,
        fontSize: 11, fontWeight: 800, color: "var(--text-secondary)",
        textTransform: "uppercase", letterSpacing: 0.6,
      }}>
        <BookOpen size={12} strokeWidth={2} /> Setup no MagnusBilling — passo-a-passo
        <a href="https://wiki.magnusbilling.org/pt-br/source/modules/index.html#api"
           target="_blank" rel="noopener noreferrer"
           style={{ marginLeft: "auto", fontSize: 10, color: "var(--accent)",
                     display: "inline-flex", alignItems: "center", gap: 3 }}>
          Ver na wiki <ExternalLink size={10} />
        </a>
      </div>

      <ol style={{
        margin: 0, paddingLeft: 18, fontSize: 12, lineHeight: 1.65,
        color: "var(--text-primary)",
      }}>
        <li>
          <strong>Liberar permissões da API Key</strong>: no painel MagnusBilling,
          vá em <span className="mono" style={pillTagStyle}>Configurações → API</span>,
          edite a Key existente, e em <strong>Permissões</strong> marque pelo menos:{" "}
          <span className="mono" style={pillTagStyle}>getInfo</span>{" "}
          <span className="mono" style={pillTagStyle}>getDid</span>{" "}
          <span className="mono" style={pillTagStyle}>getCdr</span>{" "}
          <span className="mono" style={pillTagStyle}>originate</span>.
          {" "}Em <strong>IPs restritos</strong> deixe vazio (ou cole o IP do nosso servidor).
        </li>
        <li>
          <strong>Roteamento do DID {didNumber || "(seu DID)"}</strong>: vá em{" "}
          <span className="mono" style={pillTagStyle}>DIDs → Destino de DIDs</span>,
          adicione um destino apontando o DID para a Conta SIP{" "}
          <span className="mono" style={pillTagStyle}>{sipUsername || "(seu usuário SIP)"}</span>.
        </li>
        <li>
          <strong>Webhook de eventos</strong> (importante!): em{" "}
          <span className="mono" style={pillTagStyle}>Clientes → Contas SIP</span>,
          edite a conta da Jerusa e cole no campo{" "}
          <em>“URL notificações de eventos”</em> a URL abaixo:
          <div style={{
            marginTop: 6, display: "flex", alignItems: "center", gap: 6,
            padding: "8px 10px", border: "1px solid var(--border-default)",
            borderRadius: 8, background: "var(--bg-surface-2)",
          }}>
            <code className="mono" style={{ flex: 1, fontSize: 11, wordBreak: "break-all" }}>
              {webhookUrl}
            </code>
            <button onClick={copy} className="btn btn-ghost btn-sm"
                    data-testid="mb-copy-webhook-btn"
                    style={{ padding: "4px 8px" }}>
              <Copy size={12} /> {copied ? "Copiado!" : "Copiar"}
            </button>
          </div>
        </li>
        <li>
          <strong>SIP Register no nosso servidor</strong>: a Jerusa precisa estar
          registrada como ramal pra <em>receber</em> chamadas. Salve as credenciais
          SIP acima — em breve o backend roda o REGISTER automaticamente
          (próximo deploy).
        </li>
      </ol>

      <div style={{
        marginTop: 12, padding: 10, borderRadius: 8,
        background: "var(--warning-soft)", color: "var(--warning-soft-fg)",
        fontSize: 11, display: "flex", alignItems: "flex-start", gap: 8,
      }}>
        <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: 1 }} />
        <span>
          <strong>Sem o passo 4 (SIP Register):</strong> mesmo configurando 1, 2 e 3,
          a Jerusa não recebe áudio das chamadas — só os eventos via webhook.
          Para áudio bidirecional real, o SIP client backend é necessário.
        </span>
      </div>
    </div>
  );
}

const pillTagStyle = {
  display: "inline-block", padding: "1px 6px", borderRadius: 4,
  background: "var(--bg-surface-2)", border: "1px solid var(--border-default)",
  fontSize: 10.5, fontWeight: 600,
};
