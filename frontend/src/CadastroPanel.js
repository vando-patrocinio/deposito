import React, { useEffect, useState } from "react";
import { Car } from "lucide-react";
import { api } from "@/api";
import { AvatarZoomModal, Button, Card, Field, Icon, inputStyle, Row, StatusBadge } from "@/ui";
import GeofenceMap from "@/GeofenceMap";
import useEventStream from "@/useEventStream";
import AssetsSection from "@/AssetsSection";
import DeactivationAssetsModal from "@/DeactivationAssetsModal";
import VehicleChecklistModal from "@/VehicleChecklistModal";

const EMPTY = {
  name: "",
  cpf: "",
  email: "",
  phone: "",
  role: "Colaborador de Campo",
  praca_id: "",
  praca_ids_extra: [],
  pis: "",
  admitted_at: "",
  matricula: "",
  schedule: { entrada: "08:00", inicio_intervalo: "12:00", fim_intervalo: "13:00", saida: "17:00" },
  overtime_policy: { mode: "banco", hourly_rate_brl: 0, weekday_multiplier: 1.5, sunday_multiplier: 2.0 },
  is_test_mode: false,
  clock_in_enabled: true,  // CLT bate ponto. False = freelancer/MEI: app vai direto pra Lousa
  active: true,  // false = colaborador desligado/inativo
};

export default function CadastroPanel() {
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
    if (!window.confirm(msg)) return;
    setTogglingId(c.id);
    try {
      // PUT exige payload completo do CollaboratorIn — preserva todos os campos atuais
      await api.updateCollaborator(c.id, {
        name: c.name, cpf: c.cpf, email: c.email, phone: c.phone,
        role: c.role, company: c.company,
        schedule: c.schedule, overtime_policy: c.overtime_policy,
        city: c.city ?? null, state: c.state ?? null, praca_id: c.praca_id ?? null,
        is_test_mode: !!c.is_test_mode,
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
        setAtlazFlash(`👷 ${data.created_count} novo(s) técnico(s) sincronizado(s) do Atlaz`);
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
          {list.map((c) => (
            <div
              key={c.id}
              data-testid={`collab-card-${c.id}`}
              style={{
                background: "white",
                border: "1px solid #e2e8f0",
                borderRadius: 16,
                padding: 14,
                marginBottom: 10,
                boxShadow: "0 2px 6px rgba(15,23,42,.04)",
              }}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                <button
                  type="button"
                  onClick={() => { if (c.avatar_data_url) { setZoomSrc(c.avatar_data_url); setZoomCaption(c.name); } }}
                  disabled={!c.avatar_data_url}
                  title={c.avatar_data_url ? "Clique para ampliar" : "Sem foto cadastrada"}
                  data-testid={`avatar-${c.id}`}
                  style={{
                    width: 56, height: 56, borderRadius: "50%", overflow: "hidden",
                    background: "linear-gradient(135deg,#e2e8f0,#cbd5e1)",
                    display: "grid", placeItems: "center", fontSize: 22,
                    border: "2px solid white", boxShadow: "0 4px 12px rgba(15,23,42,.08)",
                    padding: 0, flexShrink: 0,
                    cursor: c.avatar_data_url ? "zoom-in" : "default",
                  }}
                >
                  {c.avatar_data_url ? <img src={c.avatar_data_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <Icon name="user" />}
                </button>

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <strong style={{ fontSize: 15 }}>{c.name}</strong>
                    {!c.avatar_data_url && (
                      <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#fef3c7", color: "#92400e", border: "1px solid #fde68a" }}>
                        sem avatar facial
                      </span>
                    )}
                    {c.device_id && (
                      <span title={`Vinculado a: ${c.google_email || "(Google)"}`} style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>
                        📱 dispositivo vinculado
                      </span>
                    )}
                    {!c.device_id && c.email && (
                      <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#e0f2fe", color: "#075985", border: "1px solid #bae6fd" }}>
                        aguardando 1º login Google
                      </span>
                    )}
                    {c.is_test_mode && (
                      <span title="Modo teste — bate ponto em qualquer local com qualquer selfie" style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#f0fdfa", color: "#0d9488", border: "1px solid #5eead4" }}>
                        🧪 MODO TESTE
                      </span>
                    )}
                    {c.clock_in_enabled === false && (
                      <span title="Colaborador externo — app abre direto na Lousa, sem registro de ponto" style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#fff7ed", color: "#9a3412", border: "1px solid #fdba74" }}>
                        🚫 NÃO BATE PONTO
                      </span>
                    )}
                  </div>
                  <div style={{ color: "#64748b", fontSize: 12, marginTop: 2 }}>
                    {c.role}{(() => {
                      const p = pracas.find((x) => x.id === c.praca_id);
                      return p ? ` · ${p.city}/${p.state}` : c.company ? ` · ${c.company}` : "";
                    })()}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px", marginTop: 6, fontSize: 12, color: "#475569" }}>
                    <span><span style={{ color: "#94a3b8" }}>CPF</span>&nbsp;{c.cpf}</span>
                    <span><span style={{ color: "#94a3b8" }}>E-mail</span>&nbsp;{c.email}</span>
                    <span><span style={{ color: "#94a3b8" }}>Tel</span>&nbsp;{c.phone}</span>
                  </div>

                  <CollabShareLink collaborator={c} />
                </div>
              </div>

              <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #f1f5f9", display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                {confirmDelete === c.id ? (
                  <>
                    <span style={{ alignSelf: "center", marginRight: "auto", fontSize: 12, color: "#be123c", fontWeight: 700 }}>Apagar tudo? Não dá pra desfazer.</span>
                    <Button variant="secondary" onClick={() => setConfirmDelete(null)}>Cancelar</Button>
                    <Button variant="danger" onClick={() => remove(c.id)} disabled={deletingId === c.id} data-testid={`confirm-del-${c.id}`}>
                      {deletingId === c.id ? "..." : "Sim, excluir"}
                    </Button>
                  </>
                ) : confirmReset === c.id ? (
                  <>
                    <span style={{ alignSelf: "center", marginRight: "auto", fontSize: 12, color: "#92400e", fontWeight: 700 }}>
                      Resetar avatar e dispositivo? O colaborador precisará entrar com Google novamente.
                    </span>
                    <Button variant="secondary" onClick={() => setConfirmReset(null)}>Cancelar</Button>
                    <Button variant="danger" onClick={() => resetFace(c)} disabled={resettingId === c.id} data-testid={`confirm-reset-${c.id}`}>
                      {resettingId === c.id ? "..." : "Sim, resetar"}
                    </Button>
                  </>
                ) : (
                  <>
                    {c.clock_in_enabled !== false ? (
                      <Button variant="soft" onClick={() => setSelectedId(c.id)} data-testid={`fences-${c.id}`}>
                        <Icon name="map" /> Cercas
                        {(() => {
                          const indiv = fenceCounts[c.id] ?? 0;
                          const hasPraca = c.praca_id && c.praca_id !== "NOTA";
                          const total = indiv + (hasPraca ? 1 : 0);
                          const title = hasPraca
                            ? `${indiv} cerca(s) individual(is) + 1 praça vinculada`
                            : `${indiv} cerca(s) individual(is)`;
                          return (
                            <span title={title} data-testid={`fence-count-${c.id}`} style={{ marginLeft: 6, background: total ? "#0ea5e9" : "#94a3b8", color: "white", borderRadius: 999, padding: "1px 7px", fontSize: 10, fontWeight: 900 }}>
                              {total}
                            </span>
                          );
                        })()}
                      </Button>
                    ) : (
                      <span
                        data-testid={`fences-disabled-${c.id}`}
                        title="Colaborador externo (não-CLT) — cercas não se aplicam, validação de localização e selfie estão desativadas"
                        style={{
                          fontSize: 11, fontWeight: 700, color: "#9a3412",
                          background: "#fff7ed", border: "1px dashed #fdba74",
                          padding: "6px 12px", borderRadius: 999,
                        }}
                      >
                        🚫 Cerca não se aplica
                      </span>
                    )}
                    <Button
                      variant="soft"
                      onClick={() => setConfirmReset(c.id)}
                      disabled={!c.avatar_data_url}
                      title={c.avatar_data_url ? "Remove a foto de referência — próxima selfie válida vira o novo avatar" : "Colaborador ainda não tem avatar"}
                      data-testid={`reset-face-${c.id}`}
                    >
                      <Icon name="camera" /> Resetar avatar e dispositivo
                    </Button>
                    <Button
                      variant="soft"
                      onClick={() => toggleClockInEnabled(c)}
                      disabled={togglingId === c.id}
                      data-testid={`toggle-clock-${c.id}`}
                      title={c.clock_in_enabled !== false
                        ? "Clique para desativar — colaborador não vai mais bater ponto, app abre direto na Lousa"
                        : "Clique para ativar — colaborador volta a bater ponto e a tela home padrão"}
                      style={{
                        background: c.clock_in_enabled !== false ? "#ecfeff" : "#fff7ed",
                        color: c.clock_in_enabled !== false ? "#0e7490" : "#9a3412",
                        border: `1px solid ${c.clock_in_enabled !== false ? "#67e8f9" : "#fdba74"}`,
                        fontWeight: 700,
                      }}
                    >
                      {togglingId === c.id
                        ? "..."
                        : c.clock_in_enabled !== false ? "🕐 Bate ponto: ON" : "🚫 Bate ponto: OFF"}
                    </Button>
                    {c.clock_in_enabled !== false && (
                      <Button
                        variant="soft"
                        onClick={() => setClockHistoryFor(c)}
                        data-testid={`view-clock-${c.id}`}
                        title="Ver batimentos de ponto deste colaborador"
                        style={{ background: "#ecfdf5", color: "#065f46", border: "1px solid #6ee7b7" }}
                      >
                        🕐 Pontos
                      </Button>
                    )}
                    <Button
                      variant="soft"
                      onClick={() => setAssetsFor(c)}
                      data-testid={`view-assets-${c.id}`}
                      title="Itens em custódia (Checklist EPIs)"
                      style={{ background: "var(--accent-soft)", color: "var(--accent-soft-fg)", border: "1px solid #99f6e4" }}
                    >
                      <Icon name="clipboard" /> Checklist
                    </Button>
                    <Button
                      variant="soft"
                      onClick={() => setVehicleChecklistFor(c)}
                      data-testid={`view-vehicle-${c.id}`}
                      title="Checklist veicular pré-jornada (CONTRAN)"
                      style={{ background: "#eff6ff", color: "#1e40af", border: "1px solid #bfdbfe" }}
                    >
                      <Car size={14} strokeWidth={1.75} /> Veicular
                    </Button>
                    <Button variant="secondary" onClick={() => startEdit(c)} data-testid={`edit-${c.id}`}>
                      <Icon name="gear" /> Editar
                    </Button>
                    <Button variant="danger" onClick={() => setConfirmDelete(c.id)} data-testid={`del-${c.id}`} title="Excluir colaborador">
                      <Icon name="trash" />
                    </Button>
                  </>
                )}
              </div>
            </div>
          ))}
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
          <Field label="Cargo">
            <input style={inputStyle} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} />
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
                <option value="NOTA">📍 Endereço da Nota (cerca dinâmica)</option>
                {pracas.map((p) => (
                  <option key={p.id} value={p.id}>{p.city}/{p.state} — {p.name}</option>
                ))}
              </select>
            )}
            {form.praca_id === "NOTA" && (
              <div style={{ marginTop: 6, padding: 10, background: "#e0f2fe", border: "1px solid #0ea5e9", borderRadius: 10, fontSize: 12, color: "#075985" }}>
                <strong>📍 Praça Nota:</strong> este colaborador pode bater ponto direto no endereço do cliente
                (cerca virtual gerada automaticamente no endereço da bolha aberta ou da próxima pendente).
                Útil para técnicos que vão direto ao cliente sem passar na empresa, economizando tempo.
                O raio da cerca é configurado em <strong>Configurações → Tempos de Referência</strong>.
              </div>
            )}
          </Field>

          {/* Praças secundárias — usadas quando o colaborador opera em mais de
              uma unidade. A cerca virtual e os feriados consideram QUALQUER
              uma das praças listadas (principal + secundárias). */}
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
                      📍 {p.city}/{p.state} — {p.name}
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
                As cercas virtuais e feriados dessas praças adicionais também serão aceitas para este colaborador.
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
                  {form.clock_in_enabled ? "🕐 CLT — bate ponto" : "🚫 Não bate ponto (terceirizado/MEI)"}
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
                  🧪 Modo Teste (Admin)
                </strong>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                  Quando ativado, este colaborador pode bater ponto em <strong>qualquer localização</strong> e
                  com <strong>qualquer selfie</strong> — útil para demos e validação. Os registros ficam
                  marcados com 🧪 na auditoria.
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
                  {form.active === false ? "🚫 Inativo (desligado/desativado)" : "✅ Ativo"}
                </strong>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                  Ao desativar, o colaborador <strong>não bate mais ponto</strong> e some das listas operacionais.
                  {' '}Se ele tiver itens em custódia ativos, ao salvar você verá a lista pra cobrar/devolver e
                  poderá imprimir o romaneio.
                </div>
              </div>
            </label>
          </div>

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
                  📋 Reaproveitar cercas já cadastradas
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
                  Nenhuma cerca para <strong>{collaborator?.name}</strong>. Clique em <strong>"+ Nova cerca"</strong> para adicionar — múltiplas permitidas.
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
                          📋 Duplicar para…
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
                        Selecione colaboradores que receberão uma cópia de "<strong>{f.name}</strong>":
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
    "Entrada": "🚪",
    "Início intervalo": "🍽️",
    "Fim intervalo": "🔄",
    "Saída": "🏁",
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
      window.prompt("Copie o link manualmente:", url);
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
        <span style={{ fontSize: 11, fontWeight: 700, color: "#475569", flexShrink: 0 }}>🔗 Link</span>
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
          {copied ? "✓ Copiado!" : "📋 Copiar"}
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
            💬 WhatsApp
          </a>
        )}
      </div>
      <div style={{ fontSize: 10, color: "#64748b", marginTop: 4, paddingLeft: 2 }}>
        Abre o app de serviço já com {collaborator.name?.split(" ")[0] || "o técnico"} selecionado.
      </div>
    </div>
  );
}
