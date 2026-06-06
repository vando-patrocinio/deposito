/* NeoReportsPanel.js — Agendamento de relatórios em PDF via NEO.
 *
 * Funcionalidades:
 *  - Listar / criar / editar / remover schedules
 *  - Disparar manualmente um schedule (Executar Agora)
 *  - Histórico das últimas execuções
 *
 * UX:
 *  - Card list à esquerda, modal de criação/edição na direita.
 *  - Frequência: diária (HH:MM), semanal (DoW + HH:MM), mensal (DoM + HH:MM)
 *  - Opcional: whatsapp_phone para entrega via Baileys.
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  Calendar, Clock, FileText, Play, Plus, RefreshCw,
  Trash2, Edit3, Phone, History, CheckCircle2, XCircle, AlertCircle,
  Sparkles, Sun,
} from "lucide-react";
import { api } from "@/api";

const DOW_LABELS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const FREQ_LABELS = { daily: "Diário", weekly: "Semanal", monthly: "Mensal" };

const card = {
  padding: 16, borderRadius: 12, border: "1px solid var(--border-default)",
  background: "var(--bg-surface)",
};
const input = {
  width: "100%", padding: "8px 10px", borderRadius: 8,
  border: "1px solid var(--border-default)", background: "var(--bg-surface)",
  color: "var(--text-primary)", fontSize: 13,
};
const btnPrimary = {
  padding: "8px 14px", borderRadius: 8, border: 0,
  background: "linear-gradient(135deg, #0d9488, #06b6d4)",
  color: "#fff", fontWeight: 700, fontSize: 13, cursor: "pointer",
};
const btnGhost = {
  padding: "6px 10px", borderRadius: 8,
  border: "1px solid var(--border-default)",
  background: "transparent", color: "var(--text-primary)",
  fontSize: 12, cursor: "pointer",
};

function formatNext(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
}

function StatusBadge({ status }) {
  const map = {
    success: { bg: "#dcfce7", fg: "#15803d", icon: CheckCircle2, label: "Sucesso" },
    error: { bg: "#fee2e2", fg: "#991b1b", icon: XCircle, label: "Erro" },
    delivery_failed: { bg: "#fef3c7", fg: "#92400e", icon: AlertCircle, label: "Entrega falhou" },
    running: { bg: "#dbeafe", fg: "#1e40af", icon: RefreshCw, label: "Executando" },
  };
  const cfg = map[status] || { bg: "#e2e8f0", fg: "#334155", icon: AlertCircle, label: status };
  const Icon = cfg.icon;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      background: cfg.bg, color: cfg.fg, padding: "2px 8px",
      borderRadius: 999, fontSize: 11, fontWeight: 700,
    }}>
      <Icon size={11} /> {cfg.label}
    </span>
  );
}

function ScheduleForm({ initial, onSave, onCancel, reportTypes }) {
  const [data, setData] = useState(() => ({
    name: "",
    report_type: reportTypes[0]?.key || "ctos_occupancy",
    frequency: "daily",
    hour: 8,
    minute: 0,
    day_of_week: 0,
    day_of_month: 1,
    whatsapp_phone: "",
    active: true,
    ...(initial || {}),
  }));
  const update = (k, v) => setData((p) => ({ ...p, [k]: v }));
  const submit = (e) => {
    e?.preventDefault();
    if (!data.name?.trim()) return alert("Informe um nome para o agendamento");
    const payload = { ...data };
    if (payload.frequency !== "weekly") delete payload.day_of_week;
    if (payload.frequency !== "monthly") delete payload.day_of_month;
    if (!payload.whatsapp_phone?.trim()) payload.whatsapp_phone = null;
    onSave(payload);
  };
  return (
    <form onSubmit={submit} data-testid="neo-schedule-form" style={{
      ...card, display: "grid", gap: 10,
    }}>
      <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 4 }}>
        {initial?.id ? "Editar Agendamento" : "Novo Agendamento"}
      </div>
      <div>
        <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>Nome</label>
        <input data-testid="neo-form-name" style={input} value={data.name}
                  onChange={(e) => update("name", e.target.value)}
                  placeholder="Ex: Ocupação CTOs Diária" />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>Relatório</label>
          <select data-testid="neo-form-type" style={input} value={data.report_type}
                     onChange={(e) => update("report_type", e.target.value)}>
            {reportTypes.map((t) => (
              <option key={t.key} value={t.key}>{t.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>Frequência</label>
          <select data-testid="neo-form-frequency" style={input} value={data.frequency}
                     onChange={(e) => update("frequency", e.target.value)}>
            <option value="daily">Diário</option>
            <option value="weekly">Semanal</option>
            <option value="monthly">Mensal</option>
          </select>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>Hora</label>
          <input data-testid="neo-form-hour" type="number" min={0} max={23} style={input}
                  value={data.hour}
                  onChange={(e) => update("hour", parseInt(e.target.value || 0, 10))} />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>Minuto</label>
          <input data-testid="neo-form-minute" type="number" min={0} max={59} style={input}
                  value={data.minute}
                  onChange={(e) => update("minute", parseInt(e.target.value || 0, 10))} />
        </div>
        {data.frequency === "weekly" && (
          <div>
            <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>Dia da semana</label>
            <select data-testid="neo-form-dow" style={input} value={data.day_of_week}
                       onChange={(e) => update("day_of_week", parseInt(e.target.value, 10))}>
              {DOW_LABELS.map((l, i) => <option key={i} value={i}>{l}</option>)}
            </select>
          </div>
        )}
        {data.frequency === "monthly" && (
          <div>
            <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>Dia do mês</label>
            <input data-testid="neo-form-dom" type="number" min={1} max={28} style={input}
                    value={data.day_of_month}
                    onChange={(e) => update("day_of_month", parseInt(e.target.value || 1, 10))} />
          </div>
        )}
      </div>
      <div>
        <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>
          <Phone size={11} style={{ display: "inline", marginRight: 4 }} />
          WhatsApp p/ envio (E.164 sem '+', opcional)
        </label>
        <input data-testid="neo-form-phone" style={input} value={data.whatsapp_phone || ""}
                onChange={(e) => update("whatsapp_phone", e.target.value)}
                placeholder="Ex: 5582999999999" />
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600 }}>
        <input data-testid="neo-form-active" type="checkbox" checked={!!data.active}
                onChange={(e) => update("active", e.target.checked)} />
        Ativo
      </label>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button type="button" onClick={onCancel} style={btnGhost} data-testid="neo-form-cancel">
          Cancelar
        </button>
        <button type="submit" style={btnPrimary} data-testid="neo-form-save">
          {initial?.id ? "Salvar" : "Criar Agendamento"}
        </button>
      </div>
    </form>
  );
}

export default function NeoReportsPanel() {
  const [schedules, setSchedules] = useState([]);
  const [history, setHistory] = useState([]);
  const [reportTypes, setReportTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // null | {} | schedule
  const [busyId, setBusyId] = useState(null);
  const [briefing, setBriefing] = useState({ active: false, count: 0, schedules: [] });
  const [showBriefingForm, setShowBriefingForm] = useState(false);
  const [briefingForm, setBriefingForm] = useState({ phones: "", hour: 7, minute: 0 });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, h, t, b] = await Promise.all([
        api.neoReportSchedules(),
        api.neoReportHistory(20),
        api.neoReportTypes(),
        api.neoBriefingStatus().catch(() => ({ active: false, count: 0, schedules: [] })),
      ]);
      setSchedules(s?.items || []);
      setHistory(h?.items || []);
      setReportTypes(t?.items || []);
      setBriefing(b || { active: false, count: 0, schedules: [] });
    } catch (e) {
      console.error("[neo-reports] load fail", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onSave = async (payload) => {
    try {
      if (editing?.id) {
        await api.neoReportScheduleUpdate(editing.id, payload);
      } else {
        await api.neoReportScheduleCreate(payload);
      }
      setEditing(null);
      load();
    } catch (e) {
      alert("Erro ao salvar: " + (e?.response?.data?.detail || e.message));
    }
  };

  const onDelete = async (sid) => {
    if (!window.confirm("Remover este agendamento?")) return;
    try {
      await api.neoReportScheduleDelete(sid);
      load();
    } catch (e) {
      alert("Erro ao remover: " + (e?.response?.data?.detail || e.message));
    }
  };

  const onRunNow = async (sid) => {
    setBusyId(sid);
    try {
      const r = await api.neoReportScheduleRun(sid);
      alert(`Status: ${r.status}\nArquivo: ${r.filename || "—"}`);
      load();
    } catch (e) {
      alert("Falha ao executar: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBusyId(null);
    }
  };

  const onActivateBriefing = async () => {
    const phones = briefingForm.phones
      .split(/[\s,;]+/)
      .map((p) => p.replace(/\D/g, ""))
      .filter(Boolean);
    if (phones.length === 0) {
      alert("Informe ao menos 1 telefone (E.164 sem '+', ex: 5582999998888)");
      return;
    }
    try {
      const r = await api.neoBriefingActivate({
        phones,
        hour: parseInt(briefingForm.hour, 10) || 7,
        minute: parseInt(briefingForm.minute, 10) || 0,
      });
      alert(`Briefing Diário NEO ativado para ${r.count} destinatário(s) às ${String(briefingForm.hour).padStart(2,"0")}:${String(briefingForm.minute).padStart(2,"0")}.`);
      setShowBriefingForm(false);
      load();
    } catch (e) {
      alert("Erro ao ativar briefing: " + (e?.response?.data?.detail || e.message));
    }
  };

  const onDeactivateBriefing = async () => {
    if (!window.confirm("Desativar o Briefing Diário NEO?")) return;
    try {
      await api.neoBriefingDeactivate();
      load();
    } catch (e) {
      alert("Erro ao desativar: " + (e?.response?.data?.detail || e.message));
    }
  };

  const typeLabel = (key) =>
    reportTypes.find((t) => t.key === key)?.label || key;

  return (
    <div data-testid="neo-reports-panel" style={{ display: "grid", gap: 16 }}>
      {/* Header */}
      <div style={{
        ...card,
        background: "linear-gradient(135deg, var(--accent-soft) 0%, var(--bg-surface) 60%)",
        display: "flex", alignItems: "center", gap: 14,
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: "linear-gradient(135deg, #0d9488, #06b6d4)",
          color: "#fff", display: "grid", placeItems: "center",
        }}>
          <FileText size={24} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 800, fontSize: 16 }}>NEO • Relatórios Agendados</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Programe relatórios para serem gerados e enviados automaticamente via WhatsApp.
          </div>
        </div>
        <button data-testid="neo-new-schedule" style={btnPrimary}
                onClick={() => setEditing({})}>
          <Plus size={14} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
          Novo Agendamento
        </button>
        <button data-testid="neo-refresh" style={btnGhost} onClick={load} title="Recarregar">
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Briefing Diário NEO — 1-click */}
      <div data-testid="neo-briefing-card" style={{
        ...card,
        background: briefing.active
          ? "linear-gradient(135deg, #ecfeff 0%, #cffafe 100%)"
          : "linear-gradient(135deg, #fef3c7 0%, #fde68a 60%)",
        border: `1px solid ${briefing.active ? "#06b6d4" : "#f59e0b"}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{
            width: 44, height: 44, borderRadius: 12,
            background: briefing.active
              ? "linear-gradient(135deg, #0d9488, #06b6d4)"
              : "linear-gradient(135deg, #f59e0b, #f97316)",
            color: "#fff", display: "grid", placeItems: "center", flexShrink: 0,
          }}>
            <Sun size={22} strokeWidth={2} />
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontWeight: 800, fontSize: 15, color: "#0f172a", display: "flex", alignItems: "center", gap: 6 }}>
              <Sparkles size={14} /> Briefing Diário NEO
              {briefing.active && (
                <span style={{
                  fontSize: 10, padding: "2px 10px", borderRadius: 999,
                  background: "#10b981", color: "#fff", fontWeight: 700,
                }}>ATIVO</span>
              )}
            </div>
            <div style={{ fontSize: 12, color: "#334155", marginTop: 4 }}>
              {briefing.active
                ? `Enviando para ${briefing.count} destinatário(s) todo dia. PDF com KPIs de Isabella, Álvaro, Camila, Secretaria + resumo IA executivo.`
                : "Ative com 1 clique: todo dia às 7h, o NEO gera 1 PDF executivo (KPIs dos 4 agentes + alertas + resumo IA) e envia no WhatsApp pra você."}
            </div>
            {briefing.active && briefing.schedules?.[0] && (
              <div style={{ fontSize: 11, color: "#0d9488", marginTop: 4, fontFamily: "monospace" }}>
                ⏰ Próximo: {new Date(briefing.schedules[0].next_run_at).toLocaleString("pt-BR")}
              </div>
            )}
          </div>
          {briefing.active ? (
            <button data-testid="neo-briefing-deactivate" style={{
              ...btnGhost, borderColor: "#ef4444", color: "#991b1b",
            }} onClick={onDeactivateBriefing}>
              Desativar
            </button>
          ) : (
            <button data-testid="neo-briefing-activate" style={{
              ...btnPrimary,
              background: "linear-gradient(135deg, #f59e0b, #f97316)",
            }} onClick={() => setShowBriefingForm((v) => !v)}>
              <Sparkles size={14} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
              Ativar Briefing Diário NEO
            </button>
          )}
        </div>
        {showBriefingForm && !briefing.active && (
          <div data-testid="neo-briefing-form" style={{
            marginTop: 14, padding: 14, borderRadius: 10,
            background: "rgba(255,255,255,.7)", border: "1px solid #fbbf24",
            display: "grid", gap: 10,
          }}>
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: "#475569" }}>
                Telefones (separados por vírgula ou espaço · E.164 sem '+')
              </label>
              <input
                data-testid="neo-briefing-phones"
                style={input}
                placeholder="5582999998888, 5511988887777"
                value={briefingForm.phones}
                onChange={(e) => setBriefingForm((p) => ({ ...p, phones: e.target.value }))}
              />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 8 }}>
              <div>
                <label style={{ fontSize: 11, fontWeight: 700, color: "#475569" }}>Hora</label>
                <input data-testid="neo-briefing-hour" type="number" min={0} max={23} style={input}
                        value={briefingForm.hour}
                        onChange={(e) => setBriefingForm((p) => ({ ...p, hour: e.target.value }))} />
              </div>
              <div>
                <label style={{ fontSize: 11, fontWeight: 700, color: "#475569" }}>Minuto</label>
                <input data-testid="neo-briefing-minute" type="number" min={0} max={59} style={input}
                        value={briefingForm.minute}
                        onChange={(e) => setBriefingForm((p) => ({ ...p, minute: e.target.value }))} />
              </div>
              <div style={{ display: "flex", alignItems: "flex-end" }}>
                <button data-testid="neo-briefing-confirm" style={btnPrimary} onClick={onActivateBriefing}>
                  Ativar
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Form modal */}
      {editing !== null && (
        <ScheduleForm
          initial={editing}
          reportTypes={reportTypes}
          onSave={onSave}
          onCancel={() => setEditing(null)}
        />
      )}

      {/* Lista de schedules */}
      <div style={{ ...card }}>
        <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <Calendar size={16} /> Agendamentos ({schedules.length})
        </div>
        {loading ? (
          <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)" }}>
            Carregando…
          </div>
        ) : schedules.length === 0 ? (
          <div data-testid="neo-empty-state" style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
            Nenhum agendamento ainda. Clique em “Novo Agendamento” para começar.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {schedules.map((s) => (
              <div key={s.id} data-testid={`neo-schedule-${s.id}`} style={{
                padding: 12, borderRadius: 10, border: "1px solid var(--border-default)",
                background: "var(--bg-surface-2)",
                display: "grid", gridTemplateColumns: "1fr auto", gap: 10, alignItems: "center",
              }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 14 }}>
                    {s.name}
                    {!s.active && (
                      <span style={{
                        fontSize: 10, padding: "1px 8px", borderRadius: 999,
                        background: "#fee2e2", color: "#991b1b", fontWeight: 700,
                      }}>Pausado</span>
                    )}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4, display: "flex", flexWrap: "wrap", gap: 12 }}>
                    <span><FileText size={11} style={{ display: "inline", marginRight: 3 }} />
                      {typeLabel(s.report_type)}</span>
                    <span><Clock size={11} style={{ display: "inline", marginRight: 3 }} />
                      {FREQ_LABELS[s.frequency]} {String(s.hour).padStart(2,"0")}:{String(s.minute).padStart(2,"0")}
                      {s.frequency === "weekly" && ` (${DOW_LABELS[s.day_of_week]})`}
                      {s.frequency === "monthly" && ` (dia ${s.day_of_month})`}
                    </span>
                    {s.whatsapp_phone && (
                      <span><Phone size={11} style={{ display: "inline", marginRight: 3 }} />
                        +{s.whatsapp_phone}</span>
                    )}
                    <span>Próximo: <b>{formatNext(s.next_run_at)}</b></span>
                    {s.run_count > 0 && <span>Execs: {s.run_count}</span>}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button data-testid={`neo-run-${s.id}`} style={btnGhost}
                          disabled={busyId === s.id}
                          onClick={() => onRunNow(s.id)} title="Executar agora">
                    <Play size={13} />
                  </button>
                  <button data-testid={`neo-edit-${s.id}`} style={btnGhost}
                          onClick={() => setEditing(s)} title="Editar">
                    <Edit3 size={13} />
                  </button>
                  <button data-testid={`neo-delete-${s.id}`} style={btnGhost}
                          onClick={() => onDelete(s.id)} title="Remover">
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Histórico */}
      <div style={{ ...card }}>
        <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <History size={16} /> Histórico (últimas {history.length})
        </div>
        {history.length === 0 ? (
          <div style={{ padding: 16, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            Nenhuma execução ainda.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--text-muted)", borderBottom: "1px solid var(--border-default)" }}>
                  <th style={{ padding: "8px 6px" }}>Quando</th>
                  <th style={{ padding: "8px 6px" }}>Agendamento</th>
                  <th style={{ padding: "8px 6px" }}>Trigger</th>
                  <th style={{ padding: "8px 6px" }}>Status</th>
                  <th style={{ padding: "8px 6px" }}>Arquivo</th>
                </tr>
              </thead>
              <tbody>
                {history.map((r) => (
                  <tr key={r.id} data-testid={`neo-history-${r.id}`} style={{ borderBottom: "1px solid var(--border-default)" }}>
                    <td style={{ padding: "8px 6px" }}>{formatNext(r.at)}</td>
                    <td style={{ padding: "8px 6px", fontWeight: 600 }}>{r.schedule_name}</td>
                    <td style={{ padding: "8px 6px" }}>{r.trigger}</td>
                    <td style={{ padding: "8px 6px" }}><StatusBadge status={r.status} /></td>
                    <td style={{ padding: "8px 6px", color: "var(--text-muted)" }}>{r.filename || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
