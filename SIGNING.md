# Signing and Security Reputation

IATREINER should not try to bypass Gatekeeper, SmartScreen, antivirus, or other operating-system protections. The correct way to reduce warnings is to distribute transparent, signed builds.

## Windows

For lowest friction on Windows:

1. Buy or use an existing Authenticode code-signing certificate.
2. Build `IATREINER-Setup.exe` with the GitHub Actions workflow or `scripts/build_windows.ps1`.
3. Sign both the portable executable and installer with `signtool`.

Example:

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a dist\IATREINER.exe
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a installer\Output\IATREINER-Setup.exe
```

SmartScreen reputation improves over time as signed builds are downloaded and used. Unsigned executables may still show warnings even when the app is safe.

## macOS

For lowest friction on MacBook:

1. Enroll in the Apple Developer Program.
2. Sign the `.app` with a Developer ID Application certificate.
3. Notarize the `.dmg` with Apple.
4. Staple the notarization ticket.

Example outline:

```bash
codesign --deep --force --options runtime --sign "Developer ID Application: YOUR NAME" dist/IATREINER.app
hdiutil create -volname IATREINER -srcfolder dist/IATREINER.app -ov -format UDZO dist/IATREINER-macOS.dmg
xcrun notarytool submit dist/IATREINER-macOS.dmg --apple-id YOU@example.com --team-id TEAMID --password APP_PASSWORD --wait
xcrun stapler staple dist/IATREINER-macOS.dmg
```

Unsigned macOS builds can require right-click > Open or manual approval in Privacy and Security.

## App behavior that helps trust

- Autostart is opt-in and reversible in the app.
- The app shows a visible window, log, consent text, and stop button.
- It does not request admin privileges.
- It does not access personal files, keyboard, mouse, screen, or shell commands.
- It only runs closed, predefined jobs.
