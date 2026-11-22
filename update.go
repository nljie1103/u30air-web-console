package main

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
)

type release struct {
	Version string
	Notes   string
	URL     string
	Digest  string
}

var releaseTagRe = regexp.MustCompile("^v([0-9]+)[.]([0-9]+)[.]([0-9]+)$")

func newer(a, b string) bool {
	parse := func(v string) [3]int {
		v = strings.TrimPrefix(v, "v")
		p := strings.Split(v, ".")
		o := [3]int{}
		if len(p) != 3 {
			return o
		}
		for i := 0; i < 3; i++ {
			o[i], _ = strconv.Atoi(p[i])
		}
		return o
	}
	x, y := parse(a), parse(b)
	for i := 0; i < 3; i++ {
		if x[i] > y[i] {
			return true
		}
		if x[i] < y[i] {
			return false
		}
	}
	return false
}
func fetchRelease(ctx context.Context, c *http.Client) (release, error) {
	u := "https://api.github.com/repos/" + repo + "/releases/latest"
	req, err := http.NewRequestWithContext(ctx, "GET", u, nil)
	if err != nil {
		return release{}, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "Android-Web-Desktop/"+version)
	resp, err := c.Do(req)
	if err != nil {
		return release{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return release{}, fmt.Errorf("GitHub HTTP %d", resp.StatusCode)
	}
	var data struct {
		Tag    string `json:"tag_name"`
		Body   string `json:"body"`
		Assets []struct {
			Name   string `json:"name"`
			URL    string `json:"browser_download_url"`
			Digest string `json:"digest"`
		} `json:"assets"`
	}
	if err = json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&data); err != nil {
		return release{}, err
	}
	if !releaseTagRe.MatchString(data.Tag) {
		return release{}, errors.New("Release 版本号无效")
	}
	rel := release{Version: strings.TrimPrefix(data.Tag, "v"), Notes: data.Body}
	if len(rel.Notes) > 8000 {
		rel.Notes = rel.Notes[:8000]
	}
	for _, asset := range data.Assets {
		if asset.Name == assetName {
			rel.URL = asset.URL
			rel.Digest = asset.Digest
			break
		}
	}
	if rel.URL == "" {
		return release{}, errors.New("Release 缺少 Android ARM64 安装包")
	}
	parsed, err := url.Parse(rel.URL)
	if err != nil || parsed.Scheme != "https" || parsed.Host != "github.com" || !strings.HasPrefix(parsed.Path, "/"+repo+"/releases/download/") {
		return release{}, errors.New("下载来源不合法")
	}
	if len(rel.Digest) != 71 || !strings.HasPrefix(rel.Digest, "sha256:") {
		return release{}, errors.New("缺少安装包 SHA256 摘要")
	}
	if _, err := hex.DecodeString(strings.TrimPrefix(rel.Digest, "sha256:")); err != nil {
		return release{}, errors.New("SHA256 摘要格式不正确")
	}
	return rel, nil
}
func unpackBinary(data []byte) ([]byte, error) {
	r, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, err
	}
	for _, f := range r.File {
		if f.Name != "desktopd" {
			continue
		}
		if f.UncompressedSize64 == 0 || f.UncompressedSize64 > 20<<20 {
			return nil, errors.New("可执行文件大小不合法")
		}
		rc, err := f.Open()
		if err != nil {
			return nil, err
		}
		b, err := io.ReadAll(io.LimitReader(rc, 20<<20+1))
		rc.Close()
		if err != nil || len(b) == 0 || len(b) > 20<<20 {
			return nil, errors.New("可执行文件超出限制")
		}
		if len(b) < 4 || string(b[:4]) != "\x7fELF" {
			return nil, errors.New("不是有效的 ELF 程序")
		}
		return b, nil
	}
	return nil, errors.New("ZIP 不包含 desktopd")
}
func symlinkSwap(state, target string) error {
	curr := filepath.Join(state, "current")
	next := curr + ".new"
	_ = os.Remove(next)
	if err := os.Symlink(target, next); err != nil {
		return err
	}
	return os.Rename(next, curr)
}
func (a *app) install(ctx context.Context, rel release) error {
	previous, err := os.Readlink(filepath.Join(a.state, "current"))
	if err != nil {
		return errors.New("未找到当前安装版本；请先执行一次安装器")
	}
	req, err := http.NewRequestWithContext(ctx, "GET", rel.URL, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "Android-Web-Desktop/"+version)
	resp, err := a.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("安装包下载失败 (HTTP %d)", resp.StatusCode)
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, maxPackageSize+1))
	if err != nil {
		return err
	}
	if len(b) > maxPackageSize {
		return errors.New("安装包超过大小限制")
	}
	got := sha256.Sum256(b)
	want := strings.TrimPrefix(rel.Digest, "sha256:")
	if subtle.ConstantTimeCompare([]byte(hex.EncodeToString(got[:])), []byte(want)) != 1 {
		return errors.New("SHA256 校验失败")
	}
	binary, err := unpackBinary(b)
	if err != nil {
		return err
	}
	targetRel := filepath.Join("releases", rel.Version, "desktopd")
	target := filepath.Join(a.state, targetRel)
	if err = os.MkdirAll(filepath.Dir(target), 0700); err != nil {
		return err
	}
	tmp := target + ".part"
	if err = os.WriteFile(tmp, binary, 0700); err != nil {
		return err
	}
	if err = os.Chmod(tmp, 0700); err != nil {
		return err
	}
	if err = os.Rename(tmp, target); err != nil {
		return err
	}
	if err = symlinkSwap(a.state, targetRel); err != nil {
		return err
	}
	oldbin := filepath.Join(a.state, previous)
	if _, err = os.Stat(oldbin); err != nil {
		_ = symlinkSwap(a.state, previous)
		return errors.New("找不到旧版本，更新已取消")
	}
	out, err := os.OpenFile(filepath.Join(a.state, "update.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		_ = symlinkSwap(a.state, previous)
		return err
	}
	cmd := exec.Command(oldbin, "-update-helper", "-previous", previous, "-expected", rel.Version, "-listen", a.addr, "-state-dir", a.state)
	cmd.Stdout = out
	cmd.Stderr = out
	cmd.Stdin = nil
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err = cmd.Start(); err != nil {
		_ = out.Close()
		_ = symlinkSwap(a.state, previous)
		return err
	}
	_ = cmd.Process.Release()
	_ = out.Close()
	return nil
}
func updateHelper(addr, state, previous, expected string) {
	time.Sleep(3 * time.Second)
	pidPath := filepath.Join(state, "server.pid")
	if b, e := os.ReadFile(pidPath); e == nil {
		if pid, e := strconv.Atoi(strings.TrimSpace(string(b))); e == nil && pid > 1 {
			_ = syscall.Kill(pid, syscall.SIGTERM)
		}
	}
	time.Sleep(time.Second)
	launch := func() error {
		out, e := os.OpenFile(filepath.Join(state, "server.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
		if e != nil {
			return e
		}
		defer out.Close()
		cmd := exec.Command(filepath.Join(state, "current"), "-listen", addr, "-state-dir", state)
		cmd.Stdout = out
		cmd.Stderr = out
		cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
		if e = cmd.Start(); e != nil {
			return e
		}
		return cmd.Process.Release()
	}
	if err := launch(); err != nil {
		log.Println("新版本启动失败:", err)
	}
	client := &http.Client{Timeout: time.Second}
	healthy := func() bool {
		resp, e := client.Get("http://" + addr + "/healthz")
		if e != nil {
			return false
		}
		defer resp.Body.Close()
		var b struct{ Version string }
		return resp.StatusCode == 200 && json.NewDecoder(resp.Body).Decode(&b) == nil && b.Version == expected
	}
	for i := 0; i < 18; i++ {
		time.Sleep(time.Second)
		if healthy() {
			log.Println("更新已完成:", expected)
			return
		}
	}
	log.Println("新版本健康检查未通过，恢复上一版本")
	if b, e := os.ReadFile(pidPath); e == nil {
		if pid, e := strconv.Atoi(strings.TrimSpace(string(b))); e == nil && pid > 1 {
			_ = syscall.Kill(pid, syscall.SIGTERM)
		}
	}
	time.Sleep(time.Second)
	if err := symlinkSwap(state, previous); err != nil {
		log.Println("回滚失败:", err)
		return
	}
	if err := launch(); err != nil {
		log.Println("恢复旧版本失败:", err)
		return
	}
	log.Println("已恢复上一版本")
}
