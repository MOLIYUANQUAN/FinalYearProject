# Google Calendar 只读接入（Application Phase 1）

默认仍是 **mock**（`data/calendar.json`）。要接真实日历时，按本说明操作。

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

## 2. Google Cloud 配置

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)
2. 新建（或选择）项目
3. 启用 **Google Calendar API**
4. **APIs & Services → OAuth consent screen**  
   - User type：External（个人账号）  
   - 测试用户里加上你自己的 Google 账号
5. **Credentials → Create credentials → OAuth client ID**  
   - Application type：**Desktop app**  
   - 下载 JSON
6. 把下载的文件保存为仓库内：

```text
secrets/credentials.json
```

`secrets/` 已在 `.gitignore` 中，不要提交。

## 3. 本地授权（首次）

```bash
python scripts/auth_google_calendar.py
```

浏览器登录并同意 **只读** 日历权限后，会生成：

```text
secrets/google_token.json
```

## 4. 切换后端

在 `.env` 中：

```env
CALENDAR_BACKEND=google
# selected = 网页里勾选的全部日历（含导入课表，推荐）
# primary = 仅主日历
GOOGLE_CALENDAR_ID=selected
```

重启：

```bash
python -m src.main
```

- `CALENDAR_BACKEND=mock`：继续用固定演示日 `2026-10-12/13`  
- `CALENDAR_BACKEND=google`：Agent 的「今天/明天」改为**系统真实日期**

## 5. 验收

在 Google 日历里给**明天的下午**建一个测试事件，然后问：

> 我明天下午有什么安排？

应调用 `get_calendar_events`，且返回里 `source` 为 `google`。

切回可复现 Demo：

```env
CALENDAR_BACKEND=mock
```

## 安全

- 不要把 `secrets/`、`.env` 推到 GitHub  
- 当前 scope 为完整 `calendar`（可读列表 + 可在主日历创建事件）  
- 创建事件前 Agent 必须先请求你确认；写入只针对 **primary**，不会改导入课表  
- 若从旧版 readonly 升级，请重新运行 `python scripts/auth_google_calendar.py`
- Friday 显示「Google 日历需要重新登录」时也是重新运行这条命令（后台服务从不自己弹出授权页）。如果每周都要来一次，多半是 OAuth 应用还在 Testing 状态（刷新令牌 7 天就过期）：在 Google Cloud 控制台的 OAuth consent screen 里把它发布为 In production
