/* WaBusinessHoursCard — configura horário de atendimento da empresa.
   Mensagens recebidas fora do horário caem no bucket "Fora de hora".
*/
import React, { useEffect, useState } from "react";
import { Clock, Calendar, Plus, Trash2, Save, AlertCircle, CheckCircle2 } from "lucide-react";
import { api } from "@/api";
import { Card } from "@/ui";

const WEEKDAYS = [
  { key: "0", label: "Domingo" },
  { key: "1", label: "Segunda-feira" },
  { key: "2", label: "Terça-feira" },
  { key: "3", label: "Quarta-feira" },
  { key: "4", label: "Quinta-feira" },
  { key: "5", label: "Sexta-feira" },
  { key: "6", label: "Sábado" },
];

export default function WaBusinessHoursCard() {
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState({ msg: "", type: "" });
  const [newHoliday, setNewHoliday] = useState("");

  useEffect(() => {
    api._client.get("/whatsapp-baileys/business-hours")
      .then((r) => setCfg(r.data))
      .catch(() => setCfg(null));
  }, []);

  function updateDay(key, field, value) {
    setCfg({
      ...cfg,
      weekly_schedule: {
        ...cfg.weekly_schedule,
        [key]: { ...cfg.weekly_schedule[key], [field]: value },
      },
    });
  }

  function addHoliday() {
    if (!newHoliday || !/^\d{4}-\d{2}-\d{2}$/.test(newHoliday)) {
      setStatus({ msg: "Data inválida. Use AAAA-MM-DD.", type: "error" });
      return;
    }
    if ((cfg.holidays || []).includes(newHoliday)) return;
    setCfg({ ...cfg, holidays: [...(cfg.holidays || []), newHoliday].sort() });
    setNewHoliday("");
    setStatus({ msg: "", type: "" });
  }

  function removeHoliday(d) {
    setCfg({ ...cfg, holidays: cfg.holidays.filter((x) => x !== d) });
  }

  async function save() {
    setSaving(true);
    setStatus({ msg: "", type: "" });
    try {
      const r = await api._client.put("/whatsapp-baileys/business-hours", {
        enabled: cfg.enabled,
        timezone_offset_hours: cfg.timezone_offset_hours,
        weekly_schedule: cfg.weekly_schedule,
        holidays: cfg.holidays || [],
        fora_de_hora_message: cfg.fora_de_hora_message || "",
      });
      setCfg(r.data.config);
      setStatus({
        msg: `Horário salvo. Status agora: ${r.data.is_outside_now ? "FORA DO HORÁRIO" : "DENTRO DO HORÁRIO"}.`,
        type: "ok",
      });
    } catch (e) {
      setStatus({ msg: e?.response?.data?.detail || e.message, type: "error" });
    } finally {
      setSaving(false);
    }
  }

  if (!cfg) {
    return (
      <Card style={{ padding: 16 }}>
        <p style={{ color: "#64748b" }}>Carregando horário de atendimento...</p>
      </Card>
    );
  }

  return (
    <Card style={{ padding: 0 }} data-testid="wa-business-hours-card">
      <div style={{ padding: 16, borderBottom: "1px solid #e2e8f0",
                     display: "flex", alignItems: "center", gap: 10 }}>
        <Clock size={20} style={{ color: "#0ea5e9" }} />
        <div style={{ flex: 1 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#0f172a" }}>
            Horário de Atendimento
          </h3>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "#64748b" }}>
            Mensagens recebidas fora do horário caem no bucket{" "}
            <strong>"Fora de hora"</strong> automaticamente.
          </p>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8,
                         fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
          <input type="checkbox" checked={!!cfg.enabled}
                 data-testid="wa-bh-enabled"
                 onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} />
          Ativar
        </label>
      </div>

      <div style={{ padding: 16, opacity: cfg.enabled ? 1 : 0.5,
                     pointerEvents: cfg.enabled ? "auto" : "none" }}>
        {/* Grade de horários */}
        <div style={{ display: "grid", gap: 8 }}>
          {WEEKDAYS.map((d) => {
            const day = cfg.weekly_schedule[d.key] || { enabled: false, open: "08:00", close: "18:00" };
            return (
              <div key={d.key} style={{
                display: "grid", gridTemplateColumns: "180px 80px 1fr 1fr",
                gap: 10, alignItems: "center", padding: 8,
                borderRadius: 8, background: day.enabled ? "#f0f9ff" : "#f8fafc",
                border: `1px solid ${day.enabled ? "#bae6fd" : "#e2e8f0"}`,
              }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8,
                                 fontSize: 13, fontWeight: 600 }}>
                  <input type="checkbox" checked={!!day.enabled}
                          data-testid={`wa-bh-day-${d.key}`}
                          onChange={(e) => updateDay(d.key, "enabled", e.target.checked)} />
                  {d.label}
                </label>
                <span style={{ fontSize: 11, color: "#64748b" }}>
                  {day.enabled ? "Atende" : "Fechado"}
                </span>
                <div>
                  <label style={{ display: "block", fontSize: 10, color: "#64748b",
                                   fontWeight: 700, marginBottom: 2 }}>ABERTURA</label>
                  <input type="time" value={day.open}
                         disabled={!day.enabled}
                         onChange={(e) => updateDay(d.key, "open", e.target.value)}
                         style={timeInput} />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 10, color: "#64748b",
                                   fontWeight: 700, marginBottom: 2 }}>FECHAMENTO</label>
                  <input type="time" value={day.close}
                         disabled={!day.enabled}
                         onChange={(e) => updateDay(d.key, "close", e.target.value)}
                         style={timeInput} />
                </div>
              </div>
            );
          })}
        </div>

        {/* Feriados */}
        <div style={{ marginTop: 18 }}>
          <h4 style={{ fontSize: 12, fontWeight: 700, color: "#475569",
                        letterSpacing: 0.5, textTransform: "uppercase",
                        margin: "0 0 8px", display: "flex", alignItems: "center", gap: 6 }}>
            <Calendar size={14} /> Feriados (dias fechados)
          </h4>
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <input type="date" value={newHoliday}
                    data-testid="wa-bh-holiday-input"
                    onChange={(e) => setNewHoliday(e.target.value)}
                    style={{ ...timeInput, flex: 1 }} />
            <button onClick={addHoliday}
                     data-testid="wa-bh-holiday-add"
                     style={btnSecondary}>
              <Plus size={14} /> Adicionar
            </button>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {(cfg.holidays || []).length === 0 && (
              <span style={{ fontSize: 12, color: "#94a3b8" }}>Nenhum feriado configurado.</span>
            )}
            {(cfg.holidays || []).map((h) => (
              <span key={h}
                     data-testid={`wa-bh-holiday-${h}`}
                     style={{
                       padding: "4px 10px", borderRadius: 999, fontSize: 12,
                       background: "#fee2e2", color: "#991b1b", fontWeight: 600,
                       display: "inline-flex", alignItems: "center", gap: 4,
                     }}>
                {h}
                <button onClick={() => removeHoliday(h)}
                         style={{ border: "none", background: "transparent",
                                   cursor: "pointer", color: "#991b1b",
                                   display: "grid", placeItems: "center" }}>
                  <Trash2 size={11} />
                </button>
              </span>
            ))}
          </div>
        </div>

        {/* Mensagem fora de hora */}
        <div style={{ marginTop: 18 }}>
          <label style={{ fontSize: 12, fontWeight: 700, color: "#475569",
                           letterSpacing: 0.5, textTransform: "uppercase",
                           display: "block", marginBottom: 6 }}>
            Mensagem automática "fora do horário" (opcional)
          </label>
          <textarea
            data-testid="wa-bh-message"
            value={cfg.fora_de_hora_message || ""}
            onChange={(e) => setCfg({ ...cfg, fora_de_hora_message: e.target.value })}
            placeholder="Ex: Olá! Nosso atendimento humano está fechado agora. Retornaremos amanhã às 8h. ⏰"
            rows={3}
            style={{ width: "100%", padding: 10, borderRadius: 8,
                      border: "1px solid #cbd5e1", fontSize: 13,
                      fontFamily: "inherit", resize: "vertical" }} />
        </div>
      </div>

      {/* Footer */}
      <div style={{ padding: 12, borderTop: "1px solid #e2e8f0",
                     display: "flex", justifyContent: "space-between",
                     alignItems: "center", background: "#f8fafc",
                     borderBottomLeftRadius: 12, borderBottomRightRadius: 12 }}>
        <div style={{ fontSize: 12 }}>
          {status.msg && (
            <span style={{
              color: status.type === "ok" ? "#16a34a" : "#dc2626",
              display: "inline-flex", alignItems: "center", gap: 4, fontWeight: 600,
            }}>
              {status.type === "ok" ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
              {status.msg}
            </span>
          )}
        </div>
        <button onClick={save} disabled={saving}
                 data-testid="wa-bh-save"
                 style={btnPrimary}>
          <Save size={14} /> {saving ? "Salvando..." : "Salvar configuração"}
        </button>
      </div>
    </Card>
  );
}

const timeInput = {
  padding: "6px 10px", borderRadius: 6, border: "1px solid #cbd5e1",
  fontSize: 13, fontFamily: "inherit", width: "100%",
};
const btnPrimary = {
  padding: "8px 16px", borderRadius: 8, fontSize: 13, fontWeight: 700,
  background: "#0ea5e9", color: "white", border: "none", cursor: "pointer",
  display: "inline-flex", alignItems: "center", gap: 6,
};
const btnSecondary = {
  padding: "6px 12px", borderRadius: 6, fontSize: 12, fontWeight: 600,
  background: "white", color: "#475569", border: "1px solid #cbd5e1",
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4,
};
