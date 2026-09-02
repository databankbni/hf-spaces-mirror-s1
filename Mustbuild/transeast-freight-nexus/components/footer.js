class CustomFooter extends HTMLElement {
  connectedCallback() {
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          background-color: #1A237E;
          color: white;
          padding: 4rem 2rem;
        }
        
        .footer-container {
          max-width: 1200px;
          margin: 0 auto;
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 2rem;
        }
        
        .footer-logo {
          font-size: 1.5rem;
          font-weight: 700;
          margin-bottom: 1rem;
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }
        
        .footer-description {
          color: #E8EAF6;
          margin-bottom: 1.5rem;
          line-height: 1.6;
        }
        
        .social-links {
          display: flex;
          gap: 1rem;
        }
        
        .social-link {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          background-color: rgba(255, 255, 255, 0.1);
          display: flex;
          align-items: center;
          justify-content: center;
          transition: background-color 0.3s;
        }
        
        .social-link:hover {
          background-color: rgba(255, 255, 255, 0.2);
        }
        
        .footer-heading {
          font-size: 1.2rem;
          font-weight: 600;
          margin-bottom: 1.5rem;
          position: relative;
          padding-bottom: 0.5rem;
        }
        
        .footer-heading::after {
          content: '';
          position: absolute;
          bottom: 0;
          left: 0;
          width: 40px;
          height: 2px;
          background-color: #7C4DFF;
        }
        
        .footer-links {
          display: flex;
          flex-direction: column;
          gap: 0.8rem;
        }
        
        .footer-link {
          color: #E8EAF6;
          transition: color 0.3s;
        }
        
        .footer-link:hover {
          color: #7C4DFF;
        }
        
        .footer-bottom {
          max-width: 1200px;
          margin: 3rem auto 0;
          padding-top: 2rem;
          border-top: 1px solid rgba(255, 255, 255, 0.1);
          display: flex;
          flex-wrap: wrap;
          justify-content: space-between;
          gap: 1rem;
        }
        
        .copyright {
          color: #C5CAE9;
        }
        
        .legal-links {
          display: flex;
          gap: 1.5rem;
        }
        
        .legal-link {
          color: #C5CAE9;
          transition: color 0.3s;
        }
        
        .legal-link:hover {
          color: white;
        }
        
        @media (max-width: 768px) {
          .footer-container {
            grid-template-columns: 1fr;
          }
          
          .footer-bottom {
            flex-direction: column;
            align-items: center;
            text-align: center;
          }
        }
      </style>
      
      <div class="footer-container">
        <div class="footer-about">
          <div class="footer-logo">
            <i data-feather="truck"></i>
            <span>TransEast</span>
          </div>
          <p class="footer-description">
            Africa's leading digital freight platform connecting shippers with carriers across land, air, and sea transport networks.
          </p>
          <div class="social-links">
            <a href="#" class="social-link">
              <i data-feather="facebook"></i>
            </a>
            <a href="#" class="social-link">
              <i data-feather="twitter"></i>
            </a>
            <a href="#" class="social-link">
              <i data-feather="linkedin"></i>
            </a>
            <a href="#" class="social-link">
              <i data-feather="instagram"></i>
            </a>
          </div>
        </div>
        
        <div class="footer-links-container">
          <h3 class="footer-heading">Services</h3>
          <div class="footer-links">
            <a href="/land-freight.html" class="footer-link">Land Freight</a>
            <a href="/air-freight.html" class="footer-link">Air Freight</a>
            <a href="/sea-freight.html" class="footer-link">Sea Freight</a>
            <a href="/fleet-management.html" class="footer-link">Logistics Solutions</a>
            <a href="/load-board.html" class="footer-link">Shipment Tracking</a>
</div>
        </div>
        
        <div class="footer-links-container">
          <h3 class="footer-heading">Company</h3>
          <div class="footer-links">
            <a href="/request-demo.html" class="footer-link">About Us</a>
            <a href="/request-demo.html" class="footer-link">Careers</a>
            <a href="/request-demo.html" class="footer-link">Blog</a>
            <a href="/request-demo.html" class="footer-link">Press</a>
            <a href="/request-demo.html" class="footer-link">Partners</a>
</div>
        </div>
        
        <div class="footer-links-container">
          <h3 class="footer-heading">Support</h3>
          <div class="footer-links">
            <a href="/request-demo.html" class="footer-link">Help Center</a>
            <a href="/request-demo.html" class="footer-link">Contact Us</a>
            <a href="/request-demo.html" class="footer-link">FAQs</a>
            <a href="/request-demo.html" class="footer-link">Safety</a>
            <a href="/request-demo.html" class="footer-link">Feedback</a>
</div>
        </div>
      </div>
      
      <div class="footer-bottom">
        <p class="copyright">© 2023 TransEast Freight Nexus. All rights reserved.</p>
        <div class="legal-links">
          <a href="/terms.html" class="legal-link">Terms of Service</a>
          <a href="/privacy.html" class="legal-link">Privacy Policy</a>
          <a href="/request-demo.html" class="legal-link">Cookie Policy</a>
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

customElements.define('custom-footer', CustomFooter);