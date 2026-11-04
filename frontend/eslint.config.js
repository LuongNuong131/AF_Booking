import vue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'
export default [
  { ignores: ['dist/**', 'node_modules/**', 'coverage/**', '.vercel/**'] },
  {
    files: ['**/*.{js,mjs,ts}'],
    languageOptions: { parser: tseslint.parser },
    rules: { 'no-console': ['error', { allow: ['warn'] }] },
  },
  ...vue.configs['flat/base'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'] },
    },
    rules: { 'vue/no-v-html': 'error', 'no-console': ['error', { allow: ['warn'] }] },
  },
]
