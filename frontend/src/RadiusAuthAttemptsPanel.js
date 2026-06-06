/**
 * RadiusAuthAttemptsPanel — Feed ao vivo de tentativas de auth RADIUS.
 *
 * Replica a página "Tentativas de conexão" do Atlaz:
 *   - Lista das últimas 200 tentativas (auto-refresh 5s)
 *   - Badge verde "Aceito" / vermelho "Rejeitado"
 *   - Expansível: NAS IP, atributos retornados, motivo da rejeição,
 *     MAC do cliente, IP da fonte, contract_id vinculado, radius_state
 *   - Botão "Pausar logs" pra freeze enquanto investiga
 *   - Filtros: só rejeitados / só aceitos / todos
 */
import React, { useEffect, useState, useRef, useCallback } from "react";
import { api } from "@/api";


function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("pt-BR", { hour12: false });
  } catch { return iso; }
}


function fmtFullDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR",
      { dateStyle: "short", timeStyle: "medium" });
  } catch { return iso; }
}


export default function RadiusAuthAttemptsPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState("all"); // all | accept | reject
  const [expanded, setExpanded] = useState({});
  const intervalRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const r = await api.radiusLogs({ type: "auth", limit: 200 });
      setItems(r.items || []);
    } catch (e) {
      console.warn("[auth-attempts]", e);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    if (!paused) {
      intervalRef.current = setInterval(load, 5000);
      return () => clearInterval(intervalRef.current);
    }
    return undefined;
  }, [load, paused]);

  const filtered = items.filter((l) => {
    if (filter === "accept") return l.result === "accept";
    if (filter === "reject") return l.result === "reject";
    return true;
  });

  const counts = {
    total: items.length,
    accept: items.filter((l) => l.result === "accept").length,
    reject: items.filter((l) => l.result === "reject").length,
  };

  return (
    <div data-testid="radius-auth-attempts" style={{ padding: 18 }}>
      <div style={{ marginBottom: 14 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800,
                        color: "#0f172a" }}>
          Tentativas de conexão
        </h2>
        <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 13 }}>
          Feed ao vivo de tentativas de autenticação PPPoE recebidas pelo
          RADIUS (últimas 200, atualiza a cada 5s).
        </p>
      </div>

      {/* Filtros + Pause */}
      <div style={{ display: "flex", gap: 6, alignItems: "center",
                      marginBottom: 14, flexWrap: "wrap" }}>
        {["all", "accept", "reject"].map((f) => (
          <button key={f} data-testid={`auth-filter-${f}`}
                    onClick={() => setFilter(f)}
                    style={{
                      padding: "6px 12px", borderRadius: 7, fontSize: 12,
                      fontWeight: 700, cursor: "pointer",
                      background: filter === f ? "#0f172a" : "#fff",
                      color: filter === f ? "#fff" : "#0f172a",
                      border: `1.5px solid ${
                        filter === f ? "#0f172a" : "#cbd5e1"}`,
                    }}>
            {f === "all"
              ? `Todos (${counts.total})`
              : f === "accept"
              ? `Aceitos (${counts.accept})`
              : `Rejeitados (${counts.reject})`}
          </button>
        ))}
        <span style={{
          marginLeft: 8, fontSize: 12, color: "#64748b",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          {!paused && (
            <span style={{
              width: 9, height: 9, borderRadius: 99,
              background: "#16a34a", display: "inline-block",
              animation: "pulse 1.5s ease-in-out infinite",
            }} />
          )}
          {paused
            ? "⏸ Logs pausados"
            : `Resultados (últimas ${filtered.length} tentativas)`}
        </span>
        <button data-testid="auth-pause"
                  onClick={() => setPaused(!paused)}
                  style={{
                    marginLeft: "auto", padding: "7px 13px", borderRadius: 7,
                    background: paused ? "#0ea5e9" : "#0ea5e9",
                    color: "#fff", border: 0, fontSize: 12, fontWeight: 700,
                    cursor: "pointer",
                  }}>
          {paused ? "▶ Retomar logs" : "⏸ Pausar logs"}
        </button>
        <button data-testid="auth-refresh" onClick={load}
                  style={{
                    padding: "7px 13px", borderRadius: 7,
                    background: "#f1f5f9", color: "#0f172a",
                    border: "1px solid #cbd5e1", fontSize: 12,
                    fontWeight: 700, cursor: "pointer",
                  }}></button>
      </div>

      {loading && (
        <div style={{ padding: 30, color: "#64748b" }}>⏳ Carregando…</div>
      )}
      {!loading && filtered.length === 0 && (
        <div style={{ padding: 40, background: "#f8fafc", borderRadius: 8,
                        textAlign: "center", color: "#64748b" }}>
          Nenhuma tentativa{" "}
          {filter === "reject" ? "rejeitada" :
            filter === "accept" ? "aceita" : ""} no momento.
        </div>
      )}

      <div style={{ display: "grid", gap: 6 }}>
        {filtered.map((log) => (
          <LogRow key={log.id} log={log}
            expanded={expanded[log.id]}
            onToggle={() => setExpanded({ ...expanded,
              [log.id]: !expanded[log.id] })}
          />
        ))}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(1.3); }
        }
      `}</style>
    </div>
  );
}


function LogRow({ log, expanded, onToggle }) {
  const isAccept = log.result === "accept";
  const isReject = log.result === "reject";
  const color = isAccept ? "#16a34a" : isReject ? "#dc2626" : "#94a3b8";

  return (
    <div data-testid={`auth-log-${log.id}`}
          style={{
            background: "#fff", border: "1px solid #e2e8f0",
            borderLeft: `4px solid ${color}`,
            borderRadius: 8, overflow: "hidden",
          }}>
      {/* HEADER (compacto) */}
      <button onClick={onToggle}
                data-testid={`auth-toggle-${log.id}`}
                style={{
                  width: "100%", display: "flex",
                  alignItems: "center", gap: 12,
                  padding: "12px 14px",
                  background: "transparent", border: 0,
                  cursor: "pointer", textAlign: "left",
                }}>
        <span style={{ fontSize: 13, color: "#94a3b8" }}>
          {expanded ? "▾" : "▸"}
        </span>
        <span style={{
          padding: "3px 10px", borderRadius: 6,
          background: isAccept ? "#16a34a" : "#dc2626",
          color: "#fff", fontSize: 11, fontWeight: 800,
          letterSpacing: 0.4, textTransform: "uppercase",
          minWidth: 80, textAlign: "center",
        }}>
          {isAccept ? "Aceito" : "Rejeitado"}
        </span>
        <span style={{ color: "#64748b", fontSize: 13,
                        fontFamily: "monospace" }}>
          {fmtTime(log.at)}
        </span>
        <span style={{ color: "#94a3b8" }}>·</span>
        <code style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
          {log.username || "—"}
        </code>
        {log.reason && isReject && (
          <span style={{
            marginLeft: "auto", padding: "2px 9px", borderRadius: 99,
            background: "#fee2e2", color: "#991b1b",
            fontSize: 11, fontWeight: 700,
          }}>{log.reason}</span>
        )}
        {log.radius_state && isAccept && (
          <span style={{
            marginLeft: "auto", padding: "2px 9px", borderRadius: 99,
            background: log.radius_state === "ATIVO" ? "#dcfce7" : "#fef3c7",
            color: log.radius_state === "ATIVO" ? "#14532d" : "#92400e",
            fontSize: 11, fontWeight: 700,
          }}>{log.radius_state}</span>
        )}
      </button>

      {/* DETALHES (expandido) */}
      {expanded && (
        <div style={{ padding: "10px 14px 14px 30px",
                        background: "#f8fafc",
                        borderTop: "1px solid #e2e8f0", fontSize: 12 }}>
          <div style={{ display: "grid",
                          gridTemplateColumns: "120px 1fr",
                          gap: "4px 10px", color: "#334155" }}>
            <Lbl>Quando</Lbl><Val>{fmtFullDate(log.at)}</Val>
            <Lbl>Usuário</Lbl>
            <Val><code style={{ fontSize: 11 }}>{log.username}</code></Val>
            {log.nas_ip && (<>
              <Lbl>NAS</Lbl><Val>{log.nas_ip}</Val>
            </>)}
            {log.src_ip && (<>
              <Lbl>IP fonte</Lbl><Val>{log.src_ip}</Val>
            </>)}
            {log.calling_station_id && (<>
              <Lbl>MAC cliente</Lbl>
              <Val><code style={{ fontSize: 11 }}>
                {log.calling_station_id}
              </code></Val>
            </>)}
            {log.subscriber_id && (<>
              <Lbl>Subscriber</Lbl>
              <Val><code style={{ fontSize: 11 }}>
                {log.subscriber_id}
              </code></Val>
            </>)}
            {log.contract_id && (<>
              <Lbl>Contrato</Lbl>
              <Val><code style={{ fontSize: 11 }}>
                {log.contract_id}
              </code></Val>
            </>)}
            {log.profile && (<>
              <Lbl>Perfil</Lbl><Val>{log.profile}</Val>
            </>)}
            {log.speed_down_kbps != null && (<>
              <Lbl>Velocidade</Lbl>
              <Val>
                ↓ <b>{log.speed_down_kbps} kbps</b>{" · "}
                ↑ <b>{log.speed_up_kbps} kbps</b>
              </Val>
            </>)}
            {log.reason && (<>
              <Lbl>Motivo</Lbl>
              <Val style={{ color: isReject ? "#991b1b" : "#475569" }}>
                <code style={{ fontSize: 11 }}>{log.reason}</code>
              </Val>
            </>)}
          </div>
        </div>
      )}
    </div>
  );
}


function Lbl({ children }) {
  return (
    <div style={{ color: "#94a3b8", fontWeight: 700,
                    textTransform: "uppercase", fontSize: 10,
                    letterSpacing: 0.4, alignSelf: "center" }}>
      {children}
    </div>
  );
}


function Val({ children, style = {} }) {
  return (
    <div style={{ color: "#0f172a", ...style }}>{children}</div>
  );
}
