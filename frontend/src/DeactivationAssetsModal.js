import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/ui";
import { api } from "@/api";
import {
  AlertTriangle, Shirt, HardHat, Wrench, Car, Smartphone, Package,
  Cable, Boxes, FileDown, X, CheckCircle2, ArrowLeft, PenTool,
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
 * Fluxo de desativação em 2 passos:
 *  Passo 1: Checklist visual (tique presencialmente cada item)
 *  Passo 2: Captura de assinatura digital do recebedor + nome/cargo,
 *           POST /api/collab-assets/return-confirm/{cid} → recebe PDF
 *           e abre em nova aba (auditoria salva em db.collab_returns).
 */
export default function DeactivationAssetsModal({ collaborator, onClose }) {
  const [data, setData] = useState(null);
  const [step, setStep] = useState(1);  // 1 = checklist, 2 = signature
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState(() => new Set());

  useEffect(() => {
    if (!collaborator?.id) return;
    api.assetCustodyFull(collaborator.id)
      .then(setData)
      .catch(() => setData({ assets: [], extras: [], totals: {} }));
  }, [collaborator]);

  const allItems = useMemo(() => {
    if (!data) return [];
    const base = (data.assets || []).map((a, i) => ({
      key: a.id || `a-${i}`, origin: "asset", ...a,
    }));
    const extras = (data.extras || []).map((e, i) => ({
      key: `ext-${e.category}-${e.serial || i}`,
      origin: e.category === "ont" ? "ont" : "insumo", ...e,
    }));
    return [...base, ...extras];
  }, [data]);

  const totalValue = data?.totals?.value_brl || 0;
  const allChecked = allItems.length > 0 && allItems.every((it) => checked.has(it.key));
  const checkedCount = checked.size;

  const toggleItem = (key) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };
  const toggleAll = () => {
    if (allChecked) setChecked(new Set());
    else setChecked(new Set(allItems.map((it) => it.key)));
  };

  if (!data) {
    return (
      <Backdrop onClose={onClose}>
        <div data-testid="deact-loading" style={modalStyle}>Carregando itens em custódia…</div>
      </Backdrop>
    );
  }

  if (step === 2) {
    return (
      <Backdrop onClose={onClose}>
        <SignatureStep
          collaborator={collaborator}
          allItems={allItems}
          checkedKeys={Array.from(checked)}
          busy={busy}
          setBusy={setBusy}
          onBack={() => setStep(1)}
          onClose={onClose}
        />
      </Backdrop>
    );
  }

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

        {/* Stepper */}
        <div style={stepperWrap}>
          <span style={stepBadge(true)}>1</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>Conferir itens</span>
          <span style={{ flex: 1, height: 1, background: "#e2e8f0", margin: "0 8px" }} />
          <span style={stepBadge(false)}>2</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8" }}>Assinatura da empresa</span>
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
                        background: "none", border: "none", cursor: "pointer", padding: 0,
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
                                  : a.origin === "insumo" ? "#a16207" : "#475569";
                const tagBg = a.origin === "ont" ? "#e0f2fe"
                                : a.origin === "insumo" ? "#fef3c7" : "#f1f5f9";
                return (
                  <label key={a.key} data-testid={`deact-item-${a.key}`}
                       style={{
                         padding: "10px 12px", borderBottom: "1px solid #f1f5f9",
                         display: "flex", alignItems: "center", gap: 10, cursor: "pointer",
                         background: isChecked ? "#f0fdf4" : "transparent",
                       }}>
                    <input type="checkbox" checked={isChecked}
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

            <div style={{
              padding: 10, background: allChecked ? "#dcfce7" : "#f1f5f9",
              borderRadius: 10, fontSize: 12, fontWeight: 600,
              color: allChecked ? "#15803d" : "#475569", marginBottom: 12,
              display: "flex", alignItems: "center", gap: 8,
            }}>
              {allChecked ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              {checkedCount} de {allItems.length} itens conferidos
              {allChecked && " — pronto para a assinatura."}
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

            <Button onClick={() => setStep(2)} disabled={!allChecked || busy}
                    data-testid="deact-go-signature"
                    style={{ width: "100%", background: "#0f172a", color: "white",
                             marginBottom: 8, gap: 8,
                             opacity: allChecked ? 1 : 0.5 }}>
              <PenTool size={16} />
              {allChecked ? "Avançar para assinatura da empresa" : `Confira todos os ${allItems.length} itens`}
            </Button>
          </>
        )}

        <Button variant="soft" onClick={onClose} data-testid="deact-close-btn"
                style={{ width: "100%", gap: 8 }}>
          <X size={14} /> Fechar
        </Button>
      </div>
    </Backdrop>
  );
}

/* ------------------- Step 2: Signature ------------------- */
function SignatureStep({ collaborator, allItems, checkedKeys, busy, setBusy, onBack, onClose }) {
  const canvasRef = useRef(null);
  const [drawing, setDrawing] = useState(false);
  const [hasInk, setHasInk] = useState(false);
  const [receiverName, setReceiverName] = useState("");
  const [receiverRole, setReceiverRole] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "white"; ctx.fillRect(0, 0, c.width, c.height);
    ctx.strokeStyle = "#0f172a"; ctx.lineWidth = 2.4;
    ctx.lineCap = "round"; ctx.lineJoin = "round";
  }, []);

  const getXY = (e) => {
    const c = canvasRef.current; const rect = c.getBoundingClientRect();
    const t = e.touches ? e.touches[0] : e;
    return {
      x: ((t.clientX - rect.left) / rect.width) * c.width,
      y: ((t.clientY - rect.top) / rect.height) * c.height,
    };
  };
  const start = (e) => {
    e.preventDefault();
    const { x, y } = getXY(e);
    const ctx = canvasRef.current.getContext("2d");
    ctx.beginPath(); ctx.moveTo(x, y);
    setDrawing(true); setHasInk(true);
  };
  const move = (e) => {
    if (!drawing) return;
    e.preventDefault();
    const { x, y } = getXY(e);
    const ctx = canvasRef.current.getContext("2d");
    ctx.lineTo(x, y); ctx.stroke();
  };
  const end = () => setDrawing(false);
  const clear = () => {
    const c = canvasRef.current; const ctx = c.getContext("2d");
    ctx.fillStyle = "white"; ctx.fillRect(0, 0, c.width, c.height);
    setHasInk(false);
  };

  const submit = async () => {
    if (!receiverName.trim() || receiverName.trim().length < 2) {
      alert("Informe o nome do recebedor."); return;
    }
    if (!hasInk) { alert("Assine no quadro antes de confirmar."); return; }
    // Abre janela ANTES do await pra evitar popup blocker
    const win = window.open("about:blank", "_blank");
    if (!win) {
      alert("Popup bloqueado. Permita popups deste site nas configurações do navegador.");
      return;
    }
    win.document.write(
      '<div style="font-family:system-ui;padding:24px;text-align:center;color:#475569">' +
      '<p>Confirmando devolução e gerando termo…</p></div>'
    );
    setBusy(true);
    try {
      const dataUrl = canvasRef.current.toDataURL("image/png");
      const { blob } = await api.assetReturnConfirm(collaborator.id, {
        receiver_name: receiverName.trim(),
        receiver_role: receiverRole.trim() || undefined,
        signature_data_url: dataUrl,
        notes: notes.trim() || undefined,
        confirmed_item_keys: checkedKeys,
      });
      win.location.href = URL.createObjectURL(blob);
      onClose();
    } catch (e) {
      try { win.close(); } catch {}
      alert("Falha: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  return (
    <div onClick={(e) => e.stopPropagation()} data-testid="deact-signature-step"
         style={modalStyle}>
      <div style={{ background: "#0f172a", margin: -20, padding: "16px 20px",
                     borderTopLeftRadius: 16, borderTopRightRadius: 16, marginBottom: 14,
                     display: "flex", alignItems: "center", gap: 10, color: "white" }}>
        <PenTool size={20} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 800 }}>Assinatura da empresa (recebedor)</div>
          <div style={{ fontSize: 12, opacity: 0.8, marginTop: 2 }}>
            {checkedKeys.length} de {allItems.length} itens conferidos · {collaborator.name}
          </div>
        </div>
      </div>

      <div style={stepperWrap}>
        <span style={stepBadge(false, true)}>1</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8" }}>Conferir itens</span>
        <span style={{ flex: 1, height: 1, background: "#0d9488", margin: "0 8px" }} />
        <span style={stepBadge(true)}>2</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>Assinatura da empresa</span>
      </div>

      <label style={fieldLabel}>Nome do recebedor *</label>
      <input type="text" value={receiverName}
             onChange={(e) => setReceiverName(e.target.value)}
             placeholder="Quem está recebendo os itens"
             data-testid="deact-receiver-name"
             style={inputStyle} maxLength={120} />

      <label style={fieldLabel}>Cargo / função</label>
      <input type="text" value={receiverRole}
             onChange={(e) => setReceiverRole(e.target.value)}
             placeholder="Ex.: Gerente de Operações"
             data-testid="deact-receiver-role"
             style={inputStyle} maxLength={80} />

      <label style={fieldLabel}>Assine no quadro abaixo *</label>
      <canvas ref={canvasRef} width={520} height={150}
              data-testid="deact-signature-canvas"
              onMouseDown={start} onMouseMove={move}
              onMouseUp={end} onMouseLeave={end}
              onTouchStart={start} onTouchMove={move} onTouchEnd={end}
              style={{ width: "100%", height: 150, border: "2px dashed #cbd5e1",
                       borderRadius: 12, touchAction: "none", cursor: "crosshair",
                       background: "white", marginBottom: 6 }} />
      <button type="button" onClick={clear} data-testid="deact-signature-clear"
              style={{ background: "none", border: "none", color: "#64748b",
                       fontSize: 12, cursor: "pointer", padding: 0, marginBottom: 12 }}>
        Limpar assinatura
      </button>

      <label style={fieldLabel}>Observações (opcional)</label>
      <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
                placeholder="Ex.: item X devolvido com avaria leve no canto"
                data-testid="deact-notes"
                style={{ ...inputStyle, minHeight: 60, resize: "vertical" }}
                maxLength={500} />

      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <Button variant="soft" onClick={onBack} disabled={busy}
                data-testid="deact-back-btn"
                style={{ gap: 6 }}>
          <ArrowLeft size={14} /> Voltar
        </Button>
        <Button onClick={submit} disabled={busy || !hasInk || !receiverName.trim()}
                data-testid="deact-submit-signed"
                style={{ flex: 1, background: "#16a34a", color: "white", gap: 8,
                         opacity: (hasInk && receiverName.trim()) ? 1 : 0.55 }}>
          <FileDown size={16} />
          {busy ? "Gerando…" : "Confirmar e gerar romaneio assinado"}
        </Button>
      </div>
    </div>
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
  maxWidth: 580, width: "100%", maxHeight: "92vh", overflowY: "auto",
};
const stepperWrap = {
  display: "flex", alignItems: "center", gap: 6, marginBottom: 14,
  padding: "8px 10px", background: "#f8fafc", borderRadius: 10,
};
const stepBadge = (active, done = false) => ({
  width: 22, height: 22, borderRadius: 11, display: "inline-flex",
  alignItems: "center", justifyContent: "center", fontSize: 11,
  fontWeight: 800,
  background: done ? "#0d9488" : (active ? "#0f172a" : "#cbd5e1"),
  color: (done || active) ? "white" : "#64748b",
});
const fieldLabel = {
  display: "block", fontSize: 11, fontWeight: 700, color: "#475569",
  textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4, marginTop: 4,
};
const inputStyle = {
  width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #cbd5e1",
  borderRadius: 8, marginBottom: 10, fontFamily: "inherit", boxSizing: "border-box",
};
