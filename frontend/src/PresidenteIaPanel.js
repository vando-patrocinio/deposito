/* PresidenteIaPanel.js — Sistema Nervoso Corporativo (V10)

   V10 Update: O miolo dashboard foi substituído por PresidenteExecutivo
   (decisão monetizada). Mantém Header, BriefingModal (Café com IA),
   Leo Proativo e ConselhoExecutivo (pareceres LLM). */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import PresidenteExecutivo from "@/components/PresidenteExecutivo";
import {
  BrainCircuit, ChevronDown, Clock, Coffee, RefreshCw,
  Settings, Sparkles, X, Zap,
} from "lucide-react";

const ORACLE = {
  purple: "#4b1d7a", orange: "#f28c28",
  green: "#237a4b", red: "#b42318",
  border: "#e2e8f0",
};

export default function PresidenteIaPanel() {
  const [council, setCouncil] = useState(null);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [err, setErr] = useState("");
  const [showBriefing, setShowBriefing] = useState(false);

  const fetchCouncil = async () => {
    setLoading(true); setErr("");
    try {
      const c = await api._client.get("/presidente-ia/conselho");
      setCouncil(c.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const c = await api._client.get("/presidente-ia/conselho");
        if (!cancelled) setCouncil(c.data);
      } catch (e) {
        if (!cancelled) setErr(e?.response?.data?.detail || e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const runScan = async () => {
    setScanning(true); setErr("");
    try {
      await api._client.post("/presidente-ia/scan");
      await fetchCouncil();
    } catch (e) { setErr(e.message); }
    setScanning(false);
  };

  const runLeoProactive = async () => {
    setScanning(true); setErr("");
    try {
      const r = await api._client.post(
        "/presidente-ia/leo/proactive");
      const d = r.data || {};
      setErr(`Leo Proativo: ${d.sent || 0} mensagem(ns) enviada(s), `
              + `${d.skipped_cooldown || 0} em cooldown, `
              + `${d.total_candidates || 0} candidato(s) total.`);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setScanning(false);
  };

  const regenerateCouncil = async () => {
    setLoading(true);
    try {
      const c = await api._client.get(
        "/presidente-ia/conselho?force=true");
      setCouncil(c.data);
    } catch (e) { setErr(e.message); }
    setLoading(false);
  };

  return (
    <div data-testid="presidente-ia-panel" style={{
      display: "flex", flexDirection: "column", gap: 16, padding: "0 4px",
    }}>
      <ExecActionBar loading={loading} scanning={scanning}
                       onScan={runScan} onRefresh={fetchCouncil}
                       onBriefing={() => setShowBriefing(true)}
                       onLeoProactive={runLeoProactive} />

      {showBriefing && (
        <BriefingModal onClose={() => setShowBriefing(false)} />
      )}

      {err && (
        <div data-testid="pres-error" style={{
          background: "#fef2f2", color: ORACLE.red, padding: "10px 14px",
          borderRadius: 8, fontSize: 13, fontWeight: 600,
        }}>{err}</div>
      )}

      {/* V10: Cérebro Executivo monetizado (substitui dashboard) */}
      <PresidenteExecutivo />

      {/* Conselho Executivo IA (pareceres LLM — não é dashboard) */}
      {council?.items && (
        <ConselhoExecutivo items={council.items}
                              onRegenerate={regenerateCouncil} />
      )}
    </div>
  );
}

// ─────────────────── Barra de ações (substitui Header) ───────────────────
function ExecActionBar({ loading, scanning, onScan, onRefresh,
                              onBriefing, onLeoProactive }) {
  return (
    <div style={{
      display: "flex", justifyContent: "flex-end", flexWrap: "wrap",
      gap: 8, alignItems: "center",
    }}>
      <button onClick={onBriefing}
               data-testid="pres-briefing-btn"
               style={btnSec()}>
        <Coffee size={13} />
        Café com IA
      </button>
      <button onClick={onRefresh} disabled={loading || scanning}
               data-testid="pres-refresh"
               style={btnSec()}>
        <RefreshCw size={13}
          style={{ animation: loading ? "spin 1s linear infinite" : "none" }} />
        Conselho
      </button>
      <button onClick={onScan} disabled={loading || scanning}
               data-testid="pres-scan-btn"
               style={btnPrimary()}>
        <Zap size={13}
          style={{ animation: scanning ? "pulse 1s ease infinite" : "none" }} />
        {scanning ? "Varrendo…" : "Varredura proativa"}
      </button>
      <button onClick={onLeoProactive} disabled={loading || scanning}
               data-testid="pres-leo-proactive-btn"
               style={{ ...btnPrimary(), background: ORACLE.orange }}>
        <Sparkles size={13} />
        Leo Proativo
      </button>
      <style>{`
        @keyframes spin { from {transform:rotate(0)} to {transform:rotate(360deg)} }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
      `}</style>
    </div>
  );
}

function ConselhoExecutivo({ items, onRegenerate }) {
  return (
    <div data-testid="conselho-executivo">
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: `linear-gradient(135deg, ${ORACLE.purple}, #6d28d9)`,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <BrainCircuit size={16} color="white" />
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                           color: "var(--text-primary)" }}>
              Conselho Executivo IA
            </h2>
            <div style={{ fontSize: 10, color: "#64748b" }}>
              6 cadeiras especializadas · Claude Sonnet 4.6 · cache 60min
            </div>
          </div>
        </div>
        <button onClick={onRegenerate}
                 data-testid="council-regenerate"
                 style={btnSec()}>
          <Sparkles size={11} /> Regerar Conselho
        </button>
      </div>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
        gap: 12,
      }}>
        {items.map((c) => (
          <CouncilCard key={c.role} c={c} />
        ))}
      </div>
    </div>
  );
}

function CouncilCard({ c }) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid={`council-card-${c.role}`} style={{
      background: "white", border: `1px solid ${ORACLE.border}`,
      borderTop: `4px solid ${c.color}`, borderRadius: 10, padding: 14,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: c.color }}>
          {c.label}
        </div>
        {c.from_cache && (
          <span style={{
            fontSize: 9, color: "#64748b", fontWeight: 700,
            display: "flex", alignItems: "center", gap: 3,
          }}><Clock size={9} /> cache</span>
        )}
      </div>
      <div style={{
        fontSize: 12, color: "#334155", lineHeight: 1.55,
        whiteSpace: "pre-wrap",
        maxHeight: open ? "unset" : 200,
        overflow: "hidden", position: "relative",
      }}>
        {c.parecer}
        {!open && c.parecer && c.parecer.length > 400 && (
          <div style={{
            position: "absolute", inset: "auto 0 0 0", height: 60,
            background: "linear-gradient(transparent, white)",
          }} />
        )}
      </div>
      {c.parecer && c.parecer.length > 400 && (
        <button onClick={() => setOpen(!open)} style={{
          background: "none", border: "none", color: c.color,
          fontSize: 11, fontWeight: 700, cursor: "pointer",
          marginTop: 4, padding: 0,
          display: "flex", alignItems: "center", gap: 4,
        }}>
          {open ? "Recolher" : "Ler mais"}
          <ChevronDown size={11} style={{
            transform: open ? "rotate(180deg)" : "none",
            transition: "transform .15s",
          }} />
        </button>
      )}
    </div>
  );
}

// ─────────────────── Briefing Modal (iter219) ───────────────────
function BriefingModal({ onClose }) {
  const [settings, setSettings] = useState({ enabled: false, phone: "" });
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const s = await api._client.get(
          "/presidente-ia/briefing/settings");
        setSettings({
          enabled: !!s.data.enabled,
          phone: s.data.phone || "",
        });
        const p = await api._client.get(
          "/presidente-ia/briefing/preview");
        setPreview(p.data);
      } catch (e) { setErr(e.message); }
    })();
  }, []);

  const save = async () => {
    setBusy(true); setErr(""); setMsg("");
    try {
      await api._client.put("/presidente-ia/briefing/settings",
        settings);
      setMsg("Configuração salva!");
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setBusy(false);
  };

  const testSend = async () => {
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await api._client.post("/presidente-ia/briefing/test");
      if (r.data.ok) {
        setMsg(`Briefing enviado para ${r.data.sent_to}!`);
      } else {
        setErr(r.data.error || "Falha no envio");
      }
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setBusy(false);
  };

  return (
    <div onClick={onClose} data-testid="briefing-modal-backdrop" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,0.6)",
      zIndex: 1000, display: "flex", alignItems: "center",
      justifyContent: "center", padding: 20,
    }}>
      <div onClick={(e) => e.stopPropagation()}
            data-testid="briefing-modal" style={{
        background: "white", borderRadius: 12, width: "100%",
        maxWidth: 560, maxHeight: "90vh", overflow: "auto",
      }}>
        <div style={{
          padding: "14px 20px", borderBottom: `1px solid ${ORACLE.border}`,
          display: "flex", justifyContent: "space-between",
          alignItems: "center",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 8,
              background: `linear-gradient(135deg, ${ORACLE.orange}, #d97706)`,
              display: "flex", alignItems: "center",
              justifyContent: "center",
            }}>
              <Coffee size={18} color="white" />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 15, fontWeight: 800,
                             color: ORACLE.purple }}>
                Café com a IA do CEO
              </h2>
              <div style={{ fontSize: 10, color: "#64748b" }}>
                Briefing executivo diário às 08:00 BRT no WhatsApp
              </div>
            </div>
          </div>
          <button onClick={onClose} data-testid="briefing-modal-close"
                   style={{ background: "none", border: "none",
                              cursor: "pointer", color: "#64748b" }}>
            <X size={18} />
          </button>
        </div>

        <div style={{ padding: 20, display: "flex",
                        flexDirection: "column", gap: 14 }}>
          {/* Preview */}
          {preview && (
            <div>
              <div style={{
                fontSize: 11, fontWeight: 700, color: "#475569",
                textTransform: "uppercase", letterSpacing: .4,
                marginBottom: 6,
              }}>Prévia da mensagem</div>
              <div data-testid="briefing-preview" style={{
                background: "#dcf8c6", color: "#0f172a",
                padding: "12px 14px", borderRadius: 8,
                fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap",
                border: "1px solid #c8e6a0",
                fontFamily: "-apple-system,sans-serif",
              }}>{preview.text}</div>
            </div>
          )}

          {/* Settings */}
          <div style={{ display: "flex", flexDirection: "column",
                          gap: 8 }}>
            <label style={{
              display: "flex", alignItems: "center", gap: 8,
              fontSize: 13, fontWeight: 700, color: "#334155",
              cursor: "pointer",
            }}>
              <input type="checkbox" checked={settings.enabled}
                      data-testid="briefing-enabled"
                      onChange={(e) => setSettings({
                        ...settings, enabled: e.target.checked })} />
              Habilitar envio automático às 08:00 BRT (diariamente)
            </label>
            <label style={{
              fontSize: 11, fontWeight: 700, color: "#475569",
              textTransform: "uppercase", letterSpacing: .4,
            }}>Telefone WhatsApp do gestor</label>
            <input value={settings.phone}
                    data-testid="briefing-phone"
                    onChange={(e) => setSettings({
                      ...settings, phone: e.target.value })}
                    placeholder="5511999998888 (DDI + DDD + número)"
                    style={{
                      padding: "9px 12px", fontSize: 13,
                      border: `1px solid ${ORACLE.border}`,
                      borderRadius: 6, outline: "none",
                    }} />
          </div>

          {err && (
            <div data-testid="briefing-error" style={{
              background: "#fef2f2", color: ORACLE.red,
              padding: "8px 12px", borderRadius: 6, fontSize: 12,
              fontWeight: 600,
            }}>{err}</div>
          )}
          {msg && (
            <div data-testid="briefing-success" style={{
              background: `${ORACLE.green}15`, color: ORACLE.green,
              padding: "8px 12px", borderRadius: 6, fontSize: 12,
              fontWeight: 600,
            }}>{msg}</div>
          )}

          <div style={{ display: "flex", gap: 8,
                          justifyContent: "flex-end" }}>
            <button onClick={onClose}
                     data-testid="briefing-cancel" style={btnSec()}>
              Fechar
            </button>
            <button onClick={testSend} disabled={busy || !settings.phone}
                     data-testid="briefing-test"
                     style={{ ...btnSec(),
                                color: ORACLE.orange,
                                border: `1px solid ${ORACLE.orange}` }}>
              <Coffee size={12} /> Enviar agora (teste)
            </button>
            <button onClick={save} disabled={busy}
                     data-testid="briefing-save"
                     style={btnPrimary()}>
              <Settings size={12} /> Salvar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────── Helpers UI ───────────────────
function Card({ title, icon: Icon, color, children }) {
  return (
    <div style={{
      background: "white", border: `1px solid ${ORACLE.border}`,
      borderRadius: 12, padding: 14, display: "flex",
      flexDirection: "column", gap: 8,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 26, height: 26, borderRadius: 6,
          background: `${color}15`, color,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}><Icon size={14} /></div>
        <h3 style={{ margin: 0, fontSize: 13, fontWeight: 800,
                       color: "#0f172a" }}>{title}</h3>
      </div>
      {children}
    </div>
  );
}

function MiniRow({ label, v, ok, bad }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between",
      fontSize: 11, padding: "3px 0",
      borderBottom: `1px dashed ${ORACLE.border}`,
    }}>
      <span style={{ color: "#64748b" }}>{label}</span>
      <span style={{
        fontWeight: 800,
        color: bad ? ORACLE.red : (ok ? ORACLE.green : "#0f172a"),
      }}>{typeof v === "number" ? v.toLocaleString("pt-BR") : v}</span>
    </div>
  );
}

function btnSec() {
  return {
    padding: "8px 14px", fontSize: 12, fontWeight: 700,
    border: `1px solid ${ORACLE.border}`, borderRadius: 8,
    background: "white", color: "#64748b", cursor: "pointer",
    display: "flex", alignItems: "center", gap: 6,
  };
}

function btnPrimary() {
  return {
    padding: "8px 16px", fontSize: 12, fontWeight: 700,
    border: "none", borderRadius: 8,
    background: ORACLE.purple, color: "white", cursor: "pointer",
    display: "flex", alignItems: "center", gap: 6,
  };
}

