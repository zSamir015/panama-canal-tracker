// @vitest-environment node
import { ESLint } from 'eslint';
import { describe, expect, it } from 'vitest';

// Prueba la configuración real (`eslint.config.js`) sobre fragmentos de código: si alguien quita
// la regla anti-XSS (AGENTS.md §8.7), este test falla.
const eslint = new ESLint();

async function restrictedSyntaxErrors(code: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: 'src/App.tsx' });
  return (result?.messages ?? [])
    .filter((message) => message.ruleId === 'no-restricted-syntax')
    .map((message) => message.message);
}

describe('regla anti-XSS de ESLint', () => {
  it('prohíbe dangerouslySetInnerHTML', async () => {
    const errors = await restrictedSyntaxErrors(
      'export function Name({ name }: { name: string }) {\n' +
        '  return <span dangerouslySetInnerHTML={{ __html: name }} />;\n' +
        '}\n',
    );

    expect(errors).toEqual([expect.stringContaining('dangerouslySetInnerHTML')]);
  });

  it('prohíbe asignar innerHTML', async () => {
    const errors = await restrictedSyntaxErrors(
      'export function show(el: HTMLElement, name: string) {\n  el.innerHTML = name;\n}\n',
    );

    expect(errors).toEqual([expect.stringContaining('innerHTML')]);
  });

  it('prohíbe setHTML (popups de MapLibre) e insertAdjacentHTML', async () => {
    const errors = await restrictedSyntaxErrors(
      'export function show(popup: { setHTML(h: string): void }, el: HTMLElement, n: string) {\n' +
        '  popup.setHTML(n);\n' +
        "  el.insertAdjacentHTML('beforeend', n);\n" +
        '}\n',
    );

    expect(errors).toHaveLength(2);
  });

  it('permite texto: React lo escapa', async () => {
    const errors = await restrictedSyntaxErrors(
      'export function Name({ name }: { name: string }) {\n  return <span>{name}</span>;\n}\n',
    );

    expect(errors).toEqual([]);
  });
});
