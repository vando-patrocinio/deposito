import React from "react";

// IMPORTANT: Os IDs e labels devem refletir ALL_TABS em App.js.
// Quando uma aba nova é adicionada lá, adicionar aqui também.
export const TAB_DEFINITIONS = [
  { id: "dashboard", label: "📊 Painel" },
  { id: "lousa", label: "📋 Lousa" },
  { id: "estoque", label: "📦 Estoque" },
  { id: "ai-ranking", label: "🤖 Avaliação IA" },
  { id: "cadastro", label: "👥 Cadastro" },
  { id: "pracas", label: "📍 Praças" },
  { id: "users", label: "🛡️ Usuários" },
  { id: "manager", label: "🛡️ Auditoria" },
  { id: "sheet", label: "📊 Espelho" },
  { id: "logs", label: "📋 Logs" },
  { id: "settings", label: "⚙️ Configurações" },
  // platform é controlada por superAdminOnly, fora deste card
];

// Default seed quando ainda não há tab_permissions cadastradas.
// Reflete a regra original do App.js antes da customização.
export const DEFAULT_TAB_PERMISSIONS = {
  administrador: TAB_DEFINITIONS.map((t) => t.id),
  auditor: ["dashboard", "ai-ranking", "cadastro", "pracas", "users",
            "manager", "sheet", "logs", "settings"],
  gestor: ["dashboard", "estoque", "ai-ranking", "cadastro", "pracas",
           "sheet", "logs"],
};

const ROLES = [
  { id: "administrador", label: "🛡️ Administrador",
    note: "Acesso total — recomendado manter tudo selecionado." },
  { id: "auditor", label: "🔍 Auditor",
    note: "Perfil de fiscalização/observação." },
  { id: "gestor", label: "👔 Gestor",
    note: "Perfil operacional do dia-a-dia." },
];

export default function TabPermissionsCard({ data, setData }) {
  const perms = data.tab_permissions || DEFAULT_TAB_PERMISSIONS;

  const toggle = (role, tabId) => {
    const current = perms[role] || [];
    const next = current.includes(tabId)
      ? current.filter((x) => x !== tabId)
      : [...current, tabId];
    setData({ ...data, tab_permissions: { ...perms, [role]: next } });
  };

  const setAll = (role, on) => {
    setData({
      ...data,
      tab_permissions: {
        ...perms,
        [role]: on ? TAB_DEFINITIONS.map((t) => t.id) : [],
      },
    });
  };

  const reset = () => {
    if (!window.confirm("Restaurar permissões padrão?")) return;
    setData({ ...data, tab_permissions: DEFAULT_TAB_PERMISSIONS });
  };

  return (
    <div data-testid="tab-permissions-card" style={{
      marginTop: 16, padding: 14, background: "#eff6ff",
      borderRadius: 12, border: "1px solid #93c5fd",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 6, flexWrap: "wrap", gap: 6 }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: "#1e3a8a" }}>
          🔐 Permissões de abas por perfil
        </div>
        <button onClick={reset} data-testid="perm-reset-btn"
                style={{ fontSize: 11, padding: "3px 9px", border: "1px solid #93c5fd",
                         background: "white", borderRadius: 6, cursor: "pointer",
                         color: "#1e3a8a", fontWeight: 600 }}>
          ↺ Restaurar padrão
        </button>
      </div>
      <p style={{ fontSize: 11, color: "#1e3a8a", margin: "0 0 10px", opacity: 0.85 }}>
        Marque quais abas cada perfil pode ver no menu. Mudanças aparecem após o usuário
        fazer logout/login. <em>Colaborador usa o app mobile e não tem abas de desktop.</em>
      </p>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ ...thStyle, textAlign: "left" }}>Aba</th>
              {ROLES.map((r) => (
                <th key={r.id} style={thStyle}>
                  <div>{r.label}</div>
                  <div style={{ fontWeight: 400, fontSize: 9, color: "#475569",
                                 marginTop: 2 }}>{r.note}</div>
                  <div style={{ marginTop: 4, display: "flex", gap: 4, justifyContent: "center" }}>
                    <button onClick={() => setAll(r.id, true)}
                            data-testid={`perm-all-${r.id}`}
                            style={miniBtn}>Tudo</button>
                    <button onClick={() => setAll(r.id, false)}
                            data-testid={`perm-none-${r.id}`}
                            style={miniBtn}>Nada</button>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {TAB_DEFINITIONS.map((t) => (
              <tr key={t.id} style={{ borderTop: "1px solid #dbeafe" }}>
                <td style={{ padding: "6px 10px", fontWeight: 600 }}>{t.label}</td>
                {ROLES.map((r) => {
                  const checked = (perms[r.id] || []).includes(t.id);
                  return (
                    <td key={r.id} style={{ padding: "6px 10px", textAlign: "center" }}>
                      <input type="checkbox" checked={checked}
                             onChange={() => toggle(r.id, t.id)}
                             data-testid={`perm-${r.id}-${t.id}`}
                             style={{ cursor: "pointer", width: 18, height: 18 }} />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const thStyle = {
  padding: "6px 10px", fontSize: 11, textAlign: "center",
  background: "#dbeafe", color: "#1e3a8a", fontWeight: 800,
  borderBottom: "1px solid #93c5fd",
};
const miniBtn = {
  fontSize: 10, padding: "2px 6px", border: "1px solid #93c5fd",
  background: "white", borderRadius: 4, cursor: "pointer",
  color: "#1e3a8a", fontWeight: 600,
};
