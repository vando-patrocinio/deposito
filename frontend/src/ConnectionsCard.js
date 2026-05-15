import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, inputStyle } from "@/ui";
import {
  Link2, ShieldCheck, CircleAlert, ExternalLink, Pencil, Eye, EyeOff,
  Cable, Activity,
} from "lucide-react";

/**
 * Card unificado de TODAS as conexões/integrações do SmartProv.
 * Lista todas, mostra status, permite editar key via modal.
 */
export default function ConnectionsCard() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // integração sendo editada
  const [msg, setMsg] = useState("");

  async function reload() {
    setLoading(true);
    try {
      const r = await api.connectionsList();
      setItems(r.connections || []);
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { reload(); }, []);

  return (
    <>
      <Card title="Conexões / Integrações" style={{ gridColumn: "1 / -1" }}
            data-testid="card-connections">
        <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 12px" }}>
          <Cable size={14} style={{ verticalAlign: "middle" }} /> Todas as integrações
          externas em um só lugar. Clique em <strong>Editar</strong> para alterar credenciais.
        </p>
        {msg && (
          <div style={{ color: "#be123c", fontSize: 13, marginBottom: 10 }}>
            {msg}
          </div>
        )}
        {loading ? (
          <div style={{ color: "#94a3b8" }}>Carregando…</div>
        ) : (
          <div style={{ display: "grid", gap: 0,
                        border: "1px solid #e2e8f0", borderRadius: 10,
                        overflow: "hidden" }}>
            <div style={{
              display: "grid",
              gridTemplateColumns: "1.6fr 1fr 1.4fr 1fr 110px",
              gap: 8, padding: "10px 14px", background: "#f8fafc",
              fontSize: 11, fontWeight: 700, color: "#475569",
              textTransform: "uppercase", letterSpacing: 0.4,
            }}>
              <div>Integração</div>
              <div>Categoria</div>
              <div>Credencial</div>
              <div>Status</div>
              <div style={{ textAlign: "right" }}>Ação</div>
            </div>
            {items.map((c) => (
              <ConnectionRow key={c.id} conn={c}
                             onEdit={() => setEditing(c)} />
            ))}
          </div>
        )}
      </Card>

      {editing && (
        <EditConnectionModal
          conn={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload(); }}
        />
      )}
    </>
  );
}

function ConnectionRow({ conn, onEdit }) {
  const secretField = (conn.fields || []).find((f) => f.secret);
  const maskedSecret = secretField
    ? (conn.values?.[secretField.key] || "—")
    : "—";

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "1.6fr 1fr 1.4fr 1fr 110px",
      gap: 8, padding: "12px 14px",
      borderTop: "1px solid #f1f5f9",
      alignItems: "center",
    }}
    data-testid={`conn-row-${conn.id}`}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 6,
          background: conn.configured ? "#ecfeff" : "#f1f5f9",
          color: conn.configured ? "#0e7490" : "#64748b",
          display: "grid", placeItems: "center",
        }}>
          <Link2 size={14} />
        </div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#0f172a" }}>
            {conn.name}
          </div>
          {conn.doc_url && (
            <a href={conn.doc_url} target="_blank" rel="noreferrer"
               style={{ fontSize: 10, color: "#3b82f6",
                        display: "inline-flex", alignItems: "center", gap: 3 }}>
              docs <ExternalLink size={9} />
            </a>
          )}
        </div>
      </div>
      <div style={{ fontSize: 12, color: "#64748b" }}>{conn.kind}</div>
      <div style={{ fontSize: 12, fontFamily: "monospace",
                    color: conn.configured ? "#0f172a" : "#94a3b8" }}>
        {maskedSecret}
      </div>
      <div>
        {conn.enabled ? (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "3px 8px", borderRadius: 999,
            background: "#dcfce7", color: "#166534",
            fontSize: 11, fontWeight: 700,
          }}>
            <ShieldCheck size={11} /> Ativa
          </span>
        ) : conn.configured ? (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "3px 8px", borderRadius: 999,
            background: "#fef9c3", color: "#854d0e",
            fontSize: 11, fontWeight: 700,
          }}>
            <Activity size={11} /> Configurada
          </span>
        ) : (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "3px 8px", borderRadius: 999,
            background: "#f1f5f9", color: "#64748b",
            fontSize: 11, fontWeight: 700,
          }}>
            <CircleAlert size={11} /> Não config.
          </span>
        )}
      </div>
      <div style={{ textAlign: "right" }}>
        <Button variant="secondary" size="sm" onClick={onEdit}
                data-testid={`conn-edit-${conn.id}`}>
          <Pencil size={12} /> Editar
        </Button>
      </div>
    </div>
  );
}

function EditConnectionModal({ conn, onClose, onSaved }) {
  const [form, setForm] = useState(() => {
    const initial = {};
    (conn.fields || []).forEach((f) => {
      if (f.secret) {
        initial[f.key] = ""; // vazio = manter atual
      } else if (f.type === "boolean") {
        initial[f.key] = !!conn.values?.[f.key];
      } else {
        initial[f.key] = conn.values?.[f.key] || "";
      }
    });
    return initial;
  });
  const [revealed, setRevealed] = useState({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    setBusy(true); setErr("");
    try {
      await api.connectionUpdate(conn.id, form);
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div onClick={onClose}
         style={{
           position: "fixed", inset: 0, zIndex: 1000,
           background: "rgba(2,6,23,0.7)",
           display: "grid", placeItems: "center", padding: 20,
         }}
         data-testid="conn-edit-modal">
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: "#fff", borderRadius: 14,
             padding: 24, maxWidth: 540, width: "100%",
             boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
           }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 14 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700,
                         color: "#0f172a" }}>
              {conn.name}
            </h3>
            <p style={{ margin: "2px 0 0", color: "#64748b", fontSize: 12 }}>
              {conn.kind}
            </p>
          </div>
          <button onClick={onClose} style={{
            background: "transparent", border: "none", fontSize: 24,
            color: "#94a3b8", cursor: "pointer", padding: 0,
          }}>×</button>
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {(conn.fields || []).map((f) => (
            <Field key={f.key} label={f.label}>
              {f.type === "boolean" ? (
                <label style={{ display: "flex", alignItems: "center",
                                gap: 8, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={!!form[f.key]}
                    onChange={(e) =>
                      setForm({ ...form, [f.key]: e.target.checked })}
                    style={{ width: 18, height: 18 }}
                    data-testid={`conn-fld-${f.key}`}
                  />
                  <span style={{ fontSize: 13, color: "#475569" }}>
                    {form[f.key] ? "Ativo" : "Inativo"}
                  </span>
                </label>
              ) : f.secret ? (
                <div style={{ position: "relative" }}>
                  <input
                    type={revealed[f.key] ? "text" : "password"}
                    value={form[f.key]}
                    placeholder={
                      conn.values?.[f.key + "_set"]
                        ? `Salva: ${conn.values[f.key] || "•••"}`
                        : (f.placeholder || "")
                    }
                    onChange={(e) =>
                      setForm({ ...form, [f.key]: e.target.value })}
                    style={{ ...inputStyle, paddingRight: 38 }}
                    data-testid={`conn-fld-${f.key}`}
                  />
                  <button
                    type="button"
                    onClick={() => setRevealed({ ...revealed, [f.key]: !revealed[f.key] })}
                    style={{
                      position: "absolute", right: 8, top: "50%",
                      transform: "translateY(-50%)",
                      background: "transparent", border: "none",
                      color: "#64748b", cursor: "pointer",
                    }}>
                    {revealed[f.key] ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              ) : (
                <input
                  type="text"
                  value={form[f.key]}
                  placeholder={f.placeholder || ""}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  style={inputStyle}
                  data-testid={`conn-fld-${f.key}`}
                />
              )}
              {f.secret && !form[f.key] && conn.values?.[f.key + "_set"] && (
                <small style={{ color: "#94a3b8", fontSize: 11 }}>
                  Deixe vazio para manter a chave atual.
                </small>
              )}
            </Field>
          ))}
        </div>

        {err && (
          <div style={{ marginTop: 12, padding: 10,
                        background: "#fee2e2", color: "#991b1b",
                        borderRadius: 8, fontSize: 12 }}>
            {err}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, marginTop: 18,
                      justifyContent: "flex-end" }}>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancelar
          </Button>
          <Button onClick={save} disabled={busy}
                  data-testid="conn-save-btn">
            {busy ? "Salvando…" : "Salvar"}
          </Button>
        </div>
      </div>
    </div>
  );
}
