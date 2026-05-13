import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card, fmtMin, Icon, Metric, Row, StatusBadge } from "@/ui";
import LiveMap from "@/LiveMap";

export default function ManagerPanel() {
  const [records, setRecords] = useState([]);
  const [collabs, setCollabs] = useState([]);
  const [orphanFences, setOrphanFences] = useState([]); // cercas salvas em colab não-CLT
  const [busy, setBusy] = useState(false);
  const [orphanBusy, setOrphanBusy] = useState(null);
  const [orphanFlash, setOrphanFlash] = useState("");

  async function reload() {
    const [r, c] = await Promise.all([api.listClockRecords(), api.listCollaborators()]);
    setRecords(r);
    setCollabs(c);
    // Detecta cercas órfãs: pertencem a colab com clock_in_enabled=false
    const nonClt = c.filter((x) => x.clock_in_enabled === false);
    const orphans = [];
    await Promise.all(nonClt.map(async (col) => {
      try {
        const fs = await api.listGeofences(col.id);
        for (const f of fs) orphans.push({ ...f, _collab: col });
      } catch { /* ignora colab */ }
    }));
    setOrphanFences(orphans);
  }
  useEffect(() => { reload(); }, []);

  const collabName = (cid) => collabs.find((c) => c.id === cid)?.name || cid;

  async function enableClockIn(col) {
    if (!window.confirm(`Ativar batimento de ponto para ${col.name}?\n\nA partir de agora as cercas dele(a) serão aplicadas e ele(a) verá a tela de Entrada/Intervalo/Saída no app.`)) return;
    setOrphanBusy(col.id);
    try {
      await api.updateCollaborator(col.id, {
        name: col.name, cpf: col.cpf, email: col.email, phone: col.phone,
        role: col.role, company: col.company,
        schedule: col.schedule, overtime_policy: col.overtime_policy,
        city: col.city ?? null, state: col.state ?? null, praca_id: col.praca_id ?? null,
        is_test_mode: !!col.is_test_mode,
        clock_in_enabled: true,
      });
      setOrphanFlash(`✅ ${col.name} agora bate ponto — cercas reativadas.`);
      await reload();
      setTimeout(() => setOrphanFlash(""), 4000);
    } catch (e) {
      setOrphanFlash(`❌ Erro: ${e?.response?.data?.detail || e.message}`);
      setTimeout(() => setOrphanFlash(""), 4000);
    }
    setOrphanBusy(null);
  }

  async function removeOrphan(fenceId, colName) {
    if (!window.confirm(`Remover esta cerca de ${colName}?\n\nEla está inativa porque o colaborador não bate ponto. Esta ação não pode ser desfeita.`)) return;
    setOrphanBusy(fenceId);
    try {
      await api.deleteGeofence(fenceId);
      setOrphanFlash(`✅ Cerca removida.`);
      await reload();
      setTimeout(() => setOrphanFlash(""), 3000);
    } catch (e) {
      setOrphanFlash(`❌ Erro: ${e?.response?.data?.detail || e.message}`);
      setTimeout(() => setOrphanFlash(""), 4000);
    }
    setOrphanBusy(null);
  }

  // === Insights IA · Frota (defeitos recorrentes em checklist veicular) ===
  const [fleetInsights, setFleetInsights] = useState(null);
  const [fleetLoading, setFleetLoading] = useState(false);
  const [fleetError, setFleetError] = useState("");

  async function loadFleetInsights() {
    setFleetLoading(true);
    setFleetError("");
    try {
      const r = await api.vchkAiRecurrentInsights(30, 2);
      setFleetInsights(r);
    } catch (e) {
      setFleetError(e?.response?.data?.detail || e.message);
    } finally {
      setFleetLoading(false);
    }
  }
  useEffect(() => { loadFleetInsights(); }, []);

  const valid = records.filter((r) => r.status === "Válido" || r.status === "Offline sincronizado");
  const pending = records.filter((r) => r.status === "Pendente");
  const rejected = records.filter((r) => r.status === "Recusado");
  const blocked = records.filter((r) => r.status === "Bloqueado");

  async function approve(rid) { setBusy(true); await api.approveRecord(rid); await reload(); setBusy(false); }
  async function reject(rid) { setBusy(true); await api.rejectRecord(rid); await reload(); setBusy(false); }

  return (
    <div>
      <LiveMap />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
      <div>
        <Card title="Indicadores">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
            <Metric label="Válidos" value={valid.length} />
            <Metric label="Pendentes" value={pending.length} />
            <Metric label="Recusados" value={rejected.length} />
            <Metric label="Bloqueados" value={blocked.length} />
          </div>
        </Card>

        <Card title="Aprovações pendentes">
          {pending.length === 0 && <p style={{ color: "#64748b" }}>Nenhuma pendência.</p>}
          {pending.map((r) => (
            <div key={r.id} style={{ borderBottom: "1px solid #f1f5f9", padding: "10px 0" }}>
              <strong>{collabName(r.collaborator_id)}</strong> — {r.type} {r.geofence_name && `em ${r.geofence_name}`}<br />
              <span style={{ color: "#64748b", fontSize: 13 }}>{r.date} {r.time} • {r.geo_status} • IP {r.public_ip || "—"}</span>
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <Button onClick={() => approve(r.id)} disabled={busy} data-testid={`approve-${r.id}`}>Aprovar</Button>
                <Button variant="danger" onClick={() => reject(r.id)} disabled={busy} data-testid={`reject-${r.id}`}>Recusar</Button>
              </div>
            </div>
          ))}
        </Card>

        <Card title="Tentativas bloqueadas — dados internos">
          {blocked.length === 0 && <p style={{ color: "#64748b" }}>Nenhuma tentativa bloqueada.</p>}
          {blocked.map((r) => (
            <div key={r.id} style={{ borderBottom: "1px solid #f1f5f9", padding: "10px 0" }}>
              <strong>{collabName(r.collaborator_id)}</strong> — {r.type}<br />
              <span style={{ color: "#be123c", fontSize: 13 }}>{r.date} {r.time} • IP {r.public_ip || "—"} • Motivo interno: {r.internal_block_reason}</span>
            </div>
          ))}
        </Card>

        <Card
          title={
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              Cercas órfãs
              <span data-testid="orphan-count-badge" style={{
                background: orphanFences.length ? "#fef3c7" : "#f1f5f9",
                color: orphanFences.length ? "#92400e" : "#64748b",
                border: `1px solid ${orphanFences.length ? "#fde68a" : "#e2e8f0"}`,
                fontSize: 11, fontWeight: 800, padding: "1px 8px", borderRadius: 999,
              }}>
                {orphanFences.length}
              </span>
            </span>
          }
        >
          <p style={{ color: "#64748b", fontSize: 13, marginTop: -4, marginBottom: 10 }}>
            Cercas salvas em colaboradores que <strong>não batem ponto</strong> (terceirizado/MEI) — ficam guardadas no DB mas
            não são aplicadas. Reative o ponto para validar ou remova a cerca.
          </p>
          {orphanFlash && (
            <div data-testid="orphan-flash" style={{
              background: orphanFlash.startsWith("✅") ? "#dcfce7" : "#fee2e2",
              color: orphanFlash.startsWith("✅") ? "#166534" : "#991b1b",
              padding: 10, borderRadius: 12, marginBottom: 10, fontWeight: 700, fontSize: 13,
            }}>{orphanFlash}</div>
          )}
          {orphanFences.length === 0 ? (
            <p data-testid="orphan-empty" style={{ color: "#64748b" }}>Nenhuma cerca órfã. Tudo limpo.</p>
          ) : (
            orphanFences.map((f) => (
              <div key={f.id} data-testid={`orphan-row-${f.id}`} style={{
                display: "flex", justifyContent: "space-between", gap: 10,
                padding: "10px 0", borderBottom: "1px solid #f1f5f9", flexWrap: "wrap",
              }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong>{f._collab.name}</strong>
                  <span style={{
                    marginLeft: 8, fontSize: 10, fontWeight: 700, padding: "1px 7px", borderRadius: 999,
                    background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0",
                  }}>não bate ponto</span>
                  <div style={{ color: "#475569", fontSize: 13, marginTop: 2 }}>
                    <Icon name="map" /> {f.name} <span style={{ color: "#94a3b8" }}>· {f.type}</span>
                  </div>
                  <div style={{ color: "#94a3b8", fontSize: 11, marginTop: 1 }}>
                    {f.address} · raio {f.radius}m
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, alignSelf: "center" }}>
                  <Button
                    variant="soft"
                    onClick={() => enableClockIn(f._collab)}
                    disabled={orphanBusy === f._collab.id}
                    data-testid={`orphan-enable-${f._collab.id}`}
                    title="Reativa o batimento de ponto deste colaborador — todas as cercas dele voltam a valer"
                  >
                    {orphanBusy === f._collab.id ? "..." : "Ativar ponto"}
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => removeOrphan(f.id, f._collab.name)}
                    disabled={orphanBusy === f.id}
                    data-testid={`orphan-remove-${f.id}`}
                    title="Remove a cerca permanentemente"
                  >
                    {orphanBusy === f.id ? "..." : <Icon name="trash" />}
                  </Button>
                </div>
              </div>
            ))
          )}
        </Card>

        <Card
          title={
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <Icon name="bot" /> Insights IA · Frota
              <span data-testid="fleet-ai-badge" style={{
                background: "#0f172a", color: "white", fontSize: 10, fontWeight: 800,
                padding: "1px 7px", borderRadius: 999,
              }}>30d</span>
            </span>
          }
          action={
            <Button variant="soft" onClick={loadFleetInsights} disabled={fleetLoading} data-testid="fleet-ai-reload">
              {fleetLoading ? "Consultando IA…" : "Atualizar"}
            </Button>
          }
        >
          <p style={{ color: "#64748b", fontSize: 13, marginTop: -4, marginBottom: 10 }}>
            A IA analisa os checklists veiculares dos últimos 30 dias e destaca padrões de defeitos recorrentes,
            sugerindo prioridade de manutenção.
          </p>
          {fleetError && (
            <div data-testid="fleet-ai-error" style={{
              background: "#fee2e2", color: "#991b1b",
              padding: 10, borderRadius: 10, marginBottom: 10, fontWeight: 700, fontSize: 13,
            }}>{fleetError}</div>
          )}
          {fleetLoading && !fleetInsights && (
            <div style={{ color: "#64748b" }}>Consultando IA…</div>
          )}
          {fleetInsights && (
            <div>
              <div data-testid="fleet-ai-summary" style={{
                padding: 12, background: "#f0f9ff", border: "1px solid #bae6fd",
                borderRadius: 10, fontSize: 14, fontWeight: 600, color: "#075985", marginBottom: 10,
              }}>
                {fleetInsights.ai?.summary || "—"}
              </div>
              {(fleetInsights.ai?.bullets?.length || 0) > 0 && (
                <ul data-testid="fleet-ai-bullets" style={{ margin: "0 0 10px", paddingLeft: 18, fontSize: 13, color: "#334155" }}>
                  {fleetInsights.ai.bullets.map((b, i) => (
                    <li key={i} style={{ marginBottom: 4 }}>{b}</li>
                  ))}
                </ul>
              )}
              {fleetInsights.ai?.top_priority && (
                <div data-testid="fleet-ai-priority" style={{
                  padding: 10, background: "#fef3c7", border: "1px solid #fde68a",
                  borderRadius: 10, fontSize: 13, color: "#78350f", marginBottom: 10,
                }}>
                  <strong>🔴 Top prioridade · {fleetInsights.ai.top_priority.plate}:</strong>{" "}
                  {fleetInsights.ai.top_priority.reason}
                </div>
              )}
              {(fleetInsights.alerts?.length || 0) > 0 && (
                <details style={{ fontSize: 12, color: "#475569" }}>
                  <summary style={{ cursor: "pointer", fontWeight: 700 }}>
                    Ver dados brutos ({fleetInsights.alerts.length} alerta(s))
                  </summary>
                  <table style={{ width: "100%", marginTop: 6, fontSize: 11, borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ background: "#f8fafc" }}>
                        <th style={{ textAlign: "left", padding: 4, borderBottom: "1px solid #e2e8f0" }}>Placa</th>
                        <th style={{ textAlign: "left", padding: 4, borderBottom: "1px solid #e2e8f0" }}>Item</th>
                        <th style={{ textAlign: "right", padding: 4, borderBottom: "1px solid #e2e8f0" }}>Ocorrências</th>
                        <th style={{ textAlign: "left", padding: 4, borderBottom: "1px solid #e2e8f0" }}>Último</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fleetInsights.alerts.map((a, i) => (
                        <tr key={i} style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: 4 }}><strong>{a.plate}</strong></td>
                          <td style={{ padding: 4 }}>{a.item}</td>
                          <td style={{ padding: 4, textAlign: "right", fontWeight: 700 }}>{a.count}×</td>
                          <td style={{ padding: 4 }}>{(a.last_at || "").slice(0, 10)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )}
            </div>
          )}
        </Card>
      </div>

      <Card title="Últimos registros válidos">
        {valid.length === 0 && <p style={{ color: "#64748b" }}>Nenhum registro válido ainda.</p>}
        {valid.slice(0, 30).map((r) => (
          <div key={r.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid #f1f5f9" }}>
            <div>
              <strong>{collabName(r.collaborator_id)}</strong>
              <div style={{ color: "#64748b", fontSize: 12 }}>{r.date} {r.time} • {r.type} • {r.geofence_name || "—"}</div>
            </div>
            <StatusBadge status={r.status} />
          </div>
        ))}
      </Card>
      </div>
    </div>
  );
}
