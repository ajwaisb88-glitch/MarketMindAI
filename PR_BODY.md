## Overview

This PR adds reproducible Electron installation support and a multi-platform CI matrix for MarketMindAI's Electron desktop application.

## Changes

### Reproducible Electron installation

`DesktopApp/scripts/postinstall-electron.js` runs after `npm install` and supports:

- `ELECTRON_OVERRIDE_DIST_PATH` to copy a locally extracted Electron `dist` directory, including in air-gapped environments.
- `ELECTRON_DOWNLOAD_URL` to download and extract a custom Electron archive.
- A non-failing fallback when neither source is configured.

The helper works on Windows, Linux, and macOS.

### Electron distribution cache

`.github/workflows/electron-dist-cache.yml` runs on pushes and pull requests targeting `main`. It:

1. Restores the `DesktopApp/.electron_dist_cache` cache on Ubuntu.
2. Pre-populates Electron's `dist` directory when cache contents exist.
3. Runs `npm install --no-audit --no-fund` in `DesktopApp`.
4. Saves the Electron distribution for later workflow runs.

### Multi-platform CI matrix

`.github/workflows/electron-ci-matrix.yml` validates Ubuntu, Windows, and macOS. Each matrix job:

1. Restores and pre-populates its platform-specific Electron cache.
2. Installs Node.js 18 and `DesktopApp` dependencies.
3. Installs Python 3.10 and backend dependencies.
4. Starts the FastAPI backend locally.
5. Runs the Node smoke test against `/predict?asset=gold`.
6. Verifies the post-install helper and saves Electron binaries back to the cache.

The workflow uses Bash on Unix platforms and PowerShell on Windows where needed.

### Backend smoke test

`tools/smoke_test.js` retries the `GET /predict?asset=gold` request up to 20 times, confirms that the response identifies the `gold` asset, and exits non-zero if the backend never becomes available.

### Documentation

`DesktopApp/README.md` documents reproducible install options, CI cache usage, and the smoke-test workflow.

## Problem solved

Electron downloads can be large and unreliable in restricted or air-gapped CI environments. This PR provides cache-backed installation, configurable local or remote binary sources, graceful fallback behavior, and automated backend validation across three operating systems.

## Expected CI results

- [x] Electron v43.1.0 distribution caching
- [x] Ubuntu, Windows, and macOS CI coverage
- [x] Backend smoke-test coverage
- [x] Post-install helper verification
- [ ] Monitor cache hit rates in subsequent runs

## Related issues

Closes: (if applicable)
