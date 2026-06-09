/* OltSnmpCard.jsx — Cadastro/gestão de OLTs V-SOL via SNMP direto.
   Multi-perfil (N OLTs em paralelo). Persiste no secrets_vault. */
import React, { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import {
  Plus, Trash2, Check, AlertTriangle, ShieldCheck,
  Activity, RefreshCw, Wifi, Server,
} from "lucide-react";
import { api } from "@/lib/apiClient";

const SYSTEM_PUBLIC_IP = "35.225.230.28";

const FieldRow = ({ label, value, set }) => (
  <div className="flex items-center justify-between text-xs
    px-2 py-1 rounded bg-slate-50 border border-slate-100">
    <span className="font-mono text-slate-600">{label}</span>
    <span className={set ? "text-slate-800 font-semibold" : "text-slate-400"}>
      {set ? (value || "✓") : "vazio"}
    </span>
  </div>
);

const OltItem = ({ p, onEnable, onDisable, onDelete, onPing, onDiscover }) => {
  const [busy, setBusy] = useState(null);
  const run = async (key, fn) => {
    setBusy(key);
    try { await fn(); }
    finally { setBusy(null); }
  };
  return (
    <Card className={`border ${p.enabled
      ? "border-emerald-300 bg-emerald-50/40"
      : "border-slate-200 opacity-70"}`}
      data-testid={`olt-profile-${p.profile}`}>
      <CardContent className="p-3 space-y-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm font-semibold text-slate-900">
              {p.profile}
            </span>
            {p.enabled
              ? <Badge className="bg-emerald-600 text-white text-[10px] gap-1">
                  <Check className="w-3 h-3" /> ATIVO
                </Badge>
              : <Badge variant="outline" className="text-slate-500
                  text-[10px]">DESATIVADO</Badge>}
            {p.configured
              ? <Badge variant="outline"
                  className="text-emerald-700 border-emerald-200
                  bg-emerald-50 text-[10px] gap-1">
                  <ShieldCheck className="w-3 h-3" /> Configurado
                </Badge>
              : <Badge variant="outline"
                  className="text-amber-700 border-amber-200
                  bg-amber-50 text-[10px] gap-1">
                  <AlertTriangle className="w-3 h-3" /> Incompleto
                </Badge>}
          </div>
          <div className="flex gap-1">
            <Button size="sm" variant="outline" disabled={!!busy}
              onClick={() => run("ping", () => onPing(p.profile))}
              data-testid={`olt-ping-${p.profile}`}>
              <Wifi className="w-3.5 h-3.5 mr-1" />
              {busy === "ping" ? "..." : "Ping SNMP"}
            </Button>
            <Button size="sm" variant="outline" disabled={!!busy}
              onClick={() => run("disc", () => onDiscover(p.profile))}
              className="text-emerald-700"
              data-testid={`olt-discover-${p.profile}`}>
              <Activity className="w-3.5 h-3.5 mr-1" />
              {busy === "disc" ? "..." : "Discovery"}
            </Button>
            {p.enabled
              ? <Button size="sm" variant="ghost" disabled={!!busy}
                  onClick={() => run("d", () => onDisable(p.profile))}>
                  Desativar
                </Button>
              : <Button size="sm" variant="ghost" disabled={!!busy}
                  onClick={() => run("e", () => onEnable(p.profile))}>
                  Ativar
                </Button>}
            <Button size="sm" variant="ghost" disabled={!!busy}
              onClick={async () => {
                if (!window.confirm(`Excluir OLT "${p.profile}"?`)) return;
                await run("rm", () => onDelete(p.profile));
              }}
              className="text-rose-600 hover:bg-rose-50">
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-1.5">
          <FieldRow label="host" value={p.fields?.host?.value}
            set={p.fields?.host?.set} />
          <FieldRow label="port" value={p.fields?.port?.value}
            set={p.fields?.port?.set} />
          <FieldRow label="version" value={p.fields?.version?.value}
            set={p.fields?.version?.set} />
          <FieldRow label="vendor" value={p.fields?.vendor?.value}
            set={p.fields?.vendor?.set} />
          <FieldRow label="community" value={p.fields?.community?.value}
            set={p.fields?.community?.set} />
          <FieldRow label="label" value={p.fields?.label?.value}
            set={p.fields?.label?.set} />
        </div>
      </CardContent>
    </Card>
  );
};

const AddOltForm = ({ onSaved, existing }) => {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    profile: "", host: "", port: "161", version: "v2c",
    community: "public", vendor: "vsol", label: "",
  });
  const [saving, setSaving] = useState(false);

  const reset = () => {
    setForm({ profile: "", host: "", port: "161", version: "v2c",
              community: "public", vendor: "vsol", label: "" });
    setOpen(false);
  };

  const onSave = async () => {
    const p = form.profile.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9_-]{0,31}$/.test(p)) {
      toast.error("Nome inválido (a-z, 0-9, _ -)"); return;
    }
    if (existing.includes(p)) {
      toast.error(`Já existe OLT "${p}"`); return;
    }
    if (!form.host) { toast.error("IP/host obrigatório"); return; }
    if (!form.community) { toast.error("Community obrigatória"); return; }
    setSaving(true);
    try {
      const r = await api.post(
        `/api/admin/integrations/olt/profiles/${p}/save`, {
          host: form.host, port: parseInt(form.port, 10) || 161,
          version: form.version, community: form.community,
          vendor: form.vendor, label: form.label,
        });
      toast.success(`OLT "${p}" cadastrada (${r.saved_fields.length} campos)`);
      reset(); onSaved?.();
    } catch (e) {
      toast.error(`Falha: ${e.message}`);
    } finally { setSaving(false); }
  };

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)} variant="outline"
        className="w-full border-dashed"
        data-testid="olt-add-btn">
        <Plus className="w-4 h-4 mr-1" /> Adicionar OLT
      </Button>
    );
  }

  return (
    <Card className="border-dashed border-2 border-emerald-300
      bg-emerald-50/30" data-testid="olt-add-form">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="font-semibold text-sm text-emerald-900">
            Cadastrar OLT V-SOL via SNMP
          </h4>
          <Button size="sm" variant="ghost" onClick={reset}>Cancelar</Button>
        </div>
        <div className="rounded bg-amber-50 border border-amber-200 p-2
          text-xs text-amber-900">
          <strong>⚠️ Importante:</strong> No lado da OLT (config CLI),
          libere SNMP read-only para nosso IP público:
          <code className="block font-mono mt-1 text-amber-900 bg-white
            px-2 py-1 rounded">
            snmp-server community {form.community || "public"} ro {SYSTEM_PUBLIC_IP}/32
          </code>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs">Nome (perfil) *</Label>
            <Input value={form.profile}
              onChange={(e) => setForm({ ...form, profile: e.target.value })}
              placeholder="ex: olt-cachoeiras"
              data-testid="olt-form-profile" />
          </div>
          <div>
            <Label className="text-xs">Label (descrição)</Label>
            <Input value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              placeholder="OLT Cachoeiras de Macacu"
              data-testid="olt-form-label" />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <Label className="text-xs">IP/Hostname *</Label>
            <Input value={form.host}
              onChange={(e) => setForm({ ...form, host: e.target.value })}
              placeholder="10.0.0.1 ou olt.lan"
              data-testid="olt-form-host" />
          </div>
          <div>
            <Label className="text-xs">Porta SNMP</Label>
            <Input value={form.port}
              onChange={(e) => setForm({ ...form, port: e.target.value })}
              placeholder="161"
              data-testid="olt-form-port" />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <Label className="text-xs">Versão SNMP</Label>
            <select value={form.version}
              onChange={(e) => setForm({ ...form, version: e.target.value })}
              className="w-full h-9 border border-slate-200 rounded
                px-2 text-sm"
              data-testid="olt-form-version">
              <option value="v2c">v2c (recomendado)</option>
              <option value="v1">v1</option>
            </select>
          </div>
          <div>
            <Label className="text-xs">Fabricante</Label>
            <select value={form.vendor}
              onChange={(e) => setForm({ ...form, vendor: e.target.value })}
              className="w-full h-9 border border-slate-200 rounded
                px-2 text-sm"
              data-testid="olt-form-vendor">
              <option value="vsol">V-SOL (Realtek)</option>
              <option value="huawei">Huawei</option>
              <option value="zte">ZTE</option>
              <option value="datacom">Datacom</option>
              <option value="fiberhome">FiberHome</option>
            </select>
          </div>
          <div>
            <Label className="text-xs">Community *</Label>
            <Input value={form.community}
              onChange={(e) => setForm({ ...form, community: e.target.value })}
              placeholder="public"
              data-testid="olt-form-community" />
          </div>
        </div>

        <Button onClick={onSave} disabled={saving}
          className="bg-emerald-600 hover:bg-emerald-700 w-full"
          data-testid="olt-form-save">
          {saving ? "Salvando..." : "Cadastrar OLT"}
        </Button>
      </CardContent>
    </Card>
  );
};

const OltSnmpCard = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await api.get("/api/admin/integrations/olt/profiles");
        if (!cancelled) setData(r);
      } catch (e) {
        if (!cancelled) toast.error(`Falha ao listar OLTs: ${e.message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [tick]);

  const reload = () => setTick((t) => t + 1);

  const onEnable = async (n) => {
    try {
      await api.post(`/api/admin/integrations/olt/profiles/${n}/enable`);
      toast.success(`OLT "${n}" ativada`); reload();
    } catch (e) { toast.error(`Falha: ${e.message}`); }
  };
  const onDisable = async (n) => {
    try {
      await api.post(`/api/admin/integrations/olt/profiles/${n}/disable`);
      toast.success(`OLT "${n}" desativada`); reload();
    } catch (e) { toast.error(`Falha: ${e.message}`); }
  };
  const onDelete = async (n) => {
    try {
      await api.delete(`/api/admin/integrations/olt/profiles/${n}`);
      toast.success(`OLT "${n}" excluída`); reload();
    } catch (e) { toast.error(`Falha: ${e.message}`); }
  };
  const onPing = async (n) => {
    try {
      const r = await api.post(
        `/api/admin/integrations/olt/profiles/${n}/ping`);
      if (r.ok) toast.success(`Ping OK · ${(r.sys_descr || "").slice(0,80)}`);
      else toast.error(`Sem resposta SNMP: ${r.error || "timeout"}`);
    } catch (e) { toast.error(`Falha ping: ${e.message}`); }
  };
  const onDiscover = async (n) => {
    try {
      const r = await api.post(
        `/api/admin/integrations/olt/profiles/${n}/discover`);
      toast.success(`Discovery: ${r.onu_count} ONUs em "${n}"`);
    } catch (e) { toast.error(`Falha discovery: ${e.message}`); }
  };

  const profiles = data?.profiles || [];

  return (
    <div className="space-y-3" data-testid="olt-snmp-card">
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-3
        text-xs text-blue-900 space-y-1">
        <div className="font-semibold flex items-center gap-1">
          <Server className="w-4 h-4" />
          IP do nosso sistema (para liberar no lado da OLT):
        </div>
        <div className="font-mono bg-white px-2 py-1 rounded inline-block">
          {SYSTEM_PUBLIC_IP}
        </div>
        <div className="text-[11px] opacity-75 mt-1">
          Adicione esse IP no SNMP ACL da OLT antes de testar. Porta 161/UDP.
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="text-xs text-slate-500">
          {data?.enabled_count > 0
            ? <span><strong className="text-emerald-700">
                {data.enabled_count} ativa(s)</strong> de {profiles.length} OLT(s)
                — todas rodam em paralelo</span>
            : <span>Nenhuma OLT cadastrada.</span>}
        </div>
        <Button size="sm" variant="ghost" onClick={reload} disabled={loading}>
          <RefreshCw className={`w-3.5 h-3.5 ${loading
            ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {loading ? (
        <div className="text-sm text-slate-400">Carregando OLTs...</div>
      ) : (
        <>
          <div className="space-y-2">
            {profiles.map((p) => (
              <OltItem key={p.profile} p={p}
                onEnable={onEnable} onDisable={onDisable}
                onDelete={onDelete} onPing={onPing}
                onDiscover={onDiscover} />
            ))}
          </div>
          <AddOltForm onSaved={reload}
            existing={profiles.map((p) => p.profile)} />
        </>
      )}
    </div>
  );
};

export default OltSnmpCard;
