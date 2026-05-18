import { useCallback, useEffect, useState } from "react";

const SNACKBAR_MS = 2200;

/** Hook that copies text to the clipboard and manages a transient snackbar.
 *
 * Returns `{ copy, snackbarText }`. The snackbar message auto-dismisses after
 * ~2s. Relies on `navigator.clipboard`, which is available in all modern
 * browsers served over https or localhost.
 */
export default function useClipboard({ successMessage, errorMessage }) {
  const [snackbarText, setSnackbarText] = useState(null);

  useEffect(() => {
    if (!snackbarText) return undefined;
    const timer = setTimeout(() => setSnackbarText(null), SNACKBAR_MS);
    return () => clearTimeout(timer);
  }, [snackbarText]);

  const copy = useCallback(
    async (text) => {
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        setSnackbarText(successMessage(text));
      } catch {
        setSnackbarText(errorMessage);
      }
    },
    [successMessage, errorMessage],
  );

  return { copy, snackbarText };
}
