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

        // Al recargar (F5, cambio de compañía) los params del action se
        // pierden y el wizard transient puede haber sido aspirado: se
        // restaura o se crea uno nuevo con get_or_create_report_data.
        const params = (this.props.action && this.props.action.params) || {};
        this.wizardId = params.wizard_id || null;
        this.reportType = params.report_type ||
            window.sessionStorage.getItem("arfr_report_type") || null;
        this.state = useState({
            data: null,
            loading: true,
            error: null,
            filterText: "",
            expanded: {},   // group_key -> bool
            lines: {},      // group_key -> [line]
            loadingGroups: {},
            hiddenCols: {},
            showColumnsMenu: false,
            menuPos: { top: 0, left: 0 },
        });
        onWillStart(async () => {
            try {
                await this._loadInitial();
            } catch (error) {
                this.state.error = this._errorMessage(error);
            } finally {
                this.state.loading = false;
            }
        });
    }

    async _loadInitial() {
        const data = await this.orm.call(
            WIZARD_MODEL, "get_or_create_report_data", [],
            { wizard_id: this.wizardId, report_type: this.reportType });
        this._setData(data);
    }

    _setData(data) {
        this.state.data = data;
        if (data.wizard_id) {
            this.wizardId = data.wizard_id;
        }
        this.reportType = data.header.report_type;
        window.sessionStorage.setItem("arfr_report_type", this.reportType);
    }

    _errorMessage(error) {
        return (error && error.data && error.data.message) || String(error);
    }

    _isMissingWizard(error) {
        const name = (error && error.data && error.data.name) || "";
        const message = (error && error.data && error.data.message) || "";
        return name.indexOf("MissingError") !== -1 ||
            message.indexOf("Expected singleton") !== -1;
    }

    /** Llama un método del wizard; si el transient ya no existe, lo recrea
     *  con los defaults del tipo de reporte actual y reintenta una vez. */
    async _callWizard(method, args = []) {
        try {
            return await this.orm.call(
                WIZARD_MODEL, method, [this.wizardId, ...args]);
        } catch (error) {
            if (!this._isMissingWizard(error)) {
                throw error;
            }
            const data = await this.orm.call(
                WIZARD_MODEL, "get_or_create_report_data", [],
                { report_type: this.reportType });
            this._setData(data);
            this.state.lines = {};
            this.state.expanded = {};
            return await this.orm.call(
                WIZARD_MODEL, method, [this.wizardId, ...args]);
        }
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
    toggleColumnsMenu(ev) {
        if (this.state.showColumnsMenu) {
            this.state.showColumnsMenu = false;
            return;
        }
        // Menú con position:fixed: se ubica bajo el botón y no lo recorta
        // el overflow de la toolbar.
        const rect = ev.currentTarget.getBoundingClientRect();
        const width = 260;
        this.state.menuPos = {
            top: Math.round(rect.bottom + 4),
            left: Math.round(Math.max(8,
                Math.min(rect.left, window.innerWidth - width - 8))),
        };
        this.state.showColumnsMenu = true;
    }
    closeColumnsMenu() {
        this.state.showColumnsMenu = false;
    }

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
                const res = await this._callWizard("get_group_lines", [[key]]);
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
            const res = await this._callWizard("get_group_lines", [null]);
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
            const data = await this._callWizard(
                "update_filters", [{ [field]: value }]);
            this._setData(data);
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
