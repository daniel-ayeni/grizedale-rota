import { useEffect, useState } from "react";
import { Plus, Trash2, ShieldCheck, KeyRound, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
    AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

export default function Admins() {
    const { user } = useAuth();
    const [list, setList] = useState([]);
    const [loading, setLoading] = useState(true);
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState({ name: "", email: "", password: "" });
    const [creating, setCreating] = useState(false);
    // After clicking "Reset password" → backend returns the new temp
    // password ONCE. We hold it in state to render the read-it-and-copy
    // dialog; the plaintext never leaves the React state (no Redux,
    // no localStorage).
    const [resetResult, setResetResult] = useState(null);
    const [resettingId, setResettingId] = useState(null);

    const resetPassword = async (row) => {
        if (!window.confirm(`Reset password for ${row.name || row.email}? A temporary password will be generated.`)) return;
        setResettingId(row.id);
        try {
            const { data } = await api.post(`/admins/${row.id}/reset-password`);
            setResetResult(data);
        } catch (e) { toast.error(formatApiError(e)); }
        finally { setResettingId(null); }
    };

    const load = async () => {
        setLoading(true);
        try {
            const { data } = await api.get("/admins");
            setList(data);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setLoading(false);
        }
    };
    useEffect(() => { load(); }, []);

    const create = async (e) => {
        e.preventDefault();
        setCreating(true);
        try {
            const { data } = await api.post("/admins", form);
            setList((s) => [...s, data]);
            setForm({ name: "", email: "", password: "" });
            setOpen(false);
            toast.success(`${data.email} added`);
        } catch (err) {
            toast.error(formatApiError(err));
        } finally {
            setCreating(false);
        }
    };

    const remove = async (row) => {
        try {
            await api.delete(`/admins/${row.id}`);
            setList((s) => s.filter((x) => x.id !== row.id));
            toast.success(`${row.email} removed`);
        } catch (err) {
            toast.error(formatApiError(err));
        }
    };

    return (
        <div className="space-y-6" data-testid="admins-page">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="display text-3xl font-semibold">Admins</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Anyone in this list has full access to the rota builder.
                    </p>
                </div>
                <Dialog open={open} onOpenChange={setOpen}>
                    <DialogTrigger asChild>
                        <Button className="btn-primary" data-testid="admin-add-button">
                            <Plus className="w-4 h-4 mr-1.5" /> Add Admin
                        </Button>
                    </DialogTrigger>
                    <DialogContent data-testid="admin-add-dialog">
                        <DialogHeader>
                            <DialogTitle>Add admin</DialogTitle>
                            <DialogDescription>This account will have full access immediately.</DialogDescription>
                        </DialogHeader>
                        <form onSubmit={create} className="space-y-3">
                            <div>
                                <Label className="text-xs uppercase tracking-wider text-muted-foreground">Name</Label>
                                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required className="mt-1.5" data-testid="admin-form-name" />
                            </div>
                            <div>
                                <Label className="text-xs uppercase tracking-wider text-muted-foreground">Email</Label>
                                <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required className="mt-1.5" data-testid="admin-form-email" />
                            </div>
                            <div>
                                <Label className="text-xs uppercase tracking-wider text-muted-foreground">Password</Label>
                                <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required minLength={6} className="mt-1.5" data-testid="admin-form-password" />
                            </div>
                            <DialogFooter>
                                <Button type="submit" className="btn-primary" disabled={creating} data-testid="admin-form-submit">
                                    {creating ? "Adding…" : "Add Admin"}
                                </Button>
                            </DialogFooter>
                        </form>
                    </DialogContent>
                </Dialog>
            </div>

            <div className="section-header" data-testid="admins-section-header">Administrators · {list.length}</div>

            <div className="app-card overflow-x-auto" data-testid="admins-table-wrap">
                <Table className="paper-table" data-testid="admins-table">
                    <TableHeader>
                        <TableRow>
                            <TableHead>Name</TableHead>
                            <TableHead>Email</TableHead>
                            <TableHead className="hidden md:table-cell">Role</TableHead>
                            <TableHead className="hidden lg:table-cell">Created</TableHead>
                            <TableHead className="w-[100px] text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading && <TableRow><TableCell colSpan={5} className="text-center py-8 text-sm text-muted-foreground">Loading…</TableCell></TableRow>}
                        {!loading && list.length === 0 && <TableRow><TableCell colSpan={5} className="text-center py-8 text-sm text-muted-foreground">No admins</TableCell></TableRow>}
                        {list.map((row) => {
                            const isSelf = row.id === user?.id;
                            return (
                                <TableRow key={row.id} data-testid={`admin-row-${row.id}`}>
                                    <TableCell className="font-medium flex items-center gap-2">
                                        {row.name}
                                        {isSelf && <span className="text-xs uppercase tracking-wider text-muted-foreground">(you)</span>}
                                    </TableCell>
                                    <TableCell>{row.email}</TableCell>
                                    <TableCell className="hidden md:table-cell">
                                        <span className="inline-flex items-center gap-1 text-xs uppercase tracking-wider">
                                            <ShieldCheck className="w-3.5 h-3.5" /> {row.role}
                                        </span>
                                    </TableCell>
                                    <TableCell className="hidden lg:table-cell text-sm text-muted-foreground">{row.created_at?.slice(0, 10)}</TableCell>
                                    <TableCell className="text-right">
                                        <div className="flex justify-end gap-1">
                                            <Button
                                                size="sm"
                                                variant="ghost"
                                                disabled={isSelf || resettingId === row.id}
                                                onClick={() => resetPassword(row)}
                                                data-testid={`admin-${row.id}-reset-pw`}
                                                title={isSelf ? "Use 'Change password' in the user menu" : "Generate a temporary password"}
                                            >
                                                <KeyRound className="w-4 h-4" />
                                            </Button>
                                            <AlertDialog>
                                                <AlertDialogTrigger asChild>
                                                    <Button size="sm" variant="ghost" disabled={isSelf} data-testid={`admin-${row.id}-delete`}>
                                                        <Trash2 className="w-4 h-4 text-destructive" />
                                                    </Button>
                                                </AlertDialogTrigger>
                                                <AlertDialogContent>
                                                    <AlertDialogHeader>
                                                        <AlertDialogTitle>Delete {row.email}?</AlertDialogTitle>
                                                        <AlertDialogDescription>They will lose access immediately.</AlertDialogDescription>
                                                    </AlertDialogHeader>
                                                    <AlertDialogFooter>
                                                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                                                        <AlertDialogAction onClick={() => remove(row)} data-testid={`admin-${row.id}-confirm-delete`}>Delete</AlertDialogAction>
                                                    </AlertDialogFooter>
                                                </AlertDialogContent>
                                            </AlertDialog>
                                        </div>
                                    </TableCell>
                                </TableRow>
                            );
                        })}
                    </TableBody>
                </Table>
            </div>

            {/* Temp-password display modal — opens after a successful
                /admins/{id}/reset-password. The plaintext is shown
                ONCE and never persisted client-side. */}
            <Dialog open={!!resetResult} onOpenChange={(v) => { if (!v) setResetResult(null); }}>
                <DialogContent data-testid="reset-result-dialog" className="max-w-md">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <KeyRound className="w-5 h-5" /> Temporary password
                        </DialogTitle>
                        <DialogDescription>
                            Share this with <strong>{resetResult?.target_name || resetResult?.target_email}</strong> via a
                            secure channel (in person or encrypted message). They MUST change it on first login.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                        <div
                            className="p-3 rounded-md border font-mono text-lg tracking-wide select-all break-all"
                            style={{ background: "hsl(var(--bg-elev))", borderColor: "hsl(var(--border-strong))" }}
                            data-testid="reset-result-temp-password"
                        >
                            {resetResult?.temp_password}
                        </div>
                        <Button
                            variant="outline"
                            className="w-full"
                            onClick={async () => {
                                if (!resetResult?.temp_password) return;
                                try {
                                    await navigator.clipboard.writeText(resetResult.temp_password);
                                    toast.success("Temporary password copied");
                                } catch { toast.error("Couldn't copy — select & copy manually"); }
                            }}
                            data-testid="reset-result-copy"
                        >
                            <Copy className="w-3.5 h-3.5 mr-1.5" /> Copy
                        </Button>
                        <div className="text-[11px] italic text-muted-foreground">
                            This password will not be shown again. The admin will be forced to set a new one
                            on next login.
                        </div>
                    </div>
                    <DialogFooter>
                        <Button onClick={() => setResetResult(null)} data-testid="reset-result-done">I've shared it</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
