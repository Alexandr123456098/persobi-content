#!/usr/bin/env bash
set -euo pipefail
cd /opt/content_factory
export PYTHONPATH=/opt/content_factory
export REPLICATE_API_TOKEN="$(grep -m1 '^REPLICATE_API_TOKEN=' .env | cut -d= -f2)"
echo "[SELFTEST] T2V 5s @16fps"
./.venv/bin/python -m app.adapters.replicate_adapter --mode text --prompt "SELFTEST T2V" --seconds 5 --fps 16 || true
echo "[SELFTEST] I2V 5s @16fps (catbox upload)"
TEST_JPG="/opt/content_factory/inbox/images/i2v_test.jpg"
[ -f "$TEST_JPG" ] || cp -f /opt/content_factory/out/last_upload.jpg "$TEST_JPG" || convert -size 1280x720 xc:black "$TEST_JPG"
./.venv/bin/python -m app.adapters.replicate_adapter --mode image --image "$TEST_JPG" --prompt "SELFTEST I2V" --seconds 5 --fps 16 || true
echo "[SELFTEST] last 5 predictions:"
ls -1t /opt/content_factory/out/predictions | head -n 5 | sed "s|^|  - |"
echo "[SELFTEST] last 5 outputs:"
ls -1t /opt/content_factory/out | head -n 5 | sed "s|^|  - |"
