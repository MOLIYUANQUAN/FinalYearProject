# iPhone 临时入口（隧道 · 过渡）

> **正路已改成云上 API + iPhone App。** 见 [cloud-and-iphone.md](cloud-and-iphone.md)。  
> 本文只保留「电脑开着时用隧道试手机」的过渡办法。

不是另做一个代理：还是这一个 Friday。电脑开着时，可用 Safari 打开隧道链接试同一套页面。

## 为什么曾经先网页

当时要的是**马上能聊**。现在目标是电脑关机也能用，所以大脑要上云，再打正式 App。

## 一次准备

1. 电脑上 Friday 能正常用（日历 / Tasks / 邮件已接好）。
2. 安装 [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)（Windows），放进 PATH，或放到仓库里的 `tools\cloudflared.exe`。
3. `.env` 里可以先不写访问码；第一次跑下面的脚本会自动生成 `FRIDAY_ACCESS_TOKEN`。

## 每次用手机前（电脑要开着）

```powershell
.\.venv\Scripts\python.exe scripts\phone_access.py
```

脚本会：

- 确保访问码在 `.env` 里  
- 确保本机 `8765` 服务在跑  
- 开一条临时隧道，打印带 `?access=…` 的链接  

在 iPhone **Safari** 打开那条链接。可「分享 → 添加到主屏幕」。

关掉脚本窗口只停隧道；本机 Friday 还在。链接别发到群里。

## 本机快捷键

设了访问码之后，桌面窗口会由启动器自动带上同一把码。若你手动开 `http://127.0.0.1:8765/` 却进不去，用脚本打印的链接，或在页上输入访问码。

## 安全（最小、够用）

- 有 `FRIDAY_ACCESS_TOKEN` 时，所有 `/api/*` 都要带码。  
- 隧道流量在本机也像 localhost，所以**不能**「本机免登录」。  
- 这是临时隧道，不是长期公网部署；电脑休眠或断网，手机就连不上。

## 验收

手机上说：「提醒我明天续借图书馆的书。」  
电脑上打开 Friday 或手机 Google Tasks，应能看到同一条。
