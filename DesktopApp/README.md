# MarketMind AI — Desktop (Electron + React)

This is a minimal Electron + React starter using UMD React builds for rapid prototyping.

Note: This workspace has been aligned to use Electron v43 (local binaries placed in `node_modules/electron/dist`).

Quick start (after installing dependencies):

```powershell
cd DesktopApp
npm install
npm run start
```

Notes:
- For production and real development, replace the UMD renderer with a bundler (Vite/webpack) and use a proper React app structure.
- `preload.js` is present for secure IPC bridging when needed.

Reproducible Electron install
----------------------------

This project includes a postinstall helper to make Electron installs reproducible in CI or air-gapped environments.

- After `npm install`, `node ./scripts/postinstall-electron.js` runs.
- The script checks `node_modules/electron/dist` and will copy from a local path if `ELECTRON_OVERRIDE_DIST_PATH` is set, or attempt a download if `ELECTRON_DOWNLOAD_URL` is provided.
- Recommended: provide `ELECTRON_OVERRIDE_DIST_PATH` pointing to an extracted Electron `dist` folder matching the version in `package.json`.

Example (PowerShell):

```powershell
$env:ELECTRON_OVERRIDE_DIST_PATH = 'C:\path\to\electron-v43.1.0-win32-x64\'
npm ci
```

The script is best-effort and will not fail `npm install` if it cannot automatically fetch an artifact — this keeps installs resilient while allowing you to enforce reproducible artifacts via environment variables.

CI example (GitHub Actions)
---------------------------------

Add the included workflow `.github/workflows/electron-dist-cache.yml` which:

- Restores a cached `DesktopApp/.electron_dist_cache` folder (if present).
- If present, copies it into `DesktopApp/node_modules/electron/dist` before `npm ci`.
- Runs `npm ci` to install dependencies.
- After install, copies `node_modules/electron/dist` back into `.electron_dist_cache` so future runs can reuse it.

This pattern provides reproducible installs by ensuring CI has a consistent `electron/dist` available even when the normal `electron` postinstall may fail or be blocked.

How to run the CI test (create branch + PR)
-----------------------------------------

To run the multi-platform CI matrix, create and push a branch with the workflow changes and open a PR against `main`. Example commands:

```bash
git checkout -b ci/electron-dist-matrix
git add .github/workflows/electron-ci-matrix.yml DesktopApp/package.json DesktopApp/scripts/postinstall-electron.js DesktopApp/README.md
git commit -m "ci: add electron dist cache + matrix workflow"
git push origin ci/electron-dist-matrix
# then open a PR on GitHub from that branch to main
```

After opening the PR, GitHub Actions will run the matrix (Ubuntu, Windows, macOS) and attempt to populate/capture the Electron `dist` cache.

Smoke test
----------

The CI will also start the backend and run a Node-based smoke test that calls `GET /predict?asset=gold` to verify the backend responds. The smoke test retries for up to ~20 seconds before failing.

If you'd like, I can prepare the commit locally and provide the exact `git` commands; however I cannot push to your remote repository from this environment — you'll need to run the `git push` step.
