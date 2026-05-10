import React, { useEffect, useMemo, useState, useCallback } from "react";
import { api } from "@/api";
import { Card, Metric } from "@/ui";

// ============================================================
// Helpers visuais
// ============================================================
const SUB_TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "onts", label: "ONTs" },
  { id: "insumos", label: "Insumos" },
  { id: "clientes", label: "Clientes (SmartOLT)" },
  { id: "servicos", label: "Ordens de serviço" },
  { id: "historico", label: "Histórico" },
];

const STATUS_COLORS = {
  disponivel: { bg: "#dcfce7", color: "#166534", label: "Disponível" },
  com_tecnico: { bg: "#dbeafe", color: "#1e40af", label: "Com técnico" },
  instalada: { bg: "#fed7aa", color: "#9a3412", label: "Instalada" },
  retirada_com_tecnico: { bg: "#fef3c7", color: "#92400e", label: "Retirada c/ téc." },
  retornada_empresa: { bg: "#e2e8f0", color: "#475569", label: "Retornada empresa" },
  ativo: { bg: "#dcfce7", color: "#166534", label: "Ativo" },
  fechado: { bg: "#e2e8f0", color: "#475569", label: "Fechado" },
  cancelado: { bg: "#fee2e2", color: "#991b1b", label: "Cancelado" },
  erro_estoque: { bg: "#fee2e2", color: "#991b1b", label: "⚠ Erro estoque" },
};

function StatusPill({ status }) {
  const s = STATUS_COLORS[status] || { bg: "#f1f5f9", color: "#475569", label: status };
  return (
    <span style={{ background: s.bg, color: s.color, padding: "2px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700, letterSpacing: 0.2 }}>
      {s.label}
    </span>
  );
}

function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("pt-BR"); } catch { return iso; }
}

function asyncCall(fn, onDone, errMsgPrefix = "Erro") {
  return async (...args) => {
    try { await fn(...args); if (onDone) onDone(); }
    catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Erro desconhecido";
      alert(`${errMsgPrefix}: ${detail}`);
    }
  };
}

// ============================================================
// Dialog primitivo
// ============================================================
function Modal({ open, onClose, title, children, footer, "data-testid": testId }) {
  if (!open) return null;
  return (
    <div data-testid={testId} style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)", zIndex: 100,
      display: "grid", placeItems: "center", padding: 16,
    }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 18, padding: 22, width: "100%", maxWidth: 560,
        boxShadow: "0 20px 60px rgba(15,23,42,.25)", maxHeight: "90vh", overflow: "auto",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800, color: "#0f172a" }}>{title}</h3>
          <button onClick={onClose} style={{ background: "transparent", border: "none", fontSize: 22, cursor: "pointer", color: "#64748b" }}>×</button>
        </div>
        {children}
        {footer && <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>{footer}</div>}
      </div>
    </div>
  );
}

const inputStyle = {
  width: "100%", padding: "10px 12px", borderRadius: 10, border: "1px solid #cbd5e1",
  fontSize: 14, fontFamily: "inherit", outline: "none", boxSizing: "border-box",
};
const labelStyle = { fontSize: 12, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 6, display: "block" };
const btnPrimary = { padding: "9px 18px", background: "#0f172a", color: "white", border: "none", borderRadius: 10, fontWeight: 700, cursor: "pointer", fontSize: 13 };
const btnSec = { padding: "9px 18px", background: "white", color: "#0f172a", border: "1px solid #cbd5e1", borderRadius: 10, fontWeight: 700, cursor: "pointer", fontSize: 13 };
const btnDanger = { ...btnPrimary, background: "#dc2626" };
const btnGhost = { padding: "6px 12px", background: "transparent", color: "#0f172a", border: "1px solid #e2e8f0", borderRadius: 8, fontWeight: 600, cursor: "pointer", fontSize: 12 };

// ============================================================
// Dashboard
// ============================================================
function DashboardSection({ dashboard, consumables }) {
  if (!dashboard) return <Card>Carregando dashboard…</Card>;
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 14, marginBottom: 18 }}>
        <Metric label="ONTs no estoque" value={dashboard.company_onts} data-testid="stat-company-onts" />
        <Metric label="Total ONTs" value={dashboard.total_onts} />
        <Metric label="Técnicos com estoque" value={dashboard.technicians_count} />
        <Metric label="OS ativas" value={dashboard.active_services_count} />
        <Metric label="Eficiência retirada" value={`${dashboard.withdrawal_rate}%`} />
      </div>

      <Card title="Estoque da Empresa" data-testid="empresa-stock-card">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10 }}>
          {consumables.map((c) => (
            <div key={c.id} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: 12 }}>
              <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", fontWeight: 700, letterSpacing: 0.4 }}>{c.name}</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: "#0f172a", marginTop: 4 }}>
                {dashboard.empresa_stock?.[c.id] || 0}
                <span style={{ fontSize: 12, color: "#64748b", fontWeight: 500, marginLeft: 4 }}>{c.unit}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Estoque por Técnico" data-testid="tech-rows-card">
        {dashboard.tech_rows.length === 0 ? (
          <div style={{ color: "#64748b" }}>Nenhum técnico ativo.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {dashboard.tech_rows.map((t) => (
              <div key={t.id} style={{ border: "1px solid #e2e8f0", borderRadius: 12, padding: 12 }} data-testid={`tech-row-${t.id}`}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>{t.name}</div>
                    <div style={{ fontSize: 12, color: "#64748b" }}>
                      {t.tech_onts} ONTs · Instalações: {t.installed_month} · Retiradas: {t.withdrawals}
                    </div>
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(110px,1fr))", gap: 6 }}>
                  {consumables.map((c) => (
                    <div key={c.id} style={{ background: "#f8fafc", padding: "6px 10px", borderRadius: 8, fontSize: 12 }}>
                      <span style={{ color: "#64748b" }}>{c.name}: </span>
                      <strong>{t.stock?.[c.id] || 0} {c.unit}</strong>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// ============================================================
// ONTs
// ============================================================
function OntsSection({ onts, technicians, reload }) {
  const [filter, setFilter] = useState("");
  const [locFilter, setLocFilter] = useState("all");
  const [showAdd, setShowAdd] = useState(false);
  const [showTransfer, setShowTransfer] = useState(false);

  const filtered = useMemo(() => {
    const q = filter.toLowerCase();
    return onts.filter((o) => {
      const txt = !q || o.mac.toLowerCase().includes(q) || (o.model || "").toLowerCase().includes(q) || (o.client_name || "").toLowerCase().includes(q);
      const loc = locFilter === "all" || o.location_type === locFilter;
      return txt && loc;
    });
  }, [onts, filter, locFilter]);

  const techMap = useMemo(() => Object.fromEntries(technicians.map((t) => [t.id, t.name])), [technicians]);

  const editModel = asyncCall(async (mac, current) => {
    const novo = window.prompt("Novo modelo:", current);
    if (!novo || novo === current) return;
    await api.stokOntEdit(mac, novo);
  }, reload, "Erro ao editar");

  const returnToCompany = asyncCall(async (mac) => {
    if (!window.confirm(`Devolver ONT ${mac} para a empresa?`)) return;
    await api.stokOntReturn(mac);
  }, reload, "Erro ao devolver");

  return (
    <Card
      title={`ONTs (${onts.length})`}
      action={
        <div style={{ display: "flex", gap: 8 }}>
          <button data-testid="ont-add-btn" style={btnPrimary} onClick={() => setShowAdd(true)}>+ Adicionar ONTs</button>
          <button data-testid="ont-transfer-btn" style={btnSec} onClick={() => setShowTransfer(true)}>↗ Transferir</button>
        </div>
      }
    >
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <input
          data-testid="ont-filter-input"
          style={{ ...inputStyle, flex: 1, minWidth: 220 }}
          placeholder="Buscar MAC, modelo ou cliente…"
          value={filter} onChange={(e) => setFilter(e.target.value)}
        />
        <select data-testid="ont-loc-filter" style={{ ...inputStyle, width: 200 }} value={locFilter} onChange={(e) => setLocFilter(e.target.value)}>
          <option value="all">Todas as localizações</option>
          <option value="empresa">Estoque empresa</option>
          <option value="tecnico">Com técnico</option>
          <option value="cliente">Instaladas</option>
        </select>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f8fafc", textAlign: "left" }}>
              <th style={{ padding: 10 }}>MAC</th>
              <th style={{ padding: 10 }}>Modelo</th>
              <th style={{ padding: 10 }}>Local</th>
              <th style={{ padding: 10 }}>Status</th>
              <th style={{ padding: 10, textAlign: "right" }}>Ações</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={5} style={{ padding: 24, textAlign: "center", color: "#64748b" }}>Nenhuma ONT encontrada.</td></tr>
            ) : filtered.map((o) => {
              const localLabel = o.location_type === "empresa" ? "Empresa"
                : o.location_type === "tecnico" ? (techMap[o.location_id] || "Técnico desconhecido")
                : o.location_type === "cliente" ? `Cliente: ${o.client_name || o.location_id}`
                : o.location_type;
              return (
                <tr key={o.mac} style={{ borderTop: "1px solid #e2e8f0" }} data-testid={`ont-row-${o.mac}`}>
                  <td style={{ padding: 10, fontFamily: "monospace", fontWeight: 700 }}>{o.mac}</td>
                  <td style={{ padding: 10 }}>{o.model}</td>
                  <td style={{ padding: 10 }}>{localLabel}</td>
                  <td style={{ padding: 10 }}><StatusPill status={o.status} /></td>
                  <td style={{ padding: 10, textAlign: "right" }}>
                    {o.location_type === "empresa" && (
                      <button style={btnGhost} onClick={() => editModel(o.mac, o.model)} data-testid={`ont-edit-${o.mac}`}>✏️ Editar</button>
                    )}
                    {o.location_type === "tecnico" && (
                      <button style={btnGhost} onClick={() => returnToCompany(o.mac)} data-testid={`ont-return-${o.mac}`}>↩ Devolver</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <AddOntsDialog open={showAdd} onClose={() => setShowAdd(false)} onDone={reload} />
      <TransferOntDialog open={showTransfer} onClose={() => setShowTransfer(false)} onDone={reload} technicians={technicians} />
    </Card>
  );
}

function AddOntsDialog({ open, onClose, onDone }) {
  const [model, setModel] = useState("");
  const [macs, setMacs] = useState("");
  const submit = asyncCall(async () => {
    const list = macs.split(/[\s,;\n]+/).map((s) => s.trim()).filter(Boolean);
    if (!model.trim()) return alert("Informe o modelo.");
    if (list.length === 0) return alert("Informe pelo menos 1 MAC.");
    await api.stokOntsBulk(model.trim(), list);
    setModel(""); setMacs(""); onClose();
  }, onDone, "Erro ao cadastrar ONTs");
  return (
    <Modal open={open} onClose={onClose} title="Adicionar ONTs" data-testid="ont-add-dialog"
      footer={<>
        <button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="ont-add-submit">Cadastrar</button>
      </>}
    >
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Modelo</label>
        <input data-testid="ont-add-model" style={inputStyle} value={model} onChange={(e) => setModel(e.target.value)} placeholder="ZTE F670L, Huawei HG8245H, etc." />
      </div>
      <div>
        <label style={labelStyle}>MACs (1 por linha ou separados por vírgula)</label>
        <textarea data-testid="ont-add-macs" style={{ ...inputStyle, height: 140, fontFamily: "monospace" }} value={macs} onChange={(e) => setMacs(e.target.value)} placeholder="AA:BB:CC:DD:EE:01&#10;AA:BB:CC:DD:EE:02" />
      </div>
    </Modal>
  );
}

function TransferOntDialog({ open, onClose, onDone, technicians }) {
  const [mac, setMac] = useState("");
  const [techId, setTechId] = useState("");
  const submit = asyncCall(async () => {
    if (!mac.trim() || !techId) return alert("MAC e técnico são obrigatórios.");
    await api.stokOntTransfer(mac.trim(), techId);
    setMac(""); setTechId(""); onClose();
  }, onDone, "Erro ao transferir");
  return (
    <Modal open={open} onClose={onClose} title="↗ Transferir ONT para técnico" data-testid="ont-transfer-dialog"
      footer={<>
        <button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="ont-transfer-submit">Transferir</button>
      </>}
    >
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>MAC da ONT</label>
        <input data-testid="ont-transfer-mac" style={inputStyle} value={mac} onChange={(e) => setMac(e.target.value)} placeholder="AA:BB:CC:DD:EE:FF" />
      </div>
      <div>
        <label style={labelStyle}>Técnico de destino</label>
        <select data-testid="ont-transfer-tech" style={inputStyle} value={techId} onChange={(e) => setTechId(e.target.value)}>
          <option value="">Selecione…</option>
          {technicians.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
    </Modal>
  );
}

// ============================================================
// Insumos
// ============================================================
function InsumosSection({ consumables, technicians, stock, reload }) {
  const [showPurchase, setShowPurchase] = useState(false);
  const [showTransfer, setShowTransfer] = useState(false);

  return (
    <Card
      title="Insumos (consumíveis)"
      action={
        <div style={{ display: "flex", gap: 8 }}>
          <button data-testid="cons-purchase-btn" style={btnPrimary} onClick={() => setShowPurchase(true)}>+ Compra</button>
          <button data-testid="cons-transfer-btn" style={btnSec} onClick={() => setShowTransfer(true)}>↗ Transferir</button>
        </div>
      }
    >
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f8fafc", textAlign: "left" }}>
              <th style={{ padding: 10 }}>Local</th>
              {consumables.map((c) => <th key={c.id} style={{ padding: 10, textAlign: "right" }}>{c.name} ({c.unit})</th>)}
            </tr>
          </thead>
          <tbody>
            <tr style={{ borderTop: "1px solid #e2e8f0", background: "#f1f5f9" }}>
              <td style={{ padding: 10, fontWeight: 800 }}>🏢 Empresa</td>
              {consumables.map((c) => (
                <td key={c.id} style={{ padding: 10, textAlign: "right", fontFamily: "monospace", fontWeight: 700 }}>
                  {stock.empresa?.[c.id] || 0}
                </td>
              ))}
            </tr>
            {technicians.map((t) => (
              <tr key={t.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                <td style={{ padding: 10 }}>👷 {t.name}</td>
                {consumables.map((c) => (
                  <td key={c.id} style={{ padding: 10, textAlign: "right", fontFamily: "monospace" }}>
                    {stock[t.id]?.[c.id] || 0}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ConsumablePurchaseDialog open={showPurchase} onClose={() => setShowPurchase(false)} onDone={reload} consumables={consumables} />
      <ConsumableTransferDialog open={showTransfer} onClose={() => setShowTransfer(false)} onDone={reload} consumables={consumables} technicians={technicians} />
    </Card>
  );
}

function ConsumablePurchaseDialog({ open, onClose, onDone, consumables }) {
  const [cid, setCid] = useState("");
  const [qty, setQty] = useState(1);
  const item = consumables.find((c) => c.id === cid);
  const total = item ? qty * item.pack_qty : 0;
  const submit = asyncCall(async () => {
    if (!cid || qty <= 0) return alert("Selecione insumo e informe quantidade.");
    await api.stokConsumablePurchase(cid, parseInt(qty, 10));
    setCid(""); setQty(1); onClose();
  }, onDone, "Erro na compra");
  return (
    <Modal open={open} onClose={onClose} title="Registrar compra" data-testid="cons-purchase-dialog"
      footer={<><button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="cons-purchase-submit">Registrar</button></>}
    >
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Insumo</label>
        <select data-testid="cons-purchase-id" style={inputStyle} value={cid} onChange={(e) => setCid(e.target.value)}>
          <option value="">Selecione…</option>
          {consumables.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.pack_label} = {c.pack_qty} {c.unit})</option>)}
        </select>
      </div>
      <div>
        <label style={labelStyle}>Quantidade ({item?.pack_label || "pacotes"})</label>
        <input data-testid="cons-purchase-qty" type="number" min="1" style={inputStyle} value={qty} onChange={(e) => setQty(e.target.value)} />
      </div>
      {item && total > 0 && (
        <div style={{ marginTop: 12, padding: 10, background: "#dbeafe", color: "#1e40af", borderRadius: 8, fontSize: 13 }}>
          Total: <strong>{total} {item.unit}</strong>
        </div>
      )}
    </Modal>
  );
}

function ConsumableTransferDialog({ open, onClose, onDone, consumables, technicians }) {
  const [cid, setCid] = useState("");
  const [qty, setQty] = useState(0);
  const [techId, setTechId] = useState("");
  const submit = asyncCall(async () => {
    if (!cid || qty <= 0 || !techId) return alert("Preencha todos os campos.");
    await api.stokConsumableTransfer(cid, parseInt(qty, 10), techId);
    setCid(""); setQty(0); setTechId(""); onClose();
  }, onDone, "Erro na transferência");
  return (
    <Modal open={open} onClose={onClose} title="↗ Transferir insumo para técnico" data-testid="cons-transfer-dialog"
      footer={<><button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="cons-transfer-submit">Transferir</button></>}
    >
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Insumo</label>
        <select data-testid="cons-transfer-id" style={inputStyle} value={cid} onChange={(e) => setCid(e.target.value)}>
          <option value="">Selecione…</option>
          {consumables.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Quantidade</label>
        <input data-testid="cons-transfer-qty" type="number" min="1" style={inputStyle} value={qty} onChange={(e) => setQty(e.target.value)} />
      </div>
      <div>
        <label style={labelStyle}>Técnico</label>
        <select data-testid="cons-transfer-tech" style={inputStyle} value={techId} onChange={(e) => setTechId(e.target.value)}>
          <option value="">Selecione…</option>
          {technicians.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
    </Modal>
  );
}

// ============================================================
// Serviços (OS)
// ============================================================
const SERVICE_TYPES = ["instalacao", "reparo", "troca", "retirada", "ponto_adicional"];

function ServicosSection({ services, technicians, consumables, reload }) {
  const [showCreate, setShowCreate] = useState(false);
  const [closing, setClosing] = useState(null); // service object
  const techMap = useMemo(() => Object.fromEntries(technicians.map((t) => [t.id, t.name])), [technicians]);
  return (
    <Card
      title={`Serviços (${services.length})`}
      action={<button data-testid="svc-create-btn" style={btnPrimary} onClick={() => setShowCreate(true)}>+ Nova OS</button>}
    >
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f8fafc", textAlign: "left" }}>
              <th style={{ padding: 10 }}>OS</th>
              <th style={{ padding: 10 }}>Tipo</th>
              <th style={{ padding: 10 }}>Cliente</th>
              <th style={{ padding: 10 }}>Técnico</th>
              <th style={{ padding: 10 }}>Status</th>
              <th style={{ padding: 10 }}>Aberta em</th>
              <th style={{ padding: 10, textAlign: "right" }}>Ações</th>
            </tr>
          </thead>
          <tbody>
            {services.length === 0 ? (
              <tr><td colSpan={7} style={{ padding: 24, textAlign: "center", color: "#64748b" }}>Nenhuma OS cadastrada.</td></tr>
            ) : services.map((s) => (
              <tr key={s.id} style={{ borderTop: "1px solid #e2e8f0" }} data-testid={`svc-row-${s.id}`}>
                <td style={{ padding: 10, fontFamily: "monospace", fontWeight: 700 }}>{s.id}</td>
                <td style={{ padding: 10 }}>
                  {s.type}
                  {s.auto_opened && <span title="Auto-aberta pela Lousa" style={{ marginLeft: 4, fontSize: 10, color: "#64748b" }}>🤖</span>}
                  {s.auto_closed && <span title="Auto-fechada pela Lousa" style={{ marginLeft: 4, fontSize: 10, color: "#15803d" }}>✓auto</span>}
                </td>
                <td style={{ padding: 10 }}>{s.client_name}</td>
                <td style={{ padding: 10 }}>{techMap[s.technician_id] || s.technician_id}</td>
                <td style={{ padding: 10 }}>
                  <StatusPill status={s.status} />
                  {s.error_reason && (
                    <div style={{ fontSize: 10, color: "#991b1b", marginTop: 2, maxWidth: 220 }}>
                      ⚠ {s.error_reason}
                    </div>
                  )}
                </td>
                <td style={{ padding: 10, fontSize: 12, color: "#64748b" }}>{fmtDate(s.created_at)}</td>
                <td style={{ padding: 10, textAlign: "right" }}>
                  {(s.status === "ativo" || s.status === "erro_estoque") && (
                    <button style={btnGhost} onClick={() => setClosing(s)} data-testid={`svc-close-${s.id}`}>
                      {s.status === "erro_estoque" ? "🛠 Resolver" : "✓ Fechar"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CreateServiceDialog open={showCreate} onClose={() => setShowCreate(false)} onDone={reload} technicians={technicians} />
      <CloseServiceDialog service={closing} onClose={() => setClosing(null)} onDone={reload} consumables={consumables} />
    </Card>
  );
}

function CreateServiceDialog({ open, onClose, onDone, technicians }) {
  const [data, setData] = useState({ type: "instalacao", client_id: "", client_name: "", technician_id: "", reason: "" });
  const submit = asyncCall(async () => {
    if (!data.client_id || !data.client_name || !data.technician_id) return alert("Preencha cliente, ID e técnico.");
    await api.stokServiceCreate(data);
    setData({ type: "instalacao", client_id: "", client_name: "", technician_id: "", reason: "" });
    onClose();
  }, onDone, "Erro ao criar OS");
  return (
    <Modal open={open} onClose={onClose} title="Nova ordem de serviço" data-testid="svc-create-dialog"
      footer={<><button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="svc-create-submit">Abrir OS</button></>}
    >
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
        <div>
          <label style={labelStyle}>Tipo</label>
          <select data-testid="svc-create-type" style={inputStyle} value={data.type} onChange={(e) => setData({ ...data, type: e.target.value })}>
            {SERVICE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Técnico</label>
          <select data-testid="svc-create-tech" style={inputStyle} value={data.technician_id} onChange={(e) => setData({ ...data, technician_id: e.target.value })}>
            <option value="">Selecione…</option>
            {technicians.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
      </div>
      <div style={{ marginBottom: 10 }}>
        <label style={labelStyle}>ID do cliente</label>
        <input data-testid="svc-create-client-id" style={inputStyle} value={data.client_id} onChange={(e) => setData({ ...data, client_id: e.target.value })} placeholder="Ex.: 1234 ou CPF" />
      </div>
      <div style={{ marginBottom: 10 }}>
        <label style={labelStyle}>Nome do cliente</label>
        <input data-testid="svc-create-client-name" style={inputStyle} value={data.client_name} onChange={(e) => setData({ ...data, client_name: e.target.value })} />
      </div>
      <div>
        <label style={labelStyle}>Motivo (opcional)</label>
        <input data-testid="svc-create-reason" style={inputStyle} value={data.reason} onChange={(e) => setData({ ...data, reason: e.target.value })} />
      </div>
    </Modal>
  );
}

function CloseServiceDialog({ service, onClose, onDone, consumables }) {
  const [mac, setMac] = useState("");
  const [items, setItems] = useState({});
  const [tag, setTag] = useState("instalacao");

  useEffect(() => { setMac(""); setItems({}); setTag(service?.type || "instalacao"); }, [service]);

  if (!service) return null;
  const needsMac = ["instalacao", "troca", "retirada"].includes(service.type);

  const submit = asyncCall(async () => {
    const used_items = Object.entries(items).filter(([, q]) => +q > 0).map(([consumable_id, q]) => ({ consumable_id, quantity: parseInt(q, 10) }));
    if (needsMac && !mac.trim()) return alert("Informe o MAC da ONT.");
    await api.stokServiceClose(service.id, { ont_mac: mac.trim() || null, used_items, tag: tag || service.type });
    onClose();
  }, onDone, "Erro ao fechar OS");

  return (
    <Modal open={!!service} onClose={onClose} title={`Fechar ${service.id} — ${service.client_name}`} data-testid="svc-close-dialog"
      footer={<><button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="svc-close-submit">Confirmar fechamento</button></>}
    >
      {needsMac && (
        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>MAC da ONT</label>
          <input data-testid="svc-close-mac" style={inputStyle} value={mac} onChange={(e) => setMac(e.target.value)} placeholder="AA:BB:CC:DD:EE:FF" />
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
            {service.type === "retirada" ? "MAC vinculado ao cliente." : "MAC do estoque do técnico responsável."}
          </div>
        </div>
      )}
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Tag</label>
        <input data-testid="svc-close-tag" style={inputStyle} value={tag} onChange={(e) => setTag(e.target.value)} placeholder="instalacao, reparo, etc." />
      </div>
      <div>
        <label style={labelStyle}>Insumos utilizados (opcional)</label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {consumables.map((c) => (
            <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 13, flex: 1 }}>{c.name}</span>
              <input
                data-testid={`svc-close-qty-${c.id}`}
                type="number" min="0" placeholder={c.unit}
                style={{ ...inputStyle, width: 100 }}
                value={items[c.id] || ""}
                onChange={(e) => setItems({ ...items, [c.id]: e.target.value })}
              />
            </div>
          ))}
        </div>
      </div>
    </Modal>
  );
}

// ============================================================
// Histórico
// ============================================================
function HistoricoSection({ history, reload }) {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const filtered = useMemo(() => {
    const qq = q.toLowerCase();
    return history.filter((h) => {
      const txt = !qq || (h.description || "").toLowerCase().includes(qq) || (h.user || "").toLowerCase().includes(qq);
      const t = !type || h.type === type;
      return txt && t;
    });
  }, [history, q, type]);
  const types = useMemo(() => Array.from(new Set(history.map((h) => h.type))).sort(), [history]);

  const downloadExport = async (format) => {
    try {
      const params = new URLSearchParams();
      params.set("format", format);
      if (type) params.set("type", type);
      if (q) params.set("q", q);
      const token = window.localStorage.getItem("ponto_token") || "";
      const url = `${process.env.REACT_APP_BACKEND_URL}/api/stok/history/export?${params.toString()}`;
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) {
        const err = await res.text();
        alert(`Erro ao exportar: ${err}`);
        return;
      }
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      a.download = `estoque_historico_${ts}.${format}`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (e) {
      alert(`Erro ao exportar: ${e.message}`);
    }
  };

  return (
    <Card
      title={`Histórico (${filtered.length})`}
      action={
        <div style={{ display: "flex", gap: 6 }}>
          <button style={btnGhost} onClick={() => downloadExport("csv")} data-testid="hist-export-csv">📥 CSV</button>
          <button style={btnGhost} onClick={() => downloadExport("pdf")} data-testid="hist-export-pdf">📄 PDF</button>
          <button style={btnGhost} onClick={reload} data-testid="hist-reload">⟳ Atualizar</button>
        </div>
      }
    >
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <input
          data-testid="hist-search"
          style={{ ...inputStyle, flex: 1, minWidth: 220 }}
          placeholder="Buscar descrição ou usuário…" value={q} onChange={(e) => setQ(e.target.value)}
        />
        <select data-testid="hist-type-filter" style={{ ...inputStyle, width: 220 }} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">Todos os tipos</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f8fafc", textAlign: "left" }}>
              <th style={{ padding: 10 }}>Data</th>
              <th style={{ padding: 10 }}>Tipo</th>
              <th style={{ padding: 10 }}>Tag</th>
              <th style={{ padding: 10 }}>Descrição</th>
              <th style={{ padding: 10 }}>Usuário</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={5} style={{ padding: 24, textAlign: "center", color: "#64748b" }}>Sem registros.</td></tr>
            ) : filtered.map((h) => (
              <tr key={h.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                <td style={{ padding: 10, fontSize: 12, color: "#64748b", whiteSpace: "nowrap" }}>{fmtDate(h.date)}</td>
                <td style={{ padding: 10, fontSize: 12 }}>{h.type}</td>
                <td style={{ padding: 10, fontSize: 12 }}>{h.tag}</td>
                <td style={{ padding: 10 }}>{h.description}</td>
                <td style={{ padding: 10, fontSize: 12, color: "#64748b" }}>{h.user}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ============================================================
// Clientes — ONUs em uso (SmartOLT) com fabricante via IA
// ============================================================
const _th = { padding: "8px 10px", fontSize: 11, fontWeight: 700,
              color: "var(--text-secondary)", textTransform: "uppercase",
              letterSpacing: "0.06em", textAlign: "left",
              borderBottom: "1px solid var(--border-default)" };
const _td = { padding: "10px", fontSize: 12, verticalAlign: "middle" };

function ClientesSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState("");
  const [manufFilter, setManufFilter] = useState("all");
  const [identifying, setIdentifying] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      setData(await api.stokClientes(200));
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, []);

  const identifyAll = async () => {
    if (!confirm("Forçar descoberta de fabricantes via IA para TODAS as ONUs ainda desconhecidas?\n\nA IA Gemini será chamada para cada prefixo de SN não cacheado. Pode demorar 1-3 minutos dependendo do volume.")) return;
    setIdentifying(true);
    try {
      const r = await api.stokClientesIdentifyAll(false);
      alert(`Descoberta concluída:\n\n• ${r.new_manufacturers_found} novos fabricantes encontrados\n• ${r.prefixes_tested} prefixos testados via IA\n• ${r.total_prefixes_unknown_before} eram desconhecidos antes`);
      await reload();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setIdentifying(false);
    }
  };

  useEffect(() => { reload(); }, [reload]);

  const items = useMemo(() => {
    if (!data) return [];
    const q = filter.trim().toLowerCase();
    return data.items.filter((it) => {
      if (manufFilter !== "all" && (it.manufacturer || "Desconhecido") !== manufFilter) return false;
      if (!q) return true;
      return [it.client_name, it.sn, it.mac, it.olt_name].filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q));
    });
  }, [data, filter, manufFilter]);

  const signalColor = (txt) => {
    if (!txt) return { bg: "var(--bg-surface-2)", color: "var(--text-muted)" };
    const s = String(txt).toLowerCase();
    if (s.includes("very good") || s.includes("excelente")) return { bg: "var(--success-soft)", color: "var(--success-soft-fg)" };
    if (s.includes("good") || s.includes("bom")) return { bg: "var(--info-soft)", color: "var(--info-soft-fg)" };
    if (s.includes("acceptable") || s.includes("regular")) return { bg: "var(--warning-soft)", color: "var(--warning-soft-fg)" };
    return { bg: "var(--danger-soft)", color: "var(--danger-soft-fg)" };
  };

  if (loading && !data) return <Card>Carregando clientes do SmartOLT… (até 30s na primeira chamada)</Card>;
  if (err) return <Card><div style={{ color: "#dc2626" }}>Erro: {err}</div></Card>;
  if (!data) return null;

  return (
    <>
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
        gap: 10, marginBottom: 14,
      }}>
        <Metric label="Clientes" value={data.total.toLocaleString("pt-BR")} />
        <Metric label="Identificados (IA)" value={`${data.identified}/${data.total}`}
                hint={`${Math.round(100 * data.identified / Math.max(1, data.total))}% reconhecidos`} />
        {Object.entries(data.by_manufacturer).slice(0, 3).map(([k, v]) => (
          <Metric key={k} label={k} value={v.toLocaleString("pt-BR")}
                  hint={`${Math.round(100 * v / Math.max(1, data.total))}%`} />
        ))}
      </div>

      <Card title={`Clientes ativos (${items.length} de ${data.total})`}
            subtitle="ONUs em uso pegas via API do SmartOLT — fabricante identificado por prefixo de SN ou IA (Gemini)."
            data-testid="clientes-card"
            action={
              <div style={{ display: "flex", gap: 6 }}>
                <button onClick={identifyAll} disabled={loading || identifying}
                        data-testid="clientes-identify-all"
                        className="btn btn-accent btn-sm"
                        title="Roda IA Gemini em todos os prefixos de SN ainda desconhecidos">
                  {identifying ? "Descobrindo via IA…" : "Forçar descoberta IA"}
                </button>
                <button onClick={reload} disabled={loading || identifying}
                        data-testid="clientes-reload"
                        className="btn btn-secondary btn-sm">
                  {loading ? "Atualizando…" : "Atualizar"}
                </button>
              </div>
            }>
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <input className="input" data-testid="clientes-search" value={filter}
                 onChange={(e) => setFilter(e.target.value)}
                 placeholder="Buscar por cliente, SN, MAC, OLT…"
                 style={{ flex: 1, minWidth: 220 }} />
          <select className="input" data-testid="clientes-manuf-filter"
                  value={manufFilter} onChange={(e) => setManufFilter(e.target.value)}
                  style={{ width: 230 }}>
            <option value="all">Todos os fabricantes</option>
            {Object.keys(data.by_manufacturer).map((k) => (
              <option key={k} value={k}>{k} ({data.by_manufacturer[k]})</option>
            ))}
          </select>
        </div>

        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "var(--bg-surface-2)" }}>
                <th style={_th}>Cliente</th>
                <th style={_th}>Número de série</th>
                <th style={_th}>MAC</th>
                <th style={_th}>Marca / Fabricante</th>
                <th style={_th}>OLT / Slot / PON</th>
                <th style={_th}>Sinal</th>
                <th style={_th}>Autorização</th>
              </tr>
            </thead>
            <tbody>
              {items.slice(0, 500).map((it) => {
                const sig = signalColor(it.signal_text);
                const ident = !!it.manufacturer;
                return (
                  <tr key={it.smartolt_external_id || `${it.sn || ""}-${it.mac || ""}`}
                      style={{ borderBottom: "1px solid var(--border-default)" }}
                      data-testid={`cliente-row-${it.sn || it.mac}`}>
                    <td style={_td}>
                      <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{it.client_name}</div>
                    </td>
                    <td style={_td} className="mono" data-mono>{it.sn || "—"}</td>
                    <td style={_td} className="mono" data-mono>{it.mac || "—"}</td>
                    <td style={_td}>
                      <span className={`pill pill--${ident ? "accent" : "neutral"}`}
                            style={{ fontWeight: 600 }}>
                        {it.manufacturer || "Desconhecido"}
                      </span>
                      {it.model && <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>{it.model}</div>}
                    </td>
                    <td style={_td} className="mono" data-mono>
                      {it.olt_name || "—"}
                      {it.board && <span style={{ color: "var(--text-muted)" }}> · slot {it.board}/pon {it.port}</span>}
                    </td>
                    <td style={_td}>
                      <span className="pill" style={{ background: sig.bg, color: sig.color, fontWeight: 600 }}>
                        {it.signal_text || "—"}
                      </span>
                    </td>
                    <td style={_td} className="mono" data-mono>{it.authorization_date || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {items.length > 500 && (
            <div style={{ padding: 8, fontSize: 11, color: "var(--text-muted)", textAlign: "center" }}>
              Mostrando 500 de {items.length} resultados — use o filtro para refinar.
            </div>
          )}
        </div>
      </Card>
    </>
  );
}


// ============================================================
// Painel principal
// ============================================================
export default function EstoquePanel() {
  const [tab, setTab] = useState("dashboard");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [data, setData] = useState({ onts: [], technicians: [], services: [], history: [], stock: {}, dashboard: null, consumables: [] });

  const reload = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const [onts, technicians, services, history, stock, dashboard, catalog] = await Promise.all([
        api.stokOnts(), api.stokTechnicians(), api.stokServices(), api.stokHistory(), api.stokStock(),
        api.stokDashboard(), api.stokCatalog(),
      ]);
      setData({ onts, technicians, services, history, stock, dashboard, consumables: catalog.consumables });
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  return (
    <div data-testid="estoque-panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", color: "#0f172a" }}>Estoque · Fibra Óptica</h2>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748b" }}>ONTs, insumos e ordens de serviço integrados aos técnicos da Lousa.</p>
        </div>
        <button data-testid="estoque-reload" style={btnSec} onClick={reload} disabled={loading}>{loading ? "Carregando…" : "⟳ Recarregar"}</button>
      </div>

      <div style={{ display: "flex", gap: 4, padding: 4, background: "#f1f5f9", borderRadius: 12, marginBottom: 14, overflowX: "auto" }}>
        {SUB_TABS.map((s) => (
          <button
            key={s.id}
            data-testid={`estoque-tab-${s.id}`}
            onClick={() => setTab(s.id)}
            style={{
              padding: "8px 14px", border: "none", borderRadius: 8,
              background: tab === s.id ? "white" : "transparent",
              color: tab === s.id ? "#0f172a" : "#475569",
              fontWeight: 700, fontSize: 13, cursor: "pointer", whiteSpace: "nowrap",
              boxShadow: tab === s.id ? "0 1px 3px rgba(0,0,0,.08)" : "none",
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      {err && <Card><div style={{ color: "#dc2626" }}>Erro: {err}</div></Card>}

      {tab === "dashboard" && <DashboardSection dashboard={data.dashboard} consumables={data.consumables} />}
      {tab === "onts" && <OntsSection onts={data.onts} technicians={data.technicians} reload={reload} />}
      {tab === "insumos" && <InsumosSection consumables={data.consumables} technicians={data.technicians} stock={data.stock} reload={reload} />}
      {tab === "clientes" && <ClientesSection />}
      {tab === "servicos" && <ServicosSection services={data.services} technicians={data.technicians} consumables={data.consumables} reload={reload} />}
      {tab === "historico" && <HistoricoSection history={data.history} reload={reload} />}
    </div>
  );
}
