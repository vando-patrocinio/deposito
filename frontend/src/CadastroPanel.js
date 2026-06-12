import React, { useEffect, useRef, useState } from "react";
import { Car } from "lucide-react";
import { api } from "@/api";
import {
  CARGO, CARGO_META, CARGO_OPTIONS_GROUPED,
  isLousaCargo, isAtendimentoCargo, clockInEnabledFor,
  cargoLabel, cargoEmoji,
} from "@/cargo";
import { AvatarZoomModal, Button, Card, Field, Icon, inputStyle, Row, StatusBadge } from "@/ui";
import OdometerConfigCard from "@/OdometerConfigCard";
import GeofenceMap from "@/GeofenceMap";
import useEventStream from "@/useEventStream";
import AssetsSection from "@/AssetsSection";
import DeactivationAssetsModal from "@/DeactivationAssetsModal";
import VehicleChecklistModal from "@/VehicleChecklistModal";
import { useAuth } from "@/AuthContext";

// Paleta de chips sóbria — usada nos cards de colaborador
const CHIP_PALETTE = {
  slate:   { bg: "#f1f5f9", fg: "#475569", bd: "#e2e8f0" },
  amber:   { bg: "#fef3c7", fg: "#92400e", bd: "#fde68a" },
  sky:     { bg: "#e0f2fe", fg: "#075985", bd: "#bae6fd" },
  emerald: { bg: "#dcfce7", fg: "#166534", bd: "#bbf7d0" },
  teal:    { bg: "#f0fdfa", fg: "#0d9488", bd: "#99f6e4" },
};
function chipStyle(tone = "slate") {
  const p = CHIP_PALETTE[tone] || CHIP_PALETTE.slate;
  return {
    fontSize: 10, fontWeight: 700, letterSpacing: ".02em",
    padding: "1px 7px", borderRadius: 999,
    background: p.bg, color: p.fg, border: `1px solid ${p.bd}`,
    whiteSpace: "nowrap",
  };
}

const EMPTY = {
  name: "",
  cpf: "",
  email: "",
  phone: "",
  role: "Colaborador de Campo",
  cargo: "",
  praca_id: "",
  praca_ids_extra: [],
  pis: "",
  admitted_at: "",
  matricula: "",
  schedule: { entrada: "08:00", inicio_intervalo: "12:00", fim_intervalo: "13:00", saida: "17:00" },
  overtime_policy: { mode: "banco", hourly_rate_brl: 0, weekday_multiplier: 1.5, sunday_multiplier: 2.0 },
  is_test_mode: false,
  clock_in_enabled: true,
  active: true,
  can_attend_whatsapp: false,  // só auditor libera (UI condicional)
  requires_vehicle: false,  // Frota: técnico/instalador opera veículo (gera vistoria semanal)
};

export default function CadastroPanel() {
  const { user: currentUser } = useAuth();
  const isAuditor = currentUser?.role === "auditor"
                       || currentUser?.role === "admin"
                       || currentUser?.role === "administrador";
  const [list, setList] = useState([]);
  const [pracas, setPracas] = useState([]);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [confirmReset, setConfirmReset] = useState(null);
  const [resettingId, setResettingId] = useState(null);
  const [zoomSrc, setZoomSrc] = useState(null);
  const [zoomCaption, setZoomCaption] = useState("");
  const [flash, setFlash] = useState("");
  const [fenceCounts, setFenceCounts] = useState({}); // {cid: count}
  const [allFences, setAllFences] = useState([]);     // todas as cercas do sistema (para reaproveitar)
  const [reuseSelected, setReuseSelected] = useState({}); // {fence_id: bool} marcadas para clonar ao salvar
  const [clockHistoryFor, setClockHistoryFor] = useState(null);   // colaborador selecionado para ver batidas
  const [assetsFor, setAssetsFor] = useState(null);   // colaborador selecionado para gerenciar itens em custódia
  const [vehicleChecklistFor, setVehicleChecklistFor] = useState(null); // checklist veicular
  const [deactivatedFor, setDeactivatedFor] = useState(null);   // popup automático ao desativar
  const [togglingId, setTogglingId] = useState(null);             // colab cujo toggle CLT está em flight

  async function toggleClockInEnabled(c) {
    const next = c.clock_in_enabled === false ? true : false;
    const msg = next
      ? `Ativar batimento de ponto para ${c.name}?\n\nApós ativar, ele(a) verá a tela de bater ponto no app e a Lousa só vai liberar após bater Entrada.`
      : `Desativar batimento de ponto para ${c.name}?\n\nApós desativar, ele(a) NÃO vê mais a tela de ponto — o app abre direto na Lousa de Serviços.`;
    if (!await window.confirm(msg)) return;
    setTogglingId(c.id);
    try {
      // PUT exige payload completo do CollaboratorIn — preserva todos os campos atuais
      await api.updateCollaborator(c.id, {
        name: c.name, cpf: c.cpf, email: c.email, phone: c.phone,
        role: c.role, company: c.company,
        cargo: c.cargo,  // CTO 11/06/2026: sem isso, default=None apaga "tecnico" e vira externo
        schedule: c.schedule, overtime_policy: c.overtime_policy,
        city: c.city ?? null, state: c.state ?? null, praca_id: c.praca_id ?? null,
        praca_ids_extra: c.praca_ids_extra || [],
        pis: c.pis || "", admitted_at: c.admitted_at || "",
        matricula: c.matricula || "",
        is_test_mode: !!c.is_test_mode,
        active: c.active !== false,
        can_attend_whatsapp: !!c.can_attend_whatsapp,  // preserva flag de Atendimento WhatsApp
        requires_vehicle: !!c.requires_vehicle,  // preserva flag de frota
        clock_in_enabled: next,
      });
      setFlash(`✅ ${c.name} agora ${next ? "BATE PONTO" : "NÃO BATE PONTO"}.`);
      await reload();
      setTimeout(() => setFlash(""), 4000);
    } catch (e) {
      setFlash(`❌ Erro: ${e?.response?.data?.detail || e.message}`);
    }
    setTogglingId(null);
  }

  async function reload() {
    try {
      const [cs, ps] = await Promise.all([api.listCollaborators(), api.listPracas()]);
      setList(cs);
      setPracas(ps);
      // Carrega cercas em paralelo: contagem + catálogo único para reaproveitar
      const counts = {};
      const fencesByCid = {};
      await Promise.all(cs.map(async (c) => {
        try {
          const fs = await api.listGeofences(c.id);
          counts[c.id] = fs.length;
          fencesByCid[c.id] = fs.map((f) => ({ ...f, _owner_name: c.name }));
        } catch { counts[c.id] = 0; fencesByCid[c.id] = []; }
      }));
      setFenceCounts(counts);
      setAllFences(Object.values(fencesByCid).flat());
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  }
  useEffect(() => { reload(); }, []);

  // Auto-refresh quando o worker Atlaz cria novos técnicos (SSE)
  const [atlazFlash, setAtlazFlash] = useState("");
  useEventStream({
    onEvent: (name, data) => {
      if (name === "atlaz_technicians_synced" && data?.created_count > 0) {
        setAtlazFlash(`${data.created_count} novo(s) técnico(s) sincronizado(s) do Atlaz`);
        reload();
        setTimeout(() => setAtlazFlash(""), 6000);
      }
    },
  });

  function startNew() {
    setForm(EMPTY);
    setEditing("new");
    setError("");
    setReuseSelected({});
  }
  function startEdit(c) {
    setForm({
      name: c.name, cpf: c.cpf, email: c.email, phone: c.phone,
      role: c.role || "Colaborador de Campo",
      cargo: c.cargo || "",
      praca_id: c.praca_id || "",
      praca_ids_extra: Array.isArray(c.praca_ids_extra) ? [...c.praca_ids_extra] : [],
      pis: c.pis || "",
      admitted_at: (c.admitted_at || "").slice(0, 10),
      matricula: c.matricula || "",
      schedule: c.schedule || EMPTY.schedule,
      overtime_policy: c.overtime_policy || EMPTY.overtime_policy,
      is_test_mode: !!c.is_test_mode,
      clock_in_enabled: c.clock_in_enabled !== false,  // default true (legado)
      active: c.active !== false,  // default true
      can_attend_whatsapp: !!c.can_attend_whatsapp,
      requires_vehicle: !!c.requires_vehicle,
      avatar_data_url: c.avatar_data_url || c.foto_id || "",
      foto_id: c.foto_id || c.avatar_data_url || "",
    });
    setEditing(c.id);
    setError("");
    setReuseSelected({});
  }

  async function save() {
    setBusy(true); setError("");
    try {
      let targetId = editing;
      // Detecta transição active=true→false ANTES de salvar (UI precisa do colab pré-update)
      const wasActive = editing && editing !== "new"
        ? (list.find((x) => x.id === editing)?.active !== false)
        : true;
      const willBeInactive = form.active === false;
      const justDeactivated = editing && editing !== "new" && wasActive && willBeInactive;

      if (editing === "new") {
        const created = await api.createCollaborator(form);
        targetId = created.id;
      } else {
        await api.updateCollaborator(editing, form);
      }
      // Reaproveitar cercas selecionadas (clona via duplicate)
      const selectedIds = Object.keys(reuseSelected).filter((k) => reuseSelected[k]);
      let clonedCount = 0;
      let skippedCount = 0;
      for (const fid of selectedIds) {
        try {
          const r = await api.duplicateGeofence(fid, [targetId]);
          clonedCount += r.created?.length || 0;
          skippedCount += r.skipped?.length || 0;
        } catch (e) {
          // segue mesmo se 1 falhar
          console.warn("duplicate failed", fid, e);
        }
      }
      await reload();
      setEditing(null);
      setReuseSelected({});
      if (selectedIds.length) {
        setFlash(`✅ Salvo. ${clonedCount} cerca(s) reaproveitada(s)${skippedCount ? ` · ${skippedCount} já existia(m)` : ""}.`);
      } else {
        setFlash("✅ Colaborador salvo.");
      }
      setTimeout(() => setFlash(""), 3500);
      // Pop-up automático com itens em custódia quando colaborador foi desativado
      if (justDeactivated) {
        const colObj = list.find((x) => x.id === editing);
        if (colObj) setDeactivatedFor({ ...colObj, active: false });
      }
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  async function remove(id) {
    setDeletingId(id);
    try {
      await api.deleteCollaborator(id);
      if (selectedId === id) setSelectedId(null);
      if (editing === id) setEditing(null);
      setFlash("✅ Colaborador excluído.");
      setTimeout(() => setFlash(""), 2500);
    } catch (e) {
      setFlash("❌ Erro: " + (e?.response?.data?.detail || e.message));
      setTimeout(() => setFlash(""), 4000);
    }
    setDeletingId(null);
    setConfirmDelete(null);
    await reload();
  }

  async function resetFace(c) {
    setResettingId(c.id);
    try {
      const r = await api.resetCollaboratorFace(c.id, true);
      setFlash(
        `✅ ${c.name}: avatar e dispositivo resetados.` +
        (r?.sessions_invalidated ? ` ${r.sessions_invalidated} sessão(ões) Google invalidada(s).` : "") +
        " Na próxima abertura do PWA, ele(a) precisará entrar novamente com Google."
      );
      setTimeout(() => setFlash(""), 5000);
    } catch (e) {
      setFlash("❌ Erro: " + (e?.response?.data?.detail || e.message));
      setTimeout(() => setFlash(""), 4000);
    }
    setResettingId(null);
    setConfirmReset(null);
    await reload();
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 420px)", gap: 18, alignItems: "start" }}>
      <div>
        <Card
          title="Colaboradores"
          action={<Button onClick={startNew} data-testid="new-collab-btn"><Icon name="plus" /> Novo</Button>}
        >
          {flash && (
            <div data-testid="collab-flash" style={{ background: flash.startsWith("✅") ? "#dcfce7" : "#fee2e2", color: flash.startsWith("✅") ? "#166534" : "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10, fontWeight: 700 }}>
              {flash}
            </div>
          )}
          {atlazFlash && (
            <div data-testid="atlaz-flash" style={{
              background: "linear-gradient(135deg,#ecfdf5,#d1fae5)",
              color: "#064e3b", padding: 10, borderRadius: 12, marginBottom: 10,
              fontWeight: 700, border: "1px solid #6ee7b7",
              animation: "fadeIn .3s ease-out",
            }}>
              {atlazFlash}
            </div>
          )}
          {list.length === 0 && <p style={{ color: "#64748b" }}>Nenhum colaborador cadastrado.</p>}
          {list.map((c) => {
            const clockOn = c.clock_in_enabled !== false;
            const indiv = fenceCounts[c.id] ?? 0;
            const hasPraca = c.praca_id && c.praca_id !== "NOTA";
            const totalFences = indiv + (hasPraca ? 1 : 0);
            const fenceTitle = !clockOn
              ? `${indiv} cerca(s) salva(s), mas não são aplicadas — colaborador não bate ponto (terceirizado/MEI). Para reativar, ligue "Bate ponto".`
              : hasPraca
                ? `${indiv} cerca(s) individual(is) + 1 praça vinculada`
                : `${indiv} cerca(s) individual(is)`;
            const praca = pracas.find((x) => x.id === c.praca_id);
            // CTO 12/06/2026 — chips ordenados; só os 3 mais relevantes visíveis, resto em tooltip "+N"
            const allChips = [];
            if (!clockOn) allChips.push({ tone: "slate", label: "não bate ponto", title: "Externo — app abre direto na Lousa" });
            if (c.is_test_mode) allChips.push({ tone: "teal", label: "modo teste", title: "Bate ponto em qualquer local com qualquer selfie" });
            if (!c.avatar_data_url) allChips.push({ tone: "amber", label: "sem avatar", title: "Colaborador não enviou foto" });
            if (!c.device_id && c.email) allChips.push({ tone: "sky", label: "aguardando Google", title: "Ainda não fez login com Google" });
            if (c.device_id) allChips.push({ tone: "emerald", label: "✓ dispositivo OK", title: `Vinculado a: ${c.google_email || "(Google)"}` });
            const visibleChips = allChips.slice(0, 3);
            const hiddenChips = allChips.slice(3);
            return (
            <div
              key={c.id}
              data-testid={`collab-card-${c.id}`}
              style={{
                background: "white",
                border: "1px solid #e2e8f0",
                borderRadius: 14,
                padding: 16,
                marginBottom: 12,
                boxShadow: "0 1px 3px rgba(15,23,42,.04)",
                transition: "box-shadow .15s ease, transform .15s ease",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.boxShadow = "0 4px 14px rgba(15,23,42,.08)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.boxShadow = "0 1px 3px rgba(15,23,42,.04)"; }}
            >
              {/* Cabeçalho: Avatar + Identidade + Dados de contato */}
              <div style={{ display: "grid", gridTemplateColumns: "72px minmax(0, 1fr) minmax(0, 260px)", gap: 14, alignItems: "start" }}>
                <button
                  type="button"
                  onClick={() => { if (c.avatar_data_url) { setZoomSrc(c.avatar_data_url); setZoomCaption(c.name); } }}
                  disabled={!c.avatar_data_url}
                  title={c.avatar_data_url ? "Clique para ampliar" : "Sem foto cadastrada"}
                  data-testid={`avatar-${c.id}`}
                  style={{
                    width: 64, height: 64, borderRadius: "50%", overflow: "hidden",
                    background: "#f1f5f9",
                    display: "grid", placeItems: "center", fontSize: 22,
                    border: "2px solid #e2e8f0",
                    padding: 0,
                    cursor: c.avatar_data_url ? "zoom-in" : "default",
                  }}
                >
                  {c.avatar_data_url ? <img src={c.avatar_data_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <Icon name="user" />}
                </button>

                {/* Coluna 2: identidade */}
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <strong data-testid={`collab-name-${c.id}`} style={{ fontSize: 16, letterSpacing: ".01em" }}>{c.name}</strong>
                    {c.code && (
                      <code
                        data-testid={`collab-code-${c.id}`}
                        style={{
                          background: "#0d9488", color: "#fff",
                          padding: "2px 8px", borderRadius: 6,
                          fontFamily: "ui-monospace, SFMono-Regular, monospace",
                          fontWeight: 700, fontSize: 11, letterSpacing: ".03em",
                        }}
                      >{c.code}</code>
                    )}
                    {!c.active && (
                      <span style={{ ...chipStyle("amber"), fontWeight: 800 }}>INATIVO</span>
                    )}
                  </div>
                  <div style={{ color: "#64748b", fontSize: 12.5, marginTop: 6,
                                  display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    {c.cargo && (
                      <span data-testid={`collab-cargo-${c.id}`} style={{
                        padding: "2px 9px", borderRadius: 999,
                        background: isLousaCargo(c.cargo) ? "#dbeafe" : "#ecfdf5",
                        color: isLousaCargo(c.cargo) ? "#1e40af" : "#047857",
                        fontSize: 11, fontWeight: 700,
                      }}>
                        {cargoEmoji(c.cargo)} {cargoLabel(c.cargo)}
                      </span>
                    )}
                    <span style={{ color: "#475569" }}>{c.role}</span>
                    {(praca || c.company) && (
                      <span style={{ color: "#94a3b8" }}>·</span>
                    )}
                    {praca
                      ? <span>{praca.city}/{praca.state}</span>
                      : c.company && <span>{c.company}</span>}
                  </div>
                  {/* Chips de status (max 3 + "+N") */}
                  {allChips.length > 0 && (
                    <div style={{ marginTop: 8, display: "flex", gap: 5, flexWrap: "wrap" }}>
                      {visibleChips.map((chip, i) => (
                        <span key={i} title={chip.title} style={chipStyle(chip.tone)}>
                          {chip.label}
                        </span>
                      ))}
                      {hiddenChips.length > 0 && (
                        <span
                          title={hiddenChips.map(x => x.label).join(" · ")}
                          style={{ ...chipStyle("slate"), cursor: "help" }}
                        >
                          +{hiddenChips.length}
                        </span>
                      )}
                    </div>
                  )}
                  <CollabShareLink collaborator={c} />
                </div>

                {/* Coluna 3: contato — empilhado e legível */}
                <div style={{
                  fontSize: 12, color: "#475569",
                  display: "flex", flexDirection: "column", gap: 4,
                  borderLeft: "1px solid #f1f5f9", paddingLeft: 12,
                }}>
                  {c.cpf && (
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ color: "#94a3b8", fontSize: 10, fontWeight: 700,
                                       letterSpacing: ".06em", minWidth: 30 }}>CPF</span>
                      <span style={{ fontFamily: "ui-monospace, monospace" }}>{c.cpf}</span>
                    </div>
                  )}
                  {c.email && (
                    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                      <span style={{ color: "#94a3b8", fontSize: 10, fontWeight: 700,
                                       letterSpacing: ".06em", minWidth: 30 }}>E-MAIL</span>
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                                       whiteSpace: "nowrap" }} title={c.email}>{c.email}</span>
                    </div>
                  )}
                  {c.phone && (
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ color: "#94a3b8", fontSize: 10, fontWeight: 700,
                                       letterSpacing: ".06em", minWidth: 30 }}>TEL</span>
                      <span>{c.phone}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Ações agrupadas em 2 fileiras */}
              {confirmDelete === c.id ? (
                <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid #fecaca",
                                background: "#fef2f2", margin: "14px -16px -16px", padding: "12px 16px",
                                borderRadius: "0 0 14px 14px",
                                display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{ marginRight: "auto", fontSize: 12.5, color: "#991b1b", fontWeight: 700 }}>
                    ⚠ Apagar tudo? Não dá pra desfazer.
                  </span>
                  <Button variant="secondary" onClick={() => setConfirmDelete(null)}>Cancelar</Button>
                  <Button variant="danger" onClick={() => remove(c.id)} disabled={deletingId === c.id} data-testid={`confirm-del-${c.id}`}>
                    {deletingId === c.id ? "..." : "Sim, excluir"}
                  </Button>
                </div>
              ) : confirmReset === c.id ? (
                <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid #fde68a",
                                background: "#fffbeb", margin: "14px -16px -16px", padding: "12px 16px",
                                borderRadius: "0 0 14px 14px",
                                display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{ marginRight: "auto", fontSize: 12.5, color: "#92400e", fontWeight: 700 }}>
                    Resetar avatar e dispositivo? O colaborador precisará entrar com Google novamente.
                  </span>
                  <Button variant="secondary" onClick={() => setConfirmReset(null)}>Cancelar</Button>
                  <Button variant="danger" onClick={() => resetFace(c)} disabled={resettingId === c.id} data-testid={`confirm-reset-${c.id}`}>
                    {resettingId === c.id ? "..." : "Sim, resetar"}
                  </Button>
                </div>
              ) : (
                <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid #f1f5f9" }}>
                  {/* OPERAÇÃO */}
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 8 }}>
                    <span style={{ fontSize: 9, fontWeight: 800, color: "#94a3b8",
                                     letterSpacing: ".1em", marginRight: 6 }}>OPERAÇÃO</span>
                    <Button
                      variant="soft"
                      onClick={() => setSelectedId(c.id)}
                      data-testid={`fences-${c.id}`}
                      title={fenceTitle}
                      style={!clockOn ? {
                        background: "#fafafa", color: "#64748b",
                        border: "1px dashed #cbd5e1", fontWeight: 600,
                      } : undefined}
                    >
                      <Icon name="map" /> Cercas
                      <span data-testid={`fence-count-${c.id}`} style={{
                        marginLeft: 6,
                        background: !clockOn ? "#cbd5e1" : (totalFences ? "#0f172a" : "#94a3b8"),
                        color: "white", borderRadius: 999, padding: "1px 7px",
                        fontSize: 10, fontWeight: 800,
                      }}>
                        {totalFences}
                      </span>
                      {!clockOn && totalFences > 0 && (
                        <span style={{ marginLeft: 6, fontSize: 10, fontWeight: 700, color: "#9a3412" }}>
                          (inativas)
                        </span>
                      )}
                    </Button>
                    {clockOn && (
                      <Button
                        variant="soft"
                        onClick={() => setClockHistoryFor(c)}
                        data-testid={`view-clock-${c.id}`}
                        title="Ver batimentos de ponto deste colaborador"
                      >
                        <Icon name="clock" /> Pontos
                      </Button>
                    )}
                    <Button
                      variant="soft"
                      onClick={() => setAssetsFor(c)}
                      data-testid={`view-assets-${c.id}`}
                      title="Itens em custódia (Checklist EPIs)"
                    >
                      <Icon name="clipboard" /> Checklist
                    </Button>
                    <Button
                      variant="soft"
                      onClick={() => setVehicleChecklistFor(c)}
                      data-testid={`view-vehicle-${c.id}`}
                      title="Checklist veicular pré-jornada (CONTRAN)"
                    >
                      <Car size={14} strokeWidth={1.75} /> Veicular
                    </Button>
                  </div>
                  {/* GESTÃO */}
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                    <span style={{ fontSize: 9, fontWeight: 800, color: "#94a3b8",
                                     letterSpacing: ".1em", marginRight: 6 }}>GESTÃO</span>
                    <Button
                      variant="soft"
                      onClick={() => toggleClockInEnabled(c)}
                      disabled={togglingId === c.id}
                      data-testid={`toggle-clock-${c.id}`}
                      title={clockOn
                        ? "Clique para desativar — colaborador não vai mais bater ponto"
                        : "Clique para ativar — colaborador volta a bater ponto"}
                      style={{
                        background: clockOn ? "#f0fdf4" : "#fff7ed",
                        color: clockOn ? "#166534" : "#9a3412",
                        border: `1px solid ${clockOn ? "#86efac" : "#fdba74"}`,
                        fontWeight: 700,
                      }}
                    >
                      {togglingId === c.id ? "..." : clockOn ? "● Bate ponto ON" : "○ Bate ponto OFF"}
                    </Button>
                    <Button
                      variant="soft"
                      onClick={() => setConfirmReset(c.id)}
                      disabled={!c.avatar_data_url}
                      title={c.avatar_data_url ? "Remove a foto de referência — próxima selfie vira o novo avatar" : "Colaborador ainda não tem avatar"}
                      data-testid={`reset-face-${c.id}`}
                    >
                      <Icon name="camera" /> Resetar
                    </Button>
                    <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                      <Button variant="secondary" onClick={() => startEdit(c)} data-testid={`edit-${c.id}`}>
                        <Icon name="gear" /> Editar
                      </Button>
                      <Button variant="danger" onClick={() => setConfirmDelete(c.id)} data-testid={`del-${c.id}`} title="Excluir colaborador">
                        <Icon name="trash" />
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </div>
            );
          })}
        </Card>

        {selectedId && (
          <GeofencesModal
            collaboratorId={selectedId}
            collaborator={list.find((x) => x.id === selectedId)}
            allCollaborators={list}
            onClose={async () => { setSelectedId(null); await reload(); }}
          />
        )}
      </div>

      <AvatarZoomModal
        src={zoomSrc}
        caption={zoomCaption}
        onClose={() => { setZoomSrc(null); setZoomCaption(""); }}
      />

      {clockHistoryFor && (
        <ClockHistoryModal
          collaborator={clockHistoryFor}
          onClose={() => setClockHistoryFor(null)}
        />
      )}

      {assetsFor && (
        <AssetsSection
          collaborator={assetsFor}
          onClose={() => setAssetsFor(null)}
        />
      )}

      {deactivatedFor && (
        <DeactivationAssetsModal
          collaborator={deactivatedFor}
          onClose={() => setDeactivatedFor(null)}
        />
      )}

      {vehicleChecklistFor && (
        <VehicleChecklistModal
          collaborator={vehicleChecklistFor}
          onClose={() => setVehicleChecklistFor(null)}
        />
      )}

      {editing !== null ? (
        <Card title={editing === "new" ? "Novo colaborador" : "Editar colaborador"}>
          {error && <div data-testid="form-error" style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10 }}>{error}</div>}

          {/* Avatar / Foto do crachá ("foto_id") */}
          {editing !== "new" && (
            <AvatarUploader
              collaboratorId={editing}
              currentUrl={form.avatar_data_url || form.foto_id || null}
              name={form.name}
              onUpdated={(dataUrl) => {
                setForm({ ...form, avatar_data_url: dataUrl, foto_id: dataUrl });
                reload();
              }}
            />
          )}

          <Field label="Nome completo">
            <input data-testid="inp-name" style={inputStyle} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="CPF">
            <input data-testid="inp-cpf" style={inputStyle} value={form.cpf} onChange={(e) => setForm({ ...form, cpf: e.target.value })} placeholder="000.000.000-00" />
          </Field>

          {/* Dados RH — aparecem no cabeçalho do espelho de ponto (Control iD) */}
          <div style={{
            display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10,
            padding: 12, background: "#f8fafc", borderRadius: 12,
            border: "1px solid #e2e8f0", marginTop: 4, marginBottom: 4,
          }}>
            <Field label="PIS / PASEP">
              <input data-testid="inp-pis" style={inputStyle}
                     value={form.pis || ""}
                     onChange={(e) => setForm({ ...form, pis: e.target.value })}
                     placeholder="000.00000.00-0" />
            </Field>
            <Field label="Data de admissão">
              <input data-testid="inp-admitted-at" type="date" style={inputStyle}
                     value={form.admitted_at || ""}
                     onChange={(e) => setForm({ ...form, admitted_at: e.target.value })} />
            </Field>
            <Field label="Nº matrícula">
              <input data-testid="inp-matricula" style={inputStyle}
                     value={form.matricula || ""}
                     onChange={(e) => setForm({ ...form, matricula: e.target.value })}
                     placeholder="0001" />
            </Field>
          </div>

          <Field label="E-mail">
            <input data-testid="inp-email" style={inputStyle} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field label="Telefone">
            <input data-testid="inp-phone" style={inputStyle} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="+55 11 99999-0000" />
          </Field>
          <Field label="Cargo (função operacional)">
            <select
              data-testid="inp-cargo"
              style={inputStyle}
              value={form.cargo || ""}
              onChange={(e) => {
                const cargo = e.target.value;
                setForm({
                  ...form,
                  cargo,
                  clock_in_enabled: cargo === CARGO.ASSOCIADO ? false : true,
                });
              }}
            >
              <option value="">— Selecione o cargo —</option>
              {CARGO_OPTIONS_GROUPED.map((g) => (
                <optgroup key={g.label} label={g.label}>
                  {g.options.map((c) => (
                    <option key={c} value={c}>
                      {CARGO_META[c].emoji} {CARGO_META[c].label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            {form.cargo && (
              <div data-testid="cargo-rules-hint" style={{
                marginTop: 6, padding: "6px 10px",
                background: "#ecfeff", border: "1px solid #67e8f9",
                borderRadius: 8, fontSize: 11, color: "#155e75",
                display: "flex", flexWrap: "wrap", gap: 8,
              }}>
                {isLousaCargo(form.cargo) ? (
                  <span>✓ Aparece na Lousa de Agendamento</span>
                ) : isAtendimentoCargo(form.cargo) ? (
                  <span>✓ Acessa Atendimento (WhatsApp tickets)</span>
                ) : null}
                {clockInEnabledFor(form.cargo)
                  ? <span>✓ Bate ponto</span>
                  : <span>⊘ NÃO bate ponto (Associado)</span>}
              </div>
            )}
          </Field>
          <Field label="Cargo livre (apenas texto descritivo — opcional)">
            <input style={inputStyle} value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
              placeholder="Ex: Técnico Senior, Coordenador..." />
          </Field>
          <Field label="Praça principal (local onde trabalha a maior parte do tempo)">
            {pracas.length === 0 ? (
              <div style={{ background: "#fffbeb", border: "1px dashed #fde68a", color: "#92400e", padding: 10, borderRadius: 12, fontSize: 13 }}>
                Nenhuma praça cadastrada ainda. Vá até a aba <strong>Praças</strong> e cadastre uma — ela aparecerá aqui.
              </div>
            ) : (
              <select
                data-testid="inp-praca"
                style={inputStyle}
                value={form.praca_id || ""}
                onChange={(e) => setForm({ ...form, praca_id: e.target.value })}
              >
                <option value="">— Selecione a praça —</option>
                <option value="NOTA">Endereço da Nota (cerca dinâmica)</option>
                {pracas.map((p) => (
                  <option key={p.id} value={p.id}>{p.city}/{p.state} — {p.name}</option>
                ))}
              </select>
            )}
            {form.praca_id === "NOTA" && (
              <div style={{ marginTop: 6, padding: 10, background: "#e0f2fe", border: "1px solid #0ea5e9", borderRadius: 10, fontSize: 12, color: "#075985" }}>
                <strong>Praça Nota:</strong> este colaborador pode bater ponto direto no endereço do cliente
                (cerca virtual gerada automaticamente no endereço da bolha aberta ou da próxima pendente).
                Útil para técnicos que vão direto ao cliente sem passar na empresa, economizando tempo.
                O raio da cerca é configurado em <strong>Configurações → Tempos de Referência</strong>.
              </div>
            )}
          </Field>

          {/* Praças secundárias — usadas quando o colaborador opera em mais de
              uma unidade. A cerca virtual considera QUALQUER uma das praças
              listadas (principal + secundárias). */}
          {pracas.length > 0 && form.praca_id && form.praca_id !== "NOTA" && (
            <Field label="Praças adicionais (opcional — colaborador opera em mais de um local)">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                {(form.praca_ids_extra || []).map((pid) => {
                  const p = pracas.find((x) => x.id === pid);
                  if (!p) return null;
                  return (
                    <span key={pid} data-testid={`c-extra-praca-tag-${pid}`} style={{
                      display: "inline-flex", alignItems: "center", gap: 6,
                      padding: "4px 10px", borderRadius: 999,
                      background: "#ecfdf5", border: "1px solid #86efac",
                      color: "#065f46", fontSize: 12, fontWeight: 600,
                    }}>
                      {p.city}/{p.state} — {p.name}
                      <button
                        type="button"
                        onClick={() => setForm({
                          ...form,
                          praca_ids_extra: (form.praca_ids_extra || []).filter((x) => x !== pid),
                        })}
                        style={{
                          border: "none", background: "transparent", color: "#065f46",
                          cursor: "pointer", fontSize: 14, padding: 0, lineHeight: 1,
                        }}
                      >×</button>
                    </span>
                  );
                })}
                {(form.praca_ids_extra || []).length === 0 && (
                  <span style={{ fontSize: 12, color: "#94a3b8" }}>Nenhuma praça adicional.</span>
                )}
              </div>
              <select
                data-testid="inp-praca-extra-add"
                value=""
                onChange={(e) => {
                  const val = e.target.value;
                  if (!val) return;
                  const cur = form.praca_ids_extra || [];
                  if (cur.includes(val)) return;
                  setForm({ ...form, praca_ids_extra: [...cur, val] });
                  e.target.value = "";
                }}
                style={{ ...inputStyle, maxWidth: 380 }}
              >
                <option value="">+ Adicionar praça adicional...</option>
                {pracas
                  .filter((p) => p.id !== form.praca_id && !(form.praca_ids_extra || []).includes(p.id))
                  .map((p) => (
                    <option key={p.id} value={p.id}>{p.city}/{p.state} — {p.name}</option>
                  ))}
              </select>
              <p style={{ marginTop: 4, fontSize: 11, color: "#94a3b8" }}>
                As cercas virtuais dessas praças adicionais também serão aceitas para este colaborador.
              </p>
            </Field>
          )}

          {/* Modo de trabalho — controla se o colaborador bate ponto */}
          <div data-testid="clock-in-mode-block" style={{
            background: form.clock_in_enabled ? "#f0f9ff" : "#fff7ed",
            border: `2px solid ${form.clock_in_enabled ? "#0ea5e9" : "#fb923c"}`,
            borderRadius: 14, padding: 12, marginTop: 12, marginBottom: 6,
            transition: "all .2s",
          }}>
            <label style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer" }}>
              <input
                data-testid="inp-clock-in-enabled"
                type="checkbox"
                checked={!!form.clock_in_enabled}
                onChange={(e) => setForm({ ...form, clock_in_enabled: e.target.checked })}
                style={{ marginTop: 3, transform: "scale(1.4)" }}
              />
              <div>
                <strong style={{ color: form.clock_in_enabled ? "#0369a1" : "#9a3412" }}>
                  {form.clock_in_enabled ? "CLT — bate ponto" : "Não bate ponto (terceirizado/MEI)"}
                </strong>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                  {form.clock_in_enabled
                    ? "Colaborador CLT — vê tela de Entrada/Intervalo/Saída no app e a Lousa só libera após bater Entrada."
                    : "Colaborador externo — o app abre direto na Lousa de Serviços, sem registro de ponto. Ideal para freelancer/MEI/3rd party."}
                </div>
              </div>
            </label>
          </div>

          {/* Modo Teste — admin only */}
          <div data-testid="test-mode-block" style={{
            background: form.is_test_mode ? "#f0fdfa" : "#f8fafc",
            border: `2px solid ${form.is_test_mode ? "#0d9488" : "#e2e8f0"}`,
            borderRadius: 14, padding: 12, marginTop: 12, marginBottom: 6,
            transition: "all .2s",
          }}>
            <label style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer" }}>
              <input
                data-testid="inp-test-mode"
                type="checkbox"
                checked={!!form.is_test_mode}
                onChange={(e) => setForm({ ...form, is_test_mode: e.target.checked })}
                style={{ marginTop: 3, transform: "scale(1.4)" }}
              />
              <div>
                <strong style={{ color: form.is_test_mode ? "#0d9488" : "#0f172a" }}>
                  Modo Teste (Admin)
                </strong>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                  Quando ativado, este colaborador pode bater ponto em <strong>qualquer localização</strong> e
                  com <strong>qualquer selfie</strong> — útil para demos e validação. Os registros ficam
                  marcados com na auditoria.
                </div>
              </div>
            </label>
          </div>

          {/* Status do colaborador — ativo / inativo */}
          <div data-testid="active-block" style={{
            background: form.active === false ? "#fef2f2" : "#f0fdf4",
            border: `2px solid ${form.active === false ? "#fca5a5" : "#86efac"}`,
            borderRadius: 14, padding: 12, marginTop: 12, marginBottom: 6,
            transition: "all .2s",
          }}>
            <label style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer" }}>
              <input
                data-testid="inp-active"
                type="checkbox"
                checked={form.active !== false}
                onChange={(e) => setForm({ ...form, active: e.target.checked })}
                style={{ marginTop: 3, transform: "scale(1.4)" }}
              />
              <div>
                <strong style={{ color: form.active === false ? "#991b1b" : "#166534" }}>
                  {form.active === false ? "Inativo (desligado/desativado)" : "✅ Ativo"}
                </strong>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                  Ao desativar, o colaborador <strong>não bate mais ponto</strong> e some das listas operacionais.
                  {' '}Se ele tiver itens em custódia ativos, ao salvar você verá a lista pra cobrar/devolver e
                  poderá imprimir o romaneio.
                </div>
              </div>
            </label>
          </div>

          {/* Frota — opera veículo? (gera vistoria semanal automática) */}
          <div data-testid="fleet-perm-block" style={{
            background: form.requires_vehicle ? "#fff7ed" : "#f8fafc",
            border: `2px solid ${form.requires_vehicle ? "#fb923c" : "#e2e8f0"}`,
            borderRadius: 14, padding: 12, marginTop: 12, marginBottom: 6,
            transition: "all .2s",
          }}>
            <label style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer" }}>
              <input
                data-testid="inp-requires-vehicle"
                type="checkbox"
                checked={!!form.requires_vehicle}
                onChange={(e) => setForm({ ...form, requires_vehicle: e.target.checked })}
                style={{ marginTop: 3, transform: "scale(1.4)" }}
              />
              <div>
                <strong style={{ color: form.requires_vehicle ? "#9a3412" : "#0f172a" }}>
                  {form.requires_vehicle ? "Opera veículo da empresa" : "Não opera veículo"}
                </strong>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                  Quando marcado, o colaborador <strong>fará vistoria semanal</strong> obrigatória do veículo
                  (5 fotos + KM, com validação por IA) e poderá receber transferências de frota com assinatura digital.
                </div>
              </div>
            </label>
          </div>

          {/* Permissão Atendimento WhatsApp — SOMENTE AUDITOR pode editar */}
          {isAuditor ? (
            <div data-testid="whatsapp-perm-block" style={{
              background: form.can_attend_whatsapp ? "#eff6ff" : "#f8fafc",
              border: `2px solid ${form.can_attend_whatsapp ? "#3b82f6" : "#cbd5e1"}`,
              borderRadius: 14, padding: 12, marginTop: 10, marginBottom: 6,
              transition: "all .2s",
            }}>
              <label style={{ display: "flex", gap: 10, alignItems: "flex-start",
                                 cursor: "pointer" }}>
                <input
                  data-testid="inp-can-attend-whatsapp"
                  type="checkbox"
                  checked={!!form.can_attend_whatsapp}
                  onChange={(e) => setForm({ ...form,
                                              can_attend_whatsapp: e.target.checked })}
                  style={{ marginTop: 3, transform: "scale(1.4)" }}
                />
                <div>
                  <strong style={{ color: form.can_attend_whatsapp
                                       ? "#1e3a8a" : "#475569",
                                       display: "inline-flex",
                                       alignItems: "center", gap: 6 }}>
                    Pode abrir o Atendimento WhatsApp
                    <span style={{
                      background: "#fef3c7", color: "#92400e",
                      fontSize: 9.5, fontWeight: 800,
                      padding: "1px 6px", borderRadius: 999,
                      marginLeft: 4,
                    }}>AUDITOR</span>
                  </strong>
                  <div style={{ fontSize: 12, color: "#64748b", marginTop: 4,
                                  lineHeight: 1.4 }}>
                    Quando marcado, o menu <strong>“Atendimento IA”</strong> aparece
                    na sidebar deste colaborador e ele pode assumir conversas que
                    a Isabella escalou. Esse acesso é uma decisão de
                    <strong> conformidade/auditoria</strong> — por isso só o
                    auditor pode liberar.
                  </div>
                </div>
              </label>
            </div>
          ) : (
            // Mostra apenas como informação somente-leitura para gestores
            form.can_attend_whatsapp && (
              <div data-testid="whatsapp-perm-readonly" style={{
                background: "#eff6ff",
                border: "1px solid #bfdbfe",
                borderRadius: 10, padding: 10, marginTop: 10, marginBottom: 6,
                fontSize: 12, color: "#1e3a8a",
              }}>
                Este colaborador <strong>tem acesso ao Atendimento WhatsApp</strong>.
                {" "}<span style={{ color: "#64748b" }}>
                  Apenas auditor pode revogar.
                </span>
              </div>
            )
          )}

          <h4 style={{ margin: "16px 0 6px" }}>Horário de trabalho</h4>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {[
              ["entrada", "Entrada"],
              ["inicio_intervalo", "Início intervalo"],
              ["fim_intervalo", "Fim intervalo"],
              ["saida", "Saída"],
            ].map(([k, label]) => (
              <Field key={k} label={label}>
                <input
                  data-testid={`sch-${k}`}
                  type="time"
                  style={inputStyle}
                  value={form.schedule[k]}
                  onChange={(e) => setForm({ ...form, schedule: { ...form.schedule, [k]: e.target.value } })}
                />
              </Field>
            ))}
          </div>

          <h4 style={{ margin: "16px 0 6px" }}>Política de horas extras</h4>
          <Field label="Tratamento do excedente">
            <select
              data-testid="ot-mode"
              style={inputStyle}
              value={form.overtime_policy?.mode || "banco"}
              onChange={(e) => setForm({ ...form, overtime_policy: { ...form.overtime_policy, mode: e.target.value } })}
            >
              <option value="banco">Banco de horas (default — compensação)</option>
              <option value="pago">Hora extra paga (R$)</option>
            </select>
          </Field>
          {form.overtime_policy?.mode === "pago" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
              <Field label="Valor da hora normal (R$)">
                <input
                  data-testid="ot-rate"
                  type="number" step="0.01" min="0"
                  style={inputStyle}
                  value={form.overtime_policy?.hourly_rate_brl ?? 0}
                  onChange={(e) => setForm({ ...form, overtime_policy: { ...form.overtime_policy, hourly_rate_brl: Number(e.target.value) } })}
                />
              </Field>
              <Field label="Mult. dia útil (CLT 50%)">
                <input
                  type="number" step="0.1" min="1"
                  style={inputStyle}
                  value={form.overtime_policy?.weekday_multiplier ?? 1.5}
                  onChange={(e) => setForm({ ...form, overtime_policy: { ...form.overtime_policy, weekday_multiplier: Number(e.target.value) } })}
                />
              </Field>
              <Field label="Mult. dom/feriado (100%)">
                <input
                  type="number" step="0.1" min="1"
                  style={inputStyle}
                  value={form.overtime_policy?.sunday_multiplier ?? 2.0}
                  onChange={(e) => setForm({ ...form, overtime_policy: { ...form.overtime_policy, sunday_multiplier: Number(e.target.value) } })}
                />
              </Field>
            </div>
          )}

          {/* Reaproveitar cercas pré-cadastradas */}
          {(() => {
            // De-duplica por (name + lat + lng + radius) para não mostrar 5 cópias da mesma "casa"
            const seen = new Set();
            const candidates = (allFences || []).filter((f) => {
              if (!f || !f.id) return false;
              if (editing !== "new" && f.collaborator_id === editing) return false; // já tem
              const key = `${f.name}|${Number(f.lat).toFixed(5)}|${Number(f.lng).toFixed(5)}|${f.radius}`;
              if (seen.has(key)) return false;
              seen.add(key);
              return true;
            });
            if (candidates.length === 0) return null;
            return (
              <div data-testid="reuse-fences" style={{
                background: "#f0f9ff", border: "1px solid #bae6fd",
                borderRadius: 12, padding: 12, marginTop: 14, marginBottom: 6,
              }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#075985", marginBottom: 4 }}>
                  Reaproveitar cercas já cadastradas
                </div>
                <div style={{ fontSize: 12, color: "#475569", marginBottom: 8 }}>
                  Marque para clonar para este colaborador ao salvar (mantém o original intacto).
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 6, maxHeight: 220, overflowY: "auto" }}>
                  {candidates.map((f) => (
                    <label
                      key={f.id}
                      data-testid={`reuse-${f.id}`}
                      style={{
                        display: "flex", alignItems: "center", gap: 8,
                        background: "white", border: "1px solid #e2e8f0",
                        borderRadius: 10, padding: "8px 10px", fontSize: 13, cursor: "pointer",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={!!reuseSelected[f.id]}
                        onChange={() => setReuseSelected((p) => ({ ...p, [f.id]: !p[f.id] }))}
                        data-testid={`reuse-check-${f.id}`}
                      />
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <strong>{f.name}</strong> <span style={{ fontSize: 10, color: "#64748b", fontWeight: 700 }}>{f.type}</span>
                        <div style={{ fontSize: 11, color: "#94a3b8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {f.address} · raio {f.radius}m · {f._owner_name}
                        </div>
                      </span>
                    </label>
                  ))}
                </div>
                {Object.values(reuseSelected).filter(Boolean).length > 0 && (
                  <div style={{ fontSize: 12, color: "#0f766e", marginTop: 8, fontWeight: 700 }}>
                    {Object.values(reuseSelected).filter(Boolean).length} cerca(s) será(ão) clonada(s) ao salvar.
                  </div>
                )}
              </div>
            );
          })()}

          {/* iter189 — Card de Odômetro Semanal */}
          {editing !== "new" && (
            <OdometerConfigCard collabId={editing} />
          )}

          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <Button onClick={save} disabled={busy} data-testid="save-collab-btn">{busy ? "Salvando..." : "Salvar"}</Button>
            <Button variant="secondary" onClick={() => setEditing(null)}>Cancelar</Button>
          </div>
        </Card>
      ) : (
        <Card title="Como funciona">
          <ol style={{ color: "#475569", lineHeight: 1.7 }}>
            <li>Cadastre o colaborador com nome, CPF, e-mail, telefone e horário.</li>
            <li>Adicione as cercas dele em <strong>Cercas</strong> (Cliente, Loja, Base) — basta o endereço, o sistema localiza no mapa.</li>
            <li>O raio padrão é <strong>15 metros</strong>.</li>
            <li>Ao bater ponto, a IA verifica o rosto e compara com a foto cadastrada.</li>
            <li>A primeira selfie aprovada vira a foto de cadastro automaticamente.</li>
          </ol>
        </Card>
      )}
    </div>
  );
}

function GeofencesModal({ collaboratorId, collaborator, allCollaborators = [], onClose }) {
  const [fences, setFences] = useState([]);
  const [mode, setMode] = useState("list"); // list | new | edit
  const [editing, setEditing] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [flash, setFlash] = useState("");
  const [loading, setLoading] = useState(true);
  const [duplicateOpen, setDuplicateOpen] = useState(null); // fence id sendo duplicada
  const [dupTargets, setDupTargets] = useState({});         // {cid: bool}
  const [dupBusy, setDupBusy] = useState(false);

  async function reload() {
    setLoading(true);
    try { setFences(await api.listGeofences(collaboratorId)); } finally { setLoading(false); }
  }
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [collaboratorId]);

  async function handleCreate(payload) {
    await api.createGeofence(collaboratorId, payload);
    setMode("list");
    setFlash("✅ Cerca adicionada.");
    setTimeout(() => setFlash(""), 2500);
    await reload();
  }
  async function handleUpdate(payload) {
    await api.updateGeofence(editing.id, payload);
    setMode("list"); setEditing(null);
    setFlash("✅ Cerca atualizada.");
    setTimeout(() => setFlash(""), 2500);
    await reload();
  }
  async function confirmRemove(id) {
    setBusyId(id);
    try {
      await api.deleteGeofence(id);
      setFlash("✅ Cerca removida.");
      setTimeout(() => setFlash(""), 2500);
    } catch (e) {
      setFlash("❌ Erro: " + (e?.response?.data?.detail || e.message));
      setTimeout(() => setFlash(""), 4000);
    }
    setBusyId(null); setConfirmId(null);
    await reload();
  }

  // ESC fecha o modal
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function openDuplicate(fenceId) {
    setDuplicateOpen(fenceId);
    setDupTargets({});
  }
  function toggleTarget(cid) {
    setDupTargets((prev) => ({ ...prev, [cid]: !prev[cid] }));
  }
  async function confirmDuplicate() {
    const targets = Object.keys(dupTargets).filter((k) => dupTargets[k]);
    if (!targets.length) {
      setFlash("❌ Selecione pelo menos 1 colaborador.");
      setTimeout(() => setFlash(""), 3000);
      return;
    }
    setDupBusy(true);
    try {
      const r = await api.duplicateGeofence(duplicateOpen, targets);
      const created = r.created?.length || 0;
      const skipped = r.skipped?.length || 0;
      setFlash(`✅ Duplicada para ${created} colaborador(es)${skipped ? ` · ${skipped} ignorado(s) (já tinham)` : ""}.`);
      setTimeout(() => setFlash(""), 3500);
      setDuplicateOpen(null);
      setDupTargets({});
    } catch (e) {
      setFlash("❌ Erro: " + (e?.response?.data?.detail || e.message));
      setTimeout(() => setFlash(""), 4000);
    }
    setDupBusy(false);
  }

  const otherCollabs = (allCollaborators || []).filter((c) => c.id !== collaboratorId);

  const title = collaborator
    ? `Cercas de ${collaborator.name}`
    : "Cercas individuais";

  return (
    <div
      data-testid="geofences-modal"
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(2px)",
        display: "grid", placeItems: "center", zIndex: 1000, padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "white", borderRadius: 18,
          width: "min(96vw, 920px)", maxHeight: "92vh", overflow: "auto",
          padding: 0, boxShadow: "0 30px 80px rgba(0,0,0,0.4)",
        }}
      >
        {/* Header */}
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "14px 18px", borderBottom: "1px solid #e2e8f0", position: "sticky", top: 0, background: "white", zIndex: 5,
        }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 17 }}>{title}</h3>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
              {fences.length} cerca(s) ativa(s) · isolado por colaborador
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {mode === "list" && (
              <Button onClick={() => setMode("new")} data-testid="add-fence-map-btn">
                <Icon name="plus" /> Nova cerca
              </Button>
            )}
            <button data-testid="close-fences-modal" onClick={onClose}
                    style={{ border: 0, background: "#f1f5f9", padding: "8px 14px", borderRadius: 10, cursor: "pointer", fontWeight: 800 }}>
              Fechar (ESC)
            </button>
          </div>
        </div>

        <div style={{ padding: 18 }}>
          {flash && (
            <div data-testid="fence-flash" style={{ background: flash.startsWith("✅") ? "#dcfce7" : "#fee2e2", color: flash.startsWith("✅") ? "#166534" : "#991b1b", padding: 10, borderRadius: 12, marginBottom: 12, fontWeight: 700 }}>
              {flash}
            </div>
          )}

          {mode === "new" && (
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 14, padding: 14 }}>
              <h4 style={{ margin: "0 0 10px", fontSize: 14, color: "#334155" }}>Nova cerca — escolha endereço ou clique no mapa</h4>
              <GeofenceMap
                onSubmit={handleCreate}
                onCancel={() => setMode("list")}
                submitLabel="Adicionar cerca"
              />
            </div>
          )}

          {mode === "edit" && editing && (
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 14, padding: 14 }}>
              <h4 style={{ margin: "0 0 10px", fontSize: 14, color: "#334155" }}>Editar cerca: {editing.name}</h4>
              <GeofenceMap
                initial={editing}
                onSubmit={handleUpdate}
                onCancel={() => { setMode("list"); setEditing(null); }}
                submitLabel="Salvar alterações"
              />
            </div>
          )}

          {mode === "list" && (
            <>
              {loading && <div style={{ color: "#64748b", padding: 12 }}>Carregando…</div>}
              {!loading && fences.length === 0 && (
                <div style={{ background: "#fffbeb", border: "1px dashed #fde68a", color: "#92400e", padding: 18, borderRadius: 14, textAlign: "center" }}>
                  Nenhuma cerca para <strong>{collaborator?.name}</strong>. Clique em <strong>“+ Nova cerca”</strong> para adicionar — múltiplas permitidas.
                </div>
              )}
              {!loading && fences.map((f) => (
                <div key={f.id} data-testid={`fence-row-${f.id}`} style={{ padding: "12px 0", borderBottom: "1px solid #f1f5f9" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <strong>{f.name}</strong>{" "}
                      <StatusBadge status={f.type === "Cliente" ? "Pendente" : f.type === "Loja" ? "Regular" : "Aprovado"}>{f.type}</StatusBadge>
                      <div style={{ color: "#64748b", fontSize: 12, marginTop: 2 }}>{f.address}</div>
                      <div style={{ color: "#94a3b8", fontSize: 11, marginTop: 1 }}>
                        <Icon name="map" /> {Number(f.lat).toFixed(5)}, {Number(f.lng).toFixed(5)} • raio <strong>{f.radius}m</strong>
                        {f.duplicated_from && <> · <span style={{ color: "#0ea5e9", fontWeight: 700 }}>cópia</span></>}
                      </div>
                    </div>
                    {confirmId === f.id ? (
                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <span style={{ fontSize: 12, color: "#be123c", fontWeight: 700 }}>Confirmar?</span>
                        <Button variant="danger" onClick={() => confirmRemove(f.id)} disabled={busyId === f.id} data-testid={`confirm-rm-fence-${f.id}`}>
                          {busyId === f.id ? "..." : "Sim, remover"}
                        </Button>
                        <Button variant="secondary" onClick={() => setConfirmId(null)}>Cancelar</Button>
                      </div>
                    ) : (
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <Button
                          variant="soft"
                          onClick={() => openDuplicate(f.id)}
                          disabled={otherCollabs.length === 0}
                          title={otherCollabs.length === 0 ? "Cadastre outros colaboradores para duplicar" : "Clonar esta cerca para outros colaboradores"}
                          data-testid={`dup-fence-${f.id}`}
                        >
                          Duplicar para…
                        </Button>
                        <Button variant="secondary" onClick={() => { setEditing(f); setMode("edit"); }} data-testid={`edit-fence-${f.id}`}>Editar</Button>
                        <Button variant="danger" onClick={() => setConfirmId(f.id)} data-testid={`rm-fence-${f.id}`}><Icon name="trash" /></Button>
                      </div>
                    )}
                  </div>

                  {duplicateOpen === f.id && (
                    <div data-testid={`dup-panel-${f.id}`} style={{
                      marginTop: 10, background: "#f0f9ff", border: "1px solid #bae6fd",
                      borderRadius: 12, padding: 12,
                    }}>
                      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, color: "#075985" }}>
                        Selecione colaboradores que receberão uma cópia de “<strong>{f.name}</strong>”:
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 6, marginBottom: 10, maxHeight: 220, overflowY: "auto" }}>
                        {otherCollabs.length === 0 && (
                          <div style={{ fontSize: 12, color: "#64748b" }}>
                            Não há outros colaboradores cadastrados.
                          </div>
                        )}
                        {otherCollabs.map((c) => (
                          <label
                            key={c.id}
                            data-testid={`dup-target-${c.id}`}
                            style={{
                              display: "flex", alignItems: "center", gap: 8,
                              background: "white", border: "1px solid #e2e8f0",
                              borderRadius: 10, padding: "6px 10px", fontSize: 13, cursor: "pointer",
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={!!dupTargets[c.id]}
                              onChange={() => toggleTarget(c.id)}
                              data-testid={`dup-check-${c.id}`}
                            />
                            <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</span>
                          </label>
                        ))}
                      </div>
                      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                        <Button variant="secondary" onClick={() => { setDuplicateOpen(null); setDupTargets({}); }}>
                          Cancelar
                        </Button>
                        <Button
                          variant="primary"
                          onClick={confirmDuplicate}
                          disabled={dupBusy || Object.values(dupTargets).filter(Boolean).length === 0}
                          data-testid={`confirm-dup-${f.id}`}
                        >
                          {dupBusy ? "Duplicando..." : `Duplicar para ${Object.values(dupTargets).filter(Boolean).length} colaborador(es)`}
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}


function ClockHistoryModal({ collaborator, onClose }) {
  const [records, setRecords] = useState(null);
  const [days, setDays] = useState(7);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    setRecords(null); setErr("");
    const dt = new Date();
    const dateTo = dt.toISOString().slice(0, 10);
    dt.setDate(dt.getDate() - (days - 1));
    const dateFrom = dt.toISOString().slice(0, 10);
    api.listClockRecords({ collaborator_id: collaborator.id, date_from: dateFrom, date_to: dateTo })
      .then((r) => { if (alive) setRecords(r || []); })
      .catch((e) => { if (alive) setErr(e?.response?.data?.detail || e.message); });
    return () => { alive = false; };
  }, [collaborator.id, days]);

  // Agrupa por dia
  const byDate = {};
  for (const r of (records || [])) {
    (byDate[r.date] = byDate[r.date] || []).push(r);
  }
  const sortedDates = Object.keys(byDate).sort().reverse();

  const typeIcon = {
    "Entrada": "",
    "Início intervalo": "️",
    "Fim intervalo": "",
    "Saída": "",
  };

  return (
    <div data-testid="clock-history-modal" onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.55)",
      display: "grid", placeItems: "center", zIndex: 1000, padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 16, padding: 20, maxWidth: 640, width: "100%",
        maxHeight: "85vh", overflow: "auto", boxShadow: "0 20px 60px rgba(15,23,42,.3)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Pontos de {collaborator.name}</h3>
          <button data-testid="close-clock-history" onClick={onClose} style={{
            border: 0, background: "#f1f5f9", borderRadius: 999, width: 32, height: 32,
            cursor: "pointer", fontSize: 16,
          }}>✕</button>
        </div>

        <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              data-testid={`clock-history-days-${d}`}
              onClick={() => setDays(d)}
              style={{
                padding: "6px 12px", borderRadius: 999, fontSize: 12, fontWeight: 700,
                border: `1px solid ${days === d ? "#0ea5e9" : "#cbd5e1"}`,
                background: days === d ? "#0ea5e9" : "white",
                color: days === d ? "white" : "#475569", cursor: "pointer",
              }}
            >Últimos {d}d</button>
          ))}
        </div>

        {err && <div style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 8 }}>{err}</div>}
        {records === null && !err && <div style={{ color: "#94a3b8", padding: 16, textAlign: "center" }}>Carregando…</div>}
        {records !== null && records.length === 0 && (
          <div style={{ background: "#f8fafc", border: "1px dashed #cbd5e1", borderRadius: 12, padding: 24, textAlign: "center", color: "#94a3b8" }}>
            Nenhum batimento de ponto nos últimos {days} dia(s).
          </div>
        )}

        {sortedDates.map((d) => (
          <div key={d} data-testid={`clock-day-${d}`} style={{
            background: "#f8fafc", borderRadius: 12, padding: 12, marginBottom: 8,
            border: "1px solid #e2e8f0",
          }}>
            <div style={{ fontWeight: 700, marginBottom: 8, color: "#0f172a", fontSize: 13 }}>
              {new Date(d + "T12:00:00").toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" })}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {byDate[d].sort((a, b) => a.time.localeCompare(b.time)).map((r) => (
                <div key={r.id} data-testid={`clock-rec-${r.id}`} style={{
                  display: "flex", alignItems: "center", gap: 10,
                  background: "white", padding: "8px 12px", borderRadius: 10,
                  border: `1px solid ${r.status === "Válido" || r.status === "Offline sincronizado" ? "#bbf7d0" : "#fecaca"}`,
                }}>
                  <span style={{ fontSize: 20 }}>{typeIcon[r.type] || "•"}</span>
                  <div style={{ flex: 1 }}>
                    <strong style={{ fontSize: 13 }}>{r.type}</strong>
                    <div style={{ fontSize: 11, color: "#64748b" }}>
                      {r.time}{r.address ? ` · ${r.address}` : ""}
                    </div>
                  </div>
                  <span style={{
                    fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999,
                    background: r.status === "Válido" || r.status === "Offline sincronizado" ? "#dcfce7" : "#fee2e2",
                    color: r.status === "Válido" || r.status === "Offline sincronizado" ? "#166534" : "#991b1b",
                  }}>{r.status}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


function CollabShareLink({ collaborator }) {
  const [copied, setCopied] = useState(false);
  const url = (() => {
    if (typeof window === "undefined") return "";
    return `${window.location.origin}/?cid=${collaborator.id}`;
  })();
  const phoneClean = (collaborator.phone || "").replace(/\D/g, "");
  const waMsg = encodeURIComponent(
    `Olá, ${collaborator.name?.split(" ")[0] || ""}! Acesse o app de serviço pelo link abaixo:\n${url}`
  );
  const waUrl = phoneClean
    ? `https://wa.me/${phoneClean.length <= 11 ? "55" + phoneClean : phoneClean}?text=${waMsg}`
    : null;

  async function copy() {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
      } else {
        const ta = document.createElement("textarea");
        ta.value = url; document.body.appendChild(ta); ta.select();
        document.execCommand("copy"); document.body.removeChild(ta);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2200);
    } catch (e) {
      await window.prompt("Copie o link manualmente:", url);
    }
  }

  return (
    <div data-testid={`collab-share-link-${collaborator.id}`} style={{
      marginTop: 8, padding: 8,
      background: copied ? "#dcfce7" : "#f1f5f9",
      borderRadius: 10, border: `1px dashed ${copied ? "#86efac" : "#cbd5e1"}`,
      transition: "background-color .25s, border-color .25s",
    }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: "#475569", flexShrink: 0 }}>Link</span>
        <input
          data-testid={`collab-share-url-${collaborator.id}`}
          readOnly
          value={url}
          onFocus={(e) => e.target.select()}
          title="Link único deste técnico — abrir no celular dele já entra no app com o usuário certo"
          style={{
            flex: 1, minWidth: 0, fontSize: 11, fontFamily: "ui-monospace,SFMono-Regular,monospace",
            padding: "6px 8px", border: "1px solid #e2e8f0", borderRadius: 8,
            background: "white", color: "#0f172a",
          }}
        />
        <button
          data-testid={`collab-share-copy-${collaborator.id}`}
          onClick={copy}
          title="Copiar link"
          style={{
            border: 0, padding: "6px 10px", borderRadius: 8, fontSize: 11, fontWeight: 800,
            cursor: "pointer", flexShrink: 0,
            background: copied ? "#10b981" : "#0ea5e9", color: "white",
            boxShadow: "0 2px 4px rgba(15,23,42,.1)",
          }}
        >
          {copied ? "✓ Copiado!" : "Copiar"}
        </button>
        {waUrl && (
          <a
            data-testid={`collab-share-whatsapp-${collaborator.id}`}
            href={waUrl}
            target="_blank"
            rel="noopener noreferrer"
            title={`Enviar pelo WhatsApp para ${collaborator.phone}`}
            style={{
              padding: "6px 10px", borderRadius: 8, fontSize: 11, fontWeight: 800,
              background: "#25D366", color: "white", textDecoration: "none", flexShrink: 0,
              boxShadow: "0 2px 4px rgba(15,23,42,.1)",
            }}
          >
            WhatsApp
          </a>
        )}
        <GrantMobileAccessButton collaborator={collaborator} />
      </div>
      <div style={{ fontSize: 10, color: "#64748b", marginTop: 4, paddingLeft: 2 }}>
        Abre o app de serviço já com {collaborator.name?.split(" ")[0] || "o técnico"} selecionado.
      </div>
    </div>
  );
}


/* =============================================================
   AvatarUploader — sobe a foto do crachá (foto_id) do colaborador.
   Mesma imagem é replicada pelo backend pra:
     - collaborators.avatar_data_url (usado no chat, lousa, ranking)
     - collaborators.foto_id          (foto do crachá)
     - users.avatar_url               (mesma pessoa logada)
============================================================= */
function AvatarUploader({ collaboratorId, currentUrl, name, onUpdated }) {
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [zoomOpen, setZoomOpen] = useState(false);
  const [cropImage, setCropImage] = useState(null);
  const initials = (name || "??").split(" ")
    .slice(0, 2).map((s) => s[0]).join("").toUpperCase();
  const fileRef = useRef(null);

  function pickFile() { fileRef.current?.click(); }

  async function handleFile(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (!/^image\//.test(f.type)) {
      setError("Apenas imagens (JPG/PNG/WebP).");
      return;
    }
    if (f.size > 6_000_000) {
      setError("Imagem maior que ~6MB. Reduza antes de subir.");
      return;
    }
    setError("");
    // Lê a imagem original e abre o cropper centralizado no rosto
    const reader = new FileReader();
    reader.onload = () => setCropImage(reader.result);
    reader.readAsDataURL(f);
  }

  async function saveCropped(dataUrl) {
    setCropImage(null);
    setPreview(dataUrl);
    setBusy(true);
    try {
      await api.uploadCollaboratorPhoto(collaboratorId, dataUrl);
      onUpdated && onUpdated(dataUrl);
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || "Erro ao subir.");
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  const shownSrc = preview || currentUrl;

  return (
    <div data-testid="avatar-uploader" style={{
      display: "flex", alignItems: "center", gap: 14,
      padding: 14, marginBottom: 14,
      background: "linear-gradient(135deg, rgba(99,102,241,.07), #f8fafc 70%)",
      border: "1px solid #e2e8f0", borderRadius: 12,
    }}>
      <div
        onDoubleClick={() => shownSrc && setZoomOpen(true)}
        title={shownSrc ? "Clique duas vezes para ampliar" : ""}
        style={{
          width: 88, height: 88, borderRadius: "50%",
          overflow: "hidden", flexShrink: 0,
          border: "3px solid #6366f1",
          boxShadow: "0 4px 12px rgba(99,102,241,.25)",
          background: shownSrc ? "transparent"
            : "linear-gradient(135deg, #6366f1, #8b5cf6)",
          color: "white", display: "grid", placeItems: "center",
          fontSize: 28, fontWeight: 800,
          cursor: shownSrc ? "zoom-in" : "default",
        }}>
        {shownSrc ? (
          <img src={shownSrc} alt={name}
               style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : initials}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 11, fontWeight: 800, color: "#64748b",
          textTransform: "uppercase", letterSpacing: ".05em",
        }}>
          Foto do crachá (foto_id)
        </div>
        <div style={{ fontSize: 13, color: "#0f172a", marginTop: 2 }}>
          {shownSrc ? "Foto cadastrada. Clique 2× no avatar para ampliar."
                          : "Sem foto. Suba a foto do crachá pra usar em todo o sistema."}
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
          <input ref={fileRef} type="file" accept="image/*"
                 onChange={handleFile}
                 data-testid="avatar-input"
                 style={{ display: "none" }} />
          <Button variant="primary" onClick={pickFile} disabled={busy}
                  data-testid="avatar-upload-btn">
            {busy ? "Enviando..." : (shownSrc ? "Trocar foto" : "Subir foto")}
          </Button>
          {shownSrc && (
            <Button variant="ghost" onClick={() => setZoomOpen(true)}
                    data-testid="avatar-zoom-btn">
              <Icon name="search" /> Ver grande
            </Button>
          )}
          <span style={{ fontSize: 10, color: "#94a3b8",
                          alignSelf: "center" }}>
            Centralize o rosto após escolher · ↑ qualidade
          </span>
        </div>
        {error && (
          <div style={{ marginTop: 6, fontSize: 11, color: "#dc2626",
                          fontWeight: 700 }}>
            {error}
          </div>
        )}
      </div>

      {zoomOpen && shownSrc && (
        <AvatarZoomModal src={shownSrc} alt={name}
                          caption={name}
                          onClose={() => setZoomOpen(false)} />
      )}
      {cropImage && (
        <FaceCropModal src={cropImage} name={name}
                          onCancel={() => setCropImage(null)}
                          onConfirm={saveCropped} />
      )}
    </div>
  );
}

/* =============================================================
   FaceCropModal — cropper circular pra centralizar no rosto.
   Tenta auto-detectar o rosto com FaceDetector API (Chrome/Edge);
   senão, usuário arrasta/zoom manual.
============================================================= */
function FaceCropModal({ src, name, onCancel, onConfirm }) {
  const canvasRef = useRef(null);
  const imgRef = useRef(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [imgSize, setImgSize] = useState({ w: 0, h: 0 });
  const [drag, setDrag] = useState(null);
  const [autoTried, setAutoTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const STAGE = 360;   // tamanho da área redonda visível
  const OUTPUT = 512;  // imagem final exportada (quadrada)

  useEffect(() => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = async () => {
      imgRef.current = img;
      setImgSize({ w: img.width, h: img.height });
      // Auto-detect facial (best effort)
      const hasFD = typeof window !== "undefined" && "FaceDetector" in window;
      if (hasFD && !autoTried) {
        try {
          const fd = new window.FaceDetector({ fastMode: true,
                                                  maxDetectedFaces: 1 });
          const faces = await fd.detect(img);
          if (faces?.[0]?.boundingBox) {
            const b = faces[0].boundingBox;
            const fcx = b.x + b.width / 2;
            const fcy = b.y + b.height / 2;
            // Calcula zoom pra rosto ocupar ~70% do crop
            const targetSize = Math.max(b.width, b.height) * 1.55;
            const z = STAGE / Math.min(img.width, img.height)
                       * (Math.min(img.width, img.height) / targetSize);
            setZoom(Math.max(0.5, Math.min(4, z)));
            // Offset pra centralizar o rosto na stage
            setOffset({
              x: (img.width / 2 - fcx) * z,
              y: (img.height / 2 - fcy) * z,
            });
          } else {
            initialFit(img);
          }
        } catch {
          initialFit(img);
        }
      } else {
        initialFit(img);
      }
      setAutoTried(true);
    };
    img.src = src;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);

  function initialFit(img) {
    const z = STAGE / Math.min(img.width, img.height);
    setZoom(z);
    setOffset({ x: 0, y: 0 });
  }

  useEffect(() => { draw(); /* eslint-disable-next-line */ }, [zoom, offset, imgSize]);

  function draw() {
    const c = canvasRef.current; if (!c) return;
    const img = imgRef.current; if (!img) return;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, STAGE, STAGE);
    // Fundo escuro
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, STAGE, STAGE);
    // Imagem
    const dw = img.width * zoom;
    const dh = img.height * zoom;
    const dx = (STAGE - dw) / 2 + offset.x;
    const dy = (STAGE - dh) / 2 + offset.y;
    ctx.drawImage(img, dx, dy, dw, dh);
    // Máscara redonda (escurece fora do círculo)
    ctx.save();
    ctx.fillStyle = "rgba(15,23,42,.65)";
    ctx.fillRect(0, 0, STAGE, STAGE);
    ctx.globalCompositeOperation = "destination-out";
    ctx.beginPath();
    ctx.arc(STAGE / 2, STAGE / 2, STAGE / 2 - 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    // Anel
    ctx.strokeStyle = "#6366f1";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(STAGE / 2, STAGE / 2, STAGE / 2 - 6, 0, Math.PI * 2);
    ctx.stroke();
  }

  function startDrag(e) {
    const evt = e.touches ? e.touches[0] : e;
    setDrag({ x: evt.clientX - offset.x, y: evt.clientY - offset.y });
  }
  function moveDrag(e) {
    if (!drag) return;
    const evt = e.touches ? e.touches[0] : e;
    setOffset({ x: evt.clientX - drag.x, y: evt.clientY - drag.y });
  }
  function endDrag() { setDrag(null); }

  function exportCrop() {
    const img = imgRef.current; if (!img) return;
    setBusy(true);
    // Exporta canvas redondo de OUTPUT×OUTPUT
    const out = document.createElement("canvas");
    out.width = OUTPUT; out.height = OUTPUT;
    const ctx = out.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, OUTPUT, OUTPUT);
    const scale = OUTPUT / STAGE;
    const dw = img.width * zoom * scale;
    const dh = img.height * zoom * scale;
    const dx = (OUTPUT - dw) / 2 + offset.x * scale;
    const dy = (OUTPUT - dh) / 2 + offset.y * scale;
    ctx.drawImage(img, dx, dy, dw, dh);
    const dataUrl = out.toDataURL("image/jpeg", 0.9);
    onConfirm(dataUrl);
    setBusy(false);
  }

  return (
    <div data-testid="face-crop-modal" style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.7)",
      zIndex: 1100, display: "grid", placeItems: "center", padding: 20,
    }} onClick={onCancel}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "#fff", borderRadius: 16, overflow: "hidden",
        width: 460, maxWidth: "94vw",
      }}>
        <div style={{ padding: "12px 20px", borderBottom: "1px solid #e2e8f0",
                          display: "flex", alignItems: "center" }}>
          <strong style={{ fontSize: 14 }}>Ajustar foto — {name}</strong>
          <span style={{ flex: 1 }} />
          <button onClick={onCancel} style={{ background: "transparent",
                       border: "none", cursor: "pointer", fontSize: 20,
                       color: "#64748b" }}>×</button>
        </div>
        <div style={{ padding: 16, display: "grid", placeItems: "center",
                          gap: 12 }}>
          <canvas ref={canvasRef} width={STAGE} height={STAGE}
                  onMouseDown={startDrag} onMouseMove={moveDrag}
                  onMouseUp={endDrag} onMouseLeave={endDrag}
                  onTouchStart={startDrag} onTouchMove={moveDrag}
                  onTouchEnd={endDrag}
                  data-testid="crop-canvas"
                  style={{ width: STAGE, height: STAGE, borderRadius: 12,
                            cursor: drag ? "grabbing" : "grab",
                            touchAction: "none" }} />
          <div style={{ display: "flex", alignItems: "center", gap: 8,
                          width: "100%", fontSize: 11, color: "#64748b" }}>
            <span>Zoom</span>
            <input type="range" min={0.2} max={4} step={0.05} value={zoom}
                   onChange={(e) => setZoom(parseFloat(e.target.value))}
                   data-testid="crop-zoom"
                   style={{ flex: 1 }} />
            <span style={{ width: 30, textAlign: "right" }}>
              {Math.round(zoom * 100)}%
            </span>
          </div>
          <div style={{ fontSize: 11, color: "#94a3b8", textAlign: "center" }}>
            Arraste o rosto para centralizar dentro do círculo
            {imgSize.w > 0 && autoTried &&
              " · Detecção automática do rosto aplicada quando possível"}
          </div>
        </div>
        <div style={{ padding: 12, borderTop: "1px solid #e2e8f0",
                          display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onCancel}>Cancelar</Button>
          <Button variant="primary" onClick={exportCrop} disabled={busy}
                  data-testid="crop-confirm">
            {busy ? "Salvando..." : "Salvar foto"}
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * Redimensiona imagem antes do upload pra evitar payloads gigantes.
 * Retorna dataURL JPEG. Mantém aspect-ratio. Lado maior = `maxSize`.
 */
async function resizeImageToDataUrl(file, maxSize = 512, quality = 0.85) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const ratio = Math.min(maxSize / img.width, maxSize / img.height, 1);
        const w = Math.round(img.width * ratio);
        const h = Math.round(img.height * ratio);
        const canvas = document.createElement("canvas");
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", quality));
      };
      img.onerror = reject;
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}


// ============================================================================
// GrantMobileAccessButton — botão "Cadastrar acesso mobile" ao lado do link
// único. Cria/reseta o User vinculado ao Collaborator com senha aleatória,
// abre modal pra copiar credenciais + botão pré-formatado pra enviar via
// WhatsApp do gestor.
// ============================================================================
function GrantMobileAccessButton({ collaborator }) {
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [copied, setCopied] = React.useState(false);

  const onClick = async () => {
    if (busy) return;
    const has = !!collaborator?.has_mobile_access;
    const msg = has
      ? `Resetar a senha do acesso mobile de ${collaborator?.name || "este técnico"}? A senha anterior deixará de funcionar.`
      : `Criar acesso mobile (email + senha) para ${collaborator?.name || "este técnico"}?`;
    if (!await window.confirm(msg)) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.collabGrantMobileAccess(collaborator.id);
      setResult(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const close = () => { setResult(null); setCopied(false); };

  const copyAll = async () => {
    if (!result) return;
    const txt = `Olá ${collaborator?.name?.split(" ")[0] || ""}! Seu acesso ao app de serviço:\n\nE-mail: ${result.email}\nSenha: ${result.password}\n\nAbra o app no celular e entre com esses dados.`;
    try {
      await navigator.clipboard.writeText(txt);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch { /* ignora */ }
  };

  const phoneDigits = String(collaborator?.phone || "").replace(/\D/g, "");
  const waMsg = result
    ? encodeURIComponent(
        `Olá ${collaborator?.name?.split(" ")[0] || ""}! Seu acesso ao app de serviço:\n\nE-mail: ${result.email}\nSenha: ${result.password}\n\nAbra o app no celular e entre com esses dados.`,
      )
    : "";
  const waUrl = phoneDigits && result
    ? `https://wa.me/${phoneDigits}?text=${waMsg}`
    : null;

  const has = !!collaborator?.has_mobile_access;

  return (
    <>
      <button
        data-testid={`collab-grant-mobile-${collaborator.id}`}
        onClick={onClick}
        disabled={busy}
        title={has ? "Resetar senha do app mobile" : "Cadastrar acesso (e-mail/senha) para o app mobile"}
        style={{
          padding: "6px 10px", borderRadius: 8, fontSize: 11, fontWeight: 800,
          background: has ? "#7c3aed" : "#0f172a",
          color: "white", border: 0, cursor: busy ? "wait" : "pointer", flexShrink: 0,
          boxShadow: "0 2px 4px rgba(15,23,42,.1)",
        }}
      >
        {busy ? "..." : (has ? "Resetar" : "Cadastrar acesso")}
      </button>

      {err && (
        <div style={{
          position: "fixed", top: 20, right: 20, zIndex: 9999,
          background: "#fef2f2", color: "#991b1b", padding: 12,
          borderRadius: 8, fontSize: 12, fontWeight: 700,
          boxShadow: "0 4px 12px rgba(0,0,0,.15)",
          maxWidth: 320,
        }} onClick={() => setErr(null)}>
          ️ {err}
        </div>
      )}

      {result && (
        <div data-testid="grant-mobile-modal" style={{
          position: "fixed", inset: 0, background: "rgba(15,23,42,.6)",
          display: "grid", placeItems: "center", zIndex: 9999, padding: 20,
        }} onClick={close}>
          <div onClick={(e) => e.stopPropagation()} style={{
            background: "white", borderRadius: 14, padding: 24,
            maxWidth: 460, width: "100%",
            boxShadow: "0 20px 60px rgba(0,0,0,.3)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10,
                           marginBottom: 14 }}>
              <div style={{
                width: 40, height: 40, borderRadius: 10,
                background: result.action === "created" ? "#10b981" : "#7c3aed",
                display: "grid", placeItems: "center", color: "white",
                fontSize: 18, fontWeight: 800,
              }}>
                {result.action === "created" ? "✓" : "↻"}
              </div>
              <div>
                <div style={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>
                  {result.action === "created"
                    ? "Acesso mobile criado"
                    : "Senha resetada"}
                </div>
                <div style={{ fontSize: 11, color: "#64748b" }}>
                  {result.collaborator_name}
                </div>
              </div>
            </div>

            <div style={{
              background: "#f8fafc", border: "1px solid #e2e8f0",
              borderRadius: 10, padding: 14, marginBottom: 14,
              fontFamily: "ui-monospace,SFMono-Regular,monospace",
            }}>
              <div style={{ fontSize: 10, color: "#64748b",
                             textTransform: "uppercase", letterSpacing: ".06em",
                             marginBottom: 4 }}>E-mail</div>
              <div data-testid="grant-mobile-email" style={{
                fontSize: 13, color: "#0f172a", fontWeight: 700,
                userSelect: "all", marginBottom: 10,
              }}>{result.email}</div>
              <div style={{ fontSize: 10, color: "#64748b",
                             textTransform: "uppercase", letterSpacing: ".06em",
                             marginBottom: 4 }}>Senha temporária</div>
              <div data-testid="grant-mobile-password" style={{
                fontSize: 16, color: "#dc2626", fontWeight: 800,
                userSelect: "all", letterSpacing: ".05em",
              }}>{result.password}</div>
            </div>

            <div style={{
              background: "#fffbeb", border: "1px solid #fde68a",
              borderRadius: 8, padding: 10, fontSize: 11, color: "#78350f",
              marginBottom: 14, lineHeight: 1.5,
            }}>
              ️ Anote ou envie agora — por segurança, a senha não é exibida novamente.
              O técnico pode alterar depois do primeiro login.
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button onClick={copyAll}
                      data-testid="grant-mobile-copy"
                      style={{
                        flex: 1, padding: "10px 14px", borderRadius: 8,
                        background: copied ? "#10b981" : "#0ea5e9",
                        color: "white", border: 0,
                        fontSize: 13, fontWeight: 700, cursor: "pointer",
                      }}>
                {copied ? "✓ Copiado!" : "Copiar credenciais"}
              </button>
              {waUrl && (
                <a href={waUrl} target="_blank" rel="noopener noreferrer"
                   data-testid="grant-mobile-whatsapp"
                   style={{
                     flex: 1, padding: "10px 14px", borderRadius: 8,
                     background: "#25D366", color: "white",
                     fontSize: 13, fontWeight: 700, textAlign: "center",
                     textDecoration: "none",
                   }}>
                  Enviar pelo WhatsApp
                </a>
              )}
            </div>
            <button onClick={close}
                    data-testid="grant-mobile-close"
                    style={{
                      width: "100%", marginTop: 10, padding: "8px 14px",
                      background: "transparent", color: "#64748b",
                      border: "1px solid #e2e8f0", borderRadius: 8,
                      fontSize: 12, fontWeight: 600, cursor: "pointer",
                    }}>
              Fechar
            </button>
          </div>
        </div>
      )}
    </>
  );
}

