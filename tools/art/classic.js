// Shovey Classic: a quiet stone courtyard with hedge-green walls.
import { THREE, C, mat, box, sphere, cylinder, torus, lathe, slab, polygon, circleShape,
    roundedRectShape, starShape, group, at, turned, scaled, ground } from './kit.js';
import { shovey } from './shovey.js';

const PALETTE = {
    red: C.red,
    blue: C.blue,
    green: C.green,
    yellow: C.yellow,
};

// ---------------------------------------------------------------- ground

// Grey courtyard stone like the original Classic: one flat, pale floor tone
// and raised blocks a shade darker, so balls, crates and Shovey stand out.
const FLOOR_TONE = '#e4e6e5';

// One paving stone per cell on a joint barely darker than the stone; its
// top is FLOOR above ground.
const FLOOR = 0.066;
const JOINT = '#d0d3d2';

function stone(shape) {
    return slab(shape, 0.03, mat(FLOOR_TONE, { rough: 0.9 }), 0.018);
}

export function floor() {
    return group(ground(mat(JOINT)), stone(roundedRectShape(-0.475, -0.475, 0.95, 0.95, 0.07)));
}

// A flat piece lying on the paving stone, `height` above its surface.
function onStone(mesh, height = 0) {
    mesh.position.y += FLOOR + height;
    return mesh;
}

function wall() {
    const joint = ground(mat('#9aa09e'));
    const block = box(0.97, 0.36, 0.97, 0.12, mat('#c0c5c3', { rough: 0.85 }));
    block.position.y = 0.18;
    return group(joint, block);
}

// A square pit sunk deep into the paving stone and lined with the colour of
// the ball it takes. The rim throws a shadow inside, so it reads as a hole.
function hole(tone) {
    return () => {
        const mouth = 0.36, base = 0.24, bottom = -0.26;
        const opening = () => roundedRectShape(-mouth, -mouth, mouth * 2, mouth * 2, 0.03);
        const shape = roundedRectShape(-0.475, -0.475, 0.95, 0.95, 0.07);
        shape.holes.push(opening());
        const cell = roundedRectShape(-0.5, -0.5, 1, 1, 0);
        cell.holes.push(opening());
        const joint = slab(cell, 0.002, mat(JOINT), 0);
        const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
        const points = [];
        for (let side = 0; side < 4; side += 1) {
            const [ax, az] = corners[side], [bx, bz] = corners[(side + 1) % 4];
            points.push(ax * mouth, FLOOR, az * mouth, bx * base, bottom, bz * base, bx * mouth, FLOOR, bz * mouth,
                ax * mouth, FLOOR, az * mouth, ax * base, bottom, az * base, bx * base, bottom, bz * base);
        }
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
        geometry.computeVertexNormals();
        const sides = new THREE.Mesh(geometry, mat(tone, { rough: 0.9, side: THREE.DoubleSide }));
        const floorColor = new THREE.Color(tone).lerp(new THREE.Color(C.ink), 0.72);
        const pitFloor = at(new THREE.Mesh(new THREE.PlaneGeometry(base * 2, base * 2), mat(floorColor, { rough: 1 })), 0, bottom, 0);
        pitFloor.rotation.x = -Math.PI / 2;
        return group(joint, stone(shape), sides, pitFloor);
    };
}

function marking(shape, tone, height = 0) {
    return onStone(slab(shape, 0.004, mat(tone, { rough: 0.9 }), 0.006), height);
}

// Four corner brackets: where a crate belongs.
function crateGoal() {
    const parts = [marking(roundedRectShape(-0.3, -0.3, 0.6, 0.6, 0.05), '#d4c3a6')];
    for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
        const x = sx * 0.36, y = sy * 0.36;
        const arm = 0.17, width = 0.06;
        parts.push(marking(polygon([
            [x, y], [x - sx * arm, y], [x - sx * arm, y - sy * width],
            [x - sx * width, y - sy * width], [x - sx * width, y - sy * arm], [x, y - sy * arm],
        ]), C.earth, 0.004));
    }
    return group(floor(), parts);
}

// Hatched square: where a coloured block belongs.
function cycleGoal() {
    const parts = [marking(roundedRectShape(-0.36, -0.36, 0.72, 0.72, 0.06), '#ecc3b6')];
    for (let i = -1; i <= 1; i += 1) {
        const o = i * 0.17;
        parts.push(marking(polygon([[o - 0.15, 0.27], [o - 0.07, 0.27], [o + 0.15, -0.27], [o + 0.07, -0.27]]), C.red, 0.004));
    }
    return group(floor(), parts);
}

function plate() {
    const ring = onStone(slab(circleShape(0, 0, 0.34), 0.008, mat('#8fa69f'), 0.012));
    const button = onStone(slab(circleShape(0, 0, 0.25), 0.03, mat(C.orange, { rough: 0.7 }), 0.025), 0.01);
    return group(floor(), ring, button);
}

function portal() {
    const parts = [onStone(slab(circleShape(0, 0, 0.41), 0.01, mat('#6f8f8a'), 0.014))];
    const tones = ['#2d6a87', '#4f93ad', '#7fc0cf', '#cfeef3'];
    tones.forEach((tone, i) => {
        parts.push(onStone(slab(circleShape(0, 0, 0.34 - i * 0.08), 0.004,
            mat(tone, { glow: tone, glowStrength: 0.2 + i * 0.15 }), 0.006), 0.04 + i * 0.004));
    });
    return group(floor(), parts);
}

function dots(count, radius, tone, size, glow) {
    const parts = [];
    for (let i = 0; i < count; i += 1) {
        const a = i / count * Math.PI * 2;
        parts.push(onStone(slab(circleShape(Math.cos(a) * radius, Math.sin(a) * radius, size), 0.006,
            mat(tone, { glow: glow ? tone : undefined, glowStrength: 0.35 }), 0.01)));
    }
    return parts;
}

function sensor(angle, active) {
    return () => {
        const ring = onStone(slab(circleShape(0, 0, 0.33), 0.006, mat(active ? '#7fb3c2' : '#aab9b5'), 0.012));
        const hollow = onStone(slab(circleShape(0, 0, 0.21), 0.006, mat(active ? '#d9eef2' : '#e2eae7'), 0.008), 0.008);
        const tone = active ? C.orange : '#7d8b87';
        const marker = onStone(slab(circleShape(Math.cos(angle) * 0.27, Math.sin(angle) * 0.27, 0.06), 0.01,
            mat(tone, { glow: active ? tone : undefined, glowStrength: 0.6 }), 0.012), 0.008);
        return group(floor(), ring, hollow, marker);
    };
}

function closedSensor() {
    const block = at(box(0.8, 0.22, 0.8, 0.09, mat('#7d9c94')), 0, 0.11 + FLOOR, 0);
    const light = at(cylinder(0.11, 0.11, 0.03, mat(C.red, { glow: C.red, glowStrength: 0.7 })), 0, 0.23 + FLOOR, 0);
    return group(block, light);
}

// A ribbon of small stepping marks left behind.
function trail() {
    const parts = [marking(circleShape(0, 0, 0.4), '#d6cfec')];
    for (let i = 0; i < 5; i += 1) {
        const t = i / 4;
        const x = -0.28 + t * 0.56, y = Math.sin(t * Math.PI * 1.5) * 0.16;
        parts.push(marking(circleShape(x, y, 0.06 - Math.abs(t - 0.5) * 0.03), C.lilac, 0.004));
    }
    return group(floor(), parts);
}

function path(fresh) {
    return () => group(floor(), dots(10, 0.28, fresh ? C.lake : '#9aa8a4', 0.045, fresh));
}

// ---------------------------------------------------------------- objects

function ball(tone) {
    return () => {
        const body = sphere(0.3, mat(tone, { rough: 0.6 }));
        const seam = torus(0.296, 0.012, mat(new THREE.Color(tone).multiplyScalar(0.62).getStyle(), { rough: 0.7 }));
        seam.rotation.set(1.1, 0.3, 0.2);
        return at(group(body, seam), 0, 0.3, 0);
    };
}

function crate() {
    const wood = mat(C.wood, { rough: 0.85 });
    const dark = mat(C.bark, { rough: 0.85 });
    const parts = [at(box(0.74, 0.62, 0.74, 0.05, wood), 0, 0.31, 0)];
    for (const side of [-1, 1]) {
        parts.push(at(box(0.78, 0.09, 0.78, 0.03, dark), 0, 0.31 + side * 0.25, 0));
    }
    parts.push(at(turned(box(0.08, 0.66, 0.02, 0.01, dark), 0, 0, 0.78), 0, 0.31, 0.375));
    parts.push(at(turned(box(0.08, 0.66, 0.02, 0.01, dark), 0, 0, -0.78), 0, 0.31, 0.375));
    return group(parts);
}

function paint(tone) {
    return () => {
        const shape = new THREE.Shape();
        const lobes = [0.3, 0.24, 0.33, 0.22, 0.29, 0.25, 0.31, 0.21];
        lobes.forEach((r, i) => {
            const a = i / lobes.length * Math.PI * 2;
            const b = (i + 0.5) / lobes.length * Math.PI * 2;
            const x = Math.cos(a) * r, y = Math.sin(a) * r;
            const mx = Math.cos(b) * (r * 0.8), my = Math.sin(b) * (r * 0.8);
            if (i === 0) shape.moveTo(x, y);
            const next = lobes[(i + 1) % lobes.length];
            const nb = (i + 1) / lobes.length * Math.PI * 2;
            shape.quadraticCurveTo(mx * 1.25, my * 1.25, Math.cos(nb) * next, Math.sin(nb) * next);
        });
        const puddle = slab(shape, 0.03, mat(tone, { rough: 0.5 }), 0.03);
        const drops = [[0.38, -0.2, 0.05], [-0.36, 0.25, 0.04], [0.2, 0.37, 0.035]].map(([x, y, r]) =>
            slab(circleShape(x, y, r), 0.02, mat(tone, { rough: 0.5 }), 0.02));
        const shine = slab(circleShape(-0.08, -0.08, 0.07), 0.01, mat('#ffffff', { opacity: 0.35 }), 0.01);
        shine.position.y = 0.075;
        return group(puddle, drops, shine);
    };
}

function star() {
    const body = slab(starShape(0, 0, 0.36, 0.17), 0.12, mat(C.yellow, { rough: 0.6 }), 0.07);
    body.rotation.x = Math.PI;
    body.position.set(0, 0.38, 0.0);
    return group(body);
}

function apple() {
    const fruit = lathe([[0, 0.02], [0.17, 0.05], [0.27, 0.18], [0.27, 0.32], [0.2, 0.45], [0.06, 0.46], [0, 0.42]],
        mat('#c85a43', { rough: 0.6 }));
    const stem = at(turned(cylinder(0.015, 0.02, 0.12, mat(C.earth)), 0, 0, 0.2), 0.01, 0.5, 0);
    const leafShape = new THREE.Shape();
    leafShape.moveTo(0, 0);
    leafShape.quadraticCurveTo(0.08, 0.06, 0.18, 0);
    leafShape.quadraticCurveTo(0.08, -0.06, 0, 0);
    const leaf = new THREE.Mesh(new THREE.ExtrudeGeometry(leafShape, { depth: 0.01, bevelEnabled: false }),
        mat(C.leaf, { side: THREE.DoubleSide }));
    leaf.position.set(0.02, 0.52, 0);
    leaf.rotation.set(0.3, -0.4, 0.4);
    const blush = at(scaled(sphere(0.12, mat('#e07b52', { opacity: 0.5 })), 1, 1.1, 0.5), -0.08, 0.27, 0.19);
    return group(fruit, stem, leaf, blush);
}

function token(face, rim = '#e9efe9') {
    const disc = at(cylinder(0.3, 0.32, 0.08, mat(rim)), 0, 0.04, 0);
    const top = face();
    top.position.y = 0.085;
    return group(disc, top);
}

function arrowShape(length, width, head) {
    return polygon([[-length / 2, -width / 2], [length / 2 - head, -width / 2], [length / 2 - head, -width * 1.6],
        [length / 2, 0], [length / 2 - head, width * 1.6], [length / 2 - head, width / 2], [-length / 2, width / 2]]);
}

function reverse() {
    return token(() => {
        const a = slab(arrowShape(0.42, 0.07, 0.13), 0.03, mat(C.lake), 0.012);
        a.position.z = -0.08;
        const b = slab(arrowShape(0.42, 0.07, 0.13), 0.03, mat(C.lake), 0.012);
        b.rotation.z = Math.PI;
        b.rotation.x = -Math.PI / 2;
        b.position.z = 0.08;
        b.position.y = 0.05;
        return group(a, b);
    });
}

function ammo() {
    const iron = mat('#4a5553', { rough: 0.55, metal: 0.2 });
    return at(sphere(0.2, iron), 0, 0.2, 0);
}

function bolt() {
    return token(() => slab(polygon([[0.04, -0.3], [-0.16, 0.04], [-0.01, 0.04], [-0.06, 0.3], [0.16, -0.06], [0.01, -0.06], [0.08, -0.3]]),
        0.03, mat(C.yellow, { glow: '#f4d670', glowStrength: 0.4 }), 0.015), '#e3ebe7');
}

function target() {
    const tones = ['#f3f0e6', C.red, '#f3f0e6', C.red];
    const parts = [at(cylinder(0.04, 0.05, 0.36, mat(C.bark)), 0, 0.18, -0.05)];
    tones.forEach((tone, i) => {
        const ring = cylinder(0.3 - i * 0.07, 0.3 - i * 0.07, 0.06 + i * 0.012, mat(tone));
        ring.rotation.x = Math.PI / 2 - 0.25;
        ring.position.set(0, 0.36, 0.04 + i * 0.006);
        parts.push(ring);
    });
    return group(parts);
}

function puck(core, glow) {
    return () => {
        const stone = at(cylinder(0.32, 0.36, 0.2, mat('#7d8f8b')), 0, 0.1, 0);
        const light = at(cylinder(0.22, 0.24, 0.05, mat(core, { glow, glowStrength: 0.9 })), 0, 0.215, 0);
        return group(stone, light);
    };
}

function key() {
    const brass = mat(C.gold, { rough: 0.5 });
    const ring = at(turned(torus(0.12, 0.045, brass), Math.PI / 2 - 0.5, 0, 0), -0.18, 0.1, 0);
    const shaft = at(turned(cylinder(0.035, 0.035, 0.44, brass), 0, 0, Math.PI / 2), 0.1, 0.1, 0);
    const teeth = [0.2, 0.3].map(x => at(box(0.05, 0.05, 0.12, 0.01, brass), x, 0.1, 0.07));
    return group(ring, shaft, teeth);
}

function lock() {
    const body = at(box(0.56, 0.44, 0.24, 0.07, mat(C.gold, { rough: 0.55 })), 0, 0.24, 0);
    const shackle = at(torus(0.17, 0.045, mat(C.silver, { rough: 0.4, metal: 0.5 }), Math.PI), 0, 0.46, 0);
    const hole = at(cylinder(0.05, 0.05, 0.02, mat(C.ink)), 0, 0.27, 0.125);
    hole.rotation.x = Math.PI / 2;
    const slot = at(box(0.035, 0.1, 0.02, 0.01, mat(C.ink)), 0, 0.21, 0.125);
    return group(body, shackle, hole, slot);
}

function slide() {
    return token(() => {
        const parts = [];
        for (let i = 0; i < 3; i += 1) {
            const arm = slab(polygon([[-0.03, -0.26], [0.03, -0.26], [0.03, 0.26], [-0.03, 0.26]]), 0.025, mat('#7fc0cf'), 0.01);
            arm.rotation.z = i * Math.PI / 3;
            arm.rotation.x = Math.PI / 2;
            parts.push(arm);
        }
        const tip = slab(circleShape(0, 0, 0.07), 0.03, mat('#d6eef3', { glow: '#bfe3ea', glowStrength: 0.4 }), 0.012);
        tip.position.y = 0.05;
        return group(parts, tip);
    }, '#e8f0f2');
}

function cycleBlock(tone) {
    return () => {
        const cube = at(box(0.7, 0.6, 0.7, 0.1, mat('#a9b7b2')), 0, 0.3, 0);
        const face = at(box(0.5, 0.4, 0.04, 0.05, mat(tone)), 0, 0.3, 0.35);
        const top = at(box(0.5, 0.04, 0.5, 0.05, mat(tone)), 0, 0.6, 0);
        return group(cube, face, top);
    };
}

function cottage() {
    const wall = mat('#e8dcc4');
    const roof = mat(C.jade, { rough: 0.85 });
    const parts = [at(box(0.62, 0.36, 0.46, 0.04, wall), 0, 0.18, 0)];
    const gable = new THREE.Shape();
    gable.moveTo(-0.4, 0);
    gable.lineTo(0.4, 0);
    gable.lineTo(0, 0.3);
    gable.closePath();
    const prism = new THREE.Mesh(new THREE.ExtrudeGeometry(gable, { depth: 0.54, bevelEnabled: true,
        bevelThickness: 0.02, bevelSize: 0.02, bevelSegments: 3 }), roof);
    // Ridge runs left to right: the gable faces the viewer.
    prism.position.set(0, 0.35, -0.27);
    parts.push(prism);
    parts.push(at(box(0.16, 0.24, 0.03, 0.03, mat(C.orange, { glow: C.orange, glowStrength: 0.35 })), 0, 0.12, 0.235));
    parts.push(at(box(0.1, 0.1, 0.03, 0.02, mat('#bfe3ea')), -0.2, 0.22, 0.235));
    parts.push(at(box(0.1, 0.1, 0.03, 0.02, mat('#bfe3ea')), 0.2, 0.22, 0.235));
    parts.push(at(box(0.07, 0.18, 0.07, 0.02, mat(C.earth)), 0.2, 0.6, -0.1));
    return group(parts);
}

function gate(open) {
    return () => {
        const frame = mat('#6f7f7b');
        const wood = mat(C.bark, { rough: 0.85 });
        const parts = [
            at(box(0.12, 0.5, 0.2, 0.03, frame), -0.42, 0.25, 0),
            at(box(0.12, 0.5, 0.2, 0.03, frame), 0.42, 0.25, 0),
        ];
        if (open) {
            parts.push(at(box(0.72, 0.03, 0.2, 0.01, mat('#2c3a37')), 0, 0.015, 0));
        } else {
            for (let i = 0; i < 5; i += 1) {
                parts.push(at(box(0.1, 0.46, 0.08, 0.03, wood), -0.28 + i * 0.14, 0.23, 0));
            }
            parts.push(at(box(0.78, 0.07, 0.1, 0.02, frame), 0, 0.36, 0.02));
            parts.push(at(box(0.78, 0.07, 0.1, 0.02, frame), 0, 0.12, 0.02));
        }
        return group(parts);
    };
}

function projectile() {
    return at(sphere(0.12, mat('#4a5553', { rough: 0.5, metal: 0.2 })), 0, 0.2, 0);
}

// ---------------------------------------------------------------- list

function sprite(name, depicts, build, extra = {}) {
    return { path: `assets/shovey/sprites/${name}.png`, group: 'classic', depicts, build, ...extra };
}

const top = (name, depicts, build) => sprite(name, depicts, build, { view: 'top' });
const object = (name, depicts, build, extra) => sprite(name, depicts, build, { view: 'tilt', ...extra });
const standingOnFloor = (name, depicts, build, extra) => sprite(name, depicts, build, { view: 'tilt', base: floor, ...extra });

// Characters face the viewer from a lower angle.
export const FACE = { camera: { pitch: 24, lift: 0.3 } };

export function classicSprites() {
    const list = [
        top('tile-0', 'floor: a pale grey paving stone', floor),
        object('tile-1', 'red ball (pushable)', ball(PALETTE.red)),
        object('tile-2', 'blue ball (pushable)', ball(PALETTE.blue)),
        object('tile-3', 'green ball (pushable)', ball(PALETTE.green)),
        top('tile-4', 'red pit: takes the red ball', hole(PALETTE.red)),
        top('tile-5', 'blue pit: takes the blue ball', hole(PALETTE.blue)),
        top('tile-6', 'green pit: takes the green ball', hole(PALETTE.green)),
        standingOnFloor('tile-7', 'home: a small cabin with a jade roof and a lit door', cottage, { camera: { lift: 0.25 } }),
        top('tile-8', 'teleporter: a stone pad with blue rings', portal),
        object('tile-9', 'crate (pushable)', crate),
        top('tile-10', 'start position, drawn as floor', floor),
        top('tile-11', 'trail field: a ribbon of lilac marks', trail),
        top('tile-12', 'wall: a raised grey stone block', wall),
        top('tile-13', 'pressure plate: a round orange button', plate),
        standingOnFloor('tile-14', 'closed gate: wooden bars in a stone frame', gate(false)),
        object('tile-15', 'red paint puddle', paint(PALETTE.red), { outline: false, shadow: false, camera: { lift: 0 } }),
        object('tile-16', 'blue paint puddle', paint(PALETTE.blue), { outline: false, shadow: false, camera: { lift: 0 } }),
        object('tile-17', 'green paint puddle', paint(PALETTE.green), { outline: false, shadow: false, camera: { lift: 0 } }),
        top('tile-18', 'crate goal: four corner brackets', crateGoal),
        object('tile-19', 'star block: a chunky yellow star (pushable)', star),
        top('tile-20', 'sensor not yet visited', sensor(-Math.PI / 2, false)),
        object('tile-21', 'apple', apple),
        top('tile-22', 'active sensor', sensor(-Math.PI / 2, true)),
        standingOnFloor('tile-23', 'closed sensor: a raised block with a red light', closedSensor),
        top('tile-24', 'active sensor', sensor(-Math.PI / 2, true)),
        object('tile-25', 'reverse controls: a token with two opposite arrows', reverse),
        object('tile-26', 'ammunition: one iron shot', ammo),
        object('tile-27', 'charge: a token with a lightning bolt', bolt),
        object('tile-28', 'target: a red and white target board (pushable)', target),
        object('tile-29', 'moving block: a stone puck with a blue light', puck('#9fd6e2', '#7fc0cf')),
        top('tile-30', 'fresh path: a ring of blue dots', path(true)),
        top('tile-31', 'used path: a ring of grey dots', path(false)),
        object('tile-32', 'moving block stopping: its light turns red', puck('#f08a76', C.red)),
        object('tile-33', 'key', key),
        object('tile-34', 'lock: a padlock', lock),
        object('tile-35', 'slide power: a token with an ice crystal', slide),
        object('tile-36', 'red colour block (pushable)', cycleBlock(PALETTE.red)),
        object('tile-37', 'blue colour block (pushable)', cycleBlock(PALETTE.blue)),
        object('tile-38', 'yellow colour block (pushable)', cycleBlock(PALETTE.yellow)),
        top('tile-39', 'colour block goal: a red hatched square', cycleGoal),
        object('tile-40', 'mirror Shovey (pink)', () => shovey('up', C.pink, { belly: '#f1d3dc', leaf: '#b6a6d9' }), FACE),
    ];
    for (const direction of ['up', 'right', 'down', 'left']) {
        list.push(object(`player-${direction}`, `Shovey looking ${direction}`, () => shovey(direction), FACE));
    }
    for (const direction of ['up', 'right', 'down', 'left']) {
        list.push(object(`charged-${direction}`, `charged Shovey looking ${direction}`,
            () => shovey(direction, '#d9b13c', { belly: '#f5e7b6', sparks: C.yellow }), FACE));
    }
    list.push(object('shadow', 'mirror Shovey (pink)', () => shovey('up', C.pink, { belly: '#f1d3dc', leaf: '#b6a6d9' }), FACE));
    list.push(standingOnFloor('door-open', 'open gate: bars lowered into the floor', gate(true)));
    for (let frame = 1; frame <= 8; frame += 1) {
        list.push(top(`sensor-${frame}`, `active sensor, frame ${frame} of 8`,
            sensor(-Math.PI / 2 + (frame - 1) * Math.PI / 4, true)));
    }
    list.push(object('projectile', 'a flying iron shot', projectile, { shadow: false }));
    return list;
}
