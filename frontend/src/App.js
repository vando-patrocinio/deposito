import React, { useEffect, useState } from "react";
import "@/App.css";
import { Button, Icon } from "@/ui";
import CollaboratorApp from "@/CollaboratorApp";
import CadastroPanel from "@/CadastroPanel";
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
import AIPreventivePanel from "@/AIPreventivePanel";
import AiRankingPanel from "@/AiRankingPanel";
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
    // ?cid=... (link direto compartilhado para um técnico específico) força modo app
    if (params.get("cid")) return true;
    if (params.get("mode") === "desktop") return false;
    // override manual via sessionStorage (botão "Modo celular" no header)
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
  } catch {}
}

const ALL_TABS = [
  { id: "dashboard", icon: "sheet", label: "Painel", roles: ["gestor", "auditor", "administrador"] },
  { id: "lousa", icon: "users", label: "Lousa 📋", roles: ["administrador"] },
  { id: "estoque", icon: "sheet", label: "Estoque 📦", roles: ["gestor", "administrador"] },
  { id: "ai-ranking", icon: "shield", label: "Avaliação IA 🤖", roles: ["gestor", "auditor", "administrador"] },
  { id: "cadastro", icon: "users", label: "Cadastro", roles: ["gestor", "auditor", "administrador"] },
  { id: "pracas", icon: "map", label: "Praças", roles: ["gestor", "auditor", "administrador"] },
  { id: "users", icon: "shield", label: "Usuários", roles: ["auditor", "administrador"] },
  { id: "manager", icon: "shield", label: "Auditoria", roles: ["auditor", "administrador"] },
  { id: "sheet", icon: "sheet", label: "Espelho", roles: ["gestor", "auditor", "administrador"] },
  { id: "logs", icon: "history", label: "Logs", roles: ["gestor", "auditor", "administrador"] },
  { id: "settings", icon: "gear", label: "Configurações", roles: ["auditor", "administrador"] },
  // Aba exclusiva super admin (filtrada via flag isSuperAdmin no AppShell)
  { id: "platform", icon: "shield", label: "Plataforma", roles: ["auditor", "administrador"], superAdminOnly: true },
];

function ImpersonationBanner() {
  const { user, isImpersonating, endImpersonation } = useAuth();
  if (!isImpersonating || !user) return null;
  const imp = user.impersonator;
  return (
    <div data-testid="impersonation-banner" style={{
      background: "linear-gradient(90deg,#7c3aed,#5b21b6)", color: "white",
      padding: "10px 18px", display: "flex", alignItems: "center", gap: 12,
      flexWrap: "wrap", borderRadius: 14, marginBottom: 14,
      boxShadow: "0 8px 18px rgba(124,58,237,.32)",
    }}>
      <span style={{ fontSize: 22 }}>🎭</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <strong style={{ fontSize: 14 }}>Você está agindo como {user.name} ({user.role})</strong>
        <div style={{ fontSize: 12, opacity: 0.9 }}>
          Sessão original: {imp?.email} (auditor) — todas as ações são registradas.
        </div>
      </div>
      <button
        data-testid="end-impersonation-btn"
        onClick={async () => { try { await endImpersonation(); } catch (e) { alert("Erro: " + (e?.response?.data?.detail || e.message)); } }}
        style={{
          background: "white", color: "#5b21b6", border: "none", padding: "8px 14px",
          borderRadius: 12, fontWeight: 800, cursor: "pointer",
        }}
      >
        Voltar ao auditor
      </button>
    </div>
  );
}

function AppShell({ view, setView, children }) {
  const { user, logout } = useAuth();
  const [companyName, setCompanyName] = useState(null);
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  const [allCompanies, setAllCompanies] = useState([]);
  const [showAIPanel, setShowAIPanel] = useState(false);
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
          }).catch(() => {});
        }
      }).catch(() => {})
    );
    return () => { alive = false; };
  }, [activeCo]);
  function changeActiveCo(cid) {
    if (typeof window !== "undefined") {
      if (cid) window.localStorage.setItem("ponto_active_company", cid);
      else window.localStorage.removeItem("ponto_active_company");
    }
    setActiveCo(cid);
    // Reload simples — força todos os componentes a recarregar dados com novo escopo
    if (typeof window !== "undefined") window.location.reload();
  }
  const tabs = ALL_TABS.filter((t) => {
    if (!hasRole(user, ...t.roles)) return false;
    if (t.superAdminOnly && !isSuperAdmin) return false;
    return true;
  });
  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(180deg,#f8fafc 0%,#eef2ff 100%)",
      color: "#0f172a",
      fontFamily: "Inter, system-ui, -apple-system, Arial",
      padding: "24px 22px 40px",
    }}>
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <header style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          gap: 16, flexWrap: "wrap", marginBottom: 22,
          paddingBottom: 18, borderBottom: "1px solid rgba(15,23,42,0.06)",
        }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>
              <span style={{ color: "#10b981" }}>📍</span> PontoIA{companyName ? <span style={{ color: "#64748b", fontWeight: 500, fontSize: 18 }}> · {companyName}</span> : null}
              {isSuperAdmin && activeCo && <span style={{ background: "linear-gradient(135deg,#7c3aed,#5b21b6)", color: "white", fontSize: 11, fontWeight: 800, padding: "3px 10px", borderRadius: 999, marginLeft: 10, letterSpacing: "0.04em" }}>👁️ DRILL-DOWN</span>}
            </h1>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
              Gestão de pontos · cercas · espelho · auditoria
            </div>
          </div>
          <nav style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            {tabs.map((t) => (
              <Button
                key={t.id}
                variant={view === t.id ? "primary" : "secondary"}
                onClick={() => setView(t.id)}
                data-testid={`tab-${t.id}`}
              >
                <Icon name={t.icon} /> {t.label}
              </Button>
            ))}
            <Button variant="soft" onClick={() => setSessionMode("app")} data-testid="open-mobile-btn" title="Visualizar como o colaborador no celular">
              <Icon name="phone" /> Modo celular
            </Button>
            {isSuperAdmin && (
              <select
                data-testid="super-admin-company-selector"
                value={activeCo}
                onChange={(e) => changeActiveCo(e.target.value)}
                title="Drill-down: visualizar como uma empresa específica"
                style={{
                  background: activeCo ? "linear-gradient(135deg,#7c3aed,#5b21b6)" : "white",
                  color: activeCo ? "white" : "#0f172a",
                  border: activeCo ? "1px solid rgba(124,58,237,.3)" : "1px solid #e2e8f0",
                  borderRadius: 999, padding: "7px 14px", fontSize: 12,
                  fontWeight: 700, cursor: "pointer", maxWidth: 220,
                  boxShadow: activeCo ? "0 4px 10px rgba(124,58,237,.3)" : "none",
                  outline: "none",
                }}
              >
                <option value="">🌐 Todas as empresas</option>
                {allCompanies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.is_demo ? "📍 " : ""}{c.name}{c.plan === "enterprise" ? " ⭐" : c.plan === "free" ? " (Free)" : ""}
                  </option>
                ))}
              </select>
            )}
            {user && (
              <span style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "6px 12px", background: "white", borderRadius: 999,
                border: "1px solid #e2e8f0", fontSize: 12,
              }} data-testid="user-chip">
                <strong style={{ fontWeight: 700 }}>{user.name}</strong>
                <span style={{
                  fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999,
                  background: isSuperAdmin
                    ? "linear-gradient(135deg,#7c3aed,#5b21b6)"
                    : user.role === "auditor" ? "#fde68a" : user.role === "gestor" ? "#bbf7d0" : "#e0f2fe",
                  color: isSuperAdmin ? "white" : user.role === "auditor" ? "#92400e" : user.role === "gestor" ? "#166534" : "#075985",
                  textTransform: "uppercase", letterSpacing: "0.04em",
                  boxShadow: isSuperAdmin ? "0 4px 10px rgba(124,58,237,.3)" : "none",
                }}>{isSuperAdmin ? "🛡️ super admin" : user.role}</span>
              </span>
            )}
            {user && (user.role === "gestor" || user.role === "administrador") && (
              <button
                data-testid="ai-preventive-open-btn"
                onClick={() => setShowAIPanel(true)}
                title="Abrir painel de Preventivas IA"
                style={{
                  background: "linear-gradient(135deg,#a855f7,#7c3aed)", color: "white", border: "none",
                  padding: "6px 12px", borderRadius: 999, fontWeight: 800, cursor: "pointer", fontSize: 12,
                }}
              >
                🤖 Preventivas IA
              </button>
            )}
            {user && (
              <NotificationsBell onOpenAIPanel={() => setShowAIPanel(true)} />
            )}
            <ServerClock compact />
            {user && (
              <Button variant="danger" onClick={logout} data-testid="logout-btn">Sair</Button>
            )}
          </nav>
        </header>
        <ImpersonationBanner />
        {showAIPanel && <AIPreventivePanel onClose={() => setShowAIPanel(false)} />}
        {children}
      </div>
    </div>
  );
}

function AppContent() {
  // Inicia sincronização global com horário do servidor (anti-tampering)
  useEffect(() => { startServerTime(); }, []);
  const { user, loading, logout } = useAuth();
  const mobile = useMobileMode();
  const [systemStatus, setSystemStatus] = useState({ offline: false, drift_blocked: false });
  const [view, setViewState] = useState(() => {
    if (typeof window === "undefined") return "dashboard";
    const saved = window.localStorage.getItem("ponto_active_tab");
    return saved || "dashboard";
  });
  // Wrapper que persiste a aba ativa no localStorage
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
  // Tela inicial pública: 'landing' | 'signup' | 'login'
  const [publicView, setPublicView] = useState(() => {
    if (typeof window === "undefined") return "landing";
    const path = window.location.pathname || "/";
    if (path === "/signup") return "signup";
    if (path === "/login") return "login";
    return "landing";
  });

  // Listener para popstate
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

  // Onboarding wizard state — hooks DEVEM ficar antes de qualquer early return
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

  // Garante que a aba inicial corresponde ao papel do usuário (para gestor não cair em aba inexistente)
  useEffect(() => {
    if (!user) return;
    // Lousa agora é exclusiva de administrador. Gestor/auditor não veem mais essa aba.
    if (user.role === "gestor" && !["dashboard", "ai-ranking", "cadastro", "pracas", "sheet", "logs"].includes(view)) {
      setView("dashboard");
    }
    if (user.role === "auditor" && view === "lousa") {
      setView("dashboard");
    }
  }, [user, view]);

  if (loading) {
    return <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "#64748b" }}>Carregando…</div>;
  }

  // Mobile = app de ponto. Acesso livre — colaborador é autenticado pela face,
  // não precisa logar no sistema. Login é exclusivo para gestor/auditor (desktop).
  if (mobile) {
    // Suporte a ?cid=col-xxx — link direto para um colaborador específico (compartilhado pelo gestor)
    const params = new URLSearchParams(window.location.search);
    const forced = params.get("cid") || null;
    return <CollaboratorApp mobile forcedCollabId={forced} />;
  }

  // Rotas de billing (callback do Stripe) — funcionam autenticado ou não
  if (route.path === "/billing/success") {
    return <BillingSuccessPage sessionId={route.params.session_id} onDone={() => navigate(user ? "/app" : "/")} />;
  }
  if (route.path === "/billing/cancel") {
    return <BillingCancelPage onDone={() => navigate(user ? "/app" : "/")} />;
  }

  // Não autenticado → landing/signup/login
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

  // Autenticado → AppShell + paineis
  const activeTab = ALL_TABS.find((t) => t.id === view);
  const allowed = activeTab && hasRole(user, ...activeTab.roles);

  if (needsOnboarding === null) {
    return <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "#64748b" }}>Carregando…</div>;
  }
  if (needsOnboarding) {
    return <OnboardingWizard user={user} onDone={() => setNeedsOnboarding(false)} />;
  }

  return (
    <AppShell view={view} setView={setView}>
      <OfflineTimeBanner onStatusChange={setSystemStatus} />
      <BillingBanner />
      {!allowed ? (
        <div style={{ background: "white", border: "1px solid #e2e8f0", borderRadius: 16, padding: 22, textAlign: "center", color: "#64748b" }}>
          Sem acesso a esta seção. Procure o gestor.
        </div>
      ) : (
        <>
          {view === "dashboard" && <DashboardPanel />}
          {view === "lousa" && <LousaAdminPanel systemStatus={systemStatus} />}
          {view === "estoque" && <EstoquePanel />}
          {view === "ai-ranking" && <AiRankingPanel />}
          {view === "cadastro" && <CadastroPanel />}
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
