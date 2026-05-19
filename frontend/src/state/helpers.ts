export function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function createDebouncedRefresh(ms = 100): (loader: () => Promise<void>) => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (loader) => {
    clearTimeout(timer);
    timer = setTimeout(() => void loader(), ms);
  };
}
