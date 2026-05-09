import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { Card, Button, Metric } from "@/ui";

const css = {
  pillCritical: { background: "#fee2e2", color: "#991b1b", padding: "2px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800 },
  pillWarn: { background: "#fef3c7", color: "#92400e", padding: "2px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800 },
  th: { padding: 10, textAlign: "left", background: "#f8fafc", fontSize: 11, fontWeight: 800, color: "#475569", textTransform: "uppercase", letterSpacing: 0.4 },
  td: { padding: 10, fontSize: 13, borderBottom: "1px solid #f1f5f9", verticalAlign: "top" },
  btnGhost: { padding: "6px 10px", border: "1px solid #cbd5e1", borderRadius: 8, background: "white", fontWeight: 700, fontSize: 11, cursor: "pointer", marginRight: 6 },
};

export default function AIPreventivePanel({ onClose, embedded = false }) {
  const [tab, setTab] = useState("suggestions");
  const [capacity, setCapacity] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [msg, setMsg] = useState(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [cap, sug] = await Promise.all([
        api.aiPrevCapacity(),
        api.aiPrevSuggestions("pending"),
      ]);
      setCapacity(cap); setSuggestions(sug);
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const doScan = async (force = false) => {
    setScanning(true); setMsg(null);
    try {
      const r = await api.aiPrevScan(force);
      setMsg({ type: "ok", text: `Scan OK · ${r.suggestions_created} novas sugestões de ${r.scanned_clients} clientes críticos em ${r.elapsed_seconds}s` });
      loadAll();
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    } finally { setScanning(false); }
  };

  const accept = async (sid) => {
    try { await api.aiPrevAccept(sid); loadAll(); }
    catch (e) { alert(`Erro: ${e?.response?.data?.detail || e.message}`); }
  };
  const reject = async (sid) => {
    if (!window.confirm("Recusar esta sugestão?")) return;
    try { await api.aiPrevReject(sid); loadAll(); }
    catch (e) { alert(`Erro: ${e?.response?.data?.detail || e.message}`); }
  };

  const Inner = (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: embedded ? 16 : 22, fontWeight: 800, color: "#0f172a" }}>🤖 IA Preventivas</h2>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748b" }}>
            Sugere notas preventivas para clientes com sinal crítico, respeitando o ritmo dos técnicos.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Button variant="soft" onClick={() => doScan(false)} disabled={scanning} data-testid="ai-scan-btn">
            {scanning ? "🔄 Escaneando…" : "🔍 Escanear agora"}
          </Button>
          <Button variant="soft" onClick={() => doScan(true)} disabled={scanning} data-testid="ai-scan-force-btn">
            ⚡ Scan força
          </Button>
          {!embedded && <Button onClick={onClose}>Fechar</Button>}
        </div>
      </div>
      {msg && (
        <div data-testid="ai-msg" style={{
          padding: 10, borderRadius: 10, marginBottom: 12, fontSize: 13, fontWeight: 600,
          background: msg.type === "ok" ? "#dcfce7" : "#fee2e2",
          color: msg.type === "ok" ? "#166534" : "#7f1d1d",
        }}>{msg.text}</div>
      )}
      <div style={{ display: "flex", gap: 4, padding: 4, background: "#e2e8f0", borderRadius: 12, marginBottom: 14, width: "fit-content" }}>
        {[
          { id: "suggestions", label: `📋 Sugestões (${suggestions.length})` },
          { id: "capacity", label: "📊 Capacidade dos técnicos" },
        ].map((tdef) => (
          <button key={tdef.id} onClick={() => setTab(tdef.id)}
                  data-testid={`ai-tab-${tdef.id}`}
                  style={{ padding: "8px 14px", border: "none", borderRadius: 8,
                           background: tab === tdef.id ? "white" : "transparent",
                           fontWeight: 700, fontSize: 13, cursor: "pointer" }}>
            {tdef.label}
          </button>
        ))}
      </div>
      {loading && <Card>Carregando…</Card>}
      {tab === "capacity" && capacity && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 14, marginBottom: 16 }}>
            <Metric label="Capacidade total hoje" value={capacity.total_capacity_today} data-testid="cap-total" />
            <Metric label="Ritmo total/dia" value={capacity.total_pace_per_day} />
            <Metric label="Técnicos ativos" value={capacity.techs.length} />
            <Metric label="Limiar crítico" value={`${capacity.config.critical_rx_dbm} dBm`} />
          </div>
          <Card title="👷 Capacidade por técnico (ritmo histórico × carga atual)">
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr>
                <th style={css.th}>Técnico</th><th style={css.th}>30d</th><th style={css.th}>Dias ativos</th>
                <th style={css.th}>Ritmo/dia</th><th style={css.th}>Carga hoje</th><th style={css.th}>Vagas livres</th>
              </tr></thead>
              <tbody>
                {capacity.techs.sort((a, b) => b.capacity_today - a.capacity_today).map((t) => (
                  <tr key={t.id} data-testid={`cap-row-${t.id}`}>
                    <td style={css.td}><strong>{t.name}</strong></td>
                    <td style={css.td}>{t.finalizadas_total_30d}</td>
                    <td style={css.td}>{t.dias_ativos_30d}</td>
                    <td style={css.td}><strong>{t.ritmo_efetivo}</strong>/dia</td>
                    <td style={css.td}>{t.carga_hoje}</td>
                    <td style={{ ...css.td, color: t.capacity_today > 0 ? "#15803d" : "#a16207", fontWeight: 800 }}>
                      {t.capacity_today > 0 ? `+${t.capacity_today}` : "0"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
      {tab === "suggestions" && (
        <Card title={`📋 ${suggestions.length} sugestão(ões) pendente(s)`} data-testid="ai-suggestions-card">
          {suggestions.length === 0 ? (
            <div style={{ padding: 30, textAlign: "center", color: "#64748b" }}>
              Sem sugestões pendentes. Clique em <strong>🔍 Escanear agora</strong> para gerar novas.
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr>
                <th style={css.th}>Cliente · OLT</th><th style={css.th}>Sinal</th>
                <th style={css.th}>Técnico sugerido</th><th style={css.th}>Cap. téc.</th><th style={css.th}>Ações</th>
              </tr></thead>
              <tbody>
                {suggestions.map((s) => (
                  <tr key={s.id} data-testid={`ai-sugg-row-${s.id}`}>
                    <td style={css.td}>
                      <strong>{s.client_name}</strong>
                      <div style={{ fontSize: 11, color: "#64748b" }}>{s.olt_name} · {s.zone_name}</div>
                    </td>
                    <td style={css.td}>
                      <span style={s.urgency === "critical" ? css.pillCritical : css.pillWarn}>
                        📶 {s.rx_dbm.toFixed(1)} dBm
                      </span>
                      <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>{s.urgency}</div>
                    </td>
                    <td style={css.td}>
                      <strong>{s.tech_name}</strong>
                      <div style={{ fontSize: 11, color: "#64748b" }}>ritmo {s.tech_pace}/dia</div>
                    </td>
                    <td style={css.td}>{s.tech_capacity_at_suggest} vagas</td>
                    <td style={css.td}>
                      <button style={{ ...css.btnGhost, background: "#dcfce7", color: "#15803d", borderColor: "#86efac" }}
                              onClick={() => accept(s.id)} data-testid={`ai-accept-${s.id}`}>✓ Aceitar</button>
                      <button style={{ ...css.btnGhost, background: "#fee2e2", color: "#991b1b", borderColor: "#fca5a5" }}
                              onClick={() => reject(s.id)} data-testid={`ai-reject-${s.id}`}>✕ Recusar</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </>
  );

  if (embedded) return <div data-testid="ai-preventive-panel">{Inner}</div>;
  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 100, padding: 20, overflowY: "auto" }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="ai-preventive-panel"
           style={{ background: "#f8fafc", maxWidth: 1100, margin: "0 auto", borderRadius: 18, padding: 22 }}>
        {Inner}
      </div>
    </div>
  );
}

