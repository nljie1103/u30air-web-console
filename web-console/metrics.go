package main

import (
	"bufio"
	"context"
	"errors"
	"math"
	"os"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// Device metrics are read locally from Linux kernel virtual files, not from
// slow external programs or root-only APIs. Missing values are reported as
// null in JSON; never fabricate CPU or free-memory measurements.
type usageSnapshot struct {
	total uint64
	idle  uint64
}

func cpuSnapshot(path string) (usageSnapshot, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return usageSnapshot{}, err
	}
	line := strings.SplitN(string(data), "\n", 2)[0]
	fields := strings.Fields(line)
	if len(fields) < 6 || fields[0] != "cpu" {
		return usageSnapshot{}, errors.New("invalid /proc/stat CPU line")
	}
	var stats []uint64
	for _, field := range fields[1:] {
		val, e := strconv.ParseUint(field, 10, 64)
		if e != nil {
			return usageSnapshot{}, e
		}
		stats = append(stats, val)
	}
	if len(stats) < 5 {
		return usageSnapshot{}, errors.New("missing cpu times")
	}
	var total uint64
	for _, n := range stats {
		total += n
	}
	return usageSnapshot{total: total, idle: stats[3] + stats[4]}, nil
}

func cpuPercent(before, after usageSnapshot) *float64 {
	if after.total <= before.total || after.idle < before.idle {
		return nil
	}
	elapsed := after.total - before.total
	idle := after.idle - before.idle
	if idle > elapsed {
		return nil
	}
	value := math.Round((1-float64(idle)/float64(elapsed))*1000) / 10
	if value < 0 {
		value = 0
	}
	if value > 100 {
		value = 100
	}
	return &value
}

func readMemory(path string) (total, used uint64, err error) {
	file, err := os.Open(path)
	if err != nil {
		return 0, 0, err
	}
	defer file.Close()
	var available uint64
	scan := bufio.NewScanner(file)
	for scan.Scan() {
		fields := strings.Fields(scan.Text())
		if len(fields) < 2 {
			continue
		}
		switch fields[0] {
		case "MemTotal:":
			total, _ = strconv.ParseUint(fields[1], 10, 64)
		case "MemAvailable:":
			available, _ = strconv.ParseUint(fields[1], 10, 64)
		}
	}
	if scan.Err() != nil {
		return 0, 0, scan.Err()
	}
	if total == 0 {
		return 0, 0, errors.New("MemTotal missing")
	}
	if available > total {
		available = total
	}
	return total * 1024, (total - available) * 1024, nil
}

func readUptime(path string) *uint64 {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	fields := strings.Fields(string(data))
	if len(fields) == 0 {
		return nil
	}
	seconds, err := strconv.ParseFloat(fields[0], 64)
	if err != nil || seconds < 0 {
		return nil
	}
	v := uint64(seconds)
	return &v
}

func measureDevice(ctx context.Context) map[string]any {
	data := map[string]any{
		"cpuPercent": nil, "cpuCores": runtime.NumCPU(),
		"memoryTotal": nil, "memoryUsed": nil,
		"storageTotal": nil, "storageUsed": nil,
		"uptimeSeconds": readUptime("/proc/uptime"),
	}
	if total, used, err := readMemory("/proc/meminfo"); err == nil {
		data["memoryTotal"], data["memoryUsed"] = total, used
	}
	// /data contains user applications and device storage.
	var st syscall.Statfs_t
	if err := syscall.Statfs("/data", &st); err == nil && st.Blocks > 0 && st.Bsize > 0 {
		total := uint64(st.Blocks) * uint64(st.Bsize)
		available := uint64(st.Bavail) * uint64(st.Bsize)
		if available > total {
			available = total
		}
		data["storageTotal"], data["storageUsed"] = total, total-available
	}
	before, err := cpuSnapshot("/proc/stat")
	if err != nil {
		return data
	}
	select {
	case <-ctx.Done():
		return data
	case <-time.After(150 * time.Millisecond):
	}
	after, err := cpuSnapshot("/proc/stat")
	if err == nil {
		data["cpuPercent"] = cpuPercent(before, after)
	}
	return data
}
