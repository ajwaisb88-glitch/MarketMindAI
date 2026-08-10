const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

const LOCAL_API_URL = 'http://127.0.0.1:8000';
let backendProcess = null;

function backendExecutablePath() {
  const name = process.platform === 'win32' ? 'marketmind-backend.exe' : 'marketmind-backend';
  return app.isPackaged
    ? path.join(process.resourcesPath, 'backend', name)
    : null;
}

function startBundledBackend() {
  const executable = backendExecutablePath();
  if (!executable || backendProcess) return;

  backendProcess = spawn(executable, ['--host', '127.0.0.1', '--port', '8000'], {
    windowsHide: true,
    stdio: 'ignore',
    env: {
      ...process.env,
      // Packaged product: require a valid license key, and keep the activated key
      // in the per-user data folder so it persists and survives updates.
      MARKETMIND_REQUIRE_LICENSE: '1',
      MARKETMIND_LICENSE_FILE: path.join(app.getPath('userData'), 'license.key'),
      MARKETMIND_LIVE_PRICES: '1',
    },
  });
  backendProcess.on('error', (error) => console.error('Unable to start MarketMind backend:', error));
  backendProcess.on('exit', () => { backendProcess = null; });
}

function stopBundledBackend() {
  if (backendProcess && !backendProcess.killed) backendProcess.kill();
  backendProcess = null;
}

// Auto-updater — only active in packaged builds
let autoUpdater;
try {
  autoUpdater = require('electron-updater').autoUpdater;
  autoUpdater.logger = require('electron').remote || null;
  autoUpdater.autoDownload = false;
} catch (_) {
  // electron-updater not available in dev/non-packaged builds
  autoUpdater = null;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const isDev = !app.isPackaged;
  if (isDev) {
    // Dev: load old UMD renderer until Vite dev server is running
    win.loadFile('index.html');
  } else {
    win.loadFile(path.join(__dirname, 'dist', 'ui', 'index.html'));
  }

  // Check for updates after window loads (packaged builds only)
  if (autoUpdater && app.isPackaged) {
    autoUpdater.checkForUpdates();

    autoUpdater.on('update-available', (info) => {
      dialog
        .showMessageBox(win, {
          type: 'info',
          title: 'Update available',
          message: `Version ${info.version} is available. Download now?`,
          buttons: ['Yes', 'Later'],
        })
        .then(({ response }) => {
          if (response === 0) autoUpdater.downloadUpdate();
        });
    });

    autoUpdater.on('update-downloaded', () => {
      dialog
        .showMessageBox(win, {
          type: 'info',
          title: 'Update ready',
          message: 'Restart now to install the update?',
          buttons: ['Restart', 'Later'],
        })
        .then(({ response }) => {
          if (response === 0) autoUpdater.quitAndInstall();
        });
    });
  }
}

ipcMain.handle('marketmind:get-backend-info', () => ({
  localApiUrl: LOCAL_API_URL,
  bundled: app.isPackaged,
  running: Boolean(backendProcess && !backendProcess.killed),
}));

app.whenReady().then(() => {
  startBundledBackend();
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', stopBundledBackend);

