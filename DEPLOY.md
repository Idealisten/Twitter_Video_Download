# 可复用 Docker 部署

推荐把项目放到 GitHub，然后由 GitHub Actions 自动构建并推送镜像到 GHCR。之后换任何服务器，都不需要再传项目源码，只要拉镜像运行。

## 一次性发布镜像

1. 在 GitHub 新建仓库，例如 `twitter-video-download`。
2. 把本项目推到仓库的 `main` 分支。
3. GitHub Actions 会自动构建多架构镜像并推送到：

   ```text
   ghcr.io/idealisten/twitter-video-download:latest
   ```

如果 GHCR 包默认是私有的，到 GitHub 仓库页面进入 `Packages`，把这个 package 改成 Public，服务器才能免登录拉取。

## 任意服务器部署

服务器只需要 Docker 和 Docker Compose。

新建目录：

```bash
mkdir -p /opt/twitter-video-download
cd /opt/twitter-video-download
```

创建 `compose.yaml`：

```yaml
services:
  twitter-video-download:
    image: ghcr.io/idealisten/twitter-video-download:latest
    container_name: twitter-video-download
    restart: unless-stopped
    ports:
      - "127.0.0.1:8001:8000"
    environment:
      RESULT_TTL_SECONDS: 1800
      MAX_DOWNLOAD_BYTES: 1073741824
      REQUEST_TIMEOUT: 20
    volumes:
      - twitter-video-download-cache:/tmp/twitter-video-download

volumes:
  twitter-video-download-cache:
```

启动：

```bash
docker compose up -d
```

访问：

```text
http://127.0.0.1:8001
```

服务器通过 Cloudflare Tunnel 暴露后，快捷指令接口地址应使用你的 HTTPS 域名：

```text
https://xvideo.example.com/api/shortcut?url=编码后的URL
```

源站端口只绑定到 `127.0.0.1`，避免被公网扫描占满 Gunicorn 工作线程。systemd 版 cloudflared 的 Service URL 填 `http://127.0.0.1:8001`；如果 cloudflared 和本服务在同一个 Compose 网络中，则填 `http://twitter-video-download:8000`。

## 更新服务

以后你只需要在 GitHub 更新代码，Actions 构建完镜像后，服务器执行：

```bash
cd /opt/twitter-video-download
docker compose pull
docker compose up -d
```

## 一行部署方式

如果不想手写 `compose.yaml`，可以把本仓库公开后，在服务器执行：

```bash
mkdir -p /opt/twitter-video-download && cd /opt/twitter-video-download
curl -fsSL https://raw.githubusercontent.com/Idealisten/Twitter_Video_Download/main/compose.yaml -o compose.yaml
curl -fsSL https://raw.githubusercontent.com/Idealisten/Twitter_Video_Download/main/.env.example -o .env
docker compose up -d
```

macOS 的 `sed` 和 Linux 不一样；这条一行部署命令是给 Linux 服务器用的。

## HTTPS 建议

公网服务器建议用 Caddy 或 Nginx 反代到 `127.0.0.1:8001`，并开启 HTTPS。iPhone 快捷指令在 HTTPS 下更稳定，也更安全。
