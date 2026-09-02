#!/usr/bin/env python3



"""微信公众号推文自动生成 - 每天7:00执行"""



import json, os, re, ssl, time, urllib.request, datetime, random







# 配置



WECHAT_APP_ID = os.environ.get("WECHAT_APP_ID", "wxf2eebe1e44f1e24e")



WECHAT_APP_SECRET = os.environ.get("WECHAT_APP_SECRET", "a44beb6af4752cf2d47a983a7d4bb1af")



AGNES_API_KEY = os.environ.get("AGNES_API_KEY", "")



AGNES_API_URL = "https://apihub.agnes-ai.com/v1/chat/completions"



AGNES_MODEL = os.environ.get("HERMES_MODEL", "agnes-2.0-flash")



ILINK_BASE = os.environ.get("ILINK_BASE", "https://ilinkai.weixin.qq.com")



ILINK_TOKEN = os.environ.get("ILINK_TOKEN", "")



ILINK_APP_ID = "bot"



ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0



NOTIFY_OPENID = os.environ.get("NOTIFY_OPENID", "").split("@")[0]



WECHAT_BACKUP_URL = "https://mp.weixin.qq.com/"

UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")







SOLAR_TERMS_2026 = {



    (1,5):"小寒",(1,20):"大寒",(2,3):"立春",(2,18):"雨水",



    (3,5):"惊蛰",(3,20):"春分",(4,4):"清明",(4,20):"谷雨",



    (5,5):"立夏",(5,21):"小满",(6,5):"芒种",(6,21):"夏至",



    (7,7):"小暑",(7,22):"大暑",(8,7):"立秋",(8,23):"处暑",



    (9,7):"白露",(9,23):"秋分",(10,8):"寒露",(10,23):"霜降",



    (11,7):"立冬",(11,22):"小雪",(12,7):"大雪",(12,21):"冬至",



}



TOPIC_POOLS = {



    1:["新年新起点","冬日暖阳","健康养生","目标规划"],



    2:["春日希望","万物复苏","新年计划","健康饮食"],



    3:["春暖花开","运动健身","学习成长","感恩生活"],



    4:["清明踏青","健康生活","阅读成长","家庭温暖"],



    5:["劳动光荣","青春活力","母亲节感恩","健康生活"],



    6:["端午文化","夏日清凉","父亲节感恩","健康生活"],



    7:["夏日养生","防暑降温","旅行见闻","阅读成长"],



    8:["立秋养生","收获季节","健康生活","感恩生活"],



    9:["中秋团圆","教师节感恩","秋日养生","学习成长"],



    10:["国庆爱国","重阳敬老","秋日美景","健康生活"],



    11:["立冬养生","健康生活","温暖陪伴","积极心态"],



    12:["冬至团圆","年末总结","新年展望","健康生活"],



}



GUA_TOPICS = ["乾卦·自强不息","坤卦·厚德载物","屯卦·万事开头难","蒙卦·启蒙教育","需卦·等待时机","讼卦·化解矛盾","师卦·团队合作","比卦·亲密无间","小畜卦·积少成多","履卦·脚踏实地","泰卦·否极泰来","同人卦·志同道合","大有卦·丰收在望","谦卦·谦虚受益","豫卦·顺势而为","随卦·随机应变","蛊卦·改革创新","临卦·亲临现场","观卦·观察入微","贲卦·文饰美化","剥卦·剥茧抽丝","复卦·回归初心","无妄卦·真诚待人","大畜卦·厚积薄发","颐卦·颐养天年","坎卦·迎难而上","离卦·光明磊落","咸卦·感应相通","恒卦·持之以恒","遁卦·适时退让","大壮卦·壮大力量","晋卦·步步高升","家人卦·家和万事兴","睽卦·求同存异","蹇卦·知难而进","解卦·化险为夷","损卦·损己利人","益卦·损上益下","夬卦·决断时刻","萃卦·聚精会神","升卦·蒸蒸日上","困卦·困境中的智慧","革卦·革故鼎新","震卦·雷厉风行","艮卦·适可而止","渐卦·循序渐进","丰卦·丰衣足食","巽卦·温文尔雅","兑卦·喜悦分享","节卦·节制有度","中孚卦·诚信为本","未济卦·未来可期"]



ZODIAC = ["白羊座","金牛座","双子座","巨蟹座","狮子座","处女座","天秤座","天蝎座","射手座","摩羯座","水瓶座","双鱼座"]







def log(tag, msg):



    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")



    line = f"[{ts}] [{tag}] {msg}"



    print(line, flush=True)



    try:



        with open("/opt/data/wechat_auto.log","a",encoding="utf-8") as f: f.write(line+"\n")



    except: pass







def _uin(): return str(random.randint(10000000,99999999))







def ilink_h(body, token=""):



    h = {"Content-Type":"application/json","AuthorizationType":"ilink_bot_token",



         "Content-Length":str(len(body.encode())),"X-WECHAT-UIN":_uin(),



         "iLink-App-Id":ILINK_APP_ID,"iLink-App-ClientVersion":str(ILINK_APP_CLIENT_VERSION)}



    if token: h["Authorization"] = f"Bearer {token}"



    return h







def ilink_post(ep, payload, token=""):



    body = json.dumps(payload, ensure_ascii=False, separators=(",",":"))



    url = f"{ILINK_BASE.rstrip('/')}/{ep}"



    ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE



    req = urllib.request.Request(url, data=body.encode(), headers=ilink_h(body,token), method="POST")



    return json.loads(urllib.request.urlopen(req, timeout=30, context=ctx).read())







def call_llm(sys_p, usr_m, max_t=4096):



    if not AGNES_API_KEY: return None



    payload = {"model":AGNES_MODEL,"messages":[{"role":"system","content":sys_p},{"role":"user","content":usr_m}],"max_tokens":max_t}



    ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE



    try:



        req = urllib.request.Request(AGNES_API_URL, data=json.dumps(payload).encode(),



            headers={"Content-Type":"application/json","Authorization":f"Bearer {AGNES_API_KEY}"})



        with urllib.request.urlopen(req, context=ctx, timeout=120) as r:



            d = json.loads(r.read().decode())



            return d["choices"][0]["message"]["content"]



    except Exception as e: log("ERROR",f"LLM:{e}"); return None







def get_term(date):



    for d in range(-3,4):



        c = date+datetime.timedelta(days=d)



        k=(c.month,c.day)



        if k in SOLAR_TERMS_2026: return SOLAR_TERMS_2026[k],d



    return None,None







def get_zodiac(date):



    m,d=date.month,date.day



    ds=[20,19,21,20,21,22,23,23,23,24,22,22]



    return ZODIAC[m-1] if d<ds[m-1] else ZODIAC[m%12]







def generate_topic():



    today=datetime.date.today()



    wd=["周一","周二","周三","周四","周五","周六","周日"][today.weekday()]



    st,td=get_term(today)



    zc=get_zodiac(today)



    bt="养生修炼"



    ug=random.random()<0.3



    gt=random.choice(GUA_TOPICS) if ug else None



    ds=today.strftime("%Y年%m月%d日")



    inp=f"今天是 {ds} {wd}"



    if st: inp+=f"，{st}{'刚过' if td<0 else '将至' if td>0 else '当天'}"



    inp+=f"\n星座：{zc}\n主题：{bt}"



    if gt: inp+=f"\n卦象：{gt}"



    sp="你是微信公众号内容策划专家。根据日期、节气、星座、卦象生成养生修炼选题。要求：积极向上、结合节气时令、面向普通人群养生修炼（非驾驶员/驾培）、实用小窍门。直接输出标题，不超过20字。"



    t=call_llm(sp,f"请生成1个微信公众号推文选题：\n\n{inp}\n\n直接输出标题：",100)



    t=t.strip().strip('"').strip("'") if t else f"{st or ds}·{bt}"



    log("TOPIC",t)



    return {"topic":t,"date":ds,"weekday":wd,"solar_term":st,"zodiac":zc,"base_topic":bt,"gua":gt}







def generate_article(ti):



    sp="""你是专业的微信公众号内容创作者。要求：



1.积极向上、健康合规 2.语言温暖亲切 3.结构清晰



4.正文不少于1000字 5.适当使用emoji



6.图片占位符格式：【图片：描述】，至少3个



7.结尾有互动引导 8.面向普通人群养生修炼，不限定职业或场景



输出格式：第一行标题（不含#，≤25字），空一行，正文"""



    st = ti.get('solar_term', '')



    zc = ti.get('zodiac', '')



    gu = ti.get('gua', '')



    um = "选题：" + ti['topic'] + "\n日期：" + ti['date'] + " " + ti['weekday']



    if st: um += "\n节气：" + st



    if zc: um += "\n星座：" + zc



    if gu: um += "\n卦象：" + gu



    um += "\n\n请直接输出，第一行标题，空一行正文："



    log("ARTICLE","Generating: "+ti['topic'])



    art=call_llm(sp,um,4096)



    if not art: return None



    lines=art.strip().split("\n")



    title=lines[0].strip().lstrip("#").strip()



    body="\n".join(lines[1:]).strip()



    log("ARTICLE","Title:"+title+", Body:"+str(len(body))+"chars")



    return {"title":title,"body":body,"topic_info":ti}







def get_wx_token():



    cache_file = "/tmp/.wx_token_cache"



    try:



        with open(cache_file, "r") as f:



            cached = json.loads(f.read())



        if time.time() - cached.get("ts", 0) < 7000:



            return cached["token"]



    except: pass



    # getStableAccessToken 需要用 POST



    token_url = "https://api.weixin.qq.com/cgi-bin/stable_token"



    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE



    try:



        req_body = json.dumps({"grant_type": "client_credential", "appid": WECHAT_APP_ID, "secret": WECHAT_APP_SECRET}).encode()

        req = urllib.request.Request(token_url, data=req_body, method="POST")



        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:



            d = json.loads(r.read().decode())



            if "access_token" in d:



                with open(cache_file, "w") as f:



                    json.dump({"token": d["access_token"], "ts": time.time()}, f)



                return d["access_token"]



        log("ERROR", "Token: " + str(d)); return None



    except Exception as e: log("ERROR", "TokenErr: " + str(e)); return None







def search_unsplash_image(query, count=1):
    """Search Unsplash for images matching the query"""
    if not UNSPLASH_ACCESS_KEY:
        return []
    try:
        import urllib.parse
        safe_query = query[:50]
        url = f"https://api.unsplash.com/search/photos?query={urllib.parse.quote(safe_query)}&per_page={count}&orientation=landscape"
        req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"})
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            data = json.loads(r.read().decode())
            results = []
            for img in data.get("results", []):
                results.append({
                    "url": img["urls"]["regular"],
                    "thumb": img["urls"]["thumb"],
                    "description": img.get("description") or img.get("alt_description", ""),
                    "photographer": img["user"]["name"],
                    "download_url": img["links"]["download_location"]
                })
            return results
    except Exception as e:
        log("UNSPLASH", f"Search error: {e}")
        return []

def _track_unsplash_download(download_url):
    """Track download per Unsplash API guidelines"""
    if not UNSPLASH_ACCESS_KEY:
        return
    try:
        req = urllib.request.Request(download_url, 
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"})
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        urllib.request.urlopen(req, timeout=10, context=ctx)
    except:
        pass


def to_wx_html(body, topic=""):
    """Convert body to WeChat HTML, replacing image placeholders with Unsplash images"""
    placeholders = re.findall(r'【图片：([^】]+)】', body)
    
    h = body
    for desc in placeholders:
        # Unsplash returns 410 on non-ASCII/long queries; map Chinese to English keywords
        _en_map = {
            "太": "taichi", "瑜": "yoga", "茶": "tea", "水": "water", "晨": "dawn",
            "阳": "sunshine", "山": "mountain", "湖": "lake", "公": "park", "夕": "sunset",
            "卧": "bedroom", "书": "book", "伸": "stretching", "散": "walking", "笑": "smiling",
            "朋": "friends", "健": "wellness", "凉": "refresh", "静": "meditation",
            "养": "wellness", "夏": "summer", "冬": "winter", "春": "spring", "秋": "autumn",
            "花": "flowers", "草": "grass", "树": "forest", "鸟": "birds", "鱼": "fish",
            "绿": "nature", "蓝": "sky", "红": "sunset",
        }
        _kw = "nature"
        for _cn, _en in _en_map.items():
            if _cn in desc:
                _kw = _en
                break
        images = search_unsplash_image(_kw)
        if images:
            img = images[0]
            _track_unsplash_download(img["download_url"])
            img_html = f'<p style="text-align:center;"><img src="{img["url"]}" alt="{desc}" style="max-width:100%;border-radius:8px;"/></p><p style="text-align:center;color:#999;font-size:12px;">📷 {desc} | Photo by {img["photographer"]} on Unsplash</p>'
            h = h.replace(f'【图片：{desc}】', img_html)
            log("UNSPLASH", f"Image found for: {desc}")
        else:
            h = h.replace(f'【图片：{desc}】', f'<p style="text-align:center;color:#999;font-size:13px;">📷 {desc}</p>')
            log("UNSPLASH", f"No image for: {desc}")
    
    h = h.replace("\n\n", "</p><p>").replace("\n", "<br>")
    if not h.startswith("<"): h = f"<p>{h}</p>"
    return h.replace("<p></p>", "")


def upload_thumb_image():
    """上传封面图片到微信素材库，返回 media_id"""
    at = get_wx_token()
    if not at: return None
    
    import os
    cover_path = "/opt/data/assets/cover.jpg"
    if not os.path.exists(cover_path):
        # 尝试生成封面
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new('RGB', (900, 383), color=(255, 245, 235))
            draw = ImageDraw.Draw(img)
            # 简单渐变背景
            for y in range(383):
                r = int(255 - y * 0.1)
                g = int(245 - y * 0.15)
                b = int(235 - y * 0.2)
                draw.line([(0, y), (900, y)], fill=(max(r,180), max(g,160), max(b,140)))
            os.makedirs("/opt/data/assets", exist_ok=True)
            img.save(cover_path, "JPEG", quality=85)
            log("UPLOAD", "Generated cover image")
        except Exception as e:
            log("ERROR", f"Cover generation failed: {e}")
            return None
    
    with open(cover_path, "rb") as f:
        img_data = f.read()
    
    url = "https://api.weixin.qq.com/cgi-bin/material/add_material" + "?access_token=" + at + "&type=image"
    
    try:
        files = {"media": ("cover.jpg", img_data, "image/jpeg")}
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        import requests
        resp = requests.post(url, files=files, timeout=30)
        result = resp.json()
        
        if "media_id" in result:
            log("UPLOAD", f"Thumb uploaded: {result['media_id']}")
            return result["media_id"]
        else:
            log("ERROR", f"Upload failed: {result}")
            return None
    except Exception as e:
        log("ERROR", f"Upload error: {e}")
        return None

def create_draft(article):



    at=get_wx_token()



    if not at: return None



    ti=article["topic_info"]



    sm=f"{ti['date']} {ti.get('solar_term','')} · {ti['base_topic']}"[:120]



    thumb_id = upload_thumb_image()



    if not thumb_id: log("ERROR", "No thumb image"); return None



    wx_html = to_wx_html(article["body"], ti.get("topic", ""))



    url = "https://api.weixin.qq.com/cgi-bin/draft/add?" + "access_token=" + at



    payload={"articles": [{"title": article["title"], "digest": sm, "thumb_media_id": thumb_id, "show_cover_pic": 0, "need_open_comment": 0, "only_fans_can_comment": 0, "content": wx_html}]}



    ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE



    try:



        req=urllib.request.Request(url,data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),headers={"Content-Type":"application/json"})



        with urllib.request.urlopen(req,context=ctx,timeout=30) as r:



            d=json.loads(r.read().decode())



            if "media_id" in d: log("WECHAT",f"Draft OK: {d['media_id']}"); return d["media_id"]



            log("ERROR",f"Draft:{d}"); return None



    except Exception as e: log("ERROR",f"DraftErr:{e}"); return None







def main():



    log("MAIN","="*50); log("MAIN","WeChat Article Auto-Gen Start"); log("MAIN","="*50)



    log("MAIN","Step 1: Topic"); ti=generate_topic()



    log("MAIN","Step 2: Article"); article=generate_article(ti)



    if not article: log("ERROR","Article failed"); return False



    try:



        d2=datetime.date.today().strftime("%Y%m%d")



        os.makedirs("/opt/data/articles",exist_ok=True)



        with open(f"/opt/data/articles/{d2}.md","w",encoding="utf-8") as f:



            f.write(f"# {article['title']}\n\n日期:{ti['date']}\n选题:{ti['topic']}\n---\n\n{article['body']}")



        log("MAIN",f"Saved: /opt/data/articles/{d2}.md")



    except Exception as e: log("WARN",f"Save:{e}")



    log("MAIN","Step 3: Draft"); mid=create_draft(article)






    try:



        with open("/opt/data/articles/last_run.json","w",encoding="utf-8") as f:



            json.dump({"time":datetime.datetime.now().isoformat(),"topic":ti["topic"],"title":article["title"],"media_id":mid,"status":"success" if mid else "draft_failed"},f,ensure_ascii=False,indent=2)



    except: pass



    log("MAIN","Done!"); return True







if __name__=="__main__": main()



