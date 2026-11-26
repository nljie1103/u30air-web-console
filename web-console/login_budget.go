package main

import (
	"sync"
	"time"
)

const loginWindow = 30 * time.Second
const maxLoginSources = 256

type loginAttempt struct {
	count   int
	expires time.Time
}
type loginBudget struct {
	mu      sync.Mutex
	entries map[string]loginAttempt
	total   loginAttempt
}

// Check and debit under one lock, so parallel wrong guesses cannot bypass limits.
func (b *loginBudget) attempt(source string, now time.Time, check func() bool) (ok, limited bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.entries == nil {
		b.entries = make(map[string]loginAttempt)
	}
	if !now.Before(b.total.expires) {
		b.total = loginAttempt{expires: now.Add(loginWindow)}
	}
	for ip, e := range b.entries {
		if !now.Before(e.expires) {
			delete(b.entries, ip)
		}
	}
	e, exists := b.entries[source]
	if !exists {
		e = loginAttempt{expires: now.Add(loginWindow)}
	}
	if e.count >= 5 || b.total.count >= 40 || (!exists && len(b.entries) >= maxLoginSources) {
		return false, true
	}
	if check() {
		delete(b.entries, source)
		return true, false
	}
	e.count++
	b.entries[source] = e
	b.total.count++
	return false, false
}
