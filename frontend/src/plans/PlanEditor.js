import React from "react";
import { Sparkles, X, Save } from "lucide-react";
import { Field, CheckRow, CheckboxAddon, VodAddonField } from "./_shared";

/* =============================================================
   PlanEditor — formulário completo de plano comercial.
   Inclui seções avançadas (Tipo, Filial, Franquia, VOD, NFCom,
   Detalhes, Mikrotik). Mantém todos os data-testid originais.
============================================================= */
export default function PlanEditor({ plan, onChange, onSave, onCancel }) {
  const set = (k, v) => onChange({ ...plan, [k]: v });
  const canSave = (plan.name || "").trim().length >= 2
    && (plan.monthly_price === 0 || plan.monthly_price > 0
        || (typeof plan.monthly_price === "string"
            && parseFloat(plan.monthly_price) >= 0));

  return (
    <div className="surface" data-testid="plan-editor" style={{
      padding: 18, borderRadius: 14,
      border: "2px solid var(--accent)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                     marginBottom: 14 }}>
        <Sparkles size={16} style={{ color: "var(--accent)" }} />
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>
          {plan.id ? `Editar plano: ${plan.name || "—"}` : "Novo plano"}
        </h3>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr",
                     gap: 12, marginBottom: 12 }}>
        <Field label="Nome do plano *">
          <input className="input" autoFocus
                  data-testid="plan-name"
                  value={plan.name || ""}
                  onChange={(e) => set("name", e.target.value)}
                  placeholder="Ex.: Fibra 500 Mega" />
        </Field>
        <Field label="Velocidade Download (Mbps)">
          <input className="input" type="number" min="1"
                  data-testid="plan-speed-down"
                  value={plan.speed_down_mbps || ""}
                  onChange={(e) => set("speed_down_mbps", e.target.value)}
                  placeholder="500" />
        </Field>
        <Field label="Velocidade Upload (Mbps)">
          <input className="input" type="number" min="1"
                  value={plan.speed_up_mbps || ""}
                  onChange={(e) => set("speed_up_mbps", e.target.value)}
                  placeholder="opcional" />
        </Field>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12,
                     marginBottom: 12 }}>
        <Field label="Valor mensal (R$) *">
          <input className="input" type="number" step="0.01" min="0"
                  data-testid="plan-price"
                  value={plan.monthly_price ?? ""}
                  onChange={(e) => set("monthly_price", e.target.value)}
                  placeholder="99.90" />
        </Field>
        <Field label="Reajuste anual de inflação (%)">
          <input className="input" type="number" step="0.1" min="0" max="100"
                  data-testid="plan-adjustment"
                  value={plan.annual_adjustment_pct ?? 0}
                  onChange={(e) => set("annual_adjustment_pct", e.target.value)}
                  placeholder="6.5" />
        </Field>
      </div>
      <Field label="Descrição (opcional)">
        <textarea className="input" rows={2}
                   value={plan.description || ""}
                   onChange={(e) => set("description", e.target.value)}
                   placeholder="Ex.: Plano mais vendido, ideal pra streaming 4K..." />
      </Field>

      {/* ============================================================
          RADIUS — Perfil REDUZIDO (aplicado quando contrato fica em
          REDUZIDO por inadimplência). Velocidades em Mbps.
          Aceita decimais (ex: 0.5 = 512k, 1 = 1024k).
          ============================================================ */}
      <div style={{ marginTop: 12, padding: 12,
                      background: "linear-gradient(135deg,#fef3c7,#fef9c3)",
                      border: "1px solid #fcd34d", borderRadius: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: "#713f12",
                        marginBottom: 4 }}>
          Perfil REDUZIDO (aging RADIUS)
        </div>
        <div style={{ fontSize: 11, color: "#92400e",
                        marginBottom: 10, lineHeight: 1.4 }}>
          Velocidade aplicada quando o contrato cai em REDUZIDO
          (cliente em atraso após X dias — configurado no Contrato).
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 12 }}>
          <Field label="Reduzir Download (Mbps)">
            <input className="input" type="number" step="0.1" min="0"
                    data-testid="plan-reduced-down"
                    value={plan.speed_reduced_down_mbps ?? 0.5}
                    onChange={(e) => set("speed_reduced_down_mbps",
                      e.target.value)}
                    placeholder="0.5" />
          </Field>
          <Field label="Reduzir Upload (Mbps)">
            <input className="input" type="number" step="0.1" min="0"
                    data-testid="plan-reduced-up"
                    value={plan.speed_reduced_up_mbps ?? 0.25}
                    onChange={(e) => set("speed_reduced_up_mbps",
                      e.target.value)}
                    placeholder="0.25" />
          </Field>
        </div>
      </div>

      {/* Seções avançadas — Tipo, Filial, Franquia, VOD, NFCom, Mikrotik */}
      <PlanAdvancedSections plan={plan} set={set} />

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                     marginTop: 14 }}>
        <button onClick={onCancel} className="btn btn-ghost btn-sm">
          <X size={12} /> Cancelar
        </button>
        <button onClick={onSave} disabled={!canSave}
                data-testid="plan-save"
                className="btn btn-primary btn-sm">
          <Save size={12} /> Salvar
        </button>
      </div>
    </div>
  );
}


/* ========================================================================
   PlanAdvancedSections — Tipo & Filial / Franquia / VOD / NFCom / Detalhes
   / Mikrotik. Replica a estrutura de Plano do Atlaz.
   ======================================================================== */
function PlanAdvancedSections({ plan, set }) {
  return (
    <>
      {/* Tipo & Filial */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                      gap: 12, marginTop: 12, marginBottom: 12 }}>
        <Field label="Tipo de plano">
          <select className="input" data-testid="plan-type"
                    value={plan.plan_type || "Residencial"}
                    onChange={(e) => set("plan_type", e.target.value)}>
            <option value="Residencial">Residencial</option>
            <option value="Empresarial">Empresarial</option>
            <option value="Dedicado">Dedicado (banda garantida)</option>
            <option value="Hotspot">Hotspot</option>
          </select>
        </Field>
        <Field label="Filial (opcional)">
          <input className="input" data-testid="plan-branch"
                  value={plan.branch_id || ""}
                  onChange={(e) => set("branch_id", e.target.value)}
                  placeholder="ID/Nome da filial" />
        </Field>
      </div>

      {/* Avançado - Redução por atraso (dias) */}
      <div style={{ marginTop: 10, padding: 12,
                      background: "linear-gradient(135deg,#fef3c7,#fef9c3)",
                      border: "1px solid #fcd34d", borderRadius: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: "#713f12",
                        marginBottom: 8 }}>
          ️ Avançado — redução & bloqueio por atraso
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 12 }}>
          <Field label="Reduzir após N dias">
            <input className="input" type="number" min="0" max="365"
                    data-testid="plan-reduce-days"
                    value={plan.reduction_after_days ?? 7}
                    onChange={(e) =>
                      set("reduction_after_days", e.target.value)} />
          </Field>
          <Field label="Bloquear após N dias *">
            <input className="input" type="number" min="0" max="365"
                    data-testid="plan-block-days"
                    value={plan.block_after_days ?? 20}
                    onChange={(e) =>
                      set("block_after_days", e.target.value)} />
          </Field>
        </div>
      </div>

      {/* Avançado - Franquia de dados mensal */}
      <div style={{ marginTop: 10, padding: 12,
                      background: "linear-gradient(135deg,#dbeafe,#eff6ff)",
                      border: "1px solid #bfdbfe", borderRadius: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        marginBottom: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: "#1e3a8a" }}>
            Avançado — Franquia de dados mensal
          </div>
          <label style={{ display: "flex", gap: 6, alignItems: "center",
                            fontSize: 11, color: "#1e40af" }}>
            <input type="checkbox" data-testid="plan-quota-enabled"
                    checked={!!plan.data_quota?.enabled}
                    onChange={(e) => set("data_quota",
                      { ...(plan.data_quota || {}),
                        enabled: e.target.checked })}
                    style={{ accentColor: "#2563eb" }} />
            Habilitar franquia
          </label>
        </div>
        {plan.data_quota?.enabled && (
          <div style={{ display: "grid",
                          gridTemplateColumns: "1fr 1fr 1fr",
                          gap: 12 }}>
            <Field label="Franquia (GB/mês)">
              <input className="input" type="number" min="0" step="1"
                      data-testid="plan-quota-gb"
                      value={plan.data_quota?.quota_gb || ""}
                      onChange={(e) => set("data_quota",
                        { ...(plan.data_quota || {}),
                          quota_gb: e.target.value })}
                      placeholder="500" />
            </Field>
            <Field label="Após atingir — Down (Kbps)">
              <input className="input" type="number" min="0"
                      data-testid="plan-quota-down"
                      value={plan.data_quota?.reduced_down_kbps ?? 2048}
                      onChange={(e) => set("data_quota",
                        { ...(plan.data_quota || {}),
                          reduced_down_kbps: e.target.value })} />
            </Field>
            <Field label="Após atingir — Up (Kbps)">
              <input className="input" type="number" min="0"
                      data-testid="plan-quota-up"
                      value={plan.data_quota?.reduced_up_kbps ?? 2048}
                      onChange={(e) => set("data_quota",
                        { ...(plan.data_quota || {}),
                          reduced_up_kbps: e.target.value })} />
            </Field>
          </div>
        )}
      </div>

      {/* VOD addons */}
      <div style={{ marginTop: 10, padding: 12,
                      background: "linear-gradient(135deg,#f3e8ff,#fae8ff)",
                      border: "1px solid #c4b5fd", borderRadius: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: "#5b21b6",
                        marginBottom: 8 }}>
          VOD — Pacotes de streaming inclusos no plano
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 8 }}>
          <CheckboxAddon label="Noggin" testid="vod-noggin"
            checked={!!plan.vod_packages?.noggin}
            onChange={(v) => set("vod_packages",
              { ...(plan.vod_packages || {}), noggin: v })} />
          <CheckboxAddon label="Paramount+" testid="vod-paramount"
            checked={!!plan.vod_packages?.paramount_plus}
            onChange={(v) => set("vod_packages",
              { ...(plan.vod_packages || {}), paramount_plus: v })} />
          <CheckboxAddon label="CDNTV" testid="vod-cdntv"
            checked={!!plan.vod_packages?.cdntv_enabled}
            onChange={(v) => set("vod_packages",
              { ...(plan.vod_packages || {}), cdntv_enabled: v })} />
        </div>
        {["yplay", "playhub", "zappingtv", "oletv", "multtv", "campsoft"]
          .map((key) => (
            <VodAddonField key={key} keyName={key} plan={plan} set={set} />
          ))}
      </div>

      {/* NFCom — Rateio */}
      <div style={{ marginTop: 10, padding: 12,
                      background: "linear-gradient(135deg,#fff7ed,#ffedd5)",
                      border: "1px solid #fed7aa", borderRadius: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: "#9a3412",
                        marginBottom: 4 }}>
          NFCom — Rateio por produto
        </div>
        <p style={{ fontSize: 11, color: "#7c2d12", marginTop: 0,
                      marginBottom: 8, lineHeight: 1.4 }}>
          Configuração para emissão automática de NFCom. Soma dos
          percentuais deve ser <b>100%</b>.
        </p>
        {(plan.nfcom_products || []).map((p, i) => (
          <div key={i} style={{ display: "flex", gap: 8,
                                  marginBottom: 6 }}>
            <input className="input" style={{ flex: 2 }}
                    data-testid={`nfcom-product-${i}`}
                    value={p.product_code || ""}
                    onChange={(e) => {
                      const arr = [...(plan.nfcom_products || [])];
                      arr[i] = { ...arr[i], product_code: e.target.value };
                      set("nfcom_products", arr);
                    }}
                    placeholder="Código do produto / serviço" />
            <input className="input" type="number" step="0.01" min="0" max="100"
                    style={{ flex: 1 }}
                    data-testid={`nfcom-pct-${i}`}
                    value={p.percentage ?? ""}
                    onChange={(e) => {
                      const arr = [...(plan.nfcom_products || [])];
                      arr[i] = { ...arr[i], percentage:
                        parseFloat(e.target.value) || 0 };
                      set("nfcom_products", arr);
                    }}
                    placeholder="%" />
            <button className="btn btn-ghost btn-sm"
                      onClick={() => {
                        const arr = [...(plan.nfcom_products || [])];
                        arr.splice(i, 1);
                        set("nfcom_products", arr);
                      }}>✗</button>
          </div>
        ))}
        <button className="btn btn-ghost btn-sm"
                  data-testid="nfcom-add"
                  onClick={() => set("nfcom_products", [
                    ...(plan.nfcom_products || []),
                    { product_code: "", percentage: 0 }])}>
          + Inserir Item
        </button>
      </div>

      {/* Detalhes adicionais */}
      <div style={{ marginTop: 10, padding: 12,
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0", borderRadius: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: "#0f172a",
                        marginBottom: 8 }}>
          ️ Detalhes adicionais
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 8 }}>
          <CheckRow label="Cobrar ativação separadamente"
            testid="plan-charge-activation"
            checked={!!plan.charge_activation_separately}
            onChange={(v) => set("charge_activation_separately", v)} />
          <CheckRow label="Exibir na página de prospectos"
            testid="plan-show-prospects"
            checked={!!plan.show_on_prospects_page}
            onChange={(v) => set("show_on_prospects_page", v)} />
          <CheckRow label="Exibir na central do assinante"
            testid="plan-show-center"
            checked={plan.show_on_subscriber_center !== false}
            onChange={(v) => set("show_on_subscriber_center", v)} />
          <CheckRow label="Descontinuar plano"
            testid="plan-discontinued"
            checked={!!plan.discontinued}
            onChange={(v) => set("discontinued", v)} />
          <CheckRow label="Contabilizar em conectados/desconectados"
            testid="plan-count-connected"
            checked={plan.count_in_connected !== false}
            onChange={(v) => set("count_in_connected", v)} />
        </div>
      </div>

      {/* Mikrotik avançado */}
      <div style={{ marginTop: 10, padding: 12,
                      background: "linear-gradient(135deg,#ecfeff,#cffafe)",
                      border: "1px solid #67e8f9", borderRadius: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: "#155e75",
                        marginBottom: 8 }}>
          ️ Mikrotik / FreeRADIUS — atributos avançados
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 8 }}>
          <Field label="IP Pool (Mikrotik)">
            <input className="input" data-testid="mtk-ip-pool"
                    value={plan.mikrotik?.ip_pool || ""}
                    onChange={(e) => set("mikrotik", {
                      ...(plan.mikrotik || {}), ip_pool: e.target.value })}
                    placeholder="ex: pool_residencial" />
          </Field>
          <Field label="Address-List (Firewall)">
            <input className="input" data-testid="mtk-address-list"
                    value={plan.mikrotik?.address_list || ""}
                    onChange={(e) => set("mikrotik", {
                      ...(plan.mikrotik || {}),
                      address_list: e.target.value })}
                    placeholder="ex: clientes-ativos" />
          </Field>
          <Field label="Mikrotik-Delegated-IPv6-Pool">
            <input className="input" data-testid="mtk-ipv6-delegated"
                    value={plan.mikrotik?.delegated_ipv6_pool || ""}
                    onChange={(e) => set("mikrotik", {
                      ...(plan.mikrotik || {}),
                      delegated_ipv6_pool: e.target.value })}
                    placeholder="opcional" />
          </Field>
          <Field label="Framed-IPv6-Pool">
            <input className="input" data-testid="mtk-ipv6-framed"
                    value={plan.mikrotik?.framed_ipv6_pool || ""}
                    onChange={(e) => set("mikrotik", {
                      ...(plan.mikrotik || {}),
                      framed_ipv6_pool: e.target.value })}
                    placeholder="opcional" />
          </Field>
        </div>
      </div>
    </>
  );
}
