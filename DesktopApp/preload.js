const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('marketmind', {
  getBackendInfo: () => ipcRenderer.invoke('marketmind:get-backend-info'),
});
