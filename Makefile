.DEFAULT_GOAL := all
ZIRAN ?= ./scripts/ziran.sh
LOCK_FLAGS := $(if $(wildcard ziran.local.toml),,--locked)
TOOLCHAIN = $(shell $(ZIRAN) pkg path ziran $(LOCK_FLAGS))
KRYON = $(shell $(ZIRAN) pkg path kryon $(LOCK_FLAGS))
MINGCUTE = $(shell $(ZIRAN) pkg path mingcute $(LOCK_FLAGS))
APPS = $(shell $(ZIRAN) pkg path apps $(LOCK_FLAGS))
ENTITY = $(shell $(ZIRAN) pkg path entity $(LOCK_FLAGS))
DAOCHI_CLIENT = $(shell $(ZIRAN) pkg path DaochiClient $(LOCK_FLAGS))
CRYPTO = $(shell $(ZIRAN) pkg path crypto $(LOCK_FLAGS))
COMPLETION_MODULES = --module-path 'daochi_client=$(DAOCHI_CLIENT)' --module-path 'crypto=$(CRYPTO)/src'
EDITOR_OUT ?= build/private-editor
EDITOR_DEFINES ?=

# Ziran test programs: $(call ziran_test,NAME,ARGUMENTS) builds tests/NAME.zi
# into build/tests/NAME and runs it from the repository root, without the
# desktop's display or session.
ZIRAN_TEST_MODULES = --module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
	--module-path '$(KRYON)/src/ui' --module-path '$(KRYON)/src/backend' \
	--module-path 'kryon=$(KRYON)/src/ui' --module-path 'kryon=$(KRYON)/src/backend' \
	--module-path 'mingcute=$(MINGCUTE)/src'
define ziran_test
rm -rf build/tests/$(1)
'$(TOOLCHAIN)/build/bin/ziran' build --project --target=c --exe --root src --module-path tests --module-path src/solver --module-path tools/solver $(3) --entry $(1):main -o build/tests/$(1) tests/$(1).zi
env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS -u SESSION_MANAGER -u GDK_DISPLAY YUE_DESKTOP_RECOVERY=0 \
	build/tests/$(1)/$(1) $(2)
endef

.PHONY: all levels bundles landscape previews solver bench test play import-tool scenery-tool routes-tool public-test scenery-pictures editor-card web web-test web-itch web-zx web-zx-test package-crazygames-test web-crazygames

.PHONY: editor editor-ui-test editor-save-test editor-glm-test editor-server-test star-merge-test
editor-server-test:
	python3 tests/editor_chest_test.py
	python3 tests/editor_server_test.py
	python3 tests/editor_queue_test.py
	python3 tests/editor_cancel_test.py

editor-glm-test: solver
	python3 tests/editor_glm_test.py
	$(call ziran_test,solver_test)

.PHONY: public-editor-test
public-editor-test: build/ziran/libziran.a
	python3 tests/public_editor_test.py

editor-save-test: editor solver
	ZIRAN_TOOLCHAIN='$(TOOLCHAIN)' python3 tests/developer_editor_save_test.py
	ZIRAN_TOOLCHAIN='$(TOOLCHAIN)' python3 tests/editor_file_test.py

star-merge-test: editor
	$(call ziran_test,board_effects_test)
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS -u SESSION_MANAGER -u GDK_DISPLAY YUE_DESKTOP_RECOVERY=0 SDL_AUDIODRIVER=dummy \
		xvfb-run -a -n 400 -s '-screen 0 1600x1100x24' python3 tests/star_merge_ui_test.py --binary '$(EDITOR_OUT)/shovey-level-editor'

.PHONY: editor-map-test
editor-map-test: editor
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS -u SESSION_MANAGER -u GDK_DISPLAY YUE_DESKTOP_RECOVERY=0 SDL_AUDIODRIVER=dummy \
		xvfb-run -a -n 400 -s '-screen 0 1600x1200x24' python3 tests/developer_editor_map_ui_test.py

editor-ui-test: public-editor-test star-merge-test editor-server-test editor-map-test
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS YUE_DESKTOP_RECOVERY=0 \
		xvfb-run -a -n 400 -s '-screen 0 1600x1100x24' python3 tests/developer_editor_ui_test.py
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS -u SESSION_MANAGER -u GDK_DISPLAY YUE_DESKTOP_RECOVERY=0 \
		xvfb-run -a -n 400 -s '-screen 0 1600x1100x24' python3 tests/developer_editor_launch_ui_test.py
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS -u SESSION_MANAGER -u GDK_DISPLAY YUE_DESKTOP_RECOVERY=0 \
		xvfb-run -a -n 400 -s '-screen 0 1600x1100x24' python3 tests/developer_editor_designs_ui_test.py
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS -u SESSION_MANAGER -u GDK_DISPLAY YUE_DESKTOP_RECOVERY=0 \
		xvfb-run -a -n 400 -s '-screen 0 1600x1100x24' python3 tests/editor_chest_ui_test.py
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS YUE_DESKTOP_RECOVERY=0 \
		xvfb-run -a -n 400 -s '-screen 0 1600x1100x24' python3 tests/developer_editor_approval_ui_test.py
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS YUE_DESKTOP_RECOVERY=0 \
		xvfb-run -a -n 400 -s '-screen 0 1600x1100x24' python3 tests/editor_any_route_ui_test.py
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS YUE_DESKTOP_RECOVERY=0 \
		xvfb-run -a -n 400 -s '-screen 0 1600x1100x24' python3 tests/editor_memory_test.py --binary $(EDITOR_OUT)/shovey-level-editor

editor: levels build/ziran/libziran.a
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path '$(KRYON)/src/ui' --module-path '$(KRYON)/src/backend' \
		--module-path 'mingcute=$(MINGCUTE)/src' \
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
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS \
		-u SESSION_MANAGER -u GDK_DISPLAY YUE_DESKTOP_RECOVERY=0 SDL_AUDIODRIVER=dummy APP_NO_TRAY=1 \
		timeout 240s xvfb-run -a -n 400 -s '-screen 0 1280x1000x24' \
		python3 tests/level_change_ui_test.py --binary '$(INBE_BINARY)' --inbe-source '$(INBE_SOURCE)' --bundle '$(ARCADE_BUNDLE)'

all: bundles

# Shovey's player, the standalone game people download, built from this
# package's own lock (scripts/player.py): its collection, then the Linux and
# Windows downloads and the Google Play edition's bundle. The F-Droid recipe
# builds the APK with android-fdroid.
.PHONY: player player-linux player-windows player-bundle android-fdroid
player: levels landscape
	python3 scripts/player.py collection

player-linux: player
	python3 scripts/player.py linux

# Cross-builds with MinGW (x86_64-w64-mingw32-gcc, -windres and CMake).
player-windows: player
	python3 scripts/player.py windows

# The Windows player's sources through Ziran's front end, without MinGW: a
# call Kryon removed fails here in a minute rather than in the release build.
.PHONY: player-windows-check
player-windows-check: levels
	rm -rf build/player/windows-check
	'$(TOOLCHAIN)/build/bin/ziran' ir --project $(LOCK_FLAGS) --define _WIN32 --define PLATFORM_DESKTOP --define __x86_64__ \
		--define PLATFORM_DESKTOP_RGFW --define GRAPHICS_API_OPENGL_11 -o build/player/windows-check src/player_windows.zi
test: player-windows-check
public-test: player-windows-check

player-bundle: player
	python3 scripts/player.py android --bundle

# Installs the Linux player for this user, as Arcade installed Shovey before;
# saves and the account stay in ~/.local/share/arcade.
BIN_DIR ?= $(HOME)/.local/bin
LIB_DIR ?= $(HOME)/.local/lib/shovey
DATA_DIR ?= $(if $(XDG_DATA_HOME),$(XDG_DATA_HOME),$(HOME)/.local/share)
.PHONY: install
install: player-linux
	mkdir -p '$(BIN_DIR)' '$(LIB_DIR)/startup/shovey' '$(DATA_DIR)/applications' '$(DATA_DIR)/icons/hicolor/256x256/apps'
	install -m 0644 build/player/linux/startup/shovey/*.png '$(LIB_DIR)/startup/shovey/'
	install -m 0644 build/player/linux/shovey.zx build/player/linux/shovey.json build/player/linux/entity.zx '$(LIB_DIR)/'
	install -m 0755 build/player/linux/shovey '$(LIB_DIR)/shovey.new'
	mv -f '$(LIB_DIR)/shovey.new' '$(LIB_DIR)/shovey'
	ln -sfn '$(LIB_DIR)/shovey' '$(BIN_DIR)/shovey'
	install -m 0644 build/player/linux/shovey-icon.png '$(DATA_DIR)/icons/hicolor/256x256/apps/xyz.waozi.shovey.png'
	install -m 0644 packaging/linux/xyz.waozi.shovey.desktop '$(DATA_DIR)/applications/'

android-fdroid:
	sh scripts/android-build.sh

# The Google Play edition's APK, the only APK with Play Billing.
android-gplay:
	sh scripts/android-build.sh gplay

# The JSON level files are the source; the game reads the generated code.
levels: src/levels.zi

# levels/classic.json is private; without it the published campaign in
# levels/approved.json is built.
src/levels.zi: $(wildcard levels/classic.json levels/secret.json) levels/approved.json tools/levels/levels.py
	python3 tools/levels/levels.py generate
	python3 tools/levels/levels.py previews

landscape:
	python3 tools/levels/landscape.py --check

bundles: levels landscape
	python3 tests/build_bundles_test.py
	python3 scripts/build-bundles.py --toolchain '$(TOOLCHAIN)' --kryon '$(KRYON)' --apps '$(APPS)' --mingcute '$(MINGCUTE)'

# The standalone desktop app, built here without Arcade: Shovey's own bundle
# on Kryon's native player, in one folder. DESKTOP_DEFINES='--define
# SHOVEY_UNLOCK_ALL' makes a testing copy with every level open.
DESKTOP_DIR ?= build/desktop/shovey
DESKTOP_DEFINES ?=
.PHONY: desktop
desktop: bundles
	python3 scripts/prepare-web.py
	$(MAKE) -C '$(KRYON)' zx-raylib
	rm -rf '$(DESKTOP_DIR)'
	mkdir -p '$(DESKTOP_DIR)'
	'$(TOOLCHAIN)/build/bin/ziran' bundle --root . --module-path '$(KRYON)/src/ui' \
		--module-path 'kryon=$(KRYON)/src/ui' --module-path 'kryon=$(KRYON)/src/backend' \
		--module-path 'mingcute=$(MINGCUTE)/src' --module-path 'apps=$(APPS)/src' --module-path 'entity=$(ENTITY)/src' $(COMPLETION_MODULES) --module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--module-path build/web-generated --define KRYON_HOSTED_UI --define SHOVEY_WEB --define SHOVEY_RELEASE $(DESKTOP_DEFINES) \
		--bind editor_view:ReadAppUiHost=host:ReadAppUiHost --bind editor_view:AppLocaleHost=host:EditorLocaleHost \
		--bind editor_view:AppRecordHost=host:EditorRecordHost --bind editor_view:SaveAppRecordHost=host:EditorSaveRecordHost \
		--bind editor_view:AppKeyHost=host:GameKeyHost --bind editor_view:AppSoundHost=host:AppSoundHost \
		--bind editor_view:SmoothFramesHost=host:SmoothFramesHost --bind editor_view:AppSupportsHost=host:GameSupportsHost \
		--bind editor_view:AppServiceHost=controls:GameServiceHost --bind editor_view:AppFieldInputHost=host:GameFieldInputHost \
		--asset-dir assets=build/web-assets/assets --entry game:Main \
		-o '$(DESKTOP_DIR)/app.zx' src/web/game.zi
	cp '$(KRYON)/build/zx-raylib/zx' '$(DESKTOP_DIR)/shovey'
	cp '$(KRYON)/build/zx-raylib/kryon-font.ttf' '$(DESKTOP_DIR)/'
	printf 'Shovey\n' > '$(DESKTOP_DIR)/app.title'
	'$(DESKTOP_DIR)/shovey' --check '$(DESKTOP_DIR)/app.zx'

web-zx: bundles
	python3 scripts/prepare-web.py
	rm -rf build/web
	mkdir -p build/web
	'$(TOOLCHAIN)/build/bin/ziran' bundle --project $(LOCK_FLAGS) --root . \
		--module-path build/web-generated --define KRYON_HOSTED_UI --define SHOVEY_WEB --define SHOVEY_RELEASE \
		--bind editor_view:ReadAppUiHost=host:ReadAppUiHost --bind editor_view:AppLocaleHost=host:EditorLocaleHost \
		--bind editor_view:AppRecordHost=host:EditorRecordHost --bind editor_view:SaveAppRecordHost=host:EditorSaveRecordHost \
		--bind editor_view:AppKeyHost=host:GameKeyHost --bind editor_view:AppSoundHost=host:AppSoundHost \
		--bind editor_view:SmoothFramesHost=host:SmoothFramesHost --bind editor_view:AppSupportsHost=host:GameSupportsHost \
		--bind editor_view:AppServiceHost=controls:GameServiceHost --bind editor_view:AppFieldInputHost=host:GameFieldInputHost \
		--asset-dir assets=build/web-assets/assets --entry game:Main \
		-o build/web/shovey.zx src/web/game.zi
	python3 scripts/build_artifacts.py --ziran '$(ZIRAN)' profile --output build/web/entity.zx
	ZIRAN='$(TOOLCHAIN)/build/bin/ziran' python3 '$(ENTITY)/scripts/build-web.py' \
		--bundle build/web/shovey.zx --profile build/web/entity.zx --output build/web/runtime.html \
		--linked build/web/shovey.zx --linked build/web/entity.zx
	cp src/web/index.html build/web/index.html
	cp src/web/privacy.html build/web/privacy.html
	python3 scripts/stamp-web.py
	cp assets/shovey/preview.png build/web/loading.png
	cp assets/shovey/title-landscape.png assets/shovey/title-portrait.png assets/shovey/logo.png build/web/
	cp assets/branding/shovey-icon.png build/web/icon.png
	cp assets/branding/shovey-social.png build/web/og.png
	cp src/web/manifest.webmanifest src/web/_headers build/web/
	cp build/web/runtime.js build/web/index.js
	cp build/web/runtime.wasm build/web/index.wasm
	rm -f build/web/runtime.html build/web/runtime.js build/web/runtime.wasm


# The browser game compiled to WebAssembly: smooth on slow phones, where
# the interpreted ZX lagged. Kryon's canvas runner answers the app's
# context calls and keeps saves where the ZX player kept them, so players
# keep their progress. Entity supplies the shared Profile overlay and owns
# its account, referral and password services. `make web-zx` keeps the ZX
# edition available in the same output directory.
ZIRAN_BIN ?= $(TOOLCHAIN)/build/bin
EMCC ?= $(or $(wildcard $(HOME)/emsdk/upstream/emscripten/emcc),emcc)
WEB_OUT ?= build/web
WEB_NATIVE_OUT ?= build/web-native
web: bundles
	python3 scripts/prepare-web.py
	rm -rf $(WEB_OUT) $(WEB_NATIVE_OUT)
	mkdir -p $(WEB_OUT) $(WEB_NATIVE_OUT)/c
	'$(ZIRAN)' build --project $(LOCK_FLAGS) --target=c --module-path build/web-generated \
		--module-path src/web --module-path src/editor --module-path src/solver \
		--define PLATFORM_WEB --define BUNDLE_NATIVE_RENDERER --define SHOVEY_WEB --define SHOVEY_RELEASE \
		--entry web_profile_main:main --bind kryon/canvas_app_run:CanvasAppMain=game:Main \
		--bind editor_view:ReadAppUiHost=host:ReadAppUiHost --bind editor_view:AppLocaleHost=host:EditorLocaleHost \
		--bind editor_view:AppRecordHost=host:EditorRecordHost --bind editor_view:SaveAppRecordHost=host:EditorSaveRecordHost \
		--bind editor_view:AppKeyHost=host:GameKeyHost --bind editor_view:AppSoundHost=host:AppSoundHost \
		--bind editor_view:SmoothFramesHost=host:SmoothFramesHost --bind editor_view:AppSupportsHost=host:GameSupportsHost \
		--bind editor_view:AppServiceHost=controls:GameServiceHost --bind editor_view:AppFieldInputHost=host:GameFieldInputHost \
		-o $(WEB_NATIVE_OUT)/c '$(KRYON)/src/backend/canvas_app_run.zi' '$(KRYON)/src/backend/canvas_raster.zi' \
		src/web_profile_main.zi src/web/game.zi
	python3 scripts/build_artifacts.py --ziran '$(ZIRAN)' web-link --cc '$(EMCC)' \
		--include '$(TOOLCHAIN)/include' --generated $(WEB_NATIVE_OUT)/c \
		--assets build/web-assets/assets --output $(WEB_OUT)/index.js
	cp src/web/index.html $(WEB_OUT)/index.html
	cp src/web/privacy.html $(WEB_OUT)/privacy.html
	SHOVEY_WEB_OUT='$(WEB_OUT)' python3 scripts/stamp-web.py --deployed
	cp assets/shovey/preview.png $(WEB_OUT)/loading.png
	python3 scripts/build-site.py --pictures $(WEB_OUT)
	cp assets/branding/shovey-social.png $(WEB_OUT)/og.png
	cp src/web/manifest.webmanifest src/web/_headers $(WEB_OUT)/

web-itch: web

# CrazyGames Basic Launch: a self-contained relative-only ZIP made from the
# verified compiled web build, with index.html at the archive root.
CRAZYGAMES_OUT ?= work/crazygames.zip
web-crazygames: web
	'$(ZIRAN)' run --target=c scripts/package_crazygames.zi -- --output '$(CRAZYGAMES_OUT)'

package-crazygames-test:
	sh tests/package_crazygames_test.sh

web-test: web
	$(JS_RUNTIME) tests/web_mini_test.mjs
	$(JS_RUNTIME) tests/web_tap_beside_board_test.mjs
	$(JS_RUNTIME) tests/web_copy_test.mjs
	$(JS_RUNTIME) tests/web_live_campaign_test.mjs

# Requires Daochi's signed referral-fixture.test; all state and traffic stay local.
.PHONY: referral-web-test
referral-web-test: web
	$(JS_RUNTIME) tests/referral_web_test.mjs

# The profile and the live campaign run on the ZX player's web edition.
JS_RUNTIME ?= node
web-zx-test: web-zx
	$(JS_RUNTIME) tests/web_profile_test.mjs
	$(JS_RUNTIME) tests/web_live_campaign_test.mjs

previews:
	python3 tools/levels/levels.py previews

build/ziran/libziran.a:
	$(MAKE) -C '$(TOOLCHAIN)' BUILD_DIR='$(abspath build/ziran)' '$(abspath $@)'

solver: levels build/ziran/libziran.a
	ZIRAN_TOOLCHAIN='$(TOOLCHAIN)' sh tools/solver/build.sh

# The Ziran solver run natively over the story levels:
#   build/solver/shovey-bench [FIRST [LAST [BUDGET]]]
bench: levels build/ziran/libziran.a
	rm -rf build/solver/bench
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--entry bench:main -o build/solver/bench tools/solver/bench.zi
	$${CC:-cc} -std=c11 -O2 -ffunction-sections -fdata-sections -I'$(TOOLCHAIN)/include' \
		$$(find build/solver/bench -type d -printf ' -iquote %p') $$(find build/solver/bench -name '*.c') \
		build/ziran/libziran.a -Wl,--gc-sections -lm -lpthread -o build/solver/shovey-bench

# The checks the public repository can run with only the published campaign.
.PHONY: chest-fixture
chest-fixture: build/ziran/libziran.a
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--entry chest_fixture:main -o build/chest-test/c tests/chest_fixture.zi
	$${CC:-cc} -std=c11 -O1 -I'$(TOOLCHAIN)/include' \
		$$(find build/chest-test/c -type d -printf ' -iquote %p') \
		$$(find build/chest-test/c -name '*.c') build/ziran/libziran.a -lm -lpthread -o build/chest-test/fixture
	build/chest-test/fixture build/chest-test/fixture.txt

.PHONY: artifact-test artifact-provider-test
artifact-test:
	python3 tests/build_artifacts_test.py

artifact-provider-test:
	python3 tests/build_artifacts_test.py --providers --ziran '$(ZIRAN)'

.PHONY: game-maps-test
game-maps-test:
	python3 tests/game_maps_test.py

.PHONY: level-select-test
level-select-test:
	$(call ziran_test,level_select_focus_test)
	$(call ziran_test,world_map_view_test)

.PHONY: secret-results-test
secret-results-test:
	python3 tests/secret_results_test.py

public-test test: secret-results-test

.PHONY: collectibles-test
collectibles-test:
	sh tests/collectibles_test.sh

.PHONY: shop-test
shop-test: collectibles-test levels
	sh tests/daily_chest_test.sh
	sh tests/shop_state_test.sh
	sh tests/shop_view_test.sh
	sh tests/shop_host_test.sh
	sh tests/island_unlock_test.sh
	python3 tests/island_package_test.py
	python3 tests/island_catalog_test.py
	python3 tests/island_campaign_config_test.py
	python3 tests/island_live_delivery_test.py
	APPS_NODE_RELEASE='$(APPS)/scripts/node_release.py' python3 tests/island_publication_test.py

.PHONY: forest-puzzle-test
forest-puzzle-test: solver
	$(call ziran_test,forest_puzzle_test)
	python3 tests/forest_levels_test.py

official-update-test: levels
	$(call ziran_test,official_update_test)

public-test: hints-loading-test barrels-test solver laws game-maps-test level-select-test shop-test official-update-test forest-puzzle-test
	python3 tests/star_start_test.py
	python3 tests/editor_server_test.py
	python3 tests/campaign_publication_test.py
	$(call ziran_test,board_effects_test)
	sh tests/guide_test.sh '$(TOOLCHAIN)'
	python3 tests/hidden_levels_test.py
	sh tests/secret_travel_test.sh '$(TOOLCHAIN)'
	sh tests/rewards_test.sh '$(TOOLCHAIN)' '$(ENTITY)'
	sh tests/shared_progress_test.sh '$(TOOLCHAIN)'
	sh tests/completion_path_test.sh '$(TOOLCHAIN)'
	sh tests/level_replay_test.sh '$(TOOLCHAIN)'
	python3 tools/levels/levels.py generate --check
	python3 tools/levels/landscape.py --check
	python3 tests/levels_test.py
	python3 tests/classic_difficulty_test.py
	python3 tests/classic_63_65_68_test.py
	python3 tests/classic_73_74_test.py
	python3 tests/classic_variety_test.py
	python3 tests/assets_test.py

# Laws state policy independently of its implementation; `ziran check`
# proves each over its whole listed domain.
LAW_MODULES := $(wildcard src/*_laws.zi)
.PHONY: laws
laws:
	@for module in $(LAW_MODULES); do \
		'$(TOOLCHAIN)/build/bin/ziran' check --root src --module-path '$(TOOLCHAIN)/std' $$module > /dev/null || exit 1; \
	done
	@echo "Shovey laws proved: $(words $(LAW_MODULES)) modules"

# Level pictures are ignored generated assets, so a source-only checkout or
# an earlier custom --cell preview must be regenerated before asset validation.
test: hints-loading-test barrels-test solver laws game-maps-test shop-test forest-puzzle-test previews
	python3 tests/play_release_notes_test.py
	python3 tests/pages_packaging_test.py
	python3 tests/star_start_test.py
	python3 tests/editor_server_test.py
	python3 tests/campaign_publication_test.py
	python3 tests/build_artifacts_test.py
	$(call ziran_test,board_effects_test)
	sh tests/guide_test.sh '$(TOOLCHAIN)'
	python3 tests/hidden_levels_test.py
	sh tests/secret_travel_test.sh '$(TOOLCHAIN)'
	sh tests/rewards_test.sh '$(TOOLCHAIN)' '$(ENTITY)'
	python3 tools/levels/levels.py generate --check
	python3 tests/levels_test.py
	python3 tests/classic_difficulty_test.py
	python3 tests/classic_63_65_68_test.py
	python3 tests/classic_73_74_test.py
	python3 tests/classic_variety_test.py
	python3 tests/assets_test.py
	sh tests/editor_field_test.sh '$(TOOLCHAIN)'
	sh tests/editor_sharing_test.sh '$(TOOLCHAIN)'
	sh tests/engine_test.sh '$(TOOLCHAIN)' '$(ENTITY)'
	$(call ziran_test,solver_test)
	sh tests/controls_test.sh '$(TOOLCHAIN)'
	sh tests/shared_progress_test.sh '$(TOOLCHAIN)'
	sh tests/completion_path_test.sh '$(TOOLCHAIN)'
	sh tests/level_replay_test.sh '$(TOOLCHAIN)'
	$(MAKE) bundles

# A desktop player that records a winning route for each board it is given:
#   build/play/shovey-play LIST ROUTES [LEVELS]
play: levels build/ziran/libziran.a
	rm -rf build/play/c
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root tools/play \
		--module-path '$(KRYON)/src/ui' --module-path '$(KRYON)/src/backend' \
		--module-path 'mingcute=$(MINGCUTE)/src' \
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

# Dresses Classic levels with scenery that keeps every stored route winning:
#   build/levels/scenery [--levels DIR] [--no-generate] LEVEL...
scenery-tool: levels build/ziran/libziran.a
	rm -rf build/levels/scenery-c
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--entry scenery_tool:main -o build/levels/scenery-c tools/levels/scenery_tool.zi
	$${CC:-cc} -std=c11 -O2 -ffunction-sections -fdata-sections -I'$(TOOLCHAIN)/include' \
		$$(find build/levels/scenery-c -type d -printf ' -iquote %p') $$(find build/levels/scenery-c -name '*.c') \
		build/ziran/libziran.a -Wl,--gc-sections -lm -lpthread -o build/levels/scenery

# Keeps the shortest winning route found for each Classic level:
#   build/levels/shorten [--levels DIR] [--no-generate] [LEVEL...]
routes-tool: levels build/ziran/libziran.a
	rm -rf build/levels/routes-c
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--entry routes_tool:main -o build/levels/routes-c tools/levels/routes_tool.zi
	$${CC:-cc} -std=c11 -O2 -ffunction-sections -fdata-sections -I'$(TOOLCHAIN)/include' \
		$$(find build/levels/routes-c -type d -printf ' -iquote %p') $$(find build/levels/routes-c -name '*.c') \
		build/ziran/libziran.a -Wl,--gc-sections -lm -lpthread -o build/levels/shorten

# Before and after pictures of scenery, with the cells each route uses, drawn
# on a private display: make scenery-pictures SCENERY_LEVELS='1 2' writes
# build/scenery/level-NN.png.
SCENERY_LEVELS ?= 1
scenery-pictures: levels build/ziran/libziran.a
	rm -rf build/scenery/c
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path '$(KRYON)/src/ui' --module-path '$(KRYON)/src/backend' \
		--module-path 'mingcute=$(MINGCUTE)/src' \
		--module-path 'kryon=$(KRYON)/src/ui' --module-path 'kryon=$(KRYON)/src/backend' \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--entry scenery_picture:main -o build/scenery/c tools/levels/scenery_picture.zi
	$${CC:-cc} -std=c11 -O2 -ffunction-sections -fdata-sections -I'$(TOOLCHAIN)/include' \
		$$(find build/scenery/c -type d -printf ' -iquote %p') $$(find build/scenery/c -name '*.c') \
		build/ziran/libziran.a -Wl,--gc-sections \
		$$(pkg-config --libs sdl2 cairo freetype2 fontconfig pangocairo) -lm -lpthread -o build/scenery/scenery-picture
	for level in $(SCENERY_LEVELS); do \
		env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS YUE_DESKTOP_RECOVERY=0 \
			KRYON_CAPTURE_PATH="$(abspath build/scenery)/level-$$(printf %02d $$level).png" \
			xvfb-run -a -n 400 -s '-screen 0 1800x1100x24' build/scenery/scenery-picture $$level || exit 1; \
	done

# The Shovey Editor's card, drawn from both editions' pictures on a private
# display and written to assets/shovey-editor/preview.png.
editor-card: levels build/ziran/libziran.a
	rm -rf build/card/c
	'$(TOOLCHAIN)/build/bin/ziran' build --target=c --root . \
		--module-path '$(KRYON)/src/ui' --module-path '$(KRYON)/src/backend' \
		--module-path 'mingcute=$(MINGCUTE)/src' \
		--module-path 'kryon=$(KRYON)/src/ui' --module-path 'kryon=$(KRYON)/src/backend' \
		--module-path 'std=$(TOOLCHAIN)/std' --module-path '$(TOOLCHAIN)/std' \
		--entry editor_card:main -o build/card/c tools/pixel/editor_card.zi
	$${CC:-cc} -std=c11 -O2 -ffunction-sections -fdata-sections -I'$(TOOLCHAIN)/include' \
		$$(find build/card/c -type d -printf ' -iquote %p') $$(find build/card/c -name '*.c') \
		build/ziran/libziran.a -Wl,--gc-sections \
		$$(pkg-config --libs sdl2 cairo freetype2 fontconfig pangocairo) -lm -lpthread -o build/card/editor-card
	env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS YUE_DESKTOP_RECOVERY=0 \
		KRYON_CAPTURE_PATH='$(abspath assets/shovey-editor/preview.png)' xvfb-run -a -n 400 build/card/editor-card

.PHONY: barrels-test
barrels-test: solver
	$(call ziran_test,barrels_test)
	python3 tests/barrels_levels_test.py

# Repeatable continuous-map export from the joined v5 portrait and landscape sources.
.PHONY: world-map-tiles world-map-test
world-map-tiles:
	python3 scripts/tile_world_map.py

world-map-test:
	python3 tests/world_map_art_test.py
	sh tests/world_map_layout_test.sh
	sh tests/world_map_progression_test.sh
	$(MAKE) level-select-test

.PHONY: hints-loading-test
hints-loading-test: levels
	$(call ziran_test,hints_loading_test,,--define SHOVEY_RELEASE)
	'$(TOOLCHAIN)/build/bin/ziran' bundle --root tests $(ZIRAN_TEST_MODULES) --define SHOVEY_RELEASE --entry hints_loading_test:main -o build/tests/hints_loading_test.zx tests/hints_loading_test.zi
	test "$$('$(TOOLCHAIN)/build/bin/ziran' run build/tests/hints_loading_test.zx | tail -n 1)" = 0

.PHONY: island-collectible-book-test
island-collectible-book-test:
	@if test -f src/island/keepsake_book.zi; then $(MAKE) island-collectible-book-test-private; else echo "Private Island source unavailable; book test skipped"; fi

island-collectible-book-test-private:
	$(call ziran_test,island_collectible_book_test,,--bind-host island_collectible_book_test)
	'$(TOOLCHAIN)/build/bin/ziran' bundle --root tests $(ZIRAN_TEST_MODULES)  --bind-host island_collectible_book_test --entry island_collectible_book_test:main -o build/tests/island_collectible_book_test.zx tests/island_collectible_book_test.zi
	test "$$('$(TOOLCHAIN)/build/bin/ziran' run build/tests/island_collectible_book_test.zx | tail -n 1)" = 0

.PHONY: island-gameplay-test
island-gameplay-test:
	@if test -f src/island/island_engine.zi; then $(MAKE) island-gameplay-test-private; else echo "Private Island source unavailable; gameplay test skipped"; fi

island-gameplay-test-private:
	python3 scripts/island_campaign.py
	$(call ziran_test,island_gameplay_test,,--module-path src/island)
