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
        this.notification = useService("notification");
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
            showAnalyticMenu: false,
            showPeriodMenu: false,
            showCustomDates: false,
            periodAnchor: "",
            customFrom: "",
            customTo: "",
            analyticFilter: "",
            analyticPlanId: 0,
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

    /** Errores de interacción: toast que no destruye la tabla en pantalla
     *  (state.error queda solo para la carga inicial). */
    _notifyError(error) {
        this.notification.add(this._errorMessage(error), { type: "danger" });
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
    get isPl() {
        return !!this.header && this.header.report_type === "profit_loss";
    }
    get hasTotals() {
        return !!this.totals && Object.keys(this.totals).length > 0;
    }
    /** Corridas contiguas de col.group sobre las columnas VISIBLES, para la
     *  1ª fila del encabezado (ocultar columnas achica el colspan). */
    get visibleColumnGroups() {
        const groups = [];
        for (const col of this.visibleColumns) {
            const label = col.group || "";
            if (groups.length && groups[groups.length - 1].label === label) {
                groups[groups.length - 1].colspan++;
            } else {
                groups.push({ label, colspan: 1 });
            }
        }
        return groups;
    }
    get filteredGroups() {
        // En el Estado de resultados el buscador filtra solo el detalle
        // (visibleLines): sacar líneas de estructura rompería las fórmulas.
        if (this.isPl) return this.groups;
        const text = this.state.filterText.trim().toUpperCase();
        if (!text) return this.groups;
        return this.groups.filter((g) => (g.name || "").toUpperCase().includes(text));
    }
    visibleLines(g) {
        const lines = this.state.lines[g.key] || [];
        if (!this.isPl) return lines;
        const text = this.state.filterText.trim().toUpperCase();
        if (!text) return lines;
        return lines.filter((ln) => (ln.name || "").toUpperCase().includes(text));
    }

    // --- columnas -------------------------------------------------------
    _placeMenu(ev) {
        // Menú con position:fixed: se ubica bajo el botón y no lo recorta
        // el overflow de la toolbar.
        const rect = ev.currentTarget.getBoundingClientRect();
        const width = 260;
        this.state.menuPos = {
            top: Math.round(rect.bottom + 4),
            left: Math.round(Math.max(8,
                Math.min(rect.left, window.innerWidth - width - 8))),
        };
    }
    toggleColumnsMenu(ev) {
        if (this.state.showColumnsMenu) {
            this.state.showColumnsMenu = false;
            return;
        }
        this._placeMenu(ev);
        this.closeColumnsMenu();
        this.state.showColumnsMenu = true;
    }
    toggleAnalyticMenu(ev) {
        if (this.state.showAnalyticMenu) {
            this.state.showAnalyticMenu = false;
            return;
        }
        this._placeMenu(ev);
        this.closeColumnsMenu();
        this.state.showAnalyticMenu = true;
    }
    togglePeriodMenu(ev) {
        if (this.state.showPeriodMenu) {
            this.state.showPeriodMenu = false;
            return;
        }
        this._placeMenu(ev);
        this.closeColumnsMenu();
        this.state.periodAnchor = this.header.date_from || "";
        this.state.customFrom = this.header.date_from || "";
        this.state.customTo = this.header.date_to || "";
        this.state.showCustomDates = false;
        this.state.showPeriodMenu = true;
    }
    closeColumnsMenu() {
        this.state.showColumnsMenu = false;
        this.state.showAnalyticMenu = false;
        this.state.showPeriodMenu = false;
    }

    /** Menú de columnas por GRUPO (períodos) para el Estado de resultados:
     *  con 13 períodos x analíticas la lista plana es inusable. */
    get columnMenuGroups() {
        const out = [];
        for (const col of (this.header ? this.header.columns : [])) {
            const label = col.group || "";
            let group = out.find((x) => x.label === label);
            if (!group) {
                group = { label, keys: [] };
                out.push(group);
            }
            group.keys.push(col.key);
        }
        return out;
    }
    isGroupVisible(group) {
        return group.keys.some((k) => !this.state.hiddenCols[k]);
    }
    toggleColumnGroup(group) {
        const hide = this.isGroupVisible(group);
        for (const key of group.keys) {
            this.state.hiddenCols[key] = hide;
        }
    }
    /** Planes analíticos presentes en las opciones (para el filtro). */
    get analyticPlans() {
        const seen = {};
        const out = [];
        for (const an of (this.header ? this.header.analytic_options : [])) {
            const id = an.plan_id || 0;
            if (!seen[id]) {
                seen[id] = true;
                out.push({ id, name: an.plan_name || "Sin plan" });
            }
        }
        return out;
    }
    /** Cuentas analíticas agrupadas por plan, aplicando el buscador y el
     *  filtro de plan del menú. */
    get groupedAnalyticOptions() {
        const text = this.state.analyticFilter.trim().toUpperCase();
        const planId = this.state.analyticPlanId;
        const groups = [];
        for (const an of (this.header ? this.header.analytic_options : [])) {
            if (planId && (an.plan_id || 0) !== planId) {
                continue;
            }
            if (text && !(an.name || "").toUpperCase().includes(text)) {
                continue;
            }
            const label = an.plan_name || "Sin plan";
            let group = groups.find((x) => x.plan_name === label);
            if (!group) {
                group = { plan_name: label, options: [] };
                groups.push(group);
            }
            group.options.push(an);
        }
        return groups;
    }
    onAnalyticPlanChange(ev) {
        this.state.analyticPlanId = parseInt(ev.target.value, 10) || 0;
    }
    async toggleAnalytic(id) {
        const ids = (this.header.analytic_ids || []).slice();
        const index = ids.indexOf(id);
        if (index === -1) {
            ids.push(id);
        } else {
            ids.splice(index, 1);
        }
        await this.updateFilter("analytic_account_ids", ids);
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

    // --- drilldown a los apuntes (estilo Enterprise) --------------------
    isDrillable(g, col, cell) {
        // Las filas fórmula del Estado de resultados no drillan.
        return g.drillable !== false && col.type === "monetary" &&
            cell && cell.display;
    }
    onGroupCellClick(g, col, ev) {
        const cell = this.getCell(g, col);
        if (!this.isDrillable(g, col, cell)) {
            return; // deja propagar: el click pliega/despliega la fila
        }
        ev.stopPropagation();
        this.openGroupCell(g, col);
    }
    onLineCellClick(g, ln, col, ev) {
        const cell = this.getCell(ln, col);
        if (!ln.line_key || col.type !== "monetary" || !cell.display) {
            return;
        }
        ev.stopPropagation();
        this.openGroupCell(g, col, ln.line_key);
    }
    async openGroupCell(g, col, lineKey = null) {
        try {
            const action = await this._callWizard(
                "action_open_cell", [g.key, col.key, lineKey]);
            await this.action.doAction(action);
        } catch (error) {
            this._notifyError(error);
        }
    }
    openMove(ln) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: ln.move_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // --- desplegar grupos ----------------------------------------------
    async toggleGroup(key) {
        const group = this.groups.find((g) => g.key === key);
        if (group && group.has_lines === false) {
            return;
        }
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
                this._notifyError(error);
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
                if (g.has_lines !== false) {
                    expanded[g.key] = true;
                }
            }
            this.state.expanded = expanded;
        } catch (error) {
            this._notifyError(error);
        } finally {
            this.state.loading = false;
        }
    }
    collapseAll() {
        this.state.expanded = {};
    }

    // --- filtros --------------------------------------------------------
    async updateFilters(vals) {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this._callWizard("update_filters", [vals]);
            this._setData(data);
            this.state.lines = {};
            this.state.expanded = {};
        } catch (error) {
            this._notifyError(error);
        } finally {
            this.state.loading = false;
        }
    }
    async updateFilter(field, value) {
        return this.updateFilters({ [field]: value });
    }

    // --- selector de período (Mes / Trimestre / Año / Personalizado) ----
    _anchor() {
        const iso = this.state.periodAnchor ||
            (this.header && this.header.date_from) || "";
        const [y, m, d] = iso.split("-").map(Number);
        return y ? { y, m, d } : { y: 2000, m: 1, d: 1 };
    }
    _iso(y, m, d) {
        return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    }
    _daysInMonth(y, m) {
        return new Date(y, m, 0).getDate();
    }
    shiftAnchor(months) {
        const a = this._anchor();
        const total = a.y * 12 + (a.m - 1) + months;
        const y = Math.floor(total / 12);
        const m = (total % 12) + 1;
        this.state.periodAnchor = this._iso(y, m, 1);
    }
    get periodMonth() {
        const a = this._anchor();
        const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
        return {
            label: `${MONTHS[a.m - 1]} ${a.y}`,
            from: this._iso(a.y, a.m, 1),
            to: this._iso(a.y, a.m, this._daysInMonth(a.y, a.m)),
        };
    }
    get periodQuarter() {
        const a = this._anchor();
        const SHORT = ["ene", "feb", "mar", "abr", "may", "jun",
            "jul", "ago", "sept", "oct", "nov", "dic"];
        const q = Math.floor((a.m - 1) / 3);
        const m1 = q * 3 + 1;
        const m3 = q * 3 + 3;
        return {
            label: `${SHORT[m1 - 1]} - ${SHORT[m3 - 1]} ${a.y}`,
            from: this._iso(a.y, m1, 1),
            to: this._iso(a.y, m3, this._daysInMonth(a.y, m3)),
        };
    }
    get periodCalendarYear() {
        const a = this._anchor();
        return {
            label: String(a.y),
            from: this._iso(a.y, 1, 1),
            to: this._iso(a.y, 12, 31),
        };
    }
    get periodFiscalYear() {
        const a = this._anchor();
        const lm = (this.header && this.header.fy_last_month) || 12;
        const ld = (this.header && this.header.fy_last_day) || 31;
        // Fin del ejercicio que contiene el ancla.
        let endY = a.y;
        let endD = Math.min(ld, this._daysInMonth(endY, lm));
        if (a.m > lm || (a.m === lm && a.d > endD)) {
            endY += 1;
            endD = Math.min(ld, this._daysInMonth(endY, lm));
        }
        const start = new Date(endY - 1, lm - 1,
            Math.min(ld, this._daysInMonth(endY - 1, lm)));
        start.setDate(start.getDate() + 1);
        const isCalendar = lm === 12 && ld >= 31;
        return {
            label: isCalendar ? String(endY) : `AF ${endY}`,
            from: this._iso(start.getFullYear(), start.getMonth() + 1,
                start.getDate()),
            to: this._iso(endY, lm, endD),
        };
    }
    get periodRows() {
        const rows = [
            { name: "Mes", range: this.periodMonth, step: 1 },
            { name: "Trimestre", range: this.periodQuarter, step: 3 },
            { name: "Año Fiscal", range: this.periodFiscalYear, step: 12 },
        ];
        // Si el ejercicio fiscal coincide con el calendario, una sola fila.
        const fy = this.periodFiscalYear;
        const cy = this.periodCalendarYear;
        if (fy.from !== cy.from || fy.to !== cy.to) {
            rows.push({ name: "Año Calendario", range: cy, step: 12 });
        }
        return rows;
    }
    isActiveRange(range) {
        return !!this.header && this.header.date_from === range.from &&
            this.header.date_to === range.to;
    }
    get isCustomPeriod() {
        return !this.periodRows.some((row) => this.isActiveRange(row.range));
    }
    async selectPeriod(range) {
        this.closeColumnsMenu();
        await this.updateFilters({ date_from: range.from, date_to: range.to });
    }
    toggleCustomDates() {
        this.state.showCustomDates = !this.state.showCustomDates;
    }
    async applyCustomDates() {
        if (!this.state.customFrom || !this.state.customTo) {
            return;
        }
        this.closeColumnsMenu();
        await this.updateFilters({
            date_from: this.state.customFrom,
            date_to: this.state.customTo,
        });
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
    onComparisonPeriodsChange(ev) {
        const value = parseInt(ev.target.value, 10);
        if (!isNaN(value) && value >= 0) {
            this.updateFilter("comparison_periods", value);
        }
    }

    // --- exportación ----------------------------------------------------
    /** Persiste el estado de la vista (buscador, columnas ocultas) para
     *  que el export refleje exactamente lo que se ve en pantalla. */
    async _syncViewState() {
        const hidden = Object.keys(this.state.hiddenCols)
            .filter((k) => this.state.hiddenCols[k]);
        await this._callWizard("set_view_state",
            [this.state.filterText || "", hidden.join(",")]);
    }
    async exportPdf() {
        try {
            await this._syncViewState();
            await this.action.doAction({
                type: "ir.actions.report",
                report_name: "l10n_ar_financial_reports_ce.report_pdf",
                report_type: "qweb-pdf",
                context: { active_ids: [this.wizardId] },
            });
        } catch (error) {
            this._notifyError(error);
        }
    }
    async exportXlsx() {
        try {
            await this._syncViewState();
            window.location = `/l10n_ar_financial_reports_ce/xlsx/${this.wizardId}`;
        } catch (error) {
            this._notifyError(error);
        }
    }
}

registry.category("actions").add("l10n_ar_financial_report", ArFinancialReport);
