import React, { useMemo } from "react";

// IMPORTANT: Os IDs e labels devem refletir ALL_TABS em App.js.
// Quando uma aba nova é adicionada lá, adicionar aqui também.
export const TAB_DEFINITIONS = [
  { id: "dashboard", label: "Painel" },
  { id: "lousa", label: "Lousa" },
  { id: "estoque", label: "Estoque" },
  { id: "ai-center", label: "Central IA" },
  { id: "ai-ranking", label: "Avaliação IA" },
  { id: "central-ia", label: "Central IA" },
  { id: "atendimento", label: "Atendimento" },
  { id: "motor-ia", label: "Motor IA" },
  { id: "cadastro", label: "Cadastro" },
  { id: "subscribers", label: "Assinantes" },
  { id: "plans", label: "Planos" },
  { id: "pracas", label: "Praças" },
  { id: "users", label: "Usuários" },
  { id: "manager", label: "Auditoria" },
  { id: "sheet", label: "Espelho" },
  { id: "logs", label: "Logs" },
  { id: "settings", label: "Configurações" },
  // platform é controlada por superAdminOnly, fora deste card
];

// Default seed quando ainda não há tab_permissions cadastradas.
// Reflete a regra original do App.js antes da customização.
export const DEFAULT_TAB_PERMISSIONS = {
  administrador: TAB_DEFINITIONS.map((t) => t.id),
  auditor: ["dashboard", "ai-center", "ai-ranking", "central-ia", "atendimento", "cadastro", "subscribers", "plans", "pracas", "users",
            "manager", "sheet", "logs", "settings"],
  gestor: ["dashboard", "estoque", "ai-center", "ai-ranking", "central-ia", "atendimento", "cadastro", "subscribers", "plans", "pracas",
           "sheet", "logs"],
};

const ROLES = [
  { id: "administrador", label: "Administrador",
    note: "Acesso total — recomendado manter tudo selecionado." },
  { id: "auditor", label: "Auditor",
    note: "Perfil de fiscalização/observação." },
  { id: "gestor", label: "Gestor",
    note: "Perfil operacional do dia-a-dia." },
];

export default function TabPermissionsCard({ data, setData }) {
  // Migration soft: quando há config salva no banco mas faltam abas criadas
  // DEPOIS (ex.: aihub adicionada após o primeiro save), mergeia com
  // DEFAULT_TAB_PERMISSIONS — abas novas que estão liberadas no default
  // aparecem JÁ TICADAS aqui. Quando o gestor faz qualquer toggle, o estado
  // mergeado é consolidado no banco.
  const perms = useMemo(() => {
    if (!data.tab_permissions) return DEFAULT_TAB_PERMISSIONS;
    const merged = { ...data.tab_permissions };
    for (const role of Object.keys(DEFAULT_TAB_PERMISSIONS)) {
      const defaults = DEFAULT_TAB_PERMISSIONS[role] || [];
      const saved = merged[role] || [];
      const missing = defaults.filter((id) => !saved.includes(id));
      if (missing.length) merged[role] = [...saved, ...missing];
    }
    return merged;
  }, [data.tab_permissions]);

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
    <div data-testid="tab-permissions-card" className="surface" style={{
      marginTop: 16, padding: 16,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 6, flexWrap: "wrap", gap: 6 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.012em" }}>
          Permissões de abas por perfil
        </div>
        <button onClick={reset} data-testid="perm-reset-btn"
                className="btn btn-secondary btn-sm">
          Restaurar padrão
        </button>
      </div>
      <p style={{ fontSize: 12, color: "var(--text-secondary)", margin: "0 0 14px" }}>
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
                  <div style={{ fontWeight: 400, fontSize: 10, color: "var(--text-muted)",
                                 marginTop: 2 }}>{r.note}</div>
                  <div style={{ marginTop: 6, display: "flex", gap: 4, justifyContent: "center" }}>
                    <button onClick={() => setAll(r.id, true)}
                            data-testid={`perm-all-${r.id}`}
                            className="btn btn-ghost btn-sm" style={{ height: 24, padding: "0 8px", fontSize: 10 }}>Tudo</button>
                    <button onClick={() => setAll(r.id, false)}
                            data-testid={`perm-none-${r.id}`}
                            className="btn btn-ghost btn-sm" style={{ height: 24, padding: "0 8px", fontSize: 10 }}>Nada</button>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {TAB_DEFINITIONS.map((t) => (
              <tr key={t.id} style={{ borderTop: "1px solid var(--border-default)" }}>
                <td style={{ padding: "8px 10px", fontWeight: 600, color: "var(--text-primary)" }}>{t.label}</td>
                {ROLES.map((r) => {
                  const checked = (perms[r.id] || []).includes(t.id);
                  return (
                    <td key={r.id} style={{ padding: "8px 10px", textAlign: "center" }}>
                      <input type="checkbox" checked={checked}
                             onChange={() => toggle(r.id, t.id)}
                             data-testid={`perm-${r.id}-${t.id}`}
                             style={{ cursor: "pointer", width: 16, height: 16, accentColor: "var(--accent)" }} />
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
  padding: "8px 10px", fontSize: 11, textAlign: "center",
  background: "var(--bg-surface-2)", color: "var(--text-primary)", fontWeight: 700,
  borderBottom: "1px solid var(--border-default)",
  letterSpacing: "-0.005em",
};
