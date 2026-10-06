"use client";

import React, { useEffect, useState } from "react";
import { imageMeta, isStorageImage, thumbUrl, type ImageMeta, type PreviewWidth } from "@/lib/media";
import { useZoomScale } from "./ZoomPan";
import { cx } from "./ui";

/**
 * Blur-up image for station photos (19 MB PNGs): a ~1 KB blurred placeholder shows at once,
 * a JPEG preview fades in over it, and the original replaces it only once zoomed in past
 * `fullAtZoom` (inside a ZoomPan). Other URLs (data:, blob:) render as a plain <img>.
 *
 * `layout="flow"` sizes itself from the image (width 100%, height from the aspect ratio);
 * `layout="fill"` covers its positioned parent. `fit` is the object-fit of the pictures.
 * `onMeta` reports the ORIGINAL pixel size (for drawing boxes in original coordinates).
 */
export function ProgressiveImage({
  src,
  alt,
  layout = "fill",
  fit = "object-contain",
  previewWidth = 1600,
  fullAtZoom = 1.8,
  className,
  imgClassName,
  onMeta,
  onError,
}: {
  src: string;
  alt: string;
  layout?: "flow" | "fill";
  fit?: "object-contain" | "object-cover";
  previewWidth?: PreviewWidth;
  fullAtZoom?: number;
  className?: string;
  imgClassName?: string;
  onMeta?: (size: { width: number; height: number }) => void;
  onError?: () => void;
}) {
  const progressive = isStorageImage(src);
  const zoom = useZoomScale();
  const [meta, setMeta] = useState<{ src: string; meta: ImageMeta | null } | null>(null);
  const [loaded, setLoaded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!progressive) return;
    let live = true;
    imageMeta(src)
      .then((m) => {
        if (!live) return;
        setMeta({ src, meta: m });
        onMeta?.({ width: m.width, height: m.height });
      })
      .catch(() => live && setMeta({ src, meta: null }));
    return () => {
      live = false;
    };
    // onMeta is a callback prop: re-run only when the picture changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, progressive]);

  if (!progressive) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt={alt}
        draggable={false}
        className={cx(layout === "fill" ? "absolute inset-0 size-full" : "w-full block", fit, className, imgClassName)}
        onLoad={(e) => onMeta?.({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })}
        onError={onError}
      />
    );
  }

  const m = meta?.src === src ? meta.meta : undefined;
  const markLoaded = (url: string) => setLoaded((l) => (l[url] ? l : { ...l, [url]: true }));
  // A cached (or server-rendered) image can finish before React attaches onLoad.
  const watch = (url: string) => (el: HTMLImageElement | null) => {
    if (el?.complete && el.naturalWidth > 0) queueMicrotask(() => markLoaded(url));
  };
  const preview = thumbUrl(src, previewWidth);
  const wantFull = zoom >= fullAtZoom;
  const shown = loaded[preview] ? preview : null;
  const pic = cx("absolute inset-0 size-full select-none", fit, imgClassName);
  return (
    <div
      className={cx("overflow-hidden", layout === "fill" ? "absolute inset-0" : "relative w-full", className)}
      style={layout === "flow" ? { aspectRatio: m ? `${m.width} / ${m.height}` : "4 / 3" } : undefined}
    >
      {m && !shown && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={m.lqip} alt="" aria-hidden draggable={false} className={cx(pic, "blur-xl scale-110")} />
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        ref={watch(preview)}
        src={preview}
        alt={alt}
        draggable={false}
        className={cx(pic, "transition-opacity duration-300", shown ? "opacity-100" : "opacity-0")}
        onLoad={() => markLoaded(preview)}
        onError={onError}
      />
      {wantFull && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          ref={watch(src)}
          src={src}
          alt=""
          aria-hidden
          draggable={false}
          className={cx(pic, "transition-opacity duration-300", loaded[src] ? "opacity-100" : "opacity-0")}
          onLoad={() => markLoaded(src)}
        />
      )}
    </div>
  );
}
