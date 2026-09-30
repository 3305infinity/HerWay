'use client';
import { cleanText, fetchCityName } from '@/lib/utils';
import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Button } from './ui/button';
import {
  CircleX,
  Nfc,
  CalendarDays,
  FileUser,
  PersonStanding,
  MapPin,
  TrendingUp,
  Loader2,
  Check,
  Sparkles,
  ArrowLeft,
} from 'lucide-react';
import CustomTimeline from './Timeline';
import toast from 'react-hot-toast';

interface Post {
  _id: string;
  Name: string;
  Location: string;
  'Preferred way of contact': string;
  'Contact info': string;
  'Frequency of domestic violence': string;
  'Relationship with perpetrator': string;
  'Severity of domestic violence': string;
  'Nature of domestic violence': string;
  'Impact on children': string;
  'Culprit details': string;
  'Other info': string;
  status: string;
}

function PostDetail({ id }: { id: string }) {
  const router = useRouter();
  const [post, setPost] = useState<Post | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [city, setCity] = useState<string | null>(null);
  const [isCreatingCase, setIsCreatingCase] = useState(false);

  useEffect(() => {
    const fetchPostById = async () => {
      try {
        const response = await fetch(`/api/postbyid/${id}`);

        if (!response.ok) {
          throw new Error('Failed to fetch post');
        }

        const data = await response.json();
        setPost(data);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'An unknown error occurred'
        );
      }
    };

    fetchPostById();
  }, [id]);

  useEffect(() => {
    if (post) {
      const cleanLoc = cleanText(post.Location);
      const [lat, lng] = cleanLoc.split(',').map(Number);

      const fetchCity = async () => {
        try {
          const cityName = await fetchCityName(lat, lng);
          setCity(cityName);
        } catch (err) {
          console.error('Failed to fetch city name:', err);
        }
      };

      fetchCity();
    }
  }, [post]);

  if (error) {
    return <div>Error: {error}</div>;
  }

  if (!post) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 size={24} className="animate-spin" />
      </div>
    );
  }
  const cleanLoc = cleanText(post.Location);
  const [lat, lng] = cleanLoc.split(',').map(Number);
  const mapUrl = `https://www.google.com/maps/embed/v1/place?key=${process.env.NEXT_PUBLIC_MAP_KEY}&q=${lat},${lng}`;

  const handleCloseIssue = async (issueId: string) => {
    try {
      const response = await fetch('/api/closeIssue', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ issueId }),
      });

      if (!response.ok) {
        throw new Error('Failed to close issue');
      }

      // const data = await response.json();
      toast.success('Issue closed successfully');
      setPost((prevPost) =>
        prevPost ? { ...prevPost, status: 'closed' } : null
      );
    } catch (error) {
      console.error(error);
    }
  };

  const handleCreateCase = async () => {
    if (!post || isCreatingCase) return;
    setIsCreatingCase(true);
    try {
      const summary = [
        post['Nature of domestic violence'] ? `Nature: ${cleanText(post['Nature of domestic violence'])}` : '',
        post['Severity of domestic violence'] ? `Severity: ${cleanText(post['Severity of domestic violence'])}` : '',
        post['Frequency of domestic violence'] ? `Frequency: ${cleanText(post['Frequency of domestic violence'])}` : '',
        post['Culprit details'] ? `Culprit: ${cleanText(post['Culprit details'])}` : '',
        post['Other info'] ? `Additional Details: ${cleanText(post['Other info'])}` : '',
      ]
        .filter(Boolean)
        .join('. ');

      const res = await fetch('/api/v2/cases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: 'anonymous',
          situation_text: summary || 'Reported situation from community post',
          category: 'domestic_violence',
          location: post.Location ? { display_name: cleanText(post.Location) } : null,
          title: `Case from Report: ${cleanText(post.Name || 'Community Incident').slice(0, 40)}`,
        }),
      });

      if (res.ok) {
        const newCase = await res.json();
        const caseId = newCase.id || newCase._id;
        toast.success('Guided Safety Case created!');
        router.push(`/cases/${caseId}`);
      } else {
        toast.error('Failed to create case');
      }
    } catch {
      toast.error('Error creating case');
    } finally {
      setIsCreatingCase(false);
    }
  };

  return (
    <div className="flex flex-col h-full max-w-6xl w-full mx-auto p-5 space-y-4">
      <div className="flex items-center justify-between">
        <Link
          href="/community"
          className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 transition-colors"
        >
          <ArrowLeft size={14} />
          <span>Back to Community</span>
        </Link>
      </div>

      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between w-full gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold">{post.Name}</h1>
          {post.Location && (
            <p className="text-xs text-muted-foreground mt-1">📍 {cleanText(post.Location)}</p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Button
            onClick={handleCreateCase}
            disabled={isCreatingCase}
            className="flex items-center space-x-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <Sparkles size={16} />
            <span>{isCreatingCase ? 'Creating case…' : 'Create Guided Case'}</span>
          </Button>

          {post.status === 'pending' && (
            <Button
              onClick={() => handleCloseIssue(post._id)}
              variant="outline"
              className="flex items-center space-x-2"
            >
              <CircleX size={16} />
              <span>Close Issue</span>
            </Button>
          )}
          {post.status === 'closed' && (
            <Button className="flex items-center space-x-2 bg-green-500 text-white hover:bg-green-600">
              <Check size={16} />
              <span>Issue Closed</span>
            </Button>
          )}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3 mt-5">
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">Preferred way of contact</h2>
            <Nfc className="text-gray-700" />
          </div>
          <p>{post['Preferred way of contact']}</p>
          <p>{post['Contact info']}</p>
        </div>
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">
              Frequency of domestic violence
            </h2>
            <CalendarDays className="text-gray-700" />
          </div>
          <p>{post['Frequency of domestic violence']}</p>
          <p>{post['Relationship with perpetrator']}</p>
        </div>
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">
              Nature of domestic violence
            </h2>
            <PersonStanding className="text-gray-700" />
          </div>
          <p>{post['Impact on children']}</p>
          <p>{post['Severity of domestic violence']}</p>
        </div>
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">Culprit details</h2>
            <FileUser className="text-gray-700" />
          </div>
          <p>{post['Culprit details']}</p>
          <p>{post['Other info']}</p>
        </div>
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">Location</h2>
            <MapPin className="text-gray-700" />
          </div>
          <p>{post['Location']}</p>
          <p>{city}</p>
        </div>
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">Current Status</h2>
            <TrendingUp className="text-gray-700" />
          </div>
          <p>{post.status}</p>
          <p>
            Resolve this issue by contacting the person and providing necessary
          </p>
        </div>
      </div>
      <div className="flex items-center w-full mt-5 gap-3">
        <div className="rounded-md w-full p-1 border border-gray-400">
          <iframe
            width="100%"
            height="360"
            className="rounded-md border border-gray-300"
            style={{ border: 0 }}
            loading="lazy"
            allowFullScreen
            referrerPolicy="no-referrer-when-downgrade"
            src={mapUrl}
          ></iframe>
        </div>
        <div className="rounded-md h-[370px] w-full p-4 border border-gray-400">
          <h1 className="text-center text-lg font-semibold mb-4">
            Recent Activities
          </h1>
          <CustomTimeline />
        </div>
      </div>
    </div>
  );
}

export default PostDetail;
