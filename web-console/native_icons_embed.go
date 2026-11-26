//go:build nativeicons

package main

import _ "embed"

//go:embed build/native-icons/icon-reader.jar
var nativeIconDEX []byte
