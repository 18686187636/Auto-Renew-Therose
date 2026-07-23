#!/usr/bin/env python3

import os, re, sys, time, requests
from seleniumbase import SB

# ========== 环境变量 ==========
EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY_SERVER = os.environ.get("PROXY_SERVER") or ""   # socks5://127.0.0.1:1080

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

# ========== 获取有效期 ==========
def get_expiry(sb):
    xpath = '/html/body/div[1]/section/div/div[1]/div[2]/div/div/div/div[2]/div[2]/div[2]/div/span'
    try:
        sb.open("https://client.therose.cloud/panel?routeName=servers")
        sb.sleep(3)
        el = sb.find_element(f"xpath={xpath}", timeout=10)
        if el:
            text = el.text.strip()
            print(f"📅 服务器有效期: {text}")
            return text
    except Exception as e:
        print(f"⚠️ 获取有效期失败: {e}")
    return "未知"

# ========== 登录流程（含等待、重试、截图） ==========
def login(sb, email, password):
    # 设置超时
    sb.set_page_load_timeout(60)
    sb.set_script_timeout(60)

    for attempt in range(2):  # 最多重试2次
        if attempt > 0:
            print(f"\n🔄 重试登录 (第 {attempt+1} 次)...")
            # 重新打开登录页
            sb.open(BASE_URL)
            sb.wait_for_ready_state_complete()
            sb.sleep(2)
            # 重新填写
            print("📧 重新填写邮箱...")
            sb.type('#login_form_email', email, timeout=10)
            print("🔑 重新填写密码...")
            sb.type('#login_form_password', password, timeout=10)
            screenshot_step(sb, "retry_filled")
            # 等待60秒
            print("⏳ 等待60秒，确保 Turnstile 验证码完全加载...")
            time.sleep(60)
            screenshot_step(sb, "retry_after_wait")
            # 处理 Turnstile
            print("🛡 处理 Turnstile...")
            try:
                sb.uc_gui_click_captcha()
                print("✅ Turnstile 验证已处理")
            except Exception as e:
                print(f"⚠️ uc_gui_click_captcha 执行异常: {e}")
            screenshot_step(sb, "retry_captcha_handled")
            # 等待6秒
            print("⏳ 等待6秒，让验证生效...")
            time.sleep(6)
            screenshot_step(sb, "retry_after_6s")

        # 点击登录按钮
        print("🔑 点击登录按钮...")
        sb.uc_click('button:contains("Sign in")')
        screenshot_step(sb, "login_clicked")
        sb.sleep(5)

        # 等待跳转
        for i in range(30):
            current_url = sb.get_current_url()
            page_title = sb.get_title() or ""
            print(f"📄 当前 URL: {current_url} | Title: {page_title}")

            # 如果出现 chrome-error，刷新后继续等待
            if "chrome-error" in current_url:
                print("⚠️ 检测到 chrome-error 页面，尝试刷新...")
                sb.refresh()
                sb.sleep(3)
                continue

            if "panel" in current_url:
                print("✅ 登录成功，已跳转到 Dashboard")
                screenshot_step(sb, "login_success")
                return True, current_url
            time.sleep(1)

        # 本次尝试失败，截图记录
        print(f"❌ 登录失败，当前 URL: {sb.get_current_url()}")
        screenshot_step(sb, f"login_failed_attempt_{attempt+1}")
        sb.save_screenshot(f"login_failed_attempt_{attempt+1}.png")

    # 所有重试均失败
    return False, sb.get_current_url()

# ========== 主流程 ==========
def main():
    print("🚀 启动浏览器")
    if PROXY_SERVER:
        print(f"🔗 使用代理: {PROXY_SERVER}")
    else:
        print("🍭 未使用代理，直连访问")

    # 启动浏览器（有头模式，配合 Xvfb）
    with SB(uc=True, headless=False, proxy=PROXY_SERVER or None,
            page_load_strategy='eager') as sb:
        success, url = login(sb, EMAIL, PASSWORD)

        if not success:
            msg = "❌ 登录失败，请检查账号密码、代理或网络"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        # 登录成功后打开服务器列表
        print("🌐 打开服务器列表页面...")
        sb.open("https://client.therose.cloud/panel?routeName=servers")
        sb.sleep(3)
        screenshot_step(sb, "server_list")

        expiry = get_expiry(sb)
        print(f"📅 当前有效期: {expiry}")

        # 开始续期
        print("📄 开始续期流程...")
        ok, info = click_extend_button(sb)
        if not ok:
            msg = f"❌ 点击 Extend 按钮失败: {info.get('error')}"
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
                msg = "❌ 未找到 Order now 按钮"
                print(msg)
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
                return
        except Exception as e:
            msg = f"❌ 点击 Order now 失败: {e}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        # 检查续期结果
        print("🔍 检查续期结果...")
        renewal_success, renewal_msg = check_renewal_success(sb)
        screenshot_step(sb, "renewal_result")

        if renewal_success:
            msg = f"✅ 续期成功！{renewal_msg}\n📅 有效期: {expiry}"
            print(msg)
            sb.save_screenshot("renewal_success.png")
        else:
            msg = f"❌ 续期可能失败: {renewal_msg}\n📅 有效期: {expiry}"
            print(msg)
            sb.save_screenshot("renewal_failed.png")

        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)

    print("🏁 脚本执行完毕")

if __name__ == "__main__":
    main()
