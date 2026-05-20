import React, { useEffect, useState } from "react";
import { api } from "@/api";

const TONES = {
  ok: { bg: "#d1fae5", fg: "#065f46", border: "#10b981", icon: "✅" },
  warn: { bg: "#fef3c7", fg: "#92400e", border: "#f59e0b", icon: "⚠️" },
  critical: { bg: "#fee2e2", fg: "#991b1b", border: "#ef4444", icon: "🔴" },
};

function StatusBanner({ overall, checkedAt }) {
  const tone = TONES[overall] || TONES.warn;
  const label = {
    ok: "Saúde dos dados: TUDO OK",
    warn: "Saúde dos dados: ATENÇÃO",
    critical: "Saúde dos dados: CRÍTICO",
  }[overall] || "Saúde dos dados";
  return (
    <div
      data-testid="dh-status-banner"
      style={{
        background: tone.bg,
        color: tone.fg,
        border: `1px solid ${tone.border}`,
        borderLeft: `5px solid ${tone.border}`,
        padding: "16px 20px",
        borderRadius: 14,
        marginBottom: 22,
        display: "flex",
        alignItems: "center",
        gap: 16,
      }}
    >
      <div style={{ fontSize: 32 }}>{tone.icon}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 800, fontSize: 16 }}>{label}</div>
        <div style={{ fontSize: 12, opacity: 0.85, marginTop: 2 }}>
          Verificado em {new Date(checkedAt).toLocaleString("pt-BR")}
        </div>
      </div>
    </div>
  );
}

function Card({ title, children, accent }) {
  return (
    <div style={{
      background: "white",
      border: `1px solid ${accent || "#e2e8f0"}`,
      borderRadius: 14,
      padding: 20,
      boxShadow: "0 1px 3px rgba(15,23,42,.04)",
    }}>
      <div style={{
        fontSize: 11,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        fontWeight: 700,
        color: "#64748b",
        marginBottom: 12,
      }}>{title}</div>
      {children}
    </div>
  );
}

function BackupCard({ backup }) {
  if (!backup?.exists) {
    return (
      <Card title="Backup MongoDB" accent="#ef4444">
        <div style={{ fontSize: 28, fontWeight: 900, color: "#991b1b" }}>
          Nenhum backup
        </div>
        <div style={{ fontSize: 12, color: "#64748b", marginTop: 6,
                       lineHeight: 1.5 }}>
          {backup?.hint || "Agendar cron com /app/backend/scripts/backup_mongo.sh"}
        </div>
        <div style={{ marginTop: 12, padding: 10, background: "#0f172a",
                       color: "#e2e8f0", borderRadius: 8, fontSize: 11,
                       fontFamily: "monospace" }}>
          0 */6 * * * /app/backend/scripts/backup_mongo.sh
        </div>
      </Card>
    );
  }
  const fresh = backup.age_seconds < 86400;
  return (
    <Card title="Backup MongoDB"
           accent={fresh ? "#10b981" : "#f59e0b"}>
      <div style={{ fontSize: 28, fontWeight: 900,
                     color: fresh ? "#065f46" : "#92400e" }}>
        {backup.age_human} atrás
      </div>
      <div style={{ fontSize: 13, color: "#475569", marginTop: 4 }}>
        {backup.size_human}  ·  {backup.total_backups} backup(s) retidos
      </div>
      <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4,
                     fontFamily: "monospace", wordBreak: "break-all" }}>
        {backup.file}
      </div>
    </Card>
  );
}

function MigrationsCard({ migrations, onRun, runningMigrations }) {
  const ok = !migrations.pending?.length && !migrations.orphan?.length;
  return (
    <Card title="Migrations de Schema"
           accent={ok ? "#10b981" : "#f59e0b"}>
      <div style={{ fontSize: 28, fontWeight: 900,
                     color: ok ? "#065f46" : "#92400e" }}>
        {migrations.applied_count}/{migrations.defined_count}
      </div>
      <div style={{ fontSize: 12, color: "#475569", marginTop: 6 }}>
        aplicadas
      </div>
      {migrations.pending?.length > 0 && (
        <div style={{ marginTop: 10, padding: 8, background: "#fef3c7",
                       borderRadius: 6, fontSize: 11 }}>
          ⚠️ Pendentes: {migrations.pending.join(", ")}
          <button
            onClick={onRun}
            disabled={runningMigrations}
            data-testid="dh-run-migrations"
            style={{
              marginTop: 6, padding: "4px 10px", fontSize: 11,
              background: "#0f172a", color: "white", border: "none",
              borderRadius: 6, cursor: runningMigrations
                ? "not-allowed" : "pointer", fontWeight: 600,
            }}
          >
            {runningMigrations ? "Rodando…" : "Rodar pendentes"}
          </button>
        </div>
      )}
      {migrations.orphan?.length > 0 && (
        <div style={{ marginTop: 10, padding: 8, background: "#fee2e2",
                       borderRadius: 6, fontSize: 11, color: "#991b1b" }}>
          🔴 Drift: {migrations.orphan.join(", ")} — código sumiu mas
          ficaram registradas no banco
        </div>
      )}
    </Card>
  );
}

function CollectionsTable({ collections, total }) {
  return (
    <div style={{
      background: "white", border: "1px solid #e2e8f0",
      borderRadius: 14, padding: 22, marginTop: 22,
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "baseline", marginBottom: 16,
      }}>
        <div style={{
          fontSize: 11, textTransform: "uppercase",
          letterSpacing: "0.06em", fontWeight: 700, color: "#64748b",
        }}>Coleções protegidas (cadastros do cliente)</div>
        <div style={{ fontSize: 13, color: "#0f172a", fontWeight: 700 }}>
          {total.toLocaleString("pt-BR")} documentos
        </div>
      </div>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
        gap: 8,
      }}>
        {collections.map((c) => (
          <div
            key={c.name}
            data-testid={`dh-coll-${c.name}`}
            style={{
              padding: "8px 12px",
              background: c.count === 0 ? "#fef3c7" : "#f8fafc",
              border: `1px solid ${c.count === 0 ? "#fcd34d" : "#e2e8f0"}`,
              borderRadius: 8,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              fontSize: 12,
            }}
          >
            <span style={{ color: "#475569", fontFamily: "monospace" }}>
              {c.name}
            </span>
            <span style={{
              fontWeight: 800,
              color: c.count === 0 ? "#92400e" : "#0f172a",
            }}>
              {c.count.toLocaleString("pt-BR")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AlertsList({ alerts }) {
  if (!alerts?.length) {
    return (
      <div style={{
        background: "#d1fae5", border: "1px solid #10b981",
        padding: "12px 16px", borderRadius: 12, marginBottom: 22,
        fontSize: 13, color: "#065f46", fontWeight: 600,
      }}>
        ✅ Nenhum alerta. Tudo nos eixos.
      </div>
    );
  }
  return (
    <div style={{ marginBottom: 22 }}>
      {alerts.map((a, i) => {
        const tone = TONES[a.level] || TONES.warn;
        return (
          <div
            key={i}
            data-testid={`dh-alert-${a.level}`}
            style={{
              background: tone.bg, color: tone.fg,
              border: `1px solid ${tone.border}`,
              padding: "10px 14px", borderRadius: 10,
              fontSize: 13, marginBottom: 8,
              display: "flex", alignItems: "center", gap: 10,
            }}
          >
            <span style={{ fontSize: 18 }}>{tone.icon}</span>
            <span>{a.message}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function DataHealthPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [runningMigrations, setRunningMigrations] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const d = await api.dataHealth();
      setData(d);
      setErr("");
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function runMigrations() {
    setRunningMigrations(true);
    try {
      const r = await api.dataHealthRunMigrations();
      window.alert(`Migrations: ${r.applied?.length || 0} aplicadas, `
        + `${r.skipped?.length || 0} já estavam OK, `
        + `${r.failed?.length || 0} falharam`);
      await load();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setRunningMigrations(false);
    }
  }

  if (loading) {
    return <div style={{ padding: 22, color: "#64748b" }}>
      Carregando saúde dos dados...
    </div>;
  }
  if (err) {
    return <div style={{ padding: 22, color: "#991b1b" }}>{err}</div>;
  }
  if (!data) return null;

  return (
    <div style={{ padding: 22, maxWidth: 1300 }} data-testid="data-health-panel">
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 20,
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 900,
                         color: "#0f172a" }}>
            Saúde dos Dados
          </h2>
          <div style={{ fontSize: 13, color: "#64748b", marginTop: 2 }}>
            Backup, migrations e cadastros do cliente que persistem entre
            deploys.{" "}
            <a href="/app/memory/DATA_PERSISTENCE.md"
                style={{ color: "#10b981" }}>política completa</a>
          </div>
        </div>
        <button
          onClick={load}
          data-testid="dh-refresh"
          style={{
            padding: "8px 16px", background: "#0f172a", color: "white",
            border: "none", borderRadius: 8, cursor: "pointer",
            fontSize: 13, fontWeight: 600,
          }}
        >
          🔄 Atualizar
        </button>
      </div>

      <StatusBanner overall={data.overall} checkedAt={data.checked_at} />
      <AlertsList alerts={data.alerts} />

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
        gap: 14,
      }}>
        <BackupCard backup={data.backup} />
        <MigrationsCard
          migrations={data.migrations}
          onRun={runMigrations}
          runningMigrations={runningMigrations}
        />
      </div>

      <CollectionsTable
        collections={data.collections}
        total={data.collections_total_documents}
      />

      <div style={{
        marginTop: 22, padding: 14, background: "#f1f5f9",
        borderRadius: 10, fontSize: 12, color: "#475569",
        lineHeight: 1.6,
      }}>
        <strong>💡 Política de persistência:</strong> Nada acima é apagado
        em deploy. Seeds são idempotentes. Migrations são aditivas. Para
        agendar backup automatizado em produção:{" "}
        <code style={{ background: "white", padding: "2px 6px",
                         borderRadius: 4 }}>
          crontab -e
        </code>{" "}
        e adicione{" "}
        <code style={{ background: "white", padding: "2px 6px",
                         borderRadius: 4 }}>
          0 */6 * * * /app/backend/scripts/backup_mongo.sh
        </code>
      </div>
    </div>
  );
}
