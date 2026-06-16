{
    "name": "Padrón ARCA - Fix actualización (Community)",
    "version": "18.0.1.0.0",
    "category": "Localization/Argentina",
    "author": "Aceleradora LA",
    "website": "https://github.com/aceleradora-la/odoo-argentina-ce-extras",
    "license": "AGPL-3",
    "summary": "Corrige la actualización desde Padrón AFIP/ARCA: persiste el tipo "
    "de responsabilidad y la provincia (campos many2one), y aclara el toggle "
    "Mayúsculas / Nombre Propio.",
    "depends": [
        "l10n_ar_afipws",
    ],
    "data": [
        "views/res_partner_update_from_padron_wizard_view.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
