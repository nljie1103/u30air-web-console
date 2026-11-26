package main

import (
	"crypto/tls"
	"crypto/x509"
	_ "embed"
	"errors"
	"net/http"
	"time"
)

// Mozilla's public CA trust bundle, distributed at https://curl.se/ca/cacert.pem.
// Stored inside the ARM64 binary so a minimal Android device with an incomplete
// /system/etc/security/cacerts can verify GitHub's real TLS chain.
// This NEVER disables certificate verification or trusts arbitrary certificates.
//
//go:embed certs/mozilla-ca.pem
var bundledMozillaRoots []byte

func githubHTTPClient() (*http.Client, error) {
	roots, err := x509.SystemCertPool()
	if err != nil || roots == nil {
		roots = x509.NewCertPool()
	}
	if !roots.AppendCertsFromPEM(bundledMozillaRoots) {
		return nil, errors.New("无法解析内置的可信 CA 根证书")
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.TLSClientConfig = &tls.Config{
		RootCAs:    roots,
		MinVersion: tls.VersionTLS12,
	}
	return &http.Client{Transport: transport, Timeout: 45 * time.Second}, nil
}
