# Instrucciones para instalar el módulo

## Problema: Error de dependencia con l10n_ar_edi

Si al intentar instalar el módulo `l10n_ar_import_bill_ce` aparece el error:

> "Intenta instalar el módulo 'l10n_ar_import_bill_ce' que depende del módulo 'l10n_ar_edi'"

Esto se debe a que Odoo tiene el módulo en caché con la versión anterior del manifest.

## Solución

### Opción 1: Actualizar lista de módulos (Recomendado)

1. En Odoo, ve a **Aplicaciones**
2. Haz clic en el botón **"Actualizar lista de aplicaciones"** (arriba a la izquierda)
3. Busca nuevamente el módulo `l10n_ar_import_bill_ce`
4. Intenta instalarlo nuevamente

### Opción 2: Reiniciar el servidor de Odoo

1. Detén el servidor de Odoo
2. Elimina los archivos `.pyc` del módulo (si existen):
   ```bash
   find l10n_ar_import_bill_ce -name "*.pyc" -delete
   find l10n_ar_import_bill_ce -name "__pycache__" -type d -exec rm -r {} +
   ```
3. Reinicia el servidor de Odoo
4. Actualiza la lista de módulos en Odoo
5. Intenta instalar el módulo nuevamente

### Opción 3: Limpiar caché de Odoo

Si usas Odoo con modo desarrollador:

1. Activa el **modo desarrollador**
2. Ve a **Configuración > Técnico > Base de datos > Limpiar caché**
3. Actualiza la lista de módulos
4. Intenta instalar el módulo nuevamente

## Verificar que el manifest está correcto

El archivo `__manifest__.py` debe tener estas dependencias:

```python
"depends": ["account", "l10n_ar", "l10n_latam_base", "l10n_latam_invoice_document"],
```

**NO debe incluir** `l10n_ar_edi` en las dependencias.

## Dependencias requeridas

El módulo requiere estos módulos de Odoo Community:

- `account` - Módulo base de contabilidad
- `l10n_ar` - Localización base de Argentina (debe estar instalado)
- `l10n_latam_base` - Base de localización latinoamericana (debe estar instalado)
- `l10n_latam_invoice_document` - Documentos de factura latinoamericanos (debe estar instalado)

Si alguno de estos módulos no está instalado, instálalos primero antes de instalar `l10n_ar_import_bill_ce`.

