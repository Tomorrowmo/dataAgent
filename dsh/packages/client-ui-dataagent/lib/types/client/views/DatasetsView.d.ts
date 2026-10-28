/**
 * The dataset view: a lineage tree, not a list.
 *
 * The methodology this product settled on is that **data is a lineage DAG**.
 * A flat list of names loses the one fact that makes a derived number
 * trustworthy — where it came from and what was done to it. So sources are
 * roots, derived datasets nest under their parent, and each edge is labelled
 * with the operation that created it.
 *
 * Read-only on purpose. Running an algorithm from here would mutate state
 * outside the session log; that belongs to a tool call.
 */
import { type ReactNode } from 'react';
export declare function DatasetsView(): ReactNode;
