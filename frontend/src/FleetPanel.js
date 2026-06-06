import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import {
  Car, Camera, Fuel, ArrowRightLeft, Activity, Plus,
  CheckCircle2, AlertTriangle, RefreshCw, Search, Trash2,
  X, Loader2, Route,
} from "lucide-react";
import SignatureCanvas from "@/fleet/SignatureCanvas";
import TicketLogImporter from "@/fleet/TicketLogImporter";
import FleetTrailAuditPanel from "@/FleetTrailAuditPanel";

/* =============================================================
   FleetPanel — Gestão de Frota.
   Sub-abas: Veículos · Vistorias · Romaneio · Combustível · KPIs
============================================================= */
export default function FleetPanel() {
  const [tab, setTab] = useState("vehicles");
  const [kpis, setKpis] = useState(null);
  useEffect(() => {
    api.fleetKpis().then(setKpis).catch(() => {});
  }, []);
  return (
    <div data-testid="fleet-panel" style={{ display: "grid", gap: 14 }}>
      <div className="surface" style={{
        padding: 18, borderRadius: 14,
        background: "linear-gradient(135deg, rgba(14,165,233,.08), var(--bg-surface))",
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: "linear-gradient(135deg, #0ea5e9, #4f46e5)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 14px rgba(14,165,233,.35)",
        }}>
          <Car size={22} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800,
                       letterSpacing: "-0.02em" }}>
            Frota de Veículos
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            Cadastro · Vistorias semanais · Transferências · Combustível
          </div>
        </div>
        {kpis && (
          <div style={{ display: "flex", gap: 8 }}>
            <Pill color="#16a34a"
                   label={`${kpis.vehicles.active} ativos`} />
            <Pill color="#f59e0b"
                   label={`${kpis.collaborators.missing_vehicle} sem veículo`} />
            <Pill color="#0ea5e9"
                   label={`${kpis.inspections_week.pct_done}% vistorias semana`} />
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="surface" style={{
        padding: 4, borderRadius: 10,
        display: "inline-flex", gap: 4, flexWrap: "wrap",
      }}>
        {[
          { id: "vehicles", label: "Veículos", icon: Car },
          { id: "inspections", label: "Vistorias", icon: Camera },
          { id: "transfers", label: "Romaneio", icon: ArrowRightLeft },
          { id: "fuel", label: "Combustível", icon: Fuel },
          { id: "odometer", label: "Odômetro", icon: Activity },
          { id: "trails", label: "Trajetos", icon: Route },
          { id: "kpis", label: "KPIs", icon: Activity },
        ].map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
                  data-testid={`fleet-tab-${t.id}`}
                  style={{
                    padding: "9px 16px", borderRadius: 7, border: 0,
                    background: tab === t.id
                      ? "linear-gradient(135deg,#0ea5e9,#4f46e5)"
                      : "transparent",
                    color: tab === t.id ? "#fff" : "var(--text-secondary)",
                    fontSize: 12, fontWeight: 700, cursor: "pointer",
                    display: "inline-flex", alignItems: "center", gap: 6,
                  }}>
            <t.icon size={13} /> {t.label}
          </button>
        ))}
      </div>

      {tab === "vehicles" && <VehiclesTab />}
      {tab === "inspections" && <InspectionsTab />}
      {tab === "transfers" && <TransfersTab />}
      {tab === "fuel" && <FuelTab />}
      {tab === "odometer" && <OdometerTab />}
      {tab === "trails" && <FleetTrailAuditPanel />}
      {tab === "kpis" && <KpisTab kpis={kpis} />}
    </div>
  );
}

function Pill({ color, label }) {
  return (
    <span style={{
      padding: "5px 11px", borderRadius: 999,
      background: `${color}18`, color, fontSize: 11, fontWeight: 800,
    }}>{label}</span>
  );
}

/* === Veículos =============================================== */
function VehiclesTab() {
  const [items, setItems] = useState([]);
  const [collabs, setCollabs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null);
  const [detail, setDetail] = useState(null);  // veículo selecionado para Ficha

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, c] = await Promise.all([
        api.fleetVehicleList(),
        api.listCollaborators().catch(() => []),
      ]);
      setItems(r.items || []);
      setCollabs(Array.isArray(c) ? c : (c.items || []));
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const filtered = items.filter((v) => !search.trim() ||
    (v.placa || "").toLowerCase().includes(search.toLowerCase()) ||
    (v.modelo || "").toLowerCase().includes(search.toLowerCase()) ||
    (v.current_collaborator_name || "").toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="surface" style={{ padding: 16, borderRadius: 12 }}>
      <div style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "center" }}>
        <div style={{ position: "relative", flex: 1 }}>
          <Search size={13} style={{ position: "absolute", left: 10, top: "50%",
                                       transform: "translateY(-50%)",
                                       color: "var(--text-muted)" }} />
          <input className="input"
                  placeholder="Buscar placa, modelo ou responsável..."
                  value={search} onChange={(e) => setSearch(e.target.value)}
                  data-testid="fleet-search"
                  style={{ paddingLeft: 30, width: "100%" }} />
        </div>
        <button className="btn btn-ghost btn-sm" onClick={load}>
          <RefreshCw size={13} />
        </button>
        <button className="btn btn-primary btn-sm"
                onClick={() => setEditing({})}
                data-testid="fleet-vehicle-new">
          <Plus size={13} /> Novo veículo
        </button>
      </div>

      {loading ? (
        <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>
          Carregando...
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>
          {items.length === 0
            ? "Nenhum veículo cadastrado. Clique em 'Novo veículo'."
            : "Nenhum veículo bate com a busca."}
        </div>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {filtered.map((v) => (
            <VehicleRow key={v.id} v={v}
                         onOpen={() => setDetail(v)} />
          ))}
        </div>
      )}

      {detail && (
        <VehicleDetailModal vehicle={detail}
          collaborators={collabs}
          onClose={() => setDetail(null)}
          onEdit={() => { setEditing(detail); setDetail(null); }}
          onReload={load} />
      )}

      {editing && (
        <VehicleEditorModal vehicle={editing}
          collaborators={collabs}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}
    </div>
  );
}

function VehicleRow({ v, onOpen }) {
  const sColor = {
    ativo: "#16a34a", inativo: "#94a3b8",
    manutencao: "#f59e0b", transferido: "#0ea5e9",
  }[v.status] || "#94a3b8";
  return (
    <button onClick={onOpen} className="surface"
            data-testid={`vehicle-${v.id}`}
            style={{
              textAlign: "left", padding: "12px 14px",
              borderRadius: 10, cursor: "pointer", width: "100%",
              border: "1px solid var(--border-default)",
              display: "grid",
              gridTemplateColumns: "auto 1fr auto auto",
              gap: 14, alignItems: "center",
            }}>
      <div style={{
        width: 36, height: 36, borderRadius: 10,
        background: `${sColor}22`, color: sColor,
        display: "grid", placeItems: "center",
      }}>
        <Car size={18} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <strong style={{ fontSize: 14, fontFamily: "ui-monospace,monospace",
                            letterSpacing: 1 }}>
            {v.placa}
          </strong>
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
            {v.marca} {v.modelo} {v.ano && `· ${v.ano}`}
          </span>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
          {v.current_collaborator_name
            ? <>{v.current_collaborator_name}</>
            : "Sem responsável"}{" "}
          {v.km_atual ? <>· {v.km_atual.toLocaleString("pt-BR")} km</> : null}
        </div>
      </div>
      <span style={{
        padding: "3px 10px", borderRadius: 999,
        background: `${sColor}22`, color: sColor,
        fontSize: 10, fontWeight: 800,
        textTransform: "uppercase", letterSpacing: 0.5,
      }}>{v.status}</span>
      <span style={{ color: "var(--text-muted)" }}>›</span>
    </button>
  );
}

function VehicleDetailModal({ vehicle, collaborators, onClose, onEdit, onReload }) {
  const [kpis, setKpis] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [assigning, setAssigning] = useState(false);
  const [newCollab, setNewCollab] = useState("");
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.fleetVehicleKpis(vehicle.id);
      setKpis(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }, [vehicle.id]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function doAssign() {
    try {
      await api.fleetVehicleAssign(vehicle.id, newCollab);
      setAssigning(false); setNewCollab("");
      await load();
      onReload && onReload();
    } catch (e) { alert(e?.response?.data?.detail || e.message); }
  }

  async function doDelete() {
    const placa = vehicle.placa || "este veículo";
    if (!window.confirm(`Tem certeza que deseja APAGAR o veículo "${placa}"?\n\nIsso só será permitido se ele não tiver histórico (vistorias/combustível/romaneios). Para preservar auditoria, prefira marcar como 'inativo'.`)) return;
    setDeleting(true);
    try {
      await api.fleetVehicleDelete(vehicle.id);
      onReload && onReload();
      onClose();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
    setDeleting(false);
  }

  const v = kpis?.vehicle || vehicle;
  const insp = kpis?.inspections;
  const fuel = kpis?.fuel;
  const txs = kpis?.transfers;
  const km = kpis?.km;

  function scoreColor(s) {
    if (s == null) return "#94a3b8";
    if (s >= 90) return "#10b981";
    if (s >= 70) return "#3b82f6";
    if (s >= 50) return "#f59e0b";
    return "#dc2626";
  }
  function ptBr(d) {
    if (!d) return "—";
    try { return new Date(d).toLocaleDateString("pt-BR"); }
    catch { return d.slice(0, 10); }
  }

  return (
    <div data-testid="vehicle-detail-modal" onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
        zIndex: 1100, display: "grid", placeItems: "center", padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "#fff", borderRadius: 14, padding: 0,
        width: "min(96vw, 900px)", maxHeight: "94vh", overflow: "hidden",
        display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{
          background: "linear-gradient(135deg, #0ea5e9, #4f46e5)",
          color: "white", padding: "16px 22px",
          display: "flex", alignItems: "center", gap: 14,
        }}>
          <div style={{
            width: 50, height: 50, borderRadius: 12,
            background: "rgba(255,255,255,0.2)",
            display: "grid", placeItems: "center",
          }}>
            <Car size={26} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 22, fontWeight: 800, fontFamily: "ui-monospace,monospace",
                            letterSpacing: 1.2 }}>
              {v.placa}
            </div>
            <div style={{ fontSize: 12, opacity: 0.9, marginTop: 2 }}>
              {v.marca || ""} {v.modelo || ""} {v.ano && `· ${v.ano}`}
              {v.cor && ` · ${v.cor}`}
              {" · "}<span style={{
                background: "rgba(255,255,255,0.25)", padding: "2px 8px",
                borderRadius: 999, fontWeight: 700, fontSize: 10,
                letterSpacing: 0.5, textTransform: "uppercase",
              }}>{v.status}</span>
            </div>
          </div>
          <button data-testid="veh-detail-edit-btn" onClick={onEdit}
            style={{
              background: "rgba(255,255,255,0.2)", border: "1px solid rgba(255,255,255,0.4)",
              color: "white", borderRadius: 8, padding: "8px 14px",
              fontSize: 12, fontWeight: 700, cursor: "pointer",
            }}>
            Editar
          </button>
          <button data-testid="veh-detail-delete-btn" onClick={doDelete}
            disabled={deleting}
            title="Apagar este veículo (só se não tiver histórico)"
            style={{
              background: "rgba(220,38,38,0.25)", border: "1px solid rgba(255,255,255,0.4)",
              color: "white", borderRadius: 8, padding: "8px 12px",
              fontSize: 12, fontWeight: 700, cursor: deleting ? "wait" : "pointer",
              display: "inline-flex", alignItems: "center", gap: 5,
            }}>
            <Trash2 size={13} /> {deleting ? "Apagando…" : "Apagar"}
          </button>
          <button data-testid="veh-detail-close-btn" onClick={onClose}
            style={{ background: "transparent", border: "none", color: "white",
                       cursor: "pointer", fontSize: 24, lineHeight: 1, padding: "0 6px" }}>
            ×
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: 18, overflowY: "auto", flex: 1 }}>
          {busy && <div style={{ padding: 30, textAlign: "center", color: "#64748b" }}>Carregando KPIs…</div>}
          {err && <div style={{ background: "#fee2e2", color: "#991b1b",
                                  padding: 10, borderRadius: 8, marginBottom: 12 }}>{err}</div>}

          {kpis && (
            <>
              {/* Responsável atual */}
              <div style={{ background: "#f1f5f9", borderRadius: 10, padding: 12,
                              marginBottom: 14, display: "flex", alignItems: "center",
                              gap: 12, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ fontSize: 11, color: "#475569", fontWeight: 700,
                                  textTransform: "uppercase", letterSpacing: 0.4 }}>
                    Responsável atual
                  </div>
                  <div style={{ fontSize: 15, fontWeight: 700, marginTop: 2, color: "#0f172a" }}>
                    {v.current_collaborator_name
                      ? <>{v.current_collaborator_name}{v.current_collaborator_phone && <span style={{
                          fontSize: 12, color: "#64748b", fontWeight: 500, marginLeft: 8,
                        }}>· {v.current_collaborator_phone}</span>}</>
                      : <span style={{ color: "#dc2626" }}>Sem responsável</span>}
                  </div>
                </div>
                <button data-testid="veh-detail-assign-btn"
                  onClick={() => setAssigning(!assigning)}
                  className="btn btn-ghost btn-sm">
                  {v.current_collaborator_id ? "Trocar responsável" : "Vincular técnico"}
                </button>
              </div>

              {assigning && (
                <div style={{ background: "#fff7ed", border: "1px solid #fed7aa",
                                borderRadius: 10, padding: 12, marginBottom: 14,
                                display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <select className="input" style={{ flex: 1, minWidth: 200 }}
                    value={newCollab} onChange={(e) => setNewCollab(e.target.value)}
                    data-testid="veh-detail-assign-select">
                    <option value="">— Selecione —</option>
                    {(collaborators || [])
                      .filter((c) => c.requires_vehicle)
                      .map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                  <button data-testid="veh-detail-assign-save"
                    className="btn btn-primary btn-sm"
                    onClick={doAssign} disabled={!newCollab}>
                    Vincular
                  </button>
                  <button className="btn btn-ghost btn-sm"
                    onClick={() => { setAssigning(false); setNewCollab(""); }}>
                    Cancelar
                  </button>
                </div>
              )}

              {/* KPI Grid */}
              <div style={{ display: "grid", gap: 10,
                              gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
                              marginBottom: 18 }}>
                <DetailKpi testid="vk-km" label="KM atual"
                  value={(km?.current ?? 0).toLocaleString("pt-BR")}
                  sub={km?.delta_last_month != null
                    ? `+${km.delta_last_month.toLocaleString("pt-BR")} km no mês`
                    : null}
                  color="#0ea5e9" />
                <DetailKpi testid="vk-insp-pct" label="Vistorias OK"
                  value={`${insp.approved}/${insp.total}`}
                  sub={`${insp.pct_approved}% aprovadas`}
                  color={insp.pct_approved >= 80 ? "#10b981"
                          : insp.pct_approved >= 50 ? "#f59e0b" : "#dc2626"} />
                <DetailKpi testid="vk-insp-score" label="Score IA médio"
                  value={insp.avg_ai_score ?? "—"}
                  sub={insp.rejected ? `${insp.rejected} recusada(s)` : null}
                  color={scoreColor(insp.avg_ai_score)} />
                <DetailKpi testid="vk-fuel-month" label="Combustível mês"
                  value={`R$ ${fuel.month_total.toFixed(2)}`}
                  sub={`Ano: R$ ${fuel.year_total.toFixed(2)}`}
                  color="#f59e0b" />
                <DetailKpi testid="vk-fuel-os" label="Custo / OS (ano)"
                  value={fuel.avg_per_os != null ? `R$ ${fuel.avg_per_os}` : "—"}
                  sub={fuel.total_os ? `${fuel.total_os} OS executadas` : null}
                  color="#7c3aed" />
                <DetailKpi testid="vk-tx" label="Transferências"
                  value={txs.total}
                  sub={txs.pending ? `${txs.pending} pendente(s)` : "Nenhuma pendente"}
                  color={txs.pending ? "#f59e0b" : "#64748b"} />
              </div>

              {/* Última vistoria */}
              {insp.last && (
                <div style={{ marginBottom: 14 }}>
                  <h4 style={{ margin: "0 0 8px", fontSize: 12, fontWeight: 800,
                                color: "#475569", textTransform: "uppercase",
                                letterSpacing: 0.5 }}>
                    Última vistoria
                  </h4>
                  <div data-testid="vk-last-insp"
                    style={{ background: "white", border: "1px solid #e2e8f0",
                               borderRadius: 10, padding: 12,
                               display: "flex", gap: 12, alignItems: "center",
                               flexWrap: "wrap" }}>
                    <div style={{ fontFamily: "ui-monospace,monospace",
                                    color: "#64748b", fontSize: 12 }}>
                      {insp.last.week_ref}
                    </div>
                    <span style={{
                      padding: "3px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800,
                      background: insp.last.status === "approved" ? "#dcfce7"
                        : insp.last.status === "rejected" ? "#fee2e2" : "#fef3c7",
                      color: insp.last.status === "approved" ? "#15803d"
                        : insp.last.status === "rejected" ? "#991b1b" : "#a16207",
                    }}>{insp.last.status}</span>
                    {insp.last.ai_score != null && (
                      <span style={{ fontSize: 13, fontWeight: 700,
                                       color: scoreColor(insp.last.ai_score) }}>
                        IA: {insp.last.ai_score}/100
                      </span>
                    )}
                    <span style={{ flex: 1, textAlign: "right", color: "#64748b",
                                     fontSize: 12 }}>
                      {ptBr(insp.last.requested_at)}
                    </span>
                  </div>
                </div>
              )}

              {/* Histórico de vistorias */}
              {insp.history.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <h4 style={{ margin: "0 0 8px", fontSize: 12, fontWeight: 800,
                                color: "#475569", textTransform: "uppercase",
                                letterSpacing: 0.5 }}>
                    Histórico ({insp.history.length} vistoria(s))
                  </h4>
                  <div style={{ display: "grid", gap: 4 }}>
                    {insp.history.map((h) => (
                      <div key={h.id} style={{
                        padding: "8px 10px", borderRadius: 6,
                        background: "#f8fafc", border: "1px solid #e2e8f0",
                        display: "grid",
                        gridTemplateColumns: "80px 90px 60px 1fr auto",
                        gap: 10, alignItems: "center", fontSize: 12,
                      }}>
                        <span style={{ fontFamily: "ui-monospace,monospace",
                                          color: "#64748b" }}>{h.week_ref}</span>
                        <span style={{
                          padding: "2px 6px", borderRadius: 999, fontSize: 10,
                          fontWeight: 800, textAlign: "center",
                          background: h.status === "approved" ? "#dcfce7"
                            : h.status === "rejected" ? "#fee2e2" : "#fef3c7",
                          color: h.status === "approved" ? "#15803d"
                            : h.status === "rejected" ? "#991b1b" : "#a16207",
                        }}>{h.status}</span>
                        <span style={{ fontWeight: 700,
                                          color: scoreColor(h.ai_score) }}>
                          {h.ai_score ?? "—"}
                        </span>
                        <span style={{ color: "#64748b" }}>
                          {h.km_informado ? `${h.km_informado.toLocaleString("pt-BR")} km` : "—"}
                        </span>
                        <span style={{ color: "#94a3b8" }}>
                          {ptBr(h.requested_at)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Evolução combustível */}
              {fuel.by_month.length > 0 && (
                <div>
                  <h4 style={{ margin: "0 0 8px", fontSize: 12, fontWeight: 800,
                                color: "#475569", textTransform: "uppercase",
                                letterSpacing: 0.5 }}>
                    Combustível por mês
                  </h4>
                  <FuelMiniChart data={fuel.by_month} />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function DetailKpi({ testid, label, value, sub, color }) {
  return (
    <div data-testid={testid} style={{
      background: "white", border: "1px solid #e2e8f0",
      borderRadius: 12, padding: 12,
      borderTop: `4px solid ${color}`,
    }}>
      <div style={{ fontSize: 10, color: "#64748b", fontWeight: 800,
                    textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, color,
                    marginTop: 4, letterSpacing: "-0.02em" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function FuelMiniChart({ data }) {
  if (!data || data.length === 0) return null;
  const max = Math.max(...data.map((d) => d.valor)) || 1;
  return (
    <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0",
                    borderRadius: 10, padding: 12,
                    display: "flex", alignItems: "flex-end", gap: 4,
                    height: 110 }}>
      {data.map((d) => {
        const h = Math.max(8, (d.valor / max) * 80);
        return (
          <div key={d.month} title={`${d.month}: R$ ${d.valor.toFixed(2)}`}
            style={{ flex: 1, display: "flex", flexDirection: "column",
                       alignItems: "center", gap: 4 }}>
            <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700 }}>
              R${d.valor.toFixed(0)}
            </div>
            <div style={{ width: "100%", height: h,
                            background: "linear-gradient(180deg,#0ea5e9,#0369a1)",
                            borderRadius: "4px 4px 0 0" }} />
            <div style={{ fontSize: 9, color: "#94a3b8" }}>
              {d.month.slice(5)}
            </div>
          </div>
        );
      })}
    </div>
  );
}



function VehicleEditorModal({ vehicle, collaborators, onClose, onSaved }) {
  const isNew = !vehicle.id;
  const [form, setForm] = useState({
    placa: "", marca: "", modelo: "", cor: "", ano: "",
    tipo: "carro", km_atual: 0, current_collaborator_id: "",
    status: "ativo", weekly_inspection_required: true,
    ai_validation_required: true, observacoes: "",
    ownership: "empresa",
    ...vehicle,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k, v) => setForm({ ...form, [k]: v });
  const save = async () => {
    if (!form.placa) { setErr("Placa é obrigatória."); return; }
    setBusy(true); setErr("");
    try {
      const payload = { ...form, ano: form.ano ? Number(form.ano) : null,
                         km_atual: Number(form.km_atual || 0) };
      if (isNew) await api.fleetVehicleCreate(payload);
      else await api.fleetVehicleUpdate(vehicle.id, payload);
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
      zIndex: 1100, display: "grid", placeItems: "center", padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "#fff", borderRadius: 12, padding: 22,
        width: "min(94vw, 560px)", maxHeight: "92vh", overflowY: "auto",
      }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                      marginBottom: 14 }}>
          {isNew ? "Novo veículo" : `Editar — ${vehicle.placa}`}
        </h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
                       gap: 10 }}>
          <Field label="Placa *">
            <input className="input" value={form.placa}
                    data-testid="veh-placa"
                    onChange={(e) => set("placa", e.target.value.toUpperCase())}
                    placeholder="ABC1D23" />
          </Field>
          <Field label="Marca">
            <input className="input" value={form.marca || ""}
                    onChange={(e) => set("marca", e.target.value)} />
          </Field>
          <Field label="Modelo">
            <input className="input" value={form.modelo || ""}
                    onChange={(e) => set("modelo", e.target.value)} />
          </Field>
          <Field label="Cor">
            <input className="input" value={form.cor || ""}
                    onChange={(e) => set("cor", e.target.value)} />
          </Field>
          <Field label="Ano">
            <input className="input" type="number" value={form.ano || ""}
                    onChange={(e) => set("ano", e.target.value)} />
          </Field>
          <Field label="Tipo">
            <select className="input" value={form.tipo}
                      onChange={(e) => set("tipo", e.target.value)}>
              <option value="carro">Carro</option>
              <option value="moto">Moto</option>
              <option value="utilitario">Utilitário</option>
              <option value="van">Van</option>
            </select>
          </Field>
          <Field label="KM atual">
            <input className="input" type="number"
                    value={form.km_atual || 0}
                    onChange={(e) => set("km_atual", e.target.value)} />
          </Field>
          <Field label="Status">
            <select className="input" value={form.status}
                      data-testid="veh-status"
                      onChange={(e) => set("status", e.target.value)}>
              <option value="ativo">Ativo</option>
              <option value="inativo">Inativo</option>
              <option value="manutencao">Manutenção</option>
              <option value="transferido">Transferido</option>
            </select>
          </Field>
          <Field label="Origem">
            <select className="input" value={form.ownership}
                      onChange={(e) => set("ownership", e.target.value)}>
              <option value="empresa">Da empresa</option>
              <option value="proprio">Próprio do técnico</option>
            </select>
          </Field>
        </div>

        <Field label="Responsável atual">
          <select className="input" value={form.current_collaborator_id || ""}
                    data-testid="veh-collab"
                    onChange={(e) => set("current_collaborator_id",
                      e.target.value || null)}>
            <option value="">— Nenhum —</option>
            {collaborators.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </Field>

        <div style={{ display: "flex", gap: 16, marginTop: 12 }}>
          <CheckRow label="Vistoria semanal obrigatória"
            checked={form.weekly_inspection_required}
            onChange={(v) => set("weekly_inspection_required", v)} />
          <CheckRow label="Validar com IA"
            checked={form.ai_validation_required}
            onChange={(v) => set("ai_validation_required", v)} />
        </div>

        <Field label="Observações">
          <textarea className="input" rows={2}
                     value={form.observacoes || ""}
                     onChange={(e) => set("observacoes", e.target.value)} />
        </Field>

        {err && (
          <div style={{
            padding: 10, borderRadius: 7, marginTop: 8,
            background: "#fef2f2", color: "#991b1b", fontSize: 12,
            border: "1px solid #fecaca",
          }}>{err}</div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                        marginTop: 16 }}>
          <button onClick={onClose} className="btn btn-ghost btn-sm">
            Cancelar
          </button>
          <button onClick={save} disabled={busy}
                  data-testid="veh-save"
                  className="btn btn-primary btn-sm">
            {busy ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* === Vistorias =============================================== */
function InspectionsTab() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);
  const reload = useCallback(() => {
    setLoading(true);
    api.fleetInspectionList().then((r) => setItems(r.items || []))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { reload(); }, [reload]);

  async function approve(id) {
    if (!window.confirm("Aprovar esta vistoria manualmente?")) return;
    try {
      await api.fleetInspectionManualApprove(id);
      setDetail(null);
      reload();
    } catch (e) { alert(e?.response?.data?.detail || e.message); }
  }
  async function doDelete(id) {
    if (!window.confirm("Apagar esta vistoria? Isso também removerá a bolha 'frota_alerta' relacionada na Lousa, se houver.")) return;
    try {
      await api.fleetInspectionDelete(id);
      setDetail(null);
      reload();
    } catch (e) { alert(e?.response?.data?.detail || e.message); }
  }
  async function openDetail(id) {
    const d = await api.fleetInspectionGet(id);
    setDetail(d);
  }

  return (
    <div className="surface" style={{ padding: 16, borderRadius: 12 }}>
      <h3 style={{ margin: 0, fontSize: 14, fontWeight: 800, marginBottom: 10 }}>
        Vistorias Semanais
      </h3>
      {loading ? "Carregando..."
        : items.length === 0 ? (
          <div style={{ padding: 20, textAlign: "center",
                          color: "var(--text-muted)", fontSize: 12 }}>
            Nenhuma vistoria registrada ainda. Vistorias aparecem aqui
            quando os técnicos completam a captura semanal de fotos.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 6 }}>
            {items.map((i) => (
              <button key={i.id}
                data-testid={`insp-row-${i.id}`}
                onClick={() => openDetail(i.id)}
                style={{
                  padding: 10, borderRadius: 8, textAlign: "left",
                  border: "1px solid var(--border-default)",
                  background: "transparent", cursor: "pointer",
                  display: "grid",
                  gridTemplateColumns: "auto 1fr auto auto auto",
                  gap: 10, alignItems: "center",
                }}>
                <div style={{ fontSize: 11, fontFamily: "ui-monospace,monospace",
                                color: "var(--text-muted)" }}>
                  {i.week_ref}
                </div>
                <div style={{ fontSize: 12 }}>
                  Colab: {i.collaborator_id?.slice(-8)} · Veículo: {i.vehicle_id?.slice(-8)}
                </div>
                <span style={{
                  padding: "3px 8px", borderRadius: 999,
                  fontSize: 10, fontWeight: 800,
                  background:
                    i.status === "approved" ? "#dcfce7"
                      : i.status === "rejected" ? "#fee2e2"
                      : i.status === "submitted" ? "#fef3c7"
                      : "#f1f5f9",
                  color:
                    i.status === "approved" ? "#15803d"
                      : i.status === "rejected" ? "#b91c1c"
                      : i.status === "submitted" ? "#a16207"
                      : "#475569",
                }}>{i.status}</span>
                {i.ai_score && (
                  <span style={{ fontSize: 11, fontWeight: 800 }}>
                    IA: {i.ai_score}/100
                  </span>
                )}
                <span style={{ color: "var(--text-muted)" }}>›</span>
              </button>
            ))}
          </div>
        )}
      {detail && (
        <InspectionDetailModal insp={detail}
          onClose={() => setDetail(null)}
          onApprove={() => approve(detail.id)}
          onDelete={() => doDelete(detail.id)} />
      )}
    </div>
  );
}

function InspectionDetailModal({ insp, onClose, onApprove, onDelete }) {
  const photos = insp.photos || {};
  const [zoomPhoto, setZoomPhoto] = useState(null);

  // ESC fecha o lightbox; se já fechado, fecha o modal
  useEffect(() => {
    function onKey(e) {
      if (e.key !== "Escape") return;
      if (zoomPhoto) setZoomPhoto(null);
      else onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomPhoto, onClose]);
  return (
    <div data-testid="insp-detail-modal" onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
        zIndex: 1100, display: "grid", placeItems: "center", padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "#fff", borderRadius: 12, padding: 22,
        width: "min(94vw, 760px)", maxHeight: "92vh", overflowY: "auto",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800 }}>
            Vistoria · {insp.week_ref} · score {insp.ai_score ?? "—"}
          </h3>
          <button data-testid="insp-close-btn" onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer" }}>
            <X size={20} />
          </button>
        </div>
        {insp.ai_alerts?.length > 0 && (
          <div style={{ background: "#fef2f2", border: "1px solid #fecaca",
                          padding: 10, borderRadius: 8, marginBottom: 12,
                          fontSize: 12, color: "#991b1b" }}>
            <strong>Alertas IA:</strong>
            <ul style={{ margin: "6px 0 0 18px" }}>
              {insp.ai_alerts.map((a, idx) => (
                <li key={idx}>{a.type}: {a.msg || a.severity}</li>
              ))}
            </ul>
          </div>
        )}
        {insp.ai_comparacao && (
          <div style={{ background: "#f0fdf4", padding: 10, borderRadius: 8,
                          marginBottom: 12, fontSize: 12, color: "#166534" }}>
            <strong>Comparação:</strong> {insp.ai_comparacao}
          </div>
        )}
        <div style={{ display: "grid", gap: 8,
                        gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
          {["km", "frente", "traseira", "lat_dir", "lat_esq"].map((pos) => {
            const ph = photos[pos];
            return (
              <div key={pos} style={{
                background: "#f8fafc", borderRadius: 8, padding: 8, textAlign: "center",
              }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: "#475569",
                                marginBottom: 4, textTransform: "uppercase" }}>
                  {pos}{pos === "km" && insp.km_informado ? ` · ${insp.km_informado}` : ""}
                </div>
                {ph ? (
                  <img src={ph.data_url} alt={pos}
                    data-testid={`insp-photo-${pos}`}
                    onClick={(e) => { e.stopPropagation(); setZoomPhoto({ src: ph.data_url, label: pos }); }}
                    style={{ width: "100%", borderRadius: 6, objectFit: "cover",
                              maxHeight: 130, cursor: "zoom-in",
                              transition: "transform .15s",
                            }}
                    onMouseOver={(e) => { e.currentTarget.style.transform = "scale(1.03)"; }}
                    onMouseOut={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
                  />
                ) : (
                  <div style={{ color: "#94a3b8", fontSize: 11, padding: 20 }}>
                    Sem foto
                  </div>
                )}
              </div>
            );
          })}
        </div>
        {insp.status !== "approved" && (
          <button data-testid="insp-approve-btn" onClick={onApprove}
            style={{ marginTop: 14, marginRight: 8, padding: "10px 18px", background: "#10b981",
                       color: "white", border: "none", borderRadius: 8,
                       fontWeight: 700, cursor: "pointer" }}>
            Aprovar manualmente
          </button>
        )}
        <button data-testid="insp-delete-btn" onClick={onDelete}
          title="Apagar esta vistoria"
          style={{ marginTop: 14, padding: "10px 16px", background: "#fef2f2",
                     color: "#b91c1c", border: "1px solid #fecaca",
                     borderRadius: 8, fontWeight: 700, cursor: "pointer",
                     display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Trash2 size={14} /> Apagar vistoria
        </button>
      </div>
      {zoomPhoto && (
        <div
          data-testid="insp-photo-zoom"
          onClick={(e) => { e.stopPropagation(); setZoomPhoto(null); }}
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.92)",
            zIndex: 1200, display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", padding: 20,
            cursor: "zoom-out",
          }}>
          <div style={{
            position: "absolute", top: 16, left: 20,
            color: "white", fontSize: 14, fontWeight: 700,
            background: "rgba(0,0,0,0.5)", padding: "6px 14px",
            borderRadius: 999, letterSpacing: 0.5, textTransform: "uppercase",
          }}>
            {zoomPhoto.label}
          </div>
          <button
            data-testid="insp-photo-zoom-close"
            onClick={(e) => { e.stopPropagation(); setZoomPhoto(null); }}
            style={{
              position: "absolute", top: 16, right: 20,
              background: "rgba(255,255,255,0.15)", color: "white",
              border: "1px solid rgba(255,255,255,0.3)",
              borderRadius: "50%", width: 40, height: 40,
              fontSize: 22, cursor: "pointer", display: "grid",
              placeItems: "center",
            }}>
            ×
          </button>
          <img src={zoomPhoto.src} alt={zoomPhoto.label}
            onClick={(e) => e.stopPropagation()}
            style={{
              maxWidth: "92vw", maxHeight: "86vh", objectFit: "contain",
              borderRadius: 8, boxShadow: "0 10px 40px rgba(0,0,0,0.6)",
              cursor: "default",
            }} />
          <div style={{
            position: "absolute", bottom: 16, color: "rgba(255,255,255,0.7)",
            fontSize: 11,
          }}>
            Toque fora para fechar · ESC
          </div>
        </div>
      )}
    </div>
  );
}

/* === Romaneio =============================================== */
function TransfersTab() {
  const [items, setItems] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [collabs, setCollabs] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    vehicle_id: "", to_collaborator_id: "", km_transfer: 0, observacoes: "",
  });
  const [signingTx, setSigningTx] = useState(null);
  const [err, setErr] = useState("");

  const reload = useCallback(async () => {
    const [r, v, c] = await Promise.all([
      api.fleetTransferList(),
      api.fleetVehicleList(),
      api.listCollaborators().catch(() => []),
    ]);
    setItems(r.items || []);
    setVehicles(v.items || []);
    setCollabs(Array.isArray(c) ? c : []);
  }, []);
  useEffect(() => { reload(); }, [reload]);

  async function create() {
    setErr("");
    try {
      await api.fleetTransferCreate({
        ...form, km_transfer: parseInt(form.km_transfer) || 0,
      });
      setShowForm(false);
      setForm({ vehicle_id: "", to_collaborator_id: "", km_transfer: 0, observacoes: "" });
      reload();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }
  async function approve(id) {
    if (!window.confirm("Aprovar esta transferência?")) return;
    try { await api.fleetTransferApprove(id); reload(); }
    catch (e) { alert(e?.response?.data?.detail || e.message); }
  }
  async function handleSign(signature_data_url) {
    if (!signingTx) return;
    try {
      await api.fleetTransferSign(signingTx.id, { signature_data_url });
      setSigningTx(null);
      reload();
    } catch (e) { alert(e?.response?.data?.detail || e.message); }
  }

  async function doDelete(t) {
    if (!window.confirm(
      `Apagar romaneio do veículo ${t.vehicle_placa || ""}?` +
      (t.status === "accepted" ? "\n\nO técnico já assinou — tem certeza?" : "")
    )) return;
    try {
      await api.fleetTransferDelete(t.id);
      reload();
    } catch (e) { alert(e?.response?.data?.detail || e.message); }
  }

  async function openPdf(id) {
    try {
      const blob = await api.fleetTransferPdfBlob(id);
      const url = window.URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => window.URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      alert("Erro ao gerar PDF: " + (e?.response?.data?.detail || e.message));
    }
  }

  return (
    <div className="surface" style={{ padding: 16, borderRadius: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                      marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 800 }}>
          Romaneio de Transferência
        </h3>
        <button data-testid="tx-new-btn" className="btn btn-primary btn-sm"
          onClick={() => setShowForm(!showForm)}>
          <Plus size={13} /> Nova
        </button>
      </div>

      {showForm && (
        <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0",
                        borderRadius: 10, padding: 12, marginBottom: 14,
                        display: "grid", gap: 8,
                        gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          <select data-testid="tx-vehicle" className="input"
            value={form.vehicle_id}
            onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })}>
            <option value="">— Veículo —</option>
            {vehicles.map((v) =>
              <option key={v.id} value={v.id}>{v.placa} ({v.modelo})</option>)}
          </select>
          <select data-testid="tx-to-collab" className="input"
            value={form.to_collaborator_id}
            onChange={(e) => setForm({ ...form, to_collaborator_id: e.target.value })}>
            <option value="">— Para colaborador —</option>
            {collabs.filter(c => c.requires_vehicle).map((c) =>
              <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <input data-testid="tx-km" className="input" type="number"
            placeholder="KM no momento" value={form.km_transfer}
            onChange={(e) => setForm({ ...form, km_transfer: e.target.value })} />
          <input data-testid="tx-obs" className="input" placeholder="Obs."
            value={form.observacoes}
            onChange={(e) => setForm({ ...form, observacoes: e.target.value })} />
          {err && <div style={{ gridColumn: "1 / -1", color: "#dc2626",
                                    fontSize: 12 }}>{err}</div>}
          <div style={{ gridColumn: "1 / -1", display: "flex", gap: 6 }}>
            <button data-testid="tx-cancel-btn" className="btn btn-ghost btn-sm"
              onClick={() => setShowForm(false)}>Cancelar</button>
            <button data-testid="tx-save-btn" className="btn btn-primary btn-sm"
              onClick={create} disabled={!form.vehicle_id || !form.to_collaborator_id}>
              Criar transferência
            </button>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <div style={{ padding: 20, textAlign: "center",
                        color: "var(--text-muted)", fontSize: 12 }}>
          Nenhum romaneio registrado.
        </div>
      ) : items.map((t) => (
        <div key={t.id} data-testid={`tx-row-${t.id}`}
          style={{ padding: 12, borderRadius: 8,
                     border: "1px solid var(--border-default)",
                     marginBottom: 6, display: "flex", alignItems: "center",
                     gap: 10, flexWrap: "wrap" }}>
          <strong style={{ fontFamily: "ui-monospace,monospace", flex: 1, minWidth: 100 }}>
            {t.vehicle_placa}
          </strong>
          <span style={{ fontSize: 11, color: "var(--text-muted)", flex: 2,
                          minWidth: 180 }}>
            {(t.from_collaborator_id || "—").slice(-8)} → {t.to_collaborator_id?.slice(-8)}
            · {t.km_transfer} km
          </span>
          <span style={{
            padding: "3px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800,
            background: t.status === "approved" ? "#dcfce7"
              : t.status === "accepted" ? "#dbeafe"
              : t.status === "pending" ? "#fef3c7" : "#fee2e2",
            color: t.status === "approved" ? "#15803d"
              : t.status === "accepted" ? "#1e40af"
              : t.status === "pending" ? "#a16207" : "#991b1b",
          }}>{t.status}</span>
          <button data-testid={`tx-pdf-${t.id}`}
            className="btn btn-ghost btn-sm"
            title="Abrir romaneio em PDF para impressão e assinatura física"
            onClick={() => openPdf(t.id)}>
            Imprimir
          </button>
          {t.status === "pending" && (
            <button data-testid={`tx-sign-${t.id}`}
              className="btn btn-ghost btn-sm"
              onClick={() => setSigningTx(t)}>
              Assinar
            </button>
          )}
          {t.status === "accepted" && (
            <button data-testid={`tx-approve-${t.id}`}
              className="btn btn-primary btn-sm"
              onClick={() => approve(t.id)}>
              Aprovar
            </button>
          )}
          {t.status !== "approved" && (
            <button data-testid={`tx-delete-${t.id}`}
              onClick={() => doDelete(t)}
              title="Apagar romaneio"
              style={{
                background: "transparent", border: "1px solid #fecaca",
                color: "#b91c1c", borderRadius: 6,
                padding: "5px 9px", cursor: "pointer",
                display: "inline-flex", alignItems: "center", gap: 4,
                fontSize: 11, fontWeight: 700,
              }}>
              <Trash2 size={11} />
            </button>
          )}
        </div>
      ))}

      {signingTx && (
        <SignatureCanvas
          title={`Assinatura aceite — ${signingTx.vehicle_placa}`}
          onConfirm={handleSign}
          onCancel={() => setSigningTx(null)} />
      )}
    </div>
  );
}

/* === Combustível =============================================== */
function FuelTab() {
  const [items, setItems] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [collabs, setCollabs] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    vehicle_id: "", collaborator_id: "",
    month_ref: new Date().toISOString().slice(0, 7),
    valor_total: 0, qtd_os_executadas: "",
    observacoes: "", receipt_data_url: null,
  });
  const [ocrBusy, setOcrBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [showImporter, setShowImporter] = useState(false);

  const reload = useCallback(async () => {
    const [r, v, c] = await Promise.all([
      api.fleetFuelList(),
      api.fleetVehicleList(),
      api.listCollaborators().catch(() => []),
    ]);
    setItems(r.items || []);
    setVehicles(v.items || []);
    setCollabs(Array.isArray(c) ? c : []);
  }, []);
  useEffect(() => { reload(); }, [reload]);

  async function handleReceiptFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      const dataUrl = reader.result;
      setForm((x) => ({ ...x, receipt_data_url: dataUrl }));
      setOcrBusy(true); setErr("");
      try {
        const r = await api.fleetFuelOcr(dataUrl);
        if (r.ok && r.valor_total) {
          setForm((x) => ({
            ...x,
            valor_total: r.valor_total,
            observacoes: [r.posto, r.combustivel, r.litros && `${r.litros}L`]
              .filter(Boolean).join(" · "),
          }));
        } else if (r.error) {
          setErr("OCR não conseguiu ler: " + r.error);
        }
      } catch (e) {
        setErr("OCR falhou: " + (e?.response?.data?.detail || e.message));
      }
      setOcrBusy(false);
    };
    reader.readAsDataURL(file);
  }

  async function save() {
    setBusy(true); setErr("");
    try {
      await api.fleetFuelCreate({
        ...form,
        valor_total: parseFloat(form.valor_total),
        qtd_os_executadas: form.qtd_os_executadas
          ? parseInt(form.qtd_os_executadas) : null,
        collaborator_id: form.collaborator_id || null,
      });
      setShowForm(false);
      setForm({
        vehicle_id: "", collaborator_id: "",
        month_ref: new Date().toISOString().slice(0, 7),
        valor_total: 0, qtd_os_executadas: "",
        observacoes: "", receipt_data_url: null,
      });
      reload();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setBusy(false);
  }

  return (
    <div className="surface" style={{ padding: 16, borderRadius: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                      marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 800 }}>
          Combustível
        </h3>
        <button data-testid="fuel-new-btn" className="btn btn-primary btn-sm"
          onClick={() => setShowForm(!showForm)}>
          <Plus size={13} /> Lançar
        </button>
        <button data-testid="fuel-import-ticketlog-btn"
          onClick={() => setShowImporter(true)}
          title="Importar extrato CSV exportado da plataforma TicketLog/Edenred"
          style={{
            background: "linear-gradient(135deg,#f59e0b,#d97706)",
            color: "white", border: "none", borderRadius: 8,
            padding: "6px 12px", fontSize: 12, fontWeight: 700,
            display: "inline-flex", alignItems: "center", gap: 6,
            cursor: "pointer", marginLeft: 6,
          }}>
          Importar TicketLog
        </button>
        {showImporter && (
          <TicketLogImporter
            onClose={() => setShowImporter(false)}
            onSuccess={reload} />
        )}
      </div>

      {showForm && (
        <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0",
                        borderRadius: 10, padding: 12, marginBottom: 14 }}>
          <div style={{ marginBottom: 10 }}>
            <Field label="Foto da NF do posto (OCR Claude vision)">
              <input data-testid="fuel-ocr-input" type="file"
                accept="image/*" capture="environment"
                onChange={(e) => handleReceiptFile(e.target.files?.[0])} />
            </Field>
            {ocrBusy && (
              <div style={{ color: "#0369a1", fontSize: 12, marginTop: 4,
                              display: "inline-flex", gap: 6, alignItems: "center" }}>
                <Loader2 size={12} className="animate-spin"
                  style={{ animation: "spin 1s linear infinite" }} />
                Lendo NF com IA…
              </div>
            )}
            {form.receipt_data_url && (
              <img src={form.receipt_data_url} alt="NF"
                style={{ maxWidth: 220, maxHeight: 120, marginTop: 8,
                          borderRadius: 6, border: "1px solid #e2e8f0" }} />
            )}
          </div>

          <div style={{ display: "grid", gap: 8,
                          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
            <Field label="Veículo *">
              <select data-testid="fuel-veh" className="input"
                value={form.vehicle_id}
                onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })}>
                <option value="">— Selecione —</option>
                {vehicles.map((v) =>
                  <option key={v.id} value={v.id}>{v.placa} · {v.modelo}</option>)}
              </select>
            </Field>
            <Field label="Colaborador">
              <select data-testid="fuel-collab" className="input"
                value={form.collaborator_id}
                onChange={(e) => setForm({ ...form, collaborator_id: e.target.value })}>
                <option value="">— Nenhum —</option>
                {collabs.map((c) =>
                  <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            <Field label="Mês de referência">
              <input data-testid="fuel-month" className="input" type="month"
                value={form.month_ref}
                onChange={(e) => setForm({ ...form, month_ref: e.target.value })} />
            </Field>
            <Field label="Valor total (R$) *">
              <input data-testid="fuel-valor" className="input" type="number" step="0.01"
                value={form.valor_total}
                onChange={(e) => setForm({ ...form, valor_total: e.target.value })} />
            </Field>
            <Field label="Qtd OS (vazio = auto)">
              <input data-testid="fuel-qtd" className="input" type="number"
                value={form.qtd_os_executadas}
                onChange={(e) => setForm({ ...form, qtd_os_executadas: e.target.value })} />
            </Field>
            <Field label="Observações">
              <input data-testid="fuel-obs" className="input"
                value={form.observacoes}
                onChange={(e) => setForm({ ...form, observacoes: e.target.value })} />
            </Field>
          </div>

          {err && <div style={{ color: "#dc2626", fontSize: 12, marginTop: 6 }}>{err}</div>}

          <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
            <button data-testid="fuel-cancel-btn" className="btn btn-ghost btn-sm"
              onClick={() => setShowForm(false)}>Cancelar</button>
            <button data-testid="fuel-save-btn" className="btn btn-primary btn-sm"
              onClick={save} disabled={busy || !form.vehicle_id || !form.valor_total}>
              {busy ? "Salvando…" : "Salvar"}
            </button>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <div style={{ padding: 20, textAlign: "center",
                        color: "var(--text-muted)", fontSize: 12 }}>
          Nenhum lançamento de combustível. Foto da NF dispara OCR automático.
        </div>
      ) : items.map((f) => (
        <div key={f.id} data-testid={`fuel-row-${f.id}`}
          style={{ padding: 12, borderRadius: 8,
                     border: "1px solid var(--border-default)",
                     marginBottom: 6, display: "grid",
                     gridTemplateColumns: "1fr auto auto auto",
                     gap: 10, alignItems: "center" }}>
          <div>
            <strong>{f.month_ref}</strong>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              {f.vehicle_id?.slice(-8)} · {f.qtd_os_executadas} OS executadas
              {f.observacoes && ` · ${f.observacoes}`}
            </div>
          </div>
          <span>R$ {(f.valor_total || 0).toFixed(2)}</span>
          <span style={{ fontWeight: 700 }}>
            R$ {(f.media_por_os || 0).toFixed(2)}/OS
          </span>
          <button data-testid={`fuel-delete-${f.id}`}
            onClick={async () => {
              if (!window.confirm(`Apagar lançamento de R$ ${(f.valor_total || 0).toFixed(2)} (${f.month_ref})?`)) return;
              try {
                await api.fleetFuelDelete(f.id);
                reload();
              } catch (e) { alert(e?.response?.data?.detail || e.message); }
            }}
            title="Apagar lançamento"
            style={{
              background: "transparent", border: "1px solid #fecaca",
              color: "#b91c1c", borderRadius: 6,
              padding: "5px 9px", cursor: "pointer",
              display: "inline-flex", alignItems: "center",
            }}>
            <Trash2 size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}

/* === KPIs =============================================== */
function KpisTab({ kpis }) {
  if (!kpis) return null;
  const cards = [
    { label: "Total veículos", v: kpis.vehicles.total, color: "#0ea5e9" },
    { label: "Ativos", v: kpis.vehicles.active, color: "#16a34a" },
    { label: "Em manutenção", v: kpis.vehicles.maintenance, color: "#f59e0b" },
    { label: "Colab. c/ veículo", v: kpis.collaborators.with_vehicle, color: "#7c3aed" },
    { label: "Sem veículo (req)", v: kpis.collaborators.missing_vehicle, color: "#dc2626" },
    { label: "Vistorias OK semana", v: `${kpis.inspections_week.done}/${kpis.inspections_week.expected}`, color: "#16a34a" },
    { label: "% Vistorias semana", v: `${kpis.inspections_week.pct_done}%`, color: "#0ea5e9" },
    { label: "Nota IA média", v: kpis.inspections_week.avg_ai_score ?? "—", color: "#7c3aed" },
    { label: "Transferências pendentes", v: kpis.transfers.pending, color: "#f59e0b" },
    { label: "Custo combustível mês", v: `R$ ${kpis.fuel.month_total?.toFixed(2) || 0}`, color: "#dc2626" },
    { label: "Média combustível/OS", v: kpis.fuel.avg_per_os
        ? `R$ ${kpis.fuel.avg_per_os}` : "—", color: "#0ea5e9" },
  ];
  return (
    <>
    <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))" }}>
      {cards.map((k) => (
        <div key={k.label} className="surface" style={{
          padding: 14, borderRadius: 10,
          border: `1px solid ${k.color}22`,
        }}>
          <div style={{ fontSize: 10, color: k.color, fontWeight: 800,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
            {k.label}
          </div>
          <div style={{ fontSize: 24, fontWeight: 800,
                          letterSpacing: "-0.02em", marginTop: 4 }}>
            {k.v}
          </div>
        </div>
      ))}
    </div>
    {kpis.rankings && (
      <div style={{ display: "grid", gap: 12,
                      gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
                      marginTop: 14 }}>
        <RankingCard
          testid="rank-fuel-cost"
          title="Top 5 — Maior custo combustível (mês)"
          subtitle="Quem mais gastou neste mês"
          color="#f59e0b"
          items={kpis.rankings.top_fuel_cost}
          render={(it) => (
            <>
              <span style={{ fontFamily: "ui-monospace,monospace",
                              fontWeight: 700, color: "#0f172a" }}>
                {it.placa}
              </span>
              <span style={{ marginLeft: "auto", fontWeight: 800, color: "#dc2626" }}>
                R$ {it.total.toFixed(2)}
              </span>
              {it.per_os != null && (
                <span style={{ fontSize: 10, color: "#94a3b8" }}>
                  R$ {it.per_os}/OS · {it.os} OS
                </span>
              )}
            </>
          )}
          emptyMsg="Nenhum lançamento de combustível no mês."
        />
        <RankingCard
          testid="rank-rejected"
          title="️ Top 5 — Mais vistorias recusadas (90d)"
          subtitle="Veículos problemáticos pra trocar / revisar"
          color="#dc2626"
          items={kpis.rankings.top_rejected_inspections}
          render={(it) => (
            <>
              <span style={{ fontFamily: "ui-monospace,monospace",
                              fontWeight: 700, color: "#0f172a" }}>
                {it.placa}
              </span>
              <span style={{ marginLeft: "auto", padding: "3px 9px",
                              borderRadius: 999, background: "#fee2e2",
                              color: "#991b1b", fontWeight: 800,
                              fontSize: 11 }}>
                {it.count} recusas
              </span>
            </>
          )}
          emptyMsg="Parabéns! Nenhuma vistoria recusada nos últimos 90 dias."
        />
      </div>
    )}
    </>
  );
}

function RankingCard({ testid, title, subtitle, color, items, render, emptyMsg }) {
  return (
    <div data-testid={testid} className="surface" style={{
      padding: 14, borderRadius: 12,
      border: `1px solid ${color}33`,
      borderTop: `4px solid ${color}`,
    }}>
      <div style={{ marginBottom: 10 }}>
        <h4 style={{ margin: 0, fontSize: 13, fontWeight: 800, color: "#0f172a" }}>
          {title}
        </h4>
        <p style={{ margin: "2px 0 0", fontSize: 11, color: "#64748b" }}>
          {subtitle}
        </p>
      </div>
      {!items || items.length === 0 ? (
        <div style={{ padding: 14, textAlign: "center",
                        color: "#94a3b8", fontSize: 12, fontStyle: "italic" }}>
          {emptyMsg}
        </div>
      ) : (
        <div style={{ display: "grid", gap: 5 }}>
          {items.map((it, idx) => (
            <div key={(it.vehicle_id || "") + idx}
              data-testid={`${testid}-row-${idx}`}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 10px", borderRadius: 8,
                background: idx === 0 ? `${color}11` : "#f8fafc",
                border: `1px solid ${idx === 0 ? color + "44" : "#e2e8f0"}`,
                flexWrap: "wrap", fontSize: 12,
              }}>
              <span style={{
                width: 22, height: 22, borderRadius: "50%",
                background: idx === 0 ? color : "#cbd5e1",
                color: "white", display: "grid", placeItems: "center",
                fontWeight: 800, fontSize: 11, flexShrink: 0,
              }}>{idx + 1}</span>
              {render(it)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* === Atoms =============================================== */
function Field({ label, children }) {
  return (
    <label style={{ display: "block", marginTop: 8 }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.4,
                       marginBottom: 3 }}>{label}</div>
      {children}
    </label>
  );
}
function CheckRow({ label, checked, onChange }) {
  return (
    <label style={{ display: "inline-flex", gap: 6, alignItems: "center",
                      fontSize: 12, cursor: "pointer" }}>
      <input type="checkbox" checked={checked}
              onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}


// =============================================================
// iter189 — OdometerTab: leituras semanais + KPIs por técnico/carro
// KPIs aplicados (literatura ISP 2025):
//   • km_total por técnico no período
//   • km/nota (km ÷ OS executadas)
//   • R$/OS e R$/km (combinado com combustível)
//   • Consumo médio km/l
// =============================================================
function OdometerTab() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [readings, setReadings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewPhoto, setViewPhoto] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [k, r] = await Promise.all([
        api.fleetOdomKpis(days),
        api.fleetOdomReadings({}),
      ]);
      setData(k);
      setReadings(r.items || []);
    } finally { setLoading(false); }
  }, [days]);
  useEffect(() => { load(); }, [load]);

  if (loading) return (
    <div style={{ padding: 20, color: "var(--text-muted)" }}>
      Carregando KPIs de odômetro...
    </div>
  );
  const s = data?.summary || {};
  const list = data?.by_collab || [];

  const fmt = (v, suf = "") => v != null ?
    `${Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}${suf}` : "—";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Filtro período */}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          Período:
        </span>
        {[7, 14, 30, 60, 90].map((d) => (
          <button key={d} onClick={() => setDays(d)}
            style={{
              padding: "6px 12px", borderRadius: 8, fontSize: 12,
              border: days === d ? "2px solid #0d9488" : "1px solid #cbd5e1",
              background: days === d ? "#ccfbf1" : "#fff",
              color: days === d ? "#0d9488" : "#475569",
              fontWeight: 700, cursor: "pointer",
            }}>{d}d</button>
        ))}
      </div>

      {/* KPI cards gerais */}
      <div style={{ display: "grid", gap: 10,
                          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
        <KpiCard label="KM rodados (total)" value={fmt(s.total_km, " km")}
                    color="#0d9488" />
        <KpiCard label="OS executadas" value={fmt(s.total_os_executadas)}
                    color="#7c3aed" />
        <KpiCard label="km / nota" value={fmt(s.km_por_nota_geral, " km")}
                    color="#f59e0b" />
        <KpiCard label="R$ / nota" value={fmt(s.custo_por_nota_geral, "")}
                    prefix="R$ " color="#dc2626" />
        <KpiCard label="Consumo médio" value={fmt(s.media_km_l_geral, " km/l")}
                    color="#16a34a" />
        <KpiCard label="R$ / km" value={fmt(s.custo_por_km_geral, "")}
                    prefix="R$ " color="#0ea5e9" />
      </div>

      {/* Tabela por colaborador */}
      <div style={{ background: "var(--bg-elevated, #fff)", borderRadius: 12,
                          padding: 14, border: "1px solid var(--border-default, #e2e8f0)" }}>
        <h3 style={{ fontSize: 15, fontWeight: 800, margin: "0 0 10px" }}>
          Performance por técnico/veículo
        </h3>
        {list.length === 0 && (
          <div style={{ padding: 20, textAlign: "center",
                              color: "var(--text-muted)" }}>
            Nenhuma leitura de odômetro nos últimos {days} dias.
          </div>
        )}
        {list.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "2px solid #e2e8f0",
                                  textAlign: "left", color: "#64748b" }}>
                  <th style={{ padding: "8px 6px" }}>Técnico</th>
                  <th style={{ padding: "8px 6px" }}>Placa</th>
                  <th style={{ padding: "8px 6px", textAlign: "right" }}>KM</th>
                  <th style={{ padding: "8px 6px", textAlign: "right" }}>OS</th>
                  <th style={{ padding: "8px 6px", textAlign: "right" }}>km/OS</th>
                  <th style={{ padding: "8px 6px", textAlign: "right" }}>Litros</th>
                  <th style={{ padding: "8px 6px", textAlign: "right" }}>R$ Comb.</th>
                  <th style={{ padding: "8px 6px", textAlign: "right" }}>R$/OS</th>
                  <th style={{ padding: "8px 6px", textAlign: "right" }}>km/L</th>
                </tr>
              </thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.collab_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "8px 6px", fontWeight: 700 }}>
                      {r.collab_name}
                    </td>
                    <td style={{ padding: "8px 6px", fontFamily: "monospace" }}>
                      {r.vehicle_plate || "—"}
                    </td>
                    <td style={{ padding: "8px 6px", textAlign: "right",
                                          fontWeight: 700, color: "#0d9488" }}>
                      {fmt(r.km_total)}
                    </td>
                    <td style={{ padding: "8px 6px", textAlign: "right" }}>
                      {r.os_executadas}
                    </td>
                    <td style={{ padding: "8px 6px", textAlign: "right" }}>
                      {fmt(r.km_por_nota)}
                    </td>
                    <td style={{ padding: "8px 6px", textAlign: "right" }}>
                      {fmt(r.litros)}
                    </td>
                    <td style={{ padding: "8px 6px", textAlign: "right" }}>
                      R$ {fmt(r.valor_combustivel)}
                    </td>
                    <td style={{ padding: "8px 6px", textAlign: "right",
                                          color: "#dc2626", fontWeight: 700 }}>
                      R$ {fmt(r.custo_por_nota)}
                    </td>
                    <td style={{ padding: "8px 6px", textAlign: "right" }}>
                      {fmt(r.media_km_l)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Últimas leituras (gallery) */}
      <div style={{ background: "var(--bg-elevated, #fff)", borderRadius: 12,
                          padding: 14, border: "1px solid var(--border-default, #e2e8f0)" }}>
        <h3 style={{ fontSize: 15, fontWeight: 800, margin: "0 0 10px" }}>
          Últimas leituras ({readings.length})
        </h3>
        <div style={{ display: "grid", gap: 10,
                            gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))" }}>
          {readings.slice(0, 24).map((r) => (
            <button key={r.id} onClick={() => setViewPhoto(r)}
              style={{
                background: r.kind === "start" ? "#fffbeb" : "#fef2f2",
                border: `1px solid ${r.kind === "start" ? "#fbbf24" : "#ef4444"}`,
                borderRadius: 10, padding: 10, textAlign: "left",
                cursor: "pointer",
              }}>
              <div style={{ aspectRatio: "1", borderRadius: 6,
                                  overflow: "hidden", marginBottom: 6,
                                  background: "#0f172a" }}>
                {r.photo_data_url && (
                  <img src={r.photo_data_url} alt="" style={{
                    width: "100%", height: "100%", objectFit: "cover",
                  }} />
                )}
              </div>
              <div style={{ fontSize: 11, fontWeight: 800 }}>
                {r.km_final?.toLocaleString("pt-BR") || "—"} km
              </div>
              <div style={{ fontSize: 10, color: "#64748b" }}>
                {r.collab_name}
              </div>
              <div style={{ fontSize: 9, color: "#94a3b8" }}>
                {r.captured_at?.slice(0, 10)}
                {" · "}{r.kind === "start" ? "" : ""}
                {" "}IA {r.ai_confidence || 0}%
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Modal visualização foto */}
      {viewPhoto && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)",
          display: "flex", alignItems: "center", justifyContent: "center",
          zIndex: 1000, padding: 20,
        }} onClick={() => setViewPhoto(null)}>
          <div style={{ maxWidth: 720, width: "100%",
                                background: "#fff", borderRadius: 14,
                                overflow: "hidden", maxHeight: "90vh",
                                display: "flex", flexDirection: "column" }}
                  onClick={(e) => e.stopPropagation()}>
            <div style={{ padding: 14, borderBottom: "1px solid #e2e8f0",
                              display: "flex", justifyContent: "space-between",
                              alignItems: "center" }}>
              <div>
                <div style={{ fontSize: 18, fontWeight: 800 }}>
                  {viewPhoto.km_final?.toLocaleString("pt-BR")} km
                </div>
                <div style={{ fontSize: 11, color: "#64748b" }}>
                  {viewPhoto.collab_name} · {viewPhoto.vehicle_plate || "—"}
                  {" · "}{viewPhoto.captured_at?.slice(0, 16).replace("T", " ")}
                </div>
              </div>
              <button onClick={() => setViewPhoto(null)} style={{
                background: "#f1f5f9", border: 0, padding: 10, borderRadius: 8,
                fontSize: 16, fontWeight: 800, cursor: "pointer",
              }}>✕</button>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
              <img src={viewPhoto.photo_data_url} alt="" style={{
                width: "100%", borderRadius: 10,
              }} />
              <div style={{ marginTop: 10, padding: 10,
                                  background: "#f1f5f9", borderRadius: 8,
                                  fontSize: 12 }}>
                <strong>Confiança IA:</strong> {viewPhoto.ai_confidence}%
                <br />
                <strong>IA leu:</strong> {viewPhoto.km_ai} km
                {viewPhoto.km_ai !== viewPhoto.km_final && (
                  <> (sobrescrito manualmente para {viewPhoto.km_final})</>
                )}
                {viewPhoto.ai_reasoning && (
                  <>
                    <br /><strong>Razão:</strong> {viewPhoto.ai_reasoning}
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function KpiCard({ label, value, prefix = "", color = "#0ea5e9" }) {
  return (
    <div style={{
      background: "var(--bg-elevated, #fff)",
      border: `2px solid ${color}33`,
      borderRadius: 12, padding: 14,
    }}>
      <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700,
                          textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 900, color, marginTop: 4 }}>
        {prefix}{value}
      </div>
    </div>
  );
}

