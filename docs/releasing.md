# Release maintenance / 版本发布维护

QuickOps uses semantic versions and annotated Git tags. During the `0.x` phase, minor versions may
contain API or database changes; release notes must call out any migration impact.

## Release checklist

1. Update the versions in `package.json`, `package-lock.json`, `pyproject.toml`, and the public
   documentation.
2. Update `CHANGELOG.md` and create release notes for the target version.
3. Run the complete validation suite:

   ```bash
   npm ci
   uv sync --dev
   npm run build
   npm run test:sites
   npm run lint:backend
   npm run test:backend
   npm audit --omit=dev
   ```

4. Build the Linux x86_64 offline installer in a compatible Linux build environment:

   ```bash
   ./scripts/build-offline-installer.sh
   ```

5. Verify the installer checksum and smoke-test installation and in-place upgrade on a disposable
   Linux host. Confirm that SQLite backup and settings preservation work.
6. Scan the exact staged source and release assets for credentials and private data.
7. Merge to `main`, create the annotated version tag, and publish a GitHub Release containing the
   installer and its `.sha256` file.
8. Verify the public download, checksum, clean installation, login, host telemetry, terminal, AI
   streaming, and HITL approval flow.

Never place model keys or deployment login credentials in Git tags, release notes, workflow logs,
or release assets. Users must explicitly approve any in-product download or upgrade operation.
