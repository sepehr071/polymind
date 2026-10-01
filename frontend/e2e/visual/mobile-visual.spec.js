import { test, expect } from '@playwright/test';
import { VIEWPORTS, setMobileViewport, waitForStable } from '../fixtures/mobile.fixture.js';

/**
 * Visual regression tests for mobile responsiveness
 * These tests take screenshots and compare them to baselines
 */
test.describe('Mobile Visual Regression', () => {
  test.beforeEach(async ({ page }) => {
    // Login
    await page.goto('/login');
    await page.fill('input[type="email"]', 'admin@admin.com');
    await page.fill('input[type="password"]', 'admin123');
    await page.click('button[type="submit"]');
    await page.waitForURL('/chat', { timeout: 10000 });
  });

  // Focus on modern devices (390px+) - very small devices (<390px) are uncommon now
  const devices = [
    { name: 'iPhone14', label: 'iPhone-14-390px' },
    { name: 'pixel7', label: 'Pixel-7-412px' },
  ];

  for (const device of devices) {
    test(`workflow page - ${device.label}`, async ({ page }) => {
      await setMobileViewport(page, device.name);
      await page.goto('/workflow');
      await waitForStable(page);

      await expect(page).toHaveScreenshot(`workflow-${device.label}.png`, {
        maxDiffPixelRatio: 0.05,
        animations: 'disabled',
      });
    });

    test(`arena page - ${device.label}`, async ({ page }) => {
      await setMobileViewport(page, device.name);
      await page.goto('/arena');
      await waitForStable(page);

      await expect(page).toHaveScreenshot(`arena-${device.label}.png`, {
        maxDiffPixelRatio: 0.05,
        animations: 'disabled',
      });
    });

    test(`chat page - ${device.label}`, async ({ page }) => {
      await setMobileViewport(page, device.name);
      await page.goto('/chat');
      await waitForStable(page);

      await expect(page).toHaveScreenshot(`chat-${device.label}.png`, {
        maxDiffPixelRatio: 0.05,
        animations: 'disabled',
      });
    });
  }

  test('workflow sidebar open on mobile - iPhone 14', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');
    await page.goto('/workflow');
    await waitForStable(page);

    // Open sidebar
    await page.locator('[data-testid="workflow-menu-button"]').click();
    await page.waitForTimeout(400); // Wait for animation

    await expect(page).toHaveScreenshot('workflow-sidebar-open-iPhone-14.png', {
      maxDiffPixelRatio: 0.05,
      animations: 'disabled',
    });
  });

  test('workflow toolbar overflow menu - iPhone 14', async ({ page }) => {
    await setMobileViewport(page, 'iPhone14');
    await page.goto('/workflow');
    await waitForStable(page);

    // Open overflow menu
    await page.locator('[data-testid="toolbar-overflow-menu"]').click();
    await page.waitForTimeout(200);

    await expect(page).toHaveScreenshot('workflow-overflow-menu-iPhone-14.png', {
      maxDiffPixelRatio: 0.05,
      animations: 'disabled',
    });
  });

  test('landscape orientation - iPhone 14', async ({ page }) => {
    await setMobileViewport(page, 'landscapePhone'); // 844x390
    await page.goto('/workflow');
    await waitForStable(page);

    await expect(page).toHaveScreenshot('workflow-landscape-iPhone-14.png', {
      maxDiffPixelRatio: 0.05,
      animations: 'disabled',
    });
  });

  test('tablet view - iPad Mini', async ({ page }) => {
    await setMobileViewport(page, 'iPadMini'); // 768px
    await page.goto('/workflow');
    await waitForStable(page);

    await expect(page).toHaveScreenshot('workflow-iPad-Mini.png', {
      maxDiffPixelRatio: 0.05,
      animations: 'disabled',
      fullPage: true,
    });
  });
});
