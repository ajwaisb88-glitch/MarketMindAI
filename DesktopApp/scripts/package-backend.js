/* eslint-disable no-console */
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const desktopDir = path.resolve(__dirname, '..');
const projectDir = path.resolve(desktopDir, '..');
const backendDir = path.join(projectDir, 'Backend');
const outputDir = path.join(desktopDir, 'backend');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const executableName = process.platform === 'win32' ? 'marketmind-backend.exe' : 'marketmind-backend';

fs.rmSync(outputDir, { recursive: true, force: true });
fs.mkdirSync(outputDir, { recursive: true });

console.log(`Bundling FastAPI backend with ${python}...`);
execFileSync(
  python,
  [
    '-m', 'PyInstaller',
    '--noconfirm',
    '--clean',
    '--onefile',
    '--name', 'marketmind-backend',
    '--distpath', outputDir,
    '--workpath', path.join(backendDir, 'build'),
    '--specpath', backendDir,
    '--collect-all', 'yfinance',
    '--collect-all', 'uvicorn',
    '--collect-all', 'fastapi',
    path.join(backendDir, 'marketmind_backend.py'),
  ],
  { cwd: backendDir, stdio: 'inherit' },
);

const executable = path.join(outputDir, executableName);
if (!fs.existsSync(executable)) {
  throw new Error(`Backend bundle was not created: ${executable}`);
}

console.log(`Backend bundle ready: ${executable}`);