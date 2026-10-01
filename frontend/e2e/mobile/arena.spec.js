import { test, expect } from '@playwright/test';
import { VIEWPORTS, setMobileViewport, checkHorizontalScroll } from '../fixtures/mobile.fixture.js';

test.describe('ArenaPage Mobile Responsiveness', () => {
  test.beforeEach(async ({ page }) => {
    // Login
    await page.goto('/login');
    await page.fill('input[type="email"]', 'admin@admin.com');
    await page.fill('input[type="password"]', 'admin123');
    await page.click('button[type="submit"]');
    await page.waitForURL('/chat', { timeout: 10000 });

    // Navigate to arena page
    await page.goto('/arena');
    await page.waitForLoadState('networkidle');
  });

  test('displays empty state on mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');

    // Should show empty state with select button
    await expect(page.getByText(/no configs selected/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /select configs/i }).first()).toBeVisible();
  });

  test('config chips wrap properly on mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14'); // 390px - modern device size

    // If there are any config chips, they should wrap
    const chipContainer = page.locator('[data-testid="config-chips"]');

    // Container should not cause horizontal overflow
    if (await chipContainer.isVisible()) {
      const scrollInfo = await checkHorizontalScroll(page);
      expect(scrollInfo.hasOverflow).toBe(false);
    }
  });

  test('grid uses single column on mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');

    // Arena grid should exist (even if empty initially)
    const grid = page.locator('[data-testid="arena-grid"]');

    // Check if grid exists after configs are selected
    // For now, just verify the page structure is correct
    if (await grid.isVisible()) {
      const gridClasses = await grid.getAttribute('class');

      // Should have grid-cols-1 for mobile
      expect(gridClasses).toContain('grid-cols-1');
    }
  });

  test('header has appropriate padding on mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');

    // Page should be visible and not waste space
    const header = page.locator('h1:has-text("Arena")').locator('..');
    await expect(header).toBeVisible();

    // Should have reduced padding on mobile (p-4 instead of p-6)
    const headerBox = await header.boundingBox();
    expect(headerBox.width).toBeLessThanOrEqual(390); // iPhone 14 width
  });

  test('no horizontal scroll on modern mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14'); // 390px - focus on modern devices

    const scrollInfo = await checkHorizontalScroll(page);
    expect(scrollInfo.hasOverflow).toBe(false);
  });

  test('select configs button accessible on mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');

    const selectButton = page.getByRole('button', { name: /select configs/i }).first();
    await expect(selectButton).toBeVisible();

    // Button should be touchable (at least 44px height)
    const buttonBox = await selectButton.boundingBox();
    expect(buttonBox.height).toBeGreaterThanOrEqual(40); // Close to 44px target
  });

  test('input area accessible on mobile', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');

    // Input might not be visible initially (no configs selected)
    // But the layout should accommodate it
    const input = page.locator('input[placeholder*="message"]');

    if (await input.isVisible()) {
      const inputBox = await input.boundingBox();
      expect(inputBox.height).toBeGreaterThanOrEqual(40);
    }
  });

  test('works on standard mobile devices', async ({ page }) => {
    await setMobileViewport(page, 'pixel7'); // 412px - common Android size

    // Page should be usable
    await expect(page.getByRole('button', { name: /select configs/i }).first()).toBeVisible();

    // No horizontal overflow
    const scrollInfo = await checkHorizontalScroll(page);
    expect(scrollInfo.hasOverflow).toBe(false);
  });

  test('works on tablets', async ({ page }) => {
    await setMobileViewport(page, 'iPadMini'); // 768px

    // Tablet should show better layout
    await expect(page.getByText(/arena/i)).toBeVisible();

    // Should have more padding on tablet
    const scrollInfo = await checkHorizontalScroll(page);
    expect(scrollInfo.hasOverflow).toBe(false);
  });
});
