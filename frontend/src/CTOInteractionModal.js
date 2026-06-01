/*
CTOInteractionModal.js — Modal acionado ao clicar numa CTO no mapa da Rede IA.

2 abas:
  • Clientes ligados — lista ONUs com sinal, slot, status
  • Cadastrar novo  — provisiona nova ONU no slot livre + push pro SmartOLT

Usado em RedeIaMap.js.
*/
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Field, inputStyle } from "@/ui";
import {
  X, Users, Plus, Signal, MapPin, Loader2, CheckCircle2,
  AlertCircle, Search, Camera, ArrowLeftRight,
} from "lucide-react";

function statusColor(s) {
  const k = (s || "").toLowerCase();
  if (k === "online" || k === "ok") return "#16a34a";
  if (k === "warning") return "#ca8a04";
  if (k === "critical" || k === "alarm" || k === "los") return "#dc2626";
  if (k === "provisioning") return "#6366f1";
  return "#64748b";
}

export default function CTOInteractionModal({ ctoId, ctoMeta, onClose }) {
  const [tab, setTab] = useState("clients");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.redeIaCtoClients(ctoId);
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [ctoId]);

  return (
    <div onClick={onClose}
           data-testid="cto-modal"
           style={{
             position: "fixed", inset: 0, zIndex: 9999,
             background: "rgba(0,0,0,0.55)",
             display: "flex", alignItems: "center", justifyContent: "center",
             padding: 12,
           }}>
      <div onClick={(e) => e.stopPropagation()}
             style={{
               background: "#fff", borderRadius: 14,
               width: "min(820px, 100%)", maxHeight: "90vh",
               display: "flex", flexDirection: "column",
               boxShadow: "0 18px 50px rgba(0,0,0,0.35)",
             }}>
        {/* Header */}
        <div style={{ padding: "14px 18px",
                        borderBottom: "1px solid #e2e8f0",
                        display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 9,
            background: "linear-gradient(135deg,#6366f1,#8b5cf6)",
            display: "grid", placeItems: "center", color: "#fff",
          }}>
            <MapPin size={18} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>
              {data?.cto?.name || ctoMeta?.name || "CTO"}
            </div>
            <div style={{ fontSize: 11, color: "#64748b" }}>
              {data?.cto?.sigla ? `Sigla: ${data.cto.sigla} · ` : ""}
              Capacidade: {data?.cto?.capacity || ctoMeta?.capacity || "—"}
              {data ? ` · ${data.total_clients} ocupado(s) · ${data.free_count} livre(s)` : ""}
            </div>
          </div>
          <button onClick={onClose}
                    data-testid="cto-modal-close"
                    style={{
                      padding: 6, border: "1px solid #e2e8f0",
                      background: "#fff", borderRadius: 8, cursor: "pointer",
                    }}><X size={16} /></button>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0" }}>
          {[
            { id: "clients", label: "Clientes ligados", icon: Users },
            { id: "photos",  label: "Histórico de fotos", icon: Camera },
            { id: "swaps",   label: "Trocas de porta", icon: ArrowLeftRight },
            { id: "new",     label: "Cadastrar novo cliente", icon: Plus },
          ].map((t) => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <button key={t.id}
                        onClick={() => setTab(t.id)}
                        data-testid={`cto-tab-${t.id}`}
                        style={{
                          flex: 1, padding: "12px 14px", border: 0,
                          background: "transparent", cursor: "pointer",
                          fontSize: 13, fontWeight: active ? 700 : 500,
                          color: active ? "#7c3aed" : "#64748b",
                          borderBottom: "2px solid " + (active ? "#7c3aed" : "transparent"),
                          display: "inline-flex", justifyContent: "center",
                          alignItems: "center", gap: 6,
                        }}>
                <Icon size={14} /> {t.label}
              </button>
            );
          })}
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
          {err && (
            <div style={{ padding: 10, background: "#fef2f2", color: "#991b1b",
                            borderRadius: 8, fontSize: 12, marginBottom: 10 }}>
              {err}
            </div>
          )}
          {loading ? (
            <div style={{ padding: 24, textAlign: "center", color: "#64748b" }}>
              <Loader2 size={16} className="animate-spin" /> Carregando…
            </div>
          ) : tab === "clients" ? (
            <ClientsList data={data} />
          ) : tab === "photos" ? (
            <CTOPhotosTab ctoId={ctoId} />
          ) : tab === "swaps" ? (
            <CTOPortSwapsTab ctoId={ctoId} />
          ) : (
            <ProvisionForm cto={data?.cto} ctoId={ctoId}
                              freeSlots={data?.free_slots || []}
                              onCreated={async () => { await load(); setTab("clients"); }} />
          )}
        </div>
      </div>
    </div>
  );
}

function CTOPhotosTab({ ctoId }) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [err, setErr] = React.useState("");
  const [zoom, setZoom] = React.useState(null);
  const [zoomIndex, setZoomIndex] = React.useState(null);
  const [analysis, setAnalysis] = React.useState(null);
  const [analyzing, setAnalyzing] = React.useState(false);
  const [analyzeErr, setAnalyzeErr] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true); setErr("");
      try {
        const r = await api.redeIaCtoPhotos(ctoId);
        if (alive) setData(r);
      } catch (e) {
        if (alive) setErr(e?.response?.data?.detail || e.message || "Erro");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [ctoId]);

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "#64748b" }}>
        <Loader2 size={16} className="animate-spin" /> Carregando fotos…
      </div>
    );
  }
  if (err) {
    return (
      <div style={{ padding: 12, background: "#fef2f2", color: "#991b1b",
                      borderRadius: 8, fontSize: 12 }}>{err}</div>
    );
  }
  if (!data || !data.photos?.length) {
    return (
      <div data-testid="cto-photos-empty"
            style={{ padding: 24, textAlign: "center", color: "#94a3b8",
                      fontSize: 13 }}>
        Nenhuma foto registrada para esta CTO ainda.
        <div style={{ fontSize: 11, marginTop: 6 }}>
          As fotos aparecem aqui quando técnicos finalizarem OSs com vínculo
          a esta CTO.
        </div>
      </div>
    );
  }

  const fmt = (iso) => {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
    } catch { return iso; }
  };

  return (
    <div data-testid="cto-photos-list">
      <div style={{ fontSize: 12, color: "#64748b", marginBottom: 10 }}>
        {data.total} foto{data.total > 1 ? "s" : ""} registrada{data.total > 1 ? "s" : ""}.
      </div>
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                      gap: 12 }}>
        {data.photos.map((p, i) => (
          <div key={i} data-testid={`cto-photo-${i}`}
                onClick={() => { setZoom(p); setZoomIndex(i); setAnalysis(null); setAnalyzeErr(""); }}
                style={{ borderRadius: 10, overflow: "hidden",
                          border: "1px solid #e2e8f0",
                          background: "#fff", cursor: "pointer",
                          transition: "transform 120ms ease, box-shadow 120ms",
                        }}
                onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-2px)";
                                          e.currentTarget.style.boxShadow = "0 8px 20px rgba(0,0,0,0.08)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)";
                                          e.currentTarget.style.boxShadow = "none"; }}>
            <div style={{ position: "relative", aspectRatio: "1/1",
                            background: "#f1f5f9" }}>
              <img src={p.data_url} alt={`Foto ${i+1}`}
                    style={{ width: "100%", height: "100%",
                              objectFit: "cover", display: "block" }} />
              <div style={{ position: "absolute", top: 6, left: 6,
                              padding: "2px 7px", borderRadius: 999,
                              background: p.source === "cadastro_inicial"
                                  ? "#6366f1" : "#0f766e",
                              color: "#fff", fontSize: 9, fontWeight: 800 }}>
                {p.source === "cadastro_inicial" ? "Cadastro" : "OS"}
              </div>
            </div>
            <div style={{ padding: 8, fontSize: 10, color: "#475569",
                            lineHeight: 1.4 }}>
              <div style={{ fontWeight: 700, color: "#0f172a" }}>
                {fmt(p.captured_at)}
              </div>
              {p.technician_name && (
                <div>👷 {p.technician_name}</div>
              )}
              {p.client_name && (
                <div>👤 {p.client_name}</div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Lightbox */}
      {zoom && (
        <div onClick={() => { setZoom(null); setZoomIndex(null); }}
              data-testid="cto-photo-lightbox"
              style={{ position: "fixed", inset: 0, zIndex: 10000,
                        background: "rgba(0,0,0,0.85)",
                        display: "flex", alignItems: "center",
                        justifyContent: "center", padding: 20,
                        cursor: "zoom-out" }}>
          <div onClick={(e) => e.stopPropagation()}
                style={{ maxWidth: "92vw", maxHeight: "92vh",
                          background: "#fff", borderRadius: 12,
                          overflow: "auto", display: "flex",
                          flexDirection: "column", cursor: "default",
                          position: "relative" }}>
            <img src={zoom.data_url} alt="Foto CTO"
                  style={{ maxWidth: "92vw", maxHeight: "60vh",
                            objectFit: "contain", background: "#000" }} />
            <div style={{ padding: 14, fontSize: 12, color: "#475569",
                            borderBottom: "1px solid #f1f5f9" }}>
              <div style={{ fontWeight: 700, color: "#0f172a", fontSize: 13 }}>
                {fmt(zoom.captured_at)}
              </div>
              <div style={{ marginTop: 4 }}>
                {zoom.technician_name && <span>👷 {zoom.technician_name}</span>}
                {zoom.client_name && <span> · 👤 {zoom.client_name}</span>}
                {zoom.ticket_id && <span> · OS {zoom.ticket_id.slice(0, 8)}</span>}
              </div>
            </div>

            {/* Bloco de análise IA */}
            <div style={{ padding: 14 }}>
              {!analysis && !analyzing && (
                <button data-testid="cto-photo-analyze-btn"
                        onClick={async () => {
                          setAnalyzing(true); setAnalyzeErr("");
                          try {
                            const r = await api.redeIaCtoPhotoAnalyze(ctoId, {
                              photo_index: zoomIndex,
                            });
                            setAnalysis(r);
                          } catch (e) {
                            setAnalyzeErr(e?.response?.data?.detail
                              || e.message || "Falha na análise");
                          } finally { setAnalyzing(false); }
                        }}
                        style={{ width: "100%", padding: "12px 14px",
                                  background: "linear-gradient(135deg,#7c3aed,#6366f1)",
                                  color: "#fff", border: 0, borderRadius: 10,
                                  fontSize: 13, fontWeight: 700,
                                  cursor: "pointer",
                                  display: "inline-flex", justifyContent: "center",
                                  alignItems: "center", gap: 8 }}>
                  🤖 Analisar foto com IA (Gemini Vision)
                </button>
              )}
              {analyzing && (
                <div style={{ padding: 12, textAlign: "center", color: "#64748b",
                                fontSize: 12 }}>
                  <Loader2 size={14} className="animate-spin" /> Analisando…
                </div>
              )}
              {analyzeErr && (
                <div style={{ padding: 10, background: "#fef2f2",
                                color: "#991b1b", borderRadius: 8,
                                fontSize: 12 }}>{analyzeErr}</div>
              )}
              {analysis && (
                <div data-testid="cto-photo-analysis-result">
                  <div style={{ display: "flex", justifyContent: "space-between",
                                  alignItems: "center", marginBottom: 8 }}>
                    <div style={{ fontWeight: 800, fontSize: 13, color: "#0f172a",
                                    display: "flex", alignItems: "center", gap: 6 }}>
                      🤖 Análise da IA
                      {analysis.cached && (
                        <span style={{ fontSize: 9, padding: "2px 6px",
                                        borderRadius: 999, background: "#e0e7ff",
                                        color: "#4338ca", fontWeight: 700 }}>cache</span>
                      )}
                    </div>
                    <div style={{
                      padding: "3px 10px", borderRadius: 999,
                      fontSize: 11, fontWeight: 800, color: "#fff",
                      background: analysis.severity >= 70 ? "#dc2626"
                                  : analysis.severity >= 40 ? "#ea580c"
                                  : analysis.severity >= 15 ? "#ca8a04"
                                  : "#16a34a",
                    }}>
                      Severidade {analysis.severity}
                    </div>
                  </div>
                  <div style={{ fontSize: 13, color: "#0f172a", marginBottom: 8,
                                  lineHeight: 1.4 }}>
                    {analysis.summary || "—"}
                  </div>
                  {(analysis.tags || []).length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap",
                                    gap: 6, marginBottom: 10 }}>
                      {analysis.tags.map((tg) => (
                        <span key={tg}
                              style={{ padding: "3px 9px", borderRadius: 999,
                                        background: "#f1f5f9",
                                        color: "#334155",
                                        fontSize: 11, fontWeight: 600 }}>
                          {tg.replace(/_/g, " ")}
                        </span>
                      ))}
                    </div>
                  )}
                  {(analysis.recommendations || []).length > 0 && (
                    <div>
                      <div style={{ fontSize: 11, color: "#64748b",
                                      fontWeight: 700, marginBottom: 4,
                                      textTransform: "uppercase",
                                      letterSpacing: 0.5 }}>
                        Recomendações
                      </div>
                      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12,
                                    color: "#0f172a", lineHeight: 1.5 }}>
                        {analysis.recommendations.map((rec, i) => (
                          <li key={i}>{rec}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>

            <button onClick={() => { setZoom(null); setZoomIndex(null); }}
                    style={{ position: "absolute", top: 12, right: 12,
                              background: "rgba(255,255,255,.9)",
                              border: 0, borderRadius: "50%", width: 36,
                              height: 36, fontSize: 18, fontWeight: 800,
                              cursor: "pointer", zIndex: 1 }}>×</button>
          </div>
        </div>
      )}
    </div>
  );
}

function ClientsList({ data }) {
  if (!data) return null;
  if (!data.clients?.length) {
    return (
      <div style={{ padding: 24, textAlign: "center", fontSize: 13,
                      color: "#64748b" }}>
        Nenhum cliente ligado nesta CTO ainda. Use a aba <strong>Cadastrar
        novo cliente</strong> pra provisionar a primeira ONU.
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: 8 }} data-testid="cto-clients-list">
      {data.clients.map((c, i) => (
        <div key={c.sn || i}
               data-testid={`cto-client-${c.sn || i}`}
               style={{
                 padding: 11, borderRadius: 10,
                 border: "1px solid #e2e8f0",
                 background: "#fff",
                 display: "grid",
                 gridTemplateColumns: "auto 1fr auto auto",
                 gap: 10, alignItems: "center",
               }}>
          <div style={{
            minWidth: 30, textAlign: "center",
            fontSize: 10, fontWeight: 800,
            padding: "3px 7px", borderRadius: 4,
            background: "#f1f5f9", color: "#475569",
          }}>SLOT {c.slot ?? "?"}</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 13, color: "#0f172a" }}>
              {c.name}
            </div>
            <div style={{ fontSize: 11, color: "#64748b" }}>
              SN: <code>{c.sn || "—"}</code>
              {c.olt_name ? ` · ${c.olt_name} B${c.board}/P${c.port}` : ""}
            </div>
          </div>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            fontSize: 12, fontWeight: 600,
            color: statusColor(c.signal_status),
          }}>
            <Signal size={12} />
            {c.signal_dbm != null ? `${c.signal_dbm} dBm` : "—"}
          </div>
          <span style={{
            padding: "2px 8px", borderRadius: 8,
            fontSize: 10, fontWeight: 700, textTransform: "uppercase",
            background: statusColor(c.status) + "1a",
            color: statusColor(c.status),
          }}>{c.status || "—"}</span>
        </div>
      ))}
    </div>
  );
}

function ProvisionForm({ cto, ctoId, freeSlots, onCreated }) {
  const [form, setForm] = useState({
    sn: "", customer_name: "", customer_external_id: "",
    plan_id: "", plan_name: "",
    slot: freeSlots[0] || "",
    pppoe_user: "", pppoe_pwd: "",
    vlan: "", notes: "",
  });
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  // Autocomplete de cliente Atlaz
  useEffect(() => {
    const q = (form.customer_name || "").trim();
    if (q.length < 3 || form.customer_external_id) {
      setResults([]); return;
    }
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const r = await api._client.get(
          `/atlaz/clients?q=${encodeURIComponent(q)}&limit=8`,
        ).then((x) => x.data);
        setResults(Array.isArray(r) ? r : (r.clients || []));
      } catch {
        setResults([]);
      } finally { setSearching(false); }
    }, 350);
    return () => clearTimeout(t);
  }, [form.customer_name, form.customer_external_id]);

  const pickCustomer = (c) => {
    setForm((s) => ({
      ...s,
      customer_name: c.name || c.full_name || "",
      customer_external_id: String(c.external_id || c.id || ""),
      plan_id: c.plan_id || s.plan_id,
      plan_name: c.plan_name || s.plan_name,
    }));
    setResults([]);
  };

  const canSubmit = form.sn.trim().length >= 4
    && form.customer_name.trim().length >= 2
    && Number(form.slot) >= 1;

  const submit = async () => {
    setSubmitting(true); setResult(null);
    try {
      const r = await api.redeIaCtoProvision(ctoId, {
        sn: form.sn.trim().toUpperCase(),
        customer_name: form.customer_name.trim(),
        customer_external_id: form.customer_external_id || null,
        plan_id: form.plan_id || null,
        plan_name: form.plan_name || null,
        slot: Number(form.slot),
        pppoe_user: form.pppoe_user || null,
        pppoe_pwd: form.pppoe_pwd || null,
        vlan: form.vlan ? Number(form.vlan) : null,
        notes: form.notes || null,
      });
      setResult({ ok: true, ...r });
      setTimeout(() => onCreated?.(), 1200);
    } catch (e) {
      setResult({
        ok: false,
        error: e?.response?.data?.detail || e.message,
      });
    } finally { setSubmitting(false); }
  };

  return (
    <div style={{ display: "grid", gap: 14 }} data-testid="cto-provision-form">
      <div style={{ padding: 10,
                      background: "#eef2ff", borderRadius: 8,
                      fontSize: 11.5, color: "#3730a3" }}>
        💡 <strong>CTO:</strong> {cto?.name} · Slots livres: {freeSlots.length}
        {freeSlots.length > 0 && (
          <div style={{ marginTop: 4, fontSize: 10.5 }}>
            Próximos: {freeSlots.slice(0, 10).join(", ")}
            {freeSlots.length > 10 ? "…" : ""}
          </div>
        )}
      </div>

      <div style={{ display: "grid",
                      gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="SN / MAC da ONU *">
          <input type="text" value={form.sn}
                   onChange={(e) => setForm((s) => ({ ...s, sn: e.target.value }))}
                   data-testid="prov-sn-input"
                   placeholder="HWTC1A2B3C4D"
                   style={{ ...inputStyle, fontFamily: "JetBrains Mono, monospace",
                              textTransform: "uppercase" }} />
        </Field>
        <Field label="Slot da CTO *">
          <select value={form.slot}
                    onChange={(e) => setForm((s) => ({ ...s, slot: e.target.value }))}
                    data-testid="prov-slot-select"
                    style={inputStyle}>
            <option value="">Selecione…</option>
            {freeSlots.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </Field>
      </div>

      <div style={{ position: "relative" }}>
        <Field label="Cliente Atlaz *">
          <div style={{ position: "relative" }}>
            <input type="text" value={form.customer_name}
                     onChange={(e) => {
                       setForm((s) => ({ ...s, customer_name: e.target.value,
                                          customer_external_id: "" }));
                     }}
                     data-testid="prov-customer-input"
                     placeholder="Digite o nome…"
                     style={{ ...inputStyle, paddingRight: 28 }} />
            {searching ? (
              <Loader2 size={14} className="animate-spin"
                          style={{ position: "absolute", right: 8, top: 10,
                                    color: "#94a3b8" }} />
            ) : (
              <Search size={14}
                        style={{ position: "absolute", right: 8, top: 10,
                                  color: "#94a3b8" }} />
            )}
          </div>
        </Field>
        {results.length > 0 && (
          <div style={{
            position: "absolute", top: "100%", left: 0, right: 0,
            zIndex: 10, background: "#fff",
            border: "1px solid #cbd5e1", borderRadius: 8,
            maxHeight: 220, overflow: "auto",
            boxShadow: "0 8px 20px rgba(0,0,0,0.08)",
          }} data-testid="prov-customer-results">
            {results.map((c, i) => (
              <button key={i} onClick={() => pickCustomer(c)}
                        style={{
                          width: "100%", padding: "8px 12px",
                          border: 0, borderBottom: i < results.length - 1
                            ? "1px solid #f1f5f9" : 0,
                          background: "#fff", cursor: "pointer",
                          textAlign: "left", fontSize: 12.5,
                        }}>
                <div style={{ fontWeight: 600, color: "#0f172a" }}>
                  {c.name || c.full_name}
                </div>
                <div style={{ fontSize: 10.5, color: "#64748b" }}>
                  #{c.external_id || c.id}
                  {c.plan_name ? ` · ${c.plan_name}` : ""}
                  {c.address ? ` · ${c.address}` : ""}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: "grid",
                      gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="Plano (opcional)">
          <input type="text" value={form.plan_name}
                   onChange={(e) => setForm((s) => ({ ...s, plan_name: e.target.value }))}
                   data-testid="prov-plan-input"
                   placeholder="Fibra 600 Mb"
                   style={inputStyle} />
        </Field>
        <Field label="VLAN (opcional)">
          <input type="number" value={form.vlan} min="1" max="4094"
                   onChange={(e) => setForm((s) => ({ ...s, vlan: e.target.value }))}
                   data-testid="prov-vlan-input"
                   style={inputStyle} />
        </Field>
      </div>

      <div style={{ display: "grid",
                      gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="PPPoE user (opcional)">
          <input type="text" value={form.pppoe_user}
                   onChange={(e) => setForm((s) => ({ ...s, pppoe_user: e.target.value }))}
                   data-testid="prov-pppoe-user-input"
                   style={inputStyle} />
        </Field>
        <Field label="PPPoE password (opcional)">
          <input type="text" value={form.pppoe_pwd}
                   onChange={(e) => setForm((s) => ({ ...s, pppoe_pwd: e.target.value }))}
                   data-testid="prov-pppoe-pwd-input"
                   style={inputStyle} />
        </Field>
      </div>

      <Field label="Observações (opcional)">
        <textarea value={form.notes} rows={2}
                    onChange={(e) => setForm((s) => ({ ...s, notes: e.target.value }))}
                    data-testid="prov-notes-input"
                    style={{ ...inputStyle, resize: "vertical",
                              fontFamily: "inherit" }} />
      </Field>

      {result && (
        result.ok ? (
          <div data-testid="prov-success"
                 style={{ padding: 12, borderRadius: 8,
                          background: "#dcfce7", color: "#166534",
                          display: "flex", gap: 8, alignItems: "center",
                          fontSize: 13 }}>
            <CheckCircle2 size={16} />
            {result.message || "Cadastrado!"}
            {!result.smartolt_synced && (
              <span style={{ marginLeft: "auto", fontSize: 11,
                              color: "#92400e", fontWeight: 600 }}>
                ⚠️ SmartOLT pendente
              </span>
            )}
          </div>
        ) : (
          <div data-testid="prov-error"
                 style={{ padding: 12, borderRadius: 8,
                          background: "#fee2e2", color: "#991b1b",
                          display: "flex", gap: 8, alignItems: "center",
                          fontSize: 13 }}>
            <AlertCircle size={16} /> {result.error}
          </div>
        )
      )}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button onClick={submit} disabled={!canSubmit || submitting}
                  data-testid="prov-submit-btn"
                  style={{
                    padding: "10px 18px", border: 0,
                    background: !canSubmit
                      ? "#cbd5e1"
                      : "linear-gradient(135deg, #10b981, #059669)",
                    color: "#fff", borderRadius: 10,
                    cursor: !canSubmit || submitting ? "not-allowed" : "pointer",
                    fontSize: 13, fontWeight: 700,
                    display: "inline-flex", alignItems: "center", gap: 6,
                  }}>
          <Plus size={14} />
          {submitting ? "Cadastrando…" : "Cadastrar ONU"}
        </button>
      </div>
    </div>
  );
}


function CTOPortSwapsTab({ ctoId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true); setErr("");
      try {
        const r = await api.redeIaCtoPortSwaps(ctoId, 50);
        if (alive) setData(r);
      } catch (e) {
        if (alive) setErr(e?.response?.data?.detail || e.message || "Erro");
      } finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [ctoId]);

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "#64748b" }}>
        <Loader2 size={16} className="animate-spin" /> Carregando histórico…
      </div>
    );
  }
  if (err) {
    return (
      <div style={{ padding: 12, background: "#fef2f2", color: "#991b1b",
                      borderRadius: 8, fontSize: 12 }}>{err}</div>
    );
  }
  const swaps = data?.swaps || [];
  if (!swaps.length) {
    return (
      <div data-testid="cto-swaps-empty"
            style={{ padding: 24, textAlign: "center", color: "#94a3b8",
                      fontSize: 13 }}>
        Nenhuma troca de porta registrada nesta CTO.
        <div style={{ fontSize: 11, marginTop: 6 }}>
          O histórico aparece aqui quando técnicos confirmam trocas de porta
          durante a finalização de uma OS.
        </div>
      </div>
    );
  }

  // KPI rápido: total + % com sync no SmartOLT + último técnico
  const total = swaps.length;
  const olt = swaps.filter((s) => s.from_smartolt).length;
  const synced = swaps.filter((s) => s.from_smartolt && s.smartolt_synced).length;

  return (
    <div data-testid="cto-swaps-tab">
      <div style={{ display: "grid",
                       gridTemplateColumns: "repeat(3, 1fr)",
                       gap: 8, marginBottom: 14 }}>
        <KpiMini label="Total" value={total} color="#0f172a" />
        <KpiMini label="Origem SmartOLT" value={olt}
                  hint={olt ? `${synced} sync OK` : "—"}
                  color="#0891b2" />
        <KpiMini label="Última troca"
                  value={swaps[0]?.at
                            ? new Date(swaps[0].at).toLocaleDateString("pt-BR")
                            : "—"}
                  hint={swaps[0]?.technician_name || ""}
                  color="#7c3aed" />
      </div>

      <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                       textTransform: "uppercase", letterSpacing: 0.5,
                       marginBottom: 8 }}>
        Trocas recentes (mais novas primeiro)
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {swaps.map((s, idx) => {
          const when = s.at ? new Date(s.at) : null;
          return (
            <div key={idx}
                    data-testid={`cto-swap-row-${idx}`}
                    style={{
                      padding: 12, border: "1px solid #e2e8f0",
                      borderRadius: 10, background: "#fafafa",
                    }}>
              <div style={{ display: "flex", alignItems: "center",
                                 justifyContent: "space-between",
                                 marginBottom: 6 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
                  {s.client_name}
                </div>
                {s.from_smartolt && (
                  <span title={s.smartolt_synced
                                  ? "Sync no SmartOLT confirmado"
                                  : "Pendente sync no SmartOLT"}
                          style={{
                            fontSize: 9, fontWeight: 800, letterSpacing: 0.5,
                            padding: "2px 6px", borderRadius: 999,
                            background: s.smartolt_synced ? "#dcfce7" : "#fef3c7",
                            color:      s.smartolt_synced ? "#166534" : "#92400e",
                            textTransform: "uppercase",
                          }}>
                    {s.smartolt_synced ? "SmartOLT ✓" : "SmartOLT ⏳"}
                  </span>
                )}
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 8,
                                 fontSize: 16, fontWeight: 800 }}>
                <span style={{
                  width: 36, height: 36, borderRadius: 8,
                  background: "#fee2e2", color: "#991b1b",
                  display: "grid", placeItems: "center",
                }}>{s.from_port}</span>
                <ArrowLeftRight size={20} color="#0d9488" />
                <span style={{
                  width: 36, height: 36, borderRadius: 8,
                  background: "#dcfce7", color: "#15803d",
                  display: "grid", placeItems: "center",
                }}>{s.to_port}</span>
                <div style={{ fontSize: 11, color: "#64748b",
                                   marginLeft: "auto", textAlign: "right" }}>
                  {when ? when.toLocaleString("pt-BR") : "—"}
                  <br />
                  <span style={{ fontWeight: 700, color: "#475569" }}>
                    {s.technician_name}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function KpiMini({ label, value, hint, color }) {
  return (
    <div style={{
      padding: 10, borderRadius: 8, background: "#f8fafc",
      border: "1px solid #e2e8f0",
    }}>
      <div style={{
        fontSize: 9, fontWeight: 700, color: "#94a3b8",
        textTransform: "uppercase", letterSpacing: 0.5,
      }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 800, color, lineHeight: 1.1,
                       marginTop: 2 }}>{value}</div>
      {hint && (
        <div style={{ fontSize: 10, color: "#64748b",
                          marginTop: 2 }}>{hint}</div>
      )}
    </div>
  );
}
