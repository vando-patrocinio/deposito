import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
export const API = `${BACKEND_URL}/api`;

const client = axios.create({ baseURL: API, timeout: 60000 });
export { client };

// Interceptor: injeta o token JWT salvo em localStorage (escrito pelo AuthContext)
// e o header X-Active-Company (drill-down do super admin)
// Também injeta X-Public-Token quando há link público ativo (?ptoken=xxx)
client.interceptors.request.use((cfg) => {
  if (typeof window !== "undefined") {
    const t = window.localStorage.getItem("ponto_token");
    if (t) cfg.headers.Authorization = `Bearer ${t}`;
    const active = window.localStorage.getItem("ponto_active_company");
    if (active) cfg.headers["X-Active-Company"] = active;
    const ptoken = window.localStorage.getItem("smartprov_public_token");
    if (ptoken && !t) cfg.headers["X-Public-Token"] = ptoken;
  }
  return cfg;
});

// Interceptor de resposta:
//  - 401 em endpoints autenticados → limpa estado do usuário e dispara
//    evento global `smartprov-session-expired` que o AppContent escuta.
//    NÃO faz hard redirect (preserva o estado da app em memória).
//  - Não dispara em /auth/login nem /auth/logout (esses tratam o erro localmente).
client.interceptors.response.use(
  (r) => r,
  (err) => {
    if (typeof window === "undefined") return Promise.reject(err);
    // Chamadas marcadas como silent (best-effort) não disparam eventos
    // globais de sessão/toast — quem chamou trata o erro localmente.
    if (err?.config?.silent) return Promise.reject(err);
    const status = err?.response?.status;
    const url = err?.config?.url || "";
    const detail = err?.response?.data?.detail;

    // 401 — sessão expirada (mantém comportamento original)
    if (status === 401) {
      const isAuthEndpoint = url.includes("/auth/login")
        || url.includes("/auth/logout")
        || url.includes("/auth/google-login")
        || url.includes("/auth/me");
      if (!isAuthEndpoint) {
        ["ponto_token", "ponto_active_company",
         "ponto_onboarding_done", "collab_token", "collab_id"].forEach((k) => {
          try { window.localStorage.removeItem(k); } catch { /* ignore */ }
        });
        try {
          window.dispatchEvent(new CustomEvent("smartprov-session-expired", {
            detail: { url, reason: detail || "Sessão expirada" },
          }));
        } catch { /* ignore */ }
      }
    }

    // Sprint 3 — interceptor global 403 / 429 / 503
    // Dispara evento p/ AppContent renderizar toast amigável.
    if (status === 403 || status === 429 || status === 503) {
      const kind = status === 403 ? "forbidden"
        : status === 429 ? "rate-limited"
        : "unavailable";
      const defaults = {
        forbidden: "Seu perfil não tem permissão para essa ação.",
        "rate-limited": "Limite de uso atingido. Tente novamente em alguns instantes.",
        unavailable: "Serviço temporariamente indisponível.",
      };
      try {
        window.dispatchEvent(new CustomEvent("smartprov-http-error", {
          detail: {
            status, kind, url,
            message: detail || defaults[kind],
          },
        }));
      } catch { /* ignore */ }
    }

    return Promise.reject(err);
  }
);

export const api = {
  _client: client,
  // Public Referral Landing (/r/{code}) — usado por ReferralLandingPage
  publicReferralInfo: (code) =>
    client.get(`/r/${code}/info`).then((r) => r.data),
  publicReferralSubmit: (code, form) =>
    client.post(`/r/${code}/submit`, form).then((r) => r.data),
  // AI Center — RevenueOps IA (Fase 1 da Constituição V3.0)
  revenueSummary: (period = "MTD") =>
    client.get(`/ai-center/revenue/summary`, { params: { period } }).then((r) => r.data),
  revenueByTemplate: (period = "MTD", limit = 20) =>
    client.get(`/ai-center/revenue/by-template`, { params: { period, limit } }).then((r) => r.data),
  revenueByChannel: (period = "MTD") =>
    client.get(`/ai-center/revenue/by-channel`, { params: { period } }).then((r) => r.data),
  revenueByActionType: (period = "MTD") =>
    client.get(`/ai-center/revenue/by-action-type`, { params: { period } }).then((r) => r.data),
  revenueTimeline: (period = "30d", granularity = "day") =>
    client.get(`/ai-center/revenue/timeline`, { params: { period, granularity } }).then((r) => r.data),
  revenueTopActions: (period = "MTD", limit = 10) =>
    client.get(`/ai-center/revenue/top-actions`, { params: { period, limit } }).then((r) => r.data),


  // Colaboradores
  listCollaborators: (cfg) => client.get("/collaborators", cfg).then((r) => r.data),
  getCollaborator: (id) => client.get(`/collaborators/${id}`).then((r) => r.data),
  createCollaborator: (data) => client.post("/collaborators", data).then((r) => r.data),
  updateCollaborator: (id, data) => client.put(`/collaborators/${id}`, data).then((r) => r.data),
  deleteCollaborator: (id) => client.delete(`/collaborators/${id}`).then((r) => r.data),
  // resetCollaboratorFace movido para baixo (com suporte a resetDevice)

  // Cercas
  listGeofences: (cid, cfg) => client.get(`/collaborators/${cid}/geofences`, cfg).then((r) => r.data),
  createGeofence: (cid, data) => client.post(`/collaborators/${cid}/geofences`, data).then((r) => r.data),
  updateGeofence: (gid, data) => client.put(`/geofences/${gid}`, data).then((r) => r.data),
  deleteGeofence: (gid) => client.delete(`/geofences/${gid}`).then((r) => r.data),
  duplicateGeofence: (gid, targetIds) =>
    client.post(`/geofences/${gid}/duplicate`, { target_collaborator_ids: targetIds }).then((r) => r.data),
  geocode: (address) => client.get(`/geocode`, { params: { address } }).then((r) => r.data),
  geocodeSearch: (q, limit = 5) => client.get(`/geocode/search`, { params: { q, limit } }).then((r) => r.data),

  // Pontos
  todayStatus: (cid) => client.get(`/collaborators/${cid}/today`).then((r) => r.data),
  createClockRecord: (data) => client.post("/clock-records", data).then((r) => r.data),
  listClockRecords: (params = {}) => client.get("/clock-records", { params }).then((r) => r.data),
  getClockRecord: (rid) => client.get(`/clock-records/${rid}`).then((r) => r.data),
  approveRecord: (rid) => client.post(`/clock-records/${rid}/approve`).then((r) => r.data),
  rejectRecord: (rid) => client.post(`/clock-records/${rid}/reject`).then((r) => r.data),

  // Auditoria — trocas de ONT/ONU detectadas na finalização da OS
  listEquipmentSwaps: (limit = 100) =>
    client.get("/lousa/equipment-swaps", { params: { limit } }).then((r) => r.data),
  equipmentSwapsMonthlyReport: (months = 6) =>
    client.get("/lousa/equipment-swaps/monthly-report",
                  { params: { months } }).then((r) => r.data),

  // Espelho
  timesheet: (cid, year, month) => client.get(`/timesheets/${cid}/${year}/${month}`).then((r) => r.data),
  timesheetPdfUrl: (cid, year, month) => `${API}/timesheets/${cid}/${year}/${month}/pdf`,
  collectiveTimesheetPdfUrl: (year, month) => `${API}/timesheets-collective/${year}/${month}/pdf`,
  printAuditList: (limit = 30) => client.get(`/timesheets/print-audit`, { params: { limit } }).then((r) => r.data),
  sendTimesheetNow: (cid, year, month) => client.post(`/timesheets/send/${cid}`, null, { params: { year, month } }).then((r) => r.data),
  runMonthlyNow: () => client.post("/scheduler/run-monthly-now").then((r) => r.data),
  overtimeDashboard: (year, month) => client.get(`/dashboard/overtime/${year}/${month}`).then((r) => r.data),
  overtimeTrend: (months = 6) => client.get(`/dashboard/overtime/trend`, { params: { months } }).then((r) => r.data),

  // Feriados
  // (Endpoints de feriados antigos removidos — usar feriadosList/feriadoCreate)
  systemAlerts: (limit = 50) => client.get("/system/alerts", { params: { limit } }).then((r) => r.data),

  // Edição manual de ponto pelo gestor
  manualEntry: (data) => client.post("/clock-records/manual", data).then((r) => r.data),
  batchFixSchedule: (data) => client.post("/clock-records/manual/batch-fix-schedule", data).then((r) => r.data),
  deleteClockRecord: (rid, reason) => client.delete(`/clock-records/${rid}`, { params: { reason } }).then((r) => r.data),

  // Settings
  getSettings: () => client.get("/settings").then((r) => r.data),
  updateSettings: (data) => client.put("/settings", data).then((r) => r.data),

  // Email
  testEmail: (to, subject) => client.post("/email/test", { to, subject }).then((r) => r.data),

  // Praças (cidade/estado + feriados municipais/estaduais)
  listPracas: () => client.get("/pracas").then((r) => r.data),
  createPraca: (data) => client.post("/pracas", data).then((r) => r.data),
  updatePraca: (id, data) => client.put(`/pracas/${id}`, data).then((r) => r.data),
  deletePraca: (id) => client.delete(`/pracas/${id}`).then((r) => r.data),
  // (Endpoints discoverHolidays/applyHolidays removidos — feriados são gerenciados em /api/feriados)

  // Auth
  adminLogin: (password) => client.post("/auth/admin-login", { password }).then((r) => r.data),
  login: (email, password) => client.post("/auth/login", { email, password }).then((r) => r.data),
  logout: () => client.post("/auth/logout").then((r) => r.data).catch(() => ({ ok: false })),
  googleLogin: (session_id) => client.post("/auth/google-login", { session_id }).then((r) => r.data),
  me: () => client.get("/auth/me").then((r) => r.data),
  impersonate: (uid) => client.post(`/auth/impersonate/${uid}`).then((r) => r.data),
  endImpersonation: () => client.post("/auth/end-impersonation").then((r) => r.data),
  impersonationLog: (limit = 100) => client.get("/auth/impersonation-log", { params: { limit } }).then((r) => r.data),
  changeMyPassword: (current_password, new_password) => client.post("/auth/change-my-password", { current_password, new_password }).then((r) => r.data),
  listUsers: () => client.get("/users").then((r) => r.data),
  createUser: (data) => client.post("/users", data).then((r) => r.data),
  updateUser: (id, data) => client.put(`/users/${id}`, data).then((r) => r.data),
  accessTagsCatalog: () => client.get("/access-tags/catalog").then((r) => r.data),
  deleteUser: (id) => client.delete(`/users/${id}`).then((r) => r.data),
  setUserPassword: (user_id, new_password) => client.post("/users/set-password", { user_id, new_password }).then((r) => r.data),

  // Live location
  postLocation: (data) => client.post("/locations", data).then((r) => r.data),
  liveLocations: (activeMinutes = 360) => client.get("/locations/live", { params: { active_minutes: activeMinutes } }).then((r) => r.data),
  trackCollaborator: (cid, hours = 8) => client.get(`/locations/${cid}/track`, { params: { hours } }).then((r) => r.data),
  // iter211i — trajeto "colado" nas ruas via OSRM Match (segments_snapped)
  trackCollaboratorSnap: (cid, hours = 8) => client.get(`/locations/${cid}/track/snap`, { params: { hours }, timeout: 30000 }).then((r) => r.data),
  dwellAnalysis: (params = {}) => client.get(`/locations/dwell-analysis`, { params }).then((r) => r.data),
  overtimeRange: (yearFrom, monthFrom, yearTo, monthTo, mode = "monthly") =>
    client.get(`/dashboard/overtime/range`, { params: { year_from: yearFrom, month_from: monthFrom, year_to: yearTo, month_to: monthTo, mode } }).then((r) => r.data),

  // Web Push
  pushVapidKey: () => client.get("/push/vapid-public-key").then((r) => r.data),
  pushSubscribe: (sub) => client.post("/push/subscribe", sub).then((r) => r.data),
  pushUnsubscribe: (data) => client.post("/push/unsubscribe", data).then((r) => r.data),
  pushTest: () => client.post("/push/test").then((r) => r.data),
  pushSubscriptions: () => client.get("/push/subscriptions").then((r) => r.data),

  // Heatmap dwell
  dwellHeatmap: (year, month) => client.get(`/dashboard/dwell-heatmap`, { params: { year, month } }).then((r) => r.data),
  dwellHeatmapDay: (year, month, day) => client.get(`/dashboard/dwell-heatmap/day`, { params: { year, month, day } }).then((r) => r.data),

  // Collaborator Auth (Google)
  collabProcessSession: (payload) => client.post(`/collaborator-auth/process-session`, payload, { withCredentials: true }).then((r) => r.data),
  collabAuthMe: (token) => client.get(`/collaborator-auth/me`, { headers: { Authorization: `Bearer ${token}` }, withCredentials: true }).then((r) => r.data),
  collabLogout: (token) => client.post(`/collaborator-auth/logout`, {}, { headers: { Authorization: `Bearer ${token}` }, withCredentials: true }).then((r) => r.data),
  resetCollaboratorFace: (cid, resetDevice = false) =>
    client.post(`/collaborators/${cid}/reset-face`, null, { params: { reset_device: resetDevice } }).then((r) => r.data),
  uploadCollaboratorPhoto: (cid, photoDataUrl) =>
    client.post(`/collaborators/${cid}/photo`, { photo_data_url: photoDataUrl }).then((r) => r.data),

  // AI Corrections (Edit & Teach — Isabella aprende com correções do gestor)
  aiCorrectionCreate: (data) => client.post(`/ai-corrections`, data).then((r) => r.data),
  aiCorrectionList: (limit = 50) =>
    client.get(`/ai-corrections`, { params: { limit } }).then((r) => r.data),
  aiCorrectionDelete: (id) => client.delete(`/ai-corrections/${id}`).then((r) => r.data),

  // Atlaz — sync de assinantes
  atlazCustomerPreview: () => client.get(`/atlaz/customers/preview`).then((r) => r.data),
  atlazCustomerSync: () => client.post(`/atlaz/customers/sync`).then((r) => r.data),
  atlazCustomerStats: () => client.get(`/atlaz/customers/stats`).then((r) => r.data),

  // Logs (sistema)
  listLogs: (params = {}) => client.get(`/logs`, { params }).then((r) => r.data),

  // SaaS — multi-tenant + billing
  saasSignup: (data) => client.post(`/saas/signup`, data).then((r) => r.data),
  saasMe: () => client.get(`/saas/me`).then((r) => r.data),
  saasCheckout: (originUrl) => client.post(`/saas/billing/checkout`, { origin_url: originUrl }).then((r) => r.data),
  saasCheckoutStatus: (sessionId) => client.get(`/saas/billing/status/${sessionId}`).then((r) => r.data),
  saasListCompanies: () => client.get(`/saas/admin/companies`).then((r) => r.data),
  saasAdminMetrics: () => client.get(`/saas/admin/metrics`).then((r) => r.data),
  saasUpdateCompany: (cid, data) => client.patch(`/saas/admin/companies/${cid}`, data).then((r) => r.data),
  saasDeleteCompany: (cid) => client.delete(`/saas/admin/companies/${cid}`).then((r) => r.data),
  saasBulkDeleteCompanies: (ids) => client.post(`/saas/admin/companies/bulk-delete`, { ids }).then((r) => r.data),

  // ============== LOUSA (notas de serviço) ==============
  // ========= Smart Field Ops — ponte oficial App ↔ SmartProv (JWT) =========
  fieldMe: (cid) => client.get("/field/me", { params: cid ? { cid } : {} }).then((r) => r.data),
  fieldDashboard: (cid) => client.get("/field/dashboard", { params: cid ? { cid } : {} }).then((r) => r.data),
  fieldOsToday: (cid) => client.get("/field/os/today", { params: cid ? { cid } : {} }).then((r) => r.data),
  fieldOsDetail: (id, cid) => client.get(`/field/os/${id}`, { params: cid ? { cid } : {} }).then((r) => r.data),
  fieldOsStart: (id, body) => client.post(`/field/os/${id}/start`, body || {}).then((r) => r.data),
  fieldOsArrive: (id, body) => client.post(`/field/os/${id}/arrive`, body).then((r) => r.data),
  fieldOsPhoto: (id, body) => client.post(`/field/os/${id}/photo`, body).then((r) => r.data),
  fieldOsSignalTest: (id, body) => client.post(`/field/os/${id}/signal-test`, body).then((r) => r.data),
  fieldOsMaterialUsed: (id, body) => client.post(`/field/os/${id}/material-used`, body).then((r) => r.data),
  fieldOsFinish: (id, body) => client.post(`/field/os/${id}/finish`, body).then((r) => r.data),
  fieldOsReschedule: (id, body) => client.post(`/field/os/${id}/reschedule`, body).then((r) => r.data),
  fieldOsBlockReason: (id, body) => client.post(`/field/os/${id}/block-reason`, body).then((r) => r.data),
  fieldStockMe: (cid) => client.get("/field/stock/me", { params: cid ? { cid } : {} }).then((r) => r.data),
  fieldMaterialsCatalog: () => client.get("/field/materials/catalog").then((r) => r.data),
  fieldVehicleStatus: (cid) => client.get("/field/vehicle/status", { params: cid ? { cid } : {} }).then((r) => r.data),
  fieldVehicleInspection: (body) => client.post("/field/vehicle/inspection", body).then((r) => r.data),
  fieldEquipmentReturn: (body) => client.post("/field/equipment/return", body).then((r) => r.data),
  fieldSettings: () => client.get("/field/settings").then((r) => r.data),
  fieldSettingsUpdate: (body) => client.put("/field/settings", body).then((r) => r.data),
  fieldAdminOverview: () => client.get("/field/admin/overview").then((r) => r.data),

  lousaByCollaborator: (cid, opts = {}) => {
    const params = opts.adminTest ? { admin_test: 1 } : {};
    return client.get(`/lousa/by-collaborator/${cid}`, { params }).then((r) => r.data);
  },
  lousaAll: () => client.get(`/lousa/all`).then((r) => r.data),
  lousaLogs: (params = {}) => client.get(`/lousa/logs`, { params }).then((r) => r.data),
  lousaTicket: (tid) => client.get(`/lousa/tickets/${tid}`).then((r) => r.data),
  lousaCreateTicket: (data) => client.post(`/lousa/tickets`, data).then((r) => r.data),
  lousaDeleteTicket: (tid) => client.delete(`/lousa/tickets/${tid}`).then((r) => r.data),
  // iter211w — reabre uma OS fechada (gestor/auditor)
  lousaReopenTicket: (tid, data) => client.post(`/lousa/tickets/${tid}/reopen`, data).then((r) => r.data),
  // iter211x — Cardápio de fotos obrigatórias por tipo de OS
  lousaPhotoReqs: () => client.get(`/lousa/photo-requirements`).then((r) => r.data),
  lousaSavePhotoReqs: (items) => client.put(`/lousa/photo-requirements`, { items }).then((r) => r.data),
  lousaTransferTicket: (tid, data) => client.post(`/lousa/tickets/${tid}/transfer`, data).then((r) => r.data),
  lousaEditTicket: (tid, data) => client.patch(`/lousa/tickets/${tid}`, data).then((r) => r.data),
  lousaAdminOpen: (tid) => client.post(`/lousa/tickets/${tid}/admin-open`).then((r) => r.data),
  serverTime: () => client.get(`/server-time`).then((r) => r.data),
  lousaPublicOpen: (tid, cid) => client.post(`/lousa/public/tickets/${tid}/open`, { collaborator_id: cid }).then((r) => r.data),
  // iter237 — auto-distribuir bolhas pendentes na grade de horário,
  // respeitando bolhas fixas (urgente/horario/prioridade) e otimizando
  // logística por nearest-neighbor do GPS do colaborador.
  lousaAutoDistribute: (body = {}) => client.post(`/lousa/auto-distribute`, body).then((r) => r.data),
  // iter211g — timeout estendido (180s) e retry pra evitar "Network Error"
  // em 4G fraco; também marca a tentativa pra cair no fallback se falhar.
  lousaPublicFinalize: async (tid, data) => {
    const post = () => client.post(
      `/lousa/public/tickets/${tid}/finalize`,
      data,
      { timeout: 180000 },
    ).then((r) => r.data);
    try {
      return await post();
    } catch (e) {
      const msg = (e?.message || "").toLowerCase();
      const code = e?.code || "";
      const isNetwork = !e?.response
        && (code === "ECONNABORTED" || msg.includes("network"));
      if (isNetwork) {
        // Espera 1.2s e tenta UMA vez. Em 4G fraco, salva o dia.
        await new Promise((r) => setTimeout(r, 1200));
        return post();
      }
      throw e;
    }
  },
  lousaPublicExitResolve: (cid) => client.post(`/lousa/public/exit-resolve`, { collaborator_id: cid }).then((r) => r.data),
  lousaPublicReorder: (cid, items) => client.post(`/lousa/public/reorder`, { collaborator_id: cid, items }).then((r) => r.data),
  lousaAdminClose: (tid, data) => client.post(`/lousa/tickets/${tid}/admin-close`, data).then((r) => r.data),
  lousaStats: (days = 30) => client.get(`/lousa/stats`, { params: { days } }).then((r) => r.data),
  lousaAiEvaluate: (tid) => client.post(`/lousa/tickets/${tid}/ai-evaluate`).then((r) => r.data),
  lousaAiRankings: (days = 30) => client.get(`/lousa/ai-rankings`, { params: { days } }).then((r) => r.data),
  lousaBulkAction: (data) => client.post(`/lousa/tickets/bulk-action`, data).then((r) => r.data),
  lousaBulkAiEvaluate: (ticket_ids) => client.post(`/lousa/tickets/bulk-ai-evaluate`, { ticket_ids }).then((r) => r.data),
  // Manager callbacks — pedidos do técnico pra gestor entrar em contato
  lousaManagerCallbacks: (status = "pending", limit = 50) =>
    client.get(`/lousa/manager-callbacks`,
      { params: { status, limit } }).then((r) => r.data),
  lousaManagerCallbackResolve: (req_id, data) =>
    client.post(`/lousa/manager-callbacks/${req_id}/resolve`, data)
      .then((r) => r.data),
  lousaManagerCallbackReleaseBack: (req_id, data) =>
    client.post(`/lousa/manager-callbacks/${req_id}/release-back`, data)
      .then((r) => r.data),
  lousaManagerCallbackCreateNewTicket: (req_id, data) =>
    client.post(`/lousa/manager-callbacks/${req_id}/create-new-ticket`, data)
      .then((r) => r.data),
  // RADIUS / PPPoE — Módulo 2
  radiusDashboard: () => client.get(`/radius/dashboard`).then((r) => r.data),
  radiusSessionsActive: (params = {}) =>
    client.get(`/radius/sessions/active`, { params }).then((r) => r.data),
  radiusSessionsHistory: (params = {}) =>
    client.get(`/radius/sessions/history`, { params }).then((r) => r.data),
  radiusDisconnect: (sid) =>
    client.post(`/radius/sessions/${sid}/disconnect`).then((r) => r.data),
  radiusNasList: () => client.get(`/radius/nas`).then((r) => r.data),
  radiusNasUpsert: (data) =>
    client.post(`/radius/nas`, data).then((r) => r.data),
  radiusNasDelete: (id) =>
    client.delete(`/radius/nas/${id}`).then((r) => r.data),
  radiusNasTest: (id, body) =>
    client.post(`/radius/nas/${id}/test-connection`, body).then((r) => r.data),
  radiusLogs: (params = {}) =>
    client.get(`/radius/logs`, { params }).then((r) => r.data),
  // Payment gateways (Asaas, Cora, ...)
  paymentsGatewaysStatus: () =>
    client.get(`/payments/gateways/status`).then((r) => r.data),
  paymentsCustomerSync: (subscriberId, body = { gateway: "asaas" }) =>
    client.post(`/payments/customers/${subscriberId}/sync`, body).then((r) => r.data),
  paymentsChargesList: (params = {}) =>
    client.get(`/payments/charges`, { params }).then((r) => r.data),
  paymentsChargeCreate: (body) =>
    client.post(`/payments/charges`, body).then((r) => r.data),
  paymentsChargeGet: (id, refresh = false) =>
    client.get(`/payments/charges/${id}`,
      { params: refresh ? { refresh: true } : {} }).then((r) => r.data),
  paymentsChargeCancel: (id) =>
    client.post(`/payments/charges/${id}/cancel`).then((r) => r.data),
  paymentsChargeRefund: (id, value) =>
    client.post(`/payments/charges/${id}/refund`,
      value != null ? { value } : null).then((r) => r.data),
  // Site público (landing do provedor)
  siteConfigGet: () => client.get(`/site/config`).then((r) => r.data),
  siteConfigUpdate: (data) =>
    client.put(`/site/config`, data).then((r) => r.data),
  siteLeadsList: (params = {}) =>
    client.get(`/site/leads`, { params }).then((r) => r.data),
  siteLeadUpdate: (id, data) =>
    client.put(`/site/leads/${id}`, data).then((r) => r.data),
  // Fleet (Frota)
  fleetVehicleList: (params = {}) =>
    client.get(`/fleet/vehicles`, { params }).then((r) => r.data),
  fleetVehicleCreate: (data) =>
    client.post(`/fleet/vehicles`, data).then((r) => r.data),
  fleetVehicleUpdate: (id, data) =>
    client.put(`/fleet/vehicles/${id}`, data).then((r) => r.data),
  fleetVehicleAssign: (id, collabId) =>
    client.post(`/fleet/vehicles/${id}/assign`,
      null, { params: { collaborator_id: collabId } }).then((r) => r.data),
  fleetVehicleKpis: (id) =>
    client.get(`/fleet/vehicles/${id}/kpis`).then((r) => r.data),
  fleetVehicleDelete: (id) =>
    client.delete(`/fleet/vehicles/${id}`).then((r) => r.data),
  fleetInspectionDelete: (id) =>
    client.delete(`/fleet/inspections/${id}`).then((r) => r.data),
  fleetFuelDelete: (id) =>
    client.delete(`/fleet/fuel/${id}`).then((r) => r.data),
  fleetFuelImportCsv: (csv_content, opts = {}) =>
    client.post("/fleet/fuel/import-csv", {
      csv_content, delimiter: opts.delimiter || ";",
      dry_run: opts.dry_run !== false,
    }).then((r) => r.data),
  fleetTransferDelete: (id) =>
    client.delete(`/fleet/transfers/${id}`).then((r) => r.data),
  fleetInspectionStart: (vehicleId) =>
    client.post(`/fleet/inspections/start`,
      vehicleId ? { vehicle_id: vehicleId } : {}).then((r) => r.data),
  fleetInspectionUpload: (id, body) =>
    client.post(`/fleet/inspections/${id}/upload-photo`,
      body).then((r) => r.data),
  fleetInspectionSubmit: (id) =>
    client.post(`/fleet/inspections/${id}/submit`).then((r) => r.data),
  fleetInspectionList: (params = {}) =>
    client.get(`/fleet/inspections`, { params }).then((r) => r.data),
  fleetInspectionGet: (id) =>
    client.get(`/fleet/inspections/${id}`).then((r) => r.data),
  fleetInspectionManualApprove: (id) =>
    client.post(`/fleet/inspections/${id}/manual-approve`).then((r) => r.data),
  fleetCanOperate: () =>
    client.get(`/fleet/me/can-operate`).then((r) => r.data),
  fleetTransferList: (params = {}) =>
    client.get(`/fleet/transfers`, { params }).then((r) => r.data),
  fleetTransferCreate: (data) =>
    client.post(`/fleet/transfers`, data).then((r) => r.data),
  fleetTransferSign: (id, data) =>
    client.post(`/fleet/transfers/${id}/sign`, data).then((r) => r.data),
  fleetTransferApprove: (id) =>
    client.post(`/fleet/transfers/${id}/approve`).then((r) => r.data),
  fleetTransferPdfUrl: (id) => {
    const base = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
    const token = window.localStorage.getItem("ponto_token") || "";
    // Endpoint usa StreamingResponse inline → abrir em _blank é suficiente.
    // Como /api/fleet exige auth, anexamos token via querystring se backend aceita,
    // senão usa via fetch + blob.
    return `${base}/api/fleet/transfers/${id}/pdf?__t=${encodeURIComponent(token)}`;
  },
  fleetTransferPdfBlob: async (id) => {
    const r = await client.get(`/fleet/transfers/${id}/pdf`,
      { responseType: "blob" });
    return r.data;
  },
  fleetFuelList: (params = {}) =>
    client.get(`/fleet/fuel`, { params }).then((r) => r.data),
  fleetFuelCreate: (data) =>
    client.post(`/fleet/fuel`, data).then((r) => r.data),
  fleetFuelOcr: (receipt_data_url) =>
    client.post(`/fleet/fuel/ocr`,
      { receipt_data_url }).then((r) => r.data),
  fleetKpis: () =>
    client.get(`/fleet/kpis`).then((r) => r.data),
  // Payment gateways (Asaas, Cora, ...)
  // Contratos / aging policy
  contractsList: (params = {}) =>
    client.get(`/contracts`, { params }).then((r) => r.data),
  contractsCreate: (data) =>
    client.post(`/contracts`, data).then((r) => r.data),
  contractsGet: (id) =>
    client.get(`/contracts/${id}`).then((r) => r.data),
  contractsPatch: (id, data) =>
    client.patch(`/contracts/${id}`, data).then((r) => r.data),
  contractsSuspend: (id, reason) =>
    client.post(`/contracts/${id}/suspend`, { reason })
      .then((r) => r.data),
  contractsReactivate: (id, reason) =>
    client.post(`/contracts/${id}/reactivate`, { reason })
      .then((r) => r.data),
  contractsApplyRadius: (id) =>
    client.post(`/contracts/${id}/apply-radius`).then((r) => r.data),
  contractsLog: (id, limit = 50) =>
    client.get(`/contracts/${id}/log`, { params: { limit } })
      .then((r) => r.data),
  contractsAgingRunNow: () =>
    client.post(`/contracts/aging/run-now`).then((r) => r.data),
  // Clients segments (estilo Atlaz)
  clientsSegment: (segment, search = "", limit = 200) =>
    client.get(`/clients-segments/${segment}`,
      { params: { search, limit } }).then((r) => r.data),
  clientsSegmentCounts: () =>
    client.get(`/clients-segments/_counts/dashboard`).then((r) => r.data),
  // Atlaz integração
  atlazGetSettings: () => client.get(`/atlaz/settings`).then((r) => r.data),
  atlazUpdateSettings: (data) => client.put(`/atlaz/settings`, data).then((r) => r.data),
  atlazTestConnection: () => client.post(`/atlaz/test-connection`).then((r) => r.data),
  atlazSyncNow: () => client.post(`/atlaz/sync-now`).then((r) => r.data),
  atlazSyncTechnicians: () => client.post(`/atlaz/sync-technicians`).then((r) => r.data),
  // iter211z — backfill da data original Atlaz nos tickets existentes
  atlazBackfillDates: (dryRun = false) =>
    client.post(`/atlaz/backfill-dates`, null, { params: { dry_run: dryRun } }).then((r) => r.data),
  // iter211aa — distribui bolhas Atlaz com horário duplicado pelos slots livres
  atlazRedistributeSlots: (dryRun = false) =>
    client.post(`/atlaz/redistribute-slots`, null, { params: { dry_run: dryRun } }).then((r) => r.data),
  atlazReassignExisting: () => client.post(`/atlaz/reassign-existing`).then((r) => r.data),
  atlazSyncLogs: (limit = 30) => client.get(`/atlaz/sync-logs`, { params: { limit } }).then((r) => r.data),
  lousaBriefing: (useAi = true) => client.get(`/lousa/briefing`, { params: { use_ai: useAi } }).then((r) => r.data),
  lousaManagementKpis: (days = 30) => client.get(`/lousa/management-kpis`, { params: { days } }).then((r) => r.data),
  lousaManagementInsights: (days = 30) => client.post(`/lousa/management-insights`, null, { params: { days } }).then((r) => r.data),
  lousaHistory: (params) => client.get(`/lousa/history`, { params }).then((r) => r.data),
  lousaGrid: (params = {}) => client.get(`/lousa/grid`, { params }).then((r) => r.data),
  lousaWipeAll: () => client.post(`/lousa/tickets/wipe-all`, { confirm: "APAGAR TUDO" }).then((r) => r.data),
  // Notificações
  notificationsList: (unreadOnly = false) => client.get(`/notifications`, { params: { unread_only: unreadOnly } }).then((r) => r.data),
  notificationRead: (nid) => client.post(`/notifications/${nid}/read`).then((r) => r.data),
  notificationsReadAll: () => client.post(`/notifications/read-all`).then((r) => r.data),
  // Estoque (stok)
  stokCatalog: () => client.get(`/stok/catalog`).then((r) => r.data),
  stokDashboard: () => client.get(`/stok/dashboard`).then((r) => r.data),
  stokTechnicians: () => client.get(`/stok/technicians`).then((r) => r.data),
  stokOnts: () => client.get(`/stok/onts`).then((r) => r.data),
  // iter211h — Aceita SN obrigatório. Forma preferida: items=[{sn, mac?}].
  // Compat: aceita também `macs: [str]` (cada string tratada como SN no backend).
  // iter215bc — `technician_id` opcional. Quando fornecido, a ONT entra
  // direto no estoque do técnico (sem precisar de transferência).
  stokOntsBulk: (model, snsOrItems, technician_id) => {
    const body = { model };
    if (Array.isArray(snsOrItems)
          && snsOrItems.length
          && typeof snsOrItems[0] === "object") {
      body.items = snsOrItems;
    } else {
      // legado: passa como `macs` mas o backend interpreta cada string como SN
      body.macs = snsOrItems;
    }
    if (technician_id) body.technician_id = technician_id;
    return client.post(`/stok/onts/bulk`, body).then((r) => r.data);
  },
  // iter211m — Define/corrige o SN de uma ONT (legada ou nova)
  stokOntSetSn: (macOrSn, scan_sn) =>
    client.post(`/stok/onts/${encodeURIComponent(macOrSn)}/set-sn`,
                  { scan_sn }).then((r) => r.data),
  // iter211m — Migração massa: popula scan_sn com placeholder AUTOSN_*
  stokOntsMigrateFillSn: () =>
    client.post(`/stok/onts/migrate-fill-sn`).then((r) => r.data),
  stokOntEdit: (mac, model) => client.patch(`/stok/onts/${mac}`, { model }).then((r) => r.data),
  stokOntTransfer: (mac, technician_id) => client.post(`/stok/onts/transfer-to-tech`, { mac, technician_id }).then((r) => r.data),
  stokOntReturn: (mac) => client.post(`/stok/onts/${mac}/return-to-company`).then((r) => r.data),
  stokStock: () => client.get(`/stok/stock`).then((r) => r.data),
  // iter215bd — destino opcional: empresa (default) ou técnico
  stokConsumablePurchase: (consumable_id, pack_qty, technician_id) => {
    const body = { consumable_id, pack_qty };
    if (technician_id) body.technician_id = technician_id;
    return client.post(`/stok/consumables/purchase`, body).then((r) => r.data);
  },
  stokConsumableTransfer: (consumable_id, quantity, technician_id) => client.post(`/stok/consumables/transfer`, { consumable_id, quantity, technician_id }).then((r) => r.data),
  stokServices: () => client.get(`/stok/services`).then((r) => r.data),
  stokServiceCreate: (data) => client.post(`/stok/services`, data).then((r) => r.data),
  stokServiceClose: (sid, data) => client.post(`/stok/services/${sid}/close`, data).then((r) => r.data),
  stokHistory: (params = {}) => client.get(`/stok/history`, { params }).then((r) => r.data),
  // Reset destrutivo (somente Auditor)
  stokAdminReset: (data) => client.post(`/stok/admin/reset`, data).then((r) => r.data),
  stokAdminResetLog: () => client.get(`/stok/admin/reset/log`).then((r) => r.data),
  // Reset granular (item / colaborador / praça) + relatório de quebra
  stokAdminResetGranular: (data) =>
    client.post(`/stok/admin/reset-granular`, data).then((r) => r.data),
  stokShrinkageReport: () =>
    client.get(`/stok/admin/shrinkage-report`).then((r) => r.data),
  // Lookup público: cliente do ticket está no SmartOLT?
  publicClientByTicket: (ticket_id) =>
    client.get(`/smartolt/public/client-by-ticket/${ticket_id}`).then((r) => r.data),
  stokClientes: (identify_manufacturer_max = 0) =>
    client.get(`/stok/clientes`, {
      params: { identify_manufacturer_max },
      timeout: 15000,  // 15s — backend tem timeout duro de 8s + margem
    }).then((r) => r.data),
  stokClientesIdentifyAll: (force = false) =>
    client.post(`/stok/clientes/identify-all`, null, { params: { force } }).then((r) => r.data),
  // Balanço de Estoque (cycle counting)
  balancoList: (limit = 100) => client.get(`/stok/balanco/list`, { params: { limit } }).then((r) => r.data),
  balancoGet: (sid) => client.get(`/stok/balanco/${sid}`).then((r) => r.data),
  balancoStart: (data) => client.post(`/stok/balanco/start`, data).then((r) => r.data),
  balancoScan: (sid, mac) => client.post(`/stok/balanco/${sid}/scan`, { mac }).then((r) => r.data),
  balancoConsumable: (sid, consumable_id, qty) =>
    client.post(`/stok/balanco/${sid}/consumable`, { consumable_id, qty }).then((r) => r.data),
  balancoFinalize: (sid) => client.post(`/stok/balanco/${sid}/finalize`).then((r) => r.data),
  balancoApprove: (sid, data) => client.post(`/stok/balanco/${sid}/approve`, data).then((r) => r.data),
  balancoCancel: (sid) => client.post(`/stok/balanco/${sid}/cancel`).then((r) => r.data),
  // SmartOLT
  smartoltSettings: () => client.get(`/smartolt/settings`).then((r) => r.data),
  smartoltSettingsUpdate: (data) => client.put(`/smartolt/settings`, data).then((r) => r.data),
  smartoltTest: () => client.post(`/smartolt/test-connection`).then((r) => r.data),
  smartoltSync: () => client.post(`/smartolt/sync-onus`).then((r) => r.data),
  smartoltLookup: (params) => client.get(`/smartolt/onu/lookup`, { params }).then((r) => r.data),
  smartoltOnuSignal: (extId) => client.get(`/smartolt/onu/${extId}/signal`).then((r) => r.data),
  smartoltOnuActions: (extId, limit = 20) =>
    client.get(`/smartolt/onu/${extId}/actions`, { params: { limit } }).then((r) => r.data),
  centralIaAiLearning: (days = 30) =>
    client.get(`/central-ia/dashboard/ai-learning`, { params: { days } }).then((r) => r.data),
  centralIaAiLearningExamples: () =>
    client.get(`/central-ia/dashboard/ai-learning/examples`).then((r) => r.data),

  // ========= Motor IA (OpenRouter) =========
  motorIaGetConfig: () => client.get(`/motor-ia/config`).then((r) => r.data),
  motorIaSaveConfig: (payload) => client.put(`/motor-ia/config`, payload).then((r) => r.data),
  motorIaTest: () => client.post(`/motor-ia/test`).then((r) => r.data),
  motorIaSuggestedModels: () => client.get(`/motor-ia/models/suggested`).then((r) => r.data),
  motorIaUsage: (days = 30) => client.get(`/motor-ia/usage`, { params: { days } }).then((r) => r.data),
  motorIaBudgetGet: () => client.get(`/motor-ia/budget`).then((r) => r.data),
  motorIaBudgetSave: (payload) => client.put(`/motor-ia/budget`, payload).then((r) => r.data),
  motorIaBudgetStatus: () => client.get(`/motor-ia/budget/status`).then((r) => r.data),
  motorIaBudgetStatusToday: () => client.get(`/motor-ia/budget/status/today`).then((r) => r.data),

  // ========= Public Access Tokens (links públicos sem login) =========
  publicAccessList: () => client.get(`/public-access/tokens`).then((r) => r.data),
  publicAccessCreate: (payload) =>
    client.post(`/public-access/tokens`, payload).then((r) => r.data),
  publicAccessRevoke: (tokenId) =>
    client.delete(`/public-access/tokens/${tokenId}`).then((r) => r.data),

  // ========= Rede IA — Provisionamento via CTO no Mapa =========
  redeIaCtoClients: (ctoId) =>
    client.get(`/rede-ia/ctos/${ctoId}/clients`).then((r) => r.data),
  redeIaCtoProvision: (ctoId, payload) =>
    client.post(`/rede-ia/ctos/${ctoId}/provision`, payload).then((r) => r.data),
  redeIaCtoLocationUpdate: (ctoId, payload) =>
    client.put(`/rede-ia/ctos/${ctoId}/location`, payload).then((r) => r.data),

  // ========= Lousa — Notas de Qualidade =========
  lousaQualityConfig: () =>
    client.get(`/lousa/quality-notes/config`).then((r) => r.data),
  lousaQualitySaveConfig: (payload) =>
    client.put(`/lousa/quality-notes/config`, payload).then((r) => r.data),
  lousaQualityList: (days = 30) =>
    client.get(`/lousa/quality-notes?days=${days}`).then((r) => r.data),
  lousaCaptureSignal: (ticketId, moment = "close") =>
    client.post(`/lousa/tickets/${ticketId}/capture-signal`, { moment })
      .then((r) => r.data),
  lousaQualityRanking: (days = 7) =>
    client.get(`/lousa/quality-notes/technicians-ranking`, { params: { days } })
      .then((r) => r.data),
  // ========= Bank Import (Sicoob OFX) =========
  bankImportUpload: (file, source = "sicoob") => {
    const fd = new FormData();
    fd.append("file", file);
    return client.post(`/financeiro/bank-import/upload`, fd, {
      params: { source },
      headers: { "Content-Type": "multipart/form-data" },
      // Sicoob PDF c/ 500+ tx: parse + dedupe + memória pode ir até ~2min.
      // IA roda em background (polling via bankImportGetStaging).
      timeout: 180000,
    }).then((r) => r.data);
  },
  bankImportGetStaging: (stagingId) =>
    client.get(`/financeiro/bank-import/staging/${stagingId}`)
      .then((r) => r.data),

  // ========= Data Health (admin) =========
  dataHealth: () =>
    client.get(`/admin/data-health`).then((r) => r.data),
  dataHealthRunMigrations: () =>
    client.post(`/admin/data-health/run-migrations`).then((r) => r.data),

  // ========= Super Admin Toggle (somente Vando opera) =========
  toggleSuperAdmin: (userId, isSuperAdmin) =>
    client.patch(`/users/${userId}/super-admin`,
      { is_super_admin: isSuperAdmin }).then((r) => r.data),

  // ========= Backups MongoDB (iter205) =========
  backupList: () =>
    client.get(`/admin/backup/list`).then((r) => r.data),
  backupCreate: () =>
    client.post(`/admin/backup/create`, null, { timeout: 900000 }).then((r) => r.data),
  backupDelete: (filename) =>
    client.delete(`/admin/backup/${filename}`).then((r) => r.data),
  backupDriveStatus: () =>
    client.get(`/admin/backup/drive-status`).then((r) => r.data),
  backupUploadDrive: (filename) =>
    client.post(`/admin/backup/upload-drive/${filename}`,
                null, { timeout: 600000 }).then((r) => r.data),
  backupRestore: (file, dropExisting) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("drop_existing", dropExisting ? "true" : "false");
    fd.append("confirm", "RESTORE");
    return client.post(`/admin/backup/restore`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 1800000,
    }).then((r) => r.data);
  },
  backupMigrateFromRemote: (sourceUrl, sourceToken, dropExisting) =>
    client.post(`/admin/backup/migrate-from-remote`, {
      source_url: sourceUrl,
      source_token: sourceToken,
      drop_existing: !!dropExisting,
    }, { timeout: 1800000 }).then((r) => r.data),
  backupMigrateConfigGet: () =>
    client.get(`/admin/backup/migrate-config`).then((r) => r.data),
  backupMigrateConfigSet: (enabled, sourceUrl, sourceToken, dropExisting) =>
    client.post(`/admin/backup/migrate-config`, {
      enabled: !!enabled,
      source_url: sourceUrl,
      source_token: sourceToken,
      drop_existing: !!dropExisting,
    }).then((r) => r.data),

  // ========= Central de Compras =========
  purchasesRefs: () => client.get(`/purchases/refs`).then((r) => r.data),
  purchasesList: (params = {}) =>
    client.get(`/purchases`, { params }).then((r) => r.data),
  purchasesByInvoice: (params = {}) =>
    client.get(`/purchases/by-invoice`, { params }).then((r) => r.data),
  purchasesCreate: (payload) =>
    client.post(`/purchases`, payload).then((r) => r.data),
  purchasesUploadExtract: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return client.post(`/purchases/upload-extract`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 120000,
    }).then((r) => r.data);
  },
  purchasesConfirm: (purchaseId) =>
    client.post(`/purchases/${purchaseId}/confirm`).then((r) => r.data),
  // iter211o — reprocessa SNs de uma compra ONT (anexa SNs faltantes
  // que a IA não detectou) e cria as `stok_onts` no estoque da empresa.
  // payload: { extra_sns?: string[], item_index?: number, model?: string }
  purchasesReprocessSns: (purchaseId, payload = {}) =>
    client.post(`/purchases/${purchaseId}/reprocess-sns`, payload)
      .then((r) => r.data),
  // iter211r — Reprocessa SNs anexando UMA FOTO DA NF (Vision + regex).
  // Útil quando a NF foi importada antes de iter211q. Idempotente.
  purchasesReprocessFromImage: (purchaseId, file, itemIndex = 0) => {
    const fd = new FormData();
    fd.append("file", file);
    return client.post(
      `/purchases/${purchaseId}/reprocess-from-image?item_index=${itemIndex}`,
      fd,
      { headers: { "Content-Type": "multipart/form-data" }, timeout: 120000 },
    ).then((r) => r.data);
  },
  purchasesDelete: (purchaseId) =>
    client.delete(`/purchases/${purchaseId}`).then((r) => r.data),

  // ========= Stok bulk transfer =========
  stokOntsList: () => client.get(`/stok/onts`).then((r) => r.data),
  stokOntsBulkTransfer: (macs, technicianId) =>
    client.post(`/stok/onts/transfer-to-tech/bulk`,
      { macs, technician_id: technicianId }).then((r) => r.data),

  // ========= Estoque por Praça =========
  stokPracaSummary: () =>
    client.get(`/stok/praca-summary`).then((r) => r.data),
  bankImportAtlazFetch: (payload) =>
    client.post(`/financeiro/bank-import/atlaz-fetch`, payload)
      .then((r) => r.data),
  bankImportAtlazSummary: () =>
    client.get(`/financeiro/bank-import/atlaz-summary`).then((r) => r.data),
  bankImportReconciliation: (from_date, to_date) =>
    client.get(`/financeiro/bank-import/reconciliation`,
                  { params: { from_date, to_date } }).then((r) => r.data),
  bankImportReconcilePayments: (from_date, to_date, auto_mark = true) =>
    client.post(`/financeiro/bank-import/reconcile-payments`, null,
                    { params: { from_date, to_date, auto_mark } })
      .then((r) => r.data),
  bankImportReconcileConfirm: (matches) =>
    client.post(`/financeiro/bank-import/reconcile-confirm`, { matches })
      .then((r) => r.data),
  bankImportConfirm: (payload) =>
    client.post(`/financeiro/bank-import/confirm`, payload).then((r) => r.data),
  bankImportHistory: (limit = 30) =>
    client.get(`/financeiro/bank-import/history`,
                  { params: { limit } }).then((r) => r.data),
  bankImportMemory: (limit = 200) =>
    client.get(`/financeiro/bank-import/memory`,
                  { params: { limit } }).then((r) => r.data),
  bankImportMemoryDelete: (memId) =>
    client.delete(`/financeiro/bank-import/memory/${memId}`).then((r) => r.data),
  motorIaAgentsList: () => client.get(`/motor-ia/agents`).then((r) => r.data),
  motorIaAgentToggle: (agentId, enabled) =>
    client.put(`/motor-ia/agents/${agentId}`, { enabled }).then((r) => r.data),
  motorIaGroupToggle: (groupName, enabled) =>
    client.put(`/motor-ia/agents/group/${encodeURIComponent(groupName)}`,
                  { enabled }).then((r) => r.data),
  motorIaAgentsHistory: (days = 7) =>
    client.get(`/motor-ia/agents/history`, { params: { days } }).then((r) => r.data),
  churnDashboard: (days = 180) =>
    client.get(`/churn/dashboard`, { params: { days } }).then((r) => r.data),
  churnAiInsight: (days = 180) =>
    client.post(`/churn/ai-insight`, null, { params: { days } }).then((r) => r.data),
  churnAiInsightHistory: (limit = 30) =>
    client.get(`/churn/ai-insight/history`, { params: { limit } }).then((r) => r.data),
  churnAiInsightGet: (id) =>
    client.get(`/churn/ai-insight/${id}`).then((r) => r.data),
  churnAiInsightCompare: (baseId, againstId) =>
    client.post(`/churn/ai-insight/compare`, null,
                  { params: { base_id: baseId, against_id: againstId } }).then((r) => r.data),
  churnScheduleGet: () => client.get(`/churn/briefing-schedule`).then((r) => r.data),
  churnScheduleSave: (payload) =>
    client.put(`/churn/briefing-schedule`, payload).then((r) => r.data),
  churnScheduleRunNow: (days = 30) =>
    client.post(`/churn/briefing-schedule/run-now`, null, { params: { days } }).then((r) => r.data),
  smartoltOnuReboot: (extId) => client.post(`/smartolt/onu/${extId}/reboot`).then((r) => r.data),
  smartoltReconcileOnus: () => client.post(`/smartolt/onus/reconcile`).then((r) => r.data),
  smartoltHistoryKpis: () => client.get(`/smartolt/history/kpis`).then((r) => r.data),
  smartoltHistorySwaps: (days = 30, limit = 200) =>
    client.get(`/smartolt/history/swaps?days=${days}&limit=${limit}`).then((r) => r.data),
  smartoltHistoryTimeseries: (days = 30) =>
    client.get(`/smartolt/history/timeseries?days=${days}`).then((r) => r.data),

  // ========= SmartOLT AI — monitoramento autônomo =========
  smartoltAiSummary: () => client.get(`/smartolt-ai/summary`).then((r) => r.data),
  smartoltAiActiveOutages: () =>
    client.get(`/smartolt-ai/outages/active`).then((r) => r.data),
  smartoltAiRecentOutages: (hours = 24) =>
    client.get(`/smartolt-ai/outages/recent`, { params: { hours } }).then((r) => r.data),
  smartoltAiForceDetect: () =>
    client.post(`/smartolt-ai/outages/detect`).then((r) => r.data),
  // Drafts (modo ATIVO — aprovação humana antes do envio)
  smartoltAiDrafts: (params = {}) =>
    client.get(`/smartolt-ai/drafts`, { params }).then((r) => r.data),
  smartoltAiDraftEdit: (id, text) =>
    client.put(`/smartolt-ai/drafts/${id}`, { text }).then((r) => r.data),
  smartoltAiDraftSend: (id) =>
    client.post(`/smartolt-ai/drafts/${id}/send`).then((r) => r.data),
  smartoltAiDraftDiscard: (id) =>
    client.post(`/smartolt-ai/drafts/${id}/discard`).then((r) => r.data),
  smartoltAiDraftsSendBulk: (payload) =>
    client.post(`/smartolt-ai/drafts/send-bulk`, payload).then((r) => r.data),
  // Templates (mensagens proativa / resolvida / interna)
  smartoltAiTemplates: () =>
    client.get(`/smartolt-ai/templates`).then((r) => r.data),
  smartoltAiSaveTemplates: (payload) =>
    client.put(`/smartolt-ai/templates`, payload).then((r) => r.data),

  // ========= AI Topology (Motor IA card) =========
  aiTopologyFlow: () => client.get(`/ai-topology/flow`).then((r) => r.data),
  // ===== Lousa AI · Triagem =====
  lousaAiSummary: () =>
    client.get(`/lousa-ai/summary`).then((r) => r.data),
  lousaAiTriage: (ticketId, force = false) =>
    client.post(`/lousa-ai/triage/${ticketId}`, null, { params: { force } }).then((r) => r.data),
  lousaAiRevert: (ticketId) =>
    client.post(`/lousa-ai/triage/${ticketId}/revert`).then((r) => r.data),
  // ===== Sentinela Lousa AI — alertas autônomos de tickets =====
  sentinelaSummary: () =>
    client.get(`/sentinela-lousa/summary`).then((r) => r.data),
  sentinelaAlerts: (params = {}) =>
    client.get(`/sentinela-lousa/alerts`, { params }).then((r) => r.data),
  sentinelaScan: () =>
    client.post(`/sentinela-lousa/scan`).then((r) => r.data),
  sentinelaAcknowledge: (id) =>
    client.post(`/sentinela-lousa/alerts/${id}/acknowledge`).then((r) => r.data),
  sentinelaDismiss: (id) =>
    client.post(`/sentinela-lousa/alerts/${id}/dismiss`).then((r) => r.data),
  // Co-Pilot ranking — quem aplica as dicas e quem ganha CSAT
  copilotRankingWeekly: (days = 7) =>
    client.get(`/copilot-ranking/weekly`, { params: { days } }).then((r) => r.data),
  // Public mobile endpoints
  publicTechStock: (cid) => client.get(`/stok/public/collaborator/${cid}/stock`).then((r) => r.data),
  publicValidateMac: (mac, cid) => client.get(`/smartolt/public/validate-mac/${encodeURIComponent(mac)}`,
    { params: cid ? { collaborator_id: cid } : {} }).then((r) => r.data),
  // Lousa: sinal por ticket
  lousaTicketSignal: (tid, refresh = false) =>
    client.get(`/lousa/tickets/${tid}/signal`, { params: { refresh } }).then((r) => r.data),
  // Lousa: sinal por ticket — variante PÚBLICA usada pelo app do colaborador
  // (passa collaborator_id; faz refresh "Live" com force=true no backend)
  lousaPublicTicketSignal: (tid, collaboratorId, refresh = false) =>
    client.get(`/lousa/public/tickets/${tid}/signal`, {
      params: { collaborator_id: collaboratorId, refresh },
    }).then((r) => r.data),
  // AI Preventiva
  aiPrevSettings: () => client.get(`/ai/preventive/settings`).then((r) => r.data),
  aiPrevSettingsUpdate: (d) => client.put(`/ai/preventive/settings`, d).then((r) => r.data),
  aiPrevCapacity: () => client.get(`/ai/preventive/capacity`).then((r) => r.data),
  aiPrevScan: (force = false) =>
    client.post(`/ai/preventive/scan`, null, { params: { force } }).then((r) => r.data),
  aiPrevSuggestions: (status) =>
    client.get(`/ai/preventive/suggestions`, { params: status ? { status } : {} }).then((r) => r.data),
  aiPrevAccept: (sid) => client.post(`/ai/preventive/accept/${sid}`).then((r) => r.data),
  aiPrevReject: (sid) => client.post(`/ai/preventive/reject/${sid}`).then((r) => r.data),
  // Notifications
  notifList: (only_unread = false) =>
    client.get(`/notifications`, { params: { only_unread } }).then((r) => r.data),
  notifUnreadCount: () => client.get(`/notifications/unread-count`).then((r) => r.data),
  notifMarkRead: (id) => client.post(`/notifications/${id}/read`).then((r) => r.data),
  notifMarkAllRead: () => client.post(`/notifications/read-all`).then((r) => r.data),
  // AI Dashboards
  aiDashOverview: (days = 30) => client.get(`/ai/dashboard/overview`, { params: { days } }).then((r) => r.data),
  aiDashTechSpending: (days = 30) => client.get(`/ai/dashboard/tech-spending`, { params: { days } }).then((r) => r.data),
  aiDashRepairMap: (days = 30) => client.get(`/ai/dashboard/repair-map`, { params: { days } }).then((r) => r.data),
  aiDashOnuCriticalMap: (params = {}) => client.get(`/ai/dashboard/onu-critical-map`, { params }).then((r) => r.data),
  aiDashDefective: (days = 90) => client.get(`/ai/dashboard/defective-equipment`, { params: { days } }).then((r) => r.data),
  aiDashCommonIssues: (days = 30) => client.get(`/ai/dashboard/common-issues`, { params: { days } }).then((r) => r.data),
  aiDashRecurring: (days = 30) => client.get(`/ai/dashboard/recurring-tickets`, { params: { days } }).then((r) => r.data),
  aiInsight: (dashboard, context_days = 30) =>
    client.post(`/ai/dashboard/insight`, { dashboard, context_days }).then((r) => r.data),
  aiInsightsHistory: () => client.get(`/ai/dashboard/insights/history`).then((r) => r.data),
  aiDashAssetsOverview: () => client.get(`/ai/dashboard/assets-overview`).then((r) => r.data),
  aiDashManufacturerQuality: (days = 90) =>
    client.get(`/ai/dashboard/manufacturer-quality`, { params: { days } }).then((r) => r.data),

  // Branding (empresa + logo)
  brandingGet: () => client.get(`/branding/settings`).then((r) => r.data),
  brandingUpdate: (d) => client.put(`/branding/settings`, d).then((r) => r.data),

  // Collaborator assets (pertences/EPIs/uniforme)
  assetsList: (cid) => client.get(`/collab-assets/by-collaborator/${cid}`).then((r) => r.data),
  assetCreate: (d) => client.post(`/collab-assets`, d).then((r) => r.data),
  assetUpdate: (aid, d) => client.patch(`/collab-assets/${aid}`, d).then((r) => r.data),
  assetDelete: (aid) => client.delete(`/collab-assets/${aid}`).then((r) => r.data),
  assetRomaneioUrl: (cid, only_active = false, mode = "delivery") => {
    const base = client.defaults.baseURL.replace(/\/$/, "");
    const params = [];
    if (only_active) params.push("only_active=true");
    if (mode && mode !== "delivery") params.push(`mode=${encodeURIComponent(mode)}`);
    const qs = params.length ? `?${params.join("&")}` : "";
    return `${base}/collab-assets/romaneio/${cid}${qs}`;
  },
  // Devolução de itens em posse do colaborador desativado (inclui ONTs + insumos)
  assetDevolucaoUrl: (cid) => {
    const base = client.defaults.baseURL.replace(/\/$/, "");
    return `${base}/collab-assets/romaneio/${cid}?mode=return`;
  },
  // Lista TUDO em posse (assets + ONTs + insumos) — usado no modal de devolução
  assetCustodyFull: (cid) => client.get(`/collab-assets/custody-full/${cid}`).then((r) => r.data),
  // Confirma devolução com assinatura digital do recebedor → retorna PDF blob
  assetReturnConfirm: (cid, payload) =>
    client.post(`/collab-assets/return-confirm/${cid}`, payload, { responseType: "blob" })
      .then((r) => ({ blob: r.data, returnId: r.headers["x-return-id"] || null })),
  // Histórico de devoluções de um colaborador (auditoria)
  assetReturnsHistory: (cid) => client.get(`/collab-assets/returns/${cid}`).then((r) => r.data),
  // Public mobile (no auth)
  publicAssetsList: (cid) => client.get(`/collab-assets/public/by-collaborator/${cid}`).then((r) => r.data),
  publicHoleritesList: (cid) => client.get(`/holerites/public/by-collaborator/${cid}`).then((r) => r.data),
  publicHoleriteFileUrl: (cid, docId) => `${API}/holerites/public/${cid}/${docId}/file`,
  publicSignedHoleriteFileUrl: (cid, docId) => `${API}/holerites/public/${cid}/${docId}/signed-file`,
  publicAssetSign: (d) => client.post(`/collab-assets/public/sign`, d).then((r) => r.data),
  publicBranding: () => client.get(`/branding/public`).then((r) => r.data),
  publicRomaneioUrl: (cid, only_active = false) => {
    const base = client.defaults.baseURL.replace(/\/$/, "");
    return `${base}/collab-assets/public/romaneio/${cid}${only_active ? "?only_active=true" : ""}`;
  },

  // Vehicle Checklist (Inspeção pré-jornada CONTRAN)
  vehicleChecklistTemplate: () => client.get(`/vehicle-checklist/template`).then((r) => r.data),
  vehicleChecklistList: (params = {}) => client.get(`/vehicle-checklist`, { params }).then((r) => r.data),
  vehicleChecklistGet: (id) => client.get(`/vehicle-checklist/${id}`).then((r) => r.data),
  vehicleChecklistCreate: (d) => client.post(`/vehicle-checklist`, d).then((r) => r.data),
  vehicleChecklistUpdate: (id, d) => client.patch(`/vehicle-checklist/${id}`, d).then((r) => r.data),
  vehicleChecklistDelete: (id) => client.delete(`/vehicle-checklist/${id}`).then((r) => r.data),
  vehicleChecklistRecurrent: (days = 30, min_count = 3) =>
    client.get(`/vehicle-checklist/insights/recurrent-defects`, { params: { days, min_count } }).then((r) => r.data),
  vehicleChecklistAttach: (id, payload) =>
    client.post(`/vehicle-checklist/${id}/attachment`, payload).then((r) => r.data),
  vehicleChecklistAttachRemove: (id, idx) =>
    client.delete(`/vehicle-checklist/${id}/attachment/${idx}`).then((r) => r.data),
  vehicleChecklistPdfUrl: (id) => {
    const base = client.defaults.baseURL.replace(/\/$/, "");
    return `${base}/vehicle-checklist/${id}/pdf`;
  },

  // ===== Checklist Veicular · IA (vision + análise) =====
  vchkAiAnalyzeDamage: (id, attachment_indices = null, extra_context = null) =>
    client.post(`/vehicle-checklist/ai/${id}/analyze-damage`, { attachment_indices, extra_context }).then((r) => r.data),
  vchkAiRecurrentInsights: (days = 30, min_count = 3) =>
    client.get(`/vehicle-checklist/ai/recurrent-insights`, { params: { days, min_count } }).then((r) => r.data),
  vchkAiOcrPaper: (image_data_url, template_items = null) =>
    client.post(`/vehicle-checklist/ai/ocr-paper`, { image_data_url, template_items }).then((r) => r.data),
  vchkAiCollabHealth: (cid, days = 60) =>
    client.get(`/vehicle-checklist/ai/collaborator-health/${cid}`, { params: { days } }).then((r) => r.data),

  // ===== Atendimento IA Hub =====
  aihubModels: () => client.get(`/aihub/catalog/models`).then((r) => r.data),
  aihubTools: () => client.get(`/aihub/catalog/tools`).then((r) => r.data),
  aihubAgentsList: () => client.get(`/aihub/agents`).then((r) => r.data),
  aihubAgentCreate: (d) => client.post(`/aihub/agents`, d).then((r) => r.data),
  aihubAgentGet: (id) => client.get(`/aihub/agents/${id}`).then((r) => r.data),
  aihubAgentUpdate: (id, d) => client.patch(`/aihub/agents/${id}`, d).then((r) => r.data),
  aihubAgentDelete: (id) => client.delete(`/aihub/agents/${id}`).then((r) => r.data),
  aihubPlayground: (id, payload) =>
    client.post(`/aihub/agents/${id}/playground`, payload).then((r) => r.data),
  aihubSessions: (id) => client.get(`/aihub/agents/${id}/sessions`).then((r) => r.data),
  aihubSessionMessages: (sid) => client.get(`/aihub/sessions/${sid}/messages`).then((r) => r.data),
  aihubIntegrations: () => client.get(`/aihub/integrations`).then((r) => r.data),
  aihubIntegrationSave: (type, config) =>
    client.put(`/aihub/integrations/${type}`, { config }).then((r) => r.data),
  aihubIntegrationDelete: (type) =>
    client.delete(`/aihub/integrations/${type}`).then((r) => r.data),
  aihubMagnusTest: () =>
    client.post(`/aihub/integrations/magnusbilling/test`).then((r) => r.data),
  aihubWhatsappTest: () =>
    client.post(`/aihub/integrations/whatsapp_cloud/test`).then((r) => r.data),
  aihubMagnusDids: () => client.get(`/aihub/magnusbilling/dids`).then((r) => r.data),
  aihubMagnusCdr: (limit = 100) =>
    client.get(`/aihub/magnusbilling/cdr`, { params: { limit } }).then((r) => r.data),
  aihubCalls: (limit = 100) =>
    client.get(`/aihub/history/calls`, { params: { limit } }).then((r) => r.data),
  aihubOutboundCall: (payload) =>
    client.post(`/aihub/calls/outbound`, payload).then((r) => r.data),
  aihubDashboard: () => client.get(`/aihub/dashboard`).then((r) => r.data),
  aihubAgentTextGen: (payload) =>
    client.post(`/aihub/agents/text-gen`, payload).then((r) => r.data),
  // ===== WhatsApp Baileys (QR) =====
  waBaileysQR: () => client.get(`/whatsapp-baileys/qr`).then((r) => r.data),
  // ===== WhatsApp Channels (multi-number) =====
  waChannelsList: () => client.get(`/whatsapp-channels`).then((r) => r.data),
  waChannelRename: (channelId, name) =>
    client.patch(`/whatsapp-channels/${channelId}`,
                  { channel_name: name }).then((r) => r.data),
  waChannelSetDefault: (channelId) =>
    client.post(`/whatsapp-channels/${channelId}/set-default-outbound`)
      .then((r) => r.data),
  waChannelQR: (channelId) =>
    client.get(`/whatsapp-channels/${channelId}/qr`).then((r) => r.data),
  waChannelStatus: (channelId) =>
    client.get(`/whatsapp-channels/${channelId}/status`).then((r) => r.data),
  waChannelLogout: (channelId) =>
    client.post(`/whatsapp-channels/${channelId}/logout`).then((r) => r.data),
  waBaileysRefreshQR: () => client.post(`/whatsapp-baileys/qr/refresh`).then((r) => r.data),
  waBaileysStatus: () => client.get(`/whatsapp-baileys/status`).then((r) => r.data),
  waBaileysSend: (phone, text, polishedByAi = false) =>
    client.post(`/whatsapp-baileys/send`,
                  { phone, text, polished_by_ai: polishedByAi }).then((r) => r.data),
  // Isabella KPIs (sub-aba do Central IA)
  isabellaKpis: (days = 7) =>
    client.get(`/central-ia/isabella`, { params: { days } }).then((r) => r.data),
  isabellaTicketsSummary: (days = 7) =>
    client.get(`/central-ia/isabella/tickets-summary`,
                  { params: { days } }).then((r) => r.data),
  waHealthOverview: (days = 7) =>
    client.get(`/whatsapp-baileys/health-overview`,
                  { params: { days }, timeout: 30000 }).then((r) => r.data),
  waResetContext: (phone) =>
    client.post(`/whatsapp-baileys/conversation/${encodeURIComponent(phone)}/reset-context`)
      .then((r) => r.data),
  clientsClassification: (params = {}) =>
    client.get(`/central-ia/isabella/clients-classification`, {
      params, timeout: 30000,
    }).then((r) => r.data),
  isabellaConfigGet: () =>
    client.get(`/central-ia/isabella/config`).then((r) => r.data),
  isabellaConfigSet: (polishEnabled) =>
    client.put(`/central-ia/isabella/config`,
                  { polish_button_enabled: !!polishEnabled }).then((r) => r.data),
  waBaileysPolishText: (text) =>
    client.post(`/whatsapp-baileys/polish-text`, { text },
                  { timeout: 25000 }).then((r) => r.data),
  waBaileysSendImage: (phone, imageDataUrl, caption = "") =>
    client.post(`/whatsapp-baileys/send-image`, {
      phone, image_data_url: imageDataUrl, caption,
    }).then((r) => r.data),
  waBaileysSendAudio: (phone, audioB64, mimetype, durationSec) =>
    client.post(`/whatsapp-baileys/send-audio`, {
      phone, audio_b64: audioB64, mimetype, duration_sec: durationSec,
    }, { timeout: 60000 }).then((r) => r.data),
  waBaileysGetWallpaper: () =>
    client.get(`/whatsapp-baileys/wallpaper`).then((r) => r.data),
  waBaileysSetWallpaper: (imageDataUrl) =>
    client.put(`/whatsapp-baileys/wallpaper`,
                 { image_data_url: imageDataUrl },
                 { timeout: 60000 }).then((r) => r.data),
  // Subscribers — busca + by-phone (autocomplete no modal de Agendamento)
  subscribersSearch: (q, limit = 10) =>
    client.get(`/subscribers/search`, { params: { q, limit } }).then((r) => r.data),
  subscribersByPhone: (phone) =>
    client.get(`/subscribers/by-phone`, { params: { phone } }).then((r) => r.data),
  // Appointments
  scheduleCreate: (data) =>
    client.post(`/appointments`, data).then((r) => r.data),
  scheduleList: (params = {}) =>
    client.get(`/appointments`, { params }).then((r) => r.data),
  waBaileysLogout: () =>
    client.post(`/whatsapp-baileys/logout`).then((r) => r.data),
  waBaileysMessages: (limit = 50) =>
    client.get(`/whatsapp-baileys/messages`, { params: { limit } }).then((r) => r.data),
  waBaileysConversations: () =>
    client.get(`/whatsapp-baileys/conversations`).then((r) => r.data),
  waBaileysConversationMessages: (phone, limit = 200) =>
    client.get(`/whatsapp-baileys/conversations/${encodeURIComponent(phone)}/messages`, { params: { limit } }).then((r) => r.data),
  waBaileysAssignConversation: (phone, payload) =>
    client.put(`/whatsapp-baileys/conversations/${encodeURIComponent(phone)}/assign`, payload).then((r) => r.data),
  waBaileysFinalizeConversation: (phone, outcome = "resolved") =>
    client.put(`/whatsapp-baileys/conversations/${encodeURIComponent(phone)}/finalize`, { outcome }).then((r) => r.data),
  waBaileysMarkSeen: (phone) =>
    client.post(`/whatsapp-baileys/conversations/${encodeURIComponent(phone)}/mark-seen`).then((r) => r.data),
  waBaileysResetConversation: (phone) =>
    client.delete(`/whatsapp-baileys/conversations/${encodeURIComponent(phone)}`).then((r) => r.data),
  waBaileysConversationLinkStatus: (phone) =>
    client.get(`/whatsapp-baileys/conversation/${encodeURIComponent(phone)}/link-status`).then((r) => r.data),
  waBaileysUnlinkSubscriber: (phone, subscriberId) =>
    client.delete(`/whatsapp-baileys/conversation/${encodeURIComponent(phone)}/unlink-subscriber`,
      { params: subscriberId ? { subscriber_id: subscriberId } : {} }).then((r) => r.data),

  // Utilitários: CEP e validação de CPF/CNPJ
  utilsValidateDocument: (value) =>
    client.get(`/utils/validate-document`, { params: { value } }).then((r) => r.data),
  utilsLookupCep: (cep) =>
    client.get(`/utils/cep/${encodeURIComponent(cep)}`).then((r) => r.data),

  // Reajuste anual
  reajusteIndices: () =>
    client.get(`/financeiro/reajuste/indices`).then((r) => r.data),
  reajusteRefreshIndex: (name) =>
    client.post(`/financeiro/reajuste/indices/${encodeURIComponent(name)}/refresh`).then((r) => r.data),
  reajusteDue: (horizonDays = 30) =>
    client.get(`/financeiro/reajuste/due`, { params: { horizon_days: horizonDays } }).then((r) => r.data),
  reajustePreview: (subscriberId, indexName) =>
    client.get(`/financeiro/reajuste/preview/${encodeURIComponent(subscriberId)}`,
      { params: indexName ? { index_name: indexName } : {} }).then((r) => r.data),
  reajusteApply: (subscriberId, force = false) =>
    client.post(`/financeiro/reajuste/apply/${encodeURIComponent(subscriberId)}`,
      null, { params: force ? { force: true } : {} }).then((r) => r.data),
  reajusteApplyAllDue: () =>
    client.post(`/financeiro/reajuste/apply-all-due`).then((r) => r.data),
  reajusteHistory: (subscriberId) =>
    client.get(`/financeiro/reajuste/history/${encodeURIComponent(subscriberId)}`).then((r) => r.data),
  reajusteCohort: () =>
    client.get(`/financeiro/reajuste/cohort`).then((r) => r.data),
  reajusteRetentionCurve: () =>
    client.get(`/financeiro/reajuste/retention-curve`).then((r) => r.data),
  waBaileysAttendants: () =>
    client.get(`/whatsapp-baileys/attendants`).then((r) => r.data),
  // Configurações da instância (nome de exibição)
  waBaileysGetInstance: () =>
    client.get(`/whatsapp-baileys/instance`).then((r) => r.data),
  waBaileysSetInstance: (display_name) =>
    client.put(`/whatsapp-baileys/instance`, { display_name }).then((r) => r.data),
  // Auto-reply config
  waBaileysGetAutoReply: () =>
    client.get(`/whatsapp-baileys/auto-reply`).then((r) => r.data),
  waBaileysSetAutoReply: (enabled, agent_name = "Jerusa") =>
    client.put(`/whatsapp-baileys/auto-reply`, { enabled, agent_name }).then((r) => r.data),
  // AI Health — diagnóstico Isabela
  waBaileysAiHealth: () =>
    client.get(`/whatsapp-baileys/ai-health`).then((r) => r.data),
  // Routing stats — dashboard multi-agente
  waBaileysRoutingStats: (days = 7) =>
    client.get(`/whatsapp-baileys/routing-stats`, { params: { days } }).then((r) => r.data),
  // LID — vincular jid@lid anônimo a telefone real
  waBaileysLidLink: (lid, phone) =>
    client.post(`/whatsapp-baileys/lid-link`, { lid, phone }).then((r) => r.data),
  waBaileysLidMap: () =>
    client.get(`/whatsapp-baileys/lid-map`).then((r) => r.data),

  // === Canal Twilio (oficial WhatsApp Business) ===
  twilioConfig: () =>
    client.get(`/whatsapp-twilio/config`).then((r) => r.data),
  twilioSetConfig: (account_sid, auth_token, from_number, enabled = true, sandbox = false) =>
    client.put(`/whatsapp-twilio/config`,
      { account_sid, auth_token, from_number, enabled, sandbox }).then((r) => r.data),
  twilioStatus: () =>
    client.get(`/whatsapp-twilio/status`).then((r) => r.data),
  twilioSendTest: (phone, text) =>
    client.post(`/whatsapp-twilio/test`, { phone, text }).then((r) => r.data),

  // === Canal Meta Oficial (WhatsApp Cloud API / Instagram / Messenger) ===
  metaConfig: () =>
    client.get(`/whatsapp-meta/config`).then((r) => r.data),
  metaSetConfig: (data) =>
    client.put(`/whatsapp-meta/config`, data).then((r) => r.data),
  metaSend: (data) =>
    client.post(`/whatsapp-meta/send`, data).then((r) => r.data),
  metaMessages: (limit = 50, platform = null) =>
    client.get(`/whatsapp-meta/messages`, { params: { limit, platform } }).then((r) => r.data),
  metaRotateVerifyToken: () =>
    client.post(`/whatsapp-meta/verify-token/rotate`).then((r) => r.data),

  // Health check + auto-reconnect dos canais
  integrationsHealth: () => client.get(`/integrations/health`).then((r) => r.data),
  integrationsReconnect: () => client.post(`/integrations/reconnect`).then((r) => r.data),
  integrationsTopology: () => client.get(`/integrations/topology`).then((r) => r.data),

  // ===== Holerite =====
  holeriteList: (params = {}) =>
    client.get(`/holerites`, { params }).then((r) => r.data),
  holeriteUpload: (formData) =>
    client.post(`/holerites/upload`, formData,
      { headers: { "Content-Type": "multipart/form-data" } }
    ).then((r) => r.data),
  holeriteRevoke: (id) =>
    client.delete(`/holerites/${id}`).then((r) => r.data),
  holeriteDeletePermanent: (id) =>
    client.delete(`/holerites/${id}/permanent`).then((r) => r.data),
  holeriteNotify: (id, ttl_hours = 72, custom_message = null) =>
    client.post(`/holerites/${id}/notify`, { ttl_hours, custom_message }).then((r) => r.data),
  holeriteAudit: (id) =>
    client.get(`/holerites/audit/${id}`).then((r) => r.data),
  holeriteApprove: (id, note) =>
    client.post(`/holerites/${id}/approve`, { reviewer_note: note || null }).then((r) => r.data),
  holeriteReject: (id, note) =>
    client.post(`/holerites/${id}/reject`, { reviewer_note: note || null }).then((r) => r.data),
  holeriteReanalyze: (id) =>
    client.post(`/holerites/${id}/reanalyze`).then((r) => r.data),
  holeriteAnomalies: (params = {}) =>
    client.get(`/holerites/anomalies`, { params }).then((r) => r.data),
  // Token público (sem auth)
  holeriteTokenInfo: (token) =>
    client.get(`/holerites/token/${token}/info`).then((r) => r.data),
  holeriteTokenAccess: (token, password) =>
    client.post(`/holerites/token/${token}/access`, { password }).then((r) => r.data),

  // ===== Feriados =====
  feriadosList: (year, tipo) =>
    client.get(`/feriados`, { params: { year, tipo } }).then((r) => r.data),
  feriadoCreate: (data) => client.post(`/feriados`, data).then((r) => r.data),
  feriadoUpdate: (id, data) => client.put(`/feriados/${id}`, data).then((r) => r.data),
  feriadoDelete: (id) => client.delete(`/feriados/${id}`).then((r) => r.data),
  feriadosSeedBr: (year) => client.post(`/feriados/seed-br?year=${year}`).then((r) => r.data),

  // ===== Central IA Dashboard =====
  centralIaKpis: (days = 7) =>
    client.get(`/central-ia/dashboard/kpis`, { params: { days } }).then((r) => r.data),
  centralIaAttendants: (days = 7) =>
    client.get(`/central-ia/dashboard/attendants`, { params: { days } }).then((r) => r.data),
  centralIaProductivity: (days = 30) =>
    client.get(`/central-ia/dashboard/productivity`, { params: { days } }).then((r) => r.data),
  centralIaAiEvaluations: (days = 30) =>
    client.get(`/central-ia/dashboard/ai-evaluations`, { params: { days } }).then((r) => r.data),
  centralIaIntents: (days = 7) =>
    client.get(`/central-ia/dashboard/intents`, { params: { days } }).then((r) => r.data),
  centralIaAlerts: () =>
    client.get(`/central-ia/alerts`).then((r) => r.data),
  centralIaEvaluations: (limit = 100) =>
    client.get(`/central-ia/evaluations`, { params: { limit } }).then((r) => r.data),
  centralIaEvaluateNow: (phone) =>
    client.post(`/central-ia/evaluations/${encodeURIComponent(phone)}`).then((r) => r.data),

  // Coaching
  centralIaCoachingList: (params = {}) =>
    client.get(`/central-ia/coaching`, { params }).then((r) => r.data),
  centralIaCoachingByUser: (days = 7) =>
    client.get(`/central-ia/coaching/by-user`, { params: { days } }).then((r) => r.data),
  centralIaCoachingAction: (coachingId, action) =>
    client.post(`/central-ia/coaching/action`,
      { coaching_id: coachingId, action }).then((r) => r.data),
  centralIaCoachingGenerate: (phone) =>
    client.post(`/central-ia/coaching/generate`, { phone }).then((r) => r.data),
  centralIaCoachingForConversation: (phone) =>
    client.get(`/central-ia/coaching/for-conversation/${encodeURIComponent(phone)}`).then((r) => r.data),

  // Contact profile (avatar WhatsApp + presença)
  waContact: (phone) =>
    client.get(`/whatsapp-baileys/contact/${encodeURIComponent(phone)}`).then((r) => r.data),
  waContactSubscribePresence: (phone) =>
    client.post(`/whatsapp-baileys/contact/${encodeURIComponent(phone)}/subscribe-presence`).then((r) => r.data),
  waCustomerProfile: (phone) =>
    client.get(`/whatsapp-baileys/customer-profile/${encodeURIComponent(phone)}`).then((r) => r.data),

  aihubScheduleLousaTicket: (payload) =>
    client.post(`/aihub/tools/schedule-lousa-ticket`, payload).then((r) => r.data),
  aihubIntegrationsStatus: () =>
    client.get(`/aihub/integrations/status-summary`).then((r) => r.data),

  // ===== Voz da Jerusa (turno-a-turno via Whisper + GPT + TTS) =====
  voiceStartSession: (channel = "browser") =>
    client.post(`/voice/sessions/start`, { channel }).then((r) => r.data),
  voiceTurn: (sid, audioBlob, filename = "turn.webm") => {
    const fd = new FormData();
    fd.append("audio", audioBlob, filename);
    return client.post(`/voice/sessions/${sid}/turn`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
    }).then((r) => r.data);
  },
  voiceEndSession: (sid, reason = "user_hangup") =>
    client.post(`/voice/sessions/${sid}/end`, { reason }).then((r) => r.data),
  voiceGetSession: (sid) =>
    client.get(`/voice/sessions/${sid}`).then((r) => r.data),

  // ===== Assinantes (Subscribers) =====
  subscribersList: (params = {}) => client.get(`/subscribers`, { params }).then((r) => r.data),
  subscribersGet: (id) => client.get(`/subscribers/${id}`).then((r) => r.data),
  subscribersNetworkInfo: (id) =>
    client.get(`/subscribers/${id}/network-info`).then((r) => r.data),
  subscribersBackfillCtoPorts: (dryRun = false) =>
    client.post(`/subscribers/backfill-cto-ports?dry_run=${dryRun ? "true" : "false"}`)
      .then((r) => r.data),
  subscribersCreate: (d) => client.post(`/subscribers`, d).then((r) => r.data),
  subscribersUpdate: (id, d) => client.patch(`/subscribers/${id}`, d).then((r) => r.data),
  subscribersDelete: (id) => client.delete(`/subscribers/${id}`).then((r) => r.data),
  subscribersHistory: (id) => client.get(`/subscribers/${id}/history`).then((r) => r.data),
  subscribersMatchPhone: (phone) =>
    client.post(`/subscribers/match-phone`, { phone }).then((r) => r.data),
  subscribersConflicts: () => client.get(`/subscribers/conflicts`).then((r) => r.data),
  subscribersImport: (formData) =>
    client.post(`/subscribers/import`, formData,
      { headers: { "Content-Type": "multipart/form-data" } }).then((r) => r.data),

  // ----- Wi-Fi self-service (TR-069 via SmartOLT) -----
  wifiStatus: (sid) =>
    client.get(`/wifi/subscriber/${sid}/status`).then((r) => r.data),
  // ----- Billing Engine (Módulo 1 — substituição do Atlaz) -----
  billingStats: (params = {}) =>
    client.get(`/billing/stats`, { params }).then((r) => r.data),
  billingInvoicesList: (params = {}) =>
    client.get(`/billing/invoices`, { params }).then((r) => r.data),
  billingInvoiceGet: (id) =>
    client.get(`/billing/invoices/${id}`).then((r) => r.data),
  billingInvoiceCreate: (data) =>
    client.post(`/billing/invoices`, data).then((r) => r.data),
  billingInvoiceMarkPaid: (id, data = {}) =>
    client.post(`/billing/invoices/${id}/mark-paid`, data).then((r) => r.data),
  billingInvoiceCancel: (id) =>
    client.post(`/billing/invoices/${id}/cancel`).then((r) => r.data),
  billingInvoiceDelete: (id) =>
    client.delete(`/billing/invoices/${id}`).then((r) => r.data),
  billingGenerateBatch: (data) =>
    client.post(`/billing/generate-batch`, data).then((r) => r.data),
  billingGenerateBatchPreview: (competence) =>
    client.get(`/billing/generate-batch/preview`,
      { params: { competence } }).then((r) => r.data),
  billingDunningRulesGet: () =>
    client.get(`/billing/dunning-rules`).then((r) => r.data),
  billingDunningRulesUpdate: (rules) =>
    client.put(`/billing/dunning-rules`, { rules }).then((r) => r.data),
  billingDunningRun: (dryRun = false) =>
    client.post(`/billing/dunning-rules/run`,
      null, { params: { dry_run: dryRun } }).then((r) => r.data),
  billingDunningEventsList: (params = {}) =>
    client.get(`/billing/dunning-events`, { params }).then((r) => r.data),
  billingRunsList: (limit = 50) =>
    client.get(`/billing/runs`, { params: { limit } }).then((r) => r.data),
  billingBackfillPhones: () =>
    client.post(`/billing/invoices/backfill-phones`).then((r) => r.data),
  wifiLinkOnu: (sid, smartolt_onu_id) =>
    client.post(`/wifi/subscriber/${sid}/link-onu`, { smartolt_onu_id })
          .then((r) => r.data),
  wifiUnlinkOnu: (sid) =>
    client.delete(`/wifi/subscriber/${sid}/link-onu`).then((r) => r.data),
  wifiAutoMatch: (sid) =>
    client.post(`/wifi/subscriber/${sid}/auto-match`).then((r) => r.data),
  wifiChange: (sid, payload) =>
    client.post(`/wifi/subscriber/${sid}/change`, payload).then((r) => r.data),
  // Pesquisa de endereço (Nominatim via backend)
  searchAddress: (q) =>
    client.get(`/lousa/map/search-address`, { params: { q } })
          .then((r) => r.data),

  wifiLogs: (sid) =>
    client.get(`/wifi/subscriber/${sid}/logs`).then((r) => r.data),

  // Lousa Map — pinos de serviços por técnico
  lousaMapServices: (params = {}) =>
    client.get(`/lousa/map/services`, { params }).then((r) => r.data),
  lousaMapGeocodeNow: (max_count = 60) =>
    client.post(`/lousa/map/geocode-now`, null, { params: { max_count } })
          .then((r) => r.data),
  wifiReadLive: (sid) =>
    client.get(`/wifi/subscriber/${sid}/read-live`).then((r) => r.data),
  wifiReadLogs: (sid) =>
    client.get(`/wifi/subscriber/${sid}/read-logs`).then((r) => r.data),
  wifiRebootOnu: (sid) =>
    client.post(`/wifi/subscriber/${sid}/reboot-onu`).then((r) => r.data),
  wifiLeadsList: (params = {}) =>
    client.get(`/wifi/leads`, { params }).then((r) => r.data),
  wifiLeadsProcessNow: () =>
    client.post(`/wifi/leads/process-now`).then((r) => r.data),
  wifiLeadsConversionKpis: () =>
    client.get(`/wifi/leads/conversion-kpis`).then((r) => r.data),
  plansAutoMarkPremium: () =>
    client.post(`/plans/auto-mark-premium`).then((r) => r.data),
  planTogglePremiumFeature: (id, feature, enabled) =>
    client.patch(`/plans/${id}/premium-feature`,
                  { feature, enabled }).then((r) => r.data),

  // ----- Plans CRUD -----
  plansList: (params = {}) => client.get(`/plans`, { params }).then((r) => r.data),
  planCreate: (data) => client.post(`/plans`, data).then((r) => r.data),
  planGet: (id) => client.get(`/plans/${id}`).then((r) => r.data),
  planUpdate: (id, data) => client.put(`/plans/${id}`, data).then((r) => r.data),
  planDelete: (id) => client.delete(`/plans/${id}`).then((r) => r.data),
  planAdjustmentPreview: (id, body = {}) =>
    client.post(`/plans/${id}/adjustment/preview`, body).then((r) => r.data),
  planAdjustmentApply: (id, body = {}) =>
    client.post(`/plans/${id}/adjustment/apply`, body).then((r) => r.data),
  planAdjustmentSchedule: (id, body = {}) =>
    client.post(`/plans/${id}/adjustment/schedule`, body).then((r) => r.data),
  planScheduledList: (params = {}) =>
    client.get(`/plans/scheduled-adjustments`, { params }).then((r) => r.data),
  planScheduledCancel: (sid) =>
    client.delete(`/plans/scheduled-adjustments/${sid}`).then((r) => r.data),
  planScheduledNotify: (sid, body = {}) =>
    client.post(`/plans/scheduled-adjustments/${sid}/notify`, body).then((r) => r.data),
  planAdjustmentHistory: (id) =>
    client.get(`/plans/${id}/adjustment/history`).then((r) => r.data),

  // ===== Secretária IA "Ligo" =====
  secretariaAsk: (question, channel = "internal") =>
    client.post(`/secretaria/ask`, { question, channel }).then((r) => r.data),
  secretariaConfig: () => client.get(`/secretaria/config`).then((r) => r.data),
  secretariaRegenerateToken: () =>
    client.post(`/secretaria/regenerate-token`).then((r) => r.data),
  secretariaTestWebhook: (question) =>
    client.post(`/secretaria/test-webhook`,
      { question: question || "ping de teste" },
      { timeout: 90000 }).then((r) => r.data),
  secretariaLogs: (limit = 50) =>
    client.get(`/secretaria/logs`, { params: { limit } }).then((r) => r.data),

  // ===== Drive Backup =====
  driveStatus: () => client.get(`/drive/status`).then((r) => r.data),
  driveConnect: () => client.get(`/oauth/drive/connect`).then((r) => r.data),
  driveDisconnect: () => client.post(`/oauth/drive/disconnect`).then((r) => r.data),

  // ===== AI Training (multiagente) =====
  aiTrainingStatus: () => client.get(`/ai-training/status`).then((r) => r.data),
  aiTrainingReload: () => client.post(`/ai-training/reload`).then((r) => r.data),
  aiTrainingScenarios: (params = {}) =>
    client.get(`/ai-training/scenarios`, { params }).then((r) => r.data),
  aiTrainingScenario: (n) =>
    client.get(`/ai-training/scenarios/${n}`).then((r) => r.data),
  aiTrainingTests: (params = {}) =>
    client.get(`/ai-training/tests`, { params }).then((r) => r.data),
  aiTrainingTest: (n) =>
    client.get(`/ai-training/tests/${n}`).then((r) => r.data),
  aiTrainingRunTest: (n) =>
    client.post(`/ai-training/tests/${n}/run`).then((r) => r.data),
  aiTrainingRunAll: () =>
    client.post(`/ai-training/tests/run-all`).then((r) => r.data),
  aiTrainingDecisionMatrix: () =>
    client.get(`/ai-training/decision-matrix`).then((r) => r.data),
  aiTrainingRuns: (limit = 100) =>
    client.get(`/ai-training/runs`, { params: { limit } }).then((r) => r.data),
  aiTrainingRun: (id) =>
    client.get(`/ai-training/runs/${id}`).then((r) => r.data),
  aiTrainingBatchRuns: (batchId) =>
    client.get(`/ai-training/runs/batch/${batchId}`).then((r) => r.data),
  aiTrainingSchedule: () =>
    client.get(`/ai-training/schedule`).then((r) => r.data),
  aiTrainingScheduleUpdate: (data) =>
    client.put(`/ai-training/schedule`, data).then((r) => r.data),
  driveBackupNow: (include_secrets = false) =>
    client.post(`/drive/backup`, { include_secrets }).then((r) => r.data),
  driveBackupLocalUrl: (include_secrets = false, include_files = true) => {
    // Retorna URL direta pro download — usado em <a href> ou window.open.
    // Inclui o JWT como `?t=` pois o navegador não envia headers customizados
    // em navegação direta.
    const params = new URLSearchParams({
      include_secrets: include_secrets ? "true" : "false",
      include_files: include_files ? "true" : "false",
    });
    const tok = localStorage.getItem("ponto_token");
    if (tok) params.set("t", tok);
    return `${client.defaults.baseURL.replace(/\/$/, "")}/drive/backup-local?${params}`;
  },
  driveBackupLocal: async (include_secrets = false, include_files = true) => {
    // Faz POST autenticado e retorna o Blob pra dar download via JS
    const params = new URLSearchParams({
      include_secrets: include_secrets ? "true" : "false",
      include_files: include_files ? "true" : "false",
    });
    const res = await client.post(`/drive/backup-local?${params}`, null, {
      responseType: "blob",
      timeout: 600000,  // 10 min — backup pode ser pesado
    });
    // Extract filename from Content-Disposition
    const cd = res.headers["content-disposition"] || "";
    const match = cd.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : `smartprov-backup-${Date.now()}.zip`;
    return { blob: res.data, filename, size: res.data.size };
  },
  driveBackupList: () => client.get(`/drive/backups`).then((r) => r.data),
  driveRemoteFiles: () => client.get(`/drive/remote-files`).then((r) => r.data),
  driveRestore: (file_id, mode = "merge", collections = null) =>
    client.post(`/drive/restore`, { file_id, mode, collections }).then((r) => r.data),
  driveSnapshotInfo: () =>
    client.get(`/drive/snapshot-info`).then((r) => r.data),
  driveRestoreUpload: (file, mode = "merge", onUploadProgress, filesTarball = null) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mode", mode);
    if (filesTarball) fd.append("files_tarball", filesTarball);
    return client.post(`/drive/restore-upload`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress,
      timeout: 240000,  // 4 min — tarball pode ser pesado
    }).then((r) => r.data);
  },

  // Conexões (card unificado em Settings)
  connectionsList: () => client.get(`/connections/`).then((r) => r.data),
  connectionUpdate: (integration_id, values) =>
    client.put(`/connections/${integration_id}`, { values }).then((r) => r.data),

  // Financeiro — Cadastros base
  finSummary: () => client.get(`/financeiro/summary`).then((r) => r.data),
  finCategoriesList: (only_active = false) =>
    client.get(`/financeiro/categories`, { params: { only_active } }).then((r) => r.data),
  finCategoryCreate: (data) => client.post(`/financeiro/categories`, data).then((r) => r.data),
  finCategoryUpdate: (id, data) =>
    client.put(`/financeiro/categories/${id}`, data).then((r) => r.data),
  finCategoryDelete: (id) => client.delete(`/financeiro/categories/${id}`).then((r) => r.data),

  finSuppliersList: (only_active = false) =>
    client.get(`/financeiro/suppliers`, { params: { only_active } }).then((r) => r.data),
  finSupplierCreate: (data) => client.post(`/financeiro/suppliers`, data).then((r) => r.data),
  finSupplierUpdate: (id, data) =>
    client.put(`/financeiro/suppliers/${id}`, data).then((r) => r.data),
  finSupplierDelete: (id) => client.delete(`/financeiro/suppliers/${id}`).then((r) => r.data),

  finPaymentMethodsList: (only_active = false) =>
    client.get(`/financeiro/payment-methods`, { params: { only_active } }).then((r) => r.data),
  finPaymentMethodCreate: (data) =>
    client.post(`/financeiro/payment-methods`, data).then((r) => r.data),
  finPaymentMethodUpdate: (id, data) =>
    client.put(`/financeiro/payment-methods/${id}`, data).then((r) => r.data),
  finPaymentMethodDelete: (id) =>
    client.delete(`/financeiro/payment-methods/${id}`).then((r) => r.data),

  finCashAccountsList: (only_active = false) =>
    client.get(`/financeiro/cash-accounts`, { params: { only_active } }).then((r) => r.data),
  finCashAccountCreate: (data) =>
    client.post(`/financeiro/cash-accounts`, data).then((r) => r.data),
  finCashAccountUpdate: (id, data) =>
    client.put(`/financeiro/cash-accounts/${id}`, data).then((r) => r.data),
  finCashAccountDelete: (id) =>
    client.delete(`/financeiro/cash-accounts/${id}`).then((r) => r.data),

  // Filial (unidade/branch). Phase 1 cobre Financeiro (link com bills).
  finFiliaisList: (only_active = false) =>
    client.get(`/financeiro/filiais`, { params: { only_active } }).then((r) => r.data),
  finFilialCreate: (data) => client.post(`/financeiro/filiais`, data).then((r) => r.data),
  finFilialUpdate: (id, data) =>
    client.put(`/financeiro/filiais/${id}`, data).then((r) => r.data),
  finFilialDelete: (id) =>
    client.delete(`/financeiro/filiais/${id}`).then((r) => r.data),

  // Relatórios financeiros (DRE, Aging, KPIs)
  finReportsDre: (params = {}) =>
    client.get(`/financeiro/reports/dre`, { params }).then((r) => r.data),  finReportsAging: () =>
    client.get(`/financeiro/reports/aging-payable`).then((r) => r.data),
  finReportsTopSuppliers: (params = {}) =>
    client.get(`/financeiro/reports/top-suppliers`, { params }).then((r) => r.data),
  finReportsKpis: (params = {}) =>
    client.get(`/financeiro/reports/kpis`, { params }).then((r) => r.data),

  finFiliaisSyncAtlaz: () =>
    client.post(`/financeiro/filiais/sync-from-atlaz`).then((r) => r.data),

  collabsMigrateCargo: () =>
    client.post(`/collaborators/migrate-cargo`).then((r) => r.data),

  // ===== Rede IA =====
  redeIaBairros: () => client.get(`/rede-ia/bairros`).then((r) => r.data),
  redeIaOltNames: () => client.get(`/rede-ia/olt-names`).then((r) => r.data),
  redeIaFiberKpi: (days = 7) =>
    client.get(`/rede-ia/map/fiber-kpi`, { params: { days } }).then((r) => r.data),
  redeIaFiberAlerts: (threshold_m = 200) =>
    client.get(`/rede-ia/map/fiber-alerts`, { params: { threshold_m } }).then((r) => r.data),
  redeIaCableBulkDelete: (data) =>
    client.post(`/rede-ia/cables/bulk-delete`, data).then((r) => r.data),
  // iter207 — Orphan cables (faltavam handlers de API, causavam runtime error)
  redeIaCablesOrphan: () =>
    client.get(`/rede-ia/cables/orphan`).then((r) => r.data),
  redeIaCablesOrphanNear: (lat, lng, radius_m = 30) =>
    client.get(`/rede-ia/cables/orphan-near`,
      { params: { lat, lng, radius_m } }).then((r) => r.data),
  redeIaCablesOrphanNearPublic: (collab_id, lat, lng, radius_m = 30) =>
    client.get(`/rede-ia/public/cables/orphan-near/${collab_id}`,
      { params: { lat, lng, radius_m } }).then((r) => r.data),
  redeIaCablesOrphanSuggest: () =>
    client.post(`/rede-ia/cables/orphan-suggest`).then((r) => r.data),
  redeIaCablesOrphanSuggestVision: () =>
    client.post(`/rede-ia/cables/orphan-suggest-with-vision`,
                null, { timeout: 300000 }).then((r) => r.data),

  // ========= iter207 — Funções faltantes detectadas em runtime =========
  collabRedeMapData: () =>
    client.get(`/collaborator-auth/rede-map/data`).then((r) => r.data),
  finReportsAging: (params = {}) =>
    client.get(`/financeiro/reports/aging-payable`, { params }).then((r) => r.data),
  fleetOdomConfigGet: (collabId) =>
    client.get(`/fleet/odometer/config/${collabId}`).then((r) => r.data),
  fleetOdomConfigSet: (collabId, cfg) =>
    client.put(`/fleet/odometer/config/${collabId}`, cfg).then((r) => r.data),
  fleetOdomKpis: (days = 30) =>
    client.get(`/fleet/odometer/kpis`, { params: { days } }).then((r) => r.data),
  fleetOdomReadings: (params = {}) =>
    client.get(`/fleet/odometer/readings`, { params }).then((r) => r.data),
  fleetOdomSubmitPublic: (collabId, data) =>
    client.post(`/fleet/public/odometer/submit/${collabId}`, data).then((r) => r.data),
  fleetOdomTodayPublic: (collabId) =>
    client.get(`/fleet/public/odometer/today/${collabId}`).then((r) => r.data),
  // Neo (briefing + chat + reports)
  neoBriefingActivate: (cfg) =>
    client.post(`/neo-reports/briefing/activate`, cfg || {}).then((r) => r.data),
  neoBriefingDeactivate: () =>
    client.post(`/neo-reports/briefing/deactivate`).then((r) => r.data),
  neoBriefingStatus: () =>
    client.get(`/neo-reports/briefing/status`).then((r) => r.data),
  neoChatAsk: (data) =>
    client.post(`/neo-chat/ask`, data, { timeout: 120000 }).then((r) => r.data),
  neoChatHistory: (sessionId, limit = 50) =>
    client.get(`/neo-chat/history`,
      { params: { session_id: sessionId, limit } }).then((r) => r.data),
  neoReportHistory: (limit = 20) =>
    client.get(`/neo-reports/history`, { params: { limit } }).then((r) => r.data),
  neoReportTypes: () =>
    client.get(`/neo-reports/report-types`).then((r) => r.data),
  neoReportSchedules: () =>
    client.get(`/neo-reports/schedules`).then((r) => r.data),
  neoReportScheduleCreate: (payload) =>
    client.post(`/neo-reports/schedules`, payload).then((r) => r.data),
  neoReportScheduleUpdate: (id, payload) =>
    client.put(`/neo-reports/schedules/${id}`, payload).then((r) => r.data),
  neoReportScheduleDelete: (id) =>
    client.delete(`/neo-reports/schedules/${id}`).then((r) => r.data),
  neoReportScheduleRun: (id) =>
    client.post(`/neo-reports/schedules/${id}/run`,
                null, { timeout: 180000 }).then((r) => r.data),
  // Network diagnostics
  networkMyIp: () =>
    client.get(`/network/myip`).then((r) => r.data),
  networkIpv6Quality: (period = "24h") =>
    client.get(`/network/ipv6-quality`, { params: { period } }).then((r) => r.data),
  networkIpv6Test: (payload) =>
    client.post(`/network/ipv6-test`, payload, { timeout: 60000 }).then((r) => r.data),
  // ONT duplicate alerts
  ontDuplicateAlertsList: (status) =>
    client.get(`/stok/ont-duplicate-alerts`,
      { params: status ? { status } : {} }).then((r) => r.data),
  ontDuplicateAlertResolve: (alertId, data) =>
    client.post(`/stok/ont-duplicate-alerts/${alertId}/resolve`, data).then((r) => r.data),
  // Propostas comerciais
  propostasList: (params = {}) =>
    client.get(`/propostas`, { params }).then((r) => r.data),
  propostasCreate: (data) =>
    client.post(`/propostas`, data, { timeout: 180000 }).then((r) => r.data),
  propostaDelete: (id) =>
    client.delete(`/propostas/${id}`).then((r) => r.data),
  propostaPdf: (id) =>
    client.get(`/propostas/${id}/pdf`,
      { responseType: "blob", timeout: 60000 }).then((r) => r.data),
  propostasRegenerate: (id, data) =>
    client.post(`/propostas/${id}/regenerate-ai`,
                data, { timeout: 180000 }).then((r) => r.data),
  // Rede IA — cables/route + slack + link-endpoint
  redeIaCableLinkEndpoint: (cableId, endpoint, elementId) =>
    client.post(`/rede-ia/cables/${cableId}/link-endpoint`,
                { endpoint, element_id: elementId }).then((r) => r.data),
  redeIaCableRoute: (body) =>
    client.post(`/rede-ia/cables/route`, body, { timeout: 60000 }).then((r) => r.data),
  redeIaCableRoutePublic: (collabId, body) =>
    client.post(`/rede-ia/public/cables/route/${collabId}`,
                body, { timeout: 60000 }).then((r) => r.data),
  redeIaCableSlackGet: () =>
    client.get(`/rede-ia/settings/cable-slack`).then((r) => r.data),
  redeIaCableSlackUpdate: (cfg) =>
    client.put(`/rede-ia/settings/cable-slack`, cfg).then((r) => r.data),
  redeIaCableSlackPublic: (collabId) =>
    client.get(`/rede-ia/public/settings/cable-slack/${collabId}`).then((r) => r.data),
  // Rede IA — public
  redeIaClientCurrentPort: (collabId, clientId) =>
    client.get(`/rede-ia/public/client-current-port/${collabId}`,
      { params: { client_id: clientId } }).then((r) => r.data),
  redeIaMapDataPublic: (collabId, params = {}) =>
    client.get(`/rede-ia/public/map/data/${collabId}`,
      { params }).then((r) => r.data),
  redeIaSwapClientPort: (collabId, data) =>
    client.post(`/rede-ia/public/swap-client-port/${collabId}`, data).then((r) => r.data),
  redeIaPhotoValidatePublic: (collabId, data) =>
    client.post(`/rede-ia/public/photo-validate/${collabId}`,
                data, { timeout: 120000 }).then((r) => r.data),
  redeIaPhotoOpenTicketPublic: (collabId, data) =>
    client.post(`/rede-ia/public/photo-validate/${collabId}/open-ticket`,
                data).then((r) => r.data),
  // Rede IA — CTO port swaps + VLAN
  redeIaCtoPortSwaps: (ctoId, limit = 50) =>
    client.get(`/rede-ia/ctos/${ctoId}/port-swaps`,
      { params: { limit } }).then((r) => r.data),
  redeIaVlanStats: (vlan) =>
    client.get(`/rede-ia/vlans/${vlan}/stats`).then((r) => r.data),
  redeIaSmartoltSyncVlan: (apply = false) =>
    client.post(`/rede-ia/smartolt/sync-vlan-to-subscribers`,
                null, { params: { apply }, timeout: 300000 }).then((r) => r.data),
  redeIaSmartoltVlanCoverage: () =>
    client.get(`/rede-ia/smartolt/vlan-coverage`).then((r) => r.data),
  // Rede IA — Auto-vision (cables linker)
  redeIaVisionAutoConfig: () =>
    client.get(`/rede-ia/cables/auto-vision/config`).then((r) => r.data),
  redeIaVisionAutoConfigUpdate: (cfg) =>
    client.put(`/rede-ia/cables/auto-vision/config`, cfg).then((r) => r.data),
  redeIaVisionAutoRunNow: () =>
    client.post(`/rede-ia/cables/auto-vision/run-now`,
                null, { timeout: 600000 }).then((r) => r.data),
  redeIaVisionPendingReview: () =>
    client.get(`/rede-ia/cables/auto-vision/pending-review`).then((r) => r.data),
  redeIaVisionReviewApprove: (reviewId) =>
    client.post(`/rede-ia/cables/auto-vision/${reviewId}/approve`).then((r) => r.data),
  redeIaVisionReviewReject: (reviewId) =>
    client.post(`/rede-ia/cables/auto-vision/${reviewId}/reject`).then((r) => r.data),
  // Stok — Scan ONT batch
  scanOntLabel: (data) =>
    client.post(`/stok/retirada/scan-ont`,
                data, { timeout: 90000 }).then((r) => r.data),
  // iter221 — versão pública (sem JWT) usada pelo PWA do colaborador
  // que autentica via session token Google. Mesmo OCR, sem auth.
  scanOntLabelPublic: (data) =>
    client.post(`/stok/retirada/public/scan-ont`,
                data, { timeout: 90000 }).then((r) => r.data),
  scanOntBatchCommit: (data) =>
    client.post(`/stok/retirada/scan-batch-commit`,
                data, { timeout: 60000 }).then((r) => r.data),
  scanOntBatchHistory: (params = {}) =>
    client.get(`/stok/retirada/batch-history`, { params }).then((r) => r.data),
  scanOntBatchHistoryPdf: (params = {}) =>
    client.get(`/stok/retirada/batch-history/pdf`,
      { params, responseType: "blob", timeout: 60000 }).then((r) => r.data),
  // Stok — Transfers
  stokPendingTransfers: (status = "pending") =>
    client.get(`/stok/pending-transfers`, { params: { status } }).then((r) => r.data),
  stokApproveTransfer: (id) =>
    client.post(`/stok/pending-transfers/${id}/approve`).then((r) => r.data),
  stokRejectTransfer: (id, note) =>
    client.post(`/stok/pending-transfers/${id}/reject`,
                { note: note || null }).then((r) => r.data),
  stokTransferKpis: (days = 30) =>
    client.get(`/stok/transfers/kpis`, { params: { days } }).then((r) => r.data),
  // Stok — Cliente history + ONTs
  stokClientCtoPort: (serviceId) =>
    client.get(`/stok/services/${serviceId}/client-cto-port`).then((r) => r.data),
  stokClientOnts: (clientId) =>
    client.get(`/stok/client/${clientId}/onts`).then((r) => r.data),
  stokClienteHistory: (clientId) =>
    client.get(`/stok/clientes/${clientId}/history`).then((r) => r.data),
  stokClienteHistoryByName: (clientName) =>
    client.get(`/stok/clientes/by-name/${encodeURIComponent(clientName)}/history`).then((r) => r.data),
  stokTechOnts: (techId) =>
    client.get(`/stok/tech/${techId}/onts`).then((r) => r.data),
  stokOntTraceability: (ident) =>
    client.get(`/stok/onts/traceability/${encodeURIComponent(ident)}`).then((r) => r.data),
  stokHealthDashboard: () =>
    client.get(`/stok/health-dashboard`).then((r) => r.data),
  // Stok — Defective ONTs
  stokDefectiveOnts: (params = {}) =>
    client.get(`/stok/defective-onts`, { params }).then((r) => r.data),
  stokDefectiveOntConfirmReturn: (mac, notes) =>
    client.post(`/stok/defective-onts/${mac}/confirm-return`,
                { notes: notes || null }).then((r) => r.data),
  stokDefectiveOntRevert: (mac) =>
    client.post(`/stok/defective-onts/${mac}/revert`).then((r) => r.data),
  stokDefectiveOntScrap: (mac) =>
    client.post(`/stok/defective-onts/${mac}/scrap`).then((r) => r.data),
  // Stok — Admin
  stokClearShrinkage: (data) =>
    client.post(`/stok/admin/clear-shrinkage`, data).then((r) => r.data),
  stokReprocessErroEstoque: (limit = 200) =>
    client.post(`/stok/services/reprocess-erro-estoque`,
                null, { params: { limit }, timeout: 180000 }).then((r) => r.data),
  // Tickets (Lousa)
  ticketSaveIpv6Test: (ticketId, data) =>
    client.post(`/lousa/tickets/${ticketId}/ipv6-test`, data).then((r) => r.data),
  ticketSavePingAuto: (ticketId, data) =>
    client.post(`/lousa/tickets/${ticketId}/ping-auto`, data).then((r) => r.data),
  // WhatsApp Baileys público (técnico)
  waBaileysPublicMessages: (collabId, phone, limit = 20) =>
    client.get(`/whatsapp-baileys/public/conversations/${collabId}/${encodeURIComponent(phone)}/messages`,
      { params: { limit } }).then((r) => r.data),
  waBaileysPublicPresence: (collabId, phone) =>
    client.get(`/whatsapp-baileys/public/conversations/${collabId}/${encodeURIComponent(phone)}/presence`).then((r) => r.data),
  waBaileysPublicSend: (collabId, phone, text) =>
    client.post(`/whatsapp-baileys/public/conversations/${collabId}/${encodeURIComponent(phone)}/send`,
                { text }).then((r) => r.data),
  // Auto-reschedule on degraded signal (controlado pelo auditor)
  lousaAutoReschedGet: () =>
    client.get(`/lousa/auto-resched-config`).then((r) => r.data),
  lousaAutoReschedSet: (data) =>
    client.put(`/lousa/auto-resched-config`, data).then((r) => r.data),
  redeIaBairrosPublic: (collab_id) =>
    client.get(`/rede-ia/public/bairros/${collab_id}`).then((r) => r.data),
  redeIaBairroCreate: (data) => client.post(`/rede-ia/bairros`, data).then((r) => r.data),
  redeIaBairroEnsureFromField: (data) =>
    client.post(`/rede-ia/bairros/ensure-from-field`, data).then((r) => r.data),
  redeIaBairroEnsureFromFieldPublic: (collab_id, data) =>
    client.post(`/rede-ia/public/bairros/ensure-from-field/${collab_id}`, data).then((r) => r.data),
  redeIaBairroUpdate: (id, data) => client.put(`/rede-ia/bairros/${id}`, data).then((r) => r.data),
  redeIaBairroDelete: (id) => client.delete(`/rede-ia/bairros/${id}`).then((r) => r.data),
  redeIaBairrosLookup: (q) =>
    client.get(`/rede-ia/bairros/lookup`, { params: { q } }).then((r) => r.data),
  redeIaSuggestName: (sigla, vlan, number) =>
    client.get(`/rede-ia/ctos/suggest-name`, { params: { sigla, vlan, number } }).then((r) => r.data),
  redeIaSuggestNamePublic: (collab_id, sigla, vlan, number) =>
    client.get(`/rede-ia/public/ctos/suggest-name/${collab_id}`,
                { params: { sigla, vlan, number } }).then((r) => r.data),
  redeIaCtoCreate: (data) => client.post(`/rede-ia/ctos`, data).then((r) => r.data),
  redeIaCtoCreatePublic: (collab_id, data) =>
    client.post(`/rede-ia/public/ctos/${collab_id}`, data).then((r) => r.data),
  redeIaCtosList: (params = {}) =>
    client.get(`/rede-ia/ctos`, { params }).then((r) => r.data),
  redeIaCtosOccupancy: (params = {}) =>
    client.get(`/rede-ia/ctos/occupancy`, { params }).then((r) => r.data),
  redeIaCtosListPublic: (collab_id, params = {}) =>
    client.get(`/rede-ia/public/ctos/list/${collab_id}`, { params }).then((r) => r.data),
  redeIaCtoGet: (id) => client.get(`/rede-ia/ctos/${id}`).then((r) => r.data),
  redeIaCtoPhotos: (id) => client.get(`/rede-ia/ctos/${id}/photos`).then((r) => r.data),
  redeIaCtoPhotoAnalyze: (id, body) =>
    client.post(`/rede-ia/ctos/${id}/photos/analyze`, body).then((r) => r.data),
  redeIaAuditOrphans: (refresh = false) =>
    client.get(`/rede-ia/audit/orphan-onus`, { params: { refresh } })
      .then((r) => r.data),
  redeIaStatsByTechnician: (period = "all") =>
    client.get(`/rede-ia/stats/by-technician`, { params: { period } })
      .then((r) => r.data),
  redeIaPendencies: () => client.get(`/rede-ia/pendencies`).then((r) => r.data),
  redeIaValidate: (id, action, comment = "") =>
    client.post(`/rede-ia/ctos/${id}/validate`, { action, comment }).then((r) => r.data),
  redeIaHistory: (cto_id) =>
    client.get(`/rede-ia/history`, { params: { cto_id } }).then((r) => r.data),
  redeIaDiretrizes: () => client.get(`/rede-ia/diretrizes`).then((r) => r.data),
  redeIaDiretrizesUpdate: (text) =>
    client.put(`/rede-ia/diretrizes`, { text }).then((r) => r.data),
  redeIaFlowchart: (params = {}) =>
    client.get(`/rede-ia/flowchart`, { params }).then((r) => r.data),
  redeIaAnalyze: (data = {}) =>
    client.post(`/rede-ia/analyze`, data).then((r) => r.data),
  redeIaCtoQrPng: (cto_id) =>
    `${API}/rede-ia/ctos/${cto_id}/qrcode.png`,
  redeIaCtoQrInfo: (cto_id) =>
    client.get(`/rede-ia/ctos/${cto_id}/qrcode`).then((r) => r.data),
  redeIaCtoPdfRegenerate: (cto_id) =>
    client.post(`/rede-ia/ctos/${cto_id}/regenerate-pdf`).then((r) => r.data),
  redeIaCtoPdfUrl: (cto_id) =>
    `${API}/rede-ia/ctos/${cto_id}/pdf.pdf`,

  // ===== Rede IA Map =====
  redeIaMapData: () => client.get(`/rede-ia/map/data`).then((r) => r.data),
  // Signal points (mancha de clientes com sinal ruim/crítico)
  redeIaSignalPoints: (status = "all", geocode_max = 15) =>
    client.get(`/rede-ia/map/signal-points`,
               { params: { status, geocode_max } })
          .then((r) => r.data),
  redeIaSignalGeocodeBatch: (max_count = 60) =>
    client.post(`/rede-ia/map/signal-points/geocode-batch`,
                null, { params: { max_count } })
          .then((r) => r.data),
  // KMZ — export/import da topologia
  redeIaExportKmzUrl: (vlan = null) => {
    const tok = localStorage.getItem("ponto_token");
    const params = new URLSearchParams();
    if (vlan != null && vlan !== "") params.set("vlan", vlan);
    if (tok) params.set("t", tok);
    return `${client.defaults.baseURL.replace(/\/$/, "")}`
           + `/rede-ia/map/export-kmz?${params}`;
  },
  redeIaExportKmz: async (vlan = null) => {
    const params = {};
    if (vlan != null && vlan !== "") params.vlan = vlan;
    const r = await client.get(`/rede-ia/map/export-kmz`, {
      params, responseType: "blob",
    });
    const cd = r.headers["content-disposition"] || "";
    const m = /filename="([^"]+)"/.exec(cd);
    const filename = m ? m[1]
      : `smartprov-topologia-${Date.now()}.kmz`;
    return { blob: r.data, filename };
  },
  redeIaImportKmz: async (file, dry_run = false) => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await client.post(`/rede-ia/map/import-kmz`, fd, {
      params: { dry_run },
      headers: { "Content-Type": "multipart/form-data" },
    });
    return r.data;
  },
  redeIaCeCreate: (data) => client.post(`/rede-ia/ces`, data).then((r) => r.data),
  redeIaCeUpdate: (id, data) => client.put(`/rede-ia/ces/${id}`, data).then((r) => r.data),
  redeIaCeDelete: (id) => client.delete(`/rede-ia/ces/${id}`).then((r) => r.data),
  redeIaCableCreate: (data) => client.post(`/rede-ia/cables`, data).then((r) => r.data),
  redeIaCableUpdate: (id, data) => client.put(`/rede-ia/cables/${id}`, data).then((r) => r.data),
  redeIaCableDelete: (id) => client.delete(`/rede-ia/cables/${id}`).then((r) => r.data),
  redeIaPositionSave: (data) => client.post(`/rede-ia/map/positions`, data).then((r) => r.data),
  redeIaAutoGenerateCes: (radius_m = 200) =>
    client.post(`/rede-ia/map/auto-generate-ces`, null,
                  { params: { radius_m } }).then((r) => r.data),
  redeIaPublicTokenCreate: (vlan = null, ttl_days = 30) =>
    client.post(`/rede-ia/map/public/token`, { vlan, ttl_days }).then((r) => r.data),
  redeIaNotifications: (unread_only = false) =>
    client.get(`/rede-ia/notifications`, { params: { unread_only } }).then((r) => r.data),
  redeIaNotifMarkRead: (notification_id = null, mark_all = false) =>
    client.post(`/rede-ia/notifications/mark-read`,
                  { notification_id, mark_all }).then((r) => r.data),
  redeIaSyncSmartoltZone: (cto_id) =>
    client.post(`/rede-ia/ctos/${cto_id}/sync-smartolt-zone`).then((r) => r.data),
  redeIaSmartoltZones: () =>
    client.get(`/rede-ia/smartolt/zones`).then((r) => r.data),
  redeIaSmartoltZoneAudit: () =>
    client.get(`/rede-ia/smartolt/zone-audit`).then((r) => r.data),
  redeIaQrScan: (payload) =>
    client.post(`/rede-ia/qrcode/scan`, { payload }).then((r) => r.data),
  redeIaQrBindPort: (data) =>
    client.post(`/rede-ia/qrcode/bind-port`, data).then((r) => r.data),

  // -------------------- Budget / Orçamento_IA --------------------
  budgetList: () => client.get(`/budget`).then((r) => r.data),
  budgetKpis: () => client.get(`/budget/kpis`).then((r) => r.data),
  budgetCreate: (payload) => client.post(`/budget`, payload).then((r) => r.data),
  budgetGet: (bid) => client.get(`/budget/${bid}`).then((r) => r.data),
  budgetUpdate: (bid, payload) =>
    client.put(`/budget/${bid}`, payload).then((r) => r.data),
  budgetDelete: (bid) => client.delete(`/budget/${bid}`).then((r) => r.data),
  budgetUploadCsv: (bid, file) => {
    const fd = new FormData();
    fd.append("file", file);
    return client.post(`/budget/${bid}/upload`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 90000,  // PDF/DOCX disparam Claude, podem demorar
    }).then((r) => r.data);
  },
  budgetAnalyze: (bid) =>
    client.post(`/budget/${bid}/analyze`, null, { timeout: 90000 }).then((r) => r.data),
  budgetPdfUrl: (bid) => `${API}/budget/${bid}/pdf`,

  // --- Isabella Prompt Management (sub-aba "Gestão") ---
  isabellaPromptGet: () =>
    client.get("/whatsapp-baileys/isabella/prompt").then((r) => r.data),
  isabellaPromptUpdate: (system_prompt) =>
    client.put("/whatsapp-baileys/isabella/prompt", { system_prompt }).then((r) => r.data),
  isabellaFragmentsList: () =>
    client.get("/whatsapp-baileys/isabella/fragments").then((r) => r.data),
  isabellaFragmentCreate: (data) =>
    client.post("/whatsapp-baileys/isabella/fragments", data).then((r) => r.data),
  isabellaFragmentPatch: (id, data) =>
    client.patch(`/whatsapp-baileys/isabella/fragments/${id}`, data).then((r) => r.data),
  isabellaFragmentDelete: (id) =>
    client.delete(`/whatsapp-baileys/isabella/fragments/${id}`).then((r) => r.data),
  isabellaTest: (text) =>
    client.post("/whatsapp-baileys/isabella/test", { text }).then((r) => r.data),
  // Migration v6.80: refina prompts dos 4 agentes (Isabella/Álvaro/Camila/Teste)
  isabellaRefineAgentsV680: () =>
    client.post("/whatsapp-baileys/agents/refine-v680").then((r) => r.data),
  waHealthSummary: () =>
    client.get("/whatsapp-baileys/health-summary").then((r) => r.data),
  lousaReturnedNotes: (daysBack = 30) =>
    client.get(`/lousa/returned-notes?days_back=${daysBack}`).then((r) => r.data),
  lousaPingQualityReport: (daysBack = 7) =>
    client.get(`/lousa/ping-quality-report?days_back=${daysBack}`).then((r) => r.data),
  lousaCoachingConfigGet: () =>
    client.get(`/lousa/coaching-config`).then((r) => r.data),
  lousaCoachingConfigSave: (payload) =>
    client.put(`/lousa/coaching-config`, payload).then((r) => r.data),
  lousaCoachingAlerts: (daysBack = 30) =>
    client.get(`/lousa/coaching-alerts?days_back=${daysBack}`).then((r) => r.data),
  lousaClosureQualityReport: (daysBack = 7) =>
    client.get(`/lousa/reports/closure-quality?days_back=${daysBack}`).then((r) => r.data),
  lousaClosureQualityAnalyze: ({ daysBack = 7, limit = 20 } = {}) =>
    client.post(`/lousa/reports/closure-quality/analyze`,
      { days_back: daysBack, limit }).then((r) => r.data),
  collabGrantMobileAccess: (cid) =>
    client.post(`/collaborators/${cid}/grant-mobile-access`).then((r) => r.data),
  networkPing: ({ host, count = 4, port = 80, ticketId = null }) => {
    const cid = new URLSearchParams(window.location.search).get("cid");
    const qs = cid ? `?cid=${encodeURIComponent(cid)}` : "";
    const payload = { host, count, port };
    if (ticketId) payload.ticket_id = ticketId;
    return client.post(`/network/ping${qs}`, payload).then((r) => r.data);
  },
  networkResolve: ({ host }) => {
    const cid = new URLSearchParams(window.location.search).get("cid");
    const qs = cid ? `?cid=${encodeURIComponent(cid)}` : "";
    return client.post(`/network/resolve${qs}`, { host }).then((r) => r.data);
  },
  networkPingHistory: (limit = 20) => {
    const cid = new URLSearchParams(window.location.search).get("cid");
    const cidQs = cid ? `&cid=${encodeURIComponent(cid)}` : "";
    return client.get(`/network/ping/history?limit=${limit}${cidQs}`).then((r) => r.data);
  },

  // --- Boleto PDF preview & logo custom ---
  boletoPreviewUrl: () =>
    `${API}/boleto/preview?ts=${Date.now()}&t=${encodeURIComponent(localStorage.getItem("token") || "")}`,
  boletoPreviewPngBlob: () =>
    client.get("/boleto/preview.png", { responseType: "blob" }).then((r) => r.data),
  boletoPreviewBlob: () =>
    client.get("/boleto/preview", { responseType: "blob" }).then((r) => r.data),
  boletoPreviewClientBlob: (sid) =>
    client.get(`/boleto/preview/${sid}`, { responseType: "blob" }).then((r) => r.data),
  boletoLogoGet: () => client.get("/boleto/logo").then((r) => r.data),
  boletoLogoSet: (image_data_url) =>
    client.put("/boleto/logo", { image_data_url }).then((r) => r.data),
  boletoLogoDelete: () =>
    client.delete("/boleto/logo").then((r) => r.data),

  // Sales Funnel — pipeline de vendas no WhatsApp
  salesDashboard: (days = 30) =>
    client.get(`/sales/dashboard`, { params: { days } }).then((r) => r.data),
  salesLeads: (params = {}) =>
    client.get(`/sales/leads`, { params }).then((r) => r.data),
  salesLeadDetail: (phone) =>
    client.get(`/sales/leads/${encodeURIComponent(phone)}`).then((r) => r.data),
  salesLeadScore: (phone) =>
    client.get(`/sales/leads/${encodeURIComponent(phone)}/score`).then((r) => r.data),
  salesConvertLead: (phone, payload) =>
    client.post(`/sales/leads/${encodeURIComponent(phone)}/convert`, payload).then((r) => r.data),
  salesColdLeads: (min_days = 14, max_days = 90) =>
    client.get(`/sales/cold-leads`, { params: { min_days, max_days } }).then((r) => r.data),
  salesReactivate: (phones, message) =>
    client.post(`/sales/reactivate`, { phones, message }).then((r) => r.data),
};
