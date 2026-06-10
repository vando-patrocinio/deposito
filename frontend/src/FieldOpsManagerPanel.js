import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

/* =============================================================
   Field Ops (Campo) — painel administrativo do gestor.
   Visão em tempo real do que os técnicos fazem no App Colaborador:
   técnicos em campo, OS, GPS, estoque, frota, retiradas e toggles.
   Fonte: GET /api/field/admin/overview (JWT + RBAC).
============================================================= */

const card = {
  background: "white", border: "1px solid #e5e7eb", borderRadius: 14,
  padding: 18, boxShadow: "0 1px 2px rgba(15,23,42,.04)",
};
const label = {
  fontSize: 10, fontWeight: 700, color: "#64748b",
  letterSpacing: 1, textTransform: "uppercase",
};
const th = {
  textAlign: "left", fontSize: 10, fontWeight: 700, color: "#64748b",
  textTransform: "uppercase", letterSpacing: 0.5, padding: "8px 10px",
  borderBottom: "1px solid #e5e7eb",
};
const td = {
  fontSize: 12, color: "#0f172a", padding: "8px 10px",
  borderBottom: "1px solid #f1f5f9",
};

function Kpi({ title, value, warn }) {
  return (
    <div style={{ ...card, padding: 14, flex: 1, minWidth: 130 }}>
      <div style={label}>{title}</div>
      <div style={{ fontSize: 26, fontWeight: 800, marginTop: 4, color: warn && value > 0 ? "#b91c1c" : "#0f172a" }}>
        {value ?? 0}
      </div>
    </div>
  );
}

function timeAgo(iso) {
  if (!iso) return "—";
  try {
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (min < 1) return "agora";
    if (min < 60) return `${min}min`;
    return `${Math.round(min / 60)}h`;
  } catch { return "—"; }
}

/* ISABELLA FIELD PRESIDENT — governança da Lousa + indicadores p/ Presidente IA */
function IsabellaGovernance() {
  const [summary, setSummary] = useState(null);
  const [lousa, setLousa] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.isabellaPresidentSummary().then(setSummary).catch((e) => setErr(e?.response?.data?.detail || e.message));
  }, []);

  const runLousa = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.isabellaLousaAnalysis();
      setLousa(r);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  return (
    <div style={card} data-testid="isabella-governance">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
        <div>
          <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: 1.2, color: "white", background: "#0f172a", padding: "4px 8px", borderRadius: 6, textTransform: "uppercase" }}>
            Isabella Field President
          </span>
          <span style={{ fontSize: 11, color: "#64748b", marginLeft: 8 }}>preside a operação de campo e alimenta o Presidente IA</span>
        </div>
        <button data-testid="isabella-run-lousa" onClick={runLousa} disabled={busy}
          style={{ height: 36, padding: "0 14px", borderRadius: 10, border: 0, background: "#0f172a", color: "white", fontWeight: 700, fontSize: 12, cursor: "pointer", opacity: busy ? 0.6 : 1 }}>
          {busy ? "Analisando Lousa…" : "Analisar Lousa agora"}
        </button>
      </div>

      {err && <div style={{ fontSize: 12, color: "#b91c1c", marginBottom: 8 }}>{String(err)}</div>}

      {summary && (
        <div data-testid="isabella-president-summary" style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 10 }}>
          {[["Finalizadas hoje", summary.finalizadas_hoje],
            ["Causas-raiz classificadas (30d)", summary.retrabalho_classificado_30d],
            ["Truck-roll evitado (30d)", summary.truck_roll_avoidance_30d],
            ["Nota média frota (30d)", summary.fleet_score_avg_30d ?? "—"],
            ["Comodato recuperado (30d)", `R$ ${(summary.equipment_recovered_30d_brl || 0).toFixed(2)}`],
            ["Perda comodato (30d)", `R$ ${(summary.equipment_lost_30d_brl || 0).toFixed(2)}`],
            ["Eventos de campo (30d)", summary.field_events_30d]].map(([l, v]) => (
            <div key={l} style={{ minWidth: 130 }}>
              <div style={{ fontSize: 16, fontWeight: 800, color: "#0f172a" }}>{v ?? 0}</div>
              <div style={{ fontSize: 9, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5 }}>{l}</div>
            </div>
          ))}
        </div>
      )}

      {summary?.techs_today?.length > 0 && (
        <div style={{ fontSize: 12, color: "#475569", marginBottom: 10 }}>
          {summary.techs_today.map((t) => (
            <span key={t.collaborator_id} style={{ marginRight: 14 }}>
              <strong style={{ color: "#0f172a" }}>{t.name || t.collaborator_id}</strong>: {t.finalizadas_hoje} OS
              {t.nota_media != null ? ` · nota ${t.nota_media}` : ""}
            </span>
          ))}
        </div>
      )}

      {lousa && (
        <div data-testid="isabella-lousa-result" style={{ overflowX: "auto" }}>
          <div style={{ fontSize: 11, color: "#065f46", fontWeight: 700, marginBottom: 6 }}>
            {lousa.count} bolha(s) analisadas e priorizadas — análise gravada em cada OS da Lousa.
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>#</th><th style={th}>Cliente</th><th style={th}>Tipo</th>
              <th style={th}>Risco</th><th style={th}>Previsão</th><th style={th}>Análise Isabella</th>
            </tr></thead>
            <tbody>
              {lousa.items.slice(0, 10).map((i) => (
                <tr key={i.ticket_id}>
                  <td style={{ ...td, fontWeight: 800 }}>{i.priority_rank}</td>
                  <td style={td}>{i.client}</td>
                  <td style={td}>{i.type}</td>
                  <td style={{ ...td, fontWeight: 700, color: i.risk === "alto" ? "#b91c1c" : (i.risk === "medio" ? "#b45309" : "#065f46") }}>{i.risk}</td>
                  <td style={td}>{i.prediction}</td>
                  <td style={{ ...td, fontSize: 11, color: "#475569" }}>{i.analysis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Toggle({ checked, onChange, testId, disabled }) {
  return (
    <button data-testid={testId} disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      style={{ width: 42, height: 24, borderRadius: 999, border: 0,
        cursor: disabled ? "wait" : "pointer", opacity: disabled ? 0.5 : 1,
        background: checked ? "#0f172a" : "#e2e8f0", position: "relative", transition: "background .15s" }}>
      <span style={{ position: "absolute", top: 3, left: checked ? 21 : 3, width: 18, height: 18,
        borderRadius: "50%", background: "white", transition: "left .15s" }} />
    </button>
  );
}

export default function FieldOpsManagerPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [saving, setSaving] = useState(false);
  const [cost, setCost] = useState("");

  const load = useCallback(async () => {
    try {
      setErr(null);
      const d = await api.fieldAdminOverview();
      setData(d);
      setCost(String(d.toggles?.equipment_default_cost ?? ""));
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const saveToggle = async (patch) => {
    setSaving(true);
    try {
      await api.fieldSettingsUpdate(patch);
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setSaving(false); }
  };

  if (err) {
    return <div style={{ ...card, color: "#b91c1c", fontSize: 13 }} data-testid="field-admin-error">{String(err)}</div>;
  }
  if (!data) return <div style={{ ...card, color: "#64748b", fontSize: 13 }}>Carregando Field Ops…</div>;

  const c = data.counts || {};
  const tg = data.toggles || {};
  const er = data.equipment_returns || {};

  return (
    <div data-testid="field-ops-admin-panel" style={{ display: "flex", flexDirection: "column", gap: 14, paddingBottom: 140 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: "#0f172a" }}>Field Ops — Operação de Campo</h2>
        <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
          Tudo que os técnicos fazem no App Colaborador, em tempo real. Atualiza a cada 60s.
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Kpi title="Técnicos em campo" value={c.tecnicos_em_campo} />
        <Kpi title="OS em andamento" value={c.os_andamento} />
        <Kpi title="OS atrasadas" value={c.os_atrasadas} warn />
        <Kpi title="Finalizadas hoje" value={c.os_finalizadas_hoje} />
        <Kpi title="Aguardando gestor" value={c.aguardando_gestor} warn />
        <Kpi title="Retiradas pendentes" value={c.retiradas_pendentes} />
        <Kpi title="Truck-roll evitado (30d)" value={data.truck_roll_avoidance_30d} />
      </div>

      <IsabellaGovernance />

      {/* Técnicos */}
      <div style={card} data-testid="field-admin-techs">
        <div style={{ ...label, marginBottom: 10 }}>Técnicos · GPS · estoque · frota · produtividade</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Técnico</th><th style={th}>OS ativa</th><th style={th}>Hoje</th>
              <th style={th}>Feitas</th><th style={th}>GPS</th><th style={th}>ONUs</th>
              <th style={th}>Materiais</th><th style={th}>Frota</th>
            </tr></thead>
            <tbody>
              {(data.techs || []).map((t) => (
                <tr key={t.collaborator_id} data-testid={`field-admin-tech-${t.collaborator_id}`}>
                  <td style={{ ...td, fontWeight: 700 }}>{t.name}</td>
                  <td style={td}>
                    {t.active_os
                      ? <span style={{ color: "#065f46", fontWeight: 700 }}>{t.active_os.client} ({t.active_os.type})</span>
                      : <span style={{ color: "#94a3b8" }}>—</span>}
                  </td>
                  <td style={td}>{t.os_today}</td>
                  <td style={td}>{t.finalizadas_hoje}</td>
                  <td style={td}>
                    {t.gps
                      ? <span style={{ color: t.gps.active ? "#065f46" : "#b45309", fontWeight: 600 }}>{t.gps.active ? "ativo" : timeAgo(t.gps.captured_at)}</span>
                      : <span style={{ color: "#94a3b8" }}>sem ping</span>}
                  </td>
                  <td style={td}>{t.stock?.ont_count ?? 0}</td>
                  <td style={td}>{t.stock?.consumable_total ?? 0}</td>
                  <td style={td}>
                    {t.vehicle?.pending
                      ? <span style={{ color: "#b91c1c", fontWeight: 700 }}>pendente</span>
                      : t.vehicle?.last_inspection_at
                        ? <span style={{ color: "#065f46" }}>{timeAgo(t.vehicle.last_inspection_at)}</span>
                        : <span style={{ color: "#94a3b8" }}>—</span>}
                  </td>
                </tr>
              ))}
              {(data.techs || []).length === 0 && (
                <tr><td style={td} colSpan={8}>Nenhum técnico com atividade de campo.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {/* Atrasadas */}
        <div style={card} data-testid="field-admin-atrasadas">
          <div style={{ ...label, marginBottom: 10 }}>OS atrasadas hoje</div>
          {(data.atrasadas || []).length === 0 && <div style={{ fontSize: 12, color: "#64748b" }}>Nenhuma OS atrasada.</div>}
          {(data.atrasadas || []).map((t) => (
            <div key={t.id} style={{ padding: "7px 0", borderBottom: "1px solid #f1f5f9", fontSize: 12 }}>
              <strong style={{ color: "#b91c1c" }}>{t.client || t.id}</strong>
              <span style={{ color: "#64748b" }}> · {t.type} · agendada {timeAgo(t.scheduled_time)} atrás</span>
            </div>
          ))}
        </div>

        {/* Retiradas / financeiro */}
        <div style={card} data-testid="field-admin-retiradas">
          <div style={{ ...label, marginBottom: 10 }}>Retiradas · impacto financeiro (30d)</div>
          <div style={{ display: "flex", gap: 14, marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 18, fontWeight: 800, color: "#065f46" }}>R$ {(er.value_recovered_30d || 0).toFixed(2)}</div>
              <div style={{ fontSize: 10, color: "#64748b" }}>recuperado</div>
            </div>
            <div>
              <div style={{ fontSize: 18, fontWeight: 800, color: "#b91c1c" }}>R$ {(er.value_lost_30d || 0).toFixed(2)}</div>
              <div style={{ fontSize: 10, color: "#64748b" }}>perda (DRE)</div>
            </div>
          </div>
          {(er.items || []).slice(0, 8).map((r) => (
            <div key={r.id} style={{ padding: "6px 0", borderBottom: "1px solid #f1f5f9", fontSize: 11, color: "#475569" }}>
              <strong style={{ color: "#0f172a", fontFamily: "monospace" }}>{r.mac || r.sn}</strong>
              {" · "}{r.recovered ? `recuperado (${r.physical_state})` : "NÃO devolvido"}
              {" · "}{r.collaborator_name || "técnico"}
            </div>
          ))}
          {(er.items || []).length === 0 && <div style={{ fontSize: 12, color: "#64748b" }}>Nenhuma retirada registrada em 30 dias.</div>}
        </div>
      </div>

      {/* Toggles */}
      <div style={card} data-testid="field-admin-toggles">
        <div style={{ ...label, marginBottom: 12 }}>Regras de bloqueio do App (por empresa)</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>Vistoria semanal da frota obrigatória</div>
              <div style={{ fontSize: 11, color: "#64748b" }}>Bloqueia abertura de OS se a vistoria (KM + 4 fotos) estiver pendente há mais de {tg.vehicle_inspection_max_age_days} dias.</div>
            </div>
            <Toggle testId="toggle-vehicle-inspection" checked={!!tg.vehicle_inspection_required} disabled={saving}
              onChange={(v) => saveToggle({ vehicle_inspection_required: v })} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>GPS obrigatório</div>
              <div style={{ fontSize: 11, color: "#64748b" }}>Bloqueia iniciar/finalizar OS sem localização do aparelho.</div>
            </div>
            <Toggle testId="toggle-gps-required" checked={!!tg.gps_required} disabled={saving}
              onChange={(v) => saveToggle({ gps_required: v })} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>Bloquear material sem estoque</div>
              <div style={{ fontSize: 11, color: "#64748b" }}>Quando desligado, permite saldo negativo (visibilidade de quebra — padrão SmartProv).</div>
            </div>
            <Toggle testId="toggle-block-material" checked={!!tg.block_material_without_stock} disabled={saving}
              onChange={(v) => saveToggle({ block_material_without_stock: v })} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>Valor padrão do equipamento (comodato)</div>
              <div style={{ fontSize: 11, color: "#64748b" }}>Usado no impacto financeiro das retiradas (recuperado/perda → DRE).</div>
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ fontSize: 12, color: "#64748b" }}>R$</span>
              <input data-testid="input-equipment-cost" type="number" min="0" step="10" value={cost}
                onChange={(e) => setCost(e.target.value)}
                onBlur={() => { const v = parseFloat(cost); if (!Number.isNaN(v)) saveToggle({ equipment_default_cost: v }); }}
                style={{ width: 90, padding: "8px 10px", borderRadius: 8, border: "1.5px solid #e2e8f0", fontSize: 13 }} />
            </div>
          </div>
        </div>
        {saving && <div style={{ fontSize: 11, color: "#64748b", marginTop: 8 }}>Salvando…</div>}
      </div>
    </div>
  );
}
