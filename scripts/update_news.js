#!/usr/bin/env node
'use strict';

/**
 * Launcher unificado: delega en scripts/sync_live_news.py para evitar
 * duplicar lógica o mezclar catálogos estáticos con noticias en vivo.
 */

const path = require('path');
const { spawn } = require('child_process');

const scriptPath = path.join(__dirname, 'sync_live_news.py');
const pythonBin = process.env.PYTHON_BINARY || (process.platform === 'win32' ? 'python' : 'python3');
const forwardArgs = process.argv.slice(2);

const child = spawn(pythonBin, [scriptPath, ...forwardArgs], {
  stdio: 'inherit',
  env: process.env,
});

child.on('error', (err) => {
  console.error(`[NEWS_WRAPPER] No se pudo ejecutar ${pythonBin}: ${err.message}`);
  process.exit(1);
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code == null ? 0 : code);
});
