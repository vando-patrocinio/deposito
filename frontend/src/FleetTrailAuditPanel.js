/* FleetTrailAuditPanel — auditoria de trajeto dos técnicos no campo.

   Gestor seleciona uma data e vê:
     - Lista de todos os técnicos com pings no dia
     - KPIs por técnico (km, tempo de campo, paradas, primeira/última atividade)
     - Mapa com o trail do técnico selecionado (snap-to-road quando disponível)
     - Botão Imprimir/PDF (window.print, layout otimizado)

   Endpoint: GET /api/tech-tracking/fleet/day?date=YYYY-MM-DD
            GET /api/tech-tracking/trail/{collab_id}/snap?date=YYYY-MM-DD

   iter159 — 28/05/2026
*/
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import {
  MapContainer, TileLayer, Polyline, CircleMarker, Tooltip,
} from "react-leaflet";
import { Calendar, Clock, MapPin, Activity,
            Footprints, Octagon, Printer, RefreshCw } from "lucide-react";

const COLORS = {
  primary: "#0ea5e9",
  trail: "#7c3aed",
  text: "#0f172a",
  muted: "#64748b",
  border: "#e2e8f0",
};

const fmtKm = (m) => (m == null ? "—" : (m / 1000).toFixed(2) + " km");
const fmtDur = (s) => {
  if (!s) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h${String(m).padStart(2, "0")}` : `${m}min`;
};
const fmtTime = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleTimeString("pt-BR",
    { hour: "2-digit", minute: "2-digit" }); }
  catch { return "—"; }
};

function todayStr() {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}

function Kpi({ icon, label, value, color }) {
  return (
    <div style={{
      flex: 1, minWidth: 110, padding: 12,
      background: "#fff", borderRadius: 10,
      border: `1px solid ${COLORS.border}`,
      display: "flex", alignItems: "center", gap: 10,
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: 8,
        background: color + "22", color, fontSize: 16,
        display: "grid", placeItems: "center", flexShrink: 0,
      }}>{icon}</div>
      <div>
        <div style={{ fontSize: 16, fontWeight: 800, color: COLORS.text,
                          fontVariantNumeric: "tabular-nums" }}>
          {value}
        </div>
        <div style={{ fontSize: 10.5, color: COLORS.muted, fontWeight: 600,
                          marginTop: 2, textTransform: "uppercase",
                          letterSpacing: 0.5 }}>
          {label}
        </div>
      </div>
    </div>
  );
}

function FitBounds({ trail }) {
  // Hook to fit map to trail bounds whenever it changes
  const map = (window.__leafletMap || null);
  useEffect(() => {
    // Use ref approach inside the MapContainer via whenReady
  }, [trail]);
  return null;
}

export default function FleetTrailAuditPanel() {
  const [date, setDate] = useState(todayStr());
  const [day, setDay] = useState({ items: [], total_techs: 0,
                                          total_distance_m: 0 });
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [trail, setTrail] = useState(null);
  const [trailLoading, setTrailLoading] = useState(false);
  const [err, setErr] = useState("");

  const reload = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r = await api._client.get(
        `/tech-tracking/fleet/day`, { params: { date } });
      setDay(r.data || { items: [] });
      if (r.data?.items?.length && !selectedId) {
        setSelectedId(r.data.items[0].collab_id);
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, [date, selectedId]);

  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    if (!selectedId) { setTrail(null); return; }
    setTrailLoading(true);
    api._client.get(`/tech-tracking/trail/${selectedId}/snap`,
                       { params: { date } })
      .then((r) => setTrail(r.data))
      .catch(() => setTrail(null))
      .finally(() => setTrailLoading(false));
  }, [selectedId, date]);

  const selected = useMemo(() =>
    day.items.find((it) => it.collab_id === selectedId) || null,
    [day.items, selectedId]);

  const center = useMemo(() => {
    if (trail?.bbox) {
      return [
        (trail.bbox.south + trail.bbox.north) / 2,
        (trail.bbox.west + trail.bbox.east) / 2,
      ];
    }
    return [-23.5505, -46.6333]; // SP centro default
  }, [trail]);

  const positions = useMemo(() => {
    if (!trail) return [];
    if (trail.snapped && trail.snapped.length > 1) return trail.snapped;
    if (trail.points && trail.points.length > 1) {
      return trail.points.map((p) => [p.lat, p.lng]);
    }
    return [];
  }, [trail]);

  // iter215 — Quando o backend devolve `segments_snapped` /
  // `segments_raw` (trail higienizado), preferimos renderizar
  // múltiplas polylines em vez de uma única conectando todos os pontos.
  // Isso elimina o "traço voando entre quadras" causado por gaps de
  // GPS (técnico entrou em prédio / perdeu sinal) ou pings imprecisos
  // (>80m de accuracy).
  const segments = useMemo(() => {
    if (!trail) return [];
    const snapped = (trail.segments_snapped || [])
      .filter((s) => Array.isArray(s) && s.length >= 2);
    if (snapped.length > 0) return { mode: "snapped", list: snapped };
    const raw = (trail.segments_raw || [])
      .filter((s) => Array.isArray(s) && s.length >= 2);
    if (raw.length > 0) return { mode: "raw", list: raw };
    return positions.length > 1
      ? { mode: "legacy", list: [positions] }
      : { mode: "empty", list: [] };
  }, [trail, positions]);

  const handlePrint = () => {
    document.body.classList.add("fleet-print-mode");
    window.print();
    setTimeout(() => document.body.classList.remove("fleet-print-mode"), 500);
  };

  return (
    <div data-testid="fleet-trail-audit" style={{ display: "grid", gap: 14 }}>
      {/* Print styles */}
      <style>{`
        @media print {
          body.fleet-print-mode * { visibility: hidden; }
          body.fleet-print-mode [data-testid="fleet-trail-audit"],
          body.fleet-print-mode [data-testid="fleet-trail-audit"] * {
            visibility: visible;
          }
          body.fleet-print-mode [data-testid="fleet-trail-audit"] {
            position: absolute; left: 0; top: 0; width: 100%;
          }
          body.fleet-print-mode .fleet-print-hide { display: none !important; }
        }
      `}</style>

      <div style={{
        padding: 16, borderRadius: 14, background: "#fff",
        border: `1px solid ${COLORS.border}`,
        display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
      }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800,
                            color: COLORS.text, letterSpacing: -0.2 }}>
            🗺 Auditoria de Trajeto · Equipe de Campo
          </h3>
          <div style={{ fontSize: 12, color: COLORS.muted, marginTop: 4 }}>
            {day.total_techs} técnico(s) em campo · {fmtKm(day.total_distance_m)} percorridos
          </div>
        </div>
        <div className="fleet-print-hide"
                style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Calendar size={16} color={COLORS.muted} />
          <input data-testid="fleet-audit-date"
                    type="date" value={date}
                    onChange={(e) => {
                      setDate(e.target.value); setSelectedId(null);
                    }}
                    style={{
                      padding: "7px 10px", borderRadius: 7,
                      border: `1px solid ${COLORS.border}`,
                      fontSize: 12, color: COLORS.text,
                    }} />
          <button data-testid="fleet-audit-reload"
                    onClick={reload} disabled={loading}
                    title="Recarregar"
                    style={{
                      padding: "7px 10px", borderRadius: 7,
                      background: "#fff", border: `1px solid ${COLORS.border}`,
                      cursor: loading ? "wait" : "pointer", color: COLORS.text,
                    }}>
            <RefreshCw size={14} />
          </button>
          <button data-testid="fleet-audit-print"
                    onClick={handlePrint}
                    disabled={!selected}
                    style={{
                      padding: "7px 12px", borderRadius: 7,
                      background: selected
                        ? "linear-gradient(135deg,#0ea5e9,#4f46e5)" : "#cbd5e1",
                      color: "#fff", border: 0,
                      fontSize: 12, fontWeight: 700,
                      cursor: selected ? "pointer" : "not-allowed",
                      display: "inline-flex", alignItems: "center", gap: 6,
                    }}>
            <Printer size={13} /> Imprimir / PDF
          </button>
        </div>
      </div>

      {err && (
        <div style={{
          padding: 12, borderRadius: 10, background: "#fef2f2",
          color: "#7f1d1d", border: "1px solid #fca5a5", fontSize: 13,
        }}>{err}</div>
      )}

      <div style={{ display: "grid", gap: 14,
                       gridTemplateColumns: "minmax(300px, 360px) 1fr" }}>
        {/* Lista de técnicos */}
        <div style={{
          background: "#fff", borderRadius: 12,
          border: `1px solid ${COLORS.border}`,
          padding: 10, maxHeight: 600, overflowY: "auto",
        }}>
          <div style={{ padding: "6px 10px", fontSize: 11, fontWeight: 700,
                            color: COLORS.muted, textTransform: "uppercase",
                            letterSpacing: 0.5 }}>
            Técnicos em campo ({day.items.length})
          </div>
          {loading && (
            <div style={{ padding: 20, textAlign: "center", color: COLORS.muted }}>
              Carregando...
            </div>
          )}
          {!loading && day.items.length === 0 && (
            <div style={{
              padding: 20, textAlign: "center", color: COLORS.muted,
              fontSize: 12,
            }}>
              Nenhum técnico registrou GPS nesta data.
            </div>
          )}
          {day.items.map((it) => {
            const sel = selectedId === it.collab_id;
            return (
              <button key={it.collab_id}
                        data-testid={`fleet-audit-tech-${it.collab_id}`}
                        onClick={() => setSelectedId(it.collab_id)}
                        style={{
                          display: "block", width: "100%", textAlign: "left",
                          padding: 11, borderRadius: 8, marginBottom: 6,
                          background: sel
                            ? "linear-gradient(135deg,#e0f2fe,#dbeafe)"
                            : "#f8fafc",
                          border: `1.5px solid ${sel ? COLORS.primary : "transparent"}`,
                          cursor: "pointer", color: COLORS.text,
                          transition: "background .15s",
                        }}>
                <div style={{ display: "flex", alignItems: "center",
                                  justifyContent: "space-between",
                                  marginBottom: 4 }}>
                  <span style={{ fontSize: 13, fontWeight: 800 }}>
                    {it.name}
                  </span>
                  <span style={{ fontSize: 11, color: COLORS.muted,
                                    fontWeight: 700 }}>
                    {fmtKm(it.distance_m)}
                  </span>
                </div>
                <div style={{ fontSize: 10.5, color: COLORS.muted,
                                  display: "flex", gap: 10 }}>
                  <span>⏱ {fmtTime(it.first)} → {fmtTime(it.last)}</span>
                  <span>⏳ {fmtDur(it.duration_s)}</span>
                  {it.stops > 0 && (
                    <span>🛑 {it.stops}</span>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {/* Detalhe + mapa */}
        <div style={{ display: "grid", gap: 14 }}>
          {selected ? (
            <>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <Kpi icon={<Footprints size={16} />} label="Distância"
                          value={fmtKm(selected.distance_m)} color="#0ea5e9" />
                <Kpi icon={<Clock size={16} />} label="Tempo em campo"
                          value={fmtDur(selected.duration_s)} color="#7c3aed" />
                <Kpi icon={<Octagon size={16} />} label="Paradas"
                          value={selected.stops} color="#f59e0b" />
                <Kpi icon={<Activity size={16} />} label="Pings"
                          value={selected.count} color="#16a34a" />
                <Kpi icon={<MapPin size={16} />} label="Início"
                          value={fmtTime(selected.first)} color="#64748b" />
              </div>

              <div style={{
                background: "#fff", borderRadius: 12, overflow: "hidden",
                border: `1px solid ${COLORS.border}`, height: 540,
                position: "relative",
              }}>
                {trailLoading && (
                  <div style={{
                    position: "absolute", inset: 0,
                    background: "rgba(255,255,255,.8)", zIndex: 500,
                    display: "grid", placeItems: "center",
                    fontSize: 13, color: COLORS.muted, fontWeight: 700,
                  }}>Carregando trajeto...</div>
                )}
                <MapContainer center={center} zoom={14}
                                  style={{ width: "100%", height: "100%" }}>
                  <TileLayer
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    attribution="&copy; OpenStreetMap" />
                  {segments.list.map((seg, idx) => (
                    <Polyline key={`seg-${idx}`} positions={seg}
                                pathOptions={{
                                  color: COLORS.trail,
                                  weight: 5,
                                  opacity: 0.85,
                                  // dashed quando NÃO é snapped (raw/legacy)
                                  dashArray: segments.mode === "snapped"
                                    ? null : "1 6",
                                  lineCap: "round", lineJoin: "round",
                                }}>
                      <Tooltip sticky>
                        <div style={{ fontSize: 11 }}>
                          <strong>{selected.name}</strong><br />
                          {selected.count} pings · {fmtKm(selected.distance_m)}
                          {segments.mode === "snapped" && (
                            <><br/>✓ Casado nas ruas (OSM)</>
                          )}
                          {segments.mode === "raw" && (
                            <><br/>↳ Pings brutos (OSRM indisponível)</>
                          )}
                          {trail?.filtered?.kept_segments > 1 && (
                            <><br/>{trail.filtered.kept_segments} trechos
                              (gap GPS detectado)</>
                          )}
                        </div>
                      </Tooltip>
                    </Polyline>
                  ))}
                  {trail?.points?.length > 0 && (
                    <>
                      <CircleMarker
                        center={[trail.points[0].lat, trail.points[0].lng]}
                        radius={8}
                        pathOptions={{ color: "#fff",
                                         fillColor: "#16a34a",
                                         fillOpacity: 1, weight: 2 }}>
                        <Tooltip>Início · {fmtTime(trail.first)}</Tooltip>
                      </CircleMarker>
                      <CircleMarker
                        center={[trail.points[trail.points.length-1].lat,
                                  trail.points[trail.points.length-1].lng]}
                        radius={8}
                        pathOptions={{ color: "#fff",
                                         fillColor: "#dc2626",
                                         fillOpacity: 1, weight: 2 }}>
                        <Tooltip>Fim · {fmtTime(trail.last)}</Tooltip>
                      </CircleMarker>
                    </>
                  )}
                  <FitBounds trail={trail} />
                </MapContainer>
              </div>
            </>
          ) : (
            <div style={{
              padding: 60, textAlign: "center",
              background: "#fff", borderRadius: 12,
              border: `1px dashed ${COLORS.border}`,
              color: COLORS.muted,
            }}>
              <div style={{ fontSize: 36, marginBottom: 10 }}>🗺</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: COLORS.text }}>
                Selecione um técnico para ver o trajeto
              </div>
              <div style={{ fontSize: 12, marginTop: 4 }}>
                Os técnicos que registraram GPS no dia aparecem na lista à esquerda.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
