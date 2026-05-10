import React, { useEffect, useState } from "react";
import { Button } from "@/ui";
import { api } from "@/api";

const CATEGORY_ICON = {
  uniforme: "👕", epi: "🦺", ferramenta: "🔧",
  veiculo: "🚗", eletronico: "📱", outro: "📦",
};

/**
 * Modal automático que aparece logo após desativar um colaborador.
 * Lista os pertences ativos e oferece o botão para imprimir o romaneio
 * de devolução (PDF).
 */
export default function DeactivationAssetsModal({ collaborator, onClose }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!collaborator?.id) return;
    api.assetsList(collaborator.id).then(setData).catch(() => setData({ items: [], summary: {} }));
  }, [collaborator]);

  const ativos = (data?.items || []).filter((a) => a.status === "ativo");
  const totalValue = ativos.reduce((acc, a) => {
    const u = a.unit_value_brl;
    return acc + (u != null ? u * (a.qty || 1) : 0);
  }, 0);

  const printRomaneio = () => {
    setBusy(true);
    const url = api.assetRomaneioUrl(collaborator.id, true);
    const token = localStorage.getItem("ponto_token");
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        if (!r.ok) throw new Error("Falha ao gerar PDF");
        return r.blob();
      })
      .then((blob) => {
        const obj = URL.createObjectURL(blob);
        window.open(obj, "_blank");
      })
      .catch((e) => alert("Falha: " + e.message))
      .finally(() => setBusy(false));
  };

  if (!data) {
    return (
      <Backdrop onClose={onClose}>
        <div data-testid="deact-loading" style={modalStyle}>Carregando pertences…</div>
      </Backdrop>
    );
  }

  return (
    <Backdrop onClose={onClose}>
      <div onClick={(e) => e.stopPropagation()} data-testid="deactivation-assets-modal"
           style={modalStyle}>
        <div style={{ background: "#fee2e2", margin: -20, padding: "16px 20px",
                       borderTopLeftRadius: 16, borderTopRightRadius: 16, marginBottom: 14 }}>
          <div style={{ fontSize: 18, fontWeight: 800, color: "#7f1d1d" }}>
            ⚠ Colaborador desativado
          </div>
          <div style={{ fontSize: 13, color: "#7f1d1d", marginTop: 4 }}>
            <strong>{collaborator.name}</strong> foi marcado como inativo.
          </div>
        </div>

        {ativos.length === 0 ? (
          <div data-testid="deact-no-assets" style={{
            padding: 20, textAlign: "center", color: "#16a34a",
            background: "#dcfce7", borderRadius: 12, fontWeight: 600,
          }}>
            ✓ Sem pertences ativos pendentes de devolução.
          </div>
        ) : (
          <>
            <div style={{ fontSize: 13, color: "#475569", marginBottom: 10, fontWeight: 600 }}>
              📋 Pertences a serem cobrados / devolvidos ({ativos.length} item{ativos.length > 1 ? "ns" : ""}):
            </div>
            <div style={{ maxHeight: 320, overflowY: "auto", border: "1px solid #e2e8f0",
                           borderRadius: 12, marginBottom: 12 }}>
              {ativos.map((a) => (
                <div key={a.id} data-testid={`deact-item-${a.id}`}
                     style={{ padding: "10px 12px", borderBottom: "1px solid #f1f5f9",
                              display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
                      {CATEGORY_ICON[a.category] || "📦"} {a.item}
                    </div>
                    <div style={{ fontSize: 11, color: "#475569", marginTop: 2 }}>
                      {[a.marca, a.modelo].filter(Boolean).join(" / ") || "—"}
                      {a.tamanho && ` · Tam. ${a.tamanho}`}
                      {` · Qtd ${a.qty}`}
                      {a.serial && ` · SN ${a.serial}`}
                    </div>
                  </div>
                  {a.unit_value_brl != null && (
                    <div style={{ fontSize: 13, fontWeight: 800, color: "#86198f", whiteSpace: "nowrap" }}>
                      R$ {(a.unit_value_brl * (a.qty || 1)).toFixed(2).replace(".", ",")}
                    </div>
                  )}
                </div>
              ))}
            </div>
            {totalValue > 0 && (
              <div style={{
                padding: 12, background: "#fef3c7", borderRadius: 10,
                fontSize: 13, fontWeight: 700, color: "#78350f", marginBottom: 12,
                display: "flex", justifyContent: "space-between",
              }}>
                <span>💰 Valor total estimado:</span>
                <span>R$ {totalValue.toFixed(2).replace(".", ",")}</span>
              </div>
            )}
            <Button onClick={printRomaneio} disabled={busy}
                    data-testid="deact-print-romaneio"
                    style={{ width: "100%", background: "#0f172a", color: "white", marginBottom: 8 }}>
              {busy ? "Gerando…" : "📄 Imprimir romaneio de devolução"}
            </Button>
          </>
        )}
        <Button variant="soft" onClick={onClose}
                data-testid="deact-close-btn"
                style={{ width: "100%" }}>
          Fechar
        </Button>
      </div>
    </Backdrop>
  );
}

function Backdrop({ children, onClose }) {
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 200,
      display: "grid", placeItems: "center", padding: 12,
    }}>{children}</div>
  );
}

const modalStyle = {
  background: "white", borderRadius: 16, padding: 20,
  maxWidth: 540, width: "100%", maxHeight: "90vh", overflowY: "auto",
};
