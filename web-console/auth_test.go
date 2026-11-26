package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestAuthConfigPasswordFreedomAndPersistence(t *testing.T) {
	state := t.TempDir()
	for _, password := range []string{"a", "1", "中文", "  !  ", "xY@#$"} {
		cfg := authConfig{Enabled: true, Password: password}
		if err := storeAuthConfig(state, cfg); err != nil {
			t.Fatal(err)
		}
		loaded, err := loadAuthConfig(state, "legacy")
		if err != nil || loaded != cfg {
			t.Fatalf("load %q: %#v %v", password, loaded, err)
		}
	}
	if err := storeAuthConfig(state, authConfig{Enabled: true, Password: ""}); err == nil {
		t.Fatal("enabled login with blank password must fail")
	}
	if err := storeAuthConfig(state, authConfig{Enabled: false, Password: ""}); err != nil {
		t.Fatal(err)
	}
	result, err := loadAuthConfig(state, "legacy")
	if err != nil || result.Enabled {
		t.Fatalf("disabled setting lost: %v %#v", err, result)
	}
}

func TestAuthConfigNoPasswordAndSessionRotation(t *testing.T) {
	state := t.TempDir()
	a := &app{
		addr: "192.168.0.1:8765", state: state,
		password: "previous", secret: randomBytes(32),
	}
	h := a.handler()
	request := func(method, path, body, cookie string) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, "http://192.168.0.1:8765"+path, strings.NewReader(body))
		if cookie != "" {
			r.AddCookie(&http.Cookie{Name: "awd-session", Value: cookie})
		}
		if method == "POST" {
			r.Header.Set("X-Desktop-Action", "1")
			r.Header.Set("Content-Type", "application/json")
			r.Header.Set("Origin", "http://192.168.0.1:8765")
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w
	}
	if r := request("GET", "/api/auth/config", "", ""); r.Code != 401 {
		t.Fatalf("guest got %d", r.Code)
	}
	oldCookie := a.cookieValue()
	r := request("POST", "/api/auth/config", `{"enabled":false,"password":""}`, oldCookie)
	if r.Code != 200 {
		t.Fatalf("disable failed: %s", r.Body.String())
	}
	if r := request("GET", "/api/auth/config", "", ""); r.Code != 200 {
		t.Fatalf("disabled mode must be open: %d", r.Code)
	}
	r = request("POST", "/api/auth/config", `{"enabled":true,"password":""}`, "")
	if r.Code != 400 {
		t.Fatalf("enabling without password must fail: %s", r.Body.String())
	}
	r = request("POST", "/api/auth/config", `{"enabled":true,"password":"1"}`, "")
	if r.Code != 200 {
		t.Fatalf("enable failed: %s", r.Body.String())
	}
	if r := request("GET", "/api/auth/config", "", oldCookie); r.Code != 401 {
		t.Fatalf("old session should be invalidated after settings change: %d", r.Code)
	}
	login := request("POST", "/api/login", `{"password":"1"}`, "")
	if login.Code != 200 {
		t.Fatalf("single char password rejected: %s", login.Body.String())
	}
	var config authConfig
	data, _ := json.Marshal(authConfig{Enabled: true, Password: "1"})
	_ = json.Unmarshal(data, &config)
	if config.Password != "1" {
		t.Fatal(config)
	}
}

func TestAuthLegacyDefaultsToProtected(t *testing.T) {
	config, err := loadAuthConfig(t.TempDir(), "old-password")
	if err != nil || !config.Enabled || config.Password != "old-password" {
		t.Fatal(config, err)
	}
}
