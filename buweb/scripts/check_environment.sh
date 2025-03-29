#!/bin/bash
set -ue

ret=0

if type bwrap >/dev/null 2>&1; then
    echo "[CHECK] bubblewrap OK"
else
    echo "[CHECK] bubblewrap Not Found"
    ret=1
fi
if type Xvnc >/dev/null 2>&1; then
    echo "[CHECK] Xvnc OK"
else
    echo "[CHECK] Xvnc Not Found"
    ret=1
fi

if [ -n "${VIRTUAL_ENV:-}" -a -f "$VIRTUAL_ENV/bin/activate" ]; then
    echo "[CHECK] VENV ${VIRTUAL_ENV:-} OK"
    if ! type deactivate >/dev/null 2>&1; then
        source "$VIRTUAL_ENV/bin/activate"
    fi
else
    echo "[CHECK] VENV ${VIRTUAL_ENV:-} Not Found"
    ret=1
fi

CHROME_BIN=""
PLAYWRIGHT_DIR=~/.cache/ms-playwright
if [ -d "$PLAYWRIGHT_DIR" ]; then
  CHROME_BIN=$(find $PLAYWRIGHT_DIR -type f -executable -regex '.*chromium.*/chrome-linux/chrome' 2>/dev/null | sort -V | tail -1)
  if [ ! -x "$CHROME_BIN" ]; then
    CHROME_BIN=$(find $PLAYWRIGHT_DIR -type f -executable -regex '.*chrome.*/chrome-linux/chrome' 2>/dev/null | sort -V | tail -1)
  fi
fi
if [ ! -x "$CHROME_BIN" -a -x "/opt/google/chrome/google-chrome" ]; then
  CHROME_BIN="/opt/google/chrome/google-chrome"
fi
if [ -x "$CHROME_BIN" ]; then
    echo "[CHECK] $CHROME_BIN OK"
else
    echo "[CHECK] browser not found"
    ret=1
fi

exit $ret
