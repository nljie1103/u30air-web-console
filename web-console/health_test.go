package main

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestLoopbackHealthRequiresMainListener(t *testing.T) {
	state := t.TempDir()
	var ready atomic.Bool
	if err := startLocalHealth(state, &ready); err != nil {
		t.Fatal(err)
	}
	portBytes, err := os.ReadFile(filepath.Join(state, "health.port"))
	if err != nil {
		t.Fatal(err)
	}
	target := "http://127.0.0.1:" + strings.TrimSpace(string(portBytes)) + "/healthz"
	client := &http.Client{Timeout: 2 * time.Second}
	check := func(expected bool) {
		t.Helper()
		resp, err := client.Get(target)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("unexpected status %d", resp.StatusCode)
		}
		var data struct {
			Status  string
			Version string
			Ready   bool
		}
		if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
			t.Fatal(err)
		}
		if data.Status != "ok" || data.Version != version || data.Ready != expected {
			t.Fatalf("unexpected health data: %+v", data)
		}
	}
	check(false)
	ready.Store(true)
	check(true)
	resp, err := client.Post(target, "application/json", strings.NewReader("{}"))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("POST method must be blocked, got %d", resp.StatusCode)
	}
}
