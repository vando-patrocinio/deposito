/**
 * Retirada Manual — iter170.
 *
 * Modal acionado pelo botão "📦 Retirar" na linha do cliente SmartOLT.
 * Permite ao gestor registrar a retirada do equipamento (sem OS aberta),
 * escolhendo o técnico que receberá o equipamento em seu estoque.
 *
 * Backend: POST /api/stok/clientes/manual-withdraw
 * - Cria/atualiza `stok_onts` com `location_id=technician_id`
 * - Libera porta CTO vinculada
 * - Loga evento `withdraw` em `client_equipment_history` (gestor como actor)
 * - Cria notification de auditoria
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

export default function ManualWithdrawDialog({ client, onClose, onDone }) {
  const [techs, setTechs] = useState([]);
  const [techId, setTechId] = useState("");
  const [notes, setNotes] = useState("");
  const [isDefective, setIsDefective] = useState(false);
  const [defectiveReason, setDefectiveReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [me, setMe] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const cols = await api._client.get("/collaborators").then((r) => r.data);
        const list = Array.isArray(cols) ? cols : (cols?.items || []);
        if (!alive) return;
        // Prefere técnicos / colaboradores
        const filtered = list.filter((c) =>
          ["tecnico", "colaborador"].includes(c.role)
          || (c.name && c.id?.startsWith("col-"))
        );
        setTechs(filtered.length > 0 ? filtered : list);
      } catch (e) {
        if (alive) setErr("Falha ao carregar colaboradores: " + e.message);
      }
      try {
        const u = await api._client.get("/auth/me").then((r) => r.data);
        if (alive) setMe(u);
      } catch {/* opcional */}
    })();
    return () => { alive = false; };
  }, []);

  const submit = async () => {
    if (!techId) { setErr("Selecione o técnico que receberá o equipamento."); return; }
    if (!window.confirm(
      `Confirma a RETIRADA MANUAL?\n\n` +
      `Cliente: ${client.client_name}\n` +
      `SN: ${client.sn || "—"}\n` +
      `Equipamento irá para o estoque de: ${(techs.find((t) => t.id === techId) || {}).name || techId}\n\n` +
      `Esta ação será registrada em seu nome como gestor.`
    )) return;
    setBusy(true); setErr("");
    try {
      await api._client.post("/stok/clientes/manual-withdraw", {
        technician_id: techId,
        client_name: client.client_name,
        client_id: client.client_id,
        ont_mac: client.mac,
        ont_sn: client.sn,
        notes: notes || null,
        is_defective: isDefective,
        defective_reason: defectiveReason || null,
      });
      onDone?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div data-testid="manual-withdraw-modal"
         style={{
           position: "fixed", inset: 0, background: "rgba(15,23,42,0.6)",
           display: "flex", alignItems: "center", justifyContent: "center",
           zIndex: 1000, padding: 16,
         }}
         onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: "var(--bg-surface)", borderRadius: 12,
             width: "min(560px, 100%)", maxHeight: "90vh", overflow: "auto",
             border: "1px solid var(--border-default)",
             padding: 20,
           }}>
        <div style={{ fontSize: 17, fontWeight: 800,
                          color: "#dc2626", marginBottom: 4 }}>
          📦 Retirada Manual
        </div>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
          Registra a retirada do equipamento <strong>sem OS aberta</strong>.
          Use quando o equipamento foi removido fisicamente e você precisa
          regularizar o estoque agora.
        </div>

        {/* Cliente — apenas display */}
        <div style={{
          background: "var(--bg-surface-2)", borderRadius: 8, padding: 12,
          marginBottom: 14, fontSize: 13,
        }}>
          <div><strong>Cliente:</strong> {client.client_name}</div>
          {client.sn && (
            <div className="mono" data-mono>
              <strong>SN:</strong> {client.sn}
            </div>
          )}
          {client.mac && (
            <div className="mono" data-mono>
              <strong>MAC:</strong> {client.mac}
            </div>
          )}
          {client.cto_name && (
            <div>
              <strong>Porta CTO:</strong> {client.cto_name} · porta {client.cto_port_number}
              <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: 6 }}>
                (será liberada)
              </span>
            </div>
          )}
        </div>

        {/* Técnico destino */}
        <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                          color: "var(--text-muted)", marginBottom: 4,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
          Técnico que recebe o equipamento *
        </label>
        <select value={techId}
                onChange={(e) => setTechId(e.target.value)}
                data-testid="manual-withdraw-tech-select"
                className="input"
                style={{ width: "100%", marginBottom: 12 }}>
          <option value="">Selecione…</option>
          {techs.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>

        {/* Defeituoso? */}
        <label style={{ display: "flex", alignItems: "center", gap: 8,
                            marginBottom: 10, cursor: "pointer", fontSize: 13 }}>
          <input type="checkbox" checked={isDefective}
                  data-testid="manual-withdraw-defective"
                  onChange={(e) => setIsDefective(e.target.checked)} />
          <span>Equipamento DEFEITUOSO (deve voltar à empresa)</span>
        </label>
        {isDefective && (
          <input value={defectiveReason}
                   onChange={(e) => setDefectiveReason(e.target.value)}
                   placeholder="Motivo do defeito (ex.: PON queimada)"
                   data-testid="manual-withdraw-defective-reason"
                   className="input"
                   style={{ width: "100%", marginBottom: 10 }} />
        )}

        {/* Notas */}
        <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                          color: "var(--text-muted)", marginBottom: 4,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
          Notas (opcional)
        </label>
        <textarea value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Ex.: Cliente solicitou cancelamento sem agendamento de OS…"
                  data-testid="manual-withdraw-notes"
                  className="input"
                  style={{ width: "100%", minHeight: 60, marginBottom: 12 }} />

        {/* Registrado por (gestor logado) */}
        <div style={{
          background: "#fef3c7", color: "#92400e", padding: 10,
          borderRadius: 8, fontSize: 12, marginBottom: 14,
          border: "1px solid #fde68a",
        }}>
          <strong>Registrado por:</strong> {me?.name || me?.email || "(gestor logado)"}
        </div>

        {err && (
          <div style={{ color: "#dc2626", fontSize: 12, marginBottom: 10 }}>
            Erro: {err}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} disabled={busy}
                  className="btn btn-secondary btn-sm">Cancelar</button>
          <button onClick={submit} disabled={busy || !techId}
                  data-testid="manual-withdraw-submit"
                  style={{
                    padding: "8px 16px", borderRadius: 8, border: 0,
                    background: busy || !techId
                      ? "#94a3b8"
                      : "linear-gradient(135deg,#dc2626,#991b1b)",
                    color: "#fff", fontSize: 13, fontWeight: 700,
                    cursor: busy ? "wait" : "pointer",
                  }}>
            {busy ? "Registrando…" : "📦 Confirmar Retirada"}
          </button>
        </div>
      </div>
    </div>
  );
}
