/**
 * Dialog system — substitui window.confirm/alert/prompt nativos por modais
 * customizados com a identidade visual SmartProv/Ligo.
 *
 * Uso:
 *   import { appConfirm, appAlert, appPrompt } from "@/dialog";
 *   if (!(await appConfirm("Tem certeza?"))) return;
 *   await appAlert("Operação concluída!");
 *   const nome = await appPrompt("Qual o nome?", "Padrão");
 *
 * Internamente, o componente <DialogHost /> escuta um event bus interno e
 * renderiza o modal correto. Mountar UMA vez no topo da árvore (App.js).
 *
 * Também monkey-patcha window.confirm/alert/prompt para que código legado
 * que ainda chama o nativo passe a ver a versão customizada (precisa await).
 *
 * HISTÓRICO: cada modal exibido fica registrado em buffer circular (últimos
 * 100) acessível via `useDialogHistory()` ou `getDialogHistory()`. Usado
 * pelo `DialogHistoryPanel` (botão flutuante ↘ admin) pra auditoria de ações.
 */
import React, { useEffect, useState } from "react";
import { ShieldAlert, AlertCircle, Info, MessageCircle, X, Check } from "lucide-react";

// ------------------------------------------------------------
// Event bus interno (sem dependências externas)
// ------------------------------------------------------------
let _dispatch = null;
const _queue = [];

function _emit(payload) {
  if (_dispatch) _dispatch(payload);
  else _queue.push(payload);
}

// ------------------------------------------------------------
// Histórico de diálogos (buffer circular, in-memory)
// ------------------------------------------------------------
const HISTORY_MAX = 100;
const _history = [];
const _historySubs = new Set();

function _pushHistory(entry) {
  _history.unshift(entry); // mais recente no topo
  if (_history.length > HISTORY_MAX) _history.length = HISTORY_MAX;
  _historySubs.forEach((cb) => { try { cb([..._history]); } catch { /* ignore */ } });
}

export function getDialogHistory() { return [..._history]; }
export function clearDialogHistory() {
  _history.length = 0;
  _historySubs.forEach((cb) => { try { cb([]); } catch { /* ignore */ } });
}
export function useDialogHistory() {
  const [items, setItems] = useState(() => [..._history]);
  useEffect(() => {
    _historySubs.add(setItems);
    return () => { _historySubs.delete(setItems); };
  }, []);
  return items;
}

// ------------------------------------------------------------
// API pública (promise-based)
// ------------------------------------------------------------
export function appConfirm(message, opts = {}) {
  return new Promise((resolve) => {
    _emit({
      kind: "confirm",
      message: String(message ?? ""),
      title: opts.title || "Confirmar ação",
      okLabel: opts.okLabel || "Confirmar",
      cancelLabel: opts.cancelLabel || "Cancelar",
      tone: opts.tone || "danger", // danger | warning | info
      resolve,
    });
  });
}

export function appAlert(message, opts = {}) {
  return new Promise((resolve) => {
    _emit({
      kind: "alert",
      message: String(message ?? ""),
      title: opts.title || (opts.tone === "success" ? "Tudo certo" : "Aviso"),
      okLabel: opts.okLabel || "OK",
      tone: opts.tone || "info",
      resolve,
    });
  });
}

export function appPrompt(message, defaultValue = "", opts = {}) {
  return new Promise((resolve) => {
    _emit({
      kind: "prompt",
      message: String(message ?? ""),
      title: opts.title || "Informe um valor",
      okLabel: opts.okLabel || "Confirmar",
      cancelLabel: opts.cancelLabel || "Cancelar",
      defaultValue: String(defaultValue ?? ""),
      placeholder: opts.placeholder || "",
      tone: opts.tone || "info",
      resolve,
    });
  });
}

// ------------------------------------------------------------
// Monkey-patch window.confirm/alert/prompt
// (callsites legados precisam ser convertidos para `await`)
// ------------------------------------------------------------
let _patched = false;
export function installDialogPatch() {
  if (_patched || typeof window === "undefined") return;
  _patched = true;
  window.confirm = (msg) => appConfirm(msg);
  window.alert = (msg) => appAlert(msg);
  window.prompt = (msg, def) => appPrompt(msg, def);
}

// ------------------------------------------------------------
// Component <DialogHost /> — mount ONCE no App.js
// ------------------------------------------------------------
const TONES = {
  danger:  { color: "#dc2626", bg: "#fee2e2", btnBg: "#dc2626", btnHover: "#b91c1c", icon: ShieldAlert },
  warning: { color: "#d97706", bg: "#fef3c7", btnBg: "#d97706", btnHover: "#b45309", icon: AlertCircle },
  info:    { color: "#0ea5e9", bg: "#e0f2fe", btnBg: "#0f172a", btnHover: "#1e293b", icon: Info },
  success: { color: "#16a34a", bg: "#dcfce7", btnBg: "#16a34a", btnHover: "#15803d", icon: Check },
  prompt:  { color: "#0ea5e9", bg: "#e0f2fe", btnBg: "#0f172a", btnHover: "#1e293b", icon: MessageCircle },
};

export function DialogHost() {
  const [stack, setStack] = useState([]);
  const [input, setInput] = useState("");

  useEffect(() => {
    _dispatch = (p) => setStack((s) => [...s, p]);
    // Drena a fila acumulada antes do mount
    if (_queue.length) {
      _queue.splice(0).forEach((p) => setStack((s) => [...s, p]));
    }
    installDialogPatch();
    return () => { _dispatch = null; };
  }, []);

  const current = stack[0];
  useEffect(() => {
    if (current?.kind === "prompt") setInput(current.defaultValue || "");
  }, [current]);

  if (!current) return null;

  const finish = (value) => {
    // Registra no histórico antes de resolver
    let response;
    if (current.kind === "alert") response = "ok";
    else if (current.kind === "confirm") response = value ? "ok" : "cancel";
    else response = value == null ? "cancel" : value; // prompt: texto ou cancel
    _pushHistory({
      id: Math.random().toString(36).slice(2) + Date.now().toString(36),
      ts: Date.now(),
      kind: current.kind,
      title: current.title,
      message: current.message,
      tone: current.tone,
      response,
    });
    current.resolve(value);
    setStack((s) => s.slice(1));
    setInput("");
  };

  const toneKey = current.kind === "prompt" ? "prompt" : current.tone;
  const tone = TONES[toneKey] || TONES.info;
  const Icon = tone.icon;

  return (
    <>
      <style>{`
        @keyframes dlgFadeIn {
          from { opacity: 0; transform: scale(.96) translateY(8px); }
          to   { opacity: 1; transform: scale(1) translateY(0); }
        }
        @keyframes dlgBackdrop {
          from { background-color: rgba(15,23,42,0); }
          to   { background-color: rgba(15,23,42,.55); }
        }
      `}</style>
      <div
        data-testid="dialog-backdrop"
        onClick={() => current.kind !== "alert" && finish(current.kind === "prompt" ? null : false)}
        style={{
          position: "fixed", inset: 0, zIndex: 9999,
          display: "grid", placeItems: "center",
          padding: 20,
          backgroundColor: "rgba(15,23,42,.55)",
          backdropFilter: "blur(4px)",
          WebkitBackdropFilter: "blur(4px)",
          animation: "dlgBackdrop .15s ease-out",
        }}
      >
        <div
          role="dialog"
          aria-modal="true"
          data-testid={`dialog-${current.kind}`}
          onClick={(e) => e.stopPropagation()}
          style={{
            width: "min(440px, 100%)",
            background: "white",
            borderRadius: 18,
            overflow: "hidden",
            boxShadow: "0 30px 80px rgba(15,23,42,.25), 0 4px 12px rgba(15,23,42,.08)",
            animation: "dlgFadeIn .18s cubic-bezier(.16,1,.3,1)",
            border: "1px solid rgba(15,23,42,.06)",
          }}
        >
          {/* Header */}
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14,
                          padding: "20px 22px 4px" }}>
            <div style={{
              width: 44, height: 44, borderRadius: 12,
              background: tone.bg, color: tone.color,
              display: "grid", placeItems: "center", flexShrink: 0,
            }}>
              <Icon size={22} strokeWidth={2.2} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 800, color: "#0f172a",
                              letterSpacing: "-.02em", lineHeight: 1.3 }}>
                {current.title}
              </div>
            </div>
            {current.kind !== "alert" && (
              <button
                onClick={() => finish(current.kind === "prompt" ? null : false)}
                aria-label="Fechar"
                data-testid="dialog-close-x"
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: "#94a3b8", padding: 4, borderRadius: 8,
                  display: "grid", placeItems: "center",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "#f1f5f9"; e.currentTarget.style.color = "#475569"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "none"; e.currentTarget.style.color = "#94a3b8"; }}
              >
                <X size={16} />
              </button>
            )}
          </div>

          {/* Body */}
          <div style={{ padding: "10px 22px 14px", color: "#334155",
                          fontSize: 14, lineHeight: 1.55,
                          whiteSpace: "pre-wrap" }}>
            {current.message}
          </div>

          {/* Input (prompt) */}
          {current.kind === "prompt" && (
            <div style={{ padding: "0 22px 6px" }}>
              <input
                autoFocus
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={current.placeholder}
                data-testid="dialog-prompt-input"
                onKeyDown={(e) => {
                  if (e.key === "Enter") finish(input);
                  if (e.key === "Escape") finish(null);
                }}
                style={{
                  width: "100%", boxSizing: "border-box",
                  padding: "10px 14px", borderRadius: 10,
                  border: "1px solid #cbd5e1", outline: "none",
                  fontSize: 14, color: "#0f172a",
                  transition: "border-color .15s ease, box-shadow .15s ease",
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = "#0ea5e9"; e.currentTarget.style.boxShadow = "0 0 0 3px rgba(14,165,233,.15)"; }}
                onBlur={(e) => { e.currentTarget.style.borderColor = "#cbd5e1"; e.currentTarget.style.boxShadow = "none"; }}
              />
            </div>
          )}

          {/* Footer */}
          <div style={{
            display: "flex", gap: 8, justifyContent: "flex-end",
            padding: "16px 22px 20px",
            background: "linear-gradient(180deg, white, #f8fafc)",
          }}>
            {current.kind !== "alert" && (
              <button
                onClick={() => finish(current.kind === "prompt" ? null : false)}
                data-testid="dialog-cancel-btn"
                style={{
                  padding: "10px 18px", borderRadius: 10,
                  background: "white", color: "#475569",
                  border: "1px solid #e2e8f0",
                  fontSize: 13, fontWeight: 700,
                  cursor: "pointer", transition: "background .12s ease",
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "#f8fafc"}
                onMouseLeave={(e) => e.currentTarget.style.background = "white"}
              >
                {current.cancelLabel || "Cancelar"}
              </button>
            )}
            <button
              autoFocus={current.kind === "alert"}
              onClick={() => finish(current.kind === "prompt" ? input : true)}
              data-testid="dialog-confirm-btn"
              style={{
                padding: "10px 22px", borderRadius: 10,
                background: tone.btnBg, color: "white",
                border: "none",
                fontSize: 13, fontWeight: 700,
                cursor: "pointer", transition: "background .12s ease, transform .1s ease",
                boxShadow: `0 4px 12px ${tone.btnBg}33`,
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = tone.btnHover; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = tone.btnBg; }}
              onMouseDown={(e) => { e.currentTarget.style.transform = "scale(.97)"; }}
              onMouseUp={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
            >
              {current.okLabel || "OK"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

export default DialogHost;
