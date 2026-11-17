'use strict';
// Server-side publisher only. Credentials come from the host, never frontend files.
const { initializeApp, getApps, applicationDefault, cert } = require('firebase-admin/app');
const { getDatabase } = require('firebase-admin/database');
async function uploadNews(items) {
  if (!Array.isArray(items)) throw new Error('La lista de noticias no es válida.');
  const app = getApps().find(app => app.name === '28e-publisher') || initializeApp({
    credential: process.env.FIREBASE_SERVICE_ACCOUNT_JSON ? cert(JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT_JSON)) : applicationDefault(),
    databaseURL: 'https://yaire-591ca-default-rtdb.firebaseio.com', projectId: 'yaire-591ca'
  }, '28e-publisher');
  await getDatabase(app).ref('radio_state/news').set({ updatedAt: Date.now(), items });
}
if (require.main === module) {
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { input += chunk; if (input.length > 2000000) process.exit(1); });
  process.stdin.on('end', async () => {
    try { await uploadNews(JSON.parse(input)); process.exit(0); }
    catch { console.error('No se pudo publicar: revisa las credenciales de Firebase Admin en el servidor.'); process.exit(1); }
  });
}
module.exports = { uploadNews };
