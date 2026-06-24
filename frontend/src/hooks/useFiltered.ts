import { useMemo } from "react";

type FilterValue = string | number | boolean | null | undefined;

export function useFiltered<T>(
  items: readonly T[],
  query: string,
  getValues: (item: T) => readonly FilterValue[],
): T[] {
  return useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return [...items];
    return items.filter((item) =>
      getValues(item).some((value) => String(value ?? "").toLowerCase().includes(needle)),
    );
  }, [getValues, items, query]);
}
