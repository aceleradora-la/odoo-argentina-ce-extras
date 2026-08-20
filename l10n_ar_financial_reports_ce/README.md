# Reportes Financieros Interactivos (Community)

Reportes contables estilo Enterprise para **Odoo 18 Community**, en pantalla
(componente OWL) en vez de exportar siempre a PDF:

- **Libro mayor de la empresa** (partner ledger): agrupado por contacto
  (con CUIT), columnas Diario / Cuenta / Fechas / Conciliación / Deber /
  Haber / Moneda del importe / Balance.
- **Libro mayor** (general ledger): agrupado por cuenta contable, con saldo
  inicial (las cuentas de resultado arrancan en el ejercicio fiscal).
- **Cuenta por cobrar vencida** y **Cuenta por pagar vencida**: antigüedad
  de saldos con tramos configurables (A la fecha / 1-30 / 31-60 / 61-90 /
  91-120 / Antiguos), según fecha límite o fecha de factura, a cualquier
  fecha de corte (reconstruye el residual con las conciliaciones parciales).

## Características

- Pantalla interactiva: encabezado y primera columna fijos, filas
  desplegables por grupo (carga lazy de apuntes), Desplegar/Plegar todo,
  buscador, mostrar/ocultar columnas.
- Filtros en vivo sin recargar: fechas, asientos registrados/todos, tipo de
  cuenta (libro mayor de la empresa), tramo de días y base de antigüedad
  (vencidas).
- Banner "Hay asientos contables sin registrar" cuando hay borradores en el
  período, como en Enterprise.
- Export **PDF** (QWeb apaisado) y **Excel** (xlsxwriter) opcionales, con o
  sin detalle de apuntes ("Detalle en PDF/Excel"), siempre desde la misma
  fuente de datos que la pantalla.
- Solo APIs de Community: `ir.actions.client` + OWL, `qweb-pdf`,
  `http.Controller` + `xlsxwriter`. Sin `account.report` (Enterprise).

## Requisitos

- Odoo 18 Community (`account`, `web`).
- `pip install xlsxwriter` (Excel).
- `wkhtmltopdf` (PDF).

## Uso

Contabilidad → Reportes: cada reporte abre un formulario de selección
(fechas, compañía, opciones) y "Ver Reporte" abre la pantalla interactiva.
Los menús requieren el grupo *Solo lectura contable* o superior.
