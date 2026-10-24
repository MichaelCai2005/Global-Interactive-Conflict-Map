import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request, sessionToken, setSessionToken } from "./client";

export interface User {
  id: number;
  email: string;
  display_name: string;
  created_at: string;
}

/** Who is signed in, and whose data the watchlist, tasks and boards show (backend app/auth.py). */
export interface Me {
  user: User | null;
  /** "personal": signed in. "shared": a local install's shared workspace. null: sign in to save anything. */
  workspace: "personal" | "shared" | null;
  signups_open: boolean;
}

export interface SavedSearch {
  id: number;
  name: string;
  kind: "map" | "topic";
  /** A map view keeps its address-bar query in `query`; a topic keeps the topic search's input. */
  params: Record<string, unknown>;
  created_at: string;
  last_used_at: string | null;
}

/** Queries whose answer depends on who is signed in. */
const PERSONAL = new Set(["me", "watchlist", "tasks", "boards", "board", "board-geojson", "searches"]);

function refreshPersonal(client: QueryClient, me?: Me) {
  if (me) client.setQueryData(["me"], me);
  return client.invalidateQueries({ predicate: (q) => PERSONAL.has(String(q.queryKey[0])) });
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const me = await request<Me>("/auth/me");
      // A stored token the API no longer knows (expired, or signed out elsewhere).
      if (!me.user && sessionToken()) setSessionToken(null);
      return me;
    },
    staleTime: 5 * 60_000,
  });
}

/** Sign-in and sign-up also return the token, kept for an API on another site. */
type SignedIn = Me & { token: string };

async function signInWith(path: string, body: Credentials): Promise<Me> {
  const { token, ...me } = await request<SignedIn>(path, { method: "POST", json: body });
  setSessionToken(token);
  return me;
}

export interface Credentials {
  email: string;
  password: string;
  display_name?: string;
}

export function useAccount() {
  const client = useQueryClient();
  const onSuccess = (me?: Me | void) => refreshPersonal(client, me ?? undefined);
  return {
    signIn: useMutation({
      mutationFn: (body: Credentials) => signInWith("/auth/login", body),
      onSuccess,
    }),
    signUp: useMutation({
      mutationFn: (body: Credentials) => signInWith("/auth/signup", body),
      onSuccess,
    }),
    signOut: useMutation({
      mutationFn: () => request<void>("/auth/logout", { method: "POST" }).finally(() => setSessionToken(null)),
      onSuccess: () => onSuccess(),
    }),
    remove: useMutation({
      mutationFn: async (password: string) => {
        await request<void>("/auth/me", { method: "DELETE", json: { password } });
        setSessionToken(null);
      },
      onSuccess: () => onSuccess(),
    }),
  };
}

export function useSavedSearches(enabled: boolean) {
  return useQuery({
    queryKey: ["searches"],
    queryFn: () => request<SavedSearch[]>("/searches"),
    enabled,
  });
}

export function useSavedSearchMutations() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ["searches"] });
  return {
    create: useMutation({
      mutationFn: (body: Pick<SavedSearch, "name" | "kind" | "params">) =>
        request<SavedSearch>("/searches", { method: "POST", json: body }),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: { id: number; name?: string; used?: boolean }) =>
        request<SavedSearch>(`/searches/${id}`, { method: "PATCH", json: body }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: number) => request<void>(`/searches/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}
