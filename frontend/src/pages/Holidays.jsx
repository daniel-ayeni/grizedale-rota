import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Plus, Trash2, X, FileDown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
    Tabs, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
    AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";
import { ymd } from "@/lib/shifts";

const TYPE_COLOURS = {
    AL: { bg: "hsl(var(--accent-pink) / .2)", fg: "hsl(var(--accent-pink))" },
    TRN: { bg: "hsl(var(--accent-red) / .2)", fg: "hsl(var(--accent-red))" },
    OFF_REQ: { bg: "hsl(var(--muted))", fg: "hsl(var(--fg-muted))" },
};

export default function Holidays() {
    const [view, setView] = useState("year");
    const [year, setYear] = useState(2026);
    const [exportingPdf, setExportingPdf] = useState(false);
    const [exportPicker, setExportPicker] = useState(null);  // selected theme or null
    const [monthIdx, setMonthIdx] = useState(3); // April default
    const [leave, setLeave] = useState([]);
    const [holidays, setHolidays] = useState([]);
    const [staff, setStaff] = useState([]);
    const [modalDate, setModalDate] = useState(null);

    const load = async () => {
        try {
            const [leaveRes, settingsRes, staffRes] = await Promise.all([
                api.get(`/leave?from=${year}-01-01&to=${year}-12-31`),
                api.get("/settings"),
                api.get("/staff"),
            ]);
            setLeave(leaveRes.data);
            setHolidays(settingsRes.data?.public_holidays || []);
            setStaff(staffRes.data.filter((s) => s.active));
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };
    useEffect(() => { load(); /* eslint-disable-next-line */ }, [year]);

    const leaveByDate = useMemo(() => {
        const m = new Map();
        for (const l of leave) {
            if (!m.has(l.date)) m.set(l.date, []);
            m.get(l.date).push(l);
        }
        return m;
    }, [leave]);

    const holidayDates = useMemo(() => new Set(holidays.map((h) => h.date)), [holidays]);

    return (
        <div className="space-y-6" data-testid="holidays-page">
            <AlertDialog
                open={!!exportPicker}
                onOpenChange={(o) => { if (!o) setExportPicker(null); }}
            >
                <AlertDialogContent data-testid="holiday-export-picker">
                    <AlertDialogHeader>
                        <AlertDialogTitle>Export holiday sheet</AlertDialogTitle>
                        <AlertDialogDescription>
                            Which theme do you want the export to use?
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <div className="grid grid-cols-2 gap-2 mt-2">
                        {[
                            { value: "paper", label: "Paper", note: "Handwritten style — peach, italic title" },
                            { value: "modern", label: "Modern", note: "Clean slate — sans-serif, minimal chrome" },
                        ].map((opt) => (
                            <button
                                key={opt.value}
                                type="button"
                                onClick={() => setExportPicker(opt.value)}
                                className="text-left p-3 rounded-md border transition-colors"
                                style={{
                                    borderColor: exportPicker === opt.value ? "hsl(var(--primary))" : "hsl(var(--border))",
                                    background: exportPicker === opt.value ? "hsl(var(--primary) / 0.08)" : "transparent",
                                    borderWidth: exportPicker === opt.value ? "2px" : "1px",
                                }}
                                data-testid={`holiday-export-theme-${opt.value}`}
                            >
                                <div className="font-semibold mb-1">{opt.label}</div>
                                <div className="text-xs text-muted-foreground">{opt.note}</div>
                            </button>
                        ))}
                    </div>
                    <AlertDialogFooter>
                        <AlertDialogCancel data-testid="holiday-export-cancel">Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={async () => {
                                const theme = exportPicker || "paper";
                                setExportPicker(null);
                                setExportingPdf(true);
                                try {
                                    const res = await api.get(`/holidays/export.pdf?year=${year}&theme=${theme}`, { responseType: "blob" });
                                    const blob = new Blob([res.data], { type: "application/pdf" });
                                    const url = window.URL.createObjectURL(blob);
                                    const a = document.createElement("a");
                                    a.href = url;
                                    a.download = `grizedale-holiday-sheet-${year}-${theme}.pdf`;
                                    document.body.appendChild(a); a.click(); a.remove();
                                    setTimeout(() => window.URL.revokeObjectURL(url), 1000);
                                    toast.success(`Holiday sheet ${year} (${theme}) downloaded`);
                                } catch (err) {
                                    toast.error(formatApiError(err));
                                } finally { setExportingPdf(false); }
                            }}
                            data-testid="holiday-export-confirm"
                        >
                            Export
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                <div>
                    <h1 className="display text-3xl font-semibold">Holidays</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Plan annual leave and training across the year. Click any cell to add or remove leave.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <Tabs value={view} onValueChange={setView}>
                        <TabsList data-testid="holidays-view-tabs">
                            <TabsTrigger value="year" data-testid="view-year">Year</TabsTrigger>
                            <TabsTrigger value="month" data-testid="view-month">Month</TabsTrigger>
                        </TabsList>
                    </Tabs>
                    <Button variant="outline" size="icon" onClick={() => setYear((y) => y - 1)} data-testid="year-prev"><ChevronLeft className="w-4 h-4" /></Button>
                    <span className="text-sm font-semibold tabular-nums px-2" data-testid="year-label">{year}</span>
                    <Button variant="outline" size="icon" onClick={() => setYear((y) => y + 1)} data-testid="year-next"><ChevronRight className="w-4 h-4" /></Button>
                    <Button
                        variant="outline" size="sm"
                        disabled={exportingPdf}
                        onClick={() => setExportPicker("paper")}
                        data-testid="holidays-export-pdf"
                    >
                        {exportingPdf
                            ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                            : <FileDown className="w-3.5 h-3.5 mr-1.5" />}
                        Export PDF
                    </Button>
                </div>
            </div>

            {/* Legend */}
            <div className="app-card p-3 flex flex-wrap items-center gap-3 text-xs" data-testid="holidays-legend">
                <Legend label="Annual Leave" color={TYPE_COLOURS.AL} />
                <Legend label="Training" color={TYPE_COLOURS.TRN} />
                <Legend label="Off Request" color={TYPE_COLOURS.OFF_REQ} />
                <span className="inline-flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ background: "hsl(var(--accent-bright-blue))" }} />
                    Public holiday
                </span>
            </div>

            {view === "year" ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" data-testid="year-grid">
                    {Array.from({ length: 12 }, (_, m) => (
                        <MiniMonth key={m} year={year} month={m} leaveByDate={leaveByDate} holidayDates={holidayDates}
                            onCellClick={(date) => setModalDate(date)} onTitleClick={() => { setMonthIdx(m); setView("month"); }} />
                    ))}
                </div>
            ) : (
                <BigMonth year={year} month={monthIdx} setMonth={setMonthIdx}
                    leaveByDate={leaveByDate} holidayDates={holidayDates}
                    onCellClick={(date) => setModalDate(date)} />
            )}

            <LeaveModal
                open={!!modalDate}
                date={modalDate}
                onOpenChange={(v) => { if (!v) setModalDate(null); }}
                staff={staff}
                existing={modalDate ? (leaveByDate.get(modalDate) || []) : []}
                onChange={load}
            />
        </div>
    );
}

function Legend({ label, color }) {
    return (
        <span className="inline-flex items-center gap-1.5">
            <span className="w-3 h-3 rounded" style={{ background: color.bg, border: `1px solid ${color.fg}` }} />
            {label}
        </span>
    );
}

function MonthCells({ year, month, leaveByDate, holidayDates, onCellClick, mini = true }) {
    const first = new Date(year, month, 1);
    const last = new Date(year, month + 1, 0);
    const dim = last.getDate();
    const offset = (first.getDay() + 6) % 7; // Mon=0
    const cells = [];
    for (let i = 0; i < offset; i++) cells.push(null);
    for (let d = 1; d <= dim; d++) cells.push(d);
    while (cells.length % 7 !== 0) cells.push(null);

    return (
        <div className={`grid grid-cols-7 ${mini ? "gap-0.5" : "gap-1"}`}>
            {["M","T","W","T","F","S","S"].map((l, i) => (
                <div key={i} className="text-center text-[10px] uppercase text-muted-foreground py-1">{l}</div>
            ))}
            {cells.map((d, i) => {
                if (d == null) return <div key={i} />;
                const ds = `${year}-${String(month + 1).padStart(2,"0")}-${String(d).padStart(2,"0")}`;
                const items = leaveByDate.get(ds) || [];
                const isHol = holidayDates.has(ds);
                const dt = new Date(year, month, d);
                const we = dt.getDay() === 0 || dt.getDay() === 6;
                return (
                    <button
                        key={i}
                        type="button"
                        onClick={() => onCellClick(ds)}
                        data-testid={`hday-${ds}`}
                        className={`relative rounded text-left ${mini ? "p-1 text-[10px]" : "p-1.5 text-xs"}`}
                        style={{
                            background: items.length ? TYPE_COLOURS[items[0].type]?.bg || "transparent" : we ? "hsl(var(--muted))" : "transparent",
                            border: "1px solid hsl(var(--border))",
                            minHeight: mini ? 36 : 64,
                        }}
                    >
                        <div className="flex items-center gap-1">
                            <span className="font-semibold tabular-nums">{d}</span>
                            {isHol && <span className="w-1.5 h-1.5 rounded-full" style={{ background: "hsl(var(--accent-bright-blue))" }} />}
                        </div>
                        {items.length > 0 && (
                            <div className={`flex flex-wrap gap-0.5 mt-1 ${mini ? "" : "gap-1"}`}>
                                {items.slice(0, mini ? 3 : 8).map((it) => (
                                    <span key={it.id}
                                        className="rounded font-semibold tabular-nums"
                                        style={{
                                            fontSize: mini ? 9 : 10,
                                            padding: mini ? "0 3px" : "1px 5px",
                                            background: TYPE_COLOURS[it.type]?.fg + "22",
                                            color: TYPE_COLOURS[it.type]?.fg,
                                        }}>
                                        {it.staff_initials}
                                    </span>
                                ))}
                                {items.length > (mini ? 3 : 8) && (
                                    <span className="text-[9px] text-muted-foreground">+{items.length - (mini ? 3 : 8)}</span>
                                )}
                            </div>
                        )}
                    </button>
                );
            })}
        </div>
    );
}

function MiniMonth({ year, month, leaveByDate, holidayDates, onCellClick, onTitleClick }) {
    const monthName = new Date(year, month, 1).toLocaleString(undefined, { month: "long" });
    return (
        <div className="app-card p-3" data-testid={`month-${month}`}>
            <button type="button" onClick={onTitleClick} className="text-sm font-semibold mb-2 link-underline" data-testid={`month-title-${month}`}>{monthName}</button>
            <MonthCells year={year} month={month} leaveByDate={leaveByDate} holidayDates={holidayDates} onCellClick={onCellClick} mini={true} />
        </div>
    );
}

function BigMonth({ year, month, setMonth, leaveByDate, holidayDates, onCellClick }) {
    const monthName = new Date(year, month, 1).toLocaleString(undefined, { month: "long", year: "numeric" });
    return (
        <div className="app-card p-4" data-testid="big-month">
            <div className="flex items-center justify-between mb-3">
                <Button variant="outline" size="icon" onClick={() => setMonth((m) => (m + 11) % 12)} data-testid="big-month-prev"><ChevronLeft className="w-4 h-4" /></Button>
                <div className="display text-xl font-semibold">{monthName}</div>
                <Button variant="outline" size="icon" onClick={() => setMonth((m) => (m + 1) % 12)} data-testid="big-month-next"><ChevronRight className="w-4 h-4" /></Button>
            </div>
            <MonthCells year={year} month={month} leaveByDate={leaveByDate} holidayDates={holidayDates} onCellClick={onCellClick} mini={false} />
        </div>
    );
}

function LeaveModal({ open, date, onOpenChange, staff, existing, onChange }) {
    const [picked, setPicked] = useState([]);
    const [type, setType] = useState("AL");
    const [notes, setNotes] = useState("");
    const [endDate, setEndDate] = useState("");

    useEffect(() => {
        if (!open) {
            setPicked([]); setType("AL"); setNotes(""); setEndDate("");
        }
    }, [open]);

    const dates = useMemo(() => {
        if (!date) return [];
        if (!endDate || endDate <= date) return [date];
        const out = [];
        const s = new Date(date);
        const e = new Date(endDate);
        for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
            out.push(ymd(d));
        }
        return out;
    }, [date, endDate]);

    const save = async () => {
        try {
            for (const init of picked) {
                await api.post("/leave", { staff_initials: init, dates, type, notes });
            }
            toast.success(`${picked.length * dates.length} leave entries created`);
            onChange();
            onOpenChange(false);
        } catch (err) {
            toast.error(formatApiError(err));
        }
    };

    const remove = async (id) => {
        try {
            await api.delete(`/leave/${id}`);
            toast.success("Removed");
            onChange();
        } catch (err) { toast.error(formatApiError(err)); }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent data-testid="leave-modal">
                <DialogHeader>
                    <DialogTitle>Leave on {date}</DialogTitle>
                    <DialogDescription>Add or remove leave entries for one or more staff. Optionally extend to a date range.</DialogDescription>
                </DialogHeader>

                {/* Existing entries */}
                {existing.length > 0 && (
                    <div className="space-y-1.5 mb-2">
                        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Existing</Label>
                        {existing.map((l) => (
                            <div key={l.id} className="flex items-center justify-between p-2 rounded border" style={{ borderColor: "hsl(var(--border))" }}>
                                <div className="text-sm">
                                    <span className="font-semibold">{l.staff_initials}</span>
                                    <Badge className="ml-2" variant="outline">{l.type}</Badge>
                                    {l.notes && <span className="text-xs text-muted-foreground ml-2">{l.notes}</span>}
                                </div>
                                <Button variant="ghost" size="sm" onClick={() => remove(l.id)} data-testid={`leave-remove-${l.id}`}>
                                    <Trash2 className="w-4 h-4 text-destructive" />
                                </Button>
                            </div>
                        ))}
                    </div>
                )}

                {/* Add new */}
                <div className="space-y-3">
                    <div>
                        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Staff (multi-select)</Label>
                        <div className="flex flex-wrap gap-1.5 mt-1.5">
                            {staff.map((s) => (
                                <button key={s.initials} type="button"
                                    onClick={() => setPicked((p) => p.includes(s.initials) ? p.filter((x) => x !== s.initials) : [...p, s.initials])}
                                    data-testid={`leave-pick-${s.initials}`}
                                    className="px-2 py-1 rounded-full text-xs font-semibold border"
                                    style={{
                                        background: picked.includes(s.initials) ? "hsl(var(--primary))" : "transparent",
                                        color: picked.includes(s.initials) ? "hsl(var(--primary-fg))" : "hsl(var(--fg))",
                                        borderColor: "hsl(var(--border-strong))",
                                    }}>
                                    {s.initials}
                                </button>
                            ))}
                        </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <Label className="text-xs uppercase tracking-wider text-muted-foreground">Type</Label>
                            <Select value={type} onValueChange={setType}>
                                <SelectTrigger className="mt-1.5" data-testid="leave-type"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="AL">Annual Leave</SelectItem>
                                    <SelectItem value="TRN">Training</SelectItem>
                                    <SelectItem value="OFF_REQ">Off Request</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div>
                            <Label className="text-xs uppercase tracking-wider text-muted-foreground">End date (range)</Label>
                            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="mt-1.5" data-testid="leave-end-date" />
                        </div>
                    </div>
                    <div>
                        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Notes</Label>
                        <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} className="mt-1.5" rows={2} data-testid="leave-notes" />
                    </div>
                </div>
                <DialogFooter>
                    <div className="text-xs text-muted-foreground mr-auto">{picked.length} staff × {dates.length} days = {picked.length * dates.length} entries</div>
                    <Button className="btn-primary" onClick={save} disabled={picked.length === 0} data-testid="leave-save"><Plus className="w-4 h-4 mr-1.5" />Save leave</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
