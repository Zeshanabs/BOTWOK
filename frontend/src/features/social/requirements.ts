/** Pre-connect requirement explainers (doc 24 §20, docs 26/27). Plain language; shown before any OAuth redirect. */

export interface Flavor { id: string; label: string; description: string }
export interface Requirement { summary: string; checklist: string[]; notes?: string[]; flavors?: Flavor[] }

export const REQUIREMENTS: Record<string, Requirement> = {
  facebook: {
    summary: "Connect a Facebook Page you manage.",
    checklist: ["You are an admin (or have full control) of the Facebook Page", "Botwok posts to Pages — personal profiles can't be connected"],
  },
  instagram: {
    summary: "Instagram publishing works only with a Professional (Business or Creator) account.",
    checklist: ["Your Instagram account is Professional (Business or Creator)", "For Facebook Login: the account is linked to a Facebook Page you can manage"],
    notes: ["Instagram fetches media by URL, so this install needs a public media URL configured for publishing to work."],
    flavors: [
      { id: "facebook_login", label: "Facebook Login (recommended)", description: "Requires a Professional account linked to a Facebook Page you manage. Broadest feature coverage." },
      { id: "instagram_login", label: "Instagram Login", description: "No Facebook Page needed, but still requires a Professional account. Token lasts ~60 days and is refreshed automatically." },
    ],
  },
  threads: {
    summary: "Connect your Threads profile.",
    checklist: ["You can sign in to the Threads profile you want to post as"],
  },
  linkedin: {
    summary: "Post as yourself or as a Company Page.",
    checklist: ["Personal profile posting is self-serve", "Company Page posting needs LinkedIn's Community Management API approval for this app, and you must be a Page admin"],
    notes: ["LinkedIn access tokens last 60 days and usually can't be refreshed automatically — expect to reconnect about every 60 days. Botwok warns you 7 days before."],
    flavors: [
      { id: "member", label: "Personal profile", description: "Self-serve: Sign In with LinkedIn + Share on LinkedIn." },
      { id: "organization", label: "Company Page", description: "Requires Community Management approval for this instance's LinkedIn app; disabled until approved." },
    ],
  },
  x: {
    summary: "Connect an X account.",
    checklist: ["You can sign in to the X account you want to post as"],
    notes: ["The X API is pay-per-use and billed to this instance's X developer account. Posts that contain a URL cost $0.20 each."],
  },
  tiktok: {
    summary: "Connect a TikTok Creator or Business account.",
    checklist: ["You can sign in to the TikTok account"],
    notes: ["Direct posting requires TikTok's app audit, which excludes internal tools. Botwok therefore uploads videos to your TikTok inbox as drafts; you finish posting in the TikTok app."],
  },
  youtube: {
    summary: "Connect a YouTube channel you own or manage.",
    checklist: ["You are the channel owner or a manager"],
    notes: ["Until this app passes Google's audit, uploads are private (visible only to you). Uploads consume API quota."],
  },
  pinterest: {
    summary: "Connect a Pinterest Business account.",
    checklist: ["Your Pinterest account is a Business account"],
    notes: ["While the app has Trial access, pins are created as private — only you can see them until Standard access is granted."],
  },
  gbp: {
    summary: "Connect a Google Business Profile location.",
    checklist: ["You are an owner or manager of the location"],
    notes: ["Google Business Profile API access must be approved for this instance before posting works."],
  },
};

/** Plain-language names for common OAuth scopes (technical names are shown alongside). */
export const SCOPE_LABELS: Record<string, string> = {
  instagram_basic: "Read profile", instagram_content_publish: "Publish posts", instagram_manage_insights: "Read insights",
  pages_show_list: "List your Pages", pages_read_engagement: "Read Page engagement", pages_manage_posts: "Publish to Page", business_management: "Access business assets",
  w_member_social: "Post as you", r_organization_social: "Read Page posts", w_organization_social: "Post as Page", rw_organization_admin: "Manage Page",
  "tweet.read": "Read posts", "tweet.write": "Publish posts", "users.read": "Read profile", "offline.access": "Stay connected",
  "video.upload": "Upload videos (inbox)", "video.publish": "Publish videos", "user.info.basic": "Read profile",
};
