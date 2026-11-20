#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TheRose Cloud 自动续期脚本"""

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import requests
from playwright.sync_api import sync_playwright

# ==================== 配置 ====================
EMAIL = os.environ.get("THEROSE_EMAIL", "")
PASSWORD = os.environ.get("THEROSE_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
CRONJOB_API_KEY = os.environ.get("CRONJOB_API_KEY", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_REPO = os.environ.get("GH_REPO", "18686187636/Auto-Renew-Therose")
GH_WORKFLOW_ID = os.environ.get("GH_WORKFLOW_ID", "318389074")
GH_BRANCH = os.environ.get("GH_BRANCH", "main")
PROXY_SERVER = os.environ.get("PROXY_SERVER", "")
HEADLESS = os.environ.get("HEADLESS", "1") != "0"

LOGIN_URL = "https://therose.cloud/login"
DASHBOARD_URL = "https://therose.cloud/dashboard"

MINUTES_BEFORE_EXPIRY = 28
RENEW_EXTEND_HOURS = 6
RENEW_WAIT_SECONDS = 180

BJ = timezone(timedelta(hours=8))
UTC = timezone.utc

SERVER_CARD_SELECTOR = 'div.trc-server[data-testid^="server-"]'
TURNSTILE_IFRAME = 'iframe[src*="challenges.cloudflare.com"]'

COUNTDOWN_FRAGMENT = re.compile(
    r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})(?![a-zA-Z0-9])")
WAIT_RE = re.compile(
    r"Renewable in\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?", re.I)

_SCHEDULED = {"done": False}


# ==================== 工具函数 ====================
def log(msg):
    print(msg, flush=True)


def shot(page, name):
    ts = int(time.time() * 1000)
    fn = "step_" + name + "_" + str(ts) + ".png"
    try:
        page.screenshot(path=fn)
        log("📸 截图已保存: " + fn)
        return fn
    except Exception as e:
        log("⚠️ 截图失败: " + str(e))
        return None


def safe_execute_script(page, script, arg=None):
    """JS 执行统一入口，异常不抛出。"""
    try:
        if arg is None:
            return page.evaluate(script)
        return page.evaluate(script, arg)
    except Exception as e:
        log("⚠️ JS 执行失败: " + str(e))
        return None


def parse_duration(text):
    """解析 '3h 47m 30s' 这类剩余时间为秒。"""
    if not text:
        return None
    total = 0
    found = False
    for num, unit in re.findall(r"(\d+)\s*([dhms])", text, re.I):
        n = int(num)
        u = unit.lower()
        if u == "d":
            total += n * 86400
        elif u == "h":
            total += n * 3600
        elif u == "m":
            total += n * 60
        else:
            total += n
        found = True
    return total if found else None


def parse_expiry(text):
    """解析到期时间字符串为北京时间 datetime。"""
    if not text:
        return None
    m = COUNTDOWN_FRAGMENT.search(text)
    if not m:
        return None
    raw = m.group(1)
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ)
    except Exception:
        return None


def fmt_bj(dt):
    return dt.astimezone(BJ).strftime("%Y-%m-%d %H:%M:%S")


# ==================== Telegram ====================
def tg_send(text, image_path=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        if image_path and os.path.exists(image_path):
            url = ("https://api.telegram.org/bot"
                   + TELEGRAM_BOT_TOKEN + "/sendPhoto")
            with open(image_path, "rb") as f:
                r = requests.post(url, timeout=60, data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": text[:1000],
                }, files={"photo": f})
            if r.status_code == 200:
                log("📨 Telegram 通知已发送")
                return
            log("⚠️ Telegram 图片发送失败: " + str(r.status_code))

        url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
        r = requests.post(url, timeout=30, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text[:4000],
            "disable_web_page_preview": "true",
        })
        if r.status_code == 200:
            log("📨 Telegram 通知已发送")
        else:
            log("⚠️ Telegram 发送失败: " + str(r.status_code) + " " + r.text)
    except Exception as e:
        log("⚠️ Telegram 异常: " + str(e))


# ==================== 调度 ====================
def _verify_job_schedule(jid, headers, tag=""):
    """回读任务，打印 schedule 关键字段。"""
    try:
        r = requests.get("https://api.cron-job.org/jobs/" + str(jid),
                         headers=headers, timeout=30)
        if r.status_code != 200:
            log("⚠️ 回读 " + tag + " 失败: HTTP "
                + str(r.status_code) + " " + r.text)
            return None
        detail = r.json().get("jobDetails", {}) or {}
        sc = detail.get("schedule", {}) or {}
        log("🔎 回读 " + tag + " jobId=" + str(jid)
            + " enabled=" + str(detail.get("enabled")))
        log("🔎 回读 " + tag
            + " minutes=" + str(sc.get("minutes"))
            + " hours=" + str(sc.get("hours"))
            + " mdays=" + str(sc.get("mdays"))
            + " months=" + str(sc.get("months"))
            + " wdays=" + str(sc.get("wdays"))
            + " tz=" + str(sc.get("timezone")))
        log("🔎 回读 " + tag
            + " expiresAt=" + str(sc.get("expiresAt"))
            + " nextRun=" + str(sc.get("nextRun") or sc.get("next")))
        return sc
    except Exception as e:
        log("⚠️ 回读 " + tag + " 异常: " + str(e))
        return None


def schedule_via_cronjob(trigger_timestamp):
    if not CRONJOB_API_KEY or not GH_TOKEN:
        log("⚠️ 缺少 CRONJOB_API_KEY 或 GH_TOKEN，跳过调度")
        return False

    dt = datetime.fromtimestamp(trigger_timestamp, tz=UTC)
    exp = dt + timedelta(minutes=30)

    schedule = {
        "minutes": [dt.minute],
        "hours": [dt.hour],
        "mdays": [dt.day],
        "months": [dt.month],
        "wdays": [-1],
        "timezone": "UTC",
        "expiresAt": int(exp.timestamp()),
    }

    dispatch_url = ("https://api.github.com/repos/" + GH_REPO
                    + "/actions/workflows/" + GH_WORKFLOW_ID + "/dispatches")

    payload = {"job": {
        "enabled": True,
        "url": dispatch_url,
        "requestMethod": 1,
        "saveResponses": True,
        "schedule": schedule,
        "extendedData": {
            "headers": {
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + GH_TOKEN,
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "cron-job.org/1.0",
            },
            "body": json.dumps({"ref": GH_BRANCH}),
        },
    }}

    headers = {
        "Authorization": "Bearer " + CRONJOB_API_KEY,
        "Content-Type": "application/json",
    }

    log("📤 触发 (UTC): " + str(dt))
    log("📤 到期 (UTC): " + str(exp))

    try:
        resp = requests.get("https://api.cron-job.org/jobs",
                            headers=headers, timeout=30)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        log("📋 现有任务数量: " + str(len(jobs)))

        matching = [j for j in jobs if j.get("url") == dispatch_url]

        if not matching and jobs:
            for j in jobs:
                log("🔎 现有 job " + str(j.get("jobId"))
                    + " URL=" + repr(j.get("url")))
            log("🔎 期望 URL=" + repr(dispatch_url))

        matching.sort(key=lambda j: j.get("jobId") or 0, reverse=True)
        for job in matching[1:]:
            jid = job.get("jobId")
            if jid:
                r = requests.delete("https://api.cron-job.org/jobs/" + str(jid),
                                    headers=headers, timeout=30)
                log("🗑️ 删除多余 job " + str(jid) + ": " + str(r.status_code))
        if matching:
            matching = matching[:1]

        # ---------- 已存在：PATCH 更新 ----------
        if matching:
            jid = matching[0].get("jobId")
            r = requests.patch("https://api.cron-job.org/jobs/" + str(jid),
                               headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                log("✅ 任务已更新，ID: " + str(jid))
                _verify_job_schedule(jid, headers, "更新后")
                return True
            log("❌ 更新任务失败: " + str(r.status_code) + " " + r.text)
            return False

        # ---------- 不存在：PUT 创建后立刻 PATCH 补 expiresAt ----------
        r = requests.put("https://api.cron-job.org/jobs", headers=headers,
                         json=payload, timeout=30)
        if r.status_code != 200:
            log("❌ 创建任务失败: " + str(r.status_code) + " " + r.text)
            return False

        jid = r.json().get("jobId")
        log("✅ 新任务已创建，ID: " + str(jid))
        _verify_job_schedule(jid, headers, "创建后")

        rp = requests.patch("https://api.cron-job.org/jobs/" + str(jid),
                            headers=headers, json=payload, timeout=30)
        if rp.status_code == 200:
            log("🔧 已补丁 expiresAt，jobId=" + str(jid))
        else:
            log("⚠️ 补丁失败: " + str(rp.status_code) + " " + rp.text)

        _verify_job_schedule(jid, headers, "补丁后")
        return True

    except Exception as e:
        log("❌ cron-job.org API 异常: " + str(e))
        return False


def schedule_next(reason, trigger_dt=None):
    """统一调度入口，一次运行只调度一次。"""
    if _SCHEDULED["done"]:
        log("ℹ️ 已调度过，跳过重复调度（" + reason + "）")
        return True
    _SCHEDULED["done"] = True

    if trigger_dt is None:
        trigger_dt = datetime.now(UTC) + timedelta(minutes=5)

    log("🔄 安排下一次执行 （" + reason + "）: " + fmt_bj(trigger_dt) + " (北京)")
    ok = schedule_via_cronjob(trigger_dt.timestamp())
    if not ok:
        log("⚠️ 调度失败（" + reason + "）")
    return ok


# ==================== 浏览器动作 ====================
def launch_browser(p):
    log("🚀 启动浏览器")
    args = ["--no-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled"]
    kw = {"headless": HEADLESS, "args": args}
    if PROXY_SERVER:
        log("🔗 使用代理: " + PROXY_SERVER)
        kw["proxy"] = {"server": PROXY_SERVER}
    browser = p.chromium.launch(**kw)
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"),
        locale="zh-CN",
    )
    page = ctx.new_page()
    page.set_default_timeout(30000)
    return browser, ctx, page


def check_ip(page):
    try:
        page.goto("https://api.ipify.org?format=json", timeout=20000)
        body = page.inner_text("body")
        data = json.loads(body)
        log("📍 当前出口 IP: " + str(data.get("ip")))
    except Exception as e:
        log("⚠️ 出口 IP 检测失败: " + str(e))


def dismiss_consent(page):
    selectors = [
        'button:has-text("Accept All")',
        'button:has-text("Accept")',
        'button:has-text("同意")',
        'button:has-text("我同意")',
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("✅ 已点击 Consent 按钮")
                time.sleep(1)
                return True
        except Exception:
            continue
    log("ℹ️ 未检测到 Consent 按钮")
    return False


def handle_turnstile(page):
    try:
        page.wait_for_selector(TURNSTILE_IFRAME, timeout=15000)
    except Exception:
        log("⚠️ 未检测到 Turnstile iframe，可能无需验证")
        return True

    log("🛡 处理 Turnstile...")
    for attempt in range(1, 4):
        try:
            fl = page.frame_locator(TURNSTILE_IFRAME)
            for sel in ['input[type="checkbox"]', ".cb-lb", "label"]:
                box = fl.locator(sel)
                if box.count() > 0:
                    box.first.click(timeout=8000)
                    time.sleep(3)
                    log("✅ Turnstile 已处理")
                    return True
        except Exception as e:
            log("⚠️ Turnstile 第 " + str(attempt) + " 次尝试: " + str(e))
        time.sleep(2)
    log("⚠️ Turnstile 未确认通过，继续后续流程")
    return True


def login(page):
    for attempt in range(1, 3):
        log("🔄 登录尝试 " + str(attempt) + "/2")
        try:
            log("🌐 打开登录页面...")
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            shot(page, "attempt_" + str(attempt) + "_page_loaded")

            log("📧 等待邮箱输入框...")
            page.wait_for_selector(
                'input[type="email"], input[name="email"], #email', timeout=30000)
            page.fill('input[type="email"], input[name="email"], #email', EMAIL)
            log("✅ 邮箱已填写")
            shot(page, "attempt_" + str(attempt) + "_email_filled")

            log("🔑 等待密码输入框...")
            page.wait_for_selector('input[type="password"]', timeout=30000)
            page.fill('input[type="password"]', PASSWORD)
            log("✅ 密码已填写")
            shot(page, "attempt_" + str(attempt) + "_password_filled")

            log("⏳ 等待 Turnstile iframe 出现...")
            handle_turnstile(page)
            shot(page, "attempt_" + str(attempt) + "_captcha_handled")

            time.sleep(6)
            shot(page, "attempt_" + str(attempt) + "_after_6s_wait")

            log("🔑 点击登录按钮...")
            clicked = False
            for sel in ['button[type="submit"]',
                        'button:has-text("Sign in")',
                        'button:has-text("登录")']:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                safe_execute_script(
                    page, "document.querySelector('form').requestSubmit()")
            shot(page, "attempt_" + str(attempt) + "_login_clicked")

            try:
                page.wait_for_url("**/dashboard**", timeout=45000)
            except Exception:
                pass

            cur = page.url
            log("📄 当前 URL: " + cur + " | Title: " + str(page.title()))
            if "dashboard" in cur:
                log("✅ 登录成功，已跳转到 dashboard")
                shot(page, "attempt_" + str(attempt) + "_login_success")
                return True

            log("⚠️ 登录未跳转 dashboard")
            dismiss_consent(page)
            shot(page, "attempt_" + str(attempt) + "_login_failed")

        except Exception as e:
            log("❌ 登录异常: " + str(e))
            try:
                shot(page, "attempt_" + str(attempt) + "_exception")
            except Exception:
                pass

        time.sleep(3)

    log("❌ 登录失败")
    return False


def snapshot_server_from_html(html):
    """从 HTML 兜底提取 uuid 与到期时间。"""
    if not html:
        return None
    m = COUNTDOWN_FRAGMENT.search(html)
    if not m:
        return None
    raw = m.group(1)
    try:
        expiry = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ)
    except Exception:
        return None

    uuid = None
    start = max(0, m.start() - 4000)
    end = min(len(html), m.end() + 4000)
    window = html[start:end]

    um = re.search(r'data-testid="countdown-([0-9a-fA-F\-]{36})"', window)
    if um:
        uuid = um.group(1)
    else:
        um2 = re.search(
            r'data-testid="(?:renew|server)-([0-9a-fA-F\-]{36})"', window)
        if um2:
            uuid = um2.group(1)

    return {"uuid": uuid, "expiry": expiry, "raw": raw}


def read_dashboard(page):
    log("⏳ 等待 dashboard React 渲染完成...")
    try:
        page.wait_for_selector(SERVER_CARD_SELECTOR, timeout=60000)
        log("✅ 服务器卡片已出现")
    except Exception as e:
        log("❌ 服务器卡片未出现: " + str(e))
        shot(page, "dashboard_no_card")
        return None

    dismiss_consent(page)

    card = page.query_selector(SERVER_CARD_SELECTOR)
    uuid = None
    if card:
        testid = card.get_attribute("data-testid") or ""
        if testid.startswith("server-"):
            uuid = testid[len("server-"):]

    if uuid:
        log("🔍 服务器 UUID: " + uuid)
    else:
        log("⚠️ 未能从卡片取到 UUID")

    countdown_text = ""
    if uuid:
        try:
            el = page.query_selector(
                '[data-testid="countdown-' + uuid + '"] .countdown-time')
            if el:
                countdown_text = (el.inner_text() or "").strip()
        except Exception:
            pass
    if not countdown_text:
        try:
            el = page.query_selector(".countdown-time")
            if el:
                countdown_text = (el.inner_text() or "").strip()
        except Exception:
            pass

    shot(page, "dashboard_loaded")

    expiry = parse_expiry(countdown_text)
    remaining = parse_duration(countdown_text)

    if not uuid or not expiry:
        html = safe_execute_script(page, "document.documentElement.outerHTML")
        snap = snapshot_server_from_html(html)
        if snap:
            if not uuid and snap.get("uuid"):
                uuid = snap["uuid"]
                log("🔍 兜底 UUID: " + uuid)
            if not expiry and snap.get("expiry"):
                expiry = snap["expiry"]
            if remaining is None and snap.get("raw"):
                remaining = parse_duration(snap.get("raw"))

    if not uuid or not expiry:
        log("❌ 解析服务器信息失败")
        return None

    now = datetime.now(BJ)
    if remaining is None:
        remaining = int((expiry - now).total_seconds())

    log("⏰ 到期(北京): " + expiry.strftime("%Y-%m-%d %H:%M:%S"))
    hh = remaining // 3600
    mm = (remaining % 3600) // 60
    ss = remaining % 60
    log("📉 剩余: " + str(hh) + "h " + str(mm) + "m " + str(ss) + "s")

    btn_text = ""
    if uuid:
        try:
            el = page.query_selector('button[data-testid="renew-' + uuid + '"]')
            if el:
                btn_text = (el.inner_text() or "").strip()
        except Exception:
            pass
    if btn_text:
        log("🔘 按钮: " + btn_text)

    return {
        "uuid": uuid,
        "expiry": expiry,
        "remaining": remaining,
        "button_text": btn_text,
    }


def wait_until_renewable(page, uuid, max_wait_seconds=RENEW_WAIT_SECONDS):
    btn_sel = 'button[data-testid="renew-' + uuid + '"]'
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        try:
            el = page.query_selector(btn_sel)
            if el is None:
                return False
            if not el.is_disabled():
                return True
            txt = (el.inner_text() or "").strip()
            m = WAIT_RE.search(txt)
            if m:
                h = int(m.group(1) or 0)
                mi = int(m.group(2) or 0)
                s = int(m.group(3) or 0)
                total = h * 3600 + mi * 60 + s
                if total <= 0:
                    return True
                if total > max_wait_seconds:
                    log("⚠️ 按钮还需等待 " + str(total) + "s，超出上限")
                    return False
        except Exception:
            pass
        time.sleep(2)
    return False


def renew_server(page, uuid):
    if not wait_until_renewable(page, uuid):
        log("❌ 按钮未进入可点击状态")
        return False

    btn_sel = 'button[data-testid="renew-' + uuid + '"]'
    try:
        el = page.query_selector(btn_sel)
        if el is None:
            log("❌ 未找到续期按钮")
            return False
        el.click()
        log("🖱 已点击续期按钮")
        shot(page, "renew_clicked")
    except Exception as e:
        log("❌ 点击续期按钮失败: " + str(e))
        return False

    log("⏳ 等待续期结果...")
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            el = page.query_selector(
                '[data-testid="countdown-' + uuid + '"] .countdown-time')
            txt = (el.inner_text() or "").strip() if el else ""
        except Exception:
            txt = ""

        new_expiry = parse_expiry(txt)
        if new_expiry:
            delta = new_expiry - datetime.now(BJ)
            if delta > timedelta(hours=RENEW_EXTEND_HOURS - 1):
                log("✅ 续期成功，新到期(北京): "
                    + new_expiry.strftime("%Y-%m-%d %H:%M:%S"))
                shot(page, "renew_success")
                return True

        body = safe_execute_script(
            page, "document.body ? document.body.innerText : ''") or ""
        for kw in ["成功", "Success", "renewed", "已续期"]:
            if kw.lower() in body.lower():
                log("✅ 检测到成功提示: " + kw)
                shot(page, "renew_success_text")
                return True

        time.sleep(3)

    log("❌ 续期结果未确认")
    shot(page, "renew_unconfirmed")
    return False


# ==================== 主流程 ====================
def main():
    if not EMAIL or not PASSWORD:
        log("❌ 缺少 THEROSE_EMAIL / THEROSE_PASSWORD")
        return 1

    if PROXY_SERVER:
        log("🔗 已启用代理: " + PROXY_SERVER)

    try:
        with sync_playwright() as p:
            browser, ctx, page = launch_browser(p)
            try:
                check_ip(page)

                # ---------- 登录 ----------
                if not login(page):
                    img = shot(page, "login_result")
                    tg_send("❌ TheRose 登录失败，已安排 5 分钟后重试", img)
                    schedule_next("登录失败",
                                  datetime.now(UTC) + timedelta(minutes=5))
                    return 1

                # ---------- 解析 dashboard ----------
                info = read_dashboard(page)
                if not info:
                    img = shot(page, "login_result")
                    tg_send("❌ TheRose 服务器信息解析失败，已安排 5 分钟后重试", img)
                    schedule_next("解析失败",
                                  datetime.now(UTC) + timedelta(minutes=5))
                    return 1

                expiry = info["expiry"]
                trigger_dt = expiry - timedelta(minutes=MINUTES_BEFORE_EXPIRY)
                now = datetime.now(BJ)

                # ---------- 窗口未到：直接调度 ----------
                if now < trigger_dt:
                    img = shot(page, "login_result")
                    tg_send("ℹ️ TheRose 窗口未到\n"
                            + "到期(北京): "
                            + expiry.strftime("%Y-%m-%d %H:%M:%S") + "\n"
                            + "下次(北京): "
                            + trigger_dt.strftime("%Y-%m-%d %H:%M:%S"), img)
                    schedule_next("窗口未到", trigger_dt.astimezone(UTC))
                    return 0

                # ---------- 进入窗口：续期 ----------
                log("🎯 进入续期窗口，开始续期")
                ok = renew_server(page, info["uuid"])
                img = shot(page, "login_result")

                if ok:
                    tg_send("✅ TheRose 续期成功", img)
                    info2 = read_dashboard(page)
                    if info2:
                        nxt = (info2["expiry"]
                               - timedelta(minutes=MINUTES_BEFORE_EXPIRY))
                        schedule_next("续期成功", nxt.astimezone(UTC))
                    else:
                        schedule_next("续期成功-解析失败",
                                      datetime.now(UTC) + timedelta(minutes=5))
                    return 0

                tg_send("❌ TheRose 续期失败，已安排 5 分钟后重试", img)
                schedule_next("续期失败",
                              datetime.now(UTC) + timedelta(minutes=5))
                return 1

            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

    except Exception as e:
        log("❌ 顶层异常: " + str(e))
        log(traceback.format_exc())
        schedule_next("顶层异常", datetime.now(UTC) + timedelta(minutes=5))
        return 1


if __name__ == "__main__":
    sys.exit(main())
