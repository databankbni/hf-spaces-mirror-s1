# prepare_docker_context.ps1
# Refreshes the Docker build context with the latest digital_twin physics
# package, then rebuilds and restarts the docker compose stack -- one command
# to bring the packaged/offline version (for handing off to a teammate) back
# in sync with whatever's currently in ../Final_Project and this repo.
#
# Usage:
#   .\prepare_docker_context.ps1
#   .\prepare_docker_context.ps1 -PhysicsRepo "C:\path\to\your\Final_Project"
#   .\prepare_docker_context.ps1 -SkipBuild   # just refresh the staging folder, don't touch docker compose

param(
    [string]$PhysicsRepo = (Resolve-Path "../Final_Project" -ErrorAction SilentlyContinue),
    [switch]$SkipBuild
)

if (-not $PhysicsRepo -or -not (Test-Path $PhysicsRepo)) {
    Write-Error "Could not find the physics repo at '$PhysicsRepo'."
    Write-Error "Run: .\prepare_docker_context.ps1 -PhysicsRepo 'C:\path\to\Final_Project'"
    exit 1
}

$dest = "digital_twin_pkg"

Write-Host "Copying digital_twin package from: $PhysicsRepo" -ForegroundColor Cyan

# Clean and recreate staging folder
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Path $dest | Out-Null

# Copy the package source and its pyproject so pip can install it
Copy-Item "$PhysicsRepo\digital_twin" "$dest\digital_twin" -Recurse
Copy-Item "$PhysicsRepo\pyproject.toml" "$dest\pyproject.toml"

# Copy the data files that digital_twin reads at runtime
if (Test-Path "$PhysicsRepo\data") {
    Copy-Item "$PhysicsRepo\data" "$dest\data" -Recurse
} else {
    Write-Warning "No data folder found in $PhysicsRepo - skipping."
}

if ($SkipBuild) {
    Write-Host "Done. Now run: docker compose up --build" -ForegroundColor Green
    exit 0
}

Write-Host "Rebuilding and restarting docker compose..." -ForegroundColor Cyan
docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose up --build failed -- see output above."
    exit 1
}
Write-Host "Done. Docker stack is up to date at http://localhost:5173" -ForegroundColor Green
