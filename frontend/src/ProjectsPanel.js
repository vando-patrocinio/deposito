/* ProjectsPanel.js — Acompanhamento de Trabalho (Kanban).
 *
 * Inspirações: Trello, Linear, ClickUp, Splynx Field Service.
 *
 * Views: Kanban (default) | Lista.
 * Features:
 *  - 4 colunas: Backlog / Em andamento / Em revisão / Finalizado
 *  - Card com título, descrição, datas, prioridade, tags, assignees, files
 *  - Drag-and-drop entre colunas (HTML5 drag API)
 *  - Modal de detalhes com edição inline + upload de PDF/DOC/imagem
 *  - Filtros: prioridade, assignee
 *  - KPIs no topo (total, % concluído, em risco)
 *  - data-testids completos para automação
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api";
import { client } from "@/api";

const STATUSES = [
  { id: "backlog",      label: "Backlog",      tint: "#64748b", bg: "#f1f5f9" },
  { id: "em_andamento", label: "Em Andamento", tint: "#0369a1", bg: "#e0f2fe" },
  { id: "em_revisao",   label: "Em Revisão",   tint: "#b45309", bg: "#fef3c7" },
  { id: "finalizado",   label: "Finalizado",   tint: "#15803d", bg: "#dcfce7" },
];
const PRIORITIES = {
  baixa:   { label: "Baixa",   bg: "#e2e8f0", color: "#475569" },
  media:   { label: "Média",   bg: "#dbeafe", color: "#1e40af" },
  alta:    { label: "Alta",    bg: "#fed7aa", color: "#9a3412" },
  critica: { label: "Crítica", bg: "#fecaca", color: "#991b1b" },
};


export default function ProjectsPanel({ currentUser }) {
  const [view, setView] = useState("kanban");
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [filterPriority, setFilterPriority] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [selected, setSelected] = useState(null);
  const canManage = ["gestor", "administrador"]
    .includes((currentUser?.role || "").toLowerCase())
    || !!currentUser?.is_super_admin;

  const reload = async () => {
    setLoading(true); setErr("");
    try {
      const [r1, r2] = await Promise.all([
        client.get("/projects").then((r) => r.data),
        client.get("/projects/stats").then((r) => r.data),
      ]);
      setItems(r1.items || []);
      setStats(r2);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha");
    } finally { setLoading(false); }
  };
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, []);

  const filtered = useMemo(() => {
    if (!filterPriority) return items;
    return items.filter((it) => it.priority === filterPriority);
  }, [items, filterPriority]);

  const onCardMove = async (project_id, newStatus) => {
    // Optimistic UI: muda local antes de bater no backend
    setItems((arr) => arr.map((p) =>
      p.id === project_id ? { ...p, status: newStatus } : p));
    try {
      await client.patch(`/projects/${project_id}`, { status: newStatus });
      // Atualiza stats
      const s = await client.get("/projects/stats").then((r) => r.data);
      setStats(s);
    } catch (e) {
      console.error("[projects] move fail", e);
      reload();
    }
  };

  return (
    <div data-testid="projects-panel" style={{ padding: 0 }}>
      <header style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", marginBottom: 14,
                          flexWrap: "wrap", gap: 10 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800,
                          letterSpacing: "-0.02em", color: "#0f172a" }}>
            Acompanhamento · Projetos
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748b" }}>
            Kanban estilo Trello/Linear para execução em campo. Acompanhe
            do <strong>início</strong> à <strong>finalização</strong> com
            laudos PDF/DOC anexáveis.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {canManage && (
            <button data-testid="project-new-btn"
                      onClick={() => setShowNew(true)}
                      style={btnPrimary}>
              + Novo Projeto
            </button>
          )}
          <button data-testid="project-reload"
                    onClick={reload} disabled={loading}
                    style={btnSec}>
            {loading ? "..." : "⟳"}
          </button>
        </div>
      </header>

      {/* KPIs */}
      {stats && (
        <div data-testid="project-kpis"
              style={{ display: "grid",
                         gridTemplateColumns: "repeat(4, 1fr)",
                         gap: 10, marginBottom: 14 }}>
          <KPI label="Total" value={stats.total} color="#0f172a" />
          <KPI label="Em andamento"
                  value={stats.by_status.em_andamento} color="#0369a1" />
          <KPI label="Em revisão"
                  value={stats.by_status.em_revisao} color="#b45309" />
          <KPI label="Concluído"
                  value={`${stats.completed_pct}%`} color="#15803d" />
        </div>
      )}

      {/* Toolbar */}
      <div style={{ display: "flex", gap: 8, alignItems: "center",
                      flexWrap: "wrap", marginBottom: 14 }}>
        <div style={{ display: "flex", gap: 2, padding: 4,
                        background: "#f1f5f9", borderRadius: 10 }}>
          {["kanban", "lista"].map((v) => (
            <button key={v}
                      data-testid={`view-${v}`}
                      onClick={() => setView(v)}
                      style={{
                        padding: "6px 14px", borderRadius: 8, border: 0,
                        background: view === v ? "white" : "transparent",
                        color: view === v ? "#0f172a" : "#475569",
                        fontWeight: 700, fontSize: 12, cursor: "pointer",
                        boxShadow: view === v
                          ? "0 1px 3px rgba(0,0,0,.08)" : "none",
                        textTransform: "capitalize",
                      }}>
              {v}
            </button>
          ))}
        </div>
        <select data-testid="filter-priority"
                  value={filterPriority}
                  onChange={(e) => setFilterPriority(e.target.value)}
                  style={selStyle}>
          <option value="">Todas as prioridades</option>
          {Object.entries(PRIORITIES).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>
        <div style={{ marginLeft: "auto", fontSize: 11, color: "#94a3b8" }}>
          Arraste cards entre colunas para mover · clique para abrir
        </div>
      </div>

      {err && <div style={{ color: "#dc2626", marginBottom: 10 }}>Erro: {err}</div>}

      {view === "kanban"
        ? <KanbanView items={filtered} onMove={onCardMove}
                          onOpen={setSelected} canManage={canManage} />
        : <ListView items={filtered} onOpen={setSelected} />}

      {showNew && (
        <ProjectFormModal
          onClose={() => setShowNew(false)}
          onSave={async (payload) => {
            await client.post("/projects", payload);
            setShowNew(false);
            await reload();
          }} />
      )}
      {selected && (
        <ProjectDetailModal
          projectId={selected.id}
          canManage={canManage}
          onClose={() => setSelected(null)}
          onChanged={reload} />
      )}
    </div>
  );
}


// ============================================================
// Kanban view
// ============================================================
function KanbanView({ items, onMove, onOpen, canManage }) {
  const [dragOver, setDragOver] = useState(null);
  const byStatus = useMemo(() => {
    const m = {};
    STATUSES.forEach((s) => { m[s.id] = []; });
    (items || []).forEach((p) => {
      const s = p.status || "backlog";
      (m[s] = m[s] || []).push(p);
    });
    return m;
  }, [items]);

  return (
    <div data-testid="kanban-board"
          style={{ display: "grid",
                     gridTemplateColumns: "repeat(4, minmax(220px, 1fr))",
                     gap: 10, overflowX: "auto" }}>
      {STATUSES.map((col) => (
        <div key={col.id}
              data-testid={`kanban-col-${col.id}`}
              onDragOver={(e) => {
                if (!canManage) return;
                e.preventDefault();
                setDragOver(col.id);
              }}
              onDragLeave={() => setDragOver(null)}
              onDrop={(e) => {
                if (!canManage) return;
                e.preventDefault();
                const pid = e.dataTransfer.getData("text/plain");
                if (pid) onMove(pid, col.id);
                setDragOver(null);
              }}
              style={{
                background: col.bg, borderRadius: 12, padding: 10,
                minHeight: 320,
                outline: dragOver === col.id ? `2px dashed ${col.tint}` : "none",
              }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", marginBottom: 8 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ width: 8, height: 8, borderRadius: 4,
                                background: col.tint }} />
              <strong style={{ fontSize: 12.5, color: col.tint,
                                  textTransform: "uppercase",
                                  letterSpacing: "0.05em" }}>
                {col.label}
              </strong>
            </div>
            <span style={{ fontSize: 11, color: col.tint, fontWeight: 700,
                              background: "white", padding: "1px 8px",
                              borderRadius: 999 }}>
              {byStatus[col.id].length}
            </span>
          </div>
          {byStatus[col.id].map((p) => (
            <ProjectCard key={p.id} p={p}
                            draggable={canManage}
                            onOpen={() => onOpen(p)} />
          ))}
          {byStatus[col.id].length === 0 && (
            <div style={{ padding: 20, textAlign: "center",
                            color: "#94a3b8", fontSize: 12 }}>
              {col.id === "backlog" ? "Sem itens. Crie um projeto." : "—"}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}


function ProjectCard({ p, draggable, onOpen }) {
  const prio = PRIORITIES[p.priority] || PRIORITIES.media;
  const overdue = p.end_date && p.end_date < new Date().toISOString().slice(0, 10)
                    && p.status !== "finalizado";
  return (
    <div data-testid={`project-card-${p.id}`}
          onClick={onOpen}
          draggable={draggable}
          onDragStart={(e) => e.dataTransfer.setData("text/plain", p.id)}
          style={{
            background: "white", borderRadius: 10, padding: 10,
            marginBottom: 8,
            border: overdue ? "2px solid #fca5a5" : "1px solid #e2e8f0",
            cursor: "pointer",
            boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
          }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      gap: 6, marginBottom: 6 }}>
        <strong style={{ fontSize: 12.5, color: "#0f172a", lineHeight: 1.3,
                            flex: 1 }}>
          {p.title}
        </strong>
        <span style={{
          background: prio.bg, color: prio.color,
          fontSize: 9.5, fontWeight: 800,
          padding: "2px 7px", borderRadius: 999,
          textTransform: "uppercase", flexShrink: 0,
        }}>{prio.label}</span>
      </div>
      {p.description && (
        <div style={{ fontSize: 11, color: "#64748b",
                        marginBottom: 6, lineHeight: 1.4,
                        display: "-webkit-box",
                        WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                        overflow: "hidden" }}>
          {p.description}
        </div>
      )}
      {(p.tags || []).length > 0 && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap",
                        marginBottom: 6 }}>
          {p.tags.slice(0, 3).map((t) => (
            <span key={t} style={{
              background: "#f1f5f9", color: "#475569",
              fontSize: 9.5, padding: "1px 6px",
              borderRadius: 4, fontWeight: 600,
            }}>#{t}</span>
          ))}
        </div>
      )}
      {/* Progresso do checklist (apenas se houver subtarefas) */}
      {p.checklist_progress && p.checklist_progress.total > 0 && (
        <div data-testid={`progress-${p.id}`}
              style={{ marginBottom: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                          fontSize: 9.5, color: "#475569",
                          marginBottom: 2, fontWeight: 700 }}>
            <span>✓ {p.checklist_progress.done}/{p.checklist_progress.total}</span>
            <span>{p.checklist_progress.pct}%</span>
          </div>
          <div style={{ height: 4, background: "#e2e8f0",
                          borderRadius: 4, overflow: "hidden" }}>
            <div style={{
              width: `${p.checklist_progress.pct}%`,
              height: "100%",
              background: p.checklist_progress.pct === 100
                ? "#15803d" : "#0ea5e9",
              transition: "width 0.3s",
            }} />
          </div>
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", fontSize: 10,
                      color: overdue ? "#b91c1c" : "#94a3b8",
                      fontWeight: overdue ? 700 : 500 }}>
        <span>
          {p.start_date ? `📅 ${p.start_date.slice(5)}` : ""}
          {p.start_date && p.end_date ? " → " : ""}
          {p.end_date ? p.end_date.slice(5) : ""}
        </span>
        <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {p.files_count > 0 && <span>📎 {p.files_count}</span>}
          {(p.assignees || []).length > 0 &&
            <span>👤 {p.assignees.length}</span>}
        </span>
      </div>
    </div>
  );
}


// ============================================================
// List view
// ============================================================
function ListView({ items, onOpen }) {
  return (
    <table data-testid="projects-list"
            style={{ width: "100%", borderCollapse: "collapse",
                        background: "white", borderRadius: 10,
                        overflow: "hidden",
                        border: "1px solid #e2e8f0", fontSize: 12.5 }}>
      <thead>
        <tr style={{ background: "#f8fafc",
                        borderBottom: "1px solid #e2e8f0" }}>
          <th style={th}>Título</th>
          <th style={th}>Status</th>
          <th style={th}>Prioridade</th>
          <th style={th}>Início</th>
          <th style={th}>Término</th>
          <th style={th}>📎</th>
        </tr>
      </thead>
      <tbody>
        {items.map((p) => {
          const st = STATUSES.find((s) => s.id === p.status) || STATUSES[0];
          const prio = PRIORITIES[p.priority] || PRIORITIES.media;
          return (
            <tr key={p.id}
                data-testid={`project-row-${p.id}`}
                onClick={() => onOpen(p)}
                style={{ borderBottom: "1px solid #f1f5f9", cursor: "pointer" }}>
              <td style={td}>
                <strong>{p.title}</strong>
                {p.description && (
                  <div style={{ fontSize: 11, color: "#94a3b8",
                                  marginTop: 2 }}>{p.description.slice(0, 80)}</div>
                )}
              </td>
              <td style={td}>
                <span style={{
                  background: st.bg, color: st.tint, fontWeight: 700,
                  padding: "2px 8px", borderRadius: 6, fontSize: 11,
                }}>{st.label}</span>
              </td>
              <td style={td}>
                <span style={{
                  background: prio.bg, color: prio.color, fontWeight: 700,
                  padding: "2px 8px", borderRadius: 6, fontSize: 11,
                }}>{prio.label}</span>
              </td>
              <td style={td}>{p.start_date || "—"}</td>
              <td style={td}>{p.end_date || "—"}</td>
              <td style={td}>{p.files_count || 0}</td>
            </tr>
          );
        })}
        {items.length === 0 && (
          <tr><td style={{ ...td, textAlign: "center", color: "#94a3b8" }}
                  colSpan={6}>Nenhum projeto.</td></tr>
        )}
      </tbody>
    </table>
  );
}


// ============================================================
// Form modal (create)
// ============================================================
function ProjectFormModal({ onClose, onSave }) {
  const [f, setF] = useState({
    title: "", description: "", priority: "media", status: "backlog",
    tags: "", start_date: "", end_date: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const submit = async (e) => {
    e?.preventDefault?.();
    setErr(""); setBusy(true);
    try {
      await onSave({
        title: f.title, description: f.description,
        status: f.status, priority: f.priority,
        tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean),
        start_date: f.start_date || null,
        end_date: f.end_date || null,
      });
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };
  return (
    <Modal data-testid="project-form-modal" onClose={onClose}>
      <h3 style={modalTitle}>+ Novo Projeto</h3>
      <form onSubmit={submit}>
        <label style={lbl}>Título *</label>
        <input data-testid="project-title-input"
                value={f.title}
                onChange={(e) => setF({ ...f, title: e.target.value })}
                placeholder="Ex: Lançamento backbone Centro"
                style={inputStyle} required />
        <label style={lbl}>Descrição</label>
        <textarea data-testid="project-desc-input"
                    value={f.description}
                    onChange={(e) => setF({ ...f, description: e.target.value })}
                    placeholder="Detalhes da execução..."
                    rows={3} style={{ ...inputStyle, resize: "vertical" }} />
        <div style={{ display: "grid",
                        gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <div>
            <label style={lbl}>Início</label>
            <input data-testid="project-start-input"
                    type="date" value={f.start_date}
                    onChange={(e) => setF({ ...f, start_date: e.target.value })}
                    style={inputStyle} />
          </div>
          <div>
            <label style={lbl}>Término</label>
            <input data-testid="project-end-input"
                    type="date" value={f.end_date}
                    onChange={(e) => setF({ ...f, end_date: e.target.value })}
                    style={inputStyle} />
          </div>
        </div>
        <div style={{ display: "grid",
                        gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <div>
            <label style={lbl}>Prioridade</label>
            <select data-testid="project-priority"
                      value={f.priority}
                      onChange={(e) => setF({ ...f, priority: e.target.value })}
                      style={inputStyle}>
              {Object.entries(PRIORITIES).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={lbl}>Coluna inicial</label>
            <select data-testid="project-status"
                      value={f.status}
                      onChange={(e) => setF({ ...f, status: e.target.value })}
                      style={inputStyle}>
              {STATUSES.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
          </div>
        </div>
        <label style={lbl}>Tags (separadas por vírgula)</label>
        <input data-testid="project-tags-input"
                value={f.tags}
                onChange={(e) => setF({ ...f, tags: e.target.value })}
                placeholder="backbone, centro, urgente"
                style={inputStyle} />
        {err && <div style={{ color: "#dc2626", fontSize: 12,
                                marginTop: 8 }}>{err}</div>}
        <div style={{ display: "flex", gap: 8, marginTop: 14,
                        justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose}
                    style={btnSec}>Cancelar</button>
          <button type="submit"
                    data-testid="project-save-btn"
                    disabled={busy || !f.title.trim()}
                    style={{ ...btnPrimary,
                                opacity: busy || !f.title.trim() ? 0.5 : 1 }}>
            {busy ? "Salvando…" : "Criar"}
          </button>
        </div>
      </form>
    </Modal>
  );
}


// ============================================================
// Detail modal (with file upload)
// ============================================================
function ProjectDetailModal({ projectId, canManage, onClose, onChanged }) {
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(false);
  const [f, setF] = useState({});
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState("");
  const fileInput = useRef(null);

  const reload = async () => {
    try {
      const d = await client.get(`/projects/${projectId}`).then((r) => r.data);
      setData(d);
      setF({
        title: d.title || "", description: d.description || "",
        status: d.status, priority: d.priority,
        tags: (d.tags || []).join(", "),
        start_date: d.start_date || "", end_date: d.end_date || "",
      });
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  };
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [projectId]);

  const save = async () => {
    setErr(""); setBusy(true);
    try {
      await client.patch(`/projects/${projectId}`, {
        title: f.title, description: f.description,
        status: f.status, priority: f.priority,
        tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean),
        start_date: f.start_date || null,
        end_date: f.end_date || null,
      });
      setEditing(false);
      await reload();
      onChanged?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!window.confirm("Excluir este projeto e todos os arquivos?")) return;
    try {
      await client.delete(`/projects/${projectId}`);
      onClose();
      onChanged?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  };

  const uploadFile = async (file) => {
    setErr(""); setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      await client.post(`/projects/${projectId}/files`, form);
      await reload();
      onChanged?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const downloadFile = async (file) => {
    try {
      const r = await client.get(
        `/projects/${projectId}/files/${file.id}/download`,
        { responseType: "blob" },
      );
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = file.filename;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  };

  const removeFile = async (fileId) => {
    if (!window.confirm("Remover este arquivo?")) return;
    try {
      await client.delete(`/projects/${projectId}/files/${fileId}`);
      await reload();
      onChanged?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  };

  if (!data) {
    return <Modal onClose={onClose}><p>Carregando…</p></Modal>;
  }

  const st = STATUSES.find((s) => s.id === data.status) || STATUSES[0];
  const prio = PRIORITIES[data.priority] || PRIORITIES.media;

  return (
    <Modal data-testid="project-detail-modal"
            onClose={onClose} wide>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "flex-start", gap: 8, marginBottom: 10 }}>
        <div style={{ flex: 1 }}>
          {!editing ? (
            <>
              <h3 style={{ ...modalTitle, marginBottom: 4 }}>{data.title}</h3>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <span style={{
                  background: st.bg, color: st.tint, fontWeight: 700,
                  padding: "3px 10px", borderRadius: 6, fontSize: 11,
                }}>{st.label}</span>
                <span style={{
                  background: prio.bg, color: prio.color, fontWeight: 700,
                  padding: "3px 10px", borderRadius: 6, fontSize: 11,
                }}>{prio.label}</span>
                {(data.tags || []).map((t) => (
                  <span key={t} style={{
                    background: "#f1f5f9", color: "#475569",
                    fontSize: 10, padding: "2px 7px",
                    borderRadius: 4, fontWeight: 600,
                  }}>#{t}</span>
                ))}
              </div>
            </>
          ) : (
            <input value={f.title}
                    onChange={(e) => setF({ ...f, title: e.target.value })}
                    style={{ ...inputStyle, fontSize: 16, fontWeight: 700 }} />
          )}
        </div>
        {canManage && !editing && (
          <button data-testid="project-edit-btn"
                    onClick={() => setEditing(true)}
                    style={btnSec}>✏️ Editar</button>
        )}
      </div>

      {!editing && data.description && (
        <p style={{ color: "#475569", fontSize: 13, lineHeight: 1.5,
                      whiteSpace: "pre-wrap" }}>
          {data.description}
        </p>
      )}
      {editing && (
        <>
          <label style={lbl}>Descrição</label>
          <textarea value={f.description}
                      onChange={(e) => setF({ ...f, description: e.target.value })}
                      rows={3} style={{ ...inputStyle, resize: "vertical" }} />
          <div style={{ display: "grid",
                          gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8 }}>
            <div>
              <label style={lbl}>Início</label>
              <input type="date" value={f.start_date}
                      onChange={(e) => setF({ ...f, start_date: e.target.value })}
                      style={inputStyle} />
            </div>
            <div>
              <label style={lbl}>Término</label>
              <input type="date" value={f.end_date}
                      onChange={(e) => setF({ ...f, end_date: e.target.value })}
                      style={inputStyle} />
            </div>
            <div>
              <label style={lbl}>Status</label>
              <select value={f.status}
                        onChange={(e) => setF({ ...f, status: e.target.value })}
                        style={inputStyle}>
                {STATUSES.map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={lbl}>Prioridade</label>
              <select value={f.priority}
                        onChange={(e) => setF({ ...f, priority: e.target.value })}
                        style={inputStyle}>
                {Object.entries(PRIORITIES).map(([k, v]) => (
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </select>
            </div>
          </div>
          <label style={lbl}>Tags</label>
          <input value={f.tags}
                  onChange={(e) => setF({ ...f, tags: e.target.value })}
                  style={inputStyle} />
        </>
      )}

      {!editing && (
        <div style={{ display: "grid",
                        gridTemplateColumns: "1fr 1fr", gap: 8,
                        background: "#f8fafc", padding: 10,
                        borderRadius: 8, marginTop: 10 }}>
          <Info label="Início" value={data.start_date || "—"} />
          <Info label="Término" value={data.end_date || "—"} />
          <Info label="Criado por" value={data.created_by_name || "—"} />
          <Info label="Criado em"
                  value={(data.created_at || "").slice(0, 16).replace("T", " ")} />
        </div>
      )}

      {/* Checklist (subtarefas) */}
      <ChecklistSection
        projectId={projectId}
        items={data.checklist || []}
        progress={data.checklist_progress}
        canManage={canManage}
        onChanged={reload} />

      {/* Files */}
      <div style={{ marginTop: 16, padding: 12,
                      background: "#fef9c3", borderRadius: 10,
                      border: "1px solid #fde68a" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", marginBottom: 8 }}>
          <strong style={{ fontSize: 13, color: "#92400e" }}>
            📎 Laudo Fotográfico / Documentos
          </strong>
          {canManage && (
            <>
              <input ref={fileInput} type="file"
                      accept=".pdf,.doc,.docx,image/*"
                      data-testid="project-file-input"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) uploadFile(file);
                      }}
                      style={{ display: "none" }} />
              <button data-testid="project-upload-btn"
                        onClick={() => fileInput.current?.click()}
                        disabled={uploading}
                        style={btnPrimary}>
                {uploading ? "Enviando…" : "+ Anexar PDF/DOC/Imagem"}
              </button>
            </>
          )}
        </div>
        {(data.files || []).length === 0 ? (
          <div style={{ color: "#a16207", fontSize: 12 }}>
            Nenhum arquivo anexado. Use o botão acima para subir laudos
            fotográficos em PDF, DOC ou imagem.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {data.files.map((f0) => (
              <div key={f0.id}
                    data-testid={`file-row-${f0.id}`}
                    style={{
                      display: "flex", gap: 8, alignItems: "center",
                      background: "white", padding: "6px 10px",
                      borderRadius: 6, border: "1px solid #fde68a",
                      fontSize: 12.5,
                    }}>
                <span>{fileIcon(f0.mime)}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, color: "#0f172a",
                                  whiteSpace: "nowrap",
                                  overflow: "hidden",
                                  textOverflow: "ellipsis" }}>
                    {f0.filename}
                  </div>
                  <div style={{ color: "#94a3b8", fontSize: 10 }}>
                    {(f0.size / 1024).toFixed(1)} KB ·{" "}
                    {f0.uploaded_by_name || "—"} ·{" "}
                    {(f0.uploaded_at || "").slice(0, 16).replace("T", " ")}
                  </div>
                </div>
                <button data-testid={`file-download-${f0.id}`}
                          onClick={() => downloadFile(f0)}
                          style={btnSec}>⬇</button>
                {canManage && (
                  <button data-testid={`file-delete-${f0.id}`}
                            onClick={() => removeFile(f0.id)}
                            style={{ ...btnSec, color: "#dc2626" }}>×</button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {err && <div style={{ color: "#dc2626", fontSize: 12,
                              marginTop: 8 }}>{err}</div>}

      <div style={{ display: "flex", gap: 8, marginTop: 14,
                      justifyContent: "space-between" }}>
        {canManage && !editing && (
          <button data-testid="project-delete-btn"
                    onClick={remove}
                    style={{ ...btnSec, color: "#dc2626" }}>
            🗑 Excluir
          </button>
        )}
        <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
          {editing && (
            <>
              <button onClick={() => { setEditing(false); reload(); }}
                        style={btnSec}>Cancelar</button>
              <button data-testid="project-save-edit-btn"
                        onClick={save} disabled={busy}
                        style={btnPrimary}>
                {busy ? "Salvando…" : "Salvar"}
              </button>
            </>
          )}
          {!editing && (
            <button onClick={onClose} style={btnSec}>Fechar</button>
          )}
        </div>
      </div>
    </Modal>
  );
}


function ChecklistSection({ projectId, items, progress, canManage, onChanged }) {
  const [newText, setNewText] = useState("");
  const [busy, setBusy] = useState(false);

  const addItem = async (e) => {
    e?.preventDefault?.();
    const text = (newText || "").trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      await client.post(`/projects/${projectId}/checklist`, { text });
      setNewText("");
      onChanged?.();
    } finally { setBusy(false); }
  };
  const toggle = async (item) => {
    try {
      await client.patch(
        `/projects/${projectId}/checklist/${item.id}`,
        { done: !item.done });
      onChanged?.();
    } catch (e) { console.error(e); }
  };
  const remove = async (item) => {
    if (!window.confirm("Remover este item?")) return;
    try {
      await client.delete(`/projects/${projectId}/checklist/${item.id}`);
      onChanged?.();
    } catch (e) { console.error(e); }
  };

  const done = progress?.done || 0;
  const total = progress?.total || items.length;
  const pct = progress?.pct || 0;

  return (
    <div data-testid="project-checklist"
          style={{ marginTop: 16, padding: 12,
                     background: "#eff6ff", borderRadius: 10,
                     border: "1px solid #bfdbfe" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 8 }}>
        <strong style={{ fontSize: 13, color: "#1e40af" }}>
          ✓ Checklist · {done}/{total} ({pct}%)
        </strong>
      </div>
      {/* Barra de progresso */}
      {total > 0 && (
        <div style={{ height: 6, background: "#dbeafe",
                        borderRadius: 4, overflow: "hidden",
                        marginBottom: 10 }}>
          <div data-testid="checklist-progress-bar"
                style={{
                  width: `${pct}%`, height: "100%",
                  background: pct === 100 ? "#15803d" : "#0ea5e9",
                  transition: "width 0.3s",
                }} />
        </div>
      )}
      {/* Itens */}
      {items.length === 0 && (
        <div style={{ color: "#1d4ed8", fontSize: 12,
                        marginBottom: canManage ? 10 : 0 }}>
          Nenhuma subtarefa. Adicione passos como
          "Autorização → Splice → Certificação → Ativação".
        </div>
      )}
      {items.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column",
                        gap: 4, marginBottom: canManage ? 10 : 0 }}>
          {items.map((it) => (
            <div key={it.id}
                  data-testid={`checklist-item-${it.id}`}
                  style={{ display: "flex", gap: 8, alignItems: "center",
                              background: "white", padding: "6px 10px",
                              borderRadius: 6, border: "1px solid #bfdbfe",
                              fontSize: 12.5,
                              opacity: it.done ? 0.65 : 1 }}>
              <input type="checkbox"
                      checked={!!it.done}
                      onChange={() => toggle(it)}
                      data-testid={`checklist-toggle-${it.id}`}
                      disabled={!canManage}
                      style={{ width: 16, height: 16,
                                  cursor: canManage ? "pointer" : "default" }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontWeight: 600,
                  color: it.done ? "#94a3b8" : "#0f172a",
                  textDecoration: it.done ? "line-through" : "none",
                  wordBreak: "break-word",
                }}>{it.text}</div>
                {it.done && it.done_by_name && (
                  <div style={{ fontSize: 10, color: "#94a3b8" }}>
                    Concluído por {it.done_by_name}{" "}
                    em {(it.done_at || "").slice(0, 16).replace("T", " ")}
                  </div>
                )}
              </div>
              {canManage && (
                <button data-testid={`checklist-delete-${it.id}`}
                          onClick={() => remove(it)}
                          style={{
                            background: "transparent", border: 0,
                            color: "#dc2626", cursor: "pointer",
                            fontSize: 16, padding: "0 4px",
                          }}
                          title="Remover">×</button>
              )}
            </div>
          ))}
        </div>
      )}
      {canManage && (
        <form onSubmit={addItem}
              style={{ display: "flex", gap: 6 }}>
          <input data-testid="checklist-new-input"
                  value={newText}
                  onChange={(e) => setNewText(e.target.value)}
                  placeholder="Adicionar subtarefa (Enter)…"
                  disabled={busy}
                  style={{
                    flex: 1, padding: "6px 10px", borderRadius: 6,
                    border: "1px solid #bfdbfe", fontSize: 12,
                    background: "white",
                  }} />
          <button type="submit"
                    data-testid="checklist-add-btn"
                    disabled={busy || !newText.trim()}
                    style={{
                      padding: "6px 12px", borderRadius: 6, border: 0,
                      background: busy || !newText.trim()
                        ? "#cbd5e1" : "#0ea5e9",
                      color: "white", fontSize: 12, fontWeight: 700,
                      cursor: busy || !newText.trim() ? "default" : "pointer",
                    }}>
            +
          </button>
        </form>
      )}
    </div>
  );
}


function fileIcon(mime) {
  if ((mime || "").startsWith("image/")) return "🖼";
  if ((mime || "").includes("pdf")) return "📄";
  if ((mime || "").includes("word") || (mime || "").includes("officedocument"))
    return "📝";
  return "📎";
}


// ============================================================
// Reusable bits
// ============================================================
function Modal({ children, onClose, wide }) {
  return (
    <div onClick={onClose}
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            background: "rgba(15,23,42,0.7)",
            display: "flex", alignItems: "center",
            justifyContent: "center", padding: 20,
            overflowY: "auto",
          }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{
              background: "white", borderRadius: 12, padding: 22,
              width: wide ? "min(96vw, 720px)" : "min(94vw, 480px)",
              maxHeight: "92vh", overflowY: "auto",
              boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
            }}>
        {children}
      </div>
    </div>
  );
}
function KPI({ label, value, color }) {
  return (
    <div data-testid={`kpi-${label}`}
          style={{
            background: "white", border: "1px solid #e2e8f0",
            borderRadius: 10, padding: 12, textAlign: "center",
          }}>
      <div style={{ fontSize: 20, fontWeight: 800,
                       color: color || "#0f172a" }}>{value}</div>
      <div style={{ fontSize: 11, color: "#64748b", marginTop: 2,
                       fontWeight: 600, textTransform: "uppercase",
                       letterSpacing: "0.05em" }}>{label}</div>
    </div>
  );
}
function Info({ label, value }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "#94a3b8",
                       textTransform: "uppercase", fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 13, color: "#0f172a", fontWeight: 600,
                       marginTop: 2 }}>{value}</div>
    </div>
  );
}

const modalTitle = { margin: 0, marginBottom: 10, fontSize: 18,
                          fontWeight: 800, color: "#0f172a" };
const lbl = { display: "block", fontSize: 12, fontWeight: 700,
                color: "#334155", marginTop: 8, marginBottom: 4 };
const inputStyle = {
  width: "100%", padding: "8px 10px", borderRadius: 8,
  border: "1px solid #cbd5e1", fontSize: 13,
  boxSizing: "border-box",
};
const selStyle = {
  padding: "6px 10px", borderRadius: 8,
  border: "1px solid #cbd5e1", fontSize: 12,
  background: "white",
};
const btnPrimary = {
  padding: "8px 14px", borderRadius: 8, border: 0,
  background: "linear-gradient(135deg,#0ea5e9,#0369a1)",
  color: "white", fontSize: 12.5, fontWeight: 800, cursor: "pointer",
};
const btnSec = {
  padding: "8px 12px", borderRadius: 8,
  border: "1px solid #cbd5e1", background: "white",
  fontSize: 12, fontWeight: 700, cursor: "pointer", color: "#334155",
};
const th = { textAlign: "left", padding: "10px 12px",
                fontSize: 11, fontWeight: 700,
                color: "#475569", textTransform: "uppercase" };
const td = { padding: "10px 12px", color: "#1e293b" };
