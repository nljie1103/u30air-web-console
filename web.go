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

func staticAssets(mux *http.ServeMux) {
	mux.HandleFunc("/assets/app.css", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" {
			http.Error(w, "method not allowed", 405)
			return
		}
		w.Header().Set("Content-Type", "text/css; charset=utf-8")
		w.Write([]byte(stylesheet))
	})
	mux.HandleFunc("/assets/app.js", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" {
			http.Error(w, "method not allowed", 405)
			return
		}
		w.Header().Set("Content-Type", "text/javascript; charset=utf-8")
		w.Write([]byte(javascript))
	})
}
