# 상위군 매핑(하위 subCategory -> level1)
SUBCAT_TO_L1 = {
    # 의류
    "topwear": "tops", "bottomwear": "bottoms", "dress": "dresses", "dresses": "dresses",
    "innerwear": "innerwear", "ethnic wear": "tops", "jackets": "outerwear", "sweatshirts": "tops",
    "shirts": "tops", "tshirts": "tops", "tops": "tops", "tunics": "tops", "kurtas": "tops",
    "dupattas": "accessories", "coats": "outerwear", "saree": "dresses", "skirts": "bottoms",
    # 신발
    "shoes": "shoes", "casual shoes": "shoes", "sports shoes": "shoes", "formal shoes": "shoes",
    "heels": "shoes", "sandals": "shoes", "flip flops": "shoes",
    # 가방/지갑
    "bags": "bags", "handbags": "bags", "clutches": "bags", "backpacks": "bags",
    "luggage": "bags",
    # 액세서리
    "watches": "accessories", "belts": "accessories",
    "eyewear": "accessories", "socks": "accessories", "headwear": "accessories",
    "jewellery": "accessories", "scarves": "accessories", "stoles": "accessories"
}

# masterCategory -> level1 (fallback)
MASTER_TO_L1 = {
    "apparel": "tops",            # 기본값(세부는 subCategory로 보정됨)
    "footwear": "shoes",
    "accessories": "accessories",
    "bags": "bags",
    "personal care": "personal care",
    "sporting goods": "accessories",
    "home": "accessories",
    "beauty": "personal care",
    "free items": "accessories",
}


# 색상 동의어 정규화
COLOR_SYNONYMS = {
    "navy blue": "navy",
    "off white": "white",
    "cream": "beige",
    "skin": "beige",
    "charcoal": "gray",
    "coffee brown": "brown",
    "steel": "gray",
    "tan": "brown",
}

# 텍스트 키워드 기반(보강용)
MATERIALS = {
    "cotton": ["cotton","면"], "wool": ["wool","울"], "leather": ["leather","가죽"],
    "denim": ["denim","데님","청"], "linen": ["linen","린넨"],
    "nylon": ["nylon","나일론"], "polyester": ["polyester","폴리","폴리에스터"],
    "rayon": ["rayon","레이온"], "silk": ["silk","실크"], "acrylic": ["acrylic","아크릴"],
    "spandex": ["spandex","스판","엘라스틴"], "cashmere": ["cashmere","캐시미어"], "suede": ["suede","스웨이드"],
}
FITS = {
    "oversized": ["oversize","oversized","loose","relaxed","오버핏","박시","루즈","릴랙스드"],
    "regular": ["regular","레귤러","노멀"],
    "slim": ["slim","슬림"],
    "tight": ["tight","타이트","스키니"],
}
DETAILS = {
    "collar": ["collar","카라"], "ruffle": ["ruffle","frill","프릴","러플"], "slit": ["slit","슬릿"],
    "shirring": ["shirring","셔링"], "pleats": ["pleat","pleats","플리츠","주름"],
    "buttons": ["button","buttons","버튼"], "zipper": ["zip","zipper","지퍼"], "pockets": ["pocket","포켓"],
    "lace": ["lace","레이스"], "embroidery": ["embroidery","자수"], "hood": ["hood","후드"],
    "v-neck": ["v-neck","브이넥"], "crew-neck": ["crew","crew-neck","라운드넥"], "cropped": ["crop","cropped","크롭"],
    "long-sleeve": ["long sleeve","긴팔"], "short-sleeve": ["short sleeve","반팔"],
}

MATERIALS.update({
  "viscose": ["viscose","비스코스"], "modal": ["modal","모달"], "lycra": ["lycra","라이크라"],
  "chiffon": ["chiffon","쉬폰"], "georgette": ["georgette","조젯"], "crepe": ["crepe","크레이프","크레프"],
  "satin": ["satin","새틴"], "velvet": ["velvet","벨벳"], "fleece": ["fleece","플리스"],
  "mesh": ["mesh","메쉬"], "denim": ["denim","데님","청"], "pu": ["pu","합성가죽","폴리우레탄"]
})
FITS.update({
  "regular": ["regular","classic fit","straight fit","노멀","스트레이트"],
  "slim": ["slim","lean","슬림핏"],
  "tapered": ["tapered","테이퍼드"], "bootcut": ["bootcut","부츠컷"]
})
DETAILS.update({
  "printed": ["print","printed","프린트","프린티드","패턴"], "striped": ["stripe","striped","스트라이프"],
  "checked": ["check","checked","체크"], "embroidered": ["embroidered","자수"],
  "mandarin-collar": ["mandarin","차이나카라","차이나 칼라"],
  "polo-collar": ["polo","폴로카라"],
  "high-neck": ["turtle","turtleneck","high neck","터틀넥","하이넥"],
  "sleeveless": ["sleeveless","민소매"], "half-sleeve": ["half sleeve","반팔"], "long-sleeve": ["long sleeve","긴팔"],
})
