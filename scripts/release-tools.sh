#!/usr/bin/env bash
# Extract signed distribution packages inside the job; no root or sudo required.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
tools="$PWD/build/release-tools"
mkdir -p "$tools"/{lists/partial,archives/partial,log,root,bin}
apt_options=(
    -o "Dir::State::lists=$tools/lists"
    -o "Dir::Cache::archives=$tools/archives"
    -o "Dir::Log=$tools/log"
    -o Dir::Etc::main=-
    -o Dir::Etc::parts=-
    -o Debug::NoLocking=true
)
apt-get "${apt_options[@]}" update
# The dependency solver retains installed libraries and downloads missing ones.
apt-get "${apt_options[@]}" --download-only --no-install-recommends -y install \
    apksigner libapksig-java aapt apksigcopier default-jre-headless
# Also download the tools themselves when they already exist on the host.
(cd "$tools/archives" && apt-get "${apt_options[@]}" download \
    apksigner libapksig-java aapt apksigcopier)
for package in "$tools"/archives/*.deb; do
    dpkg-deb --extract "$package" "$tools/root"
done
java_bin=$(command -v java || true)
if [[ -z $java_bin ]]; then
    java_bin=$(find "$tools/root/usr/lib/jvm" -path '*/bin/java' -type f -print -quit)
fi
test -n "$java_bin"
cat > "$tools/bin/apksigner" <<EOF
#!/bin/bash
exec "$java_bin" -Xmx256m -cp "$tools/root/usr/share/java/*" com.android.apksigner.ApkSignerTool "\$@"
EOF
cat > "$tools/bin/apksigcopier" <<EOF
#!/bin/bash
exec python3 "$tools/root/usr/bin/apksigcopier" "\$@"
EOF
chmod +x "$tools/bin/apksigner" "$tools/bin/apksigcopier"
export PATH="$tools/bin:$tools/root/usr/bin:$PATH"
export PYTHONPATH="$tools/root/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
# Android's backtrace library also loads 7zip from its own library directory.
# Package extraction does not run ldconfig, so include every extracted library.
library_dirs=$(find "$tools/root" -type f -name '*.so*' -printf '%h\n' | sort -u | paste -sd:)
export LD_LIBRARY_PATH="$library_dirs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
apksigner version
aapt version
apksigcopier --version
if [[ -n ${GITHUB_ENV:-} ]]; then
    printf '%s\n' "PATH=$PATH" "PYTHONPATH=$PYTHONPATH" "LD_LIBRARY_PATH=$LD_LIBRARY_PATH" >> "$GITHUB_ENV"
fi
