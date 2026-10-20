// The old model remains for the unused 3D Classic scene. Island and its
// card use the same preserved bitmap player as the playable Classic game.
import { THREE, C, mat, sphere, cylinder, group, at, turned, scaled } from './kit.js';

const playerTextures = new Map();
export const playerTexturesReady = Promise.all(['up', 'right', 'down', 'left'].map(async direction => {
    const texture = await new THREE.TextureLoader().loadAsync(`/classic-player/player-${direction}.png`);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.magFilter = texture.minFilter = THREE.NearestFilter;
    texture.generateMipmaps = false;
    playerTextures.set(direction, texture);
}));

export function classicPlayer(direction = 'up') {
    const picture = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.9),
        new THREE.MeshBasicMaterial({ map: playerTextures.get(direction), transparent: true,
            alphaTest: 0.01, side: THREE.DoubleSide, toneMapped: false }));
    picture.rotation.x = -Math.PI / 2;
    picture.position.y = 0.12;
    return picture;
}

const LOOK = {
    up: { yaw: 0, eyeY: 0.12, pupil: [0, 0.035], lean: -0.18 },
    down: { yaw: 0, eyeY: 0.02, pupil: [0, -0.03], lean: 0.16 },
    left: { yaw: -0.5, eyeY: 0.07, pupil: [-0.035, 0], lean: 0 },
    right: { yaw: 0.5, eyeY: 0.07, pupil: [0.035, 0], lean: 0 },
};

function leaf(material, length, width) {
    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    shape.quadraticCurveTo(width, length * 0.45, 0, length);
    shape.quadraticCurveTo(-width, length * 0.45, 0, 0);
    const geometry = new THREE.ExtrudeGeometry(shape, { depth: 0.012, bevelEnabled: true,
        bevelThickness: 0.006, bevelSize: 0.006, bevelSegments: 2, curveSegments: 16 });
    geometry.translate(0, 0, -0.006);
    return new THREE.Mesh(geometry, material);
}

function eye(white, dark, pupil) {
    const ball = scaled(sphere(0.075, white), 1, 1.12, 0.62);
    const iris = at(scaled(sphere(0.042, dark), 1, 1.1, 0.5), pupil[0], pupil[1], 0.04);
    const shine = at(sphere(0.013, mat(C.white, { glow: C.white, glowStrength: 0.4 })), pupil[0] - 0.014, pupil[1] + 0.02, 0.06);
    return group(ball, iris, shine);
}

export function shovey(direction = 'down', body = C.jade, options = {}) {
    const look = LOOK[direction];
    const skin = mat(body, { rough: 0.7, opacity: options.opacity });
    const belly = mat(options.belly ?? '#cfe6dc', { rough: 0.8, opacity: options.opacity });
    const white = mat(C.white, { rough: 0.5 });
    const dark = mat(C.ink, { rough: 0.45 });
    const cheekMaterial = mat(C.orange, { rough: 0.9, opacity: 0.85 });
    const stem = mat(C.earth);
    const sprout = mat(options.leaf ?? '#7cc46f', { side: THREE.DoubleSide });

    const torso = scaled(sphere(0.3, skin), 1, 0.9, 0.95);
    const tummy = at(scaled(sphere(0.2, belly), 1, 0.85, 0.5), 0, -0.07, 0.17);
    const feet = [-0.12, 0.12].map(x => at(scaled(sphere(0.075, mat(C.pine)), 1.2, 0.7, 1.3), x, -0.25, 0.08));
    const eyes = [-0.095, 0.095].map(x => at(eye(white, dark, look.pupil), x, look.eyeY, 0.235));
    const cheeks = [-0.17, 0.17].map(x => at(scaled(sphere(0.04, cheekMaterial), 1.3, 0.8, 0.4), x, look.eyeY - 0.085, 0.22));
    const head = group(torso, tummy, eyes, cheeks);
    const top = group(
        at(cylinder(0.012, 0.016, 0.1, stem), 0, 0.05, 0),
        at(turned(leaf(sprout, 0.16, 0.08), 0, 0.3, -0.9), 0.005, 0.09, 0),
        at(turned(leaf(sprout, 0.13, 0.065), 0, -0.3, 0.95), -0.005, 0.09, 0),
    );
    top.position.y = 0.25;
    top.rotation.x = look.lean;
    const character = group(head, top, feet);
    character.rotation.y = look.yaw;
    if (options.sparks) {
        // Small sparks around a charged Shovey.
        const spark = mat(options.sparks, { glow: options.sparks, glowStrength: 0.9 });
        for (const [x, y, z] of [[-0.33, 0.2, 0.05], [0.34, 0.12, 0.02], [0.27, 0.34, -0.05]]) {
            const flash = new THREE.Mesh(new THREE.OctahedronGeometry(0.05), spark);
            flash.position.set(x, y, z);
            flash.scale.set(0.6, 1.4, 0.6);
            character.add(flash);
        }
    }
    character.position.y = 0.3;
    return character;
}
