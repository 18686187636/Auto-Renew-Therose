#!/usr/bin/env python3
"""
TheRose Cloud 自动续期脚本
适配 2025 新版站点：
  - 登录页: https://therose.cloud/login?next=%2Fdashboard
    input[data-testid="login-email"] / input[data-testid="login-password"]
    button[data-testid="login-submit"]
  - dashboard: https://therose.cloud/dashboard（React SPA）
  - 到期时间以倒计时显示（如 "4h 41m 32s"）
  - 续期按钮 data-testid="renew-<uuid>"，可续期窗口 = [到期-30min, 到期]
  - 每次续期延长 6 小时
"""

import os
import sys
import time
import re
import traceback
import requests
import json
from datetime import datetime, timedelta, timezone
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

# ========== URL 常量 ==========
BASE_URL = "https://therose.cloud/login?next=%2Fdashboard"
DASHBOARD_URL = "https://therose.cloud/dashboard"

# ========== 新版选择器常量 ==========
SEL_LOGIN_EMAIL = 'input[data-testid="login-email"]'
SEL_LOGIN_PASSWORD = 'input[data-testid="login-password"]'
SEL_LOGIN_SUBMIT = 'button[data-testid="login-submit"]'
SEL_SERVER_CARD = 'div.trc-server[data-testid^="server-"]'

# 站点可续期窗口 = 到期前 30 分钟开放；提前 28 分钟唤醒，稳进窗口且留 2 分钟缓冲
MINUTES_BEFORE_EXPIRY = 28

BEIJING_TZ = timezone(timedelta(hours=8))

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


def wait_el(sb, selector, timeout=20):
    """
    等待元素出现并返回原生 WebElement。
    仅用于：读属性 / is_enabled() / 点击。
    文本输入请一律使用 sb.type(selector, text)，不要用本函数的返回值。
    """
    sb.wait_for_element(selector, timeout=timeout)
    return sb.find_element(selector)


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


def send_tg_photo(bot_token, chat_id, photo_path, caption=""):
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            files = {'photo': f}
            data = {'chat_id': chat_id, 'caption': caption}
            resp = requests.post(url, files=files, data=data, timeout=30)
        if resp.status_code == 200:
            print(f"📸 图片已发送: {photo_path}")
        else:
            print(f"❌ 发送图片失败: {resp.text}")
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
        return f"获取失败 (HTTP {response.status_code})"
    except Exception as e:
        return f"获取失败: {e}"


def get_beijing_time():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def fmt_beijing(dt_utc):
    return dt_utc.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ========== 倒计时解析 ==========
def parse_countdown(text: str):
    """
    解析 '4h 41m 32s' / '4h 11m' / '1d 4h' / '30m' / '15s' 为 timedelta。
    无法解析返回 None。
    """
    text = (text or "").strip().replace("\xa0", " ")
    # 剥掉可能混入的前缀标签文本
    text = re.sub(r"^(Renews?\s+in|Renewable\s+in)\s+", "", text, flags=re.I)
    text = text.strip()
    if not text:
        return None
    m = re.fullmatch(
        r"(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?",
        text
    )
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi, seconds=s)


# ========== 读取服务器卡片信息（JS 快照，免疫 React 重渲染） ==========
JS_SNAPSHOT = r"""
const card = document.querySelector('div.trc-server[data-testid^="server-"]');
if (!card) return null;
const testid = card.getAttribute('data-testid') || '';
const uuid = testid.replace('server-', '');
const cd = card.querySelector('[data-testid="countdown-' + uuid + '"]');
let timeEl = cd ? cd.querySelector('[class*="countdown-time"]') : null;
let cdText = timeEl ? (timeEl.textContent || '').trim() : (cd ? (cd.textContent || '').trim() : '');
const btn = card.querySelector('[data-testid="renew-' + uuid + '"]');
return {
  uuid: uuid,
  countdown: cdText,
  btnText: btn ? (btn.textContent || '').trim() : '',
  btnDisabled: btn ? !!btn.disabled : null,
  btnExists: !!btn,
  cardText: (card.textContent || '').trim()
};
"""


def snapshot_server(sb):
    """在浏览器主线程同步读取整张卡片，避免分步 find_element 撞上 DOM 重建。"""
    sb.wait_for_element(SEL_SERVER_CARD, timeout=30)
    return sb.driver.execute_script(JS_SNAPSHOT)


def get_server_info(sb):
    snap = snapshot_server(sb)
    if not snap:
        raise RuntimeError("JS 快照取不到服务器卡片 div.trc-server")

    uuid = snap["uuid"]
    print(f"🔍 服务器 UUID: {uuid}")

    countdown_text = (snap["countdown"] or "").replace("\xa0", " ").strip()

    # 兜底 1：整卡文本里正则捞倒计时
    if not re.fullmatch(r"(?:\d+\s*[dhms]\s*)+", countdown_text):
        m = re.search(r"(\d+\s*d)?\s*(\d+\s*h)?\s*(\d+\s*m)?\s*(\d+\s*s)?",
                      snap.get("cardText") or "")
        if m and any(m.groups()):
            countdown_text = " ".join(g for g in m.groups() if g)
            print(f"⏳ 从卡片文本兜底命中: {countdown_text!r}")

    if not countdown_text:
        raise RuntimeError(f"倒计时文本为空，卡片文本: {snap.get('cardText')!r}")

    delta = parse_countdown(countdown_text)
    if delta is None:
        raise RuntimeError(f"无法解析倒计时文本: {countdown_text!r}")

    expiry_utc = datetime.now(timezone.utc) + delta

    btn_selector = f'button[data-testid="renew-{uuid}"]'
    return {
        "uuid": uuid,
        "countdown_text": countdown_text,
        "expiry_utc": expiry_utc,
        "renew_btn_selector": btn_selector,
        "renew_btn_enabled": bool(snap["btnExists"]) and not snap["btnDisabled"],
        "renew_btn_text": snap["btnText"],
    }


# ========== 点击续期按钮 ==========
def renew_server(sb, uuid, max_wait_seconds=60):
    """
    在续期窗口内点击续期按钮。
    - 按钮可用：立即点击
    - 按钮 disabled 但剩余等待 <= max_wait_seconds：等待后重试
    - 否则返回 False（由调用方决定是否调度）
    """
    sel = f'button[data-testid="renew-{uuid}"]'
    try:
        btn = wait_el(sb, sel, timeout=15)
    except Exception as e:
        return False, f"找不到续期按钮: {e}"

    if not btn.is_enabled():
        text = (btn.text or "").strip()
        m = re.search(r"Renewable in\s+([\dhms ]+?)\s*·", text)
        if not m:
            return False, f"按钮不可点击，且无法解析等待时间: {text!r}"
        wait = parse_countdown(m.group(1))
        if wait is None:
            return False, f"无法解析等待时长: {m.group(1)!r}"
        if wait.total_seconds() > max_wait_seconds:
            return False, f"未到可续期窗口（还需 {m.group(1).strip()}）"
        print(f"⏳ 等待 {wait} 后重试点击...")
        time.sleep(wait.total_seconds() + 3)
        try:
            btn = wait_el(sb, sel, timeout=15)
        except Exception as e:
            return False, f"等待后仍找不到续期按钮: {e}"

    try:
        sb.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.5)
        sb.driver.execute_script("arguments[0].click();", btn)
        return True, "点击成功"
    except Exception as e:
        return False, f"点击异常: {e}"


# ========== 验证续期结果（比较到期时间） ==========
def verify_renewal(sb, uuid, old_expiry_utc):
    """
    点击后刷新，用 JS 快照读取新倒计时并与旧到期比较。
    延长超过 30 分钟视为成功（每次应延长约 6 小时）。
    """
    time.sleep(5)
    try:
        sb.refresh()
        sb.wait_for_ready_state_complete()
        snap = snapshot_server(sb)
        if not snap:
            return False, "刷新后取不到服务器卡片", None
        new_delta = parse_countdown(snap["countdown"])
        if new_delta is None:
            return False, f"刷新后倒计时解析失败: {snap['countdown']!r}", None
        new_expiry = datetime.now(timezone.utc) + new_delta
        gain_sec = (new_expiry - old_expiry_utc).total_seconds()
        if gain_sec > 1800:
            return True, f"延长约 {gain_sec/3600:.1f} 小时", new_expiry
        return False, f"到期时间未显著延长（{gain_sec/60:.0f} 分钟）", new_expiry
    except Exception as e:
        return False, f"验证失败: {e}", None


# ========== Consent 弹窗处理 ==========
def handle_consent_if_present(sb):
    selectors = [
        'button:contains("Consent")',
        'button:contains("Accept")',
        'button:contains("I agree")',
        'button:contains("同意")',
        'button:contains("Accept all")',
        'button:contains("Allow")',
        '#consent-button',
        '.consent-btn',
        '[data-consent="accept"]',
    ]
    for selector in selectors:
        try:
            btn = sb.find_element(selector, timeout=2)
            if btn and btn.is_displayed():
                sb.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.5)
                sb.driver.execute_script("arguments[0].click();", btn)
                print(f"✅ 已点击 Consent 按钮: {selector}")
                time.sleep(1)
                return True
        except Exception:
            continue
    print("ℹ️ 未检测到 Consent 按钮")
    return False


# ========== 登录（新版：data-testid 选择器） ==========
def perform_login_attempt(sb, email, password, attempt_number):
    print(f"\n🔄 登录尝试 {attempt_number}/2")
    print("🌐 打开登录页面...")
    sb.open(BASE_URL)
    sb.wait_for_ready_state_complete()
    sb.sleep(2)
    screenshot_step(sb, f"attempt_{attempt_number}_page_loaded")

    # ---- 邮箱（sb.type 自带等待 + 清空 + 输入） ----
    print("📧 等待邮箱输入框...")
    sb.wait_for_element(SEL_LOGIN_EMAIL, timeout=30)
    sb.type(SEL_LOGIN_EMAIL, email, timeout=15)
    print("✅ 邮箱已填写")
    screenshot_step(sb, f"attempt_{attempt_number}_email_filled")

    # ---- 密码 ----
    print("🔑 等待密码输入框...")
    sb.wait_for_element(SEL_LOGIN_PASSWORD, timeout=15)
    sb.type(SEL_LOGIN_PASSWORD, password, timeout=15)
    print("✅ 密码已填写")
    screenshot_step(sb, f"attempt_{attempt_number}_password_filled")

    # ---- 等 Turnstile ----
    print("⏳ 等待 Turnstile iframe 出现...")
    try:
        sb.wait_for_element('iframe[src*="challenges.cloudflare.com"]', timeout=60)
        print("✅ Turnstile iframe 已出现")
    except Exception:
        print("⚠️ 未检测到 Turnstile iframe，可能无需验证")
    time.sleep(10)
    screenshot_step(sb, f"attempt_{attempt_number}_before_captcha")

    # ---- 处理验证码 ----
    print("🛡 处理 Turnstile...")
    try:
        sb.uc_gui_click_captcha()
        print("✅ Turnstile 已处理")
    except Exception as e:
        print(f"⚠️ uc_gui_click_captcha 异常: {e}")
    screenshot_step(sb, f"attempt_{attempt_number}_captcha_handled")

    time.sleep(6)
    screenshot_step(sb, f"attempt_{attempt_number}_after_6s_wait")

    # ---- 提交登录 ----
    print("🔑 点击登录按钮...")
    try:
        sb.wait_for_element(SEL_LOGIN_SUBMIT, timeout=15)
        sb.uc_click(SEL_LOGIN_SUBMIT)
    except Exception as e:
        print(f"⚠️ uc_click 失败，改用 JS 点击: {e}")
        btn = wait_el(sb, SEL_LOGIN_SUBMIT, timeout=10)
        sb.driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.5)
        sb.driver.execute_script("arguments[0].click();", btn)
    screenshot_step(sb, f"attempt_{attempt_number}_login_clicked")
    sb.sleep(5)

    # ---- 轮询等跳转 ----
    for _ in range(30):
        current_url = sb.get_current_url()
        page_title = sb.get_title() or ""
        print(f"📄 当前 URL: {current_url} | Title: {page_title}")

        if "chrome-error" in current_url:
            print("⚠️ chrome-error，刷新重试...")
            sb.refresh()
            sb.sleep(3)
            continue

        if "/dashboard" in current_url:
            print("✅ 登录成功，已跳转到 dashboard")
            screenshot_step(sb, f"attempt_{attempt_number}_login_success")
            return True, current_url

        time.sleep(1)

    print(f"❌ 登录尝试 {attempt_number} 失败，当前 URL: {sb.get_current_url()}")
    screenshot_step(sb, f"attempt_{attempt_number}_login_failed")
    return False, sb.get_current_url()


def login(sb, email, password):
    try:
        sb.driver.set_page_load_timeout(120)
        sb.driver.set_script_timeout(120)
    except Exception as e:
        print(f"⚠️ 设置超时失败: {e}")

    for attempt in range(1, 3):
        ok, url = perform_login_attempt(sb, email, password, attempt)
        if ok:
            return True, url
    return False, sb.get_current_url()


# ========== 调度 ==========
def _next_trigger(expiry_utc):
    """计算下次触发时间；若已落入过去，则改为 2 分钟后重试，防止调度链断裂。"""
    t = expiry_utc - timedelta(minutes=MINUTES_BEFORE_EXPIRY)
    if t.timestamp() <= time.time() + 60:
        t = datetime.now(timezone.utc) + timedelta(minutes=2)
        print(f"⚠️ 计算出的触发时间已过，兜底改为 2 分钟后: {fmt_beijing(t)} (北京)")
    return t


def schedule_via_cronjob(trigger_timestamp, gh_token, repo, workflow_id, api_key, branch="main"):
    dt = datetime.fromtimestamp(trigger_timestamp, tz=timezone.utc)
    schedule = {
        "minutes": [dt.minute],
        "hours": [dt.hour],
        # mdays / months / wdays 统一填 -1（不限），避免 cron-job.org 的 OR 语义
        # 把 mdays 与 wdays 叠加成"每天都触发"
        "mdays": [-1],
        "months": [-1],
        "wdays": [-1],
        "timezone": "UTC",
        # 放宽到 30 分钟，避免触发失败后无窗口排查
        "expiresAt": int((dt + timedelta(minutes=30)).timestamp()),
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
                    "User-Agent": "cron-job.org/1.0",
                },
                "body": json.dumps({"ref": branch}),
            },
        }
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print(f"📤 调度触发时间 (UTC): {dt}")

    try:
        resp = requests.get("https://api.cron-job.org/jobs", headers=headers, timeout=30)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        print(f"📋 现有任务数量: {len(jobs)}")

        matching = [j for j in jobs if j.get("url") == dispatch_url]

        for job in matching[1:]:
            jid = job.get("jobId")
            if jid:
                r = requests.delete(f"https://api.cron-job.org/jobs/{jid}", headers=headers, timeout=30)
                print(f"🗑️ 删除多余 job {jid}: {r.status_code}")

        if matching:
            jid = matching[0].get("jobId")
            r = requests.patch(f"https://api.cron-job.org/jobs/{jid}",
                               headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                print(f"✅ 任务已更新，ID: {jid}")
                return True
            print(f"❌ 更新任务失败: {r.status_code} {r.text}")
            return False

        r = requests.put("https://api.cron-job.org/jobs", headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            print(f"✅ 新任务已创建，ID: {r.json().get('jobId')}")
            return True
        print(f"❌ 创建任务失败: {r.status_code} {r.text}")
        return False
    except Exception as e:
        print(f"❌ cron-job.org API 异常: {e}")
        return False


def _try_schedule(trigger_dt_utc, reason=""):
    """统一封装调度，非必要失败只打印"""
    if not all([GH_TOKEN, GH_REPO, GH_WORKFLOW_ID, CRONJOB_API_KEY]):
        print("⚠️ 缺少调度变量，跳过调度")
        return False
    if trigger_dt_utc.timestamp() <= time.time() + 60:
        print(f"⚠️ 触发时间已过或太近: {trigger_dt_utc}，跳过调度")
        return False
    print(f"🔄 安排下一次执行 {reason}: {fmt_beijing(trigger_dt_utc)} (北京)")
    return schedule_via_cronjob(
        trigger_dt_utc.timestamp(), GH_TOKEN, GH_REPO, GH_WORKFLOW_ID, CRONJOB_API_KEY
    )


# ========== 主流程 ==========
def _main():
    print("🚀 启动浏览器")
    if PROXY_SERVER:
        print(f"🔗 使用代理: {PROXY_SERVER}")
    else:
        print("🍭 未使用代理，直连访问")

    ip = get_current_ip(PROXY_SERVER or None)
    print(f"📍 当前出口 IP: {ip}")

    base_header = (
        f"🌹 TheRose Cloud 自动续期\n"
        f"👤 账号: {EMAIL}\n"
        f"🕐 当前北京时间: {get_beijing_time()}"
    )

    with SB(uc=True, headless=False, proxy=PROXY_SERVER or None,
            page_load_strategy='eager') as sb:
        try:
            sb.driver.set_page_load_timeout(120)
            sb.driver.set_script_timeout(120)
        except Exception:
            pass

        # ---------- 登录 ----------
        ok, _ = login(sb, EMAIL, PASSWORD)
        login_img = screenshot_step(sb, "login_result")
        if login_img:
            send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, login_img, caption="🖼 登录结果")

        if not ok:
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID,
                    f"{base_header}\n\n❌ 登录失败，请检查账号密码、代理或网络\nhttps://therose.cloud/")
            return

        # ---------- 确保在 dashboard ----------
        if "/dashboard" not in sb.get_current_url():
            print("🌐 打开 dashboard...")
            sb.open(DASHBOARD_URL)
        handle_consent_if_present(sb)

        try:
            info = get_server_info(sb)
        except Exception as e:
            print(f"❌ 读取服务器信息失败: {e}")
            # DOM 快照，便于定位真实 data-testid
            try:
                html = sb.get_page_source()
                with open("dashboard_dump.html", "w", encoding="utf-8") as f:
                    f.write(html)
                ids = re.findall(
                    r'data-testid="([^"]*(?:countdown|renew|server|expiry|time)[^"]*)"',
                    html, re.I)
                print(f"🔎 页面相关 testid: {sorted(set(ids))}")
                print(f"🔎 trc- class: {sorted(set(re.findall(r'class=\"(trc-[^\"]*)\"', html)))}")
            except Exception as e2:
                print(f"dump 失败: {e2}")
            screenshot_step(sb, "dashboard_parse_failed")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID,
                    f"{base_header}\n\n❌ 读取服务器信息失败: {e}")
            return

        screenshot_step(sb, "dashboard_loaded")
        time_info = (
            f"\n⏰ 到期(北京): {fmt_beijing(info['expiry_utc'])}"
            f"\n📉 剩余: {info['countdown_text']}"
            f"\n🔘 按钮: {info['renew_btn_text']}"
        )
        print(time_info)

        # ---------- 未到窗口：仅调度 ----------
        if not info["renew_btn_enabled"]:
            next_at = _next_trigger(info["expiry_utc"])
            if _try_schedule(next_at, "（窗口未到）"):
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID,
                        f"{base_header}\n\n⏳ 未到续期窗口，已调度到 "
                        f"{fmt_beijing(next_at)}{time_info}")
            else:
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID,
                        f"{base_header}\n\n⏳ 未到续期窗口（调度未生效）{time_info}")
            return

        # ---------- 点击续期 ----------
        print("🔄 点击续期按钮...")
        clicked, click_msg = renew_server(sb, info["uuid"], max_wait_seconds=60)
        screenshot_step(sb, "renew_clicked")

        if not clicked:
            msg = f"{base_header}\n\n❌ 续期点击失败: {click_msg}{time_info}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            if FORCE_SCHEDULE:
                next_at = _next_trigger(info["expiry_utc"])
                _try_schedule(next_at, "（强制兜底）")
            return

        # ---------- 验证 ----------
        print("🔍 验证续期结果...")
        success, vmsg, new_expiry = verify_renewal(sb, info["uuid"], info["expiry_utc"])
        result_img = screenshot_step(sb, "renew_result")
        if result_img:
            send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, result_img, caption="🖼 续期结果")

        if success:
            msg = (
                f"{base_header}\n\n✅ 续期成功！{vmsg}"
                f"\n⏰ 新到期(北京): {fmt_beijing(new_expiry)}"
            )
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            next_at = _next_trigger(new_expiry)
            _try_schedule(next_at, "（下次续期）")
        else:
            msg = f"{base_header}\n\n⚠️ 续期可能失败: {vmsg}{time_info}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            if FORCE_SCHEDULE:
                next_at = _next_trigger(info["expiry_utc"])
                _try_schedule(next_at, "（验证失败但强制调度）")

    print("🏁 脚本执行完毕")


def main():
    try:
        _main()
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        try:
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID,
                    f"💥 脚本异常退出\n{EMAIL}\n{type(e).__name__}: {e}\n{tb[-1500:]}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
