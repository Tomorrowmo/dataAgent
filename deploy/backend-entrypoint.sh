#!/usr/bin/env bash
# Run as root: ensure the bind-mounted /data is owned by `app`, then exec
# the API as the unprivileged user. Containers don't have setuid so we use
# `gosu` from a tiny chown step. If gosu isn't available we fall back to
# `su -c` which works on slim Debian.
set -e

mkdir -p /data/db /data/uploads
chown -R app:app /data

if command -v gosu >/dev/null 2>&1; then
  exec gosu app "$@"
else
  exec su -p app -s /bin/bash -c "$(printf '%q ' "$@")"
fi
