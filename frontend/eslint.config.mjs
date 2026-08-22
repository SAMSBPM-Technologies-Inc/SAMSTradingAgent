// Accessibility linting.
//
// Scoped deliberately to jsx-a11y rather than a full lint setup: the point is to
// stop a11y regressions reaching main, and a broad ruleset would bury those
// findings under style noise nobody acts on.
//
// Run with `npm run lint:a11y`. These rules encode the gaps found in the Tier 3
// audit — unlabelled inputs, disclosures with no expanded state, click handlers
// on non-interactive elements — so the same mistakes fail loudly next time.
import a11y from 'eslint-plugin-jsx-a11y'
import tsParser from '@typescript-eslint/parser'

export default [
  {
    files: ['src/**/*.tsx'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    plugins: { 'jsx-a11y': a11y },
    rules: {
      ...a11y.flatConfigs.recommended.rules,

      // Upgraded from warn: every one of these was an actual defect here.
      'jsx-a11y/label-has-associated-control': ['error', { assert: 'either' }],
      'jsx-a11y/click-events-have-key-events': 'error',
      'jsx-a11y/no-static-element-interactions': 'error',
      'jsx-a11y/interactive-supports-focus': 'error',
    },
  },
]
