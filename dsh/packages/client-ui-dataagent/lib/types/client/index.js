/**
 * RLab Cortex browser half: keyed tool views for the data-analysis tools.
 *
 * The generic tool row prints whatever text a tool rendered. That is fine for a
 * shell command, but it flattens the two things this product exists to keep
 * distinct: a finding that was *assessed and failed* versus an item that could
 * *not be assessed at all*. A wall of text lets 未评定 read like a pass, which
 * is precisely the failure mode the wind-tunnel module was built to prevent.
 *
 * So these views are not decoration. They encode, in form, the distinction the
 * domain refuses to blur.
 *
 * Views are pure functions of the durable call/result slice, so they replay
 * identically from the session log and never consult live services.
 *
 * @module
 */
import { AlgoRunRow } from "./AlgoRunRow.js";
import { WtFindingsRow } from "./WtFindingsRow.js";
import { Workbench } from "./Workbench.js";
/** Required services: the keyed tool-view registry. */
export const inject = ['slots'];
/**
 * Register the keyed tool views.
 *
 * Both keys name tools this product registered itself, so registration is
 * purely additive — nothing shipped by dsh is taken over.
 */
export function apply(ctx) {
    ctx.slots.inject('tool.call.toolview', () => ctx.slots.register({ name: 'tool.call.toolview', key: 'algo_run' }, AlgoRunRow));
    ctx.slots.inject('tool.call.toolview', () => ctx.slots.register({ name: 'tool.call.toolview', key: 'wt_findings' }, WtFindingsRow));
    // The workbench goes into `shell.overlay` because that is the only seat the
    // frame documents as additive. `sidebar` and `conversation` are
    // single-occupancy: registering there would replace the shell's own column
    // and take its inner seats down with it.
    ctx.slots.inject('shell.overlay', () => ctx.slots.register({ name: 'shell.overlay', id: 'rlab-workbench' }, Workbench));
}
