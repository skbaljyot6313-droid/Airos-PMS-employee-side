/**
 * Static host for AiROS Staff — Vite dev server (middleware mode) in dev,
 * dist/ statics in production. The real API lives on the FastAPI backend
 * (VITE_API_URL); this server serves the app shell only.
 */
import express from 'express';
import { createServer as createViteServer } from 'vite';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = Number(process.env.PORT) || 3000;

async function start() {
  const isProduction = process.env.NODE_ENV === 'production';

  // Release artifacts for employee installs — files live in app-downloads/
  // (gitignored; baked into the deploy image). Served with APK MIME +
  // attachment headers so browsers download instead of navigating.
  const downloadsDir = path.resolve(__dirname, 'app-downloads');
  app.use(
    '/download',
    express.static(downloadsDir, {
      setHeaders(res, filePath) {
        if (filePath.endsWith('.apk')) {
          res.setHeader('Content-Type', 'application/vnd.android.package-archive');
          res.setHeader(
            'Content-Disposition',
            `attachment; filename="${path.basename(filePath)}"`
          );
        }
      },
    })
  );

  if (!isProduction) {
    const vite = await createViteServer({
      server: {
        middlewareMode: true,
        hmr: process.env.DISABLE_HMR !== 'true',
      },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.resolve(__dirname, 'dist');
    if (fs.existsSync(distPath)) {
      app.use(express.static(distPath));
      app.get('*', (_req, res) => {
        res.sendFile(path.resolve(distPath, 'index.html'));
      });
    }
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`AiROS Staff app listening on port ${PORT}`);
  });
}

start().catch((err) => {
  console.error('Failed to start server:', err);
});
