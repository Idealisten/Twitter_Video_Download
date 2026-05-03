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

## API

解析：

```bash
curl -X POST http://127.0.0.1:8000/api/parse \
  -H "Content-Type: application/json" \
  -d '{"url":"https://x.com/user/status/1234567890"}'
```

快捷指令友好的解析接口：

```text
http://127.0.0.1:8000/api/shortcut?url=URL编码后的推文链接
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
   http://你的服务器IP:8000/?url=上一步URL编码结果
   ```

6. 添加动作「打开 URL」，URL 选择上一步文本。
7. 在 X/Twitter App 里分享推文链接到这个快捷指令，会自动打开网页并开始解析，随后点想要的分辨率下载。

### 方式二：在快捷指令里选择分辨率并保存到相册

1. 新建快捷指令，打开「在共享表单中显示」，接收类型选择「URL」。
2. 添加「从输入中获取 URL」，输入为「快捷指令输入」。
3. 添加「URL 编码」，输入为上一步 URL。
4. 添加「文本」，内容为：

   ```text
   http://你的服务器IP:8000/api/shortcut?url=上一步URL编码结果
   ```

5. 添加「获取 URL 内容」，URL 使用上一步文本，方法为 `GET`。
6. 添加「从输入中获取词典」。
7. 添加「获取词典值」，键填写 `labels`。
8. 添加「从列表中选取」，让你选择分辨率。
9. 添加「获取词典值」，键填写 `downloads`，输入为第 6 步得到的词典。
10. 添加「获取词典值」，键使用第 8 步选中的项目，输入为第 9 步得到的 `downloads` 词典。
11. 添加「获取 URL 内容」，URL 使用第 10 步得到的下载地址，方法为 `GET`。
12. 添加「存储到照片相簿」，输入为第 11 步获取到的 URL 内容。

注意：如果服务跑在家里电脑上，iPhone 必须和电脑在同一个 Wi-Fi；如果要在外网用，建议放到有 HTTPS 的服务器或通过 Cloudflare Tunnel / Tailscale 之类的私有访问方式暴露，不建议裸奔公开服务。

## 环境变量

- `HOST`：监听地址，默认 `0.0.0.0`
- `PORT`：端口，默认 `8000`
- `DOWNLOAD_DIR`：临时下载目录，默认系统临时目录
- `RESULT_TTL_SECONDS`：解析结果缓存时间，默认 1800 秒
- `MAX_DOWNLOAD_BYTES`：单个视频最大下载体积，默认 1GB
