/**
 * DriveBackupTab — UI de backup/restore via Google Drive.
 *
 * Fluxo:
 *  1. Não conectado → botão "Conectar Google Drive" abre OAuth em popup
 *  2. Conectado → mostra conta + folder + lista de backups + botões
 *  3. Restore → seleciona arquivo do Drive ou histórico + modo (merge/replace)
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { Button, Card } from "@/ui";
import {
  Cloud, CloudOff, RefreshCw, Download, Upload, Trash2,
  CheckCircle2, AlertTriangle, ExternalLink, Clock,
  HardDrive, Shield, FileJson, Zap, FileUp,
} from "lucide-react";

const MODES = {
  merge: {
    label: "Mesclar (upsert)",
    desc: "Atualiza/insere docs do snapshot. Preserva dados que não estão no backup.",
    color: "#0d9488",
  },
  replace: {
    label: "Substituir (replace)",
    desc: "APAGA cada coleção da empresa antes de re-importar. Cuidado: irreversível.",
    color: "#dc2626",
  },
};

export default function DriveBackupTab() {
  const [status, setStatus] = useState(null);
  const [backups, setBackups] = useState([]);
  const [remoteFiles, setRemoteFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null); // "backup" | "connect" | "restore" | null
  const [error, setError] = useState("");
  const [restoreModal, setRestoreModal] = useState(null);
  const [snapshotInfo, setSnapshotInfo] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const s = await api.driveStatus();
      setStatus(s);
      // Snapshot info sempre carrega (independe de Drive conectado)
      api.driveSnapshotInfo().then(setSnapshotInfo).catch(() => {});
      if (s.connected) {
        const [bl, rf] = await Promise.all([
          api.driveBackupList().catch(() => ({ items: [] })),
          api.driveRemoteFiles().catch(() => ({ items: [] })),
        ]);
        setBackups(bl.items || []);
        setRemoteFiles(rf.items || []);
      } else {
        setBackups([]);
        setRemoteFiles([]);
      }
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Detecta retorno do callback OAuth via query string
  useEffect(() => {
    const qs = new URLSearchParams(window.location.search);
    if (qs.get("drive_connected") === "1") {
      // Se está dentro de uma popup OAuth → avisa a janela original e fecha
      if (window.opener && !window.opener.closed) {
        try {
          window.opener.postMessage(
            { type: "smartprov:drive_connected", ok: true },
            window.location.origin,
          );
        } catch (e) { /* cross-origin: ignora, fechamento ainda funciona */ }
        // Mensagem visual antes de fechar (caso usuário esteja olhando)
        document.body.innerHTML =
          '<div style="font-family:system-ui;padding:40px;text-align:center;color:#15803d">' +
          '<h2>✓ Google Drive conectado!</h2>' +
          '<p>Pode fechar esta janela. Voltando para o SmartProv...</p></div>';
        setTimeout(() => window.close(), 800);
        return;
      }
      // Caso 2: redirect aconteceu na mesma aba (popup bloqueado) → refresh
      window.history.replaceState({}, "", window.location.pathname);
      refresh();
    } else if (qs.get("drive_error")) {
      if (window.opener && !window.opener.closed) {
        try {
          window.opener.postMessage(
            { type: "smartprov:drive_error", error: qs.get("drive_error") },
            window.location.origin,
          );
        } catch (e) { /* */ }
        setTimeout(() => window.close(), 1200);
        return;
      }
      setError(`OAuth falhou: ${qs.get("drive_error")}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [refresh]);

  // Escuta mensagem da popup OAuth pra dar refresh
  useEffect(() => {
    function onMsg(ev) {
      if (ev.origin !== window.location.origin) return;
      if (ev.data?.type === "smartprov:drive_connected") {
        refresh();
      } else if (ev.data?.type === "smartprov:drive_error") {
        setError(`OAuth falhou: ${ev.data.error}`);
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [refresh]);

  async function connect() {
    setBusy("connect");
    setError("");
    try {
      const r = await api.driveConnect();
      const popup = window.open(
        r.authorization_url, "smartprov_oauth_drive",
        "width=600,height=700,scrollbars=yes,resizable=yes",
      );
      // Detecta popup bloqueada: fallback pra redirect na mesma aba
      if (!popup || popup.closed || typeof popup.closed === "undefined") {
        if (window.confirm(
          "Seu navegador bloqueou a janela popup do Google.\n\n" +
          "Quer abrir o OAuth NESTA aba (você volta automaticamente após autorizar)?",
        )) {
          window.location.href = r.authorization_url;
        }
      }
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    if (!await window.confirm("Desconectar Google Drive? Os arquivos não serão apagados, mas backups param de rodar.")) return;
    try {
      await api.driveDisconnect();
      refresh();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  }

  async function backupLocal() {
    setBusy("backup_local");
    setError("");
    try {
      // Detecta se a página está rodando em iframe (preview do Emergent).
      // Em iframe cross-origin, o showSaveFilePicker é BLOQUEADO pelo Chrome
      // por segurança. Detectamos isso pra cair direto no fallback.
      const inIframe = window.self !== window.top;
      const canPickFile = !inIframe
        && typeof window.showSaveFilePicker === "function";

      // Estratégia 1 (top-level Chrome/Edge): "Salvar como…" nativo.
      if (canPickFile) {
        console.log("[backup-local] usando File System Access API");
        const suggested = `smartprov-backup-${new Date().toISOString()
          .replace(/[-:T]/g, "").slice(0, 14)}.zip`;
        let handle;
        try {
          handle = await window.showSaveFilePicker({
            suggestedName: suggested,
            types: [{
              description: "Backup SmartProv (.zip)",
              accept: { "application/zip": [".zip"] },
            }],
          });
        } catch (e) {
          if (e.name === "AbortError") {
            console.log("[backup-local] cancelado pelo usuário"); return;
          }
          throw e;
        }
        const r = await api.driveBackupLocal(false, true);
        if (!r?.blob || r.blob.size === 0) {
          throw new Error("Servidor retornou backup vazio.");
        }
        const writable = await handle.createWritable();
        await writable.write(r.blob);
        await writable.close();
        const mb = (r.blob.size / 1024 / 1024).toFixed(2);
        console.log(`[backup-local] salvo (${mb} MB)`);
        return;
      }

      // Estratégia 2: link direto + ?t= (funciona em iframe e em qualquer
      // navegador). O Chrome usa a configuração default de Downloads —
      // se o usuário quer ESCOLHER a pasta, precisa ligar:
      //   chrome://settings/downloads → "Ask where to save…"
      console.log(inIframe
        ? "[backup-local] dentro de iframe — usando link direto"
        : "[backup-local] navegador sem File System API — usando link direto");
      const url = api.driveBackupLocalUrl(false, true);
      const a = document.createElement("a");
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.style.position = "fixed";
      a.style.top = "-9999px";
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        try { document.body.removeChild(a); } catch { /* ignore */ }
      }, 2000);

      // Mensagem informativa pro usuário que está em iframe
      if (inIframe) {
        setError(
          "ℹ️ Download iniciado para a pasta Downloads padrão do navegador. "
          + "Para ESCOLHER onde salvar, ative no Chrome: Configurações → "
          + "Downloads → \"Perguntar onde salvar cada arquivo antes de baixar\". "
          + "Ou abra o SmartProv numa aba dedicada (fora do preview)."
        );
      }
    } catch (e) {
      console.error("[backup-local] falha:", e);
      let msg = e.message || "Falha ao iniciar download.";
      const data = e?.response?.data;
      if (data instanceof Blob) {
        try {
          const txt = await data.text();
          try {
            const obj = JSON.parse(txt);
            msg = obj.detail || obj.message || txt.slice(0, 300);
          } catch { msg = txt.slice(0, 300); }
        } catch { msg = `Erro HTTP ${e?.response?.status || "?"}`; }
      }
      setError(msg);
    } finally {
      setBusy(null);
    }
  }

  // Fallback: abre o ZIP em nova aba (navegador trata como navegação normal
  // — não é bloqueado por extensões/políticas anti-download programático).
  function backupLocalOpenInTab() {
    const url = api.driveBackupLocalUrl(false, true);
    console.log("[backup-local] abrindo em nova aba:", url.replace(/t=[^&]+/, "t=***"));
    const win = window.open(url, "_blank", "noopener,noreferrer");
    if (!win) {
      setError(
        "Popup bloqueado pelo navegador. Permita popups deste site nas configurações " +
        "do Chrome (ícone na barra de endereço) ou tente em aba anônima."
      );
    }
  }

  async function backupNow() {
    setBusy("backup");
    setError("");
    try {
      const r = await api.driveBackupNow(false);
      // Refresh imediato pra mostrar o novo
      await refresh();
      await window.alert(`Backup criado: ${r.file_name} (${(r.size_bytes / 1024).toFixed(1)} KB)`);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(null);
    }
  }

  async function doRestore(mode) {
    if (!restoreModal) return;
    if (mode === "replace") {
      const sure = await window.prompt(
        `Modo REPLACE apaga todos os dados das coleções antes de restaurar. ` +
        `Digite "RESTAURAR" para confirmar.`
      );
      if (sure !== "RESTAURAR") return;
    }
    setBusy("restore");
    setError("");
    try {
      const r = await api.driveRestore(restoreModal.id, mode);
      const total = Object.values(r.restored || {}).reduce((a, b) => a + b, 0);
      await window.alert(`Restaurado: ${total} documentos em ${Object.keys(r.restored).length} coleções.${r.secrets_redacted_in_source ? "\n\nObs: secrets ficaram preservados (estavam mascarados no snapshot)." : ""}`);
      setRestoreModal(null);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <div style={{ padding: 16, color: "#64748b" }}>Carregando…</div>;

  if (!status?.connected) {
    return (
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <NotConnected onConnect={connect} busy={busy === "connect"} error={error}
                       onBackupLocal={backupLocal} busyLocal={busy === "backup_local"} />
        <BootstrapCard onRestored={refresh} />
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 18 }} data-testid="drive-tab">
      <Card>
        <h3 style={{ margin: "0 0 10px", fontSize: 15, fontWeight: 800, color: "#0f172a", display: "flex", alignItems: "center", gap: 6 }}>
          <Cloud size={16} color={status.needs_reconnect ? "#dc2626" : "#10b981"} />
          {status.needs_reconnect ? "Google Drive — Reconexão necessária" : "Google Drive conectado"}
        </h3>
        {status.needs_reconnect ? (
          <div style={{ padding: 12, background: "#fef3c7", border: "1px solid #fcd34d", borderRadius: 8, color: "#78350f", fontSize: 12, marginBottom: 12 }} data-testid="drive-needs-reconnect-banner">
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, marginBottom: 6 }}>
              <AlertTriangle size={14} /> Token do Google expirou ou foi revogado
            </div>
            <div style={{ lineHeight: 1.55, marginBottom: 10 }}>
              Os backups automáticos pararam de funcionar. Conta anterior: <strong>{status.user_email || "—"}</strong>.
              Clique abaixo para reautorizar (você pode usar a mesma conta Google).
            </div>
            <Button onClick={connect} disabled={busy === "connect"} data-testid="drive-reconnect-btn"
                    style={{ background: "#0d9488" }}>
              {busy === "connect"
                ? <><RefreshCw size={14} className="animate-spin" /> Abrindo…</>
                : <><Cloud size={14} /> Reconectar Google Drive</>}
            </Button>
            {status.last_error && (
              <details style={{ marginTop: 8, fontSize: 11, opacity: 0.75 }}>
                <summary style={{ cursor: "pointer" }}>Detalhes do erro</summary>
                <code style={{ display: "block", marginTop: 4, fontSize: 10 }}>{status.last_error}</code>
              </details>
            )}
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px dashed #fcd34d" }}>
              <div style={{ fontSize: 11, marginBottom: 6 }}>
                Enquanto isso, você pode baixar um backup completo localmente (não depende do Drive):
              </div>
              <Button onClick={backupLocal} disabled={busy === "backup_local"}
                       data-testid="drive-backup-local-revoked"
                       style={{ background: "#f59e0b", width: "100%" }}>
                {busy === "backup_local"
                  ? <><RefreshCw size={14} className="animate-spin" /> Gerando ZIP…</>
                  : <><Download size={14} /> Baixar backup local (.zip)</>}
              </Button>
            </div>
          </div>
        ) : (
          <div style={{ padding: 10, background: "#dcfce7", border: "1px solid #86efac", borderRadius: 8, color: "#14532d", fontSize: 12, marginBottom: 12 }} data-testid="drive-connected-banner">
            <strong>{status.user_email || "—"}</strong>
            <div style={{ fontSize: 11, marginTop: 4, opacity: 0.8 }}>
              Conectado em {status.connected_at ? new Date(status.connected_at).toLocaleString("pt-BR") : "—"}
            </div>
          </div>
        )}

        {status.folder_url && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>Pasta de backup</div>
            <a href={status.folder_url} target="_blank" rel="noreferrer" style={{ color: "#0d9488", fontSize: 12, fontWeight: 700, display: "inline-flex", alignItems: "center", gap: 4 }}>
              SmartProv-Backups <ExternalLink size={12} />
            </a>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Button onClick={backupNow}
                  disabled={busy === "backup" || status.needs_reconnect}
                  data-testid="drive-backup-now">
            {busy === "backup"
              ? <><RefreshCw size={14} className="animate-spin" /> Fazendo backup…</>
              : <><Upload size={14} /> Fazer backup agora (Drive)</>}
          </Button>
          <Button onClick={backupLocal}
                  disabled={busy === "backup_local"}
                  data-testid="drive-backup-local"
                  style={{ background: "#f59e0b" }}>
            {busy === "backup_local"
              ? <><RefreshCw size={14} className="animate-spin" /> Gerando ZIP…</>
              : <><Download size={14} /> Baixar para meu computador (.zip)</>}
          </Button>
          <DirectDownloadLink />
          <Button variant="ghost" onClick={refresh} disabled={busy}>
            <RefreshCw size={14} /> Atualizar lista
          </Button>
          <Button variant="ghost" onClick={disconnect} data-testid="drive-disconnect"
                  style={{ color: "#dc2626" }}>
            <CloudOff size={14} /> Desconectar
          </Button>
        </div>

        <div style={{ marginTop: 14, padding: 10, background: "#f1f5f9", borderRadius: 8, fontSize: 11, color: "#475569", lineHeight: 1.55 }}>
          <Shield size={11} style={{ display: "inline", marginRight: 4 }} />
          Backup automático todo dia às <strong>3h (BRT)</strong>. Snapshot inclui: settings, branding, planos, assinantes, técnicos, agentes IA, configurações de integração (com secrets mascarados), <strong>sessão WhatsApp (Baileys)</strong> e mais.
        </div>

        {snapshotInfo && (
          <details data-testid="drive-snapshot-info"
            style={{ marginTop: 8, padding: 10, background: "#f8fafc",
                      border: "1px solid #e2e8f0", borderRadius: 8,
                      fontSize: 11, color: "#475569" }}>
            <summary style={{ cursor: "pointer", fontWeight: 700, color: "#0f172a" }}>
              📊 Próximo snapshot — <strong>{snapshotInfo.collections_included}</strong> coleções
              · <strong>{snapshotInfo.total_docs.toLocaleString("pt-BR")}</strong> documentos
              {snapshotInfo.filesystem_assets?.total_files > 0 && (
                <> · <strong>{snapshotInfo.filesystem_assets.total_files}</strong> arquivos
                ({snapshotInfo.filesystem_assets.total_size_mb} MB)</>
              )}
            </summary>
            {/* Box de arquivos físicos */}
            {snapshotInfo.filesystem_assets && (
              <div style={{ marginTop: 8, padding: 8,
                              background: "#eff6ff",
                              border: "1px solid #bfdbfe", borderRadius: 6 }}>
                <div style={{ fontWeight: 700, fontSize: 11, color: "#1e40af",
                                marginBottom: 4 }}>
                  📎 Arquivos físicos no tarball (salvos no Drive como .files.tar.gz)
                </div>
                <table style={{ width: "100%", fontSize: 11,
                                  fontFamily: "JetBrains Mono, monospace",
                                  borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ background: "#dbeafe", textAlign: "left" }}>
                      <th style={{ padding: "3px 5px" }}>pasta</th>
                      <th style={{ padding: "3px 5px", textAlign: "right" }}>arquivos</th>
                      <th style={{ padding: "3px 5px", textAlign: "right" }}>tamanho</th>
                      <th style={{ padding: "3px 5px", textAlign: "center" }}>incluso?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshotInfo.filesystem_assets.paths.map((p) => (
                      <tr key={p.disk_path} style={{ borderTop: "1px solid #dbeafe" }}>
                        <td style={{ padding: "2px 5px" }}>{p.tar_name}</td>
                        <td style={{ padding: "2px 5px", textAlign: "right", fontWeight: 600 }}>
                          {p.files}
                        </td>
                        <td style={{ padding: "2px 5px", textAlign: "right" }}>
                          {p.size_kb} KB
                        </td>
                        <td style={{ padding: "2px 5px", textAlign: "center",
                                       color: p.will_be_included ? "#16a34a" : "#94a3b8" }}>
                          {p.will_be_included ? "✓" : "⊘ opcional"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div style={{ marginTop: 8, maxHeight: 200, overflowY: "auto" }}>
              <div style={{ fontWeight: 700, fontSize: 11, color: "#0f172a", marginBottom: 4 }}>
                💾 Coleções MongoDB
              </div>
              <table style={{ width: "100%", fontSize: 11,
                                fontFamily: "JetBrains Mono, monospace",
                                borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ background: "#e2e8f0", textAlign: "left" }}>
                    <th style={{ padding: "4px 6px" }}>coleção</th>
                    <th style={{ padding: "4px 6px", textAlign: "right" }}>docs</th>
                    <th style={{ padding: "4px 6px", textAlign: "center" }}>secret</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshotInfo.breakdown.map((r) => (
                    <tr key={r.collection} style={{ borderTop: "1px solid #f1f5f9" }}>
                      <td style={{ padding: "3px 6px" }}>{r.collection}</td>
                      <td style={{ padding: "3px 6px", textAlign: "right",
                                    fontWeight: 600 }}>
                        {r.docs.toLocaleString("pt-BR")}
                      </td>
                      <td style={{ padding: "3px 6px", textAlign: "center",
                                    color: r.masked_when_no_secrets ? "#dc2626" : "#cbd5e1" }}>
                        {r.masked_when_no_secrets ? "🔒" : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ marginTop: 8, padding: 6,
                              background: "#fef3c7", borderRadius: 4,
                              fontSize: 10, color: "#92400e" }}>
                <strong>{snapshotInfo.excluded_collections?.length || 0} coleções excluídas</strong> deliberadamente
                (logs grandes recicláveis: atlaz_sync_logs, subscriber_match_log,
                motor_ia_usage, push_alerts_log, notifications, drive_backups…).
                Não impactam restore — são regeneradas pela operação normal.
              </div>
            </div>
          </details>
        )}

        <div style={{ marginTop: 8, padding: 10, background: "#ecfeff", border: "1px solid #67e8f9", borderRadius: 8, fontSize: 11, color: "#0e7490", lineHeight: 1.55 }} data-testid="drive-wa-session-info">
          <strong>🟢 Inclui sessão WhatsApp:</strong> a coleção <code>wa_auth_state</code>{" "}
          (creds + keys Signal protocol) entra em cada snapshot. Se o Mongo
          travar, você restaura aqui e o Baileys reconecta automaticamente
          sem precisar escanear QR Code de novo.
        </div>

        {error && (
          <div style={{ marginTop: 10, padding: 10, background: "#fef2f2", border: "1px solid #fecaca", color: "#991b1b", borderRadius: 8, fontSize: 12 }} data-testid="drive-error">
            <AlertTriangle size={12} style={{ display: "inline", marginRight: 4 }} /> {error}
          </div>
        )}
      </Card>

      <Card>
        <h3 style={{ margin: "0 0 10px", fontSize: 15, fontWeight: 800, color: "#0f172a", display: "flex", alignItems: "center", gap: 6 }}>
          <HardDrive size={16} /> Backups disponíveis
        </h3>
        <BackupList items={remoteFiles}
                     onRestore={(f) => setRestoreModal(f)}
                     localItems={backups} />
      </Card>

      {restoreModal && (
        <RestoreModal file={restoreModal} onClose={() => setRestoreModal(null)}
                       onConfirm={doRestore} busy={busy === "restore"} />
      )}

      <div style={{ gridColumn: "1 / -1" }}>
        <BootstrapCard onRestored={refresh} />
      </div>
    </div>
  );
}

function NotConnected({ onConnect, busy, error, onBackupLocal, busyLocal }) {
  return (
    <Card data-testid="drive-not-connected">
      <div style={{ textAlign: "center", padding: "20px 12px", maxWidth: 500, margin: "0 auto" }}>
        <CloudOff size={42} color="#94a3b8" style={{ margin: "0 auto 12px" }} />
        <h3 style={{ margin: "0 0 6px", fontSize: 17, color: "#0f172a", fontWeight: 800 }}>
          Backup no Google Drive
        </h3>
        <p style={{ fontSize: 13, color: "#475569", margin: "0 0 16px", lineHeight: 1.55 }}>
          Conecte sua conta Google para que a Secretária Ligo faça backup diário automático das configurações do sistema. Em caso de problema, basta reinstalar e apontar para essa pasta para recriar o sistema com tudo no lugar.
        </p>
        <Button onClick={onConnect} disabled={busy} data-testid="drive-connect-btn">
          {busy ? <><RefreshCw size={14} className="animate-spin" /> Abrindo…</> : <><Cloud size={14} /> Conectar Google Drive</>}
        </Button>
        <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 14, lineHeight: 1.5 }}>
          Abrirá uma janela do Google para autorização. Acesso solicitado: somente arquivos criados por este app (escopo <code>drive.file</code>).
        </div>
        {onBackupLocal && (
          <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px dashed #e2e8f0" }}>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 8 }}>
              Ou baixe um backup completo direto pro seu computador, sem precisar do Google Drive:
            </div>
            <Button onClick={onBackupLocal} disabled={busyLocal}
                     data-testid="drive-backup-local-nc"
                     style={{ background: "#f59e0b" }}>
              {busyLocal
                ? <><RefreshCw size={14} className="animate-spin" /> Gerando ZIP…</>
                : <><Download size={14} /> Baixar backup local (.zip)</>}
            </Button>
          </div>
        )}
        {error && (
          <div style={{ marginTop: 16, padding: 10, background: "#fef2f2", border: "1px solid #fecaca", color: "#991b1b", borderRadius: 8, fontSize: 12 }}>
            <AlertTriangle size={12} style={{ display: "inline", marginRight: 4 }} /> {error}
          </div>
        )}
      </div>
    </Card>
  );
}

function BackupList({ items, localItems, onRestore }) {
  if (!items.length) return <div style={{ padding: 16, color: "#94a3b8", textAlign: "center", fontSize: 13 }}>Nenhum backup ainda. Clique "Fazer backup agora".</div>;
  const localByFile = Object.fromEntries((localItems || []).map((b) => [b.file_id, b]));
  return (
    <div style={{ maxHeight: 460, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
      {items.map((f) => {
        const local = localByFile[f.id];
        const sizeKb = (Number(f.size) || local?.size_bytes || 0) / 1024;
        return (
          <div key={f.id} data-testid={`drive-backup-${f.id}`}
               style={{ padding: 10, border: "1px solid #e2e8f0", borderRadius: 8, display: "flex", alignItems: "center", gap: 10 }}>
            <FileJson size={20} color="#0d9488" style={{ flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, fontSize: 12, color: "#0f172a", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                {f.name}
              </div>
              <div style={{ fontSize: 10, color: "#64748b", display: "flex", gap: 8 }}>
                <span><Clock size={9} style={{ display: "inline", marginRight: 2 }} />
                  {f.createdTime ? new Date(f.createdTime).toLocaleString("pt-BR") : "—"}</span>
                {sizeKb > 0 && <span>{sizeKb.toFixed(1)} KB</span>}
                {local?.triggered_by && <span>· {local.triggered_by}</span>}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {f.webViewLink && (
                <a href={f.webViewLink} target="_blank" rel="noreferrer"
                   style={{ display: "grid", placeItems: "center", padding: 6, border: "1px solid #e2e8f0", borderRadius: 6, color: "#475569" }}
                   title="Abrir no Drive">
                  <ExternalLink size={12} />
                </a>
              )}
              <button onClick={() => onRestore(f)}
                      style={{ background: "transparent", border: "1px solid #e2e8f0", borderRadius: 6, padding: "4px 10px", fontSize: 11, fontWeight: 700, cursor: "pointer", color: "#475569", display: "flex", alignItems: "center", gap: 4 }}
                      data-testid={`drive-restore-btn-${f.id}`}>
                <Download size={11} /> Restaurar
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RestoreModal({ file, onClose, onConfirm, busy }) {
  const [mode, setMode] = useState("merge");
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)", zIndex: 200, display: "grid", placeItems: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="drive-restore-modal"
           style={{ background: "white", borderRadius: 14, padding: 22, maxWidth: 480, width: "100%" }}>
        <h3 style={{ margin: "0 0 6px", fontSize: 16, color: "#0f172a", fontWeight: 800 }}>Restaurar backup</h3>
        <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 12px" }}>
          Arquivo: <strong>{file.name}</strong>
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {Object.entries(MODES).map(([k, v]) => (
            <label key={k} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: 12, border: `1px solid ${mode === k ? v.color : "#e2e8f0"}`, borderRadius: 10, cursor: "pointer", background: mode === k ? `${v.color}11` : "white" }}>
              <input type="radio" checked={mode === k} onChange={() => setMode(k)} style={{ marginTop: 4 }} data-testid={`drive-restore-mode-${k}`} />
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: v.color }}>{v.label}</div>
                <div style={{ fontSize: 11, color: "#475569", marginTop: 2, lineHeight: 1.5 }}>{v.desc}</div>
              </div>
            </label>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onClose}>Cancelar</Button>
          <Button onClick={() => onConfirm(mode)} disabled={busy} data-testid="drive-restore-confirm">
            {busy ? "Restaurando…" : <><Download size={13} /> Confirmar restauração</>}
          </Button>
        </div>
      </div>
    </div>
  );
}


// ===================================================================
// BootstrapCard — Provisionamento 1-clique para servidor novo
// ===================================================================
function BootstrapCard({ onRestored }) {
  const fileInputRef = useRef(null);
  const tarInputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [tarFile, setTarFile] = useState(null);
  const [mode, setMode] = useState("replace");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  function pickFile(e) {
    setError("");
    setResult(null);
    const f = e.target.files?.[0];
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".json")) {
      setError("Arquivo deve ser .json (backup do SmartProv).");
      return;
    }
    if (f.size > 50 * 1024 * 1024) {
      setError(`Arquivo muito grande (${(f.size/1024/1024).toFixed(1)} MB). Limite: 50 MB.`);
      return;
    }
    setFile(f);
  }

  function pickTar(e) {
    setError("");
    const f = e.target.files?.[0];
    if (!f) return;
    if (!/\.(tar\.gz|tgz)$/i.test(f.name)) {
      setError("Tarball deve ser .tar.gz ou .tgz");
      return;
    }
    if (f.size > 200 * 1024 * 1024) {
      setError(`Tarball muito grande (${(f.size/1024/1024).toFixed(1)} MB). Limite: 200 MB.`);
      return;
    }
    setTarFile(f);
  }

  async function doRestore() {
    if (!file) return;
    if (mode === "replace") {
      const confirm = window.prompt(
        `MODO REPLACE apaga TODAS as coleções da empresa antes de restaurar. ` +
        `Use apenas em servidor NOVO (vazio).\n\nDigite "RESTAURAR" para confirmar.`,
      );
      if (confirm !== "RESTAURAR") return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    setProgress(0);
    try {
      const r = await api.driveRestoreUpload(file, mode, (e) => {
        if (e.total) setProgress(Math.round((e.loaded / e.total) * 100));
      }, tarFile);
      setResult(r);
      onRestored?.();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card data-testid="drive-bootstrap-card"
          style={{ borderLeft: "4px solid #f59e0b" }}>
      <h3 style={{ margin: "0 0 6px", fontSize: 15, fontWeight: 800, color: "#0f172a",
                    display: "flex", alignItems: "center", gap: 6 }}>
        <Zap size={16} color="#f59e0b" /> Provisionamento 1-clique
      </h3>
      <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 14px", lineHeight: 1.55 }}>
        Subindo um servidor novo? Faça upload do <strong>último backup .json</strong> que você
        baixou do Drive (ou tem em mãos) e o sistema é restaurado em segundos —
        sem precisar conectar Google Drive primeiro.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        {/* Upload */}
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b",
                          textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>
            1. Selecionar arquivo
          </div>
          <input type="file" accept=".json,application/json"
                 ref={fileInputRef} onChange={pickFile}
                 data-testid="bootstrap-file-input"
                 style={{ display: "none" }} />
          <button onClick={() => fileInputRef.current?.click()} disabled={busy}
                  data-testid="bootstrap-pick-file"
                  style={{ width: "100%", padding: "10px 14px",
                           border: "2px dashed #cbd5e1", borderRadius: 8,
                           background: "#f8fafc", color: "#475569",
                           cursor: busy ? "not-allowed" : "pointer",
                           display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                           fontSize: 12, fontWeight: 600 }}>
            <FileUp size={14} /> {file ? file.name : "Escolher .json"}
          </button>
          {file && (
            <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4,
                            fontFamily: "JetBrains Mono, monospace" }}>
              {(file.size / 1024).toFixed(1)} KB
            </div>
          )}
          {/* Optional tarball */}
          <div style={{ marginTop: 8 }}>
            <input type="file" accept=".tar.gz,.tgz,application/gzip"
                   ref={tarInputRef} onChange={pickTar}
                   data-testid="bootstrap-tar-input"
                   style={{ display: "none" }} />
            <button onClick={() => tarInputRef.current?.click()} disabled={busy}
                    data-testid="bootstrap-pick-tar"
                    style={{ width: "100%", padding: "6px 10px",
                             border: "1px dashed #cbd5e1", borderRadius: 6,
                             background: tarFile ? "#fef3c7" : "transparent",
                             color: tarFile ? "#92400e" : "#94a3b8",
                             cursor: busy ? "not-allowed" : "pointer",
                             fontSize: 11, fontWeight: 600 }}>
              📎 {tarFile ? tarFile.name : "Anexar .files.tar.gz (opcional)"}
            </button>
            {tarFile && (
              <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 3,
                              fontFamily: "JetBrains Mono, monospace" }}>
                {(tarFile.size / 1024 / 1024).toFixed(2)} MB · restaurará imagens/PDFs
              </div>
            )}
            {!tarFile && (
              <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 3,
                              lineHeight: 1.45 }}>
                Sem o .tar.gz, fotos do onboarding/holerites/imagens WhatsApp não voltam.
              </div>
            )}
          </div>
        </div>

        {/* Modo */}
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b",
                          textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>
            2. Modo de restauração
          </div>
          <select value={mode} onChange={(e) => setMode(e.target.value)}
                  disabled={busy} data-testid="bootstrap-mode"
                  style={{ width: "100%", padding: "10px 12px",
                           border: "1px solid #cbd5e1", borderRadius: 8,
                           fontSize: 12, background: "white" }}>
            <option value="replace">Replace — servidor NOVO (apaga e recria)</option>
            <option value="merge">Merge — adicionar/atualizar</option>
          </select>
          <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4, lineHeight: 1.45 }}>
            {mode === "replace"
              ? "⚠️ Use só em servidor vazio. Apaga collections antes."
              : "✓ Seguro: faz upsert por id, não apaga nada."}
          </div>
        </div>
      </div>

      <Button onClick={doRestore} disabled={!file || busy}
              data-testid="bootstrap-restore-btn"
              style={{ width: "100%", background: file ? "#f59e0b" : "#cbd5e1",
                       padding: "12px 18px", fontSize: 13, fontWeight: 700 }}>
        {busy ? (
          progress > 0 && progress < 100
            ? <><RefreshCw size={14} className="animate-spin" /> Enviando… {progress}%</>
            : <><RefreshCw size={14} className="animate-spin" /> Restaurando coleções…</>
        ) : (
          <><Zap size={14} /> Restaurar tudo (1 clique)</>
        )}
      </Button>

      {result && (
        <div data-testid="bootstrap-result" style={{ marginTop: 12, padding: 12,
              background: "#ecfdf5", border: "1px solid #6ee7b7", borderRadius: 8,
              fontSize: 12, color: "#065f46" }}>
          <div style={{ fontWeight: 700, marginBottom: 6, display: "flex",
                          alignItems: "center", gap: 6 }}>
            <CheckCircle2 size={14} /> Restauração concluída
          </div>
          <div style={{ marginBottom: 6 }}>
            <strong>{Object.values(result.restored || {}).reduce((a,b)=>a+b, 0)}</strong> documentos
            em <strong>{Object.keys(result.restored || {}).length}</strong> coleções
            {result.files_extracted && (
              <> · <strong>{result.files_extracted.extracted || 0}</strong> arquivos físicos</>
            )}
          </div>
          <details style={{ marginTop: 4 }}>
            <summary style={{ cursor: "pointer", fontSize: 11 }}>Ver detalhe por coleção</summary>
            <div style={{ marginTop: 6, fontSize: 11,
                            fontFamily: "JetBrains Mono, monospace",
                            maxHeight: 180, overflowY: "auto" }}>
              {Object.entries(result.restored || {}).map(([k, v]) => (
                <div key={k}>{k}: <strong>{v}</strong></div>
              ))}
            </div>
          </details>
          <div style={{ marginTop: 8, fontSize: 11, padding: 8,
                          background: "#fffbeb", border: "1px solid #fde68a",
                          borderRadius: 6, color: "#92400e", lineHeight: 1.5 }}>
            <strong>📋 Próximos passos:</strong>
            <ol style={{ margin: "4px 0 0 16px", padding: 0 }}>
              <li>Reinicie o backend para recarregar configs em memória (cache de planos/agentes IA).</li>
              <li>Conecte o Google Drive nesta instância para retomar backups diários.</li>
              <li>Se tinha sessão WhatsApp ativa, o Baileys reconecta sozinho em até 30s.</li>
            </ol>
          </div>
        </div>
      )}

      {error && (
        <div style={{ marginTop: 10, padding: 10, background: "#fef2f2",
                       border: "1px solid #fecaca", color: "#991b1b",
                       borderRadius: 8, fontSize: 12 }}
             data-testid="bootstrap-error">
          <AlertTriangle size={12} style={{ display: "inline", marginRight: 4 }} /> {error}
        </div>
      )}

      <div style={{ marginTop: 12, fontSize: 10, color: "#94a3b8", lineHeight: 1.5 }}>
        Backup gerado pelo SmartProv contém: settings, branding, planos, assinantes,
        técnicos, agentes IA, integrações (secrets mascarados se include_secrets=false),
        sessão WhatsApp (Baileys). Limite de upload: 50 MB.
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// DirectDownloadLink — gera URL assinada (?t=token) pro download direto
// fora do iframe. Útil pra contornar restrições cross-origin do Chrome.
// ---------------------------------------------------------------------------
function DirectDownloadLink() {
  const [show, setShow] = useState(false);
  const [copied, setCopied] = useState(false);
  const url = api.driveBackupLocalUrl(false, true);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      window.prompt("Copie o link manualmente:", url);
    }
  };

  if (!show) {
    return (
      <button
        type="button"
        onClick={() => setShow(true)}
        data-testid="drive-show-direct-link"
        style={{
          fontSize: 11, color: "#0369a1", background: "transparent",
          border: "1px dashed #cbd5e1", borderRadius: 6,
          padding: "8px 10px", cursor: "pointer", textAlign: "left",
        }}>
        🔗 Gerar link direto (pra abrir fora do preview e escolher "Salvar como…")
      </button>
    );
  }

  return (
    <div data-testid="drive-direct-link-card"
         style={{ padding: 12, background: "#eff6ff",
                   border: "1px solid #bfdbfe", borderRadius: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: "#1e3a8a",
                     marginBottom: 6 }}>
        🔗 Link direto pro backup
      </div>
      <div style={{ fontSize: 11, color: "#1e40af", marginBottom: 8,
                     lineHeight: 1.5 }}>
        Esse link contém um token de acesso. Cole numa <b>aba normal do Chrome
        (fora do preview do Emergent)</b> pra que o "Salvar como…" do
        navegador funcione e você escolha onde guardar.
      </div>
      <textarea
        readOnly
        value={url}
        onClick={(e) => e.target.select()}
        data-testid="drive-direct-link-input"
        style={{
          width: "100%", minHeight: 70, padding: 8, fontSize: 10,
          fontFamily: "JetBrains Mono, monospace",
          background: "#fff", border: "1px solid #93c5fd",
          borderRadius: 6, color: "#1e3a8a", resize: "vertical",
          wordBreak: "break-all",
        }}
      />
      <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
        <Button onClick={copy} data-testid="drive-direct-link-copy"
                style={{ fontSize: 11, padding: "6px 10px" }}>
          {copied ? "✓ Copiado!" : "📋 Copiar link"}
        </Button>
        <Button onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
                data-testid="drive-direct-link-open"
                variant="ghost"
                style={{ fontSize: 11, padding: "6px 10px" }}>
          ↗ Abrir em nova aba
        </Button>
        <Button onClick={() => setShow(false)}
                variant="ghost"
                style={{ fontSize: 11, padding: "6px 10px",
                         color: "#64748b", marginLeft: "auto" }}>
          Ocultar
        </Button>
      </div>
      <div style={{ marginTop: 8, padding: 8, background: "#fef9c3",
                     border: "1px solid #fde047", borderRadius: 6,
                     fontSize: 10, color: "#713f12", lineHeight: 1.5 }}>
        ⚠️ <b>Importante:</b> esse link inclui seu token de autenticação.
        Não compartilhe nem mande pra outra pessoa. Validade: até seu próximo
        logout (mantém vivo enquanto você estiver logado no SmartProv).
      </div>
    </div>
  );
}
