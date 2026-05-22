import React, { useEffect, useState, useCallback, useMemo } from "react";
import { Card } from "@/ui";
import { api } from "@/api";
import {
  Users, AlertCircle, RefreshCw, Loader2, ChevronRight, Wrench,
  Phone, MapPin, Hash, ClipboardList,
} from "lucide-react";

/**
 * Classificação de Clientes + Técnicos Atribuídos
 *
 * Mostra:
 *  - Cards de resumo por classificação (persistente / recorrente / esporádico / eventual)
 *  - Tabela com filtros: cada linha = cliente com chamados nos últimos 90d
 *  - Colunas: cliente, plano, filial, classificação, tickets 30/60/90d,
 *    último diagnóstico, status, técnico responsável
 *  - Filtro por classificação clicando nos cards
 *
 * Auto-refresh a cada 60s.
 */
export default function ClientsClassificationPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState(null); // null = todos
  const [err, setErr] = useState(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true); else setRefreshing(true);
    try {
      const r = await api.clientsClassification({ limit: 200 });
      setData(r);
      setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      if (!silent) setLoading(false); else setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(() => load(true), 60000);
    return () => clearInterval(id);
  }, [load]);

  const filteredItems = useMemo(() => {
    const items = data?.items || [];
    if (!filter) return items;
    return items.filter((i) => i.classification === filter);
  }, [data, filter]);

  if (loading) {
    return (
      <Card style={{ padding: 30, textAlign: "center" }}>
        <Loader2 size={20} className="animate-spin" /> Analisando clientes…
      </Card>
    );
  }
  if (err) {
    return (
      <Card style={{ padding: 16, borderColor: "#dc2626" }}>
        <AlertCircle size={16} color="#dc2626" /> Falha ao carregar: {err}
      </Card>
    );
  }

  const summary = data?.summary || { total: 0, by_classification: {} };
  const bc = summary.by_classification || {};

  return (
    <div data-testid="clients-classification-panel" style={{ display: "grid", gap: 12 }}>
      {/* Header */}
      <Card style={{ padding: 14 }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          flexWrap: "wrap", gap: 8,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 9,
              background: "linear-gradient(135deg,#0f766e,#14b8a6)",
              display: "grid", placeItems: "center",
            }}>
              <Users size={18} color="white" strokeWidth={2} fill="none" />
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 14 }}>
                Classificação de Clientes & Técnicos
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Análise dos últimos 90 dias · {summary.total} clientes com chamados
              </div>
            </div>
          </div>
          <button
            onClick={() => load(true)}
            data-testid="clients-classification-refresh"
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
      </Card>

      {/* Cards de resumo (também atuam como filtro) */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 10,
      }}>
        <SummaryCard
          label="Persistente"
          count={bc.persistente || 0}
          desc="3+ chamados em 30d"
          color="#dc2626"
          bg="#fef2f2"
          active={filter === "persistente"}
          onClick={() => setFilter(filter === "persistente" ? null : "persistente")}
          testid="summary-persistente"
        />
        <SummaryCard
          label="Recorrente"
          count={bc.recorrente || 0}
          desc="2 em 60d"
          color="#ea580c"
          bg="#fff7ed"
          active={filter === "recorrente"}
          onClick={() => setFilter(filter === "recorrente" ? null : "recorrente")}
          testid="summary-recorrente"
        />
        <SummaryCard
          label="Esporádico"
          count={bc.esporádico || 0}
          desc="1 em 90d"
          color="#ca8a04"
          bg="#fefce8"
          active={filter === "esporádico"}
          onClick={() => setFilter(filter === "esporádico" ? null : "esporádico")}
          testid="summary-esporadico"
        />
        <SummaryCard
          label="Total ativos"
          count={summary.total}
          desc="todos os clientes"
          color="#0f766e"
          bg="#f0fdfa"
          active={filter === null}
          onClick={() => setFilter(null)}
          testid="summary-total"
        />
        <SummaryCard
          label="Reincidência crítica"
          count={summary.critical_reincidencia || 0}
          desc="mesmo téc 3+× sem resolver"
          color="#7f1d1d"
          bg="#fef2f2"
          active={false}
          onClick={() => {}}
          testid="summary-reincidencia"
        />
      </div>

      {/* Tabela */}
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{
          padding: "10px 14px",
          background: "var(--bg-elevated)",
          borderBottom: "1px solid var(--border-default)",
          display: "flex", justifyContent: "space-between", alignItems: "center",
          gap: 8,
        }}>
          <div style={{ fontWeight: 700, fontSize: 13 }}>
            {filter ? (
              <>Filtrando por <strong style={{ textTransform: "capitalize" }}>
                {filter}</strong> ({filteredItems.length})</>
            ) : (
              <>Clientes ({filteredItems.length})</>
            )}
          </div>
          {filter && (
            <button
              onClick={() => setFilter(null)}
              data-testid="clients-clear-filter"
              style={{
                padding: "3px 8px", border: "1px solid var(--border-default)",
                background: "transparent", color: "var(--text-secondary)",
                fontSize: 10, fontWeight: 600, borderRadius: 4,
                cursor: "pointer",
              }}
            >Limpar filtro</button>
          )}
        </div>
        <div style={{ maxHeight: 600, overflow: "auto" }}>
          <div className="table-wrap" style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}><table style={{ width: "100%", minWidth: 640, borderCollapse: "collapse", fontSize: 12,
          }}>
            <thead style={{
              background: "var(--bg-card)",
              position: "sticky", top: 0, zIndex: 1,
            }}>
              <tr>
                <Th>Cliente</Th>
                <Th>Plano / Filial</Th>
                <Th>Classificação</Th>
                <Th align="center">30d</Th>
                <Th align="center">60d</Th>
                <Th align="center">90d</Th>
                <Th>Último chamado</Th>
                <Th>Técnico</Th>
                <Th>Reincidência</Th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.length === 0 && (
                <tr><td colSpan={9} style={{
                  padding: 30, textAlign: "center", color: "var(--text-muted)",
                  fontSize: 12,
                }}>
                  {filter
                    ? `Nenhum cliente classificado como "${filter}" no momento. ✨`
                    : "Nenhum chamado de reparo nos últimos 90 dias."}
                </td></tr>
              )}
              {filteredItems.map((c) => <ClientRow key={c.client_id} c={c} />)}
            </tbody>
          </table></div>
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------

function SummaryCard({ label, count, desc, color, bg, active, onClick, testid }) {
  return (
    <button
      onClick={onClick}
      data-testid={testid}
      style={{
        padding: 12,
        background: active ? bg : "var(--bg-card)",
        border: active ? `2px solid ${color}` : "1px solid var(--border-default)",
        borderRadius: 8,
        cursor: "pointer",
        textAlign: "left",
        transition: "all .15s",
      }}
    >
      <div style={{
        fontSize: 10, color: "var(--text-muted)", fontWeight: 700,
        textTransform: "uppercase", letterSpacing: 0.5,
      }}>{label}</div>
      <div style={{
        fontSize: 28, fontWeight: 800, color, lineHeight: 1.1, marginTop: 2,
        fontFamily: "var(--font-mono, ui-monospace)",
      }}>{count}</div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 1 }}>
        {desc}
      </div>
    </button>
  );
}

function Th({ children, align = "left" }) {
  return (
    <th style={{
      padding: "8px 12px",
      textAlign: align,
      fontSize: 11,
      fontWeight: 700,
      color: "var(--text-muted)",
      borderBottom: "1px solid var(--border-default)",
      textTransform: "uppercase",
      letterSpacing: 0.3,
      whiteSpace: "nowrap",
    }}>{children}</th>
  );
}

function Td({ children, align = "left", style = {} }) {
  return (
    <td style={{
      padding: "10px 12px",
      borderBottom: "1px solid var(--border-default)",
      verticalAlign: "top",
      textAlign: align,
      ...style,
    }}>{children}</td>
  );
}

function ClientRow({ c }) {
  const cls = c.classification;
  const styleMap = {
    persistente: { bg: "#fef2f2", color: "#dc2626", label: "🔴 Persistente" },
    recorrente: { bg: "#fff7ed", color: "#ea580c", label: "🟠 Recorrente" },
    esporádico: { bg: "#fefce8", color: "#ca8a04", label: "🟡 Esporádico" },
    eventual: { bg: "#f0fdf4", color: "#16a34a", label: "🟢 Eventual" },
  };
  const cs = styleMap[cls] || styleMap.eventual;
  const tech = c.last_technician;
  const lastAge = c.last_ticket_at
    ? Math.round((Date.now() - new Date(c.last_ticket_at).getTime()) / 86400000)
    : null;

  return (
    <tr data-testid={`client-row-${c.client_id}`}>
      <Td>
        <div style={{ fontWeight: 700, fontSize: 12,
                       color: "var(--text-primary)" }}>
          {c.client_name || "—"}
          {c.client_nickname && c.client_nickname !== c.client_name && (
            <span style={{ marginLeft: 5, color: "var(--text-muted)",
                            fontWeight: 500, fontSize: 11 }}>
              ({c.client_nickname})
            </span>
          )}
        </div>
        {c.phone && (
          <div style={{ fontSize: 11, color: "var(--text-muted)",
                         marginTop: 2, fontFamily: "ui-monospace, monospace" }}>
            <Phone size={9} style={{ display: "inline", marginRight: 3 }} />
            +{c.phone}
          </div>
        )}
        {c.external_code && (
          <div style={{ fontSize: 10, color: "var(--text-muted)",
                         marginTop: 1 }}>
            <Hash size={9} style={{ display: "inline" }} /> {c.external_code}
          </div>
        )}
      </Td>
      <Td>
        {c.plan_name && (
          <div style={{ fontWeight: 600, fontSize: 11,
                         color: "var(--text-primary)" }}>
            {c.plan_name}
          </div>
        )}
        {c.branch && (
          <div style={{ fontSize: 10, color: "var(--text-muted)",
                         marginTop: 2, display: "flex", alignItems: "center", gap: 3 }}>
            <MapPin size={9} /> {c.branch}
          </div>
        )}
      </Td>
      <Td>
        <span style={{
          padding: "3px 8px", borderRadius: 4, fontSize: 10,
          fontWeight: 700, background: cs.bg, color: cs.color,
          whiteSpace: "nowrap",
        }}>{cs.label}</span>
        {c.last_diagnosis && (
          <div style={{ fontSize: 10, color: "var(--text-muted)",
                         marginTop: 4 }}>
            Diag: <strong style={{ color: "var(--text-primary)" }}>
              {c.last_diagnosis}
            </strong>
          </div>
        )}
      </Td>
      <Td align="center">
        <NumCell n={c.tickets_30d} severity="high" />
      </Td>
      <Td align="center">
        <NumCell n={c.tickets_60d} severity="mid" />
      </Td>
      <Td align="center">
        <NumCell n={c.tickets_90d} severity="low" />
      </Td>
      <Td>
        {lastAge !== null ? (
          <>
            <div style={{ fontSize: 11, fontWeight: 600 }}>
              {lastAge === 0 ? "hoje" : `há ${lastAge}d`}
            </div>
            <div style={{ fontSize: 10, color: "var(--text-muted)",
                           marginTop: 2 }}>
              <StatusPill status={c.last_ticket_status} />
              {c.last_ticket_priority === "prioridade" && (
                <span style={{
                  marginLeft: 4, padding: "1px 5px", borderRadius: 3,
                  background: "#fef2f2", color: "#dc2626", fontSize: 9,
                  fontWeight: 700,
                }}>PRIORIDADE</span>
              )}
            </div>
          </>
        ) : "—"}
      </Td>
      <Td>
        {tech ? (
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{
              width: 26, height: 26, borderRadius: "50%",
              background: tech.avatar_url
                ? `url(${tech.avatar_url}) center/cover`
                : "linear-gradient(135deg,#0f766e,#14b8a6)",
              display: "grid", placeItems: "center", color: "white",
              fontSize: 10, fontWeight: 700, flexShrink: 0,
            }}>
              {!tech.avatar_url && (tech.name || "?").charAt(0).toUpperCase()}
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 11, fontWeight: 600,
                             whiteSpace: "nowrap", overflow: "hidden",
                             textOverflow: "ellipsis", maxWidth: 130 }}>
                {tech.name}
              </div>
              <div style={{ fontSize: 9, color: "var(--text-muted)" }}>
                {tech.role || "Técnico"}
              </div>
            </div>
          </div>
        ) : (
          <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
            sem técnico
          </span>
        )}
        {c.all_technicians && c.all_technicians.length > 1 && (
          <div style={{ fontSize: 9, color: "var(--text-muted)",
                         marginTop: 2 }}>
            +{c.all_technicians.length - 1} outro(s) técnico(s) já atendeu
          </div>
        )}
      </Td>
      <Td>
        <TechReincidenciaCell c={c} />
      </Td>
    </tr>
  );
}

function TechReincidenciaCell({ c }) {
  const breakdown = c.tech_breakdown || [];
  const critical = c.critical_reincidencia;

  if (breakdown.length === 0) {
    return <span style={{ color: "var(--text-muted)", fontSize: 11 }}>—</span>;
  }

  // Identifica técnico com 3+ visitas E pendências não resolvidas
  const problematic = breakdown.find(
    (t) => t.count >= 3 && t.unresolved_count >= 1,
  );

  return (
    <div style={{ minWidth: 130 }}>
      {critical && problematic ? (
        <div
          title={
            `⚠ ${problematic.name} foi ${problematic.count}x neste cliente ` +
            `com ${problematic.unresolved_count} caso(s) não resolvido(s). ` +
            `Possível problema estrutural — considere reescalar.`
          }
          style={{
            padding: "4px 7px", borderRadius: 4,
            background: "#fef2f2", border: "1px solid #fecaca",
            color: "#991b1b", fontSize: 10, fontWeight: 700,
            display: "inline-flex", alignItems: "center", gap: 3,
            marginBottom: 4,
          }}
        >
          ⚠ {problematic.name.split(" ")[0]} ×{problematic.count}
        </div>
      ) : null}
      <div style={{ fontSize: 10, color: "var(--text-secondary)",
                     lineHeight: 1.6 }}>
        {breakdown.slice(0, 3).map((t) => (
          <div key={t.tech_id} style={{
            display: "flex", justifyContent: "space-between", gap: 6,
          }}>
            <span style={{
              whiteSpace: "nowrap", overflow: "hidden",
              textOverflow: "ellipsis", maxWidth: 90,
              color: t.count >= 3 ? "#dc2626"
                : t.count >= 2 ? "#ea580c" : "var(--text-secondary)",
              fontWeight: t.count >= 2 ? 700 : 500,
            }}>{t.name}</span>
            <span style={{
              fontFamily: "var(--font-mono, ui-monospace)",
              fontWeight: 700,
              color: t.count >= 3 ? "#dc2626" : "var(--text-primary)",
            }}>
              {t.count}×
              {t.unresolved_count > 0 && (
                <span style={{ color: "#ea580c", marginLeft: 2 }}>
                  ({t.unresolved_count})
                </span>
              )}
            </span>
          </div>
        ))}
        {breakdown.length > 3 && (
          <div style={{ color: "var(--text-muted)", fontSize: 9, marginTop: 2 }}>
            +{breakdown.length - 3} outro(s)
          </div>
        )}
      </div>
    </div>
  );
}

function NumCell({ n, severity }) {
  let color = "var(--text-muted)";
  if (n >= 3 && severity === "high") color = "#dc2626";
  else if (n >= 2 && severity === "mid") color = "#ea580c";
  else if (n >= 1) color = "var(--text-primary)";
  return (
    <span style={{
      fontWeight: 700, fontFamily: "var(--font-mono, ui-monospace)",
      color, fontSize: 13,
    }}>{n}</span>
  );
}

function StatusPill({ status }) {
  if (!status) return null;
  const map = {
    pendente: { bg: "#fef3c7", color: "#92400e" },
    aceito: { bg: "#dbeafe", color: "#1e40af" },
    em_andamento: { bg: "#fae8ff", color: "#86198f" },
    finalizado: { bg: "#dcfce7", color: "#166534" },
    cancelado: { bg: "#fee2e2", color: "#991b1b" },
  };
  const s = map[status] || { bg: "var(--bg-elevated)", color: "var(--text-secondary)" };
  return (
    <span style={{
      padding: "1px 5px", borderRadius: 3, fontSize: 9, fontWeight: 700,
      background: s.bg, color: s.color,
    }}>{status}</span>
  );
}
