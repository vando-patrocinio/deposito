/**
 * CtoCommandCenter.jsx — Sprint 16 (Painel CTO Frontend)
 * Centro de Comando IA: 4 cards consumindo /api/motor-ia/*
 *   1. Leader        — quem é o líder do scheduler agora
 *   2. Feedback      — stats por action_type (success_rate, factor)
 *   3. Predictions   — churn + revenue + ticket_demand
 *   4. Learnings     — snapshots recentes do feedback loop
 *
 * Polling 10s. Aceitando 401/403 gracefully.
 */
import React, { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from "recharts";

const API = process.env.REACT_APP_BACKEND_URL || "";


async function fetchJson(path, init) {
  try {
    // P0.5 — usa chave correta `ponto_token` (não `token`).
    const token = localStorage.getItem("ponto_token");
    const headers = {
      ...(init?.headers || {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
    if (init?.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const r = await fetch(`${API}${path}`, { ...init, headers });
    if (!r.ok) return { __error: r.status };
    return await r.json();
  } catch (e) {
    return { __error: e.message };
  }
}


function Card({ title, subtitle, children, testid }) {
  return (
    <div
      data-testid={testid}
      style={{
        background: "#0f172a",
        border: "1px solid #1e293b",
        borderRadius: 12,
        padding: 20,
        color: "#e2e8f0",
        minHeight: 240,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 16, color: "#7dd3fc" }}>{title}</h3>
        {subtitle && (
          <span style={{ fontSize: 11, color: "#64748b" }}>{subtitle}</span>
        )}
      </div>
      {children}
    </div>
  );
}


function LeaderCard() {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await fetchJson("/api/motor-ia/leader");
      if (alive) setData(r);
    };
    tick();
    const t = setInterval(tick, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!data) return <Card title="Leader do Scheduler" testid="cto-leader-card">Carregando…</Card>;
  if (data.__error)
    return <Card title="Leader do Scheduler" testid="cto-leader-card">
      <span style={{ color: "#f87171" }}>HTTP {data.__error}</span>
    </Card>;
  const holder = data.holder || "(nenhum)";
  const isMe = data.is_me;
  return (
    <Card title="Leader do Scheduler"
            subtitle={isMe ? "(este worker)" : ""}
            testid="cto-leader-card">
      <div style={{ fontSize: 13, lineHeight: 1.7 }}>
        <div><b>Host/PID:</b> <code data-testid="leader-host">
          {data.host || "—"}</code></div>
        <div><b>Holder:</b> <code style={{ wordBreak: "break-all" }}>
          {holder}</code></div>
        <div><b>Expira em:</b> {data.expires_at || "—"}</div>
      </div>
    </Card>
  );
}


function FeedbackCard() {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await fetchJson("/api/motor-ia/feedback");
      if (alive) setData(r);
    };
    tick();
    const t = setInterval(tick, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!data) return <Card title="Feedback Loop" testid="cto-feedback-card">Carregando…</Card>;
  if (data.__error)
    return <Card title="Feedback Loop" testid="cto-feedback-card">
      <span style={{ color: "#f87171" }}>HTTP {data.__error}</span>
    </Card>;
  const stats = data.stats || {};
  const rows = Object.entries(stats);
  return (
    <Card title="Feedback Loop" subtitle={`${rows.length} action_types`}
            testid="cto-feedback-card">
      <table style={{ width: "100%", fontSize: 12,
                        borderCollapse: "collapse" }}>
        <thead><tr style={{ color: "#94a3b8" }}>
          <th align="left">action_type</th>
          <th align="right">success</th>
          <th align="right">factor</th>
          <th align="right">total</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={4} style={{ color: "#64748b",
                                              padding: 12 }}>
              Sem outcomes suficientes ainda.
            </td></tr>
          )}
          {rows.map(([at, s]) => (
            <tr key={at} data-testid={`feedback-row-${at}`}>
              <td>{at}</td>
              <td align="right">{Math.round((s.success_rate||0) * 100)}%</td>
              <td align="right"
                  style={{ color: s.factor >= 1 ? "#34d399"
                                                 : "#fb923c" }}>
                {s.factor?.toFixed(2)}×
              </td>
              <td align="right">{s.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}


function PredictionsCard() {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await fetchJson("/api/motor-ia/predictions");
      if (alive) setData(r);
    };
    tick();
    const t = setInterval(tick, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!data) return <Card title="Predições" testid="cto-predictions-card">Carregando…</Card>;
  if (data.__error)
    return <Card title="Predições" testid="cto-predictions-card">
      <span style={{ color: "#f87171" }}>HTTP {data.__error}</span>
    </Card>;
  const c = data.churn || {};
  const r = data.revenue || {};
  const t = data.ticket_demand || {};
  return (
    <Card title="Predições"
            subtitle={`${c.kind ? "✓ churn" : "—"} · ${r.kind ? "✓ MRR" : "—"} · ${t.kind ? "✓ tickets" : "—"}`}
            testid="cto-predictions-card">
      <div style={{ fontSize: 12, lineHeight: 1.6 }}>
        <div><b style={{ color: "#fbbf24" }}>Churn risk</b> ({c.model || "—"}):
          {" "}<span data-testid="churn-count">{c.count ?? 0}</span> clientes</div>
        <div><b style={{ color: "#34d399" }}>Receita</b> ({r.model || "—"}):
          {" "}{(r.items || []).length} empresas projetadas</div>
        <div><b style={{ color: "#60a5fa" }}>Tickets 7d</b> ({t.model || "—"}):
          {" "}
          {(t.items || []).slice(0, 2).map((it, i) =>
            <span key={i}> {it.forecast_7d}</span>
          )}
        </div>
        <hr style={{ borderColor: "#1e293b", margin: "10px 0" }} />
        <div style={{ color: "#64748b", fontSize: 11 }}>
          Última atualização: {c.generated_at?.slice(0, 19) || "—"}
        </div>
      </div>
    </Card>
  );
}


function LearningsCard() {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await fetchJson("/api/motor-ia/learnings?limit=10");
      if (alive) setData(r);
    };
    tick();
    const t = setInterval(tick, 20000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!data) return <Card title="Aprendizados Recentes" testid="cto-learnings-card">Carregando…</Card>;
  if (data.__error)
    return <Card title="Aprendizados Recentes" testid="cto-learnings-card">
      <span style={{ color: "#f87171" }}>HTTP {data.__error}</span>
    </Card>;
  const items = data.items || [];
  return (
    <Card title="Aprendizados Recentes" subtitle={`${data.count || 0} snapshots`}
            testid="cto-learnings-card">
      <div style={{ fontSize: 12, lineHeight: 1.6, maxHeight: 200,
                      overflowY: "auto" }}>
        {items.length === 0 && (
          <div style={{ color: "#64748b" }}>Nenhum learning ainda.</div>
        )}
        {items.slice(0, 6).map((it, i) => {
          const deltas = it.deltas || {};
          const changed = Object.entries(deltas).filter(
            ([_, d]) => Math.abs(d.delta || 0) > 0);
          return (
            <div key={it.id || i}
                  data-testid={`learning-row-${i}`}
                  style={{ borderBottom: "1px solid #1e293b",
                             padding: "6px 0" }}>
              <div style={{ color: "#94a3b8", fontSize: 10 }}>
                {(it.generated_at || "").slice(0, 19)}
              </div>
              {changed.length === 0 ? (
                <div style={{ color: "#64748b" }}>sem variação</div>
              ) : (
                changed.map(([at, d]) => (
                  <div key={at}>
                    <code>{at}</code>:{" "}
                    {d.factor_before?.toFixed(2)} →{" "}
                    <b style={{ color: d.delta > 0 ? "#34d399"
                                                       : "#f87171" }}>
                      {d.factor_after?.toFixed(2)}
                    </b>
                  </div>
                ))
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}


function FeedbackChart() {
  const [stats, setStats] = useState({});
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await fetchJson("/api/motor-ia/feedback");
      if (alive && !r.__error) setStats(r.stats || {});
    };
    tick();
    const t = setInterval(tick, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  const data = Object.entries(stats).map(([at, s]) => ({
    action_type: at,
    success: Math.round((s.success_rate || 0) * 100),
    factor: s.factor || 0,
  }));
  return (
    <Card title="Feedback (gráfico)" testid="cto-feedback-chart">
      <div style={{ width: "100%", height: 180 }}>
        {data.length > 0 ? (
          <ResponsiveContainer>
            <BarChart data={data}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="action_type" stroke="#64748b"
                       tick={{ fontSize: 10 }} />
              <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
              <Tooltip wrapperStyle={{ background: "#0f172a" }} />
              <Bar dataKey="success" fill="#34d399" name="success %" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ color: "#64748b", padding: 20 }}>
            Sem dados ainda.
          </div>
        )}
      </div>
    </Card>
  );
}


function MLChurnCard() {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await fetchJson("/api/motor-ia/ml/churn");
      if (alive) setData(r);
    };
    tick();
    const t = setInterval(tick, 60000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!data) return <Card title="Churn ML (IsolationForest)" testid="cto-ml-churn-card">Carregando…</Card>;
  if (data.__error)
    return <Card title="Churn ML (IsolationForest)" testid="cto-ml-churn-card">
      <span style={{ color: "#f87171" }}>HTTP {data.__error}</span>
    </Card>;
  if (data.error)
    return <Card title="Churn ML (IsolationForest)" testid="cto-ml-churn-card">
      <span style={{ color: "#fbbf24" }}>
        {data.error} — rode <code>POST /api/motor-ia/ml/run</code>
      </span>
    </Card>;
  const items = (data.items || []).slice(0, 5);
  return (
    <Card title="Churn ML (IsolationForest)"
            subtitle={`${data.samples_observed || 0} samples`}
            testid="cto-ml-churn-card">
      <table style={{ width: "100%", fontSize: 12,
                        borderCollapse: "collapse" }}>
        <thead><tr style={{ color: "#94a3b8" }}>
          <th align="left">subscriber_id</th>
          <th align="right">risk %</th>
          <th align="right">anomaly</th>
        </tr></thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={i} data-testid={`ml-churn-row-${i}`}>
              <td><code style={{ fontSize: 10 }}>{it.subscriber_id}</code></td>
              <td align="right" style={{ color: "#f87171" }}>
                {it.risk_pct}%
              </td>
              <td align="right">{it.anomaly_score}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}


function ThresholdsCard() {
  const [data, setData] = useState(null);
  const [tuning, setTuning] = useState(false);
  useEffect(() => {
    let alive = true;
    (async () => {
      const r = await fetchJson("/api/motor-ia/thresholds");
      if (alive) setData(r);
    })();
    return () => { alive = false; };
  }, []);
  const runAutoTune = async () => {
    setTuning(true);
    await fetchJson("/api/motor-ia/thresholds/auto-tune",
                      { method: "POST" });
    const r = await fetchJson("/api/motor-ia/thresholds");
    setData(r);
    setTuning(false);
  };
  if (!data) return <Card title="Thresholds das Regras" testid="cto-thresholds-card">Carregando…</Card>;
  if (data.__error)
    return <Card title="Thresholds das Regras" testid="cto-thresholds-card">
      <span style={{ color: "#f87171" }}>HTTP {data.__error}</span>
    </Card>;
  const current = data.current || {};
  return (
    <Card title="Thresholds das Regras"
            subtitle={`${Object.keys(current).length} regras`}
            testid="cto-thresholds-card">
      <div style={{ fontSize: 12, lineHeight: 1.7 }}>
        {Object.entries(current).map(([rule, cfg]) => (
          <div key={rule} data-testid={`threshold-${rule}`}
                 style={{ borderBottom: "1px solid #1e293b",
                            padding: "4px 0" }}>
            <b style={{ color: "#7dd3fc" }}>{rule}</b>:
            {Object.entries(cfg).map(([k, v]) => (
              <span key={k} style={{ marginLeft: 8 }}>
                <code style={{ color: "#fbbf24" }}>{k}={v}</code>
              </span>
            ))}
          </div>
        ))}
        <button
          data-testid="run-auto-tune-btn"
          onClick={runAutoTune}
          disabled={tuning}
          style={{
            marginTop: 12, padding: "6px 12px",
            background: "#0ea5e9", color: "#fff", border: "none",
            borderRadius: 6, cursor: tuning ? "wait" : "pointer",
            fontSize: 12,
          }}>
          {tuning ? "Ajustando…" : "▶ Rodar Auto-Tune"}
        </button>
      </div>
    </Card>
  );
}


function ValidationAccuracyCard() {
  const [data, setData] = useState(null);
  const [running, setRunning] = useState(false);
  useEffect(() => {
    let alive = true;
    (async () => {
      const r = await fetchJson("/api/motor-ia/predictions/accuracy");
      if (alive) setData(r);
    })();
    return () => { alive = false; };
  }, []);
  const runValidate = async () => {
    setRunning(true);
    await fetchJson("/api/motor-ia/predictions/validate",
                      { method: "POST" });
    const r = await fetchJson("/api/motor-ia/predictions/accuracy");
    setData(r);
    setRunning(false);
  };
  if (!data) return <Card title="Acurácia das Predições" testid="cto-accuracy-card">Carregando…</Card>;
  if (data.__error)
    return <Card title="Acurácia das Predições" testid="cto-accuracy-card">
      <span style={{ color: "#f87171" }}>HTTP {data.__error}</span>
    </Card>;
  const rows = Object.entries(data || {});
  return (
    <Card title="Acurácia das Predições"
            subtitle={`${rows.length} modelos validados`}
            testid="cto-accuracy-card">
      <div style={{ fontSize: 12, lineHeight: 1.6 }}>
        {rows.length === 0 ? (
          <div style={{ color: "#64748b" }}>
            Nenhuma predição expirou ainda — não há validação possível.
            <br/><br/>
            <button onClick={runValidate}
                      data-testid="run-validate-btn"
                      disabled={running}
                      style={{
                        padding: "6px 12px", background: "#0ea5e9",
                        color: "#fff", border: "none",
                        borderRadius: 6, fontSize: 12,
                        cursor: running ? "wait" : "pointer",
                      }}>
              {running ? "Validando…" : "▶ Rodar Validation"}
            </button>
          </div>
        ) : rows.map(([k, v]) => (
          <div key={k} data-testid={`accuracy-row-${k}`}
                 style={{ borderBottom: "1px solid #1e293b",
                            padding: "4px 0" }}>
            <code style={{ color: "#a78bfa", fontSize: 10 }}>{k}</code>
            <div>n={v.n_validations}, precision=
              <b style={{ color: "#34d399" }}>
                {v.avg_precision_pct}%</b></div>
          </div>
        ))}
      </div>
    </Card>
  );
}


function OperacaoTeseCard() {
  const [op, setOp] = useState(null);
  const [running, setRunning] = useState(false);
  const [companyId, setCompanyId] = useState("");
  const refresh = async (opId) => {
    if (!opId) return;
    const r = await fetchJson(`/api/motor-ia/../operacao-tese/monitor/${opId}`);
    setOp(r);
  };
  const start = async () => {
    if (!companyId) return;
    setRunning(true);
    const r = await fetchJson("/api/operacao-tese/start", {
      method: "POST",
      body: JSON.stringify({
        company_id: companyId,
        dry_run: true,
        max_messages: 10,
      }),
    });
    if (r?.operation_id) {
      await refresh(r.operation_id);
    } else {
      setOp(r);
    }
    setRunning(false);
  };
  return (
    <Card title="Operação Tese Validada (R$)"
            subtitle={op?.recovered_BRL != null
              ? `R$ ${op.recovered_BRL?.toFixed(2) || 0} recuperados`
              : "não iniciada"}
            testid="cto-tese-card">
      <div style={{ fontSize: 12 }}>
        <input
          data-testid="tese-company-input"
          value={companyId}
          onChange={(e) => setCompanyId(e.target.value)}
          placeholder="company_id"
          style={{ width: "100%", padding: 6,
                     background: "#1e293b", border: "1px solid #334155",
                     color: "#e2e8f0", borderRadius: 4,
                     marginBottom: 6 }}
        />
        <button data-testid="tese-start-btn"
                  onClick={start}
                  disabled={running || !companyId}
                  style={{
                    padding: "6px 12px", background: "#dc2626",
                    color: "#fff", border: "none", borderRadius: 6,
                    fontSize: 12, cursor: running ? "wait" : "pointer",
                    width: "100%", marginBottom: 8,
                  }}>
          {running ? "Iniciando…" : "▶ Iniciar (DRY-RUN)"}
        </button>
        {op && !op.__error && (
          <div style={{ lineHeight: 1.8 }}>
            <div><b>Eligíveis:</b> {op.eligible_after_smartolt ?? "—"}</div>
            <div><b>Bloqueados SmartOLT:</b>
              {" "}{op.blocked_by_smartolt ?? "—"}</div>
            <div><b>Mensagens:</b> {op.messages_planned
              ?? op.messages_sent_or_planned ?? "—"}</div>
            <div><b>Pagamentos:</b> {op.payments_received ?? 0}</div>
            <div><b>R$ recuperados:</b>
              <span style={{ color: "#34d399" }}>
                {" "}{op.recovered_BRL?.toFixed(2) || "0.00"}
              </span></div>
            <div><b>ROI:</b> {op.roi_x ?? "—"}×</div>
          </div>
        )}
        {op?.__error && (
          <span style={{ color: "#f87171" }}>HTTP {op.__error}</span>
        )}
        {op?.error && (
          <div style={{ color: "#fbbf24", fontSize: 11 }}>
            {op.error}
            {op.pre_flight?.blockers && (
              <div style={{ marginTop: 4 }}>
                Blockers: {op.pre_flight.blockers.join(", ")}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}


export default function CtoCommandCenter() {
  return (
    <div data-testid="cto-command-center"
            style={{ padding: 24,
                       background: "#020617",
                       minHeight: "calc(100vh - 64px)" }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ color: "#e2e8f0", fontSize: 28, margin: 0 }}>
          Centro de Comando IA
        </h1>
        <p style={{ color: "#64748b", marginTop: 6 }}>
          Real-time. Polling 10-60s. Dados vindos diretamente de
          <code> /api/motor-ia/*</code>.
        </p>
      </div>
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
                      gap: 16 }}>
        <LeaderCard />
        <OperacaoTeseCard />
        <FeedbackCard />
        <FeedbackChart />
        <PredictionsCard />
        <MLChurnCard />
        <ThresholdsCard />
        <ValidationAccuracyCard />
        <LearningsCard />
      </div>
    </div>
  );
}
