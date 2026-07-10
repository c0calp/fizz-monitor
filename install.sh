#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "==> Creating Python venv"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
.venv/bin/playwright install chromium

echo "==> Fetching Buster extension"
bash scripts/get_buster.sh

cat <<EOF

==> Setup complete. Next steps:

  1. Run a first manual pass (Chrome window will open):
       ./.venv/bin/python monitor.py

     Solve any initial CAPTCHA by hand; cookies persist in ./profile,
     so subsequent runs should mostly breeze through.

  2. Once a clean run works, install the scheduler:
       cp com.user.fizzmonitor.plist ~/Library/LaunchAgents/
       launchctl load ~/Library/LaunchAgents/com.user.fizzmonitor.plist

  3. Inspect what's happening:
       tail -f $PWD/monitor.log
       cat $PWD/last.txt

  4. To stop:
       launchctl unload ~/Library/LaunchAgents/com.user.fizzmonitor.plist

EOF
