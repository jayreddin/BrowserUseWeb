#!/bin/bash
set -ue
ScrDir=$(cd $(dirname $0);pwd)
ScrName=$(basename $0)
echo "$ScrDir/$ScrName $*"

display_num="10"
geometry="1024x768"
rfbport="5910"
wsport="5920"

pid_vnc=""
pid_ws=""

function fn_cleanup(){
  echo "cleanup" >&2
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
    --geometry)
      if [ -z "$2" ]; then
          echo "ERROR: invalid option geometry $2" >&2
          exit 5
      fi
      geometry=$2
      shift 2
      ;;
    --rfbport)
      if [ -z "$2" ]; then
          echo "ERROR: invalid option rfbport $2" >&2
          exit 5
      fi
      rfbport=$2
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

if [ -z "$display_num" -o -z "$geometry" -o -z "$rfbport" -o -z "$wsport" ]; then
    echo "ERROR: invalid option" >&2
    exit 2
fi

VNC_OPT="-depth 24 -SecurityTypes None -localhost -alwaysshared -ac -quiet"
Xvnc ":$display_num" -geometry "$geometry" -rfbport "$rfbport" $VNC_OPT >/dev/null 2>&1 &
pid_vnc=$!
websockify --heartbeat 30 0.0.0.0:${wsport} localhost:${rfbport} >/dev/null 2>&1 &
pid_ws=$!
wait
