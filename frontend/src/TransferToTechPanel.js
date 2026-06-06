/**
 * TransferToTechPanel — UX simples para transferir ONTs do estoque da praça
 * para um técnico. Padrão validado (ServiceTitan, Finale Inventory):
 *
 *   - Fila por praça (queue-based)
 *   - Bulk select com checkboxes
 *   - Scanner SN/MAC (input com autofoco; "Enter" seleciona)
 *   - iter197c — Botão Câmera abre OntScanBatchModal (Claude Vision)
 *     com validação em tempo real (alerta se SN não está no estoque)
 *   - Dropdown técnico
 *   - 1 botão "Transferir N selecionadas"
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api";
import OntScanBatchModal from "@/OntScanBatchModal";

const inputStyle = {
  padding: "8px 12px", fontSize: 14, border: "1px solid #cbd5e1",
  borderRadius: 8, background: "white", color: "#0f172a", width: "100%",
};

function normalizeMac(s) {
  const clean = (s || "").replace(/[^0-9A-Fa-f]/g, "").toUpperCase();
  return clean.match(/.{1,2}/g)?.join(":") || "";
}

/** iter197c — Resolve um SN/MAC livre para a ONT correspondente do estoque.
 *  Retorna o objeto ONT ou null. */
function findOntByIdent(ident, list) {
  const raw = (ident || "").trim().toUpperCase();
  if (!raw) return null;
  // 1) Match exato por SN (campo prevalente)
  let found = list.find((o) => (o.scan_sn || o.sn || "").toUpperCase() === raw);
  if (found) return found;
  // 2) Match por MAC normalizado
  const mac = normalizeMac(raw);
  if (mac) {
    found = list.find((o) => (o.mac || "").toUpperCase() === mac);
    if (found) return found;
  }
  // 3) Match por MAC placeholder "SN-..."
  found = list.find((o) => (o.mac || "").toUpperCase() === `SN-${raw}`);
  return found || null;
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
  const [scanModalOpen, setScanModalOpen] = useState(false);
  const [scanReport, setScanReport] = useState(null); // {ok, notFound, alreadyAssigned}
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

  // Todos os ONTs para validação de "já alocada" (qualquer location/status)
  const allOntsLookup = onts;

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

  /** iter197c — Input manual aceita SN OU MAC (Enter para adicionar). */
  function onScan(e) {
    if (e.key !== "Enter") return;
    const found = findOntByIdent(scanInput, available);
    if (!found) {
      // Tenta achar em qualquer location pra dar mensagem útil
      const elsewhere = findOntByIdent(scanInput, allOntsLookup);
      if (elsewhere) {
        const where = elsewhere.location_type === "tecnico"
          ? "já está no estoque de um técnico"
          : elsewhere.location_type === "cliente"
            ? "já está instalada num cliente"
            : `está em ${elsewhere.location_type} (${elsewhere.status})`;
        setFlash(`️ ${scanInput} ${where} — não pode transferir`);
      } else {
        setFlash(`❌ ${scanInput} não encontrado no estoque`);
      }
      setTimeout(() => setFlash(""), 3500);
      return;
    }
    setSelectedMacs((prev) => new Set([...prev, found.mac]));
    setScanInput("");
    setFlash(`✅ ${found.scan_sn || found.mac} adicionado`);
    setTimeout(() => setFlash(""), 1500);
  }

  /** iter197c — Câmera escaneou várias etiquetas: valida cada SN. */
  function onCameraScanned(scanned) {
    // scanned = [{mac, sn, ...}]
    const report = { ok: [], notInStock: [], elsewhere: [] };
    const newSelection = new Set(selectedMacs);
    for (const it of scanned) {
      const ident = (it.sn || it.mac || "").trim().toUpperCase();
      if (!ident) continue;
      const found = findOntByIdent(ident, available);
      if (found) {
        newSelection.add(found.mac);
        report.ok.push({ sn: found.scan_sn || ident, mac: found.mac });
      } else {
        const elsewhere = findOntByIdent(ident, allOntsLookup);
        if (elsewhere) {
          report.elsewhere.push({
            sn: it.sn || ident, mac: it.mac,
            location: elsewhere.location_type, status: elsewhere.status,
          });
        } else {
          report.notInStock.push({ sn: it.sn || ident, mac: it.mac });
        }
      }
    }
    setSelectedMacs(newSelection);
    setScanReport(report);
    setScanModalOpen(false);
    setFlash(`✅ ${report.ok.length} aceitas · ️ ${report.elsewhere.length} alocadas · ❌ ${report.notInStock.length} não cadastradas`);
    setTimeout(() => setFlash(""), 6000);
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
        msg += ` · ️ ${r.skipped.length} ignoradas: `
          + r.skipped.slice(0, 3).map((s) => `${s.mac} (${s.reason})`).join(", ");
      }
      setFlash(msg);
      setSelectedMacs(new Set());
      setScanReport(null);
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
      <div style={{ marginBottom: 16, display: "flex",
                       alignItems: "flex-start", justifyContent: "space-between",
                       gap: 12, flexWrap: "wrap" }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800, color: "#0f172a" }}>
            Transferir do Estoque da Praça → Técnico
          </h3>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
            Base é por <strong>SN</strong>. Use o scanner ou digite o SN.
          </div>
        </div>
        {/* iter211m — atalho de migração quando há ONTs sem SN real */}
        {(() => {
          const semSn = available.filter((o) => {
            const sn = (o.scan_sn || o.sn || "");
            return !sn || /^(AUTOSN_|MANUAL-|SN-)/i.test(sn);
          }).length;
          if (semSn === 0) return null;
          return (
            <div style={{
              padding: "8px 12px", background: "#fef3c7",
              border: "1px solid #fcd34d", borderRadius: 10,
              fontSize: 12, color: "#92400e", fontWeight: 600,
              display: "flex", gap: 10, alignItems: "center",
            }}>
              <span>️ {semSn} ONT(s) sem SN real</span>
              <button
                data-testid="transfer-migrate-sn-btn"
                onClick={async () => {
                  if (!window.confirm(
                    "Vai gerar SN placeholder (AUTOSN_*) para todas as ONTs "
                    + "sem SN. Depois você pode editar cada uma com o SN real. "
                    + "Continuar?")) return;
                  try {
                    const r = await api.stokOntsMigrateFillSn();
                    await load();
                    await window.alert(r.message || "Migração concluída.");
                  } catch (e) {
                    await window.alert("Erro: "
                      + (e?.response?.data?.detail || e.message));
                  }
                }}
                style={{
                  padding: "5px 10px", background: "#f59e0b", color: "#fff",
                  border: 0, borderRadius: 6, fontSize: 11, fontWeight: 800,
                  cursor: "pointer",
                }}>
                Gerar SNs placeholder
              </button>
            </div>
          );
        })()}
      </div>

      {/* Toolbar — iter197c grid agora tem botão de câmera */}
      <div style={{ display: "grid",
                     gridTemplateColumns: "180px 1fr auto 1fr auto",
                     gap: 10, marginBottom: 14 }}>
        <select value={pracaFilter} onChange={(e) => {
          setPracaFilter(e.target.value); setSelectedMacs(new Set());
        }}
                data-testid="transfer-praca-filter"
                style={inputStyle}>
          <option value="">Todas as praças</option>
          {pracas.map((p) =>
            <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>

        <input
          ref={scanRef}
          value={scanInput}
          onChange={(e) => setScanInput(e.target.value)}
          onKeyDown={onScan}
          data-testid="transfer-scan-input"
          placeholder="SN ou MAC + Enter…"
          style={{ ...inputStyle, fontFamily: "monospace" }}
        />

        <button
          type="button"
          onClick={() => setScanModalOpen(true)}
          data-testid="transfer-scan-camera-btn"
          title="Escanear várias etiquetas com a câmera (Claude Vision)"
          style={{ padding: "0 12px", background: "#0f172a", color: "white",
                    border: "none", borderRadius: 8, fontWeight: 800,
                    fontSize: 12, cursor: "pointer", whiteSpace: "nowrap" }}>
          Câmera
        </button>

        <select value={techId} onChange={(e) => setTechId(e.target.value)}
                data-testid="transfer-tech-select"
                style={inputStyle}>
          <option value="">Selecione o técnico…</option>
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
          {busy ? "..." : `Transferir ${selectedMacs.size}`}
        </button>
      </div>

      {flash && (
        <div data-testid="transfer-flash"
              style={{ marginBottom: 10, padding: "8px 12px",
                        borderRadius: 8, fontSize: 13,
                        background: flash.startsWith("❌") ? "#fee2e2"
                                    : flash.startsWith("️") ? "#fef3c7"
                                    : "#d1fae5",
                        color: flash.startsWith("❌") ? "#991b1b"
                                : flash.startsWith("️") ? "#92400e"
                                : "#065f46" }}>
          {flash}
        </div>
      )}

      {/* iter197c — Relatório de scan da câmera */}
      {scanReport && (scanReport.elsewhere.length > 0 || scanReport.notInStock.length > 0) && (
        <div data-testid="transfer-scan-report"
              style={{ marginBottom: 12, padding: 12,
                        background: "#fef3c7", border: "1.5px solid #f59e0b",
                        borderRadius: 10, fontSize: 12 }}>
          <div style={{ fontWeight: 800, color: "#92400e", marginBottom: 6 }}>
            ️ {scanReport.elsewhere.length + scanReport.notInStock.length} etiqueta(s) escaneada(s) com problema:
          </div>
          {scanReport.elsewhere.map((e, i) => (
            <div key={`e${i}`} style={{ marginBottom: 3, fontFamily: "monospace" }}>
              • <strong>{e.sn}</strong> — já alocada em <strong>{e.location}</strong> ({e.status})
            </div>
          ))}
          {scanReport.notInStock.map((n, i) => (
            <div key={`n${i}`} style={{ marginBottom: 3, fontFamily: "monospace", color: "#7f1d1d" }}>
              • <strong>{n.sn}</strong> — não cadastrada no estoque (faça uma compra primeiro)
            </div>
          ))}
          <button onClick={() => setScanReport(null)}
                  style={{ marginTop: 8, padding: "4px 10px", fontSize: 11,
                            background: "white", border: "1px solid #f59e0b",
                            color: "#92400e", borderRadius: 6, cursor: "pointer",
                            fontWeight: 700 }}>
            Dispensar relatório
          </button>
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

      {/* Lista de ONTs — iter197 SN é o identificador prevalente */}
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
            const sn = o.scan_sn || o.sn || "";
            const isAutoSn = /^(AUTOSN_|MANUAL-|SN-)/i.test(sn);
            const isPlaceholderMac = /^(SN-|AUTOSN_|MANUAL-)/i.test(o.mac || "");
            // iter211m — Display SN-first, em destaque, com botão de edição
            // quando SN é placeholder ou está faltando.
            const needsRealSn = !sn || isAutoSn;
            return (
              <label key={o.mac}
                      data-testid={`transfer-row-${o.mac}`}
                      style={{
                        display: "flex", alignItems: "center", gap: 10,
                        padding: "8px 10px",
                        background: checked ? "#dbeafe"
                                      : needsRealSn ? "#fef9c3" : "white",
                        borderBottom: "1px solid #f1f5f9",
                        cursor: "pointer", fontSize: 13,
                      }}>
                <input type="checkbox" checked={checked}
                        onChange={() => toggle(o.mac)} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: "monospace", fontWeight: 800,
                                  color: needsRealSn ? "#a16207" : "#0f172a",
                                  fontSize: 13 }}>
                    ️ SN: {sn || "— vazio —"}
                  </div>
                  <div style={{ fontFamily: "monospace", fontSize: 10,
                                  color: "#64748b" }}>
                    MAC: {isPlaceholderMac ? "(placeholder)" : (o.mac || "—")}
                  </div>
                </div>
                {needsRealSn && (
                  <button
                    data-testid={`row-set-sn-${o.mac}`}
                    type="button"
                    onClick={async (e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      const novo = window.prompt(
                        `SN real (escaneie a etiqueta).\nAtual: ${sn || "(vazio)"}\n\nMAC: ${o.mac}`,
                        isAutoSn ? "" : sn,
                      );
                      const v = (novo || "").trim().toUpperCase();
                      if (!v) return;
                      try {
                        await api.stokOntSetSn(o.mac, v);
                        await load();
                      } catch (err) {
                        await window.alert("Erro: "
                          + (err?.response?.data?.detail || err.message));
                      }
                    }}
                    style={{
                      padding: "4px 8px", fontSize: 11, fontWeight: 700,
                      background: "#facc15", color: "#78350f",
                      border: 0, borderRadius: 6, cursor: "pointer",
                    }}>
                    ✏️ Definir SN
                  </button>
                )}
                <span style={{ color: "#475569", fontSize: 12 }}>
                  {o.model || "ONT"}
                </span>
                {o.praca_id && (
                  <span style={{ fontSize: 11, color: "#0369a1", fontWeight: 600 }}>
                    {pracaNameById[o.praca_id] || o.praca_id}
                  </span>
                )}
              </label>
            );
          })}
        </div>
      )}

      {/* iter197c — Scanner IA em lote com validação em tempo real */}
      {scanModalOpen && (
        <OntScanBatchModal
          open
          hint="Etiquetas das ONTs para transferir ao técnico"
          onClose={() => setScanModalOpen(false)}
          onSaved={onCameraScanned}
        />
      )}
    </div>
  );
}
