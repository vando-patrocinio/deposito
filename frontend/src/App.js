import React, { useEffect, useMemo, useState } from "react";
import "@/App.css";
import {
  Smartphone, LogOut, ChevronRight, ChevronDown, Brain, BarChart3, Layout,
  Boxes, Sparkles, Users, MapPin, ShieldCheck, ClipboardList,
  FileSpreadsheet, History as HistoryIcon, Settings as SettingsIcon,
  Building2, Eye, EyeOff, Sun, Moon, Bot, UserCircle,
} from "lucide-react";
import CollaboratorApp from "@/CollaboratorApp";
import CadastroPanel from "@/CadastroPanel";
import SubscribersPanel from "@/SubscribersPanel";
import ManagerPanel from "@/ManagerPanel";
import TimesheetView from "@/TimesheetView";
import SettingsPanel from "@/SettingsPanel";
import UsersPanel from "@/UsersPanel";
import DashboardPanel from "@/DashboardPanel";
import PracasPanel from "@/PracasPanel";
import LogsPanel from "@/LogsPanel";
import PlatformAdminPanel from "@/PlatformAdminPanel";
import LousaAdminPanel from "@/LousaAdminPanel";
import EstoquePanel from "@/EstoquePanel";
import AICenterPanel from "@/AICenterPanel";
import AiRankingPanel from "@/AiRankingPanel";
import AIHubPanel from "@/AIHubPanel";
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
const NAV_GROUPS = [
  {
    label: "Operação",
    items: [
      { id: "dashboard", icon: BarChart3, label: "Painel", roles: ["gestor", "auditor", "administrador"] },
      { id: "lousa", icon: Layout, label: "Lousa", roles: ["administrador"] },
      { id: "estoque", icon: Boxes, label: "Estoque", roles: ["gestor", "administrador"] },
    ],
  },
  {
    label: "Inteligência",
    items: [
      { id: "ai-center", icon: Brain, label: "Central IA", roles: ["gestor", "auditor", "administrador"], asModal: true },
      { id: "ai-ranking", icon: Sparkles, label: "Avaliação IA", roles: ["gestor", "auditor", "administrador"] },
      { id: "aihub", icon: Bot, label: "Atendimento IA", roles: ["gestor", "auditor", "administrador"] },
    ],
  },
  {
    label: "Pessoas",
    items: [
      { id: "cadastro", icon: Users, label: "Cadastro", roles: ["gestor", "auditor", "administrador"] },
      {
        id: "clientes",
        icon: UserCircle,
        label: "Clientes",
        roles: ["gestor", "auditor", "administrador"],
        children: [
          { id: "subscribers", label: "Assinantes" },
        ],
      },
      { id: "pracas", icon: MapPin, label: "Praças", roles: ["gestor", "auditor", "administrador"] },
      { id: "users", icon: ShieldCheck, label: "Usuários", roles: ["auditor", "administrador"] },
    ],
  },
  {
    label: "Compliance",
    items: [
      { id: "manager", icon: ClipboardList, label: "Auditoria", roles: ["auditor", "administrador"] },
      { id: "sheet", icon: FileSpreadsheet, label: "Espelho", roles: ["gestor", "auditor", "administrador"] },
      { id: "logs", icon: HistoryIcon, label: "Logs", roles: ["gestor", "auditor", "administrador"] },
    ],
  },
  {
    label: "Sistema",
    items: [
      { id: "settings", icon: SettingsIcon, label: "Configurações", roles: ["auditor", "administrador"] },
      { id: "platform", icon: Building2, label: "Plataforma", roles: ["auditor", "administrador"], superAdminOnly: true },
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
  const imp = user.impersonator;
  return (
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
          catch (e) { alert("Erro: " + (e?.response?.data?.detail || e.message)); }
        }}
        className="btn btn-secondary btn-sm"
      >
        <EyeOff size={14} strokeWidth={1.75} /> Sair do modo
      </button>
    </div>
  );
}

function SidebarNav({ activeTabs, view, setView, brand, isSuperAdmin, onOpenModal }) {
  const [collabsOpen, setCollabsOpen] = useState(false);
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
    <aside className={`app-sidebar ${collabsOpen ? "is-open" : ""}`} aria-label="Navegação principal">
      <div className="app-sidebar__brand">
        <div className="app-sidebar__brand-logo" aria-hidden="true">P</div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="app-sidebar__brand-name">PontoIA</div>
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
                  if (!hasChildren) setCollabsOpen(false);
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
                          onClick={() => { setView(c.id); setCollabsOpen(false); }}
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
  );
}

function TopBar({ user, companyName, isSuperAdmin, allCompanies, activeCo, onChangeCompany, onLogout, onOpenAIPanel, view }) {
  const tab = ALL_TABS.find((t) => t.id === view);
  const groupName = NAV_GROUPS.find((g) => g.items.some((i) => i.id === view))?.label || "Operação";
  const { theme, toggle: toggleTheme } = useTheme();
  return (
    <header className="app-topbar">
      <div className="app-topbar__crumb" style={{ flex: 1, minWidth: 0 }}>
        <span>{groupName}</span>
        <ChevronRight size={12} strokeWidth={1.75} style={{ opacity: 0.5 }} />
        <span className="app-topbar__title">{tab?.label || "Painel"}</span>
        {companyName && (
          <>
            <span style={{ width: 1, height: 14, background: "var(--border-default)", margin: "0 6px" }} />
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{companyName}</span>
          </>
        )}
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
            <Brain size={14} strokeWidth={1.75} /> IA
          </button>
        )}

        {user && <NotificationsBell onOpenAIPanel={onOpenAIPanel} />}
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
  const { user, logout } = useAuth();
  const [companyName, setCompanyName] = useState(null);
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  const [allCompanies, setAllCompanies] = useState([]);
  const [showAIPanel, setShowAIPanel] = useState(false);
  const [tabPerms, setTabPerms] = useState(null);
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
        if (!cfg?.tab_permissions) return;
        // Migration soft: para cada role, se uma aba do default está liberada
        // mas ainda não consta na config salva (porque a config foi gravada
        // ANTES da aba ser criada), adiciona automaticamente.
        const merged = { ...cfg.tab_permissions };
        for (const role of Object.keys(perms.DEFAULT_TAB_PERMISSIONS)) {
          const saved = merged[role] || [];
          const defaults = perms.DEFAULT_TAB_PERMISSIONS[role] || [];
          const missing = defaults.filter((id) => !saved.includes(id));
          if (missing.length) merged[role] = [...saved, ...missing];
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
    if (t.superAdminOnly && !isSuperAdmin) return false;
    if (tabPerms && user && tabPerms[user.role]) {
      if (user.role === "administrador") return true;
      return tabPerms[user.role].includes(t.id);
    }
    if (!hasRole(user, ...t.roles)) return false;
    return true;
  }), [user, tabPerms, isSuperAdmin]);

  return (
    <div className="app-shell">
      <SidebarNav
        activeTabs={tabs}
        view={view}
        setView={setView}
        brand={companyName}
        isSuperAdmin={isSuperAdmin}
        onOpenModal={(id) => { if (id === "ai-center") setShowAIPanel(true); }}
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
  const { user, loading, logout } = useAuth();
  const mobile = useMobileMode();
  const [systemStatus, setSystemStatus] = useState({ offline: false, drift_blocked: false });
  const [view, setViewState] = useState(() => {
    if (typeof window === "undefined") return "dashboard";
    const saved = window.localStorage.getItem("ponto_active_tab");
    return saved || "dashboard";
  });
  const setView = (v) => {
    setViewState(v);
    if (typeof window !== "undefined") window.localStorage.setItem("ponto_active_tab", v);
  };
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

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "var(--text-secondary)" }}>
        Carregando…
      </div>
    );
  }

  if (mobile) {
    const params = new URLSearchParams(window.location.search);
    const forced = params.get("cid") || null;
    return <CollaboratorApp mobile forcedCollabId={forced} />;
  }

  if (route.path === "/billing/success") {
    return <BillingSuccessPage sessionId={route.params.session_id} onDone={() => navigate(user ? "/app" : "/")} />;
  }
  if (route.path === "/billing/cancel") {
    return <BillingCancelPage onDone={() => navigate(user ? "/app" : "/")} />;
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
  const allowed = activeTab && hasRole(user, ...activeTab.roles);

  if (needsOnboarding === null) {
    return <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "var(--text-secondary)" }}>Carregando…</div>;
  }
  if (needsOnboarding) {
    return <OnboardingWizard user={user} onDone={() => setNeedsOnboarding(false)} />;
  }

  return (
    <AppShell view={view} setView={setView}>
      <OfflineTimeBanner onStatusChange={setSystemStatus} />
      <BillingBanner />
      {!allowed ? (
        <div className="surface" style={{ padding: 28, textAlign: "center", color: "var(--text-secondary)" }}>
          Sem acesso a esta seção. Procure o gestor.
        </div>
      ) : (
        <>
          {view === "dashboard" && <DashboardPanel />}
          {view === "lousa" && <LousaAdminPanel systemStatus={systemStatus} />}
          {view === "estoque" && <EstoquePanel />}
          {view === "ai-ranking" && <AiRankingPanel />}
          {view === "aihub" && <AIHubPanel />}
          {view === "cadastro" && <CadastroPanel />}
          {view === "subscribers" && <SubscribersPanel />}
          {view === "pracas" && <PracasPanel />}
          {view === "users" && <UsersPanel />}
          {view === "manager" && <ManagerPanel />}
          {view === "sheet" && <TimesheetView />}
          {view === "logs" && <LogsPanel />}
          {view === "settings" && <SettingsPanel />}
          {view === "platform" && <PlatformAdminPanel />}
        </>
      )}
    </AppShell>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
