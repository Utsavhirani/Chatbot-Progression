import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Menu, X } from "lucide-react";
import { useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useParams } from "react-router";
import { ApiError } from "./api/client";
import { Button } from "./components/ui/button";
import { AuthPage } from "./features/auth/AuthPage";
import { useSession } from "./features/auth/useSession";
import { ChatPage } from "./features/chat/ChatPage";
import { Sidebar } from "./features/conversations/Sidebar";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // Don't retry client errors (401/404/...); retry transient ones once.
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 1,
    },
  },
});

function RequireAuth() {
  const session = useSession();
  if (session.isLoading) return <FullPageMessage text="Loading…" />;
  if (session.error) return <FullPageMessage text="The server is unavailable. Please try again shortly." />;
  if (!session.data) return <Navigate to="/login" replace />;
  return <Outlet />;
}

function AppLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  return (
    <div className="flex h-full">
      <aside className="hidden w-72 shrink-0 border-r md:block">
        <Sidebar />
      </aside>
      {drawerOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDrawerOpen(false)} />
          <aside className="relative h-full w-72 max-w-[85%] border-r bg-background">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Close menu"
              className="absolute right-2 top-3 z-10"
              onClick={() => setDrawerOpen(false)}
            >
              <X className="size-4" />
            </Button>
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}
      <main className="relative flex min-w-0 flex-1 flex-col">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Open menu"
          className="absolute left-2 top-2.5 z-10 md:hidden"
          onClick={() => setDrawerOpen(true)}
        >
          <Menu className="size-4" />
        </Button>
        <div className="min-h-0 flex-1 pl-8 md:pl-0">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function ConversationRoute() {
  const { conversationId } = useParams();
  // key: fresh chat state per conversation
  return <ChatPage key={conversationId} conversationId={conversationId} />;
}

function FullPageMessage({ text }: { text: string }) {
  return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">{text}</div>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route element={<RequireAuth />}>
            <Route element={<AppLayout />}>
              <Route index element={<ChatPage key="new" />} />
              <Route path="/c/:conversationId" element={<ConversationRoute />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
