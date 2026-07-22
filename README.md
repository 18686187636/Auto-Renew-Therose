README.md

```markdown
# The Rose Cloud 自动续期

[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-手动触发-blue)](.github/workflows/renew.yml)

自动登录 [The Rose Cloud](https://client.therose.cloud) 并点击续期按钮，通过 Telegram 推送执行结果。

---

## ✨ 功能

- 使用 SeleniumBase 模拟浏览器操作
- 自动处理 Turnstile 验证码（有头/无头模式自适应）
- 检测续期成功与否并截图留存
- 通过 Telegram 推送通知（可选）

---

## 🔐 敏感信息配置

### 方式一：GitHub Actions（推荐）
在仓库的 **Settings → Secrets and variables → Actions** 中添加以下 **加密变量**：

| 变量名 | 说明 | 必需 |
|--------|------|------|
| `EMAIL` | 登录邮箱 | ✅ |
| `PASSWORD` | 登录密码 | ✅ |
| `TG_BOT_TOKEN` | Telegram Bot Token | ❌ |
| `TG_CHAT_ID` | 接收通知的 Chat ID | ❌ |

添加后，工作流运行时会自动注入，**日志不会泄露明文**。

### 方式二：本地运行
使用 `.env` 文件（**务必加入 `.gitignore`**），内容示例：
```env
EMAIL=your_email
PASSWORD=your_password
TG_BOT_TOKEN=your_token
TG_CHAT_ID=your_chat_id
HEADLESS=false   # true 为无头模式
```
安装依赖并运行：
```bash
pip install seleniumbase requests python-dotenv
python script.py
```
> 切勿将凭据硬编码在脚本或命令行中。

---

## 🚀 本地运行（不依赖 .env）

也可直接通过环境变量启动：
```bash
export EMAIL="your_email"
export PASSWORD="your_password"
export HEADLESS="false"   # 可选
python script.py
```

---

## ☁️ GitHub Actions 手动运行

1. **Fork 本仓库** 并进入页面。
2. 按上述方式添加 Secrets。
3. 进入 **Actions** 选项卡，选择 **Renew The Rose Cloud** 工作流。
4. 点击 **Run workflow** → 选择分支 → **Run workflow**。
5. 等待执行完成，查看日志或 Telegram 通知。

---

## ⚙️ 无头模式说明

脚本通过环境变量 `HEADLESS` 控制浏览器模式：
- `HEADLESS=true`  → 无头模式（适用于 GitHub Actions）
- `HEADLESS=false` → 有头模式（本地调试，可直观看到操作）

验证码处理自动适配：
- 有头模式：使用 `uc_gui_click_captcha()`（弹出图形验证窗口）
- 无头模式：使用 `uc_click_captcha()`（纯后台模拟）

> 若 Turnstile 在无头模式下仍失败，可尝试本地有头调试。

---

## 📂 文件结构

```
.
├── .github/
│   └── workflows/
│       └── renew.yml       # GitHub Actions 工作流
├── script.py               # 主脚本
└── README.md               # 本文件
```

---

## 📄 许可证

MIT License
```

---

## 🧩 使用步骤总览

1. 将上述三个文件放入仓库对应位置。
2. 在 GitHub 仓库设置中添加 Secrets（`EMAIL`、`PASSWORD` 等）。
3. 进入 Actions 页面，手动触发工作流。
4. 查看运行日志或等待 Telegram 通知。

一切就绪，祝续期顺利！ 🎉
