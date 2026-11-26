package main

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestNoVNCChunkedResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		fmt.Fprint(w, "<!doctype html>")
		w.(http.Flusher).Flush()
		time.Sleep(50 * time.Millisecond)
		fmt.Fprint(w, "<title>noVNC</title>")
	}))
	defer server.Close()
	if url, msg := probeNoVNCURL(context.Background(), server.URL); url != server.URL || msg != "" {
		t.Fatalf("chunked page rejected: %s", msg)
	}
}

func TestPackageListEmptyFailureAndLimit(t *testing.T) {
	if list, cut, err := parseInstalledApps(""); err != nil || cut || len(list) != 0 {
		t.Fatal(list, cut, err)
	}
	if _, _, err := parseInstalledApps("Error: package manager unavailable"); err == nil {
		t.Fatal("failure parsed as empty list")
	}
	var b strings.Builder
	for i := 0; i < 301; i++ {
		fmt.Fprintf(&b, "package:com.example.app%d\n", i)
	}
	if list, cut, err := parseInstalledApps(b.String()); err != nil || !cut || len(list) != 300 {
		t.Fatal(len(list), cut, err)
	}
}

func TestLoginBudgetParallel(t *testing.T) {
	var b loginBudget
	now := time.Unix(100, 0)
	var permitted atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, limited := b.attempt("client", now, func() bool { return false })
			if !limited {
				permitted.Add(1)
			}
		}()
	}
	wg.Wait()
	if permitted.Load() != 5 {
		t.Fatal(permitted.Load())
	}
	if ok, limited := b.attempt("client", now.Add(loginWindow), func() bool { return true }); !ok || limited {
		t.Fatal("budget not reset")
	}
	if _, limited := b.attempt("client", now.Add(loginWindow), func() bool { return false }); limited {
		t.Fatal("successful login did not reset source")
	}
}

func TestMaintenanceLockSurvivesParentClose(t *testing.T) {
	state := t.TempDir()
	lock, err := acquireMaintenance(state)
	if err != nil {
		t.Fatal(err)
	}
	// An inherited descriptor holds the lock after the original descriptor is closed.
	child := exec.Command("sh", "-c", "sleep 1")
	child.ExtraFiles = []*os.File{lock}
	if err = child.Start(); err != nil {
		t.Fatal(err)
	}
	lock.Close()
	if !maintenanceActive(state) {
		t.Fatal("maintenance unlocked during helper handoff")
	}
	a := &app{state: state, addr: "192.168.0.1:8765"}
	if err := os.WriteFile(filepath.Join(state, "apk-install.enabled"), []byte("1"), 0600); err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest("POST", "http://"+a.addr+"/api/apk/install", strings.NewReader("{}"))
	req.Header.Set("X-Desktop-Action", "1")
	w := httptest.NewRecorder()
	a.handler().ServeHTTP(w, req)
	if w.Code != 403 {
		t.Fatalf("maintenance allowed mutation: %d", w.Code)
	}
	if err = child.Wait(); err != nil {
		t.Fatal(err)
	}
	if maintenanceActive(state) {
		t.Fatal("lock did not release")
	}
}

func TestPIDReuseDoesNotSignalUnrelatedProcess(t *testing.T) {
	child := exec.Command("sleep", "20")
	if err := child.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = child.Process.Kill(); _ = child.Wait() }()
	actual, err := processIdentity(child.Process.Pid)
	if err != nil {
		t.Fatal(err)
	}
	stale := actual
	stale.Start = "0"
	if err = stopIdentity(stale); err == nil {
		t.Fatal("stale PID accepted")
	}
	still, err := processIdentity(child.Process.Pid)
	if err != nil || still != actual {
		t.Fatal("unrelated process was stopped")
	}
	state := t.TempDir()
	if err = os.WriteFile(filepath.Join(state, "server.pid"), []byte(fmt.Sprint(actual.PID)), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = readServiceIdentity(state); err == nil {
		t.Fatal("foreign pidfile accepted")
	}
}

func TestServiceHealthRequiresVersion(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, "{\"status\":\"ok\",\"version\":\"old\"}") }))
	defer server.Close()
	addr := strings.TrimPrefix(server.URL, "http://")
	if waitHealth(addr, "new", 1) || !waitHealth(addr, "old", 1) {
		t.Fatal("incorrect health result")
	}
}
