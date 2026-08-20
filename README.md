# Odoo Argentina CE Extras

Repositorio de módulos adicionales para Odoo Community Edition - Localización Argentina

## Estructura del repositorio

Este repositorio sigue la misma estructura que `odoo-argentina-ee`, con ramas por versión:
- `17.0` - Módulos para Odoo Community 17.0
- `18.0` - Módulos para Odoo Community 18.0
- `main` - Rama principal (sin módulos, solo documentación)

## Módulos disponibles

### l10n_ar_import_bill_ce

Módulo para importar facturas desde archivos Excel exportados desde ARCA/AFIP, adaptado para Odoo Community Edition.

**Versiones disponibles:**
- Odoo 17.0 Community: rama `17.0`
- Odoo 18.0 Community: rama `18.0`

Ver la documentación en [l10n_ar_import_bill_ce/README.rst](l10n_ar_import_bill_ce/README.rst)

### l10n_ar_financial_reports_ce

Reportes financieros interactivos estilo Enterprise para Odoo Community: Libro mayor de la empresa, Libro mayor, Cuenta por cobrar vencida y Cuenta por pagar vencida, en pantalla (OWL) con filas desplegables y filtros en vivo, más export opcional a PDF y Excel.

**Versiones disponibles:**
- Odoo 17.0 Community: rama `17.0`
- Odoo 18.0 Community: rama `18.0`
- Odoo 19.0 Community: rama `19.0`

Ver la documentación en [l10n_ar_financial_reports_ce/README.md](l10n_ar_financial_reports_ce/README.md)

## Instalación

1. Clonar este repositorio y cambiar a la rama correspondiente:
   ```bash
   git clone https://github.com/aceleradora-la/odoo-argentina-ce-extras.git
   cd odoo-argentina-ce-extras
   git checkout 17.0  # o 18.0 según tu versión de Odoo
   ```

2. Agregar la ruta al repositorio en tu configuración de Odoo
3. Actualizar la lista de aplicaciones
4. Instalar el módulo deseado

## Requisitos

- Odoo 17.0 o 18.0 Community Edition
- Módulos base de localización argentina (l10n_ar, l10n_ar_edi, etc.)

## Licencia

AGPL-3

## Autor

ADHOC SA

