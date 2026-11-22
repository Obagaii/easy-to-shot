import { useEffect, useState } from 'react';

const reducedMotionQuery = '(prefers-reduced-motion: reduce)';

export function useReducedMotion(): boolean {
  const [isReduced, setIsReduced] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(reducedMotionQuery).matches
  );

  useEffect(() => {
    const media = window.matchMedia(reducedMotionQuery);
    const handleChange = (event: MediaQueryListEvent) => setIsReduced(event.matches);
    media.addEventListener('change', handleChange);
    return () => media.removeEventListener('change', handleChange);
  }, []);

  return isReduced;
}
