#!/usr/bin/env bash
# macmini-backup-upload-r2.sh — upload latest option_wizard dump to R2.
# Called by com.argon.backup-r2 launchd plist on Sundays at 04:00.
# Reads R2_* credentials from ~/projects/argon/.env.

set -euo pipefail

ARGON_HOME="${ARGON_HOME:-$HOME/projects/argon}"
cd "$ARGON_HOME"

# shellcheck disable=SC1091
set -a; source .env; set +a

for var in R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: $var not set in .env — skipping upload" >&2
    exit 1
  fi
done

R2_ENDPOINT="${R2_ENDPOINT_OVERRIDE:-https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com}"

latest="$(ls -1t data/backups/option_wizard-*.dump.gz | head -1)"
[[ -n "$latest" ]] || { echo "no local backup to upload" >&2; exit 1; }

echo "Uploading $latest to s3://${R2_BUCKET}/postgres/"
AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
aws s3 cp "$latest" "s3://${R2_BUCKET}/postgres/" \
  --endpoint-url "$R2_ENDPOINT"

echo "Upload OK"
