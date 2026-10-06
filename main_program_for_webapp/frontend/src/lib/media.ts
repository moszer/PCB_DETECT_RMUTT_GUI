/** Fast previews of station images (/api/media): LQIP placeholder, JPEG previews, original size. */

export interface ImageMeta {
  width: number;
  height: number;
  /** Tiny blurred-up placeholder (data: URL, ~1 KB). */
  lqip: string;
}

export const isStorageImage = (url: string | null | undefined): url is string => !!url && url.startsWith("/api/storage/");

export type PreviewWidth = 480 | 1600 | 2400;

export const thumbUrl = (url: string, w: PreviewWidth) => `/api/media/thumb?w=${w}&url=${encodeURIComponent(url)}`;

const metaCache = new Map<string, Promise<ImageMeta>>();

/** Original size + placeholder of a stored image (one request per image per page load). */
export function imageMeta(url: string): Promise<ImageMeta> {
  let p = metaCache.get(url);
  if (!p) {
    p = fetch(`/api/media/meta?url=${encodeURIComponent(url)}`).then((r) => {
      if (!r.ok) throw new Error(`meta ${r.status}`);
      return r.json() as Promise<ImageMeta>;
    });
    p.catch(() => metaCache.delete(url)); // let a later render retry
    metaCache.set(url, p);
  }
  return p;
}
