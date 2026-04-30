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
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
    AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";

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
    active: true,
};

export default function Staff() {
    const [staff, setStaff] = useState([]);
    const [loading, setLoading] = useState(true);
    const [editing, setEditing] = useState(null); // staff doc or null
    const [creating, setCreating] = useState(false);

    const load = async () => {
        setLoading(true);
        try {
            const { data } = await api.get("/staff");
            setStaff(data.sort((a, b) => a.initials.localeCompare(b.initials)));
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

    const remove = async (row) => {
        try {
            await api.delete(`/staff/${row.id}`);
            setStaff((s) => s.filter((x) => x.id !== row.id));
            toast.success(`${row.initials} deleted`);
        } catch (e) {
            toast.error(formatApiError(e));
        }
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
                            <TableHead className="hidden lg:table-cell">Role</TableHead>
                            <TableHead className="text-center">Hrs</TableHead>
                            <TableHead className="text-center">Gender</TableHead>
                            <TableHead className="text-center">Med</TableHead>
                            <TableHead className="text-center">FA</TableHead>
                            <TableHead className="text-center">Fire</TableHead>
                            <TableHead className="text-center hidden md:table-cell">Day</TableHead>
                            <TableHead className="text-center hidden md:table-cell">Night</TableHead>
                            <TableHead className="text-center hidden md:table-cell">Sleep</TableHead>
                            <TableHead className="text-center">Active</TableHead>
                            <TableHead className="w-[100px] text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading && (
                            <TableRow><TableCell colSpan={13} className="text-center text-sm text-muted-foreground py-8">Loading…</TableCell></TableRow>
                        )}
                        {!loading && staff.length === 0 && (
                            <TableRow><TableCell colSpan={13} className="text-center text-sm text-muted-foreground py-8">No staff yet</TableCell></TableRow>
                        )}
                        {staff.map((row) => (
                            <TableRow key={row.id} data-testid={`staff-row-${row.initials}`}>
                                <TableCell className="font-semibold">{row.initials}</TableCell>
                                <TableCell>
                                    <div className="font-medium">{row.full_name}</div>
                                    <div className="text-xs text-muted-foreground lg:hidden">{row.role}</div>
                                </TableCell>
                                <TableCell className="hidden lg:table-cell text-sm text-muted-foreground">{row.role}</TableCell>
                                <TableCell className="text-center">{row.target_weekly_hours}</TableCell>
                                <TableCell className="text-center">{row.gender}</TableCell>
                                <TableCell className="text-center"><Switch checked={row.medication_competent} onCheckedChange={(v) => togglePatch(row, "medication_competent", v)} data-testid={`staff-${row.initials}-med`} /></TableCell>
                                <TableCell className="text-center"><Switch checked={row.first_aider} onCheckedChange={(v) => togglePatch(row, "first_aider", v)} data-testid={`staff-${row.initials}-fa`} /></TableCell>
                                <TableCell className="text-center"><Switch checked={row.fire_trained} onCheckedChange={(v) => togglePatch(row, "fire_trained", v)} data-testid={`staff-${row.initials}-fire`} /></TableCell>
                                <TableCell className="text-center hidden md:table-cell"><Switch checked={row.can_do_days} onCheckedChange={(v) => togglePatch(row, "can_do_days", v)} data-testid={`staff-${row.initials}-day`} /></TableCell>
                                <TableCell className="text-center hidden md:table-cell"><Switch checked={row.can_do_nights} onCheckedChange={(v) => togglePatch(row, "can_do_nights", v)} data-testid={`staff-${row.initials}-night`} /></TableCell>
                                <TableCell className="text-center hidden md:table-cell"><Switch checked={row.can_do_sleepover} onCheckedChange={(v) => togglePatch(row, "can_do_sleepover", v)} data-testid={`staff-${row.initials}-sleep`} /></TableCell>
                                <TableCell className="text-center"><Switch checked={row.active} onCheckedChange={(v) => togglePatch(row, "active", v)} data-testid={`staff-${row.initials}-active`} /></TableCell>
                                <TableCell className="text-right">
                                    <div className="flex justify-end gap-1">
                                        <Button size="sm" variant="ghost" onClick={() => { setEditing(row); setCreating(false); }} data-testid={`staff-${row.initials}-edit`}>
                                            <Pencil className="w-4 h-4" />
                                        </Button>
                                        <AlertDialog>
                                            <AlertDialogTrigger asChild>
                                                <Button size="sm" variant="ghost" data-testid={`staff-${row.initials}-delete`}>
                                                    <Trash2 className="w-4 h-4 text-destructive" />
                                                </Button>
                                            </AlertDialogTrigger>
                                            <AlertDialogContent>
                                                <AlertDialogHeader>
                                                    <AlertDialogTitle>Delete {row.initials}?</AlertDialogTitle>
                                                    <AlertDialogDescription>This will permanently remove the staff record. The solver will no longer schedule shifts for them.</AlertDialogDescription>
                                                </AlertDialogHeader>
                                                <AlertDialogFooter>
                                                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                                                    <AlertDialogAction onClick={() => remove(row)} data-testid={`staff-${row.initials}-confirm-delete`}>Delete</AlertDialogAction>
                                                </AlertDialogFooter>
                                            </AlertDialogContent>
                                        </AlertDialog>
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
                        return exists ? s.map((x) => (x.id === saved.id ? saved : x)) : [...s, saved].sort((a,b) => a.initials.localeCompare(b.initials));
                    });
                    setEditing(null);
                    setCreating(false);
                }}
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
