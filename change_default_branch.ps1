# Script para cambiar la rama por defecto en GitHub
# Requiere un token de acceso personal de GitHub

param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubToken,
    
    [string]$OrgName = "aceleradora-la",
    [string]$RepoName = "odoo-argentina-ce-extras",
    [string]$DefaultBranch = "18.0"
)

$headers = @{
    'Accept' = 'application/vnd.github.v3+json'
    'Authorization' = "token $GitHubToken"
}

$body = @{
    default_branch = $DefaultBranch
} | ConvertTo-Json

try {
    Write-Host "Cambiando la rama por defecto a $DefaultBranch..." -ForegroundColor Yellow
    $response = Invoke-RestMethod -Uri "https://api.github.com/repos/$OrgName/$RepoName" -Method PATCH -Headers $headers -Body $body -ContentType 'application/json'
    
    Write-Host "¡Rama por defecto cambiada exitosamente!" -ForegroundColor Green
    Write-Host "Rama por defecto: $($response.default_branch)" -ForegroundColor Cyan
} catch {
    Write-Host "Error al cambiar la rama por defecto:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    
    if ($_.Exception.Response.StatusCode -eq 401) {
        Write-Host "`nEl token no es válido o no tiene los permisos necesarios." -ForegroundColor Yellow
        Write-Host "Asegúrate de que el token tenga el scope 'repo' o 'admin:repo'" -ForegroundColor Yellow
    }
}

