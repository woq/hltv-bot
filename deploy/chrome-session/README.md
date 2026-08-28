# 持久 Chrome（Ubuntu LTS VPS）

同一出口 IP 时，Cloudflare 拦的是 **headless / 一次性 profile**，不是 IP。  
做法：真 Chrome（有显示）+ 固定 `user-data-dir` + 远程调试口。第一次用 noVNC 手过 challenge，cookie 和 profile 写在磁盘上。

不要：每次 Python 里 `launch(headless=True)`。  
要：Chrome 用 systemd 常驻，bot 只 `connect_over_cdp`。

## 1. 装 Google Chrome（别用 snap Chromium）

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
  | sudo gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
  | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update
sudo apt install -y google-chrome-stable xvfb x11vnc novnc websockify
sudo useradd --system --home /var/lib/hltv-chrome --create-home --shell /usr/sbin/nologin hltv
sudo mkdir -p /var/lib/hltv-chrome/profile
sudo chown -R hltv:hltv /var/lib/hltv-chrome
```

## 2. systemd

把本目录三个 unit 拷到 `/etc/systemd/system/`，然后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now xvfb@99 hltv-chrome x11vnc@99
# 可选，只为第一次过人机：
sudo systemctl enable --now novnc
```

Chrome 调试口只绑 `127.0.0.1:9222`。外网访问用 SSH：

```bash
ssh -L 9222:127.0.0.1:9222 -L 6080:127.0.0.1:6080 user@vps
```

浏览器打开 `http://127.0.0.1:6080/vnc.html`，在桌面里打开 HLTV，过完 challenge 后 **不要清 profile**。

## 3. Bot 只复用这个浏览器

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]  # 已有登录/CF 的那个
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://www.hltv.org/matches/2396932/x")
    # evaluate extract.js …
```

`cf_clearance` / `__cf_bm` 会过期；**profile 目录会自动再过一次轻量检查**。只要 Chrome 进程还在、不是 headless，通常不用你每次点。进程死了再起来，偶发要再开一次 VNC。

## 注意

- 内存：常驻 Chrome 预留 **1GB+**。`/dev/shm` 小的机器已加 `--disable-dev-shm-usage`。
- 升级 Chrome 后重启 `hltv-chrome` 即可，profile 可留。
- 不要用 root 跑 Chrome。
- Scorebot 也在 CF 后：在 **这个已过验证的 page 里** `fetch` / 注入 socket，不要把 cookie 拷到裸 urllib。
