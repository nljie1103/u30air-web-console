import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const python = process.env.AWD_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const pythonCode = [
  "from pathlib import Path",
  "import sys, time",
  "sys.path.insert(0, 'installer')",
  "from local_server import start_frontend_server",
  "server, url = start_frontend_server(Path('installer/frontend/dist'))",
  "print(url, flush=True)",
  "time.sleep(100)",
].join('\n');

const proc = spawn(python, ['-u', '-c', pythonCode], {
  cwd: repo, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
});

let serverStderr = '';
proc.stderr.on('data', chunk => { serverStderr += String(chunk); });

function waitForUrl() {
  return new Promise((yes, no) => {
    let buffer = '';
    const timeout = setTimeout(() => no(new Error('Frontend server did not start: ' + serverStderr)), 12000);
    proc.on('exit', code => { clearTimeout(timeout); no(new Error('Frontend server exited: ' + code + ' ' + serverStderr)); });
    proc.stdout.on('data', chunk => {
      buffer += String(chunk);
      const match = buffer.match(/http:\/\/127\.0\.0\.1:\d+\/index\.html/);
      if (match) { clearTimeout(timeout); yes(match[0]); }
    });
  });
}

function browserPath() {
  const choices = [
    process.env.AWD_BROWSER_PATH,
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    '/usr/bin/chromium',
  ].filter(Boolean);
  return choices.find(path => existsSync(path));
}

let browser;
try {
  const url = await waitForUrl();
  const executablePath = browserPath();
  if (!executablePath) throw new Error('No Edge or Chromium executable available for browser tests');
  browser = await chromium.launch({
    headless: true, executablePath,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage({ viewport: { width: 1380, height: 900 } });
  const failures = [];
  page.on('pageerror', e => failures.push(e.message));
  await page.addInitScript(() => {
    window.__mockCalls = [];
    const track = (name, response) => async (...args) => {
      window.__mockCalls.push({ name, args });
      return response;
    };
    window.pywebview = {
      api: {
        environment: track('environment', { version: '2.3.0', adb_found: true, adb_path: 'C:\\tools\\adb.exe' }),
        list_devices: track('list_devices', [
          { serial: 'USB-TEST-001', state: 'device', detail: 'mock device' },
          { serial: '192.168.1.28:5555', state: 'offline', detail: 'unreachable' },
        ]),
        device_info: track('device_info', {
          brand: 'Google', model: 'Pixel Test', android: '16', abi: 'arm64-v8a',
          installed_version: '2.2.2', ips: ['192.168.1.20'], build: 'TEST-BUILD',
        }),
        list_apps: track('list_apps', [
          { name: 'com.example.one', system: false, disabled: false },
          { name: 'org.sample.two', system: false, disabled: false },
        ]),
        get_logs: track('get_logs', []),
        clear_logs: track('clear_logs', true),
        check_release: track('check_release', { version: '2.2.3', notes: '浏览器端到端测试更新说明' }),
      },
    };
  });

  await page.goto(url, { waitUntil: 'networkidle', timeout: 25000 });
  await page.locator('.app-root').waitFor({ state: 'visible', timeout: 12000 });
  assert.equal(await page.locator('button.nav-item').count(), 6, 'Six navigation items required');
  await page.getByText('Pixel Test', { exact: true }).first().waitFor({ state: 'visible', timeout: 12000 });
  const initialCalls = await page.evaluate(() => window.__mockCalls.map(c => c.name));
  assert(!initialCalls.includes('list_apps'), 'App listing must not block startup');
  console.log('PASS lazy application loading on startup');

  const trigger = page.getByRole('button', { name: '选择 Android 设备' });
  await trigger.click();
  const picker = page.locator('.device-dropdown');
  await picker.waitFor({ state: 'visible' });
  assert.equal(await picker.locator('.device-option').count(), 2, 'Device selector must render all detected devices');
  assert.equal(await picker.locator('.device-option:disabled').count(), 1, 'Offline devices must be shown but not selectable');
  const popup = await picker.evaluate(el => {
    const r = el.getBoundingClientRect(); const styles = getComputedStyle(el);
    return { visible: r.width > 200 && r.height > 70, withinViewport: r.right <= innerWidth && r.left >= 0,
             positioned: styles.position, background: styles.backgroundColor };
  });
  assert(popup.visible && popup.withinViewport, 'Styled dropdown must be visible and inside the viewport');
  assert.equal(popup.positioned, 'absolute', 'Dropdown should render as a styled overlay');
  await picker.getByRole('textbox', { name: '搜索设备序列号' }).fill('USB-TEST');
  assert.equal(await picker.locator('.device-option').count(), 1, 'Device selector must support search');
  await picker.getByRole('textbox', { name: '搜索设备序列号' }).press('Escape');
  await picker.waitFor({ state: 'hidden' });
  console.log('PASS styled device selector, search, offline state and escape key');

  const before = await page.locator('.app-root').evaluate(el => el.classList.contains('sidebar-closed'));
  await page.locator('.sidebar-toggle').click();
  await page.waitForFunction(value => document.querySelector('.app-root')?.classList.contains('sidebar-closed') !== value, before);
  console.log('PASS sidebar collapses and expands');

  await page.locator('button.nav-item[title="应用管理"]').click();
  assert.equal((await page.locator('.page-content h1').textContent()).trim(), '应用管理');
  await page.locator('.status-segments').getByRole('button', { name: '已停用' }).click();
  assert.equal(await page.locator('.data-table tbody tr').count(), 0);
  await page.locator('.status-segments').getByRole('button', { name: '全部' }).click();
  await page.locator('.search-input input').fill('com.example.one');
  await page.waitForTimeout(150);
  assert.equal(await page.locator('.data-table tbody tr').count(), 1);
  console.log('PASS app list and search');

  await page.locator('button.nav-item[title="运行日志"]').click();
  await page.getByRole('button', { name: /清空日志/ }).click();
  await page.waitForFunction(() => window.__mockCalls.some(c => c.name === 'clear_logs'));
  console.log('PASS backend log clearing action');

  await page.locator('button.nav-item[title="部署与更新"]').click();
  assert.equal((await page.locator('.page-content h1').textContent()).trim(), '部署与更新');
  await page.getByRole('button', { name: /检查新版本/ }).click();
  await page.getByText('v2.2.3', { exact: true }).waitFor({ state: 'visible' });
  const calls = await page.evaluate(() => window.__mockCalls.map(c => c.name));
  for (const name of ['environment', 'list_devices', 'device_info', 'list_apps', 'check_release', 'clear_logs']) {
    assert(calls.includes(name), 'UI did not call API ' + name);
  }
  assert.deepEqual(failures, [], 'Unexpected frontend JavaScript exception');
  console.log('PASS Vue DOM navigation and mocked Python API contract');
  console.log('BROWSER_E2E_OK');
} finally {
  if (browser) await browser.close();
  proc.kill();
}
