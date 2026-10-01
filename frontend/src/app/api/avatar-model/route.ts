import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

/**
 * Serves the Niva avatar model from `public/models/avatar.glb`.
 *
 * The previous version also reached outside the app directory
 * (`../ai-avatar/...`) and copied files in at request time. Those paths do not
 * exist in a deployed build, so this route behaved differently in development
 * and production. It now serves only what is actually bundled, and reports a
 * clean 404 otherwise — the avatar component already has a calm fallback.
 */
export async function GET() {
  try {
    const glbPath = path.join(process.cwd(), 'public', 'models', 'avatar.glb');

    if (!fs.existsSync(glbPath)) {
      return NextResponse.json(
        { error: 'Avatar model is not bundled with this deployment.' },
        { status: 404 },
      );
    }

    const buffer = fs.readFileSync(glbPath);
    return new NextResponse(new Uint8Array(buffer), {
      headers: {
        'Content-Type': 'model/gltf-binary',
        'Cache-Control': 'public, max-age=31536000, immutable',
      },
    });
  } catch (err) {
    console.error('Error serving avatar model:', err);
    return NextResponse.json({ error: 'Could not load the avatar model.' }, { status: 500 });
  }
}
