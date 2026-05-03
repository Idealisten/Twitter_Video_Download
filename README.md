# Twitter/X 视频下载网站

一个 Python + Flask 小站：输入 Twitter/X 视频推文链接，服务端会按顺序自动尝试多个解析来源，成功后列出可下载的 MP4 分辨率和文件大小，用户点击对应分辨率即可下载。

## 解析来源

当前内置 4 层 fallback：

1. `yt-dlp` 默认 Twitter/X extractor
2. `yt-dlp` 的 `twitter:api=syndication` 模式
3. `gallery-dl -g` 直链解析
4. 内置 `cdn.syndication.twimg.com/tweet-result` JSON 解析

任一来源解析成功就会返回结果；页面里的「查看解析源状态」可以看到每个来源的耗时和错误信息。

## 本地运行

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
HOST=0.0.0.0 PORT=8000 python app.py
```

浏览器打开：

```text
http://127.0.0.1:8000
```

如果 `8000` 被占用，可以改用：

```bash
HOST=0.0.0.0 PORT=8001 python app.py
```

然后打开 `http://127.0.0.1:8001`。

如果部署给手机访问，把 `127.0.0.1` 换成电脑在局域网里的 IP，例如 `http://192.168.1.8:8000`。

## Docker 版本

构建镜像：

```bash
docker build -t twitter-video-download .
```

运行容器：

```bash
docker run --rm -p 8000:8000 --name twitter-video-download twitter-video-download
```

后台运行：

```bash
docker run -d -p 8000:8000 --name twitter-video-download twitter-video-download
```

如果宿主机的 `8000` 被占用，可以用 `docker run --rm -p 8001:8000 --name twitter-video-download twitter-video-download`，然后访问 `http://127.0.0.1:8001`。

如果要在多台服务器复用部署，不建议每次 scp 源码。推荐把镜像发布到 GHCR 或 Docker Hub，然后服务器只执行 `docker compose pull && docker compose up -d`。详见 [DEPLOY.md](DEPLOY.md)。

## 服务端部署和更新

本仓库已经配置 GitHub Actions：代码推送到 `main` 分支后，会自动构建并发布 Docker 镜像到 GHCR。

当前镜像地址：

```text
ghcr.io/idealisten/twitter-video-download:latest
```

触发自动构建的情况：

- 推送代码到 `main`
- 推送 `v*` tag，例如 `v1.0.0`
- 在 GitHub Actions 页面手动运行 `Docker Publish`

第一次部署服务器：

```bash
mkdir -p /opt/twitter-video-download
cd /opt/twitter-video-download
curl -fsSL https://raw.githubusercontent.com/Idealisten/Twitter_Video_Download/main/compose.yaml -o compose.yaml
curl -fsSL https://raw.githubusercontent.com/Idealisten/Twitter_Video_Download/main/.env.example -o .env
docker compose up -d
```

也可以使用自动端口部署脚本。脚本会从 `.env` 里的 `HOST_PORT` 开始检查；如果端口已被占用，会自动尝试下一个端口，并把最终端口写回 `.env`：

```bash
mkdir -p /opt/twitter-video-download
cd /opt/twitter-video-download
curl -fsSL https://raw.githubusercontent.com/Idealisten/Twitter_Video_Download/main/scripts/deploy.sh -o deploy.sh
chmod +x deploy.sh
./deploy.sh
```

指定从某个端口开始尝试：

```bash
HOST_PORT=8010 ./deploy.sh
```

如果端口是当前 `twitter-video-download` 容器自己占用的，脚本会继续沿用该端口；只有被其它进程或其它容器占用时才会递增。

服务器部署完成后，正式访问建议使用 Cloudflare Tunnel 绑定的 HTTPS 域名，而不是服务器 IP：

```text
https://xvideo.example.com
```

`http://服务器IP:最终HOST_PORT` 只建议用于服务器防火墙内或临时排查。

代码更新后的服务器更新流程：

```bash
cd /opt/twitter-video-download
docker compose pull
docker compose up -d
```

如果希望更新时也自动避开已占用端口，继续使用部署脚本：

```bash
cd /opt/twitter-video-download
./deploy.sh
```

如果要看服务状态和日志：

```bash
docker compose ps
docker compose logs -f twitter-video-download
```

如果要修改端口，编辑 `.env`：

```text
HOST_PORT=8001
```

然后执行：

```bash
docker compose up -d
```

## Cloudflare Tunnel 暴露公网

推荐使用 Cloudflare 的 remotely-managed Tunnel：Tunnel 配置放在 Cloudflare Dashboard，服务器只保存一个 token。官方文档也推荐大多数场景使用 remotely-managed Tunnel。

前提：

- 域名已经托管到 Cloudflare
- 服务器已经按上一节启动了服务
- 本地服务在服务器内可通过 `http://twitter-video-download:8000` 访问

### 1. 在 Cloudflare 创建 Tunnel

1. 打开 Cloudflare Dashboard。
2. 进入 `Zero Trust`。
3. 进入 `Networks` -> `Tunnels`。
4. 创建一个 `Cloudflared` tunnel，例如命名为 `twitter-video-download`。
5. 添加 Public Hostname：
   - Subdomain：例如 `xvideo`
   - Domain：选择你的域名，例如 `example.com`
   - Type：`HTTP`
   - URL：`twitter-video-download:8000`
6. 保存后，在 `Docker` 安装方式里复制 token。token 通常是一长串 `eyJ...`。

最终公网地址类似：

```text
https://xvideo.example.com
```

### 2. 在服务器运行 cloudflared

在服务器目录里拉取 Cloudflare Compose 文件：

```bash
cd /opt/twitter-video-download
curl -fsSL https://raw.githubusercontent.com/Idealisten/Twitter_Video_Download/main/compose.cloudflare.yaml -o compose.cloudflare.yaml
```

编辑 `.env`，填入刚复制的 token：

```text
CLOUDFLARE_TUNNEL_TOKEN=eyJ...
```

启动网站和 Tunnel：

```bash
docker compose -f compose.yaml -f compose.cloudflare.yaml up -d
```

查看 Tunnel 日志：

```bash
docker compose -f compose.yaml -f compose.cloudflare.yaml logs -f cloudflared
```

以后更新网站镜像，同时保留 Tunnel：

```bash
cd /opt/twitter-video-download
docker compose -f compose.yaml -f compose.cloudflare.yaml pull
docker compose -f compose.yaml -f compose.cloudflare.yaml up -d
```

如果只想重启 Tunnel：

```bash
docker compose -f compose.yaml -f compose.cloudflare.yaml restart cloudflared
```

iPhone 快捷指令里的接口地址改成公网域名：

```text
https://xvideo.example.com/api/shortcut?url=编码后的URL
```

注意：`CLOUDFLARE_TUNNEL_TOKEN` 等同于连接这个 Tunnel 的凭证，不要提交到 GitHub。如果泄露，到 Cloudflare Dashboard 里 rotate token，然后更新服务器 `.env` 并重启 `cloudflared`。

### 已有 Tunnel 时新增这个服务

如果服务器上已经有一个 Cloudflare Tunnel，不一定要新建 Tunnel。一个 Tunnel 可以发布多个 hostname，每个 hostname 指向不同的本地服务。

先在服务器启动本服务：

```bash
mkdir -p /opt/twitter-video-download
cd /opt/twitter-video-download
curl -fsSL https://raw.githubusercontent.com/Idealisten/Twitter_Video_Download/main/compose.yaml -o compose.yaml
curl -fsSL https://raw.githubusercontent.com/Idealisten/Twitter_Video_Download/main/.env.example -o .env
docker compose up -d
```

此时服务端口是：

```text
宿主机访问：http://127.0.0.1:8001
Docker Compose 内部访问：http://twitter-video-download:8000
```

#### 情况 A：已有 Tunnel 是 Dashboard / token 管理

这种是目前更推荐的方式，服务器通常只保存 `CLOUDFLARE_TUNNEL_TOKEN`，本地没有需要手写的 `config.yml`。

操作：

1. 打开 Cloudflare Dashboard。
2. 进入 `Zero Trust` -> `Networks` -> `Tunnels`。
3. 选择已有 Tunnel。
4. 进入 `Public Hostnames`。
5. 添加一个 hostname，例如：
   - Subdomain：`xvideo`
   - Domain：`example.com`
   - Type：`HTTP`
   - URL：如果 cloudflared 和本服务在同一个 `docker compose` 项目里，填 `twitter-video-download:8000`
   - URL：如果 cloudflared 是宿主机 systemd 服务或另一个独立容器，填 `127.0.0.1:8001`
6. 保存。

保存后 Cloudflare 会自动创建对应 DNS 记录。公网地址类似：

```text
https://xvideo.example.com
```

如果你的 cloudflared 已经是独立 systemd 服务，一般不需要重启；Cloudflare 会把新的 Public Hostname 配置下发给正在运行的 connector。若几分钟后仍不生效，可以重启：

```bash
sudo systemctl restart cloudflared
```

#### 情况 B：已有 Tunnel 是本地 config.yml 管理

这种方式需要修改 cloudflared 的配置文件。常见路径：

```text
/etc/cloudflared/config.yml
~/.cloudflared/config.yml
```

用下面命令先找配置文件：

```bash
sudo ls -la /etc/cloudflared
ls -la ~/.cloudflared
```

编辑 `config.yml`，在 `ingress` 里新增一个 hostname。示例：

```yaml
tunnel: 你的TunnelID或TunnelName
credentials-file: /root/.cloudflared/你的TunnelID.json

ingress:
  - hostname: old.example.com
    service: http://127.0.0.1:8000

  - hostname: xvideo.example.com
    service: http://127.0.0.1:8001

  - service: http_status:404
```

说明：

- `xvideo.example.com` 换成你的域名。
- 如果 cloudflared 是宿主机服务，`service` 用 `http://127.0.0.1:8001`。
- 如果 cloudflared 和本服务在同一个 Docker Compose 网络里，`service` 可以用 `http://twitter-video-download:8000`。
- 最后一条 `- service: http_status:404` 要保留，作为未匹配 hostname 的兜底。

为新 hostname 创建 DNS route：

```bash
cloudflared tunnel route dns 你的TunnelID或TunnelName xvideo.example.com
```

重启 cloudflared：

```bash
sudo systemctl restart cloudflared
```

检查日志：

```bash
sudo journalctl -u cloudflared -f
```

公网验证：

```bash
curl -I https://xvideo.example.com/health
```

返回 `200` 即表示 Tunnel 和服务都通了。

快捷指令地址改成：

```text
https://xvideo.example.com/api/shortcut?url=编码后的URL
```

## API

下面示例里的 `https://xvideo.example.com` 换成你的 Cloudflare Tunnel 域名。

解析：

```bash
curl -X POST https://xvideo.example.com/api/parse \
  -H "Content-Type: application/json" \
  -d '{"url":"https://x.com/user/status/1234567890"}'
```

快捷指令友好的解析接口：

```text
https://xvideo.example.com/api/shortcut?url=URL编码后的推文链接
```

响应中的 `items` 每项包含：

- `label`：给用户选择时显示的文字
- `download_url`：对应清晰度的下载地址
- `resolution`：分辨率
- `size`：文件大小

同时也会返回快捷指令更容易使用的：

- `labels`：只包含选项文字的列表
- `downloads`：以选项文字为键、下载地址为值的词典

## iPhone 快捷指令新建方法

### 方式一：最简单，打开网页选择下载

1. 打开「快捷指令」App，新建快捷指令，命名为「下载 X 视频」。
2. 点右侧信息按钮，打开「在共享表单中显示」。
3. 「接收」类型选择「URL」。
4. 添加动作「URL 编码」，输入选择「快捷指令输入」。
5. 添加动作「文本」，内容填：

   ```text
   https://xvideo.example.com/?url=上一步URL编码结果
   ```

6. 添加动作「打开 URL」，URL 选择上一步文本。
7. 在 X/Twitter App 里分享推文链接到这个快捷指令，会自动打开网页并开始解析，随后点想要的分辨率下载。

### 方式二：在快捷指令里选择分辨率并保存到相册

1. 新建快捷指令，打开「在共享表单中显示」，接收类型选择「URL」。
2. 添加「从输入中获取 URL」，输入为「快捷指令输入」。
3. 添加「URL 编码」，输入为上一步 URL。
4. 添加「文本」，内容为：

   ```text
   https://xvideo.example.com/api/shortcut?url=上一步URL编码结果
   ```

5. 添加「获取 URL 内容」，URL 使用上一步文本，方法为 `GET`。
6. 添加「从输入中获取词典」。
7. 添加「获取词典值」，键填写 `labels`。
8. 添加「从列表中选取」，让你选择分辨率。
9. 添加「获取词典值」，键填写 `downloads`，输入为第 6 步得到的词典。
10. 添加「获取词典值」，键使用第 8 步选中的项目，输入为第 9 步得到的 `downloads` 词典。
11. 添加「获取 URL 内容」，URL 使用第 10 步得到的下载地址，方法为 `GET`。
12. 添加「存储到照片相簿」，输入为第 11 步获取到的 URL 内容。

注意：iPhone 快捷指令推荐始终使用 Cloudflare Tunnel 提供的 HTTPS 域名。局域网 IP 只适合临时调试，不建议写进正式快捷指令。

## 环境变量

- `HOST`：监听地址，默认 `0.0.0.0`
- `PORT`：端口，默认 `8000`
- `DOWNLOAD_DIR`：临时下载目录，默认系统临时目录
- `RESULT_TTL_SECONDS`：解析结果缓存时间，默认 1800 秒
- `MAX_DOWNLOAD_BYTES`：单个视频最大下载体积，默认 1GB
