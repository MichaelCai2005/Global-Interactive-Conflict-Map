// Play an exported board in a running gods-eye-view and screenshot every shot.
//
//   node tools/qa_globe_board.mjs <gods-eye-view dir> <board.gevbundle.json> <out dir>
//   node tools/qa_globe_board.mjs <gods-eye-view dir> board:<id>[:all] <out dir>
//
// The second form opens the globe at ?board=<id>, the link the conflict map's "Open in
// globe" button makes, and needs the globe started with VITE_CONFLICT_MAP_API set.
//
// Needs the globe running (npm run dev in gods-eye-view, http://localhost:4173) and a
// Chromium browser: set BROWSER to its path (defaults to Google Chrome on Windows).
// Imports the bundle through the same API the IMPORT button uses, loads each shot, and
// checks that its data packs loaded and no page errors happened.
import { readFile, mkdir, mkdtemp, writeFile } from 'node:fs/promises';
import os from 'node:os';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const [gevDir, bundlePath, outDir] = process.argv.slice(2);
if (!gevDir || !bundlePath || !outDir) {
  console.error('usage: node tools/qa_globe_board.mjs <gods-eye-view dir> <bundle> <out dir>');
  process.exit(2);
}
const require = createRequire(path.join(path.resolve(gevDir), 'package.json'));
const { default: puppeteer } = await import(pathToFileURL(require.resolve('puppeteer')).href);
const base = process.env.QA_BASE_URL || 'http://localhost:4173';
const executablePath =
  process.env.BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe';

await mkdir(outDir, { recursive: true });
const linked = /^board:(\d+)(:all)?$/.exec(bundlePath);
const bundle = linked ? null : await readFile(bundlePath, 'utf8');
let sceneId = bundle && JSON.parse(bundle).project.scenes[0].id;
let shots = bundle && JSON.parse(bundle).project.scenes[0].shots;

const browser = await puppeteer.launch({
  executablePath,
  headless: true,
  // Its own profile, so it does not hand off to a browser the user already has open.
  // Keep the path short: Chrome's GPU cache fails under long Windows paths.
  userDataDir: await mkdtemp(path.join(process.env.QA_PROFILE_ROOT || os.tmpdir(), 'qa-')),
  args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
});
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
let failures = 0;
const check = (name, passed, detail = '') => {
  console.log(`[${passed ? 'PASS' : 'FAIL'}] ${name}${detail ? ` (${detail})` : ''}`);
  if (!passed) failures++;
};

try {
  await page.setViewport({ width: 1440, height: 900 });
  const query = linked ? `&board=${linked[1]}${linked[2] ? '&include=all' : ''}` : '';
  await page.goto(`${base}/?welcome=0${query}`, { waitUntil: 'domcontentloaded' });
  const loaded = () =>
    page.waitForFunction(
      () =>
        window.__godsEyeView?.sceneDirector &&
        document.getElementById('loading-screen')?.classList.contains('hidden'),
      { timeout: 60000 },
    );
  // A freshly started Vite dev server re-bundles dependencies and fails the first load
  // ("504 Outdated Optimize Dep"); one reload picks up the new bundle.
  await loaded().catch(async () => {
    await page.reload({ waitUntil: 'domcontentloaded' });
    await loaded();
  });
  if (linked) {
    const opened = await page
      .waitForFunction(
        (id) =>
          window.__godsEyeView.sceneDirector._project?.scenes?.some((s) => s.id === id),
        { timeout: 60000 },
        `board-${linked[1]}`,
      )
      .then(() => true)
      .catch(() => false);
    check('?board= link opens the board', opened);
    const scene = await page.evaluate(
      (id) => window.__godsEyeView.sceneDirector._project.scenes.find((s) => s.id === id),
      `board-${linked[1]}`,
    );
    sceneId = scene.id;
    shots = scene.shots;
  }
  const imported = linked ? { ok: true } : await page.evaluate(
    async (text, name) => {
      const d = window.__godsEyeView.sceneDirector;
      try {
        await d.importProjectFile(new File([text], name));
        return { ok: true };
      } catch (error) {
        return { ok: false, message: String(error?.message || error) };
      }
    },
    bundle,
    path.basename(bundlePath),
  );
  if (!linked) check('bundle imports', imported.ok, imported.message);

  const report = [];
  for (const [i, shot] of shots.entries()) {
    const result = await page.evaluate(
      async (scene, id) => {
        const d = window.__godsEyeView.sceneDirector;
        const outcome = await d.loadShot(scene, id, { flyDuration: 0.5 });
        return { started: outcome?.started ?? true, packs: d.getDataPackState() };
      },
      sceneId,
      shot.id,
    );
    // Let imagery and terrain settle before the picture.
    await new Promise((r) => setTimeout(r, 6000));
    const file = path.join(outDir, `${String(i).padStart(2, '0')}-${shot.id}.png`);
    await page.screenshot({ path: file });
    const loaded = result.packs?.count ?? result.packs?.loaded ?? null;
    report.push({ shot: shot.id, title: shot.title, packs: result.packs, screenshot: file });
    check(
      `shot "${shot.title}" loads its ${shot.dataPackIds.length} pack(s)`,
      result.started !== false && (loaded === null || loaded === shot.dataPackIds.length),
      JSON.stringify(result.packs),
    );
  }
  await writeFile(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2));
  check('no page errors', errors.length === 0, errors.slice(0, 3).join(' | '));
} finally {
  await browser.close();
}
process.exit(failures ? 1 : 0);
