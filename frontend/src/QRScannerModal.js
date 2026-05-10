import React, { useEffect, useRef, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";

/**
 * Modal scanner de QR/Barcode (câmera traseira).
 * - Detecta QR + Code128 + Code39 + EAN13 (boa cobertura para etiquetas de ONT).
 * - Permite tocar para selecionar foto da galeria como fallback.
 *
 * Props:
 *   onClose(): fecha sem resultado
 *   onScan(text): chamado com o texto lido (também fecha o modal)
 */
export default function QRScannerModal({ onClose, onScan }) {
  const containerId = "ont-qr-scanner-region";
  const scannerRef = useRef(null);
  const [err, setErr] = useState("");
  const [scanning, setScanning] = useState(false);
  const [cameras, setCameras] = useState([]);
  const [activeCam, setActiveCam] = useState(null);

  // Inicializa câmeras
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const cams = await Html5Qrcode.getCameras();
        if (!mounted) return;
        if (!cams || cams.length === 0) {
          setErr("Nenhuma câmera detectada. Use o botão 📷 Galeria abaixo.");
          return;
        }
        setCameras(cams);
        // Prefere traseira ("back" / "environment" / "rear")
        const back = cams.find((c) => /back|environment|traseira|rear/i.test(c.label));
        const target = back || cams[cams.length - 1];
        setActiveCam(target.id);
      } catch (e) {
        setErr(`Falha ao acessar câmera: ${e.message || e}`);
      }
    })();
    return () => { mounted = false; };
  }, []);

  // Inicia scan quando câmera escolhida
  useEffect(() => {
    if (!activeCam) return;
    const html5 = new Html5Qrcode(containerId, /* verbose */ false);
    scannerRef.current = html5;
    setScanning(true);
    setErr("");
    html5.start(
      { deviceId: { exact: activeCam } },
      {
        fps: 10,
        qrbox: { width: 280, height: 180 },
        aspectRatio: 1.6,
      },
      (decodedText) => {
        // Sucesso
        try { html5.stop().then(() => html5.clear()).catch(() => {}); } catch (e) { /* noop */ }
        onScan((decodedText || "").trim());
      },
      () => { /* ignore frames sem leitura */ }
    ).catch((e) => {
      setErr(`Não foi possível iniciar a câmera: ${e?.message || e}`);
      setScanning(false);
    });

    return () => {
      const s = scannerRef.current;
      if (s) {
        try { s.stop().then(() => s.clear()).catch(() => {}); } catch (e) { /* noop */ }
      }
    };
  }, [activeCam, onScan]);

  const onPickFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setErr("");
    const html5 = scannerRef.current || new Html5Qrcode(containerId);
    scannerRef.current = html5;
    try {
      try { await html5.stop(); } catch (e) { /* noop */ }
      const text = await html5.scanFile(file, /* showImage */ false);
      onScan((text || "").trim());
    } catch (e2) {
      setErr(`Não foi possível ler o código da imagem: ${e2?.message || e2}`);
    }
  };

  return (
    <div data-testid="qr-scanner-modal" onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.85)", zIndex: 200, display: "grid", placeItems: "center", padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ background: "#0f172a", color: "white", borderRadius: 18, padding: 18, maxWidth: 520, width: "100%" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 17 }}>Escanear MAC/SN da ONT</h3>
          <button onClick={onClose} data-testid="qr-close-btn"
                  style={{ background: "transparent", border: "none", color: "white", fontSize: 22, cursor: "pointer" }}>×</button>
        </div>
        <p style={{ fontSize: 12, color: "#94a3b8", margin: "0 0 12px" }}>
          Aponte a câmera para o QR code ou código de barras na etiqueta embaixo da ONT.
        </p>

        <div id={containerId}
             style={{ width: "100%", aspectRatio: "1.4 / 1", background: "#000",
                       borderRadius: 12, overflow: "hidden", border: "1px solid #1e293b" }} />

        {err && (
          <div data-testid="qr-error" style={{ marginTop: 10, padding: 10, background: "#fee2e2", color: "#7f1d1d", borderRadius: 10, fontSize: 12 }}>
            ⚠ {err}
          </div>
        )}

        {/* Trocar câmera */}
        {cameras.length > 1 && (
          <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
            {cameras.map((c) => (
              <button key={c.id} onClick={() => setActiveCam(c.id)}
                      style={{
                        padding: "6px 10px", borderRadius: 8, fontSize: 11,
                        border: c.id === activeCam ? "1px solid #0ea5e9" : "1px solid #334155",
                        background: c.id === activeCam ? "#075985" : "#1e293b",
                        color: "white", cursor: "pointer",
                      }}>
                {c.label?.substring(0, 28) || "Câmera"}
              </button>
            ))}
          </div>
        )}

        {/* Fallback galeria */}
        <label data-testid="qr-gallery-input"
               style={{ display: "block", marginTop: 12, padding: 10, background: "#1e293b", borderRadius: 10, fontSize: 12, textAlign: "center", cursor: "pointer", border: "1px dashed #334155" }}>
          📁 Selecionar foto da galeria (fallback)
          <input type="file" accept="image/*" onChange={onPickFile} style={{ display: "none" }} />
        </label>

        <div style={{ fontSize: 10, color: "#64748b", marginTop: 8, textAlign: "center" }}>
          {scanning ? "🟢 Câmera ativa · alinhe o código no quadro" : "Iniciando câmera…"}
        </div>
      </div>
    </div>
  );
}
