import { createContext } from "react";

/** Chat actions the message components need (retry lives outside assistant-ui's model). */
export const ChatActionsContext = createContext<{ retry: (assistantId: string) => void; isRunning: boolean }>({
  retry: () => {},
  isRunning: false,
});
