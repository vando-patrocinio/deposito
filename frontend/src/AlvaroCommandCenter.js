/* AlvaroCommandCenter.js — Constituição V5.1 / Fase 7
   Tela única com 10 cards. Cada card obrigatoriamente exibe:
   PROBLEMA / CAUSA / IMPACTO / AÇÃO / CONFIANÇA / EVIDÊNCIA. */
import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle }
  from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;
const token = () => localStorage.getItem("ponto_token") || "";

const fetchJSON = async (path) => {
  const r = await fetch(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token()}` },
  });
  if (!r.ok) throw new Error(`HTTP ${r.status} on ${path}`);
  return r.json();
};

const ConfidenceBar = ({ value }) => {
  const pct = Math.round((value || 0) * 100);
  const color = pct >= 80 ? "bg-emerald-500"
    : pct >= 60 ? "bg-amber-500"
    : "bg-rose-500";
  return (
    <div className="flex items-center gap-2"
      data-testid={`alvaro-cc-confidence-${pct}`}>
      <div className="h-1.5 w-24 rounded-full bg-slate-200
        overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium text-slate-600">
        {pct}%
      </span>
    </div>
  );
};

const CommandCard = ({ card }) => {
  const lvl = card.confidence >= 0.85 ? "alta"
    : card.confidence >= 0.65 ? "média" : "baixa";
  const variants = {
    alta: "bg-emerald-50 border-emerald-200 text-emerald-700",
    "média": "bg-amber-50 border-amber-200 text-amber-700",
    baixa: "bg-rose-50 border-rose-200 text-rose-700",
  };
  return (
    <Card className="border-slate-200 shadow-sm hover:shadow-md
      transition-shadow"
      data-testid={`alvaro-cc-card-${card.title.toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")}`}>
      <CardHeader className="pb-3 border-b border-slate-100">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-base font-semibold
            text-slate-900">
            {card.title}
          </CardTitle>
          <Badge className={`text-[10px] uppercase tracking-wide
            border ${variants[lvl]}`}>
            confiança {lvl}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-4 space-y-3 text-sm">
        <Row label="PROBLEMA" value={card.problem}
          testid={`problem-${card.title}`} />
        <Row label="CAUSA"    value={card.cause} />
        <Row label="IMPACTO"  value={card.impact} accent="text-rose-700" />
        <Row label="AÇÃO"     value={card.action} accent="text-emerald-700"
          bold />
        <div className="pt-2 border-t border-slate-100">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-semibold uppercase
              tracking-wider text-slate-500">
              EVIDÊNCIA
            </span>
            <ConfidenceBar value={card.confidence} />
          </div>
          <ul className="mt-1 space-y-1 max-h-24 overflow-y-auto">
            {(card.evidence || []).slice(0, 5).map((e, i) => (
              <li key={i} className="text-xs text-slate-600
                flex items-start gap-2">
                <span className="text-slate-400">•</span>
                <span>
                  <strong>{e.type}</strong>:{" "}
                  {String(e.value)}{" "}
                  {e.source && (
                    <span className="text-slate-400">
                      ({e.source})
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
};

const Row = ({ label, value, accent = "text-slate-700",
                bold = false, testid }) => (
  <div data-testid={testid ? `alvaro-cc-${testid}` : undefined}>
    <div className="text-[10px] font-semibold uppercase tracking-wider
      text-slate-500 mb-0.5">{label}</div>
    <div className={`${accent} ${bold ? "font-semibold" : ""}
      leading-snug`}>
      {value || "—"}
    </div>
  </div>
);

const AlvaroCommandCenter = () => {
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const load = async () => {
    try {
      setError(null);
      const data = await fetchJSON(
        "/api/ai-center/v51/command-center?window_days=30");
      setCards(data.cards || []);
    } catch (e) {
      setError(e.message);
      toast.error(`Erro ao carregar Command Center: ${e.message}`);
    }
  };

  useEffect(() => {
    (async () => {
      setLoading(true);
      await load();
      setLoading(false);
    })();
  }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
    toast.success("Command Center atualizado");
  };

  const onTriggerDrive = async () => {
    try {
      setRefreshing(true);
      const r = await fetch(
        `${API}/api/ai-center/failure-risk/drive?limit=200&only_changed=true`,
        { method: "POST",
          headers: { Authorization: `Bearer ${token()}` } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const out = await r.json();
      toast.success(
        `Drive disparado: ${out.preventive_cycles_triggered} ciclos preventivos`);
      await load();
    } catch (e) {
      toast.error(`Erro ao disparar drive: ${e.message}`);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="space-y-5 px-1" data-testid="alvaro-command-center">
      <header className="flex items-center justify-between
        flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight
            text-slate-900">
            Álvaro Command Center
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">
            10 frentes operacionais · cada decisão expõe causa, impacto,
            ação e evidência (Regra de Ouro · V5.0/J).
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={onTriggerDrive} disabled={refreshing}
            variant="default"
            data-testid="alvaro-cc-trigger-drive"
            className="bg-emerald-600 hover:bg-emerald-700">
            {refreshing ? "Processando..." : "Disparar Prevenção"}
          </Button>
          <Button onClick={onRefresh} disabled={refreshing}
            variant="outline"
            data-testid="alvaro-cc-refresh">
            {refreshing ? "Atualizando..." : "Atualizar"}
          </Button>
        </div>
      </header>

      {error && (
        <div className="rounded-md border border-rose-200 bg-rose-50
          px-4 py-2 text-sm text-rose-700"
          data-testid="alvaro-cc-error">
          {error}
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2
          xl:grid-cols-3 gap-4">
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="h-64 w-full rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2
          xl:grid-cols-3 gap-4"
          data-testid="alvaro-cc-grid">
          {cards.map((c, i) => (
            <CommandCard key={i} card={c} />
          ))}
        </div>
      )}
    </div>
  );
};

export default AlvaroCommandCenter;
