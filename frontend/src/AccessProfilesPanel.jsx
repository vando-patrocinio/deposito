/**
 * AccessProfilesPanel — "Perfil Usuário"
 * --------------------------------------
 * Substitui parcialmente UsersPanel. Gerencia PERFIS (Colaborador, Gestão,
 * Administrador, Auditor + customizados) com checklist de tags por perfil.
 *
 * CTO 12/06/2026 — pedido: aba "Perfil Usuario" com 4 perfis seed e
 * opção de criar customizados; cada perfil define as tags de acesso.
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

const PAGE = {
  maxWidth: 1200, margin: "0 auto", padding: 20,
  fontFamily: "Inter, system-ui, sans-serif",
};

const SEED_BADGE = {
  display: "inline-block", padding: "2px 8px",
  borderRadius: 999, background: "#0d9488", color: "white",
  fontSize: 9, fontWeight: 800, letterSpacing: ".08em",
  textTransform: "uppercase",
};

const ADMIN_BADGE = {
  display: "inline-block", padding: "2px 8px",
  borderRadius: 999, background: "#dc2626", color: "white",
  fontSize: 9, fontWeight: 800, letterSpacing: ".08em",
  textTransform: "uppercase",
};

const SUPER_ADMIN_BADGE = {
  display: "inline-block", padding: "2px 8px",
  borderRadius: 999,
  background: "linear-gradient(90deg,#facc15 0%,#f59e0b 100%)",
  color: "#7c2d12",
  fontSize: 9, fontWeight: 900, letterSpacing: ".08em",
  textTransform: "uppercase",
  border: "1px solid #b45309",
};

export default function AccessProfilesPanel() {
  const [profiles, setProfiles] = useState([]);
  const [allTags, setAllTags] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState(null);

  async function load() {
    setLoading(true); setError(null);
    try {
      const [ps, tagsResp] = await Promise.all([
        api.accessProfilesList(),
        api.accessTagsCatalog().catch(() => ({ tags: [] })),
      ]);
      setProfiles(ps);
      // accessTagsCatalog retorna { tags, defaults_by_role, current_user_tags }
      setAllTags(Array.isArray(tagsResp) ? tagsResp : (tagsResp?.tags || []));
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  }
  useEffect(() => { load(); }, []);

  async function handleSave(form) {
    try {
      if (form.id) {
        await api.accessProfileUpdate(form.id, {
          name: form.name,
          description: form.description,
          access_tags: form.access_tags,
        });
      } else {
        await api.accessProfileCreate({
          name: form.name,
          description: form.description,
          access_tags: form.access_tags,
        });
      }
      setEditing(null); setShowCreate(false);
      await load();
    } catch (e) {
      alert(e?.response?.data?.detail || "Falha ao salvar perfil");
    }
  }

  async function handleDelete(p) {
    if (!window.confirm(`Excluir perfil "${p.name}"?`)) return;
    try {
      await api.accessProfileDelete(p.id);
      await load();
    } catch (e) {
      alert(e?.response?.data?.detail || "Falha ao excluir");
    }
  }

  async function handleSeed() {
    try {
      await api.accessProfileSeed();
      await load();
    } catch (e) {
      alert(e?.response?.data?.detail || "Falha no seed");
    }
  }

  if (loading) return <div style={PAGE}>Carregando…</div>;
  if (error) return <div style={{ ...PAGE, color: "#dc2626" }}>Erro: {error}</div>;

  return (
    <div style={PAGE} data-testid="access-profiles-panel">
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 18 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 900, margin: 0,
                          letterSpacing: ".01em" }}>Perfil Usuário</h1>
          <p style={{ fontSize: 12.5, color: "#64748b", margin: "4px 0 0",
                       maxWidth: 600 }}>
            Cada perfil define um conjunto de módulos liberados. Colaboradores
            recebem o perfil que define o acesso deles ao sistema.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={handleSeed}
            data-testid="profiles-seed-btn"
            style={btnGhost}
            title="Cria os 4 perfis padrão se ainda não existirem (idempotente)"
          >🔄 Seed padrão</button>
          <button
            onClick={() => setShowCreate(true)}
            data-testid="profiles-create-btn"
            style={btnPrimary}
          >+ Criar perfil</button>
        </div>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))",
        gap: 14,
      }}>
        {profiles.map((p) => (
          <ProfileCard
            key={p.id}
            profile={p}
            allTags={allTags}
            onEdit={() => setEditing(p)}
            onDelete={() => handleDelete(p)}
          />
        ))}
      </div>

      {(showCreate || editing) && (
        <ProfileEditor
          profile={editing}
          allTags={allTags}
          onClose={() => { setShowCreate(false); setEditing(null); }}
          onSave={handleSave}
        />
      )}
    </div>
  );
}

function ProfileCard({ profile, allTags, onEdit, onDelete }) {
  const [expanded, setExpanded] = React.useState(false);
  const tagKeys = profile.access_tags || [];
  const tagsByKey = React.useMemo(() => {
    const m = {};
    for (const t of allTags || []) m[t.key] = t;
    return m;
  }, [allTags]);
  const visible = expanded ? tagKeys : tagKeys.slice(0, 8);
  const hiddenCount = Math.max(0, tagKeys.length - visible.length);

  return (
    <div
      data-testid={`profile-card-${profile.id}`}
      style={{
        background: "white", border: "1px solid #e2e8f0",
        borderRadius: 12, padding: 16,
        boxShadow: "0 1px 3px rgba(15,23,42,.04)",
      }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 15 }}>{profile.name}</strong>
        {profile.is_seed && <span style={SEED_BADGE}>padrão</span>}
        {profile.is_super_admin_profile
          ? <span style={SUPER_ADMIN_BADGE} data-testid={`profile-super-badge-${profile.id}`}>super admin</span>
          : (profile.is_admin_level && <span style={ADMIN_BADGE}>admin</span>)}
      </div>
      <div style={{ fontSize: 12, color: "#64748b", margin: "6px 0 10px",
                      minHeight: 24 }}>
        {profile.description || "—"}
      </div>

      {/* Tags visíveis (chips) */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "baseline", marginBottom: 6 }}>
          <span style={{
            fontSize: 9, fontWeight: 800, color: "#94a3b8",
            letterSpacing: ".08em", textTransform: "uppercase",
          }}>Tags de acesso ({tagKeys.length})</span>
          {hiddenCount > 0 && (
            <button
              onClick={() => setExpanded(true)}
              data-testid={`profile-expand-${profile.id}`}
              style={{
                fontSize: 10, color: "#0d9488",
                background: "none", border: "none", cursor: "pointer",
                padding: 0, fontWeight: 700,
              }}>ver +{hiddenCount}</button>
          )}
          {expanded && tagKeys.length > 8 && (
            <button
              onClick={() => setExpanded(false)}
              style={{
                fontSize: 10, color: "#64748b",
                background: "none", border: "none", cursor: "pointer",
                padding: 0, fontWeight: 700,
              }}>↑ recolher</button>
          )}
        </div>
        {tagKeys.length === 0 ? (
          <div style={{ fontSize: 11, color: "#94a3b8", fontStyle: "italic",
                          padding: 8, background: "#f8fafc",
                          borderRadius: 6, textAlign: "center" }}>
            sem tags — clique em Editar para liberar módulos
          </div>
        ) : (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {visible.map((k) => {
              const t = tagsByKey[k];
              return (
                <span
                  key={k}
                  title={t ? `${t.label} (${t.category})` : k}
                  style={{
                    padding: "2px 8px", borderRadius: 999,
                    background: "#f0fdfa", border: "1px solid #99f6e4",
                    color: "#0f766e", fontSize: 10, fontWeight: 600,
                    display: "inline-flex", alignItems: "center", gap: 4,
                  }}
                >
                  {t?.icon} {t?.label || k}
                </span>
              );
            })}
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 14, fontSize: 11, color: "#475569",
                      borderTop: "1px solid #f1f5f9", paddingTop: 10 }}>
        <div>
          <span style={{ color: "#94a3b8" }}>Usuários</span>{" "}
          <strong style={{ fontSize: 14, color: "#0f172a" }}>
            {profile.user_count ?? 0}
          </strong>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button onClick={onEdit} style={btnSoft}
                    data-testid={`profile-edit-${profile.id}`}>
            ⚙ Editar tags
          </button>
          {!profile.is_seed && (
            <button onClick={onDelete} style={btnDanger}
                      data-testid={`profile-delete-${profile.id}`}>
              🗑
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ProfileEditor({ profile, allTags, onClose, onSave }) {
  const [name, setName] = useState(profile?.name || "");
  const [description, setDescription] = useState(profile?.description || "");
  const [selectedTags, setSelectedTags] = useState(
    new Set(profile?.access_tags || []),
  );

  const byCategory = {};
  for (const t of allTags) {
    const cat = t.category || "Outros";
    (byCategory[cat] = byCategory[cat] || []).push(t);
  }

  function toggle(key) {
    const next = new Set(selectedTags);
    if (next.has(key)) next.delete(key); else next.add(key);
    setSelectedTags(next);
  }

  function selectAll() {
    setSelectedTags(new Set(allTags.map((t) => t.key)));
  }
  function clearAll() {
    setSelectedTags(new Set());
  }

  return (
    <div
      data-testid="profile-editor-modal"
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 20,
      }}
      onClick={onClose}
    >
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 12, padding: 20,
        width: "min(820px, 96vw)", maxHeight: "92vh", overflowY: "auto",
        boxShadow: "0 24px 60px rgba(0,0,0,.35)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        marginBottom: 14 }}>
          <h2 style={{ fontSize: 18, fontWeight: 800, margin: 0 }}>
            {profile ? `Editar perfil: ${profile.name}` : "Novo perfil"}
          </h2>
          <button onClick={onClose} style={btnGhost}
                    data-testid="profile-editor-close">Fechar ✕</button>
        </div>

        <div style={{ display: "grid", gap: 10, marginBottom: 16 }}>
          <label style={{ display: "block" }}>
            <span style={lblStyle}>Nome</span>
            <input
              data-testid="profile-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={inputStyle}
              disabled={profile?.is_seed}
              placeholder="ex.: Supervisor de Campo"
            />
            {profile?.is_seed && (
              <small style={{ color: "#94a3b8" }}>
                Nome dos perfis padrão é fixo.
              </small>
            )}
          </label>
          <label style={{ display: "block" }}>
            <span style={lblStyle}>Descrição</span>
            <input
              data-testid="profile-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              style={inputStyle}
              placeholder="Para que serve este perfil"
            />
          </label>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", marginBottom: 8 }}>
          <h3 style={{ fontSize: 14, fontWeight: 800, margin: 0 }}>
            Tags de acesso ({selectedTags.size}/{allTags.length})
          </h3>
          <div style={{ display: "flex", gap: 6 }}>
            <button onClick={selectAll} style={btnGhost}
                      data-testid="profile-tags-all">Marcar todas</button>
            <button onClick={clearAll} style={btnGhost}
                      data-testid="profile-tags-none">Limpar</button>
          </div>
        </div>

        {Object.entries(byCategory).map(([cat, tags]) => (
          <div key={cat} style={{ marginBottom: 12 }}>
            <div style={{
              fontSize: 10, fontWeight: 800, color: "#94a3b8",
              letterSpacing: ".08em", textTransform: "uppercase",
              marginBottom: 6,
            }}>{cat}</div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {tags.map((t) => {
                const on = selectedTags.has(t.key);
                return (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => toggle(t.key)}
                    data-testid={`profile-tag-${t.key}`}
                    style={{
                      padding: "5px 10px", borderRadius: 999,
                      fontSize: 11, fontWeight: 600, cursor: "pointer",
                      border: on ? "1px solid #0d9488" : "1px solid #e2e8f0",
                      background: on ? "#0d9488" : "white",
                      color: on ? "white" : "#475569",
                    }}
                  >{t.icon} {t.label}</button>
                );
              })}
            </div>
          </div>
        ))}

        <div style={{ display: "flex", justifyContent: "flex-end",
                        gap: 8, marginTop: 16, paddingTop: 14,
                        borderTop: "1px solid #f1f5f9" }}>
          <button onClick={onClose} style={btnGhost}>Cancelar</button>
          <button
            data-testid="profile-save-btn"
            onClick={() => onSave({
              id: profile?.id, name, description,
              access_tags: Array.from(selectedTags),
            })}
            style={btnPrimary}
            disabled={!name.trim()}
          >Salvar</button>
        </div>
      </div>
    </div>
  );
}

const lblStyle = {
  fontSize: 10, fontWeight: 800, color: "#94a3b8",
  letterSpacing: ".08em", textTransform: "uppercase",
  marginBottom: 4, display: "block",
};
const inputStyle = {
  width: "100%", padding: "8px 12px",
  border: "1px solid #cbd5e1", borderRadius: 6,
  fontSize: 13, marginTop: 4,
};
const btnPrimary = {
  padding: "8px 16px", background: "#0d9488", color: "white",
  border: "none", borderRadius: 8,
  fontWeight: 700, fontSize: 13, cursor: "pointer",
};
const btnGhost = {
  padding: "7px 14px", background: "white", color: "#475569",
  border: "1px solid #cbd5e1", borderRadius: 8,
  fontWeight: 600, fontSize: 12, cursor: "pointer",
};
const btnSoft = {
  padding: "6px 12px", background: "#f1f5f9", color: "#0f172a",
  border: "1px solid #e2e8f0", borderRadius: 6,
  fontWeight: 600, fontSize: 12, cursor: "pointer",
};
const btnDanger = {
  padding: "6px 12px", background: "#fee2e2", color: "#991b1b",
  border: "1px solid #fecaca", borderRadius: 6,
  fontWeight: 600, fontSize: 12, cursor: "pointer",
};
