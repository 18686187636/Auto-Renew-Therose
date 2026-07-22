#!/usr/bin/env python3
import os, time, requests, sys
from seleniumbase import SB

# ===== 环境变量 =====
EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)

def send_tg(token, chat_id, message):
    if not token or not chat_id:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": message}, timeout=10)
    except:
        pass

def login(sb):
    print("🌐 打开登录页面...")
    sb.open("https://client.therose.cloud/login")
    sb.wait_for_ready_state_complete()
    sb.sleep(2)  # 等待页面完全加载

    print("📧 填写邮箱...")
    sb.type('#login_form_email', EMAIL, timeout=10)
    print("🔑 填写密码...")
    sb.type('#login_form_password', PASSWORD, timeout=10)
    time.sleep(1)

    print("🛡 处理 Turnstile...")
    try:
        if HEADLESS:
            # 无头模式：使用自动点击
            sb.uc_click_captcha()
        else:
            # 有头模式：弹出 GUI 验证窗口
            sb.uc_gui_click_captcha()
        print("✅ Turnstile 验证已处理")
    except Exception as e:
        print(f"⚠️ 验证码处理异常: {e}")
        # 尝试备用方法：直接点击 iframe
        try:
            sb.uc_click('iframe[src*="turnstile"]', timeout=5)
            print("✅ 通过点击 iframe 尝试处理")
        except:
            print("❌ 所有验证码处理方法均失败")

    # 登录前截图（用于调试）
    sb.save_screenshot("before_login.png")

    print("🔑 点击登录按钮...")
    sb.uc_click('button:contains("Sign in")')
    sb.sleep(3)

    # 等待跳转
    for _ in range(30):
        current_url = sb.get_current_url()
        if "panel" in current_url:
            print("✅ 登录成功，已跳转到 Dashboard")
            return True
        time.sleep(1)

    print(f"❌ 登录失败，当前 URL: {current_url}")
    sb.save_screenshot("login_failed.png")
    # 打印页面源码片段帮助排查
    print("📄 页面源码片段（前500字符）：")
    print(sb.get_page_source()[:500])
    return False

def get_expiry(sb):
    xpath = '/html/body/div[1]/section/div/div[1]/div[2]/div/div/div/div[2]/div[2]/div[2]/div/span'
    try:
        sb.open("https://client.therose.cloud/panel?routeName=servers")
        sb.sleep(3)
        el = sb.find_element(f"xpath={xpath}", timeout=10)
        if el:
            return el.text.strip()
    except Exception as e:
        print(f"⚠️ 获取有效期失败: {e}")
    return "未知"

def click_extend(sb):
    selectors = ['span:contains("Extend")', 'button[title="Extend"]']
    for sel in selectors:
        try:
            sb.uc_click(sel, timeout=3)
            return True
        except:
            continue
    try:
        sb.driver.execute_script("document.querySelector('button:contains(\"Extend\")')?.click();")
        return True
    except:
        return False

def check_renewal(sb):
    time.sleep(5)
    success_keywords = ["successfully purchased", "alert-success"]
    page = sb.get_page_source().lower()
    if any(k in page for k in success_keywords):
        return True
    return False

def main():
    print(f"🚀 启动浏览器 (headless={HEADLESS})")
    with SB(uc=True, headless=HEADLESS) as sb:
        if not login(sb):
            msg = "❌ 登录失败，请检查账号密码或验证码"
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        # 进入服务器列表
        sb.open("https://client.therose.cloud/panel?routeName=servers")
        sb.sleep(3)
        expiry = get_expiry(sb)
        print(f"📅 当前有效期: {expiry}")

        if not click_extend(sb):
            msg = "❌ 点击 Extend 按钮失败"
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        time.sleep(1)
        try:
            sb.uc_click('button:contains("Order now")', timeout=5)
            print("✅ 已点击 Order now")
        except Exception as e:
            msg = f"❌ 点击 Order now 失败: {e}"
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        success = check_renewal(sb)
        if success:
            msg = f"✅ 续期成功！有效期: {expiry}"
            sb.save_screenshot("renewal_success.png")
        else:
            msg = f"❌ 续期可能失败，有效期: {expiry}"
            sb.save_screenshot("renewal_failed.png")
        print(msg)
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)

if __name__ == "__main__":
    main()
