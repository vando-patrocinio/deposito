import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { Row } from "@/ui";
import { ActionModal, appCard, darkBtn, fieldInput, sectionLabel, softBtn } from "@/FieldOps";

/* =============================================================
   Estoque Inteligente + Retirada Inteligente do técnico.
   Dados REAIS do SmartProv: /api/field/stock/me e
   /api/field/equipment/return.
============================================================= */

export default function FieldOpsEstoque({ collabId, readOnly }) {
  const [stock, setStock] = useState(null);
  const [err, setErr] = useState(null);
  const [msg, setMsg] = useState(null);
  const [showReturn, setShowReturn] = useState(false);

  const load = useCallback(async () => {
    try {
      setErr(null);
      const s = await api.fieldStockMe(collabId);
      setStock(s);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }, [collabId]);
  useEffect(() => { load(); }, [load]);

  return (
    <div data-testid="field-estoque-screen">
      {msg && <div data-testid="estoque-ok" style={{ background: "#ecfdf5", color: "#065f46", border: "1px solid #86efac", padding: "10px 12px", borderRadius: 10, fontSize: 12, marginBottom: 10 }}>{msg}</div>}
      {err && <div data-testid="estoque-err" style={{ background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca", padding: "10px 12px", borderRadius: 10, fontSize: 12, marginBottom: 10 }}>{String(err)}</div>}

      <div style={{ ...appCard, padding: 14 }}>
        <div style={{ ...sectionLabel, marginBottom: 8 }}>Equipamentos comigo (ONU/ONT)</div>
        {!stock && <div style={{ fontSize: 12, color: "#64748b" }}>Carregando…</div>}
        {stock && stock.onts.length === 0 && <div style={{ fontSize: 12, color: "#64748b" }}>Nenhum equipamento no seu estoque.</div>}
        {stock && stock.onts.map((o) => (
          <div key={o.mac} style={{ padding: "8px 0", borderBottom: "1px solid #f1f5f9", fontSize: 12 }}>
            <div style={{ fontWeight: 700, color: "#0f172a", fontFamily: "monospace" }}>{o.mac}</div>
            <div style={{ color: "#64748b", fontSize: 11 }}>
              {o.scan_sn ? `SN ${o.scan_sn} · ` : ""}{o.model || "Modelo desconhecido"} · {o.status}
            </div>
          </div>
        ))}
      </div>

      <div style={{ ...appCard, padding: 14 }}>
        <div style={{ ...sectionLabel, marginBottom: 8 }}>Materiais (consumíveis)</div>
        {stock && stock.consumables.length === 0 && <div style={{ fontSize: 12, color: "#64748b" }}>Sem saldo registrado.</div>}
        {stock && stock.consumables.map((c) => (
          <Row key={c.consumable_id} label={c.name}
            value={<span style={{ color: c.quantity < 0 ? "#b91c1c" : "#0f172a", fontWeight: 700 }}>{c.quantity} {c.unit}</span>} />
        ))}
      </div>

      {!readOnly && (
        <button data-testid="estoque-open-return" onClick={() => setShowReturn(true)} style={darkBtn}>
          Registrar retirada de equipamento
        </button>
      )}

      {showReturn && (
        <ActionModal title="Retirada de equipamento" onClose={() => setShowReturn(false)}>
          <ReturnForm onDone={(m) => { setMsg(m); setShowReturn(false); load(); }} />
        </ActionModal>
      )}
    </div>
  );
}

function ReturnForm({ onDone }) {
  const [mac, setMac] = useState("");
  const [sn, setSn] = useState("");
  const [recovered, setRecovered] = useState(true);
  const [state, setState] = useState("bom");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.fieldEquipmentReturn({
        mac: mac.trim() || null, sn: sn.trim() || null,
        recovered, physical_state: state, notes: notes || null,
      });
      const fin = r.value_lost > 0
        ? `Perda registrada: R$ ${r.value_lost.toFixed(2)} (financeiro notificado)`
        : `Valor recuperado: R$ ${r.value_recovered.toFixed(2)}`;
      onDone(`Retirada registrada no SmartProv. ${fin}`);
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "object" ? d.message : (d || e.message));
    } finally { setBusy(false); }
  };

  return (
    <div>
      {err && <div style={{ background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca", padding: "8px 12px", borderRadius: 10, fontSize: 12, marginBottom: 10 }}>{String(err)}</div>}
      <input data-testid="return-mac" placeholder="MAC (AA:BB:CC:DD:EE:FF)" value={mac}
        onChange={(e) => setMac(e.target.value.toUpperCase())} style={{ ...fieldInput, marginBottom: 8, fontFamily: "monospace" }} />
      <input data-testid="return-sn" placeholder="ou SN da etiqueta" value={sn}
        onChange={(e) => setSn(e.target.value.toUpperCase())} style={{ ...fieldInput, marginBottom: 10, fontFamily: "monospace" }} />

      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <button data-testid="return-recovered-yes" onClick={() => setRecovered(true)}
          style={{ ...softBtn, height: 42, flex: 1, background: recovered ? "#0f172a" : "white", color: recovered ? "white" : "#0f172a" }}>
          Recuperado
        </button>
        <button data-testid="return-recovered-no" onClick={() => setRecovered(false)}
          style={{ ...softBtn, height: 42, flex: 1, background: !recovered ? "#b91c1c" : "white", color: !recovered ? "white" : "#b91c1c", borderColor: "#fecaca" }}>
          Não devolvido
        </button>
      </div>

      {recovered && (
        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          {[["bom", "Bom"], ["danificado", "Danificado"], ["inutilizado", "Inutilizado"]].map(([k, l]) => (
            <button key={k} data-testid={`return-state-${k}`} onClick={() => setState(k)}
              style={{ ...softBtn, height: 38, flex: 1, fontSize: 11, background: state === k ? "#0f172a" : "white", color: state === k ? "white" : "#475569" }}>
              {l}
            </button>
          ))}
        </div>
      )}

      <textarea data-testid="return-notes" placeholder="Observações (estado físico, acessórios...)" value={notes}
        onChange={(e) => setNotes(e.target.value)} style={{ ...fieldInput, minHeight: 60, marginBottom: 10 }} />

      <button data-testid="return-submit" disabled={busy || (!mac.trim() && !sn.trim())} onClick={submit}
        style={{ ...darkBtn, opacity: (mac.trim() || sn.trim()) ? 1 : 0.5 }}>
        {busy ? "..." : "Registrar no SmartProv"}
      </button>
      <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 8, lineHeight: 1.5 }}>
        Equipamento recuperado volta ao seu estoque; porta da CTO é liberada;
        impacto financeiro do comodato alimenta o DRE automaticamente.
      </div>
    </div>
  );
}
