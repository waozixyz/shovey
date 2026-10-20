// Renders every Shovey sprite from the Three.js models in this folder.
//
//   npm install && node render.mjs [--only NAME,...] [--out DIR]
//
// Headless Chromium draws each model with WebGL; the page returns finished
// PNG bytes, which are written into the repository's asset folders together
// with a manifest describing every picture.
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';
import { execFileSync } from 'node:child_process';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.png': 'image/png' };

function option(name) {
    const at = process.argv.indexOf(name);
    return at > 0 ? process.argv[at + 1] : undefined;
}

function serve() {
    const server = createServer(async (request, response) => {
        const relative = decodeURIComponent(new URL(request.url, 'http://localhost').pathname).replace(/^\/+/, '');
        const player = /^classic-player\/player-(up|right|down|left)\.png$/.test(relative);
        const file = player ? path.join(ROOT, 'assets/shovey/sprites', path.basename(relative)) : path.resolve(HERE, relative);
        if (!player && !file.startsWith(HERE + path.sep)) { response.writeHead(403).end(); return; }
        try {
            const body = await readFile(file);
            response.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' }).end(body);
        } catch {
            response.writeHead(404).end();
        }
    });
    return new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server)));
}

async function main() {
    const only = option('--only')?.split(',');
    const out = path.resolve(ROOT, option('--out') || '.');
    const server = await serve();
    const browser = await puppeteer.launch({
        executablePath: process.env.CHROMIUM || '/usr/bin/chromium',
        headless: true,
        args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox',
            '--disable-gpu-sandbox', '--force-color-profile=srgb'],
    });
    try {
        const page = await browser.newPage();
        page.on('console', message => { if (message.type() === 'error') console.error(message.text()); });
        page.on('pageerror', error => { console.error(error); process.exitCode = 1; });
        await page.goto(`http://127.0.0.1:${server.address().port}/page.html`);
        await page.waitForFunction('window.sprites !== undefined', { timeout: 60000 });
        const names = await page.evaluate(() => window.sprites.list());
        const manifest = [];
        let written = 0;
        for (const entry of names) {
            if (only && !only.includes(entry.path) && !only.includes(entry.group)) continue;
            const encoded = await page.evaluate(name => window.sprites.render(name), entry.path);
            const bytes = Buffer.from(encoded, 'base64');
            const target = path.join(out, entry.path);
            await mkdir(path.dirname(target), { recursive: true });
            await writeFile(target, bytes);
            manifest.push({ path: entry.path, depicts: entry.depicts,
                sha256: createHash('sha256').update(bytes).digest('hex') });
            written += 1;
        }
        {
            // One manifest per asset folder, e.g. assets/shovey/art.json.
            const folders = new Map();
            for (const item of manifest) {
                const folder = item.path.split('/').slice(0, 2).join('/');
                if (!folders.has(folder)) folders.set(folder, []);
                folders.get(folder).push({ ...item, path: path.relative(folder, item.path) });
            }
            for (const [folder, files] of folders) {
                // Keep pictures other tools describe in the same folder,
                // such as Classic's pixel sprites from tools/pixel.
                const target = path.join(out, folder, 'art.json');
                let art = { generator: 'tools/art/render.mjs',
                    method: 'Rendered from Three.js models written for Shovey; no outside image is used.', files: [] };
                try { art = JSON.parse(await readFile(target, 'utf8')); } catch {}
                const rendered = new Set(files.map(item => item.path));
                art.files = [...art.files.filter(item => !rendered.has(item.path)), ...files];
                await writeFile(target, JSON.stringify(art, null, 2) + '\n');
            }
        }
        execFileSync('python3', [path.join(ROOT, 'tools/pixel/share_player.py'), '--output-root', out], { stdio: 'inherit' });
        console.log(`wrote ${written} sprites`);
    } finally {
        await browser.close();
        server.close();
    }
}

main().catch(error => { console.error(error); process.exit(1); });
