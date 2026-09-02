
// Main application scripts
// Authentication state management
let isAuthenticated = false;
let currentUserRole = '';

// Check authentication status from localStorage
function checkAuth() {
    const token = localStorage.getItem('authToken');
    isAuthenticated = !!token;
    currentUserRole = localStorage.getItem('userRole') || '';
    updateAuthUI();
}

// Update UI based on authentication status
function updateAuthUI() {
    const loginBtn = document.querySelector('.btn-login');
    const registerBtn = document.querySelector('.btn-register');
    const logoutBtn = document.querySelector('.logout-btn');
    
    if (loginBtn && registerBtn) {
        if (isAuthenticated) {
            loginBtn.style.display = 'none';
            registerBtn.style.display = 'none';
        } else {
            loginBtn.style.display = 'block';
            registerBtn.style.display = 'block';
        }
    }
    
    if (logoutBtn) {
        logoutBtn.style.display = isAuthenticated ? 'block' : 'none';
    }
}

// Handle login with role assignment
function handleLogin(email, password, role) {
    localStorage.setItem('authToken', 'sample-token-' + Date.now());
    localStorage.setItem('userEmail', email);
    localStorage.setItem('userRole', role || 'user');
    isAuthenticated = true;
    currentUserRole = role || 'user';
    updateAuthUI();
    
    // Redirect based on role
    redirectByRole(role);
}

// Redirect based on user role
function redirectByRole(role) {
    switch(role) {
        case 'broker':
            window.location.href = '/dashboard-broker.html';
            break;
        case 'carrier':
            window.location.href = '/dashboard-carrier.html';
            break;
        case 'government':
            window.location.href = '/dashboard-government.html';
            break;
        case 'shipper':
            window.location.href = '/dashboard-shipper.html';
            break;
        default:
            window.location.href = '/dashboard.html';
    }
}

// Handle logout
function handleLogout() {
    localStorage.removeItem('authToken');
    localStorage.removeItem('userEmail');
    localStorage.removeItem('userRole');
    localStorage.removeItem('userType');
    isAuthenticated = false;
    currentUserRole = '';
    updateAuthUI();
    window.location.href = '/';
}

// Protect pages that require login
function requireAuth() {
    const token = localStorage.getItem('authToken');
    if (!token) {
        window.location.href = '/login.html?redirect=' + encodeURIComponent(window.location.pathname);
        return false;
    }
    return true;
}

// Initialize auth check on page load
document.addEventListener('DOMContentLoaded', function() {
    checkAuth();
    
    // Logout button handler
    const logoutBtn = document.querySelector('.logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', handleLogout);
    }
    
    // Initialize animations
    const animateOnScroll = () => {
        const elements = document.querySelectorAll('.fade-in');
        elements.forEach(el => {
            const elementPosition = el.getBoundingClientRect().top;
            const screenPosition = window.innerHeight / 1.3;
            
            if(elementPosition < screenPosition) {
                el.classList.add('animate-fadeIn');
            }
        });
    };
    
    window.addEventListener('scroll', animateOnScroll);
    animateOnScroll(); // Run once on load
    
    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            
            const targetId = this.getAttribute('href');
            if(targetId === '#') return;
            
            const targetElement = document.querySelector(targetId);
            if(targetElement) {
                window.scrollTo({
                    top: targetElement.offsetTop - 100,
                    behavior: 'smooth'
                });
            }
        });
    });
    
    // Protect dashboard pages
    const protectedPages = ['/dashboard.html', '/dashboard-broker.html', '/dashboard-carrier.html', 
                           '/dashboard-shipper.html', '/dashboard-government.html', '/fleet-management.html',
                           '/load-board.html', '/post-load.html', '/driver-management.html'];
    const currentPath = window.location.pathname;
    if (protectedPages.some(page => currentPath.endsWith(page))) {
        requireAuth();
    }
});