// iter205 — Painel de Backup do MongoDB.
// Super-admin lista, gera novos backups via mongodump, faz download
// (stream do .tar.gz) e apaga backups antigos pra liberar disco.
import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { Database, Download, Trash2, RefreshCw, ShieldAlert, Cloud, CloudOff, Upload } from "lucide-react";

const card = {
  background: "white",
  border: "1px solid #e2e8f0",
  borderRadius: 14,
  padding: 22,
};

const btnDark = {
  background: "#0f172a",
  color: "white",
  border: "none",
  borderRadius: 10,
  padding: "10px 16px",
  fontWeight: 700,
  fontSize: 13,
  cursor: "pointer",
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
};

const btnGhost = {
  ...btnDark,
  background: "#f1f5f9",
  color: "#0f172a",
};

const btnDanger = {
  ...btnDark,
  background: "#fef2f2",
  color: "#b91c1c",
  border: "1px solid #fecaca",
};

function formatRelativeDate(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function BackupPanel() {
  const [data, setData] = useState({ backups: [], total_size_human: "0 MB" });
  const [drive, setDrive] = useState({ connected: false });
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [uploadingTo, setUploadingTo] = useState("");  // filename in progress
  // iter205i — Download progress
  const [downloadingFile, setDownloadingFile] = useState("");
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  // Restore state
  const [restoreFile, setRestoreFile] = useState(null);
  const [restoreDrop, setRestoreDrop] = useState(false);
  const [restoreConfirmText, setRestoreConfirmText] = useState("");
  const [restoring, setRestoring] = useState(false);
  const restoreInputRef = useRef(null);
  // Migrate state (iter205f)
  const [migSourceUrl, setMigSourceUrl] = useState("https://dual-combine-3.emergent.host");
  const [migSourceToken, setMigSourceToken] = useState("");
  const [migDrop, setMigDrop] = useState(true);
  const [migrating, setMigrating] = useState(false);
  // Migrate auto-schedule (iter205g)
  const [migAutoCfg, setMigAutoCfg] = useState({ enabled: false, has_token: false });
  const [migAutoSaving, setMigAutoSaving] = useState(false);
  const [migAutoTokenInput, setMigAutoTokenInput] = useState("");

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const [list, ds, autoCfg] = await Promise.all([
        api.backupList(),
        api.backupDriveStatus().catch(() => ({ connected: false })),
        api.backupMigrateConfigGet().catch(() => ({ enabled: false })),
      ]);
      setData(list);
      setDrive(ds);
      setMigAutoCfg(autoCfg);
      if (autoCfg.source_url && !migSourceUrl.startsWith("http")) {
        setMigSourceUrl(autoCfg.source_url);
      }
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);

  async function onCreate() {
    if (!window.confirm(
      "Gerar novo backup completo do MongoDB?\n\n" +
      "Isso pode levar de 30 segundos a alguns minutos dependendo do tamanho.")) return;
    setCreating(true);
    setError("");
    setInfo("");
    try {
      const r = await api.backupCreate();
      setInfo(`✅ Backup criado: ${r.filename} · ${r.size_human}`);
      await refresh();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setCreating(false);
    }
  }

  async function onUploadDrive(filename) {
    setError("");
    setInfo("");
    setUploadingTo(filename);
    try {
      await api.backupUploadDrive(filename);
      setInfo(`${filename} enviado para o Google Drive.`);
    } catch (e) {
      setError(`Drive upload falhou: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setUploadingTo("");
    }
  }

  async function onRestore() {
    if (!restoreFile) {
      setError("Selecione um arquivo .tar.gz primeiro.");
      return;
    }
    if (restoreConfirmText !== "RESTAURAR") {
      setError("Digite RESTAURAR para confirmar a operação destrutiva.");
      return;
    }
    if (!window.confirm(
      `️ ATENÇÃO — RESTAURAÇÃO DE BANCO\n\n` +
      `Arquivo: ${restoreFile.name}\n` +
      `Tamanho: ${(restoreFile.size / (1024*1024)).toFixed(1)} MB\n` +
      `Sobrescrever (drop): ${restoreDrop ? "SIM (apaga dados existentes)" : "Não (só adiciona)"}\n\n` +
      `Esta operação pode levar minutos. Confirma?`)) return;

    setRestoring(true);
    setError("");
    setInfo("");
    try {
      const r = await api.backupRestore(restoreFile, restoreDrop);
      setInfo(
        `✅ Restauração concluída · op=${r.operation_id} · ` +
        `drop=${r.drop_used ? "sim" : "não"}`);
      setRestoreFile(null);
      setRestoreConfirmText("");
      if (restoreInputRef.current) restoreInputRef.current.value = "";
      await refresh();
    } catch (e) {
      setError(`Restore falhou: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setRestoring(false);
    }
  }

  async function onMigrate() {
    if (!migSourceUrl || !migSourceToken) {
      setError("Preencha URL de origem e token.");
      return;
    }
    if (!window.confirm(
      `️ MIGRAR de OUTRO AMBIENTE → ESTE\n\n` +
      `Origem: ${migSourceUrl}\n` +
      `Sobrescrever (drop): ${migDrop ? "SIM (apaga dados deste ambiente)" : "Não (só adiciona)"}\n\n` +
      `O processo: dump remoto → download → restore.\n` +
      `Pode levar 1-5 minutos. Confirma?`)) return;

    setMigrating(true);
    setError("");
    setInfo("");
    try {
      const r = await api.backupMigrateFromRemote(
        migSourceUrl, migSourceToken, migDrop);
      setInfo(
        `✅ Migração concluída · op=${r.operation_id} · ` +
        `baixado=${r.downloaded_human} · ` +
        `drop=${r.drop_used ? "sim" : "não"}`);
      setMigSourceToken("");  // limpa por segurança
      await refresh();
    } catch (e) {
      setError(`Migração falhou: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setMigrating(false);
    }
  }

  async function saveMigrateAuto(enable) {
    setMigAutoSaving(true);
    setError("");
    setInfo("");
    try {
      // Se já tem token salvo, mantém. Senão usa o que está no input.
      const token = migAutoTokenInput || (migAutoCfg.has_token ? "" : migSourceToken);
      await api.backupMigrateConfigSet(enable, migSourceUrl, token, migDrop);
      setInfo(enable
        ? "✅ Migração automática ativada (domingo 04:00 UTC)"
        : "✅ Migração automática desativada");
      setMigAutoTokenInput("");
      await refresh();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setMigAutoSaving(false);
    }
  }

  async function onDownload(filename) {
    setError("");
    setInfo("");
    setDownloadingFile(filename);
    setDownloadProgress(0);
    try {
      const token = localStorage.getItem("ponto_token") || "";
      const base = process.env.REACT_APP_BACKEND_URL;
      const r = await fetch(
        `${base}/api/admin/backup/download/${filename}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);

      // iter205i — stream com progresso real (substitui blob() opaco)
      const contentLength = +r.headers.get("Content-Length") || 0;
      const reader = r.body.getReader();
      const chunks = [];
      let received = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.length;
        if (contentLength) {
          setDownloadProgress(Math.round((received / contentLength) * 100));
        }
      }
      const blob = new Blob(chunks, { type: "application/gzip" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      const mb = (received / (1024 * 1024)).toFixed(1);
      setInfo(
        `${filename} (${mb} MB) baixado. ` +
        `Verifique a pasta Downloads do seu navegador ` +
        `(atalho Ctrl+J / Cmd+J).`
      );
    } catch (e) {
      setError(`Download falhou: ${e.message}`);
    } finally {
      setDownloadingFile("");
      setDownloadProgress(0);
    }
  }

  async function onDelete(filename) {
    if (!window.confirm(`Apagar ${filename}? Esta ação não pode ser desfeita.`)) return;
    setError("");
    setInfo("");
    try {
      await api.backupDelete(filename);
      setInfo(`${filename} apagado.`);
      await refresh();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  }

  return (
    <div data-testid="backup-panel" style={{ display: "grid", gap: 18 }}>
      <div style={card}>
        <div style={{ display: "flex", alignItems: "center",
                       justifyContent: "space-between",
                       flexWrap: "wrap", gap: 12, marginBottom: 12 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800,
                          color: "#0f172a",
                          display: "flex", alignItems: "center", gap: 10 }}>
              <Database size={22} /> Backups do MongoDB
            </h2>
            <p style={{ margin: "6px 0 0", fontSize: 13, color: "#64748b" }}>
              Snapshots completos do banco (.tar.gz). Use para
              migração entre ambientes ou recuperação de dados.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button data-testid="backup-refresh"
                    onClick={refresh} disabled={loading}
                    style={btnGhost}>
              <RefreshCw size={14} /> Atualizar
            </button>
            <button data-testid="backup-create"
                    onClick={onCreate} disabled={creating}
                    style={btnDark}>
              <Database size={14} /> {creating ? "Gerando…" : "Gerar Novo Backup"}
            </button>
          </div>
        </div>

        {error && (
          <div style={{ padding: 10, background: "#fef2f2",
                         border: "1px solid #fecaca",
                         borderRadius: 8, color: "#b91c1c",
                         fontSize: 13, marginBottom: 12,
                         display: "flex", gap: 8, alignItems: "center" }}>
            <ShieldAlert size={16} /> {error}
          </div>
        )}
        {info && (
          <div style={{ padding: 10, background: "#f0fdf4",
                         border: "1px solid #bbf7d0",
                         borderRadius: 8, color: "#065f46",
                         fontSize: 13, marginBottom: 12 }}>
            {info}
          </div>
        )}

        {/* Status do Google Drive (iter205d) */}
        <div style={{ padding: 10,
                       background: drive.needs_reconnect
                         ? "#fef2f2"
                         : (drive.connected ? "#eff6ff" : "#fff7ed"),
                       border: `1px solid ${
                         drive.needs_reconnect
                           ? "#fecaca"
                           : (drive.connected ? "#bfdbfe" : "#fed7aa")}`,
                       borderRadius: 8, marginBottom: 12,
                       display: "flex", alignItems: "center",
                       gap: 10, fontSize: 13,
                       color: drive.needs_reconnect
                         ? "#b91c1c"
                         : (drive.connected ? "#1d4ed8" : "#9a3412") }}>
          {drive.connected && !drive.needs_reconnect
            ? <Cloud size={16} />
            : <CloudOff size={16} />}
          <div style={{ flex: 1 }}>
            {drive.needs_reconnect ? (
              <>
                <strong>Token do Google Drive expirou.</strong> Os backups
                diários NÃO estão sendo enviados. Reconecte em
                {" "}<em>Sistema → Configurações → Google Drive</em>.
                {drive.last_error_at && (
                  <span style={{ display: "block", fontSize: 11,
                                  marginTop: 4, opacity: 0.7 }}>
                    Última falha: {formatRelativeDate(drive.last_error_at)}
                  </span>
                )}
              </>
            ) : drive.connected ? (
              <>
                <strong>Google Drive conectado</strong> — backups diários
                serão enviados automaticamente para a pasta
                <code style={{ background: "rgba(0,0,0,0.06)", padding: "1px 6px",
                                borderRadius: 4, margin: "0 4px" }}>
                  PontoIA-Backups/MongoDB-Dumps
                </code>
                {drive.user_email && <span> · conta: <strong>{drive.user_email}</strong></span>}
              </>
            ) : (
              <>
                <strong>Google Drive não conectado.</strong> Backups ficam só
                no disco do pod. Para upload automático, conecte em
                {" "}<em>Sistema → Configurações → Google Drive</em>.
              </>
            )}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns:
                       "repeat(auto-fit, minmax(180px, 1fr))",
                       gap: 12, marginBottom: 16 }}>
          <Stat label="Backups disponíveis" value={data.count ?? 0} />
          <Stat label="Espaço usado" value={data.total_size_human || "0 MB"} />
          <Stat label="Diretório" value={data.dir || "/app/backups"} small />
        </div>

        {data.backups?.length === 0 ? (
          <div style={{ padding: 24, textAlign: "center",
                         background: "#f8fafc",
                         border: "1px dashed #cbd5e1",
                         borderRadius: 10, color: "#64748b",
                         fontSize: 14 }}>
            Nenhum backup salvo ainda — clica em <strong>Gerar Novo Backup</strong>.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {data.backups.map((b) => (
              <div key={b.filename} data-testid={`backup-row-${b.filename}`}
                   style={{ display: "flex", alignItems: "center",
                            justifyContent: "space-between", gap: 12,
                            padding: 12,
                            background: "#f8fafc",
                            border: "1px solid #e2e8f0",
                            borderRadius: 10, flexWrap: "wrap" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 14,
                                color: "#0f172a",
                                wordBreak: "break-all" }}>
                    {b.filename}
                  </div>
                  <div style={{ fontSize: 12, color: "#64748b",
                                marginTop: 4,
                                display: "flex", gap: 12, flexWrap: "wrap" }}>
                    <span>{b.size_human}</span>
                    <span>{formatRelativeDate(b.created_at)}</span>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  {drive.connected && !drive.needs_reconnect && (
                    <button data-testid={`backup-drive-${b.filename}`}
                            onClick={() => onUploadDrive(b.filename)}
                            disabled={uploadingTo === b.filename}
                            title="Enviar para o Google Drive"
                            style={btnGhost}>
                      <Cloud size={14} />
                      {uploadingTo === b.filename ? "Enviando…" : "Drive"}
                    </button>
                  )}
                  <button data-testid={`backup-download-${b.filename}`}
                          onClick={() => onDownload(b.filename)}
                          disabled={downloadingFile === b.filename}
                          style={btnDark}>
                    <Download size={14} />
                    {downloadingFile === b.filename
                      ? `Baixando… ${downloadProgress}%`
                      : "Baixar"}
                  </button>
                  <button data-testid={`backup-delete-${b.filename}`}
                          onClick={() => onDelete(b.filename)}
                          style={btnDanger}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ ...card, background: "#eff6ff",
                     borderColor: "#bfdbfe" }}>
        <h3 style={{ margin: "0 0 6px", fontSize: 16, fontWeight: 800,
                      color: "#1e40af",
                      display: "flex", alignItems: "center", gap: 8 }}>
          <Cloud size={18} /> Migrar de outro ambiente (1 clique)
        </h3>
        <p style={{ margin: "0 0 12px", fontSize: 13, color: "#1e3a8a" }}>
          Copia dados de OUTRO ambiente Emergent direto pra cá (gera dump
          lá, baixa pelo backend, restaura aqui). Útil para sincronizar
          PROD → PREVIEW sem depender do suporte.
        </p>

        <div style={{ display: "grid", gap: 10 }}>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: "#1e40af",
                             display: "block", marginBottom: 4 }}>
              URL do ambiente origem
            </label>
            <input type="url"
                   value={migSourceUrl}
                   data-testid="migrate-source-url"
                   onChange={(e) => setMigSourceUrl(e.target.value)}
                   placeholder="https://dual-combine-3.emergent.host"
                   disabled={migrating}
                   style={{ padding: "8px 12px", fontSize: 13,
                            border: "1px solid #93c5fd",
                            borderRadius: 8, width: "100%",
                            maxWidth: 540 }} />
            <div style={{ fontSize: 11, color: "#475569", marginTop: 4 }}>
              Só *.emergent.host, *.emergentagent.com e
              *.cluster-7.deploy.emergentcf.cloud são aceitos.
            </div>
          </div>

          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: "#1e40af",
                             display: "block", marginBottom: 4 }}>
              Token JWT do super-admin (no ambiente origem)
            </label>
            <input type="password"
                   value={migSourceToken}
                   data-testid="migrate-source-token"
                   onChange={(e) => setMigSourceToken(e.target.value)}
                   placeholder="eyJhbGciOi..."
                   disabled={migrating}
                   style={{ padding: "8px 12px", fontSize: 12,
                            fontFamily: "monospace",
                            border: "1px solid #93c5fd",
                            borderRadius: 8, width: "100%",
                            maxWidth: 540 }} />
            <div style={{ fontSize: 11, color: "#475569", marginTop: 4 }}>
              Faça login no ambiente origem com super-admin, abra DevTools
              e copie o <code>access_token</code> do localStorage. Ou rode:{" "}
              <code>{`curl -X POST {URL}/api/auth/login -H "Content-Type: application/json" -d '{"email":"...","password":"..."}'`}</code>
            </div>
          </div>

          <label style={{ display: "flex", alignItems: "center", gap: 8,
                           fontSize: 13, color: "#1e3a8a", cursor: "pointer" }}>
            <input type="checkbox"
                   checked={migDrop}
                   data-testid="migrate-drop-checkbox"
                   onChange={(e) => setMigDrop(e.target.checked)}
                   disabled={migrating} />
            <span>
              <strong>Sobrescrever este ambiente (--drop)</strong>
              {" — recomendado para PROD → PREVIEW. "}
              Sem isso, dados deste ambiente são preservados e
              só os novos são adicionados.
            </span>
          </label>

          <button data-testid="migrate-submit"
                  onClick={onMigrate}
                  disabled={migrating || !migSourceUrl || !migSourceToken}
                  style={{
                    background: "#1e40af",
                    color: "white",
                    border: "none",
                    borderRadius: 10,
                    padding: "10px 20px",
                    fontWeight: 700,
                    fontSize: 13,
                    cursor: "pointer",
                    opacity: (migrating || !migSourceUrl || !migSourceToken) ? 0.5 : 1,
                    display: "inline-flex", alignItems: "center",
                    gap: 8, width: "fit-content" }}>
            <Cloud size={14} />
            {migrating ? "Migrando… (pode levar minutos)" : "Migrar agora"}
          </button>

          {/* Sub-card: agendamento automático (iter205g) */}
          <div style={{ marginTop: 14, padding: 12,
                         background: "white",
                         border: "1px solid #c7d2fe",
                         borderRadius: 10 }}>
            <div style={{ fontWeight: 700, fontSize: 13, color: "#1e3a8a",
                           marginBottom: 6 }}>
              ⏰ Migração automática semanal
            </div>
            <div style={{ fontSize: 12, color: "#475569", marginBottom: 10 }}>
              Roda automaticamente <strong>todo domingo 04:00 UTC</strong>{" "}
              (01:00 BRT) usando a URL e token salvos abaixo.
            </div>

            {migAutoCfg.enabled ? (
              <div style={{ display: "grid", gap: 8 }}>
                <div style={{ padding: 8, background: "#dcfce7",
                               border: "1px solid #86efac",
                               borderRadius: 6, fontSize: 12,
                               color: "#166534" }}>
                  ✅ <strong>Ativado.</strong> Próxima execução: domingo 04:00 UTC.
                  {migAutoCfg.has_token && (
                    <div style={{ marginTop: 4, fontFamily: "monospace",
                                   fontSize: 11 }}>
                      Token: {migAutoCfg.source_token_preview}
                    </div>
                  )}
                </div>
                {migAutoCfg.last_run_at && (
                  <div style={{ fontSize: 11, color: "#64748b" }}>
                    Última execução: <strong>{formatRelativeDate(migAutoCfg.last_run_at)}</strong>
                    {" · status: "}
                    <strong style={{ color: migAutoCfg.last_status === "ok"
                      ? "#16a34a" : "#dc2626" }}>
                      {migAutoCfg.last_status || "—"}
                    </strong>
                    {migAutoCfg.last_error && (
                      <div style={{ marginTop: 4, color: "#b91c1c" }}>
                        Erro: {migAutoCfg.last_error}
                      </div>
                    )}
                  </div>
                )}
                <button data-testid="migrate-auto-disable"
                        onClick={() => saveMigrateAuto(false)}
                        disabled={migAutoSaving}
                        style={{ ...btnGhost, alignSelf: "start" }}>
                  Desativar
                </button>
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8 }}>
                <input type="password"
                       value={migAutoTokenInput}
                       data-testid="migrate-auto-token"
                       onChange={(e) => setMigAutoTokenInput(e.target.value)}
                       placeholder="Cole aqui o JWT do super-admin (PROD)"
                       disabled={migAutoSaving}
                       style={{ padding: "8px 12px", fontSize: 12,
                                fontFamily: "monospace",
                                border: "1px solid #c7d2fe",
                                borderRadius: 8, width: "100%",
                                maxWidth: 540 }} />
                <div style={{ fontSize: 11, color: "#64748b" }}>
                  Usa a URL “<strong>{migSourceUrl}</strong>” e o checkbox
                  “<strong>{migDrop ? "Sobrescrever" : "Não sobrescrever"}</strong>”{" "}
                  configurados acima.
                </div>
                <button data-testid="migrate-auto-enable"
                        onClick={() => saveMigrateAuto(true)}
                        disabled={migAutoSaving || !migAutoTokenInput || !migSourceUrl}
                        style={{ ...btnDark,
                                  background: "#3730a3",
                                  alignSelf: "start",
                                  opacity: (!migAutoTokenInput || !migSourceUrl) ? 0.5 : 1 }}>
                  {migAutoSaving ? "Salvando…" : "Ativar agendamento"}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={{ ...card, background: "#fef2f2",
                     borderColor: "#fecaca" }}>
        <h3 style={{ margin: "0 0 6px", fontSize: 16, fontWeight: 800,
                      color: "#991b1b",
                      display: "flex", alignItems: "center", gap: 8 }}>
          <ShieldAlert size={18} /> Zona perigosa — Restaurar Banco
        </h3>
        <p style={{ margin: "0 0 12px", fontSize: 13, color: "#7f1d1d" }}>
          Suba um <code>.tar.gz</code> gerado por <strong>Gerar Novo Backup</strong>
          {" "}para restaurar o MongoDB. <strong>OPERAÇÃO DESTRUTIVA</strong> —
          use só em emergência (corrupção, rollback, migração entre ambientes).
        </p>

        <div style={{ display: "grid", gap: 10 }}>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: "#7f1d1d",
                             display: "block", marginBottom: 4 }}>
              Arquivo .tar.gz
            </label>
            <input ref={restoreInputRef}
                   type="file" accept=".tar.gz,.gz,application/gzip"
                   data-testid="restore-file-input"
                   onChange={(e) => setRestoreFile(e.target.files?.[0] || null)}
                   disabled={restoring}
                   style={{ fontSize: 13 }} />
            {restoreFile && (
              <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
                Selecionado: <strong>{restoreFile.name}</strong>
                {" · "}{(restoreFile.size / (1024*1024)).toFixed(1)} MB
              </div>
            )}
          </div>

          <label style={{ display: "flex", alignItems: "center", gap: 8,
                           fontSize: 13, color: "#7f1d1d", cursor: "pointer" }}>
            <input type="checkbox"
                   checked={restoreDrop}
                   data-testid="restore-drop-checkbox"
                   onChange={(e) => setRestoreDrop(e.target.checked)}
                   disabled={restoring} />
            <span>
              <strong>Sobrescrever coleções (--drop)</strong>
              {" — apaga dados existentes antes de restaurar. "}
              Sem isso, mongorestore só adiciona documentos novos
              (ignora os com _id já existente).
            </span>
          </label>

          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: "#7f1d1d",
                             display: "block", marginBottom: 4 }}>
              Digite RESTAURAR para confirmar:
            </label>
            <input type="text"
                   value={restoreConfirmText}
                   data-testid="restore-confirm-input"
                   onChange={(e) => setRestoreConfirmText(e.target.value)}
                   placeholder="RESTAURAR"
                   disabled={restoring}
                   style={{ padding: "8px 12px", fontSize: 13,
                            border: "1px solid #fca5a5",
                            borderRadius: 8, width: 220,
                            fontWeight: 700, letterSpacing: 1 }} />
          </div>

          <button data-testid="restore-submit"
                  onClick={onRestore}
                  disabled={restoring || !restoreFile ||
                            restoreConfirmText !== "RESTAURAR"}
                  style={{
                    background: "#b91c1c",
                    color: "white",
                    border: "none",
                    borderRadius: 10,
                    padding: "10px 20px",
                    fontWeight: 700,
                    fontSize: 13,
                    cursor: "pointer",
                    opacity: (restoring || !restoreFile ||
                             restoreConfirmText !== "RESTAURAR") ? 0.5 : 1,
                    display: "inline-flex", alignItems: "center",
                    gap: 8, width: "fit-content" }}>
            <Upload size={14} />
            {restoring ? "Restaurando… (pode levar minutos)" : "Restaurar MongoDB"}
          </button>
        </div>
      </div>

      <div style={{ ...card, background: "#fef9c3",
                     borderColor: "#fde047",
                     fontSize: 13, color: "#854d0e" }}>
        <strong>Dica:</strong> Para baixar o backup direto na sua VPS via
        SSH, use:
        <pre style={{ background: "rgba(0,0,0,0.05)",
                       padding: 8, borderRadius: 6, marginTop: 6,
                       fontSize: 12, overflow: "auto" }}>
{`# 1) Obtém token (válido 30 dias)
TOKEN=$(curl -s -X POST $BACKEND_URL/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"email":"<seu-email>","password":"<sua-senha>"}' \\
  | jq -r '.access_token')

# 2) Lista backups disponíveis
curl -H "Authorization: Bearer $TOKEN" \\
  $BACKEND_URL/api/admin/backup/list

# 3) Baixa um backup específico
curl -L -H "Authorization: Bearer $TOKEN" \\
  -o backup.tar.gz \\
  $BACKEND_URL/api/admin/backup/download/<filename>`}
        </pre>
      </div>
    </div>
  );
}

function Stat({ label, value, small }) {
  return (
    <div style={{ background: "#f8fafc",
                   border: "1px solid #e2e8f0",
                   borderRadius: 10, padding: 12 }}>
      <div style={{ fontSize: 11, fontWeight: 600,
                     textTransform: "uppercase",
                     color: "#64748b" }}>
        {label}
      </div>
      <div style={{ fontSize: small ? 12 : 22,
                     fontWeight: 700, color: "#0f172a", marginTop: 4,
                     wordBreak: "break-all" }}>
        {value}
      </div>
    </div>
  );
}
