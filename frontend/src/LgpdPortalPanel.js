/* LgpdPortalPanel.js — Sprint 5 / iter224
   Portal LGPD: gerar dossiê de titular em 8 segundos com prova
   criptográfica de integridade. */
import React, { useEffect, useState } from "react";
import { api, API } from "@/api";
import {
  AlertTriangle, FileText, ShieldCheck, Search, Download, RefreshCw,
  CheckCircle2, XCircle,
} from "lucide-react";

const ORACLE = {
  bg: "#0b1220", panel: "#101a2e", card: "#152238",
  ink: "#e2e8f0", muted: "#94a3b8",
  purple: "#4b1d7a", orange: "#f28c28",
  green: "#22c55e", red: "#ef4444", amber: "#f59e0b",
  blue: "#3b82f6", border: "#1e293b",
};

export default function LgpdPortalPanel() {
  const [chain, setChain] = useState(null);
  const [subjectId, setSubjectId] = useState("");
  const [email, setEmail] = useState("");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [err, setErr] = useState("");

  const reloadChain = async () => {
    try {
      const r = await api._client.get(
        "/audit-log/lgpd/verify-chain?limit=5000");
      setChain(r.data);
    } catch { setChain(null); }
  };

  useEffect(() => { reloadChain(); }, []);

  const runReport = async (e) => {
    e?.preventDefault?.();
    if (!subjectId.trim()) return;
    setLoading(true); setErr(""); setReport(null);
    try {
      const r = await api._client.get(
        "/audit-log/lgpd/subject-report", {
          params: { subject_id: subjectId.trim(),
                    email: email.trim() || undefined, limit: 2000 },
        });
      setReport(r.data);
    } catch (e2) {
      setErr(e2?.response?.data?.detail || e2?.message
             || "Erro ao gerar relatório");
    } finally { setLoading(false); }
  };

  const downloadPdf = async () => {
    if (!subjectId.trim()) return;
    setDownloading(true);
    try {
      const token = window.localStorage.getItem("ponto_token") || "";
      const qs = new URLSearchParams({
        subject_id: subjectId.trim(),
        ...(email.trim() ? { email: email.trim() } : {}),
      }).toString();
      const resp = await fetch(
        `${API}/audit-log/lgpd/subject-report.pdf?${qs}`,
        { headers: { Authorization: `Bearer ${token}` } });
      if (!resp.ok) {
        const t = await resp.text();
        throw new Error(`status=${resp.status} ${t.slice(0, 120)}`);
      }
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `dossie-lgpd-${subjectId}.pdf`;
      a.click();
    } catch (e2) {
      setErr(e2?.message || "Falha ao baixar PDF");
    } finally { setDownloading(false); }
  };

  const chainOk = chain && chain.status === "ok";

  return (
    <div data-testid="lgpd-portal" style={{
      background: ORACLE.bg, color: ORACLE.ink, minHeight: "100vh",
      padding: 24,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        marginBottom: 6,
      }}>
        <ShieldCheck size={28} color={chainOk ? ORACLE.green : ORACLE.amber} />
        <h1 style={{
          margin: 0, fontSize: 22, fontWeight: 800, letterSpacing: -0.5,
        }} data-testid="lgpd-portal-title">
          LGPD Portal — Dossiê do Titular
        </h1>
      </div>
      <div style={{
        fontSize: 13, color: ORACLE.muted, marginBottom: 20,
      }}>
        Resposta a direito do titular (art. 18) em segundos, com prova
        criptográfica de integridade por hash-chain SHA-256.
      </div>

      {/* Selo da cadeia */}
      <div data-testid="chain-status-card" style={{
        background: ORACLE.panel,
        border: `1px solid ${chainOk ? ORACLE.green : ORACLE.amber}`,
        borderRadius: 12, padding: 14, marginBottom: 24,
        display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
      }}>
        {chainOk ? <CheckCircle2 size={28} color={ORACLE.green} />
                 : <AlertTriangle size={28} color={ORACLE.amber} />}
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 800 }}>
            {chain ? (chainOk
              ? "Audit Trail íntegro — hash-chain verificada"
              : "Adulteração detectada — investigar imediatamente")
              : "Verificando cadeia..."}
          </div>
          <div style={{ fontSize: 12, color: ORACLE.muted, marginTop: 2 }}>
            {chain ? `${chain.checked} eventos · ${chain.broken_count} `
              + `breaks · gerado ${fmtDate(chain.verified_at)}`
              : "—"}
          </div>
        </div>
        <button onClick={reloadChain} data-testid="chain-refresh"
          style={btnStyle(ORACLE.blue)}>
          <RefreshCw size={14} /> Recomputar
        </button>
      </div>

      {/* Formulário */}
      <form onSubmit={runReport} data-testid="lgpd-form" style={{
        background: ORACLE.panel, padding: 18, borderRadius: 12,
        marginBottom: 16,
      }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>
          Identificação do titular
        </div>
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 12, alignItems: "flex-end",
        }}>
          <Field label="ID do titular (CPF, user_id, etc.)" required>
            <input data-testid="lgpd-subject-id"
              value={subjectId}
              onChange={(e) => setSubjectId(e.target.value)}
              placeholder="ex: 12345678901"
              style={inputStyle} />
          </Field>
          <Field label="E-mail (opcional, melhora a busca)">
            <input data-testid="lgpd-email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="titular@exemplo.com"
              style={inputStyle} />
          </Field>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="submit" data-testid="lgpd-run"
              disabled={loading || !subjectId.trim()}
              style={btnStyle(ORACLE.purple)}>
              <Search size={14} />
              {loading ? "Buscando..." : "Buscar eventos"}
            </button>
            <button type="button" onClick={downloadPdf}
              disabled={downloading || !subjectId.trim()}
              data-testid="lgpd-download-pdf"
              style={btnStyle(ORACLE.green)}>
              <Download size={14} />
              {downloading ? "Gerando..." : "Baixar dossiê (PDF)"}
            </button>
          </div>
        </div>
      </form>

      {err && (
        <div data-testid="lgpd-error" style={{
          background: "#7f1d1d", color: "#fee", padding: 12,
          borderRadius: 8, marginBottom: 16, fontSize: 13,
        }}>⚠ {err}</div>
      )}

      {/* Resultado */}
      {report && (
        <div data-testid="lgpd-result">
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 12, marginBottom: 16,
          }}>
            <ResultCard icon={<FileText size={18} />} label="Total de eventos"
              value={report.total_events} color={ORACLE.purple}
              testid="result-total" />
            {Object.entries(report.by_category || {}).map(([k, v]) => (
              <ResultCard key={k}
                icon={<FileText size={18} />}
                label={k}
                value={v}
                color={ORACLE.blue}
                testid={`result-cat-${k}`} />
            ))}
          </div>

          <div style={{
            background: ORACLE.panel, borderRadius: 8,
            overflow: "auto", border: `1px solid ${ORACLE.border}`,
          }}>
            <table style={{
              width: "100%", borderCollapse: "collapse", fontSize: 12,
              minWidth: 800,
            }} data-testid="lgpd-events-table">
              <thead>
                <tr style={{ background: ORACLE.card,
                              color: ORACLE.muted }}>
                  <Th>Quando</Th><Th>Categoria</Th><Th>Ação</Th>
                  <Th>Executor</Th><Th>Status</Th><Th>Hash</Th>
                </tr>
              </thead>
              <tbody>
                {report.events.length === 0 && (
                  <tr><td colSpan={6} style={{
                    padding: 24, textAlign: "center",
                    color: ORACLE.muted,
                  }}>Nenhum evento encontrado para este titular.</td></tr>
                )}
                {report.events.slice(0, 200).map((ev) => (
                  <tr key={ev.id} style={{
                    borderTop: `1px solid ${ORACLE.border}`,
                  }}>
                    <Td>{fmtDate(ev.created_at)}</Td>
                    <Td>{ev.category}</Td>
                    <Td><code style={{ fontSize: 11 }}>
                      {(ev.action || "").slice(0, 60)}
                    </code></Td>
                    <Td>{ev.actor_email || ev.actor_role || "—"}</Td>
                    <Td>{ev.status ?? "—"}</Td>
                    <Td><code style={{
                      fontSize: 10, color: ORACLE.muted,
                    }}>{ev.hash || "—"}</code></Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{
            marginTop: 14, padding: 12,
            background: ORACLE.panel, borderRadius: 8,
            fontSize: 11, color: ORACLE.muted, lineHeight: 1.5,
          }}>
            <b>Base legal:</b> {report.lgpd_basis}<br/>
            <b>Gerado em:</b> {report.generated_at}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, required, children }) {
  return (
    <div>
      <div style={{
        fontSize: 11, fontWeight: 700, color: ORACLE.muted,
        textTransform: "uppercase", marginBottom: 4, letterSpacing: 0.5,
      }}>{label}{required ? " *" : ""}</div>
      {children}
    </div>
  );
}

function ResultCard({ icon, label, value, color, testid }) {
  return (
    <div data-testid={testid} style={{
      background: ORACLE.panel, padding: 14, borderRadius: 10,
      borderLeft: `4px solid ${color}`,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        color: ORACLE.muted, fontSize: 11, fontWeight: 700,
        textTransform: "uppercase",
      }}>
        <span style={{ color }}>{icon}</span>{label}
      </div>
      <div style={{
        marginTop: 6, fontSize: 24, fontWeight: 800,
      }}>{value ?? "—"}</div>
    </div>
  );
}

function Th({ children }) {
  return <th style={{
    padding: "10px 12px", textAlign: "left", fontWeight: 700,
    fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5,
  }}>{children}</th>;
}

function Td({ children }) {
  return <td style={{
    padding: "8px 12px", color: ORACLE.ink,
  }}>{children}</td>;
}

const inputStyle = {
  width: "100%", background: ORACLE.card, color: ORACLE.ink,
  border: `1px solid ${ORACLE.border}`, padding: "8px 10px",
  borderRadius: 6, fontSize: 13, outline: "none",
};

const btnStyle = (bg) => ({
  background: bg, color: "#fff", border: 0,
  padding: "8px 14px", borderRadius: 6, cursor: "pointer",
  fontSize: 12, fontWeight: 700, display: "inline-flex",
  alignItems: "center", gap: 6,
});

function fmtDate(s) {
  if (!s) return "—";
  try {
    const d = new Date(s);
    return d.toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return s; }
}
