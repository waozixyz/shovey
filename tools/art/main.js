// Draws one sprite at a time. Ground tiles are seen straight from above so
// neighbours join seamlessly; objects are seen from a raised front angle,
// standing on a soft shadow, with a thin ink outline for small screens.
import * as THREE from 'three';
import { islandSprites } from './island.js';
import { cards } from './cards.js';
import { playerTexturesReady } from './shovey.js';

await playerTexturesReady;

const OUTPUT = 128;
const SCALE = 4;
const SIZE = OUTPUT * SCALE;

const canvas = document.createElement('canvas');
canvas.width = canvas.height = SIZE;
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(SIZE, SIZE, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.setClearColor(0x000000, 0);

// Light comes from the top left of the screen in both views.
function lights(scene, span = 1.4) {
    scene.add(new THREE.HemisphereLight(0xeef6f3, 0x6e4c36, 1.25));
    const key = new THREE.DirectionalLight(0xfff4e6, 2.3);
    key.position.set(-2.2 * span / 1.4, 5 * span / 1.4, -2.6 * span / 1.4);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = key.shadow.camera.bottom = -span;
    key.shadow.camera.right = key.shadow.camera.top = span;
    key.shadow.camera.near = 0.1;
    key.shadow.camera.far = 14 * span;
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.01;
    key.shadow.radius = 6;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xcfe6f0, 0.7);
    rim.position.set(2.5, 2.2, 3);
    scene.add(rim);
}

// Straight down: x to the right, +z towards the bottom of the screen.
function topCamera() {
    const camera = new THREE.OrthographicCamera(-0.5, 0.5, 0.5, -0.5, 0.1, 20);
    camera.position.set(0, 10, 0);
    camera.up.set(0, 0, -1);
    camera.lookAt(0, 0, 0);
    return camera;
}

// Objects are seen from 40 degrees above the ground, framed on one cell.
function tiltCamera(view = {}) {
    const zoom = view.zoom ?? 1;
    const half = 0.5 / zoom;
    const camera = new THREE.OrthographicCamera(-half, half, half, -half, 0.1, 30);
    const pitch = THREE.MathUtils.degToRad(view.pitch ?? 40);
    const target = new THREE.Vector3(0, view.lift ?? 0.24, 0);
    camera.position.set(0, target.y + Math.sin(pitch) * 10, Math.cos(pitch) * 10);
    camera.lookAt(target);
    return camera;
}

function shadowCatcher(opacity) {
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(4, 4),
        new THREE.ShadowMaterial({ color: 0x1e3a34, opacity }));
    plane.rotation.x = -Math.PI / 2;
    plane.receiveShadow = true;
    return plane;
}

function prepare(root) {
    root.traverse(node => {
        if (node.isMesh) {
            node.castShadow = node.userData.castShadow ?? true;
            node.receiveShadow = node.userData.receiveShadow ?? true;
        }
    });
}

function draw(scene, camera) {
    renderer.clear();
    renderer.render(scene, camera);
    const copy = document.createElement('canvas');
    copy.width = copy.height = SIZE;
    copy.getContext('2d').drawImage(canvas, 0, 0);
    return copy;
}

// The silhouette, widened in every direction and filled with ink.
function outline(source, color, width) {
    const mask = document.createElement('canvas');
    mask.width = mask.height = SIZE;
    const m = mask.getContext('2d');
    m.drawImage(source, 0, 0);
    m.globalCompositeOperation = 'source-in';
    m.fillStyle = color;
    m.fillRect(0, 0, SIZE, SIZE);
    const result = document.createElement('canvas');
    result.width = result.height = SIZE;
    const r = result.getContext('2d');
    for (let step = 0; step < 24; step += 1) {
        const angle = step / 24 * Math.PI * 2;
        r.drawImage(mask, Math.cos(angle) * width, Math.sin(angle) * width);
    }
    return result;
}

function shrink(source) {
    let current = source;
    let size = SIZE;
    while (size > OUTPUT) {
        size /= 2;
        const next = document.createElement('canvas');
        next.width = next.height = size;
        const context = next.getContext('2d');
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = 'high';
        context.drawImage(current, 0, 0, size, size);
        current = next;
    }
    return current;
}

function dispose(scene) {
    scene.traverse(node => {
        if (node.isMesh) {
            node.geometry.dispose();
            for (const material of [node.material].flat()) {
                material.map?.dispose();
                material.dispose();
            }
        }
    });
}

function staged(build) {
    const scene = new THREE.Scene();
    lights(scene);
    const model = build();
    prepare(model);
    scene.add(model);
    return { scene, model };
}

// Ground seen from above: one opaque layer.
function ground(build) {
    const { scene } = staged(build);
    const picture = draw(scene, topCamera());
    dispose(scene);
    return [picture];
}

// A standing object: its shadow, ink outline and body as separate layers.
function standing(sprite) {
    const { scene, model } = staged(sprite.build);
    const camera = tiltCamera(sprite.camera);
    const layers = [];
    if (sprite.shadow !== false) {
        // Shadow alone: the model still casts it but draws nothing.
        const catcher = shadowCatcher(sprite.shadowStrength ?? 0.34);
        scene.add(catcher);
        const hidden = [];
        model.traverse(node => {
            if (node.isMesh) {
                hidden.push([node, node.material]);
                node.material = node.material.clone();
                node.material.colorWrite = false;
                node.material.depthWrite = false;
            }
        });
        layers.push(draw(scene, camera));
        for (const [node, material] of hidden) node.material = material;
        scene.remove(catcher);
    }
    const body = draw(scene, camera);
    if (sprite.outline !== false) layers.push(outline(body, sprite.ink ?? 'rgba(24, 44, 40, 0.92)', sprite.inkWidth ?? 5));
    layers.push(body);
    dispose(scene);
    return layers;
}

// Halve repeatedly for a clean downscale to any final size.
function reduce(source, width, height) {
    let current = source;
    while (current.width > width * 1.5) {
        const next = document.createElement('canvas');
        next.width = Math.max(width, Math.round(current.width / 2));
        next.height = Math.max(height, Math.round(current.height / 2));
        const context = next.getContext('2d');
        context.imageSmoothingQuality = 'high';
        context.drawImage(current, 0, 0, next.width, next.height);
        current = next;
    }
    const final = document.createElement('canvas');
    final.width = width;
    final.height = height;
    const context = final.getContext('2d');
    context.imageSmoothingQuality = 'high';
    context.drawImage(current, 0, 0, width, height);
    return final;
}

// A whole diorama through a perspective camera, e.g. a game card.
function diorama(sprite) {
    const [width, height] = sprite.size;
    renderer.setSize(width * SCALE, height * SCALE, false);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(sprite.background);
    lights(scene, sprite.span);
    const model = sprite.build();
    prepare(model);
    scene.add(model);
    const camera = new THREE.PerspectiveCamera(sprite.camera.fov, width / height, 0.1, 100);
    camera.position.set(...sprite.camera.position);
    camera.lookAt(...sprite.camera.target);
    renderer.render(scene, camera);
    const copy = document.createElement('canvas');
    copy.width = width * SCALE;
    copy.height = height * SCALE;
    copy.getContext('2d').drawImage(canvas, 0, 0);
    dispose(scene);
    renderer.setSize(SIZE, SIZE, false);
    return reduce(copy, width, height).toDataURL('image/png').slice('data:image/png;base64,'.length);
}

function render(sprite) {
    if (sprite.view === 'scene') return diorama(sprite);
    const layers = [];
    if (sprite.base) layers.push(...ground(sprite.base));
    layers.push(...(sprite.view === 'top' ? ground(sprite.build) : standing(sprite)));
    const picture = document.createElement('canvas');
    picture.width = picture.height = SIZE;
    const context = picture.getContext('2d');
    for (const layer of layers) context.drawImage(layer, 0, 0);
    if (sprite.post) sprite.post(context, SIZE);
    return shrink(picture).toDataURL('image/png').slice('data:image/png;base64,'.length);
}

// Classic's sprites and card are pixel art from tools/pixel.
const all = [...islandSprites(), ...cards().filter(card => card.path !== 'assets/shovey/preview.png')];
const byPath = new Map(all.map(sprite => [sprite.path, sprite]));
window.sprites = {
    list: () => all.map(({ path, group, depicts }) => ({ path, group, depicts })),
    render: path => render(byPath.get(path)),
};
