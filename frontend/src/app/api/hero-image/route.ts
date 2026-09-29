import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export async function GET() {
  try {
    const publicImagesDir = path.join(process.cwd(), 'public', 'images');
    const localImagePath = path.join(publicImagesDir, 'haven-hero.jpg');

    // 1. If public/images/haven-hero.jpg exists, serve it
    if (fs.existsSync(localImagePath)) {
      const buffer = fs.readFileSync(localImagePath);
      return new NextResponse(buffer, {
        headers: {
          'Content-Type': 'image/jpeg',
          'Cache-Control': 'public, max-age=31536000, immutable',
        },
      });
    }

    // 2. Find the generated artifact image in the gemini artifacts folder
    const sourceCandidates = [
      'C:\\Users\\Nishtha\\.gemini\\antigravity-ide\\brain\\4ff46878-d77c-4d09-b404-a508d4ab4cc8\\haven_hero_editorial_1790674030248.jpg',
    ];

    for (const candidate of sourceCandidates) {
      if (fs.existsSync(candidate)) {
        try {
          if (!fs.existsSync(publicImagesDir)) {
            fs.mkdirSync(publicImagesDir, { recursive: true });
          }
          fs.copyFileSync(candidate, localImagePath);
        } catch (copyErr) {
          console.warn('Failed to copy hero image to public folder:', copyErr);
        }

        const buffer = fs.readFileSync(candidate);
        return new NextResponse(buffer, {
          headers: {
            'Content-Type': 'image/jpeg',
            'Cache-Control': 'public, max-age=31536000, immutable',
          },
        });
      }
    }

    return NextResponse.json({ error: 'Image not found' }, { status: 404 });
  } catch (err) {
    console.error('Error serving hero image:', err);
    return NextResponse.json({ error: 'Failed to load image' }, { status: 500 });
  }
}
