const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');

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

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

