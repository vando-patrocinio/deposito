import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card, fmtMin, Icon, Metric, Row, StatusBadge } from "@/ui";
import LiveMap from "@/LiveMap";

export default function ManagerPanel() {
  const [records, setRecords] = useState([]);
  const [collabs, setCollabs] = useState([]);
  const [busy, setBusy] = useState(false);

  async function reload() {
    const [r, c] = await Promise.all([api.listClockRecords(), api.listCollaborators()]);
    setRecords(r);
    setCollabs(c);
  }
  useEffect(() => { reload(); }, []);

  const collabName = (cid) => collabs.find((c) => c.id === cid)?.name || cid;

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
