import React, { useEffect, useMemo, useState } from "react";
import { IsabellaCard } from "@/FieldOpsIsabella";
import FieldOpsEstoque from "@/FieldOpsEstoque";
import FieldOpsFrota from "@/FieldOpsFrota";
import ErrorBoundary from "@/ErrorBoundary";

/* ============================================================================
   LousaFieldHeader — absorve Smart Field Ops dentro da Lousa Mobile.
   - Métricas calculadas LOCALMENTE a partir de data.tickets (sem JWT)
   - Status GPS local (navigator.geolocation)
   - Acesso a Isabella IA / Estoque / Frota como overlays sob demanda
   Field Ops foi descontinuado como tela separada — tudo vem daqui.
============================================================================ */

const todayBR = () => {
  // Retorna {start, end} em UTC ISO cobrindo o "hoje" no fuso BR
  const now = new Date();
  const tzOff = now.getTimezoneOffset(); // minutos locais → UTC
  // Hoje BR é 00:00–24:00 em America/Sao_Paulo (-03:00)
  const todayBrStr = new Date(now.getTime() - tzOff * 60000)
    .toISOString().slice(0, 10);
  const start = `${todayBrStr}T03:00:00.000Z`; // 00:00 BR = 03:00 UTC
  const next = new Date(`${todayBrStr}T03:00:00.000Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  return { start, end: next.toISOString(), todayBrStr };
};

function MetricBox({ label, value, warn }) {
  const ok = !warn || !value;
  return (
    <div style={{
      flex: 1, minWidth: 64,
      padding: "10px 6px", borderRadius: 10,
      background: ok ? "#f8fafc" : "#fef2f2",
      border: `1px solid ${ok ? "#eef2f7" : "#fecaca"}`,
      textAlign: "center",
    }}>
      <div style={{
        fontSize: 20, fontWeight: 800,
        color: ok ? "#0f172a" : "#b91c1c",
        lineHeight: 1,
      }}>{value ?? 0}</div>
      <div style={{
        fontSize: 9, fontWeight: 700, color: "#64748b",
        textTransform: "uppercase", letterSpacing: 0.5, marginTop: 4,
      }}>{label}</div>
    </div>
  );
}

function MiniBtn({ icon, label, onClick, testid }) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      style={{
        flex: 1, minWidth: 90,
        height: 40, borderRadius: 10,
        border: "1px solid #e2e8f0",
        background: "white",
        color: "#0f172a", fontWeight: 700, fontSize: 12,
        cursor: "pointer",
        display: "inline-flex", alignItems: "center",
        justifyContent: "center", gap: 6,
      }}
    >
      <span style={{ fontSize: 14 }}>{icon}</span>
      {label}
    </button>
  );
}

function Overlay({ title, onClose, testid, children }) {
  return (
    <div
      data-testid={testid}
      style={{
        position: "fixed", inset: 0, zIndex: 9000,
        background: "rgba(15,23,42,.45)",
        display: "flex", alignItems: "flex-end", justifyContent: "center",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        background: "#f8fafc",
        width: "100%", maxWidth: 480,
        maxHeight: "92vh", overflowY: "auto",
        borderTopLeftRadius: 18, borderTopRightRadius: 18,
        padding: 16, boxShadow: "0 -10px 30px rgba(15,23,42,.25)",
      }}>
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "center", marginBottom: 12,
        }}>
          <div style={{ fontWeight: 800, fontSize: 14, color: "#0f172a" }}>
            {title}
          </div>
          <button
            data-testid={`${testid}-close`}
            onClick={onClose}
            style={{
              border: 0, background: "transparent",
              fontSize: 22, cursor: "pointer", color: "#64748b",
              padding: "0 6px",
            }}
          >×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export default function LousaFieldHeader({ tickets, collaboratorId, onOpenOs }) {
  // ── Métricas locais (sem JWT, baseadas no payload público da Lousa) ──
  const counts = useMemo(() => {
    const ts = Array.isArray(tickets) ? tickets : [];
    const { start, end } = todayBR();
    const inToday = (iso) => iso && iso >= start && iso < end;
    const nowIso = new Date().toISOString();
    const pendentes = ts.filter((t) => t.status === "pendente"
      && inToday(t.scheduled_time));
    const abertas = ts.filter((t) => t.status === "aberta");
    const finalizadas = ts.filter((t) =>
      (t.status === "finalizada" || t.status === "encerrada")
      && (inToday(t.closed_at) || inToday(t.finished_at)
          || inToday(t.scheduled_time)));
    const atrasadas = pendentes.filter((t) =>
      (t.scheduled_time || "") < nowIso);
    const today = pendentes.length + abertas.length + finalizadas.length;
    return {
      today,
      pendentes: pendentes.length,
      atrasadas: atrasadas.length,
      finalizadas: finalizadas.length,
    };
  }, [tickets]);

  // ── GPS local: tenta uma leitura curta, reflete status no header ──
  const [gpsOk, setGpsOk] = useState(null);
  useEffect(() => {
    let alive = true;
    const apply = (v) => { if (alive) setGpsOk(v); };
    if (!navigator.geolocation) {
      apply(false);
      return () => { alive = false; };
    }
    navigator.geolocation.getCurrentPosition(
      () => apply(true),
      () => apply(false),
      { enableHighAccuracy: false, timeout: 6000, maximumAge: 60000 },
    );
    return () => { alive = false; };
  }, []);

  const [overlay, setOverlay] = useState(null); // "isabella" | "estoque" | "frota"

  return (
    <div data-testid="lousa-field-header" style={{ marginTop: 12, marginBottom: 6 }}>
      {/* Métricas do dia */}
      <div style={{
        background: "white", border: "1px solid #e5e7eb",
        borderRadius: 14, padding: 12, marginBottom: 10,
        boxShadow: "0 1px 2px rgba(15,23,42,.04)",
      }}>
        <div style={{
          fontSize: 10, fontWeight: 700, color: "#64748b",
          letterSpacing: 1, textTransform: "uppercase", marginBottom: 8,
        }}>Meu dia em campo</div>
        <div style={{ display: "flex", gap: 6 }}>
          <MetricBox label="Hoje" value={counts.today} />
          <MetricBox label="Pendentes" value={counts.pendentes} />
          <MetricBox label="Atrasadas" value={counts.atrasadas} warn />
          <MetricBox label="Feitas" value={counts.finalizadas} />
        </div>
        <div style={{
          display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap",
          fontSize: 11, fontWeight: 600,
        }}>
          <span style={{ color: gpsOk === false ? "#b45309"
            : gpsOk ? "#065f46" : "#64748b" }}>
            GPS {gpsOk === false ? "sem sinal" : gpsOk ? "ativo" : "verificando..."}
          </span>
        </div>
        {/* Atalhos Field Ops absorvidos */}
        <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
          <MiniBtn icon="🧠" label="Isabella IA" testid="lousa-open-isabella"
            onClick={() => setOverlay("isabella")} />
          <MiniBtn icon="📦" label="Estoque" testid="lousa-open-estoque"
            onClick={() => setOverlay("estoque")} />
          <MiniBtn icon="🚐" label="Frota" testid="lousa-open-frota"
            onClick={() => setOverlay("frota")} />
        </div>
      </div>

      {overlay === "isabella" && (
        <Overlay title="Isabella Field President"
          testid="lousa-overlay-isabella"
          onClose={() => setOverlay(null)}>
          <ErrorBoundary name="lousa-isabella-overlay" variant="card"
            fallbackText="Isabella indisponível agora — faça login com sua conta SmartProv para reativar o briefing.">
            <IsabellaCard collabId={collaboratorId}
              onOpenOs={(ticketId) => {
                setOverlay(null);
                if (onOpenOs) onOpenOs(ticketId);
              }} />
          </ErrorBoundary>
        </Overlay>
      )}
      {overlay === "estoque" && (
        <Overlay title="Estoque do técnico"
          testid="lousa-overlay-estoque"
          onClose={() => setOverlay(null)}>
          <ErrorBoundary name="lousa-estoque-overlay" variant="card"
            fallbackText="Não foi possível carregar o estoque agora. Faça login com sua conta SmartProv para acessar.">
            <FieldOpsEstoque collabId={collaboratorId} readOnly={false} />
          </ErrorBoundary>
        </Overlay>
      )}
      {overlay === "frota" && (
        <Overlay title="Frota"
          testid="lousa-overlay-frota"
          onClose={() => setOverlay(null)}>
          <ErrorBoundary name="lousa-frota-overlay" variant="card"
            fallbackText="Não foi possível carregar a Frota agora. Faça login com sua conta SmartProv para acessar.">
            <FieldOpsFrota collabId={collaboratorId} readOnly={false} />
          </ErrorBoundary>
        </Overlay>
      )}
    </div>
  );
}
