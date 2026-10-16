# Outlook / Microsoft 365 邮件只读（学生邮箱）

曼大学生邮箱走 **Microsoft Graph**，不是 Gmail。

## 1. 在 Azure 注册应用

1. 打开 [Azure Portal → App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. **New registration**
   - Name：`FYP-Personal-Agent`（随意）
   - Supported account types：选  
     **Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant)**  
     （学校账号用这个；若选项不同，选能覆盖 Work/School 的）
   - Redirect URI：先留空（我们用设备码登录）
3. 创建后复制 **Application (client) ID**
4. **Authentication** → **Advanced settings** →  
   **Allow public client flows** = **Yes** → Save
5. **API permissions** → Add a permission → **Microsoft Graph** → **Delegated**：
   - `User.Read`
   - `Mail.Read`
6. 点 **Grant admin consent**（若按钮可用）。  
   若学校禁用学生授权：可能需 IT/管理员同意，或只能用个人 Microsoft 账号测试。

## 2. 配置 `.env`

```env
MAIL_BACKEND=outlook
OUTLOOK_CLIENT_ID=你的-Application-Client-ID
# 学校账号推荐 organizations；若失败可试 common
OUTLOOK_TENANT=organizations
```

## 3. 本地授权

```bash
python scripts/auth_outlook.py
```

终端会显示一串代码和网址（如 `https://microsoft.com/devicelogin`）。  
用**学生 Outlook 账号**在浏览器登录并输入代码。成功后生成：

```text
secrets/outlook_token.json
```

（已在 `.gitignore`，勿提交。）

## 4. 重启服务并试

```bash
python -m src.main
```

网页提问示例：

- 「最近和 FYP 相关的邮件有哪些？」
- 「读一下最近一封来自导师的邮件摘要」

## 5. Mock（无学校账号时）

```env
MAIL_BACKEND=mock
```

使用 `data/mail/messages.json` 本地假邮件，方便演示/复现。

## 安全与范围

- 本阶段 **只读**（`Mail.Read`），不发送邮件  
- 发送若以后要做，必须走 `request_user_confirmation`  
