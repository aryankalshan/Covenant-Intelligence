import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repositoryRoot, "FRONTEND_");
  const port = Number.parseInt(process.env.FRONTEND_PORT ?? env.FRONTEND_PORT ?? "5173", 10);
  return {
    plugins: [react()],
    server: { port, strictPort: true },
    test: { environment: "jsdom", setupFiles: "./src/test-setup.ts" },
  };
});
