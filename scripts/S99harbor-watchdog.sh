#!/bin/sh
LOCKROOT=/volume1/docker/harbor/appdata/update-guardian/locks
PIDFILE=$LOCKROOT/harbor-watchdog.pid
WATCHDOG=/volume1/docker/harbor/bin/harbor-watchdog.sh
case "$1" in
  start)
    mkdir -p "$LOCKROOT"
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then exit 0; fi
    nohup sh "$WATCHDOG" >/dev/null 2>&1 &
    echo $! > "$PIDFILE"
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; rm -f "$PIDFILE"; fi
    ;;
  restart)
    $0 stop
    sleep 1
    $0 start
    ;;
  *)
    echo "Usage: $0 {start|stop|restart}"
    exit 1
    ;;
esac
