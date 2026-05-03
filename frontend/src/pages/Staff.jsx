import { useEffect, useState } from "react";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
    Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle, SheetTrigger,
} from "@/components/ui/sheet";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";
import StaffDeleteDialog from "@/components/StaffDeleteDialog";

const EMPTY = {
    initials: "",
    full_name: "",
    role: "Care Support",
    gender: "F",
    target_weekly_hours: 36,
    is_admin_only: false,
    medication_competent: false,
    first_aider: false,
    fire_trained: true,
    trust_level: "medium",
    can_do_days: true,
    can_do_nights: false,
    can_do_sleepover: false,
    manager_weekday_admin: false,
    preferred_off_days: [],
    accepts_overtime: false,
    shift_preference: "no_preference",
    is_manager: false,
    is_deputy: false,
    is_senior: false,
    is_flexi: false,
    is_night: false,
    active: true,
};

// Role-flag metadata used by the role-chip widget.
// Each flag maps to (label, short code, solver-rule hint).
const ROLE_FLAGS = [
    { key: "is_manager", code: "MGR", label: "Manager",  tone: "red"    },
    { key: "is_deputy",  code: "DEP", label: "Deputy",   tone: "orange" },
    { key: "is_senior",  code: "SEN", label: "Senior",   tone: "blue"   },
    { key: "is_flexi",   code: "FLX", label: "Flexi",    tone: "green"  },
    { key: "is_night",   code: "NGT", label: "Night",    tone: "purple" },
];
const TONE_COLORS = {
    red:    { active: "hsl(0 70% 45%)",    bg: "hsl(0 70% 45% / 0.12)"    },
    orange: { active: "hsl(28 80% 45%)",   bg: "hsl(28 80% 45% / 0.12)"   },
    blue:   { active: "hsl(210 75% 48%)",  bg: "hsl(210 75% 48% / 0.12)"  },
    green:  { active: "hsl(142 55% 38%)",  bg: "hsl(142 55% 38% / 0.12)"  },
    purple: { active: "hsl(265 55% 50%)",  bg: "hsl(265 55% 50% / 0.12)"  },
};

const PREF_OPTIONS = ["day", "night", "no_preference"];
const PREF_LABEL = { day: "Day", night: "Night", no_preference: "—" };

export default function Staff() {
    const [staff, setStaff] = useState([]);
    const [loading, setLoading] = useState(true);
    const [editing, setEditing] = useState(null); // staff doc or null
    const [creating, setCreating] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState(null); // { row } or null

    const load = async () => {
        setLoading(true);
        try {
            const { data } = await api.get("/staff");
            setStaff(data);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const togglePatch = async (row, key, value) => {
        try {
            const { data } = await api.put(`/staff/${row.id}`, { [key]: value });
            setStaff((s) => s.map((x) => (x.id === row.id ? data : x)));
            toast.success(`${row.initials}: ${key} updated`);
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };

    const handleDeleted = (row) => {
        setStaff((s) => s.filter((x) => x.id !== row.id));
    };

    return (
        <div className="space-y-6" data-testid="staff-page">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="display text-3xl font-semibold">Staff</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Care home staff with capability flags. Edits save immediately.
                    </p>
                </div>
                <Button
                    className="btn-primary"
                    onClick={() => { setEditing({ ...EMPTY }); setCreating(true); }}
                    data-testid="staff-add-button"
                >
                    <Plus className="w-4 h-4 mr-1.5" /> Add Staff
                </Button>
            </div>

            <div className="section-header" data-testid="staff-section-header">Care team · {staff.length} staff</div>

            <div className="app-card overflow-x-auto" data-testid="staff-table-wrap">
                <Table className="paper-table" data-testid="staff-table">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[80px]">Initials</TableHead>
                            <TableHead>Name</TableHead>
                            <TableHead className="hidden lg:table-cell">Role · Flags</TableHead>
                            <TableHead className="text-center">Hrs</TableHead>
                            <TableHead className="text-center">Gender</TableHead>
                            <TableHead className="text-center">Med</TableHead>
                            <TableHead className="text-center">FA</TableHead>
                            <TableHead className="text-center">Fire</TableHead>
                            <TableHead className="text-center hidden md:table-cell">Day</TableHead>
                            <TableHead className="text-center hidden md:table-cell">Night</TableHead>
                            <TableHead className="text-center hidden md:table-cell">Sleep</TableHead>
                            <TableHead className="text-center" title="Day / Night preference (only meaningful when staff can do both)">Pref</TableHead>
                            <TableHead className="text-center" title="Accepts overtime above contracted weekly hours">OT</TableHead>
                            <TableHead className="text-center">Active</TableHead>
                            <TableHead className="w-[100px] text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading && (
                            <TableRow><TableCell colSpan={15} className="text-center text-sm text-muted-foreground py-8">Loading…</TableCell></TableRow>
                        )}
                        {!loading && staff.length === 0 && (
                            <TableRow><TableCell colSpan={15} className="text-center text-sm text-muted-foreground py-8">No staff yet</TableCell></TableRow>
                        )}
                        {staff.map((row) => (
                            <TableRow key={row.id} data-testid={`staff-row-${row.initials}`} className="staff-row-compact">
                                <TableCell className="font-semibold py-1.5">{row.initials}</TableCell>
                                <TableCell className="py-1.5">
                                    <div className="font-medium text-sm leading-tight">{row.full_name}</div>
                                    <div className="text-[11px] text-muted-foreground lg:hidden leading-tight">{row.role}</div>
                                </TableCell>
                                <TableCell className="hidden lg:table-cell py-1.5">
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="text-xs text-muted-foreground">{row.role}</span>
                                        <RoleFlagChips row={row} onToggle={(k, v) => togglePatch(row, k, v)} />
                                    </div>
                                </TableCell>
                                <TableCell className="text-center py-1.5 text-sm tabular-nums">{row.target_weekly_hours}</TableCell>
                                <TableCell className="text-center py-1.5 text-sm">{row.gender}</TableCell>
                                <TableCell className="text-center py-1.5"><Switch checked={row.medication_competent} onCheckedChange={(v) => togglePatch(row, "medication_competent", v)} data-testid={`staff-${row.initials}-med`} /></TableCell>
                                <TableCell className="text-center py-1.5"><Switch checked={row.first_aider} onCheckedChange={(v) => togglePatch(row, "first_aider", v)} data-testid={`staff-${row.initials}-fa`} /></TableCell>
                                <TableCell className="text-center py-1.5"><Switch checked={row.fire_trained} onCheckedChange={(v) => togglePatch(row, "fire_trained", v)} data-testid={`staff-${row.initials}-fire`} /></TableCell>
                                <TableCell className="text-center py-1.5 hidden md:table-cell"><Switch checked={row.can_do_days} onCheckedChange={(v) => togglePatch(row, "can_do_days", v)} data-testid={`staff-${row.initials}-day`} /></TableCell>
                                <TableCell className="text-center py-1.5 hidden md:table-cell"><Switch checked={row.can_do_nights} onCheckedChange={(v) => togglePatch(row, "can_do_nights", v)} data-testid={`staff-${row.initials}-night`} /></TableCell>
                                <TableCell className="text-center py-1.5 hidden md:table-cell"><Switch checked={row.can_do_sleepover} onCheckedChange={(v) => togglePatch(row, "can_do_sleepover", v)} data-testid={`staff-${row.initials}-sleep`} /></TableCell>
                                <TableCell className="text-center py-1.5">
                                    <PrefSegmented row={row} onChange={(v) => togglePatch(row, "shift_preference", v)} />
                                </TableCell>
                                <TableCell className="text-center py-1.5"><Switch checked={!!row.accepts_overtime} onCheckedChange={(v) => togglePatch(row, "accepts_overtime", v)} data-testid={`staff-${row.initials}-ot`} /></TableCell>
                                <TableCell className="text-center py-1.5"><Switch checked={row.active} onCheckedChange={(v) => togglePatch(row, "active", v)} data-testid={`staff-${row.initials}-active`} /></TableCell>
                                <TableCell className="text-right py-1.5">
                                    <div className="flex justify-end gap-0.5">
                                        <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => { setEditing(row); setCreating(false); }} data-testid={`staff-${row.initials}-edit`}>
                                            <Pencil className="w-3.5 h-3.5" />
                                        </Button>
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            className="h-7 w-7 p-0"
                                            onClick={() => setDeleteTarget(row)}
                                            data-testid={`staff-${row.initials}-delete`}
                                            title="Delete staff"
                                        >
                                            <Trash2 className="w-3.5 h-3.5 text-destructive" />
                                        </Button>
                                    </div>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>

            <StaffSheet
                open={!!editing}
                onOpenChange={(v) => { if (!v) { setEditing(null); setCreating(false); } }}
                value={editing}
                creating={creating}
                onSaved={(saved) => {
                    setStaff((s) => {
                        const exists = s.some((x) => x.id === saved.id);
                        return exists ? s.map((x) => (x.id === saved.id ? saved : x)) : [...s, saved];
                    });
                    setEditing(null);
                    setCreating(false);
                }}
            />
            <StaffDeleteDialog
                row={deleteTarget}
                open={!!deleteTarget}
                onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
                onDeleted={handleDeleted}
            />
        </div>
    );
}

function StaffSheet({ open, onOpenChange, value, creating, onSaved }) {
    const [form, setForm] = useState(value || EMPTY);
    useEffect(() => { setForm(value || EMPTY); }, [value]);

    const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));

    const submit = async (e) => {
        e.preventDefault();
        try {
            if (creating) {
                const { data } = await api.post("/staff", form);
                toast.success(`${form.initials} created`);
                onSaved(data);
            } else {
                const { data } = await api.put(`/staff/${form.id}`, form);
                toast.success(`${form.initials} updated`);
                onSaved(data);
            }
        } catch (err) {
            toast.error(formatApiError(err));
        }
    };

    if (!form) return null;

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="overflow-y-auto sm:max-w-xl" data-testid="staff-sheet">
                <SheetHeader>
                    <SheetTitle>{creating ? "Add Staff" : `Edit ${form.initials}`}</SheetTitle>
                    <SheetDescription>All capability flags affect what the solver can assign.</SheetDescription>
                </SheetHeader>
                <form onSubmit={submit} className="space-y-4 mt-4">
                    <div className="grid grid-cols-2 gap-3">
                        <FormField label="Initials">
                            <Input value={form.initials} onChange={(e) => update("initials", e.target.value)} required data-testid="sheet-initials" />
                        </FormField>
                        <FormField label="Target Weekly Hours">
                            <Input type="number" min="0" max="60" value={form.target_weekly_hours} onChange={(e) => update("target_weekly_hours", Number(e.target.value))} data-testid="sheet-target-hours" />
                        </FormField>
                    </div>
                    <FormField label="Full Name">
                        <Input value={form.full_name} onChange={(e) => update("full_name", e.target.value)} required data-testid="sheet-full-name" />
                    </FormField>
                    <div className="grid grid-cols-2 gap-3">
                        <FormField label="Role">
                            <Input value={form.role} onChange={(e) => update("role", e.target.value)} data-testid="sheet-role" />
                        </FormField>
                        <FormField label="Gender">
                            <Select value={form.gender} onValueChange={(v) => update("gender", v)}>
                                <SelectTrigger data-testid="sheet-gender"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="F">Female</SelectItem>
                                    <SelectItem value="M">Male</SelectItem>
                                </SelectContent>
                            </Select>
                        </FormField>
                    </div>
                    <FormField label="Trust Level">
                        <Select value={form.trust_level} onValueChange={(v) => update("trust_level", v)}>
                            <SelectTrigger data-testid="sheet-trust"><SelectValue /></SelectTrigger>
                            <SelectContent>
                                <SelectItem value="low">Low</SelectItem>
                                <SelectItem value="medium">Medium</SelectItem>
                                <SelectItem value="high">High</SelectItem>
                            </SelectContent>
                        </Select>
                    </FormField>
                    <div className="grid grid-cols-2 gap-3">
                        <SwitchRow label="Medication Competent" checked={form.medication_competent} onChange={(v) => update("medication_competent", v)} testid="sheet-med" />
                        <SwitchRow label="First Aider" checked={form.first_aider} onChange={(v) => update("first_aider", v)} testid="sheet-fa" />
                        <SwitchRow label="Fire Trained" checked={form.fire_trained} onChange={(v) => update("fire_trained", v)} testid="sheet-fire" />
                        <SwitchRow label="Admin Only (no shifts)" checked={form.is_admin_only} onChange={(v) => update("is_admin_only", v)} testid="sheet-admin-only" />
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                        <SwitchRow label="Can do Days" checked={form.can_do_days} onChange={(v) => update("can_do_days", v)} testid="sheet-can-day" />
                        <SwitchRow label="Can do Nights" checked={form.can_do_nights} onChange={(v) => update("can_do_nights", v)} testid="sheet-can-night" />
                        <SwitchRow label="Can do Sleepover" checked={form.can_do_sleepover} onChange={(v) => update("can_do_sleepover", v)} testid="sheet-can-sleep" />
                        <SwitchRow label="Accepts overtime (above contracted hours)" checked={!!form.accepts_overtime} onChange={(v) => update("accepts_overtime", v)} testid="sheet-accepts-ot" />
                    </div>

                    {/* Role flags — drive de-hardcoded solver rules */}
                    <div>
                        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Role flags (solver rules)</Label>
                        <div className="mt-1.5 flex flex-wrap gap-1.5" data-testid="sheet-role-flags">
                            {ROLE_FLAGS.map((f) => (
                                <RoleChipButton
                                    key={f.key}
                                    flag={f}
                                    active={!!form[f.key]}
                                    onToggle={() => update(f.key, !form[f.key])}
                                    testid={`sheet-role-${f.key}`}
                                />
                            ))}
                        </div>
                        <p className="text-[11px] text-muted-foreground italic mt-1.5">
                            These flags drive solver rules dynamically — e.g. tagging someone as Senior makes <code>senior_weekend_cover</code> apply to them on the next generate.
                        </p>
                    </div>

                    <SwitchRow label="Active" checked={form.active} onChange={(v) => update("active", v)} testid="sheet-active" />
                    <SheetFooter className="pt-4">
                        <Button type="submit" className="btn-primary" data-testid="sheet-save">{creating ? "Create" : "Save changes"}</Button>
                    </SheetFooter>
                </form>
            </SheetContent>
        </Sheet>
    );
}

function FormField({ label, children }) {
    return (
        <div>
            <Label className="text-xs uppercase tracking-wider text-muted-foreground">{label}</Label>
            <div className="mt-1.5">{children}</div>
        </div>
    );
}

function SwitchRow({ label, checked, onChange, testid }) {
    return (
        <div className="flex items-center justify-between p-3 rounded-lg border" style={{ borderColor: "hsl(var(--border))" }}>
            <span className="text-sm">{label}</span>
            <Switch checked={!!checked} onCheckedChange={onChange} data-testid={testid} />
        </div>
    );
}


/**
 * Segmented control for staff shift_preference (Day / Night / No Pref).
 * Disabled with tooltip when staff can only do one type.
 */
function PrefSegmented({ row, onChange }) {
    const both = !!row.can_do_days && !!row.can_do_nights;
    const value = row.shift_preference || "no_preference";
    const options = [
        { v: "day", label: "D" },
        { v: "night", label: "N" },
        { v: "no_preference", label: "—" },
    ];
    let lockedTooltip = "";
    if (!both) {
        if (row.can_do_days) lockedTooltip = "Auto: Day only";
        else if (row.can_do_nights) lockedTooltip = "Auto: Night only";
        else lockedTooltip = "No shift capability";
    }

    return (
        <div
            className="inline-flex rounded-md border overflow-hidden"
            style={{ borderColor: "hsl(var(--border-strong))", opacity: both ? 1 : 0.5 }}
            title={lockedTooltip || undefined}
            data-testid={`staff-${row.initials}-pref`}
        >
            {options.map((o) => (
                <button
                    key={o.v}
                    type="button"
                    disabled={!both}
                    onClick={() => both && onChange(o.v)}
                    className="text-[11px] px-2 py-1 transition-colors"
                    style={{
                        background: value === o.v
                            ? "hsl(var(--accent-bright-blue) / .25)"
                            : "transparent",
                        fontWeight: value === o.v ? 600 : 400,
                        cursor: both ? "pointer" : "not-allowed",
                    }}
                    data-testid={`staff-${row.initials}-pref-${o.v}`}
                >
                    {o.label}
                </button>
            ))}
        </div>
    );
}


/**
 * Compact row of role-flag chips (MGR/DEP/SEN/FLX/NGT). Clicking a chip
 * flips the corresponding `is_*` flag on the staff doc and surfaces the
 * change via `onToggle`. The chips visually feed back the active state
 * so managers can see at a glance which rules apply to each staff.
 */
function RoleFlagChips({ row, onToggle }) {
    return (
        <div className="flex flex-wrap gap-0.5" data-testid={`staff-${row.initials}-roles`}>
            {ROLE_FLAGS.map((f) => (
                <RoleChipButton
                    key={f.key}
                    flag={f}
                    active={!!row[f.key]}
                    onToggle={() => onToggle(f.key, !row[f.key])}
                    testid={`staff-${row.initials}-role-${f.key}`}
                />
            ))}
        </div>
    );
}

function RoleChipButton({ flag, active, onToggle, testid }) {
    const tone = TONE_COLORS[flag.tone] || TONE_COLORS.blue;
    return (
        <button
            type="button"
            onClick={onToggle}
            className="text-[9px] leading-none uppercase tracking-wider font-semibold px-1 py-[2px] rounded border transition-colors"
            style={{
                background: active ? tone.bg : "transparent",
                color: active ? tone.active : "hsl(var(--muted-foreground))",
                borderColor: active ? tone.active : "hsl(var(--border))",
            }}
            title={active ? `${flag.label} — click to unset` : `Click to tag as ${flag.label}`}
            data-testid={testid}
            data-active={active ? "true" : "false"}
        >
            {flag.code}
        </button>
    );
}
