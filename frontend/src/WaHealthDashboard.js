import React, { useEffect, useState, useCallback } from "react";
import { Card } from "@/ui";
import { api } from "@/api";
import {
  Heart, Wifi, WifiOff, AlertTriangle, Activity, Send, CheckCircle2,
  XCircle, Clock, RefreshCw, Loader2, TrendingUp,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend,
} from "recharts";

/**
 * Painel "Saúde do WhatsApp"
 *
 * Agrega 4 vistas:
 *  1. Sidecar Railway (uptime, state, retry, queue)
 *  2. Delivery (% de mensagens entregues vs falhadas)
 *  3. Latência da Isabella (avg / p50 / p95 / p99 em segundos)
 *  4. Alertas críticos (duplicate_session_suspected, los_cluster_alert,
 *     logged_out, connection_replaced) — counts + lista dos 20 recentes
 *
 * Auto-refresh a cada 20s.
 */
export default function WaHealthDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [days, setDays] = useState(7);
  const [err, setErr] = useState(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true); else setRefreshing(true);
    try {
      const r = await api.waHealthOverview(days);
      setData(r);
      setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      if (!silent) setLoading(false); else setRefreshing(false);
    }
  }, [days]);

  useEffect(() => {
    load();
    const id = setInterval(() => load(true), 20000);
    return () => clearInterval(id);
  }, [load]);

  if (loading) {
    return (
      <Card style={{ padding: 30, textAlign: "center" }}>
        <Loader2 size={20} className="animate-spin" /> Carregando saúde do WhatsApp…
      </Card>
    );
  }
  if (err) {
    return (
      <Card style={{ padding: 16, borderColor: "#dc2626" }}>
        <AlertTriangle size={16} color="#dc2626" /> Falha ao carregar: {err}
      </Card>
    );
  }

  const sidecar = data?.sidecar || {};
  const delivery = data?.delivery || {};
  const latency = data?.isabella_latency || {};
  const alerts = data?.alerts || { counts: {}, recent: [] };
  const sidecarOk = !!sidecar.ok && sidecar.state === "connected";

  // Detecta cenário crítico: 3+ logged_out em 10min OU duplicate_session_suspected
  // ativo nas últimas 30min → mostra banner com instruções acionáveis.
  const recentLoggedOut = (alerts.recent || []).filter((e) =>
    e.event === "logged_out"
    && (Date.now() - new Date(e.created_at).getTime()) < 10 * 60 * 1000,
  );
  const recentDuplicate = (alerts.recent || []).find((e) =>
    e.event === "duplicate_session_suspected"
    && (Date.now() - new Date(e.created_at).getTime()) < 30 * 60 * 1000,
  );
  const criticalSession = recentLoggedOut.length >= 3 || !!recentDuplicate;
  // Pega o "reason" mais recente de logged_out pra contar a verdade pro usuário
  const lastReason = (alerts.recent || [])
    .find((e) => e.event === "logged_out" && e.reason)?.reason;

  return (
    <div data-testid="wa-health-dashboard" style={{ display: "grid", gap: 12 }}>
      {/* Header */}
      <Card style={{ padding: 14 }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          gap: 10, flexWrap: "wrap",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 9,
              background: sidecarOk
                ? "linear-gradient(135deg,#0f766e,#14b8a6)"
                : "linear-gradient(135deg,#dc2626,#f97316)",
              display: "grid", placeItems: "center",
            }}>
              <Heart size={18} color="white" strokeWidth={2} fill="white" />
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 14 }}>
                Saúde do WhatsApp
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Sidecar Railway, entregabilidade, latência Isabella e alertas
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {[1, 7, 30].map((d) => (
              <button
                key={d}
                data-testid={`wa-health-range-${d}d`}
                onClick={() => setDays(d)}
                style={{
                  padding: "4px 10px",
                  border: "1px solid var(--border-default)",
                  background: days === d ? "#0f766e" : "transparent",
                  color: days === d ? "#fff" : "var(--text-secondary)",
                  fontSize: 11, fontWeight: 600, borderRadius: 6,
                  cursor: "pointer",
                }}
              >{d === 1 ? "Hoje" : `${d}d`}</button>
            ))}
            <button
              onClick={() => load(true)}
              data-testid="wa-health-refresh"
              disabled={refreshing}
              style={{
                padding: "4px 10px", border: "1px solid var(--border-default)",
                background: "transparent", color: "var(--text-secondary)",
                fontSize: 11, fontWeight: 600, borderRadius: 6,
                cursor: refreshing ? "not-allowed" : "pointer",
                display: "flex", alignItems: "center", gap: 4,
              }}
            >
              <RefreshCw size={11} className={refreshing ? "animate-spin" : ""} />
              {refreshing ? "..." : "Atualizar"}
            </button>
          </div>
        </div>
      </Card>

      {/* BANNER CRÍTICO — quando detecta cenário de desconexão repetida */}
      {criticalSession && (
        <Card
          data-testid="wa-health-critical-banner"
          style={{
            padding: 16,
            background: "linear-gradient(135deg, #fef2f2, #fff7ed)",
            border: "2px solid #dc2626",
            borderRadius: 10,
          }}
        >
          <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10,
              background: "#dc2626", display: "grid", placeItems: "center",
              flexShrink: 0,
            }}>
              <AlertTriangle size={20} color="white" strokeWidth={2.5} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontWeight: 800, fontSize: 14, color: "#991b1b",
                marginBottom: 4,
              }}>
                Atenção: sessão WhatsApp sendo encerrada repetidamente
              </div>
              <div style={{ fontSize: 12, color: "#7f1d1d", lineHeight: 1.5 }}>
                Detectamos <b>{recentLoggedOut.length}+ desconexões em 10min</b>.
                {lastReason ? (
                  <>
                    {" "}Motivo reportado pelo WhatsApp:{" "}
                    <code style={{
                      background: "#fee2e2", padding: "1px 5px",
                      borderRadius: 3, fontSize: 11,
                    }}>{lastReason}</code>.
                  </>
                ) : null}
                {" "}Esse padrão acontece quando <b>alguém está clicando
                “Desconectar dispositivo” no celular</b> ou quando o
                <b> número está logado em outro WhatsApp Web/Desktop</b>.
              </div>
              <div style={{
                marginTop: 10, padding: 10, background: "#fff",
                border: "1px solid #fecaca", borderRadius: 6,
                fontSize: 12, color: "#7f1d1d", lineHeight: 1.6,
              }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>
                  Como resolver (faça no celular do Ligo):
                </div>
                <ol style={{ margin: 0, paddingLeft: 18 }}>
                  <li>
                    Abra o WhatsApp do celular → menu <b>⋮</b> →
                    <b> Aparelhos conectados</b>
                  </li>
                  <li>
                    Toque em cada dispositivo conectado e
                    <b> Desconectar</b> — exceto este painel SmartProv
                  </li>
                  <li>
                    Verifique se ninguém mais tem acesso ao celular
                    desconectando manualmente
                  </li>
                  <li>
                    Volte aqui em ~1min — o sidecar tenta reconectar
                    automaticamente
                  </li>
                </ol>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Grid de KPIs */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        gap: 10,
      }}>
        <SidecarCard sidecar={sidecar} />
        <DeliveryCard delivery={delivery} />
        <LatencyCard latency={latency} />
        <AlertsSummaryCard alerts={alerts.counts || {}} />
      </div>

      {/* Gráfico de latência ao longo do tempo */}
      <LatencySeriesChart series={latency.series || []} />

      {/* Lista de alertas */}
      <Card style={{ padding: 12 }} data-testid="wa-health-recent-alerts">
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          marginBottom: 8,
        }}>
          <div style={{
            fontWeight: 700, fontSize: 13, display: "flex",
            alignItems: "center", gap: 6,
          }}>
            <AlertTriangle size={14} color="#f59e0b" />
            Alertas recentes (últimos {days}d)
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {alerts.recent?.length || 0} eventos
          </div>
        </div>
        {!alerts.recent?.length ? (
          <div style={{
            padding: 24, textAlign: "center", color: "var(--text-muted)",
            fontSize: 12,
          }}>
            <CheckCircle2 size={28} color="#16a34a" style={{ marginBottom: 6 }} />
            <br />
            Nenhum alerta no período. Tudo tranquilo. ✨
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {alerts.recent.map((e) => (
              <AlertRow key={e.id} ev={e} />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cards individuais
// ---------------------------------------------------------------------------

function SidecarCard({ sidecar }) {
  const ok = !!sidecar.ok && sidecar.state === "connected";
  const uptimeFmt = formatUptime(sidecar.uptime_s);
  return (
    <Card style={{ padding: 12 }} data-testid="wa-health-sidecar-card">
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
      }}>
        {ok
          ? <Wifi size={16} color="#16a34a" />
          : <WifiOff size={16} color="#dc2626" />
        }
        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.5 }}>
          Sidecar Baileys
        </div>
      </div>
      <div style={{
        fontSize: 18, fontWeight: 800,
        color: ok ? "#16a34a" : "#dc2626",
        textTransform: "uppercase",
      }} data-testid="wa-health-sidecar-state">
        {sidecar.state || "—"}
      </div>
      <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-secondary)",
                     lineHeight: 1.6 }}>
        <Row label="Uptime" value={uptimeFmt} />
        <Row label="Retries" value={sidecar.retry_count ?? 0} />
        <Row label="Queue" value={sidecar.queue_size ?? 0} />
        {sidecar.last_send_at && (
          <Row label="Último send" value={fmtRel(sidecar.last_send_at)} />
        )}
        {sidecar.error && (
          <div style={{ marginTop: 4, color: "#dc2626", fontSize: 10 }}>
            {String(sidecar.error).slice(0, 80)}
          </div>
        )}
      </div>
    </Card>
  );
}

function DeliveryCard({ delivery }) {
  const pct = delivery.delivery_pct ?? 0;
  const color = pct >= 99 ? "#16a34a" : pct >= 90 ? "#f59e0b" : "#dc2626";
  return (
    <Card style={{ padding: 12 }} data-testid="wa-health-delivery-card">
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
      }}>
        <Send size={16} color="#0f766e" />
        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.5 }}>
          Entregabilidade
        </div>
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color,
                     fontFamily: "var(--font-mono, ui-monospace)" }}
        data-testid="wa-health-delivery-pct">
        {pct}%
      </div>
      <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-secondary)",
                     lineHeight: 1.6 }}>
        <Row label="Total outbound" value={delivery.outbound_total ?? 0} />
        <Row label="Entregues" value={delivery.delivered ?? 0}
              valColor="#16a34a" />
        <Row label="Falharam" value={delivery.failed ?? 0}
              valColor={delivery.failed ? "#dc2626" : undefined} />
      </div>
    </Card>
  );
}

function LatencyCard({ latency }) {
  const samples = latency.samples ?? 0;
  return (
    <Card style={{ padding: 12 }} data-testid="wa-health-latency-card">
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
      }}>
        <Clock size={16} color="#4b1d7a" />
        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.5 }}>
          Latência da Isabella
        </div>
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color: "#4b1d7a",
                     fontFamily: "var(--font-mono, ui-monospace)" }}
        data-testid="wa-health-latency-p50">
        {latency.p50_s ?? 0}s
        <span style={{ fontSize: 11, fontWeight: 500,
                        color: "var(--text-muted)", marginLeft: 4 }}>
          (p50)
        </span>
      </div>
      <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-secondary)",
                     lineHeight: 1.6 }}>
        <Row label="Média" value={`${latency.avg_s ?? 0}s`} />
        <Row label="p95" value={`${latency.p95_s ?? 0}s`} />
        <Row label="p99" value={`${latency.p99_s ?? 0}s`} />
        <Row label="Amostras" value={samples} />
      </div>
    </Card>
  );
}

function AlertsSummaryCard({ alerts }) {
  const totalAlerts = Object.values(alerts).reduce((a, b) => a + (b || 0), 0);
  const critical = (alerts.duplicate_session_suspected || 0)
    + (alerts.los_cluster_alert || 0) + (alerts.possibly_banned || 0);
  return (
    <Card style={{ padding: 12 }} data-testid="wa-health-alerts-card">
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
      }}>
        <Activity size={16} color={critical ? "#dc2626" : "#f59e0b"} />
        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.5 }}>
          Eventos / Alertas
        </div>
      </div>
      <div style={{
        fontSize: 26, fontWeight: 800,
        color: critical ? "#dc2626" : (totalAlerts ? "#f59e0b" : "#64748b"),
        fontFamily: "var(--font-mono, ui-monospace)",
      }} data-testid="wa-health-alerts-total">
        {totalAlerts}
      </div>
      <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-secondary)",
                     lineHeight: 1.6 }}>
        {alerts.duplicate_session_suspected ? (
          <Row label="Sessão duplicada"
                value={alerts.duplicate_session_suspected}
                valColor="#dc2626" />
        ) : null}
        {alerts.los_cluster_alert ? (
          <Row label="LOS cluster" value={alerts.los_cluster_alert}
                valColor="#dc2626" />
        ) : null}
        <Row label="logged_out" value={alerts.logged_out || 0} />
        <Row label="connection_replaced" value={alerts.connection_replaced || 0} />
      </div>
    </Card>
  );
}

function AlertRow({ ev }) {
  const eventStyle = {
    duplicate_session_suspected: { bg: "#fef2f2", color: "#dc2626", label: "Sessão duplicada" },
    los_cluster_alert: { bg: "#fef2f2", color: "#dc2626", label: "LOS cluster" },
    possibly_banned: { bg: "#fef2f2", color: "#dc2626", label: "Possivelmente banido" },
    max_retries_exceeded: { bg: "#fef2f2", color: "#dc2626", label: "Max retries" },
    circuit_breaker_open: { bg: "#fef2f2", color: "#dc2626", label: "Circuit breaker" },
    logged_out: { bg: "#fef3c7", color: "#92400e", label: "Logged out" },
    connection_replaced: { bg: "#fef3c7", color: "#92400e", label: "Sessão substituída" },
  };
  const style = eventStyle[ev.event] || { bg: "var(--bg-elevated)",
    color: "var(--text-secondary)", label: ev.event };
  return (
    <div style={{
      padding: "6px 8px",
      background: "var(--bg-elevated)",
      border: "1px solid var(--border-default)",
      borderRadius: 6,
      display: "flex", justifyContent: "space-between", gap: 8,
      fontSize: 11, alignItems: "center",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, minWidth: 0 }}>
        <span style={{
          padding: "2px 6px", borderRadius: 4, fontSize: 10, fontWeight: 700,
          background: style.bg, color: style.color, whiteSpace: "nowrap",
        }}>{style.label}</span>
        {ev.reason ? (
          <span style={{
            color: "var(--text-muted)", fontSize: 11,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>{ev.reason}</span>
        ) : null}
      </div>
      <span style={{ color: "var(--text-muted)", fontSize: 10,
                      fontFamily: "var(--font-mono, ui-monospace)",
                      whiteSpace: "nowrap" }}>
        {fmtRel(ev.created_at)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gráfico de latência ao longo do tempo (p50 / p95 / p99 por hora)
// ---------------------------------------------------------------------------

function LatencySeriesChart({ series }) {
  if (!series || series.length === 0) {
    return null;
  }
  // Formata hora pra eixo X (HH:00 do dia atual; senão DD/MM HH:00)
  const today = new Date().toISOString().slice(0, 10);
  const data = series.map((s) => ({
    ...s,
    label: s.hour.startsWith(today)
      ? s.hour.slice(11, 16)
      : s.hour.slice(5, 10).replace("-", "/") + " " + s.hour.slice(11, 16),
  }));
  return (
    <Card style={{ padding: 12 }} data-testid="wa-health-latency-chart">
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 8, flexWrap: "wrap", gap: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <TrendingUp size={14} color="#4b1d7a" />
          <div style={{ fontWeight: 700, fontSize: 13 }}>
            Latência da Isabella ao longo do tempo
          </div>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {series.length} buckets · linhas: p50, p95, p99 (s)
        </div>
      </div>
      <div style={{ width: "100%", height: 220 }}>
        <ResponsiveContainer>
          <LineChart
            data={data}
            margin={{ top: 8, right: 12, bottom: 0, left: -12 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: "var(--text-muted)" }}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--text-muted)" }}
              tickFormatter={(v) => `${v}s`}
              width={50}
            />
            <Tooltip
              contentStyle={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-default)",
                fontSize: 11,
                borderRadius: 6,
              }}
              formatter={(v, name) => [`${v}s`, name]}
              labelStyle={{ color: "var(--text-primary)", fontWeight: 700 }}
            />
            <Legend
              wrapperStyle={{ fontSize: 11 }}
              iconSize={8}
            />
            <Line
              type="monotone" dataKey="p50_s" name="p50" stroke="#16a34a"
              strokeWidth={2} dot={{ r: 2 }} activeDot={{ r: 4 }}
            />
            <Line
              type="monotone" dataKey="p95_s" name="p95" stroke="#f59e0b"
              strokeWidth={2} dot={{ r: 2 }} activeDot={{ r: 4 }}
            />
            <Line
              type="monotone" dataKey="p99_s" name="p99" stroke="#dc2626"
              strokeWidth={2} dot={{ r: 2 }} activeDot={{ r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div style={{
        marginTop: 6, fontSize: 10, color: "var(--text-muted)",
        textAlign: "center",
      }}>
        Picos consistentes em p95/p99 podem indicar lentidão do DeepSeek/OpenRouter
        ou prompt grande demais (&gt;40kB).
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Row({ label, value, valColor }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between" }}>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span style={{ fontWeight: 600, color: valColor || "var(--text-primary)" }}>
        {value}
      </span>
    </div>
  );
}

function formatUptime(seconds) {
  if (!seconds || seconds < 0) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  if (h < 24) return `${h}h${rm ? ` ${rm}m` : ""}`;
  const d = Math.floor(h / 24);
  const rh = h % 24;
  return `${d}d${rh ? ` ${rh}h` : ""}`;
}

function fmtRel(iso) {
  if (!iso) return "—";
  try {
    const dt = new Date(iso);
    const diff = (Date.now() - dt.getTime()) / 1000;
    if (diff < 60) return `${Math.round(diff)}s atrás`;
    if (diff < 3600) return `${Math.round(diff / 60)}min atrás`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h atrás`;
    return `${Math.round(diff / 86400)}d atrás`;
  } catch {
    return iso.slice(0, 16);
  }
}
