# -*- coding: utf-8 -*-
"""每天由 GitHub Actions 執行：檢查同步空間裡的提醒，把今天到期的發送出去。

需要的 Secrets（在 repo 的 Settings > Secrets and variables > Actions 設定）：
  GIST_TOKEN          必要，與備忘簿同步用的同一組金鑰
  TELEGRAM_BOT_TOKEN  選填，沒設就跳過 Telegram
  TELEGRAM_CHAT_ID    選填，同上
  LINE_CHANNEL_TOKEN  選填，沒設就跳過 LINE。LINE Messaging API 的 channel access token
  LINE_USER_ID        選填，要推播給你的 userId（U 開頭）
  SMTP_HOST           選填，沒設就跳過 Email。例：smtp.gmail.com
  SMTP_PORT           選填，預設 465（SSL）或 587（STARTTLS）
  SMTP_USERNAME       選填，SMTP 登入帳號
  SMTP_PASSWORD       選填，SMTP 密碼（Gmail 需用應用程式密碼）
  SMTP_USE_SSL        選填，true/false，預設依 port 判斷
  ALERT_EMAIL_FROM    選填，寄件者，沒設就用 SMTP_USERNAME
  ALERT_EMAIL_TO      選填，收件者，沒設就用 SMTP_USERNAME
"""
import calendar
import json
import os
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

REM_FILE = 'reminders.json'
CAL_FILE = 'calendar.json'
SYNC_FILE = 'translate-memo-sync.json'
APP_URL = 'https://sauloveling.github.io/Personal_Memo_Note/'
TAIPEI = timezone(timedelta(hours=8))

GIST_TOKEN = os.environ.get('GIST_TOKEN', '')
TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TG_CHAT = os.environ.get('TELEGRAM_CHAT_ID', '')
LINE_TOKEN = os.environ.get('LINE_CHANNEL_TOKEN', '')
LINE_USER = os.environ.get('LINE_USER_ID', '')
SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT') or 465)
SMTP_USER = os.environ.get('SMTP_USERNAME', '')
SMTP_PASS = os.environ.get('SMTP_PASSWORD', '')
MAIL_FROM = os.environ.get('ALERT_EMAIL_FROM', '') or SMTP_USER
MAIL_TO = os.environ.get('ALERT_EMAIL_TO', '') or SMTP_USER

_ssl_env = os.environ.get('SMTP_USE_SSL', '').strip().lower()
if _ssl_env in ('1', 'true', 'yes', 'on'):
    USE_SSL = True
elif _ssl_env in ('0', 'false', 'no', 'off'):
    USE_SSL = False
else:
    USE_SSL = SMTP_PORT == 465


def gh(path, method='GET', body=None):
    req = urllib.request.Request('https://api.github.com' + path, method=method)
    req.add_header('Authorization', 'token ' + GIST_TOKEN)
    req.add_header('Accept', 'application/vnd.github+json')
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, data) as res:
        return json.loads(res.read().decode('utf-8'))


def find_gist():
    for g in gh('/gists?per_page=100'):
        files = g.get('files', {})
        if SYNC_FILE in files or REM_FILE in files or CAL_FILE in files:
            return g['id']
    return None


def read_file(gist, name):
    f = gist.get('files', {}).get(name)
    if not f:
        return None
    content = f.get('content')
    if f.get('truncated'):
        with urllib.request.urlopen(f['raw_url']) as r:
            content = r.read().decode('utf-8')
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        return None


def occurs_on(r, today):
    """排程當天是否落在 today（不看 enabled / lastSent / 確認狀態）。"""
    t = r.get('type')
    if t == 'daily':
        return True
    if t == 'weekly':
        # JS getDay(): 0=Sun..6=Sat ; Python weekday(): 0=Mon..6=Sun
        return r.get('weekday') == (today.weekday() + 1) % 7
    if t == 'once':
        return r.get('date') == today.strftime('%Y-%m-%d')
    if t == 'monthly':
        day = int(r.get('day', 1))
        last = calendar.monthrange(today.year, today.month)[1]
        # 例如設 31 號，但該月只有 30 天 -> 當月最後一天發送
        return today.day == min(day, last)
    return False


def is_due(r, today):
    """一般（不需確認）提醒：當天到期且今天還沒發過就發。保留給既有測試。"""
    if r.get('enabled') is False:
        return False
    if r.get('lastSent') == today.strftime('%Y-%m-%d'):
        return False
    return occurs_on(r, today)


def evaluate(r, today):
    """回傳 (要不要通知, 這次待確認的起始日或 None)。

    一般提醒：到期發一次。
    需確認提醒（ack=True）：到期後每天嘮叨，直到使用者在 app 點「完成」
    （app 會清掉 pendingSince、寫入 doneFor），才停止。
    """
    if r.get('enabled') is False:
        return (False, None)
    today_str = today.strftime('%Y-%m-%d')
    if not r.get('ack'):
        if r.get('lastSent') == today_str:
            return (False, None)
        return (occurs_on(r, today), None)
    pend = r.get('pendingSince')
    if pend:
        if r.get('lastSent') == today_str:
            return (False, None)      # 今天已經嘮叨過了
        return (True, pend)           # 尚未確認 -> 繼續嘮叨
    if occurs_on(r, today) and r.get('doneFor') != today_str:
        return (True, today_str)      # 新到期，開始等待確認
    return (False, None)


def days_pending(date_str, today):
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d').date()
        return max(1, (today.date() - d).days + 1)
    except (ValueError, TypeError):
        return 1


def build_message(rem_items, cal_lines):
    """把例行提醒與當天行事曆事項組成一則訊息（沒有的區塊就不出現）。

    rem_items 每項為 dict：{text, ack(bool), days(int), link(str)}。
    需確認的項目會附上嘮叨天數與「完成」連結。
    """
    parts = []
    if rem_items:
        lines = []
        for it in rem_items:
            lines.append('• ' + it['text'])
            if it.get('ack'):
                lines.append('  ⚠️ 尚未確認（第 %d 天）完成請點 👉 %s' % (it['days'], it['link']))
        parts.append('⏰ 今天的例行提醒\n' + '\n'.join(lines))
    if cal_lines:
        parts.append('📅 今天的行事曆\n' + '\n'.join('• ' + l for l in cal_lines))
    return '\n\n'.join(parts)


def send_telegram(text):
    if not (TG_TOKEN and TG_CHAT):
        print('telegram: skipped (secrets not set)')
        return False
    data = urllib.parse.urlencode({'chat_id': TG_CHAT, 'text': text}).encode()
    try:
        with urllib.request.urlopen(
            'https://api.telegram.org/bot%s/sendMessage' % TG_TOKEN, data
        ) as res:
            ok = json.loads(res.read().decode('utf-8')).get('ok')
            print('telegram: sent' if ok else 'telegram: rejected')
            return bool(ok)
    except urllib.error.HTTPError as e:
        print('telegram: FAILED', e.code, e.read().decode('utf-8', 'replace')[:200])
    except Exception as e:
        print('telegram: FAILED', e)
    return False


def send_line(text):
    if not (LINE_TOKEN and LINE_USER):
        print('line: skipped (secrets not set)')
        return False
    # LINE 單則文字上限 5000 字，超過就截斷保險
    if len(text) > 4900:
        text = text[:4900] + '…'
    body = json.dumps({'to': LINE_USER, 'messages': [{'type': 'text', 'text': text}]}).encode('utf-8')
    req = urllib.request.Request('https://api.line.me/v2/bot/message/push', data=body, method='POST')
    req.add_header('Authorization', 'Bearer ' + LINE_TOKEN)
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            print('line: sent (HTTP %d)' % res.status)
            return True
    except urllib.error.HTTPError as e:
        print('line: FAILED', e.code, e.read().decode('utf-8', 'replace')[:200])
    except Exception as e:
        print('line: FAILED', type(e).__name__, e)
    return False


def send_email(text, count):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and MAIL_TO):
        print('email: skipped (secrets not set)')
        return False
    msg = EmailMessage()
    msg['Subject'] = '⏰ 今天要處理的事項（%d 項）' % count
    msg['From'] = MAIL_FROM
    msg['To'] = MAIL_TO
    msg.set_content(text +
                    '\n\n— 翻譯備忘簿 https://sauloveling.github.io/Personal_Memo_Note/')
    try:
        ctx = ssl.create_default_context()
        if USE_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=30) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        print('email: sent to', MAIL_TO, 'via %s:%d' % (SMTP_HOST, SMTP_PORT),
              '(SSL)' if USE_SSL else '(STARTTLS)')
        return True
    except Exception as e:
        print('email: FAILED', type(e).__name__, e)
    return False


def alert_token_expired():
    """同步金鑰失效時，改用其他管道發一則看得懂的通知（那些管道的金鑰是獨立的）。"""
    msg = ('⚠️ 翻譯備忘簿：同步金鑰（GIST_TOKEN）已失效或過期，例行提醒與行事曆通知已暫停。\n\n'
           '請重新產生一組「不過期」的金鑰，並更新到 GitHub 的 GIST_TOKEN，'
           '以及 app 各裝置的「同步」設定，即可恢復。')
    ok = send_telegram(msg)
    ok = send_line(msg) or ok
    ok = send_email(msg, 1) or ok
    print('GIST_TOKEN invalid — alerted via channels:', ok)


def main():
    if not GIST_TOKEN:
        print('GIST_TOKEN not set — cannot read reminders'); sys.exit(1)

    try:
        gist_id = find_gist()
        if not gist_id:
            print('no sync gist found — set up sync in the app first'); return
        gist = gh('/gists/' + gist_id)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            # 金鑰失效：不要讓整個 job 崩潰（避免看不懂的失敗信），改發清楚的提示
            alert_token_expired()
            return
        raise

    today = datetime.now(TAIPEI)
    today_str = today.strftime('%Y-%m-%d')

    # --- 例行提醒 ---
    data = read_file(gist, REM_FILE)
    rems = data.get('reminders', []) if isinstance(data, dict) else []
    # due 為 (reminder, 這次待確認起始日或 None) 的清單
    due = []
    for r in rems:
        notify, pend = evaluate(r, today)
        if notify:
            due.append((r, pend))
    print('checking %d reminders for %s (Taipei)' % (len(rems), today_str))

    # --- 行事曆上當天的事項 ---
    cal = read_file(gist, CAL_FILE)
    all_events = cal.get('events', []) if isinstance(cal, dict) else []
    due_events = [e for e in all_events
                  if e.get('date') == today_str and e.get('lastSent') != today_str]
    print('checking %d calendar events, %d due today' % (len(all_events), len(due_events)))

    if not due and not due_events:
        print('nothing due today'); return

    rem_items = []
    for r, pend in due:
        item = {'text': r['text'], 'ack': bool(r.get('ack'))}
        if r.get('ack'):
            start = r.get('pendingSince') or pend or today_str
            item['days'] = days_pending(start, today)
            item['link'] = APP_URL + '#ack=' + str(r.get('id', ''))
        rem_items.append(item)
    cal_lines = [e['text'] for e in due_events]
    if rem_items:
        print('due reminders:', ' | '.join(
            it['text'] + (' [需確認 第%d天]' % it['days'] if it.get('ack') else '') for it in rem_items))
    if cal_lines:
        print('due calendar:', ' | '.join(cal_lines))

    text = build_message(rem_items, cal_lines)
    sent_tg = send_telegram(text)
    sent_line = send_line(text)
    sent_mail = send_email(text, len(rem_items) + len(cal_lines))
    if not (sent_tg or sent_line or sent_mail):
        print('no channel delivered — leaving lastSent untouched so it retries'); sys.exit(1)

    files = {}
    if due:
        for r, pend in due:
            r['lastSent'] = today_str
            r['updated'] = int(today.timestamp() * 1000)
            if r.get('ack'):
                # 記錄這次到期的待確認起始日（若尚未記錄）
                if not r.get('pendingSince'):
                    r['pendingSince'] = pend or today_str
            elif r.get('type') == 'once':
                # 一般單次提醒送出後自動停用（需確認的則等使用者確認才停）
                r['enabled'] = False
        data['reminders'] = rems
        data['updated'] = int(today.timestamp() * 1000)
        files[REM_FILE] = {'content': json.dumps(data, ensure_ascii=False, indent=2)}
    if due_events:
        for e in due_events:
            e['lastSent'] = today_str
        cal['events'] = all_events
        cal['updated'] = int(today.timestamp() * 1000)
        files[CAL_FILE] = {'content': json.dumps(cal, ensure_ascii=False, indent=2)}
    if files:
        gh('/gists/' + gist_id, 'PATCH', {'files': files})
    print('marked %d reminders and %d calendar events as sent' % (len(due), len(due_events)))


if __name__ == '__main__':
    main()
