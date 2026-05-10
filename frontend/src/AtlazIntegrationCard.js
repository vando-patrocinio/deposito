import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, inputStyle } from "@/ui";

/**
 * Card de configuração da integração Atlaz V2 (API oficial).
 * Doc: https://app.atlaz.com.br/docs/api
 *
 * IMPORTANTE: A API V2 do Atlaz NÃO permite fechar/cancelar chamados.
 * O fluxo é apenas pull (importa OSs como bolhas). Quando você encerrar
 * a bolha aqui, dá baixa MANUALMENTE no painel web do Atlaz.
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
  const [syncTec, setSyncTec] = useState(null);

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
        api_key: "",
        tenant_domain: c.tenant_domain || "",
        filiais_text: (c.filiais || []).join(", "),
        filial_to_collaborator: { ...(c.filial_to_collaborator || {}) },
        technician_to_collaborator: { ...(c.technician_to_collaborator || {}) },
        lookback_days: c.lookback_days ?? 30,
        sync_interval_minutes: c.sync_interval_minutes ?? 15,
        sync_interval_seconds: c.sync_interval_seconds ?? 30,
        auto_create_bubbles: c.auto_create_bubbles ?? true,
        auto_sync_technicians: c.auto_sync_technicians ?? true,
        tech_sync_interval_minutes: c.tech_sync_interval_minutes ?? 60,
        timeout_seconds: c.timeout_seconds ?? 20,
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
      tenant_domain: (form.tenant_domain || "").replace(/\/$/, ""),
      filiais: form.filiais_text.split(",").map((x) => x.trim()).filter(Boolean),
      filial_to_collaborator: form.filial_to_collaborator || {},
      technician_to_collaborator: form.technician_to_collaborator || {},
      lookback_days: Number(form.lookback_days) || 30,
      sync_interval_minutes: Number(form.sync_interval_minutes) || 15,
      sync_interval_seconds: Number(form.sync_interval_seconds) || 30,
      auto_create_bubbles: form.auto_create_bubbles,
      auto_sync_technicians: !!form.auto_sync_technicians,
      tech_sync_interval_minutes: Number(form.tech_sync_interval_minutes) || 60,
      timeout_seconds: Number(form.timeout_seconds) || 20,
    };
    if (form.api_key) payload.api_key = form.api_key;
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
    try { setTest(await api.atlazTestConnection()); }
    catch (e) { setTest({ ok: false, error: e?.response?.data?.detail || e.message }); }
    setBusy(false);
  }

  async function runSync() {
    setBusy(true); setSync(null); setMsg("");
    try { setSync(await api.atlazSyncNow()); }
    catch (e) { setSync({ ok: false, error: e?.response?.data?.detail || e.message }); }
    setBusy(false);
  }

  async function runSyncTec() {
    setBusy(true); setSyncTec(null); setMsg("");
    try { setSyncTec(await api.atlazSyncTechnicians()); }
    catch (e) { setSyncTec({ ok: false, error: e?.response?.data?.detail || e.message }); }
    setBusy(false);
    await reload();
  }

  async function runReassign() {
    if (!window.confirm("Re-resolver técnico de TODAS as bolhas Atlaz pendentes? Bolhas sem técnico no Atlaz serão movidas para a coluna '📥 Sem técnico (Atlaz)' na Lousa, onde você pode arrastar para o técnico real.")) return;
    setBusy(true); setMsg("");
    try {
      const r = await api.atlazReassignExisting();
      setMsg(`✓ Reatribuição: ${r.moved} movidas para o técnico correto, ${r.moved_to_inbox} para a caixa de entrada, ${r.unchanged} já estavam OK.`);
    } catch (e) { setMsg("Erro: " + (e?.response?.data?.detail || e.message)); }
    setBusy(false);
  }

  async function loadLogs() {
    try {
      const r = await api.atlazSyncLogs(30);
      setLogs(r.items || []);
      setShowLogs(true);
    } catch (e) { setMsg("Erro: " + (e?.response?.data?.detail || e.message)); }
  }

  if (!form) {
    return (
      <Card title="Integração Atlaz" data-testid="card-atlaz">
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
    <Card title="Integração Atlaz V2" data-testid="card-atlaz" style={{ gridColumn: "1 / -1" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8, gap: 10 }}>
        <p style={{ color: "#64748b", fontSize: 13, margin: 0, flex: 1 }}>
          Importa chamados abertos do Atlaz (<code>app.atlaz.com.br/api/v2</code>) como bolhas na Lousa.
          <br />
          <small style={{ color: "#dc2626", fontWeight: 600 }}>
            ⚠ A API Atlaz V2 só permite LER chamados. Para fechar/cancelar, use o painel web do Atlaz após terminar aqui.
          </small>
        </p>
        {statusBadge}
      </div>

      <Field label="Ativar integração">
        <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <input data-testid="atlaz-enabled" type="checkbox" checked={!!form.enabled}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            style={{ width: 18, height: 18 }} />
          <span style={{ fontSize: 13, color: "#475569" }}>
            {form.enabled ? "Pull periódico ATIVO" : "Integração desligada"}
          </span>
        </label>
      </Field>

      <Field label="Token da API Atlaz">
        <input
          data-testid="atlaz-api-key"
          type="password"
          placeholder={cfg?.api_key_set ? `Salvo: ${cfg.api_key}` : "Cole o token do Atlaz aqui"}
          value={form.api_key}
          onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          style={inputStyle}
        />
        <small style={{ color: "#94a3b8", fontSize: 11 }}>
          Obtenha em <code>app.atlaz.com.br</code> → Configurações → Atlaz API.
          Deixe em branco para manter o atual.
        </small>
      </Field>

      <Field label="Domínio do seu painel Atlaz">
        <input
          data-testid="atlaz-tenant-domain"
          placeholder="https://ligofibra.atlaz.com.br"
          value={form.tenant_domain}
          onChange={(e) => setForm({ ...form, tenant_domain: e.target.value })}
          style={inputStyle}
        />
        <small style={{ color: "#94a3b8", fontSize: 11 }}>
          Usado para gerar o link <strong>"🔗 Abrir no Atlaz"</strong> direto da bolha (chamados sincronizados ganham atalho rápido para fechar manualmente lá).
        </small>
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
        <Field label="Janela retroativa (dias)">
          <input data-testid="atlaz-lookback" type="number" min={1} max={365}
            value={form.lookback_days}
            onChange={(e) => setForm({ ...form, lookback_days: e.target.value })} style={inputStyle} />
          <small style={{ color: "#94a3b8", fontSize: 10 }}>Atlaz exige data inicial obrigatória.</small>
        </Field>
        <Field label="Intervalo bolhas (seg)">
          <input data-testid="atlaz-interval-seconds" type="number" min={10} max={86400}
            value={form.sync_interval_seconds}
            onChange={(e) => setForm({ ...form, sync_interval_seconds: e.target.value })} style={inputStyle} />
          <small style={{ color: "#94a3b8", fontSize: 10 }}>Default 30s. Mín 10s, máx 24h.</small>
        </Field>
        <Field label="Timeout (seg)">
          <input data-testid="atlaz-timeout" type="number" min={2} max={120}
            value={form.timeout_seconds}
            onChange={(e) => setForm({ ...form, timeout_seconds: e.target.value })} style={inputStyle} />
        </Field>
      </div>

      <Field label="Filiais (cidades — separadas por vírgula)">
        <input
          data-testid="atlaz-filiais"
          placeholder="Rio de Janeiro, Guaratinguetá, Osasco, Magé"
          value={form.filiais_text}
          onChange={(e) => setForm({ ...form, filiais_text: e.target.value })}
          style={inputStyle}
        />
        <small style={{ color: "#94a3b8", fontSize: 11 }}>
          Filtra por <code>ponto.cidade</code>. Vazio = traz todas. Use os nomes que aparecem no botão Testar.
        </small>
      </Field>

      <FilialMapper
        filiais={form.filiais_text.split(",").map((x) => x.trim()).filter(Boolean)}
        mapping={form.filial_to_collaborator || {}}
        collabs={collabs}
        onChange={(m) => setForm({ ...form, filial_to_collaborator: m })}
      />

      <TecnicoMapper
        technicians={Object.keys(test?.tecnicos_atlaz || {})}
        mapping={form.technician_to_collaborator || {}}
        collabs={collabs}
        onChange={(m) => setForm({ ...form, technician_to_collaborator: m })}
      />

      <Field label="">
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#475569" }}>
          <input data-testid="atlaz-auto-create" type="checkbox" checked={!!form.auto_create_bubbles}
            onChange={(e) => setForm({ ...form, auto_create_bubbles: e.target.checked })} />
          Criar bolhas automaticamente no pull (recomendado)
        </label>
      </Field>

      <div data-testid="atlaz-auto-sync-section" style={{
        marginTop: 12, padding: 12, background: "linear-gradient(135deg,#ecfdf5,#d1fae5)",
        border: "1px solid #6ee7b7", borderRadius: 12,
      }}>
        <div style={{ fontWeight: 800, fontSize: 13, color: "#064e3b", marginBottom: 6 }}>
          🔄 Atualizações automáticas
        </div>
        <p style={{ fontSize: 11, color: "#065f46", margin: "0 0 10px" }}>
          O sistema sincroniza automaticamente em segundo plano enquanto a integração estiver ativa.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div style={{ background: "white", padding: 10, borderRadius: 10, border: "1px solid #a7f3d0" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 12, color: "#065f46" }}>
              <span>📋 Bolhas (Lousa)</span>
            </label>
            <div style={{ fontSize: 10, color: "#047857", marginTop: 4 }}>
              A cada <strong>{form.sync_interval_seconds || 30}s</strong>
            </div>
            <div data-testid="atlaz-last-bubble-sync" style={{ fontSize: 10, color: "#475569", marginTop: 4 }}>
              Último: <strong>{cfg?.last_auto_sync_bubbles_at ? new Date(cfg.last_auto_sync_bubbles_at).toLocaleString("pt-BR") : "—"}</strong>
            </div>
          </div>

          <div style={{ background: "white", padding: 10, borderRadius: 10, border: "1px solid #a7f3d0" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 12, color: "#065f46", cursor: "pointer" }}>
              <input data-testid="atlaz-auto-sync-tec" type="checkbox" checked={!!form.auto_sync_technicians}
                onChange={(e) => setForm({ ...form, auto_sync_technicians: e.target.checked })} />
              <span>👷 Técnicos (Cadastro)</span>
            </label>
            {form.auto_sync_technicians ? (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                  <span style={{ fontSize: 10, color: "#047857" }}>A cada</span>
                  <input
                    data-testid="atlaz-tec-interval"
                    type="number" min={5} max={1440}
                    value={form.tech_sync_interval_minutes}
                    onChange={(e) => setForm({ ...form, tech_sync_interval_minutes: e.target.value })}
                    style={{ width: 60, padding: "2px 6px", border: "1px solid #cbd5e1", borderRadius: 4, fontSize: 11 }}
                  />
                  <span style={{ fontSize: 10, color: "#047857" }}>min</span>
                </div>
                <div data-testid="atlaz-last-tec-sync" style={{ fontSize: 10, color: "#475569", marginTop: 4 }}>
                  Último: <strong>{cfg?.last_auto_sync_technicians_at ? new Date(cfg.last_auto_sync_technicians_at).toLocaleString("pt-BR") : "—"}</strong>
                </div>
              </>
            ) : (
              <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 4, fontStyle: "italic" }}>
                Desligado — use o botão "Sincronizar técnicos" manualmente.
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <Button onClick={save} disabled={busy} data-testid="atlaz-save-btn">
          {busy ? "Salvando…" : "💾 Salvar"}
        </Button>
        <Button variant="soft" onClick={runTest} disabled={busy} data-testid="atlaz-test-btn">🔌 Testar conexão</Button>
        <Button variant="soft" onClick={runSync} disabled={busy} data-testid="atlaz-sync-btn">🔄 Sincronizar agora</Button>
        <Button variant="soft" onClick={runSyncTec} disabled={busy} data-testid="atlaz-sync-tec-btn"
          style={{ background: "#fef3c7", border: "1px solid #fcd34d", color: "#78350f" }}>
          👷 Sincronizar técnicos → Cadastro
        </Button>
        <Button variant="soft" onClick={runReassign} disabled={busy} data-testid="atlaz-reassign-btn"
          style={{ background: "#fae8ff", border: "1px solid #f0abfc", color: "#86198f" }}
          title="Re-resolve o técnico de todas as bolhas Atlaz pendentes baseado no mapping atual">
          🔁 Reatribuir bolhas existentes
        </Button>
        <Button variant="soft" onClick={loadLogs} data-testid="atlaz-logs-btn">📋 Ver logs</Button>
        {msg && <span style={{ color: msg.startsWith("✓") ? "#166534" : "#be123c", fontWeight: 700, fontSize: 13 }}>{msg}</span>}
      </div>

      {test && (
        <div data-testid="atlaz-test-result" style={{
          marginTop: 12, padding: 12, borderRadius: 10,
          background: test.ok ? "#dcfce7" : "#fee2e2",
          border: `1px solid ${test.ok ? "#86efac" : "#fecaca"}`,
          color: test.ok ? "#166534" : "#7f1d1d", fontSize: 12,
        }}>
          <div style={{ fontWeight: 800, marginBottom: 6 }}>
            {test.ok
              ? `✅ Conectado — ${test.total_chamados} chamados abertos nos últimos ${test.lookback_days} dias`
              : `❌ Falha: ${test.error || test.reason}`}
          </div>
          {test.ok && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginTop: 8 }}>
              <BreakdownBox title="Por cidade" data={test.cidades} />
              <BreakdownBox title="Por tipo" data={test.tipos} />
              <BreakdownBox title="Técnicos Atlaz" data={test.tecnicos_atlaz} />
            </div>
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
              <strong>✅ Sincronização</strong> — recebidas: <strong>{sync.fetched ?? 0}</strong>,
              {" "}criadas: <strong>{sync.created}</strong>,
              {" "}já existentes: <strong>{sync.skipped}</strong>,
              {" "}erros: <strong>{sync.errors?.length || 0}</strong>
              {sync.errors?.length > 0 && (
                <ul style={{ marginTop: 4, paddingLeft: 18 }}>
                  {sync.errors.slice(0, 5).map((er, i) => <li key={i}>{er}</li>)}
                </ul>
              )}
            </>
          ) : (<>❌ {sync.reason || sync.error}</>)}
        </div>
      )}

      {syncTec && (
        <div data-testid="atlaz-synctec-result" style={{
          marginTop: 12, padding: 12, borderRadius: 10,
          background: syncTec.ok ? "#fef9c3" : "#fee2e2",
          border: `1px solid ${syncTec.ok ? "#fde68a" : "#fecaca"}`,
          color: syncTec.ok ? "#713f12" : "#7f1d1d", fontSize: 12,
        }}>
          {syncTec.ok ? (
            <>
              <strong>👷 Técnicos sincronizados</strong> — total Atlaz: <strong>{syncTec.total_atlaz_technicians}</strong>,
              {" "}criados: <strong>{syncTec.created}</strong>,
              {" "}já existentes: <strong>{syncTec.matched_existing}</strong>
              {syncTec.items_created?.length > 0 && (
                <ul style={{ marginTop: 6, paddingLeft: 18 }}>
                  {syncTec.items_created.map((i) => (
                    <li key={i.id}><strong>{i.nome}</strong> {i.email && <span style={{ opacity: 0.7 }}>· {i.email}</span>} → <code>{i.id}</code></li>
                  ))}
                </ul>
              )}
              <div style={{ marginTop: 6, fontStyle: "italic", opacity: 0.8 }}>
                Os colaboradores aparecem agora em <strong>Cadastro</strong>. O mapeamento Técnico→Colab foi atualizado automaticamente.
              </div>
            </>
          ) : (
            <>❌ {syncTec.reason || syncTec.error}</>
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

function BreakdownBox({ title, data }) {
  const entries = Object.entries(data || {}).slice(0, 8);
  return (
    <div style={{ background: "rgba(255,255,255,.5)", borderRadius: 8, padding: 8, fontSize: 11 }}>
      <div style={{ fontWeight: 800, marginBottom: 4 }}>{title}</div>
      {entries.length === 0 && <div style={{ color: "#94a3b8" }}>—</div>}
      {entries.map(([k, v]) => (
        <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "1px 0" }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 140 }}>{k}</span>
          <strong>{v}</strong>
        </div>
      ))}
    </div>
  );
}

function FilialMapper({ filiais, mapping, collabs, onChange }) {
  if (!filiais.length) return null;
  return (
    <div data-testid="atlaz-filial-collab-mapper" style={{
      marginTop: 10, background: "#f0f9ff", border: "1px solid #bae6fd",
      borderRadius: 12, padding: 12,
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: "#0c4a6e", marginBottom: 6 }}>
        🏢 Mapeamento Filial → Técnico padrão
      </div>
      <p style={{ color: "#0369a1", fontSize: 11, margin: "0 0 10px" }}>
        Usado quando o chamado Atlaz não tem técnico atribuído.
      </p>
      {filiais.map((f) => (
        <div key={f} data-testid={`atlaz-fc-row-${f}`} style={{
          display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: 8,
          padding: 6, marginBottom: 4, background: "white", borderRadius: 6,
          border: "1px solid #e0f2fe", alignItems: "center",
        }}>
          <div style={{ fontSize: 12, fontWeight: 600 }}>{f}</div>
          <select
            data-testid={`atlaz-fc-select-${f}`}
            value={mapping[f] || ""}
            onChange={(e) => {
              const m = { ...mapping };
              if (e.target.value) m[f] = e.target.value; else delete m[f];
              onChange(m);
            }}
            style={{ padding: "4px 8px", border: "1px solid #cbd5e1", borderRadius: 6, fontSize: 12 }}
          >
            <option value="">— fallback —</option>
            {(collabs || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      ))}
    </div>
  );
}

function TecnicoMapper({ technicians, mapping, collabs, onChange }) {
  if (!technicians?.length) {
    return (
      <div style={{
        marginTop: 10, background: "#fef3c7", border: "1px dashed #fde68a",
        borderRadius: 12, padding: 12, fontSize: 12, color: "#78350f",
      }}>
        💡 Clique em <strong>🔌 Testar conexão</strong> para listar os técnicos do Atlaz e mapeá-los aos colaboradores locais.
      </div>
    );
  }
  return (
    <div data-testid="atlaz-tec-mapper" style={{
      marginTop: 10, background: "#fefce8", border: "1px solid #fef08a",
      borderRadius: 12, padding: 12,
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: "#713f12", marginBottom: 6 }}>
        👷 Mapeamento Técnico Atlaz → Colaborador local (prioridade máxima)
      </div>
      <p style={{ color: "#854d0e", fontSize: 11, margin: "0 0 10px" }}>
        Quando o chamado Atlaz vem com técnico atribuído, esse mapeamento é usado.
      </p>
      <div style={{ maxHeight: 220, overflowY: "auto" }}>
        {technicians.map((t) => (
          <div key={t} data-testid={`atlaz-tec-row-${t}`} style={{
            display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: 8,
            padding: 6, marginBottom: 4, background: "white", borderRadius: 6,
            border: "1px solid #fef9c3", alignItems: "center",
          }}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{t}</div>
            <select
              data-testid={`atlaz-tec-select-${t}`}
              value={mapping[t] || ""}
              onChange={(e) => {
                const m = { ...mapping };
                if (e.target.value) m[t] = e.target.value; else delete m[t];
                onChange(m);
              }}
              style={{ padding: "4px 8px", border: "1px solid #cbd5e1", borderRadius: 6, fontSize: 12 }}
            >
              <option value="">— ignorar (usa fallback) —</option>
              {(collabs || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
        ))}
      </div>
    </div>
  );
}
