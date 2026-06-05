import React, { useEffect, useState, useCallback, useRef } from "react";
import { stampFieldPhoto } from "@/utils/photoStamp";
import { saveDraft, loadDraft, clearDraft, cleanupOldDrafts } from "@/utils/osDraftStorage";
import outbox from "@/utils/offlineQueue";
import { api } from "@/api";
import { Button, Icon } from "@/ui";
import QRScannerModal from "@/QRScannerModal";
import OntScanModal from "@/OntScanModal";
import OntScanBatchModal from "@/OntScanBatchModal";
import UberGpsPicker from "@/UberGpsPicker";
import AchievementsCard from "@/AchievementsCard";
// PingTestModal removed — substituído por PingAutoStep (automático)
import CTOPortPicker from "@/CTOPortPicker";
import CadastroCTOWizard from "@/CadastroCTOWizard";
import { OdometerBubble, OdometerCaptureModal } from "@/OdometerBubble";
import CtoInlineFlow from "@/CtoInlineFlow";
import OsCtoPicker from "@/OsCtoPicker";
import LousaStepIndicator from "@/LousaStepIndicator";
import { styleForQuality } from "@/signalQuality";
import WeeklyInspectionFlow from "@/fleet/WeeklyInspectionFlow";
import Ipv6TestStep from "@/Ipv6TestStep";
import PingAutoStep from "@/PingAutoStep";
import OsClientChat from "@/OsClientChat";
import OsAlvaroSummary from "@/OsAlvaroSummary";
import { fmtAddress, fmtPhone, fmtName, fmtRelato, safeText } from "@/utils/format";
import ErrorBoundary from "@/ErrorBoundary";

/**
 * LousaMobile — vista da Lousa (bolhas) no app do colaborador.
 * Regras visuais:
 * - Lousa fica TRAVADA se: não bateu Entrada, está em intervalo, ou já bateu Saída.
 * - Bolhas com priority='horario'/'prioridade' têm cadeado (não dá para reordenar — futuro).
 * - Banner com último ponto registrado entre as bolhas.
 */
export default function LousaMobile({ collaboratorId, onBack, isAdminTest = false, onOpenCTO, onOpenRedeMap }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [openTicket, setOpenTicket] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFlash, setRefreshFlash] = useState(false);
  const [reorderMode, setReorderMode] = useState(false);
  const [orderedIds, setOrderedIds] = useState([]);   // ordem local em modo reorder
  const [dragId, setDragId] = useState(null);
  const [dragOverId, setDragOverId] = useState(null);
  const [perf, setPerf] = useState(null);
  // ── Frota: vistoria semanal obrigatória na primeira bolha do dia ─────────
  const [fleetWarnings, setFleetWarnings] = useState([]);
  const [showInspectionFlow, setShowInspectionFlow] = useState(false);
  const [pendingTicket, setPendingTicket] = useState(null);
  // ── iter189 — Bolha de Odômetro (seg/sab) ──
  const [odomToday, setOdomToday] = useState(null);
  const [showOdomModal, setShowOdomModal] = useState(false);
  const [dashCfg, setDashCfg] = useState({
    show_performance: true, show_achievements: true,
    show_smart_route: true, show_points: true,
    enable_geofence_alerts: true,
  });
  // iter211ae — Refs pra capturar completion_data e lat no escopo do catch
  // (necessário pra enfileirar finalize na outbox quando der erro de rede).
  const lastCompletionDataRef = useRef(null);
  const lastLatRef = useRef({ lat: 0, lng: 0 });
  // Contagem de finalizações pendentes (outbox)
  const [pendingOfflineCount, setPendingOfflineCount] = useState(0);

  // Bootstrap auto-sync da outbox + listener pra atualizar contagem
  useEffect(() => {
    const apiBase = process.env.REACT_APP_BACKEND_URL || "";
    if (apiBase && outbox?.startAutoSync) outbox.startAutoSync(apiBase);
    const refreshCount = async () => {
      try {
        const items = await outbox.listPending(collaboratorId);
        setPendingOfflineCount(items.filter((i) => i.kind === "finalize"
          && (i.status === "pending" || i.status === "failed"
              || i.status === "sending")).length);
      } catch { /* */ }
    };
    refreshCount();
    const unsub = outbox.onChange ? outbox.onChange(refreshCount) : null;
    const t = setInterval(refreshCount, 8000);
    return () => { if (unsub) unsub(); clearInterval(t); };
  }, [collaboratorId]);

  const refresh = useCallback(async () => {
    if (!collaboratorId) return;
    setRefreshing(true);
    try {
      const d = await api.lousaByCollaborator(collaboratorId,
                                                  { adminTest: isAdminTest });
      setData(d);
      // Quando recarrega fora do modo reorder, sincroniza orderedIds
      if (!reorderMode) {
        setOrderedIds((d.tickets || []).map((t) => t.id));
      }
      setRefreshFlash(true);
      setTimeout(() => setRefreshFlash(false), 1200);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setRefreshing(false);
    }
  }, [collaboratorId, reorderMode, isAdminTest]);

  useEffect(() => { refresh(); }, [refresh]);

  // iter189 — busca config de odômetro do dia
  useEffect(() => {
    if (!collaboratorId) return;
    api.fleetOdomTodayPublic(collaboratorId)
      .then((r) => setOdomToday(r))
      .catch(() => setOdomToday(null));
  }, [collaboratorId]);

  // Modo Boss — detecta novos chamados urgentes e alerta com beep + vibração
  const [seenUrgentIds, setSeenUrgentIds] = useState(() => new Set());
  useEffect(() => {
    if (!data?.tickets) return;
    const urgentes = data.tickets.filter(
      (t) => t.priority === "urgente"
              && t.status !== "finalizada" && !t.admin_resolved,
    );
    if (urgentes.length === 0) return;
    const newOnes = urgentes.filter((t) => !seenUrgentIds.has(t.id));
    if (newOnes.length === 0) return;
    // 1ª render: marca como já vistas sem alertar (evita spam ao abrir o app)
    if (seenUrgentIds.size === 0) {
      setSeenUrgentIds(new Set(urgentes.map((t) => t.id)));
      return;
    }
    // Beep + vibração
    try {
      // eslint-disable-next-line no-undef
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        const ctx = new AudioCtx();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = "square"; osc.frequency.value = 880;
        gain.gain.value = 0.18;
        osc.start();
        setTimeout(() => { osc.frequency.value = 660; }, 180);
        setTimeout(() => { osc.stop(); ctx.close(); }, 420);
      }
      if (navigator.vibrate) navigator.vibrate([180, 90, 180, 90, 280]);
    } catch { /* silent */ }
    setSeenUrgentIds(new Set(urgentes.map((t) => t.id)));
  }, [data?.tickets, seenUrgentIds]);

  // Performance KPIs do dia
  useEffect(() => {
    if (!collaboratorId) return undefined;
    let alive = true;
    const load = () => {
      api._client.get(`/lousa/public/tech-performance/${collaboratorId}`)
        .then((r) => { if (alive) setPerf(r.data); })
        .catch(() => {});
    };
    load();
    const t = setInterval(load, 60000); // refresh a cada 1min
    return () => { alive = false; clearInterval(t); };
  }, [collaboratorId]);

  // Dashboard config (toggles do admin)
  useEffect(() => {
    if (!collaboratorId) return undefined;
    let alive = true;
    api._client.get(`/lousa/public/dashboard-config/${collaboratorId}`)
      .then((r) => { if (alive) setDashCfg((c) => ({ ...c, ...r.data })); })
      .catch(() => {});
    return () => { alive = false; };
  }, [collaboratorId]);

  // Geofence ping — envia posição a cada 60s (se admin habilitou)
  useEffect(() => {
    if (!collaboratorId) return undefined;
    if (!dashCfg.enable_geofence_alerts) return undefined;
    if (!navigator.geolocation) return undefined;
    let alive = true;
    const ping = () => {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          if (!alive) return;
          api._client.post("/lousa/public/geofence-ping", {
            collaborator_id: collaboratorId,
            lat: pos.coords.latitude, lng: pos.coords.longitude,
          }).catch(() => {});
        },
        () => {},
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 30000 },
      );
    };
    ping();
    const t = setInterval(ping, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [collaboratorId, dashCfg.enable_geofence_alerts]);

  // --- Reorder helpers (modo "Reordenar") ---
  function isLockedTicket(t) {
    return t.reorder_locked || t.locked || t.priority !== "normal" || ["aberta", "aguardando_atendimento", "finalizada"].includes(t.status);
  }
  function moveTicket(ticketId, delta) {
    setOrderedIds((prev) => {
      const idx = prev.indexOf(ticketId);
      if (idx < 0) return prev;
      const targetIdx = idx + delta;
      if (targetIdx < 0 || targetIdx >= prev.length) return prev;
      // Não atravessar bolhas travadas
      const tickets = data?.tickets || [];
      const targetTicket = tickets.find((t) => t.id === prev[targetIdx]);
      if (!targetTicket || isLockedTicket(targetTicket)) return prev;
      const next = [...prev];
      [next[idx], next[targetIdx]] = [next[targetIdx], next[idx]];
      return next;
    });
  }
  async function saveReorder() {
    if (!data || !orderedIds.length) return;
    setBusy(true); setErr("");
    try {
      const items = orderedIds.map((id, position) => ({ id, position }));
      await api.lousaPublicReorder(collaboratorId, items);
      setReorderMode(false);
      await refresh();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }
  function cancelReorder() {
    setReorderMode(false);
    setOrderedIds((data?.tickets || []).map((t) => t.id));
    setDragId(null); setDragOverId(null);
  }
  function enterReorder() {
    setOrderedIds((data?.tickets || []).map((t) => t.id));
    setReorderMode(true);
  }

  // --- Touch/Mouse drag handlers (HTML5 DnD) ---
  function handleDragStart(id) {
    if (!reorderMode) return;
    const t = (data?.tickets || []).find((x) => x.id === id);
    if (!t || isLockedTicket(t)) return;
    setDragId(id);
  }
  function handleDragOver(e, overId) {
    if (!reorderMode || !dragId || dragId === overId) return;
    e.preventDefault();
    setDragOverId(overId);
  }
  function handleDrop(overId) {
    if (!reorderMode || !dragId) return;
    setOrderedIds((prev) => {
      const fromIdx = prev.indexOf(dragId);
      const toIdx = prev.indexOf(overId);
      if (fromIdx < 0 || toIdx < 0) return prev;
      const targetTicket = (data?.tickets || []).find((t) => t.id === overId);
      if (!targetTicket || isLockedTicket(targetTicket)) return prev;
      const next = [...prev];
      const [moved] = next.splice(fromIdx, 1);
      next.splice(toIdx, 0, moved);
      return next;
    });
    setDragId(null); setDragOverId(null);
  }

  // Helpers Frota — controla "primeira bolha do dia"
  function _todayKey() {
    return `fleet_insp_defer_${collaboratorId}_${new Date().toISOString().slice(0, 10)}`;
  }
  function _isDeferredToday() {
    try { return sessionStorage.getItem(_todayKey()) === "1"; }
    catch { return false; }
  }
  function _markDeferredToday() {
    try { sessionStorage.setItem(_todayKey(), "1"); } catch { /* */ }
  }

  async function handleOpen(ticket) {
    if (ticket.locked) return;
    // ── Verificação de frota: se vistoria pendente, intercepta com modal ──
    // (escolha 2c: soft block — usuário pode adiar pelo dia)
    if (!isAdminTest && !_isDeferredToday()) {
      try {
        const co = await api.fleetCanOperate();
        if (co?.fleet_enabled && co?.warnings?.length) {
          const pendInsp = co.warnings.find(
            (w) => w.code === "inspection_pending" || w.code === "inspection_rejected"
          );
          if (pendInsp) {
            setFleetWarnings(co.warnings);
            setPendingTicket(ticket);
            return; // não abre a bolha ainda; modal vai aparecer
          }
        }
      } catch { /* falha silenciosa — não bloqueia operação */ }
    }
    if (ticket.status === "aberta" || ticket.status === "aguardando_atendimento") {
      setOpenTicket(ticket);
      return;
    }
    setBusy(true); setErr("");
    try {
      await api.lousaPublicOpen(ticket.id, collaboratorId);
      await refresh();
      const fresh = await api.lousaTicket(ticket.id);
      setOpenTicket(fresh);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  async function handleFinalize(ticket, completionData, opts = {}) {
    setBusy(true); setErr("");
    // iter211ae — refs pra capturar dados no escopo do catch (offline queue)
    lastCompletionDataRef.current = completionData;
    try {
      // iter224 — captura GPS com high-accuracy + fallback pra última
      // posição conhecida. Em locais sem sinal (subsolo, mata fechada),
      // o navegador pode demorar muito ou falhar. Aceitamos
      // `maximumAge: 5 min` (posição cacheada serve) e em último caso
      // caímos pro lastLatRef (gravado por um watchPosition em qualquer
      // outra ação prévia). Se ainda não temos NADA, mandamos (0,0)
      // que vira o gatilho do offline queue do iter211ae.
      const lat = await new Promise((res) => {
        if (!navigator.geolocation) {
          return res(lastLatRef.current || { lat: 0, lng: 0 });
        }
        let done = false;
        const finish = (v) => { if (done) return; done = true; res(v); };
        navigator.geolocation.getCurrentPosition(
          (p) => finish({ lat: p.coords.latitude, lng: p.coords.longitude,
                            accuracy: p.coords.accuracy }),
          () => finish(lastLatRef.current?.lat
                          ? { ...lastLatRef.current, _from_cache: true }
                          : { lat: 0, lng: 0 }),
          { enableHighAccuracy: true, timeout: 8000, maximumAge: 300000 },
        );
        setTimeout(() => finish(lastLatRef.current?.lat
                                  ? { ...lastLatRef.current, _from_cache: true }
                                  : { lat: 0, lng: 0 }), 8500);
      });
      lastLatRef.current = lat;
      // iter224 — Sem sinal GPS (0,0): NÃO bate no backend (o
      // geofence iria rejeitar com 400). Enfileira no outbox como se
      // estivesse offline — assim que o GPS voltar, o cron envia.
      if (!lat.lat || !lat.lng) {
        try {
          await outbox.enqueue({
            kind: "finalize",
            endpoint: `/api/lousa/public/tickets/${ticket.id}/finalize`,
            method: "POST",
            body: {
              collaborator_id: collaboratorId,
              completion_data: completionData,
              latitude: 0, longitude: 0,
              outcome: opts.outcome || "sucesso",
              bad_signal_auth_id: opts.bad_signal_auth_id || null,
              _gps_unavailable: true,
            },
            collab_id: collaboratorId,
            collab_name: ticket?.collaborator_name || collaboratorId,
            description: `Finalizar OS ${ticket.id.slice(-6)} — sem GPS (envia quando conectar)`,
          });
          try { clearDraft(ticket.id, collaboratorId); } catch { /* */ }
          setOpenTicket(null);
          setBadSignalAuth(null);
          setErr("");
          setTimeout(() => alert(
            "📡 OS gravada SEM SINAL GPS!\n\n"
            + "Sem GPS no momento. A finalização foi gravada no aparelho "
            + "e será enviada automaticamente quando o GPS voltar.\n\n"
            + "Você pode pegar a próxima OS."
          ), 80);
          await refresh();
          setBusy(false);
          return;
        } catch (qe) {
          // Falhou enfileirar — segue fluxo normal e mostra erro do backend
          console.warn("[lousa/finalize] gps fail+queue fail:", qe);
        }
      }
      const r = await api.lousaPublicFinalize(ticket.id, {
        collaborator_id: collaboratorId,
        completion_data: completionData,
        latitude: lat.lat, longitude: lat.lng,
        outcome: opts.outcome || "sucesso",
        bad_signal_auth_id: opts.bad_signal_auth_id || null,
      });
      // Resposta especial: bloqueio "sem execução" → gestor precisa contatar
      if (r?.blocked_close && r?.manager_callback_required) {
        setBlockedCloseInfo({
          ticket,
          message: r.message,
          callback_request_id: r.callback_request_id,
        });
        // NÃO fecha o painel — técnico precisa ver o aviso
        return;
      }
      setOpenTicket(null);
      setBadSignalAuth(null);
      // iter211ad — Limpa draft local da OS finalizada com sucesso
      try { clearDraft(ticket.id, collaboratorId); } catch { /* */ }
      await refresh();
    } catch (e) {
      // Backend 403 com needs_bad_signal_auth → abre modal de espera
      const detail = e?.response?.data?.detail;
      if (e?.response?.status === 403
            && detail?.code === "needs_bad_signal_auth") {
        setBadSignalAuth({
          request_id: detail.request_id,
          threshold: detail.threshold,
          sinal: detail.sinal,
          ticket,
          completionData,
          status: "pending",
        });
        setErr("");
      } else if (e?.response?.status === 400
                  && detail?.code === "OUTSIDE_GEOFENCE") {
        // iter211bj — Técnico fora do raio de 100m do endereço da OS
        const msg = detail.message
          || `Você está a ${detail.distance_m}m da OS (limite ${detail.radius_m}m).`;
        setErr(msg);
        setTimeout(() => alert(
          "❌ FORA DA ÁREA DO SERVIÇO\n\n" + msg
        ), 30);
      } else {
        // iter211g — mensagem específica para Network Error / timeout
        const msg = (e?.message || "").toLowerCase();
        const code = e?.code || "";
        const isNetwork = !e?.response
          && (code === "ECONNABORTED" || msg.includes("network"));
        if (isNetwork) {
          // iter211ae — Enfileira finalize na outbox offline e libera UX
          try {
            const completionData = lastCompletionDataRef.current;
            await outbox.enqueue({
              kind: "finalize",
              endpoint: `/api/lousa/public/tickets/${ticket.id}/finalize`,
              method: "POST",
              body: {
                collaborator_id: collaboratorId,
                completion_data: completionData,
                latitude: lastLatRef.current?.lat || 0,
                longitude: lastLatRef.current?.lng || 0,
                outcome: opts.outcome || "sucesso",
                bad_signal_auth_id: opts.bad_signal_auth_id || null,
              },
              collab_id: collaboratorId,
              collab_name: ticket?.collaborator_name || collaboratorId,
              description: `Finalizar OS ${ticket.id.slice(-6)} — ${(ticket.client_snapshot?.name || "").slice(0, 40)}`,
            });
            // Limpa draft local pra técnico não ver "Rascunho salvo" depois
            try { clearDraft(ticket.id, collaboratorId); } catch { /* */ }
            setOpenTicket(null);
            setBadSignalAuth(null);
            setErr("");
            setTimeout(() => alert(
              "✅ OS finalizada localmente!\n\n"
              + "Sua finalização foi gravada no aparelho.\n"
              + "Assim que a internet voltar, o app envia automaticamente "
              + "pro servidor. Você pode pegar a próxima OS."
            ), 100);
            await refresh();
          } catch (queueErr) {
            setErr(
              "Conexão fraca e não foi possível salvar localmente. "
              + "Tente novamente em alguns segundos."
            );
          }
        } else {
          setErr(typeof detail === "string"
                  ? detail
                  : (detail?.message || e.message));
        }
      }
    }
    setBusy(false);
  }

  // Threshold do bad-signal warning — busca da config CENTRAL_ONT
  // (admin pode ter mudado pra -25/-30 etc). Best-effort: -27 default.
  const [badSignalThreshold, setBadSignalThreshold] = useState(-27);
  useEffect(() => {
    let alive = true;
    api._client.get("/lousa/central-ont/settings")
      .then((r) => alive && setBadSignalThreshold(
        Number(r.data?.bad_signal_threshold ?? -27)))
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // Estado: aguardando autorização do gestor pra fechar com sinal ruim
  const [badSignalAuth, setBadSignalAuth] = useState(null);
  const [blockedCloseInfo, setBlockedCloseInfo] = useState(null);
  // Poll: a cada 4s checa status da request
  useEffect(() => {
    if (!badSignalAuth?.request_id) return undefined;
    const t = setInterval(async () => {
      try {
        const r = await api._client.get(
          `/lousa/public/bad-signal-auth/${badSignalAuth.request_id}`,
        ).then((x) => x.data);
        if (r.status === "approved") {
          clearInterval(t);
          // Re-tenta o finalize com o auth id
          await handleFinalize(
            badSignalAuth.ticket,
            badSignalAuth.completionData,
            { bad_signal_auth_id: badSignalAuth.request_id },
          );
        } else if (r.status === "rejected" || r.status === "expired") {
          clearInterval(t);
          setBadSignalAuth((b) => b ? { ...b, status: r.status } : b);
        }
      } catch { /* silent */ }
    }, 4000);
    return () => clearInterval(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [badSignalAuth?.request_id]);

  if (!data) {
    return (
      <div data-testid="lousa-loading" style={{ padding: 30, textAlign: "center", color: "#64748b" }}>
        Carregando lousa...
      </div>
    );
  }

  // Vistoria semanal de Frota — modal full-screen na primeira bolha do dia
  if (showInspectionFlow) {
    return (
      <div data-testid="fleet-inspection-overlay" style={{
        minHeight: "100vh", background: "#f8fafc",
      }}>
        <WeeklyInspectionFlow
          onClose={() => {
            setShowInspectionFlow(false);
            // após enviar vistoria, abre o ticket que estava pendente
            if (pendingTicket) {
              const t = pendingTicket;
              setPendingTicket(null);
              setFleetWarnings([]);
              setTimeout(() => handleOpen(t), 100);
            }
          }}
          onDefer={() => {
            _markDeferredToday();
            setShowInspectionFlow(false);
            if (pendingTicket) {
              const t = pendingTicket;
              setPendingTicket(null);
              setFleetWarnings([]);
              setTimeout(() => handleOpen(t), 100);
            }
          }}
        />
      </div>
    );
  }

  // Modal soft-block: avisa vistoria pendente antes de abrir 1ª bolha do dia
  if (pendingTicket && fleetWarnings.length > 0) {
    const w = fleetWarnings[0];
    return (
      <div data-testid="fleet-inspection-modal" style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.7)",
        zIndex: 9000, display: "flex", alignItems: "center",
        justifyContent: "center", padding: 16,
      }}>
        <div style={{
          background: "white", borderRadius: 16, padding: 24,
          width: "100%", maxWidth: 480, textAlign: "center",
        }}>
          <div style={{ fontSize: 52 }}>🚗</div>
          <h2 style={{ fontSize: 19, fontWeight: 800, margin: "12px 0 8px",
                          color: "#0f172a" }}>
            Vistoria semanal do veículo
          </h2>
          <p style={{ color: "#475569", fontSize: 14, lineHeight: 1.5, margin: 0 }}>
            {w.msg || "Faça a vistoria antes de iniciar suas OS de hoje."}
            {" "}Leva ~3 minutos (5 fotos + KM).
          </p>
          <div style={{ marginTop: 18, display: "flex", gap: 8,
                          flexDirection: "column" }}>
            <button
              data-testid="fleet-start-inspection-btn"
              onClick={() => setShowInspectionFlow(true)}
              style={{
                padding: "13px 20px", background: "#0ea5e9", color: "white",
                border: "none", borderRadius: 10, fontWeight: 700,
                fontSize: 15, cursor: "pointer",
              }}>
              📸 Fazer vistoria agora
            </button>
            <button
              data-testid="fleet-defer-inspection-btn"
              onClick={() => {
                _markDeferredToday();
                const t = pendingTicket;
                setPendingTicket(null);
                setFleetWarnings([]);
                setTimeout(() => handleOpen(t), 80);
              }}
              style={{
                padding: "11px 18px", background: "#f1f5f9",
                color: "#475569", border: "1px solid #e2e8f0",
                borderRadius: 10, fontWeight: 600, fontSize: 13,
                cursor: "pointer",
              }}>
              Adiar até amanhã
            </button>
          </div>
          <p style={{ fontSize: 11, color: "#94a3b8", marginTop: 12 }}>
            Adiar não bloqueia sua operação — é apenas um lembrete.
          </p>
        </div>
      </div>
    );
  }

  if (openTicket) {
    return (
      <>
      <TicketDetail
        ticket={openTicket}
        onClose={() => setOpenTicket(null)}
        onFinalize={(cd, opts) => handleFinalize(openTicket, cd, opts || {})}
        badSignalThreshold={badSignalThreshold}
        collaboratorId={collaboratorId}
        collaboratorName={data?.collaborator?.name || ""}
        isAdminTest={isAdminTest}
        onOpenCTO={onOpenCTO}
        onOpenRedeMap={onOpenRedeMap}
        pendingOfflineCount={pendingOfflineCount}
        onRefresh={async () => {
          try {
            const fresh = await api.lousaTicket(openTicket.id);
            setOpenTicket(fresh);
            await refresh();
          } catch (e) { setErr(e?.response?.data?.detail || e.message); }
        }}
        busy={busy}
        err={err}
      />
      {badSignalAuth && (
        <BadSignalAuthWaitModal
          state={badSignalAuth}
          onClose={() => setBadSignalAuth(null)}
        />
      )}
      {blockedCloseInfo && (
        <BlockedCloseModal
          info={blockedCloseInfo}
          onClose={() => {
            setBlockedCloseInfo(null);
            setOpenTicket(null);
            refresh();
          }}
        />
      )}
      </>
    );
  }

  const state = (data && typeof data.clock_state === "object" && data.clock_state)
                  ? data.clock_state : { records: [] };
  const unlocked = !!data?.lousa_unlocked;
  const records = Array.isArray(state.records) ? state.records : [];
  const lastEvent = records.length ? records[records.length - 1] : null;

  // Bolhas só aparecem após bater Entrada (identificação no sistema)
  if (data.needs_clock_in) {
    return (
      <div data-testid="lousa-mobile-needs-clockin">
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Button variant="soft" onClick={onBack} data-testid="lousa-back-btn">← Voltar</Button>
          <Button
            variant="soft"
            onClick={refresh}
            disabled={refreshing}
            data-testid="lousa-refresh-btn"
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
        <h2 style={{ marginTop: 14, marginBottom: 4 }}>📋 Lousa de Serviços</h2>
        <div style={{
          marginTop: 24, padding: 30, textAlign: "center",
          background: "linear-gradient(135deg, #fef3c7, #fde68a)",
          border: "2px dashed #f59e0b", borderRadius: 22,
        }}>
          <div style={{ fontSize: 60 }}>🔒</div>
          <h3 style={{ margin: "12px 0 4px", color: "#78350f" }}>Bata o ponto de Entrada</h3>
          <p style={{ color: "#92400e", fontSize: 13, lineHeight: 1.5 }}>
            Suas notas de serviço só serão liberadas após você se identificar no sistema com o ponto de Entrada.
          </p>
          <Button onClick={onBack} style={{ marginTop: 12 }} data-testid="go-clock-btn">
            Ir para Bater Ponto
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="lousa-mobile">
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button variant="soft" onClick={onBack} data-testid="lousa-back-btn">← Voltar</Button>
        <Button
          variant="soft"
          onClick={refresh}
          disabled={busy || refreshing || reorderMode}
          data-testid="lousa-refresh-btn"
          style={{
            background: refreshFlash ? "#dcfce7" : refreshing ? "#fef9c3" : "#dbeafe",
            color: refreshFlash ? "#166534" : refreshing ? "#92400e" : "#1e40af",
            border: `1px solid ${refreshFlash ? "#86efac" : refreshing ? "#fde68a" : "#93c5fd"}`,
            transition: "background-color .25s",
          }}
        >
          {refreshing ? "⏳ Atualizando..." : refreshFlash ? "✓ Atualizado" : "🔄 Atualizar"}
        </Button>
        {!reorderMode && Array.isArray(data?.tickets) && data.tickets.length > 1 && unlocked && (
          <Button
            variant="soft"
            onClick={enterReorder}
            disabled={busy}
            data-testid="lousa-reorder-toggle"
            style={{ background: "#ede9fe", color: "#5b21b6", border: "1px solid #c4b5fd", fontWeight: 700 }}
          >
            ↕ Reordenar
          </Button>
        )}
      </div>
      <h2 style={{ marginTop: 14, marginBottom: 4 }}>📋 Lousa de Serviços</h2>
      <p style={{ color: "#64748b", fontSize: 12, margin: 0 }}>
        {(Array.isArray(data?.tickets) ? data.tickets.length : 0)} serviço(s) — {unlocked ? "🔓 lousa liberada" : "🔒 lousa travada"}
        {reorderMode && <span style={{ marginLeft: 8, color: "#5b21b6", fontWeight: 700 }}>· ↕ modo reordenar</span>}
      </p>

      {/* iter211af — Cards wrappados em ErrorBoundary individuais pra que
          falhas isoladas (perf, conquistas, rota IA) não derrubem a Lousa. */}
      {dashCfg.show_performance && (
        <ErrorBoundary name="lousa-perf-card" variant="card"
          fallbackText="Não foi possível carregar seu painel de desempenho.">
          <PerformanceCard perf={perf} showPoints={dashCfg.show_points} />
        </ErrorBoundary>
      )}
      {dashCfg.show_achievements && (
        <ErrorBoundary name="lousa-achievements-card" variant="card"
          fallbackText="Não foi possível carregar suas conquistas.">
          <AchievementsCard collaboratorId={collaboratorId} compact />
        </ErrorBoundary>
      )}
      {dashCfg.show_smart_route && (
        <ErrorBoundary name="lousa-smart-route-card" variant="card"
          fallbackText="Não foi possível calcular a rota inteligente.">
          <SmartRouteCard collaboratorId={collaboratorId} onApplied={refresh}
                           enabled={Array.isArray(data?.tickets)
                             && data.tickets.some((t) => t?.priority === "normal")} />
        </ErrorBoundary>
      )}

      {reorderMode && (
        <div data-testid="lousa-reorder-bar" style={{
          marginTop: 12, padding: "10px 14px",
          background: "linear-gradient(90deg, #ede9fe, #ddd6fe)",
          border: "1px solid #c4b5fd", borderRadius: 14,
          display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap",
        }}>
          <div style={{ fontSize: 12, color: "#4c1d95", fontWeight: 600 }}>
            Use ↑/↓ ou arraste para reordenar. 🔒 indica bolhas travadas.
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <Button
              variant="soft"
              onClick={cancelReorder}
              disabled={busy}
              data-testid="lousa-reorder-cancel"
              style={{ background: "white", color: "#475569", border: "1px solid #cbd5e1" }}
            >Cancelar</Button>
            <Button
              onClick={saveReorder}
              disabled={busy}
              data-testid="lousa-reorder-save"
              style={{ background: "#7c3aed", color: "white", fontWeight: 700 }}
            >{busy ? "Salvando..." : "✓ Salvar"}</Button>
          </div>
        </div>
      )}

      {!state.has_entrada && data.clock_in_enabled !== false && (
        <Banner color="#fef3c7" border="#f59e0b" icon="⚠️" text="Bata o ponto de Entrada para liberar a lousa." />
      )}
      {state.in_intervalo && data.clock_in_enabled !== false && (
        <Banner color="#dbeafe" border="#3b82f6" icon="🍽️" text="Você está em intervalo de almoço. A lousa abrirá após Fim intervalo." />
      )}
      {state.ended_day && data.clock_in_enabled !== false && (
        <Banner color="#e0e7ff" border="#6366f1" icon="🏁" text="Você já bateu Saída. Boa noite!" />
      )}
      {lastEvent && state.has_entrada && !reorderMode && data.clock_in_enabled !== false && (
        <Banner color="#dcfce7" border="#10b981" icon="✓" text={`Último ponto: ${lastEvent.type} às ${lastEvent.time}`} />
      )}

      {err && <Banner color="#fee2e2" border="#dc2626" icon="!" text={err} />}

      <div style={{ marginTop: 14 }}>
        {(!Array.isArray(data?.tickets) || data.tickets.length === 0) && (
          <div style={{ background: "white", border: "1px dashed #cbd5e1", borderRadius: 16, padding: 20, textAlign: "center", color: "#94a3b8" }}>
            Nenhuma nota atribuída ainda.
          </div>
        )}
        {/* iter189 — Bolha de odômetro de INÍCIO (segunda-feira) */}
        {odomToday?.show && odomToday.kind === "start" && (
          <OdometerBubble odom={odomToday}
            onClick={() => setShowOdomModal(true)} />
        )}
        {(reorderMode
          ? orderedIds.map((id) => (data?.tickets || []).find((t) => t.id === id)).filter(Boolean)
          : (data?.tickets || [])
        ).map((t, idx, arr) => (
          <React.Fragment key={t.id}>
            {idx > 0 && lastEvent && idx === Math.floor(arr.length / 2) && !reorderMode && (
              <BetweenBubblesInfo records={records} />
            )}
            {/* iter211af — Cada bolha em seu próprio ErrorBoundary pra que um
                ticket com dados malformados (ex: client_snapshot=null vindo do
                Atlaz) não derrube a lousa inteira. */}
            <ErrorBoundary name={`bubble-${t.id}`} variant="card"
              fallbackText={`OS ${String(t.id || "").slice(-6)} com dados inválidos — pule esta e continue. (Avise o gestor)`}>
              <Bubble
                ticket={t}
                onClick={() => handleOpen(t)}
                disabled={busy}
                reorderMode={reorderMode}
                isFirst={idx === 0}
                isLast={idx === arr.length - 1}
                locked={isLockedTicket(t)}
                onMoveUp={() => moveTicket(t.id, -1)}
                onMoveDown={() => moveTicket(t.id, 1)}
                isDragging={dragId === t.id}
                isDragOver={dragOverId === t.id}
                onDragStart={() => handleDragStart(t.id)}
                onDragOver={(e) => handleDragOver(e, t.id)}
                onDrop={() => handleDrop(t.id)}
                onDragEnd={() => { setDragId(null); setDragOverId(null); }}
              />
            </ErrorBoundary>
          </React.Fragment>
        ))}
        {/* iter189 — Bolha de odômetro de FIM (sábado) */}
        {odomToday?.show && odomToday.kind === "end" && (
          <OdometerBubble odom={odomToday}
            onClick={() => setShowOdomModal(true)} />
        )}
      </div>

      {/* iter189 — Modal de captura do odômetro */}
      {showOdomModal && (
        <OdometerCaptureModal
          collaboratorId={collaboratorId}
          odom={odomToday}
          onClose={() => setShowOdomModal(false)}
          onSaved={(r) => {
            setOdomToday((prev) => ({ ...prev,
              already_done_today: true, current_reading: r }));
            setShowOdomModal(false);
          }} />
      )}

      {/* Entrada de cadastro de CTO foi FUNDIDA no Step 2 da finalização
          (Vincular cliente à CTO opcional). Por isso, sem FAB separado. */}
    </div>
  );
}

function Banner({ color, border, icon, text }) {
  return (
    <div style={{
      background: color, border: `1px solid ${border}`, borderRadius: 14,
      padding: "10px 14px", marginTop: 12, display: "flex", gap: 10, alignItems: "center",
      fontSize: 13, fontWeight: 600,
    }}>
      <span style={{ fontSize: 18 }}>{icon}</span>
      <span>{text}</span>
    </div>
  );
}

/* CopyPill — pill clicável que copia o valor pro clipboard com 1 toque.
 * Mostra feedback "✓ Copiado" por 1.2s. Funciona em iOS Safari, Android
 * Chrome e desktop. Fallback usa document.execCommand pra contextos http. */
function CopyPill({ label, value, testid, mono, grow }) {
  const [copied, setCopied] = useState(false);
  async function doCopy(e) {
    e.preventDefault(); e.stopPropagation();
    const txt = String(value || "");
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(txt);
      } else {
        const ta = document.createElement("textarea");
        ta.value = txt; ta.setAttribute("readonly", "");
        ta.style.position = "absolute"; ta.style.left = "-9999px";
        document.body.appendChild(ta); ta.select();
        document.execCommand("copy"); document.body.removeChild(ta);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch { /* noop */ }
  }
  return (
    <button
      type="button"
      data-testid={testid}
      onClick={doCopy}
      title={`Toque para copiar ${label}`}
      style={{
        flex: grow ? "1 1 100%" : "0 0 auto",
        padding: "5px 10px", borderRadius: 8,
        background: copied
          ? "rgba(34,197,94,0.95)"
          : "rgba(255,255,255,0.18)",
        border: "1px solid rgba(255,255,255,0.35)",
        color: "white",
        fontSize: 12, fontWeight: 700,
        cursor: "pointer", textAlign: "left",
        display: "inline-flex", alignItems: "center", gap: 6,
        transition: "background 180ms",
        fontFamily: mono ? "monospace" : "inherit",
        letterSpacing: mono ? 0.4 : 0,
        WebkitTapHighlightColor: "transparent",
      }}>
      <span style={{ opacity: 0.85, fontWeight: 600,
                        fontFamily: "inherit", letterSpacing: 0 }}>
        {label}:
      </span>
      <span style={{ flex: 1 }}>{value}</span>
      <span style={{ opacity: 0.85, fontSize: 10 }}>
        {copied ? "✓ copiado" : "📋"}
      </span>
    </button>
  );
}

function BetweenBubblesInfo({ records }) {
  return (
    <div data-testid="lousa-records-strip" style={{
      margin: "8px 0", padding: "8px 12px",
      background: "linear-gradient(90deg, #f1f5f9, #e2e8f0)",
      borderRadius: 12, fontSize: 11, color: "#475569",
      display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center",
    }}>
      {records.map((r, i) => (
        <span key={i} style={{ background: "white", padding: "2px 8px", borderRadius: 8, border: "1px solid #cbd5e1" }}>
          {r.type === "Entrada" ? "🚪" : r.type === "Início intervalo" ? "🍽️" : r.type === "Fim intervalo" ? "🔄" : "🏁"} {r.time}
        </span>
      ))}
    </div>
  );
}

const TYPE_ICONS_M = {
  instalacao: "🔧", retirada: "📦", visita_tecnica: "🛠️", manutencao: "🔩",
  upgrade: "⬆️", downgrade: "⬇️", troca_endereco: "🏠",
  troca_titularidade: "👤", cancelamento: "🚫", outros: "📋", venda: "💼",
};

function Bubble({ ticket, onClick, disabled, reorderMode, isFirst, isLast, locked,
                 onMoveUp, onMoveDown, isDragging, isDragOver,
                 onDragStart, onDragOver, onDrop, onDragEnd }) {
  const isResolved = ticket.admin_resolved || ticket.status === "finalizada";
  const isOpen = ticket.status === "aberta" || ticket.status === "aguardando_atendimento";
  // iter211af — Guards defensivos: tickets vindos do Atlaz ou de seeds antigos
  // podem ter `client_snapshot=null` ou campos faltando. Renderização nunca pode
  // crashar — usa fallback "—".
  const cs = (ticket && typeof ticket.client_snapshot === "object"
              && ticket.client_snapshot) || {};
  const csName = typeof cs.name === "string" ? cs.name : "";
  const csNeighborhood = typeof cs.neighborhood === "string" ? cs.neighborhood : "";
  const csRelato = typeof cs.relato === "string" ? cs.relato : "";
  const csPhone = typeof cs.phone === "string" ? cs.phone : "";
  const csAddress = typeof cs.address === "string" ? cs.address : "";
  const ticketType = typeof ticket?.type === "string" ? ticket.type : "";
  const schedTime = typeof ticket?.scheduled_time === "string"
                    && ticket.scheduled_time.length >= 16
                      ? ticket.scheduled_time : "";
  const priorityColors = {
    urgente: {
      bg: "linear-gradient(135deg,#fee2e2,#fecaca)",
      accent: "#dc2626", border: "#dc2626", text: "#7f1d1d",
      label: "URGENTE · BOSS", icon: "🚨",
    },
    prioridade: {
      bg: "linear-gradient(135deg,#fff5f5,#ffe4e6)",
      accent: "#e11d48", border: "#fecdd3", text: "#9f1239",
      label: "PRIORIDADE", icon: "🚨",
    },
    horario: {
      bg: "linear-gradient(135deg,#fffbeb,#fef3c7)",
      accent: "#d97706", border: "#fde68a", text: "#78350f",
      label: "HORÁRIO", icon: "⏰",
    },
    normal: {
      bg: "white", accent: "#0ea5e9", border: "#e2e8f0",
      text: "#0f172a", label: "", icon: "",
    },
  };
  const c = priorityColors[ticket.priority] || priorityColors.normal;
  const opacity = ticket.locked || disabled ? 0.55 : 1;
  const typeIcon = TYPE_ICONS_M[ticketType] || "📋";
  const typeLabel = ticketType.replace(/_/g, " ");
  const tooltipText = [
    `${typeLabel.toUpperCase()}`,
    `Cliente: ${fmtName(csName)}`,
    csPhone ? `Tel: ${fmtPhone(csPhone)}` : null,
    csAddress ? `End.: ${fmtAddress(csAddress)}` : null,
    csNeighborhood ? `Bairro: ${safeText(csNeighborhood)}` : null,
    schedTime ? `Horário: ${schedTime.substr(11, 5)}` : null,
    csRelato ? `\nRelato:\n${fmtRelato(csRelato)}` : null,
  ].filter(Boolean).join("\n");

  // Em modo reorder, a bolha vira um container drag-handle (não clica para abrir)
  if (reorderMode) {
    const draggableHere = !locked;
    return (
      <div
        data-testid={`bubble-reorder-${ticket.id}`}
        draggable={draggableHere}
        onDragStart={draggableHere ? onDragStart : undefined}
        onDragOver={onDragOver}
        onDrop={onDrop}
        onDragEnd={onDragEnd}
        style={{
          width: "100%", padding: 12, borderRadius: 22,
          background: isDragOver ? "#ede9fe" : (isOpen ? "#dcfce7" : c.bg),
          border: `2px ${isDragging ? "dashed" : "solid"} ${isDragOver ? "#7c3aed" : (isOpen ? "#10b981" : c.border)}`,
          marginBottom: 10,
          cursor: draggableHere ? "grab" : "not-allowed",
          opacity: isDragging ? 0.55 : opacity,
          color: c.text, position: "relative",
          boxShadow: isDragOver ? "0 8px 22px rgba(124,58,237,.25)" : "0 4px 10px rgba(15,23,42,.05)",
          touchAction: "none",
          display: "flex", gap: 10, alignItems: "center",
          transition: "all 0.18s",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4, flexShrink: 0 }}>
          <button
            data-testid={`bubble-up-${ticket.id}`}
            onClick={onMoveUp}
            disabled={isFirst || locked}
            title="Mover para cima"
            style={reorderBtnStyle(isFirst || locked)}
          >▲</button>
          <button
            data-testid={`bubble-down-${ticket.id}`}
            onClick={onMoveDown}
            disabled={isLast || locked}
            title="Mover para baixo"
            style={reorderBtnStyle(isLast || locked)}
          >▼</button>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          {locked ? (
            <span style={{ position: "absolute", top: 8, right: 10, fontSize: 16 }} title="Bolha travada — não pode ser movida">🔒</span>
          ) : (
            <span style={{ position: "absolute", top: 8, right: 10, fontSize: 14, color: "#94a3b8" }} title="Arraste para reordenar">⋮⋮</span>
          )}
          {c.label && (
            <div style={{
              fontSize: 9, fontWeight: 900, letterSpacing: 0.5, marginBottom: 4,
              padding: "2px 7px", borderRadius: 999, background: c.accent, color: "white",
              display: "inline-block",
            }}>{c.icon} {c.label}</div>
          )}
          <div style={{ fontSize: 14, fontWeight: 800 }}>{fmtName(csName)}</div>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
            {ticketType.toUpperCase()} · {safeText(csNeighborhood)}
          </div>
        </div>
      </div>
    );
  }

  return (
    <button
      onClick={onClick}
      disabled={ticket.locked || disabled || isResolved}
      data-testid={`bubble-${ticket.id}`}
      title={tooltipText}
      style={{
        width: "100%", textAlign: "left",
        padding: "12px 14px 12px 16px",
        borderRadius: 18,
        background: isOpen ? "linear-gradient(135deg,#ecfdf5,#d1fae5)" : c.bg,
        border: `${ticket.priority === "urgente" ? 2 : 1}px solid ${isOpen ? "#10b981" : c.border}`,
        marginBottom: 10,
        cursor: ticket.locked || isResolved ? "not-allowed" : "pointer",
        opacity, color: c.text, position: "relative",
        boxShadow: isOpen
          ? "0 6px 18px rgba(16,185,129,.20)"
          : (ticket.priority === "urgente"
              ? "0 0 0 4px rgba(220,38,38,0.18), 0 8px 22px rgba(220,38,38,.30)"
              : "0 1px 3px rgba(15,23,42,.06), 0 2px 6px rgba(15,23,42,.04)"),
        transition: "transform .15s, box-shadow .2s",
        overflow: "hidden",
        animation: (ticket.priority === "urgente" && !isResolved)
          ? "boss-mode-pulse 1.6s ease-in-out infinite" : "none",
      }}
    >
      {/* Faixa lateral colorida */}
      {ticket.priority !== "normal" && (
        <span aria-hidden style={{
          position: "absolute", left: 0, top: 0, bottom: 0,
          width: 5, background: c.accent, borderRadius: "18px 0 0 18px",
        }} />
      )}

      {ticket.locked && !isOpen && (
        <span style={{ position: "absolute", top: 10, right: 12, fontSize: 18 }}>🔒</span>
      )}

      {/* Header: badge + horário */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
        {c.label && (
          <span style={{
            fontSize: 9, fontWeight: 900, letterSpacing: 0.5,
            padding: "2px 8px", borderRadius: 999,
            background: c.accent, color: "white",
          }}>{c.icon} {c.label}</span>
        )}
        {schedTime && (
          <span style={{
            fontSize: 10, fontWeight: 800, color: "#475569",
            background: "#f1f5f9", padding: "2px 7px", borderRadius: 999,
            border: "1px solid #e2e8f0",
          }}>{schedTime.substr(11, 5)}</span>
        )}
      </div>

      {/* Body: ícone tipo + cliente + meta */}
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <div aria-hidden style={{
          width: 40, height: 40, borderRadius: 12,
          background: ticket.priority === "normal" ? "#f1f5f9" : "rgba(255,255,255,.85)",
          border: `1px solid ${c.border}`,
          display: "grid", placeItems: "center",
          fontSize: 20, flexShrink: 0,
        }}>{typeIcon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 14.5, fontWeight: 800, lineHeight: 1.2,
            color: c.text, letterSpacing: -0.1,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>{fmtName(csName)}</div>
          <div style={{
            fontSize: 11, color: "#64748b", marginTop: 2,
            textTransform: "uppercase", letterSpacing: 0.4,
            fontWeight: 700,
          }}>{typeLabel}</div>
          {csNeighborhood && (
            <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 1 }}>
              📍 {safeText(csNeighborhood)}
            </div>
          )}
        </div>
      </div>

      {/* SINAL SMARTOLT (pill compacto) */}
      {ticket.live_signal && (
        <div
          data-testid={`signal-pill-mobile-${ticket.id}`}
          style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            marginTop: 6, padding: "3px 9px", borderRadius: 999,
            fontSize: 11, fontWeight: 800, fontFamily: "monospace",
            border: "1px solid",
            ...(() => {
              // iter182 — 5 faixas (excellent/good/warn/critical/bad)
              const q = styleForQuality(ticket.live_signal.quality);
              return { background: q.bg, color: q.fg, borderColor: q.border };
            })(),
          }}
        >
          📶 {(() => {
            // iter211af — guard: rx_dbm pode vir como string ("-25") ou null
            const rx = ticket.live_signal.rx_dbm;
            const n = typeof rx === "number" ? rx
                    : (typeof rx === "string" && rx.trim() !== "" && !isNaN(Number(rx)))
                      ? Number(rx) : null;
            return n != null ? `${n.toFixed(1)} dBm` : "—";
          })()}
          {ticket.live_signal.status === "Online" ? "🟢" : ticket.live_signal.status ? "🔴" : ""}
        </div>
      )}

      {/* Relato em footer separado — toque para copiar texto completo */}
      {csRelato && (
        <button
          type="button"
          data-testid={`bubble-relato-copy-${ticket.id}`}
          onClick={async (e) => {
            e.stopPropagation();
            const btn = e.currentTarget;
            try {
              const txt = String(csRelato || "");
              if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(txt);
              } else {
                const ta = document.createElement("textarea");
                ta.value = txt; document.body.appendChild(ta);
                ta.select(); document.execCommand("copy");
                document.body.removeChild(ta);
              }
              if (btn) btn.dataset.copied = "1";
              setTimeout(() => { if (btn) delete btn.dataset.copied; }, 1200);
            } catch { /* noop */ }
          }}
          style={{
            background: "transparent", border: 0, padding: 0,
            width: "100%", textAlign: "left",
            fontSize: 11.5, color: "#475569", marginTop: 8,
            paddingTop: 6, borderTop: "1px dashed rgba(15,23,42,.08)",
            lineHeight: 1.4, cursor: "pointer",
            fontFamily: "inherit",
            WebkitTapHighlightColor: "transparent",
          }}
          title="Toque para copiar o relato">
          <span style={{ opacity: 0.55, fontSize: 10, fontWeight: 700,
                            display: "block", marginBottom: 2,
                            letterSpacing: 0.5, textTransform: "uppercase" }}>
            📋 Relato · toque p/ copiar
          </span>
          {csRelato.length > 90
            ? csRelato.substring(0, 90) + "…"
            : csRelato}
        </button>
      )}

      {/* Card "Vínculo de rede" — aparece quando o cliente já está vinculado
          a uma CTO (porta OLT, VLAN, número da CTO + SN/MAC em caso de troca) */}
      {(() => {
        const nv = ticket.client_snapshot?.network_link
                    || ticket.network_link
                    || ticket.client_snapshot?.cto_link
                    || null;
        const liveOlt = ticket.live_signal || null;
        const oltPort = nv?.olt_port_id || liveOlt?.olt_port_id
                          || liveOlt?.port || null;
        const vlan = nv?.vlan || liveOlt?.vlan || null;
        const ctoNumber = nv?.cto_number || nv?.cto_name || null;
        const sn = nv?.sn || liveOlt?.sn || null;
        const mac = nv?.mac || liveOlt?.mac || null;
        if (!oltPort && !vlan && !ctoNumber && !sn && !mac) return null;
        const isSwap = ticket.type === "troca" || ticket.type === "troca_endereco";
        return (
          <div data-testid="network-link-card" style={{
            marginTop: 8, padding: "10px 12px", borderRadius: 12,
            background: "linear-gradient(135deg,#0ea5e9 0%,#2563eb 100%)",
            color: "white",
            boxShadow: "0 2px 6px rgba(37,99,235,.25)",
          }}>
            <div style={{ fontSize: 10, fontWeight: 800,
                              letterSpacing: 0.8, opacity: 0.9,
                              textTransform: "uppercase",
                              marginBottom: 6 }}>
              🔗 Vínculo de rede · <span style={{ opacity: 0.7,
                  fontWeight: 600, textTransform: "none" }}>toque p/ copiar</span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {oltPort && (
                <CopyPill testid="nl-olt-port"
                           label="Porta OLT" value={String(oltPort)} />
              )}
              {vlan && (
                <CopyPill testid="nl-vlan"
                           label="VLAN" value={String(vlan)} />
              )}
              {ctoNumber && (
                <CopyPill testid="nl-cto"
                           label="CTO" value={String(ctoNumber)} grow />
              )}
              {(isSwap || sn) && sn && (
                <CopyPill testid="nl-sn" label="SN"
                           value={String(sn)} mono grow />
              )}
              {(isSwap || mac) && mac && (
                <CopyPill testid="nl-mac" label="MAC"
                           value={String(mac)} mono grow />
              )}
            </div>
          </div>
        );
      })()}

      {isResolved && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#16a34a", fontWeight: 700 }}>
          ✓ {ticket.status === "finalizada" ? "Finalizada" : ticket.admin_action || "Encerrada"}
        </div>
      )}
      {isOpen && (
        <div style={{
          marginTop: 8, fontSize: 11, color: "#065f46", fontWeight: 800,
          letterSpacing: 0.4, textTransform: "uppercase",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <span style={{
            width: 8, height: 8, borderRadius: "50%", background: "#10b981",
            boxShadow: "0 0 0 3px rgba(16,185,129,.25)",
            animation: "pulse 1.6s ease-in-out infinite",
          }} />
          Em andamento — toque para detalhes
        </div>
      )}
    </button>
  );
}


function SmartRouteCard({ collaboratorId, enabled, onApplied }) {
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");

  async function fetchOptimized(apply) {
    if (!enabled || !collaboratorId) return;
    setError("");
    setBusy(true);
    try {
      const pos = await new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
          reject(new Error("Geolocalização não disponível neste dispositivo."));
          return;
        }
        navigator.geolocation.getCurrentPosition(
          (p) => resolve(p),
          (e) => reject(new Error(e.message || "Permissão negada")),
          { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 },
        );
      });
      const { latitude, longitude } = pos.coords;
      const r = await api._client.post(
        "/lousa/public/optimize-route",
        {
          collaborator_id: collaboratorId,
          current_lat: latitude, current_lng: longitude,
          apply: !!apply,
        },
      ).then((x) => x.data);
      setPreview(r);
      if (apply && r.applied && onApplied) onApplied();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="smart-route-card" style={{
      marginTop: 12, padding: "10px 12px", borderRadius: 12,
      background: preview?.ok
        ? "#ecfeff"
        : (enabled ? "#fff7ed" : "#f1f5f9"),
      border: "1px dashed " + (preview?.ok ? "#06b6d4"
                                : (enabled ? "#fb923c" : "#cbd5e1")),
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 22 }}>🗺️</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 800,
                          color: preview?.ok ? "#0e7490" : "#9a3412" }}>
            {preview?.ok
              ? `Rota otimizada: ${preview.total_km}km · ${preview.stops} paradas`
              : "Otimizar rota com IA"}
          </div>
          <div style={{ fontSize: 10, color: "#475569", marginTop: 2 }}>
            {preview?.ok
              ? `≈ ${preview.estimated_minutes}min total · ${preview.applied ? "✓ aplicada" : "pré-visualização"}`
              : (preview && preview.ok === false
                  ? preview.reason
                  : (enabled
                      ? "Calcula menor trajeto entre suas bolhas normais"
                      : "Sem bolhas reordenáveis no momento"))}
          </div>
        </div>
        {!preview?.ok && (
          <Button onClick={() => fetchOptimized(false)}
                   disabled={busy || !enabled}
                   data-testid="smart-route-preview-btn"
                   variant="primary"
                   style={{ padding: "6px 10px", fontSize: 12,
                              flexShrink: 0 }}>
            {busy ? "..." : "Calcular"}
          </Button>
        )}
        {preview?.ok && !preview.applied && (
          <Button onClick={() => fetchOptimized(true)}
                   disabled={busy}
                   data-testid="smart-route-apply-btn"
                   style={{ padding: "6px 10px", fontSize: 12,
                              flexShrink: 0,
                              background: "#06b6d4", color: "white" }}>
            {busy ? "..." : "Aplicar"}
          </Button>
        )}
      </div>
      {error && (
        <div data-testid="smart-route-error"
              style={{ marginTop: 6, fontSize: 11, color: "#b91c1c" }}>
          {error}
        </div>
      )}
      {preview?.ok && preview.optimized?.length > 0 && (
        <ol data-testid="smart-route-list" style={{
          marginTop: 8, marginBottom: 0, paddingLeft: 22,
          fontSize: 11, color: "#0f172a", lineHeight: 1.5,
        }}>
          {preview.optimized.map((stop, i) => (
            <li key={stop.id}>
              <strong>{stop.name || "Sem nome"}</strong>{" "}
              <span style={{ color: "#64748b" }}>
                · {stop.neighborhood || "—"} · {stop.distance_km}km
                {i === 0 ? " (próxima)" : ""}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}


function PerformanceCard({ perf, showPoints = true }) {
  if (!perf) return null;
  const {
    closed_today, points_today, success_rate,
    avg_minutes, rank, total_techs, streak, badge,
  } = perf;

  // Cor do card por desempenho
  let cardBg = "linear-gradient(135deg,#0ea5e9 0%,#0284c7 100%)";
  if (rank === 1 && total_techs > 1) {
    cardBg = "linear-gradient(135deg,#f59e0b 0%,#d97706 100%)"; // ouro
  } else if (closed_today === 0) {
    cardBg = "linear-gradient(135deg,#64748b 0%,#475569 100%)"; // cinza
  } else if (success_rate === 100 && closed_today >= 3) {
    cardBg = "linear-gradient(135deg,#10b981 0%,#059669 100%)"; // verde
  }

  const Stat = ({ label, value, sub }) => (
    <div style={{ flex: 1, textAlign: "center", padding: "6px 4px" }}>
      <div style={{ fontSize: 22, fontWeight: 800, lineHeight: 1,
                      color: "white" }}>{value}</div>
      <div style={{ fontSize: 9, color: "rgba(255,255,255,0.85)",
                      textTransform: "uppercase", letterSpacing: 0.6,
                      fontWeight: 700, marginTop: 4 }}>{label}</div>
      {sub && (
        <div style={{ fontSize: 9, color: "rgba(255,255,255,0.65)",
                        marginTop: 2 }}>{sub}</div>
      )}
    </div>
  );

  return (
    <div data-testid="tech-performance-card" style={{
      marginTop: 12, padding: "12px 14px", borderRadius: 14,
      background: cardBg, color: "white",
      boxShadow: "0 6px 16px -8px rgba(15,23,42,.35)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5,
                        textTransform: "uppercase",
                        color: "rgba(255,255,255,0.85)" }}>
          📊 Seu desempenho hoje
        </div>
        <div data-testid="tech-perf-badge" style={{
          fontSize: 10, fontWeight: 800, padding: "3px 8px",
          borderRadius: 999, background: "rgba(255,255,255,0.2)",
          border: "1px solid rgba(255,255,255,0.3)",
        }}>{badge}</div>
      </div>
      <div style={{ display: "flex", gap: 4 }}>
        <Stat label="Fechadas" value={closed_today} />
        {showPoints && (
          <Stat label="Pontos" value={points_today ?? 0} />
        )}
        <Stat label="% sucesso" value={`${success_rate}%`} />
        <Stat label="Tempo médio"
               value={avg_minutes ? `${avg_minutes}min` : "—"} />
        <Stat
          label="Ranking"
          value={rank ? `${rank}º` : "—"}
          sub={total_techs ? `de ${total_techs}` : null}
        />
      </div>
      {streak >= 2 && (
        <div style={{
          marginTop: 8, padding: "4px 10px", borderRadius: 999,
          background: "rgba(255,255,255,0.18)", fontSize: 10,
          fontWeight: 700, display: "inline-block",
        }}>🔥 {streak} dia(s) consecutivos com fechamento</div>
      )}
    </div>
  );
}



function ConsumableField({ label, fieldKey, consumableId, step, consMap, form, setForm }) {
  const cur = consMap[consumableId];
  const used = Number(form[fieldKey]) || 0;
  const after = cur ? cur.qty - used : null;
  const insufficient = cur && used > cur.qty;
  const emptyStock = cur && cur.qty === 0;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <label style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>{label}</label>
        {cur && !emptyStock && (
          <span style={{ fontSize: 11, color: insufficient ? "#dc2626" : "#64748b", fontWeight: 600 }} data-testid={`bal-${consumableId}`}>
            📦 {cur.qty} {cur.unit}
            {used > 0 && (
              <span style={{ color: insufficient ? "#dc2626" : "#16a34a", marginLeft: 6 }}>
                → <strong>{after} {cur.unit}</strong>
              </span>
            )}
          </span>
        )}
        {cur && emptyStock && (
          <span style={{
            fontSize: 10, fontWeight: 800, padding: "2px 7px",
            borderRadius: 999, background: "#fef3c7", color: "#92400e",
          }} data-testid={`bal-empty-${consumableId}`}>
            ⚠ sem estoque
          </span>
        )}
      </div>
      <input
        data-testid={`finalize-${fieldKey}`}
        type="number" step={step || "1"} min="0"
        value={form[fieldKey]} onChange={(e) => setForm({ ...form, [fieldKey]: e.target.value })}
        style={{
          width: "100%", padding: "10px 12px",
          border: `1px solid ${insufficient ? "#fca5a5" : "#cbd5e1"}`,
          background: insufficient ? "#fef2f2" : "white",
          borderRadius: 10, fontSize: 14, boxSizing: "border-box",
        }}
      />
      {emptyStock && (
        <div style={{
          marginTop: 4, fontSize: 10, color: "#92400e", fontWeight: 600,
        }}>
          Peça ao gestor para transferir antes de usar.
        </div>
      )}
    </div>
  );
}

function TicketDetail({ ticket, onClose, onFinalize, busy, err, onRefresh,
                          badSignalThreshold = -27, collaboratorId = null,
                          collaboratorName = "",
                          isAdminTest = false, onOpenCTO = null,
                          onOpenRedeMap = null,
                          pendingOfflineCount = 0 }) {
  // Modo "full unlock" — super_admin (Vando, admin@empresa.com) testando em modo
  // admin pode finalizar OS sem nenhuma trava (IPv6, sinal ruim, MAC, foto SN, etc).
  // Lê o JWT pra detectar `is_super_admin === true` ou email super admin conhecido.
  const isFullUnlock = React.useMemo(() => {
    if (typeof window === "undefined") return false;
    try {
      const token = window.localStorage.getItem("ponto_token");
      if (!token) return false;
      const payload = JSON.parse(atob(token.split(".")[1]));
      const SUPER_ADMIN_EMAILS = new Set([
        "vando@example.com",
        "admin@empresa.com",
      ]);
      const email = (payload?.email || "").toLowerCase();
      return Boolean(payload?.is_super_admin) || SUPER_ADMIN_EMAILS.has(email);
    } catch { return false; }
  }, []);
  // Quando admin testa como outro colab, isAdminTest=true bloqueia o finalize.
  // Mas se for super_admin (Vando), liberamos tudo (modo dev/teste sem travas).
  const adminBlocks = isAdminTest && !isFullUnlock;
  // Total de steps:
  // - Instalação (isInstall=true): 3 steps → 1=Sinal/ONT, 2=CTO+Porta, 3=Insumos
  // - Demais (retirada/reparo): 2 steps → 1=Sinal/ONT, 2=Insumos
  const [step, setStep] = useState(1);
  // iter183 — Chat WhatsApp do cliente (modal sheet)
  const [showChat, setShowChat] = useState(false);
  // Resultado do Teste IPv6 obrigatório (preenchido via Ipv6TestStep)
  const [ipv6Result, setIpv6Result] = useState(null);
  // iter155 — toggle empresa-wide para ligar/desligar a obrigatoriedade do
  // Teste IPv6 ao finalizar OS. Default DESLIGADO (carregado do backend).
  const [ipv6TestRequired, setIpv6TestRequired] = useState(false);
  // iter166 — Foto da CTO obrigatória + Validar MAC contra SmartOLT
  const [ctoPhotoRequired, setCtoPhotoRequired] = useState(false);
  const [macValidationRequired, setMacValidationRequired] = useState(false);
  // iter199 — Quando a CTO foi cadastrada há < 5 dias, pula a foto da CTO
  // (já foi fotografada no cadastro recente). State guarda o ID da CTO
  // verificada e a flag is_recent retornada pelo backend.
  const [ctoRecentInfo, setCtoRecentInfo] = useState(null); // {cto_id, is_recent, days_since}
  useEffect(() => {
    const cid = collaboratorId;
    if (!cid) {
      setIpv6TestRequired(false);
      setCtoPhotoRequired(false);
      setMacValidationRequired(false);
      return;
    }
    api._client.get(`/public/os-validation-toggles/${cid}`)
      .then((r) => {
        setIpv6TestRequired(!!r.data?.ipv6_test_required);
        setCtoPhotoRequired(!!r.data?.cto_photo_required);
        setMacValidationRequired(!!r.data?.mac_validation_required);
      })
      .catch(() => {
        setIpv6TestRequired(false);
        setCtoPhotoRequired(false);
        setMacValidationRequired(false);
      });
  }, [collaboratorId]);
  const [ctoSelected, setCtoSelected] = useState(null);

  // iter199 — Quando a CTO atual (ctoSelected ou live_signal.cto_id) está
  // cadastrada há menos do que window_days, pula a obrigatoriedade de foto
  // da CTO (já foi fotografada no cadastro recente, evita re-trabalho).
  useEffect(() => {
    const candidateId = ctoSelected?.id || ticket?.live_signal?.cto_id
      || ticket?.cto_id;
    if (!candidateId) { setCtoRecentInfo(null); return; }
    let alive = true;
    api._client.get(`/rede-ia/public/ctos/${candidateId}/recent-status`)
      .then((r) => {
        if (!alive) return;
        setCtoRecentInfo({ cto_id: candidateId, ...r.data });
      })
      .catch(() => { if (alive) setCtoRecentInfo(null); });
    return () => { alive = false; };
  }, [ctoSelected, ticket?.id, ticket?.live_signal?.cto_id, ticket?.cto_id]);
  const [ctoPortSelected, setCtoPortSelected] = useState(null);
  const [showCtoWizard, setShowCtoWizard] = useState(false);
  // State do fluxo de cadastro inline de CTO (4 telas integrado)
  const [ctoFlowState, setCtoFlowState] = useState({
    gps: { lat: null, lng: null, accuracy: null },
    address: { endereco: "", numero: "", referencia: "",
                bairro_detected: "", cidade_detected: "", estado_detected: "" },
    photo: null,
    vlan: "",
    capacity: null,
    networkType: null,
    splitter: null,
    clientPort: null,
    // Quando preenchido, indica que estamos reusando uma CTO existente
    existingCtoId: null,
  });
  // CTO existente selecionada pelo mapa (mostra confirmação)
  const [existingCtoPick, setExistingCtoPick] = useState(null);
  // Default do sinal: pega do SmartOLT (live_signal.rx_dbm) se disponível,
  // senão usa -25 dBm (média típica de instalação saudável)
  const initialSinal = ticket?.live_signal?.rx_dbm != null
    ? Number(ticket.live_signal.rx_dbm.toFixed(1))
    : -25;
  // iter211ad — Auto-save de draft local pra não perder dados se app crashar/recarregar.
  // Restaura draft salvo no localStorage se houver pra este ticket+colaborador.
  const draftKey = `${ticket?.id}::${collaboratorId}`;
  const initialForm = React.useMemo(() => {
    if (!ticket?.id) return null;
    const draft = loadDraft(ticket.id, collaboratorId);
    if (draft?.form) {
      // eslint-disable-next-line no-console
      console.log("[LousaMobile] draft restaurado de", draft.savedAt,
                  draft._droppedPhotos ? "(sem fotos)" : "");
      return draft.form;
    }
    return {
      sinal: initialSinal, qtd_drop: 0, esticadores: 0, conectores_fast: 0,
      cabo_rede: 0, conectores_rede: 0,
      fibra_06fo: 0, fibra_12fo: 0, fibra_24fo: 0,
      ont: "", observacoes: "",
      ont_sn: "",
      fotos: [],
      isSwap: false, old_ont_mac: "", new_ont_mac: "",
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey]);
  const [form, setForm] = useState(() => initialForm || {
    sinal: initialSinal, qtd_drop: 0, esticadores: 0, conectores_fast: 0,
    cabo_rede: 0, conectores_rede: 0,
    fibra_06fo: 0, fibra_12fo: 0, fibra_24fo: 0,
    ont: "", observacoes: "",
    ont_sn: "",  // iter174 — SN separado p/ retirada validar por SN ou MAC
    fotos: [],          // [{kind:'cto'|'sn', dataUrl}]
    // Troca de ONT/ONU em reparo
    isSwap: false, old_ont_mac: "", new_ont_mac: "",
  });
  const [draftSavedAt, setDraftSavedAt] = useState(null);

  // Auto-save com debounce 600ms via osDraftStorage
  React.useEffect(() => {
    if (!ticket?.id) return;
    saveDraft(ticket.id, collaboratorId, form);
    setDraftSavedAt(new Date());
  }, [form, ticket?.id, collaboratorId]);

  // Cleanup periódico de drafts > 7 dias (1× por mount)
  React.useEffect(() => {
    try { cleanupOldDrafts(); } catch { /* */ }
  }, []);
  // Ref do input file pra captura sequencial das 3 fotos no step final
  // (CTO + Equipamento + MAC/SN). O kind é definido dinamicamente em
  // `_kind` antes de abrir a câmera. Consolidação 28/05/2026.
  const equipPhotoInputRef = useRef(null);
  // Marca se o valor atual ainda é o auto-preenchido do SmartOLT (mostra badge
  // "do SmartOLT"). Quando o usuário edita o input, vira false.
  const [sinalFromOlt, setSinalFromOlt] = useState(
    ticket?.live_signal?.rx_dbm != null,
  );

  // iter211x — Carrega cardápio dinâmico de fotos obrigatórias por OS
  const [photoReqs, setPhotoReqs] = useState(null);
  useEffect(() => {
    let alive = true;
    api.lousaPhotoReqs?.()
      .then((r) => { if (alive) setPhotoReqs(r?.items || []); })
      .catch(() => { if (alive) setPhotoReqs([]); });
    return () => { alive = false; };
  }, []);

  // Sincroniza se o ticket atualizar (poll) e o usuário ainda não digitou
  React.useEffect(() => {
    if (sinalFromOlt && ticket?.live_signal?.rx_dbm != null) {
      setForm((f) => ({
        ...f,
        sinal: Number(ticket.live_signal.rx_dbm.toFixed(1)),
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticket?.live_signal?.rx_dbm]);
  const [stock, setStock] = useState(null);
  const [macStatus, setMacStatus] = useState(null);
  const [showStockPicker, setShowStockPicker] = useState(false);
  const [macInfo, setMacInfo] = useState(null);
  const [showQR, setShowQR] = useState(false);
  const [ocrBusy, setOcrBusy] = useState(false);
  const [ocrResult, setOcrResult] = useState(null);
  // iter176 — valor ORIGINAL lido pela IA (sem edições do técnico). Quando
  // o técnico finaliza, comparamos com `form.ont`/`form.ont_sn` para detectar
  // correções manuais e gravar em `stok_ocr_corrections`.
  const [ocrOriginal, setOcrOriginal] = useState(null);
  const [showOntScan, setShowOntScan] = useState(false);
  const [showOntBatch, setShowOntBatch] = useState(false);
  const [techOnts, setTechOnts] = useState({ novos: [], retirados: [] });
  const [clientOnts, setClientOnts] = useState([]);

  const cid = ticket.assigned_collaborator_id;
  // iter182 — Substituição de ONT/ONU (`troca`) segue o mesmo molde da
  // Instalação: MAC/SN obrigatórios, fluxo completo de CTO/porta/insumos
  // e validações de cadastro novo no SmartOLT.
  const isInstall = ticket.type === "instalacao"
    || ticket.type === "troca"
    || ticket.type === "troca_endereco";
  const isWithdraw = ticket.type === "retirada";
  // ONT do estoque é oferecida em qualquer fluxo de cliente final
  // (instalação, troca, troca de endereço, ponto adicional, reparo).
  const needsTechOnts = [
    "instalacao", "troca", "troca_endereco",
    "ponto_adicional", "reparo",
  ].includes(ticket.type);
  const isRepair = ticket.type === "reparo";
  // Cliente do ticket existe no SmartOLT? (null = ainda buscando)
  // Quando found=true, há um MAC/SN registrado lá; o técnico precisa bater
  // com esse valor no MAC informado em retirada/reparo. Quando found=false,
  // não há referência → MAC vira opcional (pedido do usuário, 21/05/2026).
  const [clientSmart, setClientSmart] = useState(null);
  useEffect(() => {
    if (!ticket?.id) return;
    let alive = true;
    api.publicClientByTicket(ticket.id)
      .then((r) => { if (alive) setClientSmart(r); })
      .catch(() => { if (alive) setClientSmart({ found: false }); });
    return () => { alive = false; };
  }, [ticket?.id]);

  // Cobrança do MAC:
  // - Instalação/troca → sempre obrigatório (cadastro novo no SmartOLT)
  // - Retirada/Reparo → SÓ obrigatório se o cliente está no SmartOLT
  // - Reparo sem retirada → opcional (continua opcional)
  const clientInSmartOlt = clientSmart?.found === true;
  const needsMac = isInstall || ((isWithdraw || isRepair) && clientInSmartOlt);

  // Auto-prefill `old_ont_mac` (MAC/SN retirado) com o valor registrado.
  // iter182 — Funciona para qualquer tipo de OS que envolve substituir
  // ONT (reparo, troca, retirada): pega o MAC/SN do SmartOLT OU do
  // histórico do cliente (clientOnts), assim que estiver disponível.
  // Mantém editável caso o técnico precise corrigir.
  useEffect(() => {
    const expectedFromSmartolt = (
      clientSmart?.mac_expected || clientSmart?.sn_expected || ""
    ).toUpperCase();
    // Fallback: último MAC instalado no cliente do nosso estoque
    const expectedFromStock = (
      (clientOnts && clientOnts[0]?.mac) || ""
    ).toUpperCase();
    const expected = expectedFromSmartolt || expectedFromStock;
    if (expected && !form.old_ont_mac) {
      setForm((f) => ({ ...f, old_ont_mac: expected }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    clientSmart?.mac_expected,
    clientSmart?.sn_expected,
    clientOnts,
  ]);

  // Carrega estoque do técnico
  useEffect(() => {
    if (!cid) return;
    let alive = true;
    api.publicTechStock(cid).then((s) => { if (alive) setStock(s); }).catch(() => {});
    return () => { alive = false; };
  }, [cid]);

  // Carrega ONTs do técnico (install) ou do cliente (retirada) para seletor
  useEffect(() => {
    if (!ticket) return;
    const techId = ticket.assigned_collaborator_id
                    || ticket.assigned_to
                    || ticket.technician_id
                    || collaboratorId;
    const clientId = ticket.client_id;
    if (needsTechOnts && techId) {
      api.stokTechOnts(techId).then((r) => {
        setTechOnts({
          novos: r.novos || [],
          retirados: r.retirados || [],
        });
      }).catch(() => setTechOnts({ novos: [], retirados: [] }));
    }
    if (isWithdraw && clientId) {
      api.stokClientOnts(clientId).then((r) => {
        setClientOnts(r.items || []);
      }).catch(() => setClientOnts([]));
    } else if (isRepair && clientId) {
      // iter182 — Em reparo também carregamos ONTs do cliente para
      // pré-preencher MAC RETIRADA quando o técnico marcar "Foi troca".
      api.stokClientOnts(clientId).then((r) => {
        setClientOnts(r.items || []);
      }).catch(() => setClientOnts([]));
    }
  }, [ticket, needsTechOnts, isWithdraw, isRepair, collaboratorId]);

  // Validação MAC contra SmartOLT (debounce)
  useEffect(() => {
    if (!form.ont || form.ont.length < 6) {
      setMacStatus(null); setMacInfo(null); return;
    }
    setMacStatus("loading");
    const handle = setTimeout(async () => {
      try {
        const r = await api.publicValidateMac(form.ont, cid);
        setMacInfo(r);
        if (!r.found_smartolt) {
          setMacStatus("error"); // não existe na SmartOLT
        } else if (isInstall && !r.in_tech_stock) {
          setMacStatus("warn"); // existe mas não está no técnico → bloqueia auto-baixa
        } else if (isWithdraw && !r.in_client) {
          setMacStatus("warn"); // retirada precisa estar no cliente
        } else {
          // Confere se bate com o MAC esperado do cliente (quando aplicável)
          if ((isWithdraw || isRepair) && clientInSmartOlt) {
            const expected = (
              clientSmart?.mac_expected || clientSmart?.sn_expected || ""
            ).toUpperCase();
            const informed = (form.ont || "").toUpperCase();
            if (expected && expected !== informed) {
              setMacStatus("mismatch"); // MAC não bate com o registrado do cliente
              return;
            }
          }
          setMacStatus("ok");
        }
      } catch {
        setMacStatus("error");
      }
    }, 600);
    return () => clearTimeout(handle);
  }, [form.ont, cid, isInstall, isWithdraw, isRepair, clientInSmartOlt,
       clientSmart?.mac_expected, clientSmart?.sn_expected]);

  // ============ HELPERS Foto + OCR ============
  async function readFileAsDataURL(file) {
    return new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = (e) => res(e.target.result);
      r.onerror = rej;
      r.readAsDataURL(file);
    });
  }

  // iter211g — Comprime DataURL pra evitar payloads >10MB que estouram
  // o gateway (causa do "Network Error" ao finalizar nota com fotos
  // diretas da câmera). Redimensiona pro maior lado = 1280px e JPEG 0.78.
  // Em conexões 4G fracas reduz ~20× o body.
  async function compressDataUrl(dataUrl, maxSide = 1280, quality = 0.78) {
    return new Promise((resolve) => {
      try {
        const img = new Image();
        img.onload = () => {
          const w = img.naturalWidth, h = img.naturalHeight;
          const scale = Math.min(1, maxSide / Math.max(w, h));
          const nw = Math.round(w * scale), nh = Math.round(h * scale);
          const canvas = document.createElement("canvas");
          canvas.width = nw; canvas.height = nh;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0, nw, nh);
          try {
            resolve(canvas.toDataURL("image/jpeg", quality));
          } catch (_) { resolve(dataUrl); }
        };
        img.onerror = () => resolve(dataUrl);
        img.src = dataUrl;
      } catch (_) { resolve(dataUrl); }
    });
  }

  // iter153 — divergência cruzada entre o MAC selecionado do estoque
  // (técnico escolheu uma ONT específica para instalar/substituir) e o
  // MAC que a IA leu da etiqueta na 3ª foto. Quando diferentes, exibe
  // alerta no card do wizard.
  const [macMismatch, setMacMismatch] = useState(null);
  // iter160 — validação Retirada: SN lido pela IA × SN cadastrado no SmartOLT.
  // Quando não coincide, finalização da Retirada precisa ser confirmada.
  const [withdrawSnCheck, setWithdrawSnCheck] = useState(null);
  // {match, sn_scanned, sn_expected, client_name, reason}

  async function captureSnPhoto(file) {
    try {
      setOcrBusy(true);
      setOcrResult(null);
      // Guarda o MAC selecionado do estoque ANTES do OCR rodar para
      // permitir comparação cruzada após detecção.
      const macBefore = (form.ont || "").trim().toUpperCase();
      const rawUrl = await readFileAsDataURL(file);
      // iter211g — comprime a foto da etiqueta SN antes de embarcar no
      // form e enviar pro OCR; ainda fica grande o bastante pra leitura
      // de IA, mas evita "Network Error" no finalize.
      const dataUrl = await compressDataUrl(rawUrl, 1280, 0.78);
      setForm((f) => ({
        ...f,
        fotos: [...f.fotos.filter((p) => p.kind !== "sn"),
                 { kind: "sn", dataUrl }],
      }));
      const r = await api._client.post(
        "/lousa/public/ocr-sn",
        { image_base64: dataUrl, hint: "SN/MAC de ONT" },
      ).then((x) => x.data);
      setOcrResult(r);
      const detectedSn = (r.sn || "").toUpperCase().replace(/[:\-.\s]/g, "");
      const detectedMac = (r.mac || "").toUpperCase();
      const detected = (r.sn || r.mac || r.best || "").toUpperCase();
      // iter176 — guarda os valores originais detectados pela IA para
      // depois comparar com a correção manual do técnico
      setOcrOriginal({
        mac: detectedMac || null,
        sn: detectedSn || null,
        confidence: r.confidence || null,
      });
      if (detected) {
        // Normaliza ambos os lados (remove separadores) para comparação
        const norm = (s) => (s || "").replace(/[:\-.\s]/g, "").toUpperCase();
        const dN = norm(detected);
        const bN = norm(macBefore);
        if (bN && bN !== dN && (isInstall || isRepair)) {
          // Divergência cruzada — operário PRECISA confirmar (a ONT que
          // ele selecionou do estoque NÃO é a que ele está instalando).
          setMacMismatch({ stock: macBefore, scanned: detected });
        } else {
          setMacMismatch(null);
        }
        // iter174 — distingue SN puro de MAC: MAC tem padrão XX:XX:XX:XX:XX:XX
        // ou 12 chars hex; SN tipicamente é mais longo ou contém letras não-hex.
        // Guardamos ambos no form: `ont` mantém compat; `ont_sn` é o SN puro.
        setForm((f) => ({
          ...f,
          ont: detected,
          ont_sn: detectedSn || (detectedMac ? "" : detected) || f.ont_sn || "",
        }));

        // iter160 — Para Retirada, valida SN escaneado contra SmartOLT
        if (isWithdraw && ticket?.id) {
          try {
            const v = await api._client.get(
              `/smartolt/public/validate-withdraw-sn/${ticket.id}`,
              { params: { sn: detected } },
            );
            setWithdrawSnCheck(v.data);
          } catch (vErr) {
            setWithdrawSnCheck({
              ok: false, match: false,
              reason: vErr?.response?.data?.detail || "Erro de rede",
            });
          }
        }
      }
    } catch (e) {
      await window.alert("OCR falhou: " + (e?.response?.data?.detail || e.message));
    } finally {
      setOcrBusy(false);
    }
  }

  async function goToStep2() {
    // Modo full unlock (super_admin/Vando) ignora TODAS as travas — modo teste.
    if (isFullUnlock) { setStep(2); return; }
    // Para RETIRADA (iter174): MAC OU SN aceito. A IA Claude 4.6 lê
    // a etiqueta e qualquer um dos dois identifica o equipamento.
    if (isWithdraw && !form.ont && !form.ont_sn) {
      await window.alert(
        "📡 Em retiradas o MAC OU SN da ONT é OBRIGATÓRIO antes de fechar.\n\n" +
        "Toque no botão 🤖 IA para fotografar a etiqueta — Claude 4.6 lê " +
        "MAC e SN automaticamente em 5 segundos. Basta detectar UM dos dois.");
      return;
    }
    // iter160 — Para Retirada: valida SN escaneado contra SmartOLT
    // (resposta de /smartolt/public/validate-withdraw-sn).
    // - match: libera direto
    // - mismatch: exige confirmação explícita do técnico
    // - not_in_smartolt: aviso suave (cliente não tem mapeamento)
    if (isWithdraw && withdrawSnCheck) {
      if (withdrawSnCheck.reason === "mismatch") {
        const ok = await window.confirm(
          "🚫 SN DIVERGENTE — o equipamento na foto não é o cadastrado " +
          "no SmartOLT para esse cliente.\n\n" +
          `Lido: ${withdrawSnCheck.sn_scanned}\n` +
          `Esperado: ${withdrawSnCheck.sn_expected}\n\n` +
          "Tem certeza que quer registrar a retirada mesmo assim? " +
          "(O equipamento provavelmente foi trocado anteriormente sem registro)");
        if (!ok) return;
      }
      // not_in_smartolt e match: passa direto
    } else if ((isWithdraw || isRepair) && clientInSmartOlt && macStatus === "mismatch") {
      // Fallback antigo (quando OCR não rodou ainda)
      const expected = clientSmart?.mac_expected || clientSmart?.sn_expected || "?";
      const ok = await window.confirm(
        `O MAC informado (${form.ont}) NÃO bate com o registrado no SmartOLT (${expected}).\n\n` +
        "Confirma mesmo assim? (Recomendado revisar a foto/etiqueta antes)");
      if (!ok) return;
    }
    // Em retiradas, exige a foto da etiqueta (prova auditável)
    if (isWithdraw) {
      const hasSnPhoto = (form.fotos || []).some((p) => p.kind === "sn");
      if (!hasSnPhoto) {
        await window.alert(
          "📸 Foto da etiqueta da ONT é OBRIGATÓRIA na retirada.\n\n" +
          "Toque em 🤖 IA para tirar a foto da etiqueta — a IA lerá o MAC/SN " +
          "e a foto fica como prova.");
        return;
      }
    }
    // Foto do equipamento foi removida do fluxo no step 1 — não bloqueia.
    // Para RETIRADA: pula totalmente as telas de CTO (steps 2 e 3) — vai
    // direto pro step de Insumos onde está o botão "Finalizar nota"
    // (pedido do usuário 28/05/2026 — fluxo retirada minimalista).
    if (isWithdraw) { setStep(insumosStepNum); return; }
    setStep(2);
  }

  // Total de steps no fluxo atual: 4 para TODOS os tipos
  // 1=Sinal, 2=CTO Mapa+Foto+VLAN, 3=CTO Portas+Tipo+Porta, 4=Insumos
  const totalFinalizeSteps = 4;
  const insumosStepNum = 4;

  async function submit() {
    // iter176 — Registra correção do OCR (best-effort, fire-and-forget)
    if (ocrOriginal && (ocrOriginal.mac || ocrOriginal.sn)) {
      const fnorm = (s) => (s || "").trim().toUpperCase().replace(/[:\-.\s]/g, "");
      const changedMac = fnorm(ocrOriginal.mac) !== fnorm(form.ont) && !!fnorm(form.ont);
      const changedSn = fnorm(ocrOriginal.sn) !== fnorm(form.ont_sn) && !!fnorm(form.ont_sn);
      if (changedMac || changedSn) {
        api._client.post("/lousa/public/ocr-correction", {
          ticket_id: ticket.id,
          collaborator_id: collaboratorId,
          original_mac: ocrOriginal.mac,
          original_sn: ocrOriginal.sn,
          corrected_mac: form.ont || null,
          corrected_sn: form.ont_sn || null,
          ont_model: ticket?.client_snapshot?.ont_model || null,
          confidence: ocrOriginal.confidence,
        }).catch(() => { /* silent */ });
      }
    }
    // Modo full unlock (Vando/super_admin) — finaliza sem nenhuma confirmação.
    if (isFullUnlock) {
      onFinalize({
        sinal: Number(form.sinal) || -25,
        qtd_drop: Number(form.qtd_drop) || 0,
        esticadores: Number(form.esticadores) || 0,
        conectores_fast: Number(form.conectores_fast) || 0,
        cabo_rede: Number(form.cabo_rede) || 0,
        conectores_rede: Number(form.conectores_rede) || 0,
        fibra_06fo: Number(form.fibra_06fo) || 0,
        fibra_12fo: Number(form.fibra_12fo) || 0,
        fibra_24fo: Number(form.fibra_24fo) || 0,
        ont: form.ont || null,
        ont_sn: form.ont_sn || null,  // iter174
        fotos: form.fotos,
        observacoes: form.observacoes || null,
        old_ont_mac: (isRepair && form.isSwap && form.old_ont_mac) || null,
        new_ont_mac: (isRepair && form.isSwap && form.new_ont_mac) || null,
        cto_id: ctoSelected?.id || null,
        cto_name: ctoSelected?.name || null,
        cto_port_number: ctoPortSelected || null,
        cto_splitter: ctoSelected?.splitter || ctoFlowState.splitter || null,
        cto_vlan: ctoSelected?.vlan
                    || (ctoFlowState.vlan ? parseInt(ctoFlowState.vlan, 10) : null),
        cto_network_type: ctoSelected?.network_type
                            || ctoFlowState.networkType || null,
        cancel_reason_category: form.cancel_reason_category || null,
        // iter153 — flag de equipamento defeituoso (apenas retirada)
        is_defective: !!form.is_defective,
        defective_reason: (form.is_defective && form.defective_reason)
                              ? form.defective_reason : null,
      });
      return;
    }
    if (needsMac && macStatus === "error") {
      if (!await window.confirm("MAC não encontrado no SmartOLT. Continuar mesmo "
                            + "assim? (Marca erro_estoque pra revisão)")) return;
    }
    // Wizard de 3 fotos (CTO + Equipamento + MAC/SN) obrigatório ao
    // finalizar OS de instalação ou reparo (pedido user 28/05/2026 —
    // consolidação no botão único do step de Insumos).
    // iter180 — TAMBÉM exige foto da CTO quando houve consumo de conector
    // de rede (troca de conector na CTO), independente do tipo da OS.
    // iter199 — PULA a foto da CTO quando ela foi cadastrada há < 5 dias
    // (já foi fotografada no cadastro recente; evita re-trabalho).
    // iter211aj — Respeita toggles globais cto_photo_required e
    // mac_validation_required quando o cardápio dinâmico não estiver
    // configurado (photoReqs vazio).
    const usedNetworkConnector = Number(form.conectores_rede) > 0;
    const photoRequired = isInstall || isRepair || usedNetworkConnector;
    const skipCtoPhoto = !!ctoRecentInfo?.is_recent;
    if (!isFullUnlock && photoRequired) {
      const fotos = form.fotos || [];
      const missing = [];
      // iter211x — Consulta cardápio dinâmico (Configurações > Fotos da OS).
      // Se config disponível: valida cada item com required=true e ticket_types
      // contendo o tipo desta OS. Senão: cai no comportamento hardcoded legado
      // (agora também respeitando os toggles globais).
      const ttype = ticket?.type;
      if (Array.isArray(photoReqs) && photoReqs.length > 0) {
        photoReqs.forEach((req) => {
          if (!req.required) return;
          const types = req.ticket_types || [];
          if (types.length > 0 && !types.includes(ttype)) return;
          // CTO recém-cadastrada dispensa só a foto "cto"
          if (req.id === "cto" && skipCtoPhoto) return;
          if (!fotos.some((p) => p.kind === req.id)) {
            missing.push(`${req.icon || "📷"} ${req.label}`);
          }
        });
      } else {
        // iter211aj — só exige se o toggle estiver ligado
        if (ctoPhotoRequired && !skipCtoPhoto
            && !fotos.some((p) => p.kind === "cto")) {
          missing.push("CTO");
        }
        // Equipamento e MAC/SN só são obrigatórios em instalação/reparo
        // (não em "troca de conector na CTO" que pode ser visita pontual).
        if ((isInstall || isRepair) && macValidationRequired) {
          if (!fotos.some((p) => p.kind === "equipamento")) missing.push("Equipamento (ONT/ONU)");
          if (!fotos.some((p) => p.kind === "sn")) missing.push("MAC/SN da etiqueta");
        }
      }
      if (missing.length > 0) {
        const ctx = usedNetworkConnector && !(isInstall || isRepair)
          ? "\n\nVocê informou consumo de conector de rede — a foto da "
            + "CTO é obrigatória para auditoria."
          : "\n\nO card vermelho no topo do step de Insumos guia você nas 3 capturas em sequência.";
        await window.alert(
          "📸 Faltam fotos obrigatórias antes de finalizar:\n\n" +
          missing.map((m) => `• ${m}`).join("\n") + ctx);
        return;
      }
    }
    // Saldo
    const consMap = Object.fromEntries(
      (stock?.consumables || []).map((c) => [c.id, c.qty]));
    const checks = [
      ["drop", form.qtd_drop], ["esticador", form.esticadores],
      ["conector_fast", form.conectores_fast], ["cabo_rede", form.cabo_rede],
      ["conector_rede", form.conectores_rede],
      ["fibra_06fo", form.fibra_06fo], ["fibra_12fo", form.fibra_12fo],
      ["fibra_24fo", form.fibra_24fo],
    ];
    for (const [k, v] of checks) {
      const used = Number(v) || 0;
      if (used > (consMap[k] ?? Infinity)) {
        if (!await window.confirm(`Saldo insuficiente de ${k} (disp ${consMap[k]}, `
                              + `gasto ${used}). Continuar? Vai ficar erro_estoque.`)) return;
        break;
      }
    }
    onFinalize({
      // Quando o campo Sinal foi ocultado pq já há live_signal,
      // injetamos o valor do SmartOLT automaticamente.
      sinal: Number(form.sinal !== "" && form.sinal != null
                       ? form.sinal
                       : (ticket?.live_signal?.rx_dbm ?? -25)),
      qtd_drop: Number(form.qtd_drop),
      esticadores: Number(form.esticadores),
      conectores_fast: Number(form.conectores_fast),
      cabo_rede: Number(form.cabo_rede),
      conectores_rede: Number(form.conectores_rede),
      fibra_06fo: Number(form.fibra_06fo) || 0,
      fibra_12fo: Number(form.fibra_12fo) || 0,
      fibra_24fo: Number(form.fibra_24fo) || 0,
      ont: form.ont || null,
      ont_sn: form.ont_sn || null,  // iter174 — SN como alternativa ao MAC
      fotos: form.fotos,
      observacoes: form.observacoes || null,
      // Troca de ONT/ONU em reparo — capturado opcionalmente pelo técnico.
      // Quando isSwap=ON e isRepair, enviamos old/new explicitamente. O
      // backend também tenta auto-detectar comparando `ont` × SmartOLT.
      old_ont_mac: (isRepair && form.isSwap && form.old_ont_mac) || null,
      new_ont_mac: (isRepair && form.isSwap && form.new_ont_mac) || null,
      // Vínculo do cliente à porta da CTO (todos os tipos de OS).
      // Registra CTO, PORTA, SPLITTER, VLAN, Cliente no completion_data
      // e no mapa interativo (Rede IA).
      cto_id: ctoSelected?.id || null,
      cto_name: ctoSelected?.name || null,
      cto_port_number: ctoPortSelected || null,
      cto_splitter: ctoSelected?.splitter || ctoFlowState.splitter || null,
      cto_vlan: ctoSelected?.vlan
                  || (ctoFlowState.vlan ? parseInt(ctoFlowState.vlan, 10) : null),
      cto_network_type: ctoSelected?.network_type
                          || ctoFlowState.networkType || null,
      cancel_reason_category: form.cancel_reason_category || null,
    });
  }

  const consMap = Object.fromEntries((stock?.consumables || []).map((c) => [c.id, c]));

  const macColors = {
    loading: { bg: "#dbeafe", color: "#1e40af", border: "#93c5fd", icon: "🔍", txt: "Validando…" },
    ok: { bg: "#dcfce7", color: "#166534", border: "#86efac", icon: "✓", txt: "Equipamento validado" },
    warn: { bg: "#fef3c7", color: "#92400e", border: "#fde68a", icon: "⚠", txt: "Não está no estoque correto" },
    error: { bg: "#fee2e2", color: "#991b1b", border: "#fca5a5", icon: "✕", txt: "MAC não encontrado no SmartOLT" },
    mismatch: { bg: "#fee2e2", color: "#991b1b", border: "#fca5a5", icon: "🚫",
                  txt: "MAC não bate com o registrado do cliente no SmartOLT" },
  };
  const macStyle = macStatus ? macColors[macStatus] : null;

  return (
    <div data-testid="ticket-detail">
      {isFullUnlock && (
        <div data-testid="full-unlock-badge"
              style={{
                background: "linear-gradient(135deg,#fbbf24 0%,#f59e0b 100%)",
                color: "#7c2d12", padding: "8px 12px", borderRadius: 10,
                fontSize: 11, fontWeight: 800, letterSpacing: 0.5,
                textTransform: "uppercase",
                boxShadow: "0 1px 3px rgba(245,158,11,0.4)",
                display: "flex", alignItems: "center", gap: 8,
                marginBottom: 10,
              }}>
          <span style={{ fontSize: 14 }}>🔓</span>
          <span style={{ flex: 1 }}>Modo Teste · Super Admin · sem travas</span>
          <button data-testid="demo-finalize-fast"
                  onClick={() => {
                    // Auto-preenche tudo e pula direto pro último step.
                    const expMac = clientSmart?.mac_expected
                                    || ticket?.live_signal?.sn
                                    || "TESTMAC000001";
                    setForm((f) => ({
                      ...f,
                      sinal: "-25",
                      qtd_drop: 10, esticadores: 2, conectores_fast: 2,
                      cabo_rede: 5, conectores_rede: 2,
                      fibra_06fo: 0, fibra_12fo: 0, fibra_24fo: 0,
                      ont: (f.ont || expMac).toUpperCase(),
                      observacoes: f.observacoes || "OS de teste (Modo Demo)",
                    }));
                    setCtoFlowState((s) => ({
                      ...s,
                      vlan: s.vlan || "313",
                      photo: s.photo || null,
                      gps: s.gps?.lat ? s.gps : { lat: -22.9, lng: -43.2, accuracy: 10 },
                      address: s.address?.endereco ? s.address : {
                        endereco: "Endereço de teste, 100",
                        bairro: "Centro", cidade: "Demo",
                        estado: "RJ", cep: "00000-000",
                        bairro_detected: "Centro",
                      },
                    }));
                    setIpv6Result({ score: 10, has_ipv6: true, test: "demo" });
                    setStep(insumosStepNum);
                  }}
                  style={{
                    padding: "5px 10px", borderRadius: 6,
                    background: "#7c2d12", color: "#fbbf24",
                    border: 0, fontSize: 10, fontWeight: 800,
                    cursor: "pointer", letterSpacing: 0.5,
                    textTransform: "uppercase",
                  }}>
            ⚡ Pular p/ Finalizar
          </button>
        </div>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button variant="soft" onClick={onClose} data-testid="ticket-close-btn">← Voltar</Button>
        {onRefresh && (
          <Button variant="soft" onClick={onRefresh} data-testid="ticket-refresh-btn"
            style={{ background: "#dbeafe", color: "#1e40af", border: "1px solid #93c5fd" }}>🔄 Atualizar</Button>
        )}
        {ticket?.client_snapshot?.phone && (
          <button
            data-testid="ticket-open-chat-btn"
            onClick={() => setShowChat(true)}
            style={{
              marginLeft: "auto",
              background: "#065f46", color: "white",
              border: 0, padding: "8px 14px", borderRadius: 10,
              fontSize: 13, fontWeight: 700, cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 6,
              boxShadow: "0 2px 6px rgba(6,95,70,0.25)",
            }}>
            💬 Chat WhatsApp
          </button>
        )}
      </div>

      {/* HEADER da nota */}
      <div style={{
        background: "linear-gradient(135deg,#0f172a 0%,#1e293b 100%)", color: "white",
        padding: 16, borderRadius: 14, marginTop: 14,
      }}>
        <div style={{ fontSize: 11, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 700, marginBottom: 4 }}>
          {ticket.type.toUpperCase()}
          {/* iter211ax — Mostra o HORÁRIO agendado (hh:mm) ao invés do label
              "HORARIO"/priority. Se não tiver scheduled_time, esconde. */}
          {typeof ticket.scheduled_time === "string"
           && ticket.scheduled_time.length >= 16
            ? ` · ${ticket.scheduled_time.substr(11, 5)}`
            : ""}
        </div>
        <button
          type="button"
          data-testid="ticket-client-name-copy"
          onClick={async (e) => {
            e.stopPropagation();
            const btn = e.currentTarget;
            try {
              await navigator.clipboard.writeText(ticket.client_snapshot.name);
            } catch {
              const ta = document.createElement("textarea");
              ta.value = ticket.client_snapshot.name;
              document.body.appendChild(ta); ta.select();
              try { document.execCommand("copy"); } catch { /* noop */ }
              document.body.removeChild(ta);
            }
            if (btn) btn.dataset.copied = "1";
            setTimeout(() => { if (btn) delete btn.dataset.copied; }, 1200);
          }}
          style={{
            background: "transparent", border: 0, padding: 0,
            color: "inherit", textAlign: "left", cursor: "pointer",
            fontSize: 18, fontWeight: 800, marginBottom: 6,
            fontFamily: "inherit",
            WebkitTapHighlightColor: "transparent",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}
          title="Toque para copiar nome">
          {ticket.client_snapshot.name}
          <span style={{ opacity: 0.5, fontSize: 11, fontWeight: 600 }}>📋</span>
        </button>
        <div style={{ fontSize: 12, color: "#cbd5e1", marginBottom: 8 }}>
          📍 {fmtAddress(ticket.client_snapshot.address)}{ticket.client_snapshot.neighborhood ? ` · ${ticket.client_snapshot.neighborhood}` : ""}
        </div>
        {ticket.client_snapshot.pppoe_user && (
          <PppoeChip pppoe={ticket.client_snapshot.pppoe_user} />
        )}
        {ticket.live_signal && (
          <>
            <div style={{ marginTop: 8, padding: "6px 10px", background: "rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}>
              📶 <strong>{ticket.live_signal.rx_dbm != null
                ? `${ticket.live_signal.rx_dbm.toFixed(1)} dBm` : "—"}</strong>
              {ticket.live_signal.status
                && ticket.live_signal.status !== "—"
                && ` · ${ticket.live_signal.status}`}
              {ticket.live_signal.olt_name
                && ` · ${ticket.live_signal.olt_name}`}
              {ticket.live_signal.source === "cto_ports_fallback" && (
                <span style={{ marginLeft: 6, fontSize: 9.5,
                                 padding: "1px 5px", borderRadius: 4,
                                 background: "rgba(251,191,36,0.2)",
                                 color: "#fbbf24" }}>
                  cache rede
                </span>
              )}
            </div>
            <SmartOltDetailBlock ls={ticket.live_signal} />
          </>
        )}
      </div>

      <div style={{
        background: "#f1f5f9", padding: 12, borderRadius: 12, marginTop: 12,
        fontSize: 13, lineHeight: 1.5, borderLeft: "3px solid #6366f1",
      }}>
        <strong>📝 Relato:</strong> {ticket.client_snapshot.relato}
      </div>

      {/* iter211ay — Resumo Álvaro IA do atendimento (gerado a partir do
          relato + histórico WhatsApp do cliente nas últimas 48h). */}
      <OsAlvaroSummary ticketId={ticket.id} />

      {/* Indicador de progresso removido a pedido do usuário (28/05/2026) */}

      {/* iter211ad — Indicador "💾 Rascunho salvo" pra técnico saber que
          mesmo se app crashar/recarregar, os dados estão preservados.
          iter211aw — Removido (poluindo a tela). Autosave continua
          funcionando silenciosamente em background. */}

      {/* iter211ae — Badge fila offline (finalizações aguardando reenvio) */}
      {pendingOfflineCount > 0 && (
        <div data-testid="offline-queue-badge"
              style={{
                marginTop: 8, padding: "8px 12px",
                background: "linear-gradient(135deg,#fef3c7,#fde68a)",
                border: "1.5px solid #f59e0b",
                borderRadius: 10, fontSize: 12, color: "#78350f",
                fontWeight: 700, display: "flex", alignItems: "center",
                gap: 8,
              }}
              title="Você finalizou OS sem internet. O app vai enviar pro servidor assim que a conexão voltar — não precisa fazer nada.">
          <span style={{ fontSize: 16 }}>📡</span>
          <span>
            {pendingOfflineCount} finalização{pendingOfflineCount > 1 ? "ões" : ""} aguardando reenvio
          </span>
          <span style={{ marginLeft: "auto", fontSize: 10, opacity: 0.85,
                          background: "rgba(255,255,255,0.6)",
                          padding: "2px 8px", borderRadius: 999 }}>
            auto-sync ativo
          </span>
        </div>
      )}

      {/* iter182 — StepIndicator reintroduzido com design Swiss/High-Contrast
          (best practice 2026: progressive disclosure + thumb-zone). Mostra
          quanto falta da OS e dá contexto da etapa atual. Não mostra em
          retirada (fluxo direto de 1 step).
          iter182.2 — Steps 1+2 unificados: agora 3 etapas exibidas
          (Equipamento+CTO / Porta / Finalização). */}
      {!isWithdraw && (() => {
        // step real → step exibido (1,3,4) → (1,2,3)
        const displayStep = step === 1 ? 1
                          : step === 2 ? 1   // ainda no card de CTO
                          : step === 3 ? 2
                          : 3;
        const displayLabel = displayStep === 1 ? "Equipamento + CTO"
                            : displayStep === 2 ? "Porta CTO"
                            : "Finalização";
        return (
          <LousaStepIndicator
            step={displayStep}
            totalSteps={3}
            variant="full"
            // iter211av — só volta pra Step 3 (Porta CTO) se houver CTO
            // selecionada. Senão volta direto pra Step 1 (não passa por
            // tela de criação que não existe mais no fluxo OS).
            onStepBack={displayStep > 1 ? () => {
              if (step === insumosStepNum) {
                setStep(ctoFlowState.existingCtoId ? 3 : 1);
              } else if (step === 3) setStep(1);
            } : null}
            // Sobreescreve label dinâmico
            // (variant "full" usa o mapping interno; passo via prop)
            customLabel={displayLabel}
          />
        );
      })()}

      {/* SINAL — step 1 · NÃO mostra em retirada (poluía a tela)
          · NÃO mostra se o card SmartOLT acima já trouxe sinal (info duplicada,
            o gestor vê live_signal.rx_dbm direto no header escuro)
            iter182 — Bloco removido conforme decisão do gestor: o input
            manual era confuso (sem função quando o cliente já tem
            live_signal). `form.sinal` segue no state com fallback -25
            usado na request de finalização. */}
      {false && step === 1 && !isWithdraw && !ticket?.live_signal?.rx_dbm && (
      <div style={{ marginBottom: 14 }}>
        <label style={{ fontSize: 12, color: "#475569", fontWeight: 700,
                         display: "flex", alignItems: "center", gap: 6 }}>
          📶 Sinal medido (dBm)
        </label>
        <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
          <input data-testid="finalize-sinal" type="number" step="0.1" value={form.sinal}
            onChange={(e) => {
              setForm({ ...form, sinal: e.target.value });
              if (sinalFromOlt) setSinalFromOlt(false);
            }}
            style={{ flex: 1, padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 14, boxSizing: "border-box" }} />
          {ticket?.live_signal?.rx_dbm != null && !sinalFromOlt && (
            <button type="button"
                      onClick={() => {
                        setForm({ ...form,
                          sinal: Number(ticket.live_signal.rx_dbm.toFixed(1)) });
                        setSinalFromOlt(true);
                      }}
                      data-testid="finalize-sinal-refresh"
                      title="Usar sinal atual do SmartOLT"
                      style={{
                        padding: "10px 12px", border: "1px solid #06b6d4",
                        background: "#ecfeff", color: "#0e7490",
                        borderRadius: 10, fontSize: 11, fontWeight: 700,
                        cursor: "pointer", whiteSpace: "nowrap",
                      }}>
              ⟳ OLT
            </button>
          )}
        </div>
        {form.sinal !== "" && Number(form.sinal) < badSignalThreshold && (
          <div data-testid="finalize-bad-signal-warning"
                style={{
                  marginTop: 6, padding: "8px 10px", borderRadius: 8,
                  background: "#fef3c7", border: "1px solid #fde68a",
                  color: "#78350f", fontSize: 12, lineHeight: 1.4,
                  fontWeight: 600,
                }}>
            ⚠ Sinal abaixo de {badSignalThreshold} dBm. Se a Central proibir
            fechamento ruim, o gestor receberá um pedido de autorização ao você
            finalizar.
          </div>
        )}
        {ticket.live_signal?.sn && form.ont
            && form.ont.toUpperCase().replace(/:/g, "")
              !== ticket.live_signal.sn.toUpperCase().replace(/:/g, "") && (
          <div data-testid="finalize-sn-mismatch-warning"
                style={{
                  marginTop: 6, padding: "8px 10px", borderRadius: 8,
                  background: "#fef3c7", border: "1px solid #fde68a",
                  color: "#78350f", fontSize: 12, lineHeight: 1.4,
                  fontWeight: 600,
                }}>
            ⚠ O SN/MAC registrado na SmartOLT é
            <code style={{ background: "white", padding: "1px 4px",
                            borderRadius: 4, marginLeft: 4 }}>
              {ticket.live_signal.sn}
            </code>
            <br/>
            Você digitou <code style={{ background: "white",
                                            padding: "1px 4px",
                                            borderRadius: 4 }}>{form.ont}</code>.
            Confirma que trocou a ONT?
          </div>
        )}
      </div>
      )}

      {/* MAC ONT — step 1
          Para INSTALAÇÃO o cadastro de ONU é feito pela Rede IA. Aqui só
          pedimos MAC em RETIRADA (registrar qual ONT saiu do cliente). */}
      {step === 1 && isWithdraw && (
        <div style={{ marginBottom: 14 }}>
          {/* Aviso "Cliente encontrado no SmartOLT" REMOVIDO a pedido do
              usuário (28/05/2026) — informação poluía a tela. A regra de
              negócio em si (MAC obrigatório quando clientInSmartOlt) é
              preservada no submit. */}
          <label style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
            📡 SN da ONT (retirada do cliente) <span style={{ fontSize: 10, color: "#94a3b8", fontWeight: 500 }}>· identificador principal</span>
            {clientInSmartOlt ? " *" : " (opcional)"}
          </label>
          <div style={{ display: "flex", gap: 6, marginTop: 4, marginBottom: 6 }}>
            <input
              data-testid="finalize-ont"
              value={form.ont} onChange={(e) => setForm({ ...form, ont: e.target.value.trim().toUpperCase() })}
              placeholder="Ex.: HWTC12345678 (SN) ou AA:BB:CC:DD:EE:FF (MAC)"
              style={{
                flex: 1, padding: "10px 12px",
                border: `1px solid ${macStyle?.border || "#cbd5e1"}`,
                borderRadius: 10, fontSize: 14,
                fontFamily: "monospace", textTransform: "uppercase", boxSizing: "border-box",
              }}
            />
            {/* 📦 Selecionar do estoque do TÉCNICO (instalação) ou
                do CLIENTE (retirada) */}
            {(() => {
              const installOpts = [...(techOnts.novos || []),
                                    ...(techOnts.retirados || [])];
              const withdrawOpts = clientOnts || [];
              const opts = isWithdraw ? withdrawOpts : installOpts;
              if (opts.length === 0 && !((!isWithdraw && (stock?.onts || []).length > 0))) return null;
              const label = isWithdraw ? "Cliente" : "Meu estoque";
              const count = opts.length || (stock?.onts || []).length;
              return (
                <button
                  type="button"
                  data-testid="ont-stock-picker-btn"
                  onClick={() => setShowStockPicker(true)}
                  title={`Selecionar do ${label.toLowerCase()} (${count} ONTs)`}
                  style={{
                    padding: "10px 14px", border: "none", borderRadius: 10,
                    background: isWithdraw
                      ? "linear-gradient(135deg,#8b5cf6,#6366f1)"
                      : "linear-gradient(135deg,#f59e0b,#d97706)",
                    color: "white", fontWeight: 800, fontSize: 16,
                    cursor: "pointer", flexShrink: 0,
                    display: "inline-flex", alignItems: "center", gap: 4,
                  }}>
                  {isWithdraw ? "👤" : "📦"}
                  <span style={{ fontSize: 11, fontWeight: 800 }}>{count}</span>
                </button>
              );
            })()}
            {/* Câmera OCR — foto da etiqueta preenche o MAC/SN */}
            <button
              type="button"
              data-testid="ai-scan-ont-btn"
              onClick={() => setShowOntScan(true)}
              title="Scan IA: Claude 4.6 lê MAC/SN da etiqueta"
              style={{
                padding: "10px 14px", border: "none", borderRadius: 10,
                background: "linear-gradient(135deg,#0d9488,#06b6d4)",
                color: "white", fontWeight: 800, fontSize: 16,
                cursor: "pointer", flexShrink: 0,
                display: "inline-flex", alignItems: "center", gap: 3,
              }}>
              🤖
              <span style={{ fontSize: 10, fontWeight: 800 }}>IA</span>
            </button>
            {/* Botões verde (OCR file) e azul (QR scanner) removidos a pedido
                do usuário — IA já cobre os dois casos. */}
          </div>
          {ocrResult && (
            <div data-testid="ocr-result"
                  style={{
                    padding: 10, borderRadius: 10, marginBottom: 6,
                    background: ocrResult.best ? "#f0fdfa" : "#fef2f2",
                    border: `1px solid ${ocrResult.best ? "#5eead4" : "#fca5a5"}`,
                    fontSize: 11, lineHeight: 1.4,
                  }}>
              {!ocrResult.best && (
                <div style={{ color: "#991b1b", fontWeight: 700 }}>
                  ⚠ Nada legível na foto. Tente novamente com melhor luz.
                </div>
              )}
              {ocrResult.best && (
                <>
                  <div style={{ fontWeight: 700, color: "#0f766e", marginBottom: 6 }}>
                    ✓ IA detectou (confiança: {ocrResult.confidence}) — você pode corrigir se necessário:
                  </div>
                  {/* iter197 — SN é o identificador prevalente: SN primeiro, MAC secundário */}
                  <div style={{ display: "grid",
                                    gridTemplateColumns: "auto 1fr",
                                    gap: "6px 8px", alignItems: "center" }}>
                    <label style={{ fontSize: 11, fontWeight: 800, color: "#065f46" }}>
                      SN: *
                    </label>
                    <input
                      data-testid="ocr-sn-input"
                      value={form.ont_sn || ""}
                      onChange={(e) => setForm((f) => ({ ...f,
                        ont_sn: e.target.value.trim().toUpperCase() }))}
                      placeholder="(principal — pode digitar)"
                      style={{
                        padding: "8px 10px",
                        border: "2px solid #10b981",
                        borderRadius: 6, fontSize: 14, fontWeight: 800,
                        fontFamily: "monospace", textTransform: "uppercase",
                        background: form.ont_sn ? "#ecfdf5" : "#fef3c7",
                      }}
                    />
                    <label style={{ fontSize: 10, fontWeight: 600, color: "#94a3b8" }}>
                      MAC:
                    </label>
                    <input
                      data-testid="ocr-mac-input"
                      value={form.ont || ""}
                      onChange={(e) => setForm((f) => ({ ...f,
                        ont: e.target.value.trim().toUpperCase() }))}
                      placeholder="(opcional)"
                      style={{
                        padding: "6px 8px",
                        border: "1px solid #cbd5e1",
                        borderRadius: 6, fontSize: 11,
                        fontFamily: "monospace", textTransform: "uppercase",
                        background: form.ont ? "#fff" : "#fafafa",
                      }}
                    />
                  </div>
                  {isWithdraw && (
                    <div style={{ marginTop: 6, fontSize: 10,
                                      color: "#64748b", fontStyle: "italic" }}>
                      💡 Em retiradas, basta preencher MAC OU SN — qualquer um valida.
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* iter160 — Validação Retirada: SN scaneado × SmartOLT */}
          {isWithdraw && withdrawSnCheck && (
            <div data-testid="withdraw-sn-check" style={{
              padding: "10px 12px", borderRadius: 10,
              marginBottom: 8, fontSize: 12, lineHeight: 1.5,
              background: withdrawSnCheck.match
                ? "#dcfce7"
                : (withdrawSnCheck.reason === "not_in_smartolt"
                    ? "#fef3c7" : "#fee2e2"),
              color: withdrawSnCheck.match
                ? "#166534"
                : (withdrawSnCheck.reason === "not_in_smartolt"
                    ? "#92400e" : "#7f1d1d"),
              border: `1.5px solid ${withdrawSnCheck.match
                ? "#16a34a"
                : (withdrawSnCheck.reason === "not_in_smartolt"
                    ? "#fde68a" : "#dc2626")}`,
            }}>
              {withdrawSnCheck.match ? (
                <>
                  <div style={{ fontWeight: 800, marginBottom: 4 }}>
                    ✅ SN confere com o cadastro no SmartOLT
                  </div>
                  <div style={{ fontSize: 11, fontFamily: "monospace" }}>
                    SN: <strong>{withdrawSnCheck.sn_scanned}</strong>
                    {withdrawSnCheck.olt_name && (
                      <> · OLT: {withdrawSnCheck.olt_name}</>
                    )}
                  </div>
                  <div style={{ fontSize: 11, marginTop: 4, fontWeight: 600 }}>
                    Retirada liberada — equipamento correto do cliente.
                  </div>
                </>
              ) : withdrawSnCheck.reason === "not_in_smartolt" ? (
                <>
                  <div style={{ fontWeight: 800, marginBottom: 4 }}>
                    ⚠️ Cliente não localizado no SmartOLT
                  </div>
                  <div style={{ fontSize: 11 }}>
                    Não foi possível confirmar o SN. A retirada será
                    finalizada sem validação cruzada. Confirme
                    visualmente o equipamento.
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontWeight: 800, marginBottom: 4 }}>
                    🚫 SN DIVERGENTE — retirada bloqueada
                  </div>
                  <div style={{ fontSize: 11, fontFamily: "monospace",
                                   marginTop: 4 }}>
                    Lido na etiqueta: <strong>{withdrawSnCheck.sn_scanned}</strong>
                    <br />
                    Cadastrado SmartOLT: <strong style={{ color: "#dc2626" }}>
                      {withdrawSnCheck.sn_expected || "—"}
                    </strong>
                  </div>
                  <div style={{ fontSize: 11, marginTop: 6, fontWeight: 600 }}>
                    Este SN NÃO é o equipamento do cliente
                    {withdrawSnCheck.client_name ? ` ${withdrawSnCheck.client_name}` : ""}.
                    Confirme se está retirando o equipamento certo. Se foi
                    trocado anteriormente sem registro, marque "Equipamento
                    com defeito" no step de Insumos para forçar análise.
                  </div>
                </>
              )}
            </div>
          )}

          {macStyle && (
            <div data-testid="mac-validation" style={{
              padding: "8px 12px", borderRadius: 10, fontSize: 12,
              background: macStyle.bg, color: macStyle.color, fontWeight: 600,
              display: "flex", flexDirection: "column", gap: 4,
            }}>
              <div><strong>{macStyle.icon} {macStyle.txt}</strong></div>
              {macInfo?.smartolt && (
                <div style={{ fontSize: 11, fontFamily: "monospace" }}>
                  {macInfo.smartolt.name} · {macInfo.smartolt.olt_name} · sinal {macInfo.smartolt.signal_1490} dBm · {macInfo.smartolt.status}
                </div>
              )}
              {macInfo?.ont_record && (
                <div style={{ fontSize: 11 }}>
                  🏷 Estoque: {macInfo.ont_record.location_type === "tecnico" ? "no técnico" : macInfo.ont_record.location_type === "cliente" ? `cliente ${macInfo.ont_record.client_name || ""}` : macInfo.ont_record.location_type}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* iter182 — Bloco "Foi troca de ONT/ONU" foi MOVIDO do Step 1 para
          o Step Insumos (acima do wizard de fotos). MAC da ONT RETIRADA é
          pré-preenchido com o valor do SmartOLT quando disponível. */}

      {/* iter182 — STEP 1 + STEP 2 unificados: CTO Picker renderizado
          aqui no Step 1, logo abaixo do MAC/SN. Decisão do gestor:
          economiza 1 toque do técnico. Só em fluxo não-retirada. */}
      {step === 1 && !isWithdraw && (
        <div style={{ marginTop: 16, marginBottom: 12 }}>
          <div style={{ height: 1, background: "#e2e8f0",
                          marginBottom: 12 }} />
          <OsCtoPicker
            collabId={collaboratorId}
            onSelectExistingCto={(cto) => setExistingCtoPick(cto)}
            onBack={() => {}} /* sem voltar — está no Step 1 */
            onSkip={() => {
              // validações de retirada não aplicam aqui (já filtramos
              // !isWithdraw). Pula CTO e vai direto pra Finalização.
              setStep(insumosStepNum);
            }}
          />
        </div>
      )}

      {/* Step 1 → botão de avançar.
          • Retirada: finaliza direto na 1ª tela (já tem botão próprio).
          • Demais tipos: NÃO precisa mais — a seleção da CTO no
            OsCtoPicker acima já avança o fluxo (abre modal existing-cto
            e chama setStep(3) ao confirmar). */}
      {step === 1 && isWithdraw && false && (
        <Button onClick={goToStep2}
                 data-testid="finalize-next-btn"
                 style={{ width: "100%", marginTop: 6, height: 52, fontSize: 15 }}>
          Próximo: Localização da CTO →
        </Button>
      )}

      {/* ============ STEP 1 RETIRADA — fluxo direto: finalizar nesta tela
          (pedido do usuário 28/05/2026 — sem CTO, sem insumos, sem IPv6)
          ============ */}
      {step === 1 && isWithdraw && (
        <>
          <label style={{ fontSize: 12, color: "#475569", fontWeight: 700,
                              marginTop: 14, display: "block" }}>
            🚪 Motivo do cancelamento *
          </label>
          <select
            data-testid="finalize-cancel-reason-category"
            value={form.cancel_reason_category || ""}
            onChange={(e) => setForm({ ...form,
                cancel_reason_category: e.target.value })}
            style={{
              width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1",
              borderRadius: 10, fontSize: 14, marginTop: 4,
              boxSizing: "border-box", background: "white",
              fontFamily: "inherit",
            }}>
            <option value="">Selecione uma categoria…</option>
            <option value="preco">💰 Preço / custo elevado</option>
            <option value="atendimento">📞 Insatisfação com atendimento</option>
            <option value="qualidade">📡 Problemas técnicos / qualidade</option>
            <option value="mudanca">🚚 Mudança de endereço</option>
            <option value="concorrente">🔁 Migração para concorrente</option>
            <option value="financeiro">💳 Dificuldade financeira</option>
            <option value="nao_usa">🛌 Não usa mais (idade, viagem...)</option>
            <option value="outros">❓ Outros</option>
          </select>

          {/* iter153 — Equipamento com defeito (apenas Retirada)
              Quando marcado, a ONT volta como DEFEITO e NÃO fica disponível
              para reinstalar em outro cliente; só pode ser devolvida ao
              estoque da empresa para análise/reparo. */}
          <div data-testid="finalize-defective-section" style={{ marginTop: 14 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 10,
                              padding: "12px 14px", borderRadius: 12,
                              background: form.is_defective
                                ? "linear-gradient(135deg,#fef2f2,#fee2e2)"
                                : "#f8fafc",
                              border: `1.5px solid ${form.is_defective ? "#dc2626" : "#cbd5e1"}`,
                              cursor: "pointer", fontSize: 13.5,
                              color: form.is_defective ? "#7f1d1d" : "#334155",
                              fontWeight: 700,
                              transition: "background .15s, border-color .15s" }}>
              <input type="checkbox" data-testid="finalize-defective-toggle"
                      checked={!!form.is_defective}
                      onChange={(e) => setForm({ ...form,
                          is_defective: e.target.checked,
                          defective_reason: e.target.checked
                            ? form.defective_reason : "" })}
                      style={{ width: 20, height: 20, cursor: "pointer",
                                accentColor: "#dc2626" }} />
              <span style={{ flex: 1 }}>
                <span style={{ display: "block", fontSize: 14, fontWeight: 800 }}>
                  ⚠️ Equipamento com defeito
                </span>
                <span style={{ display: "block", fontSize: 11, fontWeight: 500,
                                  color: form.is_defective ? "#991b1b" : "#64748b",
                                  marginTop: 3, lineHeight: 1.4 }}>
                  {form.is_defective
                    ? "✓ Não estará disponível para nova instalação. Devolução obrigatória ao estoque da empresa."
                    : "Marque caso a ONT esteja queimada, com porta solta, sem login, etc."}
                </span>
              </span>
            </label>
            {form.is_defective && (
              <div style={{ marginTop: 8 }}>
                <label style={{ fontSize: 11, color: "#7f1d1d",
                                  fontWeight: 700, display: "block",
                                  marginBottom: 4 }}>
                  Defeito observado (opcional, ajuda o gestor a triar)
                </label>
                <input
                  data-testid="finalize-defective-reason"
                  value={form.defective_reason || ""}
                  onChange={(e) => setForm({ ...form,
                      defective_reason: e.target.value.slice(0, 300) })}
                  placeholder="Ex.: não liga, porta GPON queimada, LED PON apagado..."
                  style={{
                    width: "100%", padding: "10px 12px", borderRadius: 10,
                    border: "1px solid #fca5a5", fontSize: 13,
                    boxSizing: "border-box", fontFamily: "inherit",
                    background: "#fff", color: "#7f1d1d",
                  }}
                />
              </div>
            )}
          </div>
          <label style={{ fontSize: 12, color: "#475569", fontWeight: 700,
                              marginTop: 10, display: "block" }}>
            📝 Detalhes do motivo (obrigatório · mínimo 10 caracteres)
          </label>
          <textarea
            data-testid="finalize-obs-withdraw" value={form.observacoes}
            onChange={(e) => setForm({ ...form, observacoes: e.target.value })}
            rows={4}
            placeholder="Descreva em detalhes o que o cliente relatou. Ex: 'Cliente mencionou que a Vivo ofereceu 600 Mbps por R$ 79,90'."
            style={{
              width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1",
              borderRadius: 10, fontSize: 14, marginTop: 4, marginBottom: 12,
              resize: "vertical", boxSizing: "border-box", fontFamily: "inherit",
            }}
          />
          {err && <Banner color="#fee2e2" border="#dc2626" icon="!" text={err} />}
          <Button
            data-testid="finalize-btn-withdraw"
            disabled={busy || adminBlocks}
            onClick={async () => {
              // Modo Full Unlock bypassa as validações; senão exige categoria + obs.
              if (!isFullUnlock) {
                if (!form.cancel_reason_category) {
                  await window.alert(
                    "🚪 Selecione uma categoria do motivo do cancelamento.");
                  return;
                }
                if ((form.observacoes || "").trim().length < 10) {
                  await window.alert(
                    "📝 Descreva o motivo do cancelamento (mínimo 10 caracteres). " +
                    "Esses detalhes são usados pelo KPI de retenção.");
                  return;
                }
                if (clientInSmartOlt && !form.ont) {
                  await window.alert(
                    "📡 Em retiradas o MAC/SN da ONT é OBRIGATÓRIO.\n\n" +
                    "Toque no 🤖 IA para fotografar a etiqueta — " +
                    "Claude 4.6 lê MAC/SN automaticamente.");
                  return;
                }
                if (clientInSmartOlt && macStatus === "mismatch") {
                  const expected = clientSmart?.mac_expected
                                    || clientSmart?.sn_expected || "?";
                  const ok = await window.confirm(
                    `O MAC (${form.ont}) NÃO bate com o registrado no ` +
                    `SmartOLT (${expected}).\n\nConfirma mesmo assim?`);
                  if (!ok) return;
                }
                if (clientInSmartOlt) {
                  const hasSnPhoto = (form.fotos || [])
                    .some((p) => p.kind === "sn");
                  if (!hasSnPhoto) {
                    await window.alert(
                      "📸 Foto da etiqueta da ONT é OBRIGATÓRIA.\n\n" +
                      "Toque em 🤖 IA — a IA lerá o MAC/SN e a foto " +
                      "fica como prova.");
                    return;
                  }
                }
              }
              await submit();
            }}
            style={{ width: "100%", marginTop: 6, height: 56, fontSize: 16 }}>
            <Icon name="check" /> {busy ? "Finalizando..." : "Finalizar Retirada"}
          </Button>
        </>
      )}

      {/* ============ STEP 2 — Mapa GPS + Foto + VLAN ============ */}
      {step === 2 && (
        <>
          {ctoSelected && ctoPortSelected ? (
            <div data-testid="cto-port-selected-summary"
                  style={{
                    padding: 14, borderRadius: 12,
                    background: "#f0fdf4", border: "1.5px solid #86efac",
                    marginBottom: 12,
                  }}>
              <div style={{ fontSize: 12, color: "#16a34a", fontWeight: 800,
                              textTransform: "uppercase", letterSpacing: 0.5 }}>
                ✓ CTO já registrada
              </div>
              <div style={{ fontSize: 16, fontWeight: 800, marginTop: 4,
                              color: "#0f172a" }}>
                {ctoSelected.name} · Porta {ctoPortSelected}
              </div>
              <button onClick={() => {
                          setCtoSelected(null);
                          setCtoPortSelected(null);
                        }}
                        style={{ marginTop: 8, padding: "6px 10px",
                                  fontSize: 11, fontWeight: 700,
                                  background: "transparent",
                                  border: "1px solid #cbd5e1",
                                  borderRadius: 999, cursor: "pointer",
                                  color: "#475569" }}>
                Trocar / recadastrar
              </button>
              <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                <Button variant="soft" onClick={() => setStep(1)}
                         style={{ flex: 1, height: 48, fontSize: 14 }}>
                  ← Voltar
                </Button>
                <Button onClick={() => setStep(insumosStepNum)}
                         style={{ flex: 2, height: 48, fontSize: 14 }}>
                  Próximo: Insumos →
                </Button>
              </div>
            </div>
          ) : (
            <OsCtoPicker
              collabId={collaboratorId}
              onSelectExistingCto={(cto) => setExistingCtoPick(cto)}
              onBack={() => setStep(1)}
              onSkip={() => setStep(insumosStepNum)}
            />
          )}
        </>
      )}

      {/* Modal de confirmação: usar CTO existente do mapa */}
      {existingCtoPick && (
        <div onClick={() => setExistingCtoPick(null)}
              data-testid="existing-cto-confirm-overlay"
              style={{ position: "fixed", inset: 0, zIndex: 9999,
                        background: "rgba(15,23,42,0.6)",
                        display: "flex", alignItems: "center",
                        justifyContent: "center", padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()}
                data-testid="existing-cto-confirm"
                style={{ background: "#fff", borderRadius: 16,
                          padding: 20, width: "100%", maxWidth: 380,
                          boxShadow: "0 20px 60px rgba(0,0,0,.25)" }}>
            <div style={{ fontSize: 18, fontWeight: 800, color: "#0f172a",
                            marginBottom: 6 }}>
              📍 Usar esta CTO existente?
            </div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a",
                            marginBottom: 4 }}>
              {existingCtoPick.name}
            </div>
            <div style={{ fontSize: 12, color: "#64748b", marginBottom: 12,
                            lineHeight: 1.5 }}>
              VLAN <strong>{existingCtoPick.vlan}</strong> ·{" "}
              {existingCtoPick.capacity} portas ·{" "}
              {(existingCtoPick.ports || []).filter((p) => p.status === "free").length} livres
              {existingCtoPick.splitter ? ` · Splitter ${existingCtoPick.splitter}` : ""}
              <br/>
              Os dados já cadastrados serão usados. Você só precisa{" "}
              <strong>tirar a foto</strong> e <strong>escolher a porta</strong>.
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button data-testid="existing-cto-cancel"
                      onClick={() => setExistingCtoPick(null)}
                      style={{ flex: 1, padding: "12px 14px", borderRadius: 10,
                                background: "#fff", border: "1px solid #cbd5e1",
                                color: "#475569", fontWeight: 600, fontSize: 13,
                                cursor: "pointer" }}>
                Cancelar
              </button>
              <button data-testid="existing-cto-use"
                      onClick={() => {
                        // Pré-preenche todos os dados da CTO existente
                        const c = existingCtoPick;
                        setCtoFlowState((s) => ({
                          ...s,
                          existingCtoId: c.id,
                          existingPorts: c.ports || [],
                          gps: { lat: c.gps?.lat || c.lat,
                                  lng: c.gps?.lng || c.lng, accuracy: null },
                          address: {
                            ...(s.address || {}),
                            endereco: c.address?.rua || s.address?.endereco || "",
                            numero: c.address?.numero || s.address?.numero || "",
                            bairro_detected: c.address?.bairro
                                                || s.address?.bairro_detected || "",
                            cidade_detected: c.address?.cidade
                                                || s.address?.cidade_detected || "",
                            estado_detected: c.address?.estado
                                                || s.address?.estado_detected || "",
                          },
                          vlan: c.vlan ? String(c.vlan) : "",
                          capacity: c.capacity || null,
                          networkType: c.network_type || null,
                          splitter: c.splitter || null,
                          clientPort: null,
                          // iter211au — preserva nomenclatura/identificação
                          // da CTO existente pra exibir em destaque no Step 3.
                          ctoName: c.name || c.nome || null,
                          ctoNumber: c.number || c.cto_number || null,
                        }));
                        setCtoSelected(c);
                        setExistingCtoPick(null);
                        // Vai pra tela B (foto + porta) — usuário ainda precisa
                        // tirar foto E escolher porta
                        setStep(3);
                      }}
                      style={{ flex: 2, padding: "12px 14px", borderRadius: 10,
                                background: "#0f766e", border: 0,
                                color: "#fff", fontWeight: 700, fontSize: 14,
                                cursor: "pointer" }}>
                ✓ Usar esta CTO
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ============ STEP 3 — Porta do cliente (CTO EXISTENTE) ============
          iter211av — Esta tela só aparece quando o técnico selecionou
          uma CTO EXISTENTE no mapa (Step 1). Não há mais fluxo de cadastro
          de CTO dentro da OS — cadastro só pelo módulo Rede no Início da
          Lousa. Se chegar aqui sem CTO selecionada, redireciona pra
          Finalização (não bloqueia o técnico). */}
      {step === 3 && !ctoFlowState.existingCtoId && (() => {
        // useEffect síncrono no render — chama setStep no próximo tick
        setTimeout(() => setStep(insumosStepNum), 0);
        return (
          <div style={{ padding: 24, textAlign: "center", color: "#64748b",
                          fontSize: 13 }}>
            Pulando seleção de CTO…
          </div>
        );
      })()}
      {step === 3 && ctoFlowState.existingCtoId && (
        <CtoInlineFlow
          screen="B"
          state={ctoFlowState}
          setState={setCtoFlowState}
          collabId={collaboratorId}
          client={{ id: ticket?.client_id,
                      name: ticket?.client_snapshot?.name }}
          technician={{ id: collaboratorId,
                          name: ticket?.client_snapshot?.collaborator_name }}
          isFullUnlock={isFullUnlock}
          ctoPhotoRequired={ctoPhotoRequired}
          onBackFromB={() => setStep(2)}
          onCreated={async ({ cto, port_number, photo }) => {
            // Modo "CTO existente": ctoSelected já está setado
            if (cto && cto.id && !ctoSelected) {
              setCtoSelected(cto);
            }
            setCtoPortSelected(port_number);
            // Adiciona a foto da CTO ao laudo de fotos do completion
            if (photo) {
              const compPhoto = await compressDataUrl(photo, 1280, 0.78);
              setForm((f) => ({
                ...f,
                fotos: [...(f.fotos || []),
                          { kind: "cto", dataUrl: compPhoto }],
              }));
            }
            setStep(insumosStepNum);
          }}
        />
      )}

      {/* ============ STEP DE INSUMOS — último step ============ */}
      {step === insumosStepNum && (
        <>
          {/* iter182 — Bloco "Troca de ONT/ONU" movido para cá (acima dos
              insumos). MAC da ONT RETIRADA é auto-preenchido a partir do
              SmartOLT (clientSmart) quando o cliente já tem mapeamento. */}
          {isRepair && (
            <div data-testid="repair-swap-section" style={{ marginBottom: 14 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 10,
                                padding: "10px 12px", borderRadius: 10,
                                background: form.isSwap ? "#eef2ff" : "#f8fafc",
                                border: `1px solid ${form.isSwap ? "#6366f1" : "#cbd5e1"}`,
                                cursor: "pointer", fontSize: 13.5,
                                color: form.isSwap ? "#3730a3" : "#334155",
                                fontWeight: 700 }}>
                <input type="checkbox" data-testid="repair-swap-toggle"
                        checked={form.isSwap}
                        onChange={(e) => setForm({
                          ...form, isSwap: e.target.checked })}
                        style={{ width: 18, height: 18, cursor: "pointer" }} />
                🔁 Foi troca de ONT/ONU neste atendimento?
              </label>
              {form.isSwap && (
                <div style={{ marginTop: 10, padding: 12, borderRadius: 10,
                                background: "#fefce8",
                                border: "1px solid #fde68a" }}>
                  {clientInSmartOlt && (
                    <div style={{ marginBottom: 8, fontSize: 11.5,
                                    color: "#92400e", lineHeight: 1.5 }}>
                      💡 MAC esperado do cliente (SmartOLT):{" "}
                      <code style={{ fontFamily: "monospace",
                                       fontWeight: 800 }}>
                        {(clientSmart?.mac_expected
                          || clientSmart?.sn_expected
                          || "?").toUpperCase()}
                      </code>
                      {form.old_ont_mac && (
                        <span data-testid="repair-old-mac-autofilled"
                              style={{ marginLeft: 6,
                                         color: "#15803d",
                                         fontWeight: 700 }}>
                          · preenchido automaticamente ✓
                        </span>
                      )}
                    </div>
                  )}
                  <label style={{ fontSize: 12, color: "#475569",
                                    fontWeight: 700 }}>
                    📤 MAC/SN da ONT RETIRADA (antigo)
                  </label>
                  <input
                    data-testid="repair-old-mac"
                    value={form.old_ont_mac}
                    onChange={(e) => setForm({
                      ...form,
                      old_ont_mac: e.target.value.trim().toUpperCase(),
                    })}
                    placeholder="Ex.: HWTC12345678 (SN) ou AA:BB:CC:DD:EE:FF (MAC)"
                    style={{ width: "100%", padding: "10px 12px",
                              border: "1px solid #cbd5e1", borderRadius: 10,
                              fontSize: 14, fontFamily: "monospace",
                              textTransform: "uppercase",
                              boxSizing: "border-box",
                              marginTop: 4, marginBottom: 10 }}
                  />
                  <label style={{ fontSize: 12, color: "#475569",
                                    fontWeight: 700 }}>
                    📥 ONT/ONU NOVA (instalada) — escolha do seu estoque
                  </label>
                  {/* iter182 — Seleção a partir do estoque do técnico (não
                      mais input livre). Garante rastreabilidade do
                      equipamento e baixa automática no inventário. */}
                  {(techOnts.novos || techOnts.retirados || []).length > 0 ||
                   ((techOnts.novos || []).length
                     + (techOnts.retirados || []).length) > 0 ? (
                    <select
                      data-testid="repair-new-mac"
                      value={form.new_ont_mac}
                      onChange={(e) => setForm({
                        ...form,
                        new_ont_mac: e.target.value.toUpperCase(),
                      })}
                      style={{ width: "100%", padding: "10px 12px",
                                border: "1px solid #cbd5e1", borderRadius: 10,
                                fontSize: 14, fontFamily: "monospace",
                                background: form.new_ont_mac
                                  ? "#dcfce7" : "white",
                                color: "#0f172a", outline: "none",
                                boxSizing: "border-box", marginTop: 4 }}>
                      <option value="">
                        — Selecione uma ONT do meu estoque —
                      </option>
                      {(techOnts.novos || []).length > 0 && (
                        <optgroup label="🆕 Novos (do almoxarifado)">
                          {(techOnts.novos || []).map((o) => (
                            <option key={`new-${o.mac}`} value={o.mac}>
                              {o.mac}
                              {o.sn ? ` · SN ${o.sn}` : ""}
                              {o.model ? ` · ${o.model}` : ""}
                            </option>
                          ))}
                        </optgroup>
                      )}
                      {(techOnts.retirados || []).length > 0 && (
                        <optgroup label="♻️ Retirados (reaproveitar)">
                          {(techOnts.retirados || []).map((o) => (
                            <option key={`reu-${o.mac}`} value={o.mac}>
                              {o.mac}
                              {o.sn ? ` · SN ${o.sn}` : ""}
                              {o.model ? ` · ${o.model}` : ""}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </select>
                  ) : (
                    <div data-testid="repair-new-mac-empty" style={{
                      padding: "10px 12px", borderRadius: 10,
                      background: "#fef2f2", color: "#991b1b",
                      fontSize: 11.5, marginTop: 4,
                      border: "1px solid #fecaca", lineHeight: 1.5,
                    }}>
                      ⚠️ Você não tem ONTs no seu estoque. Peça ao gestor
                      para fazer uma transferência antes de finalizar
                      esta troca.
                    </div>
                  )}
                  <p style={{ margin: "8px 0 0 0", fontSize: 11,
                                color: "#92400e", lineHeight: 1.5 }}>
                    Ambos os MACs serão gravados na OS finalizada para
                    auditoria e rastreabilidade do equipamento.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* CARD OBRIGATÓRIO: Wizard de 3 fotos — apenas para OS de
              instalação ou reparo. Foto 1 = CTO, Foto 2 = Equipamento
              ONT/ONU, Foto 3 = etiqueta MAC/SN do equipamento.
              Consolida toda a captura num único botão sequencial.
              Pedido do user 28/05/2026.
              iter211aj — Respeita toggles `cto_photo_required` e
              `mac_validation_required`. Se ambos OFF, card some. */}
          {(isInstall || isRepair)
           && (ctoPhotoRequired || macValidationRequired) && (() => {
            const fotos = form.fotos || [];
            const needCto = !!ctoPhotoRequired;
            const needEquip = !!macValidationRequired;
            const needSn = !!macValidationRequired;
            const hasCto = fotos.some((p) => p.kind === "cto");
            const hasEquip = fotos.some((p) => p.kind === "equipamento");
            const hasSn = fotos.some((p) => p.kind === "sn");
            // iter199 — CTO recém-cadastrada (< 5 dias) dispensa a foto
            const ctoRecent = !!ctoRecentInfo?.is_recent;
            const stagesAll = [
              { key: "cto", label: "Foto da CTO",
                enabled: needCto,
                hint: ctoRecent
                  ? `✅ CTO cadastrada há ${Math.round(ctoRecentInfo.days_since)} dia(s) — foto dispensada.`
                  : "Tire uma foto da caixa CTO onde o cliente foi conectado.",
                icon: "📦", done: hasCto || ctoRecent,
                skipped: ctoRecent && !hasCto },
              { key: "equipamento", label: "Foto do Equipamento",
                enabled: needEquip,
                hint: "Tire uma foto do equipamento (ONT/ONU) instalado no cliente.",
                icon: "📡", done: hasEquip },
              { key: "sn", label: "Foto do MAC/SN",
                enabled: needSn,
                hint: "Tire uma foto da etiqueta com MAC/SN do equipamento (leitura por IA).",
                icon: "🏷️", done: hasSn },
            ];
            const stages = stagesAll.filter((s) => s.enabled);
            if (stages.length === 0) return null;
            const totalNeeded = stages.length;
            const doneCount = stages.filter((s) => s.done).length;
            const allDone = doneCount === totalNeeded;
            // Próxima foto a capturar (a primeira não tirada e não skipped)
            const nextStage = stages.find((s) => !s.done && !s.skipped);
            return (
              <div data-testid="finalize-photos-wizard" style={{
                padding: 14, borderRadius: 12, marginBottom: 12,
                background: allDone
                  ? "linear-gradient(135deg,#f0fdf4 0%,#dcfce7 100%)"
                  : "linear-gradient(135deg,#fffbeb 0%,#fef3c7 100%)",
                border: `2px solid ${allDone ? "#86efac" : "#fcd34d"}`,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10,
                                  marginBottom: 10 }}>
                  <span style={{ fontSize: 22 }}>📸</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 800,
                                      color: allDone ? "#166534" : "#92400e" }}>
                      {allDone
                        ? `Fotos completas (${doneCount}/${totalNeeded})`
                        : `Fotos pendentes (${doneCount}/${totalNeeded})`}
                    </div>
                    <div style={{ fontSize: 11,
                                      color: allDone ? "#15803d" : "#78350f",
                                      marginTop: 2, lineHeight: 1.4 }}>
                      {allDone
                        ? "Todas as fotos foram capturadas. Você já pode finalizar a OS."
                        : (nextStage?.hint
                          || `Capture as ${totalNeeded} foto(s) antes de finalizar.`)}
                    </div>
                  </div>
                </div>

                {/* Progressão visual: 3 chips */}
                <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
                  {stages.map((s) => (
                    <div key={s.key}
                          data-testid={`finalize-photo-chip-${s.key}`}
                          style={{
                            flex: 1, display: "flex", alignItems: "center",
                            gap: 6, padding: "6px 8px", borderRadius: 8,
                            background: s.done ? "#16a34a" : "#fff",
                            border: s.done ? "1px solid #15803d"
                                              : "1px dashed #fca5a5",
                            fontSize: 10, fontWeight: 800,
                            color: s.done ? "#fff" : "#991b1b",
                          }}>
                      <span style={{ fontSize: 13 }}>
                        {s.done ? "✓" : s.icon}
                      </span>
                      <span style={{ overflow: "hidden",
                                       textOverflow: "ellipsis",
                                       whiteSpace: "nowrap" }}>
                        {s.label.replace("Foto ", "").replace("d", "").replace("o ", "")}
                      </span>
                    </div>
                  ))}
                </div>

                {/* Input file único — define o kind dinamicamente */}
                <input
                  ref={equipPhotoInputRef}
                  type="file" accept="image/*" capture="environment"
                  data-testid="finalize-photo-input"
                  style={{ display: "none" }}
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    const kindToSet = equipPhotoInputRef.current?._kind || "equipamento";
                    e.target.value = "";
                    // 3ª foto = MAC/SN — reaproveita o pipeline OCR Claude
                    // 4.6 da retirada: salva foto + preenche form.ont
                    // automaticamente (iter151).
                    if (kindToSet === "sn") {
                      await captureSnPhoto(f);
                      return;
                    }
                    // iter211y v2 — foto-first UX: comprime e salva a foto crua
                    // IMEDIATAMENTE (não trava no fetch Nominatim). O selo é
                    // aplicado em background com timeout de 7s e substitui a
                    // dataUrl quando pronto.
                    const reqItem = (photoReqs || []).find((r) => r.id === kindToSet);
                    const shouldStamp = reqItem
                      ? !!reqItem.stamp_location
                      : (kindToSet === "cto" || kindToSet === "ce");
                    let gpsForStamp = null;
                    if (shouldStamp && navigator.geolocation) {
                      gpsForStamp = await new Promise((res) => {
                        navigator.geolocation.getCurrentPosition(
                          (p) => res({ lat: p.coords.latitude,
                                        lng: p.coords.longitude }),
                          () => res(null),
                          { enableHighAccuracy: true, timeout: 4500, maximumAge: 15000 },
                        );
                      });
                    }
                    const reader = new FileReader();
                    reader.onload = () => {
                      const img = new Image();
                      img.onload = () => {
                        const max = 1280;
                        const scale = Math.min(1, max / Math.max(img.width, img.height));
                        const w = Math.round(img.width * scale);
                        const h = Math.round(img.height * scale);
                        const canvas = document.createElement("canvas");
                        canvas.width = w; canvas.height = h;
                        const ctx = canvas.getContext("2d");
                        ctx.drawImage(img, 0, 0, w, h);
                        const dataUrl = canvas.toDataURL("image/jpeg", 0.78);
                        // Salva foto crua imediatamente
                        const setRawPhoto = (url) => setForm((s) => ({
                          ...s,
                          fotos: [
                            ...(s.fotos || []).filter((p) => p.kind !== kindToSet),
                            { kind: kindToSet, dataUrl: url },
                          ],
                        }));
                        setRawPhoto(dataUrl);
                        // Aplica selo em background (best-effort, com timeout 7s)
                        if (shouldStamp) {
                          const stampLabel = reqItem
                            ? `${reqItem.icon || "📷"} ${reqItem.label || ""}`.trim()
                            : (kindToSet === "cto" ? "📦 FOTO CTO" : "🏢 FOTO CE");
                          // iter211az — colaborador + nomenclatura da CTO/CE
                          const collabName = data?.collaborator?.name || "";
                          const elementName = ctoSelected?.name
                                                || ctoFlowState?.ctoName
                                                || (ctoSelected?.vlan && ctoSelected?.number
                                                      ? `CTO_${ctoSelected.vlan}_${String(ctoSelected.number).padStart(4, "0")}`
                                                      : "");
                          const stampPromise = stampFieldPhoto(dataUrl, {
                            lat: gpsForStamp?.lat,
                            lng: gpsForStamp?.lng,
                            label: stampLabel,
                            collaborator: collabName,
                            element: elementName,
                          });
                          const timeoutPromise = new Promise((resolve) =>
                            setTimeout(() => resolve(dataUrl), 7000));
                          Promise.race([stampPromise, timeoutPromise])
                            .then((stamped) => {
                              if (stamped && stamped !== dataUrl) setRawPhoto(stamped);
                            })
                            .catch(() => { /* silencioso */ });
                        }
                      };
                      img.onerror = () => { /* swallow */ };
                      img.src = reader.result;
                    };
                    reader.onerror = () => { /* swallow */ };
                    reader.readAsDataURL(f);
                  }}
                />

                {!allDone ? (
                  <>
                    <button
                      type="button"
                      data-testid="finalize-open-photo"
                      disabled={ocrBusy}
                      onClick={() => {
                        // Define o kind da próxima foto a capturar
                        if (equipPhotoInputRef.current) {
                          equipPhotoInputRef.current._kind = nextStage?.key;
                        }
                        equipPhotoInputRef.current?.click();
                      }}
                      style={{
                        width: "100%", padding: "12px 14px", borderRadius: 10,
                        background: ocrBusy ? "#94a3b8"
                          : "linear-gradient(135deg,#0ea5e9,#0284c7)",
                        border: 0, color: "white", fontSize: 14, fontWeight: 800,
                        cursor: ocrBusy ? "wait" : "pointer",
                        display: "inline-flex", justifyContent: "center",
                        alignItems: "center", gap: 8,
                      }}>
                      <span style={{ fontSize: 18 }}>{nextStage?.icon || "📸"}</span>
                      {ocrBusy && nextStage?.key === "sn"
                        ? "🤖 IA lendo MAC/SN..."
                        : `Tirar ${nextStage?.label?.toLowerCase() || "próxima foto"} (${stages.filter((s)=>s.done).length + 1}/3)`}
                    </button>
                    {nextStage?.key === "sn" && (
                      <div style={{
                        marginTop: 6, fontSize: 10, color: "#7f1d1d",
                        lineHeight: 1.4, fontWeight: 600,
                      }}>
                        🤖 A IA Claude 4.6 lerá o MAC/SN automaticamente da etiqueta.
                      </div>
                    )}
                  </>
                ) : (
                  <div style={{ display: "flex", gap: 6 }}>
                    {stages.map((s) => (
                      <button key={s.key}
                                type="button"
                                data-testid={`finalize-photo-retake-${s.key}`}
                                onClick={() => {
                                  if (equipPhotoInputRef.current) {
                                    equipPhotoInputRef.current._kind = s.key;
                                  }
                                  equipPhotoInputRef.current?.click();
                                }}
                                style={{
                                  flex: 1, padding: "8px 4px",
                                  borderRadius: 8,
                                  background: "#fff",
                                  border: "1px solid #86efac",
                                  color: "#166534",
                                  fontSize: 10, fontWeight: 800,
                                  cursor: "pointer",
                                  display: "flex", alignItems: "center",
                                  justifyContent: "center", gap: 4,
                                }}>
                      <span>↺</span>
                      <span>{s.icon}</span>
                      </button>
                    ))}
                  </div>
                )}

                {/* Badge MAC detectado pela IA quando 3 fotos OK */}
                {allDone && form.ont && (
                  <div data-testid="finalize-mac-detected" style={{
                    marginTop: 10, padding: "8px 10px",
                    background: "rgba(255,255,255,0.7)",
                    border: "1px solid #16a34a", borderRadius: 8,
                    display: "flex", alignItems: "center", gap: 8,
                    fontSize: 11, color: "#166534", fontWeight: 700,
                  }}>
                    <span style={{ fontSize: 14 }}>🤖</span>
                    <span>MAC lido pela IA:</span>
                    <code style={{
                      fontFamily: "monospace", fontSize: 12,
                      background: "#fff", padding: "2px 6px",
                      borderRadius: 4, color: "#0f172a",
                      letterSpacing: 0.5,
                    }}>{form.ont}</code>
                  </div>
                )}

                {/* iter153 — Divergência ONT estoque × MAC lido pela IA */}
                {macMismatch && (
                  <div data-testid="finalize-mac-mismatch" style={{
                    marginTop: 10, padding: "10px 12px",
                    background: "#fef2f2", border: "1.5px solid #dc2626",
                    borderRadius: 10, fontSize: 11.5,
                    color: "#7f1d1d", lineHeight: 1.5,
                  }}>
                    <div style={{ fontWeight: 800, marginBottom: 6,
                                     fontSize: 12, color: "#991b1b",
                                     display: "flex", alignItems: "center", gap: 6 }}>
                      <span>⚠️</span> ATENÇÃO: MAC divergente do estoque
                    </div>
                    <div style={{ marginBottom: 4 }}>
                      Equipamento selecionado do estoque:{" "}
                      <code style={{ background: "#fff", padding: "1px 5px",
                                       borderRadius: 4, fontWeight: 800 }}>
                        {macMismatch.stock}
                      </code>
                    </div>
                    <div style={{ marginBottom: 6 }}>
                      MAC lido pela IA na etiqueta:{" "}
                      <code style={{ background: "#fff", padding: "1px 5px",
                                       borderRadius: 4, fontWeight: 800,
                                       color: "#dc2626" }}>
                        {macMismatch.scanned}
                      </code>
                    </div>
                    <div style={{ fontSize: 10.5, fontWeight: 600,
                                     color: "#7f1d1d" }}>
                      Você selecionou uma ONT do seu estoque, mas a etiqueta
                      lida é de outro equipamento. Confirme qual está
                      realmente sendo instalado antes de finalizar — a
                      transferência de estoque usará o MAC final.
                    </div>
                    <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                      <button
                        type="button"
                        data-testid="mac-mismatch-keep-scanned"
                        onClick={() => setMacMismatch(null)}
                        style={{
                          flex: 1, padding: "6px 8px", borderRadius: 6,
                          background: "#dc2626", color: "#fff", border: 0,
                          fontSize: 11, fontWeight: 800, cursor: "pointer",
                        }}>
                        Confirmar MAC da etiqueta
                      </button>
                      <button
                        type="button"
                        data-testid="mac-mismatch-revert-stock"
                        onClick={() => {
                          setForm((f) => ({ ...f, ont: macMismatch.stock }));
                          setMacMismatch(null);
                        }}
                        style={{
                          flex: 1, padding: "6px 8px", borderRadius: 6,
                          background: "#fff", color: "#7f1d1d",
                          border: "1px solid #dc2626",
                          fontSize: 11, fontWeight: 800, cursor: "pointer",
                        }}>
                        Voltar p/ MAC do estoque
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })()}

          {/* Preview das fotos anexadas — confirma visualmente antes de finalizar */}
          {(form.fotos || []).length > 0 && (
            <div data-testid="finalize-photos-preview" style={{
              padding: "10px 12px", background: "#f0fdf4",
              border: "1px solid #86efac", borderRadius: 12, marginBottom: 12,
            }}>
              <div style={{ fontSize: 10, fontWeight: 800, color: "#15803d",
                                textTransform: "uppercase", letterSpacing: 0.5,
                                marginBottom: 6 }}>
                📸 Fotos anexadas ({(form.fotos || []).length})
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {(form.fotos || []).map((f, idx) => (
                  <div key={idx}
                          data-testid={`finalize-photo-thumb-${idx}`}
                          style={{
                            position: "relative", width: 64, height: 64,
                            borderRadius: 8, overflow: "hidden",
                            border: "1px solid #86efac",
                            background: "#fff",
                          }}>
                    <img src={f.dataUrl || f}
                            alt={f.kind || "foto"}
                            style={{ width: "100%", height: "100%",
                                        objectFit: "cover" }} />
                    {f.kind && (
                      <span style={{
                        position: "absolute", bottom: 0, left: 0, right: 0,
                        background: "rgba(15,23,42,0.7)", color: "white",
                        fontSize: 8, fontWeight: 800, textAlign: "center",
                        padding: "1px 0", textTransform: "uppercase",
                        letterSpacing: 0.3,
                      }}>
                        {f.kind === "cto" ? "CTO" : f.kind === "sn" ? "SN" : f.kind === "equipamento" ? "ONT" : f.kind}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TESTE IPv6 OPCIONAL — controlado por toggle empresa-wide
              (iter155). Só p/ instalacao/reparo/troca/ponto_adicional.
              Modo full unlock (Vando/super_admin) NÃO renderiza. */}
          {["instalacao", "troca", "troca_endereco", "reparo",
              "ponto_adicional"].includes(ticket.type) && !isFullUnlock
              && ipv6TestRequired && (
            <>
              <Ipv6TestStep ticketId={ticket.id}
                              autoRun={true}
                              onResult={(r) => setIpv6Result(r)} />
              <PingAutoStep ticketId={ticket.id} autoRun={true} />
            </>
          )}
          {/* Ping continua sendo executado mesmo quando IPv6 está desligado */}
          {["instalacao", "troca", "troca_endereco", "reparo",
              "ponto_adicional"].includes(ticket.type) && !isFullUnlock
              && !ipv6TestRequired && (
            <PingAutoStep ticketId={ticket.id} autoRun={true} />
          )}

          {/* SELETOR DE ONT/ONU DO ESTOQUE DO TÉCNICO — só pra instalação/troca */}
          {(isInstall || ticket.type === "troca" || ticket.type === "troca_endereco"
            || ticket.type === "ponto_adicional") && (
            <div data-testid="ont-stock-selector-insumos" style={{
              padding: "12px 14px", background: "white",
              border: "1px solid #fde68a", borderRadius: 14, marginBottom: 12,
            }}>
              <div style={{ fontSize: 12, fontWeight: 800, color: "#0369a1",
                              marginBottom: 8, letterSpacing: 0.5,
                              textTransform: "uppercase",
                              display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span>📦 ONT/ONU a instalar</span>
                <span style={{ fontSize: 10, color: "#64748b", fontWeight: 500,
                                 textTransform: "none", letterSpacing: 0 }}>
                  Estoque: {((techOnts.novos || []).length + (techOnts.retirados || []).length)} disponíveis
                </span>
              </div>
              <select
                data-testid="ont-stock-select-insumos"
                value={form.ont || ""}
                onChange={(e) => {
                  const mac = e.target.value;
                  setForm((s) => ({ ...s, ont: mac }));
                }}
                style={{
                  width: "100%", padding: "10px 12px", borderRadius: 10,
                  border: "1px solid #cbd5e1", fontSize: 13,
                  fontFamily: "monospace", textTransform: "uppercase",
                  background: form.ont ? "#dcfce7" : "white",
                  color: "#0f172a", outline: "none",
                }}>
                <option value="">— Selecione uma ONT do meu estoque —</option>
                {(techOnts.novos || []).length > 0 && (
                  <optgroup label="🆕 Novos (do almoxarifado)">
                    {(techOnts.novos || []).map((o) => (
                      <option key={o.mac} value={o.mac}>
                        {o.mac} {o.sn ? `· SN ${o.sn}` : ""} {o.model ? `· ${o.model}` : ""}
                      </option>
                    ))}
                  </optgroup>
                )}
                {(techOnts.retirados || []).length > 0 && (
                  <optgroup label="♻️ Retirados (reaproveitar)">
                    {(techOnts.retirados || []).map((o) => (
                      <option key={o.mac} value={o.mac}>
                        {o.mac} {o.sn ? `· SN ${o.sn}` : ""} {o.model ? `· ${o.model}` : ""}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
              {form.ont && (
                <div style={{ fontSize: 11, color: "#15803d", marginTop: 6, fontWeight: 700 }}>
                  ✓ ONT {form.ont} selecionada do seu estoque
                </div>
              )}
              {!form.ont && ((techOnts.novos || []).length + (techOnts.retirados || []).length) === 0 && (
                <div style={{ fontSize: 11, color: "#991b1b", marginTop: 6 }}>
                  ⚠️ Você não tem ONTs no estoque. Peça ao gestor para fazer uma transferência.
                </div>
              )}
            </div>
          )}

          {/* INSUMOS FTTH */}
          <div style={{
            padding: "12px 14px", background: "white",
            border: "1px solid #fde68a", borderRadius: 14, marginBottom: 12,
          }}>
            <div style={{ fontSize: 12, fontWeight: 800, color: "#ca8a04",
                            marginBottom: 8, letterSpacing: 0.5,
                            textTransform: "uppercase" }}>
              🌐 Insumo FTTH
              {stock && (
                <span style={{ fontSize: 10, color: "#64748b",
                                 fontWeight: 500, marginLeft: 6,
                                 textTransform: "none", letterSpacing: 0 }}>
                  · estoque: {stock.collaborator_name}
                </span>
              )}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <ConsumableField label="Drop (m)" fieldKey="qtd_drop"
                                consumableId="drop" consMap={consMap}
                                form={form} setForm={setForm} />
              <ConsumableField label="Esticador (un)" fieldKey="esticadores"
                                consumableId="esticador" consMap={consMap}
                                form={form} setForm={setForm} />
              <ConsumableField label="Conector fast (un)" fieldKey="conectores_fast"
                                consumableId="conector_fast" consMap={consMap}
                                form={form} setForm={setForm} />
            </div>
          </div>

          {/* INSUMOS REDE */}
          <div style={{
            padding: "12px 14px", background: "white",
            border: "1px solid #bfdbfe", borderRadius: 14, marginBottom: 12,
          }}>
            <div style={{ fontSize: 12, fontWeight: 800, color: "#1d4ed8",
                            marginBottom: 8, letterSpacing: 0.5,
                            textTransform: "uppercase" }}>
              🖧 Rede
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <ConsumableField label="Cabo rede (m)" fieldKey="cabo_rede"
                                consumableId="cabo_rede" step="0.5"
                                consMap={consMap}
                                form={form} setForm={setForm} />
              <ConsumableField label="Conector rede (un)" fieldKey="conectores_rede"
                                consumableId="conector_rede" consMap={consMap}
                                form={form} setForm={setForm} />
            </div>
          </div>

          {/* INSUMOS BACKBONE (fibras ópticas multi-FO — só mostra se o
              técnico tiver saldo de alguma. Útil pra técnicos de rede). */}
          {(((consMap.fibra_06fo?.qty || 0)
             + (consMap.fibra_12fo?.qty || 0)
             + (consMap.fibra_24fo?.qty || 0)) > 0) && (
            <div style={{
              padding: "12px 14px", background: "white",
              border: "1px solid #c7d2fe", borderRadius: 14, marginBottom: 12,
            }}>
              <div style={{ fontSize: 12, fontWeight: 800, color: "#4338ca",
                              marginBottom: 8, letterSpacing: 0.5,
                              textTransform: "uppercase" }}>
                🧵 Backbone / Fibra Óptica
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                {(consMap.fibra_06fo?.qty || 0) > 0 && (
                  <ConsumableField label="06FO (m)" fieldKey="fibra_06fo"
                                    consumableId="fibra_06fo" step="0.5"
                                    consMap={consMap}
                                    form={form} setForm={setForm} />
                )}
                {(consMap.fibra_12fo?.qty || 0) > 0 && (
                  <ConsumableField label="12FO (m)" fieldKey="fibra_12fo"
                                    consumableId="fibra_12fo" step="0.5"
                                    consMap={consMap}
                                    form={form} setForm={setForm} />
                )}
                {(consMap.fibra_24fo?.qty || 0) > 0 && (
                  <ConsumableField label="24FO (m)" fieldKey="fibra_24fo"
                                    consumableId="fibra_24fo" step="0.5"
                                    consMap={consMap}
                                    form={form} setForm={setForm} />
                )}
              </div>
            </div>
          )}

          <label style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
            📝 Observações
          </label>
          <textarea
            data-testid="finalize-obs" value={form.observacoes}
            onChange={(e) => setForm({ ...form, observacoes: e.target.value })}
            rows={3}
            placeholder="Detalhes do serviço, materiais especiais, etc."
            style={{
              width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1",
              borderRadius: 10, fontSize: 14, marginTop: 4, marginBottom: 12,
              resize: "vertical", boxSizing: "border-box", fontFamily: "inherit",
            }}
          />

          {/* Removido: botão manual de Ping (substituído por PingAutoStep abaixo do IPv6) */}

          {err && <Banner color="#fee2e2" border="#dc2626" icon="!" text={err} />}

          <div style={{ display: "flex", gap: 8 }}>
            <Button onClick={() => setStep(insumosStepNum - 1)} variant="soft"
                     data-testid="finalize-back-btn"
                     style={{ flex: 1, height: 52, fontSize: 14 }}>
              ← Voltar
            </Button>
            {(() => {
              // iter155 — IPv6 só vira "obrigatório" se o toggle empresa-wide
              // estiver ligado (default: desligado, pedido user).
              const ipv6Required = ipv6TestRequired
                                       && ["instalacao", "troca", "troca_endereco",
                                       "reparo", "ponto_adicional"].includes(ticket.type)
                                       && !isFullUnlock;
              const ipv6Pending = ipv6Required && !ipv6Result;
              const ontPhotoPending = !isFullUnlock && macValidationRequired
                && (isInstall || isRepair)
                && !(form.fotos || []).some((p) => p.kind === "equipamento");
              // iter166 — Foto da CTO obrigatória (toggle empresa-wide)
              // iter199 — Pula se CTO < 5 dias de cadastro
              const ctoPhotoRequiredHere = ctoPhotoRequired
                && ["instalacao", "reparo", "troca", "ponto_adicional"].includes(ticket.type)
                && !isFullUnlock
                && !ctoRecentInfo?.is_recent;
              const ctoPhotoPending = ctoPhotoRequiredHere
                && !(form.fotos || []).some((p) => p.kind === "cto");
              // iter182 — Trava: se marcou "Foi troca de ONT/ONU",
              // exige MAC da ONT NOVA (escolhida do estoque) antes de
              // permitir finalizar. Poupa o técnico de receber 422 do
              // backend depois.
              const swapNewMacPending = isRepair
                && form.isSwap
                && !form.new_ont_mac
                && !isFullUnlock;
              const disabled = busy || adminBlocks || ipv6Pending
                || ontPhotoPending || ctoPhotoPending || swapNewMacPending;
              return (
                <Button onClick={submit} disabled={disabled}
                         data-testid="finalize-btn"
                         title={adminBlocks
                           ? "Modo gestor — não é possível finalizar bolha alheia"
                           : ipv6Pending ? "Aguarde o Teste IPv6 concluir"
                           : ontPhotoPending ? "Foto da ONT/ONU obrigatória"
                           : ctoPhotoPending ? "Foto da CTO obrigatória"
                           : swapNewMacPending
                              ? "Selecione a ONT NOVA do seu estoque"
                              : undefined}
                         style={{ flex: 2, height: 52, fontSize: 15,
                                    opacity: disabled ? 0.5 : 1 }}>
                  <Icon name="check" /> {adminBlocks
                    ? "🔒 Modo gestor"
                    : ipv6Pending ? "⏳ Aguarde teste IPv6"
                    : ontPhotoPending ? "📷 Foto da ONT/ONU"
                    : ctoPhotoPending ? "📷 Foto da CTO"
                    : swapNewMacPending ? "📦 Selecione ONT NOVA"
                    : (busy ? "Finalizando..." : "Finalizar nota")}
                </Button>
              );
            })()}
          </div>
          {/* Saída alternativa: técnico não consegue executar — chama gestor */}
        </>
      )}

      {showQR && (
        <QRScannerModal
          onClose={() => setShowQR(false)}
          onScan={(text) => {
            // Normaliza: maiúsculas + remove espaços, mantém alfanum + ":"
            const cleaned = (text || "").trim().toUpperCase().replace(/[^A-Z0-9:]/g, "");
            setForm((f) => ({ ...f, ont: cleaned }));
            setShowQR(false);
          }}
        />
      )}

      {/* Scan IA: Claude 4.6 lê MAC/SN da etiqueta com viewfinder */}
      <OntScanModal
        open={showOntScan}
        usePublic={true}
        hint={ticket?.client_snapshot?.ont_model || ticket?.ont_model || ""}
        isFullUnlock={isFullUnlock}
        expectedMac={clientSmart?.mac_expected || clientSmart?.sn_expected
                      || ticket?.live_signal?.sn || ""}
        onClose={() => setShowOntScan(false)}
        onScanned={async (data) => {
          const chosen = data.mac || data.sn;
          if (chosen) {
            // iter211g — comprime a foto antes de embarcar no form
            const rawUrl = `data:image/jpeg;base64,${data.image_base64}`;
            const compUrl = await compressDataUrl(rawUrl, 1280, 0.78);
            setForm((f) => ({
              ...f,
              ont: chosen.toUpperCase(),
              // Guarda a foto da etiqueta como prova
              fotos: [
                ...(f.fotos || []).filter((p) => p.kind !== "sn"),
                { kind: "sn", dataUrl: compUrl },
              ],
            }));
            setOcrResult({
              best: chosen,
              confidence: Math.round((data.confidence || 0) * 100) + "%",
              mac: data.mac, sn: data.sn,
            });
          }
          setShowOntScan(false);
        }}
      />

      {/* Bottom Sheet: Selecionar ONT do estoque do técnico */}
      {showStockPicker && (
        <div
          onClick={() => setShowStockPicker(false)}
          data-testid="ont-stock-picker-overlay"
          style={{
            position: "fixed", inset: 0,
            background: "rgba(15,23,42,.6)", zIndex: 9999,
            display: "flex", alignItems: "flex-end",
            justifyContent: "center",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            data-testid="ont-stock-picker"
            style={{
              background: "white",
              borderRadius: "20px 20px 0 0",
              maxHeight: "75vh",
              width: "100%", maxWidth: 600,
              padding: 16,
              display: "flex", flexDirection: "column",
              boxShadow: "0 -10px 30px rgba(0,0,0,.2)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between",
                            alignItems: "center", marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 800,
                                color: "#0f172a" }}>📦 Meu estoque de ONTs</div>
                <div style={{ fontSize: 11, color: "#64748b" }}>
                  Toque para selecionar
                </div>
              </div>
              <button
                onClick={() => setShowStockPicker(false)}
                style={{ background: "none", border: "none",
                          fontSize: 22, cursor: "pointer", color: "#64748b" }}
              >×</button>
            </div>
            <div style={{ overflowY: "auto", flex: 1 }}>
              {(stock?.onts || []).map((o) => {
                const fromClient = o.status === "retirada_com_tecnico";
                return (
                  <button
                    type="button"
                    key={o.mac}
                    data-testid={`stock-picker-ont-${o.mac}`}
                    onClick={() => {
                      setForm({ ...form, ont: o.mac });
                      setShowStockPicker(false);
                    }}
                    style={{
                      width: "100%",
                      padding: "12px 14px",
                      marginBottom: 8,
                      background: form.ont === o.mac ? "#dbeafe" : "#f8fafc",
                      border: form.ont === o.mac
                        ? "2px solid #3b82f6" : "1px solid #e2e8f0",
                      borderRadius: 10,
                      cursor: "pointer",
                      display: "flex", justifyContent: "space-between",
                      alignItems: "center", gap: 8,
                      textAlign: "left",
                    }}
                  >
                    <div style={{ display: "flex", flexDirection: "column",
                                    gap: 2, flex: 1, minWidth: 0 }}>
                      <span style={{
                        fontFamily: "monospace",
                        fontWeight: 800, fontSize: 14,
                        color: "#0f172a",
                      }}>{o.mac}</span>
                      <span style={{ fontSize: 11, color: "#64748b" }}>
                        {o.model || "ONT"}
                      </span>
                    </div>
                    <span style={{
                      fontSize: 10, fontWeight: 700,
                      padding: "3px 8px", borderRadius: 999,
                      background: fromClient ? "#fef3c7" : "#dbeafe",
                      color: fromClient ? "#92400e" : "#1e40af",
                      flexShrink: 0,
                    }}>
                      {fromClient ? "↩️ Cliente" : "📦 Praça"}
                    </span>
                  </button>
                );
              })}
              {(stock?.onts || []).length === 0 && (
                <div style={{ padding: 30, textAlign: "center",
                                color: "#94a3b8", fontSize: 13 }}>
                  Nenhuma ONT no seu estoque ainda.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* iter183 — Chat WhatsApp do cliente (sheet modal) */}
      <OsClientChat
        open={showChat}
        onClose={() => setShowChat(false)}
        collabId={collaboratorId}
        collabName={collaboratorName}
        phone={ticket?.client_snapshot?.phone}
        clientName={ticket?.client_snapshot?.name}
      />
    </div>
  );
}

// =========================================================================
// Modal: técnico não consegue executar — pede contato pelo gestor
// =========================================================================
/* CantExecuteModal removed — botão "Não consegui executar" foi tirado */


function reorderBtnStyle(disabled) {
  return {
    width: 32, height: 28, border: "1px solid #c4b5fd",
    background: disabled ? "#f1f5f9" : "white",
    color: disabled ? "#cbd5e1" : "#5b21b6",
    borderRadius: 8, fontSize: 12, fontWeight: 700,
    cursor: disabled ? "not-allowed" : "pointer",
    display: "grid", placeItems: "center",
    boxShadow: "0 1px 2px rgba(15,23,42,.05)",
  };
}


/* Modal: técnico foi bloqueado de fechar OS sem execução */
function BlockedCloseModal({ info, onClose }) {
  return (
    <div data-testid="blocked-close-modal"
         style={{
           position: "fixed", inset: 0, zIndex: 1500,
           background: "rgba(2,6,23,0.85)",
           display: "grid", placeItems: "center", padding: 18,
         }}>
      <div style={{
        background: "white", borderRadius: 14, padding: 24,
        maxWidth: 420, width: "100%", textAlign: "center",
        boxShadow: "0 25px 60px rgba(0,0,0,0.4)",
      }}>
        <div style={{
          width: 72, height: 72, borderRadius: "50%",
          margin: "0 auto 14px", background: "#fef3c7",
          display: "grid", placeItems: "center", fontSize: 36,
        }}>📞</div>
        <h3 style={{ margin: "0 0 8px", fontSize: 18, fontWeight: 800,
                      color: "#0f172a" }}>
          Gestor foi acionado
        </h3>
        <p style={{ margin: "0 0 16px", color: "#475569", fontSize: 13,
                     lineHeight: 1.5 }}>
          {info.message || (
            "Sua solicitação foi registrada. O gestor entrará em contato "
            + "com o cliente e decidirá os próximos passos."
          )}
        </p>
        <div style={{ padding: "10px 12px", background: "#eff6ff",
                       border: "1px solid #bfdbfe", borderRadius: 8,
                       fontSize: 11, color: "#1e40af",
                       lineHeight: 1.5, marginBottom: 14 }}>
          🔒 Você <b>não pode finalizar</b> esta OS. Ela ficará marcada
          como "aguardando contato do gestor" e será resolvida pelo
          gestor depois que ele conversar com o cliente.
        </div>
        <button onClick={onClose}
                data-testid="blocked-close-modal-ok"
                style={{ width: "100%", padding: "13px 14px",
                          background: "#0f172a", color: "white",
                          border: 0, borderRadius: 9, fontSize: 14,
                          fontWeight: 700, cursor: "pointer" }}>
          ✓ Entendi
        </button>
      </div>
    </div>
  );
}

/* Modal: técnico aguardando autorização do gestor pra fechar com sinal ruim */
function BadSignalAuthWaitModal({ state, onClose }) {
  const isPending = state.status === "pending";
  const isRejected = state.status === "rejected";
  const isExpired = state.status === "expired";
  return (
    <div data-testid="bad-signal-auth-wait-modal"
          style={{
            position: "fixed", inset: 0, zIndex: 1500,
            background: "rgba(2,6,23,0.85)",
            display: "grid", placeItems: "center", padding: 18,
          }}>
      <div style={{
        background: "white", borderRadius: 14, padding: 22,
        maxWidth: 380, width: "100%", textAlign: "center",
        boxShadow: "0 25px 60px rgba(0,0,0,0.4)",
      }}>
        <div style={{
          width: 64, height: 64, borderRadius: "50%", margin: "0 auto 14px",
          background: isPending ? "#fef9c3" : isRejected ? "#fee2e2" : "#fef3c7",
          color: isPending ? "#ca8a04" : isRejected ? "#dc2626" : "#92400e",
          display: "grid", placeItems: "center",
          fontSize: 30,
          animation: isPending ? "wa-pulse 2s ease infinite" : "none",
        }}>
          {isPending ? "⏳" : isRejected ? "✗" : "⌛"}
        </div>
        <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700,
                      color: "#0f172a" }}>
          {isPending && "Aguardando autorização"}
          {isRejected && "Pedido rejeitado"}
          {isExpired && "Pedido expirou"}
        </h3>
        <p style={{ margin: "8px 0 16px", fontSize: 13, color: "#475569",
                     lineHeight: 1.5 }}>
          {isPending && (
            <>Você está fechando com <strong style={{ color: "#dc2626" }}>
              {state.sinal?.toFixed(1)} dBm</strong> (limite {state.threshold}).
              <br/>O gestor foi notificado — aguarde a aprovação.</>
          )}
          {isRejected && (
            <>O gestor negou o fechamento com este sinal.<br/>
            Melhore o sinal e tente novamente.</>
          )}
          {isExpired && (
            <>O pedido passou de 30 minutos sem decisão.<br/>
            Faça uma nova tentativa.</>
          )}
        </p>
        <button onClick={onClose}
                 data-testid="bad-signal-auth-close-btn"
                 style={{
                   padding: "10px 24px", borderRadius: 8,
                   border: "1.5px solid #cbd5e1", background: "white",
                   color: "#475569", fontWeight: 700, fontSize: 13,
                   cursor: "pointer",
                 }}>
          Fechar
        </button>
      </div>
      <style>{`
        @keyframes wa-pulse {
          0%,100% { transform: scale(1); }
          50% { transform: scale(1.08); }
        }
      `}</style>
    </div>
  );
}

/* PPPoE chip — clique copia pro clipboard com flash verde "✓ copiado" */
function PppoeChip({ pppoe }) {
  const [copied, setCopied] = React.useState(false);
  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(pppoe);
    } catch {
      // fallback: createElement textarea + execCommand (já obsoleto mas funciona em http)
      const ta = document.createElement("textarea");
      ta.value = pppoe; document.body.appendChild(ta);
      ta.select(); try { document.execCommand("copy"); } catch {}
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };
  return (
    <button onClick={onClick} data-testid="lousa-pppoe-copy"
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              border: "none", cursor: "pointer", padding: "4px 10px",
              borderRadius: 999, fontSize: 11, fontFamily: "monospace",
              fontWeight: 700, marginBottom: 4,
              background: copied ? "#16a34a" : "rgba(165,180,252,0.15)",
              color: copied ? "white" : "#a5b4fc",
              transition: "background 180ms, color 180ms",
            }}
            title="Toque pra copiar">
      {copied ? "✓ Copiado!" : <>🔑 {pppoe}</>}
    </button>
  );
}

/* Bloco com dados puxados da SmartOLT — Porta OLT, VLAN, CTO, SN.
   Cada item só renderiza se houver dado. Cor azul-acinzentada pra
   diferenciar das infos do cliente (azul-índigo do PPPoE). */
function SmartOltDetailBlock({ ls, ticket }) {
  const [showGpsPicker, setShowGpsPicker] = React.useState(false);
  const [savingGps, setSavingGps] = React.useState(false);
  const [gpsMsg, setGpsMsg] = React.useState(null);
  const [pushBusy, setPushBusy] = React.useState(false);
  // iter180 — designação manual da CTO (quando porta existe mas nome não)
  const [ctoEditOpen, setCtoEditOpen] = React.useState(false);
  const [ctoQuery, setCtoQuery] = React.useState("");
  const [ctoOptions, setCtoOptions] = React.useState([]);
  const [ctoSaving, setCtoSaving] = React.useState(false);
  const [ctoSavedMsg, setCtoSavedMsg] = React.useState(null);
  const [localCtoBox, setLocalCtoBox] = React.useState(null);

  // ---- Search CTOs lazy (debounce simples) ----
  // iter181 — Hook precisa ficar ANTES dos early returns (Rules of Hooks)
  React.useEffect(() => {
    if (!ctoEditOpen) return;
    const q = (ctoQuery || "").trim();
    if (q.length < 2) { setCtoOptions([]); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await api._client.get(
          `/rede-ia/ctos?q=${encodeURIComponent(q)}&limit=10`,
        ).then((x) => x.data);
        if (cancelled) return;
        setCtoOptions(r.items || []);
      } catch { /* silent */ }
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [ctoEditOpen, ctoQuery]);

  if (!ls) return null;
  // iter180 — diff cliente vs média da VLAN, com cor pra ajudar diagnóstico:
  // se a VLAN inteira está ruim, problema é rede; se só o cliente está ruim,
  // problema é local (drop, conector, fusão).
  const vlanAvg = ls.vlan_avg_dbm;
  const vlanDiff = ls.vlan_diff_dbm;
  const hasVlanAvg = typeof vlanAvg === "number";
  let vlanDiffColor = "#7dd3fc";
  let vlanDiffLabel = "";
  if (typeof vlanDiff === "number") {
    if (vlanDiff > 3) {
      vlanDiffColor = "#fca5a5";
      vlanDiffLabel = "cliente pior";
    } else if (vlanDiff < -3) {
      vlanDiffColor = "#86efac";
      vlanDiffLabel = "cliente melhor";
    } else {
      vlanDiffLabel = "compatível";
    }
  }
  const effectiveCtoBox = localCtoBox || ls.cto_box;
  const showCtoEditor = ls.cto_port && !effectiveCtoBox;
  const items = [
    { label: "PORTA OLT", value: ls.olt_port, hint: `ONU #${ls.onu || "?"}` },
    { label: "VLAN", value: ls.vlan,
      hint: hasVlanAvg ? `méd ${vlanAvg.toFixed(1)} dBm` : null },
    { label: "CTO", value: effectiveCtoBox },
    { label: "PORTA CTO", value: ls.cto_port },
    { label: "MAC", value: ls.mac, mono: true },     // iter180
    { label: "SN", value: ls.sn, mono: true },
    { label: "ONLINE HÁ", value: ls.uptime_human, mono: false },
  ].filter((i) => i.value);
  // iter180 — mostra o card mesmo sem todos os items se houver editor
  if (items.length === 0 && !showCtoEditor) return null;

  const saveCtoAssignment = async (selected) => {
    if (!selected || !ticket?.id) return;
    setCtoSaving(true); setCtoSavedMsg(null);
    try {
      await api._client.patch(
        `/lousa/tickets/${ticket.id}/cto-assignment`,
        {
          cto_id: selected.id,
          cto_name: selected.name,
          cto_port: ls.cto_port || null,
        },
      );
      setLocalCtoBox(selected.name);
      setCtoSavedMsg({ kind: "ok", text: "CTO designada!" });
      setCtoEditOpen(false);
      setTimeout(() => setCtoSavedMsg(null), 3000);
    } catch (e) {
      setCtoSavedMsg({ kind: "err",
        text: e?.response?.data?.detail || "Falha ao salvar" });
    } finally { setCtoSaving(false); }
  };

  // Tenta achar o `cto_id` via ls.cto_id ou ls.cto_box (alguns sidecars
  // só retornam o nome). Se vier só nome, busca lazy no clique.
  const ctoId = ls.cto_id;
  const ctoBox = ls.cto_box;
  const initialGps = ls.cto_gps || ls.gps || null;

  const saveLocation = async ({ lat, lng, address }) => {
    setSavingGps(true); setGpsMsg(null);
    try {
      let resolvedId = ctoId;
      if (!resolvedId && ctoBox) {
        // Resolve por nome
        try {
          const r = await api._client.get(
            `/rede-ia/ctos?bairro=&q=${encodeURIComponent(ctoBox)}`,
          ).then((x) => x.data);
          const items = r.items || [];
          const hit = items.find((c) => c.name === ctoBox)
            || items[0];
          resolvedId = hit?.id;
        } catch { /* ignore */ }
      }
      if (!resolvedId) {
        setGpsMsg({ kind: "err", text: "CTO não encontrada no cadastro." });
        return;
      }
      const addrPayload = address ? {
        rua: address.rua, numero: address.numero,
        bairro: address.bairro, cidade: address.cidade,
        estado: address.estado, cep: address.cep,
      } : null;
      await api.redeIaCtoLocationUpdate(resolvedId, {
        lat, lng, address: addrPayload,
      });
      setGpsMsg({ kind: "ok", text: "Localização atualizada!" });
      setShowGpsPicker(false);
    } catch (e) {
      setGpsMsg({
        kind: "err",
        text: e?.response?.data?.detail || e.message,
      });
    } finally { setSavingGps(false); }
  };

  return (
    <div data-testid="lousa-smartolt-block"
          style={{
            marginTop: 8, padding: "8px 10px", borderRadius: 8,
            background: "rgba(14,165,233,0.08)",
            border: "1px solid rgba(14,165,233,0.18)",
          }}>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(85px, 1fr))",
        gap: 6,
      }}>
        {items.map((i) => (
          <div key={i.label}>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#67e8f9",
                            textTransform: "uppercase", letterSpacing: 0.5 }}>
              {i.label}
            </div>
            <div style={{
              fontSize: 11.5, color: "#e0f2fe", fontWeight: 600,
              fontFamily: i.mono ? "monospace" : "inherit",
              wordBreak: "break-all",
            }}>{i.value}</div>
            {i.hint && (
              <div style={{ fontSize: 9, color: "#7dd3fc",
                              opacity: 0.7 }}>{i.hint}</div>
            )}
          </div>
        ))}
      </div>

      {/* iter180 — Designação de CTO quando a porta está definida mas o
          nome ainda não foi associado, ou para corrigir associação errada */}
      {ls.cto_port && (
        <div data-testid="lousa-cto-designate" style={{
          marginTop: 10, padding: 10, borderRadius: 10,
          background: effectiveCtoBox
            ? "rgba(34,197,94,0.06)" : "rgba(251,191,36,0.10)",
          border: `1px solid ${effectiveCtoBox ? "#16a34a55" : "#f59e0b66"}`,
        }}>
          {!ctoEditOpen ? (
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 18 }}>
                {effectiveCtoBox ? "📦" : "❓"}
              </span>
              <div style={{ flex: 1, fontSize: 12, color: "#e0f2fe",
                              lineHeight: 1.4 }}>
                {effectiveCtoBox ? (
                  <>
                    Cliente designado em
                    {" "}<strong>{effectiveCtoBox}</strong>
                    {" · porta "}<strong>{ls.cto_port}</strong>
                  </>
                ) : (
                  <>
                    <strong style={{ color: "#fbbf24" }}>
                      Designar CTO para o cliente
                    </strong>
                    <div style={{ fontSize: 10.5, color: "#cbd5e1",
                                      marginTop: 2 }}>
                      Porta {ls.cto_port} está definida na OLT.
                      Vincule à caixa correta.
                    </div>
                  </>
                )}
              </div>
              <button data-testid="lousa-cto-designate-btn"
                      onClick={() => setCtoEditOpen(true)}
                      style={{
                        padding: "6px 12px", borderRadius: 8,
                        background: effectiveCtoBox ? "#0e7490" : "#f59e0b",
                        color: "#fff", border: 0, fontSize: 11, fontWeight: 700,
                        cursor: "pointer", whiteSpace: "nowrap",
                      }}>
                {effectiveCtoBox ? "Trocar" : "Designar"}
              </button>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 10, fontWeight: 800, color: "#fbbf24",
                              letterSpacing: 0.6, marginBottom: 6,
                              textTransform: "uppercase" }}>
                Selecione a CTO
              </div>
              <input data-testid="lousa-cto-search-input"
                type="search" autoFocus value={ctoQuery}
                onChange={(e) => setCtoQuery(e.target.value)}
                placeholder="Digite CTO_301_004…"
                style={{
                  width: "100%", padding: "8px 10px", borderRadius: 8,
                  border: "1px solid #475569", background: "#1e293b",
                  color: "#f1f5f9", fontFamily: "monospace", fontSize: 12.5,
                  boxSizing: "border-box", marginBottom: 6,
                }} />
              {ctoOptions.length > 0 && (
                <div style={{
                  maxHeight: 180, overflowY: "auto",
                  border: "1px solid #334155", borderRadius: 8,
                  background: "#0f172a",
                }}>
                  {ctoOptions.map((c) => (
                    <button key={c.id}
                            data-testid={`lousa-cto-option-${c.id}`}
                            onClick={() => saveCtoAssignment(c)}
                            disabled={ctoSaving}
                            style={{
                              display: "block", width: "100%",
                              padding: "7px 10px", textAlign: "left",
                              border: 0, background: "transparent",
                              color: "#e2e8f0", fontSize: 12,
                              fontFamily: "monospace", cursor: "pointer",
                              borderBottom: "1px solid #1e293b",
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.background = "#1e293b")}
                            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
                      <strong>{c.name}</strong>
                      <span style={{ marginLeft: 8, opacity: 0.6, fontSize: 10 }}>
                        VLAN {c.vlan} · {c.used_ports || 0}/{c.capacity || 0} portas
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {ctoQuery.length >= 2 && ctoOptions.length === 0 && (
                <div style={{ fontSize: 11, color: "#94a3b8",
                                padding: "8px 0", textAlign: "center" }}>
                  Nenhuma CTO encontrada.
                </div>
              )}
              <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                <button onClick={() => { setCtoEditOpen(false);
                                            setCtoQuery(""); }}
                        disabled={ctoSaving}
                        style={{
                          flex: 1, padding: "6px 10px", borderRadius: 6,
                          background: "transparent",
                          border: "1px solid #475569", color: "#94a3b8",
                          fontSize: 11, fontWeight: 700, cursor: "pointer",
                        }}>
                  Cancelar
                </button>
              </div>
            </div>
          )}
          {ctoSavedMsg && (
            <div style={{
              marginTop: 6, padding: "4px 8px", borderRadius: 4,
              fontSize: 10.5, fontWeight: 700,
              background: ctoSavedMsg.kind === "ok" ? "#16a34a" : "#dc2626",
              color: "#fff",
            }}>
              {ctoSavedMsg.text}
            </div>
          )}
        </div>
      )}
      {hasVlanAvg && typeof ls.rx_dbm === "number" && (
        <div data-testid="lousa-vlan-compare" style={{
          marginTop: 10, padding: 12, borderRadius: 10,
          background: "rgba(14,165,233,0.08)",
          border: `1.5px solid ${vlanDiffColor}55`,
        }}>
          <div style={{
            fontSize: 10, fontWeight: 800, color: "#67e8f9",
            textTransform: "uppercase", letterSpacing: 0.8,
            marginBottom: 8,
          }}>
            Cliente vs VLAN
          </div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 10, marginBottom: 8,
          }}>
            <div style={{
              padding: "8px 10px", borderRadius: 8,
              background: "rgba(255,255,255,0.06)",
            }}>
              <div style={{ fontSize: 9, color: "#94a3b8",
                              letterSpacing: 0.6, marginBottom: 2,
                              textTransform: "uppercase" }}>
                Cliente
              </div>
              <div style={{ fontSize: 18, fontWeight: 800,
                              color: "#f1f5f9", fontFamily: "monospace",
                              whiteSpace: "nowrap" }}>
                {ls.rx_dbm.toFixed(1)}
                <span style={{ fontSize: 10, opacity: 0.7,
                                  marginLeft: 3 }}>dBm</span>
              </div>
            </div>
            <div style={{
              padding: "8px 10px", borderRadius: 8,
              background: "rgba(255,255,255,0.06)",
            }}>
              <div style={{ fontSize: 9, color: "#94a3b8",
                              letterSpacing: 0.6, marginBottom: 2,
                              textTransform: "uppercase" }}>
                Média ({ls.vlan_onu_count || 0} ONUs)
              </div>
              <div style={{ fontSize: 18, fontWeight: 800,
                              color: "#f1f5f9", fontFamily: "monospace",
                              whiteSpace: "nowrap" }}>
                {vlanAvg.toFixed(1)}
                <span style={{ fontSize: 10, opacity: 0.7,
                                  marginLeft: 3 }}>dBm</span>
              </div>
            </div>
          </div>
          <div style={{
            padding: "6px 10px", borderRadius: 6,
            background: `${vlanDiffColor}22`,
            color: vlanDiffColor, fontWeight: 700, fontSize: 12,
            textAlign: "center", letterSpacing: 0.3,
            whiteSpace: "nowrap",
          }}>
            {vlanDiff > 0 ? "+" : ""}{vlanDiff.toFixed(1)} dBm
            {vlanDiffLabel && ` · ${vlanDiffLabel}`}
          </div>
        </div>
      )}
      {ctoBox && (
        <div style={{
          marginTop: 8, display: "grid",
          gridTemplateColumns: "1fr 1fr", gap: 6,
        }}>
          <button
            onClick={() => setShowGpsPicker(true)}
            disabled={savingGps}
            data-testid="lousa-cto-gps-btn"
            style={{
              padding: "7px 8px", border: 0,
              background: "linear-gradient(135deg,#8b5cf6,#6366f1)",
              color: "#fff", borderRadius: 8, fontSize: 11, fontWeight: 600,
              cursor: savingGps ? "wait" : "pointer",
              display: "inline-flex", justifyContent: "center", alignItems: "center", gap: 4,
            }}>
            📍 {savingGps ? "Salvando..." : "GPS"}
          </button>
          <button
            onClick={async () => {
              if (!ls?.sn) return await window.alert("ONU sem SN cadastrado");
              if (!await window.confirm(`Enviar PUSH (reiniciar ONU ${ls.sn})?\n\nO cliente vai ficar offline por ~30s.`)) return;
              setPushBusy(true); setGpsMsg(null);
              try {
                await api._client.post(`/rede-ia/onu/${encodeURIComponent(ls.sn)}/push`,
                  { action: "reboot" });
                setGpsMsg({ kind: "ok", text: "Push enviado! Aguarde ~30s." });
              } catch (e) {
                setGpsMsg({
                  kind: "err",
                  text: e?.response?.data?.detail || e.message,
                });
              } finally { setPushBusy(false); }
            }}
            disabled={pushBusy || !ls?.sn}
            data-testid="lousa-cto-push-btn"
            style={{
              padding: "7px 8px", border: 0,
              background: pushBusy
                ? "#94a3b8"
                : "linear-gradient(135deg,#f43f5e,#ec4899)",
              color: "#fff", borderRadius: 8, fontSize: 11, fontWeight: 600,
              cursor: pushBusy ? "wait" : "pointer",
              display: "inline-flex", justifyContent: "center", alignItems: "center", gap: 4,
            }}>
            ⚡ {pushBusy ? "Enviando..." : "Push ONU"}
          </button>
        </div>
      )}
      {gpsMsg && (
        <div data-testid={`lousa-cto-gps-${gpsMsg.kind}`}
              style={{
                marginTop: 6, padding: 7, borderRadius: 6, fontSize: 11,
                background: gpsMsg.kind === "ok" ? "#dcfce7" : "#fee2e2",
                color: gpsMsg.kind === "ok" ? "#166534" : "#991b1b",
              }}>
          {gpsMsg.text}
        </div>
      )}
      {showGpsPicker && (
        <UberGpsPicker
          title={`CTO ${ctoBox} — Ajustar GPS`}
          initialLat={initialGps?.lat}
          initialLng={initialGps?.lng}
          onClose={() => setShowGpsPicker(false)}
          onConfirm={saveLocation}
        />
      )}
    </div>
  );
}


/* ------------------------------------------------------------------ */
/* NotaTecnicaCard                                                     */
/* Card que mostra o "antes vs depois" do sinal SmartOLT pra cada      */
/* chamado. O sinal de abertura é gravado automaticamente na criação   */
/* do chamado (se a captura estiver ligada). O sinal de fechamento     */
/* só aparece depois que o técnico finalizar. Antes disso, o técnico   */
/* pode clicar em "Ler sinal agora" pra fazer um snapshot ao vivo do   */
/* SmartOLT e ver onde está o sinal antes de fechar.                   */
/* ------------------------------------------------------------------ */
function NotaTecnicaCard({ ticket, onRefresh }) {
  const [busyOpen, setBusyOpen] = React.useState(false);
  const [busyClose, setBusyClose] = React.useState(false);
  const [errMsg, setErrMsg] = React.useState("");
  const [okMsg, setOkMsg] = React.useState("");

  const open = ticket?.signal_at_open;
  const close = ticket?.signal_at_close;
  const openAt = ticket?.signal_at_open_at;
  const closeAt = ticket?.signal_at_close_at;
  const isFinalized = ticket?.status === "finalizada"
                       || ticket?.status === "encerrada";

  const fmtDbm = (v) => (v == null ? "—" : `${Number(v).toFixed(1)} dBm`);
  const fmtTime = (iso) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("pt-BR",
        { dateStyle: "short", timeStyle: "short" });
    } catch { return ""; }
  };
  const dbmTone = (v) => {
    if (v == null) return { bg: "#f1f5f9", color: "#475569", label: "—" };
    if (v <= -28) return { bg: "#fee2e2", color: "#b91c1c", label: "LOS" };
    if (v <= -27) return { bg: "#fee2e2", color: "#b91c1c", label: "RUIM" };
    if (v <= -25) return { bg: "#fef3c7", color: "#a16207", label: "MÉDIO" };
    return { bg: "#dcfce7", color: "#15803d", label: "BOM" };
  };

  let delta = null;
  let deltaTone = null;
  if (open?.rx_dbm != null && close?.rx_dbm != null) {
    delta = Number((close.rx_dbm - open.rx_dbm).toFixed(2));
    // mais próximo de 0 = melhor (ex: -23 > -27). delta>0 = melhorou
    if (close.rx_dbm <= -28) {
      deltaTone = { bg: "#fee2e2", color: "#b91c1c",
        verdict: "🔴 PÓS-REPARO EM LOS" };
    } else if (delta < -3) {
      deltaTone = { bg: "#fee2e2", color: "#b91c1c",
        verdict: `🔴 PIOROU ${Math.abs(delta).toFixed(1)} dB` };
    } else if (delta < 0) {
      deltaTone = { bg: "#fef3c7", color: "#a16207",
        verdict: `🟡 Caiu ${Math.abs(delta).toFixed(1)} dB (tolerável)` };
    } else {
      deltaTone = { bg: "#dcfce7", color: "#15803d",
        verdict: `🟢 ${delta >= 0 ? "+" : ""}${delta.toFixed(1)} dB` };
    }
  }

  async function capture(moment) {
    setErrMsg(""); setOkMsg("");
    const setBusy = moment === "open" ? setBusyOpen : setBusyClose;
    setBusy(true);
    try {
      const r = await api.lousaCaptureSignal(ticket.id, moment);
      setOkMsg(
        `Sinal ${moment === "open" ? "de abertura" : "de fechamento"} `
        + `atualizado: ${r.snapshot.rx_dbm.toFixed(1)} dBm`,
      );
      if (onRefresh) await onRefresh();
      setTimeout(() => setOkMsg(""), 3000);
    } catch (e) {
      const d = e?.response?.data?.detail;
      const msg = typeof d === "string" ? d
        : (e?.response?.status === 400
            ? "Captura de sinal está desligada no painel admin."
            : e.message);
      setErrMsg(msg);
      setTimeout(() => setErrMsg(""), 4500);
    } finally { setBusy(false); }
  }

  const openTone = dbmTone(open?.rx_dbm);
  const closeTone = dbmTone(close?.rx_dbm);

  return (
    <div
      data-testid={`nota-tecnica-card-${ticket.id}`}
      style={{
        marginTop: 14, padding: 14, borderRadius: 14,
        background: "linear-gradient(135deg,#ffffff 0%,#f8fafc 100%)",
        border: "1px solid #e2e8f0",
        boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
      }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                       marginBottom: 10, gap: 8 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 800, color: "#0f172a",
                          display: "inline-flex", alignItems: "center", gap: 6 }}>
            📶 Nota Técnica — Sinal antes × depois
          </div>
          <div style={{ fontSize: 10.5, color: "#64748b", marginTop: 2 }}>
            Comparativo automático do SmartOLT pra avaliar a qualidade do reparo
          </div>
        </div>
      </div>

      {/* Banner sem mapeamento SmartOLT */}
      {!open && !close && (
        <div data-testid="nota-tecnica-empty" style={{
          padding: 10, background: "#f1f5f9", borderRadius: 10,
          fontSize: 11.5, color: "#475569", lineHeight: 1.5,
        }}>
          Sem mapeamento SmartOLT para este cliente, ou a captura automática está
          desligada no painel admin.
          <br/>Você ainda pode tentar uma leitura manual abaixo.
        </div>
      )}

      {(open || close) && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {/* ANTES */}
          <div data-testid="nota-tecnica-open" style={{
            padding: 10, borderRadius: 10, border: "1px dashed #cbd5e1",
            background: openTone.bg + "55",
          }}>
            <div style={{ fontSize: 9.5, fontWeight: 800, color: "#64748b",
                            textTransform: "uppercase", letterSpacing: 0.5 }}>
              📥 Na abertura
            </div>
            <div data-testid="nota-tecnica-open-dbm"
                  style={{ fontSize: 22, fontWeight: 800,
                            color: openTone.color, fontFamily: "monospace",
                            marginTop: 4 }}>
              {fmtDbm(open?.rx_dbm)}
            </div>
            <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>
              {openAt ? fmtTime(openAt) : "Sem snapshot"}
              {open?.status ? ` · ${open.status}` : ""}
            </div>
            <div style={{ marginTop: 6, fontSize: 10, fontWeight: 700,
                            color: openTone.color }}>{openTone.label}</div>
          </div>

          {/* DEPOIS */}
          <div data-testid="nota-tecnica-close" style={{
            padding: 10, borderRadius: 10, border: "1px solid #cbd5e1",
            background: closeTone.bg + "55",
          }}>
            <div style={{ fontSize: 9.5, fontWeight: 800, color: "#64748b",
                            textTransform: "uppercase", letterSpacing: 0.5 }}>
              📤 {isFinalized ? "No fechamento" : "Agora (live)"}
            </div>
            <div data-testid="nota-tecnica-close-dbm"
                  style={{ fontSize: 22, fontWeight: 800,
                            color: closeTone.color, fontFamily: "monospace",
                            marginTop: 4 }}>
              {fmtDbm(close?.rx_dbm)}
            </div>
            <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>
              {closeAt ? fmtTime(closeAt) : "Sem snapshot"}
              {close?.status ? ` · ${close.status}` : ""}
            </div>
            <div style={{ marginTop: 6, fontSize: 10, fontWeight: 700,
                            color: closeTone.color }}>{closeTone.label}</div>
          </div>
        </div>
      )}

      {/* Verdito (delta) */}
      {deltaTone && (
        <div data-testid="nota-tecnica-verdict"
              style={{
                marginTop: 10, padding: "8px 10px", borderRadius: 8,
                background: deltaTone.bg, color: deltaTone.color,
                fontSize: 12, fontWeight: 800, textAlign: "center",
              }}>
          {deltaTone.verdict}
        </div>
      )}

      {/* Botões de captura manual */}
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        {!isFinalized && (
          <button
            data-testid="nota-tecnica-capture-close"
            onClick={() => capture("close")}
            disabled={busyClose}
            style={{
              flex: 1, padding: "8px 10px", borderRadius: 8, fontSize: 12,
              fontWeight: 700, border: "1px solid #0ea5e9",
              background: busyClose ? "#bae6fd" : "#0ea5e9",
              color: "#fff", cursor: busyClose ? "wait" : "pointer",
            }}>
            📡 {busyClose ? "Lendo SmartOLT…" : "Ler sinal agora"}
          </button>
        )}
        {!open && (
          <button
            data-testid="nota-tecnica-capture-open"
            onClick={() => capture("open")}
            disabled={busyOpen}
            style={{
              flex: 1, padding: "8px 10px", borderRadius: 8, fontSize: 12,
              fontWeight: 700, border: "1px dashed #94a3b8",
              background: "#fff", color: "#334155",
              cursor: busyOpen ? "wait" : "pointer",
            }}>
            {busyOpen ? "Lendo…" : "Recapturar abertura"}
          </button>
        )}
      </div>

      {errMsg && (
        <div data-testid="nota-tecnica-err"
              style={{ marginTop: 8, padding: 8, borderRadius: 8,
                        fontSize: 11, background: "#fee2e2", color: "#991b1b" }}>
          ⚠ {errMsg}
        </div>
      )}
      {okMsg && (
        <div data-testid="nota-tecnica-ok"
              style={{ marginTop: 8, padding: 8, borderRadius: 8,
                        fontSize: 11, background: "#dcfce7", color: "#15803d" }}>
          ✓ {okMsg}
        </div>
      )}
    </div>
  );
}
