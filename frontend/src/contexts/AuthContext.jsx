import { createContext, useCallback, useContext, useEffect, useState } from "react";
import api, { setToken, getToken, formatApiError } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(undefined); // undefined=loading, null=not logged in
    const [error, setError] = useState(null);

    const refreshMe = useCallback(async () => {
        if (!getToken()) {
            setUser(null);
            return;
        }
        try {
            const { data } = await api.get("/auth/me");
            setUser(data);
        } catch {
            setToken(null);
            setUser(null);
        }
    }, []);

    useEffect(() => {
        refreshMe();
    }, [refreshMe]);

    const login = async (email, password) => {
        setError(null);
        try {
            const { data } = await api.post("/auth/login", { email, password });
            setToken(data.token);
            setUser(data.user);
            return data.user;
        } catch (e) {
            const msg = formatApiError(e);
            setError(msg);
            throw new Error(msg);
        }
    };

    const logout = async () => {
        try {
            await api.post("/auth/logout");
        } catch {
            // ignore — token might already be invalid
        }
        setToken(null);
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, error, login, logout, refreshMe }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error("useAuth must be used within AuthProvider");
    return ctx;
}
