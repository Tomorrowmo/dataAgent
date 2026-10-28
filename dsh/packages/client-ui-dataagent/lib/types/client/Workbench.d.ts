/**
 * The workbench: RLab's own surface inside the harness shell.
 *
 * dsh's frame is deliberately chat-centric — `sidebar` and `conversation` are
 * single-occupancy slots, so registering into either would REPLACE the shell's
 * own column rather than add to it. `shell.overlay` is the one seat documented
 * as additive ("a frame-wide surface of your own"), so that is where a product
 * with its own views belongs.
 *
 * The layer is click-through by default; only the launcher and the open panel
 * take pointer events, so the conversation underneath stays fully usable when
 * the workbench is closed.
 */
import { type ReactNode } from 'react';
export declare function Workbench(): ReactNode;
