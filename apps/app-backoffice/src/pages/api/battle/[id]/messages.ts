import type { APIRoute } from "astro";
import { getBattle, getBattleChatMessages, getLatestViewerJoin, isBattleActive } from "@/lib/db";

export const GET: APIRoute = ({ params, url }) => {
  const id = Number(params.id);
  if (isNaN(id)) {
    return new Response(JSON.stringify({ error: "Invalid id" }), { status: 400 });
  }

  const battle = getBattle(id);
  if (!battle) {
    return new Response(JSON.stringify({ error: "Not found" }), { status: 404 });
  }

  const since = url.searchParams.get("since") || undefined;
  const messages = getBattleChatMessages(battle.battle_id, since);
  const active = isBattleActive(battle.battle_id);
  const last_join = getLatestViewerJoin(battle.session_id);

  return new Response(
    JSON.stringify({
      messages,
      battle: {
        host_score: battle.host_score,
        opponent_score: battle.opponent_score,
        is_active: active,
      },
      last_join,
    }),
    {
      headers: { "Content-Type": "application/json" },
    },
  );
};
