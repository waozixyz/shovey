"""Exercise the editor's real JSON reader and byte-preserving writer."""
import json, os, shlex, shutil, subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
work = root / 'work/editor-variant-parser'
profile = work / 'profile'
(profile / 'levels').mkdir(parents=True, exist_ok=True)
(profile / 'assets/shovey/sprites').mkdir(parents=True, exist_ok=True)
(profile / 'backup/editor-drafts').mkdir(parents=True, exist_ok=True)
shutil.copyfile(root / 'assets/shovey/sprites/tile-0.png', profile / 'assets/shovey/sprites/tile-0.png')
data = json.loads((root / 'levels/approved.json').read_text())
data['unknown_metadata'] = {'nested': ['keep', {'cells': ['not a board']}]}
fixture = work / 'fixture.json'
fixture.write_text(json.dumps(data, indent=1) + '\n')
raw = fixture.read_bytes()
assert len(data['levels']) == 175
assert all('engine_variant' in data['levels'][n-1] for n in (93, 125))
(profile / 'levels/classic.json').write_bytes(raw)
binary = root / 'build/private-editor/shovey-level-editor'
subprocess.run([binary, '--check-file', fixture], check=True)
subprocess.run([binary, '--export-boards', work / 'boards.json'], cwd=profile, check=True)
boards = json.loads((work / 'boards.json').read_text())['boards']
for n in (93, 94, 97, 98, 99, 125):
    level = data['levels'][n-1]
    effective = dict(level, **level.get('engine_variant', {}))
    assert boards[n-1]['number'] == n and boards[n-1]['in_game']
    cells = ''.join(effective['cells'])
    if n == 99:
        # ReadBoard moves legacy terrain from the cell layer to tiles.
        for offset, kind in ((78, '04'), (88, '06')):
            assert cells[offset:offset+2] == kind and boards[n-1]['hex'][480+offset:482+offset] == kind
            cells = cells[:offset] + '00' + cells[offset+2:]
    assert boards[n-1]['hex'][:480] == cells
assert sum(bool(x['in_game']) for x in boards) == 175
# Compile a non-GUI harness against the actual generated editor code. It edits
# one byte of the variant and invokes the same writer used by StartSave.
c = work / 'parser_test.c'
c.write_text('''#include "tools/editor/editor.h"\n#include <assert.h>\n#include <stdio.h>\n#include <stdlib.h>\n#undef main\nint main(int argc, char **argv) {\n FILE *f=fopen(argv[1],"rb"); assert(f); fseek(f,0,SEEK_END); long n=ftell(f); rewind(f); char *p=malloc(n); assert(fread(p,1,n,f)==n); fclose(f);\n assert(editor_ReadLevelFile((String){p,n}));\n String before=editor_LevelFileText(); assert(before.length==n && !memcmp(before.data,p,n));\n int idx=atoi(argv[3]); file_insert=atoi(argv[4]); file_dirty=idx;\n if(file_insert) { if(idx==file_count) memcpy(file_boards+idx*HEX,file_boards+(idx-1)*HEX,HEX); for(int i=file_count;i>idx;i--) { memcpy(file_boards+i*HEX,file_boards+(i-1)*HEX,HEX); file_route_start[i]=file_route_start[i-1]; file_route_length[i]=file_route_length[i-1]; } file_count++; }\n file_boards[idx*HEX] = file_boards[idx*HEX]=='0' ? '1' : '0';\n file_route_start[idx]=file_routes_used; file_route_length[idx]=1; file_routes[file_routes_used++]='2';\n String out=editor_LevelFileText(); f=fopen(argv[2],"wb"); assert(f); assert(fwrite(out.data,1,out.length,f)==out.length); fclose(f); free(p); return 0; }\n''')
# Local package overrides replace the lock, as in the Makefile and scripts/player.py.
lock = [] if (root / 'ziran.local.toml').exists() else ['--locked']
toolchain = Path(subprocess.check_output([str(root / 'scripts/ziran.sh'), 'pkg', 'path', 'ziran', *lock], cwd=root, text=True).strip())
generated = root / 'build/private-editor/c'
cmd = [os.environ.get('CC','cc'), '-std=c11', '-O2', '-ffunction-sections', '-fdata-sections', '-Dmain=shovey_editor_main', '-include', 'string.h', '-I'+str(toolchain/'include'), '-I'+str(generated)]
for folder in sorted({p.parent for p in generated.rglob('*.h')}): cmd += ['-iquote',str(folder)]
cmd += [str(p) for p in generated.rglob('*.c')] + [str(c),str(root/'build/ziran/libziran.a'),'-Wl,--gc-sections']
cmd += shlex.split(subprocess.check_output(['pkg-config','--libs','sdl2','cairo','freetype2','fontconfig','pangocairo'],text=True)) + ['-lm','-lpthread','-o',str(work/'parser-test')]
subprocess.run(cmd,cwd=root,check=True)
output=work/'edited.json'
subprocess.run([work/'parser-test',fixture,output,'92','0'],check=True)
edited=json.loads(output.read_bytes())
expected=json.loads(raw)
old=expected['levels'][92]['engine_variant']['cells'][0]
expected['levels'][92]['engine_variant']['cells'][0]=('1' if old[0]=='0' else '0')+old[1:]
expected['levels'][92]['engine_variant']['solution']='2'
# Writer materializes inherited fields in the variant when edited.
for field in ('tiles','decorations','solution'):
    if field not in expected['levels'][92]['engine_variant']:
        expected['levels'][92]['engine_variant'][field]=expected['levels'][92][field]
assert edited == expected
subprocess.run([binary,'--check-file',output],check=True)
# Insert at the beginning, middle, and end, retaining every prior record.
for idx in (0, 87, 175):
    result = work / f'insert-{idx}.json'
    subprocess.run([work/'parser-test',fixture,result,str(idx),'1'],check=True)
    actual = json.loads(result.read_text())
    records = actual['levels']
    assert len(records) == 176 and [x['number'] for x in records] == list(range(1,177))
    for old_idx, old in enumerate(data['levels']):
        restored = dict(records[old_idx + (old_idx >= idx)])
        restored['number'] = old['number']
        assert restored == old
    assert {k:v for k,v in actual.items() if k != 'levels'} == {k:v for k,v in data.items() if k != 'levels'}
    subprocess.run([binary,'--check-file',result],check=True)
# A later save reads the bytes written by the first, then edits a second variant.
second = work/'second.json'
subprocess.run([work/'parser-test',output,second,'124','0'],check=True)
second_data = json.loads(second.read_text())
assert second_data['levels'][92] == edited['levels'][92]
assert second_data['levels'][124]['engine_variant']['solution'] == '2'
# An empty variant inherits the base; a missing solution must remain safe.
empty = json.loads(raw)
empty['levels'][92]['engine_variant'] = {}
empty['levels'][92].pop('solution', None)
empty_file = work/'empty.json'
empty_file.write_text(json.dumps(empty, indent=1)+'\n')
empty_out = work/'empty-edited.json'
subprocess.run([work/'parser-test',empty_file,empty_out,'92','0'],check=True)
empty_result = json.loads(empty_out.read_text())
assert empty_result['levels'][92]['engine_variant']['solution'] == '2'
assert 'solution' not in empty_result['levels'][92]
assert empty_result['levels'][:92] == empty['levels'][:92]
assert empty_result['levels'][93:] == empty['levels'][93:]
# The historical original is an additional local repro when available.
historical = root/'work/level-redesign-97-99/editor-before-normalization-classic.json'
if historical.exists(): subprocess.run([binary,'--check-file',historical],check=True)
print('175 records, variants, metadata, insertions and repeated saves verified')
