import { useEffect, useState } from "react";
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Eye, EyeOff, KeyRound } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";

/** Returns a 0-3 strength score + label for the given password.
 *  0 = empty / too short, 1 = weak, 2 = ok, 3 = strong. */
function scorePassword(pw) {
    if (!pw || pw.length < 8) return { score: 0, label: "Too short" };
    let n = 0;
    if (/[a-z]/.test(pw)) n++;
    if (/[A-Z]/.test(pw)) n++;
    if (/[0-9]/.test(pw)) n++;
    if (/[^A-Za-z0-9]/.test(pw)) n++;
    if (pw.length >= 12) n++;
    return n <= 2 ? { score: 1, label: "Weak" }
        : n === 3 ? { score: 2, label: "OK" }
        : { score: 3, label: "Strong" };
}

/**
 * ChangePasswordDialog — authenticated user changes their own password.
 * Backend rotates the JWT on success; we still force a log-out so the
 * stale token in localStorage is wiped. Triggered from Layout user menu
 * AND from /set-new-password (where `firstLogin` is true and the current-
 * password is the temp password the manager handed over).
 */
export default function ChangePasswordDialog({
    open, onOpenChange, onSuccess,
    firstLogin = false,                    // true when forced by `password_must_change`
    initialCurrentPassword = "",
}) {
    const [curr, setCurr] = useState(initialCurrentPassword);
    const [next, setNext] = useState("");
    const [confirm, setConfirm] = useState("");
    const [showPw, setShowPw] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        if (!open) { setCurr(initialCurrentPassword); setNext(""); setConfirm(""); setShowPw(false); }
    }, [open, initialCurrentPassword]);

    const strength = scorePassword(next);
    const policyOk = next.length >= 8 && /[A-Za-z]/.test(next) && /[0-9]/.test(next);
    const matches = next === confirm && next.length > 0;
    const canSubmit = curr.length > 0 && policyOk && matches && !submitting;

    const submit = async () => {
        if (!canSubmit) return;
        setSubmitting(true);
        try {
            await api.post("/auth/change-password", {
                current_password: curr,
                new_password: next,
            });
            toast.success("Password updated. Please log in again.");
            onOpenChange(false);
            onSuccess?.();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={firstLogin ? () => {} : onOpenChange}>
            <DialogContent className="max-w-md" data-testid="change-password-dialog">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <KeyRound className="w-5 h-5" />
                        {firstLogin ? "Set a new password" : "Change password"}
                    </DialogTitle>
                    <DialogDescription>
                        {firstLogin
                            ? "Your password was reset by an admin. Choose a new one before you can use the app."
                            : "Update your password. You'll be logged out and asked to sign in again with the new one."}
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-3 text-sm">
                    <PwField
                        label={firstLogin ? "Temporary password" : "Current password"}
                        value={curr}
                        onChange={setCurr}
                        show={showPw}
                        onToggleShow={() => setShowPw((v) => !v)}
                        testid="cp-current"
                    />
                    <PwField
                        label="New password"
                        value={next}
                        onChange={setNext}
                        show={showPw}
                        onToggleShow={() => setShowPw((v) => !v)}
                        testid="cp-new"
                    />
                    {next && (
                        <StrengthBar strength={strength} policyOk={policyOk} />
                    )}
                    <PwField
                        label="Confirm new password"
                        value={confirm}
                        onChange={setConfirm}
                        show={showPw}
                        onToggleShow={() => setShowPw((v) => !v)}
                        testid="cp-confirm"
                    />
                    {confirm && !matches && (
                        <div className="text-xs text-destructive">Passwords don't match.</div>
                    )}
                </div>
                <DialogFooter>
                    {!firstLogin && (
                        <Button variant="outline" onClick={() => onOpenChange(false)} data-testid="cp-cancel">
                            Cancel
                        </Button>
                    )}
                    <Button
                        disabled={!canSubmit}
                        onClick={submit}
                        className="btn-primary"
                        data-testid="cp-submit"
                    >
                        {submitting ? "Updating…" : "Update password"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

function PwField({ label, value, onChange, show, onToggleShow, testid }) {
    return (
        <div>
            <Label className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</Label>
            <div className="relative">
                <Input
                    type={show ? "text" : "password"}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className="pr-10"
                    data-testid={testid}
                    autoComplete="new-password"
                />
                <button
                    type="button"
                    onClick={onToggleShow}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 text-muted-foreground"
                    aria-label="Toggle password visibility"
                    tabIndex={-1}
                >
                    {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
            </div>
        </div>
    );
}

function StrengthBar({ strength, policyOk }) {
    const colours = ["hsl(var(--muted))", "hsl(0 75% 55%)", "hsl(38 90% 50%)", "hsl(142 60% 40%)"];
    const colour = colours[strength.score] || colours[0];
    const widthPct = (strength.score + 1) * 25;
    return (
        <div data-testid="cp-strength">
            <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                    className="h-full transition-all"
                    style={{ width: `${widthPct}%`, background: colour }}
                />
            </div>
            <div className="flex items-center justify-between mt-1 text-[10px]">
                <span style={{ color: colour }}>{strength.label}</span>
                <span className={policyOk ? "text-muted-foreground" : "text-destructive"}>
                    {policyOk ? "Meets policy" : "Need ≥8 chars · letter + digit"}
                </span>
            </div>
        </div>
    );
}
