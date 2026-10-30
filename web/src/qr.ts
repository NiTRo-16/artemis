// Reading QR codes. Everything here runs in the visitor's browser: the image is never uploaded.
import jsQR from "jsqr";

export function decodePixels(data: Uint8ClampedArray, width: number, height: number): string | null {
  // Screenshots can be light on dark, so both ways are tried.
  return jsQR(data, width, height, { inversionAttempts: "attemptBoth" })?.data || null;
}

export type QrKind = "upi" | "link" | "other";

/** Only web addresses count as links, so a code holding javascript:, tel: or Wi-Fi details is just shown as text. */
export function classifyQr(text: string): QrKind {
  const value = text.trim();
  if (/^upi:/i.test(value)) return "upi";
  if (/^https?:\/\/\S+$/i.test(value) || /^www\.\S+$/i.test(value)) return "link";
  if (/^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(\/\S*)?$/i.test(value)) return "link";
  return "other";
}

// A photo can be huge, and a small code in a big screenshot can be missed at one size but found at another.
const WIDTHS = [1600, 800, 2400, 400];

export async function decodeFile(file: Blob): Promise<string | null> {
  const image = await createImageBitmap(file);
  try {
    const longest = Math.max(image.width, image.height);
    for (const target of WIDTHS) {
      if (target > longest && target !== WIDTHS[0]) continue;
      const scale = Math.min(1, target / longest);
      const width = Math.max(1, Math.round(image.width * scale));
      const height = Math.max(1, Math.round(image.height * scale));
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) return null;
      // A white backing, so transparent images read as dark code on light.
      context.fillStyle = "#fff";
      context.fillRect(0, 0, width, height);
      context.drawImage(image, 0, 0, width, height);
      const found = decodePixels(context.getImageData(0, 0, width, height).data, width, height);
      if (found) return found;
    }
    return null;
  } finally {
    image.close();
  }
}
