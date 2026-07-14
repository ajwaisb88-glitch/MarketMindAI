Overview

This PR adds reproducible Electron installation support and a comprehensive multi-platform CI matrix workflow for MarketMindAI's Electron-based desktop application.

Changes

1. **Reproducible Electron Install Support** (`DesktopApp/scripts/postinstall-electron.js`)
- Implements a postinstall helper script that runs after `npm install`
- Supports three methods for reproducible Electron binary distribution:
  - **Override path** (`ELECTRON_OVERRIDE_DIST_PATH`): Copy from a local extracted Electron dist folder (recommended for air-gapped installs)
  - **Download URL** (`ELECTRON_DOWNLOAD_URL`): Download from a custom artifact URL
  - Graceful fallback if neither is configured (install continues without failing)
- Cross-platform support: Windows (PowerShell), Unix/Linux/macOS (shell)
- Eliminates Electron binary download variability in CI/CD pipelines

2. **Electron Dist Cache Workflow** (`.github/workflows/electron-dist-cache.yml`)
- Runs on every push to `main` and pull request to `main`
- Single-platform workflow (Ubuntu) to establish and cache Electron binaries
- Workflow steps:
  1. Restores cached `DesktopApp/.electron_dist_cache` if available
  2. Pre-populates `node_modules/electron/dist` from cache (if present)
  3. Runs `npm ci` to install dependencies
  4. Saves downloaded Electron dist back to cache for future runs
- Significantly reduces build times in subsequent CI runs

3. **Multi-Platform CI Matrix Workflow** (`.github/workflows/electron-ci-matrix.yml`)
- Runs on pushes to `main` and all pull requests to `main`
- Tests across three platforms: **Ubuntu, Windows, macOS**
- For each platform:
  1. Checks out code
  2. Restores Electron dist cache (platform-specific)
  3. Pre-populates Electron binaries from cache
  4. Sets up Node.js 18
  5. Installs DesktopApp dependencies
  6. Sets up Python 3.10
  7. Installs backend dependencies
  8. Starts the FastAPI backend locally
  9. Runs smoke test to verify backend is responding
  10. Verifies postinstall helper functionality
  11. Saves Electron dist to cache for next run
- **Platform-specific scripting**: Bash for Unix, PowerShell for Windows

4. **Smoke Test Script** (`tools/smoke_test.js`)
- Simple Node.js HTTP client that validates backend is running
- Calls `GET /predict?asset=gold` endpoint
- Retries up to 20 times (1s delay between attempts)
- Verifies response contains expected `asset=gold` field
- Exits with code 0 on success, 1 on failure
- Provides visibility into backend availability during CI

5. **Documentation** (`DesktopApp/README.md`)
- Added "Reproducible Electron install" section with setup instructions
- Included environment variable options and examples
- Added "CI example (GitHub Actions)" section explaining the cache workflow
- Added "How to run the CI test" section with branch/commit commands
- Added "Smoke test" section explaining validation approach

Problem Solved

**Issue**: Electron binary downloads in CI are unreliable and inconsistent across platforms, leading to:
- Unpredictable build times (Electron binary is ~150MB+)
- Potential download failures in air-gapped or restricted environments
- No reproducible build artifacts

**Solution**: This PR implements:
- ✅ Cached Electron binaries to eliminate repeated downloads
- ✅ Configurable binary sources (local path or custom URL)
- ✅ Multi-platform CI validation
- ✅ Backend integration testing via smoke test
- ✅ Graceful fallback when caching isn't available

Testing

The workflows will execute when this PR is opened:
1. **electron-dist-cache.yml** - Establishes initial cache on Ubuntu
2. **electron-ci-matrix.yml** - Tests on Ubuntu, Windows, and macOS in parallel
   - Each platform builds independently
   - Smoke test validates backend endpoint
   - Subsequent runs should be faster due to cache reuse

Expected outcomes:
- All three platforms complete successfully
- Smoke test passes (backend responds to `/predict?asset=gold`)
- Postinstall helper runs without errors
- Cache is populated for faster subsequent builds

Files Changed

- `.github/workflows/electron-ci-matrix.yml` - NEW: Multi-platform CI matrix
- `.github/workflows/electron-dist-cache.yml` - NEW: Cache management workflow
- `DesktopApp/scripts/postinstall-electron.js` - NEW: Reproducible Electron install helper
- `DesktopApp/README.md` - UPDATED: Added CI and reproducible install documentation
- `tools/smoke_test.js` - NEW: Backend smoke test

Checklist

- [x] Electron v43.1.0 binary caching support
- [x] Cross-platform CI matrix (Ubuntu, Windows, macOS)
- [x] Reproducible install without external dependencies
- [x] Backend smoke test integration
- [x] Documentation and examples
- [ ] Follow-up: Monitor cache hit rates in subsequent CI runs

Related Issues

Closes: (if applicable)

---

Note: This PR is ready for review. The CI workflows will automatically run when the PR is opened. Please allow all checks to complete before merging.
