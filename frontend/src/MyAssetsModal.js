import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/ui";
import BottomSheet from "@/BottomSheet";
import OntScanBatchModal from "@/OntScanBatchModal";
import { api } from "@/api";

const CATEGORY_ICON = {
  uniforme: "", epi: "", ferramenta: "",
  veiculo: "", eletronico: "", outro: "",
};

const STATUS_LABEL = {
  ativo: { label: "Em uso", color: "#166534", bg: "#dcfce7" },
  devolvido: { label: "Devolvido", color: "#475569", bg: "#e2e8f0" },
  danificado: { label: "Danificado", color: "#92400e", bg: "#fef3c7" },
  perdido: { label: "Perdido", color: "#991b1b", bg: "#fee2e2" },
};

export default function MyAssetsModal({ collaboratorId, onClose, role = "tecnico" }) {
  const [data, setData] = useState({ collaborator: {}, items: [] });
  // iter183 — estoque técnico (ONTs + consumíveis do stok)
  const [techStock, setTechStock] = useState({ onts: [], consumables: [] });
  const [signing, setSigning] = useState(false);
  const [msg, setMsg] = useState(null);
  const [showBatchScan, setShowBatchScan] = useState(false);
  const [assetTab, setAssetTab] = useState("todos"); // todos | novos | retirados | onts | insumos

  const reload = useCallback(async () => {
    try {
      const [assets, stock] = await Promise.all([
        api.publicAssetsList(collaboratorId),
        api._client.get(`/stok/public/collaborator/${collaboratorId}/stock`)
          .then((r) => r.data).catch(() => ({ onts: [], consumables: [] })),
      ]);
      setData(assets);
      setTechStock({
        onts: stock.onts || [],
        consumables: stock.consumables || [],
      });
    } catch (e) { setMsg({ type: "err", text: e.message }); }
  }, [collaboratorId]);
  useEffect(() => { reload(); }, [reload]);

  const onBatchSaved = useCallback(async (items) => {
    try {
      const r = await api.scanOntBatchCommit({
        items: items.map((it) => ({
          mac: it.mac, sn: it.sn,
          confidence: it.confidence,
          image_base64: it.image_base64,
        })),
        technician_id: collaboratorId,
        reason: "Retirada em massa via app do colaborador",
      });
      setMsg({
        type: "ok",
        text: `✓ ${r.total} ONT${r.total !== 1 ? "s" : ""} adicionada${r.total !== 1 ? "s" : ""} ao seu estoque (${r.created.length} novas, ${r.moved.length} movidas).`,
      });
      setShowBatchScan(false);
      reload();
    } catch (e) {
      setMsg({
        type: "err",
        text: "Erro ao salvar: " + (e?.response?.data?.detail || e.message),
      });
    }
  }, [collaboratorId, reload]);

  const pending = data.items.filter((a) => !a.signed_at && a.status === "ativo");
  // Separa novos (entrada por nota/almoxarife) de retirados (de cliente via OS)
  const RETIRADO_SOURCES = new Set(["retirada", "ai_scan_retirada", "ai_scan_batch"]);
  const novosItems = data.items.filter((a) => !RETIRADO_SOURCES.has(a.source));
  const retiradosItems = data.items.filter((a) => RETIRADO_SOURCES.has(a.source));
  // iter183 — aba "Todos" mostra o estoque inteiro pra visualização rápida
  const visibleItems = assetTab === "todos" ? data.items
                       : assetTab === "retirados" ? retiradosItems
                       : novosItems;

  const downloadRomaneio = () => {
    const url = api.publicRomaneioUrl(collaboratorId, false);
    window.open(url, "_blank");
  };

  return (
    <BottomSheet open onClose={onClose} testid="my-assets-modal">
      <div style={{ padding: "8px 18px 0" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: "#0f172a" }}>Meu estoque</h2>
          <button onClick={onClose} data-testid="assets-close-btn"
                  style={{ background: "transparent", border: 0, fontSize: 22,
                           cursor: "pointer", color: "#64748b" }}>✕</button>
        </div>

        <div style={{
          padding: 12, background: "#f8fafc", borderRadius: 12, marginBottom: 12,
          fontSize: 12, color: "#64748b",
        }}>
          <div style={{ fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>
            {data.items.length} item{data.items.length === 1 ? "" : "s"} no seu estoque
          </div>
          {/* Resumo por status — iter183 */}
          {data.items.length > 0 && (() => {
            const byStatus = data.items.reduce((acc, a) => {
              acc[a.status || "ativo"] = (acc[a.status || "ativo"] || 0) + 1;
              return acc;
            }, {});
            const totalValue = data.items
              .filter((a) => a.status === "ativo" && a.unit_value_brl != null)
              .reduce((s, a) => s + a.unit_value_brl * (a.qty || 1), 0);
            return (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6,
                              marginBottom: 6 }}>
                {Object.entries(byStatus).map(([st, n]) => {
                  const stCfg = STATUS_LABEL[st] || STATUS_LABEL.ativo;
                  return (
                    <span key={st}
                          style={{ padding: "3px 8px", borderRadius: 999,
                                     background: stCfg.bg, color: stCfg.color,
                                     fontSize: 10, fontWeight: 800 }}>
                      {stCfg.label}: {n}
                    </span>
                  );
                })}
                {totalValue > 0 && (
                  <span style={{ padding: "3px 8px", borderRadius: 999,
                                   background: "#fae8ff", color: "#86198f",
                                   fontSize: 10, fontWeight: 800 }}>
                    R$ {totalValue.toFixed(2).replace(".", ",")}
                  </span>
                )}
              </div>
            );
          })()}
          {pending.length > 0 && (
            <div style={{ marginTop: 6, color: "#92400e", fontWeight: 700 }}>
              ⏳ {pending.length} item(ns) aguardando sua assinatura
            </div>
          )}
        </div>

        {/* Botão de retirada em lote (IA) — só gestor/admin */}
        {(role === "gestor" || role === "administrador" || role === "admin"
            || data.collaborator?.role === "gestor"
            || data.collaborator?.role === "administrador"
            || data.collaborator?.role === "Administrador") && (
          <button
            data-testid="open-batch-scan-btn"
            onClick={() => setShowBatchScan(true)}
            style={{
              width: "100%", padding: "12px 14px", marginBottom: 14,
              border: 0, borderRadius: 12, cursor: "pointer",
              background: "linear-gradient(135deg,#0d9488,#06b6d4)",
              color: "#fff", fontWeight: 800, fontSize: 13,
              display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              boxShadow: "0 4px 12px rgba(13,148,136,.3)",
            }}>
            Adicionar várias ONTs (Scan IA em lote)
          </button>
        )}

        {pending.length > 0 && (
          <div data-testid="pending-banner" style={{
            background: "linear-gradient(135deg,#fde68a,#fbbf24)",
            padding: 14, borderRadius: 14, marginBottom: 14,
          }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: "#78350f", marginBottom: 6 }}>
              Assine o romaneio
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

        {/* Tabs Todos / Pertences / ONTs / Insumos / Retirados */}
        <div data-testid="assets-tabs" style={{
          display: "flex", gap: 4, marginBottom: 12, flexWrap: "wrap",
        }}>
          {[
            { key: "todos", label: `Todos`, count: data.items.length
                                                  + techStock.onts.length
                                                  + techStock.consumables.filter((c) => c.qty > 0).length,
              color: "#0f172a", grad: "#475569" },
            { key: "novos", label: `Pertences`, count: novosItems.length,
              color: "#0d9488", grad: "#06b6d4" },
            { key: "onts", label: `ONTs`, count: techStock.onts.length,
              color: "#2563eb", grad: "#0ea5e9" },
            { key: "insumos", label: `Insumos`,
              count: techStock.consumables.filter((c) => c.qty > 0).length,
              color: "#a16207", grad: "#eab308" },
            { key: "retirados", label: `️ Retirados`, count: retiradosItems.length,
              color: "#8b5cf6", grad: "#6366f1" },
          ].map((t) => (
            <button key={t.key}
              data-testid={`assets-tab-${t.key}`}
              onClick={() => setAssetTab(t.key)}
              style={{
                flex: "1 1 30%", padding: "8px 4px", borderRadius: 10,
                border: "1px solid " + (assetTab === t.key ? t.color : "#e2e8f0"),
                background: assetTab === t.key
                  ? `linear-gradient(135deg,${t.color},${t.grad})` : "white",
                color: assetTab === t.key ? "#fff" : "#0f172a",
                fontWeight: 800, fontSize: 11, cursor: "pointer",
                minHeight: 38,
              }}>
              {t.label} ({t.count})
            </button>
          ))}
        </div>

        {/* Lista um a um */}
        <div data-testid="assets-list">
          {/* iter183 — ONTs do stok */}
          {(assetTab === "onts" || assetTab === "todos") && techStock.onts.length > 0 && (
            <>
              {assetTab === "todos" && (
                <div style={{ fontSize: 11, fontWeight: 800, color: "#64748b",
                                margin: "6px 0", textTransform: "uppercase",
                                letterSpacing: 0.5 }}>
                  ONTs ({techStock.onts.length})
                </div>
              )}
              {techStock.onts.map((o, i) => (
                <div key={`ont-${o.mac || i}`}
                     data-testid={`my-ont-${o.mac || i}`}
                     style={{
                       padding: 12, marginBottom: 8, border: "1px solid #bfdbfe",
                       borderRadius: 12, background: "#eff6ff",
                       borderLeft: "4px solid #2563eb",
                       display: "flex", alignItems: "center", gap: 10,
                     }}>
                  <div style={{ fontSize: 22 }}></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {/* iter197 — SN é o identificador principal exibido */}
                    <div style={{ fontSize: 15, fontWeight: 800, color: "#1e3a8a",
                                    fontFamily: "monospace" }}>
                      {o.sn || o.scan_sn || (
                        /^(SN-|AUTOSN_|MANUAL-)/i.test(o.mac || "")
                          ? "— sem SN —"
                          : o.mac || "—"
                      )}
                    </div>
                    {(o.sn || o.scan_sn) && o.mac
                      && !/^(SN-|AUTOSN_|MANUAL-)/i.test(o.mac) && (
                      <div style={{ fontSize: 10, color: "#94a3b8",
                                      fontFamily: "monospace", marginTop: 1 }}>
                        MAC: {o.mac}
                      </div>
                    )}
                    <div style={{ fontSize: 11, color: "#475569" }}>
                      {o.model || "Modelo desconhecido"}
                    </div>
                  </div>
                  <span style={{ fontSize: 10, fontWeight: 800,
                                   padding: "3px 8px", borderRadius: 999,
                                   background: o.status?.startsWith("defeito") ? "#fef2f2" : "#dbeafe",
                                   color: o.status?.startsWith("defeito") ? "#991b1b" : "#1e40af" }}>
                    {(o.status || "estoque").replace(/_/g, " ")}
                  </span>
                </div>
              ))}
            </>
          )}

          {/* iter183 — Insumos/consumíveis do stok */}
          {(assetTab === "insumos" || assetTab === "todos") && techStock.consumables.filter((c) => c.qty > 0).length > 0 && (
            <>
              {assetTab === "todos" && (
                <div style={{ fontSize: 11, fontWeight: 800, color: "#64748b",
                                margin: "12px 0 6px", textTransform: "uppercase",
                                letterSpacing: 0.5 }}>
                  Insumos
                </div>
              )}
              {techStock.consumables.filter((c) => c.qty > 0).map((c) => (
                <div key={`cons-${c.id}`}
                     data-testid={`my-cons-${c.id}`}
                     style={{
                       padding: 12, marginBottom: 8, border: "1px solid #fde68a",
                       borderRadius: 12, background: "#fffbeb",
                       borderLeft: "4px solid #eab308",
                       display: "flex", alignItems: "center", gap: 10,
                     }}>
                  <div style={{ fontSize: 22 }}></div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: "#78350f" }}>
                      {c.name}
                    </div>
                  </div>
                  <div style={{ fontSize: 16, fontWeight: 900, color: "#a16207" }}>
                    {c.qty} {c.unit}
                  </div>
                </div>
              ))}
            </>
          )}

          {/* Itens em custódia (pertences, uniformes, etc) */}
          {(assetTab === "todos" || assetTab === "novos" || assetTab === "retirados") && visibleItems.length === 0
            && (assetTab === "novos" || assetTab === "retirados") ? (
            <div style={{ padding: 40, textAlign: "center", color: "#94a3b8", fontSize: 13 }}>
              {assetTab === "retirados"
                ? "Você não tem ONTs retiradas de clientes ainda."
                : "Nenhum pertence novo cadastrado em seu nome ainda."}
            </div>
          ) : null}
          {assetTab === "onts" && techStock.onts.length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "#94a3b8", fontSize: 13 }}>
              Você não tem ONTs no seu estoque.
            </div>
          )}
          {assetTab === "insumos" && techStock.consumables.filter((c) => c.qty > 0).length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "#94a3b8", fontSize: 13 }}>
              Você não tem insumos no seu estoque.
            </div>
          )}
          {assetTab === "todos" && data.items.length === 0
            && techStock.onts.length === 0
            && techStock.consumables.filter((c) => c.qty > 0).length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "#94a3b8", fontSize: 13 }}>
              Você não tem itens no estoque ainda.
            </div>
          )}
          {(assetTab === "todos" || assetTab === "novos" || assetTab === "retirados") && (
            <>
              {assetTab === "todos" && visibleItems.length > 0 && (
                <div style={{ fontSize: 11, fontWeight: 800, color: "#64748b",
                                margin: "12px 0 6px", textTransform: "uppercase",
                                letterSpacing: 0.5 }}>
                  Pertences ({visibleItems.length})
                </div>
              )}
              {visibleItems.map((a) => {
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
                    {CATEGORY_ICON[a.category] || ""} {a.item}
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
                  {a.withdrawn_from_client_name && (
                    <><br />️ Retirado de <strong>{a.withdrawn_from_client_name}</strong>
                      {a.withdrawn_at && ` em ${(a.withdrawn_at || "").slice(0, 10)}`}
                      {a.withdrawn_by_email && (
                        <em style={{ color: "#64748b" }}> · {a.withdrawn_by_email}</em>
                      )}
                    </>
                  )}
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
            </>
          )}
        </div>

        {data.items.length > 0 && (
          <Button variant="soft" onClick={downloadRomaneio}
                  data-testid="download-romaneio-btn"
                  style={{ width: "100%", marginTop: 12 }}>
            Imprimir / baixar romaneio
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
      <OntScanBatchModal
        open={showBatchScan}
        onClose={() => setShowBatchScan(false)}
        onSaved={onBatchSaved}
      />
    </BottomSheet>
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
    if (!hasInk) { await window.alert("Assine no quadro antes de confirmar."); return; }
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
      await window.alert(e?.response?.data?.detail || e.message);
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
