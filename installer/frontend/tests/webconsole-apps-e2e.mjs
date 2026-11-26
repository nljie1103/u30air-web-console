import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../../web-console/web');
const browserPaths = [
  process.env.AWD_BROWSER_PATH,
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/chromium',
];
const executablePath = browserPaths.find(path => path && existsSync(path));
if (!executablePath) throw new Error('No Chrome/Edge browser for website E2E');

const packages = [
  'com.v2ray.ang',
  'com.topjohnwu.magisk',
  'com.example.hidden',
];
const labels = new Map([
  ['com.v2ray.ang', { label: 'v2rayNG', hasIcon: true }],
  ['com.topjohnwu.magisk', { label: 'Magisk', hasIcon: true }],
  ['com.example.hidden', { label: 'com.example.hidden', hasIcon: false }],
]);
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==', 'base64');
const calls = [];

const server = createServer(async (req, res) => {
  const path = new URL(req.url, 'http://localhost');
  const respond = (code, body, mime = 'application/json') => {
    res.writeHead(code, { 'Content-Type': mime, 'Cache-Control': 'no-store' });
    res.end(Buffer.isBuffer(body) ? body : (typeof body === 'string' ? body : JSON.stringify(body)));
  };
  if (path.pathname === '/assets/app.css') return respond(200, readFileSync(join(root, 'app.css')), 'text/css');
  if (path.pathname === '/assets/app.js') return respond(200, readFileSync(join(root, 'app.js')), 'text/javascript');
  if (path.pathname === '/') return respond(200, readFileSync(join(root, 'index.html')), 'text/html');
  if (path.pathname === '/api/status') return respond(200, { version: '2.4.1', manufacturer: 'ZTE', model: 'U30 Air', android: '13', abi: 'arm64-v8a' });
  if (path.pathname === '/api/apps') return respond(200, { packages });
  if (path.pathname === '/api/app-info') {
    const pkg = path.searchParams.get('package');
    return respond(200, { package: pkg, ...(labels.get(pkg) || { label: pkg, hasIcon: false }) });
  }
  if (path.pathname === '/api/app-icon') return respond(200, png, 'image/png');
  if (path.pathname === '/api/screen') return respond(200, png, 'image/png');
  if (path.pathname === '/api/control') {
    let body = '';
    for await (const chunk of req) body += chunk;
    const command = JSON.parse(body);
    calls.push(command);
    if (command.package === 'com.example.hidden') {
      return respond(503, { error: '应用没有可用的桌面启动入口（后台组件）' });
    }
    return respond(200, { status: 'sent' });
  }
  return respond(404, { error: 'not found' });
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
try {
  browser = await chromium.launch({ executablePath, headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1300, height: 900 } });
  const exceptions = [];
  page.on('pageerror', error => exceptions.push(error.message));
  await page.goto('http://127.0.0.1:' + server.address().port + '/', { waitUntil: 'domcontentloaded' });
  await page.getByText('v2rayNG', { exact: true }).waitFor({ timeout: 10000 });
  await page.getByText('Magisk', { exact: true }).waitFor();
  assert.equal(await page.locator('.app-item').count(), 3, 'All installed packages remain visible');
  assert.equal(await page.locator('.app-item .app-icon').count(), 2, 'Real icon images should be rendered');
  await page.getByText('com.v2ray.ang', { exact: true }).waitFor();
  console.log('PASS labels, icons, package identifiers and fallback render');

  await page.locator('#searchApps').fill('v2rayNG');
  assert.equal(await page.locator('.app-item').count(), 1, 'Search should match app labels');
  await page.locator('.app-item').click();
  await page.waitForFunction(() => document.querySelector('#toast')?.textContent?.includes('v2rayNG'));
  assert(calls.some(c => c.action === 'launch' && c.package === 'com.v2ray.ang'), 'Launch must send correct package');
  console.log('PASS label search and application launch action');

  await page.locator('#searchApps').fill('com.example.hidden');
  assert.equal(await page.locator('.app-item').count(), 1);
  await page.locator('.app-item').click();
  await page.waitForFunction(() => document.querySelector('#toast')?.textContent?.includes('没有可用的桌面启动入口'));
  assert.deepEqual(exceptions, [], 'Frontend script must remain stable on application launch errors');
  console.log('PASS backend permission/launcher errors remain readable and do not break UI');
  console.log('ANDROID_WEB_APPS_E2E_OK');
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
