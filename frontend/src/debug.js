import {createContext, useContext} from 'react';
export const DebugContext = createContext(false);
export const useDebug = () => useContext(DebugContext);
export const sourceBadge = (badge, debug) => {
  const label = badge || 'Source record';
  if (debug) return label;
  if (/^AI\b|^ai_/i.test(label)) return 'AI reviewed';
  if (/^(Human|Entered by|Reviewed by)\b/i.test(label)) return 'Human reviewed';
  return label;
};
