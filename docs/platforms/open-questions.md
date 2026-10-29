# Platform open questions (must be verified before enabling the related feature)

| Platform | Question | Blocks | Owner / status |
|---|---|---|---|
| Facebook | Exact parameter for multi-photo feed posts (`attached_media` with unpublished photo ids) | Facebook carousel/multi-photo | open |
| Facebook | Alt text on photos and poll support via API | validators | open |
| Facebook | Stories max video length (docs show 60 s and 90 s) | Stories validation | assume 60 s |
| Instagram | `follower_count`, `online_followers` account metrics still available | best-time audience signal | open |
| Instagram | `instagram_business_manage_insights` scope on Instagram Login (missing from login scope list) | IG Login insights | open |
| Threads | Business Verification required for App Review? | competitor features | open |
| Threads | Endpoint for reading another profile's posts (beyond keyword search/profile lookup) | competitor posts | open |
| LinkedIn | Max `commentary` length (FIELD_LENGTH_TOO_LONG threshold); approval turnaround for Community Management | validators; roadmap | open (assume 3,000) |
| X | Refresh-token lifetime/rotation; 3,200-post timeline cap; self-reply exemption from "summoned" rule (secondary source) | threads feature flag | verify in sandbox |
| Pinterest | Video size/duration specs; comments API | video pins | open |
| GBP | Max post length and media count; OAuth verification requirement for `business.manage` | GBP validators | open |
| YouTube | Scope sensitivity classification; `batchGetStats` max ids per call; custom thumbnails on Shorts | verification plan; competitor sync batching | open |
| TikTok | Inbox upload for non-private accounts without audit; Business API photo publishing/scheduling/delete; US-specific changes after Jan 2026 | TikTok modes | open |
