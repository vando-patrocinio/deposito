/* DiagnosticReport.js — iter215by
   Página imprimível com diagnóstico completo do SmartProv.
   Browser-native window.print() vira PDF.
*/
import React, { useState, useEffect } from "react";
import { api } from "@/api";
import { Printer, FileText, ArrowLeft } from "lucide-react";

const O = { purple: "#4b1d7a", orange: "#f28c28",
            green: "#237a4b", red: "#b42318", border: "#e2e8f0" };

export default function DiagnosticReport({ onBack }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await api._client.get("/diagnostic/full");
        setData(r.data);
      } catch (e) { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) {
    return <div style={{ padding: 40, textAlign: "center",
                          color: "#64748b" }}>
      Gerando diagnóstico completo… (pode levar até 60s)
    </div>;
  }
  if (!data) {
    return <div style={{ padding: 40, color: O.red }}>
      Falha ao gerar diagnóstico.
    </div>;
  }

  const ai = data.ai_analysis || {};
  const auto = ai.autoanalise || {};
  const par = ai.parecer_executivo || {};

  return (
    <>
      <style>{`
        @media print {
          .no-print { display: none !important; }
          body { background: white !important; }
          .diag-page { box-shadow: none !important; max-width: 100% !important; }
          section { break-inside: avoid; }
        }
        @page { size: A4; margin: 16mm; }
      `}</style>

      <div className="no-print" style={{
        position: "sticky", top: 0, zIndex: 10,
        background: "white", padding: "12px 18px",
        borderBottom: `1px solid ${O.border}`,
        display: "flex", gap: 10, alignItems: "center",
      }}>
        <button onClick={onBack} data-testid="diag-back"
          style={{ padding: "6px 12px", border: `1px solid ${O.border}`,
                     borderRadius: 6, background: "white",
                     cursor: "pointer", display: "flex",
                     alignItems: "center", gap: 6 }}>
          <ArrowLeft size={14} /> Voltar
        </button>
        <h1 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                       color: O.purple }}>Diagnóstico Completo</h1>
        <button onClick={() => window.print()} data-testid="diag-print"
          style={{ marginLeft: "auto", padding: "8px 16px",
                     border: "none", background: O.purple, color: "white",
                     borderRadius: 8, cursor: "pointer", fontWeight: 700,
                     fontSize: 13, display: "flex", alignItems: "center",
                     gap: 6 }}>
          <Printer size={14} /> Imprimir / PDF
        </button>
      </div>

      <div className="diag-page" data-testid="diagnostic-report"
            style={{ maxWidth: 900, margin: "20px auto",
                      padding: 32, background: "white",
                      boxShadow: "0 1px 6px rgba(0,0,0,.08)",
                      fontFamily: "Inter, sans-serif",
                      color: "#1e293b" }}>
        <header style={{ borderBottom: `3px solid ${O.purple}`,
                          paddingBottom: 14, marginBottom: 20 }}>
          <div style={{ fontSize: 11, color: O.orange, fontWeight: 800,
                          letterSpacing: 3, textTransform: "uppercase" }}>
            SmartProv · Ligo Sistema
          </div>
          <h1 style={{ margin: "4px 0 0 0", fontSize: 28, fontWeight: 800,
                          color: O.purple, letterSpacing: "-0.02em" }}>
            Relatório de Diagnóstico Completo
          </h1>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 8 }}>
            Gerado em {new Date(data.generated_at).toLocaleString("pt-BR")}
            {" · "}Versão {data.versao}
          </div>
        </header>

        <Sec n="1" title="Resumo Executivo">
          <Kv data={data.executive_summary} />
        </Sec>

        <Sec n="2" title="Mapa Completo de Módulos">
          <Table cols={["Módulo", "Status", "Objetivo"]} rows={
            data.modulos.map((m) => [
              m.nome,
              <Badge key={m.nome} status={m.status} />,
              m.objetivo || "—",
            ])
          } />
        </Sec>

        <Sec n="3" title="Motor IA">
          <p><b>Arquitetura:</b> {data.motor_ia.arquitetura}</p>
          <p><b>Modelos:</b> {data.motor_ia.modelos.join(", ")}</p>
          <p><b>Provedores:</b> {data.motor_ia.provedores.join(", ")}</p>
          <h4 style={{ marginTop: 14 }}>Agentes existentes</h4>
          <Table cols={["Agente", "Objetivo", "Entradas", "Saídas"]} rows={
            data.motor_ia.agentes.map((a) => [
              a.nome, a.objetivo, a.entradas || "—", a.saidas || "—",
            ])
          } />
        </Sec>

        <Sec n="4" title="Base de Dados">
          <Kv data={data.base_dados} />
        </Sec>

        <Sec n="5" title="Operação"><Kv data={data.operacao} /></Sec>

        <Sec n="6" title="Rede">
          <Kv data={{
            OLTs: data.rede.olts, CTOs: data.rede.ctos,
            "ONUs online": data.rede.onus_online,
            "ONUs offline": data.rede.onus_offline,
            "Potência média (dBm)": data.rede.potencia_media_dbm,
          }} />
          {!!data.rede.ctos_saturadas?.length && (
            <>
              <h4 style={{ marginTop: 14 }}>Top 10 CTOs por ocupação</h4>
              <Table cols={["CTO", "Bairro", "Clientes/Cap.", "Saturação"]}
                rows={data.rede.ctos_saturadas.map((c) => [
                  c.label, c.bairro,
                  `${c.clientes}/${c.capacidade}`,
                  `${c.saturacao_pct}%`,
                ])} />
            </>
          )}
        </Sec>

        <Sec n="7" title="Universo Ligo"><Kv data={data.universo_ligo} /></Sec>

        <Sec n="8" title="GPS & Monitoramento">
          <Kv data={data.gps_monitoramento || {}} />
        </Sec>

        <Sec n="9" title="Segurança"><Kv data={data.seguranca || {}} /></Sec>

        <Sec n="10" title="Financeiro"><Kv data={data.financeiro} /></Sec>

        <Sec n="11" title="KPIs">
          <Table cols={["KPI", "Objetivo", "Fórmula", "Atual", "Meta"]}
            rows={data.kpis.map((k) => [
              k.nome, k.objetivo, k.formula,
              k.atual ?? "—", k.meta || "—",
            ])} />
        </Sec>

        <Sec n="12" title="Automações">
          <ul style={{ paddingLeft: 18 }}>
            {data.automacoes.map((a, i) =>
              <li key={i} style={{ marginBottom: 4 }}>{a}</li>)}
          </ul>
        </Sec>

        <Sec n="13" title="Integrações">
          <Table cols={["Integração", "Status"]}
            rows={data.integracoes.map((i) => [
              i.nome, <Badge key={i.nome} status={i.status} />,
            ])} />
        </Sec>

        <Sec n="14" title="Roadmap">
          <Table cols={["Módulo", "Status"]}
            rows={data.modulos
              .filter((m) => m.status !== "Produção")
              .map((m) => [m.nome,
                <Badge key={m.nome} status={m.status} />])} />
        </Sec>

        <Sec n="15" title="Autoanálise do Motor IA">
          <Block k="Pontos fortes" v={auto.pontos_fortes} />
          <Block k="Maiores gargalos" v={auto.gargalos} />
          <Block k="O que está faltando" v={auto.faltando} />
          <Block k="O que está duplicado" v={auto.duplicado} />
          <Block k="O que pode ser simplificado" v={auto.simplificavel} />
          <Block k="Valor para a Ligo" v={auto.valor_ligo} />
          <Block k="Valor para o cliente" v={auto.valor_cliente} />
          <Block k="Valor para o colaborador" v={auto.valor_colaborador} />
          <Block k="Valor para os parceiros" v={auto.valor_parceiros} />
          <Block k="Prioridades 90 dias" v={auto.prioridades_90d} />
        </Sec>

        <section style={{ background: `linear-gradient(135deg, ${O.purple} 0%, #1e1b4b 100%)`,
                            color: "white", padding: 22, borderRadius: 12,
                            marginTop: 24 }}
                  data-testid="diag-parecer">
          <div style={{ fontSize: 10, color: "rgba(255,255,255,.55)",
                          letterSpacing: 2, textTransform: "uppercase",
                          fontWeight: 800 }}>Seção 16</div>
          <h2 style={{ margin: "4px 0 14px 0", fontSize: 22,
                          fontWeight: 800 }}>
            Parecer Executivo · CTO · COO · CPO · CEO
          </h2>
          <ParBlock k="Onde estamos hoje" v={par.onde_estamos} />
          <ParBlock k="O que já foi construído" v={par.ja_construido} />
          <ParBlock k="O que falta" v={par.o_que_falta} />
          <ParBlock k="Próximo passo" v={par.proximo_passo} />
          <ParBlock k="Risco atual" v={par.risco_atual} />
          <ParBlock k="Maior oportunidade" v={par.maior_oportunidade} />
          <ParBlock k="Visão para 12 meses" v={par.visao_12m} />
          <ParBlock k="Visão para 36 meses" v={par.visao_36m} />
        </section>

        <footer style={{ marginTop: 30, paddingTop: 14,
                          borderTop: `1px solid ${O.border}`,
                          fontSize: 10, color: "#94a3b8",
                          textAlign: "center" }}>
          SmartProv {data.versao} · Documento confidencial
        </footer>
      </div>
    </>
  );
}

function Sec({ n, title, children }) {
  return <section style={{ marginBottom: 22 }}>
    <h2 style={{ fontSize: 14, fontWeight: 800, color: O.purple,
                    textTransform: "uppercase", letterSpacing: 1,
                    borderBottom: `2px solid ${O.orange}`,
                    paddingBottom: 4, marginBottom: 10 }}>
      {n}. {title}
    </h2>
    {children}
  </section>;
}

function Kv({ data }) {
  const entries = Object.entries(data || {});
  return <div style={{ display: "grid", gap: 6,
                          gridTemplateColumns: "1fr 1fr" }}>
    {entries.map(([k, v]) => (
      <div key={k} style={{ display: "flex", gap: 8,
                              fontSize: 12, padding: "4px 8px",
                              background: "#f8fafc", borderRadius: 4 }}>
        <span style={{ color: "#64748b", textTransform: "capitalize",
                         flex: 1 }}>{k.replace(/_/g, " ")}:</span>
        <span style={{ fontWeight: 700 }}>
          {typeof v === "object" ? JSON.stringify(v).slice(0, 50)
            : String(v)}</span>
      </div>
    ))}
  </div>;
}

function Table({ cols, rows }) {
  return <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 12, marginTop: 6 }}>
    <thead><tr style={{ background: "#f1f5f9" }}>
      {cols.map((c) => <th key={c} style={{ padding: "6px 8px",
        textAlign: "left", fontWeight: 700, fontSize: 10,
        textTransform: "uppercase", color: "#475569" }}>{c}</th>)}
    </tr></thead>
    <tbody>{rows.map((r, i) => (
      <tr key={i} style={{ borderTop: `1px solid ${O.border}` }}>
        {r.map((cell, j) => <td key={j}
          style={{ padding: "6px 8px" }}>{cell}</td>)}
      </tr>
    ))}</tbody>
  </table>;
}

function Badge({ status }) {
  const map = { "Produção": O.green, "Desenvolvimento": O.orange,
                 "Planejado": "#64748b", "Ativo": O.green,
                 "Inativo": "#94a3b8", "Teste": "#0891b2" };
  return <span style={{ background: map[status] || "#64748b",
                          color: "white", padding: "2px 8px",
                          borderRadius: 10, fontSize: 9, fontWeight: 800,
                          letterSpacing: .4, textTransform: "uppercase" }}>
    {status}
  </span>;
}

function Block({ k, v }) {
  if (!v) return null;
  return <div style={{ marginBottom: 10, padding: "8px 12px",
                          background: "#f8fafc",
                          borderLeft: `3px solid ${O.orange}`,
                          borderRadius: 4 }}>
    <div style={{ fontSize: 10, fontWeight: 800, color: O.orange,
                    textTransform: "uppercase", letterSpacing: .5,
                    marginBottom: 4 }}>{k}</div>
    <div style={{ fontSize: 12, lineHeight: 1.5 }}>{v}</div>
  </div>;
}

function ParBlock({ k, v }) {
  if (!v) return null;
  return <div style={{ marginBottom: 12, padding: "10px 14px",
                          background: "rgba(255,255,255,.08)",
                          borderLeft: `3px solid #f28c28`,
                          borderRadius: 4 }}>
    <div style={{ fontSize: 10, fontWeight: 800, color: O.orange,
                    textTransform: "uppercase", letterSpacing: .5,
                    marginBottom: 4 }}>{k}</div>
    <div style={{ fontSize: 13, lineHeight: 1.6 }}>{v}</div>
  </div>;
}
