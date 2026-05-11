import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import { Cpu, CheckCircle2, AlertCircle, ExternalLink, Loader2 } from "lucide-react";

/**
 * Motor IA — configuração centralizada de TODAS as chamadas de IA.
 * Usa OpenRouter.ai como gateway primário (400+ modelos com fallback nativo).
 * Áudio (Whisper STT / TTS) usa OpenAI direto pois OpenRouter não suporta.
 */
export default function MotorIaCard() {
  const [cfg, setCfg] = useState(null);
  const [suggested, setSuggested] = useState(null);
  const [orKey, setOrKey] = useState("");
  const [audioKey, setAudioKey] = useState("");
  const [model, setModel] = useState("");
  const [fallbacks, setFallbacks] = useState("");
  const [atendModel, setAtendModel] = useState("");
  const [atendFallbacks, setAtendFallbacks] = useState("");
  const [tts, setTts] = useState("nova");
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [msg, setMsg] = useState("");

  const reload = async () => {
    try {
      const c = await api.motorIaGetConfig();
      setCfg(c);
      setModel(c.default_text_model || "openai/gpt-4o-mini");
      setFallbacks((c.fallback_models || []).join("\n"));
      setAtendModel(c.atendimento_model || "deepseek/deepseek-chat");
      setAtendFallbacks((c.atendimento_fallbacks || []).join("\n"));
      setTts(c.tts_voice || "nova");
      setEnabled(!!c.enabled);
      setOrKey(""); setAudioKey("");
    } catch (e) {
      setMsg("Erro ao carregar config: " + e.message);
    }
    try {
      const s = await api.motorIaSuggestedModels();
      setSuggested(s);
    } catch (e) { /* ignore */ }
  };

  useEffect(() => { reload(); }, []);

  const save = async () => {
    setBusy(true); setMsg("");
    try {
      const payload = {
        default_text_model: model,
        fallback_models: fallbacks.split(/\r?\n/).map((s) => s.trim()).filter(Boolean),
        atendimento_model: atendModel,
        atendimento_fallbacks: atendFallbacks.split(/\r?\n/).map((s) => s.trim()).filter(Boolean),
        tts_voice: tts,
        enabled,
      };
      if (orKey.trim()) payload.openrouter_api_key = orKey.trim();
      if (audioKey.trim()) payload.openai_audio_key = audioKey.trim();
      await api.motorIaSaveConfig(payload);
      setMsg("Configuração salva.");
      await reload();
    } catch (e) {
      setMsg("Erro ao salvar: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const runTest = async () => {
    setBusy(true); setTestResult(null);
    try {
      const r = await api.motorIaTest();
      setTestResult(r);
    } catch (e) {
      setTestResult({ ok: false, error: e.message });
    } finally { setBusy(false); }
  };

  const applySuggested = (modelsArr) => {
    if (!modelsArr || !modelsArr.length) return;
    setModel(modelsArr[0]);
    setFallbacks(modelsArr.slice(1).join("\n"));
  };

  return (
    <Card style={{ padding: 22 }} data-testid="motor-ia-card">
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12, marginBottom: 14, flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 38, height: 38, borderRadius: 8,
            background: "var(--bg-surface-2)",
            border: "1px solid var(--border-default)",
            display: "grid", placeItems: "center",
            color: "var(--text-primary)",
          }}>
            <Cpu size={18} strokeWidth={1.75} />
          </div>
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0,
                            color: "var(--text-primary)",
                            letterSpacing: "-0.012em" }}>
              Motor IA
            </h3>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
              Gateway central para todas as chamadas de IA da aplicação.
            </div>
          </div>
        </div>
        <div style={{
          padding: "4px 10px", borderRadius: 999, fontSize: 10, fontWeight: 700,
          background: cfg?.enabled && cfg?.has_openrouter_key
            ? "rgba(34,197,94,.15)" : "rgba(245,158,11,.15)",
          color: cfg?.enabled && cfg?.has_openrouter_key ? "#16a34a" : "#d97706",
          textTransform: "uppercase", letterSpacing: 0.5,
        }} data-testid="motor-ia-status-badge">
          {cfg?.enabled && cfg?.has_openrouter_key ? "Ativo" : "Não configurado"}
        </div>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
        gap: 10, marginBottom: 18,
      }} data-testid="motor-ia-status-panel">
        <StatusBox
          label="Texto geral"
          active={!!(cfg?.enabled && cfg?.has_openrouter_key)}
          detail={cfg?.default_text_model || "—"}
          subtitle="Avaliações, coaching, insights"
          testId="status-text-general"
        />
        <StatusBox
          label="Agentes de atendimento"
          active={!!(cfg?.enabled && cfg?.has_openrouter_key)}
          detail={cfg?.atendimento_model || "—"}
          subtitle="WhatsApp · Jerusa · Playground"
          accent="#0d9488"
          testId="status-atendimento"
        />
        <StatusBox
          label="Voz — Transcrição (STT)"
          active={!!cfg?.has_audio_key}
          detail={cfg?.has_audio_key ? "Whisper-1 (OpenAI)" : "Não configurado"}
          subtitle="Cliente fala → texto"
          testId="status-stt"
        />
        <StatusBox
          label="Voz — Síntese (TTS)"
          active={!!cfg?.has_audio_key}
          detail={cfg?.has_audio_key
            ? `tts-1 · voz "${cfg?.tts_voice || "nova"}"`
            : "Não configurado"}
          subtitle="IA responde falando"
          testId="status-tts"
        />
      </div>

      <div style={{
        padding: 12, borderRadius: 8, fontSize: 12,
        background: "rgba(59,130,246,.06)",
        border: "1px solid rgba(59,130,246,.20)",
        color: "var(--text-secondary)", lineHeight: 1.5, marginBottom: 18,
      }}>
        <strong style={{ color: "var(--text-primary)" }}>OpenRouter.ai</strong> é o
        gateway escolhido — agrega 400+ modelos (OpenAI, Anthropic, Google, Meta,
        Mistral, etc) com fallback automático nativo. Um único motor é suficiente
        — o fallback entre provedores já está dentro do OpenRouter.
        {" "}<a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer"
                  style={{ color: "var(--accent)", textDecoration: "underline",
                            display: "inline-flex", alignItems: "center", gap: 3 }}>
          Obter API key <ExternalLink size={11} />
        </a>
      </div>

      {/* OpenRouter key */}
      <Section title="Chave OpenRouter (texto)">
        <Row label="API Key">
          <input value={orKey} onChange={(e) => setOrKey(e.target.value)}
                  type="password"
                  placeholder={cfg?.has_openrouter_key
                    ? `Atual: ${cfg.openrouter_api_key} — deixe em branco para manter`
                    : "sk-or-v1-..."}
                  data-testid="motor-ia-or-key"
                  style={inputStyle} />
        </Row>
        <Row label="Modelo padrão">
          <input value={model} onChange={(e) => setModel(e.target.value)}
                  placeholder="openai/gpt-4o-mini"
                  data-testid="motor-ia-default-model"
                  style={{ ...inputStyle, fontFamily: "ui-monospace, monospace" }} />
        </Row>
        <Row label="Fallbacks (um por linha)">
          <textarea value={fallbacks} onChange={(e) => setFallbacks(e.target.value)}
                    rows={4}
                    placeholder={"anthropic/claude-3.5-sonnet\ngoogle/gemini-2.0-flash-exp:free"}
                    data-testid="motor-ia-fallbacks"
                    style={{ ...inputStyle, fontFamily: "ui-monospace, monospace",
                              resize: "vertical" }} />
        </Row>

        {suggested?.tiers && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
                            textTransform: "uppercase", letterSpacing: 0.5,
                            marginBottom: 6 }}>
              Aplicar perfil sugerido
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {suggested.tiers.map((t) => (
                <button key={t.id} onClick={() => applySuggested(t.models)}
                        data-testid={`motor-ia-tier-${t.id}`}
                        style={{
                          padding: "5px 10px", borderRadius: 6,
                          border: "1px solid var(--border-default)",
                          background: "var(--bg-surface-2)",
                          color: "var(--text-primary)",
                          fontSize: 11, fontWeight: 600, cursor: "pointer",
                        }}>
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* Motor de Atendimento — DeepSeek dedicado, regra de negócio fixa */}
      <div data-testid="motor-ia-atendimento-section" style={{
        padding: 14, borderRadius: 8,
        background: "rgba(13,148,136,.06)",
        border: "1px solid rgba(13,148,136,.30)",
        marginBottom: 16,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8,
                         marginBottom: 6 }}>
          <Cpu size={14} strokeWidth={2} style={{ color: "#0d9488" }} />
          <strong style={{ fontSize: 12, color: "#0d9488",
                              textTransform: "uppercase", letterSpacing: 0.5 }}>
            Motor para Agentes de Atendimento
          </strong>
          <span style={{
            marginLeft: "auto", fontSize: 9, fontWeight: 700,
            padding: "2px 8px", borderRadius: 4,
            background: "rgba(13,148,136,.18)", color: "#0d9488",
            textTransform: "uppercase", letterSpacing: 0.5,
          }}>Política fixa</span>
        </div>
        <p style={{ fontSize: 11, color: "var(--text-secondary)",
                      margin: "0 0 12px", lineHeight: 1.5 }}>
          Todos os Agentes de Atendimento (Isabella WhatsApp, Jerusa Voz, Playground)
          usam <strong>DeepSeek</strong> como motor. Custo ~10× menor que GPT-4o e
          excelente em PT-BR. Não é permitido trocar por outro provedor — apenas o
          modelo específico DeepSeek pode ser ajustado.
        </p>
        <Row label="Modelo DeepSeek">
          <input list="deepseek-models"
                  value={atendModel}
                  onChange={(e) => setAtendModel(e.target.value)}
                  data-testid="motor-ia-atend-model"
                  placeholder="deepseek/deepseek-v4-flash"
                  style={{ ...inputStyle, fontFamily: "ui-monospace, monospace" }} />
          <datalist id="deepseek-models">
            <option value="deepseek/deepseek-chat">DeepSeek Chat (rápido, custo baixo)</option>
            <option value="deepseek/deepseek-v4-flash">DeepSeek V4 Flash (recomendado)</option>
            <option value="deepseek/deepseek-r1">DeepSeek R1 (raciocínio profundo)</option>
            <option value="deepseek/deepseek-chat-v3.1">DeepSeek Chat v3.1</option>
            <option value="deepseek/deepseek-r1-distill-llama-70b">R1 Distill Llama 70B</option>
            <option value="deepseek/deepseek-r1:free">DeepSeek R1 (Free tier)</option>
          </datalist>
          <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
            Digite ou escolha qualquer modelo com prefixo <code>deepseek/</code>.
            Veja a lista completa em{" "}
            <a href="https://openrouter.ai/deepseek" target="_blank" rel="noreferrer"
                style={{ color: "var(--accent)", textDecoration: "underline" }}>
              openrouter.ai/deepseek
            </a>
          </div>
        </Row>
        <Row label="Fallbacks DeepSeek">
          <textarea value={atendFallbacks}
                      onChange={(e) => setAtendFallbacks(e.target.value)}
                      rows={2}
                      data-testid="motor-ia-atend-fallbacks"
                      placeholder={"deepseek/deepseek-r1\ndeepseek/deepseek-chat-v3.1"}
                      style={{ ...inputStyle, fontFamily: "ui-monospace, monospace",
                                resize: "vertical" }} />
        </Row>
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
          ⓘ Os fallbacks só aceitam modelos do prefixo <code>deepseek/</code> — qualquer
          outro valor é ignorado pelo backend.
        </div>
      </div>

      {/* Audio */}
      <Section title="Chave OpenAI (áudio: Whisper + TTS) — opcional">
        <div style={{
          padding: 10, borderRadius: 6, fontSize: 11,
          background: "rgba(245,158,11,.08)",
          border: "1px solid rgba(245,158,11,.25)",
          color: "var(--text-secondary)", lineHeight: 1.5, marginBottom: 10,
        }}>
          <strong style={{ color: "var(--text-primary)" }}>Só preencha isso se você
          usa o recurso de voz (Jerusa).</strong> Para WhatsApp / Lousa / Central
          IA, deixe vazio. OpenRouter não suporta áudio — por isso aqui é a chave
          da OpenAI direta.
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)",
                        marginBottom: 8, lineHeight: 1.5 }}>
          <strong>Onde pegar:</strong>{" "}
          <a href="https://platform.openai.com/api-keys" target="_blank"
              rel="noreferrer" style={{ color: "var(--accent)",
              textDecoration: "underline" }}>
            platform.openai.com/api-keys
          </a>
          {" "}→ <em>"+ Create new secret key"</em> → cola aqui.
          <br />
          <strong>Custo aproximado:</strong> ~$0.05 por chamada de 3 minutos
          (Whisper $0.006/min + TTS $15/M chars). Adicione crédito em{" "}
          <a href="https://platform.openai.com/settings/billing" target="_blank"
              rel="noreferrer" style={{ color: "var(--accent)",
              textDecoration: "underline" }}>
            platform.openai.com/billing
          </a>.
        </div>
        <Row label="API Key (sk-...)">
          <input value={audioKey} onChange={(e) => setAudioKey(e.target.value)}
                  type="password"
                  placeholder={cfg?.has_audio_key
                    ? `Atual: ${cfg.openai_audio_key} — deixe em branco para manter`
                    : "sk-proj-... (deixe vazio se não usa voz)"}
                  data-testid="motor-ia-audio-key"
                  style={inputStyle} />
        </Row>
        <Row label="Voz TTS">
          <select value={tts} onChange={(e) => setTts(e.target.value)}
                    data-testid="motor-ia-tts-voice" style={inputStyle}>
            <option value="nova">nova (feminina, jovem, recomendada)</option>
            <option value="shimmer">shimmer (feminina, calma)</option>
            <option value="alloy">alloy (neutra)</option>
            <option value="echo">echo (masculina, séria)</option>
            <option value="fable">fable (masculina, narrativa)</option>
            <option value="onyx">onyx (masculina, grave)</option>
          </select>
        </Row>
      </Section>

      <div style={{ display: "flex", alignItems: "center", gap: 12,
                       padding: "12px 14px", borderRadius: 8,
                       background: "var(--bg-surface-2)", marginTop: 8 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 8,
                          cursor: "pointer", fontSize: 13 }}>
          <input type="checkbox" checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  data-testid="motor-ia-enabled" />
          <strong>Motor habilitado</strong>
          <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
            (desligue para voltar ao motor legado temporariamente)
          </span>
        </label>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
        <button onClick={save} disabled={busy}
                data-testid="motor-ia-save"
                style={primaryBtn(busy)}>
          {busy ? <Loader2 size={13} className="animate-spin" /> : null}
          Salvar configuração
        </button>
        <button onClick={runTest} disabled={busy || !cfg?.has_openrouter_key}
                data-testid="motor-ia-test"
                title={!cfg?.has_openrouter_key
                  ? "Salve uma chave OpenRouter antes" : "Faz uma chamada de teste real"}
                style={secondaryBtn(busy || !cfg?.has_openrouter_key)}>
          Testar conexão
        </button>
        {msg && <span style={{ alignSelf: "center", fontSize: 12,
                                  color: msg.startsWith("Erro") ? "#dc2626" : "#16a34a" }}>
          {msg}
        </span>}
      </div>

      {testResult && (
        <div data-testid="motor-ia-test-result" style={{
          marginTop: 12, padding: 12, borderRadius: 8,
          background: testResult.ok ? "rgba(34,197,94,.08)" : "rgba(220,38,38,.08)",
          border: `1px solid ${testResult.ok ? "rgba(34,197,94,.30)" : "rgba(220,38,38,.30)"}`,
          fontSize: 12, display: "flex", gap: 8, alignItems: "flex-start",
        }}>
          {testResult.ok
            ? <CheckCircle2 size={14} style={{ color: "#16a34a", marginTop: 1 }} />
            : <AlertCircle size={14} style={{ color: "#dc2626", marginTop: 1 }} />}
          <div style={{ flex: 1 }}>
            {testResult.ok ? (
              <>
                <strong style={{ color: "#16a34a" }}>Conexão OK</strong>
                <div style={{ marginTop: 4, color: "var(--text-secondary)" }}>
                  Modelo retornado: <code>{testResult.model}</code> · Provider:{" "}
                  <code>{testResult.provider}</code>
                </div>
                <div style={{ marginTop: 4, fontFamily: "ui-monospace, monospace",
                                color: "var(--text-muted)" }}>
                  Resposta: "{testResult.sample}"
                </div>
              </>
            ) : (
              <>
                <strong style={{ color: "#dc2626" }}>Falha</strong>
                <div style={{ marginTop: 4, fontFamily: "ui-monospace, monospace",
                                color: "var(--text-muted)" }}>
                  {testResult.error}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

const inputStyle = {
  width: "100%", padding: "8px 10px", borderRadius: 6,
  border: "1px solid var(--border-default)",
  background: "var(--bg-surface)",
  fontSize: 13, color: "var(--text-primary)",
  outline: "none",
};

function StatusBox({ label, active, detail, subtitle, accent, testId }) {
  const color = active ? (accent || "#16a34a") : "#dc2626";
  return (
    <div data-testid={testId} style={{
      padding: "10px 12px", borderRadius: 8,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface-2)",
      borderLeft: `3px solid ${color}`,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 10, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 700,
      }}>
        <span style={{
          width: 7, height: 7, borderRadius: "50%",
          background: color,
          boxShadow: active ? `0 0 0 2px ${color}33` : "none",
        }} />
        <span>{label}</span>
      </div>
      <div style={{
        fontSize: 12, fontWeight: 600, color: "var(--text-primary)",
        marginTop: 5, fontFamily: "ui-monospace, monospace",
        wordBreak: "break-all", lineHeight: 1.3,
      }}>
        {detail}
      </div>
      {subtitle && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 3 }}>
          {subtitle}
        </div>
      )}
      <div style={{
        marginTop: 6,
        fontSize: 10, fontWeight: 700, color: color,
        display: "inline-flex", alignItems: "center", gap: 4,
      }}>
        {active ? (
          <><CheckCircle2 size={11} /> Ativo</>
        ) : (
          <><AlertCircle size={11} /> Inativo</>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 8,
        paddingBottom: 6, borderBottom: "1px solid var(--border-default)",
      }}>{title}</div>
      <div style={{ display: "grid", gap: 8 }}>{children}</div>
    </div>
  );
}

function Row({ label, children }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "160px 1fr",
                     gap: 12, alignItems: "center" }}>
      <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{label}</span>
      <div>{children}</div>
    </div>
  );
}

function primaryBtn(disabled) {
  return {
    padding: "8px 14px", borderRadius: 6,
    border: "1px solid var(--text-primary)",
    background: "var(--text-primary)",
    color: "var(--bg-surface)",
    fontSize: 12, fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
    display: "inline-flex", alignItems: "center", gap: 6,
  };
}

function secondaryBtn(disabled) {
  return {
    padding: "8px 14px", borderRadius: 6,
    border: "1px solid var(--border-default)",
    background: "transparent",
    color: "var(--text-primary)",
    fontSize: 12, fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
  };
}
