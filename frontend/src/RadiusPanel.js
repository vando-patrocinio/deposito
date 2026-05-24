/**
 * RadiusPanel — Painel administrativo do módulo RADIUS / PPPoE (MVP).
 *
 * 4 sub-abas:
 *   - 📊 Dashboard   — KPIs (sessões ativas, auth 24h, top rejeições)
 *   - 🟢 Sessões     — sessões ativas com filtro + botão CoA Disconnect
 *   - 📜 Histórico   — sessões encerradas (24h default)
 *   - 🛰️ NAS         — gerenciamento de roteadores/concentradores
 */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";


function fmtUptime(secs) {
  if (!secs || secs < 0) return "—";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  if (h > 0) return `${h}h${String(m).padStart(2, "0")}`;
  if (m > 0) return `${m}m${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

function fmtDateBr(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR",
      { dateStyle: "short", timeStyle: "medium" });
  } catch { return iso; }
}


export default function RadiusPanel() {
  const [tab, setTab] = useState("dashboard");

  return (
    <div data-testid="radius-panel" style={{ padding: 18 }}>
      <h2 style={{ fontSize: 22, fontWeight: 800, color: "#0f172a",
                      marginBottom: 4 }}>
        🛰️ RADIUS / PPPoE
      </h2>
      <p style={{ color: "#64748b", fontSize: 13, marginBottom: 14 }}>
        Autenticação, accounting e desconexão (CoA) de sessões PPPoE.
        FreeRADIUS externo chama este backend via HTTP (rlm_rest).
      </p>

      <div style={{ display: "flex", gap: 4,
                      borderBottom: "1px solid #e2e8f0", marginBottom: 14 }}>
        {[
          { id: "dashboard", label: "📊 Dashboard" },
          { id: "active", label: "🟢 Sessões Ativas" },
          { id: "history", label: "📜 Histórico" },
          { id: "nas", label: "🛰️ NAS" },
        ].map((t) => (
          <button key={t.id} data-testid={`radius-tab-${t.id}`}
                    onClick={() => setTab(t.id)}
                    style={{
                      padding: "10px 16px", border: 0,
                      background: "transparent", cursor: "pointer",
                      fontSize: 13, fontWeight: tab === t.id ? 700 : 500,
                      color: tab === t.id ? "#0ea5e9" : "#64748b",
                      borderBottom: "2px solid " +
                        (tab === t.id ? "#0ea5e9" : "transparent"),
                      marginBottom: -1, transition: "color 150ms",
                    }}>{t.label}</button>
        ))}
      </div>

      {tab === "dashboard" && <DashboardTab />}
      {tab === "active" && <ActiveSessionsTab />}
      {tab === "history" && <HistoryTab />}
      {tab === "nas" && <NasTab />}
    </div>
  );
}


function DashboardTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const r = await api.radiusDashboard();
      setData(r);
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  if (loading) return <div style={{ padding: 30, color: "#64748b" }}>⏳ Carregando…</div>;
  if (!data) return <div style={{ padding: 30, color: "#dc2626" }}>Erro ao carregar</div>;

  return (
    <div data-testid="radius-dashboard"
          style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(180px,1fr))",
                    gap: 12 }}>
      <KpiCard label="🟢 Sessões Ativas" value={data.active_sessions}
                color="#16a34a" />
      <KpiCard label="📥 Encerradas hoje" value={data.closed_today}
                color="#64748b" />
      <KpiCard label="🔑 Auths 24h" value={data.auth_24h} color="#0ea5e9" />
      <KpiCard label="❌ Rejeitadas 24h" value={data.reject_24h}
                color="#dc2626" />
      <KpiCard label="✅ Taxa de aceite"
                value={data.accept_rate != null
                  ? `${data.accept_rate}%` : "—"}
                color="#10b981" />
      <KpiCard label="🛰️ NAS cadastrados" value={data.nas_count}
                color="#7c3aed" />

      {(data.top_reject_reasons || []).length > 0 && (
        <div style={{ gridColumn: "1 / -1", background: "#fef2f2",
                        border: "1px solid #fecaca", borderRadius: 10,
                        padding: 14 }}>
          <div style={{ fontWeight: 800, color: "#7f1d1d",
                          marginBottom: 8 }}>
            🚨 Top motivos de rejeição (24h)
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            {data.top_reject_reasons.map((r) => (
              <div key={r.reason}
                    style={{ display: "flex",
                              justifyContent: "space-between",
                              padding: "6px 10px", background: "#fff",
                              borderRadius: 6, fontSize: 13 }}>
                <span style={{ color: "#0f172a", fontFamily: "monospace" }}>
                  {r.reason}
                </span>
                <span style={{ fontWeight: 700, color: "#dc2626" }}>
                  {r.count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


function KpiCard({ label, value, color }) {
  return (
    <div data-testid={`kpi-${String(label).replace(/\s+/g, '-').toLowerCase()}`}
          style={{
            background: "#fff", border: "1px solid #e2e8f0",
            borderLeft: `4px solid ${color}`,
            borderRadius: 10, padding: 14,
          }}>
      <div style={{ fontSize: 11, color: "#64748b", fontWeight: 700,
                      textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color, marginTop: 4 }}>
        {value}
      </div>
    </div>
  );
}


function ActiveSessionsTab() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.radiusSessionsActive({ search });
      setItems(r.items || []);
    } catch { /* silent */ }
    setLoading(false);
  }, [search]);

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  async function disconnect(s) {
    if (!window.confirm(
      `Cortar sessão do usuário ${s.username}?\n\n`
      + "O CoA Disconnect será enviado ao NAS via UDP. "
      + "Use para inadimplência, troca de plano ou abuso.")) return;
    setBusyId(s.id);
    try {
      const r = await api.radiusDisconnect(s.id);
      window.alert(r.message || "Solicitado.");
      await load();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusyId(null); }
  }

  return (
    <div data-testid="radius-active">
      <div style={{ display: "flex", gap: 8, marginBottom: 12,
                      alignItems: "center" }}>
        <input data-testid="radius-active-search" type="text"
                placeholder="Buscar por usuário, nome, IP ou MAC…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                  flex: 1, maxWidth: 360, padding: "8px 12px",
                  border: "1px solid #cbd5e1", borderRadius: 7,
                  fontSize: 13, outline: "none",
                }} />
        <button data-testid="radius-active-refresh" onClick={load}
                  style={refBtn}>🔄 Atualizar</button>
        <span style={{ color: "#64748b", fontSize: 12, marginLeft: "auto" }}>
          {loading ? "⏳" : ""} {items.length} sessões ativas
          {" · auto-refresh 20s"}
        </span>
      </div>

      {items.length === 0 && !loading && (
        <div style={{ padding: 40, background: "#f8fafc", borderRadius: 8,
                        textAlign: "center", color: "#64748b" }}>
          Nenhuma sessão ativa no momento.
        </div>
      )}

      <div style={{ display: "grid", gap: 8 }}>
        {items.map((s) => (
          <div key={s.id} data-testid={`session-${s.id}`}
                style={{
                  background: "#fff", border: "1px solid #e2e8f0",
                  borderLeft: "4px solid #16a34a", borderRadius: 10,
                  padding: 14, display: "grid",
                  gridTemplateColumns: "1fr auto", gap: 12,
                }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                              alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontWeight: 800, fontSize: 15,
                                color: "#0f172a" }}>
                  {s.subscriber_name || "(?)"} ·
                  {" "}<code style={{ background: "#f1f5f9",
                                        padding: "1px 6px",
                                        borderRadius: 4,
                                        fontSize: 12 }}>
                    {s.username}
                  </code>
                </span>
                {s.pending_disconnect_at && (
                  <span style={{ background: "#fef3c7", color: "#92400e",
                                  padding: "2px 8px", borderRadius: 99,
                                  fontSize: 11, fontWeight: 700 }}>
                    ⏳ Disconnect pendente
                  </span>
                )}
              </div>
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap",
                              fontSize: 12, color: "#475569" }}>
                {s.framed_ip && <span>📍 <b>{s.framed_ip}</b></span>}
                {s.nas_ip && <span>🛰️ NAS {s.nas_ip}</span>}
                {s.calling_station_id && (
                  <span>📱 {s.calling_station_id}</span>
                )}
                <span>⏱ {fmtUptime(s.uptime_seconds || s.session_time)}</span>
                <span>📥 {s.bytes_in_human}</span>
                <span>📤 {s.bytes_out_human}</span>
                <span style={{ color: "#94a3b8" }}>
                  desde {fmtDateBr(s.started_at)}
                </span>
              </div>
            </div>
            <div>
              <button data-testid={`session-disconnect-${s.id}`}
                        onClick={() => disconnect(s)} disabled={busyId === s.id}
                        style={{
                          padding: "8px 14px", borderRadius: 8,
                          background: "#dc2626", color: "#fff", border: 0,
                          fontSize: 12, fontWeight: 700,
                          cursor: busyId === s.id ? "wait" : "pointer",
                          opacity: busyId === s.id ? 0.5 : 1,
                          whiteSpace: "nowrap",
                        }}>
                {busyId === s.id ? "Enviando…" : "✗ CoA Disconnect"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


function HistoryTab() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [hours, setHours] = useState(24);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.radiusSessionsHistory({ hours, search });
      setItems(r.items || []);
    } catch { /* silent */ }
    setLoading(false);
  }, [hours, search]);

  useEffect(() => { load(); }, [load]);

  return (
    <div data-testid="radius-history">
      <div style={{ display: "flex", gap: 8, marginBottom: 12,
                      alignItems: "center", flexWrap: "wrap" }}>
        <input data-testid="radius-history-search" type="text"
                placeholder="Buscar usuário ou nome…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                  flex: 1, maxWidth: 320, padding: "8px 12px",
                  border: "1px solid #cbd5e1", borderRadius: 7,
                  fontSize: 13, outline: "none",
                }} />
        <select value={hours} onChange={(e) => setHours(parseInt(e.target.value))}
                  data-testid="radius-history-hours"
                  style={{ padding: "8px 10px", border: "1px solid #cbd5e1",
                            borderRadius: 7, fontSize: 13 }}>
          <option value={1}>Última 1h</option>
          <option value={6}>6h</option>
          <option value={24}>24h</option>
          <option value={72}>3 dias</option>
          <option value={168}>7 dias</option>
        </select>
        <button data-testid="radius-history-refresh" onClick={load}
                  style={refBtn}>🔄</button>
        <span style={{ color: "#64748b", fontSize: 12 }}>
          {loading ? "⏳" : ""} {items.length} sessões
        </span>
      </div>

      {items.length === 0 && !loading && (
        <div style={{ padding: 40, background: "#f8fafc", borderRadius: 8,
                        textAlign: "center", color: "#64748b" }}>
          Nenhuma sessão encerrada no período.
        </div>
      )}

      <div style={{ display: "grid", gap: 6 }}>
        {items.map((s) => (
          <div key={s.id}
                style={{
                  background: "#fff", border: "1px solid #e2e8f0",
                  borderRadius: 8, padding: 10,
                  display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr",
                  gap: 8, fontSize: 12, alignItems: "center",
                }}>
            <div>
              <div style={{ fontWeight: 700, color: "#0f172a" }}>
                {s.subscriber_name || s.username}
              </div>
              <code style={{ fontSize: 10, color: "#64748b" }}>
                {s.username} · {s.framed_ip || "—"}
              </code>
            </div>
            <div style={{ color: "#475569" }}>
              ⏱ {fmtUptime(s.session_time)}
            </div>
            <div style={{ color: "#475569" }}>
              📥 {s.bytes_in_human} · 📤 {s.bytes_out_human}
            </div>
            <div style={{ color: "#94a3b8", fontSize: 11,
                            textAlign: "right" }}>
              {fmtDateBr(s.ended_at)}
              {s.terminate_cause && (
                <div style={{ fontSize: 10 }}>{s.terminate_cause}</div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


function NasTab() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [testing, setTesting] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.radiusNasList();
      setItems(r.items || []);
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function remove(nas) {
    if (!window.confirm(`Remover NAS ${nas.name} (${nas.ip})?`)) return;
    try {
      await api.radiusNasDelete(nas.id);
      await load();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  }

  return (
    <div data-testid="radius-nas">
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button data-testid="nas-add-btn"
                  onClick={() => { setEditing(null); setShowForm(true); }}
                  style={{
                    padding: "8px 14px", borderRadius: 8, background: "#0ea5e9",
                    color: "#fff", border: 0, fontSize: 12, fontWeight: 700,
                    cursor: "pointer",
                  }}>
          ➕ Adicionar NAS
        </button>
        <button onClick={load} style={refBtn}>🔄 Atualizar</button>
      </div>

      {items.length === 0 && !loading && (
        <div style={{ padding: 40, background: "#f8fafc", borderRadius: 8,
                        textAlign: "center", color: "#64748b" }}>
          Nenhum NAS cadastrado. Adicione seu primeiro Mikrotik/concentrador.
        </div>
      )}

      <div style={{ display: "grid", gap: 8 }}>
        {items.map((n) => (
          <div key={n.id} data-testid={`nas-${n.id}`}
                style={{
                  background: "#fff", border: "1px solid #e2e8f0",
                  borderLeft: "4px solid #7c3aed",
                  borderRadius: 10, padding: 14,
                  display: "grid",
                  gridTemplateColumns: "1fr auto", gap: 12,
                }}>
            <div>
              <div style={{ display: "flex", gap: 10, alignItems: "center",
                              flexWrap: "wrap", marginBottom: 6 }}>
                <span style={{ fontWeight: 800, fontSize: 15,
                                color: "#0f172a" }}>
                  {n.name}
                </span>
                <span style={{ padding: "2px 8px", borderRadius: 99,
                                background: "#ede9fe", color: "#5b21b6",
                                fontSize: 11, fontWeight: 700 }}>
                  {(n.vendor || "generic").toUpperCase()}
                </span>
                <code style={{ fontSize: 12, color: "#475569",
                                background: "#f1f5f9",
                                padding: "1px 7px", borderRadius: 4 }}>
                  {n.ip}:{n.coa_port}
                </code>
              </div>
              {n.description && (
                <div style={{ fontSize: 12, color: "#64748b" }}>
                  {n.description}
                </div>
              )}
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>
                {n.last_seen_at
                  ? `🟢 visto em ${fmtDateBr(n.last_seen_at)}`
                  : "⚪ ainda não recebeu pacote"}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <button data-testid={`nas-test-${n.id}`}
                        onClick={() => setTesting(n)}
                        style={{
                          padding: "6px 12px", borderRadius: 7,
                          background: "#ecfdf5", color: "#065f46",
                          border: "1px solid #6ee7b7", fontSize: 11,
                          fontWeight: 700, cursor: "pointer",
                        }}>🧪 Testar</button>
              <button data-testid={`nas-edit-${n.id}`}
                        onClick={() => { setEditing(n); setShowForm(true); }}
                        style={{
                          padding: "6px 12px", borderRadius: 7,
                          background: "#f1f5f9", color: "#0f172a",
                          border: "1px solid #cbd5e1", fontSize: 11,
                          fontWeight: 700, cursor: "pointer",
                        }}>✏️ Editar</button>
              <button data-testid={`nas-delete-${n.id}`}
                        onClick={() => remove(n)}
                        style={{
                          padding: "6px 12px", borderRadius: 7,
                          background: "#fef2f2", color: "#991b1b",
                          border: "1px solid #fecaca", fontSize: 11,
                          fontWeight: 700, cursor: "pointer",
                        }}>🗑️ Remover</button>
            </div>
          </div>
        ))}
      </div>

      {showForm && (
        <NasFormModal initial={editing}
          onClose={() => { setShowForm(false); setEditing(null); }}
          onSaved={() => { setShowForm(false); setEditing(null); load(); }} />
      )}
      {testing && (
        <NasTestModal nas={testing} onClose={() => setTesting(null)} />
      )}
    </div>
  );
}


function NasFormModal({ initial, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: initial?.name || "",
    ip: initial?.ip || "",
    shared_secret: "",
    vendor: initial?.vendor || "mikrotik",
    coa_port: initial?.coa_port || 3799,
    description: initial?.description || "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  function set(k) {
    return (e) => setForm({ ...form,
      [k]: e?.target ? e.target.value : e });
  }

  async function submit() {
    if (!form.name || !form.ip) { setErr("Preencha nome e IP"); return; }
    if (!form.shared_secret || form.shared_secret.length < 4) {
      setErr("Shared secret mínimo 4 chars"); return;
    }
    setBusy(true); setErr(null);
    try {
      await api.radiusNasUpsert({ ...form,
        coa_port: parseInt(form.coa_port) || 3799 });
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  return (
    <div onClick={onClose} data-testid="nas-form-modal"
          style={{
            position: "fixed", inset: 0, zIndex: 9500,
            background: "rgba(15,23,42,0.75)",
            display: "grid", placeItems: "center", padding: 20,
            overflowY: "auto",
          }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{
              background: "#fff", borderRadius: 14, padding: 22,
              width: "100%", maxWidth: 500,
              boxShadow: "0 25px 60px rgba(0,0,0,0.4)",
            }}>
        <h3 style={{ margin: "0 0 16px", fontSize: 17, fontWeight: 800 }}>
          {initial ? "✏️ Editar NAS" : "➕ Adicionar NAS"}
        </h3>
        <Field label="Nome *">
          <input data-testid="nas-form-name" value={form.name}
                  onChange={set("name")} style={inp} />
        </Field>
        <Field label="IP do NAS *">
          <input data-testid="nas-form-ip" value={form.ip}
                  onChange={set("ip")} placeholder="ex: 10.10.10.1"
                  style={inp} disabled={!!initial} />
        </Field>
        <Field label={`Shared Secret * ${initial ? "(deixe igual ou cole novo)" : ""}`}>
          <input data-testid="nas-form-secret" type="text"
                  value={form.shared_secret}
                  onChange={set("shared_secret")}
                  placeholder="senha compartilhada com o NAS"
                  style={inp} />
        </Field>
        <Row>
          <Field label="Vendor" half>
            <select data-testid="nas-form-vendor" value={form.vendor}
                      onChange={(e) => {
                        const v = e.target.value;
                        // CoA port default por vendor:
                        // Mikrotik=3799 (RFC 5176), Cisco/Huawei=1700 (alguns
                        // deployments) ou 3799 default. Mantém atual se user
                        // já mexeu, senão ajusta.
                        const port_default = v === "cisco_asr"
                          ? 1700 : 3799;
                        setForm((s) => ({ ...s, vendor: v,
                          coa_port: s.coa_port === 3799 || s.coa_port === 1700
                            ? port_default : s.coa_port }));
                      }} style={inp}>
              <option value="mikrotik">Mikrotik (RouterOS)</option>
              <option value="cisco_asr">Cisco ASR 1000/9000 (ISG)</option>
              <option value="huawei">Huawei (NE40/MA5800/ME60)</option>
              <option value="cisco">Cisco IOS (genérico)</option>
              <option value="generic">Genérico RFC2865</option>
            </select>
          </Field>
          <Field label="CoA Port" half>
            <input data-testid="nas-form-coa" type="number"
                    value={form.coa_port}
                    onChange={set("coa_port")} style={inp} />
          </Field>
        </Row>
        <Field label="Descrição (opcional)">
          <input data-testid="nas-form-desc" value={form.description}
                  onChange={set("description")} style={inp} />
        </Field>

        {form.vendor === "cisco_asr" && (
          <div style={{
            padding: 12, borderRadius: 8, marginBottom: 12,
            background: "#eff6ff", border: "1px solid #bfdbfe",
            fontSize: 11, color: "#1e3a8a", lineHeight: 1.5,
          }}>
            <div style={{ fontWeight: 800, marginBottom: 4 }}>
              💡 Cisco ASR 1002-X — configuração no equipamento
            </div>
            <div>
              No ASR rode os comandos abaixo (substitua IPs/secret):
            </div>
            <pre style={{ background: "#0f172a", color: "#cbd5e1",
                            padding: 8, borderRadius: 5, marginTop: 6,
                            fontSize: 10, overflow: "auto" }}>
{`aaa group server radius SMARTPROV
 server-private ${form.ip || "<IP_BACKEND>"} auth-port 1812 acct-port 1813 key ${form.shared_secret || "<SECRET>"}
!
aaa authentication ppp default group SMARTPROV
aaa authorization network default group SMARTPROV
aaa accounting network default start-stop group SMARTPROV
!
! CoA Listener
aaa server radius dynamic-author
 client ${form.ip || "<IP_BACKEND>"} server-key ${form.shared_secret || "<SECRET>"}
 port ${form.coa_port || 1700}
 auth-type any
!
! Policy maps de QoS já configurados no ASR
policy-map PMAP_OUT_30720K
 class class-default
  shape average 30720000`}
            </pre>
            <div style={{ marginTop: 4 }}>
              Backend retorna <code>Cisco-AVPair: subscriber:service-name=BW_XM_YM</code>
              {" "}para acionar policy-maps que devem existir no ASR.
            </div>
          </div>
        )}
        {err && (
          <div style={{ padding: 10, background: "#fef2f2",
                          color: "#991b1b", borderRadius: 7,
                          fontSize: 12, marginBottom: 8 }}>❌ {err}</div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button onClick={onClose} data-testid="nas-form-cancel"
                    style={{ padding: "8px 14px", borderRadius: 8,
                              background: "#f1f5f9", color: "#0f172a",
                              border: 0, fontSize: 12, fontWeight: 700,
                              cursor: "pointer" }}>Cancelar</button>
          <button onClick={submit} disabled={busy} data-testid="nas-form-save"
                    style={{ padding: "8px 14px", borderRadius: 8,
                              background: "#0ea5e9", color: "#fff",
                              border: 0, fontSize: 12, fontWeight: 700,
                              cursor: "pointer",
                              opacity: busy ? 0.5 : 1 }}>
            {busy ? "Salvando…" : "💾 Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}


function Field({ label, children, half }) {
  return (
    <div style={{ marginBottom: 12, flex: half ? 1 : "1 1 auto",
                    minWidth: 0 }}>
      <label style={{ fontSize: 11, color: "#64748b", fontWeight: 700,
                        display: "block", marginBottom: 4,
                        textTransform: "uppercase",
                        letterSpacing: 0.4 }}>{label}</label>
      {children}
    </div>
  );
}


function Row({ children }) {
  return (
    <div style={{ display: "flex", gap: 10 }}>{children}</div>
  );
}


const refBtn = {
  padding: "8px 14px", borderRadius: 8, background: "#f1f5f9",
  color: "#0f172a", border: "1px solid #cbd5e1", fontSize: 12,
  fontWeight: 700, cursor: "pointer",
};

const inp = {
  width: "100%", padding: "8px 11px", border: "1px solid #cbd5e1",
  borderRadius: 7, fontSize: 13, outline: "none",
  background: "#fff", boxSizing: "border-box",
};



/* =============================================================
   NasTestModal — Testar conexão RADIUS de um NAS.
   Envia Access-Request fake (com username de teste), valida shared_secret
   + dictionary + montagem de policies do vendor + reply HMAC.
============================================================= */
function NasTestModal({ nas, onClose }) {
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState(null);
  const [err, setErr] = React.useState("");

  async function runTest() {
    if (!username.trim()) {
      setErr("Informe um username (ex: pppoe user de um assinante ativo).");
      return;
    }
    setBusy(true); setErr(""); setResult(null);
    try {
      const r = await api.radiusNasTest(nas.id, {
        username: username.trim(), password: password,
      });
      setResult(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  return (
    <div onClick={onClose} data-testid="nas-test-modal" style={{
      position: "fixed", inset: 0, zIndex: 1200,
      background: "rgba(15,23,42,.7)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 16, overflowY: "auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "#fff", borderRadius: 12, padding: 22,
        width: "min(94vw, 680px)", maxHeight: "92vh", overflowY: "auto",
        boxShadow: "0 20px 60px rgba(0,0,0,.35)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10,
                        marginBottom: 6 }}>
          <span style={{ fontSize: 22 }}>🧪</span>
          <div style={{ flex: 1 }}>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                          color: "#0f172a" }}>
              Testar conexão · {nas.name}
            </h3>
            <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
              {(nas.vendor || "generic").toUpperCase()} · {nas.ip}:{nas.coa_port}
            </div>
          </div>
          <button onClick={onClose} style={{
            background: "transparent", border: 0, fontSize: 22,
            cursor: "pointer", color: "#64748b",
          }}>×</button>
        </div>

        <p style={{ fontSize: 11.5, color: "#64748b", marginTop: 4,
                      marginBottom: 14, lineHeight: 1.5 }}>
          Constrói um Access-Request RADIUS válido (assinado com o
          shared_secret deste NAS), invoca a lógica interna de auth e
          devolve o pacote de reply (Access-Accept/Reject) com os atributos
          que seriam aplicados no NAS — <strong>sem precisar autenticar um
          cliente real</strong>.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 10, marginBottom: 12 }}>
          <label style={{ display: "block" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                            textTransform: "uppercase", letterSpacing: 0.4,
                            marginBottom: 4 }}>
              Username (PPPoE) *
            </div>
            <input data-testid="nas-test-username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="ex: 0800_IrmaoJulinho_Mercadinho"
                    style={inp} />
          </label>
          <label style={{ display: "block" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                            textTransform: "uppercase", letterSpacing: 0.4,
                            marginBottom: 4 }}>
              Senha (vazio = usa a do assinante)
            </div>
            <input data-testid="nas-test-password"
                    value={password} type="password"
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="deixe vazio pra testar Accept"
                    style={inp} />
          </label>
        </div>

        {err && (
          <div style={{ padding: 10, borderRadius: 7, marginBottom: 10,
                          background: "#fef2f2", color: "#991b1b",
                          fontSize: 12, border: "1px solid #fecaca" }}>
            ⚠ {err}
          </div>
        )}

        <button data-testid="nas-test-run"
                onClick={runTest} disabled={busy}
                style={{
                  padding: "10px 18px", borderRadius: 8,
                  background: busy ? "#94a3b8"
                    : "linear-gradient(135deg,#16a34a,#0d9488)",
                  color: "#fff", border: 0, fontSize: 13, fontWeight: 700,
                  cursor: busy ? "wait" : "pointer", width: "100%",
                }}>
          {busy ? "Testando…" : "▶ Enviar Access-Request fake"}
        </button>

        {result && (
          <div data-testid="nas-test-result" style={{ marginTop: 16 }}>
            {/* Header status */}
            <div style={{
              padding: 12, borderRadius: 9,
              background: result.ok ? "#ecfdf5" : "#fef2f2",
              border: `1.5px solid ${result.ok ? "#6ee7b7" : "#fecaca"}`,
              marginBottom: 12,
            }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 10,
                fontSize: 15, fontWeight: 800,
                color: result.ok ? "#065f46" : "#991b1b",
              }}>
                {result.ok ? "✅ Access-Accept" : "❌ Access-Reject"}
                <span style={{ fontSize: 11, fontWeight: 600, color: "#64748b" }}>
                  · {result.elapsed_ms}ms
                </span>
              </div>
              {result.reason && (
                <div style={{ fontSize: 12, color: "#7f1d1d", marginTop: 4 }}>
                  Motivo: {result.reason}
                </div>
              )}
              {result.subscriber && (
                <div style={{ fontSize: 12, color: "#0f172a", marginTop: 4 }}>
                  Assinante: <strong>{result.subscriber.name}</strong>
                  {" · "}status <strong>{result.subscriber.status}</strong>
                  {" · "}radius_state <strong>{result.radius_state}</strong>
                </div>
              )}
            </div>

            {/* Pyrad diagnostics */}
            <div style={{
              padding: 10, borderRadius: 8, background: "#f8fafc",
              border: "1px solid #e2e8f0", marginBottom: 12,
            }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                              textTransform: "uppercase", letterSpacing: 0.4,
                              marginBottom: 6 }}>
                Pipeline pyrad (validação binária)
              </div>
              <div style={{ display: "grid",
                              gridTemplateColumns: "1fr 1fr", gap: 6,
                              fontSize: 12 }}>
                <DiagItem label="Request encoded"
                  ok={result.diagnostics?.pyrad?.request_encoded}
                  sub={`${result.diagnostics?.pyrad?.request_size_bytes || 0}B`} />
                <DiagItem label="Reply encoded"
                  ok={result.diagnostics?.pyrad?.reply_encoded}
                  sub={`${result.diagnostics?.pyrad?.reply_size_bytes || 0}B`} />
              </div>
              {result.diagnostics?.errors?.length > 0 && (
                <div style={{ marginTop: 8, fontSize: 11, color: "#991b1b" }}>
                  ⚠ {result.diagnostics.errors.join(" · ")}
                </div>
              )}
            </div>

            {/* Atributos aplicados */}
            {Object.keys(result.attributes || {}).length > 0 && (
              <div style={{
                padding: 12, borderRadius: 8,
                background: "#0f172a", color: "#e2e8f0",
                fontFamily: "ui-monospace, Menlo, monospace",
                fontSize: 11.5, lineHeight: 1.6,
              }}>
                <div style={{ fontSize: 10, color: "#94a3b8",
                                marginBottom: 6, letterSpacing: 0.4 }}>
                  RADIUS Reply Attributes ({(nas.vendor || "generic").toUpperCase()})
                </div>
                {Object.entries(result.attributes).map(([k, v]) => (
                  <div key={k} style={{ marginBottom: 2 }}>
                    <span style={{ color: "#22d3ee" }}>{k}</span>
                    <span style={{ color: "#64748b" }}>{" = "}</span>
                    <span style={{ color: "#fef3c7" }}>
                      {Array.isArray(v) ? (
                        <>[<br/>{v.map((vv, i) => (
                          <span key={i}>
                            &nbsp;&nbsp;"{vv}"{i < v.length - 1 ? "," : ""}<br/>
                          </span>
                        ))}]</>
                      ) : (
                        typeof v === "string" ? `"${v}"` : String(v)
                      )}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function DiagItem({ label, ok, sub }) {
  return (
    <div style={{
      padding: "6px 10px", borderRadius: 6,
      background: ok ? "#dcfce7" : "#fef2f2",
      border: `1px solid ${ok ? "#bbf7d0" : "#fecaca"}`,
      display: "flex", alignItems: "center", gap: 6,
    }}>
      <span>{ok ? "✓" : "✗"}</span>
      <span style={{ flex: 1, fontWeight: 700,
                       color: ok ? "#065f46" : "#991b1b" }}>{label}</span>
      <span style={{ fontSize: 10, color: "#64748b" }}>{sub}</span>
    </div>
  );
}
