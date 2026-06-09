/* LigoMapsPanel — GIS/OSP de planta externa FTTH (iter215bf).
 *
 * Funcionalidades:
 * - Mapa Leaflet com camadas: OpenStreetMap (default) e Satélite Esri.
 * - Plot de ativos da rede: CTO, CEO, POP, Splitter, Poste.
 * - Cores de status: verde=online, amarelo=warning, vermelho=offline.
 * - Modos de edição:
 *    • NAVEGAR — pan/zoom livre
 *    • + ASSET — clique pra colocar pin (escolhe tipo no modal)
 *    • CABO — clica em 2 ativos pra conectar
 *    • MOVER — arrastar ativos
 *    • DELETAR — remove ao clicar
 * - KPIs no header: Regiões Ativas, Total CTOs, Total Cabos.
 */
import React, { useEffect, useState } from "react";
import {
  MapContainer, TileLayer, Marker, Popup, Polyline, LayersControl, useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Map as MapIcon, Plus, MousePointer, Trash2, Cable, Download, Upload, GitMerge, Undo2 } from "lucide-react";

import { client } from "@/api";

// Cores Ligo (Design Oracle)
const COLORS = {
  online: "#237a4b", warning: "#f28c28", offline: "#b42318",
  planned: "#7c3aed",
};
const TYPE_ICONS = {
  cto: { emoji: "▣", label: "CTO" },
  ceo: { emoji: "◆", label: "CEO" },
  pop: { emoji: "★", label: "POP" },
  splitter: { emoji: "⫶", label: "Splitter" },
  post: { emoji: "│", label: "Poste" },
  junction: { emoji: "●", label: "Junção" },
};

// Cria ícone Leaflet customizado a partir de SVG
function makeIcon(type, status) {
  const color = COLORS[status] || COLORS.online;
  const t = TYPE_ICONS[type] || TYPE_ICONS.cto;
  const html = `<div style="
    width:28px;height:28px;background:${color};
    border:2px solid #fff;border-radius:6px;
    display:flex;align-items:center;justify-content:center;
    color:#fff;font-weight:800;font-size:14px;
    box-shadow:0 2px 8px rgba(0,0,0,.35);
    font-family:system-ui;
  ">${t.emoji}</div>`;
  return L.divIcon({
    html, className: "ligo-map-icon",
    iconSize: [28, 28], iconAnchor: [14, 14],
  });
}

// Componente interno que captura clicks no mapa pra modos de edição
function MapClickHandler({ mode, onAddClick }) {
  useMapEvents({
    click(e) {
      if (mode === "add") {
        onAddClick(e.latlng);
      }
    },
  });
  return null;
}

export default function LigoMapsPanel() {
  const [assets, setAssets] = useState([]);
  const [cables, setCables] = useState([]);
  const [stats, setStats] = useState(null);
  const [mode, setMode] = useState("navigate");  // navigate | add | cable | delete
  const [pendingFrom, setPendingFrom] = useState(null);
  const [addModal, setAddModal] = useState(null);  // { lat, lng }
  const [spliceCeo, setSpliceCeo] = useState(null);  // CEO aberto pra fusões
  const [loading, setLoading] = useState(true);
  // iter215bi — Toast de desfazer após delete
  const [undoToast, setUndoToast] = useState(null); // { kind, id, label }
  const [trashModal, setTrashModal] = useState(null); // {assets, cables}

  const load = async () => {
    try {
      const [a, c, s] = await Promise.all([
        client.get("/ligo-maps/assets"),
        client.get("/ligo-maps/cables"),
        client.get("/ligo-maps/stats"),
      ]);
      setAssets(a.data.items || []);
      setCables(c.data.items || []);
      setStats(s.data);
    } catch (e) {
      // silent
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const onAssetClick = async (asset) => {
    if (mode === "delete") {
      if (!window.confirm(`Apagar ${asset.label}? Cabos conectados também serão removidos.`)) return;
      await client.delete(`/ligo-maps/assets/${asset.id}`);
      setUndoToast({ kind: "asset", id: asset.id, label: asset.label,
                      ts: Date.now() });
      load();
    } else if (mode === "cable") {
      if (!pendingFrom) {
        setPendingFrom(asset);
      } else if (pendingFrom.id !== asset.id) {
        const raw = window.prompt(
          `Quantas fibras? (6, 12, 24, 48, 72, 96, 144)`, "12");
        if (raw === null) { setPendingFrom(null); return; } // cancelou
        const fibers = parseInt(raw, 10);
        if (!Number.isFinite(fibers) || fibers <= 0) {
          alert("Quantidade de fibras inválida. Operação cancelada.");
          setPendingFrom(null);
          return;
        }
        try {
          await client.post("/ligo-maps/cables", {
            from_asset_id: pendingFrom.id,
            to_asset_id: asset.id,
            fibers,
          });
        } catch (e) {
          const detail = e?.response?.data?.detail;
          const msg = Array.isArray(detail)
            ? detail.map((d) => d.msg || d.message).join("; ")
            : (detail || e?.message || "Erro desconhecido");
          alert(`Não foi possível criar o cabo:\n\n${msg}`);
        }
        setPendingFrom(null);
        load();
      }
    } else if (mode === "navigate" && ["ceo", "pop"].includes(asset.type)) {
      // FASE 2: Abre diagrama de fusões para CEOs/POPs
      setSpliceCeo(asset);
    }
  };

  const submitAdd = async (form) => {
    if (!addModal) return;
    await client.post("/ligo-maps/assets", {
      ...form,
      lat: addModal.lat, lng: addModal.lng,
    });
    setAddModal(null);
    setMode("navigate");
    load();
  };

  // Centro padrão: Guaratinguetá (SP) - LIGO HQ. Pode ser ajustado.
  const center = assets.length > 0
    ? [assets[0].lat, assets[0].lng]
    : [-22.8126, -45.1925];

  return (
    <div data-testid="ligo-maps-panel" style={{ height: "calc(100vh - 100px)" }}>
      {/* Header com KPIs e modos */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "12px 16px", background: "#fff",
        borderBottom: "1px solid #e2e8f0", marginBottom: 0,
      }}>
        <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
          <h2 style={{ margin: 0, fontSize: 18, color: "#4b1d7a",
                          display: "flex", alignItems: "center", gap: 8 }}>
            <MapIcon size={18} /> Ligo Maps
          </h2>
          {stats && (
            <>
              <KPI label="Regiões" value={stats.regions_count} />
              <KPI label="CTOs" value={stats.by_type?.cto || 0} />
              <KPI label="CEOs" value={stats.by_type?.ceo || 0} />
              <KPI label="Cabos" value={stats.total_cables} color="#237a4b" />
            </>
          )}
        </div>

        {/* Modos + Ações */}
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          <ModeBtn icon={<MousePointer size={13} />} label="Navegar"
            active={mode === "navigate"}
            onClick={() => { setMode("navigate"); setPendingFrom(null); }}
            testId="map-mode-navigate" />
          <ModeBtn icon={<Plus size={13} />} label="+ Ativo"
            active={mode === "add"}
            onClick={() => { setMode("add"); setPendingFrom(null); }}
            testId="map-mode-add" />
          <ModeBtn icon={<Cable size={13} />} label="Cabo"
            active={mode === "cable"}
            onClick={() => { setMode("cable"); setPendingFrom(null); }}
            testId="map-mode-cable" />
          <ModeBtn icon={<MousePointer size={13} />} label="Editar trajeto"
            active={mode === "edit-cable"}
            onClick={() => { setMode("edit-cable"); setPendingFrom(null); }}
            testId="map-mode-edit-cable" />
          <ModeBtn icon={<Trash2 size={13} />} label="Deletar"
            active={mode === "delete"}
            onClick={() => { setMode("delete"); setPendingFrom(null); }}
            testId="map-mode-delete" danger />
          {/* Separador visual */}
          <span style={{ width: 1, background: "#e2e8f0", margin: "0 4px" }} />
          <ModeBtn icon={<Upload size={13} />} label="Importar rede"
            onClick={async () => {
              if (!window.confirm("Importar CTOs e clientes do banco existente para o mapa? É idempotente — não duplica.")) return;
              const r = await client.post("/ligo-maps/import-from-network", {});
              alert(`✓ Importação concluída\n\n• ${r.data.added_ctos} CTOs\n• ${r.data.added_subscribers} clientes\n• ${r.data.skipped} já existiam (ignorados)`);
              load();
            }}
            testId="map-import" />
          <ModeBtn icon={<Download size={13} />} label="KML"
            onClick={() => {
              const url = `${process.env.REACT_APP_BACKEND_URL}/api/ligo-maps/export/kml`;
              window.open(url, "_blank");
            }}
            testId="map-export-kml" />
          <ModeBtn icon={<Undo2 size={13} />} label="Lixeira"
            onClick={async () => {
              try {
                const r = await client.get("/ligo-maps/trash");
                setTrashModal(r.data);
              } catch (e) {
                alert("Não foi possível abrir a lixeira.");
              }
            }}
            testId="map-trash" />
        </div>
      </div>

      {/* Indicador de modo ativo */}
      {mode !== "navigate" && (
        <div style={{
          padding: "6px 16px", background: "#fef3c7",
          color: "#92400e", fontSize: 12, fontWeight: 600,
          borderBottom: "1px solid #fde68a",
        }}>
          {mode === "add" && "Clique no mapa para adicionar um ativo"}
          {mode === "cable" && (pendingFrom
            ? `Selecione o destino do cabo (origem: ${pendingFrom.label})`
            : "Clique no ativo de ORIGEM do cabo")}
          {mode === "edit-cable" && "Clique e arraste os pontos cinzas no meio do cabo pra ajustar o trajeto. Clique duplo num cabo pra adicionar um waypoint."}
          {mode === "delete" && "⚠ Clique em um ativo OU cabo para apagar"}
        </div>
      )}

      {/* Mapa */}
      <div style={{ height: "calc(100% - 60px)", position: "relative" }}>
        <MapContainer center={center} zoom={14}
          style={{ height: "100%", width: "100%" }}
          scrollWheelZoom={true}>
          <LayersControl position="topright">
            <LayersControl.BaseLayer checked name="Satélite">
              <TileLayer
                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                attribution='Tiles &copy; Esri' />
            </LayersControl.BaseLayer>
            <LayersControl.BaseLayer name="OpenStreetMap">
              <TileLayer
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                attribution='&copy; OpenStreetMap' />
            </LayersControl.BaseLayer>
          </LayersControl>

          <MapClickHandler mode={mode}
            onAddClick={(latlng) => setAddModal(latlng)} />

          {/* Cabos primeiro pra ficarem abaixo dos pins */}
          {cables.map((c) => {
            // iter215bf — cor herda do PIOR status entre as 2 pontas
            const from = assets.find((a) => a.id === c.from_asset_id);
            const to = assets.find((a) => a.id === c.to_asset_id);
            const ranking = { offline: 3, warning: 2, planned: 1, online: 0 };
            const worst = Math.max(
              ranking[from?.status] ?? 0,
              ranking[to?.status] ?? 0,
              ranking[c.status] ?? 0,
            );
            const cableStatus = Object.keys(ranking)
              .find((k) => ranking[k] === worst) || "online";
            return (
              <EditablePolyline key={c.id} cable={c}
                color={COLORS[cableStatus] || COLORS.online}
                editable={mode === "edit-cable"}
                onDelete={async () => {
                  if (mode === "delete") {
                    if (window.confirm(`Apagar cabo ${c.label}?`)) {
                      await client.delete(`/ligo-maps/cables/${c.id}`);
                      setUndoToast({ kind: "cable", id: c.id,
                                      label: c.label, ts: Date.now() });
                      load();
                    }
                  }
                }}
                onWaypointsChange={async (wp) => {
                  await client.patch(`/ligo-maps/cables/${c.id}`,
                    { waypoints: wp });
                  load();
                }} />
            );
          })}

          {/* Ativos */}
          {assets.map((a) => (
            <Marker key={a.id}
              position={[a.lat, a.lng]}
              icon={makeIcon(a.type, a.status)}
              eventHandlers={{ click: () => onAssetClick(a) }}>
              <Popup>
                <strong>{a.label}</strong><br />
                {TYPE_ICONS[a.type]?.label || a.type}
                {a.capacity && ` · ${a.capacity}p`}
                {a.model && <><br />Modelo: {a.model}</>}
                <br />Status: <strong style={{
                  color: COLORS[a.status],
                }}>{a.status}</strong>
                {a.region && <><br />Região: {a.region}</>}
              </Popup>
            </Marker>
          ))}
        </MapContainer>

        {/* Modal de adicionar ativo */}
        {addModal && (
          <AddAssetModal
            lat={addModal.lat} lng={addModal.lng}
            onClose={() => { setAddModal(null); setMode("navigate"); }}
            onSubmit={submitAdd} />
        )}

        {/* FASE 2 — Diagrama de Fusões do CEO selecionado */}
        {spliceCeo && (
          <SpliceDiagram
            ceo={spliceCeo}
            assets={assets}
            cables={cables}
            onClose={() => setSpliceCeo(null)} />
        )}

        {/* iter215bj — Modal Lixeira */}
        {trashModal && (
          <TrashModal data={trashModal}
            onRestore={async (kind, id) => {
              await client.post(`/ligo-maps/restore/${kind}/${id}`, {});
              const r = await client.get("/ligo-maps/trash");
              setTrashModal(r.data);
              load();
            }}
            onClose={() => setTrashModal(null)} />
        )}

        {/* iter215bi — Toast de Desfazer (10s) */}
        {undoToast && (
          <UndoToast
            toast={undoToast}
            onUndo={async () => {
              try {
                await client.post(
                  `/ligo-maps/restore/${undoToast.kind}/${undoToast.id}`,
                  {});
                setUndoToast(null);
                load();
              } catch (e) {
                alert(`Não foi possível restaurar: ${e?.message || e}`);
              }
            }}
            onDismiss={() => setUndoToast(null)} />
        )}

        {/* Loading overlay */}
        {loading && (
          <div style={{
            position: "absolute", top: "50%", left: "50%",
            transform: "translate(-50%, -50%)", zIndex: 1000,
            background: "#fff", padding: 16, borderRadius: 8,
            boxShadow: "0 8px 20px rgba(0,0,0,.15)",
          }}>Carregando rede…</div>
        )}
      </div>
    </div>
  );
}

function KPI({ label, value, color = "#0f172a" }) {
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <span style={{ fontSize: 10, color: "#64748b",
                       textTransform: "uppercase", letterSpacing: 0.4,
                       fontWeight: 700 }}>{label}</span>
      <span style={{ fontSize: 18, fontWeight: 800, color,
                       lineHeight: 1 }}>{value}</span>
    </div>
  );
}

function ModeBtn({ icon, label, active, onClick, testId, danger }) {
  const bg = active
    ? (danger ? "#b42318" : "#4b1d7a")
    : "#fff";
  const color = active ? "#fff" : "#475569";
  return (
    <button onClick={onClick} data-testid={testId}
      style={{
        padding: "6px 12px", fontSize: 12, fontWeight: 600,
        background: bg, color,
        border: `1px solid ${active ? bg : "#e2e8f0"}`,
        borderRadius: 6, cursor: "pointer",
        display: "flex", alignItems: "center", gap: 4,
      }}>
      {icon} {label}
    </button>
  );
}

function AddAssetModal({ lat, lng, onClose, onSubmit }) {
  const [type, setType] = useState("cto");
  const [label, setLabel] = useState("");
  const [capacity, setCapacity] = useState(16);
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("online");
  const [region, setRegion] = useState("");
  return (
    <div onClick={onClose} style={{
      position: "absolute", inset: 0, background: "rgba(0,0,0,.5)",
      zIndex: 1001, display: "flex", alignItems: "center",
      justifyContent: "center", padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()}
        data-testid="add-asset-modal"
        style={{
          background: "#fff", borderRadius: 12, padding: 20,
          maxWidth: 420, width: "100%",
          boxShadow: "0 20px 50px rgba(0,0,0,.3)",
        }}>
        <h3 style={{ margin: "0 0 12px", color: "#4b1d7a" }}>
          Adicionar Ativo
        </h3>
        <div style={{ fontSize: 11, color: "#64748b", marginBottom: 14 }}>
          Posição: {lat.toFixed(6)}, {lng.toFixed(6)}
        </div>
        <FormField label="Tipo">
          <select className="input" value={type}
            data-testid="add-asset-type"
            onChange={(e) => setType(e.target.value)}>
            {Object.entries(TYPE_ICONS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </FormField>
        <FormField label="Identificação *">
          <input className="input" value={label}
            data-testid="add-asset-label"
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Ex: CTO 0001, CEO Bairro X, POP Sede" />
        </FormField>
        <FormField label="Capacidade (portas/fibras)">
          <input className="input" type="number" value={capacity}
            onChange={(e) => setCapacity(parseInt(e.target.value || 0, 10))} />
        </FormField>
        <FormField label="Modelo">
          <input className="input" value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="Ex: Furukawa 1x16, ZTE C320" />
        </FormField>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <FormField label="Status">
            <select className="input" value={status}
              onChange={(e) => setStatus(e.target.value)}>
              <option value="online">Online</option>
              <option value="warning">Atenção</option>
              <option value="offline">Offline</option>
              <option value="planned">Planejado</option>
            </select>
          </FormField>
          <FormField label="Região/Cidade">
            <input className="input" value={region}
              onChange={(e) => setRegion(e.target.value)}
              placeholder="Ex: GUARATINGUETA" />
          </FormField>
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                        marginTop: 16 }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button data-testid="add-asset-submit"
            disabled={!label.trim()}
            onClick={() => onSubmit({ type, label: label.trim(),
                                        capacity, model, status, region })}
            style={{
              padding: "8px 16px", fontWeight: 700, background: "#4b1d7a",
              color: "#fff", border: "none", borderRadius: 6,
              cursor: "pointer", opacity: label.trim() ? 1 : 0.5,
            }}>
            Adicionar
          </button>
        </div>
      </div>
    </div>
  );
}

function FormField({ label, children }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                        textTransform: "uppercase", letterSpacing: 0.4,
                        display: "block", marginBottom: 4 }}>{label}</label>
      {children}
    </div>
  );
}

/* FASE 2 — Diagrama de Fusões (Splice Diagram) ---------------------- */

// Padrão TIA-598-C: cores das fibras 1-12 (depois repete em pares)
const FIBER_COLORS = [
  "#0066CC", "#FF7F00", "#00A651", "#8B4513", "#9B9B9B", "#FFFFFF",
  "#E60012", "#000000", "#FFD700", "#7B1FA2", "#FFC0CB", "#00BCD4",
];
function fiberColor(n) {
  return FIBER_COLORS[(n - 1) % 12];
}

/* iter215bg — Polyline editável: arrastar waypoints + duplo-clique adiciona ponto */
function EditablePolyline({ cable, color, editable, onDelete, onWaypointsChange }) {
  const [wp, setWp] = useState(cable.waypoints || []);
  useEffect(() => { setWp(cable.waypoints || []); }, [cable.waypoints]);

  const updateWaypoint = (idx, latlng) => {
    const next = wp.map((p, i) => i === idx ? [latlng.lat, latlng.lng] : p);
    setWp(next);
  };
  const commit = (next) => {
    onWaypointsChange(next);
  };
  const onLineDblClick = (e) => {
    if (!editable) return;
    const { lat, lng } = e.latlng;
    // Insere waypoint próximo do segmento mais próximo
    const next = [...wp];
    next.splice(next.length - 1, 0, [lat, lng]);
    setWp(next);
    commit(next);
  };

  return (
    <>
      <Polyline
        positions={wp}
        pathOptions={{ color, weight: 3, opacity: 0.85 }}
        eventHandlers={{
          click: onDelete,
          dblclick: onLineDblClick,
        }}>
        <Popup>
          <strong>{cable.label}</strong><br />
          {cable.fibers}FO · {cable.status}
        </Popup>
      </Polyline>
      {editable && wp.slice(1, -1).map((p, i) => (
        <Marker key={i + 1}
          position={p}
          draggable={true}
          icon={L.divIcon({
            html: `<div style="width:10px;height:10px;background:#fff;
                     border:2px solid ${color};border-radius:50%;
                     box-shadow:0 0 4px rgba(0,0,0,.4)"></div>`,
            className: "ligo-waypoint-handle",
            iconSize: [10, 10], iconAnchor: [5, 5],
          })}
          eventHandlers={{
            drag: (e) => updateWaypoint(i + 1, e.target.getLatLng()),
            dragend: () => commit(wp),
            contextmenu: () => {
              const next = wp.filter((_, idx) => idx !== i + 1);
              setWp(next);
              commit(next);
            },
          }} />
      ))}
    </>
  );
}


function SpliceDiagram({ ceo, assets, cables, onClose }) {
  const [splices, setSplices] = useState([]);
  const [selected, setSelected] = useState(null);  // {cableId, fiber}
  const [loading, setLoading] = useState(true);

  // Cabos conectados ao CEO
  const connectedCables = cables.filter(
    (c) => c.from_asset_id === ceo.id || c.to_asset_id === ceo.id);

  const load = async () => {
    setLoading(true);
    try {
      const r = await client.get("/ligo-maps/splices", {
        params: { ceo_asset_id: ceo.id },
      });
      setSplices(r.data.items || []);
    } catch {
      setSplices([]);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [ceo.id]);  // eslint-disable-line

  const onFiberClick = async (cableId, fiber) => {
    if (!selected) {
      setSelected({ cableId, fiber });
      return;
    }
    if (selected.cableId === cableId && selected.fiber === fiber) {
      setSelected(null);
      return;
    }
    // Fundir
    try {
      await client.post("/ligo-maps/splices", {
        ceo_asset_id: ceo.id,
        cable_in_id: selected.cableId,
        fiber_in: selected.fiber,
        cable_out_id: cableId,
        fiber_out: fiber,
      });
      setSelected(null);
      load();
    } catch (e) {
      alert(`Erro ao fundir: ${e?.response?.data?.detail || e.message}`);
      setSelected(null);
    }
  };

  const removeSplice = async (id) => {
    if (!window.confirm("Remover essa fusão?")) return;
    await client.delete(`/ligo-maps/splices/${id}`);
    load();
  };

  // Helper: verifica se uma fibra está fundida
  const findSplice = (cableId, fiber) => splices.find(
    (s) => (s.cable_in_id === cableId && s.fiber_in === fiber)
        || (s.cable_out_id === cableId && s.fiber_out === fiber));

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.65)",
      zIndex: 2000, display: "flex", alignItems: "center",
      justifyContent: "center", padding: 24,
    }}>
      <div onClick={(e) => e.stopPropagation()}
        data-testid="splice-diagram"
        style={{
          background: "#fff", borderRadius: 12, padding: 20,
          maxWidth: 1100, width: "100%", maxHeight: "92vh",
          overflow: "auto",
          boxShadow: "0 24px 64px rgba(0,0,0,.4)",
        }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", marginBottom: 16 }}>
          <h2 style={{ margin: 0, color: "#4b1d7a", display: "flex",
                          alignItems: "center", gap: 8 }}>
            <GitMerge size={20} /> Diagrama de Fusões — {ceo.label}
          </h2>
          <button className="btn btn-ghost" onClick={onClose}>×</button>
        </div>

        <div style={{ fontSize: 12, color: "#475569", marginBottom: 12 }}>
          Clique em uma fibra de origem, depois clique em outra fibra de
          destino para criar a fusão. Cores seguem o padrão TIA-598-C.
          {selected && (
            <span style={{ color: "#4b1d7a", fontWeight: 700, marginLeft: 8 }}>
              Origem selecionada: F{selected.fiber}
            </span>
          )}
        </div>

        {loading && <div style={{ padding: 20 }}>Carregando fusões…</div>}

        {!loading && connectedCables.length === 0 && (
          <div style={{ padding: 30, textAlign: "center", color: "#64748b" }}>
            Nenhum cabo conectado a este CEO. Use o modo &quot;Cabo&quot; no mapa
            para conectar este ponto a outro.
          </div>
        )}

        {!loading && connectedCables.length > 0 && (
          <div style={{
            display: "grid",
            gridTemplateColumns: `repeat(${connectedCables.length}, 1fr)`,
            gap: 16,
          }}>
            {connectedCables.map((cable) => {
              const other = assets.find((a) =>
                a.id === (cable.from_asset_id === ceo.id
                          ? cable.to_asset_id : cable.from_asset_id));
              return (
                <div key={cable.id} style={{
                  border: "1px solid #e2e8f0", borderRadius: 8,
                  padding: 12, background: "#f8fafc",
                }}>
                  <div style={{ fontSize: 12, fontWeight: 700,
                                  marginBottom: 8, color: "#0f172a" }}>
                    {cable.label}
                    <div style={{ fontSize: 10, color: "#64748b",
                                    fontWeight: 400 }}>
                      {cable.fibers}FO · → {other?.label || "?"}
                    </div>
                  </div>
                  <div style={{ display: "grid",
                                  gridTemplateColumns: "repeat(2, 1fr)",
                                  gap: 4 }}>
                    {Array.from({ length: cable.fibers }, (_, i) => i + 1)
                      .map((f) => {
                        const splice = findSplice(cable.id, f);
                        const isSelected = selected
                          && selected.cableId === cable.id
                          && selected.fiber === f;
                        return (
                          <div key={f}
                            data-testid={`fiber-${cable.id}-${f}`}
                            onClick={() => splice
                              ? removeSplice(splice.id)
                              : onFiberClick(cable.id, f)}
                            style={{
                              display: "flex", alignItems: "center",
                              gap: 6, padding: "4px 8px",
                              background: isSelected ? "#fef3c7" : "#fff",
                              border: `1px solid ${isSelected ? "#f28c28" : "#e2e8f0"}`,
                              borderRadius: 4, cursor: "pointer",
                              fontSize: 11,
                            }}
                            title={splice ? `Fundida — clique pra remover` : "Clique pra selecionar"}>
                            <span style={{
                              width: 14, height: 14, borderRadius: 3,
                              background: fiberColor(f),
                              border: "1px solid #888",
                            }} />
                            <span style={{ fontWeight: 600 }}>F{f}</span>
                            {splice && (
                              <span style={{ marginLeft: "auto",
                                              fontSize: 9, color: "#237a4b",
                                              fontWeight: 700 }}>
                                ✓
                              </span>
                            )}
                          </div>
                        );
                      })}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Resumo */}
        {!loading && splices.length > 0 && (
          <div style={{
            marginTop: 16, padding: 12,
            background: "#dbeafe", border: "1px solid #93c5fd",
            borderRadius: 8, fontSize: 12, color: "#1e40af",
          }}>
            <strong>{splices.length} fusões ativas</strong> neste CEO.
            Clique em uma fibra fundida (✓) para removê-la.
          </div>
        )}
      </div>
    </div>
  );
}


/* iter215bi — Toast com botão "Desfazer" após delete (10s auto-dismiss) */
function UndoToast({ toast, onUndo, onDismiss }) {
  const [secondsLeft, setSecondsLeft] = useState(10);
  useEffect(() => {
    setSecondsLeft(10);
    const iv = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) { clearInterval(iv); onDismiss(); return 0; }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(iv);
  }, [toast.ts, onDismiss]);

  return (
    <div data-testid="undo-toast" style={{
      position: "absolute", bottom: 24, left: "50%",
      transform: "translateX(-50%)", zIndex: 1500,
      background: "#0f172a", color: "#fff",
      padding: "12px 16px", borderRadius: 8,
      boxShadow: "0 10px 30px rgba(0,0,0,.35)",
      display: "flex", alignItems: "center", gap: 12,
      minWidth: 360,
    }}>
      <Trash2 size={16} style={{ color: "#fca5a5" }} />
      <div style={{ flex: 1, fontSize: 13 }}>
        <strong>{toast.label}</strong> apagado(a).
        <span style={{ color: "#94a3b8", marginLeft: 6,
                         fontSize: 11 }}>
          Reverter em {secondsLeft}s…
        </span>
      </div>
      <button
        data-testid="undo-restore-btn"
        onClick={onUndo}
        style={{
          background: "#f28c28", color: "#fff",
          border: "none", borderRadius: 6,
          padding: "6px 14px", fontWeight: 700,
          cursor: "pointer", fontSize: 12,
          display: "flex", alignItems: "center", gap: 6,
        }}>
        <Undo2 size={13} /> Desfazer
      </button>
      <button onClick={onDismiss}
        data-testid="undo-dismiss"
        style={{
          background: "transparent", color: "#94a3b8",
          border: "none", cursor: "pointer", fontSize: 18,
          padding: "0 4px",
        }}>×</button>
    </div>
  );
}


/* iter215bj — Modal de Lixeira com restore por linha */
function TrashModal({ data, onRestore, onClose }) {
  const items = [
    ...(data.assets || []).map((a) => ({ ...a, _kind: "asset" })),
    ...(data.cables || []).map((c) => ({ ...c, _kind: "cable" })),
  ];
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.6)",
      zIndex: 2000, display: "flex", alignItems: "center",
      justifyContent: "center", padding: 24,
    }}>
      <div onClick={(e) => e.stopPropagation()}
        data-testid="trash-modal"
        style={{
          background: "#fff", borderRadius: 12, padding: 20,
          maxWidth: 720, width: "100%", maxHeight: "85vh",
          overflow: "auto", boxShadow: "0 24px 64px rgba(0,0,0,.4)",
        }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", marginBottom: 14 }}>
          <h2 style={{ margin: 0, color: "#4b1d7a",
                          display: "flex", alignItems: "center", gap: 8 }}>
            <Trash2 size={18} /> Lixeira ({items.length})
          </h2>
          <button onClick={onClose} className="btn btn-ghost">×</button>
        </div>
        <div style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
          Aqui ficam os últimos 50 ativos/cabos apagados. Clique
          em <strong>Restaurar</strong> pra trazer de volta.
        </div>
        {items.length === 0 ? (
          <div style={{ padding: 30, textAlign: "center",
                          color: "#64748b" }}>
            Lixeira vazia.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                <th style={{ padding: "8px 10px", fontWeight: 700 }}>Tipo</th>
                <th style={{ padding: "8px 10px", fontWeight: 700 }}>Nome</th>
                <th style={{ padding: "8px 10px", fontWeight: 700 }}>Apagado em</th>
                <th style={{ padding: "8px 10px", fontWeight: 700 }}>Por</th>
                <th style={{ padding: "8px 10px" }}></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={`${it._kind}-${it.id}`}
                  data-testid={`trash-row-${it.id}`}
                  style={{ borderTop: "1px solid #e2e8f0" }}>
                  <td style={{ padding: "8px 10px",
                                 textTransform: "uppercase",
                                 fontWeight: 700, color: "#475569",
                                 fontSize: 10 }}>
                    {it._kind === "asset"
                      ? (TYPE_ICONS[it.type]?.label || it.type)
                      : `Cabo ${it.fibers || ""}FO`}
                  </td>
                  <td style={{ padding: "8px 10px",
                                 fontWeight: 600 }}>{it.label}</td>
                  <td style={{ padding: "8px 10px", color: "#64748b",
                                 fontSize: 12 }}>
                    {it.deleted_at ? new Date(it.deleted_at)
                      .toLocaleString("pt-BR") : "—"}
                  </td>
                  <td style={{ padding: "8px 10px", color: "#64748b",
                                 fontSize: 12 }}>
                    {it.deleted_by || "—"}
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right" }}>
                    <button
                      data-testid={`trash-restore-${it.id}`}
                      onClick={() => onRestore(it._kind, it.id)}
                      style={{
                        padding: "5px 12px", fontSize: 11,
                        background: "#f28c28", color: "#fff",
                        border: "none", borderRadius: 5,
                        fontWeight: 700, cursor: "pointer",
                        display: "inline-flex", alignItems: "center", gap: 4,
                      }}>
                      <Undo2 size={11} /> Restaurar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

