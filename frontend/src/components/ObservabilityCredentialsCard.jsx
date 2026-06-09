/* ObservabilityCredentialsCard.jsx — Card UI para cadastro/gestão
   das credenciais de Grafana e Zabbix.
   Criado por ordem direta do CTO (P0). Persiste via secrets_vault
   (Fernet AES-128) através de /api/admin/integrations/*.
   NÃO exibe valores em texto plano (apenas indicadores "set/unset"
   e preview parcial). */
import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle }
  from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent }
  from "@/components/ui/tabs";
import { toast } from "sonner";
import { Lock, ShieldCheck, AlertTriangle, Eye, EyeOff,
  CheckCircle2, XCircle } from "lucide-react";
import { api } from "@/lib/apiClient";
import GrafanaMultiProfile from "@/components/GrafanaMultiProfile";

const ProbeBanner = ({ probe, integration }) => {
  if (!probe) return null;
  const connected = probe.connected;
  const fullyOp = probe.fully_operational !== false;
  const warns = probe.permission_warnings || [];
  const caps = probe.capabilities || {};
  return (
    <div className={`rounded-lg border p-3 ${connected && fullyOp
      ? "bg-emerald-50 border-emerald-200"
      : connected
        ? "bg-amber-50 border-amber-200"
        : "bg-rose-50 border-rose-200"}`}
      data-testid={`probe-banner-${integration}`}>
      <div className="flex items-center gap-2 text-sm font-semibold">
        {connected && fullyOp
          ? <CheckCircle2 className="w-4 h-4 text-emerald-700" />
          : connected
            ? <AlertTriangle className="w-4 h-4 text-amber-700" />
            : <XCircle className="w-4 h-4 text-rose-700" />}
        <span className={connected && fullyOp
          ? "text-emerald-800"
          : connected ? "text-amber-800" : "text-rose-800"}>
          {connected
            ? (fullyOp
                ? `Conectado · ${probe.org_name || probe.api_version || "OK"}`
                : `Parcialmente conectado · ${probe.org_name || "OK"}`)
            : `Não conectado · status ${probe.status || "?"}`}
        </span>
      </div>
      {/* Capabilities grid */}
      {Object.keys(caps).length > 0 && (
        <div className="mt-2 grid grid-cols-2 md:grid-cols-3 gap-1.5">
          {Object.entries(caps).map(([name, info]) => (
            <div key={name}
              className={`text-[11px] px-2 py-1 rounded border flex
                items-center gap-1.5 ${info.ok
                ? "bg-white border-emerald-200 text-emerald-700"
                : "bg-white border-rose-200 text-rose-700"}`}
              data-testid={`cap-${integration}-${name}`}>
              {info.ok ? <CheckCircle2 className="w-3 h-3" />
                : <XCircle className="w-3 h-3" />}
              <span className="capitalize">{name}</span>
              {info.via === "fallback" && (
                <span className="ml-auto text-[9px] text-slate-500
                  bg-slate-100 px-1 rounded">via fallback</span>
              )}
              {!info.ok && info.status && (
                <span className="ml-auto text-[9px] text-rose-500">
                  {info.status}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {warns.map((w, i) => (
        <div key={i}
          className="mt-2 text-xs text-amber-800 flex items-start gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          <span>{w}</span>
        </div>
      ))}
      {probe.error && (
        <div className="mt-1 text-xs text-rose-700 font-mono">
          {probe.error}
        </div>
      )}
    </div>
  );
};

const StatusPill = ({ status }) => {
  if (!status) return null;
  const ok = status.configured;
  const Icon = ok ? ShieldCheck : AlertTriangle;
  return (
    <Badge className={`gap-1 ${ok
      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : "bg-amber-50 text-amber-700 border-amber-200"} border`}
      data-testid="cred-status-pill">
      <Icon className="w-3 h-3" />
      {ok ? "Configurado no Vault" : "Não configurado no Vault"}
    </Badge>
  );
};

const FieldStatus = ({ label, set, preview }) => (
  <div className="flex items-center justify-between text-xs
    px-2 py-1 rounded bg-slate-50 border border-slate-100">
    <span className="font-mono text-slate-600">{label}</span>
    <span className={set ? "text-emerald-700 font-semibold"
      : "text-slate-400"}>
      {set ? (preview ? `${preview}` : "✓ cadastrado") : "vazio"}
    </span>
  </div>
);

// ─── GRAFANA FORM ─────────────────────────────────────────
const GrafanaForm = ({ status, onSaved }) => {
  const [form, setForm] = useState({
    url: "", user: "", password: "", token: "", org_id: "",
  });
  const [show, setShow] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const onTest = async () => {
    setTestResult(null);
    setTesting(true);
    try {
      const r = await api.post("/api/admin/integrations/grafana/test", form);
      setTestResult(r);
      if (r.ok) toast.success(
        `Conexão OK · org=${r.org_name} · auth=${r.auth_mode}`);
      else toast.error(`Falha: ${r.error || r.status}`);
    } catch (e) {
      toast.error(`Erro: ${e.message}`);
      setTestResult({ ok: false, error: e.message });
    } finally { setTesting(false); }
  };

  const onSave = async () => {
    if (!form.url) {
      toast.error("URL é obrigatório");
      return;
    }
    if (!form.token && !(form.user && form.password)) {
      toast.error("Informe TOKEN ou USUÁRIO + SENHA");
      return;
    }
    setSaving(true);
    try {
      const r = await api.post("/api/admin/integrations/grafana/save", form);
      toast.success(`Salvo no Vault: ${r.saved_fields.join(", ")}`);
      setForm({ url: "", user: "", password: "", token: "", org_id: "" });
      onSaved?.();
    } catch (e) {
      toast.error(`Falha ao salvar: ${e.message}`);
    } finally { setSaving(false); }
  };

  return (
    <div className="space-y-4" data-testid="grafana-cred-form">
      <div className="flex items-center justify-between">
        <StatusPill status={status} />
        {status?.vault_available === false && (
          <Badge className="bg-rose-50 text-rose-700 border border-rose-200
            gap-1" data-testid="vault-unavailable">
            <Lock className="w-3 h-3" /> Vault indisponível
          </Badge>
        )}
      </div>

      {status && (
        <div className="grid grid-cols-2 gap-1.5">
          <FieldStatus label="url" set={status.fields?.url?.set}
            preview={status.fields?.url?.preview} />
          <FieldStatus label="token" set={status.fields?.token?.set} />
          <FieldStatus label="user" set={status.fields?.user?.set} />
          <FieldStatus label="password" set={status.fields?.password?.set} />
          <FieldStatus label="org_id" set={status.fields?.org_id?.set} />
        </div>
      )}

      <div className="border-t border-slate-100 pt-4 space-y-3">
        <div className="text-xs font-semibold uppercase tracking-wider
          text-slate-500">Cadastrar / Atualizar credenciais</div>

        <div className="space-y-1">
          <Label className="text-xs">URL do Grafana *</Label>
          <Input value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
            placeholder="https://grafana.empresa.net"
            data-testid="grafana-url-input" />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label className="text-xs">Usuário (basic auth)</Label>
            <Input value={form.user}
              onChange={(e) => setForm({ ...form, user: e.target.value })}
              placeholder="admin"
              data-testid="grafana-user-input" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Senha</Label>
            <div className="relative">
              <Input type={show ? "text" : "password"} value={form.password}
                onChange={(e) =>
                  setForm({ ...form, password: e.target.value })}
                placeholder="••••••••"
                data-testid="grafana-pass-input" />
              <button type="button"
                onClick={() => setShow(!show)}
                className="absolute right-2 top-1/2 -translate-y-1/2
                  text-slate-400 hover:text-slate-600"
                data-testid="grafana-pass-toggle">
                {show ? <EyeOff className="w-4 h-4" />
                  : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">
            Service Account Token (preferido — se informado, ignora user/pass)
          </Label>
          <Input value={form.token}
            onChange={(e) => setForm({ ...form, token: e.target.value })}
            placeholder="glsa_xxx..."
            data-testid="grafana-token-input" />
        </div>

        <div className="space-y-1">
          <Label className="text-xs">Org ID (opcional)</Label>
          <Input value={form.org_id}
            onChange={(e) => setForm({ ...form, org_id: e.target.value })}
            placeholder="1"
            data-testid="grafana-org-input" />
        </div>

        {testResult && (
          <div className={`text-xs p-2 rounded border ${testResult.ok
            ? "bg-emerald-50 border-emerald-200 text-emerald-800"
            : "bg-rose-50 border-rose-200 text-rose-800"}`}
            data-testid="grafana-test-result">
            {testResult.ok
              ? `✓ OK · org=${testResult.org_name} (id=${testResult.org_id}) · auth=${testResult.auth_mode}`
              : `✗ ${testResult.error || testResult.status || "Falha"}`}
          </div>
        )}

        <div className="flex gap-2 pt-2">
          <Button onClick={onTest} disabled={testing || !form.url}
            variant="outline"
            data-testid="grafana-test-btn">
            {testing ? "Testando..." : "Testar Conexão"}
          </Button>
          <Button onClick={onSave} disabled={saving || !form.url}
            className="bg-emerald-600 hover:bg-emerald-700"
            data-testid="grafana-save-btn">
            {saving ? "Salvando..." : "Salvar no Vault"}
          </Button>
        </div>
      </div>
    </div>
  );
};

// ─── ZABBIX FORM ──────────────────────────────────────────
const ZabbixForm = ({ status, onSaved }) => {
  const [form, setForm] = useState({
    url: "", user: "", password: "", api_token: "",
  });
  const [show, setShow] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const onTest = async () => {
    setTestResult(null);
    setTesting(true);
    try {
      const r = await api.post("/api/admin/integrations/zabbix/test", form);
      setTestResult(r);
      if (r.ok) toast.success(`Zabbix OK · auth=${r.auth_mode}`);
      else toast.error(`Falha Zabbix: ${JSON.stringify(r.error)}`);
    } catch (e) {
      toast.error(`Erro: ${e.message}`);
      setTestResult({ ok: false, error: e.message });
    } finally { setTesting(false); }
  };

  const onSave = async () => {
    if (!form.url) { toast.error("URL é obrigatório"); return; }
    if (!form.api_token && !(form.user && form.password)) {
      toast.error("Informe API TOKEN ou USUÁRIO + SENHA");
      return;
    }
    setSaving(true);
    try {
      const r = await api.post("/api/admin/integrations/zabbix/save", form);
      toast.success(`Salvo no Vault: ${r.saved_fields.join(", ")}`);
      setForm({ url: "", user: "", password: "", api_token: "" });
      onSaved?.();
    } catch (e) {
      toast.error(`Falha ao salvar: ${e.message}`);
    } finally { setSaving(false); }
  };

  return (
    <div className="space-y-4" data-testid="zabbix-cred-form">
      <div className="flex items-center justify-between">
        <StatusPill status={status} />
        {status?.vault_available === false && (
          <Badge className="bg-rose-50 text-rose-700 border border-rose-200
            gap-1">
            <Lock className="w-3 h-3" /> Vault indisponível
          </Badge>
        )}
      </div>

      {status && (
        <div className="grid grid-cols-2 gap-1.5">
          <FieldStatus label="url" set={status.fields?.url?.set}
            preview={status.fields?.url?.preview} />
          <FieldStatus label="api_token" set={status.fields?.api_token?.set} />
          <FieldStatus label="user" set={status.fields?.user?.set} />
          <FieldStatus label="password" set={status.fields?.password?.set} />
        </div>
      )}

      <div className="border-t border-slate-100 pt-4 space-y-3">
        <div className="text-xs font-semibold uppercase tracking-wider
          text-slate-500">Cadastrar / Atualizar credenciais</div>

        <div className="space-y-1">
          <Label className="text-xs">URL do Zabbix *</Label>
          <Input value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
            placeholder="https://zabbix.empresa.net"
            data-testid="zabbix-url-input" />
        </div>

        <div className="space-y-1">
          <Label className="text-xs">
            API Token (preferido — gerar em &quot;Users → API tokens&quot;)
          </Label>
          <Input value={form.api_token}
            onChange={(e) =>
              setForm({ ...form, api_token: e.target.value })}
            placeholder="xxxx..."
            data-testid="zabbix-token-input" />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label className="text-xs">Usuário (fallback)</Label>
            <Input value={form.user}
              onChange={(e) => setForm({ ...form, user: e.target.value })}
              placeholder="Admin"
              data-testid="zabbix-user-input" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Senha</Label>
            <div className="relative">
              <Input type={show ? "text" : "password"} value={form.password}
                onChange={(e) =>
                  setForm({ ...form, password: e.target.value })}
                placeholder="••••••••"
                data-testid="zabbix-pass-input" />
              <button type="button"
                onClick={() => setShow(!show)}
                className="absolute right-2 top-1/2 -translate-y-1/2
                  text-slate-400 hover:text-slate-600"
                data-testid="zabbix-pass-toggle">
                {show ? <EyeOff className="w-4 h-4" />
                  : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        {testResult && (
          <div className={`text-xs p-2 rounded border ${testResult.ok
            ? "bg-emerald-50 border-emerald-200 text-emerald-800"
            : "bg-rose-50 border-rose-200 text-rose-800"}`}
            data-testid="zabbix-test-result">
            {testResult.ok
              ? `✓ OK · result=${testResult.result} · auth=${testResult.auth_mode}`
              : `✗ ${JSON.stringify(testResult.error).slice(0, 200)}`}
          </div>
        )}

        <div className="flex gap-2 pt-2">
          <Button onClick={onTest} disabled={testing || !form.url}
            variant="outline"
            data-testid="zabbix-test-btn">
            {testing ? "Testando..." : "Testar Conexão"}
          </Button>
          <Button onClick={onSave} disabled={saving || !form.url}
            className="bg-emerald-600 hover:bg-emerald-700"
            data-testid="zabbix-save-btn">
            {saving ? "Salvando..." : "Salvar no Vault"}
          </Button>
        </div>
      </div>
    </div>
  );
};

// ─── MAIN CARD ────────────────────────────────────────────
const ObservabilityCredentialsCard = ({ defaultOpen = false }) => {
  const [open, setOpen] = useState(!!defaultOpen);
  const [grafanaStatus, setGrafanaStatus] = useState(null);
  const [zabbixStatus, setZabbixStatus] = useState(null);
  const [connStatus, setConnStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [g, z, c] = await Promise.all([
        api.get("/api/admin/integrations/grafana/status"),
        api.get("/api/admin/integrations/zabbix/status"),
        api.get("/api/ai-center/observability/connectors/status"),
      ]);
      setGrafanaStatus(g);
      setZabbixStatus(z);
      setConnStatus(c);
    } catch (e) {
      toast.error(`Falha ao carregar status: ${e.message}`);
    } finally { setLoading(false); }
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [g, z, c] = await Promise.all([
          api.get("/api/admin/integrations/grafana/status"),
          api.get("/api/admin/integrations/zabbix/status"),
          api.get("/api/ai-center/observability/connectors/status"),
        ]);
        if (cancelled) return;
        setGrafanaStatus(g);
        setZabbixStatus(z);
        setConnStatus(c);
      } catch (e) {
        if (!cancelled) toast.error(`Falha ao carregar status: ${e.message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  return (
    <Card className="border-slate-200 shadow-sm"
      data-testid="obs-credentials-card">
      <CardHeader className="cursor-pointer select-none"
        onClick={() => setOpen(!open)}
        data-testid="obs-credentials-header">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-slate-900 text-white">
              <Lock className="w-4 h-4" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold text-slate-900">
                Credenciais de Observabilidade
              </CardTitle>
              <p className="text-xs text-slate-500 mt-0.5">
                Cadastre Grafana e Zabbix com segurança ·
                criptografia Fernet AES-128 via Secrets Vault
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {grafanaStatus && (
              <Badge variant="outline" className={`text-[10px] gap-1 ${
                connStatus?.grafana?.probe?.connected
                  ? "border-emerald-200 text-emerald-700 bg-emerald-50"
                  : grafanaStatus.configured
                    ? "border-amber-200 text-amber-700 bg-amber-50"
                    : ""}`}
                data-testid="header-badge-grafana">
                Grafana: {connStatus?.grafana?.probe?.connected
                  ? "● conectado"
                  : grafanaStatus.configured ? "⚠ não respondeu" : "—"}
              </Badge>
            )}
            {zabbixStatus && (
              <Badge variant="outline" className={`text-[10px] gap-1 ${
                connStatus?.zabbix?.probe?.connected
                  ? "border-emerald-200 text-emerald-700 bg-emerald-50"
                  : zabbixStatus.configured
                    ? "border-amber-200 text-amber-700 bg-amber-50"
                    : ""}`}
                data-testid="header-badge-zabbix">
                Zabbix: {connStatus?.zabbix?.probe?.connected
                  ? "● conectado"
                  : zabbixStatus.configured ? "⚠ não respondeu" : "—"}
              </Badge>
            )}
            <span className="text-xs text-slate-500">
              {open ? "−" : "+"}
            </span>
          </div>
        </div>
      </CardHeader>
      {open && (
        <CardContent className="border-t border-slate-100 pt-5">
          {loading ? (
            <div className="text-sm text-slate-500">Carregando...</div>
          ) : (
            <Tabs defaultValue="grafana">
              <TabsList data-testid="obs-cred-tabs">
                <TabsTrigger value="grafana"
                  data-testid="obs-cred-tab-grafana">Grafana</TabsTrigger>
                <TabsTrigger value="zabbix"
                  data-testid="obs-cred-tab-zabbix">Zabbix</TabsTrigger>
              </TabsList>
              <TabsContent value="grafana" className="pt-4 space-y-4">
                <ProbeBanner
                  probe={connStatus?.grafana?.probe}
                  integration="grafana" />
                <GrafanaMultiProfile />
              </TabsContent>
              <TabsContent value="zabbix" className="pt-4 space-y-4">
                <ProbeBanner
                  probe={connStatus?.zabbix?.probe}
                  integration="zabbix" />
                <ZabbixForm status={zabbixStatus} onSaved={load} />
              </TabsContent>
            </Tabs>
          )}
        </CardContent>
      )}
    </Card>
  );
};

export default ObservabilityCredentialsCard;
