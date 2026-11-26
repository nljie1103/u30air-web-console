package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestVersionCompare(t *testing.T) {
	for _, tt := range []struct {
		new, old string
		want     bool
	}{
		{"2.0.0", "1.0.1", true}, {"2.0.0", "2.0.0", false},
		{"2.1.0", "2.0.99", true}, {"1.9.9", "2.0.0", false},
	} {
		if got := newer(tt.new, tt.old); got != tt.want {
			t.Fatalf("%s > %s = %v", tt.new, tt.old, got)
		}
	}
}
func TestZIPPackage(t *testing.T) {
	buffer := new(bytes.Buffer)
	z := zip.NewWriter(buffer)
	f, e := z.Create("desktopd")
	if e != nil {
		t.Fatal(e)
	}
	_, _ = f.Write(append([]byte{127, 'E', 'L', 'F'}, bytes.Repeat([]byte{1}, 200)...))
	if e = z.Close(); e != nil {
		t.Fatal(e)
	}
	b, e := unpackBinary(buffer.Bytes())
	if e != nil || len(b) != 204 {
		t.Fatalf("extract: %v, %d bytes", e, len(b))
	}
	if _, e = unpackBinary([]byte("not zip")); e == nil {
		t.Fatal("bad zip accepted")
	}
	sum := sha256.Sum256(buffer.Bytes())
	if len(hex.EncodeToString(sum[:])) != 64 {
		t.Fatal("digest invalid")
	}
}
func TestProtectedRoutesAndLogin(t *testing.T) {
	a := &app{addr: "192.168.1.5:8765", password: strings.Repeat("a", 32), secret: randomBytes(32), state: t.TempDir(), httpClient: http.DefaultClient}
	h := a.handler()
	request := func(method, path string, auth bool, origin string, body string) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, "http://192.168.1.5:8765"+path, strings.NewReader(body))
		if auth {
			r.AddCookie(&http.Cookie{Name: "awd-session", Value: a.cookieValue()})
		}
		if method == "POST" {
			r.Header.Set("X-Desktop-Action", "1")
			r.Header.Set("Content-Type", "application/json")
		}
		if origin != "" {
			r.Header.Set("Origin", origin)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w
	}
	for _, p := range []string{"/api/status", "/api/apps", "/api/screen", "/api/app-info?package=com.example.app", "/api/app-icon?package=com.example.app", "/api/novnc/status", "/api/update/check"} {
		if got := request("GET", p, false, "", "").Code; got != 401 {
			t.Fatalf("%s should reject guest, got %d", p, got)
		}
	}
	if got := request("POST", "/api/control", false, "", "{}").Code; got != 403 {
		t.Fatalf("control unauthorized: %d", got)
	}
	if got := request("GET", "/api/app-info?package=bad%3Bcommand", true, "", "").Code; got != 400 {
		t.Fatalf("invalid APK metadata query should fail: %d", got)
	}
	if got := request("GET", "/api/app-icon?package=bad%2Fpath", true, "", "").Code; got != 400 {
		t.Fatalf("invalid APK icon path should fail: %d", got)
	}

	if got := request("POST", "/api/control", true, "http://evil.local", "{}").Code; got != 403 {
		t.Fatalf("origin bypass: %d", got)
	}
	if got := request("POST", "/api/control", true, "", "{\"action\":\"shutdown\"}").Code; got != 400 {
		t.Fatalf("shutdown must require explicit confirmation: %d", got)
	}
	if got := request("POST", "/api/control", true, "", "{\"action\":\"reboot\",\"confirm\":\"关机\"}").Code; got != 400 {
		t.Fatalf("reboot must reject wrong confirmation: %d", got)
	}

	if got := request("POST", "/api/control", true, "", "{\"action\":\"launch\",\"package\":\"example;rm -rf /\"}").Code; got != 400 {
		t.Fatalf("injection not blocked: %d", got)
	}
	if got := request("POST", "/api/login", false, "", "{\"password\":\"bad\"}").Code; got != 401 {
		t.Fatalf("bad password accepted: %d", got)
	}
	w := request("POST", "/api/login", false, "", "{\"password\":\""+a.password+"\"}")
	if w.Code != 200 || len(w.Result().Cookies()) == 0 {
		t.Fatalf("login failed: %d", w.Code)
	}
	if got := request("GET", "/assets/app.css", false, "", "").Code; got != 200 {
		t.Fatalf("css: %d", got)
	}
	if got := request("GET", "/assets/app.js", false, "", "").Code; got != 200 {
		t.Fatalf("js: %d", got)
	}
	w = request("GET", "/healthz", false, "", "")
	var data map[string]string
	if e := json.Unmarshal(w.Body.Bytes(), &data); e != nil || data["version"] != version {
		t.Fatalf("health: %v %v", e, data)
	}
}
func TestHostProtection(t *testing.T) {
	a := &app{addr: "192.168.1.5:8765", secret: randomBytes(32), password: strings.Repeat("a", 32)}
	r := httptest.NewRequest("GET", "http://evil.example:8765/healthz", nil)
	w := httptest.NewRecorder()
	a.handler().ServeHTTP(w, r)
	if w.Code != 403 {
		t.Fatalf("untrusted host: %d", w.Code)
	}
}
func TestPackageNameValidation(t *testing.T) {
	for _, v := range []string{"com.example.app", "org.test_1.pkg"} {
		if !packageRe.MatchString(v) {
			t.Fatalf("unexpected reject: %q", v)
		}
	}
	for _, v := range []string{"app", "com.example;shutdown", "a.b/c", "a.b\n"} {
		if packageRe.MatchString(v) {
			t.Fatalf("unexpected accept: %q", v)
		}
	}
}
