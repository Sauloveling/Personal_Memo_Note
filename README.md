# 翻譯備忘簿

一個單一 HTML 檔的「備忘 + 翻譯」工具，取代把長文字塞進 Google 翻譯網址的用法，突破 5000 字上限。

## 使用方式

- 線上版（建議）：<https://sauloveling.github.io/Personal_Memo_Note/>，手機可用「加入主畫面」變成 App 圖示
- 離線版：直接用瀏覽器打開 `index.html`，不用安裝任何東西

## 跨裝置自動同步

按畫面右上角的「同步」，依畫面指示建立 GitHub 金鑰（權限只有 gist），電腦和手機各貼一次同一組金鑰即可。之後筆記會自動存到你 GitHub 帳號的私密 Gist，兩邊自動保持一致：

- 打字停止約 3 秒後自動上傳
- 切回頁面、恢復網路、每 3 分鐘會自動檢查更新
- 同一篇筆記兩台裝置同時修改時，以較晚儲存的版本為準
- 沒設定同步也完全可以用，筆記就存在該裝置的瀏覽器裡

## 功能

- **備忘**：多筆筆記、打字自動儲存、全文搜尋、字數統計。筆記存在瀏覽器的 localStorage，字數不限。
- **文字格式**：編輯區上方工具列可設定粗體、斜體、底線、大小（小/一般/大）、文字顏色（紅橘綠藍紫），以及清除格式。格式會跟著同步；翻譯與搜尋一律使用純文字，不受格式影響。
- **翻譯**：按「翻譯全文」會自動把超過 5000 字的內容在段落邊界切段，逐段翻譯後左右對照顯示，可逐段或整篇複製。
- **備援**：若線上翻譯失效，按「產生分段連結」會產生多個切好段的 Google 翻譯網頁連結。
- **圖片**：每篇筆記可附加照片 — 按「📷 加入圖片」選擇（手機可直接拍照），或在頁面上直接 Ctrl+V 貼上。圖片自動壓縮（最長邊 1280px），點縮圖看大圖，跟著筆記一起同步。
- **行事曆**：按「📅 行事曆」開啟月曆檢視，點任一天即可寫當天的事項（可多筆），像紙本月曆一樣。有事項的日子會顯示內容、今天會標示，可切換月份。行事曆事項跟著同步，手機電腦共用。
- **垃圾桶**：刪除的筆記會先進垃圾桶保留 30 天，隨時可復原，30 天後才真的清除。復原狀態會跨裝置同步。
- **版本記錄**：編輯過程每隔一段時間自動存快照（每篇最多 10 個），打錯字或刪錯段落可回到先前版本。復原前會先把當下內容存成版本，所以復原本身也能反悔。版本記錄存在本機、不佔用同步空間。
- **備份**：「備份全部」匯出全部筆記為 json（含圖片與垃圾桶），「還原」可匯回；「匯出 txt」匯出目前這篇（純文字，不含圖片）。

## 提醒設定

例行公事提醒（例如「每月 4 號申報歐洲 VAT」）由 GitHub Actions 每天台北時間早上 9 點自動檢查發送，電腦手機關機也照樣運作，完全免費。

提醒內容在 app 裡按右上角「⏰ 提醒」新增即可（需先啟用同步）。通知管道要做一次性設定：

### 一、必要：讓機器人能讀到提醒

1. 到 repo 的 **Settings → Secrets and variables → Actions → New repository secret**
2. Name 填 `GIST_TOKEN`，Secret 貼上**與 app 同步用的同一組金鑰**（`ghp_` 開頭）

### 二、Telegram 通知（約 3 分鐘）

1. 在 Telegram 搜尋 **@BotFather** → 傳送 `/newbot` → 依指示命名 → 取得 `123456:ABC...` 格式的 token
2. 加入 secret `TELEGRAM_BOT_TOKEN`，值就是上面的 token
3. 對你剛建立的機器人傳送任意一句話（例如 hi）— **這步不能省，否則機器人無法主動傳訊給你**
4. 瀏覽器開啟 `https://api.telegram.org/bot<你的TOKEN>/getUpdates`，找到 `"chat":{"id":123456789`
5. 加入 secret `TELEGRAM_CHAT_ID`，值就是那串數字

### 三、LINE 通知（約 5 分鐘）

> 註：舊的「LINE Notify」已於 2025 年 3 月停止服務，改用官方 Messaging API。

1. 到 <https://developers.line.biz/console/> 用 LINE 帳號登入
2. 建立一個 **Provider**（隨便命名，例如自己的名字）
3. 在該 Provider 下建立一個 **Messaging API channel**（頻道名稱、圖示隨意填）
4. 進入頻道的 **Messaging API** 分頁：
   - 最下方 **Channel access token (long-lived)** 按 **Issue** 產生 token → 加入 secret `LINE_CHANNEL_TOKEN`
   - 頁面上會有一個 QR code，用手機 LINE 掃描 **把這個官方帳號加為好友**（不加好友會推播失敗）
5. 取得你自己的 **userId**（U 開頭）：進入頻道 **Basic settings** 分頁，最下方「Your user ID」就是 → 加入 secret `LINE_USER_ID`
6. （建議）在 Messaging API 分頁把 **Auto-reply messages / Greeting messages** 關掉，免得每次互動它自動回你罐頭訊息

沒設定這兩個 secret 就會自動跳過 LINE，不影響其他管道。

### 四、Email 通知

支援任何 SMTP 伺服器，secret 名稱與常見 `.env` 慣例一致：

| Secret | 說明 |
|---|---|
| `SMTP_HOST` | 例：`smtp.gmail.com`。沒設就跳過 Email |
| `SMTP_PORT` | 465（SSL）或 587（STARTTLS），預設 465 |
| `SMTP_USERNAME` | SMTP 登入帳號 |
| `SMTP_PASSWORD` | SMTP 密碼。Gmail 需用<a href="https://myaccount.google.com/apppasswords">應用程式密碼</a>（16 碼），**不是**登入密碼 |
| `SMTP_USE_SSL` | 選填，`true`/`false`。沒設就依 port 自動判斷（465→SSL，其餘→STARTTLS） |
| `ALERT_EMAIL_FROM` | 選填，寄件者。沒設就用 `SMTP_USERNAME` |
| `ALERT_EMAIL_TO` | 收件者。沒設就用 `SMTP_USERNAME` |

### 五、測試

到 repo 的 **Actions → 例行提醒 → Run workflow** 手動執行一次，看 log 是否顯示 `telegram: sent` / `line: sent` / `email: sent`。

三個管道（Telegram / LINE / Email）都是選填、彼此獨立 — 只設定其中一個也能運作，沒設定的那組 secrets 會自動跳過。

## 注意事項

- 筆記存在「這台裝置的這個瀏覽器」，換裝置不會同步，請定期用「備份全部」留存。
- 清除瀏覽器資料（cookie／網站資料）會把筆記一起清掉。
- 線上翻譯使用 Google 翻譯的免費介面（非官方 API），若 Google 調整導致失效，改用「產生分段連結」即可。
- **同步金鑰等同於你筆記的存取權，只給自己的裝置用，不要分享給別人。**
- GitHub 會在 repo **連續 60 天沒有任何提交**時自動停用排程工作（會先寄信通知）。若提醒突然不再發送，到 Actions 頁面按 Enable 即可恢復。
- 排程觸發時間會有幾分鐘到數十分鐘的延遲，這是 GitHub 免費排程的正常現象。
