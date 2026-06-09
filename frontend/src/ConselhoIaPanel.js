/* ConselhoIaPanel.js — iter215bq, Fase 1
   Conselho Estratégico IA. Consome /api/conselho-ia/report e
   renderiza módulos com Dado · Interpretação IA · Recomendação +
   o Parecer Executivo do Presidente IA.

   Design Oracle:
     primary:  #4b1d7a (roxo)
     secondary:#f28c28 (laranja)
     success:  #237a4b (verde)
     danger:   #b42318 (vermelho)
*/
import React, { useState, useEffect } from "react";
import { api } from "@/api";
import {
  BrainCircuit, RefreshCw, Calendar, TrendingUp, Wifi, FileText,
  AlertTriangle, CheckCircle2, Lightbulb, ChevronDown,
  Wrench, MessagesSquare, ShoppingCart, Sparkles, ShieldCheck,
  Wand2, ShieldAlert, Bot, Zap, History, Clock, Bell, Phone,
  FileSearch,
} from "lucide-react";
import DiagnosticReportPanel from "./DiagnosticReportPanel";

const ORACLE = {
  purple: "#4b1d7a", orange: "#f28c28",
  green: "#237a4b", red: "#b42318",
  bg: "#f8fafc", border: "#e2e8f0",
};

const PERIODS = [
  { id: "daily", label: "Diário" },
  { id: "weekly", label: "Semanal" },
  { id: "monthly", label: "Mensal" },
  { id: "quarterly", label: "Trimestral" },
  { id: "yearly", label: "Anual" },
];

const RISK_COLOR = {
  vermelho: ORACLE.red,
  amarelo: ORACLE.orange,
  verde: ORACLE.green,
  azul: "#1e40af",
};
const RISK_LABEL = {
  vermelho: "Crítico", amarelo: "Atenção",
  verde: "Saudável", azul: "Oportunidade",
};

export default function ConselhoIaPanel() {
  const [view, setView] = useState("conselho"); // 'conselho' | 'diagnostic'
  const [period, setPeriod] = useState("monthly");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const fetchReport = async (regenerate = false) => {
    setLoading(true); setErr("");
    try {
      const r = await api._client.post("/conselho-ia/report",
        { period, regenerate });
      setReport(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  };

  useEffect(() => {
    if (view === "conselho") fetchReport(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period, view]);

  return (
    <div data-testid="conselho-ia-panel" style={{
      display: "flex", flexDirection: "column", gap: 16, padding: "0 4px",
    }}>
      {/* Tabs: Conselho IA / Diagnóstico Completo */}
      <div data-testid="cia-view-tabs" style={{
        display: "flex", gap: 4, padding: 4,
        background: "#f1f5f9", borderRadius: 10,
        border: `1px solid ${ORACLE.border}`, width: "fit-content",
      }}>
        <TabButton active={view === "conselho"}
                    onClick={() => setView("conselho")}
                    icon={BrainCircuit} label="Conselho IA"
                    testid="cia-tab-conselho" />
        <TabButton active={view === "diagnostic"}
                    onClick={() => setView("diagnostic")}
                    icon={FileSearch} label="Diagnóstico Completo"
                    testid="cia-tab-diagnostic" />
      </div>

      {view === "diagnostic" && <DiagnosticReportPanel />}

      {view === "conselho" && (
        <>
        {/* Cabeçalho */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 42, height: 42, borderRadius: 10,
            background: `linear-gradient(135deg, ${ORACLE.purple}, #6d28d9)`,
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "0 4px 12px rgba(75, 29, 122, .3)",
          }}>
            <BrainCircuit size={22} color="white" />
          </div>
          <div>
            <h1 style={{
              fontSize: 22, fontWeight: 800, margin: 0,
              color: "var(--text-primary)", letterSpacing: "-0.02em",
            }}>Conselho Estratégico IA</h1>
            <div style={{
              fontSize: 12, color: "#64748b", marginTop: 2,
            }}>
              Camada executiva acima do Motor IA — converte dados em decisões.
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Calendar size={14} color="#64748b" />
          <select value={period} onChange={(e) => setPeriod(e.target.value)}
                   data-testid="cia-period-select"
                   style={{
                     padding: "8px 12px", fontSize: 13, fontWeight: 600,
                     border: `1px solid ${ORACLE.border}`,
                     borderRadius: 8, background: "white",
                     color: ORACLE.purple, cursor: "pointer",
                   }}>
            {PERIODS.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
          <button onClick={() => fetchReport(true)}
                   data-testid="cia-regenerate"
                   disabled={loading}
                   style={{
                     padding: "8px 14px", fontSize: 12, fontWeight: 700,
                     border: "none", borderRadius: 8, cursor: "pointer",
                     background: ORACLE.purple, color: "white",
                     display: "flex", alignItems: "center", gap: 6,
                     opacity: loading ? .6 : 1,
                   }}>
            <RefreshCw size={13}
              style={{
                animation: loading ? "spin 1s linear infinite" : "none",
              }} />
            {loading ? "Gerando…" : "Regerar com IA"}
          </button>
          <NotifySettingsButton />
        </div>
      </div>

      {err && (
        <div style={{
          background: "#fef2f2", border: `1px solid ${ORACLE.red}`,
          color: ORACLE.red, padding: "10px 14px", borderRadius: 8,
          fontSize: 13, fontWeight: 600,
        }} data-testid="cia-error">
          Erro: {err}
        </div>
      )}

      {!report && !err && (
        <div style={{
          background: "white", padding: 40, textAlign: "center",
          color: "#64748b", border: `1px solid ${ORACLE.border}`,
          borderRadius: 10, fontSize: 13,
        }}>
          Carregando relatório {PERIODS.find((p) => p.id === period)?.label.toLowerCase()}…
        </div>
      )}

      {report?.from_cache && (
        <div style={{
          fontSize: 11, color: "#64748b", textAlign: "right",
          fontStyle: "italic",
        }}>
          Relatório gerado em{" "}
          {new Date(report.generated_at).toLocaleString("pt-BR")}.
          Clique em <b>Regerar com IA</b> para atualizar.
        </div>
      )}

      {/* iter215bs — Auditor IA: card de correções automáticas */}
      {report?.auditor && <AuditorCard auditor={report.auditor} onRefresh={() => fetchReport(true)} />}

      {/* iter215bt — Agente IA: ações executáveis */}
      {report?.agent && <AgentCard agent={report.agent} />}

      {/* iter215bv — Timeline do Agente IA (feed histórico) */}
      <AgentTimeline />

      {/* Módulo 1: Visão Geral */}
      {report?.modules?.overview && (
        <ModuleCard
          icon={TrendingUp} color={ORACLE.purple}
          title="Módulo 1 — Visão Geral da Empresa"
          insight={report.modules.overview.insight}
        >
          <OverviewData data={report.modules.overview.data} />
        </ModuleCard>
      )}

      {/* Módulo 2: Rede & Operação */}
      {report?.modules?.network && (
        <ModuleCard
          icon={Wifi} color="#1e40af"
          title="Módulo 2 — Rede e Operação"
          insight={report.modules.network.insight}
        >
          <NetworkData data={report.modules.network.data} />
        </ModuleCard>
      )}

      {/* Módulo 3: Técnicos */}
      {report?.modules?.technicians && (
        <ModuleCard
          icon={Wrench} color="#0891b2"
          title="Módulo 3 — Técnicos"
          insight={report.modules.technicians.insight}
        >
          <TechniciansData data={report.modules.technicians.data} />
        </ModuleCard>
      )}

      {/* Módulo 4: Atendimento */}
      {report?.modules?.atendimento && (
        <ModuleCard
          icon={MessagesSquare} color="#7c3aed"
          title="Módulo 4 — Atendimento"
          insight={report.modules.atendimento.insight}
        >
          <AtendimentoData data={report.modules.atendimento.data} />
        </ModuleCard>
      )}

      {/* Módulo 5: Vendas */}
      {report?.modules?.sales && (
        <ModuleCard
          icon={ShoppingCart} color={ORACLE.orange}
          title="Módulo 5 — Vendas"
          insight={report.modules.sales.insight}
        >
          <SalesData data={report.modules.sales.data} />
        </ModuleCard>
      )}

      {/* Módulo 6: Universo Ligo */}
      {report?.modules?.universo && (
        <ModuleCard
          icon={Sparkles} color={ORACLE.purple}
          title="Módulo 6 — Universo Ligo"
          insight={report.modules.universo.insight}
        >
          <UniversoData data={report.modules.universo.data} />
        </ModuleCard>
      )}

      {/* Módulo 7: Ligo Protege */}
      {report?.modules?.protege && (
        <ModuleCard
          icon={ShieldCheck} color={ORACLE.green}
          title="Módulo 7 — Ligo Protege"
          insight={report.modules.protege.insight}
        >
          <ProtegeData data={report.modules.protege.data} />
        </ModuleCard>
      )}

      {/* Módulo 12: Parecer Executivo do Presidente IA */}
      {report?.parecer_executivo && (
        <ParecerCard parecer={report.parecer_executivo} />
      )}

      <style>{`@keyframes spin {
        from { transform: rotate(0deg); } to { transform: rotate(360deg); }
      }`}</style>
      </>
      )}
    </div>
  );
}

function TabButton({ active, onClick, icon: Icon, label, testid }) {
  return (
    <button onClick={onClick} data-testid={testid} style={{
      padding: "8px 14px", border: "none", borderRadius: 8,
      cursor: "pointer", fontSize: 12, fontWeight: 700,
      background: active ? ORACLE.purple : "transparent",
      color: active ? "white" : "#64748b",
      display: "flex", alignItems: "center", gap: 6,
      transition: "all .15s ease",
    }}>
      <Icon size={14} />
      {label}
    </button>
  );
}

// ────── Sub-components ──────
function ModuleCard({ icon: Icon, color, title, insight, children }) {
  const risk = insight?.risco || "verde";
  const riskColor = RISK_COLOR[risk] || ORACLE.green;
  return (
    <section data-testid={`cia-module-${title.split("—")[0].trim().toLowerCase().replace(/\s/g, "-")}`}
              style={{
                background: "white", border: `1px solid ${ORACLE.border}`,
                borderRadius: 12, padding: 0, overflow: "hidden",
                boxShadow: "0 1px 3px rgba(15, 23, 42, .04)",
              }}>
      <header style={{
        padding: "14px 18px", display: "flex", alignItems: "center",
        gap: 10, background: `${color}10`, borderBottom: `1px solid ${color}25`,
      }}>
        <Icon size={18} color={color} />
        <h2 style={{
          margin: 0, fontSize: 14, fontWeight: 800, color,
          letterSpacing: "-0.01em", flex: 1,
        }}>{title}</h2>
        <span style={{
          background: riskColor, color: "white",
          padding: "3px 10px", borderRadius: 12,
          fontSize: 10, fontWeight: 800, textTransform: "uppercase",
          letterSpacing: .5,
        }}>{RISK_LABEL[risk]}</span>
      </header>
      <div style={{ padding: 18 }}>
        {children}
        {(insight?.interpretacao || insight?.recomendacao) && (
          <div style={{
            marginTop: 16, display: "grid",
            gridTemplateColumns: "1fr 1fr", gap: 12,
          }}>
            <InsightBox
              icon={Lightbulb} color={ORACLE.orange}
              label="Interpretação do Motor IA"
              text={insight?.interpretacao} />
            <InsightBox
              icon={CheckCircle2} color={ORACLE.green}
              label="Recomendação executiva"
              text={insight?.recomendacao} />
          </div>
        )}
      </div>
    </section>
  );
}

function InsightBox({ icon: Icon, color, label, text }) {
  if (!text) return null;
  return (
    <div style={{
      background: `${color}10`, border: `1px solid ${color}30`,
      borderLeft: `3px solid ${color}`, borderRadius: 8,
      padding: "10px 14px",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 6, marginBottom: 6,
      }}>
        <Icon size={12} color={color} />
        <span style={{
          fontSize: 10, fontWeight: 800, color,
          textTransform: "uppercase", letterSpacing: .5,
        }}>{label}</span>
      </div>
      <div style={{ fontSize: 13, color: "#1e293b", lineHeight: 1.5 }}>
        {text}
      </div>
    </div>
  );
}

function Kpi({ label, value, color, prefix = "", suffix = "" }) {
  return (
    <div style={{
      background: "#fafbfc", border: `1px solid ${ORACLE.border}`,
      borderTop: `3px solid ${color}`, borderRadius: 8,
      padding: 12, textAlign: "left",
    }}>
      <div style={{ fontSize: 19, fontWeight: 800, color }}>
        {prefix}{typeof value === "number"
          ? value.toLocaleString("pt-BR") : value}{suffix}
      </div>
      <div style={{
        fontSize: 9, color: "#64748b", textTransform: "uppercase",
        letterSpacing: .5, fontWeight: 700, marginTop: 2,
      }}>{label}</div>
    </div>
  );
}

function OverviewData({ data }) {
  const fmt = (n) => `R$ ${Number(n || 0).toLocaleString("pt-BR",
    { minimumFractionDigits: 2 })}`;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
        gap: 10,
      }}>
        <Kpi label="Total clientes" value={data.total_clientes}
              color={ORACLE.purple} />
        <Kpi label="Ativos" value={data.ativos} color={ORACLE.green} />
        <Kpi label="Suspensos" value={data.suspensos} color={ORACLE.orange} />
        <Kpi label="Bloqueados" value={data.bloqueados} color={ORACLE.red} />
        <Kpi label="Cancelados" value={data.cancelados} color="#64748b" />
        <Kpi label="Novos no período" value={data.novos_no_periodo}
              color="#1e40af" />
        <Kpi label="MRR" value={fmt(data.mrr_brl)} color={ORACLE.green} />
        <Kpi label="Ticket médio" value={fmt(data.ticket_medio_brl)}
              color={ORACLE.purple} />
        <Kpi label="Churn" value={data.churn_pct}
              color={data.churn_pct > 5 ? ORACLE.red : ORACLE.green}
              suffix="%" />
        <Kpi label="Inadimplência" value={data.inadimplencia_pct}
              color={data.inadimplencia_pct > 10 ? ORACLE.red : ORACLE.orange}
              suffix="%" />
      </div>
      {!!data.top_cidades?.length && (
        <SubList title="Top cidades por MRR" items={
          data.top_cidades.map((c) => ({
            primary: c.cidade,
            secondary: `${c.qtd} clientes`,
            value: fmt(c.mrr),
          }))
        } />
      )}
      {!!data.top_planos?.length && (
        <SubList title="Top planos por volume" items={
          data.top_planos.map((p) => ({
            primary: p.plano,
            secondary: `${p.qtd} contratos`,
            value: fmt(p.mrr),
          }))
        } />
      )}
    </div>
  );
}

function NetworkData({ data }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
        gap: 10,
      }}>
        <Kpi label="OLTs" value={data.olts} color={ORACLE.purple} />
        <Kpi label="CTOs" value={data.ctos} color={ORACLE.purple} />
        <Kpi label="ONUs online" value={data.onus_online}
              color={ORACLE.green} />
        <Kpi label="ONUs offline" value={data.onus_offline}
              color={data.onus_offline > 0 ? ORACLE.red : "#64748b"} />
        <Kpi label="Potência média" value={data.potencia_media_dbm}
              color={ORACLE.purple} suffix=" dBm" />
      </div>
      {!!data.ctos_saturadas?.length && (
        <SubList title="Top 10 CTOs por número de clientes" items={
          data.ctos_saturadas.map((c) => ({
            primary: c.label,
            secondary: `${c.bairro} · ${c.clientes}/${c.capacidade} portas`,
            value: `${c.saturacao_pct}%`,
            valueColor: c.saturacao_pct > 85 ? ORACLE.red
              : (c.saturacao_pct > 70 ? ORACLE.orange : ORACLE.green),
          }))
        } />
      )}
      {!!data.bairros_com_mais_chamados?.length && (
        <SubList title="Bairros com mais chamados no período" items={
          data.bairros_com_mais_chamados.map((b) => ({
            primary: b.bairro, secondary: "",
            value: `${b.qtd} chamados`,
            valueColor: ORACLE.orange,
          }))
        } />
      )}
    </div>
  );
}

function SubList({ title, items }) {
  const [open, setOpen] = useState(true);
  return (
    <div>
      <button onClick={() => setOpen(!open)}
               style={{
                 background: "transparent", border: "none",
                 cursor: "pointer", display: "flex", alignItems: "center",
                 gap: 6, padding: 0, marginBottom: 8,
                 color: "#475569",
               }}>
        <ChevronDown size={14}
          style={{
            transform: open ? "rotate(0deg)" : "rotate(-90deg)",
            transition: "transform .2s",
          }} />
        <span style={{
          fontSize: 11, fontWeight: 800, textTransform: "uppercase",
          letterSpacing: .5,
        }}>{title}</span>
      </button>
      {open && (
        <div style={{
          border: `1px solid ${ORACLE.border}`, borderRadius: 8,
          overflow: "hidden",
        }}>
          {items.map((it, i) => (
            <div key={i} style={{
              padding: "8px 14px", display: "flex",
              justifyContent: "space-between", alignItems: "center",
              borderTop: i === 0 ? "none" : `1px solid ${ORACLE.border}`,
              background: i % 2 ? "#fafbfc" : "white",
            }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>
                  {it.primary}
                </div>
                {it.secondary && (
                  <div style={{ fontSize: 11, color: "#64748b" }}>
                    {it.secondary}
                  </div>
                )}
              </div>
              <div style={{
                fontSize: 13, fontWeight: 700,
                color: it.valueColor || ORACLE.purple,
              }}>{it.value}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ───── Dados — Módulos 3 a 7 (iter215br Fase 2) ─────
function TechniciansData({ data }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
                      gap: 10 }}>
        <Kpi label="Total tarefas" value={data.total_tarefas}
              color={ORACLE.purple} />
        <Kpi label="Instalações" value={data.instalacoes}
              color={ORACLE.green} />
        <Kpi label="Reparos" value={data.reparos}
              color={ORACLE.orange} />
        <Kpi label="Tempo médio" value={data.tempo_medio_horas}
              color="#0891b2" suffix="h" />
      </div>
      {!!data.por_tipo?.length && (
        <SubList title="Distribuição por tipo de tarefa"
                  items={data.por_tipo.map((t) => ({
                    primary: t.tipo || "—", secondary: "",
                    value: `${t.qtd}`,
                  }))} />
      )}
      {!!data.top_tecnicos?.length && (
        <SubList title="Top técnicos por volume"
                  items={data.top_tecnicos.map((t) => ({
                    primary: t.tecnico,
                    secondary: `${t.tarefas} tarefas`,
                    value: t.nota_media > 0
                      ? `${t.nota_media.toFixed(2)} ★`
                      : "—",
                    valueColor: t.nota_media >= 4 ? ORACLE.green
                      : (t.nota_media >= 3 ? ORACLE.orange
                        : t.nota_media > 0 ? ORACLE.red : "#94a3b8"),
                  }))} />
      )}
    </div>
  );
}

function AtendimentoData({ data }) {
  const s = data.sentimento || {};
  const total_sent = (s.positivo || 0) + (s.neutro || 0) + (s.negativo || 0);
  const pct = (n) => total_sent ? Math.round(100 * n / total_sent) : 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
                      gap: 10 }}>
        <Kpi label="Isabella · conversas" value={data.isabella_conversas}
              color={ORACLE.purple} />
        <Kpi label="Álvaro · análises" value={data.alvaro_analises}
              color="#7c3aed" />
        <Kpi label="Humano · mensagens" value={data.atendimento_humano_msgs}
              color="#1e40af" />
        <Kpi label="Solicitações suporte" value={data.solicitacoes_suporte}
              color={ORACLE.orange} />
      </div>
      {total_sent > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", letterSpacing: .5,
                          marginBottom: 6 }}>
            Sentimento dos clientes ({total_sent})
          </div>
          <div style={{ display: "flex", height: 28,
                          borderRadius: 8, overflow: "hidden",
                          border: `1px solid ${ORACLE.border}` }}>
            <div style={{ width: `${pct(s.positivo)}%`,
                            background: ORACLE.green,
                            color: "white", fontSize: 11, fontWeight: 700,
                            display: "flex", alignItems: "center",
                            justifyContent: "center" }}>
              {pct(s.positivo) > 5 && `${pct(s.positivo)}%`}
            </div>
            <div style={{ width: `${pct(s.neutro)}%`,
                            background: "#94a3b8",
                            color: "white", fontSize: 11, fontWeight: 700,
                            display: "flex", alignItems: "center",
                            justifyContent: "center" }}>
              {pct(s.neutro) > 5 && `${pct(s.neutro)}%`}
            </div>
            <div style={{ width: `${pct(s.negativo)}%`,
                            background: ORACLE.red,
                            color: "white", fontSize: 11, fontWeight: 700,
                            display: "flex", alignItems: "center",
                            justifyContent: "center" }}>
              {pct(s.negativo) > 5 && `${pct(s.negativo)}%`}
            </div>
          </div>
          <div style={{ display: "flex", gap: 14, marginTop: 6,
                          fontSize: 11, color: "#475569" }}>
            <span><b style={{ color: ORACLE.green }}>Positivo</b>
              {" "}{s.positivo || 0}</span>
            <span><b style={{ color: "#94a3b8" }}>Neutro</b>
              {" "}{s.neutro || 0}</span>
            <span><b style={{ color: ORACLE.red }}>Negativo</b>
              {" "}{s.negativo || 0}</span>
          </div>
        </div>
      )}
      {!!data.top_assuntos?.length && (
        <SubList title="Principais assuntos"
                  items={data.top_assuntos.map((a) => ({
                    primary: a.assunto, secondary: "",
                    value: `${a.qtd} chamados`,
                    valueColor: ORACLE.orange,
                  }))} />
      )}
    </div>
  );
}

function SalesData({ data }) {
  const b = data.leads_breakdown || {};
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
                      gap: 10 }}>
        <Kpi label="Leads totais" value={data.leads_total}
              color={ORACLE.orange} />
        <Kpi label="Vendas concluídas" value={data.vendas_concluidas}
              color={ORACLE.green} />
        <Kpi label="Conversão"
              value={data.taxa_conversao_pct}
              color={data.taxa_conversao_pct >= 30 ? ORACLE.green
                : data.taxa_conversao_pct >= 10 ? ORACLE.orange
                : ORACLE.red}
              suffix="%" />
        <Kpi label="Vindo do site" value={b.site || 0}
              color="#1e40af" />
        <Kpi label="Indicações" value={b.indicacao || 0}
              color={ORACLE.purple} />
      </div>
      {!!data.top_bairros_vendas?.length && (
        <SubList title="Top bairros — novos contratos"
                  items={data.top_bairros_vendas.map((b2) => ({
                    primary: b2.bairro || "—", secondary: "",
                    value: `${b2.qtd}`,
                    valueColor: ORACLE.green,
                  }))} />
      )}
      {!!data.top_planos_vendidos?.length && (
        <SubList title="Planos mais vendidos no período"
                  items={data.top_planos_vendidos.map((p) => ({
                    primary: p.plano || "—", secondary: "",
                    value: `${p.qtd}`,
                    valueColor: ORACLE.purple,
                  }))} />
      )}
    </div>
  );
}

function UniversoData({ data }) {
  const f = data.ligo_fibra || {};
  const c = data.clube_ligo || {};
  const p = data.parceiros_qr || {};
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(125px, 1fr))",
                      gap: 10 }}>
        <Kpi label="Ligo Fibra · base" value={f.base_ativa || 0}
              color={ORACLE.purple} />
        <Kpi label="Fibra · novos período" value={f.novos_periodo || 0}
              color={ORACLE.green} />
        <Kpi label="Ligo de Casa" value={(data.ligo_de_casa || {}).ativos || 0}
              color="#0891b2" />
        <Kpi label="Conteúdos" value={(data.ligo_conteudos || {}).assinantes || 0}
              color="#7c3aed" />
        <Kpi label="Clube · indicações" value={c.indicacoes || 0}
              color={ORACLE.orange} />
        <Kpi label="Clube · conversões" value={c.conversoes || 0}
              color={ORACLE.green} />
        <Kpi label="Parceiros · resgates" value={p.resgates || 0}
              color={ORACLE.purple} />
      </div>
      {!!(p.top_parceiros || []).length && (
        <SubList title="Parceiros mais acessados"
                  items={p.top_parceiros.map((pr) => ({
                    primary: pr.parceiro, secondary: "",
                    value: `${pr.qtd} resgates`,
                    valueColor: ORACLE.purple,
                  }))} />
      )}
    </div>
  );
}

function ProtegeData({ data }) {
  const s = data.security || {};
  const f = data.fleet || {};
  return (
    <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(125px, 1fr))",
                    gap: 10 }}>
      <Kpi label="Sites monitorados" value={s.sites || 0}
            color={ORACLE.green} />
      <Kpi label="Sensores" value={s.sensores || 0}
            color={ORACLE.green} />
      <Kpi label="Alarmes (total)" value={s.alarmes_totais || 0}
            color={(s.alarmes_totais || 0) > 0 ? ORACLE.orange : "#94a3b8"} />
      <Kpi label="Alarmes no período" value={s.alarmes_no_periodo || 0}
            color={(s.alarmes_no_periodo || 0) > 0 ? ORACLE.red : "#94a3b8"} />
      <Kpi label="Veículos rastreados" value={f.rastreadores || 0}
            color="#1e40af" />
      <Kpi label="Eventos GPS período" value={f.eventos_no_periodo || 0}
            color={ORACLE.purple} />
    </div>
  );
}


// iter215bv — Timeline do Agente IA (feed histórico)
function relativeTime(iso) {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.max(0, now - then);
  const min = Math.floor(diff / 60000);
  if (min < 1) return "agora";
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h}h`;
  const d = Math.floor(h / 24);
  if (d < 30) return `há ${d}d`;
  return new Date(iso).toLocaleDateString("pt-BR");
}

const AGENT_TOOL_LABEL = {
  flag_dunning: "Marcar para cobrança",
  create_inspection_ticket: "Criar chamado de inspeção",
  bulk_whatsapp_campaign: "Criar campanha WhatsApp (rascunho)",
};

// iter215bw — Botão "Notificar no WhatsApp" no cabeçalho
function NotifySettingsButton() {
  const [open, setOpen] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [phone, setPhone] = useState("");
  const [cronEnabled, setCronEnabled] = useState(false);
  const [cronHour, setCronHour] = useState(11);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await api._client.get("/conselho-ia/settings");
        setEnabled(!!r.data?.notify_on_action);
        setPhone(r.data?.notify_phone || "");
        setCronEnabled(!!r.data?.cron_enabled);
        setCronHour(r.data?.cron_hour_utc ?? 11);
      } catch { /* */ }
    })();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api._client.put("/conselho-ia/settings",
        { notify_on_action: enabled, notify_phone: phone,
          cron_enabled: cronEnabled, cron_hour_utc: cronHour });
      setOpen(false);
    } catch (e) {
      alert(`Erro: ${e?.response?.data?.detail || e.message}`);
    }
    setSaving(false);
  };

  return (
    <>
      <button onClick={() => setOpen(true)}
                data-testid="cia-notify-settings-btn"
                title="Notificações por WhatsApp"
                style={{
                  padding: "8px 10px", fontSize: 12, fontWeight: 700,
                  border: `1px solid ${ORACLE.border}`,
                  borderRadius: 8, cursor: "pointer",
                  background: enabled ? "#dcfce7" : "white",
                  color: enabled ? ORACLE.green : "#475569",
                  display: "flex", alignItems: "center", gap: 6,
                }}>
        <Bell size={13} />
        {enabled ? "WA ativo" : "WhatsApp"}
      </button>
      {open && (
        <div onClick={() => setOpen(false)}
              style={{ position: "fixed", inset: 0,
                        background: "rgba(0,0,0,.5)", zIndex: 2000,
                        display: "flex", alignItems: "center",
                        justifyContent: "center", padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()}
                data-testid="cia-notify-modal"
                style={{ background: "white", borderRadius: 12,
                          padding: 24, maxWidth: 420, width: "100%",
                          boxShadow: "0 24px 64px rgba(0,0,0,.4)" }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                            color: ORACLE.purple,
                            display: "flex", alignItems: "center", gap: 8 }}>
              <Bell size={16} /> Notificações por WhatsApp
            </h2>
            <div style={{ fontSize: 12, color: "#64748b",
                            marginTop: 6, marginBottom: 16 }}>
              Quando habilitado, o Agente IA manda uma mensagem
              cada vez que executar uma ação relevante (cobrança,
              chamado, campanha).
            </div>
            <label style={{ display: "flex", alignItems: "center",
                              gap: 8, fontSize: 13, fontWeight: 600,
                              cursor: "pointer", marginBottom: 14 }}>
              <input type="checkbox" checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)}
                      data-testid="cia-notify-enabled" />
              Habilitar notificações
            </label>
            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, fontWeight: 800,
                                color: "#475569", textTransform: "uppercase",
                                letterSpacing: .4 }}>
                Telefone do operador (com DDD)
              </label>
              <div style={{ position: "relative", marginTop: 6 }}>
                <Phone size={13} style={{ position: "absolute",
                  left: 10, top: 11, color: "#94a3b8" }} />
                <input type="tel" value={phone}
                        onChange={(e) => setPhone(e.target.value)}
                        placeholder="(11) 98765-4321"
                        data-testid="cia-notify-phone"
                        style={{ width: "100%",
                                   padding: "9px 12px 9px 32px", fontSize: 13,
                                   border: `1px solid ${ORACLE.border}`,
                                   borderRadius: 8 }} />
              </div>
            </div>
            <div style={{ marginBottom: 14, paddingTop: 14,
                            borderTop: `1px solid ${ORACLE.border}` }}>
              <label style={{ display: "flex", alignItems: "center",
                                gap: 8, fontSize: 13, fontWeight: 600,
                                cursor: "pointer", marginBottom: 8 }}>
                <input type="checkbox" checked={cronEnabled}
                        onChange={(e) => setCronEnabled(e.target.checked)}
                        data-testid="cia-cron-enabled" />
                Geração automática diária
              </label>
              <div style={{ fontSize: 11, color: "#64748b",
                              marginBottom: 8 }}>
                Roda o Conselho IA todo dia no horário escolhido (UTC).
                O agente decide e executa ações sozinho, e te avisa
                no WhatsApp.
              </div>
              {cronEnabled && (
                <div style={{ display: "flex", alignItems: "center",
                                gap: 8 }}>
                  <Clock size={13} color="#94a3b8" />
                  <span style={{ fontSize: 12, color: "#475569" }}>
                    Hora (UTC):
                  </span>
                  <input type="number" min={0} max={23}
                          value={cronHour}
                          onChange={(e) => setCronHour(parseInt(e.target.value) || 0)}
                          data-testid="cia-cron-hour"
                          style={{ width: 60, padding: "6px 8px",
                                    fontSize: 13, fontWeight: 700,
                                    border: `1px solid ${ORACLE.border}`,
                                    borderRadius: 6, textAlign: "center" }} />
                  <span style={{ fontSize: 11, color: "#94a3b8" }}>
                    (BRT = UTC-3 → {((cronHour - 3 + 24) % 24)
                      .toString().padStart(2, "0")}:00)
                  </span>
                </div>
              )}
            </div>
            <div style={{ display: "flex", gap: 8,
                            justifyContent: "flex-end" }}>
              <button onClick={() => setOpen(false)}
                       style={{ padding: "8px 14px", fontSize: 12,
                                  fontWeight: 700, border: `1px solid ${ORACLE.border}`,
                                  borderRadius: 8, background: "white",
                                  color: "#475569", cursor: "pointer" }}>
                Cancelar
              </button>
              <button onClick={save} disabled={saving}
                       data-testid="cia-notify-save"
                       style={{ padding: "8px 14px", fontSize: 12,
                                  fontWeight: 700, border: "none",
                                  borderRadius: 8, background: ORACLE.purple,
                                  color: "white", cursor: "pointer",
                                  opacity: saving ? .6 : 1 }}>
                {saving ? "Salvando…" : "Salvar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}



function AgentTimeline() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api._client.get("/conselho-ia/agent-actions?limit=30");
      setItems(r.data?.items || []);
    } catch { setItems([]); }
    setLoading(false);
  };

  useEffect(() => { if (open) load(); }, [open]);

  return (
    <section data-testid="cia-agent-timeline" style={{
      background: "white", borderRadius: 12,
      border: `1px solid ${ORACLE.border}`, overflow: "hidden",
    }}>
      <button onClick={() => setOpen(!open)}
                data-testid="cia-agent-timeline-toggle"
                style={{
                  width: "100%", padding: "12px 18px",
                  display: "flex", alignItems: "center", gap: 10,
                  background: open ? "#f8fafc" : "white",
                  border: "none", cursor: "pointer", textAlign: "left",
                  borderBottom: open ? `1px solid ${ORACLE.border}` : "none",
                }}>
        <History size={18} color="#475569" />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 800,
                          color: "#1e293b" }}>
            Timeline do Agente IA
          </div>
          <div style={{ fontSize: 11, color: "#64748b" }}>
            Histórico completo das ações que o agente executou
          </div>
        </div>
        <ChevronDown size={16} color="#475569"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)",
                     transition: "transform .2s" }} />
      </button>

      {open && (
        <div style={{ padding: "16px 20px" }}>
          {loading ? (
            <div style={{ padding: 20, textAlign: "center",
                            color: "#64748b", fontSize: 13 }}>
              Carregando histórico…
            </div>
          ) : !items.length ? (
            <div style={{ padding: 30, textAlign: "center",
                            color: "#64748b", fontSize: 13 }}>
              Nenhuma ação registrada ainda. Quando o Agente IA
              executar alguma ferramenta, ela aparecerá aqui.
            </div>
          ) : (
            <div style={{ position: "relative", paddingLeft: 24 }}>
              {/* Linha vertical do timeline */}
              <div style={{
                position: "absolute", left: 6, top: 4, bottom: 4,
                width: 2, background: "#e2e8f0",
              }} />
              {items.map((it, i) => {
                const colorMap = {
                  executed: ORACLE.green, pending: ORACLE.orange,
                  failed: ORACLE.red, rejected: "#64748b",
                  approved: ORACLE.green,
                };
                const c = colorMap[it.status] || "#64748b";
                const label = AGENT_TOOL_LABEL[it.tool] || it.tool;
                return (
                  <div key={it.id || i}
                        data-testid={`cia-timeline-item-${it.id}`}
                        style={{ position: "relative", paddingBottom: 18 }}>
                    {/* Dot */}
                    <div style={{
                      position: "absolute", left: -23, top: 2,
                      width: 14, height: 14, borderRadius: "50%",
                      background: "white", border: `3px solid ${c}`,
                    }} />
                    <div style={{
                      display: "flex", alignItems: "flex-start",
                      gap: 10, flexWrap: "wrap",
                    }}>
                      <div style={{ flex: 1, minWidth: 200 }}>
                        <div style={{ display: "flex",
                                        alignItems: "center", gap: 8,
                                        flexWrap: "wrap" }}>
                          <code style={{ fontSize: 12, fontWeight: 800,
                                           color: c,
                                           fontFamily: "monospace" }}>
                            {label}
                          </code>
                          <span style={{
                            background: c, color: "white",
                            padding: "1px 7px", borderRadius: 10,
                            fontSize: 9, fontWeight: 800,
                            letterSpacing: .4, textTransform: "uppercase",
                          }}>{it.status}</span>
                          <span style={{ fontSize: 10, color: "#94a3b8",
                                           display: "inline-flex",
                                           alignItems: "center", gap: 3 }}>
                            <Clock size={10} />
                            {relativeTime(it.created_at)}
                          </span>
                        </div>
                        {it.justification && (
                          <div style={{ fontSize: 12, color: "#334155",
                                          marginTop: 4, lineHeight: 1.5 }}>
                            {it.justification}
                          </div>
                        )}
                        {it.result && Object.keys(it.result).length > 0 && (
                          <div style={{ fontSize: 10, color: "#64748b",
                                          marginTop: 4,
                                          fontFamily: "monospace",
                                          background: "#f1f5f9",
                                          padding: "4px 8px",
                                          borderRadius: 4,
                                          display: "inline-block",
                                          maxWidth: "100%",
                                          overflow: "hidden",
                                          textOverflow: "ellipsis",
                                          whiteSpace: "nowrap" }}>
                            {JSON.stringify(it.result)}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </section>
  );
}


// iter215bs — Card do Auditor IA
function AuditorCard({ auditor, onRefresh }) {
  const applied = auditor?.applied_actions || [];
  const pending = auditor?.pending_actions || [];
  const fixed = auditor?.total_records_fixed || 0;
  if (!applied.length && !pending.length) return null;

  const ACTION_LABEL = {
    backfill_plan_price: "Preencher preço do plano",
    backfill_plan_name: "Preencher nome do plano",
    normalize_status_case: "Padronizar status",
    anomalia_vendas: "Anomalia em vendas",
  };

  const resolvePending = async (aid, decision) => {
    let notes = "";
    if (decision === "rejected") {
      notes = window.prompt(
        "Por que rejeitar essa ação? (mín. 3 caracteres):");
      if (!notes || notes.trim().length < 3) return;
    } else {
      if (!window.confirm("Aprovar a ação? Marca como aprovada no log "
        + "(sem aplicar mudanças automáticas).")) return;
    }
    try {
      await api._client.post(
        `/conselho-ia/audit-log/${aid}/resolve`,
        { decision, notes });
      if (typeof onRefresh === "function") onRefresh();
    } catch (e) {
      alert(`Erro: ${e?.response?.data?.detail || e.message}`);
    }
  };

  return (
    <section data-testid="cia-auditor-card" style={{
      background: "white", borderRadius: 12,
      border: `1px solid ${ORACLE.border}`,
      borderTop: `3px solid ${ORACLE.green}`,
      overflow: "hidden",
      boxShadow: "0 2px 8px rgba(35, 122, 75, .08)",
    }}>
      <header style={{
        padding: "12px 18px", display: "flex", alignItems: "center",
        gap: 10, background: "#ecfdf5", borderBottom: "1px solid #a7f3d0",
      }}>
        <Wand2 size={18} color={ORACLE.green} />
        <div style={{ flex: 1 }}>
          <h2 style={{
            margin: 0, fontSize: 14, fontWeight: 800,
            color: ORACLE.green, letterSpacing: "-0.01em",
          }}>Auditor IA · Correções automáticas</h2>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
            {fixed > 0
              ? `${fixed} registro${fixed === 1 ? "" : "s"} corrigido${
                  fixed === 1 ? "" : "s"} automaticamente (whitelist)`
              : "Nenhuma correção automática aplicada nesta execução."}
          </div>
        </div>
      </header>
      <div style={{ padding: 14, display: "flex",
                      flexDirection: "column", gap: 8 }}>
        {applied.map((a, i) => (
          <div key={i} data-testid={`cia-applied-${a.action}`}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "8px 12px", borderRadius: 8,
                  background: "#f0fdf4", border: "1px solid #bbf7d0",
                }}>
            <CheckCircle2 size={14} color={ORACLE.green} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 700,
                              color: "#065f46" }}>
                {ACTION_LABEL[a.action] || a.action}
              </div>
              {!!a.sample?.length && (
                <div style={{ fontSize: 11, color: "#64748b",
                                marginTop: 2 }}>
                  Ex.:{" "}
                  <b>{a.sample[0].name || a.sample[0].sub_id}</b>
                  {a.sample[0].new !== undefined && (
                    <>
                      {" "}·{" "}
                      {a.sample[0].old === null ? "null"
                        : a.sample[0].old}
                      {" → "}
                      <b style={{ color: ORACLE.green }}>{
                        typeof a.sample[0].new === "number"
                          ? `R$ ${a.sample[0].new.toFixed(2)}`
                          : a.sample[0].new}</b>
                    </>
                  )}
                </div>
              )}
            </div>
            <span style={{
              background: ORACLE.green, color: "white",
              padding: "3px 10px", borderRadius: 12, fontSize: 10,
              fontWeight: 800, letterSpacing: .5,
            }}>{a.applied} aplicado{a.applied === 1 ? "" : "s"}</span>
          </div>
        ))}
        {pending.map((p, i) => (
          <div key={`p${i}`} data-testid={`cia-pending-${p.action}`}
                style={{
                  display: "flex", alignItems: "flex-start", gap: 10,
                  padding: "10px 12px", borderRadius: 8,
                  background: "#fefce8", border: "1px solid #fde68a",
                }}>
            <ShieldAlert size={14} color={ORACLE.orange}
              style={{ marginTop: 3 }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 700,
                              color: "#854d0e" }}>
                {ACTION_LABEL[p.action] || p.action}
              </div>
              <div style={{ fontSize: 11, color: "#92400e",
                              marginTop: 4, lineHeight: 1.5 }}>
                {p.notes}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
              <button onClick={() => resolvePending(p.id, "approved")}
                       data-testid={`cia-approve-${p.action}`}
                       style={{
                         padding: "5px 12px", fontSize: 11, fontWeight: 700,
                         border: `1px solid ${ORACLE.green}`,
                         background: "white", color: ORACLE.green,
                         borderRadius: 6, cursor: "pointer",
                       }}>
                Aprovar
              </button>
              <button onClick={() => resolvePending(p.id, "rejected")}
                       data-testid={`cia-reject-${p.action}`}
                       style={{
                         padding: "5px 12px", fontSize: 11, fontWeight: 700,
                         border: `1px solid ${ORACLE.red}`,
                         background: "white", color: ORACLE.red,
                         borderRadius: 6, cursor: "pointer",
                       }}>
                Ignorar
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// iter215bt — Agente IA: card de ações executadas
function AgentCard({ agent }) {
  const execs = agent?.executions || [];
  if (!execs.length) return null;

  const STATUS_COLOR = {
    executed: ORACLE.green, pending: ORACLE.orange,
    failed: ORACLE.red, rejected: "#64748b",
  };
  const STATUS_LABEL = {
    executed: "Executado", pending: "Aguarda aprovação",
    failed: "Falhou", rejected: "Rejeitado",
  };

  return (
    <section data-testid="cia-agent-card" style={{
      background: "white", borderRadius: 12,
      border: `1px solid ${ORACLE.border}`,
      borderTop: `3px solid ${ORACLE.purple}`,
      overflow: "hidden",
      boxShadow: "0 2px 8px rgba(75, 29, 122, .1)",
    }}>
      <header style={{
        padding: "12px 18px", display: "flex", alignItems: "center",
        gap: 10, background: "#faf5ff", borderBottom: "1px solid #e9d5ff",
      }}>
        <Bot size={18} color={ORACLE.purple} />
        <div style={{ flex: 1 }}>
          <h2 style={{
            margin: 0, fontSize: 14, fontWeight: 800,
            color: ORACLE.purple, letterSpacing: "-0.01em",
          }}>Agente IA · Ações executáveis</h2>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
            {execs.length} ação{execs.length === 1 ? "" : "ões"} planejada
            {execs.length === 1 ? "" : "s"} pelo Motor IA.
          </div>
        </div>
      </header>
      <div style={{ padding: 14, display: "flex",
                      flexDirection: "column", gap: 8 }}>
        {execs.map((e, i) => (
          <div key={i} data-testid={`cia-agent-exec-${e.tool}`}
                style={{
                  display: "flex", alignItems: "flex-start", gap: 10,
                  padding: "10px 12px", borderRadius: 8,
                  background: e.status === "executed" ? "#f0fdf4"
                    : e.status === "pending" ? "#fefce8" : "#fef2f2",
                  border: `1px solid ${
                    e.status === "executed" ? "#bbf7d0"
                      : e.status === "pending" ? "#fde68a" : "#fecaca"}`,
                }}>
            <Zap size={14} color={STATUS_COLOR[e.status] || ORACLE.purple}
                  style={{ marginTop: 3 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center",
                              gap: 8, flexWrap: "wrap" }}>
                <code style={{ fontSize: 12, fontWeight: 800,
                                 color: ORACLE.purple,
                                 fontFamily: "monospace" }}>
                  {e.tool}()
                </code>
                <span style={{
                  background: STATUS_COLOR[e.status] || "#64748b",
                  color: "white", padding: "2px 8px", borderRadius: 10,
                  fontSize: 9, fontWeight: 800, letterSpacing: .4,
                  textTransform: "uppercase",
                }}>{STATUS_LABEL[e.status] || e.status}</span>
              </div>
              {e.justification && (
                <div style={{ fontSize: 12, color: "#374151",
                                marginTop: 4 }}>
                  {e.justification}
                </div>
              )}
              {e.result && (
                <div style={{ fontSize: 10, color: "#64748b",
                                marginTop: 4, fontFamily: "monospace" }}>
                  resultado: {JSON.stringify(e.result)}
                </div>
              )}
              {e.error && (
                <div style={{ fontSize: 11, color: ORACLE.red,
                                marginTop: 4 }}>
                  Erro: {e.error}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}



function ParecerCard({ parecer }) {
  const sections = [
    { key: "o_que_aconteceu", title: "O que aconteceu",
      icon: FileText, color: "#64748b" },
    { key: "o_que_merece_atencao", title: "O que merece atenção",
      icon: AlertTriangle, color: ORACLE.orange },
    { key: "o_que_esta_funcionando", title: "O que está funcionando",
      icon: CheckCircle2, color: ORACLE.green },
    { key: "o_que_pode_crescer", title: "O que pode crescer",
      icon: TrendingUp, color: "#1e40af" },
    { key: "proximos_7_dias", title: "Próximos 7 dias",
      icon: Lightbulb, color: ORACLE.purple },
    { key: "proximos_30_dias", title: "Próximos 30 dias",
      icon: Lightbulb, color: ORACLE.purple },
    { key: "proximos_90_dias", title: "Próximos 90 dias",
      icon: Lightbulb, color: ORACLE.purple },
  ];
  return (
    <section data-testid="cia-parecer-executivo"
              style={{
                background: `linear-gradient(135deg, ${ORACLE.purple} 0%, #1e1b4b 100%)`,
                borderRadius: 12, overflow: "hidden",
                color: "white", padding: 0,
                boxShadow: "0 10px 30px rgba(75, 29, 122, .25)",
              }}>
      <header style={{
        padding: "18px 22px", display: "flex", alignItems: "center",
        gap: 12, borderBottom: "1px solid rgba(255,255,255,.15)",
      }}>
        <div style={{
          width: 38, height: 38, borderRadius: 10,
          background: "rgba(255,255,255,.15)",
          backdropFilter: "blur(8px)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <BrainCircuit size={20} color="white" />
        </div>
        <div>
          <div style={{
            fontSize: 10, fontWeight: 800, letterSpacing: 2,
            textTransform: "uppercase", color: "rgba(255,255,255,.5)",
          }}>Módulo 12 · Parecer Executivo</div>
          <h2 style={{
            margin: 0, fontSize: 18, fontWeight: 800,
          }}>Presidente IA</h2>
        </div>
      </header>
      <div style={{ padding: 22, display: "flex",
                      flexDirection: "column", gap: 14 }}>
        {sections.map((s) => {
          const text = parecer[s.key];
          if (!text) return null;
          return (
            <div key={s.key} style={{
              background: "rgba(255,255,255,.06)",
              borderLeft: `3px solid ${s.color}`,
              padding: "12px 16px", borderRadius: 8,
            }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 8, marginBottom: 6,
              }}>
                <s.icon size={13} color={s.color} />
                <span style={{
                  fontSize: 11, fontWeight: 800, color: s.color,
                  textTransform: "uppercase", letterSpacing: .5,
                }}>{s.title}</span>
              </div>
              <div style={{
                fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap",
                color: "rgba(255,255,255,.92)",
              }}>{text}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
