#!/usr/bin/env bash
set -euo pipefail

install_root=${QUICKOPS_INSTALL_ROOT:-/opt/quickops}
config_dir=${QUICKOPS_CONFIG_DIR:-/etc/quickops}
data_dir=${QUICKOPS_DATA_DIR:-/var/lib/quickops}
backup_dir=${QUICKOPS_BACKUP_DIR:-/var/backups/quickops}
service_name=${QUICKOPS_SERVICE_NAME:-quickops}
systemd_unit_dir=${QUICKOPS_SYSTEMD_UNIT_DIR:-/etc/systemd/system}
payload_dir=""
release_id=""
run_user=""
admin_user="admin"
admin_password=""
admin_password_file=""
port="8443"
non_interactive=false
allow_root_service=false
reset_credentials=false

usage() {
  echo "用法: sudo ./quickops-offline-installer.run [选项]"
  echo
  echo "选项:"
  echo "  --run-user USER            QuickOps 与终端使用的现有系统账户"
  echo "  --admin-user USER          网页登录账号（默认 admin）"
  echo "  --admin-password-file FILE 从仅 root 可读文件读取网页登录密码"
  echo "  --port PORT                HTTP 端口（默认 8443）"
  echo "  --non-interactive          禁用交互；首次安装需提供全部必要参数"
  echo "  --reset-credentials        升级时重新设置网页登录账号密码"
  echo "  --allow-root-service       明确允许 QuickOps 以 root 账户运行"
  echo "  --help                     显示帮助"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --payload-dir) payload_dir=${2:?}; shift 2 ;;
    --release-id) release_id=${2:?}; shift 2 ;;
    --run-user) run_user=${2:?}; shift 2 ;;
    --admin-user) admin_user=${2:?}; shift 2 ;;
    --admin-password-file) admin_password_file=${2:?}; shift 2 ;;
    --port) port=${2:?}; shift 2 ;;
    --non-interactive) non_interactive=true; shift ;;
    --reset-credentials) reset_credentials=true; shift ;;
    --allow-root-service) allow_root_service=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 sudo 或 root 运行安装器。" >&2
  exit 1
fi
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
  echo "此安装包仅支持 Linux x86_64。" >&2
  exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
  echo "目标系统必须使用 systemd。" >&2
  exit 1
fi
if [[ -z "$payload_dir" ]]; then
  payload_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fi
if [[ ! -x "$payload_dir/runtime/python/bin/python3" ]]; then
  echo "离线包缺少内置 Python 运行时。" >&2
  exit 1
fi
if [[ ! -d "$payload_dir/wheelhouse" || ! -d "$payload_dir/wheels" ]]; then
  echo "离线包缺少 Python wheelhouse。" >&2
  exit 1
fi
if [[ ! -f "$payload_dir/dist/client/index.html" ]]; then
  echo "离线包缺少已构建的前端资源。" >&2
  exit 1
fi

metadata_file="$config_dir/install.conf"
env_file="$config_dir/quickops.env"
existing_install=false
existing_run_user=""
existing_port=""
if [[ -f "$metadata_file" ]]; then
  existing_install=true
  existing_run_user=$(sed -n 's/^QUICKOPS_RUN_USER=//p' "$metadata_file" | head -1)
  existing_port=$(sed -n 's/^QUICKOPS_PORT=//p' "$metadata_file" | head -1)
fi
if [[ -z "$run_user" && -n "$existing_run_user" ]]; then run_user=$existing_run_user; fi
if [[ "$port" == "8443" && -n "$existing_port" ]]; then port=$existing_port; fi

default_login_user=""
if [[ -n ${SUDO_USER:-} && ${SUDO_USER} != root ]]; then
  default_login_user=$SUDO_USER
else
  default_login_user=$(getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 && $7 !~ /(nologin|false)$/ {print $1; exit}')
fi

if [[ -z "$run_user" ]]; then
  if $non_interactive; then
    echo "首次非交互安装必须提供 --run-user。" >&2
    exit 1
  fi
  read -r -p "QuickOps 运行账户 [${default_login_user:-请输入现有账户}]: " run_user
  run_user=${run_user:-$default_login_user}
fi
if ! id "$run_user" >/dev/null 2>&1; then
  echo "系统账户不存在: $run_user" >&2
  exit 1
fi
if [[ "$run_user" == root && "$allow_root_service" != true ]]; then
  echo "出于安全考虑，默认不允许 Web 服务以 root 运行。请指定普通运维账户。" >&2
  echo "确需使用 root 时显式添加 --allow-root-service。" >&2
  exit 1
fi
run_group=$(id -gn "$run_user")
target_home=$(getent passwd "$run_user" | awk -F: '{print $6}')
if [[ -z "$target_home" || ! -d "$target_home" ]]; then
  echo "运行账户没有可用的登录主目录: $run_user" >&2
  exit 1
fi
if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
  echo "端口必须是 1-65535 的整数。" >&2
  exit 1
fi

configure_credentials=true
if $existing_install && [[ -f "$env_file" ]] && ! $reset_credentials; then
  configure_credentials=false
fi
if $configure_credentials; then
  if [[ -n "$admin_password_file" ]]; then
    if [[ ! -f "$admin_password_file" ]]; then
      echo "密码文件不存在: $admin_password_file" >&2
      exit 1
    fi
    admin_password=$(<"$admin_password_file")
  elif [[ -n ${QUICKOPS_ADMIN_PASSWORD:-} ]]; then
    admin_password=$QUICKOPS_ADMIN_PASSWORD
  elif $non_interactive; then
    echo "首次非交互安装需使用 --admin-password-file 提供网页登录密码。" >&2
    exit 1
  else
    read -r -p "网页登录账号 [admin]: " entered_admin_user
    admin_user=${entered_admin_user:-admin}
    read -r -s -p "网页登录密码: " admin_password
    echo
    read -r -s -p "再次输入密码: " admin_password_confirm
    echo
    if [[ "$admin_password" != "$admin_password_confirm" ]]; then
      echo "两次输入的密码不一致。" >&2
      exit 1
    fi
  fi
  if [[ -z "$admin_user" || "$admin_user" == *$'\n'* ]]; then
    echo "网页登录账号不能为空或包含换行。" >&2
    exit 1
  fi
  if (( ${#admin_password} < 8 )) || [[ "$admin_password" == *$'\n'* ]]; then
    echo "网页登录密码至少需要 8 个字符且不能包含换行。" >&2
    exit 1
  fi
fi

if [[ -z "$release_id" ]]; then
  if [[ -f "$payload_dir/RELEASE_ID" ]]; then
    release_id=$(tr -cd 'A-Za-z0-9._-' < "$payload_dir/RELEASE_ID")
  fi
  release_id=${release_id:-$(date +%Y%m%d%H%M%S)}
fi
release_dir="$install_root/releases/$release_id"
previous_release=""
if [[ -L "$install_root/current" ]]; then
  previous_release=$(readlink -f "$install_root/current")
fi
if [[ -e "$release_dir" ]]; then
  echo "发布目录已存在: $release_dir" >&2
  exit 1
fi

echo ""
echo "正在安装 QuickOps："
echo "  运行账户: $run_user"
echo "  工作目录: $target_home"
echo "  HTTP 端口: $port"
echo "  发布版本: $release_id"

install -d -m 0755 "$install_root/releases"
install -d -o "$run_user" -g "$run_group" -m 0700 "$data_dir"
install -d -o root -g "$run_group" -m 0750 "$config_dir"
install -d -m 0700 "$backup_dir"

if [[ -f "$data_dir/quickops.db" ]]; then
  backup_file="$backup_dir/quickops-$(date +%Y%m%d%H%M%S).db"
  "$payload_dir/runtime/python/bin/python3" - "$data_dir/quickops.db" "$backup_file" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
target.close()
source.close()
PY
  chmod 0600 "$backup_file"
  echo "  数据备份: $backup_file"
fi

install -d -m 0755 "$release_dir"
cp -a "$payload_dir/dist" "$payload_dir/deploy" "$payload_dir/runtime" \
  "$payload_dir/wheelhouse" "$payload_dir/wheels" "$release_dir/"
chown -R root:root "$release_dir"
chmod 0755 "$release_dir" "$release_dir/runtime/python/bin/python3"

echo "  安装离线依赖（不会访问外网）..."
PIP_ROOT_USER_ACTION=ignore "$release_dir/runtime/python/bin/python3" -m pip install \
  --disable-pip-version-check \
  --no-index \
  --find-links "$release_dir/wheelhouse" \
  --upgrade \
  "$release_dir"/wheels/*.whl >/dev/null

escape_env_value() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  printf '%s' "$value"
}

if $configure_credentials; then
  umask 0077
  {
    printf 'QUICKOPS_AUTH_USERNAME="%s"\n' "$(escape_env_value "$admin_user")"
    printf 'QUICKOPS_AUTH_PASSWORD="%s"\n' "$(escape_env_value "$admin_password")"
    printf 'QUICKOPS_AUTH_SESSION_TTL_HOURS=12\n'
    printf 'QUICKOPS_DB_FILE=%s/quickops.db\n' "$data_dir"
    printf 'QUICKOPS_WORKSPACE_ROOT="%s"\n' "$(escape_env_value "$target_home")"
    printf 'QUICKOPS_STATIC_DIR=%s/dist/client\n' "$install_root/current"
    printf 'SILICONFLOW_API_KEY=\n'
    printf 'MODEL_ID=deepseek-ai/DeepSeek-V4-Flash\n'
    printf 'MODEL_BASE_URL=https://api.siliconflow.cn/v1\n'
    printf 'MODEL_PROVIDER=SiliconFlow\n'
    printf 'THINKING_MODE=auto\n'
    printf 'MAX_CONTEXT_TOKENS=128000\n'
  } > "$env_file"
else
  "$release_dir/runtime/python/bin/python3" - \
    "$env_file" "$target_home" "$data_dir/quickops.db" "$install_root/current/dist/client" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
updates = {
    "QUICKOPS_DB_FILE": sys.argv[3],
    "QUICKOPS_WORKSPACE_ROOT": sys.argv[2],
    "QUICKOPS_STATIC_DIR": sys.argv[4],
}
lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
result = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
    if key in updates:
        result.append(f'{key}="{updates[key].replace(chr(34), chr(92) + chr(34))}"')
        seen.add(key)
    else:
        result.append(line)
for key, value in updates.items():
    if key not in seen:
        result.append(f'{key}="{value}"')
path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY
fi
chown root:"$run_group" "$env_file"
chmod 0640 "$env_file"

{
  printf 'QUICKOPS_RUN_USER=%s\n' "$run_user"
  printf 'QUICKOPS_PORT=%s\n' "$port"
} > "$metadata_file"
chown root:root "$metadata_file"
chmod 0600 "$metadata_file"

unit_file="$systemd_unit_dir/$service_name.service"
install -d -m 0755 "$systemd_unit_dir"
unit_backup=""
if [[ -f "$unit_file" ]]; then
  unit_backup=$(mktemp /tmp/quickops-unit.XXXXXX)
  cp -a "$unit_file" "$unit_backup"
fi
cat > "$unit_file" <<EOF
[Unit]
Description=QuickOps Harness Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$run_user
Group=$run_group
WorkingDirectory=$install_root/current
EnvironmentFile=$env_file
ExecStart=$install_root/current/runtime/python/bin/uvicorn quickops.api:app --host 0.0.0.0 --port $port --workers 1
Restart=on-failure
RestartSec=3
TimeoutStartSec=180
TimeoutStopSec=20
KillMode=control-group
UMask=0077
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$unit_file"

ln -sfn "$release_dir" "$install_root/current"
systemctl daemon-reload
systemctl enable "$service_name" >/dev/null

start_ok=true
if ! systemctl restart "$service_name"; then start_ok=false; fi
if $start_ok; then
  if ! "$release_dir/runtime/python/bin/python3" - "$port" <<'PY'
import json
import sys
import time
import urllib.request

url = f"http://127.0.0.1:{sys.argv[1]}/api/quickops/health"
for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            payload = json.load(response)
        if payload.get("status") == "ok":
            raise SystemExit(0)
    except Exception:
        time.sleep(1)
raise SystemExit(1)
PY
  then
    start_ok=false
  fi
fi

if ! $start_ok; then
  echo "QuickOps 启动失败，正在恢复上一版本。" >&2
  if [[ -n "$previous_release" && -d "$previous_release" ]]; then
    ln -sfn "$previous_release" "$install_root/current"
  else
    rm -f "$install_root/current"
  fi
  if [[ -n "$unit_backup" && -f "$unit_backup" ]]; then
    cp -a "$unit_backup" "$unit_file"
  fi
  systemctl daemon-reload
  if [[ -n "$previous_release" ]]; then systemctl restart "$service_name" || true; fi
  journalctl -u "$service_name" -n 30 --no-pager >&2 || true
  exit 1
fi
if [[ -n "$unit_backup" && -f "$unit_backup" ]]; then rm -f "$unit_backup"; fi

host_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
host_ip=${host_ip:-127.0.0.1}
echo
echo "QuickOps 安装成功"
echo "访问地址：http://$host_ip:$port"
if $configure_credentials; then echo "登录账号：$admin_user"; fi
echo "模型配置：登录后进入 设置 → 模型配置"
echo "服务状态：systemctl status $service_name"
