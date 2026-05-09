import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { AvatarZoomModal, Button, Card, Field, Icon, inputStyle, Row, StatusBadge } from "@/ui";
import GeofenceMap from "@/GeofenceMap";

const EMPTY = {
  name: "",
  cpf: "",
  email: "",
  phone: "",
  role: "Colaborador de Campo",
  praca_id: "",
  schedule: { entrada: "08:00", inicio_intervalo: "12:00", fim_intervalo: "13:00", saida: "17:00" },
  overtime_policy: { mode: "banco", hourly_rate_brl: 0, weekday_multiplier: 1.5, sunday_multiplier: 2.0 },
  is_test_mode: false,
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
      schedule: c.schedule || EMPTY.schedule,
      overtime_policy: c.overtime_policy || EMPTY.overtime_policy,
      is_test_mode: !!c.is_test_mode,
    });
    setEditing(c.id);
    setError("");
    setReuseSelected({});
  }

  async function save() {
    setBusy(true); setError("");
    try {
      let targetId = editing;
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
                      <span title="Modo teste — bate ponto em qualquer local com qualquer selfie" style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#faf5ff", color: "#7c3aed", border: "1px solid #d8b4fe" }}>
                        🧪 MODO TESTE
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
                    <Button variant="soft" onClick={() => setSelectedId(c.id)} data-testid={`fences-${c.id}`}>
                      <Icon name="map" /> Cercas
                      <span style={{ marginLeft: 6, background: fenceCounts[c.id] ? "#0ea5e9" : "#94a3b8", color: "white", borderRadius: 999, padding: "1px 7px", fontSize: 10, fontWeight: 900 }}>
                        {fenceCounts[c.id] ?? 0}
                      </span>
                    </Button>
                    <Button
                      variant="soft"
                      onClick={() => setConfirmReset(c.id)}
                      disabled={!c.avatar_data_url}
                      title={c.avatar_data_url ? "Remove a foto de referência — próxima selfie válida vira o novo avatar" : "Colaborador ainda não tem avatar"}
                      data-testid={`reset-face-${c.id}`}
                    >
                      <Icon name="camera" /> Resetar avatar e dispositivo
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

      {editing !== null ? (
        <Card title={editing === "new" ? "Novo colaborador" : "Editar colaborador"}>
          {error && <div data-testid="form-error" style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10 }}>{error}</div>}
          <Field label="Nome completo">
            <input data-testid="inp-name" style={inputStyle} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="CPF">
            <input data-testid="inp-cpf" style={inputStyle} value={form.cpf} onChange={(e) => setForm({ ...form, cpf: e.target.value })} placeholder="000.000.000-00" />
          </Field>
          <Field label="E-mail">
            <input data-testid="inp-email" style={inputStyle} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field label="Telefone">
            <input data-testid="inp-phone" style={inputStyle} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="+55 11 99999-0000" />
          </Field>
          <Field label="Cargo">
            <input style={inputStyle} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} />
          </Field>
          <Field label="Praça (local onde trabalha a maior parte do tempo)">
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
                {pracas.map((p) => (
                  <option key={p.id} value={p.id}>{p.city}/{p.state} — {p.name}</option>
                ))}
              </select>
            )}
          </Field>

          {/* Modo Teste — admin only */}
          <div data-testid="test-mode-block" style={{
            background: form.is_test_mode ? "#faf5ff" : "#f8fafc",
            border: `2px solid ${form.is_test_mode ? "#a855f7" : "#e2e8f0"}`,
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
                <strong style={{ color: form.is_test_mode ? "#7c3aed" : "#0f172a" }}>
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
