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

const SPEECH_ERR: Record<string, string> = {
  "no-speech": "No speech detected — try again or speak a bit louder.",
  "not-allowed": "Microphone blocked — allow microphone for this site in the browser address bar (site settings), then try again.",
  aborted: "Recording stopped.",
  network: "Speech recognition could not reach the network service. Check your connection and try again.",
  "audio-capture": "No microphone was found or it could not be opened.",
  "service-not-allowed":
    "Chrome blocked the speech service (often fixed by allowing the mic, using HTTPS, or disabling conflicting extensions). Try again after allowing microphone access.",
  "bad-grammar": "Speech recognition configuration error — try again.",
  "language-not-supported": "This language is not supported for speech recognition.",
};

function speechErrorMessage(ev: { error: string; message?: string }): string {
  const code = ev.error || "";
  const fromCode = SPEECH_ERR[code];
  if (fromCode) return fromCode;
  const raw = (ev.message || "").trim();
  const lower = raw.toLowerCase();
  if (lower.includes("permission check") || lower.includes("permission denied")) {
    return (
      "Speech recognition could not verify microphone permission. " +
      "Use HTTPS (or localhost), click the lock icon → Site settings → Microphone → Allow, then try again. " +
      "If it still fails, allow the mic once via any voice button, or try a normal (non-guest) Chrome window."
    );
  }
  return raw || `Speech error (${code || "unknown"})`;
}

/** Prime mic permission before Web Speech API — reduces Chrome “permission check has failed” failures. */
async function ensureMicrophonePermission(): Promise<void> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
  } catch (e: unknown) {
    const name = e instanceof DOMException ? e.name : "";
    if (name === "NotAllowedError" || name === "PermissionDeniedError") {
      throw new Error(
        "Microphone access was denied. In Chrome: click the lock or tune icon in the address bar → Site settings → Microphone → Allow, then try again.",
      );
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      throw new Error("No microphone was found on this device.");
    }
    if (name === "NotReadableError" || name === "TrackStartError") {
      throw new Error("The microphone is in use or unavailable. Close other apps using the mic and try again.");
    }
    throw new Error(e instanceof Error ? e.message : "Could not open the microphone.");
  }
}

export async function listenOnce(opts?: {
  lang?: string;
  signal?: AbortSignal;
}): Promise<string> {
  if (typeof window === "undefined") {
    throw new Error("Speech recognition is only available in the browser.");
  }
  if (!window.isSecureContext) {
    throw new Error(
      "Speech recognition only works on a secure origin. Use HTTPS in production, or http://localhost for local development (not a raw LAN IP over HTTP).",
    );
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

  await ensureMicrophonePermission();

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
      const msg = speechErrorMessage(ev);
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
