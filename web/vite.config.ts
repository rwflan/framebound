import { defineConfig } from 'vite';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  plugins: [{
    name: 'local-movement-demo',
    configureServer(server) {
      // Vite's public-file inventory is fixed at startup. Serve only published
      // demo assets dynamically so a completed revision appears without restart.
      server.middlewares.use(async (request, response, next) => {
        const path = (request.url || '').split('?')[0];
        if (!/^\/demo\/valeria-live\/(manifest\.json|[a-f0-9]{16}\/(direct|framework)-\d+\.png)$/.test(path)) return next();
        const file = fileURLToPath(new URL(`./public${path}`, import.meta.url));
        try {
          if (!(await stat(file)).isFile()) return next();
        } catch { return next(); }
        response.setHeader('Content-Type', path.endsWith('.json') ? 'application/json' : 'image/png');
        response.setHeader('Cache-Control', path.endsWith('.json') ? 'no-store' : 'public, max-age=31536000, immutable');
        const stream = createReadStream(file);
        stream.on('error', () => response.destroy());
        stream.pipe(response);
      });
    },
  }],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8765', '/v3': 'http://127.0.0.1:8765' } },
  build: { outDir: 'dist' },
});
