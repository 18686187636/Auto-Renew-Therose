#!/usr/bin/env python3
"""TheRose Cloud 自动续期脚本（兼容 Python 3.10，f-string 内无反斜杠）"""
import os, sys, time, re, json, traceback, requests
from datetime import datetime, timedelta, timezone
from seleniumbase import SB

EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY_SERVER = os.environ.get("PROXY_SERVER") or ""
CRONJOB_API_KEY = os.environ.get("CRONJOB_API_KEY") or ""
GH_TOKEN = os.environ.get("GH_TOKEN") or ""
GH_REPO = os.environ.get("GH_REPO") or ""
GH_WORKFLOW_ID = os.environ.get("GH_WORKFLOW_ID") or ""

# 已废弃，失败分支现在无条件调度；保留仅为兼容旧 workflow
FORCE_SCHEDULE = os.environ.get("FORCE_SCHEDULE", "false").lower() == "true"

BASE_URL = "https://therose.cloud/login?next=%2Fdashboard"
DASHBOARD_URL = "https://therose.cloud/dashboard"

SEL_LOGIN_EMAIL = 'input[data-testid="login-email"]'
SEL_LOGIN_PASSWORD = 'input[data-testid="login-password"]'
SEL_LOGIN_SUBMIT = 'button[data-testid="login-submit"]'
SEL_SERVER_CARD = 'div.trc-server[data-testid^="server-"]'

# 站点窗口 = 到期前 30 分钟；提前 28 分钟唤醒留缓冲
MINUTES_BEFORE_EXPIRY = 28
RETRY_AFTER_MINUTES = 5
BEIJING_TZ = timezone(timedelta(hours=8))

if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)


def screenshot_step(sb, step_name):
    filename = "step_" + step_name + "_" + str(int(time.time() * 1000)) + ".png"
    try:
        sb.save_screenshot(filename)
        print("📸 截图已保存: " + filename)
        return filename
    except Exception as e:
        print("⚠️ 截图失败: " + str(e))
        return None


def wait_el(sb, selector, timeout=20):
    """返回原生 WebElement，仅用于读属性 / is_enabled / 点击。文本输入请用 sb.type。"""
    sb.wait_for_element(selector, timeout=timeout)
    return sb.find_element(selector)


def safe_execute_script(sb, script, *args, retries=3, delay=2.0):
    """execute_script 带重试 + 探活，规避 chromedriver 瞬时 connection refused。"""
    last_err = None
    for i in range(retries):
        try:
            return sb.driver.execute_script(script, *args)
        except Exception as e:
            last_err = e
            print("⚠️ execute_script 第 " + str(i + 1) + "/" + str(retries) + " 次失败: " + str(e))
            if i < retries - 1:
                time.sleep(delay)
                try:
                    _ = sb.driver.current_url
                    print("ℹ️ driver 探活正常，继续重试")
                except Exception as e2:
                    print("⚠️ driver 探活失败: " + str(e2))
    raise last_err


def send_tg(token, chat_id, message):
    if not token or not chat_id:
        return
    try:
        resp = requests.post(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            json={"chat_id": chat_id, "text": message}, timeout=10)
        print("📨 Telegram 通知已发送" if resp.status_code == 200
              else "❌ Telegram 发送失败: " + resp.text)
    except Exception as e:
        print("❌ Telegram 发送异常: " + str(e))


def send_tg_photo(bot_token, chat_id, photo_path, caption=""):
    if not bot_token or not chat_id or not photo_path:
        return
    try:
        with open(photo_path, "rb") as f:
            resp = requests.post(
                "https://api.telegram.org/bot" + bot_token + "/sendPhoto",
                files={"photo": f},
                data={"chat_id": chat_id, "caption": caption}, timeout=30)
        print("📸 图片已发送: " + photo_path if resp.status_code == 200
              else "❌ 发送图片失败: " + resp.text)
    except Exception as e:
        print("❌ 发送图片异常: " + str(e))


def get_current_ip(proxy_server=None):
    proxies = {"http": proxy_server, "https": proxy_server} if proxy_server else None
    try:
        r = requests.get("https://api.ip.sb/ip", proxies=proxies, timeout=15)
        return r.text.strip() if r.status_code == 200 else "获取失败 (HTTP " + str(r.status_code) + ")"
    except Exception as e:
        return "获取失败: " + str(e)


def get_beijing_time():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def fmt_beijing(dt_utc):
    return dt_utc.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def parse_countdown(text):
    """解析 '4h 41m 32s' / '4h 11m' / '1d 4h' / '30m' / '15s'，失败返回 None。"""
    text = (text or "").strip().replace("\xa0", " ")
    text = re.sub(r"^(Renews?\s+in|Renewable\s+in)\s+", "", text, flags=re.I).strip()
    if not text:
        return None
    m = re.fullmatch(
        r"(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?", text)
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi, seconds=s)


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

# 单位后不能紧跟字母数字，排除 "1 server" 里的 "1 s"
COUNTDOWN_FRAGMENT = r"((?:\d+\s*[dhms](?![a-zA-Z0-9])\s*){1,4})"


def snapshot_server_from_html(html):
    """execute_script 彻底失败时的兜底：从页面源码正则解析。"""
    m = re.search(r'data-testid="server-([0-9a-fA-F\-]{36})"', html)
    if not m:
        return None
    uuid = m.group(1)

    cd = None
    pat_cd = (r'data-testid="countdown-' + re.escape(uuid)
              + r'"[^>]*>.*?class="trc-countdown-time[^"]*"[^>]*>([^<]+)<')
    mc = re.search(pat_cd, html, re.S)
    if mc:
        cd = mc.group(1).strip()
    else:
        idx = html.find('data-testid="countdown-' + uuid + '"')
        if idx != -1:
            ms = re.search(COUNTDOWN_FRAGMENT, html[idx:idx + 800])
            if ms:
                cd = ms.group(1).strip()
                print("ℹ️ 倒计时走 testid 邻近兜底提取")

    btn_text, btn_disabled, btn_exists = "", None, False
    pat_btn_tag = r'<button[^>]*data-testid="renew-' + re.escape(uuid) + r'"[^>]*>'
    mt = re.search(pat_btn_tag, html, re.S)
    if mt:
        btn_exists = True
        btn_disabled = bool(re.search(r'\bdisabled\b', mt.group(0)))
        mf = re.search(pat_btn_tag + r'(.*?)</button>', html, re.S)
        if mf:
            btn_text = re.sub(r'<[^>]+>', '', mf.group(1)).strip()

    if not cd:
        return None
    return {"uuid": uuid, "countdown": cd, "btnText": btn_text,
            "btnDisabled": btn_disabled, "btnExists": btn_exists, "cardText": ""}


def snapshot_server(sb):
    """优先 JS 快照；失败则用页面源码正则兜底。"""
    sb.wait_for_element(SEL_SERVER_CARD, timeout=30)
    try:
        sb.wait_for_ready_state_complete()
    except Exception:
        pass
    time.sleep(2)

    try:
        snap = safe_execute_script(sb, JS_SNAPSHOT)
        if snap:
            return snap
        print("⚠️ JS 快照返回空，转 HTML 兜底")
    except Exception as e:
        print("⚠️ JS 快照彻底失败: " + str(e) + "，转 HTML 兜底")

    snap = snapshot_server_from_html(sb.get_page_source())
    if snap:
        print("✅ HTML 兜底解析成功")
    return snap


def get_server_info(sb):
    snap = snapshot_server(sb)
    if not snap:
        raise RuntimeError("JS 快照与 HTML 兜底均无法解析服务器卡片")

    uuid = snap["uuid"]
    print("🔍 服务器 UUID: " + uuid)
    countdown_text = (snap["countdown"] or "").replace("\xa0", " ").strip()

    if not re.fullmatch(r"(?:\d+\s*[dhms]\s*)+", countdown_text):
        m = re.search(COUNTDOWN_FRAGMENT, snap.get("cardText") or "")
        if m:
            countdown_text = m.group(1).strip()
            print("⏳ 从卡片文本兜底命中: " + repr(countdown_text))

    if not countdown_text:
        raise RuntimeError("倒计时文本为空，卡片文本: " + repr(snap.get("cardText")))

    delta = parse_countdown(countdown_text)
    if delta is None:
        raise RuntimeError("无法解析倒计时文本: " + repr(countdown_text))

    return {
        "uuid": uuid,
        "countdown_text": countdown_text,
        "expiry_utc": datetime.now(timezone.utc) + delta,
        "renew_btn_selector": 'button[data-testid="renew-' + uuid + '"]',
        "renew_btn_enabled": bool(snap["btnExists"]) and not snap["btnDisabled"],
        "renew_btn_text": snap["btnText"],
    }


def renew_server(sb, uuid, max_wait_seconds=60):
    sel = 'button[data-testid="renew-' + uuid + '"]'
    try:
        btn = wait_el(sb, sel, timeout=15)
    except Exception as e:
        return False, "找不到续期按钮: " + str(e)

    if not btn.is_enabled():
        text = (btn.text or "").strip()
        m = re.search(r"Renewable in\s+([\dhms ]+?)\s*·", text)
        if not m:
            m = re.search(r"Renewable in\s+([\dhms ]+)", text)
        if not m:
            return False, "按钮不可点击，且无法解析等待时间: " + repr(text)
        wait = parse_countdown(m.group(1))
        if wait is None:
            return False, "无法解析等待时长: " + repr(m.group(1))
        if wait.total_seconds() > max_wait_seconds:
            return False, "未到可续期窗口（还需 " + m.group(1).strip() + "）"
        print("⏳ 等待 " + str(wait) + " 后重试点击...")
        time.sleep(wait.total_seconds() + 3)
        try:
            btn = wait_el(sb, sel, timeout=15)
        except Exception as e:
            return False, "等待后仍找不到续期按钮: " + str(e)

    try:
        safe_execute_script(sb, "arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.5)
        safe_execute_script(sb, "arguments[0].click();", btn)
        return True, "点击成功"
    except Exception as e:
        return False, "点击异常: " + str(e)


def verify_renewal(sb, uuid, old_expiry_utc):
    time.sleep(5)
    try:
        sb.refresh()
        sb.wait_for_ready_state_complete()
        time.sleep(3)
        snap = snapshot_server(sb)
        if not snap:
            return False, "刷新后取不到服务器卡片", None
        new_delta = parse_countdown(snap["countdown"])
        if new_delta is None:
            return False, "刷新后倒计时解析失败: " + repr(snap["countdown"]), None
        new_expiry = datetime.now(timezone.utc) + new_delta
        gain_sec = (new_expiry - old_expiry_utc).total_seconds()
        if gain_sec > 1800:
            return True, "延长约 " + ("%.1f" % (gain_sec / 3600)) + " 小时", new_expiry
        return False, "到期时间未显著延长（" + str(int(gain_sec / 60)) + " 分钟）", new_expiry
    except Exception as e:
        return False, "验证失败: " + str(e), None


def handle_consent_if_present(sb):
    try:
        src = sb.get_page_source() or ""
        if not re.search(r"(consent|cookie|agree|accept)", src, re.I):
            print("ℹ️ 页面无 consent 相关字样，跳过检测")
            return False
    except Exception:
        pass

    selectors = [
        'button:contains("Consent")', 'button:contains("Accept")',
        'button:contains("I agree")', 'button:contains("同意")',
        'button:contains("Accept all")', 'button:contains("Allow")',
        "#consent-button", ".consent-btn", '[data-consent="accept"]',
    ]
    for selector in selectors:
        try:
            btn = sb.find_element(selector, timeout=1)
            if btn and btn.is_displayed():
                safe_execute_script(sb, "arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.5)
                safe_execute_script(sb, "arguments[0].click();", btn)
                print("✅ 已点击 Consent 按钮: " + selector)
                time.sleep(1)
                return True
        except Exception:
            continue
    print("ℹ️ 未检测到 Consent 按钮")
    return False


def perform_login_attempt(sb, email, password, attempt_number):
    tag = "attempt_" + str(attempt_number)
    print("\n🔄 登录尝试 " + str(attempt_number) + "/2")
    print("🌐 打开登录页面...")
    sb.open(BASE_URL)
    sb.wait_for_ready_state_complete()
    sb.sleep(2)
    screenshot_step(sb, tag + "_page_loaded")

    print("📧 等待邮箱输入框...")
    sb.wait_for_element(SEL_LOGIN_EMAIL, timeout=30)
    sb.type(SEL_LOGIN_EMAIL, email, timeout=15)
    print("✅ 邮箱已填写")
    screenshot_step(sb, tag + "_email_filled")

    print("🔑 等待密码输入框...")
    sb.wait_for_element(SEL_LOGIN_PASSWORD, timeout=15)
    sb.type(SEL_LOGIN_PASSWORD, password, timeout=15)
    print("✅ 密码已填写")
    screenshot_step(sb, tag + "_password_filled")

    print("⏳ 等待 Turnstile iframe 出现...")
    try:
        sb.wait_for_element('iframe[src*="challenges.cloudflare.com"]', timeout=60)
        print("✅ Turnstile iframe 已出现")
    except Exception:
        print("⚠️ 未检测到 Turnstile iframe，可能无需验证")
    time.sleep(10)
    screenshot_step(sb, tag + "_before_captcha")

    print("🛡 处理 Turnstile...")
    try:
        sb.uc_gui_click_captcha()
        print("✅ Turnstile 已处理")
    except Exception as e:
        print("⚠️ uc_gui_click_captcha 异常: " + str(e))
    screenshot_step(sb, tag + "_captcha_handled")

    time.sleep(6)
    screenshot_step(sb, tag + "_after_6s_wait")

    print("🔑 点击登录按钮...")
    try:
        sb.wait_for_element(SEL_LOGIN_SUBMIT, timeout=15)
        sb.uc_click(SEL_LOGIN_SUBMIT)
    except Exception as e:
        print("⚠️ uc_click 失败，改用 JS 点击: " + str(e))
        try:
            btn = wait_el(sb, SEL_LOGIN_SUBMIT, timeout=10)
            safe_execute_script(sb, "arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.5)
            safe_execute_script(sb, "arguments[0].click();", btn)
        except Exception as e2:
            print("⚠️ JS 点击也失败: " + str(e2))
    screenshot_step(sb, tag + "_login_clicked")
    sb.sleep(5)

    for _ in range(30):
        current_url = sb.get_current_url()
        print("📄 当前 URL: " + current_url + " | Title: " + (sb.get_title() or ""))
        if "chrome-error" in current_url:
            print("⚠️ chrome-error，刷新重试...")
            sb.refresh()
            sb.sleep(3)
            continue
        if "/dashboard" in current_url:
            print("✅ 登录成功，已跳转到 dashboard")
            screenshot_step(sb, tag + "_login_success")
            return True, current_url
        time.sleep(1)

    print("❌ 登录尝试 " + str(attempt_number) + " 失败，当前 URL: " + sb.get_current_url())
    screenshot_step(sb, tag + "_login_failed")
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
    return False, sb.get_current_url()


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

    # 关键修复：cron-job.org 里 -1 表示“任意/每天”，不是“不限制”。
    # mdays/months 填 -1 会退化成 "28 21 * * *"，即每天同一时刻触发。
    # 必须给具体 day / month，才能真正只在那一天触发。
    # wdays 必须保持 -1：它与 mdays 是 OR 关系，填具体星期几会变成“每周也触发”。
    schedule = {
        "minutes": [dt.minute],
        "hours": [dt.hour],
        "mdays": [dt.day],
        "months": [dt.month],
        "wdays": [-1],
        "timezone": "UTC",
        "expiresAt": int((dt + timedelta(minutes=30)).timestamp()),
    }

    dispatch_url = ("https://api.github.com/repos/" + repo
                    + "/actions/workflows/" + workflow_id + "/dispatches")
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
    print("🧮 cron 表达式(UTC): "
          + str(dt.minute) + " " + str(dt.hour) + " "
          + str(dt.day) + " " + str(dt.month) + " *")

    try:
        resp = requests.get("https://api.cron-job.org/jobs", headers=headers, timeout=30)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        print("📋 现有任务数量: " + str(len(jobs)))

        # 按 URL 前缀宽松匹配，避免 workflow 文件名大小写 / 数字 ID 差异导致重复创建
        prefix = "https://api.github.com/repos/" + repo + "/actions/workflows/"
        matching = [j for j in jobs if (j.get("url") or "").startswith(prefix)]

        # 保留 jobId 最大的一个，其余删除，避免任务堆积
        matching.sort(key=lambda x: x.get("jobId", 0), reverse=True)

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


def _main():
    print("🚀 启动浏览器")
    print("🔗 使用代理: " + PROXY_SERVER if PROXY_SERVER else "🍭 未使用代理，直连访问")
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
            # 失败也必须排下一次，否则 one-shot 过期后链条断掉
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
                # 先算好再拼接，避免 f-string 内出现反斜杠（Py3.10 限制）
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
            # 无条件调度重试，不依赖 FORCE_SCHEDULE
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
            # 验证失败也无条件重试；new_expiry 有效则按到期时间排，否则 5 分钟后
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
        # 顶层异常也补一次重试调度，防止链条断裂
        try:
            _try_schedule(_retry_trigger(), "（异常退出，" + str(RETRY_AFTER_MINUTES) + " 分钟后重试）")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
