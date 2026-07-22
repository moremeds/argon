#!/usr/bin/env bash
# Verify the BUILT IMAGE carries its runtime assets.
#
# No checkout-based test can catch a missing runtime asset: docs/ and src/ data
# files both exist in a working tree. They only vanish in the image. This is the
# check that would have caught the 2026-07-08 cutover.
#
# NOTE: this proves the asset reached the image, NOT that package-data is
# declared — the image installs /app/src editable, so it passes either way.
# The wheel inspection in tests/CI is the only thing that catches a missing
# [tool.setuptools.package-data] block.
#
# Usage: bash scripts/smoke_container_assets.sh [image-tag]
set -euo pipefail

IMAGE="${1:-argon-app:smoke}"

# ALWAYS rebuild. Reusing an existing tag lets a stale known-good image pass
# after the source has regressed — the one thing this script exists to prevent.
echo "building $IMAGE ..."
docker build -f docker/app.Dockerfile -t "$IMAGE" .

echo "--- canary calibration ---"
docker run --rm "$IMAGE" python -c "
from uw_scan.cards.canary_calibration import load_calibration, DEFAULT_PATH
cal = load_calibration()
print('OK', DEFAULT_PATH)
assert cal.composite_version == 1
"

echo "--- guidance rules ---"
docker run --rm "$IMAGE" python -c "
from uw_scan.api.routers.regime_validation import _parse_guidance_md
rules = _parse_guidance_md()
print('OK', len(rules), 'rules')
assert rules, 'guidance.md did not ship'
"

echo "PASS: runtime assets present in $IMAGE"
