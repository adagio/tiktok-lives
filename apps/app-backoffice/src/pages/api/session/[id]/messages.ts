import type { APIRoute } from "astro";
import { getLatestViewerJoin, getSession, getSessionChatMessages, isSessionActive } from "@/lib/db";

export const GET: APIRoute = async ({ params, url }) => {
  const id = Number(params.id);
  if (isNaN(id)) {
    return new Response(JSON.stringify({ error: "Invalid id" }), { status: 400 });
  }

  const session = await getSession(id);
  if (!session) {
    return new Response(JSON.stringify({ error: "Not found" }), { status: 404 });
  }

  const since = url.searchParams.get("since") || undefined;
  const messages = await getSessionChatMessages(id, since);
  const active = await isSessionActive(id);
  const last_join = await getLatestViewerJoin(id);

  return new Response(
    JSON.stringify({ messages, is_active: active, last_join }),
    { headers: { "Content-Type": "application/json" } },
  );
};
