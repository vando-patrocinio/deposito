import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  CalendarDays, Plus, Trash2, Edit3, MapPin, Building2, Flag,
  RefreshCw, Sparkles, X, AlertCircle, Search,
} from "lucide-react";
import { api } from "@/api";

/* =============================================================
   FeriadosPanel — Calendário de feriados (RH)
   - Lista cronológica por ano
   - CRUD completo
   - Botão "Importar feriados nacionais BR" (Tiradentes, Carnaval,
     Páscoa via algoritmo de Gauss, Natal, etc)
============================================================= */
const TIPOS = [
  { value: "nacional",  label: "Nacional",  color: "#dc2626", icon: Flag },
  { value: "estadual",  label: "Estadual",  color: "#f59e0b", icon: MapPin },
  { value: "municipal", label: "Municipal", color: "#0ea5e9", icon: MapPin },
  { value: "empresa",   label: "Empresa",   color: "#7c3aed", icon: Building2 },
];
const MONTHS_FULL = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                      "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];

export default function FeriadosPanel() {
  const [items, setItems] = useState([]);
  const [pracas, setPracas] = useState([]);
  const [year, setYear] = useState(new Date().getFullYear());
  const [tipo, setTipo] = useState("");
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [seedBusy, setSeedBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const r = await api.feriadosList(year, tipo || undefined);
      setItems(r.items || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [year, tipo]);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    api.listPracas().then((list) => setPracas(Array.isArray(list) ? list : []))
      .catch(() => setPracas([]));
  }, []);

  const filtered = useMemo(() => {
    if (!filter) return items;
    const f = filter.toLowerCase();
    return items.filter((x) => x.nome.toLowerCase().includes(f));
  }, [items, filter]);

  // agrupa por mês
  const byMonth = useMemo(() => {
    const out = {};
    filtered.forEach((it) => {
      const m = parseInt(it.data.slice(5, 7), 10);
      out[m] = out[m] || [];
      out[m].push(it);
    });
    return out;
  }, [filtered]);

  async function seedBr() {
    if (!window.confirm(`Importar feriados nacionais brasileiros de ${year}? ` +
                              `Não duplica os que já existem.`)) return;
    setSeedBusy(true);
    try {
      const r = await api.feriadosSeedBr(year);
      await reload();
      window.alert(`✅ Importação concluída.\n\n` +
                       `Inseridos: ${r.inserted}\n` +
                       `Já existiam: ${r.skipped}`);
    } catch (e) {
      window.alert(extractErr(e));
    } finally { setSeedBusy(false); }
  }

  async function remove(it) {
    if (!window.confirm(`Excluir "${it.nome}" (${fmtDate(it.data)})?`)) return;
    try {
      await api.feriadoDelete(it.id);
      await reload();
    } catch (e) {
      window.alert(extractErr(e));
    }
  }

  const stats = useMemo(() => {
    const out = { nacional: 0, estadual: 0, municipal: 0, empresa: 0 };
    items.forEach((it) => { if (out[it.tipo] != null) out[it.tipo]++; });
    return out;
  }, [items]);

  return (
    <div data-testid="feriados-panel" style={{ display: "grid", gap: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                       flexWrap: "wrap" }}>
        <div style={{
          width: 42, height: 42, borderRadius: 10,
          background: "linear-gradient(135deg, #dc2626, #f59e0b)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 12px rgba(220,38,38,.3)",
        }}>
          <CalendarDays size={20} strokeWidth={1.75} />
        </div>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800,
                            letterSpacing: "-0.02em" }}>
            Feriados
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Calendário oficial nacional, estadual, municipal e da empresa.
          </div>
        </div>
        <span style={{ flex: 1 }} />
        <button onClick={reload} style={btn("ghost")} title="Atualizar">
          <RefreshCw size={13} />
        </button>
        <button onClick={seedBr} disabled={seedBusy}
                data-testid="feriados-seed-btn"
                style={btn("ghost", "md", seedBusy)}>
          <Sparkles size={13} />
          {seedBusy ? "Importando..." : `Importar BR ${year}`}
        </button>
        <button onClick={() => setEditing({})}
                data-testid="feriados-add-btn"
                style={btn("primary")}>
          <Plus size={14} /> Novo feriado
        </button>
      </div>

      {/* KPIs por tipo */}
      <div style={{ display: "grid",
                       gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                       gap: 10 }}>
        {TIPOS.map((t) => (
          <Kpi key={t.value} label={t.label} accent={t.color}
                value={stats[t.value]} icon={t.icon} />
        ))}
      </div>

      {/* Filtros */}
      <div className="surface" style={{
        padding: 12, borderRadius: 10,
        border: "1px solid var(--border-default)",
        display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
      }}>
        <div style={{ position: "relative", flex: 1, minWidth: 220 }}>
          <Search size={14} style={{ position: "absolute", left: 10, top: 10,
                                          color: "var(--text-muted)" }} />
          <input value={filter} onChange={(e) => setFilter(e.target.value)}
                 data-testid="feriados-filter"
                 placeholder="Filtrar por nome..."
                 style={{ ...input(), paddingLeft: 30 }} />
        </div>
        <select value={tipo} onChange={(e) => setTipo(e.target.value)}
                data-testid="feriados-tipo-filter" style={input(160)}>
          <option value="">Todos os tipos</option>
          {TIPOS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <select value={year} onChange={(e) => setYear(parseInt(e.target.value, 10))}
                data-testid="feriados-year" style={input(110)}>
          {[year + 1, year, year - 1, year - 2].map((y) =>
            <option key={y} value={y}>{y}</option>)}
        </select>
      </div>

      {/* Lista por mês */}
      {loading ? (
        <div className="surface" style={{ padding: 30, textAlign: "center",
                                                color: "var(--text-muted)",
                                                borderRadius: 10,
                                                border: "1px solid var(--border-default)" }}>
          Carregando...
        </div>
      ) : filtered.length === 0 ? (
        <div className="surface" style={{
          padding: 40, textAlign: "center", color: "var(--text-muted)",
          borderRadius: 10, border: "1px solid var(--border-default)", fontSize: 13,
        }}>
          <CalendarDays size={32} strokeWidth={1.25}
                          style={{ opacity: .4, marginBottom: 8 }} />
          <div style={{ fontWeight: 700, marginBottom: 4 }}>
            Nenhum feriado em {year}{filter ? " com esse filtro" : ""}.
          </div>
          <div style={{ fontSize: 11 }}>
            Clique em <strong>Importar BR {year}</strong> para popular os nacionais
            ou <strong>Novo feriado</strong> para adicionar manualmente.
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {Object.keys(byMonth).sort((a, b) => parseInt(a) - parseInt(b))
            .map((m) => (
            <div key={m} className="surface" style={{
              borderRadius: 10, border: "1px solid var(--border-default)",
              overflow: "hidden",
            }}>
              <div style={{
                padding: "8px 14px",
                background: "var(--bg-surface-2)",
                borderBottom: "1px solid var(--border-default)",
                fontSize: 11, fontWeight: 800, color: "var(--text-muted)",
                textTransform: "uppercase", letterSpacing: ".06em",
              }}>
                {MONTHS_FULL[parseInt(m) - 1]} ·
                <span style={{ marginLeft: 6, color: "var(--text-primary)" }}>
                  {byMonth[m].length}
                </span>
              </div>
              {byMonth[m].map((it) => (
                <FeriadoRow key={it.id} item={it} pracas={pracas}
                              onEdit={() => setEditing(it)}
                              onDelete={() => remove(it)} />
              ))}
            </div>
          ))}
        </div>
      )}

      {editing !== null && (
        <FeriadoModal item={editing} pracas={pracas}
                       onClose={() => setEditing(null)}
                       onSaved={() => { setEditing(null); reload(); }} />
      )}
    </div>
  );
}

function FeriadoRow({ item, pracas, onEdit, onDelete }) {
  const t = TIPOS.find((x) => x.value === item.tipo) || TIPOS[0];
  const Icon = t.icon;
  const d = new Date(item.data + "T12:00:00");
  const dia = d.getDate();
  const dow = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"][d.getDay()];
  const linkedPracaIds = item.praca_ids || [];
  const linkedPracaNames = linkedPracaIds
    .map((id) => (pracas.find((p) => p.id === id) || {}).name)
    .filter(Boolean);
  const aplica = linkedPracaIds.length === 0
    ? "Todos os colaboradores"
    : `${linkedPracaIds.length} praça${linkedPracaIds.length > 1 ? "s" : ""}`;

  return (
    <div data-testid={`feriado-row-${item.id}`} style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "10px 14px", borderTop: "1px solid var(--border-default)",
    }}>
      <div style={{
        width: 46, height: 46, borderRadius: 8,
        background: t.color, color: "white",
        display: "grid", placeItems: "center", flexShrink: 0,
      }}>
        <div style={{ fontSize: 9, fontWeight: 800,
                          textTransform: "uppercase", opacity: .85 }}>
          {dow}
        </div>
        <div style={{ fontSize: 18, fontWeight: 800, lineHeight: 1,
                          marginTop: -2 }}>
          {dia}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 700,
                          color: "var(--text-primary)" }}>
          {item.nome}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                          marginTop: 3, fontSize: 11,
                          color: "var(--text-muted)" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <Icon size={11} color={t.color} />
            {t.label}
          </span>
          {item.uf && <span>UF: <strong>{item.uf}</strong></span>}
          {item.municipio && <span>{item.municipio}</span>}
          {item.recorrente && <span style={{ color: "#10b981" }}>↺ recorrente</span>}
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            padding: "1px 7px", borderRadius: 999,
            background: linkedPracaIds.length === 0 ? "#dcfce7" : "#dbeafe",
            color: linkedPracaIds.length === 0 ? "#166534" : "#1e40af",
            fontSize: 10, fontWeight: 700,
          }}
                title={linkedPracaNames.join(", ") || "Aplica a todos"}>
            🎯 {aplica}
          </span>
          {item.observacao && (
            <span style={{ fontStyle: "italic", maxWidth: 280,
                              overflow: "hidden", textOverflow: "ellipsis",
                              whiteSpace: "nowrap" }}>
              {item.observacao}
            </span>
          )}
        </div>
      </div>
      <button onClick={onEdit}
              data-testid={`feriado-edit-${item.id}`}
              style={btn("ghost", "xs")} title="Editar">
        <Edit3 size={11} />
      </button>
      <button onClick={onDelete}
              data-testid={`feriado-del-${item.id}`}
              style={{ ...btn("ghost", "xs"), color: "#dc2626" }}
              title="Excluir">
        <Trash2 size={11} />
      </button>
    </div>
  );
}

function FeriadoModal({ item, pracas, onClose, onSaved }) {
  const isNew = !item.id;
  const [data, setData] = useState(item.data || todayISO());
  const [nome, setNome] = useState(item.nome || "");
  const [tipo, setTipo] = useState(item.tipo || "nacional");
  const [uf, setUf] = useState(item.uf || "");
  const [municipio, setMunicipio] = useState(item.municipio || "");
  const [recorrente, setRecorrente] = useState(item.recorrente !== false);
  const [observacao, setObservacao] = useState(item.observacao || "");
  const [pracaIds, setPracaIds] = useState(item.praca_ids || []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function togglePraca(id) {
    setPracaIds((cur) => cur.includes(id)
      ? cur.filter((x) => x !== id) : [...cur, id]);
  }
  function selectAllPracas() { setPracaIds(pracas.map((p) => p.id)); }
  function clearPracas() { setPracaIds([]); }

  async function submit() {
    setErr("");
    if (!data) { setErr("Informe a data."); return; }
    if (!nome.trim()) { setErr("Informe o nome."); return; }
    setBusy(true);
    const payload = {
      data, nome: nome.trim(), tipo,
      uf: uf.trim().toUpperCase() || null,
      municipio: municipio.trim() || null,
      recorrente, observacao: observacao.trim() || null,
      praca_ids: pracaIds,
    };
    try {
      if (isNew) await api.feriadoCreate(payload);
      else await api.feriadoUpdate(item.id, payload);
      onSaved();
    } catch (e) {
      setErr(extractErr(e));
    } finally { setBusy(false); }
  }

  return (
    <div data-testid="feriado-modal" style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
      display: "grid", placeItems: "center", zIndex: 1000,
    }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ width: 480, maxWidth: "92vw", borderRadius: 12,
                       background: "var(--bg-surface)",
                       border: "1px solid var(--border-default)" }}>
        <div style={{ padding: "14px 20px",
                          borderBottom: "1px solid var(--border-default)",
                          display: "flex", alignItems: "center", gap: 10 }}>
          <CalendarDays size={18} color="#dc2626" />
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800 }}>
            {isNew ? "Novo feriado" : "Editar feriado"}
          </h3>
          <span style={{ flex: 1 }} />
          <button onClick={onClose} style={btn("ghost", "xs")}>
            <X size={14} />
          </button>
        </div>
        <div style={{ padding: 20, display: "grid", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div>
              <Lbl>Data *</Lbl>
              <input type="date" value={data}
                     onChange={(e) => setData(e.target.value)}
                     data-testid="feriado-data" style={input()} />
            </div>
            <div>
              <Lbl>Tipo *</Lbl>
              <select value={tipo} onChange={(e) => setTipo(e.target.value)}
                      data-testid="feriado-tipo" style={input()}>
                {TIPOS.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <Lbl>Nome *</Lbl>
            <input value={nome} onChange={(e) => setNome(e.target.value)}
                   data-testid="feriado-nome"
                   placeholder="Ex.: Aniversário da cidade" style={input()} />
          </div>
          {(tipo === "estadual" || tipo === "municipal") && (
            <div style={{ display: "grid", gridTemplateColumns: "100px 1fr",
                               gap: 10 }}>
              <div>
                <Lbl>UF</Lbl>
                <input value={uf} maxLength={2}
                       onChange={(e) => setUf(e.target.value)}
                       data-testid="feriado-uf"
                       placeholder="RJ" style={input()} />
              </div>
              {tipo === "municipal" && (
                <div>
                  <Lbl>Município</Lbl>
                  <input value={municipio}
                         onChange={(e) => setMunicipio(e.target.value)}
                         data-testid="feriado-municipio"
                         placeholder="Rio de Janeiro" style={input()} />
                </div>
              )}
            </div>
          )}
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Lbl>Aplica-se a</Lbl>
              <span style={{ flex: 1 }} />
              <button type="button" onClick={selectAllPracas}
                       data-testid="feriado-pracas-all"
                       style={{ ...btn("ghost", "xs"), fontSize: 10 }}>
                Selecionar todas
              </button>
              <button type="button" onClick={clearPracas}
                       data-testid="feriado-pracas-clear"
                       style={{ ...btn("ghost", "xs"), fontSize: 10 }}>
                Limpar
              </button>
            </div>
            {pracas.length === 0 ? (
              <div style={{ fontSize: 11, color: "var(--text-muted)",
                              fontStyle: "italic", padding: "8px 0" }}>
                Sem praças cadastradas — feriado valerá para todos.
              </div>
            ) : (
              <div style={{
                padding: 8, borderRadius: 8,
                border: "1px solid var(--border-default)",
                background: "var(--bg-surface-2)",
                maxHeight: 140, overflowY: "auto",
              }}>
                {pracaIds.length === 0 && (
                  <div style={{ fontSize: 11, color: "#166534",
                                    background: "#dcfce7", padding: 6,
                                    borderRadius: 6, marginBottom: 6,
                                    fontWeight: 700 }}>
                    🌍 Aplica para TODOS os colaboradores (nenhuma praça marcada)
                  </div>
                )}
                {pracas.map((p) => (
                  <label key={p.id} style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "4px 0", cursor: "pointer", fontSize: 12,
                  }}>
                    <input type="checkbox"
                           checked={pracaIds.includes(p.id)}
                           onChange={() => togglePraca(p.id)}
                           data-testid={`feriado-praca-${p.id}`} />
                    <strong>{p.name}</strong>
                    <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
                      {p.city} · {p.state}
                    </span>
                  </label>
                ))}
              </div>
            )}
            <p style={{ fontSize: 10, color: "var(--text-muted)",
                          margin: "4px 0 0" }}>
              💡 Marque praças específicas pra feriados estaduais/municipais —
              só colaboradores destas praças terão o dia como feriado.
              Deixe vazio pra valer pra todos.
            </p>
          </div>

          <div>
            <Lbl>Observação (opcional)</Lbl>
            <textarea value={observacao}
                      onChange={(e) => setObservacao(e.target.value)}
                      data-testid="feriado-obs"
                      rows={2} style={{ ...input(), resize: "vertical" }} />
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: 8,
                              fontSize: 12, cursor: "pointer" }}>
            <input type="checkbox" checked={recorrente}
                   onChange={(e) => setRecorrente(e.target.checked)}
                   data-testid="feriado-recorrente" />
            Feriado recorrente (todo ano)
          </label>
          {err && (
            <div data-testid="feriado-error" style={{
              background: "#fef2f2", color: "#991b1b", padding: 8,
              borderRadius: 6, fontSize: 12, fontWeight: 700,
              display: "flex", alignItems: "center", gap: 6,
            }}>
              <AlertCircle size={13} /> {err}
            </div>
          )}
        </div>
        <div style={{ padding: "12px 20px",
                          borderTop: "1px solid var(--border-default)",
                          display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={btn("ghost")}>Cancelar</button>
          <button onClick={submit} disabled={busy}
                  data-testid="feriado-save"
                  style={btn("primary", "md", busy)}>
            {busy ? "Salvando..." : (isNew ? "Criar" : "Salvar")}
          </button>
        </div>
      </div>
    </div>
  );
}

function Kpi({ label, value, accent, icon: Icon }) {
  return (
    <div className="surface" style={{
      padding: 12, borderRadius: 10,
      border: "1px solid var(--border-default)",
      borderLeft: `3px solid ${accent}`,
      background: "var(--bg-surface)",
      display: "flex", alignItems: "center", gap: 10,
    }}>
      <Icon size={18} color={accent} strokeWidth={1.75} />
      <div>
        <div style={{ fontSize: 10, fontWeight: 800, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: ".05em" }}>
          {label}
        </div>
        <div style={{ fontSize: 18, fontWeight: 800,
                          color: "var(--text-primary)",
                          marginTop: 2, letterSpacing: "-0.02em" }}>
          {value}
        </div>
      </div>
    </div>
  );
}

function Lbl({ children }) {
  return <label style={{ fontSize: 11, fontWeight: 800,
                              color: "var(--text-muted)",
                              textTransform: "uppercase",
                              letterSpacing: ".05em",
                              display: "block", marginBottom: 4 }}>{children}</label>;
}
function input(width) {
  return {
    width: width || "100%", padding: "8px 10px",
    border: "1px solid var(--border-default)", borderRadius: 8,
    fontSize: 13, background: "var(--bg-surface)",
    color: "var(--text-primary)", outline: "none",
  };
}
function btn(variant = "primary", size = "md", disabled = false) {
  const sizes = {
    xs: { padding: "4px 8px", fontSize: 11 },
    md: { padding: "8px 14px", fontSize: 12 },
  };
  const base = {
    ...(sizes[size] || sizes.md),
    borderRadius: 8, fontWeight: 800,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.6 : 1,
    display: "inline-flex", alignItems: "center", gap: 5,
  };
  if (variant === "primary")
    return { ...base, border: "1px solid #6366f1", background: "#6366f1", color: "white" };
  return { ...base, border: "1px solid var(--border-default)",
              background: "var(--bg-surface)", color: "var(--text-primary)" };
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString("pt-BR");
}
function todayISO() {
  return new Date().toISOString().slice(0, 10);
}
function extractErr(e) {
  const d = e?.response?.data?.detail ?? e?.response?.data ?? e?.message;
  if (!d) return "Erro desconhecido.";
  if (typeof d === "string") return d;
  return JSON.stringify(d);
}
