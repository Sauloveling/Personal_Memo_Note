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
SYNC_FILE = 'translate-memo-sync.json'
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
        if SYNC_FILE in g.get('files', {}) or REM_FILE in g.get('files', {}):
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


def is_due(r, today):
    if r.get('enabled') is False:
        return False
    if r.get('lastSent') == today.strftime('%Y-%m-%d'):
        return False
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


def send_telegram(lines):
    if not (TG_TOKEN and TG_CHAT):
        print('telegram: skipped (secrets not set)')
        return False
    text = '⏰ 今天的例行提醒\n\n' + '\n'.join('• ' + l for l in lines)
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


def send_line(lines):
    if not (LINE_TOKEN and LINE_USER):
        print('line: skipped (secrets not set)')
        return False
    text = '⏰ 今天的例行提醒\n\n' + '\n'.join('• ' + l for l in lines)
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


def send_email(lines):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and MAIL_TO):
        print('email: skipped (secrets not set)')
        return False
    msg = EmailMessage()
    msg['Subject'] = '⏰ 今天的例行提醒（%d 項）' % len(lines)
    msg['From'] = MAIL_FROM
    msg['To'] = MAIL_TO
    msg.set_content('今天要處理的例行公事：\n\n' + '\n'.join('• ' + l for l in lines) +
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


def main():
    if not GIST_TOKEN:
        print('GIST_TOKEN not set — cannot read reminders'); sys.exit(1)

    gist_id = find_gist()
    if not gist_id:
        print('no sync gist found — set up sync in the app first'); return
    gist = gh('/gists/' + gist_id)
    data = read_file(gist, REM_FILE)
    if not data or not isinstance(data.get('reminders'), list):
        print('no reminders yet'); return

    rems = data['reminders']
    today = datetime.now(TAIPEI)
    today_str = today.strftime('%Y-%m-%d')
    print('checking %d reminders for %s (Taipei)' % (len(rems), today_str))

    due = [r for r in rems if is_due(r, today)]
    if not due:
        print('nothing due today'); return

    lines = [r['text'] for r in due]
    print('due:', ' | '.join(lines))

    sent_tg = send_telegram(lines)
    sent_line = send_line(lines)
    sent_mail = send_email(lines)
    if not (sent_tg or sent_line or sent_mail):
        print('no channel delivered — leaving lastSent untouched so it retries'); sys.exit(1)

    for r in due:
        r['lastSent'] = today_str
    # 單次提醒送出後自動停用，不再重複
    for r in due:
        if r.get('type') == 'once':
            r['enabled'] = False
    data['reminders'] = rems
    data['updated'] = int(today.timestamp() * 1000)
    gh('/gists/' + gist_id, 'PATCH', {
        'files': {REM_FILE: {'content': json.dumps(data, ensure_ascii=False, indent=2)}}
    })
    print('marked %d reminders as sent' % len(due))


if __name__ == '__main__':
    main()
