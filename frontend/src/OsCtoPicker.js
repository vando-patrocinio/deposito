/* OsCtoPicker — Step 2 do fluxo de OS na Lousa Mobile.
   iter182 — Tira a responsabilidade de CADASTRO da OS.
   O técnico apenas SELECIONA uma CTO existente (cadastrada previamente
   no módulo "Cadastro de Rede"). Se a CTO necessária ainda não existe,
   ele é redirecionado pro módulo de cadastro.

   Substitui o antigo `CtoInlineFlow screen="A"` que coletava endereço,
   GPS, VLAN, foto e capacidade dentro da OS.
*/
import React from "react";
import CTOMapPicker from "@/CTOMapPicker";

const Card = ({ children, ...rest }) => (
  <div {...rest} style={{
    padding: 14, borderRadius: 14, background: "#fff",
    border: "1px solid #e2e8f0",
    boxShadow: "0 1px 3px rgba(15,23,42,.04)",
    ...(rest.style || {}),
  }}>{children}</div>
);

export default function OsCtoPicker({
  collabId,
  onSelectExistingCto,
  onSkip,
  onBack,
}) {
  const [err, setErr] = React.useState("");

  return (
    <div data-testid="os-cto-picker">
      <Card style={{ marginBottom: 10,
                       background: "linear-gradient(135deg,#eff6ff,#dbeafe)",
                       border: "1px solid #93c5fd" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 24 }}>📍</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: "#1e40af" }}>
              Selecione a CTO já cadastrada
            </div>
            <div style={{ fontSize: 11.5, color: "#1e3a8a", marginTop: 2,
                            lineHeight: 1.4 }}>
              Toque no pino azul da CTO no mapa. Cadastro de CTO/CE/Cabo
              só pelo <strong>início da Lousa</strong>.
            </div>
          </div>
        </div>
      </Card>

      {/* Mapa — só leitura + seleção de CTOs existentes */}
      <div style={{ borderRadius: 14, overflow: "hidden",
                      border: "1px solid #e2e8f0", marginBottom: 10,
                      height: 320 }}>
        <CTOMapPicker
          collabId={collabId}
          onSelectExistingCto={onSelectExistingCto}
          onError={(m) => setErr(m)}
        />
      </div>

      {err && (
        <div data-testid="os-cto-picker-err" style={{
          padding: "8px 12px", borderRadius: 8,
          background: "#fef2f2", color: "#991b1b",
          fontSize: 12, marginBottom: 8,
        }}>⚠️ {err}</div>
      )}

      {/* iter182 — CTA de cadastro de CTO REMOVIDA do fluxo da OS.
          Decisão do gestor: cadastro de CTO/CE/Cabo só pelo INÍCIO da
          Lousa (módulo "Cadastro de Rede"). Aqui só selecionamos uma
          existente. */}
      <div data-testid="os-cto-picker-hint" style={{
        marginBottom: 10, padding: "10px 12px", borderRadius: 10,
        background: "#fffbeb", border: "1px solid #fcd34d",
        fontSize: 11.5, color: "#78350f", lineHeight: 1.5,
      }}>
        <strong>Não encontrou a CTO no mapa?</strong> Volte ao início da
        Lousa e abra <strong>Cadastro de Rede (CTO / CE / Cabo)</strong>{" "}
        para criá-la. Depois retorne para esta OS.
      </div>

      {/* Navegação */}
      <div style={{ display: "flex", gap: 8 }}>
        <button data-testid="os-cto-picker-back"
          onClick={onBack}
          style={{ flex: 1, padding: "12px 14px", borderRadius: 10,
                     background: "#f1f5f9", color: "#475569",
                     border: "1px solid #cbd5e1",
                     fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
          ← Voltar
        </button>
        {onSkip && (
          <button data-testid="os-cto-picker-skip"
            onClick={onSkip}
            style={{ flex: 1, padding: "12px 14px", borderRadius: 10,
                       background: "#fff", color: "#64748b",
                       border: "1px solid #cbd5e1",
                       fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
            Pular CTO →
          </button>
        )}
      </div>
    </div>
  );
}
