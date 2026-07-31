#!/usr/bin/env python3

import os
import sys
import time
import requests
import json
from datetime import datetime, timedelta
from seleniumbase import SB
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ========== 环境变量 ==========
EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY_SERVER = os.environ.get("PROXY_SERVER") or ""

CRONJOB_API_KEY = os.environ.get("CRONJOB_API_KEY") or ""
GH_TOKEN = os.environ.get("GH_TOKEN") or ""
GH_REPO = os.environ.get("GH_REPO") or ""
GH_WORKFLOW_ID = os.environ.get("GH_WORKFLOW_ID") or ""

FORCE_SCHEDULE = os.environ.get("FORCE_SCHEDULE", "false").lower() == "true"

BASE_URL = "https://client.therose.cloud/login"

if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)

# ========== 辅助函数 ==========
def screenshot_step(sb, step_name):
    timestamp = int(time.time() * 1000)
    filename = f"step_{step_name}_{timestamp}.png"
    try:
        sb.save_screenshot(filename)
        print(f"📸 截图已保存: {filename}")
    except Exception as e:
        print(f"⚠️ 截图失败: {e}")

def send_tg(token, chat_id, message):
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
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

# ========== 点击 Extend 按钮（使用 JS 点击） ==========
def click_extend_button(sb):
    selectors = [
        'span:contains("Extend")',
        'button:contains(title="Extend")',
        'button:contains("Extend")',
    ]
    for sel in selectors:
        try:
            element = sb.find_element(sel, timeout=3)
            if element:
                print(f"✅ 找到 Extend 按钮，选择器: {sel}")
                sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.5)
                sb.driver.execute_script("arguments[0].click();", element)
                print("✅ 点击 Extend 成功")
                return True, {}
        except Exception as e:
            print(f"⚠️ 选择器 {sel} 失败: {e}")
            continue
    try:
        buttons = sb.find_elements('button')
        for btn in buttons:
            text = btn.text.strip().lower()
            if 'extend' in text:
                sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(0.5)
                sb.driver.execute_script("arguments[0].click();", btn)
                print("✅ 通过遍历点击 Extend 成功")
                return True, {}
    except Exception as e:
        return False, {"error": str(e)}
    return False, {"error": "未找到 Extend 按钮"}

# ========== 点击确认按钮 ==========
def click_confirm_choices(sb):
    confirm_selectors = [
        'button:contains("Confirm choices")',
        'button:contains("Confirm")',
        'button:contains("Yes")',
        'button:contains("确定")',
        'button:contains("确认")',
        'button[type="submit"]:contains("Confirm")',
        'button[class*="confirm"]',
    ]
    for sel in confirm_selectors:
        try:
            element = sb.find_element(sel, timeout=2)
            if element and element.is_displayed():
                print(f"✅ 发现确认按钮: {sel}")
                sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.5)
                sb.driver.execute_script("arguments[0].click();", element)
                print("✅ 点击确认按钮成功")
                return True
        except Exception as e:
            print(f"⚠️ 选择器 {sel} 失败: {e}")
            continue
    try:
        buttons = sb.find_elements('button')
        for btn in buttons:
            text = btn.text.strip().lower()
            if 'confirm' in text or 'yes' in text or '确定' in text or '确认' in text:
                sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(0.5)
                sb.driver.execute_script("arguments[0].click();", btn)
                print("✅ 通过遍历点击确认按钮成功")
                return True
    except Exception as e:
        print(f"⚠️ 遍历确认按钮失败: {e}")
    return False

# ========== 最终点击 Order now ==========
def click_order_now(sb):
    print("⏳ 等待页面加载...")
    time.sleep(3)

    current_url = sb.get_current_url()
    print(f"📄 当前 URL: {current_url}")

    if "cart_renew" not in current_url:
        print("🔍 检测到可能需要在当前页面点击确认按钮")
        if click_confirm_choices(sb):
            print("✅ 点击确认按钮后，等待跳转...")
            time.sleep(5)
            current_url = sb.get_current_url()
            print(f"📄 点击确认后 URL: {current_url}")

    try:
        wait = WebDriverWait(sb.driver, 20)
        element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#order-submit")))
        if element:
            print("✅ 检测到 Order now 按钮 (ID: #order-submit)")
            sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.5)
            sb.driver.execute_script("arguments[0].click();", element)
            print("✅ 点击 Order now 成功")
            return True, ""
    except Exception as e:
        print(f"⚠️ 等待/点击 #order-submit 失败: {e}")

    strategies = [
        ('button:contains("Order now")', '精确文本'),
        ('button:contains("Order")', '包含 Order'),
        ('button[type="submit"]', 'type=submit'),
        ('button:contains("购买")', '中文购买'),
        ('button:contains("续期")', '续期'),
        ('a:contains("Order")', 'a 标签'),
        ('span:contains("Order")', 'span'),
        ('//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "order")]', 'XPath'),
    ]
    for selector, desc in strategies:
        try:
            element = sb.find_element(selector, timeout=2)
            if element:
                print(f"🛒 备用策略 '{desc}' 找到元素，选择器: {selector}")
                sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.5)
                sb.driver.execute_script("arguments[0].click();", element)
                print("✅ 点击成功 (备用策略)")
                return True, ""
        except Exception as e:
            continue

    try:
        buttons = sb.find_elements('button')
        for btn in buttons:
            text = btn.text.strip().lower()
            if any(kw in text for kw in ['order', 'renew', 'confirm', 'purchase', 'buy', '立即购买', '续期']):
                print(f"🛒 通过遍历按钮找到: {text[:30]}")
                sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(0.5)
                sb.driver.execute_script("arguments[0].click();", btn)
                print("✅ 点击成功 (遍历按钮)")
                return True, ""
    except Exception as e:
        print(f"⚠️ 遍历按钮失败: {e}")

    return False, "未找到任何可点击的 Order/Renew/购买 按钮"

# ========== 检查续期结果 ==========
def check_renewal_success(sb):
    success_selectors = [
        '.alert-success',
        '.alert.alert-success',
        'div[role="alert"].alert-success',
        'div.alert-success',
        'span:contains("successfully purchased")',
        'div:contains("successfully purchased")',
        'span:contains("purchased successfully")',
        'div:contains("purchased successfully")'
    ]
    print("⏳ 等待10秒检查续期结果...")
    time.sleep(10)
    for selector in success_selectors:
        try:
            element = sb.find_element(selector, timeout=3)
            if element:
                text = element.text
                print(f"✅ 发现成功提示！选择器: {selector}")
                print(f"📝 提示内容: {text}")
                return True, text
        except:
            continue
    try:
        page_source = sb.get_page_source()
        if "successfully purchased" in page_source.lower() or "purchased successfully" in page_source.lower():
            print("✅ 页面源码中发现成功关键词")
            return True, "服务器已成功续期"
    except:
        pass
    return False, "未检测到续期成功提示"

# ========== 获取服务器到期时间 ==========
def get_server_time_info(sb, refresh=False):
    try:
        if refresh:
            print("🔄 刷新服务器列表页面以获取最新到期时间...")
            sb.open("https://client.therose.cloud/panel?routeName=servers")
            sb.sleep(3)
            screenshot_step(sb, "refresh_server_list")
        el = sb.find_element('span.fw-bold.text-muted', timeout=10)
        if el:
            time_str = el.text.strip()
            print(f"📅 服务器到期时间 (UTC): {time_str}")
            datetime.strptime(time_str, "%Y-%m-%d %H:%M")
            return time_str
    except Exception as e:
        print(f"⚠️ 获取服务器时间信息失败: {e}")
    return None

# ========== 登录相关 ==========
def perform_login_attempt(sb, email, password, attempt_number):
    print(f"\n🔄 登录尝试 {attempt_number}/2")
    print("🌐 打开登录页面...")
    sb.open(BASE_URL)
    sb.wait_for_ready_state_complete()
    sb.sleep(1)
    screenshot_step(sb, f"attempt_{attempt_number}_page_loaded")

    print("📧 填写邮箱...")
    sb.type('#login_form_email', email, timeout=10)
    screenshot_step(sb, f"attempt_{attempt_number}_email_filled")

    print("🔑 填写密码...")
    sb.type('#login_form_password', password, timeout=10)
    screenshot_step(sb, f"attempt_{attempt_number}_password_filled")

    print("⏳ 等待60秒，确保 Turnstile 验证码完全加载...")
    time.sleep(60)
    screenshot_step(sb, f"attempt_{attempt_number}_after_60s_wait")

    print("🛡 处理 Turnstile...")
    try:
        sb.uc_gui_click_captcha()
        print("✅ Turnstile 验证已处理")
    except Exception as e:
        print(f"⚠️ uc_gui_click_captcha 执行异常: {e}")
    screenshot_step(sb, f"attempt_{attempt_number}_captcha_handled")

    print("⏳ 等待6秒，让验证生效...")
    time.sleep(6)
    screenshot_step(sb, f"attempt_{attempt_number}_after_6s_wait")

    print("🔑 点击登录按钮...")
    sb.uc_click('button:contains("Sign in")')
    screenshot_step(sb, f"attempt_{attempt_number}_login_clicked")
    sb.sleep(5)

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

    print(f"❌ 登录尝试 {attempt_number} 失败，当前 URL: {sb.get_current_url()}")
    screenshot_step(sb, f"attempt_{attempt_number}_login_failed")
    sb.save_screenshot(f"login_failed_attempt_{attempt_number}.png")
    return False, sb.get_current_url()

def login(sb, email, password):
    try:
        sb.driver.set_page_load_timeout(120)
        sb.driver.set_script_timeout(120)
    except Exception as e:
        print(f"⚠️ 设置超时失败: {e}")

    for attempt in range(1, 3):
        success, url = perform_login_attempt(sb, email, password, attempt)
        if success:
            return True, url
    return False, sb.get_current_url()

# ========== 调度：全局唯一任务 ==========
def schedule_via_cronjob(trigger_timestamp, gh_token, repo, workflow_id, api_key, branch="main"):
    dt = datetime.fromtimestamp(trigger_timestamp)
    schedule = {
        "minutes": [dt.minute],
        "hours": [dt.hour],
        "mdays": [dt.day],
        "months": [dt.month],
        "wdays": [-1],
        "timezone": "UTC",
        "expiresAt": (dt + timedelta(minutes=5)).strftime("%Y%m%d%H%M%S")
    }

    dispatch_url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/dispatches"

    payload = {
        "job": {
            "enabled": True,
            "url": dispatch_url,
            "requestMethod": 1,
            "saveResponses": True,
            "schedule": schedule,
            "extendedData": {
                "headers": {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {gh_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Content-Type": "application/json",
                    "User-Agent": "cron-job.org/1.0"
                },
                "body": json.dumps({"ref": branch})
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    print(f"📤 调度触发时间: {dt}")

    try:
        resp = requests.get("https://api.cron-job.org/jobs", headers=headers, timeout=30)
        resp.raise_for_status()
        jobs_data = resp.json()
        jobs = jobs_data.get("jobs", [])
        print(f"📋 现有任务数量: {len(jobs)}")

        matching_jobs = [j for j in jobs if j.get("url") == dispatch_url]

        for job in matching_jobs[1:]:
            job_id = job.get("jobId")
            if job_id:
                del_resp = requests.delete(f"https://api.cron-job.org/jobs/{job_id}", headers=headers, timeout=30)
                if del_resp.status_code == 200:
                    print(f"🗑️ 已删除多余的 job {job_id}")
                else:
                    print(f"⚠️ 删除 job {job_id} 失败: {del_resp.status_code}")

        if matching_jobs:
            job_id = matching_jobs[0].get("jobId")
            print(f"🔄 更新现有任务 ID: {job_id}")
            update_resp = requests.patch(
                f"https://api.cron-job.org/jobs/{job_id}",
                headers=headers,
                json=payload,
                timeout=30
            )
            if update_resp.status_code == 200:
                print(f"✅ 任务已更新，ID: {job_id}")
                return True
            else:
                print(f"❌ 更新任务失败: {update_resp.status_code} {update_resp.text}")
                return False
        else:
            print("📤 创建新任务...")
            create_resp = requests.put("https://api.cron-job.org/jobs", headers=headers, json=payload, timeout=30)
            if create_resp.status_code == 200:
                job_id = create_resp.json().get("jobId")
                print(f"✅ cron-job 创建成功，ID: {job_id}")
                return True
            else:
                print(f"❌ 创建任务失败: {create_resp.status_code} {create_resp.text}")
                return False
    except Exception as e:
        print(f"❌ 操作 cron-job.org API 异常: {e}")
        return False

# ========== 主流程 ==========
def main():
    print("🚀 启动浏览器")
    if PROXY_SERVER:
        print(f"🔗 使用代理: {PROXY_SERVER}")
    else:
        print("🍭 未使用代理，直连访问")

    ip = get_current_ip(PROXY_SERVER or None)
    print(f"📍 当前出口 IP: {ip}")

    beijing_time = get_beijing_time()
    base_header = (
        f"🌹 Therose cloud 自动续期\n"
        f"👤 账号: {EMAIL}\n"
        f"🕐 当前北京时间: {beijing_time}"
    )

    # 修正：移除 driver_timeout 参数
    with SB(uc=True, headless=False, proxy=PROXY_SERVER or None,
            page_load_strategy='eager') as sb:
        # 超时已在 login 中设置，但为确保也可在此处设置
        try:
            sb.driver.set_page_load_timeout(120)
            sb.driver.set_script_timeout(120)
        except:
            pass

        success, url = login(sb, EMAIL, PASSWORD)

        if not success:
            msg = f"{base_header}\n\n❌ 登录失败，请检查账号密码、代理或网络\nhttps://therose.cloud/"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        print("🌐 打开服务器列表页面...")
        sb.open("https://client.therose.cloud/panel?routeName=servers")
        sb.sleep(3)
        screenshot_step(sb, "server_list")

        expiry_time_utc_str = get_server_time_info(sb)
        if expiry_time_utc_str:
            expiry_dt = datetime.strptime(expiry_time_utc_str, "%Y-%m-%d %H:%M")
            expiry_beijing = expiry_dt + timedelta(hours=8)
            expiry_beijing_str = expiry_beijing.strftime("%Y-%m-%d %H:%M")
            time_info = f"\n⏰ 到期 (北京时间): {expiry_beijing_str}"
            print(f"⏰ 到期 (UTC): {expiry_time_utc_str} -> 北京时间: {expiry_beijing_str}")
        else:
            time_info = "\n⚠️ 未获取到时间信息"
            expiry_time_utc_str = None

        url_line = "\nhttps://therose.cloud/"

        print("📄 开始续期流程...")
        ok, info = click_extend_button(sb)
        if not ok:
            msg = f"{base_header}\n\n❌ 点击 Extend 按钮失败: {info.get('error')}{time_info}{url_line}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        order_ok, order_err = click_order_now(sb)
        if not order_ok:
            msg = f"{base_header}\n\n❌ 点击 Order now 失败: {order_err}{time_info}{url_line}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        screenshot_step(sb, "ordernow_clicked")

        print("🔍 检查续期结果...")
        renewal_success, renewal_msg = check_renewal_success(sb)
        screenshot_step(sb, "renewal_result")

        if renewal_success:
            print("✅ 续期成功，重新获取最新到期时间...")
            new_expiry_utc_str = get_server_time_info(sb, refresh=True)
            if new_expiry_utc_str:
                expiry_time_utc_str = new_expiry_utc_str
                expiry_dt = datetime.strptime(expiry_time_utc_str, "%Y-%m-%d %H:%M")
                expiry_beijing = expiry_dt + timedelta(hours=8)
                expiry_beijing_str = expiry_beijing.strftime("%Y-%m-%d %H:%M")
                time_info = f"\n⏰ 到期 (北京时间): {expiry_beijing_str}"
                print(f"⏰ 最新的到期 (UTC): {expiry_time_utc_str} -> 北京时间: {expiry_beijing_str}")
            else:
                print("⚠️ 重新获取时间失败，将使用之前的时间")
        else:
            print("ℹ️ 续期未成功，不重新获取时间")

        if renewal_success:
            msg = f"{base_header}\n\n✅ 续期成功！{renewal_msg}{time_info}{url_line}"
            print(msg)
            sb.save_screenshot("renewal_success.png")
        else:
            msg = f"{base_header}\n\n❌ 续期可能失败: {renewal_msg}{time_info}{url_line}"
            print(msg)
            sb.save_screenshot("renewal_failed.png")

        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)

        should_schedule = (renewal_success or FORCE_SCHEDULE) and expiry_time_utc_str is not None

        if should_schedule:
            if FORCE_SCHEDULE and not renewal_success:
                print("🔄 强制调度模式已开启：即使续期未成功，仍安排下次执行（首次运行）")
            elif renewal_success:
                print("🔄 续期成功，开始安排下次执行...")
            else:
                print("🔄 开始安排下次执行...")

            expiry_dt = datetime.strptime(expiry_time_utc_str, "%Y-%m-%d %H:%M")
            expiry_ts = expiry_dt.timestamp()

            if not all([GH_TOKEN, GH_REPO, GH_WORKFLOW_ID, CRONJOB_API_KEY]):
                print("⚠️ 缺少必要的环境变量，跳过调度")
            else:
                minutes_before = 20
                trigger_ts = expiry_ts - (minutes_before * 60)
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
            if not renewal_success:
                print("ℹ️ 续期未成功，且未开启强制调度，不安排下次执行（避免死循环）")
            else:
                print("⚠️ 未获取到到期时间，跳过调度")

    print("🏁 脚本执行完毕")

if __name__ == "__main__":
    main()
