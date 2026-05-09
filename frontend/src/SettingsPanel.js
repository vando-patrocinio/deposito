import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, Icon, inputStyle, StatusBadge } from "@/ui";

export default function SettingsPanel() {
  const [s, setS] = useState(null);
  const [form, setForm] = useState({ resend_api_key: "", sender_email: "", sender_name: "Ponto do Colaborador", openai_api_key: "", monthly_email_enabled: true, location_ping_interval_sec: 15, he_monthly_budget_brl: 0, he_alert_threshold_pct: 30 });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [testEmailTo, setTestEmailTo] = useState("");
  const [testMsg, setTestMsg] = useState("");
  const [testBusy, setTestBusy] = useState(false);
  const [showResendHelp, setShowResendHelp] = useState(false);

  async function reload() {
    const cur = await api.getSettings();
    setS(cur);
    setForm({
      resend_api_key: "",
      sender_email: cur.sender_email || "",
      sender_name: cur.sender_name || "Ponto do Colaborador",
      openai_api_key: "",
      monthly_email_enabled: cur.monthly_email_enabled,
      location_ping_interval_sec: cur.location_ping_interval_sec || 15,
      he_monthly_budget_brl: cur.he_monthly_budget_brl ?? 0,
      he_alert_threshold_pct: cur.he_alert_threshold_pct ?? 30,
    });
  }
  useEffect(() => { reload(); }, []);

  async function save() {
    setBusy(true); setMsg("");
    const payload = { ...form };
    if (!payload.resend_api_key) delete payload.resend_api_key;
    if (!payload.openai_api_key) delete payload.openai_api_key;
    try {
      await api.updateSettings(payload);
      setMsg("Configurações salvas com sucesso.");
      await reload();
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    }
    setBusy(false);
  }

  async function runMonthly() {
    setBusy(true); setMsg("");
    try {
      await api.runMonthlyNow();
      setMsg("Rotina mensal disparada (verifique seu inbox).");
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    }
    setBusy(false);
  }

  async function sendTestEmail() {
    setTestBusy(true); setTestMsg("");
    try {
      const res = await api.testEmail(testEmailTo, "Teste de envio — Ponto do Colaborador");
      setTestMsg(`✅ Enviado para ${res.to} (id: ${res.id})`);
    } catch (e) {
      setTestMsg("❌ " + (e?.response?.data?.detail || e.message));
    }
    setTestBusy(false);
  }

  if (!s) return <Card title="Configurações">Carregando...</Card>;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
      <Card title="Integrações de IA">
        <div style={{ marginBottom: 10 }}>
          {s.emergent_key_available
            ? <StatusBadge status="Aprovado">Emergent Universal Key ativa</StatusBadge>
            : <StatusBadge status="Bloqueado">Emergent Universal Key ausente</StatusBadge>}
          <p style={{ color: "#64748b", fontSize: 13, marginTop: 8 }}>
            Por padrão usamos a Emergent Universal Key (sem custo extra de configuração).
            Se preferir, cole sua própria chave OpenAI abaixo — ela tem prioridade.
          </p>
        </div>
        <Field label={`Chave OpenAI (sk-...) ${s.openai_api_key_set ? "— já existe (cole nova para trocar)" : ""}`}>
          <input
            data-testid="inp-openai-key"
            type="password"
            style={inputStyle}
            value={form.openai_api_key}
            onChange={(e) => setForm({ ...form, openai_api_key: e.target.value })}
            placeholder={s.openai_api_key_set ? s.openai_api_key : "sk-..."}
          />
        </Field>
      </Card>

      <Card title="E-mail mensal (Resend)">
        <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 10px" }}>
          Crie sua conta gratuita em <a href="https://resend.com" target="_blank" rel="noreferrer">resend.com</a> (3.000 e-mails/mês free).
          Após gerar a API key, cole abaixo.
        </p>
        <Field label={`API Key Resend (re_...) ${s.resend_api_key_set ? "— já existe (cole nova para trocar)" : ""}`}>
          <input
            data-testid="inp-resend-key"
            type="password"
            style={inputStyle}
            value={form.resend_api_key}
            onChange={(e) => setForm({ ...form, resend_api_key: e.target.value })}
            placeholder={s.resend_api_key_set ? s.resend_api_key : "re_..."}
          />
        </Field>
        <Field label="E-mail remetente (verificado no Resend)">
          <input data-testid="inp-sender-email" style={inputStyle} value={form.sender_email} onChange={(e) => setForm({ ...form, sender_email: e.target.value })} placeholder="onboarding@resend.dev" />
        </Field>
        <Field label="Nome do remetente">
          <input style={inputStyle} value={form.sender_name} onChange={(e) => setForm({ ...form, sender_name: e.target.value })} />
        </Field>
        <label style={{ display: "flex", gap: 8, alignItems: "center", color: "#475569", fontSize: 14, marginTop: 6 }}>
          <input
            type="checkbox"
            data-testid="chk-monthly"
            checked={form.monthly_email_enabled}
            onChange={(e) => setForm({ ...form, monthly_email_enabled: e.target.checked })}
          />
          Enviar espelho mensal automaticamente no último dia do mês (23:30, fuso de São Paulo)
        </label>
      </Card>

      <Card title="Rastreamento ao vivo (GPS do colaborador)" style={{ gridColumn: "1 / -1" }}>
        <p style={{ color: "#64748b", margin: "0 0 10px", fontSize: 14 }}>
          Define com que frequência o app dos colaboradores envia a localização atual para o painel do gestor.
          Valores menores = mapa mais responsivo, mas consomem mais bateria/dados.
          <br />
          <strong>Recomendado: 15 segundos.</strong>
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 10 }}>
          {[5, 10, 15, 30, 60, 120].map((sec) => (
            <button
              key={sec}
              type="button"
              data-testid={`ping-preset-${sec}`}
              onClick={() => setForm({ ...form, location_ping_interval_sec: sec })}
              style={{
                padding: 12,
                borderRadius: 14,
                border: form.location_ping_interval_sec === sec ? "2px solid #0f172a" : "1px solid #cbd5e1",
                background: form.location_ping_interval_sec === sec ? "#0f172a" : "white",
                color: form.location_ping_interval_sec === sec ? "white" : "#0f172a",
                fontWeight: 800,
                cursor: "pointer",
              }}
            >
              {sec < 60 ? `${sec} s` : `${sec / 60} min`}
            </button>
          ))}
        </div>
        <Field label={`Intervalo personalizado: ${form.location_ping_interval_sec}s ${form.location_ping_interval_sec < 60 ? "" : `(${(form.location_ping_interval_sec / 60).toFixed(1)} min)`}`}>
          <input
            data-testid="ping-interval-slider"
            type="range"
            min={5}
            max={300}
            step={1}
            value={form.location_ping_interval_sec}
            onChange={(e) => setForm({ ...form, location_ping_interval_sec: Number(e.target.value) })}
            style={{ width: "100%" }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", color: "#94a3b8", fontSize: 11 }}>
            <span>5 s</span><span>15 s</span><span>30 s</span><span>1 min</span><span>5 min</span>
          </div>
        </Field>
        <p style={{ color: "#94a3b8", fontSize: 12, marginTop: 6 }}>
          ⚙️ A nova frequência entra em vigor automaticamente nos celulares dos colaboradores assim que o app estiver aberto/recarregado.
        </p>
      </Card>

      <Card title="Testar envio de e-mail" style={{ gridColumn: "1 / -1" }}>
        <p style={{ color: "#64748b", margin: "0 0 10px", fontSize: 14 }}>
          Envie um e-mail de teste agora para verificar se a integração está funcionando.
          ⚠️ Em conta Resend gratuita sem domínio próprio, o destinatário precisa ser o e-mail cadastrado na sua conta Resend.
        </p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <input
            data-testid="inp-test-email"
            style={{ ...inputStyle, maxWidth: 360 }}
            type="email"
            placeholder="seu@email.com"
            value={testEmailTo}
            onChange={(e) => setTestEmailTo(e.target.value)}
          />
          <Button onClick={sendTestEmail} disabled={testBusy || !testEmailTo} data-testid="send-test-email-btn">
            <Icon name="mail" /> {testBusy ? "Enviando..." : "Enviar e-mail de teste"}
          </Button>
          {testMsg && <span style={{ color: testMsg.startsWith("✅") ? "#166534" : "#be123c", fontWeight: 700 }}>{testMsg}</span>}
        </div>
      </Card>

      <Card title="Verificar domínio próprio no Resend (opcional)" style={{ gridColumn: "1 / -1" }}>
        <p style={{ color: "#64748b", margin: "0 0 8px", fontSize: 14 }}>
          Sem domínio verificado, o Resend só envia para o e-mail cadastrado na sua conta. Para enviar para qualquer colaborador,
          verifique um domínio próprio (gratuito).
        </p>
        <Button variant="soft" onClick={() => setShowResendHelp(!showResendHelp)} data-testid="toggle-resend-help">
          {showResendHelp ? "Ocultar passo a passo" : "Mostrar passo a passo"}
        </Button>
        {showResendHelp && (
          <div style={{ marginTop: 14, color: "#475569", lineHeight: 1.6, fontSize: 14 }}>
            <ol style={{ paddingLeft: 18 }}>
              <li>Entre em <a href="https://resend.com/domains" target="_blank" rel="noreferrer">resend.com/domains</a> → <strong>Add Domain</strong>.</li>
              <li>Digite seu domínio (ex.: <code>empresa.com.br</code>) e selecione a região mais próxima (us-east-1 funciona bem para o Brasil).</li>
              <li>O Resend mostrará 3 a 4 registros DNS que você precisa adicionar no seu provedor de domínio (Registro.br, Cloudflare, GoDaddy, etc):
                <ul>
                  <li><strong>MX</strong> — encaminha bounces (ex: <code>send</code> → <code>feedback-smtp.us-east-1.amazonses.com</code>, prioridade 10)</li>
                  <li><strong>TXT (SPF)</strong> — autoriza o Resend a enviar em nome do seu domínio (ex: <code>send</code> → <code>v=spf1 include:amazonses.com ~all</code>)</li>
                  <li><strong>TXT (DKIM)</strong> — assinatura criptográfica (ex: <code>resend._domainkey</code> → string longa começando com <code>p=...</code>)</li>
                  <li><strong>TXT (DMARC)</strong> opcional, recomendado (<code>_dmarc</code> → <code>v=DMARC1; p=none;</code>)</li>
                </ul>
              </li>
              <li>No painel DNS do seu provedor, adicione exatamente como o Resend mostrou — host/nome, tipo, valor.</li>
              <li>Volte ao Resend e clique em <strong>Verify DNS Records</strong>. Em geral leva de 5 minutos a 24 h para propagar.</li>
              <li>Quando ficar verde ✅, volte aqui e troque o <strong>E-mail remetente</strong> para algo como <code>naoresponda@empresa.com.br</code>.</li>
              <li>Pronto — agora pode enviar para qualquer colaborador.</li>
            </ol>
            <p style={{ background: "#f1f5f9", padding: 10, borderRadius: 12, fontSize: 13 }}>
              💡 Dica: se usar Cloudflare como DNS, desligue o "proxy" (nuvem laranja) nesses registros — só nuvem cinza/DNS only.
            </p>
          </div>
        )}
      </Card>

      <Card title="Orçamento de Horas Extras" style={{ gridColumn: "1 / -1" }}>
        <p style={{ color: "#64748b", margin: "0 0 10px", fontSize: 14 }}>
          Configure um orçamento mensal de HE em R$ e um percentual de alerta. O Painel exibirá um banner quando a
          projeção do mês ultrapassar o orçamento ou quando crescer acima do limite definido.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <Field label="Orçamento mensal de HE (R$) — 0 desativa">
            <input
              data-testid="inp-he-budget"
              type="number" step="0.01" min="0"
              style={inputStyle}
              value={form.he_monthly_budget_brl}
              onChange={(e) => setForm({ ...form, he_monthly_budget_brl: Number(e.target.value) })}
              placeholder="ex.: 5000"
            />
          </Field>
          <Field label="Limite de alerta sobre o realizado (%)">
            <input
              data-testid="inp-he-threshold"
              type="number" step="1" min="1" max="500"
              style={inputStyle}
              value={form.he_alert_threshold_pct}
              onChange={(e) => setForm({ ...form, he_alert_threshold_pct: Number(e.target.value) })}
              placeholder="ex.: 30"
            />
          </Field>
        </div>
        <p style={{ color: "#94a3b8", fontSize: 12, marginTop: 6 }}>
          🚨 Banner aparece quando: (a) projeção &gt; orçamento; (b) projeção &ge; 90% do orçamento; ou (c)
          projeção excede o realizado em mais de {form.he_alert_threshold_pct || 30}%.
        </p>
      </Card>

      <Card title="Ações" style={{ gridColumn: "1 / -1" }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <Button onClick={save} disabled={busy} data-testid="save-settings-btn">{busy ? "Salvando..." : "Salvar configurações"}</Button>
          <Button variant="secondary" onClick={runMonthly} disabled={busy} data-testid="run-monthly-btn"><Icon name="mail" /> Disparar rotina mensal agora</Button>
          {msg && <span style={{ color: msg.startsWith("Erro") ? "#be123c" : "#166534", fontWeight: 700 }}>{msg}</span>}
        </div>
      </Card>
    </div>
  );
}
