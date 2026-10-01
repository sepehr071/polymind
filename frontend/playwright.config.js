import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for mobile responsiveness testing
 * See https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  testDir: './e2e',

  // Run tests in parallel
  fullyParallel: true,

  // Fail build on CI if you accidentally left test.only in source code
  forbidOnly: !!process.env.CI,

  // Retry on CI only
  retries: process.env.CI ? 2 : 0,

  // Reporter to use
  reporter: [
    ['html'],
    ['list']
  ],

  // Shared settings for all projects
  use: {
    // Base URL for the app
    baseURL: 'http://localhost:3000',

    // Collect trace when retrying the failed test
    trace: 'on-first-retry',

    // Screenshot on failure
    screenshot: 'only-on-failure',

    // Video on failure
    video: 'retain-on-failure',
  },

  // Configure projects for major browsers and mobile devices
  projects: [
    // Desktop browsers
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },

    // Mobile devices
    {
      name: 'Mobile Chrome',
      use: { ...devices['Pixel 7'] },
    },

    {
      name: 'Mobile Safari',
      use: { ...devices['iPhone 14'] },
    },

    {
      name: 'Mobile Safari Pro Max',
      use: { ...devices['iPhone 14 Pro Max'] },
    },

    {
      name: 'Small Mobile',
      use: { ...devices['Galaxy S8+'] },
    },

    // Tablet
    {
      name: 'iPad',
      use: { ...devices['iPad Pro 11'] },
    },

    // Firefox and WebKit (optional, uncomment to enable)
    // {
    //   name: 'firefox',
    //   use: { ...devices['Desktop Firefox'] },
    // },
    // {
    //   name: 'webkit',
    //   use: { ...devices['Desktop Safari'] },
    // },
  ],

  // Run local dev server before starting tests
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
});
