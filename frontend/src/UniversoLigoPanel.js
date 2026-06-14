/**
 * Universo Ligo — painel anfitriã.
 * Distribuição de níveis + campanhas Experience Commander com Human Gate.
 */
import React, { useEffect, useState } from "react";
import { Button } from "./components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./components/ui/tabs";
import { Badge } from "./components/ui/badge";
import { api } from "./api";
import { toast } from "sonner";

const BRL = (v) =>
  Number(v || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", maximumFractionDigits: 2,
  });

const LEVEL_COLORS = {
  explorador: "#7c8da3",
  cometa: "#3aa1ff",
  orbita: "#8a5cf6",
  estelar: "#e63cb9",
  galaxia_ouro: "#f5b94a",
  universo_ligo: "#10e6c2",
};

const STATUS_LABEL = {
  DRAFT: { label: "Rascunho", variant: "outline" },
  READY: { label: "Pronto (L1)", variant: "secondary" },
  AWAITING_APPROVAL: { label: "Aguarda aprovação", variant: "destructive" },
  APPROVED: { label: "Aprovado", variant: "default" },
  SCHEDULED: { label: "Agendado", variant: "secondary" },
  EXECUTED: { label: "Enviado", variant: "default" },
  CANCELLED: { label: "Cancelado", variant: "outline" },
};

function Card({ children, testid, className = "" }) {
  return (
    <div
      className={`rounded-xl border border-zinc-200 bg-white p-5 ${className}`}
      data-testid={testid}
    >
      {children}
    </div>
  );
}

function LevelBar({ panel }) {
  if (!panel) return null;
  const total = panel.n_total || 1;
  return (
    <Card testid="ul-level-bar" className="mb-6">
      <div className="text-xs uppercase text-zinc-500 mb-2">
        Distribuição por nível ({total.toLocaleString("pt-BR")} clientes)
      </div>
      <div className="flex h-8 rounded-lg overflow-hidden bg-zinc-100">
        {(panel.distribution || []).map((d) => {
          const lvl = panel.levels.find((l) => l.id === d.level_id);
          const pct = (d.n_subscribers / total) * 100;
          return (
            <div
              key={d.level_id}
              title={`${d.level_name}: ${d.n_subscribers}`}
              style={{
                width: `${pct}%`,
                backgroundColor: LEVEL_COLORS[lvl?.key] || "#444",
              }}
              data-testid={`ul-bar-${lvl?.key}`}
            />
          );
        })}
      </div>
      <div className="grid grid-cols-3 md:grid-cols-6 gap-2 mt-3">
        {(panel.distribution || []).map((d) => {
          const lvl = panel.levels.find((l) => l.id === d.level_id);
          return (
            <div
              key={d.level_id}
              className="text-xs flex items-center gap-2"
              data-testid={`ul-legend-${lvl?.key}`}
            >
              <div
                style={{ backgroundColor: LEVEL_COLORS[lvl?.key] || "#444" }}
                className="w-3 h-3 rounded-sm"
              />
              <span className="text-zinc-700 truncate">
                {d.level_name}{" "}
                <span className="text-zinc-500">
                  · {d.n_subscribers.toLocaleString("pt-BR")}
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function IdentifyTab() {
  const [phone, setPhone] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const lookup = async () => {
    if (!phone.trim()) return;
    setLoading(true);
    try {
      const r = await api.ulIdentify({ phone: phone.trim() });
      setResult(r);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Não encontrado");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };
  return (
    <div data-testid="ul-tab-identify">
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="Telefone (com DDD)"
            className="flex-1 bg-white border border-zinc-300 rounded-md px-3 py-2 text-zinc-900"
            data-testid="ul-identify-phone-input"
          />
          <Button onClick={lookup} data-testid="ul-identify-btn">
            {loading ? "Buscando..." : "Identificar"}
          </Button>
        </div>
        {result && (
          <div className="border-t border-zinc-200 pt-4" data-testid="ul-identify-result">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-lg font-semibold text-zinc-900">
                  {result.name}
                </div>
                <div className="text-xs text-zinc-500">
                  {result.external_code} · {result.phone}
                </div>
              </div>
              <Badge
                style={{
                  backgroundColor:
                    LEVEL_COLORS[result.universo_ligo?.level_key] || "#444",
                  color: "#000",
                }}
              >
                {result.universo_ligo?.level_name}
              </Badge>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div>
                <div className="text-zinc-500 text-xs">Plano</div>
                <div className="text-zinc-800">{result.plan_name || "—"}</div>
              </div>
              <div>
                <div className="text-zinc-500 text-xs">Score</div>
                <div className="text-zinc-800">
                  {result.universo_ligo?.score?.toFixed(1)}
                </div>
              </div>
              <div>
                <div className="text-zinc-500 text-xs">Tempo de casa</div>
                <div className="text-zinc-800">
                  {result.universo_ligo?.factors?.tempo_casa_meses || 0} meses
                </div>
              </div>
              <div>
                <div className="text-zinc-500 text-xs">Faturas em dia</div>
                <div className="text-zinc-800">
                  {result.universo_ligo?.factors?.pagamentos_em_dia || 0}
                </div>
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function CampaignsTab() {
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("AWAITING_APPROVAL");
  const [scanning, setScanning] = useState(false);
  const load = async () => {
    try {
      const r = await api.expListCampaigns({
        status: statusFilter,
        limit: 100,
      });
      setItems(r.items || []);
    } catch (e) {
      toast.error("Falha ao carregar campanhas");
    }
  };
  useEffect(() => {
    load();
  }, [statusFilter]);

  const scan = async () => {
    setScanning(true);
    try {
      const r = await api.expScan();
      toast.success(
        `Scan: ${r.totals.total} drafts (aniv=${r.totals.anniversaries} · niv=${r.totals.level_ups} · inc=${r.totals.incidents_resolved})`
      );
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Falha no scan");
    } finally {
      setScanning(false);
    }
  };
  const approve = async (id) => {
    try {
      await api.expApproveCampaign(id, "via console");
      toast.success("Campanha aprovada");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Sem permissão");
    }
  };
  const execute = async (id) => {
    try {
      const r = await api.expExecuteCampaign(id);
      toast.success(`Enviado ${r.status}`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Falha");
    }
  };
  const cancel = async (id) => {
    try {
      await api.expCancelCampaign(id, "cancelado pelo console");
      await load();
    } catch (e) {
      toast.error("Falha");
    }
  };
  const council = async (id) => {
    try {
      const p = await api.expCouncilReview(id);
      toast.success(`${p.recomendacao.toUpperCase()} · risco ${p.risco}`);
    } catch (e) {
      toast.error("Falha");
    }
  };

  return (
    <div data-testid="ul-tab-campaigns">
      <div className="flex items-center justify-between mb-4 gap-3">
        <div className="flex gap-2 flex-wrap">
          {Object.keys(STATUS_LABEL).map((s) => (
            <Button
              key={s}
              size="sm"
              variant={statusFilter === s ? "default" : "outline"}
              onClick={() => setStatusFilter(s)}
              data-testid={`ul-filter-${s}`}
            >
              {STATUS_LABEL[s].label}
            </Button>
          ))}
        </div>
        <Button onClick={scan} data-testid="ul-scan-btn">
          {scanning ? "Detectando..." : "Detectar eventos"}
        </Button>
      </div>
      {items.length === 0 ? (
        <div className="text-zinc-500 text-sm text-center py-12">
          Sem campanhas neste status.
        </div>
      ) : (
        items.map((c) => (
          <Card key={c.id} testid={`ul-camp-${c.id}`} className="mb-3">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <Badge variant={STATUS_LABEL[c.status]?.variant || "outline"}>
                    {STATUS_LABEL[c.status]?.label || c.status}
                  </Badge>
                  <Badge variant="outline" className="text-xs">
                    L{c.approval_level} · {c.approval_role}
                  </Badge>
                  <Badge variant="secondary" className="text-xs">
                    {c.event_key}
                  </Badge>
                  {c.auto_execute && (
                    <Badge variant="default" className="text-xs">
                      auto
                    </Badge>
                  )}
                </div>
                <div className="text-zinc-800 font-semibold truncate">
                  {c.target_label}{" "}
                  <span className="text-xs text-zinc-500">
                    {c.target_phone}
                  </span>
                </div>
                <div className="text-sm text-zinc-600 mt-1 italic">
                  “{c.message}”
                </div>
                <div className="text-xs text-zinc-500 mt-2 flex gap-4">
                  <span>
                    Custo: <span className="text-zinc-700">{BRL(c.estimated_cost_brl)}</span>
                  </span>
                  <span>
                    ROI esperado:{" "}
                    <span className="text-emerald-600">{BRL(c.expected_roi_brl)}</span>
                  </span>
                </div>
                {c.message_warnings && c.message_warnings.length > 0 && (
                  <div className="text-xs text-rose-600 mt-1">
                    ⚠ {c.message_warnings.join(" · ")}
                  </div>
                )}
                {c.council_review && (
                  <div className="text-xs text-zinc-500 mt-2 border-t border-zinc-200 pt-2">
                    <strong>Conselho:</strong>{" "}
                    {c.council_review.recomendacao.toUpperCase()} · risco{" "}
                    {c.council_review.risco}
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-2 shrink-0">
                {c.status === "AWAITING_APPROVAL" && (
                  <Button
                    size="sm"
                    onClick={() => approve(c.id)}
                    data-testid={`ul-approve-${c.id}`}
                  >
                    Aprovar
                  </Button>
                )}
                {(c.status === "APPROVED" || c.status === "READY") && (
                  <Button
                    size="sm"
                    onClick={() => execute(c.id)}
                    data-testid={`ul-execute-${c.id}`}
                  >
                    Enviar
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => council(c.id)}
                  data-testid={`ul-council-${c.id}`}
                >
                  Parecer
                </Button>
                {c.status !== "EXECUTED" && c.status !== "CANCELLED" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => cancel(c.id)}
                    data-testid={`ul-cancel-${c.id}`}
                  >
                    Cancelar
                  </Button>
                )}
              </div>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}

export default function UniversoLigoPanel() {
  const [panel, setPanel] = useState(null);
  const load = async () => {
    try {
      const p = await api.ulPanel();
      setPanel(p);
    } catch (e) {
      toast.error("Falha ao carregar painel");
    }
  };
  useEffect(() => {
    load();
  }, []);

  const refresh = async () => {
    try {
      const r = await api.ulRefreshAll();
      toast.success(
        `Recalculado: ${r.refreshed} · mudanças de nível: ${r.level_changes}`
      );
      await load();
    } catch (e) {
      toast.error("Falha no refresh");
    }
  };

  return (
    <div className="p-6 bg-white min-h-screen" data-testid="universo-ligo-panel">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Universo Ligo</h1>
          <p className="text-zinc-600 text-sm mt-1">
            Anfitriã da comunidade · níveis · Experience Commander · Human
            Authorization Gate
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={refresh} data-testid="ul-refresh-all">
            Recalcular níveis
          </Button>
        </div>
      </div>
      <LevelBar panel={panel} />
      <Tabs defaultValue="campaigns" className="w-full">
        <TabsList className="mb-4" data-testid="ul-tabs">
          <TabsTrigger value="campaigns" data-testid="ul-tab-campaigns-tab">
            Campanhas
          </TabsTrigger>
          <TabsTrigger value="identify" data-testid="ul-tab-identify-tab">
            Identificar cliente
          </TabsTrigger>
        </TabsList>
        <TabsContent value="campaigns">
          <CampaignsTab />
        </TabsContent>
        <TabsContent value="identify">
          <IdentifyTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
