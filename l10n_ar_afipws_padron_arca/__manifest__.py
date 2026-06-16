{
    "name": "Padrón ARCA - getPersona_v2 (Community)",
    "version": "18.0.2.0.1",
    "category": "Localization/Argentina",
    "author": "Aceleradora LA",
    "website": "https://github.com/aceleradora-la/odoo-argentina-ce-extras",
    "license": "AGPL-3",
    "summary": "Actualiza el padrón AFIP/ARCA vía getPersona_v2: tipo de "
    "responsabilidad, provincia, actividades e impuestos. Corrige el casteo "
    "de campos many2one del wizard y aclara el toggle Mayúsculas / Nombre Propio.",
    "depends": [
        "l10n_ar_afipws",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/res_partner_view.xml",
        "views/res_partner_update_from_padron_wizard_view.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
