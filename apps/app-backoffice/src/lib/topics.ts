export interface TopicScore {
  id: string;
  label: string;
  color: string;
  /** Raw cosine similarity (max across chunks) */
  rawScore: number;
  /** Normalized 0-100 score (relative to context range) */
  normalizedScore: number;
}

export interface TopicMeta {
  label: string;
  color: string;
}

export const TOPIC_META: Record<string, TopicMeta> = {
  risas: { label: "Risas", color: "var(--color-accent-orange)" },
  baile: { label: "Baile", color: "var(--color-accent-pink)" },
  bromas: { label: "Bromas", color: "var(--color-accent-cyan)" },
  reflexion: { label: "Reflexión", color: "var(--color-accent-green)" },
  guinos: { label: "Guiños", color: "var(--color-brand)" },
  besos: { label: "Besos", color: "#f9a8d4" },
};

export const TOPIC_IDS = Object.keys(TOPIC_META);

/** Min-max normalize an array of raw scores to 0-100 */
export function normalizeScores(
  items: { id: string; rawScore: number }[],
): TopicScore[] {
  if (items.length === 0) return [];

  const scores = items.map((i) => i.rawScore);
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min;

  return items
    .map((item) => {
      const meta = TOPIC_META[item.id] || { label: item.id, color: "var(--color-text-muted)" };
      return {
        id: item.id,
        label: meta.label,
        color: meta.color,
        rawScore: item.rawScore,
        normalizedScore: range > 0 ? ((item.rawScore - min) / range) * 100 : 50,
      };
    })
    .sort((a, b) => b.normalizedScore - a.normalizedScore);
}
