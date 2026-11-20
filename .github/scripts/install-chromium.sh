#!/usr/bin/env bash
# Install Playwright's Chromium and the system packages it needs, without
# letting one slow package mirror decide whether the job finishes.
#
#   install-chromium.sh <path to the playwright binary>
#
# "playwright install --with-deps chromium" does two unrelated things: it
# downloads the browser from Playwright's own CDN, and it runs apt to install
# libraries and fonts from Ubuntu's mirror. The second is the one that stalls.
# It usually takes under a minute; on a bad day the runner's default mirror
# has served the font packages at a trickle for more than ten, and the job's
# time limit then cancelled a run in which nothing was wrong.
#
# apt has no "give up if this is too slow" setting, only a timeout for a
# connection that has gone silent. So each attempt is given a time limit
# here, and the attempt after a slow one asks a different mirror. Packages
# already downloaded are kept between attempts.
set -uo pipefail

PW="${1:?usage: install-chromium.sh <path to playwright>}"
# Seconds allowed for each attempt at the system packages.
LIMITS=(${APT_ATTEMPT_LIMITS:-180 240 240})
SUDO=sudo; [ "$(id -u)" = 0 ] && SUDO=

note() { echo "install-chromium: $*"; }

# ── The browser itself: Playwright's CDN, not apt ──────────────────────────
for n in 1 2 3; do
  if timeout --kill-after=15 300 "$PW" install chromium; then break; fi
  if [ "$n" = 3 ]; then echo "::error::Chromium could not be downloaded in three attempts."; exit 1; fi
  note "browser download failed or stalled (attempt $n); trying again"
  sleep 5
done

# ── The system packages: apt ───────────────────────────────────────────────
# A connection that goes quiet is dropped after 20 seconds and the file is
# asked for again, instead of being waited on for apt's default two minutes.
printf '%s\n' 'Acquire::Retries "3";' 'Acquire::http::Timeout "20";' 'Acquire::https::Timeout "20";' \
  | $SUDO tee /etc/apt/apt.conf.d/80-ci-impatient >/dev/null

# Leave the runner's default mirror for Ubuntu's own. GitHub's images list
# mirrors in apt-mirrors.txt, first one preferred; older ones name the
# mirror in the sources file.
other_mirror() {
  if [ -f /etc/apt/apt-mirrors.txt ] && grep -q azure /etc/apt/apt-mirrors.txt; then
    $SUDO sed -i '/azure\.archive\.ubuntu\.com/d' /etc/apt/apt-mirrors.txt
    grep -q . /etc/apt/apt-mirrors.txt || echo 'http://archive.ubuntu.com/ubuntu/' | $SUDO tee /etc/apt/apt-mirrors.txt >/dev/null
  fi
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    [ -f "$f" ] && $SUDO sed -i 's#http://azure\.archive\.ubuntu\.com/ubuntu#http://archive.ubuntu.com/ubuntu#g' "$f"
  done
  note "now asking archive.ubuntu.com instead of the runner's default mirror"
}

# An attempt cut short can leave apt running, or a package half set up.
tidy() {
  $SUDO pkill -x apt-get 2>/dev/null; $SUDO pkill -x apt 2>/dev/null
  for _ in $(seq 1 20); do pgrep -x apt-get >/dev/null || pgrep -x dpkg >/dev/null || break; sleep 1; done
  $SUDO dpkg --configure -a || true
}

n=0
for limit in "${LIMITS[@]}"; do
  n=$((n + 1))
  started=$(date +%s)
  # Playwright calls sudo itself when it is not root.
  timeout --kill-after=15 "$limit" "$PW" install-deps chromium
  code=$?
  took=$(( $(date +%s) - started ))
  if [ "$code" = 0 ]; then note "system packages installed in ${took}s (attempt $n)"; exit 0; fi
  if [ "$code" = 124 ] || [ "$code" = 137 ]; then
    echo "::warning::apt was still installing Chromium's packages after ${limit}s (attempt $n). The mirror is slow; stopped it."
  else
    echo "::warning::apt failed installing Chromium's packages (attempt $n, exit $code, ${took}s)."
  fi
  tidy
  [ "$n" = 1 ] && other_mirror
done

echo "::error::Chromium's system packages could not be installed in ${#LIMITS[@]} attempts. This is the package mirror, not the code under test: re-run the job."
exit 1
