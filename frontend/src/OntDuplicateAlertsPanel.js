/**
 * Painel de Alertas de ONT Duplicada — iter164.
 *
 * Lista alertas onde o mesmo equipamento (SN/MAC) foi instalado em
 * clientes diferentes em curto espaço de tempo SEM retirada registrada.
 * Permite ao gestor classificar o alerta (legítimo, retirada não
 * registrada, clonagem, erro de cadastro).
 */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Card } from "@/ui";

const RESOLUTION_LABEL = {
  ok_legitimo: "Legítimo (verificado)",
  retirada_nao_registrada: "Retirada não registrada",
  clonagem: "Clonagem / ONT pirata",
  erro_cadastro: "Erro de cadastro",
  outro: "Outro",
};

function fmtDateTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      dateStyle: "short", timeStyle: "short",
    });
  } catch { return iso; }
}

function severityColor(sev) {
  if (sev === "critical") return { bg: "#fee2e2", color: "#991b1b" };
  return { bg: "#fef3c7", color: "#92400e" };
}

export default function OntDuplicateAlertsPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [statusFilter, setStatusFilter] = useState("open");
  const [resolving, setResolving] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      setData(await api.ontDuplicateAlertsList(statusFilter));
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => { reload(); }, [reload]);

  const items = data?.items || [];

  return (
    <Card title="Alertas de ONT Duplicada"
          data-testid="ont-duplicate-alerts-card"
          subtitle="Mesma ONT (SN ou MAC) instalada em clientes diferentes recentemente sem retirada registrada. Possíveis casos de 'ONT pirata', clonagem ou erro de cadastro."
          action={
            <div style={{ display: "flex", gap: 6 }}>
              <select className="input" value={statusFilter}
                      data-testid="ont-dup-status-filter"
                      onChange={(e) => setStatusFilter(e.target.value)}
                      style={{ width: 130 }}>
                <option value="open">Abertos</option>
                <option value="resolved">Resolvidos</option>
                <option value="all">Todos</option>
              </select>
              <button onClick={reload} disabled={loading}
                      data-testid="ont-dup-reload"
                      className="btn btn-secondary btn-sm">
                {loading ? "…" : "Atualizar"}
              </button>
            </div>
          }>
      {err && <div style={{ padding: 10, color: "#dc2626" }}>Erro: {err}</div>}
      {!err && data && (
        <>
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
            gap: 10, marginBottom: 14,
          }}>
            <KPI label="Abertos" value={data.open_count} color="#d97706" />
            <KPI label="Críticos" value={data.critical_count} color="#dc2626" />
            <KPI label="Total" value={data.total} color="#64748b" />
          </div>

          {items.length === 0 && (
            <div style={{ padding: 30, textAlign: "center",
                            color: "var(--text-muted)" }}>
              {statusFilter === "open"
                ? "✅ Nenhum alerta aberto — nenhuma ONT duplicada detectada."
                : "Nenhum alerta nesta categoria."}
            </div>
          )}

          {items.map((a) => (
            <AlertRow key={a.id} alert={a}
                      onResolve={() => setResolving(a)} />
          ))}
        </>
      )}

      {resolving && (
        <ResolveModal alert={resolving}
                      onClose={() => setResolving(null)}
                      onDone={() => { setResolving(null); reload(); }} />
      )}
    </Card>
  );
}

function KPI({ label, value, color }) {
  return (
    <div style={{
      background: "var(--bg-surface-2)",
      borderLeft: `3px solid ${color}`,
      border: "1px solid var(--border-default)",
      borderRadius: 8, padding: "10px 12px",
    }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
                     textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, marginTop: 2, color }}>
        {value ?? 0}
      </div>
    </div>
  );
}

function AlertRow({ alert, onResolve }) {
  const sev = severityColor(alert.severity);
  const isResolved = alert.status === "resolved";
  return (
    <div data-testid={`ont-dup-alert-${alert.id}`}
         style={{
           border: "1px solid var(--border-default)",
           borderLeft: `4px solid ${sev.color}`,
           borderRadius: 8, padding: 12, marginBottom: 10,
           background: "var(--bg-surface)",
           opacity: isResolved ? 0.7 : 1,
         }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <div>
          <span className="pill" style={{ background: sev.bg, color: sev.color,
                                            fontWeight: 700, marginRight: 6 }}>
            {alert.severity === "critical" ? "CRÍTICO" : "ATENÇÃO"}
          </span>
          <span className="mono" data-mono style={{ fontWeight: 700, fontSize: 14 }}>
            {alert.ont_sn || alert.ont_mac}
          </span>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {fmtDateTime(alert.detected_at)}
        </div>
      </div>

      <div style={{ marginTop: 8, fontSize: 12 }}>
        <div>
          <strong>Atual:</strong> {alert.current_client_name || alert.current_client_id}
          {alert.actor_name && <> (por <em>{alert.actor_name}</em>)</>}
        </div>
        <div style={{ marginTop: 4, padding: "6px 8px",
                       background: "var(--bg-surface-2)", borderRadius: 6 }}>
          <div style={{ fontSize: 10, color: "var(--text-muted)",
                          fontWeight: 700, textTransform: "uppercase",
                          marginBottom: 4 }}>
            Já instalado em {alert.conflicts?.length || 0} outro(s) cliente(s):
          </div>
          {(alert.conflicts || []).map((c) => (
            <div key={c.history_id} style={{ fontSize: 11, padding: "2px 0" }}>
              • <strong>{c.client_name || c.client_id}</strong>
              {c.installed_by && <> · por {c.installed_by}</>}
              <span style={{ color: "var(--text-muted)" }}>
                {" "}({fmtDateTime(c.installed_at)})
              </span>
              {c.ticket_id && (
                <span style={{ color: "var(--text-muted)", fontSize: 10,
                                  marginLeft: 4 }}>· ticket {c.ticket_id}</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {!isResolved && (
        <div style={{ marginTop: 10 }}>
          <button onClick={onResolve}
                  data-testid={`ont-dup-resolve-${alert.id}`}
                  className="btn btn-accent btn-sm">
            Analisar e marcar como resolvido
          </button>
        </div>
      )}
      {isResolved && (
        <div style={{ marginTop: 8, padding: "6px 8px",
                        background: "#d1fae5", color: "#065f46",
                        borderRadius: 6, fontSize: 11 }}>
          ✓ Resolvido como <strong>{RESOLUTION_LABEL[alert.resolution] || alert.resolution}</strong>
          {alert.resolved_by && <> por {alert.resolved_by}</>}
          {alert.resolution_notes && (
            <div style={{ fontStyle: "italic", marginTop: 2 }}>“{alert.resolution_notes}”</div>
          )}
        </div>
      )}
    </div>
  );
}

function ResolveModal({ alert, onClose, onDone }) {
  const [resolution, setResolution] = useState("ok_legitimo");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async () => {
    setErr(""); setBusy(true);
    try {
      await api.ontDuplicateAlertResolve(alert.id, { resolution, notes });
      onDone();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div data-testid="ont-dup-resolve-modal"
         style={{
           position: "fixed", inset: 0, background: "rgba(15,23,42,0.6)",
           display: "flex", alignItems: "center", justifyContent: "center",
           zIndex: 1000, padding: 16,
         }}
         onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: "var(--bg-surface)", borderRadius: 12,
             width: "min(520px, 100%)",
             border: "1px solid var(--border-default)",
             padding: 20,
           }}>
        <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 8 }}>
          Resolver alerta de ONT duplicada
        </div>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 14 }}>
          {alert.ont_sn || alert.ont_mac} · {alert.current_client_name}
        </div>

        <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                          color: "var(--text-muted)", marginBottom: 4,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
          Classificação
        </label>
        <select className="input" value={resolution}
                data-testid="ont-dup-resolve-select"
                onChange={(e) => setResolution(e.target.value)}
                style={{ width: "100%", marginBottom: 12 }}>
          {Object.entries(RESOLUTION_LABEL).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>

        <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                          color: "var(--text-muted)", marginBottom: 4,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
          Notas (opcional)
        </label>
        <textarea className="input" value={notes}
                  data-testid="ont-dup-resolve-notes"
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Detalhe a investigação realizada…"
                  style={{ width: "100%", minHeight: 80, marginBottom: 14 }} />

        {err && <div style={{ color: "#dc2626", marginBottom: 10, fontSize: 12 }}>{err}</div>}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} disabled={busy}
                  className="btn btn-secondary btn-sm">Cancelar</button>
          <button onClick={submit} disabled={busy}
                  data-testid="ont-dup-resolve-submit"
                  className="btn btn-accent btn-sm">
            {busy ? "Salvando…" : "Resolver"}
          </button>
        </div>
      </div>
    </div>
  );
}
