#!/usr/bin/env bash
# Rebuild the vendored daisyUI bundle from assets/corvus.css.
# Output (committed, served self-hosted): app/static/vendor/daisyui.min.css
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../assets"
npm install --no-audit --no-fund
./node_modules/.bin/tailwindcss -i corvus.css -o ../app/static/vendor/daisyui.min.css --minify
echo "wrote ../app/static/vendor/daisyui.min.css"
