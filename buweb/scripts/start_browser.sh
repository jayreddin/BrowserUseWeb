#!/bin/bash
set -ue
ScrDir=$(cd $(dirname $0);pwd)
ScrName=$(basename $0)
echo "$ScrDir/$ScrName $*"

display_num="10"
workdir="$HOME/tmp"
hosts=""
cdpport=""
wsport=""

pid_vnc=""
pid_ws=""

function fn_cleanup(){
  echo "cleanup browser" >&2
  set +u +e
  if [ -n "$pid_ws" ]; then
    echo "cleanup kill ws $pid_ws" >&2
    kill -9 "$pid_ws"
  fi
  if [ -n "$pid_vnc" ]; then
    echo "cleanup kill vnc $pid_vnc" >&2
    kill -9 "$pid_vnc"
  fi
}
trap fn_cleanup EXIT

while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    --display)
      if [ -z "$2" ]; then
          echo "ERROR: invalid option display $2" >&2
          exit 5
      fi
      display_num=$2
      shift 2
      ;;
    --workdir)
      if [ -z "$2" ]; then
          echo "ERROR: invalid option workdir $2" >&2
          exit 5
      fi
      workdir=$2
      shift 2
      ;;
    --hosts)
      if [ -z "$2" ]; then
          echo "ERROR: invalid option hosts $2" >&2
          exit 5
      fi
      hosts=$2
      shift 2
      ;;
    --cdpport)
      if [ -z "$2" ]; then
          echo "ERROR: invalid option cdpport $2" >&2
          exit 5
      fi
      cdpport=$2
      shift 2
      ;;
    --wsport)
      if [ -z "$2" ]; then
          echo "ERROR: invalid option wsport $2" >&2
          exit 5
      fi
      wsport=$2
      shift 2
      ;;
    *)
     exit 5
     ;;
  esac
done

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
if [ ! -x "$CHROME_BIN" ]; then
  echo "ERROR: chrome not found" >&2
  exit 5
fi

CHROME_OPT=""
CHROME_OPT="$CHROME_OPT --no-first-run --no-default-browser-check --disable-infobars --ozone-platform=x11"
CHROME_OPT="$CHROME_OPT --disable-sync --password-store=basic"
CHROME_OPT="$CHROME_OPT --disable-extensions --disable-metrics --disable-metrics-reporting --disable-crash-reporter --disable-logging"
CHROME_OPT="$CHROME_OPT --disable-smooth-scrolling --disable-spell-checking --disable-remote-fonts --disable-dev-shm-usage"
CHROME_OPT="$CHROME_OPT --disable-geolocation"
CHROME_OPT="$CHROME_OPT --disable-gpu --disable-webgl --disable-vulkan --disable-accelerated-layers --enable-unsafe-swiftshader"
CHROME_OPT="$CHROME_OPT --disable-features=Translate"
#CHROME_OPT="$CHROME_OPT --enable-strict-powerful-feature-restrictions"
if [ -n "$cdpport" ]; then
    CHROME_OPT="$CHROME_OPT --remote-debugging-port=${cdpport}"
fi
export GOOGLE_API_KEY=no
export GOOGLE_DEFAULT_CLIENT_ID=no
export GOOGLE_DEFAULT_CLIENT_SECRET=no

if [ -n "$display_num" ]; then
    export DISPLAY=":${display_num}"
fi

BWRAP_OPT="--bind / / --dev /dev --bind /tmp /tmp"
if [ -n "$workdir" ]; then
    mkdir -p "$workdir"
    BWRAP_OPT="$BWRAP_OPT --bind $workdir $HOME --chdir $HOME"
fi
if [ -n "$hosts" ]; then
    BWRAP_OPT="$BWRAP_OPT --ro-bind $hosts /etc/hosts"
fi
if [ -d "$PLAYWRIGHT_DIR" ]; then
    BWRAP_OPT="$BWRAP_OPT --ro-bind $PLAYWRIGHT_DIR $PLAYWRIGHT_DIR"
fi
export LANG=C
bwrap $BWRAP_OPT $CHROME_BIN $CHROME_OPT >/dev/null 2>&1
