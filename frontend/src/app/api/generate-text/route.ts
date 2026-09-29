import axios from 'axios';
import { NextResponse } from 'next/server';

interface GenerateTextRequestData {
  name: string;
  phone: string;
  location: { lat: number; lng: number };
  occurrenceDuration: number;
  frequency: number;
  visibleInjuries: 'Yes' | 'No';
  preferredContact: string[];
  culprit: string;
  currentSituation: string;
}

export async function POST(req: Request) {
  try {
    const data: GenerateTextRequestData = await req.json();
    const updatedData = {
      name: data.name,
      phone: data.phone,
      location: data.location,
      duration_of_abuse: data.occurrenceDuration,
      frequency_of_incidents: data.frequency,
      preferred_contact_method: data.preferredContact,
      culprit_description: data.culprit,
      current_situation: data.currentSituation,
    };

    const res = await axios.post(
      `${process.env.NEXT_PUBLIC_BACKEND_URL}/text-generation`,
      updatedData
    );
    return NextResponse.json(
      {
        gemini_response: res.data.gemini_response,
        gemma_response: res.data.gemma_response,
      },
      { status: 200 }
    );
  } catch (error) {
    console.error('Image generation failed:', error);
    return NextResponse.json(
      { error: 'Failed to generate image' },
      { status: 500 }
    );
  }
}
