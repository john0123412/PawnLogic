#!/usr/bin/env bash
# Verify a published PawnLogic distribution by installing it from an index.
#
# This is the post-upload gate. Uploading is not evidence that users can
# install: the index may serve an older file, the console script may be
# missing, or the reported version may not match. Each of those fails here.
#
# The served wheel is compared against the hash of the wheel the release run
# actually built, so `skip-existing` cannot leave a stale artifact in place
# and still report a green publish.
#
# Required environment:
#   EXPECTED_VERSION  version string that must be installed, without a leading v
#   EXPECTED_WHEEL    wheel filename the release run built
#   EXPECTED_SHA256   sha256 of the wheel the release run built
#   INDEX_URL         index to install from
#
# Optional environment:
#   SMOKE_ATTEMPTS    download attempts before failing (default 6)
#   SMOKE_SLEEP       seconds between attempts (default 20)

set -euo pipefail

for var in EXPECTED_VERSION EXPECTED_WHEEL EXPECTED_SHA256 INDEX_URL; do
    if [ -z "${!var:-}" ]; then
        echo "release_install_smoke: $var is required" >&2
        exit 2
    fi
done

attempts="${SMOKE_ATTEMPTS:-6}"
sleep_seconds="${SMOKE_SLEEP:-20}"

workdir="$(mktemp -d)"
cleanup() { rm -rf "$workdir"; }
trap cleanup EXIT

venv="$workdir/venv"
download="$workdir/download"
runtime_home="$workdir/home"
mkdir -p "$download" "$runtime_home"

python3 -m venv "$venv"

pip_download() {
    "$venv/bin/pip" download --no-deps --no-cache-dir \
        --only-binary :all: \
        --index-url "$INDEX_URL" \
        --extra-index-url https://pypi.org/simple/ \
        --dest "$download" \
        "pawnlogic==${EXPECTED_VERSION}"
}

# A freshly uploaded file is not always served immediately.
downloaded=0
for attempt in $(seq 1 "$attempts"); do
    if pip_download; then
        downloaded=1
        break
    fi
    echo "Download attempt ${attempt}/${attempts} failed; the index may lag."
    sleep "$sleep_seconds"
done

if [ "$downloaded" -ne 1 ]; then
    echo "Could not download pawnlogic==${EXPECTED_VERSION} from ${INDEX_URL}." >&2
    exit 1
fi

served_wheel="$download/$EXPECTED_WHEEL"
if [ ! -f "$served_wheel" ]; then
    echo "Index did not serve ${EXPECTED_WHEEL}." >&2
    ls -la "$download" >&2
    exit 1
fi

served_sha="$(sha256sum "$served_wheel" | cut -d' ' -f1)"
if [ "$served_sha" != "$EXPECTED_SHA256" ]; then
    echo "Served wheel differs from the wheel this run built." >&2
    echo "  built:  ${EXPECTED_SHA256}" >&2
    echo "  served: ${served_sha}" >&2
    exit 1
fi
echo "Served wheel matches the wheel this run built."

# Install the exact wheel whose index identity was just verified. Dependencies
# still resolve from the configured index pair.
"$venv/bin/pip" install --no-cache-dir \
    --index-url "$INDEX_URL" \
    --extra-index-url https://pypi.org/simple/ \
    "$served_wheel"

reported="$("$venv/bin/python" -c \
    'import importlib.metadata as m; print(m.version("pawnlogic"))')"
if [ "$reported" != "$EXPECTED_VERSION" ]; then
    echo "Installed version ${reported} does not match ${EXPECTED_VERSION}." >&2
    exit 1
fi
echo "Installed distribution reports ${reported}."

# The console script must run from a clean runtime home without a real key.
help_output="$workdir/help.txt"
PAWNLOGIC_HOME="$runtime_home" \
PAWNLOGIC_TEST_MODE=true \
MCP_ENABLED=false \
PROMPT_TOOLKIT_ENABLED=0 \
TERM=dumb \
NO_COLOR=1 \
    "$venv/bin/pawn" --help > "$help_output"

if ! grep -q -- "--debug" "$help_output"; then
    echo "pawn --help did not include the expected --debug option." >&2
    cat "$help_output" >&2
    exit 1
fi
echo "Installed pawn --help responded as expected."

echo "Release install smoke passed for pawnlogic==${EXPECTED_VERSION}."
