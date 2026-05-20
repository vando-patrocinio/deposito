/**
 * TransferToTechPanel — UX simples para transferir ONTs do estoque da praça
 * para um técnico. Padrão validado (ServiceTitan, Finale Inventory):
 *
 *   - Fila por praça (queue-based)
 *   - Bulk select com checkboxes
 *   - Scanner MAC (input com autofoco; "Enter" seleciona)
 *   - Dropdown técnico
 *   - 1 botão "Transferir N selecionadas"
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api";

const inputStyle = {
  padding: "8px 12px", fontSize: 14, border: "1px solid #cbd5e1",
  borderRadius: 8, background: "white", color: "#0f172a", width: "100%",
};

function normalizeMac(s) {
  const clean = (s || "").replace(/[^0-9A-Fa-f]/g, "").toUpperCase();
  return clean.match(/.{1,2}/g)?.join(":") || "";
}

export default function TransferToTechPanel({ pracas = [] }) {
  const [onts, setOnts] = useState([]);
  const [techs, setTechs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [selectedMacs, setSelectedMacs] = useState(new Set());
  const [pracaFilter, setPracaFilter] = useState("");
  const [techId, setTechId] = useState("");
  const [scanInput, setScanInput] = useState("");
  const [flash, setFlash] = useState("");
  const scanRef = useRef(null);

  async function load() {
    setLoading(true);
    try {
      const [o, t] = await Promise.all([
        api.stokOntsList(),
        api.stokTechnicians(),
      ]);
      setOnts(o || []);
      setTechs(t || []);
    } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  // ONTs no estoque da empresa (=praça), filtradas por praça selecionada
  const available = useMemo(() => onts.filter((o) =>
    o.location_type === "empresa" &&
    o.status === "disponivel" &&
    (!pracaFilter || o.praca_id === pracaFilter),
  ), [onts, pracaFilter]);

  const pracaNameById = useMemo(() => {
    const m = {};
    pracas.forEach((p) => { m[p.id] = p.name; });
    return m;
  }, [pracas]);

  function toggle(mac) {
    setSelectedMacs((prev) => {
      const next = new Set(prev);
      if (next.has(mac)) next.delete(mac); else next.add(mac);
      return next;
    });
  }
  function toggleAll() {
    if (selectedMacs.size === available.length) setSelectedMacs(new Set());
    else setSelectedMacs(new Set(available.map((o) => o.mac)));
  }

  function onScan(e) {
    if (e.key !== "Enter") return;
    const mac = normalizeMac(scanInput);
    if (!mac) return;
    const found = available.find((o) => o.mac === mac);
    if (!found) {
      setFlash(`❌ MAC ${mac} não está disponível no estoque`);
      setTimeout(() => setFlash(""), 3000);
      return;
    }
    setSelectedMacs((prev) => new Set([...prev, mac]));
    setScanInput("");
    setFlash(`✅ ${mac} adicionado`);
    setTimeout(() => setFlash(""), 1500);
  }

  async function transfer() {
    if (!techId) { setFlash("❌ Escolha o técnico"); return; }
    if (selectedMacs.size === 0) { setFlash("❌ Selecione ao menos 1 ONT"); return; }
    if (!window.confirm(
      `Transferir ${selectedMacs.size} ONT(s) para o técnico selecionado?`)) return;
    setBusy(true);
    try {
      const r = await api.stokOntsBulkTransfer(
        Array.from(selectedMacs), techId);
      const tech = techs.find((t) => t.id === techId);
      let msg = `✅ ${r.transferred_count} ONT(s) transferidas para ${tech?.name}`;
      if (r.skipped?.length) {
        msg += ` · ⚠️ ${r.skipped.length} ignoradas: `
          + r.skipped.slice(0, 3).map((s) => `${s.mac} (${s.reason})`).join(", ");
      }
      setFlash(msg);
      setSelectedMacs(new Set());
      await load();
    } catch (e) {
      setFlash("❌ " + (e?.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
      setTimeout(() => setFlash(""), 8000);
    }
  }

  if (loading) return <div style={{ padding: 20, color: "#64748b" }}>Carregando estoque…</div>;

  return (
    <div data-testid="transfer-to-tech-panel"
          style={{ background: "white", border: "1px solid #e2e8f0",
                    borderRadius: 14, padding: 22, marginTop: 22 }}>
      <div style={{ marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800, color: "#0f172a" }}>
          🚚 Transferir do Estoque da Praça → Técnico
        </h3>
        <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
          Selecione ONTs (ou escaneie/cole MACs) e escolha o técnico destino.
        </div>
      </div>

      {/* Toolbar */}
      <div style={{ display: "grid",
                     gridTemplateColumns: "180px 1fr 1fr auto",
                     gap: 10, marginBottom: 14 }}>
        <select value={pracaFilter} onChange={(e) => {
          setPracaFilter(e.target.value); setSelectedMacs(new Set());
        }}
                data-testid="transfer-praca-filter"
                style={inputStyle}>
          <option value="">📦 Todas as praças</option>
          {pracas.map((p) =>
            <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>

        <input
          ref={scanRef}
          value={scanInput}
          onChange={(e) => setScanInput(e.target.value)}
          onKeyDown={onScan}
          data-testid="transfer-scan-input"
          placeholder="📷 Escaneie ou cole MAC + Enter…"
          style={{ ...inputStyle, fontFamily: "monospace" }}
        />

        <select value={techId} onChange={(e) => setTechId(e.target.value)}
                data-testid="transfer-tech-select"
                style={inputStyle}>
          <option value="">👷 Selecione o técnico…</option>
          {techs.map((t) =>
            <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>

        <button
          onClick={transfer}
          disabled={busy || selectedMacs.size === 0 || !techId}
          data-testid="transfer-submit"
          style={{
            padding: "8px 18px", fontWeight: 700, fontSize: 13,
            background: selectedMacs.size && techId ? "#0f172a" : "#94a3b8",
            color: "white", border: "none", borderRadius: 8,
            cursor: busy ? "not-allowed" : "pointer",
            whiteSpace: "nowrap",
          }}
        >
          {busy ? "..." : `🚚 Transferir ${selectedMacs.size}`}
        </button>
      </div>

      {flash && (
        <div data-testid="transfer-flash"
              style={{ marginBottom: 10, padding: "8px 12px",
                        borderRadius: 8, fontSize: 13,
                        background: flash.startsWith("❌") ? "#fee2e2" : "#d1fae5",
                        color: flash.startsWith("❌") ? "#991b1b" : "#065f46" }}>
          {flash}
        </div>
      )}

      {/* Progresso */}
      <div style={{ display: "flex", justifyContent: "space-between",
                     alignItems: "center", padding: "8px 12px",
                     background: "#f8fafc", borderRadius: 8,
                     fontSize: 12, color: "#475569", marginBottom: 8 }}>
        <span><strong>{selectedMacs.size}</strong> de <strong>{available.length}</strong> ONT(s) selecionadas</span>
        <button onClick={toggleAll}
                data-testid="transfer-toggle-all"
                style={{ padding: "4px 10px", fontSize: 11,
                          background: "white", border: "1px solid #cbd5e1",
                          borderRadius: 6, cursor: "pointer", fontWeight: 600 }}>
          {selectedMacs.size === available.length ? "Limpar seleção" : "Selecionar todas"}
        </button>
      </div>

      {/* Lista de ONTs */}
      {available.length === 0 ? (
        <div style={{ padding: 28, textAlign: "center", color: "#94a3b8",
                       background: "#f8fafc", border: "1px dashed #cbd5e1",
                       borderRadius: 10 }}>
          {pracaFilter
            ? "Nenhuma ONT disponível nesta praça"
            : "Nenhuma ONT disponível para transferência. Faça uma compra primeiro."}
        </div>
      ) : (
        <div style={{ maxHeight: 380, overflowY: "auto" }}>
          {available.map((o) => {
            const checked = selectedMacs.has(o.mac);
            return (
              <label key={o.mac}
                      data-testid={`transfer-row-${o.mac}`}
                      style={{
                        display: "flex", alignItems: "center", gap: 10,
                        padding: "8px 10px",
                        background: checked ? "#dbeafe" : "white",
                        borderBottom: "1px solid #f1f5f9",
                        cursor: "pointer", fontSize: 13,
                      }}>
                <input type="checkbox" checked={checked}
                        onChange={() => toggle(o.mac)} />
                <span style={{ fontFamily: "monospace", fontWeight: 700,
                                color: "#0f172a" }}>
                  {o.mac}
                </span>
                <span style={{ color: "#475569", fontSize: 12 }}>
                  {o.model || "ONT"}
                </span>
                {o.praca_id && (
                  <span style={{ marginLeft: "auto", fontSize: 11,
                                  color: "#0369a1", fontWeight: 600 }}>
                    📦 {pracaNameById[o.praca_id] || o.praca_id}
                  </span>
                )}
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
