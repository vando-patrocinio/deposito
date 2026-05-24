import React from "react";
import { api } from "@/api";
import { Calendar, Clock, MessageCircle, X } from "lucide-react";

/* =============================================================
   ScheduledAdjustmentsCard — lista de reajustes agendados (pending).
   Mostra: plano, data, %, autor, contagem de dias restantes, botões
   "Notificar" (envia aviso prévio por WhatsApp) e "Cancelar".
============================================================= */
export default function ScheduledAdjustmentsCard({ items, onChange }) {
  const fmt = (v) => new Intl.NumberFormat("pt-BR",
        { style: "currency", currency: "BRL" }).format(v || 0);
  const cancel = async (id) => {
    if (!await window.confirm("Cancelar este reajuste agendado?")) return;
    try {
      await api.planScheduledCancel(id);
      onChange();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };
  const notify = async (item) => {
    if (item.notified_at && !await window.confirm(
        `Já foi notificado em ${new Date(item.notified_at).toLocaleString("pt-BR")} ` +
        `(${item.notified_count || 0} envios). Enviar novamente?`)) return;
    if (!item.notified_at && !await window.confirm(
        `Enviar aviso prévio via WhatsApp para TODOS os assinantes ativos do plano "${item.plan_name}"?\n\n` +
        `O sistema vai usar o template padrão (você pode customizar via API) e gravar tudo na Lousa de Chat.`)) return;
    try {
      const r = await api.planScheduledNotify(item.id);
      await window.alert(`✓ Notificação enviada!\n\n` +
            `${r.sent} mensagens enviadas\n` +
            `${r.failed} falhas\n` +
            `${r.skipped_no_phone} sem telefone cadastrado`);
      onChange();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };
  return (
    <div className="surface" data-testid="scheduled-adjustments-card" style={{
      padding: 16, borderRadius: 12,
      border: "1px solid rgba(2,132,199,.3)",
      background: "linear-gradient(135deg, rgba(2,132,199,.06), var(--bg-surface))",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                     marginBottom: 12 }}>
        <div style={{
          width: 34, height: 34, borderRadius: 9,
          background: "linear-gradient(135deg, #0284c7, #0369a1)",
          color: "#fff", display: "grid", placeItems: "center",
        }}>
          <Calendar size={16} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <strong style={{ fontSize: 13, color: "#0369a1",
                            letterSpacing: 0.2 }}>
            Reajustes agendados
          </strong>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>
            Aplicação automática na data marcada · {items.length} pendente(s)
          </div>
        </div>
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        {items.map((s) => {
          const days = Math.ceil(
            (new Date(s.scheduled_for) - new Date()) / 86400000);
          return (
            <div key={s.id}
                 data-testid={`scheduled-item-${s.id}`}
                 style={{
                   display: "grid",
                   gridTemplateColumns: "auto 1fr auto auto auto auto",
                   gap: 12, alignItems: "center",
                   padding: "10px 12px", borderRadius: 8,
                   background: "var(--bg-surface)",
                   border: "1px solid var(--border-default)",
                 }}>
              <div style={{ fontFamily: "ui-monospace, monospace",
                             fontSize: 12, color: "var(--text-primary)",
                             fontWeight: 700, minWidth: 86 }}>
                {new Date(s.scheduled_for).toLocaleDateString("pt-BR")}
              </div>
              <div style={{ minWidth: 0 }}>
                <strong style={{ fontSize: 13 }}>{s.plan_name}</strong>
                <div style={{ fontSize: 11, color: "var(--text-muted)",
                               marginTop: 1 }}>
                  +{s.pct}% · por {s.created_by_name || s.created_by}
                  {s.note && <> · "{s.note}"</>}
                </div>
              </div>
              <span style={{
                padding: "3px 9px", borderRadius: 999,
                background: days <= 7
                  ? "rgba(245,158,11,.15)" : "rgba(2,132,199,.12)",
                color: days <= 7 ? "#b45309" : "#0369a1",
                fontSize: 10, fontWeight: 800, letterSpacing: 0.3,
                display: "inline-flex", alignItems: "center", gap: 4,
                whiteSpace: "nowrap",
              }}>
                <Clock size={10} />
                {days <= 0 ? "HOJE"
                  : days === 1 ? "AMANHÃ"
                  : `EM ${days} DIAS`}
              </span>
              <button onClick={() => notify(s)}
                       className="btn btn-ghost btn-sm"
                       data-testid={`scheduled-notify-${s.id}`}
                       title={s.notified_at
                         ? `Já notificado: ${s.notified_count || 0} envios em ${new Date(s.notified_at).toLocaleDateString("pt-BR")}`
                         : "Enviar aviso prévio via WhatsApp pra todos os afetados"}
                       style={{
                         color: s.notified_at ? "var(--text-muted)" : "#16a34a",
                       }}>
                <MessageCircle size={12} />
                {s.notified_at
                  ? `✓ ${s.notified_count || 0}`
                  : "Notificar"}
              </button>
              <button onClick={() => cancel(s.id)}
                       className="btn btn-ghost btn-sm"
                       data-testid={`scheduled-cancel-${s.id}`}
                       style={{ color: "var(--danger)" }}
                       title="Cancelar agendamento">
                <X size={12} /> Cancelar
              </button>
              <span style={{
                fontSize: 9, color: "var(--text-muted)",
                fontFamily: "ui-monospace, monospace",
              }}>
                {fmt(0).replace("R$", "")
                  // placeholder pra alinhar visualmente
                  ? "" : ""}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
