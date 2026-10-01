/**
 * Mobile testing utilities and viewport configurations
 */

/**
 * Common mobile device viewports
 */
export const VIEWPORTS = {
  // Phones
  iPhoneSE: { width: 375, height: 667 },
  iPhone14: { width: 390, height: 844 },
  iPhone14ProMax: { width: 430, height: 932 },
  pixel7: { width: 412, height: 915 },
  galaxyS8: { width: 360, height: 740 },

  // Tablets
  iPadMini: { width: 768, height: 1024 },
  iPadPro11: { width: 834, height: 1194 },

  // Edge cases
  narrowPhone: { width: 320, height: 568 }, // iPhone 5/SE 1st gen
  landscapePhone: { width: 844, height: 390 }, // iPhone 14 landscape
};

/**
 * Set viewport to a specific mobile device
 * @param {Page} page - Playwright page object
 * @param {string|object} device - Device name from VIEWPORTS or custom viewport object
 */
export async function setMobileViewport(page, device) {
  const viewport = typeof device === 'string' ? VIEWPORTS[device] : device;
  if (!viewport) {
    throw new Error(`Unknown device: ${device}. Available: ${Object.keys(VIEWPORTS).join(', ')}`);
  }
  await page.setViewportSize(viewport);
}

/**
 * Check if all interactive elements meet minimum touch target size
 * @param {Page} page - Playwright page object
 * @param {number} minSize - Minimum size in pixels (default: 44px per Apple HIG)
 * @returns {Promise<Array>} Array of violations with element info
 */
export async function checkTouchTargets(page, minSize = 44) {
  const violations = await page.evaluate((min) => {
    const selectors = 'button, a, input, select, textarea, [role="button"], [role="link"], [onclick]';
    const elements = document.querySelectorAll(selectors);
    const found = [];

    elements.forEach((el) => {
      // Skip hidden elements
      if (el.offsetParent === null) return;

      const rect = el.getBoundingClientRect();
      if (rect.width < min || rect.height < min) {
        found.push({
          tag: el.tagName,
          id: el.id || null,
          classes: el.className || null,
          text: el.textContent?.trim().substring(0, 50) || null,
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        });
      }
    });

    return found;
  }, minSize);

  return violations;
}

/**
 * Check if page has horizontal scrolling (indicates layout overflow)
 * @param {Page} page - Playwright page object
 * @returns {Promise<object>} Object with scrollWidth, clientWidth, and hasOverflow
 */
export async function checkHorizontalScroll(page) {
  return await page.evaluate(() => {
    const body = document.body;
    const html = document.documentElement;

    return {
      scrollWidth: Math.max(body.scrollWidth, html.scrollWidth),
      clientWidth: Math.max(body.clientWidth, html.clientWidth),
      hasOverflow: Math.max(body.scrollWidth, html.scrollWidth) > Math.max(body.clientWidth, html.clientWidth) + 5, // 5px tolerance
    };
  });
}

/**
 * Wait for page to be stable (no animations, network idle)
 * @param {Page} page - Playwright page object
 */
export async function waitForStable(page) {
  await page.waitForLoadState('networkidle');
  // Wait a bit for animations to complete
  await page.waitForTimeout(300);
}

/**
 * Take a full page screenshot with a descriptive name
 * @param {Page} page - Playwright page object
 * @param {string} name - Screenshot name
 * @param {object} options - Additional screenshot options
 */
export async function takeFullScreenshot(page, name, options = {}) {
  await page.screenshot({
    path: `e2e/screenshots/${name}.png`,
    fullPage: true,
    ...options,
  });
}
