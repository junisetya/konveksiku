// Catat semua request HTTP saat login untuk menemukan 401/404 yang bocor.
const puppeteer = require('puppeteer-core');
const BASE = process.env.BASE || 'http://127.0.0.1:8099';
const PW = process.env.ROFI_PW || '';
(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new', args: ['--no-sandbox'] });
  const page = await browser.newPage();
  const log = [];
  page.on('response', r => {
    const s = r.status();
    if (s >= 400) log.push(s + ' ' + r.request().method() + ' ' + r.url().replace(BASE, ''));
  });
  await page.setViewport({ width: 1440, height: 1000 });
  await page.goto(BASE + '/', { waitUntil: 'networkidle0' });
  await page.type('input[name=password]', PW);
  await Promise.all([page.click('#login-form button[type=submit]'),
    page.waitForSelector('.shell', { timeout: 20000 })]);
  await new Promise(r => setTimeout(r, 2000));
  const toast = await page.$eval('#toast', e => e.textContent).catch(() => '');
  await browser.close();
  console.log(JSON.stringify({ failed: log, toast }, null, 2));
})().catch(e => { console.error('GAGAL:', e.message); process.exit(1); });
