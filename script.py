#!/usr/bin/env python3

import os
import sys
import time
import requests
import json
from datetime import datetime, timedelta
from seleniumbase import SB

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

# 续期页面 ID，默认 2635，可通过环境变量覆盖
SERVER_RENEW_ID = os.environ.get("SERVER_RENEW_ID", "2635")
RENEW_URL = f"https://client.therose.cloud/panel?routeName=cart_renew&id={SERVER_RENEW_ID}"

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
        return filename
    except Exception as e:
        print(f"⚠️ 截图失败: {e}")
        return None

def send_tg_text(token, chat_id, message):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        if resp.status_code == 200:
            print("📨 Telegram 文本通知已发送")
        else:
            print(f"❌ Telegram 发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")

def send_tg_photo(token, chat_id, photo_path, caption=""):
    if not token or not chat_id:
        return
    if not photo_path or not os.path.exists(photo_path):
        print(f"⚠️ 图片 {photo_path} 不存在，跳过发送")
        return
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            files = {'photo': f}
            data = {'chat_id': chat_id, 'caption': caption}
            resp = requests.post(url, files=files, data=data, timeout=20)
        if resp.status_code == 200:
            print(f"📸 截图已通过 Telegram 发送: {photo_path}")
        else:
            print(f"❌ Telegram 发送图片失败: {resp.text}")
    except Exception as e:
        print(f"❌ 发送图片异常: {e}")

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

# ========== 点击 Extend ==========
def click_extend_button(sb):
    try:
        sb.click('span:contains("Extend")', timeout=3)
        print("✅ 点击 Extend 成功")
        return True, {}
    except Exception as e:
        return False, {"error": str(e)}

# ========== 关闭广告弹窗 ==========
def close_ad_popup(sb):
    """
    关闭续期页面上的广告弹窗（如 "Watch an advertisement to access the site"）。
    """
    # 1. 尝试点击关闭按钮
    close_selectors = [
        'button:contains("×")',
        'button:contains("Close")',
        'button:contains("关闭")',
        '.modal-close',
        '.close',
        '[aria-label="Close"]',
        'button[data-dismiss="modal"]',
        '.ad-close',
        '#ad-close'
    ]
    for sel in close_selectors:
        try:
            elem = sb.find_element(sel, timeout=2)
            if elem:
                sb.click(sel)
                print(f"✅ 已点击广告关闭按钮: {sel}")
                time.sleep(1)
                return True
        except:
            continue

    # 2. 尝试通过文本定位并移除
    try:
        ad_elem = sb.find_element('*:contains("Watch an advertisement")', timeout=2)
        if ad_elem:
            print("⚠️ 找到广告文本，使用 JavaScript 移除弹窗...")
            sb.driver.execute_script("""
                var elems = document.querySelectorAll('div, section, article');
                for(var i=0; i<elems.length; i++) {
                    if(elems[i].innerText && elems[i].innerText.indexOf('Watch an advertisement') !== -1) {
                        var parent = elems[i].closest('div[style*="position"], div[class*="modal"], div[class*="overlay"]');
                        if(parent) parent.remove();
                        else elems[i].remove();
                        break;
                    }
                }
            """)
            print("✅ 已通过 JavaScript 移除广告弹窗")
            time.sleep(1)
            return True
    except:
        pass

    # 3. 若仍无法关闭，刷新页面（广告可能只出现一次）
    print("⚠️ 无法关闭广告，尝试刷新页面...")
    sb.refresh()
    time.sleep(3)
    return False

# ========== 点击 Order now（直接访问续期页面，避免 Consent 弹窗） ==========
def click_order_now(sb):
    """
    直接打开续期订单页，关闭广告，然后点击 Order now。
    避免因 Consent 弹窗导致的 WebDriver 会话中断。
    """
    # 1. 直接打开续期页面
    print(f"🌐 直接打开续期页面: {RENEW_URL}")
    sb.open(RENEW_URL)
    time.sleep(3)

    # 2. 关闭广告弹窗（若有）
    print("🔍 检查并关闭广告弹窗...")
    close_ad_popup(sb)

    # 3. 等待续期页面加载
    try:
        sb.wait_for_element_present('*:contains("Renew your server")', timeout=10)
        print("✅ 续期页面已加载")
    except:
        print("⚠️ 续期页面标题未出现，但继续尝试...")

    # 4. 打印当前状态
    current_url = sb.get_current_url()
    page_title = sb.get_title() or ""
    print(f"📍 当前 URL: {current_url}")
    print(f"📄 页面标题: {page_title}")

    # 5. 使用 ID 选择器点击 Order now
    order_selector = 'button#order-submit'
    try:
        elem = sb.wait_for_element_present(order_selector, timeout=10)
        if elem:
            sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", elem.webelement)
            time.sleep(0.5)
            sb.driver.execute_script("arguments[0].click();", elem.webelement)
            print(f"✅ 点击 Order now 成功，选择器: {order_selector}")
            return True, ""
    except Exception as e:
        print(f"⚠️ 点击 Order now 失败: {e}")

    # 6. 若失败，刷新页面重试一次
    try:
        print("🔄 刷新页面并重试...")
        sb.refresh()
        time.sleep(5)
        elem = sb.wait_for_element_present(order_selector, timeout=10)
        if elem:
            sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", elem.webelement)
            time.sleep(0.5)
            sb.driver.execute_script("arguments[0].click();", elem.webelement)
            print("✅ 刷新后点击 Order now 成功")
            return True, ""
    except Exception as e:
        print(f"⚠️ 刷新后重试仍失败: {e}")

    # 全部失败，保存截图并发送
    fail_img = screenshot_step(sb, "order_now_not_found")
    if fail_img:
        send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, fail_img, caption="❌ 未找到 Order now 按钮")
    return False, "未找到 Order now 按钮"

# ========== 检查续期结果 ==========
def check_renewal_result(sb):
    time.sleep(5)
    try:
        danger_elem = sb.find_element('div.alert-danger', timeout=3)
        if danger_elem is not None:
            text = danger_elem.text.strip()
            print(f"⚠️ 检测到错误提示: {text}")
            if "Renewal is available only within 30 minutes before expiration" in text:
                return "no_need", "未到期，需在到期前30分钟内续期（当前不满足）"
            else:
                return "error", f"续期出错: {text}"
    except:
        pass

    try:
        success_elem = sb.find_element('div.alert-success', timeout=3)
        if success_elem is not None:
            text = success_elem.text.strip()
            print(f"✅ 检测到成功提示: {text}")
            if "successfully purchased" in text or "success" in text.lower():
                return "success", "续期成功"
    except:
        pass

    return "unknown", "未检测到明确的续期结果"

# ========== 获取服务器到期时间 ==========
def get_server_time_info(sb, refresh=False):
    try:
        if refresh:
            print("🔄 刷新服务器列表页面以获取最新到期时间...")
            sb.open("https://client.therose.cloud/panel?routeName=servers")
            sb.sleep(3)
            screenshot_step(sb, "refresh_server_list")
        el = sb.find_element('span.fw-bold.text-muted', timeout=10)
        if el is not None:
            time_str = el.text.strip()
            print(f"📅 服务器到期时间 (UTC): {time_str}")
            datetime.strptime(time_str, "%Y-%m-%d %H:%M")
            return time_str
    except Exception as e:
        print(f"⚠️ 获取服务器时间信息失败: {e}")
    return None

# ========== 登录（保持不变） ==========
def perform_login_attempt(sb, email, password, attempt_number):
    print(f"\n🔄 登录尝试 {attempt_number}/2")
    print("🌐 打开登录页面...")
    sb.open(BASE_URL)
    sb.wait_for_ready_state_complete()
    time.sleep(3)
    screenshot_step(sb, f"attempt_{attempt_number}_page_loaded")

    email_selectors = [
        '#login_form_email',
        'input[type="email"]',
        'input[name="email"]',
        'input[placeholder*="email"]',
        'input[placeholder*="Email"]',
        'input[class*="email"]'
    ]
    email_input = None
    for sel in email_selectors:
        try:
            email_input = sb.find_element(sel, timeout=3)
            if email_input is not None:
                print(f"✅ 找到邮箱输入框，选择器: {sel}")
                break
        except:
            continue
    if email_input is None:
        print("❌ 未找到邮箱输入框，尝试刷新页面重试...")
        sb.refresh()
        time.sleep(5)
        for sel in email_selectors:
            try:
                email_input = sb.find_element(sel, timeout=3)
                if email_input is not None:
                    print(f"✅ 刷新后找到邮箱输入框，选择器: {sel}")
                    break
            except:
                continue
        if email_input is None:
            screenshot_step(sb, "email_input_not_found")
            return False, "未找到邮箱输入框"

    print("📧 填写邮箱...")
    email_input.clear()
    email_input.send_keys(email)
    screenshot_step(sb, f"attempt_{attempt_number}_email_filled")

    password_selectors = [
        '#login_form_password',
        'input[type="password"]',
        'input[name="password"]',
        'input[placeholder*="password"]',
        'input[placeholder*="Password"]'
    ]
    password_input = None
    for sel in password_selectors:
        try:
            password_input = sb.find_element(sel, timeout=3)
            if password_input is not None:
                print(f"✅ 找到密码输入框，选择器: {sel}")
                break
        except:
            continue
    if password_input is None:
        print("❌ 未找到密码输入框")
        return False, "未找到密码输入框"

    print("🔑 填写密码...")
    password_input.clear()
    password_input.send_keys(password)
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
    login_btn_selectors = [
        'button:contains("Sign in")',
        'button[type="submit"]',
        'button:contains("Login")',
        'button:contains("登录")'
    ]
    clicked = False
    for sel in login_btn_selectors:
        try:
            sb.click(sel, timeout=5)
            clicked = True
            print(f"✅ 点击登录按钮成功，选择器: {sel}")
            break
        except:
            continue
    if not clicked:
        print("❌ 未找到登录按钮")
        return False, "未找到登录按钮"

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

# ========== 调度（cron-job.org，保持不变） ==========
def schedule_via_cronjob(trigger_timestamp, gh_token, repo, workflow_id, api_key, branch="main", minutes_before=20):
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
    job_title = f"TheRose Renew {minutes_before}min"

    payload = {
        "job": {
            "enabled": True,
            "title": job_title,
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

    print(f"📤 调度任务 '{job_title}'，触发时间: {dt}")

    try:
        resp = requests.get("https://api.cron-job.org/jobs", headers=headers, timeout=30)
        resp.raise_for_status()
        jobs_data = resp.json()
        jobs = jobs_data.get("jobs", [])
        print(f"📋 现有任务数量: {len(jobs)}")

        matching_jobs = [j for j in jobs if j.get("title") == job_title]

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
            print(f"🔄 更新现有任务 ID: {job_id} ({job_title})")
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
            print(f"📤 创建新任务: {job_title}")
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

    with SB(uc=True, headless=False, proxy=PROXY_SERVER or None,
            page_load_strategy='eager') as sb:
        try:
            sb.driver.set_page_load_timeout(120)
            sb.driver.set_script_timeout(120)
        except:
            pass

        # ---------- 登录 ----------
        success, url = login(sb, EMAIL, PASSWORD)
        if not success:
            msg = f"{base_header}\n\n❌ 登录失败，请检查账号密码、代理或网络\nhttps://therose.cloud/"
            print(msg)
            send_tg_text(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            login_fail_img = "login_failed_attempt_2.png"
            if os.path.exists(login_fail_img):
                send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, login_fail_img, caption="登录失败截图")
            return

        login_success_img = screenshot_step(sb, "login_success")
        if login_success_img:
            send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, login_success_img, caption="✅ 登录成功")

        # ---------- 打开服务器列表 ----------
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

        # ---------- 续期流程 ----------
        print("📄 开始续期流程...")
        ok, info = click_extend_button(sb)
        if not ok:
            msg = f"{base_header}\n\n❌ 点击 Extend 按钮失败: {info.get('error')}{time_info}{url_line}"
            print(msg)
            send_tg_text(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        time.sleep(3)
        screenshot_step(sb, "extend_clicked")

        # 点击 Order now（直接访问续期页面，避免 Consent 弹窗）
        order_ok, order_err = click_order_now(sb)
        if not order_ok:
            msg = f"{base_header}\n\n❌ 点击 Order now 失败: {order_err}{time_info}{url_line}"
            print(msg)
            send_tg_text(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        screenshot_step(sb, "ordernow_clicked")

        # ---------- 检查续期结果 ----------
        status, result_msg = check_renewal_result(sb)
        if status in ("success", "no_need"):
            renewal_success = True
            renewal_msg = result_msg
        else:
            renewal_success = False
            renewal_msg = result_msg

        result_img = screenshot_step(sb, "renewal_result")
        if result_img:
            send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, result_img, caption=f"续期结果: {renewal_msg}")

        if renewal_success:
            print("✅ 续期成功（或无需续期），重新获取最新到期时间...")
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

        send_tg_text(TG_BOT_TOKEN, TG_CHAT_ID, msg)

        # ---------- 调度下次运行 ----------
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
                time_points = [20, 10]
                for minutes_before in time_points:
                    trigger_ts = expiry_ts - (minutes_before * 60)
                    if trigger_ts > time.time() + 60:
                        success_schedule = schedule_via_cronjob(
                            trigger_ts, GH_TOKEN, GH_REPO, GH_WORKFLOW_ID, CRONJOB_API_KEY,
                            branch="main", minutes_before=minutes_before
                        )
                        if success_schedule:
                            print(f"✅ 已安排 {minutes_before} 分钟后触发")
                        else:
                            print(f"❌ 安排 {minutes_before} 分钟后触发失败")
                        time.sleep(2)
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
