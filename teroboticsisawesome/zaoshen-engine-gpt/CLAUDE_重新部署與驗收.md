# 造神引擎GPT版：重新部署與驗收

專案：`/mnt/c/Users/HP-PC/Documents/WAYNE共享專案/造神引擎GPT版`

只部署獨立 Hugging Face Space `teroboticsisawesome/zaoshen-engine-gpt`。禁止操作 ERP、Firebase 與 DNS。

## 本次修復

- 3D 有圖節點改成金色雙環。
- 節點滑過顯示縮圖，點擊顯示完整圖片與文案。
- 增加「只看有圖」篩選與圖片統計。
- 無圖節點清楚標示待補圖。
- 「建立／審核內容」與「匯出戰報」按鈕已接線。
- 左側 Roadmap、粉專營運、個人帳號營運、審核中心、安全與執行均已接到實際頁面／篩選。
- 新增 `/audience` 留言與名單頁，可讀取 88 筆名單與留言回覆範本。

## 部署

先從 `~/.bashrc` 將 `HF_TOKEN` 帶進目前 shell，但不可將 Token 寫入檔案，然後：

```bash
cd '/mnt/c/Users/HP-PC/Documents/WAYNE共享專案/造神引擎GPT版'
python3 deploy_hf.py
```

等 Space stage 變成 `RUNNING`。

## 必驗

1. `/warroom` 回應 200，顯示「29 篇有圖・73 篇待補圖・共 102 篇」。
2. 「只看有圖」切換後只剩 29 個內容節點；滑過有縮圖。
3. 點金色雙環節點後，大圖可以載入。
4. `/audience` 回應 200，全部名單為 88 筆。
5. 左側五個營運入口都可點擊並到達正確內容。
6. `/api/network` 為 102 節點，29 筆 `image_url` 非空。
7. `/api/dashboard` 的 `live` 必須維持 `false`，除非 Wayne 另外明確授權正式發文。

## 真實行銷上線條件

在 Hugging Face Space Settings → Variables and secrets 設定（不可寫進 repo）：

- `OPENAI_API_KEY`：GPT 生稿／重寫。
- `FB_PAGE_ID`：目標 Facebook 粉專。
- `FB_PAGE_TOKEN`：需具備發文所需權限。

不要自行把 `ZAOSHEN_LIVE` 改成 `1`。正式 Facebook 發送必須由 Wayne 另行確認。

留言同步尚未實作；頁面應誠實顯示尚未同步，不得回報已完成。
