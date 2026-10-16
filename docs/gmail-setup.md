# Gmail 只读接入

学校 Outlook / Azure 对学生常无权限，本项目邮件集成默认走 **个人 Gmail**。

复用日历同一套 Google Cloud OAuth 客户端：`secrets/credentials.json`。

## 1. 启用 Gmail API

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)（项目可用之前的 `calendar`）
2. **API 和服务 → 库** → 搜索 **Gmail API** → **启用**
3. OAuth 同意屏幕仍为外部 + 测试用户包含你的 Gmail

## 2. 授权

```bash
python scripts/auth_gmail.py
```

浏览器登录你的 Gmail 并同意只读邮件权限。生成：

```text
secrets/gmail_token.json
```

## 3. `.env`

```env
MAIL_BACKEND=gmail
```

重启：

```bash
python -m src.main
```

试问：「最近和 FYP 相关的邮件有哪些？」

## 说明

- 只读（`gmail.readonly`），不发送邮件  
- 学校邮箱若以后能接，仍保留 `outlook` / `mock` 选项  
