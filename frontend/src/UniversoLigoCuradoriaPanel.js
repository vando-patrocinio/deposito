/**
 * Universo Ligo — Curadoria de Fundadores.
 *
 * Painel CRM-style (sem gamificação, sem ranking, sem score).
 *
 * Funcionalidades:
 *  - Lista TOP 10 fundadores com status atual de validação
 *  - Validar APTO/REVISAR/NÃO CONVIDAR com motivo obrigatório
 *  - Registrar convite com canal e notas
 *  - Marcar DNC (Do Not Contact) permanente
 *  - Capturar NPS mínimo (0-10) por cliente
 *  - Inspecionar guard log de tenants sintéticos
 */
import React, { useEffect, useState, useCallback } from "react";
import { Button } from "./components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./components/ui/tabs";
import { Badge } from "./components/ui/badge";
import { Textarea } from "./components/ui/textarea";
import { Input } from "./components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "./components/ui/select";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "./components/ui/dialog";
import { client } from "./api";
import { toast } from "sonner";

const decisionLabel = {
  APTO: { label: "APTO", color: "bg-emerald-100 text-emerald-700 border-emerald-300" },
  REVISAR: { label: "REVISAR", color: "bg-amber-100 text-amber-700 border-amber-300" },
  NAO_CONVIDAR: { label: "NÃO CONVIDAR", color: "bg-rose-100 text-rose-700 border-rose-300" },
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

function FieldRow({ label, value, testid }) {
  return (
    <div className="flex justify-between text-sm py-1 border-b border-zinc-100 last:border-0">
      <span className="text-zinc-500">{label}</span>
      <span className="font-medium text-zinc-900" data-testid={testid}>{value}</span>
    </div>
  );
}

function ValidationDialog({ open, onOpenChange, founder, onSaved }) {
  const [decision, setDecision] = useState("APTO");
  const [reason, setReason] = useState("");
  const [confidence, setConfidence] = useState("alta");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && founder?.validation) {
      setDecision(founder.validation.decision || "APTO");
      setReason(founder.validation.decision_reason || "");
      setConfidence(founder.validation.confidence || "alta");
    } else if (open) {
      setDecision("APTO");
      setReason("");
      setConfidence("alta");
    }
  }, [open, founder]);

  async function save() {
    if (!reason || reason.trim().length < 5) {
      toast.error("Motivo da decisão é obrigatório (mínimo 5 caracteres)");
      return;
    }
    setSaving(true);
    try {
      const r = await client.post("/universo-ligo/curadoria/validate", {
          document: founder.document,
          decision,
          decision_reason: reason.trim(),
          confidence,
          invite_source: "fundador",
      }).then(r => r.data);
      if (r?.ok) {
        toast.success(`Salvo: ${r.status}`);
        onSaved?.();
        onOpenChange(false);
      } else {
        toast.error("Não foi possível salvar");
      }
    } catch (e) {
      toast.error(String(e?.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="validation-dialog" className="max-w-md">
        <DialogHeader>
          <DialogTitle>Validar fundador</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="text-sm">
            <div className="font-medium text-zinc-900">{founder?.name}</div>
            <div className="text-zinc-500">{founder?.district} · {founder?.city}</div>
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Decisão</label>
            <Select value={decision} onValueChange={setDecision}>
              <SelectTrigger data-testid="select-decision">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="APTO">APTO — pode receber convite</SelectItem>
                <SelectItem value="REVISAR">REVISAR — precisa segunda opinião</SelectItem>
                <SelectItem value="NAO_CONVIDAR">NÃO CONVIDAR — atrito ou inconsistência</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">
              Motivo da decisão <span className="text-rose-600">*obrigatório</span>
            </label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Ex: Cliente extremamente satisfeito / Cliente passou por problema grave em 2025 / Cadastro inconsistente…"
              rows={4}
              data-testid="textarea-reason"
            />
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Confiança dos dados</label>
            <Select value={confidence} onValueChange={setConfidence}>
              <SelectTrigger data-testid="select-confidence">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="alta">alta</SelectItem>
                <SelectItem value="media">média</SelectItem>
                <SelectItem value="baixa">baixa</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            data-testid="btn-validation-cancel"
          >
            Cancelar
          </Button>
          <Button
            onClick={save}
            disabled={saving}
            data-testid="btn-validation-save"
          >
            {saving ? "Salvando…" : "Salvar carimbo"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DncDialog({ open, onOpenChange, founder, onSaved }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setReason("");
  }, [open]);

  async function save() {
    if (!reason || reason.trim().length < 3) {
      toast.error("Motivo do DNC é obrigatório (mínimo 3 caracteres)");
      return;
    }
    setSaving(true);
    try {
      const r = await client.post("/universo-ligo/curadoria/dnc", {
        document: founder.document, reason: reason.trim(),
      }).then(r => r.data);
      if (r?.ok) {
        toast.success("DNC permanente registrado");
        onSaved?.();
        onOpenChange(false);
      }
    } catch (e) {
      toast.error(String(e?.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="dnc-dialog" className="max-w-md">
        <DialogHeader>
          <DialogTitle>Marcar Do Not Contact</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="rounded-md bg-rose-50 border border-rose-200 p-3 text-sm text-rose-800">
            ⚠️ DNC é <strong>definitivo</strong>. O cliente sai de toda comunicação Universo Ligo permanentemente.
            Não bloqueia operacional (boleto, suporte). Não há &quot;desmarcar&quot; via interface.
          </div>
          <div className="text-sm">
            <div className="font-medium text-zinc-900">{founder?.name}</div>
            <div className="text-zinc-500">{founder?.document_masked}</div>
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">
              Motivo do DNC <span className="text-rose-600">*obrigatório</span>
            </label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Cliente pediu para não receber. Liguei, ouvi, respeitei."
              rows={3}
              data-testid="textarea-dnc-reason"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} data-testid="btn-dnc-cancel">
            Cancelar
          </Button>
          <Button
            onClick={save}
            disabled={saving}
            className="bg-rose-600 hover:bg-rose-700 text-white"
            data-testid="btn-dnc-save"
          >
            {saving ? "Salvando…" : "Confirmar DNC"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FounderCard({ f, onValidate, onDnc, onInvite }) {
  const v = f.validation;
  const decisionTag = v?.decision ? decisionLabel[v.decision] : null;
  const isDnc = v?.status === "do_not_contact";
  const isAccepted = v?.status === "accepted";

  return (
    <Card testid={`founder-card-${f.document_masked}`} className="hover:shadow-sm transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="text-base font-semibold text-zinc-900" data-testid="founder-name">
            {f.name}
          </div>
          <div className="text-xs text-zinc-500">
            {f.district} · {f.city}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          {decisionTag && (
            <span className={`text-xs px-2 py-0.5 rounded-full border ${decisionTag.color}`}>
              {decisionTag.label}
            </span>
          )}
          {isAccepted && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300">
              aceito
            </span>
          )}
          {isDnc && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-200 text-zinc-700 border border-zinc-300">
              DNC permanente
            </span>
          )}
        </div>
      </div>

      <div className="text-sm space-y-0">
        <FieldRow label="Registro" value={f.first_reg} testid="field-reg" />
        <FieldRow label="Faturas pagas" value={f.paid} testid="field-paid" />
        <FieldRow label="Tickets encerrados" value={f.tickets_closed} testid="field-tc" />
        <FieldRow label="CPF" value={f.document_masked} testid="field-doc" />
        <FieldRow label="Telefone" value={f.phone_masked} testid="field-phone" />
        {v?.decision_reason && (
          <div className="pt-2 mt-2 border-t border-zinc-100">
            <div className="text-xs text-zinc-500 mb-1">Motivo da última decisão</div>
            <div className="text-xs text-zinc-700 italic" data-testid="last-reason">
              {`"${v.decision_reason}"`}
            </div>
            <div className="text-[10px] text-zinc-400 mt-1">
              por {v.validated_by} · {v.validated_at?.slice(0, 16)}
            </div>
          </div>
        )}
      </div>

      <div className="flex gap-2 mt-4">
        <Button
          size="sm"
          variant="outline"
          onClick={() => onValidate(f)}
          disabled={isDnc}
          data-testid="btn-validate"
        >
          {v ? "Re-validar" : "Validar"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onInvite(f)}
          disabled={v?.decision !== "APTO" || isDnc}
          data-testid="btn-invite"
        >
          Registrar convite
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onDnc(f)}
          disabled={isDnc}
          className="text-rose-600 hover:bg-rose-50 ml-auto"
          data-testid="btn-dnc"
        >
          DNC
        </Button>
      </div>
    </Card>
  );
}

function InviteDialog({ open, onOpenChange, founder, onSaved }) {
  const [channel, setChannel] = useState("call");
  const [notes, setNotes] = useState("");
  const [outcome, setOutcome] = useState("invited_pending");
  const [declineReason, setDeclineReason] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setChannel("call");
      setNotes("");
      setOutcome("invited_pending");
      setDeclineReason("");
    }
  }, [open]);

  async function save() {
    setSaving(true);
    try {
      const r = await client.post("/universo-ligo/curadoria/invite", {
          document: founder.document,
          channel,
          notes: notes.trim() || null,
          accepted: outcome === "accepted",
          declined: outcome === "declined",
          decline_reason: outcome === "declined" ? declineReason.trim() : null,
      }).then(r => r.data);
      if (r?.ok) {
        toast.success(`Convite registrado (${r.status})`);
        onSaved?.();
        onOpenChange(false);
      }
    } catch (e) {
      toast.error(String(e?.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="invite-dialog" className="max-w-md">
        <DialogHeader>
          <DialogTitle>Registrar convite</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="text-sm">
            <div className="font-medium text-zinc-900">{founder?.name}</div>
            <div className="text-zinc-500">{founder?.district} · {founder?.city}</div>
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Canal usado</label>
            <Select value={channel} onValueChange={setChannel}>
              <SelectTrigger data-testid="select-channel">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="call">Ligação</SelectItem>
                <SelectItem value="wa">WhatsApp pessoal</SelectItem>
                <SelectItem value="visita">Visita / encontro</SelectItem>
                <SelectItem value="manual">Outro</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Resultado</label>
            <Select value={outcome} onValueChange={setOutcome}>
              <SelectTrigger data-testid="select-outcome">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="invited_pending">Contato feito — pendente resposta</SelectItem>
                <SelectItem value="accepted">Topou — entrou na comunidade</SelectItem>
                <SelectItem value="declined">Recusou educadamente</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {outcome === "declined" && (
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Motivo da recusa (opcional)</label>
              <Input
                value={declineReason}
                onChange={(e) => setDeclineReason(e.target.value)}
                data-testid="input-decline-reason"
              />
            </div>
          )}
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Notas do convidador</label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="O que o cliente falou, como reagiu, próximo contato combinado…"
              data-testid="textarea-invite-notes"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} data-testid="btn-invite-cancel">
            Cancelar
          </Button>
          <Button onClick={save} disabled={saving} data-testid="btn-invite-save">
            {saving ? "Salvando…" : "Registrar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function NpsTab() {
  const [stats, setStats] = useState(null);
  const [doc, setDoc] = useState("");
  const [score, setScore] = useState("");
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);

  const loadStats = useCallback(async () => {
    try {
      const r = await client.get("/universo-ligo/curadoria/nps/stats").then(r => r.data);
      setStats(r);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);

  async function submit() {
    const s = parseInt(score, 10);
    if (isNaN(s) || s < 0 || s > 10) {
      toast.error("Score deve ser entre 0 e 10");
      return;
    }
    if (!doc) {
      toast.error("Informe o CPF/CNPJ do cliente");
      return;
    }
    setSaving(true);
    try {
      const r = await client.post("/universo-ligo/curadoria/nps", {
          document: doc.replace(/\D/g, ""),
          score: s,
          comment: comment.trim() || null,
          source: "manual",
      }).then(r => r.data);
      if (r?.ok) {
        toast.success(`NPS registrado (${r.category})`);
        setDoc(""); setScore(""); setComment("");
        loadStats();
      }
    } catch (e) {
      toast.error(String(e?.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card testid="nps-stats-card">
        <div className="text-sm font-semibold mb-3">NPS — estatísticas atuais</div>
        {stats ? (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
            <div>
              <div className="text-xs text-zinc-500">Respostas</div>
              <div className="text-2xl font-semibold" data-testid="nps-total">{stats.total_responses}</div>
            </div>
            <div>
              <div className="text-xs text-zinc-500">Promotores</div>
              <div className="text-2xl font-semibold text-emerald-700">{stats.promoters}</div>
            </div>
            <div>
              <div className="text-xs text-zinc-500">Passivos</div>
              <div className="text-2xl font-semibold text-zinc-600">{stats.passives}</div>
            </div>
            <div>
              <div className="text-xs text-zinc-500">Detratores</div>
              <div className="text-2xl font-semibold text-rose-700">{stats.detractors}</div>
            </div>
            <div>
              <div className="text-xs text-zinc-500">NPS</div>
              <div className="text-2xl font-semibold" data-testid="nps-score">
                {stats.nps_score ?? "—"}
              </div>
              <div className="text-xs text-zinc-400">conf. {stats.confidence}</div>
            </div>
          </div>
        ) : (
          <div className="text-sm text-zinc-500">Carregando…</div>
        )}
      </Card>

      <Card testid="nps-submit-card">
        <div className="text-sm font-semibold mb-1">Registrar resposta NPS — 1 pergunta apenas</div>
        <div className="text-xs text-zinc-500 mb-3">
          {`"De 0 a 10, o quanto você indicaria a Ligo para um amigo?"`}
        </div>
        <div className="space-y-2">
          <Input
            placeholder="CPF/CNPJ (apenas números)"
            value={doc}
            onChange={(e) => setDoc(e.target.value)}
            data-testid="nps-input-doc"
          />
          <Input
            placeholder="Score (0-10)"
            value={score}
            onChange={(e) => setScore(e.target.value)}
            data-testid="nps-input-score"
            type="number"
            min={0}
            max={10}
          />
          <Textarea
            placeholder="Comentário do cliente (opcional)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            data-testid="nps-input-comment"
          />
          <Button onClick={submit} disabled={saving} data-testid="nps-submit-btn">
            {saving ? "Salvando…" : "Registrar NPS"}
          </Button>
        </div>
      </Card>
    </div>
  );
}

function GuardTab() {
  const [items, setItems] = useState([]);

  useEffect(() => {
    client.get("/universo-ligo/curadoria/guard/log?limit=100")
      .then((r) => setItems(r?.data?.items || []))
      .catch(() => {});
  }, []);

  return (
    <Card testid="guard-card">
      <div className="text-sm font-semibold mb-1">Synthetic Tenant Guard — Log</div>
      <div className="text-xs text-zinc-500 mb-3">
        Worker periódico (1h) que classifica novos tenants. Sintéticos detectados ficam fora dos dashboards executivos automaticamente.
      </div>
      <div className="space-y-2 max-h-[60vh] overflow-auto">
        {items.length === 0 && (
          <div className="text-sm text-zinc-500">Sem entradas ainda.</div>
        )}
        {items.map((it, i) => (
          <div
            key={i}
            className="flex items-center justify-between border-l-4 border-amber-400 bg-amber-50 px-3 py-2 rounded"
            data-testid={`guard-entry-${i}`}
          >
            <div>
              <div className="text-sm font-medium text-zinc-900">{it.tenant_id}</div>
              <div className="text-xs text-zinc-600">{it.reasons?.[0]}</div>
              <div className="text-[10px] text-zinc-400 mt-1">
                docs totais: {it.total_docs?.toLocaleString("pt-BR")} · {it.scanned_at?.slice(0, 16)}
              </div>
            </div>
            <Badge variant="secondary" className="font-mono text-[10px]">
              {it.classification}
            </Badge>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function UniversoLigoCuradoriaPanel() {
  const [top, setTop] = useState([]);
  const [loading, setLoading] = useState(true);
  const [valDialog, setValDialog] = useState({ open: false, founder: null });
  const [dncDialog, setDncDialog] = useState({ open: false, founder: null });
  const [invDialog, setInvDialog] = useState({ open: false, founder: null });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await client.get("/universo-ligo/curadoria/top10").then(r => r.data);
      setTop(r?.items || []);
    } catch (e) {
      toast.error("Erro ao carregar TOP 10");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const stats = {
    total: top.length,
    apto: top.filter((f) => f.validation?.decision === "APTO").length,
    revisar: top.filter((f) => f.validation?.decision === "REVISAR").length,
    nao: top.filter((f) => f.validation?.decision === "NAO_CONVIDAR").length,
    aceitos: top.filter((f) => f.validation?.status === "accepted").length,
    dnc: top.filter((f) => f.validation?.status === "do_not_contact").length,
    pendentes: top.filter((f) => !f.validation).length,
  };

  return (
    <div className="space-y-6" data-testid="curadoria-panel">
      <div>
        <h2 className="text-2xl font-bold text-zinc-900">
          Universo Ligo — Curadoria de Fundadores
        </h2>
        <p className="text-sm text-zinc-500 mt-1">
          Painel CRM-style para validação humana antes de qualquer convite. Nenhuma comunicação é
          disparada automaticamente.
        </p>
      </div>

      <Tabs defaultValue="founders">
        <TabsList>
          <TabsTrigger value="founders" data-testid="tab-founders">TOP 10 fundadores</TabsTrigger>
          <TabsTrigger value="nps" data-testid="tab-nps">NPS mínimo</TabsTrigger>
          <TabsTrigger value="guard" data-testid="tab-guard">Tenant Guard</TabsTrigger>
        </TabsList>

        <TabsContent value="founders" className="mt-4 space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
            <Card testid="kpi-total"><div className="text-xs text-zinc-500">Total</div><div className="text-xl font-bold">{stats.total}</div></Card>
            <Card testid="kpi-apto"><div className="text-xs text-zinc-500">APTO</div><div className="text-xl font-bold text-emerald-700">{stats.apto}</div></Card>
            <Card testid="kpi-revisar"><div className="text-xs text-zinc-500">REVISAR</div><div className="text-xl font-bold text-amber-700">{stats.revisar}</div></Card>
            <Card testid="kpi-nao"><div className="text-xs text-zinc-500">NÃO CONVIDAR</div><div className="text-xl font-bold text-rose-700">{stats.nao}</div></Card>
            <Card testid="kpi-aceitos"><div className="text-xs text-zinc-500">Aceitos</div><div className="text-xl font-bold text-emerald-700">{stats.aceitos}</div></Card>
            <Card testid="kpi-dnc"><div className="text-xs text-zinc-500">DNC</div><div className="text-xl font-bold text-zinc-700">{stats.dnc}</div></Card>
          </div>

          {loading ? (
            <div className="text-sm text-zinc-500">Carregando…</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {top.map((f) => (
                <FounderCard
                  key={f.document}
                  f={f}
                  onValidate={(x) => setValDialog({ open: true, founder: x })}
                  onDnc={(x) => setDncDialog({ open: true, founder: x })}
                  onInvite={(x) => setInvDialog({ open: true, founder: x })}
                />
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="nps" className="mt-4">
          <NpsTab />
        </TabsContent>

        <TabsContent value="guard" className="mt-4">
          <GuardTab />
        </TabsContent>
      </Tabs>

      <ValidationDialog
        open={valDialog.open}
        onOpenChange={(o) => setValDialog({ open: o, founder: valDialog.founder })}
        founder={valDialog.founder}
        onSaved={load}
      />
      <DncDialog
        open={dncDialog.open}
        onOpenChange={(o) => setDncDialog({ open: o, founder: dncDialog.founder })}
        founder={dncDialog.founder}
        onSaved={load}
      />
      <InviteDialog
        open={invDialog.open}
        onOpenChange={(o) => setInvDialog({ open: o, founder: invDialog.founder })}
        founder={invDialog.founder}
        onSaved={load}
      />
    </div>
  );
}
