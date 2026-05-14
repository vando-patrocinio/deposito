import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, fmtMin, Icon, inputStyle, Metric, Row } from "@/ui";

const TYPES = ["Entrada", "Início intervalo", "Fim intervalo", "Saída"];
const TYPE_KEYS = {
  "Entrada": "entrada",
  "Início intervalo": "inicio_intervalo",
  "Fim intervalo": "fim_intervalo",
  "Saída": "saida",
};

const MANUAL_ACTIONS = ["Edição manual", "Criação manual", "Removido manualmente"];

function fmtTs(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

function collectDayAudit(day) {
  const out = [];
  (day?.records || []).forEach((r) => {
    (r.audit || []).forEach((a) => {
      if (MANUAL_ACTIONS.includes(a.action)) {
        out.push({ type: r.type, ...a });
      }
    });
  });
  out.sort((a, b) => (b.at || "").localeCompare(a.at || ""));
  return out;
}

function DayAuditTimeline({ entries }) {
  if (!entries || entries.length === 0) {
    return (
      <div data-testid="day-audit-empty" style={{ background: "#f8fafc", border: "1px dashed #cbd5e1", borderRadius: 12, padding: 12, color: "#64748b", fontSize: 13, textAlign: "center" }}>
        Sem edições manuais neste dia ainda.
      </div>
    );
  }
  return (
    <div data-testid="day-audit-timeline" style={{ borderLeft: "2px solid #e2e8f0", paddingLeft: 14, marginTop: 4 }}>
      {entries.map((e, i) => {
        const isRemove = e.action === "Removido manualmente";
        return (
          <div key={i} data-testid={`day-audit-entry-${i}`} style={{ position: "relative", paddingBottom: 12 }}>
            <span style={{
              position: "absolute", left: -21, top: 4,
              width: 12, height: 12, borderRadius: "50%",
              background: isRemove ? "#dc2626" : "#f59e0b",
              border: "3px solid white", boxShadow: "0 0 0 2px " + (isRemove ? "#fecaca" : "#fde68a"),
            }} />
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <strong style={{ fontSize: 13 }}>{e.type}</strong>
              <span style={{
                fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999,
                background: isRemove ? "#fee2e2" : "#fde68a",
                color: isRemove ? "#991b1b" : "#92400e",
              }}>{e.action}</span>
            </div>
            {(e.from_time || e.to_time) && (
              <div style={{ fontSize: 12, color: "#334155", marginTop: 2 }}>
                <strong>{e.from_time || "—"}</strong> → <strong>{e.to_time || "—"}</strong>
              </div>
            )}
            <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
              Por <strong>{e.actor || "Gestor"}</strong> em {fmtTs(e.at)}
            </div>
            {e.reason && (
              <div style={{ marginTop: 4, fontSize: 12, color: "#0f172a", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8, padding: "6px 8px" }}>
                {e.reason}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function EditDayModal({ open, day, collabId, onClose, onSaved }) {
  const [form, setForm] = useState({});
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const dayEntries = useMemo(() => collectDayAudit(day), [day]);

  useEffect(() => {
    if (!open || !day) return;
    setForm({
      "Entrada": day.entrada || "",
      "Início intervalo": day.inicio_intervalo || "",
      "Fim intervalo": day.fim_intervalo || "",
      "Saída": day.saida || "",
    });
    setReason("");
    setErr("");
  }, [open, day]);

  if (!open || !day) return null;

  async function save() {
    setErr("");
    if (!reason.trim() || reason.trim().length < 3) {
      setErr("Justificativa é obrigatória (mínimo 3 caracteres).");
      return;
    }
    setSaving(true);
    try {
      const original = {
        "Entrada": day.entrada || "",
        "Início intervalo": day.inicio_intervalo || "",
        "Fim intervalo": day.fim_intervalo || "",
        "Saída": day.saida || "",
      };
      const changes = TYPES.filter((t) => (form[t] || "") !== (original[t] || "") && form[t]);
      if (changes.length === 0) {
        setErr("Nenhuma alteração detectada.");
        setSaving(false);
        return;
      }
      for (const t of changes) {
        await api.manualEntry({
          collaborator_id: collabId,
          type: t,
          date: day.date,
          time: form[t],
          reason: reason.trim(),
          actor: "Gestor",
        });
      }
      onSaved && onSaved();
      onClose();
    } catch (e) {
      setErr("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      role="dialog"
      data-testid="edit-day-modal"
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,.55)", zIndex: 9999,
        display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        background: "white", borderRadius: 22, maxWidth: 560, width: "100%",
        maxHeight: "90vh", display: "flex", flexDirection: "column",
        boxShadow: "0 24px 60px rgba(15,23,42,.32)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "20px 22px 6px" }}>
          <h3 style={{ margin: 0 }}>Editar ponto — {day.date}</h3>
          <button onClick={onClose} data-testid="edit-day-close" style={{ background: "transparent", border: "none", fontSize: 22, cursor: "pointer", color: "#64748b" }}>×</button>
        </div>
        <div style={{ overflowY: "auto", padding: "0 22px 22px" }}>
          <p style={{ color: "#64748b", marginTop: 0, fontSize: 13 }}>
            Ajuste manualmente as marcações faltantes ou incorretas. O registro será marcado como <strong>modificado</strong> e auditado.
          </p>

          {TYPES.map((t) => (
            <Field key={t} label={t}>
              <input
                type="time"
                value={form[t] || ""}
                onChange={(e) => setForm({ ...form, [t]: e.target.value })}
                data-testid={`edit-time-${TYPE_KEYS[t]}`}
                style={inputStyle}
              />
            </Field>
          ))}

          <Field label="Justificativa (obrigatória)">
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Ex.: colaborador esqueceu de bater entrada — confirmado por mim"
              data-testid="edit-reason"
              rows={3}
              style={{ ...inputStyle, fontFamily: "inherit", resize: "vertical" }}
            />
          </Field>

          {err && <div style={{ color: "#be123c", marginBottom: 10, fontSize: 13 }}>{err}</div>}

          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginBottom: 16 }}>
            <Button variant="secondary" onClick={onClose} disabled={saving} data-testid="edit-cancel">Cancelar</Button>
            <Button onClick={save} disabled={saving} data-testid="edit-save">
              {saving ? "Salvando..." : "Salvar correção"}
            </Button>
          </div>

          <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: 14, marginTop: 4 }}>
            <h4 style={{ margin: "0 0 8px", fontSize: 14, color: "#0f172a" }}>
              Histórico de edições deste dia
              {dayEntries.length > 0 && (
                <span style={{ marginLeft: 6, fontSize: 11, background: "#fde68a", color: "#92400e", padding: "2px 8px", borderRadius: 999, fontWeight: 800 }}>{dayEntries.length}</span>
              )}
            </h4>
            <DayAuditTimeline entries={dayEntries} />
          </div>
        </div>
      </div>
    </div>
  );
}

function TimeCell({ value, missing, origin }) {
  if (value) {
    return (
      <span style={{ whiteSpace: "nowrap" }}>
        {value}
        {origin && (
          <span style={{
            marginLeft: 3, fontSize: 9, color: "#64748b", fontWeight: 600,
          }}>({origin})</span>
        )}
      </span>
    );
  }
  if (missing) return <span style={{ color: "#dc2626", fontWeight: 800 }}>—</span>;
  return <span style={{ color: "#94a3b8" }}>—</span>;
}

const thS = (align = "center") => ({
  padding: "8px 4px", fontSize: 10, fontWeight: 700,
  textTransform: "uppercase", letterSpacing: "0.04em",
  textAlign: align, whiteSpace: "nowrap",
});
const tdS = (extra = {}) => ({
  padding: "6px 4px", textAlign: "center",
  whiteSpace: "nowrap", fontSize: 12,
  ...extra,
});

function downloadCsv(filename, rows) {
  const escape = (v) => {
    if (v === null || v === undefined) return "";
    const s = String(v).replace(/"/g, '""');
    return /[",\n;]/.test(s) ? `"${s}"` : s;
  };
  const csv = rows.map((r) => r.map(escape).join(";")).join("\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
}

function AuditModal({ open, days, monthLabel, collabName, onClose }) {
  if (!open) return null;
  const entries = [];
  (days || []).forEach((d) => {
    (d.records || []).forEach((r) => {
      (r.audit || []).forEach((a) => {
        if (MANUAL_ACTIONS.includes(a.action)) {
          entries.push({ date: d.date, type: r.type, ...a });
        }
      });
    });
  });
  entries.sort((a, b) => (b.at || "").localeCompare(a.at || ""));

  return (
    <div
      role="dialog"
      data-testid="audit-modal"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,.55)", zIndex: 9999,
        display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
      }}
    >
      <div style={{
        background: "white", borderRadius: 22, width: "100%", maxWidth: 720,
        maxHeight: "85vh", display: "flex", flexDirection: "column",
        boxShadow: "0 24px 60px rgba(15,23,42,.32)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "18px 22px 8px", gap: 8, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0 }}>Auditoria de edições manuais</h3>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button
              data-testid="audit-csv-btn"
              disabled={entries.length === 0}
              onClick={() => {
                const header = ["Data", "Tipo", "Ação", "De", "Para", "Autor", "Quando", "Justificativa"];
                const rows = [header, ...entries.map((e) => [
                  e.date, e.type, e.action, e.from_time || "", e.to_time || "",
                  e.actor || "Gestor", fmtTs(e.at), e.reason || "",
                ])];
                const safeName = (collabName || "colaborador").replace(/\s+/g, "_").toLowerCase();
                const safeMonth = (monthLabel || "").replace(/\s+/g, "").replace("/", "-");
                downloadCsv(`auditoria-${safeName}-${safeMonth}.csv`, rows);
              }}
              style={{
                background: entries.length === 0 ? "#f1f5f9" : "#0f172a",
                color: entries.length === 0 ? "#94a3b8" : "white",
                border: "none", padding: "8px 14px", borderRadius: 12,
                fontWeight: 800, cursor: entries.length === 0 ? "not-allowed" : "pointer", fontSize: 13,
              }}
            >
              Baixar CSV
            </button>
            <button onClick={onClose} data-testid="audit-close" style={{ background: "transparent", border: "none", fontSize: 22, cursor: "pointer", color: "#64748b" }}>×</button>
          </div>
        </div>
        <p style={{ color: "#64748b", margin: "0 22px 10px", fontSize: 13 }}>
          {entries.length === 0
            ? "Nenhuma edição manual registrada neste mês."
            : `${entries.length} edição(ões) registrada(s) — mais recentes primeiro.`}
        </p>
        <div style={{ overflowY: "auto", padding: "8px 22px 22px" }}>
          {entries.length === 0 ? (
            <div data-testid="audit-empty" style={{ background: "#f8fafc", border: "1px dashed #cbd5e1", borderRadius: 14, padding: 22, textAlign: "center", color: "#64748b" }}>
              Nada para mostrar. As edições feitas pelo gestor aparecerão aqui.
            </div>
          ) : (
            entries.map((e, i) => (
              <div key={i} data-testid={`audit-entry-${i}`} style={{
                border: "1px solid #e2e8f0", borderRadius: 14, padding: 12, marginBottom: 8,
                background: e.action === "Removido manualmente" ? "#fef2f2" : "#fffbeb",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
                  <strong style={{ fontSize: 14 }}>
                    {e.date} · {e.type}
                  </strong>
                  <span style={{
                    fontSize: 11, fontWeight: 800, padding: "2px 8px", borderRadius: 999,
                    background: e.action === "Removido manualmente" ? "#fee2e2" : "#fde68a",
                    color: e.action === "Removido manualmente" ? "#991b1b" : "#92400e",
                  }}>{e.action}</span>
                </div>
                <div style={{ fontSize: 13, color: "#334155", marginBottom: 4 }}>
                  {e.from_time || e.to_time ? (
                    <>
                      <strong>{e.from_time || "—"}</strong> → <strong>{e.to_time || "—"}</strong>
                    </>
                  ) : null}
                </div>
                <div style={{ fontSize: 12, color: "#64748b" }}>
                  Por <strong>{e.actor || "Gestor"}</strong> em {fmtTs(e.at)}
                </div>
                {e.reason && (
                  <div style={{ marginTop: 6, fontSize: 13, color: "#0f172a", background: "white", border: "1px solid #e2e8f0", borderRadius: 10, padding: 8 }}>
                    <span style={{ color: "#64748b", fontSize: 11, fontWeight: 700 }}>JUSTIFICATIVA</span>
                    <div>{e.reason}</div>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default function TimesheetView() {
  const [collabs, setCollabs] = useState([]);
  const [collabId, setCollabId] = useState(null);
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [data, setData] = useState(null);
  const [msg, setMsg] = useState("");
  const [editing, setEditing] = useState(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [overview, setOverview] = useState(null);

  useEffect(() => {
    api.overtimeDashboard(year, month).then(setOverview).catch(() => setOverview(null));
  }, [year, month, data]);

  useEffect(() => {
    api.listCollaborators().then((cs) => {
      // Mostra TODOS os colaboradores ativos, exceto os com clock_in_enabled
      // explicitamente desligado (false). Aceita true/null/undefined.
      // Também exclui o pseudo-colaborador "Sem técnico (Atlaz)" usado para
      // chamados sem técnico vinculado.
      const eligible = (cs || []).filter((c) => {
        if (c.active === false) return false;
        if (c.clock_in_enabled === false) return false;
        const nm = (c.name || c.full_name || "").toLowerCase();
        if (nm.includes("sem técnico") || nm.includes("sem tecnico")) return false;
        return true;
      });
      // Ordena alfabeticamente por nome pra ficar previsível no select
      eligible.sort((a, b) =>
        (a.name || a.full_name || "").localeCompare(b.name || b.full_name || "")
      );
      setCollabs(eligible);
      if (eligible[0]) setCollabId(eligible[0].id);
      else setCollabId(null);
    });
  }, []);

  function reload() {
    if (!collabId) return;
    api.timesheet(collabId, year, month).then(setData).catch(() => setData(null));
  }

  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [collabId, year, month]);

  async function send() {
    setMsg("Enviando...");
    try {
      const res = await api.sendTimesheetNow(collabId, year, month);
      setMsg(res.sent ? `Enviado para ${res.to}` : `Não enviado: ${res.reason}`);
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    }
  }

  function downloadPdf() {
    if (!collabId) return;
    const url = api.timesheetPdfUrl(collabId, year, month);
    window.open(url, "_blank", "noopener,noreferrer");
  }

  function downloadCollectivePdf() {
    const url = api.collectiveTimesheetPdfUrl(year, month);
    window.open(url, "_blank", "noopener,noreferrer");
  }

  const monthLabel = useMemo(() => {
    const names = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"];
    return `${names[month - 1]} / ${year}`;
  }, [month, year]);

  return (
    <div>
      {overview && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14, marginBottom: 14 }}>
          <Card title={`HE no mês — ${monthLabel}`} style={{ marginBottom: 0 }}>
            <Metric label="Total HE acumulada" value={fmtMin(overview.total_overtime_min)} />
            <div style={{ marginTop: 10 }}>
              <Metric label="Total a pagar (somente policy=pago)" value={`R$ ${overview.total_paid_brl.toFixed(2).replace(".", ",")}`} />
            </div>
            <p style={{ color: "#94a3b8", fontSize: 11, marginTop: 8, marginBottom: 0 }}>
              Considera HE 50% (dia útil) e 100% (domingo/feriado) — CLT.
            </p>
          </Card>

          <Card title="Top 3 — mais HE no mês" style={{ marginBottom: 0 }}>
            {(overview.top3_overtime || []).length === 0 ? (
              <p style={{ color: "#64748b", margin: 0 }}>Ninguém com HE este mês.</p>
            ) : (
              overview.top3_overtime.map((r, i) => (
                <div key={r.collaborator_id} data-testid={`top3-ot-${i}`} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: i < 2 ? "1px solid #f1f5f9" : "none" }}>
                  <div style={{ width: 28, height: 28, borderRadius: "50%", background: i === 0 ? "#fde68a" : "#e2e8f0", color: i === 0 ? "#92400e" : "#475569", display: "grid", placeItems: "center", fontWeight: 900, fontSize: 13 }}>
                    {i + 1}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <strong style={{ fontSize: 13 }}>{r.name}</strong>
                    <div style={{ color: "#94a3b8", fontSize: 11 }}>{r.policy_mode === "pago" ? "HE paga" : "Banco de horas"}</div>
                  </div>
                  <strong style={{ fontSize: 13 }}>{fmtMin(r.total_overtime_min)}</strong>
                </div>
              ))
            )}
          </Card>

          <Card title="Top 3 — HE a pagar (R$)" style={{ marginBottom: 0 }}>
            {(overview.top3_paid || []).length === 0 ? (
              <p style={{ color: "#64748b", margin: 0 }}>Ninguém em política <strong>HE paga</strong> com saldo &gt; 0.</p>
            ) : (
              overview.top3_paid.map((r, i) => (
                <div key={r.collaborator_id} data-testid={`top3-paid-${i}`} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: i < 2 ? "1px solid #f1f5f9" : "none" }}>
                  <div style={{ width: 28, height: 28, borderRadius: "50%", background: i === 0 ? "#bbf7d0" : "#e2e8f0", color: i === 0 ? "#166534" : "#475569", display: "grid", placeItems: "center", fontWeight: 900, fontSize: 13 }}>
                    {i + 1}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <strong style={{ fontSize: 13 }}>{r.name}</strong>
                    <div style={{ color: "#94a3b8", fontSize: 11 }}>R$ {(r.hourly_rate_brl || 0).toFixed(2)}/h</div>
                  </div>
                  <strong style={{ fontSize: 13, color: "#166534" }}>R$ {r.paid_overtime_brl.toFixed(2).replace(".", ",")}</strong>
                </div>
              ))
            )}
          </Card>
        </div>
      )}

      <Card title="Espelho mensal">
        {collabs.length === 0 ? (
          <div data-testid="sheet-empty-state" style={{
            padding: "20px 16px", background: "#fef3c7", border: "1px solid #fcd34d",
            borderRadius: 10, color: "#92400e", fontSize: 13, lineHeight: 1.55,
          }}>
            <strong>Nenhum colaborador habilitado para bater ponto.</strong><br />
            Vá em <strong>Cadastro → Colaboradores</strong>, edite o colaborador
            desejado e marque a opção <em>"Habilitado para bater ponto"</em>.
          </div>
        ) : (
          <>
        <Row label="Colaborador" value={
          <select value={collabId || ""} onChange={(e) => setCollabId(e.target.value)} data-testid="sheet-collab-select">
            {collabs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        } />
        <Row label="Período" value={
          <span>
            <select value={month} onChange={(e) => setMonth(Number(e.target.value))} data-testid="sheet-month">
              {Array.from({ length: 12 }).map((_, i) => <option key={i + 1} value={i + 1}>{String(i + 1).padStart(2, "0")}</option>)}
            </select>{" "}/{" "}
            <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 90, padding: 6, borderRadius: 8, border: "1px solid #cbd5e1" }} data-testid="sheet-year" />
          </span>
        } />
        {data && (
          <>
            <Row label="Total trabalhado" value={fmtMin(data.total_worked_min)} />
            <Row label="Saldo do mês" value={fmtMin(data.total_balance_min)} />
            <Row label="HE 50% (dia útil)" value={fmtMin(data.total_overtime_weekday_min)} />
            <Row label="HE 100% (dom/feriado)" value={fmtMin(data.total_overtime_sunday_holiday_min)} />
            <Row
              label="Política"
              value={
                <span style={{ fontWeight: 800, color: data.policy_mode === "pago" ? "#166534" : "#0369a1" }}>
                  {data.policy_mode === "pago" ? `HE paga · R$ ${data.hourly_rate_brl.toFixed(2)}/h · Total: R$ ${data.paid_overtime_brl.toFixed(2)}` : "Banco de horas"}
                </span>
              }
            />
          </>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          <Button onClick={downloadPdf} variant="secondary" data-testid="download-pdf-btn">
            <Icon name="export" /> Baixar PDF
          </Button>
          <Button onClick={downloadCollectivePdf} variant="soft"
                   data-testid="download-collective-pdf-btn"
                   title="Gera 1 PDF único com todos os colaboradores ativos do mês (1 página por colaborador). Útil pro fechamento mensal do RH.">
            <Icon name="export" /> Espelho coletivo (todos)
          </Button>
          <Button onClick={() => setAuditOpen(true)} variant="soft" data-testid="open-audit-btn">
            <Icon name="shield" /> Auditoria
            {data && (() => {
              const n = (data.days || []).reduce((acc, d) => acc + (d.records || []).reduce((a, r) => a + (r.audit || []).filter((x) => ["Edição manual", "Criação manual", "Removido manualmente"].includes(x.action)).length, 0), 0);
              return n > 0 ? <span style={{ marginLeft: 6, fontSize: 11, background: "#fde68a", color: "#92400e", padding: "2px 8px", borderRadius: 999, fontWeight: 800 }}>{n}</span> : null;
            })()}
          </Button>
          <Button onClick={() => setBatchOpen(true)} variant="soft" data-testid="batch-fix-btn" title="Preenche dias úteis incompletos com o horário cadastrado">
            <Icon name="sync" /> Acertar em lote
          </Button>
          <Button onClick={send} data-testid="send-timesheet-btn"><Icon name="mail" /> Enviar agora</Button>
          {msg && <span style={{ alignSelf: "center", color: msg.startsWith("Erro") || msg.startsWith("Não") ? "#be123c" : "#166534" }}>{msg}</span>}
        </div>
          </>
        )}
      </Card>

      <Card title={`Espelho mensal — ${monthLabel}`}>
        {!data ? (
          <p style={{ color: "#64748b" }}>Carregando...</p>
        ) : (
          <>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 10,
                          fontSize: 11, color: "#475569" }}>
              <span><strong>Legenda:</strong></span>
              <span>(I) Incluído manual</span>
              <span>(P) Pré-assinalado</span>
              <span>(M) Mobile/Web</span>
              <span>(C) Coletor REP</span>
              <span style={{ marginLeft: "auto", fontStyle: "italic" }}>
                Portaria 671/2021-MTE · CLT art. 74 §2º
              </span>
            </div>
            <div style={{ overflowX: "auto", border: "1px solid #e2e8f0", borderRadius: 10 }}>
              <table data-testid="sheet-table-controlid" style={{ width: "100%", minWidth: 1280, borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "#0b1220", color: "white" }}>
                  <th style={thS()}>Dia</th>
                  <th style={thS()}>DS</th>
                  <th style={thS("left")}>Previsto</th>
                  <th style={thS()}>Ent. 1</th>
                  <th style={thS()}>Saí. 1</th>
                  <th style={thS()}>Ent. 2</th>
                  <th style={thS()}>Saí. 2</th>
                  <th style={thS()}>Normais</th>
                  <th style={thS()}>Noturno</th>
                  <th style={thS()}>Falta/Atr.</th>
                  <th style={thS()}>Abono</th>
                  <th style={thS()}>Extra D.</th>
                  <th style={thS()}>Extra N.</th>
                  <th style={thS()}>Saldo banco</th>
                  <th style={{ ...thS("right"), paddingRight: 8 }}>Ação</th>
                </tr>
              </thead>
              <tbody>
                {data.days.map((d) => {
                  const isFuture = d.is_future;
                  const isToday = d.is_today;
                  const isWeekend = d.is_weekend;
                  const isHoliday = d.is_holiday;
                  const missingEntrada = !isFuture && !isWeekend && !isHoliday && (d.missing || []).includes("Entrada");
                  const missingSaida = !isFuture && !isWeekend && !isHoliday && (d.missing || []).includes("Saída");
                  const dayNum = Number(d.date.slice(8, 10));
                  const dayName = ["Dom","Seg","Ter","Qua","Qui","Sex","Sáb"][d.weekday ?? 0];
                  const rowBg = isToday ? "#fff7ed"
                    : isFuture ? "#f8fafc"
                    : isHoliday ? "#fef9c3"
                    : isWeekend ? "#f1f5f9"
                    : "white";
                  const rowStyle = {
                    borderTop: "1px solid #e2e8f0",
                    background: rowBg,
                    color: isFuture ? "#94a3b8" : "#0f172a",
                  };
                  const orig = d.origens || {};
                  return (
                    <tr key={d.date} style={rowStyle} data-testid={`sheet-row-${d.date}`}>
                      <td style={tdS({ fontWeight: 700, paddingLeft: 8 })}>
                        {String(dayNum).padStart(2, "0")}
                        {isToday && <span style={{ marginLeft: 4, fontSize: 9, color: "#ea580c" }}>•</span>}
                        {d.manually_edited && (
                          <span data-testid={`modified-tag-${d.date}`}
                                title="Algum horário foi editado manualmente"
                                style={{ marginLeft: 4, fontSize: 9, color: "#92400e" }}>✎</span>
                        )}
                      </td>
                      <td style={tdS({ color: "#64748b", fontSize: 11 })}>{dayName}</td>
                      <td style={tdS({ textAlign: "left", color: "#475569", fontSize: 11 })}>
                        {d.previsto || "—"}
                        {isHoliday && (
                          <span data-testid={`holiday-tag-${d.date}`} title={d.holiday?.name}
                                style={{ marginLeft: 4, fontSize: 9, fontWeight: 700, color: "#92400e",
                                          background: "#fde68a", padding: "1px 5px", borderRadius: 4 }}>
                            feriado
                          </span>
                        )}
                      </td>
                      <td style={tdS()}><TimeCell value={d.entrada} missing={missingEntrada} origin={orig.entrada} /></td>
                      <td style={tdS()}><TimeCell value={d.inicio_intervalo} missing={false} origin={orig.inicio_intervalo} /></td>
                      <td style={tdS()}><TimeCell value={d.fim_intervalo} missing={false} origin={orig.fim_intervalo} /></td>
                      <td style={tdS()}><TimeCell value={d.saida} missing={missingSaida} origin={orig.saida} /></td>
                      <td style={tdS({ fontWeight: d.worked > 0 ? 600 : 400 })}>
                        {isFuture ? "—" : (d.worked > 0 ? fmtMin(d.worked) : "—")}
                      </td>
                      <td style={tdS({ color: d.noturno_min > 0 ? "#7c3aed" : "#94a3b8", fontWeight: d.noturno_min > 0 ? 700 : 400 })}>
                        {isFuture ? "—" : (d.noturno_min > 0 ? fmtMin(d.noturno_min) : "—")}
                      </td>
                      <td style={tdS({ color: d.falta_atraso_min > 0 ? "#dc2626" : "#94a3b8", fontWeight: d.falta_atraso_min > 0 ? 700 : 400 })}>
                        {isFuture ? "—" : (d.falta_atraso_min > 0 ? `-${fmtMin(d.falta_atraso_min)}` : "—")}
                      </td>
                      <td style={tdS({ color: d.abono_min > 0 ? "#0369a1" : "#94a3b8" })}>
                        {isFuture ? "—" : (d.abono_min > 0 ? fmtMin(d.abono_min) : "—")}
                      </td>
                      <td style={tdS({ color: d.extra_diurna_min > 0 ? "#16a34a" : "#94a3b8", fontWeight: d.extra_diurna_min > 0 ? 700 : 400 })}>
                        {isFuture ? "—" : (d.extra_diurna_min > 0 ? fmtMin(d.extra_diurna_min) : "—")}
                      </td>
                      <td style={tdS({ color: d.extra_noturna_min > 0 ? "#16a34a" : "#94a3b8", fontWeight: d.extra_noturna_min > 0 ? 700 : 400 })}>
                        {isFuture ? "—" : (d.extra_noturna_min > 0 ? fmtMin(d.extra_noturna_min) : "—")}
                      </td>
                      <td style={tdS({ color: (d.banco_saldo_min || 0) < 0 ? "#dc2626" : (d.banco_saldo_min || 0) > 0 ? "#16a34a" : "inherit",
                                       fontWeight: 700 })}>
                        {fmtMin(d.banco_saldo_min || 0)}
                      </td>
                      <td style={{ ...tdS({ textAlign: "right", paddingRight: 8 }) }}>
                        {!isFuture && (
                          <button
                            onClick={() => setEditing(d)}
                            data-testid={`edit-day-btn-${d.date}`}
                            title="Editar / corrigir horários"
                            style={{
                              background: "white", border: "1px solid #cbd5e1", borderRadius: 6,
                              padding: "2px 8px", cursor: "pointer", fontSize: 11, fontWeight: 600,
                            }}
                          >
                            Editar
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {/* Linha TOTAIS — Control iD style */}
                <tr style={{ background: "#1f2937", color: "white", fontWeight: 700 }}>
                  <td colSpan={2} style={tdS({ paddingLeft: 8 })}>TOTAIS</td>
                  <td style={tdS()}></td>
                  <td style={tdS()}></td>
                  <td style={tdS()}></td>
                  <td style={tdS()}></td>
                  <td style={tdS()}></td>
                  <td style={tdS()}>{fmtMin(data.total_worked_min || 0)}</td>
                  <td style={tdS()}>{fmtMin(data.total_noturno_min || 0)}</td>
                  <td style={tdS({ color: (data.total_falta_atraso_min || 0) > 0 ? "#fca5a5" : "white" })}>
                    {(data.total_falta_atraso_min || 0) > 0 ? `-${fmtMin(data.total_falta_atraso_min)}` : "—"}
                  </td>
                  <td style={tdS()}>{(data.total_abono_min || 0) > 0 ? fmtMin(data.total_abono_min) : "—"}</td>
                  <td style={tdS({ color: (data.total_extra_diurna_min || 0) > 0 ? "#86efac" : "white" })}>
                    {(data.total_extra_diurna_min || 0) > 0 ? fmtMin(data.total_extra_diurna_min) : "—"}
                  </td>
                  <td style={tdS({ color: (data.total_extra_noturna_min || 0) > 0 ? "#86efac" : "white" })}>
                    {(data.total_extra_noturna_min || 0) > 0 ? fmtMin(data.total_extra_noturna_min) : "—"}
                  </td>
                  <td style={tdS({ color: (data.banco_saldo_final_min || 0) < 0 ? "#fca5a5" :
                                          (data.banco_saldo_final_min || 0) > 0 ? "#86efac" : "white" })}>
                    {fmtMin(data.banco_saldo_final_min || data.total_balance_min || 0)}
                  </td>
                  <td style={tdS()}></td>
                </tr>
              </tbody>
            </table>
            </div>
          </>
        )}
      </Card>

      <PrintAuditCard />

      <EditDayModal
        open={!!editing}
        day={editing}
        collabId={collabId}
        onClose={() => setEditing(null)}
        onSaved={reload}
      />

      <AuditModal
        open={auditOpen}
        days={data?.days}
        monthLabel={monthLabel}
        collabName={collabs.find((c) => c.id === collabId)?.name}
        onClose={() => setAuditOpen(false)}
      />

      <BatchFixModal
        open={batchOpen}
        collabId={collabId}
        year={year}
        month={month}
        monthLabel={monthLabel}
        onClose={() => setBatchOpen(false)}
        onDone={reload}
      />
    </div>
  );
}

function BatchFixModal({ open, collabId, year, month, monthLabel, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    setReason(""); setOverwrite(false); setResult(null); setErr("");
  }, [open]);

  if (!open) return null;

  async function run() {
    setErr("");
    if (!reason.trim() || reason.trim().length < 3) {
      setErr("Justificativa obrigatória (mínimo 3 caracteres).");
      return;
    }
    setRunning(true);
    try {
      const res = await api.batchFixSchedule({
        collaborator_id: collabId, year, month,
        reason: reason.trim(), overwrite_existing: overwrite, actor: "Gestor",
      });
      setResult(res);
      onDone && onDone();
    } catch (e) {
      setErr("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div
      role="dialog"
      data-testid="batch-fix-modal"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.55)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
    >
      <div style={{ background: "white", borderRadius: 22, width: "100%", maxWidth: 520, padding: 22, boxShadow: "0 24px 60px rgba(15,23,42,.32)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>Acertar marcações em lote</h3>
          <button onClick={onClose} data-testid="batch-fix-close" style={{ background: "transparent", border: "none", fontSize: 22, cursor: "pointer", color: "#64748b" }}>×</button>
        </div>
        <p style={{ color: "#64748b", marginTop: 0, fontSize: 13 }}>
          Preenche todos os <strong>dias úteis</strong> de <strong>{monthLabel}</strong> em que faltam marcações,
          usando o <strong>horário cadastrado</strong> do colaborador. Sábados, domingos e dias futuros são ignorados.
        </p>

        <Field label="Justificativa (obrigatória) — aplicada a todas as marcações criadas">
          <textarea
            value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="Ex.: colaborador esqueceu de bater ponto em vários dias — confirmado por ele e pela liderança"
            data-testid="batch-fix-reason" rows={3}
            style={{ ...inputStyle, fontFamily: "inherit", resize: "vertical" }}
          />
        </Field>

        <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12, fontSize: 13, color: "#475569", cursor: "pointer" }}>
          <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} data-testid="batch-fix-overwrite" />
          Sobrescrever horários já existentes (use com cuidado)
        </label>

        {err && <div style={{ color: "#be123c", marginBottom: 10, fontSize: 13 }}>{err}</div>}
        {result && (
          <div data-testid="batch-fix-result" style={{ background: "#dcfce7", color: "#166534", padding: 10, borderRadius: 12, marginBottom: 10, fontSize: 13 }}>
            ✅ {result.message} {result.skipped ? `(${result.skipped} pulada(s))` : ""}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Button variant="secondary" onClick={onClose} disabled={running} data-testid="batch-fix-cancel">
            {result ? "Fechar" : "Cancelar"}
          </Button>
          {!result && (
            <Button onClick={run} disabled={running} data-testid="batch-fix-run">
              {running ? "Aplicando..." : "Aplicar agora"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ============================================================= */
/* PrintAuditCard — histórico de impressões / downloads / envios
   do espelho de ponto. Compliance: cada ação fica rastreada. */
function PrintAuditCard() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.printAuditList(30)
      .then((r) => setItems(r?.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return null;
  if (!items.length) return null;

  return (
    <Card title="Histórico de impressões (ID de Impressão)" style={{ marginTop: 16 }}>
      <p style={{ fontSize: 12, color: "#64748b", marginTop: 0, marginBottom: 12 }}>
        Cada vez que um espelho é baixado, impresso ou enviado, o sistema gera um
        <strong> ID de Impressão</strong> único, gravado nesta auditoria para fins de
        compliance (Portaria 671/2021).
      </p>
      <div style={{ overflowX: "auto" }}>
        <table data-testid="print-audit-table" style={{
          width: "100%", borderCollapse: "collapse", fontSize: 12,
        }}>
          <thead>
            <tr style={{ background: "#f1f5f9", color: "#475569" }}>
              <th style={{ padding: "6px 8px", textAlign: "left", fontSize: 10, textTransform: "uppercase" }}>ID de Impressão</th>
              <th style={{ padding: "6px 8px", textAlign: "left", fontSize: 10, textTransform: "uppercase" }}>Tipo</th>
              <th style={{ padding: "6px 8px", textAlign: "left", fontSize: 10, textTransform: "uppercase" }}>Colaborador</th>
              <th style={{ padding: "6px 8px", textAlign: "left", fontSize: 10, textTransform: "uppercase" }}>Solicitante</th>
              <th style={{ padding: "6px 8px", textAlign: "left", fontSize: 10, textTransform: "uppercase" }}>Quando</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                <td style={{ padding: "6px 8px", fontFamily: "monospace", fontSize: 10.5 }}>
                  {it.id}
                </td>
                <td style={{ padding: "6px 8px" }}>
                  <span style={{
                    padding: "2px 7px", borderRadius: 999, fontSize: 10, fontWeight: 700,
                    background: it.type === "timesheet_collective" ? "#fef3c7" : "#dbeafe",
                    color: it.type === "timesheet_collective" ? "#92400e" : "#1e40af",
                  }}>
                    {it.type === "timesheet_collective" ? "COLETIVO" : "INDIVIDUAL"}
                  </span>
                </td>
                <td style={{ padding: "6px 8px" }}>
                  {it.collaborator_name || (it.count_collaborators ? `${it.count_collaborators} colaborador(es)` : "—")}
                </td>
                <td style={{ padding: "6px 8px" }}>{it.requested_by_user_name || "—"}</td>
                <td style={{ padding: "6px 8px", color: "#64748b" }}>
                  {it.at ? new Date(it.at).toLocaleString("pt-BR") : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

