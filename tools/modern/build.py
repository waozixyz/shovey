#!/usr/bin/env python3
"""Build modern sprite derivatives, one deduplicated atlas and before/after art.
The generated provider masters and original sheet are preserved in source/.
"""
from pathlib import Path
import colorsys, hashlib, json, math, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
from make_shop_art import SKIN_RAMPS
from wall_tiles import WALL_KINDS, WALL_MASKS, wall_name, pit_floor

SIZE=64
FACINGS={'up':0,'right':-90,'down':180,'left':90}
NAMES=json.loads((HERE/'source/original.json').read_text())
CLASSIC_RAMP = ((15, 65, 26), (52, 185, 48), (157, 241, 111))

def blank(): return Image.new('RGBA',(SIZE,SIZE))
def crop_sheet(file,cols,rows):
    from scipy import ndimage
    im=Image.open(HERE/'source'/file).convert('RGBA')
    a=np.array(clean_cutout(im))
    # Generated shapes can cross an ideal grid boundary. Assign complete
    # connected silhouettes by their center, rather than clipping a neighbor's
    # tail into the apple/crystal cell. Keep multi-part goals and bee swarms.
    isolated_from = 0 if file != 'terrain.png' else 20
    mask=a[...,3]>=64
    if isolated_from:
        for i in range(isolated_from):
            x,y=i%cols,i//cols
            mask[round(y*im.height/rows):round((y+1)*im.height/rows),
                 round(x*im.width/cols):round((x+1)*im.width/cols)]=False
    labels,count=ndimage.label(mask,structure=np.ones((3,3)))
    boxes=ndimage.find_objects(labels)
    areas=np.bincount(labels.ravel())
    groups={i:[] for i in range(isolated_from,cols*rows)}
    for n,box in enumerate(boxes,1):
        if box is None or areas[n]<8:continue
        yy,xx=box
        x=min(cols-1,int((xx.start+xx.stop)/2/im.width*cols))
        y=min(rows-1,int((yy.start+yy.stop)/2/im.height*rows))
        index=y*cols+x
        if index in groups:groups[index].append(n)
    out=[]
    for i in range(cols*rows):
        x,y=i%cols,i//cols
        if i<isolated_from:
            out.append(im.crop((round(x*im.width/cols),round(y*im.height/rows),round((x+1)*im.width/cols),round((y+1)*im.height/rows))))
            continue
        members=groups[i]
        assert members,(file,i,'missing silhouette')
        x0=min(boxes[n-1][1].start for n in members);x1=max(boxes[n-1][1].stop for n in members)
        y0=min(boxes[n-1][0].start for n in members);y1=max(boxes[n-1][0].stop for n in members)
        cell=a[y0:y1,x0:x1].copy()
        cell[~np.isin(labels[y0:y1,x0:x1],members)]=0
        out.append(Image.fromarray(cell))
    return out

def fit(im,fill=0.87):
    box=im.getchannel('A').point(lambda a:255 if a>64 else 0).getbbox()
    assert box
    im=im.crop(box); im.thumbnail((round(SIZE*fill),round(SIZE*fill)),Image.Resampling.LANCZOS)
    out=blank();out.alpha_composite(im,((SIZE-im.width)//2,(SIZE-im.height)//2));return out

def hue(im,degrees):
    a=np.array(im); rgb=a[...,:3].astype(float)/255
    import matplotlib.colors as col
    hsv=col.rgb_to_hsv(rgb); mask=hsv[...,1]>.22
    hsv[...,0][mask]=(hsv[...,0][mask]+degrees/360)%1
    a[...,:3]=np.round(col.hsv_to_rgb(hsv)*255).astype('uint8');return Image.fromarray(a)

def overhead_blob(ramp):
    # Match the original's round body and the two eyes at its leading edge.
    scale = 4
    side = SIZE * scale
    y, x = np.mgrid[:side, :side] / scale + .5 / scale
    x, y = (x - 32) / 27, (y - 32) / 27
    radius = np.hypot(x, y)
    dome = np.sqrt(np.maximum(1 - radius**2, 0))
    light = .32 + .27 * dome - .13 * x - .17 * y
    gleam = .31 * np.exp(-((x + .34)**2 / .115 + (y + .49)**2 / .048))
    rim = .10 * np.exp(-((radius - .88) / .04)**2) * np.maximum(y, 0)
    colors = np.stack([np.interp(light + gleam + rim, (0, .57, 1), tones)
                       for tones in zip(*ramp)], axis=-1)
    colors[radius > .945] = np.array(ramp[0]) * .65
    body = Image.fromarray(np.dstack((colors, 255 * (radius <= 1))).astype('uint8'))
    eyes = Image.new('RGBA', body.size)
    draw = ImageDraw.Draw(eyes)
    for cx in (25, 39):
        for box, color in (((cx - 4.8, 6.5, cx + 4.8, 15.6), '#181f25'),
                           ((cx - 3.4, 7.7, cx + 3.4, 14.4), '#fff9f0'),
                           ((cx - 1.9, 7.8, cx + 1.9, 11.8), '#1c2328')):
            draw.ellipse(tuple(round(n * scale) for n in box), fill=color)
    return {facing: over(body, eyes.rotate(degrees)).resize((SIZE, SIZE), Image.Resampling.LANCZOS)
            for facing, degrees in FACINGS.items()}

def metal_color(im, color):
    a = np.array(im)
    light = np.asarray(ImageOps.grayscale(im)).astype(float)[...,None]/255
    rgb = np.array(color, dtype=float)[None,None,:]
    a[...,:3] = np.clip(a[...,:3]*.25 + rgb*(.22+.78*light)*.75,0,255).astype('uint8')
    return Image.fromarray(a)

def inset(im,n=2):
    out=blank();out.alpha_composite(im.resize((64-2*n,64-2*n),Image.Resampling.LANCZOS),(n,n));return out

def over(base,top):
    im=base.copy();im.alpha_composite(top);return im

def glow(im):
    a=im.getchannel('A').filter(ImageFilter.MaxFilter(5)); out=Image.new('RGBA',im.size,(255,203,76));out.putalpha(a);out.alpha_composite(im);return out

def terrain(cell):
    # Remove the generator's narrow cell margin; surfaces meet exactly.
    return cell.crop((round(cell.width*.035),round(cell.height*.035),round(cell.width*.965),round(cell.height*.965))).resize((64,64),Image.Resampling.LANCZOS).convert('RGBA')

def seamless_wall(cell, crop_bevel=True):
    # The master's bottom bevel is for an isolated block. Crop to its face
    # before joining walls, then match opposite edge bands in both axes.
    face = cell.crop((round(cell.width*.055), round(cell.height*.035),
                      round(cell.width*.945), round(cell.height*.82))) if crop_bevel else cell
    a = np.array(face.resize((64,64), Image.Resampling.LANCZOS)).astype(float)
    for axis in (0,1):
        a = np.swapaxes(a,0,axis)
        for k in range(6):
            left, right = a[k].copy(), a[-1-k].copy()
            average = (left + right) / 2
            blend = (6-k)/6
            a[k] = left*(1-blend)+average*blend
            a[-1-k] = right*(1-blend)+average*blend
        a = np.swapaxes(a,0,axis)
    a[...,3] = 255
    return Image.fromarray(np.round(a).astype('uint8'))

def connected_wall(texture, mask):
    # Only exposed edges have a bevel/front face. A joined edge is the
    # unmodified material, so long walls and filled blocks share one cap.
    y, x = np.mgrid[:SIZE, :SIZE]
    shade = np.ones((SIZE, SIZE), dtype=float)
    for bit, distance, light, width in ((1, x, .24, 5), (2, y, .30, 5),
                                         (4, 63-x, -.28, 5), (8, 63-y, -.42, 10)):
        if not mask & bit:
            shade += light * np.maximum(0, 1-distance/width)
    for bit, cx, cy, light in ((16, 0, 0, .24), (32, 63, 0, .12),
                                (64, 63, 63, -.32), (128, 0, 63, -.22)):
        if mask & bit:
            shade += light * np.maximum(0, 1-np.hypot(x-cx, y-cy)/9)
    a = np.array(texture)
    a[..., :3] = np.clip(a[..., :3].astype(float)*shade[..., None], 0, 255).astype('uint8')
    a[..., 3] = 255
    return Image.fromarray(a)

def clean_cutout(im):
    a = np.array(im)
    # Remove the faint matte around the generated crystal without changing
    # the provider master; retain antialiasing on its opaque silhouette.
    a[...,3] = np.clip((a[...,3].astype(float)-48)*255/207,0,255).astype('uint8')
    a[a[...,3]==0] = 0
    return Image.fromarray(a)

def refined_sprite(name, fill):
    return fit(Image.open(HERE/'source'/name).convert('RGBA'), fill)

def sensor_marker(ring, frame=0, active=False):
    # The original has an open center and a small bead travelling around
    # the ring. Draw the bead in each phase without filling in the floor.
    scale=4
    out=ring.resize((SIZE*scale,SIZE*scale),Image.Resampling.LANCZOS)
    angle=frame*math.pi/4
    x,y=32+19*math.sin(angle),32-19*math.cos(angle)
    d=ImageDraw.Draw(out)
    box=tuple(round(v*scale) for v in (x-3,y-3,x+3,y+3))
    d.ellipse(box,fill='#ff7950' if active else '#e73525',outline='#70251e',width=scale)
    d.ellipse(tuple(round(v*scale) for v in (x-1.5,y-1.8,x,y-.3)),fill='#ffd1a0')
    return out.resize((SIZE,SIZE),Image.Resampling.LANCZOS)

def build_sprites():
    objects=[fit(i) for i in crop_sheet('objects.png',8,8)]
    raw=crop_sheet('terrain.png',6,6)
    t=[terrain(i) if n<20 else fit(i) for n,i in enumerate(raw)]
    for i in range(12, 19):
        t[i] = seamless_wall(raw[i])
    # Raised wooden braces distinguish the wall from the unchanged plank
    # floor. Matching edge bands still support every connected wall mask.
    t[16]=seamless_wall(Image.open(HERE/'source/timber-refined.png').convert('RGBA'),False)
    characters=[fit(i) for i in crop_sheet('characters.png',4,7)]
    views={'down':0,'left':1,'up':2,'right':3}
    o=lambda i:objects[i].copy()
    out={}
    def tile(n,im):out[f'tile-{n}']=im
    for n,i in {0:0,10:0,12:12,60:1,61:4,63:18,64:10,70:28,76:12,77:6,78:7,95:13,96:14,97:15,98:16,99:1,100:2,101:3,102:4,103:5,162:8,163:9,164:17}.items():tile(n,t[i])
    mapping={1:0,2:1,3:2,7:7,8:8,9:6,13:9,15:12,16:13,17:14,18:20,21:16,25:17,26:18,27:19,29:21,33:22,34:23,44:1,45:4,46:3,50:13,51:13,52:13,57:41,58:36,59:47,72:6,82:34,83:29,84:36,88:30,89:31,90:32,91:33,92:10,93:62,94:63,104:10,105:11,106:54,122:47,123:11,135:40,136:46,137:41,138:45,139:38,140:44,141:48,142:43,148:49,150:57,151:58,156:60,157:61,158:37,159:42,160:47,161:36,165:39,167:56,168:55}
    for n,i in mapping.items():tile(n,o(i))
    for n,i in {11:25,19:23,28:24,30:26,31:26,35:27,36:21,37:21,38:21,39:22,53:21,54:21,55:21,56:34,62:29,71:29,72:33,57:30,58:31,59:32}.items():tile(n,t[i])
    for n,deg in {44:-45,50:-60,51:90,52:180,37:220,38:50,53:170,54:270,55:120,31:0}.items():tile(n,hue(out[f'tile-{n}'],deg))
    # All six original-style paint splats share exactly the same silhouette.
    paint=refined_sprite('paint-refined.png',.76)
    for n,deg in {15:-120,16:120,17:0,50:60,51:160,52:-65}.items():tile(n,hue(paint,deg))
    tile(18,refined_sprite('goal-refined.png',.66))
    for n,deg in {4:0,5:220,6:120,47:175,48:275,49:50}.items():tile(n,hue(t[20],deg))
    for n,deg in {73:0,74:100,75:220,85:180,86:-60,87:205}.items():tile(n,hue(o(8),deg))
    for n,deg in {143:220,144:50,145:175,146:275,147:120}.items():tile(n,hue(t[22],deg))
    for n in (14,127,128,129,130):tile(n,inset(t[18] if n==14 else hue(t[18],(n-127)*15),1))
    trail=hue(t[26],75); ImageDraw.Draw(trail).rectangle((12,31,51,34),fill='#b26bdd'); tile(11,trail)
    out['door-open']=inset(t[19])
    for i in range(4):
        out[f'moss-lowered-{i}']=inset(hue(t[19],i*15))
        tile(131+i,over(inset(t[1+i],4),inset(o(9),12)))
    wood_door = over(inset(t[16],6),o(10))
    colors = ((237,67,61),(65,137,240),(88,185,96))
    for c,color in enumerate(colors):
        for part,im in enumerate((o(10),o(62),o(63))):tile(107+c*3+part,metal_color(im,color))
        out[f'gate-open-{c}']=metal_color(o(11),color);tile(124+c,out[f'gate-open-{c}'])
        tile(116+c*2,metal_color(wood_door,color));tile(117+c*2,metal_color(o(11),color))
    for n,i in ((92,10),(93,62),(94,63),(123,11)):tile(n,metal_color(o(i),(244,156,58)))
    tile(104,wood_door)
    out['gate-open']=o(11)
    sensor=refined_sprite('sensor-refined.png',.64)
    active_sensor=hue(sensor,12)
    tile(20,sensor_marker(sensor))
    for n in (22,24):tile(n,sensor_marker(active_sensor,active=True))
    tile(19,over(t[23],inset(o(15),10)))
    tile(23,over(inset(connected_wall(t[12],0),3),fit(out['tile-1'],.4)))
    tile(32,hue(o(21),180))
    path_grey = ImageOps.grayscale(t[26]).convert('RGBA'); path_grey.putalpha(t[26].getchannel('A')); tile(31,path_grey)
    tile(161,t[31])
    tile(140,over(o(44),inset(o(41),8)))
    for i in range(1,9):
        out[f'sensor-{i}']=sensor_marker(active_sensor,i-1,True)
    for n,deg in zip(range(66,70),(180,90,0,-90)):tile(n,o(24).rotate(deg))
    for n,deg in zip(range(152,156),(90,0,-90,180)):tile(n,hue(o(59),180).rotate(deg))
    for n,deg in zip(range(169,173),(90,0,-90,180)):tile(n,hue(o(25),150).rotate(deg))
    for row,kind in enumerate(('dog','turtle','crab'), start=1):
        for facing,col in views.items():out[f'{kind}-{facing}']=characters[row*4+col].copy()
    for skin, ramp in {0: CLASSIC_RAMP, **SKIN_RAMPS}.items():
        for facing, base in overhead_blob(ramp).items():
            prefix=f'skin-{skin}-' if skin else ''
            out[f'{prefix}player-{facing}']=base
            out[f'{prefix}charged-{facing}']=glow(base)
    tile(40,hue(characters[0],110));out['shadow']=out['tile-40']
    out['projectile']=o(26)
    for fish,row in (('gold',4),('koi',5),('minnow',6)):
        for frame in range(4):
            for facing,col in views.items():
                # Bend the tail in each drawn view, retaining the body anchor.
                deg=FACINGS[facing]
                im=characters[row*4+col].rotate(-deg);a=np.array(im);start=42
                for y in range(start,64):a[y]=np.roll(a[y],round(math.sin(frame*math.pi/2)*(y-start)/12),axis=0)
                out[f'fish-{fish}-{frame}-{facing}']=Image.fromarray(a).rotate(deg)
    for n,row in ((82,1),(83,2),(88,3),(89,4),(90,5),(91,6)):tile(n,characters[row*4])
    for i in range(4):
        # Separate highlight phases keep the wave shape anchored.
        a=np.array(t[10]);rgb=a[...,:3].astype(float);a[...,:3]=np.clip(rgb*(1+.025*math.sin(i*math.pi/2)),0,255).astype('uint8');out[f'water-{i}']=Image.fromarray(a)
    def pit(mask,lava=False,phase=0,corner=False):
        im=t[11].copy() if lava else Image.new('RGBA',(64,64),'#102028')
        if lava and phase:
            a=np.array(im);a[...,:3]=np.clip(a[...,:3].astype(float)*(1+.045*math.sin(phase*math.pi/2)),0,255).astype('uint8');im=Image.fromarray(a)
        d=ImageDraw.Draw(im)
        # Screen-oriented connected edges, preserving existing 4-bit masks.
        for bit,rect in ((1,(0,0,3,63)),(2,(0,0,63,12)),(4,(60,0,63,63)),(8,(0,60,63,63))):
            if mask&bit:d.rectangle(rect,fill='#596565');d.line((rect[0],rect[1],rect[2],rect[1]),fill='#aebdb4',width=2)
        if corner:
            im=blank();d=ImageDraw.Draw(im)
            for bit,x,y in ((1,0,0),(2,58,0),(4,58,58),(8,0,58)):
                if mask&bit:d.rounded_rectangle((x,y,x+5,y+5),2,fill='#81948d')
        return im
    for mask in range(16):
        im=t[6].copy();d=ImageDraw.Draw(im)
        for bit,r in ((1,(0,0,4,63)),(2,(0,0,63,4)),(4,(59,0,63,63)),(8,(0,59,63,63))):
            if mask&bit:im.alpha_composite(t[6].crop(r),(r[0],r[1]))
        out[f'grass-edge-{mask}']=im
        out[f'abyss-edge-{mask}']=pit(mask);out[f'abyss-corner-{mask}']=pit(mask,corner=True)
        for phase in range(4):out[f'lava-edge-{mask}'+(f'-{phase}' if phase else '')]=pit(mask,True,phase)
    tile(65,out['abyss-edge-15']);tile(166,out['lava-edge-15'])
    out['boat-big']=o(50);out['boat-big-hull']=blank()
    out['boat-big-hull'].alpha_composite(o(50).crop((0,43,64,64)),(0,43))
    tile(149,over(inset(t[10]),inset(o(6),4)))
    for i in range(4):
        im=blank();d=ImageDraw.Draw(im);d.arc((3-i,5,60+i,59),25,155,fill=(183,242,244,130+i*20),width=2);out[f'boat-wake-{i}']=im
    for name,i in (('chest-closed',51),('chest-open',52),('chest-empty',53)):out[name]=o(i)
    for kind,count in (('burst',6),('explosion',8)):
        for i in range(count):
            im=inset(t[35],max(0,18-i*3));a=im.getchannel('A').point(lambda a:round(a*(1-i/(count+1))));im.putalpha(a);out[f'{kind}-{i}']=im
    assert set(out)==set(NAMES),(set(NAMES)-set(out),set(out)-set(NAMES))
    wall_textures = {kind: out[f'tile-{kind}'] for kind in WALL_KINDS}
    wall_textures[14] = t[18]
    wall_textures[62] = over(t[12], inset(t[29], 3))
    for kind in range(127, 131):
        wall_textures[kind] = hue(t[18], (kind-127)*15)
    for kind, texture in wall_textures.items():
        for mask in WALL_MASKS:
            out[f'wall-{kind}-{mask}'] = connected_wall(texture, mask)
        # Existing individual paths remain useful for palette consumers.
        out[f'tile-{kind}'] = out[f'wall-{kind}-0']
    return out

def hashname(name):
    h=2166136261
    for b in name.encode():h=((h^b)*16777619)&0xffffffff
    return h

def pack(sprites):
    from importlib.machinery import SourceFileLoader
    land=SourceFileLoader('landscape',str(ROOT/'tools/levels/landscape.py')).load_module()
    images={}
    for name,im in sprites.items():images['portrait/'+name]=im
    for name,im in sprites.items():
        other=land.landscape_source_stem(name)
        wide=sprites[other]
        if land.turns_with_board(Path(name+'.png')):wide=wide.transpose(Image.Transpose.ROTATE_90)
        images['landscape/'+name]=wide
    unique={};entries={}
    for name,im in sorted(images.items()):
        digest=hashlib.sha256(im.tobytes()).hexdigest()
        if digest not in unique:unique[digest]=(len(unique),im)
        entries[name]=unique[digest][0]
    columns=math.ceil(math.sqrt(len(unique)));rows=math.ceil(len(unique)/columns);pitch=66
    atlas=Image.new('RGBA',(columns*pitch,rows*pitch))
    for i,im in unique.values():
        x,y=i%columns*pitch+1,i//columns*pitch+1
        atlas.alpha_composite(im,(x,y))
        # Extruded borders prevent neighbor bleed during smooth scaling.
        for box,pos in (((0,0,64,1),(x,y-1)),((0,63,64,64),(x,y+64)),((0,0,1,64),(x-1,y)),((63,0,64,64),(x+64,y))):atlas.paste(im.crop(box),pos)
        for dx,dy in ((-1,-1),(64,-1),(-1,64),(64,64)):atlas.putpixel((x+dx,y+dy),im.getpixel((0 if dx<0 else 63,0 if dy<0 else 63)))
    frames={name:[i%columns*pitch+1,i//columns*pitch+1,64,64] for name,i in entries.items()}
    dest=ROOT/'assets/shovey/sprites/atlas.png';atlas.save(dest,optimize=True)
    spec={'image':'atlas.png','size':list(atlas.size),'logical_size':128,'unique_frames':len(unique),'aliases':len(entries),'padding':1,'occupied_cells':len(unique)/(columns*rows),'frames':frames}
    (dest.with_suffix('.json')).write_text(json.dumps(spec,indent=2)+'\n')
    generate_code(frames)
    return spec

def generate_code(frames):
    def numbers(values):
        values=list(map(str,values))
        return ',\n'.join(','.join(values[at:at+64]) for at in range(0,len(values),64))
    names=sorted(name.removeprefix('portrait/') for name in frames if name.startswith('portrait/'))
    capacity=1 << (len(names)*2-1).bit_length()
    slots=[0]*capacity
    for i,name in enumerate(names):
        at=hashname(name)%capacity
        while slots[at]:at=(at+1)%capacity
        slots[at]=i+1
    text='// Generated by tools/modern/build.py. Do not edit.\n'
    text+='atlas_names: [%d]string = .[%s];\n'%(len(names),',\n'.join(json.dumps(n+'.png') for n in names))
    text+=f'atlas_slots: [{capacity}]s32 = .['+numbers(slots)+'];\n'
    text+=f'atlas_hash_capacity :: {capacity}\n'
    text+='atlas_wall_kinds: [14]s32 = .['+','.join(map(str,WALL_KINDS))+'];\n'
    text+='atlas_wall_masks: [47]s32 = .['+','.join(map(str,WALL_MASKS))+'];\n'
    text+='atlas_wall_indices: [256]s32 = .['+','.join(str(WALL_MASKS.index(mask) if mask in WALL_MASKS else -1) for mask in range(256))+'];\n'
    columns = max(rect[0] for rect in frames.values()) // 66 + 1
    text += f'atlas_columns :: {columns}\n'
    for orientation in ('portrait','landscape'):
        indices = [(frames[orientation+'/'+n][1]-1)//66*columns + (frames[orientation+'/'+n][0]-1)//66 for n in names]
        text += f'atlas_{orientation}: [{len(names)}]s32 = .[' + numbers(indices) + '];\n'
    (ROOT/'src/sprite_atlas_data.zi').write_text(text)


def previews(sprites):
    original=Image.open(HERE/'source/original.png').convert('RGBA')
    before={n:original.crop((r[0],r[1],r[0]+r[2],r[1]+r[3])).resize((64,64),Image.Resampling.NEAREST) for n,r in NAMES.items()}
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22)
    selected=[f'tile-{i}' for i in range(173) if f'tile-{i}' in sprites]+[f'{a}-{f}' for a in ('player','charged','dog','turtle','crab') for f in FACINGS]
    columns=12;rows=math.ceil(len(selected)/columns);panel=columns*76
    out=Image.new('RGB',(panel*2+48,rows*92+90),'#17262b');d=ImageDraw.Draw(out)
    for side,group in enumerate((before,sprites)):
        ox=16+side*(panel+16);d.text((ox,18),'BEFORE  /  original sprites' if side==0 else 'AFTER  /  modern sprites',font=font,fill='#eff3e9')
        for i,n in enumerate(selected):
            x=ox+i%columns*76;y=65+i//columns*92
            out.paste(group['tile-0'].convert('RGB'),(x,y));out.paste(group[n],(x,y),group[n]);d.text((x,y+65),n.removeprefix('tile-'),fill='#aebdb4')
    out.save(ROOT/'art/modern/before-after-sprites.png')
    # Exercise runs, ends, corners, T/cross junctions and concave corners.
    walls=[(12,'Stone'),(95,'Slate'),(96,'Brick'),(97,'Sandstone'),(98,'Timber'),(164,'Cave'),(63,'Moss')]
    shape=('111000111', '111000101', '111000111', '000010000', '011111110', '000010000')
    tiled=Image.new('RGB',(9*40*2+36,6*40*4+160),'#17262b');d=ImageDraw.Draw(tiled)
    for i,(n,label) in enumerate(walls):
        x=i%2*(9*40+16)+8;y=i//2*(6*40+38)+32
        walls=[0]*240
        for yy,row in enumerate(shape):
            for xx,occupied in enumerate(row):
                if occupied=='1':walls[yy*12+xx]=n
        for yy,row in enumerate(shape):
            for xx,occupied in enumerate(row):
                name=wall_name(n,yy*12+xx,walls) if occupied=='1' else 'tile-99'
                tiled.paste(sprites[name].resize((40,40),Image.Resampling.LANCZOS),(x+xx*40,y+yy*40))
        d.text((x,y-22),label,fill='white')
    tiled.save(ROOT/'art/modern/wall-tiling.png')
    sheets=Image.new('RGB',(808,7*166),'#17262b');d=ImageDraw.Draw(sheets)
    for material,kind in enumerate(WALL_KINDS):
        x=material%2*404+8;y=material//2*166+24
        d.text((x,y-18),f'Wall {kind} / 47 connection shapes',fill='white')
        for shape,mask in enumerate(WALL_MASKS):
            sheets.paste(sprites[f'wall-{kind}-{mask}'].resize((32,32),Image.Resampling.LANCZOS),
                         (x+shape%12*32,y+shape//12*32))
    sheets.save(ROOT/'art/modern/wall-spritesheets.png')

    cutouts=Image.new('RGB',(1024,512))
    for row,name in enumerate(('tile-21','tile-165')):
        for col,bg in enumerate(('#141e28','#eeeeee','#b4d191','#85517f')):
            cell=Image.new('RGBA',(256,256),bg)
            cell.alpha_composite(sprites[name].resize((256,256),Image.Resampling.LANCZOS))
            cutouts.paste(cell,(col*256,row*256))
    cutouts.save(ROOT/'art/modern/cutouts.png')

    # Same authored cave level for both sides; level data is read only.
    data=json.loads((ROOT/'levels/approved.json').read_text())
    level=next((l for l in data['levels'] if any('a6' in row for row in l.get('tiles',[]))),data['levels'][0])
    def board(group):
        im=Image.new('RGBA',(12*48,20*48),'#17262b')
        walls=[int(''.join(level.get('tiles',level['cells']))[at*2:at*2+2],16) for at in range(240)]
        for at in range(240):
            cell=int(''.join(level['cells'])[at*2:at*2+2],16)
            if cell in WALL_KINDS:walls[at]=cell
        for y,row in enumerate(level['cells']):
            for x in range(12):
                idx=y*12+x;kind=int(row[x*2:x*2+2],16)
                im.alpha_composite(group['tile-0'].resize((48,48),Image.Resampling.LANCZOS),(x*48,y*48))
                for layer in ('tiles','cells','decorations'):
                    lines=level.get(layer,[])
                    k=int(lines[y][x*2:x*2+2],16) if len(lines)>y else 0
                    n='player-up' if k==10 else f'tile-{k}'
                    if layer=='tiles' and k==0:n='tile-0'
                    elif k==0:continue
                    if group is sprites and k in WALL_KINDS:n=wall_name(k,idx,walls)
                    if group is sprites and k in {4,5,6,47,48,49}:
                        im.alpha_composite(group[f'tile-{pit_floor(idx,walls)}'].resize((48,48),Image.Resampling.LANCZOS),(x*48,y*48))
                    im.alpha_composite(group.get(n,group['tile-0']).resize((48,48),Image.Resampling.LANCZOS),(x*48,y*48))
        return im
    a,b=board(before),board(sprites);out=Image.new('RGB',(a.width*2+60,a.height+96),'#17262b');d=ImageDraw.Draw(out)
    d.text((20,20),'BEFORE',font=font,fill='white');d.text((a.width+40,20),'AFTER',font=font,fill='white')
    out.paste(a,(20,70),a);out.paste(b,(a.width+40,70),b);out.save(ROOT/'art/modern/before-after-board.png')
    refinement_previews(before,sprites)

def refinement_previews(original,sprites):
    kinds=(98,102,20,22,23,15,18)
    labels=('Timber wall','Wood floor (unchanged)','Sensor ring','Active ring','Closed sensor','Paint splat','Box target')
    previous=Image.open(HERE/'source/refinement-before.png').convert('RGBA')
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',18)
    out=Image.new('RGB',(810,70+len(kinds)*126),'#17262b');d=ImageDraw.Draw(out)
    for column,title in enumerate(('ORIGINAL','PREVIOUS','REFINED')):
        d.text((232+column*190,20),title,font=font,fill='white')
    for row,(kind,label) in enumerate(zip(kinds,labels)):
        y=64+row*126
        d.text((12,y+44),label,font=font,fill='#eff3e9')
        old=previous.crop((row*128,0,(row+1)*128,128))
        for column,image in enumerate((original[f'tile-{kind}'],old,sprites[f'tile-{kind}'])):
            floor=sprites['tile-99'].resize((108,108),Image.Resampling.LANCZOS)
            floor.alpha_composite(image.resize((108,108),Image.Resampling.NEAREST if column==0 else Image.Resampling.LANCZOS))
            out.paste(floor,(242+column*190,y))
    out.save(ROOT/'art/modern/refinements-before-after.png')
    # The goal keeps clear margins and a dark/light outline on every
    # authored floor material, plus ice, water, abyss and lava.
    floors=(0,60,61,77,78,99,100,101,102,103,162,163,70,64,65,166)
    names=('Stone','Checker','Striped','Grass','Sand','Slate','Brick','Sandstone','Timber','Moss','Forest','Cave','Ice','Water','Abyss','Lava')
    out=Image.new('RGB',(8*112+16,2*140+56),'#17262b');d=ImageDraw.Draw(out)
    d.text((12,12),'INSET BOX TARGET / FLOOR CONTRAST',font=font,fill='white')
    for i,(kind,label) in enumerate(zip(floors,names)):
        image=sprites[f'tile-{kind}'].resize((96,96),Image.Resampling.LANCZOS)
        image.alpha_composite(sprites['tile-18'].resize((96,96),Image.Resampling.LANCZOS))
        x=12+i%8*112;y=48+i//8*140
        out.paste(image,(x,y));d.text((x,y+100),label,font=font,fill='#eff3e9')
    out.save(ROOT/'art/modern/target-floor-contrast.png')

def main():
    sprites=build_sprites()
    folder=ROOT/'assets/shovey/sprites'
    for n,im in sprites.items():im.resize((128,128),Image.Resampling.LANCZOS).save(folder/(n+'.png'),optimize=True)
    spec=pack(sprites)
    artpath=ROOT/'assets/shovey/art.json';art=json.loads(artpath.read_text())
    listed={item['path'] for item in art['files']}
    for name in sprites:
        if f'sprites/{name}.png' not in listed:
            art['files'].append({'path':f'sprites/{name}.png','depicts':f'Connected wall variant {name}'})
    for item in art['files']:
        descriptions={18:'crate goal: inset gold corner brackets, dark outline and transparent center',
                      20:'sensor: open red ring with a small red bead and transparent center',
                      22:'active sensor: open warm red ring and orbiting bead',
                      24:'active sensor: open warm red ring and orbiting bead',
                      23:'closed sensor: raised stone block with a red center',
                      98:'timber wall: raised wooden framing and inset planks, without metal bands'}
        for kind,description in descriptions.items():
            if item['path']==f'sprites/tile-{kind}.png':item['depicts']=description
        p=artpath.parent/item['path']
        if p.exists():item['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    art['files']=[i for i in art['files'] if i['path']!='sprites/atlas.png']+[{'path':'sprites/atlas.png','depicts':'Modern packed portrait and landscape sprites, deduplicated with extruded borders','sha256':hashlib.sha256((folder/'atlas.png').read_bytes()).hexdigest()}]
    art['generator']='tools/modern/build.py';art['method']='AI-generated modern bitmap masters; deterministic crops, color variants, connected edges and deduplicated 64px atlas. Original artwork preserved in tools/modern/source/original.png.'
    artpath.write_text(json.dumps(art,indent=2)+'\n')
    previews(sprites)
    print(f"Modern art: {len(sprites)} sprites, {spec['unique_frames']} unique atlas frames, {spec['size']}, {spec['occupied_cells']:.1%} cells occupied")
if __name__=='__main__':main()
