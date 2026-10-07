/**
 * Media upload — POST /media/uploads (multipart/form-data, field `file`).
 * Server validates MIME + magic bytes (JPEG/PNG/WebP/HEIC/HEIF) and a 10 MB cap.
 *
 * Returns the raw storage path for submission payloads (photo_urls /
 * attachment_urls) plus a display-ready absolute URL via mediaUrl().
 */

import { apiClient, mediaUrl } from './client';
import { EvidenceItem } from '../types';

const dataUrlToBlob = (dataUrl: string): { blob: Blob; mime: string } => {
  const [head, body] = dataUrl.split(',');
  const mime = head.match(/data:(.*?)(;|$)/)?.[1] || 'image/jpeg';
  const binary = atob(body);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return { blob: new Blob([bytes], { type: mime }), mime };
};

const MIME_EXT: Record<string, string> = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
  'image/heic': 'heic',
  'image/heif': 'heic',
};

export interface UploadedMedia {
  /** Raw backend path (e.g. /uploads/x.jpg) — what payloads should submit. */
  path: string;
  /** Absolute URL for <img> rendering. */
  url: string;
  key: string;
}

export async function uploadMediaApi(
  input: string | File | Blob,
  filename?: string
): Promise<UploadedMedia> {
  let blob: Blob;
  let name = filename;

  if (typeof input === 'string') {
    const { blob: b, mime } = dataUrlToBlob(input);
    blob = b;
    name = name || `photo-${Date.now()}.${MIME_EXT[mime] || 'jpg'}`;
  } else {
    blob = input;
    name = name || (input instanceof File ? input.name : `photo-${Date.now()}.jpg`);
  }

  const form = new FormData();
  form.append('file', blob, name);

  const res = await apiClient<{ url: string; key: string }>('/media/uploads', {
    method: 'POST',
    body: form,
    timeoutMs: 60000,
  });

  return { path: res.url, url: mediaUrl(res.url), key: res.key };
}

/** Shape used by submission payloads — send the raw backend path. */
export const toEvidenceItem = (m: UploadedMedia, filename?: string | null): EvidenceItem => ({
  id: m.key,
  url: m.path,
  filename: filename ?? m.path.split('/').pop() ?? null,
  uploaded_at: null,
});
