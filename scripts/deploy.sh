#!/usr/bin/env bash
set -euo pipefail

# Single source of truth for what runs on the EC2 server to deploy a new
# build. A copy of this file lives on the server and is what actually
# executes there (the SSH deploy key is restricted, via an authorized_keys
# forced-command, to run only that copy). This in-repo copy exists for
# review/history and so the workflow step stays correct and equivalent if
# that restriction is ever removed.
#
# `set -euo pipefail` above is load-bearing: if `docker pull` fails, the
# script must abort immediately, before the existing container is touched.

cd ~/PO-agents

docker pull ghcr.io/jasonpaul0727/po-agents:latest

# Only reached if the pull above succeeded.
docker stop po-intake || true
docker rm po-intake || true

docker run -d --name po-intake \
  --env-file .env \
  -v po_data:/app/data \
  -p 127.0.0.1:8000:8000 \
  --restart unless-stopped \
  ghcr.io/jasonpaul0727/po-agents:latest

# Real HTTP health check with retries. A crash-looping or 500-ing container
# must not read as a successful deploy, so we poll for the app's actual
# response rather than just checking that the process is alive. 401 is the
# expected, correct response here: it proves Uvicorn is serving AND the
# Basic Auth guard in backend/security.py is intact.
status=""
for _ in $(seq 1 20); do
  status="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ || true)"
  if [ "$status" = "401" ]; then
    break
  fi
  sleep 2
done

if [ "$status" != "401" ]; then
  echo "Health check failed: expected HTTP 401 from http://127.0.0.1:8000/, last got '${status}'" >&2
  exit 1
fi

echo "Health check passed (HTTP 401 from http://127.0.0.1:8000/)."

# Prune old images so the disk doesn't fill up over time.
docker image prune -af --filter "until=168h"
