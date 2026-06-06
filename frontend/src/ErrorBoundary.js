/*
ErrorBoundary.js — Captura erros React em componentes filhos e mostra um
fallback amigável em vez de quebrar a UI inteira (e poluir o overlay do CRA
com "Script error." cross-origin).
*/
import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false, errorMsg: null,
      stack: null, componentStack: null, ts: null,
    };
  }

  static getDerivedStateFromError(err) {
    return {
      hasError: true,
      errorMsg: err?.message || String(err),
      stack: String(err?.stack || "").slice(0, 4000),
      ts: new Date().toISOString(),
    };
  }

  componentDidCatch(err, info) {
    try {
      const componentStack = String(info?.componentStack || "").slice(0, 2000);
      this.setState({ componentStack });
      console.warn("[ErrorBoundary]", this.props.name || "component",
                   "·", err?.message, componentStack.slice(0, 200));
      // Best-effort: envia log estruturado pro backend pra ficar gravado.
      const apiBase = process.env.REACT_APP_BACKEND_URL || "";
      if (apiBase) {
        const payload = {
          boundary: this.props.name || "unknown",
          message: String(err?.message || err),
          stack: String(err?.stack || "").slice(0, 4000),
          component_stack: componentStack,
          url: typeof window !== "undefined" ? window.location.href : "",
          user_agent: typeof navigator !== "undefined" ? navigator.userAgent : "",
          ts: new Date().toISOString(),
        };
        fetch(`${apiBase}/api/client-errors/log`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          keepalive: true,
        }).catch(() => { /* offline ou indisponível */ });
      }
    } catch { /* ignore */ }
  }

  reset = () => this.setState({
    hasError: false, errorMsg: null, stack: null,
    componentStack: null, ts: null,
  });
  hardReload = () => { try { window.location.reload(); } catch { /* */ } };
  goBack = () => {
    try {
      if (window.history.length > 1) window.history.back();
      else window.location.href = "/";
    } catch { /* */ }
  };

  // iter211ah — Copia diagnóstico completo do crash pra clipboard, pra usuário
  // mandar pro suporte/dev via WhatsApp.
  copyDiagnostic = async () => {
    const diag = {
      boundary: this.props.name || "unknown",
      message: this.state.errorMsg,
      stack: this.state.stack,
      component_stack: this.state.componentStack,
      ts: this.state.ts,
      url: typeof window !== "undefined" ? window.location.href : "",
      user_agent: typeof navigator !== "undefined" ? navigator.userAgent : "",
      app_version: typeof window !== "undefined" ? window.__APP_VERSION__ : "",
    };
    const text = "===== DIAGNÓSTICO DE ERRO — SmartProv =====\n"
                 + JSON.stringify(diag, null, 2);
    try {
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text; document.body.appendChild(ta);
        ta.select(); document.execCommand("copy");
        document.body.removeChild(ta);
      }
      this.setState({ _copied: true });
      setTimeout(() => this.setState({ _copied: false }), 2000);
    } catch (e) {
      alert("Não consegui copiar. Manda screenshot da tela.");
    }
  };
  // iter211af — Limpa TODO estado local (drafts, fila offline, caches do SW)
  // e força reload. Útil quando um rascunho corrompido fica em loop crashando
  // a tela. Last-resort pra técnico não ficar travado em campo.
  cleanReload = async () => {
    try {
      // 1) localStorage: drafts da Lousa (osdraft:*) e outros itens
      try {
        const toDelete = [];
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i);
          if (!k) continue;
          if (k.startsWith("osdraft:") || k.startsWith("smartprov:")
              || k.startsWith("lousa:")) toDelete.push(k);
        }
        toDelete.forEach((k) => { try { localStorage.removeItem(k); } catch { /* */ } });
      } catch { /* */ }
      // 2) IndexedDB: outbox offline (smartprov-outbox)
      try {
        if (typeof indexedDB !== "undefined" && indexedDB.deleteDatabase) {
          indexedDB.deleteDatabase("smartprov-outbox");
        }
      } catch { /* */ }
      // 3) Service Worker caches
      try {
        if ("caches" in window) {
          const names = await caches.keys();
          await Promise.all(names.map((n) => caches.delete(n)));
        }
      } catch { /* */ }
      // 4) Unregister SW pra forçar refetch do bundle novo
      try {
        if (navigator.serviceWorker?.getRegistrations) {
          const regs = await navigator.serviceWorker.getRegistrations();
          await Promise.all(regs.map((r) => r.unregister()));
        }
      } catch { /* */ }
    } finally {
      try { window.location.reload(); } catch { /* */ }
    }
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    if (this.props.variant === "fullscreen") {
      return (
        <div data-testid={`error-boundary-${this.props.name || "x"}`}
              style={{
                minHeight: "60vh", display: "flex", flexDirection: "column",
                alignItems: "center", justifyContent: "center", padding: 24,
                background: "linear-gradient(180deg,#fff8f1,#fef3c7)",
                borderRadius: 12, margin: 16,
                border: "1.5px solid #fed7aa",
                boxShadow: "0 8px 24px rgba(217,119,6,0.12)",
              }}>
          <div style={{ fontSize: 48, marginBottom: 4 }}>️</div>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#7c2d12",
                         margin: "0 0 6px" }}>
            Algo deu errado nesta tela
          </h2>
          <p style={{ color: "#9a3412", textAlign: "center", maxWidth: 480,
                        lineHeight: 1.5, margin: "0 0 16px", fontSize: 13 }}>
            A tela <strong>{this.props.name || "atual"}</strong> teve um erro
            inesperado. Os dados estão seguros — tente novamente, volte ou
            recarregue a página.
          </p>
          {this.state.errorMsg && (
            <details open style={{ maxWidth: 600, marginBottom: 14, width: "100%" }}>
              <summary style={{ cursor: "pointer", fontSize: 11,
                                  color: "#7c2d12", fontWeight: 700 }}>
                Detalhes técnicos · boundary: {this.props.name || "—"}
              </summary>
              <pre style={{ fontSize: 10, background: "#1c1917", color: "#fde68a",
                              padding: 10, borderRadius: 6, overflow: "auto",
                              marginTop: 6, maxHeight: 260, whiteSpace: "pre-wrap" }}>
{`MSG: ${this.state.errorMsg}

STACK:
${(this.state.stack || "—").slice(0, 1200)}

COMPONENT STACK:
${(this.state.componentStack || "—").slice(0, 800)}`}
              </pre>
            </details>
          )}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                          justifyContent: "center" }}>
            <button data-testid="error-boundary-retry"
                    onClick={this.reset}
                    style={{ padding: "10px 18px",
                              background: "linear-gradient(135deg,#f59e0b,#d97706)",
                              color: "white", border: "none", borderRadius: 8,
                              fontWeight: 800, fontSize: 13, cursor: "pointer" }}>
              ↻ Tentar de novo
            </button>
            <button data-testid="error-boundary-copy-diagnostic"
                    onClick={this.copyDiagnostic}
                    title="Copia o erro completo (stack, URL, navegador) pra você colar no WhatsApp e mandar pro suporte."
                    style={{
                      ...btnSecondary,
                      background: this.state._copied ? "#dcfce7" : "#dbeafe",
                      borderColor: this.state._copied ? "#86efac" : "#93c5fd",
                      color: this.state._copied ? "#166534" : "#1e3a8a",
                      fontWeight: 800,
                    }}>
              {this.state._copied ? "✓ Copiado!" : "Copiar diagnóstico"}
            </button>
            <button data-testid="error-boundary-back"
                    onClick={this.goBack}
                    style={btnSecondary}>
              ← Voltar
            </button>
            <button data-testid="error-boundary-hard-reload"
                    onClick={this.hardReload}
                    style={btnSecondary}>
              Recarregar página
            </button>
            <button data-testid="error-boundary-clean-reload"
                    onClick={this.cleanReload}
                    title="Apaga rascunhos locais, fila offline e caches deste app, depois recarrega. Use se a tela continuar dando erro mesmo após Recarregar."
                    style={{
                      ...btnSecondary,
                      background: "#fee2e2",
                      borderColor: "#fca5a5",
                      color: "#991b1b",
                    }}>
              Limpar dados locais e recarregar
            </button>
          </div>
        </div>
      );
    }
    // variant default — card inline (não tela cheia)
    return (
        <div
          data-testid={`error-boundary-${this.props.name || "x"}`}
          style={{
            padding: 14,
            background: "#fef3c7",
            border: "1px solid #fbbf24",
            borderRadius: 10,
            display: "flex", gap: 10, alignItems: "flex-start",
            fontSize: 13, color: "#78350f",
          }}>
          <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
          <div style={{ flex: 1 }}>
            <strong>Algo deu errado neste card.</strong>
            <div style={{ fontSize: 11.5, marginTop: 2, opacity: 0.85 }}>
              {this.props.fallbackText
                || "O resto da página segue funcionando normalmente. Você pode tentar recarregar este componente abaixo."}
            </div>
            {this.state.errorMsg && (
              <details style={{ marginTop: 6, fontSize: 11 }}>
                <summary style={{ cursor: "pointer" }}>Detalhes técnicos</summary>
                <pre style={{ whiteSpace: "pre-wrap", margin: "4px 0 0",
                              background: "rgba(0,0,0,0.04)", padding: 6,
                              borderRadius: 4 }}>{this.state.errorMsg}</pre>
              </details>
            )}
            <button onClick={this.reset}
                      style={{
                        marginTop: 8, padding: "5px 10px",
                        border: "1px solid #f59e0b",
                        background: "#fff", color: "#78350f",
                        borderRadius: 6, cursor: "pointer",
                        fontSize: 11, fontWeight: 600,
                        display: "inline-flex", alignItems: "center", gap: 4,
                      }}>
              <RefreshCw size={11} /> Tentar novamente
            </button>
          </div>
        </div>
      );
  }
}

const btnSecondary = {
  padding: "10px 18px",
  background: "white", color: "#7c2d12",
  border: "1.5px solid #fed7aa", borderRadius: 8,
  fontWeight: 700, fontSize: 13, cursor: "pointer",
};
