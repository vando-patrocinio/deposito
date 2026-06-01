/* RetiradaTemplateCard — edita o template "Comprovante de Devolução de
 * Equipamento" enviado via WhatsApp pro cliente ao finalizar OS de retirada.
 *
 * Variáveis suportadas no template:
 *   {cliente} {endereco} {equipamento} {sn} {data} {tecnico} {empresa}
 *
 * Backend: GET/PUT/POST /api/settings/retirada-template
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

const VARS = [
  { token: "{cliente}",     desc: "Nome do cliente" },
  { token: "{endereco}",    desc: "Endereço completo" },
  { token: "{equipamento}", desc: "Modelo (ex: Modem/ONU)" },
  { token: "{sn}",          desc: "Número de série/MAC" },
  { token: "{data}",        desc: "Data da retirada (DD/MM/AAAA)" },
  { token: "{tecnico}",     desc: "Nome do técnico" },
  { token: "{empresa}",     desc: "Nome da empresa (branding)" },
];

export default function RetiradaTemplateCard() {
  const [tpl, setTpl] = useState("");
  const [defaultTpl, setDefaultTpl] = useState("");
  const [variables, setVariables] = useState([]);
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [showPreview, setShowPreview] = useState(false);

  const previewText = React.useMemo(() => {
    const samples = {
      "{cliente}": "João da Silva",
      "{endereco}": "Rua das Palmeiras, 123 · Centro · Rio de Janeiro",
      "{equipamento}": "Huawei HG8245H5 (ONU GPON)",
      "{sn}": "HWTC12345678",
      "{data}": new Date().toLocaleDateString("pt-BR"),
      "{tecnico}": "Carlos Pereira",
      "{empresa}": "SmartProv ISP",
    };
    return Object.entries(samples).reduce(
      (acc, [k, v]) => acc.split(k).join(v),
      tpl,
    );
  }, [tpl]);

  const reload = useCallback(async () => {
    setLoading(true); setMsg(null);
    try {
      const r = await api._client
        .get("/settings/retirada-template")
        .then((x) => x.data);
      setTpl(r.template);
      setDefaultTpl(r.default_template);
      setVariables(r.variables || []);
      setIsDefault(r.is_default);
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      await api._client.put("/settings/retirada-template", { template: tpl });
      setMsg({ kind: "ok", text: "Template salvo com sucesso." });
      await reload();
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const reset = async () => {
    if (!window.confirm("Voltar ao template padrão? Sua versão editada será perdida.")) return;
    setBusy(true); setMsg(null);
    try {
      await api._client.post("/settings/retirada-template/reset");
      setMsg({ kind: "ok", text: "Template restaurado para o padrão." });
      await reload();
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const insertVar = (token) => {
    setTpl((cur) => cur + (cur.endsWith(" ") || cur.endsWith("\n") ? "" : " ") + token);
  };

  return (
    <div data-testid="retirada-template-card" style={{
      background: "white", border: "1px solid #e5e7eb", borderRadius: 12,
      padding: 20, marginBottom: 16,
      boxShadow: "0 1px 2px rgba(15,23,42,.04)",
    }}>
      <div style={{ display: "flex", alignItems: "center",
                       justifyContent: "space-between", marginBottom: 8 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                          color: "#0f172a" }}>
            📤 Mensagem de Comprovante de Retirada
          </h3>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748b" }}>
            Enviada automaticamente via WhatsApp ao cliente quando o técnico
            finaliza uma OS de retirada.
          </p>
        </div>
        {!isDefault && (
          <span style={{
            padding: "2px 8px", borderRadius: 999, fontSize: 10,
            fontWeight: 700, background: "#dcfce7", color: "#15803d",
            textTransform: "uppercase", letterSpacing: 0.5,
          }}>Personalizado</span>
        )}
      </div>

      {loading ? (
        <div style={{ padding: 20, color: "#94a3b8", fontSize: 13 }}>
          Carregando…
        </div>
      ) : (
        <>
          <div style={{ marginTop: 12 }}>
            <label style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                              textTransform: "uppercase", letterSpacing: 0.5 }}>
              Variáveis disponíveis (clique para inserir)
            </label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6,
                              marginTop: 6 }}>
              {(variables.length ? variables : VARS.map((v) => v.token))
                .map((v) => {
                  const token = typeof v === "string" ? v : v.token;
                  const desc = VARS.find((x) => x.token === token)?.desc;
                  return (
                    <button
                      key={token}
                      type="button"
                      data-testid={`retirada-tpl-var-${token.replace(/[{}]/g, "")}`}
                      onClick={() => insertVar(token)}
                      title={desc || ""}
                      style={{
                        padding: "4px 10px", borderRadius: 6,
                        border: "1px solid #e2e8f0", background: "#f8fafc",
                        fontSize: 11, fontFamily: "monospace",
                        fontWeight: 700, color: "#334155", cursor: "pointer",
                      }}>
                      {token}
                    </button>
                  );
                })}
            </div>
          </div>

          <textarea
            data-testid="retirada-tpl-textarea"
            value={tpl}
            onChange={(e) => setTpl(e.target.value)}
            rows={14}
            style={{
              width: "100%", marginTop: 12, padding: 12,
              border: "1px solid #cbd5e1", borderRadius: 8,
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              fontSize: 12, lineHeight: 1.55, resize: "vertical",
              boxSizing: "border-box", color: "#0f172a",
              background: "#fafafa",
            }}
          />

          {msg && (
            <div data-testid={`retirada-tpl-msg-${msg.kind}`} style={{
              marginTop: 8, padding: "8px 10px", borderRadius: 6,
              fontSize: 12, fontWeight: 600,
              background: msg.kind === "ok" ? "#dcfce7" : "#fee2e2",
              color:      msg.kind === "ok" ? "#166534" : "#991b1b",
            }}>{msg.text}</div>
          )}

          <div style={{ display: "flex", gap: 8, marginTop: 12,
                          justifyContent: "flex-end" }}>
            <button
              type="button"
              data-testid="retirada-tpl-preview"
              onClick={() => setShowPreview(true)}
              disabled={busy}
              style={{
                padding: "8px 14px", borderRadius: 6,
                border: "1px solid #0d9488", background: "white",
                fontSize: 13, fontWeight: 700, color: "#0d9488",
                cursor: "pointer",
              }}>
              👁 Pré-visualizar
            </button>
            <button
              type="button"
              data-testid="retirada-tpl-reset"
              onClick={reset}
              disabled={busy || isDefault}
              style={{
                padding: "8px 14px", borderRadius: 6,
                border: "1px solid #cbd5e1", background: "white",
                fontSize: 13, fontWeight: 700, color: "#475569",
                cursor: busy || isDefault ? "not-allowed" : "pointer",
                opacity: isDefault ? 0.5 : 1,
              }}>
              ↺ Restaurar padrão
            </button>
            <button
              type="button"
              data-testid="retirada-tpl-save"
              onClick={save}
              disabled={busy || tpl === defaultTpl && isDefault}
              style={{
                padding: "8px 18px", borderRadius: 6, border: 0,
                background: "#0f172a", color: "white",
                fontSize: 13, fontWeight: 800,
                cursor: busy ? "wait" : "pointer", opacity: busy ? 0.6 : 1,
              }}>
              {busy ? "Salvando…" : "Salvar"}
            </button>
          </div>
        </>
      )}

      {showPreview && (
        <div
          data-testid="retirada-tpl-preview-overlay"
          onClick={() => setShowPreview(false)}
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            background: "rgba(15,23,42,0.65)",
            display: "grid", placeItems: "center",
            padding: 16,
          }}>
          <div
            onClick={(e) => e.stopPropagation()}
            data-testid="retirada-tpl-preview-modal"
            style={{
              background: "white", borderRadius: 14, padding: 0,
              maxWidth: 380, width: "100%",
              maxHeight: "85vh", overflow: "hidden",
              display: "flex", flexDirection: "column",
              boxShadow: "0 20px 50px rgba(15,23,42,0.4)",
            }}>
            <div style={{
              background: "#075e54", color: "white",
              padding: "12px 16px",
              display: "flex", alignItems: "center", gap: 10,
            }}>
              <div style={{
                width: 36, height: 36, borderRadius: "50%",
                background: "#0d9488", display: "grid", placeItems: "center",
                fontSize: 16, fontWeight: 800,
              }}>SP</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 700 }}>SmartProv ISP</div>
                <div style={{ fontSize: 11, opacity: 0.85 }}>preview · WhatsApp</div>
              </div>
              <button
                onClick={() => setShowPreview(false)}
                data-testid="retirada-tpl-preview-close"
                style={{
                  background: "transparent", border: 0, color: "white",
                  fontSize: 22, cursor: "pointer", lineHeight: 1,
                }}>×</button>
            </div>
            <div style={{
              flex: 1, overflow: "auto", padding: 16,
              background: "#ece5dd",
            }}>
              <div data-testid="retirada-tpl-preview-bubble"
                    style={{
                      background: "#dcf8c6", padding: "10px 12px",
                      borderRadius: 10, fontSize: 13, lineHeight: 1.55,
                      color: "#0f172a", whiteSpace: "pre-wrap",
                      maxWidth: "95%", marginLeft: "auto",
                      boxShadow: "0 1px 1px rgba(0,0,0,0.1)",
                      fontFamily: "system-ui, -apple-system, sans-serif",
                    }}>
                {previewText}
                <div style={{ fontSize: 9, color: "#64748b",
                                textAlign: "right", marginTop: 4 }}>
                  {new Date().toLocaleTimeString("pt-BR", {
                    hour: "2-digit", minute: "2-digit" })} ✓✓
                </div>
              </div>
            </div>
            <div style={{
              padding: "10px 16px", background: "#f8fafc",
              borderTop: "1px solid #e2e8f0", fontSize: 11,
              color: "#64748b", textAlign: "center",
            }}>
              Dados de exemplo · cliente real receberá com os dados da OS
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
