/* AfterHoursMetricsCard — dashboard de conversas resolvidas pela IA
   FORA do horário comercial. Conta auto_reply outbound msgs em janela
   fora do business_hours.
*/
import React, { useEffect, useState, useCallback } from "react";
import { Card } from "@/ui";
import { api } from "@/api";
import { Moon, Sun, TrendingUp, Users, RefreshCw, Sparkles } from "lucide-react";

const RANGES = [
  { id: 1, label: "24h" },
  { id: 7, label: "7d" },
  { id: 30, label: "30d" },
];

export default function AfterHoursMetricsCard() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data: d } = await api._client.get(
        `/whatsapp-baileys/after-hours-metrics?days=${days}`,
      );
      setData(d);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  if (loading && !data) {
    return (
      <Card style={{ padding: 16 }} data-testid="after-hours-card-loading">
        <p style={{ color: "#64748b", fontSize: 13 }}>
          Carregando métricas fora do horário...
        </p>
      </Card>
    );
  }
  if (error) {
    return (
      <Card style={{ padding: 16, background: "#fef2f2",
                      border: "1px solid #fecaca" }}
            data-testid="after-hours-card-error">
        <p style={{ color: "#991b1b", fontSize: 13, fontWeight: 600 }}>
          {error}
        </p>
      </Card>
    );
  }
  if (!data) return null;

  const total = data.after_hours_total_messages || 0;
  const clients = data.after_hours_unique_clients || 0;
  const inHours = data.in_hours_total_messages || 0;
  const totalAll = total + inHours;
  const sharePct = totalAll > 0 ? Math.round((total / totalAll) * 100) : 0;
  const maxBar = Math.max(1, ...data.by_day.map((d) => d.count));
  const isOpen = data.is_open_now;

  return (
    <Card style={{ padding: 0, overflow: "hidden" }}
          data-testid="after-hours-metrics-card">
      <div style={{
        padding: 18,
        background: isOpen
          ? "linear-gradient(135deg, #16a34a 0%, #15803d 100%)"
          : "linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)",
        color: "white",
        display: "flex", alignItems: "center", gap: 12,
      }}>
        {isOpen ? <Sun size={28} /> : <Moon size={28} />}
        <div style={{ flex: 1 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800 }}>
            Conversas resolvidas pela IA fora do horário
          </h3>
          <p style={{ margin: "3px 0 0", fontSize: 12, opacity: 0.9 }}>
            {isOpen
              ? "Atendimento humano aberto agora — IA segue trabalhando 24/7"
              : `Fora do horário comercial${
                    data.next_open_human ? ` · abre ${data.next_open_human}` : ""
                  }`}
          </p>
        </div>
        <div style={{ display: "inline-flex", borderRadius: 8,
                        background: "rgba(255,255,255,.15)" }}>
          {RANGES.map((r) => (
            <button key={r.id}
                    onClick={() => setDays(r.id)}
                    data-testid={`ah-range-${r.id}`}
                    style={{
                      padding: "6px 12px", fontSize: 11, fontWeight: 800,
                      border: "none", cursor: "pointer",
                      background: days === r.id
                        ? "rgba(255,255,255,.25)"
                        : "transparent",
                      color: "white",
                    }}>{r.label}</button>
          ))}
        </div>
        <button onClick={load}
                data-testid="ah-refresh"
                style={{
                  padding: 8, borderRadius: 8, border: "none",
                  background: "rgba(255,255,255,.15)", color: "white",
                  cursor: "pointer", display: "grid", placeItems: "center",
                }}>
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Big numbers */}
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(3, 1fr)",
                      gap: 1, background: "#e2e8f0" }}>
        <KPI testid="ah-total"
              icon={<Sparkles size={16} />}
              label="Mensagens auto-respondidas"
              value={total}
              hint={`${sharePct}% do total da janela`} />
        <KPI testid="ah-clients"
              icon={<Users size={16} />}
              label="Clientes únicos atendidos"
              value={clients}
              hint="sem você levantar dedo" />
        <KPI testid="ah-roi"
              icon={<TrendingUp size={16} />}
              label="Equivalente em call-center"
              value={`R$ ${(total * 2.5).toFixed(2)}`}
              hint="≈R$2,50/atendimento evitado" />
      </div>

      {/* Sparkline */}
      <div style={{ padding: 16 }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                        textTransform: "uppercase", letterSpacing: 0.5,
                        marginBottom: 8 }}>
          ÚLTIMOS {data.window_days} {data.window_days === 1 ? "DIA" : "DIAS"}
        </div>
        <div data-testid="ah-sparkline"
              style={{ display: "flex", alignItems: "flex-end", gap: 4,
                        height: 64, padding: "0 4px" }}>
          {data.by_day.map((d) => (
            <div key={d.date}
                  style={{ flex: 1, display: "flex",
                            flexDirection: "column", alignItems: "center",
                            gap: 4 }}
                  title={`${d.label}: ${d.count} msg`}>
              <div style={{
                width: "100%",
                height: `${(d.count / maxBar) * 100}%`,
                minHeight: d.count > 0 ? 3 : 1,
                background: d.count > 0 ? "#7c3aed" : "#e2e8f0",
                borderRadius: 3,
                transition: "height .3s ease",
              }} />
              <span style={{ fontSize: 9, color: "#64748b" }}>{d.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Top agents */}
      {data.top_agents && data.top_agents.length > 0 && (
        <div style={{ padding: "0 16px 12px" }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", letterSpacing: 0.5,
                          marginBottom: 6 }}>
            TOP AGENTES (FORA DO HORÁRIO)
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {data.top_agents.map((a) => (
              <span key={a.agent_name}
                    data-testid={`ah-agent-${a.agent_name}`}
                    style={{
                      padding: "4px 10px", borderRadius: 999, fontSize: 12,
                      background: "#f3e8ff", color: "#6b21a8",
                      fontWeight: 700,
                      border: "1px solid #ddd6fe",
                    }}>
                {a.agent_name} · {a.count}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Samples */}
      {data.samples && data.samples.length > 0 && (
        <div style={{ padding: "12px 16px 16px",
                        borderTop: "1px solid #e2e8f0",
                        background: "#fafafa" }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", letterSpacing: 0.5,
                          marginBottom: 8 }}>
            ÚLTIMAS RESPOSTAS DA IA FORA DO HORÁRIO
          </div>
          <div data-testid="ah-samples"
                style={{ display: "grid", gap: 6 }}>
            {data.samples.slice(0, 5).map((s, i) => (
              <div key={i}
                    style={{
                      padding: "8px 10px", borderRadius: 8, fontSize: 12,
                      background: "white", border: "1px solid #e2e8f0",
                    }}>
                <div style={{ display: "flex", gap: 6, fontSize: 10,
                                color: "#64748b", marginBottom: 3 }}>
                  <strong style={{ color: "#7c3aed" }}>
                    {s.agent_name}
                  </strong>
                  <span>· {s.phone}</span>
                  <span style={{ marginLeft: "auto" }}>
                    {formatSampleTime(s.at)}
                  </span>
                </div>
                <div style={{ color: "#0f172a", lineHeight: 1.4 }}>
                  {s.text}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {total === 0 && (
        <div data-testid="ah-empty"
              style={{ padding: 24, textAlign: "center",
                        color: "#64748b", fontSize: 13 }}>
          Nenhuma resposta automática fora do horário nos últimos{" "}
          {data.window_days} {data.window_days === 1 ? "dia" : "dias"}.
          {" "}Quando isso acontecer, vai aparecer aqui 🌙
        </div>
      )}
    </Card>
  );
}

function KPI({ icon, label, value, hint, testid }) {
  return (
    <div data-testid={testid}
          style={{ padding: 14, background: "white",
                    display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                      fontSize: 10, fontWeight: 800, color: "#7c3aed",
                      textTransform: "uppercase", letterSpacing: 0.5 }}>
        {icon} {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color: "#0f172a",
                      lineHeight: 1, letterSpacing: "-.02em" }}>
        {value}
      </div>
      {hint && (
        <div style={{ fontSize: 11, color: "#64748b" }}>{hint}</div>
      )}
    </div>
  );
}

function formatSampleTime(iso) {
  if (!iso) return "";
  try {
    const dt = new Date(iso);
    const now = new Date();
    const diff = (now - dt) / 1000;
    if (diff < 60) return "agora";
    if (diff < 3600) return `${Math.round(diff / 60)}min`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h`;
    return dt.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  } catch {
    return "";
  }
}
