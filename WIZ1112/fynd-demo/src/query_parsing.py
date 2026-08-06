# -*- coding: utf-8 -*-
"""
쿼리 파싱 공용 모듈
- src/recommend.py(CLI)와 app.py(웹 API)가 동일한 카테고리/키워드 매핑과
  파싱 로직을 공유하도록 이 모듈에서 단일 정의를 제공한다.
"""

from typing import Optional, List, Dict, Set, Union
from collections import defaultdict
import numpy as np

# 카테고리는 단일 문자열이거나, 여러 대분류에 걸칠 수 있는 경우 Set으로 표현된다
CategoryValue = Union[str, Set[str]]


# -------------------------
# 카테고리 판정/페널티 설정 (조정 가능)
# -------------------------
CATEGORY_MIN_CONFIDENCE = 0.3  # 이 미만이면 DB category 대신 이름 기반 추론으로 폴백
CATEGORY_MISMATCH_PENALTY = 0.3  # 카테고리 불일치 시 정규화된 점수에서 뺄 고정 페널티


# -------------------------
# 카테고리 매핑 (정확 매칭용)
# -------------------------
CATEGORY_GROUPS = {
    "hoodie": ["후드티", "후드 티", "hoodie", "hoody", "후디", "hooded sweatshirt", "후드"],
    "hood_coat": ["후드코트", "후드 코트", "hooded coat", "hood coat"],
    "coat": ["코트", "coat", "trench", "트렌치"],
    "jacket": ["자켓", "jacket", "점퍼", "jumper"],
    "blazer": ["블레이저", "blazer"],
    "puffer": ["패딩", "puffer", "다운", "down", "padding", "퍼퍼", "푸퍼"],
    "sweatshirt": ["맨투맨", "스웨트셔츠", "sweatshirt", "mtm"],
    "knit": ["니트", "knit", "스웨터", "sweater", "풀오버", "pullover"],
    "cardigan": ["가디건", "cardigan", "카디건"],
    "shirt": ["셔츠", "shirt", "남방"],
    "blouse": ["블라우스", "blouse"],
    "tshirt": ["티셔츠", "t-shirt", "tee", "tshirt", "티"],
    "dress": ["원피스", "dress", "드레스"],
    "skirt": ["스커트", "skirt", "치마"],
    "pants": ["팬츠", "pants", "바지", "트라우저", "trousers", "슬랙스", "slacks"],
    "jeans": ["진", "jeans", "청바지", "데님팬츠", "denim pants", "데님"],
    "shorts": ["반바지", "shorts", "숏팬츠", "숏츠"],
}

# 역매핑 생성
KEYWORD_TO_CATEGORY = {}
for cat, keywords in CATEGORY_GROUPS.items():
    for kw in keywords:
        KEYWORD_TO_CATEGORY[kw.lower()] = cat


# -------------------------
# 계층적 카테고리 분류 체계 (대분류 → 중분류)
# - SigLIP2 2단계 분류(scripts/classify_categories_siglip2.py) 및 이후 카테고리
#   필터링의 기준. CATEGORY_GROUPS는 하위 호환을 위해 당분간 유지한다.
# - 라벨은 영어로 정의한다: 현재 사용자 쿼리가 영어 위주이고, SigLIP2
#   (google/siglip2-base-patch16-224)가 한국어 프롬프트에서는 신뢰도 낮은
#   오분류를 체계적으로 일으키는 것을 확인했기 때문. 한국어 지원은 추후 별도 확장.
# - 선글라스/시계는 데이터셋에 거의 없어 "other accessories"로 흡수한다.
# -------------------------
TAXONOMY = {
    "tops": ["t-shirts", "sweatshirts", "shirts/blouses", "hoodies", "sleeveless tops", "other tops"],
    "outerwear": ["zip-up hoodies", "jackets", "cardigans", "padded jackets", "coats"],
    "pants": ["denim", "sweatpants", "cotton pants", "slacks", "leggings", "other pants"],
    "dresses": ["mini dresses", "midi dresses", "maxi dresses"],
    "skirts": ["mini skirts", "midi skirts", "long skirts"],
    "shoes": ["sneakers", "dress shoes", "boots", "sandals/slippers", "other shoes"],
    "bags": ["backpacks", "tote bags", "shoulder bags", "eco bags", "wallets", "other bags"],
    "accessories": ["hats", "scarves", "jewelry", "socks", "belts", "other accessories"],
}

# 신 TAXONOMY 대분류 이름 자체("tops", "outerwear" 등)도 검색 키워드로 인식한다.
# 값이 이미 신 어휘이므로 parse_query의 OLD_TO_TAXONOMY_CATEGORY.get(x, x)
# 폴백에서 그대로 통과한다. (기존 구 어휘 키워드와 이름이 겹치는 "pants"는
# 어차피 같은 대분류로 귀결되므로 덮어써도 무해)
for _major in TAXONOMY:
    KEYWORD_TO_CATEGORY[_major] = _major


# -------------------------
# 구 CATEGORY_GROUPS 어휘 → 신 TAXONOMY 대분류 매핑
# - parse_query()가 반환하는 category(구 CATEGORY_GROUPS 17개 키)와 DB의
#   SigLIP2 category(신 TAXONOMY 8개 대분류)는 서로 다른 어휘 체계라
#   문자열 비교(==)가 사실상 항상 실패하던 문제를 해결하기 위한 매핑.
# - 명확한 경우는 단일 문자열, 여러 대분류에 걸칠 수 있는 경우(예: "hoodie"는
#   상의형 후드티=tops와 아우터형 후드집업=outerwear 둘 다 가능)는 Set으로 표현한다.
# -------------------------
OLD_TO_TAXONOMY_CATEGORY: Dict[str, CategoryValue] = {
    "hoodie": {"tops", "outerwear"},  # 후드티(tops) / 후드집업(outerwear) 둘 다 가능
    "hood_coat": "outerwear",
    "coat": "outerwear",
    "jacket": "outerwear",
    "blazer": "outerwear",
    "puffer": "outerwear",
    "sweatshirt": "tops",
    "knit": "tops",
    "cardigan": "outerwear",
    "shirt": "tops",
    "blouse": "tops",
    "tshirt": "tops",
    "dress": "dresses",
    "skirt": "skirts",
    "pants": "pants",
    "jeans": "pants",
    "shorts": "pants",
}


def _as_category_set(category: Optional[CategoryValue]) -> Set[str]:
    """단일 카테고리 문자열 또는 Set을 항상 Set[str]로 정규화 (빈 값은 빈 Set)"""
    if not category:
        return set()
    if isinstance(category, (set, frozenset)):
        return set(category)
    return {category}


def categories_overlap(a: Optional[CategoryValue], b: Optional[CategoryValue]) -> bool:
    """카테고리 두 개(단일 문자열 또는 Set)가 하나라도 겹치는지 확인"""
    return bool(_as_category_set(a) & _as_category_set(b))


# -------------------------
# 상의 오분류 보정 키워드
# - SigLIP2가 탱크탑/홀터탑/튜브탑류를 skirts/dresses로 오분류하는 패턴이 있어,
#   상품명에 이 키워드가 있으면 category를 tops로 보정한다.
#   (scripts/apply_top_keyword_override.py)
# -------------------------
TOP_OVERRIDE_KEYWORDS = [
    "top", "tee", "shirt", "blouse", "tank", "cami", "halter",
    "탱크탑", "홀터", "튜브탑", "캐미", "블라우스", "셔츠", "티셔츠",
]


# -------------------------
# 디테일/핏 키워드 (확장)
# -------------------------
DETAIL_KEYWORDS_EXPANDED = {
    # 소매 디테일
    "puff": ["퍼프", "퍼프소매", "puff sleeve", "puff", "볼륨소매"],
    "shirring": ["셔링", "shirring", "주름", "개더"],
    "bell_sleeve": ["벨슬리브", "bell sleeve", "나팔소매", "플레어소매"],
    "long_sleeve": ["긴소매", "long sleeve", "롱슬리브"],
    "short_sleeve": ["반소매", "short sleeve", "숏슬리브", "반팔"],
    "sleeveless": ["민소매", "sleeveless", "민소매탑", "슬리브리스"],

    # 어깨/넥 디테일
    "off_shoulder": ["오프숄더", "off shoulder", "off-shoulder", "숄더오프"],
    "one_shoulder": ["원숄더", "one shoulder", "one-shoulder", "한쪽어깨"],
    "cold_shoulder": ["콜드숄더", "cold shoulder", "어깨트임"],
    "halter": ["홀터", "halter", "홀터넥"],
    "square_neck": ["스퀘어넥", "square neck", "각진넥"],
    "v_neck": ["브이넥", "v-neck", "v neck", "vneck"],
    "round_neck": ["라운드넥", "round neck", "라운드"],
    "collar": ["카라", "collar", "셔츠카라"],
    "boat_neck": ["보트넥", "boat neck", "보트"],
    "turtleneck": ["터틀넥", "turtleneck", "폴라", "하이넥"],

    # 기장/실루엣
    "crop": ["크롭", "crop", "cropped", "짧은기장"],
    "midi": ["미디", "midi", "미디기장"],
    "maxi": ["맥시", "maxi", "롱기장"],
    "asymmetric": ["언발란스", "asymmetric", "비대칭", "unbalance", "언발"],
    "flare": ["플레어", "flare", "A라인", "에이라인"],
    "boots_cut": ["부츠컷", "boots cut", "부츠컷팬츠"],
    "aline": ["에이라인", "a-line", "aline", "A라인"],

    # 패턴
    "stripe": ["스트라이프", "stripe", "줄무늬", "단가라"],
    "check": ["체크", "check", "plaid", "격자", "타탄"],
    "floral": ["플로럴", "floral", "꽃무늬", "플라워"],
    "dot": ["도트", "dot", "물방울", "폴카도트", "polka"],
    "solid": ["솔리드", "solid", "무지", "단색"],
    "animal_print": ["애니멀프린트", "animal print", "호피", "레오파드", "지브라", "leopard"],
    "camouflage": ["카모플라주", "camouflage", "카무플라주", "밀리터리", "camo", "카모"],
    "argyle": ["아가일", "argyle", "다이아몬드패턴"],

    # 기타 디테일
    "ruffle": ["러플", "ruffle", "프릴", "frill"],
    "lace": ["레이스", "lace"],
    "bow": ["보우", "bow", "리본", "ribbon"],
    "cutout": ["컷아웃", "cutout", "cut-out", "트임"],
    "slit": ["슬릿", "slit", "트임"],
    "pleats": ["플리츠", "pleats", "주름", "플레어"],
    "wrap": ["랩", "wrap", "여밈"],
    "backless": ["백리스", "backless", "등트임", "오픈백"],
    "tie": ["타이", "tie", "스트링", "string"],
    "pintuck": ["핀턱", "pintuck", "핀턱주름", "원턱", "투턱"],
}

FIT_KEYWORDS_EXPANDED = {
    "oversized": ["오버사이즈", "오버핏", "oversized", "overfit", "루즈핏", "loose fit", "루즈", "박시", "boxy"],
    "slim": ["슬림", "슬림핏", "slim", "slim fit", "스키니", "skinny", "타이트", "tight"],
    "regular": ["레귤러", "레귤러핏", "regular", "regular fit", "기본핏", "노멀핏"],
    "relaxed": ["릴렉스", "릴렉스핏", "relaxed", "relaxed fit", "편한핏"],
    "fitted": ["피티드", "fitted", "바디핏", "몸에붙는", "스키니", "타이트", "슬림", "tight", "skinny", "slim"],
    "straight": ["스트레이트", "straight", "일자", "H라인"]
}

# 색상 매핑
COLOR_KEYWORDS = {
    "black": ["블랙", "black", "검정", "검은"],
    "white": ["화이트", "white", "흰색", "하얀"],
    "gray": ["그레이", "gray", "grey", "회색", "그레이"],
    "beige": ["베이지", "beige", "베이지색"],
    "brown": ["브라운", "brown", "갈색"],
    "navy": ["네이비", "navy", "남색", "곤색"],
    "blue": ["블루", "blue", "파란", "파랑"],
    "red": ["레드", "red", "빨강", "빨간"],
    "pink": ["핑크", "pink", "분홍"],
    "green": ["그린", "green", "초록", "녹색"],
    "yellow": ["옐로우", "yellow", "노랑", "노란"],
    "orange": ["오렌지", "orange", "주황"],
    "purple": ["퍼플", "purple", "보라"],
    "ivory": ["아이보리", "ivory", "상아색"],
    "cream": ["크림", "cream", "크림색"],
    "burgundy": ["버건디", "burgundy", "와인", "wine"],
    "charcoal": ["차콜", "charcoal", "진회색"],
    "khaki": ["카키", "khaki"],
    "camel": ["카멜", "camel", "낙타색"],
}


# -------------------------
# 쿼리 파싱
# -------------------------
def parse_query(query: str) -> Dict:
    """
    쿼리에서 카테고리, 핏, 디테일, 색상 추출.
    category는 신 TAXONOMY 어휘(단일 문자열 또는 Set[str])로 반환된다 —
    KEYWORD_TO_CATEGORY 매칭은 구 CATEGORY_GROUPS 어휘이므로
    OLD_TO_TAXONOMY_CATEGORY로 변환한 값을 담는다.
    """
    query_lower = query.lower()

    result = {
        "category": None,
        "fit": [],
        "detail": [],
        "color": [],
        "raw_query": query
    }

    # 카테고리 추출 (가장 긴 매칭 우선)
    matched_categories = []
    for keyword, category in KEYWORD_TO_CATEGORY.items():
        if keyword in query_lower:
            matched_categories.append((len(keyword), keyword, category))

    if matched_categories:
        # 가장 긴 키워드로 매칭된 카테고리 선택
        matched_categories.sort(reverse=True)
        matched_old_category = matched_categories[0][2]
        result["category"] = OLD_TO_TAXONOMY_CATEGORY.get(matched_old_category, matched_old_category)

    # 핏 추출
    for fit_name, keywords in FIT_KEYWORDS_EXPANDED.items():
        for kw in keywords:
            if kw.lower() in query_lower:
                result["fit"].append(fit_name)
                break

    # 디테일 추출
    for detail_name, keywords in DETAIL_KEYWORDS_EXPANDED.items():
        for kw in keywords:
            if kw.lower() in query_lower:
                result["detail"].append(detail_name)
                break

    # 색상 추출
    for color_name, keywords in COLOR_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in query_lower:
                result["color"].append(color_name)
                break

    return result


def extract_product_category(product_name: str) -> Optional[str]:
    """상품명에서 카테고리 추출"""
    name_lower = product_name.lower()

    matched = []
    for keyword, category in KEYWORD_TO_CATEGORY.items():
        if keyword in name_lower:
            matched.append((len(keyword), category))

    if matched:
        matched.sort(reverse=True)
        return matched[0][1]

    return None


def resolve_product_category(
    product: Dict, min_confidence: float = CATEGORY_MIN_CONFIDENCE
) -> Optional[CategoryValue]:
    """
    상품의 카테고리를 결정한다. 항상 신 TAXONOMY 어휘(단일 문자열 또는 Set[str])로 반환된다.
    - SigLIP2 분류 결과(product['category'] / product['category_confidence'])를 우선 사용
      (이미 TAXONOMY 어휘이므로 그대로 반환)
    - confidence가 min_confidence 미만이거나 category가 비어있으면 상품명 기반
      extract_product_category()로 폴백하되, 그 결과(구 CATEGORY_GROUPS 어휘)를
      OLD_TO_TAXONOMY_CATEGORY로 다시 TAXONOMY 어휘로 변환해서 반환한다.
    """
    category = product.get('category')
    confidence = product.get('category_confidence')

    if category and confidence is not None and confidence >= min_confidence:
        return category

    old_category = extract_product_category(product.get('name', ''))
    if old_category is None:
        return None
    return OLD_TO_TAXONOMY_CATEGORY.get(old_category, old_category)


# -------------------------
# 카테고리 불일치 페널티
# -------------------------
def normalize_similarity(sim):
    """코사인 유사도([-1, 1])를 [0, 1] 범위로 정규화"""
    return (sim + 1) / 2


def apply_category_penalty(
    scores: np.ndarray,
    products: List[Dict],
    target_category: Optional[CategoryValue],
    categories: Optional[List[Optional[CategoryValue]]] = None,
    min_confidence: float = CATEGORY_MIN_CONFIDENCE,
    penalty: float = CATEGORY_MISMATCH_PENALTY,
) -> np.ndarray:
    """
    코사인 유사도를 0~1로 정규화한 뒤, target_category와 겹치지 않는 상품에는
    penalty * category_confidence 만큼 빼고(음수면 0으로 clip) 반환한다.

    카테고리 판정이 불확실했던(category_confidence가 낮은) 상품일수록 페널티도
    약하게 적용된다 — SigLIP2 확신이 낮은 판정을 고정 페널티로 강하게 벌점 주지
    않기 위함. confidence가 없는 상품은 페널티 0(=벌점 없음)으로 취급한다.

    target_category와 카테고리는 단일 문자열 또는 Set일 수 있으며, 비교는 `==`가
    아닌 categories_overlap()(교집합 존재 여부)로 수행한다 — "hoodie"처럼
    {"tops", "outerwear"} 둘 다에 해당할 수 있는 카테고리를 다루기 위함.

    - categories: products와 같은 순서의 미리 계산된 카테고리 리스트가 있으면 재사용하고,
      없으면 resolve_product_category()로 그때그때 계산한다.
    - target_category가 없으면 정규화만 적용한다.
    """
    normalized = normalize_similarity(np.asarray(scores, dtype=float))

    if not target_category:
        return normalized

    if categories is None:
        categories = [resolve_product_category(p, min_confidence) for p in products]

    result = normalized.copy()
    for i, cat in enumerate(categories):
        if cat and not categories_overlap(cat, target_category):
            confidence = products[i].get('category_confidence') or 0.0
            scaled_penalty = penalty * confidence
            result[i] = max(0.0, result[i] - scaled_penalty)

    return result


# -------------------------
# 쿼리 확장
# -------------------------
def expand_query(query: str, parsed: Dict) -> str:
    """쿼리를 영어/한글 혼합으로 확장"""
    expanded_parts = [query]

    # 핏 확장
    for fit in parsed["fit"]:
        if fit in FIT_KEYWORDS_EXPANDED:
            expanded_parts.extend(FIT_KEYWORDS_EXPANDED[fit][:3])

    # 디테일 확장
    for detail in parsed["detail"]:
        if detail in DETAIL_KEYWORDS_EXPANDED:
            expanded_parts.extend(DETAIL_KEYWORDS_EXPANDED[detail][:3])

    # 색상 확장
    for color in parsed["color"]:
        if color in COLOR_KEYWORDS:
            expanded_parts.extend(COLOR_KEYWORDS[color][:2])

    return " ".join(expanded_parts)


# -------------------------
# 브랜드 다양성 적용
# -------------------------
def apply_brand_diversity(
    results: List[Dict],
    scores: np.ndarray,
    indices: Optional[np.ndarray],
    products: List[Dict],
    top_k: int = 5,
    max_per_brand: int = 2,
    excluded_ids: Optional[Set] = None
) -> List[int]:
    """
    브랜드당 최대 max_per_brand개로 제한하여 다양성 보장

    - results: (미사용, 호출부 호환을 위해 유지)
    - indices: None이면 scores의 인덱스를 그대로 상품 인덱스로 사용
    - excluded_ids: 이미 노출된 상품 id를 제외하고 싶을 때 사용 (예: 위시리스트 페이지네이션)
    """
    if excluded_ids is None:
        excluded_ids = set()

    brand_count = defaultdict(int)
    selected_indices = []

    # 점수 높은 순으로 정렬된 인덱스
    sorted_idx = np.argsort(scores)[::-1]

    for idx in sorted_idx:
        if len(selected_indices) >= top_k:
            break

        original_idx = indices[idx] if indices is not None else idx
        product = products[original_idx]
        product_id = product.get('id', original_idx)
        if product_id in excluded_ids:
            continue

        brand = product.get('brand_name', 'unknown')

        if brand_count[brand] < max_per_brand:
            selected_indices.append(idx)
            brand_count[brand] += 1

    return selected_indices
