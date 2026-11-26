import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright-core';

// Windows integration: packaged EXE -> native Edge app window -> interactive
// title-bar drag -> live Vue DOM and real Python-bridge response over CDP.
if (process.platform !== 'win32') throw new Error('Windows drag integration test only');

const exe = resolve(process.env.AWD_EXE_PATH || 'dist/AndroidWebDesktopManager/AndroidWebDesktopManager.exe');
if (!existsSync(exe)) throw new Error('Portable EXE missing: ' + exe);
const folder = mkdtempSync(join(tmpdir(), 'awd-window-drag-'));
const metadata = join(folder, 'smoke.json');
const doneFile = join(folder, 'finished');
const proc = spawn(exe, ['--gui-smoke-test'], {
  env: { ...process.env, AWD_SMOKE_INFO: metadata, AWD_SMOKE_DONE: doneFile, AWD_SMOKE_HOLD: '30' },
  windowsHide: false,
});
let exitCode = undefined;
proc.once('exit', code => { exitCode = code; });

async function waitUntil(predicate, timeoutMs, message) {
  const cutoff = Date.now() + timeoutMs;
  while (Date.now() < cutoff) {
    if (exitCode !== undefined) throw new Error('Packaged EXE exited early: ' + exitCode);
    const result = await predicate();
    if (result) return result;
    await sleep(180);
  }
  throw new Error(message);
}

let browser;
try {
  const data = await waitUntil(
    () => existsSync(metadata) ? JSON.parse(readFileSync(metadata, 'utf8')) : null,
    17000, 'No smoke metadata from packaged EXE',
  );
  const portFile = join(data.profile, 'DevToolsActivePort');
  const port = await waitUntil(
    () => existsSync(portFile) ? Number(readFileSync(portFile, 'utf8').split('\n')[0]) : null,
    17000, 'Edge did not expose its localhost CDP debugging port',
  );
  assert(Number.isSafeInteger(port) && port > 1024);
  browser = await chromium.connectOverCDP('http://127.0.0.1:' + port, { timeout: 11000 });
  const page = await waitUntil(() => {
    const pages = browser.contexts().flatMap(context => context.pages());
    return pages.find(p => p.url().includes('127.0.0.1')) || null;
  }, 9000, 'Edge native app page not found');

  await page.locator('.app-root').waitFor({ state: 'visible', timeout: 12000 });
  await page.locator('.startup-notice').waitFor({ state: 'hidden', timeout: 10000 });
  const v = await page.evaluate(async () => {
    const api = window.pywebview?.api;
    if (!api) throw new Error('Live Python bridge missing');
    return await api.environment();
  });
  assert.equal(v.version, '2.4.0');
  console.log('PASS packaged Edge window rendered Vue and Python bridge');

  // The EXE itself is moving the real HWND, including an actual title-bar
  // left-button drag. Check UI AFTER the drag is complete.
  await waitUntil(() => {
    try {
      return existsSync(metadata) && JSON.parse(readFileSync(metadata, 'utf8')).drag_complete;
    } catch { return false; }
  }, 17500, 'Edge app window did not finish its interactive mouse drag');
  assert.equal(exitCode, undefined, 'Packaged EXE terminated on window drag');
  await page.locator('button.nav-item[title="设置"]').click({ timeout: 9000 });
  assert.equal((await page.locator('.page-content h1').textContent()).trim(), '设置');
  await page.locator('button.nav-item[title="工作台"]').click({ timeout: 9000 });
  assert.equal((await page.locator('.page-content h1').textContent()).trim(), '工作台');
  const postMove = await page.evaluate(async () => await window.pywebview.api.environment());
  assert.equal(postMove.version, '2.4.0');
  console.log('PASS actual Windows HWND reposition + mouse drag + responsive Vue/Python after moving');
  console.log('WINDOW_DRAG_INTEGRATION_OK');
} finally {
  if (browser) await browser.close().catch(() => {});
  writeFileSync(doneFile, 'complete');
  const cutoff = Date.now() + 9000;
  while (exitCode === undefined && Date.now() < cutoff) await sleep(180);
  if (exitCode === undefined) proc.kill('SIGTERM');
  rmSync(folder, { recursive: true, force: true });
}
if (exitCode !== 0) throw new Error('Packaged EXE did not exit successfully: ' + exitCode);
