/**
 * ESLint flat config — sane defaults for SmartProv.
 *
 * Regras críticas:
 *   - `no-undef: error` — pega componentes/variáveis usados sem import
 *     (foi exatamente isso que travou a tela no iter135 com <Metric>).
 *   - `no-dupe-keys: error` (default) — pega bugs como o que estava em
 *     `api.js` (chaves duplicadas sobrescrevendo silenciosamente).
 *   - `react-hooks/rules-of-hooks: error` — proteção máxima.
 *   - `react-hooks/exhaustive-deps: warn` — segue recomendação oficial do
 *     time React (warn ao invés de error, evita CI vermelho por hint).
 *
 * Run:
 *   yarn lint           # report (warnings allowed)
 *   yarn lint:strict    # CI mode (any warning = fail)
 */
const reactHooks = require('eslint-plugin-react-hooks');
const reactPlugin = require('eslint-plugin-react');
const js = require('@eslint/js');

module.exports = [
  js.configs.recommended,
  {
    files: ['src/**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: {
        window: 'readonly', document: 'readonly', console: 'readonly',
        navigator: 'readonly', localStorage: 'readonly', sessionStorage: 'readonly',
        fetch: 'readonly', URL: 'readonly', URLSearchParams: 'readonly',
        Blob: 'readonly', FormData: 'readonly', FileReader: 'readonly',
        File: 'readonly', Image: 'readonly', alert: 'readonly', confirm: 'readonly',
        prompt: 'readonly', setTimeout: 'readonly', clearTimeout: 'readonly',
        setInterval: 'readonly', clearInterval: 'readonly', requestAnimationFrame: 'readonly',
        cancelAnimationFrame: 'readonly', AbortController: 'readonly',
        EventSource: 'readonly', MutationObserver: 'readonly',
        ResizeObserver: 'readonly', IntersectionObserver: 'readonly',
        MediaRecorder: 'readonly', AudioContext: 'readonly',
        webkitAudioContext: 'readonly', performance: 'readonly',
        Notification: 'readonly', SpeechSynthesisUtterance: 'readonly',
        speechSynthesis: 'readonly', process: 'readonly', module: 'readonly',
        require: 'readonly', __dirname: 'readonly', global: 'readonly',
        // Globals do browser que faltavam (revelados ao ligar no-undef):
        Event: 'readonly', CustomEvent: 'readonly', WebSocket: 'readonly',
        XMLSerializer: 'readonly', Audio: 'readonly', atob: 'readonly',
        btoa: 'readonly', crypto: 'readonly', HTMLImageElement: 'readonly',
        HTMLInputElement: 'readonly', HTMLElement: 'readonly',
        DOMParser: 'readonly', RTCPeerConnection: 'readonly',
        navigator: 'readonly', screen: 'readonly', location: 'readonly',
        getComputedStyle: 'readonly', matchMedia: 'readonly',
        history: 'readonly', Worker: 'readonly', SharedWorker: 'readonly',
        Blob: 'readonly', ImageData: 'readonly', OffscreenCanvas: 'readonly',
        BroadcastChannel: 'readonly', queueMicrotask: 'readonly',
        TextEncoder: 'readonly', TextDecoder: 'readonly',
        structuredClone: 'readonly', AbortSignal: 'readonly',
      },
    },
    plugins: { 'react-hooks': reactHooks, react: reactPlugin },
    settings: { react: { version: 'detect' } },
    rules: {
      // React Hooks
      'react-hooks/rules-of-hooks': 'error',
      // exhaustive-deps fica como warn por design — recomendação oficial
      // React team. Pega tanto novos quanto legados sem quebrar CI/build.
      'react-hooks/exhaustive-deps': 'warn',
      // React JSX basics
      'react/jsx-uses-react': 'error',
      'react/jsx-uses-vars': 'error',
      // Disable rules too noisy for this codebase
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-undef': 'error',         // pega componentes/variáveis usados sem import (ex: bug iter135 <Metric>)
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
];
