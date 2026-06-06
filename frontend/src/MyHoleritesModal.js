import React, { useCallback, useEffect, useState } from "react";
import { Button } from "@/ui";
import BottomSheet from "@/BottomSheet";
import { api } from "@/api";

const MONTHS_FULL = [
  "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
];
const MONTHS_SHORT = [
  "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
  "Jul", "Ago", "Set", "Out", "Nov", "Dez",
];

function fmtBRL(v) {
  const n = Number(v || 0);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

/* localStorage helper: marca quando o colaborador baixou o original */
const downloadedKey = (cid, docId) => `holerite_dl_${cid}_${docId}`;
function markDownloaded(cid, docId) {
  try { localStorage.setItem(downloadedKey(cid, docId), "1"); } catch {}
}
function wasDownloaded(cid, docId) {
  try { return !!localStorage.getItem(downloadedKey(cid, docId)); } catch { return false; }
}

export default function MyHoleritesModal({ collaboratorId, onClose }) {
  const [data, setData] = useState({ collaborator: {}, items: [], count: 0 });
  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.publicHoleritesList(collaboratorId);
      setData(r);
    } finally { setLoading(false); }
  }, [collaboratorId]);

  useEffect(() => { reload(); }, [reload]);

  const items = data.items || [];

  return (
    <BottomSheet open onClose={onClose} testid="my-holerites-modal">
      <div style={{ padding: "8px 18px 0" }}>
        {/* Header sóbrio */}
        <div style={{ marginBottom: 18, display: "flex",
          justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800,
              color: "#0f172a", letterSpacing: "-.02em" }}>
              Holerites
            </h2>
            <div style={{ fontSize: 12.5, color: "#64748b", marginTop: 3 }}>
              {data.count} {data.count === 1 ? "documento disponível" : "documentos disponíveis"}
            </div>
          </div>
          <button onClick={onClose} data-testid="my-holerites-close"
                  aria-label="Fechar"
                  style={{
                    width: 32, height: 32, borderRadius: "50%",
                    border: "1px solid #e2e8f0", background: "white",
                    cursor: "pointer", fontSize: 16, color: "#64748b",
                    display: "grid", placeItems: "center", padding: 0,
                  }}>×</button>
        </div>

        {/* Lista */}
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "#94a3b8", fontSize: 13 }}>
            Carregando…
          </div>
        ) : items.length === 0 ? (
          <div style={{
            padding: 50, textAlign: "center",
            background: "white", borderRadius: 14,
            border: "1px solid #f1f5f9",
          }}>
            <div style={{ fontSize: 36, marginBottom: 8, opacity: .35 }}></div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
              Nenhum holerite disponível
            </div>
            <div style={{ fontSize: 12, marginTop: 4, color: "#64748b" }}>
              Você verá seu holerite aqui no mês do pagamento.
            </div>
          </div>
        ) : (
          <div data-testid="my-holerites-list" style={{ display: "grid", gap: 10 }}>
            {items.map((h) => (
              <HoleriteCard key={h.id} h={h}
                              collaboratorId={collaboratorId}
                              onSign={() => setSigning(h)} />
            ))}
          </div>
        )}

        {/* Footer LGPD compacto */}
        <div style={{
          marginTop: 22, padding: "10px 12px",
          fontSize: 10.5, lineHeight: 1.5, color: "#94a3b8",
          textAlign: "center",
        }}>
          Documentos protegidos pela LGPD. Você pode assinar digitalmente
          com gov.br (Lei 14.063/2020).
        </div>
      </div>

      {signing && (
        <SignWithGovBrModal
          doc={signing}
          collaboratorId={collaboratorId}
          onClose={() => setSigning(null)}
          onSuccess={() => { setSigning(null); reload(); }}
        />
      )}
    </BottomSheet>
  );
}

/* =============================================================
   HoleriteCard — minimalista com botão único dinâmico
============================================================= */
function HoleriteCard({ h, collaboratorId, onSign }) {
  const signed = !!h.signed_at;
  const [downloaded, setDownloaded] = useState(wasDownloaded(collaboratorId, h.id));

  function downloadOriginal() {
    window.open(api.publicHoleriteFileUrl(collaboratorId, h.id), "_blank");
    markDownloaded(collaboratorId, h.id);
    setDownloaded(true);
  }
  function downloadSigned() {
    window.open(api.publicSignedHoleriteFileUrl(collaboratorId, h.id), "_blank");
  }

  // Determina o botão principal
  let action;
  if (signed) {
    action = {
      label: "Baixar assinado",
      icon: "✓",
      onClick: downloadSigned,
      testid: `view-signed-${h.id}`,
      bg: "#0f172a",
      color: "white",
    };
  } else if (downloaded) {
    action = {
      label: "Enviar assinado",
      icon: "↑",
      onClick: onSign,
      testid: `sign-holerite-${h.id}`,
      bg: "#1351b4",
      color: "white",
    };
  } else {
    action = {
      label: "Baixar",
      icon: "↓",
      onClick: downloadOriginal,
      testid: `view-holerite-${h.id}`,
      bg: "#0f172a",
      color: "white",
    };
  }

  return (
    <div data-testid={`my-holerite-${h.id}`} style={{
      padding: 14,
      background: "white",
      borderRadius: 14,
      border: "1px solid #f1f5f9",
      transition: "border .15s",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "flex-start", marginBottom: 10 }}>
        <div>
          <div style={{
            fontSize: 11, fontWeight: 700, color: "#94a3b8",
            textTransform: "uppercase", letterSpacing: ".06em",
          }}>
            {MONTHS_FULL[h.competence_month - 1]} {h.competence_year}
          </div>
          <div style={{
            fontSize: 22, fontWeight: 800, color: "#0f172a",
            marginTop: 2, letterSpacing: "-.015em",
          }}>
            {fmtBRL(h.net)}
          </div>
        </div>
        {signed && (
          <div data-testid={`signed-badge-${h.id}`} style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "3px 8px", borderRadius: 999,
            background: "#f0fdf4", color: "#15803d",
            border: "1px solid #bbf7d0",
            fontSize: 10, fontWeight: 700,
          }}>
            <span style={{ fontSize: 9 }}>●</span>
            Assinado
          </div>
        )}
      </div>

      {/* Detalhes secundários */}
      <div style={{ display: "flex", gap: 14, marginBottom: 12,
        fontSize: 11, color: "#64748b" }}>
        <div>
          <div style={{ fontSize: 10, color: "#94a3b8", marginBottom: 1 }}>Bruto</div>
          {fmtBRL(h.gross)}
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#94a3b8", marginBottom: 1 }}>Descontos</div>
          {fmtBRL(h.deductions_total || 0)}
        </div>
      </div>

      {/* Botão único dinâmico */}
      <button
        onClick={action.onClick}
        data-testid={action.testid}
        style={{
          width: "100%", padding: "12px 14px", borderRadius: 10,
          border: "none", cursor: "pointer",
          background: action.bg, color: action.color,
          fontSize: 13, fontWeight: 700,
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          gap: 8, transition: "transform .1s, opacity .15s",
        }}
        onMouseDown={(e) => e.currentTarget.style.transform = "scale(.985)"}
        onMouseUp={(e) => e.currentTarget.style.transform = "scale(1)"}
        onMouseLeave={(e) => e.currentTarget.style.transform = "scale(1)"}
      >
        <span style={{ fontSize: 14, fontWeight: 900 }}>{action.icon}</span>
        {action.label}
      </button>

      {/* Hint sutil para próximo passo */}
      {!signed && downloaded && (
        <div style={{
          marginTop: 8, fontSize: 10.5, color: "#94a3b8", textAlign: "center",
        }}>
          Já baixou? Assine no gov.br e envie aqui.
        </div>
      )}
      {signed && h.signed_at && (
        <div style={{
          marginTop: 8, fontSize: 10.5, color: "#94a3b8", textAlign: "center",
        }}>
          Assinado em {new Date(h.signed_at).toLocaleDateString("pt-BR")}
          {h.signature_valid && " · digital validada"}
        </div>
      )}
    </div>
  );
}

/* =============================================================
   SignWithGovBrModal — fluxo de 3 passos (mantido + clean)
============================================================= */
function SignWithGovBrModal({ doc, collaboratorId, onClose, onSuccess }) {
  const [step, setStep] = useState(1);
  const [file, setFile] = useState(null);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);

  async function handleUpload() {
    if (!file) { setError("Selecione o PDF assinado."); return; }
    setError(""); setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const url = `/holerites/public/${collaboratorId}/${doc.id}/sign-upload`;
      const { data } = await api._client.post(url, fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 60000,
      });
      setResult(data);
      setStep(4);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "Erro ao enviar.");
    } finally { setUploading(false); }
  }

  return (
    <BottomSheet open onClose={onClose} testid="sign-govbr-modal">
      <div style={{ padding: "8px 18px 0" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
          alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: "#1351b4",
              textTransform: "uppercase", letterSpacing: ".06em" }}>
              Assinatura gov.br
            </div>
            <h3 style={{ margin: "2px 0 0", fontSize: 17, fontWeight: 800,
              color: "#0f172a", letterSpacing: "-.015em" }}>
              {MONTHS_SHORT[doc.competence_month - 1]}/{doc.competence_year} ·
              {" "}{fmtBRL(doc.net)}
            </h3>
          </div>
          <button onClick={onClose} style={{
            width: 30, height: 30, borderRadius: "50%",
            background: "#f1f5f9", border: "none", color: "#64748b",
            fontSize: 16, cursor: "pointer",
          }}>×</button>
        </div>

        {/* Step indicator minimalista */}
        <div style={{ display: "flex", gap: 4, marginBottom: 18 }}>
          {[1, 2, 3].map((n) => (
            <div key={n} style={{
              flex: 1, height: 3, borderRadius: 4,
              background: step >= n ? "#1351b4" : "#e2e8f0",
              transition: "background .25s",
            }} />
          ))}
        </div>
      </div>

      <div style={{ padding: "0 18px" }}>
          {step === 1 && (
            <div data-testid="sign-step-1">
              <h4 style={{ margin: 0, fontSize: 15, fontWeight: 800, color: "#0f172a" }}>
                1. Baixe o holerite
              </h4>
              <p style={{ fontSize: 12.5, color: "#64748b", lineHeight: 1.5, margin: "6px 0 14px" }}>
                Salve o PDF no seu dispositivo. Você vai usar no próximo passo.
              </p>
              <Button
                onClick={() => {
                  window.open(api.publicHoleriteFileUrl(collaboratorId, doc.id), "_blank");
                  markDownloaded(collaboratorId, doc.id);
                  setStep(2);
                }}
                data-testid="sign-download-btn"
                style={{
                  width: "100%", padding: 12, fontSize: 13, fontWeight: 700,
                  background: "#0f172a", borderColor: "#0f172a", color: "white",
                }}
              >
                ↓  Baixar PDF
              </Button>
              <button onClick={() => setStep(2)} style={{
                width: "100%", marginTop: 6, padding: 6, fontSize: 11,
                background: "transparent", border: "none", color: "#94a3b8",
                cursor: "pointer",
              }}>
                Já tenho · próximo
              </button>
            </div>
          )}

          {step === 2 && (
            <div data-testid="sign-step-2">
              <h4 style={{ margin: 0, fontSize: 15, fontWeight: 800, color: "#0f172a" }}>
                2. Assine no gov.br
              </h4>
              <ol style={{
                fontSize: 12.5, color: "#475569", lineHeight: 1.7,
                paddingLeft: 18, margin: "8px 0 12px",
              }}>
                <li>Abra o assinador gov.br</li>
                <li>Entre com sua conta gov.br</li>
                <li>Suba o PDF que você baixou</li>
                <li>Assine e baixe o PDF assinado</li>
              </ol>
              <a href="https://assinador.iti.br/" target="_blank" rel="noopener noreferrer"
                  data-testid="open-govbr-signer"
                  style={{
                    display: "block", textAlign: "center",
                    padding: 12, borderRadius: 10, fontSize: 13, fontWeight: 700,
                    background: "#1351b4", color: "white", textDecoration: "none",
                  }}>
                Abrir assinador gov.br  ↗
              </a>
              <div style={{
                marginTop: 10, padding: 9, borderRadius: 8,
                background: "#f8fafc", color: "#475569",
                fontSize: 10.5, lineHeight: 1.45, textAlign: "center",
              }}>
                Assinatura tem valor legal pela Lei 14.063/2020 (STJ 2026).
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
                <button onClick={() => setStep(1)} style={{
                  flex: 1, padding: 9, fontSize: 12, fontWeight: 600,
                  background: "white", border: "1px solid #e2e8f0",
                  borderRadius: 8, color: "#64748b", cursor: "pointer",
                }}>
                  Voltar
                </button>
                <button onClick={() => setStep(3)} style={{
                  flex: 2, padding: 9, fontSize: 12, fontWeight: 700,
                  background: "#0f172a", border: "none",
                  borderRadius: 8, color: "white", cursor: "pointer",
                }}>
                  Já assinei · próximo
                </button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div data-testid="sign-step-3">
              <h4 style={{ margin: 0, fontSize: 15, fontWeight: 800, color: "#0f172a" }}>
                3. Envie o PDF assinado
              </h4>
              <p style={{ fontSize: 12.5, color: "#64748b", lineHeight: 1.5, margin: "6px 0 12px" }}>
                Selecione o arquivo que você baixou do assinador gov.br.
              </p>
              {error && (
                <div style={{
                  padding: 9, borderRadius: 8, marginBottom: 10,
                  background: "#fef2f2", color: "#b91c1c",
                  fontSize: 12, fontWeight: 600,
                }}>{error}</div>
              )}
              <label style={{
                display: "block", padding: 22, borderRadius: 10,
                border: "2px dashed #cbd5e1", background: "#fafafa",
                textAlign: "center", cursor: "pointer", marginBottom: 12,
              }}>
                <input
                  type="file" accept="application/pdf"
                  data-testid="sign-upload-input"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  style={{ display: "none" }}
                />
                {file ? (
                  <div style={{ fontSize: 13, color: "#15803d", fontWeight: 700 }}>
                     {file.name}
                    <div style={{ fontSize: 10.5, color: "#94a3b8", marginTop: 3 }}>
                      {(file.size / 1024).toFixed(0)} KB
                    </div>
                  </div>
                ) : (
                  <>
                    <div style={{ fontSize: 28, opacity: .3, marginBottom: 4 }}>↑</div>
                    <div style={{ fontSize: 12.5, color: "#475569", fontWeight: 600 }}>
                      Toque para selecionar o PDF
                    </div>
                  </>
                )}
              </label>
              <Button
                onClick={handleUpload}
                disabled={!file || uploading}
                data-testid="sign-submit-btn"
                style={{
                  width: "100%", padding: 12, fontSize: 13, fontWeight: 700,
                  background: file && !uploading ? "#15803d" : "#cbd5e1",
                  borderColor: file && !uploading ? "#15803d" : "#cbd5e1",
                  color: "white",
                }}
              >
                {uploading ? "Enviando…" : "Confirmar envio"}
              </Button>
              <button onClick={() => setStep(2)} style={{
                width: "100%", marginTop: 6, padding: 6, fontSize: 11,
                background: "transparent", border: "none", color: "#94a3b8",
                cursor: "pointer",
              }}>
                Voltar
              </button>
            </div>
          )}

          {step === 4 && result && (
            <div data-testid="sign-step-done" style={{ textAlign: "center" }}>
              <div style={{
                width: 56, height: 56, borderRadius: "50%",
                background: result.signature_valid ? "#dcfce7" : "#fff7ed",
                color: result.signature_valid ? "#15803d" : "#9a3412",
                display: "inline-grid", placeItems: "center",
                fontSize: 28, marginBottom: 12, fontWeight: 900,
              }}>{result.signature_valid ? "✓" : "!"}</div>
              <h3 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
                {result.signature_valid ? "Assinatura validada" : "Recebido com aviso"}
              </h3>
              <p style={{ fontSize: 12, color: "#64748b", lineHeight: 1.5,
                margin: "0 0 12px", padding: "0 8px" }}>
                {result.signature_valid
                  ? "Seu holerite assinado foi recebido e a assinatura digital foi detectada."
                  : "Recebemos seu arquivo, mas não detectamos assinatura digital. Verifique se foi assinado pelo gov.br."}
              </p>
              {result.warning && (
                <div style={{
                  padding: 9, borderRadius: 8, marginBottom: 12,
                  background: "#fff7ed", color: "#9a3412",
                  fontSize: 11, lineHeight: 1.5, textAlign: "left",
                }}>{result.warning}</div>
              )}
              <details style={{ textAlign: "left", marginBottom: 14 }}>
                <summary style={{ fontSize: 11, color: "#94a3b8",
                  fontWeight: 600, cursor: "pointer" }}>
                  Hash SHA-256 (auditoria)
                </summary>
                <div style={{
                  marginTop: 4, padding: 8, borderRadius: 6,
                  background: "#f1f5f9", fontFamily: "monospace",
                  fontSize: 9.5, wordBreak: "break-all", color: "#475569",
                }}>{result.signature_hash}</div>
              </details>
              <Button onClick={onSuccess}
                        data-testid="sign-done-close"
                        style={{ width: "100%", padding: 11, fontSize: 13, fontWeight: 700 }}>
                Fechar
              </Button>
            </div>
          )}
      </div>
    </BottomSheet>
  );
}
