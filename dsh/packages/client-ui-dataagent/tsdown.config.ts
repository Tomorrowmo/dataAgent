/**
 * Browser-bundle config for the RLab client plugin.
 *
 * dsh's client bundles are not ordinary ESM: each is a closure-factory artifact
 * that calls `window.__ModuleLoader__.load({id, factory})` and resolves shared
 * packages through the loader's module table rather than importing them. Two
 * copies of a runtime service would break its identity, so the externals list
 * is a correctness contract, not a size optimisation.
 *
 * Rather than restate that contract, this reuses dsh's own preset from the
 * local checkout. It is the one place where being out-of-tree costs something:
 * the path below must point at the dsh source tree.
 */
import { clientBundle } from '../../../../../GitBubProj/DeepseekHarness/packages/client/tsdown.client.ts'

export default clientBundle('@rlab/dsh-client-ui-dataagent', ['lib/types/index.js'])
