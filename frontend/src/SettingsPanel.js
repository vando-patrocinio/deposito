import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, Icon, inputStyle, StatusBadge } from "@/ui";
import AtlazIntegrationCard from "@/AtlazIntegrationCard";
import SmartoltIntegrationCard from "@/SmartoltIntegrationCard";
import MagnusBillingIntegrationCard from "@/MagnusBillingIntegrationCard";
import BrandingCard from "@/BrandingCard";
import MotorIaCard from "@/MotorIaCard";
import ConnectionsCard from "@/ConnectionsCard";
import PublicAccessPanel from "@/PublicAccessPanel";
import AiConfigCard from "@/AiConfigCard";

export default function SettingsPanel() {
  const [s, setS] = useState(null);
  const [form, setForm] = useState({
    resend_api_key: "", sender_email: "", sender_name: "SmartProv",
    openai_api_key: "", anthropic_api_key: "", gemini_api_key: "",
    monthly_email_enabled: true, location_ping_interval_sec: 15,
    he_monthly_budget_brl: 0, he_alert_threshold_pct: 30,
    sla_reparo_minutes: 60, sla_instalacao_minutes: 120, sla_retirada_minutes: 30,
    sla_prioridade_minutes: 45, sla_preventiva_minutes: 90, sla_venda_minutes: 60,
    sla_warning_pct: 80, sla_yellow_minutes: 15, sla_red_after_minutes: 0,
    sla_blink_when_overdue: true, nota_fence_radius_m: 80,
    lousa_grid_start_hour: 8, lousa_grid_end_hour: 18,
    lousa_grid_slot_minutes: 60, lousa_grid_max_per_slot: 2,
    time_sync_enabled: false, time_sync_max_drift_seconds: 60,
    time_sync_timezone: "America/Sao_Paulo",
  });
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
      sender_name: cur.sender_name || "SmartProv",
      openai_api_key: "",
      anthropic_api_key: "",
      gemini_api_key: "",
      monthly_email_enabled: cur.monthly_email_enabled,
      location_ping_interval_sec: cur.location_ping_interval_sec || 15,
      he_monthly_budget_brl: cur.he_monthly_budget_brl ?? 0,
      he_alert_threshold_pct: cur.he_alert_threshold_pct ?? 30,
      sla_reparo_minutes: cur.sla_reparo_minutes ?? 60,
      sla_instalacao_minutes: cur.sla_instalacao_minutes ?? 120,
      sla_retirada_minutes: cur.sla_retirada_minutes ?? 30,
      sla_prioridade_minutes: cur.sla_prioridade_minutes ?? 45,
      sla_preventiva_minutes: cur.sla_preventiva_minutes ?? 90,
      sla_venda_minutes: cur.sla_venda_minutes ?? 60,
      sla_warning_pct: cur.sla_warning_pct ?? 80,
      sla_yellow_minutes: cur.sla_yellow_minutes ?? 15,
      sla_red_after_minutes: cur.sla_red_after_minutes ?? 0,
      sla_blink_when_overdue: cur.sla_blink_when_overdue ?? true,
      nota_fence_radius_m: cur.nota_fence_radius_m ?? 80,
      lousa_grid_start_hour: cur.lousa_grid_start_hour ?? 8,
      lousa_grid_end_hour: cur.lousa_grid_end_hour ?? 18,
      lousa_grid_slot_minutes: cur.lousa_grid_slot_minutes ?? 60,
      lousa_grid_max_per_slot: cur.lousa_grid_max_per_slot ?? 2,
      time_sync_enabled: cur.time_sync_enabled ?? false,
      time_sync_max_drift_seconds: cur.time_sync_max_drift_seconds ?? 60,
      time_sync_timezone: cur.time_sync_timezone ?? "America/Sao_Paulo",
      openrouter_enabled: cur.openrouter_enabled ?? false,
      openrouter_api_key: "",
      openrouter_model: cur.openrouter_model ?? "deepseek/deepseek-v4-flash",
      online_threshold_minutes: cur.online_threshold_minutes ?? 5,
    });
  }
  useEffect(() => { reload(); }, []);

  async function save() {
    setBusy(true); setMsg("");
    const payload = { ...form };
    if (!payload.resend_api_key) delete payload.resend_api_key;
    if (!payload.openai_api_key) delete payload.openai_api_key;
    if (!payload.anthropic_api_key) delete payload.anthropic_api_key;
    if (!payload.gemini_api_key) delete payload.gemini_api_key;
    if (!payload.openrouter_api_key) delete payload.openrouter_api_key;
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
      const res = await api.testEmail(testEmailTo, "Teste de envio — SmartProv");
      setTestMsg(`✅ Enviado para ${res.to} (id: ${res.id})`);
    } catch (e) {
      setTestMsg("❌ " + (e?.response?.data?.detail || e.message));
    }
    setTestBusy(false);
  }

  if (!s) return <Card title="Configurações">Carregando...</Card>;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
      {/* Card de SLA / Tempos de Referência */}
      <Card title="Tempos de Referência por Serviço (SLA)">
        <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 12px" }}>
          Defina o tempo esperado de execução para cada tipo de serviço. Bolhas que ultrapassarem
          esse tempo ficam piscando vermelho na lousa para o gestor.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
          <Field label="Reparo (min)">
            <input data-testid="inp-sla-reparo" type="number" min="1" style={inputStyle}
              value={form.sla_reparo_minutes}
              onChange={(e) => setForm({ ...form, sla_reparo_minutes: Number(e.target.value) })} />
          </Field>
          <Field label="Instalação (min)">
            <input data-testid="inp-sla-instalacao" type="number" min="1" style={inputStyle}
              value={form.sla_instalacao_minutes}
              onChange={(e) => setForm({ ...form, sla_instalacao_minutes: Number(e.target.value) })} />
          </Field>
          <Field label="Retirada (min)">
            <input data-testid="inp-sla-retirada" type="number" min="1" style={inputStyle}
              value={form.sla_retirada_minutes}
              onChange={(e) => setForm({ ...form, sla_retirada_minutes: Number(e.target.value) })} />
          </Field>
          <Field label="Prioridade (min)">
            <input data-testid="inp-sla-prioridade" type="number" min="1" style={inputStyle}
              value={form.sla_prioridade_minutes}
              onChange={(e) => setForm({ ...form, sla_prioridade_minutes: Number(e.target.value) })} />
          </Field>
          <Field label="Preventiva (min)">
            <input data-testid="inp-sla-preventiva" type="number" min="1" style={inputStyle}
              value={form.sla_preventiva_minutes}
              onChange={(e) => setForm({ ...form, sla_preventiva_minutes: Number(e.target.value) })} />
          </Field>
          <Field label="Venda (min)">
            <input data-testid="inp-sla-venda" type="number" min="1" style={inputStyle}
              value={form.sla_venda_minutes}
              onChange={(e) => setForm({ ...form, sla_venda_minutes: Number(e.target.value) })} />
          </Field>
        </div>
        <div style={{
          marginTop: 12, padding: 12, background: "#f8fafc",
          border: "1px solid #e2e8f0", borderRadius: 12,
        }}>
          <strong style={{ fontSize: 13, color: "#0f172a" }}>🚦 Quando alertar</strong>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 8 }}>
            <div>
              <label style={{ fontSize: 11, color: "#78350f", fontWeight: 700 }}>
                🟡 Pisca AMARELO faltando (min)
              </label>
              <input
                data-testid="inp-sla-yellow"
                type="number" min="0" step="1"
                style={{ ...inputStyle, borderColor: "#f59e0b" }}
                value={form.sla_yellow_minutes}
                onChange={(e) => setForm({ ...form, sla_yellow_minutes: Number(e.target.value) })}
              />
              <small style={{ color: "#64748b", fontSize: 10 }}>
                Bolha pisca amarelo quando faltam até {form.sla_yellow_minutes} min p/ estourar
              </small>
            </div>
            <div>
              <label style={{ fontSize: 11, color: "#7f1d1d", fontWeight: 700 }}>
                🔴 Pisca VERMELHO após (min)
              </label>
              <input
                data-testid="inp-sla-red"
                type="number" min="0" step="1"
                style={{ ...inputStyle, borderColor: "#dc2626" }}
                value={form.sla_red_after_minutes}
                onChange={(e) => setForm({ ...form, sla_red_after_minutes: Number(e.target.value) })}
              />
              <small style={{ color: "#64748b", fontSize: 10 }}>
                Bolha pisca vermelho {form.sla_red_after_minutes === 0 ? "imediatamente" : `${form.sla_red_after_minutes} min`} após estourar
              </small>
            </div>
          </div>
        </div>
        <label style={{ display: "flex", gap: 8, alignItems: "center", color: "#475569", fontSize: 14, marginTop: 10, cursor: "pointer" }}>
          <input data-testid="chk-blink-overdue" type="checkbox"
            checked={!!form.sla_blink_when_overdue}
            onChange={(e) => setForm({ ...form, sla_blink_when_overdue: e.target.checked })}
            style={{ transform: "scale(1.3)" }} />
          <span><strong>Piscar bolhas vermelhas</strong> quando ultrapassarem o tempo</span>
        </label>
        <Field label={`Raio da cerca virtual em "Praça=Nota": ${form.nota_fence_radius_m}m`}>
          <input data-testid="inp-nota-radius" type="range" min="20" max="500" step="10"
            value={form.nota_fence_radius_m}
            onChange={(e) => setForm({ ...form, nota_fence_radius_m: Number(e.target.value) })}
            style={{ width: "100%" }} />
        </Field>
      </Card>

      <Card title="Grade de Horários da Lousa">
        <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 12px" }}>
          Defina a faixa de horários e a duração de cada slot. A lousa exibirá esses horários
          fixos em cada técnico, e bolhas podem ser arrastadas para qualquer slot.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Hora de início (0-23)">
            <input data-testid="inp-grid-start" type="number" min="0" max="23"
              style={inputStyle}
              value={form.lousa_grid_start_hour}
              onChange={(e) => setForm({ ...form, lousa_grid_start_hour: Number(e.target.value) })} />
          </Field>
          <Field label="Hora de fim (1-24)">
            <input data-testid="inp-grid-end" type="number" min="1" max="24"
              style={inputStyle}
              value={form.lousa_grid_end_hour}
              onChange={(e) => setForm({ ...form, lousa_grid_end_hour: Number(e.target.value) })} />
          </Field>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 8 }}>
          <Field label="Duração do slot (min)">
            <select data-testid="inp-grid-slot" style={inputStyle}
              value={form.lousa_grid_slot_minutes}
              onChange={(e) => setForm({ ...form, lousa_grid_slot_minutes: Number(e.target.value) })}>
              <option value={15}>15 min</option>
              <option value={30}>30 min</option>
              <option value={60}>1 hora</option>
              <option value={120}>2 horas</option>
            </select>
          </Field>
          <Field label="Máx. bolhas por slot">
            <input data-testid="inp-grid-max" type="number" min="1" max="10"
              style={inputStyle}
              value={form.lousa_grid_max_per_slot}
              onChange={(e) => setForm({ ...form, lousa_grid_max_per_slot: Number(e.target.value) })} />
          </Field>
        </div>
        <div style={{
          marginTop: 10, padding: 10, background: "#f0fdf4",
          border: "1px solid #86efac", borderRadius: 10, fontSize: 12, color: "#15803d",
        }}>
          📊 <strong>Prévia:</strong> {Math.max(1, ((form.lousa_grid_end_hour - form.lousa_grid_start_hour) * 60) / form.lousa_grid_slot_minutes)} slots de {form.lousa_grid_slot_minutes}min entre {String(form.lousa_grid_start_hour).padStart(2, "0")}:00 e {String(form.lousa_grid_end_hour).padStart(2, "0")}:00 — {form.lousa_grid_max_per_slot} bolha(s)/slot
        </div>
      </Card>

      <Card title="Sincronização de Horário (Servidor Brasil)">
        <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 12px" }}>
          Quando ativado, o sistema valida o relógio do dispositivo contra o horário do servidor.
          Se a diferença for maior que o limite configurado, o dispositivo NÃO consegue
          registrar ponto nem operar a lousa — garantindo que todos os horários sigam o mesmo padrão.
        </p>
        <label style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer", padding: 10, background: form.time_sync_enabled ? "#f0fdfa" : "#f8fafc", border: `2px solid ${form.time_sync_enabled ? "#0d9488" : "#e2e8f0"}`, borderRadius: 12, marginBottom: 10 }}>
          <input
            data-testid="chk-time-sync"
            type="checkbox"
            checked={!!form.time_sync_enabled}
            onChange={(e) => setForm({ ...form, time_sync_enabled: e.target.checked })}
            style={{ marginTop: 3, transform: "scale(1.3)" }}
          />
          <div>
            <strong style={{ color: form.time_sync_enabled ? "#0d9488" : "#0f172a" }}>
              Ativar sincronização obrigatória
            </strong>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
              Bloqueia ações se o relógio do dispositivo estiver fora do limite.
            </div>
          </div>
        </label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Diferença máxima (segundos)">
            <input
              data-testid="inp-time-drift"
              type="number" min="5" max="3600" step="5"
              style={inputStyle}
              value={form.time_sync_max_drift_seconds}
              onChange={(e) => setForm({ ...form, time_sync_max_drift_seconds: Number(e.target.value) })}
            />
          </Field>
          <Field label="Fuso horário do Brasil">
            <select
              data-testid="inp-time-tz"
              style={inputStyle}
              value={form.time_sync_timezone}
              onChange={(e) => setForm({ ...form, time_sync_timezone: e.target.value })}
            >
              <option value="America/Sao_Paulo">São Paulo (UTC-3) — padrão</option>
              <option value="America/Manaus">Manaus (UTC-4)</option>
              <option value="America/Belem">Belém (UTC-3)</option>
              <option value="America/Rio_Branco">Rio Branco (UTC-5)</option>
              <option value="America/Fortaleza">Fortaleza (UTC-3)</option>
              <option value="America/Recife">Recife (UTC-3)</option>
              <option value="America/Cuiaba">Cuiabá (UTC-4)</option>
              <option value="America/Noronha">Fernando de Noronha (UTC-2)</option>
            </select>
          </Field>
        </div>
        <div style={{
          marginTop: 10, padding: 10, background: "#fef3c7",
          border: "1px solid #fde68a", borderRadius: 10, fontSize: 12, color: "#92400e",
        }}>
          ⚠️ <strong>Atenção:</strong> ao ativar, dispositivos com relógio desajustado serão bloqueados.
          Recomende aos colaboradores ativarem "Hora automática" no Android/iOS antes.
        </div>
      </Card>

      <AiConfigCard />

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

      <Card title="OpenRouter (LLM)" data-testid="card-openrouter">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8, gap: 8 }}>
          <p style={{ color: "#64748b", fontSize: 13, margin: 0, flex: 1 }}>
            Pode ser usado como prioridade principal ou fallback. Se estiver sem chave, é ignorado e cai no Emergent LLM.
          </p>
          <span style={{
            background: form.openrouter_enabled ? "linear-gradient(135deg,#10b981,#059669)" : "#94a3b8",
            color: "white", fontSize: 10, fontWeight: 800, padding: "3px 8px", borderRadius: 999, letterSpacing: 0.4,
          }}>
            {s?.openrouter_api_key_set ? "PADRÃO" : "INATIVO"}
          </span>
        </div>

        <Field label="Ativar no roteamento">
          <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
            <input
              data-testid="openrouter-enabled"
              type="checkbox"
              checked={!!form.openrouter_enabled}
              onChange={(e) => setForm({ ...form, openrouter_enabled: e.target.checked })}
              style={{ width: 18, height: 18 }}
            />
            <span style={{ fontSize: 13, color: "#475569" }}>
              {form.openrouter_enabled ? "Ativo — chamadas LLM usam OpenRouter" : "Inativo — chamadas LLM usam Emergent"}
            </span>
          </label>
        </Field>

        <Field label="OpenRouter API Key">
          <div style={{ position: "relative" }}>
            <input
              data-testid="inp-openrouter-key"
              type="password"
              placeholder={s?.openrouter_api_key_set ? `Salva: ${s.openrouter_api_key}` : "sk-or-v1-..."}
              value={form.openrouter_api_key || ""}
              onChange={(e) => setForm({ ...form, openrouter_api_key: e.target.value })}
              style={{ ...inputStyle, paddingRight: 36 }}
            />
          </div>
          <small style={{ color: "#94a3b8", fontSize: 11 }}>
            Chave de API necessária para acessar os modelos OpenRouter.
            {" "}
            <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer" style={{ color: "#3b82f6" }}>Obter chave</a>
          </small>
        </Field>

        <Field label="Modelo de IA">
          <input
            data-testid="inp-openrouter-model"
            type="text"
            placeholder="deepseek/deepseek-v4-flash"
            value={form.openrouter_model || ""}
            onChange={(e) => setForm({ ...form, openrouter_model: e.target.value })}
            style={inputStyle}
          />
          <small style={{ color: "#94a3b8", fontSize: 11 }}>
            Informe sempre o nome exato do modelo da OpenRouter. Não há lista pré-definida.
            {" "}
            <a href="https://openrouter.ai/models" target="_blank" rel="noreferrer" style={{ color: "#3b82f6" }}>Ver catálogo</a>
          </small>
        </Field>
      </Card>

      <Card title="Ações" style={{ gridColumn: "1 / -1" }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <Button onClick={save} disabled={busy} data-testid="save-settings-btn">{busy ? "Salvando..." : "Salvar configurações"}</Button>
          <Button variant="secondary" onClick={runMonthly} disabled={busy} data-testid="run-monthly-btn"><Icon name="mail" /> Disparar rotina mensal agora</Button>
          {msg && <span style={{ color: msg.startsWith("Erro") ? "#be123c" : "#166534", fontWeight: 700 }}>{msg}</span>}
        </div>
      </Card>

      <BrandingCard />
      <MotorIaCard />
      <PublicAccessPanel />
      <ConnectionsCard />
      <AtlazIntegrationCard />
      <SmartoltIntegrationCard />
      <MagnusBillingIntegrationCard />
    </div>
  );
}
