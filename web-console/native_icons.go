package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"image/png"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"
)

func parseNativeIcon(pkg string, output []byte) (appMetadata, error) {
	for _, line := range bytes.Split(output, []byte{'\n'}) {
		fields := strings.Split(strings.TrimSpace(string(line)), "\t")
		if len(fields) != 3 || fields[0] != "AWD_ICON_V1" {
			continue
		}
		if len(fields[1]) > 1024 || len(fields[2]) > maxIconBytes*2 {
			return appMetadata{}, errors.New("oversized native icon")
		}
		label, e := base64.StdEncoding.DecodeString(fields[1])
		if e != nil || !utf8.Valid(label) {
			return appMetadata{}, errors.New("invalid native label")
		}
		data, e := base64.StdEncoding.DecodeString(fields[2])
		if e != nil || len(data) > maxIconBytes {
			return appMetadata{}, errors.New("invalid native icon")
		}
		config, e := png.DecodeConfig(bytes.NewReader(data))
		if e != nil || config.Width != 96 || config.Height != 96 {
			return appMetadata{}, errors.New("invalid native icon size")
		}
		if _, e = png.Decode(bytes.NewReader(data)); e != nil {
			return appMetadata{}, e
		}
		name := strings.TrimSpace(string(label))
		if name == "" || utf8.RuneCountInString(name) > 90 {
			name = pkg
		}
		return appMetadata{Package: pkg, Label: name, Icon: data, HasIcon: true}, nil
	}
	return appMetadata{}, errors.New("native icon not available")
}

func nativeAppMetadata(ctx context.Context, state, pkg string) (appMetadata, error) {
	if len(nativeIconDEX) == 0 || !packageRe.MatchString(pkg) {
		return appMetadata{}, errors.New("native icon reader unavailable")
	}
	// Embed the tiny helper in desktopd so existing deployment and online
	// update paths need no new files or APK installation.
	f, err := os.CreateTemp(state, "icon-reader-*.jar")
	if err != nil {
		return appMetadata{}, err
	}
	defer os.Remove(f.Name())
	// Android 14+ requires dynamically loaded code to be read-only.
	if err = f.Chmod(0400); err != nil {
		f.Close()
		return appMetadata{}, err
	}
	_, err = f.Write(nativeIconDEX)
	closeErr := f.Close()
	if err != nil {
		return appMetadata{}, err
	}
	if closeErr != nil {
		return appMetadata{}, closeErr
	}
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "/system/bin/app_process", "/system/bin", "org.jiuliu.awd.IconReader", pkg)
	cmd.Env = append(os.Environ(), "CLASSPATH="+filepath.Clean(f.Name()))
	out, err := cmd.Output()
	if err != nil {
		return appMetadata{}, err
	}
	return parseNativeIcon(pkg, out)
}
