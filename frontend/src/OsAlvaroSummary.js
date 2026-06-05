/*
OsAlvaroSummary.js — iter211ay

Card que aparece logo abaixo do "📝 Relato" da OS, mostrando o resumo
gerado pelo agente Álvaro IA:
  • Entendimento (frase curta)
  • Procedimentos já feitos
  • Testes realizados

Backend: GET /api/alvaro/os-summary/{ticket_id}
Cacheado por 6h. Primeira abertura: ~3s gerando. Próximas: instantâneo.
*/
import React, { useEffect, useState } from "react";
import { api } from "@/api";

export default function OsAlvaroSummary({ ticketId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let alive = true;
    if (!ticketId) return undefined;
    setLoading(true); setErr("");
    api._client.get(`/alvaro/os-summary/${ticketId}`)
      .then((r) => { if (alive) { setData(r.data); setLoading(false); } })
      .catch((e) => {
        if (alive) {
          setErr(e?.response?.data?.detail || e.message);
          setLoading(false);
        }
      });
    return () => { alive = false; };
  }, [ticketId]);

  if (loading) {
    return (
      <div data-testid="os-alvaro-loading"
            style={{ ...wrapStyle, color: "#475569", fontStyle: "italic" }}>
        <span style={titleStyle}>🤖 Álvaro analisando atendimento…</span>
      </div>
    );
  }
  if (err) {
    // Silencioso: não polui se IA estiver indisponível
    return null;
  }
  if (!data) return null;

  const hasProc = (data.procedimentos || []).length > 0;
  const hasTests = (data.testes || []).length > 0;
  const understanding = (data.entendimento || "").trim();
  if (!understanding && !hasProc && !hasTests) return null;

  return (
    <div data-testid="os-alvaro-summary" style={wrapStyle}>
      <button type="button"
              onClick={() => setExpanded((v) => !v)}
              style={headerBtnStyle}>
        <span style={titleStyle}>🤖 Álvaro entendeu</span>
        <span style={{ fontSize: 10, color: "#64748b" }}>
          {expanded ? "▲ ocultar" : "▼ ver detalhes"}
        </span>
      </button>

      {understanding && (
        <div style={{ fontSize: 12.5, color: "#334155", lineHeight: 1.45,
                        marginTop: 4 }}>
          {understanding}
        </div>
      )}

      {expanded && (hasProc || hasTests) && (
        <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
          {hasProc && (
            <div>
              <div style={subTitleStyle}>Procedimentos feitos</div>
              <ul style={listStyle}>
                {data.procedimentos.map((p, i) => (
                  <li key={`proc-${i}`} style={liStyle}>{p}</li>
                ))}
              </ul>
            </div>
          )}
          {hasTests && (
            <div>
              <div style={subTitleStyle}>Testes realizados</div>
              <ul style={listStyle}>
                {data.testes.map((t, i) => (
                  <li key={`test-${i}`} style={liStyle}>{t}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const wrapStyle = {
  marginTop: 6, padding: "10px 12px", borderRadius: 12,
  background: "linear-gradient(135deg,#fff7ed,#fef3c7)",
  border: "1px solid #fde68a",
  fontSize: 13, lineHeight: 1.45,
};
const headerBtnStyle = {
  width: "100%", display: "flex", alignItems: "center",
  justifyContent: "space-between",
  background: "transparent", border: 0, padding: 0,
  fontFamily: "inherit", cursor: "pointer",
};
const titleStyle = {
  fontSize: 11, fontWeight: 800, color: "#9a3412",
  letterSpacing: 0.5, textTransform: "uppercase",
};
const subTitleStyle = {
  fontSize: 10, fontWeight: 800, color: "#7c2d12",
  textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 2,
};
const listStyle = {
  margin: 0, paddingLeft: 18, color: "#334155",
};
const liStyle = {
  fontSize: 12, lineHeight: 1.4, marginBottom: 2,
};
