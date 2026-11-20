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
mkdir -p "$OUT"

fail() {
  echo "FAIL  $1"
  adb logcat -d > "$OUT/logcat.txt" || true
  grep -E "AndroidRuntime|FATAL|Capacitor" "$OUT/logcat.txt" | tail -60 || true
  adb exec-out screencap -p > "$OUT/android-failure.png" || true
  exit 1
}

# Waits for a line in the log, because a cold emulator takes its time.
wait_for() {
  local pattern="$1" seconds="$2"
  for _ in $(seq "$seconds"); do
    if adb logcat -d | grep -qE "$pattern"; then return 0; fi
    sleep 1
  done
  return 1
}

# A picture for a person to look at. Never the reason a run fails: on a
# headless emulator the screenshot is the least reliable thing there is, and
# the first run of this script lost the whole emulator to one.
shot() {
  timeout 30 adb exec-out screencap -p > "$OUT/$1" 2>/dev/null || { echo "      (no screenshot: $1)"; rm -f "$OUT/$1"; }
}

adb install -r "$APK"
adb logcat -c

adb shell am start -W -n "$PKG/.MainActivity" > /dev/null
wait_for "\[altaha\] bridge ready: android [0-9.]+ /(index\.html)?( |$|\")" 90 \
  || fail "the home page never reported in"
echo "ok    the app starts and the home page loads"

adb shell am start -W -a android.intent.action.VIEW -d "altaha://stock?ticker=TCS" "$PKG" > /dev/null
wait_for "\[altaha\] bridge ready: android [0-9.]+ /stock\.html" 60 \
  || fail "altaha://stock?ticker=TCS did not open the stock page"
echo "ok    a link from outside opens the page it names"

sleep 10
adb shell pidof "$PKG" > /dev/null || fail "the app is no longer running"
adb logcat -d > "$OUT/logcat.txt"
if grep -A3 "FATAL EXCEPTION" "$OUT/logcat.txt" | grep -q "$PKG"; then
  fail "the app crashed"
fi
if grep -qE "AltahaShell.*not implemented" "$OUT/logcat.txt"; then
  fail "the app's own plugin did not register"
fi
echo "ok    still running, nothing crashed, the app's own plugin answered"

shot android-stock.png
adb shell input keyevent KEYCODE_BACK || true
sleep 6
shot android-home.png
