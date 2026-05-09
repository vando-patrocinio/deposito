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

// Interceptor de resposta: 401 → limpa token (AuthContext detecta e volta para login)
client.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && typeof window !== "undefined") {
      const url = err?.config?.url || "";
      // Não dispara logout em /auth/login (senão login com senha errada zera tudo)
      if (!url.includes("/auth/login")) {
        window.localStorage.removeItem("ponto_token");
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
  geocodeSearch: (q, limit = 5) => client.get(`/geocode/search`, { params: { q, limit } }).then((r) => r.data),

  // Auth
  adminLogin: (password) => client.post("/auth/admin-login", { password }).then((r) => r.data),
  login: (email, password) => client.post("/auth/login", { email, password }).then((r) => r.data),
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

  // ============== LOUSA (notas de serviço) ==============
  lousaByCollaborator: (cid) => client.get(`/lousa/by-collaborator/${cid}`).then((r) => r.data),
  lousaAll: () => client.get(`/lousa/all`).then((r) => r.data),
  lousaGrid: () => client.get(`/lousa/grid`).then((r) => r.data),
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
  lousaAdminClose: (tid, data) => client.post(`/lousa/tickets/${tid}/admin-close`, data).then((r) => r.data),
  lousaStats: (days = 30) => client.get(`/lousa/stats`, { params: { days } }).then((r) => r.data),
  lousaAiEvaluate: (tid) => client.post(`/lousa/tickets/${tid}/ai-evaluate`).then((r) => r.data),
  lousaBriefing: (useAi = true) => client.get(`/lousa/briefing`, { params: { use_ai: useAi } }).then((r) => r.data),
  lousaManagementKpis: (days = 30) => client.get(`/lousa/management-kpis`, { params: { days } }).then((r) => r.data),
  lousaManagementInsights: (days = 30) => client.post(`/lousa/management-insights`, null, { params: { days } }).then((r) => r.data),
  lousaHistory: (params) => client.get(`/lousa/history`, { params }).then((r) => r.data),
  // Notificações
  notificationsList: (unreadOnly = false) => client.get(`/notifications`, { params: { unread_only: unreadOnly } }).then((r) => r.data),
  notificationRead: (nid) => client.post(`/notifications/${nid}/read`).then((r) => r.data),
  notificationsReadAll: () => client.post(`/notifications/read-all`).then((r) => r.data),
};
