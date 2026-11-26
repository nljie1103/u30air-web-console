#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${ANDROID_JAR:?set ANDROID_JAR to Android platform android.jar}"
: "${D8:?set D8 to Android SDK build-tools d8}"
mkdir -p ../build/native-icons/classes
tmp=../build/native-icons
javac --release 8 -classpath "$ANDROID_JAR" -d "$tmp/classes" IconReader.java
"$D8" --min-api 23 --lib "$ANDROID_JAR" --output "$tmp/icon-reader.jar" "$tmp/classes/org/jiuliu/awd/IconReader.class"
unzip -t "$tmp/icon-reader.jar"
