/** One-shot speech-to-text via Web Speech API (HTTPS; Chrome/Safari/Edge typical). */

type BrowserSpeechRecognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((ev: { results: { 0: { 0: { transcript: string } } } }) => void) | null;
  onerror: ((ev: { error: string; message?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type RecCtor = new () => BrowserSpeechRecognition;

export async function listenOnce(opts?: {
  lang?: string;
  signal?: AbortSignal;
}): Promise<string> {
  if (typeof window === "undefined") {
    throw new Error("Speech recognition is only available in the browser.");
  }
  const w = window as unknown as {
    SpeechRecognition?: RecCtor;
    webkitSpeechRecognition?: RecCtor;
  };
  const SpeechRec = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!SpeechRec) {
    throw new Error("Speech recognition is not supported in this browser.");
  }

  const lang = opts?.lang ?? "en-US";

  return new Promise((resolve, reject) => {
    const recognition = new SpeechRec();
    let settled = false;
    let sawResult = false;

    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      try {
        fn();
      } catch {
        /* ignore */
      }
    };

    recognition.lang = lang;
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (ev) => {
      sawResult = true;
      const t = ev.results[0]?.[0]?.transcript?.trim?.() ?? "";
      settle(() =>
        t.length ? resolve(t) : reject(new Error("No speech detected — try again.")),
      );
    };

    recognition.onerror = (ev) => {
      const msg =
        ev.message ||
        (
          ({
            no_speech: "No speech detected — try again or speak a bit louder.",
            not_allowed: "Microphone blocked — enable permissions in browser settings.",
            aborted: "Recording stopped.",
          }) as Record<string, string>
        )[ev.error] ||
        `Speech error (${ev.error})`;
      settle(() => reject(new Error(msg)));
    };

    recognition.onend = () => {
      if (settled) return;
      if (!sawResult) {
        settle(() => reject(new Error("No speech captured — tap the mic again.")));
      }
    };

    if (opts?.signal) {
      if (opts.signal.aborted) {
        settle(() => reject(new Error("aborted")));
        return;
      }
      opts.signal.addEventListener(
        "abort",
        () => {
          try {
            recognition.stop();
          } catch {
            /* ignore */
          }
          settle(() => reject(new Error("aborted")));
        },
        { once: true },
      );
    }

    try {
      recognition.start();
    } catch (e) {
      settle(() =>
        reject(e instanceof Error ? e : new Error("Could not start microphone capture.")),
      );
    }
  });
}
