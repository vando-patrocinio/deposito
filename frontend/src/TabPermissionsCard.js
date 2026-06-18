import React, { useMemo } from "react";

// ============================================================
// IMPORTANT: Os IDs e labels devem refletir ALL_TABS em App.js.
// Quando uma aba nova é adicionada lá, adicionar aqui também.
//
// Estrutura agrupada (mesma ordem do menu lateral) para facilitar
// visualização. `group` é meramente visual — backend só lê o array
// chato de tab_ids por role.
// ============================================================
export const TAB_DEFINITIONS = [
  // Dashboard Executivo
  { id: "watchtower", label: "Watchtower",
    group: "Dashboard Executivo",
    hint: "Painéis executivos: IA Presidente, Relacionamento, Recebimentos, Patrimônio, Estoque (sub-abas internas)." },

  // Operação
  { id: "dashboard",       label: "Painel",            group: "Operação" },
  { id: "lousa",           label: "Chamados",          group: "Operação" },
  { id: "estoque",         label: "Movimento",         group: "Operação" },
  { id: "central-compras", label: "Central de Compras", group: "Operação",
    hint: "Almoxarifes da praça veem só a própria; gestores veem todas." },
  { id: "projects",        label: "Acompanhamento",    group: "Operação",
    hint: "Kanban de projetos/obras: início, término, laudos PDF/DOC." },

  // Projetos
  { id: "projetos",        label: "Projetos",          group: "Projetos" },
  { id: "propostas",       label: "Propostas (IA)",    group: "Projetos",
    hint: "Geração de propostas comerciais com IA." },

  // Frota
  { id: "fleet",           label: "Gestão de Frota",   group: "Frota" },

  // Inteligência
  { id: "ai-ranking",      label: "Avaliação IA",      group: "Inteligência" },
  { id: "ai-corrections",  label: "Correções IA",      group: "Inteligência" },
  { id: "central-ia",      label: "Central IA",        group: "Inteligência" },
  { id: "rede-ia",         label: "Rede IA",           group: "Inteligência" },
  { id: "atendimento",     label: "Atendimento IA",    group: "Inteligência" },
  { id: "alvaro-ia",       label: "Alvaro IA",         group: "Inteligência" },
  { id: "mass-messaging",  label: "Disparo em Massa",  group: "Inteligência" },
  { id: "sales-funnel",    label: "Funil de Vendas",   group: "Inteligência" },

  // Cadastro
  { id: "cadastro",        label: "Colaboradores",     group: "Cadastro" },
  { id: "subscribers",     label: "Assinantes",        group: "Cadastro" },
  { id: "plans",           label: "Planos",            group: "Cadastro" },
  { id: "pracas",          label: "Praças",            group: "Cadastro" },

  // Relatórios
  { id: "manager",         label: "Auditoria",         group: "Relatórios" },
  { id: "logs",            label: "Logs",              group: "Relatórios" },

  // RH
  { id: "sheet",           label: "Espelho de Ponto",  group: "RH" },
  { id: "holerite",        label: "Holerite",          group: "RH" },
  { id: "feriados",        label: "Feriados",          group: "RH" },

  // Financeiro
  { id: "financeiro",      label: "Financeiro",        group: "Financeiro",
    superAdminOnly: true,
    hint: "Mesmo marcado, só aparece para usuários com tik Super Admin." },
  { id: "billing",         label: "Faturamento",       group: "Financeiro",
    hint: "Geração de faturas, régua de cobrança e dunning (substitui o Atlaz)." },

  // Comercial
  { id: "budget",          label: "Orçamento",         group: "Comercial" },

  // Sistema
  { id: "users",           label: "Usuários",          group: "Sistema" },
  { id: "motor-ia",        label: "Motor IA",          group: "Sistema" },
  { id: "settings",        label: "Configurações",     group: "Sistema" },
  { id: "platform",        label: "Plataforma",        group: "Sistema" },
];

const ALL_TAB_IDS = TAB_DEFINITIONS.map((t) => t.id);

// Default seed quando ainda não há tab_permissions cadastradas.
// REGRA: Auditor tem acesso TOTAL (fiscalização sem restrição) — igual ao administrador
//        E inclui a aba Plataforma (gestão SaaS cross-tenant).
//        Gestor tem acesso operacional (sem Auditoria/Usuários/Motor IA/Settings/Plataforma).
export const DEFAULT_TAB_PERMISSIONS = {
  administrador: [...ALL_TAB_IDS],
  auditor:       [...ALL_TAB_IDS],
  gestor: [
    "watchtower",
    "dashboard", "lousa", "estoque", "central-compras", "projects",
    "ai-ranking", "ai-corrections", "central-ia", "rede-ia",
    "atendimento", "alvaro-ia", "mass-messaging", "sales-funnel",
    "cadastro", "subscribers", "plans", "pracas",
    "logs",
    "sheet", "feriados",
    "budget", "fleet",
  ],
};

const ROLES = [
  { id: "administrador", label: "Administrador",
    note: "Acesso total — recomendado manter tudo selecionado." },
  { id: "auditor", label: "Auditor",
    note: "Fiscalização. Acesso total a tudo (read + write)." },
  { id: "gestor", label: "Gestor",
    note: "Operacional do dia-a-dia (sem Auditoria/Usuários/Sistema)." },
];

export default function TabPermissionsCard({ data, setData }) {
  // Quando NÃO HÁ config salva ainda (1ª vez), usa defaults completos.
  // Quando JÁ HÁ config salva, respeita exatamente o que está no banco
  // (não re-mescla com defaults — senão impede o gestor de DESMARCAR abas
  // que estão no default).
  // Para abas NOVAS criadas após a 1ª configuração, exibimos com checkbox
  // desmarcado por padrão; o gestor decide ativar se quiser.
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
        [role]: on ? [...ALL_TAB_IDS] : [],
      },
    });
  };

  const reset = async () => {
    if (!await window.confirm("Restaurar permissões padrão?")) return;
    setData({ ...data, tab_permissions: DEFAULT_TAB_PERMISSIONS });
  };

  // Agrupa as tabs por seção, mantendo a ordem original.
  const grouped = useMemo(() => {
    const out = [];
    let lastGroup = null;
    for (const t of TAB_DEFINITIONS) {
      if (t.group !== lastGroup) {
        out.push({ kind: "header", group: t.group });
        lastGroup = t.group;
      }
      out.push({ kind: "tab", tab: t });
    }
    return out;
  }, []);

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
        Marque quais abas cada perfil pode ver no menu. Mudanças aparecem após o
        usuário fazer logout/login.{" "}
        <em>Colaborador usa o app mobile e não tem abas de desktop.</em>{" "}
        <em>Auditor tem acesso total por padrão (fiscalização).</em>
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
            {grouped.map((row, idx) => {
              if (row.kind === "header") {
                return (
                  <tr key={`grp-${row.group}-${idx}`}
                      data-testid={`perm-group-${row.group}`}>
                    <td colSpan={1 + ROLES.length}
                        style={{
                          padding: "10px 10px 4px",
                          fontSize: 10,
                          fontWeight: 700,
                          textTransform: "uppercase",
                          letterSpacing: ".06em",
                          color: "var(--text-muted)",
                          background: "var(--bg-surface-2)",
                          borderTop: "1px solid var(--border-default)",
                        }}>
                      {row.group}
                    </td>
                  </tr>
                );
              }
              const t = row.tab;
              return (
                <tr key={t.id} style={{ borderTop: "1px solid var(--border-default)" }}>
                  <td style={{ padding: "8px 10px", fontWeight: 600, color: "var(--text-primary)" }}>
                    {t.label}
                    {t.superAdminOnly && (
                      <span title={t.hint || "Apenas Super Admin"}
                            data-testid={`perm-superadmin-tag-${t.id}`}
                            style={{
                              marginLeft: 8, fontSize: 9, fontWeight: 800,
                              padding: "2px 6px", borderRadius: 999,
                              background: "#0f172a", color: "#facc15",
                              letterSpacing: ".04em",
                            }}>
                        ⭐ SUPER ADMIN
                      </span>
                    )}
                    {t.hint && (
                      <div style={{ fontSize: 10, color: "#94a3b8",
                                     marginTop: 2, fontStyle: "italic" }}>
                        {t.hint}
                      </div>
                    )}
                  </td>
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
              );
            })}
          </tbody>
        </table>
      </div>

      <p style={{ fontSize: 11, color: "var(--text-muted)", margin: "12px 0 0",
                  lineHeight: 1.6 }}>
        <strong>Total de {ALL_TAB_IDS.length} abas</strong> disponíveis.{" "}
        Perfis específicos como <em>gestor_rede</em> e <em>financeiro</em>{" "}
        usam permissões hardcoded no App.js (não controlados por este card).
      </p>
    </div>
  );
}

const thStyle = {
  padding: "8px 10px", fontSize: 11, textAlign: "center",
  background: "var(--bg-surface-2)", color: "var(--text-primary)", fontWeight: 700,
  borderBottom: "1px solid var(--border-default)",
  letterSpacing: "-0.005em",
};
