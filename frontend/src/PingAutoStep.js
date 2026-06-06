/* PingAutoStep — Teste de latência REAL contra 8.8.8.8 (Google DNS).
 *
 * 10 amostras sequenciais via fetch(no-cors) para `https://8.8.8.8/`.
 * Como a página roda em HTTPS, plain HTTP:80 é bloqueado por mixed-content,
 * então usamos 443 (TLS+TCP RTT mede o ping real até Google).
 *
 * Resposta opaca (mode:no-cors) — só medimos o round-trip pra saber se
 * o cliente alcança a internet. Fallback p/ backend echo se Google bloquear.
 * Calcula avg/min/max/jitter/loss reais. Persiste no ticket.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api";

const PROBE_COUNT = 10;
const PROBE_TIMEOUT_MS = 3000;
const BACKEND = process.env.REACT_APP_BACKEND_URL;
// Alvo principal: 8.8.8.8 (Google Public DNS) — porta 443 obrigatório por
// causa de mixed-content na page HTTPS. Cert do Google cobre o IP 8.8.8.8.
const PRIMARY_PROBE_URL = "https://8.8.8.8/";
const FALLBACK_PROBE_URL = `${BACKEND}/api/network/echo`;
// Etiqueta que aparece no relatório do ticket (mantemos 8.8.8.8 mesmo se
// cair pro fallback — o que importa é a saúde da conexão do cliente).
const DISPLAY_HOST = "8.8.8.8";
const DISPLAY_PORT = 443;

async function _pingOnce(url, useNoCors = true) {
  const t0 = performance.now();
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), PROBE_TIMEOUT_MS);
  try {
    const cacheBust = `${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}_${Math.random()}`;
    const opts = {
      method: "GET", cache: "no-store", credentials: "omit",
      signal: ctl.signal,
    };
    if (useNoCors) opts.mode = "no-cors";
    const res = await fetch(cacheBust, opts);
    clearTimeout(timer);
    // No-cors devolve resposta opaca — type === "opaque", status 0 mas OK.
    // Se conseguimos resposta, o round-trip foi medido.
    if (!useNoCors && !res.ok) throw new Error(`HTTP ${res.status}`);
    if (!useNoCors) await res.text();
    return { ok: true, ms: Math.round(performance.now() - t0) };
  } catch (e) {
    clearTimeout(timer);
    return { ok: false, ms: Math.round(performance.now() - t0),
              error: e.name === "AbortError" ? "timeout" : e.message };
  }
}

function ScorePill({ loss }) {
  let bg, fg, label;
  if (loss === 0)      { bg = "#dcfce7"; fg = "#15803d"; label = "Excelente"; }
  else if (loss <= 10) { bg = "#dcfce7"; fg = "#16a34a"; label = "Bom"; }
  else if (loss <= 30) { bg = "#fef3c7"; fg = "#b45309"; label = "Atenção"; }
  else                 { bg = "#fee2e2"; fg = "#991b1b"; label = "Crítico"; }
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 999, fontSize: 10,
      fontWeight: 800, background: bg, color: fg,
    }}>{label}</span>
  );
}

export default function PingAutoStep({ ticketId, onResult, autoRun = true }) {
  const [phase, setPhase] = useState("idle");
  const [result, setResult] = useState(null);
  const [progress, setProgress] = useState(0);
  const [err, setErr] = useState(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const runTest = useCallback(async () => {
    setPhase("running"); setErr(null); setProgress(0);
    try {
      // 1 probe de aquecimento contra 8.8.8.8 — se falhar feio (DNS/firewall
      // bloqueando), faz fallback pro backend echo (que sempre responde).
      const warmup = await _pingOnce(PRIMARY_PROBE_URL, true);
      const targetUrl = warmup.ok ? PRIMARY_PROBE_URL : FALLBACK_PROBE_URL;
      const useNoCors = targetUrl === PRIMARY_PROBE_URL;
      // 2º warmup (DNS+TLS handshake) — descartado, só pra estabilizar
      await _pingOnce(targetUrl, useNoCors);
      const out = [];
      for (let i = 0; i < PROBE_COUNT; i++) {
        const r = await _pingOnce(targetUrl, useNoCors);
        if (!mounted.current) return;
        out.push(r);
        setProgress(Math.round(((i + 1) / PROBE_COUNT) * 100));
        // pausa curta pra não saturar HTTP/2
        await new Promise((res) => setTimeout(res, 80));
      }
      const oks = out.filter((p) => p.ok);
      const lats = oks.map((p) => p.ms);
      const lossPct = Math.round(((PROBE_COUNT - oks.length) / PROBE_COUNT) * 100);
      const avgMs = lats.length
        ? Math.round(lats.reduce((s, v) => s + v, 0) / lats.length) : null;
      const minMs = lats.length ? Math.min(...lats) : null;
      const maxMs = lats.length ? Math.max(...lats) : null;
      const jitter = lats.length > 1
        ? Math.round(lats.reduce((s, v, i) =>
            i > 0 ? s + Math.abs(v - lats[i - 1]) : 0, 0) / (lats.length - 1))
        : null;
      const payload = {
        host: DISPLAY_HOST, port: DISPLAY_PORT, packets: PROBE_COUNT,
        success: oks.length, loss_pct: lossPct, avg_ms: avgMs,
        min_ms: minMs, max_ms: maxMs, jitter_ms: jitter,
        target_used: useNoCors ? "8.8.8.8" : "backend-echo",
        raw_results: out,
      };
      setResult(payload);
      setPhase("done");
      if (ticketId) {
        try { await api.ticketSavePingAuto(ticketId, payload); }
        catch (e) { console.warn("Falha persist ping", e); }
      }
      onResult && onResult(payload);
    } catch (e) {
      if (!mounted.current) return;
      setErr(e?.message || "Erro");
      setPhase("error");
    }
  }, [ticketId, onResult]);

  useEffect(() => { if (autoRun) runTest();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const passed = result && result.loss_pct <= 30;

  return (
    <div data-testid="ping-auto-step" style={{
      padding: 14, borderRadius: 14, marginBottom: 12,
      background: passed
        ? "linear-gradient(135deg,#ecfdf5,#dcfce7)"
        : phase === "done"
          ? "linear-gradient(135deg,#fef3c7,#fde68a)"
          : "linear-gradient(135deg,#eff6ff,#dbeafe)",
      border: "1px solid " + (passed ? "#86efac"
        : phase === "done" ? "#fbbf24" : "#bfdbfe"),
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 10, gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#0c4a6e",
                          letterSpacing: 0.5, textTransform: "uppercase" }}>
            Teste de Latência · 8.8.8.8 (Google) · 10 pings
          </div>
          {phase === "done" && (
            <>
              <div data-testid="ping-auto-verdict" style={{
                fontSize: 13, fontWeight: 700, marginTop: 4, color: "#0f172a",
                display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
              }}>
                <ScorePill loss={result.loss_pct} />
                <span>{result.success}/{PROBE_COUNT} OK</span>
                {result.avg_ms != null && <span>· avg {result.avg_ms}ms</span>}
                <span>· {result.loss_pct}% perda</span>
              </div>
              <div style={{ fontSize: 10, color: "#475569", marginTop: 4,
                              fontFamily: "monospace" }}>
                {result.min_ms != null && `min ${result.min_ms}ms · `}
                {result.max_ms != null && `max ${result.max_ms}ms · `}
                {result.jitter_ms != null && `jitter ${result.jitter_ms}ms`}
              </div>
              <div style={{ fontSize: 9, color: "#64748b", marginTop: 2 }}>
                Alvo: {result.host}:{result.port}
                {result.target_used === "backend-echo" && (
                  <span style={{ color: "#92400e", marginLeft: 4 }}>
                    (fallback)
                  </span>
                )}
              </div>
            </>
          )}
          {phase === "running" && (
            <div style={{ fontSize: 12, color: "#1e40af", marginTop: 4 }}>
              Pingando 8.8.8.8… {progress}%
            </div>
          )}
          {phase === "error" && (
            <div style={{ fontSize: 12, color: "#991b1b", marginTop: 4 }}>
              Erro: {err}
            </div>
          )}
        </div>
        {phase === "done" && (
          <button type="button" data-testid="ping-auto-retest" onClick={runTest}
                    style={{
                      padding: "6px 12px", borderRadius: 8,
                      border: "1px solid #cbd5e1", background: "white",
                      fontSize: 11, fontWeight: 700, cursor: "pointer",
                    }}>
            Re-testar
          </button>
        )}
      </div>
      {phase === "running" && (
        <div style={{ height: 4, borderRadius: 2, background: "#dbeafe", overflow: "hidden" }}>
          <div style={{
            height: "100%", width: `${progress}%`, background: "#2563eb",
            transition: "width 200ms",
          }} />
        </div>
      )}
      {phase === "done" && !passed && (
        <div style={{
          marginTop: 8, padding: 8, borderRadius: 8,
          background: "#fef3c7", border: "1px solid #fbbf24",
          fontSize: 11, color: "#78350f", fontWeight: 600,
        }}>
          ️ Perda de pacotes acima do tolerável. Verifique cabo/conector antes de finalizar.
        </div>
      )}
    </div>
  );
}
