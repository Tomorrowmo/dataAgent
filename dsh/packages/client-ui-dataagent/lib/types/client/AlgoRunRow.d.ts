/**
 * Keyed tool view for `algo_run`.
 *
 * Shows the lineage edge the run created — parent dataset, operation, result —
 * because that edge is the product's claim to traceability. A line of prose
 * saying "saved as #263" makes the reader reconstruct the graph in their head;
 * the arrow shows it.
 *
 * Pure function of the durable slice, so it replays identically from the log.
 */
import { type ReactNode } from 'react';
import type { ToolCallViewProps } from '@deepseek-ai/dsh-client-ui-tool/client';
export declare function AlgoRunRow({ block }: ToolCallViewProps): ReactNode;
