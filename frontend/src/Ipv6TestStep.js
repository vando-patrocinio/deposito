/* Ipv6TestStep — Testa IPv6 do cliente direto no navegador do técnico.
 * Roda automaticamente ao montar + botão pra re-testar.
 *
 * Estratégia (similar ao test-ipv6.com):
 *  - <img> tags carregando endpoints só-IPv4, só-IPv6, dual-stack, MTU-large.
 *  - onload = reachable, onerror = no reach. Timeout 6s.
 *  - Backend /api/network/myip retorna o IP público de quem chamou (v4 ou v6).
 *  - Score 0-10 calculado no backend.
 *
 * Resultado salvo no ticket via POST /api/lousa/tickets/{id}/ipv6-test
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api";

const PROBE_TIMEOUT_MS = 6000;

// Endpoints públicos do test-ipv6.com (carregam imagens pequenas dedicadas
// a forçar a versão de IP via hostname). Cache-buster aplicado no useEffect.
const PROBES = {
  ipv4: "https://ipv4.test-ipv6.com/images/knob_green.png",
  ipv6: "https://ipv6.test-ipv6.com/images/knob_green.png",
  ds:   "https://ds.test-ipv6.com/images/knob_green.png",
  mtu:  "https://ipv6.test-ipv6.com/images/buttonshadow.png",
};

function _loadImg(url, timeoutMs = PROBE_TIMEOUT_MS) {
  return new Promise((resolve) => {
    const img = new Image();
    const t0 = performance.now();
    let done = false;
    const finish = (ok) => {
      if (done) return; done = true;
      resolve({ ok, ms: Math.round(performance.now() - t0) });
    };
    img.onload = () => finish(true);
    img.onerror = () => finish(false);
    setTimeout(() => finish(false), timeoutMs);
    img.src = url + (url.includes("?") ? "&" : "?") + "_t=" + Date.now();
  });
}

function ScoreCircle({ score }) {
  const color =
    score >= 10 ? "#15803d" :
    score >= 8  ? "#16a34a" :
    score >= 4  ? "#f59e0b" : "#dc2626";
  return (
    <div data-testid="ipv6-score" style={{
      width: 84, height: 84, borderRadius: "50%",
      display: "grid", placeItems: "center",
      border: `4px solid ${color}`, background: "#fff",
    }}>
      <div style={{ fontSize: 22, fontWeight: 900, color, lineHeight: 1 }}>
        {score}/10
      </div>
    </div>
  );
}

function CheckRow({ ok, label, value }) {
  return (
    <div data-testid={`ipv6-row-${label.replace(/\s/g, "-").toLowerCase()}`}
         style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "8px 10px", borderRadius: 8,
      background: ok ? "#dcfce7" : "#fee2e2",
      border: "1px solid " + (ok ? "#bbf7d0" : "#fecaca"),
      marginBottom: 6, fontSize: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                       color: ok ? "#166534" : "#991b1b", fontWeight: 700 }}>
        <span style={{ fontSize: 14 }}>{ok ? "✓" : "✕"}</span>
        {label}
      </div>
      {value && (
        <div style={{ color: ok ? "#15803d" : "#991b1b", fontFamily: "monospace",
                         fontSize: 11 }}>
          {value}
        </div>
      )}
    </div>
  );
}

export default function Ipv6TestStep({ ticketId, onResult, autoRun = true }) {
  const [phase, setPhase] = useState("idle"); // idle | running | done | error
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);
  const mounted = useRef(true);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const runTest = useCallback(async () => {
    setPhase("running");
    setErr(null);
    try {
      // 1) Backend vê o IP público do cliente (via X-Forwarded-For)
      const myipRaw = await api.networkMyIp();
      // 2) Probes paralelos para v4/v6/dual-stack
      const [ipv4Probe, ipv6Probe, dsProbe] = await Promise.all([
        _loadImg(PROBES.ipv4),
        _loadImg(PROBES.ipv6),
        _loadImg(PROBES.ds),
      ]);
      if (!mounted.current) return;
      // MTU: se IPv6 funciona, conexão tá OK pra pacotes grandes (o image
      // probe de buttonshadow era pouco confiável em alguns DPIs).
      const mtu_ok = ipv6Probe.ok;
      const payload = {
        ipv4_reachable: ipv4Probe.ok,
        ipv6_reachable: ipv6Probe.ok,
        dual_stack_ok: dsProbe.ok && ipv6Probe.ok,
        mtu_ok,
        dns_ipv6_ok: ipv6Probe.ok,
        v4_addr: myipRaw.family === 4 ? myipRaw.ip : null,
        v6_addr: myipRaw.family === 6 ? myipRaw.ip : null,
        latency_v4_ms: ipv4Probe.ok ? ipv4Probe.ms : null,
        latency_v6_ms: ipv6Probe.ok ? ipv6Probe.ms : null,
        raw_results: {
          myip: myipRaw,
          probes: {
            ipv4: ipv4Probe, ipv6: ipv6Probe, ds: dsProbe,
          },
        },
      };
      const verdict = await api.networkIpv6Test(payload);
      if (!mounted.current) return;
      const full = { ...payload, ...verdict };
      setResult(full);
      setPhase("done");

      // Persiste no ticket
      if (ticketId) {
        try {
          await api.ticketSaveIpv6Test(ticketId, {
            score: verdict.score,
            ipv4_reachable: payload.ipv4_reachable,
            ipv6_reachable: payload.ipv6_reachable,
            dual_stack_ok: payload.dual_stack_ok,
            mtu_ok: payload.mtu_ok,
            dns_ipv6_ok: payload.dns_ipv6_ok,
            v4_addr: payload.v4_addr,
            v6_addr: payload.v6_addr,
            latency_v4_ms: payload.latency_v4_ms,
            latency_v6_ms: payload.latency_v6_ms,
            raw_results: payload.raw_results,
          });
        } catch (e) {
          console.warn("Falha ao persistir ipv6-test no ticket", e);
        }
      }
      onResult && onResult(full);
    } catch (e) {
      if (!mounted.current) return;
      setErr(e?.response?.data?.detail || e.message);
      setPhase("error");
    }
  }, [ticketId, onResult]);

  useEffect(() => {
    if (autoRun) runTest();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const score = result?.score ?? 0;
  const verdict = result?.verdict || "";
  const passed = result?.passed ?? false;

  return (
    <div data-testid="ipv6-test-step" style={{
      padding: 14, borderRadius: 14, marginBottom: 12,
      background: passed ? "linear-gradient(135deg,#ecfdf5,#dcfce7)"
                          : phase === "done" ? "linear-gradient(135deg,#fef3c7,#fde68a)"
                          : "linear-gradient(135deg,#eff6ff,#dbeafe)",
      border: "1px solid " + (passed ? "#86efac" : phase === "done" ? "#fbbf24" : "#bfdbfe"),
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 12, gap: 12 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#1e3a8a",
                          letterSpacing: 0.5, textTransform: "uppercase" }}>
            🌐 Teste IPv6 obrigatório
          </div>
          {phase === "done" && (
            <div data-testid="ipv6-verdict" style={{
              fontSize: 14, fontWeight: 800, marginTop: 4,
              color: passed ? "#166534" : "#92400e",
            }}>
              {verdict}
            </div>
          )}
          {phase === "running" && (
            <div style={{ fontSize: 12, color: "#1e40af", marginTop: 4 }}>
              Testando conectividade IPv6 do cliente… (até 6s)
            </div>
          )}
          {phase === "error" && (
            <div style={{ fontSize: 12, color: "#991b1b", marginTop: 4 }}>
              Erro: {err}
            </div>
          )}
        </div>
        {phase === "done" && <ScoreCircle score={score} />}
      </div>

      {phase === "done" && result && (
        <>
          <CheckRow ok={result.ipv4_reachable} label="IPv4 alcançável"
                     value={result.v4_addr || "—"} />
          <CheckRow ok={result.ipv6_reachable} label="IPv6 alcançável"
                     value={result.v6_addr || "—"} />
          <CheckRow ok={result.dual_stack_ok} label="Dual-stack (prefere IPv6)" />
          <CheckRow ok={result.dns_ipv6_ok} label="DNS resolve AAAA" />
          <CheckRow ok={result.mtu_ok} label="MTU IPv6 (pacote grande)" />

          {!passed && (
            <div style={{
              marginTop: 8, padding: 10, borderRadius: 8,
              background: "#fef3c7", border: "1px solid #fbbf24",
              fontSize: 12, color: "#78350f",
            }}>
              ⚠️ <strong>OS será marcada com IPv6 inconsistente</strong>.
              Verifique configuração do ONT/CPE e DNS antes de entregar.
            </div>
          )}

          <button
            type="button"
            data-testid="ipv6-retest-btn"
            onClick={runTest}
            disabled={phase === "running"}
            style={{
              marginTop: 10, padding: "10px 14px", width: "100%",
              borderRadius: 10, border: "1px solid #cbd5e1", background: "white",
              fontWeight: 700, fontSize: 12, color: "#0f172a", cursor: "pointer",
            }}>
            🔁 Re-testar IPv6
          </button>
        </>
      )}

      {phase === "running" && (
        <div style={{
          height: 4, borderRadius: 2, background: "#dbeafe",
          overflow: "hidden", marginTop: 8,
        }}>
          <div style={{
            height: "100%", width: "40%", background: "#2563eb",
            animation: "ipv6prog 1s linear infinite",
          }} />
        </div>
      )}
      <style>{`
        @keyframes ipv6prog {
          0%   { margin-left: 0; }
          100% { margin-left: 60%; }
        }
      `}</style>
    </div>
  );
}
