import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
    ArrowLeft, Lock, Unlock, RefreshCw, AlertTriangle,
    AlertCircle, Copy, Save, Inbox,
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
    SHIFT_TYPES, CYCLE, nextShift, shiftCellClass,
    SHIFT_LABEL, SHIFT_HOURS, ymd, parseYmd, addDays, dayLetter, isWeekend,
} from "@/lib/shifts";

const DAY_COVER = new Set(["D", "D*"]);
const NIGHT_COVER = new Set(["N", "D*", "*"]);
const ON_CALL_STAFF = ["L.M.", "J.C.", "L.D."];

export default function RotaEditor() {
    const { id } = useParams();
    const [rota, setRota] = useState(null);
    const [staff, setStaff] = useState([]);
    const [holidays, setHolidays] = useState([]);
    const [requests, setRequests] = useState([]);
    const [violations, setViolations] = useState([]);
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [requestPopoverDate, setRequestPopoverDate] = useState(null);
    const [busyKey, setBusyKey] = useState(null);
    const violationCellsRef = useRef({ hard: new Set(), soft: new Set() });

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

    // Violation cell index — paint borders fast
    useEffect(() => {
        const hard = new Set();
        const soft = new Set();
        for (const v of violations) {
            for (const c of (v.affected_cells || [])) {
                (v.severity === "hard" ? hard : soft).add(`${c.date}|${c.staff_initials}`);
            }
        }
        violationCellsRef.current = { hard, soft };
        // force re-render
        setViolationKey((k) => k + 1);
    }, [violations]);
    const [violationKey, setViolationKey] = useState(0);

    const summary = useMemo(() => {
        const hard = violations.filter((v) => v.severity === "hard").length;
        const soft = violations.filter((v) => v.severity === "soft").length;
        return { hard, soft, total: violations.length };
    }, [violations]);

    // Cell click → cycle shift
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
            // Optimistic update
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

    // Categories computed from current state
    const categoryRows = useMemo(() => {
        if (!rota) return null;
        const fa = []; const al = []; const trn = []; const sleep = []; const weekendOff = [];
        for (const dStr of dateStrs) {
            const onShiftToday = staff
                .map((s) => ({ s, sh: cellMap.get(`${dStr}|${s.initials}`)?.shift || "" }))
                .filter(({ sh }) => sh && sh !== "OFF" && sh !== "AL" && sh !== "TRN");
            fa.push(onShiftToday.filter(({ s }) => s.first_aider).map(({ s }) => s.initials));
            al.push(staff.filter((s) => cellMap.get(`${dStr}|${s.initials}`)?.shift === "AL").map((s) => s.initials));
            trn.push(staff.filter((s) => cellMap.get(`${dStr}|${s.initials}`)?.shift === "TRN").map((s) => s.initials));
            sleep.push(staff.filter((s) => ["D*", "*"].includes(cellMap.get(`${dStr}|${s.initials}`)?.shift)).map((s) => s.initials));
        }
        // Weekend off — staff with no working shifts that weekend
        for (let weekIdx = 0; weekIdx < (rota.weeks || 4); weekIdx++) {
            const sat = dateStrs[weekIdx * 7 + 5];
            const sun = dateStrs[weekIdx * 7 + 6];
            const offThisWeekend = staff.filter((s) => {
                const sat_shift = cellMap.get(`${sat}|${s.initials}`)?.shift;
                const sun_shift = cellMap.get(`${sun}|${s.initials}`)?.shift;
                const isWorking = (sh) => sh && !["", "OFF", "AL", "TRN"].includes(sh);
                return !isWorking(sat_shift) && !isWorking(sun_shift);
            }).map((s) => s.initials);
            weekendOff[weekIdx] = offThisWeekend;
        }
        return { fa, al, trn, sleep, weekendOff };
    }, [rota, staff, dateStrs, cellMap]);

    // Medication 28-day cycle: first Friday of the rota
    const medCycleStartIdx = useMemo(() => {
        if (!dates.length) return -1;
        for (let i = 0; i < 7; i++) {
            if (dates[i].getDay() === 5) return i;
        }
        return -1;
    }, [dates]);

    if (!rota) {
        return <div className="text-sm text-muted-foreground" data-testid="rota-loading">Loading rota…</div>;
    }

    const titleRange = `${rota.start_date} — ${dateStrs[dateStrs.length - 1]}`;

    return (
        <div className="space-y-4" data-testid="rota-editor-page">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-3">
                <div>
                    <Link to="/rotas" className="text-xs text-muted-foreground inline-flex items-center gap-1 mb-1" data-testid="rota-back">
                        <ArrowLeft className="w-3 h-3" /> Rotas
                    </Link>
                    <h1 className="display text-2xl sm:text-3xl font-semibold leading-tight">{rota.title}</h1>
                    <div className="text-sm text-muted-foreground mt-1">{titleRange} · {rota.weeks} weeks</div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={rota.status === "published" ? "default" : "outline"} data-testid="rota-status-badge">{rota.status}</Badge>
                    <Button variant="outline" onClick={async () => {
                        try {
                            const start = rota.start_date;
                            const empty = (rota.assignments || []).length === 0;
                            const res = await api.post(`/rotas/${id}/copy-from-previous`);
                            const h = res.data?.validation_report?.summary?.hard ?? 0;
                            toast.success(`Copied ${res.data.assignments_count} cells. ${h} hard violations to review.`);
                            await load();
                        } catch (err) { toast.error(formatApiError(err)); }
                    }} data-testid="rota-copy-from-previous">
                        <Copy className="w-4 h-4 mr-1.5" /> Copy from previous
                    </Button>
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

            {/* Grid */}
            <TooltipProvider delayDuration={150}>
                <div className="overflow-x-auto" data-testid="rota-grid-wrap">
                    <div className="rota-grid" data-testid="rota-grid" data-violation-key={violationKey}>
                        {/* Header row 1: week labels + day letters */}
                        <div className="rota-header-cell" style={{ gridColumn: "span 3" }}>Staff / Date</div>
                        {dates.map((d, i) => {
                            const ds = dateStrs[i];
                            const we = isWeekend(d);
                            const hol = holidayDates.has(ds);
                            const isWeekEnd = (i + 1) % 7 === 0 && i < dates.length - 1;
                            return (
                                <div
                                    key={ds}
                                    className={`rota-header-cell ${we ? "weekend" : ""} ${isWeekEnd ? "week-divider" : ""}`}
                                    data-testid={`grid-header-${ds}`}
                                >
                                    <div>{dayLetter(d)}</div>
                                    <div style={{ fontSize: "0.7rem", fontWeight: 700, color: hol ? "hsl(var(--accent-pink))" : undefined }}>
                                        {d.getDate()}
                                    </div>
                                </div>
                            );
                        })}

                        {/* Staff rows */}
                        {staff.map((s) => (
                            <StaffRow
                                key={s.initials}
                                s={s}
                                dateStrs={dateStrs}
                                cellMap={cellMap}
                                onClick={onCellClick}
                                onPatch={patchCell}
                                violationCellsRef={violationCellsRef}
                                busyKey={busyKey}
                            />
                        ))}

                        {/* Category rows */}
                        {categoryRows && (
                            <>
                                <CategoryRow label="First Aider" sub="auto" cls="cat-fa" testid="cat-fa">
                                    {categoryRows.fa.map((arr, i) => (
                                        <div key={dateStrs[i]} className={`cat-cell ${(i + 1) % 7 === 0 && i < dates.length - 1 ? "week-divider" : ""}`}>
                                            {arr.map((init) => <span key={init} className="cat-cell-init">{init}</span>)}
                                        </div>
                                    ))}
                                </CategoryRow>
                                <CategoryRow label="Annual Leave" sub="auto" cls="cat-al" testid="cat-al">
                                    {categoryRows.al.map((arr, i) => (
                                        <div key={dateStrs[i]} className={`cat-cell ${(i + 1) % 7 === 0 && i < dates.length - 1 ? "week-divider" : ""}`}>
                                            {arr.map((init) => <span key={init} className="cat-cell-init" style={{ background: "hsl(var(--accent-pink) / .15)", color: "hsl(var(--accent-pink))" }}>{init}</span>)}
                                        </div>
                                    ))}
                                </CategoryRow>
                                <CategoryRow label="Training" sub="auto" cls="cat-trn" testid="cat-trn">
                                    {categoryRows.trn.map((arr, i) => (
                                        <div key={dateStrs[i]} className={`cat-cell ${(i + 1) % 7 === 0 && i < dates.length - 1 ? "week-divider" : ""}`}>
                                            {arr.map((init) => <span key={init} className="cat-cell-init" style={{ background: "hsl(var(--accent-red) / .15)", color: "hsl(var(--accent-red))" }}>{init}</span>)}
                                        </div>
                                    ))}
                                </CategoryRow>
                                <CategoryRow label="On-Call" sub="L.M./J.C./L.D. only" cls="cat-oncall" testid="cat-oncall">
                                    {dateStrs.map((ds, i) => {
                                        const dt = dates[i];
                                        const editable = isWeekend(dt) || holidayDates.has(ds);
                                        const cur = onCallByDate.get(ds);
                                        return (
                                            <div key={ds} className={`cat-cell ${(i + 1) % 7 === 0 && i < dates.length - 1 ? "week-divider" : ""}`} style={{ opacity: editable ? 1 : 0.45 }}>
                                                <Popover>
                                                    <PopoverTrigger asChild>
                                                        <button type="button" data-testid={`oncall-${ds}`} disabled={!editable}
                                                            className="text-xs"
                                                            style={{ color: cur ? "hsl(var(--accent-bright-blue))" : "hsl(var(--fg-muted))" }}>
                                                            {cur || (editable ? "—" : "")}
                                                        </button>
                                                    </PopoverTrigger>
                                                    <PopoverContent className="w-44 p-2 space-y-1" align="center">
                                                        <div className="text-xs text-muted-foreground px-1 pb-1">On-Call · {ds}</div>
                                                        {[...ON_CALL_STAFF, "_clear_"].map((init) => (
                                                            <Button key={init} variant="ghost" size="sm" className="w-full justify-start"
                                                                onClick={async () => {
                                                                    try {
                                                                        const newOnCall = (rota.on_call || []).filter((o) => o.date !== ds);
                                                                        if (init !== "_clear_") newOnCall.push({ date: ds, staff_initials: init });
                                                                        await api.put(`/rotas/${id}`, { on_call: newOnCall });
                                                                        await load();
                                                                    } catch (err) { toast.error(formatApiError(err)); }
                                                                }}
                                                                data-testid={`oncall-${ds}-${init}`}>
                                                                {init === "_clear_" ? "(Clear)" : init}
                                                            </Button>
                                                        ))}
                                                    </PopoverContent>
                                                </Popover>
                                            </div>
                                        );
                                    })}
                                </CategoryRow>
                                <CategoryRow label="Sleep-in" sub="auto" cls="cat-sleep" testid="cat-sleep">
                                    {categoryRows.sleep.map((arr, i) => (
                                        <div key={dateStrs[i]} className={`cat-cell ${(i + 1) % 7 === 0 && i < dates.length - 1 ? "week-divider" : ""}`}>
                                            {arr.map((init) => <span key={init} className="cat-cell-init" style={{ background: "hsl(48 100% 88%)" }}>{init}</span>)}
                                        </div>
                                    ))}
                                </CategoryRow>
                                <CategoryRow label="Pay cut off" sub="manual" cls="cat-paycut" testid="cat-paycut">
                                    {dateStrs.map((ds, i) => (
                                        <div key={ds} className={`cat-cell ${(i + 1) % 7 === 0 && i < dates.length - 1 ? "week-divider" : ""}`} />
                                    ))}
                                </CategoryRow>
                                <CategoryRow label="Weekend Off" sub="auto · per week" cls="cat-weekend" testid="cat-weekend">
                                    {dateStrs.map((ds, i) => {
                                        const wIdx = Math.floor(i / 7);
                                        const isSatOrSun = i % 7 === 5 || i % 7 === 6;
                                        const off = categoryRows.weekendOff[wIdx] || [];
                                        return (
                                            <div key={ds} className={`cat-cell ${(i + 1) % 7 === 0 && i < dates.length - 1 ? "week-divider" : ""}`}>
                                                {isSatOrSun && i % 7 === 5 && off.map((init) => (
                                                    <span key={init} className="cat-cell-init" style={{ background: "hsl(var(--accent-purple) / .15)", color: "hsl(var(--accent-purple))" }}>{init}</span>
                                                ))}
                                            </div>
                                        );
                                    })}
                                </CategoryRow>
                                <CategoryRow label="Med. cycle" sub="28-day · auto" cls="cat-med" testid="cat-med">
                                    {dateStrs.map((ds, i) => (
                                        <div key={ds} className={`cat-cell ${(i + 1) % 7 === 0 && i < dates.length - 1 ? "week-divider" : ""}`}>
                                            {i === medCycleStartIdx && <span className="cat-cell-init" style={{ background: "hsl(280 50% 88%)" }}>Start</span>}
                                        </div>
                                    ))}
                                </CategoryRow>
                                <CategoryRow label="Bus" sub="—" cls="cat-row" testid="cat-bus">
                                    {dateStrs.map((ds, i) => (
                                        <div key={ds} className={`cat-cell ${(i + 1) % 7 === 0 && i < dates.length - 1 ? "week-divider" : ""}`} />
                                    ))}
                                </CategoryRow>
                                <CategoryRow label="Request Box" sub={`${requests.length} pending`} cls="cat-row" testid="cat-requests">
                                    {dateStrs.map((ds, i) => {
                                        const reqsToday = requests.filter((r) => r.date === ds);
                                        return (
                                            <div key={ds} className={`cat-cell ${(i + 1) % 7 === 0 && i < dates.length - 1 ? "week-divider" : ""}`}>
                                                {reqsToday.length > 0 && (
                                                    <Popover open={requestPopoverDate === ds} onOpenChange={(o) => setRequestPopoverDate(o ? ds : null)}>
                                                        <PopoverTrigger asChild>
                                                            <button type="button" className="cat-cell-init"
                                                                style={{ background: "hsl(var(--accent-bright-blue) / .2)", color: "hsl(var(--accent-bright-blue))" }}
                                                                data-testid={`req-pop-${ds}`}>
                                                                <Inbox className="inline w-3 h-3 mr-0.5" />{reqsToday.length}
                                                            </button>
                                                        </PopoverTrigger>
                                                        <PopoverContent align="center" className="w-72">
                                                            <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Pending requests · {ds}</div>
                                                            {reqsToday.map((r) => (
                                                                <div key={r.id} className="text-xs border-t py-1.5" style={{ borderColor: "hsl(var(--border))" }}>
                                                                    <div className="font-semibold">{r.staff_initials} · {r.shift_preference}</div>
                                                                    {r.notes && <div className="text-muted-foreground">{r.notes}</div>}
                                                                </div>
                                                            ))}
                                                        </PopoverContent>
                                                    </Popover>
                                                )}
                                            </div>
                                        );
                                    })}
                                </CategoryRow>
                            </>
                        )}
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

function CategoryRow({ label, sub, cls, children, testid }) {
    return (
        <>
            <div className={`rota-row-label cat-row ${cls}`} style={{ gridColumn: "span 3" }} data-testid={testid}>
                <div>{label}</div>
                <div className="rota-row-sub">{sub}</div>
            </div>
            {children}
        </>
    );
}

function StaffRow({ s, dateStrs, cellMap, onClick, onPatch, violationCellsRef, busyKey }) {
    return (
        <>
            <div className="rota-row-label" style={{ gridColumn: "span 3" }} data-testid={`row-label-${s.initials}`}>
                <div className="font-semibold">{s.initials}</div>
                <div className="rota-row-sub">{s.role} · {s.target_weekly_hours}h</div>
            </div>
            {dateStrs.map((ds, i) => {
                const cell = cellMap.get(`${ds}|${s.initials}`);
                const shift = cell?.shift || "";
                const locked = !!cell?.locked;
                const k = `${ds}|${s.initials}`;
                const hard = violationCellsRef.current.hard.has(k);
                const soft = violationCellsRef.current.soft.has(k);
                const isWeekEnd = (i + 1) % 7 === 0 && i < dateStrs.length - 1;
                const cellCls = `${shiftCellClass(shift)} ${locked ? "locked" : ""} ${hard ? "violation-hard" : ""} ${soft && !hard ? "violation-soft" : ""} ${isWeekEnd ? "week-divider" : ""}`;
                const busy = busyKey === k;
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
                        busy={busy}
                    />
                );
            })}
        </>
    );
}

function CellWithMenu({ dateStr, init, shift, locked, cls, onClick, onPatch, busy }) {
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
                    {SHIFT_LABEL[shift] || "·"}
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
                <div className="mt-2">
                    <Label className="text-xs uppercase tracking-wider text-muted-foreground">Reason (optional)</Label>
                    <Input value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} placeholder="e.g. requested by L.M." className="mt-1" data-testid="cell-popover-reason" />
                </div>
                <Button className="btn-primary w-full mt-3" onClick={save} data-testid="cell-popover-save">Save</Button>
            </PopoverContent>
        </Popover>
    );
}
