/**
 * IntegrationCredsCard.jsx
 * Página dedicada (sidebar "Credenciais Integração") — wrapper do
 * componente ObservabilityCredentialsCard com expansão padrão aberta.
 * Persiste via /api/admin/integrations/* → secrets_vault (Fernet).
 */
import React from "react";
import ObservabilityCredentialsCard
  from "@/components/ObservabilityCredentialsCard";

export default function IntegrationCredsCard() {
  return (
    <div className="space-y-4 px-1 max-w-4xl"
      data-testid="integration-creds-page">
      <header>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Credenciais de Integração
        </h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Gerencie credenciais de Grafana e Zabbix com criptografia
          Fernet AES-128 via Secrets Vault.
        </p>
      </header>
      <ObservabilityCredentialsCard defaultOpen />
    </div>
  );
}
