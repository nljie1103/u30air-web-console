package main

import (
	"archive/zip"
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAPKPublicURL(t *testing.T) {
	for _, raw := range []string{"http://example.com/a.apk", "https://user:pass@example.com/a.apk", "https://example.com:8888/a.apk", "file:///tmp/a.apk"} {
		if _, err := apkURL(raw); err == nil {
			t.Fatalf("accepted %s", raw)
		}
	}
	for _, ip := range []string{"127.0.0.1", "192.168.0.1", "169.254.169.254", "100.64.0.1", "::1", "::ffff:10.0.0.1", "64:ff9b::a00:1", "2001:db8::1"} {
		if publicAPKIP(netip.MustParseAddr(ip)) {
			t.Fatalf("accepted %s", ip)
		}
	}
	for _, ip := range []string{"8.8.8.8", "2606:4700:4700::1111"} {
		if !publicAPKIP(netip.MustParseAddr(ip)) {
			t.Fatalf("rejected %s", ip)
		}
	}
	if err := copyAPK(io.Discard, strings.NewReader("x"), maxAPKSize+1, func(int64, int64) {}); err == nil {
		t.Fatal("oversize accepted")
	}
}

func TestAPKInstallAuthorizationAndLocalUpload(t *testing.T) {
	state := t.TempDir()
	a := &app{addr: "192.168.0.1:8765", state: state, password: "secret", secret: randomBytes(32)}
	handler := a.handler()
	request := func(path, method, kind string, body io.Reader, auth bool) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, "http://"+a.addr+path, body)
		r.Header.Set("X-Desktop-Action", "1")
		r.Header.Set("Content-Type", kind)
		if auth {
			r.AddCookie(&http.Cookie{Name: "awd-session", Value: a.cookieValue()})
		}
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w
	}
	if w := request("/api/apk/install", "POST", "application/json", strings.NewReader("{}"), true); w.Code != 403 {
		t.Fatal(w.Code)
	}
	if w := request("/api/apk/config", "POST", "application/json", strings.NewReader("{\"enabled\":true}"), false); w.Code != 401 {
		t.Fatal(w.Code)
	}
	if w := request("/api/apk/config", "POST", "application/json", strings.NewReader("{\"enabled\":true}"), true); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	if w := request("/api/apk/install", "POST", "application/vnd.android.package-archive", strings.NewReader("not APK"), true); w.Code != 400 {
		t.Fatal(w.Code)
	}
	bin := t.TempDir()
	if err := os.WriteFile(filepath.Join(bin, "pm"), []byte("#!/bin/sh\n[ \"$1\" = install ] && [ \"$2\" = -r ] && [ -f \"$3\" ] || exit 1\nprintf 'Success\\n'\n"), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+":"+os.Getenv("PATH"))
	var buf bytes.Buffer
	z := zip.NewWriter(&buf)
	f, err := z.Create("AndroidManifest.xml")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.Write([]byte("mock manifest")); err != nil {
		t.Fatal(err)
	}
	if err = z.Close(); err != nil {
		t.Fatal(err)
	}
	if w := request("/api/apk/install", "POST", "application/vnd.android.package-archive", &buf, true); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	files, err := filepath.Glob(filepath.Join(state, "apk-*.apk"))
	if err != nil || len(files) != 0 {
		t.Fatalf("temporary APK leaked: %v %v", files, err)
	}
}
