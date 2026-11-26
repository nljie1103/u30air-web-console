package main

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

// Android's official svc power commands invoke PowerManager. We use fixed
// argv (never a shell string) and do not attempt hidden privilege escalation.
func executePowerAction(ctx context.Context, action string, run androidCommand) error {
	if action != "reboot" && action != "shutdown" {
		return errors.New("不支持的电源操作")
	}
	output, err := run(ctx, "/system/bin/svc", "power", action)
	if err != nil || strings.Contains(strings.ToLower(output), "failed to") ||
		strings.Contains(strings.ToLower(output), "permission denial") ||
		strings.Contains(output, "SecurityException") {
		detail := strings.TrimSpace(output)
		if len(detail) > 240 {
			detail = detail[:240] + "…"
		}
		if detail == "" && err != nil {
			detail = err.Error()
		}
		return fmt.Errorf("Android 电源服务拒绝操作（可能需要特殊系统权限）：%s", detail)
	}
	return nil
}
