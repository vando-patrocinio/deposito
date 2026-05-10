import React, { useEffect, useMemo, useState } from "react";
import { Button } from "@/ui";
import { api } from "@/api";
import {
  AlertTriangle, Shirt, HardHat, Wrench, Car, Smartphone, Package,
  Cable, Boxes, FileDown, X, CheckCircle2,
} from "lucide-react";

const CATEGORY_ICON = {
  uniforme: Shirt,
  epi: HardHat,
  ferramenta: Wrench,
  veiculo: Car,
  eletronico: Smartphone,
  ont: Cable,
  insumo: Boxes,
  outro: Package,
};

/**
 * Modal automático que aparece logo após desativar um colaborador.
 * Lista TUDO em posse (pertences ATIVOS + ONTs do estoque do técnico +
 * insumos) com checkbox por item para conferência presencial. Ao final,
 * gera o "Romaneio de Devolução à Empresa" (PDF) que precisa da assinatura
 * do recebedor da empresa.
 */
export default function DeactivationAssetsModal({ collaborator, onClose }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState(() => new Set());

  useEffect(() => {
    if (!collaborator?.id) return;
    api.assetCustodyFull(collaborator.id)
      .then(setData)
      .catch(() => setData({ assets: [], extras: [], totals: {} }));
  }, [collaborator]);

  // Normaliza a lista única (assets + extras) preservando o tipo de origem.
  const allItems = useMemo(() => {
    if (!data) return [];
    const base = (data.assets || []).map((a, i) => ({
      key: a.id || `a-${i}`,
      origin: "asset",
      ...a,
    }));
    const extras = (data.extras || []).map((e, i) => ({
      key: `ext-${e.category}-${e.serial || i}`,
      origin: e.category === "ont" ? "ont" : "insumo",
      ...e,
    }));
    return [...base, ...extras];
  }, [data]);

  const totalValue = data?.totals?.value_brl || 0;
  const allChecked = allItems.length > 0 && allItems.every((it) => checked.has(it.key));

  const toggleItem = (key) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleAll = () => {
    if (allChecked) setChecked(new Set());
    else setChecked(new Set(allItems.map((it) => it.key)));
  };

  const printRomaneio = () => {
    setBusy(true);
    const url = api.assetDevolucaoUrl(collaborator.id);
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
        <div data-testid="deact-loading" style={modalStyle}>Carregando itens em custódia…</div>
      </Backdrop>
    );
  }

  const checkedCount = checked.size;

  return (
    <Backdrop onClose={onClose}>
      <div onClick={(e) => e.stopPropagation()} data-testid="deactivation-assets-modal"
           style={modalStyle}>
        {/* Header alerta */}
        <div style={{ background: "#fee2e2", margin: -20, padding: "16px 20px",
                       borderTopLeftRadius: 16, borderTopRightRadius: 16, marginBottom: 14,
                       display: "flex", alignItems: "center", gap: 10 }}>
          <AlertTriangle size={22} color="#7f1d1d" />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 17, fontWeight: 800, color: "#7f1d1d" }}>
              Colaborador desativado
            </div>
            <div style={{ fontSize: 13, color: "#7f1d1d", marginTop: 2 }}>
              Confira a devolução de tudo que estava em posse de <strong>{collaborator.name}</strong>.
            </div>
          </div>
        </div>

        {allItems.length === 0 ? (
          <div data-testid="deact-no-assets" style={{
            padding: 20, textAlign: "center", color: "#15803d",
            background: "#dcfce7", borderRadius: 12, fontWeight: 600,
            display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
          }}>
            <CheckCircle2 size={18} />
            Sem itens em posse — nada a devolver.
          </div>
        ) : (
          <>
            <div style={{ display: "flex", justifyContent: "space-between",
                           alignItems: "center", marginBottom: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
                Itens a devolver ({allItems.length}) — confira presencialmente:
              </div>
              <button type="button" onClick={toggleAll}
                      data-testid="deact-toggle-all"
                      style={{
                        fontSize: 12, fontWeight: 700, color: "#0d9488",
                        background: "none", border: "none", cursor: "pointer",
                        padding: 0,
                      }}>
                {allChecked ? "Desmarcar todos" : "Marcar todos"}
              </button>
            </div>

            <div style={{ maxHeight: 320, overflowY: "auto", border: "1px solid #e2e8f0",
                           borderRadius: 12, marginBottom: 12 }}>
              {allItems.map((a) => {
                const Icon = CATEGORY_ICON[a.category] || Package;
                const isChecked = checked.has(a.key);
                const tagColor = a.origin === "ont" ? "#0369a1"
                                  : a.origin === "insumo" ? "#a16207"
                                  : "#475569";
                const tagBg = a.origin === "ont" ? "#e0f2fe"
                                : a.origin === "insumo" ? "#fef3c7"
                                : "#f1f5f9";
                return (
                  <label key={a.key} data-testid={`deact-item-${a.key}`}
                       style={{
                         padding: "10px 12px", borderBottom: "1px solid #f1f5f9",
                         display: "flex", alignItems: "center", gap: 10,
                         cursor: "pointer",
                         background: isChecked ? "#f0fdf4" : "transparent",
                       }}>
                    <input type="checkbox"
                           checked={isChecked}
                           onChange={() => toggleItem(a.key)}
                           data-testid={`deact-check-${a.key}`}
                           style={{ width: 18, height: 18, accentColor: "#0d9488",
                                    cursor: "pointer", flexShrink: 0 }} />
                    <Icon size={18} color={tagColor} style={{ flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a",
                                     textDecoration: isChecked ? "line-through" : "none" }}>
                        {a.item}
                        <span style={{
                          marginLeft: 8, padding: "1px 6px", borderRadius: 4,
                          fontSize: 10, fontWeight: 700, color: tagColor,
                          background: tagBg, textTransform: "uppercase",
                          letterSpacing: 0.4, textDecoration: "none",
                        }}>{a.origin === "ont" ? "ONT" : a.origin === "insumo" ? "Insumo" : a.category}</span>
                      </div>
                      <div style={{ fontSize: 11, color: "#475569", marginTop: 2 }}>
                        {[a.marca, a.modelo].filter(Boolean).join(" / ") || ""}
                        {a.tamanho && ` · ${a.tamanho}`}
                        {a.qty && ` · Qtd ${a.qty}`}
                        {a.serial && ` · ${a.origin === "ont" ? "MAC" : "SN"} ${a.serial}`}
                      </div>
                    </div>
                    {a.unit_value_brl != null && (
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#86198f",
                                     whiteSpace: "nowrap", flexShrink: 0 }}>
                        R$ {(a.unit_value_brl * (a.qty || 1)).toFixed(2).replace(".", ",")}
                      </div>
                    )}
                  </label>
                );
              })}
            </div>

            {/* Status de conferência */}
            <div style={{
              padding: 10, background: allChecked ? "#dcfce7" : "#f1f5f9",
              borderRadius: 10, fontSize: 12, fontWeight: 600,
              color: allChecked ? "#15803d" : "#475569", marginBottom: 12,
              display: "flex", alignItems: "center", gap: 8,
            }}>
              {allChecked ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              {checkedCount} de {allItems.length} itens conferidos
              {allChecked && " — pronto para gerar o romaneio assinado pela empresa."}
            </div>

            {totalValue > 0 && (
              <div style={{
                padding: 10, background: "#fef3c7", borderRadius: 10,
                fontSize: 12, fontWeight: 700, color: "#78350f", marginBottom: 12,
                display: "flex", justifyContent: "space-between",
              }}>
                <span>Valor total estimado dos pertences:</span>
                <span>R$ {totalValue.toFixed(2).replace(".", ",")}</span>
              </div>
            )}

            <Button onClick={printRomaneio} disabled={busy}
                    data-testid="deact-print-romaneio"
                    style={{ width: "100%", background: "#0f172a", color: "white",
                             marginBottom: 8, gap: 8 }}>
              <FileDown size={16} />
              {busy ? "Gerando…" : "Imprimir romaneio de devolução à empresa"}
            </Button>
          </>
        )}

        <Button variant="soft" onClick={onClose}
                data-testid="deact-close-btn"
                style={{ width: "100%", gap: 8 }}>
          <X size={14} /> Fechar
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
  maxWidth: 580, width: "100%", maxHeight: "90vh", overflowY: "auto",
};
