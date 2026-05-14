import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import SelfieCamera from "@/SelfieCamera";
import LousaMobile from "@/LousaMobile";
import MyAssetsModal from "@/MyAssetsModal";
import ServerClock from "@/ServerClock";
import { serverNow } from "@/serverTime";
import { AvatarZoomModal, Button, Card, fmtMin, Icon, inputStyle, PhoneFrame, Row, StatusBadge } from "@/ui";
import { enqueue as enqueueOffline, count as offlineCount, flush as flushOffline } from "@/offlineClockQueue";

const EVENT_TYPES = ["Entrada", "Início intervalo", "Fim intervalo", "Saída"];
const GEOFENCE_REQUIRED = new Set(["Entrada", "Saída"]);

function formatDur(min) {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h}h${String(m).padStart(2, "0")}` : `${m}min`;
}
function formatGap(min) {
  if (min == null) return "—";
  if (min < 60) return `${Math.round(min)}min`;
  return formatDur(min);
}

export default function CollaboratorApp({ mobile = false, forcedCollabId = null, onLogout = null }) {
  return <CollaboratorAppInner mobile={mobile} forcedCollabId={forcedCollabId} onLogout={onLogout} />;
}

function CollaboratorAppInner({ mobile = false, forcedCollabId = null, onLogout = null }) {
  const [collabs, setCollabs] = useState([]);
  const [collabId, setCollabId] = useState(forcedCollabId);
  const [today, setToday] = useState(null);
  const [fences, setFences] = useState([]);
  const [screen, setScreen] = useState("home");
  const [eventType, setEventType] = useState("Entrada");
  const [receipt, setReceipt] = useState(null);
  const [position, setPosition] = useState(null);
  const [geoError, setGeoError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [avatarZoom, setAvatarZoom] = useState(false);
  const [pracas, setPracas] = useState([]);
  const [cameraKey, setCameraKey] = useState(0);
  const [forceCloseOpen, setForceCloseOpen] = useState(false);
  const [exitConfirm, setExitConfirm] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFlash, setRefreshFlash] = useState(false);
  const [lousaSummary, setLousaSummary] = useState(null);  // {last_closed_at, minutes_since_last_close, last_finished_ticket}
  const [pendingCount, setPendingCount] = useState(() => offlineCount());  // batidas offline aguardando reenvio
  const [flushingOffline, setFlushingOffline] = useState(false);
  const [showMyAssets, setShowMyAssets] = useState(false);

  // Worker que tenta reenviar a fila offline. Chamado quando: (a) GPS muda, (b) volta online.
  const flushPending = useCallback(async () => {
    if (offlineCount() === 0) return;
    setFlushingOffline(true);
    try {
      await flushOffline(async (item) => {
        // Reenvio precisa de GPS — se ainda indisponível, falha cedo (queue mantém)
        if (item.lat == null || item.lng == null) {
          if (position?.lat == null || position?.lng == null) {
            throw new Error("GPS ainda indisponível");
          }
          item = { ...item, lat: position.lat, lng: position.lng };
        }
        await api.createClockRecord({
          collaborator_id: item.collaborator_id,
          type: item.type,
          selfie_base64: item.selfie_base64,
          lat: item.lat,
          lng: item.lng,
          offline_created_at: item.captured_at,
          public_ip: null,
          client_time_ms: serverNow(),
        });
      });
    } catch (e) {
      console.warn("[offline-clock] flush erro:", e);
    }
    setPendingCount(offlineCount());
    setFlushingOffline(false);
    // refresh será disparado naturalmente pelos próximos polls/useEffect dos dados.
  }, [position?.lat, position?.lng]);

  // Dispara flush quando GPS fica disponível
  useEffect(() => {
    if (position?.lat != null && position?.lng != null && pendingCount > 0) {
      flushPending();
    }
  }, [position?.lat, position?.lng, pendingCount, flushPending]);

  // Dispara flush quando navegador volta online
  useEffect(() => {
    function onOnline() { flushPending(); }
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [flushPending]);

  async function loadLousaSummary(cid = collabId) {
    if (!cid) return;
    try {
      const r = await api.lousaByCollaborator(cid);
      const lastFin = (r.tickets || []).find((t) => t.status === "finalizada" || t.status === "encerrada");
      setLousaSummary({
        last_closed_at: r.last_closed_at,
        minutes_since_last_close: r.minutes_since_last_close,
        last_finished_ticket: lastFin || null,
      });
    } catch { /* ignore — pode não ter Entrada ainda */ }
  }

  async function doRefresh() {
    setRefreshing(true);
    try {
      await refresh(collabId);
      setRefreshFlash(true);
      setTimeout(() => setRefreshFlash(false), 1200);
    } finally {
      setRefreshing(false);
    }
  }

  // Carrega colaboradores + praças
  useEffect(() => {
    api.listCollaborators().then((cs) => {
      setCollabs(cs);
      if (forcedCollabId) {
        // mobile autenticado: usa o forçado pelo link
        setCollabId(forcedCollabId);
        return;
      }
      // SEM ?cid= no link → não selecionamos automaticamente. Cada técnico tem
      // o seu próprio link único compartilhado pelo gestor (rota /?cid=col-xxx).
      // O componente renderiza tela orientativa quando collabId fica vazio.
    });
    api.listPracas().then(setPracas).catch(() => setPracas([]));
  }, [forcedCollabId]);

  // Atualiza today + fences + colaborador (avatar) ao trocar colaborador
  async function refresh(cid = collabId) {
    if (!cid) return;
    const [t, f, cs] = await Promise.all([
      api.todayStatus(cid),
      api.listGeofences(cid),
      api.listCollaborators(),
    ]);
    setToday(t);
    setFences(f);
    setCollabs(cs);  // pega avatar_data_url atualizado da 1ª selfie válida
    loadLousaSummary(cid);
  }
  useEffect(() => {
    if (!collabId) return;
    if (typeof window !== "undefined") window.localStorage.setItem("ponto_collab_id", collabId);
    refresh(collabId);
    // eslint-disable-next-line
  }, [collabId]);

  // Tracking ao vivo: envia GPS ao backend enquanto o app está aberto
  const [pingIntervalSec, setPingIntervalSec] = useState(15);
  useEffect(() => {
    api.getSettings().then((s) => {
      if (s?.location_ping_interval_sec) setPingIntervalSec(Number(s.location_ping_interval_sec));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!collabId || typeof navigator === "undefined" || !navigator.geolocation) return;
    let lastSent = 0;
    let lastLat = null;
    let lastLng = null;
    const intervalMs = Math.max(5, Number(pingIntervalSec) || 15) * 1000;
    const watchId = navigator.geolocation.watchPosition(
      (pos) => {
        const now = Date.now();
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        const moved = lastLat == null ? Infinity : Math.hypot(lat - lastLat, lng - lastLng) * 111000;
        // Envia se: passou o intervalo configurado OU moveu mais de 10m
        if (now - lastSent >= intervalMs || moved > 10) {
          api.postLocation({
            collaborator_id: collabId,
            lat,
            lng,
            accuracy: pos.coords.accuracy,
            speed: pos.coords.speed,
            heading: pos.coords.heading,
          }).catch(() => {});
          lastSent = now;
          lastLat = lat;
          lastLng = lng;
        }
      },
      () => {},
      { enableHighAccuracy: true, maximumAge: Math.min(intervalMs / 2, 30000), timeout: 30000 }
    );
    return () => navigator.geolocation.clearWatch(watchId);
  }, [collabId, pingIntervalSec]);

  function getPosition() {
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        resolve({ ok: false, error: "Geolocalização não suportada neste dispositivo." });
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({ ok: true, lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy }),
        (err) => resolve({ ok: false, error: err.message || "Não foi possível obter sua localização." }),
        { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 }
      );
    });
  }

  async function quickClock() {
    setError(""); setGeoError("");
    const next = today?.next_expected || "Entrada";
    setEventType(next);
    // Captura GPS antes de abrir câmera
    setBusy(true);
    const pos = await getPosition();
    setBusy(false);
    if (!pos.ok) {
      setGeoError(pos.error);
      // Para Entrada/Saída exige cerca → bloqueia. Para intervalo, ainda dá pra prosseguir? Por segurança, exige.
      setError("Permita a localização para registrar o ponto.");
      return;
    }
    setPosition(pos);
    setCameraKey((k) => k + 1);
    setScreen("camera");
  }

  function retrySelfie() {
    setError("");
    setReceipt(null);
    setCameraKey((k) => k + 1);
    setScreen("camera");
  }

  async function onSelfieCaptured(dataUrl) {
    setBusy(true); setError("");
    const needsGps = collab?.is_test_mode !== true && collab?.clock_in_enabled !== false;
    const gpsMissing = needsGps && (position?.lat == null || position?.lng == null);

    // GPS indisponível → enfileira offline e avisa o usuário (não perde a selfie)
    if (gpsMissing) {
      try {
        const len = enqueueOffline({
          collaborator_id: collabId,
          type: eventType,
          selfie_base64: dataUrl,
          captured_at: new Date().toISOString(),
        });
        setPendingCount(len);
        setError(`Sua selfie foi salva (${len} pendente${len > 1 ? "s" : ""}). Quando o GPS for liberado, vamos reenviar automaticamente.`);
        setScreen("selfie-error");
      } catch (e) {
        setError("Não foi possível salvar localmente. Verifique o armazenamento do navegador.");
        setScreen("selfie-error");
      }
      setBusy(false);
      return;
    }

    try {
      const rec = await api.createClockRecord({
        collaborator_id: collabId,
        type: eventType,
        selfie_base64: dataUrl,
        lat: position?.lat ?? null,
        lng: position?.lng ?? null,
        public_ip: null,
        force_close_open_tickets: forceCloseOpen,
        client_time_ms: serverNow(),  // sincronizado com servidor (anti-tampering local)
      });
      setReceipt(rec);
      if (rec.status === "Bloqueado") {
        setScreen("blocked");
      } else {
        setScreen("receipt");
      }
      setForceCloseOpen(false);
      await refresh(collabId);
    } catch (e) {
      const status = e?.response?.status;
      const raw = e?.response?.data?.detail;
      // Trata mensagens estruturadas do FastAPI (Pydantic 422 vem como array)
      let detail;
      if (Array.isArray(raw)) {
        detail = raw.map((d) => `${(d.loc || []).slice(-1)[0] || "campo"}: ${d.msg}`).join(" · ");
      } else if (typeof raw === "string") {
        detail = raw;
      } else {
        detail = e.message || "Erro desconhecido";
      }
      // Status 409 ao bater Saída com bolha aberta → confirma
      if (status === 409 && eventType === "Saída") {
        setExitConfirm(true);
        setError("");
      } else if (status === 422) {
        setError(`Falha na validação dos dados enviados (${detail}). Recarregue a página e tente novamente.`);
        setScreen("selfie-error");
      } else if (!status) {
        // Erro de rede (offline ou backend indisponível) → enfileira
        try {
          const len = enqueueOffline({
            collaborator_id: collabId,
            type: eventType,
            selfie_base64: dataUrl,
            lat: position?.lat ?? null,
            lng: position?.lng ?? null,
            captured_at: new Date().toISOString(),
          });
          setPendingCount(len);
          setError(`Sem internet — sua selfie foi salva (${len} pendente${len > 1 ? "s" : ""}). Reenvio automático ao reconectar.`);
        } catch {
          setError("Sem internet e não conseguimos salvar localmente.");
        }
        setScreen("selfie-error");
      } else {
        setError(detail);
        setScreen("selfie-error");
      }
    }
    setBusy(false);
  }

  const collab = collabs.find((c) => c.id === collabId);

  // Wrapper para mobile vs desktop
  const Wrapper = mobile
    ? ({ children }) => (
        <div data-testid="mobile-collaborator" style={{ minHeight: "100vh", background: "#f8fafc", color: "#0f172a", fontFamily: "Inter, system-ui, Arial" }}>
          <div style={{ maxWidth: 480, margin: "0 auto" }}>{children}</div>
        </div>
      )
    : PhoneFrame;

  // Detecta se está em "Modo celular" via session override (botão do header) — permite voltar
  const overrideMode = (typeof sessionStorage !== "undefined") && sessionStorage.getItem("ponto_mode") === "app";
  const isAdminTest = (() => {
    if (typeof window === "undefined") return false;
    const token = window.localStorage.getItem("ponto_token");
    if (!token) return false;
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
      return payload.role === "administrador" || payload.role === "auditor";
    } catch { return false; }
  })();
  const exitMobile = () => {
    try {
      sessionStorage.removeItem("ponto_mode");
      window.dispatchEvent(new Event("ponto-mode-changed"));
    } catch {}
  };

  const appCard = { background: "white", border: "1px solid #e5e7eb", borderRadius: 14, padding: 18, boxShadow: "0 1px 2px rgba(15,23,42,.04)", marginBottom: 12 };
  const softCard = { ...appCard, background: "#f8fafc", boxShadow: "none", border: "1px solid #eef2f7" };
  const sectionLabel = { fontSize: 10, fontWeight: 700, color: "#64748b", letterSpacing: 1, textTransform: "uppercase" };

  if (!collabs.length) {
    return (
      <div style={{ padding: 24, color: "#64748b" }}>
        Nenhum colaborador cadastrado. Cadastre na aba <strong>Cadastro</strong> primeiro.
      </div>
    );
  }

  // App acessado sem ?cid= no link → orienta o técnico a usar o link próprio
  if (!collabId) {
    return (
      <Wrapper>
        <div data-testid="screen-no-link" style={{ ...appCard, padding: 28, textAlign: "center" }}>
          <div style={{
            width: 56, height: 56, borderRadius: 14, margin: "0 auto 14px",
            background: "#f1f5f9", display: "grid", placeItems: "center",
            border: "1px solid #e2e8f0",
          }}>
            <Icon name="phone" size={26} style={{ color: "#475569" }} />
          </div>
          <h2 style={{ margin: "0 0 8px", fontSize: 18, fontWeight: 700, color: "#0f172a" }}>
            Acesso pelo link próprio
          </h2>
          <p style={{ color: "#64748b", fontSize: 13, lineHeight: 1.5, margin: "0 0 16px" }}>
            Cada técnico tem um <strong style={{ color: "#0f172a" }}>link único</strong> enviado pelo gestor (geralmente por
            WhatsApp). Abra o link que você recebeu para entrar na sua Lousa.
          </p>
          <div style={{
            background: "#f8fafc", border: "1px solid #e2e8f0",
            borderRadius: 10, padding: 12, fontSize: 12, color: "#475569", textAlign: "left",
          }}>
            <strong style={{ color: "#0f172a" }}>Não tem o link?</strong>
            <br/>
            Procure o gestor da sua filial. Ele consegue gerar/copiar/enviar o seu link em segundos
            pela aba <em>Cadastro</em> do painel.
          </div>
        </div>
      </Wrapper>
    );
  }

  return (
    <div style={mobile ? {} : { display: "grid", gridTemplateColumns: "430px 1fr", gap: 22, alignItems: "start" }}>
      <Wrapper>
        {mobile && overrideMode && (
          <div data-testid="exit-mobile-bar" style={{
            background: "#0f172a", color: "white",
            padding: "8px 14px", display: "flex", justifyContent: "space-between",
            alignItems: "center", fontSize: 12, position: "sticky", top: 0, zIndex: 50,
          }}>
            <span>Visualizando como o colaborador no celular</span>
            <button
              data-testid="exit-mobile-btn"
              onClick={exitMobile}
              style={{ background: "white", color: "#0f172a", border: 0, padding: "4px 10px", borderRadius: 6, fontWeight: 700, cursor: "pointer", fontSize: 11 }}
            >
              ← Voltar ao painel
            </button>
          </div>
        )}
        {isAdminTest && (
          <div data-testid="admin-test-banner" style={{
            background: "#fffbeb", color: "#92400e",
            borderBottom: "1px solid #fcd34d",
            padding: "10px 14px", fontSize: 12, fontWeight: 600,
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "#f59e0b" }} />
            <span>Modo teste admin — cerca virtual ignorada (bater ponto em qualquer localização)</span>
          </div>
        )}
        <div style={{ padding: mobile ? "16px 16px 32px" : 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, position: "relative" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, flex: 1, minWidth: 0 }}>
              <button
                type="button"
                onDoubleClick={() => { if (collab?.avatar_data_url) setAvatarZoom(true); }}
                onClick={(e) => {
                  if (e.detail === 2 && collab?.avatar_data_url) setAvatarZoom(true);
                }}
                title={collab?.avatar_data_url ? "Toque 2x para ampliar" : "Sem foto cadastrada — bata seu primeiro ponto"}
                data-testid="user-avatar-btn"
                style={{
                  width: 56, height: 56, borderRadius: "50%", overflow: "hidden",
                  background: "#0f172a",
                  display: "grid", placeItems: "center", fontSize: 22, fontWeight: 700, color: "white",
                  border: "2px solid #ffffff", boxShadow: "0 0 0 1px #e2e8f0",
                  padding: 0, cursor: collab?.avatar_data_url ? "zoom-in" : "default",
                  flexShrink: 0, letterSpacing: 0.5,
                }}
              >
                {collab?.avatar_data_url
                  ? <img src={collab.avatar_data_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  : (collab?.name?.[0] || "?").toUpperCase()}
              </button>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 10, color: "#94a3b8", fontWeight: 700, letterSpacing: 1, textTransform: "uppercase" }}>Olá</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: "#0f172a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 2 }}>
                  {collab?.name?.split(" ")[0] || "—"}
                </div>
                <div style={{ fontSize: 11, color: "#64748b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {collab?.role || ""}
                </div>
              </div>
            </div>

            {/* Server clock + Kebab menu */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
              {pendingCount > 0 && (
                <button
                  data-testid="offline-pending-badge"
                  onClick={flushPending}
                  disabled={flushingOffline}
                  title={`${pendingCount} batida(s) salvas localmente — clique para tentar reenviar agora`}
                  style={{
                    border: "1px solid #fcd34d", padding: "4px 10px", borderRadius: 8,
                    background: flushingOffline ? "#fef3c7" : "#fffbeb",
                    color: "#92400e", fontSize: 11, fontWeight: 700,
                    cursor: "pointer", display: "flex", alignItems: "center", gap: 4,
                  }}
                >
                  {flushingOffline ? "↻" : "•"} {pendingCount} pend.
                </button>
              )}
              <ServerClock compact />
              <KebabMenu
                isAdminTest={isAdminTest}
                forcedCollabId={forcedCollabId}
                onLogoutGoogle={onLogout}
                onExitMobile={mobile && !forcedCollabId ? exitMobile : null}
                onOpenHistory={() => setScreen("history")}
                onOpenAssets={() => setShowMyAssets(true)}
              />
            </div>
          </div>

          {/* Sem seletor de colaborador — cada técnico acessa pelo SEU link único compartilhado pelo gestor.
              Se a página for aberta sem ?cid=, mostramos uma tela orientativa em vez de uma lista. */}

          {error && screen !== "selfie-error" && <div style={{ background: "#fef2f2", color: "#991b1b", padding: "10px 12px", borderRadius: 10, marginBottom: 10, fontSize: 12, border: "1px solid #fecaca" }}>{error}</div>}

          {screen === "home" && today && (() => {
            const clockEnabled = collab?.clock_in_enabled !== false;
            // Colaborador externo (clock_in_enabled=false) → tela focada em Lousa
            if (!clockEnabled) {
              return (
                <div data-testid="screen-home-no-clock">
                  <div style={{ ...appCard, padding: 18 }}>
                    <div style={sectionLabel}>Colaborador externo</div>
                    <div style={{ fontSize: 20, fontWeight: 800, marginTop: 6, color: "#0f172a", letterSpacing: -0.3 }}>
                      Você não bate ponto
                    </div>
                    <div style={{ marginTop: 6, color: "#64748b", fontSize: 12, lineHeight: 1.5 }}>
                      Acompanhe e finalize seus serviços diretamente na Lousa.
                    </div>
                  </div>

                  <button
                    data-testid="open-lousa-btn-primary"
                    onClick={() => setScreen("lousa")}
                    style={{
                      width: "100%", height: 56, borderRadius: 12, border: 0,
                      background: "#0f172a",
                      color: "white", fontWeight: 700, fontSize: 15,
                      marginTop: 2, marginBottom: 10,
                      cursor: "pointer", letterSpacing: 0.2,
                      display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
                    }}
                  >
                    <Icon name="clipboard" /> Abrir Lousa de Serviços
                  </button>

                  {/* Resumo do último serviço */}
                  {lousaSummary?.last_finished_ticket && (
                    <div data-testid="last-service-summary" style={{
                      marginTop: 10, padding: 14, borderRadius: 12,
                      background: "white", border: "1px solid #e2e8f0",
                      fontSize: 12, color: "#475569",
                    }}>
                      <div style={{ ...sectionLabel, marginBottom: 6 }}>Último serviço encerrado</div>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                        <span style={{ color: "#0f172a", fontWeight: 600 }}>{lousaSummary.last_finished_ticket.client_snapshot?.name}</span>
                        <strong style={{ color: "#0f172a" }}>
                          {lousaSummary.last_finished_ticket.duration_minutes != null
                            ? formatDur(lousaSummary.last_finished_ticket.duration_minutes)
                            : ""}
                        </strong>
                      </div>
                    </div>
                  )}

                  <div style={{ ...softCard, marginTop: 14 }}>
                    {(() => {
                      const p = pracas.find((x) => x.id === collab?.praca_id);
                      return <Row label="Praça" value={p ? `${p.city}/${p.state}` : (collab?.company || "—")} />;
                    })()}
                    {(() => {
                      const dev = parseDevice(navigator.userAgent || "");
                      return (
                        <>
                          <Row label="Dispositivo" value={dev.device} />
                          <Row label="Sistema" value={dev.os} />
                        </>
                      );
                    })()}
                  </div>
                </div>
              );
            }
            // Layout CLT padrão (com bater ponto)
            return (
            <div data-testid="screen-home">
              <div style={{ ...appCard, padding: 18 }}>
                <div style={sectionLabel}>Próximo ponto</div>
                <div style={{ fontSize: 30, fontWeight: 800, marginTop: 6, color: "#0f172a", letterSpacing: -0.5 }}>{today.next_expected}</div>
                <div style={{ marginTop: 4, color: "#64748b", fontSize: 12 }}>{today.records.length} registro(s) hoje</div>
              </div>

              <button
                data-testid="open-clock-btn"
                onClick={quickClock}
                disabled={busy || !collabId}
                style={{ width: "100%", height: 56, borderRadius: 12, border: 0, background: "#0f172a", color: "white", fontWeight: 700, fontSize: 15, marginBottom: 10, cursor: "pointer", opacity: busy ? 0.6 : 1, letterSpacing: 0.2, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8 }}
              >
                <Icon name="camera" /> {busy ? "..." : `Bater ${today.next_expected || "Ponto"}`}
              </button>
              {geoError && <div style={{ color: "#b91c1c", fontSize: 11, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}><Icon name="alert" /> {geoError}</div>}

              <button
                data-testid="open-lousa-btn"
                onClick={() => setScreen("lousa")}
                style={{
                  width: "100%", height: 48, marginTop: 2, marginBottom: 4,
                  background: "white",
                  border: "1px solid #e2e8f0",
                  borderRadius: 12,
                  color: "#0f172a",
                  fontWeight: 600, fontSize: 14,
                  cursor: "pointer",
                  display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
                }}
              >
                <Icon name="clipboard" /> Lousa de Serviços
              </button>

              {/* Resumo do último serviço — visível antes de bater Saída */}
              {lousaSummary?.last_finished_ticket && (
                <div data-testid="last-service-summary" style={{
                  marginTop: 10, padding: 14, borderRadius: 12,
                  background: "white", border: "1px solid #e2e8f0",
                  fontSize: 12, color: "#475569",
                }}>
                  <div style={{ ...sectionLabel, marginBottom: 6 }}>Último serviço encerrado</div>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <span style={{ color: "#0f172a", fontWeight: 600 }}>{lousaSummary.last_finished_ticket.client_snapshot?.name}</span>
                    <strong style={{ color: "#0f172a" }}>
                      {lousaSummary.last_finished_ticket.duration_minutes != null
                        ? formatDur(lousaSummary.last_finished_ticket.duration_minutes)
                        : ""}
                    </strong>
                  </div>
                  {lousaSummary.minutes_since_last_close != null && (
                    <div style={{ marginTop: 8, color: "#64748b", fontSize: 11 }}>
                      Há {formatGap(lousaSummary.minutes_since_last_close)} desde o encerramento — bata Saída assim que terminar.
                    </div>
                  )}
                </div>
              )}

              <div style={{ ...softCard, marginTop: 14 }}>
                {(() => {
                  const p = pracas.find((x) => x.id === collab?.praca_id);
                  return <Row label="Praça" value={p ? `${p.city}/${p.state}` : (collab?.company || "—")} />;
                })()}
                <Row label="Horário" value={`${collab?.schedule?.entrada} / ${collab?.schedule?.saida}`} />
                {(() => {
                  const valid = (today?.records || []).filter((r) => r.status === "Válido" || r.status === "Offline sincronizado");
                  const byType = {};
                  valid.forEach((r) => { byType[r.type] = r; });
                  return (
                    <>
                      <Row
                        label="Entrada (hoje)"
                        value={byType["Entrada"]?.time ? `${byType["Entrada"].time}` : "—"}
                      />
                      <Row
                        label="Saída (hoje)"
                        value={byType["Saída"]?.time ? `${byType["Saída"].time}` : "—"}
                      />
                    </>
                  );
                })()}
                {(() => {
                  const dev = parseDevice(navigator.userAgent || "");
                  return (
                    <>
                      <Row label="Dispositivo" value={dev.device} />
                      <Row label="Sistema" value={dev.os} />
                    </>
                  );
                })()}
              </div>
            </div>
            );
          })()}

          {screen === "camera" && (
            <SelfieCamera key={cameraKey} eventType={eventType} onCapture={onSelfieCaptured} onCancel={() => setScreen("home")} />
          )}

          {screen === "selfie-error" && (
            <div data-testid="screen-selfie-error">
              <div style={{ textAlign: "center", padding: "24px 0" }}>
                <div style={{ width: 72, height: 72, borderRadius: 18, background: "#fef3c7", display: "grid", placeItems: "center", margin: "0 auto", border: "1px solid #fcd34d" }}>
                  <Icon name="alert" size={32} style={{ color: "#b45309" }} />
                </div>
                <h2 style={{ marginBottom: 6, marginTop: 14, fontSize: 17, fontWeight: 700, color: "#0f172a" }}>Não conseguimos validar sua selfie</h2>
                <p style={{ color: "#b45309", marginTop: 0, fontWeight: 600, fontSize: 13 }}>{error || "Erro ao registrar o ponto. Tente novamente."}</p>
              </div>
              <Button onClick={retrySelfie} style={{ width: "100%", borderRadius: 12, marginBottom: 8 }} data-testid="selfie-retry-btn">
                <Icon name="camera" /> Refazer selfie
              </Button>
              <Button variant="soft" onClick={() => { setError(""); setScreen("home"); }} style={{ width: "100%", borderRadius: 12 }} data-testid="selfie-error-home-btn">
                Voltar ao início
              </Button>
            </div>
          )}

          {screen === "blocked" && receipt && (
            <div data-testid="screen-blocked">
              <div style={{ textAlign: "center", padding: "24px 0" }}>
                <div style={{ width: 72, height: 72, borderRadius: 18, background: "#fee2e2", display: "grid", placeItems: "center", margin: "0 auto", border: "1px solid #fecaca" }}>
                  <Icon name="block" size={32} style={{ color: "#b91c1c" }} />
                </div>
                <h2 style={{ marginBottom: 6, marginTop: 14, fontSize: 17, fontWeight: 700, color: "#0f172a" }}>Ponto não registrado</h2>
                <p style={{ color: "#b91c1c", marginTop: 0, fontWeight: 600, fontSize: 13 }}>{receipt.public_block_message || receipt.note}</p>
              </div>
              <Button onClick={retrySelfie} style={{ width: "100%", borderRadius: 12, marginBottom: 8 }} data-testid="blocked-retry-btn">
                <Icon name="camera" /> Refazer selfie
              </Button>
              <Button variant="soft" onClick={() => { setReceipt(null); setScreen("home"); }} style={{ width: "100%", borderRadius: 12 }} data-testid="blocked-home-btn">
                Voltar ao início
              </Button>
            </div>
          )}

          {screen === "receipt" && receipt && (
            <div data-testid="screen-receipt">
              <div style={{ textAlign: "center", padding: "12px 0" }}>
                {receipt.selfie_url && (
                  <img src={receipt.selfie_url} alt="Selfie" style={{ width: 110, height: 140, objectFit: "cover", borderRadius: 14, border: "1px solid #e2e8f0" }} />
                )}
                <div style={{ marginTop: 12 }}>
                  <Icon name="check" size={28} style={{ color: "#059669" }} />
                </div>
                <h2 style={{ marginBottom: 4, marginTop: 6, fontSize: 17, fontWeight: 700, color: "#0f172a" }}>{receipt.type} registrada</h2>
                <p style={{ color: "#64748b", marginTop: 0, fontSize: 12 }}>{receipt.protocol}</p>
              </div>
              <div style={appCard}>
                <Row label="Data/hora" value={`${receipt.date} ${receipt.time}`} />
                <Row label="Local" value={receipt.geofence_name || "Cerca não exigida"} />
                <Row label="Distância" value={receipt.distance_m != null ? `${receipt.distance_m} m` : "—"} />
                <Row label="Cerca" value={<StatusBadge status={receipt.geo_status} />} />
                <Row label="Status" value={<StatusBadge status={receipt.status} />} />
              </div>
              <Button onClick={() => setScreen("home")} style={{ width: "100%", borderRadius: 12 }} data-testid="receipt-done-btn">Concluir</Button>
            </div>
          )}

          {screen === "history" && today && (
            <div data-testid="screen-history">
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 14 }}>
                <Button variant="soft" onClick={() => setScreen("home")} data-testid="back-home-btn">← Voltar</Button>
                <Button
                  variant="soft"
                  onClick={doRefresh}
                  disabled={refreshing}
                  data-testid="history-refresh-btn"
                  style={{
                    background: refreshFlash ? "#f0fdf4" : refreshing ? "#fefce8" : "#f8fafc",
                    color: refreshFlash ? "#15803d" : refreshing ? "#a16207" : "#475569",
                    border: `1px solid ${refreshFlash ? "#bbf7d0" : refreshing ? "#fef08a" : "#e2e8f0"}`,
                    transition: "background-color .25s",
                  }}
                >
                  {refreshing ? "Atualizando…" : refreshFlash ? "✓ Atualizado" : "Atualizar"}
                </Button>
              </div>
              <div style={{ ...sectionLabel, marginBottom: 8 }}>Hoje ({today.date})</div>
              {today.records.length === 0 && <p style={{ color: "#64748b", fontSize: 13 }}>Sem registros ainda.</p>}
              {today.records.map((r) => (
                <div key={r.id} style={{ background: "white", border: "1px solid #e2e8f0", borderRadius: 12, padding: 12, marginBottom: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong style={{ color: "#0f172a", fontSize: 13 }}>{r.type}</strong><StatusBadge status={r.status} />
                  </div>
                  <div style={{ color: "#64748b", fontSize: 12, marginTop: 4 }}>{r.time} • {r.geofence_name || "—"} {r.distance_m != null ? `(${r.distance_m}m)` : ""}</div>
                </div>
              ))}
            </div>
          )}

          {screen === "lousa" && (
            <LousaMobile collaboratorId={collabId} onBack={() => setScreen("home")} />
          )}

          {/* Modal: Saída com bolhas em aberto */}
          {exitConfirm && (
            <div
              data-testid="exit-confirm-modal"
              style={{
                position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", zIndex: 100,
                display: "grid", placeItems: "center", padding: 16,
              }}
              onClick={() => setExitConfirm(false)}
            >
              <div onClick={(e) => e.stopPropagation()} style={{
                background: "white", borderRadius: 14, padding: 22, maxWidth: 380, width: "100%",
                border: "1px solid #e2e8f0",
              }}>
                <div style={{
                  width: 56, height: 56, borderRadius: 14, background: "#fef3c7",
                  display: "grid", placeItems: "center", margin: "0 auto 12px",
                  border: "1px solid #fcd34d",
                }}>
                  <Icon name="alert" size={26} style={{ color: "#b45309" }} />
                </div>
                <h2 style={{ textAlign: "center", margin: "0 0 6px", fontSize: 16, fontWeight: 700, color: "#0f172a" }}>Você tem nota(s) em aberto</h2>
                <p style={{ color: "#64748b", textAlign: "center", margin: "0 0 18px", fontSize: 13, lineHeight: 1.5 }}>
                  Deseja encerrar essas notas e bater o ponto de Saída?<br />
                  <strong style={{ color: "#0f172a" }}>O gestor será notificado</strong>.
                </p>
                <Button
                  data-testid="confirm-close-tickets-btn"
                  onClick={async () => {
                    setExitConfirm(false);
                    setForceCloseOpen(true);
                    setCameraKey((k) => k + 1);
                    setScreen("camera");
                  }}
                  style={{ width: "100%", marginBottom: 8, background: "#0f172a", color: "white", borderRadius: 10 }}
                >
                  Sim, encerrar e bater Saída
                </Button>
                <Button
                  variant="soft"
                  onClick={() => setExitConfirm(false)}
                  style={{ width: "100%", borderRadius: 10 }}
                  data-testid="cancel-exit-btn"
                >
                  Cancelar — voltar e finalizar manualmente
                </Button>
              </div>
            </div>
          )}
        </div>
      </Wrapper>

      {!mobile && (
        <div>
          <Card title="QR do app">
            <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
              <img
                alt="QR"
                src={`https://api.qrserver.com/v1/create-qr-code/?size=220x220&margin=8&data=${encodeURIComponent((typeof window !== "undefined" ? window.location.origin : "") + "/?mode=app")}`}
                width={130} height={130}
                style={{ borderRadius: 14, border: "1px solid #e2e8f0", background: "white" }}
                data-testid="qr-mobile"
              />
              <div style={{ flex: 1, minWidth: 180 }}>
                <p style={{ color: "#64748b", fontSize: 12, margin: 0, lineHeight: 1.5 }}>
                  Escaneie e adicione à tela inicial.
                </p>
                <Button style={{ marginTop: 10 }} variant="soft" onClick={() => window.open("/?mode=app", "_blank")}><Icon name="phone" /> Abrir</Button>
              </div>
            </div>
          </Card>

          <Card title="Resumo de hoje">
            {today && <Row label="Próximo ponto" value={today.next_expected} />}
            <Row label="Registros hoje" value={today?.records?.length || 0} />
          </Card>
        </div>
      )}

      <AvatarZoomModal
        src={avatarZoom ? collab?.avatar_data_url : null}
        caption={collab?.name}
        onClose={() => setAvatarZoom(false)}
      />

      {showMyAssets && (
        <MyAssetsModal collaboratorId={collabId} onClose={() => setShowMyAssets(false)} />
      )}
    </div>
  );
}

// Detecta dispositivo e SO a partir do user-agent (heurística leve, sem libs externas)
function parseDevice(ua) {
  const u = (ua || "").toLowerCase();
  let device = "Navegador";
  let os = "Desconhecido";
  // OS
  if (/iphone|ipad|ipod/.test(u)) os = "iOS";
  else if (/android/.test(u)) os = "Android";
  else if (/windows nt 10/.test(u)) os = "Windows 10/11";
  else if (/windows nt/.test(u)) os = "Windows";
  else if (/mac os x/.test(u)) os = "macOS";
  else if (/linux/.test(u)) os = "Linux";
  // Modelo (Android costuma incluir, ex: "; SM-G998B Build/...")
  const androidModel = ua && ua.match(/Android[^;]*; ([^;)]+)/i);
  const iphoneVer = ua && ua.match(/iPhone OS ([\d_]+)/i);
  if (androidModel) device = androidModel[1].split("Build")[0].trim();
  else if (iphoneVer) device = `iPhone (iOS ${iphoneVer[1].replace(/_/g, ".")})`;
  else if (/iphone/.test(u)) device = "iPhone";
  else if (/ipad/.test(u)) device = "iPad";
  else if (/macintosh/.test(u)) device = "Mac";
  else if (/windows/.test(u)) device = "PC";
  // Browser
  let browser = "navegador";
  if (/edg\//.test(u)) browser = "Edge";
  else if (/chrome\//.test(u)) browser = "Chrome";
  else if (/firefox/.test(u)) browser = "Firefox";
  else if (/safari/.test(u)) browser = "Safari";
  return { device: `${device} · ${browser}`, os };
}


function KebabMenu({ isAdminTest, forcedCollabId, onLogoutGoogle, onExitMobile, onOpenHistory, onOpenAssets }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);

  React.useEffect(() => {
    if (!open) return;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const items = [];
  items.push({ key: "history", label: "Histórico", icon: "history", onClick: () => { onOpenHistory && onOpenHistory(); setOpen(false); } });
  if (onOpenAssets) {
    items.push({ key: "assets", label: "Meus itens em custódia", icon: "boxes", onClick: () => { onOpenAssets(); setOpen(false); } });
  }
  if (forcedCollabId && onLogoutGoogle) {
    items.push({ key: "logout", label: "Sair da conta Google", icon: "logout", onClick: () => { onLogoutGoogle(); setOpen(false); } });
  }
  if (onExitMobile) {
    items.push({ key: "exit-mobile", label: "Voltar ao painel", icon: "chevron", onClick: () => { onExitMobile(); setOpen(false); } });
  }

  return (
    <div ref={ref} style={{ position: "relative", flexShrink: 0 }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        data-testid="kebab-menu-btn"
        aria-label="Mais opções"
        title="Mais opções"
        style={{
          width: 38, height: 38, borderRadius: "50%",
          border: "1px solid #e2e8f0", background: open ? "#f1f5f9" : "white",
          display: "grid", placeItems: "center", cursor: "pointer",
          fontSize: 20, color: "#475569", padding: 0, lineHeight: 0,
          transition: "background-color .15s, transform .15s",
          transform: open ? "rotate(90deg)" : "rotate(0deg)",
        }}
      >⋮</button>
      {open && (
        <div data-testid="kebab-menu-dropdown" style={{
          position: "absolute", top: 44, right: 0, zIndex: 60,
          background: "white", border: "1px solid #e2e8f0",
          borderRadius: 14, boxShadow: "0 14px 30px rgba(15,23,42,.18)",
          minWidth: 200, padding: 6, animation: "fadeIn .15s",
        }}>
          {items.map((it) => (
            <button
              key={it.key}
              data-testid={`kebab-${it.key}`}
              onClick={it.onClick}
              style={{
                display: "flex", alignItems: "center", gap: 10, width: "100%",
                background: "transparent", border: 0, padding: "10px 12px",
                fontSize: 13, fontWeight: 500, color: "#0f172a",
                cursor: "pointer", borderRadius: 8, textAlign: "left",
              }}
              onMouseOver={(e) => (e.currentTarget.style.background = "#f1f5f9")}
              onMouseOut={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <Icon name={it.icon} size={15} style={{ color: "#64748b" }} />
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
