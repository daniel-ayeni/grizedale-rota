import { useEffect, useState } from "react";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
    Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
    AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";

const EMPTY = { name: "", notes: "", needs_female_staff: false, needs_med_competent_present: false, active: true };

export default function ServiceUsers() {
    const [list, setList] = useState([]);
    const [loading, setLoading] = useState(true);
    const [editing, setEditing] = useState(null);
    const [creating, setCreating] = useState(false);

    const load = async () => {
        setLoading(true);
        try {
            const { data } = await api.get("/service-users");
            setList(data.sort((a, b) => a.name.localeCompare(b.name)));
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const togglePatch = async (row, key, value) => {
        try {
            const { data } = await api.put(`/service-users/${row.id}`, { [key]: value });
            setList((s) => s.map((x) => (x.id === row.id ? data : x)));
            toast.success(`${row.name}: ${key} updated`);
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };

    const remove = async (row) => {
        try {
            await api.delete(`/service-users/${row.id}`);
            setList((s) => s.filter((x) => x.id !== row.id));
            toast.success(`${row.name} deleted`);
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };

    return (
        <div className="space-y-6" data-testid="service-users-page">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="display text-3xl font-semibold">Service Users</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Residents and their care needs. Affects rota constraints.
                    </p>
                </div>
                <Button
                    className="btn-primary"
                    onClick={() => { setEditing({ ...EMPTY }); setCreating(true); }}
                    data-testid="su-add-button"
                >
                    <Plus className="w-4 h-4 mr-1.5" /> Add Service User
                </Button>
            </div>

            <div className="section-header" data-testid="su-section-header">{list.length} service users</div>

            <div className="app-card overflow-x-auto" data-testid="su-table-wrap">
                <Table className="paper-table" data-testid="su-table">
                    <TableHeader>
                        <TableRow>
                            <TableHead>Name</TableHead>
                            <TableHead className="hidden md:table-cell">Notes</TableHead>
                            <TableHead className="text-center">Female Staff</TableHead>
                            <TableHead className="text-center">Med-Competent</TableHead>
                            <TableHead className="text-center">Active</TableHead>
                            <TableHead className="w-[100px] text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading && <TableRow><TableCell colSpan={6} className="text-center py-8 text-sm text-muted-foreground">Loading…</TableCell></TableRow>}
                        {!loading && list.length === 0 && <TableRow><TableCell colSpan={6} className="text-center py-8 text-sm text-muted-foreground">No service users</TableCell></TableRow>}
                        {list.map((row) => (
                            <TableRow key={row.id} data-testid={`su-row-${row.id}`}>
                                <TableCell className="font-medium">{row.name}</TableCell>
                                <TableCell className="hidden md:table-cell text-sm text-muted-foreground max-w-xs truncate">{row.notes || "—"}</TableCell>
                                <TableCell className="text-center"><Switch checked={!!row.needs_female_staff} onCheckedChange={(v) => togglePatch(row, "needs_female_staff", v)} data-testid={`su-${row.id}-female`} /></TableCell>
                                <TableCell className="text-center"><Switch checked={!!row.needs_med_competent_present} onCheckedChange={(v) => togglePatch(row, "needs_med_competent_present", v)} data-testid={`su-${row.id}-med`} /></TableCell>
                                <TableCell className="text-center"><Switch checked={!!row.active} onCheckedChange={(v) => togglePatch(row, "active", v)} data-testid={`su-${row.id}-active`} /></TableCell>
                                <TableCell className="text-right">
                                    <div className="flex justify-end gap-1">
                                        <Button size="sm" variant="ghost" onClick={() => { setEditing(row); setCreating(false); }} data-testid={`su-${row.id}-edit`}>
                                            <Pencil className="w-4 h-4" />
                                        </Button>
                                        <AlertDialog>
                                            <AlertDialogTrigger asChild>
                                                <Button size="sm" variant="ghost" data-testid={`su-${row.id}-delete`}>
                                                    <Trash2 className="w-4 h-4 text-destructive" />
                                                </Button>
                                            </AlertDialogTrigger>
                                            <AlertDialogContent>
                                                <AlertDialogHeader>
                                                    <AlertDialogTitle>Delete {row.name}?</AlertDialogTitle>
                                                    <AlertDialogDescription>This permanently removes the service user from the records.</AlertDialogDescription>
                                                </AlertDialogHeader>
                                                <AlertDialogFooter>
                                                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                                                    <AlertDialogAction onClick={() => remove(row)} data-testid={`su-${row.id}-confirm-delete`}>Delete</AlertDialogAction>
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

            <ServiceUserSheet
                open={!!editing}
                onOpenChange={(v) => { if (!v) { setEditing(null); setCreating(false); } }}
                value={editing}
                creating={creating}
                onSaved={(saved) => {
                    setList((s) => {
                        const exists = s.some((x) => x.id === saved.id);
                        return exists ? s.map((x) => (x.id === saved.id ? saved : x)) : [...s, saved].sort((a,b) => a.name.localeCompare(b.name));
                    });
                    setEditing(null);
                    setCreating(false);
                }}
            />
        </div>
    );
}

function ServiceUserSheet({ open, onOpenChange, value, creating, onSaved }) {
    const [form, setForm] = useState(value || EMPTY);
    useEffect(() => { setForm(value || EMPTY); }, [value]);

    if (!form) return null;
    const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));

    const submit = async (e) => {
        e.preventDefault();
        try {
            if (creating) {
                const { data } = await api.post("/service-users", form);
                onSaved(data);
                toast.success("Created");
            } else {
                const { data } = await api.put(`/service-users/${form.id}`, form);
                onSaved(data);
                toast.success("Saved");
            }
        } catch (err) {
            toast.error(formatApiError(err));
        }
    };

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="overflow-y-auto sm:max-w-xl" data-testid="su-sheet">
                <SheetHeader>
                    <SheetTitle>{creating ? "Add Service User" : `Edit ${form.name}`}</SheetTitle>
                    <SheetDescription>Care needs feed into rota constraints.</SheetDescription>
                </SheetHeader>
                <form onSubmit={submit} className="space-y-4 mt-4">
                    <div>
                        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Name</Label>
                        <Input value={form.name} onChange={(e) => update("name", e.target.value)} required className="mt-1.5" data-testid="su-sheet-name" />
                    </div>
                    <div>
                        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Notes</Label>
                        <Textarea value={form.notes || ""} onChange={(e) => update("notes", e.target.value)} className="mt-1.5" rows={4} data-testid="su-sheet-notes" />
                    </div>
                    <div className="space-y-2">
                        <SwitchRow label="Needs female staff" checked={form.needs_female_staff} onChange={(v) => update("needs_female_staff", v)} testid="su-sheet-female" />
                        <SwitchRow label="Needs medication-competent staff present" checked={form.needs_med_competent_present} onChange={(v) => update("needs_med_competent_present", v)} testid="su-sheet-med" />
                        <SwitchRow label="Active" checked={form.active} onChange={(v) => update("active", v)} testid="su-sheet-active" />
                    </div>
                    <SheetFooter className="pt-4">
                        <Button type="submit" className="btn-primary" data-testid="su-sheet-save">{creating ? "Create" : "Save"}</Button>
                    </SheetFooter>
                </form>
            </SheetContent>
        </Sheet>
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
