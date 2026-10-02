import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const eslintConfig = [
  ...nextVitals,
  ...nextTypescript,
  {
    ignores: [".next/**", ".mcp-dist/**", "next-env.d.ts", "node_modules/**"],
  },
];

export default eslintConfig;
