# QuickOps Linux x86_64 一键离线部署

交付文件只有一个：

```text
quickops-linux-x86_64-offline-<date>.run
```

安装包内含 QuickOps 前后端、Linux x86_64 Python 3.12 运行时和完整 wheelhouse。
安装、升级和启动都不会访问 PyPI、系统软件源或其他外网资源，也不依赖 Nginx、
系统 Python、pip、venv 或 Docker。目标机只需具备 Linux x86_64、glibc、systemd、
tar、awk、sed、sha256sum 等基础系统工具。

## 首次安装

把文件复制到目标服务器后执行：

```bash
chmod +x quickops-linux-x86_64-offline-20260813.run
sudo ./quickops-linux-x86_64-offline-20260813.run
```

安装器只会询问：

1. QuickOps 使用的现有系统账户。该账户也是会话终端和小维操作主机时的系统身份。
2. 网页登录账号，默认 `admin`。
3. 网页登录密码。
4. HTTP 端口，默认 `8443`。

完成后安装器会打印实际访问地址。模型不属于启动必填项；服务可在没有模型密钥时启动，
登录后到 `设置 → 模型配置` 添加模型即可。

## 无人值守安装

密码不要直接写在命令行参数中。先准备一个仅 root 可读的密码文件：

```bash
sudo chmod 600 /root/quickops-admin.password
sudo ./quickops-linux-x86_64-offline-20260813.run \
  --run-user ops \
  --admin-user admin \
  --admin-password-file /root/quickops-admin.password \
  --port 8443 \
  --non-interactive
```

## 升级

直接执行新版本安装包：

```bash
sudo ./quickops-linux-x86_64-offline-<new-date>.run
```

安装器会识别现有安装，保留网页登录配置、SQLite 数据、模型配置和设置；切换版本前会使用
SQLite 在线备份 API 将数据库备份到 `/var/backups/quickops/`。新版本健康检查失败时会恢复
先前的版本链接和 systemd 单元。

## 默认布局

- `/opt/quickops/releases/<release>`：不可变发布版本及其内置 Python
- `/opt/quickops/current`：当前版本软链接
- `/var/lib/quickops/quickops.db`：SQLite 数据库
- `/var/lib/quickops/attachments/`：会话附件
- `/etc/quickops/quickops.env`：仅 root 和运行账户可读的服务配置
- `/etc/quickops/install.conf`：安装元数据
- `/var/backups/quickops/`：升级前数据库备份
- `/etc/systemd/system/quickops.service`：服务单元

QuickOps 直接在所选 HTTP 端口提供前端、API 和流式事件，不会安装、停止或修改 Nginx，
也不会占用或覆盖现有 80/443 入口。若服务器启用了防火墙，需要由管理员放行所选端口。

## 常用运维命令

```bash
systemctl status quickops
journalctl -u quickops -f
systemctl restart quickops
```

运行账户必须是已经存在且拥有可用登录主目录的系统账户。安装器默认拒绝让 Web 服务以 root
运行；确有需求时必须显式传入 `--run-user root --allow-root-service`。
