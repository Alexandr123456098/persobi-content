#!/usr/bin/env bash
set -euo pipefail
PRED="${1:-}"; [ -z "$PRED" ] && { echo "usage: $0 <prediction_id>"; exit 1; }
while :; do
  J=$(curl -s -H "Authorization: Bearer $REPLICATE_API_TOKEN" \
        "https://api.replicate.com/v1/predictions/$PRED")
  S=$(printf '%s' "$J" | jq -r '.status')
  echo "status: $S"
  case "$S" in
    succeeded)
      URL=$(printf '%s' "$J" | jq -r '(.output | if type=="array" then .[0] else . end) // empty')
      echo "output: $URL"
      exit 0;;
    failed|canceled)
      printf '%s\n' "$J" | jq
      exit 2;;
  esac
  sleep 2
done
