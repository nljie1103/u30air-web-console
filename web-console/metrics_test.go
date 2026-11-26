package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCPUSnapshotAndPercent(t *testing.T) {
	p := filepath.Join(t.TempDir(), "stat")
	if err := os.WriteFile(p, []byte("cpu  100 0 100 200 10 0 0 0 0 0\ncpu0 1 0 0 0\n"), 0600); err != nil {
		t.Fatal(err)
	}
	before, err := cpuSnapshot(p)
	if err != nil {
		t.Fatal(err)
	}
	if before.total != 410 || before.idle != 210 {
		t.Fatalf("%+v", before)
	}
	after := usageSnapshot{total: 510, idle: 270}
	v := cpuPercent(before, after)
	if v == nil || *v != 40 {
		t.Fatalf("CPU usage expected 40%%: %v", v)
	}
	if cpuPercent(after, before) != nil {
		t.Fatal("invalid CPU counter order accepted")
	}
}

func TestMemoryParser(t *testing.T) {
	p := filepath.Join(t.TempDir(), "meminfo")
	text := "MemTotal:  4000000 kB\nMemFree: 1000000 kB\nMemAvailable: 1500000 kB\n"
	if err := os.WriteFile(p, []byte(text), 0600); err != nil {
		t.Fatal(err)
	}
	total, used, err := readMemory(p)
	if err != nil || total != 4000000*1024 || used != 2500000*1024 {
		t.Fatalf("%d %d %v", total, used, err)
	}
	if err := os.WriteFile(p, []byte(strings.ReplaceAll(text, "MemTotal", "BadTotal")), 0600); err != nil {
		t.Fatal(err)
	}
	_, _, err = readMemory(p)
	if err == nil {
		t.Fatal("missing total accepted")
	}
}
