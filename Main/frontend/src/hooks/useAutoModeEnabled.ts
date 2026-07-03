import { useAutoModeStatus } from "./useAutoModeStatus";

export function useAutoModeEnabled(): boolean {
  const { enabled } = useAutoModeStatus();
  return enabled;
}
