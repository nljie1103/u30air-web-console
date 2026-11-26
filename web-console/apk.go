package main

import (
	"archive/zip"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const maxAPKSize = 128 << 20

type apkState struct {
	mu              sync.Mutex
	stage           string
	received, total int64
}

func (s *apkState) progress(stage string, received, total int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.stage, s.received, s.total = stage, received, total
}

func (s *apkState) snapshot() map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	return map[string]any{"stage": s.stage, "received": s.received, "total": s.total}
}

func apkURL(raw string) (*url.URL, error) {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || (u.Port() != "" && u.Port() != "443") {
		return nil, errors.New("请输入公开 HTTPS APK 下载链接（仅 443 端口）")
	}
	return u, nil
}

var blockedAPKNetworks = []netip.Prefix{
	netip.MustParsePrefix("0.0.0.0/8"), netip.MustParsePrefix("100.64.0.0/10"),
	netip.MustParsePrefix("192.0.0.0/24"), netip.MustParsePrefix("192.0.2.0/24"),
	netip.MustParsePrefix("198.18.0.0/15"), netip.MustParsePrefix("198.51.100.0/24"),
	netip.MustParsePrefix("203.0.113.0/24"), netip.MustParsePrefix("240.0.0.0/4"),
	netip.MustParsePrefix("64:ff9b::/96"), netip.MustParsePrefix("64:ff9b:1::/48"),
	netip.MustParsePrefix("2001::/23"), netip.MustParsePrefix("2001:db8::/32"),
	netip.MustParsePrefix("2002::/16"),
}

func publicAPKIP(ip netip.Addr) bool {
	ip = ip.Unmap()
	if (ip.Is6() && !netip.MustParsePrefix("2000::/3").Contains(ip)) || !ip.IsGlobalUnicast() || ip.IsPrivate() || ip.IsLoopback() || ip.IsLinkLocalUnicast() || ip.Zone() != "" {
		return false
	}
	for _, p := range blockedAPKNetworks {
		if p.Contains(ip) {
			return false
		}
	}
	return true
}

// Resolve and dial the validated address directly, avoiding DNS rebinding.
// Disable proxy inheritance so a proxy cannot bypass destination validation.
func apkDial(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil || port != "443" {
		return nil, errors.New("下载目标端口无效")
	}
	ips, err := net.DefaultResolver.LookupNetIP(ctx, "ip", host)
	if err != nil {
		return nil, err
	}
	if len(ips) == 0 {
		return nil, errors.New("下载地址无法解析")
	}
	for _, ip := range ips {
		if !publicAPKIP(ip) {
			return nil, errors.New("不允许下载局域网或保留地址")
		}
	}
	d := net.Dialer{Timeout: 10 * time.Second}
	for _, ip := range ips {
		conn, e := d.DialContext(ctx, network, net.JoinHostPort(ip.String(), port))
		if e == nil {
			return conn, nil
		}
		err = e
	}
	return nil, err
}

func apkHTTPClient() (*http.Client, error) {
	c, err := githubHTTPClient()
	if err != nil {
		return nil, err
	}
	t := c.Transport.(*http.Transport)
	t.Proxy = nil
	t.DialContext = apkDial
	c.Timeout = 4 * time.Minute
	c.CheckRedirect = func(r *http.Request, via []*http.Request) error {
		if len(via) >= 8 {
			return errors.New("下载跳转次数过多")
		}
		_, err := apkURL(r.URL.String())
		return err
	}
	return c, nil
}

func copyAPK(dst io.Writer, src io.Reader, total int64, progress func(int64, int64)) error {
	if total > maxAPKSize {
		return errors.New("APK 超过 128 MiB")
	}
	buf := make([]byte, 64<<10)
	var count int64
	for {
		n, e := src.Read(buf)
		if n > 0 {
			count += int64(n)
			if count > maxAPKSize {
				return errors.New("APK 超过 128 MiB")
			}
			if _, err := dst.Write(buf[:n]); err != nil {
				return err
			}
			progress(count, total)
		}
		if e == io.EOF {
			break
		}
		if e != nil {
			return e
		}
	}
	if count == 0 {
		return errors.New("APK 文件为空")
	}
	return nil
}

func validateAPK(path string) error {
	z, err := zip.OpenReader(path)
	if err != nil {
		return errors.New("文件不是有效 APK")
	}
	defer z.Close()
	for _, f := range z.File {
		if f.Name == "AndroidManifest.xml" && f.UncompressedSize64 > 0 {
			return nil
		}
	}
	return errors.New("仅支持包含 AndroidManifest.xml 的单文件 APK")
}

func (a *app) apkEnabled() bool {
	b, err := os.ReadFile(filepath.Join(a.state, "apk-install.enabled"))
	return err == nil && string(b) == "1"
}

func (a *app) apkRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/api/apk/config", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		if r.Method == "GET" {
			respond(w, 200, map[string]bool{"enabled": a.apkEnabled()})
			return
		}
		if !a.validMutation(r) {
			fail(w, 403, "forbidden")
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, 1024)
		var in struct{ Enabled *bool }
		if json.NewDecoder(r.Body).Decode(&in) != nil || in.Enabled == nil {
			fail(w, 400, "请选择启用或关闭")
			return
		}
		path := filepath.Join(a.state, "apk-install.enabled")
		var err error
		if *in.Enabled {
			err = os.WriteFile(path, []byte("1"), 0600)
		} else {
			err = os.Remove(path)
			if os.IsNotExist(err) {
				err = nil
			}
		}
		if err != nil {
			fail(w, 500, "无法保存安装设置")
			return
		}
		respond(w, 200, map[string]bool{"enabled": *in.Enabled})
	})
	mux.HandleFunc("/api/apk/progress", func(w http.ResponseWriter, r *http.Request) {
		if !a.authed(r) {
			fail(w, 401, "login required")
			return
		}
		if r.Method != "GET" {
			fail(w, 405, "method not allowed")
			return
		}
		respond(w, 200, a.apk.snapshot())
	})
	mux.HandleFunc("/api/apk/install", func(w http.ResponseWriter, r *http.Request) {
		if !a.validMutation(r) || !a.apkEnabled() {
			fail(w, 403, "请先启用网页 APK 安装")
			return
		}
		a.updater.Lock()
		if a.updating {
			a.updater.Unlock()
			fail(w, 409, "已有安装或更新任务")
			return
		}
		a.updating = true
		a.updater.Unlock()
		defer func() { a.updater.Lock(); a.updating = false; a.updater.Unlock() }()
		rc := http.NewResponseController(w)
		_ = rc.SetReadDeadline(time.Now().Add(5 * time.Minute))
		_ = rc.SetWriteDeadline(time.Now().Add(7 * time.Minute))
		ctx, cancel := context.WithTimeout(r.Context(), 6*time.Minute)
		defer cancel()
		a.apk.progress("接收文件", 0, 0)
		err := a.installAPK(ctx, w, r)
		if err != nil {
			a.apk.progress("安装失败", 0, 0)
			fail(w, 400, err.Error())
			return
		}
		a.metadata.invalidate()
		a.apk.progress("安装完成", 0, 0)
		respond(w, 200, map[string]string{"status": "installed"})
	})
}

func (a *app) installAPK(ctx context.Context, w http.ResponseWriter, r *http.Request) error {
	// A fixed generated filename in the shell-readable state directory.
	f, err := os.CreateTemp(a.state, "apk-*.apk")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	defer f.Close()
	var src io.Reader
	var total int64
	switch r.Header.Get("Content-Type") {
	case "application/json":
		r.Body = http.MaxBytesReader(w, r.Body, 8192)
		var in struct{ URL string }
		if json.NewDecoder(r.Body).Decode(&in) != nil {
			return errors.New("下载链接格式错误")
		}
		u, err := apkURL(in.URL)
		if err != nil {
			return err
		}
		c, err := apkHTTPClient()
		if err != nil {
			return err
		}
		defer c.CloseIdleConnections()
		req, err := http.NewRequestWithContext(ctx, "GET", u.String(), nil)
		if err != nil {
			return err
		}
		a.apk.progress("设备正在下载", 0, 0)
		res, err := c.Do(req)
		if err != nil {
			return errors.New("设备下载失败：请检查网络、证书和下载地址")
		}
		defer res.Body.Close()
		if res.StatusCode != 200 {
			return fmt.Errorf("下载失败：HTTP %d", res.StatusCode)
		}
		src, total = res.Body, res.ContentLength
	case "application/vnd.android.package-archive":
		src, total = http.MaxBytesReader(w, r.Body, maxAPKSize), r.ContentLength
	default:
		return errors.New("不支持的上传类型")
	}
	if err = copyAPK(f, src, total, func(n, t int64) { a.apk.progress("传输 APK", n, t) }); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if err = validateAPK(f.Name()); err != nil {
		return err
	}
	// Package manager verifies the manifest, signature, ABI and update rules.
	a.apk.progress("Android 正在安装", 0, 0)
	installCtx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	out, err := exec.CommandContext(installCtx, "pm", "install", "-r", f.Name()).CombinedOutput()
	result := strings.TrimSpace(string(out))
	if err != nil || result != "Success" {
		return fmt.Errorf("Android 安装失败：%s", result)
	}
	return nil
}
