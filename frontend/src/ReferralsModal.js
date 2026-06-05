/* ============================================================
   ReferralsModal — Indique e Ganhe para colaboradores (técnicos)
   Acessado pelo menu de 3 pontinhos do app PWA. Cada técnico tem
   um código de indicação único + link compartilhável; ao indicar
   alguém que vire ATIVO/INSTALADO, ganha R$ 50,00.
============================================================ */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

const C_BG = "rgba(15,23,42,0.7)";
const C_ACCENT = "#0d9488";
const C_PRIMARY = "#0f172a";
const C_MUTED = "#64748b";

export default function ReferralsModal({ collaboratorId, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        setLoading(true);
        const r = await api.referralsCollabPublic(collaboratorId);
        if (!cancel) setData(r);
      } catch (e) {
        if (!cancel) setError(e?.response?.data?.detail || "Falha ao carregar.");
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => { cancel = true; };
  }, [collaboratorId]);

  // Constroi share URL a partir do origin atual (mais confiável que backend)
  const shareUrl = data?.code
    ? `${window.location.origin}/r/${data.code}`
    : "";

  const handleCopy = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* fallback ignore */ }
  };

  const handleShare = async () => {
    if (!shareUrl) return;
    const text = `Olá! Vem ser cliente da nossa internet com minha indicação: ${shareUrl}`;
    if (navigator.share) {
      try {
        await navigator.share({
          title: "Indique e Ganhe",
          text,
          url: shareUrl,
        });
      } catch { /* user cancelou */ }
    } else {
      // Fallback: wa.me
      window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank");
    }
  };

  const stats = data?.stats || {};

  return (
    <div onClick={onClose} data-testid="referrals-modal"
          style={{ position: "fixed", inset: 0, zIndex: 9999, background: C_BG,
                    display: "flex", alignItems: "flex-end",
                    justifyContent: "center", padding: 0 }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ background: "#fff", borderTopLeftRadius: 22,
                      borderTopRightRadius: 22, width: "100%",
                      maxWidth: 560, maxHeight: "92vh",
                      display: "flex", flexDirection: "column",
                      overflow: "hidden",
                      boxShadow: "0 -20px 60px rgba(0,0,0,0.35)" }}>
        {/* Header gradient */}
        <div style={{
          padding: "20px 18px 22px",
          background: "linear-gradient(135deg, #0d9488 0%, #14b8a6 100%)",
          color: "#fff", position: "relative",
        }}>
          <button onClick={onClose} data-testid="referrals-close"
                  aria-label="Fechar"
                  style={{ position: "absolute", top: 12, right: 14,
                            background: "rgba(255,255,255,0.18)",
                            border: 0, color: "#fff", fontSize: 20,
                            width: 32, height: 32, borderRadius: "50%",
                            cursor: "pointer", lineHeight: 0 }}>×</button>
          <div style={{ fontSize: 32, marginBottom: 6 }}>🎁</div>
          <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 800,
                          letterSpacing: -0.4 }}>
            Indique e Ganhe + Metas
          </h2>
          <p style={{ margin: 0, fontSize: 13, opacity: 0.95, lineHeight: 1.5 }}>
            Olá, <strong>{data?.owner_first_name || "Técnico"}</strong>!
            Indique amigos e ganhe{" "}
            <strong>R$ {(data?.reward_per_install_brl || 50).toFixed(2)}</strong>{" "}
            por cada instalação confirmada.
          </p>

          {/* Badge de Ranking Global */}
          {data?.ranking && (
            <div data-testid="referrals-ranking-badge" style={{
              marginTop: 12, padding: "8px 12px",
              background: "rgba(255,255,255,0.18)",
              border: "1px solid rgba(255,255,255,0.35)",
              borderRadius: 999, display: "inline-flex",
              alignItems: "center", gap: 8, backdropFilter: "blur(8px)",
            }}>
              <span style={{ fontSize: 16 }}>🏆</span>
              {data.ranking.position ? (
                <span style={{ fontSize: 12, fontWeight: 700,
                                  letterSpacing: 0.3 }}>
                  Sua posição: <strong style={{ fontSize: 14 }}>#{data.ranking.position}</strong>
                  {" "}de {data.ranking.total_referrers}
                  {data.ranking.position === 1 && " 👑"}
                  {data.ranking.position === 2 && " 🥈"}
                  {data.ranking.position === 3 && " 🥉"}
                </span>
              ) : (
                <span style={{ fontSize: 12, fontWeight: 600,
                                  letterSpacing: 0.3 }}>
                  Indique seu 1° amigo pra entrar no ranking!
                </span>
              )}
            </div>
          )}
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "18px",
                        fontSize: 13, color: C_PRIMARY }}>
          {loading && (
            <div style={{ color: C_MUTED, textAlign: "center", padding: 32 }}>
              Carregando…
            </div>
          )}
          {error && (
            <div data-testid="referrals-error" style={{
              background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca",
              borderRadius: 10, padding: "10px 12px", fontSize: 12,
            }}>{error}</div>
          )}
          {!loading && !error && data && (
            <>
              {/* Stats grid */}
              <div data-testid="referrals-stats" style={{
                display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
                gap: 8, marginBottom: 16,
              }}>
                <StatCard label="Indicações" value={stats.total ?? 0} />
                <StatCard label="Instaladas" value={stats.installed ?? 0}
                            accent="#16a34a" />
                <StatCard label="A receber"
                            value={`R$ ${(stats.available_brl ?? 0).toFixed(0)}`}
                            accent={C_ACCENT} />
              </div>

              {/* Meta de bônus 30 instalações = R$ 500 */}
              {data.goal && (
                <GoalCard goal={data.goal} />
              )}

              {/* Share link card */}
              <div style={{
                background: "#f8fafc", border: "1.5px dashed #0d9488",
                borderRadius: 14, padding: 14, marginBottom: 16,
              }}>
                <div style={{ fontSize: 10, fontWeight: 800,
                                color: C_ACCENT, letterSpacing: 1,
                                marginBottom: 4, textTransform: "uppercase" }}>
                  Seu link de indicação
                </div>
                <div data-testid="referrals-share-url" style={{
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 12, color: C_PRIMARY, wordBreak: "break-all",
                  padding: "8px 10px", background: "#fff",
                  borderRadius: 8, border: "1px solid #e2e8f0",
                  marginBottom: 10,
                }}>{shareUrl}</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                                gap: 8 }}>
                  <button
                    data-testid="referrals-copy-btn"
                    onClick={handleCopy}
                    style={{
                      padding: "11px 14px", borderRadius: 10,
                      background: "#fff", border: "1.5px solid #0d9488",
                      color: C_ACCENT, fontWeight: 700, fontSize: 13,
                      cursor: "pointer",
                      display: "inline-flex", alignItems: "center",
                      justifyContent: "center", gap: 6,
                    }}>
                    {copied ? "✓ Copiado!" : "📋 Copiar"}
                  </button>
                  <button
                    data-testid="referrals-share-btn"
                    onClick={handleShare}
                    style={{
                      padding: "11px 14px", borderRadius: 10,
                      background: C_ACCENT, border: 0,
                      color: "#fff", fontWeight: 700, fontSize: 13,
                      cursor: "pointer",
                      display: "inline-flex", alignItems: "center",
                      justifyContent: "center", gap: 6,
                    }}>
                    🚀 Compartilhar
                  </button>
                </div>
              </div>

              {/* Como funciona */}
              <div style={{
                background: "#fefce8", border: "1px solid #fde68a",
                borderRadius: 12, padding: 12, marginBottom: 16,
                fontSize: 12, color: "#78350f", lineHeight: 1.6,
              }}>
                <div style={{ fontWeight: 800, marginBottom: 6, fontSize: 13 }}>
                  💡 Como funciona
                </div>
                <ol style={{ paddingLeft: 18, margin: 0 }}>
                  <li>Compartilhe seu link com amigos e conhecidos.</li>
                  <li>Eles preenchem um formulário rápido na landing.</li>
                  <li>Nossa Isabella entra em contato e fecha a instalação.</li>
                  <li>
                    Você ganha <strong>R$ 50</strong> por cada instalação confirmada.
                  </li>
                </ol>
              </div>

              {/* Indicações recentes */}
              {data.recent && data.recent.length > 0 ? (
                <div data-testid="referrals-recent">
                  <div style={{ fontSize: 10, fontWeight: 800,
                                  color: C_MUTED, letterSpacing: 1,
                                  marginBottom: 8, textTransform: "uppercase" }}>
                    Indicações recentes
                  </div>
                  {data.recent.map((r) => (
                    <div key={r.id}
                          data-testid={`referral-row-${r.id}`}
                          style={{
                            display: "flex", justifyContent: "space-between",
                            alignItems: "center", padding: "10px 0",
                            borderBottom: "1px solid #f1f5f9",
                          }}>
                      <span style={{ fontSize: 13, fontWeight: 600 }}>
                        {r.friend_name}
                      </span>
                      <StatusPill status={r.status} />
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{
                  textAlign: "center", padding: 16, color: C_MUTED,
                  fontSize: 12, fontStyle: "italic",
                }}>
                  Ainda sem indicações. Compartilhe seu link! 🚀
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, accent }) {
  return (
    <div style={{
      background: "#fff", border: "1px solid #e2e8f0",
      borderRadius: 10, padding: "10px 8px", textAlign: "center",
    }}>
      <div style={{
        fontSize: 18, fontWeight: 800, color: accent || C_PRIMARY,
        letterSpacing: -0.5,
      }}>{value}</div>
      <div style={{
        fontSize: 9, color: C_MUTED, textTransform: "uppercase",
        letterSpacing: 0.8, fontWeight: 700, marginTop: 2,
      }}>{label}</div>
    </div>
  );
}

function GoalCard({ goal }) {
  const reached = goal.reached;
  const pct = Math.max(2, goal.pct || 0); // mínimo 2% pra mostrar a barra
  const remaining = goal.remaining || 0;
  return (
    <div data-testid="referrals-goal" style={{
      background: reached
        ? "linear-gradient(135deg,#dcfce7,#bbf7d0)"
        : "linear-gradient(135deg,#fef3c7,#fde68a)",
      border: reached ? "1.5px solid #16a34a" : "1.5px solid #f59e0b",
      borderRadius: 14, padding: 14, marginBottom: 16,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "flex-start", gap: 8, marginBottom: 8 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 10, fontWeight: 800,
                          color: reached ? "#14532d" : "#78350f",
                          letterSpacing: 1, textTransform: "uppercase",
                          marginBottom: 2 }}>
            🎯 Meta de Bônus
          </div>
          <div style={{ fontSize: 14, fontWeight: 800,
                          color: reached ? "#14532d" : "#78350f",
                          lineHeight: 1.3 }}>
            {goal.target_installs} instalações ={" "}
            <span style={{ color: "#15803d" }}>
              R$ {goal.bonus_brl.toFixed(0)}
            </span>{" "}
            extras
          </div>
        </div>
        <div style={{
          background: "#fff", padding: "4px 10px", borderRadius: 999,
          border: reached ? "1.5px solid #16a34a" : "1.5px solid #f59e0b",
          fontSize: 11, fontWeight: 800,
          color: reached ? "#14532d" : "#78350f", whiteSpace: "nowrap",
        }}>
          {goal.current_installs} / {goal.target_installs}
        </div>
      </div>
      <div style={{
        position: "relative", height: 10, borderRadius: 999,
        background: "rgba(255,255,255,0.6)", overflow: "hidden",
      }}>
        <div data-testid="referrals-goal-bar" style={{
          height: "100%", width: `${pct}%`,
          background: reached
            ? "linear-gradient(90deg,#16a34a,#15803d)"
            : "linear-gradient(90deg,#f59e0b,#d97706)",
          borderRadius: 999, transition: "width .6s ease",
        }} />
      </div>
      <div style={{
        marginTop: 6, fontSize: 11, color: reached ? "#14532d" : "#78350f",
        fontWeight: 600,
      }}>
        {reached
          ? "🎉 Parabéns! Bônus de R$ " + goal.bonus_brl.toFixed(0) + " desbloqueado!"
          : remaining === 1
          ? "🔥 Falta SÓ 1 instalação pra desbloquear o bônus!"
          : `Faltam ${remaining} instalações pro bônus de R$ ${goal.bonus_brl.toFixed(0)}.`}
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  const map = {
    contacted: { bg: "#dbeafe", color: "#1e3a8a", label: "Contatado" },
    installed: { bg: "#dcfce7", color: "#14532d", label: "✓ Instalado" },
    converted: { bg: "#dcfce7", color: "#14532d", label: "✓ Convertido" },
  };
  const cfg = map[status] || { bg: "#f1f5f9", color: "#475569", label: status };
  return (
    <span style={{
      background: cfg.bg, color: cfg.color,
      padding: "3px 8px", borderRadius: 999, fontSize: 10,
      fontWeight: 800, letterSpacing: 0.3, textTransform: "uppercase",
    }}>{cfg.label}</span>
  );
}
