#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-IATREINER}"

cd "$(dirname "$0")/.."

echo "Installing build tools..."
python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller

if [ -f "client/requirements.txt" ]; then
  python3 -m pip install -r client/requirements.txt
fi

echo "Cleaning old build output..."
rm -rf build dist "${APP_NAME}.spec"

echo "Building macOS app..."
pyinstaller \
  --windowed \
  --clean \
  --name "${APP_NAME}" \
  --osx-bundle-identifier "com.amthedev.iatreiner" \
  client/volunteer_app.py

if [ ! -d "dist/${APP_NAME}.app" ]; then
  echo "PyInstaller did not produce dist/${APP_NAME}.app" >&2
  exit 1
fi

echo "Applying macOS app metadata..."
python3 - <<'PY'
import plistlib
from pathlib import Path

app_plist = Path("dist/IATREINER.app/Contents/Info.plist")
metadata_plist = Path("packaging/macos_info_plist.plist")

with app_plist.open("rb") as handle:
    app_data = plistlib.load(handle)
with metadata_plist.open("rb") as handle:
    metadata = plistlib.load(handle)

app_data.update(metadata)

with app_plist.open("wb") as handle:
    plistlib.dump(app_data, handle)
PY

echo "Creating DMG..."
rm -f "dist/${APP_NAME}-macOS.dmg"
hdiutil create \
  -volname "${APP_NAME}" \
  -srcfolder "dist/${APP_NAME}.app" \
  -ov \
  -format UDZO \
  "dist/${APP_NAME}-macOS.dmg"

echo "Created dist/${APP_NAME}.app and dist/${APP_NAME}-macOS.dmg"
