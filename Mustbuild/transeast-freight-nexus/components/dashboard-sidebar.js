class CustomDashboardSidebar extends HTMLElement {
  connectedCallback() {
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 250px;
          background-color: white;
          height: calc(100vh - 70px);
          position: fixed;
          top: 70px;
          left: 0;
          border-right: 1px solid #E5E7EB;
          padding: 1.5rem 0;
          overflow-y: auto;
        }
        
        .sidebar-menu {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }
        
        .menu-item {
          display: flex;
          align-items: center;
          padding: 0.75rem 1.5rem;
          color: #4B5563;
          font-weight: 500;
          transition: all 0.3s;
          cursor: pointer;
        }
        
        .menu-item:hover {
          background-color: #F9FAFB;
          color: #5E35B1;
        }
        
        .menu-item.active {
          background-color: #F3F0FF;
          color: #5E35B1;
          border-right: 3px solid #5E35B1;
        }
        
        .menu-item i {
          margin-right: 0.75rem;
          width: 20px;
          height: 20px;
        }
        
        .menu-section {
          margin: 1.5rem 0 0.5rem 1.5rem;
          font-size: 0.75rem;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: #6B7280;
        }
        
        @media (max-width: 768px) {
          :host {
            width: 100%;
            height: auto;
            position: static;
            border-right: none;
            border-bottom: 1px solid #E5E7EB;
            padding: 0;
          }
          
          .sidebar-menu {
            flex-direction: row;
            overflow-x: auto;
            padding: 0.5rem 1rem;
          }
          
          .menu-item {
            padding: 0.5rem 1rem;
            white-space: nowrap;
          }
          
          .menu-section {
            display: none;
          }
        }
      </style>
      
      <div class="sidebar-menu">
        <div class="menu-section">Main</div>
        <div class="menu-item active">
          <i data-feather="home"></i>
          <span>Dashboard</span>
        </div>
        <div class="menu-item">
          <i data-feather="package"></i>
          <span>Shipments</span>
        </div>
        <div class="menu-item">
          <i data-feather="truck"></i>
          <span>Carriers</span>
        </div>
        <div class="menu-item">
          <i data-feather="dollar-sign"></i>
          <span>Payments</span>
        </div>
        
        <div class="menu-section">Tools</div>
        <div class="menu-item">
          <i data-feather="map"></i>
          <span>Route Planner</span>
        </div>
        <div class="menu-item">
          <i data-feather="bar-chart-2"></i>
          <span>Analytics</span>
        </div>
        <div class="menu-item">
          <i data-feather="file-text"></i>
          <span>Documents</span>
        </div>
        
        <div class="menu-section">Account</div>
        <div class="menu-item">
          <i data-feather="settings"></i>
          <span>Settings</span>
        </div>
        <div class="menu-item">
          <i data-feather="help-circle"></i>
          <span>Support</span>
        </div>
        <div class="menu-item">
          <i data-feather="log-out"></i>
          <span>Logout</span>
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
    
    // Add click handlers for menu items
    const menuItems = this.shadowRoot.querySelectorAll('.menu-item');
    menuItems.forEach(item => {
      item.addEventListener('click', () => {
        menuItems.forEach(i => i.classList.remove('active'));
        item.classList.add('active');
      });
    });
  }
}

customElements.define('custom-dashboard-sidebar', CustomDashboardSidebar);