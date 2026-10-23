import { describe, expect, it } from 'vitest';
import { DEFAULT_MAP_STYLE_URL, readConfig } from './config';

describe('readConfig', () => {
  it('usa la misma origen y el estilo de OpenFreeMap si no hay variables', () => {
    expect(readConfig({} as ImportMetaEnv)).toEqual({
      apiUrl: '',
      mapStyleUrl: DEFAULT_MAP_STYLE_URL,
    });
  });

  it('quita la barra final y los espacios', () => {
    const config = readConfig({
      VITE_API_URL: ' https://api.example.com/ ',
      VITE_MAP_STYLE_URL: 'https://tiles.example.com/style.json',
    } as ImportMetaEnv);

    expect(config).toEqual({
      apiUrl: 'https://api.example.com',
      mapStyleUrl: 'https://tiles.example.com/style.json',
    });
  });

  it.each(['javascript:alert(1)', 'ftp://api.example.com', 'no es una url'])(
    'rechaza %s',
    (value) => {
      expect(() => readConfig({ VITE_API_URL: value } as ImportMetaEnv)).toThrow();
    },
  );

  it('rechaza URLs con credenciales: VITE_* es público', () => {
    expect(() =>
      readConfig({ VITE_API_URL: 'https://user:pass@api.example.com' } as ImportMetaEnv),
    ).toThrow('credenciales');
  });
});
