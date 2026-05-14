import React, { useEffect, useRef, useState } from "react";
import { Filter, ChevronDown, Search, X, RotateCcw, Calendar } from "lucide-react";

/* ============================================================
   Filtro avançado das conversas — inspirado em UIs concorrentes
   (BotZap / ChatGuru). Modal popover ancorado num ícone funil
   no header do chat.

   Props:
     value: estado atual do filtro {
       unreadOnly, onlyMine, userIds[], channels[], search,
       dateAtendimentoIni, dateAtendimentoFim,
       dateInteracaoIni, dateInteracaoFim,
     }
     onChange(newValue): chamado quando OK clicado.
     onClear(): chamado quando "Limpar filtros".
     authUser: { id, name, email, role } — pra ativar "meus".
     attendants: lista [{ id, name }] pra popular "Filtrar por usuários".
============================================================ */

const BLANK_FILTER = {
  search: "",
  unreadOnly: false,
  onlyMine: false,
  userIds: [],
  channels: [],
  dateAtendimentoIni: "",
  dateAtendimentoFim: "",
  dateInteracaoIni: "",
  dateInteracaoFim: "",
};

export const CHANNEL_OPTIONS = [
  { id: "baileys", label: "WhatsApp Web (Baileys)", color: "#16a34a" },
  { id: "twilio",  label: "WhatsApp Business (Twilio)", color: "#0ea5e9" },
  { id: "meta_messenger", label: "Messenger (Meta)", color: "#6366f1" },
  { id: "meta_instagram", label: "Instagram (Meta)", color: "#ec4899" },
];

export function countActiveFilters(f) {
  if (!f) return 0;
  let n = 0;
  if (f.search) n += 1;
  if (f.unreadOnly) n += 1;
  if (f.onlyMine) n += 1;
  if ((f.userIds || []).length > 0) n += 1;
  if ((f.channels || []).length > 0) n += 1;
  if (f.dateAtendimentoIni || f.dateAtendimentoFim) n += 1;
  if (f.dateInteracaoIni || f.dateInteracaoFim) n += 1;
  return n;
}

export function makeBlankFilter() {
  return { ...BLANK_FILTER, userIds: [], channels: [] };
}

export default function WaChatFilterPopover({ value, onChange, onClear,
                                                  authUser, attendants }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(() => ({ ...BLANK_FILTER, ...(value || {}) }));
  const wrapperRef = useRef(null);

  useEffect(() => {
    setDraft({ ...BLANK_FILTER, ...(value || {}) });
  }, [value]);

  // Fecha o popover quando clicar fora.
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const activeCount = countActiveFilters(value);

  function apply() {
    onChange(draft);
    setOpen(false);
  }

  function reset() {
    const blank = makeBlankFilter();
    setDraft(blank);
    onClear();
    setOpen(false);
  }

  function toggleArrayItem(field, id) {
    setDraft((d) => {
      const arr = new Set(d[field] || []);
      if (arr.has(id)) arr.delete(id); else arr.add(id);
      return { ...d, [field]: Array.from(arr) };
    });
  }

  return (
    <div ref={wrapperRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        data-testid="wa-filter-toggle"
        title={activeCount > 0 ? `${activeCount} filtro(s) ativo(s)` : "Abrir filtros"}
        style={{
          padding: "7px 10px",
          borderRadius: 9,
          border: activeCount > 0
            ? "1px solid var(--accent)" : "1px solid var(--border-default)",
          background: activeCount > 0 ? "var(--accent-soft)" : "var(--bg-surface)",
          color: activeCount > 0 ? "var(--accent-strong, var(--accent))"
                                  : "var(--text-secondary)",
          fontSize: 12, fontWeight: 700, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
          position: "relative",
          transition: "all .15s",
        }}>
        <Filter size={14} />
        Filtros
        {activeCount > 0 && (
          <span style={{
            position: "absolute", top: -6, right: -6,
            minWidth: 18, height: 18, borderRadius: 9,
            background: "#dc2626", color: "#fff",
            fontSize: 10, fontWeight: 800,
            display: "grid", placeItems: "center",
            padding: "0 5px",
            boxShadow: "0 2px 6px rgba(220,38,38,.4)",
          }}>{activeCount}</span>
        )}
      </button>

      {open && (
        <div data-testid="wa-filter-popover" style={{
          position: "absolute",
          top: "calc(100% + 8px)",
          right: 0,
          zIndex: 100,
          width: 380,
          maxHeight: "calc(100vh - 200px)",
          overflowY: "auto",
          background: "var(--bg-surface)",
          border: "1px solid var(--border-default)",
          borderRadius: 12,
          boxShadow: "0 20px 50px rgba(15,23,42,.18)",
          padding: 14,
          animation: "wa-fade-in .15s ease-out",
        }}>
          {/* Search */}
          <SearchInput value={draft.search}
                       onChange={(v) => setDraft((d) => ({ ...d, search: v }))} />

          {/* Checkboxes */}
          <CheckBox
            checked={draft.unreadOnly}
            onChange={(v) => setDraft((d) => ({ ...d, unreadOnly: v }))}
            label="Apenas não lidas"
            testid="filter-unread-only" />
          <CheckBox
            checked={draft.onlyMine}
            onChange={(v) => setDraft((d) => ({ ...d, onlyMine: v }))}
            label="Apenas meus atendimentos"
            testid="filter-only-mine"
            disabled={!authUser?.id} />

          {/* Multi-select dropdowns */}
          <MultiSelect
            label="Filtrar por usuários"
            options={(attendants || []).map((a) => ({
              id: a.id, label: a.name || a.email || a.id,
              color: "#6366f1",
            }))}
            selected={draft.userIds}
            onToggle={(id) => toggleArrayItem("userIds", id)}
            testid="filter-users" />

          <MultiSelect
            label="Filtrar por canais"
            options={CHANNEL_OPTIONS}
            selected={draft.channels}
            onToggle={(id) => toggleArrayItem("channels", id)}
            testid="filter-channels" />

          {/* Date ranges */}
          <DateRange
            title="Filtrar pela data inicial do atendimento:"
            iniValue={draft.dateAtendimentoIni}
            fimValue={draft.dateAtendimentoFim}
            onIniChange={(v) => setDraft((d) => ({ ...d, dateAtendimentoIni: v }))}
            onFimChange={(v) => setDraft((d) => ({ ...d, dateAtendimentoFim: v }))}
            testid="filter-date-atendimento" />

          <DateRange
            title="Filtrar pela data da última interação:"
            iniValue={draft.dateInteracaoIni}
            fimValue={draft.dateInteracaoFim}
            onIniChange={(v) => setDraft((d) => ({ ...d, dateInteracaoIni: v }))}
            onFimChange={(v) => setDraft((d) => ({ ...d, dateInteracaoFim: v }))}
            testid="filter-date-interacao" />

          {/* Action buttons */}
          <div style={{
            display: "flex", justifyContent: "space-between",
            marginTop: 16, gap: 8,
          }}>
            <button
              onClick={apply}
              data-testid="filter-apply-btn"
              style={{
                padding: "9px 22px",
                borderRadius: 8,
                border: "none",
                background: "#0f172a",
                color: "white",
                fontSize: 12, fontWeight: 800,
                letterSpacing: 0.5,
                cursor: "pointer",
              }}>OK</button>
            <button
              onClick={reset}
              data-testid="filter-clear-btn"
              style={{
                padding: "9px 14px",
                borderRadius: 8,
                border: "1px solid var(--border-default)",
                background: "var(--bg-surface-2)",
                color: "var(--text-secondary)",
                fontSize: 12, fontWeight: 700,
                letterSpacing: 0.4,
                cursor: "pointer",
                display: "inline-flex", alignItems: "center", gap: 5,
              }}>
              <RotateCcw size={12} /> Limpar filtros
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SearchInput({ value, onChange }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "8px 10px", marginBottom: 12,
      border: "1px solid var(--border-default)",
      borderRadius: 8,
      background: "var(--bg-surface-2)",
    }}>
      <Search size={14} style={{ color: "var(--text-muted)" }} />
      <input
        type="text"
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Pesquisar"
        data-testid="filter-search-input"
        style={{
          flex: 1, border: "none", background: "transparent",
          outline: "none", fontSize: 13, color: "var(--text-primary)",
        }} />
      {value && (
        <button onClick={() => onChange("")} style={{
          background: "transparent", border: "none", cursor: "pointer",
          color: "var(--text-muted)", display: "grid", placeItems: "center",
        }}><X size={13} /></button>
      )}
    </div>
  );
}

function CheckBox({ checked, onChange, label, testid, disabled }) {
  return (
    <label data-testid={testid} style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "8px 6px", borderRadius: 6,
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.5 : 1,
      transition: "background .12s",
    }}
           onMouseEnter={(e) => { if (!disabled)
             e.currentTarget.style.background = "var(--bg-surface-2)"; }}
           onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
      <input type="checkbox" checked={!!checked} disabled={disabled}
              onChange={(e) => onChange(e.target.checked)}
              style={{
                width: 16, height: 16, cursor: disabled ? "not-allowed" : "pointer",
                accentColor: "var(--accent, #6366f1)",
              }} />
      <span style={{
        fontSize: 13, color: "var(--text-primary)",
        userSelect: "none",
      }}>{label}</span>
    </label>
  );
}

function MultiSelect({ label, options, selected, onToggle, testid }) {
  const [expanded, setExpanded] = useState(false);
  const selectedSet = new Set(selected || []);
  const selectedLabels = options
    .filter((o) => selectedSet.has(o.id))
    .map((o) => o.label);
  return (
    <div data-testid={testid} style={{ marginBottom: 10 }}>
      <button onClick={() => setExpanded((e) => !e)} style={{
        width: "100%",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 12px",
        border: "1px solid var(--border-default)",
        borderRadius: 8,
        background: "var(--bg-surface)",
        cursor: "pointer",
        fontSize: 13,
        color: selectedLabels.length > 0
          ? "var(--text-primary)" : "var(--text-muted)",
      }}>
        <span style={{
          flex: 1, textAlign: "left",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {selectedLabels.length === 0
            ? label
            : selectedLabels.length === 1
            ? selectedLabels[0]
            : `${selectedLabels[0]} +${selectedLabels.length - 1}`}
        </span>
        <ChevronDown size={14} style={{
          transition: "transform .15s",
          transform: expanded ? "rotate(180deg)" : "rotate(0)",
        }} />
      </button>
      {expanded && (
        <div style={{
          marginTop: 6, padding: 4,
          border: "1px solid var(--border-default)",
          borderRadius: 8,
          background: "var(--bg-surface-2)",
          maxHeight: 180, overflowY: "auto",
        }}>
          {(options || []).length === 0 && (
            <div style={{
              padding: "10px 8px", fontSize: 12,
              color: "var(--text-muted)", textAlign: "center",
            }}>Nenhuma opção disponível</div>
          )}
          {(options || []).map((opt) => (
            <label key={opt.id} style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "7px 8px", borderRadius: 6,
              cursor: "pointer",
              transition: "background .12s",
              fontSize: 12.5, color: "var(--text-primary)",
            }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = "var(--bg-surface)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "transparent";
                    }}>
              <input type="checkbox"
                      checked={selectedSet.has(opt.id)}
                      onChange={() => onToggle(opt.id)}
                      style={{
                        width: 14, height: 14, cursor: "pointer",
                        accentColor: opt.color || "var(--accent, #6366f1)",
                      }} />
              {opt.color && (
                <span style={{
                  width: 9, height: 9, borderRadius: 3,
                  background: opt.color, flexShrink: 0,
                }} />
              )}
              <span style={{ flex: 1 }}>{opt.label}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function DateRange({ title, iniValue, fimValue, onIniChange, onFimChange,
                       testid }) {
  return (
    <div data-testid={testid} style={{ marginTop: 12 }}>
      <div style={{
        fontSize: 11.5, color: "var(--text-secondary)", fontWeight: 600,
        marginBottom: 6,
      }}>{title}</div>
      <div style={{ display: "flex", gap: 8 }}>
        <DateInput value={iniValue} onChange={onIniChange} placeholder="Data inicial" />
        <DateInput value={fimValue} onChange={onFimChange} placeholder="Data final" />
      </div>
    </div>
  );
}

function DateInput({ value, onChange, placeholder }) {
  return (
    <div style={{
      flex: 1, display: "flex", alignItems: "center", gap: 6,
      padding: "8px 10px",
      border: "1px solid var(--border-default)",
      borderRadius: 8,
      background: "var(--bg-surface)",
    }}>
      <Calendar size={13} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
      <input type="date"
              value={value || ""}
              onChange={(e) => onChange(e.target.value)}
              placeholder={placeholder}
              style={{
                flex: 1, border: "none", outline: "none",
                background: "transparent", fontSize: 12,
                color: "var(--text-primary)", minWidth: 0,
              }} />
    </div>
  );
}
