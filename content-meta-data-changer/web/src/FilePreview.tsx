import { useEffect, useState } from "react";
import { previewUrl } from "./api/client";

type FilePreviewProps = {
  fileId: string | null;
  alt: string;
};

/**
 * Thumbnail for an uploaded file. The API renders images directly and grabs the
 * first frame for videos, so one endpoint covers both.
 */
export default function FilePreview({ fileId, alt }: FilePreviewProps) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // A new file in the same slot deserves a fresh attempt.
  useEffect(() => {
    setFailed(false);
    setLoaded(false);
  }, [fileId]);

  if (!fileId) {
    return null;
  }

  if (failed) {
    return <div className="slot-preview slot-preview-empty">No preview available</div>;
  }

  return (
    <div className={`slot-preview-frame${loaded ? " slot-preview-ready" : ""}`}>
      {/* use-credentials so the session cookie travels when the API lives on
          another domain; the endpoint enforces session ownership. */}
      <img
        className="slot-preview"
        src={previewUrl(fileId)}
        alt={alt}
        crossOrigin="use-credentials"
        onLoad={() => setLoaded(true)}
        onError={() => setFailed(true)}
      />
    </div>
  );
}
