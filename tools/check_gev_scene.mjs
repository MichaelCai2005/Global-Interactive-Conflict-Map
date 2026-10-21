// Check an exported board against gods-eye-view's own validators.
//
//   node tools/check_gev_scene.mjs <path-to-gods-eye-view> <board.gevbundle.json>
//
// Runs the same code the globe runs on IMPORT: the bundle and scene-document parser,
// then the GeoJSON pack decoder on every asset, then checks that every card targets a
// feature that exists in its pack. Exits 1 with the reason if the globe would refuse it.
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const [gevDir, file] = process.argv.slice(2);
if (!gevDir || !file) {
  console.error('usage: node tools/check_gev_scene.mjs <gods-eye-view dir> <bundle>');
  process.exit(2);
}
const load = (rel) => import(pathToFileURL(path.join(gevDir, rel)).href);
const { parseSceneShare } = await load('src/director/sharing/bundle.js');
const { decodePackGeoJSON } = await load('src/director/packs/geojson.js');

const text = await readFile(file, 'utf8');
let parsed;
try {
  parsed = await parseSceneShare(text);
} catch (error) {
  console.error(`REJECTED by parseSceneShare: ${error.message}`);
  process.exit(1);
}
const { project, assets } = parsed;
let features = 0;
const featureIds = new Map();
for (const scene of project.scenes) {
  for (const pack of scene.dataPacks || []) {
    const asset = assets.get(pack.source.path);
    if (!asset) {
      console.error(`REJECTED: pack ${pack.id} has no bundled asset`);
      process.exit(1);
    }
    let decoded;
    try {
      decoded = decodePackGeoJSON(asset.bytes);
    } catch (error) {
      console.error(`REJECTED: pack ${pack.id}: ${error.message}`);
      process.exit(1);
    }
    features += decoded.length;
    featureIds.set(pack.id, new Set(decoded.map((f) => f.id)));
  }
  for (const shot of scene.shots) {
    for (const item of shot.interactions || []) {
      const ids = featureIds.get(item.target.packId);
      if (!ids?.has(item.target.featureId)) {
        console.error(
          `REJECTED: shot ${shot.id} card ${item.id} targets missing feature ` +
            `${item.target.packId}/${item.target.featureId}`,
        );
        process.exit(1);
      }
    }
  }
}
const scenes = project.scenes;
const shots = scenes.reduce((n, s) => n + s.shots.length, 0);
const cards = scenes.reduce(
  (n, s) => n + s.shots.reduce((m, shot) => m + (shot.interactions?.length || 0), 0),
  0,
);
console.log(
  `OK: version ${project.version}, ${scenes.length} scene(s), ${shots} shot(s), ` +
    `${assets.size} pack(s), ${features} feature(s), ${cards} card(s)`,
);
