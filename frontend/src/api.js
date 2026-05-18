import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
export const API = `${BACKEND_URL}/api`;

const client = axios.create({ baseURL: API, timeout: 60000 });

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
    if (err?.response?.status === 401 && typeof window !== "undefined") {
      const url = err?.config?.url || "";
      const isAuthEndpoint = url.includes("/auth/login")
        || url.includes("/auth/logout")
        || url.includes("/auth/google-login")
        || url.includes("/auth/me");
      if (!isAuthEndpoint) {
        // Limpa SOMENTE credenciais — preserva preferências de UI
        // (ponto_active_tab, theme, etc.) para que, após re-login, o
        // usuário volte exatamente onde estava.
        ["ponto_token", "ponto_active_company",
         "ponto_onboarding_done", "collab_token", "collab_id"].forEach((k) => {
          try { window.localStorage.removeItem(k); } catch { /* ignore */ }
        });
        // Em vez de hard redirect (que destrói TODO o estado e força
        // o usuário a recarregar a página inteira), apenas dispara
        // um evento. O AppContent escuta e renderiza a tela de login
        // dentro do mesmo componente, preservando aba atual, scroll,
        // dados em memória, etc. UX muito mais suave.
        try {
          window.dispatchEvent(new CustomEvent("smartprov-session-expired", {
            detail: { url, reason: err?.response?.data?.detail || "Sessão expirada" },
          }));
        } catch { /* ignore */ }
      }
    }
    return Promise.reject(err);
  }
);

export const api = {
  _client: client,
  // Colaboradores
  listCollaborators: () => client.get("/collaborators").then((r) => r.data),
  getCollaborator: (id) => client.get(`/collaborators/${id}`).then((r) => r.data),
  createCollaborator: (data) => client.post("/collaborators", data).then((r) => r.data),
  updateCollaborator: (id, data) => client.put(`/collaborators/${id}`, data).then((r) => r.data),
  deleteCollaborator: (id) => client.delete(`/collaborators/${id}`).then((r) => r.data),
  // resetCollaboratorFace movido para baixo (com suporte a resetDevice)

  // Cercas
  listGeofences: (cid) => client.get(`/collaborators/${cid}/geofences`).then((r) => r.data),
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
  deleteUser: (id) => client.delete(`/users/${id}`).then((r) => r.data),
  setUserPassword: (user_id, new_password) => client.post("/users/set-password", { user_id, new_password }).then((r) => r.data),

  // Live location
  postLocation: (data) => client.post("/locations", data).then((r) => r.data),
  liveLocations: (activeMinutes = 360) => client.get("/locations/live", { params: { active_minutes: activeMinutes } }).then((r) => r.data),
  trackCollaborator: (cid, hours = 8) => client.get(`/locations/${cid}/track`, { params: { hours } }).then((r) => r.data),
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
  lousaByCollaborator: (cid) => client.get(`/lousa/by-collaborator/${cid}`).then((r) => r.data),
  lousaAll: () => client.get(`/lousa/all`).then((r) => r.data),
  lousaLogs: (params = {}) => client.get(`/lousa/logs`, { params }).then((r) => r.data),
  lousaTicket: (tid) => client.get(`/lousa/tickets/${tid}`).then((r) => r.data),
  lousaCreateTicket: (data) => client.post(`/lousa/tickets`, data).then((r) => r.data),
  lousaDeleteTicket: (tid) => client.delete(`/lousa/tickets/${tid}`).then((r) => r.data),
  lousaTransferTicket: (tid, data) => client.post(`/lousa/tickets/${tid}/transfer`, data).then((r) => r.data),
  lousaEditTicket: (tid, data) => client.patch(`/lousa/tickets/${tid}`, data).then((r) => r.data),
  lousaAdminOpen: (tid) => client.post(`/lousa/tickets/${tid}/admin-open`).then((r) => r.data),
  serverTime: () => client.get(`/server-time`).then((r) => r.data),
  lousaPublicOpen: (tid, cid) => client.post(`/lousa/public/tickets/${tid}/open`, { collaborator_id: cid }).then((r) => r.data),
  lousaPublicFinalize: (tid, data) => client.post(`/lousa/public/tickets/${tid}/finalize`, data).then((r) => r.data),
  lousaPublicExitResolve: (cid) => client.post(`/lousa/public/exit-resolve`, { collaborator_id: cid }).then((r) => r.data),
  lousaPublicReorder: (cid, items) => client.post(`/lousa/public/reorder`, { collaborator_id: cid, items }).then((r) => r.data),
  lousaAdminClose: (tid, data) => client.post(`/lousa/tickets/${tid}/admin-close`, data).then((r) => r.data),
  lousaStats: (days = 30) => client.get(`/lousa/stats`, { params: { days } }).then((r) => r.data),
  lousaAiEvaluate: (tid) => client.post(`/lousa/tickets/${tid}/ai-evaluate`).then((r) => r.data),
  lousaAiRankings: (days = 30) => client.get(`/lousa/ai-rankings`, { params: { days } }).then((r) => r.data),
  lousaBulkAction: (data) => client.post(`/lousa/tickets/bulk-action`, data).then((r) => r.data),
  lousaBulkAiEvaluate: (ticket_ids) => client.post(`/lousa/tickets/bulk-ai-evaluate`, { ticket_ids }).then((r) => r.data),
  // Atlaz integração
  atlazGetSettings: () => client.get(`/atlaz/settings`).then((r) => r.data),
  atlazUpdateSettings: (data) => client.put(`/atlaz/settings`, data).then((r) => r.data),
  atlazTestConnection: () => client.post(`/atlaz/test-connection`).then((r) => r.data),
  atlazSyncNow: () => client.post(`/atlaz/sync-now`).then((r) => r.data),
  atlazSyncTechnicians: () => client.post(`/atlaz/sync-technicians`).then((r) => r.data),
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
  stokOntsBulk: (model, macs) => client.post(`/stok/onts/bulk`, { model, macs }).then((r) => r.data),
  stokOntEdit: (mac, model) => client.patch(`/stok/onts/${mac}`, { model }).then((r) => r.data),
  stokOntTransfer: (mac, technician_id) => client.post(`/stok/onts/transfer-to-tech`, { mac, technician_id }).then((r) => r.data),
  stokOntReturn: (mac) => client.post(`/stok/onts/${mac}/return-to-company`).then((r) => r.data),
  stokStock: () => client.get(`/stok/stock`).then((r) => r.data),
  stokConsumablePurchase: (consumable_id, pack_qty) => client.post(`/stok/consumables/purchase`, { consumable_id, pack_qty }).then((r) => r.data),
  stokConsumableTransfer: (consumable_id, quantity, technician_id) => client.post(`/stok/consumables/transfer`, { consumable_id, quantity, technician_id }).then((r) => r.data),
  stokServices: () => client.get(`/stok/services`).then((r) => r.data),
  stokServiceCreate: (data) => client.post(`/stok/services`, data).then((r) => r.data),
  stokServiceClose: (sid, data) => client.post(`/stok/services/${sid}/close`, data).then((r) => r.data),
  stokHistory: (params = {}) => client.get(`/stok/history`, { params }).then((r) => r.data),
  stokClientes: (identify_manufacturer_max = 200) =>
    client.get(`/stok/clientes`, { params: { identify_manufacturer_max } }).then((r) => r.data),
  stokClientesIdentifyAll: (force = false) =>
    client.post(`/stok/clientes/identify-all`, null, { params: { force } }).then((r) => r.data),
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
    }).then((r) => r.data);
  },
  bankImportAtlazFetch: (payload) =>
    client.post(`/financeiro/bank-import/atlaz-fetch`, payload)
      .then((r) => r.data),
  bankImportAtlazSummary: () =>
    client.get(`/financeiro/bank-import/atlaz-summary`).then((r) => r.data),
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
  waBaileysGetAutoReply: () =>
    client.get(`/whatsapp-baileys/auto-reply`).then((r) => r.data),
  waBaileysSetAutoReply: (enabled, agentName = "Jerusa") =>
    client.put(`/whatsapp-baileys/auto-reply`,
      { enabled, agent_name: agentName }).then((r) => r.data),

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
  driveBackupList: () => client.get(`/drive/backups`).then((r) => r.data),
  driveRemoteFiles: () => client.get(`/drive/remote-files`).then((r) => r.data),
  driveRestore: (file_id, mode = "merge", collections = null) =>
    client.post(`/drive/restore`, { file_id, mode, collections }).then((r) => r.data),

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

  // ===== Rede IA =====
  redeIaBairros: () => client.get(`/rede-ia/bairros`).then((r) => r.data),
  redeIaBairrosPublic: (collab_id) =>
    client.get(`/rede-ia/public/bairros/${collab_id}`).then((r) => r.data),
  redeIaBairroCreate: (data) => client.post(`/rede-ia/bairros`, data).then((r) => r.data),
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
  redeIaCtoGet: (id) => client.get(`/rede-ia/ctos/${id}`).then((r) => r.data),
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
};
