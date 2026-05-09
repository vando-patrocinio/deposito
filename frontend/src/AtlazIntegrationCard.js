import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, inputStyle } from "@/ui";

/**
 * Card de configuração e operação da integração com Atlaz.
 * Aparece dentro do SettingsPanel.
 */
export default function AtlazIntegrationCard() {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState(null);
  const [collabs, setCollabs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [test, setTest] = useState(null);
  const [sync, setSync] = useState(null);
  const [logs, setLogs] = useState([]);
  const [showLogs, setShowLogs] = useState(false);

  async function reload() {
    try {
      const [c, cs] = await Promise.all([
        api.atlazGetSettings(),
        api.listCollaborators().catch(() => []),
      ]);
      setCfg(c);
      setCollabs(cs || []);
      setForm({
        enabled: !!c.enabled,
        base_url: c.base_url || "",
        api_key: "",
        api_key_header: c.api_key_header || "X-API-Key",
        list_path: c.list_path || "/v1/ordens-servico",
        list_query_status: c.list_query_status || "aberta",
        close_path: c.close_path || "/v1/ordens-servico/{id}/concluir",
        cancel_path: c.cancel_path || "/v1/ordens-servico/{id}/cancelar",
        reschedule_path: c.reschedule_path || "/v1/ordens-servico/{id}/reagendar",
        filiais_text: (c.filiais || []).join(", "),
        filial_to_collaborator: { ...(c.filial_to_collaborator || {}) },
        type_map_text: JSON.stringify(c.type_map || {}, null, 2),
        field_map_text: JSON.stringify(c.field_map || {}, null, 2),
        sync_interval_minutes: c.sync_interval_minutes ?? 10,
        auto_create_bubbles: c.auto_create_bubbles ?? true,
        auto_push_on_close: c.auto_push_on_close ?? true,
        timeout_seconds: c.timeout_seconds ?? 15,
      });
    } catch (e) {
      setMsg("Erro carregando config: " + (e?.response?.data?.detail || e.message));
    }
  }
  useEffect(() => { reload(); }, []);

  async function save() {
    setBusy(true); setMsg("");
    const payload = {
      enabled: form.enabled,
      base_url: form.base_url,
      api_key_header: form.api_key_header,
      list_path: form.list_path,
      list_query_status: form.list_query_status,
      close_path: form.close_path,
      cancel_path: form.cancel_path,
      reschedule_path: form.reschedule_path,
      filiais: form.filiais_text.split(",").map((x) => x.trim()).filter(Boolean),
      sync_interval_minutes: Number(form.sync_interval_minutes) || 10,
      auto_create_bubbles: form.auto_create_bubbles,
      auto_push_on_close: form.auto_push_on_close,
      timeout_seconds: Number(form.timeout_seconds) || 15,
    };
    if (form.api_key) payload.api_key = form.api_key;
    payload.filial_to_collaborator = form.filial_to_collaborator || {};
    try {
      payload.type_map = JSON.parse(form.type_map_text || "{}");
    } catch { setMsg("Mapeamento de tipos inválido (não é JSON)"); setBusy(false); return; }
    try {
      payload.field_map = JSON.parse(form.field_map_text || "{}");
    } catch { setMsg("Mapeamento de campos inválido (não é JSON)"); setBusy(false); return; }

    try {
      await api.atlazUpdateSettings(payload);
      setMsg("✓ Configuração salva.");
      await reload();
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    }
    setBusy(false);
  }

  async function runTest() {
    setBusy(true); setTest(null); setMsg("");
    try {
      const r = await api.atlazTestConnection();
      setTest(r);
    } catch (e) {
      setTest({ ok: false, error: e?.response?.data?.detail || e.message });
    }
    setBusy(false);
  }

  async function runSync() {
    setBusy(true); setSync(null); setMsg("");
    try {
      const r = await api.atlazSyncNow();
      setSync(r);
    } catch (e) {
      setSync({ ok: false, error: e?.response?.data?.detail || e.message });
    }
    setBusy(false);
  }

  async function loadLogs() {
    try {
      const r = await api.atlazSyncLogs(30);
      setLogs(r.items || []);
      setShowLogs(true);
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    }
  }

  if (!form) {
    return (
      <Card title="🔗 Integração Atlaz" data-testid="card-atlaz">
        <p style={{ color: "#94a3b8" }}>Carregando…</p>
      </Card>
    );
  }

  const statusBadge = (
    <span data-testid="atlaz-status-badge" style={{
      background: form.enabled ? "linear-gradient(135deg,#10b981,#059669)" : "#94a3b8",
      color: "white", fontSize: 10, fontWeight: 800, padding: "3px 8px",
      borderRadius: 999, letterSpacing: 0.4,
    }}>
      {form.enabled ? (cfg?.api_key_set ? "ATIVO" : "ATIVO SEM CHAVE") : "INATIVO"}
    </span>
  );

  return (
    <Card title="🔗 Integração Atlaz" data-testid="card-atlaz" style={{ gridColumn: "1 / -1" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8, gap: 10 }}>
        <p style={{ color: "#64748b", fontSize: 13, margin: 0, flex: 1 }}>
          Importa OSs do Atlaz como bolhas e dá baixa automática quando você encerrar/cancelar/reagendar.
          <br />
          <small style={{ color: "#94a3b8" }}>
            Worker periódico roda a cada {form.sync_interval_minutes}min.
            Os caminhos dos endpoints e o mapeamento de campos são configuráveis abaixo —
            ajuste conforme a documentação que você recebeu da equipe Atlaz.
          </small>
        </p>
        {statusBadge}
      </div>

      <Field label="Ativar integração">
        <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <input
            data-testid="atlaz-enabled"
            type="checkbox"
            checked={!!form.enabled}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            style={{ width: 18, height: 18 }}
          />
          <span style={{ fontSize: 13, color: "#475569" }}>
            {form.enabled ? "Integração ativa — pull periódico + push de baixa" : "Integração desligada"}
          </span>
        </label>
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 10 }}>
        <Field label="🌐 Base URL da API">
          <input
            data-testid="atlaz-base-url"
            placeholder="https://api.atlaz.com.br"
            value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            style={inputStyle}
          />
          <small style={{ color: "#94a3b8", fontSize: 11 }}>
            Conforme doc do seu provedor (substitua o placeholder "seuatlaz" pela URL real).
          </small>
        </Field>
        <Field label="Header de auth">
          <input
            data-testid="atlaz-api-key-header"
            placeholder="X-API-Key"
            value={form.api_key_header}
            onChange={(e) => setForm({ ...form, api_key_header: e.target.value })}
            style={inputStyle}
          />
        </Field>
      </div>

      <Field label="🔑 API Key">
        <input
          data-testid="atlaz-api-key"
          type="password"
          placeholder={cfg?.api_key_set ? `Salva: ${cfg.api_key}` : "Cole a chave do Atlaz aqui"}
          value={form.api_key}
          onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          style={inputStyle}
        />
        <small style={{ color: "#94a3b8", fontSize: 11 }}>
          Deixe em branco para manter a chave atual.
        </small>
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 10 }}>
        <Field label="📥 Path para listar OSs">
          <input data-testid="atlaz-list-path" value={form.list_path}
            onChange={(e) => setForm({ ...form, list_path: e.target.value })} style={inputStyle} />
        </Field>
        <Field label="?status=">
          <input data-testid="atlaz-list-status" value={form.list_query_status}
            onChange={(e) => setForm({ ...form, list_query_status: e.target.value })} style={inputStyle} />
        </Field>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
        <Field label="✓ Path concluir">
          <input data-testid="atlaz-close-path" value={form.close_path}
            onChange={(e) => setForm({ ...form, close_path: e.target.value })} style={inputStyle} />
        </Field>
        <Field label="✗ Path cancelar">
          <input data-testid="atlaz-cancel-path" value={form.cancel_path}
            onChange={(e) => setForm({ ...form, cancel_path: e.target.value })} style={inputStyle} />
        </Field>
        <Field label="📅 Path reagendar">
          <input data-testid="atlaz-reschedule-path" value={form.reschedule_path}
            onChange={(e) => setForm({ ...form, reschedule_path: e.target.value })} style={inputStyle} />
        </Field>
      </div>

      <Field label="🏢 Filiais (separadas por vírgula)">
        <input
          data-testid="atlaz-filiais"
          placeholder="FILIAL_CENTRO, FILIAL_NORTE, FILIAL_SUL"
          value={form.filiais_text}
          onChange={(e) => setForm({ ...form, filiais_text: e.target.value })}
          style={inputStyle}
        />
        <small style={{ color: "#94a3b8", fontSize: 11 }}>
          Vazio = busca todas (sem filtro de filial). Cada filial vira uma chamada separada à API.
        </small>
      </Field>

      <FilialCollabMapper
        filiais={form.filiais_text.split(",").map((x) => x.trim()).filter(Boolean)}
        mapping={form.filial_to_collaborator || {}}
        collabs={collabs}
        onChange={(m) => setForm({ ...form, filial_to_collaborator: m })}
      />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
        <Field label="⏱ Intervalo (min)">
          <input data-testid="atlaz-interval" type="number" min={1} max={1440}
            value={form.sync_interval_minutes}
            onChange={(e) => setForm({ ...form, sync_interval_minutes: e.target.value })} style={inputStyle} />
        </Field>
        <Field label="⏰ Timeout (seg)">
          <input data-testid="atlaz-timeout" type="number" min={2} max={120}
            value={form.timeout_seconds}
            onChange={(e) => setForm({ ...form, timeout_seconds: e.target.value })} style={inputStyle} />
        </Field>
        <Field label="Comportamento">
          <label style={{ display: "block", fontSize: 12, marginBottom: 4 }}>
            <input data-testid="atlaz-auto-create" type="checkbox" checked={!!form.auto_create_bubbles}
              onChange={(e) => setForm({ ...form, auto_create_bubbles: e.target.checked })} /> Auto criar bolhas
          </label>
          <label style={{ display: "block", fontSize: 12 }}>
            <input data-testid="atlaz-auto-push" type="checkbox" checked={!!form.auto_push_on_close}
              onChange={(e) => setForm({ ...form, auto_push_on_close: e.target.checked })} /> Push ao encerrar
          </label>
        </Field>
      </div>

      <details style={{ marginTop: 8, background: "#f8fafc", borderRadius: 10, padding: 10, border: "1px solid #e2e8f0" }}>
        <summary style={{ cursor: "pointer", fontWeight: 700, color: "#475569", fontSize: 13 }}>
          🛠 Mapeamentos avançados (JSON) — só altere se a doc do Atlaz usar nomes diferentes
        </summary>
        <Field label="Mapeamento de tipos (JSON)">
          <textarea data-testid="atlaz-type-map" rows={4} value={form.type_map_text}
            onChange={(e) => setForm({ ...form, type_map_text: e.target.value })}
            style={{ ...inputStyle, fontFamily: "monospace", fontSize: 12 }} />
          <small style={{ color: "#94a3b8", fontSize: 11 }}>
            Tipos do Atlaz (UPPERCASE) → tipos internos (reparo|instalacao|retirada|prioridade|preventiva|venda).
          </small>
        </Field>
        <Field label="Mapeamento de campos JSON do Atlaz (JSON)">
          <textarea data-testid="atlaz-field-map" rows={6} value={form.field_map_text}
            onChange={(e) => setForm({ ...form, field_map_text: e.target.value })}
            style={{ ...inputStyle, fontFamily: "monospace", fontSize: 12 }} />
          <small style={{ color: "#94a3b8", fontSize: 11 }}>
            Chave = campo interno (id, client_name, address, neighborhood, phone, type, scheduled_time, relato, filial). Valor = nome do campo no JSON da resposta do Atlaz.
          </small>
        </Field>
      </details>

      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <Button onClick={save} disabled={busy} data-testid="atlaz-save-btn">
          {busy ? "Salvando…" : "💾 Salvar config Atlaz"}
        </Button>
        <Button variant="soft" onClick={runTest} disabled={busy} data-testid="atlaz-test-btn">
          🔌 Testar conexão
        </Button>
        <Button variant="soft" onClick={runSync} disabled={busy} data-testid="atlaz-sync-btn">
          🔄 Sincronizar agora
        </Button>
        <Button variant="soft" onClick={loadLogs} data-testid="atlaz-logs-btn">
          📋 Ver logs
        </Button>
        {msg && <span style={{ color: msg.startsWith("✓") ? "#166534" : "#be123c", fontWeight: 700, fontSize: 13 }}>{msg}</span>}
      </div>

      {test && (
        <div data-testid="atlaz-test-result" style={{
          marginTop: 12, padding: 12, borderRadius: 10,
          background: test.ok ? "#dcfce7" : "#fee2e2",
          border: `1px solid ${test.ok ? "#86efac" : "#fecaca"}`,
          color: test.ok ? "#166534" : "#7f1d1d", fontSize: 12,
        }}>
          <div style={{ fontWeight: 800, marginBottom: 4 }}>
            {test.ok ? `✅ Conectado (HTTP ${test.status})` : `❌ Falha — ${test.reason || test.error || `HTTP ${test.status}`}`}
          </div>
          {test.url && <div><strong>URL:</strong> <code>{test.url}</code></div>}
          {test.sample_count != null && <div><strong>Itens recebidos:</strong> {test.sample_count}</div>}
          {test.sample_keys?.length > 0 && (
            <div style={{ marginTop: 4 }}>
              <strong>Campos detectados no JSON:</strong> <code style={{ fontSize: 11 }}>{test.sample_keys.join(", ")}</code>
            </div>
          )}
          {test.body_preview && (
            <details style={{ marginTop: 6 }}>
              <summary style={{ cursor: "pointer" }}>Ver resposta crua</summary>
              <pre style={{ fontSize: 11, marginTop: 4, whiteSpace: "pre-wrap", maxHeight: 160, overflow: "auto" }}>{test.body_preview}</pre>
            </details>
          )}
        </div>
      )}

      {sync && (
        <div data-testid="atlaz-sync-result" style={{
          marginTop: 12, padding: 12, borderRadius: 10,
          background: sync.ok ? "#dbeafe" : "#fee2e2",
          border: `1px solid ${sync.ok ? "#93c5fd" : "#fecaca"}`,
          color: sync.ok ? "#1e40af" : "#7f1d1d", fontSize: 12,
        }}>
          {sync.ok ? (
            <>
              <strong>✅ Sincronização concluída</strong> — criadas: <strong>{sync.created}</strong>,
              {" "}já existentes: <strong>{sync.skipped}</strong>,
              {" "}erros: <strong>{sync.errors?.length || 0}</strong>
              {sync.errors?.length > 0 && (
                <ul style={{ marginTop: 4, paddingLeft: 18 }}>
                  {sync.errors.slice(0, 5).map((er, i) => <li key={i}>{er}</li>)}
                </ul>
              )}
            </>
          ) : (
            <>❌ {sync.reason || sync.error || "Falha"}</>
          )}
        </div>
      )}

      {showLogs && (
        <div data-testid="atlaz-logs-panel" style={{ marginTop: 12, background: "#0f172a", color: "#e2e8f0", borderRadius: 10, padding: 10, maxHeight: 280, overflowY: "auto", fontFamily: "monospace", fontSize: 11 }}>
          {logs.length === 0 && <div style={{ color: "#94a3b8" }}>Sem logs.</div>}
          {logs.map((l) => (
            <div key={l.id} style={{ paddingBottom: 4, marginBottom: 4, borderBottom: "1px solid rgba(255,255,255,.06)" }}>
              <span style={{ color: l.status === "ok" ? "#34d399" : l.status === "partial" ? "#fbbf24" : "#f87171" }}>
                [{l.status.toUpperCase()}]
              </span>{" "}
              <span style={{ color: "#94a3b8" }}>{new Date(l.at).toLocaleString("pt-BR")}</span>{" "}
              <strong>{l.event}</strong> — {l.details}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function FilialCollabMapper({ filiais, mapping, collabs, onChange }) {
  const list = Array.isArray(filiais) ? filiais : [];

  function setForFilial(filial, collabId) {
    const next = { ...(mapping || {}) };
    if (collabId) next[filial] = collabId;
    else delete next[filial];
    onChange(next);
  }

  // Filiais "órfãs" no mapeamento que não estão mais na lista de filiais
  const orphaned = Object.keys(mapping || {}).filter((f) => !list.includes(f));

  if (list.length === 0 && orphaned.length === 0) {
    return (
      <div data-testid="atlaz-filial-collab-empty" style={{
        background: "#f8fafc", border: "1px dashed #cbd5e1", borderRadius: 10,
        padding: 14, color: "#94a3b8", fontSize: 13, textAlign: "center", marginTop: 8,
      }}>
        Adicione filiais acima para mapear cada uma a um técnico responsável.
      </div>
    );
  }

  return (
    <div data-testid="atlaz-filial-collab-mapper" style={{
      marginTop: 10, background: "#f8fafc", border: "1px solid #e2e8f0",
      borderRadius: 12, padding: 12,
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: "#0f172a", marginBottom: 8 }}>
        🔗 Filial → Técnico responsável
      </div>
      <p style={{ color: "#64748b", fontSize: 12, margin: "0 0 10px" }}>
        Define qual técnico recebe as bolhas importadas de cada filial.
        Filiais sem mapeamento usam o primeiro técnico ativo da empresa como fallback.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {list.map((filial) => (
          <div key={filial} data-testid={`atlaz-fc-row-${filial}`} style={{
            display: "grid", gridTemplateColumns: "1fr 1.4fr",
            gap: 10, alignItems: "center",
            padding: 8, background: "white", borderRadius: 8, border: "1px solid #e2e8f0",
          }}>
            <div style={{ fontWeight: 700, fontSize: 13, color: "#1e293b" }}>{filial}</div>
            <select
              data-testid={`atlaz-fc-select-${filial}`}
              value={(mapping || {})[filial] || ""}
              onChange={(e) => setForFilial(filial, e.target.value)}
              style={{
                padding: "6px 8px", border: "1px solid #cbd5e1",
                borderRadius: 8, fontSize: 13, background: "white",
              }}
            >
              <option value="">— Sem mapeamento (usa fallback) —</option>
              {(collabs || []).map((c) => (
                <option key={c.id} value={c.id}>{c.name} ({c.id})</option>
              ))}
            </select>
          </div>
        ))}
        {orphaned.map((filial) => (
          <div key={filial} data-testid={`atlaz-fc-orphan-${filial}`} style={{
            display: "grid", gridTemplateColumns: "1fr auto",
            gap: 10, alignItems: "center",
            padding: 8, background: "#fef3c7", borderRadius: 8, border: "1px solid #fde68a",
          }}>
            <div style={{ fontSize: 12, color: "#78350f" }}>
              ⚠ <strong>{filial}</strong> mapeada para <code style={{ background: "white", padding: "1px 4px", borderRadius: 4 }}>{mapping[filial]}</code> mas não está mais na lista de filiais ativas.
            </div>
            <button
              data-testid={`atlaz-fc-remove-${filial}`}
              type="button"
              onClick={() => setForFilial(filial, null)}
              style={{ background: "#dc2626", color: "white", border: 0, borderRadius: 6, padding: "4px 8px", fontSize: 11, fontWeight: 700, cursor: "pointer" }}
            >
              Remover
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
