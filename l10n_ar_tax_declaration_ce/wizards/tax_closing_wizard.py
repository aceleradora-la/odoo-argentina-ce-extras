from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class L10nArTaxClosingWizard(models.TransientModel):
    """Propone el asiento de Cierre de Impuestos del período (estilo Enterprise):
    revierte los saldos de las cuentas de IVA débito/crédito fiscal (y
    opcionalmente percepciones sufridas) contra cuentas de saldo a pagar /
    saldo a favor. El asiento queda en borrador para revisión del usuario.
    """

    _name = "l10n_ar.tax.closing.wizard"
    _description = "Cierre de Impuestos (AR)"

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(string="Fecha Desde", required=True)
    date_to = fields.Date(string="Fecha Hasta", required=True)
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario",
        required=True,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        default=lambda self: self._default_journal(),
    )
    scope = fields.Selection(
        [
            ("vat", "Solo IVA (débito/crédito fiscal)"),
            ("vat_perceptions", "IVA + Percepciones sufridas (compras)"),
        ],
        string="Alcance",
        required=True,
        default="vat_perceptions",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Organismo recaudador",
        default=lambda self: self.env.ref("l10n_ar.partner_afip", raise_if_not_found=False),
        help="Partner (ARCA/AFIP) que se asigna a la contrapartida del cierre. "
        "Con una cuenta de tipo 'A pagar' conciliable, la línea queda como deuda "
        "abierta y puede pagarse desde el Libro IVA.",
    )
    payable_account_id = fields.Many2one(
        "account.account",
        string="Cuenta saldo a pagar",
        help="Contrapartida si el cierre arroja impuesto a pagar (ej. IVA saldo a pagar)",
        check_company=True,
    )
    receivable_account_id = fields.Many2one(
        "account.account",
        string="Cuenta saldo a favor",
        help="Contrapartida si el cierre arroja saldo a favor (ej. IVA saldo técnico / libre disponibilidad)",
        check_company=True,
    )
    vat_ledger_id = fields.Many2one(
        "account.vat.ledger",
        string="Libro IVA",
        readonly=True,
        help="Libro IVA desde el que se lanzó el cierre (trazabilidad del asiento).",
    )
    carryover_favor = fields.Boolean(
        string="Arrastrar saldo a favor del período anterior",
        default=True,
        help="Si está activo, el cierre toma el saldo a favor acumulado en la "
        "'Cuenta saldo a favor' de períodos anteriores (movimientos previos a la "
        "fecha desde), lo reversa y lo netea contra el resultado del período. "
        "Requiere cerrar los períodos en orden secuencial.",
    )

    @api.model
    def _company_chain_ids(self, company):
        """IDs de la compañía y sus empresas padre (en setups de sucursal, la
        hija usa cuentas/diarios de la principal)."""
        ids = []
        current = company
        while current:
            ids.append(current.id)
            current = current.parent_id
        return ids

    @api.model
    def _default_journal(self):
        company = self.env.company
        Journal = self.env["account.journal"]
        base = [("type", "=", "general"), ("company_id", "=", company.id)]
        # Preferimos el diario de liquidación de IVA (l10n_ar_account_tax_settlement).
        if "settlement_tax" in Journal._fields:
            journal = Journal.search(base + [("settlement_tax", "=", "vat")], limit=1)
            if journal:
                return journal
        journal = Journal.search(base + [("code", "=", "MISC")], limit=1)
        if not journal:
            journal = Journal.search(base, limit=1)
        return journal

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env["res.company"].browse(res.get("company_id") or self.env.company.id)
        # Defaults de contrapartidas desde la configuración de grupos de impuestos
        # (campos estándar de CE: tax_payable_account_id / tax_receivable_account_id).
        # Buscamos los grupos en el contexto de la compañía (no filtramos por
        # company_id del grupo, que en setups multicompañía vive en otra empresa)
        # y elegimos la primera cuenta utilizable por la compañía del cierre.
        vat_groups = (
            self.env["account.tax.group"]
            .with_company(company)
            .search([("l10n_ar_vat_afip_code", "!=", False)])
        )

        # Cuentas válidas: las de la compañía del cierre o de sus empresas padre
        # (sucursal que usa las cuentas de la principal).
        allowed_ids = set(self._company_chain_ids(company))

        def _usable(accounts):
            for acc in accounts:
                # account.account usa company_ids (m2m) en 18 y company_id en 17.
                if "company_ids" in acc._fields:
                    if allowed_ids & set(acc.company_ids.ids):
                        return acc
                elif acc.company_id.id in allowed_ids:
                    return acc
            return self.env["account.account"]

        if "payable_account_id" in fields_list and not res.get("payable_account_id"):
            acc = _usable(vat_groups.mapped("tax_payable_account_id"))
            if acc:
                res["payable_account_id"] = acc.id
        if "receivable_account_id" in fields_list and not res.get("receivable_account_id"):
            acc = _usable(vat_groups.mapped("tax_receivable_account_id"))
            if acc:
                res["receivable_account_id"] = acc.id
        return res

    # -------------------------------------------------------------------------

    def _get_period_label(self):
        self.ensure_one()
        if (
            self.date_from.year == self.date_to.year
            and self.date_from.month == self.date_to.month
        ):
            return self.date_from.strftime("%m/%Y")
        return "%s - %s" % (self.date_from, self.date_to)

    def _get_tax_lines(self):
        """Apuntes de impuestos del período a incluir en el cierre."""
        self.ensure_one()
        base_domain = [
            ("company_id", "=", self.company_id.id),
            ("parent_state", "=", "posted"),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("tax_line_id", "!=", False),
        ]
        vat_lines = self.env["account.move.line"].search(
            base_domain + [("tax_line_id.tax_group_id.l10n_ar_vat_afip_code", "!=", False)]
        )
        lines = vat_lines
        if self.scope == "vat_perceptions":
            # Percepciones sufridas: impuestos con código de tributo en
            # comprobantes de compra (las aplicadas se liquidan por su propio
            # circuito en l10n_ar_account_tax_settlement).
            perception_lines = self.env["account.move.line"].search(
                base_domain
                + [
                    ("tax_line_id.tax_group_id.l10n_ar_tribute_afip_code", "!=", False),
                    ("journal_id.type", "=", "purchase"),
                ]
            )
            lines |= perception_lines
        return lines

    def _get_carryover_balance(self):
        """Saldo a favor acumulado en la 'Cuenta saldo a favor' de períodos
        anteriores (movimientos publicados con fecha anterior a date_from).

        Devuelve el balance redondeado (positivo = saldo a favor a arrastrar).
        Cero si el arrastre está desactivado o no hay cuenta de saldo a favor."""
        self.ensure_one()
        if not self.carryover_favor or not self.receivable_account_id:
            return 0.0
        prior_lines = self.env["account.move.line"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("parent_state", "=", "posted"),
                ("account_id", "=", self.receivable_account_id.id),
                ("date", "<", self.date_from),
            ]
        )
        return self.company_id.currency_id.round(sum(prior_lines.mapped("balance")))

    def action_generate(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise ValidationError(_("La fecha desde no puede ser mayor a la fecha hasta."))

        ref = "Cierre de impuestos: %s" % self._get_period_label()

        # Detección de duplicados por período real (fechas), independiente del
        # diario (ventas/compras) y del texto del ref. Fallback al ref para
        # asientos de cierre antiguos creados sin la marca de período.
        company_domain = [
            ("company_id", "=", self.company_id.id),
            ("state", "!=", "cancel"),
        ]
        existing = self.env["account.move"].search(
            company_domain
            + [
                ("l10n_ar_tax_closing_date_from", "=", self.date_from),
                ("l10n_ar_tax_closing_date_to", "=", self.date_to),
            ],
            limit=1,
        )
        if not existing:
            existing = self.env["account.move"].search(
                company_domain + [("ref", "=", ref)], limit=1
            )
        if existing:
            raise ValidationError(
                _(
                    "Ya existe un asiento de cierre para este período: %s (id %s). "
                    "Cancele o elimine ese asiento si desea regenerarlo."
                )
                % (existing.display_name, existing.id)
            )

        lines = self._get_tax_lines()
        if not lines:
            raise ValidationError(
                _("No se encontraron apuntes de impuestos en el período seleccionado.")
            )

        company_currency = self.company_id.currency_id

        # Agrupar por cuenta: el cierre revierte el saldo de cada cuenta de impuesto.
        grouped = defaultdict(lambda: {"balance": 0.0, "names": set()})
        for line in lines:
            key = line.account_id.id
            grouped[key]["balance"] += line.balance
            if line.tax_line_id.name:
                grouped[key]["names"].add(line.tax_line_id.name)

        move_lines = []
        net_balance = 0.0
        for account_id, vals in grouped.items():
            balance = company_currency.round(vals["balance"])
            if company_currency.is_zero(balance):
                continue
            net_balance += balance
            label = ", ".join(sorted(vals["names"]))[:200] or _("Cierre de impuestos")
            move_lines.append(
                {
                    "name": label,
                    "account_id": account_id,
                    # Reversión: el asiento de cierre deja en cero la cuenta.
                    "debit": -balance if balance < 0.0 else 0.0,
                    "credit": balance if balance > 0.0 else 0.0,
                }
            )

        # Arrastre del saldo a favor del período anterior: reversa el saldo
        # acumulado en la cuenta de saldo a favor y lo netea contra el período,
        # replicando el "saldo a favor del período anterior" de AFIP.
        carryover = self._get_carryover_balance()
        if not company_currency.is_zero(carryover):
            net_balance += carryover
            move_lines.append(
                {
                    "name": _("Saldo a favor per. anterior"),
                    "account_id": self.receivable_account_id.id,
                    # Reversión: deja en cero el saldo a favor arrastrado.
                    "debit": -carryover if carryover < 0.0 else 0.0,
                    "credit": carryover if carryover > 0.0 else 0.0,
                }
            )

        if not move_lines:
            raise ValidationError(
                _("Los saldos de impuestos del período están en cero, no hay nada que cerrar.")
            )

        # Contrapartida del neto: a pagar (neto acreedor) o a favor (neto deudor).
        net_balance = company_currency.round(net_balance)
        if not company_currency.is_zero(net_balance):
            if net_balance < 0.0:
                account = self.payable_account_id
                if not account:
                    raise ValidationError(
                        _("El período arroja saldo a pagar: configure la 'Cuenta saldo a pagar'.")
                    )
                label = _("Saldo a pagar %s") % self._get_period_label()
            else:
                account = self.receivable_account_id
                if not account:
                    raise ValidationError(
                        _("El período arroja saldo a favor: configure la 'Cuenta saldo a favor'.")
                    )
                label = _("Saldo a favor %s") % self._get_period_label()
            counterpart_vals = {
                "name": label,
                "account_id": account.id,
                "debit": net_balance if net_balance > 0.0 else 0.0,
                "credit": -net_balance if net_balance < 0.0 else 0.0,
            }
            # Con partner + cuenta por pagar/cobrar, la contrapartida queda como
            # deuda abierta del organismo y habilita el circuito de pago.
            if self.partner_id and account.account_type in ("liability_payable", "asset_receivable"):
                counterpart_vals["partner_id"] = self.partner_id.id
                counterpart_vals["date_maturity"] = self.date_to
            move_lines.append(counterpart_vals)

        move = self.env["account.move"].create(
            {
                "ref": ref,
                "date": self.date_to,
                "journal_id": self.journal_id.id,
                "company_id": self.company_id.id,
                "line_ids": [(0, 0, vals) for vals in move_lines],
                # Marca de período para detección de duplicados por fechas.
                "l10n_ar_tax_closing_date_from": self.date_from,
                "l10n_ar_tax_closing_date_to": self.date_to,
            }
        )

        # Trazabilidad: vinculamos el asiento a TODOS los Libros IVA del período
        # (ventas y compras), no solo al que lanzó el cierre, así desde cualquiera
        # se ve "Ver asiento de cierre" / "Pagar cierre".
        ledgers = self.env["account.vat.ledger"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("date_from", "=", self.date_from),
                ("date_to", "=", self.date_to),
            ]
        )
        ledgers |= self.vat_ledger_id
        if ledgers:
            ledgers.tax_closing_move_id = move

        return {
            "type": "ir.actions.act_window",
            "name": _("Cierre de impuestos"),
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
            "target": "current",
        }
