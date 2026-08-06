# Deployment Guide: Production Website

## Quick Start with Docker

### Prerequisites
- Docker installed ([Download](https://www.docker.com/products/docker-desktop))
- Docker Compose (included with Docker Desktop)

### Local Deployment

1. **Build and run with Docker Compose:**
   ```bash
   docker-compose up --build
   ```

2. **Access the services:**
   - API: `http://localhost:8000`
   - Dashboard: `http://localhost:8501`
   - API Docs: `http://localhost:8000/docs`

3. **Stop services:**
   ```bash
   docker-compose down
   ```

### Production Deployment (Cloud)

#### Option 1: AWS (Recommended for scalability)

1. **Build and push Docker image to ECR:**
   ```bash
   # Create ECR repository
   aws ecr create-repository --repository-name dynamic-pricing-ai

   # Get login token
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

   # Build and push
   docker build -t dynamic-pricing-ai .
   docker tag dynamic-pricing-ai:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/dynamic-pricing-ai:latest
   docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/dynamic-pricing-ai:latest
   ```

2. **Deploy to ECS:**
   - Create ECS Cluster
   - Create Task Definition pointing to ECR image
   - Create Service with load balancer
   - Configure auto-scaling

3. **Set environment variables:**
   - Use `.env.production` as reference
   - Configure in ECS Task Definition

#### Option 2: DigitalOcean App Platform (Easiest)

1. **Push to GitHub:**
   ```bash
   git push origin master
   ```

2. **Create DigitalOcean App:**
   - Go to [DigitalOcean App Platform](https://cloud.digitalocean.com/apps)
   - Create new app → Select GitHub repo
   - Configure build:
     ```yaml
     services:
     - name: api
       github:
         repo: username/dynamic_pricing_ai
         branch: master
       build_command: docker build -f Dockerfile -t api .
       run_command: python scripts/run_api.py
       http_port: 8000
     - name: dashboard
       github:
         repo: username/dynamic_pricing_ai
         branch: master
       build_command: docker build -f Dockerfile -t dashboard .
       run_command: python -m streamlit run apps/dashboard/streamlit_app.py
       http_port: 8501
     ```
   - Deploy and get auto-assigned domain

#### Option 3: Docker Hub + Any VPS

1. **Push to Docker Hub:**
   ```bash
   docker build -t yourusername/dynamic-pricing-ai:latest .
   docker push yourusername/dynamic-pricing-ai:latest
   ```

2. **On your VPS (Ubuntu 20.04+):**
   ```bash
   # Install Docker
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh

   # Clone repo and deploy
   git clone https://github.com/yourusername/dynamic_pricing_ai.git
   cd dynamic_pricing_ai
   docker-compose up -d
   ```

3. **Setup Nginx reverse proxy:**
   ```nginx
   upstream api {
       server api:8000;
   }

   upstream dashboard {
       server dashboard:8501;
   }

   server {
       listen 80;
       server_name your-domain.com;

       location /api {
           proxy_pass http://api;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }

       location / {
           proxy_pass http://dashboard;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

4. **Setup SSL with Let's Encrypt:**
   ```bash
   sudo apt-get install certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.com
   ```

### Production Checklist

- [ ] Environment variables configured (`.env.production`)
- [ ] SSL/HTTPS enabled
- [ ] Database backups configured
- [ ] Logging & monitoring setup
- [ ] Health checks configured
- [ ] Auto-restart on failure enabled
- [ ] Load balancer configured (if needed)
- [ ] Rate limiting configured
- [ ] CORS properly configured for production
- [ ] API documentation at `/docs`

### Monitoring

Check logs:
```bash
docker-compose logs -f api
docker-compose logs -f dashboard
```

Health check:
```bash
curl http://localhost:8000/
```

### Scaling

For high traffic, add more workers in `docker-compose.yml`:
```yaml
api:
  # ... other config
  deploy:
    replicas: 3  # Multiple API instances
```

### Backup & Recovery

```bash
# Backup model artifacts
docker cp dynamic_pricing_api:/app/artifacts ./backup/

# Restore from backup
docker cp ./backup/artifacts dynamic_pricing_api:/app/
```

### Useful Docker Commands

```bash
# View running containers
docker-compose ps

# Execute command in container
docker-compose exec api python -m unittest discover -s tests

# View container logs
docker-compose logs -f api

# Restart service
docker-compose restart api

# Remove all containers and volumes
docker-compose down -v
```

---

**Your Dynamic Pricing AI is now ready for production deployment!** 🚀
