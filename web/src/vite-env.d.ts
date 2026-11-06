/// <reference types="vite/client" />

// Variables públicas del frontend: acaban en el JavaScript que se descarga cualquiera.
// Nunca secretos aquí (AGENTS.md §8.2).
interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_MAP_STYLE_URL?: string;
  readonly VITE_DEMO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
