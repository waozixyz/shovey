// Shared colours, materials, textures and shapes for every Shovey model.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

// Cool greens and blues grounded by earth brown, with a little light orange.
export const C = {
    mist: '#dde9e5',
    paleMist: '#eef4f1',
    sky: '#a8c8d2',
    lake: '#3f6f8f',
    jade: '#2e7d68',
    pine: '#1e4a40',
    earth: '#6e4c36',
    bark: '#8a6446',
    wood: '#a9805a',
    lightWood: '#c7a27a',
    orange: '#f2a65e',
    ink: '#1b322d',
    stone: '#9aa8a4',
    darkStone: '#6f7f7b',
    paleStone: '#c9d4d0',
    red: '#cf5643',
    blue: '#3f7cc4',
    green: '#46a05e',
    yellow: '#e9c44c',
    pink: '#d98aa6',
    lilac: '#a99ad0',
    sand: '#e6d9b2',
    wetSand: '#cdbf98',
    water: '#6aaec2',
    deepWater: '#4b8fa8',
    foam: '#eef7f5',
    grass: '#6fb27c',
    darkGrass: '#4f9466',
    leaf: '#4c9a5e',
    white: '#f6f8f4',
    gold: '#e6b84f',
    silver: '#c3cdd0',
};

export function color(value) {
    return new THREE.Color(value);
}

// Matte surfaces: nothing glossy or plastic.
export function mat(value, options = {}) {
    return new THREE.MeshStandardMaterial({
        color: color(value),
        roughness: options.rough ?? 0.78,
        metalness: options.metal ?? 0,
        emissive: options.glow ? color(options.glow) : undefined,
        emissiveIntensity: options.glowStrength ?? (options.glow ? 0.6 : 0),
        transparent: options.opacity !== undefined,
        opacity: options.opacity ?? 1,
        map: options.map,
        side: options.side ?? THREE.FrontSide,
        flatShading: options.flat ?? false,
    });
}

export function rng(seed) {
    let state = seed >>> 0;
    return () => {
        state = (state + 0x6D2B79F5) >>> 0;
        let t = state;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

// Value noise that repeats every `period` lattice cells, so a texture spread
// over one board cell joins its neighbours exactly.
export function periodicNoise(period, seed) {
    const random = rng(seed);
    const lattice = Array.from({ length: period * period }, () => random());
    const at = (x, y) => lattice[((y % period + period) % period) * period + ((x % period + period) % period)];
    const smooth = t => t * t * (3 - 2 * t);
    return (u, v) => {
        const x = u * period, y = v * period;
        const x0 = Math.floor(x), y0 = Math.floor(y);
        const fx = smooth(x - x0), fy = smooth(y - y0);
        const top = at(x0, y0) * (1 - fx) + at(x0 + 1, y0) * fx;
        const bottom = at(x0, y0 + 1) * (1 - fx) + at(x0 + 1, y0 + 1) * fx;
        return top * (1 - fy) + bottom * fy;
    };
}

// A canvas texture that repeats once per board cell.
export function cellTexture(size, paint) {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const context = canvas.getContext('2d');
    const image = context.createImageData(size, size);
    for (let y = 0; y < size; y += 1) {
        for (let x = 0; x < size; x += 1) {
            const [r, g, b] = paint(x / size, y / size);
            const at = (y * size + x) * 4;
            image.data[at] = r; image.data[at + 1] = g; image.data[at + 2] = b; image.data[at + 3] = 255;
        }
    }
    context.putImageData(image, 0, 0);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.anisotropy = 8;
    return texture;
}

function rgb(value) {
    const c = new THREE.Color(value);
    return [c.r * 255, c.g * 255, c.b * 255];
}

export function blend(a, b, t) {
    const x = rgb(a), y = rgb(b);
    return [0, 1, 2].map(i => x[i] + (y[i] - x[i]) * t);
}

// Two-tone noise texture, e.g. grains of sand or blades of grass.
export function noiseTexture(a, b, { period = 8, seed = 1, fine = 0, fineSeed = 7, finePeriod = 32 } = {}) {
    const coarse = periodicNoise(period, seed);
    const detail = periodicNoise(finePeriod, fineSeed);
    return cellTexture(256, (u, v) => {
        let t = coarse(u, v) * (1 - fine) + detail(u, v) * fine;
        return blend(a, b, Math.min(1, Math.max(0, t)));
    });
}

export function box(w, h, d, r, material) {
    const mesh = new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 4, Math.min(r, w / 2, h / 2, d / 2)), material);
    return mesh;
}

export function sphere(radius, material, segments = 48) {
    return new THREE.Mesh(new THREE.SphereGeometry(radius, segments, Math.round(segments * 0.75)), material);
}

export function cylinder(top, bottom, height, material, segments = 40) {
    return new THREE.Mesh(new THREE.CylinderGeometry(top, bottom, height, segments), material);
}

export function torus(radius, tube, material, arc = Math.PI * 2) {
    return new THREE.Mesh(new THREE.TorusGeometry(radius, tube, 24, 64, arc), material);
}

// Revolve a profile of [radius, height] points around the vertical axis.
export function lathe(points, material, segments = 48) {
    return new THREE.Mesh(new THREE.LatheGeometry(points.map(([x, y]) => new THREE.Vector2(x, y)), segments), material);
}

// A flat shape lying on the ground, raised to `depth` with soft edges.
// Shape points are in board units: x to the right, y towards the bottom.
export function slab(shape, depth, material, bevel = 0.02) {
    const geometry = new THREE.ExtrudeGeometry(shape, {
        depth, bevelEnabled: bevel > 0, bevelThickness: bevel, bevelSize: bevel,
        bevelSegments: 4, curveSegments: 48,
    });
    const mesh = new THREE.Mesh(geometry, material);
    // Shape y runs down the screen; lay it on the ground facing up.
    mesh.rotation.x = Math.PI / 2;
    mesh.position.y = depth + bevel;
    return mesh;
}

export function polygon(points) {
    const shape = new THREE.Shape();
    points.forEach(([x, y], index) => index ? shape.lineTo(x, y) : shape.moveTo(x, y));
    shape.closePath();
    return shape;
}

export function circleShape(cx, cy, r) {
    const shape = new THREE.Shape();
    shape.absarc(cx, cy, r, 0, Math.PI * 2, false);
    return shape;
}

export function roundedRectShape(x, y, w, h, r) {
    const shape = new THREE.Shape();
    shape.moveTo(x + r, y);
    shape.lineTo(x + w - r, y);
    shape.quadraticCurveTo(x + w, y, x + w, y + r);
    shape.lineTo(x + w, y + h - r);
    shape.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    shape.lineTo(x + r, y + h);
    shape.quadraticCurveTo(x, y + h, x, y + h - r);
    shape.lineTo(x, y + r);
    shape.quadraticCurveTo(x, y, x + r, y);
    return shape;
}

export function starShape(cx, cy, outer, inner, points = 5, turn = -Math.PI / 2) {
    const list = [];
    for (let i = 0; i < points * 2; i += 1) {
        const r = i % 2 ? inner : outer;
        const a = turn + i * Math.PI / points;
        list.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
    }
    return polygon(list);
}

export function group(...children) {
    const g = new THREE.Group();
    for (const child of children.flat(Infinity)) if (child) g.add(child);
    return g;
}

export function at(object, x = 0, y = 0, z = 0) {
    object.position.set(x, y, z);
    return object;
}

export function turned(object, x = 0, y = 0, z = 0) {
    object.rotation.set(x, y, z);
    return object;
}

export function scaled(object, x, y = x, z = x) {
    object.scale.set(x, y, z);
    return object;
}

// A plane on the ground showing a cell texture; used under terrain shapes.
export function ground(material, y = 0) {
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), material);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = y;
    mesh.userData.castShadow = false;
    return mesh;
}

// Texture coordinates follow board position, so patterns continue across cells.
export function worldUV(geometry) {
    const position = geometry.attributes.position;
    const uv = new Float32Array(position.count * 2);
    for (let i = 0; i < position.count; i += 1) {
        uv[i * 2] = position.getX(i) + 0.5;
        uv[i * 2 + 1] = position.getY(i) + 0.5;
    }
    geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    return geometry;
}

export { THREE };
