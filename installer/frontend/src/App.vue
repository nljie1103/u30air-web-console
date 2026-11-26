<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  Activity, AppWindow, ArrowDownToLine, ArrowRight, ArrowUpRight,
  Check, CheckCheck, CheckCircle2, ChevronDown, ChevronRight, CircleAlert,
  Clock3, CloudDownload, Code2, Command, Copy, Download, FileArchive, FileDown,
  FolderOpen, HardDrive, House, Info, LayoutDashboard, Link2, ListFilter,
  LoaderCircle, Menu, Monitor, MoreHorizontal, Package, PanelLeftClose,
  PanelLeftOpen, PlugZap, Power, RefreshCw, RotateCcw, Search, ServerCog,
  Settings2, ShieldAlert, Smartphone, Terminal, Trash2, Unplug, Usb, Wifi, X,
} from 'lucide-vue-next'

type View = 'overview' | 'devices' | 'applications' | 'deployment' | 'logs' | 'settings'
type Device = { serial: string; state: string; detail?: string }
type InfoData = {
  adb_serial?: string; manufacturer?: string; brand?: string; model?: string
  android?: string; sdk?: string; abi?: string; build?: string
  installed_version?: string | null; ips?: string[]
}
type AndroidApp = { name: string; system: boolean; disabled: boolean }
type Entry = { time: string; level: string; message: string }
type DialogData = {
  title: string; description: string; confirmText: string
  destructive?: boolean; expected?: string; inputLabel?: string
  inputPlaceholder?: string; initial?: string; onConfirm: (input: string) => Promise<void> | void
}
type ResultInstall = { version: string; password: string; url: string }

const views: { id: View; label: string; icon: any; hint?: string }[] = [
  { id: 'overview', label: '工作台', icon: LayoutDashboard },
  { id: 'devices', label: '设备管理', icon: Smartphone },
  { id: 'applications', label: '应用管理', icon: AppWindow },
  { id: 'deployment', label: '部署与更新', icon: Package },
  { id: 'logs', label: '运行日志', icon: Terminal },
  { id: 'settings', label: '设置', icon: Settings2 },
]
const current = ref<View>('overview')
const collapsed = ref(false)
const devices = ref<Device[]>([])
const selected = ref('')
const deviceMenuOpen = ref(false)
const deviceSearch = ref('')
const devicePickerRef = ref<HTMLElement | null>(null)
const appsLoadedFor = ref('')
let logPollBusy = false
let quietScanBusy = false
let infoGeneration = 0
let initFailureCount = 0
const info = ref<InfoData>({})
const applications = ref<AndroidApp[]>([])
const appSearch = ref('')
const showSystem = ref(false)
const activeOnly = ref<'all' | 'enabled' | 'disabled'>('all')
const adbPath = ref('')
const envVersion = ref('2.3.2')
const loading = ref('')
const scanning = ref(false)
const deviceLoading = ref(false)
const ready = ref(false)
const startupSlow = ref(false)
const error = ref('')
const entries = ref<Entry[]>([])
const release = ref<any>(null)
const targetIp = ref('')
const modal = ref<DialogData | null>(null)
const modalInput = ref('')
const pendingInstall = ref<ResultInstall | null>(null)
const infoDismissed = ref(false)
const toast = ref<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
let noticeTimer: ReturnType<typeof setTimeout> | undefined
let timer: ReturnType<typeof setInterval> | undefined
let initialized = false
let initializing = false
let bridgePoll: ReturnType<typeof setInterval> | undefined
let startupTimeout: ReturnType<typeof setTimeout> | undefined
const preview = new URLSearchParams(window.location.search).has('preview')

const onlineCount = computed(() => devices.value.filter(d => d.state === 'device').length)
const selectedDevice = computed(() => devices.value.find(d => d.serial === selected.value))
const selectedReady = computed(() => selectedDevice.value?.state === 'device')
const availableDevices = computed(() => devices.value.filter(d =>
  d.serial.toLowerCase().includes(deviceSearch.value.trim().toLowerCase()) ||
  (d.detail || '').toLowerCase().includes(deviceSearch.value.trim().toLowerCase())
))
const modelName = computed(() => [info.value.brand, info.value.model].filter(Boolean).join(' ') || '未知设备')
const installed = computed(() => Boolean(info.value.installed_version))
const installedLabel = computed(() => installed.value ? 'v' + info.value.installed_version : '未部署')
const filteredApps = computed(() => {
  const search = appSearch.value.trim().toLowerCase()
  return applications.value.filter(a =>
    (!search || a.name.toLowerCase().includes(search)) &&
    (activeOnly.value === 'all' || (activeOnly.value === 'enabled' && !a.disabled) ||
      (activeOnly.value === 'disabled' && a.disabled)),
  )
})
const preferredIp = computed(() => targetIp.value || info.value.ips?.[0] || '')
const bodyTitle = computed(() => ({
  overview: '工作台', devices: '设备管理', applications: '应用管理', deployment: '部署与更新',
  logs: '运行日志', settings: '设置',
})[current.value])

function showToast(message: string, type: 'success' | 'error' | 'info' = 'success') {
  toast.value = { message, type }
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { toast.value = null }, 4500)
}
function logLocal(message: string, level = 'info') {
  entries.value.push({ time: new Date().toLocaleTimeString('zh-CN', { hour12: false }), message, level })
  if (entries.value.length > 300) entries.value.shift()
}
const INITIAL_API_METHODS = ['environment', 'list_devices', 'get_logs'] as const

function bridgeMethodsReady(): boolean {
  const api = window.pywebview?.api
  return Boolean(api && INITIAL_API_METHODS.every(name => typeof api[name] === 'function'))
}
async function invoke<T = any>(method: string, ...args: any[]): Promise<T> {
  const api = window.pywebview?.api
  const fn = api?.[method]
  // pywebview can publish its API object before every function has been
  // injected into WebView2. An absent method is NOT a function to call.
  if (typeof fn !== 'function') {
    throw new Error('Windows 管理接口「' + method + '」尚未就绪，请稍后重试')
  }
  return await fn.apply(api, args) as T
}
async function work<T>(message: string, action: () => Promise<T>, done?: (result: T) => Promise<void> | void) {
  if (loading.value) { showToast('已有任务正在执行', 'info'); return }
  loading.value = message
  error.value = ''
  try {
    const response = await action()
    if (done) await done(response)
    if (current.value === 'logs' || current.value === 'overview') await getLogs()
  } catch (cause: any) {
    const msg = cause instanceof Error ? cause.message : String(cause)
    error.value = msg
    logLocal(message + '：' + msg, 'error')
    showToast(msg, 'error')
  } finally {
    loading.value = ''
  }
}
async function getLogs() {
  if (preview || !ready.value || logPollBusy || document.visibilityState === 'hidden') return
  logPollBusy = true
  try {
    const latest = await invoke<Entry[]>('get_logs')
    const currentLast = entries.value.at(-1)
    const nextLast = latest.at(-1)
    if (latest.length !== entries.value.length ||
        currentLast?.time !== nextLast?.time ||
        currentLast?.message !== nextLast?.message) {
      entries.value = latest
    }
  } catch { /* log endpoint may be offline */ }
  finally { logPollBusy = false }
}
async function refreshDevicesQuietly() {
  if (preview || !ready.value || loading.value || scanning.value || quietScanBusy ||
      document.visibilityState === 'hidden') return
  quietScanBusy = true
  try {
    const found = await invoke<Device[]>('list_devices')
    const old = devices.value.map(d => d.serial + ':' + d.state).join('|')
    const latest = found.map(d => d.serial + ':' + d.state).join('|')
    if (old !== latest) {
      devices.value = found
      if (!found.some(d => d.serial === selected.value && d.state === 'device')) {
        ++infoGeneration
        deviceLoading.value = false
        ++infoGeneration
        deviceLoading.value = false
        ++infoGeneration
        deviceLoading.value = false
        ++infoGeneration
        deviceLoading.value = false
        selected.value = ''
        info.value = {}
        applications.value = []
        appsLoadedFor.value = ''
        const first = found.find(d => d.state === 'device')
        if (first) await loadDevice(first.serial)
      }
    }
  } catch { /* disconnected ADB is handled by the manual refresh action */ }
  finally { quietScanBusy = false }
}
async function clearLogs() {
  if (preview) { entries.value = []; return }
  await work('清空当前会话日志…', () => invoke<boolean>('clear_logs'), () => {
    entries.value = []
    showToast('当前会话日志已清空')
  })
}
async function scanDevices(silent = false) {
  if (preview || !ready.value || scanning.value) return
  scanning.value = true
  try {
    const response = await invoke<Device[]>('list_devices')
    devices.value = response
    const stillOnline = response.some(d => d.serial === selected.value && d.state === 'device')
    if (!stillOnline) {
      ++infoGeneration
      deviceLoading.value = false
      selected.value = ''
      info.value = {}
      applications.value = []
      appsLoadedFor.value = ''
    }
    const next = stillOnline ? selected.value : (response.find(d => d.state === 'device')?.serial || '')
    if (next) void loadDevice(next)
    else if (!silent) showToast(response.length ? '检测到设备，请在 Android 上完成 ADB 授权' : '暂未检测到已连接设备', 'info')
  } catch (cause: any) {
    // ADB may be starting or missing during first launch. Do not block the UI.
    const msg = cause instanceof Error ? cause.message : String(cause)
    logLocal('设备扫描失败：' + msg, 'error')
    if (!silent) showToast(msg, 'error')
  } finally {
    scanning.value = false
  }
}
async function refreshDevices() { await scanDevices(false) }
async function loadDevice(serial: string) {
  const request = ++infoGeneration
  if (!serial) {
    selected.value = ''; info.value = {}; applications.value = []; appsLoadedFor.value = ''
    deviceLoading.value = false
    return
  }
  if (selected.value !== serial) {
    applications.value = []
    appsLoadedFor.value = ''
  }
  selected.value = serial
  deviceLoading.value = true
  try {
    const data = await invoke<InfoData>('device_info', serial)
    if (selected.value !== serial || request !== infoGeneration) return
    info.value = data
    targetIp.value = data.ips?.[0] || ''
    if (current.value === 'applications') void loadApps()
  } catch (cause: any) {
    if (request === infoGeneration) {
      logLocal('读取设备失败：' + String(cause), 'error')
      showToast('无法读取设备信息，请检查 ADB 授权', 'error')
    }
  } finally {
    if (request === infoGeneration) deviceLoading.value = false
  }
}
async function loadApps(force = false) {
  if (!selected.value || preview) return
  const serial = selected.value
  const system = showSystem.value
  const key = serial + ':' + String(system)
  if (!force && appsLoadedFor.value === key) return
  try {
    const result = await invoke<AndroidApp[]>('list_apps', serial, system)
    if (selected.value === serial && showSystem.value === system) {
      applications.value = result
      appsLoadedFor.value = key
    }
  } catch (cause: any) {
    logLocal('获取应用列表失败：' + String(cause), 'error')
    showToast('应用列表读取失败，可在应用页面重试', 'error')
  }
}
async function chooseDevice(serial: string) {
  if (loading.value) return
  deviceMenuOpen.value = false
  deviceSearch.value = ''
  if (serial === selected.value) return
  await loadDevice(serial)
}
function closeDeviceMenu(event: PointerEvent) {
  const target = event.target
  if (deviceMenuOpen.value && target instanceof Node &&
      !devicePickerRef.value?.contains(target)) {
    deviceMenuOpen.value = false
  }
}
function deviceMenuKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { deviceMenuOpen.value = false; return }
  if (event.key === 'Enter' && deviceMenuOpen.value && availableDevices.value.length) {
    const first = availableDevices.value.find(d => d.state === 'device')
    if (first) void chooseDevice(first.serial)
  }
}
function requireDevice() {
  if (!selected.value || !selectedReady.value) { showToast('请先选择已授权且在线的设备', 'error'); return false }
  return true
}
function openDialog(data: DialogData) {
  modalInput.value = data.initial || ''
  modal.value = data
}
function closeDialog() { modal.value = null; modalInput.value = '' }
async function confirmDialog() {
  const value = modalInput.value.trim()
  const m = modal.value
  if (!m) return
  if (m.expected && value !== m.expected) { showToast('确认内容不匹配', 'error'); return }
  if (m.inputLabel && !value) { showToast('请填写必要信息', 'error'); return }
  closeDialog()
  await m.onConfirm(value)
}
function chooseNetwork() {
  openDialog({
    title: '连接无线 ADB 设备', description: '目标设备需要提前启用无线调试或 TCP ADB，并完成授权。',
    confirmText: '连接设备', inputLabel: '设备地址', inputPlaceholder: '例如 192.168.1.20:5555',
    onConfirm: async value => {
      await work('正在连接无线设备…', () => invoke<string>('connect', value), async result => {
        showToast(result || '连接请求已发送')
        setTimeout(() => void refreshDevices(), 10)
      })
    },
  })
}
async function reloadInfo() {
  if (!requireDevice()) return
  await work('同步设备状态…', async () => await invoke<InfoData>('device_info', selected.value), result => {
    info.value = result
    targetIp.value = result.ips?.[0] || ''
    showToast('设备信息已更新')
  })
}
async function checkRelease() {
  await work('检查 GitHub Release…', () => invoke('check_release'), result => {
    release.value = result
    showToast('已获取最新版本 v' + result.version)
  })
}
async function deploy(mode: 'online' | 'offline') {
  if (!requireDevice()) return
  const ip = preferredIp.value
  if (!ip) { showToast('请填写设备实际局域网 IPv4', 'error'); return }
  if (mode === 'online') {
    openDialog({ title: installed.value ? '升级网页桌面' : '部署网页桌面',
      description: '将从项目 GitHub Release 下载 ARM64 安装包并验证 SHA256。部署时可能短暂中断现有服务。',
      confirmText: '确认部署', onConfirm: async () => {
        await work('正在下载安装包并部署…', () => invoke<ResultInstall>('install_latest', selected.value, ip), onInstalled)
      },
    })
  } else {
    let file = ''
    try { file = await invoke<string>('choose_local_zip') } catch (cause: any) { showToast(String(cause), 'error'); return }
    if (!file) return
    openDialog({ title: '安装本地 ZIP', description: '本地安装包不会进行 GitHub 发布摘要校验，请确认文件来源可信。\n' + file,
      confirmText: '继续安装', onConfirm: async () => {
        await work('正在部署本地安装包…', () => invoke<ResultInstall>('install_local', selected.value, ip, file), onInstalled)
      },
    })
  }
}
async function onInstalled(result: ResultInstall) {
  pendingInstall.value = result
  info.value.installed_version = result.version
  showToast('网页桌面 v' + result.version + ' 已安装')
}
function uninstall() {
  if (!requireDevice() || !installed.value) { if (!installed.value) showToast('当前设备尚未安装项目', 'info'); return }
  openDialog({
    title: '卸载设备端网页桌面', description: '将删除项目程序、口令、日志和所有历史版本。此操作不会影响其他应用。',
    confirmText: '确认卸载', destructive: true, expected: '卸载', inputLabel: '请输入「卸载」确认操作',
    onConfirm: async () => {
      await work('正在卸载项目…', () => invoke<string>('uninstall', selected.value), async result => {
        info.value.installed_version = null
        showToast(result)
      })
    },
  })
}
function removeApplication(pkg: AndroidApp) {
  if (!requireDevice()) return
  if (pkg.system) {
    openDialog({ title: pkg.disabled ? '恢复系统应用' : '停用系统应用',
      description: '系统组件操作存在风险，可能影响网络、桌面或启动。请先确认该包可安全调整。\n' + pkg.name,
      confirmText: pkg.disabled ? '确认恢复' : '确认停用',
      destructive: !pkg.disabled, expected: pkg.name, inputLabel: '输入完整包名确认',
      onConfirm: async () => {
        await work('正在调整系统组件…', () => invoke<string>('set_system_app', selected.value, pkg.name, pkg.disabled), async result => {
          showToast(result || '操作已执行'); await loadApps()
        })
      },
    })
  } else {
    openDialog({ title: '卸载普通应用', description: '将为当前主用户卸载 ' + pkg.name + '，应用数据可能丢失。',
      confirmText: '卸载应用', destructive: true,
      onConfirm: async () => {
        await work('正在卸载应用…', () => invoke<string>('uninstall_app', selected.value, pkg.name), async result => {
          showToast(result || '已卸载'); await loadApps()
        })
      },
    })
  }
}
function requestPower(operation: 'reboot' | 'poweroff') {
  if (!requireDevice()) return
  const off = operation === 'poweroff'
  openDialog({ title: off ? '关闭设备电源' : '重新启动设备',
    description: off ? '设备关机后可能需要现场手动开机，无法保证能通过网络再次唤醒。' : '重启将暂时断开 ADB 和网页桌面连接。',
    confirmText: off ? '确认关机' : '确认重启', destructive: off,
    onConfirm: async () => {
      await work(off ? '正在发送关机命令…' : '正在发送重启命令…',
        () => invoke<string>(operation, selected.value), result => showToast(result))
    },
  })
}
async function openWeb() {
  if (!requireDevice()) return
  if (!preferredIp.value) { showToast('没有可访问的设备 IP 地址', 'error'); return }
  await work('正在打开网页控制台…', () => invoke<string>('open_web', preferredIp.value, 8765), url => showToast('正在打开 ' + url))
}
function chooseAdb() {
  work('正在选择 ADB…', () => invoke<string>('choose_adb'), result => {
    if (result) { adbPath.value = result; showToast('已更新 ADB 路径'); setTimeout(() => void refreshDevices(), 10) }
  })
}
function downloadAdb() {
  openDialog({ title: '获取 Google 官方 ADB', description: '将从 Google 官方地址下载 Platform Tools 所需文件，保存在 Windows 当前用户目录。',
    confirmText: '开始下载', onConfirm: async () => {
      await work('正在下载官方 ADB…', () => invoke<string>('install_official_adb'), result => {
        adbPath.value = result; showToast('ADB 已就绪'); setTimeout(() => void refreshDevices(), 10)
      })
    },
  })
}
async function copyText(value: string) {
  try { await navigator.clipboard.writeText(value); showToast('已复制到剪贴板') }
  catch {
    const area = document.createElement('textarea'); area.value = value; area.style.position = 'fixed'; area.style.left = '-9999px'
    document.body.append(area); area.select(); document.execCommand('copy'); area.remove(); showToast('已复制到剪贴板')
  }
}
function previewSetup() {
  ready.value = true
  envVersion.value = '2.3.2'
  adbPath.value = 'C:\\Android\\platform-tools\\adb.exe'
  devices.value = [{ serial: 'ZY22FQ7A9H', state: 'device', detail: 'usb:1-4 product:demo model:Pixel' },{ serial: '192.168.1.28:5555', state: 'offline' }]
  selected.value = 'ZY22FQ7A9H'
  info.value = { brand: 'Google', model: 'Pixel 9 Pro', android: '16', sdk: '36', abi: 'arm64-v8a',
    build: 'BP2A.250605.008', ips: ['192.168.1.28'], installed_version: '2.1.0' }
  targetIp.value = '192.168.1.28'
  applications.value = [
    { name: 'com.spotify.music', system: false, disabled: false },
    { name: 'com.tencent.mm', system: false, disabled: false },
    { name: 'com.android.chrome', system: false, disabled: false },
    { name: 'org.mozilla.firefox', system: false, disabled: false },
  ]
  entries.value = [
    { time: '08:42:12', level: 'success', message: 'ADB 检测完成，发现 2 台设备' },
    { time: '08:42:13', level: 'info', message: '读取设备 Pixel 9 Pro 信息' },
    { time: '08:42:13', level: 'success', message: '已检测网页桌面 v2.1.0' },
  ]
}
async function initialize() {
  if (initialized) return
  if (preview) { initialized = true; previewSetup(); return }
  // The pywebviewready event and API method injection are not necessarily
  // simultaneous on cold WebView2 launches.
  if (initializing || !bridgeMethodsReady()) return
  initializing = true
  try {
    // A first WebView2 bridge call may never resolve if the native side is
    // still initializing. Bound the handshake so the retry loop cannot stall.
    let handshakeTimer: ReturnType<typeof setTimeout> | undefined
    let result: any
    try {
      result = await Promise.race([
        invoke<any>('environment'),
        new Promise<never>((_, reject) => {
          handshakeTimer = setTimeout(() => reject(new Error('管理接口初始化响应超时')), 5000)
        }),
      ])
    } finally {
      if (handshakeTimer) clearTimeout(handshakeTimer)
    }
    if (!result || typeof result.version !== 'string') throw new Error('本机管理接口返回无效信息')
    envVersion.value = result.version
    adbPath.value = result.adb_path || ''
    ready.value = true
    startupSlow.value = false
    initialized = true
    initFailureCount = 0
    if (bridgePoll) clearInterval(bridgePoll)
    // Never await ADB on the startup path; navigating between pages must remain responsive.
    if (result.adb_found) void scanDevices(true)
    else showToast('尚未发现 ADB，可以在设置中下载官方工具', 'info')
    timer = setInterval(() => {
      if (current.value === 'logs' && !loading.value) void getLogs()
      void refreshDevicesQuietly()
    }, 15000)
  } catch (cause: any) {
    // Transient startup errors are retried, not displayed as a fatal red banner.
    initFailureCount++
    if (initFailureCount === 5) logLocal('管理服务正在初始化，自动重试连接', 'info')
  } finally { initializing = false }
}
onMounted(() => {
  try { collapsed.value = localStorage.getItem('awd-sidebar-collapsed') === 'true' } catch { /* ignored */ }
  void initialize()
  window.addEventListener('pywebviewready', initialize)
  bridgePoll = setInterval(() => { if (!initialized) void initialize() }, 400)
  startupTimeout = setTimeout(() => { if (!ready.value) startupSlow.value = true }, 12000)
  window.addEventListener('pointerdown', closeDeviceMenu)
})
onUnmounted(() => {
  if (bridgePoll) clearInterval(bridgePoll)
  if (startupTimeout) clearTimeout(startupTimeout)
  window.removeEventListener('pywebviewready', initialize)
  window.removeEventListener('pointerdown', closeDeviceMenu)
  if (timer) clearInterval(timer)
  if (noticeTimer) clearTimeout(noticeTimer)
})
watch(collapsed, v => {
  try { localStorage.setItem('awd-sidebar-collapsed', String(v)) } catch { /* ignored */ }
})
watch(current, page => {
  deviceMenuOpen.value = false
  if (preview) return
  if (page === 'applications' && selected.value &&
      appsLoadedFor.value !== selected.value + ':' + String(showSystem.value)) {
    void work('正在读取设备应用…', () => loadApps())
  } else if (page === 'logs') {
    void getLogs()
  }
})
watch(showSystem, () => {
  appsLoadedFor.value = ''
  if (!preview && selected.value && current.value === 'applications') {
    void work('正在筛选应用…', () => loadApps(true))
  }
})
</script>

<template>
  <div class="app-root" :class="{ 'sidebar-closed': collapsed }">
    <aside class="sidebar" aria-label="主导航">
      <div class="sidebar-head">
        <div class="brand-icon"><Monitor :size="19" :stroke-width="2.3" /></div>
        <div v-show="!collapsed" class="brand-words">
          <strong>Android Desktop</strong>
          <small>Device Manager</small>
        </div>
        <button class="icon-button sidebar-toggle" type="button" :title="collapsed ? '展开侧边栏' : '收起侧边栏'"
          :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'" @click="collapsed = !collapsed">
          <PanelLeftOpen v-if="collapsed" :size="17" />
          <PanelLeftClose v-else :size="17" />
        </button>
      </div>

      <div v-show="!collapsed" class="sidebar-section-heading">工作空间</div>
      <nav class="sidebar-nav">
        <button v-for="item in views.slice(0,4)" :key="item.id" type="button"
          :class="['nav-item', { active: current === item.id }]" :title="item.label" @click="current = item.id">
          <component :is="item.icon" :size="18" :stroke-width="1.85" />
          <span v-show="!collapsed">{{ item.label }}</span>
          <ChevronRight v-if="current === item.id && !collapsed" class="nav-arrow" :size="15" />
        </button>
      </nav>
      <div v-show="!collapsed" class="sidebar-section-heading secondary-heading">系统</div>
      <nav class="sidebar-nav">
        <button v-for="item in views.slice(4)" :key="item.id" type="button"
          :class="['nav-item', { active: current === item.id }]" :title="item.label" @click="current = item.id">
          <component :is="item.icon" :size="18" :stroke-width="1.85" />
          <span v-show="!collapsed">{{ item.label }}</span>
          <ChevronRight v-if="current === item.id && !collapsed" class="nav-arrow" :size="15" />
        </button>
      </nav>
      <div class="sidebar-spacer"></div>
      <div v-if="!collapsed" class="sidebar-bottom-card">
        <span class="small-icon"><ShieldAlert :size="17" /></span>
        <strong>本地安全管理</strong>
        <p>设备操作仅在本机执行，系统组件操作须二次确认。</p>
      </div>
      <div class="sidebar-footer">
        <span class="avatar-mark">A</span>
        <div v-show="!collapsed" class="sidebar-profile"><b>Desktop Manager</b><span>v{{ envVersion }}</span></div>
        <MoreHorizontal v-show="!collapsed" :size="17" class="muted" />
      </div>
    </aside>

    <div class="main-area">
      <header class="topbar">
        <div class="topbar-left">
          <button type="button" class="icon-button mobile-collapse" @click="collapsed = !collapsed"><Menu :size="19" /></button>
          <span class="breadcrumb-root">管理平台</span>
          <ChevronRight :size="15" class="breadcrumb-chevron" />
          <span class="breadcrumb-active">{{ bodyTitle }}</span>
        </div>
        <div class="topbar-right">
          <span v-if="preview" class="tag tag-muted">界面预览</span>
          <div class="status-pill"><span class="status-dot" :class="onlineCount > 0 ? 'online' : 'offline'"></span>
            {{ onlineCount > 0 ? onlineCount + ' 台设备在线' : '未连接设备' }}
          </div>
          <button class="icon-button" type="button" :disabled="!!loading || scanning" title="刷新设备" aria-label="刷新设备" @click="refreshDevices">
            <RefreshCw :size="17" :class="{ spin: scanning }" />
          </button>
          <span class="top-avatar">A</span>
        </div>
      </header>

      <main class="page-content">
        <div class="page-title-row">
          <div>
            <div class="eyebrow">DEVICE CONTROL CENTER</div>
            <h1>{{ bodyTitle }}</h1>
            <p class="page-intro">
              {{ current === 'overview' ? '统一查看设备连接、安装状态和快捷操作。' :
                current === 'devices' ? '选择 Android 设备，检查系统参数和连接状态。' :
                current === 'applications' ? '管理设备应用，并谨慎处理系统组件。' :
                current === 'deployment' ? '部署网页桌面、检查更新并管理已安装版本。' :
                current === 'logs' ? '查看 ADB 连接、部署与维护操作记录。' :
                '管理 ADB 工具路径和 Windows 客户端。' }}
            </p>
          </div>
          <div v-if="current !== 'settings' && current !== 'logs'" class="page-actions">
            <div ref="devicePickerRef" class="device-picker">
              <button type="button" class="device-picker-trigger" aria-label="选择 Android 设备"
                aria-haspopup="listbox" :aria-expanded="deviceMenuOpen"
                :disabled="!!loading" @click="deviceMenuOpen = !deviceMenuOpen"
                @keydown="deviceMenuKeydown">
                <Smartphone :size="16" />
                <span class="device-picker-label">{{ selectedDevice ? selectedDevice.serial : '选择 Android 设备' }}</span>
                <ChevronDown :size="15" :class="{ 'chevron-open': deviceMenuOpen }" />
              </button>
              <div v-if="deviceMenuOpen" class="device-dropdown" role="group" aria-label="设备选择面板"
                @keydown="deviceMenuKeydown">
                <div class="device-dropdown-head">
                  <span>已发现设备 <b>{{ devices.length }}</b></span>
                  <span class="device-online-count">{{ onlineCount }} 台在线</span>
                </div>
                <div class="device-dropdown-search">
                  <Search :size="15" />
                  <input v-model="deviceSearch" aria-label="搜索设备序列号" placeholder="搜索设备或序列号…" />
                </div>
                <div class="device-dropdown-list" role="listbox" aria-label="可用设备">
                  <button v-for="d in availableDevices" :key="d.serial" type="button"
                    class="device-option" role="option" :aria-selected="selected === d.serial"
                    :disabled="d.state !== 'device' || !!loading" @click="chooseDevice(d.serial)">
                    <span class="device-option-icon"><Smartphone :size="16" /></span>
                    <span class="device-option-copy"><strong>{{ d.serial }}</strong>
                      <small>{{ d.state === 'device' ? '已连接 · 可管理' : d.state === 'unauthorized' ? '需要设备授权' : d.state === 'offline' ? '设备离线' : d.state }}</small>
                    </span>
                    <Check v-if="selected === d.serial" :size="16" class="device-selected-check" />
                    <span v-else class="mini-dot" :class="d.state === 'device' ? 'green' : 'grey'"></span>
                  </button>
                  <div v-if="!availableDevices.length" class="device-option-empty">
                    {{ devices.length ? '没有匹配的设备' : '还没有检测到设备，请点击刷新' }}
                  </div>
                </div>
                <div class="device-dropdown-footer">
                  <button type="button" @click="deviceMenuOpen = false; refreshDevices()">
                    <RefreshCw :size="14" /> 重新检测设备
                  </button>
                </div>
              </div>
            </div>
            <button class="btn btn-outline" type="button" :disabled="!!loading" @click="refreshDevices">
              <RefreshCw :size="16" /> 刷新
            </button>
          </div>
        </div>

        <div v-if="!ready && !preview" class="startup-notice" role="status">
          <LoaderCircle :size="16" class="spin" />
          <span>{{ startupSlow ? 'Windows 管理接口仍未连接成功；可点击重试，其他页面仍可切换。' : '正在连接 Windows 本机管理服务，侧边栏仍可正常切换…' }}</span>
          <button type="button" @click="initialize">重试连接</button>
        </div>

        <div v-if="error && !infoDismissed" class="inline-error" role="alert">
          <CircleAlert :size="18" /><span>{{ error }}</span>
          <button class="icon-button" title="关闭提醒" @click="infoDismissed = true"><X :size="16" /></button>
        </div>

        <template v-if="current === 'overview'">
          <section class="stats-grid">
            <div class="stat-card">
              <div class="stat-icon purple"><Smartphone :size="19" /></div>
              <div class="stat-heading">已发现设备 <Activity :size="15" /></div>
              <div class="stat-value">{{ devices.length }} <span>台</span></div>
              <div class="stat-footer"><span class="mini-dot green"></span>{{ onlineCount }} 台在线并已授权</div>
            </div>
            <div class="stat-card">
              <div class="stat-icon blue"><Monitor :size="19" /></div>
              <div class="stat-heading">当前设备 <HardDrive :size="15" /></div>
              <div class="stat-value stat-truncate">{{ info.model || '未选择' }}</div>
              <div class="stat-footer">{{ info.android ? 'Android ' + info.android : '连接后查看设备型号' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-icon orange"><Package :size="19" /></div>
              <div class="stat-heading">网页桌面 <CheckCircle2 :size="15" /></div>
              <div class="stat-value stat-truncate">{{ installedLabel }}</div>
              <div class="stat-footer">{{ installed ? '设备端服务已检测' : '选择设备进行部署' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-icon green"><Wifi :size="19" /></div>
              <div class="stat-heading">局域网地址 <Activity :size="15" /></div>
              <div class="stat-value stat-truncate">{{ preferredIp || '—' }}</div>
              <div class="stat-footer">{{ preferredIp ? '设备 IPv4 地址' : '等待设备网络信息' }}</div>
            </div>
          </section>

          <section class="two-col">
            <article class="panel device-overview">
              <div class="panel-head">
                <div><h2>设备概况</h2><p>当前选中设备的主要信息</p></div>
                <span class="tag" :class="selectedReady ? 'tag-success' : 'tag-muted'">
                  <span class="mini-dot" :class="selectedReady ? 'green' : 'grey'"></span>
                  {{ selectedReady ? '已连接' : '未连接' }}
                </span>
              </div>
              <div v-if="selectedReady" class="device-hero">
                <div class="hero-device-icon"><Smartphone :size="36" :stroke-width="1.25" /></div>
                <div class="hero-device-copy"><h3>{{ modelName }}</h3><p>{{ selected }}</p>
                  <span class="micro-text">Android {{ info.android || '—' }} · {{ info.abi || '—' }}</span></div>
              </div>
              <div v-else class="empty-hero"><PlugZap :size="28" /><strong>尚未选择设备</strong><span>通过 USB 或局域网连接 Android 设备。</span>
                <button class="btn btn-outline" type="button" @click="chooseNetwork"><Link2 :size="15" />连接局域网设备</button>
              </div>
              <div class="info-grid">
                <div class="info-item"><span>设备品牌</span><b>{{ info.brand || '—' }}</b></div>
                <div class="info-item"><span>系统版本</span><b>{{ info.android || '—' }}</b></div>
                <div class="info-item"><span>系统构建号</span><b class="ellipsed" :title="info.build">{{ info.build || '—' }}</b></div>
                <div class="info-item"><span>网页桌面版本</span><b>{{ installedLabel }}</b></div>
              </div>
            </article>

            <article class="panel">
              <div class="panel-head"><div><h2>快捷操作</h2><p>管理选中的 Android 设备</p></div><MoreHorizontal :size="19" class="muted" /></div>
              <div class="quick-list">
                <button class="quick-action" :disabled="!selectedReady || !!loading" @click="deploy('online')">
                  <span class="quick-icon" style="background:#eef2ff;color:#4f46e5"><CloudDownload :size="18" /></span>
                  <span><strong>{{ installed ? '升级网页桌面' : '一键部署网页桌面' }}</strong><small>从 GitHub 下载并校验最新版本</small></span>
                  <ArrowRight :size="17" />
                </button>
                <button class="quick-action" :disabled="!selectedReady || !installed || !!loading" @click="openWeb">
                  <span class="quick-icon" style="background:#ecfdf5;color:#0f8961"><Monitor :size="18" /></span>
                  <span><strong>打开网页桌面</strong><small>在浏览器中远程操作设备</small></span>
                  <ArrowUpRight :size="17" />
                </button>
                <button class="quick-action" :disabled="!!loading" @click="chooseNetwork">
                  <span class="quick-icon" style="background:#eff6ff;color:#3576c8"><Wifi :size="18" /></span>
                  <span><strong>连接无线设备</strong><small>通过局域网 IP 和 ADB 端口连接</small></span>
                  <ArrowRight :size="17" />
                </button>
                <button class="quick-action" :disabled="!selectedReady || !!loading" @click="requestPower('reboot')">
                  <span class="quick-icon" style="background:#fff7ed;color:#cf7e26"><RotateCcw :size="18" /></span>
                  <span><strong>重新启动设备</strong><small>向已授权设备发送重启命令</small></span>
                  <ArrowRight :size="17" />
                </button>
              </div>
            </article>
          </section>

          <section class="panel bottom-panel">
            <div class="panel-head"><div><h2>最近活动</h2><p>当前管理会话中的操作记录</p></div><button class="text-link" @click="current = 'logs'">查看全部 <ArrowRight :size="14" /></button></div>
            <div v-if="entries.length" class="activity-list">
              <div v-for="(entry,i) in entries.slice(-4).reverse()" :key="i" class="activity-row">
                <span class="activity-dot" :class="entry.level"></span>
                <span class="activity-message">{{ entry.message }}</span><time>{{ entry.time }}</time>
              </div>
            </div>
            <div v-else class="empty-activity"><Clock3 :size="19" />暂无操作记录</div>
          </section>
        </template>

        <template v-else-if="current === 'devices'">
          <section class="panel device-list-panel">
            <div class="panel-head"><div><h2>设备列表</h2><p>通过 ADB 发现的所有设备</p></div>
              <div class="button-row"><button class="btn btn-outline" @click="chooseNetwork"><Wifi :size="16" /> 连接 IP</button>
                <button class="btn btn-primary" :disabled="!!loading" @click="refreshDevices"><RefreshCw :size="16" /> 检测设备</button></div>
            </div>
            <div class="table-wrap">
              <table class="data-table"><thead><tr><th>设备标识</th><th>连接状态</th><th>连接方式</th><th>操作</th></tr></thead>
                <tbody><tr v-for="d in devices" :key="d.serial" :class="{ 'selected-row': selected === d.serial }">
                  <td><span class="row-icon"><Smartphone :size="18" /></span><span class="text-main">{{ d.serial }}</span></td>
                  <td><span class="tag" :class="d.state === 'device' ? 'tag-success' : 'tag-warn'">{{ d.state === 'device' ? '已授权' : d.state }}</span></td>
                  <td>{{ d.serial.includes(':') ? '无线 ADB' : 'USB / 本地' }}</td>
                  <td><button class="table-action" :disabled="d.state !== 'device' || !!loading" @click="chooseDevice(d.serial)">查看详情 <ArrowRight :size="15" /></button></td>
                </tr></tbody>
              </table>
              <div v-if="!devices.length" class="table-empty"><Unplug :size="28" /><strong>未检测到 Android 设备</strong><span>请连接 USB、允许调试授权，或使用无线 ADB。</span></div>
            </div>
          </section>
          <section class="panel">
            <div class="panel-head"><div><h2>设备详细信息</h2><p>通过 Android 系统属性读取</p></div>
              <button class="btn btn-outline" :disabled="!selectedReady || !!loading" @click="reloadInfo"><RefreshCw :size="15" /> 同步状态</button>
            </div>
            <div class="detail-grid">
              <div v-for="(value,key) in { '品牌 / 型号':modelName, 'Android 版本':info.android || '—', '系统 SDK':info.sdk || '—',
                'CPU 架构':info.abi || '—', '系统构建号':info.build || '—', '安装版本':installedLabel }" :key="key" class="detail-box">
                <span>{{ key }}</span><strong>{{ value }}</strong>
              </div>
            </div>
          </section>
        </template>

        <template v-else-if="current === 'applications'">
          <section class="panel app-panel">
            <div class="panel-head"><div><h2>应用列表</h2><p>查询已安装的软件包与运行状态</p></div>
              <div class="button-row"><span class="tag tag-muted">{{ filteredApps.length }} 个应用</span>
                <button class="btn btn-outline" :disabled="!selectedReady || !!loading" @click="loadApps(true)"><RefreshCw :size="16" /> 刷新列表</button></div>
            </div>
            <div class="filters-row">
              <div class="search-input"><Search :size="17" /><input v-model="appSearch" placeholder="搜索应用包名…" aria-label="搜索应用" /></div>
              <button class="toggle" :class="{ enabled: showSystem }" @click="showSystem = !showSystem"><ListFilter :size="16" />{{ showSystem ? '系统应用' : '用户应用' }}</button>
              <div class="status-segments" role="group" aria-label="筛选状态">
                <button v-for="option in ([{ value: 'all', label: '全部' }, { value: 'enabled', label: '已启用' }, { value: 'disabled', label: '已停用' }] as const)"
                  :key="option.value" type="button" :class="{ active: activeOnly === option.value }"
                  :aria-pressed="activeOnly === option.value" @click="activeOnly = option.value">
                  {{ option.label }}
                </button>
              </div>
            </div>
            <div class="table-wrap">
              <table class="data-table"><thead><tr><th>软件包名</th><th>类型</th><th>状态</th><th class="align-right">管理</th></tr></thead>
                <tbody><tr v-for="pkg in filteredApps" :key="pkg.name">
                  <td><span class="app-symbol"><AppWindow :size="17" /></span><b class="package-name">{{ pkg.name }}</b></td>
                  <td><span class="tag tag-muted">{{ pkg.system ? '系统组件' : '普通应用' }}</span></td>
                  <td><span class="tag" :class="pkg.disabled ? 'tag-warn' : 'tag-success'">{{ pkg.disabled ? '已停用' : '已启用' }}</span></td>
                  <td class="align-right"><button class="table-action" :disabled="!!loading" @click="removeApplication(pkg)">
                    {{ pkg.system ? (pkg.disabled ? '恢复' : '停用') : '卸载' }} <ChevronRight :size="15" /></button></td>
                </tr></tbody>
              </table>
              <div v-if="!filteredApps.length" class="table-empty"><AppWindow :size="28" /><strong>没有匹配的应用</strong><span>调整搜索条件或检查设备连接。</span></div>
            </div>
            <div class="panel-footnote"><ShieldAlert :size="16" />系统组件操作可能影响设备功能，必须输入完整包名确认；关键系统组件禁止修改。</div>
          </section>
        </template>

        <template v-else-if="current === 'deployment'">
          <div class="deployment-grid">
            <section class="panel">
              <div class="panel-head"><div><h2>部署网页桌面</h2><p>安装或更新设备端控制服务</p></div><span class="tag" :class="installed ? 'tag-success' : 'tag-muted'">{{ installedLabel }}</span></div>
              <div class="deploy-banner"><div class="deploy-banner-icon"><Monitor :size="30" /></div><div><strong>Android Web Desktop</strong><p>通过设备局域网浏览器查看和操作 Android 桌面。</p></div></div>
              <label class="field-label" for="ipField">设备监听地址</label>
              <div class="input-with-icon"><Wifi :size="17" /><input id="ipField" v-model="targetIp" placeholder="例如 192.168.1.28" /></div>
              <p class="field-help">需填写目标设备的私有局域网 IPv4，默认网页端口为 8765。</p>
              <div class="deploy-buttons">
                <button class="btn btn-primary" :disabled="!selectedReady || !!loading" @click="deploy('online')"><CloudDownload :size="17" />从 GitHub 安装最新版</button>
                <button class="btn btn-outline" :disabled="!selectedReady || !!loading" @click="deploy('offline')"><FileArchive :size="17" />安装本地 ZIP</button>
              </div>
              <div class="separator"></div>
              <div class="danger-row"><div><strong>卸载设备端服务</strong><p>删除项目程序、历史版本、口令与运行日志。</p></div>
                <button class="btn btn-destructive-outline" :disabled="!selectedReady || !installed || !!loading" @click="uninstall"><Trash2 :size="15" />卸载</button></div>
            </section>
            <section class="panel">
              <div class="panel-head"><div><h2>版本与更新</h2><p>检查来自 GitHub 的最新稳定版本</p></div><span class="tag tag-muted">手动更新</span></div>
              <div class="version-card">
                <small>已安装版本</small><strong>{{ installedLabel }}</strong>
                <span>{{ installed ? '当前设备已部署' : '尚未检测到部署' }}</span>
              </div>
              <div class="version-card second">
                <small>最新可用版本</small><strong>{{ release ? 'v' + release.version : '尚未检查' }}</strong>
                <span>通过 GitHub Releases 获取</span>
              </div>
              <button class="btn btn-outline full-button" :disabled="!!loading" @click="checkRelease"><RefreshCw :size="16" />检查新版本</button>
              <div v-if="release" class="release-notes">
                <strong>版本说明</strong>
                <pre>{{ release.notes || '暂无更新说明' }}</pre>
              </div>
              <div class="note-card"><Info :size="18" /><p>下载时校验 SHA256；新版服务未通过健康检查时，将尝试恢复上一版本。</p></div>
            </section>
          </div>
        </template>

        <template v-else-if="current === 'logs'">
          <section class="panel log-panel">
            <div class="panel-head"><div><h2>运行日志</h2><p>本次管理器会话中的操作记录与错误信息</p></div>
              <button class="btn btn-outline" :disabled="!!loading" @click="clearLogs"><Trash2 :size="15" /> 清空日志</button>
            </div>
            <div class="logs-toolbar"><div><span class="log-live-dot"></span> 本地会话日志</div><span>{{ entries.length }} 条记录</span></div>
            <div class="console-rows">
              <div v-for="(entry,i) in entries.slice().reverse()" :key="i" class="console-line">
                <span class="console-time">{{ entry.time }}</span><span class="console-level" :class="entry.level">{{ entry.level.toUpperCase() }}</span>
                <span>{{ entry.message }}</span>
              </div>
              <div v-if="!entries.length" class="console-empty">尚无日志记录，连接设备后将显示管理操作。</div>
            </div>
          </section>
        </template>

        <template v-else-if="current === 'settings'">
          <div class="settings-stack">
            <section class="panel">
              <div class="panel-head"><div><h2>ADB 工具</h2><p>选择本地 Platform Tools，或获取 Google 官方组件</p></div><span class="tag" :class="adbPath ? 'tag-success' : 'tag-warn'">{{ adbPath ? '已配置' : '未配置' }}</span></div>
              <label class="field-label">当前 ADB 路径</label>
              <div class="read-only-path"><Code2 :size="17" /><span>{{ adbPath || '尚未检测到 adb.exe' }}</span></div>
              <div class="button-row settings-actions"><button class="btn btn-outline" :disabled="!!loading" @click="chooseAdb"><FolderOpen :size="16" />选择 adb.exe</button>
                <button class="btn btn-primary" :disabled="!!loading" @click="downloadAdb"><Download :size="16" />获取官方 ADB</button></div>
            </section>
            <section class="panel">
              <div class="panel-head"><div><h2>设备电源</h2><p>仅对已选择并授权的设备执行</p></div></div>
              <div class="settings-power">
                <div><span class="settings-action-icon"><RotateCcw :size="20" /></span><span><strong>重启 Android 设备</strong><small>短暂中断设备连接及网页控制</small></span></div>
                <button class="btn btn-outline" :disabled="!selectedReady || !!loading" @click="requestPower('reboot')">重启设备</button>
              </div>
              <div class="settings-power">
                <div><span class="settings-action-icon danger"><Power :size="20" /></span><span><strong>关闭设备电源</strong><small>设备可能需要现场按键才能重新开机</small></span></div>
                <button class="btn btn-destructive-outline" :disabled="!selectedReady || !!loading" @click="requestPower('poweroff')">关机</button>
              </div>
            </section>
            <section class="panel">
              <div class="panel-head"><div><h2>客户端信息</h2><p>Windows 图形化管理器</p></div></div>
              <div class="detail-grid">
                <div class="detail-box"><span>当前版本</span><strong>v{{ envVersion }}</strong></div>
                <div class="detail-box"><span>界面框架</span><strong>Vue 3 · WebView2</strong></div>
                <div class="detail-box"><span>设计系统</span><strong>shadcn-vue 风格</strong></div>
              </div>
            </section>
          </div>
        </template>

        <footer class="page-footer">
          <span>Android Web Desktop · Device Manager</span>
          <span v-if="loading" class="loading-flag"><LoaderCircle :size="14" class="spin" />{{ loading }}</span>
          <span v-else-if="scanning" class="loading-flag"><LoaderCircle :size="14" class="spin" />后台扫描设备中</span>
          <span v-else-if="deviceLoading" class="loading-flag"><LoaderCircle :size="14" class="spin" />读取设备信息中</span>
          <span v-else>本地运行 · 安全操作</span>
        </footer>
      </main>
    </div>

    <div v-if="toast" class="toast" :class="toast.type" role="status">
      <CheckCircle2 v-if="toast.type === 'success'" :size="18" />
      <CircleAlert v-else-if="toast.type === 'error'" :size="18" />
      <Info v-else :size="18" />
      <span>{{ toast.message }}</span>
      <button class="toast-close" @click="toast = null"><X :size="16" /></button>
    </div>

    <div v-if="modal" class="dialog-backdrop" role="presentation" @click.self="closeDialog">
      <div class="dialog-panel" role="dialog" aria-modal="true" :aria-label="modal.title">
        <button class="dialog-close" title="关闭" @click="closeDialog"><X :size="17" /></button>
        <div class="dialog-icon" :class="{ danger: modal.destructive }"><ShieldAlert v-if="modal.destructive" :size="22" /><Info v-else :size="22" /></div>
        <h2>{{ modal.title }}</h2><p class="dialog-description">{{ modal.description }}</p>
        <template v-if="modal.inputLabel">
          <label class="field-label">{{ modal.inputLabel }}</label>
          <input v-model="modalInput" class="dialog-input" :placeholder="modal.inputPlaceholder || ''"
            @keyup.enter="confirmDialog" autofocus />
        </template>
        <div class="dialog-actions"><button class="btn btn-outline" @click="closeDialog">取消</button>
          <button class="btn" :class="modal.destructive ? 'btn-destructive' : 'btn-primary'"
            :disabled="Boolean(modal.expected) && modalInput.trim() !== modal.expected" @click="confirmDialog">{{ modal.confirmText }}</button></div>
      </div>
    </div>

    <div v-if="pendingInstall" class="dialog-backdrop" role="presentation">
      <div class="dialog-panel" role="dialog" aria-modal="true" aria-label="安装完成">
        <div class="dialog-icon success"><Check :size="23" /></div>
        <h2>安装已完成</h2><p class="dialog-description">设备端网页桌面 v{{ pendingInstall.version }} 已部署，管理口令仅在此处显示。</p>
        <div class="result-field"><small>访问地址</small><div><b>{{ pendingInstall.url }}</b><button @click="copyText(pendingInstall.url)"><Copy :size="15" /></button></div></div>
        <div class="result-field"><small>登录口令</small><div><b>{{ pendingInstall.password }}</b><button @click="copyText(pendingInstall.password)"><Copy :size="15" /></button></div></div>
        <button class="btn btn-primary full-button" @click="pendingInstall = null">完成</button>
      </div>
    </div>
  </div>
</template>
