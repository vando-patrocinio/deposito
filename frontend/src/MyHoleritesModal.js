import React, { useCallback, useEffect, useState } from "react";
import { Button } from "@/ui";
import { api } from "@/api";

const MONTHS = [
  "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
  "Jul", "Ago", "Set", "Out", "Nov", "Dez",
];

function fmtBRL(v) {
  const n = Number(v || 0);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export default function MyHoleritesModal({ collaboratorId, onClose }) {
  const [data, setData] = useState({ collaborator: {}, items: [], count: 0 });
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [signing, setSigning] = useState(null); // doc being signed

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.publicHoleritesList(collaboratorId);
      setData(r);
    } finally { setLoading(false); }
  }, [collaboratorId]);

  useEffect(() => { reload(); }, [reload]);

  const items = (data.items || []).filter((h) => {
    if (!filter) return true;
    const q = filter.toLowerCase();
    return (
      String(h.competence_year).includes(q) ||
      MONTHS[h.competence_month - 1]?.toLowerCase().includes(q) ||
      String(fmtBRL(h.net)).toLowerCase().includes(q)
    );
  });

  function viewPDF(h) {
    window.open(api.publicHoleriteFileUrl(collaboratorId, h.id), "_blank");
  }

  function viewSignedPDF(h) {
    window.open(api.publicSignedHoleriteFileUrl(collaboratorId, h.id), "_blank");
  }

  return (
    <div onClick={onClose} data-testid="my-holerites-modal" style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.7)", zIndex: 100,
      padding: 12, overflowY: "auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        maxWidth: 720, margin: "20px auto",
        background: "white", borderRadius: 16, padding: 18,
        boxShadow: "0 20px 50px rgba(0,0,0,.25)",
      }}>
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "flex-start", marginBottom: 14,
        }}>
          <div>
            <div style={{
              fontSize: 11, fontWeight: 800, color: "#64748b",
              textTransform: "uppercase", letterSpacing: ".5px",
            }}>Meus holerites</div>
            <h2 style={{ margin: 0, fontSize: 19, fontWeight: 900, color: "#0f172a" }}>
              Olá, {data.collaborator?.name?.split(" ")[0] || "colaborador"}
            </h2>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
              {data.count || 0} {(data.count || 0) === 1 ? "holerite disponível" : "holerites disponíveis"}
            </div>
          </div>
          <button onClick={onClose} data-testid="my-holerites-close"
                  style={{
                    width: 34, height: 34, borderRadius: "50%",
                    border: "1px solid #e2e8f0", background: "white",
                    cursor: "pointer", fontSize: 18, color: "#64748b",
                  }}>×</button>
        </div>

        <input
          type="text" placeholder="Filtrar por ano, mês ou valor…"
          value={filter} onChange={(e) => setFilter(e.target.value)}
          data-testid="my-holerites-filter"
          style={{
            width: "100%", padding: "9px 12px", borderRadius: 10,
            border: "1px solid #e2e8f0", fontSize: 13, marginBottom: 14,
            outline: "none",
          }}
        />

        {loading ? (
          <div style={{ padding: 30, textAlign: "center", color: "#64748b" }}>
            Carregando…
          </div>
        ) : items.length === 0 ? (
          <div style={{
            padding: 36, textAlign: "center", color: "#64748b",
            border: "1px dashed #e2e8f0", borderRadius: 12,
          }}>
            <div style={{ fontSize: 28, marginBottom: 6 }}>🧾</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
              Nenhum holerite disponível ainda
            </div>
            <div style={{ fontSize: 12, marginTop: 4 }}>
              Quando o RH publicar seu holerite, ele aparecerá aqui no mês do pagamento.
            </div>
          </div>
        ) : (
          <div data-testid="my-holerites-list" style={{ display: "grid", gap: 8 }}>
            {items.map((h) => (
              <HoleriteCard key={h.id} h={h}
                              onView={() => viewPDF(h)}
                              onSign={() => setSigning(h)}
                              onViewSigned={() => viewSignedPDF(h)} />
            ))}
          </div>
        )}

        <div style={{
          marginTop: 18, padding: 10, borderRadius: 8,
          background: "#f1f5f9", color: "#475569",
          fontSize: 11, lineHeight: 1.5,
        }}>
          <strong>🔒 LGPD:</strong> Esses documentos são confidenciais. Holerites
          aparecem aqui somente a partir da data de pagamento. Todo download é
          auditado. Você pode assinar digitalmente com sua conta gov.br para
          confirmar recebimento (Lei 14.063/2020).
        </div>

        {signing && (
          <SignWithGovBrModal
            doc={signing}
            collaboratorId={collaboratorId}
            onClose={() => setSigning(null)}
            onSuccess={() => { setSigning(null); reload(); }}
          />
        )}
      </div>
    </div>
  );
}

function HoleriteCard({ h, onView, onSign, onViewSigned }) {
  const month = MONTHS[h.competence_month - 1] || "?";
  const signed = !!h.signed_at;
  return (
    <div data-testid={`my-holerite-${h.id}`} style={{
      padding: 12, borderRadius: 12,
      border: signed ? "1px solid #16a34a" : "1px solid #e2e8f0",
      background: signed ? "rgba(22,163,74,.04)" : "white",
    }}>
      <div style={{
        display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 12,
        alignItems: "center",
      }}>
        <div style={{
          width: 50, height: 50, borderRadius: 10,
          background: signed
            ? "linear-gradient(135deg, #16a34a, #22c55e)"
            : "linear-gradient(135deg, #6366f1, #8b5cf6)",
          color: "white", display: "grid", placeItems: "center",
        }}>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".5px",
              textTransform: "uppercase", opacity: .9 }}>{month}</div>
            <div style={{ fontSize: 13, fontWeight: 900, marginTop: 1 }}>
              {h.competence_year}
            </div>
          </div>
        </div>

        <div>
          <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>
            {fmtBRL(h.net)}
          </div>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 1 }}>
            Bruto {fmtBRL(h.gross)} · Descontos {fmtBRL(h.deductions_total || 0)}
          </div>
          {signed && (
            <div data-testid={`signed-badge-${h.id}`} style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              marginTop: 4, padding: "2px 8px", borderRadius: 999,
              background: "#16a34a", color: "white",
              fontSize: 10, fontWeight: 800,
            }}>
              ✓ Assinado em {new Date(h.signed_at).toLocaleDateString("pt-BR")}
              {h.signature_valid && <span title="Assinatura digital detectada">🔐</span>}
            </div>
          )}
          {h.viewed_at && !signed && (
            <div style={{ fontSize: 10, color: "#16a34a", marginTop: 2, fontWeight: 700 }}>
              ✓ Visualizado
            </div>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <Button onClick={onView} data-testid={`view-holerite-${h.id}`}
                    style={{ fontSize: 11, padding: "5px 10px" }}>
            Baixar original
          </Button>
          {signed ? (
            <Button onClick={onViewSigned}
                      data-testid={`view-signed-${h.id}`}
                      style={{ fontSize: 11, padding: "5px 10px",
                        background: "#16a34a", borderColor: "#16a34a",
                        color: "white" }}>
              Baixar assinado
            </Button>
          ) : (
            <Button onClick={onSign}
                      data-testid={`sign-holerite-${h.id}`}
                      style={{ fontSize: 11, padding: "5px 10px",
                        background: "#1351b4", borderColor: "#1351b4",
                        color: "white" }}>
              Assinar gov.br
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/* =============================================================
   SignWithGovBrModal — fluxo de 3 passos
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
      setError(e?.response?.data?.detail || e.message || "Erro ao enviar arquivo.");
    } finally { setUploading(false); }
  }

  return (
    <div onClick={onClose} data-testid="sign-govbr-modal" style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", zIndex: 200,
      padding: 14, display: "grid", placeItems: "center",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 14,
        width: "min(560px, 96vw)", maxHeight: "92vh", overflow: "auto",
      }}>
        {/* Header */}
        <div style={{
          padding: 16,
          background: "linear-gradient(135deg, #1351b4, #2670e8)",
          color: "white", borderRadius: "14px 14px 0 0",
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <div>
            <div style={{ fontSize: 11, opacity: .9, fontWeight: 700,
              textTransform: "uppercase", letterSpacing: ".5px" }}>
              Assinatura gov.br
            </div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800 }}>
              Holerite {MONTHS[doc.competence_month - 1]}/{doc.competence_year}
            </h3>
          </div>
          <button onClick={onClose} style={{
            background: "rgba(255,255,255,.2)", border: "none",
            color: "white", width: 30, height: 30, borderRadius: "50%",
            fontSize: 16, cursor: "pointer",
          }}>×</button>
        </div>

        <div style={{ padding: 18 }}>
          {/* Step indicator */}
          <div style={{
            display: "flex", justifyContent: "space-between",
            marginBottom: 18, gap: 6,
          }}>
            {[1, 2, 3].map((n) => (
              <div key={n} style={{
                flex: 1, height: 4, borderRadius: 4,
                background: step >= n ? "#1351b4" : "#e2e8f0",
                transition: "background .2s",
              }} />
            ))}
          </div>

          {step === 1 && (
            <div data-testid="sign-step-1">
              <div style={{ fontSize: 11, color: "#1351b4", fontWeight: 800,
                textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 4 }}>
                Passo 1 de 3
              </div>
              <h4 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
                Baixe o holerite original
              </h4>
              <p style={{ fontSize: 12.5, color: "#475569", lineHeight: 1.5, marginBottom: 14 }}>
                Vamos abrir o PDF original em uma nova aba. Salve no seu celular ou computador
                para usar no próximo passo.
              </p>
              <Button
                onClick={() => {
                  window.open(
                    api.publicHoleriteFileUrl(collaboratorId, doc.id), "_blank",
                  );
                  setStep(2);
                }}
                data-testid="sign-download-btn"
                style={{
                  width: "100%", padding: 12, fontSize: 14, fontWeight: 800,
                  background: "#1351b4", borderColor: "#1351b4", color: "white",
                }}
              >
                📥 Baixar PDF original
              </Button>
              <button onClick={() => setStep(2)} style={{
                width: "100%", marginTop: 8, padding: 8, fontSize: 12,
                background: "transparent", border: "none", color: "#64748b",
                cursor: "pointer", textDecoration: "underline",
              }}>
                Já tenho o PDF, próximo →
              </button>
            </div>
          )}

          {step === 2 && (
            <div data-testid="sign-step-2">
              <div style={{ fontSize: 11, color: "#1351b4", fontWeight: 800,
                textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 4 }}>
                Passo 2 de 3
              </div>
              <h4 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
                Assine com sua conta gov.br
              </h4>
              <ol style={{
                fontSize: 12.5, color: "#475569", lineHeight: 1.7,
                paddingLeft: 18, marginBottom: 12,
              }}>
                <li>Clique em <strong>"Abrir assinador gov.br"</strong> abaixo.</li>
                <li>Faça login com sua conta <strong>gov.br</strong> (CPF + senha).</li>
                <li>Suba o PDF que você baixou no Passo 1.</li>
                <li>Clique em <strong>"Assinar"</strong> e digite seu código de validação.</li>
                <li>Baixe o PDF assinado de volta no seu dispositivo.</li>
              </ol>
              <div style={{
                padding: 10, borderRadius: 8, marginBottom: 12,
                background: "#dbeafe", color: "#1e40af",
                fontSize: 11, lineHeight: 1.5,
              }}>
                ℹ️ A assinatura via gov.br tem valor legal pela
                <strong> Lei 14.063/2020</strong> e é aceita pelo STJ para
                holerites e documentos trabalhistas.
              </div>
              <a href="https://assinador.iti.br/" target="_blank" rel="noopener noreferrer"
                  data-testid="open-govbr-signer"
                  style={{
                    display: "block", textAlign: "center",
                    padding: 12, borderRadius: 8, fontSize: 14, fontWeight: 800,
                    background: "#1351b4", color: "white", textDecoration: "none",
                  }}>
                🔐 Abrir assinador gov.br ↗
              </a>
              <button onClick={() => setStep(3)} style={{
                width: "100%", marginTop: 10, padding: 10, fontSize: 12.5,
                fontWeight: 700, background: "white",
                border: "1px solid #e2e8f0", borderRadius: 8,
                color: "#475569", cursor: "pointer",
              }}>
                Já assinei, próximo →
              </button>
              <button onClick={() => setStep(1)} style={{
                width: "100%", marginTop: 4, padding: 6, fontSize: 11,
                background: "transparent", border: "none", color: "#64748b",
                cursor: "pointer",
              }}>
                ← Voltar
              </button>
            </div>
          )}

          {step === 3 && (
            <div data-testid="sign-step-3">
              <div style={{ fontSize: 11, color: "#1351b4", fontWeight: 800,
                textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 4 }}>
                Passo 3 de 3
              </div>
              <h4 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
                Envie o PDF assinado
              </h4>
              <p style={{ fontSize: 12.5, color: "#475569", lineHeight: 1.5, marginBottom: 12 }}>
                Selecione o arquivo que você baixou do assinador gov.br.
                Vamos guardá-lo junto com o original.
              </p>
              {error && (
                <div style={{
                  padding: 8, borderRadius: 6, marginBottom: 10,
                  background: "#fef2f2", color: "#b91c1c",
                  fontSize: 12, fontWeight: 600,
                }}>{error}</div>
              )}
              <div style={{
                border: "2px dashed #cbd5e1", borderRadius: 10,
                padding: 22, textAlign: "center", marginBottom: 12,
                background: "#f8fafc",
              }}>
                <input
                  type="file" accept="application/pdf"
                  data-testid="sign-upload-input"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  style={{ fontSize: 12 }}
                />
                {file && (
                  <div style={{ marginTop: 8, fontSize: 12, color: "#16a34a", fontWeight: 700 }}>
                    📄 {file.name} ({(file.size / 1024).toFixed(0)}KB)
                  </div>
                )}
              </div>
              <Button
                onClick={handleUpload}
                disabled={!file || uploading}
                data-testid="sign-submit-btn"
                style={{
                  width: "100%", padding: 12, fontSize: 14, fontWeight: 800,
                  background: file && !uploading ? "#16a34a" : "#94a3b8",
                  borderColor: file && !uploading ? "#16a34a" : "#94a3b8",
                  color: "white",
                }}
              >
                {uploading ? "Enviando…" : "✓ Confirmar envio"}
              </Button>
              <button onClick={() => setStep(2)} style={{
                width: "100%", marginTop: 8, padding: 6, fontSize: 11,
                background: "transparent", border: "none", color: "#64748b",
                cursor: "pointer",
              }}>
                ← Voltar
              </button>
            </div>
          )}

          {step === 4 && result && (
            <div data-testid="sign-step-done" style={{ textAlign: "center" }}>
              <div style={{
                width: 70, height: 70, borderRadius: "50%",
                background: result.signature_valid ? "#16a34a" : "#f59e0b",
                color: "white", display: "inline-grid", placeItems: "center",
                fontSize: 36, marginBottom: 12,
              }}>{result.signature_valid ? "🔐" : "✓"}</div>
              <h3 style={{ margin: "0 0 6px", fontSize: 17, fontWeight: 800, color: "#0f172a" }}>
                {result.signature_valid ? "Assinatura validada!" : "Recebido com observação"}
              </h3>
              <p style={{ fontSize: 12.5, color: "#475569", lineHeight: 1.5, marginBottom: 12 }}>
                {result.signature_valid
                  ? "Seu holerite assinado foi recebido e validado. A assinatura digital foi detectada no arquivo."
                  : "Recebemos seu arquivo, mas não detectamos marcadores de assinatura digital. Verifique se foi mesmo assinado via gov.br."}
              </p>
              {result.warning && (
                <div style={{
                  padding: 9, borderRadius: 6, marginBottom: 12,
                  background: "#fff7ed", color: "#9a3412",
                  fontSize: 11.5, fontWeight: 600,
                  textAlign: "left",
                }}>
                  ⚠️ {result.warning}
                </div>
              )}
              <div style={{
                padding: 9, borderRadius: 6, marginBottom: 14,
                background: "#f1f5f9", color: "#475569",
                fontSize: 10, fontFamily: "monospace", wordBreak: "break-all",
              }}>
                <strong>SHA-256:</strong> {result.signature_hash}
              </div>
              <Button onClick={onSuccess}
                        data-testid="sign-done-close"
                        style={{ width: "100%", padding: 11, fontSize: 13,
                          fontWeight: 800 }}>
                Fechar
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
