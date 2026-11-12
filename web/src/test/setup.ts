import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Algunos tests corren en Node, sin DOM (`@vitest-environment node`): ahí no hay nada que preparar.
const hasDom = typeof window !== 'undefined';

afterEach(() => {
  cleanup();
  if (hasDom) {
    window.localStorage.clear();
  }
});

// jsdom tiene `<dialog>` pero no `showModal()` ni `close()`. Este sustituto mínimo abre y cierra
// y emite `close`, como el navegador; lo modal (foco atrapado, fondo inerte) no se simula.
if (hasDom) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (this.open) {
      this.open = false;
      this.dispatchEvent(new Event('close'));
    }
  };
}
