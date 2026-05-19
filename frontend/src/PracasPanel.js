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
  logo_url: "", cnpj: "", inscricao_estadual: "",
  phone: "", email: "", site: "",
  branch_codes: [],
};

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


export default function PracasPanel() {
  const [list, setList] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(null); // null | "new" | id
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(null);

  const [filiaisAtlaz, setFiliaisAtlaz] = useState([]);

  async function reload() {
    try { setList(await api.listPracas()); }
    catch (e) { setError(e?.response?.data?.detail || e.message); }
  }
  useEffect(() => { reload(); }, []);
  useEffect(() => {
    // Carrega filiais Atlaz uma vez para popular o multi-select
    api.atlazGetSettings()
      .then((c) => setFiliaisAtlaz(Array.isArray(c?.filiais) ? c.filiais : []))
      .catch(() => setFiliaisAtlaz([]));
  }, []);

  function startNew() { setForm(EMPTY); setEditing("new"); setError(""); }
  function startEdit(p) {
    setForm({
      name: p.name, city: p.city, state: p.state,
      full_address: p.full_address || "", street: p.street || "", number: p.number || "",
      neighborhood: p.neighborhood || "", postal_code: p.postal_code || "",
      lat: p.lat ?? null, lng: p.lng ?? null,
      logo_url: p.logo_url || "", cnpj: p.cnpj || "", inscricao_estadual: p.inscricao_estadual || "",
      phone: p.phone || "", email: p.email || "", site: p.site || "",
      branch_codes: Array.isArray(p.branch_codes) ? [...p.branch_codes] : [],
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
                {(p.branch_codes || []).length > 0 && (
                  <div data-testid={`praca-branches-${p.id}`} style={{
                    display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8,
                  }}>
                    {(p.branch_codes || []).map((b) => (
                      <span key={b} style={{
                        display: "inline-flex", alignItems: "center", gap: 3,
                        padding: "2px 7px", borderRadius: 999,
                        background: "#dbeafe", border: "1px solid #93c5fd",
                        color: "#1e40af", fontSize: 10.5, fontWeight: 700,
                      }}>🏢 {b}</span>
                    ))}
                  </div>
                )}
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
                        await window.alert(`Imagem maior que 1.5 MB (atual: ${(file.size / 1024 / 1024).toFixed(2)} MB).`);
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

            {/* Filiais Atlaz vinculadas — uma praça pode operar com várias filiais */}
            <div style={{ marginTop: 4 }}>
              <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: "#475569",
                              textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 6 }}>
                Filiais (Atlaz) que operam nesta praça
              </label>
              {filiaisAtlaz.length === 0 ? (
                <p style={{ fontSize: 12, color: "#94a3b8", margin: 0 }}>
                  Nenhuma filial cadastrada no Atlaz. Cadastre primeiro em
                  <strong> Sistema → Configurações → Atlaz → Mapeamento Filial</strong>.
                </p>
              ) : (
                <>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                    {(form.branch_codes || []).map((b) => (
                      <span key={b} data-testid={`p-branch-tag-${b}`} style={{
                        display: "inline-flex", alignItems: "center", gap: 6,
                        padding: "4px 10px", borderRadius: 999,
                        background: "#dbeafe", border: "1px solid #93c5fd",
                        color: "#1e40af", fontSize: 12, fontWeight: 600,
                      }}>
                        🏢 {b}
                        <button
                          type="button"
                          onClick={() => setForm({
                            ...form,
                            branch_codes: (form.branch_codes || []).filter((x) => x !== b),
                          })}
                          style={{
                            border: "none", background: "transparent", color: "#1e40af",
                            cursor: "pointer", fontSize: 14, padding: 0, lineHeight: 1,
                          }}
                        >×</button>
                      </span>
                    ))}
                    {(form.branch_codes || []).length === 0 && (
                      <span style={{ fontSize: 12, color: "#94a3b8" }}>Nenhuma filial selecionada.</span>
                    )}
                  </div>
                  <select
                    data-testid="p-branch-add"
                    value=""
                    onChange={(e) => {
                      const val = e.target.value;
                      if (!val) return;
                      if ((form.branch_codes || []).includes(val)) return;
                      setForm({ ...form, branch_codes: [...(form.branch_codes || []), val] });
                      e.target.value = "";
                    }}
                    style={{ ...inputStyle, maxWidth: 320 }}
                  >
                    <option value="">+ Adicionar filial...</option>
                    {filiaisAtlaz.filter((f) => !(form.branch_codes || []).includes(f)).map((f) => (
                      <option key={f} value={f}>{f}</option>
                    ))}
                  </select>
                  <p style={{ marginTop: 4, fontSize: 11, color: "#94a3b8" }}>
                    Quando um chamado Atlaz vier de uma dessas filiais, ele será roteado para esta praça.
                  </p>
                </>
              )}
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
            <Button onClick={save} data-testid="save-praca-btn">Salvar praça</Button>
            <Button variant="secondary" onClick={() => setEditing(null)}>Cancelar</Button>
          </div>
        </Card>
      ) : (
        <Card title="Como funciona">
          <Row label="Endereço" value="Use o autocompletar para buscar o endereço completo da operação." />
          <Row label="Feriados" value="Gerenciados de forma centralizada em RH → Feriados. Aplicam-se a todas as praças da empresa." />
          <Row label="Como aparece no espelho" value="Toda batida em dia de feriado vira HE 100% (CLT)." />
        </Card>
      )}
    </div>
  );
}
