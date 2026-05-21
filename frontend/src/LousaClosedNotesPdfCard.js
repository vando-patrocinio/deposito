/*
LousaClosedNotesPdfCard.js — Card para exportar relatório PDF de
fechamento de notas (Lousa) por período.

Períodos: Hoje · Ontem · 7 dias · Custom (start/end).
*/
import React, { useState } from "react";
import { api } from "@/api";

const PERIODS = [
  { id: "today",     label: "Hoje" },
  { id: "yesterday", label: "Ontem" },
  { id: "week",      label: "7 dias" },
  { id: "custom",    label: "Período personalizado" },
];

function todayIso() { return new Date().toISOString().slice(0, 10); }
function aWeekAgoIso() {
  const d = new Date(); d.setDate(d.getDate() - 7);
  return d.toISOString().slice(0, 10);
}

export default function LousaClosedNotesPdfCard() {
  const [period, setPeriod] = useState("today");
  const [start, setStart] = useState(aWeekAgoIso());
  const [end, setEnd] = useState(todayIso());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const download = async () => {
    setErr(""); setBusy(true);
    try {
      const params = new URLSearchParams({ period });
      if (period === "custom") {
        params.set("start", start);
        params.set("end", end);
      }
      const r = await api._client.get(
        `/lousa/tickets/closed/pdf?${params.toString()}`,
        { responseType: "blob" },
      );
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `fechamento_notas_${period}_${todayIso()}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao gerar PDF");
    } finally { setBusy(false); }
  };

  return (
    <div data-testid="lousa-pdf-card" style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                       marginBottom: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 18 }}>📄</span>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>
            Relatório PDF · Fechamento de Notas
          </div>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
            Gera um PDF com as notas fechadas no período escolhido,
            agrupadas por tipo e técnico.
          </div>
        </div>
      </div>

      {/* Chips de período */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6,
                       marginBottom: 10 }}>
        {PERIODS.map((p) => {
          const active = period === p.id;
          return (
            <button key={p.id} data-testid={`pdf-period-${p.id}`}
                      onClick={() => setPeriod(p.id)}
                      style={{
                        padding: "7px 12px", borderRadius: 999,
                        border: active ? "1.5px solid #0f172a" : "1px solid #e2e8f0",
                        background: active ? "#f1f5f9" : "#fff",
                        color: "#0f172a", fontSize: 12, fontWeight: 700,
                        cursor: "pointer",
                      }}>
              {p.label}
            </button>
          );
        })}
      </div>

      {/* Inputs de data quando custom */}
      {period === "custom" && (
        <div style={{ display: "flex", gap: 8, marginBottom: 10,
                          flexWrap: "wrap" }}>
          <label style={{ flex: 1, minWidth: 140 }}>
            <div style={lbl}>De</div>
            <input data-testid="pdf-start" type="date"
                    value={start} max={end}
                    onChange={(e) => setStart(e.target.value)}
                    style={input} />
          </label>
          <label style={{ flex: 1, minWidth: 140 }}>
            <div style={lbl}>Até</div>
            <input data-testid="pdf-end" type="date"
                    value={end} min={start} max={todayIso()}
                    onChange={(e) => setEnd(e.target.value)}
                    style={input} />
          </label>
        </div>
      )}

      {err && (
        <div style={{ padding: 8, marginBottom: 8, borderRadius: 6,
                          background: "#fee2e2", color: "#991b1b",
                          fontSize: 12 }}>
          {err}
        </div>
      )}

      <button onClick={download} disabled={busy}
                data-testid="pdf-download-btn"
                style={{
                  padding: "10px 16px", border: 0, borderRadius: 8,
                  background: busy ? "#94a3b8" : "#0f172a",
                  color: "#fff", fontWeight: 700, fontSize: 13,
                  cursor: busy ? "wait" : "pointer", width: "100%",
                }}>
        {busy ? "Gerando PDF..." : "📥 Baixar PDF"}
      </button>
    </div>
  );
}

const card = {
  background: "#fff", borderRadius: 12, padding: 14,
  border: "1px solid #e2e8f0",
};
const lbl = {
  fontSize: 10, fontWeight: 800, color: "#475569",
  textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4,
};
const input = {
  width: "100%", padding: "8px 10px", borderRadius: 6,
  border: "1px solid #cbd5e1", fontSize: 13,
  fontFamily: "inherit", boxSizing: "border-box",
};
