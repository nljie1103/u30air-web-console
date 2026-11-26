package main

import (
	_ "embed"
	"net/http"
)

//go:embed web/index.html
var desktopPage string

//go:embed web/login.html
var loginPage string

//go:embed web/app.css
var stylesheet string

//go:embed web/app.js
var javascript string

//go:embed web/app-icon.svg
var appIcon string

func staticAssets(mux *http.ServeMux) {
	for _, asset := range []struct{ path, contentType, content string }{
		{"/assets/app.css", "text/css; charset=utf-8", stylesheet},
		{"/assets/app.js", "text/javascript; charset=utf-8", javascript},
		{"/assets/app-icon.svg", "image/svg+xml", appIcon},
	} {
		mux.HandleFunc(asset.path, func(w http.ResponseWriter, r *http.Request) {
			if r.Method != "GET" {
				http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
				return
			}
			w.Header().Set("Content-Type", asset.contentType)
			_, _ = w.Write([]byte(asset.content))
		})
	}
}
