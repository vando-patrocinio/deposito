/**
 * IsabellaMemoryInspector.jsx — Dashboard Memória da Isabella
 *
 * Aba dentro do AICenterOS que mostra EXATAMENTE qual contexto a
 * Isabella veria agora se um determinado telefone mandasse mensagem.
 *
 * Útil pro CTO auditar:
 *   - Quais blocos foram carregados (anti-cpf / short-term / long-term / ...)
 *   - Tamanho em chars/tokens de cada bloco
 *   - History turns recentes (chat-like)
 *   - System prompt completo (copiar p/ auditoria offline)
 */
import React, { useEffect, useState } from "react";
import { client } from "@/api";

const BLOCK_COLORS = {
  base_prompt:     "#475569",
  subscriber_ctx:  "#0ea5e9",
  anti_cpf:        "#ef4444",
  short_term:      "#fbbf24",
  long_term:       "#10b981",
  corrections:     "#a855f7",
  orchestrated:    "#06b6d4",
};

function fmtN(n) { return (n || 0).toLocaleString("pt-BR"); }

function CopyBtn({ text, label = "Copiar" }) {
  const [done, setDone] = useState(false);
  return (
    <button
      data-testid="copy-prompt-btn"
      onClick={async () => {
        await navigator.clipboard.writeText(text || "");
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      style={{
        padding: "6px 12px",
        background: done ? "#10b981" : "#1e293b",
        color: "#e2e8f0",
        border: "1px solid #334155",
        borderRadius: 6,
        cursor: "pointer",
        fontSize: 12,
      }}>
      {done ? "✔ Copiado" : `📋 ${label}`}
    </button>
  );
}

function BlockCard({ block, expanded, onToggle }) {
  const color = BLOCK_COLORS[block.id] || "#64748b";
  return (
    <div data-testid={`memory-block-${block.id}`}
         style={{
           background: "#0b1220", border: `1px solid ${color}33`,
           borderLeft: `4px solid ${color}`,
           borderRadius: 8, padding: 14, marginBottom: 10,
         }}>
      <div onClick={onToggle}
           style={{
             display: "flex", justifyContent: "space-between",
             alignItems: "center", cursor: "pointer",
           }}>
        <div>
          <div style={{ color: "#e2e8f0", fontWeight: 600, fontSize: 14 }}>
            {block.label}
          </div>
          <div style={{ color: "#64748b", fontSize: 11, marginTop: 2 }}>
            {fmtN(block.chars)} chars · ~{fmtN(block.tokens_est)} tokens
          </div>
        </div>
        <div style={{ color, fontSize: 18 }}>
          {expanded ? "▾" : "▸"}
        </div>
      </div>
      {expanded && (
        <pre data-testid={`memory-block-content-${block.id}`}
             style={{
               background: "#020617", color: "#cbd5e1",
               padding: 12, marginTop: 10, borderRadius: 6,
               fontSize: 12, maxHeight: 360, overflow: "auto",
               whiteSpace: "pre-wrap", wordBreak: "break-word",
             }}>
{block.content}
        </pre>
      )}
      {expanded && block.meta && (
        <pre style={{
          background: "#020617", color: "#10b981",
          padding: 10, marginTop: 8, borderRadius: 6,
          fontSize: 11, overflow: "auto",
        }}>
{`meta: ${JSON.stringify(block.meta, null, 2)}`}
        </pre>
      )}
    </div>
  );
}

function HistoryTurns({ turns }) {
  if (!turns || turns.length === 0) {
    return <div style={{ color: "#64748b", padding: 12 }}>
      Sem histórico recente.
    </div>;
  }
  return (
    <div data-testid="memory-history-turns"
         style={{ maxHeight: 480, overflow: "auto", padding: 8 }}>
      {turns.map((t, i) => {
        const isUser = t.role === "user";
        return (
          <div key={i} style={{
            display: "flex",
            justifyContent: isUser ? "flex-start" : "flex-end",
            marginBottom: 6,
          }}>
            <div style={{
              maxWidth: "75%",
              background: isUser ? "#1e293b" : "#064e3b",
              color: "#e2e8f0",
              padding: "8px 12px",
              borderRadius: 10,
              fontSize: 13,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}>
              <div style={{
                fontSize: 10, color: isUser ? "#60a5fa" : "#10b981",
                marginBottom: 4, fontWeight: 600,
              }}>
                {isUser ? "🧑 Cliente" : "👩‍💼 Isabella"}
              </div>
              {t.content}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function IsabellaMemoryInspector() {
  const [phone, setPhone] = useState("");
  const [userText, setUserText] = useState("sim");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState({});
  const [recent, setRecent] = useState([]);

  const loadRecent = async () => {
    try {
      const r = await client.get("/isabella/memory/recent-phones?limit=10");
      setRecent(r.data?.items || []);
    } catch (e) {
      // silencioso
    }
  };

  useEffect(() => {
    loadRecent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const inspect = async (phoneOverride) => {
    const p = (phoneOverride || phone || "").trim();
    if (!p) { setError("Informe um telefone."); return; }
    setLoading(true); setError(""); setData(null);
    try {
      const r = await client.get("/isabella/memory/preview", {
        params: { phone: p, user_text: userText || "sim" },
      });
      setData(r.data);
      // expande automaticamente os blocos críticos
      setExpanded({ short_term: true, long_term: true });
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "Falha ao inspecionar");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div data-testid="isabella-memory-inspector"
         style={{ color: "#e2e8f0", padding: 24, maxWidth: 1300,
                  margin: "0 auto" }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>
        🧠 Memória da Isabella — Inspector
      </h2>
      <p style={{ color: "#94a3b8", fontSize: 13, marginBottom: 20 }}>
        Veja exatamente quais blocos de contexto a Isabella carregaria
        agora pra um cliente específico. Auditoria em tempo real do
        cérebro da Customer Success Director.
      </p>

      {/* Form */}
      <div style={{
        background: "#0b1220", padding: 16, borderRadius: 10,
        border: "1px solid #1e293b", marginBottom: 20,
      }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <input
            data-testid="memory-phone-input"
            placeholder="Telefone (ex: 5521998176526)"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            style={{
              flex: "1 1 240px", background: "#020617",
              color: "#e2e8f0", border: "1px solid #334155",
              borderRadius: 6, padding: "8px 12px", fontSize: 14,
            }}
          />
          <input
            data-testid="memory-user-text-input"
            placeholder='Texto simulado (ex: "sim")'
            value={userText}
            onChange={(e) => setUserText(e.target.value)}
            style={{
              flex: "1 1 200px", background: "#020617",
              color: "#e2e8f0", border: "1px solid #334155",
              borderRadius: 6, padding: "8px 12px", fontSize: 14,
            }}
          />
          <button
            data-testid="memory-inspect-btn"
            onClick={() => inspect()}
            disabled={loading}
            style={{
              padding: "8px 20px", background: "#0ea5e9",
              color: "#fff", border: "none", borderRadius: 6,
              cursor: loading ? "wait" : "pointer", fontWeight: 600,
            }}>
            {loading ? "Inspecionando..." : "🔍 Inspecionar"}
          </button>
        </div>

        {/* Atalhos recentes */}
        {recent.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>
              ATIVIDADE RECENTE — clique pra inspecionar
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {recent.slice(0, 10).map((r) => (
                <button key={r.phone}
                        data-testid={`recent-phone-${r.phone}`}
                        onClick={() => { setPhone(r.phone); inspect(r.phone); }}
                        style={{
                          padding: "4px 10px", background: "#1e293b",
                          color: "#cbd5e1", border: "1px solid #334155",
                          borderRadius: 14, fontSize: 11, cursor: "pointer",
                        }}>
                  {r.phone} · {fmtN(r.messages)}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {error && (
        <div data-testid="memory-error"
             style={{
               background: "#7f1d1d", color: "#fecaca", padding: 12,
               borderRadius: 6, marginBottom: 16, fontSize: 13,
             }}>
          ⚠ {error}
        </div>
      )}

      {data && (
        <>
          {/* KPI bar */}
          <div data-testid="memory-kpi-bar"
               style={{
                 display: "grid",
                 gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))",
                 gap: 10, marginBottom: 20,
               }}>
            {[
              ["Phone", data.phone],
              ["Subscriber", data.subscriber_id || "—"],
              ["Blocos", data.blocks.length],
              ["History turns", data.history_turns_count],
              ["Prompt chars", fmtN(data.full_prompt_chars)],
              ["Total payload chars", fmtN(data.total_payload_chars)],
            ].map(([k, v]) => (
              <div key={k} style={{
                background: "#0b1220", padding: 12, borderRadius: 8,
                border: "1px solid #1e293b",
              }}>
                <div style={{ fontSize: 10, color: "#64748b" }}>{k}</div>
                <div style={{ fontSize: 14, color: "#e2e8f0",
                              fontWeight: 600, marginTop: 4,
                              wordBreak: "break-all" }}>
                  {v}
                </div>
              </div>
            ))}
          </div>

          {/* Grid de 2 colunas: blocos | history */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1fr)",
            gap: 16,
          }}>
            <div>
              <div style={{
                display: "flex", justifyContent: "space-between",
                alignItems: "center", marginBottom: 10,
              }}>
                <h3 style={{ fontSize: 15, fontWeight: 600 }}>
                  📦 Blocos do System Prompt
                </h3>
                <CopyBtn text={data.full_system_prompt}
                         label="Copiar prompt completo" />
              </div>
              {data.blocks.map((b) => (
                <BlockCard key={b.id} block={b}
                           expanded={!!expanded[b.id]}
                           onToggle={() => setExpanded((s) => ({
                             ...s, [b.id]: !s[b.id],
                           }))} />
              ))}
            </div>

            <div>
              <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
                💬 History Turns ({data.history_turns_count})
              </h3>
              <div style={{
                background: "#0b1220", borderRadius: 8,
                border: "1px solid #1e293b",
              }}>
                <HistoryTurns turns={data.history_turns} />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
