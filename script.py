#!/usr/bin/env python3
"""
The Rose Cloud 自动续期脚本
支持通过环境变量 HEADLESS=true 切换到无头模式（GitHub Actions 适用）
"""

import os
import re
import sys
import time
import requests
from seleniumbase import SB

# ==================== 环境变量 ====================
EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"  # 默认有头

BASE_URL = "https://client.therose.cloud/login"

if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)


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


def login(sb, email, password):
    """登录流程"""
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
    try:
        if HEADLESS:
            # 无头模式使用 uc_click_captcha
            sb.uc_click_captcha()
        else:
            sb.uc_gui_click_captcha()
        print("✅ Turnstile 验证已处理")
    except Exception as e:
        print(f"⚠️ 验证码处理异常: {e}")

    print("🔑 点击登录按钮...")
    sb.uc_click('button:contains("Sign in")')
    sb.sleep(3)

    for _ in range(30):
        current_url = sb.get_current_url()
        page_title = sb.get_title() or ""
        print(f"📄 当前 URL: {current_url} | Title: {page_title}")
        if "panel" in current_url:
            print("✅ 登录成功，已跳转到 Dashboard")
            return True, current_url
        time.sleep(1)

    print(f"❌ 登录失败，当前 URL: {sb.get_current_url()}")
    sb.save_screenshot("login_failed.png")
    return False, sb.get_current_url()


def get_expiry(sb):
    """获取服务器有效期"""
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


def click_extend_button(sb):
    """点击续期按钮"""
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


def check_renewal_success(sb):
    """检查续期是否成功"""
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


def main():
    print(f"🚀 启动浏览器 (headless={HEADLESS})")
    with SB(uc=True, headless=HEADLESS) as sb:
        success, url = login(sb, EMAIL, PASSWORD)
        if not success:
            msg = f"❌ 登录失败"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        # 进入服务器列表
        print("🌐 打开服务器列表页面...")
        sb.open("https://client.therose.cloud/panel?routeName=servers")
        sb.sleep(3)

        expiry = get_expiry(sb)
        print(f"📅 当前有效期: {expiry}")

        print("📄 开始续期流程...")
        ok, info = click_extend_button(sb)
        if not ok:
            msg = f"❌ 点击 Extend 按钮失败: {info.get('error')}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        time.sleep(1)

        # 点击 Order now
        try:
            button = sb.find_element('button:contains("Order now")', timeout=5)
            if button:
                print("🛒 点击 Order now 按钮...")
                sb.uc_click('button:contains("Order now")')
                print("✅ 已点击 Order now 按钮")
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
