## REMOVED Requirements

### Requirement: Join events stored as chat messages
**Reason**: Join events were stored as `chat_messages` rows with `text='__join__'`, but the `guests` table already captures joins with richer data (user_id, joined_at, left_at). This was redundant.
**Migration**: The `guests` table is the sole source of truth for join events. Old `__join__` rows remain in `chat_messages` but are filtered out at render time.
