/**
 * Platform presets for the AI Agent (Copywriter) node.
 * Object keyed by preset id stored in node.data.platform_preset.
 * Backend executor uses the same id to look up char limits in PLATFORM_LIMITS.
 */
export const PLATFORM_PRESETS = {
  instagram: {
    label: 'Instagram',
    maxChars: 2200,
    hashtagBlock: true,
    systemPrompt:
      'You are a senior Instagram copywriter. Write a hook (1 line), body (2-3 sentences), CTA, then 5-8 niche hashtags grouped on a new line block. Stay under 2200 characters.',
  },
  twitter: {
    label: 'X / Twitter',
    maxChars: 280,
    hashtagBlock: false,
    systemPrompt:
      'You are a senior X/Twitter copywriter. Write a single hook-first post within 280 characters. No trailing hashtag block — one or two inline hashtags at most.',
  },
  linkedin: {
    label: 'LinkedIn',
    maxChars: 3000,
    hashtagBlock: false,
    systemPrompt:
      'You are a senior LinkedIn copywriter. Professional tone, storytelling structure (hook → insight → takeaway). No inline hashtags. Close with a thought-provoking question or CTA. Stay under 3000 characters.',
  },
  tiktok: {
    label: 'TikTok',
    maxChars: 2200,
    hashtagBlock: true,
    systemPrompt:
      'You are a senior TikTok copywriter. Casual, energetic, on-trend tone. Strong hook in line one. End with 4-6 trending hashtags grouped on a new line block. Stay under 2200 characters.',
  },
  youtube_description: {
    label: 'YouTube Description',
    maxChars: 5000,
    hashtagBlock: false,
    systemPrompt:
      'You are a senior YouTube SEO copywriter. Keyword-rich first 200 characters (above-the-fold). Include a short context paragraph, a links/timestamps section placeholder, and 5-10 hashtags. Stay under 5000 characters.',
  },
};
