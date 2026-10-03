import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), 'dist');
const port = Number(process.env.PORT || 4173);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('PORT must be an integer from 1024 through 65535.');
const assets = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/index.html', ['index.html', 'text/html; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
  ['/app.js', ['app.js', 'text/javascript; charset=utf-8']],
  ['/core.js', ['core.js', 'text/javascript; charset=utf-8']],
  ['/api.js', ['api.js', 'text/javascript; charset=utf-8']],
  ['/workspace.css', ['workspace.css', 'text/css; charset=utf-8']]
]);
const server = http.createServer(async (req, res) => {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { Allow: 'GET, HEAD' }).end('Method not allowed');
    return;
  }
  let pathname;
  try { pathname = new URL(req.url, 'http://127.0.0.1').pathname; }
  catch { res.writeHead(400).end('Invalid URL'); return; }
  const asset = assets.get(pathname);
  if (!asset) { res.writeHead(404).end('Not found'); return; }
  try {
    const bytes = await readFile(path.join(root, asset[0]));
    res.writeHead(200, {
      'Content-Type': asset[1],
      'Content-Length': bytes.length,
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' https: http://127.0.0.1:* http://localhost:* http://[::1]:*; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    });
    res.end(req.method === 'HEAD' ? undefined : bytes);
  } catch {
    res.writeHead(500).end('Unable to load application files.');
  }
});
server.on('error', error => {
  console.error(error.code === 'EADDRINUSE' ? 'Port ' + port + ' is already in use. Set PORT to another port, or open dist/index.html directly.' : error.message);
  process.exitCode = 1;
});
server.listen(port, '127.0.0.1', () => console.log('Privacy Lens: http://127.0.0.1:' + port + '\nPress Ctrl+C to stop. No images are uploaded to this server.'));
