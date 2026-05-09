import React, { useEffect, useState } from "react";
import { api } from "@/api";
import SelfieCamera from "@/SelfieCamera";
import LousaMobile from "@/LousaMobile";
import { AvatarZoomModal, Button, Card, fmtMin, Icon, inputStyle, PhoneFrame, Row, softButtonStyle, StatusBadge } from "@/ui";

const EVENT_TYPES = ["Entrada", "Início intervalo", "Fim intervalo", "Saída"];
const GEOFENCE_REQUIRED = new Set(["Entrada", "Saída"]);

export default function CollaboratorApp({ mobile = false }) {
  return <CollaboratorAppInner mobile={mobile} forcedCollabId={null} onLogout={null} />;
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
        // mobile autenticado: usa o forçado
        setCollabId(forcedCollabId);
        return;
      }
      // desktop preview / sem auth: usa última escolha ou primeiro
      const saved = (typeof window !== "undefined") ? window.localStorage.getItem("ponto_collab_id") : null;
      const valid = cs.find((c) => c.id === saved) ? saved : cs[0]?.id;
      if (valid) setCollabId(valid);
    });
    api.listPracas().then(setPracas).catch(() => setPracas([]));
  }, [forcedCollabId]);

  // Atualiza today + fences ao trocar colaborador
  async function refresh(cid = collabId) {
    if (!cid) return;
    const [t, f] = await Promise.all([api.todayStatus(cid), api.listGeofences(cid)]);
    setToday(t);
    setFences(f);
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
    try {
      const rec = await api.createClockRecord({
        collaborator_id: collabId,
        type: eventType,
        selfie_base64: dataUrl,
        lat: position.lat,
        lng: position.lng,
        public_ip: null,
        force_close_open_tickets: forceCloseOpen,
        client_time_ms: Date.now(),
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
      const detail = e?.response?.data?.detail || e.message;
      const status = e?.response?.status;
      // Status 409 ao bater Saída com bolha aberta → confirma
      if (status === 409 && eventType === "Saída") {
        setExitConfirm(true);
        setError("");
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

  const appCard = { background: "white", border: "1px solid #e2e8f0", borderRadius: 24, padding: 16, boxShadow: "0 10px 24px rgba(15,23,42,.06)", marginBottom: 14 };
  const softCard = { ...appCard, background: "#f8fafc", boxShadow: "none" };

  if (!collabs.length) {
    return (
      <div style={{ padding: 24, color: "#64748b" }}>
        Nenhum colaborador cadastrado. Cadastre na aba <strong>Cadastro</strong> primeiro.
      </div>
    );
  }

  return (
    <div style={mobile ? {} : { display: "grid", gridTemplateColumns: "430px 1fr", gap: 22, alignItems: "start" }}>
      <Wrapper>
        {mobile && overrideMode && (
          <div data-testid="exit-mobile-bar" style={{
            background: "linear-gradient(90deg,#0f172a,#334155)", color: "white",
            padding: "8px 14px", display: "flex", justifyContent: "space-between",
            alignItems: "center", fontSize: 12, position: "sticky", top: 0, zIndex: 50,
          }}>
            <span>👁️ Visualizando como o colaborador no celular</span>
            <button
              data-testid="exit-mobile-btn"
              onClick={exitMobile}
              style={{ background: "white", color: "#0f172a", border: 0, padding: "4px 10px", borderRadius: 8, fontWeight: 800, cursor: "pointer", fontSize: 11 }}
            >
              ← Voltar ao painel
            </button>
          </div>
        )}
        {isAdminTest && (
          <div data-testid="admin-test-banner" style={{
            background: "linear-gradient(90deg,#7c3aed,#a855f7)", color: "white",
            padding: "10px 14px", fontSize: 12, fontWeight: 700,
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <span style={{ fontSize: 18 }}>🧪</span>
            <span>MODO TESTE ADMIN — cerca virtual ignorada (bater ponto em qualquer localização)</span>
          </div>
        )}
        <div style={{ padding: mobile ? "16px 16px 32px" : 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 12, color: "#64748b" }}>Olá</div>
              <strong style={{ fontSize: 18 }}>{collab?.name}</strong>
              <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>{collab?.role}</div>
            </div>
            <button
              type="button"
              onDoubleClick={() => { if (collab?.avatar_data_url) setAvatarZoom(true); }}
              onClick={(e) => {
                // No mobile/touch o duplo toque é registrado como dois clicks rápidos — detectamos via detail
                if (e.detail === 2 && collab?.avatar_data_url) setAvatarZoom(true);
              }}
              title={collab?.avatar_data_url ? "Toque 2x para ampliar" : "Sem foto cadastrada"}
              data-testid="user-avatar-btn"
              style={{
                width: 50, height: 50, borderRadius: "50%", overflow: "hidden",
                background: "linear-gradient(135deg,#e2e8f0,#cbd5e1)",
                display: "grid", placeItems: "center", fontSize: 23,
                border: "3px solid white", boxShadow: "0 8px 18px rgba(15,23,42,.12)",
                padding: 0, cursor: collab?.avatar_data_url ? "zoom-in" : "default",
              }}
            >
              {collab?.avatar_data_url ? <img src={collab.avatar_data_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <Icon name="user" />}
            </button>
          </div>

          {forcedCollabId && onLogout && (
            <div style={{ marginBottom: 10 }}>
              <button
                onClick={onLogout}
                data-testid="logout-collab-btn"
                style={{ background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0", borderRadius: 8, padding: "4px 10px", fontSize: 11, cursor: "pointer", fontWeight: 700 }}
              >
                Sair da conta Google
              </button>
            </div>
          )}

          {/* Seletor de colaborador — escondido quando autenticado via Google (mobile) */}
          {!forcedCollabId && collabs.length > 1 && (
            <div style={{ marginBottom: 12 }}>
              <select data-testid="collab-select" value={collabId || ""} onChange={(e) => setCollabId(e.target.value)} style={{ ...inputStyle, fontSize: 13 }}>
                {collabs.map((c) => <option key={c.id} value={c.id}>{c.name} — {c.cpf}</option>)}
              </select>
            </div>
          )}

          {error && screen !== "selfie-error" && <div style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10 }}>{error}</div>}

          {screen === "home" && today && (
            <div data-testid="screen-home">
              <div style={{ ...appCard, background: "linear-gradient(135deg,#0f172a,#1e293b)", color: "white", border: "none", padding: 18 }}>
                <div style={{ color: "#cbd5e1", fontSize: 12 }}>Próximo</div>
                <div style={{ fontSize: 28, fontWeight: 950, marginTop: 4 }}>{today.next_expected}</div>
                <div style={{ marginTop: 6, color: "#94a3b8", fontSize: 11 }}>{today.records.length} registro(s) hoje</div>
              </div>

              <button
                data-testid="open-clock-btn"
                onClick={quickClock}
                disabled={busy || !collabId}
                style={{ width: "100%", height: 62, borderRadius: 32, border: 0, background: "#10b981", color: "#050b16", fontWeight: 950, fontSize: 16, marginBottom: 8, boxShadow: "0 16px 30px rgba(16,185,129,.4)", cursor: "pointer", opacity: busy ? 0.6 : 1 }}
              >
                <Icon name="camera" /> {busy ? "..." : "Bater Ponto"}
              </button>
              {geoError && <div style={{ color: "#be123c", fontSize: 11, marginBottom: 8 }}><Icon name="alert" /> {geoError}</div>}

              <button data-testid="open-history-btn" onClick={() => setScreen("history")} style={{ ...softButtonStyle(), width: "100%", height: 58 }}>
                <div style={{ fontSize: 18 }}><Icon name="history" /></div><strong>Histórico</strong>
              </button>

              <button
                data-testid="open-lousa-btn"
                onClick={() => setScreen("lousa")}
                style={{
                  ...softButtonStyle(),
                  width: "100%", height: 58, marginTop: 8,
                  background: "linear-gradient(135deg, #fef3c7, #fde68a)",
                  border: "1px solid #f59e0b",
                  color: "#78350f",
                }}
              >
                <div style={{ fontSize: 18 }}>📋</div><strong>Lousa de Serviços</strong>
              </button>

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
          )}

          {screen === "camera" && (
            <SelfieCamera key={cameraKey} eventType={eventType} onCapture={onSelfieCaptured} onCancel={() => setScreen("home")} />
          )}

          {screen === "selfie-error" && (
            <div data-testid="screen-selfie-error">
              <div style={{ textAlign: "center", padding: "24px 0" }}>
                <div style={{ width: 110, height: 110, borderRadius: "50%", background: "#fef3c7", display: "grid", placeItems: "center", fontSize: 50, margin: "0 auto", border: "6px solid white", boxShadow: "0 16px 34px rgba(15,23,42,.16)" }}>
                  <Icon name="alert" />
                </div>
                <h2 style={{ marginBottom: 6 }}>Não conseguimos validar sua selfie</h2>
                <p style={{ color: "#b45309", marginTop: 0, fontWeight: 700 }}>{error || "Erro ao registrar o ponto. Tente novamente."}</p>
              </div>
              <Button onClick={retrySelfie} style={{ width: "100%", borderRadius: 28, marginBottom: 8 }} data-testid="selfie-retry-btn">
                <Icon name="camera" /> Refazer selfie
              </Button>
              <Button variant="soft" onClick={() => { setError(""); setScreen("home"); }} style={{ width: "100%", borderRadius: 28 }} data-testid="selfie-error-home-btn">
                Voltar ao início
              </Button>
            </div>
          )}

          {screen === "blocked" && receipt && (
            <div data-testid="screen-blocked">
              <div style={{ textAlign: "center", padding: "24px 0" }}>
                <div style={{ width: 110, height: 110, borderRadius: "50%", background: "#fee2e2", display: "grid", placeItems: "center", fontSize: 50, margin: "0 auto", border: "6px solid white", boxShadow: "0 16px 34px rgba(15,23,42,.16)" }}>
                  <Icon name="block" />
                </div>
                <h2 style={{ marginBottom: 6 }}>Ponto não registrado</h2>
                <p style={{ color: "#be123c", marginTop: 0, fontWeight: 700 }}>{receipt.public_block_message || receipt.note}</p>
              </div>
              <Button onClick={retrySelfie} style={{ width: "100%", borderRadius: 28, marginBottom: 8 }} data-testid="blocked-retry-btn">
                <Icon name="camera" /> Refazer selfie
              </Button>
              <Button variant="soft" onClick={() => { setReceipt(null); setScreen("home"); }} style={{ width: "100%", borderRadius: 28 }} data-testid="blocked-home-btn">
                Voltar ao início
              </Button>
            </div>
          )}

          {screen === "receipt" && receipt && (
            <div data-testid="screen-receipt">
              <div style={{ textAlign: "center", padding: "12px 0" }}>
                {receipt.selfie_url && (
                  <img src={receipt.selfie_url} alt="Selfie" style={{ width: 120, height: 150, objectFit: "cover", borderRadius: 22, border: "5px solid white", boxShadow: "0 12px 26px rgba(15,23,42,.16)" }} />
                )}
                <div style={{ fontSize: 36, marginTop: 8 }}><Icon name="check" /></div>
                <h2 style={{ marginBottom: 4 }}>{receipt.type} registrada</h2>
                <p style={{ color: "#64748b", marginTop: 0 }}>{receipt.protocol}</p>
              </div>
              <div style={appCard}>
                <Row label="Data/hora" value={`${receipt.date} ${receipt.time}`} />
                <Row label="Local" value={receipt.geofence_name || "Cerca não exigida"} />
                <Row label="Distância" value={receipt.distance_m != null ? `${receipt.distance_m} m` : "—"} />
                <Row label="Cerca" value={<StatusBadge status={receipt.geo_status} />} />
                <Row label="Status" value={<StatusBadge status={receipt.status} />} />
              </div>
              <Button onClick={() => setScreen("home")} style={{ width: "100%", borderRadius: 28 }} data-testid="receipt-done-btn">Concluir</Button>
            </div>
          )}

          {screen === "history" && today && (
            <div data-testid="screen-history">
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Button variant="soft" onClick={() => setScreen("home")} data-testid="back-home-btn">← Voltar</Button>
                <Button
                  variant="soft"
                  onClick={doRefresh}
                  disabled={refreshing}
                  data-testid="history-refresh-btn"
                  style={{
                    background: refreshFlash ? "#dcfce7" : refreshing ? "#fef9c3" : "#dbeafe",
                    color: refreshFlash ? "#166534" : refreshing ? "#92400e" : "#1e40af",
                    border: `1px solid ${refreshFlash ? "#86efac" : refreshing ? "#fde68a" : "#93c5fd"}`,
                    transition: "background-color .25s",
                  }}
                >
                  {refreshing ? "⏳ Atualizando..." : refreshFlash ? "✓ Atualizado" : "🔄 Atualizar"}
                </Button>
              </div>
              <h2>Hoje ({today.date})</h2>
              {today.records.length === 0 && <p style={{ color: "#64748b" }}>Sem registros ainda.</p>}
              {today.records.map((r) => (
                <div key={r.id} style={{ background: "white", border: "1px solid #e2e8f0", borderRadius: 18, padding: 12, marginBottom: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <strong>{r.type}</strong><StatusBadge status={r.status} />
                  </div>
                  <div style={{ color: "#64748b", fontSize: 13 }}>{r.time} • {r.geofence_name || "—"} {r.distance_m != null ? `(${r.distance_m}m)` : ""}</div>
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
                background: "white", borderRadius: 22, padding: 22, maxWidth: 380, width: "100%",
              }}>
                <div style={{ fontSize: 50, textAlign: "center" }}>⚠️</div>
                <h2 style={{ textAlign: "center", margin: "8px 0 4px" }}>Você tem nota(s) em aberto</h2>
                <p style={{ color: "#64748b", textAlign: "center", margin: "0 0 18px", fontSize: 13 }}>
                  Deseja encerrar essas notas e bater o ponto de Saída?<br />
                  <strong>O gestor será notificado</strong>.
                </p>
                <Button
                  data-testid="confirm-close-tickets-btn"
                  onClick={async () => {
                    setExitConfirm(false);
                    setForceCloseOpen(true);
                    setCameraKey((k) => k + 1);
                    setScreen("camera");
                  }}
                  style={{ width: "100%", marginBottom: 8, background: "#dc2626" }}
                >
                  Sim, encerrar e bater Saída
                </Button>
                <Button
                  variant="soft"
                  onClick={() => setExitConfirm(false)}
                  style={{ width: "100%" }}
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
