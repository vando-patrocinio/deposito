import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/ui";
import { api } from "@/api";

const CATEGORY_ICON = {
  uniforme: "👕", epi: "🦺", ferramenta: "🔧",
  veiculo: "🚗", eletronico: "📱", outro: "📦",
};

const STATUS_LABEL = {
  ativo: { label: "Em uso", color: "#166534", bg: "#dcfce7" },
  devolvido: { label: "Devolvido", color: "#475569", bg: "#e2e8f0" },
  danificado: { label: "Danificado", color: "#92400e", bg: "#fef3c7" },
  perdido: { label: "Perdido", color: "#991b1b", bg: "#fee2e2" },
};

export default function MyAssetsModal({ collaboratorId, onClose }) {
  const [data, setData] = useState({ collaborator: {}, items: [] });
  const [signing, setSigning] = useState(false);
  const [msg, setMsg] = useState(null);

  const reload = useCallback(async () => {
    try { setData(await api.publicAssetsList(collaboratorId)); }
    catch (e) { setMsg({ type: "err", text: e.message }); }
  }, [collaboratorId]);
  useEffect(() => { reload(); }, [reload]);

  const pending = data.items.filter((a) => !a.signed_at && a.status === "ativo");

  const downloadRomaneio = () => {
    const url = api.publicRomaneioUrl(collaboratorId, false);
    window.open(url, "_blank");
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.7)", zIndex: 100,
      padding: 12, overflowY: "auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="my-assets-modal" style={{
        background: "white", maxWidth: 480, margin: "0 auto",
        borderRadius: 22, padding: 16, minHeight: "70vh",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: "#0f172a" }}>Meus itens em custódia </h2>
          <button onClick={onClose} data-testid="assets-close-btn"
                  style={{ background: "transparent", border: 0, fontSize: 22,
                           cursor: "pointer", color: "#64748b" }}>✕</button>
        </div>

        <div style={{
          padding: 12, background: "#f8fafc", borderRadius: 12, marginBottom: 12,
          fontSize: 12, color: "#64748b",
        }}>
          {data.items.length} item(ns) registrados em seu nome.
          {pending.length > 0 && (
            <div style={{ marginTop: 6, color: "#92400e", fontWeight: 700 }}>
              ⏳ {pending.length} item(ns) aguardando sua assinatura
            </div>
          )}
        </div>

        {pending.length > 0 && (
          <div data-testid="pending-banner" style={{
            background: "linear-gradient(135deg,#fde68a,#fbbf24)",
            padding: 14, borderRadius: 14, marginBottom: 14,
          }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: "#78350f", marginBottom: 6 }}>
              📝 Assine o romaneio
            </div>
            <div style={{ fontSize: 12, color: "#78350f", lineHeight: 1.5, marginBottom: 8 }}>
              Você recebeu novos itens. Confira a lista e <strong>assine</strong> aceitando a
              responsabilidade pela guarda e devolução.
            </div>
            <Button onClick={() => setSigning(true)} data-testid="open-sign-btn"
                    style={{ background: "#78350f", color: "white", width: "100%" }}>
              ✍ Conferir e assinar romaneio ({pending.length})
            </Button>
          </div>
        )}

        {/* Lista um a um */}
        <div data-testid="assets-list">
          {data.items.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", color: "#94a3b8", fontSize: 13 }}>
              Nenhum pertence cadastrado em seu nome ainda.<br />
              Procure o gestor da sua filial.
            </div>
          ) : data.items.map((a) => {
            const st = STATUS_LABEL[a.status] || STATUS_LABEL.ativo;
            return (
              <div key={a.id} data-testid={`my-asset-${a.id}`}
                   style={{
                     padding: 14, marginBottom: 10, border: "1px solid #e2e8f0",
                     borderRadius: 14, background: "white",
                     borderLeft: a.signed_at ? "4px solid #16a34a" : "4px solid #f59e0b",
                   }}>
                <div style={{ display: "flex", justifyContent: "space-between",
                               gap: 10, marginBottom: 6, alignItems: "flex-start" }}>
                  <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>
                    {CATEGORY_ICON[a.category] || "📦"} {a.item}
                  </div>
                  <span style={{ padding: "2px 8px", borderRadius: 999,
                                  background: st.bg, color: st.color, fontSize: 10, fontWeight: 800 }}>
                    {st.label}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: "#475569", lineHeight: 1.6 }}>
                  {a.marca || a.modelo
                    ? <>Marca/Modelo: <strong>{[a.marca, a.modelo].filter(Boolean).join(" / ")}</strong><br /></>
                    : null}
                  {a.tamanho && <>Tamanho: <strong>{a.tamanho}</strong>  ·  </>}
                  Qtd: <strong>{a.qty}</strong>
                  {a.unit_value_brl != null && (
                    <>  ·  Valor: <strong style={{ color: "#86198f" }}>
                      R$ {(a.unit_value_brl * (a.qty || 1)).toFixed(2).replace('.', ',')}
                    </strong></>
                  )}
                  {a.serial && <><br />Nº série: <code style={{ fontSize: 11 }}>{a.serial}</code></>}
                  <br />Entregue em <strong>{(a.delivered_at || "").slice(0, 10)}</strong>
                  {a.delivered_by && ` por ${a.delivered_by}`}
                  {a.notes && <><br /><em style={{ color: "#64748b" }}>{a.notes}</em></>}
                </div>
                {a.signed_at && (
                  <div style={{ marginTop: 6, fontSize: 11, color: "#166534", fontWeight: 700 }}>
                    ✓ Assinado em {a.signed_at.slice(0, 16).replace("T", " ")}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {data.items.length > 0 && (
          <Button variant="soft" onClick={downloadRomaneio}
                  data-testid="download-romaneio-btn"
                  style={{ width: "100%", marginTop: 12 }}>
            📄 Imprimir / baixar romaneio
          </Button>
        )}

        {msg && (
          <div style={{
            marginTop: 10, padding: 10, borderRadius: 8, fontSize: 12, fontWeight: 600,
            background: msg.type === "ok" ? "#dcfce7" : "#fee2e2",
            color: msg.type === "ok" ? "#166534" : "#7f1d1d",
          }}>{msg.text}</div>
        )}

        {signing && (
          <SignaturePad
            collaboratorId={collaboratorId}
            assetIds={pending.map((p) => p.id)}
            onClose={() => setSigning(false)}
            onSigned={() => { setSigning(false); reload(); setMsg({ type: "ok", text: "Assinado com sucesso!" }); }}
          />
        )}
      </div>
    </div>
  );
}

function SignaturePad({ collaboratorId, assetIds, onClose, onSigned }) {
  const canvasRef = useRef(null);
  const [drawing, setDrawing] = useState(false);
  const [hasInk, setHasInk] = useState(false);
  const [busy, setBusy] = useState(false);

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
    if (!hasInk) { alert("Assine no quadro antes de confirmar."); return; }
    setBusy(true);
    try {
      const dataUrl = canvasRef.current.toDataURL("image/png");
      await api.publicAssetSign({
        collaborator_id: collaboratorId,
        asset_ids: assetIds,
        signature_data_url: dataUrl,
      });
      onSigned();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.85)", zIndex: 110,
      display: "grid", placeItems: "center", padding: 12,
    }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="signature-pad" style={{
        background: "white", borderRadius: 16, padding: 16, maxWidth: 460, width: "100%",
      }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 800 }}>Assine no quadro abaixo </h3>
        <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 10px" }}>
          Ao assinar, você declara ter recebido os {assetIds.length} item(ns) e
          aceita a responsabilidade pela sua guarda e devolução.
        </p>
        <canvas ref={canvasRef} width={420} height={160}
                data-testid="signature-canvas"
                onMouseDown={start} onMouseMove={move}
                onMouseUp={end} onMouseLeave={end}
                onTouchStart={start} onTouchMove={move} onTouchEnd={end}
                style={{ width: "100%", height: 160, border: "2px dashed #cbd5e1",
                         borderRadius: 12, touchAction: "none", cursor: "crosshair" }} />
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <Button variant="soft" onClick={clear} data-testid="signature-clear">
            Limpar
          </Button>
          <Button onClick={submit} disabled={busy} data-testid="signature-submit"
                  style={{ flex: 1, background: "#16a34a" }}>
            {busy ? "Enviando…" : "✓ Confirmar assinatura"}
          </Button>
          <Button variant="soft" onClick={onClose} data-testid="signature-cancel">
            Cancelar
          </Button>
        </div>
      </div>
    </div>
  );
}
