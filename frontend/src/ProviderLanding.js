import React, { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import {
  Zap, ShieldCheck, Clock, Wifi, Tv, Gamepad2, Phone, MessageCircle,
  Star, MapPin, ChevronRight, Sparkles, Headphones, ChevronDown,
  CheckCircle2, Smartphone, Award, ArrowRight,
} from "lucide-react";
import "./landing/landing.css";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

/* =================================================================
   SmartProv Landing — Design Swiss & High-Contrast (light)
   Sections:
     1. Header sticky (glassmorphism)
     2. Hero com CEP checker
     3. Stats bar (trust signals)
     4. Plans (4 cards, "MAIS VENDIDO" destacado)
     5. Calculadora visual de velocidade
     6. Combos carousel (marquee)
     7. Why SmartProv (3 diferenciais)
     8. Testimonials
     9. App showcase (mobile mockup)
    10. FAQ accordion
    11. Lead form
    12. Footer + WhatsApp floating sticky
================================================================= */

export default function ProviderLanding() {
  const [config, setConfig] = useState(null);
  const [plans, setPlans] = useState([]);

  useEffect(() => {
    Promise.all([
      axios.get(`${BACKEND}/api/site/config`).then((r) => r.data).catch(() => null),
      axios.get(`${BACKEND}/api/site/plans`).then((r) => r.data).catch(() => null),
    ]).then(([c, p]) => {
      setConfig(c || DEFAULT_CONFIG);
      const items = p?.items || [];
      // Fallback: se não há planos cadastrados, usa exemplos.
      setPlans(items.length >= 4 ? items.slice(0, 4) : FALLBACK_PLANS);
    });
  }, []);

  if (!config) {
    return (
      <div className="min-h-screen grid place-items-center bg-[#FAFAFA] text-[#475569]">
        <div className="animate-pulse text-sm tracking-widest uppercase">Carregando…</div>
      </div>
    );
  }

  return (
    <div className="sp-landing" data-testid="provider-landing">
      <Header config={config} />
      <Hero config={config} />
      <StatsBar />
      <PlansSection plans={plans} config={config} />
      <Calculator />
      <CombosMarquee config={config} />
      <WhySection />
      <Testimonials />
      <AppShowcase config={config} />
      <FAQ />
      <LeadFormSection config={config} plans={plans} />
      <Footer config={config} />
      <WhatsAppFloating config={config} />
    </div>
  );
}

/* === Defaults & Fallbacks ====================================== */
const DEFAULT_CONFIG = {
  site_name: "SmartProv",
  cnpj: "00.000.000/0001-00",
  anatel: "Fistel: 00000000",
  phone_0800: "0800 000 0000",
  phone_whatsapp: "5511999999999",
  email: "contato@smartprov.com.br",
  hero_kicker: "FIBRA ÓTICA 100% PURA",
  hero_title: "Sua casa na velocidade da luz.",
  hero_subtitle:
    "Internet ultra rápida, estável e com suporte humano de verdade. Sem fidelidade obrigatória.",
  primary_color: "#4F46E5",
  secondary_color: "#06B6D4",
};
const FALLBACK_PLANS = [
  { id: "p500", name: "Essencial", speed_down_mbps: 500, monthly_price: 79.90 },
  { id: "p1000", name: "Família", speed_down_mbps: 1000, monthly_price: 99.90,
    _highlight: true },
  { id: "p2000", name: "Pro", speed_down_mbps: 2000, monthly_price: 149.90 },
  { id: "p5000", name: "Ultra", speed_down_mbps: 5000, monthly_price: 299.90 },
];

/* === Header ==================================================== */
function Header({ config }) {
  const whats = waLink(config.phone_whatsapp, "Olá, vim do site!");
  return (
    <header className="sticky top-0 z-50 backdrop-blur-xl bg-white/80
                       border-b border-slate-200/60">
      <div className="max-w-7xl mx-auto px-6 lg:px-10 h-16 flex items-center gap-6">
        <a href="#top" className="display text-2xl font-black tracking-tighter">
          <span style={{ color: "#4F46E5" }}>Smart</span>
          <span className="text-slate-900">Prov</span>
        </a>
        <nav className="hidden md:flex gap-8 ml-6 text-sm font-medium text-slate-600">
          <a href="#planos" className="hover:text-slate-900 transition">Planos</a>
          <a href="#combos" className="hover:text-slate-900 transition">Combos</a>
          <a href="#beneficios" className="hover:text-slate-900 transition">Benefícios</a>
          <a href="#faq" className="hover:text-slate-900 transition">FAQ</a>
        </nav>
        <div className="flex-1" />
        <a href={whats} target="_blank" rel="noopener noreferrer"
            data-testid="header-whats"
            className="hidden sm:inline-flex items-center gap-2 rounded-full
                        px-5 py-2.5 text-sm font-bold text-white
                        bg-[#4F46E5] hover:bg-[#4338CA] transition shadow-lg
                        shadow-indigo-500/30">
          Assine já <ArrowRight className="w-4 h-4" />
        </a>
      </div>
    </header>
  );
}

/* === Hero with CEP checker ===================================== */
function Hero({ config }) {
  const [cep, setCep] = useState("");
  const [check, setCheck] = useState(null);  // null | 'loading' | 'ok' | 'no'
  const onCheck = () => {
    if (!/^\d{5}-?\d{3}$/.test(cep.trim())) return;
    setCheck("loading");
    setTimeout(() => {
      // demo: CEPs começando com 0-4 → coberto; 5-9 → não coberto
      const first = cep.replace(/\D/g, "")[0];
      setCheck(["0","1","2","3","4"].includes(first) ? "ok" : "no");
    }, 1100);
  };
  return (
    <section id="top" className="relative overflow-hidden pt-12 pb-24
                                   lg:pt-20 lg:pb-32 px-6 lg:px-10">
      {/* Background blob */}
      <div aria-hidden className="absolute -top-40 -right-32 w-[640px] h-[640px]
                                     rounded-full opacity-30 blur-3xl"
            style={{ background: "radial-gradient(circle, #4F46E5 0%, transparent 70%)" }} />
      <div aria-hidden className="absolute -bottom-32 -left-32 w-[520px] h-[520px]
                                     rounded-full opacity-20 blur-3xl"
            style={{ background: "radial-gradient(circle, #06B6D4 0%, transparent 70%)" }} />

      <div className="relative max-w-7xl mx-auto grid lg:grid-cols-12 gap-12 items-center">
        <motion.div initial={{ opacity: 0, y: 24 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.55 }}
                      className="lg:col-span-7">
          <div className="eyebrow mb-6">{config.hero_kicker}</div>
          <h1 className="display text-5xl sm:text-6xl lg:text-7xl
                          font-black leading-[0.95] text-slate-900">
            {config.hero_title}
          </h1>
          <p className="mt-7 text-lg lg:text-xl text-slate-600 max-w-xl leading-relaxed">
            {config.hero_subtitle}
          </p>

          {/* CEP checker */}
          <div className="mt-10 max-w-md">
            <label className="eyebrow block mb-3">Verifique a cobertura</label>
            <div className="flex gap-2 p-1.5 rounded-2xl bg-white shadow-xl
                              shadow-slate-200/60 border border-slate-200">
              <MapPin className="w-5 h-5 self-center ml-3 text-slate-400" />
              <input data-testid="cep-input" value={cep}
                      onChange={(e) => setCep(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && onCheck()}
                      placeholder="Digite seu CEP — ex: 22290-000"
                      className="flex-1 bg-transparent outline-none text-sm
                                  placeholder:text-slate-400" />
              <button onClick={onCheck} data-testid="cep-check"
                        className="rounded-xl bg-slate-900 hover:bg-slate-800
                                    text-white text-sm font-bold
                                    px-5 py-2.5 transition">
                {check === "loading" ? "..." : "Verificar"}
              </button>
            </div>
            {check === "ok" && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                          className="mt-3 flex items-center gap-2 text-sm
                                      text-emerald-700 font-semibold">
                <CheckCircle2 className="w-4 h-4" /> Cobertura disponível!
                Veja os planos abaixo.
              </motion.div>
            )}
            {check === "no" && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                          className="mt-3 flex items-center gap-2 text-sm
                                      text-amber-700 font-semibold">
                <Sparkles className="w-4 h-4" /> Ainda não chegamos aí, mas
                queremos! Deixe seus dados e te avisamos.
              </motion.div>
            )}
          </div>

          <div className="mt-10 flex flex-wrap gap-3 text-xs text-slate-500">
            {["100% Fibra ótica", "Wi-Fi 6 incluso", "Sem fidelidade", "Instalação rápida"]
              .map((t) => (
                <span key={t} className="px-3 py-1.5 rounded-full bg-white
                                            border border-slate-200">
                  {t}
                </span>
              ))}
          </div>
        </motion.div>

        {/* Hero visual */}
        <motion.div initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ duration: 0.7, delay: 0.15 }}
                      className="lg:col-span-5 relative">
          <div className="absolute -inset-6 rounded-[2.5rem]
                            bg-gradient-to-br from-indigo-100 via-white to-cyan-50
                            -z-10" />
          <img src="https://images.pexels.com/photos/8949350/pexels-photo-8949350.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940"
                alt="Família conectada"
                className="rounded-3xl shadow-2xl shadow-slate-300/50 w-full h-auto" />
          {/* Floating speed card */}
          <motion.div initial={{ y: 20, opacity: 0 }}
                        animate={{ y: 0, opacity: 1 }}
                        transition={{ delay: 0.6 }}
                        className="absolute -bottom-6 -left-6 bg-white p-5
                                    rounded-2xl shadow-2xl border border-slate-100
                                    max-w-[200px]">
            <div className="text-xs text-slate-400 font-bold tracking-widest uppercase">Download</div>
            <div className="display text-3xl font-black text-slate-900 mt-1">
              987<span className="text-base text-slate-500"> Mbps</span>
            </div>
            <div className="flex items-center gap-1 mt-2 text-xs text-emerald-600 font-semibold">
              <CheckCircle2 className="w-3 h-3" /> Em tempo real
            </div>
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}

/* === Stats trust bar =========================================== */
function StatsBar() {
  const stats = [
    { v: "99.9%", l: "Uptime garantido" },
    { v: "+50 mil", l: "Lares conectados" },
    { v: "4.9", l: "Avaliação Google" },
    { v: "24/7", l: "Suporte humano" },
  ];
  return (
    <section className="bg-slate-900 text-white py-10 px-6 lg:px-10">
      <div className="max-w-6xl mx-auto grid grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((s) => (
          <div key={s.l} className="text-center">
            <div className="display text-3xl lg:text-4xl font-black">{s.v}</div>
            <div className="text-xs uppercase tracking-widest text-slate-400 mt-1">
              {s.l}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* === Plans ===================================================== */
function PlansSection({ plans, config }) {
  return (
    <section id="planos" className="py-24 px-6 lg:px-10">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-14">
          <div className="eyebrow mb-3">Planos</div>
          <h2 className="display text-4xl lg:text-5xl font-black text-slate-900">
            Escolha a velocidade ideal
          </h2>
          <p className="mt-4 text-slate-600 max-w-xl mx-auto">
            Internet pura, com Wi-Fi 6 incluso e instalação grátis.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {plans.map((p, i) => {
            // Destaca o segundo plano por padrão como "MAIS VENDIDO"
            const isHero = p._highlight ?? (i === 1);
            return (
              <PlanCard key={p.id} plan={p} hero={isHero} config={config} />
            );
          })}
        </div>
      </div>
    </section>
  );
}

function PlanCard({ plan, hero, config }) {
  const cents = String(Math.round((plan.monthly_price % 1) * 100))
        .padStart(2, "0").slice(0, 2);
  const whats = waLink(config.phone_whatsapp,
    `Olá! Quero contratar o plano ${plan.name} ` +
    `(${plan.speed_down_mbps} Mega — R$ ${plan.monthly_price.toFixed(2)}/mês).`);
  const speed = plan.speed_down_mbps;
  const speedLabel = speed >= 1000
    ? `${Math.round(speed / 1000)}` : `${speed}`;
  const speedUnit = speed >= 1000 ? "GIGA" : "MEGA";
  return (
    <motion.div
      data-testid={`plan-card-${plan.id}`}
      whileHover={{ y: -8 }} transition={{ type: "spring", stiffness: 280 }}
      className={`relative rounded-3xl p-7 transition
        ${hero
          ? "bg-[#4F46E5] text-white sp-best-pulse lg:scale-105 z-10"
          : "bg-white border border-slate-200 shadow-md hover:shadow-xl"}`}>
      {hero && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2
                          bg-amber-400 text-slate-900 text-[10px] font-black
                          tracking-widest uppercase px-3 py-1 rounded-full">
          Mais vendido
        </div>
      )}
      <div className={`text-sm font-bold ${hero ? "text-indigo-100" : "text-indigo-600"}`}>
        {plan.name || `Plano ${plan.speed_down_mbps}`}
      </div>
      <div className="mt-5">
        <span className="display text-7xl font-black leading-none">{speedLabel}</span>
        <span className={`ml-1 text-lg font-bold ${hero ? "text-indigo-100" : "text-slate-500"}`}>
          {speedUnit}
        </span>
      </div>
      <ul className={`mt-6 space-y-2 text-sm ${hero ? "text-indigo-100" : "text-slate-600"}`}>
        <li className="flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" /> Wi-Fi 6 incluso
        </li>
        <li className="flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" /> Instalação grátis
        </li>
        <li className="flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" /> 1 app à escolha
        </li>
        {speed >= 1000 && (
          <li className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4" /> Suporte prioritário
          </li>
        )}
      </ul>
      <div className="mt-7 flex items-baseline gap-1">
        <span className={`${hero ? "text-indigo-200" : "text-slate-500"} text-sm`}>R$</span>
        <span className="display text-5xl font-black">{Math.floor(plan.monthly_price)}</span>
        <span className={`${hero ? "text-indigo-200" : "text-slate-500"} text-lg font-bold`}>
          ,{cents}
        </span>
        <span className={`${hero ? "text-indigo-200" : "text-slate-500"} text-sm`}>/mês</span>
      </div>
      <a href={whats} target="_blank" rel="noopener noreferrer"
          data-testid={`plan-cta-${plan.id}`}
          className={`mt-6 block text-center rounded-xl py-3.5 px-4 text-sm
                        font-bold transition
                        ${hero
                          ? "bg-white text-[#4F46E5] hover:bg-indigo-50"
                          : "bg-slate-900 hover:bg-slate-800 text-white"}`}>
        Assinar agora →
      </a>
    </motion.div>
  );
}

/* === Calculator (what fits in X Mega) ========================== */
function Calculator() {
  const [speed, setSpeed] = useState(1000);
  const data = {
    500: { tvs: 5, ping: 14, calls: 8 },
    1000: { tvs: 12, ping: 9, calls: 18 },
    2000: { tvs: 25, ping: 6, calls: 35 },
    5000: { tvs: 60, ping: 3, calls: 80 },
  };
  const d = data[speed];
  return (
    <section className="py-24 px-6 lg:px-10 bg-slate-50">
      <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center">
        <div>
          <div className="eyebrow mb-3">O que cabe na sua casa</div>
          <h2 className="display text-4xl lg:text-5xl font-black text-slate-900
                           leading-tight">
            Veja o que sua família consegue fazer ao mesmo tempo.
          </h2>
          <p className="mt-4 text-slate-600">
            Escolha uma velocidade e simule o uso.
          </p>

          <div className="mt-8 flex flex-wrap gap-2">
            {[500, 1000, 2000, 5000].map((s) => (
              <button key={s} onClick={() => setSpeed(s)}
                       data-testid={`calc-${s}`}
                       className={`rounded-full px-5 py-2.5 text-sm font-bold
                                     transition
                                     ${speed === s
                                       ? "bg-[#4F46E5] text-white"
                                       : "bg-white text-slate-700 border border-slate-200 hover:border-indigo-300"}`}>
                {s >= 1000 ? `${s / 1000} Giga` : `${s} Mega`}
              </button>
            ))}
          </div>

          <div className="mt-10 grid grid-cols-3 gap-5">
            <CalcStat icon={Tv} value={d.tvs} label="TVs 4K simultâneas" />
            <CalcStat icon={Gamepad2} value={`${d.ping}ms`} label="Ping para jogos" />
            <CalcStat icon={Phone} value={d.calls} label="Vídeo chamadas" />
          </div>
        </div>
        <div className="relative">
          <div className="absolute -inset-6 rounded-[2.5rem]
                            bg-gradient-to-tr from-indigo-100 to-cyan-50 -z-10" />
          <img src="https://images.unsplash.com/photo-1758521541324-d304c5303fe5?crop=entropy&cs=srgb&fm=jpg&q=85&w=900"
                alt="Vídeo chamada"
                className="rounded-3xl shadow-2xl shadow-slate-300/40 w-full" />
        </div>
      </div>
    </section>
  );
}
function CalcStat({ icon: Ico, value, label }) {
  return (
    <motion.div key={value} initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="bg-white rounded-2xl p-5 border border-slate-200
                              shadow-sm">
      <Ico className="w-5 h-5 text-indigo-600 mb-3" />
      <div className="display text-3xl font-black text-slate-900">{value}</div>
      <div className="text-xs text-slate-500 mt-1 leading-tight">{label}</div>
    </motion.div>
  );
}

/* === Combos marquee ============================================ */
function CombosMarquee({ config }) {
  const combos = config.combos?.length ? config.combos : [
    { name: "Disney+" }, { name: "HBO Max" }, { name: "Globoplay" },
    { name: "Deezer" }, { name: "Sky+" }, { name: "Telefone Fixo" },
    { name: "Celular" }, { name: "Paramount+" }, { name: "Noggin" },
  ];
  // duplica pra criar loop infinito
  const items = [...combos, ...combos];
  return (
    <section id="combos" className="py-24 bg-[#4F46E5] text-white
                                       overflow-hidden">
      <div className="text-center max-w-3xl mx-auto px-6 mb-12">
        <div className="eyebrow mb-3" style={{ color: "#A5B4FC" }}>
          Combos disponíveis
        </div>
        <h2 className="display text-4xl lg:text-5xl font-black">
          Ainda melhor com seus streamings favoritos.
        </h2>
        <p className="mt-4 text-indigo-200">
          Adicione apps de streaming, TV digital ou telefonia ao seu plano.
        </p>
      </div>
      <div className="relative">
        <div className="flex sp-marquee-track gap-4 w-max">
          {items.map((c, i) => (
            <div key={i} className="shrink-0 px-8 py-6 bg-white/10
                                       backdrop-blur-sm rounded-2xl
                                       border border-white/20 min-w-[200px]
                                       text-center">
              <div className="text-3xl mb-2">{comboEmoji(c.name)}</div>
              <div className="font-bold text-sm">{c.name}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
function comboEmoji(n) {
  n = (n || "").toLowerCase();
  if (n.includes("disney")) return "";
  if (n.includes("hbo")) return "";
  if (n.includes("globo")) return "";
  if (n.includes("deezer") || n.includes("spotify")) return "";
  if (n.includes("sky")) return "";
  if (n.includes("paramount")) return "️";
  if (n.includes("noggin")) return "";
  if (n.includes("telefone")) return "️";
  if (n.includes("celular")) return "";
  return "✨";
}

/* === Why SmartProv ============================================= */
function WhySection() {
  const items = [
    { icon: Zap, title: "Fibra 100% pura até sua casa",
       desc: "FTTH ponta a ponta. Sem rádio, sem coaxial, sem perda." },
    { icon: ShieldCheck, title: "Estabilidade garantida",
       desc: "99.9% de uptime e SLA com multa contratual." },
    { icon: Clock, title: "Suporte humano em minutos",
       desc: "Atendimento 24/7 por WhatsApp, telefone e app." },
    { icon: Award, title: "Sem fidelidade obrigatória",
       desc: "Permanência opcional. Pague mais barato sem amarras." },
  ];
  return (
    <section id="beneficios" className="py-24 px-6 lg:px-10">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <div className="eyebrow mb-3">Por que SmartProv</div>
          <h2 className="display text-4xl lg:text-5xl font-black text-slate-900">
            Internet que não te dá raiva.
          </h2>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {items.map((it) => (
            <motion.div key={it.title}
              whileHover={{ y: -4 }}
              className="group p-7 rounded-2xl bg-white border border-slate-200
                           hover:border-indigo-300 hover:shadow-xl transition">
              <div className="w-12 h-12 rounded-xl bg-indigo-50
                                grid place-items-center
                                group-hover:bg-indigo-100 transition">
                <it.icon className="w-6 h-6 text-indigo-600" />
              </div>
              <h3 className="display text-lg font-bold text-slate-900 mt-5">
                {it.title}
              </h3>
              <p className="text-sm text-slate-600 mt-2 leading-relaxed">
                {it.desc}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* === Testimonials ============================================== */
function Testimonials() {
  const data = [
    { name: "Cláudia Mendes", bairro: "Copacabana", rating: 5,
      text: "Trocamos da operadora antiga e nunca mais tive Netflix travando.",
      avatar: "" },
    { name: "Roberto Silva", bairro: "Tijuca", rating: 5,
      text: "O técnico chegou no dia agendado e instalou em 1 hora. Recomendo.",
      avatar: "" },
    { name: "Patrícia Lima", bairro: "Barra da Tijuca", rating: 5,
      text: "Suporte resolve por WhatsApp em 5 minutos. Atendimento humano de verdade.",
      avatar: "" },
    { name: "André Oliveira", bairro: "Botafogo", rating: 5,
      text: "Plano de 1 giga, ping de 8ms jogando FPS. Internet de gamer.",
      avatar: "‍" },
  ];
  return (
    <section className="py-24 px-6 lg:px-10 bg-slate-50">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-14">
          <div className="eyebrow mb-3">Histórias reais</div>
          <h2 className="display text-4xl lg:text-5xl font-black text-slate-900">
            Quem assinou, indica.
          </h2>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {data.map((t) => (
            <motion.div key={t.name}
              whileHover={{ y: -4 }}
              className="bg-white rounded-2xl p-6 border border-slate-200
                          shadow-sm hover:shadow-md transition">
              <div className="flex gap-1 text-amber-400 mb-3">
                {Array(t.rating).fill(0).map((_, i) => (
                  <Star key={i} className="w-4 h-4 fill-current" />
                ))}
              </div>
              <p className="text-sm text-slate-700 leading-relaxed">
                “{t.text}”
              </p>
              <div className="mt-5 flex items-center gap-3 pt-4 border-t border-slate-100">
                <div className="w-10 h-10 rounded-full bg-indigo-50
                                  grid place-items-center text-xl">{t.avatar}</div>
                <div>
                  <div className="text-sm font-bold text-slate-900">{t.name}</div>
                  <div className="text-xs text-slate-500">{t.bairro}</div>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* === App Showcase ============================================== */
function AppShowcase({ config }) {
  return (
    <section className="py-24 px-6 lg:px-10">
      <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center">
        <div className="order-2 lg:order-1">
          <div className="eyebrow mb-3">Aplicativo móvel</div>
          <h2 className="display text-4xl lg:text-5xl font-black text-slate-900
                          leading-tight">
            Controle tudo na palma da mão.
          </h2>
          <p className="mt-5 text-slate-600 leading-relaxed">
            Emita 2ª via, teste a velocidade, abra chamado e desbloqueie sua
            internet sem ligar pra ninguém.
          </p>
          <ul className="mt-7 space-y-3">
            {["2ª via de boleto em 1 toque",
              "Teste de velocidade integrado",
              "Suporte por chat direto na lousa",
              "Desbloqueio imediato em emergência"].map((f) => (
              <li key={f} className="flex items-center gap-3 text-slate-700">
                <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0" />
                {f}
              </li>
            ))}
          </ul>
          <div className="mt-8 flex flex-wrap gap-3">
            {config.app_android_url && (
              <a href={config.app_android_url} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-5 py-3 rounded-xl
                              bg-slate-900 text-white text-sm font-bold
                              hover:bg-slate-800 transition">
                Google Play
              </a>
            )}
            {config.app_ios_url && (
              <a href={config.app_ios_url} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-5 py-3 rounded-xl
                              bg-slate-900 text-white text-sm font-bold
                              hover:bg-slate-800 transition">
                App Store
              </a>
            )}
            {!config.app_android_url && !config.app_ios_url && (
              <div className="text-sm text-slate-400">
                <Smartphone className="w-4 h-4 inline mr-2" />
                Em breve nas lojas
              </div>
            )}
          </div>
        </div>
        <div className="order-1 lg:order-2 relative">
          <motion.div whileInView={{ y: [20, 0] }}
                        viewport={{ once: true }}
                        transition={{ duration: 0.6 }}
                        className="relative max-w-sm mx-auto">
            <div className="absolute -inset-10 rounded-full
                              bg-gradient-to-br from-indigo-200 via-cyan-100
                              to-white blur-3xl -z-10" />
            <img src="https://static.prod-images.emergentagent.com/jobs/0f7afc70-e3c4-4925-8f2c-a35d20f80a39/images/1a0d4489bc4a26c2996824d43d00e18620e173b08aed3be3123db9623fe4e8d0.png"
                  alt="App SmartProv" className="w-full h-auto drop-shadow-2xl" />
          </motion.div>
        </div>
      </div>
    </section>
  );
}

/* === FAQ ======================================================= */
function FAQ() {
  const items = [
    { q: "Quanto tempo leva pra instalar?",
       a: "Após confirmação da viabilidade, agendamos a instalação em até 48h. O técnico leva em média 1 hora pra finalizar." },
    { q: "Preciso pagar taxa de adesão?",
       a: "Não. A instalação e o roteador Wi-Fi 6 são gratuitos. Você paga só a mensalidade." },
    { q: "Tenho fidelidade?",
       a: "Fidelidade é opcional. Se aceitar 12 meses, ganha desconto. Sem fidelidade, você cancela quando quiser." },
    { q: "Quanto custa pra mudar de endereço?",
       a: "Mudança dentro da área de cobertura é totalmente gratuita. Basta avisar a gente com 5 dias de antecedência." },
    { q: "Como funciona o suporte técnico?",
       a: "24/7 por WhatsApp, telefone (0800) e chat no app. SLA garantido em contrato com multa caso descumprido." },
  ];
  const [open, setOpen] = useState(0);
  return (
    <section id="faq" className="py-24 px-6 lg:px-10 bg-slate-50">
      <div className="max-w-3xl mx-auto">
        <div className="text-center mb-12">
          <div className="eyebrow mb-3">Perguntas frequentes</div>
          <h2 className="display text-4xl lg:text-5xl font-black text-slate-900">
            Dúvidas? A gente responde.
          </h2>
        </div>
        <div className="space-y-3">
          {items.map((it, i) => (
            <div key={i} data-testid={`faq-${i}`}
                  className="bg-white rounded-2xl border border-slate-200
                              overflow-hidden">
              <button onClick={() => setOpen(open === i ? -1 : i)}
                       className="w-full px-6 py-5 flex items-center justify-between
                                   text-left hover:bg-slate-50 transition">
                <span className="font-bold text-slate-900">{it.q}</span>
                <ChevronDown className={`w-5 h-5 text-slate-400 transition
                                            ${open === i ? "rotate-180" : ""}`} />
              </button>
              {open === i && (
                <motion.div initial={{ height: 0, opacity: 0 }}
                              animate={{ height: "auto", opacity: 1 }}
                              className="px-6 pb-5 text-sm text-slate-600 leading-relaxed">
                  {it.a}
                </motion.div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* === Lead Form Section ========================================= */
function LeadFormSection({ config, plans }) {
  const [form, setForm] = useState({
    name: "", email: "", phone: "", plan_interest: "", address: "",
  });
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.phone.trim()) {
      setErr("Preencha nome e telefone."); return;
    }
    setBusy(true); setErr("");
    try {
      await axios.post(`${BACKEND}/api/site/leads`, form);
      setSent(true);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };
  return (
    <section id="lead" className="py-24 px-6 lg:px-10 bg-slate-900 text-white
                                     relative overflow-hidden">
      <div aria-hidden className="absolute -top-32 -right-32 w-[500px] h-[500px]
                                     rounded-full opacity-20 blur-3xl"
            style={{ background: "radial-gradient(circle, #06B6D4 0%, transparent 70%)" }} />
      <div aria-hidden className="absolute -bottom-32 -left-32 w-[500px] h-[500px]
                                     rounded-full opacity-20 blur-3xl"
            style={{ background: "radial-gradient(circle, #4F46E5 0%, transparent 70%)" }} />
      <div className="relative max-w-3xl mx-auto text-center mb-12">
        <div className="eyebrow mb-3" style={{ color: "#A5B4FC" }}>
          Última chamada
        </div>
        <h2 className="display text-4xl lg:text-5xl font-black">
          Pronto pra trocar de provedor?
        </h2>
        <p className="mt-4 text-slate-300">
          Deixe seu contato e a gente liga em 1 hora pra confirmar a viabilidade.
        </p>
      </div>
      <div className="relative max-w-2xl mx-auto">
        {sent ? (
          <motion.div initial={{ scale: 0.9, opacity: 0 }}
                       animate={{ scale: 1, opacity: 1 }}
                       data-testid="lead-form-success"
                       className="bg-emerald-500/20 border border-emerald-400/40
                                   rounded-3xl p-10 text-center">
            <CheckCircle2 className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
            <h3 className="display text-2xl font-bold">
              Recebemos seu pedido!
            </h3>
            <p className="mt-3 text-emerald-200">
              Em até 1 hora você recebe uma mensagem no WhatsApp pra confirmar
              cobertura e finalizar a contratação.
            </p>
          </motion.div>
        ) : (
          <form onSubmit={submit} data-testid="lead-form"
                 className="bg-white/5 backdrop-blur-md border border-white/10
                             rounded-3xl p-8 space-y-4">
            <input data-testid="lead-name" required value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="Seu nome completo *"
                    className="w-full px-5 py-4 rounded-xl bg-white/10
                                border border-white/20 placeholder:text-slate-400
                                text-white outline-none focus:border-indigo-400
                                transition" />
            <div className="grid sm:grid-cols-2 gap-4">
              <input data-testid="lead-email" type="email" value={form.email}
                      onChange={(e) => setForm({ ...form, email: e.target.value })}
                      placeholder="E-mail (opcional)"
                      className="px-5 py-4 rounded-xl bg-white/10
                                  border border-white/20 placeholder:text-slate-400
                                  text-white outline-none focus:border-indigo-400
                                  transition" />
              <input data-testid="lead-phone" required value={form.phone}
                      onChange={(e) => setForm({ ...form, phone: e.target.value })}
                      placeholder="Telefone / WhatsApp *"
                      className="px-5 py-4 rounded-xl bg-white/10
                                  border border-white/20 placeholder:text-slate-400
                                  text-white outline-none focus:border-indigo-400
                                  transition" />
            </div>
            <select data-testid="lead-plan" value={form.plan_interest}
                     onChange={(e) => setForm({
                       ...form, plan_interest: e.target.value })}
                     className="w-full px-5 py-4 rounded-xl bg-white/10
                                 border border-white/20 text-white outline-none
                                 focus:border-indigo-400 transition">
              <option value="" className="text-slate-900">Plano de interesse</option>
              {plans.map((p) => (
                <option key={p.id} value={p.name} className="text-slate-900">
                  {p.name} ({p.speed_down_mbps} Mbps · R$ {p.monthly_price.toFixed(2)})
                </option>
              ))}
            </select>
            <input data-testid="lead-address" value={form.address}
                    onChange={(e) => setForm({ ...form, address: e.target.value })}
                    placeholder="Endereço (rua, nº, bairro, cidade)"
                    className="w-full px-5 py-4 rounded-xl bg-white/10
                                border border-white/20 placeholder:text-slate-400
                                text-white outline-none focus:border-indigo-400
                                transition" />
            {err && (
              <div className="px-5 py-3 rounded-xl bg-red-500/20 border border-red-400/30
                                text-red-200 text-sm">{err}</div>
            )}
            <button type="submit" disabled={busy} data-testid="lead-submit"
                     className="w-full py-4 rounded-xl bg-[#4F46E5]
                                 hover:bg-[#4338CA] text-white font-bold
                                 transition shadow-xl shadow-indigo-500/30
                                 inline-flex items-center justify-center gap-2">
              {busy ? "Enviando…" : <>
                Quero assinar agora <ArrowRight className="w-5 h-5" />
              </>}
            </button>
            <p className="text-xs text-slate-400 text-center">
              Ao enviar, você concorda em receber contato comercial.
            </p>
          </form>
        )}
      </div>
    </section>
  );
}

/* === Footer ==================================================== */
function Footer({ config }) {
  return (
    <footer className="bg-slate-950 text-slate-400 py-16 px-6 lg:px-10">
      <div className="max-w-7xl mx-auto grid md:grid-cols-4 gap-10">
        <div>
          <div className="display text-2xl font-black tracking-tighter text-white">
            <span style={{ color: "#818CF8" }}>Smart</span>Prov
          </div>
          <p className="text-sm mt-4 leading-relaxed">
            Internet de fibra ótica pura, pra quem não aceita conexão ruim.
          </p>
        </div>
        <div>
          <div className="text-white font-bold text-sm mb-4">Atendimento</div>
          <div className="text-sm space-y-2">
            <div>{config.phone_0800}</div>
            <div>{config.email}</div>
            <div>24/7 via WhatsApp</div>
          </div>
        </div>
        <div>
          <div className="text-white font-bold text-sm mb-4">Atalhos</div>
          <ul className="text-sm space-y-2">
            <li><a href="#planos" className="hover:text-white transition">Planos</a></li>
            <li><a href="#combos" className="hover:text-white transition">Combos</a></li>
            <li><a href="#faq" className="hover:text-white transition">FAQ</a></li>
            {config.central_url && (
              <li><a href={config.central_url} className="hover:text-white transition">
                Central do Assinante
              </a></li>
            )}
          </ul>
        </div>
        <div>
          <div className="text-white font-bold text-sm mb-4">Legal</div>
          <div className="text-xs space-y-2 leading-relaxed">
            <div>CNPJ: {config.cnpj}</div>
            {config.anatel && <div>{config.anatel}</div>}
            <div>Provedor licenciado pela ANATEL.</div>
          </div>
        </div>
      </div>
      <div className="max-w-7xl mx-auto mt-12 pt-8 border-t border-slate-800
                       text-center text-xs">
        © {new Date().getFullYear()} {config.site_name}. Todos os direitos reservados.
      </div>
    </footer>
  );
}

/* === WhatsApp floating button ================================== */
function WhatsAppFloating({ config }) {
  const whats = waLink(config.phone_whatsapp,
    "Olá! Vim do site e quero falar com vocês.");
  return (
    <a href={whats} target="_blank" rel="noopener noreferrer"
        data-testid="whatsapp-floating-btn"
        aria-label="Falar no WhatsApp"
        className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full
                    bg-[#25D366] hover:bg-[#20BD5A] shadow-2xl
                    grid place-items-center transition
                    sp-whats-pulse">
      <MessageCircle className="w-7 h-7 text-white" fill="currentColor" />
    </a>
  );
}

/* === Helpers =================================================== */
function waLink(phone, text) {
  const digits = (phone || "").replace(/\D/g, "");
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}
