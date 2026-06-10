import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { Row } from "@/ui";
import { appCard, sectionLabel, softBtn } from "@/FieldOps";

/* =============================================================
   ISABELLA FIELD PRESIDENT — dentro do Smart Field Ops.
   Briefing dinâmico, rota recomendada, alertas de estoque e
   frota. Tudo calculado pelo SmartProv com dados reais
   (/api/field/isabella/*). Visual 100% SmartProv.
============================================================= */

const isaHeader = {
  display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
};
const isaBadge = {
  fontSize: 9, fontWeight: 800, letterSpacing: 1.2, color: "white",
  background: "#0f172a", padding: "4px 8px", borderRadius: 6,
  textTransform: "uppercase",
};

export function IsabellaCard({ collabId, onOpenOs }) {
  const [brief, setBrief] = useState(null);
  const [err, setErr] = useState(null);
  const [showRoute, setShowRoute] = useState(false);

  const load = useCallback(async () => {
    try {
      setErr(null);
      const b = await api.isabellaBriefing(collabId);
      setBrief(b);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }, [collabId]);
  useEffect(() => { load(); }, [load]);

  if (err) {
    return (
      <div style={{ ...appCard, padding: 14 }} data-testid="isabella-card-error">
        <div style={isaHeader}><span style={isaBadge}>Isabella Field President</span></div>
        <div style={{ fontSize: 12, color: "#991b1b" }}>{String(err)}</div>
      </div>
    );
  }
  if (!brief) {
    return (
      <div style={{ ...appCard, padding: 14 }} data-testid="isabella-card-loading">
        <div style={isaHeader}><span style={isaBadge}>Isabella Field President</span></div>
        <div style={{ fontSize: 12, color: "#64748b" }}>Analisando sua operação…</div>
      </div>
    );
  }

  const rec = brief.recommended_os;
  const route = brief.route || [];

  return (
    <div data-testid="isabella-card" style={{ ...appCard, padding: 16, border: "1.5px solid #0f172a" }}>
      <div style={isaHeader}>
        <span style={isaBadge}>Isabella Field President</span>
        {brief.gps_active
          ? <span style={{ fontSize: 10, color: "#065f46", fontWeight: 700 }}>GPS ativo</span>
          : <span style={{ fontSize: 10, color: "#b45309", fontWeight: 700 }}>sem GPS recente</span>}
      </div>

      <div data-testid="isabella-headline" style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", lineHeight: 1.5 }}>
        {brief.headline}
      </div>

      {rec && (
        <button data-testid="isabella-recommendation" onClick={() => onOpenOs && onOpenOs(rec.ticket_id)}
          style={{ display: "block", width: "100%", textAlign: "left", marginTop: 12, padding: 12,
            borderRadius: 10, background: "#f8fafc", border: "1px solid #e2e8f0", cursor: "pointer" }}>
          <div style={{ ...sectionLabel, marginBottom: 6 }}>Por que começar por {rec.client}?</div>
          {(rec.reasons || []).map((r, i) => (
            <div key={i} style={{ fontSize: 12, color: "#334155", padding: "2px 0", display: "flex", gap: 6 }}>
              <span style={{ color: "#0f172a", fontWeight: 800 }}>·</span> {r}
            </div>
          ))}
        </button>
      )}

      {(brief.stock_alerts || []).length > 0 && (
        <div data-testid="isabella-stock-alerts" style={{ marginTop: 10, padding: 10, borderRadius: 10, background: "#fffbeb", border: "1px solid #fcd34d" }}>
          <div style={{ ...sectionLabel, color: "#92400e", marginBottom: 4 }}>Estoque antes de sair</div>
          {brief.stock_alerts.slice(0, 3).map((a, i) => (
            <div key={i} style={{ fontSize: 11, color: "#78350f", padding: "2px 0" }}>{a.msg}</div>
          ))}
        </div>
      )}

      {route.length > 1 && (
        <div style={{ marginTop: 10 }}>
          <button data-testid="isabella-route-toggle" onClick={() => setShowRoute(!showRoute)}
            style={{ ...softBtn, height: 38, fontSize: 12 }}>
            {showRoute ? "Ocultar rota" : `Rota recomendada pela Isabella (${route.length} paradas)`}
          </button>
          {showRoute && (
            <div data-testid="isabella-route" style={{ marginTop: 8 }}>
              {route.map((r) => (
                <button key={r.ticket_id} onClick={() => onOpenOs && onOpenOs(r.ticket_id)}
                  data-testid={`isabella-route-stop-${r.route_position}`}
                  style={{ display: "flex", width: "100%", textAlign: "left", gap: 10, alignItems: "center",
                    padding: "8px 6px", borderBottom: "1px solid #f1f5f9", background: "none",
                    border: "none", borderBottomStyle: "solid", cursor: "pointer" }}>
                  <span style={{ width: 22, height: 22, borderRadius: "50%", background: "#0f172a", color: "white",
                    fontSize: 11, fontWeight: 800, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                    {r.route_position}
                  </span>
                  <span style={{ flex: 1 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: "#0f172a", display: "block" }}>{r.client}</span>
                    <span style={{ fontSize: 10, color: "#64748b" }}>
                      {r.type}{r.distance_km != null ? ` · ${r.distance_km} km` : ""} · resolução {r.resolution_probability}%
                    </span>
                  </span>
                </button>
              ))}
              {brief.route_changed_vs_schedule && (
                <div style={{ fontSize: 10, color: "#64748b", marginTop: 6 }}>
                  Isabella reordenou a agenda por SLA, distância e probabilidade de resolução.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {brief.fleet?.isabella_score && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#475569" }}>
          Frota: nota {brief.fleet.isabella_score.nota}/10
          {brief.fleet.alvaro ? ` · Álvaro: risco ${brief.fleet.alvaro.risco_quebra}` : ""}
        </div>
      )}
    </div>
  );
}

/* Brief pré-visita por OS (Instalação/Reparo/Retirada Inteligente) */
export function IsabellaOsBrief({ ticketId, collabId }) {
  const [brief, setBrief] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let on = true;
    api.isabellaOsBrief(ticketId, collabId)
      .then((b) => on && setBrief(b))
      .catch((e) => on && setErr(e?.response?.data?.detail || e.message));
    return () => { on = false; };
  }, [ticketId, collabId]);

  if (err) return null;
  if (!brief) {
    return (
      <div style={{ ...appCard, padding: 14 }} data-testid="isabella-brief-loading">
        <div style={isaHeader}><span style={isaBadge}>Isabella</span></div>
        <div style={{ fontSize: 12, color: "#64748b" }}>Preparando análise da OS…</div>
      </div>
    );
  }

  const cto = brief.cto_suggestion || {};
  return (
    <div data-testid="isabella-os-brief" style={{ ...appCard, padding: 14, border: "1.5px solid #0f172a" }}>
      <div style={isaHeader}>
        <span style={isaBadge}>Isabella · análise pré-visita</span>
      </div>
      <Row label="Probabilidade de resolução"
        value={`${brief.resolution_probability}%${brief.probability_sample ? ` (${brief.probability_sample} OS reais)` : ""}`} />

      {brief.type === "instalacao" && (
        <>
          {cto.cto_name && <Row label="CTO sugerida" value={`${cto.cto_name}${cto.port_number ? ` · porta ${cto.port_number}` : ""}`} />}
          {cto.expected_signal_dbm != null && <Row label="Previsão de sinal" value={`${cto.expected_signal_dbm} dBm (média de ${cto.signal_sample} portas)`} />}
          {brief.suggested_materials && (
            <Row label="Materiais sugeridos"
              value={`drop ${brief.suggested_materials.qtd_drop}m · ${brief.suggested_materials.esticadores} esticadores · ${brief.suggested_materials.conectores_fast} fast`} />
          )}
          {brief.region_risk && (
            <Row label="Risco da região"
              value={`${brief.region_risk.level.toUpperCase()} (${brief.region_risk.repairs_90d} reparos/90d em ${brief.region_risk.neighborhood})`} />
          )}
        </>
      )}

      {brief.type === "reparo" && (
        <>
          {(brief.probable_causes || []).length > 0 ? (
            <div style={{ margin: "8px 0" }}>
              <div style={{ ...sectionLabel, marginBottom: 4 }}>Causa provável (histórico real)</div>
              {brief.probable_causes.map((c, i) => (
                <div key={i} style={{ fontSize: 12, color: "#334155", padding: "2px 0" }}>
                  {c.cause} — <strong>{c.probability}%</strong> ({c.sample} casos · {c.scope})
                </div>
              ))}
            </div>
          ) : (
            <Row label="Causa provável" value="Sem histórico classificado ainda — Isabella aprende a cada reparo" />
          )}
          {brief.client_repairs_60d >= 2 && (
            <Row label="Reincidência" value={`${brief.client_repairs_60d} reparos deste cliente em 60 dias`} />
          )}
          {brief.cto_context && (
            <Row label="CTO do cliente" value={`${brief.cto_context.cto_name || brief.cto_context.cto_id} · porta ${brief.cto_context.port_number} · ${brief.cto_context.repairs_60d} reparos/60d`} />
          )}
          {(brief.test_guidance || []).length > 0 && (
            <div style={{ marginTop: 8, padding: 10, borderRadius: 10, background: "#f8fafc", border: "1px solid #eef2f7" }}>
              <div style={{ ...sectionLabel, marginBottom: 4 }}>Roteiro de testes</div>
              {brief.test_guidance.map((g, i) => (
                <div key={i} style={{ fontSize: 11, color: "#475569", padding: "2px 0" }}>{i + 1}. {g}</div>
              ))}
            </div>
          )}
        </>
      )}

      {brief.type === "retirada" && brief.comodato && (
        <>
          <Row label="Valor do ativo (comodato)" value={`R$ ${Number(brief.comodato.asset_value).toFixed(2)}`} />
          {(brief.comodato.equipment || []).map((e) => (
            <Row key={e.mac} label="Equipamento no cliente" value={`${e.mac}${e.scan_sn ? ` · ${e.scan_sn}` : ""}`} />
          ))}
          <div style={{ fontSize: 11, color: "#78350f", background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 10, padding: 10, marginTop: 8 }}>
            {brief.comodato.guidance}
          </div>
        </>
      )}
    </div>
  );
}
