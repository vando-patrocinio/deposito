import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, Icon, inputStyle, Row } from "@/ui";

const BR_STATES_BY_NAME = {
  "Acre": "AC", "Alagoas": "AL", "Amapá": "AP", "Amapa": "AP", "Amazonas": "AM",
  "Bahia": "BA", "Ceará": "CE", "Ceara": "CE", "Distrito Federal": "DF",
  "Espírito Santo": "ES", "Espirito Santo": "ES", "Goiás": "GO", "Goias": "GO",
  "Maranhão": "MA", "Maranhao": "MA", "Mato Grosso": "MT", "Mato Grosso do Sul": "MS",
  "Minas Gerais": "MG", "Pará": "PA", "Para": "PA", "Paraíba": "PB", "Paraiba": "PB",
  "Paraná": "PR", "Parana": "PR", "Pernambuco": "PE", "Piauí": "PI", "Piaui": "PI",
  "Rio de Janeiro": "RJ", "Rio Grande do Norte": "RN", "Rio Grande do Sul": "RS",
  "Rondônia": "RO", "Rondonia": "RO", "Roraima": "RR", "Santa Catarina": "SC",
  "São Paulo": "SP", "Sao Paulo": "SP", "Sergipe": "SE", "Tocantins": "TO",
};

const EMPTY = {
  name: "", city: "", state: "",
  full_address: "", street: "", number: "", neighborhood: "", postal_code: "",
  lat: null, lng: null,
  holidays_extra: [],
  logo_url: "", cnpj: "", inscricao_estadual: "",
  phone: "", email: "", site: "",
};
const SCOPES = [
  { value: "municipal", label: "Municipal" },
  { value: "estadual", label: "Estadual" },
  { value: "facultativo", label: "Facultativo" },
];

function AddressAutocomplete({ value, onChange, onSelect }) {
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const timer = useRef(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!value || value.trim().length < 4) { setResults([]); return; }
    timer.current = setTimeout(async () => {
      try {
        const r = await api.geocodeSearch(value, 5);
        setResults(r || []); setOpen(true);
      } catch { setResults([]); }
    }, 400);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [value]);

  return (
    <div style={{ position: "relative" }}>
      <input
        data-testid="p-address"
        style={inputStyle}
        value={value || ""}
        placeholder="Comece a digitar (ex.: Rua Brasil, 123, Cachoeiras de Macacu)"
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
      />
      {open && results.length > 0 && (
        <div style={{ position: "absolute", zIndex: 20, top: "100%", left: 0, right: 0, background: "white", border: "1px solid #cbd5e1", borderRadius: 12, marginTop: 4, maxHeight: 240, overflowY: "auto", boxShadow: "0 8px 24px rgba(15,23,42,.16)" }}>
          {results.map((r, i) => (
            <button
              key={i}
              type="button"
              onClick={() => { onSelect && onSelect(r); setOpen(false); }}
              data-testid={`addr-result-${i}`}
              style={{ display: "block", width: "100%", textAlign: "left", padding: "10px 12px", background: "white", border: "none", borderBottom: "1px solid #f1f5f9", cursor: "pointer", fontSize: 13 }}
            >
              <strong>{r.display_name?.split(",")[0]}</strong>
              <div style={{ color: "#64748b", fontSize: 11 }}>{r.display_name}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AiHolidaysModal({ open, praca, onClose, onApplied }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [selected, setSelected] = useState({});
  const [err, setErr] = useState("");
  const [appliedMsg, setAppliedMsg] = useState("");

  useEffect(() => { if (!open) { setSuggestions([]); setSelected({}); setErr(""); setAppliedMsg(""); } }, [open]);

  if (!open || !praca) return null;

  async function discover() {
    setLoading(true); setErr(""); setAppliedMsg("");
    try {
      const r = await api.discoverHolidays(praca.id, year);
      setSuggestions(r.suggestions || []);
      // marca tudo selecionado por padrão
      const sel = {};
      (r.suggestions || []).forEach((s, i) => { sel[i] = true; });
      setSelected(sel);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }

  async function apply() {
    const toApply = suggestions.filter((_, i) => selected[i]);
    if (toApply.length === 0) { setErr("Selecione pelo menos um feriado para aplicar."); return; }
    try {
      const r = await api.applyHolidays(praca.id, toApply);
      setAppliedMsg(`✅ ${r.added} feriado(s) novo(s) aplicado(s) (total: ${r.total}).`);
      onApplied && onApplied(r.holidays_extra);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }

  return (
    <div role="dialog" data-testid="ai-holidays-modal" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }} style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.55)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div style={{ background: "white", borderRadius: 22, width: "100%", maxWidth: 600, maxHeight: "90vh", display: "flex", flexDirection: "column", boxShadow: "0 24px 60px rgba(15,23,42,.32)" }}>
        <div style={{ padding: "18px 22px 8px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>Buscar feriados com IA</h3>
          <button onClick={onClose} data-testid="ai-close" style={{ background: "transparent", border: "none", fontSize: 22, cursor: "pointer", color: "#64748b" }}>×</button>
        </div>
        <div style={{ overflowY: "auto", padding: "0 22px 22px" }}>
          <p style={{ color: "#64748b", margin: "0 0 12px", fontSize: 13 }}>
            A IA vai sugerir feriados <strong>estaduais</strong> e <strong>municipais</strong> de
            <strong> {praca.city} - {praca.state}</strong> (não inclui nacionais — esses já vêm da BrasilAPI).
          </p>

          <div style={{ display: "flex", gap: 8, alignItems: "end", marginBottom: 12 }}>
            <Field label="Ano">
              <input data-testid="ai-year" type="number" min="2000" max="2100" style={{ ...inputStyle, width: 140 }} value={year} onChange={(e) => setYear(Number(e.target.value))} />
            </Field>
            <Button onClick={discover} disabled={loading} data-testid="ai-discover-btn">
              {loading ? "Consultando IA..." : <><Icon name="sync" /> Buscar com IA</>}
            </Button>
          </div>

          {err && <div data-testid="ai-error" style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10, fontSize: 13 }}>{err}</div>}
          {appliedMsg && <div data-testid="ai-success" style={{ background: "#dcfce7", color: "#166534", padding: 10, borderRadius: 12, marginBottom: 10, fontSize: 13 }}>{appliedMsg}</div>}

          {suggestions.length > 0 && (
            <>
              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: 8, marginBottom: 10 }} data-testid="ai-suggestions">
                {suggestions.map((s, i) => (
                  <label key={i} data-testid={`ai-sug-${i}`} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 6px", borderBottom: i < suggestions.length - 1 ? "1px solid #f1f5f9" : "none", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={!!selected[i]}
                      onChange={(e) => setSelected({ ...selected, [i]: e.target.checked })}
                      data-testid={`ai-sug-chk-${i}`}
                    />
                    <strong style={{ minWidth: 96, fontSize: 13 }}>{s.date}</strong>
                    <span style={{ flex: 1, fontSize: 13 }}>{s.name}</span>
                    <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: s.scope === "estadual" ? "#dbeafe" : s.scope === "facultativo" ? "#e2e8f0" : "#fde68a", color: s.scope === "estadual" ? "#1e3a8a" : s.scope === "facultativo" ? "#475569" : "#92400e" }}>
                      {s.scope}
                    </span>
                  </label>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                <Button variant="secondary" onClick={onClose} data-testid="ai-cancel">Cancelar</Button>
                <Button onClick={apply} data-testid="ai-apply-btn">Aplicar selecionados</Button>
              </div>
            </>
          )}

          {!loading && suggestions.length === 0 && !err && (
            <p style={{ color: "#94a3b8", fontSize: 12, fontStyle: "italic" }}>
              Clique em "Buscar com IA" para listar sugestões. Você poderá revisar antes de aplicar.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function PracasPanel() {
  const [list, setList] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(null); // null | "new" | id
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [aiPraca, setAiPraca] = useState(null);

  // form para nova entrada de feriado
  const [hDate, setHDate] = useState("");
  const [hName, setHName] = useState("");
  const [hScope, setHScope] = useState("municipal");

  async function reload() {
    try { setList(await api.listPracas()); }
    catch (e) { setError(e?.response?.data?.detail || e.message); }
  }
  useEffect(() => { reload(); }, []);

  function startNew() { setForm(EMPTY); setEditing("new"); setError(""); }
  function startEdit(p) {
    setForm({
      name: p.name, city: p.city, state: p.state,
      full_address: p.full_address || "", street: p.street || "", number: p.number || "",
      neighborhood: p.neighborhood || "", postal_code: p.postal_code || "",
      lat: p.lat ?? null, lng: p.lng ?? null,
      holidays_extra: [...(p.holidays_extra || [])],
    });
    setEditing(p.id); setError("");
  }

  function selectAddress(r) {
    const parts = (r.display_name || "").split(",").map((s) => s.trim());
    let city = form.city, state = form.state;
    // 1) Tenta pegar sigla UF direta
    const ufMatch = parts.find((p) => /^[A-Z]{2}$/.test(p));
    if (ufMatch) state = ufMatch;
    // 2) Fallback: nome do estado por extenso (Photon)
    if (!ufMatch) {
      for (const p of parts) {
        if (BR_STATES_BY_NAME[p]) { state = BR_STATES_BY_NAME[p]; break; }
      }
    }
    const cityCandidate = parts.find((p) => !/^\d/.test(p) && p.length > 2 && p !== ufMatch && p !== "Brasil" && !BR_STATES_BY_NAME[p]);
    if (cityCandidate && !form.city) city = cityCandidate;
    setForm({
      ...form,
      full_address: r.display_name,
      lat: r.lat, lng: r.lng,
      city, state: (state || "").toUpperCase().slice(0, 2),
    });
  }

  function addHoliday() {
    if (!hDate || !hName.trim()) { setError("Preencha data e nome do feriado."); return; }
    setForm({ ...form, holidays_extra: [...form.holidays_extra, { date: hDate, name: hName.trim(), scope: hScope, source: "manual" }] });
    setHDate(""); setHName(""); setHScope("municipal"); setError("");
  }
  function removeHoliday(i) {
    const arr = [...form.holidays_extra]; arr.splice(i, 1);
    setForm({ ...form, holidays_extra: arr });
  }

  async function save() {
    setError("");
    if (!form.name.trim() || !form.city.trim() || !form.state.trim()) {
      setError("Nome, cidade e UF são obrigatórios.");
      return;
    }
    try {
      const payload = {
        ...form,
        name: form.name.trim(), city: form.city.trim(),
        state: form.state.trim().toUpperCase().slice(0, 2),
      };
      if (editing === "new") await api.createPraca(payload);
      else await api.updatePraca(editing, payload);
      await reload();
      setEditing(null);
      setFlash("✅ Praça salva.");
      setTimeout(() => setFlash(""), 3000);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  }

  async function remove(id) {
    try {
      await api.deletePraca(id);
      await reload();
      setConfirmDelete(null);
      setFlash("✅ Praça removida.");
      setTimeout(() => setFlash(""), 3000);
    } catch (e) {
      setFlash("❌ " + (e?.response?.data?.detail || e.message));
      setTimeout(() => setFlash(""), 5000);
    }
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
      <Card title="Praças cadastradas" action={<Button onClick={startNew} data-testid="new-praca-btn"><Icon name="plus" /> Nova praça</Button>}>
        {flash && <div data-testid="praca-flash" style={{ background: flash.startsWith("✅") ? "#dcfce7" : "#fee2e2", color: flash.startsWith("✅") ? "#166534" : "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10, fontWeight: 700 }}>{flash}</div>}
        {list.length === 0 && (
          <div style={{ background: "#fffbeb", border: "1px dashed #fde68a", borderRadius: 14, padding: 22, textAlign: "center", color: "#92400e" }}>
            Nenhuma praça cadastrada. Clique em <strong>Nova praça</strong> para começar.
          </div>
        )}
        {list.map((p) => (
          <div key={p.id} data-testid={`praca-card-${p.id}`} style={{ background: "white", border: "1px solid #e2e8f0", borderRadius: 14, padding: 12, marginBottom: 8 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "flex-start", flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong>{p.name}</strong>
                <div style={{ color: "#64748b", fontSize: 12 }}>{p.city} · {p.state}</div>
                {p.full_address && <div style={{ color: "#94a3b8", fontSize: 11, marginTop: 2 }}>{p.full_address}</div>}
                <div style={{ color: "#94a3b8", fontSize: 11, marginTop: 4 }}>{(p.holidays_extra || []).length} feriado(s) cadastrado(s)</div>
              </div>
            </div>
            <div style={{ marginTop: 10, paddingTop: 8, borderTop: "1px solid #f1f5f9", display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
              {confirmDelete === p.id ? (
                <>
                  <span style={{ alignSelf: "center", marginRight: "auto", fontSize: 12, color: "#be123c", fontWeight: 700 }}>Excluir?</span>
                  <Button variant="secondary" onClick={() => setConfirmDelete(null)}>Cancelar</Button>
                  <Button variant="danger" onClick={() => remove(p.id)} data-testid={`confirm-del-praca-${p.id}`}>Sim</Button>
                </>
              ) : (
                <>
                  <Button variant="soft" onClick={() => setAiPraca(p)} data-testid={`ai-praca-${p.id}`} title="Buscar feriados com IA">
                    <Icon name="sync" /> Feriados IA
                  </Button>
                  <Button variant="secondary" onClick={() => startEdit(p)} data-testid={`edit-praca-${p.id}`}><Icon name="gear" /> Editar</Button>
                  <Button variant="danger" onClick={() => setConfirmDelete(p.id)} data-testid={`del-praca-${p.id}`}><Icon name="trash" /></Button>
                </>
              )}
            </div>
          </div>
        ))}
      </Card>

      {editing !== null ? (
        <Card title={editing === "new" ? "Nova praça" : "Editar praça"}>
          {error && <div data-testid="praca-form-error" style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10 }}>{error}</div>}

          <Field label="Nome / apelido da operação">
            <input data-testid="p-name" style={inputStyle} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Ex.: Operação Cachoeiras" />
          </Field>

          <Field label="Endereço completo (busca via mapa)">
            <AddressAutocomplete
              value={form.full_address}
              onChange={(v) => setForm({ ...form, full_address: v })}
              onSelect={selectAddress}
            />
          </Field>

          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 10 }}>
            <Field label="Cidade">
              <input data-testid="p-city" style={inputStyle} value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} placeholder="Cachoeiras de Macacu" />
            </Field>
            <Field label="UF">
              <input data-testid="p-state" maxLength={2} style={inputStyle} value={form.state} onChange={(e) => setForm({ ...form, state: e.target.value.toUpperCase() })} placeholder="RJ" />
            </Field>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 10 }}>
            <Field label="Bairro">
              <input data-testid="p-neighborhood" style={inputStyle} value={form.neighborhood || ""} onChange={(e) => setForm({ ...form, neighborhood: e.target.value })} />
            </Field>
            <Field label="CEP">
              <input data-testid="p-cep" style={inputStyle} value={form.postal_code || ""} onChange={(e) => setForm({ ...form, postal_code: e.target.value })} placeholder="00000-000" />
            </Field>
          </div>

          {/* ===== Identificação fiscal & branding da praça =====
              Esses dados aparecem no cabeçalho do espelho de ponto (Control iD).
              Quando preenchidos, sobrescrevem os dados da matriz para os
              colaboradores lotados nesta praça. */}
          <div style={{
            background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12,
            padding: 14, marginTop: 16, marginBottom: 8,
          }}>
            <h4 style={{ margin: "0 0 4px", fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
              Identificação fiscal & branding
            </h4>
            <p style={{ margin: "0 0 12px", fontSize: 12, color: "#64748b" }}>
              Aparece no <strong>cabeçalho do espelho de ponto</strong> e do romaneio. Se em branco,
              usa os dados da matriz.
            </p>

            <Field label="Logo da praça">
              <div style={{
                display: "flex", alignItems: "center", gap: 14,
                padding: 10, background: "white",
                border: "1.5px dashed #cbd5e1", borderRadius: 12,
              }}>
                {form.logo_url ? (
                  <img
                    src={form.logo_url} alt="logo praça"
                    style={{
                      width: 64, height: 64, borderRadius: 10, objectFit: "contain",
                      border: "1px solid #e2e8f0", background: "white", padding: 4,
                      flexShrink: 0,
                    }}
                  />
                ) : (
                  <div style={{
                    width: 64, height: 64, borderRadius: 10,
                    background: "#f1f5f9", display: "grid", placeItems: "center",
                    color: "#94a3b8", fontSize: 11, fontWeight: 700, flexShrink: 0,
                  }}>LOGO</div>
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/svg+xml,image/webp"
                    data-testid="p-logo-file"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      const MAX = 1.5 * 1024 * 1024;
                      if (file.size > MAX) {
                        alert(`Imagem maior que 1.5 MB (atual: ${(file.size / 1024 / 1024).toFixed(2)} MB).`);
                        e.target.value = "";
                        return;
                      }
                      const reader = new FileReader();
                      reader.onload = () => {
                        setForm((f) => ({ ...f, logo_url: reader.result }));
                      };
                      reader.readAsDataURL(file);
                    }}
                    style={{ fontSize: 12, color: "#475569" }}
                  />
                  {form.logo_url && (
                    <button
                      type="button"
                      data-testid="p-logo-remove"
                      onClick={() => setForm({ ...form, logo_url: "" })}
                      style={{
                        marginTop: 6, marginLeft: 0,
                        border: "1px solid #fecaca", color: "#dc2626", background: "white",
                        borderRadius: 8, padding: "3px 10px", fontSize: 11, fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >× Remover logo</button>
                  )}
                  <div style={{ fontSize: 10.5, color: "#94a3b8", marginTop: 4 }}>
                    PNG/JPG/SVG · max 1.5 MB · ideal 400×400 px
                  </div>
                </div>
              </div>
            </Field>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <Field label="CNPJ">
                <input data-testid="p-cnpj" style={inputStyle} value={form.cnpj || ""}
                       onChange={(e) => setForm({ ...form, cnpj: e.target.value })}
                       placeholder="00.000.000/0000-00" />
              </Field>
              <Field label="Inscrição Estadual">
                <input data-testid="p-ie" style={inputStyle} value={form.inscricao_estadual || ""}
                       onChange={(e) => setForm({ ...form, inscricao_estadual: e.target.value })}
                       placeholder="000000000" />
              </Field>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
              <Field label="Telefone">
                <input data-testid="p-phone" style={inputStyle} value={form.phone || ""}
                       onChange={(e) => setForm({ ...form, phone: e.target.value })}
                       placeholder="(21) 4042-9393" />
              </Field>
              <Field label="E-mail">
                <input data-testid="p-email" type="email" style={inputStyle} value={form.email || ""}
                       onChange={(e) => setForm({ ...form, email: e.target.value })}
                       placeholder="contato@praca.com" />
              </Field>
              <Field label="Site">
                <input data-testid="p-site" style={inputStyle} value={form.site || ""}
                       onChange={(e) => setForm({ ...form, site: e.target.value })}
                       placeholder="www.empresa.com.br" />
              </Field>
            </div>
          </div>

          <h4 style={{ margin: "18px 0 8px", display: "flex", alignItems: "center", gap: 10 }}>
            Feriados específicos da praça
            {editing !== "new" && (
              <Button variant="soft" onClick={() => setAiPraca({ ...form, id: editing })} data-testid="ai-from-form-btn" style={{ marginLeft: "auto", fontSize: 12 }}>
                <Icon name="sync" /> Buscar com IA
              </Button>
            )}
          </h4>
          <p style={{ color: "#64748b", fontSize: 12, marginTop: 0 }}>
            Adicione manualmente ou use a IA para sugerir os feriados <strong>municipais</strong> e <strong>estaduais</strong> daqui.
          </p>

          <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: 10, marginBottom: 10 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr 1fr auto", gap: 6, alignItems: "center" }}>
              <input data-testid="ph-date" type="date" style={{ ...inputStyle, padding: 8 }} value={hDate} onChange={(e) => setHDate(e.target.value)} />
              <input data-testid="ph-name" style={{ ...inputStyle, padding: 8 }} placeholder="Nome do feriado" value={hName} onChange={(e) => setHName(e.target.value)} />
              <select data-testid="ph-scope" style={{ ...inputStyle, padding: 8 }} value={hScope} onChange={(e) => setHScope(e.target.value)}>
                {SCOPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
              <Button variant="soft" onClick={addHoliday} data-testid="add-holiday-btn"><Icon name="plus" /></Button>
            </div>
          </div>

          {form.holidays_extra.length === 0 ? (
            <p style={{ color: "#94a3b8", fontSize: 12, fontStyle: "italic" }}>Nenhum feriado adicionado.</p>
          ) : (
            <div style={{ marginBottom: 10 }}>
              {form.holidays_extra.map((h, i) => (
                <div key={i} data-testid={`praca-holiday-${i}`} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderBottom: "1px solid #f1f5f9", fontSize: 13 }}>
                  <strong style={{ minWidth: 96 }}>{h.date}</strong>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    {h.name}
                    {h.source === "ai" && <span style={{ marginLeft: 6, fontSize: 10, fontWeight: 800, padding: "1px 6px", borderRadius: 999, background: "#ccfbf1", color: "#0f766e" }}>IA</span>}
                  </span>
                  <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: h.scope === "estadual" ? "#dbeafe" : h.scope === "facultativo" ? "#e2e8f0" : "#fde68a", color: h.scope === "estadual" ? "#1e3a8a" : h.scope === "facultativo" ? "#475569" : "#92400e" }}>
                    {h.scope}
                  </span>
                  <button onClick={() => removeHoliday(i)} data-testid={`rm-holiday-${i}`} style={{ background: "transparent", border: "none", color: "#dc2626", cursor: "pointer", fontSize: 16, padding: 4 }}>×</button>
                </div>
              ))}
            </div>
          )}

          <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
            <Button onClick={save} data-testid="save-praca-btn">Salvar praça</Button>
            <Button variant="secondary" onClick={() => setEditing(null)}>Cancelar</Button>
          </div>
        </Card>
      ) : (
        <Card title="Como funciona">
          <Row label="Endereço" value="Use o autocompletar para buscar o endereço completo da operação." />
          <Row label="Feriados nacionais" value="Buscados da BrasilAPI automaticamente — você não precisa cadastrar." />
          <Row label="Feriados estaduais/municipais" value="Use o botão 'Feriados IA' para que o sistema sugira os feriados — você revisa e aplica." />
          <Row label="Como aparece no espelho" value="Toda batida no dia de feriado vira HE 100% (CLT)." />
          <p style={{ color: "#64748b", fontSize: 12, marginTop: 14 }}>
            🤖 A IA pode falhar ocasionalmente — sempre revise as sugestões antes de aplicar. Você ainda pode adicionar feriados manualmente.
          </p>
        </Card>
      )}

      <AiHolidaysModal
        open={!!aiPraca}
        praca={aiPraca}
        onClose={() => setAiPraca(null)}
        onApplied={async (merged) => {
          // Atualiza form se estiver editando a mesma praça
          if (editing && aiPraca && editing === aiPraca.id) {
            setForm((f) => ({ ...f, holidays_extra: merged }));
          }
          await reload();
        }}
      />
    </div>
  );
}
