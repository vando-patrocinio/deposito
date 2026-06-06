/* LoyaltyOpportunitiesAITab — sub-aba" Oportunidades IA".
 *
 * Busca oportunidades B2B/B2C (empresas + condomínios) num raio
 * geográfico ao redor do endereço do escritório.
 *
 * Fluxo:
 * - Geocodifica endereço base via Nominatim (OpenStreetMap)
 * - Busca prédios/POIs via Overpass API em raio km
 * - Claude Sonnet 4.6 analisa e ranqueia oportunidades
 *
 * iter215m
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

const DEFAULT_ADDRESS ="Av. Vicente de Carvalho, 909, Vicente de Carvalho, Rio de Janeiro, RJ";
const DEFAULT_RADIUS = 5;

const PRIORITY_BG = {
 alta:"#fee2e2", media:"#fef3c7", baixa:"#dbeafe",
};
const PRIORITY_TXT = {
 alta:"#7f1d1d", media:"#78350f", baixa:"#1e3a8a",
};

function fmtAge(h) {
 if (h == null) return"—";
 if (h < 1) return `${Math.round(h * 60)} min`;
 if (h < 24) return `${h.toFixed(1)} h`;
 return `${Math.round(h / 24)} d`;
}

export default function LoyaltyOpportunitiesAITab() {
 const [data, setData] = useState(null);
 const [loading, setLoading] = useState(true);
 const [scanning, setScanning] = useState(false);
 const [err, setErr] = useState("");
 const [addr, setAddr] = useState(DEFAULT_ADDRESS);
 const [radius, setRadius] = useState(DEFAULT_RADIUS);

 const load = useCallback(async () =>{
 setLoading(true); setErr("");
 try {
 const r = await api._client.get("/customer/loyalty-ai/nearby-opportunities");
 if (r.data?.cached) {
 setData(r.data);
 if (r.data.origin_address) setAddr(r.data.origin_address);
 if (r.data.radius_km) setRadius(r.data.radius_km);
 }
 } catch (e) {
 setErr(e?.response?.data?.detail || e.message);
 }
 setLoading(false);
 }, []);

 useEffect(() =>{ load(); }, [load]);
 // iter215w — Recarrega quando uma nova base é importada (regra global)
 useEffect(() =>{
 const h = () =>load();
 window.addEventListener("loyalty-db-imported", h);
 return () =>window.removeEventListener("loyalty-db-imported", h);
 }, [load]);

 const scan = async () =>{
 setScanning(true); setErr("");
 try {
 const r = await api._client.post(
"/customer/loyalty-ai/nearby-opportunities/scan",
 { address: addr, radius_km: Number(radius) },
 { timeout: 240000 },
);
 setData({
 cached: true, age_hours: 0,
 ...r.data,
 origin_address: r.data.origin.address,
 origin_display_name: r.data.origin.display_name,
 origin_lat: r.data.origin.lat,
 origin_lon: r.data.origin.lon,
 });
 } catch (e) {
 setErr(e?.response?.data?.detail || e.message);
 }
 setScanning(false);
 };

 if (loading) {
 return <div style={{ padding: 20, color:"#64748b" }}>Carregando…</div>;
 }

 const ins = data?.insights;
 const condos = ins?.top_condominios || [];
 const empresas = ins?.top_empresas || [];
 const insightsRegional = ins?.regional_insights || [];
 const actionPlan = ins?.action_plan_30d || [];

 return (
 <div style={{ display: "grid", gap: 16 }}
 data-testid="loyalty-opportunities-ai-tab">
 <div style={{ fontSize: 13, color:"#64748b" }}>
 Prospecção B2B/B2C ao redor do escritório usando{""}
 <b style={{ color:"#7c3aed" }}>OpenStreetMap</b>+{""}
 <b style={{ color:"#7c3aed" }}>Claude Sonnet 4.6</b>.
 Identifica condomínios grandes e empresas com potencial de fechar fibra.
 </div>

 {/* Controles de scan */}
 <div style={{
 display: "grid", gap: 8,
 gridTemplateColumns:"1fr 130px auto", alignItems: "center",
 padding: 12, background: "white", borderRadius: 12,
 border:"1px solid #e2e8f0",
 }}>
 <label style={{ fontSize: 11, color:"#475569", display: "grid" }}>
 Endereço base
 <input value={addr} onChange={(e) =>setAddr(e.target.value)}
 data-testid="opp-ai-address"
 style={{
 padding:"8px 10px", fontSize: 12,
 border:"1px solid #cbd5e1", borderRadius: 6,
 }} />
 </label>
 <label style={{ fontSize: 11, color:"#475569", display: "grid" }}>
 Raio (km)
 <input type="number" value={radius} min={1} max={20} step={0.5}
 onChange={(e) =>setRadius(+e.target.value || 5)}
 data-testid="opp-ai-radius"
 style={{
 padding:"8px 10px", fontSize: 12,
 border:"1px solid #cbd5e1", borderRadius: 6,
 }} />
 </label>
 <button onClick={scan} disabled={scanning}
 data-testid="opp-ai-scan"
 style={{
 border: 0, borderRadius: 8, padding:"10px 16px",
 fontSize: 12, fontWeight: 800, color: "white",
 background: scanning ?"#94a3b8"
 : "linear-gradient(135deg, #0ea5e9, #7c3aed)",
 cursor: scanning ?"wait" : "pointer",
 alignSelf: "end",
 }}>
 {scanning ?"Escaneando…" :" Escanear oportunidades"}
 </button>
 </div>

 {err && (
 <div style={{
 background:"#fee2e2", color:"#7f1d1d",
 padding: 10, borderRadius: 8, fontSize: 13,
 }}>️ {err}</div>
)}

 {/* Estado vazio */}
 {!ins && !err && (
 <div style={{
 padding: 40, textAlign: "center", background: "white",
 border:"2px dashed #e2e8f0", borderRadius: 12,
 }}>
 <div style={{ fontSize: 56 }}></div>
 <div style={{ fontSize: 16, fontWeight: 700, marginTop: 12,
 color:"#0f172a" }}>
 Nenhum scan executado ainda
 </div>
 <div style={{ fontSize: 13, color:"#64748b", marginTop: 6 }}>
 Clique em <code>Escanear oportunidades</code> — a IA vai buscar prédios e
 empresas em raio de {radius}km do endereço e ranquear oportunidades.
 </div>
 </div>
)}

 {ins && (
 <>
 {/* Meta do scan */}
 <div style={{
 fontSize: 11, color:"#64748b", display: "flex", gap: 12,
 flexWrap: "wrap", padding:"6px 12px", background:"#f1f5f9",
 borderRadius: 8, width: "fit-content",
 }}>
 <span><b>{data.origin_display_name || addr}</b></span>
 <span>· raio: <b>{data.radius_km}km</b></span>
 <span>· prospects coletados: <b>{data.raw_count}</b></span>
 <span>· modelo: <b>{data.model}</b></span>
 <span>· há <b>{fmtAge(data.age_hours)}</b></span>
 </div>

 {/* Header score + summary */}
 <div style={{
 display: "grid", gap: 16,
 gridTemplateColumns:"200px 1fr",
 }}>
 <div style={{
 padding: 24, borderRadius: 16,
 background: `linear-gradient(135deg, ${
 ins.market_score >= 70 ?"#22c55e"
 : ins.market_score >= 40 ?"#eab308" :"#dc2626"
 }, ${
 ins.market_score >= 70 ?"#15803d"
 : ins.market_score >= 40 ?"#a16207" :"#7f1d1d"
 })`,
 color: "white", textAlign: "center",
 }}>
 <div style={{
 fontSize: 11, textTransform: "uppercase",
 letterSpacing: 1, opacity: 0.85, fontWeight: 800,
 }}>Market Score</div>
 <div style={{ fontSize: 56, fontWeight: 900, lineHeight: 1,
 marginTop: 4 }}>
 {ins.market_score ??"—"}
 </div>
 <div style={{ fontSize: 11, opacity: 0.85, marginTop: 4 }}>/ 100</div>
 </div>
 <div style={{
 padding: 20, background: "white", borderRadius: 16,
 border:"1px solid #e2e8f0",
 }}>
 <div style={{
 fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5,
 color:"#64748b", fontWeight: 800,
 }}>Resumo da Região</div>
 <div style={{ fontSize: 14, marginTop: 8, lineHeight: 1.6,
 color:"#0f172a" }}>
 {ins.summary}
 </div>
 {insightsRegional.length >0 && (
 <ul style={{
 marginTop: 10, paddingLeft: 18, fontSize: 12,
 color:"#475569", lineHeight: 1.6,
 }}>
 {insightsRegional.map((i, idx) =><li key={idx}>{i}</li>)}
 </ul>
)}
 </div>
 </div>

 {/* Condomínios */}
 {condos.length >0 && (
 <Section title=" Condomínios Residenciais (100+ unidades)"
 accent="#7c3aed"
 count={condos.length}>
 <ProspectTable items={condos} kind="condo" />
 </Section>
)}

 {/* Empresas */}
 {empresas.length >0 && (
 <Section title=" Empresas, Hospitais, Escolas"
 accent="#0ea5e9"
 count={empresas.length}>
 <ProspectTable items={empresas} kind="empresa" />
 </Section>
)}

 {/* Plano de ação */}
 {actionPlan.length >0 && (
 <div style={{
 background: "white", borderRadius: 12, padding: 16,
 border:"1px solid #e2e8f0",
 }}>
 <div style={{ fontSize: 14, fontWeight: 800, color:"#0f172a",
 marginBottom: 12 }}>
 Plano de Prospecção dos Próximos 30 Dias
 </div>
 <div style={{
 display: "grid", gap: 12,
 gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
 }}>
 {actionPlan.map((w) =>(
 <div key={w.week} style={{
 padding: 12, background:"#f8fafc", borderRadius: 8,
 borderLeft:"3px solid #0ea5e9",
 }}>
 <div style={{
 fontSize: 10, fontWeight: 800, color:"#0ea5e9",
 textTransform: "uppercase", letterSpacing: 0.5,
 }}>
 Semana {w.week}
 </div>
 {w.focus && (
 <div style={{ fontSize: 11, color:"#0f172a",
 fontWeight: 700, marginTop: 4 }}>
 {w.focus}
 </div>
)}
 <ul style={{ margin:"6px 0 0", paddingLeft: 16,
 fontSize: 11, lineHeight: 1.6,
 color:"#475569" }}>
 {(w.actions || []).map((a, i) =><li key={i}>{a}</li>)}
 </ul>
 </div>
))}
 </div>
 </div>
)}

 {/* Raw prospects sample */}
 {data.prospects && data.prospects.length >0 && (
 <details style={{
 background: "white", borderRadius: 12, padding: 12,
 border:"1px solid #e2e8f0",
 }}>
 <summary style={{ fontSize: 12, fontWeight: 800, color:"#475569",
 cursor: "pointer" }}>
 Ver todos os {data.prospects.length} prospects brutos (OSM)
 </summary>
 <div style={{ marginTop: 10, maxHeight: 300, overflow: "auto" }}>
 <table style={{ width:"100%", fontSize: 11,
 borderCollapse: "collapse" }}>
 <thead>
 <tr style={{ background:"#f1f5f9" }}>
 <Th>Nome</Th><Th>Categoria</Th><Th>Dist.</Th>
 <Th>Andares</Th><Th>Unidades est.</Th>
 </tr>
 </thead>
 <tbody>
 {data.prospects.map((p, i) =>(
 <tr key={i} style={{ borderTop:"1px solid #f1f5f9" }}>
 <Td>{p.name}</Td>
 <Td>{p.category}</Td>
 <Td>{p.distance_km}km</Td>
 <Td>{p.levels ||"—"}</Td>
 <Td>{p.estimated_units ||"—"}</Td>
 </tr>
))}
 </tbody>
 </table>
 </div>
 </details>
)}
 </>
)}
 </div>
);
}

function Section({ title, accent, count, children }) {
 return (
 <div style={{
 background: "white", borderRadius: 12, overflow: "hidden",
 border:"1px solid #e2e8f0", borderTop: `3px solid ${accent}`,
 }}>
 <div style={{
 padding:"12px 16px", display: "flex", justifyContent: "space-between",
 alignItems: "center", borderBottom:"1px solid #e2e8f0",
 }}>
 <div style={{ fontSize: 14, fontWeight: 800, color:"#0f172a" }}>
 {title}
 </div>
 <span style={{
 background: accent, color: "white",
 padding:"2px 10px", borderRadius: 999,
 fontSize: 11, fontWeight: 800,
 }}>
 {count} oportunidades
 </span>
 </div>
 {children}
 </div>
);
}

function ProspectTable({ items, kind }) {
 return (
 <div style={{ overflowX: "auto" }}>
 <table style={{ width:"100%", borderCollapse: "collapse",
 fontSize: 12, minWidth: 800 }}>
 <thead>
 <tr style={{ background:"#f8fafc",
 borderBottom:"1px solid #e2e8f0" }}>
 <Th>#</Th>
 <Th>Nome / Endereço</Th>
 {kind ==="condo" && <Th>Unidades est.</Th>}
 {kind ==="empresa" && <Th>Categoria</Th>}
 <Th>Prioridade</Th>
 <Th>Estratégia</Th>
 <Th>Potencial</Th>
 </tr>
 </thead>
 <tbody>
 {items.map((it, idx) =>(
 <tr key={idx}
 data-testid={`opp-row-${kind}-${idx}`}
 style={{ borderBottom:"1px solid #f1f5f9" }}>
 <Td><b>{idx + 1}</b></Td>
 <Td>
 <div style={{ fontWeight: 700, color:"#0f172a" }}>
 {it.name}
 </div>
 {it.address_or_distance && (
 <div style={{ fontSize: 10, color:"#64748b" }}>
 {it.address_or_distance}
 </div>
)}
 {it.rationale && (
 <div style={{ fontSize: 10, color:"#475569",
 marginTop: 4, lineHeight: 1.4 }}>
 {it.rationale}
 </div>
)}
 </Td>
 {kind ==="condo" && (
 <Td>
 <b style={{ fontSize: 14, color:"#7c3aed" }}>
 {it.estimated_units ||"—"}
 </b>
 </Td>
)}
 {kind ==="empresa" && (
 <Td>
 <span style={{
 fontSize: 10, padding:"2px 8px", borderRadius: 999,
 background:"#dbeafe", color:"#1e3a8a", fontWeight: 700,
 }}>
 {it.category ||"—"}
 </span>
 </Td>
)}
 <Td>
 <span style={{
 fontSize: 10, padding:"2px 8px", borderRadius: 999,
 background: PRIORITY_BG[it.priority] ||"#f1f5f9",
 color: PRIORITY_TXT[it.priority] ||"#475569",
 fontWeight: 800, textTransform: "uppercase",
 }}>
 {it.priority}
 </span>
 </Td>
 <Td>
 <div style={{ fontSize: 11, lineHeight: 1.4 }}>
 {it.approach_strategy}
 </div>
 </Td>
 <Td>
 <div style={{ fontSize: 11, color:"#15803d",
 fontWeight: 700 }}>
 {it.estimated_revenue_potential}
 </div>
 </Td>
 </tr>
))}
 </tbody>
 </table>
 </div>
);
}

function Th({ children }) {
 return (
 <th style={{
 textAlign: "left", padding:"8px 12px", fontSize: 10,
 fontWeight: 800, color:"#475569", textTransform: "uppercase",
 letterSpacing: 0.5, whiteSpace: "nowrap",
 }}>{children}</th>
);
}

function Td({ children }) {
 return (
 <td style={{ padding:"10px 12px", verticalAlign: "top" }}>
 {children}
 </td>
);
}
