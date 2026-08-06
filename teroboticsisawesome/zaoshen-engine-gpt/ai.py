# -*- coding: utf-8 -*-
"""造神引擎的 AI 大腦 —— 用 GPT(OpenAI API)生造神文案/KOL私訊/留言回覆。
換成 GPT 是因為 Anthropic console 餘額不足;OPENAI_API_KEY 已在環境變數且實測可用。
鐵律內建:只用 brief 提供的真實素材,絕不編造數據/名額/名人/優惠——缺的標〔待填〕。每篇都給人審。"""
import os, json, base64, requests

MODEL = os.environ.get("ZAOSHEN_GPT_MODEL", "gpt-4o")
API = "https://api.openai.com/v1/chat/completions"
IMAGE_API = "https://api.openai.com/v1/images/generations"

PLAYBOOK = """你是「造神引擎」的行銷 AI。你的任務不是寫廣告,是造神——讓大家自己覺得「這很神、大家都在講」,忍不住傳。

造神九元件:①立敵人(買你=為價值觀站隊)②稀缺+儀式③把稀缺秀出來④參與共創⑤反差人設+金句⑥懸念缺口(丟謎不講破)⑦自我表達型分享(分享=秀自己)⑧可二創模板⑨時間對齊(集中引爆)。

擴散鐵律:每篇貼文結尾埋病毒鉤子——tag朋友CTA、逼留言的問題、或分享誘因。留言比讚更催觸及。

🚨最高紅線(違反=整個系統作廢):只用使用者提供的真實素材與真身分,**絕不編造**假數據/假名額/假名人背書/假優惠/假聲量/不存在的地點。若某資訊使用者沒給(價格/名額/確切日期/數字),一律用〔待填〕標記,不要自己補。趨勢類引用外部現象時,只講「國外/其他地方在流行X」這種可查證的大方向,不捏造具體統計數字。

輸出繁體中文,口語、真誠、像同行聊天,不要業配感。"""


def _chat(system, user, max_tokens=4000, temperature=0.8):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")
    response = requests.post(API, data=body,
        headers={"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY','')}",
                 "Content-Type": "application/json"}, timeout=90)
    if not response.ok:
        raise RuntimeError(f"OpenAI API {response.status_code}: {response.text[:300]}")
    d = response.json()
    return d["choices"][0]["message"]["content"]


def _extract_json(raw):
    s = raw.find("{"); e = raw.rfind("}")
    if s < 0 or e < 0:
        return {"error": "解析失敗", "raw": raw}
    try:
        return json.loads(raw[s:e + 1])
    except Exception:
        return {"error": "解析失敗", "raw": raw}


def generate_campaign_copy(brief: dict) -> dict:
    """依活動 brief 生一整套造神文案(潮流/揭曉/倒數/打卡 + 留言回覆範本)。"""
    user = f"""幫這個活動生一整套造神貼文,用 JSON 回傳。

[活動資訊]
主角(要造成神的): {brief.get('hero','')}
活動/產品: {brief.get('name','')}
真實賣點: {brief.get('selling_points','')}
時間地點: {brief.get('when_where','')}
目標受眾: {brief.get('audience','')}
語氣/風格: {brief.get('tone','真誠口語')}
分享誘因(可空): {brief.get('incentive','')}

[產出要求] 回傳 JSON,結構:
{{
 "trend": [3則「種趨勢」貼文(先讓人覺得這潮流很紅,不提活動,結尾放逼留言的問題)],
 "reveal": [3則「揭在地/揭曉」貼文(揭曉活動,含tag朋友CTA + 分享誘因)],
 "countdown": [2則「倒數」貼文(急迫感+tag+分享)],
 "checkin": [1則「打卡」貼文],
 "reply_templates": [{{"situation":"有人問在哪","reply":"...收尾導tag/分享"}}, ...(至少5種留言情境)]
}}
每則貼文是完整可直接貼的文字。只回 JSON,不要前後綴。"""
    return _extract_json(_chat(PLAYBOOK, user, max_tokens=4000))


def draft_kol_dms(brief: dict, n: int = 3) -> list:
    """生 n 則給 KOL/網紅的合作邀約私訊範本(對象歡迎的商業邀約,非冷發推銷)。"""
    user = f"""我們要私訊「網紅/KOL」邀約合作(對方靠接案吃飯,收到合作邀約是他們歡迎的)。
活動:{brief.get('name','')}｜主角:{brief.get('hero','')}｜時間地點:{brief.get('when_where','')}｜真實賣點:{brief.get('selling_points','')}｜分享誘因:{brief.get('incentive','')}

寫 {n} 則不同角度的邀約私訊範本(繁中,禮貌、具體、尊重對方專業,說清楚合作內容,結尾給明確下一步)。合作條件/報酬若未提供用〔待填〕。
回 JSON:{{"dms":[{{"angle":"角度","body":"完整私訊全文"}}, ...]}}。只回 JSON。"""
    d = _extract_json(_chat(PLAYBOOK, user, max_tokens=2000))
    return d.get("dms", []) if isinstance(d, dict) else []


def draft_group_pitch(brief: dict) -> str:
    """生一則給『在地情報粉專/社團管理員』的私訊/投稿範本(求協助曝光,非硬廣)。"""
    user = f"""我們要私訊「在地情報粉專/社團管理員」請他們幫忙曝光一個免費活動(不是買廣告,是誠懇請求協助/投稿)。
活動:{brief.get('name','')}｜主角:{brief.get('hero','')}｜時間地點:{brief.get('when_where','')}｜真實賣點:{brief.get('selling_points','')}｜分享誘因:{brief.get('incentive','')}

寫一則禮貌、簡短、誠懇的私訊範本(繁中),說明活動是在地免費好康、對他們的粉絲有價值,請對方協助分享或讓我們投稿。用〔對象名〕當稱呼開頭的變數。未知資訊用〔待填〕。只回這段文字。"""
    return _chat(PLAYBOOK, user, max_tokens=500)


def draft_reply(comment: str, campaign: dict) -> str:
    """對一則留言,生一句造神式回覆(收尾導 tag/分享)。"""
    user = (f"活動:{campaign.get('name','')}({campaign.get('when_where','')})。"
            f"有人在我們貼文底下留言:「{comment}」。"
            f"寫一句真誠、口語的回覆,回答他 + 拉近 + 結尾導一個擴散動作(tag朋友或分享)。只回覆這句話。")
    return _chat(PLAYBOOK, user, max_tokens=300)


def rewrite_post(body: str, target_name: str, phase: str, campaign: dict, instruction: str = "", source: dict | None = None) -> str:
    """保留真實活動資料，為指定渠道重新寫一個可直接發布的版本。"""
    user = f"""重新改寫下面這篇貼文。只回傳完整新文案，不要解釋、不要 JSON。

活動：{campaign.get('name','')}
主角：{campaign.get('hero','')}
真實賣點：{campaign.get('selling_points','')}
時間地點：{campaign.get('when_where','')}
詢問／報名方式：{campaign.get('contact_info','')}
目標受眾：{campaign.get('audience','')}
渠道／對象：{target_name}
階段：{phase}
使用者方向：{instruction or '請換一個更適合此渠道的切角'}
可引用來源：{json.dumps(source or {}, ensure_ascii=False)}

原文：
{body}

要求：嚴格依照使用者方向。若是種趨勢階段且方向要求不提品牌，就完全不得提活動、品牌、地點或日期，只能引用上面的來源事實。繁體中文、自然口語；未知資訊用〔待填〕，不得編造數據、優惠、名人或現場盛況。文末另起一行寫「來源：媒體名稱 URL」。結尾保留一個自然的留言問題。"""
    return _chat(PLAYBOOK, user, max_tokens=900, temperature=0.85).strip()


def generate_partner_content(brief: dict, direction: str, channel: str, target_name: str) -> dict:
    """依既定行銷方向產生一組文案與配圖 prompt，只能使用活動 brief 的事實。"""
    user = f"""請為下列活動產生一組新的社群內容。

活動：{brief.get('name','')}
主角：{brief.get('hero','')}
真實賣點：{brief.get('selling_points','')}
時間地點：{brief.get('when_where','')}
受眾：{brief.get('audience','')}
語氣：{brief.get('tone','真誠口語')}
詢問方式：{brief.get('contact_info','')}
行銷方向：{direction}
發布渠道：{channel}
指定目標：{target_name}

回傳 JSON：{{"body":"完整繁體中文文案","image_prompt":"無文字、無 logo 的方形社群配圖英文 prompt"}}。
不得編造數據、名人、優惠、名額或現場盛況；未知資訊用〔待填〕。只回 JSON。"""
    result = _extract_json(_chat(PLAYBOOK, user, max_tokens=1200, temperature=0.85))
    if result.get("error") or not result.get("body") or not result.get("image_prompt"):
        raise RuntimeError("圖文生成結果不完整")
    return result


def generate_image(prompt: str) -> bytes:
    """使用 OpenAI 圖片端點產生一張方形社群配圖。"""
    body = json.dumps({
        "model": os.environ.get("ZAOSHEN_IMAGE_MODEL", "gpt-image-2"),
        "prompt": prompt,
        "size": "1024x1024",
        "quality": "low",
        "output_format": "png",
    }).encode("utf-8")
    response = requests.post(IMAGE_API, data=body, headers={
        "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY','')}",
        "Content-Type": "application/json",
    }, timeout=180)
    if not response.ok:
        raise RuntimeError(f"OpenAI 圖片 API {response.status_code}: {response.text[:300]}")
    data = response.json()
    return base64.b64decode(data["data"][0]["b64_json"])
