/**
 * Si la guía al primer uso ya se cerró en este navegador (issue #137). Se guarda un único
 * booleano en `localStorage`: nada personal ni ningún token (AGENTS.md §8.4 solo los prohíbe a
 * ellos ahí). Si el navegador bloquea el almacenamiento, la guía vuelve a salir y nada falla.
 */
export const GUIDE_SEEN_KEY = 'panama-canal-tracker:guide-seen';

export function hasSeenGuide(): boolean {
  try {
    return window.localStorage.getItem(GUIDE_SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

export function rememberGuideSeen(): void {
  try {
    window.localStorage.setItem(GUIDE_SEEN_KEY, '1');
  } catch {
    // Almacenamiento bloqueado (modo privado, política del navegador): saldrá otra vez.
  }
}
