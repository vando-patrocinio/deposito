/**
 * ESLint flat config — strict for NEW files, lenient for grandfathered legacy files.
 *
 * Goal: `react-hooks/exhaustive-deps` is `error` by default so new code can't add
 * more debt. Files in `LEGACY_FILES` keep the rule as `warn` so the existing 108
 * violations don't block the CI. Remove a path from `LEGACY_FILES` once it's clean.
 *
 * Run:
 *   yarn lint           # report (warnings allowed in legacy)
 *   yarn lint:strict    # CI mode (any warning = fail)
 */
const reactHooks = require('eslint-plugin-react-hooks');
const reactPlugin = require('eslint-plugin-react');
const js = require('@eslint/js');

// Files allowed to keep the existing exhaustive-deps violations.
// New files MUST NOT be added here.
const LEGACY_FILES = [
  'src/App.js',
  'src/CollaboratorApp.js',
  'src/CadastroPanel.js',
  'src/SettingsPanel.js',
  'src/LousaAdminPanel.js',
  'src/LousaMobile.js',
  'src/LiveMap.js',
  'src/LogsPanel.js',
  'src/StokPanel.js',
  'src/AtlazIntegrationCard.js',
  'src/EstoquePanel.js',
  'src/DashboardPanel.js',
  'src/PracasPanel.js',
  'src/TimesheetView.js',
  'src/AdminLogin.js',
  'src/AuthContext.js',
  'src/AiRankingPanel.js',
  'src/SmartoltIntegrationCard.js',
  'src/QRScannerModal.js',
  'src/useEventStream.js',
  'src/serverTime.js',
  'src/lousa/LousaHistoryModal.js',
  'src/lousa/EditTicketModal.js',
  'src/lousa/CreateTicketModal.js',
  'src/lousa/BulkActionsBar.js',
  'src/lousa/RescheduleModal.js',
];

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
      },
    },
    plugins: { 'react-hooks': reactHooks, react: reactPlugin },
    settings: { react: { version: 'detect' } },
    rules: {
      // React Hooks — STRICT for new files
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',
      // React JSX basics
      'react/jsx-uses-react': 'error',
      'react/jsx-uses-vars': 'error',
      // Disable rules too noisy for this codebase
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-undef': 'off',          // globals handled above; CRA doesn't need this
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
  // Grandfathered files — exhaustive-deps as warning to not block CI
  {
    files: LEGACY_FILES,
    rules: { 'react-hooks/exhaustive-deps': 'warn' },
  },
];
