#!/usr/bin/env bash
# Orchestrates one monitor pass: scrape -> diff against baseline -> alert.
# Never exits nonzero on a scrape failure (the fail counter + alert email
# handle chronic breakage); the only hard failure is a change we could not
# email about, so the baseline stays put and the next run retries.
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$ROOT/state"
LAST="$STATE_DIR/last.txt"
CUR="$ROOT/current.txt"
FAILCOUNT="$ROOT/.failcount"
THRESHOLD="${FAIL_ALERT_THRESHOLD:-8}"
RUNS_PER_DAY=48
URL="https://www.the-fizz.com/en/search-nl/?searchcriteria=BUILDING:THE_FIZZ_LEIDEN;AREA:LEIDEN;"
RUN_URL="${GITHUB_SERVER_URL:-}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}"
# CI scrapes with Playwright; on a Mac you can test with the Safari path:
#   SCRAPER_CMD="/usr/bin/osascript check.scpt" bash ci_check.sh
SCRAPER_CMD="${SCRAPER_CMD:-python monitor.py}"

out() { if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "status=$1" >> "$GITHUB_OUTPUT"; fi; }
mkdir -p "$STATE_DIR"

# workflow_dispatch test hook: force a diff on the next comparison
if [ "${FORCE_CHANGE:-false}" = "true" ]; then
    echo "SEEDED DUMMY BASELINE" > "$LAST"
    echo "forced change: dummy baseline seeded"
fi

if $SCRAPER_CMD > "$CUR" 2> scrape.err && [ -s "$CUR" ]; then
    echo 0 > "$FAILCOUNT"
    if [ ! -f "$LAST" ]; then
        cp "$CUR" "$LAST"
        echo "baseline saved: $(cat "$CUR")"
        out baseline
        exit 0
    fi
    if ! cmp -s "$LAST" "$CUR"; then
        if { echo "$URL"; echo; cat "$CUR"; echo; echo "run: $RUN_URL"; } \
             | python send_email.py "Fizz Leiden CHANGED"; then
            cp "$CUR" "$LAST"
            echo "CHANGE: $(head -c 240 "$CUR")"
            out changed
        else
            echo "CHANGE detected but email failed — baseline kept for retry"
            out email_failed
            exit 1
        fi
    else
        echo "ok (no change)"
        out ok
    fi
    exit 0
else
    cat scrape.err >&2
    PREV=$(cat "$FAILCOUNT" 2>/dev/null || echo 0)
    [[ "$PREV" =~ ^[0-9]+$ ]] || PREV=0
    N=$((PREV + 1))
    echo "$N" > "$FAILCOUNT"
    echo "scrape failed (consecutive: $N)"
    if [ "$N" -eq "$THRESHOLD" ] || { [ "$N" -gt "$THRESHOLD" ] \
         && [ $(( (N - THRESHOLD) % RUNS_PER_DAY )) -eq 0 ]; }; then
        { echo "Scraper failed $N consecutive runs (~$((N / 2))h)."
          echo
          tail -c 2000 scrape.err
          echo
          echo "run: $RUN_URL"
        } | python send_email.py "Fizz monitor BROKEN ($N consecutive failures)" \
          || echo "failure-alert email also failed"
    fi
    out failed
    exit 0
fi
