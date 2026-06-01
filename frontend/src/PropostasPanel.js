/* PropostasPanel — Aba "Projetos > Propostas"
   IA Claude 4.6 gera copy variável; identidade visual LIGO (roxo+laranja) fixa.
   Layout: formulário à esquerda + card de preview + lista de propostas salvas. */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

const PURPLE_DARK = "#4c1d95";
const PURPLE = "#5b21b6";
const PURPLE_LIGHT = "#ede9fe";
const ORANGE = "#f59e0b";

const cardBox = {
  background: "white", border: "1px solid #e2e8f0",
  borderRadius: 14, padding: 18, boxShadow: "0 2px 8px rgba(15,23,42,.04)",
};
const inputStyle = {
  width: "100%", padding: "10px 12px", borderRadius: 10,
  border: "1px solid #cbd5e1", fontSize: 13, color: "#0f172a",
  outline: "none", background: "white",
};
const labelStyle = {
  display: "block", fontSize: 11, color: "#64748b",
  fontWeight: 700, marginBottom: 5, letterSpacing: 0.3,
  textTransform: "uppercase",
};
const btnPrimary = {
  padding: "12px 18px", borderRadius: 10, border: 0,
  background: `linear-gradient(135deg,${PURPLE_DARK},${PURPLE})`,
  color: "white", fontWeight: 700, fontSize: 13, cursor: "pointer",
  boxShadow: `0 4px 14px ${PURPLE}40`,
};
const btnSec = {
  padding: "10px 14px", borderRadius: 10, border: "1px solid #cbd5e1",
  background: "white", color: "#0f172a", fontWeight: 600,
  fontSize: 12, cursor: "pointer",
};
const btnOrange = {
  ...btnPrimary,
  background: `linear-gradient(135deg,${ORANGE},#ea580c)`,
  boxShadow: `0 4px 14px ${ORANGE}55`,
};

const fmtMoney = (n) =>
  Number(n || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export default function PropostasPanel({ currentUser }) {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null); // proposta atual no card

  // Formulário
  const empty = {
    client_name: "",
    address: "",
    plan_description: "Link Dedicado 1 Giga",
    monthly_value: 1950,
    fidelity_months: 26,
    exemption_months_count: 2,
    exemption_pattern: "alternados",
    differential_text: "",
    additional_benefit_text: "",
    run_ai: true,
    ai_tone: "profissional",
  };
  const [form, setForm] = useState(empty);
  const setF = (k, v) => setForm((s) => ({ ...s, [k]: v }));

  const reload = useCallback(async () => {
    try {
      const r = await api.propostasList({ q: search || undefined });
      setItems(r.items || []);
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    }
  }, [search]);

  useEffect(() => { reload(); }, [reload]);

  const onCreate = async () => {
    if (!form.client_name.trim() || !form.address.trim()) {
      setMsg({ type: "err", text: "Preencha nome e endereço" });
      return;
    }
    setBusy(true);
    setMsg({ type: "info", text: form.run_ai ? "🤖 Claude 4.6 está gerando a copy…" : "Salvando…" });
    try {
      const r = await api.propostasCreate({
        ...form,
        monthly_value: Number(form.monthly_value),
        fidelity_months: Number(form.fidelity_months),
        exemption_months_count: Number(form.exemption_months_count),
      });
      setSelected(r);
      setMsg({ type: "ok", text: "✓ Proposta criada com sucesso" });
      await reload();
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  const onRegenerate = async () => {
    if (!selected?.id) return;
    setBusy(true);
    setMsg({ type: "info", text: "🤖 Re-gerando copy com Claude 4.6…" });
    try {
      const r = await api.propostasRegenerate(selected.id, { ai_tone: form.ai_tone });
      setSelected(r);
      setMsg({ type: "ok", text: "✓ Copy regenerada" });
      await reload();
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  const onDownloadPdf = async (id) => {
    try {
      const blob = await api.propostaPdf(id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `proposta_${id}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setMsg({ type: "err", text: "Falha no PDF: " + e.message });
    }
  };

  const onDelete = async (id) => {
    if (!window.confirm("Excluir proposta?")) return;
    try {
      await api.propostaDelete(id);
      if (selected?.id === id) setSelected(null);
      await reload();
    } catch (e) {
      setMsg({ type: "err", text: e.message });
    }
  };

  return (
    <div data-testid="propostas-panel" style={{ padding: 18 }}>
      <div style={{ marginBottom: 16, display: "flex", justifyContent: "space-between",
                      alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "#0f172a",
                         letterSpacing: -0.4 }}>
            Projetos · Propostas Comerciais
          </h1>
          <div style={{ color: "#64748b", fontSize: 12, marginTop: 4 }}>
            IA Claude 4.6 formata o texto · identidade visual fixa · exporta em PDF
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{
            background: PURPLE_LIGHT, color: PURPLE_DARK, padding: "5px 10px",
            borderRadius: 999, fontSize: 11, fontWeight: 700,
          }}>{items.length} salva(s)</span>
        </div>
      </div>

      {msg && (
        <div data-testid="propostas-msg" style={{
          marginBottom: 12, padding: "10px 14px", borderRadius: 10, fontSize: 12,
          background: msg.type === "err" ? "#fee2e2" : msg.type === "ok" ? "#dcfce7" : "#fef3c7",
          color: msg.type === "err" ? "#991b1b" : msg.type === "ok" ? "#166534" : "#78350f",
          border: "1px solid " + (msg.type === "err" ? "#fecaca" : msg.type === "ok" ? "#bbf7d0" : "#fde68a"),
        }}>
          {msg.text}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 16,
                      alignItems: "start" }}>
        {/* ============ FORMULÁRIO ============ */}
        <div data-testid="propostas-form" style={cardBox}>
          <div style={{ fontSize: 13, fontWeight: 800, color: PURPLE_DARK,
                          marginBottom: 12, letterSpacing: 0.3, textTransform: "uppercase" }}>
            📝 Dados da Proposta
          </div>

          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Nome do cliente</label>
            <input data-testid="propostas-client-name"
                     style={inputStyle} value={form.client_name}
                     onChange={(e) => setF("client_name", e.target.value)}
                     placeholder="Ex.: Assembleia de Deus Vitória em Cristo" />
          </div>
          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Endereço completo</label>
            <input data-testid="propostas-address"
                     style={inputStyle} value={form.address}
                     onChange={(e) => setF("address", e.target.value)}
                     placeholder="Rua, número – Bairro – Cidade/UF" />
          </div>
          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Plano contratado</label>
            <input data-testid="propostas-plan"
                     style={inputStyle} value={form.plan_description}
                     onChange={(e) => setF("plan_description", e.target.value)}
                     placeholder="Link Dedicado 1 Giga + Instalação" />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
            <div>
              <label style={labelStyle}>Valor mensal (R$)</label>
              <input data-testid="propostas-value"
                       type="number" min="0" step="0.01"
                       style={inputStyle} value={form.monthly_value}
                       onChange={(e) => setF("monthly_value", e.target.value)} />
            </div>
            <div>
              <label style={labelStyle}>Fidelidade (meses)</label>
              <input data-testid="propostas-fidelity"
                       type="number" min="1" max="60"
                       style={inputStyle} value={form.fidelity_months}
                       onChange={(e) => setF("fidelity_months", e.target.value)} />
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
            <div>
              <label style={labelStyle}>Meses de isenção</label>
              <input data-testid="propostas-exemption-count"
                       type="number" min="0" max="12"
                       style={inputStyle} value={form.exemption_months_count}
                       onChange={(e) => setF("exemption_months_count", e.target.value)} />
            </div>
            <div>
              <label style={labelStyle}>Padrão</label>
              <select data-testid="propostas-exemption-pattern"
                        style={inputStyle} value={form.exemption_pattern}
                        onChange={(e) => setF("exemption_pattern", e.target.value)}>
                <option value="alternados">Alternados</option>
                <option value="primeiros">Primeiros meses</option>
                <option value="ultimos">Últimos meses</option>
              </select>
            </div>
          </div>

          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Tom da IA</label>
            <select data-testid="propostas-tone"
                      style={inputStyle} value={form.ai_tone}
                      onChange={(e) => setF("ai_tone", e.target.value)}>
              <option value="profissional">Profissional</option>
              <option value="caloroso">Caloroso</option>
              <option value="direto">Direto</option>
            </select>
          </div>

          <div style={{ marginBottom: 12, padding: 10, background: PURPLE_LIGHT,
                          borderRadius: 10, fontSize: 11, color: PURPLE_DARK }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8,
                              cursor: "pointer", fontWeight: 600 }}>
              <input data-testid="propostas-use-ai"
                       type="checkbox" checked={form.run_ai}
                       onChange={(e) => setF("run_ai", e.target.checked)} />
              🤖 Usar Claude 4.6 para variar o informativo
            </label>
          </div>

          <button data-testid="propostas-create-btn" onClick={onCreate} disabled={busy}
                    style={{ ...btnPrimary, width: "100%", opacity: busy ? 0.6 : 1 }}>
            {busy ? "Processando…" : "Gerar proposta"}
          </button>
          <button data-testid="propostas-reset-btn" onClick={() => { setForm(empty); setSelected(null); }}
                    disabled={busy}
                    style={{ ...btnSec, width: "100%", marginTop: 8 }}>
            Limpar formulário
          </button>
        </div>

        {/* ============ PREVIEW CARD (LIGO) ============ */}
        <div data-testid="propostas-preview" style={{
          ...cardBox,
          background: `linear-gradient(180deg, white 0%, ${PURPLE_LIGHT}55 100%)`,
          border: `2px solid ${PURPLE}33`, padding: 20, position: "relative",
          overflow: "hidden",
        }}>
          <div style={{
            position: "absolute", top: 0, right: 0, width: 70, height: 70,
            background: `linear-gradient(135deg, transparent 50%, ${ORANGE} 50%)`,
          }} />
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
            <div style={{
              fontSize: 30, fontWeight: 900, color: PURPLE_DARK,
              letterSpacing: -1, fontFamily: "system-ui, sans-serif",
            }}>LIGO</div>
            <div style={{ width: 30, height: 2, background: ORANGE,
                            borderRadius: 2, transform: "translateY(8px)" }} />
          </div>
          <div style={{
            fontSize: 18, fontWeight: 900, color: PURPLE_DARK,
            letterSpacing: -0.5, marginBottom: 4,
          }}>
            {selected?.ai_copy?.title || "PROPOSTA COMERCIAL"}
          </div>
          <div style={{ borderBottom: `1px solid ${PURPLE}`, marginBottom: 12 }} />

          <div style={{ fontSize: 11, color: "#0f172a", marginBottom: 10 }}>
            {selected?.ai_copy?.header_intro || "Preencha os dados ao lado e clique em Gerar Proposta."}
          </div>

          {selected && (
            <>
              <div style={{
                background: PURPLE_LIGHT, padding: 12, borderRadius: 10,
                marginBottom: 12, fontSize: 11,
              }}>
                <div style={{ color: PURPLE_DARK, fontWeight: 800 }}>
                  Cliente: <span style={{ color: "#0f172a", fontWeight: 600 }}>{selected.client_name}</span>
                </div>
                <div style={{ color: PURPLE_DARK, fontWeight: 800, marginTop: 4 }}>
                  Endereço: <span style={{ color: "#0f172a", fontWeight: 600 }}>{selected.address}</span>
                </div>
              </div>

              <div style={{ fontSize: 11, fontWeight: 800, color: PURPLE_DARK,
                              letterSpacing: 0.5, marginBottom: 4 }}>SERVIÇO CONTRATADO</div>
              <ul style={{ paddingLeft: 18, margin: "0 0 10px 0", fontSize: 11, color: "#0f172a" }}>
                {(selected.ai_copy?.service_bullets || []).map((b, i) => (
                  <li key={i} style={{ marginBottom: 3 }}>{b}</li>
                ))}
              </ul>

              <div style={{ fontSize: 11, fontWeight: 800, color: PURPLE_DARK,
                              letterSpacing: 0.5, marginBottom: 4 }}>INVESTIMENTO</div>
              <div style={{ fontSize: 11, marginBottom: 10 }}>
                Valor mensal:{" "}
                <strong style={{ color: PURPLE_DARK, fontSize: 13 }}>
                  {fmtMoney(selected.monthly_value)}
                </strong>
              </div>

              <div style={{ fontSize: 11, fontWeight: 800, color: PURPLE_DARK,
                              letterSpacing: 0.5, marginBottom: 4 }}>CONDIÇÃO ESPECIAL</div>
              <ul style={{ paddingLeft: 18, margin: "0 0 8px 0", fontSize: 11, color: "#0f172a" }}>
                <li>Contrato com fidelidade de <strong>{selected.fidelity_months} meses</strong></li>
                {selected.exemption_months_count > 0 && (
                  <li>Benefício de {selected.exemption_months_count} mese(s) de isenção</li>
                )}
              </ul>
              {selected.exemption_months_count > 0 && (
                <div style={{ display: "grid",
                                gridTemplateColumns: `repeat(${selected.payment_schedule.length}, 1fr)`,
                                gap: 0, marginBottom: 10, border: `1px solid ${PURPLE}` }}>
                  {selected.payment_schedule.map((m, i) => (
                    <div key={i} style={{
                      padding: 4, textAlign: "center", fontSize: 10,
                      borderRight: i < selected.payment_schedule.length - 1 ? `1px solid ${PURPLE}` : 0,
                    }}>
                      <div style={{ color: PURPLE_DARK, fontWeight: 700 }}>{m.label}</div>
                      <div style={{ borderTop: `1px solid ${PURPLE}`, marginTop: 2, paddingTop: 3,
                                      color: m.type === "Isenção" ? PURPLE_DARK : "#0f172a",
                                      fontWeight: m.type === "Isenção" ? 700 : 500 }}>
                        {m.type}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div style={{ fontSize: 11, fontWeight: 800, color: PURPLE_DARK,
                              letterSpacing: 0.5, marginBottom: 4 }}>DIFERENCIAL DO SERVIÇO</div>
              <div style={{ fontSize: 11, color: "#0f172a", marginBottom: 10, lineHeight: 1.4 }}>
                {selected.ai_copy?.differential || "—"}
              </div>

              <div style={{ fontSize: 11, fontWeight: 800, color: PURPLE_DARK,
                              letterSpacing: 0.5, marginBottom: 4 }}>BENEFÍCIO ADICIONAL</div>
              <div style={{ fontSize: 11, color: "#0f172a", marginBottom: 12, lineHeight: 1.4 }}>
                {selected.ai_copy?.additional_benefit || "—"}
              </div>

              <div style={{ borderTop: `1px solid ${PURPLE}`, paddingTop: 8,
                              fontSize: 10, color: "#475569", marginBottom: 12 }}>
                {selected.ai_copy?.closing}
                <div style={{ marginTop: 6 }}>
                  <span style={{ color: "#64748b" }}>Atenciosamente,</span>{" "}
                  <strong style={{ color: PURPLE_DARK }}>Ligo.</strong>
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button data-testid="propostas-pdf-btn"
                          onClick={() => onDownloadPdf(selected.id)}
                          style={btnOrange}>
                  📄 Baixar PDF
                </button>
                <button data-testid="propostas-regenerate-btn"
                          onClick={onRegenerate} disabled={busy}
                          style={btnSec}>
                  🤖 Regenerar texto (IA)
                </button>
              </div>
              <div style={{ marginTop: 10, fontSize: 10, color: "#64748b" }}>
                Criada por <strong>{selected.created_by_name}</strong>{" "}
                em {selected.created_at?.slice(0, 16).replace("T", " ")}
              </div>
            </>
          )}
        </div>
      </div>

      {/* ============ LISTA DE PROPOSTAS SALVAS ============ */}
      <div data-testid="propostas-list-wrap" style={{ ...cardBox, marginTop: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, gap: 12, flexWrap: "wrap" }}>
          <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>
            Propostas salvas ({items.length})
          </div>
          <input data-testid="propostas-search"
                   style={{ ...inputStyle, maxWidth: 260 }}
                   placeholder="Buscar por cliente ou endereço…"
                   value={search}
                   onChange={(e) => setSearch(e.target.value)} />
        </div>
        {items.length === 0 ? (
          <div style={{ padding: 30, textAlign: "center", color: "#94a3b8", fontSize: 13 }}>
            Nenhuma proposta criada ainda. Use o formulário acima para gerar a primeira.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "#f8fafc", color: "#64748b", textAlign: "left" }}>
                  <th style={{ padding: "10px 12px" }}>Cliente</th>
                  <th style={{ padding: "10px 12px" }}>Plano</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Valor</th>
                  <th style={{ padding: "10px 12px" }}>Criada por</th>
                  <th style={{ padding: "10px 12px" }}>Data</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>Ações</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id} data-testid={`propostas-row-${it.id}`}
                       style={{ borderTop: "1px solid #e2e8f0",
                                 background: selected?.id === it.id ? PURPLE_LIGHT : "white",
                                 cursor: "pointer" }}
                       onClick={() => setSelected(it)}>
                    <td style={{ padding: "10px 12px", fontWeight: 600, color: "#0f172a" }}>{it.client_name}</td>
                    <td style={{ padding: "10px 12px", color: "#475569" }}>{it.plan_description}</td>
                    <td style={{ padding: "10px 12px", textAlign: "right", color: PURPLE_DARK, fontWeight: 700 }}>
                      {fmtMoney(it.monthly_value)}
                    </td>
                    <td style={{ padding: "10px 12px", color: "#475569" }}>{it.created_by_name}</td>
                    <td style={{ padding: "10px 12px", color: "#64748b", fontSize: 11 }}>
                      {it.created_at?.slice(0, 16).replace("T", " ")}
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                      <button data-testid={`propostas-row-pdf-${it.id}`}
                                onClick={() => onDownloadPdf(it.id)}
                                style={{ ...btnSec, padding: "6px 10px", marginRight: 4 }}>
                        📄 PDF
                      </button>
                      <button data-testid={`propostas-row-del-${it.id}`}
                                onClick={() => onDelete(it.id)}
                                style={{ ...btnSec, padding: "6px 10px", color: "#991b1b", borderColor: "#fecaca" }}>
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
