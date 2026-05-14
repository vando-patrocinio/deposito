import React, { useCallback, useEffect, useState } from "react";
import {
  Receipt, Upload, Search, Calendar, User as UserIcon, Shield, MessageCircle,
  Eye, Ban, History, FileText, AlertCircle, CheckCircle2, RefreshCw, X,
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

  async function notify() {
    if (!h.employee_phone) {
      window.alert("Este colaborador não tem WhatsApp cadastrado.");
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
        window.alert("Link gerado, mas WhatsApp falhou:\n" + (r.error || "—") +
                         "\n\nVocê pode enviar manualmente.");
      }
      await onReload();
    } catch (e) {
      window.alert(extractErr(e));
    } finally { setBusy(false); }
  }

  async function revoke() {
    if (!window.confirm("Revogar este holerite? Links ativos ficarão inválidos.")) return;
    setBusy(true);
    try {
      await api.holeriteRevoke(h.id);
      await onReload();
    } catch (e) {
      window.alert(extractErr(e));
    } finally { setBusy(false); }
  }

  function copyLink() {
    if (lastLink) {
      navigator.clipboard?.writeText(lastLink);
      window.alert("✅ Link copiado.");
    }
  }

  const statusBadge = (() => {
    if (h.status === "revoked") return { color: "#dc2626", bg: "#fef2f2", text: "REVOGADO" };
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
                title="Revogar">
          <Ban size={11} />
        </button>
      </Td>
    </tr>
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
function extractErr(e) {
  const d = e?.response?.data?.detail ?? e?.response?.data ?? e?.message;
  if (!d) return "Erro desconhecido.";
  if (typeof d === "string") return d;
  return JSON.stringify(d);
}
