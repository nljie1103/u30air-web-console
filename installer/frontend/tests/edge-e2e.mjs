import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

// Unlike the existing simulated pywebview API test, this starts the actual
// Python loopback bridge and performs browser fetch() calls to its endpoints.
const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const python = process.env.AWD_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const pythonSource = [
  'from pathlib import Path',
  'import sys,time',
  "sys.path.insert(0, 'installer')",
  'from edge_host import start_edge_server',
  'class Bridge:',
  ' def environment(self): return {"version":"2.4.4","adb_found":True,"adb_path":"C:\\\\tools\\\\adb.exe"}',
  ' def list_devices(self): return [{"serial":"USB-REAL-BRIDGE","state":"device","detail":"USB"}]',
  ' def device_info(self,serial): return {"brand":"Google","model":"Bridge Test Device","android":"16","abi":"arm64-v8a","ips":["192.168.2.5"],"installed_version":"2.4.1"}',
  ' def list_apps(self,serial,system=False): return [{"name":"org.example.app","system":False,"disabled":False}]',
  ' def get_logs(self): return []',
  ' def clear_logs(self): return True',
  ' def check_release(self): return {"version":"2.4.4","notes":"test"}',
  'server,url=start_edge_server(Path("installer/frontend/dist"), Bridge())',
  'print(url,flush=True)',
  'time.sleep(90)',
].join('\n');

const proc = spawn(python, ['-u', '-c', pythonSource], {
  cwd: repo, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
});
let errors = '';
proc.stderr.on('data', data => { errors += String(data); });

const urlPromise = new Promise((yes, no) => {
  let buffer = '';
  const timeout = setTimeout(() => no(new Error('Bridge startup timed out: ' + errors)), 12000);
  proc.on('exit', code => { clearTimeout(timeout); no(new Error('Bridge failed: ' + code + ' ' + errors)); });
  proc.stdout.on('data', bytes => {
    buffer += String(bytes);
    const match = buffer.match(/http:\/\/127\.0\.0\.1:\d+\/index\.html/);
    if (match) { clearTimeout(timeout); yes(match[0]); }
  });
});

function findChromium() {
  const paths = [
    process.env.AWD_BROWSER_PATH,
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    '/usr/bin/chromium',
  ].filter(Boolean);
  return paths.find(path => existsSync(path));
}

let browser;
try {
  const url = await urlPromise;
  const executablePath = findChromium();
  if (!executablePath) throw new Error('Edge/Chromium executable missing');
  browser = await chromium.launch({ executablePath, headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const pageErrors = [];
  page.on('pageerror', e => pageErrors.push(e.message));
  await page.goto(url, { waitUntil: 'networkidle', timeout: 25000 });
  await page.locator('.app-root').waitFor();
  await page.locator('.startup-notice').waitFor({ state: 'hidden', timeout: 9000 });
  await page.getByText('Bridge Test Device', { exact: true }).first().waitFor({ timeout: 10000 });
  console.log('PASS real Python HTTP bridge with Vue init and ADB device info');

  const menu = page.getByRole('button', { name: '选择 Android 设备' });
  await menu.click();
  await page.getByRole('option', { name: /USB-REAL-BRIDGE/ }).waitFor();
  await page.keyboard.press('Escape');
  await page.locator('button.nav-item[title="应用管理"]').click();
  await page.getByText('org.example.app', { exact: true }).first().waitFor();
  console.log('PASS device picker, lazy app list and Python bridge');

  await page.locator('button.nav-item[title="运行日志"]').click();
  await page.getByRole('button', { name: /清空日志/ }).click();
  await page.locator('.inline-error').waitFor({ state: 'hidden' });
  await page.locator('button.nav-item[title="设置"]').click();
  assert.equal((await page.locator('.page-content h1').textContent()).trim(), '设置');
  assert.deepEqual(pageErrors, []);
  console.log('PASS native Edge host page switching and bridge actions');
  console.log('EDGE_BRIDGE_E2E_OK');
} finally {
  if (browser) await browser.close();
  proc.kill();
}
