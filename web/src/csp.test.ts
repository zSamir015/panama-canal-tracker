import { describe, expect, it } from 'vitest';
import { buildCsp, DEFAULT_TILES_ORIGIN } from '../csp';
import { DEFAULT_MAP_STYLE_URL } from './config';

function directive(csp: string, name: string): string[] {
  const entry = csp.split('; ').find((part) => part.startsWith(`${name} `));
  return entry === undefined ? [] : entry.split(' ').slice(1);
}

describe('buildCsp', () => {
  it('el origen de tiles por defecto es el que usa la aplicación', () => {
    expect(DEFAULT_TILES_ORIGIN).toBe(new URL(DEFAULT_MAP_STYLE_URL).origin);
  });

  it('por defecto: el mismo origen y OpenFreeMap', () => {
    const csp = buildCsp({});

    expect(directive(csp, 'connect-src')).toEqual(["'self'", 'https://tiles.openfreemap.org']);
    expect(directive(csp, 'img-src')).toContain('https://tiles.openfreemap.org');
  });

  it('los scripts solo del propio origen, sin unsafe-inline ni unsafe-eval', () => {
    const csp = buildCsp({});

    expect(directive(csp, 'script-src')).toEqual(["'self'"]);
    expect(csp).not.toContain('unsafe-eval');
    expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/);
  });

  it('cierra lo que no se usa: objetos, base, formularios y todo lo demás por defecto', () => {
    const csp = buildCsp({});

    expect(directive(csp, 'default-src')).toEqual(["'self'"]);
    expect(directive(csp, 'object-src')).toEqual(["'none'"]);
    expect(directive(csp, 'base-uri')).toEqual(["'self'"]);
    expect(directive(csp, 'form-action')).toEqual(["'self'"]);
    expect(directive(csp, 'worker-src')).toEqual(["'self'", 'blob:']);
  });

  it('con una API en otro origen permite su HTTP y su WebSocket, y solo eso', () => {
    const csp = buildCsp({ VITE_API_URL: 'https://api.example.com/' });

    expect(directive(csp, 'connect-src')).toEqual([
      "'self'",
      'https://tiles.openfreemap.org',
      'https://api.example.com',
      'wss://api.example.com',
    ]);
  });

  it('una API sin TLS usa ws://', () => {
    const csp = buildCsp({ VITE_API_URL: 'http://localhost:8000' });

    expect(directive(csp, 'connect-src')).toContain('ws://localhost:8000');
  });

  it('un proveedor de tiles distinto sustituye al de por defecto', () => {
    const csp = buildCsp({ VITE_MAP_STYLE_URL: 'https://tiles.example.com/styles/x.json' });

    expect(csp).toContain('https://tiles.example.com');
    expect(csp).not.toContain('openfreemap');
  });

  it('una URL inválida hace fallar la compilación en lugar de abrir la política', () => {
    expect(() => buildCsp({ VITE_API_URL: 'javascript:alert(1)' })).toThrow();
  });

  it('nunca deja comodines', () => {
    expect(buildCsp({ VITE_API_URL: 'https://api.example.com' })).not.toMatch(/\s\*[\s;]|\*$/);
  });
});
