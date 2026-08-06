# -*- coding: utf-8 -*-
"""
의류 추천 시스템 — 5개 비교 조건 통합 인터페이스
- Text: google/embeddinggemma-300m (Gemma)
- Image/CLIP text: patrickjohncyh/fashion-clip (FashionCLIP)

서빙 조건 (2026-07 평가 실험으로 확정):
  A. text_text      : cos(Gemma(query_text), Gemma(product_name))
  B. image_image    : cos(CLIP_img(query_image), CLIP_img(product_photo))
  C. hybrid_legacy  : A항 + B항 가중합 (기존 TextImageRecommender 로직 보존 베이스라인)
  F. cross_t2i_only : cos(CLIP_text(query_text), CLIP_img(product_photo)) 단일 항
                      — 묘사형 텍스트 쿼리 평가에서 최고 성능 (텍스트-only 기본 경로)
  E. full_fusion    : A + B + 교차항 2개(쿼리텍스트→사진, 쿼리이미지→상품명) 4항 전부를
                      각각 페널티 적용 후 순위화 → RRF(k=60) 결합
                      — 텍스트+이미지 입력 시 기본 경로 (최종 채택 모델)

실험 전용 조건(D cross_only, G rrf3, H 가중 RRF 그리드)은 서빙 경로에서 제거됨 —
재현은 scripts/evaluate_all_modes.py 참고.

카테고리 페널티는 모든 조건에서 동일하게 src.query_parsing.apply_category_penalty
(confidence 스케일링 덧셈식) 하나만 사용한다. 조건별 별도 카테고리 로직 없음.
(구 FilteredRecommender의 하드필터는 이 공용 페널티로 대체되어 제거됨)
"""

import os
import argparse
from typing import Optional, List, Dict, Set
import numpy as np
from PIL import Image
import torch
import sqlite3
import pickle
from sentence_transformers import SentenceTransformer
from transformers import CLIPProcessor, CLIPModel

from src.query_parsing import (
    parse_query,
    expand_query,
    apply_brand_diversity,
    apply_category_penalty,
)


# -------------------------
# 설정
# -------------------------
DB_PATH = "fashion_products.db"
IMAGES_ROOT = "images"

EMBEDDING_DIR = "embeddings"
EMBEDDING_PATHS = {
    "model1": os.path.join(EMBEDDING_DIR, "model1_gemma.pkl"),            # Gemma(product_name)
    "model3": os.path.join(EMBEDDING_DIR, "model3_fashionclip.pkl"),      # CLIP_img(product_photo)
    "clip_text_names": os.path.join(EMBEDDING_DIR, "clip_text_names.pkl"),  # CLIP_text(product_name)
}

MODES = ["text_text", "image_image", "hybrid_legacy", "cross_t2i_only", "full_fusion"]
MODE_ALIASES = {"a": "text_text", "b": "image_image", "c": "hybrid_legacy",
                "f": "cross_t2i_only", "e": "full_fusion"}
RRF_K = 60

CLIP_MAX_LENGTH = 77  # CLIP 텍스트 인코더 최대 토큰 수

# --- 유저 피드백 반영 파라미터 (조정 가능) ---
# refine 임베딩 스티어링: q_new = normalize(q_base + α·Σ CLIP_text(정제문구))
REFINE_ALPHA = 0.6
# X(싫어요) 소프트 페널티: 제외 상품과 CLIP 이미지 유사도가 임계값 이상인 상품의
# 최종 점수를 감쇠 — factor = 1 − strength × (sim − thr)/(1 − thr)
SOFT_PENALTY_SIM_THRESHOLD = 0.8
SOFT_PENALTY_STRENGTH = 0.5


def ensure_embedding_dir():
    os.makedirs(EMBEDDING_DIR, exist_ok=True)


# -------------------------
# 데이터베이스
# -------------------------
class FashionDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def get_all_products(self, only_with_image: bool = True) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                p.id, p.product_code, p.name, p.original_price, p.sale_price,
                p.image_url, p.product_url, p.category, p.category_confidence,
                b.name as brand_name,
                i.local_path as local_image_path
            FROM products p
            JOIN brands b ON p.brand_id = b.id
            LEFT JOIN images i ON p.id = i.product_id
        ''')

        products = []
        for row in cursor.fetchall():
            product = dict(row)
            if only_with_image:
                local_path = product.get('local_image_path')
                if not local_path or not os.path.exists(local_path):
                    continue
            products.append(product)

        conn.close()
        return products


def load_products_by_ids(db: FashionDB, product_ids: List[int], only_with_image: bool = True) -> List[Dict]:
    """
    pkl에 저장된 product_ids 순서 그대로 DB에서 최신 상품 정보를 조회한다.
    임베딩 행 순서와 상품 순서가 어긋나면 안 되므로, id가 DB에 없으면 에러를 낸다.
    """
    products_by_id = {p['id']: p for p in db.get_all_products(only_with_image=only_with_image)}

    missing = [pid for pid in product_ids if pid not in products_by_id]
    if missing:
        raise ValueError(
            f"pkl의 product_ids 중 {len(missing)}개가 DB에 없습니다 (예: {missing[:5]}). "
            "임베딩과 상품 순서가 어긋나므로 임베딩을 재생성해야 합니다."
        )

    return [products_by_id[pid] for pid in product_ids]


# -------------------------
# 통일된 결과 출력
# -------------------------
def print_results(results: List[Dict], mode_name: str, query_info: str = ""):
    """모든 조건에서 동일한 형식으로 결과 출력"""
    print("\n" + "=" * 80)
    print(f"📌 {mode_name}")
    if query_info:
        print(f"   {query_info}")
    print("=" * 80)

    for item in results:
        rank = item.get('rank', '?')
        name = item.get('name', 'N/A')
        brand = item.get('brand', 'N/A')

        score_parts = [f"최종: {item['final_score']:.4f}"] if 'final_score' in item else []
        for key, label in [('gemma_text', 'A:Gemma텍스트'), ('clip_image', 'B:CLIP이미지'),
                           ('cross_t2i', 'F:쿼리텍스트→사진'), ('cross_i2t', '쿼리이미지→상품명')]:
            if key in item.get('term_scores', {}):
                score_parts.append(f"{label}: {item['term_scores'][key]:.4f}")
        score_str = " | ".join(score_parts) if score_parts else "N/A"

        price = item.get('price', 0)

        print(f"\n[{rank}위] {name}")
        print(f"     브랜드: {brand}")
        print(f"     점수: {score_str}")
        print(f"     가격: {price:,}원")
        print(f"     이미지: {item.get('image_path', '')}")
        if item.get('product_url'):
            print(f"     URL: {item['product_url']}")

    print("\n" + "-" * 80)


# -------------------------
# 통합 추천기 (5개 조건)
# -------------------------
class UnifiedRecommender:
    """
    5개 비교 조건을 하나의 인터페이스로 제공한다.
    recommend(mode, query_text=..., query_image=...) 형태로 호출.
    모델(Gemma/FashionCLIP)은 실제 필요한 조건에서만 lazy 로딩된다.
    """

    def __init__(self, db: FashionDB = None):
        self.db = db or FashionDB()

        if torch.cuda.is_available():
            self.device = "cuda"
        elif torch.backends.mps.is_available():
            self.device = "mps"
        else:
            self.device = "cpu"

        self._gemma = None
        self._clip_model = None
        self._clip_processor = None

        self.products: List[Dict] = []
        self.gemma_name_embeddings = None   # Gemma(product_name)      (5881, 768)
        self.clip_image_embeddings = None   # CLIP_img(product_photo)  (5881, 512)
        self.clip_name_embeddings = None    # CLIP_text(product_name)  (5881, 512)
        self.is_loaded = False

    # --- lazy 모델 로딩 ---
    @property
    def gemma(self) -> SentenceTransformer:
        if self._gemma is None:
            print("📦 Gemma 로딩 중...")
            self._gemma = SentenceTransformer("google/embeddinggemma-300m")
        return self._gemma

    def _ensure_clip(self):
        if self._clip_model is None:
            print(f"📦 FashionCLIP 로딩 중... (device={self.device})")
            self._clip_model = CLIPModel.from_pretrained("patrickjohncyh/fashion-clip").to(self.device)
            self._clip_model.eval()
            self._clip_processor = CLIPProcessor.from_pretrained("patrickjohncyh/fashion-clip")

    # --- 임베딩 로딩 ---
    def load_embeddings(self):
        """3개 pkl(Gemma 상품명 / CLIP 사진 / CLIP 상품명)을 로드하고 정합성 검증"""
        required = {
            "model1": "scripts/rebuild_embeddings.py",
            "model3": "scripts/rebuild_embeddings.py",
            "clip_text_names": "scripts/build_clip_text_embeddings.py",
        }
        for key, builder in required.items():
            if not os.path.exists(EMBEDDING_PATHS[key]):
                raise FileNotFoundError(
                    f"임베딩 없음: {EMBEDDING_PATHS[key]} — 먼저 {builder}를 실행하세요."
                )

        with open(EMBEDDING_PATHS["model1"], 'rb') as f:
            d1 = pickle.load(f)
        with open(EMBEDDING_PATHS["model3"], 'rb') as f:
            d3 = pickle.load(f)
        with open(EMBEDDING_PATHS["clip_text_names"], 'rb') as f:
            dn = pickle.load(f)

        if not (d1['product_ids'] == d3['product_ids'] == dn['product_ids']):
            raise ValueError(
                "pkl 간 product_ids 순서가 다릅니다. "
                "scripts/rebuild_embeddings.py와 scripts/build_clip_text_embeddings.py를 다시 실행하세요."
            )

        self.gemma_name_embeddings = d1['embeddings']
        self.clip_image_embeddings = d3['image_embeddings']
        self.clip_name_embeddings = dn['text_name_embeddings']
        self.products = load_products_by_ids(self.db, d1['product_ids'], only_with_image=True)
        self.is_loaded = True
        print(f"   📂 임베딩 로드 완료: 상품 {len(self.products)}개 | "
              f"Gemma{self.gemma_name_embeddings.shape} CLIP사진{self.clip_image_embeddings.shape} "
              f"CLIP상품명{self.clip_name_embeddings.shape}")
        return self

    def ensure_loaded(self):
        if not self.is_loaded:
            self.load_embeddings()

    # --- 쿼리 인코더 ---
    def encode_query_text_gemma(self, query_text: str, parsed: Dict) -> np.ndarray:
        # A/C(레거시)는 기존과 동일하게 한/영 확장 쿼리를 사용한다
        expanded = expand_query(query_text, parsed)
        return self.gemma.encode(expanded, normalize_embeddings=True)

    def encode_query_text_clip(self, query_text: str) -> np.ndarray:
        # FashionCLIP은 영어 인코더이므로 확장 없이 원본 쿼리 사용
        self._ensure_clip()
        inputs = self._clip_processor(
            text=query_text, return_tensors="pt",
            padding=True, truncation=True, max_length=CLIP_MAX_LENGTH,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            features = self._clip_model.get_text_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy().flatten()

    def encode_query_image_clip(self, image_path: str) -> np.ndarray:
        self._ensure_clip()
        image = Image.open(image_path).convert("RGB")
        inputs = self._clip_processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            features = self._clip_model.get_image_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy().flatten()

    # --- 유사도 항 계산 ---
    def compute_similarity(self, mode: str, query_text: Optional[str] = None,
                           query_image: Optional[str] = None, parsed: Optional[Dict] = None,
                           refinements: Optional[List[str]] = None) -> Dict[str, np.ndarray]:
        """
        mode에 필요한 유사도 항(raw 코사인 유사도)을 계산해서 dict로 반환.
        항 이름: gemma_text(A), clip_image(B), cross_t2i(F), cross_i2t(E의 4번째 항)

        refinements: 추가 프롬프트("lighter blue" 등) 목록.
        - cross_t2i 항: 각 정제 문구를 CLIP 텍스트로 임베딩해 쿼리 벡터에 방향으로
          더하는 임베딩 스티어링 적용 — q = normalize(q_base + α·Σd_i).
          비교급/상대 표현("slimmer", "warmer tone")을 사전 없이 반영하기 위함.
        - gemma_text 항: 문자열 연결(query + refinements)로 반영 (문장 임베딩 특성상 충분).
        """
        need = {
            "text_text": ["gemma_text"],
            "image_image": ["clip_image"],
            "hybrid_legacy": ["gemma_text", "clip_image"],
            "cross_t2i_only": ["cross_t2i"],
            "full_fusion": ["gemma_text", "clip_image", "cross_t2i", "cross_i2t"],
        }[mode]

        refinements = [r for r in (refinements or []) if r and r.strip()]
        full_text = " ".join([query_text] + refinements) if query_text else None

        terms = {}
        query_image_emb = None  # clip_image/cross_i2t가 같은 쿼리 이미지 인코딩을 공유

        for term in need:
            if term == "gemma_text":
                if full_text:
                    q = self.encode_query_text_gemma(full_text, parsed)
                    terms[term] = np.dot(self.gemma_name_embeddings, q)
            elif term == "clip_image":
                if query_image:
                    if query_image_emb is None:
                        query_image_emb = self.encode_query_image_clip(query_image)
                    terms[term] = np.dot(self.clip_image_embeddings, query_image_emb)
            elif term == "cross_t2i":
                if query_text:
                    q = self.encode_query_text_clip(query_text)
                    for r in refinements:
                        q = q + REFINE_ALPHA * self.encode_query_text_clip(r)
                    q = q / np.linalg.norm(q)
                    terms[term] = np.dot(self.clip_image_embeddings, q)
            elif term == "cross_i2t":
                if query_image:
                    if query_image_emb is None:
                        query_image_emb = self.encode_query_image_clip(query_image)
                    terms[term] = np.dot(self.clip_name_embeddings, query_image_emb)
        return terms

    # --- X(싫어요) 소프트 페널티 ---
    def _apply_soft_dislike_penalty(self, final_scores: np.ndarray, excluded_ids: Set) -> np.ndarray:
        """
        제외 상품과 CLIP 이미지 유사도가 높은(사실상 같은 디자인/색상 변형) 상품의
        최종 점수를 감쇠한다. 제외 상품 자체는 apply_brand_diversity에서 하드 제외됨.
        곱셈 감쇠라 코사인 점수/RRF 점수 어느 스케일에서도 동일하게 동작한다.
        """
        idx = [i for i, p in enumerate(self.products) if p['id'] in excluded_ids]
        if not idx:
            return final_scores

        sims = self.clip_image_embeddings @ self.clip_image_embeddings[idx].T  # (N, k)
        max_sim = sims.max(axis=1)
        thr = SOFT_PENALTY_SIM_THRESHOLD
        over = np.clip((max_sim - thr) / (1 - thr), 0.0, 1.0)
        return final_scores * (1.0 - SOFT_PENALTY_STRENGTH * over)

    # --- RRF ---
    @staticmethod
    def _rrf_combine(score_arrays: List[np.ndarray], k: int = RRF_K) -> np.ndarray:
        """각 점수 배열을 순위화한 뒤 Reciprocal Rank Fusion으로 결합"""
        n = len(score_arrays[0])
        fused = np.zeros(n)
        for scores in score_arrays:
            order = np.argsort(scores)[::-1]           # 점수 내림차순 인덱스
            ranks = np.empty(n, dtype=np.int64)
            ranks[order] = np.arange(1, n + 1)          # 1-indexed 순위
            fused += 1.0 / (k + ranks)
        return fused

    # --- 추천 ---
    def recommend(self, mode: str, query_text: Optional[str] = None,
                  query_image: Optional[str] = None, top_k: int = 5,
                  max_per_brand: int = 2, excluded_ids: Optional[Set] = None,
                  refinements: Optional[List[str]] = None,
                  text_weight: float = 0.5, image_weight: float = 0.5,
                  debug: bool = False):
        mode = MODE_ALIASES.get(mode, mode)
        if mode not in MODES:
            raise ValueError(f"알 수 없는 mode: {mode} (가능: {MODES})")

        # 입력 검증
        if mode in ("text_text", "cross_t2i_only") and not query_text:
            raise ValueError(f"{mode} 조건은 query_text가 필요합니다")
        if mode == "image_image" and not query_image:
            raise ValueError("image_image 조건은 query_image가 필요합니다")
        if mode == "hybrid_legacy" and not (query_text and query_image):
            raise ValueError("hybrid_legacy 조건은 query_text와 query_image가 모두 필요합니다")
        if mode == "full_fusion" and not (query_text or query_image):
            raise ValueError("full_fusion 조건은 query_text 또는 query_image 중 하나 이상이 필요합니다")

        self.ensure_loaded()

        refinements = [r for r in (refinements or []) if r and r.strip()]
        # 카테고리/색상 파싱은 원쿼리+정제 연결 문자열 기준 (카테고리 페널티 안전망)
        parse_text = " ".join([query_text] + refinements) if query_text else ""
        parsed = parse_query(parse_text) if parse_text else {
            "category": None, "fit": [], "detail": [], "color": [], "raw_query": ""
        }
        target_category = parsed["category"]

        terms = self.compute_similarity(mode, query_text, query_image, parsed, refinements)

        # --- 조건별 결합 (카테고리 페널티는 전 조건 공용 apply_category_penalty 하나만 사용) ---
        if mode == "text_text":
            final_scores = apply_category_penalty(terms["gemma_text"], self.products, target_category)
            fusion = "단일 항 + 카테고리 페널티"
        elif mode == "image_image":
            final_scores = apply_category_penalty(terms["clip_image"], self.products, target_category)
            fusion = "단일 항 + 카테고리 페널티"
        elif mode == "cross_t2i_only":
            final_scores = apply_category_penalty(terms["cross_t2i"], self.products, target_category)
            fusion = "단일 항(쿼리텍스트→상품사진) + 카테고리 페널티"
        elif mode == "hybrid_legacy":
            # 기존 TextImageRecommender 가중합 로직 그대로 (개선 전 베이스라인, 변경 금지)
            combined = text_weight * terms["gemma_text"] + image_weight * terms["clip_image"]
            final_scores = apply_category_penalty(combined, self.products, target_category)
            fusion = f"가중합(text {text_weight} + image {image_weight}) + 카테고리 페널티"
        else:  # full_fusion
            penalized = {
                name: apply_category_penalty(scores, self.products, target_category)
                for name, scores in terms.items()
            }
            final_scores = self._rrf_combine(list(penalized.values()))
            fusion = f"항별 카테고리 페널티 → 순위화 → RRF(k={RRF_K}, {len(penalized)}개 항)"

        # X(싫어요) 소프트 페널티: 제외 상품과 유사한 상품도 함께 강등
        if excluded_ids:
            final_scores = self._apply_soft_dislike_penalty(final_scores, excluded_ids)

        if debug:
            print(f"   [debug] mode={mode} | 사용 항: {sorted(terms.keys())} | 결합: {fusion} "
                  f"| target_category={target_category} | refinements={refinements} "
                  f"| 소프트페널티 대상: {len(excluded_ids) if excluded_ids else 0}개 제외상품 기준")

        selected = apply_brand_diversity(
            [], final_scores, None, self.products, top_k, max_per_brand, excluded_ids=excluded_ids
        )

        results = []
        for rank, idx in enumerate(selected):
            p = self.products[idx]
            results.append({
                'rank': rank + 1,
                'product_id': p['id'],
                'name': p.get('name', ''),
                'brand': p.get('brand_name', ''),
                'final_score': float(final_scores[idx]),
                'term_scores': {name: float(scores[idx]) for name, scores in terms.items()},
                'terms_used': sorted(terms.keys()),
                'fusion': fusion,
                'price': p.get('sale_price', 0) or p.get('original_price', 0),
                'image_path': p.get('local_image_path', ''),
                'product_url': p.get('product_url', '')
            })

        return results, parsed


# -------------------------
# 실행 함수
# -------------------------
def run_mode(mode: str, query_text: str = "", query_image: str = "",
             top_k: int = 5, db_path: str = DB_PATH, debug: bool = False,
             recommender: UnifiedRecommender = None):
    if query_image and not os.path.exists(query_image):
        print(f"❌ 이미지 없음: {query_image}")
        return None

    rec = recommender or UnifiedRecommender(FashionDB(db_path))
    results, parsed = rec.recommend(
        mode, query_text=query_text or None, query_image=query_image or None,
        top_k=top_k, debug=debug,
    )

    mode_name = MODE_ALIASES.get(mode, mode)
    info_parts = []
    if query_text:
        info_parts.append(f"쿼리: {query_text}")
    if query_image:
        info_parts.append(f"이미지: {query_image}")
    info_parts.append(f"파싱: {parsed}")
    if results:
        info_parts.append(f"결합: {results[0]['fusion']}")
    print_results(results, f"조건 {mode_name}", " | ".join(info_parts))
    return results


# -------------------------
# 대화형 모드
# -------------------------
def interactive_mode(db_path: str = DB_PATH):
    print("\n" + "=" * 80)
    print("🎮 의류 추천 시스템 - 대화형 모드 (5개 비교 조건)")
    print("=" * 80)

    rec = UnifiedRecommender(FashionDB(db_path))

    while True:
        print("\n조건 선택:")
        print("  a. text_text      - Gemma 텍스트 vs 상품명")
        print("  b. image_image    - CLIP 이미지 vs 상품 사진")
        print("  c. hybrid_legacy  - a+b 가중합 (레거시 베이스라인)")
        print("  f. cross_t2i_only - 쿼리텍스트→상품사진 단일 항 (텍스트 검색 기본)")
        print("  e. full_fusion    - 4개 항 전부 RRF (최종 채택 모델)")
        print("  q. 종료")

        choice = input("\n선택: ").strip().lower()
        if choice == 'q':
            print("종료합니다.")
            break
        if choice not in MODE_ALIASES:
            print("잘못된 선택입니다.")
            continue

        mode = MODE_ALIASES[choice]
        top_k = int(input("추천 개수 (기본 5): ").strip() or "5")
        query_text = input("텍스트 쿼리 (없으면 엔터): ").strip()
        query_image = input("이미지 경로 (없으면 엔터): ").strip()

        try:
            run_mode(mode, query_text, query_image, top_k, db_path, debug=True, recommender=rec)
        except ValueError as e:
            print(f"❌ {e}")


def main():
    parser = argparse.ArgumentParser(description="의류 추천 시스템 (5개 비교 조건)")
    parser.add_argument("--mode", "-m", type=str,
                        choices=MODES + list(MODE_ALIASES.keys()),
                        help="비교 조건 (a~e 또는 전체 이름)")
    parser.add_argument("--text", "-t", type=str, default="")
    parser.add_argument("--image", "-i", type=str, default="")
    parser.add_argument("--top-k", "-k", type=int, default=5)
    parser.add_argument("--db", type=str, default=DB_PATH)
    parser.add_argument("--debug", action="store_true", help="사용된 유사도 항/결합 로직 출력")
    parser.add_argument("--interactive", action="store_true")

    args = parser.parse_args()

    if args.interactive or not args.mode:
        interactive_mode(args.db)
        return

    run_mode(args.mode, args.text, args.image, args.top_k, args.db, debug=args.debug)


if __name__ == "__main__":
    main()
