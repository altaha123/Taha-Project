#!/usr/bin/env bash
# The Android app, started on a real Android. Run by .github/workflows/mobile-apps.yml
# inside an emulator; works the same against a phone on USB.
#
# The browser tests prove the pages work. They cannot prove the app starts:
# a plugin that fails to register, or a line of MainActivity that throws,
# kills the app before any page exists. So this installs the APK, opens it,
# and reads the phone's log for the one line the bridge writes on every page
# (src/bridge.js, "[altaha] bridge ready").
#
#     mobile/tests/android-smoke.sh [path/to/app-debug.apk] [folder for screenshots]
set -euo pipefail

APK="${1:-mobile/android/app/build/outputs/apk/debug/app-debug.apk}"
OUT="${2:-mobile-smoke}"
PKG=in.altahascreener.app
LOG="$OUT/logcat.txt"
mkdir -p "$OUT"

# Every call to the phone has a time limit. An emulator in CI can stop
# answering without dying, and a command that waits for it waits for ever:
# the second run of this script sat for the whole job timeout that way.
phone() { timeout 60 adb "$@"; }

# A picture for a person to look at. Never the reason a run fails: on a
# headless emulator the screenshot is the least reliable thing there is.
shot() {
  timeout 30 adb exec-out screencap -p > "$OUT/$1" 2>/dev/null || { echo "      (no screenshot: $1)"; rm -f "$OUT/$1"; }
}

fail() {
  echo "FAIL  $1"
  timeout 20 adb logcat -d > "$LOG" 2>/dev/null || true
  grep -E "AndroidRuntime|FATAL|Capacitor|chromium" "$LOG" | tail -60 || true
  shot android-failure.png
  exit 1
}

# Waits for a line in the log, because a cold emulator takes its time. The
# log is written to a file and the file is searched: piping it into a search
# that stops at the first match can end the pipe early and read as "not found".
wait_for() {
  local pattern="$1" seconds="$2" i
  for i in $(seq "$seconds"); do
    timeout 20 adb logcat -d > "$LOG" 2>/dev/null || true
    if grep -qE "$pattern" "$LOG"; then return 0; fi
    sleep 1
  done
  return 1
}

phone install -r "$APK"

# The emulator draws with a software stand-in for a graphics chip, and the
# planets on the site are WebGL. Left on, the emulator stopped answering a few
# seconds after the home page appeared, twice. This switches WebGL off inside
# the web view for this run only; the pages already cope without it. A real
# phone has a real chip, and nothing in the app is changed.
phone shell "echo 'webview --disable-webgl --disable-gpu-rasterization' > /data/local/tmp/webview-command-line" || true

phone logcat -c || true

phone shell am start -W -n "$PKG/.MainActivity" > /dev/null
wait_for "\[altaha\] bridge ready: android [0-9.]+ /(index\.html)?[[:space:]\"]*$" 90 \
  || fail "the home page never reported in"
echo "ok    the app starts and the home page loads"

phone shell am start -W -a android.intent.action.VIEW -d "altaha://stock?ticker=TCS" "$PKG" > /dev/null \
  || fail "the phone did not answer when asked to open altaha://stock?ticker=TCS"
wait_for "\[altaha\] bridge ready: android [0-9.]+ /stock\.html" 60 \
  || fail "altaha://stock?ticker=TCS did not open the stock page"
echo "ok    a link from outside opens the page it names"

sleep 10
phone shell pidof "$PKG" > /dev/null || fail "the app is no longer running"
timeout 20 adb logcat -d > "$LOG" 2>/dev/null || true
if grep -A3 "FATAL EXCEPTION" "$LOG" | grep -q "$PKG"; then
  fail "the app crashed"
fi
# The page asks the app's own plugin for the colour behind it on every load.
# The call has to be in the log, and nothing may have said it is missing.
grep -q "pluginId: AltahaShell, methodName: setBackground" "$LOG" || fail "the page never reached the app's own plugin"
if grep -qE "AltahaShell.*not implemented" "$LOG"; then
  fail "the app's own plugin did not register"
fi
echo "ok    still running, nothing crashed, the app's own plugin answered"

shot android-stock.png
phone shell input keyevent KEYCODE_BACK || true
sleep 6
shot android-home.png
