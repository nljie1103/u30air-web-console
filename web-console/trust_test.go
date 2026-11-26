package main

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestEmbeddedMozillaCACertificates(t *testing.T) {
	count := 0
	remaining := bundledMozillaRoots
	for {
		block, rest := pem.Decode(remaining)
		if block == nil {
			break
		}
		remaining = rest
		if block.Type != "CERTIFICATE" {
			continue
		}
		cert, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			t.Fatal(err)
		}
		if !cert.IsCA {
			t.Fatalf("bundle includes non-CA cert %s", cert.Subject)
		}
		count++
	}
	if count < 70 || count > 250 {
		t.Fatalf("expected a reasonably complete public CA bundle, got %d", count)
	}
}

func TestGitHubClientKeepsStrictTLSVerification(t *testing.T) {
	client, err := githubHTTPClient()
	if err != nil {
		t.Fatal(err)
	}
	if client.Timeout < 5*time.Second || client.Timeout > 90*time.Second {
		t.Fatalf("invalid timeout: %v", client.Timeout)
	}
	transport, ok := client.Transport.(*http.Transport)
	if !ok || transport.TLSClientConfig == nil {
		t.Fatal("GitHub transport missing secure TLS config")
	}
	if transport.TLSClientConfig.InsecureSkipVerify ||
		transport.TLSClientConfig.MinVersion < tls.VersionTLS12 ||
		transport.TLSClientConfig.RootCAs == nil {
		t.Fatal("TLS validation disabled or root CA unavailable")
	}
	// A self-signed HTTPS server MUST remain untrusted. Bundling trusted
	// public roots is not an SSL bypass and does not trust arbitrary certs.
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("OK"))
	}))
	defer server.Close()
	_, err = client.Get(server.URL)
	if err == nil || !strings.Contains(err.Error(), "certificate") {
		t.Fatalf("untrusted server unexpectedly accepted: %v", err)
	}
}
