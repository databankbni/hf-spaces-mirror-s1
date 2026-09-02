# Quick Deployment Script for Hugging Face Spaces
# Run this after cloning your HF Space repository

Write-Host "🚀 SegmentoPulse Backend - Hugging Face Spaces Deployment" -ForegroundColor Cyan
Write-Host ""

# Check if we're in the right directory
if (-not (Test-Path "app/main.py")) {
    Write-Host "❌ Error: app/main.py not found. Make sure you're in the SegmentoPulse/backend directory" -ForegroundColor Red
    exit 1
}

# Check for .env file and warn
if (Test-Path ".env") {
    Write-Host "⚠️  Warning: .env file found. This should NOT be committed to Git!" -ForegroundColor Yellow
    Write-Host "   Make sure .env is in .gitignore" -ForegroundColor Yellow
    Write-Host ""
}

# Clean up unnecessary files
Write-Host "🧹 Cleaning up..." -ForegroundColor Green
Get-ChildItem -Path "." -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path "." -Recurse -Filter "*.pyc" | Remove-Item -Force -ErrorAction SilentlyContinue
Remove-Item -Path ".env" -ErrorAction SilentlyContinue

# Check required files
Write-Host "✅ Checking required files..." -ForegroundColor Green
$required = @("Dockerfile", "README.md", "requirements.txt", "app/main.py", "app/config.py")
foreach ($file in $required) {
    if (Test-Path $file) {
        Write-Host "  ✓ $file" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $file MISSING" -ForegroundColor Red
    }
}
Write-Host ""

# Git status
Write-Host "📦 Preparing for deployment..." -ForegroundColor Cyan
git status --short

Write-Host ""
Write-Host "📋 Pre-Deployment Checklist:" -ForegroundColor Yellow
Write-Host "  [ ] Created HF Space with Docker SDK" -ForegroundColor White
Write-Host "  [ ] Cloned Space repository" -ForegroundColor White
Write-Host "  [ ] Copied backend files to Space directory" -ForegroundColor White
Write-Host "  [ ] Added API keys to HF Spaces Secrets" -ForegroundColor White
Write-Host ""

$confirm = Read-Host "Ready to commit and push to Hugging Face? (y/n)"
if ($confirm -eq 'y' -or $confirm -eq 'Y') {
    Write-Host ""
    Write-Host "🚀 Deploying to Hugging Face..." -ForegroundColor Cyan
    
    git add .
    git commit -m "Deploy SegmentoPulse backend to HF Spaces"
    git push
    
    Write-Host ""
    Write-Host "✅ Deployment initiated!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📊 Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Monitor build logs in your HF Space" -ForegroundColor White
    Write-Host "  2. Test endpoints once deployed" -ForegroundColor White
    Write-Host "  3. Update frontend environment variable" -ForegroundColor White
    Write-Host "  4. Deploy frontend to production" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "Deployment cancelled." -ForegroundColor Yellow
}
