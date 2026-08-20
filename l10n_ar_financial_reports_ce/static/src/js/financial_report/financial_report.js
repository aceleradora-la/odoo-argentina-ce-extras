/** @odoo-module **/
// Pantalla de los reportes financieros interactivos (Odoo Community).
// Client action "l10n_ar_financial_report": debe coincidir con el tag que
// devuelve action_generate() del wizard.

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, onPatched, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const WIZARD_MODEL = "l10n_ar.financial.report.wizard";

export class ArFinancialReport extends Component {
    static template = "l10n_ar_financial_reports_ce.Report";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.rootRef = useRef("root");
        // El thead sticky de 2 filas necesita la altura REAL de la fila 1:
        // se mide tras cada render (ver skill odoo-community-report).
        onMounted(() => this._updateStickyOffsets());
        onPatched(() => this._updateStickyOffsets());

        this.wizardId = this.props.action.params.wizard_id;
        this.state = useState({
            data: null,
            loading: true,
            error: null,
            filterText: "",
            expanded: {},   // group_key -> bool
            lines: {},      // group_key -> [line]
            loadingGroups: {},
            hiddenCols: {},
        });
        onWillStart(async () => {
            try {
                this.state.data = await this.orm.call(
                    WIZARD_MODEL, "get_report_data", [this.wizardId]);
            } catch (error) {
                this.state.error = this._errorMessage(error);
            } finally {
                this.state.loading = false;
            }
        });
    }

    _errorMessage(error) {
        return (error && error.data && error.data.message) || String(error);
    }

    _updateStickyOffsets() {
        const root = this.rootRef.el;
        if (!root) return;
        for (const table of root.querySelectorAll("table")) {
            const firstRow = table.querySelector("thead tr:first-child");
            if (firstRow) {
                table.style.setProperty(
                    "--arfr-thead-row1-h",
                    `${firstRow.getBoundingClientRect().height}px`);
            }
        }
    }

    get header() {
        return this.state.data ? this.state.data.header : null;
    }
    get groups() {
        return this.state.data ? this.state.data.groups : [];
    }
    get totals() {
        return this.state.data ? this.state.data.totals : {};
    }
    get visibleColumns() {
        if (!this.header) return [];
        return this.header.columns.filter((c) => !this.state.hiddenCols[c.key]);
    }
    get filteredGroups() {
        const text = this.state.filterText.trim().toUpperCase();
        if (!text) return this.groups;
        return this.groups.filter((g) => (g.name || "").toUpperCase().includes(text));
    }

    // --- columnas -------------------------------------------------------
    toggleColumn(key) {
        this.state.hiddenCols[key] = !this.state.hiddenCols[key];
    }
    showAllColumns() {
        this.state.hiddenCols = {};
    }

    // --- celdas ---------------------------------------------------------
    getCell(row, col) {
        return (row.values || {})[col.key] || {};
    }
    cellClass(col, cell) {
        const align = (col.type === "monetary" || col.type === "text_right")
            ? "text-end" : (col.type === "date" ? "text-center" : "");
        return `${align} text-nowrap ${cell.class || ""}`;
    }
    thClass(col) {
        return (col.type === "monetary" || col.type === "text_right")
            ? "text-end" : (col.type === "date" ? "text-center" : "");
    }

    // --- drilldown ------------------------------------------------------
    async toggleGroup(key) {
        if (this.state.expanded[key]) {
            this.state.expanded[key] = false;
            return;
        }
        if (!(key in this.state.lines)) {
            this.state.loadingGroups[key] = true;
            try {
                const res = await this.orm.call(
                    WIZARD_MODEL, "get_group_lines", [this.wizardId, [key]]);
                Object.assign(this.state.lines, res);
                if (!(key in this.state.lines)) {
                    this.state.lines[key] = [];
                }
            } catch (error) {
                this.state.error = this._errorMessage(error);
                return;
            } finally {
                this.state.loadingGroups[key] = false;
            }
        }
        this.state.expanded[key] = true;
    }
    async expandAll() {
        this.state.loading = true;
        try {
            const res = await this.orm.call(
                WIZARD_MODEL, "get_group_lines", [this.wizardId, null]);
            this.state.lines = res;
            const expanded = {};
            for (const g of this.groups) {
                expanded[g.key] = true;
            }
            this.state.expanded = expanded;
        } catch (error) {
            this.state.error = this._errorMessage(error);
        } finally {
            this.state.loading = false;
        }
    }
    collapseAll() {
        this.state.expanded = {};
    }

    // --- filtros --------------------------------------------------------
    async updateFilter(field, value) {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call(
                WIZARD_MODEL, "update_filters",
                [this.wizardId, { [field]: value }]);
            this.state.lines = {};
            this.state.expanded = {};
        } catch (error) {
            this.state.error = this._errorMessage(error);
        } finally {
            this.state.loading = false;
        }
    }
    onDateChange(field, ev) {
        if (ev.target.value) {
            this.updateFilter(field, ev.target.value);
        }
    }
    onPeriodLengthChange(ev) {
        const value = parseInt(ev.target.value, 10);
        if (value && value > 0) {
            this.updateFilter("period_length", value);
        }
    }

    // --- exportación ----------------------------------------------------
    async exportPdf() {
        await this.action.doAction({
            type: "ir.actions.report",
            report_name: "l10n_ar_financial_reports_ce.report_pdf",
            report_type: "qweb-pdf",
            context: { active_ids: [this.wizardId] },
        });
    }
    exportXlsx() {
        window.location = `/l10n_ar_financial_reports_ce/xlsx/${this.wizardId}`;
    }
}

registry.category("actions").add("l10n_ar_financial_report", ArFinancialReport);
