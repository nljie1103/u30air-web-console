package main

import (
	"bytes"
	"encoding/base64"
	"image"
	"image/png"
	"testing"
	"time"
)

func TestNativeIconResponse(t *testing.T) {
	var out bytes.Buffer
	if err := png.Encode(&out, image.NewRGBA(image.Rect(0, 0, 96, 96))); err != nil {
		t.Fatal(err)
	}
	encode := base64.StdEncoding.EncodeToString
	line := "system log\nAWD_ICON_V1\t" + encode([]byte("测试应用")) + "\t" + encode(out.Bytes()) + "\n"
	meta, err := parseNativeIcon("com.example.test", []byte(line))
	if err != nil || !meta.HasIcon || meta.Label != "测试应用" {
		t.Fatal(meta, err)
	}
	for _, bad := range []string{"", "AWD_ICON_V1\tinvalid\tinvalid", "AWD_ICON_V1\tYQ==\tYWJj"} {
		if _, err := parseNativeIcon("com.example.test", []byte(bad)); err == nil {
			t.Fatal("accepted bad helper output")
		}
	}
	if metadataLifetime(appMetadata{}) != 30*time.Second {
		t.Fatal("failed icon should retry")
	}
	var cache metadataStore
	cache.items = map[string]appMetadata{"com.example.test": meta}
	cache.invalidate()
	if len(cache.items) != 0 {
		t.Fatal("stale cache")
	}
}
