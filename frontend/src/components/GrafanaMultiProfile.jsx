/* GrafanaMultiProfile.jsx — Gestão de múltiplas contas Grafana
   P0.5 — Criado por ordem do CTO ("segundo card para outra conta").
   - Lista perfis cadastrados (via /api/admin/integrations/grafana/profiles)
   - Permite adicionar novo perfil, ativar (define qual o connector usa),
     deletar, e testar credenciais.
   - Persiste no secrets_vault encriptado (Fernet AES-128). */
import React, { useEffect, useState, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import {
  Plus, Trash2, Check, Eye, EyeOff, ShieldCheck,
  AlertTriangle, RefreshCw,
} from "lucide-react";
import { api } from "@/lib/apiClient";

const FieldStatus = ({ label, set, preview }) => (
  <div className="flex items-center justify-between text-xs
    px-2 py-1 rounded bg-slate-50 border border-slate-100">
    <span className="font-mono text-slate-600">{label}</span>
    <span className={set ? "text-emerald-700 font-semibold"
      : "text-slate-400"}>
      {set ? (preview || "✓ cadastrado") : "vazio"}
    </span>
  </div>
);

// ─── Profile Card (lista) ─────────────────────────────────
const ProfileItem = ({ profile, onActivate, onDelete }) => {
  const [busy, setBusy] = useState(false);
  return (
    <Card className={`border ${profile.active
      ? "border-emerald-300 bg-emerald-50/40"
      : "border-slate-200"}`}
      data-testid={`grafana-profile-${profile.profile}`}>
      <CardContent className="p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold text-slate-900">
              {profile.profile}
            </span>
            {profile.active && (
              <Badge className="bg-emerald-600 text-white text-[10px]
                gap-1">
                <Check className="w-3 h-3" /> ATIVO
              </Badge>
            )}
            {profile.configured ? (
              <Badge variant="outline"
                className="text-emerald-700 border-emerald-200
                bg-emerald-50 text-[10px] gap-1">
                <ShieldCheck className="w-3 h-3" /> Configurado
              </Badge>
            ) : (
              <Badge variant="outline"
                className="text-amber-700 border-amber-200
                bg-amber-50 text-[10px] gap-1">
                <AlertTriangle className="w-3 h-3" /> Incompleto
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1">
            {!profile.active && profile.configured && (
              <Button size="sm" variant="outline" disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try { await onActivate(profile.profile); }
                  finally { setBusy(false); }
                }}
                data-testid={`profile-activate-${profile.profile}`}>
                Ativar
              </Button>
            )}
            {!profile.active && (
              <Button size="sm" variant="ghost" disabled={busy}
                onClick={async () => {
                  if (!window.confirm(
                    `Excluir perfil "${profile.profile}"?`)) return;
                  setBusy(true);
                  try { await onDelete(profile.profile); }
                  finally { setBusy(false); }
                }}
                className="text-rose-600 hover:text-rose-700
                hover:bg-rose-50"
                data-testid={`profile-delete-${profile.profile}`}>
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <FieldStatus label="url"
            set={profile.fields?.url?.set}
            preview={profile.fields?.url?.preview} />
          <FieldStatus label="token"
            set={profile.fields?.token?.set} />
          <FieldStatus label="user"
            set={profile.fields?.user?.set} />
          <FieldStatus label="password"
            set={profile.fields?.password?.set} />
          <FieldStatus label="org_id"
            set={profile.fields?.org_id?.set} />
        </div>
      </CardContent>
    </Card>
  );
};

// ─── Add Profile Form ─────────────────────────────────────
const AddProfileForm = ({ onSaved, existingProfiles }) => {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    profile: "", url: "", user: "", password: "", token: "", org_id: "",
  });
  const [show, setShow] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const reset = () => {
    setForm({ profile: "", url: "", user: "", password: "",
              token: "", org_id: "" });
    setTestResult(null);
    setOpen(false);
  };

  const validate = () => {
    const p = form.profile.trim().toLowerCase();
    if (!p) { toast.error("Nome do perfil é obrigatório"); return false; }
    if (!/^[a-z0-9][a-z0-9_-]{0,31}$/.test(p)) {
      toast.error("Nome inválido: use a-z, 0-9, _ ou - (até 32 chars)");
      return false;
    }
    if (existingProfiles.includes(p)) {
      toast.error(`Já existe perfil "${p}". Edite ou exclua antes.`);
      return false;
    }
    if (!form.url) { toast.error("URL é obrigatória"); return false; }
    if (!form.token && !(form.user && form.password)) {
      toast.error("Informe TOKEN ou USER+SENHA");
      return false;
    }
    return true;
  };

  const onTest = async () => {
    if (!validate()) return;
    setTesting(true); setTestResult(null);
    try {
      const p = form.profile.trim().toLowerCase();
      const r = await api.post(
        `/api/admin/integrations/grafana/profiles/${p}/test`, form);
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
    if (!validate()) return;
    setSaving(true);
    try {
      const p = form.profile.trim().toLowerCase();
      const r = await api.post(
        `/api/admin/integrations/grafana/profiles/${p}/save`, form);
      toast.success(
        `Perfil "${p}" salvo (${r.saved_fields.join(", ")})`);
      reset();
      onSaved?.();
    } catch (e) {
      toast.error(`Falha ao salvar: ${e.message}`);
    } finally { setSaving(false); }
  };

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)} variant="outline"
        className="w-full border-dashed"
        data-testid="grafana-add-profile-btn">
        <Plus className="w-4 h-4 mr-1" /> Adicionar conta Grafana
      </Button>
    );
  }

  return (
    <Card className="border-dashed border-2 border-emerald-300
      bg-emerald-50/30" data-testid="grafana-add-profile-form">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="font-semibold text-sm text-emerald-900">
            Nova conta Grafana
          </h4>
          <Button size="sm" variant="ghost" onClick={reset}>
            Cancelar
          </Button>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">
            Nome do perfil * (a-z, 0-9, _ ou -)
          </Label>
          <Input value={form.profile}
            onChange={(e) => setForm({ ...form, profile: e.target.value })}
            placeholder="ex: cliente_x, secundaria, prod-2"
            data-testid="grafana-add-profile-name" />
        </div>

        <div className="space-y-1">
          <Label className="text-xs">URL do Grafana *</Label>
          <Input value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
            placeholder="https://grafana.empresa.net"
            data-testid="grafana-add-profile-url" />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label className="text-xs">Usuário</Label>
            <Input value={form.user}
              onChange={(e) => setForm({ ...form, user: e.target.value })}
              placeholder="admin"
              data-testid="grafana-add-profile-user" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Senha</Label>
            <div className="relative">
              <Input type={show ? "text" : "password"}
                value={form.password}
                onChange={(e) =>
                  setForm({ ...form, password: e.target.value })}
                placeholder="••••••••"
                data-testid="grafana-add-profile-pass" />
              <button type="button"
                onClick={() => setShow(!show)}
                className="absolute right-2 top-1/2 -translate-y-1/2
                text-slate-400 hover:text-slate-600">
                {show ? <EyeOff className="w-4 h-4" />
                  : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">
            Service Account Token (preferido)
          </Label>
          <Input value={form.token}
            onChange={(e) => setForm({ ...form, token: e.target.value })}
            placeholder="glsa_xxx..."
            data-testid="grafana-add-profile-token" />
        </div>

        <div className="space-y-1">
          <Label className="text-xs">Org ID (opcional)</Label>
          <Input value={form.org_id}
            onChange={(e) => setForm({ ...form, org_id: e.target.value })}
            placeholder="1"
            data-testid="grafana-add-profile-org" />
        </div>

        {testResult && (
          <div className={`text-xs p-2 rounded border ${testResult.ok
            ? "bg-emerald-50 border-emerald-200 text-emerald-800"
            : "bg-rose-50 border-rose-200 text-rose-800"}`}
            data-testid="grafana-add-profile-test-result">
            {testResult.ok
              ? `✓ ${testResult.org_name} (id=${testResult.org_id}) · ${testResult.auth_mode}`
              : `✗ ${testResult.error || testResult.status}`}
          </div>
        )}

        <div className="flex gap-2 pt-1">
          <Button onClick={onTest} disabled={testing} variant="outline"
            data-testid="grafana-add-profile-test-btn">
            {testing ? "Testando..." : "Testar"}
          </Button>
          <Button onClick={onSave} disabled={saving}
            className="bg-emerald-600 hover:bg-emerald-700"
            data-testid="grafana-add-profile-save-btn">
            {saving ? "Salvando..." : "Salvar perfil"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

// ─── Main ─────────────────────────────────────────────────
const GrafanaMultiProfile = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await api.get(
          "/api/admin/integrations/grafana/profiles");
        if (!cancelled) setData(r);
      } catch (e) {
        if (!cancelled) toast.error(
          `Falha ao listar perfis: ${e.message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [tick]);

  const onActivate = async (profile) => {
    try {
      await api.post(
        `/api/admin/integrations/grafana/profiles/${profile}/activate`);
      toast.success(`Perfil "${profile}" ativado`);
      reload();
    } catch (e) {
      toast.error(`Falha ao ativar: ${e.message}`);
    }
  };

  const onDelete = async (profile) => {
    try {
      await api.delete(
        `/api/admin/integrations/grafana/profiles/${profile}`);
      toast.success(`Perfil "${profile}" excluído`);
      reload();
    } catch (e) {
      toast.error(`Falha ao excluir: ${e.message}`);
    }
  };

  const profiles = data?.profiles || [];
  const existingNames = profiles.map((p) => p.profile);

  return (
    <div className="space-y-3" data-testid="grafana-multi-profile">
      <div className="flex items-center justify-between">
        <div className="text-xs text-slate-500">
          {data?.active ? (
            <span>Perfil ativo: <strong className="text-slate-800
              font-mono">{data.active}</strong> ·
              {profiles.length} perfil(is) cadastrado(s)</span>
          ) : (
            <span>Nenhum perfil cadastrado ainda.</span>
          )}
        </div>
        <Button size="sm" variant="ghost" onClick={reload}
          disabled={loading}
          data-testid="grafana-profiles-refresh">
          <RefreshCw className={`w-3.5 h-3.5 ${loading
            ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {loading ? (
        <div className="text-sm text-slate-400">Carregando perfis...</div>
      ) : (
        <>
          <div className="space-y-2">
            {profiles.map((p) => (
              <ProfileItem key={p.profile} profile={p}
                onActivate={onActivate} onDelete={onDelete} />
            ))}
          </div>
          <AddProfileForm onSaved={reload}
            existingProfiles={existingNames} />
        </>
      )}

      {data?.vault_available === false && (
        <div className="text-xs text-rose-700 bg-rose-50 border
          border-rose-200 rounded p-2 flex items-start gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5" />
          Vault indisponível. Verifique <code>SECRETS_MASTER_KEY</code>
          no <code>.env</code>.
        </div>
      )}
    </div>
  );
};

export default GrafanaMultiProfile;
