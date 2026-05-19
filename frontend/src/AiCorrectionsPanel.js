import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import { Wand2, Search, Trash2, CalendarDays, MessageSquare, RefreshCw } from "lucide-react";

/**
 * AI Corrections Panel — visão analítica das correções que a Isabella IA
 * recebeu. Funciona como painel de qualidade do agente: onde a IA mais
 * erra, com filtro e busca + gráfico semanal.
 */
export default function AiCorrectionsPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true); setError("");
    try {
      const r = await api.aiCorrectionList(200);
      setItems(r.items || []);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  // Todas as tags únicas
  const allTags = useMemo(() => {
    const s = new Set();
    items.forEach((it) => (it.tags || []).forEach((t) => s.add(t)));
    return Array.from(s).sort();
  }, [items]);

  // Filtro + busca
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((it) => {
      if (tagFilter && !(it.tags || []).includes(tagFilter)) return false;
      if (!q) return true;
      const hay = [
        it.user_question, it.ai_original_reply, it.correct_reply,
        it.reason, it.corrected_by, it.phone,
      ].filter(Boolean).join(" ").toLowerCase();
      return hay.includes(q);
    });
  }, [items, search, tagFilter]);

  // Agregado por semana (gráfico simples)
  const weekly = useMemo(() => buildWeekly(items, 12), [items]);
  const maxWeek = Math.max(1, ...weekly.map((w) => w.count));

  // Top phones com mais correções
  const topPhones = useMemo(() => {
    const m = new Map();
    items.forEach((it) => m.set(it.phone, (m.get(it.phone) || 0) + 1));
    return Array.from(m.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);
  }, [items]);

  const handleDelete = async (id) => {
    if (!await window.confirm("Apagar esta correção? A IA pode voltar a cometer este erro.")) return;
    try {
      await api.aiCorrectionDelete(id);
      setItems((arr) => arr.filter((c) => c.id !== id));
    } catch (e) {
      await window.alert("Falha ao apagar: " + e.message);
    }
  };

  return (
    <div data-testid="ai-corrections-panel" style={{ padding: 20, maxWidth: 1280, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 16, marginBottom: 18, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--text-primary)", margin: 0, display: "flex", alignItems: "center", gap: 10 }}>
            <Wand2 size={20} /> Correções da Isabella IA
          </h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, margin: "4px 0 0" }}>
            Cada correção vira <strong>memória permanente</strong> da IA. Use para auditoria de qualidade e identificação de pontos cegos do atendimento.
          </p>
        </div>
        <button onClick={load} disabled={loading}
                className="btn btn-sm" style={{ background: "var(--accent)", color: "white", display: "flex", alignItems: "center", gap: 6 }}
                data-testid="ai-corr-reload">
          <RefreshCw size={13} className={loading ? "spin" : ""} /> Recarregar
        </button>
      </div>

      {/* KPIs */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 18 }}>
        <StatTile label="Total de correções" value={items.length} icon={<Wand2 size={16} />} />
        <StatTile label="Últimos 7 dias" value={countLastDays(items, 7)} icon={<CalendarDays size={16} />} accent="#f59e0b" />
        <StatTile label="Conversas únicas" value={new Set(items.map((i) => i.phone)).size} icon={<MessageSquare size={16} />} accent="#0ea5e9" />
        <StatTile label="Reenviadas ao cliente" value={items.filter((i) => i.resent_to_client).length} accent="#10b981" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 18, alignItems: "start" }}>
        {/* Coluna esquerda: lista + filtros */}
        <Card style={{ padding: 0 }}>
          <div style={{ padding: 14, borderBottom: "1px solid var(--border-color)", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <div style={{ flex: 1, position: "relative", minWidth: 240 }}>
              <Search size={14} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)" }} />
              <input
                data-testid="ai-corr-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar por pergunta, resposta, motivo, telefone..."
                style={{
                  width: "100%", padding: "8px 12px 8px 32px",
                  border: "1px solid var(--border-color)", borderRadius: 8,
                  background: "var(--bg-input)", color: "var(--text-primary)",
                  fontSize: 13, boxSizing: "border-box",
                }}
              />
            </div>
            <select value={tagFilter} onChange={(e) => setTagFilter(e.target.value)}
                     data-testid="ai-corr-tag-filter"
                     style={{ padding: "8px 10px", border: "1px solid var(--border-color)",
                              borderRadius: 8, background: "var(--bg-input)",
                              color: "var(--text-primary)", fontSize: 12 }}>
              <option value="">Todas as tags</option>
              {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          {error && <div style={{ padding: 12, color: "#dc2626", fontSize: 12, background: "rgba(239,68,68,.08)" }}>{error}</div>}

          {loading && <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>Carregando...</div>}

          {!loading && filtered.length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
              {items.length === 0
                ? "Ainda não há correções salvas. Quando o gestor corrigir uma resposta da Isabella no chat, ela aparecerá aqui."
                : "Nenhuma correção bate com este filtro."}
            </div>
          )}

          <div style={{ maxHeight: 600, overflowY: "auto" }}>
            {filtered.map((c) => <CorrectionRow key={c.id} item={c} onDelete={() => handleDelete(c.id)} />)}
          </div>
        </Card>

        {/* Coluna direita: gráfico semanal + top phones */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <Card style={{ padding: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)", letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 10 }}>
              Correções por semana
            </div>
            {weekly.length === 0 ? (
              <div style={{ color: "var(--text-muted)", fontSize: 12 }}>Sem dados ainda</div>
            ) : (
              <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 100 }}>
                {weekly.map((w) => (
                  <div key={w.label} title={`${w.label} · ${w.count} correções`}
                        style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                    <div style={{
                      width: "100%", background: w.count ? "#0ea5e9" : "rgba(0,0,0,.05)",
                      height: `${(w.count / maxWeek) * 80}px`,
                      minHeight: 4, borderRadius: "4px 4px 0 0",
                      transition: "background 0.2s",
                    }} />
                    <div style={{ fontSize: 8, color: "var(--text-muted)", whiteSpace: "nowrap", transform: "rotate(-45deg)", transformOrigin: "center" }}>
                      {w.label}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card style={{ padding: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)", letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 10 }}>
              Conversas com mais correções
            </div>
            {topPhones.length === 0 ? (
              <div style={{ color: "var(--text-muted)", fontSize: 12 }}>Sem dados</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {topPhones.map(([phone, count]) => (
                  <div key={phone} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, padding: "6px 8px", background: "var(--bg-surface-2)", borderRadius: 6 }}>
                    <span style={{ color: "var(--text-primary)", fontFamily: "ui-monospace, monospace" }}>{phone}</span>
                    <span style={{ color: "#0ea5e9", fontWeight: 700 }}>{count}×</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>

      <style>{`
        .spin { animation: spin 1s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

function StatTile({ label, value, icon, accent = "#0ea5e9" }) {
  return (
    <Card style={{ padding: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 10, color: "var(--text-muted)", fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase" }}>
        {label}
        {icon && <span style={{ color: accent }}>{icon}</span>}
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, color: "var(--text-primary)", marginTop: 4 }}>{value}</div>
    </Card>
  );
}

function CorrectionRow({ item, onDelete }) {
  const [open, setOpen] = useState(false);
  const date = item.created_at ? new Date(item.created_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "";
  return (
    <div data-testid={`ai-corr-row-${item.id}`} style={{
      padding: "12px 14px", borderBottom: "1px solid var(--border-color)",
      cursor: "pointer", transition: "background 0.15s",
    }} onClick={() => setOpen((v) => !v)}
       onMouseOver={(e) => e.currentTarget.style.background = "var(--bg-surface-2)"}
       onMouseOut={(e) => e.currentTarget.style.background = "transparent"}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 600, marginBottom: 2 }}>
            {(item.user_question || "(sem pergunta)").slice(0, 120)}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-muted)", display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontFamily: "ui-monospace, monospace" }}>{item.phone}</span>
            <span>·</span>
            <span>{date}</span>
            <span>·</span>
            <span>por {item.corrected_by || "—"}</span>
            {item.resent_to_client && (
              <span style={{ color: "#10b981", fontWeight: 700 }}>✓ Reenviada</span>
            )}
          </div>
        </div>
        <button onClick={(e) => { e.stopPropagation(); onDelete(); }}
                 data-testid={`ai-corr-delete-${item.id}`}
                 title="Apagar correção"
                 style={{ border: 0, background: "transparent", color: "#dc2626", cursor: "pointer", padding: 4 }}>
          <Trash2 size={13} />
        </button>
      </div>

      {open && (
        <div onClick={(e) => e.stopPropagation()} style={{ marginTop: 10, display: "grid", gap: 8, fontSize: 11.5 }}>
          <Field label="Resposta errada" color="#b91c1c" bg="#fef2f2" border="#fecaca" text={item.ai_original_reply} />
          <Field label="Resposta correta" color="#15803d" bg="#f0fdf4" border="#bbf7d0" text={item.correct_reply} />
          {item.reason && <Field label="Motivo" color="#475569" bg="#f8fafc" border="#e2e8f0" text={item.reason} />}
        </div>
      )}
    </div>
  );
}

function Field({ label, text, color, bg, border }) {
  return (
    <div>
      <div style={{ fontSize: 9, fontWeight: 700, color, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 3 }}>{label}</div>
      <div style={{ padding: "6px 10px", background: bg, border: `1px solid ${border}`, borderRadius: 6, color: "var(--text-primary)", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{text}</div>
    </div>
  );
}

function countLastDays(items, days) {
  const cutoff = Date.now() - days * 86400_000;
  return items.filter((i) => new Date(i.created_at).getTime() >= cutoff).length;
}

function buildWeekly(items, weeks = 12) {
  const buckets = new Array(weeks).fill(0).map((_, i) => {
    const offset = (weeks - 1 - i) * 7;
    const start = new Date(Date.now() - offset * 86400_000);
    start.setHours(0, 0, 0, 0);
    // Find Monday
    const day = start.getDay() || 7;
    start.setDate(start.getDate() - day + 1);
    const label = `${String(start.getDate()).padStart(2, "0")}/${String(start.getMonth() + 1).padStart(2, "0")}`;
    return { start: start.getTime(), end: start.getTime() + 7 * 86400_000, label, count: 0 };
  });
  items.forEach((it) => {
    const t = new Date(it.created_at).getTime();
    const bucket = buckets.find((b) => t >= b.start && t < b.end);
    if (bucket) bucket.count++;
  });
  return buckets;
}
