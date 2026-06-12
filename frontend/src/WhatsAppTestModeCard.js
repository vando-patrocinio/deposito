/* WhatsAppTestModeCard — controle UI do modo teste do WhatsApp.
 *
 * Quando LIGADO: todas as mensagens outbound são REDIRECIONADAS para o
 * número de teste configurado. Clientes reais NÃO recebem nada.
 *
 * Backend: GET/PUT /api/settings/wa-test-mode
 *
 * Failsafe: default `enabled=true`, `test_phone=5521998176526`.
 */
import React, { useCallback, useEffect, useState } from "react";
import { client } from "@/api";
import { Card } from "@/ui";

function formatPhone(digits) {
  const d = String(digits || "").replace(/\D/g, "");
  if (d.length === 13 && d.startsWith("55")) {
    return `(${d.slice(2, 4)}) ${d.slice(4, 9)}-${d.slice(9)}`;
  }
  if (d.length === 12 && d.startsWith("55")) {
    return `(${d.slice(2, 4)}) ${d.slice(4, 8)}-${d.slice(8)}`;
  }
  if (d.length === 11) {
    return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  }
  if (d.length === 10) {
    return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  }
  return d;
}

export default function WhatsAppTestModeCard() {
  const [state, setState] = useState(null);
  const [phoneInput, setPhoneInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await client.get("/settings/wa-test-mode");
      setState(r.data);
      setPhoneInput(formatPhone(r.data.test_phone));
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async (patch) => {
    setSaving(true); setMsg(""); setErr("");
    try {
      const r = await client.put("/settings/wa-test-mode", patch);
      setState((cur) => ({ ...cur, ...r.data }));
      setPhoneInput(formatPhone(r.data.test_phone));
      setMsg("Salvo.");
      setTimeout(() => setMsg(""), 2500);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setSaving(false);
    }
  };

  const toggle = () => {
    if (!state) return;
    const willTurnOff = state.enabled;
    if (willTurnOff) {
      const ok = window.confirm(
        "⚠️ ATENÇÃO — Desligar o Modo Teste faz com que mensagens reais "
        + "sejam enviadas a clientes cadastrados. Deseja continuar?",
      );
      if (!ok) return;
    }
    save({ enabled: !state.enabled });
  };

  const savePhone = () => {
    const digits = phoneInput.replace(/\D/g, "");
    if (digits.length < 10) {
      setErr("Telefone inválido. Use DDD + número.");
      return;
    }
    save({ test_phone: digits });
  };

  if (!state) {
    return (
      <Card title="Modo Teste WhatsApp" style={{ gridColumn: "1 / -1" }}
            data-testid="wa-test-mode-card">
        <div style={{ color: "#64748b" }}>Carregando…</div>
      </Card>
    );
  }

  const on = !!state.enabled;
  const bg = on ? "#dcfce7" : "#fee2e2";
  const border = on ? "#16a34a" : "#dc2626";
  const text = on ? "#166534" : "#991b1b";
  const statusLabel = on ? "MODO TESTE ATIVO" : "MODO TESTE DESLIGADO";
  const subLabel = on
    ? "Todas as mensagens vão APENAS para o número de teste. Clientes reais NÃO recebem nada."
    : "⚠️ Mensagens reais sendo enviadas aos clientes.";

  return (
    <Card title="🛡️ Modo Teste WhatsApp"
          style={{ gridColumn: "1 / -1" }}
          data-testid="wa-test-mode-card">
      <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 14px" }}>
        Quando ligado, todas as mensagens enviadas pelo sistema (Isabella,
        Pâmela, disparos, boletos, follow-ups) são redirecionadas para o
        número de teste abaixo. Use para validar fluxos sem mandar mensagens
        indevidas a clientes cadastrados.
      </p>

      <div
        data-testid="wa-test-mode-status"
        style={{
          padding: "14px 18px",
          borderRadius: 10,
          border: `2px solid ${border}`,
          background: bg,
          marginBottom: 16,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontSize: 18, fontWeight: 800, color: text }}>
            {statusLabel}
          </div>
          <div style={{ fontSize: 13, color: text, marginTop: 4 }}>
            {subLabel}
          </div>
        </div>
        <button
          type="button"
          data-testid="wa-test-mode-toggle"
          onClick={toggle}
          disabled={saving}
          style={{
            padding: "10px 18px",
            border: 0,
            borderRadius: 8,
            background: on ? "#dc2626" : "#16a34a",
            color: "#fff",
            fontWeight: 700,
            cursor: saving ? "wait" : "pointer",
            minWidth: 160,
          }}
        >
          {saving
            ? "Salvando…"
            : on
              ? "Desligar Modo Teste"
              : "Ligar Modo Teste"}
        </button>
      </div>

      <div style={{ display: "grid", gap: 6 }}>
        <label style={{ fontSize: 12, fontWeight: 700, color: "#334155" }}>
          Número de teste (todos os outbounds vão aqui)
        </label>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            type="tel"
            data-testid="wa-test-mode-phone-input"
            value={phoneInput}
            onChange={(e) => setPhoneInput(e.target.value)}
            placeholder="(21) 99817-6526"
            style={{
              flex: 1,
              minWidth: 200,
              padding: "10px 12px",
              border: "1px solid #cbd5e1",
              borderRadius: 8,
              fontSize: 15,
              fontFamily: "monospace",
            }}
          />
          <button
            type="button"
            data-testid="wa-test-mode-phone-save"
            onClick={savePhone}
            disabled={saving}
            style={{
              padding: "10px 18px",
              border: 0,
              borderRadius: 8,
              background: "#0f172a",
              color: "#fff",
              fontWeight: 700,
              cursor: saving ? "wait" : "pointer",
            }}
          >
            Salvar número
          </button>
        </div>
        <div style={{ fontSize: 12, color: "#64748b" }}>
          Atual: <span style={{ fontWeight: 700, fontFamily: "monospace" }}
                       data-testid="wa-test-mode-current-phone">
            {state.test_phone_display || state.test_phone}
          </span>
        </div>
      </div>

      {msg && (
        <div data-testid="wa-test-mode-msg"
             style={{ marginTop: 12, color: "#166534", fontWeight: 700 }}>
          ✓ {msg}
        </div>
      )}
      {err && (
        <div data-testid="wa-test-mode-err"
             style={{ marginTop: 12, color: "#be123c", fontWeight: 700 }}>
          {err}
        </div>
      )}
    </Card>
  );
}
