# TheRose Cloud 自动续期脚本

> 自动登录 [TheRose Cloud](https://client.therose.cloud) 并续期服务器，支持 Telegram 通知与 cron-job.org 定时调度。

---

## 📖 简介

本脚本通过浏览器自动化（SeleniumBase）模拟用户登录、绕过 Turnstile 验证码、点击续期按钮，并自动检查续期结果。同时，利用 [cron-job.org](https://cron-job.org) 的 API 在服务器到期前 **20 分钟**自动触发 GitHub Actions 工作流，实现全自动无人值守续期。

---

## ✨ 功能特点

- ✅ 自动登录 TheRose Cloud 面板
- 🛡️ 内置 Turnstile 验证码处理（`uc_gui_click_captcha`）
- 📸 关键步骤自动截图，便于调试
- 📨 续期结果通过 Telegram 实时通知
- 🔄 续期成功后自动获取最新到期时间
- ⏰ 在服务器到期前 **20 分钟**自动设置 cron-job 任务（仅保留一个）
- 🚀 支持代理（HTTP/SOCKS）和强制调度模式

---

## 🧰 环境变量

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `EMAIL` | ✅ | TheRose Cloud 登录邮箱 |
| `PASSWORD` | ✅ | TheRose Cloud 登录密码 |
| `TG_BOT_TOKEN` | ❌ | Telegram Bot Token（如需通知） |
| `TG_CHAT_ID` | ❌ | Telegram 接收消息的 Chat ID |
| `PROXY_SERVER` | ❌ | 代理地址，例如 `http://127.0.0.1:7890` |
| `CRONJOB_API_KEY` | ⚠️ | cron-job.org API Key（如需自动调度） |
| `GH_TOKEN` | ⚠️ | GitHub Personal Access Token（用于触发 workflow） |
| `GH_REPO` | ⚠️ | GitHub 仓库名，格式 `owner/repo` |
| `GH_WORKFLOW_ID` | ⚠️ | GitHub Actions 工作流 ID（数字） |
| `FORCE_SCHEDULE` | ❌ | 设为 `true` 时，即使续期失败也强制创建调度任务（用于首次运行） |

> ⚠️ 表示：若需启用自动调度功能，则这些变量必须全部设置。

---

## 📦 安装依赖

推荐使用 Python 3.8+ 和虚拟环境：

```bash
# 克隆仓库
git clone https://github.com/your-username/therose-renew.git
cd therose-renew

# 创建虚拟环境（可选）
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

`requirements.txt` 内容示例：

```
seleniumbase
requests
```

另外，脚本依赖浏览器驱动（Chrome/Chromium），SeleniumBase 会自动下载，您也可以手动安装 `chromedriver`。

---

## 🚀 使用方法

### 1. 手动运行

设置好环境变量后，直接执行：

```bash
python renew.py
```

脚本会：
- 打开浏览器（非 headless 模式）
- 登录面板
- 进入服务器列表
- 点击 `Extend` → `Order now`
- 检查续期结果
- 发送 Telegram 通知
- 若续期成功，则调用 cron-job.org 在到期前 20 分钟触发 GitHub Actions

### 2. GitHub Actions 自动化（推荐）

您可以在仓库中创建 `.github/workflows/renew.yml`，并配置定时触发（例如每天一次）。当 cron-job 触发时，会自动运行该 workflow。

示例 workflow：

```yaml
name: Auto Renew
on:
  workflow_dispatch:
  schedule:
    - cron: '0 0 * * *'  # 每天UTC 0点，可自行调整

jobs:
  renew:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run renew script
        env:
          EMAIL: ${{ secrets.EMAIL }}
          PASSWORD: ${{ secrets.PASSWORD }}
          TG_BOT_TOKEN: ${{ secrets.TG_BOT_TOKEN }}
          TG_CHAT_ID: ${{ secrets.TG_CHAT_ID }}
          PROXY_SERVER: ${{ secrets.PROXY_SERVER }}
          CRONJOB_API_KEY: ${{ secrets.CRONJOB_API_KEY }}
          GH_TOKEN: ${{ secrets.GH_TOKEN }}
          GH_REPO: ${{ github.repository }}
          GH_WORKFLOW_ID: ${{ secrets.GH_WORKFLOW_ID }}
          FORCE_SCHEDULE: "true"  # 第一次运行时启用
        run: python renew.py
```

### 3. 通过 cron-job.org 触发

当脚本成功续期后，它会调用 cron-job.org API 创建一个（或更新已有的）定时任务，该任务在服务器到期前 **20 分钟** 向 GitHub API 发送 `workflow_dispatch` 请求，从而触发上述 workflow，再次运行续期脚本。

这样就形成了一个闭环：每次续期成功后，自动安排下次执行，无需人工干预。

---

## ⚙️ 调度逻辑说明

- 脚本会从页面获取服务器到期时间（UTC 格式 `%Y-%m-%d %H:%M`）
- 将到期时间转换为时间戳，减去 20 分钟作为触发时间
- 调用 `schedule_via_cronjob()` 函数：
  - 先查询 cron-job.org 上所有现有任务
  - 若存在相同 `url`（即相同的 GitHub workflow 触发地址）的任务，则删除多余的，只保留一个并更新其调度时间
  - 若不存在，则创建一个新任务
- **保证全局只有 1 个定时任务**，且每次运行都会刷新触发时间

---

## 📸 截图与调试

脚本会在以下时机自动截图（保存为 `step_*.png`）：
- 登录页面加载后
- 填写表单后
- 处理验证码后
- 点击登录后
- 服务器列表页
- 续期操作后
- 最终结果

这些截图可用于排查问题。

---

## 📨 Telegram 通知

若设置了 `TG_BOT_TOKEN` 和 `TG_CHAT_ID`，脚本会在以下情况发送通知：
- 登录失败
- 续期成功/失败
- 包含当前北京时间、账号信息和到期时间

---

## 🔒 安全建议

- 请将 `EMAIL`、`PASSWORD`、`GH_TOKEN` 等敏感信息保存在 GitHub Secrets 或本地 `.env` 文件中，切勿硬编码
- 若使用代理，确保代理稳定且可访问目标网站
- 建议在 GitHub Actions 中启用 `FORCE_SCHEDULE` 仅在首次运行时使用，之后可关闭，避免意外调度

---

## 🐛 常见问题

### 1. 登录失败 / Turnstile 无法通过
- 检查网络环境（尝试更换代理）
- 增加 `sleep` 等待时间（脚本已内置 60 秒等待，可自行调整）
- 手动打开浏览器测试是否能正常登录

### 2. 未找到 Extend 按钮
- 确认账户下存在有效服务器
- 检查页面布局是否变化（可截图对比）

### 3. cron-job.org 调度失败
- 确认 API Key 有创建/更新任务的权限
- 检查环境变量是否齐全
- 查看 API 响应日志（脚本会打印错误信息）

### 4. 任务重复创建
- 已采用“查询-更新-删除冗余”策略，理论上只保留一个任务。若仍有多个，可检查 `url` 字段是否完全一致（包括尾部斜杠等）

---

## 📄 许可证

本项目采用 [MIT License](LICENSE)。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。若有改进建议，请随时联系。

---

## 📎 相关链接

- [TheRose Cloud](https://client.therose.cloud)
- [cron-job.org](https://cron-job.org)
- [SeleniumBase 文档](https://seleniumbase.io)

---

**Happy Renewing! 🌹**
