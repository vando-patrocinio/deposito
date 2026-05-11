import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import {
  CalendarClock, MessageSquare, Save, Play, Loader2, CheckCircle2,
} from "lucide-react";

/**
 * Card de configuração do agendamento automático de briefings de churn.
 * Vive dentro da sub-aba "Churn" — geralmente abaixo do dashboard principal.
 */
export default function ChurnBriefingScheduleCard() {
  const [cfg, setCfg] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [hour, setHour] = useState(12);
  const [minute, setMinute] = useState(0);
  const [phone, setPhone] = useState("");
  const [windowDays, setWindowDays] = useState(30);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    setMsg("");
    try {
      const c = await api.churnScheduleGet();
      setCfg(c);
      setEnabled(!!c.enabled);
      setHour(c.hour_utc ?? 12);
      setMinute(c.minute ?? 0);
      setPhone(c.notify_phone || "");
      setWindowDays(c.window_days || 30);
    } catch (e) {
      setMsg("Erro ao carregar: " + (e?.response?.data?.detail || e.message));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true); setMsg("");
    try {
      await api.churnScheduleSave({
        enabled,
        hour_utc: parseInt(hour, 10) || 0,
        minute: parseInt(minute, 10) || 0,
        notify_phone: phone.replace(/\D/g, ""),
        window_days: parseInt(windowDays, 10) || 30,
      });
      await load();
      setMsg("Agendamento salvo.");
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const runNow = async () => {
    setRunning(true); setMsg("");
    try {
      const r = await api.churnScheduleRunNow(windowDays);
      setMsg(`Briefing gerado: ${r.id} (${r.based_on?.total_churn} churn(s))`);
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setRunning(false);
    }
  };

  if (!cfg) return null;

  // Mostra hora local (UTC-3 ≈ BRT) só para humanos
  const brtHour = (hour - 3 + 24) % 24;

  return (
    <div className="surface" data-testid="churn-schedule-card" style={{
      padding: 16, borderRadius: 12,
      border: "1px solid var(--border-default)",
      background: "linear-gradient(135deg, rgba(99,102,241,0.04), var(--bg-surface) 70%)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <CalendarClock size={14} color="#6366f1" />
        <span style={{ fontSize: 13, fontWeight: 800,
                          letterSpacing: "-0.012em" }}>
          Briefing automático diário
        </span>
        {cfg.last_run_date && (
          <span style={{
            marginLeft: "auto", fontSize: 10, fontWeight: 700,
            padding: "2px 7px", borderRadius: 999,
            background: cfg.last_whatsapp_sent ? "#dcfce7" : "#f1f5f9",
            color: cfg.last_whatsapp_sent ? "#166534" : "#475569",
          }}>
            Último: {cfg.last_run_date}
            {cfg.last_whatsapp_sent ? " · WhatsApp enviado" : ""}
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 12 }}>
        Claude Sonnet 4.5 gera um briefing por dia e envia resumo no WhatsApp do gestor.
      </div>

      <div style={{ display: "grid",
                      gridTemplateColumns: "auto 80px 80px 1fr 100px",
                      gap: 10, alignItems: "end" }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6,
                          fontSize: 12, fontWeight: 600, padding: "8px 0" }}>
          <input type="checkbox" checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  data-testid="schedule-enabled-toggle" />
          Ativar
        </label>
        <div>
          <label style={{ fontSize: 10, fontWeight: 600,
                            color: "var(--text-muted)" }}>
            Hora (UTC)
          </label>
          <input type="number" min="0" max="23"
                  value={hour}
                  onChange={(e) => setHour(e.target.value)}
                  data-testid="schedule-hour-input"
                  style={{ width: "100%", marginTop: 4, padding: "7px 8px",
                              border: "1px solid var(--border-default)",
                              borderRadius: 6, fontSize: 13 }} />
        </div>
        <div>
          <label style={{ fontSize: 10, fontWeight: 600,
                            color: "var(--text-muted)" }}>
            Minuto
          </label>
          <input type="number" min="0" max="59" step="5"
                  value={minute}
                  onChange={(e) => setMinute(e.target.value)}
                  data-testid="schedule-minute-input"
                  style={{ width: "100%", marginTop: 4, padding: "7px 8px",
                              border: "1px solid var(--border-default)",
                              borderRadius: 6, fontSize: 13 }} />
        </div>
        <div>
          <label style={{ fontSize: 10, fontWeight: 600,
                            color: "var(--text-muted)",
                            display: "flex", alignItems: "center", gap: 4 }}>
            <MessageSquare size={10} /> WhatsApp do gestor
          </label>
          <input type="tel" placeholder="55 11 99999-9999"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  data-testid="schedule-phone-input"
                  style={{ width: "100%", marginTop: 4, padding: "7px 8px",
                              border: "1px solid var(--border-default)",
                              borderRadius: 6, fontSize: 13 }} />
        </div>
        <div>
          <label style={{ fontSize: 10, fontWeight: 600,
                            color: "var(--text-muted)" }}>
            Janela
          </label>
          <select value={windowDays}
                    onChange={(e) => setWindowDays(e.target.value)}
                    data-testid="schedule-window-select"
                    style={{ width: "100%", marginTop: 4, padding: "7px 8px",
                                border: "1px solid var(--border-default)",
                                borderRadius: 6, fontSize: 13,
                                background: "var(--bg-surface)" }}>
            <option value={7}>7 dias</option>
            <option value={30}>30 dias</option>
            <option value={90}>90 dias</option>
            <option value={180}>180 dias</option>
          </select>
        </div>
      </div>

      <div style={{ marginTop: 8, fontSize: 10, color: "var(--text-muted)" }}>
        Disparo aproximado: <strong>{String(hour).padStart(2,"0")}:{String(minute).padStart(2,"0")} UTC</strong>
        {" "}(~ {String(brtHour).padStart(2,"0")}:{String(minute).padStart(2,"0")} BRT)
      </div>

      <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
        <button onClick={save} disabled={saving}
                  data-testid="schedule-save-btn"
                  style={{
                    padding: "8px 14px", border: 0, borderRadius: 8,
                    background: "var(--text-primary)", color: "#fff",
                    cursor: saving ? "wait" : "pointer",
                    display: "inline-flex", alignItems: "center", gap: 6,
                    fontSize: 12, fontWeight: 700,
                  }}>
          {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          Salvar
        </button>
        <button onClick={runNow} disabled={running}
                  data-testid="schedule-runnow-btn"
                  style={{
                    padding: "8px 14px", border: "1px solid #6366f1",
                    borderRadius: 8, background: "transparent", color: "#6366f1",
                    cursor: running ? "wait" : "pointer",
                    display: "inline-flex", alignItems: "center", gap: 6,
                    fontSize: 12, fontWeight: 700,
                  }}>
          {running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          Testar agora (sem WhatsApp)
        </button>
        {msg && (
          <span style={{
            fontSize: 11, marginLeft: "auto",
            display: "inline-flex", alignItems: "center", gap: 4,
            color: msg.startsWith("Erro") ? "#be123c" : "#166534",
            fontWeight: 600,
          }}>
            {!msg.startsWith("Erro") && <CheckCircle2 size={12} />}
            {msg}
          </span>
        )}
      </div>
    </div>
  );
}
