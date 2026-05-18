import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import { Link2, Copy, Check, Trash2, Plus, RefreshCw, Loader2 } from "lucide-react";

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso.slice(0, 16);
  }
}

function buildPublicLink(token) {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/${token}`;
}

export default function PublicAccessPanel() {
  const [tokens, setTokens] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [creating, setCreating] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [draft, setDraft] = useState({ label: "Quadro Chamados TV", scope: "lousa", expires_in_days: "" });
  const [copiedId, setCopiedId] = useState(null);

  const load = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.publicAccessList();
      setTokens(r.tokens || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro ao carregar tokens");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const create = async () => {
    setCreating(true); setErr("");
    try {
      const payload = {
        label: draft.label.trim(),
        scope: draft.scope.trim() || "lousa",
      };
      if (draft.expires_in_days && Number(draft.expires_in_days) > 0) {
        payload.expires_in_days = Number(draft.expires_in_days);
      }
      await api.publicAccessCreate(payload);
      setShowCreate(false);
      setDraft({ label: "Quadro Chamados TV", scope: "lousa", expires_in_days: "" });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro ao criar token");
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (id) => {
    if (!window.confirm("Revogar este link? Quem estiver usando perderá acesso na hora.")) return;
    try {
      await api.publicAccessRevoke(id);
      await load();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };

  const copy = (id, token) => {
    const link = buildPublicLink(token);
    try {
      navigator.clipboard.writeText(link);
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 1500);
    } catch {
      window.prompt("Copie o link manualmente:", link);
    }
  };

  return (
    <Card
      title="Links Públicos"
      subtitle="Crie URLs sem login para abas específicas (acesso admin completo)."
      action={
        <div style={{ display: "flex", gap: 6 }}>
          <button
            onClick={load} disabled={loading}
            data-testid="public-access-refresh"
            style={{
              padding: "6px 10px", border: "1px solid var(--border, #e2e8f0)",
              background: "var(--surface, #fff)", borderRadius: 8, cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12,
              color: "var(--text-muted, #64748b)",
            }}
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          </button>
          <button
            onClick={() => setShowCreate((v) => !v)}
            data-testid="public-access-new-btn"
            style={{
              padding: "6px 12px", border: 0,
              background: "linear-gradient(90deg, #6366f1, #8b5cf6)",
              color: "#fff", borderRadius: 8, cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12,
              fontWeight: 600,
            }}
          >
            <Plus size={13} /> Novo link
          </button>
        </div>
      }
      data-testid="public-access-panel"
    >
      {err && (
        <div style={{ padding: 10, background: "#fef2f2", color: "#be123c",
                        borderRadius: 8, fontSize: 13, marginBottom: 12 }}>
          {err}
        </div>
      )}

      {showCreate && (
        <div data-testid="public-access-create-panel"
             style={{
               padding: 14, marginBottom: 14,
               background: "var(--surface-2, #f8fafc)",
               border: "1px dashed var(--border, #cbd5e1)",
               borderRadius: 10,
             }}>
          <div style={{ display: "grid",
                          gridTemplateColumns: "2fr 1fr 1fr auto",
                          gap: 10, alignItems: "end" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 4,
                              fontSize: 11, color: "var(--text-muted, #64748b)" }}>
              Descrição (rótulo)
              <input
                type="text"
                value={draft.label}
                onChange={(e) => setDraft((s) => ({ ...s, label: e.target.value }))}
                data-testid="public-access-label-input"
                placeholder="Ex: Quadro Chamados sala técnica"
                style={{
                  padding: "7px 9px", border: "1px solid var(--border, #e2e8f0)",
                  borderRadius: 6, fontSize: 13, background: "var(--surface, #fff)",
                }}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 4,
                              fontSize: 11, color: "var(--text-muted, #64748b)" }}>
              Aba (escopo)
              <select
                value={draft.scope}
                onChange={(e) => setDraft((s) => ({ ...s, scope: e.target.value }))}
                data-testid="public-access-scope-select"
                style={{
                  padding: "7px 9px", border: "1px solid var(--border, #e2e8f0)",
                  borderRadius: 6, fontSize: 13, background: "var(--surface, #fff)",
                }}
              >
                <option value="lousa">Chamados</option>
                <option value="all">Acesso total (admin)</option>
              </select>
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 4,
                              fontSize: 11, color: "var(--text-muted, #64748b)" }}>
              Expira em (dias)
              <input
                type="number"
                min="1"
                max="3650"
                value={draft.expires_in_days}
                onChange={(e) => setDraft((s) => ({ ...s, expires_in_days: e.target.value }))}
                data-testid="public-access-expires-input"
                placeholder="(sem expiração)"
                style={{
                  padding: "7px 9px", border: "1px solid var(--border, #e2e8f0)",
                  borderRadius: 6, fontSize: 13, background: "var(--surface, #fff)",
                }}
              />
            </label>
            <button
              onClick={create} disabled={creating || !draft.label.trim()}
              data-testid="public-access-create-btn"
              style={{
                padding: "8px 14px", border: 0, height: 34,
                background: "linear-gradient(90deg, #10b981, #14b8a6)",
                color: "#fff", borderRadius: 6, cursor: creating ? "wait" : "pointer",
                fontSize: 12, fontWeight: 600, whiteSpace: "nowrap",
              }}
            >{creating ? "Criando..." : "Criar"}</button>
          </div>
          <div style={{ marginTop: 10, padding: 8,
                          background: "rgba(251,191,36,0.12)",
                          color: "#78350f", fontSize: 11.5,
                          borderRadius: 6 }}>
            ⚠️ <strong>Atenção:</strong> qualquer pessoa com o link terá poder de
            administrador na empresa (criar, editar e fechar chamados). Use só com
            quem confia. Revogue quando não precisar mais.
          </div>
        </div>
      )}

      {!loading && tokens.length === 0 && (
        <div style={{ padding: 24, textAlign: "center", fontSize: 13,
                        color: "var(--text-muted, #64748b)" }}>
          Nenhum link público criado ainda. Clique em <strong>Novo link</strong> pra começar.
        </div>
      )}

      {tokens.length > 0 && (
        <div style={{ display: "grid", gap: 10 }} data-testid="public-access-list">
          {tokens.map((t) => {
            const revoked = !!t.revoked_at;
            const expired = t.expires_at && new Date(t.expires_at) < new Date();
            const link = buildPublicLink(t.token);
            return (
              <div key={t.id}
                   data-testid={`public-access-row-${t.id}`}
                   style={{
                     padding: 12,
                     background: revoked || expired
                       ? "var(--surface-2, #f1f5f9)" : "var(--surface, #fff)",
                     border: "1px solid var(--border, #e2e8f0)",
                     borderRadius: 10,
                     opacity: revoked || expired ? 0.55 : 1,
                   }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10,
                                marginBottom: 8 }}>
                  <Link2 size={14} color="#6366f1" />
                  <strong style={{ fontSize: 13, flex: 1,
                                     color: "var(--text-primary, #0f172a)" }}>
                    {t.label}
                  </strong>
                  <span style={{
                    padding: "2px 8px", borderRadius: 12, fontSize: 10,
                    fontWeight: 600, textTransform: "uppercase",
                    background: revoked ? "#fee2e2" : expired ? "#fef3c7" : "#dcfce7",
                    color: revoked ? "#991b1b" : expired ? "#92400e" : "#166534",
                  }}>
                    {revoked ? "Revogado" : expired ? "Expirado" : "Ativo"}
                  </span>
                  {!revoked && !expired && (
                    <button
                      onClick={() => revoke(t.id)}
                      data-testid={`public-access-revoke-${t.id}`}
                      title="Revogar link"
                      style={{
                        padding: 5, border: "1px solid #fca5a5",
                        background: "#fef2f2", color: "#991b1b",
                        borderRadius: 6, cursor: "pointer",
                        display: "inline-flex", alignItems: "center",
                      }}
                    ><Trash2 size={12} /></button>
                  )}
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center",
                                marginBottom: 6 }}>
                  <code style={{
                    flex: 1, padding: "6px 8px",
                    background: "var(--surface-2, #f8fafc)",
                    border: "1px solid var(--border, #e2e8f0)",
                    borderRadius: 6, fontSize: 11.5, color: "#475569",
                    overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }} title={link}>{link}</code>
                  <button
                    onClick={() => copy(t.id, t.token)}
                    disabled={revoked || expired}
                    data-testid={`public-access-copy-${t.id}`}
                    style={{
                      padding: "6px 10px", border: "1px solid var(--border, #e2e8f0)",
                      background: copiedId === t.id ? "#dcfce7" : "var(--surface, #fff)",
                      color: copiedId === t.id ? "#166534" : "var(--text-primary, #0f172a)",
                      borderRadius: 6, cursor: revoked || expired ? "not-allowed" : "pointer",
                      fontSize: 11, fontWeight: 600,
                      display: "inline-flex", alignItems: "center", gap: 4,
                    }}
                  >
                    {copiedId === t.id
                      ? (<><Check size={12} /> Copiado</>)
                      : (<><Copy size={12} /> Copiar</>)}
                  </button>
                </div>
                <div style={{ display: "flex", gap: 14, flexWrap: "wrap",
                                fontSize: 11, color: "var(--text-muted, #64748b)" }}>
                  <span>Escopo: <strong>{t.scope}</strong></span>
                  <span>Criado: {fmtDate(t.created_at)}</span>
                  {t.expires_at && <span>Expira: {fmtDate(t.expires_at)}</span>}
                  <span>Acessos: <strong>{t.use_count || 0}</strong></span>
                  {t.last_used_at && <span>Último uso: {fmtDate(t.last_used_at)}</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
