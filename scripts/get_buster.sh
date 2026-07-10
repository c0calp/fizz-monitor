#!/usr/bin/env bash
# Fetch the Buster reCAPTCHA-solver extension and patch it so Playwright can
# click its solver button. Always exits 0: a missing extension surfaces as a
# scrape failure downstream (one alert email) instead of a red run every 30m.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/extensions/buster"

if [ -d "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
    echo "buster already present"
else
    AUTH=()
    [ -n "${GH_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $GH_TOKEN")
    LATEST=$(curl -fsSL "${AUTH[@]}" \
        https://api.github.com/repos/dessant/buster/releases/latest \
        | grep -oE 'https://[^"]*chrome\.zip' | head -1)
    if [ -z "$LATEST" ]; then
        echo "WARN: could not resolve Buster download URL" >&2
        exit 0
    fi
    TMP=$(mktemp -d)
    if curl -fsSL -o "$TMP/buster.zip" "$LATEST" \
        && mkdir -p "$DEST" \
        && unzip -q "$TMP/buster.zip" -d "$DEST"; then
        echo "installed from: $LATEST"
    else
        echo "WARN: Buster download/unzip failed" >&2
        rm -rf "$DEST" "$TMP"
        exit 0
    fi
    rm -rf "$TMP"
fi

# Buster injects its solver button into a CLOSED shadow DOM, which Playwright
# locators cannot pierce. Patch its content script to use an open shadow root.
BUSTER_JS="$DEST/src/base/script.js"
if [ -f "$BUSTER_JS" ] && grep -q 'mode:"closed"' "$BUSTER_JS"; then
    sed -i.bak 's/mode:"closed"/mode:"open"/g' "$BUSTER_JS"
    rm -f "$BUSTER_JS.bak"
    echo "patched Buster to use open shadow DOM"
elif [ -f "$BUSTER_JS" ]; then
    echo "shadow DOM patch already applied or pattern missing"
else
    echo "WARN: $BUSTER_JS not found — Buster layout changed?" >&2
fi
exit 0
