import { useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router";
import { MessageSquareText } from "lucide-react";
import { ApiError } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Input, Label } from "../../components/ui/input";
import { useAuthActions, useSession } from "./useSession";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const session = useSession();
  const { login, register } = useAuthActions();
  const action = mode === "login" ? login : register;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  if (session.data) return <Navigate to="/" replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    action.mutate({ email, password });
  };
  const error = action.error;
  const fieldErrors = error instanceof ApiError && error.code === "validation_error";

  return (
    <main className="flex min-h-full items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <div className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <MessageSquareText className="size-6" />
          </div>
          <h1 className="text-xl font-semibold">{mode === "login" ? "Sign in" : "Create your account"}</h1>
          <p className="text-sm text-muted-foreground">Customer support assistant</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-lg border bg-card p-6 shadow-sm" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {mode === "register" && <p className="text-xs text-muted-foreground">At least 8 characters.</p>}
          </div>
          {error && (
            <p role="alert" className="rounded-md bg-destructive-muted px-3 py-2 text-sm text-destructive">
              {fieldErrors ? "Please enter a valid email and a password of at least 8 characters." : error.message}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={action.isPending}>
            {action.isPending ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          {mode === "login" ? (
            <>
              No account? <Link className="text-primary underline" to="/register">Create one</Link>
            </>
          ) : (
            <>
              Already registered? <Link className="text-primary underline" to="/login">Sign in</Link>
            </>
          )}
        </p>
      </div>
    </main>
  );
}
