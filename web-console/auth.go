package main

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
)

// Password is intentionally not subject to a minimum length, case,
// digits or symbol rules. Blank passwords are only valid when login is off.
// This service binds to a configured LAN address, never 0.0.0.0.
type authConfig struct {
	Enabled  bool   `json:"enabled"`
	Password string `json:"password"`
}

type authState struct {
	mu       sync.RWMutex
	disabled bool
	password string
	secret   []byte
}

func loadAuthConfig(state, legacyPassword string) (authConfig, error) {
	data, err := os.ReadFile(filepath.Join(state, "auth.json"))
	if errors.Is(err, os.ErrNotExist) {
		// Upgrades of existing installations remain protected until explicitly
		// reconfigured. GUI first-time installers write auth.json themselves.
		return authConfig{Enabled: true, Password: legacyPassword}, nil
	}
	if err != nil {
		return authConfig{}, err
	}
	var raw struct {
		Enabled  *bool
		Password string
	}
	if err = json.Unmarshal(data, &raw); err != nil {
		return authConfig{}, err
	}
	if raw.Enabled == nil {
		return authConfig{}, errors.New("登录配置缺少启用状态")
	}
	cfg := authConfig{Enabled: *raw.Enabled, Password: raw.Password}
	if cfg.Enabled && cfg.Password == "" {
		return cfg, errors.New("已启用登录但未设置密码")
	}
	return cfg, nil
}

func storeAuthConfig(state string, cfg authConfig) error {
	if cfg.Enabled && cfg.Password == "" {
		return errors.New("开启密码登录时需要填写密码")
	}
	if err := os.MkdirAll(state, 0700); err != nil {
		return err
	}
	payload, err := json.Marshal(cfg)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(state, ".auth-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if err = tmp.Chmod(0600); err != nil {
		tmp.Close()
		return err
	}
	if _, err = tmp.Write(payload); err != nil {
		tmp.Close()
		return err
	}
	if err = tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), filepath.Join(state, "auth.json"))
}

func (a *app) authEnabled() bool {
	a.auth.mu.RLock()
	defer a.auth.mu.RUnlock()
	return !a.auth.disabled
}

func (a *app) currentPassword() string {
	a.auth.mu.RLock()
	defer a.auth.mu.RUnlock()
	if a.auth.password != "" {
		return a.auth.password
	}
	return a.password // compatibility for tests and previous initial config
}

func (a *app) checkPassword(submitted string) bool {
	stored := a.currentPassword()
	return len(submitted) == len(stored) && subtle.ConstantTimeCompare([]byte(submitted), []byte(stored)) == 1
}

func (a *app) setAuthConfig(enabled bool, newPassword string) error {
	a.auth.mu.Lock()
	defer a.auth.mu.Unlock()
	current := a.auth.password
	if current == "" {
		current = a.password
	}
	// Keeping an enabled password without typing it again is convenient,
	// but turning a passwordless service on requires a fresh password.
	if enabled && newPassword == "" {
		if a.auth.disabled {
			return errors.New("开启密码时，请输入新密码")
		}
		newPassword = current
	}
	if !enabled {
		newPassword = current
	}
	cfg := authConfig{Enabled: enabled, Password: newPassword}
	if err := storeAuthConfig(a.state, cfg); err != nil {
		return err
	}
	a.auth.password = cfg.Password
	a.auth.disabled = !enabled
	a.auth.secret = randomBytes(32) // invalidate existing cookies after every change
	return nil
}
