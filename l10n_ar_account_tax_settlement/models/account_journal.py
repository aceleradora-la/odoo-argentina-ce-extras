# from odoo.tools.misc import formatLang
# from odoo.tools import DEFAULT_SERVER_DATE_FORMAT
import re
import unicodedata

from odoo import _, fields, models
from odoo.exceptions import RedirectWarning, ValidationError
from odoo.tools import ustr
from odoo.tools.float_utils import float_round
from odoo.tools.safe_eval import safe_eval
import logging

_logger = logging.getLogger(__name__)

#########
# helpers
#########


def format_amount(amount, padding=15, decimals=2, sep=""):
    if amount < 0:
        template = "-{:0>%dd}" % (padding - 1 - len(sep))
    else:
        template = "{:0>%dd}" % (padding - len(sep))
    res = template.format(int(round(abs(amount) * 10**decimals, decimals)))
    if sep:
        res = f"{res[:-decimals]}{sep}{res[-decimals:]}"
    return res


def get_line_tax_base(move_line):
    return sum(move_line.move_id.line_ids.filtered(lambda x: move_line.tax_line_id in x.tax_ids).mapped("balance"))


def get_pos_and_number(full_number):
    """
    Para un numero nos fijamos si hay '-', si hay:
    * mas de 1, entonces devolvemos error
    * 1, entonces devolvemos las partes (solo parte númerica)
    * 0, entonces devolvemos '0' y parte númerica del número que se pasó
    """
    args = full_number.split("-")
    if len(args) == 1:
        # si no hay '-' tomamos punto de venta 0
        return ("0", re.sub("[^0-9]", "", args[0]))
    else:
        return re.sub("[^0-9]", "", args[0]), re.sub("[^0-9]", "", "".join(args[1:]))


def remove_accents_and_dieresis(input_str):
    """Suboptimal-but-better-than-nothing way to replace accented or dieresis-containing
    latin letters by an ASCII equivalent."""
    input_str = ustr(input_str)
    nkfd_form = unicodedata.normalize("NFKD", input_str)
    return "".join([c for c in nkfd_form if not unicodedata.combining(c)])


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def _get_tax_code(self, tax, line=None):
        """
        Obtiene el código del impuesto de forma compatible con Community Edition.
        Intenta obtener el código desde diferentes fuentes:
        1. tax.l10n_ar_code (si existe en Enterprise)
        2. line.withholding_id.tax_id.l10n_ar_code (si hay withholding)
        3. line.payment_id.tax_withholding_id.codigo_regimen (si hay payment con withholding)
        """
        # Intentar obtener desde el campo directo (Enterprise)
        if hasattr(tax, 'l10n_ar_code') and tax.l10n_ar_code:
            return tax.l10n_ar_code
        
        # Si hay una línea, intentar obtener desde withholding
        if line:
            # Desde withholding_id (l10n_ar.payment.withholding)
            if hasattr(line, 'withholding_id') and line.withholding_id:
                withholding_tax = line.withholding_id.tax_id
                if withholding_tax and hasattr(withholding_tax, 'l10n_ar_code') and withholding_tax.l10n_ar_code:
                    return withholding_tax.l10n_ar_code
            
            # Desde payment_id.tax_withholding_id (account.tax con codigo_regimen)
            if hasattr(line, 'payment_id') and line.payment_id:
                payment = line.payment_id
                if hasattr(payment, 'tax_withholding_id') and payment.tax_withholding_id:
                    withholding_tax = payment.tax_withholding_id
                    # Intentar codigo_regimen (Community)
                    if hasattr(withholding_tax, 'codigo_regimen') and withholding_tax.codigo_regimen:
                        return withholding_tax.codigo_regimen
                    # Intentar l10n_ar_code si existe
                    if hasattr(withholding_tax, 'l10n_ar_code') and withholding_tax.l10n_ar_code:
                        return withholding_tax.l10n_ar_code

        return False

    def _get_tax_jurisdiction_code(self, tax):
        """Código de jurisdicción (Convenio Multilateral) del impuesto, vía
        `l10n_ar_state_id` (aportado por l10n_ar_withholding + l10n_ar_ux).
        Ese módulo puede no estar instalado, o alguno de sus campos puede no
        existir según la versión: usamos hasattr para no romper con
        AttributeError, igual que _get_tax_code. Devuelve False si no hay
        dato disponible."""
        state = getattr(tax, "l10n_ar_state_id", False)
        if not state:
            return False
        return getattr(state, "jurisdiction_code", False) or False

    settlement_tax = fields.Selection(
        [
            ("vat", "IVA"),
            ("profits", "Ganancias"),
            ("misiones", "TXT IIBB aplicado DGR Misiones"),
            ("sicore_aplicado", "TXT SICORE Aplicado"),
            ("iibb_sufrido", "TXT IIBB p/ SIFERE"),
            (
                "iibb_aplicado",
                "TXT Perc/Ret IIBB aplicadas ARBA: Percepciones ( excepto actividad 29, 7 quincenal, 7 y 17 de Bancos)",
            ),
            (
                "iibb_aplicado_act_7",
                "TXT Perc/Ret IIBB aplicadas ARBA: Percepciones Act. 7 método Percibido (quincenal)",
            ),
            ("iibb_aplicado_agip", "TXT Perc/Ret IIBB aplicadas AGIP"),
            ("iibb_aplicado_api", "TXT Perc/Ret IIBB aplicadas API"),
            ("iibb_aplicado_sircar", "TXT Perc/Ret IIBB aplicadas SIRCAR"),
            ("iibb_aplicado_dgr_mendoza", "TXT  Perc/Ret IIBB aplicado DGR Mendoza"),
            ("retenciones_iva", "TXT Retenciones/Percepciones Sufridas IVA"),
        ],
        string="Impuesto a liquidar",
    )

    # Gate field; mirrors the Enterprise account_tax_settlement design.
    # The actual settlement type lives in `settlement_tax` only.
    tax_settlement = fields.Selection(
        [
            ("yes", "Sí"),
            ("allow_per_line", "Sí, permitir por línea"),
        ],
        string="Liquidación de impuestos",
    )

    # Tags que este diario liquida. Equivalente al campo del módulo Enterprise:
    # cada diario define qué etiquetas de impuesto liquida (en lugar de un
    # mapeo hardcodeado). Las líneas a liquidar se filtran por estos tags.
    settlement_account_tag_ids = fields.Many2many(
        "account.account.tag",
        "account_journal_account_tag",
        string="Etiquetas para liquidación",
        domain=[("applicability", "=", "taxes")],
    )

    # Campos adicionales para liquidación
    settlement_partner_id = fields.Many2one(
        "res.partner",
        string="Contacto de liquidación",
        help="Partner para liquidación de impuestos",
        check_company=True,
    )

    settlement_account_id = fields.Many2one(
        "account.account",
        string="Cuenta de contrapartida",
        help="Cuenta de contrapartida para liquidación de impuestos",
        check_company=True,
    )

    def iibb_aplicado_dgr_mendoza_files_values(self, move_lines):
        self.ensure_one()
        ret = ""
        for line in move_lines:
            # Agente de Retención del Impuesto sobre los Ingresos Brutos

            partner = line.partner_id
            payment = line.payment_id
            move = line.move_id

            tax = line._get_settlement_tax()
            if not payment:
                continue

            # Campo 1: CUIT char(13). CUIT del Sujeto retenido o percibido. Ejemplo: 20-10111222-3
            # Example "30-58710878-6"
            partner.ensure_vat()
            content = partner.l10n_ar_formatted_vat
            # Campo 2: Denominación char(80). Apellido y Nombre o Razón Social. Formato: 80 posiciones, se completa con
            # blancos a la derecha.
            # Example "ELECTRICIDAD MAZA SRL                                                           "
            content += f"{partner.name:80.80}"

            # Campo 3: Fecha Comprobante char(8). Fecha del Comprobante de Retención/Percepción según Res.40/2012 (ddmmaaaa)
            # Example s"16052020"
            content += fields.Date.from_string(move.date).strftime("%d%m%Y")

            # Campo 4: Comprobante char(12)- Número de Comprobante de Retención/Percepción según Res.40/2012.
            # Formato: 999999999999 (rellenar con ceros (0) a la izquierda) Ejemplo: 000000001521
            # Example "000000027860"
            content += (line.withholding_id.name or "").rjust(12, "0")[:12]  # we are forcing 12 first numbers always.

            # Campo 5: Fecha Ret./Perc. char(8)- Fecha de efectuada la retención / percepción (ddmmaaaa)
            # Example "16052020"
            content += fields.Date.from_string(payment.date).strftime("%d%m%Y")

            # Campo 6. Base Imponible char(15). Formato: 999999999999.99 (doce enteros, punto decimal y dos decimales,
            # dejando espacios en blanco a izquierda para completar las 15 posiciones). Ejemplo: "         345.21"
            # Example "000000027229.33"
            content += "%15.2f" % line.withholding_id.base_amount

            # Campo 7: Alícuota char(5). Alícuota para la retención y/o percepción. Formato: 99.99 (dos enteros,
            # punto decimal y dos decimales. Ejemplo: " 3.00"
            # Example "03.00"
            content += "%5.2f" % tax.amount

            # Campo 8: Importe Ret./Perc. char(15). Importe retenido y/o percibido. Formato: 999999999999.99 (doce enteros,
            # punto decimal y dos decimales, dejando espacios en blanco a izquierda para completar las 15 posiciones).
            # Ejemplo: "          34.50" "000000000816.88"
            content += "%15.2f" % -line.balance

            content += "\r\n"
            ret += content

        # File name
        move_line = move_lines and move_lines[0] or self.env["account.move.line"]
        tipo_agente = "rr"  # This value is fixed just because we are doing the retention txt, when adding the
        # perception we need to change it
        cuit = move_line.company_id.vat
        periodo = fields.Date.from_string(move_line.date).strftime("%Y") or ""  # 'pppp' AÑO '2020'
        cuota = fields.Date.from_string(move_line.date).strftime("%m") or ""  # 'cc'
        return [
            {
                "txt_filename": "%s%s%s%s.txt" % (tipo_agente, cuit, periodo, cuota),
                "txt_content": ret,
            }
        ]

    def _get_perception_original_invoice_number(self, line):
        self.ensure_one()
        res = ""
        related_invoice = line.move_id._found_related_invoice() or line.move_id
        letter = related_invoice.l10n_latam_document_type_id.l10n_ar_letter
        internal_type = related_invoice.l10n_latam_document_type_id.internal_type

        # 2 Tipo de comprobante
        if internal_type == "invoice":
            document_type = letter == "E" and 5 or 1
        elif internal_type == "credit_note":
            document_type = letter == "E" and 106 or 102
        elif internal_type == "debit_note":
            document_type = letter == "E" and 6 or 2
        elif related_invoice.move_type == "out_invoice":
            document_type = 20
        elif related_invoice.move_type == "out_refund":
            document_type = 120
        else:
            raise ValidationError(_("Tipo de comprobante no reconocido"))
        res += str(document_type)[:1]

        # 3 Letra del comprobante
        res += letter

        # 4 Número del comprobante
        res += "%012d" % int(re.sub("[^0-9]", "", related_invoice.l10n_latam_document_number or ""))
        return res

    def iibb_aplicado_api_files_values(self, move_lines):
        """Implementado segun especificación en carpeta doc de este repo"""

        def format_amount(amount, integers, decimals=2):
            # overwrite default format_amount
            template = "%0" + "%ss" % (integers + decimals + 1)
            # TODO se podria mejorar haciendo algo asi pero hace falta
            # hacer parametro el 16
            # "{0:>16.2f}".format(12.1)
            return template % f"{round(amount, decimals):.2f}".replace(".", ",")

        self.ensure_one()
        ret = ""
        perc = ""

        for line in move_lines:
            partner = line.partner_id

            tax = line._get_settlement_tax()

            # 1 - tipo de operacion
            if tax.type_tax_use in ["sale", "purchase"]:
                content = "2"

                # para percepciones ho es obligatorio
                articulo_inciso_calculo = tax.api_articulo_inciso_calculo_percepcion or "000"
                articulo_inciso_retiene = tax.api_codigo_articulo_percepcion
            elif tax.l10n_ar_withholding_payment_type in ["customer", "supplier"]:
                content = "1"

                articulo_inciso_calculo = tax.api_articulo_inciso_calculo_retencion
                articulo_inciso_retiene = tax.api_codigo_articulo_retencion
            else:
                raise ValidationError(_("Tipo de impuesto %s equivocado") % (tax.tax_group_id.name))

            if not articulo_inciso_calculo or not articulo_inciso_retiene:
                raise RedirectWarning(
                    message=_(
                        'Debe establecer la información de "artículo/inciso" en la configuración del impuesto "%s"'
                        'en la solapa "API".',
                        tax.name,
                    ),
                    action={
                        "type": "ir.actions.act_window",
                        "res_model": "account.tax",
                        "views": [(False, "form")],
                        "res_id": tax.id,
                        "name": _("Tax"),
                        "view_mode": "form",
                    },
                    button_text=_("Edit Tax"),
                )

            # 2 - fecha
            content += fields.Date.from_string(line.date).strftime("%d/%m/%Y")

            # 3 - Código de artículo Inciso por el que retiene
            content += articulo_inciso_retiene

            # 4 - tipo de comprobante y
            # 5 - letra de comprobante
            internal_type = line.l10n_latam_document_type_id.internal_type
            # No se si esto es correcto en 17: si no tiene internal type entonces es pago
            if internal_type:
                move = line.move_id

            if internal_type and internal_type == "invoice":
                # factura
                content += "01" + line.l10n_latam_document_type_id.l10n_ar_letter

            elif internal_type and internal_type == "debit_note":
                # ND
                content += "02" + line.l10n_latam_document_type_id.l10n_ar_letter
            elif internal_type and internal_type == "credit_note":
                content += "10" + line.l10n_latam_document_type_id.l10n_ar_letter
            else:
                # orden de pago (sin letra)
                # 09 sería otro comprobante y 10 reinitegro de perc/ret
                # aclaración: si cargo una nota de crédito con código 10 me aparece un mensaje como este:
                # "Error: Línea 25: Debe ingresar un tipo de comprobante válido.
                # La carga de Reintegro de Retenc./Perc solo se puede efectuar desde el formulario en forma manual. La línea fue descartada."
                content += "03 "

            # 6 - numero comprobante Texto(16)
            if internal_type and internal_type in ("invoice", "credit_note", "debit_note"):
                # TODO el aplicativo deberia empezar a aceptar 5 digitos
                pos, number = get_pos_and_number(move.l10n_latam_document_number)
                # versión 4.0 de siprib release 0 no acepta 5 dígitos aún
                content += f"{pos:>03s}"[-4:]
                content += f"{number:>08s}"
                content += "    "
            else:
                content += "%016s" % (line.withholding_id.name or "")

            # 7 - fecha comprobante
            content += fields.Date.from_string(line.date).strftime("%d/%m/%Y")

            # 8 - monto comprobante
            content += (
                format_amount(abs(line.move_id.amount_total_signed), 12, 2)
                if line.move_id.is_invoice()
                else format_amount(abs(-line.balance), 12, 2)
            )

            # 9 - tipo de documento
            # nosotros solo permitimos CUIT por ahora
            # Revisar
            content += "3"

            # 10 - numero de documento
            content += partner.ensure_vat()

            # 11 - Condición frente a Ingresos Brutos
            # 1 es inscripto, 2 no inscripto con oblig. a insc y 3 no insc sin
            # oblig a insc. TODO implementar 2
            gross_income_type = partner.l10n_ar_gross_income_type
            if not gross_income_type:
                raise ValidationError(
                    _('Debe setear el tipo de inscripción de IIBB del partner "%s" (id: %s)')
                    % (partner.name, partner.id)
                )
            if gross_income_type in ["multilateral", "local"]:
                content += "1"
            else:
                content += "3"

            # 12 - Número de Inscripción en Ingresos Brutos
            content += (re.sub("[^0-9]", "", partner.l10n_ar_gross_income_number or "")).rjust(10, "0")

            # 13 - Situación frente a IVA donde:
            # ri (1), rni (2), exento (3), monotr (4)
            res_iva = partner.l10n_ar_afip_responsibility_type_id
            if res_iva.code in ["1", "1FM"]:
                # RI
                content += "1"
            elif res_iva.code == "2":
                # RNI
                content += "2"
            elif res_iva.code == "4":
                # EXENTO
                content += "3"
            elif res_iva.code == "6":
                # MONOT
                content += "4"
            else:
                raise ValidationError(
                    _('La responsabilidad frente a IVA "%s" no está soportada para ret/perc Santa Fe') % res_iva.name
                )

            # 14 - Marca inscripción Otros Gravámenes
            # TODO implementar (requiere nuevo campo en odoo?)
            content += "0"

            # 15 - Marca Inscripción DREI
            # TODO revisar si implementamos o no, aparentemente este campo
            # activo en drei no se usa o no es lo que esperamos, por ahora
            # no lo hacemos requerido para no andar molestando al dope
            # if not partner.drei:
            #     raise ValidationError(_(
            #         'Debe seleccionar situación DREI para partner '
            #         '"%s" (id: %s)') % (
            #             partner.name, partner.id))
            content += partner.drei == "activo" and "1" or "0"

            # 16 - Importe Otros Gravámenes
            # TODO implementar
            content += format_amount(0.0, 10, 2)

            # 17 - Importe IVA (solo si factura)
            if line.move_id.is_invoice():
                amounts = line.move_id._l10n_ar_get_amounts(company_currency=True)
                vat_amount = amounts["vat_amount"]
                base_amount = amounts["vat_taxable_amount"]
            else:
                vat_amount = 0.0
                base_amount = line.payment_id and line.withholding_id.base_amount or 0.0
            content += format_amount(vat_amount, 10, 2)

            # 18 - Base Imponible para el cálculo
            # tal vez la base deberiamos calcularlo asi, en pagos no porque
            # los asientos estan separados
            # content += format_amount(-get_line_tax_base(line), 12, 2, ',')
            content += format_amount(base_amount, 12, 2)

            # 19 - Alícuota / alicuota
            content += format_amount(tax.amount, 2, 2)

            # 20 - Impuesto Determinado
            content += format_amount(abs(-line.balance), 12, 2)

            # 21 - Derecho Registro e Inspección
            # TODO implementar
            # es un importe seguramente importe retenido de drei
            content += format_amount(0.0, 9, 2)

            # 22 - Monto Retenido
            # TODO por ahora es igual a impuesto determinado pero, podria ser
            # distinto en algún caso?
            content += format_amount(abs(-line.balance), 12, 2)

            # 23 - Artículo/Inciso para el cálculo
            content += articulo_inciso_calculo

            # 24 - Tipo de Exención
            # TODO implementar. Por ahora no implementamos excenciones ya que
            # a priori no las informan
            content += "0"

            # 25 - Año de Exención
            # TODO implementar
            content += "0000"

            # 26 - Número de Certificado de Exención
            # TODO implementar
            content += "      "

            # 27 - Número de Certificado Propio
            # TODO implementar
            content += "            "

            # new line
            content += "\r\n"

            if tax.type_tax_use in ["sale", "purchase"]:
                perc += content
            elif tax.l10n_ar_withholding_payment_type in ["customer", "supplier"]:
                ret += content

        return [
            {
                "txt_filename": "Perc/Ret IIBB API Aplicadas.txt",
                "txt_content": perc + ret,
            }
        ]

    def iibb_aplicado_sircar_files_values(self, move_lines):
        """Percepciones/Retenciones de IIBB aplicadas bajo SIRCAR (Sistema de
        Recaudación y Control de Agentes de Retención - Comisión Arbitral),
        portado 1:1 desde l10n_ar_account_reports (Enterprise, ingadhoc):
        https://github.com/ingadhoc/odoo-argentina-ee/blob/47fbbde/l10n_ar_account_reports/models/sircar_report.py

        Clasificación (EE usa 2 dominios/botones separados; acá recibimos un
        único `move_lines` ya filtrado por los tags del diario y lo separamos
        igual): retención si l10n_ar_withholding_payment_type == 'supplier',
        percepción si type_tax_use == 'sale'.
        """
        self.ensure_one()

        ret_lines = self.env["account.move.line"]
        perc_lines = self.env["account.move.line"]
        for line in move_lines:
            tax = line._get_settlement_tax()
            if tax.l10n_ar_withholding_payment_type == "supplier":
                ret_lines |= line
            elif tax.type_tax_use == "sale":
                perc_lines |= line
            else:
                raise ValidationError(
                    _("El impuesto '%s' no es percepción ni retención: no se puede incluir en SIRCAR.")
                    % tax.name
                )

        files = []
        if ret_lines:
            files.append(
                {
                    "txt_filename": "SIRCAR_Retenciones_Aplicadas.txt",
                    "txt_content": self._sircar_txt_content(ret_lines, "ret"),
                }
            )
        if perc_lines:
            files.append(
                {
                    "txt_filename": "SIRCAR_Percepciones_Aplicadas.txt",
                    "txt_content": self._sircar_txt_content(perc_lines, "perc"),
                }
            )
        return files

    def _sircar_txt_content(self, move_lines, file_type):
        lines = []
        line_nbr = 1
        if file_type == "ret":
            for line in move_lines.filtered("amount_currency").sorted(key=lambda r: (r.date, r.id)):
                tax = line._get_settlement_tax()
                alicuot = tax.amount
                internal_type = line.l10n_latam_document_type_id.internal_type

                content = ["%05d" % line_nbr]  # 1: Número de renglón (único por archivo)
                content.append("1")  # 2: Origen del comprobante
                # 3: Tipo del comprobante
                content.append("1" if line.payment_id.payment_type == "outbound" else "2")
                # 4: Número del comprobante
                content.append("%012d" % int(re.sub("[^0-9]", "", line.payment_id.name or "0")))
                # 5: CUIT del contribuyente
                content.append(line.partner_id.ensure_vat())
                # 6: Fecha de la percepción/retención
                content.append(fields.Date.from_string(line.date).strftime("%d/%m/%Y"))
                # 7: Monto sujeto a percepción/retención
                content.append(format_amount(line._l10n_ar_withholding_data()[1], 12, 2, "."))
                # 8: Alícuota
                content.append(format_amount(alicuot, 6, 2, "."))
                # 9: Monto retenido
                content.append(format_amount(-line.balance, 12, 2, "."))
                # 10: Código de régimen (según tabla de la jurisdicción)
                codigo_regimen = self._get_tax_code(tax, line)
                if not codigo_regimen:
                    raise ValidationError(
                        _("No hay código de régimen configurado para el impuesto '%s'.") % tax.name
                    )
                content.append(codigo_regimen)
                # 11: Jurisdicción (código Convenio Multilateral)
                jurisdiction_code = self._get_tax_jurisdiction_code(tax)
                if not jurisdiction_code:
                    raise ValidationError(
                        _('El impuesto "%s" no tiene jurisdicción configurada, o la jurisdicción no tiene código.')
                        % tax.name
                    )
                content.append(jurisdiction_code)

                if jurisdiction_code in ("904", "914"):  # Córdoba
                    # 12: Tipo de operación (1-Efectuada, 2-Anulada, 3-Omitida)
                    content.append("2" if internal_type == "supplier_payment" else "1")
                    # 13: Fecha de emisión de constancia
                    content.append(fields.Date.from_string(line.date).strftime("%d/%m/%Y"))
                    # 14: Número de constancia
                    certificado = line._l10n_ar_withholding_data()[0]
                    content.append("%014s" % int(re.sub("[^0-9]", "", certificado or "0")[:14] or "0"))
                    # 15: Número de constancia original (solo anulaciones)
                    reconciled_bills = line.payment_id.reconciled_bill_ids
                    original_invoice = reconciled_bills.reversed_entry_id or line.move_id
                    content.append(
                        "%014d" % int(re.sub("[^0-9]", "", original_invoice.name or "0"))
                        if internal_type == "supplier_payment"
                        else "%014d" % 0
                    )
                lines.append(",".join(content) + "\r\n")
                line_nbr += 1
        else:
            for line in move_lines.filtered("amount_currency").sorted(key=lambda r: (r.date, r.id)):
                tax = line._get_settlement_tax()
                alicuot = tax.amount
                internal_type = line.l10n_latam_document_type_id.internal_type
                letter = line.l10n_latam_document_type_id.l10n_ar_letter

                content = ["%05d" % line_nbr]  # 1: Número de renglón
                # 2: Tipo de comprobante
                if internal_type == "invoice":
                    tipo_comprobante = 5 if letter == "E" else 1
                elif internal_type == "credit_note":
                    tipo_comprobante = 106 if letter == "E" else 102
                elif internal_type == "debit_note":
                    tipo_comprobante = 6 if letter == "E" else 2
                elif line.move_id.move_type == "out_invoice":
                    tipo_comprobante = 20
                elif line.move_id.move_type == "out_refund":
                    tipo_comprobante = 120
                else:
                    raise ValidationError(_("Tipo de comprobante no reconocido para SIRCAR."))
                content.append("%03d" % tipo_comprobante)
                # 3: Letra del comprobante
                content.append(letter or "")
                # 4: Número del comprobante
                content.append("%012d" % int(re.sub("[^0-9]", "", line.move_id.l10n_latam_document_number or "0")))
                # 5: CUIT del contribuyente
                content.append(line.partner_id.ensure_vat())
                # 6: Fecha de la percepción
                content.append(fields.Date.from_string(line.date).strftime("%d/%m/%Y"))
                # 7: Monto sujeto a percepción
                content.append(format_amount(abs(get_line_tax_base(line)), 12, 2, "."))
                # 8: Alícuota
                content.append(format_amount(alicuot, 6, 2, "."))
                # 9: Monto percibido
                content.append(format_amount(abs(line.balance), 12, 2, "."))
                # 10: Código de régimen (según tabla de la jurisdicción)
                codigo_regimen = self._get_tax_code(tax, line)
                if not codigo_regimen:
                    raise ValidationError(
                        _("No hay código de régimen configurado para el impuesto '%s'.") % tax.name
                    )
                content.append(codigo_regimen)
                # 11: Jurisdicción (código Convenio Multilateral)
                jurisdiction_code = self._get_tax_jurisdiction_code(tax)
                if not jurisdiction_code:
                    raise ValidationError(
                        _('El impuesto "%s" no tiene jurisdicción configurada, o la jurisdicción no tiene código.')
                        % tax.name
                    )
                content.append(jurisdiction_code)

                if jurisdiction_code in ("904", "914"):  # Córdoba
                    # 12: Tipo de operación (1-Efectuada, 2-Anulada, 3-Omitida, 4-Informativa)
                    content.append("2" if internal_type == "credit_note" else "1")
                    # 13: Número de constancia original (solo anulaciones)
                    content.append(
                        self._get_perception_original_invoice_number(line)
                        if internal_type == "credit_note"
                        else "%014d" % 0
                    )
                lines.append(",".join(content) + "\r\n")
                line_nbr += 1

        return "".join(lines)

    def retenciones_iva_files_values(self, move_lines):
        """TXT de Retenciones/Percepciones de IVA sufridas, portado desde
        l10n_ar_account_reports (Enterprise, ingadhoc):
        https://github.com/ingadhoc/odoo-argentina-ee/blob/47fbbde/l10n_ar_account_reports/models/l10n_ar_vat_ret_perc_sufrido.py

        EE genera 2 archivos separados (botones "Retenciones IVA sufridas" /
        "Percepciones IVA sufridas": son 2 casilleros distintos en el Portal
        ARCA). Acá recibimos un único `move_lines` ya filtrado por los tags
        del diario y lo separamos igual: retención sufrida si
        l10n_ar_withholding_payment_type == 'customer' (pago cobrado);
        percepción sufrida si no (factura de compra).
        """
        self.ensure_one()

        ret_lines = self.env["account.move.line"]
        perc_lines = self.env["account.move.line"]
        for line in move_lines:
            tax = line._get_settlement_tax()
            if tax.l10n_ar_withholding_payment_type == "customer":
                ret_lines |= line
            else:
                perc_lines |= line

        ret_content = ""
        for line in ret_lines.filtered("amount_currency").sorted(key=lambda r: (r.date, r.id)):
            payment = line.payment_id
            certificado, _base = line._l10n_ar_withholding_data()
            withholding_tax = line._get_settlement_tax()
            codigo_regimen = self._get_tax_code(withholding_tax, line)
            if not codigo_regimen or len(codigo_regimen) < 3:
                raise ValidationError(
                    _("El impuesto '%s' necesita un código de régimen de al menos 3 dígitos.")
                    % withholding_tax.name
                )
            ret_content += codigo_regimen[:3]
            ret_content += payment.partner_id.ensure_vat()
            ret_content += fields.Date.from_string(payment.date).strftime("%d/%m/%Y")
            ret_content += re.sub(r"[^0-9\.]", "", certificado or "").ljust(16, "0")
            ret_content += "%016.2f" % line.balance
            ret_content += "\r\n"

        perc_content = ""
        for line in perc_lines.filtered("amount_currency").sorted(key=lambda r: (r.date, r.id)):
            tax = line._get_settlement_tax()
            codigo_regimen = self._get_tax_code(tax, line)
            if not codigo_regimen or len(codigo_regimen) < 3:
                raise ValidationError(
                    _("El impuesto '%s' necesita un código de régimen de al menos 3 dígitos.") % tax.name
                )
            perc_content += codigo_regimen[:3]
            perc_content += line.move_id.partner_id.ensure_vat()
            perc_content += fields.Date.from_string(line.move_id.invoice_date).strftime("%d/%m/%Y")
            perc_content += (line.move_id.l10n_latam_document_number or "").ljust(16)
            perc_content += "%16.2f" % line.balance
            perc_content += "\r\n"

        files = []
        if ret_content:
            files.append({"txt_filename": "Retenciones_IVA_Sufridas.txt", "txt_content": ret_content})
        if perc_content:
            files.append({"txt_filename": "Percepciones_IVA_Sufridas.txt", "txt_content": perc_content})
        return files

    def iibb_aplicado_agip_files_values(self, move_lines):  # noqa: C901
        """Ver readme del modulo para descripcion del formato. Tambien
        archivos de ejemplo en /doc
        """
        self.ensure_one()

        ret_perc = ""
        credito = ""

        company_currency = self.company_id.currency_id
        # Removed dependency checker logic since we assume it's there or handle failures gracefully
        backward_comp_is_installed = False # self.env["ir.module.module"].search(
        #    [("name", "=", "l10n_ar_tax_settlement_backward_comp"), ("state", "=", "installed")]
        # )
        for line in move_lines.filtered("amount_currency").sorted("date"):
            # pay_group = payment.payment_group_id
            move = line.move_id
            payment = line.payment_id
            # implementamos esto que teniamos en agip para obtener alicuota de rectificativa
            date = line.move_id._found_related_invoice().date or line.date
            tax = line._get_settlement_tax(date=date)
            partner = line.partner_id
            internal_type = line.l10n_latam_document_type_id.internal_type

            if not partner.vat:
                raise ValidationError(
                    _('El partner "%s" (id %s) no tiene número de identificación establecido')
                    % (partner.name, partner.id)
                )
            alicuot = tax.amount

            ret_perc_applied = False
            es_percepcion = False
            # 1 - Tipo de Operación
            if tax.type_tax_use in ["sale", "purchase"]:
                # tax.amount_type == 'partner_tax':
                es_percepcion = True
                content = "2"
            elif tax.l10n_ar_withholding_payment_type in ["customer", "supplier"]:
                # tax.withholding_type == 'partner_tax':
                content = "1"
            else:
                raise ValidationError(
                    _("El impuesto '%s' no es percepción ni retención: no se puede incluir en el TXT de AGIP.")
                    % tax.name
                )

            # notas de credito
            if internal_type == "credit_note":
                # 2 - Nro. Nota de crédito
                content += "%012d" % int(re.sub("[^0-9]", "", move.l10n_latam_document_number or ""))

                # 3 - Fecha Nota de crédito
                content += fields.Date.from_string(line.date).strftime("%d/%m/%Y")

                # 4 - Monto nota de crédito
                # TODO implementar devoluciones de pagos
                # content += format_amount(
                #     line.move_id.cc_amount_total, 16, 2, ',')
                # la especificacion no lo dice claro pero un errror al importar
                # si, lo que se espera es el importe base, ya que dice que
                # este, multiplicado por la alícuota, debe ser igual al importe
                # a retener/percibir
                taxable_amount = line.tax_base_amount
                content += format_amount(taxable_amount, 16, 2, ",")

                # 5 - Nro. certificado propio
                # opcional y el que nos pasaron no tenia
                content += "                "

                # segun interpretamos de los daots que nos pasaron 6, 7, 8 y 11
                # son del comprobante original
                or_inv = line.move_id._found_related_invoice()
                if not or_inv:
                    raise ValidationError(
                        _(
                            "No pudimos encontrar el comprobante original para %s "
                            '(id %s). Verifique que en la nota de crédito "%s", el'
                            " campo origen es el número de la factura original"
                        )
                        % (line.move_id.display_name, line.move_id.id, line.move_id.display_name)
                    )

                # 6 - Tipo de comprobante origen de la retención

                # Identificamos si el comprobante de origen es una Factura de credito MiPyMEs sino lo
                # tratamos como una factura normal
                # NOTA: Esto solo aplica para el calculo de Percepciones
                content += "10" if or_inv.l10n_latam_document_type_id.code in ["201", "206", "211"] else "01"

                # 7 - Letra del Comprobante
                if payment:
                    content += " "
                else:
                    content += or_inv.l10n_latam_document_type_id.l10n_ar_letter

                # 8 - Nro de comprobante (original)
                content += "%016d" % int(re.sub("[^0-9]", "", or_inv.l10n_latam_document_number or ""))

                # 9 - Nro de documento del Retenido
                content += str(partner._get_id_number_sanitize())

                # 10 - Código de norma
                # por ahora solo padron regimenes generales
                content += "029"

                # 11 - Fecha de retención/percepción
                content += fields.Date.from_string(or_inv.invoice_date).strftime("%d/%m/%Y")

                # 12 - Ret/percep a deducir

                # si la línea tiene moneda diferente de la moneda de la compañía queremos que la ret/perc
                # se calcule aplicando la alícuota sobre la base imponible en la moneda de la compañía
                if line.currency_id and line.currency_id != line.company_id.currency_id:
                    ret_perc_applied = float_round((taxable_amount * alicuot / 100), precision_digits=2)
                content += format_amount((line.balance if not ret_perc_applied else ret_perc_applied), 16, 2, ",")

                # 13 - Alícuota
                content += format_amount(alicuot, 5, 2, ",")

                content += "\r\n"

                credito += content
                continue

            # 2 - Código de Norma
            # por ahora solo padron regimenes generales
            content += "029"

            # 3 - Fecha de retención/percepción
            content += fields.Date.from_string(line.date).strftime("%d/%m/%Y")

            # 4 - Tipo de comprobante origen de la retención
            if internal_type == "invoice":
                content += "10" if line.move_id.l10n_latam_document_type_id.code in ["201", "206", "211"] else "01"
            elif internal_type == "debit_note":
                if es_percepcion:
                    content += "09"
                else:
                    content += "02"
            else:
                # orden de pago
                content += "03"

            # 5 - Letra del Comprobante
            # segun vemos en los archivos de ejemplo solo en percepciones
            if payment:
                content += " "
            else:
                content += line.l10n_latam_document_type_id.l10n_ar_letter if internal_type == "invoice" else " "

            # 6 - Nro de comprobante
            content += "%016d" % int(re.sub("[^0-9]", "", move.l10n_latam_document_number or ""))

            # 7 - Fecha del comprobante
            content += fields.Date.from_string(move.date).strftime("%d/%m/%Y")

            # obtenemos montos de los comprobantes
            if payment:
                # solo en comprobantes A, M segun especificacion
                vat_amount = 0.0
                # es lo mismo que payment_group.matched_amount_untaxed
                taxable_amount = float_round(line.withholding_id.base_amount, precision_digits=2)
                rounded_withholding = float_round((taxable_amount * alicuot / 100), precision_digits=2)
                # TODO en febrero 2026 sacar el if de abajo (más información en tarea 59174).
                # Hacer revert de https://github.com/ingadhoc/odoo-argentina-ee/pull/743 en febrero 2026
                total_amount = float_round(payment.move_id.amount_total_in_currency_signed, precision_digits=2)
                if rounded_withholding != -line.balance:
                    total_amount = float_round(total_amount + line.balance + rounded_withholding, precision_digits=2)
                if backward_comp_is_installed and payment.is_backward_withholding_payment:
                    # Buscamos los payments sin retención que vienen migrados de la versión anterior y le sumamos
                    # el amount total de los mismos (move_id.amount_total_in_currency_signed) al total_amount de la
                    # retención. Esto lo hacemos porque en la migración de 16 a 18 se migran los pagos y las retenciones
                    # por separado a diferencia de 16 que estaba todo en el mismo asiento.
                    related_payments = self.env["account.payment"].search(
                        [
                            ("name", "=", payment.name),
                            ("company_id", "=", payment.company_id.id),
                            ("partner_id", "=", payment.partner_id.id),
                            ("id", "!=", payment.id),
                            ("state", "in", ["paid", "in_process"]),
                        ]
                    )
                    if related_payments:
                        total_amount += float_round(
                            sum(related_payments.mapped("move_id.amount_total_in_currency_signed")), precision_digits=2
                        )

                # lo sacamos por diferencia
                other_taxes_amount = company_currency.round(total_amount - taxable_amount - vat_amount)
            elif line.move_id.is_invoice():
                amounts = line.move_id._l10n_ar_get_amounts(company_currency=True)
                # segun especificacion el iva solo se reporta para estos
                if line.l10n_latam_document_type_id.l10n_ar_letter in ["A", "M"]:
                    vat_amount = amounts["vat_amount"]
                else:
                    vat_amount = 0.0

                total_amount = (1 if line.move_id.is_inbound() else -1) * line.move_id.amount_total_signed

                # por si se olvidaron de poner agip en una linea de factura
                # la base la sacamos desde las lineas de impuesto
                # taxable_amount = line.move_id.cc_amount_untaxed
                taxable_amount = line.tax_base_amount

                # tambien lo sacamos por diferencia para no tener error (por el
                # calculo trucado de taxable_amount por ejemplo) y
                # ademas porque el iva solo se reporta si es factura A, M
                other_taxes_amount = company_currency.round(total_amount - taxable_amount - vat_amount)
                # other_taxes_amount = line.move_id.cc_other_taxes_amount
            else:
                raise ValidationError(_("El impuesto no está asociado"))

            # 8 - Monto del comprobante
            content += format_amount(total_amount, 16, 2, ",")

            # 9 - Nro de certificado propio
            content += (line.withholding_id.name or "").rjust(16, " ")

            # 10 - Tipo de documento del Retenido
            # vat
            if partner.l10n_latam_identification_type_id.name not in ["CUIT", "CUIL", "CDI"]:
                raise ValidationError(
                    _(
                        'EL el partner "%s" (id %s), el tipo de identificación'
                        "debe ser una de siguientes: CUIT, CUIL, CDI."
                    )
                    % (partner.id, partner.name)
                )
            doc_type_mapping = {"CUIT": "3", "CUIL": "2", "CDI": "1"}
            content += doc_type_mapping[partner.l10n_latam_identification_type_id.name]

            # 11 - Nro de documento del Retenido
            content += str(partner._get_id_number_sanitize())

            # 12 - Situación IB del Retenido
            # 1: Local 2: Convenio Multilateral
            # 4: No inscripto 5: Reg.Simplificado
            if not partner.l10n_ar_gross_income_type:
                raise ValidationError(
                    _('Debe setear el tipo de inscripción de IIBB del partner "%s" (id: %s)')
                    % (partner.name, partner.id)
                )

            # ahora se reportaria para cualquier inscripto el numero de cuit
            gross_income_mapping = {"local": "5", "multilateral": "2", "exempt": "4"}
            content += gross_income_mapping[partner.l10n_ar_gross_income_type]

            # 13 - Nro Inscripción IB del Retenido
            if partner.l10n_ar_gross_income_type == "exempt":
                content += "00000000000"
            else:
                content += partner.ensure_vat()

            # 14 - Situación frente al IVA del Retenido
            # 1 - Responsable Inscripto
            # 3 - Exento
            # 4 - Monotributo
            res_iva = partner.l10n_ar_afip_responsibility_type_id
            if res_iva.code in ["1", "1FM"]:
                # RI
                content += "1"
            elif res_iva.code == "4":
                # EXENTO
                content += "3"
            elif res_iva.code == "6":
                # MONOT
                content += "4"
            else:
                raise ValidationError(
                    _('La responsabilidad frente a IVA "%s" no está soportada para ret/perc AGIP') % res_iva.name
                )

            # 15 - Razón Social del Retenido
            content += f"{partner.name:30.30}"

            # 16 - Importe otros conceptos
            content += format_amount(other_taxes_amount, 16, 2, ",")

            # 17 - Importe IVA
            content += format_amount(vat_amount, 16, 2, ",")

            # 18 - Monto Sujeto a Retención/ Percepción
            content += format_amount(taxable_amount, 16, 2, ",")

            # 19 - Alícuota
            content += format_amount(alicuot, 5, 2, ",")

            # 20 - Retención/Percepción Practicada

            # si la línea tiene moneda diferente de la moneda de la compañía queremos que la ret/perc
            # se calcule aplicando la alícuota sobre la base imponible en la moneda de la compañía
            # TODO en febrero 2026 sacar lo que está a la derecha del "or" del if de abajo
            # (más información en tarea 59174).
            # Hacer revert de esto https://github.com/ingadhoc/odoo-argentina-ee/pull/743 en febrero 2026
            rounded_ret_perc_applied = float_round((taxable_amount * alicuot / 100), precision_digits=2)
            if (
                line.currency_id
                and line.currency_id != line.company_id.currency_id
                or rounded_ret_perc_applied != -line.balance
            ):
                ret_perc_applied = rounded_ret_perc_applied
            content += format_amount((-line.balance if not ret_perc_applied else ret_perc_applied), 16, 2, ",")

            # 21 - Monto Total Retenido/Percibido
            content += format_amount((-line.balance if not ret_perc_applied else ret_perc_applied), 16, 2, ",")

            # # 22 - Aceptacion
            content += " "

            # 24 - Fecha Aceptación "Expresa"
            content += "          "

            content += "\r\n"

            ret_perc += content

        return [
            {
                "txt_filename": "Perc/Ret IIBB AGIP Aplicadas.txt",
                "txt_content": ret_perc,
            },
            {
                "txt_filename": "NC Perc/Ret IIBB AGIP Aplicadas.txt",
                "txt_content": credito,
            },
        ]

    def iibb_aplicado_act_7_files_values(self, move_lines):
        return self.iibb_aplicado_files_values(move_lines, act_7=True)

    def iibb_aplicado_files_values(self, move_lines, act_7=None):
        """
        Por ahora es el de arba, renombrar o generalizar para otros
        Implementado segun esta especificacion
        https://drive.google.com/file/d/0B3trzV0e2WzveHhBTk9xWEl6RjA/view
        Implementados:
            - 1.2 Percepciones Act. 7 método Percibido (quincenal)
            - 1.7 Retenciones ( excepto actividad 26, 6 de Bancos y 17 de
            Bancos y No Bancos)
        """
        self.ensure_one()
        ret = ""
        perc = ""

        for line in move_lines:
            # pay_group = payment.payment_group_id
            move = line.move_id
            payment = line.payment_id
            internal_type = line.l10n_latam_document_type_id.internal_type
            document_code = line.l10n_latam_document_type_id.code

            line.partner_id.ensure_vat()

            content = line.partner_id.l10n_ar_formatted_vat
            content += fields.Date.from_string(line.date).strftime("%d/%m/%Y")

            # solo para percepciones
            if not payment:
                content += (
                    document_code in ["201", "206", "211"]
                    and "E"
                    or document_code in ["203", "208", "213"]
                    and "H"
                    or document_code in ["202", "207", "212"]
                    and "I"
                    or internal_type == "invoice"
                    and "F"
                    or internal_type == "debit_note"
                    and "D"
                    or internal_type == "credit_note"
                    and "C"
                    or "O"
                )
                if document_code in ["201", "206", "211", "202", "207", "212", "203", "208", "213"]:
                    content += " "
                else:
                    content += line.l10n_latam_document_type_id.l10n_ar_letter
                content += (
                    # si es nota de debito/credito de mipymes le sacamos el prefijo
                    "%012d"
                    % int(re.sub("[^0-9]", "", move.l10n_latam_document_number or "")[3:])
                    if document_code in ["201", "206", "211", "202", "207", "212", "203", "208", "213"]
                    else "%012d" % int(re.sub("[^0-9]", "", move.l10n_latam_document_number or ""))
                )

                content += format_amount(move.amount_total_signed, 11, 2)
            else:
                # comprobante origen de retencion. se pide CUIT + Tipo (F) + Letra + Punto Venta (4) + Nro (8)
                # se completa con espacios
                content += " " * 27

            content += format_amount(line.tax_base_amount, 11, 2)
            content += format_amount(abs(-line.balance), 11, 2)
            # fecha ret/perc
            if payment:
                content += fields.Date.from_string(payment.date).strftime("%d/%m/%Y")
            else:
                content += fields.Date.from_string(line.date).strftime("%d/%m/%Y")

            # percepciones
            if not payment:
                # tipo
                if act_7:
                    content += "A"
                else:
                    content += "P"
                # codigo norma
                # TODO ver si esto hace falta hacerlo configurable o algo
                # DN serie B 01/04
                content += "000"
            # retenciones
            else:
                # tipo
                content += "R"
                code = "000"
                if line.tax_line_id.description:
                    code = line.tax_line_id.description[0:3]
                content += code

                # nro certificado
            content += (line.withholding_id.name or "").replace("-", "")[:16].rjust(16, "0")

            content += fields.Date.from_string(line.date).strftime("%d/%m/%Y")

            content += "\r\n"

            # tipo_agente == 'rp'
            if not payment:
                perc += content
            # tipo_agente == 'rr'
            else:
                ret += content

        return [
            {
                "txt_filename": "Percepciones IIBB ARBA Aplicadas.txt",
                "txt_content": perc,
            },
            {
                "txt_filename": "Retenciones IIBB ARBA Aplicadas.txt",
                "txt_content": ret,
            },
        ]

    ###################################
    # SIFERE (IIBB sufrido - Convenio Multilateral)
    ###################################

    # Códigos AFIP de tipo de comprobante para Despacho de Importación.
    _SIFERE_IMPORT_DOCUMENT_CODES = ("66", "67")

    def iibb_sufrido_files_values(self, move_lines):
        """TXT de IIBB sufrido para SIFERE WEB (Comisión Arbitral - Convenio
        Multilateral), portado 1:1 desde l10n_ar_account_reports (Enterprise,
        ingadhoc) para asegurar compatibilidad con el formato real:
        https://github.com/ingadhoc/odoo-argentina-ee/blob/47fbbde/l10n_ar_account_reports/models/sifere_report.py

        EE arma cada archivo con su propio dominio de búsqueda (3 botones);
        acá recibimos un único `move_lines` (ya filtrado por los tags del
        diario de liquidación) y lo clasificamos con el mismo criterio:
          * Retenciones sufridas: impuesto con l10n_ar_withholding_payment_type
            == 'customer' (nos retuvo el cliente al cobrar).
          * Despachos de importación: comprobante con código AFIP 66 o 67
            (listado informativo, se carga a mano en SIFERE WEB).
          * Percepciones sufridas: el resto (percepción de proveedor en compra).
        """
        self.ensure_one()

        ret_lines = self.env["account.move.line"]
        perc_lines = self.env["account.move.line"]
        desp_lines = self.env["account.move.line"]
        for line in move_lines:
            tax = line._get_settlement_tax()
            if tax.l10n_ar_withholding_payment_type == "customer":
                ret_lines |= line
            elif line.l10n_latam_document_type_id.code in self._SIFERE_IMPORT_DOCUMENT_CODES:
                desp_lines |= line
            else:
                perc_lines |= line

        files = []
        if ret_lines:
            files.append(
                {
                    "txt_filename": "SIFERE_Retenciones_Sufridas.txt",
                    "txt_content": self._sifere_txt_content(ret_lines, "ret"),
                }
            )
        if perc_lines:
            files.append(
                {
                    "txt_filename": "SIFERE_Percepciones_Sufridas.txt",
                    "txt_content": self._sifere_txt_content(perc_lines, "perc"),
                }
            )
        if desp_lines:
            files.append(
                {
                    "txt_filename": "SIFERE_Despachos_Importacion (no importar).txt",
                    "txt_content": self._sifere_txt_content(desp_lines, "despachos"),
                }
            )
        return files

    def _sifere_txt_content(self, move_lines, file_type):
        lines = []
        desp_imp = []
        for line in move_lines.filtered("amount_currency").sorted(key=lambda r: (r.date, r.id)):
            if file_type == "despachos":
                # No es un TXT para importar: los despachos de importación se
                # cargan a mano en SIFERE WEB, igual que hace Enterprise.
                desp_imp.append(" - " + line.move_id.display_name + "\n")
                continue

            move = line.move_id
            internal_type = line.l10n_latam_document_type_id.internal_type

            if not line.partner_id:
                raise ValidationError(
                    _('El apunte %s (id %s) del comprobante "%s" (id %s) no tiene contacto asociado.')
                    % (line.display_name, line.id, move.name, move.id)
                )
            line.partner_id.ensure_vat()

            tax = line._get_settlement_tax()
            content = self._get_tax_jurisdiction_code(tax) or "000"
            content += line.partner_id.l10n_ar_formatted_vat
            content += fields.Date.from_string(line.date).strftime("%d/%m/%Y")

            if file_type == "ret":
                if float_round(line.balance, precision_digits=2) == 0.0:
                    continue
                certificado = line._l10n_ar_withholding_data()[0]
                pos, number = get_pos_and_number(certificado)
                content += f"{pos:>04s}"
                content += f"{number:>016s}"
            else:
                document_parts = move._l10n_ar_get_document_number_parts(
                    move.l10n_latam_document_number, move.l10n_latam_document_type_id.code
                )
                # Si el punto de venta es de 5 dígitos tomamos los últimos 4
                # (no hay especificación de cómo proceder en ese caso).
                pto_venta = "{:0>4d}".format(document_parts["point_of_sale"])[-4:]
                nro_documento = "{:0>8d}".format(document_parts["invoice_number"])[-8:]
                content += pto_venta
                content += nro_documento

            if file_type == "ret":
                content += "R"
                content += " "
            else:
                doc_type = (
                    (internal_type in ("invoice", "ticket") and "F")
                    or (internal_type == "credit_note" and "C")
                    or (internal_type == "debit_note" and "D")
                    or (internal_type == "receipt_invoice" and "R")
                    or "O"
                )
                if internal_type == "ticket" and line.balance < 0.0:
                    doc_type = "C"
                content += doc_type
                content += " " if doc_type == "O" else (line.l10n_latam_document_type_id.l10n_ar_letter or " ")

            if file_type == "ret":
                content += "%020d" % int(re.sub("[^0-9]", "", move.l10n_latam_document_number or "0"))
            content += format_amount(line.balance, 11, 2, ",")
            content += "\r\n"
            lines.append(content)

        if desp_imp:
            desp_imp.insert(
                0,
                "En los registros seleccionados encontramos algunos despachos de "
                "importación, los mismos deben cargarse a mano. Los comprobantes "
                "correspondientes son:\n",
            )
            return "".join(desp_imp)
        return "".join(lines)

    def sicore_aplicado_files_values(self, move_lines):
        self.ensure_one()

        # build txt file
        content = ""

        for line in move_lines.filtered("amount_currency").sorted(key=lambda r: (r.date, r.id)):
            partner = line.partner_id
            if not partner.l10n_latam_identification_type_id.l10n_ar_afip_code:
                raise ValidationError(
                    _('EL tipo de identificación "%s" no tiene código de arca configurado')
                    % (partner.l10n_latam_identification_type_id.name)
                )
            if not partner.vat:
                raise ValidationError(
                    _('El partner "%s" (id %s) no tiene número de identificación establecido')
                    % (partner.name, partner.id)
                )

            payment = line.payment_id
            move = line.move_id

            # si tengo payment es una retención, sino es una percepción y tengo que sacar la información de la factura (del move)
            if payment:
                # Codigo del Comprobante         [ 2]
                content += (
                    (payment.payment_type == "inbound" and "02")
                    or (payment.payment_type == "outbound" and "06")
                    or "00"
                )

                # Fecha Emision Comprobante      [10] (dd/mm/yyyy)
                content += fields.Date.from_string(line.date).strftime("%d/%m/%Y")
                # Numero Comprobante            [16]
                # En stacks sin receiptbook el asiento del pago no tiene número
                # de documento LATAM: usamos el nombre del pago como fallback.
                raw_number = move.l10n_latam_document_number or payment.name or ""
                content += "%016d" % int(re.sub("[^0-9]", "", raw_number) or 0)
                # Importe del comprobante
                codop = "1"
                issue_date = payment.date
                # payment_total es de account_payment_pro (ingadhoc); en el
                # stack oficial usamos el importe en moneda de la compañía.
                if "payment_total" in payment._fields:
                    amount_tot = abs(payment.payment_total)
                elif "amount_company_currency_signed" in payment._fields:
                    amount_tot = abs(payment.amount_company_currency_signed)
                else:
                    amount_tot = abs(payment.amount)
                base_amount = line._l10n_ar_withholding_data()[1]

            elif move.is_invoice():
                # Codigo del Comprobante         [ 2]
                tipodoc = int(move.l10n_latam_document_type_id.code)
                es_nc = False

                if tipodoc in [1, 6, 19, 51, 81, 82, 118, 201, 206]:
                    # Factura
                    content += "01"
                elif tipodoc in [4, 9, 54]:
                    # Recibo
                    content += "02"
                elif tipodoc in [3, 8, 21, 53, 43, 44, 110, 112, 113, 114, 119, 203, 208]:
                    # Nota de Crédito
                    content += "03"
                    es_nc = True
                elif tipodoc in [2, 7, 20, 52, 45, 46, 115, 116, 120, 202, 207]:
                    # Nota de Débito
                    content += "04"
                else:
                    # Otro comprobante
                    content += "05"

                # Fecha Emision Comprobante      [10] (dd/mm/yyyy)
                content += fields.Date.from_string(move.invoice_date).strftime("%d/%m/%Y")
                # Numero Comprobante            [16]
                # content += '%016d' % int(re.sub('[^0-9]', '', move.l10n_latam_document_number))
                content += "%05d" % int(re.sub("[^0-9]", "", move.l10n_latam_document_number)[:5])
                content += "%011d" % int(re.sub("[^0-9]", "", move.l10n_latam_document_number)[5:])
                issue_date = move.invoice_date
                # si la percepción es sobre una nota de crédito informamos el importe de la percepción
                # aclaración: no tenemos ningún respaldo documental respecto a esto, solo lo hicimos para
                # solucionar la inconsistencia del ticket 61671
                base_amount = line.tax_base_amount if es_nc == False else line.balance
                codop = "2"
                # Importe del comprobante
                amount_tot = abs(move.amount_total_signed)
            else:
                raise ValidationError(
                    _(
                        "El apunte %s (id %s) no proviene ni de un pago ni de una "
                        "factura: no se puede incluir en el TXT de SICORE."
                    )
                    % (line.display_name, line.id)
                )

            # Importe Comprobante            [16]
            content += "%016.2f" % amount_tot
            # Codigo de Impuesto             [ 4]
            # Codigo de Regimen              [ 3]
            codcond = "01"

            tax = line._get_settlement_tax()
            if tax.l10n_ar_withholding_payment_type:
                # 01 --> retención ganancias
                # En Community Edition, l10n_ar_tax_type puede no existir
                # Verificamos si el campo existe, y si no, intentamos identificar por nombre del grupo
                is_earnings_tax = False
                if hasattr(tax, 'l10n_ar_tax_type') and tax.l10n_ar_tax_type in ["earnings", "earnings_scale"]:
                    is_earnings_tax = True
                elif tax.tax_group_id:
                    # Intentar identificar por nombre del grupo de impuestos
                    group_name_lower = (tax.tax_group_id.name or "").lower()
                    if any(keyword in group_name_lower for keyword in ["ganancia", "earnings", "profit"]):
                        is_earnings_tax = True
                
                if is_earnings_tax:
                    content += "0217"
                    regimen = self._get_tax_code(tax, line)
                    # necesitamos lo de filter porque hay dos regimenes que le
                    # agregamos caracteres
                    content += regimen and "%03d" % int("".join(filter(str.isdigit, str(regimen)))) or "000"
                # 02 --> retención iva
                else:
                    content += "0767"
                    # por ahora el unico implementado es para factura M
                    tax_code = self._get_tax_code(tax, line)
                    content += "%03d" % int(tax_code) if tax_code else "499"
                    if tax_code == "602":
                        codcond = "13" if tax.amount == 3 else "14"
                    # Si el código de régimen es 214 entonces el código de condición debe ser '00'.
                    # Más información en archivo l10n_ar_account_tax_settlement/data/relaciones-codigos-sicore.csv
                    if tax_code == "214":
                        codcond = "00"
            else:
                # Percepción de IVA
                content += "0767"
                tax_code = self._get_tax_code(tax, line)
                if not tax_code:
                    raise ValidationError(
                        _("No se encontró código de régimen para el impuesto '%s'. "
                          "Configure el código en la tabla de impuestos del impuesto.") % tax.name
                    )
                content += "%03d" % int(tax_code)
                if tax_code == "602":
                    codcond = "13" if tax.amount == 3 else "14"
                # Si el código de régimen es 493 entonces el código de condición debe ser '00'.
                # Más información en archivo l10n_ar_account_tax_settlement/data/relaciones-codigos-sicore.xlsx
                elif tax_code == "493":
                    codcond = "00"

            # Codigo de Operacion            [ 1]
            content += codop  # TODO: ???? DUDA: SERÍA PARA VER SI ES RETENCION O PERCEPCION

            # Base de Calculo                [14]
            content += "%014.2f" % base_amount

            # Fecha Emision Retencion        [10] (dd/mm/yyyy)
            content += fields.Date.from_string(issue_date).strftime("%d/%m/%Y")

            # Codigo de Condicion            [ 2]
            content += codcond  # TODO: ???? ver tabla de condición sicore

            # Retención Pract. a Suj. ..     [ 1]
            content += "0"  # TODO: ????

            # Importe de Retencion           [14] (también se usa para importe de percepción)
            content += "%014.2f" % abs(line.balance)

            # Porcentaje de Exclusion        [ 6]
            # AFIP/ARCA no expone este dato vía las APIs disponibles; el
            # propio Odoo Enterprise lo hardcodea a "000.00" siempre (ver
            # sicore_report.py de l10n_ar_account_reports). No es un campo
            # real de account.tax: por eso lo fijamos igual, en vez de leer
            # un atributo que nunca existe.
            content += "000.00"

            # Fecha Emision Boletin          [10] (dd/mm/yyyy)
            content += fields.Date.from_string(issue_date).strftime("%d/%m/%Y")

            # Tipo Documento Retenido        [ 2]
            # Código AFIP dinámico del tipo de documento del partner (80=CUIT,
            # 86=CUIL, 96=DNI, etc.), ya validado como presente al inicio del
            # loop. Antes se hardcodeaba "3", que no es un código válido de
            # esta tabla (ver sicore_report.py de l10n_ar_account_reports).
            content += "%02d" % int(partner.l10n_latam_identification_type_id.l10n_ar_afip_code)

            # Numero Documento Retenido      [20]
            vat = re.sub(r"\D", "", partner.vat)
            content += vat.ljust(20)

            # Numero Certificado Original    [14]
            content += "%014d" % 0  # TODO: ????

            content += "\r\n"

        # Nombre con período (mes de los apuntes) para identificar la presentación.
        period = ""
        if move_lines:
            period = "_%s" % fields.Date.from_string(move_lines[0].date).strftime("%Y%m")
        return [
            {
                "txt_filename": "SICORE_Aplicado%s.txt" % period,
                "txt_content": content,
            }
        ]

    ###################################
    # Métodos de generación de archivos
    ###################################

    def get_tax_settlement_files_values(self, move_lines):
        """
        Función que devuelve lista de diccionarios con "nombre de archivo"
        y "contenido de archivo" para todos los apuntes seleccionados
        Ej:
        [{'txt_filename': 'Nombre', 'txt_content': 'Contenido'}]
        """
        self.ensure_one()
        if draft_lines := move_lines.filtered(lambda x: x.move_id.state == "draft"):
            raise ValidationError(
                _(
                    "Ha seleccionado apuntes contables de asientos en borrador. "
                    "Solo puede generar el txt de apuntes de asientos publicados. Apuntes: %s"
                )
                % draft_lines.ids
            )
        if self.settlement_tax and hasattr(self, "%s_files_values" % self.settlement_tax):
            return getattr(self, "%s_files_values" % self.settlement_tax)(move_lines)
        return []

    ###################################
    # account.journal.dashboard methods
    ###################################

    def _get_tax_settlement_lines_domain_by_tags(self):
        """Apuntes contables liquidables por este diario (liquidados o no), filtrando por
        los tags configurados en `settlement_account_tag_ids`. Misma estrategia que el
        módulo Enterprise: el usuario indica qué tags liquida cada diario."""
        self.ensure_one()
        if not self.settlement_account_tag_ids:
            return [("id", "=", False)]

        domain = [
            ("company_id", "=", self.company_id.id),
            ("tax_repartition_line_id.tag_ids", "in", self.settlement_account_tag_ids.ids),
            ("parent_state", "=", "posted"),
        ]

        if from_date := self._context.get("from_date"):
            domain.append(("date", ">=", from_date))

        if to_date := self._context.get("to_date"):
            domain.append(("date", "<=", to_date))

        return domain

    def _compute_tax_settlement_lines_info(self):
        """Calcula información de líneas a liquidar para el tablero"""
        for journal in self:
            if not journal.tax_settlement:
                journal.tax_settlement_lines_count = 0
                journal.tax_settlement_lines_amount = 0.0
                journal.tax_settlement_debt_balance = 0.0
                continue
            
            domain = journal._get_tax_settlement_lines_domain_by_tags()
            # Filtrar solo líneas sin liquidar (tax_settlement_move_id = False o tax_state = 'to_settle')
            domain.append(("tax_settlement_move_id", "=", False))
            
            lines = self.env["account.move.line"].search(domain)
            journal.tax_settlement_lines_count = len(lines)
            journal.tax_settlement_lines_amount = abs(sum(lines.mapped("balance")))
            
            # Calcular saldo a pagar (líneas liquidadas pero no pagadas)
            if journal.settlement_partner_id:
                # Buscar movimientos de liquidación del partner
                settlement_moves = self.env["account.move"].search([
                    ("journal_id", "=", journal.id),
                    ("partner_id", "=", journal.settlement_partner_id.id),
                    ("state", "=", "posted"),
                ])
                # Sumar saldos de cuentas por pagar de estos movimientos
                payable_lines = settlement_moves.line_ids.filtered(
                    lambda l: l.account_id.account_type == "liability_payable" and not l.reconciled
                )
                journal.tax_settlement_debt_balance = abs(sum(payable_lines.mapped("balance")))
            else:
                journal.tax_settlement_debt_balance = 0.0

    tax_settlement_lines_count = fields.Integer(
        string="Líneas a liquidar",
        compute="_compute_tax_settlement_lines_info",
        help="Número de líneas pendientes de liquidar"
    )
    tax_settlement_lines_amount = fields.Monetary(
        string="Monto líneas a liquidar",
        compute="_compute_tax_settlement_lines_info",
        currency_field="currency_id",
        help="Monto total de líneas pendientes de liquidar"
    )
    tax_settlement_debt_balance = fields.Monetary(
        string="Saldo a pagar",
        compute="_compute_tax_settlement_lines_info",
        currency_field="currency_id",
        help="Saldo pendiente de pago de liquidaciones"
    )

    def action_create_payment(self):
        """Abre el wizard de pago para el partner de liquidación"""
        self.ensure_one()
        partner = self.settlement_partner_id
        if not partner:
            raise ValidationError(_("Solo puede crear pago si el diario tiene un contacto de liquidación configurado!"))
        
        # Buscar asientos de liquidación del partner que tienen líneas sin pagar
        settlement_moves = self.env["account.move"].search([
            ("journal_id", "=", self.id),
            ("partner_id", "=", partner.id),
            ("state", "=", "posted"),
        ])
        
        # Buscar líneas de cuentas por pagar que no están reconciliadas
        open_move_line_ids = settlement_moves.line_ids.filtered(
            lambda r: not r.reconciled and r.account_id.account_type in ("asset_receivable", "liability_payable")
        )

        # Inferimos partner_type/payment_type a partir del tipo de cuenta de las líneas.
        # Si no hay líneas (no se cargó liquidación todavía), asumimos pago a proveedor.
        if open_move_line_ids:
            partner_type, payment_type = self.env["account.move.line"]._tax_settlement_payment_kind(
                open_move_line_ids
            )
        else:
            partner_type, payment_type = "supplier", "outbound"

        # account_payment_pro popula `to_pay_move_line_ids` mediante un compute que
        # corre solo si `pay_now` está en el contexto. Si tenemos líneas concretas,
        # las restringimos vía active_model/active_ids; si no, dejamos que el
        # compute traiga todo lo abierto del partner.
        context = {
            "default_partner_id": partner.id,
            "default_partner_type": partner_type,
            "default_payment_type": payment_type,
            "default_company_id": self.company_id.id,
            "pay_now": True,
            "create": True,
            "pop_up": True,
            "force_simple": True,
        }
        if open_move_line_ids:
            context["active_model"] = "account.move.line"
            context["active_ids"] = open_move_line_ids.ids
        
        return {
            "name": _("Registrar Pago"),
            "view_mode": "form",
            "res_model": "account.payment",
            "view_id": False,
            "target": "current",
            "type": "ir.actions.act_window",
            "context": context,
        }

    ####################################
    # Métodos compartidos de liquidación
    ####################################

    def create_tax_settlement_entry(self, move_lines):
        """
        Función que recibe move lines y crea una liquidación en este diario
        agrupando por cuenta contable. (se usa desde apuntes contables)
        Devuelve un browse del move creado
        """
        self.ensure_one()
        if draft_lines := move_lines.filtered(lambda x: x.move_id.state == "draft"):
            raise ValidationError(
                _(
                    "Ha seleccionado apuntes contables de asientos en borrador. "
                    "Solo puede liquidar apuntes de asientos publicados. Apuntes: %s"
                )
                % draft_lines.ids
            )
        if not self.tax_settlement:
            raise ValidationError(_("Settlement only allowed on journals with Tax Settlement enable"))

        # En Community Edition, no tenemos tax_settlement_move_id, así que no validamos si ya está liquidado
        # Si el campo existe, validamos
        if hasattr(move_lines, 'tax_settlement_move_id'):
            if move_lines.filtered("tax_settlement_move_id"):
                raise ValidationError(
                    _("You can not settle lines that has already been settled!\n" "* Lines ids: %s")
                    % (move_lines.filtered("tax_settlement_move_id").ids)
                )

        lines_vals = self._get_tax_settlement_entry_lines_vals([("id", "in", move_lines.ids)])
        vals = self._get_tax_settlement_entry_vals(lines_vals)
        move = self.env["account.move"].create(vals)
        
        # Siempre actualizar tax_settlement_move_id (el campo existe en nuestro modelo)
        move_lines.write({"tax_settlement_move_id": move.id})
        
        return move

    def _get_tax_settlement_entry_lines_vals(self, domain=None):
        """
        Obtiene los valores de las líneas del asiento de liquidación
        agrupando por cuenta contable
        """
        self.ensure_one()
        if not domain:
            domain = []
        
        # Agrupar líneas por cuenta contable
        grouped_move_lines = self.env["account.move.line"].read_group(
            domain, ["account_id", "balance", "amount_currency:sum"], ["account_id"]
        )

        new_move_lines = []
        company_currency = self.company_id.currency_id
        is_zero = company_currency.is_zero
        
        for group in grouped_move_lines:
            group_balance = company_currency.round(group["balance"])
            if is_zero(group_balance):
                continue
            # La liquidación debe ser el signo contrario de las líneas originales
            # (equivalente a una reversión por cuenta agrupada).
            # Ejemplo: si en origen la cuenta quedó en crédito (balance < 0),
            # en liquidación debe ir a débito por el mismo importe.
            new_vals_line = {
                "name": self.name,
                "debit": group_balance < 0.0 and -group_balance or 0.0,
                "credit": group_balance > 0.0 and group_balance or 0.0,
                "account_id": group["account_id"][0],
            }
            
            # Si la cuenta tiene moneda secundaria, agregar currency_id y amount_currency
            account = self.env["account.account"].browse(group["account_id"][0])
            if account.currency_id:
                # Mismo criterio que balance: en liquidación va con signo opuesto.
                amount_currency = -(group["amount_currency"] or 0.0)
                new_vals_line.update({"currency_id": account.currency_id.id, "amount_currency": amount_currency})
            
            new_move_lines.append(new_vals_line)

        return new_move_lines

    def _get_tax_settlement_entry_vals(self, lines_vals):
        """
        Obtiene los valores para crear el asiento de liquidación
        """
        self.ensure_one()
        
        # Calcular el balance total de las líneas de impuestos
        total_balance = sum(line["debit"] - line["credit"] for line in lines_vals)
        
        # Si hay desbalance, crear línea de contrapartida
        # La contrapartida debe equilibrar: si las líneas de impuestos suman positivo (más débito),
        # la contrapartida va a crédito; si suman negativo (más crédito), va a débito
        if not self.company_id.currency_id.is_zero(total_balance):
            if not self.settlement_account_id:
                raise ValidationError(
                    _("El diario de liquidación debe tener una cuenta de contrapartida configurada "
                      "para crear asientos con desbalance.")
                )
            
            # Agregar línea de contrapartida con el partner si está configurado
            contrapartida_line = {
                "name": self.name,
                "debit": total_balance < 0.0 and -total_balance or 0.0,
                "credit": total_balance >= 0.0 and total_balance or 0.0,
                "account_id": self.settlement_account_id.id,
            }
            
            # Si hay partner configurado, agregarlo a la línea de contrapartida
            if self.settlement_partner_id:
                contrapartida_line["partner_id"] = self.settlement_partner_id.id
            
            lines_vals.append(contrapartida_line)
        
        # El partner ya se agregó en la línea de contrapartida si estaba configurado
        # No necesitamos agregar una línea adicional

        move_vals = {
            "ref": self._context.get("entry_ref", self.name),
            "date": self._context.get("entry_date", fields.Date.today()),
            "journal_id": self.id,
            "company_id": self.company_id.id,
            "line_ids": [(0, 0, line_vals) for line_vals in lines_vals],
        }
        
        # Agregar partner al move si está configurado
        if self.settlement_partner_id:
            move_vals["partner_id"] = self.settlement_partner_id.id
        
        return move_vals

    def open_action(self):
        """
        Modificamos funcion para que si es liquidacion de impuestos devuelva accion correspondiente
        Y si es deuda del partner muestre el partner ledger
        """
        if self.type == "general" and self.tax_settlement:
            tax_settlement = self._context.get("tax_settlement", False)
            debt_balance = self._context.get("debt_balance", False)
            if tax_settlement:
                # Ingresa aquí al entrar en vista Kanban en diario de liquidacion en el botoncito "Líneas a liquidar"
                action = self.env["ir.actions.actions"]._for_xml_id(
                    "l10n_ar_account_tax_settlement.action_account_tax_move_line"
                )
                action["domain"] = self._get_tax_settlement_lines_domain_by_tags()
                ctx = action.get("context", {})
                if isinstance(ctx, str):
                    ctx = safe_eval(ctx)
                ctx.update(
                    {
                        "from_tax_settlement_journal": True,
                        "default_journal_id": self.id,
                    }
                )
                action["context"] = ctx
                return action
            elif debt_balance and hasattr(self, 'settlement_partner_id') and self.settlement_partner_id:
                # Ingresa aquí al entrar en vista Kanban en diario de liquidacion en el botoncito 'Saldo a pagar'
                # En Community, puede que no exista open_partner_ledger, usar alternativa
                if hasattr(self.settlement_partner_id, 'open_partner_ledger'):
                    action = self.settlement_partner_id.open_partner_ledger()
                    ctx = action.get("context", {})
                    if isinstance(ctx, str):
                        ctx = safe_eval(ctx)
                    ctx.update(
                        {
                            "default_partner_id": self.settlement_partner_id.id,
                        }
                    )
                    action["context"] = ctx
                    return action
        return super(AccountJournal, self).open_action()
