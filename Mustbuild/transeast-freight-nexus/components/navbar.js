class CustomNavbar extends HTMLElement {
  connectedCallback() {
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          position: fixed;
          top: 0;
          left: 0;
          z-index: 1000;
          background-color: white;
          box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }
        
        .navbar-container {
          max-width: 1200px;
          margin: 0 auto;
          padding: 1rem 2rem;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        
        .logo {
          font-size: 1.5rem;
          font-weight: 700;
          color: #5E35B1;
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }
        
        .nav-links {
          display: flex;
          gap: 2rem;
        }
        
        .nav-link {
          color: #4A5568;
          font-weight: 500;
          transition: color 0.3s;
          position: relative;
        }
        
        .nav-link:hover {
          color: #5E35B1;
        }
        
        .nav-link.active {
          color: #5E35B1;
        }
        
        .nav-link.active::after {
          content: '';
          position: absolute;
          bottom: -5px;
          left: 0;
          width: 100%;
          height: 2px;
          background-color: #5E35B1;
        }
        
        .mobile-menu-btn {
          display: none;
          background: none;
          border: none;
          cursor: pointer;
        }
        
        .auth-buttons {
          display: flex;
          gap: 1rem;
        }
        
        .btn-login {
          padding: 0.5rem 1.5rem;
          border-radius: 9999px;
          border: 1px solid #5E35B1;
          color: #5E35B1;
          font-weight: 500;
          transition: all 0.3s;
        }
        
        .btn-login:hover {
          background-color: #F3F0FF;
        }
        
        .btn-register {
          padding: 0.5rem 1.5rem;
          border-radius: 9999px;
          background-color: #5E35B1;
          color: white;
          font-weight: 500;
          transition: all 0.3s;
        }
        
        .btn-register:hover {
          background-color: #4A2D8F;
        }
        
        .dropdown-wrapper {
          position: relative;
        }
        
        .dropdown-menu {
          display: none;
          position: absolute;
          top: 100%;
          left: 0;
          background: white;
          min-width: 220px;
          box-shadow: 0 10px 25px rgba(0,0,0,0.15);
          border-radius: 8px;
          padding: 8px 0;
          z-index: 1001;
          margin-top: 10px;
          border: 1px solid #E5E7EB;
        }
        
        .dropdown-menu.show {
          display: block;
        }
        
        .dropdown-item {
          display: block;
          padding: 10px 20px;
          color: #4A5568;
          font-weight: 400;
          transition: all 0.2s;
          white-space: nowrap;
        }
        
        .dropdown-item:hover {
          background-color: #F3F0FF;
          color: #5E35B1;
        }
        
        @media (max-width: 768px) {
          .nav-links, .auth-buttons {
            display: none;
          }
          
          .mobile-menu-btn {
            display: block;
          }
        }
      </style>
      
      <div class="navbar-container">
        <a href="/" class="logo">
          <i data-feather="truck"></i>
          <span>TransEast</span>
        </a>
        
        <div class="nav-links">
          <a href="/" class="nav-link active">Home</a>
          
          <div class="dropdown-wrapper">
            <a href="#" class="nav-link dropdown-trigger" data-dropdown="services">
              Services <i data-feather="chevron-down" class="w-4 h-4 inline ml-1"></i>
            </a>
            <div class="dropdown-menu" id="dropdown-services">
              <a href="/land-freight.html" class="dropdown-item">Land Freight</a>
              <a href="/air-freight.html" class="dropdown-item">Air Freight</a>
              <a href="/sea-freight.html" class="dropdown-item">Sea Freight</a>
              <a href="/logistics-solutions.html" class="dropdown-item">Logistics Solutions</a>
              <a href="/warehousing.html" class="dropdown-item">Warehousing</a>
            </div>
          </div>
          
          <div class="dropdown-wrapper">
            <a href="/load-board.html" class="nav-link dropdown-trigger" data-dropdown="loadboard">
              Load Board <i data-feather="chevron-down" class="w-4 h-4 inline ml-1"></i>
            </a>
            <div class="dropdown-menu" id="dropdown-loadboard">
              <a href="/load-board.html" class="dropdown-item">Find Loads</a>
              <a href="/post-load.html" class="dropdown-item">Post Load</a>
              <a href="/rate-calculator.html" class="dropdown-item">Rate Calculator</a>
              <a href="/shipment-tracking.html" class="dropdown-item">Track Shipment</a>
            </div>
          </div>
          
          <a href="/dashboard.html" class="nav-link">Dashboard</a>
          
          <div class="dropdown-wrapper">
            <a href="/fleet-management.html" class="nav-link dropdown-trigger" data-dropdown="fleet">
              Fleet <i data-feather="chevron-down" class="w-4 h-4 inline ml-1"></i>
            </a>
            <div class="dropdown-menu" id="dropdown-fleet">
              <a href="/fleet-management.html" class="dropdown-item">Fleet Overview</a>
              <a href="/driver-management.html" class="dropdown-item">Driver Management</a>
              <a href="/maintenance-schedule.html" class="dropdown-item">Maintenance</a>
              <a href="/fuel-management.html" class="dropdown-item">Fuel Management</a>
            </div>
          </div>
          
          <div class="dropdown-wrapper">
            <a href="/request-demo.html" class="nav-link dropdown-trigger" data-dropdown="contact">
              Contact <i data-feather="chevron-down" class="w-4 h-4 inline ml-1"></i>
            </a>
            <div class="dropdown-menu" id="dropdown-contact">
              <a href="/request-demo.html" class="dropdown-item">Request Demo</a>
              <a href="/contact-support.html" class="dropdown-item">Support</a>
              <a href="/about-us.html" class="dropdown-item">About Us</a>
              <a href="/careers.html" class="dropdown-item">Careers</a>
            </div>
          </div>
        </div>
        
        <div class="auth-buttons">
          <a href="/login.html" class="btn-login">Log In</a>
          <a href="/register.html" class="btn-register">Register</a>
        </div>
        
        <button class="mobile-menu-btn">
          <i data-feather="menu"></i>
        </button>
      </div>
    `;
    
    // Initialize feather icons
    const featherScript = document.createElement('script');
    featherScript.src = 'https://cdn.jsdelivr.net/npm/feather-icons/dist/feather.min.js';
    this.shadowRoot.appendChild(featherScript);
    
    featherScript.onload = () => {
      if (window.feather) {
        window.feather.replace();
      }
    };
    
    // Dropdown menu handling
    const dropdownTriggers = this.shadowRoot.querySelectorAll('.dropdown-trigger');
    let activeDropdown = null;
    
    dropdownTriggers.forEach(trigger => {
      trigger.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        const dropdownId = trigger.getAttribute('data-dropdown');
        const dropdownMenu = this.shadowRoot.querySelector(`#dropdown-${dropdownId}`);
        
        // Close other dropdowns
        if (activeDropdown && activeDropdown !== dropdownMenu) {
          activeDropdown.classList.remove('show');
        }
        
        // Toggle current
        dropdownMenu.classList.toggle('show');
        activeDropdown = dropdownMenu.classList.contains('show') ? dropdownMenu : null;
      });
    });
    
    // Close dropdowns when clicking outside
    this.shadowRoot.addEventListener('click', (e) => {
      if (!e.target.closest('.dropdown-wrapper')) {
        const dropdowns = this.shadowRoot.querySelectorAll('.dropdown-menu');
        dropdowns.forEach(d => d.classList.remove('show'));
        activeDropdown = null;
      }
    });
    
    // Mobile menu toggle
    const mobileMenuBtn = this.shadowRoot.querySelector('.mobile-menu-btn');
    mobileMenuBtn.addEventListener('click', () => {
      this.toggleMobileMenu();
    });
  }
  
  toggleMobileMenu() {
    console.log('Mobile menu toggled - implement your mobile menu logic here');
    // In a real implementation, you would show/hide a mobile menu
  }
}

customElements.define('custom-navbar', CustomNavbar);