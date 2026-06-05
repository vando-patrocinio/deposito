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

export default function OsCtoPicker({
  collabId,
  onSelectExistingCto,
  onSkip,
  onBack,
}) {
  return (
    <div data-testid="os-cto-picker">
      {/* iter211ak — Card azul "Selecione a CTO já cadastrada" removido
          (poluindo a tela). O aviso amarelo abaixo já comunica o mesmo. */}

      {/* Mapa — só leitura + seleção de CTOs existentes.
          iter211al — Removido banner externo de erro de GPS: o próprio
          CTOMapPicker já exibe o aviso dentro do mapa (overlay amarelo).
          Manter os 2 era duplicação visual. */}
      <div style={{ borderRadius: 14, overflow: "hidden",
                      border: "1px solid #e2e8f0", marginBottom: 10,
                      height: 320 }}>
        <CTOMapPicker
          collabId={collabId}
          onSelectExistingCto={onSelectExistingCto}
        />
      </div>

      {/* iter182 — CTA de cadastro de CTO REMOVIDA do fluxo da OS.
          iter211an — Aviso amarelo removido (poluindo a tela). */}

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
            Ir para Finalização →
          </button>
        )}
      </div>
    </div>
  );
}
