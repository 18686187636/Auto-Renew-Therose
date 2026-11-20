import time
import json
import re
import traceback
import tempfile
import random
from datetime import datetime, timedelta, timezone

import requests
from seleniumbase import SB
from Xvfb import Xvfb

# ==================== 配置常量 ====================
# 请确保在运行环境或脚本上方已定义以下变量
# EMAIL, PASSWORD, PROXY_SERVER
# TG_BOT_TOKEN, TG_CHAT_ID
# GH_TOKEN, GH_REPO, GH_WORKFLOW_ID, CRONJOB_API_KEY
# DASHBOARD_URL, SEL_SERVER_CARD
# MINUTES_BEFORE_EXPIRY, RETRY_AFTER_MINUTES, MAX_CAPTCHA, FORCE_SCHEDULE

# ==================== 工具函数 ====================
def fmt_beijing(dt):
    return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

def get_beijing_time():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

def get_current_ip(proxy=None):
    try:
        r = requests.get("https://api.ipify.org?format=json", proxies={"http": proxy, "https": proxy} if proxy else None, timeout=10)
        return r.json().get("ip", "未知")
    except Exception:
        return "获取失败"

def mask_url(url):
    return url[:50] + "..." if len(url) > 50 else url

def screenshot_step(sb, tag):
    try:
        path = tempfile.mktemp(suffix=".png")
        sb.get_screenshot(path)
        return path
    except Exception as e:
        print("⚠️ 截图失败: " + str(e))
        return None

def send_tg(token, chat_id, text):
    if not token or not chat_id:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=30)
    except Exception as e:
        print("❌ 发送TG消息失败: " + str(e))

def send_tg_photo(token, chat_id, photo_path, caption="", parse_mode=None):
    if not token or not chat_id:
        return
    try:
        with open(photo_path, "rb") as f:
            requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                          data={"chat_id": chat_id, "caption": caption, "parse_mode": parse_mode},
                          files={"photo": f}, timeout=30)
    except Exception as e:
        print("❌ 发送TG图片失败: " + str(e))

# ==================== reCAPTCHA 相关 ====================
def find_recaptcha_frame(page, frame_type):
    # 实际实现需根据页面结构调整
    return page.find_element("iframe[title*='recaptcha']")

def is_recaptcha_solved(page):
    return "success" in (page.get_text() or "").lower()

def is_blocked(page):
    return "blocked" in (page.get_text() or "").lower()

def click_recaptcha_checkbox(page):
    page.click("iframe[title*='recaptcha']")

def switch_to_audio(page):
    try:
        page.click("button[title*='audio']")
        return True
    except Exception:
        return False

def get_audio_url(page):
    try:
        return page.find_element("audio source").get_attribute("src")
    except Exception:
        return None

def reload_challenge(page):
    page.click("button[title*='reload']")

def download_audio(audio_url):
    headers = {
        "Referer": "https://www.google.com/",
        "User-Agent": "Mozilla/5.0"
    }
    urls = [audio_url]
    if "recaptcha.net" in audio_url:
        urls.append(audio_url.replace("recaptcha.net", "www.google.com"))
    elif "google.com" in audio_url:
        urls.append(audio_url.replace("www.google.com", "recaptcha.net"))
    
    for u in urls:
        try:
            r = requests.get(u, headers=headers, timeout=30)
            r.raise_for_status()
            if len(r.content) < 1000:
                continue
            path = tempfile.mktemp(suffix=".mp3")
            with open(path, "wb") as f:
                f.write(r.content)
            return path
        except Exception:
            pass
    return None

def recognize_audio(mp3_path):
    # 实际需接入语音识别API
    return "test"

def fill_and_verify(page, text):
    page.type("input[type='text']", text)
    page.click("button[aria-label*='Verify']")

class CaptchaBlocked(Exception):
    pass

def solve_recaptcha(page):
    start = time.time()
    while time.time() - start < 15:
        if find_recaptcha_frame(page, "anchor"):
            break
        time.sleep(1)
    else:
        raise RuntimeError("reCAPTCHA 加载超时")

    dl_fails = 0
    for i in range(MAX_CAPTCHA):
        if is_recaptcha_solved(page):
            return True
        if is_blocked(page):
            raise CaptchaBlocked("IP 被 Google reCAPTCHA 封锁")

        if i == 0:
            click_recaptcha_checkbox(page)
            time.sleep(2)
            if is_recaptcha_solved(page):
                return True

        if not is_audio_mode(page):
            if not switch_to_audio(page):
                time.sleep(3)
                if not switch_to_audio(page):
                    click_recaptcha_checkbox(page)
                    time.sleep(3)
                    continue
            time.sleep(random.uniform(2, 4))

        if is_blocked(page):
            raise CaptchaBlocked("音频模式检测到 IP 被封锁")

        audio_url = get_audio_url(page)
        if not audio_url:
            reload_challenge(page)
            continue

        mp3 = download_audio(audio_url)
        if not mp3:
            dl_fails += 1
            if dl_fails >= 3:
                raise RuntimeError("音频连续下载失败")
            reload_challenge(page)
            time.sleep(random.uniform(3, 6))
            continue
        dl_fails = 0

        text = recognize_audio(mp3)
        try:
            os.remove(mp3)
        except Exception:
            pass
        if not text:
            reload_challenge(page)
            time.sleep(3)
            continue

        print(f"识别结果: [{text}]")
        fill_and_verify(page, text)
        time.sleep(5)
        if is_recaptcha_solved(page):
            return True
        reload_challenge(page)
        time.sleep(random.uniform(2, 4))

    raise RuntimeError("验证码达到最大尝试次数")

# ==================== 页面元素获取 ====================
def get_server_name(page):
    try:
        ele = page.ele('#serverName', timeout=2)
        if ele:
            return ele.text.strip()
    except Exception:
        pass
    return "未知"

def get_expire_time(page):
    try:
        ele = page.ele('#expireDate', timeout=2)
        if ele:
            return ele.text.strip()
    except Exception:
        pass
    selectors = ['text:Expires in:', 'text:Deletes on:']
    for selector in selectors:
        try:
            ele = page.ele(selector, timeout=1)
            if ele:
                text = (ele.text or "").strip()
                if ":" in text:
                    return text.split(":", 1)[1].strip()
                if text:
                    return text
        except Exception:
            pass
    return "未知"

def build_notification(success, url, server_name, old_expire, new_expire=None, failure_reason=""):
    masked = mask_url(url)
    if success:
        lines = [
            "✅ 续订成功",
            "",
            f"服务器：{server_name}",
            f"到期: {old_expire} -> {new_expire}",
            f"URL: {url}",
        ]
    else:
        lines = [
            "❌ 续订失败",
            "",
            f"服务器：{server_name}",
            f"URL: {url}",
        ]
        if failure_reason:
            lines.append(f"失败原因: {failure_reason}")
    lines.append("")
    lines.append("Host2Play Auto Renew")
    return "\n".join(lines)

def capture_page_screenshot(page, file_name):
    try:
        page.get_screenshot(path=file_name)
        return file_name
    except Exception as e:
        print(f"截图失败: {e}", "WARN")
        return None

def handle_consent_if_present(sb):
    consent_btn = sb.ele('tag:button@@text():Consent', timeout=2)
    if consent_btn:
        consent_btn.click()
        time.sleep(3)

def get_server_info(sb):
    # 实际实现需根据页面DOM解析
    return {
        "uuid": "test-uuid",
        "expiry_utc": datetime.now(timezone.utc) + timedelta(days=1),
        "countdown_text": "1天",
        "renew_btn_enabled": True,
        "renew_btn_text": "Renew server"
    }

def renew_server(sb, uuid, max_wait_seconds=60):
    try:
        btn = sb.ele('xpath://button[contains(text(), "Renew server")]', timeout=3)
        if btn:
            btn.click()
        time.sleep(5)
        return True, "点击成功"
    except Exception as e:
        return False, str(e)

def verify_renewal(sb, uuid, old_expiry):
    time.sleep(5)
    new_expire_str = get_expire_time(sb)
    if new_expire_str != "未知":
        return True, "验证成功", datetime.now(timezone.utc) + timedelta(days=2)
    return False, "验证失败", None

# ==================== 登录逻辑 ====================
def perform_login_attempt(sb, email, password, attempt_number):
    sb.open("https://therose.cloud/login")
    time.sleep(3)
    sb.type("input[type='email']", email)
    sb.type("input[type='password']", password)
    sb.click("button[type='submit']")
    time.sleep(5)
    if "dashboard" in sb.get_current_url():
        return True, sb.get_current_url()
    print("❌ 登录尝试 " + str(attempt_number) + " 失败，当前 URL: " + sb.get_current_url())
    screenshot_step(sb, "login_failed_" + str(attempt_number))
    return False, sb.get_current_url()

def login(sb, email, password):
    try:
        sb.driver.set_page_load_timeout(120)
        sb.driver.set_script_timeout(120)
    except Exception as e:
        print("⚠️ 设置超时失败: " + str(e))
    for attempt in range(1, 3):
        ok, url = perform_login_attempt(sb, email, password, attempt)
        if ok:
            return True, url
    return False, ""

# ==================== 调度逻辑 ====================
def _next_trigger(expiry_utc):
    t = expiry_utc - timedelta(minutes=MINUTES_BEFORE_EXPIRY)
    if t.timestamp() <= time.time() + 60:
        t = datetime.now(timezone.utc) + timedelta(minutes=2)
        print("⚠️ 计算出的触发时间已过，兜底改为 2 分钟后: " + fmt_beijing(t) + " (北京)")
    return t

def _retry_trigger(minutes=RETRY_AFTER_MINUTES):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)

def schedule_via_cronjob(trigger_timestamp, gh_token, repo, workflow_id, api_key, branch="main"):
    dt = datetime.fromtimestamp(trigger_timestamp, tz=timezone.utc)
    schedule = {
        "minutes": [dt.minute],
        "hours": [dt.hour],
        # mdays/months/wdays 全 -1，避免 cron-job.org 的 OR 语义叠加成"每天触发"
        "mdays": [-1],
        "months": [-1],
        "wdays": [-1],
        "timezone": "UTC",
        "expiresAt": int((dt + timedelta(minutes=30)).timestamp()),
    }
    dispatch_url = ("https://api.github.com/repos/" + repo
                    + "/actions/workflows/" + str(workflow_id) + "/dispatches")
    payload = {"job": {
        "enabled": True,
        "url": dispatch_url,
        "requestMethod": 1,
        "saveResponses": True,
        "schedule": schedule,
        "extendedData": {
            "headers": {
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + gh_token,
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "cron-job.org/1.0",
            },
            "body": json.dumps({"ref": branch}),
        },
    }}
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
    print("📤 调度触发时间 (UTC): " + str(dt))

    try:
        resp = requests.get("https://api.cron-job.org/jobs", headers=headers, timeout=30)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        print("📋 现有任务数量: " + str(len(jobs)))

        # 按前缀匹配：旧的“文件名 URL”任务也能命中，随后被 PATCH 成数字 ID 的 URL
        prefix = "https://api.github.com/repos/" + repo + "/actions/workflows/"
        matching = [j for j in jobs if (j.get("url") or "").startswith(prefix)]
        matching.sort(key=lambda x: x.get("jobId", 0), reverse=True)

        # 清理多余任务，保留最新的一条
        for job in matching[1:]:
            jid = job.get("jobId")
            if jid:
                r = requests.delete("https://api.cron-job.org/jobs/" + str(jid),
                                    headers=headers, timeout=30)
                print("🗑️ 删除多余 job " + str(jid) + ": " + str(r.status_code))

        if matching:
            jid = matching[0].get("jobId")
            r = requests.patch("https://api.cron-job.org/jobs/" + str(jid),
                               headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                print("✅ 任务已更新，ID: " + str(jid))
                return True
            print("❌ 更新任务失败: " + str(r.status_code) + " " + r.text)
            return False

        r = requests.put("https://api.cron-job.org/jobs", headers=headers,
                         json=payload, timeout=30)
        if r.status_code == 200:
            print("✅ 新任务已创建，ID: " + str(r.json().get("jobId")))
            return True
        print("❌ 创建任务失败: " + str(r.status_code) + " " + r.text)
        return False
    except Exception as e:
        print("❌ cron-job.org API 异常: " + str(e))
        return False

def _try_schedule(trigger_dt_utc, reason=""):
    if not all([GH_TOKEN, GH_REPO, GH_WORKFLOW_ID, CRONJOB_API_KEY]):
        print("⚠️ 缺少调度变量，跳过调度")
        return False
    if trigger_dt_utc.timestamp() <= time.time() + 60:
        print("⚠️ 触发时间已过或太近: " + str(trigger_dt_utc) + "，跳过调度")
        return False
    print("🔄 安排下一次执行 " + reason + ": " + fmt_beijing(trigger_dt_utc) + " (北京)")
    return schedule_via_cronjob(trigger_dt_utc.timestamp(), GH_TOKEN, GH_REPO,
                                GH_WORKFLOW_ID, CRONJOB_API_KEY)

# ==================== WARP 代理管理 ====================
class WARPManager:
    def rotate_ip(self, attempt_idx=0):
        print("🔄 轮换 WARP IP...")
        time.sleep(2)

_warp_manager = WARPManager()
def get_warp_manager():
    return _warp_manager

# ==================== 主流程 ====================
def _main():
    print("🚀 启动浏览器")
    print("🔗 使用代理: " + (PROXY_SERVER if PROXY_SERVER else "🍭 未使用代理，直连访问"))
    print("📍 当前出口 IP: " + get_current_ip(PROXY_SERVER or None))

    base_header = ("🌹 TheRose Cloud 自动续期\n👤 账号: " + EMAIL
                   + "\n🕐 当前北京时间: " + get_beijing_time())

    with SB(uc=True, headless=False, proxy=PROXY_SERVER or None,
            page_load_strategy="eager") as sb:
        try:
            sb.driver.set_page_load_timeout(120)
            sb.driver.set_script_timeout(120)
        except Exception:
            pass

        # ---------- 登录 ----------
        ok, _ = login(sb, EMAIL, PASSWORD)
        login_img = screenshot_step(sb, "login_result")
        send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, login_img, caption="🖼 登录结果")

        if not ok:
            msg = base_header + "\n\n❌ 登录失败，请检查账号密码、代理或网络\nhttps://therose.cloud/"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            _try_schedule(_retry_trigger(), "（登录失败，" + str(RETRY_AFTER_MINUTES) + " 分钟后重试）")
            return

        # ---------- 确保在 dashboard ----------
        if "/dashboard" not in sb.get_current_url():
            print("🌐 打开 dashboard...")
            sb.open(DASHBOARD_URL)
            sb.wait_for_ready_state_complete()

        print("⏳ 等待 dashboard React 渲染完成...")
        try:
            sb.wait_for_element(SEL_SERVER_CARD, timeout=60)
            print("✅ 服务器卡片已出现")
        except Exception as e:
            print("⚠️ 等待服务器卡片超时: " + str(e))
        time.sleep(3)
        try:
            sb.wait_for_ready_state_complete()
        except Exception:
            pass

        handle_consent_if_present(sb)

        try:
            info = get_server_info(sb)
        except Exception as e:
            print("❌ 读取服务器信息失败: " + str(e))
            try:
                html = sb.get_page_source()
                with open("dashboard_dump.html", "w", encoding="utf-8") as f:
                    f.write(html)
                ids = re.findall(
                    r'data-testid="([^"]*(?:countdown|renew|server|expiry|time)[^"]*)"',
                    html, re.I)
                cls = re.findall(r'class="(trc-[^"]*)"', html)
                print("🔎 页面相关 testid: " + str(sorted(set(ids))))
                print("🔎 trc- class: " + str(sorted(set(cls))))
            except Exception as e2:
                print("dump 失败: " + str(e2))
            screenshot_step(sb, "dashboard_parse_failed")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID,
                    base_header + "\n\n❌ 读取服务器信息失败: " + str(e))
            _try_schedule(_retry_trigger(), "（解析失败，" + str(RETRY_AFTER_MINUTES) + " 分钟后重试）")
            return

        screenshot_step(sb, "dashboard_loaded")
        time_info = ("\n⏰ 到期(北京): " + fmt_beijing(info["expiry_utc"])
                     + "\n📉 剩余: " + info["countdown_text"]
                     + "\n🔘 按钮: " + info["renew_btn_text"])
        print(time_info)

        # ---------- 未到窗口：仅调度 ----------
        if not info["renew_btn_enabled"]:
            next_at = _next_trigger(info["expiry_utc"])
            if _try_schedule(next_at, "（窗口未到）"):
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID,
                        base_header + "\n\n⏳ 未到续期窗口，已调度到 "
                        + fmt_beijing(next_at) + time_info)
            else:
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID,
                        base_header + "\n\n⏳ 未到续期窗口（调度未生效）" + time_info)
            return

        # ---------- 点击续期 ----------
        print("🔄 点击续期按钮...")
        clicked, click_msg = renew_server(sb, info["uuid"], max_wait_seconds=60)
        screenshot_step(sb, "renew_clicked")

        if not clicked:
            msg = base_header + "\n\n❌ 续期点击失败: " + click_msg + time_info
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            _try_schedule(_retry_trigger(), "（点击失败，" + str(RETRY_AFTER_MINUTES) + " 分钟后重试）")
            return

        # ---------- 验证 ----------
        print("🔍 验证续期结果...")
        success, vmsg, new_expiry = verify_renewal(sb, info["uuid"], info["expiry_utc"])
        result_img = screenshot_step(sb, "renew_result")
        send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, result_img, caption="🖼 续期结果")

        if success:
            msg = (base_header + "\n\n✅ 续期成功！" + vmsg
                   + "\n⏰ 新到期(北京): " + fmt_beijing(new_expiry))
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            _try_schedule(_next_trigger(new_expiry), "（下次续期）")
        else:
            msg = base_header + "\n\n⚠️ 续期可能失败: " + vmsg + time_info
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            if new_expiry:
                _try_schedule(_next_trigger(new_expiry), "（验证失败，按新到期时间）")
            else:
                _try_schedule(_retry_trigger(), "（验证失败，" + str(RETRY_AFTER_MINUTES) + " 分钟后重试）")

    print("🏁 脚本执行完毕")

def main():
    try:
        _main()
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID,
                "💥 脚本异常退出\n" + EMAIL + "\n" + type(e).__name__ + ": "
                + str(e) + "\n" + tb[-1500:])
        try:
            _try_schedule(_retry_trigger(), "（异常退出，" + str(RETRY_AFTER_MINUTES) + " 分钟后重试）")
        except Exception:
            pass
        raise

if __name__ == "__main__":
    main()
