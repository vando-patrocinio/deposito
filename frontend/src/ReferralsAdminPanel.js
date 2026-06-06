import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

/**
 * Painel admin de Indicações — lista solicitações de PIX/desconto
 * pendentes e permite gestor aprovar/rejeitar. Acesso: administrador,
 * gestor, financeiro, auditor.
 */
const STATUS = {
  pending:  { label: "Pendente", color: "#a16207", bg: "#fef9c3" },
  paid:     { label: "Pago",     color: "#15803d", bg: "#dcfce7" },
  rejected: { label: "Rejeitado", color: "#b91c1c", bg: "#fee2e2" },
};

export default function ReferralsAdminPanel() {
  const [items, setItems] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [filter, setFilter] = useState("pending");
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, dash] = await Promise.all([
        api._client.get("/referrals/admin/payouts").then((res) => res.data),
        api._client.get("/referrals/admin/dashboard").then((res) => res.data),
      ]);
      setItems(r.items || []);
      setDashboard(dash);
      setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function decide(id, action) {
    setBusy(id);
    try {
      await api._client.post(`/referrals/admin/payouts/${id}/${action}`);
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(null); }
  }

  const [blasting, setBlasting] = useState(false);
  const [blastMsg, setBlastMsg] = useState(null);

  async function blastInvite(force = false) {
    const confirmMsg = force
      ? "RE-ENVIAR convite pra TODOS os assinantes ATIVOS (mesmo quem já recebeu)?"
      : "Enviar convite do Indique e Ganhe pra todos os assinantes ATIVOS que ainda não receberam?\n\n(Cada um recebe só 1x — disparo a ~50/min com throttle)";
    if (!window.confirm(confirmMsg)) return;
    setBlasting(true); setBlastMsg(null); setErr(null);
    try {
      const url = force
        ? "/referrals/admin/blast-invite?force=1"
        : "/referrals/admin/blast-invite";
      const r = await api._client.post(url).then((res) => res.data);
      setBlastMsg(r.message || `Disparado para ${r.queued} assinantes`);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBlasting(false); }
  }

  const visible = items.filter((p) => filter === "all" || p.status === filter);
  const totalPending = items.filter((p) => p.status === "pending")
    .reduce((acc, p) => acc + Number(p.amount || 0), 0);

  return (
    <div data-testid="referrals-admin" style={{ padding: 24, maxWidth: 1100, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "#0f172a" }}>
            Indicações · Solicitações de PIX
          </h2>
          <p style={{ margin: "6px 0 0", color: "#64748b", fontSize: 14 }}>
            Clientes pediram resgate do saldo acumulado. Aprove pra pagar via PIX
            (ou aplicar como desconto na próxima fatura).
          </p>
        </div>
        <div style={{ textAlign: "right", display: "flex", gap: 10,
                       alignItems: "center" }}>
          <a
            href="/cliente"
            target="_blank"
            rel="noopener noreferrer"
            data-testid="open-customer-app"
            style={{
              padding: "8px 14px",
              background: "white", color: "#0f766e",
              border: "1px solid #99f6e4", borderRadius: 8,
              fontSize: 12, fontWeight: 700, cursor: "pointer",
              textDecoration: "none",
              display: "inline-flex", alignItems: "center", gap: 6,
            }}
            title="Abre o app do cliente em uma nova aba"
          >
            Ver app do cliente
          </a>
          <div>
            <div style={{ fontSize: 11, color: "#64748b" }}>Pendente</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: "#a16207" }}>
              R$ {totalPending.toFixed(2)}
            </div>
          </div>
        </div>
      </div>

      {/* KPIs de crescimento & engajamento */}
      {dashboard && <DashboardCards d={dashboard} />}

      {/* Bloco de blast — convidar todos os assinantes ATIVOS pro app */}
      <div style={{
        background: "linear-gradient(135deg, #ecfdf5, #d1fae5)",
        border: "1px solid #6ee7b7", borderRadius: 12, padding: 14,
        marginBottom: 18, display: "flex", gap: 12,
        alignItems: "center", flexWrap: "wrap",
      }} data-testid="blast-block">
        <div style={{ flex: 1, minWidth: 280 }}>
          <div style={{ fontWeight: 700, color: "#065f46", marginBottom: 4 }}>
            Convidar todos os assinantes ATIVOS
          </div>
          <div style={{ fontSize: 12, color: "#047857" }}>
            Dispara uma mensagem WhatsApp pra cada assinante apresentando o
            programa <b>Indique e Ganhe</b> + o link do app do cliente +
            link de indicação personalizado. Cada um recebe só 1x
            (throttle ~50/min).
          </div>
          {blastMsg && (
            <div style={{
              marginTop: 8, padding: "6px 10px", background: "white",
              border: "1px solid #6ee7b7", borderRadius: 6,
              fontSize: 12, color: "#065f46",
            }} data-testid="blast-result">
              ✓ {blastMsg}
            </div>
          )}
        </div>
        <button
          data-testid="blast-invite-btn"
          onClick={() => blastInvite(false)}
          disabled={blasting}
          style={{
            padding: "10px 18px",
            background: blasting ? "#94a3b8" : "#0d9488",
            color: "white", border: 0, borderRadius: 10,
            fontSize: 13, fontWeight: 700, cursor: "pointer",
            boxShadow: "0 4px 12px rgba(13,148,136,.3)",
          }}>
          {blasting ? "Disparando…" : "Disparar convite"}
        </button>
        <button
          data-testid="blast-invite-force-btn"
          onClick={() => blastInvite(true)}
          disabled={blasting}
          title="Reenviar para TODOS, inclusive quem já recebeu"
          style={{
            padding: "10px 14px",
            background: "white", color: "#0f766e",
            border: "1px solid #99f6e4", borderRadius: 10,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
          }}>
          ↻ Re-enviar
        </button>
      </div>

      {/* Bloco de Configuração da Campanha (mensagem + arte) */}
      <CampaignConfigCard />



      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        {[
          { id: "pending", label: "Pendentes" },
          { id: "paid", label: "Pagos" },
          { id: "rejected", label: "Rejeitados" },
          { id: "all", label: "Todos" },
        ].map((f) => (
          <button key={f.id}
                  data-testid={`ref-admin-filter-${f.id}`}
                  onClick={() => setFilter(f.id)}
                  style={{
                    padding: "6px 14px", borderRadius: 999,
                    background: filter === f.id ? "#0d9488" : "white",
                    color: filter === f.id ? "white" : "#475569",
                    border: filter === f.id ? "none" : "1px solid #cbd5e1",
                    fontSize: 12, fontWeight: 600, cursor: "pointer",
                  }}>{f.label}</button>
        ))}
      </div>

      {err && (
        <div style={{ background: "#fef2f2", color: "#b91c1c", padding: 10,
                        borderRadius: 8, fontSize: 13, marginBottom: 12 }}>
          {err}
        </div>
      )}

      {loading ? (
        <div style={{ padding: 40, textAlign: "center", color: "#94a3b8" }}>Carregando…</div>
      ) : visible.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "#94a3b8",
                       background: "white", borderRadius: 12, border: "1px dashed #cbd5e1" }}>
          Nenhuma solicitação.
        </div>
      ) : (
        <div style={{ background: "white", borderRadius: 12, border: "1px solid #e2e8f0",
                       overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={th}>Cliente</th>
                <th style={th}>Chave PIX</th>
                <th style={th}>Método</th>
                <th style={th}>Valor</th>
                <th style={th}>Status</th>
                <th style={th}>Data</th>
                <th style={th}>Ações</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((p) => {
                const s = STATUS[p.status] || STATUS.pending;
                return (
                  <tr key={p.id} data-testid={`payout-row-${p.id}`}
                       style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={td}>
                      <div style={{ fontWeight: 600 }}>{p.owner_name || "—"}</div>
                      <div style={{ fontSize: 11, color: "#94a3b8" }}>
                        {p.owner_external_code || p.owner_subscriber_id}
                        {p.owner_phone && ` · +${p.owner_phone}`}
                      </div>
                    </td>
                    <td style={{ ...td, fontFamily: "JetBrains Mono, monospace", fontSize: 12 }}>
                      {p.pix_key_snapshot || "—"}
                      <div style={{ fontSize: 10, color: "#94a3b8" }}>{p.pix_key_type_snapshot}</div>
                    </td>
                    <td style={td}>{p.method === "pix" ? "PIX" : "Desconto fatura"}</td>
                    <td style={{ ...td, fontWeight: 700 }}>R$ {Number(p.amount).toFixed(2)}</td>
                    <td style={td}>
                      <span style={{ background: s.bg, color: s.color, padding: "3px 10px",
                                       borderRadius: 999, fontSize: 11, fontWeight: 700 }}>
                        {s.label}
                      </span>
                    </td>
                    <td style={{ ...td, fontSize: 12, color: "#64748b" }}>
                      {(p.created_at || "").slice(0, 16).replace("T", " ")}
                    </td>
                    <td style={td}>
                      {p.status === "pending" && (
                        <div style={{ display: "flex", gap: 6 }}>
                          <button data-testid={`approve-${p.id}`}
                                  disabled={busy === p.id}
                                  onClick={() => decide(p.id, "approve")}
                                  style={{ padding: "4px 10px", background: "#0d9488",
                                            color: "white", border: 0, borderRadius: 6,
                                            cursor: "pointer", fontSize: 11, fontWeight: 700 }}>
                            ✓ Pagar
                          </button>
                          <button data-testid={`reject-${p.id}`}
                                  disabled={busy === p.id}
                                  onClick={() => decide(p.id, "reject")}
                                  style={{ padding: "4px 10px", background: "#fef2f2",
                                            color: "#b91c1c", border: "1px solid #fca5a5",
                                            borderRadius: 6, cursor: "pointer", fontSize: 11,
                                            fontWeight: 700 }}>
                            ✕
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const th = { padding: "10px 12px", fontSize: 11, fontWeight: 700,
              color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5 };
const td = { padding: "10px 12px", fontSize: 13, color: "#0f172a", verticalAlign: "top" };

/* ============================================================ */
/* Dashboard cards — KPIs de crescimento + engajamento          */
/* ============================================================ */
function DashboardCards({ d }) {
  const fmt = (n) => Number(n || 0).toLocaleString("pt-BR");
  const brl = (n) => `R$ ${Number(n || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  return (
    <div data-testid="ref-admin-dashboard" style={{ marginBottom: 18 }}>
      {/* Linha 1: KPIs com growth */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 12, marginBottom: 12,
      }}>
        <KpiCard
          label="Indicações (30d)"
          value={fmt(d.indications.current)}
          delta={d.indications.growth_pct}
          icon=""
          tooltip={`vs ${d.indications.previous} no período anterior`}
        />
        <KpiCard
          label="Instalações (30d)"
          value={fmt(d.installs.current)}
          delta={d.installs.growth_pct}
          icon="✅"
          tooltip={`vs ${d.installs.previous} no período anterior`}
          highlight
        />
        <KpiCard
          label="Conversão (30d)"
          value={`${d.conversion_pct_30d}%`}
          delta={null}
          icon=""
          tooltip="Instalações ÷ Indicações"
        />
        <KpiCard
          label="Indicadores ativos"
          value={fmt(d.active_referrers.current)}
          delta={d.active_referrers.growth_pct}
          icon=""
          tooltip="Clientes únicos que indicaram nos últimos 30d"
        />
      </div>

      {/* Linha 2: totais all-time + penetração */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 12, marginBottom: 12,
      }}>
        <KpiCard label="Total pago" value={brl(d.totals_all_time.paid_brl)} icon="" />
        <KpiCard label="Saldo disponível" value={brl(d.totals_all_time.available_brl)} icon="" />
        <KpiCard label="A aprovar" value={brl(d.totals_all_time.pending_brl)} icon="⏳" />
        <KpiCard
          label="Adesão ao programa"
          value={`${d.base.penetration_pct}%`}
          icon=""
          tooltip={`${d.base.eligible_referrers} de ${d.base.active_subscribers} ativos`}
        />
      </div>

      {/* Sparkline + Top performers */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1.4fr 1fr", gap: 12,
        marginBottom: 4,
      }}>
        <SparklineCard data={d.sparkline_30d} />
        <TopPerformersCard top={d.top_referrers_30d} />
      </div>
    </div>
  );
}

function KpiCard({ label, value, delta, icon, tooltip, highlight }) {
  return (
    <div title={tooltip || ""} style={{
      background: highlight
        ? "linear-gradient(135deg, #ecfdf5, #fff)"
        : "white",
      border: `1px solid ${highlight ? "#86efac" : "#e2e8f0"}`,
      borderRadius: 12, padding: 14,
    }}>
      <div style={{ display: "flex", alignItems: "baseline",
                     justifyContent: "space-between" }}>
        <span style={{ fontSize: 22 }}>{icon}</span>
        {delta !== null && delta !== undefined && (
          <span style={{
            fontSize: 11, fontWeight: 700,
            color: delta > 0 ? "#15803d" : delta < 0 ? "#b91c1c" : "#64748b",
            background: delta > 0 ? "#dcfce7"
                          : delta < 0 ? "#fee2e2" : "#f1f5f9",
            padding: "2px 8px", borderRadius: 999,
          }}>
            {delta > 0 ? "↑" : delta < 0 ? "↓" : "·"} {Math.abs(delta)}%
          </span>
        )}
      </div>
      <div style={{ fontSize: 10, color: "#64748b", textTransform: "uppercase",
                      letterSpacing: 0.5, marginTop: 6 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, color: "#0f172a",
                      marginTop: 2 }}>
        {value}
      </div>
    </div>
  );
}

function SparklineCard({ data }) {
  const maxI = Math.max(1, ...data.map((d) => d.indications));
  const maxIns = Math.max(1, ...data.map((d) => d.installs));
  const max = Math.max(maxI, maxIns);
  return (
    <div data-testid="sparkline-card" style={{
      background: "white", border: "1px solid #e2e8f0", borderRadius: 12,
      padding: 14,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b",
                        letterSpacing: 1, textTransform: "uppercase" }}>
          Últimos 30 dias
        </div>
        <div style={{ display: "flex", gap: 10, fontSize: 11 }}>
          <span style={{ color: "#0d9488" }}>● Indicações</span>
          <span style={{ color: "#a16207" }}>● Instalações</span>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2,
                      height: 80, padding: "4px 2px" }}>
        {data.map((d, i) => (
          <div key={i} title={`${d.date}: ${d.indications} ind, ${d.installs} inst`}
                style={{ flex: 1, display: "flex", flexDirection: "column",
                          gap: 1, justifyContent: "flex-end" }}>
            <div style={{
              background: "#0d9488",
              height: `${(d.indications / max) * 70 + 1}px`,
              borderRadius: 2, opacity: 0.85,
            }} />
            <div style={{
              background: "#f59e0b",
              height: `${(d.installs / max) * 70 + 1}px`,
              borderRadius: 2, opacity: 0.85,
            }} />
          </div>
        ))}
      </div>
    </div>
  );
}

function TopPerformersCard({ top }) {
  return (
    <div data-testid="top-performers" style={{
      background: "white", border: "1px solid #e2e8f0", borderRadius: 12,
      padding: 14,
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b",
                      letterSpacing: 1, textTransform: "uppercase",
                      marginBottom: 10 }}>
        Top indicadores (30d)
      </div>
      {top.length === 0 ? (
        <div style={{ padding: 14, color: "#94a3b8", fontSize: 13,
                       textAlign: "center" }}>
          Sem instalações esse mês ainda.
        </div>
      ) : (
        top.map((t, i) => (
          <div key={t.subscriber_id} style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "6px 0",
            borderBottom: i === top.length - 1 ? "none" : "1px solid #f1f5f9",
          }}>
            <span style={{
              fontSize: 18, width: 26, textAlign: "center",
            }}>
              {i === 0 ? "" : i === 1 ? "" : i === 2 ? "" : `#${i + 1}`}
            </span>
            <span style={{ flex: 1, fontSize: 13, color: "#0f172a",
                            whiteSpace: "nowrap", overflow: "hidden",
                            textOverflow: "ellipsis" }}>
              {t.name || t.subscriber_id}
            </span>
            <span style={{ fontSize: 11, color: "#64748b" }}>
              {t.installs_30d}x · R$ {t.earned_30d_brl.toFixed(0)}
            </span>
          </div>
        ))
      )}
    </div>
  );
}


/* ───────────────────────────────────────────────────────────────────────── */
/* Card: Configuração da Campanha (mensagem + imagem oficial)                */
/* ───────────────────────────────────────────────────────────────────────── */
function CampaignConfigCard() {
  const [cfg, setCfg] = useState(null);
  const [message, setMessage] = useState("");
  const [image, setImage] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);
  const [ok, setOk] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await api.referralCampaignGet();
      setCfg(r);
      setMessage(r.message || "");
      setImage(r.image_data_url || "");
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  function onPickImage(e) {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!/^image\//.test(f.type)) {
      setErr("Selecione uma imagem (PNG/JPG)."); return;
    }
    if (f.size > 4 * 1024 * 1024) {
      setErr("Imagem grande — máximo 4 MB."); return;
    }
    setErr(null);
    const r = new FileReader();
    r.onload = () => setImage(String(r.result || ""));
    r.readAsDataURL(f);
  }

  async function save() {
    setSaving(true); setErr(null); setOk(null);
    try {
      const r = await api.referralCampaignPut({
        message: message.trim(),
        image_data_url: image || "",
      });
      setCfg(r);
      setOk("Campanha atualizada! O app do cliente já mostra a nova arte.");
      setTimeout(() => setOk(null), 3500);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setSaving(false); }
  }

  async function reset() {
    if (!window.confirm(
      "Restaurar a mensagem e a imagem padrão da campanha?\n" +
      "(Não afeta indicações já enviadas — só o conteúdo futuro)"
    )) return;
    setSaving(true); setErr(null);
    try {
      const r = await api.referralCampaignReset();
      setCfg(r);
      setMessage(r.message || "");
      setImage(r.image_data_url || "");
      setOk("Restaurado para o padrão de fábrica.");
      setTimeout(() => setOk(null), 3500);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setSaving(false); }
  }

  const isDirty =
    cfg && (message !== (cfg.message || "") || image !== (cfg.image_data_url || ""));

  return (
    <div data-testid="campaign-config-card" style={{
      background: "white", borderRadius: 12, padding: 16, marginBottom: 18,
      border: "1px solid #e2e8f0",
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 10, marginBottom: 10, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#6B2BFB",
                          letterSpacing: 1.5, textTransform: "uppercase" }}>
            CAMPANHA DE INDICAÇÃO
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#0f172a",
                          marginTop: 2 }}>
            Mensagem e arte que o cliente compartilha
          </div>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
            Esta mensagem + imagem aparecem no app do cliente quando ele clica
            em “Compartilhar no WhatsApp”.
            {cfg?.updated_at && (
              <> · Atualizado em <b>{new Date(cfg.updated_at).toLocaleString("pt-BR")}</b>
              {cfg.updated_by && ` por ${cfg.updated_by}`}</>
            )}
            {cfg?.is_default && (
              <> · <span style={{ color: "#a16207", fontWeight: 700 }}>Usando padrão de fábrica</span></>
            )}
          </div>
        </div>
        <button
          data-testid="campaign-config-reset"
          onClick={reset}
          disabled={saving || loading}
          style={{
            background: "transparent", border: "1px solid #e2e8f0",
            color: "#64748b", padding: "6px 12px", borderRadius: 8,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
          }}>
          ↺ Restaurar padrão
        </button>
      </div>

      {loading ? (
        <div style={{ padding: 30, textAlign: "center", color: "#94a3b8",
                        fontSize: 13 }}>Carregando…</div>
      ) : (
        <div style={{
          display: "grid", gridTemplateColumns: "minmax(160px, 220px) 1fr",
          gap: 16,
        }}>
          {/* Coluna imagem */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                            marginBottom: 6, textTransform: "uppercase",
                            letterSpacing: 0.5 }}>
              Imagem da campanha
            </div>
            <div style={{
              width: "100%", aspectRatio: "1 / 1",
              borderRadius: 10, overflow: "hidden",
              background: "#f1f5f9", border: "1px solid #e2e8f0",
              display: "grid", placeItems: "center", marginBottom: 8,
            }}>
              {image ? (
                <img
                  data-testid="campaign-config-image-preview"
                  src={image}
                  alt="arte da campanha"
                  style={{ width: "100%", height: "100%", objectFit: "cover" }}
                />
              ) : (
                <div style={{ color: "#94a3b8", fontSize: 12 }}>Sem imagem</div>
              )}
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <label
                data-testid="campaign-config-image-upload"
                htmlFor="campaign-img-file"
                style={{
                  flex: 1, textAlign: "center", cursor: "pointer",
                  background: "#FF6A1A", color: "white",
                  padding: "8px 10px", borderRadius: 8,
                  fontSize: 12, fontWeight: 700,
                }}>
                Trocar imagem
              </label>
              <input
                id="campaign-img-file" type="file" accept="image/*"
                onChange={onPickImage}
                style={{ display: "none" }}
              />
              {image && (
                <button
                  data-testid="campaign-config-image-clear"
                  onClick={() => setImage("")}
                  style={{
                    background: "transparent", border: "1px solid #e2e8f0",
                    color: "#64748b", padding: "8px 10px", borderRadius: 8,
                    fontSize: 11, cursor: "pointer",
                  }}>
                  ✕
                </button>
              )}
            </div>
            <div style={{ fontSize: 10.5, color: "#94a3b8", marginTop: 6 }}>
              PNG/JPG até 4 MB. Quadrado funciona melhor no WhatsApp.
            </div>
          </div>

          {/* Coluna mensagem */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                            marginBottom: 6, textTransform: "uppercase",
                            letterSpacing: 0.5 }}>
              Mensagem padrão
            </div>
            <textarea
              data-testid="campaign-config-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={8}
              maxLength={2000}
              placeholder="Ex.: Eu já sou cliente LIGO e indico! ..."
              style={{
                width: "100%", boxSizing: "border-box",
                border: "1px solid #cbd5e1", borderRadius: 10,
                padding: 12, fontSize: 13.5, color: "#0f172a",
                fontFamily: "inherit", resize: "vertical",
                lineHeight: 1.5,
              }}
            />
            <div style={{
              display: "flex", justifyContent: "space-between",
              alignItems: "center", fontSize: 11, color: "#94a3b8",
              marginTop: 6,
            }}>
              <span>
                O link de indicação do cliente é anexado automaticamente
                no final da mensagem.
              </span>
              <span>{message.length}/2000</span>
            </div>
          </div>
        </div>
      )}

      {err && (
        <div data-testid="campaign-config-err" style={{
          marginTop: 12, padding: 10, background: "#fef2f2",
          color: "#b91c1c", borderRadius: 8, fontSize: 13,
          border: "1px solid #fecaca",
        }}>{err}</div>
      )}
      {ok && (
        <div data-testid="campaign-config-ok" style={{
          marginTop: 12, padding: 10, background: "#ecfdf5",
          color: "#065f46", borderRadius: 8, fontSize: 13,
          border: "1px solid #6ee7b7",
        }}>✓ {ok}</div>
      )}

      <div style={{
        marginTop: 14, display: "flex", justifyContent: "flex-end", gap: 8,
      }}>
        <button
          data-testid="campaign-config-save"
          onClick={save}
          disabled={saving || loading || !isDirty || !message.trim()}
          style={{
            background: (saving || !isDirty || !message.trim())
              ? "#cbd5e1" : "#6B2BFB",
            color: "white", border: 0, padding: "10px 22px", borderRadius: 10,
            fontSize: 13, fontWeight: 700,
            cursor: (saving || !isDirty || !message.trim()) ? "not-allowed" : "pointer",
            boxShadow: (saving || !isDirty || !message.trim())
              ? "none" : "0 4px 12px rgba(107,43,251,.3)",
          }}>
          {saving ? "Salvando…" : "Salvar campanha"}
        </button>
      </div>
    </div>
  );
}

