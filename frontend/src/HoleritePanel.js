import React, { useCallback, useEffect, useState } from "react";
import {
  Receipt, Upload, Search, Calendar, User as UserIcon, Shield, MessageCircle,
  Eye, Ban, History, FileText, AlertCircle, CheckCircle2, RefreshCw, X,
  Sparkles, Bot, AlertTriangle, Loader2, Check, Users, Trash2,
} from "lucide-react";
import { api } from "@/api";

/* =============================================================
   HoleritePanel — RH/Admin
   - Upload PDF com validação
   - Lista com filtros
   - Notificar via WhatsApp (gera link seguro)
   - Revogar holerite
   - Auditoria por documento
============================================================= */
const MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                  "Jul", "Ago", "Set", "Out", "Nov", "Dez"];

export default function HoleritePanel() {
  const [items, setItems] = useState([]);
  const [collabs, setCollabs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(0);
  const [showUpload, setShowUpload] = useState(false);
  const [showAiImport, setShowAiImport] = useState(false);
  const [auditOf, setAuditOf] = useState(null);

  const reload = useCallback(async () => {
    try {
      const params = { year };
      if (month) params.month = month;
      if (filter) params.q = filter;
      const r = await api.holeriteList(params);
      setItems(r.items || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [year, month, filter]);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    api.listCollaborators().then((d) => {
      setCollabs(Array.isArray(d) ? d : (d?.items || []));
    }).catch(() => setCollabs([]));
  }, []);

  const totalGross = items.reduce((s, h) => s + (h.gross || 0), 0);
  const totalNet = items.reduce((s, h) => s + (h.net || 0), 0);
  const notifiedCount = items.filter((h) => h.notified_at).length;
  const viewedCount = items.filter((h) => h.viewed_at).length;

  return (
    <div data-testid="holerite-panel" style={{ display: "grid", gap: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{
          width: 42, height: 42, borderRadius: 10,
          background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 12px rgba(99,102,241,.35)",
        }}>
          <Receipt size={20} strokeWidth={1.75} />
        </div>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800, letterSpacing: "-0.02em" }}>
            Holerite Digital
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Distribuição segura com link autenticado, LGPD e auditoria completa.
          </div>
        </div>
        <span style={{ flex: 1 }} />
        <button onClick={reload} style={btn("ghost")} title="Atualizar">
          <RefreshCw size={13} />
        </button>
        <button onClick={() => setShowAiImport(true)}
                data-testid="holerite-ai-import-btn"
                style={{
                  padding: "8px 14px", borderRadius: 8,
                  border: "1px solid #8b5cf6",
                  background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
                  color: "white",
                  fontSize: 13, fontWeight: 700, cursor: "pointer",
                  display: "inline-flex", alignItems: "center", gap: 6,
                  boxShadow: "0 4px 12px rgba(139,92,246,.25)",
                  transition: "all .15s",
                }}>
          <Sparkles size={14} /> Importar com Holerite IA
        </button>
        <button onClick={() => setShowUpload(true)}
                data-testid="holerite-add-btn"
                style={btn("primary")}>
          <Upload size={14} /> Lançar holerite
        </button>
      </div>

      {/* LGPD strip */}
      <div style={{
        padding: 10, borderRadius: 8,
        background: "rgba(99,102,241,.06)",
        border: "1px solid rgba(99,102,241,.18)",
        display: "flex", alignItems: "center", gap: 8, fontSize: 11,
        color: "var(--text-secondary)",
      }}>
        <Shield size={13} color="#6366f1" />
        <span>
          <strong>LGPD</strong>: holerites são armazenados criptografados,
          servidos só com autenticação do colaborador e auditados.
          Links expiram em 72h por padrão. PDF nunca trafega anexado no WhatsApp.
        </span>
      </div>

      {/* KPIs */}
      <div style={{ display: "grid",
                       gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                       gap: 10 }}>
        <Kpi label="Holerites" value={items.length} accent="#6366f1" />
        <Kpi label="Notificados" value={notifiedCount} accent="#0ea5e9" />
        <Kpi label="Visualizados" value={viewedCount} accent="#10b981" />
        <Kpi label="Folha bruta" value={fmtBRL(totalGross)} accent="#f59e0b" />
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
                 data-testid="holerite-filter"
                 placeholder="Filtrar por colaborador..."
                 style={{ ...input(), paddingLeft: 30 }} />
        </div>
        <select value={month} onChange={(e) => setMonth(parseInt(e.target.value, 10))}
                data-testid="holerite-month" style={input(120)}>
          <option value={0}>Todo ano</option>
          {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
        </select>
        <select value={year} onChange={(e) => setYear(parseInt(e.target.value, 10))}
                data-testid="holerite-year" style={input(110)}>
          {[year, year - 1, year - 2].map((y) =>
            <option key={y} value={y}>{y}</option>)}
        </select>
      </div>

      {/* Lista */}
      <div className="surface" data-testid="holerite-list" style={{
        padding: 0, borderRadius: 10,
        border: "1px solid var(--border-default)",
        overflow: "hidden",
      }}>
        {loading ? (
          <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>
            Carregando...
          </div>
        ) : items.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center",
                          color: "var(--text-muted)", fontSize: 13 }}>
            <Receipt size={32} strokeWidth={1.25}
                     style={{ opacity: .4, marginBottom: 8 }} />
            <div style={{ fontWeight: 700, marginBottom: 4 }}>
              Nenhum holerite com esses filtros.
            </div>
            <div style={{ fontSize: 11 }}>
              Clique em <strong>Lançar holerite</strong> para começar.
            </div>
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "var(--bg-surface-2)" }}>
                <Th>Colaborador</Th>
                <Th>Competência</Th>
                <Th align="right">Bruto</Th>
                <Th align="right">Líquido</Th>
                <Th>Status</Th>
                <Th align="right">Ações</Th>
              </tr>
            </thead>
            <tbody>
              {items.map((h) => (
                <HoleriteRow key={h.id} h={h}
                              onReload={reload}
                              onShowAudit={() => setAuditOf(h)} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showUpload && (
        <UploadModal onClose={() => setShowUpload(false)}
                     onSubmit={reload} collabs={collabs} />
      )}
      {showAiImport && (
        <HoleriteAIImportModal
          onClose={() => setShowAiImport(false)}
          onSuccess={reload}
        />
      )}
      {auditOf && (
        <AuditModal doc={auditOf} onClose={() => setAuditOf(null)} />
      )}
    </div>
  );
}

/* =============================================================
   HoleriteRow — uma linha da tabela com botões de ação
============================================================= */
function HoleriteRow({ h, onReload, onShowAudit }) {
  const [busy, setBusy] = useState(false);
  const [lastLink, setLastLink] = useState(null);
  const [showAnomalies, setShowAnomalies] = useState(false);

  async function notify() {
    if (!h.employee_phone) {
      await window.alert("Este colaborador não tem WhatsApp cadastrado.");
      return;
    }
    setBusy(true);
    try {
      const r = await api.holeriteNotify(h.id, 72);
      if (r.ok) {
        setLastLink(r.secure_link);
      } else {
        // mesmo se WhatsApp falhar, mostra link pra envio manual
        setLastLink(r.secure_link);
        await window.alert("Link gerado, mas WhatsApp falhou:\n" + (r.error || "—") +
                         "\n\nVocê pode enviar manualmente.");
      }
      await onReload();
    } catch (e) {
      await window.alert(extractErr(e));
    } finally { setBusy(false); }
  }

  async function revoke() {
    if (!await window.confirm("Revogar este holerite? Links ativos ficarão inválidos.")) return;
    setBusy(true);
    try {
      await api.holeriteRevoke(h.id);
      await onReload();
    } catch (e) {
      await window.alert(extractErr(e));
    } finally { setBusy(false); }
  }

  async function deletePermanent() {
    if (!await window.confirm(
      "⚠️ APAGAR PERMANENTEMENTE este lançamento?\n\n" +
      "Esta ação não pode ser desfeita. O arquivo PDF original e qualquer " +
      "versão assinada serão removidos do servidor.\n\n" +
      "Use apenas quando o lançamento foi feito por engano."
    )) return;
    if (!await window.confirm("Tem CERTEZA? Esta ação é IRREVERSÍVEL.")) return;
    setBusy(true);
    try {
      await api.holeriteDeletePermanent(h.id);
      await onReload();
    } catch (e) {
      await window.alert(extractErr(e));
    } finally { setBusy(false); }
  }

  async function copyLink() {
    if (lastLink) {
      navigator.clipboard?.writeText(lastLink);
      await window.alert("✅ Link copiado.");
    }
  }

  const statusBadge = (() => {
    if (h.status === "revoked") return { color: "#dc2626", bg: "#fef2f2", text: "REVOGADO" };
    if (h.status === "pending_review") return { color: "#ea580c", bg: "#fff7ed", text: "🔒 AGUARDA RH" };
    if (h.viewed_at) return { color: "#10b981", bg: "#dcfce7", text: "VISTO" };
    if (h.notified_at) return { color: "#0ea5e9", bg: "#dbeafe", text: "ENVIADO" };
    return { color: "#64748b", bg: "var(--bg-surface-2)", text: "PENDENTE" };
  })();

  return (
    <tr style={{ borderTop: "1px solid var(--border-default)" }}
        data-testid={`holerite-row-${h.id}`}>
      <Td>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <UserIcon size={13} color="var(--text-muted)" />
          <strong>{h.employee_name || "—"}</strong>
        </div>
        {h.employee_phone && (
          <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
            📱 {h.employee_phone}
          </div>
        )}
      </Td>
      <Td>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Calendar size={12} color="var(--text-muted)" />
          {MONTHS[h.competence_month - 1]}/{h.competence_year}
        </div>
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
          {h.file_size_kb} KB
        </div>
      </Td>
      <Td align="right">{fmtBRL(h.gross)}</Td>
      <Td align="right"><strong>{fmtBRL(h.net)}</strong></Td>
      <Td>
        <span style={{
          padding: "2px 8px", borderRadius: 4, fontSize: 9, fontWeight: 800,
          background: statusBadge.bg, color: statusBadge.color,
          letterSpacing: ".05em",
        }}>{statusBadge.text}</span>
        {h.viewed_at && (
          <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
            👁 {new Date(h.viewed_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}
          </div>
        )}
        {(h.anomalies_count || 0) > 0 && (
          <button
            onClick={() => setShowAnomalies(true)}
            data-testid={`holerite-anomalies-${h.id}`}
            style={{
              marginTop: 4, padding: "2px 7px", borderRadius: 4,
              fontSize: 10, fontWeight: 800,
              border: "none", cursor: "pointer",
              background: h.anomalies_critical > 0 ? "#dc2626" : "#f59e0b",
              color: "white",
              display: "inline-flex", alignItems: "center", gap: 4,
            }}
            title="Ver anomalias detectadas"
          >
            <AlertTriangle size={10} />
            {h.anomalies_count} {h.anomalies_count === 1 ? "anomalia" : "anomalias"}
          </button>
        )}
      </Td>
      <Td align="right">
        {lastLink && (
          <button onClick={copyLink} style={{ ...btn("ghost", "xs"), marginRight: 4 }}>
            📋 Link
          </button>
        )}
        <button onClick={notify} disabled={busy || h.status === "revoked"}
                data-testid={`holerite-notify-${h.id}`}
                style={btn("primary", "xs", busy)} title="Enviar via WhatsApp">
          <MessageCircle size={11} /> Notificar
        </button>
        <button onClick={onShowAudit}
                data-testid={`holerite-audit-${h.id}`}
                style={{ ...btn("ghost", "xs"), marginLeft: 4 }}
                title="Auditoria">
          <History size={11} />
        </button>
        <button onClick={revoke} disabled={busy || h.status === "revoked"}
                data-testid={`holerite-revoke-${h.id}`}
                style={{ ...btn("ghost", "xs"), color: "#dc2626", marginLeft: 4 }}
                title="Revogar (soft delete)">
          <Ban size={11} />
        </button>
        <button onClick={deletePermanent} disabled={busy}
                data-testid={`holerite-delete-${h.id}`}
                style={{ ...btn("ghost", "xs"), color: "#991b1b", marginLeft: 2 }}
                title="Apagar permanentemente (com auditoria)">
          <Trash2 size={11} />
        </button>
      </Td>
      {showAnomalies && (
        <AnomaliesModal h={h} onClose={() => setShowAnomalies(false)} onReload={onReload} />
      )}
    </tr>
  );
}

function AnomaliesModal({ h, onClose, onReload }) {
  const anomalies = h.anomalies || [];
  const visible = anomalies.filter((a) => a.severity !== "info");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const isLocked = h.status === "pending_review";

  async function approve() {
    if (!await window.confirm(
      "Aprovar este holerite e liberar para o colaborador?\n\n" +
      "Você confirma que verificou as anomalias com o contador/RH e os valores estão corretos."
    )) return;
    setBusy(true);
    try {
      await api.holeriteApprove(h.id, note);
      await window.alert("✅ Holerite aprovado e liberado.");
      onReload?.();
      onClose();
    } catch (e) {
      await window.alert(extractErr(e));
    } finally { setBusy(false); }
  }

  async function reject() {
    if (!await window.confirm(
      "Rejeitar este holerite e marcar como REVOGADO?\n\n" +
      "Use quando o contador precisa corrigir o arquivo. Esta ação não pode ser desfeita por aqui."
    )) return;
    setBusy(true);
    try {
      await api.holeriteReject(h.id, note);
      await window.alert("Holerite rejeitado e revogado.");
      onReload?.();
      onClose();
    } catch (e) {
      await window.alert(extractErr(e));
    } finally { setBusy(false); }
  }

  return (
    <td colSpan={6}>
      <div onClick={onClose} style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
        zIndex: 200, display: "grid", placeItems: "center", padding: 20,
      }}>
        <div onClick={(e) => e.stopPropagation()}
              data-testid={`anomalies-modal-${h.id}`}
              style={{
                background: "var(--bg-surface)", borderRadius: 12,
                width: "min(680px, 96vw)", maxHeight: "90vh", overflow: "auto",
                padding: 18,
              }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
            marginBottom: 14, gap: 10 }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <AlertTriangle size={18}
                  color={h.anomalies_critical > 0 ? "#dc2626" : "#f59e0b"} />
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: "var(--text-primary)" }}>
                  Anomalias detectadas
                </h3>
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {h.employee_name} · {MONTHS[h.competence_month - 1]}/{h.competence_year}
                {" · Líquido "}<strong>{fmtBRL(h.net)}</strong>
              </div>
            </div>
            <button onClick={onClose} style={{ padding: 6, border: "none",
              background: "transparent", cursor: "pointer", color: "var(--text-muted)" }}>
              <X size={18} />
            </button>
          </div>

          {isLocked && (
            <div data-testid="lock-banner" style={{
              padding: 10, borderRadius: 8, marginBottom: 12,
              background: "linear-gradient(135deg, #fee2e2, #fef3c7)",
              border: "1px solid #dc2626",
              fontSize: 12.5, color: "#991b1b",
              display: "flex", alignItems: "flex-start", gap: 8,
            }}>
              <span style={{ fontSize: 16 }}>🔒</span>
              <div>
                <strong>Holerite bloqueado.</strong> O colaborador NÃO recebeu
                este holerite ainda. Anomalias críticas exigem aprovação manual
                do RH antes da liberação.
              </div>
            </div>
          )}

          {h.approved_at && (
            <div data-testid="approved-banner" style={{
              padding: 10, borderRadius: 8, marginBottom: 12,
              background: "rgba(22,163,74,.10)", color: "#15803d",
              fontSize: 12.5, borderLeft: "3px solid #16a34a",
            }}>
              ✓ Aprovado em {new Date(h.approved_at).toLocaleString("pt-BR")}
              {h.approved_by_name && ` por ${h.approved_by_name}`}
              {h.approval_note && (<><br/><em>"{h.approval_note}"</em></>)}
            </div>
          )}

          {visible.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
              Nenhuma anomalia significativa.
            </div>
          ) : (
            <div style={{ display: "grid", gap: 6, marginBottom: 14 }}>
              {visible.map((a, i) => <AnomalyChip key={i} a={a} />)}
            </div>
          )}

          {isLocked && (
            <div style={{ marginTop: 12, paddingTop: 14,
              borderTop: "1px solid var(--border-default)" }}>
              <label style={{
                display: "block", fontSize: 11, fontWeight: 800,
                color: "var(--text-muted)", marginBottom: 5,
                textTransform: "uppercase", letterSpacing: ".5px",
              }}>
                Nota do revisor (opcional)
              </label>
              <textarea
                value={note} onChange={(e) => setNote(e.target.value)}
                placeholder="Ex.: Confirmado com contador — foi falta justificada do dia 15."
                data-testid="reviewer-note"
                style={{
                  width: "100%", padding: 9, borderRadius: 7,
                  border: "1px solid var(--border-default)", fontSize: 12.5,
                  background: "var(--bg-surface)", color: "var(--text-primary)",
                  minHeight: 60, resize: "vertical", marginBottom: 10,
                }}
              />
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                <button onClick={reject} disabled={busy}
                        data-testid={`anomaly-reject-${h.id}`}
                        style={{ ...btn("secondary"), color: "#dc2626" }}>
                  <Ban size={13} /> Rejeitar e revogar
                </button>
                <button onClick={approve} disabled={busy}
                        data-testid={`anomaly-approve-${h.id}`}
                        style={{ ...btn("primary"),
                          background: "#16a34a", borderColor: "#16a34a" }}>
                  <Check size={13} /> Aprovar e liberar
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </td>
  );
}

/* =============================================================
   UploadModal — upload de PDF + metadados
============================================================= */
function UploadModal({ onClose, onSubmit, collabs }) {
  const today = new Date();
  const [collabId, setCollabId] = useState("");
  const [collabName, setCollabName] = useState("");
  const [collabPhone, setCollabPhone] = useState("");
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [year, setYear] = useState(today.getFullYear());
  const [gross, setGross] = useState("");
  const [net, setNet] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function pickCollab(e) {
    const id = e.target.value;
    setCollabId(id);
    const c = collabs.find((x) => (x.id || x._id) === id);
    if (c) {
      setCollabName(c.name || c.full_name || "");
      setCollabPhone(c.phone || c.whatsapp || c.cell || "");
    }
  }

  function handleFile(e) {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".pdf") && f.type !== "application/pdf") {
      setErr("Aceito apenas PDF.");
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      setErr("Limite: 10MB."); return;
    }
    setErr("");
    setFile(f);
  }

  async function submit() {
    setErr("");
    if (!collabName) { setErr("Informe o colaborador."); return; }
    if (!file) { setErr("Selecione o PDF."); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (collabId) fd.append("employee_id", collabId);
      fd.append("employee_name", collabName);
      if (collabPhone) fd.append("employee_phone", collabPhone);
      fd.append("competence_month", String(month));
      fd.append("competence_year", String(year));
      fd.append("gross", String(parseFloat(gross || "0") || 0));
      fd.append("net", String(parseFloat(net || "0") || 0));
      await api.holeriteUpload(fd);
      await onSubmit();
      onClose();
    } catch (e) {
      setErr(extractErr(e));
    } finally { setBusy(false); }
  }

  return (
    <Modal title="Lançar holerite" icon={Upload} onClose={onClose} testid="holerite-upload-modal">
      <div style={{ display: "grid", gap: 12 }}>
        <Lbl>Colaborador *</Lbl>
        {collabs.length > 0 ? (
          <select value={collabId} onChange={pickCollab}
                  data-testid="upload-collab" style={input()}>
            <option value="">— Selecione —</option>
            {collabs.map((c) => (
              <option key={c.id || c._id} value={c.id || c._id}>
                {c.name || c.full_name}
              </option>
            ))}
          </select>
        ) : (
          <input value={collabName} onChange={(e) => setCollabName(e.target.value)}
                 data-testid="upload-collab-name"
                 placeholder="Nome do colaborador" style={input()} />
        )}
        <Lbl>WhatsApp do colaborador (E.164)</Lbl>
        <input value={collabPhone} onChange={(e) => setCollabPhone(e.target.value)}
               data-testid="upload-collab-phone"
               placeholder="+5521999999999" style={input()} />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div>
            <Lbl>Mês *</Lbl>
            <select value={month} onChange={(e) => setMonth(parseInt(e.target.value, 10))}
                    data-testid="upload-month" style={input()}>
              {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
          </div>
          <div>
            <Lbl>Ano *</Lbl>
            <input type="number" value={year}
                   onChange={(e) => setYear(parseInt(e.target.value, 10))}
                   data-testid="upload-year" style={input()} />
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div>
            <Lbl>Valor bruto (R$)</Lbl>
            <input type="number" step="0.01" value={gross}
                   onChange={(e) => setGross(e.target.value)}
                   data-testid="upload-gross" style={input()}
                   placeholder="3500.00" />
          </div>
          <div>
            <Lbl>Valor líquido (R$)</Lbl>
            <input type="number" step="0.01" value={net}
                   onChange={(e) => setNet(e.target.value)}
                   data-testid="upload-net" style={input()}
                   placeholder="2890.50" />
          </div>
        </div>

        <Lbl>Arquivo PDF * (até 10MB)</Lbl>
        <input type="file" accept="application/pdf"
               onChange={handleFile}
               data-testid="upload-file" style={{ fontSize: 12 }} />
        {file && (
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            ✓ {file.name} · {(file.size / 1024).toFixed(0)} KB
          </div>
        )}

        {err && (
          <div data-testid="upload-error"
               style={{ background: "#fef2f2", color: "#991b1b", padding: 8,
                           borderRadius: 6, fontSize: 12, fontWeight: 700,
                           display: "flex", alignItems: "center", gap: 6 }}>
            <AlertCircle size={13} /> {err}
          </div>
        )}
      </div>
      <ModalFooter>
        <button onClick={onClose} style={btn("ghost")}>Cancelar</button>
        <button onClick={submit} disabled={busy}
                data-testid="upload-submit"
                style={btn("primary", "md", busy)}>
          <Upload size={13} /> {busy ? "Enviando..." : "Salvar holerite"}
        </button>
      </ModalFooter>
    </Modal>
  );
}

/* =============================================================
   AuditModal — exibe logs de um documento
============================================================= */
function AuditModal({ doc, onClose }) {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.holeriteAudit(doc.id).then((r) => setLogs(r.items || []))
      .catch(() => setLogs([]))
      .finally(() => setLoading(false));
  }, [doc.id]);

  return (
    <Modal title={`Auditoria — ${doc.employee_name}`} icon={History}
           onClose={onClose} testid="holerite-audit-modal" wide>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 10 }}>
        Competência {String(doc.competence_month).padStart(2, "0")}/{doc.competence_year}
      </div>
      {loading ? (
        <div style={{ padding: 30, textAlign: "center" }}>Carregando...</div>
      ) : logs.length === 0 ? (
        <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)",
                          fontSize: 12 }}>
          Sem registros ainda.
        </div>
      ) : (
        <div style={{ display: "grid", gap: 4, maxHeight: 380, overflowY: "auto" }}>
          {logs.map((l) => (
            <div key={l.id} style={{
              padding: "6px 8px", borderRadius: 6, fontSize: 11,
              background: l.result === "fail" ? "rgba(220,38,38,.07)" : "var(--bg-surface-2)",
              display: "grid", gridTemplateColumns: "120px 100px 80px 1fr",
              gap: 8, alignItems: "center",
            }}>
              <span style={{ fontFamily: "ui-monospace, monospace",
                              color: "var(--text-muted)" }}>
                {new Date(l.created_at).toLocaleString("pt-BR")}
              </span>
              <span style={{ fontWeight: 800,
                              color: l.result === "fail" ? "#dc2626" : "#6366f1" }}>
                {l.action}
              </span>
              <span style={{ fontSize: 9, color: "var(--text-muted)",
                              textTransform: "uppercase" }}>
                {l.actor_type}
              </span>
              <span style={{ color: "var(--text-muted)",
                              fontFamily: "ui-monospace, monospace", fontSize: 10 }}>
                {l.ip || "—"} · {(l.user_agent || "").slice(0, 40)}
              </span>
            </div>
          ))}
        </div>
      )}
      <ModalFooter>
        <button onClick={onClose} style={btn("ghost")}>Fechar</button>
      </ModalFooter>
    </Modal>
  );
}

/* =============================================================
   Utilitários visuais reutilizáveis
============================================================= */
function Modal({ title, icon: Icon, onClose, children, testid, wide }) {
  return (
    <div data-testid={testid} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
      display: "grid", placeItems: "center", zIndex: 1000,
    }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ width: wide ? 720 : 560, maxWidth: "94vw",
                       maxHeight: "92vh", overflowY: "auto",
                       borderRadius: 12, background: "var(--bg-surface)",
                       border: "1px solid var(--border-default)" }}>
        <div style={{ padding: "14px 20px",
                          borderBottom: "1px solid var(--border-default)",
                          display: "flex", alignItems: "center", gap: 10 }}>
          {Icon && <Icon size={18} color="#6366f1" />}
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800 }}>{title}</h3>
          <span style={{ flex: 1 }} />
          <button onClick={onClose} style={btn("ghost", "xs")}>
            <X size={14} />
          </button>
        </div>
        <div style={{ padding: 20 }}>{children}</div>
      </div>
    </div>
  );
}
function ModalFooter({ children }) {
  return (
    <div style={{ marginTop: 16, paddingTop: 12,
                       borderTop: "1px solid var(--border-default)",
                       display: "flex", gap: 8, justifyContent: "flex-end" }}>
      {children}
    </div>
  );
}
function Kpi({ label, value, accent }) {
  return (
    <div className="surface" style={{
      padding: 12, borderRadius: 10,
      border: "1px solid var(--border-default)",
      borderLeft: `3px solid ${accent}`,
      background: "var(--bg-surface)",
    }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: ".05em" }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 800, color: "var(--text-primary)",
                       marginTop: 4, letterSpacing: "-0.02em" }}>
        {value}
      </div>
    </div>
  );
}
function Th({ children, align = "left" }) {
  return <th style={{ padding: "10px 12px", textAlign: align, fontSize: 11,
                          fontWeight: 800, textTransform: "uppercase",
                          color: "var(--text-muted)", letterSpacing: ".05em" }}>
    {children}
  </th>;
}
function Td({ children, align = "left" }) {
  return <td style={{ padding: "10px 12px", textAlign: align,
                          fontSize: 13, color: "var(--text-primary)",
                          verticalAlign: "top" }}>
    {children}
  </td>;
}
function Lbl({ children }) {
  return <label style={{ fontSize: 11, fontWeight: 800,
                              color: "var(--text-muted)",
                              textTransform: "uppercase",
                              letterSpacing: ".05em" }}>{children}</label>;
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
function fmtBRL(v) {
  const n = Number(v || 0);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

/* =============================================================
   HoleriteAIImportModal — upload PDF do contador + parsing IA
============================================================= */
function HoleriteAIImportModal({ onClose, onSuccess }) {
  const [step, setStep] = useState("upload"); // upload | parsing | review | importing | done
  const [file, setFile] = useState(null);
  const [threshold, setThreshold] = useState(85);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [decisions, setDecisions] = useState({}); // {parsed_index: {employee_id, skip}}
  const [importResult, setImportResult] = useState(null);
  const [collabs, setCollabs] = useState([]);

  useEffect(() => {
    api.listCollaborators().then((d) => setCollabs(d.items || d || [])).catch(() => {});
  }, []);

  async function handleParse() {
    if (!file) { setError("Selecione um PDF primeiro."); return; }
    setError(""); setStep("parsing");
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("threshold", String(threshold));
      const { data } = await api._client.post("/holerites/ai-parse", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 180000,
      });
      setPreview(data);
      const d = {};
      (data.matches || []).forEach((m, i) => {
        d[i] = {
          employee_id: m.match?.id || null,
          skip: !m.match,
        };
      });
      setDecisions(d);
      setStep("review");
    } catch (e) {
      setError(extractErr(e));
      setStep("upload");
    }
  }

  async function handleImport() {
    if (!preview) return;
    setStep("importing"); setError("");
    try {
      const items = (preview.matches || []).map((m, i) => ({
        parsed_index: i,
        employee_id: decisions[i]?.employee_id || null,
        skip: !!decisions[i]?.skip,
      }));
      const { data } = await api._client.post("/holerites/ai-import", {
        parse_id: preview.parse_id,
        competence_month: preview.competence?.month || new Date().getMonth() + 1,
        competence_year: preview.competence?.year || new Date().getFullYear(),
        items,
      });
      setImportResult(data);
      setStep("done");
      onSuccess?.();
    } catch (e) {
      setError(extractErr(e));
      setStep("review");
    }
  }

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
                zIndex: 9999, display: "grid", placeItems: "center", padding: 20 }}
    >
      <div onClick={(e) => e.stopPropagation()}
            data-testid="ai-import-modal"
            style={{
              background: "var(--bg-surface)", borderRadius: 12,
              width: "min(1100px, 96vw)", maxHeight: "94vh", overflow: "hidden",
              display: "flex", flexDirection: "column",
            }}>
        <div style={{
          padding: 18,
          borderBottom: "1px solid var(--border-default)",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10,
              background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
              color: "white", display: "grid", placeItems: "center",
              boxShadow: "0 4px 14px rgba(139,92,246,.3)",
            }}>
              <Bot size={20} strokeWidth={1.75} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: "var(--text-primary)" }}>
                Holerite IA · Import do PDF do contador
              </h3>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                Claude Sonnet 4.5 extrai cada funcionário · faz match com cadastro · gera holerite digital
              </div>
            </div>
          </div>
          <button onClick={onClose} style={{ padding: 6, border: "none",
            background: "transparent", cursor: "pointer", color: "var(--text-muted)" }}>
            <X size={18} />
          </button>
        </div>

        <div style={{ padding: 18, overflow: "auto", flex: 1 }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 16, alignItems: "center" }}>
            <StepDot active={step === "upload"} done={["parsing","review","importing","done"].includes(step)} label="Upload" />
            <Arrow />
            <StepDot active={step === "parsing"} done={["review","importing","done"].includes(step)} label="Analisar com IA" />
            <Arrow />
            <StepDot active={step === "review"} done={["importing","done"].includes(step)} label="Revisar matches" />
            <Arrow />
            <StepDot active={step === "importing" || step === "done"} done={step === "done"} label="Importar" />
          </div>

          {error && (
            <div style={{
              padding: 10, borderRadius: 8, marginBottom: 14,
              background: "rgba(220,38,38,.10)", color: "#b91c1c",
              fontSize: 12.5, display: "flex", gap: 8, alignItems: "flex-start",
            }}>
              <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
              <div>{error}</div>
            </div>
          )}

          {step === "upload" && (
            <UploadStep file={file} setFile={setFile}
                          threshold={threshold} setThreshold={setThreshold}
                          onParse={handleParse} />
          )}
          {step === "parsing" && (
            <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
              <Loader2 size={32} className="spin"
                        style={{ color: "#8b5cf6", marginBottom: 12 }} />
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>
                Holerite IA analisando o PDF…
              </div>
              <div style={{ fontSize: 12, marginTop: 4 }}>
                Pode levar até 30-60 segundos. Identificando funcionários, valores e período.
              </div>
            </div>
          )}
          {step === "review" && preview && (
            <ReviewStep preview={preview} collabs={collabs}
                          decisions={decisions} setDecisions={setDecisions} />
          )}
          {step === "importing" && (
            <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
              <Loader2 size={32} className="spin"
                        style={{ color: "#8b5cf6", marginBottom: 12 }} />
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>
                Importando holerites no sistema…
              </div>
            </div>
          )}
          {step === "done" && importResult && (
            <DoneStep result={importResult} onClose={onClose} />
          )}
        </div>

        {step === "review" && (
          <div style={{
            padding: 14, borderTop: "1px solid var(--border-default)",
            display: "flex", justifyContent: "space-between", alignItems: "center",
            background: "var(--bg-surface-2)",
          }}>
            <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
              <strong>{Object.values(decisions).filter((d) => !d.skip && d.employee_id).length}</strong>
              {" "}de {preview?.matches?.length || 0} serão importados
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={() => setStep("upload")}
                      data-testid="ai-import-back"
                      style={btn("secondary")}>
                ← Trocar arquivo
              </button>
              <button onClick={handleImport}
                      data-testid="ai-import-confirm"
                      style={btn("primary")}>
                <Check size={14} /> Confirmar e importar
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function StepDot({ active, done, label }) {
  const color = done ? "#16a34a" : active ? "#8b5cf6" : "#cbd5e1";
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <div style={{
        width: 22, height: 22, borderRadius: 999,
        background: done || active ? color : "var(--bg-surface)",
        border: `2px solid ${color}`,
        display: "grid", placeItems: "center",
        color: done || active ? "white" : color, fontSize: 11, fontWeight: 800,
      }}>{done ? "✓" : ""}</div>
      <span style={{ fontSize: 11.5, fontWeight: 700,
        color: done || active ? "var(--text-primary)" : "var(--text-muted)" }}>
        {label}
      </span>
    </div>
  );
}
function Arrow() {
  return <span style={{ color: "var(--text-muted)", fontSize: 12 }}>→</span>;
}

function UploadStep({ file, setFile, threshold, setThreshold, onParse }) {
  return (
    <div>
      <div
        onDrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer.files?.[0];
          if (f && f.type === "application/pdf") setFile(f);
        }}
        onDragOver={(e) => e.preventDefault()}
        style={{
          border: "2px dashed var(--border-default)",
          borderRadius: 10, padding: 28, textAlign: "center",
          background: "var(--bg-surface-2)",
        }}
      >
        <Upload size={32} style={{ color: "#8b5cf6", marginBottom: 8 }} />
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>
          Solte o PDF do contador aqui
        </div>
        <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 4 }}>
          Pode conter 1 ou múltiplos funcionários. Máximo 10MB.
        </div>
        <input type="file" accept="application/pdf"
                data-testid="ai-import-file"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                style={{ marginTop: 14, fontSize: 12 }} />
        {file && (
          <div style={{ marginTop: 10, fontSize: 12, fontWeight: 700,
            color: "#16a34a", display: "inline-flex", alignItems: "center", gap: 5 }}>
            <FileText size={14} /> {file.name} · {(file.size / 1024).toFixed(0)}KB
          </div>
        )}
      </div>

      <div style={{ marginTop: 16, padding: 12, borderRadius: 8,
        background: "rgba(139,92,246,.06)",
        border: "1px solid rgba(139,92,246,.18)" }}>
        <label style={{ fontSize: 11, fontWeight: 700, color: "#6d28d9",
          textTransform: "uppercase", letterSpacing: ".5px",
          display: "block", marginBottom: 6 }}>
          Threshold de match de nomes
        </label>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <input type="range" min="50" max="100" step="1"
                  value={threshold}
                  data-testid="ai-import-threshold"
                  onChange={(e) => setThreshold(parseInt(e.target.value, 10))}
                  style={{ flex: 1, accentColor: "#8b5cf6" }} />
          <span style={{ minWidth: 50, textAlign: "right",
            fontSize: 14, fontWeight: 800, color: "#6d28d9" }}>{threshold}%</span>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 5 }}>
          {threshold >= 90 ? "Rigoroso — só matches quase exatos." :
            threshold >= 75 ? "Equilibrado — recomendado." :
              "Permissivo — pode haver falsos positivos."}
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
        <button onClick={onParse}
                data-testid="ai-import-parse"
                disabled={!file}
                style={btn("primary", "md", !file)}>
          <Sparkles size={14} /> Analisar com Holerite IA
        </button>
      </div>
    </div>
  );
}

function ReviewStep({ preview, collabs, decisions, setDecisions }) {
  const stats = preview.stats || {};
  return (
    <div>
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
        gap: 8, marginBottom: 16,
      }}>
        <MiniKpi label="Identificados" value={stats.parsed_count} color="#0f172a" />
        <MiniKpi label="Match auto" value={stats.matched_count} color="#16a34a" />
        <MiniKpi label="Não encontrados" value={stats.unmatched_count} color="#ef4444" />
        <MiniKpi label="Bruto total" value={fmtBRL(stats.total_gross)} color="#f59e0b" />
        <MiniKpi label="Líquido total" value={fmtBRL(stats.total_net)} color="#0ea5e9" />
      </div>

      <div style={{
        padding: 10, borderRadius: 8, marginBottom: 14,
        background: "var(--bg-surface-2)",
        fontSize: 12, color: "var(--text-secondary)",
      }}>
        <strong>Competência:</strong> {String(preview.competence?.month || "?").padStart(2, "0")}/{preview.competence?.year || "?"}
        {" · "}<strong>Empresa:</strong> {preview.company?.name || "—"}
        {preview.company?.cnpj && (<> · CNPJ {preview.company.cnpj}</>)}
      </div>

      <div data-testid="ai-import-matches" style={{ display: "grid", gap: 8, maxHeight: 380, overflow: "auto" }}>
        {(preview.matches || []).map((m, i) => (
          <MatchRow key={i} index={i} m={m} collabs={collabs}
                      decision={decisions[i] || {}}
                      onChange={(d) => setDecisions({ ...decisions, [i]: d })} />
        ))}
      </div>
    </div>
  );
}

function MatchRow({ index, m, collabs, decision, onChange }) {
  const p = m.parsed || {};
  const status = m.match_status;
  const statusColor = {
    cpf_exact: "#16a34a",
    name_high: "#0ea5e9",
    name_medium: "#f59e0b",
    no_match: "#dc2626",
  }[status] || "#64748b";
  const statusLabel = {
    cpf_exact: "CPF exato",
    name_high: "Nome (alta)",
    name_medium: "Nome (média)",
    no_match: "Sem match",
  }[status] || status;

  return (
    <div data-testid={`ai-match-${index}`} style={{
      padding: 12, borderRadius: 8,
      border: `1px solid ${decision.skip ? "rgba(220,38,38,.4)" : "var(--border-default)"}`,
      background: decision.skip ? "rgba(220,38,38,.04)" : "var(--bg-surface)",
      display: "grid", gridTemplateColumns: "auto 1fr auto 1fr auto", gap: 12,
      alignItems: "center", opacity: decision.skip ? 0.65 : 1,
    }}>
      <div style={{
        width: 30, height: 30, borderRadius: 8,
        background: statusColor + "22", color: statusColor,
        display: "grid", placeItems: "center", fontSize: 12, fontWeight: 900,
      }}>#{index + 1}</div>

      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
          {p.full_name}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
          {p.cpf && <>CPF {p.cpf} · </>}
          Bruto <strong>{fmtBRL(p.gross)}</strong> · Líquido <strong>{fmtBRL(p.net)}</strong>
        </div>
      </div>

      <div style={{ textAlign: "center" }}>
        <span style={{
          padding: "3px 8px", borderRadius: 4,
          background: statusColor + "22", color: statusColor,
          fontSize: 10.5, fontWeight: 800, textTransform: "uppercase",
        }}>{statusLabel}</span>
        {m.match_score > 0 && (
          <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 2 }}>
            {Math.round(m.match_score)}%
          </div>
        )}
      </div>

      <div>
        <select
          value={decision.employee_id || ""}
          data-testid={`ai-match-select-${index}`}
          disabled={decision.skip}
          onChange={(e) => onChange({ ...decision, employee_id: e.target.value || null })}
          style={input()}
        >
          <option value="">— Selecionar colaborador —</option>
          {collabs.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        {decision.employee_id !== (m.match?.id || null) && decision.employee_id && (
          <div style={{ fontSize: 10, color: "#f59e0b", marginTop: 3 }}>
            ⚠️ Match alterado manualmente
          </div>
        )}
      </div>

      <label style={{
        display: "inline-flex", alignItems: "center", gap: 5,
        cursor: "pointer", fontSize: 11, fontWeight: 700,
        color: decision.skip ? "#dc2626" : "var(--text-muted)",
      }}>
        <input type="checkbox" checked={!!decision.skip}
                data-testid={`ai-match-skip-${index}`}
                onChange={(e) => onChange({ ...decision, skip: e.target.checked })}
                style={{ accentColor: "#dc2626" }} />
        Ignorar
      </label>
    </div>
  );
}

function MiniKpi({ label, value, color }) {
  return (
    <div style={{
      padding: 10, borderRadius: 8,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
    }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
        fontWeight: 700, textTransform: "uppercase", letterSpacing: ".4px" }}>
        {label}
      </div>
      <div style={{ fontSize: 16, fontWeight: 900, color, marginTop: 2 }}>
        {value}
      </div>
    </div>
  );
}

function DoneStep({ result, onClose }) {
  const totalAnomalies = (result.items || []).reduce(
    (sum, it) => sum + (it.anomalies_count || 0), 0,
  );
  const criticalAnomalies = (result.items || []).reduce(
    (sum, it) => sum + (it.anomalies_critical || 0), 0,
  );
  return (
    <div data-testid="ai-import-done" style={{ padding: 24 }}>
      <div style={{ textAlign: "center", marginBottom: 18 }}>
        <div style={{
          width: 60, height: 60, borderRadius: "50%",
          background: "rgba(22,163,74,.15)", color: "#16a34a",
          display: "inline-grid", placeItems: "center", marginBottom: 12,
        }}>
          <CheckCircle2 size={32} />
        </div>
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: "var(--text-primary)" }}>
          Import concluído!
        </h3>
        <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 6 }}>
          <strong>{result.imported}</strong> holerites importados ·
          {" "}<strong>{result.skipped}</strong> ignorados.
        </div>
      </div>

      {totalAnomalies > 0 && (
        <div data-testid="ai-import-anomalies-summary" style={{
          padding: 14, borderRadius: 10, marginBottom: 16,
          background: criticalAnomalies > 0
            ? "linear-gradient(135deg, #fee2e2, #fef3c7)"
            : "rgba(245,158,11,.08)",
          border: `1px solid ${criticalAnomalies > 0 ? "#dc2626" : "#f59e0b"}`,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <AlertTriangle size={18} color={criticalAnomalies > 0 ? "#dc2626" : "#f59e0b"} />
            <strong style={{ fontSize: 14, color: criticalAnomalies > 0 ? "#991b1b" : "#92400e" }}>
              ⚠️ {totalAnomalies} {totalAnomalies === 1 ? "anomalia detectada" : "anomalias detectadas"}
              {criticalAnomalies > 0 && (
                <span style={{ marginLeft: 8, padding: "1px 8px",
                  borderRadius: 999, background: "#dc2626", color: "white",
                  fontSize: 11, fontWeight: 800 }}>
                  {criticalAnomalies} crítica{criticalAnomalies > 1 ? "s" : ""}
                </span>
              )}
            </strong>
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {(result.items || []).filter((it) => (it.anomalies_count || 0) > 0)
              .map((it) => (
                <div key={it.id} style={{
                  padding: 10, borderRadius: 8, background: "white",
                  border: "1px solid var(--border-default)",
                }}>
                  <div style={{ fontWeight: 800, fontSize: 12.5, marginBottom: 6, color: "#0f172a" }}>
                    {it.employee_name} · {String(it.competence_month).padStart(2,"0")}/{it.competence_year}
                  </div>
                  <div style={{ display: "grid", gap: 4 }}>
                    {(it.anomalies || []).filter((a) => a.severity !== "info").map((a, i) => (
                      <AnomalyChip key={i} a={a} />
                    ))}
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      <div style={{ textAlign: "center" }}>
        <button onClick={onClose}
                data-testid="ai-import-close"
                style={btn("primary")}>
          Fechar
        </button>
      </div>
    </div>
  );
}

function AnomalyChip({ a }) {
  const colors = {
    critical: { bg: "rgba(220,38,38,.10)", color: "#991b1b", border: "#dc2626" },
    warning: { bg: "rgba(245,158,11,.10)", color: "#92400e", border: "#f59e0b" },
    info: { bg: "rgba(14,165,233,.08)", color: "#075985", border: "#0ea5e9" },
  };
  const c = colors[a.severity] || colors.info;
  return (
    <div style={{
      padding: "6px 10px", borderRadius: 6, fontSize: 11.5,
      background: c.bg, color: c.color,
      borderLeft: `3px solid ${c.border}`,
      display: "flex", alignItems: "flex-start", gap: 6,
    }}>
      <span style={{
        padding: "1px 6px", borderRadius: 4, fontSize: 9.5, fontWeight: 800,
        background: c.border, color: "white", textTransform: "uppercase",
        letterSpacing: ".4px", flexShrink: 0,
      }}>{a.kind.replace(/_/g, " ")}</span>
      <span>{a.message}</span>
    </div>
  );
}

function extractErr(e) {
  const d = e?.response?.data?.detail ?? e?.response?.data ?? e?.message;
  if (!d) return "Erro desconhecido.";
  if (typeof d === "string") return d;
  return JSON.stringify(d);
}
