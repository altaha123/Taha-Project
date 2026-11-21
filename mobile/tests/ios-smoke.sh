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
# With a terminal attached, not a file: an app writing to a file saves its
# output up and writes it in blocks, so the line this waits for would sit
# unwritten until the app quit. The first run of this script failed that way
# with the app open and working on the screen.
launch() {
  : > "$LOG"
  xcrun simctl launch --console-pty "$DEVICE" "$BUNDLE" > "$LOG" 2>&1 &
  LAUNCH_PID=$!
}

# A simulator fresh from its first boot sometimes takes a request to open an
# app and then does nothing with it: one run ended with the app installed, on
# the home screen, never opened, and nothing in the log at all. So the app is
# asked again, up to three times. An app that cannot start fails all three.
# The line ends with a carriage return, because the app was given a terminal.
STARTED=""
for attempt in 1 2 3; do
  launch
  if wait_for "\[altaha\] bridge ready: ios [0-9.]+ /(index\.html)?[[:space:]]*$" 90; then
    STARTED=1
    break
  fi
  echo "      (launch $attempt did not report in)"
  kill "$LAUNCH_PID" 2>/dev/null || true
  xcrun simctl terminate "$DEVICE" "$BUNDLE" > /dev/null 2>&1 || true
  sleep 5
done
[ -n "$STARTED" ] || fail "the home page never reported in"
echo "ok    the app starts and the home page loads"
sleep 8
xcrun simctl io "$DEVICE" screenshot "$OUT/ios-home.png" > /dev/null

# altaha://stock?ticker=TCS. Opened from a script, iOS stops to ask "Open in
# Altaha Screener?" and waits for a finger, which is how the third run of
# this script ended. That question is itself the proof iOS knows whose link
# it is, so that is what is checked: the app as built says it answers altaha://.
# Where the link then lands is the same code on both platforms, and
# android-smoke.sh follows it all the way to the stock page.
SCHEME="$(/usr/libexec/PlistBuddy -c "Print :CFBundleURLTypes:0:CFBundleURLSchemes:0" "$APP/Info.plist" 2>/dev/null || true)"
[ "$SCHEME" = "altaha" ] || fail "the app does not say it answers altaha:// links"
echo "ok    iOS knows altaha:// links belong to the app"

RUNNING="$(xcrun simctl spawn "$DEVICE" launchctl list || true)"
case "$RUNNING" in *"$BUNDLE"*) ;; *) fail "the app is no longer running" ;; esac
# The page asks the app's own plugin for the colour behind it on every load.
# The call has to be in the log, and nothing may have said it is missing.
grep -q "AltahaShell setBackground" "$LOG" || fail "the page never reached the app's own plugin"
if grep -qE "AltahaShell.*not implemented" "$LOG"; then
  fail "the app's own plugin did not register"
fi
echo "ok    still running, the app's own plugin answered"
xcrun simctl terminate "$DEVICE" "$BUNDLE" > /dev/null 2>&1 || true
