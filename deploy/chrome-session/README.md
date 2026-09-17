# 持久 Chrome（root VPS）

Chrome **默认拒绝 uid 0**。这台机是专用 root 盒，unit 用 `--no-sandbox --disable-setuid-sandbox` 跑 headed Chrome。不要再搞 `hltv` 系统用户。

Bot **只 attach** `127.0.0.1:9222`，不 launch。首次 noVNC 过 Turnstile；之后 idle keeper tab 自己续 `__cf_bm`。

不要：`--headless`、每次 Python `launch`、`Restart=always`（新进程会掉 clearance）。

## 1. Bootstrap（root，一次性）

```bash
# 1G swap
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
sysctl -w vm.swappiness=10
echo 'vm.swappiness=10' > /etc/sysctl.d/99-hltv-swappiness.conf

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
  | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
  > /etc/apt/sources.list.d/google-chrome.list
apt-get update
apt-get install -y google-chrome-stable xvfb x11vnc novnc websockify smem

mkdir -p /var/lib/hltv-chrome/profile

install -m 644 /opt/hltv-bot/deploy/chrome-session/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now xvfb@99 hltv-chrome
systemctl start x11vnc@99 novnc
```

本机 **只转 6080**（不要转 9222）：

```bash
ssh -L 6080:127.0.0.1:6080 hytron
# http://127.0.0.1:6080/vnc.html 过 Turnstile，不要清 profile
```

过完：`systemctl stop novnc x11vnc@99`。不要 disable xvfb/chrome。

```bash
curl -sS http://127.0.0.1:9222/json/list
ss -lntp | grep -E '9222|5900|6080'   # 不得听 0.0.0.0
python3 -m hltv_bot export-cookies
smem -p -k | grep -i chrome
```

GitHub Actions **只** `restart hltv-bot`，绝不 start/restart Chrome。Chrome 挂了是维护事件：`systemctl start hltv-chrome` + 再 VNC。

## 2. 分辨率

默认 Xvfb `800x600x16`、Chrome `--window-size=800,600`。Turnstile 白板则维护窗口改 unit 后 `systemctl start` Chrome（`Restart=no`）：

1. `1280x720x24` + `--window-size=1280,720`
2. `1920x1080x24` + `--window-size=1920,1080`

## 3. Cookie 导出

```bash
python3 -m hltv_bot export-cookies
python3 -m hltv_bot export-cookies --write   # challenge 时拒绝写盘
```

`--write` 不是热更新。bot 里的 keeper 线程会原地改同一个 `BrowserSession`。

## 注意

- `MemoryMax=900M` 是 RAM 杀进程线。过夜 `smem`，Chrome RSS 目标 <700M。
- 不要 `--disable-software-rasterizer`（和 `--disable-gpu` 一起关会没 canvas）。
- 不要 `Page.reload` keeper。不要自动重启 Chrome。
