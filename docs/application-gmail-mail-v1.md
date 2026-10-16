# Application：Gmail 邮件读写 v1

因曼大学生账号无法使用 Azure App Registration，邮件集成使用 **个人 Gmail**。

| 工具 | 确认？ |
|------|--------|
| `search_emails` / `read_email` | 否 |
| `modify_email` mark_read/unread | 否 |
| `modify_email` archive/trash | 是 |
| `send_email` | 是 |

| `MAIL_BACKEND` | 含义 |
|----------------|------|
| `gmail` | 个人 Gmail（推荐） |
| `mock` | 本地假邮件 |
| `outlook` | 保留，学校常无权限 |
| `none` | 关闭 |

Setup：[gmail-setup.md](gmail-setup.md)
