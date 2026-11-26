import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright-core';

const project = resolve('installer/frontend');
const vite = resolve(project, 'node_modules/vite/bin/vite.js');
const port = 4189;
const server = spawn(process.execPath, [vite, 'preview', '--host', '127.0.0.1',
  '--port', String(port), '--strictPort'], { cwd: project, stdio: 'pipe', windowsHide: true });
let lastError = '';
server.stderr.on('data', chunk => lastError += String(chunk));

async function checkServer() {
  for (let i = 0; i < 80; ++i) {
    if (server.exitCode !== null) throw Error('Vite died: '+lastError);
    try {
      const result = await fetch('http://127.0.0.1:'+port);
      if (result.ok) return;
    } catch {}
    await sleep(150);
  }
  throw Error('Vite server did not respond: '+lastError);
}

function browserPath() {
  const choices = [
    process.env.AWD_BROWSER_PATH,
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    '/usr/bin/chromium'
  ];
  return choices.filter(Boolean).find(existsSync);
}

let browser;
try {
  await checkServer();
  const executablePath = browserPath();
  if (!executablePath) throw Error('No Chromium browser for SPA regression tests');
  browser = await chromium.launch({
    executablePath, headless: true,
    args: process.platform === 'linux' ? ['--no-sandbox','--disable-dev-shm-usage'] : []
  });
  const page = await browser.newPage({ viewport: { width: 1550, height: 920 } });
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  await page.addInitScript(() => {
    window.__calls = [];
    window.__devices = [{serial:"U30-AIR-TEST",state:"device"},{serial:"192.168.0.8:5555",state:"offline"}];
    const capture = (name, response) => async (...args) => {
      window.__calls.push({name,args});return response;
    };
    window.pywebview = { api: {
      environment: capture('environment',{version:'3.0.0',adb_path:'C:\\Android\\adb.exe',adb_found:true}),
      list_devices: async () => {window.__calls.push({name:'list_devices',args:[]});return window.__devices},
      device_info: capture('device_info',{
        brand:'ZTE',model:'U30 Air',manufacturer:'ZTE',android:'13',
        abi:'arm64-v8a',sdk:'33',build:'U30Air_ABSSV',
        ips:['192.168.0.1'],preferred_ip:'192.168.0.1',
        installed_version:'2.5.0',listening_address:'192.168.0.1:9000',
        network_addresses:[{ip:'192.168.0.1',interface:'br0',role:'热点/局域网'}],
      }),
      read_auth:capture('read_auth',{enabled:true,configured:true}),
      configure_auth:capture('configure_auth',{enabled:false,message:'saved'}),
      list_apps:capture('list_apps',[{name:'com.v2ray.ang',system:false,disabled:false}]),
      poweroff:capture('poweroff','ok'), reboot:capture('reboot','ok'), open_web:capture('open_web','http://192.168.0.1:9000'),
      choose_apk:capture('choose_apk','C:/Downloads/test.apk'),
      install_application:capture('install_application','Success'),
      get_logs:capture('get_logs',[]), clear_logs:capture('clear_logs',true),
      check_release:capture('check_release',{version:'3.0.0',notes:'视觉恢复验证'}),
      install_official_adb:capture('install_official_adb','C:\\Android\\adb.exe'),
    }};
  });
  await page.goto('http://127.0.0.1:'+port, {waitUntil:'domcontentloaded'});
  await page.locator('.startup-notice').waitFor({state:'hidden',timeout:10000});
  await page.locator('.stat-card').first().waitFor();
  assert.equal(await page.locator('.stat-card').count(),4);
  assert.equal(await page.locator('button.nav-item').count(),6);
  const sidebarColor = await page.locator('.sidebar').evaluate(el=>getComputedStyle(el).backgroundColor);
  assert.equal(sidebarColor,'rgb(255, 255, 255)');
  assert.equal((await page.locator('.sidebar-profile').innerText()).includes('3.0.0'),true);
  console.log('PASS restored original shadcn-style sidebar and four dashboard cards');

  await page.locator('.sidebar-toggle').click();
  assert(await page.locator('.app-root').evaluate(el=>el.classList.contains('sidebar-closed')));
  await page.locator('.sidebar-toggle').click();
  assert(!(await page.locator('.app-root').evaluate(el=>el.classList.contains('sidebar-closed'))));
  const picker = page.getByRole('button',{name:'选择 Android 设备'});
  await picker.click();
  await page.locator('.device-dropdown').waitFor({state:'visible'});
  assert.equal(await page.locator('.device-option').count(),2);
  await page.locator('.device-dropdown input').fill('U30-AIR');
  assert.equal(await page.locator('.device-option').count(),1);
  await page.locator('.device-dropdown input').press('Escape');
  console.log('PASS collapsible original sidebar and searchable Android device picker');

  await page.locator('button.nav-item[title="部署与更新"]').click();
  assert.equal((await page.locator('.page-content h1').textContent()).trim(),'部署与更新');
  await page.locator('#ipField').waitFor();
  assert.equal(await page.locator('#ipField').inputValue(),'192.168.0.1');
  await page.locator('.auth-setup').waitFor();
  assert(await page.getByText('升级时保留原来的网页登录设置').count()>0);
  await page.getByText('升级时保留原来的网页登录设置').click();
  await page.locator('#installPassword').waitFor({state:'hidden'});
  await page.getByText('启用 8765 网页访问密码').click();
  await page.locator('#installPassword').fill('1');
  await page.locator('#authEditPassword').fill('a');
  await page.locator('.auth-save').click();
  await page.getByRole('dialog',{name:'保存网页访问密码设置'}).waitFor();
  await page.getByRole('dialog',{name:'保存网页访问密码设置'})
    .getByRole('button',{name:'保存设置'}).click();
  await page.waitForFunction(()=>window.__calls.some(c=>c.name==='configure_auth'));
  const calls = await page.evaluate(()=>window.__calls);
  assert(calls.some(c=>c.name==='configure_auth'&&c.args[2]==='a'));
  console.log('PASS styled first-install password choices and existing password management');

  await page.locator('button.nav-item[title="应用管理"]').click();
  await page.getByRole('heading',{name:'APK 安装器'}).waitFor();
  await page.getByRole('textbox',{name:'APK 下载链接'}).fill('https://example.com/app.apk');
  await page.getByRole('button',{name:'下载并安装'}).click();
  await page.getByRole('dialog',{name:'确认安装 APK'}).getByRole('button',{name:'安装应用'}).click();
  await page.waitForFunction(()=>window.__calls.some(c=>c.name==='install_application'&&c.args[2]===true));
  await page.getByText('安装成功',{exact:true}).waitFor();
  await page.getByRole('button',{name:'本地 APK'}).click();
  await page.getByRole('dialog',{name:'确认安装 APK'}).getByRole('button',{name:'安装应用'}).click();
  await page.waitForFunction(()=>window.__calls.some(c=>c.name==='install_application'&&c.args[2]===false));
  await page.getByText('安装成功',{exact:true}).waitFor();
  console.log('PASS Windows APK link and local-file workflows');

  await page.locator('button.nav-item[title="设置"]').click();
  await page.getByRole('button',{name:/获取官方 ADB/}).waitFor();
  await page.getByText('Vue 3 · WebView2',{exact:true}).waitFor();
  await page.locator('button.nav-item[title="工作台"]').click();
  assert.equal((await page.locator('.page-content h1').textContent()).trim(),'工作台');
  for (const name of ['设备管理','应用管理','部署与更新','运行日志','设置','工作台']) {
    await page.locator('button.nav-item[title="'+name+'"]').click();
    assert.equal((await page.locator('.page-content h1').textContent()).trim(),name);
    assert.equal(await page.locator('select').count(),0,'No unstyled native select');
    assert(await page.locator('.page-content .panel, .stat-card').count()>0);
  }
  await page.waitForFunction(()=>document.querySelector('.brand-icon img')?.naturalWidth>0);
  console.log('PASS all six pages, custom controls and brand logo');
  await page.getByRole('button',{name:/打开网页桌面/}).click();
  await page.waitForFunction(()=>window.__calls.some(c=>c.name==='open_web'&&c.args[1]===9000));
  console.log('PASS actual deployed port used to open web console');

  // Confirm an operation only after the originally selected device is rechecked.
  await page.locator('button.nav-item[title="设置"]').click();
  await page.getByRole('button',{name:'关机',exact:true}).click();
  const offDialog=page.getByRole('dialog',{name:'关闭设备电源'});
  await offDialog.getByText('U30-AIR-TEST',{exact:true}).waitFor();
  await page.evaluate(()=>{window.__devices=[{serial:'U30-AIR-TEST',state:'offline'},{serial:'SECOND-DEVICE',state:'device'}]});
  await offDialog.getByRole('button',{name:'确认关机'}).click();
  await offDialog.waitFor({state:'hidden'});
  assert(!(await page.evaluate(()=>window.__calls.some(c=>c.name==='poweroff'))),'Offline target must not receive any power RPC');
  // After automatic scanning selects a different device, an old modal must close.
  await page.evaluate(()=>{window.__devices=[{serial:'U30-AIR-TEST',state:'device'},{serial:'SECOND-DEVICE',state:'offline'}]});
  await page.getByRole('button',{name:'关机',exact:true}).click();
  await offDialog.waitFor();
  await page.evaluate(()=>{window.__devices=[{serial:'U30-AIR-TEST',state:'offline'},{serial:'SECOND-DEVICE',state:'device'}]});
  await offDialog.waitFor({state:'hidden',timeout:25000});
  assert(!(await page.evaluate(()=>window.__calls.some(c=>c.name==='poweroff'))));
  console.log('PASS original-target guard on confirmation and automatic device switch');
  assert.deepEqual(errors,[],'No uncaught JS errors in restored Vue3 UI');
  console.log('RESTORED_VUE3_SHADCN_E2E_OK');
} finally {
  await browser?.close();
  server.kill();
}
