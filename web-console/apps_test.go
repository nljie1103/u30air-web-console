package main

import (
	"context"
	"errors"
	"image"
	"image/color"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDirectActivityLaunch(t *testing.T) {
	var actions []string
	stub := func(ctx context.Context, exe string, args ...string) (string, error) {
		actions = append(actions, exe+" "+strings.Join(args, " "))
		if strings.HasSuffix(exe, "/cmd") {
			return "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\ncom.v2ray.ang/com.v2ray.ang.ui.MainActivity\n", nil
		}
		return "Starting: Intent { cmp=com.v2ray.ang/.ui.MainActivity }", nil
	}
	if err := launchInstalledApp(context.Background(), "com.v2ray.ang", stub); err != nil {
		t.Fatal(err)
	}
	if len(actions) != 2 || !strings.Contains(actions[1], "start --user 0 -n com.v2ray.ang/com.v2ray.ang.ui.MainActivity") {
		t.Fatalf("Expected explicit am start without monkey: %v", actions)
	}
}

func TestLaunchFallbackForUnavailableResolver(t *testing.T) {
	calls := []string{}
	stub := func(ctx context.Context, exe string, args ...string) (string, error) {
		calls = append(calls, exe+" "+strings.Join(args, " "))
		if strings.HasSuffix(exe, "/cmd") {
			return "resolver unsupported", errors.New("unknown command")
		}
		return "Starting: Intent", nil
	}
	if err := launchInstalledApp(context.Background(), "com.example.app", stub); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(calls[len(calls)-1], "-a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p com.example.app") {
		t.Fatal(calls)
	}
}

func TestLaunchReportsRealActivityErrors(t *testing.T) {
	tests := []struct {
		output string
		wanted string
	}{
		{"Error: Activity not started, unable to resolve Intent", "没有可用的桌面启动入口"},
		{"SecurityException: Permission Denial: starting Intent", "Android 系统拒绝启动"},
		{"Error: Activity class {com.example.app/Main} does not exist", "没有可用的桌面启动入口"},
	}
	for _, tt := range tests {
		t.Run(tt.wanted, func(t *testing.T) {
			stub := func(ctx context.Context, exe string, args ...string) (string, error) {
				if strings.HasSuffix(exe, "/cmd") {
					return "com.example.app/com.example.app.Main", nil
				}
				return tt.output, nil // Android am may exit 0 while printing Error:
			}
			err := launchInstalledApp(context.Background(), "com.example.app", stub)
			if err == nil || !strings.Contains(err.Error(), tt.wanted) {
				t.Fatalf("got %v, want %q", err, tt.wanted)
			}
		})
	}
	if err := launchInstalledApp(context.Background(), "invalid;rm", nil); err == nil {
		t.Fatal("unvalidated package accepted")
	}
}

func TestAPKPathValidation(t *testing.T) {
	valid := func(path string) (string, error) {
		return appAPKPath(context.Background(), "com.v2ray.ang",
			func(ctx context.Context, exe string, args ...string) (string, error) {
				return "package:" + path + "\n", nil
			})
	}
	for _, path := range []string{
		"/data/app/~~abc/com.v2ray.ang-random/base.apk",
		"/system/app/Example/Example.apk",
	} {
		if got, err := valid(path); err != nil || got != path {
			t.Fatalf("%s: %s %v", path, got, err)
		}
	}
	for _, path := range []string{"/etc/passwd", "../../etc/passwd", "/data/app/../../etc/something.apk", "/tmp/fake.apk"} {
		if got, err := valid(path); err == nil {
			t.Errorf("invalid path accepted: %q -> %q", path, got)
		}
	}
}

func TestMetadataFallbackAndIconConversion(t *testing.T) {
	pkg := "com.example.hello"
	info := parseAPKMetadata(pkg, filepath.Join(t.TempDir(), "missing.apk"))
	if info.Label != pkg || info.HasIcon {
		t.Fatal(info)
	}
	source := image.NewRGBA(image.Rect(0, 0, 128, 128))
	for y := 0; y < 128; y++ {
		for x := 0; x < 128; x++ {
			source.Set(x, y, color.RGBA{R: 25, G: 160, B: 225, A: 255})
		}
	}
	data := iconPNG(source)
	if len(data) < 40 || len(data) >= maxIconBytes || !isPNG(data) {
		t.Fatal("invalid encoded icon")
	}
	p := filepath.Join(t.TempDir(), "junk.apk")
	if err := os.WriteFile(p, []byte("not an APK"), 0600); err != nil {
		t.Fatal(err)
	}
	info = parseAPKMetadata(pkg, p)
	if info.Label != pkg || info.HasIcon {
		t.Fatal("malformed APK should fall back")
	}
}
