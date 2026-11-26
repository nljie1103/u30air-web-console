package main

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func TestPowerUsesAndroidPowerManager(t *testing.T) {
	for _, action := range []string{"reboot", "shutdown"} {
		t.Run(action, func(t *testing.T) {
			calls := 0
			stub := func(ctx context.Context, executable string, args ...string) (string, error) {
				calls++
				if executable != "/system/bin/svc" || len(args) != 2 ||
					args[0] != "power" || args[1] != action {
					t.Errorf("unexpected privileged request: %q %v", executable, args)
				}
				return "", nil
			}
			if err := executePowerAction(context.Background(), action, stub); err != nil {
				t.Fatal(err)
			}
			if calls != 1 {
				t.Fatal("expected exactly one fixed-command invocation")
			}
		})
	}
	if err := executePowerAction(context.Background(), "wipe-data",
		func(context.Context, string, ...string) (string, error) {
			t.Fatal("unsafe power operation attempted")
			return "", nil
		}); err == nil {
		t.Fatal("invalid action accepted")
	}
}

func TestPowerManagerPermissionErrors(t *testing.T) {
	cases := []struct {
		out string
		err error
	}{
		{"Failed to reboot: Permission Denial", nil},
		{"SecurityException: not allowed", errors.New("exit status 1")},
	}
	for _, tc := range cases {
		stub := func(context.Context, string, ...string) (string, error) {
			return tc.out, tc.err
		}
		err := executePowerAction(context.Background(), "reboot", stub)
		if err == nil || !strings.Contains(err.Error(), "权限") {
			t.Fatalf("permission failure must be surfaced, got %v", err)
		}
	}
}
