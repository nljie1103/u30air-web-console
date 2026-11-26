//go:build windows

package main

import (
	"bufio"
	"context"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
	"github.com/wailsapp/wails/v2/pkg/runtime"
)

//go:embed build/frontend/* build/worker.exe
var bundled embed.FS

type response struct {
	ID     uint64          `json:"id"`
	OK     bool            `json:"ok"`
	Result json.RawMessage `json:"result"`
	Error  string          `json:"error"`
}

type Worker struct {
	cmd      *exec.Cmd
	stdin    io.WriteCloser
	pending  map[uint64]chan response
	mu       sync.Mutex
	write    sync.Mutex
	next     atomic.Uint64
	critical atomic.Int32
	done     chan struct{}
	folder   string
}

func startWorker() (*Worker, error) {
	folder, err := os.MkdirTemp("", "awd-worker-")
	if err != nil {
		return nil, err
	}
	cleanup := true
	defer func() {
		if cleanup {
			os.RemoveAll(folder)
		}
	}()
	binary, err := bundled.ReadFile("build/worker.exe")
	if err != nil {
		return nil, err
	}
	path := filepath.Join(folder, "worker.exe")
	if err = os.WriteFile(path, binary, 0700); err != nil {
		return nil, err
	}
	cmd := exec.Command(path)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	manager, err := os.Executable()
	if err != nil {
		return nil, err
	}
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "AWD_MANAGER_DIR="+filepath.Dir(manager))
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	if err = cmd.Start(); err != nil {
		return nil, err
	}
	w := &Worker{cmd: cmd, stdin: stdin, pending: make(map[uint64]chan response), done: make(chan struct{}), folder: folder}
	cleanup = false
	go func() {
		scan := bufio.NewScanner(stdout)
		scan.Buffer(make([]byte, 65536), 8<<20)
		for scan.Scan() {
			var r response
			if json.Unmarshal(scan.Bytes(), &r) != nil {
				continue
			}
			w.mu.Lock()
			if c := w.pending[r.ID]; c != nil {
				c <- r
				delete(w.pending, r.ID)
			}
			w.mu.Unlock()
		}
		_ = cmd.Wait()
		close(w.done)
	}()
	return w, nil
}

func (w *Worker) close() {
	_ = w.stdin.Close()
	select {
	case <-w.done:
	case <-time.After(2 * time.Second):
		_ = w.cmd.Process.Kill()
		select {
		case <-w.done:
		case <-time.After(2 * time.Second):
		}
	}
	_ = os.RemoveAll(w.folder)
}

func (w *Worker) call(method string, args []any) (json.RawMessage, error) {
	id := w.next.Add(1)
	switch method {
	case "install_latest", "install_local", "uninstall", "configure_auth", "install_application", "install_official_adb", "uninstall_app", "set_system_app":
		w.critical.Add(1)
		defer w.critical.Add(-1)
	}
	if args == nil {
		args = []any{}
	}
	data, err := json.Marshal(map[string]any{"id": id, "method": method, "args": args})
	if err != nil || len(data) > 60000 {
		return nil, errors.New("操作参数无效或过长")
	}
	ch := make(chan response, 1)
	w.mu.Lock()
	w.pending[id] = ch
	w.mu.Unlock()
	defer func() { w.mu.Lock(); delete(w.pending, id); w.mu.Unlock() }()
	w.write.Lock()
	_, err = w.stdin.Write(append(data, '\n'))
	w.write.Unlock()
	if err != nil {
		return nil, err
	}
	select {
	case r := <-ch:
		if !r.OK {
			return nil, errors.New(r.Error)
		}
		return r.Result, nil
	case <-w.done:
		return nil, errors.New("设备管理后端已退出，请重新打开软件")
	case <-time.After(12 * time.Minute):
		return nil, errors.New("管理操作超时")
	}
}

type Host struct {
	ctx    context.Context
	worker *Worker
	smoke  chan error
}

func (h *Host) Call(method string, args []any) (json.RawMessage, error) {
	switch method {
	case "choose_adb", "choose_local_zip", "choose_apk":
		title, pattern := "选择 APK", "*.apk"
		if method == "choose_adb" {
			title, pattern = "选择 ADB", "adb.exe"
		} else if method == "choose_local_zip" {
			title, pattern = "选择 Android ARM64 ZIP", "*.zip"
		}
		path, err := runtime.OpenFileDialog(h.ctx, runtime.OpenDialogOptions{Title: title, Filters: []runtime.FileFilter{{DisplayName: title, Pattern: pattern}}})
		if err != nil {
			return nil, err
		}
		if method == "choose_adb" && path != "" {
			return h.worker.call("set_adb_path", []any{path})
		}
		return json.Marshal(path)
	default:
		return h.worker.call(method, args)
	}
}

// SmokeResult is only used by the packaged GUI regression test.
func (h *Host) SmokeResult(ok bool, message string) {
	if h.smoke == nil {
		return
	}
	var err error
	if !ok {
		err = errors.New(message)
	}
	select {
	case h.smoke <- err:
	default:
	}
}
func report(args ...any) {
	fmt.Fprintln(os.Stderr, args...)
	if name := os.Getenv("AWD_SMOKE_LOG"); name != "" {
		if f, err := os.OpenFile(name, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0600); err == nil {
			fmt.Fprintln(f, args...)
			f.Close()
		}
	}
}

func main() {
	worker, err := startWorker()
	if err != nil {
		report(err)
		os.Exit(1)
	}
	code := run(worker)
	worker.close()
	os.Exit(code)
}
func run(worker *Worker) int {
	if len(os.Args) > 1 && os.Args[1] == "--self-test" {
		result, err := worker.call("environment", nil)
		if err != nil {
			report(err)
			return 1
		}
		var info map[string]any
		if json.Unmarshal(result, &info) != nil || info["version"] == nil {
			return 1
		}
		if _, err = worker.call("exec_command", nil); err == nil {
			return 1
		}
		report("Worker RPC self-test passed")
		return 0
	}
	assets, err := fs.Sub(bundled, "build/frontend")
	if err != nil {
		return 1
	}
	h := &Host{worker: worker}
	smoke := len(os.Args) > 1 && os.Args[1] == "--gui-smoke-test"
	if smoke {
		h.smoke = make(chan error, 1)
	}
	m := windows.DefaultMessages()
	m.InstallationRequired = "需要 Microsoft WebView2 运行库。确认后自动下载并安装。"
	m.UpdateRequired = "需要更新 WebView2 运行库。确认后自动下载安装。"
	m.MissingRequirements = "安装运行组件"
	m.FailedToInstall = "WebView2 安装失败，请检查网络或系统权限后重试。"
	var smokeErr error
	var smokeOnce sync.Once
	err = wails.Run(&options.App{
		Title: "Android Web Desktop · 设备管理器", Width: 1400, Height: 900, MinWidth: 960, MinHeight: 600,
		AssetServer:      &assetserver.Options{Assets: assets},
		BackgroundColour: options.NewRGB(248, 250, 252),
		Windows:          &windows.Options{Theme: windows.Light, Messages: m},
		DragAndDrop:      &options.DragAndDrop{DisableWebViewDrop: true},
		Bind:             []interface{}{h},
		OnStartup:        func(ctx context.Context) { h.ctx = ctx },
		OnBeforeClose: func(ctx context.Context) bool {
			if worker.critical.Load() == 0 {
				return false
			}
			_, _ = runtime.MessageDialog(ctx, runtime.MessageDialogOptions{Type: runtime.InfoDialog, Title: "设备操作进行中", Message: "请在当前安装或部署操作完成后关闭窗口。"})
			return true
		},
		OnDomReady: func(ctx context.Context) {
			if !smoke {
				return
			}
			smokeOnce.Do(func() {
				go func() {
					x, y := runtime.WindowGetPosition(ctx)
					for i := 0; i < 4; i++ {
						runtime.WindowSetPosition(ctx, x+i*12, y+i*8)
						time.Sleep(80 * time.Millisecond)
					}
					runtime.WindowExecJS(ctx, "window.__awdSmokeTest = true; window.dispatchEvent(new Event('awdsmoke'));")
					select {
					case smokeErr = <-h.smoke:
					case <-time.After(35 * time.Second):
						smokeErr = errors.New("WebView2 GUI test timed out")
					}
					runtime.Quit(ctx)
				}()
			})
		},
	})
	if smoke && err == nil && smokeErr == nil {
		report("WebView2 GUI smoke test passed")
	}
	if err != nil || smokeErr != nil {
		report(err, smokeErr)
		return 1
	}
	return 0
}
