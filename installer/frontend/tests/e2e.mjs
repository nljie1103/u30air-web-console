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
        environment: track('environment', { version: '2.4.2', adb_found: true, adb_path: 'C:\\tools\\adb.exe' }),
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
  // Regression: on a cold WebView2 launch, window.pywebview.api can exist
  // before pywebview injects all its callable methods.
  const delayedPage = await browser.newPage({ viewport: { width: 1300, height: 820 } });
  const coldErrors = [];
  delayedPage.on('pageerror', e => coldErrors.push(e.message));
  await delayedPage.addInitScript(() => {
    window.pywebview = { api: {} };
    setTimeout(() => {
      Object.assign(window.pywebview.api, {
        environment: async () => ({ version: '2.4.2', adb_found: true, adb_path: 'C:\\tools\\adb.exe' }),
        list_devices: async () => [{ serial: 'USB-DELAYED', state: 'device' }],
        get_logs: async () => [],
        device_info: async () => ({ brand: 'Google', model: 'Delayed Mock', android: '16', ips: [], installed_version: null }),
      });
    }, 1100);
  });
  await delayedPage.goto(url, { waitUntil: 'domcontentloaded', timeout: 25000 });
  await delayedPage.locator('.startup-notice').waitFor({ state: 'visible' });
  assert.equal(await delayedPage.locator('.inline-error').count(), 0, 'Partial API must not produce red TypeError');
  await delayedPage.locator('button.nav-item[title="设置"]').click();
  assert.equal((await delayedPage.locator('.page-content h1').textContent()).trim(), '设置');
  await delayedPage.locator('.startup-notice').waitFor({ state: 'hidden', timeout: 8000 });
  await delayedPage.locator('button.nav-item[title="工作台"]').click();
  await delayedPage.getByText('Delayed Mock', { exact: true }).first().waitFor({ state: 'visible', timeout: 10000 });
  assert.equal(await delayedPage.locator('.inline-error').count(), 0);
  assert.deepEqual(coldErrors, [], 'Partial bridge injection must not cause unhandled JS exceptions');
  console.log('PASS cold-launch partial API injection, retry and navigation');
  await delayedPage.close();

  // Regression: environment() can fail once during bridge initialization.
  const transientPage = await browser.newPage({ viewport: { width: 1300, height: 820 } });
  const transientErrors = [];
  transientPage.on('pageerror', e => transientErrors.push(e.message));
  await transientPage.addInitScript(() => {
    let calls = 0;
    window.pywebview = { api: {
      environment: async () => {
        if (++calls === 1) throw new Error('temporary initialization error');
        return { version: '2.4.2', adb_found: false, adb_path: '' };
      },
      list_devices: async () => [],
      get_logs: async () => [],
    }};
    window.__getInitCalls = () => calls;
  });
  await transientPage.goto(url, { waitUntil: 'domcontentloaded' });
  await transientPage.locator('.startup-notice').waitFor({ state: 'hidden', timeout: 8000 });
  assert((await transientPage.evaluate(() => window.__getInitCalls())) >= 2, 'Environment should be retried');
  assert.equal(await transientPage.locator('.inline-error').count(), 0, 'Transient startup error must not be fatal');
  assert.deepEqual(transientErrors, []);
  console.log('PASS transient environment failure, self-recovery');
  await transientPage.close();

  // ADB can take several seconds, but UI navigation must be independent.
  const slowPage = await browser.newPage({ viewport: { width: 1300, height: 820 } });
  await slowPage.addInitScript(() => {
    window.pywebview = { api: {
      environment: async () => ({ version: '2.4.2', adb_found: true, adb_path: 'C:\\tools\\adb.exe' }),
      get_logs: async () => [],
      list_devices: async () => new Promise(resolve => setTimeout(() => resolve([{ serial: 'SLOW-ADB', state: 'device' }]), 2600)),
      device_info: async () => new Promise(resolve => setTimeout(() => resolve({ brand: 'Mock', model: 'Slow USB', android: '14', ips: [] }), 1200)),
    }};
  });
  await slowPage.goto(url, { waitUntil: 'domcontentloaded' });
  await slowPage.locator('.startup-notice').waitFor({ state: 'hidden', timeout: 5000 });
  const navStart = Date.now();
  for (const label of ['设备管理', '应用管理', '部署与更新', '运行日志', '设置']) {
    await slowPage.locator('button.nav-item[title="' + label + '"]').click();
    assert.equal((await slowPage.locator('.page-content h1').textContent()).trim(), label);
  }
  assert(Date.now() - navStart < 1500, 'Multiple page switches must not wait for long ADB calls');
  await slowPage.locator('button.nav-item[title="工作台"]').click();
  await slowPage.getByText('Slow USB', { exact: true }).first().waitFor({ state: 'visible', timeout: 10000 });
  assert.equal(await slowPage.locator('.inline-error').count(), 0);
  console.log('PASS slow ADB scan leaves navigation responsive');
  await slowPage.close();

  // An unavailable backend method must fail with an actionable description,
  // never a minified "x(...)[i] is not a function" crash.
  const missingPage = await browser.newPage({ viewport: { width: 1300, height: 820 } });
  await missingPage.addInitScript(() => {
    window.pywebview = { api: {
      environment: async () => ({ version: '2.4.2', adb_found: false, adb_path: '' }),
      list_devices: async () => [], get_logs: async () => [],
    }};
  });
  await missingPage.goto(url, { waitUntil: 'domcontentloaded' });
  await missingPage.locator('.startup-notice').waitFor({ state: 'hidden', timeout: 5000 });
  await missingPage.locator('button.nav-item[title="设置"]').click();
  await missingPage.getByRole('button', { name: '选择 adb.exe' }).click();
  await missingPage.locator('.inline-error').getByText('尚未就绪', { exact: false }).waitFor({ state: 'visible' });
  const msg = await missingPage.locator('.inline-error').innerText();
  assert(!msg.includes('is not a function'), 'No raw JS TypeError should reach UI');
  await missingPage.locator('button.nav-item[title="工作台"]').click();
  assert.equal((await missingPage.locator('.page-content h1').textContent()).trim(), '工作台');
  console.log('PASS incomplete backend API reports readable error without freezing navigation');
  await missingPage.close();

  // The native environment() Promise may never settle on a broken first
  // attempt. The handshake must time out and recover automatically.
  const hangingPage = await browser.newPage({ viewport: { width: 1300, height: 820 } });
  const hangingErrors = [];
  hangingPage.on('pageerror', e => hangingErrors.push(e.message));
  await hangingPage.addInitScript(() => {
    let calls = 0;
    window.pywebview = { api: {
      environment: () => {
        if (++calls === 1) return new Promise(() => {});
        return Promise.resolve({ version: '2.4.2', adb_found: false, adb_path: '' });
      },
      list_devices: async () => [],
      get_logs: async () => [],
    }};
    window.__handshakeCalls = () => calls;
  });
  await hangingPage.goto(url, { waitUntil: 'domcontentloaded' });
  await hangingPage.locator('.startup-notice').waitFor({ state: 'visible' });
  await hangingPage.locator('button.nav-item[title="部署与更新"]').click();
  assert.equal((await hangingPage.locator('.page-content h1').textContent()).trim(), '部署与更新');
  await hangingPage.locator('.startup-notice').waitFor({ state: 'hidden', timeout: 10000 });
  assert((await hangingPage.evaluate(() => window.__handshakeCalls())) >= 2, 'Hung handshake must be retried');
  assert.equal(await hangingPage.locator('.inline-error').count(), 0);
  assert.deepEqual(hangingErrors, []);
  console.log('PASS hung first bridge call times out and retries without freezing UI');
  await hangingPage.close();

  // Regression: cellular 10.x addresses must not be recommended for U30
  // hotspot management. Expose the current old daemon binding separately.
  const networkPage = await browser.newPage({ viewport: { width: 1350, height: 900 } });
  const networkErrors = [];
  networkPage.on('pageerror', e => networkErrors.push(e.message));
  await networkPage.addInitScript(() => {
    window.pywebview = { api: {
      environment: async () => ({ version: '2.4.2', adb_found: true, adb_path: 'C:\\\\tools\\\\adb.exe' }),
      list_devices: async () => [{ serial: 'U30-TEST', state: 'device' }],
      device_info: async () => ({
        brand: 'ZTE', model: 'U30 Air', android: '13',
        installed_version: '2.4.2', ips: ['192.168.0.1', '10.10.14.1'],
        preferred_ip: '192.168.0.1',
        suggested_ip: '192.168.0.1',
        listening_address: '10.129.230.33:8765',
        network_addresses: [
          { ip: '192.168.0.1', interface: 'br0', role: '热点/局域网' },
          { ip: '10.10.14.1', interface: 'rndis0', role: 'USB 网络' },
          { ip: '10.129.230.33', interface: 'rmnet_data0', role: '蜂窝/隧道' },
        ],
      }),
      get_logs: async () => [],
    }};
  });
  await networkPage.goto(url, { waitUntil: 'domcontentloaded' });
  await networkPage.locator('.startup-notice').waitFor({ state: 'hidden', timeout: 7000 });
  await networkPage.locator('button.nav-item[title="部署与更新"]').click();
  assert.equal(await networkPage.locator('#ipField').inputValue(), '192.168.0.1');
  const options = networkPage.locator('.network-option');
  assert.equal(await options.count(), 2, 'Cellular IP must not be a deployment shortcut');
  assert((await networkPage.locator('.network-warn').allInnerTexts()).some(x => x.includes('10.129.230.33')));
  assert((await networkPage.locator('.page-content').innerText()).includes('当前运行服务监听'));
  await options.filter({ hasText: '10.10.14.1' }).click();
  assert.equal(await networkPage.locator('#ipField').inputValue(), '10.10.14.1');
  assert.deepEqual(networkErrors, []);
  console.log('PASS fixed hotspot gateway preference, cellular exclusion and listener migration warning');
  await networkPage.close();
  console.log('BROWSER_E2E_OK');
} finally {
  if (browser) await browser.close();
  proc.kill();
}
