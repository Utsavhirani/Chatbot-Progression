import { defineConfig, devices } from "@playwright/test";

// E2E runs the real backend (fake LLM provider, dedicated assistant_e2e database) and the Vite
// dev server on separate ports, so it never touches dev data or uses Groq quota.
const API_PORT = 8001;
const WEB_PORT = 5174;
const E2E_DB = "postgresql+asyncpg://assistant:assistant_dev_pw@127.0.0.1:5433/assistant_e2e";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  timeout: 30_000,
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      cwd: "../backend",
      command: `python -m uv run alembic upgrade head && python -m uv run uvicorn app.main:app --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/health/live`,
      env: {
        PROVIDER: "fake",
        DATABASE_URL: E2E_DB,
        ALLOWED_ORIGINS: `http://localhost:${WEB_PORT}`,
        LOG_LEVEL: "WARNING",
        CHAT_RATE_PER_MINUTE: "1000",
        LOGIN_RATE_PER_MINUTE: "1000",
        REGISTER_RATE_PER_MINUTE: "1000",
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      env: { API_PROXY_TARGET: `http://127.0.0.1:${API_PORT}`, PORT: String(WEB_PORT) },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
