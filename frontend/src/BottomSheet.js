import React, { useCallback, useEffect, useRef, useState } from "react";

/**
 * BottomSheet — modal estilo iOS/Android nativo com drag-to-dismiss.
 *
 * Regras de UX aplicadas no app do colaborador (kebab menu):
 * - Aparece subindo de baixo
 * - Pull handle no topo (visual feedback)
 * - Touch ou mouse drag pra baixo → desliza
 * - Drag > 35% da altura ou velocidade alta → fecha
 * - Drag < threshold → snap back com mola
 * - ESC ou click no backdrop também fecham
 * - Body content é scrollável; drag só funciona puxando do handle/header
 *
 * Props:
 *   open      — controla visibilidade
 *   onClose   — callback de fechar
 *   children  — conteúdo do sheet
 *   maxHeight — altura máxima (default 92vh)
 *   testid    — data-testid do container
 */
export default function BottomSheet({
  open, onClose, children, maxHeight = "92vh", testid,
}) {
  const sheetRef = useRef(null);
  const startY = useRef(0);
  const startTime = useRef(0);
  const lastY = useRef(0);
  const lastTime = useRef(0);
  const dragging = useRef(false);
  const sheetHeight = useRef(0);
  const [offset, setOffset] = useState(0);
  const [closing, setClosing] = useState(false);
  const [entering, setEntering] = useState(true);

  // Animação de entrada
  useEffect(() => {
    if (open) {
      setEntering(true);
      const t = setTimeout(() => setEntering(false), 50);
      return () => clearTimeout(t);
    }
  }, [open]);

  // ESC fecha
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const handleStart = useCallback((clientY) => {
    dragging.current = true;
    startY.current = clientY;
    lastY.current = clientY;
    startTime.current = Date.now();
    lastTime.current = Date.now();
    sheetHeight.current = sheetRef.current?.getBoundingClientRect().height || 600;
  }, []);

  const handleMove = useCallback((clientY) => {
    if (!dragging.current) return;
    const dy = clientY - startY.current;
    // Só permite drag pra baixo (positivo). Negativo trava em 0 com resistência.
    if (dy < 0) {
      setOffset(dy * 0.15); // resistência
    } else {
      setOffset(dy);
    }
    lastY.current = clientY;
    lastTime.current = Date.now();
  }, []);

  const handleEnd = useCallback(() => {
    if (!dragging.current) return;
    dragging.current = false;
    const dy = lastY.current - startY.current;
    const elapsed = Math.max(1, lastTime.current - startTime.current);
    const velocity = dy / elapsed; // px/ms — positivo = pra baixo

    const closeThreshold = sheetHeight.current * 0.35;
    const fastSwipe = velocity > 0.6;

    if (dy > closeThreshold || fastSwipe) {
      // Dismiss
      setClosing(true);
      setOffset(sheetHeight.current + 100);
      setTimeout(() => {
        setClosing(false);
        setOffset(0);
        onClose?.();
      }, 220);
    } else {
      // Snap back
      setOffset(0);
    }
  }, [onClose]);

  // Touch
  const onTouchStart = (e) => handleStart(e.touches[0].clientY);
  const onTouchMove = (e) => handleMove(e.touches[0].clientY);
  const onTouchEnd = () => handleEnd();

  // Mouse (drag por desktop)
  const onMouseDown = (e) => {
    e.preventDefault();
    handleStart(e.clientY);
    const onMM = (ev) => handleMove(ev.clientY);
    const onMU = () => {
      handleEnd();
      window.removeEventListener("mousemove", onMM);
      window.removeEventListener("mouseup", onMU);
    };
    window.addEventListener("mousemove", onMM);
    window.addEventListener("mouseup", onMU);
  };

  if (!open) return null;

  const transitionStyle = (dragging.current && !closing)
    ? "none"
    : closing
      ? "transform .22s cubic-bezier(.4,0,.6,1)"
      : entering
        ? "transform .28s cubic-bezier(.16,1,.3,1)"
        : "transform .35s cubic-bezier(.34,1.56,.64,1)"; // spring snap-back

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
      data-testid={testid || "bottom-sheet-backdrop"}
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,.72)",
        zIndex: 100, overflow: "hidden",
        display: "flex", alignItems: "flex-end",
        opacity: entering ? 0 : 1,
        transition: "opacity .22s",
        touchAction: "none",
      }}
    >
      <div
        ref={sheetRef}
        data-testid={testid ? `${testid}-sheet` : "bottom-sheet"}
        style={{
          width: "100%", background: "#fafafa",
          borderRadius: "20px 20px 0 0",
          maxHeight, overflow: "hidden",
          boxShadow: "0 -20px 50px rgba(0,0,0,.28)",
          transform: entering
            ? "translateY(100%)"
            : `translateY(${offset}px)`,
          transition: transitionStyle,
          display: "flex", flexDirection: "column",
        }}
      >
        {/* Drag handle area — só essa região responde ao drag */}
        <div
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
          onMouseDown={onMouseDown}
          data-testid="sheet-drag-handle"
          style={{
            padding: "10px 0 6px", cursor: "grab",
            display: "flex", justifyContent: "center",
            flexShrink: 0,
            background: "transparent",
            userSelect: "none",
            WebkitUserSelect: "none",
          }}
        >
          <div style={{
            width: 40, height: 4, borderRadius: 999,
            background: "#cbd5e1",
            transition: "background .15s",
          }} />
        </div>

        {/* Body scrollável */}
        <div style={{
          flex: 1, overflowY: "auto", overscrollBehavior: "contain",
          WebkitOverflowScrolling: "touch",
          padding: "0 0 28px",
        }}>
          {children}
        </div>
      </div>
    </div>
  );
}
