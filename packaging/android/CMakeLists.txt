# Shovey's Android player (scripts/player.py android copies this file over
# the droid/app/src/main/cpp/CMakeLists.txt Kryon's scaffold makes): the
# host in src/app.zi with Entity's native account cryptography.
cmake_minimum_required(VERSION 3.22)
project(Shovey C)

get_filename_component(REPO_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../.." ABSOLUTE)
if(NOT DEFINED KRYON_DIR OR NOT DEFINED ZIRAN_DIR)
    message(FATAL_ERROR
        "kryon build --profile android passes -DKRYON_DIR, -DZIRAN_DIR; a manual gradle run passes them as -P properties")
endif()
get_filename_component(KRYON_DIR "${KRYON_DIR}" ABSOLUTE BASE_DIR "${REPO_ROOT}")
get_filename_component(ZIRAN_DIR "${ZIRAN_DIR}" ABSOLUTE BASE_DIR "${REPO_ROOT}")
include("${KRYON_DIR}/cmake/KryonAndroid.cmake")

find_program(HOST_PYTHON NAMES python3 REQUIRED)

set(ZIRAN_BIN "${ZIRAN_DIR}/build/bin/ziran")
set(ZI2C_BIN "${ZIRAN_DIR}/build/bin/zi2c")
if(NOT EXISTS "${ZIRAN_BIN}" OR NOT EXISTS "${ZI2C_BIN}")
    message(FATAL_ERROR
        "The pinned Ziran toolchain in ${ZIRAN_DIR} is not built; "
        "run kryon build --profile android, which builds it first")
endif()

set(APP_ZIRAN_DEFINES --define ANDROID_BUILD)
# The app's edition (build.gradle app.edition): Google Play or F-Droid.
if(NOT APP_EDITION)
    set(APP_EDITION direct)
endif()
if(APP_EDITION STREQUAL "gplay")
    list(APPEND APP_ZIRAN_DEFINES --define GOOGLE_PLAY)
elseif(APP_EDITION STREQUAL "fdroid")
    list(APPEND APP_ZIRAN_DEFINES --define FDROID)
endif()
if(NOT DEFINED APP_CODEGEN)
    set(APP_CODEGEN c99)
endif()
if(ANDROID_ABI STREQUAL "arm64-v8a")
    set(APP_ZIRAN_ARCH __aarch64__)
elseif(ANDROID_ABI STREQUAL "armeabi-v7a")
    set(APP_ZIRAN_ARCH __arm__)
elseif(ANDROID_ABI STREQUAL "x86_64")
    set(APP_ZIRAN_ARCH __x86_64__)
elseif(ANDROID_ABI STREQUAL "x86")
    set(APP_ZIRAN_ARCH __i386__)
else()
    message(FATAL_ERROR "Unsupported Android ABI: ${ANDROID_ABI}")
endif()
list(APPEND APP_ZIRAN_DEFINES --define ${APP_ZIRAN_ARCH})

set(APP_ZIRAN_IR_DIR "${CMAKE_BINARY_DIR}/ziran/ir")
set(APP_ZIRAN_GEN_DIR "${CMAKE_BINARY_DIR}/ziran/generated")
set(APP_ZIRAN_MANIFEST "${CMAKE_BINARY_DIR}/ziran/generated-sources.cmake")
file(GLOB_RECURSE APP_ZIRAN_SOURCES CONFIGURE_DEPENDS "${REPO_ROOT}/src/*.zi")
file(GLOB_RECURSE APP_LIBRARY_ZIRAN_SOURCES CONFIGURE_DEPENDS
    "${KRYON_DIR}/src/ui/*.zi" "${KRYON_DIR}/src/backend/*.zi"
    "${ZIRAN_DIR}/std/*.zi")
execute_process(COMMAND "${HOST_PYTHON}"
    "${KRYON_DIR}/scripts/generate_android_sources.py"
    --ziran "${ZIRAN_BIN}" --zi2c "${ZI2C_BIN}"
    --root "${REPO_ROOT}" --kryon "${KRYON_DIR}"
    --ir "${APP_ZIRAN_IR_DIR}" --output "${APP_ZIRAN_GEN_DIR}"
    --manifest "${APP_ZIRAN_MANIFEST}" ${APP_ZIRAN_DEFINES}
    --codegen "${APP_CODEGEN}"
    WORKING_DIRECTORY "${REPO_ROOT}" COMMAND_ERROR_IS_FATAL ANY)
include("${APP_ZIRAN_MANIFEST}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    ${APP_ZIRAN_SOURCES} ${APP_LIBRARY_ZIRAN_SOURCES}
    "${REPO_ROOT}/ziran.toml" "${REPO_ROOT}/ziran.lock"
    "${REPO_ROOT}/scripts/build_artifacts.py")

# Foreign renderer and account support are owned by their locked providers.
# Shovey's Entity/Kryon Ziran modules above remain ordinary imports, once.
set(SHOVEY_ARTIFACT_EDITION "${APP_EDITION}")
if(APP_EDITION STREQUAL "gplay")
    set(SHOVEY_ARTIFACT_EDITION play)
endif()
set(SHOVEY_ARTIFACT_CONFIG "${CMAKE_BINARY_DIR}/shovey-artifacts.cmake")
execute_process(COMMAND "${HOST_PYTHON}" "${REPO_ROOT}/scripts/build_artifacts.py"
    --ziran "${ZIRAN_BIN}" android-config
    --ndk "${ANDROID_NDK}" --abi "${ANDROID_ABI}" --api "${ANDROID_NATIVE_API_LEVEL}"
    --edition "${SHOVEY_ARTIFACT_EDITION}" --output "${SHOVEY_ARTIFACT_CONFIG}"
    WORKING_DIRECTORY "${REPO_ROOT}" COMMAND_ERROR_IS_FATAL ANY)
include("${SHOVEY_ARTIFACT_CONFIG}")
add_library(raylib INTERFACE)
target_link_libraries(raylib INTERFACE ${SHOVEY_RENDERER_LINK})
target_compile_options(raylib INTERFACE ${SHOVEY_RENDERER_COMPILE})
target_compile_definitions(raylib INTERFACE ${SHOVEY_RENDERER_DEFINES})
target_include_directories(raylib INTERFACE ${SHOVEY_RENDERER_INCLUDES})
add_library(main SHARED ${APP_ZIRAN_GENERATED_SOURCES})
kryon_android_app(main)
kryon_android_host(main ${APP_ZIRAN_GENERATED_SOURCES})
# Keep independently built APKs identical after their debug symbols are stripped.
target_link_options(main PRIVATE -Wl,--build-id=none)

target_include_directories(main PRIVATE "${ZIRAN_DIR}/include")
# Generated module names such as math.h must not shadow libc's <math.h> in
# raylib and other native dependencies. Zi imports use quoted includes.
foreach(directory ${APP_ZIRAN_INCLUDE_DIRS})
    target_compile_options(main PRIVATE "-iquote${directory}")
endforeach()

target_link_libraries(main ${SHOVEY_CRYPTO_LINK})
