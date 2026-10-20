// The cards that represent each edition in a game library: small dioramas
// built from the same models as the sprites.
import { THREE, group } from './kit.js';
import { classicSprites } from './classic.js';
import { islandSprites } from './island.js';

function place(build, x, z, columns, rows) {
    const model = build();
    model.position.x += x - (columns - 1) / 2;
    model.position.z += z - (rows - 1) / 2;
    return model;
}

function classic() {
    const sprites = new Map(classicSprites().map(sprite => [sprite.path.split('/').pop().slice(0, -4), sprite]));
    const tile = name => sprites.get(name).build;
    const layout = [
        'w w w w w w w',
        'f c f f f f f',
        'f p b f h f f',
        'f f f f f f f',
        'f f f f f f f',
    ].map(row => row.split(' '));
    const parts = [];
    layout.forEach((row, z) => row.forEach((cell, x) => {
        parts.push(place(tile(cell === 'w' ? 'tile-12' : cell === 'h' ? 'tile-4' : 'tile-0'), x, z, 7, 5));
        if (cell === 'c') parts.push(place(tile('tile-9'), x, z, 7, 5));
        if (cell === 'p') parts.push(place(tile('player-right'), x, z, 7, 5));
        if (cell === 'b') parts.push(place(tile('tile-1'), x, z, 7, 5));
    }));
    parts.push(place(tile('tile-7'), 5, 1, 7, 5));
    return group(parts);
}

function island() {
    const sprites = new Map(islandSprites().map(sprite => [sprite.path.replace('assets/shovey-island/', ''), sprite]));
    const tile = id => sprites.get(`tiles/${id}.png`).build;
    const terrain = [
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 2, 8, 8, 8, 8, 3, 0, 0],
        [0, 0, 12, 14, 20, 15, 1, 9, 0, 0],
        [0, 0, 12, 17, 22, 16, 1, 9, 0, 0],
        [0, 0, 5, 11, 11, 11, 11, 4, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ];
    const parts = [];
    terrain.forEach((row, z) => row.forEach((id, x) => parts.push(place(tile(id), x, z, 10, 8))));
    parts.push(place(tile(51), 3, 3, 10, 8));
    parts.push(place(tile(55), 7, 4, 10, 8));
    parts.push(place(tile(75), 6, 3, 10, 8));
    parts.push(place(tile(70), 4, 3, 10, 8));
    parts.push(place(sprites.get('player/1.png').build, 6, 4, 10, 8));
    parts.push(place(tile(66), 3, 5, 10, 8));
    return group(parts);
}

export function cards() {
    return [
        { path: 'assets/shovey/preview.png', group: 'cards', view: 'scene', depicts: 'Shovey Classic card: Shovey pushes a red ball towards its hole in a stone courtyard',
            size: [480, 288], background: '#dde9e5', span: 5, build: classic,
            camera: { fov: 30, position: [0, 5.6, 4.6], target: [0, 0, -0.3] } },
        { path: 'assets/shovey-island/preview.png', group: 'cards', view: 'scene', depicts: 'Shovey Island card: Shovey beside a round hut on a small island',
            size: [480, 288], background: '#8ccbd8', span: 5, build: island,
            camera: { fov: 30, position: [0, 5.6, 5.0], target: [0, 0, 0.2] } },
    ];
}
