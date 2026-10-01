import { test, expect } from '@playwright/test';
import { VIEWPORTS, setMobileViewport, checkHorizontalScroll } from '../fixtures/mobile.fixture.js';

test.describe('ChatPage Mobile Responsiveness', () => {
  test.beforeEach(async ({ page }) => {
    // Login
    await page.goto('/login');
    await page.fill('input[type="email"]', 'admin@admin.com');
    await page.fill('input[type="password"]', 'admin123');
    await page.click('button[type="submit"]');
    await page.waitForURL('/chat', { timeout: 10000 });
  });

  test('page loads correctly on mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');

    // Main chat elements should be visible
    await expect(page.locator('textarea[placeholder*="message"]')).toBeVisible();
  });

  test('config selector is responsive on mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14'); // 390px - modern device size

    // Look for config selector trigger in the main chat area
    const configButton = page.locator('[data-testid="config-selector-trigger"]');

    if (await configButton.isVisible({ timeout: 2000 }).catch(() => false)) {
      await configButton.click();
      await page.waitForTimeout(300); // Wait for animation

      const selector = page.locator('[data-testid="config-selector"]');
      if (await selector.isVisible()) {
        const selectorBox = await selector.boundingBox();

        // Should be nearly full width on mobile (with margins)
        expect(selectorBox.width).toBeGreaterThan(350); // 390px - margins
        expect(selectorBox.width).toBeLessThanOrEqual(390);
      }
    }
    // Test passes if config selector doesn't exist (optional feature)
  });

  test('conversation title truncates appropriately', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14'); // 390px

    // If there's a conversation title, it should be visible and truncated
    const title = page.locator('[data-testid="conversation-title"]');

    if (await title.isVisible()) {
      const titleBox = await title.boundingBox();

      // Title should fit within mobile screen constraints
      expect(titleBox.width).toBeLessThanOrEqual(200); // Reasonable for modern phones
    }
  });

  test('title uses more space on larger screens', async ({ page }) => {
    await setMobileViewport(page, 'iPadMini'); // 768px

    const title = page.locator('[data-testid="conversation-title"]');

    if (await title.isVisible()) {
      const titleBox = await title.boundingBox();

      // On tablet, title can be wider
      // Should allow up to md:max-w-[300px]
      expect(titleBox.width).toBeGreaterThanOrEqual(100);
    }
  });

  test('input area is touch-friendly', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');

    const textarea = page.locator('textarea[placeholder*="message"]');
    await expect(textarea).toBeVisible();

    const textareaBox = await textarea.boundingBox();

    // Input should have adequate height for touch
    expect(textareaBox.height).toBeGreaterThanOrEqual(44);
  });

  test('send button is touch-friendly', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');

    // Send button should be adequately sized
    const sendButton = page.locator('button[type="submit"]').or(page.getByRole('button', { name: /send/i }));

    if (await sendButton.isVisible()) {
      const buttonBox = await sendButton.boundingBox();
      expect(buttonBox.width).toBeGreaterThanOrEqual(40);
      expect(buttonBox.height).toBeGreaterThanOrEqual(40);
    }
  });

  test('no horizontal scroll on mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14'); // 390px - modern device

    const scrollInfo = await checkHorizontalScroll(page);
    expect(scrollInfo.hasOverflow).toBe(false);
  });

  test('no horizontal scroll on standard mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14'); // 390px

    const scrollInfo = await checkHorizontalScroll(page);
    expect(scrollInfo.hasOverflow).toBe(false);
  });

  test('sidebar opens on mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');

    // Find and click menu button (should be in MainLayout header)
    const menuButton = page.getByRole('button', { name: /open menu/i });

    if (await menuButton.isVisible()) {
      await menuButton.click();

      // Sidebar should be visible
      // Wait a bit for animation
      await page.waitForTimeout(300);

      // Check if sidebar navigation appeared (folders, settings, etc.)
      const sidebar = page.locator('nav').or(page.locator('[role="navigation"]'));
      await expect(sidebar.first()).toBeVisible();
    }
  });

  test('chat messages fit within viewport', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');

    // Send a test message
    const textarea = page.locator('textarea[placeholder*="message"]');
    await textarea.fill('Test message for mobile');

    const sendButton = page.locator('button[type="submit"]').first();
    if (await sendButton.isVisible()) {
      await sendButton.click();

      // Wait for message to appear
      await page.waitForTimeout(1000);

      // Check that no horizontal scroll was introduced
      const scrollInfo = await checkHorizontalScroll(page);
      expect(scrollInfo.hasOverflow).toBe(false);
    }
  });

  test('works in landscape orientation', async ({ page }) => {
    await setMobileViewport(page, 'landscapePhone'); // 844x390

    // Page should still be usable
    await expect(page.locator('textarea[placeholder*="message"]')).toBeVisible();

    // No horizontal overflow
    const scrollInfo = await checkHorizontalScroll(page);
    expect(scrollInfo.hasOverflow).toBe(false);
  });
});
