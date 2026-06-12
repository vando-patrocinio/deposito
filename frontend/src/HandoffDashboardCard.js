/**
 * HandoffDashboardCard.js — Métricas de handoff entre agentes IA
 * (Isabella ⇄ Alvaro ⇄ Pâmela)
 *
 * Mostra:
 *  - Total de handoffs e taxa (% das respostas IA)
 *  - Rotas mais comuns (ex.: "Isabella → Pâmela: 12")
 *  - Agente que mais RECEBE vs mais ENVIA handoffs
 *  - Conversas "hot" (≥3 handoffs — sinal de prompt fraco)
 */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import { ArrowRightLeft, TrendingUp, AlertCircle, RefreshCw, Loader2 } from "lucide-react";

const PERIODS = [
  { label: "24h", value: 1 },
  { label: "7 dias", value: 7 },
  { label: "30 dias", value: 30 },
];

const AGENT_COLOR = {
  Isabella: "#a855f7",  // roxo
  Alvaro:   "#3b82f6",  // azul
  Pâmela:   "#10b981",  // verde
  Camila:   "#10b981",  // verde (nome antigo — conversas históricas)
  Teste:    "#64748b",  // cinza
};

export default function HandoffDashboardCard() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api._client.get(`/central-ia/dashboard/handoffs?days=${days}`);
      setData(r.data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const colorOf = (name) => AGENT_COLOR[name] || "#94a3b8";

  return (
    <Card title={null} style={{ padding: 0, overflow: "hidden" }}>
      <div style={{
        padding: "14px 18px",
        background: "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)",
        color: "#f1f5f9", display: "flex", alignItems: "center",
        justifyContent: "space-between", flexWrap: "wrap", gap: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <ArrowRightLeft size={18} color="#fbbf24" />
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }} data-testid="handoff-card-title">
            Handoffs entre Agentes IA
          </h3>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {PERIODS.map(p => (
            <button
              key={p.value}
              onClick={() => setDays(p.value)}
              data-testid={`handoff-period-${p.value}`}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600,
                background: days === p.value ? "#fbbf24" : "rgba(255,255,255,0.08)",
                color: days === p.value ? "#451a03" : "#cbd5e1",
                border: "none", borderRadius: 6, cursor: "pointer",
              }}
            >
              {p.label}
            </button>
          ))}
          <button
            onClick={load}
            data-testid="handoff-reload"
            style={{
              padding: "4px 8px",
              background: "rgba(255,255,255,0.08)",
              color: "#cbd5e1", border: "none", borderRadius: 6, cursor: "pointer",
            }}
            title="Recarregar"
          >
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      <div style={{ padding: 18 }}>
        {loading && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", color: "#64748b" }}>
            <Loader2 size={14} className="animate-spin" /> Carregando…
          </div>
        )}

        {!loading && data && (
          <>
            {/* KPIs topo */}
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: 10, marginBottom: 16,
            }}>
              <Kpi label="Total handoffs" value={data.total_handoffs} testid="kpi-total" />
              <Kpi
                label="Taxa"
                value={`${data.handoff_rate_pct}%`}
                hint={`de ${data.total_ai_replies} respostas IA`}
                testid="kpi-rate"
              />
              <Kpi
                label="Rotas únicas"
                value={data.routes.length}
                testid="kpi-routes"
              />
              <Kpi
                label="Conv. com ≥2 handoffs"
                value={data.hot_phones.length}
                tone={data.hot_phones.length > 0 ? "warn" : "ok"}
                testid="kpi-hot"
              />
            </div>

            {/* Empty state */}
            {data.total_handoffs === 0 && (
              <div style={{
                padding: 16, textAlign: "center",
                background: "#f8fafc", borderRadius: 10,
                border: "1px dashed #cbd5e1", color: "#64748b", fontSize: 13,
              }} data-testid="handoff-empty">
                Nenhum handoff registrado ainda neste período.<br/>
                <span style={{ fontSize: 11, color: "#94a3b8" }}>
                  Quando a Isabella passar uma conversa pra Alvaro ou Pâmela (ou vice-versa), aparece aqui.
                </span>
              </div>
            )}

            {/* Rotas */}
            {data.routes.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#475569", marginBottom: 8 }}>
                  Rotas mais comuns
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }} data-testid="handoff-routes">
                  {data.routes.slice(0, 8).map(r => (
                    <div
                      key={r.route}
                      data-testid={`handoff-route-${r.from}-${r.to}`}
                      style={{
                        display: "flex", alignItems: "center", gap: 10,
                        padding: "8px 12px", background: "#f8fafc",
                        borderRadius: 8, border: "1px solid #e2e8f0",
                      }}
                    >
                      <Pill name={r.from} color={colorOf(r.from)} />
                      <ArrowRightLeft size={12} color="#94a3b8" />
                      <Pill name={r.to} color={colorOf(r.to)} />
                      <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center" }}>
                        <span style={{ fontSize: 12, color: "#64748b" }}>
                          {r.pct}%
                        </span>
                        <span style={{
                          fontSize: 13, fontWeight: 700,
                          color: "#0f172a", minWidth: 28, textAlign: "right",
                        }}>{r.count}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Mais recebe vs mais envia */}
            {(data.agents_received.length > 0 || data.agents_sent.length > 0) && (
              <div style={{
                display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: 14, marginBottom: 16,
              }}>
                {data.agents_received.length > 0 && (
                  <Block title="Mais RECEBE" hint="quem cuida do problema final" data-testid="handoff-received">
                    {data.agents_received.map(a => (
                      <AgentBar key={a.agent} name={a.agent} count={a.count}
                        max={Math.max(...data.agents_received.map(x => x.count))}
                        color={colorOf(a.agent)} />
                    ))}
                  </Block>
                )}
                {data.agents_sent.length > 0 && (
                  <Block title="Mais ENVIA" hint="quem mais transfere" data-testid="handoff-sent">
                    {data.agents_sent.map(a => (
                      <AgentBar key={a.agent} name={a.agent} count={a.count}
                        max={Math.max(...data.agents_sent.map(x => x.count))}
                        color={colorOf(a.agent)} />
                    ))}
                  </Block>
                )}
              </div>
            )}

            {/* Conversas hot */}
            {data.hot_phones.length > 0 && (
              <div style={{
                padding: 12, background: "#fef3c7", borderRadius: 10,
                border: "1px solid #fbbf24", marginBottom: 10,
              }} data-testid="handoff-hot-phones">
                <div style={{
                  display: "flex", alignItems: "center", gap: 6,
                  fontSize: 12, fontWeight: 700, color: "#92400e", marginBottom: 6,
                }}>
                  <AlertCircle size={13} /> Conversas com múltiplos handoffs
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {data.hot_phones.map(p => (
                    <span key={p.phone} style={{
                      fontSize: 11, padding: "3px 8px", borderRadius: 999,
                      background: "white", color: "#92400e", fontWeight: 600,
                      fontFamily: "JetBrains Mono, monospace",
                      border: "1px solid #fbbf24",
                    }}>
                      {p.phone} · {p.count}x
                    </span>
                  ))}
                </div>
                <div style={{ fontSize: 11, color: "#78350f", marginTop: 6, lineHeight: 1.4 }}>
                  Muitos handoffs na mesma conversa pode indicar que os prompts dos agentes
                  precisam de ajuste ou que o cliente tem dúvidas mistas (vendas + suporte + cobrança).
                </div>
              </div>
            )}

            {/* Footer com insight */}
            {data.total_handoffs > 0 && (
              <div style={{
                fontSize: 11, color: "#64748b", marginTop: 10,
                padding: 8, background: "#f0fdf4", borderRadius: 8,
                border: "1px solid #bbf7d0",
                display: "flex", gap: 6, alignItems: "flex-start",
              }}>
                <TrendingUp size={12} color="#16a34a" style={{ marginTop: 2 }} />
                <span>
                  Taxa de handoff saudável é entre <strong>5-15%</strong>.
                  {data.handoff_rate_pct < 5
                    ? " Sua taxa está baixa — bom sinal, os agentes estão resolvendo no escopo."
                    : data.handoff_rate_pct > 15
                      ? " Sua taxa está alta — talvez o roteamento inicial esteja errando ou os prompts precisam de ajuste."
                      : " Sua taxa está dentro do esperado."}
                </span>
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

function Kpi({ label, value, hint, tone, testid }) {
  const bg = tone === "warn" ? "#fef3c7" : tone === "ok" ? "#f0fdf4" : "#f8fafc";
  const fg = tone === "warn" ? "#92400e" : tone === "ok" ? "#15803d" : "#0f172a";
  return (
    <div style={{
      padding: 10, background: bg, borderRadius: 10,
      border: "1px solid #e2e8f0",
    }} data-testid={testid}>
      <div style={{ fontSize: 10, color: "#64748b", textTransform: "uppercase",
        letterSpacing: 0.4, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, color: fg, marginTop: 2 }}>
        {value}
      </div>
      {hint && <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 1 }}>{hint}</div>}
    </div>
  );
}

function Pill({ name, color }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontSize: 12, fontWeight: 600,
      padding: "3px 9px", borderRadius: 999,
      background: `${color}22`, color: color,
      border: `1px solid ${color}55`,
    }}>
      {name}
    </span>
  );
}

function Block({ title, hint, children, ...props }) {
  return (
    <div style={{
      padding: 10, background: "#f8fafc", borderRadius: 10,
      border: "1px solid #e2e8f0",
    }} {...props}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
        textTransform: "uppercase", letterSpacing: 0.4 }}>
        {title}
      </div>
      {hint && <div style={{ fontSize: 10, color: "#94a3b8", marginBottom: 8 }}>{hint}</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
        {children}
      </div>
    </div>
  );
}

function AgentBar({ name, count, max, color }) {
  const pct = max > 0 ? (count / max) * 100 : 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ fontSize: 12, fontWeight: 600, minWidth: 70, color: "#0f172a" }}>
        {name}
      </span>
      <div style={{
        flex: 1, height: 8, background: "#e2e8f0", borderRadius: 4,
        overflow: "hidden",
      }}>
        <div style={{
          width: `${pct}%`, height: "100%", background: color,
          transition: "width 250ms",
        }} />
      </div>
      <span style={{ fontSize: 11, fontWeight: 700, color: "#475569", minWidth: 22, textAlign: "right" }}>
        {count}
      </span>
    </div>
  );
}
