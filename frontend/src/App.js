import React, { useEffect, useMemo, useState } from "react";
import "@/App.css";
import {
  Smartphone, LogOut, ChevronRight, ChevronDown, Brain, BarChart3, Layout,
  Boxes, Sparkles, Users, MapPin, ShieldCheck, ClipboardList,
  FileSpreadsheet, History as HistoryIcon, Settings as SettingsIcon,
  Building2, Eye, EyeOff, Sun, Moon, Bot, UserCircle, MessageCircle, Cpu,
  Receipt, CalendarDays, Wand2, DollarSign, Megaphone, Calculator,
  ShoppingCart,
} from "lucide-react";
import CollaboratorApp from "@/CollaboratorApp";
import CadastroPanel from "@/CadastroPanel";
import LeaderboardMural from "@/LeaderboardMural";
import TvHub from "@/TvHub";
import SubscribersPanel from "@/SubscribersPanel";
import PlansPanel from "@/PlansPanel";
import ManagerPanel from "@/ManagerPanel";
import TimesheetView from "@/TimesheetView";
import HoleritePanel from "@/HoleritePanel";
import HoleriteViewer from "@/HoleriteViewer";
import FeriadosPanel from "@/FeriadosPanel";
import SettingsPanel from "@/SettingsPanel";
import FinanceiroPanel from "@/FinanceiroPanel";
import BudgetPanel from "@/BudgetPanel";
import RedeIaPanel from "@/RedeIaPanel";
import { DEFAULT_TAB_PERMISSIONS as _DEFAULT_TAB_PERMS } from "@/TabPermissionsCard";
import AlvaroPanel from "@/AlvaroPanel";
import MassMessagingPanel from "@/MassMessagingPanel";
import MotorIaCard from "@/MotorIaCard";
import MotorIaUsageCard from "@/MotorIaUsageCard";
import MotorIaBudgetCard from "@/MotorIaBudgetCard";
import BudgetAlertBadge from "@/BudgetAlertBadge";
import AiTopologyCard from "@/AiTopologyCard";
import UsersPanel from "@/UsersPanel";
import DashboardPanel from "@/DashboardPanel";
import PracasPanel from "@/PracasPanel";
import LogsPanel from "@/LogsPanel";
import PlatformAdminPanel from "@/PlatformAdminPanel";
import BlockedPage from "@/BlockedPage";
import DialogHost from "@/dialog";
import DialogHistoryPanel from "@/DialogHistoryPanel";
import LousaAdminPanel from "@/LousaAdminPanel";
import EstoquePanel from "@/EstoquePanel";
import CentralComprasPanel from "@/CentralComprasPanel";
import AICenterPanel from "@/AICenterPanel";
import AiRankingPanel from "@/AiRankingPanel";
import AiCorrectionsPanel from "@/AiCorrectionsPanel";
import AIHubPanel from "@/AIHubPanel";
import CentralIaDashboard from "@/CentralIaDashboard";
import NotificationsBell from "@/NotificationsBell";
import OfflineTimeBanner from "@/OfflineTimeBanner";
import ServerClock from "@/ServerClock";
import { startServerTime } from "@/serverTime";
import LoginPage from "@/LoginPage";
import LandingPage from "@/LandingPage";
import SignupPage from "@/SignupPage";
import OnboardingWizard from "@/OnboardingWizard";
import { BillingBanner, BillingCancelPage, BillingSuccessPage } from "@/BillingPage";
import { AuthProvider, hasRole, useAuth } from "@/AuthContext";

function useMobileMode() {
  const detect = () => {
    if (typeof window === "undefined") return false;
    const params = new URLSearchParams(window.location.search);
    if (params.get("mode") === "app" || params.get("mode") === "mobile") return true;
    if (params.get("cid")) return true;
    if (params.get("mode") === "desktop") return false;
    if (typeof sessionStorage !== "undefined") {
      const ov = sessionStorage.getItem("ponto_mode");
      if (ov === "app") return true;
      if (ov === "desktop") return false;
    }
    const standalone = window.matchMedia?.("(display-mode: standalone)")?.matches || window.navigator.standalone === true;
    if (standalone) return true;
    const isTouch = window.matchMedia?.("(pointer: coarse)")?.matches;
    const narrow = window.innerWidth <= 820;
    return Boolean(isTouch && narrow);
  };
  const [mobile, setMobile] = useState(detect);
  useEffect(() => {
    const onResize = () => setMobile(detect());
    const onStorage = () => setMobile(detect());
    window.addEventListener("resize", onResize);
    window.addEventListener("storage", onStorage);
    window.addEventListener("ponto-mode-changed", onStorage);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("ponto-mode-changed", onStorage);
    };
  }, []);
  return mobile;
}

function setSessionMode(mode) {
  try {
    if (mode) sessionStorage.setItem("ponto_mode", mode);
    else sessionStorage.removeItem("ponto_mode");
    window.dispatchEvent(new Event("ponto-mode-changed"));
  } catch { /* ignore */ }
}

/* Theme (light/dark) — persisted in localStorage, applied on <html> */
function useTheme() {
  const getInitial = () => {
    if (typeof window === "undefined") return "light";
    const saved = localStorage.getItem("ponto_theme");
    if (saved === "dark" || saved === "light") return saved;
    return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
  };
  const [theme, setTheme] = useState(getInitial);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    try { localStorage.setItem("ponto_theme", theme); } catch { /* ignore */ }
  }, [theme]);
  const toggle = () => setTheme((t) => (t === "dark" ? "light" : "dark"));
  return { theme, toggle };
}

/* ------------------------------------------------------------
   Sidebar navigation — categorized, sober
------------------------------------------------------------ */
/* ============================================================
   Navegação — nomenclatura alinhada com o padrão ISP (Atlaz/Voalle/SGP)
   ============================================================ */
const NAV_GROUPS = [
  {
    label: "Operação",
    items: [
      { id: "dashboard", icon: BarChart3, label: "Painel", roles: ["gestor", "auditor", "administrador"] },
      { id: "lousa", icon: Layout, label: "Chamados", roles: ["administrador"] },
      { id: "estoque", icon: Boxes, label: "Movimento", roles: ["gestor", "administrador"] },
      { id: "central-compras", icon: ShoppingCart, label: "Central de Compras",
        roles: ["gestor", "administrador", "colaborador"] },
    ],
  },
  {
    label: "Inteligência",
    items: [
      { id: "ai-ranking", icon: Sparkles, label: "Avaliação IA", roles: ["gestor", "auditor", "administrador"] },
      { id: "ai-corrections", icon: Wand2, label: "Correções IA", roles: ["gestor", "auditor", "administrador"] },
      { id: "central-ia", icon: Brain, label: "Central IA", roles: ["gestor", "auditor", "administrador"] },
      { id: "rede-ia", icon: Brain, label: "Rede IA", roles: ["gestor", "auditor", "administrador", "gestor_rede"] },
      { id: "atendimento", icon: MessageCircle, label: "Atendimento IA", roles: ["gestor", "auditor", "administrador", "colaborador"], requires: "can_attend_whatsapp" },
      { id: "alvaro-ia", icon: Brain, label: "Alvaro IA", roles: ["gestor", "auditor", "administrador"] },
      { id: "mass-messaging", icon: Megaphone, label: "Disparo em Massa", roles: ["gestor", "auditor", "administrador"] },
    ],
  },
  {
    label: "Cadastro",
    items: [
      { id: "cadastro", icon: Users, label: "Colaboradores", roles: ["gestor", "auditor", "administrador"] },
      {
        id: "clientes",
        icon: UserCircle,
        label: "Clientes",
        roles: ["gestor", "auditor", "administrador"],
        children: [
          { id: "subscribers", label: "Assinantes" },
          { id: "plans", label: "Planos" },
        ],
      },
      { id: "pracas", icon: MapPin, label: "Praças", roles: ["gestor", "auditor", "administrador"] },
    ],
  },
  {
    label: "Relatórios",
    items: [
      { id: "manager", icon: ClipboardList, label: "Auditoria", roles: ["auditor", "administrador"] },
      { id: "logs", icon: HistoryIcon, label: "Logs", roles: ["gestor", "auditor", "administrador"] },
    ],
  },
  {
    label: "RH",
    items: [
      {
        id: "espelho",
        icon: FileSpreadsheet,
        label: "Ponto",
        roles: ["gestor", "auditor", "administrador"],
        children: [
          { id: "sheet", label: "Espelho" },
        ],
      },
      { id: "holerite", icon: Receipt, label: "Holerite",
        roles: ["gestor", "auditor", "administrador"] },
      { id: "feriados", icon: CalendarDays, label: "Feriados",
        roles: ["gestor", "auditor", "administrador"] },
    ],
  },
  {
    label: "Financeiro",
    items: [
      // Aba Financeiro: visível APENAS para super admin (decisão de produto).
      // O TIK "Super Admin" no card de Usuários é controlado pelo Vando.
      { id: "financeiro", icon: DollarSign, label: "Financeiro",
        roles: ["auditor", "administrador", "financeiro"],
        superAdminOnly: true },
    ],
  },
  {
    label: "Comercial",
    items: [
      { id: "budget", icon: Calculator, label: "Orçamento",
        roles: ["administrador", "gestor", "financeiro"] },
    ],
  },
  {
    label: "Sistema",
    items: [
      { id: "users", icon: ShieldCheck, label: "Usuários", roles: ["auditor", "administrador"] },
      { id: "motor-ia", icon: Cpu, label: "Motor IA", roles: ["administrador"] },
      { id: "settings", icon: SettingsIcon, label: "Configurações", roles: ["auditor", "administrador"] },
      { id: "platform", icon: Building2, label: "Plataforma", roles: ["auditor", "administrador"] },
    ],
  },
];

const ALL_TABS = NAV_GROUPS.flatMap((g) => g.items.flatMap((it) => (
  it.children?.length
    ? [it, ...it.children.map((c) => ({ ...c, roles: c.roles || it.roles }))]
    : [it]
)));

function ImpersonationBanner() {
  const { user, isImpersonating, endImpersonation } = useAuth();
  if (!isImpersonating || !user) return null;
  const imp = user.impersonator;  return (
    <div
      data-testid="impersonation-banner"
      style={{
        background: "var(--warning-soft)",
        color: "var(--warning-soft-fg)",
        border: "1px solid #fcd34d",
        padding: "10px 14px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        flexWrap: "wrap",
        borderRadius: 10,
        marginBottom: 14,
        fontSize: 13,
      }}
    >
      <Eye size={16} strokeWidth={1.75} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <strong style={{ fontWeight: 700 }}>Modo drill-down — agindo como {user.name} ({user.role})</strong>
        <div style={{ fontSize: 12, opacity: 0.85, marginTop: 1 }}>
          Sessão original: <span className="mono">{imp?.email}</span> · ações registradas
        </div>
      </div>
      <button
        data-testid="end-impersonation-btn"
        onClick={async () => {
          try { await endImpersonation(); }
          catch (e) { await window.alert("Erro: " + (e?.response?.data?.detail || e.message)); }
        }}
        className="btn btn-secondary btn-sm"
      >
        <EyeOff size={14} strokeWidth={1.75} /> Sair do modo
      </button>
    </div>
  );
}

function PublicAccessBanner() {
  const { isPublicAccess } = useAuth();
  if (!isPublicAccess) return null;
  const onExit = () => {
    try {
      window.localStorage.removeItem("smartprov_public_token");
    } catch { /* ignore */ }
    window.location.replace("/login");
  };
  return (
    <div
      data-testid="public-access-banner"
      style={{
        background: "linear-gradient(90deg, #fef3c7, #fde68a)",
        color: "#78350f",
        border: "1px solid #fbbf24",
        padding: "8px 14px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        borderRadius: 10,
        marginBottom: 14,
        fontSize: 13,
      }}
    >
      <span aria-hidden style={{ fontSize: 16 }}>🔓</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <strong style={{ fontWeight: 700 }}>Acesso público ativo</strong>
        <div style={{ fontSize: 11.5, opacity: 0.85, marginTop: 1 }}>
          Você está acessando via link compartilhado (sem login). Ações ficam
          registradas no log.
        </div>
      </div>
      <button
        data-testid="exit-public-access-btn"
        onClick={onExit}
        className="btn btn-secondary btn-sm"
      >
        Sair do modo
      </button>
    </div>
  );
}

function SidebarNav({ activeTabs, view, setView, brand, isSuperAdmin, onOpenModal, isOpen, onClose }) {
  // Items pais expansíveis: começam fechados; abrem quando clicados ou
  // quando o view atual pertence a um filho.
  const [expandedParents, setExpandedParents] = useState(() => new Set());
  useEffect(() => {
    // auto-expand do pai quando view atual é filho
    NAV_GROUPS.forEach((g) => {
      g.items.forEach((it) => {
        if (it.children?.some((c) => c.id === view)) {
          setExpandedParents((prev) => new Set(prev).add(it.id));
        }
      });
    });
  }, [view]);
  const toggleParent = (id) => {
    setExpandedParents((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  return (
    <>
      {/* Overlay mobile — clica fora fecha o drawer */}
      {isOpen && (
        <div
          data-testid="sidebar-overlay"
          onClick={onClose}
          style={{
            position: "fixed", inset: 0, background: "rgba(15,23,42,.55)",
            zIndex: 40, display: "none",
          }}
          className="app-sidebar__overlay"
        />
      )}
      <aside className={`app-sidebar ${isOpen ? "is-open" : ""}`} aria-label="Navegação principal">
        <div className="app-sidebar__brand">
          <img src="/smartprov_icon.png" alt="SmartProv"
                className="app-sidebar__brand-logo"
                style={{ width: 32, height: 32, objectFit: "contain",
                          background: "transparent" }} />
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="app-sidebar__brand-name">SmartProv</div>
            <div className="app-sidebar__brand-tag">{brand || "Operações ISP"}</div>
          </div>
        </div>
      <nav className="app-sidebar__nav">
        {NAV_GROUPS.map((group) => {
          // Item pai com children é visível se ele OU algum filho está em activeTabs.
          const visible = group.items.filter((it) => {
            if (it.children?.length) {
              return it.children.some((c) => activeTabs.some((t) => t.id === c.id));
            }
            return activeTabs.some((t) => t.id === it.id);
          });
          if (visible.length === 0) return null;
          return (
            <div className="app-sidebar__group" key={group.label}>
              <div className="app-sidebar__group-title">{group.label}</div>
              {visible.map((it) => {
                const Ico = it.icon;
                const hasChildren = it.children?.length > 0;
                const isExpanded = expandedParents.has(it.id);
                const childActive = hasChildren && it.children.some((c) => c.id === view);
                const active = !it.asModal && !hasChildren && view === it.id;
                const handleClick = () => {
                  if (it.asModal) onOpenModal?.(it.id);
                  else if (hasChildren) toggleParent(it.id);
                  else setView(it.id);
                  if (!hasChildren) onClose?.();
                };
                return (
                  <React.Fragment key={it.id}>
                    <button
                      className={`app-sidebar__link ${active || childActive ? "is-active" : ""}`}
                      onClick={handleClick}
                      data-testid={`tab-${it.id}`}
                      aria-current={active ? "page" : undefined}
                      aria-expanded={hasChildren ? isExpanded : undefined}
                    >
                      <Ico size={16} strokeWidth={1.75} />
                      <span style={{ flex: 1, textAlign: "left" }}>{it.label}</span>
                      {hasChildren ? (
                        isExpanded
                          ? <ChevronDown size={14} strokeWidth={1.75} style={{ opacity: 0.6 }} />
                          : <ChevronRight size={14} strokeWidth={1.75} style={{ opacity: 0.6 }} />
                      ) : active && (
                        <ChevronRight size={14} strokeWidth={1.75} style={{ opacity: 0.6 }} />
                      )}
                    </button>
                    {hasChildren && isExpanded && it.children.map((c) => {
                      const childAvail = activeTabs.some((t) => t.id === c.id);
                      if (!childAvail) return null;
                      const cActive = view === c.id;
                      return (
                        <button
                          key={c.id}
                          className={`app-sidebar__link ${cActive ? "is-active" : ""}`}
                          onClick={() => { setView(c.id); onClose?.(); }}
                          data-testid={`tab-${c.id}`}
                          style={{ paddingLeft: 32, fontSize: 12.5 }}
                        >
                          <span style={{ width: 16, display: "inline-block" }} />
                          <span style={{ flex: 1, textAlign: "left" }}>{c.label}</span>
                          {cActive && <ChevronRight size={12} strokeWidth={1.75} style={{ opacity: 0.6 }} />}
                        </button>
                      );
                    })}
                  </React.Fragment>
                );
              })}
            </div>
          );
        })}
      </nav>
      <div className="app-sidebar__footer">
        {isSuperAdmin && (
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
            color: "#5eead4", textTransform: "uppercase",
            border: "1px solid rgba(94,234,212,.35)", padding: "2px 8px",
            borderRadius: 999,
          }}>
            Super admin
          </span>
        )}
      </div>
    </aside>
    </>
  );
}

function TopBar({ user, companyName, isSuperAdmin, allCompanies, activeCo, onChangeCompany, onLogout, onOpenAIPanel, view, setView, onToggleSidebar }) {
  const tab = ALL_TABS.find((t) => t.id === view);
  const groupName = NAV_GROUPS.find((g) => g.items.some((i) => i.id === view))?.label || "Operação";
  const { theme, toggle: toggleTheme } = useTheme();
  return (
    <header className="app-topbar">
      <button
        data-testid="sidebar-toggle-btn"
        onClick={onToggleSidebar}
        aria-label="Abrir menu"
        className="app-topbar__hamburger"
        style={{
          display: "none",
          background: "transparent", border: 0, padding: 8, cursor: "pointer",
          color: "var(--text-primary)", marginRight: 4,
        }}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M3 6h18M3 12h18M3 18h18"/>
        </svg>
      </button>
      <div className="app-topbar__crumb" style={{ flex: 1, minWidth: 0 }}>
        <span>{groupName}</span>
        <ChevronRight size={12} strokeWidth={1.75} style={{ opacity: 0.5 }} />
        <span className="app-topbar__title">{tab?.label || "Painel"}</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {isSuperAdmin && (
          <select
            data-testid="super-admin-company-selector"
            value={activeCo}
            onChange={(e) => onChangeCompany(e.target.value)}
            title="Drill-down: visualizar como uma empresa específica"
            className="input"
            style={{
              width: 200, height: 32, fontSize: 12,
              borderColor: activeCo ? "var(--accent)" : undefined,
              color: activeCo ? "var(--accent-soft-fg)" : undefined,
              background: activeCo ? "var(--accent-soft)" : undefined,
              fontWeight: 600,
            }}
          >
            <option value="">Todas as empresas</option>
            {allCompanies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}{c.plan === "enterprise" ? " · enterprise" : c.plan === "free" ? " · free" : ""}
              </option>
            ))}
          </select>
        )}

        <button
          className="btn btn-ghost btn-sm"
          onClick={toggleTheme}
          data-testid="theme-toggle-btn"
          title={theme === "dark" ? "Mudar para tema claro" : "Mudar para tema escuro"}
          aria-label="Alternar tema claro/escuro"
        >
          {theme === "dark" ? <Sun size={14} strokeWidth={1.75} /> : <Moon size={14} strokeWidth={1.75} />}
        </button>

        <button
          className="btn btn-ghost btn-sm"
          onClick={() => setSessionMode("app")}
          data-testid="open-mobile-btn"
          title="Visualizar como o colaborador no celular"
        >
          <Smartphone size={14} strokeWidth={1.75} />
          <span style={{ display: "none" }}>Modo celular</span>
        </button>

        {user && (user.role === "gestor" || user.role === "auditor" || user.role === "administrador") && (
          <button
            data-testid="ai-preventive-open-btn"
            onClick={onOpenAIPanel}
            className="btn btn-ghost btn-sm"
            title="Abrir Central IA"
          >
            <Brain size={14} strokeWidth={1.75} /> Inteligência
          </button>
        )}

        {user && <NotificationsBell onOpenAIPanel={onOpenAIPanel} />}
        {user && <BudgetAlertBadge role={user.role} onClick={() => setView && setView("motor-ia")} />}
        <ServerClock compact />

        {user && (
          <div className="user-chip" data-testid="user-chip" style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "4px 10px 4px 4px", borderRadius: 999,
            border: "1px solid var(--border-default)",
            background: "var(--bg-surface)",
          }}>
            <div style={{
              width: 26, height: 26, borderRadius: "50%",
              background: "linear-gradient(135deg, #0d9488, #0f766e)",
              color: "#fff", display: "grid", placeItems: "center",
              fontSize: 11, fontWeight: 700, letterSpacing: "-0.02em",
            }}>
              {(user.name || "U").substring(0, 2).toUpperCase()}
            </div>
            <div style={{ minWidth: 0, lineHeight: 1.1 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>{user.name}</div>
              <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>
                {isSuperAdmin ? "super admin" : user.role}
              </div>
            </div>
          </div>
        )}

        {user && (
          <button
            onClick={onLogout}
            data-testid="logout-btn"
            className="btn btn-ghost btn-sm btn-icon"
            title="Sair"
          >
            <LogOut size={14} strokeWidth={1.75} />
          </button>
        )}
      </div>
    </header>
  );
}

function AppShell({ view, setView, children }) {
  const { user, logout, isPublicAccess } = useAuth();
  const [companyName, setCompanyName] = useState(null);
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  const [allCompanies, setAllCompanies] = useState([]);
  const [showAIPanel, setShowAIPanel] = useState(false);
  const [tabPerms, setTabPerms] = useState(_DEFAULT_TAB_PERMS);
  const [activeCo, setActiveCo] = useState(() => {
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem("ponto_active_company") || "";
  });

  useEffect(() => {
    let alive = true;
    import("@/api").then(({ api }) =>
      api.saasMe().then((c) => {
        if (!alive) return;
        setCompanyName(c?.name);
        setIsSuperAdmin(!!c?.is_super_admin);
        if (c?.is_super_admin) {
          api.saasListCompanies().then((list) => {
            if (alive) setAllCompanies(list);
          }).catch(() => { /* ignore */ });
        }
      }).catch(() => { /* ignore */ })
    );
    return () => { alive = false; };
  }, [activeCo]);

  useEffect(() => {
    let alive = true;
    if (!user || user.role === "colaborador") return undefined;
    Promise.all([
      import("@/api").then((m) => m.api),
      import("@/TabPermissionsCard").then((m) => ({
        TAB_DEFINITIONS: m.TAB_DEFINITIONS,
        DEFAULT_TAB_PERMISSIONS: m.DEFAULT_TAB_PERMISSIONS,
      })),
    ]).then(([api, perms]) => {
      api.brandingGet().then((cfg) => {
        if (!alive) return;
        const saved = cfg?.tab_permissions;
        if (!saved || typeof saved !== "object") {
          // Sem config salva → mantém defaults (já aplicados no estado inicial).
          return;
        }
        // RESPEITA exatamente o que foi salvo. Se uma role NÃO foi customizada
        // (chave ausente no cfg), cai para o default daquela role.
        // CRITICAL: nunca adicionar abas do default em cima do array salvo —
        // isso anula desmarcações feitas pelo admin.
        const merged = {};
        for (const role of Object.keys(perms.DEFAULT_TAB_PERMISSIONS)) {
          if (Array.isArray(saved[role])) {
            merged[role] = saved[role];
          } else {
            merged[role] = perms.DEFAULT_TAB_PERMISSIONS[role] || [];
          }
        }
        setTabPerms(merged);
      }).catch(() => { /* ignore */ });
    });
    return () => { alive = false; };
  }, [user]);

  function changeActiveCo(cid) {
    if (typeof window !== "undefined") {
      if (cid) window.localStorage.setItem("ponto_active_company", cid);
      else window.localStorage.removeItem("ponto_active_company");
    }
    setActiveCo(cid);
    if (typeof window !== "undefined") window.location.reload();
  }

  const tabs = useMemo(() => ALL_TABS.filter((t) => {
    // Modo público (link sem login) só vê a aba autorizada no escopo do token.
    // Hoje o único escopo é "lousa" (Chamados) — quando expandir suportar
    // outros, basta ler `user._public_token_scope` e filtrar aqui.
    if (isPublicAccess) return t.id === "lousa";
    if (t.superAdminOnly && !isSuperAdmin) return false;
    // Feature flags por usuário (ex.: can_attend_whatsapp).
    // Admin/auditor bypassam essa restrição.
    if (t.requires && user && user.role !== "administrador" && user.role !== "auditor") {
      if (!user[t.requires]) return false;
    }
    if (tabPerms && user && tabPerms[user.role]) {
      if (user.role === "administrador") return true;
      return tabPerms[user.role].includes(t.id);
    }
    // Administrador sempre vê tudo (super-role).
    if (user && user.role === "administrador") return true;
    // Pra QUALQUER outro role, se `tabPerms` ainda não carregou ou não tem
    // entrada pro role do usuário, NÃO caímos no fallback `hasRole`
    // (que liberava abas demais pro gestor). Aplicamos o DEFAULT direto.
    if (user && _DEFAULT_TAB_PERMS[user.role]) {
      return _DEFAULT_TAB_PERMS[user.role].includes(t.id);
    }
    if (!hasRole(user, ...t.roles)) return false;
    return true;
  }), [user, tabPerms, isSuperAdmin, isPublicAccess]);

  // Drawer state (mobile sidebar)
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Fecha o drawer ao trocar de view (impressão de "selecionou item")
  useEffect(() => { setSidebarOpen(false); }, [view]);

  return (
    <div className="app-shell">
      <SidebarNav
        activeTabs={tabs}
        view={view}
        setView={setView}
        brand={companyName}
        isSuperAdmin={isSuperAdmin}
        onOpenModal={(id) => { if (id === "ai-center") setShowAIPanel(true); }}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <main className="app-main">
        <TopBar
          user={user}
          companyName={companyName}
          isSuperAdmin={isSuperAdmin}
          allCompanies={allCompanies}
          activeCo={activeCo}
          onChangeCompany={changeActiveCo}
          onLogout={logout}
          onOpenAIPanel={() => setShowAIPanel(true)}
          view={view}
          setView={setView}
          onToggleSidebar={() => setSidebarOpen((v) => !v)}
        />
        <div className="app-content">
          <ImpersonationBanner />
          {showAIPanel && <AICenterPanel onClose={() => setShowAIPanel(false)} />}
          {children}
        </div>
      </main>
    </div>
  );
}

function AppContent() {
  useEffect(() => { startServerTime(); }, []);
  const { user, loading, logout, login, isPublicAccess } = useAuth();
  const mobile = useMobileMode();

  // Lógica de tabs centralizada aqui para que tanto o sidebar (AppShell)
  // quanto o roteador (BlockedPage check) usem a MESMA fonte de verdade.
  // Antes, `tabs` era computado dentro de AppShell e referenciado por engano
  // em AppContent, causando `ReferenceError: tabs is not defined` após login.
  const [tabPerms, setTabPerms] = useState(_DEFAULT_TAB_PERMS);
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  useEffect(() => {
    let alive = true;
    if (!user || user.role === "colaborador") return undefined;
    (async () => {
      try {
        const { api } = await import("@/api");
        const me = await api.saasMe().catch(() => null);
        if (alive && me?.is_super_admin) setIsSuperAdmin(true);
        const cfg = await api.brandingGet().catch(() => null);
        if (!alive) return;
        const saved = cfg?.tab_permissions;
        if (!saved || typeof saved !== "object") {
          // Sem config salva → usa defaults
          setTabPerms(_DEFAULT_TAB_PERMS);
          return;
        }
        // RESPEITA exatamente o que foi salvo. Se uma role NÃO foi customizada
        // (chave ausente no cfg), aí sim cai para o default daquela role.
        // Isso garante que desmarcar uma aba do Gestor remova ela DE FATO.
        const merged = {};
        for (const role of Object.keys(_DEFAULT_TAB_PERMS)) {
          if (Array.isArray(saved[role])) {
            merged[role] = saved[role];
          } else {
            merged[role] = _DEFAULT_TAB_PERMS[role] || [];
          }
        }
        setTabPerms(merged);
      } catch { /* ignore */ }
    })();
    return () => { alive = false; };
  }, [user]);

  const tabs = useMemo(() => ALL_TABS.filter((t) => {
    if (isPublicAccess) return t.id === "lousa";
    if (t.superAdminOnly && !isSuperAdmin) return false;
    if (t.requires && user && user.role !== "administrador" && user.role !== "auditor") {
      if (!user[t.requires]) return false;
    }
    if (tabPerms && user && tabPerms[user.role]) {
      if (user.role === "administrador") return true;
      return tabPerms[user.role].includes(t.id);
    }
    if (user && user.role === "administrador") return true;
    if (user && _DEFAULT_TAB_PERMS[user.role]) {
      return _DEFAULT_TAB_PERMS[user.role].includes(t.id);
    }
    if (!hasRole(user, ...t.roles)) return false;
    return true;
  }), [user, tabPerms, isSuperAdmin, isPublicAccess]);

  const [autoLoginState, setAutoLoginState] = useState(() => {
    if (typeof window === "undefined") return "idle";
    const path = window.location.pathname || "";
    if (path === "/preview" || path === "/demo") return "pending";
    // Auto-redirect só em ambientes Emergent preview (domínio .preview.emergentagent.com)
    // e somente se ainda não estiver logado nem em rota específica.
    const host = window.location.hostname || "";
    const isPreviewHost = host.endsWith(".preview.emergentagent.com");
    const alreadyHasToken = !!window.localStorage.getItem("ponto_token");
    const isRootPath = path === "/" || path === "";
    // Se há ?cid= o usuário quer abrir o app do técnico (sem login admin) — pula auto-login.
    const hasCid = !!new URLSearchParams(window.location.search).get("cid");
    // Se há ptoken (link público), o usuário sintético é resolvido via header — pula auto-login.
    const hasPublicToken = !!window.localStorage.getItem("smartprov_public_token");
    if (isPreviewHost && isRootPath && !alreadyHasToken && !hasCid && !hasPublicToken) return "pending";
    return "idle";
  });

  // Auto-login para demonstração: rota `/preview` ou `/demo` faz login com
  // credenciais do test_credentials.md e redireciona pro app. Útil para
  // visualizadores externos (Emergent preview, sales demos, QA).
  useEffect(() => {
    if (autoLoginState !== "pending") return;
    if (user) {
      setAutoLoginState("done");
      window.history.replaceState({}, "", "/app");
      return;
    }
    (async () => {
      try {
        await login("admin@empresa.com", "123456");
        setAutoLoginState("done");
        window.history.replaceState({}, "", "/app");
      } catch (e) {
        console.error("[preview] auto-login failed:", e);
        setAutoLoginState("error");
        window.history.replaceState({}, "", "/login");
      }
    })();
  }, [autoLoginState, user, login]);
  const [systemStatus, setSystemStatus] = useState({ offline: false, drift_blocked: false });
  const [view, setViewState] = useState(() => {
    if (typeof window === "undefined") return "dashboard";
    // Em modo público (link sem login), abre direto na aba Chamados.
    if (window.localStorage.getItem("smartprov_public_token")
        && !window.localStorage.getItem("ponto_token")) {
      return "lousa";
    }
    const saved = window.localStorage.getItem("ponto_active_tab");
    return saved || "dashboard";
  });
  const setView = (v) => {
    // Em modo público, ignora tentativa de trocar pra aba fora do escopo.
    if (typeof window !== "undefined"
        && window.localStorage.getItem("smartprov_public_token")
        && !window.localStorage.getItem("ponto_token")
        && v !== "lousa") {
      return;
    }
    setViewState(v);
    if (typeof window !== "undefined") window.localStorage.setItem("ponto_active_tab", v);
  };

  // Reforça view=lousa quando entra em modo público (caso o localStorage tenha
  // resíduo de uma sessão anterior).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const hasPtoken = !!window.localStorage.getItem("smartprov_public_token");
    const hasJWT = !!window.localStorage.getItem("ponto_token");
    if (hasPtoken && !hasJWT && view !== "lousa") {
      setViewState("lousa");
    }
  }, [view]);

  // Deep-link: ao clicar num atendente humano no Central IA, navegar para Atendimento IA com filtro
  useEffect(() => {
    const onOpenAttendant = (e) => {
      const detail = e?.detail || {};
      if (!detail.user_id) return;
      try {
        window.localStorage.setItem("smartprov_attendant_filter", JSON.stringify(detail));
      } catch { /* ignore */ }
      setView("atendimento");
    };
    window.addEventListener("smartprov-open-attendant", onOpenAttendant);
    return () => window.removeEventListener("smartprov-open-attendant", onOpenAttendant);
  }, []);
  const [route, setRoute] = useState(() => {
    if (typeof window === "undefined") return { path: "/", params: {} };
    const path = window.location.pathname || "/";
    const search = new URLSearchParams(window.location.search);
    return { path, params: Object.fromEntries(search) };
  });
  const [publicView, setPublicView] = useState(() => {
    if (typeof window === "undefined") return "landing";
    const path = window.location.pathname || "/";
    if (path === "/signup") return "signup";
    if (path === "/login") return "login";
    return "landing";
  });

  useEffect(() => {
    const onPop = () => {
      const path = window.location.pathname || "/";
      setRoute({ path, params: Object.fromEntries(new URLSearchParams(window.location.search)) });
      if (path === "/signup") setPublicView("signup");
      else if (path === "/login") setPublicView("login");
      else setPublicView("landing");
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = (path) => {
    if (typeof window !== "undefined") window.history.pushState({}, "", path);
    const [bare, qs = ""] = path.split("?");
    setRoute({ path: bare, params: Object.fromEntries(new URLSearchParams(qs)) });
    if (bare === "/signup") setPublicView("signup");
    else if (bare === "/login") setPublicView("login");
    else if (bare === "/") setPublicView("landing");
  };

  const [needsOnboarding, setNeedsOnboarding] = useState(null);
  useEffect(() => {
    if (!user) { setNeedsOnboarding(false); return; }
    let alive = true;
    (async () => {
      const done = (typeof window !== "undefined") && window.localStorage.getItem("ponto_onboarding_done") === "1";
      if (done) { if (alive) setNeedsOnboarding(false); return; }
      try {
        const me = await import("@/api").then(({ api }) => api.saasMe());
        const should = (me?.collaborators_count || 0) === 0 && !me?.is_super_admin;
        if (alive) setNeedsOnboarding(should);
      } catch {
        if (alive) setNeedsOnboarding(false);
      }
    })();
    return () => { alive = false; };
  }, [user]);

  if (loading || autoLoginState === "pending") {
    // Mural público funciona sem auth — pula loader
    if (typeof window !== "undefined") {
      const p = window.location.pathname;
      if (p === "/mural" || p === "/leaderboard") return <LeaderboardMural />;
      if (p === "/tv" || p === "/quadro" || p.startsWith("/tv/")) return <TvHub />;
      if (p.startsWith("/onboarding/")) {
        const token = p.replace("/onboarding/", "");
        const OnboardingPage = require("@/OnboardingPage").default;
        return <OnboardingPage token={token} />;
      }
    }
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "var(--text-secondary)" }} data-testid={autoLoginState === "pending" ? "auto-login-loading" : "auth-loading"}>
        {autoLoginState === "pending" ? "Entrando no modo demo…" : "Carregando…"}
      </div>
    );
  }

  // Mural público — TV no escritório (sem auth)
  if (route.path === "/mural" || route.path === "/leaderboard") {
    return <LeaderboardMural />;
  }
  // Onboarding público — cliente captura documentos pós-venda (sem auth)
  if ((route.path || "").startsWith("/onboarding/")) {
    const token = route.path.replace("/onboarding/", "");
    const OnboardingPage = require("@/OnboardingPage").default;
    return <OnboardingPage token={token} />;
  }
  // TV Hub — Quadro Kanban + KPIs Isabella + Financeiro + Mural (público, sem auth)
  if (route.path === "/tv" || route.path === "/quadro"
       || (route.path || "").startsWith("/tv/")) {
    return <TvHub />;
  }

  if (mobile) {
    const params = new URLSearchParams(window.location.search);
    const forced = params.get("cid") || null;
    // Gestores e super_admins acessam o painel admin completo (com sidebar drawer)
    // mesmo no celular. Apenas técnicos/colaboradores caem no CollaboratorApp PWA.
    const userRoles = Array.isArray(user?.roles) ? user.roles : [];
    const isManager = userRoles.includes("gestor") || userRoles.includes("super_admin")
      || userRoles.includes("admin") || userRoles.includes("financeiro");
    if (!user || !isManager) {
      return <CollaboratorApp mobile forcedCollabId={forced} />;
    }
    // Manager: cai no fluxo admin abaixo (sidebar vira drawer via CSS @media)
  }

  if (route.path === "/billing/success") {
    return <BillingSuccessPage sessionId={route.params.session_id} onDone={() => navigate(user ? "/app" : "/")} />;
  }
  if (route.path === "/billing/cancel") {
    return <BillingCancelPage onDone={() => navigate(user ? "/app" : "/")} />;
  }

  // Página pública do holerite (acessada via link WhatsApp).
  // É independente da sessão — colaborador autentica dentro do componente.
  if (route.path && route.path.startsWith("/holerite/")) {
    const token = route.path.replace("/holerite/", "").replace(/\/$/, "");
    return <HoleriteViewer token={token} onBack={() => navigate("/")} />;
  }

  if (!user) {
    if (publicView === "signup") {
      return <SignupPage
        defaultPlan={route.params.plan === "free" ? "free" : "trial"}
        onSuccess={() => { window.location.href = "/app"; }}
        onBack={() => navigate("/")}
      />;
    }
    if (publicView === "login") {
      return <LoginPage onBack={() => navigate("/")} />;
    }
    return <LandingPage
      onSignup={(opts) => navigate("/signup" + (opts?.plan === "free" ? "?plan=free" : ""))}
      onLogin={() => navigate("/login")}
    />;
  }

  const activeTab = ALL_TABS.find((t) => t.id === view);
  // `tabs` já aplica TODAS as regras (superAdminOnly, tab_permissions custom,
  // feature flags do user, e fallback DEFAULT_TAB_PERMISSIONS). Usamos ele
  // como única fonte de verdade — se a aba não está lá, BlockedPage.
  const allowed = !!(activeTab && tabs.find((t) => t.id === view));

  if (needsOnboarding === null) {
    return <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "var(--text-secondary)" }}>Carregando…</div>;
  }
  if (needsOnboarding) {
    return <OnboardingWizard user={user} onDone={() => setNeedsOnboarding(false)} />;
  }

  return (
    <AppShell view={view} setView={setView}>
      <OfflineTimeBanner onStatusChange={setSystemStatus} />
      <PublicAccessBanner />
      <BillingBanner />
      {!allowed ? (
        <BlockedPage tabLabel={activeTab?.label || "esta seção"} />
      ) : (
        <>
          {view === "dashboard" && <DashboardPanel />}
          {view === "lousa" && <LousaAdminPanel systemStatus={systemStatus} />}
          {view === "estoque" && <EstoquePanel currentUser={user} />}
          {view === "central-compras" && <CentralComprasPanel currentUser={user} />}
          {view === "ai-ranking" && <AiRankingPanel />}
          {view === "ai-corrections" && <AiCorrectionsPanel />}
          {view === "central-ia" && <CentralIaDashboard />}
          {view === "atendimento" && <AIHubPanel initialTab="whatsapp_qr" />}
          {view === "cadastro" && <CadastroPanel />}
          {view === "subscribers" && <SubscribersPanel />}
          {view === "plans" && <PlansPanel />}
          {view === "pracas" && <PracasPanel />}
          {view === "users" && <UsersPanel />}
          {view === "manager" && <ManagerPanel />}
          {view === "sheet" && <TimesheetView />}
          {view === "holerite" && <HoleritePanel />}
          {view === "feriados" && <FeriadosPanel />}
          {view === "financeiro" && <FinanceiroPanel />}
          {view === "budget" && <BudgetPanel />}
          {view === "rede-ia" && <RedeIaPanel currentUser={user} />}
          {view === "alvaro-ia" && <AlvaroPanel />}
          {view === "mass-messaging" && <MassMessagingPanel />}
          {view === "logs" && <LogsPanel />}
          {view === "settings" && <SettingsPanel />}
          {view === "motor-ia" && (
            <div style={{ padding: "0 4px", display: "grid", gap: 16 }}>
              <h1 style={{ fontSize: 24, fontWeight: 700,
                              color: "var(--text-primary)",
                              letterSpacing: "-0.02em", margin: 0 }}>
                Motor IA
              </h1>
              <AiTopologyCard />
              <MotorIaBudgetCard />
              <MotorIaUsageCard />
              <MotorIaCard />
            </div>
          )}
          {view === "platform" && <PlatformAdminPanel />}
        </>
      )}
    </AppShell>
  );
}

const PublicMapPage = React.lazy(() => import("@/PublicMapPage"));

export default function App() {
  // Rota pública /rede-publica — sem auth, sem sidebar
  const isPublicMap = typeof window !== "undefined" &&
    window.location.pathname.startsWith("/rede-publica");
  if (isPublicMap) {
    return (
      <React.Suspense fallback={<div style={{
        display: "grid", placeItems: "center", height: "100vh",
        fontFamily: "system-ui", color: "#64748b",
      }}>Carregando mapa…</div>}>
        <PublicMapPage />
      </React.Suspense>
    );
  }
  return (
    <AuthProvider>
      <AppContent />
      <DialogHost />
      <DialogHistoryGate />
    </AuthProvider>
  );
}

function DialogHistoryGate() {
  const { user } = useAuth();
  const canView = !!user && (user.role === "administrador" || user.role === "auditor");
  return <DialogHistoryPanel canView={canView} />;
}
