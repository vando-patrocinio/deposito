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
    this.state = { hasError: false, errorMsg: null };
  }

  static getDerivedStateFromError(err) {
    return { hasError: true, errorMsg: err?.message || String(err) };
  }

  componentDidCatch(err, info) {
    try {
      console.warn("[ErrorBoundary]", this.props.name || "component",
                   "·", err?.message, info?.componentStack?.slice(0, 200));
    } catch { /* ignore */ }
  }

  reset = () => this.setState({ hasError: false, errorMsg: null });

  render() {
    if (this.state.hasError) {
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
    return this.props.children;
  }
}
