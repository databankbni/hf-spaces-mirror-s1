---
title: 2027 富士山・東京之旅
sdk: static
app_file: index.html
disable_embedding: true
thumbnail: "https://sapphirejimmy-2027-tokyo-fuji.static.hf.space/brand/tokyo-fuji-share-cover-20260821.jpg"
short_description: "東京與富士山自駕、地鐵共編旅途規劃筆記。"
---

# 旅途筆記

這是一個可在手機、平板與桌機使用的共編旅途筆記。公開 memory mode 只載入虛構資料，沒有真實旅程 seed；設定 Supabase runtime config 與 `VITE_TRIP_ID` 後，adapter factory 才會切換到 server-authoritative adapter。

## 官方即時天氣與日本路況維護

使用者明確點擊後才會啟用瀏覽器定位；座標只留在當次頁面記憶體，不寫入 URL、瀏覽器儲存或離線快照，也不會以經緯度參數送進天氣供應者網址。定位天氣卡固定顯示最近官方測站、距離、觀測／抓取時間、資料新鮮度與穩定的官方來源頁。

- 台灣目前觀測使用[交通部中央氣象署 O-A0003-001](https://opendata.cwa.gov.tw/dataset/observation/O-A0003-001) 的政府公開輕度使用資源路由；可見頁面觀測資料每 45 分鐘最多自動更新一次，回到前景時只有在資料已過刷新週期才會更新，使用者也可手動刷新（有短暫冷卻時間）。不得嵌入會員或私人 API 金鑰，也不得以非官方資料作為目前觀測的 fallback。
- 日本目前觀測使用[日本氣象廳 AMeDAS](https://www.jma.go.jp/jma/kishou/know/amedas/kaisetsu.html) 官方網域的網站資料介面；JMA 測站表使用瀏覽器快取 7 天，觀測資料同樣遵循 45 分鐘自動刷新、回到前景檢查與手動刷新策略。程式會驗證測站與數值 payload，但該網址／schema 並非文件化的穩定 API 契約；若 JMA 改版，錯誤必須保持可見並維護 adapter。
- 日本路況目前採官方連結卡：[JARTIC 即時地圖](https://www.jartic.or.jp/map/?p=A01)、[NEXCO 中日本](https://www.c-nexco.co.jp/jam/)、[國土交通省道路資訊](https://www.road-info-prvs.mlit.go.jp/roadinfo/pcen/pcTop_00_0.html) 與[山梨縣道路規制](https://www.pref.yamanashi.jp/dourokisei/)。因即時事故／封路 feed 不是穩定的瀏覽器 CORS API，介面不宣稱已嵌入即時路況。

此設計以低流量、個人使用的 static SPA 為前提。若使用量增加或官方資源路由改變，將天氣 adapter 移到 gateway 即可，UI 的資料模型不需改動。

## Local verification

```text
npm install --ignore-scripts
npm run typecheck
npm run lint
npm test
npm run build
npm run test:e2e
npm run test:e2e:pwa
npm run build
```

`npm run test:e2e:pwa` 使用 `playwright.pwa.config.ts` 與隔離的假 runtime
（Supabase 網址為 `.invalid`，不會讀取或暴露 `.env.local`），會先建立可重現的
虛構 production `dist/` 來驗證登出首屏與完全離線冷啟動。此測試會覆寫本機
`dist/`；測試結束後、送 staging 或發布前，務必再執行一次一般的
`npm run build` 還原正式設定產出的 `dist/`。

Hugging Face 發布使用本機驗證後的預建 `dist/`，不要求 Space 執行付費的
Static build job。每次發布前先執行上方完整驗證，再同步 production source
與 `dist/` 到部署 staging。

唯一 lockfile 是 `package-lock.json`，package manager 宣告為 npm 11.13.0。Production source map 關閉；`.env.example` 僅含 placeholder。Supabase PKCE verifier 與 session 預設使用同分頁 `sessionStorage`；使用者明確勾選「在這台裝置保持登入」後，才會使用同一個 origin 的 `localStorage`，讓關閉瀏覽器分頁或已安裝 PWA 後可以恢復登入。既有分頁 session 不會在切換偏好時自動搬移；登出會清除兩種 storage 的自有 auth keys 並重設偏好。不保存 Google provider token。離線快照使用 user、trip、schema 三段 partition key；有效期由 `VITE_OFFLINE_TTL_HOURS` 設定（未設定時預設 24 小時），並以旅程結束後 7 天為最低保障，取兩者較晚時間。快照只保存明確 allowlist 內容。

## Supabase / HF Static 設定

本機 Vite 會優先讀取 `.env.local`（請勿提交），再由 Hugging Face Static Space 的 `window.huggingface.variables` 讀取相同的三個公開 runtime 變數：

```text
VITE_SUPABASE_URL
VITE_SUPABASE_PUBLISHABLE_KEY
VITE_TRIP_ID
```

部署時到 Hugging Face Space → Settings → Variables 設定它們；不需要重新編譯。Static Space 的 Variables/Secrets 會被瀏覽器端程式讀取，不能視為秘密。只放 Supabase URL、publishable/anon key 與 trip UUID；絕不放 Google OAuth secret、Supabase service-role key、資料庫密碼或 HF token。缺少完整 production 設定時，adapter 會停留在沒有真實旅程資料的 fictional memory demo。

Google PKCE callback 由 app 手動交換並清理 `code`、`state`、錯誤 query；session 與 PKCE verifier 依上述明確偏好選擇 `sessionStorage` 或 `localStorage`，不保存 provider token。若 persistent storage 不可用，會安全退回分頁 session。加入邀請則獨立使用短 TTL 的 fragment continuation，成功/拒絕、登出或 callback 失敗後清除。
