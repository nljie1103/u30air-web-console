package main

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
)

const mainAction = "android.intent.action.MAIN"
const launcherCategory = "android.intent.category.LAUNCHER"

// Android 13's monkey command may require INJECT_EVENTS. Starting the exported
// launcher activity directly uses ActivityManager without injecting input.
var launcherComponent = regexp.MustCompile("^[a-zA-Z_][\\w]*(?:\\.[a-zA-Z_][\\w]*)+/[a-zA-Z_.$][\\w.$]*$")

type androidCommand func(context.Context, string, ...string) (string, error)

func launchInstalledApp(ctx context.Context, pkg string, run androidCommand) error {
	if !packageRe.MatchString(pkg) {
		return errors.New("应用包名不合法")
	}

	// The package manager resolves the currently enabled exported LAUNCHER
	// entry, including activity aliases and OEM changes.
	lookup, lookupErr := run(ctx, "/system/bin/cmd",
		"package", "resolve-activity", "--brief", "--user", "0",
		"-a", mainAction, "-c", launcherCategory, "-p", pkg)
	component := ""
	if lookupErr == nil {
		for _, line := range strings.Split(lookup, "\n") {
			line = strings.TrimSpace(line)
			if launcherComponent.MatchString(line) && strings.HasPrefix(line, pkg+"/") {
				component = line
			}
		}
	}

	var args []string
	if component != "" {
		args = []string{"start", "--user", "0", "-n", component}
	} else {
		// A few OEM builds don't expose cmd package resolve-activity to shell.
		// Let ActivityManager resolve MAIN/LAUNCHER directly as a fallback.
		args = []string{"start", "--user", "0",
			"-a", mainAction, "-c", launcherCategory, "-p", pkg}
	}
	out, err := run(ctx, "/system/bin/am", args...)
	if err != nil || isActivityStartError(out) {
		detail := firstAndroidError(out)
		switch {
		case strings.Contains(strings.ToLower(detail), "permission denial"),
			strings.Contains(detail, "SecurityException"),
			strings.Contains(strings.ToLower(detail), "not allowed"):
			return fmt.Errorf("Android 系统拒绝启动 %s：%s", pkg, detail)
		case strings.Contains(strings.ToLower(detail), "unable to resolve"),
			strings.Contains(strings.ToLower(detail), "no activity"),
			strings.Contains(strings.ToLower(detail), "does not exist"):
			return fmt.Errorf("应用 %s 没有可用的桌面启动入口（可能是后台组件）：%s", pkg, detail)
		case err != nil:
			if detail != "" {
				return fmt.Errorf("启动 %s 失败：%s（%w）", pkg, detail, err)
			}
			return fmt.Errorf("启动 %s 失败：%w", pkg, err)
		default:
			return fmt.Errorf("启动 %s 失败：%s", pkg, detail)
		}
	}
	return nil
}

func isActivityStartError(out string) bool {
	lower := strings.ToLower(out)
	// am may return exit 0 even when it prints "Error: Activity not started".
	return strings.Contains(lower, "error:") ||
		strings.Contains(lower, "exception") ||
		strings.Contains(lower, "permission denial") ||
		strings.Contains(lower, "not allowed to start")
}

func firstAndroidError(output string) string {
	lines := strings.Split(output, "\n")
	for _, fragment := range []string{"Permission Denial", "SecurityException", "Error:", "Unable to resolve", "No activity"} {
		for _, line := range lines {
			if strings.Contains(strings.ToLower(line), strings.ToLower(fragment)) {
				line = strings.TrimSpace(line)
				if len(line) > 280 {
					return line[:280] + "…"
				}
				return line
			}
		}
	}
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "Starting:") {
			continue
		}
		if len(line) > 280 {
			return line[:280] + "…"
		}
		return line
	}
	return "系统未提供具体错误原因"
}
