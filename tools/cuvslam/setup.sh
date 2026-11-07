#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
experiment="$PWD/storage/experiments/cuvslam"
wheel="cuvslam-17.0.1+cu12-cp310-cp310-manylinux_2_35_x86_64.whl"
mkdir -p "$experiment/vendor"
if [[ ! -f "$experiment/vendor/$wheel" ]]; then
    curl --fail --location --retry 3 \
        "https://github.com/nvidia-isaac/cuVSLAM/releases/download/v17.0.1/${wheel/+/%2B}" \
        --output "$experiment/vendor/$wheel.download"
    mv "$experiment/vendor/$wheel.download" "$experiment/vendor/$wheel"
fi
echo "c4fac1e9f577c2bfe8160a9595ce8f8c8b44b98308344bffd991925821599cc1  $experiment/vendor/$wheel" | sha256sum --check
# This release wheel targets Ubuntu 22.04 / glibc >= 2.35 and CPython 3.10.
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/slam-uv-cache}" uv venv --python /usr/bin/python3.10 --allow-existing "$experiment/.venv"
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/slam-uv-cache}" uv pip install \
    --python "$experiment/.venv/bin/python" \
    --index https://pypi.nvidia.com --default-index https://pypi.org/simple \
    -r tools/cuvslam/requirements.txt "$experiment/vendor/$wheel"
