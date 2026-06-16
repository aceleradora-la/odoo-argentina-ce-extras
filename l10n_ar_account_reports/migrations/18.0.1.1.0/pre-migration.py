import logging

_logger = logging.getLogger(__name__)

# La actividad AFIP se implementó primero como Char `l10n_ar_afip_activity_code`
# y luego pasó a Many2one `l10n_ar_afip_activity_id`. Limpiamos la columna Char
# huérfana en cuenta y compañía para no dejar restos en la base.
ORPHAN_COLUMNS = (
    ("account_account", "l10n_ar_afip_activity_code"),
    ("res_company", "l10n_ar_afip_activity_code"),
)


def migrate(cr, version):
    for table, column in ORPHAN_COLUMNS:
        cr.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        if cr.fetchone():
            cr.execute('ALTER TABLE "%s" DROP COLUMN "%s"' % (table, column))
            _logger.info("Columna huérfana %s.%s eliminada.", table, column)
