import type { APIRoute } from "astro";
import { getLatestViewerJoin, getSession, getSessionChatMessages, isSessionActive } from "@/lib/db";

export const GET: APIRoute = ({ params, url }) => {
  const id = Number(params.id);
  if (isNaN(id)) {
    return new Response(JSON.stringify({ error: "Invalid id" }), { status: 400 });
  }

  const session = getSession(id);
  if (!session) {
    return new Response(JSON.stringify({ error: "Not found" }), { status: 404 });
  }

  const since = url.searchParams.get("since") || undefined;
  const messages = getSessionChatMessages(id, since);
  const active = isSessionActive(id);
  const last_join = getLatestViewerJoin(id);

  return new Response(
    JSON.stringify({ messages, is_active: active, last_join }),
    { headers: { "Content-Type": "application/json" } },
  );
};
