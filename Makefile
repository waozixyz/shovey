.DEFAULT_GOAL := all
ZIRAN ?= ziran
LOCK_FLAGS := $(if $(wildcard ziran.local.toml),,--locked)
TOOLCHAIN = $(shell $(ZIRAN) pkg path ziran $(LOCK_FLAGS))
KRYON = $(shell $(ZIRAN) pkg path kryon $(LOCK_FLAGS))
APPS = $(shell $(ZIRAN) pkg path apps $(LOCK_FLAGS))
EDITOR_OUT ?= build/private-editor
EDITOR_DEFINES ?=

.PHONY: all levels bundles landscape previews art solver bench test play import-tool editor-card web web-test web-itch

.PHONY: editor editor-ui-test editor-save-test editor-glm-test editor-server-test
editor-server-test:
	python3 tests/editor_server_test.py

editor-glm-test: solver
	python3 tests/editor_glm_test.py

editor-save-test: editor solver
	python3 tests/developer_editor_save_test.py

editor-ui-test: editor editor-server-test
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS YUE_DESKTOP_RECOVERY=0 \
		xvfb-run -a -n 400 -s '-screen 0 1600x1100x24' python3 tests/developer_editor_ui_test.py
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS YUE_DESKTOP_RECOVERY=0 \
		xvfb-run -a -n 400 -s '-screen 0 1600x1100x24' python3 tests/developer_editor_approval_ui_test.py

editor: levels build/ziran/libziran.a
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path '$(KRYON)/src/ui' --module-path '$(KRYON)/src/backend' \
		--module-path 'kryon=$(KRYON)/src/ui' --module-path 'kryon=$(KRYON)/src/backend' \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		$(EDITOR_DEFINES) --entry editor:main -o $(EDITOR_OUT)/c tools/editor/editor.zi
	$${CC:-cc} -std=c11 -O2 -ffunction-sections -fdata-sections -I'$(TOOLCHAIN)/include' \
		$$(find $(EDITOR_OUT)/c -type d -printf ' -iquote %p') $$(find $(EDITOR_OUT)/c -name '*.c') \
		build/ziran/libziran.a -Wl,--gc-sections \
		$$(pkg-config --libs sdl2 cairo freetype2 fontconfig pangocairo) -lm -lpthread \
		-o $(EDITOR_OUT)/shovey-level-editor.new
	mv $(EDITOR_OUT)/shovey-level-editor.new $(EDITOR_OUT)/shovey-level-editor

.PHONY: admin-editor
admin-editor:
	$(MAKE) editor EDITOR_OUT=build/admin-editor EDITOR_DEFINES='--define SHOVEY_ADMIN'
	ZIRAN_TOOLCHAIN='$(TOOLCHAIN)' SOLVER_OUT='$(abspath build/admin-editor/solver)' SHOVEY_ADMIN=1 sh tools/solver/build.sh
	python3 scripts/package-editor.py

.PHONY: inbe-ui-test
inbe-ui-test:
	@test -n "$(INBE_BINARY)" || { echo 'Set INBE_BINARY to the intended Inbe host'; exit 2; }
	@test -n "$(INBE_SOURCE)" || { echo 'Set INBE_SOURCE to the Inbe source'; exit 2; }
	@test -n "$(ARCADE_BUNDLE)" || { echo 'Set ARCADE_BUNDLE to the Arcade collection'; exit 2; }
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS \
		-u SESSION_MANAGER -u GDK_DISPLAY YUE_DESKTOP_RECOVERY=0 SDL_AUDIODRIVER=dummy APP_NO_TRAY=1 \
		timeout 240s xvfb-run -a -n 400 -s '-screen 0 1280x1000x24' \
		python3 tests/inbe_navigation_ui_test.py --binary '$(INBE_BINARY)' --inbe-source '$(INBE_SOURCE)' --bundle '$(ARCADE_BUNDLE)'

all: bundles

# The JSON level files are the source; the game reads the generated code.
levels: src/levels.zi src/island_levels.zi

src/levels.zi src/island_levels.zi: levels/classic.json levels/island.json tools/levels/levels.py
	python3 tools/levels/levels.py generate

landscape:
	python3 tools/levels/landscape.py --check

bundles: levels landscape
	python3 scripts/build-bundles.py --toolchain '$(TOOLCHAIN)' --kryon '$(KRYON)' --apps '$(APPS)'

web: bundles
	rm -rf build/web
	mkdir -p build/web
	'$(TOOLCHAIN)/build/bin/ziran' bundle --root . --module-path '$(KRYON)/src/ui' \
		--module-path 'kryon=$(KRYON)/src/ui' --module-path 'kryon=$(KRYON)/src/backend' \
		--module-path 'apps=$(APPS)/src' --module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--module-path build/game-generated/shovey --define KRYON_HOSTED_UI --define SHOVEY_WEB \
		--asset-dir assets=build/game-assets/shovey/assets --entry game:Main \
		-o build/web/shovey.zib src/web/game.zi
	$(MAKE) -C '$(KRYON)' zib-canvas ZIRAN_ROOT='$(TOOLCHAIN)' \
		ZIB_CANVAS_DIR='$(abspath build/web-runtime)' \
		ZIB_CANVAS_BUNDLE='$(abspath build/web/shovey.zib)' \
		ZIB_CANVAS_PROGRAM='$(abspath build/web/runtime.html)'
	cp src/web/index.html build/web/index.html
	cp assets/shovey/preview.png build/web/loading.png
	cp build/web/runtime.js build/web/index.js
	cp build/web/runtime.wasm build/web/index.wasm
	rm -f build/web/runtime.html build/web/runtime.js build/web/runtime.wasm

web-itch: web

web-test: web
	node tests/web_loading_test.mjs

previews:
	python3 tools/levels/levels.py previews

art:
	cd tools/art && npm ci && node render.mjs

build/ziran/libziran.a:
	$(MAKE) -C '$(TOOLCHAIN)' BUILD_DIR='$(abspath build/ziran)' '$(abspath $@)'

solver: levels build/ziran/libziran.a
	ZIRAN_TOOLCHAIN='$(TOOLCHAIN)' sh tools/solver/build.sh

# The Ziran solver run natively over the story levels:
#   build/solver/shovey-bench classic|island [FIRST [LAST [BUDGET]]]
bench: levels build/ziran/libziran.a
	rm -rf build/solver/bench
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--entry bench:main -o build/solver/bench tools/solver/bench.zi
	$${CC:-cc} -std=c11 -O2 -ffunction-sections -fdata-sections -I'$(TOOLCHAIN)/include' \
		$$(find build/solver/bench -type d -printf ' -iquote %p') $$(find build/solver/bench -name '*.c') \
		build/ziran/libziran.a -Wl,--gc-sections -lm -lpthread -o build/solver/shovey-bench

test: solver
	python3 tools/levels/levels.py generate --check
	python3 tools/levels/landscape.py --check
	python3 tests/levels_test.py
	python3 tests/assets_test.py
	sh tests/engine_test.sh '$(TOOLCHAIN)'
	$(MAKE) bundles

# A desktop player that records a winning route for each board it is given:
#   build/play/shovey-play LIST ROUTES [CLASSIC_LEVELS ISLAND_LEVELS]
play: levels build/ziran/libziran.a
	rm -rf build/play/c
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root tools/play \
		--module-path '$(KRYON)/src/ui' --module-path '$(KRYON)/src/backend' \
		--module-path 'kryon=$(KRYON)/src/ui' --module-path 'kryon=$(KRYON)/src/backend' \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--entry play:main -o build/play/c tools/play/play.zi
	$${CC:-cc} -std=c11 -O2 -ffunction-sections -fdata-sections -I'$(TOOLCHAIN)/include' \
		$$(find build/play/c -type d -printf ' -iquote %p') $$(find build/play/c -name '*.c') \
		build/ziran/libziran.a -Wl,--gc-sections \
		$$(pkg-config --libs sdl2 cairo freetype2 fontconfig pangocairo) -lm -lpthread -o build/play/shovey-play

# Brings levels made in the Shovey Editor into the level files, when the
# developer decides to; every route is replayed to a win first:
#   build/levels/import-edits [--append] [--no-generate] [--levels DIR] [EXPORT]
import-tool: levels build/ziran/libziran.a
	rm -rf build/levels/c
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--entry import_edits:main -o build/levels/c tools/levels/import_edits.zi
	$${CC:-cc} -std=c11 -O2 -ffunction-sections -fdata-sections -I'$(TOOLCHAIN)/include' \
		$$(find build/levels/c -type d -printf ' -iquote %p') $$(find build/levels/c -name '*.c') \
		build/ziran/libziran.a -Wl,--gc-sections -lm -lpthread -o build/levels/import-edits

# The Shovey Editor's card, drawn from both editions' pictures on a private
# display and written to assets/shovey-editor/preview.png.
editor-card: levels build/ziran/libziran.a
	rm -rf build/card/c
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path '$(KRYON)/src/ui' --module-path '$(KRYON)/src/backend' \
		--module-path 'kryon=$(KRYON)/src/ui' --module-path 'kryon=$(KRYON)/src/backend' \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--entry editor_card:main -o build/card/c tools/pixel/editor_card.zi
	$${CC:-cc} -std=c11 -O2 -ffunction-sections -fdata-sections -I'$(TOOLCHAIN)/include' \
		$$(find build/card/c -type d -printf ' -iquote %p') $$(find build/card/c -name '*.c') \
		build/ziran/libziran.a -Wl,--gc-sections \
		$$(pkg-config --libs sdl2 cairo freetype2 fontconfig pangocairo) -lm -lpthread -o build/card/editor-card
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS YUE_DESKTOP_RECOVERY=0 \
		KRYON_CAPTURE_PATH='$(abspath assets/shovey-editor/preview.png)' xvfb-run -a -n 400 build/card/editor-card
