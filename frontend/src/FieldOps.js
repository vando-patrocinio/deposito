import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { Icon, Row } from "@/ui";
import FieldOpsFrota from "@/FieldOpsFrota";
import FieldOpsEstoque from "@/FieldOpsEstoque";
import { IsabellaCard, IsabellaOsBrief } from "@/FieldOpsIsabella";

/* =============================================================
   Smart Field Ops — módulo do técnico DENTRO do CollaboratorApp.
   Conexão oficial App ↔ SmartProv via /api/field/* (JWT real).
   Visual 100% SmartProv: mesmos cards, paleta e tipografia.
============================================================= */

export const appCard = {
  background: "white", border: "1px solid #e5e7eb", borderRadius: 14,
  padding: 18, boxShadow: "0 1px 2px rgba(15,23,42,.04)", marginBottom: 12,
};
export const sectionLabel = {
  fontSize: 10, fontWeight: 700, color: "#64748b",
  letterSpacing: 1, textTransform: "uppercase",
};
export const darkBtn = {
  width: "100%", height: 48, borderRadius: 12, border: 0,
  background: "#0f172a", color: "white", fontWeight: 700, fontSize: 14,
  cursor: "pointer", display: "inline-flex", alignItems: "center",
  justifyContent: "center", gap: 8,
};
export const softBtn = {
  ...darkBtn, background: "white", color: "#0f172a",
  border: "1px solid #e2e8f0", fontWeight: 600,
};
export const fieldInput = {
  width: "100%", padding: "12px 14px", borderRadius: 10,
  border: "1.5px solid #e2e8f0", fontSize: 14, color: "#0f172a",
  background: "white", boxSizing: "border-box",
};

export function getGps() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy: p.coords.accuracy }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 5000 },
    );
  });
}

export function readPhotoFile(file, maxSide = 1280) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", 0.82));
      };
      img.onerror = reject;
      img.src = reader.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

const TYPE_LABEL = { instalacao: "Instalação", reparo: "Reparo", retirada: "Retirada", troca: "Troca" };

function StatusPill({ status }) {
  const map = {
    pendente: { bg: "#fffbeb", fg: "#92400e", bd: "#fcd34d", label: "Pendente" },
    aberta: { bg: "#ecfdf5", fg: "#065f46", bd: "#86efac", label: "Em andamento" },
    finalizada: { bg: "#f1f5f9", fg: "#475569", bd: "#cbd5e1", label: "Finalizada" },
    encerrada: { bg: "#f1f5f9", fg: "#475569", bd: "#cbd5e1", label: "Encerrada" },
  };
  const s = map[status] || map.pendente;
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: "3px 8px", borderRadius: 999, background: s.bg, color: s.fg, border: `1px solid ${s.bd}` }}>
      {s.label}
    </span>
  );
}

function hhmm(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo" });
  } catch { return "—"; }
}

/* ---------------- OS card (lista do dia) ---------------- */
function OsCard({ t, onOpen }) {
  const snap = t.client_snapshot || {};
  return (
    <button data-testid={`field-os-card-${t.id}`} onClick={onOpen}
      style={{ ...appCard, width: "100%", textAlign: "left", cursor: "pointer", marginBottom: 10, padding: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <span style={{ fontWeight: 800, fontSize: 14, color: "#0f172a" }}>{snap.name || "Cliente"}</span>
        <StatusPill status={t.status} />
      </div>
      <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>{snap.address || ""}</div>
      <div style={{ display: "flex", gap: 10, marginTop: 8, fontSize: 11, color: "#475569", fontWeight: 600 }}>
        <span>{TYPE_LABEL[t.type] || t.type}</span>
        <span>· {hhmm(t.scheduled_time)}</span>
        {t.priority === "horario" && <span style={{ color: "#b45309" }}>· Janela fixa</span>}
        {t.needs_manager_action && <span style={{ color: "#b91c1c" }}>· Aguardando gestor</span>}
      </div>
    </button>
  );
}

/* ---------------- Detalhe da OS + ações ---------------- */
function OsDetail({ ticketId, collabId, readOnly, onBack, onOpenLousa }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);
  const [modal, setModal] = useState(null); // signal | material | reschedule | block
  const [catalog, setCatalog] = useState([]);

  const load = useCallback(async () => {
    try {
      setErr(null);
      const d = await api.fieldOsDetail(ticketId, collabId);
      setData(d);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }, [ticketId, collabId]);
  useEffect(() => { load(); }, [load]);

  const act = async (key, fn, okMsg) => {
    setBusy(key); setMsg(null); setErr(null);
    try {
      const r = await fn();
      setMsg(okMsg || r?.message || "Ação registrada no SmartProv");
      setModal(null);
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "object" ? (d.message || JSON.stringify(d)) : (d || e.message));
    } finally { setBusy(null); }
  };

  if (err && !data) {
    return (
      <div style={appCard}>
        <div style={{ color: "#b91c1c", fontSize: 13 }}>{String(err)}</div>
        <button style={{ ...softBtn, marginTop: 12 }} onClick={onBack} data-testid="field-os-detail-back-err">Voltar</button>
      </div>
    );
  }
  if (!data) return <div style={{ ...appCard, color: "#64748b", fontSize: 13 }}>Carregando OS…</div>;

  const t = data.ticket || {};
  const snap = t.client_snapshot || {};
  const isOpen = t.status === "aberta";
  const isPending = t.status === "pendente";
  const done = t.status === "finalizada" || t.status === "encerrada";

  return (
    <div data-testid="field-os-detail">
      <button onClick={onBack} data-testid="field-os-detail-back"
        style={{ background: "none", border: 0, color: "#0f172a", fontWeight: 700, fontSize: 13, cursor: "pointer", padding: "4px 0", marginBottom: 8, display: "inline-flex", alignItems: "center", gap: 6 }}>
        ← Voltar para o dia
      </button>

      {msg && <div data-testid="field-action-ok" style={{ background: "#ecfdf5", color: "#065f46", border: "1px solid #86efac", padding: "10px 12px", borderRadius: 10, fontSize: 12, marginBottom: 10 }}>{msg}</div>}
      {err && <div data-testid="field-action-err" style={{ background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca", padding: "10px 12px", borderRadius: 10, fontSize: 12, marginBottom: 10 }}>{String(err)}</div>}

      <div style={appCard}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
          <div style={sectionLabel}>{TYPE_LABEL[t.type] || t.type} · {hhmm(t.scheduled_time)}</div>
          <StatusPill status={t.status} />
        </div>
        <div style={{ fontSize: 19, fontWeight: 800, color: "#0f172a", marginTop: 6 }}>{snap.name}</div>
        <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>{snap.address}{snap.neighborhood ? ` · ${snap.neighborhood}` : ""}</div>
        {snap.relato && (
          <div style={{ marginTop: 10, padding: 10, borderRadius: 10, background: "#f8fafc", border: "1px solid #eef2f7", fontSize: 12, color: "#475569" }}>
            <div style={{ ...sectionLabel, marginBottom: 4 }}>Relato / diagnóstico</div>
            {snap.relato}
          </div>
        )}
        <div style={{ marginTop: 10 }}>
          <Row label="Telefone" value={snap.phone || "—"} />
          <Row label="PPPoE" value={snap.pppoe_user || data.subscriber?.pppoe_user || "—"} />
          <Row label="Plano" value={data.subscriber?.plan_name || data.subscriber?.plan || "—"} />
          <Row label="CTO" value={data.cto ? `${data.cto.name}${data.cto_port ? ` · porta ${data.cto_port}` : ""}` : "—"} />
          {(data.equipment || []).map((e) => (
            <Row key={e.mac} label="ONU" value={`${e.mac}${e.scan_sn ? ` · ${e.scan_sn}` : ""}`} />
          ))}
          {t.field_arrived_at && <Row label="Chegada" value={hhmm(t.field_arrived_at)} />}
        </div>
      </div>

      {!done && <IsabellaOsBrief ticketId={t.id} collabId={collabId} />}

      {done && t.isabella_score && (
        <div data-testid="isabella-score-card" style={{ ...appCard, padding: 14, border: "1.5px solid #0f172a" }}>
          <div style={{ ...sectionLabel, marginBottom: 8 }}>Nota Isabella desta OS</div>
          <div style={{ display: "flex", gap: 8 }}>
            {[["Qualidade", t.isabella_score.qualidade], ["Organização", t.isabella_score.organizacao],
              ["Processo", t.isabella_score.processo], ["Resultado", t.isabella_score.resultado]].map(([l, v]) => (
              <div key={l} style={{ flex: 1, textAlign: "center", padding: "8px 4px", borderRadius: 10, background: "#f8fafc", border: "1px solid #eef2f7" }}>
                <div style={{ fontSize: 16, fontWeight: 800, color: "#0f172a" }}>{v}</div>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>{l}</div>
              </div>
            ))}
          </div>
          <div style={{ textAlign: "center", marginTop: 8, fontSize: 13, fontWeight: 800, color: "#0f172a" }}>
            Nota final: {t.isabella_score.nota_final}/10
          </div>
        </div>
      )}

      {!readOnly && !done && (
        <div style={{ ...appCard, padding: 14 }}>
          <div style={{ ...sectionLabel, marginBottom: 10 }}>Ações de campo</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            {isPending && (
              <button data-testid="field-action-start" disabled={busy}
                onClick={() => act("start", async () => {
                  const gps = await getGps();
                  return api.fieldOsStart(t.id, gps || {});
                }, "OS iniciada — bolha aberta na Lousa")}
                style={{ ...darkBtn, gridColumn: "1 / -1", opacity: busy === "start" ? 0.6 : 1 }}>
                <Icon name="clipboard" /> {busy === "start" ? "..." : "Iniciar OS"}
              </button>
            )}
            <button data-testid="field-action-arrive" disabled={busy || !isOpen && !isPending}
              onClick={() => act("arrive", async () => {
                const gps = await getGps();
                if (!gps) throw new Error("GPS indisponível — ative a localização");
                return api.fieldOsArrive(t.id, gps);
              }, "Chegada registrada (GPS)")}
              style={{ ...softBtn, opacity: busy === "arrive" ? 0.6 : 1 }}>
              {busy === "arrive" ? "..." : "Cheguei no local"}
            </button>
            <label data-testid="field-action-photo" style={{ ...softBtn, opacity: busy === "photo" ? 0.6 : 1 }}>
              {busy === "photo" ? "..." : "Anexar foto"}
              <input type="file" accept="image/*" capture="environment" style={{ display: "none" }}
                onChange={async (ev) => {
                  const f = ev.target.files?.[0];
                  ev.target.value = "";
                  if (!f) return;
                  await act("photo", async () => {
                    const dataUrl = await readPhotoFile(f);
                    return api.fieldOsPhoto(t.id, { data_url: dataUrl, kind: "evidencia" });
                  }, "Foto enviada ao SmartProv");
                }} />
            </label>
            <button data-testid="field-action-signal" disabled={busy} onClick={() => setModal("signal")} style={softBtn}>
              Registrar sinal dBm
            </button>
            <button data-testid="field-action-material" disabled={busy}
              onClick={async () => {
                if (!catalog.length) {
                  try { const c = await api.fieldMaterialsCatalog(); setCatalog(c.items || []); } catch { /* */ }
                }
                setModal("material");
              }} style={softBtn}>
              Material usado
            </button>
            <button data-testid="field-action-reschedule" disabled={busy} onClick={() => setModal("reschedule")} style={softBtn}>
              Reagendar
            </button>
            <button data-testid="field-action-block" disabled={busy} onClick={() => setModal("block")} style={{ ...softBtn, color: "#b91c1c", borderColor: "#fecaca" }}>
              Impedimento
            </button>
            {isOpen && (
              <button data-testid="field-action-finish" onClick={onOpenLousa}
                style={{ ...darkBtn, gridColumn: "1 / -1", background: "#065f46" }}>
                Finalizar na Lousa (checklist completo)
              </button>
            )}
          </div>
          <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 10, lineHeight: 1.5 }}>
            Toda ação é gravada no SmartProv em tempo real: Lousa, estoque, auditoria e Presidente IA.
          </div>
        </div>
      )}

      {/* Evidências registradas */}
      {(data.photos?.length > 0 || data.signal_tests?.length > 0 || data.materials?.length > 0) && (
        <div style={{ ...appCard, padding: 14 }}>
          <div style={{ ...sectionLabel, marginBottom: 8 }}>Registros desta OS</div>
          {data.signal_tests?.map((s) => (
            <Row key={s.id} label={`Sinal ${s.phase === "before" ? "antes" : "depois"}`} value={`${s.dbm} dBm`} />
          ))}
          {data.photos?.length > 0 && <Row label="Fotos anexadas" value={String(data.photos.length)} />}
          {data.materials?.map((m) => (
            <Row key={m.id} label="Material" value={(m.items || []).map((i) => `${i.name} ×${i.quantity}`).join(", ")} />
          ))}
        </div>
      )}

      {/* Histórico (timeline da Lousa) */}
      {data.history?.length > 0 && (
        <div style={{ ...appCard, padding: 14 }}>
          <div style={{ ...sectionLabel, marginBottom: 8 }}>Histórico da OS</div>
          {data.history.slice(0, 8).map((h, i) => (
            <div key={i} style={{ fontSize: 11, color: "#475569", padding: "6px 0", borderBottom: i < 7 ? "1px solid #f1f5f9" : "none" }}>
              <strong style={{ color: "#0f172a" }}>{h.action}</strong> · {h.details || ""} <span style={{ color: "#94a3b8" }}>{hhmm(h.at || h.created_at)}</span>
            </div>
          ))}
        </div>
      )}

      {/* ---------- Modais de ação ---------- */}
      {modal === "signal" && (
        <ActionModal title="Registrar sinal (dBm)" onClose={() => setModal(null)}>
          <SignalForm busy={busy === "signal"} onSubmit={(body) => act("signal", () => api.fieldOsSignalTest(t.id, body), "Sinal registrado")} />
        </ActionModal>
      )}
      {modal === "material" && (
        <ActionModal title="Material usado" onClose={() => setModal(null)}>
          <MaterialForm catalog={catalog} busy={busy === "material"}
            onSubmit={(items) => act("material", () => api.fieldOsMaterialUsed(t.id, { items }), "Estoque baixado no SmartProv")} />
        </ActionModal>
      )}
      {modal === "reschedule" && (
        <ActionModal title="Propor reagendamento" onClose={() => setModal(null)}>
          <RescheduleForm busy={busy === "reschedule"}
            onSubmit={(body) => act("reschedule", () => api.fieldOsReschedule(t.id, body))} />
        </ActionModal>
      )}
      {modal === "block" && (
        <ActionModal title="Justificar impedimento" onClose={() => setModal(null)}>
          <BlockForm busy={busy === "block"}
            onSubmit={async (motivo) => {
              const gps = await getGps();
              return act("block", () => api.fieldOsBlockReason(t.id, { motivo, ...(gps || {}) }));
            }} />
        </ActionModal>
      )}
    </div>
  );
}

export function ActionModal({ title, onClose, children }) {
  return (
    <div data-testid="field-action-modal" style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.5)", zIndex: 1000, display: "flex", alignItems: "flex-end", justifyContent: "center" }} onClick={onClose}>
      <div style={{ background: "white", borderRadius: "16px 16px 0 0", padding: 18, width: "100%", maxWidth: 480, maxHeight: "80vh", overflowY: "auto" }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <div style={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>{title}</div>
          <button onClick={onClose} data-testid="field-modal-close" style={{ background: "none", border: 0, fontSize: 20, color: "#64748b", cursor: "pointer" }}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function SignalForm({ onSubmit, busy }) {
  const [dbm, setDbm] = useState("");
  const [phase, setPhase] = useState("before");
  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        {["before", "after"].map((p) => (
          <button key={p} data-testid={`signal-phase-${p}`} onClick={() => setPhase(p)}
            style={{ ...softBtn, height: 40, flex: 1, background: phase === p ? "#0f172a" : "white", color: phase === p ? "white" : "#0f172a" }}>
            {p === "before" ? "Antes" : "Depois"}
          </button>
        ))}
      </div>
      <input data-testid="signal-dbm-input" type="number" step="0.1" placeholder="Ex: -21.5" value={dbm}
        onChange={(e) => setDbm(e.target.value)} style={{ ...fieldInput, marginBottom: 10 }} />
      <button data-testid="signal-submit" disabled={busy || dbm === ""} onClick={() => onSubmit({ dbm: parseFloat(dbm), phase })} style={darkBtn}>
        {busy ? "..." : "Registrar no SmartProv"}
      </button>
    </div>
  );
}

function MaterialForm({ catalog, onSubmit, busy }) {
  const [qty, setQty] = useState({});
  const items = Object.entries(qty).filter(([, v]) => v > 0).map(([k, v]) => ({ consumable_id: k, quantity: v }));
  return (
    <div>
      {(catalog || []).map((c) => (
        <div key={c.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid #f1f5f9" }}>
          <span style={{ fontSize: 13, color: "#0f172a", fontWeight: 600 }}>{c.name} <span style={{ color: "#94a3b8", fontWeight: 400 }}>({c.unit})</span></span>
          <input data-testid={`material-qty-${c.id}`} type="number" min="0" value={qty[c.id] || ""}
            onChange={(e) => setQty({ ...qty, [c.id]: parseInt(e.target.value || "0", 10) })}
            style={{ ...fieldInput, width: 80, padding: "8px 10px" }} placeholder="0" />
        </div>
      ))}
      <button data-testid="material-submit" disabled={busy || !items.length} onClick={() => onSubmit(items)} style={{ ...darkBtn, marginTop: 12, opacity: items.length ? 1 : 0.5 }}>
        {busy ? "..." : "Baixar do meu estoque"}
      </button>
    </div>
  );
}

function RescheduleForm({ onSubmit, busy }) {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("09:00");
  const [motivo, setMotivo] = useState("");
  return (
    <div>
      <input data-testid="resched-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} style={{ ...fieldInput, marginBottom: 8 }} />
      <input data-testid="resched-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} style={{ ...fieldInput, marginBottom: 8 }} />
      <textarea data-testid="resched-motivo" placeholder="Motivo (mín. 5 caracteres)" value={motivo} onChange={(e) => setMotivo(e.target.value)}
        style={{ ...fieldInput, minHeight: 70, marginBottom: 10 }} />
      <button data-testid="resched-submit" disabled={busy || !date || motivo.trim().length < 5}
        onClick={() => onSubmit({ new_date: date, new_time: time, motivo: motivo.trim() })} style={darkBtn}>
        {busy ? "..." : "Enviar ao gestor"}
      </button>
      <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 8 }}>O gestor confirma o reagendamento no SmartProv.</div>
    </div>
  );
}

function BlockForm({ onSubmit, busy }) {
  const [motivo, setMotivo] = useState("");
  return (
    <div>
      <textarea data-testid="block-motivo" placeholder="Descreva o impedimento (cliente ausente, sem acesso, endereço errado...)" value={motivo}
        onChange={(e) => setMotivo(e.target.value)} style={{ ...fieldInput, minHeight: 90, marginBottom: 10 }} />
      <button data-testid="block-submit" disabled={busy || motivo.trim().length < 5} onClick={() => onSubmit(motivo.trim())} style={{ ...darkBtn, background: "#b91c1c" }}>
        {busy ? "..." : "Registrar impedimento"}
      </button>
    </div>
  );
}

/* ---------------- Dashboard (Hoje) ---------------- */
function FieldDashboard({ dash, onOpenOs, collabId }) {
  if (!dash) return <div style={{ ...appCard, color: "#64748b", fontSize: 13 }}>Carregando painel…</div>;
  const c = dash.counts || {};
  const metric = (label, value, warn) => (
    <div style={{ flex: 1, minWidth: 70, padding: "10px 8px", borderRadius: 10, background: warn && value > 0 ? "#fef2f2" : "#f8fafc", border: `1px solid ${warn && value > 0 ? "#fecaca" : "#eef2f7"}`, textAlign: "center" }}>
      <div style={{ fontSize: 20, fontWeight: 800, color: warn && value > 0 ? "#b91c1c" : "#0f172a" }}>{value ?? 0}</div>
      <div style={{ fontSize: 9, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
    </div>
  );
  return (
    <div data-testid="field-dashboard">
      <IsabellaCard collabId={collabId} onOpenOs={onOpenOs} />
      <div style={{ ...appCard, padding: 14 }}>
        <div style={{ ...sectionLabel, marginBottom: 10 }}>Meu dia em campo</div>
        <div style={{ display: "flex", gap: 8 }}>
          {metric("Hoje", c.today)}
          {metric("Pendentes", c.pendentes)}
          {metric("Atrasadas", c.atrasadas, true)}
          {metric("Feitas", c.finalizadas_hoje)}
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap", fontSize: 11, fontWeight: 600 }}>
          <span style={{ color: dash.gps_active ? "#065f46" : "#b45309" }}>GPS {dash.gps_active ? "ativo" : "sem sinal recente"}</span>
          <span style={{ color: "#475569" }}>· Estoque: {dash.stock?.ont_count ?? 0} ONU(s)</span>
          {dash.vehicle?.inspection_required && (
            <span style={{ color: dash.vehicle.pending ? "#b91c1c" : "#065f46" }}>· Frota {dash.vehicle.pending ? "PENDENTE" : "ok"}</span>
          )}
        </div>
      </div>

      {dash.active_os && (
        <button data-testid="field-active-os" onClick={() => onOpenOs(dash.active_os.id)}
          style={{ ...appCard, width: "100%", textAlign: "left", cursor: "pointer", border: "2px solid #86efac", background: "#f0fdf4" }}>
          <div style={{ ...sectionLabel, color: "#065f46" }}>OS em andamento</div>
          <div style={{ fontWeight: 800, fontSize: 15, color: "#0f172a", marginTop: 4 }}>{(dash.active_os.client_snapshot || {}).name}</div>
          <div style={{ fontSize: 12, color: "#475569" }}>{TYPE_LABEL[dash.active_os.type] || dash.active_os.type} · aberta {hhmm(dash.active_os.opened_at)}</div>
        </button>
      )}

      {!dash.active_os && dash.next_os && (
        <button data-testid="field-next-os" onClick={() => onOpenOs(dash.next_os.id)}
          style={{ ...appCard, width: "100%", textAlign: "left", cursor: "pointer", border: "2px solid #bfdbfe", background: "#eff6ff" }}>
          <div style={{ ...sectionLabel, color: "#1d4ed8" }}>Próxima OS</div>
          <div style={{ fontWeight: 800, fontSize: 15, color: "#0f172a", marginTop: 4 }}>{(dash.next_os.client_snapshot || {}).name}</div>
          <div style={{ fontSize: 12, color: "#475569" }}>{TYPE_LABEL[dash.next_os.type] || dash.next_os.type} · {hhmm(dash.next_os.scheduled_time)} · {(dash.next_os.client_snapshot || {}).neighborhood || ""}</div>
        </button>
      )}

      <div style={{ ...sectionLabel, margin: "14px 2px 8px" }}>Ordens de serviço de hoje</div>
      {(dash.os_today || []).length === 0 && (
        <div style={{ ...appCard, color: "#64748b", fontSize: 13, textAlign: "center" }}>Nenhuma OS para hoje.</div>
      )}
      {(dash.os_today || []).map((t) => <OsCard key={t.id} t={t} onOpen={() => onOpenOs(t.id)} />)}
    </div>
  );
}

/* ---------------- Hub principal ---------------- */
export default function FieldOps({ collabId, onBack, onOpenLousa }) {
  const [tab, setTab] = useState("hoje");
  const [dash, setDash] = useState(null);
  const [authErr, setAuthErr] = useState(null);
  const [osId, setOsId] = useState(null);

  const loadDash = useCallback(async () => {
    try {
      setAuthErr(null);
      const d = await api.fieldDashboard(collabId);
      setDash(d);
    } catch (e) {
      const status = e?.response?.status;
      if (status === 401) setAuthErr("login");
      else if (status === 403) setAuthErr(e?.response?.data?.detail || "Sem permissão");
      else setAuthErr(e?.response?.data?.detail || e.message);
    }
  }, [collabId]);
  useEffect(() => { if (tab === "hoje" && !osId) loadDash(); }, [tab, osId, loadDash]);

  const TABS = [
    { id: "hoje", label: "Hoje" },
    { id: "estoque", label: "Estoque" },
    { id: "frota", label: "Frota" },
  ];

  if (authErr === "login") {
    return (
      <div data-testid="field-ops-login-required" style={{ ...appCard, padding: 24, textAlign: "center" }}>
        <div style={{ fontWeight: 800, fontSize: 16, color: "#0f172a", marginBottom: 8 }}>Login necessário</div>
        <div style={{ fontSize: 12, color: "#64748b", lineHeight: 1.6, marginBottom: 14 }}>
          O Smart Field Ops usa a autenticação oficial do SmartProv (JWT).
          Entre com seu e-mail e senha de colaborador para continuar.
        </div>
        <button style={darkBtn} data-testid="field-ops-go-login" onClick={() => { window.localStorage.removeItem("ponto_collab_id"); window.location.href = "/login"; }}>
          Ir para o login
        </button>
        <button style={{ ...softBtn, marginTop: 8 }} onClick={onBack} data-testid="field-ops-back-login">Voltar</button>
      </div>
    );
  }

  return (
    <div data-testid="field-ops-screen">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <button onClick={onBack} data-testid="field-ops-back"
          style={{ background: "none", border: 0, color: "#0f172a", fontWeight: 700, fontSize: 13, cursor: "pointer", padding: "4px 0" }}>
          ← Início
        </button>
        <div style={{ fontWeight: 800, fontSize: 14, color: "#0f172a" }}>Smart Field Ops</div>
        <span style={{ width: 40 }} />
      </div>

      {dash?.read_only && (
        <div data-testid="field-readonly-banner" style={{ background: "#fff7ed", border: "1.5px solid #fdba74", color: "#7c2d12", padding: "8px 12px", borderRadius: 10, fontSize: 11, fontWeight: 700, marginBottom: 10 }}>
          Modo gestor — somente leitura
        </div>
      )}

      {!osId && (
        <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
          {TABS.map((t) => (
            <button key={t.id} data-testid={`field-tab-${t.id}`} onClick={() => setTab(t.id)}
              style={{ flex: 1, height: 38, borderRadius: 10, border: "1px solid #e2e8f0", fontWeight: 700, fontSize: 12, cursor: "pointer",
                background: tab === t.id ? "#0f172a" : "white", color: tab === t.id ? "white" : "#475569" }}>
              {t.label}
            </button>
          ))}
        </div>
      )}

      {authErr && authErr !== "login" && (
        <div style={{ background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca", padding: "10px 12px", borderRadius: 10, fontSize: 12, marginBottom: 10 }}>{String(authErr)}</div>
      )}

      {osId ? (
        <OsDetail ticketId={osId} collabId={collabId} readOnly={dash?.read_only}
          onBack={() => { setOsId(null); loadDash(); }} onOpenLousa={onOpenLousa} />
      ) : tab === "hoje" ? (
        <FieldDashboard dash={dash} onOpenOs={setOsId} collabId={collabId} />
      ) : tab === "estoque" ? (
        <FieldOpsEstoque collabId={collabId} readOnly={dash?.read_only} />
      ) : (
        <FieldOpsFrota collabId={collabId} readOnly={dash?.read_only} />
      )}
    </div>
  );
}
