import type { APIRoute } from "astro";
import { readWatchlist } from "@/lib/watchlist";
import {
  getLatestSessionByUsername,
  getChatMessageCount,
  isSessionActive,
  getLatestVideo,
  getActiveGuests,
} from "@/lib/db";

export const GET: APIRoute = async () => {
  try {
    const watchlist = await readWatchlist();

    const users = await Promise.all(watchlist.users
      .filter((u) => u.enabled)
      .map(async (u) => {
        const session = await getLatestSessionByUsername(u.username);
        const active_guests = session ? await getActiveGuests(session.id) : [];
        const is_live = (session ? await isSessionActive(session.id) : false) || active_guests.length > 0;
        const message_count = session ? await getChatMessageCount(session.id) : 0;

        const latestVideo = await getLatestVideo(u.username);

        return {
          username: u.username,
          is_live,
          active_guests,
          latest_session: session
            ? {
                id: session.id,
                date: session.date,
                duration_seconds: session.duration_seconds,
              }
            : null,
          message_count,
          latest_video: latestVideo
            ? {
                video_id: latestVideo.video_id,
                description: latestVideo.description,
                create_time: latestVideo.create_time,
              }
            : null,
        };
      }));

    return new Response(JSON.stringify({ users }), {
      headers: { "Content-Type": "application/json" },
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown error";
    return new Response(JSON.stringify({ error: message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
};
