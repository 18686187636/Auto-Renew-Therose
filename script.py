#!/usr/bin/env python3

import os, re, sys, time, requests
import json                                      # 🆕 新增导入
from datetime import datetime, timedelta
from seleniumbase import SB

# ========== 环境变量 ==========
EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY_SERVER = os.environ.get("PROXY_SERVER") or ""   # socks5://127.0.0.1:1080

# 🆕 调度相关环境变量（可选，缺少则跳过调度）
CRONJOB_API_KEY = os.environ.get("CRONJOB_API_KEY") or ""
GH_TOKEN = os.environ.get("GH_TOKEN") or ""
GH_REPO = os.environ.get("GH_REPO") or ""            # 格式 "owner/repo"
GH_WORKFLOW_ID = os.environ.get("GH_WORKFLOW_ID") or ""  # 如 "renew.yml"

BASE_URL = "https://client.therose.cloud/login"

if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)

# ========== 辅助函数 ==========
def screenshot_step(sb, step_name):
    """保存带步骤名的截图（含时间戳）"""
    timestamp = int(time.time() * 1000)
    filename = f"step_{step_name}_{timestamp}.png"
    sb.save_screenshot(filename)
    print(f"📸 截图已保存: {filename}")

def send_tg(token, chat_id, message):
    """发送 Telegram 通知"""
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        if resp.status_code == 200:
            print("📨 Telegram 通知已发送")
        else:
            print(f"❌ Telegram 发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")

def get_current_ip(proxy_server=None):
    """通过代理获取当前出口 IP"""
    proxies = None
    if proxy_server:
        proxies = {"http": proxy_server, "https": proxy_server}
    try:
        response = requests.get("https://api.ip.sb/ip", proxies=proxies, timeout=15)
        if response.status_code == 200:
            return response.text.strip()
        else:
            return f"获取失败 (HTTP {response.status_code})"
    except Exception as e:
        return f"获取失败: {e}"

def get_beijing_time():
    """获取当前北京时间字符串 (UTC+8)"""
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

# ========== 续期按钮点击 ==========
def click_extend_button(sb):
    selectors = [
        'span:contains("Extend")',
        'button:contains(title="Extend")',
    ]
    for sel in selectors:
        try:
            if sb.find_element(sel, timeout=2):
                print(f"✅ 找到按钮，选择器: {sel}")
                sb.uc_click(sel, timeout=5)
                print("✅ 点击成功")
                return True, {}
        except:
            continue
    try:
        btn = sb.find_element('button:contains("Extend")', timeout=2)
        sb.driver.execute_script("arguments[0].click();", btn)
        print("✅ 通过 JavaScript 点击成功")
        return True, {}
    except Exception as e:
        return False, {"error": str(e)}

# ========== 检查续期结果 ==========
def check_renewal_success(sb):
    success_selectors = [
        '.alert-success',
        '.alert.alert-success',
        'div[role="alert"].alert-success',
        'div.alert-success',
        'span:contains("successfully purchased")',
        'div:contains("successfully purchased")'
    ]
    print("⏳ 等待5秒检查续期结果...")
    time.sleep(5)
    for selector in success_selectors:
        try:
            element = sb.find_element(selector, timeout=2)
            if element:
                text = element.text
                print(f"✅ 发现成功提示！选择器: {selector}")
                print(f"📝 提示内容: {text}")
                return True, text
        except:
            continue
    try:
        page_source = sb.get_page_source()
        if "successfully purchased" in page_source.lower():
            print("✅ 页面源码中发现 'successfully purchased' 关键词")
            return True, "服务器已成功续期"
    except:
        pass
    return False, "未检测到续期成功提示"

# ========== 获取服务器开始时间和到期时间 ==========
def get_server_time_info(sb):
    """
    从服务器列表页面提取开始时间（<span class="fw-bold text-muted">）
    并计算 6 小时后的到期时间
    返回: (开始时间字符串, 到期时间字符串)
    """
    try:
        el = sb.find_element('span.fw-bold.text-muted', timeout=10)
        if el:
            start_time_str = el.text.strip()
            print(f"📅 服务器开始时间: {start_time_str}")

            start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M")
            expiry_time = start_time + timedelta(hours=6)
            expiry_time_str = expiry_time.strftime("%Y-%m-%d %H:%M")

            print(f"⏰ 服务器到期时间: {expiry_time_str} (有效期6小时)")
            return start_time_str, expiry_time_str
    except Exception as e:
        print(f"⚠️ 获取服务器时间信息失败: {e}")
    return None, None

# ========== 单次登录尝试（填写表单 + 处理验证码 + 点击登录） ==========
def perform_login_attempt(sb, email, password, attempt_number):
    """执行一次完整的登录尝试，返回 (success, url)"""
    print(f"\n🔄 登录尝试 {attempt_number}/2")

    # 1. 打开登录页
    print("🌐 打开登录页面...")
    sb.open(BASE_URL)
    sb.wait_for_ready_state_complete()
    sb.sleep(1)
    screenshot_step(sb, f"attempt_{attempt_number}_page_loaded")

    # 2. 填写邮箱
    print("📧 填写邮箱...")
    sb.type('#login_form_email', email, timeout=10)
    screenshot_step(sb, f"attempt_{attempt_number}_email_filled")

    # 3. 填写密码
    print("🔑 填写密码...")
    sb.type('#login_form_password', password, timeout=10)
    screenshot_step(sb, f"attempt_{attempt_number}_password_filled")

    # 4. 等待60秒（让 Turnstile 加载）
    print("⏳ 等待60秒，确保 Turnstile 验证码完全加载...")
    time.sleep(60)
    screenshot_step(sb, f"attempt_{attempt_number}_after_60s_wait")

    # 5. 处理 Turnstile
    print("🛡 处理 Turnstile...")
    try:
        sb.uc_gui_click_captcha()   # 原样保留，未作修改
        print("✅ Turnstile 验证已处理")
    except Exception as e:
        print(f"⚠️ uc_gui_click_captcha 执行异常: {e}")
    screenshot_step(sb, f"attempt_{attempt_number}_captcha_handled")

    # 6. 等待6秒（让验证生效）
    print("⏳ 等待6秒，让验证生效...")
    time.sleep(6)
    screenshot_step(sb, f"attempt_{attempt_number}_after_6s_wait")

    # 7. 点击登录按钮
    print("🔑 点击登录按钮...")
    sb.uc_click('button:contains("Sign in")')
    screenshot_step(sb, f"attempt_{attempt_number}_login_clicked")
    sb.sleep(5)

    # 8. 等待跳转，检查是否成功
    for i in range(30):
        current_url = sb.get_current_url()
        page_title = sb.get_title() or ""
        print(f"📄 当前 URL: {current_url} | Title: {page_title}")

        if "chrome-error" in current_url:
            print("⚠️ 检测到 chrome-error 页面，尝试刷新...")
            sb.refresh()
            sb.sleep(3)
            continue

        if "panel" in current_url:
            print("✅ 登录成功，已跳转到 Dashboard")
            screenshot_step(sb, f"attempt_{attempt_number}_login_success")
            return True, current_url
        time.sleep(1)

    # 如果循环结束仍未成功
    print(f"❌ 登录尝试 {attempt_number} 失败，当前 URL: {sb.get_current_url()}")
    screenshot_step(sb, f"attempt_{attempt_number}_login_failed")
    sb.save_screenshot(f"login_failed_attempt_{attempt_number}.png")
    return False, sb.get_current_url()

# ========== 登录主函数（含重试） ==========
def login(sb, email, password):
    # 设置超时（通过 driver 对象）
    try:
        sb.driver.set_page_load_timeout(60)
        sb.driver.set_script_timeout(60)
    except Exception as e:
        print(f"⚠️ 设置超时失败: {e}")

    # 最多尝试2次
    for attempt in range(1, 3):
        success, url = perform_login_attempt(sb, email, password, attempt)
        if success:
            return True, url

    # 所有尝试均失败
    return False, sb.get_current_url()

# ========== 🆕 调度函数：通过 cron-job.org API 创建一次性任务 ==========
def schedule_via_cronjob(trigger_timestamp, gh_token, repo, workflow_id, api_key, branch="main"):
    """
    通过 cron-job.org API 创建一个一次性定时任务，
    任务会在 trigger_timestamp（Unix 时间戳）时刻向 GitHub workflow_dispatch API 发送 POST 请求。
    返回: bool 是否成功创建
    """
    dt = datetime.fromtimestamp(trigger_timestamp)
    # 构造精确到分钟的调度（使用 UTC 时区）
    schedule = {
        "minutes": [dt.minute],
        "hours": [dt.hour],
        "mdays": [dt.day],
        "months": [dt.month],
        "wdays": [-1],          # 不限定星期几
        "timezone": "UTC",
        "expiresAt": (dt + timedelta(minutes=1)).strftime("%Y%m%d%H%M%S")  # 触发后1分钟过期
    }

    # GitHub workflow_dispatch 的 URL
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/dispatches"

    # 构建请求体（包含 headers 和 body）
    payload = {
        "job": {
            "enabled": True,
            "title": f"Trigger renewal at {dt.isoformat()}",
            "url": url,
            "requestMethod": 1,   # 1 = POST
            "extendedData": {
                "headers": {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {gh_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Content-Type": "application/json"
                },
                "body": json.dumps({"ref": branch})   # 指定工作流运行的分支
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.put("https://api.cron-job.org/jobs", headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            job_id = resp.json().get("jobId")
            print(f"✅ 已创建 cron 任务 (ID: {job_id})，触发时间: {dt}")
            return True
        else:
            print(f"❌ 创建 cron 任务失败: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 调用 cron-job.org API 异常: {e}")
        return False

# ========== 主流程 ==========
def main():
    print("🚀 启动浏览器")
    if PROXY_SERVER:
        print(f"🔗 使用代理: {PROXY_SERVER}")
    else:
        print("🍭 未使用代理，直连访问")

    # 获取并显示出口 IP
    ip = get_current_ip(PROXY_SERVER or None)
    print(f"📍 当前出口 IP: {ip}")

    # 获取北京时间
    beijing_time = get_beijing_time()

    # 构建基础通知头（不含 URL）
    base_header = (
        f"🌹 Therose cloud 自动续期\n"
        f"👤 账号: {EMAIL}\n"
        f"🕐 北京时间: {beijing_time}"
    )

    with SB(uc=True, headless=False, proxy=PROXY_SERVER or None,
            page_load_strategy='eager') as sb:
        success, url = login(sb, EMAIL, PASSWORD)

        if not success:
            msg = f"{base_header}\n\n❌ 登录失败，请检查账号密码、代理或网络\nhttps://therose.cloud/"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        # 登录成功后打开服务器列表页面
        print("🌐 打开服务器列表页面...")
        sb.open("https://client.therose.cloud/panel?routeName=servers")
        sb.sleep(3)
        screenshot_step(sb, "server_list")

        # 获取开始时间和计算的到期时间
        start_time, expiry_time = get_server_time_info(sb)

        # 构建时间信息和 URL 行
        url_line = "\nhttps://therose.cloud/"
        if start_time and expiry_time:
            time_info = f"\n📅 开始: {start_time}\n⏰ 到期: {expiry_time}"
            print(f"📅 服务器开始时间: {start_time}")
            print(f"⏰ 服务器到期时间: {expiry_time} (有效期6小时)")
        else:
            time_info = "\n⚠️ 未获取到时间信息"
            print("⚠️ 无法获取服务器时间信息")

        # 开始续期流程
        print("📄 开始续期流程...")
        ok, info = click_extend_button(sb)
        if not ok:
            msg = f"{base_header}\n\n❌ 点击 Extend 按钮失败: {info.get('error')}{time_info}{url_line}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        time.sleep(1)
        screenshot_step(sb, "extend_clicked")

        # 点击 Order now
        try:
            button = sb.find_element('button:contains("Order now")', timeout=5)
            if button:
                print("🛒 点击 Order now 按钮...")
                sb.uc_click('button:contains("Order now")')
                print("✅ 已点击 Order now 按钮")
                screenshot_step(sb, "ordernow_clicked")
            else:
                msg = f"{base_header}\n\n❌ 未找到 Order now 按钮{time_info}{url_line}"
                print(msg)
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
                return
        except Exception as e:
            msg = f"{base_header}\n\n❌ 点击 Order now 失败: {e}{time_info}{url_line}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        # 检查续期结果
        print("🔍 检查续期结果...")
        renewal_success, renewal_msg = check_renewal_success(sb)
        screenshot_step(sb, "renewal_result")

        # 构建最终消息（无论成功或失败都包含时间信息 + URL）
        if renewal_success:
            msg = f"{base_header}\n\n✅ 续期成功！{renewal_msg}{time_info}{url_line}"
            print(msg)
            sb.save_screenshot("renewal_success.png")
        else:
            msg = f"{base_header}\n\n❌ 续期可能失败: {renewal_msg}{time_info}{url_line}"
            print(msg)
            sb.save_screenshot("renewal_failed.png")

        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)

        # ========== 🆕 新增：自我调度（仅在续期成功且环境变量齐全时执行） ==========
        if renewal_success:
            print("🔄 续期成功，开始重新获取新的到期时间以安排下次执行...")
            # 重新刷新服务器列表页面以获取最新开始时间
            sb.open("https://client.therose.cloud/panel?routeName=servers")
            sb.sleep(3)
            new_start, new_expiry = get_server_time_info(sb)
            if new_expiry:
                # 解析时间为 datetime 对象（无时区）
                expiry_dt = datetime.strptime(new_expiry, "%Y-%m-%d %H:%M")
                
                # ===== 关键：将北京时间（UTC+8）转换为 UTC =====
                expiry_dt_utc = expiry_dt - timedelta(hours=8)
                expiry_ts = expiry_dt_utc.timestamp()

                # 检查所需环境变量是否齐全
                if not all([GH_TOKEN, GH_REPO, GH_WORKFLOW_ID, CRONJOB_API_KEY]):
                    print("⚠️ 缺少必要的环境变量（GH_TOKEN/GH_REPO/GH_WORKFLOW_ID/CRONJOB_API_KEY），跳过调度")
                else:
                    # 安排两次触发：到期前 20 分钟 和 10 分钟
                    for minutes_before in [20, 10]:
                        trigger_ts = expiry_ts - (minutes_before * 60)
                        # 确保触发时间在未来（至少1分钟后）
                        if trigger_ts > time.time() + 60:
                            success_schedule = schedule_via_cronjob(
                                trigger_ts, GH_TOKEN, GH_REPO, GH_WORKFLOW_ID, CRONJOB_API_KEY
                            )
                            if success_schedule:
                                print(f"✅ 已安排 {minutes_before} 分钟后触发")
                            else:
                                print(f"❌ 安排 {minutes_before} 分钟后触发失败")
                        else:
                            print(f"⚠️ 触发时间 {datetime.fromtimestamp(trigger_ts)} 已过期或太近，跳过")
            else:
                print("⚠️ 未能获取新的到期时间，跳过调度")
        else:
            print("ℹ️ 续期未成功，不安排下次执行（避免死循环）")
        # ========== 调度结束 ==========

    print("🏁 脚本执行完毕")

if __name__ == "__main__":
    main()
