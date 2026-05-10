import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import {
  UserCircle, Search, Plus, Phone, MapPin, Tag,
  Save, X, Trash2, Edit2, Upload, Download, AlertTriangle,
  CheckCircle2, History, FileText, RefreshCw,
} from "lucide-react";

const STATUS_OPTIONS = [
  "ATIVO", "BLOQUEADO", "SUSPENSO", "CANCELADO",
  "EM_INSTALACAO", "AGUARDANDO_VIABILIDADE", "SEM_VIABILIDADE",
  "PROSPECT", "INADIMPLENTE",
];

const STATUS_COLORS = {
  ATIVO: "success", BLOQUEADO: "danger", SUSPENSO: "warning",
  CANCELADO: "neutral", INADIMPLENTE: "danger",
  EM_INSTALACAO: "info", AGUARDANDO_VIABILIDADE: "info",
  SEM_VIABILIDADE: "warning", PROSPECT: "neutral",
};

export default function SubscribersPanel() {
  const [items, setItems] = useState([]);
  const [filters, setFilters] = useState({ q: "", status: "", plan: "" });
  const [editing, setEditing] = useState(null);  // null | {id?, ...}
  const [historyOf, setHistoryOf] = useState(null);
  const [showImport, setShowImport] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setBusy(true);
    api.subscribersList(filters).then((r) => setItems(r.items || []))
      .finally(() => setBusy(false));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const newSub = () => setEditing({
    name: "", status: "ATIVO", phones: [{ raw_number: "", is_primary: true, is_whatsapp: true }],
    addresses: [{ is_primary: true }], tags: [],
  });

  if (editing) return <SubscriberEditor data={editing} setData={setEditing}
                                          onSaved={() => { setEditing(null); load(); }}
                                          onCancel={() => setEditing(null)} />;
  if (historyOf) return <SubscriberHistory subscriber={historyOf}
                                            onClose={() => setHistoryOf(null)} />;
  if (showImport) return <CsvImporter onClose={() => { setShowImport(false); load(); }} />;

  return (
    <div data-testid="subscribers-panel" style={{ padding: "0 4px" }}>
      <div style={{ marginBottom: 14, display: "flex", justifyContent: "space-between",
                     alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 className="page-title" style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <UserCircle size={24} strokeWidth={1.75} /> Assinantes
          </h1>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 4 }}>
            Cadastro de clientes vinculado automaticamente a chamadas e WhatsApp pelo telefone.
          </p>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="btn btn-secondary btn-sm" onClick={() => setShowImport(true)}
                  data-testid="subs-import-btn">
            <Upload size={13} /> Importar CSV
          </button>
          <button className="btn btn-primary btn-sm" onClick={newSub}
                  data-testid="subs-new-btn">
            <Plus size={13} /> Novo assinante
          </button>
        </div>
      </div>

      {/* Filtros */}
      <div className="surface" style={{ padding: 12, borderRadius: 12, marginBottom: 14,
                                          display: "grid",
                                          gridTemplateColumns: "2fr 1fr 1fr auto", gap: 8 }}>
        <div style={{ position: "relative" }}>
          <Search size={14} style={{ position: "absolute", left: 10, top: 11,
                                       color: "var(--text-muted)" }} />
          <input className="input" placeholder="Buscar por nome, documento, código, e-mail..."
                 value={filters.q}
                 onChange={(e) => setFilters({ ...filters, q: e.target.value })}
                 onKeyDown={(e) => e.key === "Enter" && load()}
                 data-testid="subs-search-input"
                 style={{ paddingLeft: 32 }} />
        </div>
        <select className="input" value={filters.status}
                onChange={(e) => { setFilters({ ...filters, status: e.target.value }); }}
                data-testid="subs-status-filter">
          <option value="">Todos os status</option>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input className="input" placeholder="Plano"
               value={filters.plan}
               onChange={(e) => setFilters({ ...filters, plan: e.target.value })} />
        <button className="btn btn-secondary btn-sm" onClick={load}
                data-testid="subs-apply-filters">
          <RefreshCw size={13} /> Aplicar
        </button>
      </div>

      {/* Lista */}
      <div className="surface" style={{ padding: 0, borderRadius: 12, overflow: "hidden" }}>
        {busy && items.length === 0 && (
          <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>
            Carregando…
          </div>
        )}
        {!busy && items.length === 0 && (
          <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>
            Nenhum assinante encontrado.
            <button onClick={newSub} className="btn btn-primary btn-sm"
                    style={{ marginLeft: 12 }}>
              <Plus size={13} /> Cadastrar agora
            </button>
          </div>
        )}
        {items.map((s, i) => (
          <div key={s.id} data-testid={`sub-row-${s.id}`}
               style={{
                 padding: 12, borderTop: i ? "1px solid var(--border-default)" : "none",
                 display: "grid",
                 gridTemplateColumns: "2.5fr 1fr 1.5fr 1.5fr auto",
                 gap: 12, alignItems: "center",
               }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 14 }}>{s.name}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                {s.external_code && <>#{s.external_code} · </>}
                {s.email && <>{s.email}</>}
                {s.tags?.length > 0 && <>{s.email && " · "}<Tag size={10}
                  style={{ display: "inline", verticalAlign: -1 }} /> {s.tags.join(", ")}</>}
              </div>
            </div>
            <span className={`pill pill--${STATUS_COLORS[s.status] || "neutral"}`}>
              {s.status}
            </span>
            <div style={{ fontSize: 12 }}>
              {s.plan_name || "—"}
              {s.plan_speed && <span style={{ color: "var(--text-muted)" }}> · {s.plan_speed}</span>}
            </div>
            <div className="mono" style={{ fontSize: 12 }}>
              {s.primary_phone || "—"}
            </div>
            <div style={{ display: "flex", gap: 4 }}>
              <button onClick={async () => {
                const full = await api.subscribersGet(s.id);
                setEditing(full);
              }} className="btn btn-ghost btn-sm"
                      data-testid={`sub-edit-${s.id}`}>
                <Edit2 size={12} />
              </button>
              <button onClick={() => setHistoryOf(s)}
                      className="btn btn-ghost btn-sm"
                      data-testid={`sub-history-${s.id}`}>
                <History size={12} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SubscriberEditor({ data, setData, onSaved, onCancel }) {
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setData((p) => ({ ...p, [k]: v }));

  const save = async () => {
    if (!data.name || data.name.length < 2) {
      alert("Nome obrigatório."); return;
    }
    setBusy(true);
    try {
      const cleaned = {
        ...data,
        phones: (data.phones || []).filter((p) => p.raw_number && p.raw_number.length >= 8),
        addresses: (data.addresses || []).filter((a) =>
          a.street || a.district || a.city),
      };
      if (data.id) await api.subscribersUpdate(data.id, cleaned);
      else await api.subscribersCreate(cleaned);
      onSaved();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const del = async () => {
    if (!data.id || !window.confirm(`Excluir assinante ${data.name}?`)) return;
    setBusy(true);
    try {
      await api.subscribersDelete(data.id);
      onSaved();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const addPhone = () => set("phones", [
    ...(data.phones || []),
    { raw_number: "", is_whatsapp: true, is_primary: !data.phones?.length },
  ]);
  const updPhone = (i, k, v) => {
    const next = [...(data.phones || [])];
    next[i] = { ...next[i], [k]: v };
    if (k === "is_primary" && v) next.forEach((p, idx) => { if (idx !== i) p.is_primary = false; });
    set("phones", next);
  };
  const delPhone = (i) => set("phones",
    (data.phones || []).filter((_, idx) => idx !== i));

  const updAddr = (k, v) => set("addresses", [{ ...(data.addresses?.[0] || {}), [k]: v, is_primary: true }]);
  const addr = (data.addresses?.[0]) || {};

  return (
    <div data-testid="sub-editor" className="surface" style={{ padding: 22, borderRadius: 14 }}>
      <h3 style={{ margin: "0 0 16px", fontSize: 17, fontWeight: 700 }}>
        {data.id ? `Editar: ${data.name}` : "Novo assinante"}
      </h3>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 12 }}>
        <Field label="Nome completo *">
          <input className="input" value={data.name || ""} onChange={(e) => set("name", e.target.value)}
                 data-testid="sub-name" />
        </Field>
        <Field label="CPF/CNPJ">
          <input className="input" value={data.document || ""}
                 onChange={(e) => set("document", e.target.value)}
                 data-testid="sub-document" />
        </Field>
        <Field label="Código externo">
          <input className="input" value={data.external_code || ""}
                 onChange={(e) => set("external_code", e.target.value)}
                 placeholder="ID do sistema legado" />
        </Field>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
        <Field label="Status">
          <select className="input" value={data.status || "ATIVO"}
                  onChange={(e) => set("status", e.target.value)}>
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="E-mail">
          <input className="input" type="email" value={data.email || ""}
                 onChange={(e) => set("email", e.target.value)} />
        </Field>
        <Field label="Tags (separe por vírgula)">
          <input className="input" value={(data.tags || []).join(", ")}
                 onChange={(e) => set("tags", e.target.value.split(",").map((t) => t.trim()).filter(Boolean))}
                 placeholder="vip, fibra, comercial" />
        </Field>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 12 }}>
        <Field label="Plano">
          <input className="input" value={data.plan_name || ""}
                 onChange={(e) => set("plan_name", e.target.value)}
                 placeholder="Fibra 500 Mega" />
        </Field>
        <Field label="Velocidade">
          <input className="input" value={data.plan_speed || ""}
                 onChange={(e) => set("plan_speed", e.target.value)}
                 placeholder="500 Mbps" />
        </Field>
        <Field label="Valor (R$)">
          <input className="input" type="number" step="0.01" value={data.plan_price || ""}
                 onChange={(e) => set("plan_price", parseFloat(e.target.value) || null)} />
        </Field>
      </div>

      {/* Telefones */}
      <Field label="Telefones (vinculam o assinante a conversas/chamadas)">
        <div style={{ display: "grid", gap: 8 }}>
          {(data.phones || []).map((p, i) => (
            <div key={i} style={{
              display: "grid",
              gridTemplateColumns: "2fr 1fr auto auto auto",
              gap: 8, alignItems: "center",
              padding: 8, border: "1px solid var(--border-default)", borderRadius: 8,
            }}>
              <input className="input" placeholder="Ex.: 21998176526"
                     value={p.raw_number || ""}
                     onChange={(e) => updPhone(i, "raw_number", e.target.value)}
                     data-testid={`sub-phone-${i}`} />
              <input className="input" placeholder="Rótulo (opcional)"
                     value={p.label || ""}
                     onChange={(e) => updPhone(i, "label", e.target.value)} />
              <label style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
                <input type="checkbox" checked={!!p.is_whatsapp}
                       onChange={(e) => updPhone(i, "is_whatsapp", e.target.checked)} />
                WhatsApp
              </label>
              <label style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
                <input type="checkbox" checked={!!p.is_primary}
                       onChange={(e) => updPhone(i, "is_primary", e.target.checked)} />
                Principal
              </label>
              <button onClick={() => delPhone(i)} className="btn btn-ghost btn-sm"
                      style={{ color: "var(--danger)" }}>
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          <button onClick={addPhone} className="btn btn-secondary btn-sm" type="button"
                  data-testid="sub-add-phone">
            <Plus size={13} /> Adicionar telefone
          </button>
        </div>
      </Field>

      {/* Endereço primário */}
      <Field label="Endereço primário">
        <div style={{ display: "grid", gridTemplateColumns: "3fr 1fr 2fr", gap: 8, marginBottom: 8 }}>
          <input className="input" placeholder="Rua / Logradouro"
                 value={addr.street || ""} onChange={(e) => updAddr("street", e.target.value)} />
          <input className="input" placeholder="Número"
                 value={addr.number || ""} onChange={(e) => updAddr("number", e.target.value)} />
          <input className="input" placeholder="Complemento"
                 value={addr.complement || ""} onChange={(e) => updAddr("complement", e.target.value)} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1.5fr 0.5fr 1fr", gap: 8 }}>
          <input className="input" placeholder="Bairro"
                 value={addr.district || ""} onChange={(e) => updAddr("district", e.target.value)} />
          <input className="input" placeholder="Cidade"
                 value={addr.city || ""} onChange={(e) => updAddr("city", e.target.value)} />
          <input className="input" placeholder="UF" maxLength={2}
                 value={addr.state || ""} onChange={(e) => updAddr("state", e.target.value.toUpperCase())} />
          <input className="input" placeholder="CEP"
                 value={addr.zip_code || ""} onChange={(e) => updAddr("zip_code", e.target.value)} />
        </div>
      </Field>

      <Field label="Observações internas">
        <textarea className="input" rows={3} value={data.notes || ""}
                  onChange={(e) => set("notes", e.target.value)} />
      </Field>

      <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "space-between" }}>
        <div>
          {data.id && (
            <button className="btn btn-ghost" onClick={del} disabled={busy}
                    style={{ color: "var(--danger)" }}
                    data-testid="sub-delete">
              <Trash2 size={13} /> Excluir
            </button>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-ghost" onClick={onCancel}>
            <X size={14} /> Cancelar
          </button>
          <button className="btn btn-primary" onClick={save} disabled={busy}
                  data-testid="sub-save">
            <Save size={14} /> {busy ? "Salvando…" : "Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SubscriberHistory({ subscriber, onClose }) {
  const [history, setHistory] = useState(null);
  useEffect(() => {
    api.subscribersHistory(subscriber.id).then(setHistory);
  }, [subscriber]);

  return (
    <div className="surface" style={{ padding: 22, borderRadius: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>
            Histórico — {subscriber.name}
          </h3>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
            Chamadas e conversas IA vinculadas a este assinante.
          </div>
        </div>
        <button className="btn btn-ghost" onClick={onClose}>
          <X size={14} /> Fechar
        </button>
      </div>

      {!history && <div style={{ padding: 20, textAlign: "center" }}>Carregando…</div>}
      {history && (
        <>
          <h4 style={{ fontSize: 14, marginTop: 12 }}>Chamadas ({history.calls.length})</h4>
          {history.calls.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 8 }}>
              Sem chamadas registradas.
            </div>
          ) : history.calls.map((c) => (
            <div key={c.id} style={{
              padding: 10, border: "1px solid var(--border-default)",
              borderRadius: 8, marginBottom: 8, fontSize: 12,
            }}>
              <strong>{c.direction || "?"}</strong> · {c.status} · {c.started_at}
              {c.agent_name && <> · agente: {c.agent_name}</>}
              {c.summary && <div style={{ marginTop: 4 }}>{c.summary}</div>}
            </div>
          ))}

          <h4 style={{ fontSize: 14, marginTop: 16 }}>Conversas IA ({history.sessions.length})</h4>
          {history.sessions.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 8 }}>
              Sem conversas registradas.
            </div>
          ) : history.sessions.map((s) => (
            <div key={s.session_id} style={{
              padding: 10, border: "1px solid var(--border-default)",
              borderRadius: 8, marginBottom: 8, fontSize: 12,
            }}>
              <strong className="mono">{s.session_id.slice(-12)}</strong>
              · {s.msg_count} msgs · {s.last_at}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function CsvImporter({ onClose }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.subscribersImport(fd);
      setResult(r);
    } catch (e) {
      setResult({ error: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  return (
    <div className="surface" style={{ padding: 22, borderRadius: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
        <h3 style={{ margin: 0 }}>Importar assinantes (CSV)</h3>
        <button className="btn btn-ghost" onClick={onClose}><X size={14} /></button>
      </div>

      <div style={{ background: "var(--info-soft)", color: "var(--info-soft-fg)",
                     padding: 12, borderRadius: 8, fontSize: 12, marginBottom: 14 }}>
        <strong>Colunas esperadas (PT-BR):</strong>
        <code style={{ display: "block", fontFamily: "var(--font-mono, monospace)", marginTop: 4, fontSize: 11 }}>
          nome, documento, codigo_externo, telefone_principal, telefone_2, telefone_3, email, status, plano, velocidade, valor, endereco, numero, complemento, bairro, cidade, estado, cep, observacoes, tags
        </code>
        <div style={{ marginTop: 6 }}>
          Múltiplas tags separe por <code>|</code>. Telefones duplicados em outro assinante geram conflito.
        </div>
      </div>

      <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0])}
             data-testid="sub-csv-input"
             style={{ marginBottom: 12 }} />

      {result && (
        <div style={{
          padding: 12, marginBottom: 12, borderRadius: 8,
          background: result.error ? "var(--danger-soft)" : "var(--success-soft)",
          color: result.error ? "var(--danger-soft-fg)" : "var(--success-soft-fg)",
        }}>
          {result.error ? (
            <span><AlertTriangle size={14} /> {result.error}</span>
          ) : (
            <>
              <CheckCircle2 size={14} style={{ verticalAlign: -2 }} />
              {" "}<strong>{result.created}</strong> criados ·
              <strong> {result.updated}</strong> atualizados ·
              <strong> {result.errors?.length || 0}</strong> erros ·
              <strong> {result.conflicts?.length || 0}</strong> conflitos de telefone
              {result.errors?.length > 0 && (
                <details style={{ marginTop: 8 }}>
                  <summary style={{ cursor: "pointer" }}>Ver erros</summary>
                  <pre style={{ fontSize: 11, maxHeight: 200, overflow: "auto",
                                 marginTop: 4 }}>
                    {result.errors.map((e) => `linha ${e.row}: ${e.error}`).join("\n")}
                  </pre>
                </details>
              )}
            </>
          )}
        </div>
      )}

      <button className="btn btn-primary" onClick={submit} disabled={!file || busy}
              data-testid="sub-csv-submit">
        <Upload size={13} /> {busy ? "Importando…" : "Importar"}
      </button>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: "block", marginTop: 10, marginBottom: 4 }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: "var(--text-secondary)",
        textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4,
      }}>{label}</div>
      {children}
    </label>
  );
}
