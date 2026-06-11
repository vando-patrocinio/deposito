/**
 * LousaSalaTab — Aba "SALA" do painel admin.
 * Bolhas agendadas pela Isabella ficam aqui antes de serem distribuídas
 * para um técnico real.
 *
 * Backend: GET /api/lousa/sala, GET /api/lousa/sala/dias,
 *          POST /api/lousa/sala/{id}/distribuir
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";

const API = process.env.REACT_APP_BACKEND_URL;

function authHeaders() {
  const t = (typeof window !== "undefined")
    ? window.localStorage.getItem("ponto_token") : null;
  return t ? { Authorization: `Bearer ${t}` } : {};
}

function formatBRDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

function todayBRIso() {
  const now = new Date();
  // BR = UTC-3
  const br = new Date(now.getTime() - (3 * 60 * 60 * 1000));
  return br.toISOString().slice(0, 10);
}

export default function LousaSalaTab() {
  const [date, setDate] = useState(todayBRIso());
  const [data, setData] = useState({ tickets: [], by_window: {} });
  const [days, setDays] = useState([]);
  const [collabs, setCollabs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [distributing, setDistributing] = useState(null); // ticket_id
  const [pickerFor, setPickerFor] = useState(null);
  const [pickerValue, setPickerValue] = useState("");

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2, r3] = await Promise.all([
        fetch(`${API}/api/lousa/sala?date=${date}`, { headers: authHeaders() }),
        fetch(`${API}/api/lousa/sala/dias`, { headers: authHeaders() }),
        fetch(`${API}/api/collaborators`, { headers: authHeaders() }),
      ]);
      if (r1.ok) setData(await r1.json());
      if (r2.ok) {
        const j = await r2.json();
        setDays(j.days || []);
      }
      if (r3.ok) {
        const arr = await r3.json();
        // Apenas técnicos reais (filtrados por backend; já excluem SALA)
        setCollabs(Array.isArray(arr) ? arr : []);
      }
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const distribute = useCallback(async (ticketId, collaboratorId) => {
    setDistributing(ticketId);
    try {
      const r = await fetch(
        `${API}/api/lousa/sala/${ticketId}/distribuir`,
        {
          method: "POST",
          headers: {
            ...authHeaders(),
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ collaborator_id: collaboratorId }),
        });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        alert(`Falha ao distribuir: ${e.detail || r.status}`);
        return;
      }
      const j = await r.json();
      // Sucesso silencioso (sem alert intrusivo) — apenas re-fetch.
      console.log("Distribuído:", j.to);
      setPickerFor(null);
      setPickerValue("");
      await fetchAll();
    } finally {
      setDistributing(null);
    }
  }, [fetchAll]);

  const windows = useMemo(() => [
    { id: "manha", label: "Manhã (09h–12h)",
      tickets: (data.by_window && data.by_window.manha) || [] },
    { id: "tarde", label: "Tarde (13h–18h)",
      tickets: (data.by_window && data.by_window.tarde) || [] },
  ], [data]);

  return (
    <div data-testid="lousa-sala-tab" style={{ padding: "0 4px" }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        marginBottom: 16, flexWrap: "wrap",
      }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700,
                       color: "#0f172a" }}>
          🟦 Lousa SALA
        </h2>
        <span style={{ color: "#64748b", fontSize: 13 }}>
          Bolhas agendadas pela Isabella aguardando distribuição —
          atendimento especializado decide o técnico.
        </span>
        <div style={{ marginLeft: "auto", display: "flex",
                        gap: 8, alignItems: "center" }}>
          <input data-testid="sala-date-input" type="date" value={date}
                  onChange={(e) => setDate(e.target.value)}
                  style={{ padding: "6px 10px", border: "1px solid #e2e8f0",
                             borderRadius: 8, fontSize: 13 }} />
          <button data-testid="sala-today-btn"
                   onClick={() => setDate(todayBRIso())}
                   style={{ padding: "6px 12px",
                              border: "1px solid #e2e8f0",
                              borderRadius: 8, background: "#f8fafc",
                              cursor: "pointer", fontSize: 12 }}>
            Hoje
          </button>
          <button data-testid="sala-refresh-btn" onClick={fetchAll}
                   style={{ padding: "6px 12px", border: "none",
                              borderRadius: 8, background: "#0ea5e9",
                              color: "white", cursor: "pointer",
                              fontSize: 12 }}>
            Atualizar
          </button>
        </div>
      </div>

      {/* Calendário compacto: dias com bolhas */}
      {days.length > 0 && (
        <div data-testid="sala-days-strip" style={{
          display: "flex", gap: 6, flexWrap: "wrap",
          marginBottom: 16, padding: 10, background: "#f8fafc",
          borderRadius: 10, border: "1px solid #e2e8f0",
        }}>
          <span style={{ color: "#64748b", fontSize: 11, fontWeight: 700,
                          alignSelf: "center", marginRight: 6 }}>
            DIAS COM BOLHAS:
          </span>
          {days.map((d) => (
            <button key={d.date} data-testid={`sala-day-${d.date}`}
                     onClick={() => setDate(d.date)}
                     style={{
                       padding: "4px 10px", borderRadius: 6,
                       border: "1px solid "
                          + (d.date === date ? "#0ea5e9" : "#e2e8f0"),
                       background: d.date === date ? "#e0f2fe" : "white",
                       cursor: "pointer", fontSize: 12,
                       color: "#0f172a", fontWeight: 600,
                     }}>
              {formatBRDate(d.date)}
              <span style={{
                marginLeft: 6, color: "#dc2626", fontWeight: 700,
              }}>{d.count}</span>
            </button>
          ))}
        </div>
      )}

      {loading && (
        <div data-testid="sala-loading"
              style={{ padding: 20, color: "#64748b", textAlign: "center" }}>
          Carregando…
        </div>
      )}

      {!loading && data.total === 0 && (
        <div data-testid="sala-empty" style={{
          padding: 40, background: "white", borderRadius: 14,
          color: "#94a3b8", textAlign: "center", border: "1px solid #e2e8f0",
        }}>
          Nenhuma bolha em SALA para {formatBRDate(date)}.
        </div>
      )}

      {!loading && data.total > 0 && (
        <div data-testid="sala-windows" style={{ display: "grid",
                gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {windows.map((w) => (
            <div key={w.id} data-testid={`sala-window-${w.id}`}
                  style={{
                    background: "white", borderRadius: 14,
                    border: "1px solid #e2e8f0", padding: 14,
                  }}>
              <div style={{ display: "flex",
                              justifyContent: "space-between",
                              marginBottom: 10 }}>
                <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700,
                               color: "#0f172a" }}>{w.label}</h3>
                <span style={{ color: "#64748b", fontSize: 12 }}>
                  {w.tickets.length} bolha{w.tickets.length === 1 ? "" : "s"}
                </span>
              </div>
              {w.tickets.length === 0 && (
                <div style={{ padding: 12, color: "#94a3b8",
                                fontSize: 12, textAlign: "center" }}>
                  Vazio
                </div>
              )}
              {w.tickets.map((t) => {
                const isPicking = pickerFor === t.id;
                const slot = (t.scheduled_slot_label || "")
                  || ((t.scheduled_time || "").slice(11, 16));
                const clientName = (t.client_snapshot
                  && t.client_snapshot.name) || t.subscriber_name
                  || "Cliente";
                const phone = (t.client_snapshot
                  && t.client_snapshot.phone) || t.phone || "";
                const relato = (t.client_snapshot
                  && t.client_snapshot.relato) || t.description || "";
                return (
                  <div key={t.id}
                        data-testid={`sala-ticket-${t.short_id}`}
                        style={{
                          padding: 10, borderRadius: 10,
                          background: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          marginBottom: 8,
                        }}>
                    <div style={{ display: "flex",
                                    justifyContent: "space-between",
                                    alignItems: "center", marginBottom: 4 }}>
                      <span style={{ fontWeight: 700, color: "#0ea5e9",
                                       fontSize: 13 }}>{slot}</span>
                      <span style={{ fontSize: 11, color: "#64748b",
                                       fontFamily: "monospace" }}>
                        {t.short_id}
                      </span>
                    </div>
                    <div style={{ fontWeight: 600, color: "#0f172a",
                                    fontSize: 14 }}>
                      {clientName}
                    </div>
                    {phone && (
                      <div style={{ color: "#64748b", fontSize: 12 }}>
                        📱 {phone}
                      </div>
                    )}
                    {relato && (
                      <div style={{ color: "#475569", fontSize: 12,
                                      marginTop: 4 }}>
                        {relato}
                      </div>
                    )}

                    {!isPicking && (
                      <button
                        data-testid={`sala-distribuir-btn-${t.short_id}`}
                        disabled={distributing === t.id}
                        onClick={() => {
                          setPickerFor(t.id);
                          setPickerValue("");
                        }}
                        style={{
                          marginTop: 8, padding: "5px 12px",
                          border: "none", borderRadius: 6,
                          background: "#0ea5e9", color: "white",
                          cursor: "pointer", fontSize: 12,
                          fontWeight: 600,
                          opacity: distributing === t.id ? 0.6 : 1,
                        }}>
                        {distributing === t.id ? "Distribuindo…"
                          : "▶ Distribuir para técnico"}
                      </button>
                    )}

                    {isPicking && (
                      <div style={{ marginTop: 8, display: "flex",
                                      gap: 6, flexWrap: "wrap" }}>
                        <select
                          data-testid={`sala-tech-select-${t.short_id}`}
                          value={pickerValue}
                          onChange={(e) => setPickerValue(e.target.value)}
                          style={{ flex: 1, padding: "5px 8px",
                                     border: "1px solid #e2e8f0",
                                     borderRadius: 6, fontSize: 12 }}>
                          <option value="">Escolha o técnico…</option>
                          {collabs.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}{c.cargo ? ` · ${c.cargo}` : ""}
                            </option>
                          ))}
                        </select>
                        <button
                          data-testid={`sala-confirm-btn-${t.short_id}`}
                          disabled={!pickerValue}
                          onClick={() => distribute(t.id, pickerValue)}
                          style={{
                            padding: "5px 10px", border: "none",
                            borderRadius: 6, background: "#16a34a",
                            color: "white", cursor: "pointer",
                            fontSize: 12, fontWeight: 600,
                            opacity: pickerValue ? 1 : 0.5,
                          }}>
                          OK
                        </button>
                        <button
                          data-testid={`sala-cancel-btn-${t.short_id}`}
                          onClick={() => {
                            setPickerFor(null);
                            setPickerValue("");
                          }}
                          style={{
                            padding: "5px 10px", border: "1px solid #e2e8f0",
                            borderRadius: 6, background: "white",
                            cursor: "pointer", fontSize: 12,
                          }}>
                          Cancelar
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
