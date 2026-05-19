import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, Icon, inputStyle } from "@/ui";

const TABS = [
  { id: "dash", label: "Painel" },
  { id: "onts", label: "ONTs" },
  { id: "insumos", label: "Insumos" },
  { id: "servicos", label: "Serviços" },
  { id: "historico", label: "Histórico" },
];

export default function StokPanel() {
  const [tab, setTab] = useState("dash");
  return (
    <div data-testid="stok-panel">
      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            data-testid={`stok-tab-${t.id}`}
            onClick={() => setTab(t.id)}
            style={{
              padding: "6px 14px", borderRadius: 999, fontSize: 13, fontWeight: 700,
              border: `1px solid ${tab === t.id ? "#FF5C00" : "#cbd5e1"}`,
              background: tab === t.id ? "#FF5C00" : "white",
              color: tab === t.id ? "white" : "#475569", cursor: "pointer",
            }}
          >{t.label}</button>
        ))}
      </div>
      {tab === "dash" && <DashTab />}
      {tab === "onts" && <OntsTab />}
      {tab === "insumos" && <InsumosTab />}
      {tab === "servicos" && <ServicosTab />}
      {tab === "historico" && <HistTab />}
    </div>
  );
}

function DashTab() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.stokDashboard().then(setData).catch((e) => setErr(e?.response?.data?.detail || e.message)); }, []);
  if (err) return <ErrBanner err={err} />;
  if (!data) return <Loading />;
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <Stat label="ONTs na empresa" value={data.company_onts} testid="stat-company-onts" />
        <Stat label="ONTs total" value={data.total_onts} testid="stat-total-onts" />
        <Stat label="Serviços ativos" value={data.active_services_count} testid="stat-active-services" />
        <Stat label="Técnicos" value={data.technicians_count} testid="stat-techs" />
      </div>

      <Card title="Estoque por técnico" style={{ marginTop: 14 }}>
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
              <th style={th}>Técnico</th><th style={th}>ONTs</th>
              <th style={th}>Drop (m)</th><th style={th}>Cabo rede (m)</th>
              <th style={th}>Conec. fast</th><th style={th}>Conec. fibra</th>
              <th style={th}>Esticador</th><th style={th}>Conec. rede</th>
              <th style={th}>Instalações mês</th>
            </tr>
          </thead>
          <tbody>
            {data.tech_rows.map((r) => (
              <tr key={r.id} data-testid={`techrow-${r.id}`}>
                <td style={td}><strong>{r.name}</strong></td>
                <td style={td}>{r.tech_onts}</td>
                <td style={td}>{r.stock.drop || 0}</td>
                <td style={td}>{r.stock.cabo_rede || 0}</td>
                <td style={td}>{r.stock.conector_fast || 0}</td>
                <td style={td}>{r.stock.conector_fibra || 0}</td>
                <td style={td}>{r.stock.esticador || 0}</td>
                <td style={td}>{r.stock.conector_rede || 0}</td>
                <td style={td}>{r.installed_month}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Estoque da empresa" style={{ marginTop: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
          {Object.entries(data.empresa_stock).map(([k, v]) => (
            <div key={k} style={{ background: "#f8fafc", padding: 10, borderRadius: 10 }}>
              <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase" }}>{k.replace("_", " ")}</div>
              <div style={{ fontSize: 18, fontWeight: 800 }}>{v}</div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Taxa de retiradas" style={{ marginTop: 14 }}>
        <div style={{ fontSize: 14 }}>
          {data.effective_withdrawals} efetivas de {data.expected_withdrawals} esperadas <strong style={{ color: data.withdrawal_rate >= 70 ? "#16a34a" : "#dc2626" }}>({data.withdrawal_rate}%)</strong>
        </div>
      </Card>
    </div>
  );
}

function OntsTab() {
  const [onts, setOnts] = useState(null);
  const [techs, setTechs] = useState([]);
  const [model, setModel] = useState("");
  const [macsText, setMacsText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState("");

  async function reload() {
    try { setOnts(await api.stokOnts()); setTechs(await api.stokTechnicians()); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }
  useEffect(() => { reload(); }, []);

  async function bulk() {
    setBusy(true); setErr("");
    try {
      const macs = macsText.split(/[\s,;]+/).map((m) => m.trim()).filter(Boolean);
      await api.stokOntsBulk(model, macs);
      setMacsText(""); setModel("");
      await reload();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setBusy(false);
  }

  async function transfer(mac) {
    const tid = await window.prompt("ID do técnico (cole de Painel → coluna):");
    if (!tid) return;
    try { await api.stokOntTransfer(mac, tid); await reload(); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }

  async function ret(mac) {
    if (!await window.confirm(`Retornar ${mac} ao estoque da empresa?`)) return;
    try { await api.stokOntReturn(mac); await reload(); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }

  const filtered = (onts || []).filter((o) =>
    !filter || o.mac.includes(filter.toUpperCase()) || (o.model || "").toUpperCase().includes(filter.toUpperCase())
  );

  return (
    <div>
      <Card title="Entrada em massa">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr auto", gap: 8 }}>
          <Field label="Modelo">
            <input data-testid="ont-model" value={model} onChange={(e) => setModel(e.target.value)} style={inputStyle} placeholder="Ex.: ZTE F660" />
          </Field>
          <Field label="MACs (separados por espaço, vírgula ou linha)">
            <textarea data-testid="ont-macs" value={macsText} onChange={(e) => setMacsText(e.target.value)} rows={3} style={{ ...inputStyle, fontFamily: "ui-monospace" }} />
          </Field>
          <div style={{ alignSelf: "end" }}>
            <Button onClick={bulk} disabled={busy || !model || !macsText} data-testid="ont-bulk-btn">{busy ? "..." : "Cadastrar"}</Button>
          </div>
        </div>
      </Card>

      {err && <ErrBanner err={err} />}

      <Card title={`ONTs (${filtered.length})`} style={{ marginTop: 14 }}>
        <input data-testid="ont-filter" placeholder="Filtrar MAC ou modelo..." value={filter} onChange={(e) => setFilter(e.target.value)} style={{ ...inputStyle, marginBottom: 10, maxWidth: 320 }} />
        <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
              <th style={th}>MAC</th><th style={th}>Modelo</th><th style={th}>Local</th>
              <th style={th}>Cliente</th><th style={th}>Status</th><th style={th}>Ações</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 200).map((o) => {
              const tech = o.location_type === "tecnico" ? techs.find((t) => t.id === o.location_id) : null;
              return (
                <tr key={o.mac} data-testid={`ont-row-${o.mac}`}>
                  <td style={td}><code>{o.mac}</code></td>
                  <td style={td}>{o.model}</td>
                  <td style={td}>{o.location_type === "empresa" ? "Empresa" : o.location_type === "tecnico" ? `🛠 ${tech?.name || o.location_id}` : `👤 Cliente`}</td>
                  <td style={td}>{o.client_name || "—"}</td>
                  <td style={td}><span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "#f1f5f9", color: "#475569" }}>{o.status}</span></td>
                  <td style={td}>
                    {o.location_type === "empresa" && <Button variant="soft" onClick={() => transfer(o.mac)} data-testid={`ont-transfer-${o.mac}`}>→ Técnico</Button>}
                    {o.location_type === "tecnico" && <Button variant="soft" onClick={() => ret(o.mac)} data-testid={`ont-return-${o.mac}`}>↩ Empresa</Button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function InsumosTab() {
  const [catalog, setCatalog] = useState([]);
  const [stock, setStock] = useState({});
  const [techs, setTechs] = useState([]);
  const [err, setErr] = useState("");
  const [purchase, setPurchase] = useState({ id: "", qty: 1 });
  const [tx, setTx] = useState({ id: "", qty: 1, tech: "" });

  async function reload() {
    try {
      const [c, s, t] = await Promise.all([api.stokCatalog(), api.stokStock(), api.stokTechnicians()]);
      setCatalog(c.consumables); setStock(s); setTechs(t);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }
  useEffect(() => { reload(); }, []);

  return (
    <div>
      <Card title="Compra (entrada na empresa)">
        <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
          <Field label="Insumo" style={{ minWidth: 200 }}>
            <select data-testid="purchase-id" value={purchase.id} onChange={(e) => setPurchase({ ...purchase, id: e.target.value })} style={inputStyle}>
              <option value="">—</option>
              {catalog.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.pack_label} = {c.pack_qty} {c.unit})</option>)}
            </select>
          </Field>
          <Field label="Quantidade de pacotes">
            <input data-testid="purchase-qty" type="number" min={1} value={purchase.qty} onChange={(e) => setPurchase({ ...purchase, qty: +e.target.value })} style={{ ...inputStyle, width: 100 }} />
          </Field>
          <Button data-testid="purchase-btn" disabled={!purchase.id || purchase.qty < 1}
            onClick={async () => {
              try { await api.stokConsumablePurchase(purchase.id, purchase.qty); setPurchase({ id: "", qty: 1 }); await reload(); }
              catch (e) { setErr(e?.response?.data?.detail || e.message); }
            }}>+ Comprar</Button>
        </div>
      </Card>

      {err && <ErrBanner err={err} />}

      <Card title="Transferir empresa → técnico" style={{ marginTop: 14 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
          <Field label="Insumo" style={{ minWidth: 180 }}>
            <select data-testid="tx-id" value={tx.id} onChange={(e) => setTx({ ...tx, id: e.target.value })} style={inputStyle}>
              <option value="">—</option>
              {catalog.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Quantidade">
            <input data-testid="tx-qty" type="number" min={1} value={tx.qty} onChange={(e) => setTx({ ...tx, qty: +e.target.value })} style={{ ...inputStyle, width: 100 }} />
          </Field>
          <Field label="Técnico" style={{ minWidth: 200 }}>
            <select data-testid="tx-tech" value={tx.tech} onChange={(e) => setTx({ ...tx, tech: e.target.value })} style={inputStyle}>
              <option value="">—</option>
              {techs.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
          <Button data-testid="tx-btn" disabled={!tx.id || !tx.tech || tx.qty < 1}
            onClick={async () => {
              try { await api.stokConsumableTransfer(tx.id, tx.qty, tx.tech); setTx({ id: "", qty: 1, tech: "" }); await reload(); }
              catch (e) { setErr(e?.response?.data?.detail || e.message); }
            }}>→ Transferir</Button>
        </div>
      </Card>

      <Card title="Estoques atuais" style={{ marginTop: 14 }}>
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "#f1f5f9" }}>
              <th style={th}>Local</th>
              {catalog.map((c) => <th key={c.id} style={th}>{c.name}</th>)}
            </tr>
          </thead>
          <tbody>
            <tr><td style={td}><strong>Empresa</strong></td>{catalog.map((c) => <td key={c.id} style={td}>{(stock.empresa || {})[c.id] || 0}</td>)}</tr>
            {techs.map((t) => (
              <tr key={t.id}>
                <td style={td}>{t.name}</td>
                {catalog.map((c) => <td key={c.id} style={td}>{(stock[t.id] || {})[c.id] || 0}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function ServicosTab() {
  const [services, setServices] = useState([]);
  const [techs, setTechs] = useState([]);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ type: "instalacao", client_id: "", client_name: "", technician_id: "", reason: "" });

  async function reload() {
    try { setServices(await api.stokServices()); setTechs(await api.stokTechnicians()); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }
  useEffect(() => { reload(); }, []);

  async function create() {
    try { await api.stokServiceCreate(form); setForm({ type: "instalacao", client_id: "", client_name: "", technician_id: "", reason: "" }); await reload(); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }

  async function close(s) {
    const ont_mac = s.type === "instalacao" || s.type === "troca" || s.type === "retirada"
      ? await window.prompt(`MAC da ONT (${s.type === "retirada" ? "que está com o cliente" : "do estoque do técnico"}):`) : null;
    if ((s.type === "instalacao" || s.type === "troca" || s.type === "retirada") && !ont_mac) return;
    try {
      await api.stokServiceClose(s.id, { ont_mac, used_items: [], tag: s.type });
      await reload();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }

  return (
    <div>
      <Card title="Nova ordem de serviço">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 2fr 1fr 1fr auto", gap: 8 }}>
          <Field label="Tipo">
            <select data-testid="svc-type" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} style={inputStyle}>
              <option value="instalacao">Instalação</option><option value="reparo">Reparo</option>
              <option value="troca">Troca</option><option value="retirada">Retirada</option>
              <option value="ponto_adicional">Ponto adicional</option>
            </select>
          </Field>
          <Field label="ID cliente"><input data-testid="svc-cid" value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} style={inputStyle} /></Field>
          <Field label="Nome cliente"><input data-testid="svc-cname" value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} style={inputStyle} /></Field>
          <Field label="Técnico">
            <select data-testid="svc-tech" value={form.technician_id} onChange={(e) => setForm({ ...form, technician_id: e.target.value })} style={inputStyle}>
              <option value="">—</option>
              {techs.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
          <Field label="Motivo (opcional)"><input data-testid="svc-reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} style={inputStyle} /></Field>
          <Button data-testid="svc-create" disabled={!form.client_id || !form.client_name || !form.technician_id} onClick={create} style={{ alignSelf: "end" }}>Abrir OS</Button>
        </div>
      </Card>

      {err && <ErrBanner err={err} />}

      <Card title={`Ordens de Serviço (${services.length})`} style={{ marginTop: 14 }}>
        <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "#f1f5f9" }}>
              <th style={th}>ID</th><th style={th}>Tipo</th><th style={th}>Cliente</th>
              <th style={th}>Técnico</th><th style={th}>Status</th><th style={th}>Origem</th><th style={th}>Ações</th>
            </tr>
          </thead>
          <tbody>
            {services.map((s) => {
              const tech = techs.find((t) => t.id === s.technician_id);
              return (
                <tr key={s.id} data-testid={`svc-row-${s.id}`}>
                  <td style={td}><code>{s.id}</code></td><td style={td}>{s.type}</td>
                  <td style={td}>{s.client_name}</td><td style={td}>{tech?.name || "—"}</td>
                  <td style={td}><span style={{ fontSize: 10, fontWeight: 800, padding: "2px 7px", borderRadius: 999, background: s.status === "ativo" ? "#dcfce7" : "#f1f5f9", color: s.status === "ativo" ? "#166534" : "#475569" }}>{s.status}</span></td>
                  <td style={td}>{s.ticket_id ? <span title={`Bolha ${s.ticket_id}`} style={{ fontSize: 10, color: "#1e40af" }}>🔗 Lousa</span> : "Manual"}</td>
                  <td style={td}>{s.status === "ativo" && <Button variant="soft" onClick={() => close(s)} data-testid={`svc-close-${s.id}`}>✓ Fechar</Button>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function HistTab() {
  const [items, setItems] = useState(null);
  const [filter, setFilter] = useState({ tag: "", q: "" });
  const [err, setErr] = useState("");

  async function reload() {
    try { setItems(await api.stokHistory(filter)); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }
  useEffect(() => { reload(); }, [filter.tag, filter.q]);

  if (err) return <ErrBanner err={err} />;

  return (
    <Card title="Histórico">
      <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
        <input data-testid="hist-q" placeholder="Buscar..." value={filter.q} onChange={(e) => setFilter({ ...filter, q: e.target.value })} style={{ ...inputStyle, maxWidth: 240 }} />
        <select data-testid="hist-tag" value={filter.tag} onChange={(e) => setFilter({ ...filter, tag: e.target.value })} style={{ ...inputStyle, maxWidth: 200 }}>
          <option value="">Todas as tags</option>
          {["instalacao", "retirada", "compra", "transferencia", "troca", "reparo", "correcao", "retorno_empresa"].map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      {!items ? <Loading /> : (
        <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "#f1f5f9" }}>
              <th style={th}>Data</th><th style={th}>Tipo</th><th style={th}>Tag</th><th style={th}>Descrição</th><th style={th}>Por</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, 200).map((h) => (
              <tr key={h.id}>
                <td style={td}>{new Date(h.date).toLocaleString("pt-BR")}</td>
                <td style={td}>{h.type}</td>
                <td style={td}><span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 4, background: "#fef3c7", color: "#78350f" }}>{h.tag}</span></td>
                <td style={td}>{h.description}</td>
                <td style={td}>{h.user}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function Stat({ label, value, testid }) {
  return (
    <div data-testid={testid} style={{ background: "white", border: "1px solid #e2e8f0", borderRadius: 12, padding: 14 }}>
      <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 900, color: "#0f172a" }}>{value}</div>
    </div>
  );
}

function ErrBanner({ err }) {
  return <div style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 8, marginTop: 10 }}>{err}</div>;
}
function Loading() {
  return <div style={{ color: "#94a3b8", padding: 20, textAlign: "center" }}>Carregando…</div>;
}

const th = { padding: "8px 10px", fontWeight: 700, color: "#475569", borderBottom: "1px solid #e2e8f0" };
const td = { padding: "8px 10px", borderBottom: "1px solid #f1f5f9" };
