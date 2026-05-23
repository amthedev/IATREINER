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
  client/volunteer_app.py

if [ ! -d "dist/${APP_NAME}.app" ]; then
  echo "PyInstaller did not produce dist/${APP_NAME}.app" >&2
  exit 1
fi

echo "Creating DMG..."
rm -f "dist/${APP_NAME}-macOS.dmg"
hdiutil create \
  -volname "${APP_NAME}" \
  -srcfolder "dist/${APP_NAME}.app" \
  -ov \
  -format UDZO \
  "dist/${APP_NAME}-macOS.dmg"

echo "Created dist/${APP_NAME}.app and dist/${APP_NAME}-macOS.dmg"
