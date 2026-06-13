/**
 * humanizeError — traduz erros técnicos (axios, fetch, HTTP) para
 * mensagens humanas em português do Brasil que fazem sentido pro usuário
 * final (gestor, técnico, cliente).
 *
 * Política da Casa: NUNCA exibir "Request failed with status code 502"
 * ou stack-trace ao usuário. Sempre humanizar.
 */

const HTTP_PTBR = {
  400: "Dados inválidos. Confira e tente novamente.",
  401: "Sua sessão expirou. Faça login novamente.",
  403: "Você não tem permissão para essa ação.",
  404: "Item não encontrado.",
  408: "A operação demorou demais. Tente novamente.",
  409: "Conflito: outro usuário pode ter alterado este item.",
  413: "Arquivo grande demais.",
  422: "Dados inválidos. Confira o formulário.",
  429: "Muitas tentativas seguidas. Aguarde um momento.",
  500: "Erro interno do servidor. Já estamos analisando.",
  502: "Servidor indisponível no momento. Tente em alguns segundos.",
  503: "Sistema em manutenção. Tente novamente em instantes.",
  504: "Tempo esgotado na resposta do servidor. Tente de novo.",
};

const NETWORK_REGEX
  = /network error|failed to fetch|err_network|net::|connection refused/i;

function _detail(err) {
  if (!err) return null;
  // FastAPI typically returns {detail: "..."}.
  const d = err?.response?.data?.detail
        || err?.response?.data?.error
        || err?.response?.data?.message
        || err?.data?.detail
        || err?.detail;
  if (typeof d === "string" && d.trim()) return d.trim();
  if (Array.isArray(d) && d.length) {
    // Pydantic v2 422 → array de {type, loc, msg, input, ctx}. Junta msgs.
    const msgs = d
      .map((e) => (typeof e === "string" ? e : (e?.msg || e?.message || "")))
      .filter(Boolean);
    if (msgs.length) return msgs.slice(0, 3).join(" · ");
  }
  // Objeto Pydantic isolado (não em array)
  if (d && typeof d === "object") {
    if (typeof d.msg === "string") return d.msg;
    if (typeof d.message === "string") return d.message;
    if (typeof d.code === "string" && typeof d.detail === "string") {
      return d.detail;
    }
  }
  return null;
}

export function humanizeError(err, fallback) {
  if (!err) return fallback || "Algo deu errado. Tente novamente.";

  // Mensagem detalhada vinda do backend (humana, traduzida) tem prioridade.
  const detail = _detail(err);
  if (detail) return detail;

  // String pura
  if (typeof err === "string") {
    if (NETWORK_REGEX.test(err)) {
      return "Sem conexão. Verifique sua internet e tente novamente.";
    }
    if (/timeout/i.test(err)) {
      return "Tempo esgotado. Tente novamente em instantes.";
    }
    return err;
  }

  // Axios / fetch
  const status = err?.response?.status || err?.status;
  if (status && HTTP_PTBR[status]) return HTTP_PTBR[status];
  if (status) return `Erro do servidor (${status}). Tente novamente.`;

  const msg = err?.message || "";
  if (NETWORK_REGEX.test(msg)) {
    return "Sem conexão. Verifique sua internet e tente novamente.";
  }
  if (/timeout/i.test(msg)) {
    return "Tempo esgotado. Tente novamente em instantes.";
  }
  if (msg) {
    // Mensagens técnicas conhecidas → tradução direta.
    const TRANS = [
      [/^Request failed with status code (\d+)$/i,
        (m) => HTTP_PTBR[Number(m[1])]
                 || `Erro do servidor (${m[1]}). Tente novamente.`],
      [/^Network Error$/i,
        () => "Sem conexão. Verifique sua internet e tente novamente."],
      [/loadtimeout|load timeout/i,
        () => "A página demorou demais para carregar."],
    ];
    for (const [rx, fn] of TRANS) {
      const m = msg.match(rx);
      if (m) return fn(m);
    }
    // Mensagem em inglês genérica → não exibir literal.
    if (/[a-z]/i.test(msg) && !/[áéíóúçãõ]/i.test(msg)) {
      return fallback || "Algo deu errado. Tente novamente.";
    }
    return msg;
  }

  return fallback || "Algo deu errado. Tente novamente.";
}

/**
 * humanizeAndAlert — atalho para `window.alert(humanizeError(err))`
 * usado nos handlers de toolbar/modal que ainda chamam alert nativo.
 */
export function humanizeAndAlert(err, fallback) {
  if (typeof window === "undefined") return;
  window.alert(humanizeError(err, fallback));
}
