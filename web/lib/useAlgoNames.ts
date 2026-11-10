'use client';

// Chinese name + one-line description for algorithm slugs shown in the flow
// graph and the answer's step list (改进清单-5 · 7). Built-ins come from ALGO_ZH;
// custom / AI algorithms use the name and description they were saved with.

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { algoLabel } from '@/lib/algoMeta';

type Info = { name: string; description: string };
let cache: Promise<Record<string, Info>> | null = null;

function load(): Promise<Record<string, Info>> {
  if (!cache) {
    cache = api.listAlgorithms()
      .then((list) => Object.fromEntries(list.map((a) => [a.slug, { name: a.name, description: a.description }])))
      .catch(() => { cache = null; return {}; });
  }
  return cache;
}

export function useAlgoNames() {
  const [lib, setLib] = useState<Record<string, Info>>({});
  useEffect(() => { let on = true; load().then((m) => { if (on) setLib(m); }); return () => { on = false; }; }, []);
  return (slug?: string) => algoLabel(slug, slug ? lib[slug]?.name : undefined, slug ? lib[slug]?.description : undefined);
}

/** Same, but also accepts an algorithm's saved (English) name — e.g. the step
 *  label stored in a result's lineage — and maps it back to the Chinese name. */
export function useAlgoLookup() {
  const [lib, setLib] = useState<Record<string, Info>>({});
  useEffect(() => { let on = true; load().then((m) => { if (on) setLib(m); }); return () => { on = false; }; }, []);
  return (slugOrName: string) => {
    if (lib[slugOrName] || algoLabel(slugOrName).name !== slugOrName) return algoLabel(slugOrName, lib[slugOrName]?.name, lib[slugOrName]?.description);
    const slug = Object.keys(lib).find((k) => lib[k].name === slugOrName);
    return slug ? algoLabel(slug, lib[slug].name, lib[slug].description) : { name: slugOrName, desc: '' };
  };
}
