// FYND - Main JavaScript

const API_BASE = '';

// State
let currentQuery = '';
let uploadedImagePath = '';
let currentResults = [];
let excludedIds = new Set();
let refinements = [];  // 추가 프롬프트 목록 (백엔드에서 CLIP 임베딩 스티어링으로 반영)

// Utils
function formatPrice(price) {
    return '₩' + Number(price).toLocaleString();
}

function showToast(message) {
    const toast = document.getElementById('toast');
    if (toast) {
        toast.textContent = message;
        toast.classList.add('active');
        setTimeout(() => toast.classList.remove('active'), 3000);
    }
}

function getGreeting() {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good Morning';
    if (hour < 18) return 'Good Afternoon';
    return 'Good Evening';
}

// Landing Page Functions
function initLandingPage() {
    const greetingEl = document.getElementById('greeting');
    if (greetingEl) {
        greetingEl.textContent = getGreeting() + ',';
    }
    
    const form = document.getElementById('search-form');
    const searchInput = document.getElementById('search-input');
    const addImageBtn = document.getElementById('add-image-btn');
    const imageInput = document.getElementById('image-input');
    const imagePreview = document.getElementById('image-preview');
    
    if (form) {
        form.addEventListener('submit', handleSearchSubmit);
    }
    
    if (addImageBtn && imageInput) {
        addImageBtn.addEventListener('click', () => imageInput.click());
        imageInput.addEventListener('change', handleImageSelect);
    }
}

async function handleImageSelect(e) {
    const file = e.target.files[0];
    if (!file) return;
    
    const addImageBtn = document.getElementById('add-image-btn');
    const imagePreview = document.getElementById('image-preview');
    
    // Upload image
    const formData = new FormData();
    formData.append('image', file);
    
    try {
        const response = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        if (data.path) {
            uploadedImagePath = data.path;
            addImageBtn.classList.add('has-image');
            addImageBtn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M5 13l4 4L19 7"/>
                </svg>
                image added
            `;
            
            // Show preview
            if (imagePreview) {
                imagePreview.src = URL.createObjectURL(file);
                imagePreview.classList.add('active');
            }
        }
    } catch (error) {
        console.error('Image upload error:', error);
        showToast('Failed to upload image');
    }
}

function handleSearchSubmit(e) {
    e.preventDefault();
    
    const searchInput = document.getElementById('search-input');
    const query = searchInput.value.trim();
    
    if (!query) {
        showToast('Please enter a search prompt');
        searchInput.focus();
        return;
    }
    
    // Store in sessionStorage
    sessionStorage.setItem('fynd_query', query);
    sessionStorage.setItem('fynd_image_path', uploadedImagePath);
    
    // Navigate to recommendation page
    window.location.href = '/recommendation';
}

// Recommendation Page Functions
function initRecommendationPage() {
    currentQuery = sessionStorage.getItem('fynd_query') || '';
    uploadedImagePath = sessionStorage.getItem('fynd_image_path') || '';
    excludedIds = new Set();
    refinements = [];

    if (!currentQuery) {
        window.location.href = '/';
        return;
    }

    renderResultsMeta();
    loadRecommendations();

    const form = document.getElementById('refine-form');
    if (form) {
        form.addEventListener('submit', handleRefineSubmit);
    }
}

// 현재 쿼리 + refine 칩 표시
function renderResultsMeta() {
    const queryEl = document.getElementById('query-display');
    if (queryEl) queryEl.textContent = `"${currentQuery}"`;

    const chipsEl = document.getElementById('refine-chips');
    if (!chipsEl) return;
    chipsEl.innerHTML = '';

    refinements.forEach((text, i) => {
        const chip = document.createElement('span');
        chip.className = 'refine-chip';
        const label = document.createElement('span');
        label.textContent = text;
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.textContent = '✕';
        removeBtn.title = 'Remove this refinement';
        removeBtn.addEventListener('click', () => {
            refinements.splice(i, 1);
            renderResultsMeta();
            loadRecommendations();
        });
        chip.appendChild(label);
        chip.appendChild(removeBtn);
        chipsEl.appendChild(chip);
    });
}

// 스켈레톤 로딩 타일
function renderSkeletons(grid, count = 3) {
    grid.innerHTML = '';
    for (let i = 0; i < count; i++) {
        const sk = document.createElement('div');
        sk.className = 'product-card-container skeleton-card';
        sk.innerHTML = `
            <div class="skeleton-image shimmer"></div>
            <div class="skeleton-line w40 shimmer"></div>
            <div class="skeleton-line w70 shimmer"></div>
        `;
        grid.appendChild(sk);
    }
}

async function loadRecommendations() {
    const productsGrid = document.getElementById('products-grid');
    const loadingEl = document.getElementById('loading');

    if (loadingEl) loadingEl.style.display = 'none';
    if (productsGrid) renderSkeletons(productsGrid);

    try {
        const response = await fetch(`${API_BASE}/api/recommend`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: currentQuery,
                image_path: uploadedImagePath,
                excluded_ids: Array.from(excludedIds),
                refinements: refinements,
                top_k: 3
            })
        });
        
        const data = await response.json();
        
        if (loadingEl) loadingEl.style.display = 'none';
        
        if (data.results) {
            currentResults = data.results;
            renderProducts(data.results);
        } else if (data.error) {
            showToast('Error: ' + data.error);
        }
    } catch (error) {
        console.error('Recommendation error:', error);
        if (loadingEl) loadingEl.style.display = 'none';
        showToast('Failed to load recommendations');
    }
}

function renderProducts(products) {
    const productsGrid = document.getElementById('products-grid');
    if (!productsGrid) return;
    
    productsGrid.innerHTML = '';
    
    products.forEach((product, index) => {
        const card = document.createElement('div');
        card.className = 'product-card-container';
        card.innerHTML = `
            <div class="product-card" data-product-id="${product.id}" data-index="${index}">
                <div class="product-image-container">
                    <img class="product-image" src="/${product.image_path}" alt="${product.name}"
                         onerror="this.src='/static/images/placeholder.png'">
                    <button class="dislike-btn" data-product-id="${product.id}" title="Not for me">✕</button>
                </div>
                <div class="product-info">
                    <span class="product-brand">${product.brand}</span>
                    <div class="product-meta">
                        <span class="product-name">${product.name}</span>
                        <span class="product-price">${formatPrice(product.price)}</span>
                    </div>
                </div>
            </div>
        `;

        productsGrid.appendChild(card);

        // Card click -> wishlist modal
        const cardEl = card.querySelector('.product-card');
        cardEl.addEventListener('click', () => showWishlistModal(product));

        // Dislike button (이미지 우상단 오버레이)
        const dislikeBtn = card.querySelector('.dislike-btn');
        dislikeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            handleDislike(product.id);
        });
    });
}

function handleDislike(productId) {
    excludedIds.add(productId);
    loadRecommendations();
}

function handleRefineSubmit(e) {
    e.preventDefault();

    const refineInput = document.getElementById('refine-input');
    const newPrompt = refineInput.value.trim();

    if (!newPrompt) return;

    // 쿼리에 이어붙이지 않고 정제 목록으로 따로 전송
    // (백엔드가 CLIP 임베딩 스티어링으로 "lighter blue" 같은 상대 표현을 반영)
    refinements.push(newPrompt);

    refineInput.value = '';
    renderResultsMeta();
    loadRecommendations();
}

// Wishlist Modal
function showWishlistModal(product) {
    const modal = document.getElementById('wishlist-modal');
    if (!modal) return;
    
    modal.classList.add('active');
    modal.dataset.productId = product.id;
    modal.dataset.product = JSON.stringify(product);
}

function hideWishlistModal() {
    const modal = document.getElementById('wishlist-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

async function confirmAddToWishlist() {
    const modal = document.getElementById('wishlist-modal');
    const product = JSON.parse(modal.dataset.product);
    
    try {
        const response = await fetch(`${API_BASE}/api/wishlist`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(product)
        });
        
        const data = await response.json();
        hideWishlistModal();
        showToast('Added to your wishlist');
    } catch (error) {
        console.error('Wishlist error:', error);
        showToast('Failed to add to wishlist');
    }
}

// Wishlist Page Functions
async function initWishlistPage() {
    await loadWishlist();
}

async function loadWishlist() {
    const productsGrid = document.getElementById('wishlist-grid');
    const emptyEl = document.getElementById('wishlist-empty');
    
    try {
        const response = await fetch(`${API_BASE}/api/wishlist`);
        const data = await response.json();
        
        if (data.items && data.items.length > 0) {
            if (emptyEl) emptyEl.style.display = 'none';
            renderWishlistItems(data.items);
        } else {
            if (emptyEl) emptyEl.style.display = 'block';
            if (productsGrid) productsGrid.innerHTML = '';
        }
    } catch (error) {
        console.error('Wishlist load error:', error);
        showToast('Failed to load wishlist');
    }
}

function renderWishlistItems(items) {
    const productsGrid = document.getElementById('wishlist-grid');
    if (!productsGrid) return;
    
    productsGrid.innerHTML = '';
    
    items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'product-card';
        card.innerHTML = `
            <div class="product-image-container">
                <img class="product-image" src="/${item.image_path}" alt="${item.name}"
                     onerror="this.src='/static/images/placeholder.png'">
            </div>
            <div class="product-info">
                <span class="product-brand">${item.brand}</span>
                <div class="product-meta">
                    <span class="product-name">${item.name}</span>
                    <span class="product-price">${formatPrice(item.price)}</span>
                </div>
            </div>
        `;
        
        card.addEventListener('click', () => {
            if (item.product_url) {
                window.open(item.product_url, '_blank');
            }
        });
        
        productsGrid.appendChild(card);
    });
}

// Initialize based on page
document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;
    
    if (path === '/' || path === '/index.html') {
        initLandingPage();
    } else if (path === '/recommendation') {
        initRecommendationPage();
    } else if (path === '/wishlist') {
        initWishlistPage();
    }
});
