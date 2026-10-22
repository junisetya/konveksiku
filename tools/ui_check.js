// Uji UI nyata di Chrome headless: login, buka dashboard, cek error console,
// ambil screenshot desktop + mobile, dan cek overflow horizontal.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE || 'http://127.0.0.1:8099';
const PW = process.env.ROFI_PW || '';
const OUT = path.join(__dirname, '..', 'preview');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const errors = [];
  const page = await browser.newPage();
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('requestfailed', r => errors.push('requestfailed: ' + r.url()));

  await page.setViewport({ width: 1440, height: 1000 });
  await page.goto(BASE + '/', { waitUntil: 'networkidle0' });
  await page.screenshot({ path: path.join(OUT, 'ui-login.png') });

  await page.type('input[name=password]', PW);
  await Promise.all([
    page.click('#login-form button[type=submit]'),
    page.waitForSelector('.shell', { timeout: 20000 }),
  ]);
  await new Promise(r => setTimeout(r, 1200));
  const stats = await page.$$eval('.stat .n', els => els.map(e => e.textContent));
  const rows = await page.$$eval('tbody tr', els => els.length);
  const overflowDesktop = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  await page.screenshot({ path: path.join(OUT, 'ui-dashboard.png'), fullPage: false });

  // Buka detail pesanan pertama lewat tombol Detail.
  let detail = null;
  const detailBtn = await page.$('button[data-open]');
  if (detailBtn) {
    await detailBtn.click();
    await page.waitForSelector('.tabs', { timeout: 15000 });
    await new Promise(r => setTimeout(r, 800));
    await page.screenshot({ path: path.join(OUT, 'ui-detail.png') });
    // Tab Tahapan produksi
    const tabs = await page.$$('.tabs button');
    if (tabs[2]) {
      await tabs[2].click();
      await new Promise(r => setTimeout(r, 800));
      await page.screenshot({ path: path.join(OUT, 'ui-produksi.png') });
    }
    detail = await page.$eval('.head h1', e => e.textContent);
  }

  // Mobile
  await page.setViewport({ width: 390, height: 844, isMobile: true });
  await page.goto(BASE + '/', { waitUntil: 'networkidle0' });
  await new Promise(r => setTimeout(r, 1500));
  const overflowMobile = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  await page.screenshot({ path: path.join(OUT, 'ui-mobile.png'), fullPage: false });

  await browser.close();
  const report = { stats, rows, detail, overflowDesktop, overflowMobile, errors };
  fs.writeFileSync(path.join(OUT, 'ui-check.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
})().catch(e => { console.error('GAGAL:', e.message); process.exit(1); });
