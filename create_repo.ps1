# Script para crear el repositorio en GitHub usando la API
# Requiere un token de acceso personal de GitHub con permisos de repositorio

param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubToken,
    
    [string]$OrgName = "aceleradora-la",
    [string]$RepoName = "odoo-argentina-ce-extras"
)

$headers = @{
    'Accept' = 'application/vnd.github.v3+json'
    'Authorization' = "token $GitHubToken"
}

$body = @{
    name = $RepoName
    description = "Módulos adicionales para Odoo Community Edition - Localización Argentina"
    private = $false
    auto_init = $false
} | ConvertTo-Json

try {
    Write-Host "Creando repositorio $RepoName en la organización $OrgName..." -ForegroundColor Yellow
    $response = Invoke-RestMethod -Uri "https://api.github.com/orgs/$OrgName/repos" -Method Post -Headers $headers -Body $body -ContentType 'application/json'
    
    Write-Host "¡Repositorio creado exitosamente!" -ForegroundColor Green
    Write-Host "URL: $($response.html_url)" -ForegroundColor Cyan
    
    # Configurar el remoto y hacer push
    Write-Host "`nConfigurando remoto y haciendo push..." -ForegroundColor Yellow
    git remote set-url origin $response.clone_url
    git push -u origin main
    
    Write-Host "`n¡Todo listo! El repositorio está publicado en GitHub." -ForegroundColor Green
} catch {
    Write-Host "Error al crear el repositorio:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    
    if ($_.Exception.Response.StatusCode -eq 401) {
        Write-Host "`nEl token no es válido o no tiene los permisos necesarios." -ForegroundColor Yellow
        Write-Host "Asegúrate de que el token tenga el scope 'repo' o 'write:org'" -ForegroundColor Yellow
    } elseif ($_.Exception.Response.StatusCode -eq 422) {
        Write-Host "`nEl repositorio ya existe o hay un problema con el nombre." -ForegroundColor Yellow
    }
}

