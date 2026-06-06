/* SmartoltLiveCard — card de sinal SmartOLT da ONU do cliente, com botão
 * "Live" que força refresh real (bypassa cache TTL E circuit-breaker
 * local de rate-limit no backend, iter215).
 *
 * Usado em DUAS situações:
 * 1) Painel admin (gestor) — via /api/lousa/tickets/{id}/signal
 * 2) App do colaborador — via /api/lousa/public/tickets/{id}/signal
 *    (sem auth, usa collaborator_id pra validar dono da OS)
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

function signalQuality(rx) {
  const v = parseFloat(rx);
  if (isNaN(v)) return { color: "#64748b", label: "—", bg: "#f1f5f9" };
  if (v >= -23) return { color: "#15803d", label: "Excelente", bg: "#dcfce7" };
  if (v >= -27) return { color: "#a16207", label: "Atenção", bg: "#fef3c7" };
  return { color: "#b91c1c", label: "Crítico", bg: "#fee2e2" };
}

export default function SmartoltLiveCard({
  ticketId,
  collaboratorId,         // se passado → usa endpoint público
  initiallyExpanded = true,
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState("");
  const [expanded, setExpanded] = useState(initiallyExpanded);

  const fetcher = useCallback(async (refresh) => {
    if (collaboratorId) {
      return api.lousaPublicTicketSignal(ticketId, collaboratorId, refresh);
    }
    return api.lousaTicketSignal(ticketId, refresh);
  }, [ticketId, collaboratorId]);

  const load = useCallback(async (refresh) => {
    setErr("");
    if (refresh) setRefreshing(true); else setLoading(true);
    try {
      const d = await fetcher(refresh);
      setData(d);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [fetcher]);

  useEffect(() => { load(false); }, [load]);

  const wrap = {
    border: "1px solid #e2e8f0", borderRadius: 12, padding: 12,
    marginBottom: 12, background: "#f8fafc",
  };

  if (loading) {
    return (
      <div style={wrap} data-testid="smartolt-live-loading">
        Buscando sinal SmartOLT…
      </div>
    );
  }
  if (err) {
    return (
      <div style={{ ...wrap, background: "#fee2e2", color: "#7f1d1d" }}
             data-testid="smartolt-live-error">
        ️ {err}
      </div>
    );
  }
  if (!data?.found) {
    const reason = data?.reason;
    const friendly = {
      missing_pppoe_and_name: "Bolha sem nome/PPPoE.",
      no_match: "Cliente não encontrado no SmartOLT.",
      smartolt_module_missing: "Módulo SmartOLT indisponível.",
    }[reason] || "Sem sinal disponível.";
    return (
      <div style={{ ...wrap, background: "#fef9c3", color: "#713f12" }}
             data-testid="smartolt-live-not-found">
        {friendly}
      </div>
    );
  }

  const onu = data.onu || {};
  const rx = onu.signal_1490 || onu.signal_1310;
  const q = signalQuality(rx);
  const isLive = data.cached === false;
  const statusOk = onu.status === "Online";

  return (
    <div style={wrap} data-testid="smartolt-live-card">
      <div style={{ display: "flex", alignItems: "flex-start",
                       justifyContent: "space-between", gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 10, fontWeight: 800, color: "#475569",
                          textTransform: "uppercase", letterSpacing: 0.4,
                          marginBottom: 6 }}>
            Sinal SmartOLT · match {data.match_strategy}
            <span style={{
              marginLeft: 6,
              color: isLive ? "#16a34a" : "#64748b",
              fontSize: 9,
            }}>
              ● {isLive ? "LIVE" : "CACHE"}
            </span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6,
                            alignItems: "center" }}>
            <span style={{
              padding: "4px 10px", borderRadius: 999,
              background: q.bg, color: q.color,
              fontWeight: 800, fontSize: 14, fontFamily: "monospace",
            }} data-testid="smartolt-live-rx">
              {rx ? `${rx} dBm` : "—"}
            </span>
            <span style={{ fontSize: 11, color: q.color, fontWeight: 700 }}>
              {q.label}
            </span>
            <span style={{
              padding: "2px 8px", borderRadius: 6, background: "white",
              border: `1px solid ${statusOk ? "#15803d" : "#b91c1c"}33`,
              color: statusOk ? "#15803d" : "#b91c1c",
              fontSize: 10, fontWeight: 700,
            }} data-testid="smartolt-live-status">
              {onu.status || "?"}
            </span>
          </div>
          {expanded && (
            <div style={{ marginTop: 6, fontSize: 11, color: "#475569",
                            lineHeight: 1.5 }}>
              <div><b>{onu.name}</b>{onu.onu_type_name ? ` · ${onu.onu_type_name}` : ""}</div>
              {onu.olt_name && (
                <div>
                  {onu.olt_name} · Board {onu.board} / Port {onu.port}
                  {" · "}ONU {onu.onu}
                </div>
              )}
              {(onu.sn || onu.unique_external_id) && (
                <div style={{ fontFamily: "monospace", color: "#64748b" }}>
                  SN: {onu.sn || onu.unique_external_id}
                </div>
              )}
              {onu.last_status_change && (
                <div style={{ color: "#64748b" }}>
                  Última mudança: {onu.last_status_change}
                </div>
              )}
            </div>
          )}
          {data.warning && (
            <div style={{ marginTop: 6, fontSize: 10, color: "#a16207",
                            lineHeight: 1.4 }}>
              {data.warning}
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <button
            type="button"
            data-testid="smartolt-live-refresh-btn"
            onClick={() => load(true)} disabled={refreshing}
            style={{
              background: refreshing ? "#cbd5e1" : "#0f172a",
              color: "white", border: 0, borderRadius: 8,
              padding: "8px 12px", fontSize: 11, fontWeight: 800,
              cursor: refreshing ? "wait" : "pointer",
              whiteSpace: "nowrap",
              boxShadow: "0 2px 4px rgba(0,0,0,0.15)",
            }}
          >
            {refreshing ? "…" : "Live"}
          </button>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            style={{
              background: "transparent", border: "1px solid #cbd5e1",
              borderRadius: 8, padding: "4px 10px", fontSize: 10,
              cursor: "pointer", color: "#475569",
            }}
          >
            {expanded ? "▲" : "▼"}
          </button>
        </div>
      </div>
    </div>
  );
}
