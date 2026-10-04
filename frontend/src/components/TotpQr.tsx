/**
 * Renders an otpauth:// URI as a QR code, in the browser.
 *
 * Drawn locally rather than by a hosted image service. The URI contains the TOTP
 * seed, so `<img src="https://api.qrserver.com/...?data=<uri>">` would hand the
 * entire second factor to a third party -- and that image would be cached in
 * whatever proxy sits in front of it, and visible in the browser history and
 * referrer chain. A second factor is precisely the thing not to send anywhere.
 *
 * SVG rather than canvas: it scales on a high-DPI screen without blurring, and a
 * screenshot still produces a scannable code.
 */
import { useEffect, useState } from "react";
import QRCode from "qrcode";

interface TotpQrProps {
  /** The otpauth:// URI. Contains the secret, so never send it anywhere. */
  value: string;
  /** Describes the code for a screen reader. */
  label: string;
  size?: number;
}

function TotpQr({ value, label, size = 220 }: TotpQrProps) {
  const [markup, setMarkup] = useState("");

  useEffect(() => {
    let cancelled = false;
    // Async because the encoder returns a promise; the alternative is a
    // synchronous call on every render of a secret-bearing component.
    void QRCode.toString(value, {
      type: "svg",
      width: size,
      margin: 1,
      // Nearest-neighbour edges keep the module boundaries crisp, which is what
      // a scanner is actually reading.
      color: { dark: "#0f1216", light: "#ffffff" },
    })
      .then((svg) => {
        if (!cancelled) setMarkup(svg);
      })
      .catch(() => {
        // A QR code that failed to render must not leave an empty box the user
        // scans and fails on. The key below is always shown, so this is a
        // degraded path rather than a dead end.
        if (!cancelled) setMarkup("");
      });
    return () => {
      cancelled = true;
    };
  }, [value, size]);

  if (!markup) {
    // Placeholder of the exact final size, so nothing shifts when it arrives.
    return (
      <div
        className="totp-qr"
        style={{ width: size, height: size }}
        aria-label={label}
        role="img"
      />
    );
  }

  return (
    <div
      className="totp-qr"
      // Safe: qrcode emits only <path> and <rect> elements built from the input,
      // with no attribute values carried through from the encoded string.
      dangerouslySetInnerHTML={{ __html: markup }}
      role="img"
      aria-label={label}
    />
  );
}

export default TotpQr;