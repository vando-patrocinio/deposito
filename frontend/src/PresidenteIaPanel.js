/* PresidenteIaPanel.js — Sistema Nervoso Corporativo (iter218)

   Substitui o painel "Conselho IA" antigo. Centro: Presidente IA.
   Orbital: 14 agentes. Cards: saúde, riscos, oportunidades, clientes
   em risco, rede, atendimento, comercial, universo Ligo, Conselho
   Executivo (CEO/COO/CTO/CFO/CPO + Estrategista).
*/
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import {
  Activity, AlertTriangle, BrainCircuit, CheckCircle2, ChevronDown,
  Clock, Coffee, DollarSign, Heart, LineChart, Megaphone, Network,
  RefreshCw, Settings, ShieldAlert, Sparkles, Target, TrendingUp,
  Users, Wallet, X, Zap,
} from "lucide-react";

const ORACLE = {
  purple: "#4b1d7a", orange: "#f28c28",
  green: "#237a4b", red: "#b42318",
  border: "#e2e8f0",
};

const HEALTH_COLOR = {
  saudavel: ORACLE.green,
  atencao: ORACLE.orange,
  alerta: "#dc6803",
  critico: ORACLE.red,
};

const RISK_LEVEL_COLOR = {
  critico: ORACLE.red,
  alto: ORACLE.orange,
  medio: "#d97706",
  baixo: "#64748b",
};

export default function PresidenteIaPanel() {
  const [data, setData] = useState(null);
  const [council, setCouncil] = useState(null);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [err, setErr] = useState("");
  const [showBriefing, setShowBriefing] = useState(false);

  const fetchAll = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api._client.get("/presidente-ia/dashboard");
      setData(r.data);
      const c = await api._client.get("/presidente-ia/conselho");
      setCouncil(c.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  };

  useEffect(() => { fetchAll(); }, []);

  const runScan = async () => {
    setScanning(true); setErr("");
    try {
      await api._client.post("/presidente-ia/scan");
      await fetchAll();
    } catch (e) { setErr(e.message); }
    setScanning(false);
  };

  const runLeoProactive = async () => {
    setScanning(true); setErr("");
    try {
      const r = await api._client.post(
        "/presidente-ia/leo/proactive");
      const d = r.data || {};
      setErr(`Leo Proativo: ${d.sent || 0} mensagem(ns) enviada(s), `
              + `${d.skipped_cooldown || 0} em cooldown, `
              + `${d.total_candidates || 0} candidato(s) total.`);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setScanning(false);
  };

  const regenerateCouncil = async () => {
    setLoading(true);
    try {
      const c = await api._client.get(
        "/presidente-ia/conselho?force=true");
      setCouncil(c.data);
    } catch (e) { setErr(e.message); }
    setLoading(false);
  };

  return (
    <div data-testid="presidente-ia-panel" style={{
      display: "flex", flexDirection: "column", gap: 20, padding: "0 4px",
    }}>
      <Header data={data} loading={loading} scanning={scanning}
                onScan={runScan} onRefresh={fetchAll}
                onBriefing={() => setShowBriefing(true)}
                onLeoProactive={runLeoProactive} />

      {showBriefing && (
        <BriefingModal onClose={() => setShowBriefing(false)} />
      )}

      {err && (
        <div data-testid="pres-error" style={{
          background: "#fef2f2", color: ORACLE.red, padding: "10px 14px",
          borderRadius: 8, fontSize: 13, fontWeight: 600,
        }}>{err}</div>
      )}

      {!data && !err && (
        <SkeletonLoader />
      )}

      {data && (
        <>
          {/* Sistema Nervoso — Presidente IA central + agentes orbitando */}
          <OrbitalMap agents={data.agents} health={data.health}
                        risks={data.risks} />

          {/* Linhas 1: Saúde + Riscos + Oportunidades */}
          <div style={grid3()}>
            <HealthCard health={data.health} />
            <RisksCard risks={data.risks} />
            <OpportunitiesCard opps={data.opportunities} />
          </div>

          {/* Linha 2: Rede + Atendimento + Comercial */}
          <div style={grid3()}>
            <StatCard title="Rede" icon={Network}
                        color="#1e40af"
                        items={[
                          { label: "CTOs", v: data.network.ctos },
                          { label: "CTOs críticas",
                            v: data.network.ctos_criticas,
                            warn: data.network.ctos_criticas > 0 },
                          { label: "ONUs offline",
                            v: data.network.onus_offline,
                            warn: data.network.onus_offline > 0 },
                          { label: "OLTs", v: data.network.olts },
                          { label: "Outages",
                            v: data.network.outages,
                            warn: data.network.outages > 0 },
                        ]} />
            <StatCard title="Atendimento" icon={Users}
                        color="#0891b2"
                        items={[
                          { label: "Tickets abertos",
                            v: data.attendance.tickets_abertos,
                            warn: data.attendance.tickets_abertos > 50 },
                          { label: "CSAT 30d",
                            v: data.attendance.csat_30d || "—",
                            suffix: data.attendance.csat_30d ? "/5" : "" },
                        ]} />
            <StatCard title="Comercial" icon={TrendingUp}
                        color={ORACLE.green}
                        items={[
                          { label: "Leads 30d",
                            v: data.commercial.leads_30d },
                          { label: "Conversões",
                            v: data.commercial.conversoes_30d },
                          { label: "Taxa", suffix: "%",
                            v: data.commercial.taxa_conversao_pct },
                        ]} />
          </div>

          {/* Linha 3: Universo Ligo + Clientes em risco */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                          gap: 14 }}>
            <UniversoLigoCard u={data.universo_ligo} />
            <ClientsAtRiskCard clients={data.clients_at_risk} />
          </div>

          {/* Conselho Executivo */}
          {council?.items && (
            <ConselhoExecutivo items={council.items}
                                  onRegenerate={regenerateCouncil} />
          )}
        </>
      )}
    </div>
  );
}

// ─────────────────── Header ───────────────────
function Header({ data, loading, scanning, onScan, onRefresh,
                     onBriefing, onLeoProactive }) {
  const score = data?.health?.score;
  const status = data?.health?.status;
  const color = HEALTH_COLOR[status] || ORACLE.purple;
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", flexWrap: "wrap",
      gap: 14, alignItems: "center",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{
          width: 52, height: 52, borderRadius: 14,
          background: `linear-gradient(135deg, ${ORACLE.purple}, #6d28d9)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 6px 20px rgba(75, 29, 122, .35)",
        }}>
          <BrainCircuit size={26} color="white" />
        </div>
        <div>
          <h1 style={{
            fontSize: 24, fontWeight: 800, margin: 0,
            letterSpacing: "-0.02em", color: "var(--text-primary)",
            display: "flex", alignItems: "center", gap: 10,
          }}>
            Presidente IA
            {score != null && (
              <span style={{
                fontSize: 12, fontWeight: 800, padding: "3px 10px",
                borderRadius: 16, background: `${color}15`, color,
                textTransform: "uppercase", letterSpacing: .5,
              }}>{score}/100 · {status}</span>
            )}
          </h1>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
            Sistema Nervoso Corporativo do SmartProv · Observa,
            entende, correlaciona, prevê, decide, age, aprende
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={onBriefing}
                 data-testid="pres-briefing-btn"
                 style={btnSec()}>
          <Coffee size={13} />
          Café com IA
        </button>
        <button onClick={onRefresh} disabled={loading || scanning}
                 data-testid="pres-refresh"
                 style={btnSec()}>
          <RefreshCw size={13}
            style={{
              animation: loading ? "spin 1s linear infinite" : "none",
            }} />
          Atualizar
        </button>
        <button onClick={onScan} disabled={loading || scanning}
                 data-testid="pres-scan-btn"
                 style={btnPrimary()}>
          <Zap size={13}
            style={{ animation: scanning ? "pulse 1s ease infinite" : "none" }} />
          {scanning ? "Varrendo…" : "Varredura agora"}
        </button>
        <button onClick={onLeoProactive} disabled={loading || scanning}
                 data-testid="pres-leo-proactive-btn"
                 style={{ ...btnPrimary(),
                            background: ORACLE.orange }}>
          <Sparkles size={13} />
          Leo Proativo
        </button>
      </div>
      <style>{`
        @keyframes spin { from {transform:rotate(0)} to {transform:rotate(360deg)} }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        @keyframes orbit-glow { 0%,100%{opacity:.5} 50%{opacity:1} }
      `}</style>
    </div>
  );
}

// ─────────────────── Orbital Map ───────────────────
function OrbitalMap({ agents, health, risks }) {
  const color = HEALTH_COLOR[health?.status] || ORACLE.purple;
  const totalRisk = risks?.total || 0;
  const size = 520;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 200;

  return (
    <div data-testid="orbital-map" style={{
      background: `radial-gradient(circle at center, rgba(75,29,122,0.08) 0%, transparent 70%), white`,
      border: `1px solid ${ORACLE.border}`,
      borderRadius: 16, padding: 24, position: "relative",
      overflow: "hidden",
    }}>
      <div style={{
        fontSize: 10, fontWeight: 800, color: "#64748b",
        textTransform: "uppercase", letterSpacing: .8,
        marginBottom: 8, textAlign: "center",
      }}>
        Sistema Nervoso · 14 agentes coordenados
      </div>
      <div style={{
        position: "relative", width: "100%", maxWidth: size,
        margin: "0 auto", height: size,
      }}>
        <svg viewBox={`0 0 ${size} ${size}`}
              style={{ position: "absolute", inset: 0, width: "100%",
                         height: "100%" }}>
          {/* Anéis decorativos */}
          {[radius * 1.0, radius * 0.7, radius * 0.45].map((r, i) => (
            <circle key={i} cx={cx} cy={cy} r={r}
                     fill="none"
                     stroke={`${color}${i === 0 ? "30" : "15"}`}
                     strokeWidth={i === 0 ? 1.5 : 0.7}
                     strokeDasharray={i === 0 ? "" : "4 6"} />
          ))}
          {/* Linhas dos agentes ao centro */}
          {agents.map((a, idx) => {
            const angle = (2 * Math.PI * idx) / agents.length - Math.PI / 2;
            const x = cx + radius * Math.cos(angle);
            const y = cy + radius * Math.sin(angle);
            return (
              <line key={`l-${a.id}`} x1={cx} y1={cy} x2={x} y2={y}
                     stroke={`${a.color}40`} strokeWidth={1}
                     strokeDasharray="2 4" />
            );
          })}
        </svg>

        {/* Centro — Presidente */}
        <div style={{
          position: "absolute", top: "50%", left: "50%",
          transform: "translate(-50%, -50%)",
          width: 130, height: 130, borderRadius: "50%",
          background: `radial-gradient(circle, ${ORACLE.purple} 0%, #2d0f4a 100%)`,
          boxShadow: `0 0 40px ${ORACLE.purple}55, 0 8px 32px rgba(0,0,0,0.2)`,
          display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center", gap: 4,
          color: "white", textAlign: "center", padding: 6,
        }}>
          <BrainCircuit size={26} color="white" />
          <div style={{ fontSize: 12, fontWeight: 800,
                          letterSpacing: "-0.01em" }}>Presidente IA</div>
          <div style={{ fontSize: 8, fontWeight: 700, opacity: .85,
                          textTransform: "uppercase", letterSpacing: .5 }}>
            {health?.score}/100
          </div>
          {totalRisk > 0 && (
            <div style={{
              position: "absolute", top: -8, right: -8,
              background: ORACLE.red, color: "white",
              borderRadius: "50%", width: 26, height: 26,
              display: "flex", alignItems: "center",
              justifyContent: "center", fontSize: 11, fontWeight: 800,
              boxShadow: "0 4px 12px rgba(180,35,24,.5)",
              animation: "pulse 1.5s ease infinite",
            }}>{totalRisk}</div>
          )}
        </div>

        {/* Agentes orbitando */}
        {agents.map((a, idx) => {
          const angle = (2 * Math.PI * idx) / agents.length - Math.PI / 2;
          const x = (size / 2) + radius * Math.cos(angle);
          const y = (size / 2) + radius * Math.sin(angle);
          return (
            <div key={a.id} data-testid={`agent-orbit-${a.id}`} style={{
              position: "absolute",
              left: `${(x / size) * 100}%`,
              top: `${(y / size) * 100}%`,
              transform: "translate(-50%, -50%)",
              width: 86, textAlign: "center",
            }}>
              <div style={{
                width: 52, height: 52, borderRadius: "50%",
                background: "white",
                border: `2px solid ${a.color}`,
                margin: "0 auto",
                display: "flex", alignItems: "center",
                justifyContent: "center",
                boxShadow: `0 4px 12px ${a.color}40`,
                color: a.color, fontSize: 11, fontWeight: 800,
              }}>
                {a.label.split(" ")[0].slice(0, 4).toUpperCase()}
              </div>
              <div style={{
                fontSize: 9.5, fontWeight: 700, color: "#334155",
                marginTop: 4, whiteSpace: "nowrap",
              }}>{a.label}</div>
              <div style={{
                fontSize: 8, color: "#94a3b8", fontWeight: 600,
              }}>{a.group}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────── Cards ───────────────────
function HealthCard({ health }) {
  const c = health.components;
  const color = HEALTH_COLOR[health.status] || ORACLE.purple;
  return (
    <Card title="Saúde da Empresa" icon={Heart} color={color}>
      <div style={{ position: "relative", margin: "8px auto 12px",
                      width: 130, height: 130 }}>
        <svg viewBox="0 0 100 100" style={{
          transform: "rotate(-90deg)", width: "100%", height: "100%" }}>
          <circle cx="50" cy="50" r="42" fill="none"
                   stroke="#f1f5f9" strokeWidth="8" />
          <circle cx="50" cy="50" r="42" fill="none"
                   stroke={color} strokeWidth="8" strokeLinecap="round"
                   strokeDasharray={`${(health.score / 100) * 264} 264`} />
        </svg>
        <div style={{
          position: "absolute", inset: 0, display: "flex",
          alignItems: "center", justifyContent: "center",
          flexDirection: "column",
        }}>
          <div style={{ fontSize: 30, fontWeight: 800, color }}>
            {health.score}
          </div>
          <div style={{ fontSize: 9, color: "#64748b", fontWeight: 700,
                          textTransform: "uppercase", letterSpacing: .5 }}>
            {health.status}
          </div>
        </div>
      </div>
      <MiniRow label="Total clientes" v={c.total_clientes} />
      <MiniRow label="Ativos" v={c.ativos} ok />
      <MiniRow label="Churn" v={`${c.churn_pct}%`}
                bad={c.churn_pct > 3} />
      <MiniRow label="Inadimplência" v={`${c.inadimplencia_pct}%`}
                bad={c.inadimplencia_pct > 10} />
      <MiniRow label="ONUs offline" v={c.onus_offline}
                bad={c.onu_offline_pct > 2} />
    </Card>
  );
}

function RisksCard({ risks }) {
  const tot = risks.total || 0;
  return (
    <Card title="Riscos" icon={ShieldAlert} color={ORACLE.red}>
      {tot === 0 ? (
        <div style={{ textAlign: "center", padding: 20, color: "#64748b" }}>
          <CheckCircle2 size={32} color={ORACLE.green}
                          style={{ margin: "0 auto" }} />
          <div style={{ fontSize: 12, fontWeight: 700, marginTop: 8 }}>
            Nenhum risco detectado
          </div>
        </div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            <Pill n={risks.criticos.length} label="crítico"
                    color={ORACLE.red} />
            <Pill n={risks.altos.length} label="alto"
                    color={ORACLE.orange} />
            <Pill n={risks.medios.length} label="médio" color="#d97706" />
          </div>
          {[
            ...risks.criticos, ...risks.altos, ...risks.medios,
          ].slice(0, 5).map((r, i) => (
            <RiskRow key={i} r={r} />
          ))}
        </>
      )}
    </Card>
  );
}

function OpportunitiesCard({ opps }) {
  return (
    <Card title="Oportunidades" icon={Target} color={ORACLE.green}>
      {opps.receita_potencial_brl > 0 && (
        <div style={{
          background: `${ORACLE.green}10`,
          padding: "8px 12px", borderRadius: 8, marginBottom: 8,
        }}>
          <div style={{ fontSize: 9, fontWeight: 800, color: ORACLE.green,
                          textTransform: "uppercase", letterSpacing: .5 }}>
            Receita potencial
          </div>
          <div style={{ fontSize: 18, fontWeight: 800, color: ORACLE.green }}>
            R$ {Number(opps.receita_potencial_brl).toLocaleString(
              "pt-BR", { minimumFractionDigits: 2 })}
          </div>
        </div>
      )}
      {opps.items.slice(0, 4).map((o, i) => (
        <div key={i} style={{
          padding: "6px 0", borderBottom: `1px dashed ${ORACLE.border}`,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                          fontSize: 12, fontWeight: 700,
                          color: "#0f172a" }}>
            <span>{o.titulo}</span>
            {o.receita_potencial_brl > 0 && (
              <span style={{ color: ORACLE.green }}>
                +R$ {Number(o.receita_potencial_brl).toLocaleString(
                  "pt-BR", { maximumFractionDigits: 0 })}
              </span>
            )}
          </div>
          <div style={{ fontSize: 10, color: "#64748b" }}>{o.descricao}</div>
        </div>
      ))}
      {opps.items.length === 0 && (
        <div style={{ color: "#94a3b8", fontSize: 12, padding: 10 }}>
          Nenhuma oportunidade identificada agora.
        </div>
      )}
    </Card>
  );
}

function StatCard({ title, icon: Icon, color, items }) {
  return (
    <Card title={title} icon={Icon} color={color}>
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(90px, 1fr))",
                      gap: 8 }}>
        {items.map((it, i) => (
          <div key={i} style={{
            background: "#fafbfc", borderRadius: 6, padding: "8px 10px",
            border: `1px solid ${ORACLE.border}`,
          }}>
            <div style={{
              fontSize: 18, fontWeight: 800,
              color: it.warn ? ORACLE.red : (it.ok ? ORACLE.green : "#0f172a"),
            }}>{typeof it.v === "number"
                  ? it.v.toLocaleString("pt-BR") : (it.v ?? "—")}
                {it.suffix || ""}</div>
            <div style={{
              fontSize: 9, color: "#64748b", fontWeight: 700,
              textTransform: "uppercase", letterSpacing: .4,
            }}>{it.label}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function UniversoLigoCard({ u }) {
  return (
    <Card title="Universo Ligo" icon={Sparkles} color={ORACLE.orange}>
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
        <MiniBox v={u.clientes_fibra} label="Fibra" color={ORACLE.purple} />
        <MiniBox v={u.ligo_de_casa} label="Ligo Casa"
                   color={ORACLE.orange} />
        <MiniBox v={u.parceiros_ativos} label="Parceiros"
                   color={ORACLE.green} />
        <MiniBox v={u.promocoes_ativas} label="Promoções"
                   color="#0891b2" />
        <MiniBox v={u.resgates_30d} label="Resgates 30d"
                   color="#7c3aed" />
        <MiniBox v={u.indicacoes_total} label="Indicações"
                   color={ORACLE.orange} />
      </div>
    </Card>
  );
}

function ClientsAtRiskCard({ clients }) {
  return (
    <Card title="Clientes em risco de churn"
            icon={AlertTriangle} color={ORACLE.red}>
      {clients.length === 0 ? (
        <div style={{ padding: 20, textAlign: "center",
                        color: "#64748b" }}>
          <CheckCircle2 size={28} color={ORACLE.green}
                          style={{ margin: "0 auto" }} />
          <div style={{ fontSize: 12, fontWeight: 700, marginTop: 6 }}>
            Nenhum cliente em risco crítico
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4,
                        maxHeight: 240, overflowY: "auto" }}>
          {clients.map((c) => (
            <div key={c.subscriber_id} style={{
              display: "flex", justifyContent: "space-between",
              padding: "6px 8px", borderRadius: 6,
              background: c.score >= 60
                ? `${ORACLE.red}10`
                : `${ORACLE.orange}10`,
              fontSize: 11,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, color: "#0f172a",
                                whiteSpace: "nowrap", overflow: "hidden",
                                textOverflow: "ellipsis" }}>
                  {c.name || c.subscriber_id}
                </div>
                <div style={{ fontSize: 10, color: "#64748b" }}>
                  {(c.reasons || []).join(" · ")}
                </div>
              </div>
              <div style={{
                fontWeight: 800,
                color: c.score >= 60 ? ORACLE.red : ORACLE.orange,
                fontSize: 14, marginLeft: 8,
              }}>{c.score}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function ConselhoExecutivo({ items, onRegenerate }) {
  return (
    <div data-testid="conselho-executivo">
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: `linear-gradient(135deg, ${ORACLE.purple}, #6d28d9)`,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <BrainCircuit size={16} color="white" />
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                           color: "var(--text-primary)" }}>
              Conselho Executivo IA
            </h2>
            <div style={{ fontSize: 10, color: "#64748b" }}>
              6 cadeiras especializadas · Claude Sonnet 4.6 · cache 60min
            </div>
          </div>
        </div>
        <button onClick={onRegenerate}
                 data-testid="council-regenerate"
                 style={btnSec()}>
          <Sparkles size={11} /> Regerar Conselho
        </button>
      </div>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
        gap: 12,
      }}>
        {items.map((c) => (
          <CouncilCard key={c.role} c={c} />
        ))}
      </div>
    </div>
  );
}

function CouncilCard({ c }) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid={`council-card-${c.role}`} style={{
      background: "white", border: `1px solid ${ORACLE.border}`,
      borderTop: `4px solid ${c.color}`, borderRadius: 10, padding: 14,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: c.color }}>
          {c.label}
        </div>
        {c.from_cache && (
          <span style={{
            fontSize: 9, color: "#64748b", fontWeight: 700,
            display: "flex", alignItems: "center", gap: 3,
          }}><Clock size={9} /> cache</span>
        )}
      </div>
      <div style={{
        fontSize: 12, color: "#334155", lineHeight: 1.55,
        whiteSpace: "pre-wrap",
        maxHeight: open ? "unset" : 200,
        overflow: "hidden", position: "relative",
      }}>
        {c.parecer}
        {!open && c.parecer && c.parecer.length > 400 && (
          <div style={{
            position: "absolute", inset: "auto 0 0 0", height: 60,
            background: "linear-gradient(transparent, white)",
          }} />
        )}
      </div>
      {c.parecer && c.parecer.length > 400 && (
        <button onClick={() => setOpen(!open)} style={{
          background: "none", border: "none", color: c.color,
          fontSize: 11, fontWeight: 700, cursor: "pointer",
          marginTop: 4, padding: 0,
          display: "flex", alignItems: "center", gap: 4,
        }}>
          {open ? "Recolher" : "Ler mais"}
          <ChevronDown size={11} style={{
            transform: open ? "rotate(180deg)" : "none",
            transition: "transform .15s",
          }} />
        </button>
      )}
    </div>
  );
}

// ─────────────────── Briefing Modal (iter219) ───────────────────
function BriefingModal({ onClose }) {
  const [settings, setSettings] = useState({ enabled: false, phone: "" });
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const s = await api._client.get(
          "/presidente-ia/briefing/settings");
        setSettings({
          enabled: !!s.data.enabled,
          phone: s.data.phone || "",
        });
        const p = await api._client.get(
          "/presidente-ia/briefing/preview");
        setPreview(p.data);
      } catch (e) { setErr(e.message); }
    })();
  }, []);

  const save = async () => {
    setBusy(true); setErr(""); setMsg("");
    try {
      await api._client.put("/presidente-ia/briefing/settings",
        settings);
      setMsg("Configuração salva!");
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setBusy(false);
  };

  const testSend = async () => {
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await api._client.post("/presidente-ia/briefing/test");
      if (r.data.ok) {
        setMsg(`Briefing enviado para ${r.data.sent_to}!`);
      } else {
        setErr(r.data.error || "Falha no envio");
      }
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setBusy(false);
  };

  return (
    <div onClick={onClose} data-testid="briefing-modal-backdrop" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,0.6)",
      zIndex: 1000, display: "flex", alignItems: "center",
      justifyContent: "center", padding: 20,
    }}>
      <div onClick={(e) => e.stopPropagation()}
            data-testid="briefing-modal" style={{
        background: "white", borderRadius: 12, width: "100%",
        maxWidth: 560, maxHeight: "90vh", overflow: "auto",
      }}>
        <div style={{
          padding: "14px 20px", borderBottom: `1px solid ${ORACLE.border}`,
          display: "flex", justifyContent: "space-between",
          alignItems: "center",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 8,
              background: `linear-gradient(135deg, ${ORACLE.orange}, #d97706)`,
              display: "flex", alignItems: "center",
              justifyContent: "center",
            }}>
              <Coffee size={18} color="white" />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 15, fontWeight: 800,
                             color: ORACLE.purple }}>
                Café com a IA do CEO
              </h2>
              <div style={{ fontSize: 10, color: "#64748b" }}>
                Briefing executivo diário às 08:00 BRT no WhatsApp
              </div>
            </div>
          </div>
          <button onClick={onClose} data-testid="briefing-modal-close"
                   style={{ background: "none", border: "none",
                              cursor: "pointer", color: "#64748b" }}>
            <X size={18} />
          </button>
        </div>

        <div style={{ padding: 20, display: "flex",
                        flexDirection: "column", gap: 14 }}>
          {/* Preview */}
          {preview && (
            <div>
              <div style={{
                fontSize: 11, fontWeight: 700, color: "#475569",
                textTransform: "uppercase", letterSpacing: .4,
                marginBottom: 6,
              }}>Prévia da mensagem</div>
              <div data-testid="briefing-preview" style={{
                background: "#dcf8c6", color: "#0f172a",
                padding: "12px 14px", borderRadius: 8,
                fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap",
                border: "1px solid #c8e6a0",
                fontFamily: "-apple-system,sans-serif",
              }}>{preview.text}</div>
            </div>
          )}

          {/* Settings */}
          <div style={{ display: "flex", flexDirection: "column",
                          gap: 8 }}>
            <label style={{
              display: "flex", alignItems: "center", gap: 8,
              fontSize: 13, fontWeight: 700, color: "#334155",
              cursor: "pointer",
            }}>
              <input type="checkbox" checked={settings.enabled}
                      data-testid="briefing-enabled"
                      onChange={(e) => setSettings({
                        ...settings, enabled: e.target.checked })} />
              Habilitar envio automático às 08:00 BRT (diariamente)
            </label>
            <label style={{
              fontSize: 11, fontWeight: 700, color: "#475569",
              textTransform: "uppercase", letterSpacing: .4,
            }}>Telefone WhatsApp do gestor</label>
            <input value={settings.phone}
                    data-testid="briefing-phone"
                    onChange={(e) => setSettings({
                      ...settings, phone: e.target.value })}
                    placeholder="5511999998888 (DDI + DDD + número)"
                    style={{
                      padding: "9px 12px", fontSize: 13,
                      border: `1px solid ${ORACLE.border}`,
                      borderRadius: 6, outline: "none",
                    }} />
          </div>

          {err && (
            <div data-testid="briefing-error" style={{
              background: "#fef2f2", color: ORACLE.red,
              padding: "8px 12px", borderRadius: 6, fontSize: 12,
              fontWeight: 600,
            }}>{err}</div>
          )}
          {msg && (
            <div data-testid="briefing-success" style={{
              background: `${ORACLE.green}15`, color: ORACLE.green,
              padding: "8px 12px", borderRadius: 6, fontSize: 12,
              fontWeight: 600,
            }}>{msg}</div>
          )}

          <div style={{ display: "flex", gap: 8,
                          justifyContent: "flex-end" }}>
            <button onClick={onClose}
                     data-testid="briefing-cancel" style={btnSec()}>
              Fechar
            </button>
            <button onClick={testSend} disabled={busy || !settings.phone}
                     data-testid="briefing-test"
                     style={{ ...btnSec(),
                                color: ORACLE.orange,
                                border: `1px solid ${ORACLE.orange}` }}>
              <Coffee size={12} /> Enviar agora (teste)
            </button>
            <button onClick={save} disabled={busy}
                     data-testid="briefing-save"
                     style={btnPrimary()}>
              <Settings size={12} /> Salvar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────── Helpers UI ───────────────────
function Card({ title, icon: Icon, color, children }) {
  return (
    <div style={{
      background: "white", border: `1px solid ${ORACLE.border}`,
      borderRadius: 12, padding: 14, display: "flex",
      flexDirection: "column", gap: 8,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 26, height: 26, borderRadius: 6,
          background: `${color}15`, color,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}><Icon size={14} /></div>
        <h3 style={{ margin: 0, fontSize: 13, fontWeight: 800,
                       color: "#0f172a" }}>{title}</h3>
      </div>
      {children}
    </div>
  );
}

function MiniRow({ label, v, ok, bad }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between",
      fontSize: 11, padding: "3px 0",
      borderBottom: `1px dashed ${ORACLE.border}`,
    }}>
      <span style={{ color: "#64748b" }}>{label}</span>
      <span style={{
        fontWeight: 800,
        color: bad ? ORACLE.red : (ok ? ORACLE.green : "#0f172a"),
      }}>{typeof v === "number" ? v.toLocaleString("pt-BR") : v}</span>
    </div>
  );
}

function Pill({ n, label, color }) {
  return (
    <div style={{
      flex: 1, padding: "6px 10px", borderRadius: 6,
      background: `${color}10`, color, textAlign: "center",
    }}>
      <div style={{ fontSize: 18, fontWeight: 800 }}>{n}</div>
      <div style={{ fontSize: 9, fontWeight: 700,
                      textTransform: "uppercase", letterSpacing: .5 }}>
        {label}
      </div>
    </div>
  );
}

function RiskRow({ r }) {
  const c = RISK_LEVEL_COLOR[r.level] || "#64748b";
  return (
    <div style={{
      padding: "5px 8px", borderRadius: 6, marginTop: 3,
      borderLeft: `3px solid ${c}`, background: `${c}08`,
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "#0f172a" }}>
        {r.area}
      </div>
      <div style={{ fontSize: 10, color: "#475569" }}>{r.descricao}</div>
    </div>
  );
}

function MiniBox({ v, label, color }) {
  return (
    <div style={{
      background: `${color}08`, borderRadius: 6, padding: "8px 6px",
      textAlign: "center", border: `1px solid ${color}20`,
    }}>
      <div style={{ fontSize: 18, fontWeight: 800, color }}>
        {typeof v === "number" ? v.toLocaleString("pt-BR") : v}
      </div>
      <div style={{
        fontSize: 9, color: "#64748b", fontWeight: 700,
        textTransform: "uppercase", letterSpacing: .4,
      }}>{label}</div>
    </div>
  );
}

function SkeletonLoader() {
  return (
    <div style={{
      background: "white", border: `1px solid ${ORACLE.border}`,
      borderRadius: 12, padding: 40, textAlign: "center", color: "#64748b",
    }}>
      <BrainCircuit size={40} color={ORACLE.purple}
                       style={{ margin: "0 auto",
                                  animation: "pulse 1.5s ease infinite" }} />
      <div style={{ fontSize: 13, fontWeight: 700, marginTop: 12 }}>
        Inicializando o Sistema Nervoso…
      </div>
    </div>
  );
}

function grid3() {
  return {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
    gap: 14,
  };
}

function btnSec() {
  return {
    padding: "8px 14px", fontSize: 12, fontWeight: 700,
    border: `1px solid ${ORACLE.border}`, borderRadius: 8,
    background: "white", color: "#64748b", cursor: "pointer",
    display: "flex", alignItems: "center", gap: 6,
  };
}
function btnPrimary() {
  return {
    padding: "8px 16px", fontSize: 12, fontWeight: 700,
    border: "none", borderRadius: 8,
    background: ORACLE.purple, color: "white", cursor: "pointer",
    display: "flex", alignItems: "center", gap: 6,
  };
}

// Reexport p/ não dar warning
export {
  Activity, DollarSign, LineChart, Megaphone, Wallet,
};
