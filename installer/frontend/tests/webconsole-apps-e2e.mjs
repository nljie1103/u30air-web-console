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
  if (path.pathname === '/api/novnc/status') return respond(200, {
    available: false, url: '', reason: '5800 端口未提供 noVNC 服务，设备上尚未部署独立 VNC 服务与网页代理'
  });
  if (path.pathname === '/api/control') {
    let body = '';
    for await (const chunk of req) body += chunk;
    const command = JSON.parse(body);
    calls.push(command);
    if ((command.action === 'reboot' && command.confirm !== '重启') ||
        (command.action === 'shutdown' && command.confirm !== '关机')) {
      return respond(400, { error: '必须输入确认内容' });
    }
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
  await page.locator('#vncStatus').getByText('5800 端口未提供 noVNC 服务', { exact: false }).waitFor();
  assert.equal(await page.locator('#vncLink').isVisible(), false,
    'noVNC link must be hidden when no server is installed');
  console.log('PASS optional noVNC correctly reports missing 5800 server, no dead link');

  await page.locator('button[data-action="wake"]').click();
  await page.locator('button[data-action="screenoff"]').click();
  assert(calls.some(c => c.action === 'wake'));
  assert(calls.some(c => c.action === 'screenoff'));
  await page.locator('button[data-swipe="up"]').click();
  await page.locator('button[data-swipe="down"]').click();
  await page.locator('button[data-swipe="left"]').click();
  await page.locator('button[data-swipe="right"]').click();
  const swipes = calls.filter(c => c.action === 'swipe');
  assert.equal(swipes.length, 4);
  assert(swipes[0].y > swipes[0].y2, 'up swipe should move toward top');
  assert(swipes[1].y < swipes[1].y2, 'down swipe should move toward bottom');
  assert(swipes[2].x > swipes[2].x2, 'left swipe should move toward left');
  assert(swipes[3].x < swipes[3].x2, 'right swipe should move toward right');
  console.log('PASS wake, screen sleep, all directional swipe button actions');

  // Browser confirmation is required even if the backend also validates
  // the exact requested word. The mock never reboots real hardware.
  page.once('dialog', async dialog => {
    assert.equal(dialog.type(), 'prompt');
    await dialog.accept('wrong');
  });
  await page.locator('#shutdownDevice').click();
  assert.equal(calls.filter(c => c.action === 'shutdown').length, 0);
  page.once('dialog', async dialog => {
    assert.equal(dialog.type(), 'prompt');
    await dialog.accept('重启');
  });
  await page.locator('#rebootDevice').click();
  await page.waitForFunction(() => document.querySelector('#toast')?.textContent?.includes('已发送重启'));
  assert(calls.some(c => c.action === 'reboot' && c.confirm === '重启'));
  console.log('PASS power controls require explicit Chinese confirmation text');

  assert.deepEqual(exceptions, [], 'Frontend script must stay error-free');
  console.log('ANDROID_WEB_APPS_E2E_OK');
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
