import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
    ArrowLeft, Lock, Unlock, RefreshCw, AlertTriangle,
    AlertCircle, Copy, Save,
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
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";
import {
    SHIFT_TYPES, shiftCellClass,
    SHIFT_LABEL, parseYmd, addDays, dayLetter, isWeekend, ymd, nextShift,
} from "@/lib/shifts";

const ON_CALL_STAFF = ["L.M.", "J.C.", "L.D."];

/* Visual cell display: OFF renders blank, otherwise the shift letter */
function displayShift(shift) {
    if (!shift || shift === "OFF") return "";
    return SHIFT_LABEL[shift] || shift;
}

const LEGEND_BLOCKS = [
    { key: "firstaider", label: "First Aider" },
    { key: "al",         label: "Annual Leave" },
    { key: "trn",        label: "Training" },
    { key: "oncall",     label: "On-Call" },
    { key: "sleep",      label: "Sleep In" },
    { key: "paycut",     label: "Pay cut off" },
    { key: "weekend",    label: "Weekend Off" },
    { key: "medcycle",   label: "Med 28-day cycle" },
    { key: "bus",        label: "Bus" },
    { key: "request",    label: "Request Box" },
];

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
    const violationCellsRef = useRef({ hard: new Set(), soft: new Set() });
    const [violationKey, setViolationKey] = useState(0);

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
            setPayCutOffDate(rotaRes.data?.pay_cut_off_date || null);
            setRequests(requestsRes.data);
            setViolations(rotaRes.data.validation_report?.violations || []);
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };
    useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

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

    // First Friday → start of medication 28-day cycle
    const medCycleStartIdx = useMemo(() => {
        for (let i = 0; i < dates.length && i < 7; i++) {
            if (dates[i].getDay() === 5) return i;
        }
        return -1;
    }, [dates]);

    // Per-week weekend-off staff (Sat & Sun both blank)
    const weekendOffByWeek = useMemo(() => {
        if (!rota) return [];
        const out = [];
        for (let w = 0; w < (rota.weeks || 4); w++) {
            const sat = dateStrs[w * 7 + 5];
            const sun = dateStrs[w * 7 + 6];
            const isWorking = (sh) => sh && !["", "OFF", "AL", "TRN"].includes(sh);
            out.push(
                staff
                    .filter((s) =>
                        !isWorking(cellMap.get(`${sat}|${s.initials}`)?.shift) &&
                        !isWorking(cellMap.get(`${sun}|${s.initials}`)?.shift),
                    )
                    .map((s) => s.initials),
            );
        }
        return out;
    }, [rota, dateStrs, staff, cellMap]);

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

    if (!rota) {
        return <div className="text-sm text-muted-foreground" data-testid="rota-loading">Loading rota…</div>;
    }

    const titleRange = `${rota.start_date} ───── ${dateStrs[dateStrs.length - 1]}`;

    return (
        <div className="space-y-4" data-testid="rota-editor-page">
            {/* Top toolbar */}
            <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-3">
                <div>
                    <Link to="/rotas" className="text-xs text-muted-foreground inline-flex items-center gap-1 mb-1" data-testid="rota-back">
                        <ArrowLeft className="w-3 h-3" /> Rotas
                    </Link>
                    <div className="text-sm text-muted-foreground">{rota.title} · {rota.weeks} weeks</div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={rota.status === "published" ? "default" : "outline"} data-testid="rota-status-badge">{rota.status}</Badge>
                    <Button variant="outline" onClick={async () => {
                        try {
                            const res = await api.post(`/rotas/${id}/copy-from-previous`);
                            const h = res.data?.validation_report?.summary?.hard ?? 0;
                            toast.success(`Copied ${res.data.assignments_count} cells. ${h} hard violations to review.`);
                            await load();
                        } catch (err) { toast.error(formatApiError(err)); }
                    }} data-testid="rota-copy-from-previous">
                        <Copy className="w-4 h-4 mr-1.5" /> Copy from previous
                    </Button>
                    <Popover>
                        <PopoverTrigger asChild>
                            <Button variant="outline" data-testid="rota-paycutoff-button">Pay cut-off: {payCutOffDate || "—"}</Button>
                        </PopoverTrigger>
                        <PopoverContent className="w-60 p-2 space-y-2" align="end">
                            <Label className="text-xs uppercase tracking-wider text-muted-foreground">Set pay cut-off date</Label>
                            <Input type="date" defaultValue={payCutOffDate || ""}
                                onChange={(e) => setPayCutOff(e.target.value || null)}
                                data-testid="rota-paycutoff-input" />
                            {payCutOffDate && <Button size="sm" variant="ghost" className="w-full" onClick={() => setPayCutOff(null)} data-testid="rota-paycutoff-clear">Clear</Button>}
                        </PopoverContent>
                    </Popover>
                    <Button variant="outline" onClick={async () => {
                        try {
                            const res = await api.post(`/rotas/${id}/validate`);
                            setViolations(res.data?.violations || []);
                            toast.info(`Validation: ${res.data?.summary?.hard || 0} hard, ${res.data?.summary?.soft || 0} soft`);
                            setDrawerOpen(true);
                        } catch (err) { toast.error(formatApiError(err)); }
                    }} data-testid="rota-validate-button">
                        <RefreshCw className="w-4 h-4 mr-1.5" /> Validate
                    </Button>
                    <Button
                        variant={summary.hard > 0 ? "destructive" : "outline"}
                        onClick={() => setDrawerOpen(true)}
                        data-testid="rota-violations-button"
                    >
                        <AlertTriangle className="w-4 h-4 mr-1.5" />
                        {summary.hard} hard {summary.soft > 0 ? `· ${summary.soft} soft` : ""}
                    </Button>
                    <Button className="btn-primary" onClick={async () => {
                        try {
                            await api.put(`/rotas/${id}`, { status: rota.status === "draft" ? "published" : "draft" });
                            toast.success(rota.status === "draft" ? "Published" : "Reverted to draft");
                            await load();
                        } catch (err) { toast.error(formatApiError(err)); }
                    }} data-testid="rota-publish-button">
                        <Save className="w-4 h-4 mr-1.5" /> {rota.status === "draft" ? "Publish" : "Revert to draft"}
                    </Button>
                </div>
            </div>

            {/* Italic blue title — Paper-style */}
            <div className="px-2 pt-2">
                <h1 className="rota-paper-title" data-testid="rota-grid-title">
                    Grizedale Monthly · {titleRange} · Rota
                </h1>
            </div>

            {/* Grid */}
            <TooltipProvider delayDuration={150}>
                <div className="overflow-x-auto" data-testid="rota-grid-wrap">
                    <div className="rota-grid" data-testid="rota-grid" data-violation-key={violationKey}>
                        {/* Header row: legend label cell + staff-column header + 28 day cells */}
                        <div className="rota-header-cell-staff" style={{ borderBottom: "2px solid hsl(var(--fg) / .35)" }}>
                            Key
                        </div>
                        <div className="rota-header-cell-staff" style={{ borderBottom: "2px solid hsl(var(--fg) / .35)" }}>
                            Staff
                        </div>
                        {dates.map((d, i) => {
                            const ds = dateStrs[i];
                            const we = isWeekend(d);
                            const hol = holidayDates.has(ds);
                            const isWeekEnd = (i + 1) % 7 === 0 && i < dates.length - 1;
                            const reqs = requestsByDate.get(ds);
                            const isMedCycle = i === medCycleStartIdx;
                            const isPayCut = ds === payCutOffDate;
                            return (
                                <Tooltip key={ds}>
                                    <TooltipTrigger asChild>
                                        <div
                                            className={`rota-header-cell ${we ? "weekend" : ""} ${isWeekEnd ? "week-divider" : ""}`}
                                            data-testid={`grid-header-${ds}`}
                                        >
                                            <span className="day-letter">{dayLetter(d)}</span>
                                            <span className="day-num">{d.getDate()}</span>
                                            <div className="marker-row">
                                                {hol && <span className="marker-dot" style={{ background: "hsl(var(--accent-bright-blue))" }} title="Public holiday" />}
                                                {isMedCycle && <span className="marker-dot" style={{ background: "hsl(280 50% 70%)" }} title="Medication 28-day cycle starts" />}
                                                {isPayCut && <span className="marker-dot" style={{ background: "hsl(45 30% 50%)" }} title="Pay cut-off" />}
                                                {reqs && reqs.length > 0 && (
                                                    <Popover>
                                                        <PopoverTrigger asChild>
                                                            <button type="button" className="marker-dot"
                                                                style={{ background: "hsl(var(--accent-red))", cursor: "pointer" }}
                                                                title={`${reqs.length} pending request(s)`}
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
                                            </div>
                                        </div>
                                    </TooltipTrigger>
                                    {(hol || isMedCycle || isPayCut) && (
                                        <TooltipContent>
                                            {hol && <div>Public holiday: {holidayMap.get(ds)}</div>}
                                            {isMedCycle && <div>Medication 28-day cycle starts here</div>}
                                            {isPayCut && <div>Pay cut-off date</div>}
                                        </TooltipContent>
                                    )}
                                </Tooltip>
                            );
                        })}

                        {/* Staff rows — each staff row begins with a legend cell, then the staff label, then 28 cells */}
                        {staff.map((s, sIdx) => {
                            // Cycle through legend blocks so the 8 staff rows get the 8 most relevant ones,
                            // remaining 2 legend blocks (bus / request) are appended below.
                            const legend = LEGEND_BLOCKS[sIdx] || LEGEND_BLOCKS[0];
                            return (
                                <StaffRow
                                    key={s.initials}
                                    s={s}
                                    legend={legend}
                                    dateStrs={dateStrs}
                                    dates={dates}
                                    cellMap={cellMap}
                                    onCallByDate={onCallByDate}
                                    weekendOffByWeek={weekendOffByWeek}
                                    onClick={onCellClick}
                                    onPatch={patchCell}
                                    onSetOnCall={setOnCall}
                                    holidayDates={holidayDates}
                                    violationCellsRef={violationCellsRef}
                                    busyKey={busyKey}
                                />
                            );
                        })}

                        {/* Footer rows for the remaining 2 legend blocks (Bus + Request Box) — empty cells */}
                        {LEGEND_BLOCKS.slice(staff.length).map((legend) => (
                            <FooterLegendRow key={legend.key} legend={legend} dateStrs={dateStrs} />
                        ))}
                    </div>
                </div>
            </TooltipProvider>

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
        </div>
    );
}

function StaffRow({ s, legend, dateStrs, dates, cellMap, onCallByDate, weekendOffByWeek, onClick, onPatch, onSetOnCall, holidayDates, violationCellsRef, busyKey }) {
    return (
        <>
            <div className={`rota-legend-cell legend-${legend.key}`} data-testid={`legend-${legend.key}`}>
                <span className="legend-label">{legend.label}</span>
            </div>
            <div className="rota-row-label" data-testid={`row-label-${s.initials}`}>
                <span className="role-tag">{s.role}</span>
                <span className="name-tag">{s.initials}</span>
                <span className="hours-tag">{s.target_weekly_hours}h</span>
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
                // Weekend-off chip: on Saturdays only, when this staff has both Sat & Sun blank in this week
                const wIdx = Math.floor(i / 7);
                const isSat = i % 7 === 5;
                const showWO = isSat && weekendOffByWeek[wIdx]?.includes(s.initials);

                const cellCls = `${shiftCellClass(shift)} ${locked ? "locked" : ""} ${hard ? "violation-hard" : ""} ${soft && !hard ? "violation-soft" : ""} ${isWeekEnd ? "week-divider" : ""}`;
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
                        showWO={showWO}
                        isOnCallEditable={isOnCallEditable}
                        busy={busy}
                    />
                );
            })}
        </>
    );
}

function FooterLegendRow({ legend, dateStrs }) {
    return (
        <>
            <div className={`rota-legend-cell legend-${legend.key}`} data-testid={`legend-${legend.key}`}>
                <span className="legend-label">{legend.label}</span>
            </div>
            <div className="rota-row-label" style={{ color: "hsl(var(--fg-muted))", fontSize: "0.7rem" }}>
                {legend.label}
            </div>
            {dateStrs.map((ds, i) => {
                const isWeekEnd = (i + 1) % 7 === 0 && i < dateStrs.length - 1;
                return (
                    <div key={ds} className={`shift-cell shift-blank ${isWeekEnd ? "week-divider" : ""}`}
                        style={{ background: "hsl(var(--bg-elev))" }} />
                );
            })}
        </>
    );
}

function CellWithMenu({ dateStr, init, shift, locked, cls, onClick, onPatch, onCall, onSetOnCall, showWO, isOnCallEditable, busy }) {
    const [open, setOpen] = useState(false);
    const [draft, setDraft] = useState({ shift, locked, reason: "" });
    useEffect(() => { setDraft({ shift, locked, reason: "" }); }, [shift, locked, dateStr, init]);

    const save = async () => {
        await onPatch(dateStr, init, draft.shift, !!draft.locked, draft.reason || null);
        setOpen(false);
    };

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <button
                    type="button"
                    className={cls}
                    onClick={onClick}
                    onContextMenu={(e) => { e.preventDefault(); setOpen(true); }}
                    data-testid={`cell-${dateStr}-${init}`}
                    disabled={busy}
                    title={shift ? SHIFT_LABEL[shift] : ""}
                >
                    {displayShift(shift)}
                    {showWO && <span className="wo-chip" title="Weekend off">WO</span>}
                    {onCall && <span className="oncall-chip">on-call</span>}
                </button>
            </PopoverTrigger>
            <PopoverContent className="w-72" align="center" data-testid={`cell-popover-${dateStr}-${init}`}>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">{init} · {dateStr}</div>
                <div className="grid grid-cols-4 gap-1">
                    {["", ...SHIFT_TYPES].map((sh) => (
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
