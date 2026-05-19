import React, { useEffect, useState } from "react";
import { Database, Download, RefreshCw, AlertCircle, CheckCircle2, Users, Cloud } from "lucide-react";
import { api } from "@/api";
import { Card } from "@/ui";

/**
 * Sub-painel Atlaz — vive dentro do Central IA.
 * Mostra preview, KPIs, último sync e botão para puxar /listaclientes.
 */
export default function AtlazSubPanel() {
  const [stats, setStats] = useState(null);
  const [preview, setPreview] = useState(null);
  const [syncRes, setSyncRes] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadStats = async () => {
    try {
      const r = await api.atlazCustomerStats();
      setStats(r);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  };

  const loadPreview = async () => {
    setError("");
    try {
      const r = await api.atlazCustomerPreview();
      setPreview(r);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  };

  useEffect(() => {
    Promise.all([loadStats(), loadPreview()]).finally(() => setLoading(false));
  }, []);

  const runSync = async () => {
    if (!await window.confirm(
      "Iniciar sincronização de assinantes do Atlaz?\n\n" +
      "Pode levar 1-3 minutos para bases grandes (~2.800 clientes).\n" +
      "Não bloqueia o painel — você pode continuar usando."
    )) return;
    setBusy(true); setError(""); setSyncRes(null);
    try {
      const r = await api.atlazCustomerSync();
      setSyncRes(r);
      await loadStats();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const lastSyncFmt = stats?.last_sync_at
    ? new Date(stats.last_sync_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })
    : "nunca";

  return (
    <div data-testid="atlaz-subpanel" style={{ display: "grid", gap: 14 }}>
      <Card style={{ padding: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{
            width: 48, height: 48, borderRadius: 12,
            background: "linear-gradient(135deg,#1e293b,#0f172a)",
            color: "white", display: "grid", placeItems: "center",
            boxShadow: "0 4px 14px rgba(15,23,42,.35)",
          }}>
            <Database size={22} strokeWidth={1.8} />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700, letterSpacing: "-0.015em", color: "var(--text-primary)" }}>
              Atlaz · Base de Assinantes
            </h2>
            <p style={{ margin: "3px 0 0", color: "var(--text-secondary)", fontSize: 12, lineHeight: 1.45 }}>
              Sincronize a base de clientes do Atlaz para o SmartProv. Isso alimenta a Isabella IA com nome, CPF, e-mail, telefone e dia de vencimento — usados para matching automático no chat.
            </p>
          </div>
          <button
            data-testid="atlaz-sync-btn"
            onClick={runSync}
            disabled={busy}
            style={{
              padding: "10px 18px", borderRadius: 10, border: 0,
              background: busy ? "#94a3b8" : "#0f172a",
              color: "white", fontSize: 13, fontWeight: 700,
              cursor: busy ? "not-allowed" : "pointer",
              display: "inline-flex", alignItems: "center", gap: 8,
              boxShadow: busy ? "none" : "0 4px 14px rgba(15,23,42,.25)",
            }}
          >
            {busy ? <RefreshCw size={14} className="ci-spin" /> : <Download size={14} />}
            {busy ? "Sincronizando…" : "Sync from Atlaz"}
          </button>
        </div>
      </Card>

      {/* KPIs */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10 }}>
        <Tile label="Total no Atlaz" value={preview ? preview.estimated_total.toLocaleString("pt-BR") : "—"} icon={<Cloud size={15} />} accent="#0ea5e9" />
        <Tile label="Local (SmartProv)" value={stats ? stats.local_total.toLocaleString("pt-BR") : "—"} icon={<Database size={15} />} accent="#10b981" />
        <Tile label="Importados Atlaz" value={stats ? stats.local_from_atlaz.toLocaleString("pt-BR") : "—"} icon={<Users size={15} />} accent="#8b5cf6" />
        <Tile label="Último sync" value={lastSyncFmt} compact />
      </div>

      {/* Erro */}
      {error && (
        <Card style={{ padding: 14, borderLeft: "4px solid #dc2626", background: "rgba(239,68,68,.05)" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 10, color: "#b91c1c", fontSize: 13 }}>
            <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
            <div><strong>Falha:</strong> {error}</div>
          </div>
        </Card>
      )}

      {/* Resultado do sync (mostra após executar) */}
      {syncRes && (
        <Card style={{ padding: 14, borderLeft: "4px solid #10b981", background: "rgba(16,185,129,.05)" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 10, fontSize: 13 }}>
            <CheckCircle2 size={16} style={{ flexShrink: 0, marginTop: 1, color: "#10b981" }} />
            <div style={{ flex: 1 }}>
              <strong style={{ color: "var(--text-primary)" }}>Sincronização concluída em {syncRes.duration_s}s</strong>
              <div style={{ marginTop: 6, display: "flex", gap: 14, flexWrap: "wrap", color: "var(--text-secondary)", fontSize: 12 }}>
                <span><strong style={{ color: "var(--text-primary)" }}>{syncRes.items_seen}</strong> itens lidos</span>
                <span><strong style={{ color: "#10b981" }}>{syncRes.inserted}</strong> novos</span>
                <span><strong style={{ color: "#0ea5e9" }}>{syncRes.updated}</strong> atualizados</span>
                <span><strong style={{ color: "#8b5cf6" }}>{syncRes.phones_attached}</strong> telefones vinculados</span>
                {syncRes.errors > 0 && <span style={{ color: "#dc2626" }}>{syncRes.errors} erros</span>}
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Preview de amostra */}
      <Card style={{ padding: 0 }}>
        <div style={{ padding: 14, borderBottom: "1px solid var(--border-default)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5 }}>
            Amostra (primeiros 10 clientes da página 1)
          </div>
          <button
            data-testid="atlaz-preview-reload"
            onClick={loadPreview}
            style={{ background: "transparent", border: "1px solid var(--border-default)", borderRadius: 8, padding: "4px 10px", fontSize: 11, color: "var(--text-secondary)", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 5 }}
          >
            <RefreshCw size={12} /> Atualizar
          </button>
        </div>

        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            <RefreshCw size={20} className="ci-spin" /> Consultando Atlaz…
          </div>
        ) : preview?.sample?.length ? (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "var(--bg-surface-2)", color: "var(--text-muted)", textTransform: "uppercase", fontSize: 10, letterSpacing: 0.5 }}>
                  <th style={th}>ID Atlaz</th>
                  <th style={th}>Nome</th>
                  <th style={th}>CPF/CNPJ</th>
                  <th style={th}>Telefone</th>
                  <th style={th}>E-mail</th>
                  <th style={{ ...th, textAlign: "center" }}>Venc.</th>
                </tr>
              </thead>
              <tbody>
                {preview.sample.map((c) => (
                  <tr key={c.id_assinante} style={{ borderBottom: "1px solid var(--border-default)" }}>
                    <td style={{ ...td, fontFamily: "ui-monospace, monospace", color: "var(--text-muted)" }}>{c.id_assinante}</td>
                    <td style={{ ...td, fontWeight: 600 }}>{c.nome}</td>
                    <td style={{ ...td, fontFamily: "ui-monospace, monospace" }}>{c.cpf_cnpj || "—"}</td>
                    <td style={{ ...td, fontFamily: "ui-monospace, monospace" }}>{c.telefone || "—"}</td>
                    <td style={{ ...td, color: "var(--text-secondary)" }}>{c.email || "—"}</td>
                    <td style={{ ...td, textAlign: "center" }}>{c.dia_de_vencimento || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            Nenhum dado para mostrar.
          </div>
        )}
      </Card>

      <style>{`@keyframes ci-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
                .ci-spin { animation: ci-spin 1s linear infinite; }`}</style>
    </div>
  );
}

const th = { padding: "8px 14px", textAlign: "left", fontWeight: 700 };
const td = { padding: "8px 14px", color: "var(--text-primary)" };

function Tile({ label, value, icon, accent = "#0ea5e9", compact }) {
  return (
    <Card style={{ padding: 14 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 10, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
        {icon && <span style={{ color: accent }}>{icon}</span>}
      </div>
      <div style={{ fontSize: compact ? 13 : 22, fontWeight: 700, color: "var(--text-primary)", marginTop: 4 }}>{value}</div>
    </Card>
  );
}
