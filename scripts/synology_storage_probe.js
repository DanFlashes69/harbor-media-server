const { chromium } = require('C:/Users/tanne/AppData/Local/Temp/synology-playwright/node_modules/playwright-core');

async function clickIfVisible(page, selector) {
  const loc = page.locator(selector).first();
  if (!(await loc.count())) {
    return false;
  }
  try {
    if (await loc.isVisible()) {
      await loc.click({ timeout: 2000 });
      return true;
    }
  } catch {
    return false;
  }
  return false;
}

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: true,
    args: ['--ignore-certificate-errors'],
  });
  const page = await browser.newPage({ ignoreHTTPSErrors: true });
  const seen = new Set();

  page.on('requestfinished', async (req) => {
    try {
      const url = req.url();
      if (!url.includes('/webapi/entry.cgi') && !url.includes('/webapi/auth.cgi')) {
        return;
      }

      let payload = {};
      if (req.method() === 'GET') {
        payload = Object.fromEntries(new URL(url).searchParams.entries());
      } else {
        payload = Object.fromEntries(new URLSearchParams(req.postData() || '').entries());
      }

      const key = JSON.stringify({
        api: payload.api,
        method: payload.method,
        version: payload.version,
        action: payload.action,
        func: payload.func,
      });

      if (!seen.has(key)) {
        seen.add(key);
        console.log('REQ', key);
      }
    } catch {
      // best-effort request logging only
    }
  });

  await page.goto('http://synology.example.lan:5000/', { waitUntil: 'networkidle' });
  await page.locator('input[name="username"]').first().fill('harboradmin');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(1500);
  await page.locator('input[type="password"]').first().fill('change_me');
  await page.keyboard.press('Enter');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(5000);

  for (const selector of ['text=Later', 'text=Close', 'text=Not now', 'text=No, thanks', 'text=Skip']) {
    await clickIfVisible(page, selector);
  }
  await page.waitForTimeout(2000);

  for (const selector of ['#sds-launcher', '.desktop-menu-button', 'div[role="button"]']) {
    const loc = page.locator(selector).first();
    if (!(await loc.count())) {
      continue;
    }
    try {
      await loc.click({ timeout: 2000 });
      break;
    } catch {
      // keep trying other selectors
    }
  }

  await page.waitForTimeout(1500);
  for (const selector of ['text=Storage Manager', 'text=Storage']) {
    const loc = page.locator(selector).first();
    if (!(await loc.count())) {
      continue;
    }
    try {
      await loc.click({ timeout: 2000 });
      break;
    } catch {
      // try next selector
    }
  }

  await page.waitForTimeout(8000);
  for (const selector of ['text=Storage Pool 1', 'text=Volume 1']) {
    const loc = page.locator(selector).first();
    if (!(await loc.count())) {
      continue;
    }
    try {
      await loc.click({ timeout: 3000 });
      await page.waitForTimeout(2500);
    } catch {
      // continue probing
    }
  }

  const texts = await page.evaluate(() => {
    const out = [];
    for (const el of Array.from(document.querySelectorAll('button,[role="button"],[role="menuitem"],a,span,div,input'))) {
      const text = (el.innerText || el.value || '').trim();
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      if (
        text &&
        rect.width > 0 &&
        rect.height > 0 &&
        style.visibility !== 'hidden' &&
        style.display !== 'none'
      ) {
        out.push(text.replace(/\s+/g, ' '));
      }
    }
    return Array.from(new Set(out)).slice(0, 1000);
  });

  console.log('VISIBLE_START');
  for (const text of texts) {
    console.log(text);
  }
  console.log('VISIBLE_END');

  await browser.close();
})();

