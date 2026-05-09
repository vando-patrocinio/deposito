import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";

export default function NotificationsBell() {
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);

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
      <button
        data-testid="notifications-bell-btn"
        onClick={() => setOpen(!open)}
        style={{
          position: "relative", background: "white", border: "1px solid #e2e8f0",
          borderRadius: 999, padding: "6px 10px", cursor: "pointer", fontSize: 16,
        }}
        title="Notificações"
      >
        🔔
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
                  onClick={() => markRead(n.id)}
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
