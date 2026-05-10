import React, { useEffect, useState, useCallback } from "react";
import { Bell } from "lucide-react";
import { api } from "@/api";
import useEventStream from "@/useEventStream";

export default function NotificationsBell({ onOpenAIPanel } = {}) {
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [pulse, setPulse] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await api.notificationsList(false);
      setItems(r.items || []);
      setUnread(r.unread_count || 0);
    } catch {}
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh]);

  // SSE — recebe notificação ao vivo, faz pulse na bell + insert no topo
  const { connected } = useEventStream({
    onNotification: (n) => {
      setItems((prev) => [n, ...prev.filter((x) => x.id !== n.id)].slice(0, 200));
      setUnread((u) => u + 1);
      setPulse(true);
      setTimeout(() => setPulse(false), 2400);
      // tenta tocar beep de notificação (best-effort)
      try {
        const audio = new Audio("data:audio/mp3;base64,SUQzAwAAAAAAEFRJVDIAAAAGAAAATm90aWY=");
        audio.volume = 0.3;
        audio.play().catch(() => {});
      } catch {}
    },
  });

  async function markRead(nid) {
    await api.notificationRead(nid);
    refresh();
  }

  async function markAllRead() {
    await api.notificationsReadAll();
    refresh();
  }

  return (
    <div style={{ position: "relative" }} data-testid="notifications-bell-wrapper">
      <style>{`
        @keyframes notif-pulse {
          0%, 100% { transform: scale(1); }
          25% { transform: scale(1.2) rotate(-12deg); }
          50% { transform: scale(1.15) rotate(10deg); }
          75% { transform: scale(1.1) rotate(-6deg); }
        }
        .notif-pulse { animation: notif-pulse 0.9s ease-in-out 2; }
      `}</style>
      <button
        data-testid="notifications-bell-btn"
        onClick={() => setOpen(!open)}
        className={`btn btn-ghost btn-sm btn-icon ${pulse ? "notif-pulse" : ""}`.trim()}
        style={{ position: "relative", width: 32, height: 32 }}
        title={connected ? "Notificações · ao vivo" : "Notificações · offline"}
      >
        <Bell size={15} strokeWidth={1.75} />
        <span data-testid="notifications-live-dot" style={{
          position: "absolute", bottom: -1, left: -1,
          width: 10, height: 10, borderRadius: "50%",
          background: connected ? "#10b981" : "#94a3b8",
          border: "2px solid white",
          boxShadow: connected ? "0 0 0 2px rgba(16,185,129,.18)" : "none",
        }} />
        {unread > 0 && (
          <span style={{
            position: "absolute", top: -4, right: -4,
            background: "#dc2626", color: "white", borderRadius: 999,
            fontSize: 10, fontWeight: 800, padding: "1px 6px", minWidth: 16,
          }}>{unread}</span>
        )}
      </button>

      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 80 }} />
          <div data-testid="notifications-dropdown" style={{
            position: "absolute", right: 0, top: "calc(100% + 8px)",
            background: "white", border: "1px solid #e2e8f0", borderRadius: 14,
            boxShadow: "0 18px 40px rgba(15,23,42,.18)", width: 360,
            maxHeight: 480, overflowY: "auto", zIndex: 90, padding: 12,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <strong>Notificações ({items.length})</strong>
              {unread > 0 && (
                <button onClick={markAllRead} style={{ background: "none", border: "none", color: "#3b82f6", cursor: "pointer", fontSize: 12, fontWeight: 700 }}>
                  Marcar todas
                </button>
              )}
            </div>
            {items.length === 0 && (
              <div style={{ color: "#94a3b8", textAlign: "center", padding: 30, fontSize: 13 }}>
                Sem notificações.
              </div>
            )}
            {items.map((n) => {
              const isUnread = !(n.read_by || []).some((x) => x);  // simplificado
              const sevColor = n.severity === "critical" ? "#dc2626" : n.severity === "warning" ? "#f59e0b" : "#3b82f6";
              return (
                <div
                  key={n.id}
                  onClick={() => {
                    markRead(n.id);
                    if (n.type === "ai_preventive_suggestion" && onOpenAIPanel) {
                      onOpenAIPanel();
                      setOpen(false);
                    }
                  }}
                  data-testid={`notif-${n.id}`}
                  style={{
                    padding: 10, borderRadius: 10,
                    background: isUnread ? "#fef9c3" : "#f8fafc",
                    border: `1px solid ${sevColor}`,
                    marginBottom: 6, cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 800, color: sevColor }}>{n.title}</div>
                  <div style={{ fontSize: 12, color: "#475569", marginTop: 2 }}>{n.message}</div>
                  <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 4 }}>
                    {new Date(n.created_at).toLocaleString("pt-BR")}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
