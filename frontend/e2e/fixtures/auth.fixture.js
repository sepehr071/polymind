import { test as base } from '@playwright/test';

/**
 * Auth fixture that provides an authenticated page
 * Usage:
 *   import { test } from '../fixtures/auth.fixture.js';
 *   test('my test', async ({ authenticatedPage }) => {
 *     // page is already logged in
 *   });
 */
export const test = base.extend({
  authenticatedPage: async ({ page }, use) => {
    // Navigate to login page
    await page.goto('/login');

    // Fill in login credentials
    await page.fill('input[type="email"]', 'admin@admin.com');
    await page.fill('input[type="password"]', 'admin123');

    // Submit login form
    await page.click('button[type="submit"]');

    // Wait for successful login (redirect to chat page)
    await page.waitForURL('/chat', { timeout: 10000 });

    // Use the authenticated page
    await use(page);
  },
});

export { expect } from '@playwright/test';
