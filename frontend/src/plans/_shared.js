import React from "react";

/* =============================================================
   Componentes utilitários compartilhados pelos sub-painéis de Planos.
   Field    — wrapper de label + input
   CheckRow — checkbox horizontal (linha)
   CheckboxAddon — checkbox com fundo pintado (VOD)
   VodAddonField — addon VOD com input de plano dependente
   KpiCard  — card colorido pra preview de reajuste
============================================================= */

export function Field({ label, children }) {
  return (
    <label style={{ display: "block" }}>
      <div style={{ fontSize: 11, color: "var(--text-muted)",
                     textTransform: "uppercase", letterSpacing: 0.4,
                     fontWeight: 700, marginBottom: 5 }}>
        {label}
      </div>
      {children}
    </label>
  );
}

export function CheckRow({ label, testid, checked, onChange }) {
  return (
    <label style={{ display: "flex", gap: 8, alignItems: "center",
                      fontSize: 12, color: "#334155", padding: "6px 0",
                      cursor: "pointer" }}>
      <input type="checkbox" data-testid={testid}
              checked={!!checked}
              onChange={(e) => onChange(e.target.checked)}
              style={{ accentColor: "#0ea5e9" }} />
      {label}
    </label>
  );
}

export function CheckboxAddon({ label, testid, checked, onChange }) {
  return (
    <label style={{ display: "flex", gap: 6, alignItems: "center",
                      padding: "5px 8px", borderRadius: 6,
                      background: checked ? "#ede9fe" : "transparent",
                      cursor: "pointer", fontSize: 12 }}>
      <input type="checkbox" data-testid={testid}
              checked={!!checked}
              onChange={(e) => onChange(e.target.checked)}
              style={{ accentColor: "#7c3aed" }} />
      {label}
    </label>
  );
}

export function VodAddonField({ keyName, plan, set }) {
  const obj = plan.vod_packages?.[keyName] || { enabled: false };
  const label = {
    yplay: "Yplay", playhub: "Playhub", zappingtv: "ZappingTV",
    oletv: "Olé TV", multtv: "Mult TV", campsoft: "Campsoft",
  }[keyName] || keyName;
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center",
                    marginTop: 6 }}>
      <label style={{ display: "flex", gap: 6, alignItems: "center",
                        fontSize: 12, minWidth: 105 }}>
        <input type="checkbox" data-testid={`vod-${keyName}`}
                checked={!!obj.enabled}
                onChange={(e) => set("vod_packages", {
                  ...(plan.vod_packages || {}),
                  [keyName]: { ...obj, enabled: e.target.checked } })}
                style={{ accentColor: "#7c3aed" }} />
        {label}
      </label>
      {obj.enabled && (
        <input className="input" style={{ flex: 1, height: 28 }}
                data-testid={`vod-${keyName}-plan`}
                value={obj.plan_name || ""}
                onChange={(e) => set("vod_packages", {
                  ...(plan.vod_packages || {}),
                  [keyName]: { ...obj, plan_name: e.target.value } })}
                placeholder={`Nome do plano ${label}`} />
      )}
    </div>
  );
}

export function KpiCard({ icon: Ico, color, label, value, sub }) {
  return (
    <div style={{
      padding: 14, borderRadius: 12,
      border: `1px solid ${color}33`,
      background: `${color}0A`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                     marginBottom: 6 }}>
        <Ico size={12} strokeWidth={2} style={{ color }} />
        <span style={{ fontSize: 10, fontWeight: 800, color,
                         textTransform: "uppercase", letterSpacing: 0.4 }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 20, fontWeight: 800,
                     color: "var(--text-primary)",
                     letterSpacing: "-0.02em" }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 3 }}>
          {sub}
        </div>
      )}
    </div>
  );
}
