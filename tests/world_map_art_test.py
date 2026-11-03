"""Verify continuous source crops, seams, native road nodes and stable graph IDs."""
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def table(source, name):
    match = re.search(r'\b'+re.escape(name)+r':\s*\[\d+\]\w+\s*=\s*\.\[(.*?)\];',source,re.S)
    assert match,name
    return [float(v) for v in re.sub(r'//[^\n]*','',''.join(match[1])).split(',') if v.strip()]


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    data=json.loads((ROOT/'assets/shovey/world-map/scenes.json').read_text())
    expected_count=max(math.ceil((source['size'][1 if orientation=='portrait' else 0]-128)/data['section_step_native_pixels'])
                       for orientation,source in data['sources'].items())
    assert data['schema']==3 and len(data['scenes'])==expected_count
    layout=(ROOT/'src/world_map_layout.zi').read_text()
    view=(ROOT/'src/world_map_view.zi').read_text()
    for orientation, expected in data['world_bounds_before_zoom'].items():
        assert f'{expected[2]}.0 * scale,{expected[3]}.0 * scale' in layout
    zoom=float(re.search(r'WorldMapWorldZoom :: ([\d.]+)',layout)[1])
    registered={e['path']:e['sha256'] for e in json.loads((ROOT/'assets/shovey/art.json').read_text())['files']}
    total=0
    for orientation,name in [('portrait','world_map_positions'),('landscape','world_map_landscape_positions')]:
        source=data['sources'][orientation];assert digest(ROOT/source['path'])==source['sha256']
        with Image.open(ROOT/source['path']) as loaded:original=np.asarray(loaded.convert('RGB'))
        quantized=np.minimum(255,((original.astype(np.uint16)+4)//8)*8).astype('uint8')
        flat=table(layout,name);nodes=list(zip(flat[::2],flat[1::2]));assert len(nodes)==175
        assert nodes==[tuple(p) for p in data['nodes'][orientation]]
        assert min(math.dist(a,b)*zoom for i,a in enumerate(nodes) for b in nodes[i+1:])>=80.1
        # Independent image test: every destination must occupy visibly paved
        # pixels in the actual joined source, not merely lie on a generated rail.
        for level,(x,y) in enumerate(nodes,1):
            x,y=round(x),round(y);patch=original[y-3:y+4,x-3:x+4].astype(np.int16)
            r,g,b=patch[:,:,0],patch[:,:,1],patch[:,:,2]
            paved=(r>165)&(g>105)&(b>55)&(r-g>4)&(g-b>12)&(r-b>40)
            assert paved.mean()>=.6,('destination off visible paving',orientation,level,x,y,float(paved.mean()))
        axis=1 if orientation=='portrait' else 0
        covered=np.zeros(original.shape[axis],dtype=bool)
        previous=None
        for scene in data['scenes']:
            asset=scene[orientation];path=ROOT/asset['path'];assert asset['path'] in view
            assert digest(path)==asset['sha256']==registered[asset['path'].removeprefix('assets/shovey/')]
            total+=path.stat().st_size
            x,y,w,h=asset['world_bounds_before_zoom'];assert max(w,h)<=2048
            with Image.open(path) as image:
                assert image.size==(w,h)==tuple(asset['size'])
                tile=np.asarray(image.convert('RGB')).astype(np.int16)
            # Lossy WebP q75 tiles: each crop must stay a faithful copy of the
            # quantized source (v5 worst tile is about 29 dB PSNR, 6 mean error).
            error=np.abs(tile-quantized[y:y+h,x:x+w].astype(np.int16)).astype(np.float64)
            psnr=10*math.log10(255**2/max((error**2).mean(),1e-9))
            assert psnr>=27 and error.mean()<=8,('source crop drifted',path,psnr,float(error.mean()))
            # Overlapping neighbours must agree, or the join shows as a line.
            if previous is not None:
                px,py,pw,ph,ptile=previous
                x0,y0,x1,y1=max(x,px),max(y,py),min(x+w,px+pw),min(y+h,py+ph)
                assert x1>x0 and y1>y0,('neighbours do not overlap',path)
                seam=np.abs(tile[y0-y:y1-y,x0-x:x1-x]-ptile[y0-py:y1-py,x0-px:x1-px]).mean()
                assert seam<=8,('seam mismatch',path,float(seam))
            previous=(x,y,w,h,tile)
            start=[x,y][axis];extent=[w,h][axis];covered[start:start+extent]=True
        assert covered.all(),('gap',orientation)
        rails=[]
        for group in range(36):
            flat=table(layout,f'world_map_rail_{orientation}{group}');rails.extend(zip(flat[::2],flat[1::2]))
        graph=table((ROOT/'src/world_map_progression.zi').read_text(),'world_map_edges')
        edges=list(zip(map(int,graph[::2]),map(int,graph[1::2])))
        assert len(edges)==176
        for i,(a,b) in enumerate(edges):
            assert math.dist(rails[i*33],nodes[a-1])<.01
            assert math.dist(rails[i*33+32],nodes[b-1])<.01
    # v5 is 37 sections long; q75 WebP tiles total about 10 MiB.
    assert total<=12*1024*1024,total
    print(f'Continuous map local test passed: source v{data["source_version"]}, {2*expected_count} faithful q75 source crops, gap-free coverage and seams, 350 paved nodes, {len(edges)} stable rails per orientation ({total//1024} KiB)')


if __name__=='__main__':main()
