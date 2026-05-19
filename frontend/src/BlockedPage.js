/**
 * BlockedPage — Página padrão exibida quando o usuário tenta acessar um
 * recurso (aba, panel, API) sem permissão suficiente.
 *
 * Uso típico:
 *   {!allowed && <BlockedPage tabLabel="Plataforma" requiredRole="auditor" />}
 *
 * Também pode ser usada como página dedicada via roteador.
 */
import React from "react";
import { ShieldAlert, ArrowLeft, MessageSquare } from "lucide-react";
import { useAuth } from "@/AuthContext";

export default function BlockedPage({
  tabLabel = "esta seção",
  requiredRole = null,
  message = null,
  onBack = null,
}) {
  const { user, logout } = useAuth() || {};
  const roleLabel = (user?.role || "usuário").toLowerCase();
  const niceMessage = message
    || (requiredRole
      ? `Esta área é exclusiva para usuários com perfil ${requiredRole.toUpperCase()}.`
      : `Você está logado como ${roleLabel}. Esta área não está liberada para o seu perfil.`);

  const goHome = () => {
    if (onBack) return onBack();
    try {
      window.history.length > 1 ? window.history.back() : (window.location.href = "/");
    } catch { window.location.href = "/"; }
  };

  return (
    <div
      data-testid="blocked-page"
      style={{
        minHeight: "60vh",
        display: "grid",
        placeItems: "center",
        padding: "40px 20px",
      }}
    >
      <div style={{
        maxWidth: 520, width: "100%",
        background: "white",
        borderRadius: 20,
        boxShadow: "0 18px 48px rgba(15,23,42,.08), 0 2px 4px rgba(15,23,42,.04)",
        border: "1px solid rgba(220, 38, 38, .12)",
        overflow: "hidden",
      }}>
        {/* Top stripe */}
        <div style={{
          height: 6,
          background: "linear-gradient(90deg, #dc2626, #f59e0b, #dc2626)",
          backgroundSize: "200% 100%",
          animation: "blockedStripe 3s linear infinite",
        }} />
        <style>{`
          @keyframes blockedStripe {
            0% { background-position: 0% 50%; }
            100% { background-position: 200% 50%; }
          }
          @keyframes blockedPulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.05); opacity: .85; }
          }
        `}</style>

        <div style={{ padding: "36px 32px 32px" }}>
          {/* Ícone */}
          <div style={{
            width: 84, height: 84, borderRadius: 24,
            background: "linear-gradient(135deg, #fee2e2, #fecaca)",
            display: "grid", placeItems: "center",
            margin: "0 auto 20px",
            color: "#dc2626",
            animation: "blockedPulse 2.4s ease-in-out infinite",
          }}>
            <ShieldAlert size={42} strokeWidth={2.2} />
          </div>

          {/* Status code */}
          <div style={{
            textAlign: "center",
            fontSize: 11, fontWeight: 800,
            letterSpacing: "0.18em",
            color: "#dc2626",
            textTransform: "uppercase",
            marginBottom: 8,
          }}>
            HTTP 403 · Acesso bloqueado
          </div>

          {/* Título */}
          <h1 style={{
            margin: "0 0 12px",
            fontSize: 26, fontWeight: 800,
            color: "#0f172a",
            textAlign: "center",
            letterSpacing: "-0.025em",
          }}>
            Você não tem acesso a {tabLabel}
          </h1>

          {/* Mensagem */}
          <p style={{
            margin: "0 0 24px",
            fontSize: 14, lineHeight: 1.55,
            color: "#475569",
            textAlign: "center",
          }}>
            {niceMessage}
          </p>

          {/* Detalhes do usuário */}
          {user && (
            <div style={{
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              borderRadius: 12,
              padding: "14px 16px",
              marginBottom: 22,
              fontSize: 12,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between",
                              marginBottom: 6 }}>
                <span style={{ color: "#64748b", fontWeight: 600 }}>Usuário</span>
                <span style={{ color: "#0f172a", fontWeight: 700 }}>
                  {user.email || user.name || "—"}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b", fontWeight: 600 }}>Perfil</span>
                <span style={{
                  background: "#fef3c7", color: "#92400e",
                  padding: "2px 10px", borderRadius: 999,
                  fontWeight: 700, fontSize: 11,
                  textTransform: "uppercase", letterSpacing: ".05em",
                }}>
                  {roleLabel}
                </span>
              </div>
            </div>
          )}

          {/* Ações */}
          <div style={{ display: "flex", gap: 10, justifyContent: "center",
                          flexWrap: "wrap" }}>
            <button
              data-testid="blocked-back-btn"
              onClick={goHome}
              style={{
                padding: "11px 22px",
                background: "#0f172a", color: "white",
                border: "none", borderRadius: 12,
                fontSize: 13, fontWeight: 700,
                cursor: "pointer",
                display: "flex", alignItems: "center", gap: 8,
                transition: "transform .15s ease",
              }}
              onMouseEnter={(e) => e.currentTarget.style.transform = "translateY(-1px)"}
              onMouseLeave={(e) => e.currentTarget.style.transform = "translateY(0)"}
            >
              <ArrowLeft size={16} /> Voltar
            </button>
            <a
              data-testid="blocked-contact-btn"
              href="mailto:suporte@ligo.site?subject=Solicitação de acesso&body=Olá,%0A%0Apreciso de acesso à área: "
              style={{
                padding: "11px 22px",
                background: "white", color: "#0f172a",
                border: "1px solid #e2e8f0", borderRadius: 12,
                fontSize: 13, fontWeight: 700,
                cursor: "pointer",
                display: "flex", alignItems: "center", gap: 8,
                textDecoration: "none",
              }}
            >
              <MessageSquare size={16} /> Pedir acesso ao gestor
            </a>
          </div>

          {/* Logout sutil */}
          {logout && (
            <div style={{
              marginTop: 20, paddingTop: 16,
              borderTop: "1px solid #f1f5f9",
              textAlign: "center", fontSize: 11,
              color: "#94a3b8",
            }}>
              Não é você?{" "}
              <button
                data-testid="blocked-logout-btn"
                onClick={() => logout()}
                style={{
                  background: "none", border: "none",
                  color: "#dc2626", fontWeight: 700,
                  textDecoration: "underline", cursor: "pointer",
                  padding: 0, fontSize: 11,
                }}
              >
                Sair e entrar com outra conta
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
