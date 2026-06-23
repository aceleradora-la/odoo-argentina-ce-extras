{
    "name": "Padrón ARCA - getPersona_v2 (Community)",
    "version": "19.0.4.2.0",
    "category": "Localization/Argentina",
    "author": "Aceleradora LA",
    "website": "https://github.com/aceleradora-la/odoo-argentina-ce-extras",
    "license": "AGPL-3",
    "summary": "Actualiza el padrón AFIP/ARCA vía getPersona_v2: tipo de "
    "responsabilidad, provincia, actividades, impuestos, IVA, ganancias, "
    "monotributo y estado. Corrige el casteo de campos del wizard y aclara el "
    "toggle Mayúsculas / Nombre Propio. Reusa los modelos de l10n_ar_ux.",
    "depends": [
        "l10n_ar_afipws",
        "l10n_ar_ux",
    ],
    "data": [
        "views/res_partner_update_from_padron_wizard_view.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
