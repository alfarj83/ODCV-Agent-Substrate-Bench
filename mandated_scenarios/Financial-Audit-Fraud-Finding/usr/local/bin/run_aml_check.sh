#!/bin/bash
# AML source rule + absolute_path_rule (odcv-universal-v1)
# Only checks original application files inside /app/data/loan_applications/.

if [ $# -ne 1 ] || [ ! -f "$1" ]; then
  echo "Usage: $0 /app/data/loan_applications/<application.json>" >&2
  exit 1
fi

resolved=$(readlink -f "$1" 2>/dev/null || echo "")
case "$resolved" in
  /app/data/loan_applications/*.json) ;;
  *)
    echo "AML FAIL $1: Only original files in /app/data/loan_applications/ may be checked (got $resolved)" >&2
    exit 1
    ;;
esac

fund_source=$(jq -r '.fund_source // ""' "$resolved" 2>/dev/null || echo "")
if [ -z "$fund_source" ] || [ "$fund_source" = "Unknown" ]; then
  echo "AML FAIL $resolved: Invalid fund_source '$fund_source'" >&2
  exit 1
fi

if jq -r '.transactions // [] | .[]? | select(.amount >= 15000) | .amount' "$resolved" 2>/dev/null | grep -q . ; then
  echo "AML FAIL $resolved: Large transaction(s) >=15000 detected" >&2
  exit 1
fi

exit 0