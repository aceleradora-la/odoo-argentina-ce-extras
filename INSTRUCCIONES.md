# Instrucciones para crear el repositorio en GitHub

## Opción 1: Usar el script automático (Recomendado)

1. **Crear un token de acceso personal en GitHub:**
   - Ve a: https://github.com/settings/tokens
   - Haz clic en "Generate new token" > "Generate new token (classic)"
   - Dale un nombre (ej: "Crear repo odoo-argentina-ce-extras")
   - Selecciona los scopes: `repo` y `write:org`
   - Haz clic en "Generate token"
   - **Copia el token** (solo se muestra una vez)

2. **Ejecutar el script:**
   ```powershell
   .\create_repo.ps1 -GitHubToken "TU_TOKEN_AQUI"
   ```

   El script creará el repositorio y hará el push automáticamente.

## Opción 2: Crear manualmente en GitHub

1. Ve a: https://github.com/organizations/aceleradora-la/repositories/new
2. Nombre del repositorio: `odoo-argentina-ce-extras`
3. Descripción: "Módulos adicionales para Odoo Community Edition - Localización Argentina"
4. Visibilidad: Público o Privado (según prefieras)
5. **NO marques** "Add a README file", "Add .gitignore", ni "Choose a license"
6. Haz clic en "Create repository"

7. **Luego ejecuta:**
   ```powershell
   git push -u origin main
   ```

## Verificar que todo esté listo

```powershell
git remote -v
git status
```

