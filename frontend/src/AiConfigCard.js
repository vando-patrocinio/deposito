/**
 * AiConfigCard.js — Card único para configuração de IA do tenant.
 *
 * Funcionalidades:
 *  - Lista os 3 providers (Gemini, Anthropic, OpenAI) com badge de status
 *  - Drag-and-drop pra reordenar a cascata (1º = principal, demais = fallback)
 *  - Botão "Trocar" abre input pra colar nova chave (validação de prefixo)
 *  - Botão "Testar" pinga o provider e mostra latência
 *  - Cascata automática: se principal cair, próximo assume
 */
import React, { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/api";
import { Card, Button, inputStyle } from "@/ui";
import {
  Sparkles, Brain, Cpu, GripVertical, Check, AlertTriangle,
  Loader2, Pencil, Zap, Crown, ArrowRight,
} from "lucide-react";

const PROVIDER_ICONS = { sparkles: Sparkles, brain: Brain, cpu: Cpu };

export default function AiConfigCard() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [editingKey, setEditingKey] = useState(null); // provider id sendo editado
  const [newKeyValue, setNewKeyValue] = useState("");
  const [testResults, setTestResults] = useState({}); // {gemini: {ok,latency_ms,...}}
  const [dragId, setDragId] = useState(null);
  const [dragOverId, setDragOverId] = useState(null);
  const draggedFromIdx = useRef(null);

  const reload = useCallback(async () => {
    try {
      const r = await api._client.get("/ai-config");
      setData(r.data);
    } catch (e) {
      setErr("Falha ao carregar configuração: " + (e?.response?.data?.detail || e.message));
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  // ---- Drag-and-drop ----
  function onDragStart(e, id, idx) {
    setDragId(id);
    draggedFromIdx.current = idx;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", id);
  }
  function onDragOver(e, id) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (id !== dragOverId) setDragOverId(id);
  }
  function onDragLeave() {
    setDragOverId(null);
  }
  async function onDrop(e, targetId, targetIdx) {
    e.preventDefault();
    setDragOverId(null);
    if (!dragId || dragId === targetId) { setDragId(null); return; }
    const chain = [...(data?.chain || [])];
    const from = chain.indexOf(dragId);
    const to = chain.indexOf(targetId);
    if (from < 0 || to < 0) { setDragId(null); return; }
    chain.splice(from, 1);
    chain.splice(to, 0, dragId);
    setDragId(null);
    // Atualiza UI otimisticamente
    setData(d => ({ ...d, chain, providers: chain.map((id, i) => {
      const p = d.providers.find(pp => pp.id === id);
      return { ...p, is_primary: i === 0, position: i };
    }) }));
    // Persiste
    try {
      setBusy(true); setMsg(""); setErr("");
      const r = await api._client.put("/ai-config/chain", { chain });
      setMsg(`Ordem atualizada · principal agora é ${labelOf(r.data.primary)}`);
      setTimeout(() => setMsg(""), 4000);
    } catch (e) {
      setErr("Falha ao salvar ordem: " + (e?.response?.data?.detail || e.message));
      await reload(); // reverte UI
    } finally {
      setBusy(false);
    }
  }

  function labelOf(id) {
    return data?.providers?.find(p => p.id === id)?.label || id;
  }

  async function saveKey(provider) {
    if (!newKeyValue.trim()) return;
    try {
      setBusy(true); setMsg(""); setErr("");
      await api._client.put(`/ai-config/key/${provider}`, { api_key: newKeyValue.trim() });
      setMsg(`Chave do ${labelOf(provider)} atualizada com sucesso.`);
      setEditingKey(null); setNewKeyValue("");
      await reload();
      setTimeout(() => setMsg(""), 4000);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  async function runTest(provider) {
    setTestResults(t => ({ ...t, [provider]: { loading: true } }));
    try {
      const r = await api._client.post(`/ai-config/test/${provider}`);
      setTestResults(t => ({ ...t, [provider]: r.data }));
    } catch (e) {
      setTestResults(t => ({ ...t, [provider]: { ok: false, error: e.message } }));
    }
  }

  if (!data) {
    return (
      <Card title="Conexão de IA">
        <div style={{ padding: 14, color: "#64748b", display: "flex", gap: 8, alignItems: "center" }}>
          <Loader2 size={16} className="animate-spin" /> Carregando…
        </div>
      </Card>
    );
  }

  const primaryProvider = data.providers.find(p => p.is_primary);
  const configuredCount = data.providers.filter(p => p.configured).length;

  return (
    <Card title={null} style={{ padding: 0, overflow: "hidden" }}>
      {/* ─── Header com gradient ─── */}
      <div style={{
        background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
        padding: "20px 22px", color: "#f1f5f9",
        borderBottom: "1px solid #1e293b",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Sparkles size={20} color="#fbbf24" />
              <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700 }} data-testid="ai-config-title">
                Conexão de IA
              </h3>
              <span style={{
                fontSize: 11, padding: "2px 8px", borderRadius: 999,
                background: configuredCount >= 1 ? "#16a34a" : "#f59e0b",
                color: "white", fontWeight: 600,
              }} data-testid="ai-config-configured-count">
                {configuredCount}/{data.providers.length} configuradas
              </span>
            </div>
            <p style={{ margin: "6px 0 0", fontSize: 13, color: "#94a3b8" }}>
              Arraste pra reordenar · 1º da lista atende · demais assumem se cair
            </p>
          </div>
          {primaryProvider && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "8px 14px", borderRadius: 10,
              background: "rgba(251, 191, 36, 0.12)",
              border: "1px solid rgba(251, 191, 36, 0.3)",
            }} data-testid="ai-config-primary-badge">
              <Crown size={16} color="#fbbf24" />
              <div>
                <div style={{ fontSize: 10, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Em uso agora
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, color: "#fbbf24" }}>
                  {primaryProvider.label} · {primaryProvider.model}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ─── Lista drag-and-drop ─── */}
      <div style={{ padding: 18 }}>
        {data.providers.map((p, idx) => {
          const IconCmp = PROVIDER_ICONS[p.icon] || Sparkles;
          const isDragging = dragId === p.id;
          const isDragOver = dragOverId === p.id;
          const isPrimary = idx === 0;
          const testResult = testResults[p.id];
          return (
            <div
              key={p.id}
              draggable
              onDragStart={(e) => onDragStart(e, p.id, idx)}
              onDragOver={(e) => onDragOver(e, p.id)}
              onDragLeave={onDragLeave}
              onDrop={(e) => onDrop(e, p.id, idx)}
              onDragEnd={() => { setDragId(null); setDragOverId(null); }}
              style={{
                display: "flex", alignItems: "stretch", gap: 12,
                padding: "14px 16px", marginBottom: 10,
                background: isPrimary
                  ? "linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)"
                  : "white",
                border: `2px solid ${isDragOver ? "#0d9488" : isPrimary ? "#fbbf24" : "#e2e8f0"}`,
                borderRadius: 14,
                cursor: isDragging ? "grabbing" : "grab",
                opacity: isDragging ? 0.4 : 1,
                transform: isDragOver ? "scale(1.01)" : "scale(1)",
                transition: "all 160ms ease",
                position: "relative",
              }}
              data-testid={`ai-provider-row-${p.id}`}
            >
              {/* Drag handle */}
              <div style={{
                display: "flex", alignItems: "center",
                color: "#94a3b8", padding: "0 4px",
              }} data-testid={`ai-provider-drag-${p.id}`}>
                <GripVertical size={20} />
              </div>

              {/* Position number */}
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "center",
                minWidth: 28, fontWeight: 800, fontSize: 20,
                color: isPrimary ? "#92400e" : "#64748b",
              }}>
                {idx + 1}
              </div>

              {/* Icon + Info */}
              <div style={{ display: "flex", alignItems: "center", gap: 14, flex: 1, minWidth: 0 }}>
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  width: 44, height: 44, borderRadius: 12,
                  background: p.color, color: "white", flexShrink: 0,
                }}>
                  <IconCmp size={22} />
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 15, fontWeight: 700, color: "#0f172a" }}>
                      {p.label}
                    </span>
                    {isPrimary && (
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 4,
                        fontSize: 10, padding: "2px 8px", borderRadius: 999,
                        background: "#fbbf24", color: "#451a03", fontWeight: 700,
                        textTransform: "uppercase", letterSpacing: 0.5,
                      }} data-testid={`ai-provider-primary-tag-${p.id}`}>
                        <Crown size={10} /> Principal
                      </span>
                    )}
                    {!isPrimary && (
                      <span style={{
                        fontSize: 10, padding: "2px 8px", borderRadius: 999,
                        background: "#e0e7ff", color: "#3730a3", fontWeight: 600,
                      }}>
                        Backup #{idx}
                      </span>
                    )}
                    {p.configured ? (
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 4,
                        fontSize: 10, padding: "2px 8px", borderRadius: 999,
                        background: "#dcfce7", color: "#166534", fontWeight: 600,
                      }} data-testid={`ai-provider-status-${p.id}`}>
                        <Check size={10} /> Configurada
                      </span>
                    ) : (
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 4,
                        fontSize: 10, padding: "2px 8px", borderRadius: 999,
                        background: "#fee2e2", color: "#991b1b", fontWeight: 600,
                      }} data-testid={`ai-provider-status-${p.id}`}>
                        <AlertTriangle size={10} /> Sem chave
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
                    Modelo: <code style={{ background: "#f1f5f9", padding: "1px 6px", borderRadius: 4, fontFamily: "JetBrains Mono, monospace" }}>{p.model}</code>
                  </div>
                  {p.configured && (
                    <div style={{
                      fontSize: 11, color: "#475569", marginTop: 4,
                      fontFamily: "JetBrains Mono, monospace",
                    }} data-testid={`ai-provider-key-${p.id}`}>
                      Chave: {p.key_masked}
                    </div>
                  )}
                  {!p.configured && (
                    <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>
                      {p.key_help}
                    </div>
                  )}
                  {testResult && !testResult.loading && (
                    <div style={{
                      fontSize: 11, marginTop: 6,
                      color: testResult.ok ? "#16a34a" : "#dc2626",
                      fontWeight: 600,
                    }} data-testid={`ai-provider-test-result-${p.id}`}>
                      {testResult.ok
                        ? <><Zap size={11} style={{ display: "inline", verticalAlign: "middle" }} /> {testResult.latency_ms}ms · {testResult.response_preview}</>
                        : <>✗ {String(testResult.error || "Falhou").slice(0, 80)}</>
                      }
                    </div>
                  )}
                </div>
              </div>

              {/* Botões de ação */}
              <div style={{ display: "flex", flexDirection: "column", gap: 6, justifyContent: "center" }}>
                {p.configured && (
                  <button
                    onClick={() => runTest(p.id)}
                    disabled={testResult?.loading}
                    data-testid={`ai-provider-test-btn-${p.id}`}
                    style={{
                      padding: "5px 10px", fontSize: 11, fontWeight: 600,
                      background: "white", color: "#0f766e",
                      border: "1px solid #14b8a6", borderRadius: 7,
                      cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4,
                    }}
                  >
                    {testResult?.loading ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />}
                    Testar
                  </button>
                )}
                <button
                  onClick={() => { setEditingKey(p.id); setNewKeyValue(""); }}
                  data-testid={`ai-provider-edit-btn-${p.id}`}
                  style={{
                    padding: "5px 10px", fontSize: 11, fontWeight: 600,
                    background: p.configured ? "white" : "#0f766e",
                    color: p.configured ? "#0f172a" : "white",
                    border: `1px solid ${p.configured ? "#cbd5e1" : "#0f766e"}`,
                    borderRadius: 7, cursor: "pointer",
                    display: "inline-flex", alignItems: "center", gap: 4,
                  }}
                >
                  <Pencil size={11} />
                  {p.configured ? "Trocar" : "Configurar"}
                </button>
              </div>

              {/* Modal inline pra trocar chave */}
              {editingKey === p.id && (
                <div style={{
                  position: "absolute", top: "100%", left: 12, right: 12, marginTop: 6,
                  background: "white", border: "1px solid #cbd5e1", borderRadius: 12,
                  padding: 14, boxShadow: "0 12px 36px rgba(0,0,0,0.15)", zIndex: 30,
                }} data-testid={`ai-provider-edit-modal-${p.id}`}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#0f172a" }}>
                    Nova chave do {p.label}
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b", marginBottom: 8 }}>
                    Deve começar com <code style={{ background: "#f1f5f9", padding: "1px 6px", borderRadius: 4 }}>{p.prefix}</code>
                  </div>
                  <input
                    type="password"
                    autoFocus
                    value={newKeyValue}
                    onChange={(e) => setNewKeyValue(e.target.value)}
                    placeholder={`${p.prefix}...`}
                    style={{ ...inputStyle, marginBottom: 10 }}
                    data-testid={`ai-provider-edit-input-${p.id}`}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") saveKey(p.id);
                      if (e.key === "Escape") { setEditingKey(null); setNewKeyValue(""); }
                    }}
                  />
                  <div style={{ display: "flex", gap: 8 }}>
                    <Button
                      onClick={() => saveKey(p.id)}
                      disabled={!newKeyValue.trim() || busy}
                      data-testid={`ai-provider-edit-save-${p.id}`}
                    >
                      {busy ? "Salvando…" : "Salvar"}
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => { setEditingKey(null); setNewKeyValue(""); }}
                      data-testid={`ai-provider-edit-cancel-${p.id}`}
                    >
                      Cancelar
                    </Button>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {/* ─── Fluxo da cascata ─── */}
        <div style={{
          marginTop: 18, padding: 12, borderRadius: 10,
          background: "#f8fafc", border: "1px solid #e2e8f0",
          display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
        }} data-testid="ai-cascade-flow">
          <span style={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
            Fluxo de cascata automática:
          </span>
          {data.chain.map((id, i) => (
            <React.Fragment key={id}>
              <span style={{
                fontSize: 12, padding: "3px 8px", borderRadius: 999,
                background: i === 0 ? "#fbbf24" : "#e0e7ff",
                color: i === 0 ? "#451a03" : "#3730a3",
                fontWeight: 700,
              }}>
                {labelOf(id)}
              </span>
              {i < data.chain.length - 1 && <ArrowRight size={14} color="#94a3b8" />}
            </React.Fragment>
          ))}
        </div>

        {/* ─── Mensagens ─── */}
        {msg && (
          <div style={{
            marginTop: 12, padding: 10, borderRadius: 8,
            background: "#dcfce7", color: "#166534", fontSize: 13, fontWeight: 500,
          }} data-testid="ai-config-msg">
            {msg}
          </div>
        )}
        {err && (
          <div style={{
            marginTop: 12, padding: 10, borderRadius: 8,
            background: "#fee2e2", color: "#991b1b", fontSize: 13, fontWeight: 500,
          }} data-testid="ai-config-err">
            {String(err)}
          </div>
        )}

        {/* ─── Explicação curta ─── */}
        <details style={{ marginTop: 14, fontSize: 12, color: "#64748b" }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>
            Como a cascata funciona?
          </summary>
          <div style={{ marginTop: 8, paddingLeft: 12, lineHeight: 1.6 }}>
            <strong>1.</strong> Quando um cliente fala com a Isabella, o sistema tenta o provider <strong>#1</strong> primeiro.<br/>
            <strong>2.</strong> Se a chave estiver inválida, sem créditos ou der erro, o sistema tenta o <strong>#2</strong> automaticamente — sem você fazer nada.<br/>
            <strong>3.</strong> O cliente nunca fica sem resposta. Você economiza usando o mais barato como #1 (Gemini ~$0.075/M tokens) e mantém Claude como #2 pra qualidade premium.<br/>
            <strong>4.</strong> Pra trocar o principal: <strong>arraste o card pra cima</strong>. Pra atualizar uma chave: clique em <strong>Trocar</strong>.
          </div>
        </details>
      </div>
    </Card>
  );
}
