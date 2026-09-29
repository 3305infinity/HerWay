import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export async function GET() {
  try {
    const publicModelsDir = path.join(process.cwd(), 'public', 'models');
    const localGlbPath = path.join(publicModelsDir, 'avatar.glb');

    const animDest = path.join(publicModelsDir, 'animations.glb');
    const animSource = path.join(process.cwd(), '..', 'ai-avatar', 'ai-avatar-frontend', 'public', 'models', 'animations.glb');
    if (!fs.existsSync(animDest) && fs.existsSync(animSource)) {
      try { fs.copyFileSync(animSource, animDest); } catch {}
    }

    // 1. If public/models/avatar.glb exists, read and serve it
    if (fs.existsSync(localGlbPath)) {
      const buffer = fs.readFileSync(localGlbPath);
      return new NextResponse(buffer, {
        headers: {
          'Content-Type': 'model/gltf-binary',
          'Cache-Control': 'public, max-age=31536000, immutable',
        },
      });
    }

    // 2. Candidate source files in the project workspace
    const sourceCandidates = [
      path.join(process.cwd(), '..', 'ai-avatar', 'ai-avatar-frontend', 'public', 'models', '64f1a714fe61576b46f27ca2.glb'),
      path.join(process.cwd(), '..', 'ai-avatar', 'ai-avatar-frontend', 'public', 'models', '6732180e5415f67e067badca.glb'),
    ];

    for (const candidate of sourceCandidates) {
      if (fs.existsSync(candidate)) {
        try {
          if (!fs.existsSync(publicModelsDir)) {
            fs.mkdirSync(publicModelsDir, { recursive: true });
          }
          fs.copyFileSync(candidate, localGlbPath);
          const animSource = path.join(path.dirname(candidate), 'animations.glb');
          const animDest = path.join(publicModelsDir, 'animations.glb');
          if (fs.existsSync(animSource) && !fs.existsSync(animDest)) {
            fs.copyFileSync(animSource, animDest);
          }
        } catch (copyErr) {
          console.warn('Failed to copy avatar model to public folder:', copyErr);
        }

        const buffer = fs.readFileSync(candidate);
        return new NextResponse(buffer, {
          headers: {
            'Content-Type': 'model/gltf-binary',
            'Cache-Control': 'public, max-age=31536000, immutable',
          },
        });
      }
    }

    return NextResponse.json({ error: 'Avatar model file not found' }, { status: 404 });
  } catch (err) {
    console.error('Error serving avatar model:', err);
    return NextResponse.json({ error: 'Internal server error loading avatar model' }, { status: 500 });
  }
}
