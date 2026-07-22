#!/usr/bin/env python3
import os, sys, time, requests
from seleniumbase import SB

EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

BASE_URL = "https://client.therose.cloud/login"

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

def login(sb, email, password):
    print("🌐 打开登录页面...")
    sb.open(BASE_URL)
    sb.wait_for_ready_state_complete()
    sb.sleep(1)

    print("📧 填写邮箱...")
    sb.type('#login_form_email', email, timeout=10)
    print("🔑 填写密码...")
    sb.type('#login_form_password', password, timeout=10)
    time.sleep(1)

    print("🛡 处理 Turnstile...")
    # 用 uc_click 点击 Turnstile iframe
    sb.uc_click('iframe[src*="turnstile"]', timeout=60)
    print("✅ Turnstile 验证已处理")

    print("🔑 点击登录按钮...")
    sb.uc_click('button:contains("Sign in")')
    sb.sleep(3)

    for _ in range(30):
        current_url = sb.get_current_url()
        if "panel" in current_url:
            print("✅ 登录成功，已跳转到 Dashboard")
            return True, current_url
        time.sleep(1)

    print(f"❌ 登录失败，当前 URL: {sb.get_current_url()}")
    sb.save_screenshot("login_failed.png")
    return False, sb.get_current_url()

def get_expiry(sb):
    xpath = '/html/body/div[1]/section/div/div[1]/div[2]/div/div/div/div[2]/div[2]/div[2]/div/span'
    try:
        sb.open("https://client.therose.cloud/panel?routeName=servers")
        sb.sleep(3)
        el = sb.find_element(f"xpath={xpath}", timeout=10)
        if el:
            return el.text.strip()
    except:
        pass
    return "未知"

def click_extend_button(sb):
    selectors = ['span:contains("Extend")', 'button[title="Extend"]']
    for sel in selectors:
        try:
            if sb.find_element(sel, timeout=2):
                sb.uc_click(sel, timeout=5)
                return True, {}
        except:
            continue
    try:
        sb.driver.execute_script("document.querySelector('button:contains(\"Extend\")')?.click();")
        return True, {}
    except Exception as e:
        return False, {"error": str(e)}

def check_renewal_success(sb):
    time.sleep(5)
    success_keywords = ["successfully purchased", "alert-success"]
    page = sb.get_page_source().lower()
    if any(k in page for k in success_keywords):
        return True, "服务器已成功续期"
    return False, "未检测到续期成功提示"

def main():
    print(f"🚀 启动浏览器 (headless={HEADLESS})")
    with SB(uc=True, headless=HEADLESS) as sb:
        success, url = login(sb, EMAIL, PASSWORD)
        if not success:
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, "❌ 登录失败")
            return

        sb.open("https://client.therose.cloud/panel?routeName=servers")
        sb.sleep(3)
        expiry = get_expiry(sb)
        print(f"📅 当前有效期: {expiry}")

        ok, info = click_extend_button(sb)
        if not ok:
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, f"❌ 点击 Extend 失败: {info.get('error')}")
            return

        time.sleep(1)
        try:
            sb.uc_click('button:contains("Order now")', timeout=5)
        except:
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, "❌ 点击 Order now 失败")
            return

        success, msg = check_renewal_success(sb)
        if success:
            msg = f"✅ 续期成功！{msg}\n📅 有效期: {expiry}"
            sb.save_screenshot("renewal_success.png")
        else:
            msg = f"❌ 续期可能失败: {msg}\n📅 有效期: {expiry}"
            sb.save_screenshot("renewal_failed.png")
        print(msg)
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)

if __name__ == "__main__":
    main()
