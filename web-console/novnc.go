package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// noVNC requires an independently running VNC server, websockify, and the
// noVNC HTML client. Android Web Desktop does NOT install these components.
// Only show the optional external link if a real HTTP client is listening.
func probeNoVNC(ctx context.Context, deviceAddress string) (string, string) {
	host, _, err := net.SplitHostPort(deviceAddress)
	if err != nil || net.ParseIP(host) == nil {
		return "", "设备地址无效"
	}
	target := (&url.URL{Scheme: "http", Host: net.JoinHostPort(host, "5800"), Path: "/vnc.html"}).String()
	return probeNoVNCURL(ctx, target)
}

func probeNoVNCURL(ctx context.Context, target string) (string, string) {
	transport := &http.Transport{
		Proxy: nil, DisableKeepAlives: true, MaxIdleConns: 0,
		DialContext: (&net.Dialer{Timeout: 1200 * time.Millisecond}).DialContext,
	}
	client := &http.Client{
		Timeout:   2500 * time.Millisecond,
		Transport: transport,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return "", "noVNC 地址无效"
	}
	resp, err := client.Do(req)
	if err != nil {
		var opErr *net.OpError
		if errors.As(err, &opErr) {
			return "", "5800 端口未提供 noVNC 服务，设备上尚未部署独立 VNC 服务与网页代理"
		}
		return "", "noVNC 连接失败，未检测到可用的 5800 网页服务"
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Sprintf("5800 端口响应 HTTP %d，但没有可用的 noVNC 页面", resp.StatusCode)
	}
	if !strings.Contains(strings.ToLower(resp.Header.Get("Content-Type")), "html") {
		return "", "5800 端口不是 noVNC HTML 页面"
	}
	// A 200 is not enough: avoid linking to another unrelated service's page.
	// Checking content is deliberately small and never executes HTML.
	buf, err := io.ReadAll(io.LimitReader(resp.Body, 8192))
	if err != nil || !strings.Contains(strings.ToLower(string(buf)), "novnc") {
		return "", "5800 端口响应内容不是 noVNC 页面"
	}
	return target, ""
}
