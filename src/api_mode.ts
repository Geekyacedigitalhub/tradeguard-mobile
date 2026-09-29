export const BOT_MODES = ["signals_only", "semi_auto", "full_auto"] as const;
export type BotMode = typeof BOT_MODES[number];
