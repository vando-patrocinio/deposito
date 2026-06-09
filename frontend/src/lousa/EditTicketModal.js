import React, { useEffect, useState, useCallback } from "react";
import { Button } from "@/ui";
import { api } from "@/api";

const css = { width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 13, marginBottom: 8 };

// ============================================================
// Bloco SmartOLT (sinal vivo da ONU pelo PPPoE/nome)
// ============================================================
function signalQuality(rx) {
  // rx em dBm (negativo). Padrão GPON: -8 a -28 saudável
  const v = parseFloat(rx);
  if (isNaN(v)) return { color: "#64748b", label: "—", bg: "#f1f5f9" };
  if (v >= -23) return { color: "#15803d", label: "Excelente", bg: "#dcfce7" };
  if (v >= -27) return { color: "#a16207", label: "Atenção", bg: "#fef3c7" };
  return { color: "#b91c1c", label: "Crítico", bg: "#fee2e2" };
}

function RebootButton({ extId, onDone }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const click = async () => {
    if (!window.confirm(
      "Religar a ONT/ONU agora? Isso vai derrubar a conexão "
      + "do cliente por ~30s e o equipamento vai reiniciar.")) return;
    setBusy(true);
    try {
      await api.smartoltOnuReboot(extId);
      setDone(true);
      // Aguarda ~25s antes de buscar sinal de novo (ONU precisa subir)
      setTimeout(() => { if (typeof onDone === "function") onDone(); }, 25000);
    } catch (e) {
      window.alert("Falha ao religar: "
        + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };
  return (
    <button type="button" onClick={click} disabled={busy || done}
            data-testid="signal-reboot-onu-btn"
            style={{ marginTop: 8, padding: "6px 12px", borderRadius: 8,
                      border: "none",
                      background: done ? "#15803d" : "#b91c1c",
                      color: "white", fontWeight: 800, fontSize: 11,
                      cursor: (busy || done) ? "default" : "pointer",
                      opacity: busy ? 0.7 : 1,
                      fontFamily: "Inter, sans-serif" }}>
      {done
        ? "Religada — aguardando voltar (~25s)…"
        : busy ? "Religando…" : "Religar ONU agora"}
    </button>
  );
}

function SignalBlock({ ticketId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async (refresh = false) => {
    setErr("");
    if (refresh) setRefreshing(true); else setLoading(true);
    try {
      const d = await api.lousaTicketSignal(ticketId, refresh);
      setData(d);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [ticketId]);

  useEffect(() => { load(false); }, [load]);

  const baseStyle = {
    border: "1px solid #e2e8f0", borderRadius: 12, padding: 12,
    marginBottom: 14, background: "#f8fafc",
  };

  if (loading) {
    return <div style={baseStyle} data-testid="signal-block-loading">Buscando sinal SmartOLT…</div>;
  }
  if (err) {
    return <div style={{ ...baseStyle, background: "#fee2e2", color: "#7f1d1d" }} data-testid="signal-block-error">️ {err}</div>;
  }
  if (!data?.found) {
    const reason = data?.reason || "no_match";
    const friendly = {
      missing_pppoe_and_name: "Bolha sem nome/PPPoE — preencha abaixo.",
      no_match: `Cliente não encontrado no SmartOLT. Tente o PPPoE: ${data?.pppoe || data?.name || "?"}`,
      smartolt_module_missing: "Módulo SmartOLT indisponível.",
    }[reason] || "Não foi possível resolver o cliente no SmartOLT.";
    return (
      <div style={{ ...baseStyle, background: "#fef9c3", color: "#713f12" }} data-testid="signal-block-not-found">
        {friendly}
      </div>
    );
  }
  const onu = data.onu || {};
  const rx = onu.signal_1490 || onu.signal_1310;
  const q = signalQuality(rx);
  const onlineClr = onu.status === "Online" ? "#15803d" : (onu.status?.toLowerCase().includes("offline") ? "#b91c1c" : "#a16207");
  return (
    <div style={baseStyle} data-testid="signal-block">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>
            Sinal SmartOLT · match {data.match_strategy}
            {data.cached === false && <span style={{ marginLeft: 6, color: "#16a34a" }}>● live</span>}
            {data.cached === true && <span style={{ marginLeft: 6, color: "#64748b" }}>● cache</span>}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <span style={{
              padding: "4px 10px", borderRadius: 999, background: q.bg, color: q.color,
              fontWeight: 800, fontSize: 14, fontFamily: "monospace",
            }} data-testid="signal-rx">
              {rx ? `${rx} dBm` : "sem leitura"}
            </span>
            <span style={{ fontSize: 11, color: q.color, fontWeight: 700 }}>{q.label}</span>
            <span style={{ padding: "2px 8px", borderRadius: 6, background: "white", border: `1px solid ${onlineClr}33`, color: onlineClr, fontSize: 11, fontWeight: 700 }} data-testid="signal-status">
              {onu.status || "?"}
            </span>
            {onu.signal_text && <span style={{ fontSize: 11, color: "#64748b" }}>SmartOLT: <b>{onu.signal_text}</b></span>}
          </div>
          <div style={{ marginTop: 6, fontSize: 11, color: "#475569", lineHeight: 1.5 }}>
            <div><b>{onu.name}</b> · {onu.onu_type_name}</div>
            <div>{onu.olt_name} · Board {onu.board} / Port {onu.port} / ONU {onu.onu} · {onu.zone_name}</div>
            <div style={{ fontFamily: "monospace", color: "#64748b" }}>SN: {onu.sn || onu.unique_external_id}</div>
            {onu.last_status_change && <div style={{ color: "#64748b" }}>Última mudança de status: {onu.last_status_change}</div>}
          </div>
          {data.warning && (
            <div data-testid="signal-warning"
                  style={{ marginTop: 8, padding: "8px 10px",
                            borderRadius: 8, fontSize: 11,
                            background: data?.live_error?.is_los
                              ? "#fef2f2" : "#fef9c3",
                            border: `1px solid ${data?.live_error?.is_los
                              ? "#fca5a5" : "#fde68a"}`,
                            color: data?.live_error?.is_los
                              ? "#7f1d1d" : "#713f12",
                            lineHeight: 1.5 }}>
              <b style={{ display: "block", marginBottom: 2 }}>
                {data?.live_error?.cleared
                  ? "Sem leitura · cache zerado"
                  : data?.live_error?.is_los
                  ? "ONU em LOS · sem sinal pra ler"
                  : "Aviso"}
              </b>
              {data.warning}
              {data?.live_error?.is_los && (onu.unique_external_id || onu.sn) && (
                <RebootButton
                  extId={onu.unique_external_id || onu.sn}
                  onDone={() => load(true)}
                />
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => load(true)} disabled={refreshing}
          data-testid="signal-refresh-btn"
          style={{
            background: "white", border: "1px solid #cbd5e1", borderRadius: 8,
            padding: "6px 10px", fontSize: 11, fontWeight: 700, cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          {refreshing ? "…" : "Live"}
        </button>
      </div>
    </div>
  );
}

// ============================================================
// Modal principal
// ============================================================
export default function EditTicketModal({ ticket, onClose, onSave, busy }) {
  const [form, setForm] = useState({
    client_name: ticket.client_snapshot?.name || "",
    address: ticket.client_snapshot?.address || "",
    neighborhood: ticket.client_snapshot?.neighborhood || "",
    phone: ticket.client_snapshot?.phone || "",
    relato: ticket.client_snapshot?.relato || "",
    pppoe_user: ticket.client_snapshot?.pppoe_user || "",
    type: ticket.type || "reparo",
    priority: ticket.priority || "normal",
    scheduled_time: ticket.scheduled_time || "",
  });

  function submit(e) {
    e?.preventDefault();
    const payload = { ...form };
    if (!payload.scheduled_time) delete payload.scheduled_time;
    onSave(payload);
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 100, display: "grid", placeItems: "center", padding: 20 }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{ background: "white", borderRadius: 18, padding: 22, maxWidth: 560, width: "100%", maxHeight: "92vh", overflowY: "auto" }} data-testid="lousa-edit-modal">
        <h2 style={{ marginTop: 0 }}>✎ Editar nota</h2>
        <p style={{ color: "#64748b", fontSize: 12, margin: "0 0 12px" }}>
          Status: <strong>{ticket.status}</strong> · ID: <code>{ticket.id}</code>
        </p>

        <SignalBlock ticketId={ticket.id} />

        <label style={{ fontSize: 12, color: "#64748b" }}>Nome do cliente</label>
        <input value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} style={css} data-testid="edit-client-name" />
        <label style={{ fontSize: 12, color: "#64748b" }}>Login PPPoE (chave SmartOLT)</label>
        <input value={form.pppoe_user} onChange={(e) => setForm({ ...form, pppoe_user: e.target.value })} style={css} placeholder="ex.: TnPalestrina733_Vitoria" data-testid="edit-pppoe-user" />
        <label style={{ fontSize: 12, color: "#64748b" }}>Endereço</label>
        <input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} style={css} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Bairro</label>
            <input value={form.neighborhood} onChange={(e) => setForm({ ...form, neighborhood: e.target.value })} style={css} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Telefone</label>
            <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} style={css} />
          </div>
        </div>
        <label style={{ fontSize: 12, color: "#64748b" }}>Relato</label>
        <textarea value={form.relato} onChange={(e) => setForm({ ...form, relato: e.target.value })} rows={3} style={{ ...css, resize: "vertical" }} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Tipo</label>
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} style={css} data-testid="edit-type">
              <option value="reparo">Reparo</option>
              <option value="instalacao">Instalação</option>
              <option value="retirada">Retirada</option>
              <option value="prioridade">Prioridade</option>
              <option value="preventiva">️ Preventiva</option>
              <option value="venda">Venda</option>
              <option value="rompimento">Rompimento</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Prioridade</label>
            <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} style={css}>
              <option value="normal">Normal</option>
              <option value="horario">Horário marcado</option>
              <option value="prioridade">Prioridade</option>
            </select>
          </div>
        </div>
        {form.priority === "horario" && (
          <>
            <label style={{ fontSize: 12, color: "#64748b" }}>Horário agendado</label>
            <input type="datetime-local" value={form.scheduled_time?.substring(0, 16) || ""} onChange={(e) => setForm({ ...form, scheduled_time: e.target.value })} style={css} />
          </>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <Button variant="soft" type="button" onClick={onClose} style={{ flex: 1 }}>Cancelar</Button>
          <Button type="submit" disabled={busy} style={{ flex: 1 }} data-testid="edit-submit">
            {busy ? "Salvando..." : "Salvar alterações"}
          </Button>
        </div>
      </form>
    </div>
  );
}
