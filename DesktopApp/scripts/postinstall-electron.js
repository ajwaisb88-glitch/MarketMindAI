const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');

function log(...args) { console.log('[postinstall-electron]', ...args); }

(async () => {
  try {
    const appRoot = path.join(__dirname, '..');
    const pkg = require(path.join(appRoot, 'package.json'));
    const devDeps = pkg.devDependencies || {};
    const dep = devDeps.electron || pkg.dependencies && pkg.dependencies.electron;
    let version = dep || '43.1.0';
    version = version.replace(/^[\^~>=<]+/, '');

    const destDist = path.join(appRoot, 'node_modules', 'electron', 'dist');
    const isWindows = process.platform === 'win32';
    const expectedExe = isWindows ? 'electron.exe' : 'electron';

    // if dist already has electron binary, nothing to do
    if (fs.existsSync(path.join(destDist, expectedExe))) {
      log('electron binary already present at', destDist);
      return;
    }

    const override = process.env.ELECTRON_OVERRIDE_DIST_PATH || process.env.ELECTRON_CUSTOM_DIST_PATH;
    const downloadUrl = process.env.ELECTRON_DOWNLOAD_URL;

    // Helper: recursive copy
    const copyRecursive = (src, dest) => {
      if (!fs.existsSync(src)) throw new Error('Source not found: ' + src);
      if (!fs.existsSync(dest)) fs.mkdirSync(dest, { recursive: true });
      const entries = fs.readdirSync(src, { withFileTypes: true });
      for (const e of entries) {
        const srcPath = path.join(src, e.name);
        const destPath = path.join(dest, e.name);
        if (e.isDirectory()) {
          copyRecursive(srcPath, destPath);
        } else if (e.isFile()) {
          fs.copyFileSync(srcPath, destPath);
        }
      }
    };

    if (override) {
      const abs = path.isAbsolute(override) ? override : path.join(process.cwd(), override);
      if (!fs.existsSync(abs)) {
        log('ELECTRON_OVERRIDE_DIST_PATH set but path not found:', abs);
      } else {
        log('Copying Electron dist from override path:', abs);
        copyRecursive(abs, destDist);
        log('Copied Electron dist to', destDist);
        return;
      }
    }

    if (downloadUrl) {
      try {
        log('Attempting to download electron from', downloadUrl);
        const https = require('https');
        const os = require('os');
        const tmp = path.join(os.tmpdir(), `electron-download-${Date.now()}`);
        const zipPath = tmp + '.zip';
        await new Promise((resolve, reject) => {
          const file = fs.createWriteStream(zipPath);
          https.get(downloadUrl, (res) => {
            if (res.statusCode >= 400) return reject(new Error('Download failed: ' + res.statusCode));
            res.pipe(file);
            file.on('finish', () => file.close(resolve));
          }).on('error', reject);
        });
        log('Downloaded zip to', zipPath);
        // extract
        if (isWindows) {
          // use PowerShell Expand-Archive
          await new Promise((resolve, reject) => {
            const cmd = `powershell -NoProfile -Command "Expand-Archive -Force -LiteralPath '${zipPath}' -DestinationPath '${tmp}'"`;
            exec(cmd, (err, stdout, stderr) => err ? reject(err) : resolve());
          });
        } else {
          // try unzip
          await new Promise((resolve, reject) => {
            exec(`unzip -o '${zipPath}' -d '${tmp}'`, (err) => err ? reject(err) : resolve());
          });
        }
        // Find the extracted folder (may be electron-v{version}-...)
        const files = fs.readdirSync(tmp);
        const extracted = files.length === 1 ? path.join(tmp, files[0]) : tmp;
        copyRecursive(extracted, destDist);
        log('Extracted and copied electron dist to', destDist);
        return;
      } catch (e) {
        log('Download/extract failed:', e.message);
      }
    }

    log('No override path or download URL provided. To make installs reproducible, either:');
    log('- Set ELECTRON_OVERRIDE_DIST_PATH to a local extracted electron `dist` folder (recommended for air-gapped installs).');
    log(`  Example (Windows): set ELECTRON_OVERRIDE_DIST_PATH=C:\\path\\to\\electron-v${version}-win32-x64\\`);
    log('- Or set ELECTRON_DOWNLOAD_URL to an electron release archive URL for your platform.');
    log('This script exits without failing so `npm install` can continue; run the copy manually if needed.');
  } catch (err) {
    console.error('[postinstall-electron] error', err && err.stack ? err.stack : err);
  }
})();
