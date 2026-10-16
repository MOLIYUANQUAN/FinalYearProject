# Application：Gmail 邮件只读 v1

因曼大学生账号无法使用 Azure App Registration，邮件集成改为 **Gmail 只读**。

| `MAIL_BACKEND` | 含义 |
|----------------|------|
| `gmail` | 个人 Gmail（推荐） |
| `mock` | 本地假邮件 |
| `outlook` | 保留代码，学校 Azure 无权限时不可用 |
| `none` | 关闭 |

Setup：[gmail-setup.md](gmail-setup.md)
