/* PresidenteExecutivo.jsx — Cérebro Executivo V10.

   Substitui o miolo dashboard do Presidente IA. Tudo monetizado.
   Consome GET /api/presidente-ia/executive.
   8 blocos: SCORE / RISCOS / OPORTUNIDADES / PREVISÃO 30d /
   DINHEIRO EM RISCO / DINHEIRO RECUPERÁVEL / 5 AÇÕES / SURPRESAS. */
import React, { useEffect, useState, useMemo } from "react";
import { api } from "@/lib/apiClient";
import {
  AlertTriangle, TrendingUp, TrendingDown, DollarSign, Zap,
  Target, Eye, RefreshCw, ShieldAlert, Wallet,
  Sparkles, Activity, ChevronRight,
} from "lucide-react";
import ScoreRecoveryBlock from "./ScoreRecoveryBlock";

const COLORS = {
  purple: "#4b1d7a", purpleLight: "#6d28d9",
  orange: "#f28c28", green: "#237a4b", greenLight: "#10b981",
  red: "#b42318", redLight: "#ef4444",
  amber: "#d97706", blue: "#0891b2", slate: "#64748b",
  border: "#e2e8f0", bg: "#fafbfc",
};

const STATUS_COLOR = {
  saudavel: COLORS.green, atencao: COLORS.amber,
  alerta: COLORS.orange, critico: COLORS.red,
};

const PRIO_COLOR = {
  ALTA: COLORS.red, "MÉDIA": COLORS.amber, BAIXA: COLORS.slate,
};

const brl = (v) => {
  if (v == null || isNaN(v)) return "R$ 0";
  const n = Number(v);
  if (Math.abs(n) >= 1000) {
    return `R$ ${n.toLocaleString("pt-BR", { maximumFractionDigits: 0 })}`;
  }
  return `R$ ${n.toLocaleString("pt-BR", { minimumFractionDigits: 2,
                                              maximumFractionDigits: 2 })}`;
};

export default function PresidenteExecutivo() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.get("/api/presidente-ia/executive");
      setData(r);
    } catch (e) {
      setErr(e?.message || "Falha ao carregar relatório executivo");
    } finally { setLoading(false); }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await api.get("/api/presidente-ia/executive");
        if (!cancelled) setData(r);
      } catch (e) {
        if (!cancelled) setErr(
          e?.message || "Falha ao carregar relatório executivo");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // iter241 — recarrega quando o ScoreRecoveryBlock executa/reverte
  useEffect(() => {
    const handler = () => { load(); };
    window.addEventListener("president-score-updated", handler);
    return () => window.removeEventListener("president-score-updated", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading && !data) return <ExecSkeleton />;
  if (err && !data) {
    return (
      <div data-testid="pres-exec-error" style={{
        background: "#fef2f2", color: COLORS.red, padding: 16,
        borderRadius: 10, fontWeight: 700,
      }}>{err}</div>
    );
  }
  if (!data) return null;

  return (
    <div data-testid="presidente-executivo" style={{
      display: "flex", flexDirection: "column", gap: 16,
    }}>
      {/* Header executivo */}
      <ExecHeader data={data} loading={loading} onReload={load} />

      {/* iter241 — Card de Score Recovery (limpa lixo histórico) */}
      <ScoreRecoveryBlock />

      {/* Bloco 1: PRESIDENT SCORE */}
      <PresidentScoreBlock score={data.president_score}
                              ctx={data.contexto_financeiro} />

      {/* Bloco 2: PREVISÃO 30d */}
      <PrevisaoBlock previsao={data.previsao_30d}
                       ctx={data.contexto_financeiro} />

      {/* Linha — Dinheiro em Risco × Recuperável */}
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
                      gap: 14 }}>
        <DinheiroBlock title="DINHEIRO EM RISCO"
                          icon={TrendingDown}
                          color={COLORS.red}
                          block={data.dinheiro_em_risco}
                          testid="dinheiro-em-risco" />
        <DinheiroBlock title="DINHEIRO RECUPERÁVEL"
                          icon={TrendingUp}
                          color={COLORS.green}
                          block={data.dinheiro_recuperavel}
                          testid="dinheiro-recuperavel" />
      </div>

      {/* Bloco 5 AÇÕES PRESIDENCIAIS */}
      <AcoesBlock acoes={data.acoes_presidenciais} />

      {/* Riscos × Oportunidades */}
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
                      gap: 14 }}>
        <RiscosBlock riscos={data.riscos_criticos} />
        <OportunidadesBlock opps={data.oportunidades} />
      </div>

      {/* Surpresas */}
      <SurpresasBlock surpresas={data.surpresas} />

      {/* Fontes (footer técnico discreto) */}
      <FontesFooter fontes={data.fontes} elapsed={data.elapsed_ms}
                       generated={data.generated_at} />
    </div>
  );
}

// ───────────── Header ─────────────
function ExecHeader({ data, loading, onReload }) {
  const s = data.president_score || {};
  const color = STATUS_COLOR[s.status] || COLORS.purple;
  return (
    <div style={{
      display: "flex", justifyContent: "space-between",
      alignItems: "center", flexWrap: "wrap", gap: 12,
      padding: "12px 16px",
      background: `linear-gradient(135deg, ${COLORS.purple} 0%, #2d0f4a 100%)`,
      borderRadius: 14, color: "white",
    }} data-testid="exec-header">
      <div>
        <div style={{ fontSize: 10, fontWeight: 800, opacity: .85,
                        textTransform: "uppercase", letterSpacing: 1.2 }}>
          Cérebro Executivo · V10
        </div>
        <div style={{ fontSize: 20, fontWeight: 800, marginTop: 2 }}>
          O que você precisa decidir hoje
        </div>
        <div style={{ fontSize: 11, opacity: .8, marginTop: 4 }}>
          {data.contexto_financeiro?.clientes_ativos?.toLocaleString("pt-BR")}
          {" "}contratos ativos · MRR{" "}
          <strong>{brl(data.contexto_financeiro?.mrr_atual_brl)}</strong>
          {" "}· Ticket médio{" "}
          <strong>{brl(data.contexto_financeiro?.ticket_medio_brl)}</strong>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{
          background: `${color}25`, border: `1px solid ${color}`,
          padding: "8px 16px", borderRadius: 10, textAlign: "center",
        }} data-testid="exec-score-badge">
          <div style={{ fontSize: 26, fontWeight: 900, color: "white",
                          lineHeight: 1 }}>{s.score ?? "—"}</div>
          <div style={{ fontSize: 9, fontWeight: 800,
                          textTransform: "uppercase", letterSpacing: 1,
                          marginTop: 4, opacity: .9 }}>{s.status}</div>
        </div>
        <button onClick={onReload} disabled={loading}
                 data-testid="exec-reload"
                 style={{
                   background: "rgba(255,255,255,0.15)",
                   border: "1px solid rgba(255,255,255,0.3)",
                   color: "white", padding: "8px 12px",
                   borderRadius: 8, fontWeight: 700, fontSize: 12,
                   cursor: "pointer", display: "flex",
                   alignItems: "center", gap: 6,
                 }}>
          <RefreshCw size={12} style={{
            animation: loading ? "spin 1s linear infinite" : "none" }} />
          Recalcular
        </button>
      </div>
      <style>{`
        @keyframes spin { from{transform:rotate(0)} to{transform:rotate(360deg)} }
      `}</style>
    </div>
  );
}

// ───────────── Bloco 1: PRESIDENT SCORE ─────────────
function PresidentScoreBlock({ score, ctx }) {
  if (!score) return null;
  const color = STATUS_COLOR[score.status] || COLORS.purple;
  return (
    <Card icon={Activity} title="PRESIDENT_SCORE · Saúde executiva"
            color={color} testid="block-president-score">
      <div style={{ display: "grid",
                      gridTemplateColumns: "200px 1fr",
                      gap: 20, alignItems: "center" }}>
        <Gauge score={score.score} color={color} />
        <div>
          <div style={{ fontSize: 12, color: COLORS.slate,
                          fontWeight: 700, marginBottom: 8 }}>
            COMPONENTES (8 áreas)
          </div>
          <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(4, 1fr)",
                          gap: 6 }}>
            {Object.entries(score.components).map(([k, v]) => (
              <div key={k} style={{
                background: COLORS.bg, borderRadius: 6,
                padding: "6px 8px", border: `1px solid ${COLORS.border}`,
              }} data-testid={`score-comp-${k}`}>
                <div style={{ fontSize: 9, color: COLORS.slate,
                                fontWeight: 700, textTransform: "uppercase",
                                letterSpacing: .5 }}>{k}</div>
                <div style={{ fontSize: 15, fontWeight: 800,
                                color: v < 60 ? COLORS.red
                                      : v < 80 ? COLORS.amber : COLORS.green
                              }}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 10, fontSize: 11, color: COLORS.slate }}>
            <strong>Piores drivers:</strong>{" "}
            {score.piores_drivers.map(d =>
              `${d.area} (${d.score})`).join(" · ")}
          </div>
        </div>
      </div>
    </Card>
  );
}

function Gauge({ score, color }) {
  const pct = Math.max(0, Math.min(100, score));
  return (
    <div style={{ position: "relative", width: 180, height: 180,
                    margin: "0 auto" }}>
      <svg viewBox="0 0 100 100" style={{
        transform: "rotate(-90deg)", width: "100%", height: "100%" }}>
        <circle cx="50" cy="50" r="42" fill="none"
                 stroke="#f1f5f9" strokeWidth="10" />
        <circle cx="50" cy="50" r="42" fill="none"
                 stroke={color} strokeWidth="10" strokeLinecap="round"
                 strokeDasharray={`${(pct / 100) * 264} 264`}
                 style={{ transition: "stroke-dasharray .8s ease" }} />
      </svg>
      <div style={{
        position: "absolute", inset: 0, display: "flex",
        flexDirection: "column", alignItems: "center",
        justifyContent: "center",
      }}>
        <div style={{ fontSize: 38, fontWeight: 900, color,
                        lineHeight: 1 }}>{pct}</div>
        <div style={{ fontSize: 10, color: COLORS.slate,
                        fontWeight: 700, textTransform: "uppercase",
                        letterSpacing: 1, marginTop: 4 }}>de 100</div>
      </div>
    </div>
  );
}

// ───────────── Bloco 2: PREVISÃO 30d ─────────────
function PrevisaoBlock({ previsao, ctx }) {
  if (!previsao) return null;
  const riskColor = previsao.risco_operacional === "ALTO" ? COLORS.red
    : previsao.risco_operacional === "MÉDIO" ? COLORS.amber : COLORS.green;
  return (
    <Card icon={Eye} title="PREVISÃO EXECUTIVA · próximos 30 dias"
            color={COLORS.blue} testid="block-previsao">
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                      gap: 10, marginBottom: 12 }}>
        <MetricBig label="Receita prevista"
                     value={brl(previsao.receita_prevista_brl)}
                     color={COLORS.green} testid="prev-receita" />
        <MetricBig label="Churn previsto"
                     value={`${previsao.churn_previsto_qty} clientes`}
                     sub={`- ${brl(previsao.churn_previsto_brl)}`}
                     color={COLORS.red} testid="prev-churn" />
        <MetricBig label="Crescimento previsto"
                     value={`+${previsao.crescimento_previsto_qty} clientes`}
                     sub={`+ ${brl(previsao.crescimento_previsto_brl)}`}
                     color={COLORS.green} testid="prev-cresc" />
        <MetricBig label="Risco operacional"
                     value={previsao.risco_operacional}
                     color={riskColor} testid="prev-risco-op" />
      </div>
      <div style={{
        background: `${COLORS.blue}08`, borderLeft: `3px solid ${COLORS.blue}`,
        padding: 10, borderRadius: 6, fontSize: 12, color: "#0f172a",
        lineHeight: 1.55,
      }} data-testid="prev-causal">
        <strong style={{ color: COLORS.blue }}>POR QUÊ:</strong>{" "}
        {previsao.explicacao_causal}
      </div>
    </Card>
  );
}

// ───────────── Bloco Dinheiro (em risco / recuperável) ─────────────
function DinheiroBlock({ title, icon, color, block, testid }) {
  if (!block) return null;
  return (
    <Card icon={icon} title={title} color={color} testid={testid}>
      <div style={{
        background: `${color}10`, padding: 12, borderRadius: 8,
        marginBottom: 12, textAlign: "center",
      }}>
        <div style={{ fontSize: 10, fontWeight: 800, color,
                        textTransform: "uppercase", letterSpacing: 1 }}>
          Total
        </div>
        <div style={{ fontSize: 30, fontWeight: 900, color,
                        lineHeight: 1, marginTop: 4 }}>
          {brl(block.total_brl)}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {Object.entries(block.breakdown || {}).map(([k, v]) => {
          const titulo = k.replace(/_/g, " ");
          return (
            <div key={k} style={{
              padding: 8, borderRadius: 6, background: COLORS.bg,
              border: `1px solid ${COLORS.border}`,
            }} data-testid={`bucket-${k}`}>
              <div style={{ display: "flex",
                              justifyContent: "space-between",
                              alignItems: "baseline", gap: 8 }}>
                <span style={{ fontSize: 11, fontWeight: 700,
                                color: "#0f172a",
                                textTransform: "capitalize" }}>
                  {titulo}
                </span>
                <span style={{ fontSize: 14, fontWeight: 800, color }}>
                  {brl(v.brl)}
                </span>
              </div>
              {(v.evidencia || v.metodo) && (
                <div style={{ fontSize: 10, color: COLORS.slate,
                                marginTop: 3, lineHeight: 1.4 }}>
                  {v.evidencia && (
                    <div><strong>Evidência:</strong> {v.evidencia}</div>
                  )}
                  {v.metodo && (
                    <div><strong>Método:</strong> {v.metodo}</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ───────────── 5 AÇÕES PRESIDENCIAIS ─────────────
function AcoesBlock({ acoes }) {
  return (
    <Card icon={Zap} title="5 AÇÕES PRESIDENCIAIS · executar agora"
            color={COLORS.purple} testid="block-acoes">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {acoes.map((a, i) => (
          <div key={i} style={{
            display: "grid",
            gridTemplateColumns: "auto 1fr auto auto",
            gap: 10, alignItems: "center",
            padding: "10px 12px",
            borderLeft: `4px solid ${PRIO_COLOR[a.prioridade] || COLORS.slate}`,
            background: COLORS.bg, borderRadius: 6,
          }} data-testid={`acao-${i + 1}`}>
            <div style={{
              width: 28, height: 28, borderRadius: "50%",
              background: COLORS.purple, color: "white",
              display: "flex", alignItems: "center",
              justifyContent: "center", fontSize: 13, fontWeight: 900,
            }}>{i + 1}</div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700,
                              color: "#0f172a", lineHeight: 1.4 }}>
                {a.acao}
              </div>
              <div style={{ fontSize: 10, color: COLORS.slate,
                              marginTop: 3, lineHeight: 1.4 }}>
                {a.justificativa}
              </div>
            </div>
            <div style={{ textAlign: "right", minWidth: 90 }}>
              <div style={{ fontSize: 9, fontWeight: 800,
                              color: COLORS.slate,
                              textTransform: "uppercase" }}>Impacto</div>
              <div style={{ fontSize: 15, fontWeight: 800,
                              color: COLORS.green }}>{brl(a.impacto_brl)}</div>
            </div>
            <div style={{
              display: "flex", flexDirection: "column", gap: 3,
              alignItems: "flex-end",
            }}>
              <span style={{
                padding: "2px 8px", borderRadius: 4, fontSize: 9,
                fontWeight: 800, letterSpacing: .5,
                background: `${PRIO_COLOR[a.prioridade] || COLORS.slate}15`,
                color: PRIO_COLOR[a.prioridade] || COLORS.slate,
              }}>{a.prioridade}</span>
              <span style={{ fontSize: 9, color: COLORS.slate,
                              fontWeight: 700 }}>
                Esforço: {a.esforco}
              </span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ───────────── RISCOS ─────────────
function RiscosBlock({ riscos }) {
  return (
    <Card icon={ShieldAlert} title="RISCOS CRÍTICOS"
            color={COLORS.red} testid="block-riscos">
      {riscos.length === 0 ? (
        <Empty msg="Nenhum risco crítico identificado." />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {riscos.map((r, i) => (
            <div key={i} style={{
              padding: 10, borderRadius: 6,
              background: `${COLORS.red}06`,
              borderLeft: `3px solid ${COLORS.red}`,
            }} data-testid={`risco-${i}`}>
              <div style={{ display: "flex",
                              justifyContent: "space-between",
                              gap: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 800,
                                color: "#0f172a" }}>{r.titulo}</span>
                <span style={{ fontSize: 13, fontWeight: 800,
                                color: COLORS.red, whiteSpace: "nowrap" }}>
                  {brl(r.impacto_brl)}
                </span>
              </div>
              <div style={{ fontSize: 10, color: COLORS.slate,
                              marginTop: 4, lineHeight: 1.4 }}>
                <div><strong>Evidência:</strong> {r.evidencia}</div>
                <div><strong>Causa:</strong> {r.causa}</div>
                <div style={{ marginTop: 3, color: "#0f172a" }}>
                  <strong>→ Ação:</strong> {r.acao}
                </div>
              </div>
              <div style={{ fontSize: 9, color: COLORS.slate,
                              marginTop: 4, fontWeight: 700 }}>
                Probabilidade: {r.probabilidade_pct}%
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ───────────── OPORTUNIDADES ─────────────
function OportunidadesBlock({ opps }) {
  return (
    <Card icon={Target} title="OPORTUNIDADES IMEDIATAS"
            color={COLORS.green} testid="block-oportunidades">
      {opps.length === 0 ? (
        <Empty msg="Nenhuma oportunidade quantificável agora." />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {opps.map((o, i) => (
            <div key={i} style={{
              padding: 10, borderRadius: 6,
              background: `${COLORS.green}06`,
              borderLeft: `3px solid ${COLORS.green}`,
            }} data-testid={`opp-${i}`}>
              <div style={{ display: "flex",
                              justifyContent: "space-between",
                              gap: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 800,
                                color: "#0f172a" }}>{o.titulo}</span>
                <span style={{ fontSize: 13, fontWeight: 800,
                                color: COLORS.green, whiteSpace: "nowrap" }}>
                  +{brl(o.ganho_brl_mensal)}
                  <span style={{ fontSize: 9, color: COLORS.slate,
                                  fontWeight: 600 }}> /mês</span>
                </span>
              </div>
              <div style={{ fontSize: 10, color: COLORS.slate,
                              marginTop: 4, lineHeight: 1.4,
                              display: "flex", alignItems: "flex-start",
                              gap: 4 }}>
                <ChevronRight size={11} style={{
                  flexShrink: 0, marginTop: 1, color: COLORS.green }} />
                <span><strong>Ação:</strong> {o.acao}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ───────────── SURPRESAS ─────────────
function SurpresasBlock({ surpresas }) {
  return (
    <Card icon={Sparkles} title="SURPRESAS EXECUTIVAS · fatos que você pode não ter visto"
            color={COLORS.orange} testid="block-surpresas">
      {surpresas.length === 0 ? (
        <Empty msg="Nenhuma surpresa relevante detectada nesta varredura." />
      ) : (
        <div style={{ display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                        gap: 8 }}>
          {surpresas.map((s, i) => (
            <div key={i} style={{
              padding: 10, borderRadius: 6,
              background: `${COLORS.orange}08`,
              border: `1px solid ${COLORS.orange}30`,
            }} data-testid={`surpresa-${i}`}>
              <div style={{ display: "flex",
                              justifyContent: "space-between",
                              gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 9, fontWeight: 800,
                                color: COLORS.orange,
                                textTransform: "uppercase",
                                letterSpacing: .5 }}>{s.categoria}</span>
                {s.impacto_brl > 0 && (
                  <span style={{ fontSize: 11, fontWeight: 800,
                                  color: COLORS.orange }}>
                    {brl(s.impacto_brl)}
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#0f172a",
                              lineHeight: 1.4 }}>{s.fato}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ───────────── Fontes / footer ─────────────
function FontesFooter({ fontes, elapsed, generated }) {
  const ausenteCount = fontes?.ausentes?.length || 0;
  return (
    <div style={{
      display: "flex", justifyContent: "space-between",
      fontSize: 10, color: COLORS.slate, padding: "8px 12px",
      borderTop: `1px dashed ${COLORS.border}`, gap: 8,
      flexWrap: "wrap",
    }} data-testid="exec-fontes-footer">
      <span>
        Gerado em {elapsed}ms · {new Date(generated).toLocaleString("pt-BR")}
      </span>
      <span>
        Fontes usadas: <strong>{fontes?.usadas?.length || 0}</strong>
        {ausenteCount > 0 && (
          <> · ausentes: <strong style={{ color: COLORS.amber }}>
            {ausenteCount}</strong></>
        )}
      </span>
    </div>
  );
}

// ───────────── Atoms ─────────────
function Card({ icon: Icon, title, color, children, testid }) {
  return (
    <div data-testid={testid} style={{
      background: "white", border: `1px solid ${COLORS.border}`,
      borderRadius: 12, padding: 14, display: "flex",
      flexDirection: "column", gap: 10,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{
          width: 30, height: 30, borderRadius: 8,
          background: `${color}15`, color,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}><Icon size={16} /></div>
        <h3 style={{ margin: 0, fontSize: 13, fontWeight: 800,
                       color: "#0f172a", textTransform: "uppercase",
                       letterSpacing: .6 }}>{title}</h3>
      </div>
      {children}
    </div>
  );
}

function MetricBig({ label, value, sub, color, testid }) {
  return (
    <div data-testid={testid} style={{
      background: COLORS.bg, border: `1px solid ${COLORS.border}`,
      borderRadius: 8, padding: 10,
    }}>
      <div style={{ fontSize: 9, color: COLORS.slate, fontWeight: 800,
                      textTransform: "uppercase", letterSpacing: .5 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 800, color,
                      marginTop: 4 }}>{value}</div>
      {sub && (
        <div style={{ fontSize: 11, color, fontWeight: 700,
                        marginTop: 2 }}>{sub}</div>
      )}
    </div>
  );
}

function Empty({ msg }) {
  return (
    <div style={{ padding: 18, textAlign: "center",
                    fontSize: 12, color: COLORS.slate }}>{msg}</div>
  );
}

function ExecSkeleton() {
  return (
    <div data-testid="exec-skeleton" style={{
      padding: 40, textAlign: "center", color: COLORS.slate,
      background: "white", border: `1px solid ${COLORS.border}`,
      borderRadius: 12,
    }}>
      <Wallet size={36} color={COLORS.purple} style={{
        margin: "0 auto", animation: "pulse 1.5s ease infinite" }} />
      <div style={{ fontSize: 13, fontWeight: 700, marginTop: 12 }}>
        Calculando relatório executivo monetizado…
      </div>
      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
      `}</style>
    </div>
  );
}
