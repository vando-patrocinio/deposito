/**
 * SecretariaIaSection — UI da Secretária IA "Ligo".
 *
 * Sub-aba dentro da Central de IA com:
 *   - Chat de teste (perguntas → respostas em pt-BR)
 *   - Wizard de setup do GPT customizado (webhook URL + bearer token + spec OpenAPI)
 *   - Histórico de perguntas
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { Button, Card } from "@/ui";
import {
  Send, Copy, RefreshCw, Eye, EyeOff, CheckCircle2, ExternalLink,
  Bot, User as UserIcon, History as HistoryIcon, Sparkles,
} from "lucide-react";

const SUGGESTIONS = [
  "oi minha Ligo, quantos clientes ativos eu tenho?",
  "quantas instalações foram feitas esse mês?",
  "como está a rede óptica? tem ONU em LOS?",
  "quais são os 5 melhores técnicos do mês?",
  "como está o churn?",
  "qual o custo do Motor IA hoje?",
];

export default function SecretariaIaSection() {
  const [tab, setTab] = useState("chat");
  return (
    <div data-testid="secretaria-section">
      <div style={{ display: "flex", gap: 4, padding: 4, background: "#e2e8f0", borderRadius: 10, marginBottom: 14, maxWidth: 480 }}>
        {[
          { id: "chat", label: "Chat", icon: Bot },
          { id: "gpt", label: "GPT customizado", icon: Sparkles },
          { id: "history", label: "Histórico", icon: HistoryIcon },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            data-testid={`sec-tab-${id}`}
            onClick={() => setTab(id)}
            style={{
              flex: 1, padding: "8px 12px", border: "none", borderRadius: 8,
              background: tab === id ? "white" : "transparent",
              color: tab === id ? "#0f172a" : "#475569",
              fontWeight: 700, fontSize: 13, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
              boxShadow: tab === id ? "0 1px 3px rgba(0,0,0,.08)" : "none",
            }}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>
      {tab === "chat" && <ChatTab />}
      {tab === "gpt" && <GptSetupTab />}
      {tab === "history" && <HistoryTab />}
    </div>
  );
}

/* ===========================
   Chat tab
   =========================== */
function ChatTab() {
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Oi, sou a Ligo, sua secretária. Me pergunta qualquer coisa sobre clientes, técnicos, rede, churn..." },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, busy]);

  const send = useCallback(async (text) => {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: q }]);
    setBusy(true);
    try {
      const r = await api.secretariaAsk(q);
      setMessages((m) => [...m, {
        role: "assistant",
        content: r.answer || "(sem resposta)",
        tools: r.tools_used || [],
      }]);
    } catch (e) {
      setMessages((m) => [...m, {
        role: "assistant",
        content: `Erro: ${e?.response?.data?.detail || e.message}`,
        error: true,
      }]);
    } finally {
      setBusy(false);
    }
  }, [input, busy]);

  return (
    <Card>
      <div style={{ height: 460, overflowY: "auto", padding: "8px 4px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
        {messages.map((m, i) => <MessageBubble key={i} msg={m} />)}
        {busy && (
          <div data-testid="sec-typing" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", color: "#64748b", fontSize: 13 }}>
            <Bot size={14} />
            <span style={{ display: "inline-flex", gap: 3 }}>
              <Dot delay={0} /><Dot delay={120} /><Dot delay={240} />
            </span>
            <span style={{ fontSize: 11 }}>Ligo está pensando…</span>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        {SUGGESTIONS.map((s, i) => (
          <button key={i} onClick={() => send(s)} disabled={busy}
                  data-testid={`sec-suggestion-${i}`}
                  style={{
                    background: "#f1f5f9", border: "1px solid #e2e8f0",
                    borderRadius: 999, padding: "4px 10px", fontSize: 11,
                    cursor: busy ? "not-allowed" : "pointer", color: "#475569",
                  }}>
            {s}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <input
          data-testid="sec-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="Pergunta para a Ligo..."
          disabled={busy}
          style={{
            flex: 1, padding: "10px 14px", border: "1px solid #e2e8f0",
            borderRadius: 10, fontSize: 14, background: "white",
          }}
        />
        <Button onClick={() => send()} disabled={busy || !input.trim()} data-testid="sec-send">
          <Send size={14} /> Enviar
        </Button>
      </div>
    </Card>
  );
}

function MessageBubble({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", flexDirection: isUser ? "row-reverse" : "row" }}>
      <div style={{ width: 28, height: 28, borderRadius: 999, background: isUser ? "#3b82f6" : "#10b981", color: "white", display: "grid", placeItems: "center", flexShrink: 0 }}>
        {isUser ? <UserIcon size={14} /> : <Bot size={14} />}
      </div>
      <div style={{ maxWidth: "78%", background: isUser ? "#dbeafe" : (msg.error ? "#fee2e2" : "#f1f5f9"), color: msg.error ? "#991b1b" : "#0f172a", padding: "10px 14px", borderRadius: 12, fontSize: 13, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
        {msg.content}
        {msg.tools && msg.tools.length > 0 && (
          <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px dashed #cbd5e1", fontSize: 10, color: "#64748b" }}>
            🔧 Consultou: {msg.tools.map((t) => t.name).join(", ")}
          </div>
        )}
      </div>
    </div>
  );
}

function Dot({ delay }) {
  return <span style={{
    width: 6, height: 6, borderRadius: 999, background: "#94a3b8",
    animation: `sec-bounce 1.2s infinite ease-in-out`, animationDelay: `${delay}ms`,
  }} />;
}

/* ===========================
   GPT Custom setup tab
   =========================== */
function GptSetupTab() {
  const [cfg, setCfg] = useState(null);
  const [showToken, setShowToken] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copiedKey, setCopiedKey] = useState(null);

  const load = useCallback(async () => {
    try { setCfg(await api.secretariaConfig()); }
    catch { setCfg(null); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function regenerate() {
    if (!window.confirm("Gerar novo token? O GPT atual deixará de funcionar até você atualizar a Action.")) return;
    setBusy(true);
    try {
      const r = await api.secretariaRegenerateToken();
      setCfg((c) => ({ ...c, webhook_token: r.webhook_token }));
    } finally { setBusy(false); }
  }

  function copy(text, key) {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1500);
  }

  if (!cfg) return <div style={{ padding: 16, color: "#64748b" }}>Carregando…</div>;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 18 }}>
      <Card>
        <h3 style={{ margin: "0 0 6px", fontSize: 15, fontWeight: 800, color: "#0f172a" }}>
          Como criar o GPT customizado
        </h3>
        <div style={{ fontSize: 12, color: "#64748b", marginBottom: 14 }}>
          A Ligo fica disponível dentro do ChatGPT (web e celular), respondendo perguntas com dados reais do seu sistema.
        </div>

        <Step n={1} title="Acesse o GPT Builder">
          <p>Abra <a href="https://chatgpt.com/gpts/editor" target="_blank" rel="noreferrer" style={{ color: "#0d9488", textDecoration: "underline" }}>chatgpt.com/gpts/editor <ExternalLink size={11} style={{ display: "inline" }} /></a> (precisa do ChatGPT Plus).</p>
          <p>Aba <strong>Configure</strong> → coloque o nome <code style={codeInline}>Ligo - Secretária ISP</code> e a descrição que quiser.</p>
        </Step>

        <Step n={2} title="Cole as instruções (Instructions)">
          <CopyBlock label="Instructions" testid="sec-gpt-instructions"
                     onCopy={(t) => copy(t, "inst")}
                     copied={copiedKey === "inst"}
                     text={`Você é o front-end conversacional da Ligo, secretária executiva de um provedor de internet (ISP).
Sempre que o usuário fizer uma pergunta sobre dados operacionais (clientes, técnicos, lousa de serviços, OLT, churn, financeiro, agentes IA), você DEVE chamar a Action "askLigo" e passar a pergunta no campo "question". Repasse a resposta da Ligo ao usuário SEM alterar números. Você pode adicionar contexto curto antes/depois.`} />
        </Step>

        <Step n={3} title="Adicione a Action">
          <p>Role até <strong>Actions</strong> → <strong>Create new action</strong> → cole o schema abaixo em "Schema":</p>
          <CopyBlock label="OpenAPI URL" testid="sec-gpt-openapi" small
                     onCopy={() => copy(cfg.openapi_url, "spec")}
                     copied={copiedKey === "spec"}
                     text={cfg.openapi_url} />
          <p style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
            Ou clique em "Import from URL" no GPT Builder e cole essa URL.
          </p>
        </Step>

        <Step n={4} title="Autenticação">
          <p>Em <strong>Authentication</strong> dessa Action, escolha:</p>
          <ul style={{ margin: "4px 0 8px 18px", fontSize: 12, lineHeight: 1.6 }}>
            <li>Type: <strong>API Key</strong></li>
            <li>Auth Type: <strong>Bearer</strong></li>
            <li>API Key: cole o token abaixo</li>
          </ul>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <code style={{ ...codeBlock, flex: 1, fontFamily: "monospace", padding: "8px 10px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} data-testid="sec-gpt-token">
              {showToken ? cfg.webhook_token : "•".repeat(40)}
            </code>
            <button onClick={() => setShowToken((v) => !v)} title={showToken ? "Esconder" : "Mostrar"}
                    style={iconBtn} data-testid="sec-gpt-token-toggle">
              {showToken ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
            <button onClick={() => copy(cfg.webhook_token, "token")} title="Copiar"
                    style={iconBtn} data-testid="sec-gpt-token-copy">
              {copiedKey === "token" ? <CheckCircle2 size={14} color="#16a34a" /> : <Copy size={14} />}
            </button>
            <button onClick={regenerate} disabled={busy} title="Gerar novo token"
                    style={iconBtn} data-testid="sec-gpt-token-regen">
              <RefreshCw size={14} className={busy ? "animate-spin" : ""} />
            </button>
          </div>
        </Step>

        <Step n={5} title="Privacy Policy (qualquer URL serve)">
          <p>OpenAI exige uma URL de Privacy Policy. Use a do seu site, ou crie uma página simples.</p>
        </Step>

        <Step n={6} title="Salvar e testar">
          <p>Clique <strong>Create</strong>. No chat com seu GPT, digite: "oi minha Ligo, quantos clientes eu tenho?" — ele vai chamar a Action e responder com dados reais.</p>
        </Step>
      </Card>

      <Card>
        <h3 style={{ margin: "0 0 6px", fontSize: 14, fontWeight: 800, color: "#0f172a" }}>Status</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", background: cfg.enabled ? "#dcfce7" : "#fee2e2", color: cfg.enabled ? "#15803d" : "#991b1b", borderRadius: 8, fontSize: 12, fontWeight: 700, marginBottom: 12 }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: cfg.enabled ? "#22c55e" : "#ef4444" }} />
          {cfg.enabled ? "Webhook ativo" : "Webhook desativado"}
        </div>

        <h4 style={{ margin: "10px 0 4px", fontSize: 12, fontWeight: 700, color: "#475569" }}>URL do Webhook</h4>
        <code style={{ ...codeBlock, display: "block", wordBreak: "break-all", padding: "8px 10px", fontSize: 11 }} data-testid="sec-gpt-webhook-url">
          {cfg.webhook_url}
        </code>

        <h4 style={{ margin: "14px 0 4px", fontSize: 12, fontWeight: 700, color: "#475569" }}>Suporte</h4>
        <div style={{ fontSize: 11, color: "#64748b", lineHeight: 1.55 }}>
          O GPT customizado é construído na sua conta ChatGPT Plus. Para que ele converse com a Ligo, ele chama via HTTPS o webhook acima usando o bearer token gerado aqui. Você pode rotacionar o token a qualquer momento (invalida o GPT antigo).
        </div>
      </Card>
    </div>
  );
}

function Step({ n, title, children }) {
  return (
    <div style={{ marginBottom: 14, paddingBottom: 14, borderBottom: "1px dashed #e2e8f0" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span style={{ width: 22, height: 22, borderRadius: 999, background: "#0f172a", color: "white", display: "grid", placeItems: "center", fontSize: 11, fontWeight: 800 }}>{n}</span>
        <strong style={{ fontSize: 13, color: "#0f172a" }}>{title}</strong>
      </div>
      <div style={{ fontSize: 12, color: "#475569", lineHeight: 1.55 }}>{children}</div>
    </div>
  );
}

function CopyBlock({ label, text, onCopy, copied, testid, small }) {
  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</span>
        <button onClick={onCopy} data-testid={testid}
                style={{ background: "transparent", border: "1px solid #e2e8f0", borderRadius: 6, padding: "2px 8px", fontSize: 10, cursor: "pointer", display: "flex", alignItems: "center", gap: 4, color: copied ? "#16a34a" : "#475569" }}>
          {copied ? <><CheckCircle2 size={10} /> Copiado</> : <><Copy size={10} /> Copiar</>}
        </button>
      </div>
      <pre style={{ ...codeBlock, padding: small ? 8 : 10, fontSize: small ? 11 : 11.5, margin: 0, maxHeight: small ? 60 : 160, overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {text}
      </pre>
    </div>
  );
}

/* ===========================
   History tab
   =========================== */
function HistoryTab() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try { setItems((await api.secretariaLogs(50)).items || []); }
      catch { setItems([]); }
      finally { setLoading(false); }
    })();
  }, []);

  if (loading) return <div style={{ padding: 16, color: "#64748b" }}>Carregando…</div>;
  if (!items.length) return <Card><div style={{ padding: 16, color: "#94a3b8", textAlign: "center", fontSize: 13 }}>Nenhuma pergunta registrada ainda.</div></Card>;

  return (
    <Card>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((it) => (
          <div key={it.id} data-testid={`sec-log-${it.id}`} style={{ padding: 12, border: "1px solid #e2e8f0", borderRadius: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, alignItems: "center", flexWrap: "wrap", gap: 6 }}>
              <span style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.4 }}>
                {it.channel || "internal"} · {it.who || "—"}
              </span>
              <span style={{ fontSize: 10, color: "#94a3b8" }}>
                {it.created_at ? new Date(it.created_at).toLocaleString("pt-BR") : "—"}
                {it.elapsed_ms ? ` · ${it.elapsed_ms}ms` : ""}
              </span>
            </div>
            <div style={{ fontSize: 12, color: "#0f172a", fontWeight: 700, marginBottom: 4 }}>
              <UserIcon size={11} style={{ display: "inline", marginRight: 4 }} />
              {it.question}
            </div>
            <div style={{ fontSize: 12, color: "#475569", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
              <Bot size={11} style={{ display: "inline", marginRight: 4, color: "#10b981" }} />
              {it.answer}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ===========================
   Style helpers
   =========================== */
const codeInline = { background: "#f1f5f9", padding: "1px 5px", borderRadius: 3, fontFamily: "monospace", fontSize: 11 };
const codeBlock = { background: "#0f172a", color: "#e2e8f0", borderRadius: 6, fontFamily: "ui-monospace, SFMono-Regular, monospace" };
const iconBtn = { background: "transparent", border: "1px solid #e2e8f0", borderRadius: 6, padding: 6, cursor: "pointer", color: "#475569" };

// CSS keyframes globais (poderia ir no index.css, mas inline-safe via styled)
if (typeof document !== "undefined" && !document.getElementById("sec-bounce-kf")) {
  const style = document.createElement("style");
  style.id = "sec-bounce-kf";
  style.textContent = `@keyframes sec-bounce { 0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); } 40% { opacity: 1; transform: scale(1); } }`;
  document.head.appendChild(style);
}
