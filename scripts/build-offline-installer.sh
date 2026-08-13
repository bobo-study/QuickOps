#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
runtime_archive=""
wheelhouse=""
app_wheel=""
output="$project_root/artifacts/quickops-linux-x86_64-offline.run"
release_id="$(date +%Y%m%d%H%M%S)"

usage() {
  echo "用法: scripts/build-offline-installer.sh --runtime-archive FILE --wheelhouse DIR --app-wheel FILE [--output FILE] [--release-id ID]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-archive) runtime_archive=${2:?}; shift 2 ;;
    --wheelhouse) wheelhouse=${2:?}; shift 2 ;;
    --app-wheel) app_wheel=${2:?}; shift 2 ;;
    --output) output=${2:?}; shift 2 ;;
    --release-id) release_id=${2:?}; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for required in "$runtime_archive" "$app_wheel"; do
  if [[ -z "$required" || ! -f "$required" ]]; then
    echo "缺少文件: ${required:-未指定}" >&2
    exit 1
  fi
done
if [[ -z "$wheelhouse" || ! -d "$wheelhouse" ]]; then
  echo "缺少 wheelhouse 目录。" >&2
  exit 1
fi
if [[ ! -f "$project_root/dist/client/index.html" ]]; then
  echo "请先运行 npm run build。" >&2
  exit 1
fi

stage=$(mktemp -d /tmp/quickops-offline-stage.XXXXXX)
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT INT TERM
mkdir -p "$stage/deploy" "$stage/dist" "$stage/runtime" "$stage/wheels" "$stage/wheelhouse"
cp -a "$project_root/dist/client" "$stage/dist/client"
install -m 0755 "$project_root/deploy/install-quickops.sh" "$stage/deploy/install-quickops.sh"
cp -a "$wheelhouse"/. "$stage/wheelhouse/"
cp -a "$app_wheel" "$stage/wheels/"
printf '%s\n' "$release_id" > "$stage/RELEASE_ID"

tar -xzf "$runtime_archive" -C "$stage/runtime"
if [[ -d "$stage/runtime/python" ]]; then
  true
elif [[ -d "$stage/runtime"/*/python ]]; then
  runtime_parent=$(find "$stage/runtime" -mindepth 1 -maxdepth 1 -type d | head -1)
  mv "$runtime_parent/python" "$stage/runtime/python"
  rmdir "$runtime_parent" 2>/dev/null || true
else
  echo "Python 运行时压缩包结构不受支持。" >&2
  exit 1
fi
if [[ ! -x "$stage/runtime/python/bin/python3" ]]; then
  echo "Python 运行时缺少 bin/python3。" >&2
  exit 1
fi

payload="$stage/payload.tar.gz"
if command -v xattr >/dev/null 2>&1; then xattr -cr "$stage"; fi
COPYFILE_DISABLE=1 tar --no-xattrs -czf "$payload" -C "$stage" \
  RELEASE_ID deploy dist runtime wheelhouse wheels
payload_sha=$(sha256sum "$payload" | awk '{print $1}')
mkdir -p "$(dirname "$output")"
sed "s/__ARCHIVE_SHA256__/$payload_sha/" \
  "$project_root/deploy/quickops-offline-installer.stub" > "$output"
cat "$payload" >> "$output"
chmod +x "$output"

echo "$output"
sha256sum "$output"
