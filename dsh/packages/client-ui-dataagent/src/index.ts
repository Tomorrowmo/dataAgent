/**
 * Node half of the RLab Cortex browser plugin.
 *
 * A client plugin still needs a Node-side entry: the host scans `dsh.client`
 * on the package and serves the browser bundle, while this module is what the
 * loader resolves on the server. All behaviour lives in `./client`.
 *
 * @module @rlab/dsh-client-ui-dataagent
 */

/** Cordis plugin name used by loader diagnostics. */
export const name = 'client-ui-dataagent'

/**
 * No host-side services: the browser half registers the tool views. The empty
 * body keeps the entry a valid Cordis plugin so the composition can list it.
 */
export function apply(): void {}
