/*
PhotoRequirementsCard.js — Cardápio de fotos obrigatórias por OS (iter211x)

Permite ao gestor:
  • Ligar/desligar cada exigência de foto
  • Editar label, ícone, instrução
  • Selecionar em quais tipos de OS a foto se aplica
  • Adicionar novas exigências de foto (ex: "comprovante", "painel da rua")
  • Reordenar via sort_order (up/down)

Os 3 defaults (cto, equipamento, sn) podem ser desligados mas NUNCA excluídos
— o backend reanexa automaticamente como required=false se faltarem.
*/
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Button, Card } from "@/ui";

const TICKET_TYPE_LABELS = {
  instalacao: "Instalação",
  troca: "Troca",
  reparo: "Reparo",
  retirada: "Retirada",
  prioridade: "Prioridade",
  preventiva: "Preventiva",
  venda: "Venda",
};

const ICONS = ["", "", "", "️", "", "", "", "✍️", "", "",
                  "", "️", "", "", "", "", ""];

export default function PhotoRequirementsCard() {
  const [items, setItems] = useState([]);
  const [validTypes, setValidTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [adding, setAdding] = useState(false);
  const [newItem, setNewItem] = useState({
    id: "", label: "", icon: "", instruction: "", ticket_types: [],
    stamp_location: false,
  });

  const reload = async () => {
    setLoading(true);
    try {
      const r = await api.lousaPhotoReqs();
      setItems(r.items || []);
      setValidTypes(r.valid_ticket_types || []);
    } catch (e) {
      setMsg("Erro ao carregar: " + (e?.response?.data?.detail || e.message));
    } finally { setLoading(false); }
  };
  useEffect(() => { reload(); }, []);

  const defaultIds = useMemo(() => new Set(["cto", "equipamento", "sn"]), []);

  const setItem = (id, patch) => {
    setItems((prev) => prev.map((it) => it.id === id ? { ...it, ...patch } : it));
  };

  const toggleTicketType = (id, type) => {
    setItems((prev) => prev.map((it) => {
      if (it.id !== id) return it;
      const has = (it.ticket_types || []).includes(type);
      return {
        ...it,
        ticket_types: has
          ? it.ticket_types.filter((t) => t !== type)
          : [...(it.ticket_types || []), type],
      };
    }));
  };

  const move = (id, dir) => {
    setItems((prev) => {
      const arr = [...prev];
      const i = arr.findIndex((it) => it.id === id);
      if (i < 0) return arr;
      const j = dir === "up" ? i - 1 : i + 1;
      if (j < 0 || j >= arr.length) return arr;
      [arr[i], arr[j]] = [arr[j], arr[i]];
      return arr.map((it, idx) => ({ ...it, sort_order: (idx + 1) * 10 }));
    });
  };

  const removeItem = (id) => {
    if (defaultIds.has(id)) {
      window.alert("Os 3 padrões (cto, equipamento, sn) não podem ser excluídos — desligue se não quiser exigir.");
      return;
    }
    if (!window.confirm("Remover esta exigência de foto?")) return;
    setItems((prev) => prev.filter((it) => it.id !== id));
  };

  const addNew = () => {
    const id = newItem.id.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9_-]{1,39}$/.test(id)) {
      window.alert("ID inválido. Use 2-40 caracteres minúsculos, números, _ ou -.");
      return;
    }
    if (items.some((it) => it.id === id)) {
      window.alert("Já existe uma foto com esse ID.");
      return;
    }
    if (!newItem.label.trim()) {
      window.alert("Informe o nome da foto.");
      return;
    }
    setItems((prev) => [...prev, {
      id, label: newItem.label.trim(),
      icon: newItem.icon || "",
      instruction: newItem.instruction || "",
      ticket_types: newItem.ticket_types || [],
      required: true, is_default: false,
      sort_order: (prev.length + 1) * 10,
      stamp_location: !!newItem.stamp_location,
    }]);
    setNewItem({ id: "", label: "", icon: "", instruction: "",
                 ticket_types: [], stamp_location: false });
    setAdding(false);
  };

  const save = async () => {
    setSaving(true); setMsg("");
    try {
      const payload = items.map((it) => ({
        id: it.id, label: it.label, icon: it.icon || "",
        instruction: it.instruction || "",
        ticket_types: it.ticket_types || [],
        required: !!it.required, sort_order: it.sort_order || 100,
        stamp_location: !!it.stamp_location,
      }));
      const r = await api.lousaSavePhotoReqs(payload);
      setItems(r.items || []);
      setMsg("✅ Cardápio de fotos salvo.");
      setTimeout(() => setMsg(""), 3000);
    } catch (e) {
      setMsg("❌ " + (e?.response?.data?.detail || e.message));
    } finally { setSaving(false); }
  };

  if (loading) return <Card title="Cardápio de fotos da OS">Carregando…</Card>;

  return (
    <Card title="Cardápio de fotos obrigatórias na OS"
          data-testid="photo-reqs-card"
          style={{ gridColumn: "1 / -1" }}>
      <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 14px" }}>
        Configure quais fotos o técnico precisa tirar em cada tipo de OS.
        Ligue/desligue, edite a instrução ou adicione novas exigências (ex: foto do painel da rua, comprovante assinado, etc).
      </p>

      <div style={{ display: "grid", gap: 10 }}>
        {items.map((it, idx) => {
          const isDefault = defaultIds.has(it.id);
          return (
            <div key={it.id}
                  data-testid={`photo-req-row-${it.id}`}
                  style={{
                    background: it.required ? "#f8fafc" : "#fef2f2",
                    border: `1px solid ${it.required ? "#cbd5e1" : "#fecaca"}`,
                    borderRadius: 10, padding: 12,
                  }}>
              <div style={{ display: "flex", gap: 10, alignItems: "flex-start",
                              flexWrap: "wrap" }}>
                {/* Toggle ON/OFF */}
                <label data-testid={`photo-req-toggle-${it.id}`}
                        style={{ display: "flex", alignItems: "center",
                                  gap: 8, cursor: "pointer" }}>
                  <input type="checkbox" checked={!!it.required}
                          onChange={(e) => setItem(it.id, { required: e.target.checked })}
                          style={{ width: 18, height: 18 }} />
                  <span style={{
                    fontSize: 11, fontWeight: 800,
                    color: it.required ? "#065f46" : "#991b1b",
                    background: it.required ? "#d1fae5" : "#fee2e2",
                    padding: "2px 8px", borderRadius: 999,
                  }}>{it.required ? "LIGADO" : "DESLIGADO"}</span>
                </label>

                {/* Icon picker */}
                <select value={it.icon || ""}
                          onChange={(e) => setItem(it.id, { icon: e.target.value })}
                          data-testid={`photo-req-icon-${it.id}`}
                          style={{ padding: "4px 6px", border: "1px solid #cbd5e1",
                                    borderRadius: 6, fontSize: 16, width: 56 }}>
                  {ICONS.map((ic) => <option key={ic} value={ic}>{ic}</option>)}
                </select>

                {/* Label */}
                <input value={it.label}
                        onChange={(e) => setItem(it.id, { label: e.target.value })}
                        data-testid={`photo-req-label-${it.id}`}
                        placeholder="Nome da foto"
                        style={{ flex: 1, minWidth: 180, padding: "6px 10px",
                                  border: "1px solid #cbd5e1", borderRadius: 6,
                                  fontSize: 13, fontWeight: 600 }} />

                {/* Move/Delete */}
                <div style={{ display: "flex", gap: 4 }}>
                  <button onClick={() => move(it.id, "up")}
                            disabled={idx === 0}
                            title="Mover para cima"
                            style={smallBtnStyle}
                            data-testid={`photo-req-up-${it.id}`}>▲</button>
                  <button onClick={() => move(it.id, "down")}
                            disabled={idx === items.length - 1}
                            title="Mover para baixo"
                            style={smallBtnStyle}
                            data-testid={`photo-req-down-${it.id}`}>▼</button>
                  <button onClick={() => removeItem(it.id)}
                            disabled={isDefault}
                            title={isDefault ? "Padrão — não pode excluir, só desligar" : "Excluir"}
                            style={{ ...smallBtnStyle,
                                      opacity: isDefault ? 0.4 : 1,
                                      color: "#dc2626", borderColor: "#fecaca" }}
                            data-testid={`photo-req-del-${it.id}`}>✕</button>
                </div>
              </div>

              {/* Instruction */}
              <input value={it.instruction || ""}
                      onChange={(e) => setItem(it.id, { instruction: e.target.value })}
                      data-testid={`photo-req-instr-${it.id}`}
                      placeholder="Instrução exibida para o técnico (ex: 'foto frontal da caixa com a porta usada visível')"
                      style={{ width: "100%", marginTop: 8, padding: "6px 10px",
                                border: "1px solid #e2e8f0", borderRadius: 6,
                                fontSize: 12, color: "#475569" }} />

              {/* iter211y — Carimbar local/data/dispositivo */}
              <label data-testid={`photo-req-stamp-${it.id}`}
                      style={{ display: "flex", alignItems: "center",
                                gap: 8, marginTop: 8, cursor: "pointer",
                                padding: "6px 8px",
                                background: it.stamp_location ? "#ecfeff" : "transparent",
                                border: `1px ${it.stamp_location ? "solid #06b6d4" : "dashed #cbd5e1"}`,
                                borderRadius: 6 }}>
                <input type="checkbox" checked={!!it.stamp_location}
                        onChange={(e) => setItem(it.id, { stamp_location: e.target.checked })}
                        style={{ width: 16, height: 16 }} />
                <span style={{ fontSize: 11, fontWeight: 700,
                                color: it.stamp_location ? "#0e7490" : "#64748b" }}>
                  Carimbar local/data/dispositivo na própria foto
                </span>
                {it.stamp_location && (
                  <span style={{ fontSize: 9, color: "#0e7490",
                                  background: "#cffafe", padding: "2px 6px",
                                  borderRadius: 999, fontWeight: 800 }}>
                    Selo no canto inferior direito
                  </span>
                )}
              </label>

              {/* Ticket types chips */}
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b",
                                textTransform: "uppercase", letterSpacing: 0.4,
                                marginBottom: 4 }}>
                  Aplicar em quais tipos de OS:
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {validTypes.map((t) => {
                    const active = (it.ticket_types || []).includes(t);
                    return (
                      <button key={t}
                              onClick={() => toggleTicketType(it.id, t)}
                              data-testid={`photo-req-${it.id}-type-${t}`}
                              style={{
                                padding: "3px 10px", borderRadius: 999,
                                border: `1px solid ${active ? "#0f766e" : "#cbd5e1"}`,
                                background: active ? "#0f766e" : "white",
                                color: active ? "white" : "#475569",
                                fontSize: 11, fontWeight: 700, cursor: "pointer",
                              }}>
                        {active ? "✓ " : ""}{TICKET_TYPE_LABELS[t] || t}
                      </button>
                    );
                  })}
                </div>
              </div>

              {isDefault && (
                <div style={{ marginTop: 6, fontSize: 10, color: "#64748b",
                                fontStyle: "italic" }}>
                  Foto padrão do sistema — não pode ser excluída, apenas desligada.
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Adicionar nova */}
      <div style={{ marginTop: 14, padding: 14,
                      background: adding ? "#ecfdf5" : "transparent",
                      border: adding ? "1.5px dashed #10b981" : "1.5px dashed #cbd5e1",
                      borderRadius: 10 }}>
        {!adding ? (
          <Button variant="secondary" onClick={() => setAdding(true)}
                   data-testid="photo-req-add-btn">
            ➕ Adicionar nova exigência de foto
          </Button>
        ) : (
          <div data-testid="photo-req-add-form" style={{ display: "grid", gap: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 800, color: "#065f46" }}>
              ➕ Nova exigência de foto
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "120px 1fr 60px",
                            gap: 8 }}>
              <input placeholder="id-interno"
                      value={newItem.id}
                      onChange={(e) => setNewItem({ ...newItem, id: e.target.value })}
                      data-testid="photo-req-new-id"
                      style={{ padding: "6px 10px", border: "1px solid #cbd5e1",
                                borderRadius: 6, fontSize: 12, fontFamily: "monospace" }} />
              <input placeholder="Nome (ex: Comprovante assinado)"
                      value={newItem.label}
                      onChange={(e) => setNewItem({ ...newItem, label: e.target.value })}
                      data-testid="photo-req-new-label"
                      style={{ padding: "6px 10px", border: "1px solid #cbd5e1",
                                borderRadius: 6, fontSize: 13, fontWeight: 600 }} />
              <select value={newItem.icon}
                        onChange={(e) => setNewItem({ ...newItem, icon: e.target.value })}
                        data-testid="photo-req-new-icon"
                        style={{ padding: "4px 6px", border: "1px solid #cbd5e1",
                                  borderRadius: 6, fontSize: 16 }}>
                {ICONS.map((ic) => <option key={ic} value={ic}>{ic}</option>)}
              </select>
            </div>
            <input placeholder="Instrução para o técnico"
                    value={newItem.instruction}
                    onChange={(e) => setNewItem({ ...newItem, instruction: e.target.value })}
                    data-testid="photo-req-new-instr"
                    style={{ padding: "6px 10px", border: "1px solid #cbd5e1",
                              borderRadius: 6, fontSize: 12 }} />
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#064e3b",
                              marginBottom: 4 }}>Aplicar em quais tipos:</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {validTypes.map((t) => {
                  const active = (newItem.ticket_types || []).includes(t);
                  return (
                    <button key={t}
                            onClick={() => setNewItem({
                              ...newItem,
                              ticket_types: active
                                ? newItem.ticket_types.filter((x) => x !== t)
                                : [...(newItem.ticket_types || []), t],
                            })}
                            data-testid={`photo-req-new-type-${t}`}
                            style={{
                              padding: "3px 10px", borderRadius: 999,
                              border: `1px solid ${active ? "#0f766e" : "#cbd5e1"}`,
                              background: active ? "#0f766e" : "white",
                              color: active ? "white" : "#475569",
                              fontSize: 11, fontWeight: 700, cursor: "pointer",
                            }}>
                      {active ? "✓ " : ""}{TICKET_TYPE_LABELS[t] || t}
                    </button>
                  );
                })}
              </div>
            </div>
            <label data-testid="photo-req-new-stamp"
                    style={{ display: "flex", alignItems: "center",
                              gap: 8, cursor: "pointer", padding: "6px 8px",
                              background: newItem.stamp_location ? "#ecfeff" : "transparent",
                              border: `1px ${newItem.stamp_location ? "solid #06b6d4" : "dashed #cbd5e1"}`,
                              borderRadius: 6 }}>
              <input type="checkbox" checked={!!newItem.stamp_location}
                      onChange={(e) => setNewItem({ ...newItem, stamp_location: e.target.checked })}
                      style={{ width: 16, height: 16 }} />
              <span style={{ fontSize: 11, fontWeight: 700,
                              color: newItem.stamp_location ? "#0e7490" : "#64748b" }}>
                Carimbar local/data/dispositivo na própria foto
              </span>
            </label>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <Button variant="secondary" onClick={() => setAdding(false)}>
                Cancelar
              </Button>
              <Button onClick={addNew} data-testid="photo-req-new-save">
                ✓ Adicionar
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Save bar */}
      <div style={{ marginTop: 14, display: "flex", gap: 10,
                      alignItems: "center", flexWrap: "wrap" }}>
        <Button onClick={save} disabled={saving} data-testid="photo-req-save">
          {saving ? "Salvando…" : "Salvar cardápio"}
        </Button>
        <Button variant="secondary" onClick={reload} disabled={saving}>
          Descartar mudanças
        </Button>
        {msg && (
          <span style={{ fontWeight: 700,
                          color: msg.startsWith("✅") ? "#166534" : "#be123c" }}>
            {msg}
          </span>
        )}
      </div>
    </Card>
  );
}

const smallBtnStyle = {
  width: 30, height: 30, border: "1px solid #cbd5e1",
  background: "white", borderRadius: 6, fontSize: 13,
  cursor: "pointer", color: "#475569",
};
