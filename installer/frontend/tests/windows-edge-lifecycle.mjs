import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright-core';

// Packaged Windows EXE, normal app lifecycle, not the one-off GUI smoke loop.
// Starts and closes the real Edge window twice in succession.
if (process.platform !== 'win32') throw new Error('Windows-only lifecycle test');

const expectedVersion = JSON.parse(readFileSync(resolve('installer/frontend/package.json'), 'utf8')).version;
const exe = resolve(process.env.AWD_EXE_PATH || 'dist/AndroidWebDesktopManager/AndroidWebDesktopManager.exe');
if (!existsSync(exe)) throw new Error('Packaged EXE missing: ' + exe);
const root = mkdtempSync(join(tmpdir(), 'awd-lifecycle-'));

async function awaitValue(getter, timeout, message) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await getter();
    if (value) return value;
    await sleep(175);
  }
  throw new Error(message);
}

async function runCycle(n) {
  const infoPath = join(root, 'startup-' + n + '.json');
  const child = spawn(exe, ['--lifecycle-smoke-test'], {
    windowsHide: false,
    stdio: 'ignore',
    env: { ...process.env, AWD_SMOKE_INFO: infoPath },
  });
  let exitCode;
  child.once('exit', code => { exitCode = code; });
  let browser;
  let page;
  try {
    const info = await awaitValue(() => {
      if (!existsSync(infoPath)) return null;
      try { return JSON.parse(readFileSync(infoPath, 'utf8')); }
      catch { return null; }
    }, 22000, 'Cycle ' + n + ': no startup metadata');
    const debuggingFile = join(info.profile, 'DevToolsActivePort');
    const port = await awaitValue(() => {
      if (!existsSync(debuggingFile)) return null;
      const value = Number(readFileSync(debuggingFile, 'utf8').split('\n')[0]);
      return value > 1024 ? value : null;
    }, 18000, 'Cycle ' + n + ': Edge browser did not start');
    browser = await chromium.connectOverCDP('http://127.0.0.1:' + port);
    page = await awaitValue(() => {
      const pages = browser.contexts().flatMap(c => c.pages());
      return pages.find(p => p.url().includes('127.0.0.1')) || null;
    }, 12000, 'Cycle ' + n + ': Edge localhost window not created');
    // If the backend dies when the Edge launcher exits, the page never
    // renders and the next two operations fail.
    await page.locator('.app-root').waitFor({ timeout: 16000 });
    await page.locator('.startup-notice').waitFor({ state: 'hidden', timeout: 13000 });
    await awaitValue(() => {
      try {
        return existsSync(infoPath) && JSON.parse(readFileSync(infoPath, 'utf8')).window_ready;
      } catch { return false; }
    }, 16000, 'Cycle ' + n + ': native Edge window not tracked');
    const first = await page.evaluate(() => window.pywebview?.api?.environment());
    assert.equal(first.version, expectedVersion);
    await page.locator('button.nav-item[title="设置"]').click();
    assert.equal((await page.locator('.page-content h1').textContent()).trim(), '设置');
    await page.locator('button.nav-item[title="工作台"]').click();
    assert.equal((await page.locator('.page-content h1').textContent()).trim(), '工作台');
    const last = await page.evaluate(() => window.pywebview?.api?.environment());
    assert.equal(last.version, expectedVersion);
    console.log('PASS cycle ' + n + ': first-load, local Python API, two navigation actions');

    await page.close({ runBeforeUnload: false });
    page = undefined;
    await awaitValue(() => exitCode !== undefined ? { code: exitCode } : null, 14000,
      'Cycle ' + n + ': EXE did not exit after Edge window closed');
    assert.equal(exitCode, 0);
    console.log('PASS cycle ' + n + ': window close stopped Python service and EXE');
  } finally {
    if (page) await page.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
    if (exitCode === undefined) child.kill('SIGTERM');
  }
}

try {
  await runCycle(1);
  await runCycle(2);
  console.log('WINDOW_FIRST_LAUNCH_AND_REOPEN_OK');
} finally {
  rmSync(root, { recursive: true, force: true });
}
