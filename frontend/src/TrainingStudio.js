import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  X, RefreshCw, Play, Loader2, CheckCircle2, XCircle, AlertTriangle,
  Bot, BookOpen, ListChecks, Network, History, Search,
  ChevronRight, Award, Target, Clock, Zap, Filter,
} from "lucide-react";
import { Card, Button } from "@/ui";
import { api } from "@/api";

/* =============================================================
   Training Studio — gestão completa do treinamento multiagente

   Tabs:
     1. Cenários   — 60 simulações realistas (filtros + detalhe)
     2. Testes     — 20 testes de validação (executa LLM real)
     3. Matriz     — 31 regras de decisão (quando X → acionar Y)
     4. Histórico  — runs executadas (score, breakdown, replay)
============================================================= */

const CATEGORY_LABELS = {
  rede_smartolt: "Rede / SmartOLT",
  agendamento_kanban: "Agendamento / Kanban",
  atendimento_humano: "Atendimento Humano",
  avaliacao_coach: "Avaliação / Coach",
  falhas_escalonamento: "Falhas / Escalonamento",
  variacao_dificil: "Variações Difíceis",
};

const CATEGORY_COLORS = {
  rede_smartolt: "#0ea5e9",
  agendamento_kanban: "#8b5cf6",
  atendimento_humano: "#22c55e",
  avaliacao_coach: "#f59e0b",
  falhas_escalonamento: "#ef4444",
  variacao_dificil: "#ec4899",
};

const TEST_CATEGORIA_COLORS = {
  rede: "#0ea5e9",
  kanban: "#8b5cf6",
  retencao: "#ef4444",
  humano_obrigatorio: "#dc2626",
  falha_sistema: "#f59e0b",
  comunicacao: "#10b981",
  preventivo: "#06b6d4",
  supervisao: "#7c3aed",
  qualidade: "#f97316",
  financeiro: "#84cc16",
  juridico: "#b91c1c",
  encerramento: "#64748b",
  sistema: "#fbbf24",
  transparencia: "#0d9488",
};

const MATRIX_CATEGORIA_COLORS = {
  rede: "#0ea5e9",
  agendamento: "#8b5cf6",
  risco: "#ef4444",
  supervisao: "#7c3aed",
  sistema: "#f59e0b",
  ticket: "#64748b",
  qualidade: "#f97316",
  transparencia: "#0d9488",
  cadastro: "#10b981",
  especial: "#ec4899",
};

const PRIORITY_COLORS = {
  critica: "#dc2626",
  alta: "#f97316",
  media: "#0ea5e9",
  baixa: "#64748b",
};

const SCORE_COLOR = (s) =>
  s >= 9 ? "#16a34a" : s >= 7.5 ? "#0ea5e9" : s >= 6 ? "#f59e0b" : "#dc2626";

function Tab({ id, label, icon: Icon, count, active, onClick }) {
  return (
    <button
      data-testid={`ts-tab-${id}`}
      onClick={() => onClick(id)}
      style={{
        padding: "10px 16px",
        borderRadius: 8,
        border: active ? "1px solid #0f172a" : "1px solid var(--border-default)",
        background: active ? "#0f172a" : "var(--bg-surface)",
        color: active ? "white" : "var(--text-primary)",
        fontSize: 13, fontWeight: 700, cursor: "pointer",
        display: "inline-flex", alignItems: "center", gap: 8,
        transition: "all .15s",
      }}
    >
      <Icon size={14} />
      {label}
      {count != null && (
        <span style={{
          padding: "2px 7px", borderRadius: 999, fontSize: 11,
          background: active ? "rgba(255,255,255,.2)" : "var(--bg-surface-2)",
          color: active ? "white" : "var(--text-muted)",
          fontWeight: 700,
        }}>{count}</span>
      )}
    </button>
  );
}

/* ============================================================
   CENÁRIOS TAB
============================================================ */
function ScenariosTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [filterCat, setFilterCat] = useState("");
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.aiTrainingScenarios({
        category: filterCat || undefined,
        q: query || undefined,
      });
      setData(r);
    } finally { setLoading(false); }
  }, [filterCat, query]);

  useEffect(() => { load(); }, [load]);

  const items = data?.items || [];
  const categories = data?.categories || {};

  return (
    <div style={{ display: "grid", gridTemplateColumns: selected ? "1fr 1.4fr" : "1fr", gap: 14 }}>
      <div>
        {/* Toolbar */}
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ position: "relative", flex: 1, minWidth: 200 }}>
            <Search size={13} style={{ position: "absolute", left: 10, top: "50%",
              transform: "translateY(-50%)", color: "var(--text-muted)" }} />
            <input
              data-testid="ts-scenarios-search"
              value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar por nome ou objetivo…"
              style={{
                width: "100%", padding: "8px 10px 8px 30px", borderRadius: 8,
                border: "1px solid var(--border-default)", fontSize: 12.5,
                background: "var(--bg-surface)", color: "var(--text-primary)",
              }}
            />
          </div>
          <select
            data-testid="ts-scenarios-filter-cat"
            value={filterCat} onChange={(e) => setFilterCat(e.target.value)}
            style={{
              padding: "8px 10px", borderRadius: 8,
              border: "1px solid var(--border-default)", fontSize: 12.5,
              background: "var(--bg-surface)", color: "var(--text-primary)",
              minWidth: 180,
            }}
          >
            <option value="">Todas categorias</option>
            {Object.entries(categories).map(([k, n]) => (
              <option key={k} value={k}>{CATEGORY_LABELS[k] || k} ({n})</option>
            ))}
          </select>
          <Button onClick={load} variant="secondary" size="sm">
            <RefreshCw size={12} /> Atualizar
          </Button>
        </div>

        {/* Lista */}
        {loading ? (
          <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
            <Loader2 size={14} className="spin" /> Carregando cenários…
          </div>
        ) : (
          <div data-testid="ts-scenarios-list" style={{
            display: "grid", gap: 8, maxHeight: "65vh", overflow: "auto", paddingRight: 4,
          }}>
            {items.map((s) => (
              <button
                key={s.number}
                data-testid={`ts-scenario-${s.number}`}
                onClick={() => setSelected(s)}
                style={{
                  textAlign: "left", padding: "10px 12px", borderRadius: 8,
                  border: selected?.number === s.number
                    ? `2px solid ${CATEGORY_COLORS[s.category] || "#0f172a"}`
                    : "1px solid var(--border-default)",
                  background: "var(--bg-surface)", cursor: "pointer",
                  transition: "all .12s",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span style={{
                    padding: "2px 7px", borderRadius: 4, fontSize: 10, fontWeight: 800,
                    background: (CATEGORY_COLORS[s.category] || "#0f172a") + "22",
                    color: CATEGORY_COLORS[s.category] || "#0f172a",
                  }}>#{s.number}</span>
                  <span style={{
                    fontSize: 10, color: "var(--text-muted)", fontWeight: 700,
                    textTransform: "uppercase", letterSpacing: ".5px",
                  }}>{CATEGORY_LABELS[s.category] || s.category}</span>
                </div>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
                  {s.name}
                </div>
                <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 3, lineHeight: 1.4 }}>
                  {(s.objetivo || "").slice(0, 90)}…
                </div>
              </button>
            ))}
            {items.length === 0 && (
              <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
                Nenhum cenário encontrado com esses filtros.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Detalhe */}
      {selected && <ScenarioDetail s={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function ScenarioDetail({ s, onClose }) {
  return (
    <div data-testid="ts-scenario-detail" style={{
      border: "1px solid var(--border-default)", borderRadius: 10,
      background: "var(--bg-surface)", padding: 16, maxHeight: "70vh", overflow: "auto",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{
              padding: "3px 9px", borderRadius: 6, fontSize: 11, fontWeight: 800,
              background: (CATEGORY_COLORS[s.category] || "#0f172a"),
              color: "white",
            }}>Cenário #{s.number}</span>
            <span style={{ fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)",
              textTransform: "uppercase", letterSpacing: ".5px" }}>
              {CATEGORY_LABELS[s.category] || s.category}
            </span>
          </div>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: "var(--text-primary)" }}>
            {s.name}
          </h3>
        </div>
        <button onClick={onClose} style={{
          padding: 6, border: "none", background: "transparent",
          cursor: "pointer", color: "var(--text-muted)",
        }}><X size={16} /></button>
      </div>

      <Section title="Objetivo do treinamento">
        <p style={{ fontSize: 13, lineHeight: 1.55, color: "var(--text-primary)", margin: 0 }}>
          {s.objetivo}
        </p>
      </Section>

      <Section title="Contexto">
        <p style={{ fontSize: 13, lineHeight: 1.55, color: "var(--text-secondary)", margin: 0 }}>
          {s.contexto}
        </p>
      </Section>

      <Section title="Agentes envolvidos">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {(s.agentes_envolvidos || []).map((a) => (
            <span key={a} style={{
              padding: "3px 9px", borderRadius: 999, fontSize: 11, fontWeight: 700,
              background: "var(--bg-surface-2)", color: "var(--text-primary)",
              border: "1px solid var(--border-default)",
            }}>{a}</span>
          ))}
        </div>
      </Section>

      <Section title="Fluxo ideal esperado">
        <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.7 }}>
          {(s.fluxo_ideal || []).map((p, i) => (
            <li key={i} style={{ color: "var(--text-primary)" }}>{p}</li>
          ))}
        </ol>
      </Section>

      <Section title="Simulação da conversa">
        <div style={{ display: "grid", gap: 6 }}>
          {(s.simulacao_conversa || []).map((m, i) => (
            <MessageBubble key={i} m={m} />
          ))}
        </div>
      </Section>

      {s.resposta_correta_cliente && (
        <Section title="Resposta correta ao cliente" highlight="#16a34a">
          <div style={{
            padding: 10, borderRadius: 8, fontSize: 12.5, lineHeight: 1.5,
            background: "rgba(22,163,74,.08)", color: "#15803d",
            borderLeft: "3px solid #16a34a",
          }}>{s.resposta_correta_cliente}</div>
        </Section>
      )}

      {Array.isArray(s.erros_a_evitar) && s.erros_a_evitar.length > 0 && (
        <Section title="Erros a evitar" highlight="#dc2626">
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, lineHeight: 1.6, color: "#b91c1c" }}>
            {s.erros_a_evitar.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </Section>
      )}

      {s.criterios_avaliacao && (
        <Section title="Critérios de avaliação">
          <p style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--text-secondary)", margin: 0 }}>
            {s.criterios_avaliacao}
          </p>
        </Section>
      )}

      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 12,
      }}>
        <div style={{
          padding: 10, borderRadius: 8, textAlign: "center",
          background: "rgba(22,163,74,.10)", border: "1px solid #16a34a44",
        }}>
          <div style={{ fontSize: 10, color: "#16a34a", fontWeight: 800,
            textTransform: "uppercase", letterSpacing: ".5px" }}>Nota se correto</div>
          <div style={{ fontSize: 24, fontWeight: 900, color: "#16a34a" }}>
            {s.nota_esperada_correto || "—"}
          </div>
        </div>
        <div style={{
          padding: 10, borderRadius: 8, textAlign: "center",
          background: "rgba(220,38,38,.10)", border: "1px solid #dc262644",
        }}>
          <div style={{ fontSize: 10, color: "#dc2626", fontWeight: 800,
            textTransform: "uppercase", letterSpacing: ".5px" }}>Nota se errado</div>
          <div style={{ fontSize: 24, fontWeight: 900, color: "#dc2626" }}>
            {s.nota_esperada_errado || "—"}
          </div>
          {s.motivo_nota_errado && (
            <div style={{ fontSize: 10, color: "#b91c1c", marginTop: 3, lineHeight: 1.3 }}>
              {s.motivo_nota_errado}
            </div>
          )}
        </div>
      </div>

      {s.licao && (
        <Section title="Lição do cenário" highlight="#8b5cf6">
          <div style={{
            padding: 10, borderRadius: 8, fontSize: 13, lineHeight: 1.55,
            fontStyle: "italic", color: "#7c3aed",
            background: "rgba(139,92,246,.08)",
            borderLeft: "3px solid #8b5cf6",
          }}>{s.licao}</div>
        </Section>
      )}
    </div>
  );
}

function Section({ title, highlight, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{
        fontSize: 10.5, fontWeight: 800, color: highlight || "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: ".7px", marginBottom: 6,
      }}>{title}</div>
      {children}
    </div>
  );
}

function MessageBubble({ m }) {
  const isClient = (m.de || "").startsWith("Cliente");
  const isCoPilot = (m.de || "").includes("Co-Pilot");
  const isAvaliador = (m.de || "").includes("Avaliador");
  const isCoach = (m.de || "").includes("Coach");
  const isSentinela = (m.de || "").includes("Sentinela");
  const isMotor = (m.de || "").includes("Motor");
  const isSmartolt = (m.de || "").includes("SmartOLT");
  const isIsabela = (m.de || "").includes("Isabela");
  const isKanban = (m.de || "").includes("Kanban");
  const isAprendizado = (m.de || "").includes("Aprendizado");

  let color = "#64748b";
  if (isClient) color = "#0f172a";
  else if (isCoPilot) color = "#ec4899";
  else if (isAvaliador) color = "#f59e0b";
  else if (isCoach) color = "#8b5cf6";
  else if (isSentinela) color = "#dc2626";
  else if (isMotor) color = "#7c3aed";
  else if (isSmartolt) color = "#0ea5e9";
  else if (isIsabela) color = "#0d9488";
  else if (isKanban) color = "#6366f1";
  else if (isAprendizado) color = "#84cc16";

  return (
    <div style={{
      padding: "8px 10px", borderRadius: 7,
      background: color + "0d",
      borderLeft: `3px solid ${color}`,
    }}>
      <div style={{
        fontSize: 10, fontWeight: 800, color,
        textTransform: "uppercase", letterSpacing: ".4px", marginBottom: 3,
      }}>
        {m.de} {m.para && <span style={{ opacity: .6 }}>→ {m.para}</span>}
      </div>
      <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--text-primary)", whiteSpace: "pre-wrap" }}>
        {m.fala}
      </div>
    </div>
  );
}

/* ============================================================
   TESTES TAB
============================================================ */
function TestsTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(null); // test number being run
  const [runningAll, setRunningAll] = useState(false);
  const [batchResult, setBatchResult] = useState(null);
  const [detailRun, setDetailRun] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.aiTrainingTests();
      setData(r);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function runOne(n) {
    setRunning(n);
    try {
      const r = await api.aiTrainingRunTest(n);
      setDetailRun(r.run);
      await load();
    } catch (e) {
      alert("Erro ao executar teste: " + (e?.response?.data?.detail || e.message));
    } finally { setRunning(null); }
  }

  async function runAll() {
    if (!window.confirm("Executar TODOS os 20 testes? Isso vai consumir tokens LLM.")) return;
    setRunningAll(true);
    setBatchResult(null);
    try {
      const r = await api.aiTrainingRunAll();
      setBatchResult(r);
      await load();
    } catch (e) {
      alert("Erro batch: " + (e?.response?.data?.detail || e.message));
    } finally { setRunningAll(false); }
  }

  const items = data?.items || [];

  return (
    <div>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        gap: 10, marginBottom: 14, flexWrap: "wrap",
      }}>
        <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          {items.length} testes de validação. Cada teste roda a Isabela IA real
          contra a entrada e usa o Avaliador IA para dar nota (0-10).
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Button onClick={load} variant="secondary" size="sm">
            <RefreshCw size={12} /> Atualizar
          </Button>
          <Button
            onClick={runAll}
            disabled={runningAll}
            variant="primary"
            size="sm"
            data-testid="ts-tests-run-all"
          >
            {runningAll ? (
              <><Loader2 size={12} className="spin" /> Executando 20 testes…</>
            ) : (
              <><Play size={12} /> Executar todos</>
            )}
          </Button>
        </div>
      </div>

      {batchResult && (
        <div data-testid="ts-batch-summary" style={{
          padding: 14, borderRadius: 10, marginBottom: 14,
          background: "linear-gradient(135deg, #0f172a, #1e293b)",
          color: "white",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
            <div>
              <div style={{ fontSize: 11, opacity: .7, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".5px" }}>
                Batch concluído
              </div>
              <div style={{ fontSize: 13, fontWeight: 700, marginTop: 2 }}>
                {batchResult.passed}/{batchResult.total} aprovados ·
                Média {batchResult.average_score}/10
              </div>
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              <Metric label="Aprovados" value={batchResult.passed} color="#22c55e" />
              <Metric label="Reprovados" value={batchResult.failed} color="#ef4444" />
              <Metric label="Média" value={batchResult.average_score} color="#0ea5e9" suffix="/10" />
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
          <Loader2 size={14} className="spin" /> Carregando testes…
        </div>
      ) : (
        <div style={{
          display: "grid", gridTemplateColumns: detailRun ? "1fr 1.2fr" : "1fr",
          gap: 14, alignItems: "start",
        }}>
          <div data-testid="ts-tests-list" style={{
            display: "grid", gap: 6, maxHeight: "65vh", overflow: "auto", paddingRight: 4,
          }}>
            {items.map((t) => (
              <TestRow
                key={t.number} t={t}
                isRunning={running === t.number}
                onRun={() => runOne(t.number)}
                onViewLast={() => t.last_run?.id && api.aiTrainingRun(t.last_run.id).then(setDetailRun)}
              />
            ))}
          </div>

          {detailRun && (
            <RunDetail run={detailRun} onClose={() => setDetailRun(null)} />
          )}
        </div>
      )}
    </div>
  );
}

function TestRow({ t, isRunning, onRun, onViewLast }) {
  const last = t.last_run;
  const cat = t.categoria;
  const color = TEST_CATEGORIA_COLORS[cat] || "#64748b";
  return (
    <div data-testid={`ts-test-${t.number}`} style={{
      padding: "10px 12px", borderRadius: 8,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
      display: "flex", alignItems: "center", gap: 10,
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 8, flexShrink: 0,
        background: color + "22", color, display: "grid", placeItems: "center",
        fontSize: 12, fontWeight: 900,
      }}>{t.number}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, color, textTransform: "uppercase",
            letterSpacing: ".4px",
          }}>{cat}</span>
          {last && (
            <span style={{
              fontSize: 10, fontWeight: 800, padding: "1px 6px", borderRadius: 4,
              background: SCORE_COLOR(last.score) + "22",
              color: SCORE_COLOR(last.score),
            }}>
              Última: {last.score?.toFixed?.(1) || last.score}/10 {last.pass ? "✓" : "✗"}
            </span>
          )}
        </div>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {t.name}
        </div>
        <div style={{ fontSize: 11.5, color: "var(--text-muted)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 1 }}>
          "{(t.entrada_cliente || "").slice(0, 80)}"
        </div>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        {last && (
          <Button onClick={onViewLast} variant="secondary" size="sm">
            Ver última
          </Button>
        )}
        <Button
          onClick={onRun}
          disabled={isRunning}
          variant="primary"
          size="sm"
          data-testid={`ts-test-run-${t.number}`}
        >
          {isRunning ? <Loader2 size={12} className="spin" /> : <Play size={12} />}
          {isRunning ? "Executando…" : "Executar"}
        </Button>
      </div>
    </div>
  );
}

function RunDetail({ run, onClose }) {
  const ev = run.evaluation || {};
  const bd = ev.breakdown || {};
  return (
    <div data-testid="ts-run-detail" style={{
      border: "1px solid var(--border-default)", borderRadius: 10,
      background: "var(--bg-surface)", padding: 16,
      maxHeight: "70vh", overflow: "auto",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{
              padding: "3px 9px", borderRadius: 6, fontSize: 11, fontWeight: 800,
              background: SCORE_COLOR(run.score) + "22",
              color: SCORE_COLOR(run.score),
            }}>{run.score?.toFixed?.(1) || run.score}/10</span>
            {ev.classificacao && (
              <span style={{ fontSize: 10.5, fontWeight: 800,
                color: run.pass ? "#16a34a" : "#dc2626", textTransform: "uppercase",
                letterSpacing: ".5px" }}>
                {run.pass ? <CheckCircle2 size={11} style={{ display: "inline" }} /> : <XCircle size={11} style={{ display: "inline" }} />}
                {" "}{ev.classificacao}
              </span>
            )}
          </div>
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 800, color: "var(--text-primary)" }}>
            Teste #{run.test_number} · {run.test_name}
          </h3>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
            {String(run.created_at || "").slice(0, 16).replace("T", " ")}
            {run.user_name && ` · por ${run.user_name}`}
          </div>
        </div>
        <button onClick={onClose} style={{
          padding: 6, border: "none", background: "transparent",
          cursor: "pointer", color: "var(--text-muted)",
        }}><X size={16} /></button>
      </div>

      {run.status === "error" && (
        <div style={{
          padding: 10, borderRadius: 8, marginBottom: 12,
          background: "rgba(220,38,38,.10)", color: "#b91c1c",
          fontSize: 12, display: "flex", gap: 8, alignItems: "flex-start",
        }}>
          <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
          <div>{run.error}</div>
        </div>
      )}

      <Section title="Entrada do cliente">
        <div style={{
          padding: 10, borderRadius: 8, fontSize: 12.5, lineHeight: 1.5,
          background: "rgba(15,23,42,.05)", color: "var(--text-primary)",
          borderLeft: "3px solid #64748b",
        }}>"{run.entrada_cliente}"</div>
      </Section>

      <Section title="Resposta da Isabela IA">
        <div style={{
          padding: 10, borderRadius: 8, fontSize: 12.5, lineHeight: 1.55,
          background: "rgba(13,148,136,.06)", color: "var(--text-primary)",
          borderLeft: "3px solid #0d9488", whiteSpace: "pre-wrap",
          maxHeight: 300, overflow: "auto",
        }}>{run.isabela_response || "(sem resposta)"}</div>
      </Section>

      {Object.keys(bd).length > 0 && (
        <Section title="Breakdown da nota (100 pts)">
          <div style={{ display: "grid", gap: 4 }}>
            {[
              ["Fluxo correto", bd.fluxo_correto, 30],
              ["Consulta à fonte", bd.consulta_fonte, 25],
              ["Sem invenção", bd.sem_invencao, 20],
              ["Empatia + clareza", bd.empatia_clareza, 10],
              ["Reconhecimento risco", bd.reconhecimento_risco, 10],
              ["Transparência", bd.transparencia, 5],
            ].map(([label, got, max]) => (
              <BreakdownRow key={label} label={label} got={got || 0} max={max} />
            ))}
          </div>
          {Array.isArray(ev.penalidades) && ev.penalidades.length > 0 && (
            <div style={{ marginTop: 8, padding: 8, borderRadius: 6,
              background: "rgba(220,38,38,.08)", color: "#b91c1c", fontSize: 11.5 }}>
              <strong>Penalidades:</strong>
              <ul style={{ margin: "4px 0 0", paddingLeft: 16 }}>
                {ev.penalidades.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </div>
          )}
        </Section>
      )}

      {ev.justificativa && (
        <Section title="Justificativa do Avaliador">
          <p style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--text-primary)", margin: 0 }}>
            {ev.justificativa}
          </p>
        </Section>
      )}

      {Array.isArray(ev.agentes_acionados_corretamente) && (
        <Section title="Agentes acionados corretamente">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {ev.agentes_acionados_corretamente.length === 0 && (
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>—</span>
            )}
            {ev.agentes_acionados_corretamente.map((a, i) => (
              <span key={i} style={{
                padding: "2px 7px", borderRadius: 999, fontSize: 10.5, fontWeight: 700,
                background: "rgba(22,163,74,.12)", color: "#16a34a",
              }}>{a}</span>
            ))}
          </div>
        </Section>
      )}

      {Array.isArray(ev.agentes_faltando) && ev.agentes_faltando.length > 0 && (
        <Section title="Agentes que faltaram">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {ev.agentes_faltando.map((a, i) => (
              <span key={i} style={{
                padding: "2px 7px", borderRadius: 999, fontSize: 10.5, fontWeight: 700,
                background: "rgba(220,38,38,.12)", color: "#dc2626",
              }}>{a}</span>
            ))}
          </div>
        </Section>
      )}

      {Array.isArray(ev.sugestoes_melhoria) && ev.sugestoes_melhoria.length > 0 && (
        <Section title="Sugestões de melhoria" highlight="#8b5cf6">
          <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, lineHeight: 1.55, color: "#7c3aed" }}>
            {ev.sugestoes_melhoria.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </Section>
      )}
    </div>
  );
}

function BreakdownRow({ label, got, max }) {
  const pct = max > 0 ? (got / max) * 100 : 0;
  const color = pct >= 80 ? "#16a34a" : pct >= 60 ? "#0ea5e9" : pct >= 40 ? "#f59e0b" : "#dc2626";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ fontSize: 11.5, color: "var(--text-secondary)", minWidth: 120 }}>{label}</span>
      <div style={{ flex: 1, height: 8, borderRadius: 4, background: "var(--bg-surface-2)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, transition: "width .3s" }} />
      </div>
      <span style={{ fontSize: 11, fontWeight: 800, color, minWidth: 38, textAlign: "right" }}>
        {got}/{max}
      </span>
    </div>
  );
}

function Metric({ label, value, color, suffix }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: 10, opacity: .7, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".5px" }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 900, color }}>{value}{suffix}</div>
    </div>
  );
}

/* ============================================================
   MATRIZ DE DECISÃO TAB
============================================================ */
function MatrixTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filterCat, setFilterCat] = useState("");

  useEffect(() => {
    setLoading(true);
    api.aiTrainingDecisionMatrix().then((r) => {
      setData(r); setLoading(false);
    });
  }, []);

  const grouped = useMemo(() => {
    const g = data?.by_categoria || {};
    if (!filterCat) return g;
    return { [filterCat]: g[filterCat] || [] };
  }, [data, filterCat]);

  if (loading) return (
    <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
      <Loader2 size={14} className="spin" /> Carregando matriz…
    </div>
  );

  const cats = Object.keys(data?.by_categoria || {});

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <Filter size={14} style={{ color: "var(--text-muted)" }} />
        <button
          onClick={() => setFilterCat("")}
          data-testid="ts-matrix-cat-all"
          style={chipStyle(!filterCat, "#0f172a")}
        >Todas ({data?.count || 0})</button>
        {cats.map((c) => (
          <button
            key={c} onClick={() => setFilterCat(c)}
            data-testid={`ts-matrix-cat-${c}`}
            style={chipStyle(filterCat === c, MATRIX_CATEGORIA_COLORS[c] || "#64748b")}
          >
            {c} ({(data.by_categoria[c] || []).length})
          </button>
        ))}
      </div>

      <div data-testid="ts-matrix-list" style={{ display: "grid", gap: 14, maxHeight: "65vh", overflow: "auto", paddingRight: 4 }}>
        {Object.entries(grouped).map(([cat, rows]) => (
          <div key={cat}>
            <h4 style={{
              margin: "0 0 8px", fontSize: 12.5, fontWeight: 800,
              color: MATRIX_CATEGORIA_COLORS[cat] || "var(--text-primary)",
              textTransform: "uppercase", letterSpacing: ".5px",
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <span style={{
                width: 10, height: 10, borderRadius: 999,
                background: MATRIX_CATEGORIA_COLORS[cat] || "#64748b",
              }} />
              {cat} <span style={{ opacity: .6 }}>({rows.length})</span>
            </h4>
            <div style={{ display: "grid", gap: 5 }}>
              {rows.map((r) => <MatrixRow key={r.id} r={r} />)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function chipStyle(active, color) {
  return {
    padding: "5px 10px", borderRadius: 999, fontSize: 11.5, fontWeight: 700,
    border: active ? `1px solid ${color}` : "1px solid var(--border-default)",
    background: active ? color : "var(--bg-surface)",
    color: active ? "white" : "var(--text-primary)",
    cursor: "pointer", transition: "all .12s",
  };
}

function MatrixRow({ r }) {
  return (
    <div data-testid={`ts-matrix-row-${r.order}`} style={{
      padding: "10px 12px", borderRadius: 8,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
      display: "grid",
      gridTemplateColumns: "auto 1fr auto 1fr",
      gap: 10, alignItems: "center",
    }}>
      <div style={{
        width: 26, height: 26, borderRadius: 6, display: "grid", placeItems: "center",
        background: (MATRIX_CATEGORIA_COLORS[r.categoria] || "#64748b") + "22",
        color: MATRIX_CATEGORIA_COLORS[r.categoria] || "#64748b",
        fontSize: 11, fontWeight: 900,
      }}>{r.order}</div>
      <div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700,
          marginBottom: 2, textTransform: "uppercase", letterSpacing: ".4px" }}>Quando</div>
        <div style={{ fontSize: 12.5, color: "var(--text-primary)" }}>{r.condicao}</div>
      </div>
      <ChevronRight size={16} style={{ color: "var(--text-muted)" }} />
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
          <span style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700,
            textTransform: "uppercase", letterSpacing: ".4px" }}>Acionar</span>
          {r.prioridade && (
            <span style={{
              padding: "1px 6px", borderRadius: 4, fontSize: 9.5, fontWeight: 800,
              background: (PRIORITY_COLORS[r.prioridade] || "#64748b") + "22",
              color: PRIORITY_COLORS[r.prioridade] || "#64748b",
              textTransform: "uppercase", letterSpacing: ".4px",
            }}>{r.prioridade}</span>
          )}
        </div>
        <div style={{ fontSize: 12.5, color: "var(--text-primary)" }}>{r.acao}</div>
        <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 2 }}>
          <span style={{ fontWeight: 700 }}>{r.agente_origem}</span> → {r.agente_destino}
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   HISTÓRICO TAB
============================================================ */
function HistoryTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailRun, setDetailRun] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api.aiTrainingRuns(100).then((r) => { setData(r); setLoading(false); });
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loading) return (
    <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
      <Loader2 size={14} className="spin" /> Carregando histórico…
    </div>
  );

  const items = data?.items || [];

  return (
    <div>
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
        gap: 10, marginBottom: 14,
      }}>
        <KpiCard label="Execuções" value={data?.count || 0} color="#0f172a" />
        <KpiCard label="Aprovados" value={data?.passed || 0} color="#16a34a" />
        <KpiCard label="Reprovados" value={data?.failed || 0} color="#dc2626" />
        <KpiCard label="Nota média" value={data?.average_score || 0} suffix="/10" color="#0ea5e9" />
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
          Últimas {items.length} execuções
        </div>
        <Button onClick={load} variant="secondary" size="sm">
          <RefreshCw size={12} /> Atualizar
        </Button>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: detailRun ? "1fr 1.2fr" : "1fr",
        gap: 14, alignItems: "start",
      }}>
        <div data-testid="ts-history-list" style={{
          display: "grid", gap: 5, maxHeight: "60vh", overflow: "auto", paddingRight: 4,
        }}>
          {items.length === 0 && (
            <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
              Nenhuma execução ainda. Execute alguns testes na aba "Testes".
            </div>
          )}
          {items.map((r) => (
            <button
              key={r.id}
              data-testid={`ts-history-${r.id}`}
              onClick={() => api.aiTrainingRun(r.id).then(setDetailRun)}
              style={{
                textAlign: "left", padding: "8px 11px", borderRadius: 7,
                border: detailRun?.id === r.id
                  ? "2px solid #0f172a"
                  : "1px solid var(--border-default)",
                background: "var(--bg-surface)", cursor: "pointer",
                display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 8,
                alignItems: "center",
              }}
            >
              <div style={{
                width: 28, height: 28, borderRadius: 7,
                background: SCORE_COLOR(r.score) + "22",
                color: SCORE_COLOR(r.score),
                fontSize: 11, fontWeight: 900,
                display: "grid", placeItems: "center",
              }}>{r.test_number}</div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-primary)",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.test_name}
                </div>
                <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 1 }}>
                  {String(r.created_at || "").slice(0, 16).replace("T", " ")}
                  {r.user_name && ` · ${r.user_name}`}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                {r.pass ? (
                  <CheckCircle2 size={14} style={{ color: "#16a34a" }} />
                ) : (
                  <XCircle size={14} style={{ color: "#dc2626" }} />
                )}
                <span style={{
                  fontSize: 12, fontWeight: 800,
                  color: SCORE_COLOR(r.score),
                }}>
                  {r.score?.toFixed?.(1) || r.score}/10
                </span>
              </div>
            </button>
          ))}
        </div>

        {detailRun && <RunDetail run={detailRun} onClose={() => setDetailRun(null)} />}
      </div>
    </div>
  );
}

function KpiCard({ label, value, suffix, color }) {
  return (
    <div style={{
      padding: 12, borderRadius: 10,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
    }}>
      <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: ".5px" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 900, color, marginTop: 2 }}>
        {value}{suffix || ""}
      </div>
    </div>
  );
}

/* ============================================================
   MAIN — TrainingStudio
============================================================ */
export default function TrainingStudio({ embedded = false, onClose }) {
  const [tab, setTab] = useState("cenarios");
  const [counts, setCounts] = useState({ scenarios: 0, tests: 0, matrix: 0 });

  useEffect(() => {
    Promise.all([
      api.aiTrainingScenarios().then((r) => r.total).catch(() => 0),
      api.aiTrainingTests().then((r) => r.count).catch(() => 0),
      api.aiTrainingDecisionMatrix().then((r) => r.count).catch(() => 0),
    ]).then(([s, t, m]) => setCounts({ scenarios: s, tests: t, matrix: m }));
  }, []);

  const content = (
    <>
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 16,
        flexWrap: "wrap",
      }}>
        <Tab id="cenarios" label="Cenários" icon={BookOpen} count={counts.scenarios}
              active={tab === "cenarios"} onClick={setTab} />
        <Tab id="testes" label="Testes" icon={ListChecks} count={counts.tests}
              active={tab === "testes"} onClick={setTab} />
        <Tab id="matriz" label="Matriz" icon={Network} count={counts.matrix}
              active={tab === "matriz"} onClick={setTab} />
        <Tab id="historico" label="Histórico" icon={History}
              active={tab === "historico"} onClick={setTab} />
      </div>

      {tab === "cenarios" && <ScenariosTab />}
      {tab === "testes" && <TestsTab />}
      {tab === "matriz" && <MatrixTab />}
      {tab === "historico" && <HistoryTab />}
    </>
  );

  if (embedded) return content;

  return (
    <div data-testid="training-studio-modal" style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
      zIndex: 9999, display: "grid", placeItems: "center", padding: 24,
    }}>
      <div style={{
        background: "var(--bg-surface)", borderRadius: 14,
        width: "min(1280px, 96vw)", maxHeight: "94vh", overflow: "auto",
        padding: 20,
      }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 14, paddingBottom: 14,
          borderBottom: "1px solid var(--border-default)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 38, height: 38, borderRadius: 10,
              background: "linear-gradient(135deg, #0f172a, #1e293b)",
              color: "white", display: "grid", placeItems: "center",
              boxShadow: "0 4px 14px rgba(15,23,42,.25)",
            }}>
              <Bot size={20} strokeWidth={1.75} />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 17, fontWeight: 800,
                letterSpacing: "-0.018em", color: "var(--text-primary)" }}>
                Training Studio
              </h2>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                Simulador de treinamento multiagente · Isabela · Motor · SmartOLT · Co-Pilot · Avaliador · Coach · Sentinela · Aprendizado · Triagem
              </div>
            </div>
          </div>
          <button onClick={onClose} data-testid="ts-close"
                  style={{
                    padding: 8, border: "1px solid var(--border-default)",
                    background: "var(--bg-surface)", borderRadius: 8,
                    cursor: "pointer", color: "var(--text-muted)",
                  }}><X size={16} /></button>
        </div>
        {content}
      </div>
    </div>
  );
}
