import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Switch } from "@/components/ui/switch";
import {
  Plus, Trash2, Loader2, CheckCircle2, AlertCircle, Save, Wallet,
} from "lucide-react";

/**
 * Tabela de Preços oficial — gerencia o catálogo `pricing_catalog`.
 * Tudo que estiver habilitado aqui vira o bloco `=== PREÇOS E VALORES ===`
 * injetado nos prompts da Isabella / Pâmela / Álvaro em runtime.
 */
const CATEGORIES = [
  { value: "plano_fibra", label: "Plano Fibra" },
  { value: "combo", label: "Combo" },
  { value: "adicional", label: "Adicional" },
  { value: "servico", label: "Serviço" },
  { value: "taxa", label: "Taxa" },
];
const CYCLES = [
  { value: "mensal", label: "Mensal" },
  { value: "unico", label: "Cobrança única" },
];
const FIDELITY = [
  { value: "na", label: "N/A" },
  { value: "com", label: "Com fidelidade" },
  { value: "sem", label: "Sem fidelidade" },
];

const inputStyle = {
  width: "100%", padding: "7px 9px", borderRadius: 7, fontSize: 12,
  border: "1px solid var(--border-color, #334155)",
  background: "var(--bg-input, transparent)", color: "var(--text-primary)",
};

export function PricingCatalogPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.pricingItemsList();
      setItems(r.items || []);
    } catch (e) {
      setMsg({ type: "err", text: "Falha ao carregar tabela de preços." });
    }
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const createItem = async (data) => {
    try {
      const created = await api.pricingItemCreate(data);
      setItems((p) => [...p, created]);
      setCreating(false);
      setMsg({ type: "ok", text: `"${created.name}" adicionado à tabela.` });
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || "Falha ao criar item." });
    }
  };
  const patchItem = async (id, data) => {
    try {
      const updated = await api.pricingItemPatch(id, data);
      setItems((p) => p.map((x) => (x.id === id ? updated : x)));
      setMsg({ type: "ok", text: "Item atualizado." });
    } catch (e) {
      setMsg({ type: "err", text: "Falha ao atualizar item." });
    }
  };
  const deleteItem = async (id) => {
    if (!window.confirm("Remover este item da tabela de preços?")) return;
    try {
      await api.pricingItemDelete(id);
      setItems((p) => p.filter((x) => x.id !== id));
      setMsg({ type: "ok", text: "Item removido." });
    } catch (e) {
      setMsg({ type: "err", text: "Falha ao remover item." });
    }
  };

  return (
    <div data-testid="pricing-catalog-panel" style={{ paddingTop: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <Wallet size={15} color="#10b981" />
        <div style={{ fontSize: 12, color: "var(--text-muted)", flex: 1 }}>
          Valores oficiais lançados aqui são a ÚNICA fonte de preço que a IA
          (Isabella, Pâmela, Álvaro) pode citar ao cliente.
        </div>
        <button
          data-testid="pricing-add-item-btn"
          onClick={() => setCreating((v) => !v)}
          style={{
            display: "flex", alignItems: "center", gap: 6, padding: "7px 12px",
            borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12,
            fontWeight: 600, background: "#10b981", color: "white",
          }}>
          <Plus size={14} /> Novo item
        </button>
      </div>

      {msg && (
        <div data-testid="pricing-msg" style={{
          display: "flex", alignItems: "center", gap: 6, fontSize: 12,
          padding: "7px 10px", borderRadius: 8, marginBottom: 8,
          background: msg.type === "ok" ? "rgba(16,185,129,.12)" : "rgba(239,68,68,.12)",
          color: msg.type === "ok" ? "#10b981" : "#ef4444",
        }}>
          {msg.type === "ok" ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
          {msg.text}
        </div>
      )}

      {creating && (
        <PricingItemForm onSave={createItem} onCancel={() => setCreating(false)} />
      )}

      {loading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 30 }}>
          <Loader2 size={20} className="animate-spin" color="var(--text-muted)" />
        </div>
      ) : items.length === 0 && !creating ? (
        <div data-testid="pricing-empty-state" style={{
          textAlign: "center", padding: 26, fontSize: 12.5,
          color: "var(--text-muted)", border: "1px dashed var(--border-color,#334155)",
          borderRadius: 10,
        }}>
          Nenhum valor lançado ainda. Enquanto a tabela estiver vazia, a IA
          usa o campo legado "Preços" do agente (se preenchido).
        </div>
      ) : (
        CATEGORIES.map((cat) => {
          const rows = items.filter((x) => x.category === cat.value);
          if (!rows.length) return null;
          return (
            <div key={cat.value} style={{ marginBottom: 14 }}>
              <div style={{
                fontSize: 11, fontWeight: 700, textTransform: "uppercase",
                letterSpacing: 0.6, color: "var(--text-muted)", margin: "8px 0 6px",
              }}>
                {cat.label} ({rows.length})
              </div>
              {rows.map((it) => (
                <PricingItemRow key={it.id} item={it}
                  onPatch={patchItem} onDelete={deleteItem} />
              ))}
            </div>
          );
        })
      )}
    </div>
  );
}

function PricingItemRow({ item, onPatch, onDelete }) {
  const [price, setPrice] = useState(String(item.price_brl ?? ""));
  const dirty = parseFloat(price) !== item.price_brl;
  return (
    <div data-testid={`pricing-item-${item.id}`} style={{
      display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
      borderRadius: 9, marginBottom: 5,
      border: "1px solid var(--border-color,#334155)",
      opacity: item.enabled ? 1 : 0.5,
    }}>
      <Switch checked={item.enabled}
        data-testid={`pricing-item-toggle-${item.id}`}
        onCheckedChange={(v) => onPatch(item.id, { enabled: v })} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>
          {item.name}
          {item.fidelity !== "na" && (
            <span style={{ fontSize: 10.5, fontWeight: 500, marginLeft: 6, color: "var(--text-muted)" }}>
              {item.fidelity === "com" ? "com fidelidade" : "sem fidelidade"}
            </span>
          )}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {item.billing_cycle === "mensal" ? "mensal" : "cobrança única"}
          {item.description ? ` · ${item.description}` : ""}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>R$</span>
        <input
          data-testid={`pricing-item-price-${item.id}`}
          value={price} type="number" min="0" step="0.01"
          onChange={(e) => setPrice(e.target.value)}
          style={{ ...inputStyle, width: 92, textAlign: "right" }} />
        {dirty && (
          <button
            data-testid={`pricing-item-save-${item.id}`}
            onClick={() => onPatch(item.id, { price_brl: parseFloat(price) || 0 })}
            title="Salvar preço"
            style={{
              border: "none", background: "#10b981", color: "white",
              borderRadius: 7, padding: 6, cursor: "pointer", display: "flex",
            }}>
            <Save size={13} />
          </button>
        )}
      </div>
      <button
        data-testid={`pricing-item-delete-${item.id}`}
        onClick={() => onDelete(item.id)} title="Remover"
        style={{
          border: "none", background: "transparent", color: "#ef4444",
          cursor: "pointer", display: "flex", padding: 4,
        }}>
        <Trash2 size={14} />
      </button>
    </div>
  );
}

function PricingItemForm({ onSave, onCancel }) {
  const [category, setCategory] = useState("plano_fibra");
  const [name, setName] = useState("");
  const [priceBrl, setPriceBrl] = useState("");
  const [cycle, setCycle] = useState("mensal");
  const [fidelity, setFidelity] = useState("na");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!name.trim() || priceBrl === "") return;
    setSaving(true);
    await onSave({
      category, name: name.trim(), price_brl: parseFloat(priceBrl) || 0,
      billing_cycle: cycle, fidelity,
      description: description.trim() || null, enabled: true,
    });
    setSaving(false);
  };

  return (
    <div data-testid="pricing-item-form" style={{
      border: "1px solid #10b98155", borderRadius: 10, padding: 12,
      marginBottom: 12, display: "grid", gap: 8,
      gridTemplateColumns: "1.2fr 2fr 1fr 1.2fr 1.2fr",
    }}>
      <select data-testid="pricing-form-category" value={category}
        onChange={(e) => setCategory(e.target.value)} style={inputStyle}>
        {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
      </select>
      <input data-testid="pricing-form-name" placeholder="Nome (ex: 500 Mega)"
        value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} />
      <input data-testid="pricing-form-price" placeholder="Preço R$" type="number"
        min="0" step="0.01" value={priceBrl}
        onChange={(e) => setPriceBrl(e.target.value)} style={inputStyle} />
      <select data-testid="pricing-form-cycle" value={cycle}
        onChange={(e) => setCycle(e.target.value)} style={inputStyle}>
        {CYCLES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
      </select>
      <select data-testid="pricing-form-fidelity" value={fidelity}
        onChange={(e) => setFidelity(e.target.value)} style={inputStyle}>
        {FIDELITY.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
      </select>
      <input data-testid="pricing-form-description" placeholder="Condição/observação (opcional)"
        value={description} onChange={(e) => setDescription(e.target.value)}
        style={{ ...inputStyle, gridColumn: "1 / span 3" }} />
      <div style={{ gridColumn: "4 / span 2", display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button data-testid="pricing-form-cancel" onClick={onCancel} disabled={saving}
          style={{
            padding: "7px 12px", borderRadius: 8, fontSize: 12, cursor: "pointer",
            border: "1px solid var(--border-color,#334155)", background: "transparent",
            color: "var(--text-muted)",
          }}>
          Cancelar
        </button>
        <button data-testid="pricing-form-save" onClick={submit}
          disabled={saving || !name.trim() || priceBrl === ""}
          style={{
            padding: "7px 14px", borderRadius: 8, fontSize: 12, fontWeight: 600,
            border: "none", cursor: "pointer", background: "#10b981", color: "white",
            display: "flex", alignItems: "center", gap: 6,
            opacity: saving || !name.trim() || priceBrl === "" ? 0.6 : 1,
          }}>
          {saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          Lançar valor
        </button>
      </div>
    </div>
  );
}
