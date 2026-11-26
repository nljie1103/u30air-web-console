package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestNoVNCRequiresRealClientAndProxy(t *testing.T) {
	html := "<!doctype html><html><head><title>noVNC - Web Client</title></head></html>"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/vnc.html" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(html))
	}))
	defer server.Close()
	target := server.URL + "/vnc.html"
	address, reason := probeNoVNCURL(context.Background(), target)
	if address != target || reason != "" {
		t.Fatalf("expected noVNC client to be available: %q %q", address, reason)
	}

	bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte("<html><title>Some other service</title></html>"))
	}))
	defer bad.Close()
	address, reason = probeNoVNCURL(context.Background(), bad.URL+"/vnc.html")
	if address != "" || !strings.Contains(reason, "不是 noVNC") {
		t.Fatalf("unrelated page must be rejected: %q %q", address, reason)
	}
}

func TestNoVNCDoesNotFollowRedirects(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "http://example.org", http.StatusFound)
	}))
	defer server.Close()
	address, reason := probeNoVNCURL(context.Background(), server.URL+"/vnc.html")
	if address != "" || !strings.Contains(reason, "HTTP 302") {
		t.Fatalf("untrusted noVNC redirect should not be followed: %q %q", address, reason)
	}
}
