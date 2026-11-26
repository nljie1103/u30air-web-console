package main

import (
	"archive/zip"
	"bytes"
	"context"
	"errors"
	"image"
	_ "image/jpeg"
	"image/png"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/shogo82148/androidbinary"
	"github.com/shogo82148/androidbinary/apk"
	"golang.org/x/image/webp"
)

const maxAPKBytes int64 = 600 << 20
const maxIconBytes = 160 << 10
const appMetadataLifetime = 10 * time.Minute

type appMetadata struct {
	Package string
	Label   string
	HasIcon bool
	Icon    []byte
	Checked time.Time
}

type metadataStore struct {
	mu         sync.Mutex
	items      map[string]appMetadata
	limit      chan struct{}
	generation uint64
}

func (m *metadataStore) get(ctx context.Context, state, pkg string) appMetadata {
	fallback := appMetadata{Package: pkg, Label: pkg, Checked: time.Now()}
	if !packageRe.MatchString(pkg) {
		return fallback
	}
	m.mu.Lock()
	if cached, ok := m.items[pkg]; ok && time.Since(cached.Checked) < metadataLifetime(cached) {
		m.mu.Unlock()
		return cached
	}
	if m.limit == nil {
		m.limit = make(chan struct{}, 3)
	}
	limit := m.limit
	m.mu.Unlock()

	select {
	case limit <- struct{}{}:
		defer func() { <-limit }()
	case <-ctx.Done():
		return fallback
	}

	m.mu.Lock()
	if cached, ok := m.items[pkg]; ok && time.Since(cached.Checked) < metadataLifetime(cached) {
		m.mu.Unlock()
		return cached
	}
	generation := m.generation
	m.mu.Unlock()
	result, err := nativeAppMetadata(ctx, state, pkg)
	if err != nil {
		path, err := appAPKPath(ctx, pkg, runWith)
		if err != nil {
			return fallback
		}
		result = parseAPKMetadata(pkg, path)
	}
	result.Checked = time.Now()
	m.mu.Lock()
	if generation != m.generation {
		m.mu.Unlock()
		return result
	}
	if m.items == nil {
		m.items = make(map[string]appMetadata)
	}
	if len(m.items) > 320 {
		m.items = make(map[string]appMetadata)
	}
	m.items[pkg] = result
	m.mu.Unlock()
	return result
}

func metadataLifetime(meta appMetadata) time.Duration {
	if !meta.HasIcon {
		return 30 * time.Second
	}
	return appMetadataLifetime
}

func (m *metadataStore) invalidate() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.items = nil
	m.generation++
}

func appAPKPath(ctx context.Context, pkg string, run androidCommand) (string, error) {
	if !packageRe.MatchString(pkg) {
		return "", errors.New("invalid package")
	}
	output, err := run(ctx, "/system/bin/pm", "path", pkg)
	if err != nil {
		return "", err
	}
	for _, line := range strings.Split(output, "\n") {
		if !strings.HasPrefix(line, "package:") {
			continue
		}
		path := strings.TrimSpace(strings.TrimPrefix(line, "package:"))
		if filepath.IsAbs(path) && filepath.Clean(path) == path && strings.HasSuffix(path, ".apk") &&
			(strings.HasPrefix(path, "/data/app/") || strings.HasPrefix(path, "/system/app/") ||
				strings.HasPrefix(path, "/product/app/") || strings.HasPrefix(path, "/system/priv-app/")) {
			return path, nil
		}
	}
	return "", errors.New("installed APK path is inaccessible")
}

func parseAPKMetadata(pkg, path string) (result appMetadata) {
	result = appMetadata{Package: pkg, Label: pkg}
	// Malformed application resources must not crash the web desktop daemon.
	defer func() {
		if recover() != nil {
			result = appMetadata{Package: pkg, Label: pkg}
		}
	}()
	fi, err := os.Stat(path)
	if err != nil || !fi.Mode().IsRegular() || fi.Size() <= 0 || fi.Size() > maxAPKBytes {
		return
	}
	// Do not let an installed but malformed APK force excessive allocations
	// when parsing AndroidManifest.xml or the compiled resource table.
	if !apkResourcesWithinLimits(path) {
		return
	}
	packageFile, err := apk.OpenFile(path)
	if err != nil {
		return
	}
	defer packageFile.Close()
	if packageFile.PackageName() != pkg {
		return
	}
	if name, err := packageFile.Label(nil); err == nil {
		name = strings.TrimSpace(name)
		if name != "" && len([]rune(name)) <= 90 {
			result.Label = name
		}
	}
	icon, err := packageFile.Icon(nil)
	if err != nil || icon == nil {
		// Ask the resource table for pre-adaptive launcher variants. This
		// also works when AAPT has renamed every raster file (res/FS.png).
		for _, density := range []uint16{480, 320, 640, 160} {
			icon, err = packageFile.Icon(&androidbinary.ResTableConfig{SDKVersion: 25, Density: density})
			if err == nil && icon != nil {
				break
			}
		}
	}
	if icon == nil {
		// Adaptive icons are often XML backed, with a raster fallback in
		// another density. Prefer the manifest's actual resource name.
		iconResource, _ := packageFile.Manifest().App.Icon.WithResTableConfig(nil).String()
		stem := strings.TrimSuffix(filepath.Base(iconResource), filepath.Ext(iconResource))
		icon = fallbackRasterIcon(path, stem)
	}
	if icon == nil {
		return
	}
	b := iconPNG(icon)
	if len(b) > 0 && len(b) <= maxIconBytes {
		result.Icon = b
		result.HasIcon = true
	}
	return
}

func apkResourcesWithinLimits(path string) bool {
	zr, err := zip.OpenReader(path)
	if err != nil {
		return false
	}
	defer zr.Close()
	hasManifest, hasResources := false, false
	for _, f := range zr.File {
		switch f.Name {
		case "AndroidManifest.xml":
			hasManifest = f.UncompressedSize64 > 0 && f.UncompressedSize64 < 4<<20
		case "resources.arsc":
			hasResources = f.UncompressedSize64 > 0 && f.UncompressedSize64 < 24<<20
		}
	}
	return hasManifest && hasResources
}

func iconPNG(img image.Image) []byte {
	bounds := img.Bounds()
	if bounds.Dx() < 1 || bounds.Dy() < 1 || bounds.Dx() > 4096 || bounds.Dy() > 4096 {
		return nil
	}
	const size = 64
	dest := image.NewNRGBA(image.Rect(0, 0, size, size))
	for y := 0; y < size; y++ {
		for x := 0; x < size; x++ {
			sx := bounds.Min.X + x*bounds.Dx()/size
			sy := bounds.Min.Y + y*bounds.Dy()/size
			dest.Set(x, y, img.At(sx, sy))
		}
	}
	var output bytes.Buffer
	if png.Encode(&output, dest) != nil {
		return nil
	}
	return output.Bytes()
}

func fallbackRasterIcon(path, preferredStem string) image.Image {
	zr, err := zip.OpenReader(path)
	if err != nil {
		return nil
	}
	defer zr.Close()
	// Adaptive XML icons can be used as a fallback if the same APK also
	// bundles a launcher PNG/WebP for legacy-density devices.
	targets := []string{}
	if preferredStem != "" && preferredStem != "." && preferredStem != "/" {
		targets = append(targets, preferredStem+".png", preferredStem+".webp",
			preferredStem+"_foreground.png", preferredStem+"_foreground.webp")
	}
	targets = append(targets, "ic_launcher.png", "ic_launcher.webp", "icon.png", "icon.webp")
	for _, target := range targets {
		var best *zip.File
		for _, file := range zr.File {
			name := file.Name
			if !strings.HasPrefix(name, "res/mipmap-") && !strings.HasPrefix(name, "res/mipmap/") &&
				!strings.HasPrefix(name, "res/drawable-") && !strings.HasPrefix(name, "res/drawable/") {
				continue
			}
			if strings.ToLower(filepath.Base(name)) != target || file.UncompressedSize64 > 3<<20 {
				continue
			}
			if best == nil || strings.Contains(name, "xxxhdpi") ||
				(strings.Contains(name, "xxhdpi") && !strings.Contains(best.Name, "xxxhdpi")) {
				best = file
			}
		}
		if best == nil {
			continue
		}
		rc, err := best.Open()
		if err != nil {
			continue
		}
		data, err := io.ReadAll(io.LimitReader(rc, 3<<20))
		_ = rc.Close()
		if err != nil {
			continue
		}
		if strings.HasSuffix(target, ".webp") {
			if img, err := webp.Decode(bytes.NewReader(data)); err == nil {
				return img
			}
		} else if img, _, err := image.Decode(bytes.NewReader(data)); err == nil {
			return img
		}
	}
	return nil
}
