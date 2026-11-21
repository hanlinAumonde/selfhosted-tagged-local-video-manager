import { defineConfig, devices } from '@playwright/test';

// The stack is started outside Playwright (see docker-compose.e2e.yml): in CI it is a
// step of its own, so its logs can be collected whether or not the journeys pass.
const port = process.env['E2E_PORT'] ?? '8080';

export default defineConfig({
  testDir: './journeys',
  // Journeys share one stack, and migration slots and device limits are global to it,
  // so two journeys at once could slow or block each other's migrations.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env['CI'],
  retries: 0,
  reporter: process.env['CI'] ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${port}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
