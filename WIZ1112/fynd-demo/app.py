# -*- coding: utf-8 -*-
"""
FYND - Flask Backend API
의류 추천 시스템 웹 API
- 추천 로직은 src.recommend.UnifiedRecommender(5개 비교 조건 통합 인터페이스)에 위임한다.
"""

import os
import json
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

from src.recommend import UnifiedRecommender, FashionDB, MODES, MODE_ALIASES

app = Flask(__name__)
CORS(app)

# 설정
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# 경로 설정
DB_PATH = "fashion_products.db"
WISHLIST_PATH = "wishlist.json"

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# -------------------------
# 유틸리티 함수
# -------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# 전역 추천 엔진 (통합 인터페이스, lazy 로딩)
engine = UnifiedRecommender(FashionDB(DB_PATH))

# 하위 호환용 mode 별칭 (기존 API 파라미터 유지)
LEGACY_MODE_ALIASES = {
    "text_image_cross": "cross_t2i_only",  # 구 Model 5 → F
    "cross_only": "cross_t2i_only",        # 구 D 조건은 서빙에서 제거, F로 매핑
}


def resolve_mode(mode: str, has_image: bool) -> str:
    """
    API mode 파라미터 → 통합 인터페이스 조건 이름.
    기본(default) 라우팅 — 2026-07 평가 실험으로 확정:
      텍스트만        → F(cross_t2i_only): 묘사형 쿼리 평가 최고 성능 (MRR 0.480)
      텍스트+이미지   → E(full_fusion): 최종 채택 모델 (4-way 결합)
    """
    if mode in (None, "", "default"):
        return "full_fusion" if has_image else "cross_t2i_only"
    mode = LEGACY_MODE_ALIASES.get(mode, mode)
    mode = MODE_ALIASES.get(mode, mode)
    if mode not in MODES:
        raise ValueError(f"알 수 없는 mode: {mode} (가능: {MODES})")
    return mode


# -------------------------
# 위시리스트 관리
# -------------------------
def load_wishlist():
    if os.path.exists(WISHLIST_PATH):
        with open(WISHLIST_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_wishlist(items):
    with open(WISHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


# -------------------------
# 라우트
# -------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/recommendation')
def recommendation():
    return render_template('recommendation.html')


@app.route('/wishlist')
def wishlist_page():
    return render_template('wishlist.html')


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/mypage')
def mypage():
    return render_template('mypage.html')


@app.route('/images/<path:filename>')
def serve_image(filename):
    """이미지 서빙"""
    return send_from_directory('images', filename)


@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """업로드된 이미지 서빙"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/upload', methods=['POST'])
def upload_image():
    """이미지 업로드"""
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        return jsonify({'filename': filename, 'path': filepath})

    return jsonify({'error': 'Invalid file type'}), 400


@app.route('/api/recommend', methods=['POST'])
def recommend():
    """
    추천 API — mode로 서빙 조건 선택 가능:
      text_text / image_image / hybrid_legacy / cross_t2i_only / full_fusion
    생략(default) 시: 텍스트만 → cross_t2i_only(F), 텍스트+이미지 → full_fusion(E).
    (구 "text_image_cross"/"cross_only"는 cross_t2i_only 별칭으로 하위 호환 지원)
    """
    data = request.json
    query = data.get('query', '')
    image_path = data.get('image_path', '')
    excluded_ids = set(data.get('excluded_ids', []))
    # 추가 프롬프트 목록 ("lighter blue" 등) — CLIP 임베딩 스티어링으로 반영
    refinements = [str(r) for r in data.get('refinements', []) if str(r).strip()]
    top_k = data.get('top_k', 3)

    has_image = bool(image_path and os.path.exists(image_path))

    try:
        mode = resolve_mode(data.get('mode'), has_image)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    if mode == 'image_image':
        if not has_image:
            return jsonify({'error': 'image_path is required for image_image mode'}), 400
    elif not query:
        return jsonify({'error': 'Query is required'}), 400

    try:
        results, _ = engine.recommend(
            mode,
            query_text=query or None,
            query_image=image_path if has_image else None,
            top_k=top_k,
            max_per_brand=1,
            excluded_ids=excluded_ids,
            refinements=refinements,
        )

        # 기존 API 응답 포맷 유지 (id/score) + 조건/항 정보 추가
        payload = [{
            'id': r['product_id'],
            'name': r['name'],
            'brand': r['brand'],
            'price': r['price'],
            'image_path': r['image_path'],
            'product_url': r['product_url'],
            'score': r['final_score'],
            'term_scores': r['term_scores'],
        } for r in results]

        return jsonify({'results': payload, 'mode': mode,
                        'terms_used': results[0]['terms_used'] if results else []})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/wishlist', methods=['GET'])
def get_wishlist():
    """위시리스트 조회"""
    items = load_wishlist()
    return jsonify({'items': items})


@app.route('/api/wishlist', methods=['POST'])
def add_to_wishlist():
    """위시리스트에 추가"""
    data = request.json
    items = load_wishlist()

    # 중복 체크
    for item in items:
        if item.get('id') == data.get('id'):
            return jsonify({'message': 'Already in wishlist'}), 200

    items.append({
        'id': data.get('id'),
        'name': data.get('name'),
        'brand': data.get('brand'),
        'price': data.get('price'),
        'image_path': data.get('image_path'),
        'product_url': data.get('product_url'),
        'added_at': datetime.now().isoformat()
    })

    save_wishlist(items)
    return jsonify({'message': 'Added to wishlist'})


@app.route('/api/wishlist/<int:item_id>', methods=['DELETE'])
def remove_from_wishlist(item_id):
    """위시리스트에서 제거"""
    items = load_wishlist()
    items = [item for item in items if item.get('id') != item_id]
    save_wishlist(items)
    return jsonify({'message': 'Removed from wishlist'})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
