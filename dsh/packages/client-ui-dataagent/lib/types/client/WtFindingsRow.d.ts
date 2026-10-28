/**
 * Keyed tool view for `wt_findings`.
 *
 * The point of this view is one distinction: an item that was **assessed and
 * failed** is not the same as an item that could **not be assessed**. In a flat
 * text dump those read alike, and a 未评定 item mistaken for a pass is the exact
 * failure this module exists to prevent. So the two live in separate blocks
 * with different labels, and the unassessed block states what is missing.
 *
 * Pure function of the durable slice — no service reads, no clock — so it
 * replays identically from the session log.
 */
import { type ReactNode } from 'react';
import type { ToolCallViewProps } from '@deepseek-ai/dsh-client-ui-tool/client';
export declare function WtFindingsRow({ block }: ToolCallViewProps): ReactNode;
