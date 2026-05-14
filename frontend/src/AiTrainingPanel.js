import React, { useCallback, useEffect, useState } from "react";
import {
  RefreshCw, CheckCircle2, AlertTriangle, Bot, Database, BookOpen,
  Loader2, ChevronRight, Sparkles,
} from "lucide-react";
import { Card } from "@/ui";
import { api } from "@/api";
import TrainingStudio from "@/TrainingStudio";

/**
 * Painel de Treinamento Multiagente — mostra status dos 10 agentes IA +
 * 5 docs KB + botão "Recarregar treinamento" + botão "Abrir Training Studio".
 *
 * Pensado para ser embedado no CentralIaDashboard.
 */
export default function AiTrainingPanel() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [flash, setFlash] = useState("");
  const [error, setError] = useState("");
  const [studioOpen, setStudioOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.aiTrainingStatus();
      setStatus(r);
      setError("");
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleReload() {
    if (!window.confirm(
      "Tem certeza? Isso vai sobrescrever os system_prompts dos 10 agentes " +
      "com a versão mais recente do treinamento (regras + matriz + " +
      "scoring + papel específico)."
    )) return;
    setReloading(true);
    setError("");
    try {
      const r = await api.aiTrainingReload();
      setFlash(`Recarregado · ${r.agents_count} agentes · ${r.kb_documents} docs`);
      await load();
      setTimeout(() => setFlash(""), 4500);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setReloading(false);
    }
  }

  if (loading) {
    return (
      <Card style={{ padding: 16, textAlign: "center", color: "var(--text-muted)" }}>
        <Loader2 size={16} className="spin" /> Carregando treinamento…
      </Card>
    );
  }

  return (
    <Card data-testid="ai-training-panel" style={{ padding: 14 }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 10, marginBottom: 12,
      }}>
        <div style={{
          width: 36, height: 36, borderRadius: 10,
          background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
          color: "white", display: "grid", placeItems: "center",
          boxShadow: "0 4px 12px rgba(139,92,246,.25)",
        }}>
          <BookOpen size={18} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1 }}>
          <h3 style={{
            margin: 0, fontSize: 14, fontWeight: 800,
            letterSpacing: "-0.012em", color: "var(--text-primary)",
          }}>Treinamento Multiagente</h3>
          <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 1 }}>
            {status?.agents_with_training || 0} de {status?.agents_count || 0} agentes
            alimentados · {status?.kb_documents || 0} docs KB
            {status?.last_reload_at && (
              <> · último reload <span className="mono">{
                String(status.last_reload_at).slice(0,16).replace("T", " ")
              }</span></>
            )}
          </div>
        </div>
        <button onClick={handleReload} disabled={reloading}
                data-testid="ai-training-reload-btn"
                style={{
                  padding: "8px 14px", borderRadius: 8,
                  border: "1px solid var(--border-default)",
                  background: reloading ? "var(--bg-surface-2)" : "#0f172a",
                  color: reloading ? "var(--text-muted)" : "white",
                  fontSize: 12, fontWeight: 800, cursor: reloading ? "wait" : "pointer",
                  display: "inline-flex", alignItems: "center", gap: 6,
                  transition: "all .15s",
                }}>
          <RefreshCw size={13}
                      style={{ animation: reloading ? "spin 1s linear infinite" : "none" }} />
          {reloading ? "Recarregando…" : "Recarregar treinamento"}
        </button>
        <button onClick={() => setStudioOpen(true)}
                data-testid="open-training-studio-btn"
                style={{
                  padding: "8px 14px", borderRadius: 8,
                  border: "1px solid #8b5cf6",
                  background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
                  color: "white",
                  fontSize: 12, fontWeight: 800, cursor: "pointer",
                  display: "inline-flex", alignItems: "center", gap: 6,
                  transition: "all .15s",
                  boxShadow: "0 4px 12px rgba(139,92,246,.25)",
                }}>
          <Sparkles size={13} />
          Abrir Training Studio
        </button>
      </div>

      {flash && (
        <div data-testid="ai-training-flash" style={{
          padding: "8px 12px", borderRadius: 8, marginBottom: 10,
          background: "rgba(22,163,74,.10)", color: "#15803d",
          fontSize: 12, fontWeight: 700,
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <CheckCircle2 size={14} /> {flash}
        </div>
      )}

      {error && (
        <div data-testid="ai-training-error" style={{
          padding: "8px 12px", borderRadius: 8, marginBottom: 10,
          background: "rgba(220,38,38,.08)", color: "#b91c1c",
          fontSize: 12, fontWeight: 600,
          display: "flex", alignItems: "flex-start", gap: 8,
        }}>
          <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
          {error}
        </div>
      )}

      {/* Lista compacta dos agentes */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
        gap: 6, marginTop: 6,
      }}>
        {(status?.agents || []).map((a) => (
          <div key={a.id || a.name} data-testid={`ai-training-agent-${a.topology_node}`}
                style={{
                  padding: "8px 10px", borderRadius: 7,
                  background: "var(--bg-surface-2)",
                  border: "1px solid var(--border-default)",
                  display: "flex", alignItems: "center", gap: 8,
                  fontSize: 11.5,
                }}>
            <Bot size={12} style={{
              color: a.training_loaded_at ? "#16a34a" : "var(--text-muted)",
              flexShrink: 0,
            }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontWeight: 700, color: "var(--text-primary)",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>{a.name}</div>
              <div style={{ fontSize: 10, color: "var(--text-muted)",
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {a.model_provider}/{a.model_name}
              </div>
            </div>
          </div>
        ))}
      </div>

      <details style={{ marginTop: 12 }}>
        <summary style={{
          cursor: "pointer", fontSize: 11.5, fontWeight: 700,
          color: "var(--text-muted)", padding: "4px 0",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <Database size={12} /> Knowledge Base ({status?.kb?.length || 0})
          <ChevronRight size={12} style={{ transition: "transform .15s" }} />
        </summary>
        <div style={{ marginTop: 8, display: "grid", gap: 4 }}>
          {(status?.kb || []).map((d) => (
            <div key={d.id} style={{
              padding: "6px 10px", borderRadius: 6,
              background: "var(--bg-surface-2)",
              fontSize: 11.5, display: "flex", alignItems: "center", gap: 8,
            }}>
              <span className="mono" style={{
                fontSize: 10, color: "var(--text-muted)",
                background: "var(--bg-surface)",
                padding: "1px 5px", borderRadius: 4,
              }}>{d.key}</span>
              <span style={{ flex: 1, color: "var(--text-primary)" }}>{d.title}</span>
              <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                {String(d.updated_at || "").slice(0,16).replace("T"," ")}
              </span>
            </div>
          ))}
        </div>
      </details>
      {studioOpen && (
        <TrainingStudio onClose={() => setStudioOpen(false)} />
      )}
    </Card>
  );
}
