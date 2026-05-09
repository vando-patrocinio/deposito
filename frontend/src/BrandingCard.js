import React, { useEffect, useState } from "react";
import { Card, Button } from "@/ui";
import { api } from "@/api";

export default function BrandingCard() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    api.brandingGet().then(setData).catch(() => setData({}));
  }, []);

  const onLogo = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 1_500_000) {
      setMsg({ type: "err", text: "Arquivo muito grande (max 1.5 MB)." });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setData({ ...data, logo_data_url: reader.result });
    reader.readAsDataURL(file);
  };

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const out = await api.brandingUpdate(data);
      setData(out);
      setMsg({ type: "ok", text: "Salvo com sucesso." });
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  if (!data) return <Card title="🏢 Empresa & Branding">Carregando…</Card>;

  const fld = (label, key, hint, opts = {}) => (
    <label style={{ display: "block", marginBottom: 10 }}>
      <div style={{ fontSize: 11, color: "#475569", fontWeight: 700, marginBottom: 3 }}>{label}</div>
      <input data-testid={`branding-${key}`} value={data[key] || ""} {...opts}
             onChange={(e) => setData({ ...data, [key]: e.target.value })}
             style={{ width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1",
                      borderRadius: 8, fontSize: 13, boxSizing: "border-box" }} />
      {hint && <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2 }}>{hint}</div>}
    </label>
  );

  return (
    <Card title="🏢 Empresa & Branding (Romaneio)" data-testid="branding-card">
      <p style={{ fontSize: 12, color: "#64748b", marginTop: 0 }}>
        Esses dados aparecem no <strong>cabeçalho do romaneio</strong> assinado pelos colaboradores.
      </p>

      {/* Logo */}
      <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 14,
                    padding: 12, background: "#f8fafc", borderRadius: 12 }}>
        <div style={{ width: 100, height: 100, borderRadius: 14, background: "white",
                       border: "2px dashed #cbd5e1", display: "grid", placeItems: "center",
                       overflow: "hidden", flexShrink: 0 }}>
          {data.logo_data_url
            ? <img src={data.logo_data_url} alt="logo" style={{ width: "100%", height: "100%", objectFit: "contain" }} data-testid="branding-logo-preview" />
            : <div style={{ color: "#94a3b8", fontSize: 11, textAlign: "center" }}>Sem logo</div>}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>
            Logo da empresa
          </div>
          <input type="file" accept="image/png,image/jpeg,image/svg+xml" onChange={onLogo}
                 data-testid="branding-logo-input"
                 style={{ fontSize: 12, marginBottom: 6 }} />
          {data.logo_data_url && (
            <button data-testid="branding-logo-remove"
                    onClick={() => setData({ ...data, logo_data_url: "" })}
                    style={{ fontSize: 11, padding: "4px 8px", border: "1px solid #fca5a5",
                             background: "#fef2f2", color: "#991b1b", borderRadius: 6,
                             cursor: "pointer", fontWeight: 600 }}>
              ✕ Remover logo
            </button>
          )}
          <div style={{ fontSize: 10, color: "#94a3b8" }}>
            PNG/JPG/SVG · max 1.5 MB · ideal 400×400px
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {fld("Nome da empresa *", "company_name", "Aparece em destaque no romaneio")}
        {fld("CNPJ", "cnpj")}
        <div style={{ gridColumn: "span 2" }}>
          {fld("Endereço (sede)", "address", "Rua, número, bairro")}
        </div>
        {fld("Cidade", "city")}
        {fld("Estado (UF)", "state")}
        {fld("CEP", "zip_code")}
        {fld("Telefone", "phone")}
        {fld("E-mail", "email")}
        {fld("Site", "website")}
      </div>

      <label style={{ display: "block", marginTop: 8 }}>
        <div style={{ fontSize: 11, color: "#475569", fontWeight: 700, marginBottom: 3 }}>
          Termo de responsabilidade (rodapé do romaneio)
        </div>
        <textarea data-testid="branding-romaneio_footer"
                  value={data.romaneio_footer || ""} rows={3}
                  onChange={(e) => setData({ ...data, romaneio_footer: e.target.value })}
                  style={{ width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1",
                           borderRadius: 8, fontSize: 12, boxSizing: "border-box",
                           fontFamily: "inherit", resize: "vertical" }} />
      </label>

      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <Button onClick={save} disabled={busy} data-testid="branding-save-btn">
          {busy ? "Salvando…" : "💾 Salvar"}
        </Button>
      </div>
      {msg && (
        <div data-testid="branding-msg" style={{
          marginTop: 10, padding: 10, borderRadius: 8, fontSize: 12, fontWeight: 600,
          background: msg.type === "ok" ? "#dcfce7" : "#fee2e2",
          color: msg.type === "ok" ? "#166534" : "#7f1d1d",
        }}>{msg.text}</div>
      )}
    </Card>
  );
}
