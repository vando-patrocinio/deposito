/*
CTOOccupancyPanel.js — Relatório "Mapa de Ocupação por CTO".

Mostra:
- Métricas globais (total portas/usadas/livres + ocupação global)
- Alertas: contagem de CTOs saturadas (≥80%) e lotadas (100%)
- Lista ordenada por % decrescente com barra de progresso colorida
- Click numa linha abre o CTOLocationViewer no mapa

Usa endpoint `/rede-ia/ctos/occupancy`.
*/
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import CTOLocationViewer from "@/CTOLocationViewer";

export default function CTOOccupancyPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [threshold, setThreshold] = useState(80);
  const [filter, setFilter] = useState("all"); // all | saturated | full
  const [mapCto, setMapCto] = useState(null);

  const load = () => {
    setLoading(true);
    setErr("");
    api.redeIaCtosOccupancy({ threshold: threshold / 100 })
      .then(setData)
      .catch((e) => setErr(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [threshold]);

  const items = useMemo(() => {
    if (!data) return [];
    if (filter === "saturated") return data.items.filter((x) => x.is_saturated);
    if (filter === "full") return data.items.filter((x) => x.is_full);
    return data.items;
  }, [data, filter]);

  return (
    <div data-testid="cto-occupancy-panel">
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 14, gap: 10, flexWrap: "wrap",
      }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: "#0f172a" }}>
            📊 Mapa de Ocupação por CTO
          </h3>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
            Identifica CTOs próximas da capacidade total para planejar expansão.
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label style={{ fontSize: 11, color: "#475569", fontWeight: 700 }}>
            Limiar saturação:
          </label>
          <input data-testid="threshold-input"
                  type="number" min="50" max="100" step="5"
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value) || 80)}
                  style={{ width: 60, padding: "5px 8px", borderRadius: 6,
                            border: "1px solid #cbd5e1", fontSize: 13,
                            fontWeight: 700, textAlign: "center" }} />
          <span style={{ fontSize: 11, color: "#475569" }}>%</span>
          <button onClick={load} data-testid="reload-btn"
                    style={btnGhost}>↻</button>
          <button data-testid="occupancy-pdf-btn"
                    onClick={async () => {
                      try {
                        const r = await api._client.get(
                          `/rede-ia/ctos/occupancy/pdf?threshold=${threshold/100}`,
                          { responseType: "blob" },
                        );
                        const url = URL.createObjectURL(r.data);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = `ocupacao_ctos_${new Date().toISOString().slice(0,10)}.pdf`;
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                        URL.revokeObjectURL(url);
                      } catch (e) {
                        setErr(e?.response?.data?.detail || e.message);
                      }
                    }}
                    style={{ ...btnGhost, background: "#0f172a", color: "#fff",
                              borderColor: "#0f172a", fontSize: 12,
                              cursor: "pointer" }}>
            📄 PDF
          </button>
        </div>
      </div>

      {err && (
        <div style={errBox}>{err}</div>
      )}

      {/* Summary cards */}
      {data?.summary && (
        <div style={summaryGrid}>
          <SummaryCard label="CTOs aprovadas"
                       value={data.summary.total_ctos}
                       color="#0f172a" testid="sum-ctos" />
          <SummaryCard label="Ocupação global"
                       value={`${data.summary.global_percent}%`}
                       sub={`${data.summary.total_used}/${data.summary.total_ports} portas`}
                       color="#0f766e" testid="sum-global" />
          <SummaryCard label={`Saturadas (≥${data.summary.threshold_percent}%)`}
                       value={data.summary.saturated_count}
                       color="#ca8a04"
                       onClick={() => setFilter(filter === "saturated" ? "all" : "saturated")}
                       active={filter === "saturated"}
                       testid="sum-saturated" />
          <SummaryCard label="Lotadas (100%)"
                       value={data.summary.full_count}
                       color="#dc2626"
                       onClick={() => setFilter(filter === "full" ? "all" : "full")}
                       active={filter === "full"}
                       testid="sum-full" />
        </div>
      )}

      {/* List of CTOs */}
      <div style={{ background: "#fff", borderRadius: 10,
                       border: "1px solid #e2e8f0", overflow: "hidden",
                       marginTop: 14 }}>
        {loading && (
          <div style={{ padding: 24, textAlign: "center", color: "#64748b" }}>
            Carregando...
          </div>
        )}
        {!loading && items.length === 0 && (
          <div style={{ padding: 24, textAlign: "center", color: "#64748b" }}>
            {filter === "all" ? "Sem CTOs aprovadas cadastradas." :
             "Nenhuma CTO neste filtro."}
          </div>
        )}
        {!loading && items.map((c, i) => (
          <div key={c.id} data-testid={`cto-occ-row-${c.id}`}
               style={{
                 padding: "12px 14px",
                 borderBottom: i < items.length - 1 ? "1px solid #f1f5f9" : 0,
                 display: "flex", alignItems: "center", gap: 12,
               }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 800, color: "#0f172a" }}>
                  {c.name}
                </span>
                {c.is_full && (
                  <span style={badge("#fee2e2", "#991b1b")}>LOTADA</span>
                )}
                {!c.is_full && c.is_saturated && (
                  <span style={badge("#fef3c7", "#92400e")}>SATURADA</span>
                )}
              </div>
              <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                {c.bairro ? `${c.bairro} · ` : ""}VLAN {c.vlan} · {c.used}/{c.capacity} portas usadas
              </div>
              {/* Barra de progresso */}
              <div style={{ marginTop: 6, height: 6, background: "#f1f5f9",
                              borderRadius: 999, overflow: "hidden" }}>
                <div style={{
                  width: `${c.percent}%`, height: "100%",
                  background: c.is_full ? "#dc2626"
                            : c.is_saturated ? "#f59e0b" : "#10b981",
                  transition: "width 250ms",
                }} />
              </div>
            </div>
            <div style={{ minWidth: 56, textAlign: "right" }}>
              <div style={{ fontSize: 18, fontWeight: 800,
                              color: c.is_full ? "#dc2626"
                                    : c.is_saturated ? "#92400e" : "#0f172a" }}>
                {c.percent}%
              </div>
            </div>
            {(c.gps?.lat || c.gps?.lng) && (
              <button onClick={() => setMapCto({
                          name: c.name, gps: c.gps,
                          address: { bairro: c.bairro },
                        })}
                        data-testid={`cto-occ-map-${c.id}`}
                        style={mapBtn} title="Ver no mapa">
                🗺
              </button>
            )}
          </div>
        ))}
      </div>

      {mapCto && (
        <CTOLocationViewer cto={mapCto} onClose={() => setMapCto(null)} />
      )}
    </div>
  );
}

function SummaryCard({ label, value, sub, color, onClick, active, testid }) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      disabled={!onClick}
      style={{
        padding: "12px 14px", textAlign: "left",
        border: `1.5px solid ${active ? color : "#e2e8f0"}`,
        background: active ? "#f8fafc" : "#fff",
        borderRadius: 10, cursor: onClick ? "pointer" : "default",
        flex: "1 1 130px", minWidth: 130,
      }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#475569",
                       textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, color, marginTop: 2,
                       lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>
          {sub}
        </div>
      )}
    </button>
  );
}

const summaryGrid = {
  display: "flex", flexWrap: "wrap", gap: 10,
};
const errBox = {
  padding: 10, background: "#fee2e2", color: "#991b1b",
  borderRadius: 8, fontSize: 12, marginBottom: 10,
};
const btnGhost = {
  padding: "5px 10px", fontSize: 14, fontWeight: 700,
  background: "#fff", color: "#1d4ed8",
  border: "1px solid #cbd5e1", borderRadius: 6, cursor: "pointer",
};
const mapBtn = {
  padding: "6px 10px", fontSize: 16,
  background: "#f0fdfa", color: "#0f766e",
  border: "1px solid #99f6e4", borderRadius: 6, cursor: "pointer",
};
const badge = (bg, fg) => ({
  background: bg, color: fg,
  fontSize: 9, fontWeight: 800, padding: "2px 6px",
  borderRadius: 999, textTransform: "uppercase", letterSpacing: 0.5,
});
