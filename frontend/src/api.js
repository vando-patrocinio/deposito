import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
export const API = `${BACKEND_URL}/api`;

const client = axios.create({ baseURL: API, timeout: 60000 });

// Interceptor: injeta o token JWT salvo em localStorage (escrito pelo AuthContext)
// e o header X-Active-Company (drill-down do super admin)
client.interceptors.request.use((cfg) => {
  if (typeof window !== "undefined") {
    const t = window.localStorage.getItem("ponto_token");
    if (t) cfg.headers.Authorization = `Bearer ${t}`;
    const active = window.localStorage.getItem("ponto_active_company");
    if (active) cfg.headers["X-Active-Company"] = active;
  }
  return cfg;
});

// Interceptor de resposta:
//  - 401 em endpoints autenticados → limpa estado do usuário e força redirect ao /login.
//  - Não dispara em /auth/login nem /auth/logout (esses tratam o erro localmente).
client.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && typeof window !== "undefined") {
      const url = err?.config?.url || "";
      const isAuthEndpoint = url.includes("/auth/login") || url.includes("/auth/logout") || url.includes("/auth/google-login");
      if (!isAuthEndpoint) {
        // Mesmas chaves de USER_SCOPED_KEYS do AuthContext (evita import circular).
        ["ponto_token", "ponto_active_company", "ponto_active_tab",
         "ponto_onboarding_done", "collab_token", "collab_id"].forEach((k) => {
          try { window.localStorage.removeItem(k); } catch { /* ignore */ }
        });
        // Hard redirect: garante que toda memória do app é descartada.
        // Se já está em /login ou na landing, não recarrega (evita loop).
        const path = window.location.pathname || "";
        const isLoginPath = path === "/login" || path === "/" || path === "/preview" || path === "/demo";
        if (!isLoginPath) {
          window.location.replace("/login?session_expired=1");
        }
      }
    }
    return Promise.reject(err);
  }
);

export const api = {
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
  listHolidays: (year) => client.get(`/holidays/${year}`).then((r) => r.data),
  refreshHolidays: (year) => client.post(`/holidays/refresh/${year}`).then((r) => r.data),
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
  discoverHolidays: (id, year) => client.post(`/pracas/${id}/discover-holidays`, null, { params: { year } }).then((r) => r.data),
  applyHolidays: (id, holidays) => client.post(`/pracas/${id}/apply-holidays`, { holidays }).then((r) => r.data),

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
  waBaileysStatus: () => client.get(`/whatsapp-baileys/status`).then((r) => r.data),
  waBaileysSend: (phone, text) =>
    client.post(`/whatsapp-baileys/send`, { phone, text }).then((r) => r.data),
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
  driveBackupNow: (include_secrets = false) =>
    client.post(`/drive/backup`, { include_secrets }).then((r) => r.data),
  driveBackupList: () => client.get(`/drive/backups`).then((r) => r.data),
  driveRemoteFiles: () => client.get(`/drive/remote-files`).then((r) => r.data),
  driveRestore: (file_id, mode = "merge", collections = null) =>
    client.post(`/drive/restore`, { file_id, mode, collections }).then((r) => r.data),
};
