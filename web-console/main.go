package main

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

var version = "dev"

const repo = "nljie1103/u30air-web-console"
const assetName = "android-web-desktop-arm64.zip"
const stateDefault = "/data/local/tmp/android-web-desktop"
const maxPackageSize = 35 << 20
const maxScreenSize = 20 << 20

type app struct {
	addr       string
	state      string
	password   string
	secret     []byte
	httpClient *http.Client
	updater    sync.Mutex
	updating   bool
	metadata   metadataStore
	auth       authState
	apk        apkState
	login      loginBudget
}

func randomBytes(n int) []byte {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		log.Fatal(err)
	}
	return b
}
func passwordAt(state string) string {
	if err := os.MkdirAll(state, 0700); err != nil {
		log.Fatal(err)
	}
	path := filepath.Join(state, "password.txt")
	b, err := os.ReadFile(path)
	if err == nil {
		// No password length/complexity rule: simple user-selected passwords
		// are allowed, including one-character passwords.
		p := strings.TrimSuffix(string(b), "\n")
		if p == "" {
			log.Fatal("password file is empty")
		}
		return p
	}
	if !errors.Is(err, os.ErrNotExist) {
		log.Fatal(err)
	}
	p := hex.EncodeToString(randomBytes(16))
	// O_EXCL prevents accidental replacement during concurrent starts.
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if errors.Is(err, os.ErrExist) {
		return passwordAt(state)
	}
	if err != nil {
		log.Fatal(err)
	}
	if _, err = f.WriteString(p + "\n"); err != nil {
		f.Close()
		log.Fatal(err)
	}
	if err = f.Close(); err != nil {
		log.Fatal(err)
	}
	log.Print("管理口令已生成，请从设备本地读取 password.txt")
	return p
}
func (a *app) mac(s string) []byte {
	a.auth.mu.RLock()
	secret := a.auth.secret
	if len(secret) == 0 {
		secret = a.secret
	}
	h := hmac.New(sha256.New, secret)
	a.auth.mu.RUnlock()
	_, _ = h.Write([]byte(s))
	return h.Sum(nil)
}
func (a *app) cookieValue() string {
	v := strconv.FormatInt(time.Now().Unix(), 10) + "." + base64.RawURLEncoding.EncodeToString(randomBytes(16))
	return v + "." + base64.RawURLEncoding.EncodeToString(a.mac(v))
}
func (a *app) authed(r *http.Request) bool {
	if !a.authEnabled() {
		return true
	}
	c, e := r.Cookie("awd-session")
	if e != nil {
		return false
	}
	parts := strings.Split(c.Value, ".")
	if len(parts) != 3 {
		return false
	}
	ts, e := strconv.ParseInt(parts[0], 10, 64)
	if e != nil {
		return false
	}
	elapsed := time.Since(time.Unix(ts, 0))
	if elapsed < -time.Minute || elapsed > 24*time.Hour {
		return false
	}
	sig, e := base64.RawURLEncoding.DecodeString(parts[2])
	return e == nil && hmac.Equal(sig, a.mac(parts[0]+"."+parts[1]))
}
func (a *app) validHost(r *http.Request) bool {
	// Block DNS rebinding; intended entry point is the configured device IP only.
	return r.Host == a.addr
}
func (a *app) validMutation(r *http.Request) bool {
	if maintenanceActive(a.state) || r.Method != "POST" || !a.authed(r) || r.Header.Get("X-Desktop-Action") != "1" {
		return false
	}
	origin := r.Header.Get("Origin")
	return origin == "" || origin == "http://"+a.addr
}
func respond(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func fail(w http.ResponseWriter, status int, msg string) {
	respond(w, status, map[string]string{"error": msg})
}
func runWith(ctx context.Context, exe string, args ...string) (string, error) {
	cctx, cancel := context.WithTimeout(ctx, 8*time.Second)
	defer cancel()
	out, e := exec.CommandContext(cctx, exe, args...).CombinedOutput()
	return strings.TrimSpace(string(out)), e
}
func prop(ctx context.Context, key string) string {
	v, _ := runWith(ctx, "/system/bin/getprop", key)
	return v
}

var packageRe = regexp.MustCompile("^([a-zA-Z_][a-zA-Z0-9_]*)([.][a-zA-Z_][a-zA-Z0-9_]*)+$")

func installedApps(ctx context.Context) ([]string, bool, error) {
	v, err := runWith(ctx, "/system/bin/pm", "list", "packages", "-3")
	if err != nil {
		return nil, false, fmt.Errorf("读取 Android 应用列表失败: %w", err)
	}
	return parseInstalledApps(v)
}
func parseInstalledApps(v string) ([]string, bool, error) {
	result := make([]string, 0)
	seen := make(map[string]bool)
	for _, line := range strings.Split(v, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		if !strings.HasPrefix(line, "package:") {
			return nil, false, errors.New("Android 包管理器返回异常")
		}
		name := strings.TrimPrefix(line, "package:")
		if !packageRe.MatchString(name) || seen[name] {
			continue
		}
		seen[name] = true
		if len(result) >= 300 {
			return result, true, nil
		}
		result = append(result, name)
	}
	return result, false, nil
}
func (a *app) handler() http.Handler {
	mux := http.NewServeMux()
	staticAssets(mux)
	a.apkRoutes(mux)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" {
			fail(w, 405, "method not allowed")
			return
		}
		respond(w, 200, map[string]string{"status": "ok", "version": version})
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		if !a.authed(r) {
			_, _ = io.WriteString(w, loginPage)
			return
		}
		_, _ = io.WriteString(w, desktopPage)
	})
	mux.HandleFunc("/api/login", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.Header.Get("Origin") != "" && r.Header.Get("Origin") != "http://"+a.addr {
			fail(w, 403, "forbidden")
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, 2048)
		var in struct{ Password string }
		if json.NewDecoder(r.Body).Decode(&in) != nil {
			fail(w, 400, "invalid json")
			return
		}
		if a.authEnabled() {
			host, _, err := net.SplitHostPort(r.RemoteAddr)
			if err != nil {
				host = r.RemoteAddr
			}
			ok, limited := a.login.attempt(host, time.Now(), func() bool { return a.checkPassword(in.Password) })
			if limited {
				w.Header().Set("Retry-After", "30")
				fail(w, 429, "登录尝试过多，请稍后重试")
				return
			}
			if !ok {
				fail(w, 401, "管理口令不正确")
				return
			}
		}
		http.SetCookie(w, &http.Cookie{Name: "awd-session", Value: a.cookieValue(), HttpOnly: true, SameSite: http.SameSiteStrictMode, Path: "/", MaxAge: 86400})
		respond(w, 200, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("/api/logout", func(w http.ResponseWriter, r *http.Request) {
		if !a.validMutation(r) {
			fail(w, 403, "forbidden")
			return
		}
		http.SetCookie(w, &http.Cookie{Name: "awd-session", Value: "", HttpOnly: true, SameSite: http.SameSiteStrictMode, Path: "/", MaxAge: -1})
		respond(w, 200, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("/api/auth/config", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		switch r.Method {
		case "GET":
			respond(w, 200, map[string]any{"enabled": a.authEnabled()})
		case "POST":
			if !a.validMutation(r) {
				fail(w, 403, "forbidden")
				return
			}
			r.Body = http.MaxBytesReader(w, r.Body, 8<<10)
			var data struct {
				Enabled  *bool
				Password string
			}
			if err := json.NewDecoder(r.Body).Decode(&data); err != nil || data.Enabled == nil {
				fail(w, 400, "密码设置格式不正确")
				return
			}
			a.updater.Lock()
			if a.updating {
				a.updater.Unlock()
				fail(w, 409, "设备正在安装或更新")
				return
			}
			defer a.updater.Unlock()
			if err := a.setAuthConfig(*data.Enabled, data.Password); err != nil {
				fail(w, 400, err.Error())
				return
			}
			respond(w, 200, map[string]any{"enabled": *data.Enabled, "status": "saved"})
		default:
			fail(w, 405, "method not allowed")
		}
	})
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		if r.Method != "GET" {
			fail(w, 405, "method not allowed")
			return
		}
		respond(w, 200, map[string]any{
			"version":      version,
			"manufacturer": prop(r.Context(), "ro.product.manufacturer"),
			"model":        prop(r.Context(), "ro.product.model"),
			"android":      prop(r.Context(), "ro.build.version.release"),
			"abi":          prop(r.Context(), "ro.product.cpu.abi"),
		})
	})
	mux.HandleFunc("/api/metrics", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		if r.Method != "GET" {
			fail(w, 405, "method not allowed")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		respond(w, 200, measureDevice(ctx))
	})
	mux.HandleFunc("/api/apps", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		if r.Method != "GET" {
			fail(w, 405, "method not allowed")
			return
		}
		packages, truncated, err := installedApps(r.Context())
		if err != nil {
			fail(w, 502, err.Error())
			return
		}
		if r.URL.Query().Get("refresh") == "1" {
			a.metadata.invalidate()
		}
		respond(w, 200, map[string]any{"packages": packages, "truncated": truncated})
	})
	// APK label/icon metadata is loaded lazily, after the lightweight app list.
	// Access is restricted to authenticated users; no external icon provider.
	mux.HandleFunc("/api/app-info", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		if r.Method != "GET" {
			fail(w, 405, "method not allowed")
			return
		}
		pkg := r.URL.Query().Get("package")
		if !packageRe.MatchString(pkg) {
			fail(w, 400, "invalid package name")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 12*time.Second)
		defer cancel()
		meta := a.metadata.get(ctx, a.state, pkg)
		respond(w, 200, map[string]any{
			"package": meta.Package, "label": meta.Label, "hasIcon": meta.HasIcon,
		})
	})
	mux.HandleFunc("/api/app-icon", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		if r.Method != "GET" {
			fail(w, 405, "method not allowed")
			return
		}
		pkg := r.URL.Query().Get("package")
		if !packageRe.MatchString(pkg) {
			fail(w, 400, "invalid package name")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 12*time.Second)
		defer cancel()
		meta := a.metadata.get(ctx, a.state, pkg)
		if !meta.HasIcon || len(meta.Icon) < 8 {
			fail(w, 404, "icon unavailable")
			return
		}
		w.Header().Set("Content-Type", "image/png")
		w.Header().Set("Content-Length", strconv.Itoa(len(meta.Icon)))
		_, _ = w.Write(meta.Icon)
	})
	mux.HandleFunc("/api/screen", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		if r.Method != "GET" {
			fail(w, 405, "method not allowed")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 7*time.Second)
		defer cancel()
		b, e := exec.CommandContext(ctx, "/system/bin/screencap", "-p").Output()
		if e != nil || len(b) < 24 || len(b) > maxScreenSize || !isPNG(b) {
			fail(w, 503, "当前设备无法提供屏幕画面")
			return
		}
		w.Header().Set("Content-Type", "image/png")
		_, _ = w.Write(b)
	})
	mux.HandleFunc("/api/control", func(w http.ResponseWriter, r *http.Request) {
		if !a.validMutation(r) {
			fail(w, 403, "forbidden")
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, 2048)
		var in struct {
			Action  string
			Package string
			X       int
			Y       int
			X2      int
			Y2      int
			Confirm string
		}
		if json.NewDecoder(r.Body).Decode(&in) != nil {
			fail(w, 400, "invalid request")
			return
		}
		valid := func(x int) bool { return x >= 0 && x <= 16384 }
		var args []string
		exe := "/system/bin/input"
		switch in.Action {
		case "home":
			args = []string{"keyevent", "3"}
		case "back":
			args = []string{"keyevent", "4"}
		case "recents":
			args = []string{"keyevent", "187"}
		case "wake":
			args = []string{"keyevent", "224"} // KEYCODE_WAKEUP: only wakes, does not unlock
		case "screenoff":
			args = []string{"keyevent", "223"} // KEYCODE_SLEEP: sleep without power toggle
		case "tap":
			if !valid(in.X) || !valid(in.Y) {
				fail(w, 400, "invalid coordinates")
				return
			}
			args = []string{"tap", strconv.Itoa(in.X), strconv.Itoa(in.Y)}
		case "swipe":
			if !valid(in.X) || !valid(in.Y) || !valid(in.X2) || !valid(in.Y2) {
				fail(w, 400, "invalid coordinates")
				return
			}
			args = []string{"swipe", strconv.Itoa(in.X), strconv.Itoa(in.Y), strconv.Itoa(in.X2), strconv.Itoa(in.Y2), "320"}
		case "reboot", "shutdown":
			expected := "重启"
			if in.Action == "shutdown" {
				expected = "关机"
			}
			if in.Confirm != expected {
				fail(w, 400, "请确认操作：必须填写“"+expected+"”")
				return
			}
			// Use Android's svc power manager. This does not silently elevate
			// privileges; some OEM builds can restrict these operations.
			if err := executePowerAction(r.Context(), in.Action, runWith); err != nil {
				log.Printf("power %s rejected: %v", in.Action, err)
				fail(w, 503, err.Error())
				return
			}
			respond(w, 200, map[string]string{"status": "sent"})
			return
		case "launch":
			if !packageRe.MatchString(in.Package) {
				fail(w, 400, "invalid package name")
				return
			}
			if err := launchInstalledApp(r.Context(), in.Package, runWith); err != nil {
				log.Printf("desktop launch %q failed: %v", in.Package, err)
				fail(w, 503, err.Error())
				return
			}
			respond(w, 200, map[string]string{"status": "sent"})
			return
		default:
			fail(w, 400, "unknown action")
			return
		}
		output, e := runWith(r.Context(), exe, args...)
		if e != nil || strings.Contains(output, "No activities found") || strings.Contains(output, "monkey aborted") {
			log.Printf("desktop action %q failed: %v %s", in.Action, e, output)
			fail(w, 503, "操作未成功，可能是应用没有启动入口或系统限制了输入权限")
			return
		}
		respond(w, 200, map[string]string{"status": "sent"})
	})
	mux.HandleFunc("/api/novnc/status", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		if r.Method != "GET" {
			fail(w, 405, "method not allowed")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel()
		url, reason := probeNoVNC(ctx, a.addr)
		respond(w, 200, map[string]any{
			"available": url != "", "url": url, "reason": reason,
		})
	})
	mux.HandleFunc("/api/update/check", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		if r.Method != "GET" {
			fail(w, 405, "method not allowed")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()
		rel, e := fetchRelease(ctx, a.httpClient)
		if e != nil {
			fail(w, 502, "检查更新失败："+e.Error())
			return
		}
		respond(w, 200, map[string]any{"current": version, "latest": rel.Version, "available": newer(rel.Version, version), "notes": rel.Notes})
	})
	mux.HandleFunc("/api/update/apply", func(w http.ResponseWriter, r *http.Request) {
		if !a.validMutation(r) {
			fail(w, 403, "forbidden")
			return
		}
		a.updater.Lock()
		if a.updating {
			a.updater.Unlock()
			fail(w, 409, "更新任务正在执行")
			return
		}
		a.updating = true
		a.updater.Unlock()
		restart := false
		defer func() {
			if !restart {
				a.updater.Lock()
				a.updating = false
				a.updater.Unlock()
			}
		}()
		ctx, cancel := context.WithTimeout(context.Background(), 100*time.Second)
		defer cancel()
		rel, e := fetchRelease(ctx, a.httpClient)
		if e == nil && !newer(rel.Version, version) {
			e = errors.New("当前没有更新版本")
		}
		if e == nil {
			e = a.install(ctx, rel)
		}
		if e != nil {
			log.Printf("update error: %v", e)
			fail(w, 502, "更新失败："+e.Error())
			return
		}
		restart = true
		respond(w, 200, map[string]any{"status": "restarting", "version": rel.Version})
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !a.validHost(r) {
			fail(w, 403, "invalid host")
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
		mux.ServeHTTP(w, r)
	})
}
func isPNG(b []byte) bool {
	return len(b) >= 8 && string(b[:8]) == "\x89PNG\r\n\x1a\n"
}
func main() {
	addr := flag.String("listen", "192.168.0.1:8765", "设备局域网 IP:端口")
	state := flag.String("state-dir", stateDefault, "程序数据目录")
	helper := flag.Bool("update-helper", false, "内部更新进程")
	parentPID := flag.Int("parent-pid", 0, "更新进程父 PID")
	parentStart := flag.String("parent-start", "", "更新父进程启动标识")
	serviceAction := flag.String("service-action", "", "内部服务控制")
	checkVersion := flag.String("check-health", "", "等待指定版本就绪")
	deployVersion := flag.String("deploy-version", "", "内部命令行部署事务")
	previous := flag.String("previous", "", "上一版本相对路径")
	expected := flag.String("expected", "", "目标版本")
	flag.Parse()
	ip, port, e := net.SplitHostPort(*addr)
	if e != nil {
		log.Fatal(e)
	}
	n, portErr := strconv.Atoi(port)
	if portErr != nil || n < 1024 || n > 65535 || strconv.Itoa(n) != port {
		log.Fatal("无效监听端口")
	}
	parsed := net.ParseIP(ip)
	if parsed == nil || parsed.To4() == nil || !parsed.IsPrivate() || parsed.IsLoopback() || parsed.IsUnspecified() {
		log.Fatal("请指定设备的私有局域网 IPv4；不允许绑定公网或所有网卡")
	}
	if *helper {
		updateHelper(*addr, *state, *previous, *expected, *parentPID, *parentStart)
		return
	}
	if *deployVersion != "" {
		if err := cliDeploy(*state, *addr, *deployVersion); err != nil {
			log.Fatal(err)
		}
		return
	}
	if *serviceAction != "" {
		if err := serviceControl(*state, *serviceAction); err != nil {
			log.Fatal(err)
		}
		return
	}
	if *checkVersion != "" {
		if !waitHealth(*addr, *checkVersion, 20) {
			log.Fatal("服务健康检查失败")
		}
		return
	}
	if err := os.MkdirAll(*state, 0700); err != nil {
		log.Fatal(err)
	}
	daemonLock, err := lockFile(*state, "server.lock")
	if err != nil {
		log.Fatal("another managed service is running:", err)
	}
	defer daemonLock.Close()
	githubClient, err := githubHTTPClient()
	if err != nil {
		log.Fatal("GitHub HTTPS 信任配置错误：", err)
	}
	legacyPassword := passwordAt(*state)
	authCfg, err := loadAuthConfig(*state, legacyPassword)
	if err != nil {
		log.Fatal("设备登录配置无效：", err)
	}
	a := &app{addr: *addr, state: *state, password: legacyPassword, secret: randomBytes(32), httpClient: githubClient}
	a.auth.password = authCfg.Password
	a.auth.disabled = !authCfg.Enabled
	a.auth.secret = randomBytes(32)
	if err := writeServiceIdentity(*state); err != nil {
		log.Fatal(err)
	}
	if exe, err := os.Readlink("/proc/self/exe"); err == nil && servicePath(*state, exe) {
		if err = syncServiceScripts(*state); err != nil {
			log.Fatal("更新管理脚本失败：", err)
		}
	}
	var serverReady atomic.Bool
	if err := startLocalHealth(*state, &serverReady); err != nil {
		log.Fatal("cannot launch local readiness check: ", err)
	}
	server := &http.Server{Addr: *addr, Handler: a.handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 100 * time.Second, IdleTimeout: 20 * time.Second, MaxHeaderBytes: 8192}
	for {
		listener, err := net.Listen("tcp", *addr)
		if err != nil {
			serverReady.Store(false)
			log.Printf("等待局域网 IP %s：%v", *addr, err)
			time.Sleep(3 * time.Second)
			continue
		}
		serverReady.Store(true)
		log.Printf("Android Web Desktop %s listening %s", version, *addr)
		log.Fatal(server.Serve(listener))
	}
}
