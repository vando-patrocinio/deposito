/*
AccessTagsPicker.js — Widget de seleção de tags de acesso por usuário.

UX: dois containers lado a lado — "Disponíveis" (cinza) e "Liberadas" (verde).
Cada tag é uma pílula clicável agrupada por categoria. Click → move a tag
entre as listas. Não usa drag-drop pesado pra funcionar bem no mobile.

Para auditor/administrador, mostra um aviso de que sempre tem todas e
desabilita interação.
*/
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";

export default function AccessTagsPicker({
  selected,            // Array<string> — tags atuais do usuário
  onChange,            // (newTags: string[]) => void
  role,                // string — papel do usuário (auditor/gestor/...)
  disabled = false,
}) {
  const [catalog, setCatalog] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.accessTagsCatalog().then(setCatalog).catch((e) => {
      setErr(e?.response?.data?.detail || e.message);
    });
  }, []);

  const isAllGranted = role === "auditor" || role === "administrador";

  const byCategory = useMemo(() => {
    if (!catalog) return {};
    const acc = {};
    for (const t of catalog.tags) {
      acc[t.category] = acc[t.category] || [];
      acc[t.category].push(t);
    }
    return acc;
  }, [catalog]);

  const sel = useMemo(() => new Set(selected || []), [selected]);

  if (err) return <div style={errBox}>{err}</div>;
  if (!catalog) return <div style={hintBox}>Carregando catálogo de acessos…</div>;

  const toggle = (key) => {
    if (disabled || isAllGranted) return;
    const next = new Set(sel);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(Array.from(next));
  };

  const grantAll = () => {
    if (disabled || isAllGranted) return;
    onChange(catalog.tags.map((t) => t.key));
  };
  const revokeAll = () => {
    if (disabled || isAllGranted) return;
    onChange([]);
  };
  const applyDefault = () => {
    if (disabled || isAllGranted) return;
    onChange(catalog.defaults_by_role[role] || []);
  };

  return (
    <div data-testid="access-tags-picker" style={{ marginTop: 4 }}>
      {isAllGranted ? (
        <div style={infoBox}>
          Usuários com papel <strong>{role}</strong> recebem
          automaticamente acesso a <strong>todos</strong> os módulos. Não é
          necessário (e nem é permitido) restringir tags aqui.
        </div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 6, marginBottom: 10,
                          flexWrap: "wrap" }}>
            <button type="button" onClick={applyDefault} style={btnGhost}
                    data-testid="tags-apply-default">
              ↻ Padrão do papel
            </button>
            <button type="button" onClick={grantAll} style={btnGhost}
                    data-testid="tags-grant-all">
              ✓ Liberar todos
            </button>
            <button type="button" onClick={revokeAll} style={btnGhostRed}
                    data-testid="tags-revoke-all">
              ✕ Remover todos
            </button>
            <div style={{ marginLeft: "auto", fontSize: 11,
                            color: "#475569", alignSelf: "center" }}>
              <strong style={{ color: "#0f766e" }}>{sel.size}</strong>
              {" "}/ {catalog.tags.length} liberadas
            </div>
          </div>

          <div data-testid="tags-categories" style={{ display: "grid", gap: 12 }}>
            {Object.entries(byCategory).map(([cat, items]) => (
              <div key={cat}>
                <div style={catLabel}>{cat}</div>
                <div style={chipsRow}>
                  {items.map((t) => {
                    const active = sel.has(t.key);
                    return (
                      <button key={t.key} type="button"
                              data-testid={`tag-chip-${t.key}`}
                              data-active={active}
                              onClick={() => toggle(t.key)}
                              style={active ? chipActive : chipIdle}
                              title={active
                                ? `Click para remover acesso a "${t.label}"`
                                : `Click para liberar acesso a "${t.label}"`}>
                        <span style={{ fontSize: 13 }}>{t.icon}</span>
                        <span>{t.label}</span>
                        <span style={active ? chipBadgeOn : chipBadgeOff}>
                          {active ? "✓" : "+"}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>

          <div style={hintBox}>
            Clique em qualquer tag para alternar entre <strong>liberada</strong>
            e <strong>não liberada</strong>. As tags controlam quais módulos
            aparecem na barra lateral do usuário.
          </div>
        </>
      )}
    </div>
  );
}

const btnGhost = {
  padding: "5px 10px", fontSize: 11, fontWeight: 600,
  border: "1px solid #cbd5e1", background: "#fff",
  borderRadius: 999, cursor: "pointer", color: "#0f172a",
};
const btnGhostRed = {
  ...btnGhost, borderColor: "#fecaca", color: "#b91c1c",
};
const catLabel = {
  fontSize: 10, fontWeight: 800, color: "#64748b",
  textTransform: "uppercase", letterSpacing: 0.8, marginBottom: 6,
};
const chipsRow = {
  display: "flex", flexWrap: "wrap", gap: 6,
};
const chipBase = {
  display: "inline-flex", alignItems: "center", gap: 6,
  padding: "5px 10px 5px 8px", borderRadius: 999,
  fontSize: 12, fontWeight: 600, cursor: "pointer",
  transition: "all 120ms",
  border: "1px solid",
};
const chipIdle = {
  ...chipBase,
  background: "#f8fafc", borderColor: "#e2e8f0", color: "#475569",
};
const chipActive = {
  ...chipBase,
  background: "#ecfdf5", borderColor: "#10b981", color: "#065f46",
};
const chipBadgeOn = {
  fontSize: 10, fontWeight: 800, color: "#fff",
  background: "#10b981", borderRadius: 999,
  width: 16, height: 16, display: "inline-flex",
  alignItems: "center", justifyContent: "center",
};
const chipBadgeOff = {
  fontSize: 11, fontWeight: 800, color: "#94a3b8",
  width: 16, height: 16, display: "inline-flex",
  alignItems: "center", justifyContent: "center",
};
const infoBox = {
  background: "#fef3c7", color: "#92400e",
  padding: 10, borderRadius: 8, border: "1px solid #fcd34d",
  fontSize: 12, marginTop: 6,
};
const hintBox = {
  marginTop: 10, padding: 8, fontSize: 11, color: "#64748b",
  background: "#f8fafc", borderRadius: 6, border: "1px dashed #cbd5e1",
};
const errBox = {
  padding: 10, background: "#fee2e2", color: "#991b1b",
  borderRadius: 6, fontSize: 12,
};
