import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import { defineConfig, globalIgnores } from 'eslint/config';
import globals from 'globals';
import tseslint from 'typescript-eslint';

// Insertar HTML con datos dinámicos abre la puerta al XSS: los nombres y destinos de los buques
// vienen de AIS, y cualquiera con un transpondedor puede escribirlos (AGENTS.md §8.7).
const noRawHtml = [
  {
    selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
    message: 'Prohibido dangerouslySetInnerHTML (AGENTS.md §8.7): renderiza texto con React.',
  },
  {
    selector: 'AssignmentExpression > MemberExpression[property.name=/^(innerHTML|outerHTML)$/]',
    message: 'Prohibido asignar innerHTML/outerHTML (AGENTS.md §8.7): usa textContent.',
  },
  {
    selector: 'CallExpression[callee.property.name=/^(insertAdjacentHTML|setHTML)$/]',
    message:
      'Prohibido insertAdjacentHTML y Popup.setHTML de MapLibre (AGENTS.md §8.7): usa setText.',
  },
];

export default defineConfig([
  globalIgnores(['dist', 'coverage']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.strictTypeChecked,
      tseslint.configs.stylisticTypeChecked,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      'no-restricted-syntax': ['error', ...noRawHtml],
    },
  },
  {
    files: ['**/*.js'],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  prettier,
]);
