/* RompimentoCloseForm — fechamento de OS de rompimento.
 *
 * Fluxo simplificado: técnico descreve o serviço em texto livre.
 * IA (Claude Sonnet 4.5) identifica insumos e dá baixa no estoque
 * da praça (permite saldo negativo até gestor lançar entrada).
 *
 * UI minimalista: textarea grande + botão "Pré-visualizar IA" (opcional)
 * + botão "Finalizar OS". Sem CTO, sem foto, sem MAC.
 */
import React, { useEffect, useState } from "react";
import { Button, Icon } from "@/ui";
import { api } from "@/api";

export default function RompimentoCloseForm({ ticket, collaboratorId,
                                                 onClose, onFinalized }) {
  const [reportText, setReportText] = useState("");
  const [observacoes, setObservacoes] = useState("");
  const [preview, setPreview] = useState(null); // {items, summary}
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // OSes individuais do colaborador que podem ser fechadas em lote junto
  const [related, setRelated] = useState([]);
  const [linkedIds, setLinkedIds] = useState([]);
  const [loadingRelated, setLoadingRelated] = useState(true);
  // iter215: sugestão da IA Claude — quais notas devem ser vinculadas
  const [suggesting, setSuggesting] = useState(false);
  const [reasoning, setReasoning] = useState({});  // {ticketId: motivo}
  const cs = ticket?.client_snapshot || {};

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api._client.get(
          `/lousa/public/tickets/${ticket.id}/related-open`,
          { params: { collaborator_id: collaboratorId } },
        );
        if (!cancelled) setRelated(r.data?.items || []);
      } catch {
        if (!cancelled) setRelated([]);
      } finally {
        if (!cancelled) setLoadingRelated(false);
      }
    })();
    return () => { cancelled = true; };
  }, [ticket.id, collaboratorId]);

  function toggleLinked(id) {
    setLinkedIds((cur) => cur.includes(id)
      ? cur.filter((x) => x !== id)
      : [...cur, id]);
  }

  async function suggestWithAI() {
    if (related.length === 0) return;
    setSuggesting(true);
    try {
      const r = await api._client.post(
        `/lousa/public/tickets/${ticket.id}/rompimento/suggest-links`,
        {
          collaborator_id: collaboratorId,
          report_text: reportText || null,
        },
      );
      const suggested = r.data?.suggested_ids || [];
      const reason = r.data?.reasoning || {};
      // Merge: mantém marcações manuais do técnico + adiciona sugestões da IA
      setLinkedIds((cur) => Array.from(new Set([...cur, ...suggested])));
      setReasoning(reason);
      if (suggested.length === 0) {
        await window.alert("IA analisou e não encontrou notas relacionadas ao rompimento.");
      }
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message;
      await window.alert("Falha na IA: " + msg);
    }
    setSuggesting(false);
  }

  async function previewItems() {
    setErr("");
    if (reportText.trim().length < 5) {
      setErr("Descreva o serviço em ao menos 5 caracteres.");
      return;
    }
    setBusy(true);
    try {
      const r = await api._client.post(
        "/lousa/public/rompimento/parse-preview",
        { report_text: reportText },
      );
      setPreview(r.data);
    } catch (e) {
      setErr("Falha na IA: " + (e?.response?.data?.detail || e.message));
    }
    setBusy(false);
  }

  async function finalize() {
    setErr("");
    if (reportText.trim().length < 5) {
      setErr("Descreva o serviço em ao menos 5 caracteres.");
      return;
    }
    if (!await window.confirm(
      "Confirmar fechamento da OS?\n\n" +
        "A IA vai ler seu relato e dar baixa nos insumos no estoque da praça. " +
        "Caso o saldo fique negativo, o gestor será notificado para regularizar.",
    )) return;
    setBusy(true);
    let lat = null;
    let lng = null;
    try {
      const pos = await new Promise((res) => {
        if (!navigator.geolocation) return res(null);
        navigator.geolocation.getCurrentPosition(
          (p) => res(p), () => res(null),
          { enableHighAccuracy: true, timeout: 8000 });
      });
      if (pos?.coords) {
        lat = pos.coords.latitude;
        lng = pos.coords.longitude;
      }
    } catch { /* ignore */ }
    try {
      const r = await api._client.post(
        `/lousa/public/tickets/${ticket.id}/rompimento-finalize`,
        {
          collaborator_id: collaboratorId,
          report_text: reportText,
          observacoes: observacoes || null,
          latitude: lat, longitude: lng,
          linked_ticket_ids: linkedIds,
        },
      );
      const items = r.data?.items || [];
      const shortages = r.data?.shortages || [];
      const linkedOk = r.data?.linked_count_ok || 0;
      let msg = "✅ OS finalizada!\n\n";
      if (items.length) {
        msg += "Insumos identificados pela IA:\n";
        items.forEach((i) => {
          msg += `• ${i.name}: ${i.quantity} ${i.unit}\n`;
        });
      } else {
        msg += "Nenhum insumo identificado no relato.\n";
      }
      if (linkedOk > 0) {
        msg += `\n${linkedOk} nota(s) individual(is) fechada(s) em lote.\n`;
      }
      if (shortages.length) {
        msg += "\n️ Saldo negativo na praça (gestor foi notificado):\n";
        shortages.forEach((s) => {
          msg += `• ${s.name}: ${s.deficit} ${s.unit}\n`;
        });
      }
      await window.alert(msg);
      if (onFinalized) onFinalized();
      if (onClose) onClose();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      const msg = typeof detail === "object"
        ? (detail?.message || JSON.stringify(detail))
        : (detail || e.message);
      setErr("Falha ao finalizar: " + msg);
    }
    setBusy(false);
  }

  return (
    <div data-testid="rompimento-close-form"
          style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button variant="soft" onClick={onClose}
                data-testid="rompimento-back-btn">← Voltar</Button>
        <div style={{ marginLeft: "auto", fontSize: 11, color: "#64748b" }}>
          OS {ticket.id.slice(-6)}
        </div>
      </div>

      {/* Cabeçalho contextual (cliente + endereço) */}
      <div style={{
        background: "linear-gradient(135deg,#0f172a 0%,#1e293b 100%)",
        color: "white", padding: 14, borderRadius: 12,
      }}>
        <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 4 }}>
          ROMPIMENTO DE REDE
        </div>
        <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 4 }}>
          {cs.name || "—"}
        </div>
        <div style={{ fontSize: 12, opacity: 0.85 }}>
          {cs.address || "—"}
          {cs.neighborhood ? ` · ${cs.neighborhood}` : ""}
        </div>
        {cs.relato && (
          <div style={{
            marginTop: 10, padding: 10,
            background: "rgba(255,255,255,0.07)", borderRadius: 8,
            fontSize: 12, lineHeight: 1.5,
          }}>
            <strong>Relato do cliente:</strong> {cs.relato}
          </div>
        )}
      </div>

      <div style={{
        background: "#fef3c7", border: "1.5px solid #f59e0b",
        borderRadius: 10, padding: 12, fontSize: 12, lineHeight: 1.5,
        color: "#78350f",
      }}>
        <strong>ℹ️ Como funciona:</strong> Descreva em texto o que você fez
        (cabos, conectores, esticadores, fibras…). A IA <strong>Claude 4.5</strong>
        {" "}vai identificar os insumos e dar baixa no estoque da sua praça.
        Se faltar saldo, o gestor recebe um alerta para regularizar.
      </div>

      <label style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
        Relato do serviço executado *
      </label>
      <textarea
        data-testid="rompimento-report-text"
        value={reportText}
        onChange={(e) => { setReportText(e.target.value); setPreview(null); }}
        rows={7}
        placeholder={
          "Ex: 'Atendi rompimento no poste 12 da rua X. Passei 80m de drop "
          + "novo, troquei 2 conectores fast e usei 3 esticadores. "
          + "Reemendei 5m de fibra 12FO.'"
        }
        style={{
          width: "100%", padding: 12, border: "1.5px solid #cbd5e1",
          borderRadius: 10, fontSize: 14, fontFamily: "inherit",
          resize: "vertical", boxSizing: "border-box",
        }}
      />

      {preview && (
        <div data-testid="rompimento-ai-preview"
              style={{
                background: "#ecfdf5", border: "1.5px solid #10b981",
                borderRadius: 10, padding: 12,
              }}>
          <div style={{ fontWeight: 800, fontSize: 13, color: "#065f46",
                          marginBottom: 8 }}>
            IA identificou {preview.items.length} insumo
            {preview.items.length !== 1 ? "s" : ""}:
          </div>
          {preview.items.length === 0 ? (
            <div style={{ fontSize: 12, color: "#065f46", fontStyle: "italic" }}>
              Nenhum insumo identificado no relato. Será fechado sem baixa.
            </div>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "#065f46" }}>
              {preview.items.map((i, idx) => (
                <li key={idx} style={{ marginBottom: 4 }}>
                  <strong>{i.name}</strong>: {i.quantity} {i.unit}
                  <span style={{ marginLeft: 6, fontSize: 10, color: "#047857",
                                   padding: "1px 6px", background: "rgba(16,185,129,0.15)",
                                   borderRadius: 4 }}>
                    {(i.confidence * 100).toFixed(0)}%
                  </span>
                </li>
              ))}
            </ul>
          )}
          {preview.summary && (
            <div style={{ marginTop: 8, fontSize: 11, color: "#065f46",
                            fontStyle: "italic", borderTop: "1px solid #6ee7b7",
                            paddingTop: 8 }}>
              <strong>Resumo IA:</strong> {preview.summary}
            </div>
          )}
        </div>
      )}

      <label style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
        Observações adicionais (opcional)
      </label>
      <textarea
        data-testid="rompimento-observations"
        value={observacoes}
        onChange={(e) => setObservacoes(e.target.value)}
        rows={2}
        placeholder="Ex: alinhei caixa, comuniquei moradores, etc."
        style={{
          width: "100%", padding: 10, border: "1px solid #cbd5e1",
          borderRadius: 10, fontSize: 13, fontFamily: "inherit",
          resize: "vertical", boxSizing: "border-box",
        }}
      />

      {/* Vinculação de notas individuais — iter215 */}
      <div data-testid="rompimento-linked-section"
            style={{
              border: "1.5px solid #cbd5e1", borderRadius: 12,
              padding: 10, background: "#f8fafc",
            }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8,
                          marginBottom: 6 }}>
          <div style={{ fontSize: 12, color: "#0f172a", fontWeight: 800, flex: 1 }}>
            Vincular notas afetadas pelo rompimento
          </div>
          {related.length > 0 && (
            <button type="button"
                    data-testid="rompimento-ai-suggest-btn"
                    onClick={suggestWithAI} disabled={suggesting}
                    style={{
                      border: 0, borderRadius: 999,
                      padding: "6px 12px", fontSize: 11, fontWeight: 800,
                      background: suggesting
                        ? "#cbd5e1"
                        : "linear-gradient(135deg,#7c3aed,#a855f7)",
                      color: "white", cursor: suggesting ? "wait" : "pointer",
                      boxShadow: "0 2px 6px rgba(124,58,237,0.4)",
                    }}>
              {suggesting ? "Analisando…" : "IA sugerir"}
            </button>
          )}
        </div>
        <div style={{ fontSize: 11, color: "#475569",
                          lineHeight: 1.5, marginBottom: 8 }}>
          Marque as notas individuais que foram causadas por este rompimento.
          Elas serão <strong>fechadas em lote</strong> junto com esta OS,
          evitando que sejam tratadas individualmente.
        </div>
        {loadingRelated ? (
          <div style={{ fontSize: 11, color: "#64748b" }}>Carregando suas notas abertas…</div>
        ) : related.length === 0 ? (
          <div style={{ fontSize: 11, color: "#94a3b8", fontStyle: "italic" }}>
            Sem outras notas abertas atribuídas a você.
          </div>
        ) : (
          <div style={{
            display: "flex", flexDirection: "column", gap: 6,
            maxHeight: 240, overflowY: "auto",
          }}>
            {related.map((r) => {
              const checked = linkedIds.includes(r.id);
              const aiReason = reasoning[r.id];
              return (
                <label
                  key={r.id}
                  data-testid={`rompimento-linked-item-${r.id}`}
                  style={{
                    display: "flex", alignItems: "flex-start", gap: 8,
                    padding: 8, borderRadius: 8,
                    background: checked
                      ? (aiReason ? "#ede9fe" : "#dbeafe")
                      : "white",
                    border: `1px solid ${
                      checked ? (aiReason ? "#7c3aed" : "#3b82f6") : "#e2e8f0"
                    }`,
                    cursor: "pointer",
                  }}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleLinked(r.id)}
                    data-testid={`rompimento-linked-checkbox-${r.id}`}
                    style={{ marginTop: 3, width: 18, height: 18,
                                 cursor: "pointer", accentColor: "#2563eb" }}
                  />
                  <div style={{ flex: 1, minWidth: 0, fontSize: 12 }}>
                    <div style={{ fontWeight: 700, color: "#0f172a",
                                      whiteSpace: "nowrap", overflow: "hidden",
                                      textOverflow: "ellipsis",
                                      display: "flex", gap: 6, alignItems: "center" }}>
                      <span style={{ flex: 1, overflow: "hidden",
                                         textOverflow: "ellipsis" }}>
                        {r.client_name || "(sem nome)"}
                      </span>
                      {aiReason && (
                        <span title={aiReason}
                              style={{
                                fontSize: 9, padding: "1px 7px",
                                borderRadius: 999, background: "#7c3aed",
                                color: "white", fontWeight: 800,
                                whiteSpace: "nowrap",
                              }}>
                          IA
                        </span>
                      )}
                    </div>
                    {r.pppoe_user && (
                      <div style={{
                        marginTop: 2,
                        display: "inline-block",
                        padding: "1px 8px",
                        borderRadius: 4,
                        background: "#0f172a", color: "#22d3ee",
                        fontFamily: "monospace", fontSize: 10.5,
                      }}>
                        {r.pppoe_user}
                      </div>
                    )}
                    <div style={{ color: "#64748b", fontSize: 11,
                                      marginTop: 2 }}>
                      {r.type} · {r.neighborhood || r.address || "—"}
                    </div>
                    {r.relato && (
                      <div style={{ color: "#475569", fontSize: 10.5,
                                        marginTop: 2, fontStyle: "italic" }}>
                        “{r.relato}”
                      </div>
                    )}
                    {aiReason && (
                      <div style={{ color: "#6b21a8", fontSize: 10.5,
                                        marginTop: 4, fontWeight: 700 }}>
                        {aiReason}
                      </div>
                    )}
                  </div>
                </label>
              );
            })}
          </div>
        )}
        {linkedIds.length > 0 && (
          <div style={{
            marginTop: 8, padding: "6px 10px",
            background: "#3b82f6", color: "white",
            borderRadius: 8, fontSize: 11, fontWeight: 800,
          }} data-testid="rompimento-linked-counter">
            {linkedIds.length} nota{linkedIds.length === 1 ? "" : "s"} vinculada{linkedIds.length === 1 ? "" : "s"} ao rompimento
          </div>
        )}
      </div>

      {err && (
        <div data-testid="rompimento-error"
              style={{
                background: "#fee2e2", color: "#991b1b",
                border: "1.5px solid #fca5a5", borderRadius: 10,
                padding: 10, fontSize: 12,
              }}>
          ️ {err}
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <Button
          data-testid="rompimento-preview-btn"
          variant="soft"
          onClick={previewItems}
          disabled={busy || reportText.trim().length < 5}
          style={{ flex: 1, height: 52, fontSize: 14 }}>
          {busy ? "Analisando…" : "Pré-visualizar IA"}
        </Button>
        <Button
          data-testid="rompimento-finalize-btn"
          onClick={finalize}
          disabled={busy || reportText.trim().length < 5}
          style={{ flex: 2, height: 52, fontSize: 15 }}>
          <Icon name="check" />{" "}
          {busy ? "Finalizando…"
            : linkedIds.length > 0
              ? `Finalizar + ${linkedIds.length} vínculo${linkedIds.length === 1 ? "" : "s"}`
              : "Finalizar rompimento"}
        </Button>
      </div>
    </div>
  );
}
