"""Corrección puntual: facturas de COMPRA con IVA de VENTAS aplicado.

Causa: el importador (l10n_ar_import_bill_ce), en su versión anterior al fix de
`type_tax_use`, asignaba a algunas compras un impuesto de IVA de Ventas. El IVA
quedó imputado a "IVA débito fiscal" en lugar de "IVA crédito fiscal".

Qué hace este script, por cada factura de compra afectada:
  1. Detecta las líneas base con un IVA de tipo 'sale'.
  2. Busca el IVA de 'purchase' equivalente (misma alícuota, mismo amount_type y
     mismo código AFIP de IVA del grupo) en la misma compañía.
  3. Restablece a borrador, reemplaza el impuesto, vuelve a publicar.
  4. Re-concilia las líneas por pagar con los mismos pagos que tenían antes
     (el total no cambia, así que los importes calzan).

USO (vía odoo shell, NO copia/pega en producción sin backup):
    # 1) Simulación (no toca nada, solo informa):
    docker exec -i odoo-17 odoo shell -d acl --no-http \
        --db_host=db --db_user=odoo --db_password=odoo17@2023 \
        < tools/fix_purchase_vat_tax.py

    # 2) Aplicar de verdad: cambiar DRY_RUN = False abajo y volver a correr.

IMPORTANTE: hacer BACKUP de la base y, si es posible, probar primero en una copia.
"""

import logging

_logger = logging.getLogger("fix_purchase_vat_tax")

# ---------------------------------------------------------------------------
DRY_RUN = True          # True = solo informa. False = aplica los cambios.
DATE_FROM = None        # ej. "2026-01-01" para acotar; None = sin límite inferior.
DATE_TO = None          # ej. "2026-12-31"; None = sin límite superior.
# ---------------------------------------------------------------------------


def _find_purchase_equivalent(env, sale_tax):
    """IVA de compras equivalente al de ventas: misma alícuota, mismo tipo de
    cálculo y mismo código AFIP de IVA, en la misma compañía."""
    return env["account.tax"].search(
        [
            ("type_tax_use", "=", "purchase"),
            ("company_id", "=", sale_tax.company_id.id),
            ("amount", "=", sale_tax.amount),
            ("amount_type", "=", sale_tax.amount_type),
            (
                "tax_group_id.l10n_ar_vat_afip_code",
                "=",
                sale_tax.tax_group_id.l10n_ar_vat_afip_code,
            ),
        ],
        limit=1,
    )


def _collect_reconciliations(move):
    """Devuelve, por cuenta, los apuntes contraparte (pagos) conciliados con las
    líneas por pagar/cobrar del move, para poder re-conciliar luego."""
    counterparts = move.env["account.move.line"]
    payable_lines = move.line_ids.filtered(
        lambda l: l.account_id.account_type in ("liability_payable", "asset_receivable")
    )
    for pl in payable_lines:
        for partial in pl.matched_debit_ids:
            counterparts |= partial.debit_move_id
        for partial in pl.matched_credit_ids:
            counterparts |= partial.credit_move_id
    return counterparts - move.line_ids


def run(env):
    sale_vat_taxes = env["account.tax"].search(
        [
            ("type_tax_use", "=", "sale"),
            ("tax_group_id.l10n_ar_vat_afip_code", "!=", False),
        ]
    )
    if not sale_vat_taxes:
        print("No hay impuestos de IVA de ventas; nada para revisar.")
        return

    domain = [
        ("move_type", "in", ("in_invoice", "in_refund")),
        ("line_ids.tax_ids", "in", sale_vat_taxes.ids),
        ("state", "=", "posted"),
    ]
    if DATE_FROM:
        domain.append(("invoice_date", ">=", DATE_FROM))
    if DATE_TO:
        domain.append(("invoice_date", "<=", DATE_TO))

    moves = env["account.move"].search(domain, order="invoice_date, id")
    print("=" * 72)
    print("Facturas de compra con IVA de ventas: %s" % len(moves))
    print("Modo: %s" % ("SIMULACIÓN (no se aplica)" if DRY_RUN else "APLICAR CAMBIOS"))
    print("=" * 72)

    fixed, skipped, failed = 0, 0, 0

    for move in moves:
        # Mapear, por línea base, el nuevo set de impuestos.
        line_new_taxes = {}
        problem = None
        for line in move.line_ids.filtered(lambda l: not l.tax_repartition_line_id and l.tax_ids):
            sale_vats = line.tax_ids.filtered(
                lambda t: t.type_tax_use == "sale" and t.tax_group_id.l10n_ar_vat_afip_code
            )
            if not sale_vats:
                continue
            new_taxes = line.tax_ids
            for st in sale_vats:
                pt = _find_purchase_equivalent(env, st)
                if not pt:
                    problem = "Sin equivalente de compras para '%s'" % st.name
                    break
                new_taxes = new_taxes - st + pt
            if problem:
                break
            line_new_taxes[line] = new_taxes

        if problem:
            print("  [SKIP] %s (id %s): %s" % (move.name, move.id, problem))
            skipped += 1
            continue
        if not line_new_taxes:
            continue

        detail = ", ".join(
            "%s -> %s" % (l.tax_ids.mapped("name"), t.mapped("name"))
            for l, t in line_new_taxes.items()
        )
        print("  [FIX ] %s (id %s) %s | %s" % (move.name, move.id, move.invoice_date, detail))

        if DRY_RUN:
            fixed += 1
            continue

        # Aplicar con savepoint por factura: si una falla, no arrastra al resto.
        try:
            with env.cr.savepoint():
                counterparts = _collect_reconciliations(move)
                payable_account = move.line_ids.filtered(
                    lambda l: l.account_id.account_type in ("liability_payable", "asset_receivable")
                ).account_id[:1]

                move.button_draft()
                for line, new_taxes in line_new_taxes.items():
                    line.tax_ids = [(6, 0, new_taxes.ids)]
                move.action_post()

                # Re-conciliar las nuevas líneas por pagar con los pagos originales.
                if counterparts and payable_account:
                    new_payable = move.line_ids.filtered(
                        lambda l: l.account_id == payable_account and not l.reconciled
                    )
                    to_reconcile = (new_payable | counterparts).filtered(
                        lambda l: l.account_id == payable_account and not l.reconciled
                    )
                    if len(to_reconcile) > 1:
                        to_reconcile.reconcile()
            fixed += 1
        except Exception as exc:  # noqa: BLE001
            print("  [ERROR] %s (id %s): %s" % (move.name, move.id, exc))
            failed += 1

    print("=" * 72)
    print("Corregidas: %s | Omitidas: %s | Con error: %s" % (fixed, skipped, failed))
    if DRY_RUN:
        print(">>> Fue SIMULACIÓN. Poné DRY_RUN = False para aplicar.")
    else:
        env.cr.commit()
        print(">>> Cambios COMMITEADOS. Cancele y regenere los cierres afectados.")


# Punto de entrada para `odoo shell` (la variable global `env` ya existe).
run(env)  # noqa: F821
