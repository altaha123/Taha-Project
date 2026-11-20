#!/usr/bin/env bash
# The iOS app, started on a real iOS (the simulator). Run by
# .github/workflows/mobile-apps.yml on a Mac; works the same on your own.
#
# Same reason as android-smoke.sh: the pages are tested in a browser, and this
# is the proof that the app around them starts, registers its plugin and shows
# the page it was asked for.
#
#     mobile/tests/ios-smoke.sh path/to/App.app [folder for screenshots]
set -euo pipefail

APP="${1:?path to the built App.app}"
OUT="${2:-mobile-smoke}"
BUNDLE=in.altahascreener.app
LOG="$OUT/ios-console.txt"
mkdir -p "$OUT"

fail() {
  echo "FAIL  $1"
  tail -80 "$LOG" 2>/dev/null || true
  xcrun simctl io booted screenshot "$OUT/ios-failure.png" || true
  exit 1
}

wait_for() {
  local pattern="$1" seconds="$2"
  for _ in $(seq "$seconds"); do
    if grep -qE "$pattern" "$LOG" 2>/dev/null; then return 0; fi
    sleep 1
  done
  return 1
}

# Any iPhone the machine has.
DEVICE="$(xcrun simctl list devices available | awk '/^[[:space:]]+iPhone/ { if (match($0, /[0-9A-F]+-[0-9A-F]+-[0-9A-F]+-[0-9A-F]+-[0-9A-F]+/)) { print substr($0, RSTART, RLENGTH); exit } }')"
[ -n "$DEVICE" ] || { echo "no iPhone simulator on this machine"; exit 1; }
xcrun simctl boot "$DEVICE" 2>/dev/null || true
xcrun simctl bootstatus "$DEVICE" -b > /dev/null

xcrun simctl install "$DEVICE" "$APP"
: > "$LOG"
# With a terminal attached, not a file: an app writing to a file saves its
# output up and writes it in blocks, so the line this waits for would sit
# unwritten until the app quit. The first run of this script failed that way
# with the app open and working on the screen.
xcrun simctl launch --console-pty "$DEVICE" "$BUNDLE" > "$LOG" 2>&1 &

# The line ends with a carriage return here, because the app was given a
# terminal. The second run of this script failed on exactly that.
wait_for "\[altaha\] bridge ready: ios [0-9.]+ /(index\.html)?[[:space:]]*$" 120 \
  || fail "the home page never reported in"
echo "ok    the app starts and the home page loads"
sleep 8
xcrun simctl io "$DEVICE" screenshot "$OUT/ios-home.png" > /dev/null

xcrun simctl openurl "$DEVICE" "altaha://stock?ticker=TCS"
wait_for "\[altaha\] bridge ready: ios [0-9.]+ /stock\.html" 60 \
  || fail "altaha://stock?ticker=TCS did not open the stock page"
echo "ok    a link from outside opens the page it names"
sleep 8
xcrun simctl io "$DEVICE" screenshot "$OUT/ios-stock.png" > /dev/null

xcrun simctl spawn "$DEVICE" launchctl list | grep -q "$BUNDLE" || fail "the app is no longer running"
if grep -qE "AltahaShell.*not implemented" "$LOG"; then
  fail "the app's own plugin did not register"
fi
echo "ok    still running, the app's own plugin answered"
xcrun simctl terminate "$DEVICE" "$BUNDLE" > /dev/null 2>&1 || true
