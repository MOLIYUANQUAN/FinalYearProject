# Application：Outlook 邮件只读 v1

学生邮箱使用 **Microsoft Graph / Outlook**，不是 Gmail。

## 能力

| 工具 | 作用 |
|------|------|
| `search_emails` | 按关键词搜/列最近邮件 |
| `read_email` | 读单封正文 |

后端：

- `MAIL_BACKEND=outlook`：真实学校邮箱  
- `MAIL_BACKEND=mock`：`data/mail/messages.json`  
- `MAIL_BACKEND=none`：关闭  

Setup：[outlook-mail-setup.md](outlook-mail-setup.md)

## 不做

- 发送邮件（若以后做，必须先确认）  
- 替代 Google 日历（课表仍用 Google selected）  
