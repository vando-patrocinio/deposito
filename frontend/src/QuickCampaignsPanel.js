/**
 * QuickCampaignsPanel — Cards pré-configurados para Disparo em Massa.
 *
 * Cada card abre o formulário do DisparoPromoPanel com filtros + template
 * pré-preenchidos. Foco: ações recorrentes do ISP (avisar inadimplente
 * antes da redução, lembrete de boleto, upsell de plano, manutenção, etc).
 *
 * Variáveis suportadas no template: {nome}, {plano}, {valor}, {cidade},
 * {dias_atraso}.
 */
import React, { useState } from "react";
import DisparoPromoPanel from "@/DisparoPromoPanel";


const QUICK_CARDS = [
  {
    id: "pre_reducao",
    icon: "️",
    color: "#f59e0b",
    title: "Aviso pré-redução de velocidade",
    subtitle: "Quem está em GRACE (1-6 dias) — antes da redução automática",
    audience_label: "Clientes em tolerância (GRACE)",
    filters: {
      radius_states: ["GRACE"],
      only_with_phone: true,
    },
    template: (
      "Oi, {nome}! \n\n"
      + "Vi que sua fatura de R$ {valor} está em aberto há {dias_atraso} "
      + "dias \n\n"
      + "Pra evitar a redução automática da velocidade do seu plano "
      + "{plano}, finalize o pagamento hoje. Posso te enviar o link do "
      + "PIX/boleto agora — é só responder 1️⃣"
    ),
  },
  {
    id: "ja_reduzido",
    icon: "",
    color: "#dc2626",
    title: "Cliente JÁ está em REDUZIDO",
    subtitle: "Avisar que a velocidade caiu por inadimplência",
    audience_label: "Clientes em REDUZIDO",
    filters: { radius_states: ["REDUZIDO"], only_with_phone: true },
    template: (
      "Olá, {nome}. \n\n"
      + "Sua internet do plano {plano} está com velocidade reduzida "
      + "porque sua fatura de R$ {valor} venceu há {dias_atraso} dias.\n\n"
      + "Pague agora e em até 5 minutos sua velocidade volta ao normal "
      + "automaticamente. Quer o link do PIX?"
    ),
  },
  {
    id: "wall_garden",
    icon: "",
    color: "#991b1b",
    title: "Cliente em Wall Garden",
    subtitle: "Só consegue acessar portal/bancos — pedindo negociação",
    audience_label: "Clientes em WALLED_GARDEN",
    filters: { radius_states: ["WALLED_GARDEN"], only_with_phone: true },
    template: (
      "{nome}, sua internet foi limitada (você só consegue acessar "
      + "bancos e nosso portal de pagamento) porque a fatura está em "
      + "aberto há {dias_atraso} dias.\n\n"
      + "Quer negociar agora? Posso te enviar opções de parcelamento. "
    ),
  },
  {
    id: "pre_suspensao",
    icon: "",
    color: "#7f1d1d",
    title: "URGENTE: Pré-suspensão total",
    subtitle: "Última chance antes do corte completo",
    audience_label: "Clientes em WALL GARDEN com 20-29 dias",
    filters: {
      radius_states: ["WALLED_GARDEN"],
      overdue_min_days: 20, overdue_max_days: 29,
      only_with_phone: true,
    },
    template: (
      "️ ATENÇÃO {nome}\n\n"
      + "Sua internet será SUSPENSA totalmente em até 3 dias se a fatura "
      + "de R$ {valor} (vencida há {dias_atraso} dias) não for paga.\n\n"
      + "Quer evitar o corte total? Responde 1️⃣ que envio o PIX agora."
    ),
  },
  {
    id: "boleto_chegou",
    icon: "",
    color: "#0ea5e9",
    title: "Boleto disponível",
    subtitle: "Aviso pra clientes ATIVOS no início do mês",
    audience_label: "Todos os ATIVOS",
    filters: { radius_states: ["ATIVO"], status: ["active"],
                only_with_phone: true },
    template: (
      "Oi, {nome}! \n\n"
      + "Sua fatura deste mês do plano {plano} (R$ {valor}) já está "
      + "disponível.\n\n"
      + "Quer que eu te envie o PIX/boleto agora? É só responder 1️⃣"
    ),
  },
  {
    id: "upsell",
    icon: "",
    color: "#7c3aed",
    title: "Upsell — upgrade de plano",
    subtitle: "Pra ATIVOS há +12 meses no mesmo plano",
    audience_label: "Ativos com +12 meses de casa",
    filters: {
      radius_states: ["ATIVO"], status: ["active"],
      tenure_min_months: 12, only_with_phone: true,
    },
    template: (
      "Oi, {nome}! \n\n"
      + "Vi que você está com a gente há mais de 1 ano no plano {plano} "
      + "— obrigada pela parceria! \n\n"
      + "Que tal um upgrade pra 500 Megas com **R$ 10 OFF** no primeiro "
      + "mês? Responda 1️⃣ que eu te explico."
    ),
  },
  {
    id: "manutencao",
    icon: "️",
    color: "#64748b",
    title: "Aviso de manutenção programada",
    subtitle: "Notificar todos os clientes ativos da sua cidade",
    audience_label: "Ativos por cidade (filtra antes)",
    filters: { radius_states: ["ATIVO"], status: ["active"],
                only_with_phone: true },
    template: (
      "Olá, {nome}! \n\n"
      + "Faremos uma manutenção programada HOJE das 22h às 02h. Pode "
      + "haver instabilidade no sinal nesse período.\n\n"
      + "Agradecemos a compreensão! "
    ),
  },
  {
    id: "retorno_inativo",
    icon: "",
    color: "#ec4899",
    title: "Retorno de clientes cancelados",
    subtitle: "Campanha de reativação para ex-clientes",
    audience_label: "Clientes CANCELADOS",
    filters: { status: ["canceled"], only_with_phone: true },
    template: (
      "Oi, {nome}! \n\n"
      + "Sentimos sua falta! Voltamos com uma oferta especial pra te "
      + "trazer de volta: **1º MÊS GRÁTIS** + instalação por R$ 0 no "
      + "plano {plano}.\n\n"
      + "Quer voltar? Responde aqui que a gente cuida de tudo "
    ),
  },
];


export default function QuickCampaignsPanel() {
  const [active, setActive] = useState(null);

  if (active) {
    return (
      <div>
        <div style={{ marginBottom: 14 }}>
          <button data-testid="quick-back" onClick={() => setActive(null)}
                    style={{
                      padding: "8px 14px", borderRadius: 8,
                      background: "#f1f5f9", border: "1px solid #cbd5e1",
                      fontSize: 12, fontWeight: 700, cursor: "pointer",
                    }}>
            ← Voltar para campanhas rápidas
          </button>
        </div>
        <div style={{ padding: 14, borderRadius: 10,
                        background: `${active.color}15`,
                        border: `1px solid ${active.color}50`,
                        marginBottom: 16 }}>
          <div style={{ fontSize: 17, fontWeight: 800, color: active.color,
                          marginBottom: 4 }}>
            {active.icon} {active.title}
          </div>
          <div style={{ fontSize: 12, color: "#475569" }}>
            {active.subtitle} · <b>{active.audience_label}</b>
          </div>
        </div>
        <DisparoPromoPanel initialTemplate={active.template}
                            initialFilters={active.filters} />
      </div>
    );
  }

  return (
    <div data-testid="quick-campaigns">
      <p style={{ color: "#64748b", fontSize: 13, marginTop: 0,
                    marginBottom: 16 }}>
        Cards pré-configurados pros disparos mais comuns. Clique pra abrir
        o editor com filtros e mensagem já preenchidos — vc só revisa e
        envia. Variáveis: <code>{"{nome}"}</code>, <code>{"{plano}"}</code>,
        {" "}<code>{"{valor}"}</code>, <code>{"{cidade}"}</code>,
        {" "}<code>{"{dias_atraso}"}</code>.
      </p>

      <div style={{ display: "grid", gap: 14,
                      gridTemplateColumns: "repeat(auto-fill,minmax(310px,1fr))" }}>
        {QUICK_CARDS.map((c) => (
          <button key={c.id} data-testid={`quick-card-${c.id}`}
                    onClick={() => setActive(c)}
                    style={{
                      textAlign: "left", padding: 16, borderRadius: 12,
                      background: "#fff",
                      border: `1.5px solid ${c.color}30`,
                      borderLeft: `4px solid ${c.color}`,
                      cursor: "pointer",
                      transition: "transform 150ms, box-shadow 150ms",
                      boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.transform = "translateY(-2px)";
                      e.currentTarget.style.boxShadow =
                        "0 8px 20px rgba(0,0,0,0.10)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.transform = "translateY(0)";
                      e.currentTarget.style.boxShadow =
                        "0 1px 3px rgba(0,0,0,0.04)";
                    }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>{c.icon}</div>
            <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a",
                            marginBottom: 4, lineHeight: 1.3 }}>
              {c.title}
            </div>
            <div style={{ fontSize: 12, color: "#64748b", lineHeight: 1.4,
                            marginBottom: 10 }}>
              {c.subtitle}
            </div>
            <div style={{ display: "inline-block",
                            padding: "3px 9px",
                            background: `${c.color}15`, color: c.color,
                            borderRadius: 99, fontSize: 11, fontWeight: 700 }}>
              {c.audience_label}
            </div>
            <div style={{ marginTop: 10, padding: 10,
                            background: "#f8fafc", borderRadius: 7,
                            fontSize: 11, color: "#475569", lineHeight: 1.5,
                            whiteSpace: "pre-wrap",
                            overflow: "hidden",
                            display: "-webkit-box",
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: "vertical" }}>
              {c.template}
            </div>
            <div style={{ marginTop: 10, color: c.color,
                            fontSize: 12, fontWeight: 700 }}>
              Configurar e enviar →
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
