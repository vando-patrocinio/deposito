/**
 * DriveBackupTab — UI de backup/restore via Google Drive.
 *
 * Fluxo:
 *  1. Não conectado → botão "Conectar Google Drive" abre OAuth em popup
 *  2. Conectado → mostra conta + folder + lista de backups + botões
 *  3. Restore → seleciona arquivo do Drive ou histórico + modo (merge/replace)
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card } from "@/ui";
import {
  Cloud, CloudOff, RefreshCw, Download, Upload, Trash2,
  CheckCircle2, AlertTriangle, ExternalLink, Clock,
  HardDrive, Shield, FileJson,
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

  const refresh = useCallback(async () => {
    try {
      const s = await api.driveStatus();
      setStatus(s);
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
      // Limpa query
      window.history.replaceState({}, "", window.location.pathname);
      refresh();
    } else if (qs.get("drive_error")) {
      setError(`OAuth falhou: ${qs.get("drive_error")}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [refresh]);

  async function connect() {
    setBusy("connect");
    setError("");
    try {
      const r = await api.driveConnect();
      // Abre OAuth em nova aba para preservar o estado da app
      window.open(r.authorization_url, "_blank", "width=600,height=700");
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
    return <NotConnected onConnect={connect} busy={busy === "connect"} error={error} />;
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 18 }} data-testid="drive-tab">
      <Card>
        <h3 style={{ margin: "0 0 10px", fontSize: 15, fontWeight: 800, color: "#0f172a", display: "flex", alignItems: "center", gap: 6 }}>
          <Cloud size={16} color="#10b981" /> Google Drive conectado
        </h3>
        <div style={{ padding: 10, background: "#dcfce7", border: "1px solid #86efac", borderRadius: 8, color: "#14532d", fontSize: 12, marginBottom: 12 }} data-testid="drive-connected-banner">
          <strong>{status.user_email || "—"}</strong>
          <div style={{ fontSize: 11, marginTop: 4, opacity: 0.8 }}>
            Conectado em {status.connected_at ? new Date(status.connected_at).toLocaleString("pt-BR") : "—"}
          </div>
        </div>

        {status.folder_url && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>Pasta de backup</div>
            <a href={status.folder_url} target="_blank" rel="noreferrer" style={{ color: "#0d9488", fontSize: 12, fontWeight: 700, display: "inline-flex", alignItems: "center", gap: 4 }}>
              SmartProv-Backups <ExternalLink size={12} />
            </a>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Button onClick={backupNow} disabled={busy === "backup"} data-testid="drive-backup-now">
            {busy === "backup"
              ? <><RefreshCw size={14} className="animate-spin" /> Fazendo backup…</>
              : <><Upload size={14} /> Fazer backup agora</>}
          </Button>
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
    </div>
  );
}

function NotConnected({ onConnect, busy, error }) {
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
