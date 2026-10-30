import js from '@eslint/js'
import ts from 'typescript-eslint'
import vue from 'eslint-plugin-vue'
import globals from 'globals'

export default ts.config(
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  ...ts.configs.recommended,
  ...vue.configs['flat/essential'],
  { files: ['**/*.vue'], languageOptions: { parserOptions: { parser: ts.parser, extraFileExtensions: ['.vue'] } } },
  { languageOptions: { globals: { ...globals.browser, ...globals.node } }, rules: { 'vue/multi-word-component-names': 'off' } },
)
