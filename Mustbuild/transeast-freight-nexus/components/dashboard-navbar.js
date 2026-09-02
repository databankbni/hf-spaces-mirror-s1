class CustomDashboardNavbar extends HTMLElement {
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
          max-width: 100%;
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
        
        .search-bar {
          flex-grow: 1;
          max-width: 600px;
          margin: 0 2rem;
        }
        
        .search-input {
          width: 100%;
          padding: 0.75rem 1rem;
          border: 1px solid #E5E7EB;
          border-radius: 9999px;
          background-color: #F9FAFB;
          transition: all 0.3s;
        }
        
        .search-input:focus {
          outline: none;
          border-color: #5E35B1;
          background-color: white;
          box-shadow: 0 0 0 3px rgba(94, 53, 177, 0.1);
        }
        
        .user-menu {
          display: flex;
          align-items: center;
          gap: 1.5rem;
        }
        
        .notification-icon {
          position: relative;
          cursor: pointer;
        }
        
        .notification-badge {
          position: absolute;
          top: -3px;
          right: -3px;
          width: 16px;
          height: 16px;
          background-color: #EF4444;
          border-radius: 50%;
          color: white;
          font-size: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        
        .user-profile {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          cursor: pointer;
        }
        
        .user-avatar {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          background-color: #E9D8FD;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #5E35B1;
          font-weight: 600;
        }
        
        .user-name {
          font-weight: 500;
          color: #4B5563;
        }
        
        @media (max-width: 768px) {
          .search-bar {
            display: none;
          }
        }
      </style>
      
      <div class="navbar-container">
        <a href="/" class="logo">
          <i data-feather="truck"></i>
          <span>TransEast</span>
        </a>
        
        <div class="search-bar">
          <input type="text" class="search-input" placeholder="Search shipments, carriers...">
        </div>
        
        <div class="user-menu">
          <div class="notification-icon">
            <i data-feather="bell"></i>
            <span class="notification-badge">3</span>
          </div>
          
          <div class="user-profile">
            <div class="user-avatar">JD</div>
            <span class="user-name">John Doe</span>
            <i data-feather="chevron-down"></i>
          </div>
        </div>
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
  }
}

customElements.define('custom-dashboard-navbar', CustomDashboardNavbar);