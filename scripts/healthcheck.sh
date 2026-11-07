#!/usr/bin/env bash
# Probe an application's Redis-aware health endpoint with bounded retries.
set -euo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
    printf 'Usage: %s <base-url>\n' "$0" >&2
    exit 1
fi

url="${1%/}/health"

for attempt in {1..5}; do
    status=$(curl --silent --show-error --output /dev/null \
        --write-out '%{http_code}' --connect-timeout 2 --max-time 5 "$url") || status=000

    printf '[%s] Attempt %s/5 - HTTP %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$attempt" "$status"

    if [[ "$status" == "200" ]]; then
        exit 0
    fi

    if [[ "$attempt" -lt 5 ]]; then
        sleep 3
    fi
done

exit 1
