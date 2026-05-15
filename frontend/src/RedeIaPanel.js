/* =============================================================
   RedeIaPanel — Painel administrativo da Rede IA
   - Visão geral / KPIs
   - Lista de CTOs (filtros)
   - Pendências de validação (Aprovar/Solicitar correção/Rejeitar)
   - Histórico de alterações
   - Bairros / VLAN map (admin)
   - Diretrizes da rede_IA (system prompt)
   - Fluxograma (React Flow) — em sub-aba
============================================================= */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import RedeIaMap from "@/RedeIaMap";

const TABS = [
  { id: "overview", label: "Painel" },
  { id: "ctos", label: "CTOs" },
  { id: "pendencies", label: "Pendências" },
  { id: "map", label: "Mapa interativo" },
  { id: "bairros", label: "Bairros / VLAN" },
  { id: "history", label: "Histórico" },
  { id: "diretrizes", label: "Diretrizes" },
];

const STATUS_BADGE = {
  pending_validation: { l: "Aguardando validação", c: "#ca8a04", bg: "#fef9c3" },
  pending_correction: { l: "Correção solicitada", c: "#9a3412", bg: "#fed7aa" },
  approved: { l: "Aprovada", c: "#15803d", bg: "#dcfce7" },
  rejected: { l: "Rejeitada", c: "#b91c1c", bg: "#fee2e2" },
};

export default function RedeIaPanel() {
  const [tab, setTab] = useState("overview");
  const [notifCount, setNotifCount] = useState(0);
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifs, setNotifs] = useState([]);

  const loadNotifs = useCallback(async () => {
    try {
      const r = await api.redeIaNotifications(false);
      setNotifs(r.items || []);
      setNotifCount(r.unread || 0);
    } catch (_) {}
  }, []);
  useEffect(() => {
    loadNotifs();
    const id = setInterval(loadNotifs, 25000);
    return () => clearInterval(id);
  }, [loadNotifs]);

  const markAll = async () => {
    try { await api.redeIaNotifMarkRead(null, true); await loadNotifs(); }
    catch (e) { alert(e?.response?.data?.detail || "Erro"); }
  };
  const markOne = async (id) => {
    try { await api.redeIaNotifMarkRead(id, false); await loadNotifs(); }
    catch (_) {}
  };

  return (
    <div data-testid="rede-ia-panel" style={{ display: "grid", gap: 16 }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                         flexWrap: "wrap", gap: 8 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0,
                         color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
            Rede IA
          </h1>
          <p style={{ margin: "4px 0 0", color: "var(--text-muted)", fontSize: 13 }}>
            Supervisora inteligente da rede FTTH — padroniza CTOs, valida topologia e mantém
            o fluxograma sempre atualizado.
          </p>
        </div>
        {/* Bell de notificações */}
        <div style={{ position: "relative" }}>
          <button data-testid="rede-ia-notif-bell"
            onClick={() => setNotifOpen(!notifOpen)}
            style={{
              position: "relative", padding: "8px 14px", borderRadius: 10,
              background: notifCount > 0 ? "#dc2626" : "var(--bg-surface)",
              color: notifCount > 0 ? "#fff" : "var(--text-primary)",
              border: "1px solid var(--border-default)",
              cursor: "pointer", fontSize: 14, fontWeight: 700,
              display: "inline-flex", alignItems: "center", gap: 8,
            }}>
            🔔 Notificações
            {notifCount > 0 && (
              <span style={{
                background: "#fff", color: "#dc2626", borderRadius: 99,
                padding: "1px 7px", fontSize: 11, fontWeight: 800,
              }}>{notifCount}</span>
            )}
          </button>
          {notifOpen && (
            <div data-testid="rede-ia-notif-panel"
              style={{
                position: "absolute", right: 0, top: "calc(100% + 6px)",
                width: 360, maxHeight: 480, overflow: "auto",
                background: "var(--bg-surface)",
                border: "1px solid var(--border-default)",
                borderRadius: 12, padding: 0, zIndex: 200,
                boxShadow: "0 12px 32px rgba(0,0,0,0.18)",
              }}>
              <div style={{ display: "flex", justifyContent: "space-between",
                              alignItems: "center", padding: "12px 14px",
                              borderBottom: "1px solid var(--border-default)" }}>
                <strong style={{ fontSize: 13 }}>Notificações ({notifCount} novas)</strong>
                <button onClick={markAll}
                  style={{ padding: "4px 10px", borderRadius: 6, border: 0,
                            background: "#0f172a", color: "#fff",
                            fontSize: 11, fontWeight: 700, cursor: "pointer" }}>
                  Marcar todas
                </button>
              </div>
              {notifs.length === 0 && (
                <div style={{ padding: 20, textAlign: "center",
                                 color: "var(--text-muted)", fontSize: 12 }}>
                  Nenhuma notificação ainda.
                </div>
              )}
              {notifs.map((n) => (
                <div key={n.id} onClick={() => !n.read && markOne(n.id)}
                  style={{
                    padding: "10px 14px",
                    borderBottom: "1px solid var(--border-default)",
                    cursor: n.read ? "default" : "pointer",
                    background: n.read ? "transparent" : "#fef3c7",
                  }}>
                  <div style={{ display: "flex", justifyContent: "space-between",
                                  gap: 8, alignItems: "flex-start" }}>
                    <strong style={{ fontSize: 12, color: "var(--text-primary)",
                                       lineHeight: 1.3 }}>{n.title}</strong>
                    {!n.read && <span style={{ width: 8, height: 8,
                                                  background: "#dc2626",
                                                  borderRadius: 99, marginTop: 4,
                                                  flexShrink: 0 }} />}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-secondary)",
                                  marginTop: 4, lineHeight: 1.4 }}>
                    {n.message}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)",
                                  marginTop: 4 }}>
                    {new Date(n.created_at).toLocaleString("pt-BR")}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </header>

      <div style={{ display: "flex", gap: 4, flexWrap: "wrap",
                       borderBottom: "1px solid var(--border-default)", paddingBottom: 0 }}>
        {TABS.map((t) => (
          <button key={t.id} data-testid={`rede-ia-tab-${t.id}`}
                  onClick={() => setTab(t.id)}
                  style={{
                    padding: "10px 14px", borderRadius: "6px 6px 0 0",
                    background: tab === t.id ? "var(--bg-surface)" : "transparent",
                    border: tab === t.id ? "1px solid var(--border-default)"
                                          : "1px solid transparent",
                    borderBottom: tab === t.id ? "1px solid var(--bg-surface)" : "none",
                    color: tab === t.id ? "var(--text-primary)" : "var(--text-secondary)",
                    fontWeight: tab === t.id ? 700 : 500, fontSize: 13, cursor: "pointer",
                    marginBottom: -1,
                  }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <Overview />}
      {tab === "ctos" && <CTOsList />}
      {tab === "pendencies" && <Pendencies />}
      {tab === "map" && <RedeIaMap />}
      {tab === "bairros" && <BairrosManager />}
      {tab === "history" && <HistoryList />}
      {tab === "diretrizes" && <DiretrizesEditor />}
    </div>
  );
}

/* ------------- Overview ------------- */
function Overview() {
  const [ctos, setCtos] = useState([]);
  const [pend, setPend] = useState([]);
  const [bairros, setBairros] = useState([]);
  useEffect(() => {
    api.redeIaCtosList().then((r) => setCtos(r.items || []));
    api.redeIaPendencies().then((r) => setPend(r.items || []));
    api.redeIaBairros().then((r) => setBairros(r.items || []));
  }, []);
  const approved = ctos.filter((c) => c.status === "approved").length;
  const totalPorts = ctos.reduce((acc, c) => acc + (c.capacity || 0), 0);
  const usedPorts = ctos.reduce(
    (acc, c) => acc + ((c.ports || []).filter((p) => p.status === "used").length), 0,
  );
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px,1fr))",
                     gap: 12 }}>
      <KPI label="CTOs cadastradas" value={ctos.length} />
      <KPI label="CTOs aprovadas" value={approved} color="#15803d" />
      <KPI label="Pendências validação" value={pend.length} color="#ca8a04" />
      <KPI label="Bairros mapeados" value={bairros.length} />
      <KPI label="Portas ocupadas / total" value={`${usedPorts} / ${totalPorts}`}
            color="#7c3aed" />
      <KPI label="Taxa de ocupação"
            value={totalPorts ? `${Math.round((usedPorts / totalPorts) * 100)}%` : "—"} />
    </div>
  );
}

function KPI({ label, value, color }) {
  return (
    <Card style={{ padding: 16 }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 800, marginTop: 6,
                       color: color || "var(--text-primary)", letterSpacing: -0.4 }}>
        {value}
      </div>
    </Card>
  );
}

/* ------------- CTOs list ------------- */
function CTOsList() {
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [qrModal, setQrModal] = useState(null); // {id, name}
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.redeIaCtosList(statusFilter ? { status: statusFilter } : {});
      setItems(r.items || []);
    } finally { setLoading(false); }
  }, [statusFilter]);
  useEffect(() => { load(); }, [load]);
  return (
    <Card style={{ padding: 16 }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <select data-testid="rede-ia-cto-filter-status"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                style={{ padding: "8px 10px", borderRadius: 8,
                          border: "1px solid var(--border-default)", fontSize: 13 }}>
          <option value="">Todos os status</option>
          <option value="pending_validation">Aguardando validação</option>
          <option value="approved">Aprovadas</option>
          <option value="rejected">Rejeitadas</option>
          <option value="pending_correction">Correção solicitada</option>
        </select>
        <span style={{ fontSize: 12, color: "var(--text-muted)", padding: "8px 4px" }}>
          {loading ? "Carregando..." : `${items.length} CTOs`}
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid var(--border-default)" }}>
              <th style={th}>Nome</th>
              <th style={th}>VLAN</th>
              <th style={th}>Bairro</th>
              <th style={th}>Capac.</th>
              <th style={th}>Ocupadas</th>
              <th style={th}>Status</th>
              <th style={th}>Técnico</th>
              <th style={th}>QR</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => {
              const used = (c.ports || []).filter((p) => p.status === "used").length;
              const st = STATUS_BADGE[c.status] || {};
              return (
                <tr key={c.id} data-testid={`cto-row-${c.id}`}
                    style={{ borderBottom: "1px solid var(--border-default)" }}>
                  <td style={td}><strong>{c.name}</strong></td>
                  <td style={td}>{c.vlan}</td>
                  <td style={td}>{c.address?.bairro}</td>
                  <td style={td}>{c.capacity}</td>
                  <td style={td}>{used}/{c.capacity}</td>
                  <td style={td}>
                    <span style={{
                      padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 700,
                      color: st.c, background: st.bg,
                    }}>{st.l || c.status}</span>
                  </td>
                  <td style={td}>{c.technician_name || "—"}</td>
                  <td style={td}>
                    {c.status === "approved" ? (
                      <div style={{ display: "flex", gap: 4 }}>
                        <button data-testid={`cto-qr-${c.id}`}
                                onClick={() => setQrModal({ id: c.id, name: c.name })}
                                style={btnSm("#7c3aed")}>QR</button>
                        <a href={`${process.env.REACT_APP_BACKEND_URL}/api/rede-ia/ctos/${c.id}/pdf.pdf`}
                            target="_blank" rel="noreferrer"
                            data-testid={`cto-pdf-${c.id}`}
                            style={{ ...btnSm("#dc2626"), textDecoration: "none",
                                      display: "inline-flex", alignItems: "center" }}>
                          PDF
                        </a>
                        {c.pdf_drive_url ? (
                          <a href={c.pdf_drive_url} target="_blank" rel="noreferrer"
                              data-testid={`cto-drive-${c.id}`}
                              title="Abrir PDF salvo no Drive"
                              style={{ ...btnSm("#0ea5e9"), textDecoration: "none",
                                        display: "inline-flex", alignItems: "center" }}>
                            ☁
                          </a>
                        ) : (
                          <DriveResendBtn ctoId={c.id} onDone={load} />
                        )}
                      </div>
                    ) : (
                      <span style={{ fontSize: 11, color: "var(--text-muted)" }}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
            {items.length === 0 && !loading && (
              <tr><td colSpan="8" style={{ ...td, textAlign: "center",
                                              color: "var(--text-muted)", padding: 20 }}>
                Nenhuma CTO cadastrada.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {qrModal && (
        <CTOQrModal cto={qrModal} onClose={() => setQrModal(null)} />
      )}
    </Card>
  );
}


function DriveResendBtn({ ctoId, onDone }) {
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    try {
      await api.redeIaCtoPdfRegenerate(ctoId);
      onDone?.();
    } catch (e) {
      const msg = e?.response?.data?.detail || "Falha ao enviar para Drive";
      alert(msg);
    } finally { setBusy(false); }
  };
  return (
    <button data-testid={`cto-drive-send-${ctoId}`}
            onClick={send} disabled={busy}
            title="Enviar PDF para Google Drive"
            style={{ ...btnSm("#475569"), opacity: busy ? 0.5 : 1 }}>
      {busy ? "…" : "☁+"}
    </button>
  );
}

function CTOQrModal({ cto, onClose }) {  const [imgSrc, setImgSrc] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let revokeUrl = null;
    const token = (typeof window !== "undefined") && window.localStorage.getItem("ponto_token");
    fetch(`${process.env.REACT_APP_BACKEND_URL}/api/rede-ia/ctos/${cto.id}/qrcode.png`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        revokeUrl = url;
        setImgSrc(url);
        setLoading(false);
      })
      .catch(() => setLoading(false));
    return () => { if (revokeUrl) URL.revokeObjectURL(revokeUrl); };
  }, [cto.id]);
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", zIndex: 9999,
      display: "grid", placeItems: "center",
    }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="cto-qr-modal"
           style={{ background: "#fff", borderRadius: 14, padding: 24,
                     width: "min(420px, 92vw)", textAlign: "center" }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 18 }}>{cto.name}</h3>
        <p style={{ margin: "0 0 14px", fontSize: 12, color: "#64748b" }}>
          Imprima este QR Code e cole na CTO física. Apenas técnicos com
          o app SmartProv conseguem ler (assinatura HMAC).
        </p>
        <div style={{ background: "#fff", padding: 14, border: "1px solid #e2e8f0",
                        borderRadius: 10, marginBottom: 14, minHeight: 200,
                        display: "grid", placeItems: "center" }}>
          {loading ? (
            <span style={{ color: "#64748b", fontSize: 13 }}>Gerando QR…</span>
          ) : imgSrc ? (
            <img src={imgSrc} alt={`QR ${cto.name}`}
                 style={{ width: "100%", maxWidth: 320, height: "auto" }} />
          ) : (
            <span style={{ color: "#dc2626", fontSize: 13 }}>Falha ao gerar QR</span>
          )}
        </div>
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          <button data-testid="cto-qr-print" onClick={() => window.print()}
                  style={btnSm("#0f172a")}>Imprimir</button>
          {imgSrc && (
            <a href={imgSrc} download={`qr-${cto.name}.png`}
               style={{ ...btnSm("#7c3aed"), textDecoration: "none" }}
               data-testid="cto-qr-download">Baixar PNG</a>
          )}
          <button onClick={onClose} style={btnSm("#64748b")}>Fechar</button>
        </div>
      </div>
    </div>
  );
}
const th = { textAlign: "left", padding: "8px 10px", fontSize: 11,
              color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 };
const td = { padding: "10px", color: "var(--text-primary)", verticalAlign: "middle" };

/* ------------- Pendencies (validation workflow) ------------- */
function Pendencies() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState(null); // {item, action}
  const [comment, setComment] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    const r = await api.redeIaPendencies();
    setItems(r.items || []);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  const submit = async () => {
    try {
      await api.redeIaValidate(modal.item.cto_id, modal.action, comment);
      setModal(null); setComment("");
      load();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };
  return (
    <Card style={{ padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>Pendências de validação</h3>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {loading ? "Carregando..." : `${items.length} aguardando`}
        </span>
      </div>
      {items.length === 0 && !loading && (
        <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)" }}>
          ✓ Nenhuma pendência. Tudo em dia.
        </div>
      )}
      <div style={{ display: "grid", gap: 10 }}>
        {items.map((p) => {
          const c = p.cto_snapshot || {};
          return (
            <div key={p.id} data-testid={`pendency-${p.id}`} style={{
              padding: 14, border: "1px solid var(--border-default)", borderRadius: 10,
              background: "var(--bg-surface-2)",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between",
                              alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                <div style={{ minWidth: 200 }}>
                  <div style={{ fontWeight: 800, fontSize: 16 }}>{c.name}</div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                    {c.address?.rua}, {c.address?.numero} · {c.address?.bairro} · VLAN {c.vlan}
                  </div>
                  <div style={{ fontSize: 12, marginTop: 6 }}>
                    <strong>Cap:</strong> {c.capacity} portas · <strong>Tipo:</strong> {c.network_type}
                    {c.splitter ? ` (splitter ${c.splitter})` : ""}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
                    Técnico: {p.technician_name || "—"} · {new Date(p.created_at).toLocaleString("pt-BR")}
                  </div>
                  {p.smartolt_hints && p.smartolt_hints.matched > 0 && (
                    <div data-testid={`smartolt-hints-${p.id}`} style={{
                      marginTop: 10, padding: "8px 10px", borderRadius: 6,
                      background: "#ecfdf5", border: "1px solid #6ee7b7",
                      fontSize: 11, color: "#065f46",
                    }}>
                      <strong>🛰 SmartOLT detectou {p.smartolt_hints.matched} ONUs</strong>
                      {p.smartolt_hints.alerts > 0 && (
                        <span style={{ color: "#b91c1c", marginLeft: 6 }}>
                          ⚠️ {p.smartolt_hints.alerts} com alerta de sinal
                        </span>
                      )}
                      <div style={{ marginTop: 4 }}>
                        {(p.smartolt_hints.candidates || []).slice(0, 3).map((cd, i) => (
                          <div key={i}>
                            • <strong>{cd.olt_name}</strong> Slot {cd.board}/PON {cd.port}
                            ({cd.count} ONUs)
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {c.photo_data_url && (
                    <div data-testid={`pendency-photo-${p.id}`} style={{
                      marginTop: 10, borderRadius: 8, overflow: "hidden",
                      border: "1px solid var(--border-default)", maxWidth: 240,
                    }}>
                      <img src={c.photo_data_url} alt="Foto CTO"
                        style={{ width: "100%", display: "block",
                                  maxHeight: 180, objectFit: "cover" }} />
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <button data-testid={`pendency-approve-${p.id}`}
                          onClick={() => { setModal({ item: p, action: "approve" }); setComment(""); }}
                          style={btnSm("#16a34a")}>Aprovar</button>
                  <button data-testid={`pendency-correct-${p.id}`}
                          onClick={() => { setModal({ item: p, action: "request_correction" }); setComment(""); }}
                          style={btnSm("#ca8a04")}>Solicitar correção</button>
                  <button data-testid={`pendency-reject-${p.id}`}
                          onClick={() => { setModal({ item: p, action: "reject" }); setComment(""); }}
                          style={btnSm("#dc2626")}>Rejeitar</button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {modal && (
        <div onClick={() => setModal(null)} style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,.55)", zIndex: 9999,
          display: "grid", placeItems: "center",
        }}>
          <div onClick={(e) => e.stopPropagation()} data-testid="pendency-modal"
            style={{ background: "var(--bg-surface)", borderRadius: 12, padding: 20,
                      width: "min(440px,92vw)" }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>
              {modal.action === "approve" && "Aprovar CTO"}
              {modal.action === "request_correction" && "Solicitar correção"}
              {modal.action === "reject" && "Rejeitar CTO"}
            </h3>
            <p style={{ margin: "0 0 12px", fontSize: 13, color: "var(--text-secondary)" }}>
              <strong>{modal.item.cto_snapshot?.name}</strong>
            </p>
            <textarea data-testid="pendency-comment" value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Comentário (opcional)..." rows={3}
              style={{ width: "100%", padding: 10, borderRadius: 8,
                        border: "1px solid var(--border-default)", fontSize: 13,
                        fontFamily: "inherit", boxSizing: "border-box", resize: "vertical" }} />
            <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
              <button onClick={() => setModal(null)} style={btnSm("#64748b")}>Cancelar</button>
              <button data-testid="pendency-submit" onClick={submit} style={btnSm("#0f172a")}>
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
const btnSm = (color) => ({
  padding: "6px 12px", borderRadius: 6, border: "0",
  background: color, color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer",
});

/* ------------- Bairros / VLAN map ------------- */
function BairrosManager() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ bairro: "", sigla: "", vlan: "",
                                          cidade: "", estado: "", regiao: "" });
  const [err, setErr] = useState("");
  const load = useCallback(async () => {
    const r = await api.redeIaBairros();
    setItems(r.items || []);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setErr("");
    try {
      await api.redeIaBairroCreate({
        ...form, vlan: parseInt(form.vlan, 10),
      });
      setForm({ bairro: "", sigla: "", vlan: "", cidade: "", estado: "", regiao: "" });
      load();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Erro ao salvar.");
    }
  };
  const del = async (id) => {
    if (!window.confirm("Remover bairro?")) return;
    await api.redeIaBairroDelete(id);
    load();
  };
  return (
    <Card style={{ padding: 16 }}>
      <h3 style={{ margin: "0 0 12px", fontSize: 16 }}>Bairros e VLAN</h3>
      <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 14 }}>
        Cadastre os bairros atendidos. A sigla e a VLAN são usadas pela rede_IA para gerar
        nomenclaturas padronizadas das CTOs (ex: <code>CTO 001_301_COR</code>).
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr auto",
                       gap: 8, marginBottom: 14, alignItems: "end" }}>
        <Field l="Bairro" v={form.bairro} on={(v) => setForm({ ...form, bairro: v })}
                tid="bairro-input" />
        <Field l="Sigla" v={form.sigla}
                on={(v) => setForm({ ...form, sigla: v.toUpperCase() })} tid="sigla-input" />
        <Field l="VLAN" v={form.vlan} on={(v) => setForm({ ...form, vlan: v })}
                tid="vlan-input" type="number" />
        <Field l="Cidade" v={form.cidade} on={(v) => setForm({ ...form, cidade: v })} />
        <Field l="UF" v={form.estado} on={(v) => setForm({ ...form, estado: v.toUpperCase() })} />
        <button data-testid="bairro-save" onClick={save} style={btnSm("#0f172a")}>
          Adicionar
        </button>
      </div>
      {err && (
        <div style={{ color: "#b91c1c", fontSize: 12, marginBottom: 10 }}>{err}</div>
      )}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: "2px solid var(--border-default)" }}>
            <th style={th}>Bairro</th><th style={th}>Sigla</th><th style={th}>VLAN</th>
            <th style={th}>Cidade/UF</th><th style={th}></th>
          </tr>
        </thead>
        <tbody>
          {items.map((b) => (
            <tr key={b.id} style={{ borderBottom: "1px solid var(--border-default)" }}>
              <td style={td}>{b.bairro}</td>
              <td style={td}><strong>{b.sigla}</strong></td>
              <td style={td}>{b.vlan}</td>
              <td style={td}>{b.cidade}{b.estado ? `/${b.estado}` : ""}</td>
              <td style={td}>
                <button onClick={() => del(b.id)}
                        style={{ ...btnSm("#dc2626"), padding: "4px 8px", fontSize: 11 }}
                        data-testid={`bairro-del-${b.id}`}>×</button>
              </td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr><td colSpan="5" style={{ ...td, textAlign: "center", padding: 20,
                                            color: "var(--text-muted)" }}>
              Nenhum bairro cadastrado. Adicione o primeiro acima.
            </td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}
function Field({ l, v, on, tid, type = "text" }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 600 }}>{l}</span>
      <input data-testid={tid} value={v} type={type}
        onChange={(e) => on(e.target.value)}
        style={{ padding: "8px 10px", borderRadius: 8,
                  border: "1px solid var(--border-default)", fontSize: 13 }} />
    </label>
  );
}

/* ------------- History ------------- */
function HistoryList() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.redeIaHistory().then((r) => setItems(r.items || []));
  }, []);
  return (
    <Card style={{ padding: 16 }}>
      <h3 style={{ margin: "0 0 12px", fontSize: 16 }}>Histórico de alterações</h3>
      <div style={{ display: "grid", gap: 6 }}>
        {items.map((h) => (
          <div key={h.id} style={{
            padding: "10px 12px", borderLeft: "3px solid #7c3aed",
            background: "var(--bg-surface-2)", borderRadius: 6, fontSize: 12,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <strong>{h.action}</strong>
              <span style={{ color: "var(--text-muted)" }}>
                {new Date(h.timestamp).toLocaleString("pt-BR")}
              </span>
            </div>
            <div style={{ color: "var(--text-secondary)", marginTop: 4 }}>
              {h.by_user_name} ({h.by_role}) · CTO {h.cto_id}
              {h.motivo ? ` · ${h.motivo}` : ""}
            </div>
          </div>
        ))}
        {items.length === 0 && (
          <div style={{ padding: 20, textAlign: "center",
                          color: "var(--text-muted)" }}>Sem histórico.</div>
        )}
      </div>
    </Card>
  );
}

/* ------------- Diretrizes editor ------------- */
function DiretrizesEditor() {
  const [text, setText] = useState("");
  const [meta, setMeta] = useState({});
  const [saving, setSaving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [aiReport, setAiReport] = useState(null);
  useEffect(() => {
    api.redeIaDiretrizes().then((r) => {
      setText(r.text || "");
      setMeta({ updated_at: r.updated_at, updated_by: r.updated_by });
    });
  }, []);
  const save = async () => {
    setSaving(true);
    try {
      const r = await api.redeIaDiretrizesUpdate(text);
      setMeta({ updated_at: r.updated_at, updated_by: r.updated_by });
    } catch (e) {
      alert("Erro ao salvar: " + (e?.response?.data?.detail || e.message));
    } finally { setSaving(false); }
  };
  const analyze = async () => {
    setAnalyzing(true); setAiReport(null);
    try {
      const r = await api.redeIaAnalyze({});
      setAiReport(r);
    } catch (e) {
      alert("Erro IA: " + (e?.response?.data?.detail || e.message));
    } finally { setAnalyzing(false); }
  };
  return (
    <Card style={{ padding: 16 }}>
      <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>Diretrizes da rede_IA</h3>
      <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 14 }}>
        Defina a missão, regras e critérios técnicos que orientam a IA. Esse texto é
        usado como system prompt quando a IA analisa a rede.
      </p>
      <textarea data-testid="diretrizes-text" value={text}
        onChange={(e) => setText(e.target.value)}
        rows={10}
        style={{ width: "100%", padding: 12, borderRadius: 8,
                  border: "1px solid var(--border-default)", fontSize: 13,
                  fontFamily: "inherit", lineHeight: 1.5, boxSizing: "border-box",
                  resize: "vertical" }} />
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginTop: 10, gap: 10, flexWrap: "wrap" }}>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {meta.updated_at
            ? `Atualizado por ${meta.updated_by} em ${new Date(meta.updated_at).toLocaleString("pt-BR")}`
            : "Padrão da rede_IA"}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button data-testid="diretrizes-analyze" onClick={analyze}
                  disabled={analyzing} style={btnSm("#7c3aed")}>
            {analyzing ? "Analisando..." : "Analisar rede com IA"}
          </button>
          <button data-testid="diretrizes-save" onClick={save}
                  disabled={saving} style={btnSm("#0f172a")}>
            {saving ? "Salvando..." : "Salvar diretrizes"}
          </button>
        </div>
      </div>

      {aiReport && (
        <div data-testid="ai-report" style={{
          marginTop: 16, padding: 14, borderRadius: 10,
          background: "#f5f3ff", border: "1px solid #c4b5fd",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 6, color: "#5b21b6" }}>
            Relatório da rede_IA
          </div>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit",
                          fontSize: 13, color: "#1e1b4b", margin: 0 }}>
            {aiReport.report || JSON.stringify(aiReport, null, 2)}
          </pre>
        </div>
      )}
    </Card>
  );
}
