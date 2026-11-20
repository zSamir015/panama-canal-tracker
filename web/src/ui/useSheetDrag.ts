import { useCallback, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';

interface SheetDragOptions {
  /** Llamado al arrastrar hacia abajo más allá del umbral para cerrar o plegar. */
  onDismiss: () => void;
}

const DISMISS_THRESHOLD_PX = 64;
const EXPAND_THRESHOLD_PX = -56;

/**
 * Permite arrastrar verticalmente el asa de una hoja inferior móvil (<= 640 px): deslizar hacia
 * arriba la expande y hacia abajo la cierra o pliega.
 */
export function useSheetDrag({ onDismiss }: SheetDragOptions) {
  const startYRef = useRef<number | null>(null);
  const [dragOffset, setDragOffset] = useState(0);
  const [expandedTall, setExpandedTall] = useState(false);

  const onPointerDown = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    // Solo botón primario / toque directo sobre el asa o cabecera.
    if (event.button !== 0 && event.pointerType === 'mouse') {
      return;
    }
    startYRef.current = event.clientY;
    setDragOffset(0);
    if (typeof event.currentTarget.setPointerCapture === 'function') {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
  }, []);

  const onPointerMove = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (startYRef.current === null) {
      return;
    }
    const delta = event.clientY - startYRef.current;
    // Suaviza el estiramiento hacia arriba y sigue el dedo hacia abajo.
    setDragOffset(Math.max(-96, Math.min(220, delta)));
  }, []);

  const finishDrag = useCallback(() => {
    if (startYRef.current === null) {
      return;
    }
    startYRef.current = null;
    if (dragOffset > DISMISS_THRESHOLD_PX) {
      setDragOffset(0);
      setExpandedTall(false);
      onDismiss();
      return;
    }
    if (dragOffset < EXPAND_THRESHOLD_PX) {
      setExpandedTall(true);
    } else if (dragOffset > 28) {
      setExpandedTall(false);
    }
    setDragOffset(0);
  }, [dragOffset, onDismiss]);

  const resetTall = useCallback(() => {
    setExpandedTall(false);
    setDragOffset(0);
  }, []);

  return {
    dragOffset,
    expandedTall,
    resetTall,
    handleProps: {
      onPointerDown,
      onPointerMove,
      onPointerUp: finishDrag,
      onPointerCancel: finishDrag,
    },
  };
}
