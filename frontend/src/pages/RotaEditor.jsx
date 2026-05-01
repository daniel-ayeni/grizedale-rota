import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useParams, Link, useSearchParams } from "react-router-dom";
import {
    ArrowLeft, Lock, Unlock, RefreshCw, AlertTriangle,
    AlertCircle, Copy, Save, Sparkles, Loader2, X, Eraser,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
    Popover, PopoverContent, PopoverTrigger,
} from "@/components/ui/popover";
import {
    Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import {
    Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from "@/components/ui/tooltip";
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
    AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
    AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";
import {
    SHIFT_GROUPS, shiftCellClass,
    SHIFT_LABEL, parseYmd, addDays, dayLetter, isWeekend, ymd, nextShift,
} from "@/lib/shifts";

const ON_CALL_STAFF = ["L.M.", "J.C.", "L.D."];

/* OFF + blank both render as empty cells */
function displayShift(shift) {
    if (!shift || shift === "OFF") return "";
    return SHIFT_LABEL[shift] || shift;
}

/* Horizontal legend strip below the grid */
const LEGEND_ITEMS = [
    { key: "firstaider", label: "First Aider" },
    { key: "al",         label: "Annual Leave" },
    { key: "trn",        label: "Training" },
    { key: "oncall",     label: "On-Call" },
    { key: "sleep",      label: "Sleep In" },
    { key: "paycut",     label: "Pay cut off" },
    { key: "weekend",    label: "Weekend Off" },
    { key: "medcycle",   label: "Medication 28-day cycle" },
    { key: "bus",        label: "Bus" },
    { key: "request",    label: "Request Box" },
];

/* Format the title in the same shape as the paper:
   "GRIZEDALE MONTHLY 20 April 2026 ----- 17 May 2026 ROTA" */
function formatPaperTitle(homeName, fromStr, toStr) {
    const fmt = (s) => {
        const d = parseYmd(s);
        return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
    };
    return `${(homeName || "Grizedale").toUpperCase()} MONTHLY  ${fmt(fromStr)}  -----  ${fmt(toStr)}  ROTA`;
}

export default function RotaEditor() {
    const { id } = useParams();
    const [rota, setRota] = useState(null);
    const [staff, setStaff] = useState([]);
    const [holidays, setHolidays] = useState([]);
    const [requests, setRequests] = useState([]);
    const [violations, setViolations] = useState([]);
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [busyKey, setBusyKey] = useState(null);
    const [payCutOffDate, setPayCutOffDate] = useState(null);
    const [homeName, setHomeName] = useState("Grizedale");
    const violationCellsRef = useRef({ hard: new Set(), soft: new Set() });
    const [violationKey, setViolationKey] = useState(0);
    const [generating, setGenerating] = useState(false);
    const [blockersOpen, setBlockersOpen] = useState(false);
    const [blockers, setBlockers] = useState(null);

    // Multi-cell selection state. `selected` is a Set of cell keys
    // ("YYYY-MM-DD|INITIALS"). Drag-select state lives in `dragRef`.
    const [selected, setSelected] = useState(() => new Set());
    const dragRef = useRef({ active: false, startKey: null });
    // Bulk-action confirmation modal state
    const [bulkConfirm, setBulkConfirm] = useState(null);  // { action, cells }

    const clearSelection = useCallback(() => setSelected(new Set()), []);
    const toggleSelection = useCallback((key, additive) => {
        setSelected((prev) => {
            const next = new Set(additive ? prev : []);
            if (additive && prev.has(key)) {
                next.delete(key);
            } else {
                next.add(key);
            }
            return next;
        });
    }, []);
    const replaceSelection = useCallback((keys) => {
        setSelected(new Set(keys));
    }, []);

    // Drag-select handlers passed down to cells. Pointer events allow
    // both mouse & touch.
    const cellToggleSelect = useCallback((dateStr, init) => {
        // Toggle a cell in/out of the active selection. Used while a multi-
        // select is active (typically started by a week-lock chip): a single
        // click on a selected cell removes it, on an unselected cell adds it.
        // This lets the manager curate the selection cell-by-cell before
        // applying Lock / Unlock / Clear.
        const k = `${dateStr}|${init}`;
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(k)) next.delete(k); else next.add(k);
            return next;
        });
    }, []);

    const onCellPointerDown = useCallback((dateStr, init, ev) => {
        // Plain click on a non-additive (no shift/ctrl) lets the existing
        // shift-cycle handler run; we only start drag-select on shift-drag
        // OR ctrl-drag to keep the single-click cycle behaviour intact.
        if (!ev.shiftKey && !ev.ctrlKey && !ev.metaKey) return;
        ev.preventDefault();
        const k = `${dateStr}|${init}`;
        dragRef.current = { active: true, startKey: k };
        toggleSelection(k, true);
    }, [toggleSelection]);

    const onCellPointerEnter = useCallback((dateStr, init) => {
        if (!dragRef.current.active) return;
        setSelected((prev) => {
            const next = new Set(prev);
            next.add(`${dateStr}|${init}`);
            return next;
        });
    }, []);

    useEffect(() => {
        const onUp = () => { dragRef.current = { active: false, startKey: null }; };
        window.addEventListener("pointerup", onUp);
        return () => window.removeEventListener("pointerup", onUp);
    }, []);

    const generateRota = async () => {
        setGenerating(true);
        try {
            const { data } = await api.post(`/rotas/${id}/generate`);
            await load();
            const summary = data?.validation_report?.summary || { hard: 0, soft: 0 };
            const sec = ((data?.solve_time_ms || 0) / 1000).toFixed(1);
            toast.success(`Rota generated in ${sec}s · ${summary.hard} hard · soft score ${data?.soft_violations_score ?? 0} · ${data?.locked_preserved || 0} locked preserved`);
        } catch (err) {
            const detail = err?.response?.data;
            if (detail && detail.success === false && Array.isArray(detail.blocking_constraints)) {
                setBlockers(detail);
                setBlockersOpen(true);
            } else {
                toast.error(formatApiError(err));
            }
        } finally {
            setGenerating(false);
        }
    };

    const load = async () => {
        try {
            const [rotaRes, staffRes, settingsRes, requestsRes] = await Promise.all([
                api.get(`/rotas/${id}`),
                api.get("/staff"),
                api.get("/settings"),
                api.get("/requests?status=pending"),
            ]);
            setRota(rotaRes.data);
            setStaff(staffRes.data.filter((s) => s.active));
            setHolidays(settingsRes.data?.public_holidays || []);
            setHomeName(settingsRes.data?.home_name || "Grizedale");
            setPayCutOffDate(rotaRes.data?.pay_cut_off_date || null);
            setRequests(requestsRes.data);
            setViolations(rotaRes.data.validation_report?.violations || []);
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };
    useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

    const [searchParams, setSearchParams] = useSearchParams();
    useEffect(() => {
        // Auto-trigger generate when navigated with ?generate=1 (from /dashboard).
        if (searchParams.get("generate") === "1" && rota && !generating) {
            setSearchParams({}, { replace: true });
            generateRota();
        }
        /* eslint-disable-next-line */
    }, [rota]);

    const dates = useMemo(() => {
        if (!rota) return [];
        const start = parseYmd(rota.start_date);
        return Array.from({ length: rota.weeks * 7 }, (_, i) => addDays(start, i));
    }, [rota]);

    const dateStrs = useMemo(() => dates.map(ymd), [dates]);
    const holidayDates = useMemo(() => new Set(holidays.map((h) => h.date)), [holidays]);
    const holidayMap = useMemo(() => {
        const m = new Map();
        for (const h of holidays) m.set(h.date, h.name);
        return m;
    }, [holidays]);

    const cellMap = useMemo(() => {
        const m = new Map();
        if (rota) for (const a of (rota.assignments || [])) m.set(`${a.date}|${a.staff_initials}`, a);
        return m;
    }, [rota]);

    const onCallByDate = useMemo(() => {
        const m = new Map();
        if (rota) for (const o of (rota.on_call || [])) m.set(o.date, o.staff_initials);
        return m;
    }, [rota]);

    const requestsByDate = useMemo(() => {
        const m = new Map();
        for (const r of requests) {
            if (!m.has(r.date)) m.set(r.date, []);
            m.get(r.date).push(r);
        }
        return m;
    }, [requests]);

    /* First Friday → start of medication 28-day cycle */
    const medCycleStartIdx = useMemo(() => {
        for (let i = 0; i < dates.length && i < 7; i++) {
            if (dates[i].getDay() === 5) return i;
        }
        return -1;
    }, [dates]);

    useEffect(() => {
        const hard = new Set();
        const soft = new Set();
        for (const v of violations) {
            for (const c of (v.affected_cells || [])) {
                (v.severity === "hard" ? hard : soft).add(`${c.date}|${c.staff_initials}`);
            }
        }
        violationCellsRef.current = { hard, soft };
        setViolationKey((k) => k + 1);
    }, [violations]);

    const summary = useMemo(() => {
        const hard = violations.filter((v) => v.severity === "hard").length;
        const soft = violations.filter((v) => v.severity === "soft").length;
        return { hard, soft, total: violations.length };
    }, [violations]);

    const onCellClick = async (dateStr, init) => {
        const k = `${dateStr}|${init}`;
        const cur = cellMap.get(k);
        if (cur?.locked) {
            toast.info("Cell is locked. Right-click to unlock or change.");
            return;
        }
        const newShift = nextShift(cur?.shift || "");
        await patchCell(dateStr, init, newShift, cur?.locked || false);
    };

    const patchCell = async (dateStr, init, shift, locked, reason) => {
        const k = `${dateStr}|${init}`;
        setBusyKey(k);
        try {
            const { data } = await api.patch(`/rotas/${id}/cell`, {
                date: dateStr, staff_initials: init, shift, locked: !!locked, reason: reason || null,
            });
            setRota((r) => {
                if (!r) return r;
                const filtered = (r.assignments || []).filter(
                    (a) => !(a.date === dateStr && a.staff_initials === init),
                );
                filtered.push(data.cell);
                return { ...r, assignments: filtered };
            });
            setViolations(data.validation_report?.violations || []);
        } catch (err) {
            toast.error(formatApiError(err));
        } finally {
            setBusyKey(null);
        }
    };

    const setOnCall = async (dateStr, init) => {
        try {
            const newOnCall = (rota.on_call || []).filter((o) => o.date !== dateStr);
            if (init && init !== "_clear_") newOnCall.push({ date: dateStr, staff_initials: init });
            await api.put(`/rotas/${id}`, { on_call: newOnCall });
            await load();
        } catch (err) { toast.error(formatApiError(err)); }
    };

    const setPayCutOff = async (dateStr) => {
        try {
            await api.put(`/rotas/${id}`, { pay_cut_off_date: dateStr || null });
            setPayCutOffDate(dateStr || null);
            toast.success(dateStr ? `Pay cut-off set to ${dateStr}` : "Pay cut-off cleared");
        } catch (err) { toast.error(formatApiError(err)); }
    };

    /* Select an entire week's cells (7 days × all staff). Triggered by the
       "Lock week" chip in the top header row. Toggles: clicking the same
       week's chip again clears the selection so managers can quickly back
       out of a multi-select without having to find a "deselect" button. */
    const selectWeek = useCallback((weekIdx) => {
        const startDay = weekIdx * 7;
        const endDay = Math.min(startDay + 7, dateStrs.length);
        const keys = [];
        for (let i = startDay; i < endDay; i++) {
            const ds = dateStrs[i];
            for (const s of staff) keys.push(`${ds}|${s.initials}`);
        }
        // Toggle: if the current selection is exactly this week's keys,
        // clear instead of re-selecting.
        const isSameWeekSelected =
            selected.size === keys.length
            && keys.every((k) => selected.has(k));
        if (isSameWeekSelected) {
            clearSelection();
            return;
        }
        replaceSelection(keys);
        toast.info(`Selected week ${weekIdx + 1} — ${keys.length} cells`);
    }, [dateStrs, staff, replaceSelection, selected, clearSelection]);

    /* Per-week-selection helper: tells render whether a given week's chip
       should display the "active" (toggle-off) visual state. */
    const isWeekFullySelected = useCallback((weekIdx) => {
        const startDay = weekIdx * 7;
        const endDay = Math.min(startDay + 7, dateStrs.length);
        if (selected.size !== (endDay - startDay) * staff.length) return false;
        for (let i = startDay; i < endDay; i++) {
            const ds = dateStrs[i];
            for (const s of staff) {
                if (!selected.has(`${ds}|${s.initials}`)) return false;
            }
        }
        return true;
    }, [dateStrs, staff, selected]);

    /* Escape key clears the multi-select. */
    useEffect(() => {
        const onKey = (e) => {
            if (e.key === "Escape" && selected.size > 0) clearSelection();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [selected.size, clearSelection]);

    /* Atomic bulk PATCH. action = "lock" | "unlock" | "clear" */
    const applyBulkAction = useCallback(async (action) => {
        const cells = Array.from(selected).map((k) => {
            const [date, init] = k.split("|");
            return { date, staff_initials: init };
        });
        if (cells.length === 0) return;
        const updates = cells.map((c) => {
            if (action === "lock")   return { ...c, locked: true };
            if (action === "unlock") return { ...c, locked: false };
            if (action === "clear")  return { ...c, shift: "", locked: false };
            return c;
        });
        const force = action === "unlock" || action === "clear";
        try {
            const { data } = await api.patch(`/rotas/${id}/cells`, { updates, force });
            setViolations(data?.validation_report?.violations || []);
            await load();
            const skipped = (data?.skipped_locked || []).length;
            const applied = data?.applied || 0;
            toast.success(
                `${action === "lock" ? "Locked" : action === "unlock" ? "Unlocked" : "Cleared"} `
                + `${applied} cell${applied === 1 ? "" : "s"}`
                + (skipped > 0 ? ` (skipped ${skipped} locked)` : "")
            );
            clearSelection();
        } catch (err) { toast.error(formatApiError(err)); }
    }, [id, selected, clearSelection]);  // eslint-disable-line react-hooks/exhaustive-deps

    if (!rota) {
        return <div className="text-sm text-muted-foreground" data-testid="rota-loading">Loading rota…</div>;
    }

    const fromStr = rota.start_date;
    const toStr = dateStrs[dateStrs.length - 1];
    const paperTitle = formatPaperTitle(homeName, fromStr, toStr);

    return (
        <div className="space-y-3" data-testid="rota-editor-page">
            {/* Slim toolbar above the grid */}
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                <div className="flex items-center gap-3">
                    <Link to="/rotas" className="text-xs text-muted-foreground inline-flex items-center gap-1" data-testid="rota-back">
                        <ArrowLeft className="w-3 h-3" /> Rotas
                    </Link>
                    <span className="text-sm text-muted-foreground">{rota.title} · {fromStr} → {toStr} · {rota.weeks}w</span>
                    <Badge variant={rota.status === "published" ? "default" : "outline"} data-testid="rota-status-badge">{rota.status}</Badge>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <AlertDialog>
                        <AlertDialogTrigger asChild>
                            <Button className="btn-primary" size="sm" disabled={generating} data-testid="rota-generate-button">
                                {generating
                                    ? <><Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> Solving…</>
                                    : <><Sparkles className="w-3.5 h-3.5 mr-1.5" /> Generate Rota</>}
                            </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent data-testid="rota-generate-confirm">
                            <AlertDialogHeader>
                                <AlertDialogTitle>Generate this rota?</AlertDialogTitle>
                                <AlertDialogDescription>
                                    The solver will fill all empty unlocked cells. Locked cells, AL, TRN
                                    and on-call assignments will be preserved. Up to 15s.
                                </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                                <AlertDialogCancel data-testid="rota-generate-cancel">Cancel</AlertDialogCancel>
                                <AlertDialogAction onClick={generateRota} data-testid="rota-generate-confirm-btn">Generate</AlertDialogAction>
                            </AlertDialogFooter>
                        </AlertDialogContent>
                    </AlertDialog>
                    <Button variant="outline" size="sm" onClick={async () => {
                        try {
                            const res = await api.post(`/rotas/${id}/copy-from-previous`);
                            const h = res.data?.validation_report?.summary?.hard ?? 0;
                            toast.success(`Copied ${res.data.assignments_count} cells. ${h} hard violations to review.`);
                            await load();
                        } catch (err) { toast.error(formatApiError(err)); }
                    }} data-testid="rota-copy-from-previous">
                        <Copy className="w-3.5 h-3.5 mr-1.5" /> Copy
                    </Button>
                    <Popover>
                        <PopoverTrigger asChild>
                            <Button variant="outline" size="sm" data-testid="rota-paycutoff-button">Pay cut-off: {payCutOffDate || "—"}</Button>
                        </PopoverTrigger>
                        <PopoverContent className="w-60 p-2 space-y-2" align="end">
                            <Label className="text-xs uppercase tracking-wider text-muted-foreground">Set pay cut-off date</Label>
                            <Input type="date" defaultValue={payCutOffDate || ""}
                                onChange={(e) => setPayCutOff(e.target.value || null)}
                                data-testid="rota-paycutoff-input" />
                            {payCutOffDate && <Button size="sm" variant="ghost" className="w-full" onClick={() => setPayCutOff(null)} data-testid="rota-paycutoff-clear">Clear</Button>}
                        </PopoverContent>
                    </Popover>
                    <Button variant="outline" size="sm" onClick={async () => {
                        try {
                            const res = await api.post(`/rotas/${id}/validate`);
                            setViolations(res.data?.violations || []);
                            toast.info(`Validation: ${res.data?.summary?.hard || 0} hard, ${res.data?.summary?.soft || 0} soft`);
                            setDrawerOpen(true);
                        } catch (err) { toast.error(formatApiError(err)); }
                    }} data-testid="rota-validate-button">
                        <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Validate
                    </Button>
                    <Button
                        variant={summary.hard > 0 ? "destructive" : "outline"}
                        size="sm"
                        onClick={() => setDrawerOpen(true)}
                        data-testid="rota-violations-button"
                    >
                        <AlertTriangle className="w-3.5 h-3.5 mr-1.5" />
                        {summary.hard} hard {summary.soft > 0 ? `· ${summary.soft} soft` : ""}
                    </Button>
                    <Button className="btn-primary" size="sm" onClick={async () => {
                        try {
                            await api.put(`/rotas/${id}`, { status: rota.status === "draft" ? "published" : "draft" });
                            toast.success(rota.status === "draft" ? "Published" : "Reverted to draft");
                            await load();
                        } catch (err) { toast.error(formatApiError(err)); }
                    }} data-testid="rota-publish-button">
                        <Save className="w-3.5 h-3.5 mr-1.5" /> {rota.status === "draft" ? "Publish" : "Revert"}
                    </Button>
                </div>
            </div>

            {/* Italic blue title — sits centred above the grid */}
            <div className="px-2 pt-1">
                <h1 className="rota-paper-title" data-testid="rota-grid-title">{paperTitle}</h1>
            </div>

            {/* Grid wrapper with horizontal scroll */}
            <TooltipProvider delayDuration={150}>
                <div className="rota-grid-wrap" data-testid="rota-grid-wrap">
                    <div className="rota-grid" data-testid="rota-grid" data-violation-key={violationKey}>
                        {/* HEADER ROW 1 (NEW): week-lock chip row — one cell
                            per week spanning 7 day columns, prominent
                            chip-button to bulk-select all cells in that week.
                            The corner cell from row 1 is span-3 to occupy
                            this row + the day-letter + date rows. */}
                        <div className="rota-corner-cell" data-testid="rota-corner-cell" aria-hidden="true">
                            Week
                        </div>
                        {Array.from({ length: Math.ceil(dates.length / 7) }, (_, w) => {
                            const startDate = dates[w * 7];
                            const endDate = dates[Math.min(w * 7 + 6, dates.length - 1)];
                            const isLastWeek = w === Math.ceil(dates.length / 7) - 1;
                            const fmt = (d) => `${d.getDate()} ${d.toLocaleString('en-GB', { month: 'short' })}`;
                            const range = `${fmt(startDate)} – ${fmt(endDate)}`;
                            const active = isWeekFullySelected(w);
                            return (
                                <div
                                    key={`wh-${w}`}
                                    className={`rota-week-header ${!isLastWeek ? "week-divider" : ""}`}
                                >
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <button
                                                type="button"
                                                className={`week-lock-btn ${active ? "active" : ""}`}
                                                onClick={() => selectWeek(w)}
                                                data-testid={`week-select-${w + 1}`}
                                                aria-pressed={active}
                                            >
                                                <Lock className="w-3.5 h-3.5" /> W{w + 1}
                                            </button>
                                        </TooltipTrigger>
                                        <TooltipContent>
                                            {active
                                                ? `Click to deselect week ${w + 1}`
                                                : `Select all cells in Week ${w + 1} (${range})`}
                                        </TooltipContent>
                                    </Tooltip>
                                </div>
                            );
                        })}

                        {/* HEADER ROW 2: 28 day-letter cells (no chips inside; chips moved up) */}
                        {dates.map((d, i) => {
                            const ds = dateStrs[i];
                            const we = isWeekend(d);
                            const isWeekEnd = (i + 1) % 7 === 0 && i < dates.length - 1;
                            const isMedCycle = i === medCycleStartIdx;
                            return (
                                <div
                                    key={`dl-${ds}`}
                                    className={`rota-header-day ${we ? "weekend" : ""} ${isWeekEnd ? "week-divider" : ""}`}
                                    data-testid={`grid-dayletter-${ds}`}
                                >
                                    {isMedCycle && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <span className="med-cycle-flag" data-testid="med-cycle-flag" />
                                            </TooltipTrigger>
                                            <TooltipContent>Medication 28-day cycle starts here</TooltipContent>
                                        </Tooltip>
                                    )}
                                    {dayLetter(d)}
                                </div>
                            );
                        })}

                        {/* HEADER ROW 2: identity-column header (peach merged with row 1) + 28 date-number cells */}
                        <div className="rota-corner-cell rota-corner-cell-bottom" aria-hidden="true" />
                        {dates.map((d, i) => {
                            const ds = dateStrs[i];
                            const we = isWeekend(d);
                            const isWeekEnd = (i + 1) % 7 === 0 && i < dates.length - 1;
                            const hol = holidayDates.has(ds);
                            const isPayCut = ds === payCutOffDate;
                            const reqs = requestsByDate.get(ds);
                            return (
                                <Tooltip key={`dn-${ds}`}>
                                    <TooltipTrigger asChild>
                                        <div
                                            className={`rota-header-date ${we ? "weekend" : ""} ${isWeekEnd ? "week-divider" : ""}`}
                                            data-testid={`grid-datenum-${ds}`}
                                        >
                                            {d.getDate()}
                                            {(hol || isPayCut || (reqs && reqs.length > 0)) && (
                                                <span className="header-marker-row">
                                                    {hol && <span className="marker-dot" style={{ background: "#A8C5E0" }} />}
                                                    {isPayCut && <span className="marker-dot" style={{ background: "#C8CCD0" }} />}
                                                    {reqs && reqs.length > 0 && (
                                                        <Popover>
                                                            <PopoverTrigger asChild>
                                                                <button type="button" className="marker-dot"
                                                                    style={{ background: "hsl(var(--accent-red))", cursor: "pointer" }}
                                                                    data-testid={`req-marker-${ds}`} />
                                                            </PopoverTrigger>
                                                            <PopoverContent align="center" className="w-72">
                                                                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Pending requests · {ds}</div>
                                                                {reqs.map((r) => (
                                                                    <div key={r.id} className="text-xs border-t py-1.5" style={{ borderColor: "hsl(var(--border))" }}>
                                                                        <div className="font-semibold">{r.staff_initials} · {r.shift_preference}</div>
                                                                        {r.notes && <div className="text-muted-foreground">{r.notes}</div>}
                                                                    </div>
                                                                ))}
                                                            </PopoverContent>
                                                        </Popover>
                                                    )}
                                                </span>
                                            )}
                                        </div>
                                    </TooltipTrigger>
                                    {hol && <TooltipContent>{holidayMap.get(ds)}</TooltipContent>}
                                    {isPayCut && <TooltipContent>Pay cut-off date</TooltipContent>}
                                </Tooltip>
                            );
                        })}

                        {/* STAFF ROWS */}
                        {staff.map((s) => (
                            <StaffRow
                                key={s.initials}
                                s={s}
                                dateStrs={dateStrs}
                                cellMap={cellMap}
                                onCallByDate={onCallByDate}
                                onClick={onCellClick}
                                onPatch={patchCell}
                                onSetOnCall={setOnCall}
                                violationCellsRef={violationCellsRef}
                                busyKey={busyKey}
                                selected={selected}
                                onPointerDown={onCellPointerDown}
                                onPointerEnter={onCellPointerEnter}
                                onToggleSelect={cellToggleSelect}
                            />
                        ))}
                    </div>
                </div>
            </TooltipProvider>

            {/* Bulk-action toolbar — visible when 1+ cell is selected */}
            {selected.size > 0 && (
                <div
                    className="bulk-action-toolbar"
                    data-testid="bulk-action-toolbar"
                    style={{ display: "inline-flex" }}
                >
                    <span className="count" data-testid="bulk-count">{selected.size}</span>
                    <span className="count-staff">cell{selected.size === 1 ? "" : "s"} selected</span>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setBulkConfirm({ action: "lock", cells: selected.size })}
                        data-testid="bulk-lock-button"
                    >
                        <Lock className="w-3.5 h-3.5 mr-1.5" /> Lock
                    </Button>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setBulkConfirm({ action: "unlock", cells: selected.size })}
                        data-testid="bulk-unlock-button"
                    >
                        <Unlock className="w-3.5 h-3.5 mr-1.5" /> Unlock
                    </Button>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setBulkConfirm({ action: "clear", cells: selected.size })}
                        data-testid="bulk-clear-button"
                    >
                        <Eraser className="w-3.5 h-3.5 mr-1.5" /> Clear
                    </Button>
                    <Button
                        size="sm"
                        variant="ghost"
                        onClick={clearSelection}
                        title="Deselect all"
                        data-testid="bulk-deselect-button"
                    >
                        <X className="w-3.5 h-3.5" />
                    </Button>
                </div>
            )}

            {/* Bulk-action confirmation modal */}
            <AlertDialog
                open={!!bulkConfirm}
                onOpenChange={(o) => { if (!o) setBulkConfirm(null); }}
            >
                <AlertDialogContent data-testid="bulk-confirm-dialog">
                    <AlertDialogHeader>
                        <AlertDialogTitle>
                            {bulkConfirm?.action === "lock"   && `Lock ${bulkConfirm.cells} cell${bulkConfirm.cells === 1 ? "" : "s"}?`}
                            {bulkConfirm?.action === "unlock" && `Unlock ${bulkConfirm.cells} cell${bulkConfirm.cells === 1 ? "" : "s"}?`}
                            {bulkConfirm?.action === "clear"  && `Clear ${bulkConfirm.cells} cell${bulkConfirm.cells === 1 ? "" : "s"}?`}
                        </AlertDialogTitle>
                        <AlertDialogDescription>
                            {bulkConfirm?.action === "lock"   && "Locked cells are protected from the click-cycle and from being overwritten by 'Generate Rota'. They can still be edited via the right-click popover."}
                            {bulkConfirm?.action === "unlock" && "Unlocking allows the cells to be modified again, including by the solver during 'Generate Rota'."}
                            {bulkConfirm?.action === "clear"  && "Sets each selected cell to blank (and unlocks it). The solver may refill these on the next generate."}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel data-testid="bulk-confirm-cancel">Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={() => {
                                const action = bulkConfirm.action;
                                setBulkConfirm(null);
                                applyBulkAction(action);
                            }}
                            data-testid="bulk-confirm-ok"
                        >
                            Confirm
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>

            {/* Validation Issues panel — sits between the grid and the legend strip */}
            <ValidationIssuesPanel
                violations={violations}
                onCellPing={(date, init) => {
                    const sel = `[data-testid="cell-${date}-${init}"]`;
                    const el = document.querySelector(sel);
                    if (!el) return;
                    el.scrollIntoView({ behavior: "smooth", block: "center" });
                    el.classList.add("violation-pulse");
                    setTimeout(() => el.classList.remove("violation-pulse"), 1200);
                }}
            />

            {/* Legend strip BELOW the grid */}
            <div className="rota-legend-strip" data-testid="rota-legend-strip">
                {LEGEND_ITEMS.map((it) => (
                    <span key={it.key} className="legend-item" data-testid={`legend-${it.key}`}>
                        <span className={`legend-swatch ${it.key}`} />
                        {it.label}
                    </span>
                ))}
            </div>

            {/* Violations drawer */}
            <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
                <SheetContent className="overflow-y-auto sm:max-w-md" data-testid="violations-drawer">
                    <SheetHeader>
                        <SheetTitle>Validation report</SheetTitle>
                        <SheetDescription>
                            {summary.hard} hard · {summary.soft} soft preference
                        </SheetDescription>
                    </SheetHeader>
                    <div className="mt-4 space-y-3">
                        {violations.length === 0 && (
                            <div className="text-sm text-muted-foreground py-4">No violations. Rota is valid.</div>
                        )}
                        {violations.map((v, idx) => (
                            <div key={idx} className="app-card p-3" data-testid={`violation-${idx}`}>
                                <div className="flex items-center gap-2 text-xs uppercase tracking-wider">
                                    {v.severity === "hard"
                                        ? <AlertCircle className="w-3.5 h-3.5 text-destructive" />
                                        : <AlertTriangle className="w-3.5 h-3.5" style={{ color: "hsl(var(--accent-yellow))" }} />}
                                    <span style={{ color: v.severity === "hard" ? "hsl(var(--destructive))" : "hsl(var(--fg-muted))" }}>
                                        {v.severity}
                                    </span>
                                    <span className="text-muted-foreground">·</span>
                                    <span className="font-semibold normal-case tracking-normal">{v.rule_name}</span>
                                </div>
                                <div className="text-sm mt-1.5">{v.message}</div>
                                {v.date && <div className="text-xs text-muted-foreground mt-0.5">{v.date}{v.staff_initials ? ` · ${v.staff_initials}` : ""}</div>}
                            </div>
                        ))}
                    </div>
                </SheetContent>
            </Sheet>

            {/* Blockers modal — shown when /generate returns success:false */}
            <Dialog open={blockersOpen} onOpenChange={setBlockersOpen}>
                <DialogContent data-testid="blockers-dialog">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <AlertCircle className="w-5 h-5 text-destructive" />
                            Cannot generate — over-constrained
                        </DialogTitle>
                        <DialogDescription>{blockers?.reason}</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-2 max-h-[420px] overflow-y-auto">
                        {(blockers?.blocking_constraints || []).map((b, idx) => (
                            <div key={idx} className="app-card p-3" data-testid={`blocker-${idx}`}>
                                <div className="text-sm font-semibold">{b.day_of_week} · {b.date}</div>
                                <ul className="text-xs text-muted-foreground mt-1.5 list-disc list-inside space-y-0.5">
                                    {(b.problems || []).map((p, i) => <li key={i}>{p}</li>)}
                                </ul>
                            </div>
                        ))}
                        {(!blockers?.blocking_constraints || blockers.blocking_constraints.length === 0) && (
                            <div className="text-sm text-muted-foreground py-4">{blockers?.solver_status || "Solver could not find a valid rota."}</div>
                        )}
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setBlockersOpen(false)} data-testid="blockers-close">Close</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

function StaffRow({ s, dateStrs, cellMap, onCallByDate, onClick, onPatch, onSetOnCall, violationCellsRef, busyKey, selected, onPointerDown, onPointerEnter, onToggleSelect }) {
    return (
        <>
            <div className="rota-identity-cell" data-testid={`row-label-${s.initials}`}>
                <div className="ident-role">{s.role}</div>
                <div className="ident-name-line">
                    <span className="ident-initials">{s.initials}</span>
                    <span className="ident-hours">{s.target_weekly_hours}</span>
                </div>
            </div>
            {dateStrs.map((ds, i) => {
                const cell = cellMap.get(`${ds}|${s.initials}`);
                const shift = cell?.shift || "";
                const locked = !!cell?.locked;
                const k = `${ds}|${s.initials}`;
                const hard = violationCellsRef.current.hard.has(k);
                const soft = violationCellsRef.current.soft.has(k);
                const isWeekEnd = (i + 1) % 7 === 0 && i < dateStrs.length - 1;
                const onCall = onCallByDate.get(ds) === s.initials;
                const isSelected = selected && selected.has(k);

                const cellCls = `${shiftCellClass(shift)} ${locked ? "locked" : ""} ${hard ? "violation-hard" : ""} ${soft && !hard ? "violation-soft" : ""} ${isWeekEnd ? "week-divider" : ""} ${isSelected ? "selected" : ""}`;
                const busy = busyKey === k;
                const isOnCallEditable = ON_CALL_STAFF.includes(s.initials);

                return (
                    <CellWithMenu
                        key={ds}
                        dateStr={ds}
                        init={s.initials}
                        shift={shift}
                        locked={locked}
                        cls={cellCls}
                        onClick={() => onClick(ds, s.initials)}
                        onPatch={onPatch}
                        onCall={onCall}
                        onSetOnCall={onSetOnCall}
                        isOnCallEditable={isOnCallEditable}
                        busy={busy}
                        onPointerDown={onPointerDown}
                        onPointerEnter={onPointerEnter}
                        onToggleSelect={onToggleSelect}
                        isSelected={isSelected}
                        anySelected={selected && selected.size > 0}
                    />
                );
            })}
        </>
    );
}

function CellWithMenu({ dateStr, init, shift, locked, cls, onClick, onPatch, onCall, onSetOnCall, isOnCallEditable, busy, onPointerDown, onPointerEnter, onToggleSelect, isSelected, anySelected }) {
    const [open, setOpen] = useState(false);
    const [draft, setDraft] = useState({ shift, locked, reason: "" });
    useEffect(() => { setDraft({ shift, locked, reason: "" }); }, [shift, locked, dateStr, init]);

    const save = async () => {
        await onPatch(dateStr, init, draft.shift, !!draft.locked, draft.reason || null);
        setOpen(false);
    };

    const handleClick = (e) => {
        // shift/ctrl/meta-click is reserved for drag/multi-select; the
        // pointerDown handler already captures these.
        if (e.shiftKey || e.ctrlKey || e.metaKey) return;
        // While a multi-select is active, single-click TOGGLES this cell's
        // membership in the selection — removes if currently selected,
        // adds if not. This lets the manager curate the week-lock selection
        // cell-by-cell ("select W1 then deselect the 3 days I want to leave
        // unlocked"). No shift-cycle, no popover.
        if (anySelected) {
            if (onToggleSelect) onToggleSelect(dateStr, init);
            return;
        }
        onClick();
    };

    const handleContextMenu = (e) => {
        e.preventDefault();
        // While in a multi-select, the right-click popover is also disabled
        // — the bulk-action toolbar is the single edit channel.
        if (anySelected) return;
        setOpen(true);
    };

    return (
        <Popover open={anySelected ? false : open} onOpenChange={(v) => { if (!anySelected) setOpen(v); }}>
            <PopoverTrigger asChild>
                <button
                    type="button"
                    className={cls}
                    onClick={handleClick}
                    onContextMenu={handleContextMenu}
                    onPointerDown={(e) => {
                        // While a multi-select is active, suppress the trigger
                        // entirely so Radix never opens the popover.
                        if (anySelected) { e.preventDefault(); e.stopPropagation(); return; }
                        if (onPointerDown) onPointerDown(dateStr, init, e);
                    }}
                    onPointerEnter={() => onPointerEnter && onPointerEnter(dateStr, init)}
                    data-testid={`cell-${dateStr}-${init}`}
                    disabled={busy}
                    title={
                        anySelected
                            ? (isSelected
                                ? "Click to remove from selection"
                                : "Click to add to selection")
                            : (shift ? SHIFT_LABEL[shift] : "")
                    }
                    aria-pressed={anySelected ? isSelected : undefined}
                >
                    {displayShift(shift)}
                    {onCall && <span className="oncall-chip">on-call</span>}
                </button>
            </PopoverTrigger>
            <PopoverContent className="w-72" align="center" data-testid={`cell-popover-${dateStr}-${init}`}>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">{init} · {dateStr}</div>
                {/* Grouped shift picker — Working / Off / Leave so AL/TRN
                    are visually demoted to the bottom group and never
                    surface as the "default" choice. */}
                {Object.entries(SHIFT_GROUPS).map(([group, options]) => (
                    <div key={group} className={`shift-popover-group ${group.toLowerCase()}`}>
                        <div className="shift-popover-group-label">{group}</div>
                        <div className="grid grid-cols-4 gap-1">
                            {options.map((sh) => (
                                <Button
                                    key={sh || "blank"}
                                    variant={draft.shift === sh ? "default" : "outline"}
                                    size="sm"
                                    className={draft.shift === sh ? "btn-primary" : ""}
                                    onClick={() => setDraft((d) => ({ ...d, shift: sh }))}
                                    data-testid={`cell-popover-shift-${(sh || "blank").replace("*", "star")}`}
                                >
                                    {SHIFT_LABEL[sh] || "—"}
                                </Button>
                            ))}
                        </div>
                    </div>
                ))}
                <div className="flex items-center justify-between mt-3 p-2 rounded border" style={{ borderColor: "hsl(var(--border))" }}>
                    <Label className="text-sm flex items-center gap-1.5">
                        {draft.locked ? <Lock className="w-3.5 h-3.5" /> : <Unlock className="w-3.5 h-3.5" />}
                        Lock cell
                    </Label>
                    <Switch checked={draft.locked} onCheckedChange={(v) => setDraft((d) => ({ ...d, locked: v }))} data-testid="cell-popover-lock" />
                </div>
                {isOnCallEditable && (
                    <div className="flex items-center justify-between mt-2 p-2 rounded border" style={{ borderColor: "hsl(var(--border))" }}>
                        <Label className="text-sm">Mark on-call</Label>
                        <Switch checked={onCall}
                            onCheckedChange={(v) => onSetOnCall(dateStr, v ? init : "_clear_")}
                            data-testid="cell-popover-oncall" />
                    </div>
                )}
                <div className="mt-2">
                    <Label className="text-xs uppercase tracking-wider text-muted-foreground">Reason (optional)</Label>
                    <Input value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} placeholder="e.g. requested by L.M." className="mt-1" data-testid="cell-popover-reason" />
                </div>
                <Button className="btn-primary w-full mt-3" onClick={save} data-testid="cell-popover-save">Save</Button>
            </PopoverContent>
        </Popover>
    );
}


/**
 * ValidationIssuesPanel — renders all current rule violations for the rota
 * directly below the grid, above the legend strip. Hidden when 0 issues.
 *
 * Rows are sorted hard-first then by date. Each row is clickable: clicking
 * scrolls to the first affected cell and pulses its border briefly.
 */
function ValidationIssuesPanel({ violations, onCellPing }) {
    const list = Array.isArray(violations) ? violations : [];
    if (list.length === 0) return null;

    const hardCount = list.filter((v) => v.severity === "hard").length;
    const softCount = list.length - hardCount;

    const ordered = [...list].sort((a, b) => {
        const sev = (a.severity === "hard" ? 0 : 1) - (b.severity === "hard" ? 0 : 1);
        if (sev !== 0) return sev;
        return (a.date || "").localeCompare(b.date || "");
    });

    const fmtDate = (iso) => {
        if (!iso) return "";
        const d = new Date(iso + "T00:00:00");
        return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
    };

    return (
        <div className="rota-validation-panel" data-testid="validation-issues-panel">
            <div className="validation-header">
                <span className="validation-title">Validation Issues</span>
                {hardCount > 0 && (
                    <span className="validation-chip chip-hard" data-testid="validation-hard-chip">
                        {hardCount} hard error{hardCount === 1 ? "" : "s"}
                    </span>
                )}
                {softCount > 0 && (
                    <span className="validation-chip chip-soft" data-testid="validation-soft-chip">
                        {softCount} soft warning{softCount === 1 ? "" : "s"}
                    </span>
                )}
            </div>
            <ul className="validation-list">
                {ordered.map((v, idx) => {
                    const cells = Array.isArray(v.affected_cells) ? v.affected_cells : [];
                    const inits = Array.from(new Set(cells.map((c) => c.staff_initials).filter(Boolean)));
                    const firstCell = cells[0];
                    const onClick = firstCell ? () => onCellPing(firstCell.date, firstCell.staff_initials) : undefined;
                    return (
                        <li
                            key={`${v.rule_id}-${v.date || "none"}-${idx}`}
                            className={`validation-row sev-${v.severity}`}
                            onClick={onClick}
                            role={onClick ? "button" : undefined}
                            tabIndex={onClick ? 0 : -1}
                            data-testid={`validation-row-${idx}`}
                        >
                            <span className={`validation-sev sev-${v.severity}`} aria-hidden="true">
                                {v.severity === "hard" ? "●" : "▲"}
                            </span>
                            <span className="validation-date">{fmtDate(v.date)}</span>
                            {inits.length > 0 && (
                                <span className="validation-staff">
                                    {inits.map((i) => (
                                        <span key={i} className="validation-staff-chip">{i}</span>
                                    ))}
                                </span>
                            )}
                            <span className="validation-message">{v.message}</span>
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}
