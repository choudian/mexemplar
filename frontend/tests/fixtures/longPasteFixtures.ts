/**
 * Shared test fixtures for long-paste composer interaction.
 *
 * Thresholds (from contract):
 *   - Line count: > 6 logical lines triggers collapse
 *   - Code units: > 1200 JavaScript string.length code units triggers collapse
 *
 * Logical lines are counted by splitting on /\r\n|\n|\r/ without normalizing.
 */

/** 7 logical lines — qualifies by line-count threshold (exactly 7 > 6) */
export const SEVEN_LINE_TEXT = [
  "第一行内容",
  "第二行内容",
  "第三行内容",
  "第四行内容",
  "第五行内容",
  "第六行内容",
  "第七行内容",
].join("\n");

/** 6 logical lines — does NOT qualify by line count alone */
export const SIX_LINE_TEXT = [
  "第一行",
  "第二行",
  "第三行",
  "第四行",
  "第五行",
  "第六行",
].join("\n");

/** Exactly 1200 code units — does NOT qualify by character threshold */
export const EXACTLY_1200_CHARS = "a".repeat(1200);

/** 1201 code units single line — qualifies by character threshold */
export const CHARS_1201 = "a".repeat(1201);

/** Mixed newline text with \r\n and \n — qualifies by line count */
export const MIXED_NEWLINE_TEXT = "line1\r\nline2\nline3\r\nline4\nline5\r\nline6\nline7";

/** Empty lines interspersed — 7 logical lines including blanks */
export const WITH_EMPTY_LINES = "line1\n\nline3\n\nline5\nline6\nline7";

/** Middle-selection paste fixtures */
export const BEFORE_SELECTION = "Hello ";
export const SELECTION_TEXT = "world";
export const AFTER_SELECTION = " goodbye";
export const PASTE_TEXT = "beautiful";

/** Expected result of middle-selection paste: before + paste + after */
export const MIDDLE_SELECTION_RESULT = "Hello beautiful goodbye";

/**
 * Helper: count logical lines by splitting on /\r\n|\n|\r/.
 * Matches the contract's line-counting rule exactly.
 */
export function countLogicalLines(text: string): number {
  if (text.length === 0) return 1;
  return text.split(/\r\n|\n|\r/).length;
}

/**
 * Helper: check if a text qualifies for long-paste collapse.
 * Must be > 6 lines OR > 1200 code units.
 */
export function qualifiesForCollapse(text: string): boolean {
  return countLogicalLines(text) > 6 || text.length > 1200;
}
