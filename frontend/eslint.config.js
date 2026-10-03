import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default [
  { ignores: ["dist/**", "node_modules/**"] },

  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      globals: { ...globals.browser },
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: "module",
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      // React 17+ auto-injects the JSX runtime, so the default import is dead.
      "no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },

  {
    // Tests legitimately reach into internals and use loose assertions.
    files: ["**/*.test.{js,jsx}", "src/test/**"],
    languageOptions: { globals: { ...globals.node } },
    rules: {
      "no-undef": "off",
      "react-refresh/only-export-components": "off",
    },
  },
];