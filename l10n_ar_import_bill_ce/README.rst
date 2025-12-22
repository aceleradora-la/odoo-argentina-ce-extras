==========================================
Argentinian Importing Bills from ARCA
==========================================

Este módulo permite importar facturas desde archivos Excel exportados desde ARCA/AFIP.

Versión Community
=================

Esta es la versión adaptada para Odoo Community 17.0. Las principales diferencias con la versión Enterprise son:

1. **Dependencias**: 
   - Reemplaza `account_accountant` (Enterprise) por `account` (Community)
   - Elimina la dependencia de `account_invoice_tax` (no disponible en Community)

2. **Funcionalidad de importación**:
   - En lugar de usar el método `create_document_from_attachment` de Enterprise, se agregó un botón "Importar Facturas desde Excel" en la vista del diario
   - Se creó un wizard adicional (`afip.import.wizard.upload`) para subir el archivo Excel

3. **Manejo de impuestos**:
   - Los "Otros Tributos" se agregan directamente como líneas de impuesto en la factura, sin usar el wizard `account.invoice.tax` que no está disponible en Community

Uso
===

1. Ir a Contabilidad > Configuración > Diarios
2. Seleccionar un diario de compras o ventas (no POS)
3. Hacer clic en el botón "Importar Facturas desde Excel"
4. Seleccionar el archivo Excel exportado desde ARCA/AFIP
5. Revisar las facturas a importar en el wizard
6. Confirmar la importación

Requisitos
==========

- Odoo 17.0 o 18.0 Community Edition
- Módulos base de localización argentina: `l10n_ar`, `l10n_latam_base`, `l10n_latam_invoice_document`
- Empresa argentina con responsabilidad AFIP tipo 1

Autor
=====

ADHOC SA

Licencia
========

AGPL-3

